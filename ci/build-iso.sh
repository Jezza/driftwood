#!/bin/bash
# Build the Driftwood (Plasma) ISO inside a Debian trixie container.
# Used by .github/workflows/build.yml; also runnable by hand:
#   docker run --rm --privileged -v "$PWD:/src" -w /src debian:trixie ci/build-iso.sh
# Output: out/Driftwood_Plasma_<version>_x86-64.{iso,packages,iso.sha256}
set -euo pipefail
cd "$(dirname "$0")/.."
src=$PWD

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends \
    live-build debootstrap ca-certificates gnupg wget curl \
    xorriso squashfs-tools mtools dosfstools cpio zstd \
    grub-efi-amd64-bin grub-pc-bin isolinux syslinux-common >/dev/null
echo "live-build $(dpkg-query -W -f='${Version}' live-build)"

# live-build writes into its config dir; build in a scratch copy so the
# checkout stays clean and re-runs start fresh.
work=${WORK:-/build}
mkdir -p "$work"
find "$work" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
cp -a "$src/plasma/." "$work/"
cd "$work"

VERSION=${VERSION:-13.$(date -u +%y%m%d)}
export VERSION
start=$(date +%s)
./build.sh -i
echo "build took $(( ($(date +%s) - start) / 60 )) min"

mkdir -p "$src/out"
name="Driftwood_Plasma_${VERSION}_x86-64"
mv "$name.iso" "$name.packages" "$src/out/"
cp build.log "$src/out/$name.build.log"
cd "$src/out"
sha256sum "$name.iso" > "$name.iso.sha256"
ls -l
