"""T299p: three cheap discriminators per advisor before declaring done.

(1) FW entry point — dump file offset 0..0x40 + disasm reset vector.
(2) fn@0x4718 — wl_probe passes fn-ptrs to it; does it INVOKE them or store
    them? `blx r2` or similar would propagate live-ness.
(3) Host-observation premise — locate the actual flag_struct allocation site
    and confirm what code actually places the struct in observable memory.
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB
CS_MODE_ARM = 0

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md_t = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md_a = Cs(CS_ARCH_ARM, CS_MODE_ARM)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md_t.disasm(data[pos:], pos):
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


# ============== (1) Firmware entry / reset vector ==============
print("=== (1) File offset 0..0x80 — entry / reset vector ===\n")
print("Raw bytes 0..0x80:")
for off in range(0, 0x80, 16):
    chunk = data[off:off+16]
    hex_s = " ".join(f"{b:02x}" for b in chunk)
    asc_s = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
    print(f"  {off:#06x}: {hex_s}  |{asc_s}|")

print("\nFirst 16 little-endian 32-bit words (potential vector table):")
for off in range(0, 0x40, 4):
    val = struct.unpack_from('<I', data, off)[0]
    s = str_at(val)
    extra = ""
    if s: extra = f"  → \"{s}\""
    elif val & 1 and 0x1000 < val < len(data):
        extra = f"  → fn@{val-1:#x}"
    elif 0x1000 < val < len(data):
        extra = f"  → addr {val:#x}"
    print(f"  word[{off//4}] = {val:#010x}{extra}")

# Try ARM-mode disasm (some ARMs have ARM-mode reset stubs)
print("\nARM-mode disasm @ 0x0..0x40:")
for ins in md_a.disasm(data[:0x40], 0):
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
    if ins.address >= 0x40: break

# Thumb-mode disasm @ 0..0x80
print("\nThumb disasm @ 0x0..0x80:")
seen = 0
for ins in md_t.disasm(data[:0x80], 0):
    a = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                a = f"  ; lit={val:#x}"
                if val & 1 and 0x1000 < val < len(data):
                    a += f" → fn@{val-1:#x}"
        except: pass
    elif ins.mnemonic == "bl" and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            a = f"  → fn@{t:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    seen += 1
    if seen > 40: print("  ..."); break


# ============== (2) Disasm fn@0x4718 — does it invoke the passed fn-ptr? ==============
print("\n\n=== (2) DUMP fn@0x4718 (called by wl_probe with fn-ptr in r2) ===")
print("Disasm pass for context...")
all_ins = list(iter_all())
print(f"  Total ins: {len(all_ins):,}")


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


fn_start = find_fn_start(0x4718)
if fn_start is None or fn_start > 0x4718:
    fn_start = 0x4718
fn_end = find_fn_end(fn_start)
print(f"\nfn@{fn_start:#x}..{fn_end:#x}:")
for ins in all_ins:
    if ins.address < fn_start: continue
    if ins.address >= fn_end: break
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
            a = f"  → fn@{t:#x}"
        except: pass
    elif ins.mnemonic == "blx" and ins.op_str.strip().startswith("r"):
        a = f"  → INDIRECT via {ins.op_str.strip()} (fn-ptr in reg!)"
    elif ins.mnemonic in ("str", "str.w"):
        if "r2" in ins.op_str: a = "  [STORE r2 — saving the fn-ptr]"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")


# ============== (3) Other callers of fn@0x4718 — propagation source ==============
print("\n\n=== (3) ALL callers of fn@0x4718 ===")
direct = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x4718: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        direct.append(ins)
print(f"  Direct: {len(direct)}")
for ins in direct:
    fn = find_fn_start(ins.address)
    print(f"    {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}")
needle = struct.pack("<I", 0x4719)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x4719) hits: {len(hits)}")
for h in hits[:8]:
    print(f"    {h:#x} aligned={h%4==0}")


# ============== (4) RAM-base hint: scan for 'rambase' / 'rom' / 'sram' strings — may reveal load layout ==============
print("\n\n=== (4) Strings hinting at load layout ===")
for needle in (b"rambase", b"sram", b"_main\0", b"main\0", b"_start\0", b"start\0",
               b"reset\0", b"hndrte_init", b"BCM4360", b"BCM 4360", b"%s built",
               b"fwhash", b"4360"):
    pos = 0; cnt = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        s = str_at(idx)
        if s: print(f"  '{needle.decode():15s}' @ {idx:#x}: \"{s}\"")
        pos = idx + 1
        cnt += 1
        if cnt > 6: break
