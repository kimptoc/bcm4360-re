"""T297-1: identify the 3 unknown writers of [..., #0x88] from T289b §3.

Per phase6/t289b_findings.md §3, eight stores to [..., #0x88] exist; five are
characterized. Three unknowns:

- 0x6A070 — "(fn TBD)  r3 = TBD"
- 0x7346 — strh.w (16-bit; probably not a 32-bit base — verify)
- 0x1BB28 — strh.w to sp+0x88 (stack frame; irrelevant — verify)

For each: identify enclosing function, value source, struct context.
Rule out the 16-bit / stack-frame cases; characterize the genuine candidate.

We're hunting for the writer of flag_struct[+0x88]. flag_struct shape (per
fn@0x23374 + fn@0x2309C):
  - [+0xAC] byte (enabled flag)
  - [+0x60] dword (queue state)
  - [+0x88] dword (wake-gate base ABS address)
  - [+0x168/+0x16C] read at flag_struct[+0x88] BASE — i.e. wake-gate is at base+0x168

If a [+0x88] writer's enclosing fn ALSO writes [+0x60] or [+0xAC] in the same
allocation site, that's the flag_struct allocator.
"""
import struct, sys

sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
md.detail = True


def find_fn_start(addr, scan_back=0x600):
    """Walk back from addr looking for the most recent push {..., lr} — the
    classic Thumb fn prologue. Returns the prologue address or None."""
    start = max(0, addr - scan_back)
    candidates = []
    for ins in md.disasm(data[start:addr], start):
        if ins.mnemonic == "push" and "lr" in ins.op_str:
            candidates.append(ins.address)
    return candidates[-1] if candidates else None


def context(addr, before=24, after=24):
    """Disasm ~10 ins around addr."""
    start = max(0, addr - before)
    end = min(len(data), addr + after)
    out = []
    for ins in md.disasm(data[start:end], start):
        marker = "  <-- HERE" if ins.address == addr else ""
        out.append(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}{marker}")
    return "\n".join(out)


targets = [0x6A070, 0x7346, 0x1BB28]

for tgt in targets:
    print(f"\n{'='*72}")
    print(f"=== Site @ 0x{tgt:x} ===")
    print(f"{'='*72}")
    fn = find_fn_start(tgt)
    print(f"Enclosing fn (best guess via prev push lr): {hex(fn) if fn is not None else 'NONE'}")
    if fn is not None:
        print(f"\n--- Context (~10 ins) ---")
    print(context(tgt))


# Bonus: scan for ALL writers of [..., #0x88] using a 32-bit str.w that lands
# in the 0x80..0x90 immediate range — make sure T289b's list of 8 is exhaustive.
print(f"\n{'='*72}")
print(f"=== Re-scan: all str/str.w/strd to [..., #0x88] (32-bit only) ===")
print(f"{'='*72}")
hits = []
for ins in md.disasm(data, 0):
    if ins.mnemonic in ("str", "str.w", "strd") and ", #0x88]" in ins.op_str:
        hits.append((ins.address, ins.mnemonic, ins.op_str))
for addr, mn, op in hits:
    print(f"  {addr:#7x}  {mn:8s} {op}")
print(f"Total 32-bit hits: {len(hits)}")

# Also strb (1-byte) and strh (2-byte) — for completeness
print(f"\n=== strb/strh to [..., #0x88] (sub-32-bit) ===")
sub_hits = []
for ins in md.disasm(data, 0):
    if ins.mnemonic in ("strb", "strb.w", "strh", "strh.w") and ", #0x88]" in ins.op_str:
        sub_hits.append((ins.address, ins.mnemonic, ins.op_str))
for addr, mn, op in sub_hits:
    print(f"  {addr:#7x}  {mn:8s} {op}")
print(f"Total sub-32-bit hits: {len(sub_hits)}")
