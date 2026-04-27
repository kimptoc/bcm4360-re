"""T298: enumerate hndrte_add_isr (fn@0x63C24) call sites in fw blob.
For each call, walk back ~80 bytes to find the immediately-preceding
literal-pool ldr that loads r3 (the callback fn-ptr arg). Build a
fn-ptr -> caller -> name table to interpret test.298's runtime
node[+4] dump.

Read-only static analysis. No hardware fires.
"""
import os, sys, struct
sys.path.insert(0, os.path.dirname(__file__))
from t269_disasm import Cs

BLOB = '/lib/firmware/brcm/brcmfmac4360-pcie.bin'
HNDRTE_ADD_ISR = 0x63C24

with open(BLOB,'rb') as f:
    blob = f.read()

md = Cs()

# Pass 1: find all bl/blx instructions targeting hndrte_add_isr (Thumb-2 BL = 4 bytes)
callers = []
i = 0
while i < len(blob)-4:
    out = md.disasm(blob[i:i+4], i)
    if out:
        ins = out[0]
        if ins.mnemonic in ('bl','blx') and ins.op_str.startswith('#'):
            try:
                tgt = int(ins.op_str[1:], 16)
            except ValueError:
                tgt = -1
            if tgt in (HNDRTE_ADD_ISR, HNDRTE_ADD_ISR | 1):
                callers.append(i)
    i += 2

print(f"hndrte_add_isr (0x{HNDRTE_ADD_ISR:x}) direct bl/blx call sites: {len(callers)}")
print()

def resolve_lit(pool_addr):
    if pool_addr + 4 > len(blob):
        return None
    return struct.unpack('<I', blob[pool_addr:pool_addr+4])[0]

# For each caller, walk back up to 96 bytes looking for ldr/ldr.w that loads r3
# (the fn-ptr arg) from the literal pool. Also collect ldr loads of any reg
# in case fn-ptr is loaded via mov from another register.
for c in callers:
    print(f"=== call site 0x{c:x} ===")
    for back in range(2, 96, 2):
        ip = c - back
        if ip < 0:
            break
        out = md.disasm(blob[ip:ip+4], ip)
        if not out:
            continue
        ins = out[0]
        mn, op = ins.mnemonic, ins.op_str
        if mn.startswith('ldr') and 'pc' in op:
            try:
                imm_str = op.split('#')[-1].rstrip(']').strip()
                imm = int(imm_str, 0)
                pc_at_load = (ip + 4) & ~3
                pool = pc_at_load + imm
                val = resolve_lit(pool)
                if val is not None:
                    print(f"  pre-call 0x{ip:x}: {mn} {op}  -> pool[0x{pool:x}] = 0x{val:08x}  (Thumb-fn? 0x{val & ~1:x})")
            except ValueError:
                pass
    print()

# Cross-ref: known callback strings in blob (search wider)
import re
patterns = [b'_isr', b'wlc_isr', b'pciedngl_isr', b'pcidongle_probe', b'hndrte']
for pat in patterns:
    for m in re.finditer(re.escape(pat), blob):
        # extract context as null-term string
        start = m.start()
        # walk back to find string start
        sb = start
        while sb > 0 and 0x20 <= blob[sb-1] <= 0x7e:
            sb -= 1
        end = m.end()
        while end < len(blob) and 0x20 <= blob[end] <= 0x7e:
            end += 1
        s = blob[sb:end].decode('latin1','replace')
        if 5 <= len(s) <= 80:
            print(f"str@0x{sb:x} = {s!r}")
