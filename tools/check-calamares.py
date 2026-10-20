#!/usr/bin/env python3
"""Validate a variant's Calamares module configs against upstream schemas.

Usage: tools/check-calamares.py <variant-dir>... [--version v3.3.14]

Calamares silently ignores keys it does not know, so a renamed setting
(e.g. keepDistributor -> keep_distributor) just stops working. This checks
every config/includes.chroot/etc/calamares/modules/*.conf against the
<module>.schema.yaml shipped in the matching upstream Calamares release
(fetched into tools/.cache/calamares-<version>/) and against the module's
upstream default config for keys that only exist in comments there.

The version defaults to the calamares package in trixie (read from the
fetched archive index), so it tracks Debian. Exit 1 on any error.
"""
import glob
import os
import re
import sys
import urllib.request

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, ".cache")


def trixie_calamares_version():
    idx = os.path.join(CACHE, "idx", "trixie-main.txt")
    if not os.path.exists(idx):
        sys.exit("run tools/fetch-indices.sh first (or pass --version)")
    text = open(idx, errors="replace").read()
    m = re.search(r"^Package: calamares\n(?:.+\n)*?Version: (\S+)", text, re.M)
    if not m:
        sys.exit("calamares not found in trixie index")
    return "v" + m.group(1).split(":")[-1].split("-")[0].split("+")[0]


def fetch(version, module, name):
    d = os.path.join(CACHE, f"calamares-{version}", module)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, name)
    if not os.path.exists(path):
        url = f"https://raw.githubusercontent.com/calamares/calamares/{version}/src/modules/{module}/{name}"
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = r.read()
        except Exception:
            data = b""
        open(path, "wb").write(data)
    data = open(path, "rb").read()
    return data.decode() if data else None


TYPES = {"object": dict, "array": list, "string": str, "boolean": bool,
         "integer": int, "number": (int, float)}


def validate(node, schema, path, errs):
    if not isinstance(schema, dict):
        return
    for key in ("anyOf", "oneOf"):
        if key in schema:
            trials = []
            for alt in schema[key]:
                e = []
                validate(node, alt, path, e)
                trials.append(e)
            if all(trials):
                errs.append(f"{path}: matches none of {key}: " + "; ".join(t[0] for t in trials))
            return
    t = schema.get("type")
    if t:
        ts = t if isinstance(t, list) else [t]
        ok = any(isinstance(node, TYPES[x]) and not (x in ("integer", "number") and isinstance(node, bool))
                 for x in ts if x in TYPES)
        if not ok:
            errs.append(f"{path}: expected {t}, got {type(node).__name__} ({node!r:.60})")
            return
    if "enum" in schema and node not in schema["enum"]:
        errs.append(f"{path}: {node!r} not one of {schema['enum']}")
    if isinstance(node, dict):
        props = schema.get("properties", {})
        for k, v in node.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}", errs)
            elif schema.get("additionalProperties") is False:
                errs.append(f"{path}: unknown key '{k}' (Calamares ignores it)")
            elif isinstance(schema.get("additionalProperties"), dict):
                validate(v, schema["additionalProperties"], f"{path}.{k}", errs)
        for r in schema.get("required", []):
            if r not in node:
                errs.append(f"{path}: missing required key '{r}'")
    if isinstance(node, list) and "items" in schema:
        for i, v in enumerate(node):
            validate(v, schema["items"], f"{path}[{i}]", errs)


def main():
    args = sys.argv[1:]
    version = None
    if "--version" in args:
        i = args.index("--version")
        version = args[i + 1]
        del args[i:i + 2]
    version = version or trixie_calamares_version()
    print(f"calamares {version}")
    bad = 0
    for variant in args:
        confs = sorted(glob.glob(os.path.join(variant, "config/includes.chroot/etc/calamares/modules/*.conf")))
        if not confs:
            sys.exit(f"{variant}: no calamares module configs")
        for conf in confs:
            module = os.path.basename(conf)[:-5]
            rel = os.path.relpath(conf)
            try:
                data = yaml.safe_load(open(conf)) or {}
            except yaml.YAMLError as e:
                print(f"ERROR {rel}: YAML: {e}")
                bad += 1
                continue
            raw = fetch(version, module, f"{module}.schema.yaml")
            if raw is None:
                print(f"skip  {rel}: no upstream schema")
                continue
            schema = yaml.safe_load(raw)
            errs = []
            validate(data, schema, module, errs)
            for e in errs:
                print(f"ERROR {rel}: {e}")
            bad += len(errs)
            if not errs:
                print(f"ok    {rel}")
        # Every module in settings.conf's sequence must exist upstream.
        settings = os.path.join(variant, "config/includes.chroot/etc/calamares/settings.conf")
        seq = yaml.safe_load(open(settings)).get("sequence", [])
        instances = {i.get("id") for i in (yaml.safe_load(open(settings)).get("instances") or [])}
        for step in seq:
            for name in sum(step.values(), []):
                module = name.split("@")[0]
                if name in instances:
                    continue
                local = os.path.join(variant, "config/includes.chroot/usr/lib/calamares/modules", module, "module.desc")
                if os.path.exists(local):
                    continue
                if fetch(version, module, "module.desc") is None and fetch(version, module, "CMakeLists.txt") is None:
                    print(f"ERROR {os.path.relpath(settings)}: sequence module '{name}' does not exist in {version}")
                    bad += 1
    print(f"{bad} error{'s' if bad != 1 else ''}")
    sys.exit(1 if bad else 0)


main()
