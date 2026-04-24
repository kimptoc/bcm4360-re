"""T281 deliverable (1): trace fn@0x2309c — the trigger-check function
called by fn@0x23374 at 0x2338a. This is where the 'did fn@0x1146C's
event fire?' test happens.

Key question: does fn@0x2309c read a HW register, a memory flag, or a
timer? That's the trigger we need T279 to poke.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1):
        return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data):
            break
        c = data[addr + k]
        if c == 0:
            break
        if 32 <= c < 127:
            s.append(c)
        else:
            return None
    return s.decode("ascii") if len(s) >= 3 else None


def dump(entry, label, max_bytes=512):
    print(f"\n=== {label} @{entry:#x} ===")
    window = data[entry:entry + max_bytes]
    ins = list(md.disasm(window, entry, count=0))
    saw_ret = False
    for i in ins:
        annot = ""
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                annot = f"  ← fn@{t:#x}"
                if t == 0xA30: annot = "  ← printf"
                elif t == 0x11e8: annot = "  ← printf/assert"
                elif t == 0x14948: annot = "  ← trace"
            except ValueError:
                pass
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    s = str_at(v)
                    if s:
                        annot = f"  '{s}'"
                    else:
                        annot = f"  lit = {v:#x}"
            except Exception:
                pass
        # HW IO-mapped literal addresses (Broadcom chipset MMIO is 0x1800xxxx)
        if "0x18000" in i.op_str or "0x18001" in i.op_str or "0x18002" in i.op_str:
            annot = annot or "  *** HW IO-mapped reg ***"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if i.mnemonic == "bx" and i.op_str == "lr":
            saw_ret = True
        if saw_ret and i.mnemonic == "push":
            print("  --- next fn prologue; stopping ---")
            break


# Primary target: fn@0x2309c (the trigger check)
dump(0x2309c, "fn@0x2309c — trigger-check (called from fn@0x23374)", 400)

# Also resolve fn@0x23374's own strings for context (the assert string).
# It loads `ldr r0, [pc, #0x1c]` at 0x233c6; pc+4 = 0x233ca, &~3 = 0x233c8,
# +0x1c = 0x233e4 — let's read it.
for lit_addr, label in [
    (0x233c8 + 0x1c, "fn@0x23374 assert string"),
    (0x1146c + 0x1c, "fn@0x1146C literal (if any)"),
]:
    if 0 <= lit_addr < len(data) - 4:
        v = struct.unpack_from("<I", data, lit_addr)[0]
        s = str_at(v)
        print(f"\n{label}: lit at {lit_addr:#x} = {v:#x}  '{s}'")
