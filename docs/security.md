# Security

The 21 October 2026 PHP advisory fixes CVE-2026-109618 and CVE-2026-109619 in
8.4.27 and 8.5.12. Authority:
https://www.php.net/archive/2026.php#2026-10-21-5
https://github.com/php/php-src/security/advisories/GHSA-w8hw-w9fx-j79w
https://github.com/php/php-src/security/advisories/GHSA-6wmf-4rv5-p3rp

The configuration sets these as minimum patch versions. A fresh build timestamp
or a newer Debian package does not fix the PHP interpreter. Verification executes
PHP_VERSION in the final container and compares it with the lock. Source SHA256
and GPG signature verification must succeed; do not bypass either on failure.

Run Trivy after build and integration tests. All vulnerabilities are reported;
all unreviewed CRITICAL findings block release. The raw scanner report retains
every finding. Exact OS-package reviews in security/reviews.json may defer an
unfixed finding for at most seven days with primary evidence, a reviewer,
package version, distribution scope, rationale and expiry. A newly available
fix, version/distribution drift, unknown critical finding or expiry blocks
release. PHP version minimums cannot be bypassed by these reviews. Known PHP
security minimums are enforced separately because vulnerability databases may lag.
Generate CycloneDX SBOM with scan.sh; release builds must attach provenance and
SBOM and retain final registry digests. A passing scan is not proof that every
possible vulnerability is absent.

WORDPRESS_CONFIG_EXTRA is executable PHP and is trusted configuration, not user
input. Avoid secrets in labels, release metadata or build arguments. Database
credentials are runtime configuration. Integration databases use random passwords
and private temporary Docker networks; HTTP binds only to localhost.

## Reviewed findings, 22 October 2026

### Brotli fix, 23 October 2026

CVE-2026-111497 was newly reported by the release scan against Debian's
libbrotli1 `1.1.0-2+b7`; that package is affected and is never exempted.
Debian has no fixed package at inspection. TGI r3 builds upstream Brotli 1.1.1
commit `db0631dfea829194206d269bc7b25d0908cdb97d`, SHA256
`38f9c17ee36c2e930ce00975b50fcd246a8e5594c1bcf43cd56b14118786b82a`,
as `libbrotli1 1.1.1-0+tgi1`. It replaces the original libraries through dpkg
after the image's apt operations. Upstream CTest must pass; a dynamically linked
helper checks the installed decoder/encoder versions and compression roundtrip
both at build time and in final-image verification on each architecture.
The MIT license and source provenance are installed with the replacement.

The exact replacement package has a scoped, expiring not-affected review because
Debian's unfixed-package advisory can also flag custom fixed versions. This is
upstream patch verification, not an acceptance of the vulnerable Debian package.
Sources: https://security-tracker.debian.org/tracker/CVE-2026-111497 and
https://github.com/google/brotli/releases/tag/v1.1.1 .
Remove the custom build when Debian ships a verified fixed package. Later apt
operations must not downgrade it; re-run final-image verification after changes.

### Existing Debian reviews

- CVE-2026-6653 in Debian 13 libxml2 `2.12.7+dfsg+really2.9.14-2.1+deb13u3`
  remains affected. Debian explicitly calls it a minor/no-dsa denial-of-service
  issue and has no fixed stable package. Its exact version is temporarily
  deferred to ship the independently verified critical PHP RCE fixes. This is
  an explicit risk deferral, not a claim of remediation or non-exploitability.
  Source: https://security-tracker.debian.org/tracker/CVE-2026-6653
- CVE-2026-93221 is in the executable kernel NFS server implementation. The
  matched linux-libc-dev `6.12.113-1` is userspace development headers. The
  not-affected review covers only that header package in this image, never the
  host kernel or an installed linux-image/NFS server package. Host kernel
  security is not assessed here. Sources:
  https://kernel-team.pages.debian.net/kernel-sec/CVE-2026-93221.html
  https://packages.debian.org/trixie/linux-libc-dev

The automated Codex review is recorded verbatim in security/reviews.json and
expires at 2026-10-29 00:00 UTC. No blanket CVE ignore or --ignore-unfixed is used.
The gate writes reviewed and blocking findings separately with a raw report
SHA256 and full review details. Review changes are visible in Git history.
