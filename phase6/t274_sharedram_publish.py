"""Search for writers of:
- HOSTRDY_DB1 literal (0x10000000) — the flag bit
- ramsize-4 address (0x9FFFC) — the sharedram_addr slot
- Also check fn@0x1E44's sub-calls (0x2f18, 0x2df0, 0x1dd4) for polling loops"""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Find literal refs to 0x10000000 (HOSTRDY_DB1)
print("=== literal refs to 0x10000000 (HOSTRDY_DB1) ===")
tgt = struct.pack("<I", 0x10000000)
hits_flag = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"  {len(hits_flag)} total hits")
for h in hits_flag[:10]:
    # Find ldr that references it
    for off in range(max(0, h - 4096), h, 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            lit_addr = ((off + 4) & ~3) + imm8 * 4
            if lit_addr == h:
                print(f"    lit@{h:#x}  T1 ldr from {off:#06x}")
        if off + 4 <= len(data):
            hw2 = struct.unpack_from("<H", data, off + 2)[0]
            if hw in (0xF8DF, 0xF85F):
                imm12 = hw2 & 0xFFF
                add = (hw & 0x0080) != 0
                lit_addr = ((off + 4) & ~3) + (imm12 if add else -imm12)
                if lit_addr == h:
                    print(f"    lit@{h:#x}  T2.W ldr.w from {off:#06x}")

# Find refs to 0x9FFFC (ramsize-4)
print("\n=== literal refs to 0x9FFFC (ramsize-4) ===")
tgt = struct.pack("<I", 0x9FFFC)
hits = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"  {len(hits)} total hits")
for h in hits[:10]:
    print(f"    lit@{h:#x}")

# Now disasm fn@0x1E44's sub-calls
def nxt(start):
    for off in range(start + 2, min(start+4096, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None

for addr, name in [(0x2F18, "fn@0x2F18"), (0x2DF0, "fn@0x2DF0"), (0x1DD4, "fn@0x1DD4")]:
    n = nxt(addr)
    print(f"\n=== {name} (~{n-addr} bytes) ===")
    ins = list(md.disasm(data[addr:min(n, addr+256)], addr, count=40))
    for i in ins[:40]:
        annot = ""
        if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t < i.address:
                    dist = i.address - t
                    annot = f"  [BACKWARD dist={dist}]"
                    if dist < 32: annot += " TIGHT"
            except: pass
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot = "  ← printf"
                elif t == 0x1ADC: annot = "  ← DELAY"
            except: pass
        print(f"    {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
