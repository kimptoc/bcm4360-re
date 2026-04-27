"""T297-15 v2: dump fn around 0x682D8."""
import sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm directly from a known good offset (0x6820C — T289b said this is fn-start)
target_site = 0x682D8
fn_start_estimate = 0x6820C  # T289b's claim

print(f"Disasm fn@{fn_start_estimate:#x}, looking for site {target_site:#x}…\n")
for ins in md.disasm(data[fn_start_estimate:fn_start_estimate + 0x200], fn_start_estimate):
    annot = ""
    if "[" in ins.op_str and ", #" in ins.op_str:
        try:
            bracket = ins.op_str[ins.op_str.index("["):]
            inside = bracket.lstrip("[").rstrip("]")
            parts = [p.strip() for p in inside.split(",")]
            if len(parts) >= 2:
                base = parts[0]
                off_s = parts[1].lstrip("#").strip()
                off = int(off_s, 16) if off_s.startswith("0x") else int(off_s)
                KEY = {0x60, 0x64, 0x88, 0xAC, 0x82, 0x83, 0x84, 0x85, 0x86, 0x87, 0x89, 0x180, 0x10, 0x18}
                if off in KEY:
                    annot = f"   ***[{base}, +{off:#x}]***"
                else:
                    annot = f"   [{base}, +{off:#x}]"
        except Exception:
            pass
    elif ins.mnemonic == "bl":
        if "0x9990" in ins.op_str:
            annot = "   >>> CALL fn@0x9990 (class-validate → si_setcoreidx) <<<"
        elif "0x9968" in ins.op_str:
            annot = "   call fn@0x9968 (core-id lookup)"
        elif "0x9944" in ins.op_str or "0x9940" in ins.op_str:
            annot = "   call fn@0x994x (BIT_alloc)"
    here = "  <-- TARGET 0x682D8" if ins.address == target_site else ""
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}{here}")
    if ins.mnemonic in ("pop",) and "pc" in ins.op_str:
        print("    [end of fn]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [end of fn]")
        break
