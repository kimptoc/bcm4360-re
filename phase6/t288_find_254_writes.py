"""T288: scan for ALL stores at offset 0x254 OR 0x258 (any encoding form),
plus stores via [base + register_holding_constant] patterns.

T283 already documented ONE writer of +0x254: the class-0 thunk at 0x2880
does `str.w r3, [r4, #0x254]` (write the class-table-lookup result to
scratch). That accounts for the runtime '+0x254 = 0x18100000' reading.

But who writes +0x258 (the underlying class table)? Previous scans missed
it. Possibilities:
- offset encoded as decimal (#600 instead of #0x258)
- offset reached via register-scaled addressing where the literal isn't
  in the disasm string (e.g., r3 holds 0x258 via separate mov/lsl)
- write via a base register pointing to sched+0x200 (then offset = +0x58)
- write via a base register pointing to sched+0x258 directly (then offset = 0)

Approach:
1. Confirm the str.w [r4, #0x254] writer in the class-0 thunk (sanity check).
2. Find ALL str variants that have an offset literal of 0x254 OR 0x258
   in the disasm string.
3. List ALL str instructions that occur in code regions immediately after
   a known load/computation of 0x18100000 — track register taint.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Pass 1: any str with 0x254 or 0x258 (or decimal equivalents) anywhere in op string
print("=== Pass 1: str* with 0x254 or 0x258 in operand string ===")
patterns = ["#0x254", "#0x258", "#596", "#600"]
hits = []
for ins in md.disasm(data[0x800:0x80000], 0x800, count=0):
    if not ins.mnemonic.startswith("str"):
        continue
    if "[sp" in ins.op_str:
        continue
    for p in patterns:
        if p in ins.op_str:
            hits.append((ins.address, ins.mnemonic, ins.op_str, p))
            break
print(f"  {len(hits)} hits")
for a, mn, op, p in hits:
    print(f"  {a:#x}: {mn} {op}   [matched {p}]")

# Pass 2: also pickup any 'strd' encoding capstone might emit
print("\n=== Pass 2: strd anywhere ===")
strds = []
for ins in md.disasm(data[0x800:0x80000], 0x800, count=0):
    if "strd" in ins.mnemonic.lower():
        strds.append((ins.address, ins.mnemonic, ins.op_str))
print(f"  {len(strds)} hits")
for a, mn, op in strds[:30]:
    print(f"  {a:#x}: {mn} {op}")

# Pass 3: Track registers loaded with 0x254 or 0x258 immediates,
# then look for str using that register as offset.
print("\n=== Pass 3: register taint — values 0x254/0x258 in regs, then used as str offset ===")

# Simple flow analysis: walk linearly, track which regs hold which constants.
reg_const = {}
linear_hits = []
prev_ins = None
for ins in md.disasm(data[0x800:0x80000], 0x800, count=0):
    op = ins.op_str

    # Branches reset register state (no inter-bb tracking).
    if ins.mnemonic.startswith(("b.", "b ", "bl", "bx", "blx", "cbz", "cbnz")):
        reg_const = {}
        continue

    # Track mov immediate
    if ins.mnemonic in ("mov.w", "movw", "movs", "mov"):
        try:
            parts = [p.strip() for p in op.split(",")]
            dst = parts[0]
            if len(parts) >= 2 and parts[1].startswith("#"):
                imm = parts[1][1:]
                imm_v = int(imm, 16) if imm.startswith("0x") else int(imm)
                reg_const[dst] = imm_v
            else:
                reg_const.pop(dst, None)
        except Exception:
            pass

    # Track add reg, reg, imm
    if ins.mnemonic in ("add.w", "add"):
        try:
            parts = [p.strip() for p in op.split(",")]
            if len(parts) == 3 and parts[2].startswith("#"):
                imm_str = parts[2][1:]
                imm = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
                src = parts[1]
                if src in reg_const:
                    reg_const[parts[0]] = reg_const[src] + imm
        except Exception:
            pass

    # Look at str* instructions
    if ins.mnemonic.startswith("str") and "[" in op:
        # Extract the index register if any
        # Match patterns like "[rX, rY]" or "[rX, rY, lsl ...]"
        try:
            inside = op[op.index("[") + 1:op.index("]")]
            tokens = [t.strip() for t in inside.split(",")]
            if len(tokens) >= 2:
                idx_reg = tokens[1].strip()
                # If idx_reg is a register holding 0x254 or 0x258 (or 0x96 for *4)
                if idx_reg in reg_const:
                    val = reg_const[idx_reg]
                    if val in (0x254, 0x258, 0x96):
                        linear_hits.append((ins.address, ins.mnemonic, op,
                                             idx_reg, val))
        except Exception:
            pass

print(f"  {len(linear_hits)} hits")
for a, mn, op, reg, val in linear_hits[:30]:
    print(f"  {a:#x}: {mn} {op}   [{reg}={val:#x}]")

# Pass 4: locate the EXACT class-0 thunk write of [r4, #0x254] (sanity)
print("\n=== Pass 4: confirm class-0 thunk str.w [r4, #0x254] at known location ===")
for ins in md.disasm(data[0x2870:0x28a0], 0x2870, count=0):
    print(f"  {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
