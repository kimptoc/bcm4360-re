"""T298s: find direct bl/b.w callers of the wrapper entries 0x11790, 0x11796, 0x1179c."""
import sys, struct
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


# Search for bl/b.w/b targeting each wrapper entry
for tag, target in (
    ("wrap_ARM start", 0x11790),
    ("wrap_DISARM start", 0x11796),
    ("wrap_0x2343A start", 0x1179C),
    # Also fn@0x2343A directly (the third wrapper's tail-call target)
    ("fn@0x2343A direct", 0x2343A),
):
    direct = []
    tail = []
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != target: continue
        if ins.mnemonic in ("bl", "blx"):
            direct.append(ins)
        elif ins.mnemonic in ("b", "b.w"):
            tail.append(ins)
    print(f"{tag} ({target:#x}):")
    print(f"  bl/blx callers: {len(direct)}")
    for ins in direct:
        print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
    print(f"  b/b.w tail-callers: {len(tail)}")
    for ins in tail:
        print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
    print()


# Also search for 0x11791/0x11797/0x1179D bytes ANYWHERE (any alignment)
print("=== Packed Thumb-ptr bytes for wrapper entries (any alignment) ===")
for tag, ptr_val in (("wrap_ARM 0x11791", 0x11791),
                      ("wrap_DISARM 0x11797", 0x11797),
                      ("wrap_2343A 0x1179D", 0x1179D)):
    needle = struct.pack("<I", ptr_val)
    hits = []
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx)
        pos = idx + 1
    print(f"  {tag}: {len(hits)} hit(s)")
    for h in hits:
        print(f"    {h:#x} (aligned {h%4==0})")


# What's at 0x2343A — sibling of fn@0x233E8 / 0x2340C — let me dump its body
print("\n\n=== fn@0x2343A body ===")
for ins in md.disasm(data[0x2343A:0x2343A+0x60], 0x2343A):
    annot = ""
    if ins.mnemonic in ("mov","mov.w","movs","movw") and "#" in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].strip()
            val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
            annot = f"  ; const={val:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end]"); break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [bx lr]"); break
