#!/bin/bash
# Release notes for a Driftwood tag, from the built artifacts.
#   ci/release-notes.sh <tag> <dist-dir with *.iso + *.sha256> <info-dir with *.packages>
set -euo pipefail
tag=$1 dist=$2 info=$3
ver=${tag#v}

ver_of() { # package -> upstream version (no epoch, no Debian revision)
	awk -v P="$1" -F'\t' '{sub(/:.*/, "", $1)} $1==P {v=$2; sub(/^[0-9]+:/, "", v); sub(/[-~].*/, "", v); print v; exit}' \
		$(find "$info" -name '*.packages')
}
size_of() { numfmt --to=iec-i --suffix=B --format='%.2f' "$(stat -c %s "$1")"; }
iso() { ls "$dist"/*_"$1"_x86-64.iso; }

kernel=$(ver_of linux-image-amd64)
cat <<EOF
Debian 13 "trixie" with KDE Plasma $(ver_of plasma-workspace). Installed systems track Debian \`stable\`.

## Which image?

| Image | For | Size |
|---|---|---|
| \`$(basename "$(iso amd)")\` | AMD or Intel graphics, VMs | $(size_of "$(iso amd)") |
| \`$(basename "$(iso nvidia)")\` | NVIDIA, including hybrid laptops (Intel/AMD + NVIDIA) | $(size_of "$(iso nvidia)") |

The NVIDIA image uses nouveau, the open driver. Both images boot under UEFI
and legacy BIOS; Secure Boot has not been tested yet. Write to a USB stick
with any image writer (\`dd\`, Impression, balenaEtcher, Rufus in DD mode).

## Highlights

- Linux $kernel and firmware from Debian backports, Firefox $(ver_of firefox) from Mozilla.
- Btrfs with Snapper snapshots before and after every apt run. Snapshots
  appear in the GRUB menu and stay bootable after their kernel is removed;
  \`snapper-rollback\` makes one the running system.
- Full-disk encryption with LUKS2/argon2id and one passphrase prompt.
  \`/boot\` is a small unencrypted partition.
- Calamares 3.3 installer.

## Tested

Built and boot-tested in CI: each image is booted in QEMU three ways
(direct kernel, UEFI, BIOS) until the live Plasma session is up or the
network comes up.

**Not covered by CI yet:** an install through Calamares (Calamares has no
unattended mode), so the encrypted install, the separate \`/boot\` and booting
a snapshot from GRUB are untested end to end. This is a pre-release until
that has been done on real hardware or a VM.

## Checksums

\`\`\`
$(cat "$dist"/*.iso.sha256)
\`\`\`

Package lists for each image are attached (\`*.packages\`).

Driftwood started as a fork of [SpiralLinux](https://github.com/SpiralLinux/SpiralLinux-project);
most of its system configuration is SpiralLinux's work. See the README for credits.
EOF
