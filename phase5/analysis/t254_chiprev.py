"""Re-search for chiprev banner call site using correct string start 0x4C534.
Also search for other wlc_bmac_attach key strings to constrain hang location."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_literal_refs(target_addr):
    """Find all LDR [PC, #imm] references that resolve to target_addr."""
    pattern = target_addr.to_bytes(4, "little")
    refs = []
    pos = 0
    while True:
        p = blob.find(pattern, pos)
        if p < 0: break
        # This is a literal pool entry. Find the ldr that references it.
        for back_off in range(max(0, p - 0x100), p, 2):
            for insn in md.disasm(blob[back_off:back_off+4], back_off):
                if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
                    try:
                        imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
                        pc_rel = (insn.address + 4) & ~3
                        if pc_rel + imm == p:
                            refs.append((insn.address, p, insn))
                    except Exception:
                        pass
                break
        pos = p + 1
    return refs

print("=" * 70)
print("CHIPREV BANNER — literal 0x0004C534 (correct start of fmt string)")
print("=" * 70)
refs = find_literal_refs(0x4C534)
print(f"Found {len(refs)} LDR references to literal 0x4C534:")
for ldr_addr, lit_addr, insn in refs:
    print(f"  0x{ldr_addr:06X}: {insn.mnemonic} {insn.op_str}  (lit@0x{lit_addr:06X})")

# For each reference, find the nearest BL call after the LDR (that's the printf)
for ldr_addr, lit_addr, insn in refs:
    print(f"\n-- Disasm near LDR @ 0x{ldr_addr:06X} --")
    for nxt in md.disasm(blob[ldr_addr:ldr_addr+40], ldr_addr):
        print(f"    0x{nxt.address:06X}: {nxt.mnemonic:<8} {nxt.op_str}")
        if nxt.mnemonic == "bl":
            break

print()
print("=" * 70)
print("Wlc_bmac_attach key strings — find all references to identify call-order")
print("=" * 70)
# Known wlc_bmac-related strings and their addresses
known_strings = {
    0x4C534: "chiprev banner",
    0x4B189: "wlc_bmac_suspend_mac_and_wait",
    0x4B3BC: "wlc_bmac.c (assert file)",
    0x4BCE4: "? (used in 0x1722C trace)",
    0x47589: "? (chipst/pmucaps banner)",
    0x6BAE4: "RTE banner",
    0x6BB1C: "WL controller banner",
}

for addr, desc in known_strings.items():
    refs = find_literal_refs(addr)
    if refs:
        first = refs[0][0]
        print(f"  0x{addr:06X} {desc:50s}: {len(refs)} ref(s), first at 0x{first:06X}")
    else:
        print(f"  0x{addr:06X} {desc:50s}: NO REFS")

# Also search for references to the RTE banner fmt string to identify wlc_bmac_attach start
# The call-site blob[0x6454C] for the RTE banner was stated in T251 analysis.
# And the "wlc_attach" literal that T251 mentioned lives somewhere near 0x68D2E.
print()
print("=" * 70)
print("wlc_attach / wlc_bmac_attach function-name literal refs")
print("=" * 70)
# Find "wlc_attach\0" in blob
import re
for m in re.finditer(rb"wlc_attach\x00", blob):
    refs = find_literal_refs(m.start())
    print(f"  str 'wlc_attach' at 0x{m.start():06X}: {len(refs)} ref(s)")
    for r in refs[:4]:
        print(f"    from 0x{r[0]:06X}")

for m in re.finditer(rb"wlc_bmac_attach\x00", blob):
    refs = find_literal_refs(m.start())
    print(f"  str 'wlc_bmac_attach' at 0x{m.start():06X}: {len(refs)} ref(s)")
    for r in refs[:4]:
        print(f"    from 0x{r[0]:06X}")
