#!/usr/bin/env python3
"""driftwood-span-wallpaper: geometry and cutting, without Plasma (--screens, --dry-run)."""
import importlib.machinery
import importlib.util
import json
import os
import sys
import tempfile

here = os.path.dirname(os.path.abspath(__file__))
path = os.path.join(here, "..", "plasma", "config", "includes.chroot", "usr", "bin", "driftwood-span-wallpaper")
loader = importlib.machinery.SourceFileLoader("span", path)
spec = importlib.util.spec_from_loader("span", loader)
span = importlib.util.module_from_spec(spec)
loader.exec_module(span)

try:
    from PIL import Image
except ImportError:
    print("SKIP: Pillow not installed")
    sys.exit(0)

fails = 0


def check(ok, what):
    global fails
    print(("PASS " if ok else "FAIL ") + what)
    fails += not ok


def run(img, screens, *extra):
    with tempfile.TemporaryDirectory() as t:
        src = os.path.join(t, "pano.png")
        img.save(src)
        out = os.path.join(t, "out")
        span.main([src, "--dry-run", "--out", out, "--screens", json.dumps(screens), *extra])
        files = sorted(os.listdir(out))
        return {f.split("-screen")[1][0]: Image.open(os.path.join(out, f)).convert("RGB").copy() for f in files}


def at(piece, fx, fy):
    """Pixel at a fraction of the piece's size (pieces keep the image's scale)."""
    return piece.getpixel((min(int(fx * piece.width), piece.width - 1), min(int(fy * piece.height), piece.height - 1)))


def stripes(w, h, n):
    """n vertical bands, each a distinct colour, so a piece's colours show where it came from."""
    img = Image.new("RGB", (w, h))
    colours = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (255, 0, 255), (0, 255, 255)]
    for i in range(n):
        img.paste(colours[i], (i * w // n, 0, (i + 1) * w // n, h))
    return img, colours


three = [{"id": i, "screen": i, "x": 2560 * i, "y": 0, "w": 2560, "h": 1440} for i in range(3)]

# 1. 7680x1440 on three 2560x1440 side by side: exact thirds, no scaling
img, col = stripes(7680, 1440, 3)
p = run(img, three)
check(len(p) == 3, "three pieces")
check(all(p[str(i)].size == (2560, 1440) for i in range(3)), "each piece 2560x1440")
check(all(p[str(i)].getpixel((0, 0)) == col[i] and p[str(i)].getpixel((2559, 1439)) == col[i] for i in range(3)),
      "piece i is exactly band i (edge pixels)")

# 2. screens listed out of order and with a negative origin: placement by position, not by index
shuffled = [{"id": 7, "screen": 2, "x": -2560, "y": 0, "w": 2560, "h": 1440},
            {"id": 8, "screen": 0, "x": 2560, "y": 0, "w": 2560, "h": 1440},
            {"id": 9, "screen": 1, "x": 0, "y": 0, "w": 2560, "h": 1440}]
p = run(img, shuffled)
check(p["2"].getpixel((1280, 720)) == col[0] and p["1"].getpixel((1280, 720)) == col[1]
      and p["0"].getpixel((1280, 720)) == col[2], "leftmost screen gets the left of the image")

# 3. fit with a narrower image (16:9 on a 48:9 arrangement): whole image shown, black either side
img2, col2 = stripes(1920, 1080, 3)
p = run(img2, three)
check(all(abs(q.width / q.height - 16 / 9) < 0.01 for q in p.values()), "fit: pieces keep the screens' shape")
check(at(p["0"], 0.01, 0.5) == (0, 0, 0), "fit: left edge padded black")
check(at(p["1"], 0.5, 0.5) == col2[1], "fit: middle of image on the middle screen")
check(at(p["2"], 0.99, 0.5) == (0, 0, 0), "fit: right edge padded black")

# 4. fill with the same narrow image: no padding anywhere, overflow cropped top/bottom
p = run(img2, three, "--fill")
check(all((0, 0, 0) not in [px for _, px in p[k].getcolors(1 << 20)] for k in p), "fill: no padding")
check(at(p["0"], 0, 0) == col2[0] and at(p["2"], 1, 0) == col2[2], "fill: outer bands reach the outer screens")

# 5. mixed sizes: a 1080x1920 portrait screen to the right of two 2560x1440, top-aligned
mixed = [{"id": 0, "screen": 0, "x": 0, "y": 0, "w": 2560, "h": 1440},
         {"id": 1, "screen": 1, "x": 2560, "y": 0, "w": 2560, "h": 1440},
         {"id": 2, "screen": 2, "x": 5120, "y": 0, "w": 1080, "h": 1920}]
img3 = Image.new("RGB", (6200, 1920), (10, 20, 30))
img3.paste((200, 100, 50), (5120, 1440, 6200, 1920))  # the strip only the portrait screen covers
p = run(img3, mixed)
check(p["2"].size == (1080, 1920), f"portrait piece is 1080x1920 ({p['2'].size})")
check(p["2"].getpixel((540, 1700)) == (200, 100, 50), "portrait screen gets the area below the landscape ones")
check(p["0"].size == (2560, 1440) and p["0"].getpixel((100, 100)) == (10, 20, 30), "landscape piece unaffected")

# 6. JPEG input stays JPEG and is high quality
with tempfile.TemporaryDirectory() as t:
    src = os.path.join(t, "pano.jpg")
    img.save(src, quality=95)
    span.main([src, "--dry-run", "--out", os.path.join(t, "o"), "--screens", json.dumps(three)])
    outs = os.listdir(os.path.join(t, "o"))
    check(len(outs) == 3 and all(o.endswith(".jpg") for o in outs), "jpeg in, jpeg out")
    # re-running with a different arrangement replaces the old pieces
    span.main([src, "--dry-run", "--out", os.path.join(t, "o"), "--screens", json.dumps(three[:2])])
    check(len(os.listdir(os.path.join(t, "o"))) == 2, "old pieces removed on re-run")

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
