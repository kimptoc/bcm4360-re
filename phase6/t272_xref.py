#!/usr/bin/env python3
"""T272-FW xref helper: for each anchor address, search for:
- BL/BLX direct calls
- 4-byte-aligned literal-pool occurrences of the thumb-bit-set value
  (fn_addr | 1), which are how Thumb code references functions via LDR
- 4-byte-aligned literal-pool occurrences of the raw address
Return cross-reference sets useful for tracing indirect dispatch chains.
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()


def find_literal(val):
    """Find 4-byte-aligned occurrences of val in blob."""
    hits = []
    target = struct.pack("<I", val)
    for off in range(0, len(data) - 4, 4):
        if data[off:off+4] == target:
            hits.append(off)
    return hits


def disasm_at(addr, n=10):
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    return list(md.disasm(data[addr:addr+n*4+8], addr, count=n))


def find_function_start(addr):
    for back in range(0, 4096, 2):
        cand = addr - back
        if cand < 0:
            break
        hw = struct.unpack_from("<H", data, cand)[0]
        if (hw & 0xFE00) == 0xB400:  # push {r0-r7[,lr]}
            return cand
        if hw == 0xE92D:  # push.w
            return cand
    return None


def surrounding_ctx(off, before=3, after=3):
    """Disassemble a few insns around off."""
    start = max(0, off - before * 4)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    out = []
    for i in md.disasm(data[start:off + (after + 1) * 4], start, count=before + after + 2):
        out.append(f"    {i.address:#06x}: {i.mnemonic} {i.op_str}")
    return "\n".join(out)


def report(name, addr):
    print(f"\n=== {name} @ {addr:#06x} ===")
    # Thumb ref form (fn_addr | 1)
    thumb = addr | 1
    lit = find_literal(thumb)
    print(f"  literal-pool refs to {thumb:#010x}: {len(lit)}")
    for h in lit[:20]:
        ctx = find_function_start(h)
        # Try to find a nearby LDR that references this pool entry:
        # scan backward up to 4KB looking for an ldr pc-relative that would hit `h`
        refers_from = []
        for off in range(max(0, h - 4096), h, 2):
            hw = struct.unpack_from("<H", data, off)[0]
            # Thumb-1 LDR PC-rel: 0x4800..0x4FFF (bits 15-11 = 01001)
            if (hw & 0xF800) == 0x4800:
                imm8 = hw & 0xFF
                # target = (PC + 4) & ~3 + (imm8 * 4)
                lit_addr = ((off + 4) & ~3) + imm8 * 4
                if lit_addr == h:
                    refers_from.append(off)
            # Thumb-2 LDR.W PC-rel: 0xF8DF .. / 0xF85F ..
            if off + 4 <= len(data):
                hw2 = struct.unpack_from("<H", data, off + 2)[0]
                if (hw == 0xF8DF or hw == 0xF85F):
                    imm12 = hw2 & 0xFFF
                    add = (hw & 0x0080) != 0
                    lit_addr = ((off + 4) & ~3) + (imm12 if add else -imm12)
                    if lit_addr == h:
                        refers_from.append(off)
        ctx_str = f"ctx-fn@{ctx:#06x}" if ctx else "ctx-fn=?"
        refs_str = ",".join(f"{r:#x}" for r in refers_from) if refers_from else "no-ldr-found"
        print(f"    literal at {h:#08x}  ({ctx_str})  ldr-refs: {refs_str}")
    # Plain address
    plain = find_literal(addr)
    if plain:
        print(f"  literal-pool refs to plain {addr:#010x}: {len(plain)} (rare)")
        for h in plain[:10]:
            print(f"    plain at {h:#08x}")


def main():
    report("pciedngl_isr",      0x1C98)
    report("pcidongle_probe",   0x1E90)
    report("wlc_attach-entry-4", 0x68D2A)
    report("wlc_bmac_attach-caller-return-4", 0x6831C)
    report("wlc_phy_attach",    0x6A954)
    report("hndrte_add_isr",    0x63C24)


if __name__ == "__main__":
    main()
