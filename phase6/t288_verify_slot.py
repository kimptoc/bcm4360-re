"""T288: verify slot=17 = PCIE2 hypothesis.

Two independent checks:
1. Re-read class-0 thunk at 0x27ec area to find the actual origin of r3=0x96
   (T283 claimed "class+0x96" but didn't show the add instruction).
2. Grep fn@0x64590 for BCMA_CORE_PCIE2 core-id = 0x83c. If the enumerator
   compares core-id against 0x83c anywhere, that tells us whether slot=17
   is indeed PCIE2.
3. Also check the T287b data: +0x18 = 0x58680001 = chipc.caps. That matches
   slot-0 (chipcommon). If core enum writes chipcommon's caps at +0x18
   via some per-slot field at stride 4, then slot 0's write offset = 0x18
   and slot 17 = 0x18+17*4 = 0x5c. But T287b didn't read +0x5c. The
   +0x18 field for chipcommon might come from a DIFFERENT write path
   (si_doattach reads chipc[0]=chipid which includes caps in lower bits).
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def disasm_range(start, end, label):
    print(f"\n=== {label} ({start:#x}..{end:#x}) ===")
    window = data[start:end]
    for i in md.disasm(window, start, count=0):
        annot = ""
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit={v:#x}"
            except Exception: pass
        if i.mnemonic in ("mov.w", "movw", "add.w", "adds", "add") and "#" in i.op_str:
            # Flag key constants
            for const_name, const_val in [("PCIE2 core-id", 0x83c),
                                           ("CC core-id", 0x800),
                                           ("ARM-CR4 core-id", 0x83E),
                                           ("0x96 (word-idx to 0x258)", 0x96),
                                           ("0x258 (byte-offset)", 0x258)]:
                if f"#{hex(const_val)}" in i.op_str.lower() or f"#{const_val}," in i.op_str:
                    annot += f"  [*** {const_name} ***]"
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")


# 1. Class-0 thunk and its entry — trace how r3 gets 0x96
print("=" * 70)
print("CHECK 1: class-0 thunk at 0x27ec — how does r3 get 0x96 before 0x287c?")
print("=" * 70)
disasm_range(0x27ec, 0x28a8, "class-0 thunk region (0x27ec..0x28a8)")

# 2. BIT_alloc caller context
print()
print("=" * 70)
print("CHECK 2: BIT_alloc entry at 0x9940 / 0x9944 — r3=0x96 origin")
print("=" * 70)
disasm_range(0x9930, 0x99a0, "BIT_alloc area (fn@0x9940, fn@0x9944)")

# 3. Look for PCIE2 core-id (0x83c) compares in fn@0x64590
print()
print("=" * 70)
print("CHECK 3: PCIE2 core-id (0x83c) anywhere in fn@0x64590 body?")
print("=" * 70)
# Scan the body of fn@0x64590 specifically
for pat_name, pat_val in [("0x83c PCIE2", 0x83c),
                          ("0x800 CC", 0x800),
                          ("0x83E CR4", 0x83E)]:
    found_here = []
    for addr in range(0x64590, 0x64830, 2):
        win = data[addr:addr+4]
        try:
            for ins in md.disasm(win, addr, count=1):
                if f"#{hex(pat_val)}" in ins.op_str.lower() or f"#{pat_val}," in ins.op_str:
                    found_here.append((addr, ins.mnemonic, ins.op_str))
                break
        except Exception: pass
    print(f"  {pat_name}: {len(found_here)} hits")
    for addr, mn, op in found_here[:5]:
        print(f"    {addr:#x}: {mn} {op}")

# 4. Literal pool: any occurrence of 0x83c, 0x800, 0x83E in literal slots
print()
print("=" * 70)
print("CHECK 4: Literal-pool occurrences of core IDs in full blob")
print("=" * 70)
for pat_name, pat_val in [("0x83c PCIE2", 0x83c),
                          ("0x800 CC", 0x800),
                          ("0x83E CR4", 0x83E)]:
    occurrences = []
    pat = struct.pack("<I", pat_val)
    start = 0
    while True:
        idx = data.find(pat, start)
        if idx < 0: break
        occurrences.append(idx)
        start = idx + 1
        if len(occurrences) >= 20: break
    print(f"  {pat_name}: {len(occurrences)} blob occurrences (first 10: {[hex(x) for x in occurrences[:10]]})")
