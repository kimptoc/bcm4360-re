"""T298p: characterize the OTHER 32-bit D11+0x16C writers — sites 0x23420
and 0x23448. Find their enclosing fns + callers.

If one of these is the init-time arming function, find its caller chain
and check whether it's reached during wl_probe.
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


# Identify enclosing fns for 0x23402, 0x23420, 0x23448
print("=== Enclosing fn for each [reg, +0x16C] 32-bit writer ===\n")
for site in (0x23402, 0x23420, 0x23448):
    fn, end = find_containing_fn(site)
    print(f"  Site {site:#x}: fn @ {hex(fn) if fn else '?'} (ends {hex(end) if end else '?'})")


# For each enclosing fn, find callers
print("\n=== Callers of each enclosing fn ===")
for site in (0x23402, 0x23420, 0x23448):
    fn, end = find_containing_fn(site)
    if not fn:
        print(f"\nSite {site:#x}: enclosing fn unknown")
        continue
    print(f"\nSite {site:#x} → fn@{fn:#x}: callers:")
    hits = []
    for ins in all_ins:
        if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
            try:
                target = int(ins.op_str.lstrip("#").strip(), 16)
                if target == fn:
                    hits.append(ins)
            except: pass
    for ins in hits:
        caller_fn, _ = find_containing_fn(ins.address)
        print(f"  call @ {ins.address:#x}: caller fn @ {hex(caller_fn) if caller_fn else '?'}")

    # Also fn-ptr table
    needle = struct.pack("<I", fn | 1)
    pos = 0
    ptr_hits = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        if idx % 4 == 0: ptr_hits.append(idx)
        pos = idx + 1
    if ptr_hits:
        print(f"  fn-ptr table refs: {len(ptr_hits)}")
        for h in ptr_hits[:5]:
            print(f"    {h:#x}")


# Also dump fn@0x2340C body briefly (where 0x23420 and 0x23448 likely live)
print("\n\n=== fn body around 0x2340C (sibling DISARM fn) ===\n")
for ins in md.disasm(data[0x2340C:0x23470], 0x2340C):
    annot = ""
    if ins.mnemonic in ("mov", "mov.w", "movs", "movw") and "#" in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].strip()
            val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
            annot = f"  ; const={val:#x}"
        except: pass
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{target:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str:
        print("    [end]")
        break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        print("    [bx lr]")
        break
