"""T299x: identify the functions containing cpsie at 0x4356e and wfi at 0x1c1e.
Then check if those functions are reachable from the bootstrap BFS.

Also: check if the BFS-reached `cpsie ai` site is in the same fn as wfi (idle).
If cpsie+wfi are in the live idle path, IRQs are enabled and the wake-gate
INTMASK path is meaningful.
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


print("Disasm pass...")
all_ins = list(iter_all())
print(f"Total ins: {len(all_ins):,}\n")


def find_fn_start(addr):
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if is_push_lr(ins): last = ins.address
    return last


def find_fn_end(start, max_size=0x600):
    depth = 0; in_fn = False
    for ins in all_ins:
        if ins.address < start: continue
        if ins.address > start + max_size: break
        if is_push_lr(ins):
            depth += 1; in_fn = True
        elif is_pop_pc(ins) or is_bx_lr(ins):
            if in_fn:
                depth -= 1
                if depth == 0: return ins.address + ins.size
    return start + max_size


# (1) Identify containing fns
print("=== (1) Containing function for key insns ===")
for label, addr in [("wfi (idle)", 0x1c1e), ("cpsie ai (IRQ enable)", 0x4356e),
                    ("cpsid none #1", 0x45890), ("cpsid none #2", 0x470ba),
                    ("cpsid af", 0x6b89c)]:
    fn = find_fn_start(addr)
    end = find_fn_end(fn) if fn else None
    print(f"  {label} @ {addr:#x}  inside fn@{hex(fn) if fn else '?'}..{hex(end) if end else '?'}")


# (2) Dump fn containing wfi (likely the idle function)
print("\n\n=== (2) Dump fn containing wfi (the idle function) ===")
fn_wfi = find_fn_start(0x1c1e)
print(f"  fn-start: {hex(fn_wfi) if fn_wfi else '?'}")
if fn_wfi:
    end = find_fn_end(fn_wfi)
    print(f"  fn-end: {hex(end)}")
    print()
    chunk = data[fn_wfi:end]
    for ins in md.disasm(chunk, fn_wfi):
        a = ""
        if ins.mnemonic in ("cpsie", "cpsid"):
            a = "  ★★★ CPSR-CTL"
        elif ins.mnemonic in ("wfi", "wfe"):
            a = "  ★★★ HALT"
        elif ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if 0 <= la <= len(data) - 4:
                    val = struct.unpack_from('<I', data, la)[0]
                    s = str_at(val)
                    if s: a = f"  ; \"{s}\""
                    else: a = f"  ; lit={val:#x}"
            except: pass
        elif ins.mnemonic == "bl" and "#0x" in ins.op_str:
            a = f"  → {ins.op_str}"
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")


# (3) Dump fn containing cpsie ai
print("\n\n=== (3) Dump fn containing cpsie ai ===")
fn_cpsie = find_fn_start(0x4356e)
print(f"  fn-start: {hex(fn_cpsie) if fn_cpsie else '?'}")
if fn_cpsie:
    end = find_fn_end(fn_cpsie)
    print(f"  fn-end: {hex(end)}")
    print()
    chunk = data[fn_cpsie:end]
    n = 0
    for ins in md.disasm(chunk, fn_cpsie):
        a = ""
        if ins.mnemonic in ("cpsie", "cpsid"):
            a = "  ★★★ CPSR-CTL"
        elif ins.mnemonic in ("wfi", "wfe"):
            a = "  ★★★ HALT"
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
        n += 1
        if n >= 60: print("  ..."); break


# (4) BFS from fn@0x268 — does it reach the cpsie's fn or the wfi's fn?
print("\n\n=== (4) Reachability check from fn@0x268 ===")
# Use prior simple BFS

def fn_targets_simple(start):
    targets = set()
    chunk = data[start:start + 0x800]
    for ins in md.disasm(chunk, start):
        if ins.mnemonic in ("bl", "blx", "b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                targets.add(t)
            except: pass
        # Indirect bx/blx via literal pool
        if ins.mnemonic in ("bx", "blx") and ins.op_str.strip().startswith("r"):
            # Look back for ldr to that reg
            pass
        if ins.mnemonic == "pop" and "pc" in ins.op_str: break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": break
    return targets

from collections import deque
seen = set([0x268])
q = deque([(0x268, 0)])
while q:
    fn, depth = q.popleft()
    if depth >= 12: continue
    if fn < 0 or fn >= len(data): continue
    for t in sorted(fn_targets_simple(fn)):
        if t < 0 or t >= len(data): continue
        if t in seen: continue
        seen.add(t)
        q.append((t, depth + 1))
print(f"BFS reach: {len(seen)} fns")
print(f"  fn containing wfi   ({hex(fn_wfi) if fn_wfi else '?'}): {'★ REACHED' if fn_wfi in seen else '✗ not reached'}")
print(f"  fn containing cpsie ({hex(fn_cpsie) if fn_cpsie else '?'}): {'★ REACHED' if fn_cpsie in seen else '✗ not reached'}")


# (5) Find callers of fn@0x4356e's containing fn
print(f"\n\n=== (5) Direct callers of cpsie's fn ({hex(fn_cpsie)}) ===")
if fn_cpsie:
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != fn_cpsie: continue
        if ins.mnemonic in ("bl", "blx", "b", "b.w"):
            caller_fn = find_fn_start(ins.address)
            print(f"  {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(caller_fn) if caller_fn else '?'}")
    needle = struct.pack("<I", fn_cpsie | 1)
    pos = 0; hits = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    print(f"  fn-ptr hits ({(fn_cpsie | 1):#x}): {len(hits)}")


print(f"\n=== (6) Callers of wfi's fn ({hex(fn_wfi)}) ===")
if fn_wfi:
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != fn_wfi: continue
        if ins.mnemonic in ("bl", "blx", "b", "b.w"):
            caller_fn = find_fn_start(ins.address)
            print(f"  {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(caller_fn) if caller_fn else '?'}")
