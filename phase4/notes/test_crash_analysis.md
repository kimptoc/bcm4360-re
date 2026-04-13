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

## Next Steps

1. **Level 3** — Full init: map BAR2 (TCM), halt ARM, download firmware,
   set up olmsg shared info, release ARM, poll fw_init_done
2. Investigate ARM wrapper IOCTL value 0x83828180 — may indicate window
   math issue (ARM_WRAP_BASE=0x18102000 crosses 4KB window boundary)
