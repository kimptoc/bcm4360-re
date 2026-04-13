# Phase 4B — Test Module Crash Analysis

**Date:** 2026-04-12 – 2026-04-13

## Summary

Testing the `bcm4360_test.ko` module through progressive level-gating has
identified and resolved the root cause of BAR0 read failures and machine crashes.

**Root cause: Stale AER (Advanced Error Reporting) errors left by the `wl` driver
prevent PCIe MMIO completion, causing 0xFFFFFFFF reads and machine lockups.**

**Fix: Clear AER error status registers and enable bus mastering before MMIO access.**

## Key Findings

### AER errors were the blocker (discovered 2026-04-13)

After `wl` unloads, the device has stale PCIe errors recorded:
- **Uncorrectable: 0x00008000** — bit 15 = Unsupported Request Error
- **Correctable: 0x00002000** — bit 13 = Advisory Non-Fatal Error

These are W1C (write-1-to-clear) registers at the AER extended capability.
Clearing them before MMIO access allows BAR0 reads to succeed.

### Device state after `wl` unload

- Power state: **D0** (not D3 as initially assumed)
- PMCSR: 0x4008
- Memory space: enabled (CMD bit 1 = 1)
- Bus mastering: disabled (CMD bit 2 = 0)
- BAR0_WIN: 0x18001000 (ChipCommon + 0x1000, left by wl)
- PCIe link: Gen1 x1 (speed=1, width=1)
- BAR0: phys=0xb0600000, len=0x8000 (32KB)
- BAR2: phys=0xb0400000, len=0x200000 (2MB)

### Chip identity (from BAR0 ChipCommon register)

- **Chip ID: 0x4360** (silicon ID, distinct from PCI device ID 0x43a0)
- **Revision: 3**
- **Package: 0**
- ChipCommon caps: 0x58680001
- ChipCommon status: 0x1810a000

### What doesn't work

- `pci_reset_function()` — hangs indefinitely (BCM4360 lacks FLR support)
- `pci_disable_device()` in remove — causes delayed PCIe bus lockup (~1-2 min)
- MMIO reads without clearing AER — returns 0xFFFFFFFF, may crash machine

## Timeline

| Test | Time | Level | Result |
|---|---|---|---|
| test.1 | Apr 12 23:47 | step 0 (old module) | BAR0=0xFFFFFFFF |
| test.2 | Apr 12 23:54 | step 0 (journal) | BAR0=0xFFFFFFFF |
| test.3 | Apr 13 00:14 | level 0 | PASS (bind only) |
| test.4 | Apr 13 00:14 | level 1 | PASS (config space, D0 confirmed) |
| test.5 | Apr 13 00:14 | level 2 | FAIL — BAR0=0xFFFFFFFF, no crash |
| test.6 | Apr 13 11:12 | level 1 | PASS (old module, no BAR0_WIN diag) |
| test.7 | Apr 13 11:16 | level 1 | PASS — BAR0_WIN diag, AER errors found |
| test.8 | Apr 13 11:20 | level 1 | PASS — AER cleared, bus master enabled |
| test.9 | Apr 13 11:21 | level 2 | **PASS — BAR0 MMIO works! Chip ID=0x4360 Rev=3** |

## Fixes Applied

| Fix | Status | Effect |
|---|---|---|
| BAR2 deferred to level 3 | ✅ Applied | No instant crash at probe |
| BAR2 size reduced to 640KB | ✅ Applied | Avoids unpopulated regions |
| pci_reset_function | ❌ Removed | Hangs — BCM4360 lacks FLR |
| pci_clear_master at probe | ✅ Applied | Stops residual DMA from wl |
| pci_disable_device in remove | ❌ Removed | Caused delayed crash |
| AER error clearing | ✅ Applied | **Key fix — enables MMIO** |
| Bus mastering enable | ✅ Applied | Required for DMA in level 3 |
| BAR0_WIN set to ChipCommon | ✅ Applied | Ensures known window state |

## Level 2 Successful Output (test.9)

```
[level 2] BAR0 mapped at ffffd3ef80560000 (32KB)
[level 2] AER pre-read: uncorr=0x00000000 corr=0x00000000
[level 2] BAR0_WIN register = 0x18000000
[level 2] About to do first MMIO read (BAR0+0x00)...
[level 2] BAR0[0x00] (current window) = 0x15034360
[level 2] Chip ID=0x4360 Rev=3 Pkg=0
[level 2] ChipCommon caps = 0x58680001
[level 2] ChipCommon status = 0x1810a000
[level 2] ARM wrapper IOCTL = 0x83828180 (via BAR0 window)
[level 2] PASS
```

## Level 3 Crash Analysis (2026-04-13)

### Symptom

Running `sudo ./test.sh 3` (or auto-advance reaching level 3) causes a **hard
machine lockup** — no kernel panic, no dmesg, empty log files (test.10–13 are
0 bytes). Requires physical power cycle to recover.

Level 2 passes consistently.

### Root cause: bulk TCM write overwhelming PCIe Gen1 x1 link

Level 3 writes ~640KB of firmware to BAR2 (TCM) via MMIO `iowrite32` in a tight
loop. The link is **PCIe Gen1 x1** (~250 MB/s theoretical), and write-posting
buffers can overflow when the readback pacing is too coarse.

