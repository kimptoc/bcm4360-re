"""T298m: re-track containing fn with push AND push.w both counted."""
import sys
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


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str


def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str


def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


# Find ALL push-lr (push AND push.w) in [0x60000, 0x68B91)
candidates = []
for ins in all_ins:
    if ins.address >= 0x68B90: break
    if ins.address < 0x60000: continue
    if is_push_lr(ins):
        candidates.append(ins.address)

print(f"Push-lr (incl push.w) candidates in [0x60000, 0x68B90): {len(candidates)}")
print(f"Last 15: {[hex(c) for c in candidates[-15:]]}")


# For each candidate (latest first), depth-track to see if it contains 0x68B90
def fn_contains(start):
    depth = 0
    in_fn = False
    for ins in all_ins:
        if ins.address < start: continue
        if is_push_lr(ins):
            depth += 1
            in_fn = True
        elif is_pop_pc(ins) or is_bx_lr(ins):
            if in_fn:
                depth -= 1
                if depth == 0:
                    end = ins.address + ins.size
                    if end > 0x68B90:
                        return end
                    else:
                        return None
        if ins.address > 0x80000:
            break
    return None


print("\n=== Test each candidate (latest 10) for containment of 0x68B90 ===\n")
for c in candidates[-10:]:
    end = fn_contains(c)
    if end:
        print(f"  fn@{c:#x} → ENDS at {end:#x}: CONTAINS 0x68B90 ★ size={end-c}")
    else:
        print(f"  fn@{c:#x} → does NOT contain 0x68B90")
