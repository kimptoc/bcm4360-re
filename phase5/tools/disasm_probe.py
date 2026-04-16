#!/usr/bin/env python3
"""Disassemble BCM4360 firmware around pciedngl_probe to find the spin loop."""

import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"

with open(FW_PATH, "rb") as f:
    fw = f.read()

print(f"Firmware size: {len(fw)} bytes (0x{len(fw):x})")

# Find string "pciedngl_probe" at offset 0x407f2
probe_str_off = fw.find(b"pciedngl_probe\x00")
print(f"String 'pciedngl_probe' at offset 0x{probe_str_off:x}")

# Find all references to this string address in the binary
# In Thumb-2, string refs are typically via literal pools (LDR Rn, [PC, #imm])
# The literal pool contains the absolute address. On BCM4360 with rambase=0x180000,
# the string would be at 0x180000 + 0x407f2 = 0x1C07F2

# But let's first check what the firmware's load address is.
# The reset vector at offset 0 should tell us.
# Thumb-2: first instruction is B.W (0xF000 B800 pattern)
# Let's just search for the raw offset bytes in literal pools

# The firmware might use position-independent code or be linked at a specific base.
# Let's try to find xrefs by searching for the offset as a 32-bit LE value.

# Common BCM4360 base addresses: 0x180000 (rambase) or 0x0 (if firmware uses 0-based)
for base in [0x0, 0x180000]:
    target = base + probe_str_off
    target_bytes = target.to_bytes(4, 'little')
    pos = 0
    refs = []
    while True:
        pos = fw.find(target_bytes, pos)
        if pos == -1:
            break
        refs.append(pos)
        pos += 1
    if refs:
        print(f"  base=0x{base:x}: string addr=0x{target:x} found at offsets: {['0x%x' % r for r in refs]}")

# Also find "pcidongle_probe:hndrte_add_isr failed" string ref
probe_fail_str = fw.find(b"pcidongle_probe:hndrte_add_isr failed")
print(f"String 'pcidongle_probe:hndrte_add_isr failed' at offset 0x{probe_fail_str:x}")

# Find "pciedngl_probe called" - wait, the console shows "pciedngl_probe called"
# but the string in binary is just "pciedngl_probe" - the "called" might be separate
called_str = fw.find(b"pciedngl_probe called")
if called_str >= 0:
    print(f"String 'pciedngl_probe called' at offset 0x{called_str:x}")

# Let's also look for key strings that might indicate what pciedngl_probe is waiting for
for s in [b"pcie_shared", b"pcie_ipc", b"host_ready", b"HOSTRDY",
          b"c_init", b"proto_attach", b"wl_probe"]:
    off = fw.find(s)
    if off >= 0:
        print(f"String '{s.decode()}' at offset 0x{off:x}")

# Now let's disassemble around likely function areas.
# The console output shows the CALL ORDER:
# 1. "wl_probe called"
# 2. "pciedngl_probe called"  (firmware hangs here)
# 3. "RTE (PCI-CDC) 6.30.223 (TOB)..." (this gets printed but nothing after)
#
# Actually from the console dump, the order is:
# "Chipcommon: rev 43..." -> "wl_probe called" -> "pciedngl_probe called" -> "RTE (PCI-CDC)..."
# Then firmware hangs (no more prints)
#
# The RTE banner IS printed, meaning pciedngl_probe gets past the initial print.
# Something AFTER the banner print causes the hang.

# Let's find where "RTE (PCI-CDC)" string is
rte_str = fw.find(b"RTE (PCI-CDC)")
if rte_str >= 0:
    print(f"String 'RTE (PCI-CDC)' at offset 0x{rte_str:x}")

# And "proto_attach" which is called after the banner
proto_str = fw.find(b"proto_attach")
if proto_str >= 0:
    print(f"String 'proto_attach' at offset 0x{proto_str:x}")

print("\n--- Disassembling code sections that reference probe strings ---")

# Let's search more broadly - find any 4-byte value that could be a pointer to our strings
# in the code area (first 0x40000 bytes are likely code)
print("\nSearching for literal pool entries pointing to probe-related strings...")
interesting_strings = {
    "pciedngl_probe": probe_str_off,
    "pcidongle_probe:hndrte_add_isr": probe_fail_str,
}

if rte_str >= 0:
    interesting_strings["RTE (PCI-CDC)"] = rte_str

for base in [0x0, 0x180000]:
    print(f"\n=== Assuming firmware base address: 0x{base:x} ===")
    for name, str_off in interesting_strings.items():
        target = base + str_off
        target_bytes = target.to_bytes(4, 'little')
        pos = 0
        while True:
            pos = fw.find(target_bytes, pos)
            if pos == -1:
                break
            # Literal pool entries are typically word-aligned
            if pos % 4 == 0 and pos < 0x40000:
                print(f"  Literal pool for '{name}' (0x{target:x}) at offset 0x{pos:x}")

                # Find the LDR that references this literal pool entry
                # In Thumb-2, LDR Rn, [PC, #imm] has the PC pointing 4 bytes ahead
                # and imm is (literal_addr - (PC+4)) with PC+4 aligned to 4
                # Search backwards for LDR instructions that would reference this pool entry
                # Disassemble from ~0x200 bytes before the literal to find the function
                start = max(0, pos - 0x400)
                end = min(len(fw), pos + 0x100)
                chunk = fw[start:end]

                md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
                md.detail = True

                print(f"  Disassembly around literal pool (0x{start:x}..0x{end:x}):")
                for insn in md.disasm(chunk, base + start):
                    addr = insn.address
                    # Only print near the literal pool or branch instructions
                    off_in_fw = addr - base
                    if off_in_fw >= pos - 0x100 and off_in_fw <= pos + 0x20:
                        print(f"    0x{addr:08x}: {insn.mnemonic}\t{insn.op_str}")

            pos += 1

# Now let's do a broader disassembly of the area around the probe function strings
# The strings at 0x407f2 suggest code nearby (before strings, typically)
print("\n\n=== Disassembly of code near string table (likely probe functions) ===")
print("=== Looking at 0x3F000..0x40800 (code before string table) ===\n")

# But first, let's figure out the correct base address by looking at the vector table
# The first entry at offset 0 is a branch: 00f0 0eb8 = B.W to some address
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
chunk = fw[0:0x40]
print("Vector table:")
for insn in md.disasm(chunk, 0):
    print(f"  0x{insn.address:08x}: {insn.mnemonic}\t{insn.op_str}")

print()
