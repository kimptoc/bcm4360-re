"""T269: find hndrte_add_isr callers / body and the fault-handler that prints
the deadman_to register dump. Understanding hndrte_add_isr tells us HOW a
software flag bit (0x8 for pciedngl_isr) gets mapped to a hardware interrupt
source — which is the central question for "which HW bit wakes the ISR".
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


def find_prev_fn(addr, max_back=0x400):
    for off in range(addr, max(0, addr - max_back), -2):
        w16 = int.from_bytes(blob[off:off + 2], "little")
        if w16 == 0xE92D:
            return off
        if (w16 & 0xFF00) == 0xB500 and (w16 & 0xFF) != 0:
            return off
    return None


def find_fn_end(start, max_scan=0x600):
    for off in range(start + 4, min(len(blob), start + max_scan), 2):
        w16 = int.from_bytes(blob[off:off + 2], "little")
        if w16 == 0xE92D:
            return off
        if (w16 & 0xFF00) == 0xB500 and (w16 & 0xFF) != 0:
            return off
    return start + max_scan


def scan_lit_pool(addr_val):
    """Find blob offsets where the 4-byte little-endian addr_val literal lives."""
    return find_lit_exact(addr_val)


def dump_range(start, end, label, max_lines=120):
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
                    extra = f"  ; lit@0x{lit:06X}=0x{v:08X}"
                    # annotate
                    if 0x40000 <= v < 0x6C000:
                        s_end = v
                        while s_end < len(blob) and blob[s_end] != 0 and 32 <= blob[s_end] < 127:
                            s_end += 1
                        if s_end > v + 2:
                            try:
                                extra += f' "{blob[v:s_end].decode("ascii")}"'
                            except Exception:
                                pass
            except Exception:
                pass
        print(f"  0x{ins.address:06X}: {ins.mnemonic:<10} {ins.op_str}{extra}")
        i += 1
        if i > max_lines:
            break


# Find "hndrte_add_isr failed" string and the function that uses it
ADD_ISR_MSG = b"pcidongle_probe:hndrte_add_isr failed"
h = blob.find(ADD_ISR_MSG)
print(f"pcidongle_probe err string @ 0x{h:06X}")
# find what references it
refs = find_lit_exact(h)
print(f"  literal refs to 0x{h:06X}: {refs}")
for r in refs[:5]:
    # back up to find function prologue
    fn = find_prev_fn(r, max_back=0x800)
    print(f"    ref@0x{r:06X}  containing_fn_prologue=0x{fn:06X}")

# Find where the node[0] fn-ptr value 0x1C99 (thumb) appears — this is the
# hndrte_add_isr call site literal
print("\n=== References to 0x1C99 (pciedngl_isr thumb fn-ptr) ===")
for h in find_lit_exact(0x1C99):
    fn = find_prev_fn(h)
    print(f"  lit@0x{h:06X}  prev-fn-prologue=0x{fn if fn else -1:06X}")

# Find where "pciedngldev" string (arg of ISR) is referenced as a literal
print("\n=== References to 0x58CC4 (pciedev struct 'pciedngldev') ===")
for h in find_lit_exact(0x58CC4):
    fn = find_prev_fn(h)
    print(f"  lit@0x{h:06X}  prev-fn-prologue=0x{fn if fn else -1:06X}")

# Where is "deadman_to" referenced?
print("\n=== References to 'deadman_to' string (0x40659) ===")
for h in find_lit_exact(0x40659):
    fn = find_prev_fn(h, max_back=0x1000)
    print(f"  lit@0x{h:06X}  prev-fn-prologue=0x{fn if fn else -1:06X}")

# Where is "ramstbydis" (0x4067A)? Looks like a standby-disable word
print("\n=== References to 'ramstbydis' string (0x4067A) ===")
for h in find_lit_exact(0x4067A):
    fn = find_prev_fn(h, max_back=0x400)
    print(f"  lit@0x{h:06X}  prev-fn-prologue=0x{fn if fn else -1:06X}")

# Disassemble the function that owns the pcidongle_probe error reference
print("\n=== Disasm of function that prints hndrte_add_isr failed ===")
if refs:
    # Take the first ref; find the function containing it
    ref = refs[0]
    # find a reasonable window: previous push prologue back up, then to end
    fn_start = None
    # scan back looking for push.w or short push
    for off in range(ref, max(0, ref - 0x200), -2):
        w16 = int.from_bytes(blob[off:off + 2], "little")
        if w16 == 0xE92D:
            fn_start = off
            break
        if (w16 & 0xFF00) == 0xB500 and (w16 & 0xFF) != 0:
            fn_start = off
            break
    if fn_start:
        end = find_fn_end(fn_start)
        print(f"Function @ 0x{fn_start:06X}..0x{end:06X}")
        dump_range(fn_start, end, "pcidongle_probe fragment", max_lines=200)

# Separately: disassemble 0x115C (scheduler body) to capture the
# event-mask test pattern (r5 = bl 0x9936; tst r5, flag).
print("\n=== Scheduler @ 0x115C..0x11E0 (event-dispatch loop) ===")
dump_range(0x115C, 0x11F0, "scheduler-0x115C", max_lines=60)
