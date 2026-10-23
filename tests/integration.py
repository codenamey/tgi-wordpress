#!/usr/bin/env python3
"""Disposable local Docker integration. Only random tgi-test-* resources cleaned."""
import importlib.util
import base64
import json
from pathlib import Path
import secrets
import subprocess
import sys
import time
import urllib.request

spec = importlib.util.spec_from_file_location('builder', Path(__file__).resolve().parents[1] / 'scripts/builder.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
branch = sys.argv[1]
image = sys.argv[2] if len(sys.argv) > 2 else b.image(branch)
prefix = 'tgi-test-' + secrets.token_hex(6)
network, volume, db, web, cache = [prefix + suffix for suffix in ('-net', '-data', '-db', '-web', '-redis')]
password = secrets.token_hex(24)
redis_password = secrets.token_hex(24)
containers = []
host_port = ''

def docker(*args, capture=False):
    return b.run('docker', *args, capture=capture)

def start():
    global host_port
    containers.append(web)
    docker('run', '-d', '--name', web, '--network', network, '-p', '127.0.0.1:' + host_port + ':80',
           '-v', volume + ':/var/www/html', '-e', 'WORDPRESS_DB_HOST=' + db,
           '-e', 'WORDPRESS_DB_USER=wordpress', '-e', 'WORDPRESS_DB_PASSWORD=' + password,
           '-e', 'WORDPRESS_DB_NAME=wordpress', '-e', 'WORDPRESS_CONFIG_EXTRA=define("TGI_TEST", "works");', image)
    port = docker('port', web, '80/tcp', capture=True).strip().rsplit(':', 1)[1]
    host_port = port
    url = 'http://127.0.0.1:' + port
    for _ in range(90):
        try:
            with urllib.request.urlopen(url + '/wp-admin/install.php', timeout=3) as res:
                if res.status == 200 and b'WordPress' in res.read():
                    return url
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError('Apache/WordPress initialization did not become ready')

try:
    docker('network', 'create', network)
    docker('volume', 'create', volume)
    containers.append(db)
    docker('run', '-d', '--name', db, '--network', network,
           '-e', 'MARIADB_RANDOM_ROOT_PASSWORD=1', '-e', 'MARIADB_DATABASE=wordpress',
           '-e', 'MARIADB_USER=wordpress', '-e', 'MARIADB_PASSWORD=' + password, 'mariadb:11.4')
    containers.append(cache)
    docker('run', '-d', '--name', cache, '--network', network, 'redis:7.4-alpine',
           'redis-server', '--requirepass', redis_password, '--save', '', '--appendonly', 'no')
    url = start()
    redis_code = '$r = new Redis(); $r->connect(' + json.dumps(cache) + ',6379,5); $r->auth(' + json.dumps(redis_password) + ');'
    redis_code += '''$r->setOption(Redis::OPT_SERIALIZER,Redis::SERIALIZER_PHP);
if (!$r->setex('tgi-test', 60, ['value'=>42]) || $r->get('tgi-test') !== ['value'=>42]) exit(10);
$r->del('tgi-test'); echo 'redis-ok';'''
    assert docker('exec', web, 'php', '-r', redis_code, capture=True) == 'redis-ok'
    # Invoke bundled WordPress installer in PHP: real DB connection and schema creation.
    code = 'define("WP_INSTALLING", true); define("WP_SITEURL", ' + json.dumps(url) + '); define("WP_HOME", ' + json.dumps(url) + ');' + '''require '/var/www/html/wp-load.php';
require_once ABSPATH.'wp-admin/includes/upgrade.php';
if (TGI_TEST !== 'works' || DB_NAME !== 'wordpress' || DB_USER !== 'wordpress') exit(2);
wp_install('TGI disposable test', 'testadmin', 'test@example.invalid', false, '', 'temporary-test-password');
if (!is_blog_installed()) exit(3);
echo 'installed';'''
    result = docker('exec', '-u', 'www-data', web, 'php', '-r', code, capture=True)
    assert 'installed' in result
    assert docker('exec', '-u', 'www-data', web, 'wp', 'core', 'version', capture=True).strip() == b.WP
    assert docker('exec', '-u', 'www-data', web, 'wp', 'option', 'get', 'blogname', capture=True).strip() == 'TGI disposable test'
    with urllib.request.urlopen(url, timeout=10) as res:
        assert res.status == 200 and b'TGI disposable test' in res.read()
    runtime = '<?php require __DIR__."/wp-load.php"; echo PHP_VERSION."|".TGI_TEST."|".$wpdb->get_var("SELECT 1")."|".phpversion("redis")."|".(ini_get("session.upload_progress.enabled") ? "enabled" : "disabled");'
    docker('exec', '-u', 'www-data', web, 'php', '-r',
           'file_put_contents("tgi-runtime.php", base64_decode("' + base64.b64encode(runtime.encode()).decode() + '"));')
    with urllib.request.urlopen(url + '/tgi-runtime.php', timeout=10) as res:
        actual_runtime = res.read().decode()
        assert actual_runtime == b.locked(branch)['version'] + '|works|1|' + b.config()['extensions']['redis']['version'] + '|disabled', repr(actual_runtime)
    docker('exec', '-u', 'www-data', web, 'sh', '-c', 'echo preserved > wp-content/tgi-sentinel; cp wp-config.php wp-content/tgi-config-original')
    # An existing core file must not be refreshed from /usr/src on recreation.
    docker('exec', '-u', 'www-data', web, 'sh', '-c', 'echo "/* preserved core */" >> wp-includes/version.php')
    docker('rm', '-f', web)
    containers.remove(web)
    start()
    docker('exec', web, 'sh', '-c', 'test "$(cat wp-content/tgi-sentinel)" = preserved; cmp wp-config.php wp-content/tgi-config-original; grep -q "preserved core" wp-includes/version.php')
    docker('exec', '-u', 'www-data', web, 'php', '-r', 'require "wp-load.php"; if (!is_blog_installed() || TGI_TEST !== "works") exit(1);')
    # Custom command bypasses installation, as official entrypoint does.
    assert docker('run', '--rm', image, 'sh', '-c', 'printf custom-command', capture=True) == 'custom-command'
    b.save(b.ART / f'integration-{branch}.json', {'image': image, 'passed': True,
        'image_id': json.loads(docker('image', 'inspect', image, capture=True))[0]['Id'],
        'checks': ['apache-http', 'apache-php-version', 'apache-redis-loaded', 'session-upload-progress-disabled', 'wp-cli-core', 'wp-cli-option', 'redis-auth-set-get-ttl', 'db-install', 'db-env', 'config-extra', 'persistent-content', 'persistent-config', 'core-not-overwritten', 'custom-command']})
    print('Integration checks passed: ' + branch)
except Exception:
    for container in containers:
        subprocess.run(['docker', 'logs', '--tail', '60', container], check=False)
    raise
finally:
    for container in reversed(containers):
        subprocess.run(['docker', 'rm', '-f', '-v', container], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'volume', 'rm', volume], check=False, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'network', 'rm', network], check=False, stdout=subprocess.DEVNULL)
