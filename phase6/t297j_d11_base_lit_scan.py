"""T297-11: scan blob for any literal of D11 base 0x18001000 or D11 wrapper 0x18101000.

Per T289 §3 and KEY_FINDINGS row 141: only 0x18000000 (chipcommon REG)
appears as a literal-pool entry; PCIE2 (0x18003000) and PCIE2 wrapper
(0x18103000) have ZERO literals (so fw can't construct PCIE2 base inline).

Question per advisor 2026-04-27: does fw have any D11 base/wrapper literal?
- Found → fw constructs D11 base inline; trace it
- Not found → fw obtains D11 base via EROM walk; flag_struct[+0x88] is
  populated by that path

Also cover Thumb-2 modified-immediate `mov.w` and `movw+movt` constructions.
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


# Targets: 4-byte aligned literal scan
TARGETS = [
    ("D11 REG base", 0x18001000),
    ("D11 wrapper",  0x18101000),
    ("PCIE2 REG (sanity check)", 0x18003000),
    ("PCIE2 wrapper (sanity)",   0x18103000),
    ("CC REG base (control)",    0x18000000),  # known: 1 hit at 0x328 per T289 §3
    ("ARM-CR4 REG",              0x18002000),
    ("ARM-CR4 wrapper",          0x18102000),
    ("Core[5] REG",              0x18004000),
]

print("=== Pass A: 4-byte-aligned literal-pool scan ===")
for name, val in TARGETS:
    needle = struct.pack("<I", val)
    hits = []
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0:
            break
        if idx % 4 == 0:
            hits.append(idx)
        pos = idx + 1
    print(f"  {name:30s} {val:#010x}: {len(hits)} aligned hit(s){' at ' + ', '.join(hex(h) for h in hits) if hits else ''}")


print("\n=== Pass B: Thumb-2 inline `mov.w rN, #imm` constructing target value ===")
print("Capstone iter (resumable)…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}")

for name, val in TARGETS:
    target_str = f"#{val:#x}".replace("0X", "0x").lower()
    # mov.w accepts modified-immediate; capstone shows the resolved value
    # E.g., "mov.w r3, #0x18000000"
    movw_hits = []
    for ins in all_ins:
        if ins.mnemonic in ("mov", "mov.w", "movw"):
            if target_str in ins.op_str.lower():
                movw_hits.append((ins.address, ins.mnemonic, ins.op_str))
    movt_hits = []
    # MOVT pattern: movt rN, #(val>>16)  preceded by movw rN, #(val&0xFFFF)
    high = (val >> 16) & 0xFFFF
    low = val & 0xFFFF
    movt_str = f"#{hex(high)}".lower()
    for ins in all_ins:
        if ins.mnemonic == "movt" and movt_str in ins.op_str.lower():
            # Verify preceding movw with low half on same destination reg
            try:
                dest = ins.op_str.split(",")[0].strip()
                # Look back ~16 ins for a movw rN, #low
                for prev in all_ins:
                    if prev.address >= ins.address:
                        break
                    if prev.address < ins.address - 32:
                        continue
                    if prev.mnemonic == "movw" and prev.op_str.startswith(dest + ","):
                        if f"#{hex(low)}".lower() in prev.op_str.lower() or f"#{low}" in prev.op_str:
                            movt_hits.append((ins.address, prev.address, dest))
            except Exception:
                pass

    print(f"  {name:30s} {val:#010x}: mov.w hits={len(movw_hits)}, movt+movw paired hits={len(movt_hits)}")
    for a, m, op in movw_hits[:5]:
        print(f"    movw  {a:#x}: {m} {op}")
    for movt_a, movw_a, dest in movt_hits[:5]:
        print(f"    movt+movw  {movw_a:#x} → {movt_a:#x}: {dest}")
