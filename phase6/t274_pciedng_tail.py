"""Disasm pcidongle_probe (0x1E90) tail after the hndrte_add_isr call
(which is at blob offset 0x1F28 per T269). Find sharedram publish site."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# pcidongle_probe starts at 0x1E90. Next prologue?
# Find next prologue
def nxt(start):
    for off in range(start + 2, min(start+4096, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None
n = nxt(0x1E90)
print(f"pcidongle_probe extent ~{n - 0x1E90} bytes (next fn at {n:#x})")

# Full disasm of pcidongle_probe
print("\n=== pcidongle_probe full body ===")
ins_list = list(md.disasm(data[0x1E90:n], 0x1E90, count=0))
for i in ins_list:
    annot = ""
    # Call annotations
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t == 0x63C24:
                annot = "  ← HNDRTE_ADD_ISR (registration point)"
            elif t == 0xA30:
                annot = "  ← printf"
            elif t == 0x9948 or t == 0x9964:
                annot = "  ← class-dispatch helper"
            elif t == 0x7D60 or t == 0x7D68 or t == 0x7D6E:
                annot = "  ← alloc helper"
            elif t == 0x91C:
                annot = "  ← memset/bzero"
            elif t == 0x1298:
                annot = "  ← heap-alloc"
            elif t == 0x66E64:
                annot = "  ← ???"
            elif t == 0x67358:
                annot = "  ← ???"
            elif t == 0x64248:
                annot = "  ← ???"
        except Exception:
            pass
    # String ref
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                # String?
                if 0 < v < len(data):
                    s = bytearray()
                    for k in range(80):
                        if v + k >= len(data): break
                        c = data[v + k]
                        if c == 0: break
                        if 32 <= c < 127: s.append(c)
                        else: s = None; break
                    if s and len(s) >= 4:
                        annot = f"  '{s.decode('ascii')}'"
                    elif annot == "":
                        annot = f"  lit = {v:#x}"
        except Exception:
            pass
    # Mark hang-sig: backward branches, str to TCM-tail addresses (ramsize-4 = 0x9FFFC)
    if i.mnemonic.startswith("str") and "#0x9ff" in i.op_str.lower():
        annot = "  [SHAREDRAM PUBLISH CANDIDATE]"
    if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t < i.address and i.address - t < 64:
                annot += "  [BACKWARD-BRANCH]"
        except ValueError:
            pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
