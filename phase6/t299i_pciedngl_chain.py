"""T299i: trace the offload-mode bring-up chain.

T299h proved the offload-mode functions exist:
  pciedngl_probe @ printf 0x407f2 (refs 0x1e9e, 0x1f10) — offload device probe
  pciedngl_open  @ printf 0x40801 (ref  0x1c78)         — offload device open
  pciedngl_isr   @ printf 0x40685 (refs 0x1ca0+)        — offload ISR
  bcm_olmsg_init @ printf 0x41492 (ref  0x2f26)
  bmac_up_prep   @ printf 0x4af3c                       — same fn as wlc_bmac_up_prep?
  bmac_up_finish @ printf 0x4b1f0                       — same fn as wlc_bmac_up_finish?

This probe:
1. Identify the fn containing each of those printf-using insns
2. Dump short body to spot bl into wlc_up (0x18FFC), wlc_bmac_up_prep (0x15DA8),
   wlc_bmac_up_finish (0x17ED6), si_setcoreidx (0x9990), wrap_ARM (0x11790),
   wlc_ol_or fn@0x142E0 init.
3. Verify "bmac_up_finish" string @ 0x4b1f0 is ldr'd inside fn@0x17ED6 (confirms
   that's wlc_bmac_up_finish even in offload build) — and "bmac_up_prep" in 0x15DA8.
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
all_ins_by_addr = {ins.address: ins for ins in all_ins}
print(f"Total: {len(all_ins):,}\n")


def find_fn_start(addr):
    """Find nearest preceding push-lr <= addr."""
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
                    a = f"  ; lit={val:#x} → fn@{val-1:#x}"
                else:
                    a = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic == "bl" and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            named = {
                0x9990:  "si_setcoreidx",
                0x11790: "wrap_ARM (set wake mask 0x48080)",
                0x142E0: "flag_struct init",
                0x15DA8: "wlc_bmac_up_prep",
                0x17ED6: "wlc_bmac_up_finish",
                0x18FFC: "wlc_up",
                0x11648: "wl_open (likely FullMAC dead code)",
                0x6820C: "wlc_bmac_attach",
                0x68A68: "wlc_attach",
                0x67614: "wl_probe",
                0x233E8: "wake-mask ARM impl (0x48080→D11+0x16C)",
                0x2340C: "wake-mask DISARM impl",
                0x2343A: "set-arbitrary-mask impl",
                0x2312C: "wlc_dpc",
            }
            if t in named: a = f"  → {named[t]}"
            else: a = f"  → fn@{t:#x}"
        except: pass
    elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            named = {0x17ED6: "TAIL→wlc_bmac_up_finish", 0x18FFC: "TAIL→wlc_up",
                     0x15DA8: "TAIL→wlc_bmac_up_prep"}
            if t in named: a = f"  >>> {named[t]} <<<"
        except: pass
    elif ins.mnemonic == "blx":
        a = "  → indirect"
    return a


def dump_fn(name, start, end=None):
    if end is None: end = find_fn_end(start)
    print(f"\n=========== {name}  fn @ {start:#x}..{end:#x} ===========")
    for ins in all_ins:
        if ins.address < start: continue
        if ins.address >= end: break
        a = annot(ins)
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    print(f"  ... [end {end:#x}]")


# ============== (1) Identify and dump pciedngl_open ==============
print("=== (1) pciedngl_open: fn containing 0x1c78 ===")
fn = find_fn_start(0x1c78)
print(f"  fn-start: {hex(fn) if fn else '?'}")
if fn: dump_fn("pciedngl_open", fn)


# ============== (2) Identify and dump pciedngl_probe ==============
print("\n\n=== (2) pciedngl_probe: fn containing 0x1e9e ===")
fn = find_fn_start(0x1e9e)
print(f"  fn-start: {hex(fn) if fn else '?'}")
if fn: dump_fn("pciedngl_probe", fn)


# ============== (3) Identify and dump pciedngl_isr ==============
print("\n\n=== (3) pciedngl_isr: fn containing 0x1ca0 ===")
fn = find_fn_start(0x1ca0)
print(f"  fn-start: {hex(fn) if fn else '?'}")
if fn: dump_fn("pciedngl_isr", fn)


# ============== (4) Identify and dump pciedngl_close (0x1c54) and ioctl (0x1c3a) ==============
for name, addr in (("pciedngl_close", 0x1c54), ("pciedngl_ioctl", 0x1c3a),
                   ("pciedngl_send", 0x1db0)):
    fn = find_fn_start(addr)
    print(f"\n=== ({name}: fn containing {addr:#x}) fn-start: {hex(fn) if fn else '?'} ===")
    if fn: dump_fn(name, fn)


# ============== (5) bcm_olmsg_init at 0x2f26 ==============
print("\n\n=== (5) bcm_olmsg_init: fn containing 0x2f26 ===")
fn = find_fn_start(0x2f26)
print(f"  fn-start: {hex(fn) if fn else '?'}")
if fn: dump_fn("bcm_olmsg_init", fn)


# ============== (6) Verify bmac_up_finish/prep printf strings live inside known fns ==============
print("\n\n=== (6) Verify 'bmac_up_finish' (@0x4b1f0) ldr-loaded inside fn@0x17ED6 ===")
target = 0x4b1f0
refs = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == target:
                refs.append(ins.address)
    except: pass
print(f"  Ldr-refs to 'bmac_up_finish' string: {refs and [hex(r) for r in refs] or 'NONE'}")
for r in refs:
    fns = find_fn_start(r)
    print(f"    {r:#x} inside fn@{hex(fns) if fns else '?'}  {'YES wlc_bmac_up_finish' if fns == 0x17ED6 else ''}")

print("\n=== (7) Verify 'bmac_up_prep' (@0x4af3c) ldr-loaded inside fn@0x15DA8 ===")
target = 0x4af3c
refs = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == target:
                refs.append(ins.address)
    except: pass
print(f"  Ldr-refs to 'bmac_up_prep' string: {refs and [hex(r) for r in refs] or 'NONE'}")
for r in refs:
    fns = find_fn_start(r)
    print(f"    {r:#x} inside fn@{hex(fns) if fns else '?'}  {'YES wlc_bmac_up_prep' if fns == 0x15DA8 else ''}")


# ============== (8) Find callers of fn@0x17ED6 (wlc_bmac_up_finish) — does an offload path call it? ==============
print("\n\n=== (8) ALL callers of fn@0x17ED6 (wlc_bmac_up_finish) ===")
callers = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x17ED6: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        callers.append(ins)
for ins in callers:
    fn = find_fn_start(ins.address)
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str} → caller fn @ {hex(fn) if fn else '?'}")
# fn-ptr table refs to 0x17ED7
needle = struct.pack("<I", 0x17ED7)
ptr_hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    ptr_hits.append(idx); pos = idx + 1
print(f"  fn-ptr table refs (0x17ED7): {len(ptr_hits)}")
for h in ptr_hits[:8]:
    print(f"    {h:#x} aligned={h%4==0}")


# ============== (9) Find callers of fn@0x18FFC (wlc_up) — confirm wl_open is sole caller? ==============
print("\n\n=== (9) ALL callers of fn@0x18FFC (wlc_up) ===")
callers = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x18FFC: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        callers.append(ins)
for ins in callers:
    fn = find_fn_start(ins.address)
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str} → caller fn @ {hex(fn) if fn else '?'}")
# fn-ptr table refs to 0x18FFD
needle = struct.pack("<I", 0x18FFD)
ptr_hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    ptr_hits.append(idx); pos = idx + 1
print(f"  fn-ptr table refs (0x18FFD): {len(ptr_hits)}")
for h in ptr_hits[:8]:
    print(f"    {h:#x} aligned={h%4==0}")
