"""T298t (advisor verification): scan for ALL ways fw could construct
the value 0x48080.

Per T297j's pattern: literal pool + Thumb-2 modified-immediate `mov.w` +
movw/movt pair. T297j confirmed PCIE2/D11/etc. bases have ZERO hits across
all three patterns. Apply the same to 0x48080.

Also scan for variants:
- mov.w with #0x48080 directly (Thumb-2 may not support this immediate)
- movw rN, #0x8080 followed by movt rN, #0x4 (constructs 0x00048080 = 0x48080)
- Any AND/ORR pattern that produces 0x48080 from another value
- Direct bl @0x233E8 callers (skipping wrap_ARM) — count them too
"""
import struct, sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted_any = True
            last_end = ins.address + ins.size
            if last_end >= len(data) - 2:
                return
        pos = last_end if emitted_any else pos + 2


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


# (A) mov.w / mov / movs / movw direct match for 0x48080
print("=== (A) `mov.w rN, #0x48080` (Thumb-2 modified-immediate) ===")
hits_a = []
for ins in all_ins:
    if ins.mnemonic in ("mov", "mov.w", "movs", "movw"):
        # capstone might display 0x48080 as "0x48080" or in raw form
        if "#0x48080" in ins.op_str.lower():
            hits_a.append(ins)
        elif "#" + str(0x48080) in ins.op_str:
            hits_a.append(ins)
print(f"Hits: {len(hits_a)}")
for ins in hits_a:
    print(f"  {ins.address:#7x}: {ins.mnemonic} {ins.op_str}")

# (B) movw + movt pair: movw rN, #0x8080; movt rN, #0x4
print("\n=== (B) `movw rN, #0x8080` + `movt rN, #0x4` paired (constructs 0x00048080) ===")
hits_b = []
movws = [(ins.address, ins.op_str) for ins in all_ins if ins.mnemonic == "movw" and "#0x8080" in ins.op_str.lower()]
print(f"  movw r?, #0x8080 hits: {len(movws)}")
for movw_a, movw_op in movws:
    print(f"    {movw_a:#7x}  movw {movw_op}")
    # Look for movt within next 8 ins on same dest reg
    dest = movw_op.split(",")[0].strip()
    for ins in all_ins:
        if ins.address <= movw_a or ins.address > movw_a + 16: continue
        if ins.mnemonic == "movt" and ins.op_str.startswith(dest + ","):
            if "#0x4" in ins.op_str.lower() and not any(x in ins.op_str.lower() for x in ("#0x40","#0x41","#0x42","#0x43","#0x44","#0x45","#0x46","#0x47","#0x48","#0x49","#0x4a","#0x4b","#0x4c","#0x4d","#0x4e","#0x4f")):
                hits_b.append((movw_a, ins.address))
                print(f"      MATCH movt @ {ins.address:#x}: {ins.op_str}")
print(f"Total movw+movt pairs constructing 0x00048080: {len(hits_b)}")


# (C) ORR / AND / ADD that could produce 0x48080
# Less likely in init code; skip for now unless above are zero


# (D) all direct bl/blx callers of fn@0x233E8 (the underlying ARM impl, skipping wrap)
print("\n\n=== (D) ALL bl/blx + b/b.w callers of fn@0x233E8 directly ===")
direct = []
tail = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x233E8: continue
    if ins.mnemonic in ("bl", "blx"):
        direct.append(ins)
    elif ins.mnemonic in ("b", "b.w"):
        tail.append(ins)
print(f"  bl/blx: {len(direct)}")
for ins in direct:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
print(f"  b/b.w tail-call: {len(tail)}")
for ins in tail:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# (E) Any callers of fn@0x2343A directly (the set-mask fn, skipping wrap)
print("\n\n=== (E) bl/blx + b/b.w callers of fn@0x2343A (set-mask impl) ===")
hits_e_bl = []
hits_e_b = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x2343A: continue
    if ins.mnemonic in ("bl", "blx"):
        hits_e_bl.append(ins)
    elif ins.mnemonic in ("b", "b.w"):
        hits_e_b.append(ins)
print(f"  bl/blx: {len(hits_e_bl)}")
for ins in hits_e_bl:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
print(f"  b/b.w tail: {len(hits_e_b)}")
for ins in hits_e_b:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# (F) any wrap_setmask callers that pass a constant arg containing 0x48080's bits
# wrap_setmask is at 0x1179C; the impl is fn@0x2343A which writes r1 → D11+0x16C
# Check wrap_setmask callers (4 from T298s) for what r1 they pass.
print("\n\n=== (F) wrap_setmask callers — what mask value do they pass? ===")
wrap_callers = [
    (0x17cc0, "wrap_setmask call"),
    (0x186cc, "wrap_setmask call"),
    (0x18a24, "wrap_setmask call"),
    (0x19506, "wrap_setmask call"),
    (0x1422c, "wrap_setmask tail-call"),
]
for caller_addr, tag in wrap_callers:
    print(f"\n  {tag} @ {caller_addr:#x}:")
    # Show 6 ins of context before
    seen = 0
    for ins in all_ins:
        if ins.address < caller_addr - 24 or ins.address > caller_addr + 4: continue
        marker = "  <-- CALL" if ins.address == caller_addr else ""
        annot = ""
        # If it's a mov-imm to r1 (the arg reg for set-mask), show value
        if ins.mnemonic in ("mov","mov.w","movs","movw") and ins.op_str.startswith("r1,") and "#" in ins.op_str:
            try:
                imm_s = ins.op_str.split("#")[-1].strip()
                val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
                annot = f"  ; r1 = {val:#x}"
                if val & 0x48080: annot += "  ★ has wake-mask bits"
            except: pass
        elif ins.mnemonic == "ldr" and "r1," in ins.op_str and "[pc," in ins.op_str:
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:],16) if imm_s.startswith("-") else int(imm_s,16)
                la = ((ins.address+4)&~3)+imm
                if 0<=la<=len(data)-4:
                    val = struct.unpack_from('<I',data,la)[0]
                    annot = f"  ; r1 = lit@{la:#x} = {val:#x}"
                    if val & 0x48080: annot += "  ★ has wake-mask bits"
            except: pass
        print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}{annot}")
