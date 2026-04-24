#!/usr/bin/env python3
"""T273 part 3: find the callsites of the 3 polling-loop candidates
(0x5198, 0x67F8C, 0x68D7C) in wlc_bmac_attach, and dump each candidate's
loop structure."""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_next_prologue(start, max_scan=4096):
    for off in range(start + 2, min(start + max_scan, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None


# Locate callsites inside wlc_bmac_attach
wbmac_insns = list(md.disasm(data[0x6820C:0x68A68], 0x6820C, count=0))

for target in [0x5198, 0x67F8C, 0x68D7C, 0x1415C]:
    print(f"\n=== callsites of {target:#x} inside wlc_bmac_attach ===")
    for i in wbmac_insns:
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == target:
                    saved_lr_relative = "BEFORE saved-LR" if i.address < 0x68320 else "AFTER  saved-LR"
                    print(f"    {i.address:#06x}: bl #{t:#x}   ({saved_lr_relative})")
            except ValueError:
                pass


# Dump each candidate's body focusing on the loop
def dump_loop(addr, name):
    print(f"\n{'='*70}")
    print(f"=== {name} @ {addr:#x} — loop body ===")
    nxt = find_next_prologue(addr)
    ext = min((nxt - addr) if nxt else 512, 1024)
    insns = list(md.disasm(data[addr:addr+ext+8], addr, count=0))
    insns = [i for i in insns if i.address < addr + ext]
    print(f"  ({ext} bytes, {len(insns)} insns)\n")

    # Find tight loops (backward branch < 32)
    backward = [(i.address, int(i.op_str[1:], 16), i.mnemonic) for i in insns
                if i.mnemonic.startswith("b") and i.mnemonic not in ("bl", "blx")
                and i.op_str.startswith("#")]
    tight = [(ia, tgt, m) for ia, tgt, m in backward if 0 < ia - tgt < 32]

    print(f"  Tight loops detected:")
    for ia, tgt, m in tight:
        print(f"    {ia:#06x}: {m} back to {tgt:#x} (dist {ia-tgt})")
        # Dump the loop body (from tgt to ia inclusive)
        print(f"    loop body:")
        for i in insns:
            if tgt <= i.address <= ia:
                print(f"      {i.address:#06x}: {i.mnemonic:<8} {i.op_str}")
        print()

    # Also show ALL strings referenced (role identification)
    strs = set()
    for i in insns:
        if i.mnemonic in ("ldr", "ldr.w") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    if 0 < v < len(data):
                        s = bytearray()
                        for k in range(100):
                            if v + k >= len(data): break
                            c = data[v + k]
                            if c == 0: break
                            if 32 <= c < 127: s.append(c)
                            else: s = None; break
                        if s and len(s) >= 4:
                            strs.add(s.decode("ascii"))
            except Exception:
                pass
    if strs:
        print(f"  strings referenced:")
        for s in sorted(strs)[:10]:
            print(f"    {s!r}")


for addr, name in [
    (0x5198,   "0x5198"),
    (0x67F8C,  "0x67F8C"),
    (0x68D7C,  "0x68D7C"),
]:
    dump_loop(addr, name)
