"""T288: targeted search for the writer of sched+0x258 = 0x18100000.

Background (post-T287b correction):
- Read side (T283): class-0 thunk does `add.w r3, rN, #0x96; ldr [r4, r3, lsl #2]`
  resolving to `[sched + (class+0x96)*4] = [sched + class*4 + 0x258]`.
  For class=0 → reads sched[0x258] = chipcommon_wrapper_base = 0x18100000.
- T287b runtime: BOTH +0x254 AND +0x258 = 0x18100000 (twin words).
- t288_find_258_writers.py found ZERO direct `str [rX, #0x258]` instructions.

Possible writer signatures we still haven't searched for:
1. `strd r0, r1, [base, #0x254]` — paired store covering +0x254 and +0x258
   in ONE instruction. This perfectly explains the twin pattern. Capstone
   renders these as 'strd' / 'strd.w'.
2. `add.w r3, rN, #0x96; str.w rX, [r4, r3, lsl #2]` — mirror of the
   class-0 read pattern. Class-indexed loop storing wrapper bases.
3. `orr / add #0x100000` — wrapper base computed at runtime from
   chipcommon-base (0x18000000 | 0x100000 = 0x18100000). Find any code
   ORring/ADDing the bit-20 mask onto a chipcommon-related register.

Approach: thumb-disasm the whole code region; flag each pattern.
"""
import struct, sys, re
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = False

START, END = 0x800, min(len(data), 0x80000)

strd_hits = []           # any strd instruction (rare; review all)
class_idx_writes = []    # add.w rX, rY, #0x96 followed by indexed store
or_add_100000 = []       # orr/add #0x100000
mov_18100000 = []        # mov.w r, #0x18100000 (movw+movt pair construction)

# Track recent instructions in a sliding window for pattern matching
recent = []

# Also: capstone exposes movw+movt sequences. We'll scan separately for those.

print("=== Pass 1: full disasm, flag patterns ===")
for ins in md.disasm(data[START:END], START, count=0):
    op = ins.op_str

    # Pattern 1: strd
    if ins.mnemonic.startswith("strd"):
        strd_hits.append((ins.address, ins.mnemonic, op))

    # Pattern 3: orr / add with imm 0x100000
    if ins.mnemonic in ("orr.w", "orr", "add.w", "add"):
        if "#0x100000" in op or "#1048576" in op:
            or_add_100000.append((ins.address, ins.mnemonic, op))

    # Pattern: mov.w with imm = 0x18100000 (full word)
    if ins.mnemonic in ("mov.w", "movw"):
        if "#0x18100000" in op:
            mov_18100000.append((ins.address, ins.mnemonic, op))

    # Pattern 2: add.w rX, rY, #0x96 (offset constant for the class table)
    # Capture context window for next instruction analysis.
    if ins.mnemonic in ("add.w", "add") and "#0x96" in op:
        # Window: the next 8 instructions (we'll examine after disasm).
        class_idx_writes.append({"add_addr": ins.address, "add_op": op,
                                  "add_mn": ins.mnemonic, "follow": []})

    # If we just recorded a class_idx candidate, accumulate the next ~8 ins
    for cand in class_idx_writes:
        if cand["add_addr"] < ins.address <= cand["add_addr"] + 32 and ins.address != cand["add_addr"]:
            cand["follow"].append((ins.address, ins.mnemonic, op))


print(f"\n--- strd hits: {len(strd_hits)} ---")
for a, mn, op in strd_hits:
    print(f"  {a:#x}: {mn} {op}")

print(f"\n--- mov #0x18100000: {len(mov_18100000)} ---")
for a, mn, op in mov_18100000:
    print(f"  {a:#x}: {mn} {op}")

print(f"\n--- orr/add #0x100000: {len(or_add_100000)} ---")
for a, mn, op in or_add_100000[:30]:
    print(f"  {a:#x}: {mn} {op}")
if len(or_add_100000) > 30:
    print(f"  ... +{len(or_add_100000)-30} more")

print(f"\n--- add #0x96 → indexed-store candidates: {len(class_idx_writes)} ---")
for cand in class_idx_writes:
    # Only print candidates whose follow window contains an indexed store
    has_indexed = any("lsl #2" in f[2] for f in cand["follow"][:8])
    if not has_indexed:
        continue
    print(f"\n  add@{cand['add_addr']:#x}: {cand['add_mn']} {cand['add_op']}")
    for fa, fmn, fop in cand["follow"][:8]:
        marker = "  >>>" if "lsl #2" in fop else "     "
        print(f"  {marker} {fa:#x}: {fmn} {fop}")

# Pattern 4: movw+movt pair constructing 0x18100000 (low=0x0000, high=0x1810)
print(f"\n--- movw+movt → 0x18100000 construction (low=0, high=0x1810) ---")
prev = None
movw_movt_hits = []
for ins in md.disasm(data[START:END], START, count=0):
    op = ins.op_str
    if ins.mnemonic == "movw":
        # Parse "rX, #0xNN"
        m = re.match(r"(\w+),\s*#(0x[0-9a-fA-F]+|\d+)", op)
        if m:
            try:
                imm = int(m.group(2), 0)
                prev = (ins.address, m.group(1), imm)
            except: prev = None
        else:
            prev = None
    elif ins.mnemonic == "movt" and prev is not None:
        m = re.match(r"(\w+),\s*#(0x[0-9a-fA-F]+|\d+)", op)
        if m:
            try:
                imm_hi = int(m.group(2), 0)
                reg = m.group(1)
                if reg == prev[1] and (imm_hi << 16) | prev[2] == 0x18100000:
                    movw_movt_hits.append((prev[0], ins.address, reg))
            except: pass
        prev = None
    else:
        prev = None

for a1, a2, reg in movw_movt_hits:
    print(f"  movw@{a1:#x} + movt@{a2:#x} → {reg}=0x18100000")

# Print neighborhood of each constructor for context
for a1, a2, reg in movw_movt_hits[:6]:
    print(f"\n--- context around {a1:#x}..{a2:#x} (reg={reg}) ---")
    base = max(0, a1 - 16)
    for ins in md.disasm(data[base:a2 + 40], base, count=0):
        marker = "  >>>" if a1 <= ins.address <= a2 + 36 else "     "
        print(f"  {marker} {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
        if ins.address > a2 + 36:
            break
