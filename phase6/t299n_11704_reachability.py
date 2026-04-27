"""T299n: identify fn@0x11704 (NEW caller of fn@0x142E0 — the 0x48080 writer)
and trace its reachability. If reachable from pciedngl_probe descendants
(or any live offload-mode entry), then 0x48080 IS armed at runtime and the
'wake gate dead' conclusion is wrong.

Method:
1. Dump fn@0x11704 body — what does it do? Print strings? Other ldr context.
2. Find ALL callers of fn@0x11704 (bl, fn-ptr, etc.)
3. Climb the caller tree until we hit either:
   - a known LIVE entry (pciedngl_probe, pciedngl_isr, etc.)
   - a DEAD entry (wl_probe, wl_open, handlers table)
   - or a fixed point at depth N
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


NAMED = {
    0x9990:  "si_setcoreidx",
    0x11790: "wrap_ARM",
    0x142E0: "fn@0x142E0 (writes 0x48080)",
    0x15DA8: "wlc_bmac_up_prep",
    0x17ED6: "wlc_bmac_up_finish",
    0x18FFC: "wlc_up",
    0x11648: "wl_open",
    0x6820C: "wlc_bmac_attach",
    0x68A68: "wlc_attach",
    0x67614: "wl_probe",
    0x67358: "si_doattach_wrapper",
    0x670d8: "si_doattach",
    0x1c74:  "pciedngl_open",
    0x1e90:  "pciedngl_probe",
    0x1c98:  "pciedngl_isr",
    0x1c50:  "pciedngl_close",
    0x1c38:  "pciedngl_ioctl",
    0x1d9c:  "pciedngl_send",
    0x2f18:  "bcm_olmsg_init",
    0x11704: "fn@0x11704",
}

LIVE_ROOTS = {0x1c74, 0x1c98, 0x1e90, 0x1c50, 0x1c38, 0x1d9c, 0x2f18}
DEAD_ROOTS = {0x67614, 0x11648, 0x68A68, 0x6820C, 0x18FFC, 0x17ED6}


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


def annot(ins):
    a = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s: a = f"  ; \"{s}\""
                elif val & 1 and 0x1000 < val < len(data):
                    target = val - 1
                    name = NAMED.get(target, "")
                    a = f"  ; lit={val:#x} → fn@{target:#x}{(' = '+name) if name else ''}"
                else:
                    a = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic == "bl" and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  → {NAMED[t]}"
            else: a = f"  → fn@{t:#x}"
        except: pass
    elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  >>> TAIL→{NAMED[t]} <<<"
            else: a = f"  → tail-fn@{t:#x}"
        except: pass
    elif ins.mnemonic == "blx" and ins.op_str.strip().startswith("r"):
        a = "  → INDIRECT (fn-ptr in reg)"
    return a


def dump_fn(name, start, end=None, max_lines=200):
    if end is None: end = find_fn_end(start)
    print(f"\n=========== {name}  fn @ {start:#x}..{end:#x} ===========")
    n = 0
    for ins in all_ins:
        if ins.address < start: continue
        if ins.address >= end: break
        a = annot(ins)
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
        n += 1
        if n >= max_lines:
            print(f"  ... TRUNCATED at {max_lines} lines")
            break
    print(f"  ... [end {end:#x}]")


# ============== (1) Dump fn@0x11704 ==============
print("=== (1) DUMP fn@0x11704 (NEW caller of 0x142E0) ===")
dump_fn("fn@0x11704", 0x11704, max_lines=150)


# ============== (2) Find ALL direct + fn-ptr callers of fn@0x11704 ==============
def find_callers(target, target_thumb):
    direct = []
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != target: continue
        if ins.mnemonic in ("bl", "blx", "b", "b.w"):
            direct.append(ins)
    needle = struct.pack("<I", target_thumb)
    fn_ptr_hits = []; pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        fn_ptr_hits.append(idx); pos = idx + 1
    return direct, fn_ptr_hits


print("\n\n=== (2) Callers of fn@0x11704 ===")
direct, ptrs = find_callers(0x11704, 0x11705)
print(f"  Direct bl/b: {len(direct)}")
for ins in direct:
    fn = find_fn_start(ins.address)
    fn_name = NAMED.get(fn, "")
    print(f"    {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}{(' = '+fn_name) if fn_name else ''}")
print(f"  fn-ptr (0x11705) any alignment: {len(ptrs)}")
for h in ptrs[:8]:
    ctx_start = max(0, h - 16)
    ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
    print(f"    {h:#x} aligned={h%4==0}  ctx: {ctx}")


# ============== (3) BFS upward from fn@0x11704 — climb caller tree to find live or dead root ==============
print("\n\n=== (3) BFS-climb caller tree from fn@0x11704 ===")
# Build a callgraph (caller-fn -> {callee-fn, ...}) for direct calls
print("  Building callgraph from direct bl/b/blx targets...")
callees_of_fn = {}  # caller_fn -> set of callee fn-starts (only known)
callers_of_fn = {}  # callee fn-start -> set of caller fn-starts
fn_starts = set()

# Collect fn starts from push-lr
for ins in all_ins:
    if is_push_lr(ins):
        fn_starts.add(ins.address)

print(f"  fn_starts identified: {len(fn_starts):,}")

# For each call insn, attribute to containing fn
def fn_containing(addr, sorted_starts):
    """Binary search the largest fn_start <= addr."""
    import bisect
    i = bisect.bisect_right(sorted_starts, addr) - 1
    if i < 0: return None
    return sorted_starts[i]

sorted_starts = sorted(fn_starts)
import bisect

for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    if ins.mnemonic not in ("bl", "blx", "b", "b.w"): continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    caller_fn = fn_containing(ins.address, sorted_starts)
    if caller_fn is None: continue
    callees_of_fn.setdefault(caller_fn, set()).add(t)
    callers_of_fn.setdefault(t, set()).add(caller_fn)

# fn-ptr alignments — also count as edges (since we don't know what reads them)
# Skip for now; direct call graph only

# BFS upward from 0x11704
from collections import deque
print(f"\n  BFS upward from fn@0x11704:")
seen = set([0x11704])
q = deque([(0x11704, 0)])
while q:
    fn, depth = q.popleft()
    if depth > 8: continue
    callers = callers_of_fn.get(fn, set())
    indent = "  " * (depth + 1)
    name = NAMED.get(fn, f"fn@{fn:#x}")
    if fn in LIVE_ROOTS:
        print(f"{indent}>>> LIVE ROOT REACHED: {name} <<<")
    if fn in DEAD_ROOTS:
        print(f"{indent}>>> DEAD ROOT REACHED: {name} <<<")
    if not callers:
        print(f"{indent}{name}: NO CALLERS (root)")
        continue
    for c in sorted(callers):
        if c in seen: continue
        seen.add(c)
        cname = NAMED.get(c, f"fn@{c:#x}")
        marker = ""
        if c in LIVE_ROOTS: marker = " ★ LIVE"
        elif c in DEAD_ROOTS: marker = " ✗ DEAD"
        print(f"{indent}{name} ← {cname}{marker}")
        q.append((c, depth + 1))


# ============== (4) Same BFS for fn@0x6820C (wlc_bmac_attach) — confirm it's only reached from dead ==============
print("\n\n=== (4) BFS-climb from wlc_bmac_attach (0x6820C) for sanity ===")
seen = set([0x6820C])
q = deque([(0x6820C, 0)])
while q:
    fn, depth = q.popleft()
    if depth > 6: continue
    callers = callers_of_fn.get(fn, set())
    indent = "  " * (depth + 1)
    name = NAMED.get(fn, f"fn@{fn:#x}")
    if fn in LIVE_ROOTS:
        print(f"{indent}>>> LIVE ROOT REACHED: {name} <<<")
    if not callers:
        print(f"{indent}{name}: NO CALLERS (root)")
        continue
    for c in sorted(callers):
        if c in seen: continue
        seen.add(c)
        cname = NAMED.get(c, f"fn@{c:#x}")
        marker = ""
        if c in LIVE_ROOTS: marker = " ★ LIVE"
        elif c in DEAD_ROOTS: marker = " ✗ DEAD"
        print(f"{indent}{name} ← {cname}{marker}")
        q.append((c, depth + 1))


# ============== (5) BFS for fn@0x142E0 directly ==============
print("\n\n=== (5) BFS-climb from fn@0x142E0 (0x48080 writer) ===")
seen = set([0x142E0])
q = deque([(0x142E0, 0)])
while q:
    fn, depth = q.popleft()
    if depth > 8: continue
    callers = callers_of_fn.get(fn, set())
    indent = "  " * (depth + 1)
    name = NAMED.get(fn, f"fn@{fn:#x}")
    if fn in LIVE_ROOTS:
        print(f"{indent}>>> LIVE ROOT REACHED: {name} <<<")
    if not callers:
        print(f"{indent}{name}: NO CALLERS (root)")
        continue
    for c in sorted(callers):
        if c in seen: continue
        seen.add(c)
        cname = NAMED.get(c, f"fn@{c:#x}")
        marker = ""
        if c in LIVE_ROOTS: marker = " ★ LIVE"
        elif c in DEAD_ROOTS: marker = " ✗ DEAD"
        print(f"{indent}{name} ← {cname}{marker}")
        q.append((c, depth + 1))
