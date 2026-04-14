# Phase 5: brcmfmac BCM4360 Support

## Approach

Patch the upstream `brcmfmac` kernel driver to add BCM4360 (PCI ID 14e4:43a0)
support. The firmware is PCI-CDC FullMAC (identified in Phase 4), which is
exactly what brcmfmac expects.

## Discovery: brcmfmac never supported BCM4360

No `BRCM_CC_4360_CHIP_ID`, `BRCM_PCIE_4360_DEVICE_ID`, or firmware mapping
existed in the kernel. The BCM4360 fell in a gap — too new for b43/brcmsmac
(SoftMAC drivers), never added to brcmfmac's PCI table. Only `bcma` claimed
the PCI ID, acting as a bus driver without a wireless driver on top.

The kernel module alias table confirms: `pci:v000014E4d000043A0` → `bcma` only.

## Patches applied (3 files)

### brcm_hw_ids.h
- Added `BRCM_CC_4360_CHIP_ID` (0x4360)
- Added `BRCM_PCIE_4360_DEVICE_ID` (0x43a0)

### pcie.c
- Added `BRCMF_FW_DEF(4360, "brcmfmac4360-pcie")`
- Added `BRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360)`
- Added `BRCMF_PCIE_DEVICE(BRCM_PCIE_4360_DEVICE_ID, WCC)`
- Added BCM4360 to enter/exit download state handlers (same as 43602 — ARM CR4)

### chip.c
- Added `BRCM_CC_4360_CHIP_ID` to `brcmf_chip_tcm_rambase()` → 0x180000

## Test 1: Module load and probe (2026-04-14)

### Result: PARTIAL SUCCESS — firmware loaded, crash in setup

```
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3
brcmfmac 0000:03:00.0: Direct firmware load for brcm/brcmfmac4360-pcie.Apple Inc.-MacBookPro11,1.bin failed with error -2
```

Key observations:
1. **brcmfmac recognized BCM4360** — chip ID 0x4360, rev 3
2. **Firmware loaded successfully** — used `brcmfmac4360-pcie.bin`
3. Platform-specific firmware (`Apple Inc.-MacBookPro11,1.bin`) not found (expected)
4. CLM blob and txcap blob not found (non-fatal)

### Crash in brcmf_pcie_setup

```
BUG: unable to handle page fault for address: ffffd3f8c141fffc
Oops: 0002 [#1] PREEMPT SMP PTI
RIP: 0010:iowrite32+0x10/0x40
Call Trace:
  brcmf_pcie_setup+0x1d2/0xda0 [brcmfmac]
  brcmf_fw_request_done+0x148/0x190 [brcmfmac]
```

The crash is a page fault during `iowrite32` in `brcmf_pcie_setup`. The driver
is writing to TCM (likely the NVRAM placement at end of RAM) but the target
address is outside the mapped region.

RAX=0x180000 (RAM base), faulting address is an ioremap'd address that's past
the end of the BAR2 mapping.

### Analysis

The `brcmf_pcie_setup` function writes NVRAM to `rambase + ramsize - nvram_len`.
If `brcmf_chip_tcm_ramsize()` returns an incorrect value (due to CR4 capability
register reads returning bad data on the flaky PCIe link), the write offset
could be past the end of the mapped BAR.

Alternatively, BCM4360's TCM layout may differ from 43602 — the RAM base is
correct (0x180000) but the BAR2 mapping size may not cover the full TCM range.

### Next steps

1. ~~Add debug prints to capture ramsize, rambase, and BAR2 mapping range~~ ✅ done
2. ~~Compare with Phase 4 findings~~ ✅ rambase fixed to 0
3. ~~May need to add BCM4360-specific ramsize override if auto-detection fails~~ — TBD

## Fix 1: rambase=0 (commit d872ae2)

Phase 4 proved BAR2 maps TCM directly at offset 0 (no 0x180000 offset).
Changed `brcmf_chip_tcm_rambase()` for `BRCM_CC_4360_CHIP_ID` to return 0.

## Fix 2: Replace memcpy_toio with 32-bit iowrite32 writes

Phase 3/4 proved BCM4360 hangs on 64-bit `rep movsq` (which x86 `memcpy_toio`
uses). Added `brcmf_pcie_copy_mem_todev()` helper in `pcie.c` — a 32-bit
`iowrite32` loop with trailing-byte handling.

Replaced all `memcpy_toio` calls in the firmware download path:
- Firmware data write (fw->data, ~442KB)
- NVRAM write
- Random seed footer write
- Random bytes write

One `memcpy_toio` remains in the msgbuf ring setup path (line ~1334) — this
won't be reached until after ARM release, and will likely fail anyway since
BCM4360 firmware speaks BCDC not msgbuf.

### Expected test result

Firmware download should complete without page fault or PCIe hang. After ARM
release, the msgbuf handshake will timeout (BCM4360 FW speaks BCDC). That
timeout is expected and non-fatal — it proves the firmware loaded correctly.
