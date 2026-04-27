"""T297-13 (advisor): focused scan for `ldr rN, [rM, #0x118]` followed by a
paired store of the loaded value at [..., #0x88].

Hypothesis: writer of flag_struct[+0x88] reads sched_ctx[+0x118] (D11's REG
base = slot 1*4 + 0x114 = 0x118) and stores it. T297-3's direct-offset scan
missed it because the store is indirect (via add-then-str, callee arg, or
register move).

Search:
1. Find every `ldr rN, [rM, #0x118]` in the blob (resumable iter)
2. For each, scan next ~12 instructions for stores of rN to ANY destination
   - Direct: `str rN, [..., #0x88]`
   - Indirect via add: `add rA, rB, #0x88; str rN, [rA]`
   - Via callee: `bl <fn>` — argue rN is preserved or passed
3. Also flag the source register tree: where does rM (sched_ctx) come from?

If a hit lands in a function that ALSO writes flag_struct's other fields
(+0x60 dword, +0xAC byte, or zeros [+0x82..+0x89]), that's the allocator.
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
addrs = sorted(ins_by_addr.keys())
print(f"Total: {len(all_ins):,}\n")


# Pass 1: find all `ldr rN, [rM, #0x118]` (excluding sp-rel since flag_struct alloc
# typically uses heap pointer, not stack)
print("=== `ldr rN, [rM, #0x118]` hits (excluding sp-rel) ===")
ldr_118_hits = []
for ins in all_ins:
    if ins.mnemonic not in ("ldr", "ldr.w"):
        continue
    if ", #0x118]" not in ins.op_str:
        continue
    if "[sp" in ins.op_str:
        continue
    if "[pc" in ins.op_str:
        continue
    # Capture dest reg
    try:
        dest = ins.op_str.split(",")[0].strip()
        ldr_118_hits.append((ins.address, dest, ins.op_str))
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}  → loads to {dest}")
    except Exception:
        pass
print(f"Total: {len(ldr_118_hits)}\n")


# Pass 2: for each ldr-118 hit, look 12 ins forward for str of dest reg
print("=== Forward scan: store of loaded value within 12 ins of ldr-118 ===")
producer_candidates = []  # (ldr_addr, str_addr, where_stored)
for ldr_addr, dest, ldr_op in ldr_118_hits:
    print(f"\n  --- ldr-118 @ {ldr_addr:#x} (dest = {dest}) ---")
    # Next ~12 ins
    seen = 0
    for ins in all_ins:
        if ins.address <= ldr_addr:
            continue
        if seen >= 12:
            break
        seen += 1
        # Show context line
        marker = ""
        if ins.mnemonic in ("str", "str.w", "strb", "strh", "strd"):
            # Check if dest is the value being stored
            if ins.op_str.startswith(dest + ","):
                marker = "  *** STORE OF " + dest + " ***"
                # Parse destination field
                try:
                    bracket = ins.op_str[ins.op_str.index("[") :]
                    inside = bracket.lstrip("[").rstrip("]")
                    parts = [p.strip() for p in inside.split(",")]
                    base_reg = parts[0]
                    off_str = parts[1].lstrip("#") if len(parts) > 1 else "0"
                    off = int(off_str, 16) if off_str.startswith("0x") else int(off_str)
                    producer_candidates.append((ldr_addr, ins.address, base_reg, off))
                    marker += f" → {base_reg} +{off:#x}"
                    if off == 0x88:
                        marker += "   <<<< MATCH >>>>"
                except Exception:
                    pass
        # Also flag if dest reg is overwritten (search ends naturally)
        if ins.mnemonic in ("ldr", "ldr.w", "mov", "mov.w", "movw", "movt"):
            if ins.op_str.startswith(dest + ","):
                # dest is overwritten; mark and stop
                marker = f"  (dest {dest} overwritten — stop)"
                print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}")
                break
        print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}")


print(f"\n=== Producer candidates (ldr-118 → str of value) ===")
for ldr_a, str_a, base_reg, off in producer_candidates:
    print(f"  ldr@{ldr_a:#x} → str@{str_a:#x}: stored to [{base_reg}, +{off:#x}]")
print(f"Total: {len(producer_candidates)}")

# Bonus: any hits with [reg, +0x88] = MATCH?
print("\n=== MATCH counts (ldr@+0x118 then str at [reg, +0x88]) ===")
matches = [c for c in producer_candidates if c[3] == 0x88]
print(f"Direct +0x88 stores: {len(matches)}")
for c in matches:
    print(f"  ldr@{c[0]:#x} → str@{c[1]:#x}: [reg={c[2]}, +0x88]  <<<< CANDIDATE WRITER >>>>")


# Bonus 2: also look for `add rA, rB, #0x88` then `str rN, [rA]` near each ldr-118 hit
print("\n=== Indirect: `add rA, rB, #0x88; str rN, [rA]` patterns near ldr-118 hits ===")
for ldr_addr, dest, _ in ldr_118_hits:
    seen = 0
    for ins in all_ins:
        if ins.address <= ldr_addr:
            continue
        if ins.address > ldr_addr + 80:  # 20-ish ins
            break
        if ins.mnemonic in ("add", "add.w") and "#0x88" in ins.op_str:
            print(f"  near ldr@{ldr_addr:#x}: {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
