#!/usr/bin/env python3
"""Render every Driftwood artwork file from logo.svg + the CC0 wallpaper photo."""
import os, subprocess
D = os.path.dirname(os.path.abspath(__file__))
PHOTO_URL = ("https://upload.wikimedia.org/wikipedia/commons/thumb/2/23/"
             "Driftwood_amongst_the_grasses_at_the_head_of_Captain_Cove.webp/"
             "1920px-Driftwood_amongst_the_grasses_at_the_head_of_Captain_Cove.webp")
if not os.path.exists(f"{D}/captain-cove-1920.jpg"):
    import urllib.request
    req = urllib.request.Request(PHOTO_URL, headers={"User-Agent": "driftwood-artwork/1.0"})
    open(f"{D}/captain-cove-1920.jpg", "wb").write(urllib.request.urlopen(req, timeout=60).read())
os.makedirs(f"{D}/out", exist_ok=True)
R = lambda *a: subprocess.run(["python3", os.path.join(D, "render.py"), *map(str, a)], check=True, stdout=subprocess.DEVNULL)
logo = f"file://{D}/logo.svg"
photo = f"file://{D}/captain-cove-1920.jpg"

def page(name, w, h, body, bg="transparent"):
    p = os.path.join(D, name + ".html")
    open(p, "w").write(f"""<html><head><style>
html,body{{margin:0;width:{w}px;height:{h}px;overflow:hidden;background:{bg};
  font-family:'DejaVu Sans','Noto Sans',sans-serif;color:#fff}}
.photo{{position:absolute;inset:0;background:url('{photo}') center/cover}}
.shade{{position:absolute;inset:0}}
.c{{position:absolute;left:0;right:0;text-align:center}}
</style></head><body>{body}</body></html>""")
    return p

# boot menus (GRUB + isolinux): 640x480, darkened photo, logo + wordmark in the top half
grub = page("splash", 640, 480, f"""
<div class=photo style="filter:blur(1.5px)"></div>
<div class=shade style="background:linear-gradient(#0b2a2ecc,#0b2a2ef0 55%,#071b1e)"></div>
<img src="{logo}" class=c style="left:270px;top:40px;width:100px;height:100px">
<div class=c style="top:150px;font-size:34px;font-weight:bold;letter-spacing:1px">Driftwood</div>""")
R(grub, f"{D}/out/splash.png", 640, 480)

# Calamares welcome (457x300): logo + wordmark on transparent
welcome = page("welcome", 457, 300, f"""
<img src="{logo}" class=c style="left:148px;top:14px;width:160px;height:160px">
<div class=c style="top:186px;font-size:46px;font-weight:bold;color:#24555a">Driftwood</div>
<div class=c style="top:248px;font-size:17px;color:#4a6d70">Debian, with KDE Plasma</div>""")
R(welcome, f"{D}/out/welcome.png", 457, 300, "transparent")

# Calamares slideshow (800x480): the photo with the logo
slide = page("slide1", 800, 480, f"""
<div class=photo></div>
<div class=shade style="background:linear-gradient(#0000,#0b2a2e99)"></div>
<img src="{logo}" style="position:absolute;right:28px;bottom:28px;width:96px;height:96px">""")
R(slide, f"{D}/out/slide1.png", 800, 480)

# logo PNG for Calamares productLogo/productIcon
R(f"{D}/logo.svg", f"{D}/out/driftwood-logo.png", 256, 256, "transparent")

# desktop/SDDM wallpaper: the photo, 2560x1600 (cover crop)
wall = page("wallpaper", 2560, 1600, "<div class=photo></div>")
R(wall, f"{D}/out/driftwood-captain-cove-2560x1600.png", 2560, 1600)
print("rendered:", sorted(os.listdir(f"{D}/out")))
