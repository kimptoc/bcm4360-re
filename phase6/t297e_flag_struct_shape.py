"""T297-3: hunt flag_struct's allocator by struct shape.

flag_struct (per fn@0x23374 + fn@0x2309C reads):
  - [+0x60]  dword check (queue state? non-zero gates further work)
  - [+0x88]  dword = wake-gate ABS BASE (target of flag_struct[+0x88]+0x168)
  - [+0xAC]  byte check (enabled? non-zero gates further work)

Hunt: find any function-local code window of ≤200 bytes that writes
[rN, +0x60] AND [rN, +0x88] AND [rN, +0xAC] on the same register N,
where N is consistent across the window.

The discriminator [+0x60] + [+0xAC] is distinctive — most callbacks
tables won't have a byte at +0xAC.
"""
import struct, sys
from collections import defaultdict
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open('/lib/firmware/brcm/brcmfmac4360-pcie.bin','rb') as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def parse_off(s):
    s = s.split('#')[-1].rstrip(']').strip()
    if not s:
        return None
    try:
        return int(s, 16) if s.startswith('0x') else int(s)
    except Exception:
        return None


def parse_reg(op_str):
    """Pulls 'rN' (or 'sb', 'fp' etc.) from '[rN, #imm]' or 'rN, [rM, #imm]'."""
    if '[' not in op_str:
        return None
    bracket = op_str[op_str.index('['):]
    inside = bracket.lstrip('[').split(',')[0].strip()
    return inside


# Scan whole blob for str/strb/strh stores of small offsets in {0x60, 0x88, 0xAC}
INTEREST = {0x60, 0x88, 0xAC}
hits = []  # (addr, mnemonic, reg, off)

# Resumable scanner — advance 2 bytes past each undecodable region.
# Capstone stops at the first undecodable byte; we restart at the next
# 2-byte boundary until we cover the whole blob.
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
        # Resume after the last decoded instruction (or skip 2 bytes if none)
        if emitted_any:
            pos = last_end
        else:
            pos += 2

for ins in iter_all():
    if ins.mnemonic in ('str','str.w','strb','strb.w','strh','strh.w','strd'):
        if '[' not in ins.op_str:
            continue
        # offset is the part after `, #` inside the bracket (or directly after bracket reg in pre-indexed)
        # Example operands: 'r3, [r4, #0x88]' / 'r3, [r4, #0x88]!' / 'r3, [r4]'
        bracket = ins.op_str[ins.op_str.index('['):]
        if '#' not in bracket:
            continue
        off = parse_off(bracket)
        if off in INTEREST:
            reg = parse_reg(ins.op_str)
            # Filter out sp-relative (stack frames)
            if reg == 'sp':
                continue
            hits.append((ins.address, ins.mnemonic, reg, off))

print(f"Total stores to [reg, +{{0x60,0x88,0xAC}}] (excl sp): {len(hits)}")
print()

# Group by offset and reg
by_off = defaultdict(list)
for a, m, r, o in hits:
    by_off[o].append((a, m, r))
for o in sorted(by_off):
    print(f"Stores to [reg, +{o:#x}]: {len(by_off[o])}")
    for a, m, r in by_off[o]:
        print(f"  {a:#x}: {m} <reg={r}>")
    print()

# Now look for clusters: within a 200-byte window, find any pair of stores
# to same reg with offset combinations that include 0x88 + (0x60 or 0xAC)
print("=== Clusters: same reg, store [+0x88] within 256 B of store [+0x60] OR [+0xAC] ===\n")

WINDOW = 256
clusters = []
for i, (a1, m1, r1, o1) in enumerate(hits):
    if o1 != 0x88:
        continue
    # Look for nearby [+0x60] or [+0xAC] on same reg
    nearby = []
    for j, (a2, m2, r2, o2) in enumerate(hits):
        if i == j:
            continue
        if r2 != r1:
            continue
        if abs(a2 - a1) > WINDOW:
            continue
        if o2 in (0x60, 0xAC):
            nearby.append((a2, m2, o2))
    if nearby:
        clusters.append((a1, r1, nearby))

print(f"Found {len(clusters)} clusters with [+0x88]+([+0x60] OR [+0xAC]) on same reg in {WINDOW} B window\n")

for a1, reg, nearby in clusters:
    print(f"  [+0x88] @ {a1:#x} on reg {reg}")
    for na, nm, no in nearby:
        rel = na - a1
        print(f"    {'+' if rel >= 0 else ''}{rel:>4d} B: {nm:8s} [reg+{no:#x}] @ {na:#x}")
    print()


# Even stronger: clusters with ALL THREE offsets on same reg in same window
print("=== STRONG MATCH: [+0x60] + [+0x88] + [+0xAC] all on same reg in 256 B ===\n")
strong_count = 0
for a1, reg, nearby in clusters:
    has_60 = any(no == 0x60 for _, _, no in nearby)
    has_AC = any(no == 0xAC for _, _, no in nearby)
    if has_60 and has_AC:
        strong_count += 1
        print(f"  *** {reg} @ around {a1:#x}: full triple ***")
        print(f"      [+0x88] @ {a1:#x}")
        for na, nm, no in sorted(nearby, key=lambda x: x[0]):
            print(f"      [+{no:#x}] @ {na:#x}  ({nm})")
        print()
print(f"Total strong matches: {strong_count}")
