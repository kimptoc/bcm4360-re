"""T289b-3: dump the table/struct at blob 0x58f1c containing wl_probe ptr.

Result of t289b_trace_arg: wl_probe (0x67615) appears as a literal at
exactly ONE blob offset: 0x58f1c. Likely a driver-registration table
similar to upstream `struct dev_pm_ops` or `struct pcie_driver`. By
identifying neighboring fn-ptrs and any string fields, we can name
the struct and its layout.

We also need to find:
- What CALLS wl_probe at runtime (with what args).
- What `wl_probe's arg1` is — the type of struct that becomes
  wlc_callback_ctx.

Approach: dump 64 bytes around 0x58f1c. Annotate each word as
fn-ptr-or-string-or-flag.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1):
        return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data):
            break
        c = data[addr + k]
        if c == 0:
            break
        if 32 <= c < 127:
            s.append(c)
        else:
            return None
    return s.decode("ascii") if len(s) >= 3 else None


def annotate(v):
    if 0 < v < 0xA0000:
        s = str_at(v)
        if s:
            return f"STRING '{s}'"
        # check if even — could be data
        # check if thumb-fn-ptr (odd)
        if v & 1:
            return f"thumb fn-ptr fn@{v & ~1:#x}"
        return f"data ptr/fn@{v:#x}"
    if 0x18000000 <= v < 0x18010000:
        return f"backplane MMIO {v:#x}"
    return f"value {v:#x}"


# Dump 0x40 bytes before and 0x40 after 0x58f1c
center = 0x58f1c
print(f"=== Memory dump around blob 0x{center:#x} (wl_probe fn-ptr literal) ===")
print(f"  (16 words before, 16 words after — looking for struct boundaries)")
for off_idx in range(-16, 17):
    off = center + off_idx * 4
    if 0 <= off < len(data) - 4:
        v = struct.unpack_from("<I", data, off)[0]
        marker = "  <-- TARGET (wl_probe fn-ptr)" if off == center else ""
        print(f"  {off:#x}: {v:#10x}  [{annotate(v)}]{marker}")

# Also: who reads from blob offset 0x58f1c at runtime? Search for any
# literal that matches 0x58f1c (this struct's address) or addresses
# near it (it's in the data segment, so callers reference it as a
# 32-bit pointer).
print(f"\n=== Literal references TO this region (0x58f00..0x58f60) ===")
for target in range(0x58f00, 0x58f60, 4):
    p = target.to_bytes(4, "little")
    pos = 0
    hits = []
    while True:
        h = data.find(p, pos)
        if h < 0:
            break
        hits.append(h)
        pos = h + 1
    if hits:
        print(f"  reference to {target:#x}: {len(hits)} hit(s)  at {[hex(h) for h in hits[:5]]}")

# Also check for the THUMB fn-ptr 0x1c99 (pciedngl_isr) nearby
# Recall T256: pciedngl scheduler node has fn=0x1C99. Where is 0x1C99 stored?
print(f"\n=== References to 0x1c99 (pciedngl_isr thumb) ===")
for v in (0x1c98, 0x1c99):
    p = v.to_bytes(4, "little")
    pos = 0
    hits = []
    while True:
        h = data.find(p, pos)
        if h < 0:
            break
        hits.append(h)
        pos = h + 1
    print(f"  literal {v:#x}: {len(hits)} hit(s)  at {[hex(h) for h in hits[:5]]}")
