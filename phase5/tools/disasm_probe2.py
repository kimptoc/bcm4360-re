#!/usr/bin/env python3
"""Disassemble BCM4360 firmware around pciedngl_probe to find the spin loop."""

import sys
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/tmp/bcm4360_disasm.txt"

with open(FW_PATH, "rb") as f:
    fw = f.read()

lines = []
def p(s=""):
    lines.append(s)

p(f"Firmware size: {len(fw)} bytes (0x{len(fw):x})")

# Find key strings
probe_str_off = fw.find(b"pciedngl_probe\x00")
p(f"String 'pciedngl_probe' at offset 0x{probe_str_off:x}")

probe_fail_off = fw.find(b"pcidongle_probe:hndrte_add_isr failed")
p(f"String 'pcidongle_probe:hndrte_add_isr' at offset 0x{probe_fail_off:x}")

rte_str_off = fw.find(b"RTE (PCI-CDC)")
p(f"String 'RTE (PCI-CDC)' at offset 0x{rte_str_off:x}")

proto_off = fw.find(b"proto_attach")
p(f"String 'proto_attach' at offset 0x{proto_off:x}")

cinit_off = fw.find(b"c_init: add PCI device")
p(f"String 'c_init: add PCI device' at offset 0x{cinit_off:x}")

call_proto_off = fw.find(b"call proto_attach")
p(f"String 'call proto_attach' at offset 0x{call_proto_off:x}")

proto_fail_off = fw.find(b"proto_attach failed")
p(f"String 'proto_attach failed' at offset 0x{proto_fail_off:x}")

watchdog_off = fw.find(b"Watchdog reset bit set")
p(f"String 'Watchdog reset bit set' at offset 0x{watchdog_off:x}")

# Vector table
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
p("\nVector table (first 8 entries):")
for insn in md.disasm(fw[0:0x20], 0):
    p(f"  0x{insn.address:08x}: {insn.mnemonic}\t{insn.op_str}")

# Search for literal pool references to key strings
# Try base addresses 0x0 and 0x180000
p("\n=== Searching for string references (literal pools) ===")

for base in [0x0, 0x180000]:
    p(f"\n--- Base 0x{base:x} ---")
    for name, str_off in [("pciedngl_probe", probe_str_off),
                          ("pcidongle_probe:add_isr", probe_fail_off),
                          ("RTE (PCI-CDC)", rte_str_off),
                          ("call proto_attach", call_proto_off),
                          ("proto_attach failed", proto_fail_off),
                          ("c_init: add PCI", cinit_off),
                          ("Watchdog reset", watchdog_off)]:
        if str_off < 0:
            continue
        target = base + str_off
        target_bytes = target.to_bytes(4, 'little')
        pos = 0
        while True:
            pos = fw.find(target_bytes, pos)
            if pos == -1:
                break
            if pos % 4 == 0:
                p(f"  '{name}' -> addr 0x{target:x} in literal pool at fw offset 0x{pos:x}")
            pos += 1

# Now disassemble key code regions
# The strings are in the 0x40000+ range (data section)
# Code referencing them should be in the code section (lower addresses)
# Let's find the code that references the probe strings

# With base=0x180000, "pciedngl_probe" at 0x1C07F2
# Literal pool entry for this should be somewhere in code, containing 0x001C07F2

# Let's also try a simpler approach: find the function by looking at
# the console output order. The firmware prints:
# 1. Chipcommon info
# 2. wl_probe called
# 3. pciedngl_probe called
# 4. RTE (PCI-CDC) banner
# Then hangs.
#
# The "called" suffix suggests a printf("%s called", __FUNCTION__) pattern
# or printf("pciedngl_probe called\n")
# But "pciedngl_probe called" isn't in the binary as a single string...
# The console shows it though. Let me check more carefully.

# Actually, the console buffer from test.85 shows:
# "pciedngl_probe called" as text in the console ring
# But the binary has "pciedngl_probe" at 0x407f2
# The "called" might come from a format string like "%s called"

called_fmt = fw.find(b"%s called")
if called_fmt >= 0:
    p(f"\nString '%%s called' at offset 0x{called_fmt:x}")
else:
    p("\nNo '%%s called' format string found")
    # Try variants
    for s in [b" called\n", b" called\x00", b"called"]:
        off = fw.find(s)
        if off >= 0:
            # Show context
            ctx_start = max(0, off - 20)
            ctx = fw[ctx_start:off+len(s)+10]
            p(f"  Found '{s}' at 0x{off:x}, context: {ctx}")

# Let's try a completely different approach - just disassemble a wide area
# around where we expect the probe function to be
# The strings are at 0x40000+ so the code likely references them from nearby
# Let's look at code around 0x3E000-0x40000

p("\n\n=== Full disassembly: 0x3F800..0x40200 (code near string table) ===\n")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
start = 0x3F800
end = 0x40200
chunk = fw[start:end]
for insn in md.disasm(chunk, start):
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# Also look for tight loops (branch-to-self or short backward branches)
# which would be the spin pattern
p("\n\n=== Searching for tight loops (branch-to-self or short backward branches) ===\n")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
# Scan the entire code section
chunk = fw[0:0x40000]
for insn in md.disasm(chunk, 0):
    if insn.mnemonic in ('b', 'b.n', 'b.w'):
        # Parse target address
        try:
            target_addr = int(insn.op_str.replace('#', ''), 0)
            if target_addr == insn.address:
                p(f"  SPIN (branch-to-self): 0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")
            elif 0 < insn.address - target_addr <= 16:
                p(f"  TIGHT LOOP (back {insn.address - target_addr}): 0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")
        except ValueError:
            pass

# Write output
with open(OUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Output written to {OUT_PATH}")
print(f"Total lines: {len(lines)}")
