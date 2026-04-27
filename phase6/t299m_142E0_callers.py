"""T299m: verify the load-bearing claim. Per advisor:
1. ALL callers of fn@0x142E0 (the actual 0x48080 writer) — bl + fn-ptr + movw/movt
2. ALL callers of fn@0x6820C (wlc_bmac_attach)
3. EVERY 4-byte aligned word == 0x00048080 in the blob (a second literal pool
   site would mean a different function can load that mask)
4. Sanity-check: re-verify host observation by checking what's at 0x64 within
   what flag_struct_init actually writes — confirm it's 0x48080 in the static
   init pattern.
"""
import sys, struct, re
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
def is_pop_pc(ins):
    return ins.mnemonic in ("pop", "pop.w") and "pc" in ins.op_str
def is_bx_lr(ins):
    return ins.mnemonic == "bx" and ins.op_str.strip() == "lr"


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


NAMED = {
    0x9990:  "si_setcoreidx",
    0x11790: "wrap_ARM",
    0x142E0: "fn@0x142E0 (writes 0x48080)",
    0x15DA8: "wlc_bmac_up_prep",
    0x17ED6: "wlc_bmac_up_finish",
    0x18FFC: "wlc_up",
    0x11648: "wl_open",
    0x6820C: "wlc_bmac_attach",
    0x68A68: "wlc_attach",
    0x67614: "wl_probe",
    0x67358: "si_doattach_wrapper",
    0x670d8: "si_doattach",
    0x1c74:  "pciedngl_open",
    0x1e90:  "pciedngl_probe",
    0x1c98:  "pciedngl_isr",
}


def find_fn_start(addr):
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if is_push_lr(ins): last = ins.address
    return last


def caller_scan(target, target_thumb):
    """Find: direct bl/blx/b targeting `target`, fn-ptr table refs to
    `target_thumb`, movw/movt construction. Also catches indirect tagged."""
    print(f"\n  Direct bl/blx/b targeting {target:#x}:")
    direct = []
    for ins in all_ins:
        if "#0x" not in ins.op_str: continue
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
        except: continue
        if t != target: continue
        if ins.mnemonic in ("bl", "blx", "b", "b.w"):
            direct.append(ins)
    print(f"    Hits: {len(direct)}")
    for ins in direct:
        fn = find_fn_start(ins.address)
        fn_name = NAMED.get(fn, "")
        print(f"      {ins.address:#x}: {ins.mnemonic} → caller fn @ {hex(fn) if fn else '?'}{(' = '+fn_name) if fn_name else ''}")

    # fn-ptr ALL alignments
    needle = struct.pack("<I", target_thumb)
    hits = []; pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        hits.append(idx); pos = idx + 1
    print(f"  fn-ptr ({target_thumb:#x}) any alignment: {len(hits)}")
    for h in hits[:8]:
        ctx_start = max(0, h - 16)
        ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
        print(f"      {h:#x} aligned={h%4==0}  ctx@{ctx_start:#x}: {ctx}")

    # tagged window (off-by-N near target)
    lo = (target & ~0xff) - 0x10; hi = (target & ~0xff) + 0x100
    hits_tagged = []
    for off in range(0, len(data) - 4, 2):
        val = struct.unpack_from('<I', data, off)[0]
        if lo <= val <= hi:
            hits_tagged.append((off, val))
    if hits_tagged:
        print(f"  Tagged-window [{lo:#x}..{hi:#x}] (any alignment): {len(hits_tagged)} hits")
        from collections import Counter
        val_counts = Counter(v for _, v in hits_tagged)
        for v, c in val_counts.most_common(8):
            print(f"      val={v:#x}: {c} occurrences")
    else:
        print(f"  Tagged-window [{lo:#x}..{hi:#x}]: 0 hits")


# ============== (1) Callers of fn@0x142E0 (writes 0x48080) ==============
print("=== (1) Callers of fn@0x142E0 (the 0x48080 writer) ===")
caller_scan(0x142E0, 0x142E1)


# ============== (2) Callers of fn@0x6820C (wlc_bmac_attach) ==============
print("\n\n=== (2) Callers of fn@0x6820C (wlc_bmac_attach) ===")
caller_scan(0x6820C, 0x6820D)


# ============== (3) EVERY 4-byte aligned occurrence of 0x00048080 ==============
print("\n\n=== (3) ALL 4B occurrences of value 0x00048080 ===")
needle = struct.pack("<I", 0x48080)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  Total hits (any alignment): {len(hits)}")
for h in hits:
    aligned = h % 4 == 0
    # Look at preceding bytes — could be a literal pool or static init?
    ctx_start = max(0, h - 32)
    ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(12) if ctx_start+4*k+4 <= len(data))
    print(f"    {h:#x} aligned={aligned}  ctx@{ctx_start:#x}: {ctx}")
    # Find the closest fn-start <= h to see what fn this literal belongs to
    fn = find_fn_start(h)
    fn_name = NAMED.get(fn, "")
    print(f"      nearest fn-start <= {h:#x}: fn@{hex(fn) if fn else '?'}{(' = '+fn_name) if fn_name else ''}")


# ============== (4) Verify fn@0x142E0 actually writes 0x48080 to [+0x64] of its arg ==============
print("\n\n=== (4) Re-verify fn@0x142E0 writes 0x48080 to [arg+0x64] ===")
chunk = data[0x142E0:0x142E0 + 0x100]
for ins in md.disasm(chunk, 0x142E0):
    a = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == 0x48080: a = "  ; lit=0x48080 ★★★"
                else: a = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic in ("str", "str.w", "strh", "strb"):
        a = "  [STORE]"
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end pop pc]"); break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end bx lr]"); break


# ============== (5) Sanity: callers of fn@0x142E0 dump short body so we see all dynamic refs ==============
print("\n\n=== (5) ALL load-from-pool of 0x142E1 (fn ptr to 142E0) ===")
needle = struct.pack("<I", 0x142E1)
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    aligned = idx % 4 == 0
    fn = find_fn_start(idx)
    fn_name = NAMED.get(fn, "")
    ctx_start = max(0, idx - 16)
    ctx = " ".join(f"{struct.unpack_from('<I', data, ctx_start+4*k)[0]:#010x}" for k in range(8) if ctx_start+4*k+4 <= len(data))
    print(f"  {idx:#x} aligned={aligned}  ctx: {ctx}")
    if aligned:
        # Find ldr-pc-rel insns that load this lit
        for ins in all_ins:
            if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address + 4) & ~3) + imm
                if la == idx:
                    fn2 = find_fn_start(ins.address)
                    print(f"    ldr-loader: {ins.address:#x} inside fn@{hex(fn2) if fn2 else '?'}")
            except: pass
    pos = idx + 1
