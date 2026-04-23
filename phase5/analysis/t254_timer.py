from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f: blob = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)

def find_end(start, max_scan=0x200):
    for off in range(start+4, start+max_scan, 2):
        w16 = int.from_bytes(blob[off:off+2], "little")
        if w16 == 0xe92d or ((w16 & 0xff00) == 0xb500 and (w16 & 0xff) != 0):
            return off
    return start+max_scan

end = find_end(0x1EC)
print(f"0x1EC function end: 0x{end:06X}  (size {end-0x1EC} bytes)")
for insn in md.disasm(blob[0x1EC:end], 0x1EC):
    print(f"  0x{insn.address:06X}: {insn.mnemonic:<8} {insn.op_str}")
    if insn.mnemonic.startswith("ldr") and "[pc," in insn.op_str:
        try:
            off = int(insn.op_str.split("#")[-1].strip().rstrip("]"), 16)
            pc_rel = (insn.address + 4) & ~3
            lit = pc_rel + off
            val = int.from_bytes(blob[lit:lit+4], "little")
            print(f"           lit@0x{lit:06X} = 0x{val:08X}")
        except Exception:
            pass

print()
# 0x58C98 is an address in TCM where the tick-rate is stored at runtime.
# Check the blob content at that offset (may be fw-initialized data or zeros).
hex_bytes = blob[0x58C98:0x58CA0].hex()
val = int.from_bytes(blob[0x58C98:0x58C9C], "little")
print(f"blob[0x58C98..+8]: {hex_bytes}  first_u32=0x{val:08X}")

# Also check the delay function's relationship to other places that might call 0x1EC.
# If 0x1EC reads a memory-mapped counter, identify the MMIO address.
