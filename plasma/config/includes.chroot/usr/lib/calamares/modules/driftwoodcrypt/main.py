#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
Driftwood: finish LUKS setup after Calamares' fstab and luksbootkeyfile jobs.

Two boot layouts reach this job:

1. /boot is a separate, unencrypted partition (the automatic layout).
   GRUB never touches LUKS; the initramfs prompts once. Every volume
   unlocked by passphrase gets keyscript=decrypt_keyctl, so the passphrase
   typed for the first volume is cached in the kernel keyring and reused
   for the rest (swap, a separate /home). They also get the `initramfs`
   option: systemd-cryptsetup ignores keyscript=, so volumes left to it
   would prompt a second time.

2. /boot lives on an encrypted volume (manual partitioning). GRUB must
   unlock it, and GRUB 2.12 cannot derive keys with argon2 (2.14 can). The
   passphrase keyslot of that volume is converted to PBKDF2; other volumes
   keep argon2id. luksbootkeyfile has added /crypto_keyfile.bin to every
   volume so the initramfs does not prompt again; cryptsetup-initramfs
   only embeds key files matching KEYFILE_PATTERN, so that is configured
   here, with UMASK=0077 because the initramfs then contains the key.

Runs on the live host with the target mounted. Must run after fstab
(crypttab exists) and before initramfs (the initramfs reads it).
"""
import os
import subprocess

import libcalamares

KEYFILE = "/crypto_keyfile.bin"
PASSPHRASE_OPTIONS = "luks,discard,keyscript=decrypt_keyctl,initramfs"
KEYFILE_OPTIONS = "luks,discard"


def pretty_name():
    return "Configuring disk encryption."


def is_luks(p):
    return bool(p.get("luksMapperName"))


def boot_volume(partitions):
    """The partition holding /boot: a /boot partition if there is one, else /."""
    for mp in ("/boot", "/"):
        for p in partitions:
            if p.get("mountPoint") == mp:
                return p
    return None


def rewrite_crypttab(text):
    """Return (new_text, uses_keyfile). Comments and blank lines are kept."""
    out = []
    uses_keyfile = False
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#") or len(fields) < 2:
            out.append(line)
            continue
        name, source = fields[0], fields[1]
        key = fields[2] if len(fields) > 2 else "none"
        if key == "none" or key == "-":
            out.append(f"{name} {source} none {PASSPHRASE_OPTIONS}")
        else:
            uses_keyfile = uses_keyfile or key == KEYFILE
            out.append(f"{name} {source} {key} {KEYFILE_OPTIONS}")
    return "\n".join(out) + "\n", uses_keyfile


def convert_to_pbkdf2(device, passphrase):
    """Convert the keyslot opened by passphrase to PBKDF2. Returns error text or None."""
    r = subprocess.run(["cryptsetup", "luksConvertKey", "--batch-mode", "--pbkdf", "pbkdf2",
                        "--key-file", "-", device],
                       input=passphrase.encode(), capture_output=True)
    if r.returncode != 0:
        return r.stderr.decode(errors="replace").strip() or f"exit {r.returncode}"
    return None


def luks_version(device):
    r = subprocess.run(["cryptsetup", "luksDump", device], capture_output=True, text=True)
    for line in r.stdout.splitlines():
        if line.startswith("Version:"):
            return line.split()[-1]
    return None


def write(path, text, mode=0o644):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    os.chmod(path, mode)


def run():
    partitions = libcalamares.globalstorage.value("partitions") or []
    root = libcalamares.globalstorage.value("rootMountPoint")
    if not root:
        return ("Configuration Error", "No root mount point for driftwoodcrypt.")
    if not any(is_luks(p) for p in partitions):
        libcalamares.utils.debug("driftwoodcrypt: no LUKS volumes, nothing to do")
        return None

    boot = boot_volume(partitions)
    if boot is not None and is_luks(boot):
        device = boot["device"]
        if luks_version(device) == "2":
            passphrase = boot.get("luksPassphrase") or ""
            if not passphrase:
                return ("Encryption setup error",
                        f"No passphrase known for {device}; GRUB could not unlock /boot.")
            err = convert_to_pbkdf2(device, passphrase)
            if err:
                return ("Encryption setup error",
                        f"Could not convert the keyslot of {device} to PBKDF2 for GRUB: {err}")
            libcalamares.utils.debug(f"driftwoodcrypt: {device} passphrase keyslot now PBKDF2")

    crypttab = os.path.join(root, "etc/crypttab")
    if not os.path.exists(crypttab):
        return ("Encryption setup error", "fstab did not write /etc/crypttab.")
    with open(crypttab) as f:
        text, uses_keyfile = rewrite_crypttab(f.read())
    write(crypttab, text)

    if uses_keyfile:
        write(os.path.join(root, "etc/cryptsetup-initramfs/conf-hook.d/driftwood"),
              f'KEYFILE_PATTERN="{KEYFILE}"\n')
        write(os.path.join(root, "etc/initramfs-tools/conf.d/driftwood-umask"),
              "UMASK=0077\n")
    return None
