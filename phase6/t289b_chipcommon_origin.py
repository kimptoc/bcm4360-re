"""T289b-4: find all loaders of the chipcommon literal at 0x328.

The fw blob has EXACTLY ONE literal of 0x18000000 (chipcommon REG base)
at file offset 0x328 (per T289 mbm_write_search). PC-relative LDR has
~4KB range on Thumb-2 (4096 byte limit). So ALL instructions that load
this literal must be within 0x000..0x1328 (with the literal at 0x328).

Find them. Each loader is a code site that obtains the chipcommon base.
The instruction directly after the load tells us what the value is used
for — typically `str` somewhere or `add` to compute another address.

This narrows the path from "fw blob has one chipcommon literal" to
"fw uses chipcommon base in N specific places, each doing X".
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1):
        return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data):
            break
        c = data[addr + k]
        if c == 0:
            break
        if 32 <= c < 127:
            s.append(c)
        else:
            return None
    return s.decode("ascii") if len(s) >= 3 else None


# Search 0x000..0x1328 for ldr.w / ldr that loads (PC+4 & ~3) + imm = 0x328
target_lit = 0x328
print(f"=== All PC-relative LDR loads of literal at file offset 0x{target_lit:#x} ===")
print("(Range scanned: 0x0 .. 0x1328 — Thumb PC-relative LDR has ~4KB reach)")
loaders = []
for chunk in [(0x000, 0x1500)]:  # one chunk covers all
    cstart, cend = chunk
    for ins in md.disasm(data[cstart:cend], cstart):
        if ins.mnemonic.startswith("ldr") and "[pc" in ins.op_str:
            try:
                imm_str = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((ins.address + 4) & ~3) + imm
                if lit_addr == target_lit:
                    loaders.append((ins.address, ins.mnemonic, ins.op_str))
            except Exception:
                pass

print(f"Found {len(loaders)} loader(s):")
for addr, mn, op in loaders:
    print(f"  {addr:#x}  {mn} {op}")

# For each loader, dump 12 bytes of context (~3 instructions before and after)
print("\n=== Context for each loader (10 ins around) ===")
for addr, mn, op in loaders:
    print(f"\n--- loader @ {addr:#x} ---")
    start = max(0, addr - 16)
    end = addr + 32
    for ins in md.disasm(data[start:end], start):
        marker = "  <-- here" if ins.address == addr else ""
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}")

# Also check: what if fw uses MOVW/MOVT to construct 0x18000000 inline?
# Pattern: movw rN, #0x0000 ; movt rN, #0x1800
# Encoding: F2C1_xxxx for movt with #0x1800 as the high half
print("\n\n=== Inline MOVW/MOVT constructions of chipcommon base 0x18000000 ===")
print("(MOVT rX, #0x1800 must follow MOVW rX, #0x0000)")
movt_count = 0
for ins in md.disasm(data, 0):
    if ins.mnemonic == "movt" and "#0x1800" in ins.op_str:
        movt_count += 1
        # show 6 ins of context
        ctx_start = max(0, ins.address - 12)
        ctx_end = ins.address + 8
        print(f"  MOVT match at {ins.address:#x}: {ins.op_str}")
print(f"Total movt #0x1800 hits: {movt_count}")

# Same check for backplane in general (any movt with #0x180x where x in 0..1f)
print("\n=== Inline MOVT for any backplane (0x1800x..0x1801x) ===")
movt_count_any = 0
for ins in md.disasm(data, 0):
    if ins.mnemonic == "movt":
        if "#0x1800" in ins.op_str or "#0x1801" in ins.op_str:
            movt_count_any += 1
            print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
print(f"Total backplane-MOVT hits: {movt_count_any}")
