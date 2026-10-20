#!/bin/bash
INC=${INC:-$(cd "$(dirname "$0")/.." && pwd)/plasma/config/includes.chroot}
# Test 50-driftwood-boot-snapshots on a fake /boot + /.snapshots tree.
set -u
P=$INC/usr/lib/snapper/plugins/50-driftwood-boot-snapshots
T=$(mktemp -d -p "${TMPDIR:-/tmp}" bsnap.XXXX)
export DRIFTWOOD_BOOT=$T/boot DRIFTWOOD_SNAPROOT=$T/snapshots DRIFTWOOD_BOOT_RESERVE_KB=0
fails=0
ok()  { echo "PASS $*"; }
bad() { echo "FAIL $*"; fails=$((fails+1)); }
chk() { if eval "$1"; then ok "$2"; else bad "$2"; fi; }
run() { sh "$P" "$@" / btrfs "$N" 2>&1 | sed 's/^/  /'; }

mkdir -p $T/boot
kernel() { # kernel <ver>: install a fake kernel
    head -c 300000 /dev/urandom > $T/boot/vmlinuz-$1
    head -c 200000 /dev/urandom > $T/boot/initrd.img-$1
    echo cfg-$1 > $T/boot/config-$1
}
snapshot() { # snapshot <n> <module versions...>
    local n=$1; shift
    mkdir -p $T/snapshots/$n/snapshot/usr/lib/modules
    for v in "$@"; do mkdir -p $T/snapshots/$n/snapshot/usr/lib/modules/$v; done
}

kernel 6.12.40
echo "== snapshot 1 (kernel 6.12.40)"
snapshot 1 6.12.40; N=1; run create-snapshot-post
chk '[ -f $T/boot/snapshots/1/vmlinuz-6.12.40 ] && [ -f $T/boot/snapshots/1/initrd.img-6.12.40 ]' "kernel + initramfs copied"
chk 'cmp -s $T/boot/vmlinuz-6.12.40 $T/boot/snapshots/1/vmlinuz-6.12.40' "copy is byte-identical (Secure Boot signature intact)"

echo "== snapshot 2, same kernel: deduplicated"
snapshot 2 6.12.40; N=2; run create-snapshot-post
chk '[ "$(stat -c %i $T/boot/snapshots/1/vmlinuz-6.12.40)" = "$(stat -c %i $T/boot/snapshots/2/vmlinuz-6.12.40)" ]' "snapshots 1 and 2 share one inode"
chk '[ $(ls $T/boot/snapshots/.store | wc -l) = 3 ]' "store holds 3 files (vmlinuz, initrd, config)"

echo "== kernel upgrade: 6.12.48 installed, 6.12.40 removed by apt"
kernel 6.12.48; rm $T/boot/vmlinuz-6.12.40 $T/boot/initrd.img-6.12.40 $T/boot/config-6.12.40
snapshot 3 6.12.48; N=3; run create-snapshot-post
chk '[ -f $T/boot/snapshots/3/vmlinuz-6.12.48 ] && [ ! -e $T/boot/snapshots/3/vmlinuz-6.12.40 ]' "snapshot 3 gets only the kernel it has modules for"
chk '[ -f $T/boot/snapshots/1/vmlinuz-6.12.40 ]' "snapshot 1 still has the removed kernel: still bootable"

echo "== delete snapshot 1: store keeps 6.12.40 for snapshot 2"
rm -rf $T/snapshots/1; N=1; run delete-snapshot-post
chk '[ ! -e $T/boot/snapshots/1 ]' "snapshot 1 copies removed"
chk '[ -f $T/boot/snapshots/2/vmlinuz-6.12.40 ]' "snapshot 2 copy intact"
chk '[ $(ls $T/boot/snapshots/.store | wc -l) = 6 ]' "store: 3 old + 3 new"

echo "== delete snapshot 2: last user of 6.12.40 gone, store pruned"
rm -rf $T/snapshots/2; N=2; run delete-snapshot-post
chk '[ $(ls $T/boot/snapshots/.store | wc -l) = 3 ]' "store pruned to the 3 files of 6.12.48"

echo "== stale copy for a snapshot deleted behind snapper's back is reconciled"
mkdir -p $T/boot/snapshots/99; cp $T/boot/vmlinuz-6.12.48 $T/boot/snapshots/99/
snapshot 4 6.12.48; N=4; run create-snapshot-post
chk '[ ! -e $T/boot/snapshots/99 ]' "orphan /boot/snapshots/99 removed"
chk '[ -d $T/boot/snapshots/3 ] && [ -d $T/boot/snapshots/4 ]' "live snapshot copies kept"

echo "== snapshot with no matching kernel: nothing copied"
snapshot 5 6.1.0; N=5; run create-snapshot-post
chk '[ ! -e $T/boot/snapshots/5 ]' "no directory for snapshot 5"

echo "== /boot reserve: copy skipped when space would run out"
kernel 6.12.50; snapshot 6 6.12.50; N=6
DRIFTWOOD_BOOT_RESERVE_KB=999999999999 run create-snapshot-post
chk '[ ! -e $T/boot/snapshots/6 ] && [ -z "$(ls -A $T/boot/snapshots | grep "^.new")" ]' "skipped cleanly, no partial directory"

echo "== ignores /home config and non-btrfs"
N=7; snapshot 7 6.12.50
sh "$P" create-snapshot-post /home btrfs 7; sh "$P" create-snapshot-post / ext4 7
chk '[ ! -e $T/boot/snapshots/7 ]' "nothing done"

echo "== bad snapshot numbers are ignored (no path traversal)"
sh "$P" delete-snapshot-post / btrfs "../.."
chk '[ -d $T/boot/snapshots/.store ]' "store survives"

rm -rf "$T"
echo "$fails failure(s)"
exit $fails
