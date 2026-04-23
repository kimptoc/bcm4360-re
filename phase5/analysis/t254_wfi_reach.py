"""Advisor stop-ship: verify 0x1C1E WFI reachability. Find enclosing function
and who calls it. Also grep blob for WFE (0xBF20)."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_prev_fn(addr, max_back=0x2000):
    """Find a likely function start (push prologue) before addr."""
    candidates = []
    for off in range(addr, max(0, addr - max_back), -2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        w32 = int.from_bytes(blob[off:off+4], "little") if off+4 <= len(blob) else 0
        # Thumb-2 push.w {..., lr}: 0xE92D XXXX (low 16 = 0xE92D)
        if w16 == 0xe92d:
            candidates.append(("push.w", off))
            return off
        # Thumb-1 push {..., lr}: 0xB5XX with bit 8 clear if only {lr} else set
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            candidates.append(("push", off))
            return off
    return None

# 0x1C1E WFI analysis
print("=" * 70)
print("WFI at 0x1C1E — enclosing function + call context")
print("=" * 70)
fn_start = find_prev_fn(0x1C1E)
print(f"Enclosing function likely starts at 0x{fn_start:06X}")

# Disassemble from fn_start to 30 bytes past WFI
print(f"\nDisassembly of function 0x{fn_start:06X}:")
for insn in md.disasm(blob[fn_start:0x1C1E + 20], fn_start):
    marker = " <-- WFI" if insn.address == 0x1C1E else ""
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{marker}")

# Who calls fn_start?
print(f"\nCallers of 0x{fn_start:06X} (scan for BL/B.W):")
callers = []
for off in range(0, 0x6BF78, 2):
    for insn in md.disasm(blob[off:off+4], off):
        if insn.mnemonic in ("bl", "blx", "b.w", "b"):
            op = insn.op_str
            if op.startswith("#"):
                try:
                    t = int(op.strip("#"), 16)
                    if t == fn_start:
                        callers.append((insn.address, insn.mnemonic))
                except ValueError:
                    pass
        break

if not callers:
    # Maybe the function is called indirectly (via function pointer) — not detected.
    # Check if fn_start address appears in any literal pool in the blob.
    pat_thumb = (fn_start | 1).to_bytes(4, "little")  # Thumb +1
    pat_plain = fn_start.to_bytes(4, "little")
    print(f"  No direct BL callers found. Literal-pool search:")
    for p in (pat_thumb, pat_plain):
        pos = 0
        while True:
            found = blob.find(p, pos)
            if found < 0: break
            print(f"    literal 0x{int.from_bytes(p, 'little'):08X} at blob offset 0x{found:06X}")
            pos = found + 1
else:
    for addr, mnem in callers:
        print(f"  0x{addr:06X}: {mnem} #0x{fn_start:06X}")

# Also walk back further — check if the enclosing function is actually much larger
print(f"\nExtended scan: any push.w/push preceding 0x1C1E within 0x2000?")
found_pushes = []
for off in range(max(0, 0x1C1E - 0x2000), 0x1C1E, 2):
    w16 = int.from_bytes(blob[off:off+2], "little")
    if w16 == 0xe92d:
        found_pushes.append(("push.w", off))
    elif (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
        found_pushes.append(("push", off))
for kind, off in found_pushes[-20:]:
    print(f"  {kind} at 0x{off:06X}")

# ---- WFE scan ----
print()
print("=" * 70)
print("WFE (0xBF20) scan")
print("=" * 70)
wfe_hits = []
for off in range(0, 0x6BF78, 2):
    if blob[off] == 0x20 and blob[off+1] == 0xbf:
        wfe_hits.append(off)
print(f"WFE (0xBF20) occurrences in code region: {len(wfe_hits)}")
# Check context of each — is it really a WFE, or data?
for a in wfe_hits[:30]:
    # Disassemble from a few bytes before to check it's aligned
    # and see the neighbors
    for insn in md.disasm(blob[a:a+6], a):
        if insn.address == a and insn.mnemonic == "wfe":
            # Valid WFE — show surrounding context
            start = max(0, a-10)
            print(f"\n  WFE at 0x{a:06X}:")
            for ctx in md.disasm(blob[start:a+12], start):
                mark = " <-- WFE" if ctx.address == a else ""
                print(f"    0x{ctx.address:06X}: {ctx.mnemonic:<8} {ctx.op_str}{mark}")
        break
    else:
        # Not recognized as WFE — likely data
        pass
