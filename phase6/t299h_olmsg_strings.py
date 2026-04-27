"""T299h (advisor priority): scan for bcm_olmsg_* and other offload-mode
function name strings.

Per Phase 4A: BCM4360 is SoftMAC NIC + offload engine. The FullMAC
wl_open → wlc_up → wlc_bmac_up_finish chain may be dead code. The actual
bring-up runs through bcm_olmsg_* parallel paths.

If bcm_olmsg_* names exist + are referenced by code, the wake-arm path
is via those, not via the wlc_bmac_up_finish chain.
"""
import sys, struct
sys.path.insert(0, "/home/kimptoc/bcm4360-re/phase6")
from t269_disasm import Cs, CS_ARCH_ARM, CS_MODE_THUMB

with open("/lib/firmware/brcm/brcmfmac4360-pcie.bin", "rb") as f:
    data = f.read()
md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)


def iter_all():
    pos = 0
    while pos < len(data) - 2:
        emitted_any = False
        last_end = pos
        for ins in md.disasm(data[pos:], pos):
            yield ins
            emitted_any = True
            last_end = ins.address + ins.size
            if last_end >= len(data) - 2:
                return
        pos = last_end if emitted_any else pos + 2


print("Disasm pass…")
all_ins = list(iter_all())
print(f"Total: {len(all_ins):,}\n")


# Search for ALL bcm_olmsg_* and related offload-mode names
NAME_PATTERNS = [
    b"bcm_olmsg",
    b"olmsg_",
    b"bcm_ol_",
    b"BCM_OL_",
    b"wlc_ol_",
    b"olmac",
    b"offload",
    b"OL_UP",
    b"ol_up",
    b"OL_DOWN",
    b"ol_attach",
    b"ol_init",
    b"ol_handler",
    b"pciedngl_",
    b"pcidongle_",
    b"bmac_up",
    b"writemsg",
    b"readmsg",
]


print("=== String search for offload-mode names ===")
all_found_strings = []
for needle in NAME_PATTERNS:
    pos = 0
    while True:
        idx = data.find(needle, pos)
        if idx < 0: break
        # Find full string (until null)
        end = idx
        while end < len(data) and 32 <= data[end] < 127:
            end += 1
        if end - idx >= len(needle):
            full_str = data[idx:end].decode("ascii", errors="replace")
            all_found_strings.append((idx, full_str))
        pos = idx + 1

# Dedupe and sort
seen = set()
for off, s in sorted(all_found_strings):
    if (off, s) in seen: continue
    seen.add((off, s))
    print(f"  {off:#x}: \"{s}\"")


# For each string, find ldr-pc-rel code refs that load its address
print("\n\n=== Code refs (PC-rel ldr) that load each string's address ===")
for off, s in sorted(set([(o, str_) for o, str_ in all_found_strings])):
    refs = []
    for ins in all_ins:
        if not ins.mnemonic.startswith("ldr") or "[pc," not in ins.op_str: continue
        try:
            imm_s = ins.op_str.split("#")[-1].rstrip("]").strip()
            imm = -int(imm_s[1:], 16) if imm_s.startswith("-") else int(imm_s, 16)
            la = ((ins.address + 4) & ~3) + imm
            if 0 <= la <= len(data) - 4:
                val = struct.unpack_from('<I', data, la)[0]
                if val == off:
                    refs.append(ins.address)
        except: pass
    if refs:
        print(f"  \"{s}\" @ {off:#x}: {len(refs)} ref(s) at " + ", ".join(hex(r) for r in refs[:6]))
