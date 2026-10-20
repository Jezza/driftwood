#!/bin/bash
# Build the Driftwood (Plasma) image with live-build (run as root on Debian trixie).
#   ./build.sh -i   ISO image
#   ./build.sh -d   HDD image
# VERSION defaults to <debian major>.<yymmdd>, e.g. 13.261019.
# VARIANT (amd|nvidia, default amd) overlays variants/$VARIANT/ onto this
# directory before configuring.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${VERSION:-13.$(date -u +%y%m%d)}"
VARIANT="${VARIANT:-amd}"
[ -d "variants/$VARIANT" ] || { echo "unknown VARIANT $VARIANT" >&2; exit 1; }
NAME="Driftwood_Plasma_${VERSION}_${VARIANT}"

# Live root filesystem: xz with 1 MiB blocks. Smallest ISO; costs some
# decompression speed in the live session only (installed systems are
# copied out of it by Calamares and never read squashfs again).
export MKSQUASHFS_OPTIONS="-b 1M"

build() {
	cp -a "variants/$VARIANT/." ./
	rm -f README
	cp "./auto/$1" ./auto/config
	lb clean
	lb config
	lb build
}

while getopts "di" option; do
	case $option in
		d) # HDD image
			build hdd ;;
		i) # ISO image
			build iso
			mv live-image-amd64.packages "${NAME}_x86-64.packages"
			mv live-image-amd64.hybrid.iso "${NAME}_x86-64.iso" ;;
		\?)
			echo "Error: Invalid option" >&2
			exit 1 ;;
	esac
done
