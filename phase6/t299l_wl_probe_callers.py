"""T299l: who calls wl_probe (fn@0x67614)? wlc_attach has a single caller
inside wl_probe. So if wl_probe itself has no callers (or only dead ones),
the entire wlc_attach → wlc_bmac_attach → flag_struct_init → wlc_up →
wlc_bmac_up_finish chain is reachable only from a dead entry point.

Also dump wl_probe body and look for refs to its address (fn-ptr table).
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
    0x67358: "si_doattach_wrapper",
    0x670d8: "si_doattach",
    0x67f2c: "si_doattach alt-entry",
    0x1c74:  "pciedngl_open",
    0x1e90:  "pciedngl_probe",
    0x1c98:  "pciedngl_isr",
    0x2f18:  "bcm_olmsg_init",
}


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


def dump_fn(name, start, end=None, max_lines=300):
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


# ============== (1) ALL callers of wl_probe (fn@0x67614) ==============
print("=== (1) ALL callers of wl_probe (fn@0x67614) ===")
direct = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x67614: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        direct.append(ins)
print(f"  Direct bl/b: {len(direct)}")
for ins in direct:
    fn = find_fn_start(ins.address)
    print(f"    {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}")

# fn-ptr table refs (any alignment, exact 0x67615)
needle = struct.pack("<I", 0x67615)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x67615) any alignment: {len(hits)}")
for h in hits[:8]:
    aligned = h % 4 == 0
    ctx_start = max(0, h - 16)
    ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
    print(f"    {h:#x} aligned={aligned}  ctx@{ctx_start:#x}: {ctx}")


# ============== (2) Dump wl_probe body (the entry that calls wlc_attach) ==============
print("\n\n=== (2) DUMP wl_probe (fn@0x67614) ===")
dump_fn("wl_probe", 0x67614, max_lines=100)


# ============== (3) The 0x58F1C handlers table (T299g found 0 readers).
#   Look at it and the surrounding 0x58F00 wrapper for fn-ptrs to wl_probe / wl_open ==============
print("\n\n=== (3) Handlers table @ 0x58F1C ± and 0x58F00 wrapper ===")
for off in range(0x58F00, 0x58F40, 4):
    val = struct.unpack_from('<I', data, off)[0]
    name = ""
    if val & 1:
        target = val - 1
        if target in NAMED: name = f" → {NAMED[target]}"
        else:
            # Try to find the surrounding fn-name via printf
            name = f" → fn@{target:#x}?"
    print(f"  {off:#x}: {val:#010x}{name}")


# ============== (4) Find ALL fn-ptr-style 32-bit values in [0x67000..0x68FFF] (the wl_* fn area) ==============
print("\n\n=== (4) Look for fn-ptrs to 0x67615 / 0x67613 / 0x68A69 in the blob (any alignment) ===")
for tname, tval in [("wl_probe ptr", 0x67615), ("wlc_attach ptr", 0x68A69),
                     ("wlc_bmac_attach ptr", 0x6820D)]:
    needle = struct.pack("<I", tval)
    hits = []; pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    print(f"  {tname} ({tval:#x}): {len(hits)} byte hits")
    for h in hits[:6]:
        print(f"    {h:#x} aligned={h%4==0}")


# ============== (5) Check what wl_open string is in the blob — and its single caller chain ==============
print("\n\n=== (5) Strings 'wl_open' / 'wl_probe' / 'wl_attach' / 'wlc_attach' / 'bmac_attach' ===")
for needle in (b"wl_open\0", b"wl_probe\0", b"wl_attach\0", b"wlc_attach\0",
               b"bmac_attach\0", b"wl_init\0", b"wlc_bmac_attach\0"):
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        print(f"  '{needle.decode().rstrip(chr(0))}' at file offset {idx:#x}")
        pos = idx + 1


# ============== (6) Is wl_probe identified by string ref? Find ldr-loads of "wl_probe" string ==============
print("\n\n=== (6) ldr-refs to 'wl_probe' / 'wl_open' / 'wlc_attach' / 'bmac_attach' strings ===")
for sname_bytes in (b"wl_probe\0", b"wl_open\0", b"wlc_attach\0", b"wl_attach\0", b"bmac_attach\0"):
    pos = 0
    while True:
        idx = data.find(sname_bytes, pos)
        if idx < 0: break
        ref_addrs = []
        for ins in all_ins:
            if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if 0 <= la <= len(data) - 4:
                    val = struct.unpack_from('<I', data, la)[0]
                    if val == idx:
                        ref_addrs.append(ins.address)
            except: pass
        sn = sname_bytes.decode().rstrip("\0")
        if ref_addrs:
            print(f"  '{sn}' @ {idx:#x}: {len(ref_addrs)} refs at {[hex(a) for a in ref_addrs[:6]]}")
            for r in ref_addrs[:3]:
                fn = find_fn_start(r)
                print(f"      ref {r:#x} inside fn@{hex(fn) if fn else '?'}")
        else:
            print(f"  '{sn}' @ {idx:#x}: NO ldr refs")
        pos = idx + 1
