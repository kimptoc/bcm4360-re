"""T298d: dump REST of fn@0x2312C (wlc_dpc) — find ALL `tst.w r5, #imm` patterns
to enumerate the full event-bit dispatch table.

Need to know: does wlc_dpc handle bit 14 (0x4000 = MI_GP1)? If yes, host-write
of MI_GP1 is productive. If not, MI_GP1 alone won't advance fw via this path.
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


# Disasm fn@0x2312c body, length 800 bytes (it's a big function with many dispatch bits)
print("=== fn@0x2312C (wlc_dpc) — full body, capturing all `tst r5, #imm` dispatch ===\n")
fn_start = 0x2312C
chunk = data[fn_start:fn_start + 0x600]
TST_DISPATCH = []
for ins in md.disasm(chunk, fn_start):
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        lit_addr, val = pc_rel
        s = str_at(val)
        if s:
            annot = f"  ; \"{s}\""
        else:
            annot = f"  ; lit={val:#x}"
    elif ins.mnemonic in ("tst", "tst.w") and "r5," in ins.op_str:
        # Capture event-bit dispatch
        try:
            mask_str = ins.op_str.split("#")[-1].strip()
            mask = int(mask_str, 16) if mask_str.startswith("0x") else int(mask_str)
            bit = mask.bit_length() - 1 if mask & (mask - 1) == 0 else "multi"
            annot = f"  *** dispatch test: bit {bit} (mask {mask:#x}) ***"
            TST_DISPATCH.append((ins.address, mask, bit))
        except Exception:
            pass
    elif ins.mnemonic in ("ands", "and.w") and "r5," in ins.op_str:
        try:
            mask_str = ins.op_str.split("#")[-1].strip()
            mask = int(mask_str, 16) if mask_str.startswith("0x") else int(mask_str)
            bit = mask.bit_length() - 1 if mask & (mask - 1) == 0 else "multi"
            annot = f"  *** ands dispatch: bit {bit} (mask {mask:#x}) ***"
            TST_DISPATCH.append((ins.address, mask, bit))
        except Exception:
            pass
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{target:#x}"
        except Exception:
            pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str and ins.address > fn_start + 0x100:
        print("    [end of fn]")
        break

print("\n=== Event bits dispatched by wlc_dpc ===")
for addr, mask, bit in TST_DISPATCH:
    print(f"  {addr:#7x}: mask {mask:#x} = bit {bit}")
print()
ALL_MASKS = set(m for _, m, _ in TST_DISPATCH)
print(f"Total unique masks: {len(ALL_MASKS)}")
print(f"MI_GP1 (0x4000 = bit 14) in dispatch table? {'YES' if 0x4000 in ALL_MASKS else 'NO'}")
print(f"MI_TO  (0x80000000 = bit 31) in dispatch table? {'YES' if 0x80000000 in ALL_MASKS else 'NO'}")
print(f"MI_GP0 (0x2000 = bit 13) in dispatch table? {'YES' if 0x2000 in ALL_MASKS else 'NO'}")
