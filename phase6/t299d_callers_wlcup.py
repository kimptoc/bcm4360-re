"""T299d: find callers of wlc_up (fn@0x18FFC), wlc_bmac_up_prep (fn@0x15DA8),
and wlc_bmac_up_finish (fn@0x17ED6).

Goal: identify the wlc-up dispatch chain. If wlc_up is called from a CDC
message handler, that's the host trigger we're missing.
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


def find_containing_fn(addr):
    candidates = []
    for ins in all_ins:
        if ins.address >= addr: break
        if is_push_lr(ins):
            candidates.append(ins.address)
    for c in reversed(candidates):
        depth = 0; in_fn = False; end = None
        for ins in all_ins:
            if ins.address < c: continue
            if is_push_lr(ins):
                depth += 1; in_fn = True
            elif is_pop_pc(ins) or is_bx_lr(ins):
                if in_fn:
                    depth -= 1
                    if depth == 0:
                        end = ins.address + ins.size
                        break
        if end and end > addr:
            return c, end
    return None, None


def fn_strings(start, end):
    out = []
    for ins in all_ins:
        if ins.address < start or ins.address >= end: continue
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s and len(s) >= 5:
                    out.append((ins.address, val, s))
        except: pass
    return out


def find_callers(target):
    """Return (direct, tail, indirect) caller info."""
    direct = []
    tail = []
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != target: continue
        if ins.mnemonic in ("bl", "blx"):
            direct.append(ins)
        elif ins.mnemonic in ("b", "b.w"):
            tail.append(ins)
    # Thumb fn-ptr search at any alignment
    needle = struct.pack("<I", target | 1)
    indirect = []
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        indirect.append(idx)
        pos = idx + 1
    return direct, tail, indirect


for tag, target in (
    ("wlc_up @ 0x18FFC", 0x18FFC),
    ("wlc_bmac_up_prep @ 0x15DA8", 0x15DA8),
    ("wlc_bmac_up_finish @ 0x17ED6", 0x17ED6),
    ("wlc_attach @ 0x68A68", 0x68A68),
):
    print(f"\n========== Callers of {tag} ==========")
    direct, tail, indirect = find_callers(target)
    print(f"  bl/blx: {len(direct)}")
    for ins in direct:
        fn, end = find_containing_fn(ins.address)
        fn_name = "?"
        if fn and end:
            for _, _, s in fn_strings(fn, end):
                if any(k in s for k in ("wlc_", "bmac", "_init", "_up", "_attach")):
                    fn_name = s; break
        print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}  → caller fn @ {hex(fn) if fn else '?'} \"{fn_name}\"")
    print(f"  b/b.w: {len(tail)}")
    for ins in tail:
        fn, end = find_containing_fn(ins.address)
        fn_name = "?"
        if fn and end:
            for _, _, s in fn_strings(fn, end):
                if any(k in s for k in ("wlc_", "bmac", "_init", "_up", "_attach")):
                    fn_name = s; break
        print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}  → caller fn @ {hex(fn) if fn else '?'} \"{fn_name}\"")
    print(f"  fn-ptr indirect (any alignment): {len(indirect)}")
    for h in indirect[:5]:
        # Show 32 bytes context
        ctx_start = max(0, h - 16)
        ctx_words = []
        for k in range(8):
            off = ctx_start + 4*k
            if off + 4 <= len(data):
                ctx_words.append(f"{struct.unpack_from('<I', data, off)[0]:#010x}")
        print(f"    {h:#x} aligned={h%4==0}: {' '.join(ctx_words)}")
