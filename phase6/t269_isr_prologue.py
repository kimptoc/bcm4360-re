"""T269 step 1+2: disasm pciedngl_isr (node[0].fn = 0x1C98) and 0x9936.

node[0] values captured at runtime via T256 TCM BAR2 probe:
  next = 0x96F48, fn = 0x1C99 (Thumb → entry 0x1C98), arg = 0x58CC4, flag = 0x08

String evidence confirms 0x1C98 = pciedngl_isr:
  blob[0x4069D] = "pciedngl_isr called\n"
  blob[0x406B2] = "%s: invalid ISR status: 0x%08x"
  blob[0x40685] = "pciedngl_isr"
  blob[0x406E5] = "pciedev_msg.c"
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs

BLOB = "/home/kimptoc/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    blob = f.read()

md = Cs()


def u32(off):
    return int.from_bytes(blob[off:off + 4], "little")


def find_fn_end(start, max_scan=0x600):
    """End of function = start of next function prologue (push stub)."""
    for off in range(start + 4, min(len(blob), start + max_scan), 2):
        w16 = int.from_bytes(blob[off:off + 2], "little")
        if w16 == 0xE92D:
            return off
        if (w16 & 0xFF00) == 0xB500 and (w16 & 0xFF) != 0:
            return off
    return start + max_scan


def ascii_str(off, maxlen=64):
    s = []
    for i in range(maxlen):
        b = blob[off + i]
        if b == 0:
            break
        if 32 <= b < 127:
            s.append(chr(b))
        else:
            return None
    return "".join(s) if s else None


def is_reg_base(v):
    """Is v a plausible SoC MMIO base?"""
    bases = [
        (0x18000000, 0x19000000, "backplane"),
        (0x18000000, 0x18100000, "SB core window"),
    ]
    for lo, hi, desc in bases:
        if lo <= v < hi:
            return desc
    return None


def dump_fn(addr, label, count=100, show_literals=True):
    end = find_fn_end(addr)
    print(f"=== {label} @ 0x{addr:X} ..0x{end:X} ({end - addr} bytes, ~{(end-addr)//2} halfwords) ===")
    n = 0
    for ins in md.disasm(blob[addr:end], addr):
        extra = ""
        if show_literals and "pc," in ins.op_str:
            try:
                imm_str = ins.op_str.split("#")[-1].strip().rstrip("]")
                imm = int(imm_str, 16) if "0x" in imm_str else int(imm_str)
                lit = ((ins.address + 4) & ~3) + imm
                if lit + 4 <= len(blob):
                    val = u32(lit)
                    note = ""
                    s = ascii_str(val) if 0 <= val < len(blob) else None
                    if s:
                        note = f' str="{s}"'
                    elif (rb := is_reg_base(val)):
                        note = f" ({rb})"
                    elif 0x80000 <= val < 0xA0000:
                        note = " (TCM BSS/heap)"
                    elif 0x40000 <= val < 0x70000:
                        note = " (blob data)"
                    elif val < 0x6C000:
                        ns = ascii_str(val)
                        if ns:
                            note = f' str="{ns}"'
                    extra = f"  ; lit@0x{lit:06X}=0x{val:08X}{note}"
            except Exception:
                pass
        print(f"  0x{ins.address:06X}: {ins.mnemonic:<10} {ins.op_str}{extra}")
        n += 1
        if n >= count:
            break
    return end


print("=" * 72)
dump_fn(0x1C98, "pciedngl_isr", count=200)
print()
print("=" * 72)
dump_fn(0x9936, "scheduler-event-mask-source", count=40)
print()
print("=" * 72)
print("Node[0].arg = 0x58CC4 dereferenced:")
print(f"  u32@0x58CC4 = 0x{u32(0x58CC4):08X}")
print(f"  ASCII: {ascii_str(0x58CC4)!r}")
print(f"  Hex bytes: {blob[0x58CC4:0x58CC4+64].hex(' ', 4)}")
