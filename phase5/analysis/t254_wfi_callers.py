"""Find all callers of 0x1C1E (wfi leaf) and the tiny thunk at 0x1C0C which
tail-jumps to 0x1C1E. Walk upward one level."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def scan_callers(target_addr):
    """Find all BL/BLX/B.W instructions whose immediate target is target_addr."""
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
                    except ValueError:
                        pass
            break
    return callers

def scan_literal_refs(target_val):
    """Find literal-pool entries matching target_val (both Thumb+1 and plain)."""
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

print("=== Callers of 0x1C1E (WFI leaf) ===")
c = scan_callers(0x1C1E)
print(f"{len(c)} direct callers:")
for a, m in c: print(f"  0x{a:06X}: {m} #0x1C1E")

print("\n=== Literal-pool refs to 0x1C1E (indirect/fn-ptr callers) ===")
r = scan_literal_refs(0x1C1E)
print(f"{len(r)} literal entries:")
for hit, val in r: print(f"  0x{hit:06X} = 0x{val:08X}")

# Thunks: 0x1C0C (b.w 0x1C1E), 0x1C10 (b.w 0x18C), 0x1C16 (b.w 0x1AC)
for thunk in (0x1C0C, 0x1C10, 0x1C16, 0x018C, 0x01AC):
    print(f"\n=== Callers/refs to 0x{thunk:06X} ===")
    c = scan_callers(thunk)
    print(f"  Direct calls: {len(c)}")
    for a, m in c[:10]: print(f"    0x{a:06X}: {m} #0x{thunk:06X}")
    r = scan_literal_refs(thunk)
    print(f"  Literal refs: {len(r)}")
    for hit, val in r[:5]: print(f"    0x{hit:06X} = 0x{val:08X}")

# Also check 0x18C and 0x1AC — these thunk targets
for leaf in (0x18C, 0x1AC):
    print(f"\n=== Disasm of 0x{leaf:06X} (thunk-target leaf) ===")
    for insn in md.disasm(blob[leaf:leaf+12], leaf):
        print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
