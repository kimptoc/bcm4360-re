# Phase 4B — Test Module Crash Analysis

**Date:** 2026-04-12

## Summary

Testing the `bcm4360_test.ko` module has revealed multiple issues:

1. **Original module (full probe):** Instant hard lockup — PCIe bus hang on load
2. **pci_reset_function():** Hangs indefinitely — BCM4360 doesn't support FLR
3. **Step-gated module (step 0, BAR0 only):** Loads OK, but BAR0 reads return
   `0xFFFFFFFF` (device not responding). Machine crashes ~1 minute after unload.

The `0xFFFFFFFF` return indicates the chip is in PCI D3 power state after `wl`
unloads — all MMIO reads return all-ones. The delayed crash after module unload
suggests the chip enters an unstable PCIe link state.

## Timeline

| Boot | Time | Event | Result |
|---|---|---|---|
| (a94bec1) | 21:17–23:09 | Module built, sudo blocked | No test |
| (9eecf9e) | 23:09–23:18 | First test attempt | Crash (no evidence of load) |
| (349490a) | 23:19–23:27 | `test.sh 0` (original module) | Instant crash |
| (788e34a) | 23:27–23:44 | Rebuilt with step gates, pci_reset_function | pci_reset_function hangs, module stuck |
| (352bbb3d) | 23:45–23:48 | `test.sh 0` (step-gated, BAR0 only) | Step 0 OK, reads 0xFFFFFFFF, crash ~1min later |
| current | 23:49– | Investigating | — |

## Test Results

### Test 1 (boot 349490a): Original module, step 0

**Command:** `sudo test.sh 0`
**Result:** Instant hard lockup. No kernel messages from module.
**Cause:** Module mapped BAR2 (2MB) at probe time + `pci_reset_function` + BAR reads
all happening when chip was in D3/unstable state after `wl` unload.

### Test 2 (boot 788e34a): Step-gated with pci_reset_function

**Command:** `sudo test.sh 0`
**Result:** Module hung in `pci_reset_function()` — never returned.
**Cause:** BCM4360 doesn't support PCI Function Level Reset (FLR).
**Fix:** Removed `pci_reset_function()`.

### Test 3 (boot 352bbb3d): Step-gated, BAR0 only, no FLR

**Command:** `sudo test.sh 0`
**Result:** Module loaded and completed step 0 successfully:
```
bcm4360_test 0000:03:00.0: BCM4360 test module probe
bcm4360_test 0000:03:00.0: Bus mastering disabled
bcm4360_test 0000:03:00.0: BAR0 mapped at ffffcb87c1080000 (32KB)
bcm4360_test 0000:03:00.0: === BCM4360 test: max_step=0 ===
bcm4360_test 0000:03:00.0: [step 0] Reading chip ID via BAR0...
bcm4360_test 0000:03:00.0: [step 0] BAR0[0x00] = 0xffffffff (expect 0x43a0 in low 16 bits)
bcm4360_test 0000:03:00.0: [step 0] DONE — BAR0 MMIO OK
bcm4360_test 0000:03:00.0: Test complete, result: 0
```

**Key finding:** `0xFFFFFFFF` = device in D3 power state or PCIe link down.
The `pci_set_power_state(PCI_D0)` code was in the source but its log message
didn't appear — possibly the old .ko was loaded (from before rebuild) or the
D0 transition itself was ineffective.

**Post-test crash:** System crashed ~1 minute after module unload. No kernel
panic/oops logged — suggests PCIe link entered an irrecoverable state.

## Root Cause Analysis

### Why 0xFFFFFFFF?

The `wl` driver puts the BCM4360 into PCI D3 (deep sleep) during `rmmod`. In D3:
- All BAR MMIO reads return `0xFFFFFFFF`
- The PCIe link may be in L2/L3 low-power state
- `pci_enable_device()` alone doesn't wake the device

To properly wake the device we need:
1. `pci_set_power_state(pdev, PCI_D0)` — transition from D3→D0
2. `pci_restore_state(pdev)` — restore PCI config saved by wl
3. Possibly: BCMA backplane init to wake internal cores

### Why delayed crash?

After our module unloads (`pci_disable_device`), the chip may be in a half-awake
state — PCI D0 but with no driver managing it. The PCIe link may degrade over
time (ASPM, power management) until the link fails, causing a bus error that
locks up the host.

### Why did the original module cause instant crash?

The original module mapped BAR2 (2MB TCM) at probe time. If `pci_iomap` or the
kernel's page table setup triggers a speculative read of the 2MB region while
the device is in D3, the PCIe endpoint can't respond, causing an immediate
bus timeout → machine check → lockup.

BAR0 (32KB) mapping was safe because either:
- Smaller mapping = less likely to trigger speculative access
- BAR0 may respond even in partial D3 (config space is always accessible)

## Fixes Applied

| Fix | Status | Effect |
|---|---|---|
| BAR2 deferred to step 1 | ✅ Applied | No more instant crash at probe |
| BAR2 size reduced to 640KB | ✅ Applied | Avoids unpopulated regions |
| pci_reset_function | ❌ Removed | Hangs — BCM4360 lacks FLR support |
| pci_clear_master at probe | ✅ Applied | Stops any DMA from wl |
| 5s sleep after wl unload | ✅ Applied | Hardware quiesce time |
| pci_set_power_state(D0) | ✅ Added | Not yet confirmed working |

## Next Steps

1. **Confirm D0 wake works** — Rebuild and verify "Power state set to D0" appears
   in dmesg, then check if BAR0 reads return chip ID instead of 0xFFFFFFFF
2. **If still 0xFFFFFFFF:** Try `pci_save_state`/`pci_restore_state`, or
   manually write PCI power management config space register
3. **If chip wakes up:** Proceed to step 1 (map BAR2 + halt ARM)
4. **Blacklist wl as fallback:** If wl's D3 transition is the problem,
   test with wl never loaded (add `module_blacklist=wl` to kernel cmdline)
