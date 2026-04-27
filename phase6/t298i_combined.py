"""T298i: combined check —
  (a) extended fn-start search for 0x68B90 (the sole caller of fn@0x6820C)
  (b) full body of fn@0x142E0 (the wake-mask init writer)
  (c) all writers of D11+0x16C, with VALUE source — identify independent
      INTMASK writers vs the [+0x64]-copy in fn@0x233E8.
"""
import struct, sys
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
ins_by_addr = {ins.address: ins for ins in all_ins}
print(f"Total: {len(all_ins):,}\n")


# (a) extended fn-start for 0x68B90 — scan back FAR
def find_fn_start(addr, scan_back=0x10000):
    pushes = []
    ends_after = {}
    start = max(0, addr - scan_back)
    for ins in all_ins:
        if ins.address < start or ins.address >= addr: continue
        if ins.mnemonic == "push" and "lr" in ins.op_str:
            pushes.append(ins.address)
        elif (ins.mnemonic == "pop" and "pc" in ins.op_str) or (
            ins.mnemonic == "bx" and ins.op_str.strip() == "lr"
        ):
            for p in pushes:
                if p not in ends_after:
                    ends_after[p] = ins.address
    for p in reversed(pushes):
        end = ends_after.get(p)
        if end is None or end > addr:
            return p
    return None


print("=== (a) Enclosing fn for 0x68B90 (sole caller of fn@0x6820C) ===\n")
fn = find_fn_start(0x68B90, scan_back=0x10000)
print(f"Enclosing fn (extended search): {hex(fn) if fn else 'still NOT FOUND — fn very large'}")
if fn:
    print(f"Caller fn size estimate: {0x68B90 - fn} bytes pre-call (call may not be at end)")

# Show first/last 16 ins of the caller fn
if fn:
    print(f"\n--- First 16 ins of caller fn@{hex(fn)} ---")
    seen = 0
    for ins in all_ins:
        if ins.address < fn: continue
        if seen >= 16: break
        seen += 1
        annot = ""
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
                la = ((ins.address+4) & ~3) + imm
                if 0 <= la <= len(data)-4:
                    val = struct.unpack_from('<I', data, la)[0]
                    s = str_at(val)
                    if s: annot = f"  ; \"{s}\""
                    else: annot = f"  ; lit={val:#x}"
            except: pass
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")


# (b) fn@0x142E0 full body — disasm until next push lr
print(f"\n\n=== (b) fn @ 0x142E0 (wake-mask init writer) — full body ===\n")
chunk = data[0x142E0:0x142E0 + 0x180]
end_seen = False
for ins in md.disasm(chunk, 0x142E0):
    annot = ""
    if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address+4) & ~3) + imm
            if 0 <= la <= len(data)-4:
                val = struct.unpack_from('<I', data, la)[0]
                s = str_at(val)
                if s: annot = f"  ; \"{s}\""
                else: annot = f"  ; lit={val:#x}"
        except: pass
    elif ins.mnemonic in ("mov","mov.w","movs","movw") and "#" in ins.op_str:
        try:
            imm_s = ins.op_str.split("#")[-1].strip()
            val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
            annot = f"  ; const = {val:#x}"
        except: pass
    elif ins.mnemonic == "bl":
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            annot = f"  → fn@{target:#x}"
        except: pass
    print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{annot}")
    if ins.mnemonic == "pop" and "pc" in ins.op_str: print("    [end]"); end_seen=True; break
    if ins.mnemonic == "bx" and ins.op_str.strip()=="lr": print("    [end — bx lr]"); end_seen=True; break
if not end_seen:
    print("    (truncated — body extends past 0x180 bytes)")


# (c) D11+0x16C writers — characterize source values
print(f"\n\n=== (c) ALL writers of [reg, +0x16C] with source value ===\n")

def parse_off(op):
    if "[" not in op: return None
    bracket = op[op.index("["):]
    if "#" not in bracket: return None
    s = bracket.split("#")[-1].rstrip("]").strip()
    try: return int(s, 16) if s.startswith("0x") else int(s)
    except: return None


def parse_base(op):
    if "[" not in op: return None
    bracket = op[op.index("["):]
    return bracket.lstrip("[").split(",")[0].strip()


hits_16c = []
for ins in all_ins:
    if ins.mnemonic not in ("str","str.w","strb","strb.w","strh","strh.w","strd"):
        continue
    if parse_off(ins.op_str) != 0x16C: continue
    if parse_base(ins.op_str) == "sp": continue
    hits_16c.append(ins)

print(f"Total [reg, +0x16C] writers: {len(hits_16c)}\n")

def get_src(hit):
    src_reg = hit.op_str.split(",")[0].strip()
    last = None
    for ins in all_ins:
        if ins.address >= hit.address: break
        if ins.address < hit.address - 40: continue
        if ins.mnemonic in ("mov","mov.w","movs","movw") and ins.op_str.startswith(src_reg + ","):
            last = ins
        elif ins.mnemonic in ("ldr","ldr.w") and ins.op_str.startswith(src_reg + ","):
            last = ins
    return last

for hit in hits_16c:
    src = get_src(hit)
    src_desc = f"{src.mnemonic} {src.op_str}" if src else "(no source found)"
    print(f"  {hit.address:#7x}  {hit.mnemonic:8s} {hit.op_str}  ← src: {src_desc}")
    if src and src.mnemonic in ("mov","mov.w","movs","movw") and "#" in src.op_str:
        try:
            imm_s = src.op_str.split("#")[-1].strip()
            val = int(imm_s, 16) if imm_s.startswith("0x") else int(imm_s)
            tag = ""
            if val == 0: tag = " (= ZERO — disable/clear)"
            elif val == 0x48080: tag = " (= 0x48080 — CANONICAL WAKE MASK)"
            print(f"           CONST source = {val:#x}{tag}")
        except: pass
