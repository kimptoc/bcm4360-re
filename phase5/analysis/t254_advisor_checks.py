"""T254 advisor-requested checks:
  1. Find wlc_phy_attach's first call to 0x38A50/0x38A24 table -> which index?
  2. Search blob for WFI (0xBF30) and self-branch (b .) patterns.
  3. Locate chiprev banner call site (grep for 0x0004C53E little-endian).
  4. Cross-check: does fw enable PMCCNTR (PMCR.E bit 0 set via mcr p15,0,*,c9,c12,0)?
"""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

print("=" * 70)
print("CHECK 4 FIRST: PMCCNTR enable check (mcr p15,0,*,c9,c12,0 = PMCR write)")
print("=" * 70)
# Scan all valid Thumb-2 2-byte-aligned instructions for MCR p15, 0, *, c9, c12, 0.
# Thumb-2 MCR encoding: 32-bit instr. Just disasm every 2-byte offset and match.
# To avoid running through the entire blob once per line, disasm a batch.

pmcr_writes = []
pmcntr_writes = []  # cycle counter resets/control
pmcr_reads = []
# Use capstone to find all MCR/MRC p15 coprocessor instructions
# Only scan the code region (< 0x6BF78).
# Full-blob disassembly at every 2-byte boundary is expensive; do a
# byte-pattern search for the MCR p15,0 opcode first.
# Thumb-2 MCR encoding in hex (as stored little-endian):
#   mcr p15,0,Rt,crn,crm,opc2
#   binary: 1110 1110 0 opc1 0 CRn Rt 1111 opc2 1 CRm  (split across 2 halfwords)
# It's easier to just disasm every offset.
import sys
for off in range(0, 0x6BF78, 2):
    # Try to disassemble one 4-byte instruction at this offset
    for insn in md.disasm(blob[off:off+4], off):
        if insn.mnemonic in ("mcr", "mrc"):
            op = insn.op_str
            # Looking for p15, *, *, c9, c12 or c13
            if "p15" in op and ("c9, c12" in op or "c9, c13" in op):
                if insn.mnemonic == "mcr" and "c9, c12" in op:
                    pmcr_writes.append((insn.address, op))
                elif insn.mnemonic == "mrc" and "c9, c13" in op:
                    pmcr_reads.append((insn.address, op))
                elif insn.mnemonic == "mcr" and "c9, c13" in op:
                    pmcntr_writes.append((insn.address, op))
        break  # only look at first insn at this offset

print(f"PMCR writes (mcr p15,0,*,c9,c12,*): {len(pmcr_writes)}")
for a, op in pmcr_writes:
    print(f"  0x{a:06X}: {op}")
print(f"PMCCNTR reads (mrc p15,0,*,c9,c13,0): {len(pmcr_reads)} sites")
for a, op in pmcr_reads[:5]:
    print(f"  0x{a:06X}: {op}")
print(f"PMCCNTR writes (mcr p15,0,*,c9,c13,*): {len(pmcntr_writes)}")
for a, op in pmcntr_writes:
    print(f"  0x{a:06X}: {op}")

print()
print("=" * 70)
print("CHECK 2: WFI (0xBF30) and self-loop (b .) patterns")
print("=" * 70)
# WFI Thumb encoding is 0xBF30 — scan blob for this at even offsets in code region
wfi_hits = []
for off in range(0, 0x6BF78, 2):
    if blob[off] == 0x30 and blob[off+1] == 0xbf:
        wfi_hits.append(off)
print(f"WFI (0xBF30) occurrences in code region: {len(wfi_hits)}")
for a in wfi_hits[:20]:
    print(f"  0x{a:06X}")

# b . = branch to self. Thumb B instruction to current address:
# 16-bit B: 1110 0 imm11; imm11 scaled by 2 (Thumb is halfword).
# `b .` = target == address, so PC+offset+4 == address → offset = -4 → imm11 = -2.
# -2 in 11-bit sign ext: 0x7FE. Instruction: 0xE7FE (b #-2, i.e., branch to self's 2 bytes back then +4 = self).
# Actually `b .` (infinite loop) on Thumb is typically: `b .-2` = 0xE7FE which
# targets 2 bytes before the branch, which points back to itself (loop).
# Common pattern: 0xE7FE (short branch -2). Also 0xF7FF 0xAFFE (32-bit).
self_loops = []
for off in range(0, 0x6BF78, 2):
    w = int.from_bytes(blob[off:off+2], "little")
    if w == 0xE7FE:  # b -2 (self)
        self_loops.append((off, "E7FE (b #-2)"))
