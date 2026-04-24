"""T288: wide scan for ALL instructions that STORE to [rX, #0x258] across
the entire fw blob. This catches str/str.w/strh/strb with offset 0x258.

Advisor hint: +0x258 is likely element-0 of a class-indexed stride-4 table,
so a loop storing at contiguous offsets (+0x258, +0x25c, +0x260, ...) is
the signature we're looking for. A single str.w [rX, #0x258] with a
non-sp destination narrows the search; a loop with [rX, rY, lsl #2] at
base+0x258 is the advisor's "core enumeration" signature.

Also scan for:
- Literal loads of 0x18100000 (PCIE2 base) — if any exist, we find the
  hardcoded-literal path. T283 said chipcommon was the only 0x18000000
  literal so no hits expected, but verify.
- str to [rX, rY, lsl #2] near offsets 0x240-0x280 (class-table stride).
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Scan-region: fw image code is roughly 0x800..0x90000 in TCM (outside
# the literal pool). We disasm from each aligned 2-byte offset.
START = 0x800
END = min(len(data), 0x80000)

hits_258 = []
hits_literal = []   # literal-pool hits for 0x18100000
hits_stride = []    # str [rX, rY, lsl #2] patterns

# First pass: look for literal pool entries = 0x18100000
for base in range(0, len(data) - 4, 4):
    v = struct.unpack_from("<I", data, base)[0]
    if v == 0x18100000:
        hits_literal.append(base)

print(f"=== Literal-pool hits for 0x18100000: {len(hits_literal)} ===")
for h in hits_literal[:10]:
    print(f"  literal@{h:#x}")
print()

# Second pass: thumb disasm and look for interesting stores
print(f"=== str[X, #0x258] scan from {START:#x} to {END:#x} ===")
for base in range(START, END, 2):
    window = data[base:base + 4]
    try:
        for ins in md.disasm(window, base, count=1):
            if ins.mnemonic in ("str", "str.w"):
                op = ins.op_str
                # Match #0x258 or #600 (= 0x258 decimal in some capstone)
                if "#0x258" in op and "[sp" not in op:
                    # Check whether the base reg is a register we care about
                    hits_258.append((ins.address, ins.mnemonic, op))
                # Also flag str with shifted reg index near the right base
                if "lsl #2" in op and ("0x240" in op or "0x258" in op or "0x250" in op):
                    hits_stride.append((ins.address, ins.mnemonic, op))
            break
    except Exception:
        pass

print(f"=== str [rX, #0x258] (non-sp) hits: {len(hits_258)} ===")
for addr, mn, op in hits_258:
    print(f"  {addr:#x}: {mn} {op}")
print()

print(f"=== Shifted-reg stores near 0x240-0x258 base: {len(hits_stride)} ===")
for addr, mn, op in hits_stride:
    print(f"  {addr:#x}: {mn} {op}")

# Also dump context around each hit_258 to see function boundary
print()
print("=== Context (±12 instructions) around each str [rX, #0x258] hit ===")
for addr, mn, op in hits_258:
    print(f"\n--- around {addr:#x} ---")
    ctx_start = max(0, addr - 30)
    ctx_window = data[ctx_start:addr + 30]
    for ins in md.disasm(ctx_window, ctx_start, count=0):
        marker = "  >>>" if ins.address == addr else "     "
        print(f"{marker} {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