The original pacing was a readback every **256 DWORDs (1KB)** — too infrequent
for this link speed. When the PCIe write buffer overflows:

1. An **Unsupported Request (UR)** or **Completion Timeout** fires
2. This triggers a fatal AER error
3. On this platform, fatal AER errors lock the PCIe bus → hard lockup

### Evidence

- PCIe link degraded: `speed=1 width=1` (Gen1 x1) in all test logs
- AER errors were already present before level 3 in earlier runs:
  `uncorr=0x00008000` (bit 15 = UR), `corr=0x00002000` (bit 13 = Advisory NF)
- Level 2 works because it only does a few scattered register reads
- Level 3 does ~160,000 consecutive `iowrite32` calls — qualitatively different

### Crash timeline

| Test | Level | Result |
|---|---|---|
| test.10 | 3 (auto) | **CRASH** — 0 bytes, hard lockup |
| test.11 | 3 (auto) | **CRASH** — 0 bytes, hard lockup |
| test.12 | 3 | **CRASH** — 0 bytes, hard lockup |
| test.13 | 3 | **CRASH** — 0 bytes, hard lockup |

### Fixes applied

| Fix | Description |
|---|---|
| Tighter write pacing | Readback every 64 DWORDs (256 bytes) instead of 256 (1KB) |
| udelay between chunks | 10μs pause after each paced readback to let link drain |
| Mid-transfer death check | If readback returns 0xFFFFFFFF, abort immediately |
| AER check before bulk write | Clear and verify AER errors after BAR2 map, before FW download |

## Level 3 — continued crash analysis (2026-04-13, post-pacing fix)

### Status

Level 3 still crashes the machine with **0 bytes in dmesg** (test.10–13), even
after applying the pacing fixes from the previous commit. The pacing fixes
(readback every 64 DWORDs + 10μs udelay) were confirmed compiled and loaded,
but had no effect — all four attempts produced identical hard lockups.

### Key observation: crash may not be the bulk write

The fact that 0 bytes of level 3 output appear in dmesg suggests the crash
happens very early — possibly before even the first `dev_info` can flush.
Possible crash points, in order:

1. **`pci_iomap(BAR2)`** — mapping 640KB of BAR2 after level 2 unload/reload
2. **First TCM read** — `tcm_read32(dev, 0)` via BAR2 MMIO
3. **`arm_halt()`** — `bp_write32` to ARM wrapper (0x18102000+offset) uses
   BAR0 window; rapid config space + MMIO writes may overwhelm Gen1 x1 link
4. **Bulk TCM write loop** — the previously suspected cause, but if (1)–(3)
   crash first, the pacing fix is irrelevant

### Diagnostic: pr_emerg canary printks

Added 6 `pr_emerg` canary messages with `mdelay(100)` pauses at each critical
point in `level3_tcm_and_fw()`:

| Canary | Location | If this is last seen... |
|---|---|---|
| CANARY 1 | Before `pci_iomap(BAR2)` | BAR2 mapping crashes |
| CANARY 2 | After BAR2 map, before first TCM read | TCM read crashes |
| CANARY 3 | After AER clear, before `arm_halt()` | ARM halt crashes |
| CANARY 4 | After `arm_halt()` returns | Post-halt bp_read32 verification crashes |
| CANARY 5 | Before bulk TCM write loop | Bulk write crashes (original theory) |
| CANARY 6 | After bulk write completes | Crash is in verify/shared_info reads |

`pr_emerg` is the highest kernel log priority and most likely to appear on the
physical console even during a hard lockup. Check VT or serial console — dmesg
log capture may not work if the crash is too fast.

## Canary test result (2026-04-13)

### Result: CANARY 5 was the last message on screen

Ran `sudo ./test.sh 3` with canary-instrumented module. Physical console showed
CANARY 5 ("starting bulk TCM write") but NOT CANARY 6 ("bulk write complete").

**This confirms the crash is inside the bulk TCM write loop** (lines 653–668 of
`bcm4360_test.c`). The BAR2 mapping, initial TCM reads, AER clearing, and
`arm_halt()` all succeed — the machine locks up during the sustained `iowrite32`
burst to TCM.

### Current pacing (insufficient)

- Readback flush every 64 DWORDs (256 bytes)
- 10μs `udelay` after each flush
- Still overflows the Gen1 x1 link write buffers

### Diagnosis

The 64-DWORD chunk size is still too large for the Gen1 x1 link. At ~250 MB/s
theoretical bandwidth with write-posting, 256 bytes of back-to-back MMIO writes
can still fill the PCIe write buffer before the read-back completes. The 10μs
delay is also too short to allow the link to fully drain.

### Fix: tighter pacing + progress canaries

1. **Reduce chunk size**: flush every 16 DWORDs (64 bytes) instead of 64 (256 bytes)
2. **Increase drain delay**: 50μs instead of 10μs
3. **Add progress canaries**: `pr_emerg` every 1024 DWORDs so the next crash
   (if any) reveals exactly how far the write got before dying

## Next Steps

1. Build and test with tighter pacing (16 DWORDs + 50μs)
2. If still crashing, check progress canaries for how far it gets
3. If crash is near the start — may need single-word pacing or `wmb()` barriers
4. If crash is near the end — may be a specific TCM address region issue
