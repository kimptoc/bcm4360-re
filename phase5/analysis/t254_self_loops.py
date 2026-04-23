"""Investigate 0x464F6 and 0x468F4 self-loops. Get their surrounding context
to understand when fw would reach them. Also try MOVW/MOVT-based chiprev
banner reference since the simple LDR-pool scan found nothing."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def disas_around(addr, before=64, after=32):
    """Disassemble around a given address. Since Thumb is variable-length,
    start disassembly from a known-good point (addr - before, aligned)."""
    start = (addr - before) & ~1
    end = addr + after
    insns = list(md.disasm(blob[start:end], start))
    for insn in insns:
        marker = " <-- SELF-LOOP" if insn.address == addr else ""
        print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{marker}")

print("=" * 70)
print("Context of self-loop at 0x464F6")
print("=" * 70)
disas_around(0x464F6, 80, 8)

print()
print("=" * 70)
print("Context of self-loop at 0x468F4")
print("=" * 70)
disas_around(0x468F4, 80, 8)

# Find strings nearby that might hint at which function these belong to.
import re
def nearby_strings(addr, radius=0x200):
    for m in re.finditer(rb"[ -~]{6,80}", blob[addr-radius:addr+radius]):
        chunk = m.group()
        if chunk.count(b" ") > 0 or b"." in chunk or b":" in chunk:
            p = addr - radius + m.start()
            s = chunk.split(b"\x00")[0]
            if 6 < len(s) < 80:
                print(f"  near 0x{p:06X}: {s!r}")

print()
print("Strings near 0x464F6:")
nearby_strings(0x464F6, 0x800)
print()
print("Strings near 0x468F4:")
nearby_strings(0x468F4, 0x800)

# Now find who calls addresses near these self-loops. Build a caller map
# for any code address in [self-loop - 0x80, self-loop + 4].
print()
print("=" * 70)
print("Who reaches 0x464F6 / 0x468F4 via BL?")
print("=" * 70)
targets = [(0x46488, 0x46500, "0x464F6 region"), (0x46880, 0x46900, "0x468F4 region")]
for tgt_start, tgt_end, label in targets:
    print(f"\nCallers reaching {label}:")
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+4], off):
            if insn.mnemonic in ("bl", "blx", "b.w"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"), 16)
                        if tgt_start <= t < tgt_end:
                            print(f"  0x{insn.address:06X}: {insn.mnemonic} #0x{t:06X}")
                    except ValueError:
                        pass
            break

# Find function starts preceding these addresses
print()
print("=" * 70)
print("Nearest function starts preceding the self-loops")
print("=" * 70)
def find_prev_fn(addr, max_back=0x2000):
    for off in range(addr, max(0, addr - max_back), -2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d:
            return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
    return None

for loop_addr in (0x464F6, 0x468F4):
    fn = find_prev_fn(loop_addr)
    print(f"Self-loop 0x{loop_addr:06X} is inside function starting at 0x{fn:06X}  (distance {loop_addr - fn} bytes)")

# Try MOVW/MOVT chiprev-banner reference search.
# MOVW Rn, #imm16 encoding: F240 xxxx (32-bit Thumb-2); MOVT Rn, #imm16: F2C0 xxxx.
# For addr 0x4C53E: low16=0xC53E, high16=0x0004.
# MOVW would store C5 3E in imm16 with some bit reshuffling. Easiest: disasm
# every 2-byte offset and check the mov* + const pair.
print()
print("=" * 70)
print("CHIPREV BANNER: search for movw/movt pair loading 0x4C53E or 0x4C53F")
print("=" * 70)
targets_low = {0xC53E, 0xC53F}  # low 16 bits
targets_high = {0x0004}  # high 16 bits
candidates_movw = []
for off in range(0, 0x6BF78, 2):
    for insn in md.disasm(blob[off:off+4], off):
        if insn.mnemonic in ("movw", "mov.w"):
            op = insn.op_str
            # Format: "rX, #imm"
            if "#" in op:
                try:
                    imm = int(op.split("#")[-1].strip(), 16) if "0x" in op else int(op.split("#")[-1].strip())
                    if imm in targets_low:
                        candidates_movw.append((insn.address, "movw low", imm, op))
                    elif imm == 0x4C53E or imm == 0x4C53F:
                        # Some assemblers render the full imm32 directly
                        candidates_movw.append((insn.address, "movw full", imm, op))
                except Exception:
                    pass
        break

print(f"MOVW candidates matching 0xC53E/F: {len(candidates_movw)}")
for addr, kind, imm, op in candidates_movw[:10]:
    # Check if next instruction is movt high=0x0004
    next_insns = list(md.disasm(blob[addr+4:addr+8], addr+4))
    if next_insns and next_insns[0].mnemonic == "movt":
        print(f"  0x{addr:06X}: {kind} {op}  → next: {next_insns[0].mnemonic} {next_insns[0].op_str}")
    else:
        print(f"  0x{addr:06X}: {kind} {op}  → next: (not movt)")
