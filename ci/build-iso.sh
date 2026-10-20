#!/bin/bash
# Build the Driftwood (Plasma) ISO inside a Debian trixie container.
# Used by .github/workflows/build.yml; also runnable by hand:
#   docker run --rm --privileged -v "$PWD:/src" -w /src debian:trixie ci/build-iso.sh
# Output: out/Driftwood_Plasma_<version>_<variant>_x86-64.{iso,packages,iso.sha256}
# VARIANT=amd|nvidia selects plasma/variants/<variant> (default amd).
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
VARIANT=${VARIANT:-amd}
export VERSION VARIANT
start=$(date +%s)
./build.sh -i
echo "build took $(( ($(date +%s) - start) / 60 )) min"

mkdir -p "$src/out"
name="Driftwood_Plasma_${VERSION}_${VARIANT}_x86-64"
mv "$name.iso" "$name.packages" "$src/out/"
cp build.log "$src/out/$name.build.log"
cd "$src/out"
sha256sum "$name.iso" > "$name.iso.sha256"
ls -l

echo "largest files in the ISO:"
xorriso -indev "$name.iso" -find / -type f -exec lsdl 2>/dev/null \
    | awk '{printf "%8.1f MiB  %s\n", $5/1048576, $NF}' | sort -rn | head -15 | tee "$name.contents"
