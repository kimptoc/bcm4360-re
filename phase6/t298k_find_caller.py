"""T298k: dump the fn that contains 0x68B90 (caller of fn@0x6820C).

Disasm forward from 0x68208 (just past the prior fn) to find the next push-lr.
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


# Try various alignments past 0x68204 to find a coherent push-lr
print("=== Disasm from 0x68208 looking for push-lr (start of caller fn) ===\n")
chunk = data[0x68208:0x68C00]
for ins in md.disasm(chunk, 0x68208):
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        print(f"  *** {ins.address:#7x}  PUSH-LR  {ins.op_str}")
    elif ins.mnemonic == "pop" and "pc" in ins.op_str:
        print(f"      {ins.address:#7x}  POP-PC")
    elif ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print(f"      {ins.address:#7x}  BX-LR")
    elif ins.address in (0x68B90,):
        print(f"      >>>> {ins.address:#x}: TARGET <<<<")
    elif ins.address >= 0x68B70 and ins.address <= 0x68BA0:
        print(f"      {ins.address:#7x}  {ins.mnemonic} {ins.op_str}")


# Try OFFSET +1 (in case of mid-instruction misalignment)
print("\n\n=== Re-disasm from 0x6820A (offset+2) to test alignment ===\n")
chunk = data[0x6820A:0x68C00]
push_count = 0
for ins in md.disasm(chunk, 0x6820A):
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        push_count += 1
        if push_count <= 6:
            print(f"  *** {ins.address:#7x}  PUSH-LR  {ins.op_str}")
print(f"Total pushes seen with +2 align: {push_count}")


# Try from 0x68500 forward — explicitly seek for next coherent fn start
print("\n\n=== Forward scan from 0x68500..0x68C00 looking for push-lr ===\n")
hits_in_range = []
for ins in md.disasm(data[0x68500:0x68C00], 0x68500):
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        hits_in_range.append((ins.address, ins.op_str))

print(f"Pushes seen: {len(hits_in_range)}")
for a, op in hits_in_range[:10]:
    print(f"  {a:#x}: PUSH {op}")


# Also look for the LITERAL value 0x6820D (Thumb fn ptr to fn@0x6820C)
# in the area near 0x68B90 — maybe the caller calls indirectly via a fn-ptr table
print("\n\n=== Literal 0x6820D (Thumb ptr to fn@0x6820C) anywhere in 0x68000..0x68FFF ===\n")
needle = struct.pack("<I", 0x6820D)
for offset in range(0x68000, 0x68FFF, 4):
    if data[offset:offset+4] == needle:
        print(f"  fn-ptr at {offset:#x}")
