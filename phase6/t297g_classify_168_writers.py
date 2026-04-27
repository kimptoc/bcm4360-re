"""T297-7: classify each [reg, +0x168] / [reg, +0x16C] write site.

For each hit:
- Find enclosing function (best-effort via push-lr scan with end-detection)
- Dump 8-instruction context around the write
- Classify: producer (sets bits) vs consumer (W1C clear) vs other

The producer pattern looks like: load a constant bit value, OR or just store
into the word.

The consumer pattern (T281 description) looks like:
  ldr r6, [r5, #0x168]  ; read pending
  ... mask ops ...
  str r0, [r5, #0x168]  ; W1C clear

Goal: settle T281's HW-MMIO inference vs. SW-word interpretation.
If multiple distinct producer fns exist, the SW interpretation is favoured.
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


print("Disasm pass…")
all_ins = list(iter_all())
ins_by_addr = {ins.address: ins for ins in all_ins}
addrs = sorted(ins_by_addr.keys())
print(f"Total: {len(all_ins):,} ins\n")


def find_fn_start(addr, scan_back=0x800):
    """Walk back through the cached stream, looking for the latest push-lr
    that is NOT followed by a pop-pc/bx-lr before addr."""
    pushes = []
    ends_after = {}
    start = max(0, addr - scan_back)
    for ins in all_ins:
        if ins.address < start or ins.address >= addr:
            continue
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


def context(addr, before=8, after=8):
    """Return ~16 ins of context around addr."""
    out = []
    for a in addrs:
        if a < addr - before * 4 or a > addr + after * 4:
            continue
        ins = ins_by_addr[a]
        marker = "  <-- HERE" if a == addr else ""
        out.append(f"     {a:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}")
    return "\n".join(out)


# Build the lists from t297f's results
SITES_168 = [
    ("0x15640", 0x15640, "str.w"),
    ("0x15ede", 0x15EDE, "str.w"),
    ("0x23108", 0x23108, "str.w"),
    ("0x2bdc0", 0x2BDC0, "strh.w"),
    ("0x3cb18", 0x3CB18, "strb.w"),
]
SITES_16C = [
    ("0x142ce", 0x142CE, "strb.w"),
    ("0x14310", 0x14310, "strb.w"),
    ("0x187fc", 0x187FC, "strb.w"),
    ("0x230fe", 0x230FE, "str.w"),
    ("0x23402", 0x23402, "str.w"),
    ("0x23420", 0x23420, "str.w"),
    ("0x23448", 0x23448, "str.w"),
]
ADDR_BUILDERS = [
    ("0x3cad2", 0x3CAD2, "add"),
    ("0x3dfee", 0x3DFEE, "add"),
]


def section(name, sites):
    print(f"\n{'='*72}")
    print(f"=== {name} ===")
    print(f"{'='*72}")
    for tag, addr, mn in sites:
        fn = find_fn_start(addr, scan_back=0x1000)
        print(f"\n--- {tag} ({mn}) ---")
        print(f"Enclosing fn (push-lr scan): {hex(fn) if fn is not None else 'NOT FOUND'}")
        print(context(addr))


section("STORES to [reg, +0x168]", SITES_168)
section("STORES to [reg, +0x16C]", SITES_16C)
section("ADDR-BUILDERS: add rN, rM, #0x168", ADDR_BUILDERS)
