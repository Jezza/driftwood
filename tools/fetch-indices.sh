#!/bin/bash
# Fetch the Debian archive indices and reference packages used by the checks in tools/.
# Everything lands in tools/.cache (gitignored). Safe to re-run; it refreshes.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
cache="$here/.cache"
mkdir -p "$cache/idx" "$cache/debs"
cd "$cache/idx"

DEB=https://deb.debian.org/debian
SEC=https://security.debian.org/debian-security
FT=https://fasttrack.debian.net/debian-fasttrack

fetch_pkgs() { # url out
  if curl -sfL "$1" > "$2.tmp" 2>/dev/null && grep -q '^Package: ' "$2.tmp"; then mv "$2.tmp" "$2"; return; fi
  if curl -sfL "$1.xz" | xz -d > "$2.tmp" 2>/dev/null && [ -s "$2.tmp" ]; then mv "$2.tmp" "$2"; return; fi
  if curl -sfL "$1.gz" | gunzip > "$2.tmp" 2>/dev/null && [ -s "$2.tmp" ]; then mv "$2.tmp" "$2"; return; fi
  rm -f "$2.tmp"; : > "$2"
}

for s in trixie trixie-updates trixie-backports; do
  for a in main contrib non-free non-free-firmware; do
    fetch_pkgs "$DEB/dists/$s/$a/binary-amd64/Packages" "$s-$a.txt"
  done
done
fetch_pkgs "$SEC/dists/trixie-security/main/binary-amd64/Packages" trixie-security-main.txt
for s in trixie-fasttrack trixie-backports-staging; do
  for a in main contrib non-free; do
    fetch_pkgs "$FT/dists/$s/$a/binary-amd64/Packages" "ft-$s-$a.txt"
  done
done
# Third-party repos the image enables (config/archives/*.list.chroot).
fetch_pkgs "https://packages.mozilla.org/apt/dists/mozilla/main/binary-amd64/Packages" mozilla-main.txt
mkdir -p i386
fetch_pkgs "$DEB/dists/trixie/main/binary-i386/Packages" i386/trixie-main.txt

# Unpack reference packages whose shipped files the port has to agree with.
cd "$cache/debs"
for p in live-build calamares calamares-settings-debian cryptsetup-initramfs cryptsetup-bin systemd-cryptsetup grub-common debootstrap; do
  f=$(awk -v P="$p" '$0=="Package: "P{p=1} p&&/^Filename/{print $2;exit}' "$cache/idx/trixie-main.txt")
  [ -n "$f" ] || { echo "warning: $p not in trixie main" >&2; continue; }
  [ -f "$(basename "$f")" ] || curl -sfLO "$DEB/$f"
  rm -rf "$p"; mkdir -p "$p"
  ( cd "$p" && ar x "../$(basename "$f")"
    t=$(ls data.tar* | head -1)
    case "$t" in
      *.xz) xz -dc "$t" | tar x ;;
      *.zst) zstd -dc "$t" | tar x ;;
      *.gz) tar xzf "$t" ;;
      *) tar xf "$t" ;;
    esac )
  echo "$p: $(basename "$f")"
done
wc -l "$cache"/idx/*.txt | tail -1
