#!/usr/bin/env python3
"""Trace the pciedngl_probe call chain to find the spin loop.

Key facts from test data:
- Console prints: "pciedngl_probe called" → RTE banner → then HANGS
- The function at 0x1E90 is pciedngl_probe
- After printing the banner, something spins forever
- The banner format "RTE (%s-%s%s%s) %s on BCM%s..." is at 0x6BAE5
- "6.30.223 (TOB) (r)" is at 0x40C2F
- The banner is printed from c_init (rtecdc.c), not from pciedngl_probe itself

Strategy: Find the function that prints the RTE banner, then trace what happens AFTER.
"""

from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
import struct

FW_PATH = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"
OUT_PATH = "/tmp/bcm4360_trace.txt"

with open(FW_PATH, "rb") as f:
    fw = f.read()

lines = []
def p(s=""):
    lines.append(s)

def read32(offset):
    return struct.unpack_from('<I', fw, offset)[0]

def disasm_range(start, end, base=0):
    """Disassemble firmware from start to end offset."""
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    chunk = fw[start:end]
    result = []
    for insn in md.disasm(chunk, base + start):
        result.append(insn)
    return result

def find_literal_pool_refs(target_value, code_start=0, code_end=0x40000):
    """Find literal pool entries containing target_value in code section."""
    target_bytes = struct.pack('<I', target_value)
    refs = []
    pos = code_start
    while True:
        pos = fw.find(target_bytes, pos, code_end)
        if pos == -1:
            break
        if pos % 4 == 0:
            refs.append(pos)
        pos += 1
    return refs

# ==========================================
# 1. Trace pciedngl_probe (0x1E90) call chain
# ==========================================
p("=" * 70)
p("pciedngl_probe function at 0x1E90")
p("=" * 70)

# The function calls:
# 0x1EA6: bl 0xA30 — printf("%%s called", "pciedngl_probe")
# 0x1EAC: bl 0x66E64 — ?
# 0x1EB6: bl 0x7D60 — malloc(0, 0x3C)?
# 0x1ECE: bl 0x91C — memset
# 0x1EE8: bl 0x67358 — ? (bus attach?)
# 0x1EF2: bl 0x9948 — ?
# 0x1EFA: bl 0x9964 — ?
# 0x1F08: bl 0x64248 — hndrte_add_isr?
# 0x1F28: bl 0x63C24 — ? (registers ISR callback at 0x1C99)
# 0x1F38: bl 0x1E44 — init function

p("\nFunction calls from pciedngl_probe:")
calls = [
    (0x1EA6, 0xA30, "printf('%s called', 'pciedngl_probe')"),
    (0x1EAC, 0x66E64, "unknown_1"),
    (0x1EB6, 0x7D60, "malloc(0, 0x3C)?"),
    (0x1ECE, 0x91C, "memset?"),
    (0x1EE8, 0x67358, "bus_attach?"),
    (0x1EF2, 0x9948, "unknown_2"),
    (0x1EFA, 0x9964, "unknown_3"),
    (0x1F08, 0x64248, "hndrte_add_isr?"),
    (0x1F28, 0x63C24, "register_callback? (with 0x1C99)"),
    (0x1F38, 0x1E44, "init_function"),
]

for call_from, call_to, desc in calls:
    p(f"  0x{call_from:05x}: bl 0x{call_to:05x}  ; {desc}")

# ==========================================
# 2. Find who calls pciedngl_probe
# ==========================================
p("\n" + "=" * 70)
p("Who calls pciedngl_probe (0x1E90)?")
p("=" * 70)

# Search for BL instructions targeting 0x1E90
# Thumb-2 BL encoding: imm32 = sign_extend(S:I1:I2:imm10:imm11:0)
# Easier to just search the disassembly
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
callers = []
for insn in md.disasm(fw[0:0x40000], 0):
    if insn.mnemonic == 'bl':
        try:
            target = int(insn.op_str.replace('#', ''), 0)
            if target == 0x1E90:
                callers.append(insn.address)
                p(f"  Called from 0x{insn.address:05x}")
        except ValueError:
            pass

# ==========================================
# 3. Find the c_init / rtecdc init function
# ==========================================
p("\n" + "=" * 70)
p("Searching for c_init and RTE banner code")
p("=" * 70)

