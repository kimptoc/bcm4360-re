"""Three advisor-requested pre-T256 checks:
1. Is 0x9627C (callback list head) a .data initializer value in blob?
2. Disasm 0x9936 for any BSS side-effect writes.
3. Also scan blob for 0x62A98 (context ptr) and 0x96F2C (current-task ptr) as .data inits.
"""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Check 1: does 0x9627C or 0x96F2C or 0x62A98 appear in blob as a literal?
for val, desc in [(0x9627C, "callback list head value"),
                   (0x96F2C, "current-task ptr value"),
                   (0x62A98, "context ptr value")]:
    p = val.to_bytes(4, "little")
    hits = []
    pos = 0
    while True:
        h = blob.find(p, pos)
        if h < 0: break
        hits.append(h)
        pos = h + 1
    print(f"  0x{val:08X} ({desc}): {len(hits)} occurrences")
    for h in hits[:5]: print(f"    blob@0x{h:06X}")

print()
print("=== Disasm 0x9936 (bl target from scheduler 0x1162) ===")
def find_fn_end(start, max_scan=0x400):
    for off in range(start+4, start+max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d: return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0: return off
    return start+max_scan

end = find_fn_end(0x9936)
print(f"0x9936 end at 0x{end:06X} ({end-0x9936} bytes)")
for insn in md.disasm(blob[0x9936:end], 0x9936):
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
    if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
        try:
            imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
            lit = ((insn.address+4)&~3) + imm
            val = int.from_bytes(blob[lit:lit+4], "little")
            note = ""
            if 0x40000 <= val < 0x70000: note = " (blob-range: data/str)"
            elif 0x80000 <= val < 0xA0000: note = " (TCM BSS/heap)"
            elif val < 0x10000: note = " (code)"
            elif val & 0x80000000: note = " (fw VA)"
            print(f"             lit@0x{lit:06X} = 0x{val:08X}{note}")
        except: pass
