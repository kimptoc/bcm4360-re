"""T298r: trace the ARM/DISARM wrapper at 0x11792/0x11798 and find its callers.

Tail-calls discovered by advisor's check:
  0x11792  b.w #0x233e8   (ARM)
  0x11798  b.w #0x2340c   (DISARM)

These are 6 bytes apart — a wrapper fn that branches based on some flag
(arm/disarm), tail-calling the underlying impl.

Find: enclosing fn start, full body, callers.
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


# Find enclosing fn for the tail-calls — the push-lr immediately before 0x11792
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
            # Tail-call b.w also ends a fn (no return)
            if ins.mnemonic == "b.w" and "#0x" in ins.op_str:
                # only count if depth == 1 (single-level fn)
                # Actually tail-calls don't decrement depth, but they DO end the
                # current fn. Check if depth is still 1 and we just saw b.w.
                if in_fn and depth == 1:
                    end = ins.address + ins.size
                    break
        if end and end > addr:
            return c, end
    return None, None


fn, end = find_containing_fn(0x11792)
print(f"Enclosing fn for tail-calls: {hex(fn) if fn else '?'} (ends {hex(end) if end else '?'})")
if fn:
    print(f"\n--- Full body of fn@{hex(fn)} ---")
    for ins in md.disasm(data[fn:end + 8], fn):
        if ins.address >= end + 4: break
        annot = ""
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if 0 <= la <= len(data) - 4:
                    val = struct.unpack_from('<I', data, la)[0]
                    s = str_at(val)
                    if s: annot = f"  ; \"{s}\""
                    else: annot = f"  ; lit={val:#x}"
            except: pass
        elif ins.mnemonic == "bl":
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                annot = f"  → fn@{t:#x}"
            except: pass
        elif ins.mnemonic == "b.w" and "#0x233e8" in ins.op_str:
            annot = "  >>> tail-call ARM (fn@0x233E8) <<<"
        elif ins.mnemonic == "b.w" and "#0x2340c" in ins.op_str:
            annot = "  >>> tail-call DISARM (fn@0x2340C) <<<"
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")


# Find callers of this wrapper fn
if fn:
    print(f"\n\n=== Callers of wrapper fn@{hex(fn)} ===\n")
    direct = []
    for ins in all_ins:
        if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                if t == fn:
                    direct.append(ins)
            except: pass
    print(f"Direct bl/blx hits: {len(direct)}")
    for ins in direct:
        cf, ce = find_containing_fn(ins.address)
        print(f"  call @ {ins.address:#x}: caller fn @ {hex(cf) if cf else '?'}")

    # Also tail-calls
    tail = []
    for ins in all_ins:
        if ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                if t == fn:
                    tail.append(ins)
            except: pass
    print(f"\nTail-call branches: {len(tail)}")
    for ins in tail:
        cf, ce = find_containing_fn(ins.address)
        print(f"  branch @ {ins.address:#x}: caller fn @ {hex(cf) if cf else '?'}")

    # And fn-ptr table refs
    needle = struct.pack("<I", fn | 1)
    pos = 0; ptr = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        if idx % 4 == 0: ptr.append(idx)
        pos = idx + 1
    print(f"\nfn-ptr table refs (aligned): {len(ptr)}")
    for h in ptr:
        print(f"  {h:#x}")
