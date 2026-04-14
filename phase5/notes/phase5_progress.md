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

### Fix: disable bus mastering before ARM release (uncommitted until now)

Added `pci_clear_master()` before ARM release and `pci_set_master()` after FW
wait completes. This prevents the firmware's ASSERT handler from DMA-ing to host
memory and crashing the PC. Also removed the H2D doorbell hack (was speculative,
didn't help).

## Phase 5.2: Crash investigation (tests 8-11)

### Tests 8-10: All crashed PC
- test.8: PMU logging + ForceHT → **crashed PC** (no log)
- test.9: same as test.8 (commit 3d96dbc) → **crashed PC** (no log)
- test.10: skip watchdog entirely (commit 72235c4) → **crashed PC** (no log)

**Key conclusion:** Crash is NOT caused by watchdog reset — happens regardless.
The PMU/ForceHT register writes added in test.8 are the likely crash trigger.

### Test 11: Safe baseline revert (commit a3dbbb3)
Reverted to test.7 code: read-only PMU, bus mastering disabled, no PMU writes,
no ASPM disable. **Crashed PC.** Journal (recovered from `journalctl -b -1`)
shows all output up to ARM release, then system died abruptly. Log saved to
`phase5/logs/test.11`.

**Critical finding:** Test.7 previously ran without crashing, but the identical
code (test.11) now crashes. This rules out host-side code as the crash cause.
Something environmental changed — possibly PCIe link state, thermal, or
accumulated hardware state from repeated ARM releases across reboots.

### Tests 12a-12b: PCIe safety measures (commits 81afaf3, ba216a1)
- test.12a: skip_arm=1, FW download only → **PASS** (no crash, confirms download is safe)
- test.12b: AER/SERR masking before ARM release → **crashed PC**

### Test 13: Early IRQ handler + INTx disable (commit d1181a8)
- Registered IRQ handler BEFORE ARM release, disabled INTx at PCI config level
- **Crashed PC** — IRQ handler never fired, crash is pre-interrupt

### Test 14: Strip all PCIe safety, bus mastering ON (commit 60574c6)
- Hypothesis: bus mastering disable was the crash cause (added after test.7)
- Stripped ALL PCIe modifications, released ARM with bus_master=ON (EFI default)
- PCI_COMMAND=0x0006 (memory space + bus master enabled)
- **Crashed PC** — log saved to `phase5/logs/test.14`
- Last message: "releasing ARM as-is" then instant death

**Critical conclusion:** Bus mastering hypothesis is WRONG. Tests 11-14 all crash
regardless of PCIe safety measures, bus mastering state, IRQ handlers, or AER masking.
The crash is immediate upon ARM release. Something changed between test.7 (which
worked) and all subsequent tests.

### Crash pattern summary (tests 8-14)

| Test | Bus Master | PCIe Safety | IRQ Handler | Result |
|------|-----------|-------------|-------------|--------|
| 7    | disabled  | none        | none        | **PASS** |
| 8-10 | disabled  | various     | none        | CRASH |
| 11   | disabled  | none (=test.7) | none     | CRASH |
| 12a  | N/A       | skip_arm=1  | none        | PASS  |
| 12b  | disabled  | AER/SERR    | none        | CRASH |
| 13   | disabled  | INTx disable| early IRQ   | CRASH |
| 14   | **ON**    | **none**    | none        | CRASH |

**Every ARM release since test.7 crashes the PC.** The only safe operation is
firmware download without ARM release (test.12a).

### Working hypotheses for crash

1. **Hardware state accumulation:** Repeated ARM releases across reboots may have
   left the BCM4360 in a state that EFI doesn't fully reset. Test.7 worked because
   it was the first ARM release after a cold boot / extended power-off.

2. **Firmware DMA on boot:** The firmware immediately initiates DMA upon ARM release,
   targeting host memory addresses that aren't mapped. With bus mastering ON (test.14),
   this corrupts host memory. With bus mastering OFF (tests 8-13), the PCIe root
   complex rejects the DMA and generates a fatal error.

3. **Missing interrupt/DMA infrastructure:** The firmware expects MSI/MSI-X vectors
   and DMA ring buffers to be configured BEFORE ARM release. Without them, the
   firmware's first PCIe transaction causes a fatal bus error.

## Phase 5.2: Narrowing the crash (tests 15-20)

### Tests 15-18: Hypotheses disproved

| Test | Hypothesis | Mitigation | Result |
|------|-----------|------------|--------|
| 15   | ForceHT needed before ARM | ForceHT set | CRASH |
| 16   | Warm-up needed | Read-only warm-up first | CRASH |
| 16   | PCIe cold/warm state | Cold boot comparison | CRASH |
| 17   | MSI needed before ARM | MSI + IRQ handler | CRASH |
| 18   | Rogue DMA | IOMMU protection | CRASH |

### Test 19: CPUHALT isolation (commit 1ccf441)

**Key finding:** Used CPUHALT bit (0x20) in ARM CR4 IOCTL to keep ARM halted
even after reset-clear. ARM never executed firmware, yet **PC still crashed**.

**Critical conclusion:** The crash is caused by the `brcmf_chip_resetcore()`
register write sequence itself, NOT by ARM firmware execution. The act of
clearing the ARM's reset state (writing to RESET_CTL and IOCTL registers)
triggers a PCIe bus error that kills the host.

### Test 20: Staged reset (commits c6bfdc4, a92a15c)

Broke `brcmf_chip_resetcore()` into individual register writes to find exactly
which one crashes:

- **Stage 0** (read-only ARM CR4 register dump): **PASS** -- reads are safe
  - IOCTL, IOST, RESET_CTL values captured (pre-reset state)
- **Stage 1** (write IOCTL = FGC|CLK = 0x0003): **CRASH**
  - Log shows module loaded, then instant PC death
  - The very first register WRITE to the ARM CR4 core wrapper crashes the host

### Root cause identified

**Writing to the ARM CR4 core wrapper's IOCTL register (offset 0x408) crashes
the PCIe bus.** This is the first step of `brcmf_chip_resetcore()` -- it writes
FGC|CLK to configure the core before clearing reset. Reading the same register
is perfectly safe (stage 0).

This means the BCM4360's ARM CR4 core wrapper registers are NOT writable via
the standard BCMA core wrapper mechanism that works for 43602 and other chips.
The BCM4360 may require:
1. A different core selection/access method
2. Indirect register access via ChipCommon or PMU
3. A specific backplane configuration before core wrapper writes are allowed
4. The reset sequence from the macOS `wl` driver may use a completely different
   register access path

### Updated crash pattern summary (tests 7-20)

| Test | What happened | Result |
|------|---------------|--------|
| 7    | Full ARM release (first time) | **PASS** |
| 8-14 | Various ARM release approaches | CRASH |
| 12a  | FW download only, no ARM | PASS |
| 15-18| Various pre-ARM mitigations | CRASH |
| 19   | CPUHALT (ARM never runs) | CRASH |
| 20.0 | Read ARM CR4 registers | PASS |
| 20.1 | Write IOCTL = FGC\|CLK | **CRASH** |

### Next steps

1. **Examine how `brcmf_pcie_select_core()` works** -- verify the core selection
   is correct for BCM4360 and that the register window is properly mapped
2. **Check what test.7 did differently** -- was it using `brcmf_chip_set_active()`
   which goes through the chip.c abstraction layer? The staged test bypasses
   that and does direct register writes
3. **Trace the macOS wl driver's reset sequence** -- use Phase 3/4 MMIO traces
   to see exactly how the proprietary driver resets the ARM core
4. **Try indirect core access** -- use ChipCommon backplane access registers
   instead of direct core wrapper writes
5. **Power-cycle test** -- full AC power removal to ensure clean hardware state
