"""T299o: dump the op-vector/dispatch table near 0x678c0 and find its reader.

Context: fn@0x11704 (caller of 0x48080-writer fn@0x142E0) is a 6-insn tail-call
shim. Same region of the binary contains many similar shims at 0x11718, 0x11730,
0x11734, 0x11754, 0x11790 (wrap_ARM), 0x11796, 0x1179c, 0x117a4, 0x117b4, 0x117bc,
0x117e4, 0x117f0. These look like vtable entries.

fn@0x11705 is referenced at 0x678d0 (4-byte aligned). Surrounding:
  0x40c2f 0x1146d 0x4a0f1 0x11719 [0x11705] 0x11731 0x4a10e 0x116e1

Dump 0x67800..0x67a00 (estimated table range) and check:
1. Identify table entries (str/fn pairs or fn-only triples)
2. Verify wrap_ARM (0x11790 → 0x11791) and other shims appear in the table
3. Find code that reads addresses in this range — the dispatch reader
4. Check for ldr literals = 0x67800..0x67a00 base addresses

If wrap_ARM is in the table AND the table has a live reader, then 0x48080 is
armed via the offload dispatch and the wake-gate-dead conclusion is wrong.
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted_any = True
            last_end = ins.address + ins.size
            if last_end >= len(data) - 2:
                return
        pos = last_end if emitted_any else pos + 2


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str


def str_at(addr):
    if not (0 <= addr < len(data) - 1): return None
    s = bytearray()
    for k in range(120):
        if addr + k >= len(data): break
        c = data[addr + k]
        if c == 0: break
        if 32 <= c < 127: s.append(c)
        else: return None
    return s.decode("ascii") if len(s) >= 3 else None


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


# Useful named functions
NAMED = {
    0x11790: "wrap_ARM (wake-mask ARM 0x48080)",
    0x11796: "wake-mask DISARM shim",
    0x1179c: "set-arbitrary-mask shim",
    0x142E0: "0x48080-writer",
    0x11704: "init-shim → 142E0",
    0x11648: "wl_open(dead)",
    0x67614: "wl_probe(dead)",
}


# ============== (1) Dump 0x67800..0x67a00 — find table entries ==============
print("=== (1) Dump bytes 0x67800..0x67a00 (estimated table region) ===")
print("  off       word        hi-bit  | candidate")
for off in range(0x67800, 0x67a00, 4):
    val = struct.unpack_from('<I', data, off)[0]
    hint = ""
    # Code-region thumb fn-ptr (odd, in code range)
    if (val & 1) and 0x1000 < val < 0x60000:
        target = val - 1
        name = NAMED.get(target, "")
        hint = f"  → fn@{target:#x}{(' = '+name) if name else ''}"
    elif 0x40000 <= val <= 0x60000:
        s = str_at(val)
        if s: hint = f'  → str "{s}"'
        else: hint = f"  → str-region {val:#x}"
    elif val == 0:
        hint = "  (zero)"
    print(f"  {off:#x}: {val:#010x}{hint}")


# ============== (2) Find ALL fn-ptrs in the 0x117xx shim-block area inside this table ==============
print("\n\n=== (2) Locate which shims appear in 0x67800..0x67a00 ===")
SHIMS = [
    (0x11704, "init-shim → 142E0"),
    (0x11718, "shim → 15c30/1783c"),
    (0x11730, "shim → 1ef3c"),
    (0x11734, "shim → 113b4"),
    (0x11754, "shim → 16210"),
    (0x11790, "wrap_ARM wake-arm → 233e8"),
    (0x11796, "wake-disarm → 2340c"),
    (0x1179c, "set-mask → 2343a"),
    (0x117a4, "shim → 1430"),
    (0x117b4, "shim → 1218"),
    (0x117bc, "shim → 1138"),
    (0x117e4, "shim → fc4"),
    (0x117f0, "tiny: ldr+bx"),
]
for fn_addr, label in SHIMS:
    needle = struct.pack("<I", fn_addr | 1)
    pos = 0; hits = []
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    in_range = [h for h in hits if 0x67800 <= h < 0x67a00]
    print(f"  fn@{fn_addr:#x} ({label}): {len(hits)} total hits, {len(in_range)} in [0x67800..0x67a00]")
    for h in in_range:
        # show offset within 0x67800-aligned block
        rel = h - 0x67800
        print(f"    {h:#x} (rel {rel:#x})")


# ============== (3) Find code that loads addresses in 0x67800..0x67a00 (dispatch reader) ==============
print("\n\n=== (3) Code refs that load any address in 0x67800..0x67a00 ===")
hits = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if 0x67800 <= val < 0x67a00:
                hits.append((ins.address, la, val))
    except: pass
print(f"  Hits: {len(hits)}")
for ref_addr, la, val in hits:
    fn = None
    for ins in all_ins:
        if ins.address > ref_addr: break
        if is_push_lr(ins): fn = ins.address
    print(f"    {ref_addr:#x} (lit@{la:#x} val={val:#x})  inside fn@{hex(fn) if fn else '?'}")


# ============== (4) Also check WIDER region: 0x67000..0x68000 in case table base is elsewhere ==============
print("\n\n=== (4) Locate fn@0x11705 (init-shim ptr) anywhere — confirm only one home ===")
needle = struct.pack("<I", 0x11705)
pos = 0; hits = []
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  Hits for fn@0x11705 (any alignment): {len(hits)}")
for h in hits:
    print(f"    {h:#x} aligned={h%4==0}")


# ============== (5) Find the table START — scan backwards from 0x678d0 looking for non-fn-ptr ==============
print("\n\n=== (5) Walk back from 0x678d0 to find the table START / END boundary ===")
# A table likely has consistent stride. Hypothesis: 8 byte entries (str_ptr | fn_ptr)
# or 4 byte entries (just fn_ptr).
# Walk back: find first "non-table-like" entry (likely 0)
start = 0x678d0
while start > 0x67000:
    val = struct.unpack_from('<I', data, start - 4)[0]
    # Is it plausibly a fn-ptr or str-ptr?
    is_fnp = (val & 1) and 0x1000 < val < 0x60000
    is_strp = 0x40000 <= val <= 0x60000
    if is_fnp or is_strp:
        start -= 4
    else:
        break
print(f"  Table start estimate: {start:#x}")
end = 0x678d0
while end < 0x67a00:
    val = struct.unpack_from('<I', data, end)[0]
    is_fnp = (val & 1) and 0x1000 < val < 0x60000
    is_strp = 0x40000 <= val <= 0x60000
    if is_fnp or is_strp:
        end += 4
    else:
        break
print(f"  Table end estimate:   {end:#x}  (size {end - start} bytes, {(end - start)//4} entries)")
print(f"\n  Full table dump:")
for off in range(start, end, 4):
    val = struct.unpack_from('<I', data, off)[0]
    hint = ""
    if (val & 1) and 0x1000 < val < 0x60000:
        target = val - 1
        name = NAMED.get(target, "")
        hint = f"  → fn@{target:#x}{(' = '+name) if name else ''}"
    elif 0x40000 <= val <= 0x60000:
        s = str_at(val)
        if s: hint = f'  → "{s}"'
    print(f"    {off:#x}: {val:#010x}{hint}")
