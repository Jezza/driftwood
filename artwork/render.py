#!/usr/bin/env python3
"""Render an SVG (or an HTML page) to PNG with headless Chromium at an exact size."""
import subprocess, sys, os, tempfile
src, out, w, h = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4])
transparent = len(sys.argv) > 5 and sys.argv[5] == "transparent"
src = os.path.abspath(src)
if src.endswith(".svg"):
    html = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, dir=os.environ.get("TMPDIR"))
    html.write(f"<html><body style='margin:0;background:transparent'><img src='file://{src}' style='width:{w}px;height:{h}px;display:block'></body></html>")
    html.close()
    page = html.name
else:
    page = src
cmd = [os.path.expanduser("~/.local/bin/chromium"), "--headless", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
       f"--window-size={w},{h}", f"--screenshot={os.path.abspath(out)}", "--force-device-scale-factor=1"]
if transparent:
    cmd.append("--default-background-color=00000000")
subprocess.run(cmd + ["file://" + page], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)
print(out)
