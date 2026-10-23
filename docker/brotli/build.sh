#!/bin/sh
set -eux
curl -fSL --retry 3 --retry-all-errors "https://codeload.github.com/google/brotli/tar.gz/${BROTLI_COMMIT}" -o /build/source.tar.gz
echo "$BROTLI_SHA256 */build/source.tar.gz" | sha256sum -c -
mkdir /build/source
tar -xzf /build/source.tar.gz --strip-components=1 -C /build/source
multiarch="$(dpkg-architecture -qDEB_HOST_MULTIARCH)"
arch="$(dpkg --print-architecture)"
cmake -S /build/source -B /build/compiled -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX=/usr -DCMAKE_INSTALL_LIBDIR="lib/$multiarch" \
    -DCMAKE_C_FLAGS='-O2 -fstack-protector-strong -D_FORTIFY_SOURCE=2' \
    -DCMAKE_SHARED_LINKER_FLAGS='-Wl,-z,relro,-z,now' -DBUILD_SHARED_LIBS=ON
cmake --build /build/compiled --parallel "$(nproc)"
(cd /build/compiled && ctest --output-on-failure --no-tests=error --parallel "$(nproc)")
DESTDIR=/build/installed cmake --install /build/compiled
pkg=/build/package
mkdir -p "$pkg/DEBIAN" "$pkg/usr/lib/$multiarch" "$pkg/usr/bin" "$pkg/usr/share/doc/libbrotli1"
cp -a /build/installed/usr/lib/"$multiarch"/libbrotli*.so.* "$pkg/usr/lib/$multiarch/"
gcc -O2 -fstack-protector-strong -Wl,-z,relro,-z,now \
    -I/build/source/c/include /build/verify.c -L/build/compiled \
    -lbrotlienc -lbrotlidec -lbrotlicommon -o "$pkg/usr/bin/tgi-verify-brotli"
LD_LIBRARY_PATH="$pkg/usr/lib/$multiarch" "$pkg/usr/bin/tgi-verify-brotli" "$BROTLI_VERSION"
cp /build/source/LICENSE "$pkg/usr/share/doc/libbrotli1/copyright"
printf 'version=%s\ncommit=%s\nsha256=%s\n' "$BROTLI_VERSION" "$BROTLI_COMMIT" "$BROTLI_SHA256" > "$pkg/usr/share/doc/libbrotli1/tgi-source.txt"
cat > "$pkg/DEBIAN/control" <<EOF
Package: libbrotli1
Source: brotli
Version: $BROTLI_PACKAGE_VERSION
Architecture: $arch
Maintainer: TGI image builder <noreply@takanengroup.fi>
Section: libs
Priority: optional
Multi-Arch: same
Depends: libc6 (>= 2.34)
Description: Brotli runtime libraries built from pinned upstream security release
 Replaces Debian's unfixed Brotli with ABI-compatible upstream $BROTLI_VERSION.
EOF
printf 'activate-noawait ldconfig\n' > "$pkg/DEBIAN/triggers"
mkdir /out
dpkg-deb --root-owner-group --build "$pkg" /out/libbrotli1.deb
