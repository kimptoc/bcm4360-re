"""T283: find who populates scheduler_ctx pointer at 0x6296c and
what value it holds (specifically, what it points at).

The scheduler_ctx pointer is loaded by hndrte_add_isr as
`ldr r6, [pc, #0x74] ; r6 = 0x6296c` then `ldr r0, [r6]`.
So `*(0x6296c)` is the actual scheduler ctx address.

Approach:
  1. Scan blob for 32-bit writes where the target is 0x6296c.
  2. Scan for literal pools containing 0x6296c (to find code that loads it).
  3. Walk the write chain backward to find the INITIAL value stored at 0x6296c.
  4. Check if that value is a TCM offset (< 0xa0000), BAR0 offset, or MMIO.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Scan for literal pools containing 0x6296c
print("=== Literal pool occurrences of 0x6296c ===")
matches = []
for off in range(0, len(data) - 4, 4):  # word-aligned
    v = struct.unpack_from("<I", data, off)[0]
    if v == 0x6296c:
        matches.append(off)
for m in matches:
    print(f"  lit@{m:#x} = 0x6296c")

# For each match, find the ldr that references it (nearby code)
print("\n=== Code loading 0x6296c (ldr r?, [pc, #...] patterns) ===")
for m in matches[:10]:
    # Look backward up to 1KB for LDR instructions that resolve to m
    for code_off in range(max(0, m - 1024), m, 2):
        hw = struct.unpack_from("<H", data, code_off)[0]
        # Thumb narrow LDR literal: 0x4800-0x4FFF (bits 15-11 = 01001)
        if (hw & 0xF800) == 0x4800:
            rt = (hw >> 8) & 0x7
            imm8 = hw & 0xFF
            lit_target = ((code_off + 4) & ~3) + imm8 * 4
            if lit_target == m:
                # Disasm window around this code for context
                window = data[code_off:min(len(data), code_off + 12)]
                ins = list(md.disasm(window, code_off, count=4))
                print(f"\n  code@{code_off:#x}: (loads lit@{m:#x} = 0x6296c)")
                for i in ins[:3]:
                    print(f"    {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}")
                break
        # Thumb wide LDR literal: 0xF85F xxxx (PC-rel wide)
        if (hw & 0xFFFF) in (0xF85F, 0xF8DF):
            nxt = struct.unpack_from("<H", data, code_off + 2)[0]
            sign = 1 if hw == 0xF8DF else -1
            imm12 = nxt & 0xFFF
            lit_target = ((code_off + 4) & ~3) + sign * imm12
            if lit_target == m:
                window = data[code_off:min(len(data), code_off + 12)]
                ins = list(md.disasm(window, code_off, count=3))
                print(f"\n  code@{code_off:#x}: (wide ldr, loads lit@{m:#x} = 0x6296c)")
                for i in ins[:3]:
                    print(f"    {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}")
                break

# Now look for writes to 0x6296c (STR instructions targeting that address
# after loading it into a reg).
# Grep the blob for the byte sequence of 0x6296c values stored at known loc.
# Easier: look for str patterns in disasm of functions that load 0x6296c.

# Also grep for related addresses: 0x629a4 (list head), 0x62960, 0x62958, etc.
related = [0x6296c, 0x629a4, 0x62960, 0x62958, 0x62954, 0x62974, 0x629b0, 0x6295c, 0x6297c, 0x62964, 0x62988, 0x62994]
print("\n=== Related scheduler-state addresses referenced in T283's disasm ===")
for addr in related:
    # Count literal-pool hits for each
    count = sum(1 for off in range(0, len(data) - 4, 4)
                if struct.unpack_from("<I", data, off)[0] == addr)
    print(f"  {addr:#x}: {count} lit-pool hit(s)")
