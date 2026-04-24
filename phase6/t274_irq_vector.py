#!/usr/bin/env python3
"""Look at the ARM vector table (first 0x80 bytes) and trace the IRQ handler.
Also search for register-offset stores and add+str patterns that would hit
a pending-events word.
"""
import os, sys, struct
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_ARCH_ARM

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md_thumb = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md_arm = Cs(CS_ARCH_ARM, 0)  # ARM mode

# Vector table at offset 0 (classic ARM): 8 entries of 4 bytes each
# [0x00] Reset
# [0x04] Undefined
# [0x08] SWI
# [0x0c] Prefetch abort
# [0x10] Data abort
# [0x14] Reserved
# [0x18] IRQ
# [0x1c] FIQ
print("=== ARM vector table (first 0x20 bytes) ===")
for off in range(0, 0x20, 4):
    word = struct.unpack_from("<I", data, off)[0]
    print(f"  [{off:#04x}] = {word:#010x}")

# The ARM VT usually contains load instructions. Let me disasm them as ARM.
print("\n=== disasm as ARM at 0x00..0x20 ===")
for i in md_arm.disasm(data[:0x80], 0, count=20):
    print(f"  {i.address:#04x}: {i.mnemonic:<8} {i.op_str}")

# If the handlers use LDR PC, [PC, #...] to jump to the actual handler address,
# the target addresses are stored in the table right after.
# Many Broadcom RTE firmware use a more complex setup — let me inspect further.

# Meanwhile, scan for add-with-0x100 computing ctx pointers, followed by str
print("\n=== scan for 'add rX, rY, #0x100' patterns (then look for neighboring str) ===")
CHUNK = 64 * 1024
candidates = []
for base in range(0, len(data), CHUNK):
    block = data[base:base + CHUNK + 8]
    insns = list(md_thumb.disasm(block, base, count=0))
    for idx, i in enumerate(insns):
        if i.mnemonic in ("add", "add.w", "adds") and "#0x100" in i.op_str:
            candidates.append((i.address, i, insns[max(0, idx-3):idx+4]))

print(f"  {len(candidates)} hits")
for addr, ins, ctx in candidates[:15]:
    print(f"\n  {addr:#06x}: {ins.mnemonic:<8} {ins.op_str}")
    for ii in ctx:
        print(f"    {ii.address:#06x}: {ii.mnemonic:<8} {ii.op_str}")

# Also: search for literal 0x6296c in a wider context and see ALL code refs
print("\n=== code refs that load literal 0x6296c (the global ctx ptr) ===")
tgt = struct.pack("<I", 0x6296C)
hits = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"  literal pool entries: {[hex(h) for h in hits]}")
# For each, find ldr instructions that reference it
for lit in hits:
    for base in range(max(0, lit - 4096), lit, 2):
        hw = struct.unpack_from("<H", data, base)[0]
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            lit_addr = ((base + 4) & ~3) + imm8 * 4
            if lit_addr == lit:
                print(f"    T1 ldr at {base:#06x} -> lit {lit:#x}")
        if base + 4 <= len(data):
            hw2 = struct.unpack_from("<H", data, base + 2)[0]
            if hw == 0xF8DF or hw == 0xF85F:
                imm12 = hw2 & 0xFFF
                add = (hw & 0x0080) != 0
                lit_addr = ((base + 4) & ~3) + (imm12 if add else -imm12)
                if lit_addr == lit:
                    print(f"    T2.W ldr.w at {base:#06x} -> lit {lit:#x}")
