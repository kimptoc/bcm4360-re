"""T299q: trace the firmware's true entry point at fn@0x268.

Reset handler at 0x20 → bx r0 where r0 = 0x269 (Thumb). So fn@0x268 is the
real C main equivalent. Trace it: what does it call? Does it reach wl_probe,
the handlers table 0x58F1C, or pciedngl_probe?

Also: properly disasm starting at 0x4718 (leaf fn) — the function wl_probe
passes fn-ptrs to. Determine if it invokes them.
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
    0x142E0: "fn@0x142E0 (writes 0x48080)",
    0x15DA8: "wlc_bmac_up_prep",
    0x17ED6: "wlc_bmac_up_finish",
    0x18FFC: "wlc_up",
    0x11648: "wl_open(dead?)",
    0x6820C: "wlc_bmac_attach(dead?)",
    0x68A68: "wlc_attach(dead?)",
    0x67614: "wl_probe(dead?)",
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
    0x4718:  "fn@0x4718 (wl_probe arg)",
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


def annot_for_pc(addr, mnem, op):
    a = ""
    if mnem.startswith("ldr") and "[pc," in op:
        try:
            imm_s = op.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((addr + 4) & ~3) + imm
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
    elif mnem == "bl" and "#0x" in op:
        try:
            t = int(op.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  → {NAMED[t]}"
            else: a = f"  → fn@{t:#x}"
        except: pass
    elif mnem in ("b", "b.w") and "#0x" in op:
        try:
            t = int(op.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  >>> TAIL→{NAMED[t]} <<<"
            else: a = f"  → tail-fn@{t:#x}"
        except: pass
    elif mnem == "blx" and op.strip().startswith("r"):
        a = f"  → INDIRECT via {op.strip()}"
    return a


def dump_at(start, max_lines=80, label=None):
    if label: print(f"\n=========== {label}  starting at {start:#x} ===========")
    chunk = data[start:start + 0x300]
    n = 0
    for ins in md.disasm(chunk, start):
        a = annot_for_pc(ins.address, ins.mnemonic, ins.op_str)
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
        n += 1
        if n >= max_lines:
            print(f"  ... TRUNCATED at {max_lines} lines")
            break
        if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end pop pc]"); break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end bx lr]"); break


# ============== (1) Trace fn@0x268 — the real entry point ==============
print("=== (1) DUMP fn@0x268 (firmware's true entry point per reset vector) ===")
dump_at(0x268, max_lines=120, label="fn@0x268 (true entry from reset)")


# ============== (2) Properly dump fn@0x4718 (leaf, no push lr) ==============
print("\n\n=== (2) DUMP fn@0x4718 directly (leaf — no push lr) ===")
dump_at(0x4718, max_lines=60, label="fn@0x4718")


# ============== (3) Trace ALL bl/b targets reachable from fn@0x268 to depth 4 ==============
print("\n\n=== (3) Reachable callees from fn@0x268 (BFS depth 4) ===")
# Build a mini-callgraph by scanning each fn fully
def disasm_from(start, max_size=0x600):
    out = []
    chunk = data[start:start + max_size]
    n = 0
    for ins in md.disasm(chunk, start):
        out.append(ins)
        n += 1
        if n > 200: break
        if ins.mnemonic == "pop" and "pc" in ins.op_str: break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": break
    return out

from collections import deque
seen = set([0x268])
q = deque([(0x268, 0)])
calls_from = {}
while q:
    fn, depth = q.popleft()
    if depth >= 4: continue
    if fn not in calls_from:
        calls_from[fn] = set()
        for ins in disasm_from(fn):
            if ins.mnemonic in ("bl", "blx", "b", "b.w") and "#0x" in ins.op_str:
                try:
                    t = int(ins.op_str.lstrip("#").strip(), 16)
                    calls_from[fn].add(t)
                except: pass
    for t in sorted(calls_from[fn]):
        if t in seen: continue
        seen.add(t)
        q.append((t, depth + 1))

# Print: did we reach any of the key targets?
KEY_TARGETS = {0x67614: "wl_probe", 0x68A68: "wlc_attach", 0x6820C: "wlc_bmac_attach",
               0x142E0: "0x48080-writer", 0x11704: "init-shim → 142E0",
               0x1e90: "pciedngl_probe", 0x1c98: "pciedngl_isr",
               0x18FFC: "wlc_up", 0x17ED6: "wlc_bmac_up_finish",
               0x11648: "wl_open", 0x67358: "si_doattach_wrapper",
               0x2f18: "bcm_olmsg_init", 0x11790: "wrap_ARM"}
print("Reached fns: total", len(seen))
print("Key targets reached:")
for t, name in sorted(KEY_TARGETS.items()):
    reached = t in seen
    print(f"  {t:#x} ({name}): {'★ REACHED' if reached else 'not reached'}")

# Show first 20 reached fns
print("\nFirst 30 reached fns (sorted):")
for fn in sorted(seen)[:30]:
    name = NAMED.get(fn, "")
    print(f"  fn@{fn:#x}{(' = '+name) if name else ''}")
