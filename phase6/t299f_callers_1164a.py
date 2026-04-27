"""T299f: identify fn@0x1164A and find its callers.

Also: find code refs to "WLC_UP" string at 0x4F423 — those are likely the
ioctl-table entries that map "WLC_UP" name to its handler.
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


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str
def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str
def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


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


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def find_containing_fn(addr):
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


# (1) String at lit@0x4a064 — fn@0x1164A's printf string
print("=== (1) Printf string at 0x4A064 (referenced by fn@0x1164A) ===")
s = str_at(0x4A064)
print(f"  \"{s}\"")
# Also check around — multiple strings in a row?
for off in (0x4a040, 0x4a050, 0x4a060, 0x4a070, 0x4a080, 0x4a090):
    s = str_at(off)
    if s: print(f"  @{off:#x}: \"{s}\"")


# (2) Find direct callers of fn@0x1164A
print("\n=== (2) Direct callers of fn@0x1164A ===")
direct = []; tail = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x1164A: continue
    if ins.mnemonic in ("bl", "blx"):
        direct.append(ins)
    elif ins.mnemonic in ("b", "b.w"):
        tail.append(ins)
print(f"  bl/blx: {len(direct)}")
for ins in direct:
    fn, end = find_containing_fn(ins.address)
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str} → caller fn @ {hex(fn) if fn else '?'}")
print(f"  b/b.w: {len(tail)}")
for ins in tail:
    fn, end = find_containing_fn(ins.address)
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str} → caller fn @ {hex(fn) if fn else '?'}")

# fn-ptr table refs to 0x1164B
needle = struct.pack("<I", 0x1164B)
ptr_hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    ptr_hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x1164B) any alignment: {len(ptr_hits)}")
for h in ptr_hits[:10]:
    ctx_start = max(0, h - 16)
    ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
    print(f"    {h:#x} aligned={h%4==0}: {ctx}")


# (3) Code refs to "WLC_UP" string at 0x4F423
print("\n=== (3) Code refs to \"WLC_UP\" string at 0x4F423 ===")
refs = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x4F423:
                refs.append((ins.address, la))
    except: pass
print(f"  Code refs: {len(refs)}")
for ref_addr, la in refs:
    fn, end = find_containing_fn(ref_addr)
    print(f"    {ref_addr:#x} (lit@{la:#x})  containing fn @ {hex(fn) if fn else '?'}")

# Also: literal-pool packed search for 0x4F423 in any alignment (in case it's
# in a struct template — like an ioctl name table)
print("\n=== (4) ALL byte occurrences of 0x4F423 (any alignment) ===")
needle = struct.pack("<I", 0x4F423)
all_hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    all_hits.append(idx); pos = idx + 1
print(f"  Hits: {len(all_hits)}")
for h in all_hits[:10]:
    aligned = h%4==0
    # If aligned and could be a struct template, show 32 bytes
    if aligned:
        ctx_start = max(0, h - 16)
        ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
        print(f"    {h:#x} aligned: {ctx}")
    else:
        print(f"    {h:#x} unaligned")
