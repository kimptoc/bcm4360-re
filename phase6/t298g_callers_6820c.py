"""T298g (advisor): find callers of fn@0x6820C — when in init does
flag_struct get allocated?

If pre-set_active: wake mask is armed before host probes can interfere.
If post-attach helper: flag_struct doesn't exist yet at the WFI freeze
point seen in T287c (after wl_probe).

Method: bl-target search across the full blob (resumable iter).
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
print(f"Total: {len(all_ins):,}\n")


# Find all bl/blx to fn@0x6820C
TARGETS = [0x6820C, 0x6820D]  # Thumb fn pointers also encoded with low bit set
print(f"=== Callers of fn@0x6820C ===\n")
hits = []
for ins in all_ins:
    if ins.mnemonic in ("bl", "blx") and "#0x" in ins.op_str:
        try:
            target = int(ins.op_str.lstrip("#").strip(), 16)
            if target in TARGETS:
                hits.append(ins)
        except Exception:
            pass

# Also find indirect callers via fn-ptr table (0x6820D as a literal)
print(f"Direct bl/blx hits: {len(hits)}")
for ins in hits:
    print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")

# Indirect: search for literal 0x6820D in the blob (Thumb fn ptr)
print(f"\n=== Literal-table references to 0x6820D ===")
needle = struct.pack("<I", 0x6820D)
indirect = []
pos = 0
while True:
    idx = data.find(needle, pos)
    if idx < 0: break
    if idx % 4 == 0:
        indirect.append(idx)
    pos = idx + 1
print(f"Indirect (fn-ptr table) hits: {len(indirect)}")
for h in indirect:
    # Show 16 bytes of context (4 dwords)
    ctx = " ".join(f"{struct.unpack_from('<I', data, h-8+4*k)[0]:#010x}" for k in range(5))
    print(f"  fn-ptr at file offset {h:#x}: surrounding dwords = {ctx}")


# For each direct caller, find its enclosing fn and show context
print(f"\n=== Caller context (each caller's enclosing fn + arguments) ===\n")
ins_by_addr = {ins.address: ins for ins in all_ins}

def find_fn_start(addr, scan_back=0x4000):
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


for hit_ins in hits:
    print(f"--- Caller @ {hit_ins.address:#x} ---")
    fn = find_fn_start(hit_ins.address)
    print(f"Enclosing fn: {hex(fn) if fn is not None else 'NOT FOUND'}")
    # Show 12 ins of context before the call
    for ins in all_ins:
        if ins.address < hit_ins.address - 32 or ins.address > hit_ins.address + 4:
            continue
        marker = "  <-- CALL HERE" if ins.address == hit_ins.address else ""
        annot = ""
        if ins.mnemonic.startswith("ldr") and "[pc," in ins.op_str:
            try:
                imm_str = ins.op_str.split("#")[-1].rstrip("]").strip()
                imm = -int(imm_str[1:], 16) if imm_str.startswith("-") else int(imm_str, 16)
                lit_addr = ((ins.address + 4) & ~3) + imm
                if 0 <= lit_addr <= len(data) - 4:
                    val = struct.unpack_from('<I', data, lit_addr)[0]
                    s = str_at(val)
                    if s:
                        annot = f"  ; \"{s}\""
                    else:
                        annot = f"  ; lit={val:#x}"
            except Exception:
                pass
        print(f"  {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}{annot}")
    print()
