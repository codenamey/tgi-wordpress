# TGI WordPress

Build patched PHP from official signed sources, then package WordPress with the
unmodified official Apache entrypoint and configuration template. No dependency
on the publication timing of official WordPress or PHP binary images.

Requires Python 3.9+, Docker Engine and Buildx. Build scripts use Python's standard
library. `versions/versions.yaml` uses JSON syntax (valid YAML 1.2).

```bash
./scripts/resolve.sh          # newest stable PHP in each enabled branch; lock SHA256 and Debian digest
./scripts/build.sh 8.4        # compile locked PHP + extensions, package WordPress, verify versions
./scripts/test.sh 8.4         # disposable database + HTTP + persistent volume tests
./scripts/build.sh 8.5
./scripts/test.sh 8.5
./scripts/build-all.sh
./scripts/check-updates.sh    # observation only; accepted lock is preserved
./scripts/scan.sh 8.4         # requires Trivy
```

The current minimum versions are PHP **8.4.27** and **8.5.12**, fixing
[CVE-2026-109618 and CVE-2026-109619](https://www.php.net/archive/2026.php#2026-10-21-5).
Older locks fail closed. Resolve explicitly before rebuilding for new releases;
builds consume the reviewed lock instead of changing versions during a build.
PHP 9.2 is disabled; no availability is implied.

PHP compilation uses the official docker-library/php Apache recipe, source
checksum verification and GPG verification. A shared recipe supports both
branches; OPcache is built in for 8.5 and enabled as an extension for 8.4.
WordPress packaging uses one shared Dockerfile. Upstream GPL/PHP/MIT licenses and original
recipes are retained in `docker/upstream/` and `docker/php-source/`.

```bash
python3 -m unittest discover -s tests -v
python3 scripts/builder.py matrix
```

Build/test evidence is written under `artifacts/` and excluded from Git. Local
image IDs are not published registry manifest digests. `publish.sh` requires an explicit destination and matching authorization, and a
clean committed source tree. The release workflow is manual and environment-gated.

See [architecture](docs/architecture.md), [security](docs/security.md),
[versioning](docs/versioning.md), [deployment](docs/deployment.md) and
[rollback](docs/rollback.md).

The r2 build adds the native **phpredis 6.3.0** extension to both branches. Redis
requires no runtime PHP package installation. The Redis server stays external;
configure WordPress's Redis Object Cache plugin/drop-in with its host, port,
authentication and a unique per-site cache prefix. Existing WordPress volumes
are preserved and plugins/drop-ins are not installed or replaced automatically.
CLI and Apache checks require DOM, libxml, SimpleXML, XML, XMLReader, XMLWriter,
mysqli/mysqlnd and the Redis module. Integration tests include authenticated
Redis set/get with expiry and PHP serialization.

The r3 build additionally replaces Debian's unfixed Brotli package with upstream
**Brotli 1.1.1**, built from a pinned commit and SHA256 to fix CVE-2026-111497.
The final image dynamically checks decoder/encoder versions and a compression
roundtrip. Native AMD64/ARM64 candidates are tested and scanned by digest before
their attested indexes are combined and release aliases are created.
The historical r1 validation predates Redis and Brotli; it is not r3 evidence.
See docs/security.md for time-limited, exact package security reviews.
