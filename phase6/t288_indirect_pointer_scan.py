"""T288: hunt for indirect addressing of sched+0x258 area.

Direct stores at offset #0x258 don't exist. Likely the class table is
populated via a function that receives `&sched[0x250]` or `&sched[0x258]`
as a base register, then writes via small offsets.

Patterns searched:
1. `add.w rN, rM, #imm` where imm is in [0x240..0x280] — passing a
   pointer into the class-table region.
2. `mov.w rN, #imm` followed by use of rN for indexed addressing.
3. Scan for any function entry that takes a 2nd-arg pointer and writes
   to small offsets — too broad without taint analysis. Skip for now.

Also: scan ENTIRE blob (including the 0x6bf78..end region) for str
instructions at #0x254/0x258. Maybe code outside the "main code region"
exists that we missed.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


# Pass 1: scan ENTIRE blob for any str at #0x254 / #0x258
print("=== Pass 1: ENTIRE blob (0..end) per-2-byte scan ===")
START, END = 0, len(data)
hits_254, hits_258 = [], []
for base in range(START, END, 2):
    window = data[base:base + 4]
    try:
        for ins in md.disasm(window, base, count=1):
            if not ins.mnemonic.startswith("str"):
                break
            if "[sp" in ins.op_str:
                break
            if "#0x254" in ins.op_str:
                hits_254.append((base, ins.mnemonic, ins.op_str))
            if "#0x258" in ins.op_str:
                hits_258.append((base, ins.mnemonic, ins.op_str))
            break
    except Exception:
        pass
print(f"  str at #0x254: {len(hits_254)}")
for a, mn, op in hits_254:
    print(f"    {a:#x}: {mn} {op}")
print(f"  str at #0x258: {len(hits_258)}")
for a, mn, op in hits_258:
    print(f"    {a:#x}: {mn} {op}")

# Pass 2: code region only — scan for `add rN, rM, #imm` where imm in [0x240..0x280]
print("\n=== Pass 2: add rN, rM, #imm where imm in [0x240..0x280] ===")
hits_add = []
for base in range(0x800, min(len(data), 0x80000), 2):
    window = data[base:base + 4]
    try:
        for ins in md.disasm(window, base, count=1):
            if ins.mnemonic not in ("add.w", "add", "adds"):
                break
            op = ins.op_str
            if "#" not in op:
                break
            try:
                imm_str = op.split("#")[-1].strip().rstrip("]").rstrip(",")
                imm = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
                if 0x240 <= imm <= 0x280:
                    hits_add.append((base, ins.mnemonic, op, imm))
            except Exception:
                pass
            break
    except Exception:
        pass

print(f"  {len(hits_add)} hits")
for a, mn, op, imm in hits_add:
    print(f"  {a:#x}: {mn} {op}   [imm={imm:#x}]")

# Pass 3: context around each add hit
print("\n=== Pass 3: context (±8 ins) around each add #imm hit ===")
md_ctx = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for a, mn, op, imm in hits_add:
    ctx_start = max(0x800, a - 24)
    print(f"\n--- around {a:#x} (add+{imm:#x}) ---")
    try:
        for ins in md_ctx.disasm(data[ctx_start:a + 32], ctx_start, count=0):
            if ins.address > a + 30:
                break
            marker = "  >>>" if ins.address == a else "     "
            print(f"  {marker} {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
    except Exception:
        pass

# Pass 4: scan for function calls where one arg is computed as sched+offset.
# Approximate: look for `add.w rN, rM, #N` where N=0x254 or near, immediately
# followed by mov/bl that uses rN.
print("\n=== Pass 4: add #0x254 or #0x258 then use as call arg / store base ===")
for a, mn, op, imm in hits_add:
    if imm not in (0x254, 0x258, 0x250):
        continue
    print(f"\n--- {a:#x} add+{imm:#x} ---")
    # Disasm next 6 instructions to see usage
    try:
        cnt = 0
        for ins in md_ctx.disasm(data[a:a + 24], a, count=0):
            print(f"     {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}")
            cnt += 1
            if cnt >= 8: break
    except Exception:
        pass
