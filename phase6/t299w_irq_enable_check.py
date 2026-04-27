"""T299w: verify the IRQ-disabled architecture conclusion.

Bootstrap at 0x4e sets CPSR = 0xdf (I and F bits set = IRQ+FIQ disabled).
Search for any code that RE-ENABLES IRQs (cpsie i, msr cpsr_c with I bit clear,
or similar). If none, the entire ARM-CR4 firmware runs in polling mode and
the wake-gate INTMASK path is genuinely dead.
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


print("Disasm pass...")
all_ins = list(iter_all())
print(f"Total ins: {len(all_ins):,}\n")


# (1) Find ALL CPSR-modifying / IRQ-control instructions
print("=== (1) ALL CPSR-control / IRQ-enable/disable instructions ===")
target_mnems = ("cpsie", "cpsid", "cps", "msr", "wfi", "wfe", "sev")
hits = []
for ins in all_ins:
    if ins.mnemonic in target_mnems:
        hits.append(ins)
print(f"  Total CPSR-related insns: {len(hits)}")
print(f"\n  Distribution by mnemonic:")
from collections import Counter
mnem_counts = Counter(i.mnemonic for i in hits)
for m, c in mnem_counts.most_common():
    print(f"    {m}: {c}")

print(f"\n  All instances:")
for ins in hits:
    print(f"    {ins.address:#7x}  {ins.mnemonic:8s} {ins.op_str}")


# (2) Specifically: any cpsie i (or cpsie if) — re-enables IRQ
print("\n\n=== (2) cpsie variants (would re-enable IRQ/FIQ) ===")
for ins in hits:
    if ins.mnemonic == "cpsie":
        print(f"  ★ {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# (3) Specifically: msr cpsr* with constants that have I=0
print("\n\n=== (3) msr cpsr_* — what value sets the I bit? ===")
for ins in hits:
    if ins.mnemonic == "msr" and "cpsr" in ins.op_str.lower():
        print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


# (4) Any wfi/wfe in the firmware (where it sleeps waiting for events)
print("\n\n=== (4) wfi/wfe instructions (CPU halt waiting for event) ===")
for ins in hits:
    if ins.mnemonic in ("wfi", "wfe"):
        print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")
