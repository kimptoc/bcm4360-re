"""T289: full disasm of hndrte_add_isr (fn@0x63C24).

Per T272 init_chain there are 3 callers (0x1F28 pcidongle_probe,
0x63CF0 internal recursion?, 0x67774 wlc_attach). Per T287c runtime
sched+0x254 = wrapper bases (class-keyed). The question: does
hndrte_add_isr ITSELF write to any HW register that could enable
the IRQ source for the bit it allocates?

If hndrte_add_isr only manipulates SW state (linked-list of callbacks
+ bit-pool), then the actual HW IRQ-enable must happen elsewhere —
maybe never, or only on a host-trigger.
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


def disasm_full(entry, label, max_bytes=2000):
    print(f"\n=== fn@{entry:#x} '{label}' (full body) ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    push_count = 0
    str_summary = []
    for i in ins_list:
        # Stop when we see a SECOND push (next function) after a return path
        if i.mnemonic in ("push", "push.w"):
            push_count += 1
            if push_count > 1:
                print(f"  --- next fn prologue at {i.address:#x}; stopping ---")
                break
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
                elif t == 0x9940:
                    annot += "  ← BIT_alloc (read wrap+0x100 low)"
                elif t == 0x9944:
                    annot += "  ← BIT_alloc (read wrap+0x100 mid)"
                elif t == 0x9948:
                    annot += "  ← reads sched+core_id slot"
                elif t == 0x9956:
                    annot += "  ← reads sched+0xcc class"
                elif t == 0x9968:
                    annot += "  ← core-id linear search"
                elif t == 0x9990:
                    annot += "  ← class-validate wrapper → 0x27EC (si_setcoreidx)"
                else:
                    annot += f"  ← fn@{t:#x}"
            except ValueError:
                pass
        if "0x18001" in i.op_str or "0x18002" in i.op_str or "0x18003" in i.op_str or "0x18010" in i.op_str:
            annot += "  [HW MMIO]"
        if i.mnemonic.startswith("str"):
            str_summary.append(f"  {i.address:#x}: {i.mnemonic} {i.op_str}{annot}")
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")

    print("\n--- ALL stores in this function ---")
    for s in str_summary:
        print(s)


disasm_full(0x63C24, "hndrte_add_isr", max_bytes=2400)
