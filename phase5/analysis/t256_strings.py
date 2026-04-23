"""Decode strings referenced by T256 node[0].fn at 0x1C98."""
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()

# Strings referenced from 0x1C98 function
for addr in [0x4069D, 0x406B2, 0x40685, 0x406D1, 0x406E5, 0x406F3, 0x58CC4]:
    try:
        end = blob.index(b"\x00", addr)
        s = blob[addr:end]
        if all(32 <= b < 127 for b in s):
            print(f"  0x{addr:06X}: {s.decode()!r}")
        else:
            print(f"  0x{addr:06X}: <non-ASCII {len(s)}B> {s[:30].hex()}")
    except ValueError:
        print(f"  0x{addr:06X}: <no null terminator>")

# Also dump a few bytes before 0x40685 to catch the full string if 0x40685 is mid-string
print()
for addr in [0x40680, 0x40698, 0x406AC, 0x406CC, 0x406E0, 0x406F0]:
    end = blob.index(b"\x00", addr) if blob.find(b"\x00", addr) > 0 else addr + 40
    s = blob[addr:end]
    printable = all(32 <= b < 127 for b in s) if len(s) > 0 else False
    if printable:
        print(f"  0x{addr:06X}: {s.decode()!r}")
