#!/usr/bin/env python3
"""T254 detail — full disasm of 0x1722C (strong hit) and 0x14384 (weak hit)
to understand caller args, r4 origin, and loop register target semantics.
Also identify what [r4 + 0x128] refers to by looking at the caller's struct."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(FW_PATH, "rb") as f:
    blob = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_fn_end(start, max_scan=0x4000):
    for off in range(start + 4, start + max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d:
            return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
    return start + max_scan

def resolve_lit(addr, offset_from_pc):
    """Resolve LDR [PC, #imm]. PC for Thumb LDR is (address+4) & ~3."""
    pc_rel = (addr + 4) & ~3
    lit_addr = pc_rel + offset_from_pc
    if lit_addr + 4 <= len(blob):
        return int.from_bytes(blob[lit_addr:lit_addr+4], "little"), lit_addr
    return None, lit_addr

def disas_fn(name, start, show_all=False, highlight_addr=None):
    end = find_fn_end(start)
    insns = list(md.disasm(blob[start:end], start))
    print(f"\n=== {name} at 0x{start:06X}..0x{end:06X} ({len(insns)} insns, {end-start}B) ===")
    if show_all:
        for insn in insns:
            mark = "  *" if highlight_addr and highlight_addr == insn.address else "   "
            print(f"{mark}0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
            # resolve pc-relative literal loads
            if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
                try:
                    off = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
                    val, lit_addr = resolve_lit(insn.address, off)
                    if val is not None:
                        note = f"(lit@0x{lit_addr:06X} = 0x{val:08X}"
                        if 0x18000000 <= val < 0x18010000:
                            note += " [SB core base]"
                        elif 0 < val < len(blob):
                            # might be a string pointer
                            try:
                                end_s = blob.index(b"\x00", val)
                                if 1 <= end_s - val < 60:
                                    s = blob[val:end_s].decode("ascii", errors="replace")
                                    if all(32 <= b < 127 for b in blob[val:end_s]):
                                        note += f" str={s!r}"
                            except ValueError:
                                pass
                            note += f" blob-off"
                        note += ")"
                        print(f"         {note}")
                except Exception:
                    pass
    return insns


# Full 0x1722C
disas_fn("0x1722C (STRONG HW_POLL)", 0x1722C, show_all=True)

print("\n\n" + "="*70)
# Full 0x14384
disas_fn("0x14384 (HW_POLL_WEAK)", 0x14384, show_all=True)

print("\n\n" + "="*70)
# 0x1ADC - delay function called from the polling loop
disas_fn("0x1ADC (delay helper, called from polling loop)", 0x1ADC, show_all=True)

# Check blob references to 0x1722C - which functions call it?
print("\n\n" + "="*70)
print("=== Who calls 0x1722C? (BL blx b.w to 0x1722C scan) ===")
# Thumb-2 BL encoding is complex; instead scan for addr immediates by looking
# at every disas hit.
def scan_callers(target_addr):
    callers = []
    # Scan every 2-byte boundary as potential Thumb-2 instruction start
    # but only in the code region (< 0x6BF78)
    tgt = target_addr
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+6], off):
            if insn.mnemonic in ("bl", "blx", "b.w", "b"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"), 16)
                        if t == tgt:
                            callers.append((insn.address, insn.mnemonic))
                    except ValueError:
                        pass
            break  # Only check first insn at this offset
    return callers

callers = scan_callers(0x1722C)
print(f"Callers of 0x1722C: {len(callers)}")
for addr, mnem in callers:
    print(f"  0x{addr:06X} ({mnem})")
