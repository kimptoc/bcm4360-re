"""T307b — find the static registration code for the chipcommon-class
ISR dispatch table at TCM[0x62914..0x62950].

Approach:
1. Find every site in the blob that constructs the constant 0x00062914
   either via literal-pool ldr or Thumb-2 movw/movt pair.
2. For each, decode +/-32 bytes around the construction site to identify
   whether the code is reading or writing to the table.
3. Also locate writes near 0x62914 + N*12 = {0x62914, 0x62920, 0x6292C,
   0x62938, 0x62944} (the table-entry mask offsets).
4. Identify writes to 0x62950 (the "global mask" sourced by the
   active-mask computation).

This tells us the chipcommon-class registration API entry point.
"""
import os
import sys
import struct

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from t269_disasm import Cs

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"

# The five mask-field offsets in the dispatch table:
TABLE_BASE = 0x00062914
TABLE_ENTRIES = 5
TABLE_MASK_OFFSETS = [TABLE_BASE + i * 12 for i in range(TABLE_ENTRIES)]
GLOBAL_MASK = 0x00062950  # accessed at fn@0xABC offset 0xAC4-0xAC8

TARGETS = [TABLE_BASE, GLOBAL_MASK] + TABLE_MASK_OFFSETS


def find_literal_pool_refs(blob, target):
    """Find every 4-byte aligned location in the blob where the 32-bit LE
    word equals target. Returns list of offsets."""
    hits = []
    target_bytes = target.to_bytes(4, "little")
    pos = 0
    while True:
        idx = blob.find(target_bytes, pos)
        if idx < 0:
            break
        if idx % 2 == 0:
            hits.append(idx)
        pos = idx + 1
    return hits


def find_movw_movt(blob, target):
    """Find Thumb-2 movw/movt encodings that build `target`.

    movw rd, #imm16  encodes the imm16 split as imm4:i:imm3:imm8.
    movt rd, #imm16  uses upper 16 bits.

    For our purposes, scan all 4-byte aligned (Thumb pairs are 2-byte
    aligned, but we want pairs of 32-bit instructions = 8 bytes).
    Take a simpler approach: scan halfwords looking for movw rD, #imm16-low
    immediately followed by movt rD, #imm16-high where the combined value
    equals target. This is the standard pattern for constants that don't
    fit in literal-pool reach.
    """
    lo = target & 0xFFFF
    hi = (target >> 16) & 0xFFFF
    hits = []
    # Encode movw rD lo: bits = 11110 i 1 0 0 1 0 0 imm4 | 0 imm3 rD imm8
    # We don't need to filter precisely — we just look for the pattern
    # encoding lo immediately followed by an instruction encoding hi,
    # both with the same destination register.
    n = len(blob)
    for off in range(0, n - 8, 2):
        # Decode halfword at off (Thumb-2 first half) and at off+4 (next instruction).
        h0 = struct.unpack_from("<H", blob, off)[0]
        # Movw first half: 11110 i 100100 imm4 = 1111 0X10 0100 IIII
        # Mask out i and imm4, check fixed bits.
        if (h0 & 0xFBF0) != 0xF240:
            continue
        h1 = struct.unpack_from("<H", blob, off + 2)[0]
        # Movw second half: 0 imm3 rD imm8 — bit 15 = 0
        if h1 & 0x8000:
            continue
        # Reconstruct imm16: imm4(h0[3:0]) : i(h0[10]) : imm3(h1[14:12]) : imm8(h1[7:0])
        imm4 = h0 & 0xF
        i = (h0 >> 10) & 1
        imm3 = (h1 >> 12) & 0x7
        imm8 = h1 & 0xFF
        rd = (h1 >> 8) & 0xF
        imm16 = (imm4 << 12) | (i << 11) | (imm3 << 8) | imm8
        if imm16 != lo:
            continue
        # Look for movt at off+4 with same rD producing hi
        if off + 8 > n:
            continue
        h2 = struct.unpack_from("<H", blob, off + 4)[0]
        h3 = struct.unpack_from("<H", blob, off + 6)[0]
        # Movt first half: 11110 i 101100 imm4 = 1111 0X10 1100 IIII
        if (h2 & 0xFBF0) != 0xF2C0:
            continue
        if h3 & 0x8000:
            continue
        rd2 = (h3 >> 8) & 0xF
        if rd2 != rd:
            continue
        imm4b = h2 & 0xF
        ib = (h2 >> 10) & 1
        imm3b = (h3 >> 12) & 0x7
        imm8b = h3 & 0xFF
        imm16b = (imm4b << 12) | (ib << 11) | (imm3b << 8) | imm8b
        if imm16b == hi:
            hits.append(off)
    return hits


