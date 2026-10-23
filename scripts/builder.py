#!/usr/bin/env python3
"""TGI image builder. JSON configuration is also valid YAML 1.2."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / 'versions/versions.yaml'
LOCK = ROOT / 'versions/lock.json'
ART = ROOT / 'artifacts'
UPSTREAM = '2d7faab7fb71508e6854cdbed948c195957f279e'
WP = '7.1.3'
PHP_UPSTREAM = 'e3eaff845f7a9f7259c31da54dce0320b47a3bbd'


def read(path):
    return json.loads(Path(path).read_text())


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, indent=2, sort_keys=True) + '\n')
    temp.replace(path)


def run(*args, capture=False, timeout=None):
    return subprocess.run([str(a) for a in args], check=True, text=True,
                          stdout=subprocess.PIPE if capture else None, timeout=timeout).stdout


def fetch(url, headers=None):
    req = urllib.request.Request(url, headers={'User-Agent': 'tgi-wordpress-builder', **(headers or {})})
    with urllib.request.urlopen(req, timeout=60) as response:
        data = response.read()
        return json.loads(data), data


def config():
    cfg = read(CONFIG)
    if type(cfg['build_revision']) is not int or cfg['build_revision'] < 1:
        raise ValueError('build_revision must be a positive integer')
    redis = cfg['extensions']['redis']
    if (not re.fullmatch(r'\d+\.\d+\.\d+', redis['version'])
            or not re.fullmatch(r'[0-9a-f]{40}', redis['commit'])
            or not re.fullmatch(r'[0-9a-f]{64}', redis['sha256'])):
        raise ValueError('Redis needs an exact stable version, commit and SHA256')
    brotli = cfg['brotli']
    if (not re.fullmatch(r'\d+\.\d+\.\d+', brotli['version'])
            or not re.fullmatch(r'[0-9a-f]{40}', brotli['commit'])
            or not re.fullmatch(r'[0-9a-f]{64}', brotli['sha256'])
            or brotli['package_version'] != brotli['version'] + '-0+tgi1'):
        raise ValueError('Brotli needs an exact version, commit, SHA256 and matching package version')
    for branch, entry in cfg['php'].items():
        if not re.fullmatch(r'\d+\.\d+', branch):
            raise ValueError('Invalid PHP branch: ' + branch)
        if type(entry['enabled']) is not bool:
            raise ValueError('enabled must be boolean')
        if not entry['platforms'] or any(p not in ('linux/amd64', 'linux/arm64') for p in entry['platforms']):
            raise ValueError('Unsupported platform configuration')
    return cfg


def selected(branch):
    cfg = config()
    if branch not in cfg['php'] or not cfg['php'][branch]['enabled']:
        raise ValueError(f'PHP {branch} is unavailable or explicitly disabled')
    return cfg['php'][branch]


def registry_manifest(repository, tag):
    token, _ = fetch('https://auth.docker.io/token?service=registry.docker.io&scope=repository:library/' + repository + ':pull')
    headers = {'Authorization': 'Bearer ' + token['token'],
               'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json'}
    obj, data = fetch(f'https://registry-1.docker.io/v2/library/{repository}/manifests/{tag}', headers)
    return obj, 'sha256:' + hashlib.sha256(data).hexdigest()


def validate_platforms(manifest, required):
    actual = {m['platform']['os'] + '/' + m['platform']['architecture']
              for m in manifest.get('manifests', []) if 'platform' in m}
    missing = set(required) - actual
    if missing:
        raise ValueError('Missing platforms: ' + ', '.join(sorted(missing)))
    return sorted(actual & set(required))


def resolve(persist=True):
    cfg = config()
    lock = {'schema': 1, 'wordpress': WP, 'wordpress_upstream': UPSTREAM, 'php': {}}
    for branch, entry in cfg['php'].items():
        if not entry['enabled']:
            print(f'Skipping disabled PHP {branch}', file=sys.stderr)
            continue
        release, _ = fetch('https://www.php.net/releases/index.php?json&version=' + branch)
        version = release['version']
        archive = next(item for item in release['source'] if item['filename'] == f'php-{version}.tar.xz')
        if not re.fullmatch(re.escape(branch) + r'\.\d+', version):
            raise ValueError('Not a stable version: ' + version)
        if entry.get('build_from_source'):
            manifest, digest = registry_manifest('debian', 'trixie-slim')
            platforms = validate_platforms(manifest, entry['platforms'])
            source_url = f'https://raw.githubusercontent.com/docker-library/php/{PHP_UPSTREAM}/{branch}/trixie/apache/Dockerfile'
            with urllib.request.urlopen(source_url, timeout=60) as response:
                source = response.read().decode()
            keys = re.search(r'ENV GPG_KEYS (.+)', source)[1]
            if not re.fullmatch(r'[0-9A-F]{40}( [0-9A-F]{40})*', keys):
                raise ValueError('Invalid upstream signing keys')
            lock['php'][branch] = {'version': version, 'base': f'debian:trixie-slim@{digest}',
                'platforms': platforms, 'source_sha256': archive['sha256'],
                'gpg_keys': keys, 'source_commit': PHP_UPSTREAM}
        else:
            tag = version + '-apache-trixie'
            manifest, digest = registry_manifest('php', tag)
            platforms = validate_platforms(manifest, entry['platforms'])
            lock['php'][branch] = {'version': version, 'base': f'php:{tag}@{digest}', 'platforms': platforms}
        print(f'{branch}: {version} {digest} {platforms}', file=sys.stderr)
    if persist:
        save(LOCK, lock)
    return lock


def locked(branch):
    entry = selected(branch)
    lock = read(LOCK)
    if lock['wordpress'] != WP or lock['wordpress_upstream'] != UPSTREAM:
        raise ValueError('WordPress lock does not match vendored runtime')
    data = lock['php'][branch]
    if not re.fullmatch(re.escape(branch) + r'\.\d+', data['version']):
        raise ValueError('PHP lock branch mismatch')
    if tuple(map(int, data['version'].split('.'))) < tuple(map(int, entry.get('minimum_version', '0.0.0').split('.'))):
        raise ValueError('PHP below security minimum; run resolve. Older PHP is blocked.')
    if entry.get('build_from_source'):
        if data.get('source_commit') != PHP_UPSTREAM or not re.fullmatch(r'[0-9a-f]{64}', data.get('source_sha256', '')):
            raise ValueError('Missing verified PHP source lock; run resolve')
        if not re.fullmatch(r'[0-9A-F]{40}( [0-9A-F]{40})*', data.get('gpg_keys', '')):
            raise ValueError('Missing signing fingerprints')
    expected = 'debian:trixie-slim@sha256:' if entry.get('build_from_source') else 'php:' + data['version'] + '-apache-trixie@sha256:'
    if not data['base'].startswith(expected) or not re.fullmatch(r'[0-9a-f]{64}', data['base'][len(expected):]):
        raise ValueError('Base must use verified exact version and immutable digest')
    if set(data['platforms']) != set(entry['platforms']):
        raise ValueError('Platforms changed; resolve lock first')
    return data


def image(branch):
    data = locked(branch)
    return f'tgi-wordpress:php{data["version"]}-wp{WP}-r{config()["build_revision"]}'


def prerequisites():
    run('docker', 'info', capture=True, timeout=30)
    run('docker', 'buildx', 'version', capture=True, timeout=30)


def build_parameters(branch):
    data = locked(branch)
    redis = config()['extensions']['redis']
    extension_args = ['--build-arg', 'REDIS_VERSION=' + redis['version'],
                      '--build-arg', 'REDIS_COMMIT=' + redis['commit'],
                      '--build-arg', 'REDIS_SHA256=' + redis['sha256']]
    for key, value in config()['brotli'].items():
        extension_args += ['--build-arg', 'BROTLI_' + key.upper() + '=' + value]
    ART.mkdir(exist_ok=True)
    dockerfile = ART / 'Dockerfile.source'
    source_recipe = (ROOT / 'docker/php-source/Dockerfile').read_text() if selected(branch).get('build_from_source') else ''
    dockerfile.write_text('ARG PHP_BASE=php-source\n' + (ROOT / 'docker/brotli/Dockerfile').read_text() + '\n' + source_recipe
        + '\n' + (ROOT / 'docker/Dockerfile').read_text().replace('ARG PHP_BASE\n', ''))
    if not selected(branch).get('build_from_source'):
        return extension_args + ['--build-arg', 'DEBIAN_BASE=' + data['base']], dockerfile
    return extension_args + ['--build-arg', 'DEBIAN_BASE=' + data['base'], '--build-arg', 'PHP_SHA256=' + data['source_sha256'],
            '--build-arg', 'PHP_GPG_KEYS=' + data['gpg_keys']], dockerfile


def build(branch):
    data = locked(branch)
    prerequisites()
    revision = run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture=True).strip()
    if run('git', '-C', ROOT, 'status', '--porcelain', capture=True).strip():
        revision += '-dirty'
    extra, dockerfile = build_parameters(branch)
    run('docker', 'buildx', 'build', '--load', '--pull', '--tag', image(branch), '-f', dockerfile, *extra,
        '--build-arg', 'PHP_BASE=' + ('php-source' if selected(branch).get('build_from_source') else data['base']), '--build-arg', 'PHP_VERSION=' + data['version'],
        '--build-arg', 'SOURCE_REVISION=' + revision, '--build-arg', 'BUILD_REVISION=' + str(config()['build_revision']), ROOT / 'docker')
    verify(branch)


def platform_digest(manifest, platform):
    matches = [m for m in manifest.get('manifests', [])
               if m.get('platform', {}).get('os', '') + '/' + m.get('platform', {}).get('architecture', '') == platform
               and m.get('annotations', {}).get('vnd.docker.reference.type') != 'attestation-manifest']
    if len(matches) != 1 or not re.fullmatch(r'sha256:[0-9a-f]{64}', matches[0].get('digest', '')):
        raise ValueError('Expected one valid runtime manifest for ' + platform)
    return matches[0]['digest']


def verify(branch, ref=None, expected_platform=None):
    data = locked(branch)
    ref = ref or image(branch)
    actual = run('docker', 'run', '--rm', ref, 'php', '-r', 'echo PHP_VERSION;', capture=True).strip()
    if actual != data['version']:
        raise ValueError(f'Actual PHP {actual} != expected {data["version"]}')
    wp = run('docker', 'run', '--rm', ref, 'php', '-r',
             'require "/usr/src/wordpress/wp-includes/version.php"; echo $wp_version;', capture=True).strip()
    if wp != WP:
        raise ValueError('Actual WordPress mismatch: ' + wp)
    modules = run('docker', 'run', '--rm', ref, 'php', '-m', capture=True).splitlines()
    missing = set(['bcmath', 'exif', 'gd', 'intl', 'mysqli', 'mysqlnd', 'zip', 'imagick', 'curl',
                   'mbstring', 'dom', 'libxml', 'SimpleXML', 'xml', 'xmlreader', 'xmlwriter',
                   'openssl', 'redis', 'Zend OPcache']) - set(modules)
    if missing:
        raise ValueError('Missing extensions: ' + ', '.join(missing))
    redis_version = run('docker', 'run', '--rm', ref, 'php', '-r', 'echo phpversion("redis");', capture=True).strip()
    if redis_version != config()['extensions']['redis']['version']:
        raise ValueError('Redis extension version mismatch: ' + redis_version)
    brotli = config()['brotli']
    package_version = run('docker', 'run', '--rm', ref, 'dpkg-query', '-W', '-f=${Version}', 'libbrotli1', capture=True).strip()
    if package_version != brotli['package_version']:
        raise ValueError('Brotli package version mismatch: ' + package_version)
    run('docker', 'run', '--rm', ref, 'tgi-verify-brotli', brotli['version'])
    inspect = json.loads(run('docker', 'image', 'inspect', ref, capture=True))[0]
    if inspect['Os'] + '/' + inspect['Architecture'] not in data['platforms']:
        raise ValueError('Final image architecture is not configured')
    if expected_platform and inspect['Os'] + '/' + inspect['Architecture'] != expected_platform:
        raise ValueError('Final image architecture does not match ' + expected_platform)
    save(ART / f'verified-{branch}.json', {'image': ref, 'image_id': inspect['Id'], 'php': actual,
        'wordpress': wp, 'redis': redis_version, 'brotli': brotli, 'modules': modules, 'base': data['base'], 'php_source': data,
        'architecture': inspect['Architecture'], 'repo_digests': inspect.get('RepoDigests', [])})
    print(f'Verified {ref} PHP={actual} WordPress={wp}')


def scan(branch, ref=None, platform=None):
    ART.mkdir(exist_ok=True)
    ref = ref or image(branch)
    suffix = branch + ('-' + platform.split('/')[1] if platform else '')
    platform_args = ['--platform', platform] if platform else []
    run('trivy', 'image', *platform_args, '--format', 'cyclonedx', '--output', ART / f'sbom-{suffix}.json', ref)
    report = ART / f'trivy-{suffix}.json'
    # Preserve every finding; the separate gate records exact, expiring reviews.
    run('trivy', 'image', *platform_args, '--ignorefile', '/dev/null', '--ignore-unfixed=false',
        '--scanners', 'vuln', '--severity', 'UNKNOWN,LOW,MEDIUM,HIGH,CRITICAL',
        '--format', 'json', '--output', report, ref)
    run(sys.executable, ROOT / 'scripts/security_gate.py', report, '--reviews',
        ROOT / 'security/reviews.json', '--output', ART / f'security-{suffix}.json')


def release_context(branch):
    destination = os.environ.get('TGI_REGISTRY_DESTINATION', '')
    if not re.fullmatch(r'ghcr.io/[a-z0-9][a-z0-9-]*/tgi-wordpress', destination):
        raise ValueError('Set the approved GHCR destination; see docs/versioning.md')
    if os.environ.get('TGI_PUBLISH_APPROVAL') != destination:
        raise ValueError('Explicit TGI_PUBLISH_APPROVAL must equal the approved registry destination')
    prerequisites()
    if run('git', '-C', ROOT, 'status', '--porcelain', capture=True).strip():
        raise ValueError('Publish only a clean, committed source state')
    data = locked(branch)
    revision = run('git', '-C', ROOT, 'rev-parse', 'HEAD', capture=True).strip()
    exact = destination + ':' + image(branch).split(':', 1)[1]
    check = subprocess.run(['docker', 'buildx', 'imagetools', 'inspect', exact], text=True, capture_output=True)
    if check.returncode == 0:
        raise ValueError('Immutable release tag already exists: ' + exact)
    if not any(msg in check.stderr.lower() for msg in ['not found', 'manifest unknown']):
        raise ValueError('Could not confirm tag absence: ' + check.stderr)
    return destination, data, revision, exact


def publish(branch, platform=None):
    """Push and validate candidates; native workers leave promotion to a final job."""
    destination, data, revision, exact = release_context(branch)
    platforms = data['platforms']
    if platform:
        if platform not in platforms:
            raise ValueError('Unconfigured release platform: ' + platform)
        native = run('docker', 'version', '--format', '{{.Server.Os}}/{{.Server.Arch}}', capture=True).strip()
        if native != platform:
            raise ValueError('Release worker must run natively on ' + platform)
        platforms = [platform]
    staging = destination + ':candidate-' + revision[:12] + '-php' + branch + '-r' + str(config()['build_revision'])
    if platform:
        staging += '-' + platform.split('/')[1]
    extra, dockerfile = build_parameters(branch)
    metadata = ART / f'build-metadata-{branch}.json'
    run('docker', 'buildx', 'build', '--push', '--pull', '--platform', ','.join(platforms),
        '--provenance=mode=max', '--sbom=true', '--metadata-file', metadata, '-t', staging, '-f', dockerfile, *extra,
        '--build-arg', 'PHP_BASE=' + ('php-source' if selected(branch).get('build_from_source') else data['base']),
        '--build-arg', 'PHP_VERSION=' + data['version'], '--build-arg', 'SOURCE_REVISION=' + revision,
        '--build-arg', 'BUILD_REVISION=' + str(config()['build_revision']), ROOT / 'docker')
    digest = read(metadata)['containerimage.digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Invalid published digest')
    ref = destination + '@' + digest
    manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', '--raw', ref, capture=True))
    validate_platforms(manifest, platforms)
    runtime_refs = {platform: destination + '@' + platform_digest(manifest, platform)
                    for platform in platforms}
    for runtime_platform in platforms:
        os.environ['DOCKER_DEFAULT_PLATFORM'] = runtime_platform
        runtime_ref = runtime_refs[runtime_platform]
        run('docker', 'pull', '--platform', runtime_platform, runtime_ref)
        verify(branch, runtime_ref, expected_platform=runtime_platform)
        run(sys.executable, ROOT / 'tests/integration.py', branch, runtime_ref)
        scan(branch, runtime_ref, runtime_platform)
    if platform:
        arch = platform.split('/')[1]
        for kind in ['verified', 'integration']:
            save(ART / f'{kind}-{branch}-{arch}.json', read(ART / f'{kind}-{branch}.json'))
        save(ART / f'candidate-{branch}-{arch}.json', {
            'source_revision': revision, 'platform': platform, 'reference': ref,
            'runtime_reference': runtime_refs[platform], 'inputs': data,
            'build_revision': config()['build_revision'], 'brotli': config()['brotli'],
            'extensions': config()['extensions']})
        return
    # Candidate references are never production aliases. Promote only after all gates.
    run('docker', 'buildx', 'imagetools', 'create', '-t', exact, '-t', destination + ':' + branch, ref)
    save(ART / f'release-{branch}.json', {'image': exact, 'digest': digest, 'reference': ref,
        'php': data['version'], 'wordpress': WP, 'source_revision': revision, 'platforms': data['platforms'],
        'inputs': data, 'extensions': config()['extensions'], 'brotli': config()['brotli'], 'runtime_references': runtime_refs,
        'security_reviews': read(ROOT / 'security/reviews.json'), 'provenance': True, 'sbom': True})


def promote(branch):
    """Combine native, validated candidate indexes without losing attestations."""
    destination, data, revision, exact = release_context(branch)
    refs, runtime_refs, descriptors = [], {}, set()
    for platform in data['platforms']:
        arch = platform.split('/')[1]
        candidate = read(ART / f'candidate-{branch}-{arch}.json')
        if (candidate['source_revision'] != revision or candidate['platform'] != platform
                or candidate['inputs'] != data or candidate['build_revision'] != config()['build_revision']
                or candidate['brotli'] != config()['brotli'] or candidate['extensions'] != config()['extensions']):
            raise ValueError('Candidate does not match committed release inputs: ' + platform)
        for key in ['reference', 'runtime_reference']:
            if not re.fullmatch(re.escape(destination) + r'@sha256:[0-9a-f]{64}', candidate[key]):
                raise ValueError('Invalid candidate reference')
        manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', '--raw', candidate['reference'], capture=True))
        descriptors.update(m['digest'] for m in manifest['manifests'])
        if destination + '@' + platform_digest(manifest, platform) != candidate['runtime_reference']:
            raise ValueError('Candidate runtime digest mismatch')
        verified = read(ART / f'verified-{branch}-{arch}.json')
        integration = read(ART / f'integration-{branch}-{arch}.json')
        if (verified['image'] != candidate['runtime_reference'] or verified['architecture'] != arch
                or integration['image'] != candidate['runtime_reference'] or integration.get('passed') is not True):
            raise ValueError('Candidate validation evidence mismatch')
        # Re-evaluate the retained raw report under current policy and date.
        report = ART / f'trivy-{branch}-{arch}.json'
        if read(report)['ArtifactName'] != candidate['runtime_reference']:
            raise ValueError('Candidate scan evidence mismatch')
        run(sys.executable, ROOT / 'scripts/security_gate.py', report, '--reviews',
            ROOT / 'security/reviews.json', '--output', ART / f'security-{branch}-{arch}.json')
        refs.append(candidate['reference'])
        runtime_refs[platform] = candidate['runtime_reference']
    staging = destination + ':candidate-' + revision[:12] + '-php' + branch + '-r' + str(config()['build_revision'])
    run('docker', 'buildx', 'imagetools', 'create', '-t', staging, *refs)
    descriptor = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', staging, '--format', '{{json .Manifest}}', capture=True))
    digest = descriptor['digest']
    if not re.fullmatch(r'sha256:[0-9a-f]{64}', digest):
        raise ValueError('Invalid combined candidate digest')
    ref = destination + '@' + digest
    manifest = json.loads(run('docker', 'buildx', 'imagetools', 'inspect', '--raw', ref, capture=True))
    validate_platforms(manifest, data['platforms'])
    if not descriptors.issubset({m['digest'] for m in manifest['manifests']}):
        raise ValueError('Combined index lost a runtime or attestation manifest')
    for platform, runtime_ref in runtime_refs.items():
        if destination + '@' + platform_digest(manifest, platform) != runtime_ref:
            raise ValueError('Combined index changed a validated runtime digest')
    run('docker', 'buildx', 'imagetools', 'create', '-t', exact, '-t', destination + ':' + branch, ref)
    save(ART / f'release-{branch}.json', {'image': exact, 'digest': digest, 'reference': ref,
        'php': data['version'], 'wordpress': WP, 'source_revision': revision, 'platforms': data['platforms'],
        'inputs': data, 'extensions': config()['extensions'], 'brotli': config()['brotli'],
        'runtime_references': runtime_refs, 'security_reviews': read(ROOT / 'security/reviews.json'),
        'provenance': True, 'sbom': True})


def updates():
    # Observe without silently changing the accepted WordPress packaging.
    previous = read(LOCK) if LOCK.exists() else None
    candidate = resolve(persist=False)
    wp, _ = fetch('https://raw.githubusercontent.com/docker-library/wordpress/master/versions.json')
    commit, _ = fetch('https://api.github.com/repos/docker-library/wordpress/commits/master')
    php_commit, _ = fetch('https://api.github.com/repos/docker-library/php/commits/master')
    debian, debian_digest = registry_manifest('debian', 'trixie-slim')
    php_versions, _ = fetch('https://raw.githubusercontent.com/docker-library/php/master/versions.json')
    report = {'php_source_versions': {b: php_versions[b]['version'] for b in config()['php'] if config()['php'][b]['enabled']}, 'candidate_lock': candidate, 'php_changed': candidate != previous,
              'wordpress_latest': wp['latest']['version'], 'wordpress_upstream_head': commit['sha'],
              'php_upstream_head': php_commit['sha'], 'debian_trixie_digest': debian_digest}
    save(ART / 'upstream-observation.json', report)
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['resolve', 'matrix', 'build', 'build-all', 'verify-version', 'test', 'check-updates', 'publish', 'publish-platform', 'promote', 'scan', 'image'])
    parser.add_argument('branch', nargs='?')
    args = parser.parse_args()
    if args.command == 'resolve':
        resolve()
    elif args.command == 'matrix':
        print(json.dumps({'include': [{'php': b, 'platforms': ','.join(e['platforms'])} for b, e in config()['php'].items() if e['enabled']]}))
    elif args.command == 'build-all':
        for b, e in config()['php'].items():
            if e['enabled']: build(b)
            else: print('Skipping disabled PHP ' + b)
    elif args.command == 'check-updates':
        updates()
    else:
        selected(args.branch)
        if args.command == 'build': build(args.branch)
        elif args.command == 'verify-version': verify(args.branch)
        elif args.command == 'image': print(image(args.branch))
        elif args.command == 'test':
            verify(args.branch)
            run(sys.executable, ROOT / 'tests/integration.py', args.branch)
        elif args.command == 'scan':
            scan(args.branch)
        elif args.command == 'publish':
            publish(args.branch)
        elif args.command == 'publish-platform':
            platform = os.environ.get('TGI_RELEASE_PLATFORM', '')
            if not platform:
                raise ValueError('TGI_RELEASE_PLATFORM is required')
            publish(args.branch, platform=platform)
        elif args.command == 'promote':
            promote(args.branch)

if __name__ == '__main__':
    try: main()
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print('ERROR: ' + str(exc), file=sys.stderr)
        sys.exit(1)
