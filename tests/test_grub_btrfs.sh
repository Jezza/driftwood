#!/bin/bash
INC=${INC:-$(cd "$(dirname "$0")/.." && pwd)/plasma/config/includes.chroot}
# Exercise patched boot_separate() from 41_snapshots-btrfs on a fake tree.
# Extracts the script's own functions; stubs only snapshot_list (needs btrfs)
# and make_system_path_relative_to_its_root (grub-mkconfig_lib, needs grub-probe).
# (no set -u: the script relies on unset optional GRUB_BTRFS_* variables, as under grub-mkconfig)
G=$INC/usr/share/grub-btrfs/41_snapshots-btrfs
T=$(mktemp -d -p "${TMPDIR:-/tmp}" gbt.XXXX)
fails=0
chk() { if eval "$1"; then echo "PASS $2"; else echo "FAIL $2"; fails=$((fails+1)); fi; }

# function bodies, by name, from the real script
extract() { awk -v f="$1" '$0 ~ "^"f"\\(\\)" {p=1} p {print} p && /^}/ {exit}' "$G"; }
FUNCS=""
for f in entry make_menu_entries trim parse_snapshot_list detect_kernel detect_initramfs detect_microcode detect_rootflags title_format boot_separate print_error; do
    body=$(extract $f); [ -n "$body" ] || { echo "FAIL could not extract $f"; exit 1; }
    FUNCS+="$body"$'\n'
done
# make_menu_entries' entry() body spans to the next "}" line; check it parsed
eval "$FUNCS" || { echo "FAIL extracted functions do not parse"; exit 1; }
# title_format uses this table from the script
eval "$(grep -m1 '^declare -A title_column' "$G")"

# fake system: /boot has only the new kernel; old one is in /boot/snapshots/1
boot_directory=$T/boot; grub_btrfs_mount_point=$T/fsroot; grub_btrfs_directory=$T/out
mkdir -p $T/boot/snapshots/1 $T/out
for v in 6.12.48; do : > $T/boot/vmlinuz-$v; : > $T/boot/initrd.img-$v; done
: > $T/boot/snapshots/1/vmlinuz-6.12.40; : > $T/boot/snapshots/1/initrd.img-6.12.40
mk_snap() { mkdir -p $T/fsroot/@snapshots/$1/snapshot/usr/lib/modules/$2 $T/fsroot/@snapshots/$1/snapshot/etc
            echo "UUID=x / btrfs subvol=/@,defaults,noatime,compress=zstd:1 0 0" > $T/fsroot/@snapshots/$1/snapshot/etc/fstab; }
mk_snap 1 6.12.40     # before the kernel upgrade: copies exist
mk_snap 2 6.12.48     # after: no copies, installed kernel matches
mk_snap 3 6.1.0       # no copies, no matching installed kernel

snapshot_list() {
    echo "2026-10-01 10:00:00 | @snapshots/1/snapshot | pre  | apt |"
    echo "2026-10-02 10:00:00 | @snapshots/2/snapshot | post | apt |"
    echo "2026-10-03 10:00:00 | @snapshots/3/snapshot | single | old |"
}
make_system_path_relative_to_its_root() { echo "${1#$T/boot}"; }   # /boot is its own fs
oldIFS=$IFS; limit_snap_show=50; count_limit_snap=0; count_warning_menuentries=0
CLASS="--class snapshots"; boot_uuid=BOOTUUID; boot_hs=""; LINUX_ROOT_DEVICE=UUID=ROOT; kernel_parameters="quiet"
GRUB_BTRFS_TITLE_FORMAT=("date" "snapshot" "type" "description")
: > $T/out/grub-btrfs.new

boot_separate 2> $T/err
cfg=$T/out/grub-btrfs.new
echo "--- generated (excerpt)"; grep -E "linux|initrd|submenu" $cfg | sed 's/^/  /'
echo "--- stderr"; sed 's/^/  /' $T/err

chk 'grep -q "linux \"/snapshots/1/vmlinuz-6.12.40\" .*subvol=\"@snapshots/1/snapshot\"" $cfg' "snapshot 1 boots its own copied 6.12.40 kernel"
chk 'grep -q "initrd \"/snapshots/1/initrd.img-6.12.40\"" $cfg' "snapshot 1 uses the copied initramfs"
chk 'grep -q "linux \"/vmlinuz-6.12.48\" .*subvol=\"@snapshots/2/snapshot\"" $cfg' "snapshot 2 (no copies) falls back to installed 6.12.48"
chk '! grep -q "subvol=\"@snapshots/3/snapshot\"" $cfg' "snapshot 3 (no kernel with modules) has no entry"
chk 'grep -q "Skipping snapshot @snapshots/3/snapshot" $T/err' "and says why"
chk '! grep -q "@snapshots/1/snapshot.*vmlinuz-6.12.48\|vmlinuz-6.12.48.*@snapshots/1/" $cfg' "snapshot 1 not offered the module-less 6.12.48"
chk 'grep -q "rootflags=defaults,noatime,compress=zstd:1," $cfg' "rootflags from the snapshot's fstab"
chk '[ "$count_limit_snap" = 2 ]' "2 snapshots counted"

GRUB_SCRIPT_CHECK=${GRUB_SCRIPT_CHECK:-$(command -v grub-script-check || true)}
if [ -x "$GRUB_SCRIPT_CHECK" ]; then
    printf "submenu 'x' {\n%s\n}\n" "$(cat $cfg)" > $T/check.cfg
    chk '"$GRUB_SCRIPT_CHECK" $T/check.cfg' "grub-script-check accepts the generated menu"
fi
rm -rf "$T"
echo "$fails failure(s)"; exit $fails
