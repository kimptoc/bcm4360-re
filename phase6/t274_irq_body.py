#!/usr/bin/env python3
"""Disasm the IRQ handler body starting at 0xF8."""
import os, sys, struct
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

print("=== IRQ handler at 0xF8 ===")
for i in md.disasm(data[0xF8:0xF8+200], 0xF8, count=60):
    # Annotate ldr pc-rel
    annot = ""
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                annot = f"  ← lit@{lit_addr:#x} = {v:#x}"
        except Exception:
            pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
