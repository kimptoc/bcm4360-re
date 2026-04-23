"""Trace the tail-call chain upward from 0x11D0 and 0x115C."""
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

def find_prev_fn(addr, max_back=0x2000):
    for off in range(addr, max(0, addr-max_back), -2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d: return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0: return off
    return None

# Trace 0x2422
print("=== 0x2422 (b.w target 0x11D0) ===")
fn = find_prev_fn(0x2422)
print(f"Enclosing fn: 0x{fn:06X}")
for insn in md.disasm(blob[fn:0x2430], fn):
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")

print(f"\n=== Callers of 0x{fn:06X} ===")
for a, m in scan_callers(fn)[:5]: print(f"  0x{a:06X}: {m}")

# And 0x1962 (caller of 0x115C)
print("\n=== 0x1962 (b.w target 0x115C scheduler) ===")
fn2 = find_prev_fn(0x1962)
print(f"Enclosing fn: 0x{fn2:06X}")
for insn in md.disasm(blob[fn2:0x1970], fn2):
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")

print(f"\n=== Callers of 0x{fn2:06X} ===")
for a, m in scan_callers(fn2)[:5]: print(f"  0x{a:06X}: {m}")
