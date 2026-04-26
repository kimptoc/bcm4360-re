"""T289b-2: trace what struct r7 (callback_arg) points to in wl_probe (fn@0x67614).

From t289b output: hndrte_add_isr's callback_arg = sp[0] = r7 = arg1 of
fn@0x67614 (wl_probe). wlc_callback_ctx = (whatever was passed in r0 to
wl_probe).

Steps:
1. Find references to 0x67614 / 0x67615 (thumb-bit) as literals — wl_probe
   may be installed as a function pointer in a table (struct pcie_driver
   .probe = wl_probe pattern).
2. Find what calls fn@0x67614 (BL #0x67614) — already done in t289b, none
   found. Confirms it's called via fn-ptr.
3. Look for any STR that initializes [(somestruct)+0x10] in the same code
   region — many candidates.

Also: check what r6 is in wl_probe. r6 = arg2 of fn@0x67614, used as
[r6+0x10] via:
  0x67736  ldr r3, [r6, #0x10]
  0x67738  str r3, [r4, #0xc]   ; r4 = wl_dev->[0xc] = r6->[0x10]
  ...
  0x67750  ldr r3, [r6, #0x10]   ; reads r6->[0x10] again
  0x67758  ldr r3, [r3, #0x7c]
  0x6775e  ldr r2, [r3, #0x3c]
And r6 = arg2 of wl_probe.
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def find_lit_exact(val):
    p = val.to_bytes(4, "little")
    out = []
    pos = 0
    while True:
        h = data.find(p, pos)
        if h < 0:
            break
        out.append(h)
        pos = h + 1
    return out


# (1) literal references to wl_probe entry (thumb)
print("=== References to wl_probe (fn@0x67614) ===")
for v in (0x67614, 0x67615):
    hits = find_lit_exact(v)
    print(f"  literal {v:#x}: {len(hits)} hits")
    for h in hits[:10]:
        print(f"    blob_off={h:#x}")

# (2) References to fn@0x1146c (wlc ISR) — already known to be installed
# via hndrte_add_isr at 0x6776c. Let's also scan for direct fn-ptr table
# entries (literal storage).
print("\n=== References to fn@0x1146c (wlc ISR thumb-bit-set) ===")
for v in (0x1146c, 0x1146d):
    hits = find_lit_exact(v)
    print(f"  literal {v:#x}: {len(hits)} hits")
    for h in hits[:10]:
        print(f"    blob_off={h:#x}")

# (3) Find what's at fn@0x1146c — the actual wlc ISR's arg-handling
# fn@0x1146c body per T281: ldr r4, [r0, #0x18]; ldr r0, [r4, #8]; bl 0x23374
# So r0 (wlc_callback_ctx) is dereferenced via [+0x18] then [+8]. The
# pending-events chain in fn@0x2309c is [[r0+0x10][+0x88]]+0x168.
# But fn@0x1146c reads [r0+0x18] not [r0+0x10]! Let me re-read T281.
print("\n=== fn@0x1146c body (re-disasm to verify the chain) ===")
window = data[0x1146C:0x1146C + 64]
for i in md.disasm(window, 0x1146C, count=0):
    print(f"  {i.address:#x}  {i.mnemonic:8s} {i.op_str}")
    if i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str:
        break

print("\n=== fn@0x23374 body — flag check helper ===")
window = data[0x23374:0x23374 + 200]
for i in md.disasm(window, 0x23374, count=0):
    print(f"  {i.address:#x}  {i.mnemonic:8s} {i.op_str}")
    if i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str:
        break
    if i.mnemonic == "bx" and i.op_str == "lr":
        break

print("\n=== fn@0x2309c body — pending-events check ===")
window = data[0x2309C:0x2309C + 200]
for i in md.disasm(window, 0x2309C, count=0):
    print(f"  {i.address:#x}  {i.mnemonic:8s} {i.op_str}")
    if i.mnemonic in ("pop", "pop.w") and "pc" in i.op_str:
        break
