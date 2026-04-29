"""T307 (static target B-pivot, 2026-04-29) — disassemble the bit-0
RTE chipcommon-class ISR body (fn@0xB04).

Per KEY_FINDINGS row 173 (T298 ISR enumeration):
  Node[1]: fn=0x0b05 (Thumb low-bit set; entry at 0xB04), arg=0x0,
           mask=0x1 (OOB bit 0 of oobselouta30)
  Static reach: hndrte_add_isr caller @ 0x63CF0 with class arg=0x800

Goal: enumerate the body; identify what registers/structures it touches
when fired; whether it would advance brcmfmac state if triggered.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from t269_disasm import Cs

BLOB = "/lib/firmware/brcm/brcmfmac4360-pcie.bin"


def disasm_range(blob, entry, size, label):
    chunk = blob[entry : entry + size]
    md = Cs()
    insns = md.disasm(chunk, entry)
    print(f"# {label} fn@0x{entry:04X} (window {size} bytes)")
    end_addr = None
    for i, ins in enumerate(insns):
        b = " ".join(f"{x:02x}" for x in ins.bytes)
        print(f"  0x{ins.address:05X}: {b:<14} {ins.mnemonic:<8} {ins.op_str}")
        if ins.mnemonic == "pop" and "pc" in ins.op_str.lower() and i > 2:
            end_addr = ins.address + ins.size
            print(f"# end at 0x{ins.address:05X}: {ins.mnemonic} {ins.op_str}")
            break
        if ins.mnemonic == "bx" and "lr" in ins.op_str.lower() and i > 2:
            end_addr = ins.address + ins.size
            print(f"# end at 0x{ins.address:05X}: {ins.mnemonic} {ins.op_str}")
            break
    if end_addr:
        # Dump the literal pool that follows
        pool_size = min(64, size - (end_addr - entry))
        if pool_size > 0:
            print(f"\n# literal pool / data after function (0x{end_addr:05X}..0x{end_addr+pool_size:05X}):")
            data = blob[end_addr:end_addr + pool_size]
            for off in range(0, len(data), 16):
                line = data[off:off+16]
                hex_part = " ".join(f"{b:02x}" for b in line)
                # also try interpreting as 32-bit LE words
                words = []
                for w in range(0, len(line), 4):
                    if w + 4 <= len(line):
                        words.append(int.from_bytes(line[w:w+4], "little"))
                ws = " ".join(f"0x{w:08x}" for w in words)
                print(f"  0x{end_addr + off:05X}: {hex_part:<48} {ws}")
    print()


def main():
    with open(BLOB, "rb") as f:
        blob = f.read()
    # The real ISR body
    disasm_range(blob, 0x0ABC, 96, "RTE chipcommon-class ISR (real body)")
    # The thunk
    disasm_range(blob, 0x0B04, 32, "thunk that loads sched_ctx and 0x62994")
    # The function called at 0xAD0 — fn@0xAB4 — appears to return the dispatch table
    disasm_range(blob, 0x0AB4, 16, "fn@0xAB4 (dispatch-table getter / pre-call)")


if __name__ == "__main__":
    main()
