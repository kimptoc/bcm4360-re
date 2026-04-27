"""T298h (advisor): find ALL writers of [reg, +0x64] in the blob, classified
by VALUE.

If 0x48080 appears in many writers across init: canonical wake mask.
If multiple distinct values: wake mask is dynamic per-state.
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


def parse_off(op):
    if "[" not in op: return None
    bracket = op[op.index("["):]
    if "#" not in bracket: return None
    s = bracket.split("#")[-1].rstrip("]").strip()
    try: return int(s, 16) if s.startswith("0x") else int(s)
    except: return None


def parse_base(op):
    if "[" not in op: return None
    bracket = op[op.index("["):]
    return bracket.lstrip("[").split(",")[0].strip()


# All 32-bit writes to [reg, +0x64]
hits = []
for ins in all_ins:
    if ins.mnemonic not in ("str", "str.w"): continue
    if parse_off(ins.op_str) != 0x64: continue
    if parse_base(ins.op_str) == "sp": continue
    hits.append(ins)

print(f"Total 32-bit [reg, +0x64] writers (excl sp): {len(hits)}\n")


# For each: find source value
def get_source_value(hit_ins):
    src_reg = hit_ins.op_str.split(",")[0].strip()
    last = None
    for ins in all_ins:
        if ins.address >= hit_ins.address: break
        if ins.address < hit_ins.address - 40: continue
        if ins.mnemonic in ("mov", "mov.w", "movs", "movw") and ins.op_str.startswith(src_reg + ","):
            last = ins
        elif ins.mnemonic in ("ldr", "ldr.w") and ins.op_str.startswith(src_reg + ","):
            last = ins
        elif ins.mnemonic in ("orr", "orr.w", "orrs") and ins.op_str.startswith(src_reg + ","):
            last = ins
    return last


print("=== Source values categorized ===\n")
buckets = {}  # value → list of (hit_addr, op)
for hit in hits:
    src = get_source_value(hit)
    val = None
    if src is None:
        key = "(unknown)"
    elif src.mnemonic in ("mov","mov.w","movs","movw") and "#" in src.op_str:
        try:
            imm_s = src.op_str.split("#")[-1].strip()
            val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
            key = f"const={val:#x}"
        except:
            key = "(const-unparseable)"
    elif src.mnemonic.startswith("ldr") and "[pc," in src.op_str:
        try:
            imm_s = src.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((src.address + 4) & ~3) + imm
            val = struct.unpack_from('<I', data, la)[0]
            key = f"PC-lit={val:#x}"
        except:
            key = "(pc-lit-unparseable)"
    elif src.mnemonic.startswith("ldr"):
        key = f"from-mem ({src.op_str})"
    elif src.mnemonic in ("orr","orr.w","orrs"):
        key = f"orr ({src.op_str})"
    else:
        key = f"{src.mnemonic} {src.op_str}"
    buckets.setdefault(key, []).append((hit.address, hit.op_str))


# Print sorted: most-distinct values first
sorted_buckets = sorted(buckets.items(), key=lambda x: -len(x[1]))
for key, lst in sorted_buckets:
    print(f"  [{len(lst)} hits] source = {key}")
    for addr, op in lst[:5]:
        print(f"    {addr:#7x}  {op}")
    if len(lst) > 5:
        print(f"    ... {len(lst)-5} more ...")
    print()


# Highlight: any value containing bit 7/15/18 (the wake-mask bits)?
WAKE_BITS = 0x48080
print(f"\n=== Values containing wake-mask bits 0x{WAKE_BITS:x} (or super/subset) ===")
for key, lst in buckets.items():
    if "const=" in key or "PC-lit=" in key:
        try:
            val = int(key.split("=")[-1], 16)
            if val & WAKE_BITS:
                shared = val & WAKE_BITS
                tag = " (EXACT MATCH)" if val == WAKE_BITS else f" (shares {shared:#x} with wake mask)"
                print(f"  source = {val:#x}{tag} — {len(lst)} writer(s)")
                for a, op in lst[:3]:
                    print(f"    {a:#7x}  {op}")
        except: pass
