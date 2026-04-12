# Phase 4B — Test Module Crash Analysis

**Date:** 2026-04-12

## Summary

The `bcm4360_test.ko` module causes an instant hard lockup (PCIe bus hang) when
loaded, even at `max_step=0` (BAR mapping + register read only). The crash is so
severe that no kernel messages are logged — the journal shows only the `sudo` entry
for the test script, then the machine reboots.

## Timeline

| Boot | Time | Event |
|---|---|---|
| -3 (a94bec1) | 21:17–23:09 | Previous session, module built but sudo blocked by password |
| -2 (9eecf9e) | 23:09–23:18 | First test attempt — crash (no journal evidence of module load) |
| -1 (349490a) | 23:19–23:27 | `sudo test.sh 0` confirmed in journal — instant crash |
| 0 (788e34a) | 23:27–now | Current boot |

## Key Evidence

### Boot -1 journal (the confirmed crash)

```
23:19:13  kernel: eth0: Broadcom BCM43a0 802.11 Hybrid Wireless Controller 6.30.223.271 (r587334)
23:19:14  kernel: wl 0000:03:00.0 wlp3s0: renamed from eth0
...normal operation...
23:27:20  sudo: kimptoc : TTY=pts/1 ; COMMAND=/home/kimptoc/bcm4360-re/phase4/work/test.sh 0
[boot ends — instant crash]
```

No kernel messages from the test module appear. The crash happens during or
immediately after `insmod bcm4360_test.ko max_step=0`.

### What step 0 does

```c
pci_enable_device(pdev);          // Enable PCI device
dma_set_mask_and_coherent(32bit); // Set DMA mask
pci_iomap(pdev, 0, 0x8000);      // Map BAR0 (32KB registers)
pci_iomap(pdev, 2, 0x200000);    // Map BAR2 (2MB TCM)
dma_alloc_coherent(64KB);         // Allocate olmsg buffer
ioread32(dev->regs);              // Read BAR0[0] — chip ID
ioread32(dev->tcm);               // Read TCM[0]
```

## Analysis

### Hypothesis 1: wl driver leaves hardware in unstable state

The `wl` driver initializes the BCM4360 fully at boot (loads D11 ucode, calibrates
PHY, sets up DMA, starts radio). When `rmmod wl` runs, the driver's cleanup may
leave the chip in a partially-active state where:

- D11 core is still running ucode
- DMA engines are still active
- ARM CR4 may be running (wl loads the offload firmware)
- Interrupts may be pending/unmasked

Our module then calls `pci_enable_device()` which may re-enable something that
immediately causes a PCIe bus error (e.g., unmasking interrupts with no handler,
or the device asserting an error because its state is inconsistent).

### Hypothesis 2: pci_iomap of BAR2 causes bus hang

Phase 3 discovered that BAR2 TCM access has restrictions:
- Only 32-bit `iowrite32`/`ioread32` works — `memcpy_toio` (64-bit) hangs the bus
- B-bank (BANKIDX 4) access hangs the bus
- The 2MB BAR2 window has only 640KB populated

If `pci_iomap(pdev, 2, 0x200000)` causes any prefetch or speculative read of the
unmapped region, it could hang the PCIe bus.

### Hypothesis 3: Race with wl unload

If `rmmod wl` hasn't fully completed when `insmod bcm4360_test` starts (e.g., the
PCI device is in the middle of being released), the new probe could race with
teardown and access hardware in an inconsistent state.

## Recommended Fixes to Try

### Fix A: Don't map BAR2 at probe time

Map only BAR0 first. Read chip ID. Only map BAR2 later if BAR0 reads succeed.
This tests whether BAR0 alone is safe.

### Fix B: Add sleep between wl unload and module load

In `test.sh`, add `sleep 5` after `rmmod wl` to ensure full hardware quiesce.

### Fix C: Reset the PCI device before probe

Use `pci_reset_function()` or write to PCI config space to reset the endpoint
before enabling it. This would clear any state left by `wl`.

### Fix D: Map BAR2 with smaller size

Map only the populated 640KB instead of full 2MB to avoid accessing dead regions.

### Fix E: Disable device before re-enabling

Call `pci_disable_device()` then `pci_enable_device()` to force a clean state,
or use `pci_save_state()`/`pci_restore_state()`.

## Next Steps

1. Try Fix B first (cheapest — just a sleep in the script)
2. Try Fix A (map BAR0 only, skip BAR2 entirely)
3. Try Fix C (PCI reset before enable)
4. If all fail, consider testing without wl ever loading (blacklist wl module)
