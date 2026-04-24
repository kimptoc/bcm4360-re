"""Find code that references the 5 HOSTRDY_DB1 literal pool hits."""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Find the 5 lit-pool hits for 0x10000000
tgt = struct.pack("<I", 0x10000000)
hits = [o for o in range(0, len(data) - 4, 4) if data[o:o+4] == tgt]
print(f"=== 5 HOSTRDY_DB1 literal-pool hits: {[hex(h) for h in hits]}\n")

# For each, scan WIDER backward (8KB, not 4KB) for any ldr.w / MOVW+MOVT that hits
for h in hits:
    print(f"--- lit@{h:#x} ---")
    found = []
    for off in range(max(0, h - 8192), h, 2):
        hw = struct.unpack_from("<H", data, off)[0]
        # T1 LDR pc-rel
        if (hw & 0xF800) == 0x4800:
            imm8 = hw & 0xFF
            lit_addr = ((off + 4) & ~3) + imm8 * 4
            if lit_addr == h:
                found.append(("T1", off))
        if off + 4 <= len(data):
            hw2 = struct.unpack_from("<H", data, off + 2)[0]
            # T2.W LDR pc-rel positive
            if hw in (0xF8DF, 0xF85F):
                imm12 = hw2 & 0xFFF
                add = (hw & 0x0080) != 0
                lit_addr = ((off + 4) & ~3) + (imm12 if add else -imm12)
                if lit_addr == h:
                    found.append(("T2", off))
    if not found:
        print(f"  (no direct LDR found within 8KB backward — possibly MOVW/MOVT encoded)")
    else:
        for kind, off in found[:5]:
            # Find fn start
            fn_start = None
            for back in range(0, 4096, 2):
                cand = off - back
                if cand < 0: break
                hw2 = struct.unpack_from("<H", data, cand)[0]
                if (hw2 & 0xFE00) == 0xB400 or hw2 == 0xE92D:
                    fn_start = cand; break
            print(f"  {kind} ldr at {off:#06x}  (fn@{fn_start:#06x if fn_start else '?'})")
            # Disasm 10 insns around
            start = max(0, off - 8)
            for i in md.disasm(data[start:start + 40], start, count=10):
                if i.mnemonic in ("str", "str.w", "orr", "orr.w", "orrs"):
                    print(f"      {i.address:#06x}: {i.mnemonic:<8} {i.op_str}  [WRITE]")
                else:
                    print(f"      {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")

# Also search for MOVW/MOVT pair producing 0x10000000 — i.e. MOVW rX, #0x0000 then MOVT rX, #0x1000
# Or MOV rX, #0x10000000 (impossible — imm too large for MOV)
# Common encoding: ldr from literal pool (found above) OR MOVW #0; MOVT #0x1000.
print("\n=== MOVW #0; MOVT #0x1000 pair producing 0x10000000 ===")
# Scan for MOVT rX, #0x1000 (0xF2C1 {0},000?) ...
# Thumb-2 MOVT: 0xF2C0..0xF6CF with specific encoding. Look for byte pattern:
# MOVT r?, #0x1000:  F2C1 0010 (specific reg)
# Easier: disasm and look for movt with #0x1000
for base in range(0, len(data), 64*1024):
    block = data[base:base+64*1024+8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic == "movt" and "#0x1000" in i.op_str:
            # Check the preceding insn for matching movw
            # (Just print these; they're rare.)
            print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
