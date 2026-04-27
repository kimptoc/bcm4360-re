"""T298j: locate the enclosing fn for 0x68B90 (sole caller of fn@0x6820C).

Show all push-lr / pop-pc / bx-lr in [0x68000, 0x68C00) — visualize fn
boundaries directly. Also find callers of fn@0x142E0 (the wake-mask init).
"""
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


print("=== Function boundaries in [0x68000, 0x68C00) ===\n")
for ins in all_ins:
    if ins.address < 0x68000 or ins.address >= 0x68C00:
        continue
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        print(f"  {ins.address:#7x}  PUSH-LR  {ins.op_str}")
    elif ins.mnemonic == "pop" and "pc" in ins.op_str:
        print(f"  {ins.address:#7x}  POP-PC   {ins.op_str}")
    elif ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print(f"  {ins.address:#7x}  BX-LR")
    elif ins.address == 0x68B90:
        print(f"  >>>>>> {ins.address:#x}: TARGET — bl #0x6820C <<<<<<")


print("\n\n=== Callers of fn@0x142E0 (wake-mask init) ===\n")
hits = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x142E0:
                hits.append(ins)
        except: pass
print(f"Direct bl/blx hits to 0x142E0: {len(hits)}")
for ins in hits:
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# Also fn-ptr table refs to 0x142E1
print(f"\n=== Literal references to 0x142E1 (Thumb fn ptr) ===")
needle = struct.pack("<I", 0x142E1)
hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    if idx % 4 == 0:
        hits.append(idx)
    pos = idx + 1
print(f"Aligned literal hits: {len(hits)}")
for h in hits:
    print(f"  file offset {h:#x}")


# Also search for callers of fn@0x68CD2 (the alloc helper inside fn@0x6820C)
print(f"\n\n=== Callers of fn@0x68CD2 (alloc helper for flag_struct) ===\n")
hits = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x68CD2:
                hits.append(ins)
        except: pass
print(f"Direct bl/blx hits: {len(hits)}")
for ins in hits:
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
