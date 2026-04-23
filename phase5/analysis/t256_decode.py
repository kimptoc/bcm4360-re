"""Decode T256 callback node[0]: what's at 0x1C98 (Thumb fn)?
Also check arg 0x58CC4."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_prev_fn(addr, max_back=0x200):
    for off in range(addr, max(0, addr-max_back), -2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d: return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0: return off
    return None

def find_fn_end(start, max_scan=0x200):
    for off in range(start+4, start+max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d or ((w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0):
            return off
    return start+max_scan

print("=== Disasm at 0x1C98 (T256 node[0].fn-ptr → Thumb target) ===")
start = find_prev_fn(0x1C98)
end = find_fn_end(0x1C98 if start is None else start)
if start is None: start = 0x1C98
print(f"Function body: 0x{start:06X}..0x{end:06X}")
for insn in md.disasm(blob[start:end], start):
    mark = " <-- node[0].fn target" if insn.address == 0x1C98 else ""
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{mark}")
    if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
        try:
            imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
            lit = ((insn.address+4)&~3) + imm
            if lit+4 <= len(blob):
                val = int.from_bytes(blob[lit:lit+4], "little")
                note = ""
                if 0x40000 <= val < 0x70000: note = " (blob-data/str range)"
                elif 0x80000 <= val < 0xA0000: note = " (TCM BSS/heap)"
                elif val & 0x80000000: note = " (fw VA)"
                print(f"             lit@0x{lit:06X} = 0x{val:08X}{note}")
        except: pass

# What's at arg 0x58CC4 (in blob data range)? Read a string maybe.
print(f"\n=== blob[0x58CC4..+64] (T256 node[0].arg dereferenced) ===")
chunk = blob[0x58CC4:0x58D04]
print(f"  hex: {chunk.hex(' ', 4)}")
# Try as a string
try:
    end_s = blob.index(b"\x00", 0x58CC4)
    s = blob[0x58CC4:end_s]
    if all(32 <= b < 127 for b in s) and len(s) > 2:
        print(f"  str: {s!r}")
    else:
        print(f"  not-ASCII ({len(s)}B)")
except ValueError:
    print("  no null terminator in next 64 bytes")

# Also check scan_callers(0x1C98) / (0x1C99) to see other code referencing this fn
def scan_callers(tgt):
    c = []
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+4], off):
            if insn.mnemonic in ("bl","blx","b.w","b"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"),16)
                        if t == tgt: c.append((insn.address, insn.mnemonic))
                    except: pass
            break
    return c

def scan_lit(tgt):
    results = []
    for pv in (tgt, tgt|1):
        p = pv.to_bytes(4, "little")
        pos = 0
        while True:
            h = blob.find(p, pos)
            if h < 0: break
            results.append((h, pv))
            pos = h + 1
    return results

print()
print(f"=== Direct-BL callers of 0x1C98 ===")
for a, m in scan_callers(0x1C98)[:10]: print(f"  0x{a:06X}: {m}")
print(f"=== Literal-pool refs to 0x1C99 (Thumb fn-ptr storage) ===")
for h, v in scan_lit(0x1C98)[:10]: print(f"  lit@0x{h:06X} = 0x{v:08X}")
