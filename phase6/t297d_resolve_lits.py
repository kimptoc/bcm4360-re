"""Resolve all PC-relative literals in the [0x6A040..0x6A090) struct-init
block, and identify the literal at [+0x88].

If the [+0x88] value is a backplane base address (0x180000xx range), this is
the wake-gate base. If it's a fn ptr (low bit set, in code range), it's
something else entirely (a callback, not a base).
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open('/lib/firmware/brcm/brcmfmac4360-pcie.bin','rb') as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm a wider region — the whole containing fn likely spans several KB
print("=== Resolving all PC-rel literals in stores [r4, +imm] block @0x6A040..0x6A090 ===\n")
last_lit_val = None
last_lit_addr = None
for ins in md.disasm(data[0x6A040:0x6A090], 0x6A040):
    pc_rel = None
    if ins.mnemonic.startswith('ldr') and '[pc,' in ins.op_str:
        try:
            imm_str = ins.op_str.split('#')[-1].rstrip(']').strip()
            imm = -int(imm_str[1:], 16) if imm_str.startswith('-') else int(imm_str, 16)
            lit_addr = ((ins.address + 4) & ~3) + imm
            if 0 <= lit_addr <= len(data)-4:
                val = struct.unpack_from('<I', data, lit_addr)[0]
                last_lit_val = val
                last_lit_addr = lit_addr
                pc_rel = (lit_addr, val)
        except Exception as e:
            pass
    if ins.mnemonic in ('str','str.w') and '[r4,' in ins.op_str:
        # Get offset
        try:
            off_str = ins.op_str.split('#')[-1].rstrip(']').strip()
            off = int(off_str, 16) if off_str.startswith('0x') else int(off_str)
            tag = "  <-- WAKE-GATE BASE? (+0x88)" if off == 0x88 else ""
            print(f"  {ins.address:#7x}  STORE [r4, +{off:#x}] = {last_lit_val:#010x} (lit@{last_lit_addr:#x}){tag}")
        except Exception:
            pass
    elif ins.mnemonic in ('str','str.w') and '[r3,' in ins.op_str:
        try:
            off_str = ins.op_str.split('#')[-1].rstrip(']').strip()
            off = int(off_str, 16) if off_str.startswith('0x') else int(off_str)
            print(f"  {ins.address:#7x}  STORE [r3, +{off:#x}]   (r3 was loaded from [r4,#0x1c])")
        except Exception:
            pass

print("\n=== Decoding each literal value ===")

def classify(v):
    if v == 0:
        return "(zero)"
    # Thumb fn pointer: odd, in code range (< 442233)
    if v & 1 and v < len(data) and v >= 0x1000:
        # Try disassembling at v-1
        try:
            for ins in md.disasm(data[v-1:v-1+8], v-1):
                return f"Thumb fn @{v-1:#x} → {ins.mnemonic} {ins.op_str}"
                break
        except Exception:
            pass
        return f"Thumb fn @{v-1:#x}"
    # String pointer: even, in data range, ASCII-ish
    if 0 < v < len(data):
        s = bytearray()
        for k in range(40):
            if v + k >= len(data):
                break
            c = data[v + k]
            if c == 0:
                break
            if 32 <= c < 127:
                s.append(c)
            else:
                break
        if len(s) > 3:
            return f'string @{v:#x}: "{s.decode("ascii", errors="replace")}"'
    # Backplane base?
    if 0x18000000 <= v <= 0x181FFFFF:
        return f"BACKPLANE BASE {v:#x}"
    return "(unclassified)"

# Walk literals 0x6A0F0..0x6A140 (where the lits live for this block)
for la in range(0x6A0F0, 0x6A140, 4):
    val = struct.unpack_from('<I', data, la)[0]
    print(f"  lit@{la:#x} = {val:#010x}    {classify(val)}")
