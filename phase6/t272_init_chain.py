#!/usr/bin/env python3
"""T272-FW: Trace the fw init call chain between wlc_bmac_attach and
pcidongle_probe.

Known anchor points:
- pciedngl_isr       = 0x1C98 (confirmed T269)
- pcidongle_probe    = 0x1E90 (per T269 analysis section 4)
- wlc_attach          caller-return LR observed in saved-state = 0x68D2F → thumb fn ~0x68D2E
- wlc_bmac_attach     caller-return LR observed in saved-state = 0x68321 → thumb fn ~0x68320
- wlc_phy_attach     = 0x6A954 (T253)
- hndrte_add_isr     = 0x63C24

Goal: find who calls pcidongle_probe, who calls wlc_attach, and map the
call chain gap.

Run with:
  python3 /home/kimptoc/bcm4360-re/phase6/t272_init_chain.py
"""
import sys
import os
import struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"

with open(BLOB, "rb") as f:
    data = f.read()

print(f"blob: {BLOB} ({len(data)} bytes)")


def find_bl_callers(target_addr):
    """Find all Thumb BL / BLX instructions that target ``target_addr``.

    Scans all 2-byte aligned offsets in code region; decodes the 4-byte
    Thumb-2 BL encoding when the first halfword's top 5 bits are 0b11110
    and the second halfword's top 2 bits are 0b11 (BL) or 0b11 with J1/J2
    encoded (BLX swaps low bits to 0). Computes target via the standard
    Thumb-2 BL imm23 sign-extension.
    """
    target = target_addr & ~1  # Thumb-target strip
    results = []
    for off in range(0, len(data) - 4, 2):
        hw1 = struct.unpack_from("<H", data, off)[0]
        hw2 = struct.unpack_from("<H", data, off + 2)[0]
        # Thumb-2 BL / BLX: hw1 = 11110 S imm10; hw2 = 11 J1 1 J2 imm11 (BL)
        #                                       11 J1 0 J2 imm10 0  (BLX)
        if (hw1 & 0xF800) != 0xF000:
            continue
        op2_top = (hw2 & 0xD000)
        if op2_top != 0xD000 and op2_top != 0xC000:
            continue
        S = (hw1 >> 10) & 1
        imm10 = hw1 & 0x3FF
        J1 = (hw2 >> 13) & 1
        J2 = (hw2 >> 11) & 1
        is_blx = ((hw2 & 0x1000) == 0)  # BLX if op2 bit 12 is 0
        if is_blx:
            imm10L = hw2 & 0x3FF  # imm10L field for BLX (wait — BLX imm10L)
            imm11 = imm10L << 1
        else:
            imm11 = hw2 & 0x7FF
        I1 = 1 - (J1 ^ S)
        I2 = 1 - (J2 ^ S)
        # For BL the final imm = S:I1:I2:imm10:imm11:'0'
        offset = (S << 24) | (I1 << 23) | (I2 << 22) | (imm10 << 12) | (imm11 << 1)
        if S:
            offset -= (1 << 25)
        # Address of instruction as if PC-relative; BL target is pc + 4 + offset
        # For BLX, target is (pc + 4 + offset) & ~3 and the target is ARM mode
        pc = off + 4
        tgt = (pc + offset) & 0xFFFFFFFF
        if is_blx:
            tgt = tgt & ~3
        if tgt == target:
            results.append((off, "BLX" if is_blx else "BL"))
    return results


def find_function_start(addr):
    """Walk backward from addr to find the most recent likely function
    prologue (push {...} instruction). Returns the prologue address or
    None if not found within 4KB.
    """
    # Thumb push encodings:
    #   0xB4xx (push {r0-r7}) — 1 halfword
    #   0xB5xx (push {r0-r7, lr}) — 1 halfword
    #   0xE92D (push.w {...}) — 4 bytes, second halfword specifies regs
    for back in range(0, 4096, 2):
        cand = addr - back
        if cand < 0:
            break
        hw = struct.unpack_from("<H", data, cand)[0]
        # 1-halfword push: 0xB4xx / 0xB5xx
        if (hw & 0xFE00) == 0xB400:
            return cand
        # 4-byte push.w: 0xE92D
        if hw == 0xE92D:
            return cand
    return None


def who_calls(name, addr):
    callers = find_bl_callers(addr)
    print(f"\n=== callers of {name} ({addr:#06x}) ===")
    if not callers:
        print("  (no BL/BLX hits)")
        return
    for off, kind in callers:
        fn = find_function_start(off)
        fn_str = f"fn@{fn:#06x}" if fn else "fn=UNKNOWN"
        dist = off - fn if fn else -1
        print(f"  {kind} at {off:#06x}  (from {fn_str}, +{dist:#x})")
    return callers


def main():
    who_calls("pciedngl_isr",      0x1C98)  # sanity check — should match T269 hndrte_add_isr registration
    who_calls("pcidongle_probe",   0x1E90)
    who_calls("wlc_attach-body",   0x68D2E)
    who_calls("wlc_bmac_attach",   0x68320)
    who_calls("wlc_phy_attach",    0x6A954)
    who_calls("hndrte_add_isr",    0x63C24)


if __name__ == "__main__":
    main()
