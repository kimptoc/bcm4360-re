"""Is 0x11E0 real code? Check the enclosing function and callers."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def scan_callers(tgt):
    c = []
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+4], off):
            if insn.mnemonic in ("bl","blx","b.w","b"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"),16)
                        if t == tgt: c.append((insn.address, insn.mnemonic))
                    except: pass
            break
    return c

print("=== Disasm 0x11C0..0x1220 (literal pool boundary + what follows) ===")
for insn in md.disasm(blob[0x11C0:0x1220], 0x11C0):
    mark = " <-- bl 0x11CC" if insn.address == 0x11E0 else ""
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{mark}")

print("\n=== What precedes 0x11E0? Scan backward for a push ===")
for off in range(0x11E0, max(0, 0x11E0-0x200), -2):
    w16 = int.from_bytes(blob[off:off+2], "little")
    if w16 == 0xe92d:
        print(f"  push.w at 0x{off:06X}")
        break
    if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
        print(f"  push at 0x{off:06X}")
        break
else:
    print("  No push prologue in the 0x200 bytes before 0x11E0")

print("\n=== Callers of 0x11E0 directly ===")
for a, m in scan_callers(0x11E0): print(f"  0x{a:06X}: {m}")

print("\n=== Is 0x11E0 reached as fall-through? Trace from last known fn-end ===")
# 0x11B8 is pop (end of 0x115C). 0x11BA nop. Then 0x11BC..0x11D0 are literals.
# 0x11D0 onwards might start a new function. What's at 0x11D0?
for insn in md.disasm(blob[0x11D0:0x1210], 0x11D0):
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
