#!/usr/bin/env python3
"""T272-FW: disassemble specific windows to locate call instructions
whose return-PC matches observed saved-LRs from T251 saved-state.

Observed LRs in saved-state:
  0x68D2F — someone called X, returns to 0x68D2E (T251: wlc_attach site)
  0x68321 — someone called X, returns to 0x68320 (T251: wlc_bmac_attach site)

Disassemble a 32-insn window ending at each of those PCs, find the BL /
BLX instruction whose next-PC = the saved-LR-minus-1 (thumb bit), and
print its target. Those targets are wlc_attach and wlc_bmac_attach bodies.

Also: given wlc_bmac_attach body lives around 0x6820c (from the
find_function_start of 0x68300+), dump its prologue to confirm.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def window(addr, insns_before=16, insns_after=4):
    """Disassemble a window around `addr` and return a list of insns."""
    start = max(0, addr - insns_before * 4)
    end = min(len(data), addr + insns_after * 4 + 8)
    return list(md.disasm(data[start:end], start, count=0))


def find_call_targeting_return(return_pc):
    """Find BL/BLX at (return_pc - 4) or (return_pc - 2)."""
    # Try the 4-byte Thumb-2 BL first: BL insn occupies [return_pc-4 .. return_pc-1].
    # Disassemble from return_pc-4 and see if the first insn is a bl/blx that ends at return_pc.
    for offset_back in (4, 2):
        start = return_pc - offset_back
        if start < 0:
            continue
        for i in md.disasm(data[start:start + 8], start, count=1):
            if i.mnemonic in ("bl", "blx") and i.address + i.size == return_pc:
                return i
            break
    return None


def prologue_look(addr, n=8):
    """Print n instructions starting at addr."""
    print(f"  prologue @ {addr:#06x}:")
    for i in md.disasm(data[addr:addr + n * 4 + 8], addr, count=n):
        print(f"    {i.address:#06x}: {i.mnemonic:<6} {i.op_str}")


print("=== Locating callers via saved-LR ===\n")

for name, ret_pc in [
    ("wlc_attach", 0x68D2E),
    ("wlc_bmac_attach", 0x68320),
]:
    print(f"--- {name}: saved-LR 0x{ret_pc+1:x}, return_pc = {ret_pc:#06x} ---")
    insn = find_call_targeting_return(ret_pc)
    if insn:
        print(f"  BL/BLX at {insn.address:#06x}: {insn.mnemonic} {insn.op_str}")
        # Parse target
        t = insn.op_str.strip()
        if t.startswith("#"):
            tgt = int(t[1:], 16)
            print(f"  target (stripped thumb bit) = {tgt & ~1:#06x}")
            prologue_look(tgt & ~1)
    else:
        print("  no BL/BLX found at expected location — is the LR actually a return-PC?")
    print()

# wlc_bmac_attach caller site verification:
# T253 says wlc_phy_attach is called from 0x6865e inside 'wlc_bmac_attach'.
# find_function_start(0x6865e) returned 0x6820c. Let's confirm that's the real
# prologue of wlc_bmac_attach by dumping it.
print("=== Verifying wlc_bmac_attach body at 0x6820c ===")
prologue_look(0x6820C, n=10)

# Also dump the wlc_attach body if we found it above — re-run to capture.
insn = find_call_targeting_return(0x68D2E)
if insn and insn.op_str.startswith("#"):
    tgt = int(insn.op_str[1:], 16) & ~1
    print(f"\n=== wlc_attach body at {tgt:#06x} (first 24 insns) ===")
    for i in md.disasm(data[tgt:tgt + 128], tgt, count=24):
        print(f"  {i.address:#06x}: {i.mnemonic:<6} {i.op_str}")
