"""T283: trace wlc's hndrte_add_isr call at 0x67774 (per T273). Find
what the 8th arg (callback ctx) was. That becomes fn@0x1146C's r0.

Also check the 8th arg to pciedngl_isr's registration (different site,
not the wlc one) to compare patterns.

Hndrte_add_isr reads the 8th arg from sp[0x20] of the caller. We need
to see caller's stack setup: find str r?, [sp, #0x20] just before the BL.
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
    if 0x18002000 <= v < 0x18100000: return "backplane core MMIO"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000: return "TCM offset"
    if v < 0x10000: return f"small val {v:#x}"
    return "unclassified"


def disasm_window(start, nbytes, label):
    print(f"\n=== {label} @{start:#x}..{start + nbytes:#x} ===")
    window = data[start:start + nbytes]
    ins_list = list(md.disasm(window, start, count=0))
    for i in ins_list:
        annot = ""
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit@{lit_addr:#x}={v:#x}  [{flag(v)}]"
            except Exception: pass
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0x63C24: annot += "  ← hndrte_add_isr *** HIT ***"
                elif t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        if "sp, #0x20" in i.op_str:
            annot += "  <- stack arg 8 (callback_ctx in hndrte_add_isr)"
        if "0x18001" in i.op_str or "0x18002" in i.op_str:
            annot += "  [HW MMIO]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")


# Window around 0x67774 — wlc's hndrte_add_isr call per T273
disasm_window(0x67740, 80, "wlc-probe: context around hndrte_add_isr call at 0x67774")

# Also look at earlier parts of fn@0x67614 (wlc-probe top) for arg setup
disasm_window(0x67700, 120, "wlc-probe: earlier arg setup")
