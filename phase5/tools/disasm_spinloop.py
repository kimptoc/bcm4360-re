#!/usr/bin/env python3
"""Deep analysis of the spin loop at 0x168 and its callers."""

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
import struct

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/tmp/bcm4360_spin.txt"

with open(FW_PATH, "rb") as f:
    fw = f.read()

lines = []
def p(s=""):
    lines.append(s)

def read32(offset):
    return struct.unpack_from('<I', fw, offset)[0]

# ==========================================
# The ONLY tight loop in the firmware is at 0x168:
#   0x160: sub sp, #0x30
#   0x162: ldr r4, [pc, #0x24]  → loads from 0x188
#   0x164: ldr r4, [r4]         → dereferences the pointer
#   0x166: cmp r4, #0
#   0x168: beq #0x168           → SPIN if zero!
#   0x16a: mov r0, sp
#   0x16c: blx r4               → call through function pointer
# ==========================================

p("=" * 70)
p("Spin loop at 0x168 — detailed analysis")
p("=" * 70)

# What's at 0x188 (the literal pool)?
val_188 = read32(0x188)
p(f"\nLiteral pool at 0x188 = 0x{val_188:08x}")
p(f"This is a pointer to a function pointer.")
p(f"The loop loads *0x{val_188:08x}, and spins while it's NULL.")
p(f"Once it becomes non-NULL, it calls through it with sp as arg.")

# Disassemble the full function containing the spin
p("\n--- Full function around 0x168 ---")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0x138:0x1A0], 0x138):
    annotation = ""
    if insn.address == 0x168:
        annotation = "  ; <<< SPIN LOOP — waits for function pointer to be set"
    elif insn.address == 0x162:
        annotation = f"  ; loads 0x{val_188:08x} (pointer to function pointer)"
    elif insn.address == 0x164:
        annotation = f"  ; dereferences → reads *0x{val_188:08x}"
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}{annotation}")

# ==========================================
# Who calls this function?
# ==========================================
p("\n" + "=" * 70)
p("Who calls the spin loop function?")
p("=" * 70)

# The function likely starts at some push before 0x160
# Let's check what's at 0x138 onwards
p("\nLooking for function entry before spin loop...")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0x100:0x1A0], 0x100):
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# The spin is at 0x168. What function contains it?
# The sub sp, #0x30 at 0x160 is suspicious but no push before it.
# Let's check the vector table - 0x168 might be an exception handler

p("\n--- Vector table analysis ---")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0:0x20], 0):
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# Check where the vector table branches lead
p("\n--- Vector table targets ---")
vectors = []
for insn in md.disasm(fw[0:0x20], 0):
    if insn.mnemonic.startswith('b'):
        try:
            target = int(insn.op_str.replace('#', ''), 0)
            vectors.append((insn.address, target))
            p(f"  Vector {insn.address}: -> 0x{target:05x}")
        except ValueError:
            pass

# Check the first vector target (reset handler)
p("\n--- Reset handler (vector 0 -> 0x20) ---")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0x20:0x68], 0x20):
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# ==========================================
# Now let's check: WHO sets the value at 0x{val_188:08x}?
# ==========================================
p("\n" + "=" * 70)
p(f"Who writes to address 0x{val_188:08x}? (the function pointer that breaks the spin)")
p("=" * 70)

# Search for STR instructions that target this address
# The address 0x{val_188:08x} would be loaded via LDR from a literal pool
# Let's find literal pool entries containing this value
target_bytes = struct.pack('<I', val_188)
pos = 0
refs = []
while True:
    pos = fw.find(target_bytes, pos, 0x60000)
    if pos == -1:
        break
    if pos % 4 == 0:
        refs.append(pos)
    pos += 1

p(f"Literal pool entries containing 0x{val_188:08x}: {['0x%x' % r for r in refs]}")

