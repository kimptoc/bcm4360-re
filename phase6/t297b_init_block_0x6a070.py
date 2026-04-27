"""T297-2: characterize the struct-init block around 0x6A070.

Site 0x6A070 is a series of stores to [r4, +0x2C/+0x6C/+0x70/+0x74/+0x88/+0x8C],
with each value loaded from a PC-relative literal. This looks like an
initializer for a wlc-internal struct.

Goal: resolve every literal value, find the enclosing function, identify
all other [r4, +imm] stores in that function (to map the struct shape).

If the resulting struct has BOTH [+0x60] and [+0xAC] writes nearby (the
flag_struct discriminators per fn@0x23374), that's our smoking gun.
"""
import struct, sys

sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = False


def find_fn_start(addr, scan_back=0x4000):
    """Walk back looking for `push {..., lr}` that has no fn-end between
    it and addr — i.e. the push is OUR enclosing fn's prologue, not some
    earlier fn's."""
    start = max(0, addr - scan_back)
    pushes = []
    ends_after = {}
    for ins in md.disasm(data[start:addr + 4], start):
        if ins.mnemonic == "push" and "lr" in ins.op_str:
            pushes.append(ins.address)
        elif (ins.mnemonic == "pop" and "pc" in ins.op_str) or (
            ins.mnemonic == "bx" and "lr" in ins.op_str
        ):
            # Mark each prior push as "has-end-after"
            for p in pushes:
                if p not in ends_after:
                    ends_after[p] = ins.address
    # Best candidate: latest push WITHOUT a fn-end between it and addr
    for p in reversed(pushes):
        end = ends_after.get(p)
        if end is None or end > addr:
            return p
    return None


def find_fn_end(addr, scan_fwd=0x4000):
    """Walk forward to find pop {..., pc} or bx lr — fn epilogue."""
    end = min(len(data), addr + scan_fwd)
    for ins in md.disasm(data[addr:end], addr):
        if ins.mnemonic in ("pop",) and "pc" in ins.op_str:
            return ins.address + ins.size
        if ins.mnemonic == "bx" and "lr" in ins.op_str:
            return ins.address + ins.size
    return end


# Locate enclosing fn for 0x6A070
fn_start = find_fn_start(0x6A070, scan_back=0x6000)
print(f"Enclosing fn for 0x6a070: {hex(fn_start) if fn_start else 'NOT FOUND'}")
fn_end = find_fn_end(fn_start, scan_fwd=0x4000) if fn_start else None
print(f"Fn end:                    {hex(fn_end) if fn_end else 'NOT FOUND'}")
print(f"Fn size: {fn_end - fn_start if fn_end and fn_start else '?'} bytes")

# Disasm the entire enclosing function
print(f"\n{'='*72}")
print(f"=== Full disasm of fn@{hex(fn_start)} (with [r4, +imm] store annotations) ===")
print(f"{'='*72}")

# Resolve PC-relative literal values
def resolve_pc_lit(ins):
    """Returns the literal value if ins is a PC-rel ldr, else None."""
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


r4_stores = []
in_fn = data[fn_start:fn_end] if fn_start and fn_end else b""
prev_lit_value = None
prev_lit_addr = None
for ins in md.disasm(in_fn, fn_start):
    annot = ""
    pc_rel = resolve_pc_lit(ins)
    if pc_rel:
        prev_lit_addr, prev_lit_value = pc_rel
        annot = f"  ; lit@{prev_lit_addr:#x} = {prev_lit_value:#010x}"
    if ins.mnemonic in ("str", "str.w") and ", [r4," in ins.op_str:
        # Capture offset
        try:
            off_str = ins.op_str.split("#")[-1].rstrip("]").strip()
            off = int(off_str, 16) if off_str.startswith("0x") else int(off_str)
            r4_stores.append((ins.address, off, prev_lit_value))
            annot += f"  *** [r4, +{off:#x}] store ***"
        except Exception:
            annot += "  *** [r4, ?] store ***"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")

print(f"\n=== Summary: stores to [r4, +imm] in fn@{hex(fn_start)} ===")
for addr, off, val in r4_stores:
    val_s = f"{val:#010x}" if val is not None else "?"
    print(f"  {addr:#7x}: [r4, +{off:#x}] = {val_s}")

# Are 0x60 and 0xAC among the offsets?
offsets = sorted(set(o for _, o, _ in r4_stores))
print(f"\nOffsets touched: {[hex(o) for o in offsets]}")
print(f"Has +0x60 (flag_struct queue state): {'YES' if 0x60 in offsets else 'no'}")
print(f"Has +0x88 (flag_struct wake-gate base): {'YES' if 0x88 in offsets else 'no'}")
print(f"Has +0xAC (flag_struct enabled flag):  {'YES' if 0xAC in offsets else 'no'}")
