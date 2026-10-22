# Upstream provenance

Source: https://github.com/docker-library/wordpress
Commit: `2d7faab7fb71508e6854cdbed948c195957f279e`
Path: `latest/php8.4/apache/Dockerfile`
WordPress: `7.1.3` (stable channel at inspection).

`Dockerfile` here is the unmodified source. `../docker-entrypoint.sh` and
`../wp-config-docker.php` are unmodified files from the same commit. The GPL-2.0
license is retained here; downloaded WordPress contains its own GPL license.
PHP base licensing: https://github.com/docker-library/php and the image's
bundled notices (PHP license and Debian packages' individual licenses).

The shared `../Dockerfile` parameterizes FROM and adds provenance labels.
Imagick 3.8.1 is compiled from its official release commit with a pinned SHA256
instead of relying on the PECL download service. Its build context is `docker/`. Runtime initialization stays upstream.
Review upstream updates together; do not automatically replace the entrypoint
without checking volume, environment and ownership behavior. PHP 8.5 uses the
same packaging; runtime tests must pass separately before release.

PHP bases are pinned by manifest digest. Debian apt packages are resolved at
build time, so a rebuild is not byte-for-byte reproducible: increment the build
revision, retain the resulting digest and SBOM, and re-run security gates.

Imagick source: https://github.com/Imagick/imagick/releases/tag/3.8.1
Commit: `70087bab33eab913e99ac77d64d04d1a2fd0b7b0`
Archive SHA256: `bccb748bc34edf22b1102659eaae9afe79af097dd444d82f397ef87f0b6798a0`.
The PHP version placeholder is replaced with `3.8.1` as PECL packaging does.

TGI r2 additionally builds phpredis 6.3.0 from the official source commit
`df4fab2de7fc327c54c94a13af2b9542e4fbd720` (archive SHA256
`79ecabd899e50a6efa56d9fc28a987a25d78deecc32fdd0fa9840b1b3d83740e`).
Its license is copied into the final image. Version/checksum/commit are declared
in versions/versions.yaml; PHP and WordPress packaging stay shared.
