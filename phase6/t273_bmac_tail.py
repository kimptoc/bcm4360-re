#!/usr/bin/env python3
"""T273 part 2: dump the full wlc_bmac_attach body from the saved-LR
return point (0x68320) to function end (~0x68a00 based on next prologue
at 0x68a68). Collect all BL targets and check each one for loops."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_next_prologue(start, max_scan=4096):
    for off in range(start + 2, min(start + max_scan, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None


# Full wlc_bmac_attach body from its start
print("=== wlc_bmac_attach @ 0x6820C — full body ===")
wbe_end = 0x68A68  # known: next fn starts here (fn@0x68A68 wrapper)
insns = list(md.disasm(data[0x6820C:wbe_end], 0x6820C, count=0))
print(f"  {len(insns)} instructions, {wbe_end - 0x6820C} bytes\n")

# Collect all BL/BLX targets + backward branches in the body
from collections import Counter
bl_targets = Counter()
backward_branches = []  # (ia, tgt)
for i in insns:
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            bl_targets[t] += 1
        except ValueError:
            pass
    elif i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t < i.address:
                backward_branches.append((i.address, t, i.mnemonic))
        except ValueError:
            pass

print(f"BL/BLX targets ({len(bl_targets)} unique):")
for t, c in sorted(bl_targets.items()):
    inside = 0x6820C <= t < 0x68A68
    print(f"  bl #{t:#06x}  x{c}{'  (internal)' if inside else ''}")

print(f"\nBackward branches (tight loop candidates):")
for ia, tgt, mnem in backward_branches:
    dist = ia - tgt
    tight = dist < 32
    print(f"  {ia:#06x}: {mnem} back to {tgt:#x}  (dist {dist}){' TIGHT' if tight else ''}")

# For each external BL target (not internal jump), quickly classify as:
#   - 1-2 insn tiny helper (not hang candidate)
#   - larger with backward branches (polling candidate)
#   - larger without backward branches (clean dispatch)
print(f"\nQuick classification of external BL targets:")
for t in sorted(bl_targets):
    if 0x6820C <= t < 0x68A68:
        continue  # skip internal
    if t == 0xA30 or t == 0x14948:
        continue  # known trace/printf
    nxt = find_next_prologue(t, max_scan=2048)
    ext = (nxt - t) if nxt else 2048
    ext = min(ext, 2048)
    sub_insns = list(md.disasm(data[t:t+ext+8], t, count=0))
    sub_insns = [i for i in sub_insns if i.address < t + ext]
    sub_backward = [(i.address, int(i.op_str[1:], 16)) for i in sub_insns
                    if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx")
                    and i.op_str.startswith("#") and int(i.op_str[1:], 16) < i.address]
    tight_loops = [(ia, tgt) for ia, tgt in sub_backward if ia - tgt < 32]
    status = ""
    if ext < 20:
        status = "TINY"
    elif tight_loops:
        status = f"TIGHT-LOOP x{len(tight_loops)} — POLLING CANDIDATE"
    elif sub_backward:
        status = f"has {len(sub_backward)} loose backward branches"
    else:
        status = "no loops / dispatcher / straight-line"
    print(f"  {t:#06x}  ({ext:4} bytes, {len(sub_insns):3} insns)  {status}")
