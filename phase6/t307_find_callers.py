"""T307c — find every direct-BL caller of register_cc_isr at fn@0x63AC4.

Strategy: scan blob for Thumb-2 BL instructions whose target = 0x63AC4.
Then disasm a window around each caller to identify what {fn, mask, arg}
they register.

Thumb-2 BL encoding (32-bit):
   11110 S imm10  11 J1 1 J2 imm11
   First halfword: 0xF000 | (S<<10) | imm10
   Second halfword: 0xD000 | (J1<<13) | (1<<12) | (J2<<11) | imm11

Target = PC + 4 + sign_extend(S:I1:I2:imm10:imm11:0)
where I1 = NOT(J1 XOR S), I2 = NOT(J2 XOR S).
"""
import struct
import sys
import os

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from t269_disasm import Cs

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
TARGET = 0x63AC4


def decode_bl(blob, off):
    if off + 4 > len(blob):
        return None
    h0, h1 = struct.unpack_from("<HH", blob, off)
    # BL: first halfword 11110 S imm10 = 0xF000 (with S in bit 10)
    if (h0 & 0xF800) != 0xF000:
        return None
    # BL: second halfword 11 J1 1 J2 imm11 = 0xD000..0xFFFF with bit 12 = 1
    if (h1 & 0xD000) != 0xD000:
        return None
    S = (h0 >> 10) & 1
    imm10 = h0 & 0x3FF
    J1 = (h1 >> 13) & 1
    J2 = (h1 >> 11) & 1
    imm11 = h1 & 0x7FF
    I1 = 1 - (J1 ^ S)
    I2 = 1 - (J2 ^ S)
    imm = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
    if S:
        imm |= ~((1 << 25) - 1)  # sign-extend
        imm &= 0xFFFFFFFF
        imm = imm if imm < (1 << 31) else imm - (1 << 32)
    pc = off + 4
    target = (pc + imm) & 0xFFFFFFFF
    return target


def find_bl_callers(blob, target):
    hits = []
    n = len(blob)
    for off in range(0, n - 4, 2):
        t = decode_bl(blob, off)
        if t == target:
            hits.append(off)
    return hits


def disasm_window(blob, addr, before=40, after=8):
    md = Cs()
    start = max(0, addr - before)
    end = min(len(blob), addr + after)
    chunk = blob[start:end]
    return list(md.disasm(chunk, start))


def main():
    with open(BLOB, "rb") as f:
        blob = f.read()
    hits = find_bl_callers(blob, TARGET)
    print(f"# T307c: callers of register_cc_isr (fn@0x{TARGET:05X})")
    print(f"# blob = {BLOB} ({len(blob)} bytes)")
    print(f"# direct-BL hits: {len(hits)}")
    print()
    for h in hits:
        print(f"# === caller @ 0x{h:05X} ===")
        ins_list = disasm_window(blob, h)
        for ins in ins_list:
            mark = "  > " if ins.address == h else "    "
            b = " ".join(f"{x:02x}" for x in ins.bytes)
            print(f"{mark}0x{ins.address:05X}: {b:<14} {ins.mnemonic:<8} {ins.op_str}")
        print()


if __name__ == "__main__":
    main()
