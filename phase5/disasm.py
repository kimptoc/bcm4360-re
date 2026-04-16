#!/usr/bin/env python3
"""Disassemble BCM4360 firmware code dumps from test.87 journal."""
import sys
import struct
from capstone import *

# Parse hex dumps from journal
def parse_hex_dump(lines, base_addr):
    """Parse 'addr: w0 w1 w2 w3' lines into bytes."""
    data = bytearray()
    for line in lines:
        parts = line.strip().split()
        if len(parts) < 2:
            continue
        # Skip address field (e.g. "01e90:")
        words = parts[1:]
        for w in words:
            try:
                val = int(w, 16)
                data.extend(struct.pack('<I', val))
            except ValueError:
                pass
    return bytes(data)

# pciedngl_probe 0x1E90-0x20FF
probe_lines = """
01e90: 4ff0e92d 4606b085 48304688 49304691
01ea0: f8dd469b f7fea03c 4630fdc3 ffdaf064
01eb0: 4607213c f0052000 4604ff53 4651b920
01ec0: f7fe4828 e03bfdb5 21002500 f7fe223c
01ed0: fd25 f8c4fd25 61e6a000 61274639 464b4642
01ee0: 95004658 95029501 fa36f065 8018f8c4
01ef0: f00760e0 6060fd29 f00768e0 4629fd33
01f00: 463b68e2 462060a0 f99ef062 b9206160
01f10: 48154913 fd8cf7fe 4628e01a 4652990e
01f20: 96004b12 9004f8cd fe7cf061 4810b118
01f30: fd7ef7fe 4620e00c ff84f7ff e0044620
01f40: 21ad480c f950f7ff b0052000 8ff0e8bd
01f50: 46216920 f005223c e7f1ff07 00040692
01f60: 000407f2 0004a075 00040787 00001c99
01f70: 0004079f 000406e5 460eb570 b1784604
01f80: 30248a8d 6909462a ff72f000 7280f44f
01f90: 463169a3 2200629a f0056920 e005ff13
01fa0: f44f4803 f7ff71a0 4625f91f bd704628
01fb0: 000406e5 6981460a 69484603 f0004619
01fc0: 460ab9cd 46036981 46196948 b91cf000
01fd0: 41f0e92d 4b154698 460e4604 681b4615
01fe0: 0f02f013 4812d004 49124642 fd20f7fe
01ff0: 214c4620 feb4f005 b1a04607 224c2100
02000: fc8cf7fe 63e8f44f 800cf8c7 f44f637b
02010: 603e737a 231c63fb 643b607d 60bc3b10
02020: 3b08647b 463864bb 81f0e8bd 00058d24
02030: 0004081c 0004080f 46031e0a 6bc0b510
02040: 6c9cdd13 dd102c00 42a23a01 6c1bda03
02050: 0022f853 4b05b948 f0106818 d0040001
02060: 49044803 fce4f7fe bd102000 00058d24
02070: 000408fb 000408b9 460bb538 6bc1b1f9
02080: d01d428b 21006c85 6c04e00c 4021f854
02090: f10142a3 d1040401 789a6913 709c4314
020a0: 4621e012 dbf042a9 68124a08 0f01f012
020b0: 4907d008 4807461a fcbaf7fe e003e002
020c0: e0012100 31fff04f bd384608 00058d24
020d0: 00040bdb 00040914 0f03f013 47ffe92d
020e0: 603cf89d 46884607 461c4615 9030f8dd
020f0: 481cd003 f7ff2154 4b1bf877 681a469a
""".strip().split('\n')

