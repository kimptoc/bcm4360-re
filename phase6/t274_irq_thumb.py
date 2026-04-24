#!/usr/bin/env python3
"""Re-disasm first 0x80 bytes as Thumb, since the 0xF000 0xBxxx pattern is Thumb-2 b.w."""
import os, sys, struct
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

print("=== disasm 0x00..0x80 as Thumb ===")
for i in md.disasm(data[:0x80], 0, count=0):
    print(f"  {i.address:#04x}: {i.mnemonic:<8} {i.op_str}")
