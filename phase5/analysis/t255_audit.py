"""Audit POST-TEST.255 per advisor:
1. scan_callers(0x11CC) — does anything actually reach the b.w 0x1C0C?
2. Re-examine 0x115C scheduler body to verify r4 is always 0 at strb [0x629B4].
3. Scan all literal-pool refs and indirect branches that could reach 0x11CC or 0x1C1E."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def scan_callers(target_addr):
    callers = []
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+4], off):
            if insn.mnemonic in ("bl", "blx", "b.w", "b"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"), 16)
                        if t == target_addr:
                            callers.append((insn.address, insn.mnemonic))
                    except ValueError: pass
            break
    return callers

def scan_lit_refs(target_val):
    results = []
    for pat_val in (target_val, target_val | 1):
        p = pat_val.to_bytes(4, "little")
        pos = 0
        while True:
            hit = blob.find(p, pos)
            if hit < 0: break
            results.append((hit, pat_val))
            pos = hit + 1
    return results

print("=== Callers of 0x11CC (the purported WFI-reach instruction) ===")
c = scan_callers(0x11CC)
print(f"Direct BL/B.W callers: {len(c)}")
for a, m in c:
    print(f"  0x{a:06X}: {m}")

r = scan_lit_refs(0x11CC)
print(f"Literal-pool refs to 0x11CC: {len(r)}")
for hit, val in r:
    print(f"  lit@0x{hit:06X} = 0x{val:08X}")

print()
print("=== Callers of 0x1C1E (WFI leaf) — direct + indirect ===")
c = scan_callers(0x1C1E)
print(f"Direct calls: {len(c)}")
for a, m in c: print(f"  0x{a:06X}: {m}")

r = scan_lit_refs(0x1C1E)
print(f"Literal-pool refs (for fn-ptr table): {len(r)}")
for hit, val in r:
    print(f"  lit@0x{hit:06X} = 0x{val:08X}")

print()
print("=== Where the fn-ptr forms 0x1C0C+1, 0x1C1E+1 could appear ===")
for t in (0x1C0D, 0x1C1F):  # Thumb-encoded function pointers
    p = t.to_bytes(4, "little")
    hits = []
    pos = 0
    while True:
        h = blob.find(p, pos)
        if h < 0: break
        hits.append(h)
        pos = h + 1
    print(f"  0x{t:08X} (Thumb ptr to 0x{t-1:06X}): {len(hits)} occurrences")
    for h in hits[:5]: print(f"    lit@0x{h:06X}")

print()
print("=== r4 state at 0x1192 strb? Re-trace from function entry ===")
# Disas from 0x115C to 0x11B8 (function body).
for insn in md.disasm(blob[0x115C:0x11C0], 0x115C):
    mark = ""
    if insn.address == 0x1192: mark = " <-- strb r4, [r6] (advisor claim: r4==0 here)"
    if insn.address == 0x117C: mark = " <-- r4 = r4->next (list walk)"
    if insn.address == 0x117E: mark = " <-- loop cond, r4 becomes 0 at exit"
    if insn.address == 0x1168: mark = " <-- r4 = list head"
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{mark}")
