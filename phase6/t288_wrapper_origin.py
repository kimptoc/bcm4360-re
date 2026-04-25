"""T288: where do the wrapper-base addresses come from?

After exhaustive negatives:
- No strd, no mov #0x18100000, no orr/add #0x100000, no add #0x96 + indexed
  store, no movw+movt construction of 0x18100000, no literal-pool entry of
  0x18100000.

So 0x18100000 must arrive in sched+0x258 via one of:
A. Read from chipcommon EROM (chipcommon's own EROM entry contains the
   wrapper base of every core in this AI/AXI backplane). Then a `str` of
   the EROM-read value at [r4, slot*4 + something] could land at 0x258
   for some slot value we haven't pinned.
B. Computed from chipcommon-base via add immediate of less than 0x100000:
   e.g. shift left by 20, ORR. Easier to find as `lsl #20`.
C. Read from a hardware register that returns the wrapper base.

Approach:
1. Scan literal pool for ALL wrapper bases 0x18100000..0x18108000 and ALL
   register bases 0x18000000..0x18004000. Narrow to which addresses
   appear as immediates.
2. Scan code for `lsl rX, rY, #20` or `lsl.w rX, rY, #20` (bit-20 setter
   to convert 0x18000000 → 0x18100000).
3. Disasm fn@0x66fc4 — called from si_doattach(0x671b0) with sched_ctx
   in r0, chipcommon (0x18000000) in r1, plus some EROM-related args.
   This is a strong candidate for "per-core setup that fills sched+0x214,
   +0x258, etc."
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


# Pass 1: scan literal pool for all backplane-related addresses
print("=== Pass 1: literal pool scan for backplane addresses ===")
literal_targets = {}
# core regs (0x18000000 + i*0x1000) and wrappers (0x18100000 + i*0x1000)
for i in range(16):
    literal_targets[0x18000000 + i*0x1000] = f"core[{i}] register base"
    literal_targets[0x18100000 + i*0x1000] = f"core[{i}] wrapper"
literal_targets[0x18108000] = "core[6] wrapper (no reg base)"

found = {}
for base in range(0, len(data) - 4, 2):  # 2-byte aligned (catches mid-word values)
    if base % 4 != 0:
        continue
    v = struct.unpack_from("<I", data, base)[0]
    if v in literal_targets:
        found.setdefault(v, []).append(base)

for tgt in sorted(literal_targets.keys()):
    locs = found.get(tgt, [])
    if locs:
        print(f"  {tgt:#x} ({literal_targets[tgt]}): {len(locs)} hits → {[hex(l) for l in locs[:5]]}")
    # else: print(f"  {tgt:#x} ({literal_targets[tgt]}): 0")

# Pass 2: lsl by 20 patterns
print("\n=== Pass 2: lsl rX, rY, #20 (bit-20 set) ===")
hits_lsl20 = []
for ins in md.disasm(data[0x800:0x80000], 0x800, count=0):
    op = ins.op_str
    if ins.mnemonic.startswith("lsl") and ("#20" in op or "#0x14" in op):
        hits_lsl20.append((ins.address, ins.mnemonic, op))
print(f"  {len(hits_lsl20)} hits")
for a, mn, op in hits_lsl20[:20]:
    print(f"  {a:#x}: {mn} {op}")

# Pass 3: orr/add #0x100000 with broader matching
print("\n=== Pass 3: orr/add with bit-20 mask (broader match) ===")
hits_or20 = []
for ins in md.disasm(data[0x800:0x80000], 0x800, count=0):
    op = ins.op_str
    if ins.mnemonic in ("orr", "orr.w", "add", "add.w", "orn", "orn.w"):
        # Look for any of: #0x100000, #1048576, #1<<20
        if "#0x100000" in op or "#1048576" in op:
            hits_or20.append((ins.address, ins.mnemonic, op))
print(f"  {len(hits_or20)} hits")
for a, mn, op in hits_or20[:20]:
    print(f"  {a:#x}: {mn} {op}")

# Pass 4: deep disasm of fn@0x66fc4 (from si_doattach call at 0x671b0)
print("\n=== Pass 4: fn@0x66fc4 disasm (per-core setup candidate) ===")
print("--- si_doattach@0x671b0 args at call: (r0=sched, r1=chipcommon, r2..) ---\n")
ret_count = 0
for ins in md.disasm(data[0x66fc4:0x66fc4 + 1500], 0x66fc4, count=0):
    op = ins.op_str
    annot = ""
    if ins.mnemonic.startswith("ldr") and "[pc" in op:
        try:
            imm_str = op.split("#")[-1].rstrip("]").strip()
            imm = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
            lit_addr = ((ins.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                annot = f"  lit={v:#x}"
                if v in literal_targets:
                    annot += f" [{literal_targets[v]}]"
                elif 0x18000000 <= v < 0x18200000:
                    annot += f" [BACKPLANE {v:#x}]"
        except Exception: pass
    if ins.mnemonic in ("bl", "blx") and op.startswith("#"):
        try:
            t = int(op[1:], 16)
            if t == 0xa30: annot += "  ← printf"
            elif t == 0x1298: annot += "  ← heap-alloc"
            elif t == 0x91c: annot += "  ← memset"
            else: annot += f"  ← fn@{t:#x}"
        except: pass
    if ins.mnemonic.startswith("str"):
        # Flag any store with offset 0x250-0x270
        for off in range(0x240, 0x280, 4):
            for tok in (f"#{hex(off)}]", f"#{hex(off)},"):
                if tok.lower() in op.lower() and "[sp" not in op:
                    annot += f"  *** STORE +{off:#x} ***"
                    break
        if "lsl #2" in op and "[sp" not in op:
            annot += f"  *** INDEXED STORE ***"
    print(f"  {ins.address:#7x}  {ins.mnemonic:6s}  {ins.op_str}{annot}")
    if (ins.mnemonic == "bx" and "lr" in op) or \
       (ins.mnemonic in ("pop", "pop.w") and "pc" in op):
        ret_count += 1
        if ret_count >= 2:
            print("  --- 2nd ret reached ---")
            break
