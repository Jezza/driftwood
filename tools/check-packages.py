#!/usr/bin/env python3
"""Resolve every live-build package-list entry against the trixie archive.

Usage: tools/check-packages.py <variant-dir>...

Fails (exit 1) on any entry that no real package satisfies. Also reports
entries that only resolve through a virtual name, transitional/dummy
packages, and packages that only exist outside trixie proper (backports,
third-party repos) since those need the matching repo enabled at build time.
Requires tools/fetch-indices.sh to have run.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(HERE, ".cache", "idx")


def load(paths):
    avail, provides, desc = {}, {}, {}
    for f in paths:
        suite = os.path.basename(f)[:-4]
        pkg = None
        with open(f, errors="replace") as fh:
            for line in fh:
                if line.startswith("Package: "):
                    pkg = line[9:].strip()
                    avail.setdefault(pkg, set()).add(suite)
                elif pkg and line.startswith("Provides: "):
                    for p in line[10:].split(","):
                        provides.setdefault(p.strip().split(" ")[0], set()).add(pkg)
                elif pkg and line.startswith("Description: ") and pkg not in desc:
                    desc[pkg] = line[13:].strip()
    return avail, provides, desc


if not os.path.isdir(IDX):
    sys.exit("run tools/fetch-indices.sh first")

ARCH = {
    "amd64": load(glob.glob(os.path.join(IDX, "*.txt"))),
    "i386": load(glob.glob(os.path.join(IDX, "i386", "*.txt"))),
}
PROPER = ("trixie-main", "trixie-contrib", "trixie-non-free", "trixie-non-free-firmware",
          "trixie-updates-", "trixie-security-")

missing = 0
for variant in sys.argv[1:]:
    lists = sorted(glob.glob(os.path.join(variant, "config/package-lists/*.list.chroot")))
    if not lists:
        sys.exit(f"{variant}: no package lists found")
    for lst in lists:
        for n, raw in enumerate(open(lst), 1):
            for tok in raw.split("#")[0].split():
                name, _, arch = tok.partition(":")
                avail, provides, desc = ARCH.get(arch or "amd64", ARCH["amd64"])
                loc = f"{os.path.relpath(lst)}:{n}"
                where = avail.get(name)
                if not where:
                    if name in provides:
                        print(f"VIRTUAL     {tok:40s} -> {','.join(sorted(provides[name]))}  {loc}")
                    else:
                        print(f"MISSING     {tok:40s} {loc}")
                    missing += 1
                    continue
                if not any(s.startswith(PROPER) for s in where):
                    print(f"EXTRA-REPO  {tok:40s} {','.join(sorted(where))}  {loc}")
                if re.search(r"\b(transitional|dummy)\b", desc.get(name, ""), re.I):
                    print(f"TRANSITION  {tok:40s} '{desc[name]}'  {loc}")

print(f"{missing} unresolved entr{'y' if missing == 1 else 'ies'}")
sys.exit(1 if missing else 0)
