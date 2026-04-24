"""T286: deep wlc-probe trace — find r7 origin and the pending-events
absolute address.

Chain to resolve (from T283):
  r7 at 0x6776e → callback_ctx → fn@0x1146C.r0
  callback_ctx + 0x18 → dispatch_ctx_ptr
  dispatch_ctx_ptr + 8 → ctx_2 (= fn@0x2309c.r0)
  ctx_2 + 0x10 → flag_struct
  flag_struct + 0x88 → sub_struct
  sub_struct + 0x168 → pending-events (target)

Start: fn@0x67614 (wlc-probe top). Find:
  - r7's first set (prologue)
  - How r7 is populated through early code
  - [r7+0x18] — where it gets assigned
  - subsequent chain layer populations
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(100):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


def flag(v):
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000: return "PCIe2 MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000: return "TCM offset"
    if v < 0x10000: return f"small val {v:#x}"
    return "unclassified"


def disasm_range(start, end, label, watch_reg=None):
    """Disasm and annotate interesting ops. watch_reg: highlight any
    mov/ldr/str involving that reg name (e.g. 'r7')."""
    print(f"\n=== {label} [0x{start:x}..0x{end:x}] ===")
    window = data[start:end]
    ins_list = list(md.disasm(window, start, count=0))
    for i in ins_list:
        annot = ""
        # Literal loads
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit@{lit_addr:#x}={v:#x}  [{flag(v)}]"
            except Exception: pass
        # BL target classification
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                elif t == 0x14948: annot += "  ← trace"
                elif t == 0x1298: annot += "  ← heap-alloc"
                elif t == 0x63C24: annot += "  ← hndrte_add_isr *** HIT ***"
                elif t == 0x68A68: annot += "  ← fn@0x68A68 (wlc attach top — called from wl_probe 0x67700)"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        # Highlight any instruction that involves watch_reg
        if watch_reg and watch_reg in i.op_str.split(",")[0] if "," in i.op_str else False:
            annot = "  *** " + watch_reg + " write? ***" + annot
        if watch_reg and watch_reg == i.op_str.split(",")[0].strip() and i.mnemonic not in ("cmp", "tst"):
            annot = "  *** dest=" + watch_reg + " ***" + annot
        # HW MMIO literals in operands
        if "0x18001" in i.op_str or "0x18002" in i.op_str:
            annot += "  [HW MMIO]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")


# fn@0x67614 — wlc-probe TOP. T273 identified it. Body up to hndrte_add_isr
# call at 0x67774 is 0x160 bytes. Let's dump the full probe body.
disasm_range(0x67614, 0x67778, "fn@0x67614 — wlc-probe top (through hndrte_add_isr call)")

# Also disasm fn@0x68A68 since wl_probe calls it at entry (0x67700)
# and it may allocate the struct that r7 ends up pointing at.
# Start with first 200 bytes.
disasm_range(0x68A68, 0x68B30, "fn@0x68A68 — called from wl_probe entry (likely wlc alloc)")
