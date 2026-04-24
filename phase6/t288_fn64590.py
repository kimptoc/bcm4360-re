"""T288: disasm fn@0x64590 — called from fn@0x670d8 (si_doattach) at 0x67190
with (r0=sched_ctx=0x62a98, r1=chipcommon=0x18000000, r2=r7=arg from caller).

Hypothesis: this is si_scan / core-enumeration. It should:
1. Read the chipcommon EROM pointer (or walk backplane) to discover cores
2. Populate sched_ctx with per-core base addresses at contiguous offsets
3. PCIE2 core would be one of the cores discovered; its base (0x18100000)
   ends up at +0x258 (class-0 table element)

Look for:
- Stores with indexed addressing (str rX, [rY, rZ, lsl #2]) — class table
- Calls that might return a PCIE2-base value
- Any write at offset in the range 0x200-0x280 (class table zone)
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


def flag(v):
    if v == 0x18000000: return "CHIPCOMMON base"
    if v == 0x18100000: return "PCIE2 base"
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000: return "PCIE2 core MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO (other core)"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"addr {v:#x}"
    return f"imm {v:#x}"


def disasm(entry, label, max_bytes=4000):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ins_list = list(md.disasm(window, entry, count=0))
    ret_count = 0
    for i in ins_list:
        annot = ""
        # Literal pool loads
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit@{lit_addr:#x}={v:#x}  [{flag(v)}]"
            except Exception: pass
        # Immediate mov.w of MMIO bases / key constants
        if i.mnemonic in ("mov.w", "movw") and "#" in i.op_str:
            try:
                imm_hex = i.op_str.split("#")[-1].strip()
                imm = int(imm_hex, 16) if imm_hex.startswith("0x") else int(imm_hex)
                if 0x18000000 <= imm < 0x18200000:
                    annot += f"  [MMIO {flag(imm)}]"
                elif imm == 0x96 or imm == 0x258:
                    annot += f"  [index {imm:#x} = +{imm*4:#x} class-table offset]"
            except Exception: pass
        # Branches
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                elif t == 0x14948: annot += "  ← trace"
                elif t == 0x1298: annot += "  ← heap-alloc"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        # Stores: flag any str/strh/strb to an offset in the class-table range
        if i.mnemonic in ("str", "str.w", "strh", "strb"):
            op = i.op_str
            # Fixed offset
            for off in range(0x240, 0x290, 4):
                if f"#{hex(off)}" in op.lower() or f"#{off}," in op or f"#{off}]" in op:
                    if "[sp" not in op:
                        annot += f"  *** STORE at fixed +{off:#x} ***"
                        break
            # Indexed (shifted register) — class-table pattern
            if "lsl #2" in op and "[sp" not in op:
                annot += f"  *** INDEXED STORE (shift-2, class-table pattern) ***"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        # Return tracking
        if (i.mnemonic == "bx" and "lr" in i.op_str) or \
           (i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str):
            ret_count += 1
        if ret_count >= 3:
            print("  --- 3rd ret passed; stopping ---")
            break


disasm(0x64590, "fn@0x64590 — candidate core-enumerator (si_scan?)", max_bytes=4000)