def disasm_around(blob, addr, before=16, after=32):
    md = Cs()
    start = max(0, addr - before)
    end = min(len(blob), addr + after)
    chunk = blob[start:end]
    insns = md.disasm(chunk, start)
    return insns


def main():
    with open(BLOB, "rb") as f:
        blob = f.read()
    print(f"# T307b: hunt for static writers of dispatch table TCM[0x{TABLE_BASE:08X}..0x{TABLE_BASE+60:08X}]")
    print(f"# blob = {BLOB} ({len(blob)} bytes)")
    print()
    print("# Targets being searched:")
    for t in TARGETS:
        print(f"#   0x{t:08X}")
    print()
    print("# === literal-pool occurrences ===")
    found_lp = {}
    for t in TARGETS:
        hits = find_literal_pool_refs(blob, t)
        # Filter: literal pool entries are typically embedded in code regions
        # (likely between functions or after function ends). Just print all
        # alignment-4 hits.
        aligned = [h for h in hits if h % 4 == 0]
        if aligned:
            print(f"# 0x{t:08X}:")
            for h in aligned:
                print(f"#   blob[0x{h:05X}] = 0x{t:08X}")
            found_lp[t] = aligned
    print()
    print("# === movw/movt occurrences ===")
    for t in TARGETS:
        hits = find_movw_movt(blob, t)
        if hits:
            print(f"# 0x{t:08X}:")
            for h in hits:
                print(f"#   blob[0x{h:05X}] movw/movt building 0x{t:08X}")

    # Now disasm around each literal pool hit (within range of the ldr
    # instruction). The pool is referenced by ldr.w or ldr [pc, #imm]
    # within the function body — typically up to 4 KB before.
    print()
    print("# === Functions referencing the table base 0x62914 (literal-pool consumers within 4 KB before) ===")
    for h in found_lp.get(TABLE_BASE, []):
        # Scan the 4 KB before the literal for ldr [pc] instructions
        # whose target is this pool entry.
        scan_start = max(0, h - 4096)
        md = Cs()
        chunk = blob[scan_start:h + 4]
        insns = md.disasm(chunk, scan_start)
        for ins in insns:
            if ins.mnemonic.startswith("ldr") and "[pc" in ins.op_str:
                # parse the target
                # capstone's op_str looks like "r3, [pc, #0x34]" — compute the
                # actual target.
                pcv = ins.address + 4
                if "thumb" in ins.mnemonic.lower() or ins.size == 2:
                    pcv &= ~3  # word-align
                else:
                    pcv &= ~3
                # extract immediate
                op = ins.op_str
                if "#" in op:
                    try:
                        imm_str = op.split("#")[-1].rstrip("]")
                        imm = int(imm_str, 0)
                    except Exception:
                        imm = None
                    if imm is not None and pcv + imm == h:
                        print(f"  0x{ins.address:05X}: {ins.mnemonic} {ins.op_str}    -> reads 0x{TABLE_BASE:08X}")
                        # Print the surrounding context
                        ctx = disasm_around(blob, ins.address, before=12, after=24)
                        for cins in ctx:
                            mark = "  > " if cins.address == ins.address else "    "
                            b = " ".join(f"{x:02x}" for x in cins.bytes)
                            print(f"{mark}0x{cins.address:05X}: {b:<14} {cins.mnemonic:<8} {cins.op_str}")
                        print()


if __name__ == "__main__":
    main()
