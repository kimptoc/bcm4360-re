"""T299v: find code that writes to *(0x224) — installs the unified
exception/IRQ handler pointer that fn@0x138 reads. Trace where that
handler points and whether it eventually reaches the wifi code.

Pattern: ldr rA, =0x224 (or similar); str rB, [rA] where rB is a fn-ptr.
Or: str rB, [pc-relative-addr-equal-to-0x224].

Also: check 0x21c, 0x228 nearby. These globals at 0x21c-0x228 are the
exception/dispatch state per the bootstrap dump.
"""
import sys, struct, re
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
    0x320:   "fault handler",
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


def is_push_lr(ins):
    return ins.mnemonic in ("push", "push.w") and "lr" in ins.op_str


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


print("Disasm pass...")
all_ins = list(iter_all())
all_by_addr = {ins.address: ins for ins in all_ins}
print(f"Total ins: {len(all_ins):,}\n")


def find_fn_start(addr):
    last = None
    for ins in all_ins:
        if ins.address > addr: break
        if is_push_lr(ins): last = ins.address
    return last


# ============== (1) Find ALL ldr-pc-rel that load value 0x224 ==============
print("=== (1) ALL ldr-pc-rel loaders for value 0x224 ===")
loaders_224 = []
for ins in all_ins:
    if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
    try:
        imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
        imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
        la = ((ins.address + 4) & ~3) + imm
        if 0 <= la <= len(data) - 4:
            val = struct.unpack_from('<I', data, la)[0]
            if val == 0x224:
                loaders_224.append(ins)
    except: pass
print(f"  ldr-loaders for 0x224: {len(loaders_224)}")
for ins in loaders_224:
    fn = find_fn_start(ins.address)
    fn_name = NAMED.get(fn, "")
    rd = ins.op_str.split(",")[0].strip()
    print(f"    {ins.address:#x}: ldr {rd}, =0x224  inside fn@{hex(fn) if fn else '?'}{(' = '+fn_name) if fn_name else ''}")


# ============== (2) For each loader, look at next few insns for 'str X, [Rn]' where Rn was just loaded ==============
print("\n\n=== (2) Following each loader of 0x224 — look for store to *(0x224) ===")
for ldr_ins in loaders_224:
    rd = ldr_ins.op_str.split(",")[0].strip()
    fn = find_fn_start(ldr_ins.address)
    print(f"\n  Loader at {ldr_ins.address:#x} (sets {rd} = 0x224) inside fn@{hex(fn) if fn else '?'}")
    # Walk forward up to 30 insns looking for str via Rd
    after = sorted([i for i in all_ins if i.address > ldr_ins.address and i.address < ldr_ins.address + 0x40], key=lambda x: x.address)
    for nins in after[:20]:
        # str XXX, [rd] or str XXX, [rd, #imm]
        if nins.mnemonic in ("str", "str.w") and (f"[{rd}" in nins.op_str or f"[{rd}," in nins.op_str):
            print(f"    {nins.address:#x}: {nins.mnemonic} {nins.op_str}  ← STORE TO *(0x224)")
            # What's the value being stored? Look back for what was loaded into the source reg
            src_reg = nins.op_str.split(",")[0].strip()
            # find prior ldr to src_reg
            for back in sorted([i for i in all_ins if i.address < nins.address and i.address > nins.address - 0x40], key=lambda x: -x.address):
                if back.mnemonic.startswith("ldr") and back.op_str.startswith(src_reg + ","):
                    a = ""
                    if "[pc," in back.op_str:
                        try:
                            imm_s = back.op_str.split("#")[-1].rstrip("]").strip()
                            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                            la = ((back.address + 4) & ~3) + imm
                            if 0 <= la <= len(data) - 4:
                                val = struct.unpack_from('<I', data, la)[0]
                                a = f"  → val={val:#x}"
                                if val & 1 and 0x100 < val < len(data):
                                    target = val - 1
                                    name = NAMED.get(target, "")
                                    a += f" → fn@{target:#x}{(' = '+name) if name else ''}"
                        except: pass
                    print(f"      ← src reg {src_reg} loaded by {back.address:#x}: {back.mnemonic} {back.op_str}{a}")
                    break


# ============== (3) Same scan for 0x21c, 0x228, 0x230 — adjacent globals ==============
print("\n\n=== (3) Loaders of nearby exception globals ===")
for target in (0x21c, 0x228, 0x230):
    print(f"\n  Loaders for {target:#x}:")
    cnt = 0
    for ins in all_ins:
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == target:
                    fn = find_fn_start(ins.address)
                    print(f"    {ins.address:#x}: {ins.op_str}  inside fn@{hex(fn) if fn else '?'}")
                    cnt += 1
                    if cnt > 10: print("    ..."); break
        except: pass


# ============== (4) Search for str of fn-ptrs that look like they're being installed as handlers ==============
# Pattern in handler-install: ldr r0, =SOME_FN; ldr r1, =0x224; str r0, [r1]
print("\n\n=== (4) ALL alignments where a 4-byte value 0x224 appears (could be embedded in code or struct) ===")
needle = struct.pack("<I", 0x224)
hits = []; pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    hits.append(idx); pos = idx + 1
print(f"  Hits: {len(hits)}")
for h in hits:
    aligned = h % 4 == 0
    fn = find_fn_start(h)
    fn_name = NAMED.get(fn, "") if fn else ""
    print(f"    {h:#x} aligned={aligned}  near fn@{hex(fn) if fn else '?'}{(' = '+fn_name) if fn_name else ''}")
