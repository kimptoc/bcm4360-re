"""T286: dump static contents of wlc device struct at 0x58EFC.

Hypothesis: wl_probe's r0 = wlc device struct address (0x58EFC).
That makes r7 (= r0) the base of this struct, and fn@0x1146C's
[r0+0x18] = *(0x58F14).

If 0x58F14 contains another static address, we keep walking the
chain. Each static pointer resolves a layer.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def flag(v):
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000: return "PCIe2 MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO"
    if 0 < v < len(data):
        # check if points at a string
        s = bytearray()
        for k in range(100):
            if v + k >= len(data): break
            c = data[v + k]
            if c == 0: break
            if 32 <= c < 127: s.append(c)
            else: s = None; break
        if s and len(s) >= 4:
            return f"STRING '{s.decode()}'"
        return f"code/data ptr @{v:#x}"
    if 0 < v < 0xA0000: return "TCM offset"
    if v < 0x10000: return f"small val {v:#x}"
    return "unclassified"


def dump_struct(base, nbytes, label):
    print(f"\n=== {label} [0x{base:x}..0x{base + nbytes:x}] ===")
    for off in range(0, nbytes, 4):
        addr = base + off
        if addr + 4 > len(data):
            break
        v = struct.unpack_from("<I", data, addr)[0]
        print(f"  {addr:#7x} (+0x{off:03x}) = {v:#010x}  [{flag(v)}]")


# wlc device struct per T272
dump_struct(0x58EFC, 0x50, "wlc device struct at 0x58EFC")

# pciedngl device struct for comparison (base per T272 mention "~0x58C88")
dump_struct(0x58C88, 0x40, "pciedngl device struct at ~0x58C88")

# wlc callback ctx chain — if [r7+0x18] = [0x58F14], read that too
print("\n=== chain-resolve attempt: follow [0x58F14] ===")
v = struct.unpack_from("<I", data, 0x58F14)[0]
print(f"  *(0x58F14) = {v:#010x}  [{flag(v)}]")
if 0 < v < len(data):
    # [v+8]
    v8 = struct.unpack_from("<I", data, v + 8)[0]
    print(f"  *(*(0x58F14) + 8) = *({v + 8:#x}) = {v8:#010x}  [{flag(v8)}]")
    if 0 < v8 < len(data):
        v8_10 = struct.unpack_from("<I", data, v8 + 0x10)[0]
        print(f"  [+0x10] flag_struct = *({v8 + 0x10:#x}) = {v8_10:#010x}  [{flag(v8_10)}]")
        if 0 < v8_10 < len(data):
            v88 = struct.unpack_from("<I", data, v8_10 + 0x88)[0]
            print(f"  [+0x88] sub_struct = *({v8_10 + 0x88:#x}) = {v88:#010x}  [{flag(v88)}]")
            if 0 < v88 < len(data):
                v168 = struct.unpack_from("<I", data, v88 + 0x168)[0]
                print(f"  [+0x168] pending-events = *({v88 + 0x168:#x}) = {v168:#010x}  [{flag(v168)}]")
