"""T299j: trace fn@0x67358 (the substantive call inside pciedngl_probe), map
ol_attach/ol_init printf strings to fns, and look for indirect/tagged refs to
wlc_bmac_up_finish (0x17ED6) that my direct bl scan would miss.

Per advisor: 0-callers on wlc_bmac_up_finish is suspicious. Possibilities:
  - blx rN where rN loaded from a struct field
  - addr built via add rN, pc, #imm or split mov/add
  - reached via fn-name table where stored value != 0x17ED7 exactly (tagged)
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
    0x11790: "wrap_ARM (set wake mask 0x48080)",
    0x142E0: "flag_struct init",
    0x15DA8: "wlc_bmac_up_prep",
    0x17ED6: "wlc_bmac_up_finish",
    0x18FFC: "wlc_up",
    0x11648: "wl_open (FullMAC dead?)",
    0x6820C: "wlc_bmac_attach",
    0x68A68: "wlc_attach",
    0x67614: "wl_probe",
    0x233E8: "wake-mask ARM impl (0x48080→D11+0x16C)",
    0x2340C: "wake-mask DISARM impl",
    0x2343A: "set-arbitrary-mask impl",
    0x2312C: "wlc_dpc",
}

INTERESTING_FN_TARGETS = set(NAMED.keys()) | {0x67358}


def find_fn_start(addr):
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if is_push_lr(ins): last = ins.address
    return last


def find_fn_end(start, max_size=0x1000):
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


def dump_fn(name, start, end=None, max_lines=400):
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


# ============== (1) DUMP fn@0x67358 (the substantive call inside pciedngl_probe) ==============
print("=== (1) DUMP fn@0x67358 (called from pciedngl_probe @ 0x1ee8) ===")
dump_fn("fn@0x67358 (offload-mode device-attach?)", 0x67358, max_lines=400)


# ============== (2) Map ol_attach/ol_init printf strings to their containing fns ==============
print("\n\n=== (2) Map ol_attach / ol_init / olmsg_*_up printf strings to fns ===")
TARGET_STRS = [
    (0x50f12, "ol_attach"),
    (0x56f3a, "ol_attach"),
    (0x57c0d, "ol_attach"),
    (0x58997, "ol_attach"),
    (0x57c62, "ol_init"),
    (0x4c774, "ol_attach() failed."),
    (0x4d15b, "ol_attach failed"),
    (0x4d1a0, "ol_attach failed"),
    (0x4c64a, "offload attach FAILED (err %d)"),
    (0x4c673, "offload attach FAILED (err %d)"),
    (0x4af3c, "bmac_up_prep"),
    (0x4b1f0, "bmac_up_finish"),
    (0x40685, "pciedngl_isr"),
    (0x407f2, "pciedngl_probe"),
]
results_by_fn = {}
for off, name in TARGET_STRS:
    refs = []
    for ins in all_ins:
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == off:
                    refs.append(ins.address)
        except: pass
    if not refs:
        print(f"  '{name}' @ {off:#x}: NO ldr refs")
        continue
    for r in refs:
        fn = find_fn_start(r)
        print(f"  '{name}' @ {off:#x} → ref @ {r:#x}  inside fn@{hex(fn) if fn else '?'}")
        if fn: results_by_fn.setdefault(fn, []).append((name, r))


# ============== (3) Indirect/tagged ref scan for wlc_bmac_up_finish (0x17ED6) ==============
print("\n\n=== (3) Indirect/tagged ref scan for fn@0x17ED6 (wlc_bmac_up_finish) ===")

print("  (a) Aligned 4B literal-pool occurrences of EXACT 0x17ED6 / 0x17ED7:")
for target in (0x17ED6, 0x17ED7):
    needle = struct.pack("<I", target)
    pos = 0
    hits = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    print(f"    val={target:#x}: {len(hits)} hits")
    for h in hits[:6]:
        print(f"      {h:#x} aligned={h%4==0}")

print("\n  (b) Tagged/off-by-N: any 4B word in [0x17EA0..0x17F40] anywhere in blob:")
hits_tagged = []
for off in range(0, len(data) - 4, 2):
    val = struct.unpack_from('<I', data, off)[0]
    if 0x17EA0 <= val <= 0x17F40:
        hits_tagged.append((off, val))
print(f"    Hits (any alignment): {len(hits_tagged)}")
# Group by val to find any patterns
from collections import Counter
val_counts = Counter(v for _, v in hits_tagged)
for v, c in val_counts.most_common(10):
    print(f"    val={v:#x}: {c} occurrences")
# Show first 12 occurrences with offset context
for off, val in hits_tagged[:24]:
    print(f"      off={off:#x} val={val:#x}  aligned={off%4==0}")

print("\n  (c) PC-relative add/adr targeting 0x17ED6 area:")
# add r, pc, #imm in Thumb usually means literal-pool-style. Look for 'adr' too.
hits_pc = []
for ins in all_ins:
    if ins.mnemonic in ("adr", "add"):
        try:
            # Look at op_str — adr Rn, #imm
            if ins.mnemonic == "adr" and "#" in ins.op_str:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
                target = ((ins.address + 4) & ~3) + imm
                if 0x17EA0 <= target <= 0x17F40:
                    hits_pc.append((ins.address, ins.mnemonic, ins.op_str, target))
        except: pass
print(f"    adr-near-target hits: {len(hits_pc)}")
for a, m, op, t in hits_pc[:8]:
    print(f"      {a:#x}: {m} {op} → {t:#x}")


# ============== (4) Same scan for wlc_up (0x18FFC) — supplements direct-caller scan ==============
print("\n\n=== (4) Indirect ref scan for fn@0x18FFC (wlc_up) ===")
print("  (a) Aligned 4B literal-pool occurrences of EXACT 0x18FFC / 0x18FFD:")
for target in (0x18FFC, 0x18FFD):
    needle = struct.pack("<I", target)
    pos = 0
    hits = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    print(f"    val={target:#x}: {len(hits)} hits")
    for h in hits[:6]:
        print(f"      {h:#x} aligned={h%4==0}")

print("\n  (b) Tagged: any 4B word in [0x18FE0..0x19040]:")
hits_tagged = []
for off in range(0, len(data) - 4, 2):
    val = struct.unpack_from('<I', data, off)[0]
    if 0x18FE0 <= val <= 0x19040:
        hits_tagged.append((off, val))
val_counts = Counter(v for _, v in hits_tagged)
for v, c in val_counts.most_common(10):
    print(f"    val={v:#x}: {c} occurrences")


# ============== (5) Bonus: dump fn@0x67358 callers — does any other fn call it? ==============
print("\n\n=== (5) Callers of fn@0x67358 (sanity: should be from pciedngl_probe + maybe more) ===")
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x67358: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        fn = find_fn_start(ins.address)
        print(f"  {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}")
needle = struct.pack("<I", 0x67359)
pos = 0; hits = []
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x67359) any alignment: {len(hits)}")
for h in hits[:8]:
    print(f"    {h:#x} aligned={h%4==0}")
