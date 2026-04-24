"""T283: disasm class-0 init thunk at 0x27EC.

Per T274 this is the class-0 (pciedngl) per-class unmask handler
called by hndrte_add_isr tail via 0x99ac B.W #0x27EC.

Also disasm fn@0x9940 (BIT_alloc — allocates the flag bit) and
fn@0x9956 (unknown early helper) to find the scheduler state's
bit-pool and any HW register refs.

Goal: resolve literal loads that might point at the pending-events
word the scheduler reads. Look for 0x1800xxxx (MMIO) or specific
BAR0 offsets.
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
    if 0x18100000 <= v < 0x18110000: return "PCIe2 core MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO (other core)"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000: return "TCM offset"
    if v < 0x10000: return f"small val {v:#x}"
    return "unclassified"


def disasm(entry, label, max_bytes=800):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    ret_seen = False
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
                if t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                elif t == 0x14948: annot += "  ← trace"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        if "0x18001" in i.op_str or "0x18002" in i.op_str or "0x18010" in i.op_str:
            annot += "  [HW MMIO]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if i.mnemonic == "bx" and i.op_str == "lr": ret_seen = True
        if ret_seen and i.mnemonic == "push":
            print("  --- next fn prologue; stopping ---")
            break


# class-0 thunk target (pciedngl per T274)
disasm(0x27EC, "class-0 init thunk (pciedngl) — per T274", max_bytes=400)

# BIT_alloc — called from hndrte_add_isr at 0x63c72
disasm(0x9940, "fn@0x9940 — BIT_alloc (bit-index allocator)", max_bytes=200)

# fn@0x9956 — called early in add_isr with scheduler ctx
disasm(0x9956, "fn@0x9956 — scheduler-ctx helper (ret used as r7)", max_bytes=300)

# fn@0x9944 — special variant for class 0x812
disasm(0x9944, "fn@0x9944 — class 0x812 bit helper", max_bytes=200)

# fn@0x9990 — class-validate wrapper
disasm(0x9990, "fn@0x9990 — class-validate wrapper (tail-calls 0x27EC)", max_bytes=100)
