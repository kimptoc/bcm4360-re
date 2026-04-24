#!/usr/bin/env python3
"""T273 final check: analyze fn@0x1146C (the wlc ISR registered via
hndrte_add_isr at 0x67774). Determine if its trigger is host-dependent.

Decision criteria:
  - If fn@0x1146C reads a hardware mailbox register (like pciedngl_isr
    reads FN0_0 bit), its trigger is host-dependent.
  - If it reads a timer-tick or internal counter, its trigger is
    fw-internal.

Also: trace the r0 argument to hndrte_add_isr in fn@0x67614 — r0 is the
class-context pointer, which determines which HW-class dispatcher the
unmask goes through. For pciedngl it was [0x6296C]. What is wlc's?
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


# Step 1: dump fn@0x67614 top to find how 'sb' (r9) is initialized
print("=== fn@0x67614 top — find sb (r9) setup ===\n")
for i in md.disasm(data[0x67614:0x67614+80*4], 0x67614, count=80):
    # Only print instructions that touch sb / r9
    op = i.op_str
    if "sb" in op or "r9" in op:
        annot = ""
        if i.mnemonic in ("ldr", "ldr.w") and "[pc" in op:
            try:
                imm_str = op.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  ← lit = {v:#x}"
            except Exception:
                pass
        print(f"  {i.address:#06x}: {i.mnemonic:<8} {op}{annot}")
    if i.address > 0x67774:
        break


# Step 2: disasm fn@0x1146C body
print("\n=== fn@0x1146C body (the wlc-registered ISR) — what HW does it read? ===\n")

def find_next_prologue(start, max_scan=4096):
    for off in range(start + 2, min(start + max_scan, len(data)), 2):
        hw = struct.unpack_from("<H", data, off)[0]
        if (hw & 0xFE00) == 0xB400 or hw == 0xE92D:
            return off
    return None

nxt = find_next_prologue(0x1146C)
ext = min((nxt - 0x1146C) if nxt else 512, 512)
print(f"  fn extent ~{ext} bytes\n")

insns = list(md.disasm(data[0x1146C:0x1146C+ext+8], 0x1146C, count=0))
insns = [i for i in insns if i.address < 0x1146C + ext]

# Collect literals referenced (especially anything that looks like HW register offset)
strs = set()
literal_loads = []  # list of (insn_addr, lit_addr, lit_val)
for i in insns:
    annot = ""
    if i.mnemonic in ("ldr", "ldr.w") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                literal_loads.append((i.address, lit_addr, v))
                annot = f"  ← lit = {v:#x}"
                if 0 < v < len(data):
                    s = bytearray()
                    for k in range(80):
                        if v + k >= len(data): break
                        c = data[v + k]
                        if c == 0: break
                        if 32 <= c < 127: s.append(c)
                        else: s = None; break
                    if s and len(s) >= 4:
                        strs.add(s.decode("ascii"))
                        annot += f" '{s.decode('ascii')}'"
        except Exception:
            pass
    bl_annot = ""
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t == 0xA30: bl_annot = " (printf)"
            elif t == 0x14948: bl_annot = " (trace)"
            elif t == 0x9936: bl_annot = " (event-mask reader — matches pciedngl_isr scheduler pattern!)"
            elif t == 0x63C24: bl_annot = " (hndrte_add_isr — recursive!)"
        except ValueError:
            pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}{bl_annot}")

print(f"\n  STRINGS in fn@0x1146C body:")
for s in sorted(strs):
    print(f"    {s!r}")

print(f"\n  ALL literal u32 loads:")
for ia, la, v in literal_loads:
    print(f"    {ia:#06x}: ldr → lit@{la:#x} = {v:#x}")
