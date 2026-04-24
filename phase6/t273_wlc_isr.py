#!/usr/bin/env python3
"""T273 focused check: disasm around 0x67774 inside fn@0x67614 (the wlc-probe
top) to identify the fn registered via hndrte_add_isr, trace the flag bit
allocation, and decide whether it's host-dependent.
"""
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


# Disasm fn@0x67614 body with focus on 0x67774 callsite region
print("=== fn@0x67614 body (wlc-probe top) — focus on 0x67774 hndrte_add_isr callsite ===\n")

# We want to see maybe 20 insns BEFORE 0x67774 (args being set up) and the call itself
# Backtrack by ~40 bytes
start_dump = 0x67770 - 40
end_dump = 0x67774 + 16

for i in md.disasm(data[start_dump:end_dump+16], start_dump, count=30):
    # Add annotations for known function targets
    annot = ""
    if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
        try:
            t = int(i.op_str[1:], 16)
            if t == 0x63C24:
                annot = "  ← hndrte_add_isr"
            elif t == 0xA30:
                annot = "  ← printf"
        except ValueError:
            pass
    # For ldr pc-rel, try to resolve the literal
    if i.mnemonic in ("ldr", "ldr.w") and "[pc" in i.op_str:
        try:
            imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
            lit_addr = ((i.address + 4) & ~3) + imm
            if 0 <= lit_addr < len(data) - 4:
                v = struct.unpack_from("<I", data, lit_addr)[0]
                annot = f"  ← lit@{lit_addr:#x} = {v:#x}"
                # Is it a thumb fn-ptr?
                if v & 1 and 0 < v < len(data):
                    body = v & ~1
                    # Try to disasm first insn
                    try:
                        first = list(md.disasm(data[body:body+4], body, count=1))
                        if first:
                            annot += f" (fn @ {body:#x}: {first[0].mnemonic})"
                    except Exception:
                        pass
                # Or a string?
                elif 0 < v < len(data):
                    s = bytearray()
                    for k in range(80):
                        if v + k >= len(data): break
                        c = data[v + k]
                        if c == 0: break
                        if 32 <= c < 127: s.append(c)
                        else: s = None; break
                    if s and len(s) >= 4:
                        annot += f" ('{s.decode('ascii')}')"
        except Exception:
            pass
    print(f"  {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")

# Also: look at fn@0x67614's context setup — what gets passed as ctx (r0) to hndrte_add_isr?
# hndrte_add_isr signature per T269: r0=ctx_ptr (maybe [0x6296C]), r1=arg, r2=name?, r3=fn-ptr
# The fn-ptr is in r3 per T269 §4 ("assembles a call to 0x63C24 with the pciedngl_isr fn-ptr
# literal (0x1C99) in r3").
# In the pcidongle_probe case, ctx was [0x6296C] — the HW-class context pointer.
# Check what ctx fn@0x67614 passes.

# Separate printout: walk forward through fn@0x67614 to find the hndrte_add_isr call again
# and look for the fn-ptr literal set up just before it.
print("\n=== Wider scan of fn@0x67614 (from entry to 50 insns past hndrte_add_isr call) ===")
dump_start = 0x67614
insns = list(md.disasm(data[dump_start:dump_start+0x200], dump_start, count=0))
# Find the bl #0x63c24 in this range
hndrte_calls = [i for i in insns if i.mnemonic == "bl" and i.op_str == "#0x63c24"]
if not hndrte_calls:
    print("  (no bl 0x63c24 found in disasm range)")
else:
    call = hndrte_calls[0]
    print(f"  hndrte_add_isr call at {call.address:#x}")
    # Show 20 insns before call
    print(f"  setup (20 insns before call):")
    idx = insns.index(call)
    for i in insns[max(0, idx-20):idx+1]:
        annot = ""
        if i.mnemonic in ("ldr", "ldr.w") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  ← lit = {v:#x}"
                    if v & 1 and 0 < v < len(data):
                        try:
                            first = list(md.disasm(data[v & ~1:(v & ~1)+8], v & ~1, count=2))
                            if first:
                                annot += f" (fn: {first[0].mnemonic} {first[0].op_str})"
                        except Exception:
                            pass
                    elif 0 < v < len(data):
                        s = bytearray()
                        for k in range(60):
                            if v + k >= len(data): break
                            c = data[v + k]
                            if c == 0: break
                            if 32 <= c < 127: s.append(c)
                            else: s = None; break
                        if s and len(s) >= 4:
                            annot += f" '{s.decode('ascii')}'"
            except Exception:
                pass
        print(f"    {i.address:#06x}: {i.mnemonic:<8} {i.op_str}{annot}")
