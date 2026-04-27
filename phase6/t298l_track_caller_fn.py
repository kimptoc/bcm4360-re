"""T298l: track from each candidate fn-start before 0x68B90 forward,
find the one whose body actually contains 0x68B90."""
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


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")

# Find ALL push-lr in [0x67000, 0x68B91)
candidates = []
for ins in all_ins:
    if ins.address >= 0x68B90: break
    if ins.address < 0x67000: continue
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        candidates.append(ins.address)

print(f"Push-lr candidates in [0x67000, 0x68B90): {len(candidates)}")
print(f"Last 10: {[hex(c) for c in candidates[-10:]]}")


# For each candidate, walk forward and track depth: push +1, pop/bx-lr -1.
# The candidate whose depth reaches 0 ONLY AFTER 0x68B90 is the enclosing fn.
def fn_contains(start):
    """Returns end-address of fn or None (if doesn't reach 0x68B90 before depth 0)."""
    depth = 0
    in_fn = False
    for ins in all_ins:
        if ins.address < start: continue
        if ins.mnemonic == "push" and "lr" in ins.op_str:
            depth += 1
            in_fn = True
        elif (ins.mnemonic == "pop" and "pc" in ins.op_str) or (
            ins.mnemonic == "bx" and ins.op_str.strip() == "lr"
        ):
            if in_fn:
                depth -= 1
                if depth == 0:
                    end = ins.address + ins.size
                    if end > 0x68B90:
                        return end
                    else:
                        return None
        if ins.address > 0x70000:
            break
    return None


print("\n=== Testing each push-lr candidate to see if it contains 0x68B90 ===\n")
for c in candidates[-10:]:
    end = fn_contains(c)
    if end:
        print(f"  fn@{c:#x} → ENDS at {end:#x}: CONTAINS 0x68B90 ★")
    else:
        print(f"  fn@{c:#x} → does not contain 0x68B90")


# More robust: scan back further if needed
print("\n=== Push-lr candidates in [0x60000, 0x68B90) — last 10 only ===")
candidates2 = []
for ins in all_ins:
    if ins.address >= 0x68B90: break
    if ins.address < 0x60000: continue
    if ins.mnemonic == "push" and "lr" in ins.op_str:
        candidates2.append(ins.address)
print(f"Total: {len(candidates2)}; last 5: {[hex(c) for c in candidates2[-5:]]}")
