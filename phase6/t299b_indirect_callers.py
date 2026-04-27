"""T299b: hunt for INDIRECT callers of wlc_bmac_up_finish.

Strategies:
1. Find any code that LOADS the constant 0x17ED7 (or 0x17ED6) — that's a fn-ptr
   construction site.
2. Search for byte sequences that could encode the fn ptr in struct templates
   that get memcpy'd at runtime (any alignment, both LE and packed).
3. Look at fn@0x17ECC — the function called right AFTER wlc_bmac_up_finish in
   fn@0x17ED6 body. Maybe its name reveals what UP layer wlc_bmac_up_finish
   belongs to.
4. Look at adjacent fns 0x17C00..0x17F00 — find which one has a printf string
   like "wlc_bmac_up" or "wlc_up_finish" or "wlc_init".
"""
import struct, sys
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


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


# (1) Search for ANY byte-occurrences of 0x17ED7 / 0x17ED6 at ANY alignment
print("=== (1) ALL byte occurrences of 0x17ED7 / 0x17ED6 (any alignment) ===")
for tag, val in (("Thumb fn-ptr 0x17ED7", 0x17ED7), ("Raw addr 0x17ED6", 0x17ED6)):
    needle = struct.pack("<I", val)
    hits = []
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx)
        pos = idx + 1
    print(f"  {tag}: {len(hits)} hit(s)")
    for h in hits:
        # Show 32 bytes around
        ctx_start = max(0, h - 16)
        ctx_words = []
        for k in range(8):
            off = ctx_start + 4*k
            if off + 4 <= len(data):
                ctx_words.append(f"{struct.unpack_from('<I', data, off)[0]:#010x}")
        print(f"    {h:#x} aligned={h%4==0}: {' '.join(ctx_words)}")


# (2) Disasm-side: any `mov.w/movw/movt/ldr` constructing 0x17ED7
print("\n=== (2) Any instruction loading or constructing 0x17ED7 ===")
hits_lit = []
for ins in all_ins:
    # Check ldr [pc, #imm] where the literal == 0x17ED7
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val in (0x17ED7, 0x17ED6):
                    hits_lit.append((ins.address, val, la))
        except: pass
    # mov.w / movw with #0x17ED7
    elif ins.mnemonic in ("mov","mov.w","movw") and "#0x" in ins.op_str:
        if "#0x17ed7" in ins.op_str.lower() or "#0x17ed6" in ins.op_str.lower():
            hits_lit.append((ins.address, "inline", ins.op_str))
    # movw + movt pair: low half = 0x7ED7, high half = 0x1
    elif ins.mnemonic == "movw" and "#0x7ed7" in ins.op_str.lower():
        hits_lit.append((ins.address, "movw-low", ins.op_str))

print(f"Found {len(hits_lit)} inline / lit references")
for ins_addr, kind, info in hits_lit:
    print(f"  {ins_addr:#x}: kind={kind}  {info}")


# (3) Look at fn@0x17ECC — what is it?
print("\n\n=== (3) fn@0x17ECC body (called right after wlc_bmac_up_finish) ===")
seen = 0
for ins in md.disasm(data[0x17ECC:0x17ECC+0x40], 0x17ECC):
    annot = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s: annot = f"  ; \"{s}\""
                else: annot = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic == "bl":
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{t:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    seen += 1
    if seen >= 16: break
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end]"); break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end]"); break


# (4) String search for "wlc_bmac_up", "wlc_up", "wlc_init" — find the parent fns
print("\n\n=== (4) Search for parent-function name strings ===")
for needle in (b"wlc_bmac_up\0", b"wlc_up\0", b"wlc_init\0", b"wlc_attach\0",
               b"wlc_bmac_attach\0", b"wlc_bmac_up_prep\0", b"wlc_bmac_init\0"):
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        print(f"  string \"{needle.decode().rstrip(chr(0))}\" at file offset {idx:#x}")
        pos = idx + 1
