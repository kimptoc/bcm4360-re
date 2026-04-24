"""T269 step 1: walk scheduler callback list to locate pciedngl_isr (node[0]).

Prior T254/T256 work: scheduler at 0x115C walks a linked list headed at
[0x629A4] with per-node layout (from T254 §7 read of the scheduler loop):

  +0x0  next
  +0x4  fn-ptr (Thumb, LSB=1)
  +0x8  arg
  +0xC  flag (tested with scheduler r5 = bl 0x9936 return value)

Blob maps to both flash base 0 (for code) and TCM at runtime; for static
analysis we treat the file offset == load address, so BSS data values at
offsets like 0x629A4 read directly.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from t269_disasm import Cs

BLOB = "/home/kimptoc/brcmfmac4360-pcie.bin"
with open(BLOB, "rb") as f:
    blob = f.read()

md = Cs()


def u32(off):
    return int.from_bytes(blob[off:off + 4], "little")


LIST_HEAD = 0x629A4
print(f"List head @ 0x{LIST_HEAD:X} = 0x{u32(LIST_HEAD):08X}")
print(f"Current-task ptr @ 0x6299C = 0x{u32(0x6299C):08X}")
print(f"Sleep-flag @ 0x629B4 = 0x{u32(0x629B4):08X}")

print("\n=== Walk list ===")
node = u32(LIST_HEAD)
seen = set()
i = 0
nodes = []
while node and node not in seen and i < 32:
    seen.add(node)
    nxt = u32(node + 0x0)
    fn = u32(node + 0x4)
    arg = u32(node + 0x8)
    flag = u32(node + 0xC)
    print(f"node[{i}] @ 0x{node:06X}:")
    print(f"  next  = 0x{nxt:08X}")
    print(f"  fn    = 0x{fn:08X}   (entry=0x{(fn & ~1):06X}, thumb={'yes' if fn & 1 else 'no'})")
    print(f"  arg   = 0x{arg:08X}")
    print(f"  flag  = 0x{flag:08X}")
    nodes.append((node, fn & ~1, arg, flag))
    node = nxt
    i += 1
print(f"Total nodes: {i}")

if not nodes:
    print("\nList head is zero in blob image. Checking for nearby pointers...")
    for off in range(0x62900, 0x62A00, 4):
        v = u32(off)
        if 0x50000 <= v < 0xA0000:
            print(f"  0x{off:05X} -> 0x{v:08X}")
    sys.exit(0)

# Prologue check: each node[0..].fn entry.
print("\n=== Prologue scan for each node.fn ===")
for idx, (_, fn, _, _) in enumerate(nodes):
    first = int.from_bytes(blob[fn:fn + 2], "little")
    first4 = int.from_bytes(blob[fn:fn + 4], "little")
    is_push_short = (first & 0xFF00) == 0xB500 and (first & 0xFF) != 0
    is_push_wide = (first4 & 0xFFFF) == 0xE92D
    is_push = is_push_short or is_push_wide
    print(f"  node[{idx}] fn=0x{fn:06X} first2=0x{first:04X} push-like? {is_push}")

# Disassemble node[0] fn prologue (~60 insns).
print("\n=== pciedngl_isr (node[0]) prologue — first 60 insns ===")
fn = nodes[0][1]
n = 0
for ins in md.disasm(blob[fn:fn + 0x180], fn):
    lit_str = ""
    if ins.mnemonic.startswith("ldr") and "pc," in ins.op_str:
        # ldr rX, [pc, #imm] form
        try:
            imm_str = ins.op_str.split("#")[-1].strip().rstrip("]")
            imm = int(imm_str, 16) if imm_str.startswith("0x") else int(imm_str)
            lit = ((ins.address + 4) & ~3) + imm
            if lit + 4 <= len(blob):
                val = int.from_bytes(blob[lit:lit + 4], "little")
                lit_str = f"  ; lit@0x{lit:06X} = 0x{val:08X}"
        except Exception:
            pass
    print(f"  0x{ins.address:06X}: {ins.mnemonic:<8} {ins.op_str}{lit_str}")
    n += 1
    if n >= 60:
        break
