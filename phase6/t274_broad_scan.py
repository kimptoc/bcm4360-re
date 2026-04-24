#!/usr/bin/env python3
"""T274-FW broader scan: find every str/orr pattern at offset 0x100 in the
blob, with 15-insn preceding context."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_fn_start(addr):
    for back in range(0, 4096, 2):
        cand = addr - back
        if cand < 0:
            break
        hw = struct.unpack_from("<H", data, cand)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return cand
    return None


# First pass: find all str instructions at #0x100
print("Pass 1: all str/strb/strh at offset 0x100:\n")
stores_at_100 = []
CHUNK = 64 * 1024
for base in range(0, len(data), CHUNK):
    block = data[base:base + CHUNK + 8]
    for i in md.disasm(block, base, count=0):
        if i.mnemonic not in ("str", "str.w", "strh", "strh.w", "strb", "strb.w"):
            continue
        # Look for "#0x100]" in op_str — means offset is exactly 0x100
        if "#0x100]" in i.op_str:
            stores_at_100.append((i.address, i.mnemonic, i.op_str))

print(f"  found {len(stores_at_100)} stores at [r?, #0x100]")
for addr, m, op in stores_at_100[:40]:
    fn = find_fn_start(addr)
    print(f"  {addr:#06x}  fn@{fn:#06x}  {m} {op}")

print(f"\nPass 2: context around top candidates (looking for #0x358 and/or orr):\n")

for addr, m, op in stores_at_100:
    # Disasm 30 preceding insns
    start = max(0, addr - 120)
    insns = list(md.disasm(data[start:addr + 8], start, count=0))
    insns = [i for i in insns if i.address <= addr]
    ctx = insns[-15:] if len(insns) >= 15 else insns

    has_358 = any("#0x358" in ii.op_str for ii in ctx)
    has_orr = any(ii.mnemonic.startswith("orr") for ii in ctx)
    has_ctx_ref = any("[0x6296c]" in ii.op_str.lower() or "lit = 0x6296c" in str(ii).lower()
                      for ii in ctx)
    # Check if any ldr in context refs literal 0x6296c
    for ii in ctx:
        if ii.mnemonic.startswith("ldr") and "[pc" in ii.op_str:
            try:
                imm_str = ii.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((ii.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    if v == 0x6296C:
                        has_ctx_ref = True
            except Exception:
                pass

    # Only print interesting ones
    if has_358 or has_orr or has_ctx_ref:
        fn = find_fn_start(addr)
        flags = []
        if has_358: flags.append("#0x358")
        if has_orr: flags.append("ORR")
        if has_ctx_ref: flags.append("ctx=[0x6296c]")
        print(f"\n  ---- {addr:#06x}  fn@{fn:#06x if fn else '?'}  [{','.join(flags)}] ----")
        for ii in ctx[-8:]:
            print(f"    {ii.address:#06x}: {ii.mnemonic:<8} {ii.op_str}")
