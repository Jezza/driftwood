#!/bin/bash
# Test the NVIDIA image's initramfs hook (driftwood-nvidia-late) the way
# mkinitramfs runs it: another hook has only *queued* GPU modules
# (manual_add_modules), and they are copied with their firmware when the
# queue is applied. The hook must flush the queue, then remove modules that
# need nvidia/ firmware plus that firmware, and leave other GPUs alone.
#
# Uses the real hook-functions from initramfs-tools if available
# (tools/.cache from tools/fetch-indices.sh, or the host); dracut-install is
# replaced by a stand-in that copies the module and the firmware it
# declares, which is what the real one does.
set -u
here=$(cd "$(dirname "$0")/.." && pwd)
HOOK=$here/plasma/variants/nvidia/config/includes.chroot/etc/initramfs-tools/hooks/driftwood-nvidia-late
fails=0
ok() { echo "ok   $1"; }
bad() { echo "FAIL $1"; fails=$((fails + 1)); }

HF=""
for c in "$here"/tools/.cache/debs/itc/usr/share/initramfs-tools/hook-functions /usr/share/initramfs-tools/hook-functions; do
	[ -f "$c" ] && HF=$c && break
done
command -v modinfo >/dev/null || { echo "SKIP: needs modinfo (kmod)"; echo "0 failure(s)"; exit 0; }
[ -n "$HF" ] || { echo "SKIP: no initramfs-tools hook-functions"; echo "0 failure(s)"; exit 0; }

W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
V=7.2.9-test
KDIR=$W/lib/modules/$V; FWDIR=$W/lib/firmware
DESTDIR=$W/dest
mkdir -p "$KDIR/kernel/drivers/gpu/drm"/{nouveau,amd,i915} "$FWDIR"/{nvidia/ga102/gsp,amdgpu,i915} "$DESTDIR"
# fake kernel modules: an ELF with just a .modinfo section, which is all
# modinfo reads
mkko() { # path name firmware...
	local out=$1 name=$2; shift 2
	python3 "$here/tests/mkfakeko.py" "$out" "name=$name" $(for f in "$@"; do echo "firmware=$f"; done)
}
mkko "$KDIR/kernel/drivers/gpu/drm/nouveau/nouveau.ko" nouveau nvidia/ga102/gsp/gsp-570.144.bin
mkko "$KDIR/kernel/drivers/gpu/drm/amd/amdgpu.ko" amdgpu amdgpu/navi10_gpu_info.bin
mkko "$KDIR/kernel/drivers/gpu/drm/i915/i915.ko" i915 i915/tgl_dmc.bin
echo gsp > "$FWDIR/nvidia/ga102/gsp/gsp-570.144.bin"
echo amd > "$FWDIR/amdgpu/navi10_gpu_info.bin"
echo i915 > "$FWDIR/i915/tgl_dmc.bin"
[ "$(modinfo -F firmware "$KDIR/kernel/drivers/gpu/drm/nouveau/nouveau.ko")" = nvidia/ga102/gsp/gsp-570.144.bin ] \
	|| { echo "SKIP: modinfo can't read the fake modules"; echo "0 failure(s)"; exit 0; }

# hook-functions with dracut-install replaced (same contract: copy the
# modules and their declared firmware into DESTDIR, usr-merged)
cat > "$W/hook-functions" <<EOF
. "$HF"
_call_dracut_install() {
	for m in "\$@"; do
		p=\$(find "$KDIR" -name "\$m.ko*" | head -1); [ -n "\$p" ] || continue
		rel=\${p#$W/}; mkdir -p "\$DESTDIR/usr/\$(dirname "\$rel")"; cp "\$p" "\$DESTDIR/usr/\$rel"
		for f in \$(modinfo -F firmware "\$p"); do
			[ -f "$FWDIR/\$f" ] || continue
			mkdir -p "\$DESTDIR/usr/lib/firmware/\$(dirname "\$f")"; cp "$FWDIR/\$f" "\$DESTDIR/usr/lib/firmware/\$f"
		done
	done
}
EOF
sed "s|/usr/share/initramfs-tools/hook-functions|$W/hook-functions|" "$HOOK" > "$W/hook"; chmod +x "$W/hook"

# what plymouth's hook does: queue every DRM module
export DESTDIR version=$V verbose=n __MODULES_TO_ADD=$W/queue MODULESDIR=/lib/modules/$V
printf '%s\n' nouveau amdgpu i915 > "$__MODULES_TO_ADD"

sh -n "$HOOK" && ok "hook parses" || bad "hook syntax"
[ -x "$HOOK" ] && ok "hook is executable (mkinitramfs skips it otherwise)" || bad "hook not executable"
[ "$(sh "$W/hook" prereqs)" = "" ] && ok "prereqs answers" || bad "prereqs"
out=$(sh "$W/hook" 2>&1); rc=$?
[ $rc -eq 0 ] && ok "hook exits 0" || bad "hook exit $rc: $out"
echo "  $out"

M=$DESTDIR/usr/lib/modules/$V/kernel/drivers/gpu/drm
[ ! -e "$M/nouveau/nouveau.ko" ] && ok "nouveau removed" || bad "nouveau still in initramfs"
[ ! -e "$DESTDIR/usr/lib/firmware/nvidia" ] && ok "nvidia/ firmware removed" || bad "nvidia firmware still in initramfs"
[ -e "$M/amd/amdgpu.ko" ] && [ -e "$DESTDIR/usr/lib/firmware/amdgpu/navi10_gpu_info.bin" ] && ok "amdgpu + firmware kept" || bad "amdgpu lost"
[ -e "$M/i915/i915.ko" ] && [ -e "$DESTDIR/usr/lib/firmware/i915/tgl_dmc.bin" ] && ok "i915 + firmware kept" || bad "i915 lost"
[ ! -s "$__MODULES_TO_ADD" ] && ok "queue flushed (mkinitramfs won't re-add nouveau)" || bad "queue still has: $(cat "$__MODULES_TO_ADD")"

echo "$fails failure(s)"
[ $fails -eq 0 ]