# For each ref, show surrounding code
for ref in refs[:10]:
    p(f"\n--- Code around literal pool ref at 0x{ref:x} ---")
    func_start = max(0, ref - 0x80)
    func_end = min(len(fw), ref + 0x20)
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    for insn in md.disasm(fw[func_start:func_end], func_start):
        annotation = ""
        if insn.address == ref:
            annotation = f"  ; << literal pool: 0x{val_188:08x}"
        # Check if this instruction stores to the address
        if 'str' in insn.mnemonic and insn.address < ref:
            annotation = "  ; << STORE — might write the function pointer"
        p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}{annotation}")

# ==========================================
# Check the c_init flow more carefully
# ==========================================
p("\n" + "=" * 70)
p("c_init / rtecdc init — find the function that sets up pciedngl")
p("=" * 70)

# The string "%s:   call proto_attach" at 0x40ACB
# and "%s: proto_attach failed" at 0x40AE2
# and "%s:   c_init: add PCI device" at 0x40C42 (well, "c_init: add PCI device" at 0x40C48)
# These are in rtecdc.c's c_init function

# Let's search more broadly for literal pool refs
# The strings use %s format, so the function name is passed separately
# "rtecdc.c" at 0x40C79 would be referenced
for s_name, s_off in [("rtecdc.c", 0x40C79), ("call proto_attach", 0x40ACB),
                       ("proto_attach failed", 0x40AE2), ("c_init: add PCI", 0x40C42)]:
    refs = []
    target_bytes = struct.pack('<I', s_off)
    pos = 0
    while True:
        pos = fw.find(target_bytes, pos, 0x60000)
        if pos == -1:
            break
        if pos % 4 == 0:
            refs.append(pos)
        pos += 1
    if refs:
        p(f"Refs to '{s_name}' (0x{s_off:x}): {['0x%x' % r for r in refs]}")
    else:
        # Try with different alignment
        p(f"No aligned refs to '{s_name}' (0x{s_off:x})")
        # Try unaligned
        target_bytes = struct.pack('<I', s_off)
        pos = 0
        found = False
        while True:
            pos = fw.find(target_bytes, pos, 0x60000)
            if pos == -1:
                break
            p(f"  Unaligned ref at 0x{pos:x}")
            found = True
            pos += 1
        if not found:
            # Maybe the string address includes a different base
            p(f"  (string might be referenced via offset, not absolute address)")

# ==========================================
# Let's look at what function 0x1E44 does more carefully
# It's the "init_function" called at the END of pciedngl_probe
# ==========================================
p("\n" + "=" * 70)
p("Function 0x1E44 detailed — the SBTOPCIE setup function")
p("=" * 70)

# 0x1E44 does:
# ldr r3, [pc, #0x44] → literal at 0x1E8C = ?
val_1e8c = read32(0x1E8C)
p(f"Literal pool at 0x1E8C = 0x{val_1e8c:08x}")

# 0x1E52: ldr r1, [r3, #4] — loads from *(val_1e8c + 4)
# 0x1E54: bic r1, r1, #0xfc000000 — clear top 6 bits
# 0x1E58: orr r1, r1, #0x8000000 — set bit 27
# 0x1E5C: str r1, [r0, #0x38] — store at struct+0x38
# 0x1E5E: ldr r0, [r3, #4]
# 0x1E60: and r0, r0, #0xfc000000 — keep top 6 bits
# 0x1E64: orr r0, r0, #0xc — set bits 3:2
# 0x1E68: str.w r0, [r2, #0x100] — WRITE to MMIO offset 0x100!
p("This function writes to MMIO offset 0x100 (SBTOPCIE translation reg)!")
p("It also calls 0x2F18 and 0x2DF0, then tails to 0x1DD4")

# What's at 0x2F18?
p("\n--- Function at 0x2F18 ---")
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0x2F18:0x2FA0], 0x2F18):
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

with open(OUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Output written to {OUT_PATH}")
print(f"Total lines: {len(lines)}")
