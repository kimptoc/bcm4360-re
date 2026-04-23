#!/usr/bin/env python3
"""T254 deeper — trace 0x52B8 (tail-call target from 0x6A2D8) and 0x6A2D8's
other callees, plus the dispatch tables 0x38A50 / 0x38A24 that wlc_phy_attach
calls directly. Look for polling loops anywhere in this sub-tree."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(FW_PATH, "rb") as f:
    blob = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

def find_fn_end(start, max_scan=0x4000):
    """Find next Thumb-2 push.w {...,lr} (0xE92D) OR Thumb push {...,lr} (0xB5xx)
    after 'start'. Validates the 0xB5xx hit by checking the low byte bit 8."""
    for off in range(start + 4, start + max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d:
            return off
        # 0xB500..0xB5FF = push {... ,lr} (bit 8 set = include LR)
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
    return start + max_scan

def analyze(name, start):
    end = find_fn_end(start)
    insns = list(md.disasm(blob[start:end], start))
    print(f"\n=== {name} at 0x{start:06X}..0x{end:06X} ({end-start} B, {len(insns)} insns) ===")
    # Entry + short summary
    print("Entry:")
    for insn in insns[:6]:
        print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")

    # Backward branches (loop candidates)
    by_addr = {insn.address: insn for insn in insns}
    loops = []
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
                    loops.append((insn.address, tgt, body_len, insn.mnemonic, insn.op_str))

    if not loops:
        print(f"  Loops: NONE (no backward branches)")
    else:
        loops.sort(key=lambda x: x[2])
        print(f"  Loops: {len(loops)} found")
        for addr, tgt, body, mnem, op in loops[:5]:
            # Show body for tightest loops (<=15 insns)
            if body <= 15:
                print(f"  -- loop 0x{addr:06X} -> 0x{tgt:06X} (body {body} insns) --")
                in_loop = [insn for insn in insns if tgt <= insn.address <= addr]
                for insn in in_loop:
                    print(f"    0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")

    # BL targets
    from collections import Counter
    targets = Counter()
    for insn in insns:
        if insn.mnemonic in ("bl", "blx", "b.w"):
            op = insn.op_str
            if op.startswith("#"):
                try:
                    t = int(op.strip("#"), 16)
                    targets[(insn.mnemonic, t)] += 1
                except ValueError:
                    pass
    print("  Most-called targets:")
    for (mnem, tgt), n in targets.most_common(10):
        marker = ""
        if mnem == "b.w":
            marker = " (TAIL-CALL)"
        print(f"    {mnem:<4} 0x{tgt:06X}  x{n}{marker}")


# --- Functions to trace ---
analyze("0x52B8 (tail-target from 0x6A2D8)", 0x52B8)
analyze("0x82E (called 2x from 0x6A2D8)", 0x82E)
analyze("0x7D60 (common helper)", 0x7D60)
analyze("0x34D88 (predicate used by 0x34DE0)", 0x34D88)
analyze("0x52E8 (called 2x from 0x6A2D8)", 0x52E8)
analyze("0x38A50 (dispatch table base, wlc_phy_attach caller)", 0x38A50)
analyze("0x38A24 (dispatch table base, wlc_phy_attach caller)", 0x38A24)
