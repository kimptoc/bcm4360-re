"""Pre-T255 verification:
1. Check blob content at BSS addresses 0x6296C, 0x629A4, 0x6299C, 0x629B4.
   If zero, they're true BSS; if populated, they're initialized data.
2. Cross-check: what's at blob[0x11BC..0x11CC] (literal pool addresses)?
"""
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()

print("=== Literal pool at blob[0x11BC..0x11D0] ===")
for addr in range(0x11BC, 0x11D0, 4):
    val = int.from_bytes(blob[addr:addr+4], "little")
    print(f"  lit@0x{addr:06X} = 0x{val:08X}")

print()
print("=== Blob content at hypothesized BSS addresses ===")
for addr, desc in [(0x6296C, "something (ldr r0 at 0x1160)"),
                    (0x629A4, "callback list head"),
                    (0x6299C, "current-task ptr"),
                    (0x629B4, "sleep-flag"),
                    (0x58C98, "tick scale factor")]:
    # Guard address is within blob
    if addr + 32 > len(blob):
        print(f"  0x{addr:06X}: OUT OF BLOB RANGE (blob size=0x{len(blob):X})")
        continue
    content = blob[addr:addr+16].hex(" ", 4)
    u32 = int.from_bytes(blob[addr:addr+4], "little")
    print(f"  0x{addr:06X} ({desc}): {content}  u32=0x{u32:08X}")

# Blob size
print()
print(f"Blob size: 0x{len(blob):06X} ({len(blob)} bytes)")

# TCM typically has some region boundary: code 0..0x6BF78, then .data/.rodata, then BSS/heap.
# The addresses above (0x629A4 etc.) are BELOW 0x6BF78 — that's inside the code+data section.
# If they're initialized data, blob has their values. Check.
