# Test.248+ BCM4360-Host Work

Purpose: tasks that require the BCM4360-equipped machine because they
touch the chip over PCIe, depend on real attach behavior, or need live
probe/boot results.

## Scope rule

This file is for any step that requires one of:
- loading or unloading `brcmfmac.ko`
- BAR0/BAR2 MMIO reads or writes
- real firmware download / `set_active` / FORCEHT sequencing
- observing wedge timing, crash behavior, or SMC-reset recovery
- checking whether a code change actually changes BCM4360 behavior

Everything else belongs in `phase6/test248_other_work.md`.

## Track A: Test.248 wide-TCM follow-up on real hardware

Goal: answer the open question from POST-TEST.247 with the cheapest
possible discriminator before a full Phase-6 PMU/PLL pivot.

### A1. Refine the T248 design before coding

1. Reconcile the planned sample list in `phase6/test248_decision.md`
   with prior evidence in `RESUME_NOTES_HISTORY.md` and `pcie.c`.
2. Make upper TCM the priority region, because prior project history
   already recorded firmware-originated writes near `0x98000` and
   `0x9c000`.
3. Update the final sample set so it includes both `0x98000` and
   `0x9c000` at minimum.
4. Prefer one of these two layouts:
   - Minimal revision: keep the 16-point scan but replace weaker points
     with `0x9c000` and one extra upper-TCM point.
   - Better revision: do a compact two-snapshot scan across
     `0x90000..0xa0000`, since that region has the strongest prior
     evidence.
5. Keep the T247 struct continuity at `0x80000` unless there is a
   strong reason to remove it.

### A2. Implement the T248 instrumentation

1. Add module param `bcm4360_test248_wide_tcm_scan` in `pcie.c`.
2. Add a helper or macro that logs one baseline snapshot at the chosen
   pre-FORCEHT point.
3. Add a second snapshot at the `t+90000ms` dwell, matching the current
   reliable pre-wedge observation point.
4. Keep the logging format machine-diffable:
   - stage tag
   - address
   - value
   - or one fixed-order line that is easy to compare across snapshots
5. Avoid adding per-dwell scans unless the two-snapshot result is
   ambiguous.

### A3. Build and verify on the BCM host

1. Build the module on the BCM4360 host.
2. Confirm the new module param is present via `modinfo` or `strings`.
3. Confirm no unrelated compile regressions were introduced in
   `pcie.c`, `chip.c`, or nearby brcmfmac files.
4. Capture the exact build artifact used for the run.

### A4. Pre-run hardware checklist

1. Confirm PCIe state is clean before insertion.
2. Confirm no stale `brcmfmac`, `brcmutil`, or `cfg80211` state remains
   from the previous run.
3. Confirm whether an SMC reset was already performed after the prior
   crash, and record boot number / uptime.
4. Record the exact insmod arguments for the run.

### A5. Run Test.248

1. Load dependencies.
2. Insert the module with:
   - `bcm4360_test236_force_seed=1`
   - `bcm4360_test238_ultra_dwells=1`
   - `bcm4360_test239_poll_sharedram=1`
   - `bcm4360_test240_wide_poll=1`
   - `bcm4360_test247_preplace_shared=1`
   - `bcm4360_test248_wide_tcm_scan=1`
3. Let the dwell ladder reach `t+90000ms`.
4. Remove modules after the run if the host remains responsive.
5. If the host wedges, recover with the usual SMC-reset path and record
   whether it was required.

### A6. Interpret the T248 result

1. If all sampled offsets are unchanged:
   - classify as provisional `W1`
   - proceed to Test.249 signature/version sweep
   - do not jump directly to PMU/PLL implementation yet
2. If any new dead-region offsets changed:
   - classify as `W2`
   - plan a densified scan around the changed range
   - defer signature sweep unless the changed data still looks like a
     host-expected shared struct problem
3. If in-image offsets changed:
   - classify as `W3`
   - verify whether this is real firmware activity or an artifact of
     sampling / download state

## Track B: Test.249 signature/version sweep on real hardware

Goal: only if T248 is null, test whether the pre-placed shared struct
is semantically wrong rather than merely unread.

### B1. Finalize candidate signatures

1. Start with version values `5`, `6`, and `7`.
2. Add alternate magic/signature candidates only if the offline
   research in `test248_other_work.md` turns up a credible target.
3. Keep field count, base address, and logging identical across runs so
   version is the only changed variable.

### B2. Implement the sweep cleanly

1. Prefer a paramized value over copy-pasted one-off blocks.
2. Keep the existing T247 write/readback logging so each run proves the
   struct landed as intended.
3. Avoid mixing signature changes with unrelated probe additions.

### B3. Execute the sweep on the chip

1. Run one candidate per boot/recovery cycle unless a single load can
   safely cover multiple values without cross-contamination.
2. Record for each candidate:
   - struct readback
   - `ramsize-4` behavior
   - tail-TCM behavior
   - wedge timing
   - SMC-reset requirement

### B4. Decision after T249

1. If one version produces new TCM activity or changes the failure mode,
   pivot to decoding that path.
2. If all candidates null, Phase 6 PMU/resource-mask work becomes the
   primary path.

## Track C: Hardware validation for any future `pcie.c` changes

Goal: any off-machine `pcie.c` work must eventually be proven here.

### C1. Validation steps for offloaded code changes

1. Build the incoming branch or patch on the BCM host.
2. Verify the target code path is actually exercised in logs.
3. Run the smallest safe hardware test that can falsify the intended
   hypothesis.
4. Compare against the current known baseline:
   - wedge window
   - `ramsize-4`
   - tail-TCM
   - pre-placed struct behavior
   - any upper-TCM scan output

### C2. Candidates that still require chip validation

These may be authored elsewhere, but they cannot be accepted without
running on this host:
- `pcie.c` flow cleanup
- attach-time PCIe2 init changes
- PMU/PLL/resource-mask bring-up code
- shared-struct publication changes
- NVRAM delivery changes
- altered FORCEHT or `set_active` ordering

## Artifacts to capture after each chip-bound step

For every hardware-backed task, capture:
- exact code revision
- exact insmod command line
- journal excerpt or full log
- whether the host wedged
- whether SMC reset was required
- interpretation against the W1/W2/W3 or T249 matrix

