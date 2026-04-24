"""20-minute check: is bl #0x66a60 (shared msg-queue read) a polling loop?"""
import os, struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def nxt(start):
    for off in range(start + 2, min(start+4096, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None

n = nxt(0x66A60)
print(f"fn@0x66A60 extent ~{n - 0x66A60} bytes\n")

ins = list(md.disasm(data[0x66A60:n], 0x66A60, count=0))
print(f"{len(ins)} insns\n")

# Scan for backward branches (loop candidates)
backward = []
for i in ins:
    if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t < i.address:
                backward.append((i.address, t, i.mnemonic))
        except ValueError:
            pass

# Scan for calls and strings
from collections import Counter
bl_targets = Counter()
strs = set()
for i in ins:
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            bl_targets[int(i.op_str[1:], 16)] += 1
        except ValueError:
            pass
    if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                if 0 < v < len(data):
                    s = bytearray()
                    for k in range(80):
                        if v + k >= len(data): break
                        c = data[v + k]
                        if c == 0: break
                        if 32 <= c < 127: s.append(c)
                        else: s = None; break
                    if s and len(s) >= 4:
                        strs.add(s.decode("ascii"))
        except Exception:
            pass

print(f"Backward branches: {len(backward)}")
for ia, tgt, m in backward:
    dist = ia - tgt
    print(f"  {ia:#06x}: {m} back to {tgt:#x}  (dist {dist}){' TIGHT' if dist < 32 else ''}")

print(f"\nTop BL targets:")
for t, c in bl_targets.most_common(10):
    print(f"  bl #{t:#06x}  x{c}")

print(f"\nStrings referenced: {len(strs)}")
for s in sorted(strs):
    print(f"  {s!r}")

# Full disasm for inspection
print(f"\n=== full body ===")
for i in ins:
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
