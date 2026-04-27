"""T298a: trace fn@0x113B4 — the ACTION fn called when flag_struct check
fires (per T281).

Per T281: 184 bytes, contains printf/assert. Called by fn@0x1146C with
r0 = wlc_pub (= wlc_callback_ctx[+0x18]) AFTER fn@0x23374 returns truthy
AND local byte at sp[7] is set (a "should-fire" gate).

Goal: full body disasm + identify (i) what r0 args / fields it dereferences,
(ii) what helpers it calls (bl targets), (iii) what register WRITES it makes,
(iv) any string literals or printf format args.

If the body shows actual fw advancement (state transitions, mailbox writes,
etc.), then triggering this dispatcher via host-write of MI_GP1 would be
productive. If it just logs/assert/no-ops, it's not the right wake mechanism.
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
    """Return (lit_addr, value) if PC-rel ldr, else None."""
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


# T281 said fn@0x113b4 is 184 bytes. Disasm 240 bytes to be safe.
print("=== fn@0x113B4 (ACTION dispatcher) — full body ===\n")
fn_start = 0x113B4
chunk = data[fn_start:fn_start + 240]
out = list(md.disasm(chunk, fn_start))
last_lit = None
last_lit_addr = None
for ins in out:
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        last_lit_addr, last_lit_val = pc_rel
        s = str_at(last_lit_val)
        if s:
            annot = f"  ; lit@{last_lit_addr:#x} = {last_lit_val:#x}  → string \"{s}\""
        elif last_lit_val & 1 and 0x1000 < last_lit_val < len(data):
            annot = f"  ; lit@{last_lit_addr:#x} = {last_lit_val:#x}  → Thumb fn @{last_lit_val-1:#x}"
        else:
            annot = f"  ; lit@{last_lit_addr:#x} = {last_lit_val:#x}"
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x11E8:
                annot = "  → printf/assert (fn@0x11E8)"
            elif target == 0xA30:
                annot = "  → printf-with-args (fn@0xA30)"
            elif target == 0x14948:
                annot = "  → some helper @0x14948"
            elif target in (0x91C, 0x1ADC):
                annot = "  → memset/memcpy"
        except Exception:
            pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic in ("pop",) and "pc" in ins.op_str:
        print("    [end of fn]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [end of fn]")
        break

print()
print("=== Summary: bl call targets ===")
bl_targets = []
for ins in out:
    if ins.mnemonic == "bl" and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            bl_targets.append((ins.address, target))
        except Exception:
            pass
for src, tgt in bl_targets:
    print(f"  call from {src:#x} → {tgt:#x}")
