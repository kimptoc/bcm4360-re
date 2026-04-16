#!/usr/bin/env python3
"""Find WFI instructions and all backward-branch loops in firmware."""

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
import struct

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/tmp/bcm4360_wfi.txt"

with open(FW_PATH, "rb") as f:
    fw = f.read()

lines = []
def p(s=""):
    lines.append(s)

# ==========================================
# 1. Find ALL WFI/WFE instructions
# ==========================================
p("=" * 70)
p("WFI/WFE instructions in firmware")
p("=" * 70)

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0:0x60000], 0):
    if insn.mnemonic in ('wfi', 'wfe'):
        # Show context
        ctx_start = max(0, insn.address - 16)
        ctx_end = min(len(fw), insn.address + 16)
        md2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        p(f"\n  {insn.mnemonic.upper()} at 0x{insn.address:05x}:")
        for ci in md2.disasm(fw[ctx_start:ctx_end], ctx_start):
            marker = " <<<" if ci.address == insn.address else ""
            p(f"    0x{ci.address:05x}: {ci.mnemonic}\t{ci.op_str}{marker}")

# ==========================================
# 2. Find ALL backward conditional branches (polling loops)
# ==========================================
p("\n" + "=" * 70)
p("ALL backward conditional branches (potential polling loops)")
p("Only showing loops with memory loads in the body")
p("=" * 70)

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0:0x60000], 0):
    if not insn.mnemonic.startswith('b'):
        continue
    if insn.mnemonic.startswith('bl') or insn.mnemonic.startswith('bx'):
        continue
    # Must be conditional (not just 'b' which is unconditional jump)
    # beq, bne, blt, bge, etc. or b with condition
    mnem = insn.mnemonic
    is_conditional = mnem not in ('b', 'b.w', 'b.n')

    try:
        target_str = insn.op_str.replace('#', '')
        target_addr = int(target_str, 0)
        backward = insn.address - target_addr
        if target_addr < insn.address and backward <= 64:
            # Check if loop body contains a load from memory (LDR/LDRH/LDRB)
            ctx_chunk = fw[target_addr:insn.address + insn.size]
            md2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
            has_load = False
            loop_instrs = []
            for ci in md2.disasm(ctx_chunk, target_addr):
                loop_instrs.append(ci)
                if ci.mnemonic.startswith('ldr') and '[' in ci.op_str:
                    has_load = True

            if has_load or backward <= 8:
                p(f"\n  Loop 0x{target_addr:05x}..0x{insn.address:05x} ({mnem}, back {backward}b, {'COND' if is_conditional else 'UNCOND'}):")
                for ci in loop_instrs:
                    marker = " <<< branch back" if ci.address == insn.address else ""
                    p(f"    0x{ci.address:05x}: {ci.mnemonic}\t{ci.op_str}{marker}")
    except (ValueError, IndexError):
        pass

# ==========================================
# 3. Search for the sharedram write pattern
# ==========================================
p("\n" + "=" * 70)
p("Searching for sharedram write (ramsize-4 = 0x9FFFC offset)")
p("=" * 70)

# The firmware should write to TCM[ramsize-4] = TCM[0x9FFFC] with the
# pcie_shared address. Search for references to 0x9FFFC or 0xA0000
for val in [0x9FFFC, 0xA0000, 0x9FFF0, 0x9FFE0]:
    val_bytes = struct.pack('<I', val)
    pos = 0
    while True:
        pos = fw.find(val_bytes, pos, 0x60000)
        if pos == -1:
            break
        if pos % 4 == 0:
            p(f"  0x{val:05x} in literal pool at 0x{pos:05x}")
        pos += 1

# Also search for ramsize value (0xA0000)
ramsize_bytes = struct.pack('<I', 0xA0000)
pos = 0
while True:
    pos = fw.find(ramsize_bytes, pos, 0x60000)
    if pos == -1:
        break
    if pos % 4 == 0:
        p(f"  ramsize 0xA0000 in literal pool at 0x{pos:05x}")
    pos += 1

# ==========================================
# 4. Look at where proto_attach is referenced
# ==========================================
p("\n" + "=" * 70)
p("proto_attach reference at literal pool 0x2034")
p("=" * 70)

# From first scan: "proto_attach" (0x4080F) has literal pool at 0x2034
# Let's disassemble the function around it
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
start = 0x1FD0
end = 0x20A0
p(f"\nDisassembly 0x{start:x}..0x{end:x}:")
for insn in md.disasm(fw[start:end], start):
    annotation = ""
    if insn.address == 0x2034:
        val = struct.unpack_from('<I', fw, 0x2034)[0]
        annotation = f"  ; literal pool: 0x{val:08x} = 'proto_attach'"
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}{annotation}")

# ==========================================
# 5. The key question: where does the firmware write pcie_shared?
# ==========================================
p("\n" + "=" * 70)
p("Looking for the pcie_shared / handshake write")
p("=" * 70)

# In PCI-CDC firmware, the handshake is different from FullDongle.
# FullDongle writes to ramsize-4 (0x9FFFC).
# PCI-CDC might write to a different location or use a different mechanism.
# Let's search for the string "pcie_shared" or related
for s in [b"pcie_shared", b"shared_info", b"pcie_ipc", b"pciedev_shared"]:
    off = fw.find(s)
    if off >= 0:
        p(f"  String '{s.decode()}' at offset 0x{off:x}")

# Search for writes to known handshake addresses
# The sharedram value at 0x9FFFC is currently 0xffc70038 which is the NVRAM token
# In PCI-CDC, the firmware might use BCDC protocol handshake via mailboxes instead
# Let's look for any code that writes to PCIe registers (mailboxes, doorbells)

# Search for PCIe register offset constants
for name, val in [("H2D_MAILBOX_0", 0x140), ("H2D_MAILBOX_1", 0x144),
                  ("D2H_MAILBOX_0", 0x148), ("D2H_MAILBOX_1", 0x14C),
                  ("INTSTATUS", 0x90), ("INTMASK", 0x94),
                  ("SBTOPCIMAILBOX", 0x48), ("CONFIGADDR", 0x120),
                  ("CONFIGDATA", 0x124)]:
    # These are offsets within PCIe2 core registers
    pass

# ==========================================
# 6. Disassemble the c_init function more carefully
# ==========================================
# The string "c_init: add PCI device" (0x40C48) and "rtecdc.c" (0x40C79)
# aren't found as literal pool values. Maybe they use MOVW/MOVT to load addresses.
# Let's search for MOVW #0x0C48 or MOVW with high values

p("\n" + "=" * 70)
p("Searching for MOVW/MOVT instructions loading string addresses")
p("=" * 70)

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0:0x40000], 0):
    if insn.mnemonic == 'movw':
        try:
            parts = insn.op_str.split(',')
            if len(parts) >= 2:
                imm_str = parts[1].strip().replace('#', '')
                imm = int(imm_str, 0)
                # Check if this could be the low 16 bits of a string address
                if imm == 0x0C48 or imm == 0x0C79 or imm == 0x0ACB or imm == 0x0AE2:
                    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}  ; possible string ref low-16")
        except ValueError:
            pass
    elif insn.mnemonic == 'movt':
        try:
            parts = insn.op_str.split(',')
            if len(parts) >= 2:
                imm_str = parts[1].strip().replace('#', '')
                imm = int(imm_str, 0)
                if imm == 4:  # High 16 bits = 0x0004 for strings at 0x40xxx
                    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}  ; possible string ref high-16 = 0x0004xxxx")
        except ValueError:
            pass

with open(OUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Output written to {OUT_PATH}")
print(f"Total lines: {len(lines)}")
