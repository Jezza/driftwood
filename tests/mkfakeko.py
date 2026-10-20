#!/usr/bin/env python3
"""Write a minimal ELF64 relocatable whose only content is a .modinfo section.

  mkfakeko.py <out.ko> name=foo firmware=nvidia/a.bin ...

modinfo reads exactly this section, so it is enough to stand in for a real
kernel module in tests.
"""
import struct
import sys


def elf(modinfo: bytes) -> bytes:
    shstr = b"\0.modinfo\0.shstrtab\0"
    mi_off = 64
    str_off = mi_off + len(modinfo)
    shoff = (str_off + len(shstr) + 7) & ~7
    ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\0" * 8
    eh = ident + struct.pack("<HHIQQQIHHHHHH", 1, 62, 1, 0, 0, shoff, 0, 64, 0, 0, 64, 3, 2)
    body = eh + modinfo + shstr
    body += b"\0" * (shoff - len(body))
    sh = b"\0" * 64
    sh += struct.pack("<IIQQQQIIQQ", 1, 1, 0, 0, mi_off, len(modinfo), 0, 0, 1, 0)
    sh += struct.pack("<IIQQQQIIQQ", 10, 3, 0, 0, str_off, len(shstr), 0, 0, 1, 0)
    return body + sh


out, fields = sys.argv[1], sys.argv[2:]
with open(out, "wb") as f:
    f.write(elf(b"".join(x.encode() + b"\0" for x in fields)))
