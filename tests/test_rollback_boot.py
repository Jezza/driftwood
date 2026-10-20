#!/usr/bin/env python3
"""Test snapper-rollback's plan_boot_sync/sync_boot on a fake /boot."""
import importlib.machinery
import importlib.util
import os
import pathlib
import sys
import tempfile
import types

INC = os.environ.get("INC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plasma/config/includes.chroot")
P = os.path.join(INC, "usr/sbin/snapper-rollback")
for name in ("btrfsutil", "psutil"):
    m = types.ModuleType(name)
    m.BtrfsUtilError = type("BtrfsUtilError", (Exception,), {})
    sys.modules[name] = m
loader = importlib.machinery.SourceFileLoader("snapper_rollback", P)
spec = importlib.util.spec_from_loader("snapper_rollback", loader)
sr = importlib.util.module_from_spec(spec)
loader.exec_module(sr)
calls = []
sr.subprocess = types.SimpleNamespace(run=lambda cmd, check: calls.append(cmd))

fails = 0


def check(cond, msg):
    global fails
    print(("PASS " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


def kernel(d, v, tag):
    d.mkdir(parents=True, exist_ok=True)
    for pat in sr.KERNEL_FILES:
        (d / pat.format(v)).write_text(f"{pat.format(v)} {tag}")


with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as t:
    t = pathlib.Path(t)
    boot = t / "boot"
    # now installed: only 6.12.48. Snapshot 7 was taken on 6.12.40, whose copies exist.
    kernel(boot, "6.12.48", "new")
    kernel(boot / "snapshots" / "7", "6.12.40", "old")
    snap7 = t / "snap7"
    (snap7 / "usr/lib/modules/6.12.40").mkdir(parents=True)

    print("== rollback to snapshot 7 (pre-upgrade)")
    restore, remove = sr.plan_boot_sync(boot, "7", snap7)
    check(restore == {"6.12.40"} and remove == {"6.12.48"}, f"plan: restore {restore}, remove {remove}")
    sr.sync_boot(boot, "7", restore, remove, dry_run=True)
    check((boot / "vmlinuz-6.12.48").exists() and not (boot / "vmlinuz-6.12.40").exists() and not calls,
          "dry run changes nothing")
    sr.sync_boot(boot, "7", restore, remove)
    check((boot / "vmlinuz-6.12.40").read_text() == "vmlinuz-6.12.40 old", "6.12.40 restored to /boot")
    check(all((boot / p.format("6.12.40")).exists() for p in sr.KERNEL_FILES), "with initrd, config, System.map")
    check(not any((boot / p.format("6.12.48")).exists() for p in sr.KERNEL_FILES),
          "6.12.48 removed (GRUB would default to it, no modules)")
    check((boot / "snapshots/7/vmlinuz-6.12.40").exists(), "snapshot copies left in place")
    check(calls == [["update-grub"]], "update-grub run")
    check(not list(boot.glob("*.rollback-tmp")), "no temp files left")

    print("== snapshot with modules for the installed kernel, no copies")
    calls.clear()
    snap8 = t / "snap8"
    (snap8 / "usr/lib/modules/6.12.40").mkdir(parents=True)
    restore, remove = sr.plan_boot_sync(boot, "8", snap8)
    check(restore == set() and remove == set(), "nothing to restore or remove")

    print("== snapshot that would not boot is refused")
    snap9 = t / "snap9"
    (snap9 / "usr/lib/modules/6.1.0").mkdir(parents=True)
    try:
        sr.plan_boot_sync(boot, "9", snap9)
        check(False, "raises")
    except RuntimeError as e:
        check("would not boot" in str(e), f"raises: {e}")

    print("== non-numeric snapshot id never reads outside /boot/snapshots")
    kernel(t / "evil", "6.1.0", "x")
    try:
        sr.plan_boot_sync(boot, "../../evil", snap9)
        check(False, "raises")
    except RuntimeError:
        check(True, "'../../evil' copies ignored, refused")

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
