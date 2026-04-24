#!/usr/bin/env python3
"""T272-FW: search for key function-name strings in the blob, find their
literal-pool references, and identify where they are used.

Strings of interest for the init chain:
  wlc_attach, wlc_bmac_attach, wlc_phy_attach
  pcidongle_probe, pciedngl_isr, pciedngl_attach, pciedev_attach
  si_attach, wl_attach, hndrte_add_isr
  wlc_enable_mac, wlc_bmac_up, wlc_up
  (and other common Broadcom init milestones)
"""
import os, sys, struct

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_strings(needle):
    """Return all offsets where needle appears as a nul-terminated ASCII
    string (not a substring inside a larger string)."""
    needle_b = needle.encode("ascii") + b"\x00"
    hits = []
    off = 0
    while True:
        p = data.find(needle_b, off)
        if p < 0:
            break
        hits.append(p)
        off = p + 1
    return hits


def find_literal_refs(val):
    hits = []
    tgt = struct.pack("<I", val)
    for off in range(0, len(data) - 4, 4):
        if data[off:off+4] == tgt:
            hits.append(off)
    return hits


# Look up each string then find literal-pool references to it.
INTERESTING = [
    "wlc_attach", "wlc_bmac_attach", "wlc_phy_attach",
    "pcidongle_probe", "pciedngl_isr", "pciedngl_attach", "pciedev_attach",
    "si_attach", "wl_attach",
    "hndrte_add_isr",
    "wlc_enable_mac", "wlc_bmac_up", "wlc_up",
    "dngl_init", "pciedev_init", "pciedev_pkt_init",
    "wlc_bsinit",
    "bus_init", "pciedngl_post_attach_init",
    "wl_start", "wl_dngl_probe",
]

for s in INTERESTING:
    hits = find_strings(s)
    if not hits:
        continue
    print(f"\n=== string '{s}' at {','.join(f'{h:#x}' for h in hits)} ===")
    for h in hits:
        lit_refs = find_literal_refs(h)
        print(f"  literal-pool refs to {h:#x}: {len(lit_refs)}")
        for lr in lit_refs[:5]:
            # Find a LDR that references this pool slot
            refs = []
            for off in range(max(0, lr - 4096), lr, 2):
                hw = struct.unpack_from("<H", data, off)[0]
                if (hw & 0xF800) == 0x4800:  # thumb-1 LDR pc-rel
                    imm8 = hw & 0xFF
                    lit_addr = ((off + 4) & ~3) + imm8 * 4
                    if lit_addr == lr:
                        refs.append(("T1", off))
                if off + 2 < len(data):
                    hw2 = struct.unpack_from("<H", data, off + 2)[0]
                    if (hw == 0xF8DF) or (hw == 0xF85F):
                        imm12 = hw2 & 0xFFF
                        add = (hw & 0x0080) != 0
                        lit_addr = ((off + 4) & ~3) + (imm12 if add else -imm12)
                        if lit_addr == lr:
                            refs.append(("T2.W", off))
            refs_str = ",".join(f"{k}@{o:#x}" for k, o in refs[:3])
            print(f"    lit@{lr:#x}  ldr-refs: {refs_str or '(none found)'}")
