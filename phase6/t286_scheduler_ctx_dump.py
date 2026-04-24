"""T286: dump static contents of scheduler ctx at 0x62a98 (per T283).
Check whether [0x62a98 + 0x18] is non-zero static, which would mean
r7 = scheduler_ctx is the answer.

Also check related addresses 0x62a90, 0x62a94 (used in fn@0x672e4
scheduler ctx allocator), and 0x62b18.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()


def flag(v):
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000: return "PCIe2 MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO"
    if 0 < v < len(data):
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


def dump(base, nbytes, label):
    print(f"\n=== {label} [0x{base:x}..0x{base + nbytes:x}] ===")
    for off in range(0, nbytes, 4):
        addr = base + off
        if addr + 4 > len(data):
            break
        v = struct.unpack_from("<I", data, addr)[0]
        mark = ""
        if off == 0x10: mark = "  <- [+0x10] flag_struct in fn@0x2309c"
        if off == 0x18: mark = "  <- [+0x18] dispatch_ctx_ptr in fn@0x1146C"
        if off == 0x88: mark = "  <- [+0x88] sub_struct in fn@0x2309c"
        if off == 0x168: mark = "  <- [+0x168] pending-events CANDIDATE"
        if off == 0x254: mark = "  <- [+0x254] BIT_alloc base (T283)"
        if off == 0x258: mark = "  <- [+0x258] copied to +0x254"
        if off == 0x8c: mark = "  <- [+0x8c] copied to +0x88 in class-0 thunk"
        print(f"  +0x{off:03x} @{addr:#x} = {v:#010x}  [{flag(v)}]{mark}")


# Primary: scheduler ctx allocated at 0x62a98 per T283
dump(0x62A98, 0x280, "scheduler ctx at 0x62a98 (per T283 fn@0x672e4)")

# Also relevant: 0x62B18 mentioned in fn@0x672e4 at 0x672f6 lit@0x67344
dump(0x62B18, 0x40, "aux scheduler state at 0x62b18")
