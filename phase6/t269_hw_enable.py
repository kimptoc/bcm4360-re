"""T269: dig into
- 0x99AC (called at end of hndrte_add_isr — likely HW-unmask commit)
- 0x9940 / 0x9944 / 0x9956 / 0x9990 (scheduler-bit-index helpers used to
  compute the 1<<n flag for the new node)
- 0x1A8C (the deadman-timer callback, whose ptr sits at 0x63F72 ref'd from
  the init code around deadman_to string)
- The exception / trap dumper that prints 'r11 %x, r12 %x' (0x40600) — this
  is the saved-state dumper when a fault occurs.
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


def find_lit_exact(val):
    p = val.to_bytes(4, "little")
    out = []
    pos = 0
    while True:
        h = blob.find(p, pos)
        if h < 0:
            break
        out.append(h)
        pos = h + 1
    return out


def find_fn_end(start, max_scan=0x800):
    for off in range(start + 4, min(len(blob), start + max_scan), 2):
        w16 = int.from_bytes(blob[off:off + 2], "little")
        if w16 == 0xE92D:
            return off
        if (w16 & 0xFF00) == 0xB500 and (w16 & 0xFF) != 0:
            return off
    return start + max_scan


def ascii_str(off, maxlen=80):
    if not (0 <= off < len(blob)):
        return None
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


def dump_range(start, end, label, max_lines=100):
    print(f"\n=== {label} 0x{start:X}..0x{end:X} ===")
    i = 0
    for ins in md.disasm(blob[start:end], start):
        extra = ""
        if "pc," in ins.op_str and ins.mnemonic.startswith("ldr"):
            try:
                imm_str = ins.op_str.split("#")[-1].strip().rstrip("]")
                imm = int(imm_str, 16) if "0x" in imm_str else int(imm_str)
                lit = ((ins.address + 4) & ~3) + imm
                if lit + 4 <= len(blob):
                    v = u32(lit)
                    s = ascii_str(v)
                    note = f'="{s}"' if s and len(s) > 2 else ""
                    extra = f"  ; lit@0x{lit:06X}=0x{v:08X}{note}"
            except Exception:
                pass
        print(f"  0x{ins.address:06X}: {ins.mnemonic:<10} {ins.op_str}{extra}")
        i += 1
        if i > max_lines:
            break


for start, label in [
    (0x99AC, "hndrte_add_isr tail call (0x99AC, HW unmask?)"),
    (0x9940, "sched bit index helper (0x9940)"),
    (0x9944, "sched bit index helper (0x9944)"),
    (0x9956, "sched helper (0x9956, called near entry of add_isr)"),
    (0x9990, "sched helper (0x9990, name/id lookup)"),
    (0x9A32, "sched helper (0x9A32, called inside deadman init)"),
    (0x1A8C, "deadman callback (fn-ptr 0x1A8D)"),
    (0x1BA4, "deadman 0x1BA5 callback helper"),
    (0x1298, "small-alloc wrapper (0x1298)"),
]:
    end = find_fn_end(start, 0x200)
    dump_range(start, end, label, max_lines=50)

# Fault/trap dump handler — find where 'r11 %x, r12 %x' is referenced.
print("\n=== refs to 'r11 %x, r12 %x' (0x40600) ===")
for h in find_lit_exact(0x40600):
    print(f"  lit@0x{h:06X}")

# Search for trap/exception vector writes — the exception vectors start near
# address 0 typically (reset, undef, swi, prefetch_abt, data_abt, irq, fiq).
# On CortexR-like Broadcom fw, the vector may be at 0x0 or remapped.
# Just print the first 0x80 bytes of the blob for vector table inspection.
print("\n=== Blob[0..0x80] vector table region ===")
for off in range(0, 0x80, 4):
    v = u32(off)
    print(f"  0x{off:02X}: 0x{v:08X}")
