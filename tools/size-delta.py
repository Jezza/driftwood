#!/usr/bin/env python3
"""Estimate how much removing package-list entries shrinks the image.

Usage: tools/size-delta.py <variant-dir> <group-name>=<pkg,pkg,...|prefix*> ...
       tools/size-delta.py <variant-dir> --rank     (TOP=n entries, default 40;
           columns: deb MiB, installed MiB, entry, pkgs freed, biggest freed)

Resolves the Depends/Pre-Depends closure (no Recommends, matching
--apt-recommends false) of the whole package list plus the Priority
required/important base that debootstrap installs, then again with each
group removed, and reports what only that group pulled in.

It is an approximation of apt: alternatives take the first satisfiable
option, virtual packages take the first provider, and version constraints
are ignored. Sizes: installed = Installed-Size, deb = compressed .deb Size
(the closer proxy for what a compressed squashfs costs).
Requires tools/fetch-indices.sh to have run.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(HERE, ".cache", "idx")
# Preference order: a name is taken from the first suite that has it
# (mozilla is pinned to 1000 for firefox; backports only when nothing else has it).
ORDER = [r"mozilla-", r"trixie-security-", r"trixie-updates-",
         r"trixie-(main|contrib|non-free|non-free-firmware)$", r"trixie-backports-"]


def rank(suite):
    for i, p in enumerate(ORDER):
        if re.match(p, suite):
            return i
    return len(ORDER)


pkgs, provides = {}, {}
for f in sorted(glob.glob(os.path.join(IDX, "*.txt")), key=lambda f: rank(os.path.basename(f))):
    suite = os.path.basename(f)[:-4]
    for stanza in open(f, errors="replace").read().split("\n\n"):
        m = re.search(r"^Package: (\S+)", stanza, re.M)
        if not m or m.group(1) in pkgs:
            continue
        fld = dict(re.findall(r"^([A-Za-z-]+): (.*)$", stanza, re.M))
        name = m.group(1)
        pkgs[name] = {
            "dep": ", ".join(x for x in (fld.get("Pre-Depends"), fld.get("Depends")) if x),
            "isz": int(fld.get("Installed-Size", 0)) * 1024,
            "sz": int(fld.get("Size", 0)),
            "prio": fld.get("Priority", ""),
        }
        for p in fld.get("Provides", "").split(","):
            p = p.strip().split(" ")[0]
            if p:
                provides.setdefault(p, []).append(name)


def resolve(name):
    name = name.split(":")[0]
    if name in pkgs:
        return name
    for prov in provides.get(name, []):
        return prov
    return None


def closure(roots):
    seen, stack = set(), [r for r in (resolve(x) for x in roots) if r]
    while stack:
        p = stack.pop()
        if p in seen:
            continue
        seen.add(p)
        for clause in filter(None, (c.strip() for c in pkgs[p]["dep"].split(","))):
            alts = [a.strip().split(" ")[0].split(":")[0] for a in clause.split("|")]
            chosen = next((resolve(a) for a in alts if resolve(a) in seen), None) \
                or next((r for r in (resolve(a) for a in alts) if r), None)
            if chosen and chosen not in seen:
                stack.append(chosen)
    return seen


variant, groups = sys.argv[1], sys.argv[2:]
rank_mode = groups == ["--rank"]
entries = []
for lst in glob.glob(os.path.join(variant, "config/package-lists/*.list.chroot")):
    for raw in open(lst):
        entries += raw.split("#")[0].split()
base = [n for n, p in pkgs.items() if p["prio"] in ("required", "important")
        and n in closure([n])]  # only names present in the preferred suites
base += ["linux-image-amd64", "linux-headers-amd64", "live-boot", "apt-transport-https", "ca-certificates", "openssl"]


def total(s):
    return sum(pkgs[p]["isz"] for p in s), sum(pkgs[p]["sz"] for p in s)


def match(entry, spec):
    return any(entry == s or (s.endswith("*") and entry.startswith(s[:-1])) for s in spec)


full = closure(base + entries)
fi, fs = total(full)
print(f"full image closure: {len(full)} pkgs, installed {fi/2**20:.0f} MiB, debs {fs/2**20:.0f} MiB")
if rank_mode:
    # Every list entry ranked by what removing it alone frees.
    rows = []
    for e in dict.fromkeys(entries):
        gone = full - closure(base + [x for x in entries if x != e])
        gi, gs = total(gone)
        top = sorted(gone, key=lambda p: -pkgs[p]["isz"])[:3]
        rows.append((gs, gi, e, len(gone), top))
    for gs, gi, e, n, top in sorted(rows, reverse=True)[:int(os.environ.get("TOP", 40))]:
        print(f"{gs/2**20:7.1f} {gi/2**20:7.0f}  {e:34s} {n:4d}  "
              + ", ".join(f"{p} {pkgs[p]['isz']/2**20:.0f}M" for p in top))
    sys.exit(0)
allremoved = set()
for g in groups:
    label, spec = g.split("=", 1)
    spec = spec.split(",")
    removed = [e for e in entries if match(e, spec)]
    allremoved.update(removed)
    rest = closure(base + [e for e in entries if e not in removed])
    gone = full - rest
    gi, gs = total(gone)
    top = sorted(gone, key=lambda p: -pkgs[p]["isz"])[:6]
    print(f"\n[{label}] entries removed: {' '.join(removed) or '(none matched)'}")
    print(f"  frees {len(gone)} pkgs, installed {gi/2**20:.0f} MiB, debs {gs/2**20:.0f} MiB")
    print("  biggest: " + ", ".join(f"{p} {pkgs[p]['isz']/2**20:.0f}M" for p in top))
if len(groups) > 1:
    rest = closure(base + [e for e in entries if e not in allremoved])
    gi, gs = total(full - rest)
    print(f"\n[all groups together] installed {gi/2**20:.0f} MiB, debs {gs/2**20:.0f} MiB")