# "c_init: add PCI device" at 0x40C48
# Find refs to this string
cinit_refs = find_literal_pool_refs(0x40C48)
p(f"Literal pool refs to 'c_init: add PCI device' (0x40C48): {['0x%x' % r for r in cinit_refs]}")

# "proto_attach" at 0x4080F
proto_refs = find_literal_pool_refs(0x4080F)
p(f"Literal pool refs to 'proto_attach' (0x4080F): {['0x%x' % r for r in proto_refs]}")

# "call proto_attach" at 0x40ACB
call_proto_refs = find_literal_pool_refs(0x40ACB)
p(f"Literal pool refs to 'call proto_attach' (0x40ACB): {['0x%x' % r for r in call_proto_refs]}")

# "proto_attach failed" at 0x40AE2
proto_fail_refs = find_literal_pool_refs(0x40AE2)
p(f"Literal pool refs to 'proto_attach failed' (0x40AE2): {['0x%x' % r for r in proto_fail_refs]}")

# "Watchdog reset bit set" at 0x40C05
wdog_refs = find_literal_pool_refs(0x40C05)
p(f"Literal pool refs to 'Watchdog reset' (0x40C05): {['0x%x' % r for r in wdog_refs]}")

# "rtecdc.c" at 0x40C79
rtecdc_refs = find_literal_pool_refs(0x40C79)
p(f"Literal pool refs to 'rtecdc.c' (0x40C79): {['0x%x' % r for r in rtecdc_refs]}")

# ==========================================
# 4. Disassemble around c_init refs
# ==========================================
for ref in cinit_refs[:3]:
    p(f"\n--- Disassembly around c_init ref at 0x{ref:x} ---")
    # Find function start by scanning backwards for push
    func_start = max(0, ref - 0x200)
    func_end = min(len(fw), ref + 0x200)
    instrs = disasm_range(func_start, func_end)
    for insn in instrs:
        off = insn.address
        if off >= ref - 0x200 and off <= ref + 0x100:
            p(f"  0x{off:05x}: {insn.mnemonic}\t{insn.op_str}")

# ==========================================
# 5. Disassemble the function at 0x1E44 (called from probe at end)
# ==========================================
p("\n" + "=" * 70)
p("Function at 0x1E44 (called from pciedngl_probe end)")
p("=" * 70)
instrs = disasm_range(0x1E44, 0x1E90)
for insn in instrs:
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# ==========================================
# 6. Disassemble the callback at 0x1C98 (registered via 0x63C24)
# ==========================================
p("\n" + "=" * 70)
p("Callback at 0x1C98 (thumb entry = 0x1C99, registered from probe)")
p("=" * 70)
instrs = disasm_range(0x1C98, 0x1E00)
for insn in instrs:
    p(f"  0x{insn.address:05x}: {insn.mnemonic}\t{insn.op_str}")

# ==========================================
# 7. Find ALL tight loops in the entire firmware
# ==========================================
p("\n" + "=" * 70)
p("ALL tight loops in entire firmware (including data section)")
p("=" * 70)
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
for insn in md.disasm(fw[0:0x60000], 0):
    if insn.mnemonic.startswith('b') and not insn.mnemonic.startswith('bl') and not insn.mnemonic.startswith('bx'):
        try:
            target_str = insn.op_str.replace('#', '')
            target_addr = int(target_str, 0)
            backward = insn.address - target_addr
            if target_addr <= insn.address and 0 <= backward <= 32:
                # Show context around loop
                ctx_start = max(0, target_addr - 8)
                ctx_end = insn.address + insn.size + 4
                ctx_chunk = fw[ctx_start:ctx_end]
                md2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
                p(f"\n  Loop at 0x{insn.address:05x} -> 0x{target_addr:05x} (back {backward} bytes):")
                for ci in md2.disasm(ctx_chunk, ctx_start):
                    marker = " <<< loop back" if ci.address == insn.address else ""
                    p(f"    0x{ci.address:05x}: {ci.mnemonic}\t{ci.op_str}{marker}")
        except (ValueError, IndexError):
            pass

with open(OUT_PATH, "w") as f:
    f.write("\n".join(lines) + "\n")

print(f"Output written to {OUT_PATH}")
print(f"Total lines: {len(lines)}")
