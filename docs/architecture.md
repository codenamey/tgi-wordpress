# Architecture

The version resolver reads php.net releases JSON for the latest stable patch
and source SHA256 in each enabled branch. Disabled branches are reported.
The resulting lock contains PHP source SHA256, signing fingerprints and a
multi-platform Debian manifest digest. WordPress and PHP packaging revisions
are independently pinned. Review updates to recipes and keys before changing
those revisions.

The build generates `artifacts/Dockerfile.source` from two shared recipes. The
first stage builds PHP against Apache from signed php.net sources, using the
official PHP image recipe. The second stage inherits that stage and reproduces
the official WordPress Apache packaging. No old PHP binary is inherited from a
WordPress image. Build configuration chooses the exact version, checksum and
signing keys. The upstream helper scripts are unmodified. Imagick 3.8.1 is built from its
official release commit and SHA256-pinned archive, avoiding PECL service outages.

PHP recipe upstream: docker-library/php commit
`e3eaff845f7a9f7259c31da54dce0320b47a3bbd`, `8.4/trixie/apache`.
The 8.5 recipe was compared: version, checksum, keys and OPcache activation were
the differences. TGI parameterizes these fields and enables OPcache only if it
is not already built in. PHP and WordPress sources retain their own licenses;
WordPress packaging GPL-2.0 and PHP packaging MIT licenses are bundled.

The Apache entrypoint, WORDPRESS_* and *_FILE environment semantics,
WORDPRESS_CONFIG_EXTRA, ownership and /var/www/html behavior come directly from
docker-library/wordpress. Runtime files have not been rewritten.

A persistent volume with existing core files keeps its core on recreation.
Updating the image updates PHP and the packaged /usr/src/wordpress, but does not
automatically replace an existing site's core. Update WordPress core separately
with backups and application tests. The integration test checks that existing
core, custom files and wp-config.php survive recreation.

Debian apt packages are resolved at build time. The pinned base and PHP sources
make inputs auditable, but do not make builds byte-for-byte reproducible. Record
the final image digest, package SBOM and build revision for each release.