# init/WFI 0x0160-0x022F
init_lines = """
00160: 4c09b08c 2c006824 4668d0fe b00c47a0
00170: 4680bc7f 46924689 46a4469b b08f46b6
00180: b008bcff c000e9bd 00000224 ea004906
00190: 28000001 4770d100 8100f3ef 0100ea21
001a0: 8900f381 00004770 000000c0 ea004906
001b0: 28000001 4770d100 8100f3ef 0100ea41
001c0: 8900f381 00004770 000000c0 1f1cee19
001d0: ea414a04 ee090102 49031f1c 1f3cee09
001e0: 00004770 00000001 80000000 0f1dee19
001f0: ee154770 47700f10 0f10ee16 ee154770
00200: 47700f30 0f50ee16 00004770 68114a02
00210: 46086010 00004770 00000228 00000a2c
00220: 00000000 00001951 00000000 00000001
""".strip().split('\n')

# WFI area 0x1C00-0x1C3F
wfi_lines = """
01c00: f8d32644 47703644 00062994 b807f000
01c10: f7fe2080 2080babb bac8f7fe bf304770
01c20: b5104770 f0074604 4601fe73 e8bd4620
01c30: f0054010 4770bf39 4903b508 f7fe4803
""".strip().split('\n')

# callees 0x2100-0x24FF
callee_lines = """
02100: 0f02f012 4b19d00b 481a4a19 bf182e00
02110: 4919461a f8cd462b f7fe9000 4638fc89
02120: f7ff4641 b160ff89 46296903 92009a0d
02130: 92019a0e 96024622 464b695e 460447b0
02140: f04fe001 f8da34ff f0133000 d0050f02
02150: 4622480a 46234908 fc6af7fe b0044620
02160: 87f0e8bd 00040940 00058d24 00041812
02170: 0004093a 0004094b 000408c6 0004096a
02180: 4e1cb5f8 460f4604 68334615 0f02f013
02190: 4819d004 6ba24919 fc4af7fe 68604629
021a0: fe50f005 b3184605 46394620 f7ff462a
021b0: 2800ff63 4b12db1c 68204629 68db681b
021c0: b1504798 46296860 f00269e6 6963fef5
021d0: 61633301 61e01980 6ae3e00a 62e33301
021e0: f0136833 d0030f01 49044806 fc20f7fe
021f0: bdf82000 00058d24 0004081c 000408ee
02200: 00062a14 000409ca 41f3e92d 46044f47
02210: 4615460e f013683b d0030f02 49454844
02220: fc06f7fe b92db106 f013683b d0730f01
02230: e0234841 b9526ba2 b9436be3 63a6683b
02240: 0f02f013 627563e5 d03f626e 42b2e03a
02250: 6be3d12c d02942ab 23006ca6 6c21e005
02260: 1023f851 d00442a9 42b33301 2300dbf7
02270: 683be013 0f01f013 4830d04e f7fe492d
02280: e049fbd7 eb016c21 f8510083 33011023
02290: 6005b919 626a4618 42b3e040 e03fdbf2
022a0: 46324924 f7fe4826 e035fbc3 f013683b
022b0: d0310f01 6be3491f 96004822 f7fe9501
022c0: e029fbb7 491b4820 fbb2f7fe 0800f04f
022d0: 46216860 46336822 8000f8cd fe78f7ff
022e0: b92860e0 f013683b d0150f01 e7c54817
022f0: f0106838 d0110010 46404915 ffa8f002
02300: 490c4b14 95004632 bf182800 48124603
02310: fb8ef7fe e0014640 30fff04f 81fce8bd
02320: f012683a d0f70f01 bf00e7ba 00058d24
02330: 00040a25 000408d5 00040a30 00040a4c
02340: 00040a66 00040a92 00040ac5 00040ade
02350: 00040af7 00040a1c 00040afc 4603b537
02360: b932b101 681b4b22 0f01f013 4821d03d
02370: 6b84e00a 6bc0b964 d1292800 681b4b1c
02380: 0f01f013 481cd031 f7fe491c e02cfb51
02390: d11d428c 42906bc0 6c9dd01a e00b2000
023a0: eb016c19 f8510480 30011020 d1034291
023b0: 60232300 e01a6253 dbf142a8 681b4b0c
023c0: 0f01f013 490dd011 f7fe480d e00cfb31
023d0: 68004807 0f01f010 9100d007 46229201
023e0: 49064808 f7fe6bdb f04ffb23 bd3e30ff
023f0: 00058d24 00040a30 00040b1d 00040beb
02400: 00040b34 00040a92 f061b510 f7fdff67
02410: f061fedd 4604ff73 fc28f7fe e8bd4620
02420: f7fe4010 ea41bed5 ea420300 f0130303
02430: b5300f03 680cd114 ea846803 60130303
02440: 6843684c 0303ea84 688c6053 ea846883
02450: 60930303 68c368c9 0303ea81 bd3060d3
02460: 5ccd2300 ea855cc4 54d40404 2b103301
02470: bd30d1f7 00c5b570 4614b0bc 462a4668
02480: f006461e 0969fb0b 31064668 46334622
02490: fd1ef006 bd70b03c b085b530 461d4614
024a0: 466b4a15 ffe6f7ff 2200230f 1003f81d
024b0: 0241ea42 09ca54e2 d2f73b01 3000f99d
024c0: da042b00 490d4620 f7ff4622 230fffac
024d0: 5ce12200 0241ea42 5ce254ea 3b0109d2
024e0: f994d2f7 2b003000 4628da04 462a4903
024f0: ff99f7ff bd30b005 00040ce7 00040cf7
""".strip().split('\n')

