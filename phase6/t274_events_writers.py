#!/usr/bin/env python3
"""T274-FW: find writers of the RTE pending-events word.

Per T269 analysis of 0x9936 (the event-mask reader):
  r3 = [r0 + 0x358]     ; r0 = ctx (= *[0x6296C])
  r0 = [r3 + 0x100]     ; r0 = pending-events word
  bx lr

So the word lives at *(ctx+0x358)+0x100. To find writers:
  Pattern 1: load ctx_struct_ptr from [X + 0x358], then STR to [ptr + 0x100]
  Pattern 2: use the global [0x6296C] directly to derive the address
  Pattern 3: the address is cached in a local and referred to via literal pool

Additionally, in the ARM IRQ entry path, the write typically happens via:
  ldr rX, [ctx, #0x358]
  ldr rY, [rX, #0x100]
  orr rY, rY, #bit_pattern
  str rY, [rX, #0x100]

Scan approach: disassemble the whole blob, find every STR (r?, [r?, #0x100])
and then check the preceding few insns for a "ldr r?, [r?, #0x358]" pattern.
Also check for any orr/bic with constant before the str.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_fn_start(addr):
    for back in range(0, 4096, 2):
        cand = addr - back
        if cand < 0:
            break
        hw = struct.unpack_from("<H", data, cand)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return cand
    return None


# Disasm entire blob in 64KB chunks; record every store instruction whose
# op_str contains "#0x100"; cross-check preceding 6 insns for #0x358 pattern.
CHUNK = 64 * 1024
print("Scanning blob for str [r?, #0x100] pattern...")
candidate_writes = []  # (addr, context-insns)

for base in range(0, len(data), CHUNK):
    block = data[base:base + CHUNK + 8]
    insns = list(md.disasm(block, base, count=0))
    for idx, i in enumerate(insns):
        if i.mnemonic not in ("str", "str.w", "strh", "strh.w", "strb", "strb.w"):
            continue
        if "#0x100" not in i.op_str and ", #0x100]" not in i.op_str:
            continue
        # Look back 6 insns for a ldr with #0x358
        ctx_insns = insns[max(0, idx - 6):idx + 1]
        has_358_load = any(
            prev.mnemonic in ("ldr", "ldr.w") and "#0x358" in prev.op_str
            for prev in ctx_insns
        )
        has_orr = any(
            prev.mnemonic in ("orr", "orr.w", "orrs", "orrs.w")
            for prev in ctx_insns
        )
        if has_358_load:
            candidate_writes.append((i.address, ctx_insns, "358-matched", has_orr))

# Deduplicate by address
seen = set()
filtered = []
for addr, ctx, kind, has_orr in candidate_writes:
    if addr not in seen:
        seen.add(addr)
        filtered.append((addr, ctx, kind, has_orr))

print(f"\nFound {len(filtered)} candidate writers (str #0x100 with preceding #0x358 load):\n")
for addr, ctx, kind, has_orr in filtered:
    fn = find_fn_start(addr)
    orr_marker = "  [OR-pattern]" if has_orr else ""
    print(f"  {addr:#06x}  fn@{fn:#06x if fn else '?'}  {kind}{orr_marker}")
    for pi in ctx:
        print(f"     {pi.address:#06x}: {pi.mnemonic:<8} {pi.op_str}")
    print()
