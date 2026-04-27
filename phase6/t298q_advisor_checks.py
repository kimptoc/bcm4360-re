"""T298q (advisor): three cheap checks before locking interpretation #4.

(1) Search for b/b.w #0x233E8 and #0x2340c — tail-call branches the bl-scan
    misses.
(2) Search for byte sequences `e9 33`/`0d 34` (low halves of Thumb fn-ptrs
    0x233E9 / 0x2340D) at ANY offset — packed in struct templates.
(3) Search for literal value 0x48080 anywhere in the blob beyond
    fn@0x142E0's literal pool entry — if it appears in a .data struct
    image, that's the init template.
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


# (1) tail-call b/b.w to fn@0x233E8 and fn@0x2340c
print("=== (1) tail-call branches (b/b.w) to fn@0x233E8 / fn@0x2340c ===\n")
for target_name, target in (("fn@0x233E8", 0x233E8), ("fn@0x2340c", 0x2340C)):
    hits = []
    for ins in all_ins:
        if ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                if t == target:
                    hits.append(ins)
            except: pass
    print(f"  {target_name}: {len(hits)} tail-call hit(s)")
    for ins in hits:
        print(f"    {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# (2) packed Thumb-ptr bytes — search for 0x233E9 / 0x2340D as 4-byte LE values
# at ANY offset (not just 4-byte aligned)
print("\n\n=== (2) Packed Thumb fn-ptr bytes anywhere in blob ===")
for ptr_name, ptr_val in (("fn@0x233E9 (Thumb ptr)", 0x233E9), ("fn@0x2340D (Thumb ptr)", 0x2340D)):
    needle = struct.pack("<I", ptr_val)
    hits = []
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx)
        pos = idx + 1
    print(f"  {ptr_name}: {len(hits)} hit(s) at any offset")
    for h in hits[:10]:
        print(f"    file offset {h:#x} (aligned: {'YES' if h%4==0 else 'no'})")


# (3) literal 0x48080 anywhere in blob
print("\n\n=== (3) Literal value 0x48080 (canonical wake mask) anywhere in blob ===")
needle = struct.pack("<I", 0x48080)
hits = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx)
    pos = idx + 1
print(f"  0x48080: {len(hits)} hit(s) at any offset")
for h in hits:
    aligned = "YES" if h % 4 == 0 else "no"
    print(f"    file offset {h:#x} (aligned: {aligned})")
    # Show 32 bytes of context (8 dwords) — see if it's in a struct template
    if h >= 16:
        ctx = " ".join(f"{struct.unpack_from('<I', data, h-16+4*k)[0]:#010x}" for k in range(8))
        print(f"      context dwords ({h-16:#x}..): {ctx}")
    elif h >= 8:
        ctx = " ".join(f"{struct.unpack_from('<I', data, max(0,h-8)+4*k)[0]:#010x}" for k in range(min(8, (len(data)-(max(0,h-8)))//4)))
        print(f"      context dwords: {ctx}")


# Also: search for the small int constants from fn@0x142E0 init pattern
# (3, 2, 7, 4, 0x1001, 0xff at byte offsets 0xa8, 0xaa, 0xa4, 0xa6, 0xbc, 0x16c)
# If a struct template in .data has these values at the same offsets, it's
# the template that fn@0x142E0 mirrors.
print("\n\n=== (4) Search for the fn@0x142E0 init-value pattern as a struct template ===")
# Look for: 0x48080 at +0x64 and 0x1001 (halfword) at +0xbc — a recognizable signature
# Search 4-byte hits of 0x48080 (already found above), and check if dword at hit+0x58 is 0x1001
# (since +0xbc - +0x64 = 0x58)
print("Checking each 0x48080 hit for adjacent 0x1001 at +0x58 offset (struct shape match):")
for h in hits:
    # Read halfword at h + 0x58
    if h + 0x58 + 2 <= len(data):
        hw = struct.unpack_from("<H", data, h + 0x58)[0]
        if hw == 0x1001:
            print(f"  ★ struct template MATCH at file offset {h-0x64:#x} (0x48080 at +0x64, 0x1001 at +0xbc)")
        else:
            print(f"  hit @ {h:#x}: hw at +0x58 = {hw:#x} (not 0x1001 — not the template)")


# (5) Look for any ldr/mov of constants near 0x48080 — alternative writers via different patterns
print("\n\n=== (5) Other instructions referencing 0x48080 (mov.w, ldr-pc-rel constructions) ===")
matches = 0
for ins in all_ins:
    if ins.mnemonic in ("mov.w", "movw", "movt", "mov"):
        if "#0x48080" in ins.op_str.lower():
            print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")
            matches += 1
    elif ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == 0x48080:
                    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}  ; lit@{la:#x} = 0x48080")
                    matches += 1
        except: pass
print(f"Total inline / pc-rel references to 0x48080: {matches}")
