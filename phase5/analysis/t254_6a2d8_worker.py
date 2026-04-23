#!/usr/bin/env python3
"""
T254 local blob analysis — disassemble 0x6A2D8 (the real PHY worker).

Context (from T253 analysis):
  - wlc_phy_attach at blob[0x6A954..0x6AED2] uses an 8x BL call to 0x34DE0.
  - 0x34DE0 is a predicate dispatcher that tail-calls 0x6A2D8 with caller args.
  - 0x6A2D8 is therefore where the actual per-call PHY work happens.

T254 goal: identify whether 0x6A2D8 (or its callees) contain the hardware
polling loop that causes fw to hang. Polling loops look like:
    ldr RN, [RM, #offset]   (read register via some base ptr)
    tst RN, #mask           (test a bit)
    bne / beq target        (branch back to top of loop)

If we find a tight such loop that targets a register we can identify from
the base pointer, we have the hang candidate.
"""
import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/home/kimptoc/bcm4360-re/phase5/analysis/T254_6a2d8_worker.md"

with open(FW_PATH, "rb") as f:
    blob = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

def disas_range(start, end):
    return list(md.disasm(blob[start:end], start))

def find_fn_end(start, max_scan=0x4000):
    """Find the likely function end: next push {...,lr} or pop {...,pc}
    following the entry push."""
    # Just scan for the next 'push' at a word boundary after start+4
    for off in range(start + 4, start + max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        # Thumb-2 PUSH.W: prefix 0xe92d (4-byte)
        if w16 == 0xe92d:
            # ensure 4-byte instruction follows
            return off
        # Thumb-1 PUSH {...,lr}: 0xb5xx
        if (w16 & 0xff00) == 0xb500:
            return off
    return start + max_scan

def lines(insns, limit=None):
    out = []
    for i, insn in enumerate(insns):
        if limit and i >= limit:
            break
        out.append(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
    return "\n".join(out)

def summarize_bls(insns):
    """List all BL / BLX / B calls made from the function, grouped by target."""
    from collections import Counter
    targets = Counter()
    for insn in insns:
        if insn.mnemonic in ("bl", "blx", "b.w", "b"):
            op = insn.op_str
            if op.startswith("#"):
                try:
                    t = int(op.strip("#"), 16)
                    targets[(insn.mnemonic, t)] += 1
                except ValueError:
                    targets[(insn.mnemonic, op)] += 1
    return targets

def find_loops(insns):
    """Find backward branches. A backward branch whose target is an earlier
    instruction in the same function is a loop. Small loops (<20 instructions
    between target and branch) are more likely to be tight polling loops."""
    by_addr = {insn.address: insn for insn in insns}
    hits = []
    for insn in insns:
        if insn.mnemonic.startswith(("b", "cb")):
            op = insn.op_str
            if "#" in op:
                target_str = op.split("#")[-1].split(",")[0].strip()
                try:
                    tgt = int(target_str, 16)
                except ValueError:
                    continue
                if tgt < insn.address and tgt in by_addr:
                    body_len = sum(1 for a in by_addr if tgt <= a <= insn.address)
                    hits.append((insn.address, tgt, body_len, insn.mnemonic, insn.op_str))
    return hits

# --- Main analysis ---

START = 0x6A2D8
END_CAP = find_fn_end(START)
print(f"0x6A2D8 region: start=0x{START:X}, next-push=0x{END_CAP:X}, size={END_CAP-START} bytes")

insns = disas_range(START, END_CAP)
print(f"Disassembled {len(insns)} instructions\n")

# Print first 40 instructions (entry prologue + first block)
print("=== First 40 instructions ===")
print(lines(insns, 40))

# Print last 20
print("\n=== Last 20 instructions ===")
print(lines(insns[-20:]))

# BL summary
print("\n=== BL targets (freq) ===")
bls = summarize_bls(insns)
for (mnem, tgt), n in bls.most_common(20):
    if isinstance(tgt, int):
        print(f"  {mnem} 0x{tgt:06X}  x{n}")
    else:
        print(f"  {mnem} {tgt}  x{n}")

# Backward branches
print("\n=== Backward branches (candidate loops) ===")
loops = find_loops(insns)
loops.sort(key=lambda x: x[2])  # shortest loop body first
for addr, tgt, body, mnem, op in loops[:15]:
    print(f"  0x{addr:06X}: {mnem:<6} {op:<20}  (body {body} insns, back to 0x{tgt:06X})")

# For each short loop (body <= 10), disasm the loop body
print("\n=== Short-loop bodies (body <= 10 insns) ===")
by_addr = {insn.address: insn for insn in insns}
for addr, tgt, body, mnem, op in loops:
    if body <= 10:
        print(f"\n-- Loop at 0x{addr:06X} -> 0x{tgt:06X} (body {body} insns) --")
        in_loop = [insn for insn in insns if tgt <= insn.address <= addr]
        print(lines(in_loop))
