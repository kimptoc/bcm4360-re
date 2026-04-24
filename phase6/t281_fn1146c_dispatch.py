"""T281 deliverable (1)+(3): trace fn@0x1146C's dispatch chain.

fn@0x1146C is registered as a scheduler callback inside wl_probe via
hndrte_add_isr at 0x67774 (T273 finding). Per T273: "fn@0x1146C is 10
insns, NO HW register reads — purely dispatches to `bl #0x23374`
(helper sets byte flag) → conditional `bl #0x113b4` (action)."

This script:
- Disassembles fn@0x1146C body
- Disassembles fn@0x23374 body (and its own BL targets)
- Disassembles fn@0x113b4 body (and its own BL targets)
- Flags any string refs (logging hints) or HW register accesses

Advisor note: if neither 0x23374 nor 0x113b4 log anything, T279
(mailbox-poke-with-console) becomes a blind poke.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(FW, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_next_fn(start, limit=512):
    """Scan forward for typical fn-prologue markers. Returns offset or None."""
    for off in range(start + 2, min(start + limit, len(data) - 2), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        # Thumb push {...lr} or wide push
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
        # Or a BX LR followed by alignment may appear earlier; detect via
        # the NEXT hw being a push too
        if hw == 0x4770:  # bx lr
            nx = struct.unpack_from("<H", data, off + 2)[0]
            if (nx & 0xFE00) == 0xB400 or nx == 0xE92D:
                return off + 2
    return None


def str_at(addr):
    """Return printable ASCII string at addr if one exists, else None."""
    if not (0 <= addr < len(data) - 1):
        return None
    s = bytearray()
    for k in range(120):
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


def classify_bl_target(t):
    """Known helper bl targets inherited from T274 annotations."""
    known = {
        0xA30: "printf",
        0x11e8: "printf/assert",
        0x14948: "trace",
        0x1298: "heap-alloc",
        0x1ADC: "DELAY helper",
        0x63C24: "hndrte_add_isr",
        0x1C98: "pciedngl_isr",
    }
    return known.get(t)


def disasm_fn(entry, label, limit=512):
    fn_end = find_next_fn(entry, limit)
    if fn_end is None:
        fn_end = entry + limit
    size = fn_end - entry
    print(f"\n=== fn@{entry:#x} '{label}' ({size} bytes) ===")
    ins_list = list(md.disasm(data[entry:fn_end], entry, count=0))
    bl_targets = set()
    hw_hits = []
    str_hits = []
    for i in ins_list:
        annot = ""
        # BL classification
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                bl_targets.add(t)
                c = classify_bl_target(t)
                if c:
                    annot = f"  ← {c}"
                else:
                    annot = f"  ← fn@{t:#x}"
            except ValueError:
                pass
        # PC-rel ldr → literal / string
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    s = str_at(v)
                    if s is not None:
                        annot = f"  '{s}'"
                        str_hits.append((i.address, v, s))
                    elif 0 < v < 0x10000:
                        annot = f"  lit = {v:#x}  (small val / flag?)"
                    elif 0 < v < len(data):
                        annot = f"  lit = {v:#x}  (code ptr? fn@{v & ~1:#x})"
                    else:
                        annot = f"  lit = {v:#x}  (HW addr? MMIO base?)"
                        hw_hits.append((i.address, v))
            except Exception:
                pass
        # Store/load to register tagged addresses (HW access patterns)
        if i.mnemonic in ("str", "ldr", "strb", "ldrb", "strh", "ldrh"):
            if "0x18000" in i.op_str or "0x18001" in i.op_str:
                annot = annot or "  HW IO-mapped reg?"

        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
    return bl_targets, str_hits, hw_hits


# Deliverable (1)+(3) chain: fn@0x1146C → fn@0x23374 → fn@0x113b4
for entry, label, limit in [
    (0x1146C, "fn@1146C — wlc scheduler-callback dispatcher", 80),
    (0x23374, "fn@23374 — flag-byte helper (from T273 note)", 200),
    (0x113b4, "fn@113b4 — wlc dispatch action", 400),
]:
    disasm_fn(entry, label, limit)

print("\n=== Summary ===")
print("See above for fn body disasms. Look for:")
print("  - 'printf' / 'printf/assert' BL targets → fw will log if this fn fires")
print("  - HW IO-mapped reg accesses (0x1800xxxx literal)")
print("  - String literals close to the dispatch branch point")
