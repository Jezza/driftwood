#!/usr/bin/env python3
"""Test driftwoodcrypt/main.py with a stub libcalamares and real cryptsetup on image files."""
import importlib.util
import os
import subprocess
import sys
import tempfile
import types

import shutil
HERE = os.environ.get("TMPDIR") or "/tmp"
INC = os.environ.get("INC") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "plasma/config/includes.chroot")
MOD = os.path.join(INC, "usr/lib/calamares/modules/driftwoodcrypt/main.py")
if not shutil.which("cryptsetup"):
    sys.exit("cryptsetup not found (apt install cryptsetup-bin)")

GS = {}
lc = types.ModuleType("libcalamares")
lc.globalstorage = types.SimpleNamespace(value=lambda k: GS.get(k))
lc.utils = types.SimpleNamespace(debug=lambda m: print("  debug:", m))
sys.modules["libcalamares"] = lc
spec = importlib.util.spec_from_file_location("driftwoodcrypt", MOD)
sc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sc)

PW = "correct horse battery"
fails = 0


def check(cond, msg):
    global fails
    print(("PASS " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


def luks_image(tmp, name):
    img = os.path.join(tmp, name)
    subprocess.run(["truncate", "-s", "32M", img], check=True)
    # exactly kpmcore 24.12 luks2::create (passphrase + "\n" on the prompt)
    subprocess.run(["cryptsetup", "--use-random", "--key-size", "512", "--hash", "sha512", "--batch-mode",
                    "--force-password", "--type", "luks2", "--pbkdf-memory", "65536", "luksFormat", img],
                   input=(PW + "\n").encode(), check=True, capture_output=True)
    return img


def pbkdfs(img):
    out = subprocess.run(["cryptsetup", "luksDump", img], capture_output=True, text=True).stdout
    return [l.split()[-1] for l in out.splitlines() if l.strip().startswith("PBKDF:")]


def opens(img, pw):
    return subprocess.run(["cryptsetup", "open", "--test-passphrase", "--key-file", "-", img],
                          input=pw.encode(), capture_output=True).returncode == 0


def target(tmp, crypttab):
    root = os.path.join(tmp, "target")
    os.makedirs(os.path.join(root, "etc"), exist_ok=True)
    with open(os.path.join(root, "etc/crypttab"), "w") as f:
        f.write(crypttab)
    return root


HEADER = "# /etc/crypttab: mappings for encrypted partitions.\n\n"

print("== layout 1: separate unencrypted /boot, encrypted / and swap")
with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    rootimg, swapimg = luks_image(tmp, "root.img"), luks_image(tmp, "swap.img")
    root = target(tmp, HEADER + "luks-aaa UUID=aaa none\nluks-bbb UUID=bbb none luks\n")
    GS.clear()
    GS.update(rootMountPoint=root, partitions=[
        {"mountPoint": "/boot", "device": "/dev/vda2", "fs": "ext4"},
        {"mountPoint": "/", "device": rootimg, "fs": "btrfs", "fsName": "luks2", "luksMapperName": "luks-aaa", "luksPassphrase": PW},
        {"mountPoint": "", "device": swapimg, "fs": "linuxswap", "fsName": "luks2", "luksMapperName": "luks-bbb", "luksPassphrase": PW},
    ])
    check(sc.run() is None, "run() succeeds")
    ct = open(os.path.join(root, "etc/crypttab")).read()
    print("  crypttab:\n    " + "\n    ".join(ct.splitlines()))
    check(ct.startswith("# /etc/crypttab"), "header comment kept")
    check("luks-aaa UUID=aaa none luks,discard,keyscript=decrypt_keyctl,initramfs" in ct, "root: single-prompt options")
    check("luks-bbb UUID=bbb none luks,discard,keyscript=decrypt_keyctl,initramfs" in ct, "swap: reuses cached passphrase, in initramfs")
    check(pbkdfs(rootimg) == ["argon2id"], "root keyslot stays argon2id (GRUB never reads it)")
    check(not os.path.exists(os.path.join(root, "etc/cryptsetup-initramfs/conf-hook.d/driftwood")), "no KEYFILE_PATTERN without key files")

print("== layout 2: /boot inside encrypted / (manual partitioning), keyfile from luksbootkeyfile")
with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    rootimg, homeimg = luks_image(tmp, "root.img"), luks_image(tmp, "home.img")
    root = target(tmp, HEADER + "luks-aaa UUID=aaa /crypto_keyfile.bin luks\nluks-ccc UUID=ccc /crypto_keyfile.bin luks\n")
    GS.clear()
    GS.update(rootMountPoint=root, partitions=[
        {"mountPoint": "/boot/efi", "device": "/dev/vda1", "fs": "fat32"},
        {"mountPoint": "/", "device": rootimg, "fs": "btrfs", "fsName": "luks2", "luksMapperName": "luks-aaa", "luksPassphrase": PW},
        {"mountPoint": "/home", "device": homeimg, "fs": "ext4", "fsName": "luks2", "luksMapperName": "luks-ccc", "luksPassphrase": PW},
    ])
    check(sc.run() is None, "run() succeeds")
    check(pbkdfs(rootimg) == ["pbkdf2"], "/boot-holding volume converted to PBKDF2 for GRUB 2.12")
    check(opens(rootimg, PW), "passphrase still opens it after conversion")
    check(not opens(rootimg, "wrong"), "wrong passphrase still rejected")
    check(pbkdfs(homeimg) == ["argon2id"], "/home keeps argon2id")
    ct = open(os.path.join(root, "etc/crypttab")).read()
    check("luks-aaa UUID=aaa /crypto_keyfile.bin luks,discard" in ct, "keyfile lines keep the key file")
    hook = os.path.join(root, "etc/cryptsetup-initramfs/conf-hook.d/driftwood")
    check(os.path.exists(hook) and 'KEYFILE_PATTERN="/crypto_keyfile.bin"' in open(hook).read(), "KEYFILE_PATTERN set")
    check("UMASK=0077" in open(os.path.join(root, "etc/initramfs-tools/conf.d/driftwood-umask")).read(), "initramfs UMASK=0077")

print("== wrong passphrase in global storage fails the install instead of leaving GRUB unable to unlock")
with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    rootimg = luks_image(tmp, "root.img")
    root = target(tmp, HEADER + "luks-aaa UUID=aaa /crypto_keyfile.bin luks\n")
    GS.clear()
    GS.update(rootMountPoint=root, partitions=[
        {"mountPoint": "/", "device": rootimg, "fs": "btrfs", "fsName": "luks2", "luksMapperName": "luks-aaa", "luksPassphrase": "not it"},
    ])
    r = sc.run()
    check(isinstance(r, tuple) and "PBKDF2" in r[1], f"returns an error: {r}")
    check(pbkdfs(rootimg) == ["argon2id"], "volume untouched")

print("== no encryption: no-op")
with tempfile.TemporaryDirectory(dir=HERE) as tmp:
    root = target(tmp, HEADER)
    GS.clear()
    GS.update(rootMountPoint=root, partitions=[{"mountPoint": "/", "device": "/dev/vda2", "fs": "btrfs"}])
    check(sc.run() is None and open(os.path.join(root, "etc/crypttab")).read() == HEADER, "crypttab untouched")

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
