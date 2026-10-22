# Historical r1 local validation — 21 October 2026

This report covers the earlier r1 images without Redis. The r2 Redis addition
requires its own CI validation; do not treat this report as r2 test evidence.
The untriaged critical blocking status below was later reviewed on 22 October;
see security.md and security/reviews.json for the scoped, expiring decisions.

Both PHP branches were compiled locally from official signed source releases. The final images were checked by executing PHP in CLI and through Apache HTTP, not by relying on tags or labels.

| Local image | PHP | WordPress | Tested platform |
|---|---|---|---|
| `tgi-wordpress:php8.4.27-wp7.1.3-r1` | 8.4.27 | 7.1.3 | linux/arm64 |
| `tgi-wordpress:php8.5.12-wp7.1.3-r1` | 8.5.12 | 7.1.3 | linux/arm64 |

## Image identities

These are local image configuration IDs, not registry manifest digests. No registry release was executed.

- PHP 8.4: `sha256:6f8ae6d2f1f4a6dc88a1244ed7c9b458e1ea0282d25746d580351157efe05ca4`
- PHP 8.5: `sha256:0a5b8f981f1ba8fe68b3a26e74f1e014a489c61b07a28bc1fdabde3148a819e6`

## Architecture and changed files

- `docker/php-source/`: shared parameterized official PHP Apache source-build recipe, original recipe, unmodified helper scripts and license.
- `docker/Dockerfile`: shared WordPress packaging atop compiled PHP; unmodified official entrypoint and wp-config template; original upstream recipe and licenses retained.
- `versions/versions.yaml`, `versions/lock.json`: enabled branches, security minimums, source checksums/signing keys, pinned Debian digest and packaging revisions. PHP 9.2 remains explicitly disabled.
- `scripts/`: source resolution, local builds, actual version verification, disposable integration tests, scans, bounded local verification, upstream observation and explicitly authorized release helper.
- `tests/`: eight unit tests and disposable database/Apache/volume compatibility checks.
- `.github/`: native architecture matrix CI, six-hourly review PR observations, manual gated GHCR release, Dependabot for Actions.
- `README.md`, `docs/`: developer interface, architecture, security policy, tagging, canary deployment and rollback.

Packaging revisions: WordPress `2d7faab7fb71508e6854cdbed948c195957f279e`; PHP `e3eaff845f7a9f7259c31da54dce0320b47a3bbd`. Imagick 3.8.1 uses official commit `70087bab33eab913e99ac77d64d04d1a2fd0b7b0` and a SHA256-pinned source archive, avoiding PECL download failures.

## Executed checks

- Source SHA256 and GPG verification passed for PHP 8.4.27 and 8.5.12; original source-build logs retained under artifacts/source-build-*.log.
- Both final images: actual PHP/WordPress versions, required extensions, Apache HTTP, PHP version through HTTP, real database installation/query, DB environment variables, CONFIG_EXTRA, preserved custom content/configuration/core files after recreation, custom command behavior.
- Eight unit tests passed, including rejection of vulnerable/disabled versions and missing source checksums, platform validation and selecting the latest php.net source without a prebuilt PHP image.
- Python and shell syntax passed; workflow YAML parsed locally; tracked Git diff whitespace check passed.
- Trivy 0.76.1 scans and CycloneDX SBOM generated for both final ARM64 images.
- Upstream observation exercised against official PHP, WordPress and Debian sources. Observation preserves the accepted lock.

## Scan findings

Both scans reported the same severity totals and critical findings. These are scanner findings; exploitability has not been adjudicated.

| Severity | Findings per image |
|---|---:|
| LOW | 1107 |
| HIGH | 143 |
| MEDIUM | 840 |
| UNKNOWN | 103 |
| CRITICAL | 2 |

| Critical finding | Package | Installed version | Fixed version reported |
|---|---|---|---|
| CVE-2026-6653 | libxml2 | `2.12.7+dfsg+really2.9.14-2.1+deb13u3` | None |
| CVE-2026-93221 | linux-libc-dev | `6.12.113-1` | None |

The original PHP vulnerabilities CVE-2026-109618 and CVE-2026-109619 are fixed by the verified PHP source versions, according to the [official PHP advisory](https://www.php.net/archive/2026.php#2026-10-21-5). Scanner absence alone is not used as proof of that fix. The separate critical findings above block release under scripts/scan.sh and the release workflow. No exception is approved.

## Unexecuted work and limits

- Runtime builds/tests completed on local ARM64. AMD64/ARM64 Debian base manifests were verified, but an AMD64 final image was not built or run locally. CI is configured to validate each architecture natively.
- GitHub Actions were prepared and locally parsed, but were not pushed or run on GitHub. The known critical findings would block their security gate.
- No images were published; no final multi-platform registry digest, release SBOM attestation or provenance attestation exists yet. Those are configured in the approved release workflow.
- GHCR owner/destination/visibility, protected release environment and package access must be confirmed before publishing. Existing Git history and the supplied task file were preserved; implementation remains uncommitted.
- Apt packages are resolved at build time; retain final digests and SBOM for each approved release. Persistent WordPress volumes keep their existing core files. Third-party site plugins/themes were not tested.

## Canary and rollback commands

See [deployment.md](deployment.md) for the operator command sequence and [rollback.md](rollback.md) for recovery. There is no real canary image reference yet because no registry digest has been published or approved. Do not substitute a local image ID for a registry digest. After filling in an approved Compose image reference and an actual canary project/domain, the documented sequence is:

```bash
cd /path/to/canary-compose-project
docker compose config --quiet
docker compose pull wordpress
docker compose up -d --no-deps wordpress
docker compose exec -T wordpress php -r 'echo PHP_VERSION, PHP_EOL;'
docker compose logs --tail=100 wordpress
curl --fail --silent --show-error https://canary.example.invalid/ >/dev/null
```

Back up and test recovery of both database and WordPress volume first. A container rollback does not reverse database migrations or modified persistent core files.

Machine-readable evidence: `artifacts/local-results.json`, `verified-*.json`, `integration-*.json`, `trivy-*.json`, `sbom-*.json`; build/test logs are retained beside them.
