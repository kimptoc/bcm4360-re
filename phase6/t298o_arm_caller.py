"""T298o: find callers of fn@0x233E8 (the ARM function — copies flag_struct[+0x64]
to [+0x60] AND writes D11+0x16C with the wake mask 0x48080).

If fn@0x233E8 is called by wl_probe or its descendants, the wake is armed
during early fw init.

If it's called by a LATER init helper (e.g., wlc_set_state, wlc_up,
or post-DMA-attach), the wake is NOT armed at the WFI freeze point we
observe in T287c.

Also find callers of fn@0x2340C (the DISARM function).

Also dump the strings at 0x4C6E2 (referenced by fn@0x68A68) to identify
fn@0x68A68's name.
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


# String identification
print("=== Strings near 0x4C6E2 (referenced by fn@0x68A68) ===")
for off in (0x4c6e2, 0x4c6e0, 0x4c6e4):
    s = str_at(off)
    if s: print(f"  @{off:#x}: \"{s}\"")
print()


# Find callers of fn@0x233E8 (ARM function)
print("=== Direct callers of fn@0x233E8 (wake-mask ARM) ===")
hits_arm = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x233E8:
                hits_arm.append(ins)
        except: pass
print(f"Direct: {len(hits_arm)}")
for ins in hits_arm:
    fn, end = find_containing_fn(ins.address)
    print(f"  call @ {ins.address:#x}: caller fn @ {hex(fn) if fn else '?'}")


# Indirect (fn-ptr table)
print("\n=== Literal references to 0x233E9 (Thumb fn ptr to fn@0x233E8) ===")
needle = struct.pack("<I", 0x233E9)
hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    if idx % 4 == 0: hits.append(idx)
    pos = idx + 1
print(f"Aligned literal hits: {len(hits)}")
for h in hits:
    print(f"  fn-ptr at file offset {h:#x}")


# Same for fn@0x2340C (DISARM)
print("\n\n=== Direct callers of fn@0x2340C (wake-mask DISARM) ===")
hits_dis = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target == 0x2340C:
                hits_dis.append(ins)
        except: pass
print(f"Direct: {len(hits_dis)}")
for ins in hits_dis:
    fn, end = find_containing_fn(ins.address)
    print(f"  call @ {ins.address:#x}: caller fn @ {hex(fn) if fn else '?'}")
