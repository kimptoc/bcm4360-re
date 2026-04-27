"""T299k: dump fn@0x670d8 (real helper inside 0x67358), dump fn@0x67f2c
(second caller of 0x67358), and close the movw/movt construction gap for
wlc_bmac_up_finish (0x17ED6) and the ol_attach string refs.

Per advisor: 'addr constructed via movw rN, #lo + movt rN, #hi' is the gap.
Pair adjacent insns and check if the assembled 32-bit value matches.
"""
import sys, struct, re
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
    0x142E0: "flag_struct_init",
    0x15DA8: "wlc_bmac_up_prep",
    0x17ED6: "wlc_bmac_up_finish",
    0x18FFC: "wlc_up",
    0x11648: "wl_open(dead?)",
    0x6820C: "wlc_bmac_attach",
    0x68A68: "wlc_attach",
    0x67614: "wl_probe",
    0x233E8: "wake_mask_arm",
    0x2340C: "wake_mask_disarm",
    0x2343A: "set_arbitrary_mask",
    0x2312C: "wlc_dpc",
    0x67358: "fn_670d8_wrapper",
    0x670d8: "fn_670d8_helper",
    0x67f2c: "fn_67f2c (other caller of 67358)",
}


def find_fn_start(addr):
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if is_push_lr(ins): last = ins.address
    return last


def find_fn_end(start, max_size=0x800):
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


# ============== (1) DUMP fn@0x670d8 (real helper inside fn@0x67358) ==============
print("=== (1) DUMP fn@0x670d8 (substantive offload-side helper) ===")
dump_fn("fn@0x670d8", 0x670d8, max_lines=300)


# ============== (2) DUMP fn@0x67f2c (second caller of fn@0x67358) ==============
print("\n\n=== (2) DUMP fn@0x67f2c (other caller of 0x67358) ===")
dump_fn("fn@0x67f2c", 0x67f2c, max_lines=200)


# ============== (3) Callers of wlc_attach (0x68A68) — is THIS the dispatch entry? ==============
print("\n\n=== (3) Callers of fn@0x68A68 (wlc_attach) ===")
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x68A68: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        fn = find_fn_start(ins.address)
        print(f"  {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}")
needle = struct.pack("<I", 0x68A69)
pos = 0; hits = []
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x68A69) any alignment: {len(hits)}")
for h in hits[:6]:
    print(f"    {h:#x} aligned={h%4==0}")


# ============== (4) movw/movt construction of fn@0x17ED6 / 0x17ED7 ==============
print("\n\n=== (4) movw/movt pair construction targeting wlc_bmac_up_finish ===")
# Pair adjacent movw + movt (within ~16 bytes) writing to same Rd
movw_re = re.compile(r"^(r\d+|sb|sl|fp|ip|lr),\s*#(0x[\da-fA-F]+|\d+)")
def parse_movw_movt(ins):
    """Return (Rd, imm) if matches movw/movt, else None."""
    if ins.mnemonic not in ("movw", "movt"): return None
    m = movw_re.match(ins.op_str)
    if not m: return None
    rd = m.group(1)
    imm_s = m.group(2)
    imm = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
    return (rd, imm, ins.mnemonic)

pairs = []
prev_movw = {}  # Rd -> (addr, lo)
for ins in all_ins:
    p = parse_movw_movt(ins)
    if p:
        rd, imm, kind = p
        if kind == "movw":
            prev_movw[rd] = (ins.address, imm)
        elif kind == "movt":
            if rd in prev_movw:
                addr_lo, lo = prev_movw[rd]
                if ins.address - addr_lo <= 16:
                    val = (imm << 16) | lo
                    pairs.append((addr_lo, ins.address, rd, val))
                    del prev_movw[rd]

print(f"  Total movw/movt pairs found: {len(pairs)}")
# Check for any pair constructing 0x17ED6 / 0x17ED7
TARGETS = {0x17ED6: "wlc_bmac_up_finish", 0x17ED7: "wlc_bmac_up_finish ptr",
           0x18FFC: "wlc_up", 0x18FFD: "wlc_up ptr",
           0x68A68: "wlc_attach", 0x68A69: "wlc_attach ptr",
           0x6820C: "wlc_bmac_attach", 0x6820D: "wlc_bmac_attach ptr",
           0x15DA8: "wlc_bmac_up_prep", 0x15DA9: "wlc_bmac_up_prep ptr"}
for addr_lo, addr_hi, rd, val in pairs:
    if val in TARGETS:
        fn = find_fn_start(addr_lo)
        print(f"  HIT: movw/movt @ {addr_lo:#x}/{addr_hi:#x} {rd}={val:#x} ({TARGETS[val]})  inside fn@{hex(fn) if fn else '?'}")


# ============== (5) Summary: distribution of movw/movt-constructed values ==============
print("\n  Top constructed values in [0x10000..0x7FFFF] (code region):")
from collections import Counter
codeval_pairs = [p for p in pairs if 0x10000 <= p[3] <= 0x7FFFF]
val_counts = Counter(p[3] for p in codeval_pairs)
for v, c in val_counts.most_common(20):
    name = NAMED.get(v if not (v & 1) else v - 1, "")
    print(f"    {v:#x}: {c} times {('= ' + name) if name else ''}")


# ============== (6) movw/movt construction of ol_attach string addresses ==============
print("\n\n=== (6) movw/movt construction of ol_attach / bmac_up_finish string addrs ===")
STR_TARGETS = {0x50f12: "ol_attach", 0x56f3a: "ol_attach", 0x57c0d: "ol_attach",
               0x58997: "ol_attach", 0x57c62: "ol_init", 0x4af3c: "bmac_up_prep",
               0x4b1f0: "bmac_up_finish", 0x4c774: "ol_attach() failed.",
               0x4d15b: "ol_attach failed", 0x4d1a0: "ol_attach failed"}
for addr_lo, addr_hi, rd, val in pairs:
    if val in STR_TARGETS:
        fn = find_fn_start(addr_lo)
        print(f"  HIT: movw/movt @ {addr_lo:#x}/{addr_hi:#x} {rd}={val:#x} ({STR_TARGETS[val]})  inside fn@{hex(fn) if fn else '?'}")
