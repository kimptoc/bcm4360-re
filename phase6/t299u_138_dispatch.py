"""T299u: dump fn@0x138 — the unified exception dispatcher.

ALL 8 ARM exception handlers (reset, undef, SVC, prefetch_abort, data_abort,
?, IRQ, FIQ) converge to fn@0x138 with an exception ID 0-7 in r0. fn@0x138
performs `blx r4` where r4 = [r4, #0x0] at 0x16c. Need to identify what r4
originally points to.

Probe:
1. Dump fn@0x138 in full — trace every register write
2. Identify the table base (where r4 starts)
3. Look for code that POPULATES that table — i.e., writes fn-pointers into it
4. Specifically check if any wifi entry (wl_probe / pciedngl_isr) is ever
   stored to the table
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


NAMED = {
    0x9990:  "si_setcoreidx",
    0x11790: "wrap_ARM",
    0x142E0: "0x48080-writer",
    0x6820C: "wlc_bmac_attach",
    0x68A68: "wlc_attach",
    0x67614: "wl_probe",
    0x1c98:  "pciedngl_isr",
    0x1e90:  "pciedngl_probe",
    0x11704: "init-shim → 142E0",
    0x4718:  "set_callback",
    0x2408:  "real C main",
    0x268:   "bootstrap",
    0x2312C: "wlc_dpc",
    0x113b4: "ACTION dispatcher",
    0x233E8: "wake-mask ARM impl",
    0xf8:    "IRQ handler",
    0x118:   "FIQ handler",
    0x138:   "unified exception dispatcher",
}


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


def annot(ins):
    a = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s: a = f"  ; \"{s}\""
                elif val & 1 and 0x1000 < val < len(data):
                    target = val - 1
                    name = NAMED.get(target, "")
                    a = f"  ; lit={val:#x} → fn@{target:#x}{(' = '+name) if name else ''}"
                else:
                    a = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  → {NAMED[t]}"
            else: a = f"  → fn@{t:#x}"
        except: pass
    elif ins.mnemonic in ("b", "b.w") and "#0x" in ins.op_str:
        try:
            t = int(ins.op_str.lstrip("#").strip(), 16)
            if t in NAMED: a = f"  >>> TAIL→{NAMED[t]} <<<"
            else: a = f"  → tail-fn@{t:#x}"
        except: pass
    elif ins.mnemonic in ("bx", "blx") and ins.op_str.strip().startswith("r"):
        a = f"  → INDIRECT via {ins.op_str.strip()}"
    elif ins.mnemonic.startswith("ldr") and "[" in ins.op_str:
        a = f"  [LOAD-FROM-STRUCT]"
    elif ins.mnemonic in ("str", "str.w"):
        a = f"  [STORE]"
    return a


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


# ============== (1) Dump fn@0x138 in full ==============
print("=== (1) DUMP fn@0x138 (unified exception dispatcher, called with r0=ex_id) ===\n")
chunk = data[0x138:0x138 + 0x200]
n = 0
for ins in md.disasm(chunk, 0x138):
    a = annot(ins)
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    n += 1
    if n > 100: print("  ..."); break
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end]"); break
    if ins.mnemonic == "bx" and ins.op_str.strip() == "lr": print("    [end]"); break


# ============== (2) Look for the literal pool around fn@0x138 — what addr is r4 set to? ==============
print("\n\n=== (2) Literal pool entries near fn@0x138 ===")
# scan 0x138..0x270 for words that look like fn-ptrs or struct addrs
for off in range(0x138, 0x300, 4):
    val = struct.unpack_from('<I', data, off)[0]
    if val == 0 or val == 0xffffffff: continue
    s = str_at(val)
    extra = ""
    if s: extra = f"  → \"{s}\""
    elif val & 1 and 0x1000 < val < len(data):
        target = val - 1
        name = NAMED.get(target, "")
        extra = f"  → fn@{target:#x}{(' = '+name) if name else ''}"
    elif 0x10000 < val < 0x80000:
        extra = f"  → addr {val:#x} (data?)"
    print(f"  {off:#x}: {val:#010x}{extra}")


# ============== (3) Find ALL stores into a table that fn@0x138 reads ==============
# fn@0x138 uses r4. Look for pattern like "ldr r4, =SOME_ADDR" early in fn@0x138
# Then find any store to that ADDR (or ADDR + offset)
# Simpler: any store into a memory region that holds fn-pointers — we'd need the addr first.
# So defer until we know the table base.


# ============== (4) Search for any code that writes fn-pointers to address that's near 'main_state' globals ==============
# Earlier T299q showed bootstrap stores to 0x21c, 0x230, 0x234, 0x58c74, 0x58c78, 0x58c7c, 0x58c8c
# These are exception/state globals. Check what they point to.
print("\n\n=== (4) Check known globals: 0x21c, 0x230, 0x234, 0x58c74, 0x58c78, 0x58c7c, 0x58c8c ===")
for off in (0x21c, 0x230, 0x234, 0x58c74, 0x58c78, 0x58c7c, 0x58c8c, 0x58c80, 0x58c84, 0x58c88, 0x58c90):
    if off + 4 > len(data): continue
    val = struct.unpack_from('<I', data, off)[0]
    name = NAMED.get(val if not (val & 1) else val - 1, "")
    print(f"  {off:#x}: {val:#010x}{(' (fn = '+name+')') if name else ''}")


# ============== (5) Compute reach: see what fns load 0x138 (verify it's only via exception vec) ==============
print("\n\n=== (5) Confirm fn@0x138 is reached only from exception vectors ===")
print("Disasm pass for full search...")
all_ins = list(iter_all())
print(f"  Total ins: {len(all_ins):,}")
direct = []
for ins in all_ins:
    if "#0x" not in ins.op_str: continue
    try:
        t = int(ins.op_str.lstrip("#").strip(), 16)
    except: continue
    if t != 0x138: continue
    if ins.mnemonic in ("bl", "blx", "b", "b.w"):
        direct.append(ins)
print(f"  Direct callers/jumpers to 0x138: {len(direct)}")
for ins in direct[:12]:
    print(f"    {ins.address:#x}: {ins.mnemonic} → 0x138")


# ============== (6) Dump fn that IS the indirect target — speculation: could be reset_handler or fault_handler ==============
print("\n\n=== (6) Speculation: dump fn@0x320 (lr from main on return = fault) ===")
chunk = data[0x320:0x340]
for ins in md.disasm(chunk, 0x320):
    a = annot(ins)
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{a}")
    if ins.address >= 0x335: break
