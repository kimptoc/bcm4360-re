"""Find the '40.0/160.0/160.0MHz' format string and its caller.
Also find the chiprev banner for comparison."""
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()

# Find all strings containing "40.0" in the blob
import re
# Broadcom fmt strings typically look like: '... %d.%d/%d.%d/%d.%dMHz\n'
# Search for "MHz" with surrounding format chars
for s in re.finditer(rb"[ -~]{5,200}MHz[ -~]*", blob):
    chunk = s.group().split(b"\x00")[0]
    print(f"  0x{s.start():06X}: {chunk!r}")

print("\n-- chiprev / phyrev banner format strings --")
for kw in [b"chiprev", b"chipid", b"chipst", b"phyrev", b"phy_rev", b"phytype"]:
    for m in re.finditer(kw, blob):
        ctx_start = max(0, m.start() - 10)
        end = blob.find(b"\x00", m.start())
        if end - ctx_start < 120:
            s = blob[ctx_start:end]
            print(f"  0x{m.start():06X} (ctx 0x{ctx_start:06X}): {s!r}")

print("\n-- BCM4360 mention in blob --")
for m in re.finditer(rb"BCM4360", blob):
    end = blob.find(b"\x00", m.start())
    if end - m.start() < 80:
        s = blob[m.start():end]
        print(f"  0x{m.start():06X}: {s!r}")
