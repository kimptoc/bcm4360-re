"""Find function containing 0x11CC (which b.w's to 0x1C0C → 0x1C1E WFI).
Then find its callers."""
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_prev_fn(addr, max_back=0x2000):
    for off in range(addr, max(0, addr - max_back), -2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d:
            return off
        if (w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0:
            return off
    return None

fn_start = find_prev_fn(0x11CC)
print(f"Function containing 0x11CC starts at 0x{fn_start:06X}")

# Disassemble the full function (up to next push or 200 bytes)
print(f"\nDisasm of 0x{fn_start:06X}:")
# Find function end — next push after fn_start+4
def find_next_push(start, max_scan=0x400):
    for off in range(start + 4, start + max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d or ((w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0):
            return off
    return start + max_scan

fn_end = find_next_push(fn_start)
print(f"Function spans 0x{fn_start:06X}..0x{fn_end:06X} ({fn_end-fn_start} bytes)")

for insn in md.disasm(blob[fn_start:fn_end], fn_start):
    mark = " <-- WFI path" if insn.address == 0x11CC else ""
    # Resolve pc-relative literals
    if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
        try:
            imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
            pc_rel = (insn.address + 4) & ~3
            lit = pc_rel + imm
            if lit + 4 <= len(blob):
                val = int.from_bytes(blob[lit:lit+4], "little")
                print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{mark}")
                print(f"             lit@0x{lit:06X} = 0x{val:08X}")
                continue
        except Exception:
            pass
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}{mark}")

# Callers of fn_start
def scan_callers(target_addr):
    callers = []
    for off in range(0, 0x6BF78, 2):
        for insn in md.disasm(blob[off:off+4], off):
            if insn.mnemonic in ("bl", "blx", "b.w"):
                op = insn.op_str
                if op.startswith("#"):
                    try:
                        t = int(op.strip("#"), 16)
                        if t == target_addr:
                            callers.append((insn.address, insn.mnemonic))
                    except ValueError:
                        pass
            break
    return callers

def scan_literal_refs(target_val):
    results = []
    for pat_val in (target_val, target_val | 1):
        p = pat_val.to_bytes(4, "little")
        pos = 0
        while True:
            hit = blob.find(p, pos)
            if hit < 0: break
            results.append((hit, pat_val))
            pos = hit + 1
    return results

callers = scan_callers(fn_start)
print(f"\n=== Direct callers of 0x{fn_start:06X}: {len(callers)} ===")
for a, m in callers[:20]:
    print(f"  0x{a:06X}: {m} #0x{fn_start:06X}")

refs = scan_literal_refs(fn_start)
print(f"\n=== Literal-pool refs to 0x{fn_start:06X} (fn-ptr storage): {len(refs)} ===")
for hit, val in refs[:10]:
    print(f"  lit@0x{hit:06X} = 0x{val:08X}")
    # Show small context — what instruction loads this?
    for back_off in range(max(0, hit - 0x100), hit, 2):
        for insn in md.disasm(blob[back_off:back_off+4], back_off):
            if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
                try:
                    imm = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
                    pc_rel = (insn.address + 4) & ~3
                    if pc_rel + imm == hit:
                        print(f"    referenced by LDR at 0x{insn.address:06X}")
                except Exception:
                    pass
            break
