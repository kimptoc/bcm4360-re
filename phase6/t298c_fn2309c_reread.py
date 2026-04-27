"""T298c: re-disasm fn@0x2309C carefully — T281's summary may have missed
where macintstatus matched bits get propagated into flag_struct[+0x5c].

wlc_dpc (fn@0x2312C) reads events from flag_struct[+0x5c], NOT macintstatus.
We need to find the bridge.
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


print("=== fn@0x2309C — full body careful re-disasm ===\n")
fn_start = 0x2309C
chunk = data[fn_start:fn_start + 200]
for ins in md.disasm(chunk, fn_start):
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        lit_addr, val = pc_rel
        s = str_at(val)
        if s:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}  → \"{s}\""
        else:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}"
    elif ins.mnemonic == "bl":
        annot = "  → call"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str:
        print("    [end of fn — pop pc seen]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [end of fn — bx lr]")
        break

print("\n=== ALSO trace fn@0x23374 (caller of fn@0x2309C) ===\n")
fn_start = 0x23374
chunk = data[fn_start:fn_start + 120]
for ins in md.disasm(chunk, fn_start):
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        lit_addr, val = pc_rel
        s = str_at(val)
        if s:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}  → \"{s}\""
        else:
            annot = f"  ; lit@{lit_addr:#x} = {val:#x}"
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{target:#x}"
        except Exception:
            pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str:
        print("    [end of fn]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [end of fn]")
        break
