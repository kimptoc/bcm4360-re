"""Find code that writes to address 0x224 (the ISR dispatch pointer)."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

# Search for literal 0x224 in the blob
tgt = struct.pack("<I", 0x224)
hits = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"literal-pool refs to 0x224: {len(hits)}")
for lit in hits:
    # Find ldr at this lit
    for off in range(max(0, lit - 4096), lit, 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            lit_addr = ((off + 4) & ~3) + imm8 * 4
            if lit_addr == lit:
                print(f"  lit@{lit:#x}  loaded by T1 ldr at {off:#x}")
        if off + 4 <= len(data):
            hw2 = struct.unpack_from("<H", data, off + 2)[0]
            if hw == 0xF8DF or hw == 0xF85F:
                imm12 = hw2 & 0xFFF
                add = (hw & 0x0080) != 0
                lit_addr = ((off + 4) & ~3) + (imm12 if add else -imm12)
                if lit_addr == lit:
                    print(f"  lit@{lit:#x}  loaded by T2.W ldr.w at {off:#x}")

# For each caller, disasm context around to see if it's a STR to 0x224
print("\n=== context at each loader ===")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for lit in hits:
    for off in range(max(0, lit - 4096), lit, 2):
        hw = struct.unpack_from("<H", data, off)[0]
        is_t1 = (hw & 0xF800) == 0x4800
        is_t2 = False
        if off + 4 <= len(data):
            hw2 = struct.unpack_from("<H", data, off + 2)[0]
            is_t2 = (hw == 0xF8DF or hw == 0xF85F) and ((hw & 0x0080) != 0 and
                    ((off + 4) & ~3) + (hw2 & 0xFFF) == lit)
        if is_t1:
            imm8 = hw & 0xFF
            lit_addr = ((off + 4) & ~3) + imm8 * 4
            if lit_addr != lit: continue
        elif is_t2:
            pass
        else:
            continue
        print(f"\n  loader at {off:#x}:")
        # 5 insns before + 5 after
        start = max(0, off - 16)
        for i in md.disasm(data[start:off + 32], start, count=12):
            annot = ""
            if i.mnemonic.startswith("str"):
                annot = "  [STORE]"
            print(f"    {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
