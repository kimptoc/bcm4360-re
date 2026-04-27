"""T299z: trace the actual wfi caller chain.
fn@0x1c1e (wfi;bx lr) is the idle leaf. Only direct call: b.w at 0x1c0c.
Find: who calls 0x1c0c? And up the chain.

Also: spot-check real-fn density around the cpsie 0x4356e — does any
push-lr have a matching pop within reach? If not, that area is data.
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
        emitted = False
        last = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted = True
            last = ins.address + ins.size
            if last >= len(data) - 2: return
        pos = last if emitted else pos + 2


print("Disasm pass...")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str
def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str
def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


# (1) Find direct callers/jumpers to fn@0x1c0c (the wfi tail-wrapper)
print("=== (1) Direct callers/jumpers to 0x1c0c (wfi tail-wrapper) ===")
direct_to_1c0c = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x1c0c: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        direct_to_1c0c.append(ins)
print(f"  Direct: {len(direct_to_1c0c)}")
for ins in direct_to_1c0c[:10]:
    print(f"    {ins.address:#x}: {ins.mnemonic} → 0x1c0c")

# fn-ptr (0x1c0d) hits
needle = struct.pack("<I", 0x1c0d)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x1c0d) byte hits: {len(hits)}")


# (2) Climb the caller chain from wfi-tail-wrapper to find a known root
print("\n\n=== (2) Climb caller chain from 0x1c0c (or wfi 0x1c1e) ===")

def find_fn_start_loose(addr):
    """For tiny leaf functions, find_fn_start may go too far back. Use a more
    permissive heuristic: any push-lr OR any address that's the target of bl/b
    from somewhere else."""
    # First try: closest push-lr <= addr within 0x100 bytes
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if ins.address < addr - 0x80: continue
        if is_push_lr(ins): last = ins.address
    return last

# Build a callgraph: target -> {caller_fn (where caller is fn-start of containing fn)}
print("  Building reverse callgraph (callee -> direct callers)...")
import bisect
fn_starts = sorted([i.address for i in all_ins if is_push_lr(i)])

def fn_containing(addr):
    i = bisect.bisect_right(fn_starts, addr) - 1
    if i < 0: return None
    return fn_starts[i]

# Reverse callgraph
rev_cg = {}  # callee -> set of caller fns
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    if ins.mnemonic not in ("bl", "blx", "b", "b.w"): continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    cf = fn_containing(ins.address)
    if cf is not None:
        rev_cg.setdefault(t, set()).add(cf)

# Add small targets and their adjacencies
# For tiny leaf functions like 0x1c0c which has no push-lr, treat the target itself as a "function"
# and find its callers (already in rev_cg).

# Climb from 0x1c0c
from collections import deque
seen = set([0x1c0c])
q = deque([(0x1c0c, 0)])
while q:
    addr, depth = q.popleft()
    if depth > 8: continue
    callers = rev_cg.get(addr, set())
    indent = "  " * (depth + 1)
    if not callers:
        # try the wfi addr 0x1c1e
        if addr == 0x1c0c:
            print(f"{indent}fn@{addr:#x} (wfi-tail-wrap): no direct callers via fn-graph")
            continue
        print(f"{indent}fn@{addr:#x}: NO callers (root)")
        continue
    for c in sorted(callers):
        if c in seen: continue
        seen.add(c)
        marker = ""
        # Is c a known root or in any of our key sets?
        if c == 0x268: marker = " ★ BOOTSTRAP"
        elif c == 0x2408: marker = " ★ MAIN"
        elif c == 0x11d0: marker = " ★ MAIN-IDLE-LOOP"
        print(f"{indent}fn@{addr:#x} ← fn@{c:#x}{marker}")
        q.append((c, depth + 1))


# (3) Look for ALL b/b.w landing in [0x1c00, 0x1c20] — find tail-callers of any wfi-related leaf
print("\n\n=== (3) ALL bl/b targets in [0x1c00, 0x1c30] ===")
hits = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    if ins.mnemonic not in ("bl", "blx", "b", "b.w"): continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if 0x1c00 <= t <= 0x1c30:
        hits.append((ins, t))
print(f"  Total: {len(hits)}")
for ins, t in hits[:20]:
    cf = fn_containing(ins.address)
    print(f"    {ins.address:#x}: {ins.mnemonic} → {t:#x}  inside fn@{hex(cf) if cf else '?'}")


# (4) Verify cpsie 0x4356e — find nearest push-lr forward and back, see if real fn boundaries
print("\n\n=== (4) Verify cpsie ai at 0x4356e — fn-boundary check ===")
# Find all push-lr and pop-pc in [0x43500, 0x43600]
pushes = [i for i in all_ins if 0x43500 <= i.address < 0x43600 and is_push_lr(i)]
pops = [i for i in all_ins if 0x43500 <= i.address < 0x43600 and (is_pop_pc(i) or is_bx_lr(i))]
print(f"  push-lr in [0x43500, 0x43600]: {len(pushes)}")
for p in pushes:
    print(f"    {p.address:#x}: {p.mnemonic} {p.op_str}")
print(f"  pop-pc / bx-lr in [0x43500, 0x43600]: {len(pops)}")
for p in pops:
    print(f"    {p.address:#x}: {p.mnemonic} {p.op_str}")


# (5) Check whether the 0xb666 word at 0x4356e is part of a STRING or other recognizable data
print("\n\n=== (5) Bytes 0x43500..0x43600 — find any printable string spans ===")
chunk = data[0x43500:0x43600]
print(f"  Printable spans (len >= 4):")
i = 0
while i < len(chunk):
    if 32 <= chunk[i] < 127:
        j = i
        while j < len(chunk) and 32 <= chunk[j] < 127:
            j += 1
        if j - i >= 4:
            s = chunk[i:j].decode("ascii", errors="replace")
            print(f"    @ {0x43500 + i:#x}: \"{s}\"")
        i = j
    else:
        i += 1
