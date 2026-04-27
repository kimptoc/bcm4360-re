"""T299y: verify the heuristic-derived claims:
1. Disasm 0x1c00..0x1c40 raw — what is at 0x1c1c..0x1c1e? Is wfi a leaf fn?
2. Disasm 0x4355c..0x43580 raw — what is the actual containing fn for cpsie ai?
3. Find real callers of any executable code containing wfi 0x1c1e.
4. Confirm whether *(0x224) install scan was accurate (look for any 'str XX, [r,#imm]' where r is loaded with 0x224 via something other than ldr-pc-rel — like add r,pc,#imm or movw/movt or arithmetic).
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


# ============== (1) Raw disasm 0x1bf0..0x1c40 — what's around the wfi? ==============
print("=== (1) Raw disasm 0x1bf0..0x1c40 (looking for context of wfi @ 0x1c1e) ===")
chunk = data[0x1bf0:0x1c40]
print("Raw bytes:")
for off in range(0x1bf0, 0x1c40, 8):
    chunk2 = data[off:off+8]
    hex_s = " ".join(f"{b:02x}" for b in chunk2)
    print(f"  {off:#06x}: {hex_s}")
print()
print("Disasm starting at 0x1bf0:")
for ins in md.disasm(chunk, 0x1bf0):
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")

# Also try disasm starting at 0x1c1c (alignment matters in Thumb)
print("\nDisasm starting at 0x1c1c (aligned):")
chunk2 = data[0x1c1c:0x1c40]
for ins in md.disasm(chunk2, 0x1c1c):
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")


# ============== (2) Raw disasm 0x43500..0x43590 — context of cpsie ai @ 0x4356e ==============
print("\n\n=== (2) Raw disasm 0x43500..0x43590 (context for cpsie ai @ 0x4356e) ===")
chunk = data[0x43500:0x43590]
print("Raw bytes:")
for off in range(0x43500, 0x43590, 8):
    chunk2 = data[off:off+8]
    hex_s = " ".join(f"{b:02x}" for b in chunk2)
    print(f"  {off:#06x}: {hex_s}")
print()
print("Disasm starting at 0x43500:")
for ins in md.disasm(chunk, 0x43500):
    a = ""
    if ins.mnemonic in ("cpsie", "cpsid", "wfi", "wfe"):
        a = "  ★★★"
    elif ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str:
        a = "  [PUSH-LR — fn-start]"
    elif ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str:
        a = "  [POP-PC — fn-end]"
    elif ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        a = "  [BX LR — fn-end]"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")


# ============== (3) Try alternate alignment for cpsie ai context ==============
print("\n\n=== (3) Try disasm starting at 0x43560 (just before cpsie ai) ===")
for ins in md.disasm(data[0x43560:0x435a0], 0x43560):
    a = ""
    if ins.mnemonic in ("cpsie", "cpsid", "wfi", "wfe"):
        a = "  ★★★"
    elif ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str:
        a = "  [PUSH-LR — fn-start]"
    elif ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str:
        a = "  [POP-PC — fn-end]"
    elif ins.mnemonic == "bx" and ins.op_str.strip() == "lr":
        a = "  [BX LR]"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")


# ============== (4) Find ALL push-lr instructions, identify the one immediately preceding 0x1c1e ==============
print("\n\n=== (4) push-lr addresses near wfi @ 0x1c1e (sequential disasm) ===")
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

prev_pushes = []
for ins in iter_all():
    if ins.address > 0x1c40: break
    if ins.address < 0x1b00: continue
    if ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str:
        prev_pushes.append(ins.address)
    if ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str:
        print(f"  {ins.address:#x}: pop ... pc")
print(f"  push-lr instances in [0x1b00, 0x1c40]: {[hex(p) for p in prev_pushes]}")


# ============== (5) Find actual callers of wfi instruction (or fn-ptrs to 0x1c1f) ==============
print("\n\n=== (5) Direct bl/b targeting 0x1c1e and fn-ptrs to 0x1c1f ===")
all_ins = list(iter_all())
direct = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t in (0x1c1e, 0x1c1c, 0x1c10):
        if ins.mnemonic in ("bl", "blx", "b", "b.w"):
            direct.append((ins, t))
print(f"  Direct call/jump targeting 0x1c1e / 0x1c1c / 0x1c10: {len(direct)}")
for ins, t in direct[:10]:
    print(f"    {ins.address:#x}: {ins.mnemonic} → {t:#x}")

needle = struct.pack("<I", 0x1c1f)  # Thumb fn-ptr to wfi instruction
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  fn-ptr (0x1c1f) byte hits: {len(hits)}")
for h in hits[:5]:
    print(f"    {h:#x} aligned={h%4==0}")
