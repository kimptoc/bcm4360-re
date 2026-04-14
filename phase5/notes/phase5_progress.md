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
- Added `BRCM_CC_4360_CHIP_ID` to `brcmf_chip_tcm_rambase()` → 0 (fixed from initial 0x180000)

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

## Test 2: After rambase=0 + iowrite32 fix (2026-04-14)

### Result: CRASH — NULL pointer in brcmf_chip_resetcore

```
BUG: kernel NULL pointer dereference, address: 0x0000000000000020
RIP: 0010:brcmf_chip_resetcore+0xa/0x20 [brcmfmac]
Call Trace:
  brcmf_pcie_setup.cold+0x61e/0xb9c [brcmfmac]
```

Firmware download completed successfully (no page fault or PCIe hang).
Crash in `brcmf_pcie_exit_download_state()`: calls
`brcmf_chip_get_core(BCMA_CORE_INTERNAL_MEM)` which returns NULL for BCM4360
(no INTERNAL_MEM core — that's a BCM43602 thing), then passes NULL to
`brcmf_chip_resetcore`.

## Fix 3: NULL-check INTERNAL_MEM core before resetcore

BCM4360 has ARM CR4 with TCM banks, not a separate SOCRAM/INTERNAL_MEM core.
Added NULL check: `if (core) brcmf_chip_resetcore(core, 0, 0, 0);`

## Test 3: After NULL check fix (2026-04-14)

### Result: SUCCESS — firmware downloaded, ARM released, no crash

```
brcmfmac 0000:03:00.0: BCM4360 debug: BAR0=0xb0600000 BAR2=0xb0400000 BAR2_size=0x200000 tcm=ffffd4a042800000
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3
brcmfmac 0000:03:00.0: BCM4360 debug: rambase=0x0 ramsize=0xa0000 srsize=0x0 fw_size=442233
brcmfmac 0000:03:00.0: brcmf_pcie_download_fw_nvram: FW failed to initialize
brcmfmac 0000:03:00.0: brcmf_pcie_setup: Dongle setup failed
ieee80211 phy2: brcmf_fw_crashed: Firmware has halted or crashed
```

Key results:
1. **No crash** — no page fault, no PCIe hang, no kernel oops
2. **Firmware downloaded** — 442KB written to TCM at offset 0 via iowrite32
3. **ARM released** — firmware started running
4. **Expected failure: "FW failed to initialize"** — msgbuf handshake timeout

The "FW failed to initialize" is the BCDC-vs-msgbuf protocol mismatch. The
firmware doesn't write back to the shared RAM address because it doesn't
speak the msgbuf protocol. This confirms the Phase 4 finding that BCM4360
firmware uses BCDC.

### What works now

- brcmfmac recognizes BCM4360 (14e4:43a0)
- BAR0/BAR2 mapping correct
- rambase=0, ramsize=0xa0000 (640KB) auto-detected correctly
- Firmware download via 32-bit iowrite32 (no PCIe hang)
- ARM release without host crash
- Module loads/unloads cleanly

## Phase 5.2: Firmware console debugging (tests 3-7)

### Tests 3-6: Incomplete captures

Tests 3-6 captured only the initial firmware load (rambase, ramsize, fw_size)
but no post-ARM-release output. These were intermediate iterations while adding
debug dumps and NVRAM logging to pcie.c.

### Test 7: Firmware ASSERT at hndarm.c:397

The most informative test. Added TCM debug dumps and firmware console extraction.

**Console output decoded:**
```
Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x824d pmurev 17, pmucaps 0x10a22b11
125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
140386.225 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
```

**Analysis:**
1. Firmware boots successfully — identifies BCM4360 chip, initializes ChipCommon
2. `si_kattach` (Silicon Interface kernel attach) completes — BCMA backplane init done
3. Firmware ASSERTs in `hndarm.c:397` ~14.5 seconds after first log (possibly a
   firmware watchdog or timeout)
4. The ASSERT happens during ARM initialization, likely related to:
   - Missing/incorrect NVRAM parameters
   - PCIe DMA/mailbox configuration the firmware expects but we haven't set up
   - A hardware configuration mismatch

**TCM scan results:**
- Shared memory marker at TCM end (0x9fffc) = 0xffc70038 — contains NVRAM footer data,
  not a pcie_shared address → firmware never wrote the msgbuf shared struct
- Console struct found at 0x96f70: buf_addr=0x4000, size=0 (unusual — size should be >0)
- Console text found at 0x96f78 by following `next` pointer at 0x9af94
- pcie_shared candidate at 0x9af90: flags=0xfa — this may be a pre-existing structure
  from firmware's data section, not a runtime-initialized shared memory area

### PC crash note

The last test (test 7 or a subsequent attempt) crashed the PC. This is likely due to
the firmware's ASSERT handler triggering a trap or the ARM entering an undefined state
that corrupts PCIe transactions. The 5-second timeout in `brcmf_pcie_download_fw_nvram`
may not be sufficient to safely handle the crash — the firmware may still be
writing to PCIe-visible memory during the timeout window.

### Uncommitted pcie.c changes

Added debug logging for:
- NVRAM load confirmation (len and TCM write address)
- Warning when no NVRAM is loaded
- Sharedram marker value before ARM release (to verify it's cleared to 0)

### Next steps

1. **Investigate hndarm.c:397 ASSERT** — likely a missing configuration or
   NVRAM parameter. The `ra` (return address) 0x000641cb and `fa` (frame address)
   0x0009cfe0 can be resolved against the firmware binary to identify the exact
   check that fails.
2. **NVRAM review** — ensure the NVRAM file has the right parameters for BCM4360.
   The firmware may require specific board-level settings.
3. **Reduce crash risk** — add a shorter timeout or disable bus mastering before
   ARM release to prevent firmware from corrupting host memory if it ASSERTs.
