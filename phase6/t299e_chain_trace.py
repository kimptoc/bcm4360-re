"""T299e: identify fn@0x1164A (caller of wlc_up) — what triggers wlc_up?

Also: dump wlc_bmac_up_prep body to see if it tail-calls into wlc_bmac_up_finish
or just registers it for later.

And: dump wlc_up body to see what it does.
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


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


def dump_fn(name, start, max_size=0x300):
    print(f"\n=========== {name} @ {start:#x} ===========\n")
    chunk = data[start:start + max_size]
    seen = 0
    for ins in md.disasm(chunk, start):
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
                    elif val & 1 and 0x1000 < val < len(data):
                        annot = f"  ; lit={val:#x} → fn@{val-1:#x}"
                    else:
                        annot = f"  ; lit={val:#x}"
            except: pass
        elif ins.mnemonic == "bl":
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                annot = f"  → fn@{t:#x}"
            except: pass
        elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
            try:
                t = int(ins.op_str.lstrip("#").strip(), 16)
                if t == 0x17ED6:
                    annot = "  >>> tail-call wlc_bmac_up_finish <<<"
                elif t == 0x17ECC:
                    annot = "  → tail-call fn@0x17ECC (wlc_intrson?)"
            except: pass
        elif ins.mnemonic == "blx":
            annot = "  → indirect call (fn-ptr)"
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
        seen += 1
        if seen >= 40: print("  ... (truncated)"); break
        if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end pop pc]"); break
        if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end bx lr]"); break


# (a) fn@0x1164A — caller of wlc_up
dump_fn("fn@0x1164A (caller of wlc_up)", 0x1164A, 0x80)

# (b) wlc_up body
dump_fn("wlc_up @ 0x18FFC", 0x18FFC, 0x200)

# (c) wlc_bmac_up_prep body (truncated)
dump_fn("wlc_bmac_up_prep @ 0x15DA8", 0x15DA8, 0x100)

# (d) Also search for "wlc_iovar" and other potential CDC/ioctl handler strings
print("\n\n=== Search for ioctl/iovar/ucode entry-point strings ===")
for needle in (b"wlc_iovar\0", b"wlc_ioctl\0", b"WLC_UP", b"WLC_DOWN", b"wlc_doioctl\0",
               b"wlc_dohandler\0", b"wlc_event_if\0", b"wlc_dpc\0",
               b"wlc_init\0", b"wlc_pub\0"):
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        print(f"  string \"{needle.decode().rstrip(chr(0))}\" at file offset {idx:#x}")
        pos = idx + 1
