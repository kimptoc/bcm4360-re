"""T288: disasm fn@0x670d8 — scheduler init helper.

fn@0x672e4 calls fn@0x670d8 at 0x67310 with:
  r0 = sched_ctx base (0x62a98)
  r1 = 0x4710 (small immediate — size/count?)
  r2 = arg2 (from caller)
  r3 = 0x18000000 (CHIPCOMMON MMIO base)
  sp[0] = 0
  sp[4] = 0
  sp[8] = 0 or 0x62b18
  sp[0xc] = orig-arg1

Goal: find what fn@0x670d8 stores at sched_ctx+0x258 (class 0 base).
T287b runtime shows sched_ctx+0x258 = 0x18100000 (PCIE2 base), not
chipcommon as T283 inferred. So fn@0x670d8 likely:
  (a) receives PCIE2 base from another arg slot (not r3), or
  (b) discovers PCIE2 base via core-table enumeration, or
  (c) the store happens elsewhere (not this call).

Also disasm the SECOND call site at 0x67398 (in fn@0x67358) to see
if it's structurally similar.
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
    if 0x18000000 <= v < 0x18010000: return "CHIPCOMMON MMIO"
    if 0x18100000 <= v < 0x18110000: return "PCIE2 core MMIO"
    if 0x18002000 <= v < 0x18100000: return "backplane MMIO (other core)"
    if 0 < v < len(data):
        s = str_at(v)
        if s: return f"STRING '{s}'"
        return f"code/addr {v:#x}"
    return f"imm {v:#x}"


def disasm(entry, label, max_bytes=2500, stop_after_ret=True):
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
        # Immediate mov.w of MMIO bases
        if i.mnemonic in ("mov.w", "movw", "movt") and "#" in i.op_str:
            try:
                imm_hex = i.op_str.split("#")[-1].strip()
                imm = int(imm_hex, 16) if imm_hex.startswith("0x") else int(imm_hex)
                if imm in (0x18000000, 0x18100000, 0x18102000, 0x18101000) or \
                   (0x18000000 <= imm < 0x18200000):
                    annot += f"  [MMIO {flag(imm)}]"
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
        # Stores at offsets we care about
        for off_hex, role in [("0x10", "+0x10"),
                              ("0x18", "+0x18"),
                              ("0x80", "+0x80"),
                              ("0x84", "+0x84"),
                              ("0x88", "+0x88"),
                              ("0x8c", "+0x8c"),
                              ("0x168", "+0x168"),
                              ("0x254", "+0x254"),
                              ("0x258", "+0x258"),
                              ("0x25c", "+0x25c"),
                              ("0x260", "+0x260")]:
            if i.mnemonic in ("str", "str.w", "strh", "strb") and \
               ("#" + off_hex + "]" in i.op_str or "#" + off_hex + "," in i.op_str):
                annot += f"  *** STORE {role} ***"
        # Calls into likely core-lookup functions (heuristic: unknown small-id fn#)
        print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}{annot}")
        if i.mnemonic in ("bx", "pop", "pop.w") and stop_after_ret:
            # pop.w {..., pc} is a return
            if i.mnemonic == "bx" and "lr" in i.op_str:
                ret_count += 1
            elif i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str:
                ret_count += 1
        # After 2 return points, stop — next function likely
        if ret_count >= 2:
            print("  --- 2nd ret passed; stopping ---")
            break


# Disasm the scheduler init helper
disasm(0x670d8, "fn@0x670d8 — scheduler init helper", max_bytes=3000)
