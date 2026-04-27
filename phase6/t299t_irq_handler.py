"""T299t: trace ARM exception handlers — IRQ at 0xf8, FIQ at 0x118.

Per advisor: in event-driven firmware, wifi is reached via IRQ, not via
main's BFS. The IRQ handler typically reads a ChipIntStatus register and
indexes into a handler table.

Probe:
1. Dump fn@0xf8 (IRQ) and fn@0x118 (FIQ) — what registers do they read,
   what do they dispatch to?
2. BFS from fn@0xf8 with bx-via-pool tracking; check if it reaches
   wlc_dpc, wrap_ARM, fn@0x142E0, pciedngl_isr.
3. If IRQ reads ChipIntStatus (0x18000020 or 0x180000XX), find the
   table it indexes into.
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
    0x2f18:  "bcm_olmsg_init",
    0x11704: "init-shim → 142E0",
    0x4718:  "set_callback",
    0x2408:  "real C main",
    0x268:   "bootstrap",
    0x2312C: "wlc_dpc",
    0x113b4: "ACTION dispatcher",
    0x233E8: "wake-mask ARM impl",
    0xf8:    "IRQ handler",
    0x118:   "FIQ handler",
    0x20:    "Reset handler",
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
    elif ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
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


# ============== (1) Dump IRQ + FIQ handlers ==============
print("=== (1) Dump exception handlers ===\n")
for name, addr in [("IRQ handler", 0xf8), ("FIQ handler", 0x118),
                    ("undef handler", 0x64), ("SVC handler", 0x7e),
                    ("prefetch_abort", 0x98), ("data_abort", 0xb8),
                    ("? handler", 0xd8)]:
    print(f"\n=========== {name} @ {addr:#x} ===========")
    chunk = data[addr:addr + 0x80]
    n = 0
    for ins in md.disasm(chunk, addr):
        a = annot(ins)
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
        n += 1
        if n > 30: print("  ..."); break
        # Stop at next handler boundary (the next vector entry)
        if (ins.address + ins.size) >= addr + 0x40:
            print(f"  --- (boundary at {addr + 0x40:#x}) ---")
            break


# ============== (2) BFS from fn@0xf8 with bx-via-pool tracking ==============
print("\n\n=== (2) BFS from fn@0xf8 (IRQ) with indirect tracking ===")

def fn_targets(start):
    insns = disasm_from(start)
    direct = set()
    indirect = []
    reg_lit = {}
    reg_load = {}
    for ins in insns:
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
        elif ins.mnemonic.startswith("ldr") and "[" in ins.op_str:
            try:
                parts = ins.op_str.split(",", 1)
                rd = parts[0].strip()
                rest = parts[1].strip().lstrip("[").rstrip("]")
                inner = [p.strip() for p in rest.split(",")]
                rn = inner[0]
                ofs = 0
                if len(inner) > 1:
                    ofs_s = inner[1].lstrip("#").strip()
                    if ofs_s.startswith("0x"): ofs = int(ofs_s, 16)
                    elif ofs_s.lstrip("-").isdigit(): ofs = int(ofs_s)
                reg_load[rd] = f"[{rn}, #{ofs:#x}]"
                reg_lit.pop(rd, None)
            except: pass
        elif ins.mnemonic == "mov":
            try:
                parts = [p.strip() for p in ins.op_str.split(",")]
                if len(parts) == 2:
                    rd, rs = parts
                    if rs in reg_lit: reg_lit[rd] = reg_lit[rs]
                    if rs in reg_load: reg_load[rd] = reg_load[rs]
            except: pass
        elif ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                direct.add(t)
            except: pass
        elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                direct.add(t)
            except: pass
        elif ins.mnemonic in ("bx", "blx") and ins.op_str.strip().startswith("r"):
            r = ins.op_str.strip()
            if r in reg_lit:
                val = reg_lit[r]
                if val & 1 and 0x100 < val < len(data):
                    direct.add(val - 1)
            elif r in reg_load:
                indirect.append((ins.address, r, reg_load[r]))
            else:
                indirect.append((ins.address, r, "unknown"))
    return direct, indirect


KEY_TARGETS = {0x67614: "wl_probe", 0x68A68: "wlc_attach", 0x6820C: "wlc_bmac_attach",
               0x142E0: "0x48080-writer", 0x11704: "init-shim → 142E0",
               0x1e90: "pciedngl_probe", 0x1c98: "pciedngl_isr",
               0x18FFC: "wlc_up", 0x17ED6: "wlc_bmac_up_finish",
               0x11648: "wl_open", 0x67358: "si_doattach_wrapper",
               0x2f18: "bcm_olmsg_init", 0x11790: "wrap_ARM",
               0x2312C: "wlc_dpc", 0x113b4: "ACTION dispatcher",
               0x233E8: "wake-mask ARM impl",
               0x4718: "set_callback"}

from collections import deque
seen = set([0xf8])
parent = {}
q = deque([(0xf8, 0)])
indirect_calls = []
while q:
    fn, depth = q.popleft()
    if depth >= 12: continue
    if fn < 0 or fn >= len(data): continue
    direct, indir = fn_targets(fn)
    for s in indir:
        indirect_calls.append((fn,) + s)
    for t in sorted(direct):
        if t < 0 or t >= len(data): continue
        if t in seen: continue
        seen.add(t)
        parent[t] = fn
        q.append((t, depth + 1))

print(f"Reached fns from IRQ@0xf8 BFS: {len(seen)}")
print(f"\nKey targets reached from IRQ:")
for t, name in sorted(KEY_TARGETS.items()):
    if t in seen:
        path = [t]; cur = t
        while cur in parent:
            cur = parent[cur]; path.append(cur)
            if len(path) > 12: break
        path.reverse()
        path_s = " → ".join(NAMED.get(p, f"fn@{p:#x}") for p in path)
        print(f"  ★ {t:#x} ({name})")
        print(f"      path: {path_s}")
    else:
        print(f"  ✗ {t:#x} ({name})")

print(f"\nIndirect-via-struct call sites in IRQ BFS: {len(indirect_calls)}")
for fn, ia, r, src in indirect_calls[:20]:
    print(f"  in fn@{fn:#x}: blx {r} from {src} at {ia:#x}")


# ============== (3) Same BFS from FIQ handler ==============
print("\n\n=== (3) BFS from fn@0x118 (FIQ) ===")
seen2 = set([0x118])
parent2 = {}
q = deque([(0x118, 0)])
while q:
    fn, depth = q.popleft()
    if depth >= 12: continue
    if fn < 0 or fn >= len(data): continue
    direct, _ = fn_targets(fn)
    for t in sorted(direct):
        if t < 0 or t >= len(data): continue
        if t in seen2: continue
        seen2.add(t)
        parent2[t] = fn
        q.append((t, depth + 1))
print(f"Reached fns from FIQ@0x118: {len(seen2)}")
print(f"\nKey targets reached from FIQ:")
for t, name in sorted(KEY_TARGETS.items()):
    if t in seen2:
        path = [t]; cur = t
        while cur in parent2:
            cur = parent2[cur]; path.append(cur)
            if len(path) > 12: break
        path.reverse()
        path_s = " → ".join(NAMED.get(p, f"fn@{p:#x}") for p in path)
        print(f"  ★ {t:#x} ({name})")
        print(f"      path: {path_s}")


# ============== (4) Combined: ALL exception handlers' BFS reach set ==============
print("\n\n=== (4) Combined live-reach across reset+IRQ+FIQ+ALL exceptions ===")
all_seen = set()
all_seen.update(seen)
all_seen.update(seen2)
# Also include the reset BFS's reachable set (do it again here)
seen_r = set([0x268])
q = deque([(0x268, 0)])
while q:
    fn, depth = q.popleft()
    if depth >= 12: continue
    if fn < 0 or fn >= len(data): continue
    direct, _ = fn_targets(fn)
    for t in sorted(direct):
        if t < 0 or t >= len(data): continue
        if t in seen_r: continue
        seen_r.add(t)
        q.append((t, depth + 1))
all_seen.update(seen_r)
# Also: undef, SVC, prefetch_abort, data_abort, ?
for entry in (0x64, 0x7e, 0x98, 0xb8, 0xd8):
    seen_e = set([entry])
    q = deque([(entry, 0)])
    while q:
        fn, depth = q.popleft()
        if depth >= 6: continue
        if fn < 0 or fn >= len(data): continue
        direct, _ = fn_targets(fn)
        for t in sorted(direct):
            if t < 0 or t >= len(data): continue
            if t in seen_e: continue
            seen_e.add(t)
            q.append((t, depth + 1))
    all_seen.update(seen_e)
print(f"Combined reach (reset+all exceptions): {len(all_seen)} fns")
print(f"\nKey wifi targets in combined reach:")
for t, name in sorted(KEY_TARGETS.items()):
    print(f"  {'★ REACHED' if t in all_seen else '✗ not reached'}: {t:#x} ({name})")
