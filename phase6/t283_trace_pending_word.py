"""T283: resolve absolute address of fn@0x2309c's pending-events word.

Chain (from T281):
  ctx → [ctx+0x10] = flag_struct    (hndrte_add_isr 0x63C24 allocates)
  flag_struct → [flag_struct+0x88] = sub_struct  (per-class init thunk)
  sub_struct → [sub_struct+0x168] = pending-events word

Advisor scope: find where each pointer is assigned, resolve any
literal-pool loads to absolute addresses. Look for:
  - 0x1800xxxx (chipcommon backplane MMIO)
  - 0x0000XXXX TCM offsets
  - BAR0-relative or _pcie2_regs literals

Outputs:
  - Disasm of fn@0x63C24 (hndrte_add_isr)
  - Disasm of fn@0x27EC (pciedngl class-init thunk — T274 identified)
  - Any literal loads flagged
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


def flag_literal(v):
    """Classify what a 32-bit literal might be."""
    if 0x18000000 <= v < 0x18010000:
        return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000:
        return "PCIe2 core MMIO"
    if 0x18001000 <= v < 0x18002000:
        return "ChipCommon core (si_info base?)"
    if 0x18002000 <= v < 0x18100000:
        return "backplane MMIO (other core)"
    # Blob-range code pointers
    if 0 < v < len(data):
        s = str_at(v)
        if s:
            return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    # TCM-range (ramsize 0xa0000)
    if 0 < v < 0xA0000:
        return "TCM offset"
    # Small values
    if v < 0x10000:
        return f"small val {v:#x}"
    # Very large
    if v > 0xF0000000:
        return "high memory / stack?"
    return "unclassified"


def disasm(entry, label, max_bytes=2000, stop_at_next_push=True):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    literals = []
    ret_seen = False
    for i in ins_list:
        annot = ""
        # PC-relative literal loads
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    kind = flag_literal(v)
                    annot = f"  lit@{lit_addr:#x}={v:#x}  [{kind}]"
                    literals.append((i.address, lit_addr, v, kind))
            except Exception:
                pass
        # BL target classification
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot = annot + "  ← printf"
                elif t == 0x11e8: annot = annot + "  ← printf/assert"
                elif t == 0x14948: annot = annot + "  ← trace"
                elif t == 0x63C24: annot = annot + "  ← hndrte_add_isr"
                else: annot = annot + f"  ← fn@{t:#x}"
            except ValueError:
                pass
        # Stores that include an offset — interesting for pointer assignments
        if i.mnemonic in ("str", "str.w", "strh", "strb") and "#0x" in i.op_str:
            off_part = i.op_str.split("#")[-1].rstrip("]").strip()
            # Flag stores at offsets matching our struct chain
            for off_hex, role in [("0x10", "flag_struct@+0x10?"),
                                  ("0x88", "sub_struct@+0x88?"),
                                  ("0x168", "pending-events@+0x168?")]:
                if off_hex in off_part:
                    annot = annot + f"  *** STORE {role} ***"

        # HW IO-mapped literal pattern in operand
        if "0x18001" in i.op_str or "0x18002" in i.op_str:
            annot = annot + "  [HW chipc/pcie]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")

        if i.mnemonic == "bx" and i.op_str == "lr":
            ret_seen = True
        if stop_at_next_push and ret_seen and i.mnemonic == "push":
            print("  --- next fn prologue; stopping ---")
            break
    return literals


# T283 targets (per advisor):

# Primary 1: hndrte_add_isr at 0x63C24 — look for flag_struct+0x88 assignment
hndrte_literals = disasm(0x63C24, "hndrte_add_isr (T269 identified)", max_bytes=4000)

# Primary 2: per-class thunk target for pciedngl_isr at 0x27EC
# (T274 said thunk[0] = 0x27EC is the class-0 init for pciedngl)
thunk_literals = disasm(0x27EC, "class-0 init thunk (pciedngl)", max_bytes=1000)

print("\n=== Literals summary ===")
print("\nhndrte_add_isr (0x63C24) literals:")
for (pc, lit_addr, v, kind) in hndrte_literals:
    print(f"  pc={pc:#x}: lit@{lit_addr:#x}={v:#x}  [{kind}]")
print("\nclass-0 init thunk (0x27EC) literals:")
for (pc, lit_addr, v, kind) in thunk_literals:
    print(f"  pc={pc:#x}: lit@{lit_addr:#x}={v:#x}  [{kind}]")
