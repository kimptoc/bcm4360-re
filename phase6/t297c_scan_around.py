"""Scan with different alignments to find correct decode of region around 0x6A070."""
import sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open('/lib/firmware/brcm/brcmfmac4360-pcie.bin','rb') as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

target = 0x6A070
# Show that the disasm of [0x6A058..0x6A088] (region we know is good) does work
print("=== Disasm [0x6A040..0x6A090) — should match site context ===")
for ins in md.disasm(data[0x6A040:0x6A090], 0x6A040):
    print(f"  {ins.address:#x}  {ins.mnemonic:8s} {ins.op_str}")

print("\n=== Disasm [0x69F00..0x6A040) — backward into fn body ===")
for ins in md.disasm(data[0x69F00:0x6A040], 0x69F00):
    if ins.mnemonic == 'push' and 'lr' in ins.op_str:
        print(f"  {ins.address:#x}  *** PUSH {ins.op_str}")
    elif ins.mnemonic == 'pop' and 'pc' in ins.op_str:
        print(f"  {ins.address:#x}  *** POP {ins.op_str}")
    elif ins.mnemonic == 'bx' and ins.op_str.strip() == 'lr':
        print(f"  {ins.address:#x}  *** BX LR")
    elif ins.mnemonic.startswith('b') and not ins.mnemonic.startswith('bl') and 'r' not in ins.op_str:
        # Show branches
        print(f"  {ins.address:#x}  {ins.mnemonic} {ins.op_str}")

print("\n=== Look harder: disasm fwd from each possible push lr location ===")
# Try aligning at various offsets in the region
for align in [0x69D00, 0x69E00, 0x69F00, 0x6A000]:
    print(f"\nFrom 0x{align:x}:")
    for i, ins in enumerate(md.disasm(data[align:align+0x80], align)):
        print(f"  {ins.address:#x}  {ins.mnemonic:8s} {ins.op_str}")
        if i > 16:
            break
