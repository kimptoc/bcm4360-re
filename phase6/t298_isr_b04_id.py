"""T298 follow-up: identify the ISR at fn@0xB04 and its registering function
@ 0x63CF0. Disasm prologue/body of fn@0xB04 + look for nearby string refs.
"""
import os, sys, struct, re
sys.path.insert(0, os.path.dirname(__file__))
from t269_disasm import Cs

with open('/lib/firmware/brcm/brcmfmac4360-pcie.bin','rb') as f:
    blob = f.read()

md = Cs()

def disasm_range(start, end):
    out = []
    i = start
    while i < end:
        ins = md.disasm(blob[i:i+4], i)
        if not ins:
            i += 2
            continue
        out.append(ins[0])
        i += ins[0].size
    return out

print("=== fn@0xB04 (the unknown ISR) — first 64 bytes ===")
for ins in disasm_range(0xB04, 0xB44):
    print(f"  0x{ins.address:05x}: {ins.mnemonic:8s} {ins.op_str}")

print()
print("=== ldr-from-pool resolution within fn@0xB04 first 64 bytes ===")
# Walk the disasm and decode every pc-relative ldr literal
for ins in disasm_range(0xB04, 0xB44):
    if ins.mnemonic.startswith('ldr') and 'pc' in ins.op_str:
        try:
            imm = int(ins.op_str.split('#')[-1].rstrip(']').strip(), 0)
            pool = ((ins.address + 4) & ~3) + imm
            val = struct.unpack('<I', blob[pool:pool+4])[0]
            # if val looks like a string offset try to decode
            decoded = None
            if 0 <= val < len(blob):
                end = val
                while end < len(blob) and 0x20 <= blob[end] <= 0x7e and end - val < 80:
                    end += 1
                if end - val >= 4:
                    decoded = blob[val:end].decode('latin1','replace')
            print(f"  0x{ins.address:05x}: {ins.mnemonic} {ins.op_str}  ->  pool[0x{pool:x}] = 0x{val:08x}" +
                  (f"  str=\"{decoded}\"" if decoded and len(decoded) <= 60 else ""))
        except (ValueError, IndexError):
            pass

print()
print("=== caller @ 0x63CF0 — disasm 96 bytes back to find fn boundary ===")
# Walk back from 0x63CF0 to find function start (push lr or proper prologue)
# Then disasm from there
for back in range(0, 200, 2):
    ip = 0x63CF0 - back
    ins = md.disasm(blob[ip:ip+4], ip)
    if ins and ins[0].mnemonic == 'push' and 'lr' in ins[0].op_str:
        print(f"  candidate fn start: 0x{ip:x}: {ins[0].mnemonic} {ins[0].op_str}")
        # disasm from here through the call
        for d in disasm_range(ip, 0x63CF8):
            print(f"  0x{d.address:05x}: {d.mnemonic:8s} {d.op_str}")
        break

print()
print("=== caller @ 0x1F28 — disasm 96 bytes back ===")
for back in range(0, 200, 2):
    ip = 0x1F28 - back
    ins = md.disasm(blob[ip:ip+4], ip)
    if ins and ins[0].mnemonic == 'push' and 'lr' in ins[0].op_str:
        print(f"  candidate fn start: 0x{ip:x}: {ins[0].mnemonic} {ins[0].op_str}")
        break

print()
print("=== caller @ 0x67774 — disasm 96 bytes back ===")
for back in range(0, 200, 2):
    ip = 0x67774 - back
    ins = md.disasm(blob[ip:ip+4], ip)
    if ins and ins[0].mnemonic == 'push' and 'lr' in ins[0].op_str:
        print(f"  candidate fn start: 0x{ip:x}: {ins[0].mnemonic} {ins[0].op_str}")
        break

print()
print("=== string refs near each caller (within 256 bytes) ===")
for caller in (0x1F28, 0x63CF0, 0x67774):
    for back in range(2, 256, 2):
        ip = caller - back
        ins = md.disasm(blob[ip:ip+4], ip)
        if ins and ins[0].mnemonic.startswith('ldr') and 'pc' in ins[0].op_str:
            try:
                imm = int(ins[0].op_str.split('#')[-1].rstrip(']').strip(), 0)
                pool = ((ip + 4) & ~3) + imm
                val = struct.unpack('<I', blob[pool:pool+4])[0]
                if 0 <= val < len(blob):
                    end = val
                    while end < len(blob) and 0x20 <= blob[end] <= 0x7e and end - val < 80:
                        end += 1
                    if end - val >= 6:
                        s = blob[val:end].decode('latin1','replace')
                        print(f"  caller 0x{caller:x}: {ins[0].address:#x} ldr -> str@0x{val:x} = {s!r}")
            except (ValueError, IndexError):
                pass
    print()
