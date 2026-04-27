"""T299c: map function name STRINGS back to their containing fns.

For each string ("wlc_up", "wlc_attach", "wlc_bmac_attach", "wlc_bmac_up_prep"),
find ldr instructions that load the string addr — those are inside the named fn.
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


# Find code-side refs to each name string
TARGETS = {
    "wlc_up":            0x4B16F,
    "wlc_attach":        0x4B1FF,
    "wlc_bmac_attach":   0x4B121,
    "wlc_bmac_up_prep":  0x4AF38,
    "wlc_bmac_up_finish":0x4B1EC,  # already known, sanity
}

for name, str_addr in TARGETS.items():
    print(f"\n=== refs to \"{name}\" (string at {str_addr:#x}) ===")
    refs = []
    for ins in all_ins:
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == str_addr:
                    refs.append(ins.address)
        except: pass
    print(f"  Code refs: {len(refs)}")
    for ref in refs:
        fn, end = find_containing_fn(ref)
        print(f"    {ref:#x}  containing fn @ {hex(fn) if fn else '?'} (ends {hex(end) if end else '?'})")
