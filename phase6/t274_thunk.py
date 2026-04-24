"""Disasm the 9-thunk vector at 0x99AC..0x99C8 and all targets in the 0x27EC region."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm the 9-thunk vector
print("=== 9-thunk vector at 0x99AC..0x99C8 ===")
for off in range(0x99AC, 0x99D0, 4):
    insns = list(md.disasm(data[off:off+8], off, count=2))
    for i in insns:
        print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Per T269, each thunk is a b.w to a target in 0x27xx..0x2Axx.
# Extract target addresses and disasm each
print("\n=== targets of each thunk ===")
targets = set()
for off in range(0x99AC, 0x99D0, 4):
    insns = list(md.disasm(data[off:off+4], off, count=1))
    for i in insns:
        if i.mnemonic == "b.w" and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                targets.add(t)
            except ValueError:
                pass

for t in sorted(targets):
    print(f"\n  --- target {t:#x} ---")
    # Check if prologue is a real function
    for i in md.disasm(data[t:t+60], t, count=12):
        annot = ""
        if i.mnemonic in ("str", "str.w") and "#0x100" in i.op_str:
            annot = "  [WRITE to #0x100 !!]"
        elif i.mnemonic.startswith("orr") and "#" in i.op_str:
            annot = "  [OR constant]"
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  ← lit = {v:#x}"
            except Exception:
                pass
        print(f"    {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
