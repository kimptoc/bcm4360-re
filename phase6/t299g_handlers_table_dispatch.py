"""T299g: find the dispatch mechanism for the wlc-handlers table at 0x58F1C.

The table contains:
  +0x00: wl_probe (0x67615)
  +0x04: wl_open (0x11649)
  +0x08: wl_close? (0x1132D)
  +0x0C: wl_ioctl? (0x11605)
  ...

Find code that:
1. Reads the table base 0x58F1C from a literal
2. Then loads [base, +0x04] (the wl_open ptr)
3. Calls it (blx rN)

OR: code that loads via [some_struct, +0x4] where some_struct = handlers table.

Per T289b §1, the table is referenced once at 0x58F00 (which contains 0x58F1C).
So the table base is at 0x58F00 (a wrapper struct?). Find readers of 0x58F00.
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


# Show what's at 0x58F00..0x58F40
print("=== Bytes at 0x58F00..0x58F40 (wlc-handlers table area) ===")
for off in range(0x58f00, 0x58f40, 4):
    val = struct.unpack_from('<I', data, off)[0]
    print(f"  {off:#x}: {val:#010x}")


# Find code refs to 0x58F00 (the wrapper struct base) and 0x58F1C (the table itself)
print("\n=== Code refs to 0x58F00 (wrapper struct base) ===")
refs_58f00 = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x58F00:
                refs_58f00.append((ins.address, la))
    except: pass
print(f"  Hits: {len(refs_58f00)}")
for ref_a, la in refs_58f00:
    print(f"    {ref_a:#x} (lit@{la:#x})")


print("\n=== Code refs to 0x58F1C (handlers table base) ===")
refs_58f1c = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x58F1C:
                refs_58f1c.append((ins.address, la))
    except: pass
print(f"  Hits: {len(refs_58f1c)}")
for ref_a, la in refs_58f1c:
    print(f"    {ref_a:#x} (lit@{la:#x})")

# Search for byte occurrences of 0x58F1C / 0x58F00 in any alignment (struct templates)
print("\n=== ALL byte occurrences of 0x58F1C (any alignment) ===")
needle = struct.pack("<I", 0x58F1C)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  Hits: {len(hits)}")
for h in hits:
    print(f"    {h:#x} aligned={h%4==0}")


print("\n=== ALL byte occurrences of 0x58F00 ===")
needle = struct.pack("<I", 0x58F00)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  Hits: {len(hits)}")
for h in hits:
    print(f"    {h:#x} aligned={h%4==0}")


# Show what string corresponds to lit@0x4A064 (printf in fn@0x1164A) — verify
print("\n=== Verifying string at 0x4A064 directly ===")
chunk = data[0x4a064:0x4a080]
print(f"  bytes: {chunk.hex()}")
print(f"  ascii: {chunk.decode('ascii', errors='replace')!r}")
