#!/usr/bin/env python3
"""Render every Driftwood image from two sources and install it in place.

Sources:
  artwork/logo.svg                                    the Driftwood logo (CC0)
  plasma/config/includes.chroot/usr/share/wallpapers/
      driftwood-wireframe-2560x1440.jpg               the desktop wallpaper

Every other image in the repo is generated here and written straight to
where the build uses it (OUTPUTS). tests/test_artwork.py fails if the repo
holds an image that is neither a source nor an output, so a stale copy of
old artwork cannot hide anywhere.

Needs chromium (render.py drives it headless) and ffmpeg (JPEG output).
"""
import hashlib
import json
import os
import shutil
import subprocess

D = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(D)
CHROOT = os.path.join(REPO, "plasma", "config", "includes.chroot")
BRANDING = os.path.join(CHROOT, "etc", "calamares", "branding", "driftwood")

LOGO = os.path.join(D, "logo.svg")
WALLPAPER = os.path.join(CHROOT, "usr", "share", "wallpapers", "driftwood-wireframe-2560x1440.jpg")
SOURCES = [LOGO, WALLPAPER]

# output -> where the build uses it
OUTPUTS = {
    # live boot menus: GRUB (UEFI + BIOS) and isolinux, drawn at 640x480
    "live-splash": [os.path.join(REPO, "plasma", "config", "bootloaders", "grub-pc", "splash.png"),
                    os.path.join(REPO, "plasma", "config", "bootloaders", "isolinux", "splash.png")],
    # installed system's GRUB: Debian's 05_debian_theme uses the first image
    # in /boot/grub, stretched to the screen
    "installed-grub": [os.path.join(CHROOT, "boot", "grub", "splash.png")],
    # Calamares
    "slide1": [os.path.join(BRANDING, "slide1.jpg")],
    "welcome": [os.path.join(BRANDING, "welcome.png")],
    "logo": [os.path.join(BRANDING, "driftwood-logo.png")],
}


STAMP = os.path.join(D, "outputs.json")


def all_outputs():
    return [p for paths in OUTPUTS.values() for p in paths]


def digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def stamp():
    """Hashes of the sources and outputs, relative to the repo."""
    return {os.path.relpath(p, REPO): digest(p) for p in sorted(SOURCES + all_outputs())}


def main():
    out = os.path.join(D, "out")
    os.makedirs(out, exist_ok=True)

    def render(src, name, w, h, bg=None):
        tmp = os.path.join(out, name + ".png")
        args = ["python3", os.path.join(D, "render.py"), src, tmp, str(w), str(h)] + ([bg] if bg else [])
        subprocess.run(args, check=True, stdout=subprocess.DEVNULL)
        return tmp

    logo = "file://" + LOGO
    wall = "file://" + WALLPAPER

    def page(name, w, h, body):
        p = os.path.join(D, name + ".html")
        with open(p, "w") as f:
            f.write(f"""<html><head><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:transparent;
  font-family:'DejaVu Sans','Noto Sans',sans-serif;color:#fff}}
.wall{{position:absolute;inset:0;background:url('{wall}') center/cover}}
.shade{{position:absolute;inset:0}}
.c{{position:absolute;left:0;right:0;text-align:center}}
</style></head><body>{body}</body></html>""")
        return p

    made = {}
    # live boot menus: logo + wordmark in the top half; the lower half, where
    # the menu entries are drawn, darkened so the text stays readable
    made["live-splash"] = render(page("splash", 640, 480, f"""
<div class=wall></div>
<div class=shade style="background:linear-gradient(#0000,#0000 40%,#000a 55%,#000c)"></div>
<img src="{logo}" class=c style="left:270px;top:40px;width:100px;height:100px">
<div class=c style="top:150px;font-size:34px;font-weight:bold;letter-spacing:1px">Driftwood</div>"""),
        "live-splash", 640, 480)

    # installed GRUB: Debian's menu box sits in the middle of the screen, so
    # the whole image is darkened evenly and the logo kept to a corner
    made["installed-grub"] = render(page("installed-grub", 1920, 1080, f"""
<div class=wall></div>
<div class=shade style="background:#0009"></div>
<img src="{logo}" style="position:absolute;right:40px;bottom:40px;width:120px;height:120px">"""),
        "installed-grub", 1920, 1080)

    # Calamares slideshow: the wallpaper with the logo
    made["slide1"] = render(page("slide1", 800, 480, f"""
<div class=wall></div>
<div class=shade style="background:linear-gradient(#0000,#0006)"></div>
<img src="{logo}" style="position:absolute;right:28px;bottom:28px;width:96px;height:96px">"""),
        "slide1", 800, 480)

    # Calamares welcome: logo + wordmark on transparent
    made["welcome"] = render(page("welcome", 457, 300, f"""
<img src="{logo}" class=c style="left:148px;top:14px;width:160px;height:160px">
<div class=c style="top:186px;font-size:46px;font-weight:bold;color:#24555a">Driftwood</div>
<div class=c style="top:248px;font-size:17px;color:#4a6d70">Debian, with KDE Plasma</div>"""),
        "welcome", 457, 300, "transparent")

    made["logo"] = render(LOGO, "logo", 256, 256, "transparent")

    for name, dests in OUTPUTS.items():
        for dest in dests:
            if dest.endswith((".jpg", ".jpeg")):
                subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", made[name], "-q:v", "2", dest], check=True)
            else:
                shutil.copyfile(made[name], dest)
            print("wrote", os.path.relpath(dest, REPO))
    # records which sources these outputs were made from (tests/test_artwork.py)
    with open(STAMP, "w") as f:
        json.dump(stamp(), f, indent=1, sort_keys=True)
        f.write("\n")


if __name__ == "__main__":
    main()
