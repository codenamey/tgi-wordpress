#!/bin/sh
# Run as root in a staging directory with the watcher and both unit files.
set -eu
test "$(id -u)" = 0
cd "$(dirname "$0")"
if ! getent passwd tgi-wp-updater >/dev/null; then
    useradd --system --user-group --home-dir /var/lib/tgi-wordpress-updater --shell /usr/sbin/nologin tgi-wp-updater
fi
install -d -o root -g root -m 0755 /opt/tgi-wordpress-updater
install -d -o tgi-wp-updater -g tgi-wp-updater -m 0700 /var/lib/tgi-wordpress-updater
install -o root -g root -m 0644 watch_updates.py /opt/tgi-wordpress-updater/watch_updates.py
install -o root -g root -m 0644 tgi-wordpress-updater.service tgi-wordpress-updater.timer /etc/systemd/system/
if [ ! -f /var/lib/tgi-wordpress-updater/deploy_key ]; then
    runuser -u tgi-wp-updater -- ssh-keygen -q -t ed25519 -N '' \
        -C tgi-wordpress-updater-tgi-ab-1 -f /var/lib/tgi-wordpress-updater/deploy_key
fi
# Pin host keys from GitHub's HTTPS-authenticated metadata, rather than TOFU.
python3 - <<'PY'
import json
from pathlib import Path
import urllib.request
req = urllib.request.Request('https://api.github.com/meta', headers={'User-Agent': 'tgi-wordpress-updater-installer'})
with urllib.request.urlopen(req, timeout=30) as response:
    keys = json.load(response)['ssh_keys']
if not keys or any(not k.startswith(('ssh-ed25519 ', 'ecdsa-sha2-nistp256 ', 'ssh-rsa ')) for k in keys):
    raise ValueError('Unexpected GitHub SSH host key metadata')
path = Path('/var/lib/tgi-wordpress-updater/known_hosts')
path.write_text(''.join('github.com ' + key + '\n' for key in keys))
path.chmod(0o644)
PY
systemd-analyze verify /etc/systemd/system/tgi-wordpress-updater.service /etc/systemd/system/tgi-wordpress-updater.timer
systemctl daemon-reload
printf 'Installed. Register deploy_key.pub in the repository, test --check, then enable the timer.\n'
