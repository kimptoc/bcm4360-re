"""T281: decode the 9-thunk vector at 0x99AC and the class-dispatch
region at ~0x27EC that T274 identified.

Each thunk is a 32-bit function pointer; each target sets up a
class-specific flag bit allocation for hndrte_add_isr. WLC's class
index is 0xCC (per T274). Pciedngl's class is whatever the wlc-probe
uses vs pciedngl-probe uses.

Note: T274 noted the 9-thunk vector at 0x99AC..0x99C8 (= 9*4 bytes =
36 bytes = 9 dwords, range 0x99AC..0x99D0 exclusive = 36 bytes ✓).
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
    for k in range(80):
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


print("=== 9-thunk vector at 0x99AC ===")
thunks = []
for i in range(9):
    addr = 0x99AC + i * 4
    ptr = struct.unpack_from("<I", data, addr)[0]
    thumb = ptr & ~1
    print(f"  vec[{i}] @{addr:#x} = {ptr:#x}  (thumb target {thumb:#x})")
    thunks.append(thumb)

print("\n=== Disasm of each thunk target (first 24 insns) ===")
for i, t in enumerate(thunks):
    print(f"\n--- thunk[{i}] fn@{t:#x} ---")
    ins = list(md.disasm(data[t:t + 120], t, count=24))
    for ix in ins:
        annot = ""
        # Literal loads
        if ix.mnemonic.startswith("ldr") and "[pc" in ix.op_str:
            try:
                imm_str = ix.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((ix.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    s = str_at(v)
                    if s:
                        annot = f"  '{s}'"
                    else:
                        annot = f"  lit = {v:#x}"
            except Exception:
                pass
        # BL targets
        if ix.mnemonic in ("bl", "blx") and ix.op_str.startswith("#"):
            try:
                b = int(ix.op_str[1:], 16)
                annot = f"  ← fn@{b:#x}"
            except ValueError:
                pass
        # HW MMIO literals
        if "0x180" in ix.op_str:
            annot = annot or "  *** HW IO ***"
        print(f"  {ix.address:#7x}  {ix.mnemonic:6s}  {ix.op_str}{annot}")
