"""T269: decode what's at blob 0x5000C (contains the 0x48=MAILBOXINT offset)
and 0x56AD8 / 0x5002C (MAILBOXMASK 0x4C offset). Likely a register-metadata
table used by a helper function to access mailbox regs.

Also dump the region around pciedngl_isr printf format strings (blob 0x40680+)
to see the full string neighborhood, and look at what's at 0x58CC4-0x58D00
(pciedev_info struct initializer).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs

BLOB = "/home/kimptoc/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    blob = f.read()
md = Cs()


def u32(off):
    return int.from_bytes(blob[off:off + 4], "little")


def u16(off):
    return int.from_bytes(blob[off:off + 2], "little")


def ascii_str(off, maxlen=64):
    s = []
    for i in range(maxlen):
        b = blob[off + i]
        if b == 0:
            break
        if 32 <= b < 127:
            s.append(chr(b))
        else:
            return None
    return "".join(s) if s else None


def dump_range(start, end, label):
    print(f"\n=== {label} 0x{start:X}..0x{end:X} ===")
    for off in range(start, end, 4):
        v = u32(off)
        note = ""
        if 0 < v < len(blob):
            s = ascii_str(v)
            if s and len(s) > 2:
                note = f' -> "{s}"'
        print(f"  0x{off:06X}: 0x{v:08X}{note}")


# 0x5000C region: +0x48 appeared as value. Dump 0x4FFE0..0x50050 (nearby).
dump_range(0x4FFE0, 0x50060, "MAILBOXINT offset candidate region A (0x5000C)")
dump_range(0x53800, 0x53840, "MAILBOXMASK offset candidate region B (0x5381C)")
dump_range(0x56AC0, 0x56B00, "region C (0x56AD8 hit)")

# pciedngl_isr string neighborhood
print("\n=== String table @ 0x40600..0x40780 (pciedngl_isr strings) ===")
pos = 0x40600
while pos < 0x40780:
    start = pos
    while pos < 0x40780 and blob[pos] >= 32 and blob[pos] < 127:
        pos += 1
    if pos > start:
        s = blob[start:pos].decode("ascii", "replace")
        print(f"  0x{start:06X}: {s!r}")
    # skip nulls
    while pos < 0x40780 and blob[pos] < 32:
        pos += 1

# pciedev_info struct initializer at 0x58CC4
print("\n=== pciedev struct initializer @ 0x58CC4..0x58D40 ===")
for off in range(0x58CC4, 0x58D40, 4):
    v = u32(off)
    note = ""
    if 0 < v < len(blob):
        s = ascii_str(v)
        if s and len(s) > 2:
            note = f' -> "{s}"'
        elif v < 0x6C000:
            # maybe a fn ptr (code)
            if v & 1:
                note = " (maybe thumb fn-ptr)"
    elif 0x80000 <= v < 0xA0000:
        note = " (TCM BSS/heap)"
    print(f"  0x{off:06X}: 0x{v:08X}{note}")

# Disassemble the function at 0x9948 (the next entry after 0x9936 at looks like
# a related getter for a different event-class)
print("\n=== What is at 0x9948? (next getter after 0x9936) ===")
for ins in md.disasm(blob[0x9948:0x9970], 0x9948):
    print(f"  0x{ins.address:06X}: {ins.mnemonic:<10} {ins.op_str}")
