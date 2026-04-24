"""Disasm fn@0x1E44 (post-registration finalize step in pcidongle_probe)."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Find extent of 0x1E44
def nxt(start):
    for off in range(start + 2, min(start+4096, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None

n = nxt(0x1E44)
print(f"fn@0x1E44 extent ~{n - 0x1E44} bytes (next fn at {n:#x})")

# Full disasm
print(f"\n=== fn@0x1E44 body ===")
ins = list(md.disasm(data[0x1E44:n], 0x1E44, count=0))
for i in ins:
    annot = ""
    # BL annotations
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t == 0xA30: annot = "  ← printf"
            elif t == 0x14948: annot = "  ← trace"
            elif t == 0x1298: annot = "  ← heap-alloc"
            elif t == 0x11e8: annot = "  ← printf/assert"
            elif t == 0x1ADC: annot = "  ← DELAY helper"
        except ValueError: pass

    # PC-rel ldr → literal
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
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
                        annot = f"  '{s.decode('ascii')}'"
                    elif annot == "":
                        annot = f"  lit = {v:#x}"
        except Exception: pass

    # Store at ramsize-4 (0x9FFFC)
    if i.mnemonic.startswith("str") and any(h in i.op_str.lower() for h in ["#0x9ff", "#0xfff", "#-4"]):
        annot = "  [RAMSIZE-RELATIVE STORE]"

    # Backward branches
    if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t < i.address:
                dist = i.address - t
                annot += f"  [BACKWARD-BRANCH dist={dist}]"
                if dist < 32:
                    annot += " TIGHT"
        except ValueError: pass

    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")

# Also find literal refs to 0x1e44 | 1 to see who else calls it
tgt = struct.pack("<I", 0x1e44 | 1)
hits = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"\nliteral-pool refs to 0x1e45: {[hex(h) for h in hits]}")
