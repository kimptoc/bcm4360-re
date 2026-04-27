"""T297-14: broaden the +0x118 scan to ALL per-class REG/wrap table offsets.

Per KEY_FINDINGS rows 132 + 137:
- sched_ctx +0x114..+0x12C = REG-base table (slot * 4): slot 0 = chipcommon REG (0x114),
  slot 1 = D11 REG (0x118), slot 2 = ARM-CR4 (0x11C), slot 3 = PCIE2 (0x120), slot 4 = core[5] (0x124)
- sched_ctx +0x254..+0x270 = WRAP-base table (slot * 4 + scratch): table[0] = chipcommon wrap (0x258),
  table[1] = D11 wrap (0x25C), table[2] = ARM-CR4 wrap (0x260), table[3] = PCIE2 wrap (0x264)

Since +0x118 had 0 reader hits (T297k), broaden:
- Find ldrs at all four likely REG-table offsets (+0x114, +0x118, +0x11C, +0x120, +0x124)
- Find ldrs at WRAP-table offsets too (+0x258, +0x25C, +0x260, +0x264, +0x268)
- Also `mov rN, #0x118` for register-offset addressing
- Also `add rN, rM, #0x118` for pointer-arithmetic

If all are zero: fw doesn't use direct constant-offset addressing for the per-class
table at all. Most likely uses register-indexed addressing (`ldr rA, [rB, rC, lsl #2]`)
where rC = class index — a much harder pattern to scan.
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


REG_TABLE_OFFSETS = [0x114, 0x118, 0x11C, 0x120, 0x124, 0x128]  # chipcommon..core[5] + 1 for sanity
WRAP_TABLE_OFFSETS = [0x254, 0x258, 0x25C, 0x260, 0x264, 0x268, 0x26C]


def search_offset_pattern(off):
    """Find ldr/str/add/mov for a given byte offset across the blob."""
    needle = f"#{off:#x}"
    needle_lower = needle.lower()  # capstone may use lowercase hex
    hits = []
    for ins in all_ins:
        # Match either #0x114 or #0X114 forms
        if ", #0x{:x}]".format(off) not in ins.op_str.lower():
            # Also check non-bracketed (for add/mov)
            if "#0x{:x}".format(off) not in ins.op_str.lower():
                continue
        if "[sp" in ins.op_str:
            continue
        if "[pc" in ins.op_str:
            continue
        hits.append(ins)
    return hits


print(f"\n{'='*72}")
print(f"=== REG-TABLE OFFSETS (sched+0x114..) ===")
print(f"{'='*72}")
for off in REG_TABLE_OFFSETS:
    hits = search_offset_pattern(off)
    print(f"\n  +{off:#x}: {len(hits)} hit(s)")
    for ins in hits[:8]:
        print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
    if len(hits) > 8:
        print(f"    ... {len(hits)-8} more ...")

print(f"\n{'='*72}")
print(f"=== WRAP-TABLE OFFSETS (sched+0x254..) ===")
print(f"{'='*72}")
for off in WRAP_TABLE_OFFSETS:
    hits = search_offset_pattern(off)
    print(f"\n  +{off:#x}: {len(hits)} hit(s)")
    for ins in hits[:8]:
        print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
    if len(hits) > 8:
        print(f"    ... {len(hits)-8} more ...")


# Pass 3: find register-indexed ldr — `ldr rA, [rB, rC, lsl #2]` patterns
# These are common for table[index] accesses where index varies at runtime.
print(f"\n{'='*72}")
print(f"=== Register-indexed loads: ldr rA, [rB, rC, lsl #2] ===")
print(f"{'='*72}")
indexed_hits = []
for ins in all_ins:
    if ins.mnemonic in ("ldr", "ldr.w"):
        if ", lsl #2]" in ins.op_str:
            indexed_hits.append(ins)
print(f"Total `ldr ?, [?, ?, lsl #2]` patterns: {len(indexed_hits)}")
print("Showing first 20:")
for ins in indexed_hits[:20]:
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