print(f"\nSelf-loops (0xE7FE 'b #-2'): {len(self_loops)} occurrences")
for a, t in self_loops[:20]:
    print(f"  0x{a:06X}: {t}")

print()
print("=" * 70)
print("CHECK 3: chiprev banner call site (literal 0x0004C53E)")
print("=" * 70)
# Find 32-bit little-endian 0x0004C53E pattern in blob. It's stored as bytes "3E C5 04 00".
pattern = (0x4C53E).to_bytes(4, "little")
# Also try the +1 Thumb pointer variant
pattern2 = (0x4C53E + 1).to_bytes(4, "little")
print(f"Search for {pattern.hex()} and {pattern2.hex()}:")
for m in [pattern, pattern2]:
    pos = 0
    while True:
        p = blob.find(m, pos)
        if p < 0: break
        print(f"  0x{p:06X}: {m.hex()}")
        pos = p + 1

# The format string at 0x4C53E is likely referenced directly. The nearest
# preceding BL reference is the caller.
# Find occurrences of the string address (0x4C53E, tagged bit 0 ignored)
# Also report the instruction at each hit.
print(f"\nDisassembly context at each pattern hit:")
all_hits = []
pos = 0
while True:
    p = blob.find(pattern, pos)
    if p < 0: break
    all_hits.append(p)
    pos = p + 1
for hit in all_hits:
    # The hit is a literal. Find the PC-relative load that points to it.
    # In Thumb, LDR [PC, #offset] = address + 4 & ~3 + offset = literal_addr
    # So literal_addr - 4 is the ldr instruction's PC+4 boundary.
    # Scan backward for a ldr Rx, [pc, #imm] whose resolved address == hit.
    found = False
    for back_off in range(hit - 0x200, hit, 2):
        if back_off < 0: continue
        for insn in md.disasm(blob[back_off:back_off+4], back_off):
            if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
                try:
                    imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
                    pc_rel = (insn.address + 4) & ~3
                    target = pc_rel + imm
                    if target == hit:
                        print(f"  literal@0x{hit:06X} referenced by ldr at 0x{insn.address:06X}: {insn.op_str}")
                        found = True
                except Exception:
                    pass
            break
    if not found:
        print(f"  literal@0x{hit:06X}: no direct ldr [pc,imm] reference found nearby")

print()
print("=" * 70)
print("CHECK 1: wlc_phy_attach's first call into dispatch tables 0x38A50/0x38A24")
print("=" * 70)
# wlc_phy_attach is at 0x6A954. Walk instructions in order; identify each
# bl or b.w #target where target is in the dispatch table range.
wlc_phy_attach_end = 0x6AED2
insns = list(md.disasm(blob[0x6A954:wlc_phy_attach_end], 0x6A954))
print(f"wlc_phy_attach has {len(insns)} instructions")
# Find calls into 0x38A50..0x38AB0 and 0x38A24..0x38AA8 (ranges include thunk offsets)
dispatch_hits = []
for insn in insns:
    if insn.mnemonic in ("bl", "blx", "b.w", "b"):
        op = insn.op_str
        if op.startswith("#"):
            try:
                tgt = int(op.strip("#"), 16)
                if 0x38A20 <= tgt < 0x38AC0:
                    dispatch_hits.append((insn.address, insn.mnemonic, tgt))
            except ValueError:
                pass
print(f"Calls into dispatch tables: {len(dispatch_hits)}")
for addr, mnem, tgt in dispatch_hits[:30]:
    # Compute index
    tbl_base = 0x38A50 if tgt >= 0x38A50 else 0x38A24
    idx = (tgt - tbl_base) // 4
    # Look at the target thunk
    thunk_bytes = blob[tgt:tgt+6]
    thunks = list(md.disasm(thunk_bytes, tgt))
    if len(thunks) >= 1:
        thunk_desc = f"{thunks[0].mnemonic} {thunks[0].op_str}"
    else:
        thunk_desc = "?"
    print(f"  0x{addr:06X} {mnem} #0x{tgt:06X}  (table 0x{tbl_base:06X} idx {idx}) -> thunk: {thunk_desc}")
