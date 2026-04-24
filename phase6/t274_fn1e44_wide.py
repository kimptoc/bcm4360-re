"""Wider disasm around 0x1E44 — possibly my prologue scanner false-positived."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm 0x1E44 forward for 400 bytes
print("=== disasm 0x1E44 forward ~200 insns ===")
for i in md.disasm(data[0x1E44:0x1E44+400], 0x1E44, count=120):
    annot = ""
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t == 0xA30: annot = "  ← printf"
            elif t == 0x14948: annot = "  ← trace"
            elif t == 0x1ADC: annot = "  ← DELAY helper"
            elif t == 0x11e8: annot = "  ← printf/assert"
        except: pass
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                if 0 < v < len(data):
                    s = bytearray()
                    for k in range(60):
                        if v + k >= len(data): break
                        c = data[v + k]
                        if c == 0: break
                        if 32 <= c < 127: s.append(c)
                        else: s = None; break
                    if s and len(s) >= 4:
                        annot = f"  '{s.decode('ascii')}'"
                    elif annot == "":
                        annot = f"  lit = {v:#x}"
        except: pass
    if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t < i.address:
                dist = i.address - t
                annot += f"  [BACKWARD dist={dist}]"
                if dist < 32: annot += " TIGHT"
        except: pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