def parse_and_disasm(name, lines, base_addr):
    """Parse hex dump and disassemble as ARM Thumb-2."""
    data = parse_hex_dump(lines, base_addr)

    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
    md.detail = True

    print(f"\n{'='*60}")
    print(f"  {name} @ 0x{base_addr:04X} ({len(data)} bytes)")
    print(f"{'='*60}")

    for insn in md.disasm(data, base_addr):
        # Mark interesting instructions
        mark = ""
        mnem = insn.mnemonic.lower()
        if mnem in ('b', 'bne', 'beq', 'bcs', 'bcc', 'bhi', 'bls', 'bge', 'blt', 'bgt', 'ble', 'bpl', 'bmi', 'bvs', 'bvc', 'bhs', 'blo'):
            mark = "  <-- branch"
        elif mnem in ('bl', 'blx'):
            mark = "  <-- CALL"
        elif mnem == 'wfi':
            mark = "  <-- WFI (wait for interrupt)"
        elif mnem in ('ldr', 'ldrb', 'ldrh') and '[' in insn.op_str:
            mark = "  <-- load"
        elif mnem in ('str', 'strb', 'strh') and '[' in insn.op_str:
            mark = "  <-- store"
        elif mnem in ('cmp', 'cmn', 'tst', 'teq'):
            mark = "  <-- compare"
        elif mnem == 'pop' and 'pc' in insn.op_str:
            mark = "  <-- RETURN"
        elif mnem == 'bx' and 'lr' in insn.op_str:
            mark = "  <-- RETURN"

        print(f"  0x{insn.address:04x}: {insn.bytes.hex():<12s} {insn.mnemonic:<8s} {insn.op_str}{mark}")

# Fix the probe_lines - there's a bad line with extra "fd25"
fixed_probe_lines = []
for line in probe_lines:
    # Fix line "01ed0: fd25 f8c4fd25 ..." -> "01ed0: f8c4fd25 ..."
    if line.strip().startswith("01ed0: fd25"):
        line = "01ed0: f8c4fd25 61e6a000 61274639 464b4642"
    fixed_probe_lines.append(line)

import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    parse_and_disasm("pciedngl_probe", fixed_probe_lines, 0x1E90)
    parse_and_disasm("init spin + handlers", init_lines, 0x0160)
    parse_and_disasm("WFI area", wfi_lines, 0x1C00)
    parse_and_disasm("callees (0x2100+)", callee_lines, 0x2100)
with open("/home/kimptoc/bcm4360-re/phase5/disasm_output.txt", "w") as f:
    f.write(buf.getvalue())
