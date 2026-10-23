# Automatic PHP patch releases

The watcher on `tgi-ab-1` (`192.168.31.201`) checks every 15 minutes. It uses
Python, Git, SSH and systemd, with no AI service, email or Docker access.
GitHub Actions builds and runs both AMD64 and ARM64 images natively.

Published public moving aliases:

```bash
docker pull ghcr.io/codenamey/tgi-wordpress:8.4-latest
docker pull ghcr.io/codenamey/tgi-wordpress:8.5-latest
```

The existing `:8.4` and `:8.5` aliases identify the same passing releases.
Each exact `php<patch>-wp<core>-r<revision>` tag remains immutable. There is no
unversioned `latest` alias and no automatic change between PHP branches.
Pulling an image does not replace running containers. Future production rollout
groups are france, german and finland; no production rollout is enabled.

## Update policy

`scripts/prepare_update.py` compares the configured branches with official PHP
source releases. Only patch increases in enabled branches are accepted.
Source SHA256, source-package signing fingerprints, pinned packaging revision,
branch identity, supported architectures and security minimums are checked.
Changing a checksum for an existing PHP release, downgrading, adding a branch,
changing signing keys/recipe or changing WordPress/extensions/security policy
requires manual review. Debian-base drift alone does not trigger a PHP release.
The producer preserves unchanged branches and increments build_revision once.

The watcher clones a fresh temporary repository, prepares only the version lock
and build revision, commits with `[tgi-auto-php-patch] `, verifies the committed
transition and pushes without force. GitHub repeats the transition verification
before allowing the release workflow to build and publish. Unrelated changes
cannot use this automatic publishing path. A failed push is retried from fresh
master at the next interval; changes in an operator checkout are never reset.

The same native build, WordPress/database/Redis/persistence tests, raw Trivy
report gate, digest validation, SBOM and provenance checks apply to automatic
and manual releases. Aliases move only after those gates pass. New critical
findings, expired reviews or upstream build incompatibilities stop publication;
they require an operator to investigate. This automation does not interpret
new advisories or invent source patches, and does not automatically update
WordPress core, WP-CLI, Redis, Brotli or Debian-only rebuilds.

## Runtime tooling and security configuration

The r4 build includes WP-CLI 2.12.0 from its official release artifact, verified
against SHA256 `ce34ddd838f7351d6759068d09793f26755463b4a4610a5a5c0a97b68220d85c`.
Integration tests read core version and database-backed site options using
WP-CLI as www-data. Commands requiring an external mysql/mysqldump executable
(such as `wp db export`) need a separately provisioned database client. The
optional Debian MariaDB client was excluded after it added blocking scanner
findings; no scanner exceptions were added for it.

```bash
docker exec -u www-data -w /var/www/html CONTAINER wp --info
docker exec -u www-data -w /var/www/html CONTAINER wp plugin list
docker exec -u www-data -w /var/www/html CONTAINER wp core version
```

`docker/99-security.ini` disables `session.upload_progress.enabled` before
request parsing for CVE-2026-115560. CLI and Apache HTTP verification check the
setting. It survives container recreation because it is included in the image.
WP-CLI is available for operators; the updater does not run plugin/core updates
or modify existing WordPress volumes.

## Installation and operation

For a replacement machine after host failure, follow the complete Finnish
[installation and recovery procedure](updater-recovery-fi.md). It covers a fresh
Debian host, required packages, staging the installer inputs, replacing the
repository deploy key, read-only checks, timer activation and release recovery.

The installer creates the unprivileged `tgi-wp-updater` system user, installs the
watcher under `/opt/tgi-wordpress-updater/`, and stores state in
`/var/lib/tgi-wordpress-updater/` (0700). The user has no Docker group membership.
The systemd service limits CPU/memory, filesystem writes and privileges.

An Ed25519 deploy key is generated on that host. Its private key stays there;
the public key is registered with write access to `codenamey/tgi-wordpress` only.
No personal GitHub token or GHCR write credential is copied to the host. A
repository write key is still a credential: revoke it in repository Deploy Keys
when retiring the watcher. GitHub SSH host keys are pinned using GitHub's
HTTPS-authenticated metadata. Publishing uses short-lived GITHUB_TOKEN on the
GitHub runners. The existing `ghcr-release` environment also applies; adding
required reviewers there will intentionally pause automatic publishing.

Inspect and run on the watcher host:

```bash
systemctl list-timers tgi-wordpress-updater.timer
systemctl status tgi-wordpress-updater.service
journalctl -u tgi-wordpress-updater.service -n 50 --no-pager
cat /var/lib/tgi-wordpress-updater/status.json
systemctl start tgi-wordpress-updater.service
```

Read-only commissioning check:

```bash
runuser -u tgi-wp-updater -- python3 /opt/tgi-wordpress-updater/watch_updates.py --check
```

Stop future checks with `systemctl disable --now tgi-wordpress-updater.timer`.
This does not affect published images or running customer containers.
Release run status is recorded in status.json; failures appear in the journal
and the service's exit status. There are no email notifications.
