"""T299a: find direct callers of fn@0x17ED6 (wlc_bmac_up_finish).

Scan ALL bl/blx/b/b.w + fn-ptr table refs (any alignment).
For each caller, identify enclosing fn + look for printf strings to name it.
"""
import sys, struct
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


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str
def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str
def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def find_containing_fn(addr):
    """Find the enclosing fn (push-lr / push.w-lr) that contains addr."""
    candidates = []
    for ins in all_ins:
        if ins.address >= addr: break
        if is_push_lr(ins):
            candidates.append(ins.address)
    for c in reversed(candidates):
        depth = 0; in_fn = False; end = None
        for ins in all_ins:
            if ins.address < c: continue
            if is_push_lr(ins):
                depth += 1; in_fn = True
            elif is_pop_pc(ins) or is_bx_lr(ins):
                if in_fn:
                    depth -= 1
                    if depth == 0:
                        end = ins.address + ins.size
                        break
        if end and end > addr:
            return c, end
    return None, None


def fn_strings(start, end):
    """Find printf strings referenced via PC-rel ldr in [start, end)."""
    out = []
    for ins in all_ins:
        if ins.address < start or ins.address >= end: continue
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s and len(s) >= 6:
                    out.append((ins.address, val, s))
        except: pass
    return out


# Search for ALL refs to fn@0x17ED6
target = 0x17ED6
print(f"=== Direct bl/blx callers of fn@0x17ED6 (wlc_bmac_up_finish) ===\n")
direct_bl = []
tail_b = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != target: continue
    if ins.mnemonic in ("bl", "blx"):
        direct_bl.append(ins)
    elif ins.mnemonic in ("b", "b.w"):
        tail_b.append(ins)

print(f"bl/blx hits: {len(direct_bl)}")
for ins in direct_bl:
    fn, end = find_containing_fn(ins.address)
    fn_name = "?"
    if fn and end:
        strs = fn_strings(fn, end)
        for _, _, s in strs:
            if "wlc_" in s.lower() or "bmac" in s.lower() or ".c" in s.lower():
                fn_name = s
                break
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}  caller fn @ {hex(fn) if fn else '?'}  name=\"{fn_name}\"")

print(f"\nb/b.w tail-call hits: {len(tail_b)}")
for ins in tail_b:
    fn, end = find_containing_fn(ins.address)
    fn_name = "?"
    if fn and end:
        strs = fn_strings(fn, end)
        for _, _, s in strs:
            if "wlc_" in s.lower() or "bmac" in s.lower() or ".c" in s.lower():
                fn_name = s
                break
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}  caller fn @ {hex(fn) if fn else '?'}  name=\"{fn_name}\"")


# Thumb fn-ptr table refs (any alignment)
print(f"\n=== Packed Thumb fn-ptr (0x17ED7) any alignment ===")
needle = struct.pack("<I", 0x17ED7)
hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx)
    pos = idx + 1
print(f"  Hits: {len(hits)}")
for h in hits:
    print(f"    file offset {h:#x} (aligned: {h%4==0})")


# Also: get all printf strings INSIDE wlc_bmac_up_finish to characterize it
print(f"\n=== ALL printf strings inside fn@0x17ED6 (wlc_bmac_up_finish) ===")
fn_strs = fn_strings(0x17ED6, 0x17F70)
for ins_addr, val, s in fn_strs:
    print(f"  {ins_addr:#x}: ldr → \"{s}\" (lit val={val:#x})")
