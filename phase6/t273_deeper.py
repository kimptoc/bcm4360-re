#!/usr/bin/env python3
"""T273 deeper: drill into sub-helpers called from 0x179C8
(wlc_bmac_validate_chip_access) and resolve the 2-insn stub at 0x67E1C.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_next_prologue(start, max_scan=4096):
    for off in range(start + 2, min(start + max_scan, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None


def dump_fn(name, addr, dump_body=False):
    print(f"\n{'='*70}")
    print(f"=== {name} @ {addr:#06x} ===")
    nxt = find_next_prologue(addr)
    ext = (nxt - addr) if nxt else 512
    ext = min(ext, 1024)
    print(f"  extent ~{ext} bytes (next prologue at {nxt:#x})")
    insns = list(md.disasm(data[addr:addr+ext+16], addr, count=0))
    insns = [i for i in insns if i.address < addr + ext]

    # Summarize
    from collections import Counter
    backward = [(i.address, int(i.op_str[1:], 16)) for i in insns
                if i.mnemonic.startswith(("b", "bl")) and i.op_str.startswith("#")
                and i.mnemonic not in ("bl", "blx")
                and int(i.op_str[1:], 16) < i.address]
    bl_calls = Counter()
    strs = set()
    for i in insns:
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                bl_calls[int(i.op_str[1:], 16)] += 1
            except ValueError:
                pass
        if i.mnemonic in ("ldr", "ldr.w") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    if 0 < v < len(data):
                        s = bytearray()
                        for k in range(80):
                            if v + k >= len(data): break
                            c = data[v + k]
                            if c == 0: break
                            if 32 <= c < 127: s.append(c)
                            else: s = None; break
                        if s and len(s) >= 4:
                            strs.add(s.decode("ascii"))
            except Exception:
                pass

    print(f"  {len(insns)} insns, {len(backward)} backward branches, "
          f"{sum(bl_calls.values())} BL calls to {len(bl_calls)} targets")
    if backward:
        print(f"  backward branches:")
        for ia, tgt in backward[:10]:
            tight = (ia - tgt) < 24
            print(f"    {ia:#06x}: back to {tgt:#x}  (dist {ia-tgt}){' TIGHT' if tight else ''}")
    if bl_calls:
        print(f"  top BL targets:")
        for t, c in bl_calls.most_common(8):
            print(f"    bl #{t:#06x}  x{c}")
    if strs:
        print(f"  strings: {sorted(strs)[:8]}")

    if dump_body:
        print(f"  body:")
        for i in insns[:80]:
            print(f"    {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")


# 0x67E1C is 2 insns - just print it
print("=== 0x67E1C (2-insn stub) — full body ===")
for i in md.disasm(data[0x67E1C:0x67E1C+16], 0x67E1C, count=4):
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# 0x67F2C already shown as dispatcher — dump it for reference
print("\n=== 0x67F2C (10-insn dispatcher) — full body ===")
for i in md.disasm(data[0x67F2C:0x67F2C+30], 0x67F2C, count=10):
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Now the interesting ones: sub-helpers of wlc_bmac_validate_chip_access
dump_fn("0x16358 (called 3× from wlc_bmac_validate_chip_access)", 0x16358, dump_body=True)
dump_fn("0x16790 (called 3× from wlc_bmac_validate_chip_access)", 0x16790, dump_body=True)

# Also the targets of 0x67F2C dispatcher
dump_fn("0x67358 (branch target from 0x67F2C — also called from pcidongle_probe)", 0x67358)
dump_fn("0x66F6C (branch target from 0x67F2C)", 0x66F6C)
