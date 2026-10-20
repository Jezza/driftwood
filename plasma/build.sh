#!/bin/bash
# Build the Driftwood (Plasma) image with live-build (run as root on Debian trixie).
#   ./build.sh -i   ISO image
#   ./build.sh -d   HDD image
# VERSION defaults to <debian major>.<yymmdd>, e.g. 13.261019.
set -euo pipefail
cd "$(dirname "$0")"

VERSION="${VERSION:-13.$(date -u +%y%m%d)}"
NAME="Driftwood_Plasma_${VERSION}"

build() {
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
