#!/bin/bash
# Resolve the image's package list with apt, the way the build will, without
# building anything. Catches unsatisfiable dependencies (pins, backports,
# missing packages) in a minute instead of after a 10-minute live-build run.
#
# Runs as an unprivileged user on any Debian-ish host with apt: apt gets a
# private root under $WORK with amd64 + i386, the image's apt sources
# (trixie, -updates, -security, -backports, plus config/archives/*.list.chroot)
# and the image's apt preferences, then simulates installing the kernel and
# every package list.
#   ci/resolve-check.sh [base-dir] [variant]   (default: plasma, all variants)
set -euo pipefail
cd "$(dirname "$0")/.."
V=${1:-plasma}
VARIANT=${2:-}
C=$V/config
WORK=$(mktemp -d -p "${TMPDIR:-/tmp}" resolve.XXXX)
trap '[ -n "${KEEP_SIM:-}" ] && cp "$WORK/sim.out" "$KEEP_SIM"; rm -rf "$WORK"' EXIT

mkdir -p "$WORK"/etc/apt/{sources.list.d,preferences.d,trusted.gpg.d,apt.conf.d} \
         "$WORK"/var/lib/apt/lists/partial "$WORK"/var/cache/apt/archives/partial \
         "$WORK"/var/lib/dpkg "$WORK"/usr/share/keyrings
: > "$WORK/var/lib/dpkg/status"

# Debian's archive key: the host's, or debian-archive-keyring's
for k in /usr/share/keyrings/debian-archive-keyring.gpg /usr/share/keyrings/debian-archive-keyring.pgp; do
    [ -f "$k" ] && cp "$k" "$WORK/etc/apt/trusted.gpg.d/debian-archive.gpg" && break
done
[ -f "$WORK/etc/apt/trusted.gpg.d/debian-archive.gpg" ] || { echo "no debian-archive-keyring on this host" >&2; exit 2; }

cat > "$WORK/etc/apt/sources.list" <<EOF
deb https://deb.debian.org/debian trixie main contrib non-free non-free-firmware
deb https://deb.debian.org/debian trixie-updates main contrib non-free non-free-firmware
deb https://deb.debian.org/debian trixie-backports main contrib non-free non-free-firmware
deb https://security.debian.org/debian-security trixie-security main contrib non-free non-free-firmware
EOF
# build-time archives and their keys, as live-build installs them
for f in "$C"/archives/*.list.chroot; do cp "$f" "$WORK/etc/apt/sources.list.d/$(basename "$f" .chroot)"; done
for f in "$C"/archives/*.pref.chroot; do [ -e "$f" ] && cp "$f" "$WORK/etc/apt/preferences.d/$(basename "$f" .pref.chroot)"; done
for f in "$C"/archives/*.key.chroot; do
    if grep -q 'BEGIN PGP' "$f"; then cp "$f" "$WORK/etc/apt/trusted.gpg.d/$(basename "$f").asc"
    else cp "$f" "$WORK/etc/apt/trusted.gpg.d/$(basename "$f").gpg"; fi
done
# preferences the image applies before installing packages
for d in includes.chroot_before_packages; do
    [ -d "$C/$d/etc/apt/preferences.d" ] && cp "$C/$d/etc/apt/preferences.d/"* "$WORK/etc/apt/preferences.d/"
done

APT=(-o Dir="$WORK" -o Dir::State::status="$WORK/var/lib/dpkg/status"
     -o APT::Architecture=amd64 -o APT::Architectures::=amd64 -o APT::Architectures::=i386
     -o Debug::NoLocking=1 -o Acquire::Languages=none -o APT::Install-Recommends=false
     -o Dir::Etc::TrustedParts="$WORK/etc/apt/trusted.gpg.d")
apt-get "${APT[@]}" -qq update

shopt -s nullglob
lists=("$C"/package-lists/*.list.chroot)
[ -n "$VARIANT" ] && lists+=("$V/variants/$VARIANT"/config/package-lists/*.list.chroot)
pkgs=$(cat "${lists[@]}" 2>/dev/null | sed 's/#.*//' | tr -s ' \t' '\n' | grep -v '^$' | sort -u)
kernel=$(sed -n 's/.*--linux-packages "\([^"]*\)".*/\1/p' "$V/auto/iso")
for k in $kernel; do pkgs="$pkgs $k-amd64"; done
echo "resolving $(echo $pkgs | wc -w) packages (variant: ${VARIANT:-base}, kernel: $kernel)"
if out=$(apt-get "${APT[@]}" -s install $pkgs 2>&1); then echo "$out" > "$WORK/sim.out"
    n=$(grep -c '^Inst ' <<<"$out")
    echo "OK: $n packages would be installed"
    grep -E '^Inst (linux-image-[^ ]+|linux-base|firmware-linux-nonfree|firefox) ' <<<"$out" | sed 's/^/  /'
else
    echo "FAIL: apt cannot install the package set" >&2
    sed -n '/unmet dependencies/,$p' <<<"$out" >&2
    exit 1
fi
