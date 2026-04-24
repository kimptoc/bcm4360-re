#!/usr/bin/env python3
"""T273-FW: disassemble the 3 un-traced sub-calls identified by T272 and
classify each as:
  - bounded helper (no loops, or bounded countdown via delay helper)
  - unbounded polling loop (backward branch reading HW register)
  - dispatcher / tail-call (b.w / blx to elsewhere)

Targets:
  0x179C8  (HIGH)  - first BL after T251 saved-LR return in wlc_bmac_attach
  0x67E1C  (MED)   - second BL in continuation
  0x67F2C  (LOW)   - in fn@0x68A68 before wlc_bmac_attach call

Also find the function extent (prologue to epilogue) and look for:
  - backward branches (loops)
  - BL to known delay helpers (0x1ADC, 0x11C8)
  - BL to known polling pattern helpers
  - strings referenced (identifies the function's role)
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_next_prologue(start, max_scan=4096):
    """Find the next function prologue after `start`. Returns offset or None."""
    for off in range(start + 2, min(start + max_scan, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None


def analyze(name, addr):
    print(f"\n{'='*70}")
    print(f"=== {name} @ {addr:#06x} ===")
    print('='*70)

    # Find function extent by scanning forward for next prologue
    next_fn = find_next_prologue(addr)
    extent = (next_fn - addr) if next_fn else 512
    extent = min(extent, 2048)  # cap at 2KB
    print(f"  function extent: {extent} bytes (next prologue at {next_fn:#x})" if next_fn else f"  function extent capped at {extent}")

    # Disassemble the whole function
    insns = list(md.disasm(data[addr:addr + extent + 16], addr, count=0))
    # Truncate to within extent
    insns = [i for i in insns if i.address < addr + extent]

    print(f"  disassembled {len(insns)} instructions")

    # Classification markers
    backward_branches = []  # (insn_addr, target) where target < insn_addr
    bl_calls = []           # all bl/blx targets
    printf_like = []        # bl to 0xa30 etc
    known_delays = []       # bl to 0x1ADC, 0x11C8
    strings_referenced = set()

    # Find pc-rel loads and resolve literal targets
    lit_refs = {}  # insn_addr -> literal value
    for i in insns:
        op = i.op_str
        if i.mnemonic in ("b", "b.w", "bne", "beq", "bls", "blt", "bgt", "bcs", "bcc", "bhi", "bge", "ble", "bmi", "bpl", "bvs", "bvc", "bcc.w", "beq.w", "bne.w", "bgt.w", "bge.w", "blt.w", "ble.w", "bls.w", "bhi.w", "bcs.w", "bmi.w", "bpl.w"):
            if op.startswith("#"):
                try:
                    tgt = int(op[1:], 16)
                    if tgt < i.address:
                        backward_branches.append((i.address, tgt, i.mnemonic))
                except ValueError:
                    pass
        if i.mnemonic in ("bl", "blx"):
            if op.startswith("#"):
                try:
                    tgt = int(op[1:], 16)
                    bl_calls.append((i.address, tgt))
                    if tgt == 0xA30:
                        printf_like.append(i.address)
                    if tgt in (0x1ADC, 0x11C8):
                        known_delays.append((i.address, tgt))
                except ValueError:
                    pass

    # Find string refs (ldr of pc-relative literals that point to ASCII)
    for i in insns:
        if i.mnemonic not in ("ldr", "ldr.w"):
            continue
        op = i.op_str
        if "pc" in op or "[pc" in op:
            # Extract offset from e.g. "r0, [pc, #0x34]"
            try:
                imm_str = op.split("#")[-1].rstrip("]").strip()
                if imm_str.startswith("-"):
                    imm = -int(imm_str[1:], 16)
                else:
                    imm = int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    lit_val = struct.unpack_from("<I", data, lit_addr)[0]
                    # Is it a pointer to ASCII?
                    if 0 < lit_val < len(data):
                        # Check if at lit_val we have printable ASCII-null-terminated
                        s = bytearray()
                        for k in range(80):
                            if lit_val + k >= len(data):
                                break
                            c = data[lit_val + k]
                            if c == 0:
                                break
                            if 32 <= c < 127:
                                s.append(c)
                            else:
                                s = None
                                break
                        if s and len(s) >= 4:
                            strings_referenced.add(s.decode("ascii"))
            except Exception:
                pass

    print(f"\n  backward branches (candidate loops): {len(backward_branches)}")
    for ia, tgt, mnem in backward_branches[:20]:
        # Is the target inside a "tight poll" window (< 24 bytes back)?
        tight = (ia - tgt) < 24
        note = " TIGHT" if tight else ""
        print(f"    {ia:#06x}: {mnem} back to {tgt:#x} (distance {ia-tgt}){note}")

    print(f"\n  BL/BLX calls: {len(bl_calls)}")
    # Group by target
    from collections import Counter
    targets = Counter(tgt for _, tgt in bl_calls)
    for tgt, count in targets.most_common(10):
        # Special annotations
        annot = ""
        if tgt == 0xA30:
            annot = " (printf)"
        elif tgt == 0x1ADC:
            annot = " (delay helper)"
        elif tgt == 0x11C8:
            annot = " (delay / other)"
        elif tgt == 0x14948:
            annot = " (trace helper)"
        elif tgt == 0x63C24:
            annot = " (hndrte_add_isr)"
        elif tgt == 0x7D60:
            annot = " (alloc)"
        elif tgt == 0x91C:
            annot = " (memset/bzero)"
        elif tgt == 0x1298:
            annot = " (heap-alloc)"
        print(f"    bl #{tgt:#06x}  x{count}{annot}")

    print(f"\n  strings referenced: {len(strings_referenced)}")
    for s in sorted(strings_referenced)[:15]:
        print(f"    {s!r}")

    # Short classification
    print(f"\n  CLASSIFICATION:")
    if backward_branches:
        tight_count = sum(1 for ia, tgt, _ in backward_branches if ia - tgt < 24)
        if tight_count > 0:
            print(f"    - HAS TIGHT BACKWARD BRANCHES ({tight_count}) — candidate for polling loop")
            if known_delays:
                print(f"      calls {len(known_delays)} known delay helpers → likely BOUNDED poll")
            else:
                print(f"      no known-delay calls in loop → POTENTIALLY UNBOUNDED poll")
        else:
            print(f"    - has backward branches but all loose-spread (may be just conditional returns)")
    else:
        print(f"    - no backward branches → NO LOOPS (straight-line function or dispatcher)")

    if printf_like:
        print(f"    - prints {len(printf_like)} trace message(s) — has diagnostic output")

    return insns


# === Main ===
insns_179c8 = analyze("0x179C8 (HIGH priority)", 0x179C8)
insns_67e1c = analyze("0x67E1C (MED priority)",  0x67E1C)
insns_67f2c = analyze("0x67F2C (LOW priority)",  0x67F2C)
