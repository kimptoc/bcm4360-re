"""T289: search blob for any write to MAILBOXMASK (PCIE2 reg base + 0x4C).

PCIE2 register base (per test.218 host-side enum) = 0x18003000.
MAILBOXMASK offset = 0x4C.
Absolute MMIO address = 0x1800304C.

Patterns to detect:
1. Direct literal 0x1800304C anywhere in blob.
2. PCIE2 base 0x18003000 literal followed by `add #0x4C` then `str`.
3. STR with imm offset 0x4C — too noisy without context, but combined
   with an LDR pc-rel of 0x18003000 nearby it would be specific.
4. Per-class corereg/setctl call (class 1 thunk @ 0x2B8C writes wrap+0x408,
   not reg-base+0x4C) — already known not to be the path.

If we find ZERO writers anywhere in the blob targeting 0x1800304C, that
is structural confirmation that fw NEVER unmasks its PCIE2 MAILBOXMASK
from inside the blob. Combined with T241/T280/T284 (host-side writes
silently drop), the wake-gate is structurally closed.
"""
import struct, re

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

print(f"Blob size: {len(data)} bytes")

# (1) Direct literal 0x1800304C
target_lit = 0x1800304C
target_bytes = target_lit.to_bytes(4, "little")
hits_direct = []
i = 0
while i < len(data) - 4:
    if data[i:i+4] == target_bytes:
        hits_direct.append(i)
    i += 1
print(f"\nDirect 0x1800304C literal hits: {len(hits_direct)}")
for h in hits_direct:
    print(f"  blob_off={h:#x}")

# (2a) PCIE2 base literal 0x18003000
pcie_base_lit = 0x18003000
pcie_base_bytes = pcie_base_lit.to_bytes(4, "little")
hits_pcie_base = []
i = 0
while i < len(data) - 4:
    if data[i:i+4] == pcie_base_bytes:
        hits_pcie_base.append(i)
    i += 1
print(f"\nPCIE2-base 0x18003000 literal hits: {len(hits_pcie_base)}")
for h in hits_pcie_base:
    print(f"  blob_off={h:#x}")

# (2b) any literal in 0x18003000..0x18003100 range
print(f"\nAny 0x180030xx (PCIE2 reg in low 256 bytes) literal hits:")
i = 0
near_pcie_hits = []
while i < len(data) - 4:
    v = struct.unpack_from("<I", data, i)[0]
    if 0x18003000 <= v < 0x18003100:
        near_pcie_hits.append((i, v))
    i += 4  # only check 4-byte aligned
print(f"  count: {len(near_pcie_hits)}")
for h, v in near_pcie_hits[:30]:
    print(f"  blob_off={h:#x} val={v:#x}")

# (3) Look for ANY core base in 0x18000000..0x18010000 to catalog what fw knows
print(f"\nAll backplane MMIO literals (0x18000000..0x18010000) at 4-byte alignment:")
all_backplane_lits = {}
i = 0
while i < len(data) - 4:
    v = struct.unpack_from("<I", data, i)[0]
    if 0x18000000 <= v < 0x18010000:
        if v not in all_backplane_lits:
            all_backplane_lits[v] = []
        all_backplane_lits[v].append(i)
    i += 4
for v in sorted(all_backplane_lits.keys()):
    locs = all_backplane_lits[v]
    print(f"  {v:#x}  ({len(locs)} hit{'s' if len(locs)>1 else ''})  first@{locs[0]:#x}")

# (4) Search for the wrapper version 0x18103000 (PCIE2 wrapper)
print(f"\nPCIE2-wrapper 0x18103000 literal hits:")
v = 0x18103000
i = 0
hits_wrap = []
while i < len(data) - 4:
    if data[i:i+4] == v.to_bytes(4, "little"):
        hits_wrap.append(i)
    i += 1
print(f"  count: {len(hits_wrap)}")
for h in hits_wrap:
    print(f"  blob_off={h:#x}")
