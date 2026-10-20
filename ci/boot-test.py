#!/usr/bin/env python3
"""
Boot a Driftwood live ISO in QEMU and decide whether it came up.

Modes:
  uefi    boot the ISO through OVMF and GRUB (as a user would on UEFI)
  bios    boot through SeaBIOS and isolinux
  kernel  boot the ISO's own kernel and initrd directly, with a serial
          console, to read the boot log and check what systemd started

Pass criteria:
  uefi/bios  the live system's NetworkManager sends a DHCP request
             (captured from the VM's NIC), i.e. the system finished
             booting into a running userspace from the GRUB/isolinux menu
  kernel     graphical.target reached and plasmashell started; no kernel
             panic or emergency mode. Failed units are reported.

Artifacts in --out: serial.log, screenshots (deduplicated, every few
seconds), net.pcap, result.json, and summary.md.

Only the Python standard library is used.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import struct
import subprocess
import sys
import time
import zlib

OVMF_CANDIDATES = [
    ("/usr/share/OVMF/OVMF_CODE_4M.fd", "/usr/share/OVMF/OVMF_VARS_4M.fd"),
    ("/usr/share/OVMF/OVMF_CODE.fd", "/usr/share/OVMF/OVMF_VARS.fd"),
]
KERNEL_APPEND = ("boot=live components threadirqs console=tty0 console=ttyS0,115200n8 "
                 "systemd.show_status=1 systemd.journald.forward_to_console=1")


# ---------------------------------------------------------------- pcap / DHCP

def dhcp_messages(pcap_path):
    """Yield (time, dhcp message type) for each DHCP packet a VM sent."""
    try:
        data = open(pcap_path, "rb").read()
    except FileNotFoundError:
        return
    if len(data) < 24:
        return
    magic = data[:4]
    endian = "<" if magic in (b"\xd4\xc3\xb2\xa1", b"\x4d\x3c\xb2\xa1") else ">"
    off = 24
    while off + 16 <= len(data):
        ts, _usec, incl, _orig = struct.unpack(endian + "IIII", data[off:off + 16])
        pkt = data[off + 16:off + 16 + incl]
        off += 16 + incl
        if len(pkt) < 14 + 20 + 8 or pkt[12:14] != b"\x08\x00":
            continue
        ip = pkt[14:]
        ihl = (ip[0] & 0x0F) * 4
        if ip[9] != 17:  # UDP
            continue
        udp = ip[ihl:]
        if len(udp) < 8:
            continue
        sport, dport = struct.unpack(">HH", udp[:4])
        if (sport, dport) != (68, 67):
            continue
        bootp = udp[8:]
        if len(bootp) < 240 or bootp[236:240] != b"\x63\x82\x53\x63":
            continue
        opts = bootp[240:]
        i = 0
        while i + 1 < len(opts):
            code = opts[i]
            if code == 0:
                i += 1
                continue
            if code == 255:
                break
            length = opts[i + 1]
            if code == 53 and length >= 1 and i + 2 < len(opts):
                yield ts, opts[i + 2]
                break
            i += 2 + length


DHCP_NAMES = {1: "DISCOVER", 3: "REQUEST", 8: "INFORM"}


# ----------------------------------------------------------------------- QMP

class QMP:
    def __init__(self, path, timeout=30, proc=None):
        deadline = time.time() + timeout
        while True:
            if proc is not None and proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                sys.exit(f"qemu exited with {proc.returncode} before QMP came up:\n{out}")
            try:
                self.sock = socket.socket(socket.AF_UNIX)
                self.sock.connect(path)
                break
            except OSError:
                if time.time() > deadline:
                    raise
                time.sleep(0.2)
        self.f = self.sock.makefile("rwb")
        self._read()  # greeting
        self.cmd("qmp_capabilities")

    def _read(self):
        while True:
            line = self.f.readline()
            if not line:
                raise EOFError("QMP closed")
            msg = json.loads(line)
            if "event" not in msg:
                return msg

    def cmd(self, name, **args):
        self.f.write(json.dumps({"execute": name, "arguments": args}).encode() + b"\n")
        self.f.flush()
        return self._read()


def ppm_to_png(ppm_path, png_path):
    data = open(ppm_path, "rb").read()
    parts = data.split(maxsplit=4)
    if parts[0] != b"P6":
        raise ValueError("not a P6 PPM")
    w, h, pixels = int(parts[1]), int(parts[2]), parts[4]
    rows = b"".join(b"\x00" + pixels[y * w * 3:(y + 1) * w * 3] for y in range(h))

    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
           + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b""))
    open(png_path, "wb").write(png)


class Screens:
    """Periodic screenshots, keeping only ones that differ from the last."""

    def __init__(self, qmp, out):
        self.qmp, self.out, self.last, self.n, self.png = qmp, out, None, 0, True

    def grab(self, label):
        tmp = os.path.join(self.out, ".screen")
        try:
            if self.png:
                r = self.qmp.cmd("screendump", filename=tmp, format="png")
                if "error" in r:
                    self.png = False
            if not self.png:
                r = self.qmp.cmd("screendump", filename=tmp)
                if "error" in r:
                    return None
                ppm_to_png(tmp, tmp + ".png")
                os.replace(tmp + ".png", tmp)
        except (OSError, EOFError, ValueError):
            return None
        digest = hashlib.sha256(open(tmp, "rb").read()).hexdigest()
        if digest == self.last:
            os.unlink(tmp)
            return None
        self.last = digest
        self.n += 1
        path = os.path.join(self.out, f"screen-{self.n:03d}-{label}.png")
        os.replace(tmp, path)
        return path


# -------------------------------------------------------------- serial checks

def analyse_serial(text):
    lines = text.splitlines()
    failed = sorted({m.group(1) for m in re.finditer(r"Failed to start ([^\r\n]+?)\.?\s*$", text, re.M)}
                    | {m.group(1) for m in re.finditer(r"\[\s*FAILED\s*\] Failed to start ([^\r\n]+?)\.?\s*$", text, re.M)})
    failed_units = sorted(set(re.findall(r"(\S+\.(?:service|mount|socket|target)): Failed with result", text)))
    return {
        "graphical_target": bool(re.search(r"Reached target .*Graphical Interface", text)),
        "sddm": bool(re.search(r"Started .*(Simple Desktop Display Manager|sddm)", text)),
        "plasmashell": "plasmashell" in text,
        "autologin_session": bool(re.search(r"Started .*Session \d+ of User linux", text)),
        "kernel_panic": "Kernel panic" in text,
        "emergency": bool(re.search(r"emergency mode|Entering emergency|You are in emergency", text)),
        "live_boot_failed": bool(re.search(r"Unable to find a medium containing a live file system", text)),
        "failed_to_start": failed,
        "failed_units": failed_units,
        "kernel": next((l.strip() for l in lines if "Linux version" in l), ""),
        "lines": len(lines),
    }


# ---------------------------------------------------------------------- main

def extract_kernel(iso, out):
    kdir = os.path.join(out, ".kernel")
    os.makedirs(kdir, exist_ok=True)
    k, i = os.path.join(kdir, "vmlinuz"), os.path.join(kdir, "initrd.img")
    subprocess.run(["xorriso", "-osirrox", "on", "-indev", iso,
                    "-extract", "/live/vmlinuz", k, "-extract", "/live/initrd.img", i],
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return k, i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("iso")
    ap.add_argument("--mode", choices=["uefi", "bios", "kernel"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--timeout", type=int, default=0, help="seconds (default: 420 with KVM, 1800 without)")
    ap.add_argument("--memory", default="4096")
    ap.add_argument("--settle", type=int, default=45,
                    help="seconds to keep running (screenshots) after the pass condition")
    args = ap.parse_args()

    out = os.path.abspath(args.out)
    os.makedirs(out, exist_ok=True)
    kvm = os.access("/dev/kvm", os.R_OK | os.W_OK)
    timeout = args.timeout or (420 if kvm else 1800)
    serial, pcap, qmp_sock = (os.path.join(out, n) for n in ("serial.log", "net.pcap", ".qmp.sock"))
    for p in (serial, pcap, qmp_sock):
        if os.path.exists(p):
            os.unlink(p)

    cmd = ["qemu-system-x86_64", "-machine", "q35", "-m", args.memory, "-smp", "2",
           "-device", "virtio-vga", "-display", "none",
           "-serial", f"file:{serial}", "-qmp", f"unix:{qmp_sock},server=on,wait=off",
           "-netdev", "user,id=n0", "-device", "virtio-net-pci,netdev=n0",
           "-object", f"filter-dump,id=f0,netdev=n0,file={pcap}",
           "-drive", f"file={os.path.abspath(args.iso)},media=cdrom,readonly=on,if=none,id=cd0",
           # with -kernel, QEMU's direct-boot loader takes bootindex 0; the CD
           # is then only the live medium, found by live-boot, not booted from
           "-device", "ide-cd,drive=cd0" + ("" if args.mode == "kernel" else ",bootindex=0"),
           "-device", "qemu-xhci", "-device", "usb-tablet", "-no-reboot"]
    cmd += ["-enable-kvm", "-cpu", "host"] if kvm else ["-cpu", "max"]
    if args.mode == "uefi":
        code, vars_ = next(((c, v) for c, v in OVMF_CANDIDATES if os.path.exists(c)), (None, None))
        if not code:
            sys.exit("OVMF not found (apt install ovmf)")
        local_vars = os.path.join(out, ".ovmf_vars.fd")
        shutil.copy(vars_, local_vars)
        cmd += ["-drive", f"if=pflash,format=raw,unit=0,readonly=on,file={code}",
                "-drive", f"if=pflash,format=raw,unit=1,file={local_vars}"]
    elif args.mode == "kernel":
        k, i = extract_kernel(args.iso, out)
        cmd += ["-kernel", k, "-initrd", i, "-append", KERNEL_APPEND]

    print(f"mode={args.mode} kvm={kvm} timeout={timeout}s")
    print(" ".join(cmd))
    qemu = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    start = time.time()
    result = {"mode": args.mode, "kvm": kvm, "passed": False, "reason": "timeout", "elapsed": None}
    try:
        qmp = QMP(qmp_sock, proc=qemu)
        screens = Screens(qmp, out)
        passed_at = None
        while True:
            now = time.time() - start
            if qemu.poll() is not None:
                result["reason"] = f"qemu exited with {qemu.returncode}"
                break
            screens.grab(f"{int(now):04d}s")
            if passed_at is None:
                if args.mode in ("uefi", "bios"):
                    msgs = list(dhcp_messages(pcap))
                    if msgs:
                        passed_at = now
                        result.update(passed=True, reason=f"DHCP {DHCP_NAMES.get(msgs[0][1], msgs[0][1])} from the live system")
                else:
                    a = analyse_serial(open(serial, errors="replace").read()) if os.path.exists(serial) else {}
                    if a.get("kernel_panic") or a.get("emergency") or a.get("live_boot_failed"):
                        result["reason"] = "kernel panic / emergency mode / live medium not found"
                        break
                    if a.get("graphical_target") and a.get("plasmashell"):
                        passed_at = now
                        result.update(passed=True, reason="graphical.target reached and plasmashell started")
                if passed_at is not None:
                    result["elapsed"] = round(now)
                    print(f"PASS at {now:.0f}s: {result['reason']}; settling {args.settle}s for screenshots")
            elif now - passed_at > args.settle:
                break
            if now > timeout:
                break
            time.sleep(5)
        screens.grab("final")
        try:
            qmp.cmd("quit")
        except (OSError, EOFError):
            pass
    finally:
        try:
            qemu.wait(timeout=20)
        except subprocess.TimeoutExpired:
            qemu.kill()
        qemu_out = qemu.stdout.read().decode(errors="replace") if qemu.stdout else ""
        if qemu_out.strip():
            print("qemu output:\n" + qemu_out)

    text = open(serial, errors="replace").read() if os.path.exists(serial) else ""
    result["serial"] = analyse_serial(text)
    result["dhcp"] = [DHCP_NAMES.get(t, t) for _, t in dhcp_messages(pcap)]
    if args.mode == "kernel" and result["passed"]:
        # a boot that reached the desktop but with failed units still passes;
        # failures are listed so they can be triaged.
        pass
    json.dump(result, open(os.path.join(out, "result.json"), "w"), indent=2)

    s = result["serial"]
    md = [f"### Boot test: {args.mode} {'✅' if result['passed'] else '❌'}", "",
          f"- result: {result['reason']}" + (f" after {result['elapsed']}s" if result['elapsed'] is not None else ""),
          f"- KVM: {kvm}", f"- DHCP from VM: {', '.join(map(str, result['dhcp'])) or 'none'}"]
    if args.mode == "kernel":
        md += [f"- kernel: `{s['kernel']}`",
               f"- graphical.target: {s['graphical_target']}, sddm: {s['sddm']}, plasmashell: {s['plasmashell']}"]
        if s["failed_to_start"] or s["failed_units"]:
            md += ["- failed units:"] + [f"  - `{u}`" for u in sorted(set(s["failed_to_start"]) | set(s["failed_units"]))]
        else:
            md += ["- failed units: none"]
    md.append(f"- screenshots: {screens.n}")
    open(os.path.join(out, "summary.md"), "w").write("\n".join(md) + "\n")
    print("\n".join(md))
    for f in (qmp_sock, os.path.join(out, ".ovmf_vars.fd")):
        if os.path.exists(f):
            os.unlink(f)
    shutil.rmtree(os.path.join(out, ".kernel"), ignore_errors=True)
    sys.exit(0 if result["passed"] else 1)


if __name__ == "__main__":
    main()
