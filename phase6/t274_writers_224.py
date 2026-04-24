"""Search for stores at offset #0x224 anywhere — that's how fw writes to
the ISR dispatch pointer if it uses a base+offset addressing mode."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Find str/str.w with immediate offset #0x224
print("=== stores at offset #0x224 ===")
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic in ("str", "str.w", "strh", "strh.w", "strb", "strb.w"):
            if "#0x224" in i.op_str and "]" in i.op_str:
                print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Also find str with #0x458 (0x358 + 0x100) — directly writing to pending-events-word
# via ctx+0x458
print("\n=== stores at offset #0x458 (ctx+0x358+0x100 if flat) ===")
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic in ("str", "str.w", "strh", "strh.w", "strb", "strb.w", "orr", "orr.w", "orrs"):
            if "#0x458" in i.op_str and "]" in i.op_str:
                print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# And check larger offsets too — #0x358 stores (which would be writing to ctx+0x358 itself)
print("\n=== stores at offset #0x358 (setting the ctx+0x358 ptr) ===")
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic in ("str", "str.w"):
            if "#0x358" in i.op_str and "]" in i.op_str:
                print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Also STRs with register offset — look for pattern "str r?, [r?, r?]" where the
# offset register was loaded with 0x100 earlier. Too general to grep precisely.

# Alternative: find ALL writes TO the pending-events word via pattern
# "orr.w rX, rX, #..." following a "ldr.w rX, [rY, #0x100]"
print("\n=== orr patterns preceded by ldr.w [r?, #0x100] ===")
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    insns = list(md.disasm(block, base, count=0))
    for idx, i in enumerate(insns):
        if i.mnemonic not in ("orr", "orr.w", "orrs", "orrs.w"):
            continue
        # Look back 3 insns
        ctx = insns[max(0, idx-3):idx]
        for prev in ctx:
            if prev.mnemonic in ("ldr", "ldr.w") and "#0x100]" in prev.op_str:
                print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
                for p in ctx + [i]:
                    print(f"    {p.address:#06x}: {p.mnemonic:<8} {p.op_str}")
                print()
                break
