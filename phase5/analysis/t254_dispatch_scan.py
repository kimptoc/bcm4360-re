#!/usr/bin/env python3
"""T254 dispatch-table scan — check each dispatch-table target for hardware
polling loops. Tight polling loops look like: ldr/tst/bcond-back with body
<= 6 instructions."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(FW_PATH, "rb") as f:
    blob = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True

def find_fn_end(start, max_scan=0x4000):
    for off in range(start + 4, start + max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d:
            return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
    return start + max_scan

def classify_loop(in_loop):
    """Look at a loop body and classify it by signature:
      - HW_POLL: contains LDR from a base register and TST+bcond pattern
      - STRLEN_LIKE: ldrb + cmp #0 + bne
      - COUNTER: just subs/adds + cmp constant + bne (integer counter)
      - OTHER
    Return (classification, details)."""
    mnems = [insn.mnemonic for insn in in_loop]
    ops = [insn.op_str for insn in in_loop]
    has_ldr = any(m in ("ldr", "ldr.w", "ldrb", "ldrb.w", "ldrh", "ldrh.w") for m in mnems)
    has_tst = any(m in ("tst", "tst.w", "ands", "ands.w") for m in mnems)
    has_strlen_sig = any(m == "cmp" and op.endswith(", #0") for m, op in zip(mnems, ops))
    # HW poll heuristic: ldr with offset pattern + tst
    hw_poll_strong = False
    for i in range(len(in_loop) - 1):
        if mnems[i].startswith("ldr") and "[" in ops[i] and mnems[i+1].startswith("tst"):
            hw_poll_strong = True
            break
        # Also ldr followed by cmp with #mask (not #0)
        if mnems[i].startswith("ldr") and "[" in ops[i]:
            for j in range(i+1, min(i+4, len(in_loop))):
                if mnems[j] in ("tst", "tst.w", "cmp", "cmp.w", "ands", "ands.w") and "#" in ops[j]:
                    # extract constant
                    try:
                        c = int(ops[j].split("#")[-1], 16) if "0x" in ops[j] else int(ops[j].split("#")[-1])
                    except ValueError:
                        continue
                    if c not in (0, 1):  # a bitmask > 1
                        hw_poll_strong = True
                        break

    if hw_poll_strong:
        return "HW_POLL"
    if has_ldr and has_tst:
        return "HW_POLL_WEAK"
    if has_strlen_sig and any(m.startswith("ldrb") for m in mnems):
        return "STRLEN_LIKE"
    return "OTHER"


def scan_loops(start, name):
    end = find_fn_end(start)
    if end - start < 4:
        return []
    insns = list(md.disasm(blob[start:end], start))
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
                    body = [in_ for in_ in insns if tgt <= in_.address <= insn.address]
                    cls = classify_loop(body)
                    loops.append((insn.address, tgt, len(body), cls, insn.mnemonic, insn.op_str, body))
    return loops


# Targets from T253 + T254 analysis to scan:
targets = [
    (0x6A214, "0x6A214 (tail from 0x34D88)"),
    # Dispatch table 0x38A50 targets (from wlc_phy_attach):
    (0x15940, "dispatch@0x38A50 -> 0x15940"),
    (0x1722C, "dispatch@0x38A50 -> 0x1722C"),
    (0x14CAC, "dispatch@0x38A50 -> 0x14CAC"),
    (0x14384, "dispatch@0x38A50 -> 0x14384"),
    (0x157F0, "dispatch@0x38A50 -> 0x157F0"),
    (0x14452, "dispatch@0x38A50 -> 0x14452"),
    (0x171E4, "dispatch@0x38A50 -> 0x171E4"),
    (0x143DC, "dispatch@0x38A50 -> 0x143DC"),
    (0x23018, "dispatch@0x38A50 -> 0x23018"),
    (0x22F10, "dispatch@0x38A50 -> 0x22F10"),
    # Dispatch table 0x38A24 targets:
    (0x117A4, "dispatch@0x38A24 -> 0x117A4"),
    (0x117B4, "dispatch@0x38A24 -> 0x117B4"),
    (0x117BC, "dispatch@0x38A24 -> 0x117BC"),
    (0x117E4, "dispatch@0x38A24 -> 0x117E4"),
    (0x16940, "dispatch@0x38A24 -> 0x16940"),
    (0x16476, "dispatch@0x38A24 -> 0x16476"),
    (0x16D00, "dispatch@0x38A24 -> 0x16D00"),
]

print("=== Loop scan of PHY dispatcher tree ===\n")
print(f"{'Target':30s}  {'Loops':>5s}  {'HW':>3s}  {'HWw':>3s}  {'Other':>5s}")
print("-" * 60)

interesting = []
for addr, name in targets:
    loops = scan_loops(addr, name)
    hw = sum(1 for l in loops if l[3] == "HW_POLL")
    hww = sum(1 for l in loops if l[3] == "HW_POLL_WEAK")
    other = sum(1 for l in loops if l[3] not in ("HW_POLL", "HW_POLL_WEAK"))
    print(f"{name:30s}  {len(loops):>5d}  {hw:>3d}  {hww:>3d}  {other:>5d}")
    if hw > 0 or hww > 0:
        interesting.append((name, addr, loops))


print("\n=== Detailed dump of HW_POLL candidates ===\n")
for name, addr, loops in interesting:
    print(f"--- {name} (start 0x{addr:06X}) ---")
    for la, lt, lb, cls, mnem, op, body in loops:
        if cls in ("HW_POLL", "HW_POLL_WEAK"):
            print(f"\n  [{cls}] loop 0x{la:06X} -> 0x{lt:06X} (body {lb} insns)")
            for insn in body:
                print(f"    0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
