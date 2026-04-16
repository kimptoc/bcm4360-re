#!/usr/bin/env python3
"""Disassemble BCM4360 firmware - focus on the probe function at 0x1F60 area."""

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/tmp/bcm4360_disasm2.txt"

with open(FW_PATH, "rb") as f:
    fw = f.read()

lines = []
def p(s=""):
    lines.append(s)

# The literal pool entry for "pciedngl_probe" (addr 0x407f2) is at fw offset 0x1F60
# The literal pool entry for "pcidongle_probe:add_isr failed" is at 0x1F70
# These are in the code section - the literal pool is embedded in the function
# LDR Rn, [PC, #offset] can reach +1020 bytes forward from PC
# So the code referencing these pools is within ~1KB before offset 0x1F60

# Also find the "%s called" string reference
called_fmt_off = fw.find(b"%s called")
p(f"String '%%s called' at offset 0x{called_fmt_off:x}")

# Find literal pool entries for "%s called"
called_target = called_fmt_off  # base=0
called_bytes = called_target.to_bytes(4, 'little')
pos = 0
while True:
    pos = fw.find(called_bytes, pos)
    if pos == -1:
        break
    if pos % 4 == 0 and pos < 0x40000:
        p(f"Literal pool for '%%s called' at offset 0x{pos:x}")
    pos += 1

# Disassemble 0x1C00..0x2100 (the area containing the probe function + literal pools)
p("\n=== Disassembly: 0x1C00..0x2100 (probe function area) ===\n")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
start = 0x1C00
end = 0x2100
chunk = fw[start:end]
for insn in md.disasm(chunk, start):
    off = insn.address
    # Mark literal pool entries
    annotation = ""
    if off == 0x1F60:
        val = int.from_bytes(fw[0x1F60:0x1F64], 'little')
        annotation = f"  ; << literal pool: 0x{val:08x} = 'pciedngl_probe'"
    elif off == 0x1F70:
        val = int.from_bytes(fw[0x1F70:0x1F74], 'little')
        annotation = f"  ; << literal pool: 0x{val:08x} = 'pcidongle_probe:add_isr'"
    elif off >= 0x1F50 and off <= 0x1F80 and off % 4 == 0:
        val = int.from_bytes(fw[off:off+4], 'little')
        annotation = f"  ; << literal pool value: 0x{val:08x}"

    p(f"  0x{off:05x}: {insn.mnemonic}\t{insn.op_str}{annotation}")

# Also search the ENTIRE code section for spin loops
p("\n\n=== ALL tight loops in code section (0x0000..0x3FFFF) ===\n")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
chunk = fw[0:0x40000]
for insn in md.disasm(chunk, 0):
    if insn.mnemonic.startswith('b') and not insn.mnemonic.startswith('bl') and not insn.mnemonic.startswith('bx'):
        try:
            target_str = insn.op_str.replace('#', '')
            target_addr = int(target_str, 0)
            backward = insn.address - target_addr
            if target_addr <= insn.address and backward <= 32:
                # Show context: disassemble from target to this branch
                ctx_start = target_addr
                ctx_end = insn.address + insn.size
                ctx_chunk = fw[ctx_start:ctx_end]
                p(f"  --- Tight loop at 0x{insn.address:05x} (back {backward} bytes) ---")
                md2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
                for ci in md2.disasm(ctx_chunk, ctx_start):
                    p(f"    0x{ci.address:05x}: {ci.mnemonic}\t{ci.op_str}")
                p()
        except (ValueError, IndexError):
            pass

with open(OUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Output written to {OUT_PATH}")
print(f"Total lines: {len(lines)}")
