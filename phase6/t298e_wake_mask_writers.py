"""T298e: find writers of flag_struct[+0x60] and flag_struct[+0x180] — the wake masks.

Per fn@0x2309C: matched = pending & (flag_struct[+0x60] | flag_struct[+0x180]).
For host-write of MI_GP1 (0x4000) to wake fw, that bit must be in either mask.

Strategy: find all `str rN, [rM, #0x180]` and `str rN, [rM, #0x60]` writes,
classify by enclosing fn, prefer writes where the value being stored has bit 14
(0x4000) set OR an OR-pattern that incorporates a constant including 0x4000.

Also: look for writes to flag_struct[+0x180] specifically — there are fewer
+0x180 writes globally than +0x60 (which has 207 hits), so this should narrow.
"""
import struct, sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted_any = True
            last_end = ins.address + ins.size
            if last_end >= len(data) - 2:
                return
        pos = last_end if emitted_any else pos + 2


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def parse_off(op_str):
    if "[" not in op_str:
        return None
    bracket = op_str[op_str.index("["):]
    if "#" not in bracket:
        return None
    s = bracket.split("#")[-1].rstrip("]").strip()
    try:
        return int(s, 16) if s.startswith("0x") else int(s)
    except Exception:
        return None


def parse_base(op_str):
    if "[" not in op_str:
        return None
    bracket = op_str[op_str.index("["):]
    inside = bracket.lstrip("[").split(",")[0].strip()
    return inside


# Pass 1: ALL stores to [reg, +0x180] (excluding sp)
print("=== Stores to [reg, +0x180] (32-bit only, excluding sp) ===")
hits_180 = []
for ins in all_ins:
    if ins.mnemonic not in ("str", "str.w"):
        continue
    off = parse_off(ins.op_str)
    if off != 0x180:
        continue
    base = parse_base(ins.op_str)
    if base == "sp":
        continue
    hits_180.append((ins.address, ins.mnemonic, ins.op_str))
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(hits_180)}\n")


# Pass 2: characterize each [+0x180] writer's preceding context to find the
# value's source. Look back 6 ins for ldr/mov/orr that defined the source reg.
print("=== Context for each [+0x180] writer ===\n")
for hit_addr, mn, op in hits_180:
    print(f"--- writer @ {hit_addr:#x}: {mn} {op} ---")
    # Show 8 ins before
    for ins in all_ins:
        if ins.address < hit_addr - 32 or ins.address > hit_addr + 4:
            continue
        marker = "  <-- HERE" if ins.address == hit_addr else ""
        annot = ""
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                imm_str = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((ins.address + 4) & ~3) + imm
                if 0 <= lit_addr <= len(data) - 4:
                    val = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  ; lit = {val:#x}"
                    if val & 0x4000:
                        annot += "  ★ has bit 14 (MI_GP1)"
            except Exception:
                pass
        elif ins.mnemonic in ("mov.w", "movw", "mov", "movs") and "#" in ins.op_str:
            try:
                imm_str = ins.op_str.split("#")[-1].strip()
                imm = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
                annot = f"  ; imm = {imm:#x}"
                if imm & 0x4000:
                    annot += "  ★ has bit 14 (MI_GP1)"
            except Exception:
                pass
        print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}{annot}")
    print()


# Pass 3: also check flag_struct[+0x60] writers — narrow to those near a
# [+0x88] write or [+0x10] store (allocator-context indicators)
print("\n=== Stores to [reg, +0x60] (32-bit only, excluding sp) — list first 30 ===")
hits_60 = []
for ins in all_ins:
    if ins.mnemonic not in ("str", "str.w"):
        continue
    off = parse_off(ins.op_str)
    if off != 0x60:
        continue
    base = parse_base(ins.op_str)
    if base == "sp":
        continue
    hits_60.append((ins.address, ins.mnemonic, ins.op_str))

print(f"Total +0x60 (32-bit, ex sp): {len(hits_60)}")
print("First 10:")
for h in hits_60[:10]:
    print(f"  {h[0]:#7x}  {h[1]} {h[2]}")
