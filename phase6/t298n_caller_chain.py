"""T298n: characterize fn@0x68A68 (caller of fn@0x6820C) and find ITS callers.
Iterate caller-chain back until we hit something named (with a string ref to
e.g. 'wlc_attach' or 'wl_probe' or other identifiable wlc init point).
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


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


# Dump fn@0x68A68 first 30 ins to characterize it
print("=== fn@0x68A68 prologue + first 30 ins (caller of fn@0x6820C) ===\n")
seen = 0
for ins in md.disasm(data[0x68A68:0x68A68 + 0x100], 0x68A68):
    annot = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s: annot = f"  ; \"{s}\""
                else: annot = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{target:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    seen += 1
    if seen >= 30: break


# Find callers of fn@0x68A68
print("\n\n=== Callers of fn@0x68A68 ===\n")
hits = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x68A68:
                hits.append(ins)
        except: pass
print(f"Direct hits: {len(hits)}")
for ins in hits:
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# Also fn-ptr table
needle = struct.pack("<I", 0x68A69)
ptr_hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    if idx % 4 == 0: ptr_hits.append(idx)
    pos = idx + 1
print(f"Indirect (fn-ptr) hits: {len(ptr_hits)}")
for h in ptr_hits:
    print(f"  fn-ptr at file offset {h:#x}")


# For each direct caller, look up enclosing fn
def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str
def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str
def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


def find_containing_fn(addr):
    candidates = []
    for ins in all_ins:
        if ins.address >= addr: break
        if is_push_lr(ins):
            candidates.append(ins.address)
    # Test latest first
    for c in reversed(candidates):
        depth = 0
        in_fn = False
        end = None
        for ins in all_ins:
            if ins.address < c: continue
            if is_push_lr(ins):
                depth += 1
                in_fn = True
            elif is_pop_pc(ins) or is_bx_lr(ins):
                if in_fn:
                    depth -= 1
                    if depth == 0:
                        end = ins.address + ins.size
                        break
        if end and end > addr:
            return c, end
    return None, None


print(f"\n=== Caller fn for each hit ===")
for ins in hits:
    fn, end = find_containing_fn(ins.address)
    print(f"  call @ {ins.address:#x}: caller fn @ {hex(fn) if fn else '?'} (ends {hex(end) if end else '?'})")
