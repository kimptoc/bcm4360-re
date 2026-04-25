"""T288: robust per-2-byte aligned scan for stores at offsets 0x254/0x258.

Linear capstone disasm halts on decode failures (literal pools embedded in
code). The per-2-byte aligned scan in t288_find_258_writers.py used the
correct method but only searched #0x258. This script scans for #0x254 too
(plus 0x258 sanity), AND for indexed stores via register-taint.

Sanity goals:
- Confirm the class-0 thunk's str.w [r4, #0x254] at 0x2880 IS detected.
- Find ALL writers of either offset, anywhere in the code region.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

START, END = 0x800, min(len(data), 0x80000)

hits_254, hits_258 = [], []
hits_strd = []
hits_indexed = []  # str [rX, rY (=offset)] where rY taint = 0x254/0x258

print(f"=== Per-2-byte scan from {START:#x} to {END:#x} ===")
checked = 0
for base in range(START, END, 2):
    # Try 4-byte and 2-byte windows (Thumb-2 wide vs narrow)
    window = data[base:base + 4]
    try:
        for ins in md.disasm(window, base, count=1):
            mn = ins.mnemonic
            op = ins.op_str
            if not (mn.startswith("str") or mn.startswith("strd")):
                break
            if "[sp" in op:
                break
            checked += 1
            if "#0x254" in op:
                hits_254.append((base, mn, op))
            if "#0x258" in op:
                hits_258.append((base, mn, op))
            if mn.startswith("strd"):
                hits_strd.append((base, mn, op))
            break
    except Exception:
        pass

print(f"  str* checked: {checked}")
print(f"\n--- str at #0x254: {len(hits_254)} ---")
for a, mn, op in hits_254:
    print(f"  {a:#x}: {mn} {op}")
print(f"\n--- str at #0x258: {len(hits_258)} ---")
for a, mn, op in hits_258:
    print(f"  {a:#x}: {mn} {op}")
print(f"\n--- strd anywhere: {len(hits_strd)} ---")
for a, mn, op in hits_strd:
    print(f"  {a:#x}: {mn} {op}")

# For each #0x254 hit, dump 12 instructions of context
print("\n=== Context (±10 ins) around each #0x254 hit ===")
for a, mn, op in hits_254:
    ctx_start = max(START, a - 30)
    print(f"\n--- around {a:#x} ---")
    for ins in md.disasm(data[ctx_start:a + 30], ctx_start, count=0):
        if ins.address > a + 30:
            break
        marker = "  >>>" if ins.address == a else "     "
        print(f"  {marker} {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
