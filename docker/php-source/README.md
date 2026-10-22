# PHP source build provenance

Official source: https://github.com/docker-library/php
Pinned packaging commit: `e3eaff845f7a9f7259c31da54dce0320b47a3bbd`
Path: `8.4/trixie/apache/`.

`Dockerfile.upstream` is the unmodified official recipe. The helper scripts and
MIT license are copied unchanged. TGI's Dockerfile parameterizes the Debian
base, PHP version, SHA256 and signing keys; COPY paths use this subdirectory.
OPcache activation is conditional because PHP 8.5 builds it in. The matching
8.5 recipe was compared before sharing this implementation.

The final build concatenates this recipe and the WordPress recipe. PHP is built
as an Apache module and CLI, keeping the official extensions, php.ini settings,
Apache configuration, environment and helper script behavior. Download checksum
and GPG verification remain upstream operations; neither may be disabled.
