"""T300: find ALL writers to offset 0x16C (D11 INTMASK) in the firmware.

Per the wake-gate model:
- D11 base = 0x18001000
- D11 INTMASK at +0x16C
- The mask 0x48080 enables MI_NSPECGEN_0/MI_DMAINT/MI_BG_NOISE wake bits
- fn@0x142E0 (in dead FullMAC code) writes 0x48080 to its arg's [+0x64] (flag_struct cache)
- wlc_bmac_up_finish (also dead) is the only fn that arms D11+0x16C

Question: if the FullMAC chain is dead, who actually arms D11+0x16C in
offload-mode firmware? Live fn? Host? Or never?

This probe finds ALL `str rN, [Rm, #0x16c]` insns and their containing fns.
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
        emitted = False
        last = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted = True
            last = ins.address + ins.size
            if last >= len(data) - 2: return
        pos = last if emitted else pos + 2


print("Disasm pass...")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str


fn_starts = sorted([i.address for i in all_ins if is_push_lr(i)])
import bisect

def fn_containing(addr):
    i = bisect.bisect_right(fn_starts, addr) - 1
    if i < 0: return None
    return fn_starts[i]


# Load live BFS set from T299s
live_set = set()
try:
    with open("/home/kimptoc/bcm4360-re/phase6/t299s_live_set.txt") as f:
        for line in f:
            tok = line.split()[0].strip()
            if tok.startswith("0x"):
                live_set.add(int(tok, 16))
    print(f"Loaded live BFS set: {len(live_set)} fns")
except Exception as e:
    print(f"Could not load live set: {e}")


# (1) ALL str/strh/strb instructions with offset 0x16c
print("\n=== (1) ALL stores with offset 0x16C (D11 INTMASK candidates) ===")
hits_16c = []
for ins in all_ins:
    if ins.mnemonic not in ("str", "str.w", "strh", "strh.w", "strb", "strb.w"): continue
    op = ins.op_str
    if "#0x16c" not in op: continue
    hits_16c.append(ins)

print(f"  Total str-at-+0x16c hits: {len(hits_16c)}")
for ins in hits_16c[:50]:
    fn = fn_containing(ins.address)
    in_live = fn in live_set if fn else False
    marker = " ★ LIVE" if in_live else ""
    print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}  inside fn@{hex(fn) if fn else '?'}{marker}")


# (2) All `str rN, [Rm, #0x16c]` where Rm is set by si_setcoreidx return (D11 base)
# That requires tracking si_setcoreidx (fn@0x9990) calls and what core_id was passed.
# Simplification: find ALL fns that:
#   (a) call si_setcoreidx with arg #0x812 (D11 core_id)
#   (b) AND have a str at offset 0x16c
print("\n\n=== (2) Fns calling si_setcoreidx with #0x812 (D11) ===")
# Find any fn that has both: bl 0x9990 AND mov r1, #0x812 in close proximity
d11_setcore_fns = set()
for i, ins in enumerate(all_ins):
    if ins.mnemonic != "bl": continue
    if "#0x9990" not in ins.op_str: continue
    # Look back up to 8 insns for mov r1, #0x812
    for j in range(max(0, i - 8), i):
        prev = all_ins[j]
        if (prev.mnemonic == "movs" or prev.mnemonic.startswith("mov")) and "0x812" in prev.op_str:
            fn = fn_containing(ins.address)
            if fn: d11_setcore_fns.add(fn)
            break
        # mov.w r1, #0x812 — wide encoding
        if prev.mnemonic == "mov.w" and prev.op_str.endswith("#0x812"):
            fn = fn_containing(ins.address)
            if fn: d11_setcore_fns.add(fn)
            break

print(f"  Fns calling si_setcoreidx with arg #0x812 (D11): {len(d11_setcore_fns)}")
for f in sorted(d11_setcore_fns):
    in_live = f in live_set
    marker = " ★ LIVE" if in_live else ""
    print(f"    fn@{f:#x}{marker}")


# (3) Cross-check: which fns are BOTH in d11_setcore_fns AND have a +0x16c store?
fns_with_16c = set(fn_containing(i.address) for i in hits_16c if fn_containing(i.address) is not None)
intersection = d11_setcore_fns & fns_with_16c
print(f"\n  Fns that BOTH call si_setcoreidx(D11) AND store at +0x16c: {len(intersection)}")
for f in sorted(intersection):
    in_live = f in live_set
    marker = " ★ LIVE" if in_live else " ✗ DEAD"
    print(f"    fn@{f:#x}{marker}")


# (4) For LIVE fns that store at +0x16c, dump their context to see what they store
print("\n\n=== (4) For LIVE fns with +0x16c stores: dump short context ===")
live_writers = [ins for ins in hits_16c if fn_containing(ins.address) in live_set]
print(f"  LIVE +0x16c stores: {len(live_writers)}")
for ins in live_writers[:20]:
    fn = fn_containing(ins.address)
    print(f"\n  Store at {ins.address:#x} (fn@{fn:#x}):")
    # Show 8 insns before
    for j, i2 in enumerate(all_ins):
        if i2.address >= ins.address - 0x20 and i2.address <= ins.address + 4:
            print(f"    {i2.address:#7x}  {i2.mnemonic:8s} {i2.op_str}")


# (5) Bonus: ALL stores anywhere that happen with value reg coming from a recently-loaded literal == 0x48080
# (slow but discriminating)
print("\n\n=== (5) Search for any 'ldr rN, =0x48080' followed by 'str rN, ...' ===")
# Already done for fn@0x142E0 (the only 0x48080 literal loader).
# For completeness, find all 4-byte aligned 0x48080 occurrences and ldr-loaders:
needle = struct.pack("<I", 0x48080)
hits_lit = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits_lit.append(idx); pos = idx + 1
print(f"  4B 0x48080 byte hits: {len(hits_lit)}")
for h in hits_lit:
    print(f"    {h:#x} aligned={h%4==0}")
# Find ldr loaders
print(f"\n  ldr-pool loaders for value 0x48080:")
loader_count = 0
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x48080:
                fn = fn_containing(ins.address)
                in_live = fn in live_set if fn else False
                marker = " ★ LIVE" if in_live else ""
                print(f"    {ins.address:#x}: {ins.op_str}  inside fn@{hex(fn) if fn else '?'}{marker}")
                loader_count += 1
    except: pass
print(f"  Total: {loader_count}")
