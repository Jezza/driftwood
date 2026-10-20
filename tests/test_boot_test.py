#!/usr/bin/env python3
"""Unit tests for ci/boot-test.py's pure parts: pcap/DHCP parsing, PPM->PNG, serial analysis."""
import importlib.util
import os
import struct
import sys
import tempfile
import zlib

here = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("boot_test", os.path.join(here, "..", "ci", "boot-test.py"))
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)

fails = 0


def check(cond, msg):
    global fails
    print(("PASS " if cond else "FAIL ") + msg)
    fails += 0 if cond else 1


def udp_frame(sport, dport, payload, proto=17):
    udp = struct.pack(">HHHH", sport, dport, 8 + len(payload), 0) + payload
    ip = struct.pack(">BBHHHBBH4s4s", 0x45, 0, 20 + len(udp), 0, 0, 64, proto, 0, b"\0" * 4, b"\xff" * 4) + udp
    return b"\xff" * 6 + b"\x52\x54\x00\x12\x34\x56" + b"\x08\x00" + ip


def dhcp(msg_type):
    bootp = bytearray(236)
    bootp[0] = 1
    return bytes(bootp) + b"\x63\x82\x53\x63" + bytes([12, 4]) + b"spin" + bytes([53, 1, msg_type, 255])


def pcap(frames):
    out = struct.pack("<IHHiIII", 0xA1B2C3D4, 2, 4, 0, 0, 65535, 1)
    for i, f in enumerate(frames):
        out += struct.pack("<IIII", 1000 + i, 0, len(f), len(f)) + f
    return out


with tempfile.TemporaryDirectory(dir=os.environ.get("TMPDIR")) as t:
    p = os.path.join(t, "n.pcap")
    open(p, "wb").write(pcap([udp_frame(5353, 5353, b"mdns"), udp_frame(68, 67, dhcp(1)),
                              udp_frame(67, 68, dhcp(2)), udp_frame(68, 67, dhcp(3))]))
    msgs = [m for _, m in bt.dhcp_messages(p)]
    check(msgs == [1, 3], f"DHCP from client only, after DHCP option 12 is skipped: {msgs}")
    open(p, "wb").write(pcap([udp_frame(68, 67, dhcp(1))])[:-10])
    check(list(bt.dhcp_messages(p)) == [], "truncated packet ignored")
    check(list(bt.dhcp_messages(os.path.join(t, "missing"))) == [], "missing pcap: no messages")
    open(p, "wb").write(b"")
    check(list(bt.dhcp_messages(p)) == [], "empty pcap (QEMU just started)")

    ppm = os.path.join(t, "s.ppm")
    w, h = 3, 2
    pixels = bytes(range(w * h * 3))
    open(ppm, "wb").write(b"P6\n%d %d\n255\n" % (w, h) + pixels)
    png = os.path.join(t, "s.png")
    bt.ppm_to_png(ppm, png)
    d = open(png, "rb").read()
    ihdr = struct.unpack(">IIBBBBB", d[16:29])
    idat_len = struct.unpack(">I", d[33:37])[0]
    raw = zlib.decompress(d[41:41 + idat_len])
    check(d[:8] == b"\x89PNG\r\n\x1a\n" and ihdr[:2] == (3, 2), "PNG header and size")
    check(raw == b"\0" + pixels[:9] + b"\0" + pixels[9:], "PNG pixels match the PPM")

log = """[    0.000000] Linux version 6.12.48+deb13-amd64 (debian-kernel@lists.debian.org)
[  OK  ] Reached target multi-user.target - Multi-User System.
[FAILED] Failed to start foo.service - Foo Daemon.
bar.service: Failed with result 'exit-code'.
[  OK  ] Started sddm.service - Simple Desktop Display Manager.
[  OK  ] Started session-2.scope - Session 2 of User linux.
[  OK  ] Reached target graphical.target - Graphical Interface.
plasmashell[1234]: org.kde.plasma.shell: ...
"""
a = bt.analyse_serial(log)
check(a["graphical_target"] and a["sddm"] and a["plasmashell"] and a["autologin_session"], "desktop markers found")
check(a["failed_to_start"] == ["foo.service - Foo Daemon"] and a["failed_units"] == ["bar.service"], f"failures: {a['failed_to_start']} {a['failed_units']}")
check(a["kernel"].startswith("[    0.000000] Linux version 6.12.48"), "kernel line")
check(not (a["kernel_panic"] or a["emergency"] or a["live_boot_failed"]), "no fatal markers")
b = bt.analyse_serial("Unable to find a medium containing a live file system\n---[ end Kernel panic - not syncing")
check(b["live_boot_failed"] and b["kernel_panic"], "fatal markers found")

print(f"{fails} failure(s)")
sys.exit(1 if fails else 0)
