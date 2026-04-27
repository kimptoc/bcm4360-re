"""T297-8: characterize the HW MMIO block that flag_struct[+0x88] points to.

Findings so far:
- fn@0x15638 reads [r0, +0x88] (= wake-gate BASE) then writes -1 to [+0x168]
  AND tst.w against [+0x128] bit-0 (different register on same block)
- fn@0x15E92 writes constant masks to [+0x168], [+0x188], [+0x18C], and writes
  0x10000 to a NEAR struct offset [+0x64] (which may be flag_struct itself or
  another struct mid-fn)
- fn@0x2309C / 0x233E8 / 0x2340C all write to [+0x168] / [+0x16C]
  (consumers; W1C semantic)

Goal: enumerate all loads + stores of `[X, #imm]` where X = result of `ldr X, [Y, #0x88]`
in functions that follow the flag_struct chain. Build the register-block layout
(which offsets are loaded as state, which are W1C-cleared, etc.)

If the offset pattern matches a known HW core (chipcommon / D11 / PCIE2 / ARM-CR4),
that's the wake-gate identification.
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
print(f"Total: {len(all_ins):,}\n")


# Find all functions that contain `ldr.w r?, [r?, #0x88]` AND a subsequent
# store/load to [r?, #imm] where r? = result of the ldr.
# Then enumerate the offsets touched.

# Simplification: scan windowed regions [hit-32B .. hit+200B] around each
# [reg, +0x88] LOAD; find all subsequent [target_reg, +imm] accesses.

# Step 1: find all ldr.w r?, [r?, #0x88] hits
print("=== Step 1: all `ldr/ldr.w rN, [rM, #0x88]` loads ===")
ldr_88_hits = []
for ins in all_ins:
    if ins.mnemonic in ("ldr", "ldr.w") and ", #0x88]" in ins.op_str:
        # Skip sp-relative
        if "[sp" in ins.op_str:
            continue
        # Extract dest reg (the loaded value's home)
        try:
            dest = ins.op_str.split(",")[0].strip()
            ldr_88_hits.append((ins.address, dest, ins.op_str))
        except Exception:
            pass

print(f"Found {len(ldr_88_hits)} loads of [reg, +0x88]")
for a, d, op in ldr_88_hits[:30]:
    print(f"  {a:#7x}  ldr {d:5s} ← {op}")
if len(ldr_88_hits) > 30:
    print(f"  ... {len(ldr_88_hits)-30} more ...")


# Step 2: for each ldr [+0x88], scan next 200 bytes for str/ldr to [target_reg, #imm]
print(f"\n=== Step 2: register-block layout (offsets accessed via [+0x88]-loaded reg) ===\n")
all_offsets_touched = {}  # offset → list of (addr, mnemonic, ldr_site)
for site_addr, dest_reg, _ in ldr_88_hits:
    # Pull a 200-byte window of subsequent ins
    for ins in all_ins:
        if ins.address <= site_addr or ins.address > site_addr + 200:
            continue
        # Match anything like `..., [<dest_reg>, #imm]` or `[<dest_reg>, #imm]`
        # Specifically: store or load
        if ins.mnemonic not in (
            "str","str.w","strb","strb.w","strh","strh.w","strd",
            "ldr","ldr.w","ldrb","ldrb.w","ldrh","ldrh.w","ldrd",
        ):
            continue
        bracket_str = f"[{dest_reg}, #"
        if bracket_str not in ins.op_str:
            continue
        # Parse offset
        try:
            after = ins.op_str.split(bracket_str)[-1]
            off_s = after.rstrip("]").strip().rstrip("!").strip()
            off = int(off_s, 16) if off_s.startswith("0x") else int(off_s)
        except Exception:
            continue
        kind = "STORE" if ins.mnemonic.startswith("str") else "LOAD"
        all_offsets_touched.setdefault(off, []).append((ins.address, ins.mnemonic, kind, site_addr))

# Print sorted summary
print("Register-block offsets accessed:")
print(f"  {'offset':>6}  {'  loads':>9}  {'  stores':>9}   examples")
print(f"  {'------':>6}  {'-------':>9}  {'-------':>9}   --------")
for off in sorted(all_offsets_touched.keys()):
    sites = all_offsets_touched[off]
    loads = sum(1 for _, _, k, _ in sites if k == "LOAD")
    stores = sum(1 for _, _, k, _ in sites if k == "STORE")
    examples = ", ".join(f"{m}@{a:#x}" for a, m, k, _ in sites[:3])
    print(f"  {off:#6x}  {loads:>9d}  {stores:>9d}   {examples}")

# Specifically highlight the wake-gate offsets
print(f"\n=== WAKE-GATE OFFSETS: 0x128, 0x168, 0x16C, 0x188, 0x18C, 0x180 ===")
for key_off in (0x128, 0x168, 0x16C, 0x180, 0x188, 0x18C, 0x16C, 0x28):
    if key_off in all_offsets_touched:
        sites = all_offsets_touched[key_off]
        print(f"\n[+{key_off:#x}]: {len(sites)} access(es)")
        for a, m, k, ldr_site in sites:
            print(f"  {a:#x}  {m:8s}  ({k})   from ldr-site @ {ldr_site:#x}")
