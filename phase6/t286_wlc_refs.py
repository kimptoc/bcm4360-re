"""T286: find code references to 0x58EFC (wlc struct base) and 0x58F14
(the NULL offset our chain walked into). If 0x58F14 is populated at
runtime, the writer should load 0x58EFC as a base and then store at
offset 0x18.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(100):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


# Find literal-pool entries equal to 0x58EFC, 0x58F14, 0x58F1C
for addr in [0x58EFC, 0x58F14, 0x58F1C]:
    hits = []
    for off in range(0, len(data) - 4, 4):
        v = struct.unpack_from("<I", data, off)[0]
        if v == addr:
            hits.append(off)
    print(f"\n=== Literal-pool hits for {addr:#x} ===")
    for h in hits:
        # Disasm ~10 instrs before to see loader + store context
        ctx_start = max(0, h - 40)
        window = data[ctx_start:h + 2]
        ins = list(md.disasm(window, ctx_start, count=0))
        print(f"\n  lit@{h:#x} = {addr:#x}")
        # find LDR that references this literal
        found_ldr_loc = None
        for code_off in range(max(0, h - 256), h, 2):
            hw = struct.unpack_from("<H", data, code_off)[0]
            if (hw & 0xF800) == 0x4800:  # thumb narrow ldr
                rt = (hw >> 8) & 0x7
                imm8 = hw & 0xFF
                target = ((code_off + 4) & ~3) + imm8 * 4
                if target == h:
                    found_ldr_loc = code_off
                    break
            if hw in (0xF85F, 0xF8DF):  # thumb wide ldr
                nxt = struct.unpack_from("<H", data, code_off + 2)[0]
                sign = 1 if hw == 0xF8DF else -1
                imm12 = nxt & 0xFFF
                target = ((code_off + 4) & ~3) + sign * imm12
                if target == h:
                    found_ldr_loc = code_off
                    break
        if found_ldr_loc:
            # Disasm from ldr + 10 insns forward
            window2 = data[found_ldr_loc:min(len(data), found_ldr_loc + 40)]
            ins2 = list(md.disasm(window2, found_ldr_loc, count=10))
            print(f"  LDR loader at {found_ldr_loc:#x}:")
            for i in ins2[:8]:
                print(f"    {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}")
