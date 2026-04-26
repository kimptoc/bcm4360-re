"""T289b: trace wlc_callback_ctx through hndrte_add_isr call site at 0x67774.

Per T272: hndrte_add_isr is called from 3 sites; 0x67774 is the wlc_attach
caller that registers fn@0x1146C. Args to hndrte_add_isr per T289 hndrte
disasm: r1 = class, r2 = callback_fn, r3 = callback_arg (becomes
wlc_callback_ctx when fn@0x1146C fires).

Goal:
1. Disasm fn around 0x67774 to identify what buffer/struct is in r3 at the
   call site (the value that becomes wlc_callback_ctx).
2. Trace whether [callback_ctx + 0x10] is initialized in the same fn or
   somewhere we can find via xref.
3. Identify the struct that lives at [callback_ctx+0x10] and what
   [that_struct + 0x88] points to.

Cheap zero-fire trace per advisor reconcile.
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
    for k in range(100):
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


def flag(v):
    if 0x18000000 <= v < 0x18001000:
        return "CHIPCOMMON REG"
    if 0x18001000 <= v < 0x18010000:
        return "core[N] REG"
    if 0x18100000 <= v < 0x18101000:
        return "CHIPCOMMON WRAPPER"
    if 0x18101000 <= v < 0x18110000:
        return "core[N] WRAPPER"
    if 0 < v < len(data):
        s = str_at(v)
        if s:
            return f"STRING '{s}'"
        return f"code ptr fn@{v & ~1:#x}"
    if 0 < v < 0xA0000:
        return "TCM offset"
    if v < 0x10000:
        return f"small val {v:#x}"
    return "unclassified"


def find_fn_start(addr, max_back=0x800):
    """Scan back for a push prologue. Returns the prologue address."""
    for off in range(addr & ~1, max(0, (addr & ~1) - max_back), -2):
        w16 = struct.unpack_from("<H", data, off)[0]
        # b500..b5ff = push {..., lr}
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
        # e92d xxxx = push.w {...}
        if w16 == 0xe92d:
            return off
    return None


def disasm_window(start, end, label):
    print(f"\n=== {label} {start:#x}..{end:#x} ===")
    window = data[start:end]
    for i in md.disasm(window, start, count=0):
        annot = ""
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit@{lit_addr:#x}={v:#x}  [{flag(v)}]"
            except Exception:
                pass
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30:
                    annot += "  ← printf"
                elif t == 0x11e8:
                    annot += "  ← printf/assert"
                elif t == 0x14948:
                    annot += "  ← trace"
                elif t == 0x63c24:
                    annot += "  ← hndrte_add_isr"
                elif t == 0x9990:
                    annot += "  ← class-validate (si_setcoreidx-wrap)"
                elif t == 0x1298:
                    annot += "  ← alloc"
                else:
                    annot += f"  ← fn@{t:#x}"
            except ValueError:
                pass
        print(f"  {i.address:#7x}  {i.mnemonic:8s}  {i.op_str}{annot}")


# Step 1: locate fn that contains the BL at 0x67774
print("Step 1: find function containing BL at 0x67774")
fn_start = find_fn_start(0x67774, max_back=0x1000)
print(f"  prologue at: {fn_start:#x}" if fn_start else "  not found")

# Disasm around the call site — wide window to see what arg setup occurs
if fn_start:
    # Find approximate end: scan forward for next push prologue
    end = 0x67774 + 0x100  # show enough following context
    # but cap at next push.w
    for off in range(0x67780, 0x67774 + 0x600, 2):
        if off + 2 > len(data): break
        w16 = struct.unpack_from("<H", data, off)[0]
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            end = off
            break
        if w16 == 0xe92d:
            end = off
            break
    disasm_window(fn_start, end, "fn containing 0x67774 (wlc_attach hndrte_add_isr caller)")

# Step 2: search blob for any BL that targets the fn we just identified
# (if it's at 0x67xxx, find callers/callees that pass struct ptrs)
# This will tell us where wlc_callback_ctx is allocated.

# First identify the precise fn entry:
print("\n\nStep 2: callers of this fn (xref for wlc_callback_ctx allocation)")
if fn_start:
    target = fn_start | 1  # thumb-bit
    # naive: search for any BL/B.W with offset matching this fn
    callers = []
    i = 0
    while i < len(data) - 2:
        w16 = struct.unpack_from("<H", data, i)[0]
        # T1 BL / B.W encoding: F000..FFFF / E800..EFFF / F800..FFFF
        if (w16 & 0xf800) == 0xf000:
            # potentially a BL or B.W
            if i + 4 > len(data):
                i += 2
                continue
            w32 = struct.unpack_from("<I", data, i)[0]
            # decode T1 BL: 0xF000_F800 family
            j1 = (w32 >> 13) & 1
            j2 = (w32 >> 11) & 1
            s = (w32 >> 10) & 1
            i1 = ~(j1 ^ s) & 1
            i2 = ~(j2 ^ s) & 1
            imm10 = w32 & 0x3ff
            imm11 = (w32 >> 16) & 0x7ff
            if (w32 >> 30) & 0x1:
                # only bit 11 of upper half, but we need full encoding
                pass
            # quick-and-dirty: use capstone to validate
        i += 2

    # Use capstone — disasm wide span and look for BL #fn_start
    # restrict to only sane ranges
    print(f"  searching for BL/B.W targets equal to fn entry {fn_start:#x}...")
    # Use Cs to find BL targets across the whole blob (slow but simple)
    cs2 = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    seen = 0
    target_addr = fn_start
    # disassemble in chunks to limit memory; this is slow on 442KB
    for chunk_start in range(0, len(data) - 4, 0x4000):
        chunk_end = min(len(data), chunk_start + 0x4400)
        for ins in cs2.disasm(data[chunk_start:chunk_end], chunk_start):
            if ins.mnemonic in ("bl", "blx") and ins.op_str.startswith("#"):
                try:
                    t = int(ins.op_str[1:], 16)
                    if t == target_addr or t == target_addr | 1:
                        callers.append(ins.address)
                except ValueError:
                    pass
            seen += 1
        if chunk_start > 0x70000:
            break  # only need first half of blob for early-init callers
    print(f"  callers (BL #{fn_start:#x}): {[hex(x) for x in callers[:10]]}")
