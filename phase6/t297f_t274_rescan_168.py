"""T297-6 (advisor priority): re-run T274's pending-events writer scan
with the resumable iterator that T297e proved finds 6× more hits than the
naive chunk-based approach.

T281's "wake-gate is HW MMIO" inference rests on T274 finding zero software
writers of the pending-events word. The pending-events word is read+W1C-cleared
in fn@0x2309C as `[r5+0x168]` where r5 = flag_struct[+0x88].

If T274's scan was incomplete (likely, given T297e's 6× undercount when
re-scanned), software writers may exist. Software writers → wake-gate is
TCM, NOT chipcommon/PCIE2/etc.

Search:
1. All `str/str.w/strb/strh/strd rX, [rN, #0x168]` (direct offset)
2. All `str/str.w/strb/strh/strd rX, [rN, #0x16c]` (companion W1C-clear)
3. `add rN, rM, #0x168` (pointer-arithmetic — paired with str [rN])

Cross-reference fn@0x2309C — it should appear as a writer of both 0x168 and
0x16C (the W1C clears). Other hits = candidate producers.
"""
import struct, sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


# Resumable scanner — same pattern as t297e
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


def parse_off_in_bracket(op_str):
    """Extract immediate offset from `..., [rN, #imm]` pattern."""
    if "[" not in op_str:
        return None
    bracket = op_str[op_str.index("[") :]
    if "#" not in bracket:
        return None
    s = bracket.split("#")[-1].rstrip("]").strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.startswith("0x") else int(s)
    except Exception:
        return None


def parse_base_reg(op_str):
    if "[" not in op_str:
        return None
    bracket = op_str[op_str.index("[") :]
    inside = bracket.lstrip("[").split(",")[0].strip()
    return inside


# Cache the full insn stream once (we want multiple passes)
print("Disasm pass — collecting all instructions via resumable iterator…")
all_ins = []
for ins in iter_all():
    all_ins.append(ins)
print(f"Total instructions decoded: {len(all_ins):,}\n")


# Pass 1: direct stores to [reg, +0x168]
print("=== Pass 1: STORES to [reg, +0x168] ===")
hits_168 = []
for ins in all_ins:
    if ins.mnemonic not in (
        "str", "str.w", "strb", "strb.w", "strh", "strh.w", "strd",
    ):
        continue
    if "[" not in ins.op_str:
        continue
    off = parse_off_in_bracket(ins.op_str)
    if off == 0x168:
        reg = parse_base_reg(ins.op_str)
        if reg == "sp":
            continue
        hits_168.append((ins.address, ins.mnemonic, reg, ins.op_str))
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(hits_168)} hits\n")


# Pass 2: stores to [reg, +0x16c] (companion W1C)
print("=== Pass 2: STORES to [reg, +0x16C] ===")
hits_16c = []
for ins in all_ins:
    if ins.mnemonic not in (
        "str", "str.w", "strb", "strb.w", "strh", "strh.w", "strd",
    ):
        continue
    if "[" not in ins.op_str:
        continue
    off = parse_off_in_bracket(ins.op_str)
    if off == 0x16C:
        reg = parse_base_reg(ins.op_str)
        if reg == "sp":
            continue
        hits_16c.append((ins.address, ins.mnemonic, reg, ins.op_str))
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(hits_16c)} hits\n")


# Pass 3: pointer-arithmetic — `add rN, rM, #0x168` (paired with str [rN])
print("=== Pass 3: `add rN, rM, #0x168` patterns (pointer arith) ===")
add_168_hits = []
for ins in all_ins:
    if ins.mnemonic not in ("add", "add.w", "adds"):
        continue
    if "#0x168" not in ins.op_str:
        continue
    add_168_hits.append((ins.address, ins.mnemonic, ins.op_str))
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(add_168_hits)} hits\n")


# Pass 4: also `add rN, rM, #0x16C` (less common but possible for the W1C target)
print("=== Pass 4: `add rN, rM, #0x16C` patterns ===")
add_16c_hits = []
for ins in all_ins:
    if ins.mnemonic not in ("add", "add.w", "adds"):
        continue
    if "#0x16c" not in ins.op_str:
        continue
    add_16c_hits.append((ins.address, ins.mnemonic, ins.op_str))
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(add_16c_hits)} hits\n")


# Pass 5: `mov rN, #0x168` (used as register-offset for indexed store)
print("=== Pass 5: `mov rN, #0x168` (register-offset addressing) ===")
mov_168_hits = []
for ins in all_ins:
    if ins.mnemonic not in ("mov", "mov.w", "movs", "movw"):
        continue
    if "#0x168" not in ins.op_str:
        continue
    mov_168_hits.append((ins.address, ins.mnemonic, ins.op_str))
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
print(f"Total: {len(mov_168_hits)} hits\n")


# Cross-reference: hits in fn@0x2309C body (~50 bytes from 0x2309C)
FN2309C_RANGE = (0x2309C, 0x230F0)  # rough estimate
fn_2309c_hits_168 = [h for h in hits_168 if FN2309C_RANGE[0] <= h[0] < FN2309C_RANGE[1]]
fn_2309c_hits_16c = [h for h in hits_16c if FN2309C_RANGE[0] <= h[0] < FN2309C_RANGE[1]]

print("=== Summary vs. T281's prediction ===")
print(f"T281 said fn@0x2309C should write [r5, +0x168] AND [r5, +0x16c] (W1C clears).")
print(f"  Hits at [reg, +0x168] inside fn@0x2309C body ({FN2309C_RANGE[0]:#x}..{FN2309C_RANGE[1]:#x}): {len(fn_2309c_hits_168)}")
for a, m, r, op in fn_2309c_hits_168:
    print(f"    {a:#x}: {m} {op}")
print(f"  Hits at [reg, +0x16c] inside fn@0x2309C body: {len(fn_2309c_hits_16c)}")
for a, m, r, op in fn_2309c_hits_16c:
    print(f"    {a:#x}: {m} {op}")

# Hits outside fn@0x2309C — these are the real candidates for "producer" code
out_168 = [h for h in hits_168 if not (FN2309C_RANGE[0] <= h[0] < FN2309C_RANGE[1])]
out_16c = [h for h in hits_16c if not (FN2309C_RANGE[0] <= h[0] < FN2309C_RANGE[1])]
print(f"\n=== Candidate PRODUCER writes (outside fn@0x2309C body) ===")
print(f"At [reg, +0x168]: {len(out_168)} site(s)")
for a, m, r, op in out_168:
    print(f"  {a:#x}: {m} {op}")
print(f"At [reg, +0x16c]: {len(out_16c)} site(s)")
for a, m, r, op in out_16c:
    print(f"  {a:#x}: {m} {op}")

# Decision lens
print("\n=== Verdict ===")
out_count = len(out_168) + len(out_16c) + len(add_168_hits) + len(add_16c_hits)
if out_count == 0:
    print("NO software writers of pending-events word found beyond fn@0x2309C consumer.")
    print("→ T281's HW-MMIO inference holds. Wake-gate is HW (chipcommon / D11 / etc.)")
else:
    print(f"FOUND {out_count} software writer candidate(s) outside fn@0x2309C.")
    print("→ T281's HW-MMIO inference WEAKENED. Wake-gate may be TCM (software-maintained word).")
    print("Each producer write = a code path that posts an event. Identify each one's enclosing fn.")
