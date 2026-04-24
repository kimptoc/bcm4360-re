"""T288 follow-up: find who writes sched_ctx+0x258 with chipcommon wrapper base.

After correcting PCIE2 → chipcommon-wrapper, the question is: where does
0x18100000 get stored at sched+0x258?

T287b shows pre-write=0, post-set_active=0x18100000. So between the pre-write
readback and the post-set_active readback, something wrote it.

Candidates (called from fn@0x670d8 si_doattach):
- fn@0x64590 — core enumerator. Its slot-indexed stores target +0x114, +0x194,
  +0x1d4, +0x214, +0xd4 (per slot offsets). None of those arithmetic to
  +0x258 for reasonable slot values (0..15). BUT the enumerator's function
  body may extend beyond what I've disasmed — need to check.
- fn@0x66fc4 — called from si_doattach at 0x671b0 with (sched, chipcommon,
  slot, slot, r8, r6) on the stack. Could be per-core setup.
- fn@0x6458c — called inline from enumerator at 0x64674 with sched_ctx.
  Short function (nested within enum body).
- fn@0x91c — called very early at 0x67108 to zero sched_ctx (0x35c bytes) —
  irrelevant, it only writes zeros.

Approach:
1. Disasm fn@0x66fc4 and fn@0x6458c bodies
2. Also extend fn@0x64590 disasm to the full body (earlier cut at 0x64784)
3. Flag any store to a fixed offset in the range 0x240-0x270
4. Flag any store via base+register offset that could evaluate to 0x258
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
    if v == 0x18100000: return "CHIPCOMMON WRAPPER base"
    if v == 0x18003000: return "PCIE2 base (real)"
    if v == 0x18103000: return "PCIE2 wrapper"
    if 0x18000000 <= v < 0x18010000: return "chipcommon-region"
    if 0x18100000 <= v < 0x18110000: return "wrapper-region"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"addr {v:#x}"
    return f"imm {v:#x}"


def disasm(entry, label, max_bytes=3000, stop_rets=2):
    print(f"\n=== fn@{entry:#x} '{label}' ===")
    window = data[entry:entry + max_bytes]
    ret_count = 0
    for i in md.disasm(window, entry, count=0):
        annot = ""
        if i.mnemonic.startswith("ldr") and "[pc" in i.op_str:
            try:
                imm_str = i.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((i.address + 4) & ~3) + imm
                if 0 <= lit_addr < len(data) - 4:
                    v = struct.unpack_from("<I", data, lit_addr)[0]
                    annot = f"  lit={v:#x} [{flag(v)}]"
            except Exception: pass
        if i.mnemonic in ("mov.w", "movw") and "#" in i.op_str:
            try:
                imm_hex = i.op_str.split("#")[-1].strip()
                imm = int(imm_hex, 16) if imm_hex.startswith("0x") else int(imm_hex)
                if 0x18000000 <= imm < 0x18200000:
                    annot += f"  [MMIO {flag(imm)}]"
                elif imm in (0x96, 0x258):
                    annot += f"  [*** 0x96/0x258 constant ***]"
            except Exception: pass
        if i.mnemonic in ("bl", "blx") and i.op_str.startswith("#"):
            try:
                t = int(i.op_str[1:], 16)
                if t == 0xA30: annot += "  ← printf"
                elif t == 0x11e8: annot += "  ← printf/assert"
                elif t == 0x1298: annot += "  ← heap-alloc"
                else: annot += f"  ← fn@{t:#x}"
            except ValueError: pass
        # Stores: flag ANY str at fixed offset near our area of interest
        if i.mnemonic in ("str", "str.w", "strh", "strb"):
            op = i.op_str
            # Fixed-offset stores in 0x240-0x280 range
            for off in range(0x240, 0x290, 4):
                for tok in (f"#{hex(off)}]", f"#{hex(off)},", f"#{off}]", f"#{off},"):
                    if tok.lower() in op.lower() and "[sp" not in op:
                        annot += f"  *** STORE at fixed +{off:#x} ***"
                        break
            # Indexed via shifted register
            if "lsl #2" in op and "[sp" not in op:
                annot += f"  *** INDEXED STORE (lsl #2 — class/slot table) ***"
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if (i.mnemonic == "bx" and "lr" in i.op_str) or \
           (i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str):
            ret_count += 1
        if ret_count >= stop_rets:
            print("  --- ret limit reached ---")
            break


# fn@0x6458c is a small helper called from the enumerator at 0x64674
disasm(0x6458c, "fn@0x6458c — inline enumerator helper", max_bytes=16, stop_rets=1)

# fn@0x66fc4 — per-core setup, called from si_doattach at 0x671b0
disasm(0x66fc4, "fn@0x66fc4 — candidate per-core setup", max_bytes=2500, stop_rets=2)

# Also extend fn@0x64590 past 0x64784 where earlier disasm cut off
print("\n=== fn@0x64590 BODY continuation (0x64780 onward) ===")
disasm(0x64780, "fn@0x64590 tail", max_bytes=1600, stop_rets=3)
