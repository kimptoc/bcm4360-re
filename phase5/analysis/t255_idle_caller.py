"""Find callers of 0x11D0 (the idle-loop fn that calls WFI)."""
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

def scan_lit(tgt):
    res = []
    for pv in (tgt, tgt|1):
        p = pv.to_bytes(4, "little")
        pos = 0
        while True:
            h = blob.find(p, pos)
            if h < 0: break
            res.append((h, pv))
            pos = h + 1
    return res

for tgt, desc in [(0x11D0, "idle-loop function (reaches WFI)"),
                   (0x115C, "scheduler main fn"),
                   (0x1C10, "thunk at 0x1C10 (bl from 0x11D4)"),
                   (0x1C1C, "leaf at 0x1C1C (bl from 0x11DA)")]:
    print(f"=== Callers of 0x{tgt:06X} ({desc}) ===")
    c = scan_callers(tgt)
    print(f"  BL/B.W: {len(c)}")
    for a, m in c[:10]: print(f"    0x{a:06X}: {m}")
    r = scan_lit(tgt)
    print(f"  Literal-pool refs (fn-ptr storage): {len(r)}")
    for h, v in r[:10]: print(f"    lit@0x{h:06X} = 0x{v:08X}")
    print()
