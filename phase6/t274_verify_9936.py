#!/usr/bin/env python3
"""Verify the disasm of 0x9936 and find all stores at any offset near 0x100."""
import os, sys, struct
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm 0x9936 directly (thumb)
print("=== disasm at 0x9936 ===")
for i in md.disasm(data[0x9936:0x9936+20], 0x9936, count=10):
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Now also check a wider scan: stores at ANY offset that matches a hex literal
# Let me print a sampling of all str instructions to see the format
print("\n=== sample of str/str.w insns across blob ===")
count = 0
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic == "str" and "#0x" in i.op_str:
            print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
            count += 1
            if count > 20:
                break
    if count > 20:
        break

# Look specifically for str pattern with offset 0x100
print("\n=== scan for stores at offset 0x100 (exact match '#0x100') ===")
count = 0
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic in ("str", "str.w"):
            # check all formats
            op = i.op_str.lower()
            if "#0x100" in op and "]" in op:
                print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
                count += 1
                if count > 30: break
    if count > 30: break
print(f"  total: {count}")
