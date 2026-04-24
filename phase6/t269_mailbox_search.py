"""T269 steps 3-5: search blob for mailbox-register literals, our MAILBOXMASK
value, and host-ready / watchdog-related patterns.

Reasoning for literal search:
- Fw accesses HW registers via backplane addresses. The PCIe Gen2 core window
  on a BCM4360 backplane typically sits at 0x18003000-0x18007000. If the fw's
  ISR_STATUS register read is MMIO, it'll use one of these bases + offset 0x48
  (MAILBOXINT) or 0x4C (MAILBOXMASK). Scanning for nearby literals catches it.
- Our driver writes MAILBOXMASK = 0x00FF0300 and H2D_MAILBOX_1 = 1. If fw polls
  MAILBOXMASK itself to verify host-ready, literal 0x00FF0300 would appear.
- "Panic" / "reboot" strings in blob indicate fw watchdog handlers.
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


def find_lits(lo, hi):
    """Return (blob_offset, value) for any u32 in [lo, hi) found in blob."""
    hits = []
    for off in range(0, len(blob) - 4, 4):
        v = u32(off)
        if lo <= v < hi:
            hits.append((off, v))
    return hits


def find_lit_exact(val):
    p = val.to_bytes(4, "little")
    out = []
    pos = 0
    while True:
        h = blob.find(p, pos)
        if h < 0:
            break
        out.append(h)
        pos = h + 1
    return out


def find_strings(needle):
    pos = 0
    out = []
    while True:
        h = blob.find(needle, pos)
        if h < 0:
            break
        out.append(h)
        pos = h + 1
    return out


print("=== MMIO base literals: PCIe core window candidates ===")
# BCM4360 backplane: ChipCommon 0x18001000, PMU 0x18000000, PCIe Gen2 core ~ 0x18003000
# Scan for any 0x1800xxxx literal and cluster by base.
from collections import Counter
hits = find_lits(0x18000000, 0x1A000000)
print(f"{len(hits)} literals in 0x18000000-0x1A000000 range. Bases by top-16 bits:")
bases = Counter((h[1] & 0xFFFFF000) for h in hits)
for base, n in sorted(bases.items()):
    print(f"  0x{base:08X}: {n} occurrences")
print()

# Specific literals tied to our scaffold
print("=== Specific scaffold literals ===")
for label, val in [
    ("MAILBOXMASK value (our scaffold)", 0x00FF0300),
    ("MAILBOXMASK low bits FN0_only", 0x00000300),
    ("MAILBOXMASK d2h_db only", 0x00FF0000),
    ("MB_INT_FN0_0 bit", 0x00000100),
    ("MB_INT_FN0_1 bit", 0x00000200),
    ("H2D_MAILBOX_1 offset", 0x00000144),
    ("H2D_MAILBOX_0 offset", 0x00000140),
    ("MAILBOXINT offset", 0x00000048),
    ("MAILBOXMASK offset", 0x0000004C),
    ("BRCMF_H2D_HOST_D3_INFORM", 0x00000001),  # noisy but worth locating
    # Upstream bcmfmac: pcie.c:1016 #define BRCMF_PCIE_SHARED_HOSTRDY_DB1 0x10000000
    ("BRCMF_PCIE_SHARED_HOSTRDY_DB1 bit", 0x10000000),
]:
    hits = find_lit_exact(val)
    label_n = min(20, len(hits))
    print(f"  {label} (0x{val:08X}): {len(hits)} raw hits")
    for h in hits[:label_n]:
        ctx = ""
        if 0 <= h < len(blob) - 16:
            ctx = blob[max(0, h - 4):h + 8].hex(" ", 4)
        print(f"    @0x{h:06X}  ctx={ctx}")
print()

# Strings of interest
print("=== Strings related to ISR/handshake/watchdog ===")
for s in [
    b"pciedngl_isr",
    b"mailbox",
    b"MAILBOX",
    b"hostready",
    b"HostReady",
    b"D2H_DB",
    b"pending",
    b"intstatus",
    b"watchdog",
    b"panic",
    b"reboot",
    b"reset",
    b"invalid ISR",
    b"pciedngl_",
    b"pciedev",
    b"hnd_msg",
    b"_rte",
    b"sb_cc",
    b"ci_attach",
    b"doorbell",
    b"interrupt",
    b"IntStatus",
    b"D2H",
    b"H2D",
    b"dongle",
]:
    hits = find_strings(s)
    n = len(hits)
    if n == 0:
        continue
    print(f"  {s!r}: {n} hits")
    for h in hits[:5]:
        # show the surrounding null-terminated string
        start = h
        while start > 0 and blob[start - 1] != 0 and (blob[start - 1] >= 32 and blob[start - 1] < 127):
            start -= 1
        end = h
        while end < len(blob) and blob[end] != 0 and (blob[end] >= 32 and blob[end] < 127):
            end += 1
        try:
            label = blob[start:end].decode("ascii", "replace")
        except Exception:
            label = "<decode-err>"
        print(f"    @0x{h:06X}  <{label}>")
