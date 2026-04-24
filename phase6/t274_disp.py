import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

# Read value at 0x224
val = struct.unpack_from("<I", data, 0x224)[0]
print(f"[0x224] = {val:#x}")
# Bit 0 set = Thumb fn
if val & 1:
    body = val & ~1
    print(f"Target is Thumb fn at {body:#x}")
else:
    body = val
    print(f"Target is ARM fn at {body:#x}")

# Disasm target
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
print(f"\n=== disasm at {body:#x} (first 60 insns) ===")
for i in md.disasm(data[body:body+200], body, count=60):
    annot = ""
    # Detect STRs at #0x100 etc.
    if i.mnemonic.startswith(("str", "orr", "orrs")):
        annot = "  [STORE/OR]"
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                annot = f"  ← lit@{lit_addr:#x} = {v:#x}"
                if v == 0x6296C:
                    annot += "  [GLOBAL CTX PTR]"
        except Exception:
            pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
