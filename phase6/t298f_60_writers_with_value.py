"""T298f: classify all 32-bit stores to [reg, +0x60] by VALUE category.

Most are likely "clear to 0" (consume after dispatch). The interesting ones
SET a non-zero value — those define the wake mask. We're looking for stores
where the source register holds a constant or comes from a known wake-mask.

Pattern A: `mov rN, #imm; str rN, [reg, #0x60]` — direct constant write
Pattern B: `ldr rN, [pc, #imm]; str rN, [reg, #0x60]` — literal from pool
Pattern C: `mov rN, #0; str rN, [reg, #0x60]` — clear (skip)
Pattern D: `orr rN, ...; str rN, [reg, #0x60]` — accumulate (interesting)
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
ins_by_addr = {ins.address: ins for ins in all_ins}
print(f"Total: {len(all_ins):,}\n")


def parse_off(op_str):
    if "[" not in op_str: return None
    bracket = op_str[op_str.index("["):]
    if "#" not in bracket: return None
    s = bracket.split("#")[-1].rstrip("]").strip()
    try:
        return int(s, 16) if s.startswith("0x") else int(s)
    except: return None


def parse_base(op_str):
    if "[" not in op_str: return None
    bracket = op_str[op_str.index("["):]
    return bracket.lstrip("[").split(",")[0].strip()


# Find all 32-bit stores to [reg, +0x60]
hits = []
for ins in all_ins:
    if ins.mnemonic not in ("str", "str.w"): continue
    if parse_off(ins.op_str) != 0x60: continue
    if parse_base(ins.op_str) == "sp": continue
    hits.append(ins)

print(f"Total 32-bit [reg, +0x60] writers: {len(hits)}")


# For each hit, look back ~5 ins to find what value the source reg held
def get_source_value(hit_ins):
    """Return (kind, value, context_str) for the source of the store."""
    src_reg = hit_ins.op_str.split(",")[0].strip()
    # Walk back 8 ins
    last = None
    for ins in all_ins:
        if ins.address >= hit_ins.address: break
        if ins.address < hit_ins.address - 32: continue
        # Look for instructions that write to src_reg
        if ins.mnemonic in ("mov", "mov.w", "movs", "movw"):
            if ins.op_str.startswith(src_reg + ","):
                last = ins
        elif ins.mnemonic in ("ldr", "ldr.w"):
            if ins.op_str.startswith(src_reg + ","):
                last = ins
        elif ins.mnemonic in ("orr", "orr.w", "orrs"):
            if ins.op_str.startswith(src_reg + ",") or (", " + src_reg + ",") in ins.op_str.split(",")[0]:
                last = ins
        elif ins.mnemonic == "movt" and src_reg in ins.op_str:
            last = ins
    return last


# Categorize: zero / constant-nonzero / from-memory / from-orr / unknown
buckets = {"zero": [], "constant_nonzero": [], "from_pc_lit": [], "from_memory": [], "from_orr": [], "unknown": []}
for hit in hits:
    src = get_source_value(hit)
    if src is None:
        buckets["unknown"].append((hit.address, "?", hit.op_str))
        continue
    if src.mnemonic in ("mov", "mov.w", "movs", "movw") and "#" in src.op_str:
        try:
            imm_str = src.op_str.split("#")[-1].strip()
            val = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
            if val == 0:
                buckets["zero"].append((hit.address, val, hit.op_str))
            else:
                buckets["constant_nonzero"].append((hit.address, val, hit.op_str))
        except:
            buckets["unknown"].append((hit.address, "?", hit.op_str))
    elif src.mnemonic.startswith("ldr") and "[pc," in src.op_str:
        # PC-rel: resolve literal
        try:
            imm_str = src.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((src.address + 4) & ~3) + imm
            val = struct.unpack_from("<I", data, lit_addr)[0]
            buckets["from_pc_lit"].append((hit.address, val, hit.op_str))
        except:
            buckets["unknown"].append((hit.address, "?", hit.op_str))
    elif src.mnemonic.startswith("ldr"):
        buckets["from_memory"].append((hit.address, src.op_str, hit.op_str))
    elif src.mnemonic in ("orr", "orr.w", "orrs"):
        buckets["from_orr"].append((hit.address, src.op_str, hit.op_str))
    else:
        buckets["unknown"].append((hit.address, src.mnemonic + " " + src.op_str, hit.op_str))


print(f"\n=== Categorized [+0x60] writers ===")
for cat, items in buckets.items():
    print(f"\n{cat}: {len(items)} hits")
    for hit_a, val, op in items[:30]:
        if isinstance(val, int):
            tag = ""
            if val & 0x4000:
                tag = "  ★ has bit 14 (MI_GP1)"
            print(f"  {hit_a:#7x}  src=val={val:#x}{tag}  → {op}")
        else:
            print(f"  {hit_a:#7x}  src={val}  → {op}")
    if len(items) > 30:
        print(f"  ... {len(items)-30} more ...")
