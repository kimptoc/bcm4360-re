"""T283: disasm fn@0x672e4 — scheduler ctx allocator (return value
is stored at 0x6296c by init code at 0x63dfe..0x63e00).

Goal: find what this function allocates and whether any offset in
the returned struct gets a literal address (MMIO or TCM) that
corresponds to the pending-events word chain.
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
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO (si_info base region)"
    if 0x18100000 <= v < 0x18110000: return "PCIe2 core MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO (other core)"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000: return "TCM offset"
    if v < 0x10000: return f"small val {v:#x}"
    return "unclassified"


def disasm(entry, label, max_bytes=1500):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    ret_seen = False
    saw_any_ret = False
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
                elif t == 0x1298: annot += "  ← heap-alloc"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        # Flag stores at offsets we care about
        for off_hex, role in [("0x10", "+0x10"),
                              ("0x88", "+0x88"),
                              ("0x168", "+0x168"),
                              ("0x254", "+0x254"),
                              ("0x258", "+0x258"),
                              ("0x8c", "+0x8c")]:
            if i.mnemonic in ("str", "str.w", "strh", "strb") and \
               ("#" + off_hex + "]" in i.op_str or "#" + off_hex + "," in i.op_str):
                annot += f"  *** STORE {role} ***"
        if "0x18001" in i.op_str or "0x18002" in i.op_str:
            annot += "  [HW MMIO]"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if i.mnemonic == "bx" and i.op_str == "lr":
            ret_seen = True
        if ret_seen and i.mnemonic == "push":
            print("  --- next fn; stopping ---")
            break


disasm(0x672e4, "fn@0x672e4 — scheduler ctx allocator", max_bytes=1500)
