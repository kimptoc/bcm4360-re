"""T269: disassemble hndrte_add_isr (0x63C24 — inferred from the
pcidongle_probe call site at 0x1F28 that passes pciedngl_isr thumb fn-ptr
0x1C99 as r3). This function wires a software ISR into the scheduler's
callback list and — we need to discover — may or may not program a HW
interrupt-mask register.

If hndrte_add_isr programs a HW mask bit, then the scaffold's host-side
MAILBOXMASK write could be overriding (or racing with) whatever value fw
has programmed. If hndrte_add_isr does NOT touch HW registers (just builds
the callback node in TCM), then the HW-enable is done elsewhere.
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


def dump_range(start, end, label, max_lines=300):
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


# 1. hndrte_add_isr body
end = find_fn_end(0x63C24, 0xC00)
dump_range(0x63C24, end, "hndrte_add_isr (0x63C24)")

# 2. The deadman/trap handler dumper at 0x63EE4 (prev fn before deadman_to ref)
end2 = find_fn_end(0x63EE4, 0x400)
dump_range(0x63EE4, end2, "deadman trap-dump handler (0x63EE4)")

# 3. idle-loop WFI thunks
print("\n=== 0x1C0C WFI thunk / 0x1C10 0x1C1C ===")
for start in (0x1C0C, 0x1C10, 0x1C1C, 0x1C1E):
    end = find_fn_end(start, 0x20)
    dump_range(start, end, f"fn@0x{start:X}", max_lines=10)
