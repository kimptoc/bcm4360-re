"""T288: scan for stm (store-multiple) instructions writing into the
sched_ctx +0x254/+0x258 region. Final check before declaring the
EROM-origin reading.

A pattern like `stm rN, {r3, r3}` or `stm.w rN, {r3-r4}` with rN pointing
at sched+0x254 would write the SAME value to BOTH +0x254 and +0x258 in
one instruction — perfectly explaining the T287b "twin" reading.

For STM, base register holds the address; offset is implicit (consecutive
words). So we can't filter by offset. We list ALL stm hits and look for
those where the surrounding context computes a sched-relative address.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

START, END = 0x800, min(len(data), 0x80000)

stm_hits = []
for base in range(START, END, 2):
    window = data[base:base + 4]
    try:
        for ins in md.disasm(window, base, count=1):
            mn = ins.mnemonic
            op = ins.op_str
            # stm variants: stm, stmia, stmdb, stmib, stmda, stm.w
            if mn in ("stm", "stm.w", "stmia", "stmia.w", "stmdb", "stmdb.w",
                       "stmea", "stmfa", "stmfd", "stmib", "stmda"):
                if "[sp" in op or "{lr" in op or "{pc" in op or "{r4" in op and "lr" in op:
                    # heuristic: skip function-prologue-like patterns
                    pass
                stm_hits.append((base, mn, op))
            break
    except Exception:
        pass

print(f"=== stm-family hits across code region: {len(stm_hits)} ===")
# Print with size of the register list as proxy for "how many words written"
for a, mn, op in stm_hits:
    # count number of regs in {...}
    reg_part = op[op.index("{") + 1:op.index("}")] if "{" in op and "}" in op else ""
    n = len([r for r in reg_part.split(",") if r.strip()])
    print(f"  {a:#x}: {mn} {op}   [{n} regs]")
