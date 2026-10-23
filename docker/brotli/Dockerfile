# Build the upstream security release as an auditable replacement Debian package.
ARG DEBIAN_BASE
FROM ${DEBIAN_BASE} AS brotli-build
ARG BROTLI_VERSION
ARG BROTLI_COMMIT
ARG BROTLI_SHA256
ARG BROTLI_PACKAGE_VERSION
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates curl cmake gcc libc6-dev make dpkg-dev
COPY brotli/build.sh brotli/verify.c /build/
RUN sh /build/build.sh
