#!/usr/bin/env python3
"""Every image in the repo is an artwork source or an output of
artwork/make_art.py, and every output was made from the current sources.

Fails on: an image make_art.py doesn't know (a leftover), a source changed
without re-running make_art.py, or an output edited/replaced by hand. The
proof is artwork/outputs.json, written by make_art.py: the hashes of the
sources and outputs it rendered together."""
import json
import importlib.util
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
repo = os.path.dirname(here)
spec = importlib.util.spec_from_file_location("make_art", os.path.join(repo, "artwork", "make_art.py"))
art = importlib.util.module_from_spec(spec)
spec.loader.exec_module(art)  # defines paths only; rendering is in main()

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif", ".bmp", ".tga", ".xpm", ".ico")
fails = 0


def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    fails += not ok


# Walks the tree rather than asking git: CI runs in a container where git
# refuses the checkout ("dubious ownership"). Skipped: git metadata,
# caches and render scratch output (all gitignored).
SKIP_DIRS = {".git", ".cache", "__pycache__", "out"}
images = set()
for root, dirs, files in os.walk(repo):
    dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
    images |= {os.path.join(root, f) for f in files if f.lower().endswith(IMAGE_EXT)}
known = set(art.SOURCES) | set(art.all_outputs())

for p in sorted(images - known):
    check(False, f"{os.path.relpath(p, repo)} is not made by artwork/make_art.py (stale artwork?)")
for p in sorted(known):
    check(os.path.exists(p), f"exists: {os.path.relpath(p, repo)}")

try:
    recorded = json.load(open(art.STAMP))
except FileNotFoundError:
    recorded = {}
    check(False, "artwork/outputs.json missing: run artwork/make_art.py")
current = art.stamp() if all(os.path.exists(p) for p in known) else {}
for rel in sorted(set(recorded) | set(current)):
    check(recorded.get(rel) == current.get(rel),
          f"{rel} matches what make_art.py rendered" if recorded.get(rel) == current.get(rel)
          else f"{rel} changed since make_art.py ran (re-run it)")

print(f"{len(images)} images found, {len(known)} known")
print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
