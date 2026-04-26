"""T289: disasm all 9 per-class thunk targets at 0x99AC..0x99CC.

Per T274 the vector at 0x99AC..0x99CC dispatches by class index:
  class 0 → 0x27EC, class 1 → 0x2B8C, class 2 → 0x2BDC,
  class 3 → 0x28E2, class 4 → 0x28AE, class 5 → 0x2904,
  class 6 → 0x29AC, class 7 → 0x2A4C, class >=8 → no-op (return 0)

Goal: identify which thunks (if any) write to a hardware register that
could control fw's wake gate. Discriminate KEY_FINDINGS row 118
hypotheses:
  (a) thunk writes to a different register (not MBM at BAR0+0x4C)
  (b) thunk wasn't invoked — should see "fn never reached" pattern
  (c) thunk effect gated on condition not satisfied — should see early
      conditional return
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
    for k in range(100):
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


def flag(v):
    if 0x18000000 <= v < 0x18001000:
        return "CHIPCOMMON REG base+offset"
    if 0x18001000 <= v < 0x18010000:
        return "core[N] REG base"
    if 0x18100000 <= v < 0x18101000:
        return "CHIPCOMMON WRAPPER"
    if 0x18101000 <= v < 0x18110000:
        return "core[N] WRAPPER"
    if 0 < v < len(data):
        s = str_at(v)
        if s:
            return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000:
        return "TCM offset"
    if v < 0x10000:
        return f"small val {v:#x}"
    return "unclassified"


def disasm(entry, label, max_bytes=400):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    ret_seen = False
    saw_str_after_ret = False
    write_targets = []
    read_targets = []
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
            except Exception:
                pass
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30:
                    annot += "  ← printf"
                elif t == 0x11e8:
                    annot += "  ← printf/assert"
                elif t == 0x14948:
                    annot += "  ← trace"
                else:
                    annot += f"  ← fn@{t:#x}"
            except ValueError:
                pass
        # Track stores to potentially HW addresses or interesting offsets
        if i.mnemonic.startswith("str"):
            write_targets.append(f"  {i.address:#x}: {i.mnemonic} {i.op_str}")
        if i.mnemonic.startswith("ldr") and ("[r" in i.op_str):
            read_targets.append(f"  {i.address:#x}: {i.mnemonic} {i.op_str}")
        if "0x18001" in i.op_str or "0x18002" in i.op_str or "0x18003" in i.op_str or "0x18010" in i.op_str:
            annot += "  [HW MMIO]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if i.mnemonic == "bx" and i.op_str == "lr":
            ret_seen = True
        if ret_seen and i.mnemonic == "push":
            print("  --- next fn prologue; stopping ---")
            break
    print(f"  [summary] writes: {len(write_targets)}  reads: {len(read_targets)}")


THUNKS = [
    (0x27EC, "class 0 (pciedngl per T274)"),
    (0x2B8C, "class 1"),
    (0x2BDC, "class 2"),
    (0x28E2, "class 3"),
    (0x28AE, "class 4"),
    (0x2904, "class 5"),
    (0x29AC, "class 6"),
    (0x2A4C, "class 7"),
]

for addr, label in THUNKS:
    disasm(addr, label, max_bytes=600)
