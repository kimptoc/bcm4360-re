"""T299s: per advisor — three corrections to the BFS:

(1) Start from fn@0x268 (bootstrap) NOT fn@0x2408. fn@0x268 calls 0x4ec,
    0x50c, 0x538, 0x440 BEFORE jumping to main; those are missed.
(2) Expand KEY_TARGETS to include wlc_dpc (0x2312C), fn@0x113b4 (the ACTION
    dispatcher from T298), wake-mask ARM impl (0x233E8).
(3) Detect the common 'ldr rX, [rN, #imm]; blx rX' indirect-call-via-struct
    pattern. Count how many such patterns exist in the live-reachable code.
    These calls have NO static target — but their existence is the gap.

Also: dump fn@0x11d0 (the tail-call from main) and fn@0x440 (called from
bootstrap before main).
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
    0x113b4: "ACTION dispatcher (T298)",
    0x233E8: "wake-mask ARM impl",
    0x11d0:  "fn@0x11d0 (tail from main)",
    0x440:   "fn@0x440 (bootstrap pre-main)",
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


def fn_targets(start):
    """Return tuple (direct_targets, indirect_struct_calls)."""
    insns = disasm_from(start)
    direct = set()
    indirect_struct = []  # list of (addr, base_reg, offset)
    reg_lit = {}  # reg -> last loaded literal value
    reg_load_addr = {}  # reg -> addr/[expr] last loaded from
    for i, ins in enumerate(insns):
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                rd = ins.op_str.split(",")[0].strip()
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if 0 <= la <= len(data) - 4:
                    val = struct.unpack_from('<I', data, la)[0]
                    reg_lit[rd] = val
                    reg_load_addr[rd] = f"pool@{la:#x}={val:#x}"
            except: pass
        elif ins.mnemonic.startswith("ldr") and "[" in ins.op_str:
            # Pattern: ldr rD, [rN, #imm]
            try:
                parts = ins.op_str.split(",", 1)
                rd = parts[0].strip()
                rest = parts[1].strip().lstrip("[").rstrip("]")
                # rest like "rN" or "rN, #imm"
                inner = [p.strip() for p in rest.split(",")]
                rn = inner[0]
                ofs = 0
                if len(inner) > 1:
                    ofs_s = inner[1].lstrip("#").strip()
                    if ofs_s.startswith("0x"): ofs = int(ofs_s, 16)
                    elif ofs_s.lstrip("-").isdigit(): ofs = int(ofs_s)
                # Track rd as "loaded from struct"
                reg_load_addr[rd] = f"[{rn}, #{ofs:#x}]"
                # Clear literal tracking for rd (no longer a literal)
                reg_lit.pop(rd, None)
            except: pass
        elif ins.mnemonic == "mov":
            try:
                parts = [p.strip() for p in ins.op_str.split(",")]
                if len(parts) == 2:
                    rd, rs = parts
                    if rs in reg_lit: reg_lit[rd] = reg_lit[rs]
                    if rs in reg_load_addr: reg_load_addr[rd] = reg_load_addr[rs]
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
            elif r in reg_load_addr:
                indirect_struct.append((ins.address, r, reg_load_addr[r]))
            else:
                indirect_struct.append((ins.address, r, "unknown"))
    return direct, indirect_struct


# ============== (1) BFS from fn@0x268 ==============
print("=== (1) BFS from fn@0x268 (true bootstrap entry) ===")
KEY_TARGETS = {0x67614: "wl_probe", 0x68A68: "wlc_attach", 0x6820C: "wlc_bmac_attach",
               0x142E0: "0x48080-writer", 0x11704: "init-shim → 142E0",
               0x1e90: "pciedngl_probe", 0x1c98: "pciedngl_isr",
               0x18FFC: "wlc_up", 0x17ED6: "wlc_bmac_up_finish",
               0x11648: "wl_open", 0x67358: "si_doattach_wrapper",
               0x2f18: "bcm_olmsg_init", 0x11790: "wrap_ARM",
               0x2312C: "wlc_dpc", 0x113b4: "ACTION dispatcher",
               0x233E8: "wake-mask ARM impl", 0x6820C: "wlc_bmac_attach",
               0x11d0: "fn@0x11d0", 0x440: "fn@0x440",
               0x67358: "si_doattach_wrapper",
               0x66e64: "fn@0x66e64 (alloc?)",
               0x64248: "fn@0x64248",
               0x63c24: "fn@0x63c24 (ISR register?)",
               0x4718: "set_callback"}

from collections import deque
seen = set([0x268])
parent = {}
q = deque([(0x268, 0)])
indirect_calls_total = []  # list of (containing_fn, addr, reg, source)
while q:
    fn, depth = q.popleft()
    if depth >= 12: continue
    if fn < 0 or fn >= len(data): continue
    direct, indirect = fn_targets(fn)
    for (ia, r, src) in indirect:
        indirect_calls_total.append((fn, ia, r, src))
    for t in sorted(direct):
        if t < 0 or t >= len(data): continue
        if t in seen: continue
        seen.add(t)
        parent[t] = fn
        q.append((t, depth + 1))

print(f"Reached fns from fn@0x268 BFS: {len(seen)}")
print(f"\nKey targets reached:")
for t, name in sorted(KEY_TARGETS.items()):
    if t in seen:
        # path
        path = [t]; cur = t
        while cur in parent:
            cur = parent[cur]
            path.append(cur)
            if len(path) > 12: break
        path.reverse()
        path_s = " → ".join(NAMED.get(p, f"fn@{p:#x}") for p in path)
        print(f"  ★ {t:#x} ({name})")
        print(f"      path: {path_s}")
    else:
        print(f"  ✗ NOT reached: {t:#x} ({name})")


# ============== (2) Indirect-via-struct calls in live code ==============
print(f"\n\n=== (2) Indirect 'blx rX' calls where rX loaded from [rN, #imm] (struct field) ===")
print(f"  Total indirect-struct call sites (in live BFS): {len(indirect_calls_total)}")
# Deduplicate by call site
seen_sites = set()
unique_sites = []
for fn, ia, r, src in indirect_calls_total:
    if ia in seen_sites: continue
    seen_sites.add(ia)
    unique_sites.append((fn, ia, r, src))
print(f"  Unique sites: {len(unique_sites)}")
print(f"\n  First 30 indirect call sites:")
for fn, ia, r, src in unique_sites[:30]:
    fn_name = NAMED.get(fn, "")
    print(f"    in fn@{fn:#x}{(' = '+fn_name) if fn_name else ''}: blx {r}  (loaded from {src}) at {ia:#x}")


# ============== (3) Dump fn@0x11d0 and fn@0x440 ==============
def dump_fn(name, start, max_lines=80):
    print(f"\n=========== {name} @ {start:#x} ===========")
    chunk = data[start:start + 0x300]
    n = 0
    for ins in md.disasm(chunk, start):
        a = annot(ins)
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
        n += 1
        if n >= max_lines:
            print(f"  ... TRUNCATED at {max_lines} lines")
            break
        if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end]"); break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end]"); break

print("\n\n=== (3) Dump fn@0x11d0 (tail from main) and fn@0x440 (bootstrap pre-main) ===")
dump_fn("fn@0x11d0 (tail from main)", 0x11d0, max_lines=60)
dump_fn("fn@0x440 (bootstrap, called before main)", 0x440, max_lines=80)


# ============== (4) Search for any code that loads handlers-table base 0x58F00 via struct field ==============
# i.e., look for ldr rX, [rN, #imm] where the value at the source could be 0x58F00
# Simpler: scan all 4-byte aligned words in the binary for value 0x58F00 — already done by T299g (1 hit at 0x58F00 itself)
# But check: does the live BFS reach a function that does a 'ldr rX, [rN, #ofs]' to a struct that
# might have been initialized to 0x58F00 elsewhere? Hard. Best discriminator: does the BFS
# reach fn@0x4718 (which set_callback can store any fn-ptr including wl_probe)?
print("\n\n=== (4) Live-set discriminators ===")
print(f"  fn@0x4718 (set_callback) reached by BFS? {'YES' if 0x4718 in seen else 'no'}")
print(f"  Live set size: {len(seen)}")

# Save list of reached fns to a file for further analysis
with open("/home/kimptoc/bcm4360-re/phase6/t299s_live_set.txt", "w") as f:
    for fn in sorted(seen):
        name = NAMED.get(fn, "")
        f.write(f"{fn:#x}{(' = '+name) if name else ''}\n")
print(f"  Live set written to phase6/t299s_live_set.txt")
