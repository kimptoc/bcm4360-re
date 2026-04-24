"""T281: properly determine fn@0x23374 extent and disasm it fully.

T273 notes say it's a 'flag-byte helper'. Disasm up to the next clear
function boundary (next push/bx-lr-then-push pattern).
"""
import struct, sys
sys.path.insert(0, '/home/kimptoc/bcm4360-re/phase6')
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()

md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

# Disasm a large window starting at 0x23374 and print until we see a
# natural boundary (BX LR followed by alignment/push/mov).
window = data[0x23374:0x23374 + 256]
ins = list(md.disasm(window, 0x23374, count=0))
saw_ret = False
for i in ins:
    print(f"  {i.address:#7x}  {i.mnemonic:6s}  {i.op_str}")
    # BX LR = return; note it but keep printing a few more for context
    if i.mnemonic == "bx" and i.op_str == "lr":
        saw_ret = True
    # Push marks start of next function; stop shortly after
    if saw_ret and i.mnemonic == "push":
        print("  --- likely next function prologue; stopping ---")
        break
