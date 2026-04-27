"""T299r: trace fn@0x2408 (the real C main) with BFS that follows bx-via-
literal-pool. Also: who are the consumers of [state+0x4c] (the fn-ptr stored
by fn@0x4718)?

The bootstrap at fn@0x268 jumps to fn@0x2408 via `ldr r4, =0x2409; bx r4`
which is the indirect call my prior BFS missed.

BFS rules (expanded):
- bl/blx #imm: direct call → follow to target
- b/b.w #imm: tail call → follow
- bx Rn / blx Rn: if a near-prior `ldr Rn, [pc, #imm]` set Rn to a code
  literal (odd, in code range), follow that target
- pop {..., pc} after `ldr Rn, [pc, #imm]; mov pc, Rn`: same idea
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


NAMED = {
    0x9990:  "si_setcoreidx",
    0x11790: "wrap_ARM",
    0x142E0: "0x48080-writer",
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
    0x11704: "init-shim → 142E0",
    0x4718:  "set_callback (state, fn_ptr, arg)",
    0x2408:  "real C main",
    0x268:   "bootstrap",
}


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
    elif ins.mnemonic in ("bx", "blx") and ins.op_str.strip().startswith("r"):
        a = f"  → INDIRECT via {ins.op_str.strip()}"
    return a


def disasm_from(start, max_size=0x800):
    """Return list of insns starting at start, stopping at function exit."""
    out = []
    chunk = data[start:start + max_size]
    n = 0
    for ins in md.disasm(chunk, start):
        out.append(ins)
        n += 1
        if n > 250: break
        if ins.mnemonic == "pop" and "pc" in ins.op_str: break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": break
    return out


# ============== (1) Dump fn@0x2408 — the real main ==============
print("=== (1) DUMP fn@0x2408 (real C main, lr=0x320 fault on return) ===")
chunk = data[0x2408:0x2408 + 0x600]
n = 0
for ins in md.disasm(chunk, 0x2408):
    a = annot(ins)
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    n += 1
    if n >= 250:
        print(f"  ... TRUNCATED at {n} lines")
        break
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end pop pc]"); break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end bx lr]"); break


# ============== (2) BFS from fn@0x2408 with bx-via-pool tracking ==============
print("\n\n=== (2) BFS from fn@0x2408 (with bx-via-literal-pool tracking) ===")

def fn_targets(start):
    """Return set of (target, kind) pairs from fn at start.
    kind in {direct, indirect_pool, indirect_unknown}."""
    insns = disasm_from(start, max_size=0x800)
    targets = set()
    # Track simple register defs from pc-rel ldr (last write per reg, within fn)
    reg_lit = {}  # reg name -> (addr, val) of last ldr [pc,#imm]
    for ins in insns:
        # Track ldr Rn, [pc, #imm]
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                rd = ins.op_str.split(",")[0].strip()
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if 0 <= la <= len(data) - 4:
                    val = struct.unpack_from('<I', data, la)[0]
                    reg_lit[rd] = val
            except: pass
        elif ins.mnemonic == "mov":
            # mov rd, rs — if rs has a literal, propagate
            try:
                parts = [p.strip() for p in ins.op_str.split(",")]
                if len(parts) == 2 and parts[1] in reg_lit:
                    reg_lit[parts[0]] = reg_lit[parts[1]]
            except: pass
        elif ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                targets.add((t, "direct"))
            except: pass
        elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                targets.add((t, "tail"))
            except: pass
        elif ins.mnemonic in ("bx", "blx") and ins.op_str.strip().startswith("r"):
            r = ins.op_str.strip()
            if r in reg_lit:
                val = reg_lit[r]
                if val & 1 and 0x100 < val < len(data):
                    targets.add((val - 1, "indirect_pool"))
                else:
                    targets.add((val, "indirect_pool_data"))
            else:
                targets.add((-1, "indirect_unknown"))
    return targets


KEY_TARGETS = {0x67614: "wl_probe", 0x68A68: "wlc_attach", 0x6820C: "wlc_bmac_attach",
               0x142E0: "0x48080-writer", 0x11704: "init-shim → 142E0",
               0x1e90: "pciedngl_probe", 0x1c98: "pciedngl_isr",
               0x18FFC: "wlc_up", 0x17ED6: "wlc_bmac_up_finish",
               0x11648: "wl_open", 0x67358: "si_doattach_wrapper",
               0x2f18: "bcm_olmsg_init", 0x11790: "wrap_ARM",
               0x68a68: "wlc_attach"}

from collections import deque
seen = set([0x2408])
parent = {}  # child_fn -> (parent_fn, kind)
q = deque([(0x2408, 0)])
while q:
    fn, depth = q.popleft()
    if depth >= 8: continue
    if fn < 0 or fn >= len(data): continue
    targets = fn_targets(fn)
    for t, kind in targets:
        if t < 0: continue
        if t in seen: continue
        seen.add(t)
        parent[t] = (fn, kind)
        q.append((t, depth + 1))

print(f"Reached fns: {len(seen)}")
print("\nKey targets reached + path:")
for t, name in sorted(KEY_TARGETS.items()):
    if t in seen:
        # reconstruct path
        path = [t]
        cur = t
        while cur in parent:
            cur, _ = parent[cur]
            path.append(cur)
        path.reverse()
        path_s = " → ".join(NAMED.get(p, f"fn@{p:#x}") for p in path)
        print(f"  ★ REACHED {t:#x} ({name})")
        print(f"    path: {path_s}")
    else:
        print(f"  not reached: {t:#x} ({name})")


# ============== (3) Look for `ldr r4, =0x67615` or any ldr loading wl_probe ptr followed by bx ==============
print("\n\n=== (3) Search for ldr-from-pool of wl_probe-ptr (0x67615) followed by bx ===")
print("  (only ldr-pool location of 0x67615 is at file offset 0x58F1C — handlers table)")
# Find any ldr [pc, #imm] where lit val == 0x67615
loaders = []
all_ins = []
pos = 0
while pos < len(data) - 2:
    emitted = False
    for ins in md.disasm(data[pos:], pos):
        all_ins.append(ins)
        emitted = True
        last_end = ins.address + ins.size
        if last_end >= len(data) - 2: break
    if not emitted:
        pos += 2
    else:
        pos = last_end
print(f"  Total ins disasm'd: {len(all_ins):,}")

for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x67615:
                loaders.append(ins)
    except: pass
print(f"  ldr-loaders for 0x67615: {len(loaders)}")
for ins in loaders:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# ============== (4) Look for ldr-from-literal-pool of pciedngl_probe-ptr (0x1e91) too ==============
print("\n\n=== (4) Find ldr-from-pool of pciedngl_probe-ptr (0x1e91) ===")
# 0x1e91 byte hits:
needle = struct.pack("<I", 0x1e91)
pos = 0
hits = []
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  byte hits: {len(hits)}")
for h in hits[:8]:
    print(f"    {h:#x} aligned={h%4==0}")
loaders = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x1e91:
                loaders.append(ins)
    except: pass
print(f"  ldr-loaders for 0x1e91: {len(loaders)}")
for ins in loaders:
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
