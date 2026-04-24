#!/usr/bin/env python3
"""T272-FW: find direct BL/BLX callers using capstone (more reliable than
the hand-rolled BL decoder). Disassemble the whole code region in Thumb
mode and collect every `bl` / `blx` instruction targeting known addresses.

Also dump the context around each caller so we can identify the caller fn.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

# Code region: per T254 analysis fw code lives from ~0x0 to ~0x70000;
# data/strings run roughly from 0x40000 onwards interleaved. Rather than
# parse the FLT/ELF-like headers, disassemble the whole file and rely on
# target-address matching as our filter.
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

ANCHORS = {
    0x1C98: "pciedngl_isr",
    0x1E90: "pcidongle_probe",
    0x63C24: "hndrte_add_isr",
    0x6A954: "wlc_phy_attach",
    # These are fn-body guesses; caller-BL-instruction-address = saved-LR - 4
    0x68D2A: "BL-to-X at 0x68d2a (returns to 0x68d2e, T251 wlc_attach)",
    0x6831C: "BL-to-X at 0x6831c (returns to 0x68320, T251 wlc_bmac_attach)",
}


def find_function_start(addr):
    for back in range(0, 4096, 2):
        cand = addr - back
        if cand < 0:
            break
        hw = struct.unpack_from("<H", data, cand)[0]
        if (hw & 0xFE00) == 0xB400:
            return cand
        if hw == 0xE92D:
            return cand
    return None


# Pass 1: collect ALL bl/blx instructions in the blob.
print("Scanning blob with capstone (Thumb) for bl/blx ...")
all_calls = []  # list of (insn_addr, target, mnemonic)
# Iterate at 2-byte alignment; capstone will sometimes complain but we skip.
# Disassemble in 64KB chunks to keep memory bounded.
CHUNK = 64 * 1024
for base in range(0, len(data), CHUNK):
    block = data[base:base + CHUNK + 8]  # +8 for instruction straddling
    for i in md.disasm(block, base, count=0):
        if i.mnemonic in ("bl", "blx"):
            # op_str is like "#0x1c98" — parse
            t = i.op_str.strip()
            if t.startswith("#"):
                try:
                    tgt = int(t[1:], 16)
                    all_calls.append((i.address, tgt, i.mnemonic))
                except ValueError:
                    pass
print(f"  found {len(all_calls)} direct bl/blx instructions")


# Pass 2: for each anchor, filter matching calls and report.
for target_addr, name in ANCHORS.items():
    hits = [c for c in all_calls if c[1] == target_addr or c[1] == (target_addr | 1)]
    print(f"\n=== callers of {name} ({target_addr:#06x}) ===  [{len(hits)} direct calls]")
    for addr, tgt, mnem in hits[:30]:
        fn = find_function_start(addr)
        print(f"  {mnem} #{tgt:#06x}  at {addr:#06x}   (caller fn@{fn:#06x}, +{addr-fn:#x})"
              if fn else
              f"  {mnem} #{tgt:#06x}  at {addr:#06x}   (caller fn=?)")
