"""T297-9: characterize the fn around 0x6A8A4 (str at +0x60), 0x6A8CC (strb at +0x88),
and 0x6AC70 (strb at +0xAC) — the closest shape-match to flag_struct in T297e's cluster scan.

Goal: dump enclosing fn body, look for additional [+0x88] byte stores at +0x89/+0x8A/+0x8B
(the rest of a 4-byte init via 4 strbs), or other indirect [+0x88] writes.

If this is flag_struct's allocator/init, we'll see: alloc → byte fields → 32-bit base
populated via some indirect mechanism.
"""
import struct, sys
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted_any = True
            last_end = ins.address + ins.size
            if last_end >= len(data) - 2:
                return
        pos = last_end if emitted_any else pos + 2


print("Disasm pass…")
all_ins = list(iter_all())
ins_by_addr = {ins.address: ins for ins in all_ins}
addrs = sorted(ins_by_addr.keys())
print(f"Total: {len(all_ins):,}\n")


def find_fn_start(addr, scan_back=0x1000):
    pushes = []
    ends_after = {}
    start = max(0, addr - scan_back)
    for ins in all_ins:
        if ins.address < start or ins.address >= addr:
            continue
        if ins.mnemonic == "push" and "lr" in ins.op_str:
            pushes.append(ins.address)
        elif (ins.mnemonic == "pop" and "pc" in ins.op_str) or (
            ins.mnemonic == "bx" and ins.op_str.strip() == "lr"
        ):
            for p in pushes:
                if p not in ends_after:
                    ends_after[p] = ins.address
    for p in reversed(pushes):
        end = ends_after.get(p)
        if end is None or end > addr:
            return p
    return None


def find_fn_end(start_addr):
    for ins in all_ins:
        if ins.address < start_addr:
            continue
        if (ins.mnemonic == "pop" and "pc" in ins.op_str) or (
            ins.mnemonic == "bx" and ins.op_str.strip() == "lr"
        ):
            return ins.address + ins.size
    return None


targets = [(0x6A8A4, "str +0x60"), (0x6A8CC, "strb +0x88"), (0x6AC70, "strb +0xAC")]

for addr, tag in targets:
    fn = find_fn_start(addr, scan_back=0x4000)
    print(f"\n{'='*72}\n{tag} @ {addr:#x}: enclosing fn = {hex(fn) if fn is not None else 'NOT FOUND'}\n{'='*72}")

# All three should be in the same function if they're shape-matches
fn = find_fn_start(0x6A8A4, scan_back=0x4000)
if fn is None:
    print("Could not find common enclosing fn; aborting body dump.")
    sys.exit(0)

end = find_fn_end(fn)
print(f"\nFn body: {fn:#x} → {hex(end) if end else '?'}")
print(f"Size: {end - fn if end else '?'} bytes")

# Dump body, marking key offsets
KEY_OFFSETS = (0x60, 0x88, 0xAC)
print("\n--- Body (highlighting [r4, +imm] stores; key offsets marked) ---\n")
for ins in all_ins:
    if ins.address < fn or (end and ins.address >= end):
        continue
    annot = ""
    if ins.mnemonic in ("str", "str.w", "strb", "strb.w", "strh", "strh.w", "strd"):
        if "[r4," in ins.op_str:
            try:
                off_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                off = int(off_s, 16) if off_s.startswith("0x") else int(off_s)
                marker = "  ***" if off in KEY_OFFSETS else ""
                annot = f"  [r4 +{off:#x}]{marker}"
            except Exception:
                annot = "  [r4, ?]"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
