"""T298b: trace fn@0x2312c — called by fn@0x113B4 with r0=dispatch_ctx, r1=1, r2=&sp[4].

This is the actual event-processing function in the wake-then-act chain.
fn@0x113B4 stores its return value to r5 (used as a switch later).

Goal: full body disasm + identify what bits this fn processes / dispatches /
clears. If this dispatches D11 INTSTATUS bits to specific event handlers,
we'll see the bit-mapping for what triggers what.
"""
import struct, sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
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


def resolve_pc_lit(ins):
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str:
        return None
    try:
        imm_str = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
        lit_addr = ((ins.address + 4) & ~3) + imm
        if 0 <= lit_addr <= len(data) - 4:
            return lit_addr, struct.unpack_from("<I", data, lit_addr)[0]
    except Exception:
        return None
    return None


# Disasm fn@0x2312c — guess length 256 bytes (siblings fn@0x233e8 etc nearby)
print("=== fn@0x2312C (event-processing helper) — full body ===\n")
fn_start = 0x2312C
chunk = data[fn_start:fn_start + 320]
for ins in md.disasm(chunk, fn_start):
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        lit_addr, val = pc_rel
        s = str_at(val)
        if s:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}  → \"{s}\""
        elif val & 1 and 0x1000 < val < len(data):
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}  → Thumb fn @{val-1:#x}"
        else:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}"
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x11E8:
                annot = "  → printf/assert"
            elif target == 0xA30:
                annot = "  → printf-args"
        except Exception:
            pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic in ("pop",) and "pc" in ins.op_str:
        print("    [end of fn]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [end of fn]")
        break
