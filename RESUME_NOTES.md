# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-19, PRE test.127 stage0 — add early probe markers)

### CODE STATE: EARLY PROBE MARKERS ADDED FOR BCM4360

**test.126 stage0 result — crash with PCIE2 mailbox clear skipped:**

Test log (`phase5/logs/test.126.stage0`) cuts off during insmod, before any markers printed.
Unlike test.125 which printed buscore_reset entry, test.126 didn't print ANY test markers.

**Analysis:**
- test.125: crashed at PCIE2 mailbox write (got to buscore_reset)
- test.126: skipped PCIE2 mailbox write, but still crashed before buscore_reset
  
**Hypothesis:**
Crash is happening BEFORE buscore_reset, likely:
1. In brcmf_chip_attach (called before buscore_reset)
2. Or even earlier in probe before chip_attach (in SBR, devinfo allocation, etc.)

The test.126.stage0 log cuts off during "Loading brcmfmac ..." with no marker output.
This suggests either:
- Probe is never called (module load error)
- Probe crashes very early (before first dev_emerg statement at line 3871)

**Code changes for test.127 (pcie.c):**
Add pr_emerg markers at:
1. Very start of brcmf_pcie_probe (after device ID check) — `test.127: probe entry`
2. After devinfo kzalloc — `test.127: devinfo allocated`
3. After devinfo->pdev assign — `test.127: devinfo->pdev assigned, before SBR`
4. Keep test.126: early return to skip PCIE2 mailbox clear

**Hypothesis (test.127 stage0):**
test.126 crashed during insmod before ANY test markers printed. Crash is likely:
- In probe before first dev_emerg (line 3871 with SBR logging)
- Or possibly in module load/device binding before probe is even called

test.127 adds pr_emerg (printk) markers at the very start of probe to determine
if probe is called and how far we get. Expected result: markers will show exactly
where the crash occurs (likely at a kzalloc, pci_match_id, or pci_save_state call
that's racing with hardware still in recovery).

**Run:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Success criteria:**
- No crash
- Log contains test.127 probe entry marker (proves probe is called)
- Log shows all three test.127 markers (entry, devinfo allocated, devinfo->pdev assigned)
- If all three markers printed: crash is in SBR code, next test will isolate that

**Failure signatures:**
- No test.127 markers: probe not called or crashes before first pr_emerg
- Markers stop at specific point: identifies exact crash boundary

---

## TEST.127 EXECUTION — 2026-04-19 (session 2, after crash recovery)

**PRE-TEST STATE (verified):**
- test.126 crashed during insmod before any markers printed
- test.127 code compiled at 00:07 (pcie.c markers added, brcmfmac.ko built)
- Module built: Apr 19 00:07
- PCIe state verified clean: MAbort-, CommClk+
- test-staged-reset.sh updated with test.127 labels
- Hardware ready to test

**PLAN:**
Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0` to execute test.127 stage0.

**HYPOTHESIS:**
test.126 crashed during insmod before ANY markers were printed. Crash occurs before `buscore_reset`.
test.127 adds pr_emerg markers at:
1. Probe entry (after device match)
2. After devinfo kzalloc
3. After pdev assignment

If these markers print, we know probe is being called and can identify exactly where the crash occurs.
If no markers print, crash is either in module initialization or in probe before first statement.

**EXPECTED OUTCOMES:**
- All 3 markers print → crash is in SBR code or after pdev assignment (next test: isolate SBR)
- Markers stop at marker 2 → crash in `pdev = pdev->bus->self` or nearby assignment
- Stops at marker 1 or no markers → crash in very early probe or module-level code

**SUCCESS CRITERIA:**
- Hardware survives insmod without hard crash
- At least marker 1 (probe entry) is visible in dmesg
- Log clearly identifies the crash boundary

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-19, POST test.126 stage0 crash — PCIE2 mailbox skipped, still crashed)

### CODE STATE: PCIE2 MAILBOX CLEAR BYPASSED FOR BCM4360

**test.125 stage0 result — crash at PCIE2 mailbox write:**

Journal markers from boot -1:
- `test.125: buscore_reset entry, ci assigned`
- `test.122: reset_device bypassed`
- `test.125: after reset_device return`
- `test.125: PCIE2 core found rev=1`
- `test.125: before PCIE2 reg read (reg=0x48)`
- `test.125: after PCIE2 reg read val=0x00000000`
- **NO** `test.125: before PCIE2 reg write` — crash occurred at/after the write

**Interpretation:**
PCIE2 mailbox read (reg=0x48) succeeded and returned 0x00000000 (mailbox already clear).
The write back to that register (`brcmf_pcie_write_reg32(devinfo, reg, val)`) crashed the machine —
MCE/completion timeout from writing to the PCIE2 core before it is ready.

Since val=0x00000000 (mailbox was already clear), the write is both unnecessary and lethal for BCM4360.

**Code changes for test.126 (pcie.c):**
- In `brcmf_pcie_buscore_reset`: after the reset_device bypass marker, add an early return for BCM4360
  before the PCIE2 core lookup and mailbox clear. Log `test.126: skipping PCIE2 mailbox clear; returning 0`.
- All other bypasses remain: reset_device body, RAM info fixed, module-params dummy, OTP bypass.
- Test script updated to log `test.126.stage0`.

**Hypothesis (test.126 stage0):**
- buscore_reset returns 0 cleanly for BCM4360.
- chip_attach continues: `after reset, before get_raminfo` (chip.c marker), then `get_raminfo returning 0`.
- `brcmf_chip_attach returned successfully` (test.119 marker).
- Probe continues past chip_attach. Next crash point unknown; may be in OTP or probe setup.
- If chip_attach marker is reached and crash happens later, we will continue narrowing.

**PCIe state (post-crash):** MAbort-, CommClk+, LnkSta 2.5GT/s x1 — clean.
**Build:** clean, only expected `brcmf_pcie_write_ram32` unused warning.

---

## Previous state (2026-04-18, POST test.125 stage0 crash — PCIE2 mailbox write)

### HARDWARE STATUS: STAGE0 CRASHED DURING CHIP_ATTACH, BEFORE RETURN

### HARDWARE STATUS: STAGE0 CRASHED DURING CHIP_ATTACH, BEFORE RETURN

`test.124.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.124.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~8ms) and proceeded.
- Root port bus numbering was sane (`secondary=03, subordinate=03`).
- Script reached `insmod`, then host crashed before `insmod returned`.

**Kernel journal markers (boot -1):**
- SBR worked; BAR0 probe `0x15034360 — alive`.
- `test.122: reset_device bypassed` ← LAST MARKER
- **No test.121** (post-reset passive skipped)
- **No test.119** (chip_attach returned)
- **No test.120/123/124** markers after that.

**Interpretation:**
Crash occurs after `reset_device` returns but before `brcmf_chip_attach` returns. This is within `brcmf_pcie_buscore_reset` (after reset call) or the subsequent `brcmf_chip_get_raminfo` call. `test.123` (identical code through this point) succeeded and reached "before OTP read". The regression indicates hardware state variance between runs, not code change.

**Candidate failure point:** `brcmf_pcie_buscore_reset`'s first post-reset MMIO:
```c
val = brcmf_pcie_read_reg32(devinfo, reg);  // PCIE2 mailbox read
```
This is the first BAR0 access after reset. If the device is not yet ready, a completion timeout → MCE could occur.

**Next code change (test.125):**
Add boundary markers to pinpoint crash site:
- In `brcmf_pcie_buscore_reset`: log at entry, after setting `devinfo->ci`, after `reset_device` returns, before PCIE2 reg read, after read, before write, after write.
- In `brcmf_chip_attach` (chip.c): log immediately after `ci->ops->reset` returns, before `brcmf_chip_get_raminfo` call, and before return.
- Keep all existing bypasses (reset_device body, RAM info, module-params dummy, OTP bypass).
- Keep `bcm4360_skip_arm=1`; stage1 forbidden.

**Hypothesis:** If crash is in PCIE2 mailbox MMIO, we'll see markers up to "after reset_device" but not "before PCIE2 reg read". In that case, we may need to skip that PCIE2 access for BCM4360 or delay until link stabilizes.

**Build:** clean via kernel build tree.

**Pre-run:** Force runtime PM on for bridge (00:1c.2) and endpoint (03:00.0), verify root port bus numbering.

---

## Previous state (2026-04-18, POST test.121 stage0 crash — early reset_device)

### HARDWARE STATUS: STAGE0 CRASHED INSIDE RESET_DEVICE BEFORE PCIE2 MARKER

`test.121.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.121.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Root port bus numbering was sane before test (`secondary=03, subordinate=03`).
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- Last persisted BCM4360 marker: `test.118: reset_device entering minimal reset path`.
- No `test.118: PCIE2 selected, ASPM disabled` marker persisted.
- No `test.121` fixed-RAM marker persisted.

**Post-crash hardware state:**
- PCI config still responds: BCM4360 `14e4:43a0`, COMMAND=0x0006.
- Root port bus numbering is sane after forcing runtime PM `on`.
- BAR0 direct read still fails fast (~7ms), not a slow completion timeout.

**Interpretation:**
- `test.121` did not test the fixed-RAM path; it crashed earlier.
- The crash boundary is now inside `brcmf_pcie_reset_device()` after the entry marker and before the PCIE2-selected marker.
- The suspect operation is the first reset-device PCIE2 core select and/or immediate ASPM config read/write.
- Probe-start SBR already reset the endpoint and made BAR0 alive, so the in-driver reset-device body is now a liability for BCM4360.

**Next code change:**
- Add `test.122`: for BCM4360, return early from `brcmf_pcie_reset_device()` after SBR/chip attach setup, skipping PCIE2 core select, ASPM toggles, watchdog, and PCIE2 config replay.
- Keep `test.121` fixed RAM info in place.
- Keep `bcm4360_skip_arm=1`; stage1 remains forbidden.

---

## Previous state (2026-04-18, PRE test.121 stage0 — fixed BCM4360 RAM info)

### CODE STATE: BCM4360 RAM-SIZING MMIO BYPASSED

`test.120` crashed after the post-reset passive skip and before any post-chip-attach probe setup markers. The next likely unsafe path is RAM sizing after reset.

**Code changes for test.121:**
- `brcmf_chip_get_raminfo()` now special-cases BCM4360 and uses the known RAM map directly:
  `rambase=0`, `ramsize=0xa0000`, `srsize=0`.
- This bypass applies to both the chip-recognition call and the later firmware-callback call.
- The post-reset passive skip marker was updated to `test.121`.
- Staged script now writes `phase5/logs/test.121.stage0`.

**Hypothesis (test.121 stage0):**
- If RAM-sizing MMIO caused the crash, journal should show:
  `test.121: post-reset passive skipped; using fixed RAM info next`,
  `test.121: using fixed RAM info ...`,
  `test.119: brcmf_chip_attach returned successfully`,
  and then the existing `test.120` post-chip-attach setup markers.
- If it still crashes before the fixed-RAM marker, the fault is asynchronous immediately after `reset_device`.
- If it reaches firmware download, keep `bcm4360_skip_arm=1` and stop at the safe no-ARM path; stage1 remains forbidden.

**Pre-run requirement:** force runtime PM `on` for `00:1c.2` and `03:00.0` if either is suspended, then verify root port bus is `secondary=03, subordinate=03`.

**Build:** clean via kernel build tree. Only note: BTF skipped because `vmlinux` is unavailable.

---

## Previous state (2026-04-18, POST test.120 stage0 crash — before RAM-info marker)

### HARDWARE STATUS: STAGE0 CRASHED IMMEDIATELY AFTER POST-RESET PASSIVE SKIP

`test.120.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.120.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Root port bus numbering was sane before test (`secondary=03, subordinate=03`).
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- `test.118: reset_device complete`.
- Last persisted BCM4360 marker: `test.119: skipping post-reset passive call`.
- No `test.119: entering raminfo after reset` marker persisted.
- No `test.120` post-chip-attach probe setup markers persisted.

**Interpretation:**
- `test.120` did not reach the post-chip-attach probe setup path.
- Compared with `test.119`, the crash boundary moved back into the tiny region after the post-reset passive skip and before/inside RAM-info handling.
- The remaining likely unsafe operation is `brcmf_chip_get_raminfo()`, which performs fresh core MMIO reads to size memory after reset.
- Earlier firmware-download work already established the BCM4360 RAM map: `rambase=0`, `ramsize=0xa0000`, `srsize=0`.

**Next code change:**
- Add `test.121`: for BCM4360, skip `brcmf_chip_get_raminfo()` during chip recognition and use the known RAM map directly.
- Keep `bcm4360_skip_arm=1`; stage1 remains forbidden.
- Continue to force runtime PM `on` before any future insmod if root port/endpoint are suspended.

---

## Previous state (2026-04-18, PRE test.120 stage0 — instrument post-chip-attach probe setup)

### CODE STATE: POST-CHIP-ATTACH PROBE SETUP MARKERS ADDED

`test.119` proved `brcmf_chip_attach()` returns successfully. Crash is now later in `brcmf_pcie_probe()` before firmware request/download.

**Code changes for test.120:**
- Added markers around PCIE2 core lookup/reginfo selection.
- Added markers around `pcie_bus_dev`, `bus`, and `msgbuf` allocation.
- Added marker after bus wiring / `dev_set_drvdata`.
- Added markers before/after `brcmf_alloc`.
- Added markers before/after OTP read.
- Added markers before/after firmware request preparation and firmware async request.
- Staged script now writes `phase5/logs/test.120.stage0`.

**Hypothesis (test.120 stage0):**
- If probe setup is safe, markers should reach `before brcmf_fw_get_firmwares` or `brcmf_fw_get_firmwares returned async/success`, then firmware request path should start.
- If a specific non-MMIO setup step unexpectedly crashes, the last marker identifies it.
- If firmware request starts but later crashes before callback, the boundary has moved into firmware loading/callback setup.

**Pre-run requirement:** force runtime PM `on` for `00:1c.2` and `03:00.0` if either is suspended, then verify root port bus is `secondary=03, subordinate=03`.

**Build:** clean via kernel build tree. Only warning: existing unused `brcmf_pcie_write_ram32`.

---

## Previous state (2026-04-18, POST test.119 stage0 crash — after chip_attach returns)

### HARDWARE STATUS: STAGE0 CRASHED AFTER CHIP_ATTACH RETURNED

`test.119.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.119.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~8ms) and proceeded.
- Root port bus numbering was sane before test after forcing runtime PM `on`.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- `test.118: reset_device complete`.
- `test.119: skipping post-reset passive call`.
- `test.119: entering raminfo after reset`.
- `test.119: brcmf_chip_attach returned successfully`.
- No later brcmfmac/BCM4360 markers persisted.

**Interpretation:**
- Skipping the second post-reset passive call worked.
- RAM info completed and `brcmf_chip_attach()` returned.
- Crash is now in the next part of `brcmf_pcie_probe()`, before firmware request/download and still before ARM release.
- Next suspect block: PCIE2 core lookup/reginfo setup, allocations, module params, `brcmf_alloc()`, OTP check, or firmware request preparation.

**Next code change:**
- Add `test.120` markers through the post-chip_attach probe setup path:
  PCIE2 core lookup/reginfo, `pcie_bus_dev` allocation, module params, bus/msgbuf allocation, `dev_set_drvdata`, `brcmf_alloc`, OTP, firmware request, and `brcmf_fw_get_firmwares`.
- No behavior change yet; just narrow the next crash boundary.
- Continue to force runtime PM `on` before any future insmod if root port/endpoint are suspended.

---

## Previous state (2026-04-18, PRE test.119 stage0 — skip post-reset passive)

### CODE STATE: POST-RESET PASSIVE CALL SKIPPED FOR BCM4360

`test.118` proved `brcmf_pcie_reset_device()` now completes. The next suspected operation is the second `brcmf_chip_set_passive()` in `brcmf_chip_recognition()` immediately after `ci->ops->reset()`.

**Code changes for test.119:**
- In `chip.c`, BCM4360 skips the post-reset passive call after `ops->reset`.
- Added marker before RAM info: `BCM4360 test.119: entering raminfo after reset`.
- Added marker after `brcmf_chip_attach()` returns in `pcie.c`.
- Staged script now writes `phase5/logs/test.119.stage0`.

**Hypothesis (test.119 stage0):**
- If post-reset passive caused the crash, journal should show `entering raminfo after reset`, `brcmf_chip_attach returned successfully`, then continue into firmware request/download.
- If RAM info probing is unsafe after skipping passive, the last marker will be `entering raminfo after reset`.
- If later probe setup is unsafe, the last marker will be `brcmf_chip_attach returned successfully`.
- ARM remains skipped; stage1 is still forbidden.

**Build:** clean via kernel build tree. Only warning: existing unused `brcmf_pcie_write_ram32`.

**Do not run until platform PCIe state is recovered:** after the test.118 crash, root port 00:1c.2 showed invalid bus numbering (`secondary=ff, subordinate=fe`). Reboot or full power-cycle before the next insmod; then verify root port bus is `secondary=03, subordinate=03` and BAR0 guard is fast UR/OK.

---

## Previous state (2026-04-18, POST test.118 stage0 crash — after reset_device complete)

### HARDWARE STATUS: STAGE0 CRASHED AFTER MINIMAL RESET_DEVICE COMPLETED

`test.118.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.118.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~5ms) and proceeded.
- Endpoint COMMAND was already `0x0000`; BARs disabled before test.
- Root port had `MAbort+` before test.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked: `test.53: SBR complete`
- BAR0 came alive after SBR: `test.53: BAR0 probe ... = 0x15034360 — alive`
- `test.118: reset_device entering minimal reset path`
- `test.118: PCIE2 selected, ASPM disabled`
- `test.118: ChipCommon watchdog skipped`
- `test.118: ASPM restored, entering PCIE2 cfg replay`
- `test.118: reset_device complete`
- No later brcmfmac/BCM4360 markers persisted.

**Current post-crash checks:**
- PCI config space still responds: BCM4360 `14e4:43a0`
- Endpoint COMMAND is `0x0000`; BARs disabled
- Root port config is damaged: bus shows `primary=00, secondary=ff, subordinate=fe`
- BAR0 userspace read still fails quickly (~7ms), not a slow CTO

**Interpretation:**
- The old reset-time diagnostics were not the final crash source.
- The minimal `brcmf_pcie_reset_device()` path now completes.
- The next code executed inside `brcmf_chip_recognition()` is the second `brcmf_chip_set_passive(&ci->pub)` immediately after `ci->ops->reset(...)`.
- Suspect: the second passive pass touches or disables a core that is unsafe after BCM4360 SBR/reset_device, causing the hard crash before `brcmf_chip_attach()` returns.

**Next code change before any more hardware tests:**
- Add `test.119` markers in `chip.c` around the post-reset passive step.
- For BCM4360, skip the second `brcmf_chip_set_passive()` after `ops->reset` and proceed to RAM info, because the initial passive call already ran before reset and the bus reset path completed.
- Add a `test.119` marker after `brcmf_chip_attach()` returns in `pcie.c` so the next test distinguishes chip-attach completion from later probe/setup work.
- Do not run stage1.

---

## Previous state (2026-04-18, PRE test.118 stage0 — minimal reset_device path)

### CODE STATE: OLD RESET-TIME DIAGNOSTICS REMOVED/GATED

`brcmf_pcie_reset_device()` has been simplified for BCM4360:
- Removed completed `test.111` core-list diagnostic from the reset path.
- Removed `test.112` ChipCommon FORCEHT write/poll from the reset path.
- Removed `test.114a` D11 wrapper read from the reset path.
- BCM4360 no longer selects ChipCommon solely to skip the watchdog write.
- New `test.118` markers bracket the remaining path: enter reset, PCIE2/ASPM, watchdog skipped, ASPM restore, PCIE2 cfg replay, reset complete.

**Hypothesis (test.118 stage0):**
- Pre-test BAR0 guard should see fast UR or normal MMIO and allow the run.
- SBR should restore BAR0; `test.53` should report `0x15034360 — alive`.
- The new `test.118` reset markers should reach `reset_device complete`.
- Firmware download should run and the `bcm4360_skip_arm=1` branch should return cleanly without ARM release.
- Module unload should complete.

**Run after build/commit/push:**
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

**Build:** clean via kernel build tree:
`make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
Only warning: existing unused `brcmf_pcie_write_ram32`.

---

## Previous state (2026-04-18, POST test.117 stage0 crash — reset_device diagnostic crash)

### HARDWARE STATUS: STAGE0 CRASHED; CURRENT BAR0 FAST I/O ERROR, ROOT PORT MAbort+

`test.117.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.117.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked: `test.53: SBR complete`
- BAR0 came alive after SBR: `test.53: BAR0 probe ... = 0x15034360 — alive`
- chip_attach completed far enough to enter `brcmf_pcie_reset_device`
- reset_device printed EFI/PMU/pllcontrol baseline
- last persisted BCM4360 line: `test.111: id=0x827 PMU NOT PRESENT`
- no `test.111` lines after PMU and no `test.112` / `test.114a` markers persisted

**Current post-crash checks:**
- PCI config space still responds: BCM4360 `14e4:43a0`
- Endpoint COMMAND is now `0x0000`; BARs are disabled
- Root port secondary status has `MAbort+`
- BAR0 userspace read still fails quickly (~8ms), not a slow CTO

**Interpretation:**
- The battery-drain recovery worked enough for probe-time SBR to restore BAR0 and for chip_attach to run.
- The crash is now inside or immediately after the old reset-time diagnostic area, not in ARM release and not in firmware execution.
- `test.111` had already served its purpose; keeping the core-list diagnostic and older `test.112` / `test.114a` probes in every reset path is now counterproductive.

**Next code change before any more hardware tests:**
- Remove or gate off the completed reset_device diagnostics (`test.111`, `test.112`, and `test.114a`) for BCM4360.
- Keep only the minimal production-relevant reset behavior: SBR before chip_attach, skip ChipCommon watchdog for BCM4360, ASPM handling if still needed, and the BAR0 guard.
- Add a new stage0 marker immediately before standard reset code and another immediately after reset_device returns, so the next test isolates whether standard reset still crashes once old diagnostics are removed.
- Do not run stage1 until a clean stage0 completes and the module unloads.

---

## Previous state (2026-04-18, PRE test.117 stage0 — battery-drain recovery, BAR0 UR)

### HARDWARE STATUS: CONFIG/LINK RECOVERED; BAR0 MMIO FAST I/O ERROR (UR), NOT CTO

Battery-drain recovery completed. Post-boot checks:
- PCI config space responds: BCM4360 `14e4:43a0`, COMMAND=0x0006.
- Root port 00:1c.2 is clean: no MAbort, link up, CommClk+.
- Userspace BAR0 read returns I/O error quickly (~6ms), not a slow Completion Timeout.
- Interpretation: adapter is in the recoverable UR/alive state; probe-time SBR should reset it before chip_attach.

**Harness fix before test:**
- `phase5/work/test-staged-reset.sh` now has the BAR0 timing guard from `test-brcmfmac.sh`.
- Stage0 uses `bcm4360_skip_arm=1`; ARM must not be released in this first recovery test.

**Hypothesis (test.117 stage0):**
- Pre-test BAR0 guard reports UR/I/O error under 40ms and allows the run.
- Probe-time SBR restores BAR0 MMIO; `test.53` BAR0 probe reports `0x15034360 — alive`.
- chip_attach completes, reset_device reaches `test.114c.1` through `.5`, watchdog is skipped for BCM4360, firmware download completes, skip_arm branch aborts cleanly, and module unload succeeds.

**Run:**
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-18, POST test.114d crash — BAR0 MMIO dead, power cycle needed)

### HARDWARE STATUS: BAR0 MMIO DEAD — config space accessible, MMIO I/O error

**POST test.114d result (2026-04-18):**
- Last marker printed: test.53 "BAR0 probe = 0x15034360 — alive"
- No test.114c.X markers printed — crash during chip_attach MMIO (before brcmf_pcie_reset_device)
- BAR0 MMIO now dead (dd resource0 → I/O error). Config space accessible (COMMAND=0x0006)
- Log saved: phase5/logs/test.114d.stage0

**Root cause analysis:**
- test.114c's watchdog write (`WRITECC32(watchdog, 4)`) crashed the PCIe link → MCE → reboot
- Machine rebooted but NOT a power cycle (battery keeps VAUX alive)
- BCM4360 was left in partial watchdog-reset state: ChipCommon accessible, other BCMA cores broken
- test.114d: SBR at probe start ran, BAR0 probe @ ChipCommon = 0x15034360 (alive), but
  chip_attach scans ALL BCMA core wrappers via MMIO → hit broken core → CTO → MCE → crash
- SBR is insufficient to recover from a watchdog-mid-reset state. Full power cycle required.

**HARDWARE STATUS: POWER CYCLE REQUIRED (battery drain)**

**Next steps after power cycle:**
1. Module already built with test.114d changes (watchdog skip for BCM4360, marker 3a)
2. No rebuild needed after power cycle — just run test
3. Run `sudo ./test-brcmfmac.sh` (stage0, skip_arm=1)
4. Expect: test.114c.1 through test.114c.5 all print, no crash (watchdog skipped for BCM4360)
5. If stage0 clean: run stage1 (skip_arm=0) for BBPLL + ARM release test

**Hypothesis (test.114d after power cycle):**
- With fresh power-on reset state, chip_attach MMIO will succeed (all cores accessible)
- Markers .3, .3a, .4, .5 all print (ASPM disabled, CC selected, watchdog SKIPPED, PCIE2 reselected)
- Stage0 completes without crash

---

## Previous state (2026-04-18, POST recovery crash — brcmf_pcie_reset_device watchdog crash)

### HARDWARE STATUS: BCM4360 MMIO UR (alive, recoverable) — SBR should fix for next test

**Test run (2026-04-18, ~10:43):** After battery-drain recovery, device was alive. Ran test
with SBR-in-probe + BAR0 abort guard. Device got further than ever (chip_attach succeeded,
core enumeration complete) but crashed silently after test.114a log line.

**Observations vs hypothesis:**
- BAR0 probe AFTER SBR = 0x15034360 — ALIVE. SBR worked correctly.
- BAR0 abort guard did NOT fire (correct — BAR0 was alive, guard only fires on 0xffffffff).
  User framing "guard should have fired" was mistaken — guard worked as designed.
- HT TIMEOUT at test.112: FORCEHT written, 100×100µs poll, clk_ctl_st=0x00050042, never got HAVEHT.
- test.114a: d11 wrap_RESET_CTL=0x00000000 IN_RESET=NO wrap_IOCTL=0x00000001
  UNEXPECTED: set_passive should leave d11 IN reset. IN_RESET=NO means d11 already out of reset
  before our test.114a ran (either SBR didn't reset BCMA state, or set_passive didn't coredisable).
- Crash: silent MCE-level, after test.114a log, NO further kernel output.
- Current MMIO: I/O error in ~0.5ms (UR = fast, Unsupported Request). Device alive, SBR will fix.

**Crash location: somewhere in brcmf_pcie_reset_device after test.114a block (lines 895–932).**
Candidates (in order executed after test.114a):
  - L895: select_core(CHIPCOMMON) — BAR0 write, right after test.114a log
  - L901: select_core(PCIE2) — BAR0 write
  - L909: select_core(CHIPCOMMON) — BAR0 write
  - L910: WRITECC32(watchdog, 4) — resets chip in ~200ns
  - L914: select_core(PCIE2) — first BAR0 write after watchdog fires
  - L918+: more MMIO if PCIE2 rev <= 13
Best guess: watchdog=4 kills PCIe link, then L914 select_core(PCIE2) fires → CTO → MCE.
NOT CONFIRMED — bisection markers added to next build.

**Log saved:** phase5/logs/test_20260418_watchdog_crash.log

**Next test hypothesis:** Markers will tell us the exact crash site. Last marker printed = instruction before crash.

**Next steps:**
1. Build: `make -C /home/kimptoc/bcm4360-re/phase5/work` (bisection markers added to pcie.c)
2. Run test script — look for last test.114c.N marker in dmesg
3. If last marker is test.114c.3 (pre-watchdog): watchdog write itself crashes → skip watchdog for BCM4360
4. If last marker is test.114c.4 (post-watchdog-sleep): link didn't recover in 100ms → extend sleep
5. If last marker is test.114c.1 or .2: crash is at CC or PCIE2 select_core BEFORE watchdog

---

## Previous state (2026-04-17, POST test.116 stage0 crash x2 — MMIO DEAD, DRAINING BATTERY FOR RECOVERY)

### HARDWARE STATUS (RESOLVED): BCM4360 MMIO NON-RESPONSIVE — POWER CYCLE REQUIRED

**Diagnosis (2026-04-17, post-second-crash):** BCM4360 BAR0 MMIO is completely non-responsive.
Confirmed via direct userspace probe:
- `setpci -s 03:00.0 COMMAND` = 0x0006: config space IS accessible (device visible)
- `dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1` → **I/O error**: MMIO DEAD
- This was reproduced across: manual SBR via setpci, kernel device reset (`echo 1 > reset`),
  device remove+rescan. Nothing recovers MMIO.
- `FLReset-` in DevCap: BCM4360 has no Function Level Reset capability.

**Root cause confirmed:** The test.114 stage1 firmware execution (ARM release + ~400ms hang wait)
left the BCM4360's PCIe endpoint or BCMA AXI fabric in a state that soft reset cannot clear.
A system reboot does NOT cut PCIe slot power (VAUX stays on). Only a full hardware power cycle
(complete shutdown, wait, power on) will clear this state.

**"Reboot fixes it" hypothesis was WRONG.** test.116 stage0 was run TWICE after full reboots;
both times it crashed hard (no kernel output, MCE-level crash). Userspace now confirms the
device itself is not responding to MMIO at all — the crashes were always Completion Timeout → MCE.

**Next step: FULL POWER CYCLE — MacBook-specific recovery procedure**

This machine is a pre-2018 MacBook with non-removable battery. Standard shutdown does NOT
cut PCIe slot power (VAUX stays on via battery). Attempted recovery methods, in order tried:

1. `shutdown -h now` + wait — FAILED (battery keeps VAUX alive)
2. Unplug mains — IRRELEVANT (laptop on battery anyway)
3. SMC reset (Shift+Ctrl+Option+Power, 10s) — FAILED (state too deep in BCM4360 hardware)
4. Boot macOS to let Apple kext reinitialize card — NOT POSSIBLE (no macOS partition)

**Only remaining option: drain battery to 0%**
Run `stress-ng --cpu 0 --vm 2 --vm-bytes 80%` with no charger until machine shuts off from
empty battery. Wait 2-3 minutes. Plug in charger. Power on. Test MMIO.

After recovery, verify BEFORE any test:
`dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd`
Must return 4 bytes (no I/O error). If still dead → something is wrong at the PCIe root port level.

### What to do after power cycle

After power cycle, before ANY test:

1. **Verify MMIO works:** `dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd`
   Should return 4 bytes (any value, not I/O error). If I/O error → power cycle again.

2. **Module NOT built.** Run: `make -C /home/kimptoc/bcm4360-re/phase5/work`
   (no .ko file survived the crash)

3. **Run test.116 stage0.** With MMIO restored, the d11 guard should finally be testable.
   Hypothesis: BAR0 probe returns alive, d11 IN_RESET=YES (no wl driver), guard skips 0x1e0
   read, stage0 completes cleanly.

4. **Only after stage0 clean:** run stage1 with skip_arm=0.
   CRITICAL FOR STAGE1: After ARM is released and test completes, do NOT leave module loaded
   long-term. Unload promptly to avoid another firmware-induced MMIO corruption.

### Prevention for future stage1 tests — CRITICAL on MacBook

**On this MacBook, MMIO corruption = hours of recovery time** (battery drain is the only fix).
The cost of another stage1 crash is very high. Before running stage1 again:

1. **Understand why stage0 crashes at BAR0 probe** — the d11 guard was never reached because
   both test.116 runs crashed in `brcmf_pcie_get_resource` (BAR0 ioread32) before reset_device.
   This suggests the MMIO was already dead BEFORE insmod — the pre-test MMIO check is mandatory.

2. **Add userspace MMIO check to test script** — script should abort if resource0 returns I/O
   error before attempting insmod.

3. **After any stage1 ARM release:** rmmod within the observation window. Do NOT leave loaded.
   If stage1 crashes: expect battery-drain recovery required before next run.

4. **Consider a SBR in the test script** before insmod (1000ms wait) to clear CommClk- state.

### Test.116 stage0 crash analysis (both crashes)

test.116 stage0 crashed TWICE. Both crashes produced NO kernel output (hard MCE-level crash).
The SBR in `brcmf_pcie_probe` may or may not have logged "SBR complete" — the dmesg capture
only runs if insmod returns, but both runs had insmod hard-crash the machine. The userspace
MMIO test confirms the crash was at `ioread32(devinfo->regs)` in brcmf_pcie_get_resource
(test.53 BAR0 probe) — PCIe Completion Timeout → MCE. With `pci=noaer` in boot params and
`FatalErr+` on root port, there is NO soft error recovery for this path.

**The d11 guard was never reached.** Both test.116 crashes happened in get_resource (prepare
callback), before reset_device (reset callback) where the guard lives.

**Module status:** pcie.c has d11 guard. Module NOT built (.ko was cleared by crash).
Rebuild required: `make -C /home/kimptoc/bcm4360-re/phase5/work`

**MAbort+ on root port secondary status is BASELINE** (present since test.100).

### Analysis of test.114 stage1 + test.115 crash (completed 2026-04-17)

**test.114 stage1 key results:**
- d11 wrap_RESET_CTL=0x00000000 IN_RESET=NO (d11 was already out of BCMA reset)
- test.47 BBPLL bringup succeeded: pmustatus=0x0000002e, clk_ctl_st=0x01030040 HAVEHT=YES
- test.107 T+200ms: d11.clk_ctl_st=0x070b0042 — this means:
  - Bit 19 (BP_ON_HT) = 0x070b0042 & 0x00080000 = 0x00080000 ≠ 0 → **BP_ON_HT=YES**
  - Bit 17 (HAVEHT) = YES, Bit 1 (FORCEHT) = YES
  - **CORRECTION:** earlier pice.c comment claimed BP_ON_HT=0 — this was wrong
- FW wrote FORCEHT and BP_ON_HT was granted → fn 0x1415c (the d11 clock poll) likely EXITED
- Anchor F at T+200ms: [0x9CF6C]=0x00068c49 (exp 0x68b95) MISMATCH
  - Frame pointer shifted — hang has MOVED downstream to ~FW address 0x68c49
- Counter still at 0x43b1 at T+400ms → FW blocked in si_attach nested call (different site)

**test.115 stage0 crash:**
- PCIe state showed CommClk-, MAbort+ (bad state left by test.114 stage1 ARM release)
- Crashed during insmod (hard crash, no kernel logs)
- Machine has since rebooted; PCIe state should be clean now

**pcie.c changes made (this session):**
- test.114b comment: corrected BP_ON_HT analysis (was wrong; BP_ON_HT IS set in test.114 stage1)
- test.114b block: added `d11_wrap_ioctl` readback from wrapper offset 0x1408 (was missing)
  - Now logs: `wrap_RESET_CTL=... IN_RESET=... wrap_IOCTL=... CLK=...`
  - CLK=YES means BCMA_IOCTL_CLK (bit 0) is set → AXI slave accessible

**Outstanding question:**
- With BBPLL up and d11 out of reset, FW exits fn 0x1415c. What is the NEW hang site near 0x68c49?
- Need to re-probe: run test.115 stage0 (clean d11 IOCTL snapshot), then stage1 to see if counter advances

**Module status:** pice.c edited, NOT yet rebuilt. Run `make` in phase5/work/ before testing.

**Next steps:**
1. Build: `make -C /home/kimptoc/bcm4360-re/phase5/work`
2. Run test.115 stage0 (skip_arm=1) → get clean d11 IOCTL value after cr4_set_passive
3. Run test.115 stage1 (skip_arm=0, BBPLL up, no resetcore) → does counter advance past 0x43b1?
   - YES → hang moved; need new stack frame probes for FW ~0x68c49
   - NO  → something else blocks (check IOCTL value from stage0)

---

## Previous state (2026-04-17, PRE test.114 — d11 enable before ARM release, module built)

### Test.113 crash analysis (completed 2026-04-17)

test.113 was designed to read d11.clk_ctl_st and write FORCEHT to it.
It crashed immediately with **zero journal output** — a hard machine crash
from accessing d11 core registers while d11 was in BCMA reset.

**Root cause of test.113 crash:**
`brcmf_chip_set_passive` runs BEFORE `ops->reset` (in chip.c:1040-1048).
`brcmf_chip_cr4_set_passive` calls `brcmf_chip_coredisable` on d11 (not
`resetcore`), leaving d11 in BCMA reset. Then ops->reset runs test.113.
`brcmf_pcie_select_core(BCMA_CORE_80211)` + `read_reg32(0x1e0)` accesses
d11's core AXI slave while it's non-responsive → PCIe SLVERR → crash.

**Root cause of FW hang (still the same):**
`brcmf_chip_cr4_set_passive` also leaves d11 in BCMA reset at ARM release.
FW polls d11.clk_ctl_st (0x180011e0) for BP_ON_HT → AXI SLVERR → data
abort → FW hang. This is the hang at fn 0x1415c seen in test.106.

**Fix (test.114):**
- test.114a (`brcmf_pcie_reset_device`): replaced unsafe core register read
  with wrapper-only read (BAR0+0x1800 = d11_wrapbase+BCMA_RESET_CTL, always
  safe regardless of BCMA reset state).
- test.114b (`brcmf_pcie_load_firmware`, before skip_arm check):
  call `brcmf_chip_resetcore(d11core, 0x000c, 0x0004, 0x0004)` to take d11
  out of BCMA reset. Verify via wrapper RESET_CTL before/after. Read
  d11.clk_ctl_st safely after reset cleared.
  Runs with BOTH skip_arm=1 (diagnostic) and skip_arm=0 (full ARM release).

**Expected results:**
- test.114a: `wrap_RESET_CTL=0x00000001 IN_RESET=YES` (d11 in reset during ops->reset) ✓
- test.114b pre: `wrap_RESET_CTL=0x00000001 IN_RESET=YES` (still in reset before resetcore)
- test.114b post: `wrap_RESET_CTL=0x00000000 IN_RESET=NO` (reset cleared) ← key discriminator
- test.114b d11 clk_ctl_st: with skip_arm=1, BBPLL not up → BP_ON_HT may be NO
  With skip_arm=0 + test.47 BBPLL bringup, expect BP_ON_HT=YES

**Plan:**
1. Run with skip_arm=1 first → confirm no crash, verify wrapper reads
2. If clean: run with skip_arm=0 → test.47 brings BBPLL up, d11 out of
   reset, ARM released → FW should see BP_ON_HT and proceed past fn 0x1415c

**Build:** clean, `brcmfmac.ko` rebuilt (commit 63ee5fc).

**Test script:** `test-staged-reset.sh` — update LOG_NAME to `test.114`.

**Risk:** medium. `brcmf_chip_resetcore` on d11 is the same operation
`brcmf_chip_cm3_set_passive` does for other chips. Safe with skip_arm=1
(ARM never released). Wrapper register reads are always safe.

**Workflow:** commit + push before insmod (already done).

---

## Previous state (2026-04-17, POST test.111 + offline research — HANG REG IDENTIFIED)

**COMPLETE CHAIN OF EVIDENCE:**
- test.106: FW's fn 0x1415c hangs polling MMIO at `0x180011e0`.
- test.111: `0x18001000` = `BCMA_CORE_80211` (d11 MAC core), rev 42.
- brcmsmac/d11.h:168 `u32 clk_ctl_st; /* 0x1e0 */` — offset 0x1e0 in the
  d11 MAC core is the **per-core clock control/status register**.
- brcmsmac/aiutils.h:55-66:
  - `CCS_FORCEHT     = 0x00000002` (WRITE: force HT clock request)
  - `CCS_BP_ON_HT    = 0x00080000` (RO:    backplane running on HT clock)

**The hang, fully explained:** FW writes `CCS_FORCEHT` to d11's
clk_ctl_st, then spin-polls waiting for `CCS_BP_ON_HT`. On BCM4360 the
BBPLL is off post-EFI (test.40: HAVEHT=0, HAVEALP=1), and `brcm80211`'s
bcma backend has no PMU resource config for chip `0x43A0` ("PMU resource
config unknown or not needed for 0x43A0"). Result: HT clock never comes
up → `CCS_BP_ON_HT` never sets → FW poll runs forever at fn 0x1415c.

**Core map (for reference):**

| id    | name       | base        | rev |
|-------|------------|-------------|-----|
| 0x800 | CHIPCOMMON | 0x18000000  | 43  |
| 0x812 | 80211      | 0x18001000  | 42  | ← hang is at +0x1e0 = clk_ctl_st |
| 0x83e | ARM_CR4    | 0x18002000  | 2   |
| 0x83c | PCIE2      | 0x18003000  | 1   |

**This closes Phase 5.** Root cause of FW hang is definitively isolated
to "BBPLL/HT clock absent when FW runs."

**Phase 6 direction — bring up BBPLL/HT before releasing ARM:**
Options, roughly easiest → hardest:
1. **Host-side force HT via ChipCommon.clk_ctl_st:** write `CCS_FORCEHT`
   (bit 1) to CC before ARM release, wait for `CCS_BP_ON_HT` (bit 19).
   This is what brcmsmac does on similar chips (see main.c:1230-1240).
2. **Host-side PMU resource/pllcontrol programming:** program pllcontrol[0..5]
   and min/max_res_mask to match known-good EFI state, trigger BBPLL
   start. Requires pllcontrol register-map for BCM4360 rev-3.
3. **FW patching:** skip the poll loop at fn 0x1415c (hardest; still
   doesn't fix the underlying clock problem).

**Recommended next test: test.112 — host writes CCS_FORCEHT to CC and
polls CCS_BP_ON_HT.** Read-only pollers (a few reads on CC), no new
state mutation past the single force write. Observe whether BBPLL comes
up with the simple force-write alone.

**Workflow:** test.112 touches HW (a single CC write + polls) — RESUME
plan + commit + push before insmod.

---

## Test.111 raw result (2026-04-17 18:47, POST — FW HANG TARGET IDENTIFIED)

**`0x18001000` = `BCMA_CORE_80211` (d11 MAC core), rev 42.**

Full BCM4360 backplane core map (from driver's own enumeration,
`phase5/logs/test.111.stage0`):

| id    | name       | base        | rev |
|-------|------------|-------------|-----|
| 0x800 | CHIPCOMMON | 0x18000000  | 43  |
| 0x812 | 80211      | 0x18001000  | 42  | ← **FW HANG TARGET** |
| 0x83e | ARM_CR4    | 0x18002000  | 2   |
| 0x83c | PCIE2      | 0x18003000  | 1   |

Missing (not present): INTERNAL_MEM, PMU, ARM_CM3, GCI, DEFAULT.

**Interpretation:** the FW's `fn 0x1415c` (per test.106) reads register
`0x180011e0` — that's the d11 MAC core at offset `0x1e0`. The
80211/d11 core has a register bank starting at its base; `0x1e0` is a
well-known register range in brcm80211 — typically
`D11_MACCONTROL`/`MACCONTROL1`/`MACINTSTATUS` depending on rev. Need to
cross-reference with brcmsmac or brcm80211 headers for rev-42 d11.

**Run behaviour:** insmod rc=0 (not -ENODEV). skip_arm branch lives
inside `brcmf_pcie_download_fw_nvram`, but probe's firmware files are
missing (Apple-branded `.bin`, `clm_blob`, `txcap_blob` all load with
`-ENOENT`), so `copy_mem_todev` never runs and the probe returns a
clean 0 from the fw-request callback path. Host did NOT crash. dmesg
captured everything cleanly.

**Next direction — resolve what d11 register 0x1e0 is:**
1. Grep brcmsmac + brcm80211 sources for d11 MAC register headers
   (`d11.h`, `d11ucode.h`, etc.) and find the name/semantics of offset
   0x1e0.
2. Likely candidates on rev-42 d11: MACINTSTATUS (status poll),
   MACCONTROL (MAC enable latch), PHY_VERSION, PMU/clock status mirror.
3. The FW read at 0x1e0 is a spin loop (test.106 established a poll
   loop at fn 0x1415c). So it's waiting for a bit to set — likely a
   PHY or MAC-ready indication that never asserts because BBPLL/HT
   clock is off (PMU/pllcontrol evidence from test.40/109).

**Secondary line:** BBPLL/HT initialization — even if we identify
register 0x1e0 semantics, the root cause is probably still
"BBPLL isn't running so d11 can't produce the status bit FW is waiting
for." The d11 core requires HT clock. Test.40 already established
`HAVEALP=1 HAVEHT=0` after watchdog. We'd need to either (a) bring up
BBPLL before ARM release, or (b) patch FW to skip this specific poll.

**Workflow:** next step is offline research (grep d11 headers) — no HW
touch, no insmod.

---

## Previous state (2026-04-17, PRE test.111 — module built, about to run)

**Goal (unchanged):** identify the core at backplane slot 0x18001000 (the
FW-hang target from test.106: FW reads *0x180011e0 and never returns).

**test.110 outcome: BOX CRASHED HARD, ZERO KERNEL LOGS PERSISTED.**
- `phase5/logs/test.110.stage0` stops at the `=== Loading brcmfmac ===`
  header — no `insmod returned` line, no dmesg capture → insmod itself
  never returned, the script was never resumed.
- `journalctl -b -1 -k | grep BCM4360` → empty. Boot -1 (18:21:57 →
  18:34:49) persisted nothing for brcmfmac. Faster crash than test.109
  which at least got EFI/PMU/pllcontrol lines through to the journal.
- System rebooted into boot 0 at 18:35:22 cleanly.
- `.git.broken/` is a stale .git backup from 2026-04-17 16:14 (Pre-test.105
  COMMIT_EDITMSG inside); unrelated to test.110. Leave it alone for now.

**Diagnosis (advisor-informed):** the 11-slot BAR0-remap loop added to
`brcmf_pcie_reset_device` (pcie.c:762-801) either crashed synchronously on
entry, or triggered a PCIe completer error so severe journald could not
flush. Root cause is raw BAR0 sweeping during buscore_reset — unsafe.

**Pivot for test.111: use the driver's already-enumerated cores list.**
`brcmf_chip_recognition()` runs BEFORE `ops->reset` (see chip.c:1043-1049),
so by the time `brcmf_pcie_reset_device` executes via callsite 3244, the
chip's core list is fully populated. Public API
`brcmf_chip_get_core(ci, coreid)` returns each core with its `id`, `base`,
`rev` — NO MMIO, NO hang risk. This is exactly the data we need.

**Code change plan (pcie.c):**
- REPLACE the BAR0 11-slot sweep block (762-801) with a lookup over known
  core IDs: CHIPCOMMON, PCIE2, 80211, ARM_CR4, ARM_CM3, PMU, GCI, SOCRAM,
  DEFAULT (plus any others we know about). For each, `dev_emerg` log
  `id=0x%03x base=0x%08x rev=%u` OR `not present`.
- FLAG any core whose `base == 0x18001000` (FW-hang target).
- Keep `dev_emerg` (guaranteed flush, highest priority).
- `bcm4360_skip_arm=1` retained as safety (avoids FW hang after enum).

**Expected outcome:** probe prints the core list via dev_emerg, then
either skip_arm returns cleanly (clean log), or probe continues and wedges
at copy_mem_todev like test.109 (still have enum data in journal).

**Hypothesis:** slot 0x18001000 is likely `BCMA_CORE_80211` (d11 MAC),
based on chip.c:1022 which registers BCMA_CORE_80211 at 0x18001000 under
the SOCI_SB branch. If BCM4360 is SOCI_AI (EROM scan), actual layout comes
from EROM and could differ — we'll see in the log.

**Build status:** clean. `brcmfmac.ko` rebuilt at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/`. Only
pre-existing `brcmf_pcie_write_ram32 unused` warning (unrelated).

**Test script:** `phase5/work/test-staged-reset.sh` updated:
- LOG → `test.111.stage${STAGE}`
- banners/stage header reworded for test.111
- insmod args unchanged (`bcm4360_reset_stage=0 bcm4360_skip_arm=1`)

**Expected stage0 log:**
- Pre-test PCIe/root-port state (lspci)
- Loading banner
- insmod rc (likely 0 now — with cores populated skip_arm branch returns
  after TCM dump, but behaviour depends on exact path)
- dmesg BCM4360 lines including: EFI/PMU/pllcontrol + NEW 9 "test.111:
  id=0x... name=... base=0x... rev=..." lines + "core enum complete"
- Cleaning up brcmfmac

**Success criterion:** identify which core (if any) has `base=0x18001000`
— this is the FW-hang target from test.106. Hypothesis: BCMA_CORE_80211.

**Workflow:** this run touches HW — commit + push before insmod.

---

## Previous state (2026-04-17, PRE test.109 — module built, about to run)

**Goal:** capture the pre-ARM backplane core enumeration (11 slots from
0x18000000 to 0x1800A000) without crashing the host. Identifies what
core lives at slot 0x18001000 (FW-hang target per test.106).

**Why this run differs from test.107/108 (both lost all enum output):**
1. **Enum block moved** from pcie.c:~2305 (after skip_arm check) to
   pcie.c:~1889 (BEFORE skip_arm check). Now reachable in both paths.
2. **bcm4360_skip_arm=1** passed to insmod. Probe does test.101 baseline
   + the new enum + a 64B TCM dump, then returns -ENODEV cleanly.
   **No ARM release → no FW hang → no PCIe wedge → no crash.**
3. **dmesg -k --nopager** replaces journalctl in the capture step. Reads
   /dev/kmsg directly, no journald batching.
4. **No sleep in capture** — skip_arm=1 means no crash race; we can take
   as long as we want. dmesg runs synchronously post-insmod.
5. **rmmod after capture** so next run is repeatable.

**Files changed (post test.108):**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  - NEW test.109 enum block at ~line 1889 (after test.101 baseline,
    before `if (bcm4360_skip_arm)`). All logs are dev_emerg.
  - OLD test.108 enum block at ~line 2305 replaced with a short
    breadcrumb comment pointing to the new location.
- `phase5/work/test-staged-reset.sh`:
  - LOG → test.109.stageN, headers updated.
  - insmod invocation adds `bcm4360_skip_arm=1`.
  - insmod wrapped in set+e/set-e (expected non-zero rc from skip_arm).
  - Post-insmod capture uses `dmesg -k --nopager | grep BCM4360`
    instead of `sleep 2 + journalctl | grep`.
  - rmmod at end for repeatability.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected output:** `phase5/logs/test.109.stage0` contains:
- Pre-test PCIe state (lspci)
- Loading banner
- insmod rc=non-zero message
- BCM4360 kernel lines up through test.109 slot enum (11 lines)
- "Cleaning up brcmfmac..." from rmmod

**Decision tree:**
- All 11 slot reads logged → core map obtained; identify slot 0x18001000
  ID and cross-reference to EROM/datasheet.
- Script prints the loading banner but NO BCM4360 enum lines AND box
  crashes → slot+0 reads themselves are unsafe pre-ARM (previously
  unsuspected). Next step: try an even earlier probe with fewer reads.
- Script runs to completion but slot 0x18001000 off0=0xffffffff → slot is
  DEAD pre-ARM (no core present or unpowered). Implication: FW accesses
  a non-existent core → hang. Next step: try to identify the core via
  EROM walk or find evidence FW expects a different slot.
- Script runs but slot 0x18001000 off0=live non-ff value → core exists,
  is responsive to host-side MMIO. FW hang is specifically on 0x1e0
  register read. Next step: compare with neighbour cores' 0x1e0 value.

**Workflow:** this run touches HW — commit + push before insmod.

---

## Previous state (2026-04-17, POST test.108 — CRASHED AGAIN, plan pivots to skip_arm + dmesg)

**Outcome:** journal recovery from boot -1 shows only 27 BCM4360 lines,
last is `test.101 pre-ARM baseline: *0x62e20=0x00000000 ZERO (expected)`.
**NO test.108 enum output.** Stage0 script log got to header
`=== Post-insmod journal capture (boot 0) ===` then stopped — crash hit
during the `sleep 2 + journalctl | tee` capture window, wiping the
kernel ringbuffer before it reached persistent storage.

**Root cause (confirmed):** insmod with bcm4360_reset_stage=0 and no
skip_arm does a full ARM release → FW hangs on 0x180011e0 → PCIe root
port wedges → box hard-locks within ~1-2s of insmod returning.
Script-side `sleep 2 + journalctl | tee` loses the race.

**Pivot: new approach for test.109.** Stop depending on post-insmod
journal recovery. Instead:
1. **Skip ARM release via `bcm4360_skip_arm=1`.** The existing branch
   at pcie.c:1890-1919 returns -ENODEV cleanly without releasing ARM,
   so there's no FW hang, no root-port wedge, no crash. This path was
   last exercised in test.16 (commit d595029, 2026-04-14) — rot risk
   minimal (trivial reads + return -ENODEV).
2. **Move test.108 enum block from its current site (line 2305, AFTER
   the skip_arm branch, thus unreachable when skip_arm=1) to right
   after test.101 baseline (~line 1889).** This puts enum in the path
   for BOTH skip_arm=1 AND skip_arm=0.
3. **Replace journalctl capture with `dmesg -k --nopager`** in
   test-staged-reset.sh. dmesg reads /dev/kmsg directly — no journald
   batching, faster. With skip_arm=1 we also have unlimited time since
   no crash expected.

**Risk analysis:**
- If slot+0 reads on a dead slot DO crash the box (not just slot+0x1e0),
  we'll learn that with skip_arm=1 = no ARM release path → crash source
  is narrowed to the specific slot read.
- skip_arm branch does a TCM dump (64B) then returns. Should be safe.

**Next file edits planned:**
- `pcie.c`: move test.108 enum block (2278-2328) to line ~1889, renumber to test.109
- `test-staged-reset.sh`: LOG → test.109, pass `bcm4360_skip_arm=1`, switch capture to dmesg

---

## Previous state (2026-04-17, PRE test.108 — module built, about to run)

**Goal:** same as test.107 — identify what core lives at slot 0x18001000
and whether it's MMIO-responsive host-side while ARM is stuck. This time
with a probe that (a) won't crash the host bus pre-ARM, and (b) captures
its own log before any later crash can wipe it.

**Changes vs test.107:**
1. **Pre-ARM enum reads slot+0 only.** Dropped the slot+0x1e0 read —
   for slot 0x18001000 that targets 0x180011e0, the exact register FW
   hangs on. Host read of a hung backplane reg can stall root-port
   completions and kill the box before dev_emerg flushes. Presence probe
   via slot+0 is enough to answer "is a core there".
2. **FW-wait probe of 0x180011e0 preserved** inside the outer==1 branch
   with T106_REMASK (MAbort masking active). If this probe hangs, we
   survive thanks to re-mask.
3. **test-staged-reset.sh captures `journalctl -b 0 | grep BCM4360`
   into the stage0 log immediately after insmod.** Survives the later
   ~30s crash pattern. Adds `sleep 2 + sync` around the capture.

**Expected output per slot (from EROM knowledge):**
Slot numbers vs core types are unknown pre-run — the whole point of the
enum. Reading slot+0 on a dead slot returns 0xffffffff (master-abort).
On a live core it typically returns some structured ID/config word.

**Files changed:**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  pre-ARM enum no longer reads 0x1e0; renamed test.107→test.108 header
  and slot lines; FW-wait 0x180011e0 probe unchanged (keeps test.107 tag).
- `phase5/work/test-staged-reset.sh`: LOG path → test.108; added
  post-insmod journal capture block with sync + sleep + tee.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected log capture:** stage0 log should contain full dmesg in-line
(new capture block). If box crashes before sync, recover via
`journalctl -b -1 | grep -iE "BCM4360|brcmfmac" > phase5/logs/test.108.journal`
after reboot.

---

## Previous state (2026-04-17, POST test.107 — CRASHED EARLY, zero enum data)

**Outcome:** host crashed during or shortly after the pre-ARM test.107
block. Recovered journal (`phase5/logs/test.107.journal`) captured only 4
BCM4360 kernel lines:
- SBR via bridge 0000:00:1c.2
- SBR complete — bridge_ctrl restored
- BAR0/BAR2/tcm debug line
- test.53 BAR0 probe alive = 0x15034360

**NO test.107 enumeration output** (no "slot[0x...]" lines). **NO test.96
pre-ARM baseline** either — the crash beat the next batch of dev_info
calls to console. Session closed 17:59:45 (same second as the load).

**Hypothesis:** the pre-ARM enumeration loop reads `ioread32(regs + 0x1e0)`
for every slot. For slot 0x18001000 that targets `0x180011e0` — the exact
register the FW hangs on (test.106). Host-side read of an unresponsive
backplane register likely triggered a PCIe completion timeout that hung
the root port / bridge, killing the box before the next dev_emerg flushed.

**Next step (test.108): safer probe.**
- Pre-ARM enum reads **slot+0 only** (canonical first register; safe, just
  a presence probe). Skip slot+0x1e0 entirely pre-ARM.
- Defer the `0x180011e0` read to the existing FW-wait `outer==1` branch,
  where MAbort masking + re-mask every 10ms is already active (that's the
  regime the other test.106/107 probes survived in).
- If a pre-ARM read of slot+0 also crashes the box, we'll know that one
  read ≠ one write matters and we need a completely different strategy
  (e.g., use the EROM walk in si_attach to read core IDs indirectly).

---

## Previous state (2026-04-17, PRE test.107 — module built, about to run)

**Goal:** identify what core lives at backplane slot `0x18001000` (where fn
0x1415c's first MMIO read hangs) and whether that core is MMIO-responsive
from the host side while the ARM is stuck.

**Probe design (all READ-ONLY, no backplane writes):**

1. **Pre-ARM enumeration (11 slots):** loop `N = 0..10`, point BAR0 window
   at `0x18000000 + N*0x1000`, read offset 0 + offset 0x1e0 at each. Logs
   11 lines in stage-0 dmesg. Slot 0x18001000 is the FW-hang target.
2. **T+200ms hang-target probe:** during the existing FW-wait outer==1
   window, redirect BAR0 to `0x18001000`, read offset `0x1e0`, restore
   window to CC. One additional read. Compares host-side result to
   FW-side hang state.

**Files changed:**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  inserted test.107 block after the pre-ARM `brcmf_pcie_select_core(CC)`
  (before ARM release) and a hang-target probe in the existing
  outer==1 branch.
- `phase5/work/test-staged-reset.sh`: LOG path + header → test.107.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected log capture:** host crashes ~30s post-exit (pattern from t.101-106).
If stage0 log missing, recover via
`journalctl -b -1 | grep BCM4360 > phase5/logs/test.107.stage0`
after reboot.

---

## Previous state (2026-04-17, POST test.106 — PROLOGUE-HANG CONFIRMED)

**HEADLINE RESULT:** fn 0x1415c hangs on its first MMIO read (ldr.w at
0x14176). Target register = **0x180011e0** = backplane core slot #1 base
0x18001000 + offset 0x1e0. No sub-BL ever executes.

**Evidence (test.106, all 3 time samples identical):**
- T3@0200ms/0600ms/1000ms [0x9CEC4] = **0x00091cc4** (NOT LR-shaped)
- T1[0x9CED4] = 0x00068321 (fn 0x1415c saved LR — frame live)
- STRUCT_PTR[0x9CEC8] = 0x00091cc4 (TCM-shaped, valid struct ptr)
- MMIO_BASE[struct+0x88] = **0x18001000** (read BEFORE the hang)
- Anchors E/F stable at 0x67705 / 0x68b95
- Counter frozen at 0x43b1 throughout the 1.2s wait
- *0x62e20 = 0 (FW never wrote it — consistent with early hang)

**Interpretation:** the MMIO_BASE read (at offset 0x88 of struct) completed
successfully, so the struct is reachable. The HANG is on the *next* MMIO —
the ldr.w at 0x14176 reading `[r3, #0x1e0]` where r3=0x18001000. The ARM
stalls indefinitely because core 0x18001000 is either: (a) held in reset,
(b) not clocked, (c) not powered, or (d) not present on this chip variant
and no bus-error acceptor exists.

**Next phase — identify the core at 0x18001000 (NO HW COST):**
1. **EROM walk (disasm, subagent):** traverse EROM starting at some
   known-good core to enumerate cores + their backplane addresses on
   BCM4360. Need to find which core ID is at slot 0x18001000.
2. **Cross-ref with test.96 log:** "PCIe2 core id=0x83c rev=1" — we don't
   yet know its wrapper vs regset addresses. Possible that 0x18001000 is
   the PCIe2 core *from the ARM side* (different address than PCIe2 host-
   side BAR). Verify from disasm of `si_setcore` / EROM walker.
3. **FW disasm at fn 0x6820c's r0 setup:** the struct at 0x91cc4 with +0x88
   pointing to a core base looks like a `si_info` or core-handle structure.
   Find where it's populated — that will tell us the expected core type.

**Planned HW test (post-disasm):** if we identify the core, try (a)
holding it in reset via CC→resetcore before ARM release, or (b) forcing
its clock gate on, or (c) setting up a "fake" presence bit in SROM/OTP to
make FW skip the init path.

**Workflow rule:** commit + push RESUME_NOTES before editing pcie.c or
running any new test (host crashes ~30s post-exit; pre-commit preserves
state).

---

## Previous state (2026-04-17, PRE test.106 — test executed successfully)

**Goal:** discriminate **prologue-hang at fn 0x1415c's ldr.w 0x14176**
(first MMIO touch of `[[r0+0x88]+0x1e0]`) vs **poll-hang inside fn 0x1adc**
(called from fn 0x1415c's bit-17 poll loop).

**Discriminator:** sample T3 [0x9CEC4] at 3 time points (T+200ms, T+600ms,
T+1000ms). If any sample catches fn 0x1adc active, we'll see LR=0x1418f or
0x14187. If T3 stays non-LR-shaped across all 3 samples, prologue-hang is
confirmed.

**Disasm findings (subagent, 2026-04-17):**
- `phase5/notes/offline_disasm_6820c_r0_setup.md`: fn 0x6820c never spills
  r0 — struct pointer is held live in its callee-saved r4. When fn 0x1415c's
  prologue `push {r4,r5,r6,lr}` runs, it saves caller-r4 at its body_SP.
  So **[0x9CEC8] IS the struct pointer**. [struct+0x88] is the MMIO base.
- `phase5/notes/offline_disasm_15940_prologue.md`: fn 0x15940 pushes
  {r4..r8,lr} (N=6), body_SP=0x9CEC0, saved-LR slot=0x9CED4. If it were
  active, [0x9CED4]=0x6832b, not 0x68321. **T1=0x68321 still proves fn
  0x1415c is active.**

**Probe reads (14 total):**
- T+200ms (outer==1, 12 reads): ctr[0x9d000], pd[0x62a14], anc_E[0x9CFCC],
  anc_F[0x9CF6C], T1[0x9CED4], T3@200[0x9CEC4], struct_ptr[0x9CEC8],
  mmio_base[struct+0x88] (conditional on TCM-shaped struct_ptr), sweep
  [0x9CEC0]/[0x9CEBC]/[0x9CEB8], sanity *0x62e20
- T+600ms (outer==3, 1 read): T3@600[0x9CEC4]
- T+1000ms (outer==5, 1 read): T3@1000[0x9CEC4]

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Test script:** `phase5/work/test-brcmfmac.sh` (requires sudo).

**Expected log capture:** host crashes ~30s post-exit (pattern from t.101-105).
If stage0 log missing, recover via `journalctl -b -1 | grep BCM4360 >
phase5/logs/test.106.stage0` after reboot.

**Decision tree for test.106 results:**
- All 3 T3 samples non-LR-shaped → **prologue-hang CONFIRMED**; next test:
  inject a new probe before fn 0x1415c is reached (earlier callsite) OR
  look at the struct pointer value to identify the HW block. If MMIO base
  is a known PHY/PMU core register range, we can try holding that core in
  reset before ARM release.
- Any T3 sample == 0x1418f or 0x14187 → **poll-hang CONFIRMED** (fn 0x1adc
  delay inside poll loop or pre-loop). Next test: intercept at the poll
  itself, look at counter r6 saved at [0x9CED0] for progress.
- T1 changed → frame shifted, different analysis needed (unlikely given 5
  consecutive tests with T1 stable).

## Historical state (2026-04-17, POST test.105 — initial interpretation, now superseded)

Git branch: main. **Session recovery note:** prior session crashed during/after
test.105 run (16:14); .git had 15+ empty objects (refs/heads/main included).
Working tree was intact. Recovered by re-cloning from origin (which matched
the pre-crash HEAD 0ffaaf3). Broken .git preserved as `.git.broken/`. Working
tree backup at `/tmp/bcm4360-salvage/`. Git fully healthy now.

Test.105 captured from `journalctl -b -1` → `phase5/logs/test.105.stage0`
(63 lines, complete through 2s FW-silent timeout exit). Host crashed ~30s
after test clean exit, same post-exit pattern as t.101-104.

### TEST.105 RESULT — fn 0x1adc already returned

Raw probe output:
```
test.105 T+0200ms: ctr[0x9d000]=0x000043b1 pd[0x62a14]=0x00058cf0
test.105 ANCH  E[0x9CFCC]=0x00067705 F[0x9CF6C]=0x00068b95 (MATCH E=1 F=1)
test.105 T1[0x9CED4]=0x00068321 MATCH stable (fn 0x1415c saved LR)
test.105 T3[0x9CEC4]=0x00091cc4 NOT LR-shaped → fn 0x1adc already returned
test.105 SWEEP 0x9CEC0↓: 00000000 00068d2f 00091cc4 00092440
test.105 SWEEP LR-CAND [0x9cebc]=0x00068d2f
test.105 T+0200ms: SANITY *0x62e20=0x00000000
```

**Interpretation (per PLAN decision table):**
- Regression + anchors E/F stable — same hang site as t.101/102/103/104.
- T1 stable at 0x68321 — fn 0x1415c confirmed active (body SP still 0x9CED8).
- T3=0x91cc4 is **NOT LR-shaped** (not Thumb-odd, not in code range).
  Per plan, this rules out: bit-17 poll loop (0x1418f), pre-loop delay
  (0x14187), and poll-timeout/assert (0x141b7).
- **Decision: fn 0x1adc has already returned. Hang is elsewhere in fn 0x1415c's
  body, AFTER the BL to fn 0x1adc.**
- 0x91cc4 at 0x9CEC4 is stale (appears again at 0x9CEB8, and 0x68d2f at
  0x9CEBC is the same t.104-era fn 0x68cd2 leftover — body SP of whatever
  is currently running sits above 0x9CEC4).
- Sanity *0x62e20 still 0x00000000 — FW never wrote that word.

### Refined hypothesis (advisor insight, 2026-04-17)

**The absence of any LR-shaped value at [0x9CEC4] across t.101–105 is the signal,
not noise.** If fn 0x1415c had ever called any of its sub-BLs (0x1adc ×3 or
0x11e8) and returned, [0x9CEC4] would hold an LR-shaped value (0x14187,
0x1418f, or 0x141b7) as stale pop-didn't-clear. It doesn't — 0x91cc4 is
pre-fn-0x1415c stack garbage, meaning **fn 0x1415c has not called any sub-BL
yet**.

Combined with T1 [0x9CED4]=0x68321 (fn 0x1415c still the active frame of
fn 0x6820c), the hang is in fn 0x1415c's prologue, BEFORE 0x14182 (first BL
to 0x1adc).

**Prime candidate: ldr.w at 0x14176** — `ldr.w r2, [r3, #0x1e0]` — the first
MMIO touch of the status register `[r3+0x1e0]` (same register the later poll
would read). If this register's bus access stalls, CPU is frozen on this load.
(Write-back at 0x1417e is also possible if the read completes but the store
stalls.)

### Test.106 plan — discriminate prologue-hang vs poll-hang

**Primary discriminator: time-evolve T3.** Sample [0x9CEC4] at 3 time points
across the FW-wait (e.g. T+200ms, T+600ms, T+1000ms). If fn 0x1415c were
actually in the poll loop, we'd *occasionally* catch fn 0x1adc active and see
0x1418f (stochastic over many iterations × many time-samples). If T3 stays
0x91cc4 across all samples, prologue-hang is confirmed.

**Probe reads (≤ 14 total):**
1. Regression: ctr[0x9d000], pd[0x62a14] — continuity
2. Anchors: E[0x9CFCC] (exp 0x67705), F[0x9CF6C] (exp 0x68b95),
   T1[0x9CED4] (exp 0x68321) — chain stability
3. T3 × 3 times: [0x9CEC4] at T+200ms, T+600ms, T+1000ms — key discriminator
4. Struct pointer: [0x9CEC8] (saved r4 = r0 on entry = struct pointer). This
   tells us which HW block fn 0x1415c is touching.
5. Sweep 0x9CEC0 ↓ 0x9CEB8 — pre-call stack garbage context (not written
   by fn 0x1415c if hypothesis holds)
6. Sanity *0x62e20

**Pre-test disasm tasks (subagent, no HW cost):**
- **fn 0x6820c around 0x6831c:** find instructions that set r0 before
  `bl #0x1415c`. Tells us the expected struct pointer value → we can
  compute the actual MMIO register address [r0+0x88]+0x1e0 being hit.
- **fn 0x15940 prologue:** verify push count. If fn 0x15940 pushes exactly
  3 regs (rare), its body SP would land ABOVE 0x9CED4 and T1 would not be
  overwritten by a call to fn 0x15940 — in which case T1 stable doesn't
  prove fn 0x1415c is still active. (Expected: push includes LR + ≥2 regs
  so body SP ≤ 0x9CECC, T1 anchor is live.)

**Workflow rule:** commit + push RESUME_NOTES before editing pcie.c or
running test.106 (host crashes ~30s post-exit; pre-commit preserves state).

---

## Previous state (2026-04-17, PRE test.105 — module built, about to run)

**TEST.105 PLAN** (verified against raw firmware bytes, see pcie.c @ if (outer==1) block):
- Disasm source: `phase5/notes/offline_disasm_1415c.md` + prologue of fn 0x1adc
  manually verified (0xb538 = push {r3,r4,r5,lr}).
- Frame math: fn 0x1415c body_SP=0x9CEC8, fn 0x1adc body_SP=0x9CEB8, saved LR
  of fn 0x1adc at 0x9CEC4.
- **Key reading: T3 [0x9CEC4]** decides the hang state:
  - `0x1418f` → parked in fn 0x1adc from the bit-17 POLL LOOP (most likely)
  - `0x14187` → parked in fn 0x1adc from the pre-loop `delay(0x40)` call
  - `0x141b7` → poll TIMED OUT → hung inside fn 0x11e8 (assert/svc)
  - not LR-shaped → fn 0x1adc already returned, hang elsewhere in fn 0x1415c body
- 12 reads total (well under the safe 19-budget), 1200ms FW-wait, T104_REMASK
  equivalent macro throughout.
- **RESULT: T3 = 0x91cc4, NOT LR-shaped → fn 0x1adc returned. See POST section above.**

---

## Previous state (2026-04-17, POST test.104 — HANG LOCALIZED to fn 0x1415c)

Git branch: main. Host had a hard crash after test.104 ran (at 11:49); the
probe output was captured via `journalctl -b -1` and saved to
`phase5/logs/test.104.stage0`. Test.104 ran **twice** (boots -1 and -2), both
identical — result is deterministic.

### TEST.104 RESULT — CASE 1 (known-safe): T1 LR-shaped, maps to `bl 0x1415c`

**Raw output (identical both runs):**
```
test.104 T+0200ms: ctr[0x9d000]=0x000043b1 pd[0x62a14]=0x00058cf0
test.104 ANCH E[0x9CFCC]=0x00067705 F[0x9CF6C]=0x00068b95 (MATCH E=1 F=1)
test.104 T1[0x9CED4]=0x00068321 — LR-shaped → different sub-BL of fn 0x6820c
test.104 T2[0x9CEBC]=0x00068d2f — MATCH fn 0x68cd2 sub-BL candidate (STALE, see below)
test.104 SWEEP 0x9CEB8↓: 00091cc4 00092440 00093610 00000000 0009cf44 00012c69
test.104 SWEEP LR-CAND [0x9cea4]=0x00012c69
test.104 T+0200ms: SANITY *0x62e20=0x00000000
```

**Interpretation:**
- Regression + anchors E/F stable (= same hang site as t.101/102/103).
- **T1=0x68321 maps to BL row 14 in `offline_disasm_6820c.md`: `bl 0x1415c at
  0x6831c` → LR=0x68321.** CPU is inside fn 0x1415c, the 14th sub-BL of
  fn 0x6820c's body (not fn 0x68cd2 — that returned successfully).
- T2=0x68d2f at 0x9CEBC is **stale** — fn 0x68cd2 (at 0x68258) ran, pushed
  this LR on its descent, then returned. Its stack area is below fn 0x6820c's
  current body SP (0x9CED8) and 0x9CEBC holds unreclaimed data.
- Sweep values (0x91cc4, 0x92440, 0x93610, 0, 0x9cf44, 0x12c69) are mostly
  out-of-code-range; 0x12c69 is in range and odd (points ~0x12c68 in code),
  but sits OUTSIDE fn 0x1415c's body (0x1415c..). It's either a deeper-frame
  saved LR (fn 0x1415c → X → something-at-0x12c68), or stale. Do NOT anchor
  test.105 on 0x12c69 — treat as informational only.

**Free frame-size bound from T2 staleness:** 0x68d2f surviving at 0x9CEBC
means fn 0x1415c's live frame does NOT extend down past 0x9CEC0. So:
- fn 0x1415c body SP ≥ 0x9CEC0 ⇒ push_bytes + sub_sp ≤ 24 B
- LR-slot at [0x9CED0] (top of push block); pushed regs ≤ 6
If disasm reports a larger frame, something is inconsistent — verify.

**Falsified hypotheses (from 6820c disasm executive summary):**
- ★ fn 0x68cd2 is NOT the hang site (ruled out by T1 value)
- ★ fn 0x67f44 at 0x68308 is also past (LR would be 0x6830d, not 0x68321)

**New primary target: fn 0x1415c** — described in disasm as "HW init (unknown
target)". Not yet traced. Needs offline disasm to understand what it does
and to find breadcrumb / frame-size info for test.105.

### Next steps (test.105)

1. **Offline disasm fn 0x1415c** (subagent, no HW cost):
   - prologue → frame size
   - BL list → LR-candidate table for its sub-BLs
   - any polling loops / fixed-TCM writes
2. **Test.105 probe plan:**
   - 2 regression reads (ctr, pd) — continuity
   - 2 anchor reads (E, F) — chain stable
   - 1 read @ 0x9CED4 (T1 anchor, confirm still 0x68321)
   - Saved-LR slot of fn 0x1415c's current sub-BL (computed from its
     frame size; likely 0x9CED0 - frame_size)
   - Short sweep below that slot for deeper frames
   - 1 sanity `*0x62e20`
3. **Note:** the saved-LR slot for fn 0x1415c's current sub-BL = 0x9CED0
   (fn 0x1415c's body SP) - 4. Requires fn 0x1415c's prologue push count to
   compute exactly. Placeholder until disasm: probe 0x9CED0..0x9CEB8 densely.

### POST-EXIT CRASH PATTERN (observed in t.101/102/103/104)

Each test exits cleanly after its FW-silent timeout (2s). Approximately 30s
later, the host crashes / reboots. This is **unrelated to the probe itself**
— test completes and logs are written before the crash. Recovery:
`journalctl -b -1` on next boot gives full dmesg from the previous session.
Workflow rule: commit + push before running.

---

## Previous state (2026-04-17, PRE test.104 — module built)

### TEST.104 PLAN — zoom in on fn 0x6820c sub-frame

**Frame math (primary-source verified from firmware hex + disasm):**
- fn 0x6820c prologue: `push.w {r4..r8,sb,sl,fp,lr}` (9 regs = 36 B) + `sub sp,#0x74` (116 B)
- fn 0x6820c body SP = 0x9CED8 (= 0x9CF70 − 36 + 4 − 0x74, verified from LR@0x9CF6C=0x68b95)
- Any sub-callee of fn 0x6820c that pushes LR ⇒ saved LR at **0x9CED4**
- fn 0x68cd2 (first BL in fn 0x6820c, @ 0x68258): `push.w {r4..r8,lr}` (6 regs = 24 B), no sub sp
- fn 0x68cd2 body SP = 0x9CEC0; any sub-callee saved LR at **0x9CEBC**
- fn 0x68cd2 has 4 BLs; candidate saved-LR values: 0x68ceb, 0x68d05, 0x68d19, 0x68d2f

**Disasm subagent note:** `offline_disasm_68cd2.md` was generated by Haiku subagent; its
"LR@0x9CEBC" line is **wrong** (arithmetic slip: 0x9CED8−24=0x9CEC0 not 0x9CEBC, and LR
is at push-block top offset +20 not +0). Correct LR-slot for fn 0x68cd2 is **0x9CED4**.
The secondary slot 0x9CEBC still appears in the plan but as fn 0x68cd2's sub-callee LR
(coincidental address match).

**Probe plan (13 reads @ 1200ms FW-wait):**
- 2 regression reads: `ctr[0x9d000]`, `pd[0x62a14]` — continuity with t.101/102/103
- 2 anchors: E `[0x9CFCC]` (exp 0x67705), F `[0x9CF6C]` (exp 0x68b95) — chain stability
- T1 `[0x9CED4]` — sub-BL-of-0x6820c LR. If 0x6825d → hung inside fn 0x68cd2.
  Other LR-shaped values map to later BLs in fn 0x6820c.
- T2 `[0x9CEBC]` — sub-BL-of-0x68cd2 LR. Only meaningful if T1=0x6825d. Matches
  vs 0x68ceb/0x68d05/0x68d19/0x68d2f tell which fn 0x68cd2 body-BL is pending.
- 6-word sweep 0x9CEB8↓ — catches 3+ levels deep; flags LR-shaped (Thumb bit + code range)
- 1 sanity `*0x62e20`

Total reads 13 < test.103's 19 (known-safe budget).

### POST-EXIT CRASH PATTERN (observed in t.101/102/103)

Each test exits cleanly after its FW-silent timeout (2s). Approximately 30s later,
the host crashes / reboots. This is **unrelated to the probe itself** — test completes
and logs are written before the crash. Recovery: `journalctl -b -1` on next boot gives
full dmesg from the previous session. Workflow rule: commit + push before running.

---

## Previous state (2026-04-17, POST test.103 — frames A-E CONFIRMED, hang localized to fn 0x6820c)

Git branch: main. Host crashed ~30s after test.103 clean exit (same pattern as
test.101/102 — unrelated post-exit crash, test itself completed). Probe output
was captured via `journalctl -b -1` and appended to `phase5/logs/test.103.stage0`.

### TEST.103 RESULT — shallow chain confirmed, deeper hypothesis FALSIFIED

Module loaded 10:32:22, ran full probe, exited cleanly after 2s FW-silent
timeout (`brcmfmac ... TIMEOUT — FW silent for 2s — clean exit`). Host reset
followed ~30s later (not in journal; survived 2s of FW silence).

**Regression reads (stable vs t.101/102):**
- `ctr[0x9d000] = 0x000043b1` ✓
- `pd[0x62a14]  = 0x00058cf0` ✓
- counter frozen at 0x43b1 through T+1000ms → hang still present
- sanity `*0x62e20 = 0x00000000` ✓ (no progress past 0x68bbc, as expected)

**LR-slot reads (A..G) vs predicted:**

| Slot | Addr    | Read       | Expected    | Match | Meaning |
|------|---------|------------|-------------|-------|---------|
| A    | 0x9D09C | 0x00000320 | 0x320 EVEN  | ✓     | main frame (boot anchor) |
| B    | 0x9D094 | 0x00002417 | 0x2417      | ✓     | main → c_init |
| C    | 0x9D02C | 0x000644ab | 0x644ab     | ✓     | c_init → fn 0x63b38 |
| D    | 0x9D014 | 0x00063b7b | 0x63b7b     | ✓     | fn 0x63b38 → wl_probe |
| E    | 0x9CFCC | 0x00067705 | 0x67705     | ✓     | wl_probe → fn 0x68a68 |
| F    | 0x9CF6C | 0x00068b95 | 0x68acf     | ✗     | **NOT 0x67358 descent — deeper in fn 0x68a68 body** |
| G    | 0x9CF3C | 0x00092440 | 0x6739d     | ✗     | out-of-code-range; frame position was wrong |

**Calibrations (should NOT be LR-shaped by strict Thumb-odd filter):**
- `[0x9D028] = 0x00058cc4` — EVEN, so fails Thumb filter → not LR (likely saved r6 pointer into .rodata). Log text "offset error" is misleading; strict filter says fine.
- `[0x9CFC8] = 0x000043b1` — odd, in range, but equals the counter value at T+200ms → coincidence, not an LR.

**Deep sweep 0x9CF0C↓:** `00000004 000000c4 00093610 00000000 0009238c 00000000 00000004` — no code-range LRs; frame position was wrong (predicted for 0x67358, but actual descent uses different prolog sizes).

### NEW HYPOTHESIS — hang is in fn 0x6820c, not 0x67358

**Previous hypothesis RETRACTED:** "hang in wlc_attach's `bl 0x67f2c` → 0x67358 → 0x670d8 si_attach descent" is **falsified**. For LR F to be 0x68b95, fn 0x68a68 must have RETURNED FROM all four earlier body-BLs successfully:
- `bl 0x67f2c` @ 0x68aca (tail-call to 0x67358) → returned
- `bl 0x5250` @ 0x68b02 (nvram_get) → returned
- `bl 0x50e8` @ 0x68b0c (strtoul) → returned
- `bl 0x67cbc` @ 0x68b42 (struct setup) → returned

**LR math:** `bl 0x6820c` at 0x68b90 is a 4-byte BL → return addr = 0x68b94; Thumb bit set → saved LR = **0x68b95**. Matches F exactly.

**Current hang localization:** CPU is executing somewhere inside fn 0x6820c
(called from 0x68b90 in fn 0x68a68). Per `offline_disasm_68a68_body.md`,
fn 0x6820c "calls 0x68cd2, 0x142e0, fn 0x191dc, 0x9990, 0x9964 — not yet
fully traced" with MEDIUM hang capacity. This was previously ranked LOW
priority; now promoted to PRIMARY target.

### Next steps (test.104)

1. **Offline disasm fn 0x6820c** (subagent, no HW cost): prolog → frame size,
   BL list → LR-candidate table for the current frame's sub-BLs.
2. **Test.104 probe plan:**
   - 2 regression reads (ctr, pd) — continuity
   - 5 anchor reads A..E — cheap confirmation stack didn't shift
   - **Dense sweep 0x9CF68..0x9CF40** (10 words unprobed between F and mispositioned G) — catch fn 0x6820c's saved-LR if its sub-BL is pending
   - Informed-by-disasm: targeted read at predicted fn 0x6820c sub-frame LR slot
   - 1 sanity `*0x62e20`
   - Total ~20 reads, same order as test.103 — known-safe budget.

### Pre-test.103 state retained below for context.

---

## Previous state (2026-04-17, POST test.102 — stack sweep NULL, premise corrected, planning test.103)

Git branch: main. Last pushed commit 714c24f (Offline disasm: firmware stack located).
All test.102 work committed & pushed. Session resumed after unrelated host crash.

### TEST.102 RESULT — Case WEAK/NULL: 0 plausible LRs, premise was wrong

Test.102 ran cleanly (09:53:23 → 09:53:25 exit, RP restored). The
unrelated host crash came ~30min after the test completed.

**Readings at T+200ms:**
- Regression (vs test.101): `ctr[0x9d000]=0x43b1`, `pd[0x62a14]=0x58cf0` — matches
- Sanity: `*0x62e20=0x00000000` — matches test.101 (no progress past 0x68bbc still)
- Dense stack sweep at 0x9FE20..0x9FE5C (16 words × 4B):
```
0x9FE20: 1d9522f9 e6f20132 0bb91c6f 563dc9f8
0x9FE30: eb60c52c 1da991aa 21323bfa f3f5d5f6
0x9FE40: f992d3bc cfc5e975 f784a2ae 6ca7e38c
0x9FE50: 808b62f8 54b85687 55320d7b 98c8c797
```
All 16 words fail the LR filter (`∈[0x800..0x70000] AND LSB set`) — every
value > 0x70000 as 32-bit. **No match to any LR in the pre-computed table.**

### The premise was wrong — 0x9FE20 is not stack

Investigation after the null result: RESUME_NOTES (and test.102 plan)
claimed "test.97 located active stack frames near 0x9FE40". This was a
misread. Test.97's actual probe was at **0x9CE00..0x9CE1C**, not 0x9FE40,
and the values it captured were:
```
0x9CE08..0x9CE1C:  "1258" "88.0" "00 \n" "RTE " "(PCI" "-CDC"  (ASCII)
```
That's the RTE banner string IN THE CONSOLE RING (ptr = 0x9CC5C per test.96
baseline). Test.97 wasn't reading a stack — it was reading `printf` output.
The 0x9FE40 target has no provenance at all. Test.102 probed uninitialized
memory well above the actual stack.

### Offline disasm (POST test.102) — real SP location found

`phase5/notes/offline_disasm_fw_stack_setup.md` — full report.

Subagent disasm of firmware boot at offset 0..0x400 identified the actual
SP setup at firmware offset 0x2FC: `mov sp, r5`, r5 = 0xA0000 - 0x2F60 =
**0x9D0A0**. This is the SYS-mode stack pointer, used for everything
(hndrte RTOS pattern — all exception vectors redirect to SYS stack via
srsdb, no separate per-mode stacks).

**Firmware stack: [0x9A144 .. 0x9D0A0), grows DOWN, 0x2F5C bytes.**

- Entirely inside TCM → still readable via `brcmf_pcie_read_ram32`.
- Corroborating evidence (all from prior probes):
  - `ws[0x62ea8] = 0x9D0A4` = SP_init + 4 (static struct just above top)
  - `ramsize = 0xA0000` matches the r7 literal used in the size constant
  - Console ring at 0x9CCC0 is just BELOW stack bottom — classic hndrte
    layout (stack at top, printf ring beneath, BSS below)

### Premise for test.103 (advisor-validated)

Two LR-table issues to resolve BEFORE next test:

1. **Sweep location** — target the top of the stack (0x9D0A0 down) for
   shallow frames, OR target ~0x9CFD0 (approx 200 bytes down) for the
   deep descent frames listed in `test102_lr_table.md`. Advisor's
   preferred order: extend the LR table to the SHALLOW frames FIRST (no
   hardware cost), so a top-64-bytes sweep becomes directly interpretable.

2. **LR-table gap** — existing table covers deep descent
   (wl_probe → 0x68a68 → 0x67358 → 0x670d8 → si_attach children). The
   SHALLOW path (boot → main → c_init → fn 0x63b38 → wl_probe's caller)
   has NO entries yet. A subagent run is currently populating
   `phase5/notes/test103_lr_table_shallow.md` (disasm of c_init body,
   fn 0x63b38 body, and boot init from 0x2FC forward).

### test.103 PLAN — targeted LR-slot reads + deep sub-frame sweep

**Goal:** confirm the predicted frame chain (A..G) AND read the saved LR
of the 0x670d8 sub-BL that is currently hung — the one new piece of
information we need to isolate the hang site.

**Predicted stack layout** (from `test103_lr_table_shallow.md`):

| Frame | Addr    | Expected LR value | What it confirms |
|-------|---------|-------------------|------------------|
| A main       | 0x9D09C | 0x00000320 | outermost (boot tail) — **EVEN, exact-match only** (literal `mov lr, r0`, not bl/blx — Thumb bit NOT set) |
| B c_init     | 0x9D094 | 0x00002417 | main → c_init active |
| C fn 0x63b38 | 0x9D02C | 0x000644ab | c_init's wl bl active |
| D wl_probe   | 0x9D014 | 0x00063b7b | fn 0x63b38 → wl_probe active |
| E wlc_attach | 0x9CFCC | 0x00067705 | wl_probe → fn 0x68a68 active |
| F fn 0x67358 | 0x9CF6C | 0x00068acf | wlc_attach descent active |
| G fn 0x670d8 | 0x9CF3C | 0x0006739d | deep init active |
| sub LR (hung)| ~0x9CF0C or lower | one of {0x67195 / 0x671b5 / 0x671c1 / 0x671d5 / 0x671f7} | identifies WHICH 0x670d8 BL is stuck |

**Probe design (19 reads total, T+200ms only):**

- **7 targeted LR-slot reads** (A..G): read each predicted-LR address,
  check against expected value. Each is a single word, direct hit.
- **2 calibration reads** (advisor-recommended): read "between-LR" slots
  0x9D028 (frame C mid — saved r6) and 0x9CFC8 (frame E mid — saved r8).
  Both should NOT be LR-shaped. If either IS LR-shaped, that's unambiguous
  evidence of a 4-byte offset error in the corresponding frame-size
  prediction (cheap diagnostic).
- **7 deep sweep words** at 0x9CF0C..0x9CEF0 (4B stride): catches the
  saved LR of whatever 0x670d8 sub-call is currently running. Expected
  to find ONE of the five candidate LRs listed above.
- **2 regression reads**: ctr[0x9d000] (expect 0x43b1), pd[0x62a14]
  (expect 0x58cf0) — continuity with test.101/102.
- **1 sanity**: *0x62e20 (expect 0 — confirms breadcrumb still not written).

**Pre-registered failure signatures (set before run so we can't
post-hoc rationalize):**

1. **Success**: ≥5 of 7 LR-slot reads match predicted values AND deep
   sweep contains ≥1 LR from the 0x670d8-sub candidates. → test.104
   is "pin down which sub-BL via disasm of that sub's body for
   breadcrumb candidates or deeper stack walk".
2. **Offset drift**: calibration read (0x9D028 or 0x9CFC8) IS LR-shaped,
   AND the aligned target is NOT. → frame-size prediction is off by 4B
   starting at that frame. Re-disasm that function's prologue offline.
   DO NOT trust deeper reads.
3. **Shallow only**: A/B match (0x9D09C=0x320 **EVEN**, 0x9D094=0x2417) but C+
   don't. → hang happened before reaching fn 0x63b38, OR fn 0x63b38's
   prologue is different. Either way, outer chain anchor confirms the
   model; localize the divergence.
4. **All miss**: no predicted LR at any target address AND no LR-shaped
   words in deep sweep. → SP_init is wrong (stack is elsewhere), OR
   stack was trashed by an early fault. test.104 = sparse survey across
   whole [0x9A000..0x9D100) range to locate it.

**Budget:** 19 reads — exactly at test.102's known-safe count.
FW-wait stays at 1200ms. No new regression risk.

**Implementation notes:**
- Replace test.102's 16-word sweep block with the 19-read block above.
- Each read via existing `brcmf_pcie_read_ram32` path.
- Masking (T101_REMASK) called before each read — same as test.101/102.
- Log lines: group A-G in one table-like print, calibrations in another,
  deep sweep in a third.
- **LR-filter caveat:** Frame A (0x9D09C) is a permanent static anchor
  of value **0x320 (EVEN)** because the boot code loaded LR via literal
  `mov lr, r0` (not a bl/blx, so Thumb bit is not set). Do NOT apply
  an odd-bit filter to the 0x9D09C slot — match it exactly against
  0x320. Frames B..G are all from bl/blx, so odd-bit holds for them.

### After running test.103
- Apply failure signature matrix above.
- Stage1 = none (this is a pure read-only probe; no second stage needed).

**Pre-test.102 state retained below for full context.**

---

## Previous state: POST test.101 — Case 0: breadcrumb ZERO, hang UPSTREAM of 0x68bbc

### TEST.101 RESULT — Case 0 (matrix row 1): breadcrumb ZERO

Test.101 ran cleanly in boot -1 (07:42:59 → 07:43:01 clean exit). Machine
then crashed/rebooted ~30 min later (08:13:05 boot 0) — unrelated to the
test run itself; the test completed with "RP settings restored".

Key readings:
```
Pre-ARM baseline: *0x62e20 = 0x00000000  ZERO (expected — no stale TCM) ✓
T+200ms:          *0x62e20 = 0x00000000  ZERO
```

Control pointers (as test.100):
```
ctr[0x9d000]  = 0x000043b1
d11[0x58f08]  = 0x00000000
ws [0x62ea8]  = 0x0009d0a4
pd [0x62a14]  = 0x00058cf0
```
Counter frozen at 0x43b1 from T+200ms onward, confirming hard freeze by
T+12ms (per test.89 timeline) still holds.

**Interpretation per test.101 matrix row 1:** baseline=0 means no stale
TCM (interpretation is clean); T+200ms=0 means fn 0x68a68 NEVER wrote
*0x62e20 at 0x68bbc. Therefore fn 0x68a68 did NOT reach 0x68bbc.

Combined with test.100 (Case C′: fn 0x1624c never ran), the freeze is:
- Inside fn 0x68a68 prefix/body BEFORE bl 0x1ab50 at 0x68bcc
  (specifically the unexamined body region 0x68aca–0x68bbc), OR
- Upstream in wl_probe (fn 0x67614), in one of the earlier sub-BLs
  BEFORE bl 0x68a68 at 0x67700.

Per the earlier subagent offline disasm (`offline_disasm_wl_subbls.md`),
the five wl_probe sub-BLs (fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c,
plus fn 0x68a68 prefix through 0x68aca) contain NO spin loops, HW-register
polling, or fixed-TCM stores in their direct bodies. The hang must
therefore be in one of their DESCENDANTS, or in fn 0x68a68's UNEXAMINED
body 0x68aca–0x68bbc.

### Offline disasm result (POST test.101, 2026-04-17)

`phase5/notes/offline_disasm_68a68_body.md` — full report of fn 0x68a68
body 0x68a68..0x68bcc and all 6 body-BL targets.

**Key finding:** fn 0x68a68's first body BL (`bl 0x67f2c` at 0x68aca) is a
4-insn trampoline that **tail-calls 0x67358** — the SAME si_attach descent
entered from pciedngl_probe (which succeeded). So wlc_attach's failure is
a re-entry into 0x67358 → 0x670d8 → 0x64590 (si_attach) → core-register
dispatches → deeper.

**No discriminating fixed-TCM breadcrumb exists in this descent.** Every
store in fn 0x68a68 body, fn 0x670d8 body, and fn 0x64590 (si_attach) is
r4/r3-relative into freshly-alloc'd structs. The ONLY fixed-TCM write in
the descent (fn 0x66e90: `str r0, [*0x62a88]`) is a LATCH — populated by
pciedngl's first entry, SKIPPED by wlc_attach's second entry (list is
already non-empty; takes the error-printf path without overwriting).

Advisor verdict: "Don't extend disasm further looking for a breadcrumb.
That IS the evidence." → Pivot to **stack-walk approach** for test.102.

### test.102 PLAN — stack-locator sparse sweep

**Goal:** Identify the function whose `bl` is currently pending-return by
reading the stack region and filtering for saved LR values. Each LR
candidate maps (via pre-computed table, see below) to a specific call
site — naming the function whose call is currently suspended.

**Rationale for stack walk (not more breadcrumbs):**
- The wlc_attach descent has no discriminating fixed-TCM stores.
- Each nested `bl` in ARM Thumb pushes lr on the stack (part of
  `push {..., lr}` prologues). When the CPU is stuck mid-call, its live
  frame chain is persistent in RAM.
- Test.97 located active stack frames "near 0x9FE40". TCM end is 0xA0000.
- Filter: `word ∈ [0x800..0x70000]` AND LSB set (Thumb bit) → plausible LR.
- Confirmation: ≥2 LRs forming a known caller→callee chain. A lone
  hit is data-shaped-like-LR — not confirmed. A chain is strong.

**Probe design (read-only, all via `brcmf_pcie_read_ram32`):**
- Baseline pre-ARM: `*0x62e20` — continuity check vs test.101
- T+200ms: 2 regression reads — ctr (0x9d000), pd (0x62a14) — dropped d11
  and ws (test.101 showed d11=0 stable, ws=0x9d0a4 stable, not interpretation-gating)
- T+200ms: **dense stack sweep — 16 reads × 4B stride at 0x9FE20..0x9FE60**
  (64B region centered on test.97's 0x9FE40 frame-density locator)
- T+200ms: 1 re-read of `*0x62e20` (sanity vs test.101)
- Total: **19 reads** at the single T+200ms timepoint.

**Budget analysis** (per advisor linear-scaling assumption — no data
between 5 and 13 reads, and nothing above 13):
- test.101: 5 reads @ 1200ms FW-wait → clean
- test.100: 13 reads @ 2000ms FW-wait → ~1.9s regression
- test.102: 19 reads @ 1200ms FW-wait → ~1.5× test.101, **well below** the
  known regression point at 13. Staying dense+narrow buys the ability to
  see a chained LR pair, at the cost of SP-location precision.

**FW-wait:** keep at 1200ms (same as test.101 — per advisor, budget is
probe count, not outer loop).

**Pre-computed LR → function interpretation table:**
See `phase5/notes/test102_lr_table.md` — built from existing disasm
(test88/90/91, offline_disasm_68a68_body). Expected live chain top-down:
1. wl_probe's `bl 0x68a68` @ 0x67700 → LR = **0x67705** (Thumb bit set)
2. wlc_attach's `bl 0x67f2c` @ 0x68aca → LR = **0x68acf**
3. (0x67f2c is tail-call trampoline → no frame)
4. fn 0x67358's `bl 0x670d8` @ 0x67398 → LR = **0x6739d**
5. fn 0x670d8's `bl 0x64590` @ 0x67190 → LR = **0x67195**, or a later
   child call (0x671b5, 0x671c1, 0x671d5, 0x671f7)
6. Depending on depth: LRs inside si_attach body (0x645b3, 0x645c7,
   0x6463d, 0x64679, 0x6468f — from test91_disasm BL list)
   All pushed-LR values are **odd** (Thumb bit set) — filter accordingly.

**Confirmation criteria:**
- **Strong:** ≥2 LRs from the table appear in the 16-word sweep.
- **Moderate:** 1 LR from table + nearby word in a plausible range but
  not listed (may be a deeper child not yet disassembled).
- **Weak/null:** 0 LRs from table → sweep missed the SP region; dense
  follow-up in test.103.

**Deferred to test.103 (per budget):**
- Full console ring dump (firmware may have printed an error before hang)
- Dense 32-word sweep at the LR-rich 128B region identified by test.102

**Crash-safety checks:**
- All 16 sweep addresses are inside TCM (< 0xA0000).
- No HW register reads, no core switching.
- Masking (T101_REMASK) called before each read — same pattern as test.101.

### Pre-test.101 state (retained for context below)

---

### Advisor refinement #1 (added 2026-04-17, pre-run)

Per advisor, the pre-ARM baseline read was the missing piece from the
earlier test-plan review — without it, a non-zero post-FW breadcrumb
could reflect residual TCM state from a prior in-same-boot modprobe,
not a fresh FW write. Code change: 3-line probe in pcie.c inside the
existing pre-ARM logging block (before ARM release, zero masking-loop
impact). Emits `dev_emerg "BCM4360 test.101 pre-ARM baseline: *0x62e20=...
ZERO (expected) / NON-ZERO (stale TCM, breadcrumb reading is unreliable)"`.

Matrix interpretation rule: if baseline != 0, the T+200ms breadcrumb
reading is UNRELIABLE and the run should be re-done after fresh power
cycle. If baseline == 0 and T+200 == 0 → Case U1 (hang before 0x68bbc).
If baseline == 0 and T+200 != 0 → Case D (hang at/past bl 0x1ab50).

### Offline disasm result (subagent, 2026-04-17)

`phase5/notes/offline_disasm_wl_subbls.md` — full report.

Disassembled wl_probe's 5 untraced sub-BLs (fn 0x66e64, fn 0x649a4,
fn 0x4718, fn 0x6491c) and fn 0x68a68's prefix. **None contain spin loops,
HW-register polling, or fixed-TCM stores** — every memory write is
r4-relative into the freshly-malloc'd wl_ctx. fn 0x4718 is a 3-instruction
leaf. Therefore the hang is NOT internally in any of those five.

**Most-likely hang site:** fn 0x68a68 (wlc_attach) BODY between its prefix
end at 0x68aca and `bl 0x1ab50` at 0x68bcc — an unexamined region (test.100
only excluded fn 0x1624c, a deeper descendant).

**Hot breadcrumb identified: `*0x62e20`.** Spot-verified:
```
0x68bb6: ldr  r3, [pc, #200]   ; literal at 0x68c80 = 0x00062e20 ✓
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, 0x68bbe       ; skip if already set
0x68bbc: str  r4, [r3]           ; *0x62e20 = wl_ctx ptr
0x68bcc: bl   0x1ab50            ; PHY descent (8 bytes later)
```
`*0x62e20` is zero in the firmware image. After firmware reset:
- **non-zero** → fn 0x68a68 advanced to within 8 bytes of bl 0x1ab50;
  hang is inside bl 0x1ab50 (or the 2-insn gap before it). test.100
  already excluded fn 0x1624c, so the hang would be in fn 0x1ab50 BEFORE
  it reaches fn 0x16476.
- **zero** → fn 0x68a68 did not reach 0x68bbc. Hang is in one of its
  earlier BLs (0x68a68 prefix/body), or in wl_probe BEFORE bl 0x68a68 at
  0x67700 — i.e. in fn 0x66e64 / fn 0x649a4 / fn 0x4718 / fn 0x6491c's
  DESCENDANTS (since their direct bodies are bounded).

### test.101 PLAN — minimal single breadcrumb probe

**Goal:** narrow hang to "past 0x68bbc" vs "before 0x68bbc" with MINIMUM
loop-overhead impact. Test.100 added 9 extra `read_ram32` calls and
regressed (boot ended between T+1800ms and T+2000ms).

**Probe changes from test.99 baseline:**
- REMOVE test.100's triple-timepoint 3-field wait-struct reads (already
  answered — Case C′ confirmed, struct never touched).
- REMOVE test.100's T+400ms+T+800ms duplicate pointer probes (test.99
  already proved pointers are byte-identical across those windows).
- ADD one new read: `TCM[0x62e20]` at T+200ms only.

Net: test.101 probe count = test.99 - 2 + 1 = **fewer reads than
test.99**. Should not regress on the masking-loop budget.

**Also:** shorten FW-wait from 2000ms to 1200ms to widen safety margin
against whatever periodic event killed test.100 at ~1.9s.

**Matrix (after reading *0x62e20):**

| *0x62e20 | Conclusion | Next action |
|----------|------------|-------------|
| 0          | fn 0x68a68 did NOT reach 0x68bbc. Hang is in 0x68a68 prefix/body before the breadcrumb, or upstream in wl_probe sub-BL descendants. | test.102: probe wl_ctx fields (needs wl_ctx ptr discovery first) OR disasm fn 0x68a68 prefix + descendants of fn 0x6491c. |
| non-zero, value plausible as heap ptr (TCM range 0x0..0xA0000, typically 0x9xxxx) | fn 0x68a68 reached 0x68bbc. Hang is inside the window `bl 0x1ab50 → bl 0x16476 → b.w 0x162fc → bl 0x1624c` but NOT inside fn 0x1624c itself (test.100 excluded that). So hang is in the body of fn 0x1ab50, fn 0x16476, or fn 0x162fc pre-spin. | test.102: disasm those three fn bodies pre-bl; probe their breadcrumbs. |
| non-zero, value implausible (random)    | Either TCM read failed or breadcrumb theory is wrong. | Re-check read path; verify literal pool claim with second tool. |

**Pre-flight reminders:**
- Probe is read-only via `brcmf_pcie_read_ram32` (same safe path as test.99/100).
- FW-wait shortened to 1200ms. No other change to cleanup order.
- If machine crashes anyway, that's still informative — different cadence
  than test.100 would pinpoint what the ~1.9s event is.

### Hardening checks completed before build

**Firmware image at offset 0x62e20**: 0x00000000 (surrounding .bss-like
region also zero). So post-FW non-zero at 0x62e20 unambiguously means
FW wrote it.

**All writers of 0x62e20 in the firmware** (grepped literal 0x00062e20,
3 aligned hits in pools at 0x149b0 / 0x68208 / 0x68c80):
1. `fn 0x68a68 @ 0x68bbc` — `str r4, [r3]` sets wl_ctx ptr (attach path,
   on wl_probe lineage). **This is the breadcrumb.**
2. `fn 0x681bc @ 0x681cc` — `str r2, [r3]` where r2=0, conditional clear.
   Prologue at 0x681bc; only runs on detach/cleanup (guarded by `arg ==
   *0x62e20`). **Does NOT run during wl_probe.**
3. `fn at 0x14948 uses literal at 0x149b0` — READ-ONLY
   (`ldr r3,[pc,#88]; ldr r3,[r3,#0]; cbz r3,err; ldr r3,[r3,#12]`).
   Diagnostic/logging helper. **Not a writer.**

→ During wl_probe attach, only writer of 0x62e20 is fn 0x68a68 @ 0x68bbc.
Breadcrumb semantics are preserved: non-zero at T+200ms ⇒ that single
instruction ran.

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.100 probe block with
  test.101: single read of TCM[0x62e20] at T+200ms. Drop duplicate
  pointer reads at T+400/800ms. Change FW-wait cap from 2000ms to 1200ms.
- `phase5/work/test-staged-reset.sh` — relabel test.100 → test.101,
  LOG filename accordingly.

### After running test.101
- Apply matrix, choose test.102.
- Most-likely outcome (per subagent analysis) is *0x62e20 non-zero →
  hang is in fn 0x1ab50 pre-bl body.

### TEST.100 RESULT — Case C′ (matrix row 5): wait-struct = pre-init garbage, stable

test.100 ran in boot -1 (23:31:37 → 00:46:48). Probes at T+200/400/800ms
captured identical values (stability check PASSED). Firmware hard-frozen
at T+12ms per test.89 timeline; nothing on-chip changed across 600ms.

Control pointers (identical across T+200/400/800ms):
```
ctr[0x9d000]  = 0x000043b1    (static constant from fn 0x673cc)
d11[0x58f08]  = 0x00000000    (D11 obj never linked)
ws [0x62ea8]  = 0x0009d0a4    (wait-struct pointer — static, from BSS)
pd [0x62a14]  = 0x00058cf0    (pciedngl vtable, matches test.93/99)
```

Wait-struct field reads at ws=0x9d0a4 (identical across T+200/400/800ms):
```
f20 [ws+0x14] = 0x66918f11
f24 [ws+0x18] = 0x5bebcbeb
f28 [ws+0x1c] = 0x84f54b2a
```

**None of these are {0,1}** — they are arbitrary 32-bit values. Per the
test.100 matrix (row 5): `f24 ∉ {0,1}` → **Case C′: struct never touched,
pre-init garbage**. fn 0x1624c's setup code (`r3->field24=1;
r3->field28=0`) never ran, therefore fn 0x1624c itself never ran.

**Conclusion:** the freeze is strictly upstream of fn 0x1624c — inside
wl_probe (fn 0x67614), before it reaches the D11 PHY wait chain. The
bl-graph says exactly one path from wl_probe reaches fn 0x1624c; that path
is fn 0x67700→0x68a68→…→0x1624c. The hang must be in either the body of
fn 0x68a68 before its call to fn 0x1ab50, or in one of the 6 other sub-BLs
wl_probe invokes BEFORE bl 0x68a68 (at offsets 0x67700 and earlier).

This corroborates test.97's hint (same "garbage" reading) and definitively
rules out the PHY-completion-wait hypothesis as the LIVE freeze site.

### Test.100 ALSO produced a new regression

The run died between T+1800ms and T+2000ms (journal ends at T+1800ms
FROZEN, no TIMEOUT / RP-restore lines, machine powercycled). test.99 used
the same FW-wait loop and exited cleanly at T+2000ms. The delta is 3 extra
`read_ram32` calls at each of T+200/400/800ms (≈30–90ms total extra time
in the masking loop). That evidently nudged past a re-mask window and a
periodic PCIe event slipped through.

**Implication for test.101:** the masking loop must be re-audited or the
FW-wait shortened (e.g. 1000ms) before adding any more probes. Do NOT
stack further reads on top of the current loop without budget work.

### Next step — offline-only progress before test.101

Per advisor review, the cheap-progress ordering is:

1. **Firmware-binary sanity check** (30 seconds, offline): dump firmware
   image bytes at offset 0x9d0b8, 0x9d0bc, 0x9d0c0. If they match the read
   values 0x66918f11 / 0x5bebcbeb / 0x84f54b2a → "Case C′ = firmware image
   static data" confirmed. If they don't match → new puzzle (uninit RAM?
   wrong address translation?).

2. **Offline disasm of wl_probe's 6 untraced sub-BLs**. wl_probe has 7
   sub-BLs; only bl 0x68a68 at 0x67700 (→ PHY chain) is currently mapped.
   The other 6 are unknown. Find each, note its reads/writes (globals or
   fields of wl_struct). The hang is in one of them (or in fn 0x68a68's
   body before bl 0x1ab50). This narrows test.101 to concrete breadcrumbs
   instead of the hypothetical wl_struct[+0x90] placeholder.

3. **Masking-loop audit**: ensure re-mask fires every iteration when probe
   block inflates the body; consider dropping FW-wait from 2000ms to
   1000ms for test.101 to widen margin.

4. Only THEN design test.101 probes from concrete breadcrumb sites.

---

## Pre-test.100 state (retained for context below)

### Offline disasm — wl_probe and freeze chain (no hardware test)

`phase5/notes/offline_disasm_c_init.md` Round 3 + Round 4 (full detail).

Anchored "wl_probe called\n" print site to fn 0x67614 (LDR-literal scan
matched "wl_probe" string at 0x4a1ea via *0x67890). **fn 0x67614 IS
wl_probe()**. It is called as `wl_struct.ops[0]` from inside fn 0x63b38 in
c_init's wl-device registration step.

Brute-force callgraph BFS (depth ≤ 6) from each of wl_probe's 7 sub-BLs
shows EXACTLY ONE reaches the test.96 D11 PHY wait chain:

```
wl_probe @ 0x67614
 → bl 0x68a68 @ 0x67700           (5 stack args + 4 reg args)
   → bl 0x1ab50 @ 0x68bcc
     → bl 0x16476 @ 0x1ad2e        (PHY register access wrapper)
       → b.w 0x162fc                (PHY-completion wrapper)
         → bl 0x1624c @ 0x1632e     (SPIN: while ws->f20==1 && ws->f28==0)
```

`fn 0x68a68` has exactly ONE caller — wl_probe at 0x67700 — so the entry to
the spin-loop subtree is unique through wl_probe. The freeze fingerprint
matches test.96's analysis (D11 PHY ISR never fires → field28 stays 0). The
EARLIER claim that the hang was via c_init's "Call 3" (0x6451a) was wrong —
that dispatch chain only runs AFTER wl_probe RETURNS, and wl_probe never
returns (so wl_struct[+0x18] stays 0, as observed in test.99).

Open questions remaining (will be answered by test.100):
- Is the live freeze actually inside the fn 0x1624c spin-wait, or earlier
  in the wl_probe path (e.g. inside fn 0x66e64 / fn 0x649a4 / fn 0x68a68
  body before reaching the PHY chain)?
- Wait struct address: test.99 read `*0x62ea8 = 0x9d0a4` — the static BSS
  struct that fn 0x1624c spins on. We can probe its field20/24/28 directly.

### test.100 PLAN — wait-struct field probe (cheap PHY-wait fingerprint check)

**Goal:** decide between three concrete hypotheses with ONE more cheap
read-only hardware cycle:

1. PHY spin-loop is the live freeze location (advisor's "case A").
2. fn 0x1624c entered then exited via the cancel path (case B).
3. fn 0x1624c never entered — freeze is upstream in wl_probe (case C).

**Probes (stage0, all read-only TCM accesses via brcmf_pcie_read_ram32):**

Wait struct: addr = `*0x62ea8 = 0x9d0a4` (confirmed in test.99). Read fields
at offsets +0x14/+0x18/+0x1c (= field20 / field24 / field28 in test.96
analysis) at T+200/400/800ms to confirm stability:

```
ws_addr  = *0x62ea8                        ; should be 0x9d0a4
field20  = TCM[ws_addr + 0x14]             ; status flag (loop var)
field24  = TCM[ws_addr + 0x18]             ; "in progress" flag
field28  = TCM[ws_addr + 0x1c]             ; completion flag (set by ISR)
```

Also keep the test.99 pointer-sample probes (ctr/d11/ws/pd) as control — if
those CHANGE between test.99 and test.100 it would invalidate the read.

**Pre-flight stability check (READ FIRST before applying matrix):**

test.89 established firmware hard-freezes by T+12ms. test.99 confirmed
control pointers are byte-identical across T+200/400/800ms. Therefore
field20/field24/field28 MUST also be byte-identical across the three
timepoints. **If they vary, that itself is the bigger story** (delayed
code path, or the read isn't doing what we think — e.g. probe disturbing
state, addr translation wrong). Stop, characterise the variation, and DO
NOT apply the matrix to T+200ms values alone.

**Matrix interpretation (advisor, refined):**

| field24 | field20 | field28 | Conclusion |
|---------|---------|---------|------------|
| 1 | 1 | 0 | **Case A — spin-loop is live freeze.** Path B step 1 (D11 BCMA wrapper bring-up to enable D11 core / route ISR). |
| 1 | 0 | 0 | **Case B — entered then cancelled.** Hang is in fn 0x162fc body AFTER bl 0x1624c returned via cancel path. Re-examine fn 0x162fc continuation. |
| 1 | * | !=0 | Spin completed (field28 set), but firmware still hung downstream. Hang is past PHY wait — need to trace fn 0x1ab50 / fn 0x68a68 callees beyond the PHY register loop. |
| 0 | * | * | **Case C — fn 0x1624c never entered, struct zero-initialised.** Freeze is upstream in wl_probe. Probe candidates: fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c, or fn 0x68a68 body before bl 0x1ab50. |
| ∉{0,1} | * | * | **Case C′ — struct never touched, pre-init garbage** (test.97 saw garbage values here). Same upstream-freeze conclusion as C, but distinguishable from "BSS-zero never-entered" — different next-test framing. |

**Risk profile:** identical to test.99. All probes are TCM reads via
existing `brcmf_pcie_read_ram32` path, gated by the same masking macro.
test.99 ran cleanly (clean exit, RP restored) so test.100 should too. If
the machine crashes anyway, that itself is a useful signal (different from
test.99's clean exit).

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.99 probe block (lines
  ~2516-2621) with test.100: 3-field wait-struct probes + control pointer
  re-reads at T+200/400/800ms. Drop the console ring dump (test.99 already
  read it; nothing changed).
- `phase5/work/test-staged-reset.sh` — labels test.99 → test.100, LOG
  filename test.99.stage${STAGE} → test.100.stage${STAGE}.

### After running test.100
- Map readings to the matrix above to choose next test.
- Common-case (A) follow-up = test.101 = D11 core wrapper bring-up via
  chip.c bus-ops (Path B step 1).
- (B) follow-up = offline-disasm fn 0x162fc continuation past 0x16332.
- (C) follow-up = test.101 = probe wl_probe sub-allocations (e.g. write a
  "breadcrumb" by reading r4 alloc result via TCM probe of wl_struct[+0x90]).

---

## Pre-test.99 state (2026-04-17, retained for context)

Git branch: main. Last pushed commit 75b52a1 (Post-test.99 doc).
Pending commit: offline disasm of c_init() + corrected freeze location.

**TEST.99 RESULT: firmware hard-frozen, no delayed code path, D11 obj still unlinked.**

Test.99 ran cleanly at 23:28:52–23:28:56 (boot -1, journal
`phase5/logs/test.99.journal`). "RP settings restored" — no host crash.

Pointer sample — **IDENTICAL across T+200/400/800ms**:
```
ctr[0x9d000]  = 0x000043b1    (static, matches test.89)
d11[0x58f08]  = 0x00000000    (D11 obj never linked — matches test.98)
ws [0x62ea8]  = 0x0009d0a4    (TCM ptr to static struct in BSS)
pd [0x62a14]  = 0x00058cf0    (vtable, matches test.93)
```
→ firmware is frozen by T+200ms with NO runtime change for the next 600ms.
Eliminates any "delayed DPC/ISR writes" hypothesis for these globals.

Console ring (256 bytes from 0x9ccc0): ChipCommon banner truncated. The
test.80 console captured the printed sequence:
ChipCommon → "wl_probe called" → "pciedngl_probe called" → **RTE banner**
(`RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz`)
then KATS fill — i.e. **freeze is AFTER the RTE banner print**, not at
"pciedngl_probe called" as earlier notes incorrectly stated.

### Offline disasm finding (2026-04-17, no hardware test)

`phase5/notes/offline_disasm_c_init.md` — full breakdown.

**`c_init()` lives at TCM 0x642fc.** Its literal pool (0x64540-0x6458c)
reveals the function's full call structure:

| Step | What c_init does | Observed? |
|------|------------------|-----------|
| 1 | Print RTE banner (format @ 0x6bae4, version @ 0x40c2f) | ✓ test.80 |
| 2 | Print `"c_init: add PCI device"` (@ 0x40c42) | ✗ |
| 3 | Store `*0x62a14 = 0x58cf0` (pciedngl_probe vtable) | ✓ test.99 |
| 4 | Print `"add WL device 0x%x"` (@ 0x40c61) | ✗ |
| 5 | Failure paths: `binddev failed` / `device open failed` / `netdev open failed` | ✗ none |

So execution definitely reaches step 3 (vtable populated). It does NOT
reach the failure paths. Freeze is between step 3 and the WL print, inside
either pciedngl_probe init or a subroutine called from c_init.

### Next decision (test.100) — three options

- (a) **Continue offline disasm** (free, no hardware test): trace c_init
  body 0x642fc–0x6453e (~322 bytes Thumb-2) to identify the exact BL after
  the vtable store. May pinpoint the failing subroutine without any
  hardware cycle.
- (b) **Wider/relocated console dump** to capture KATS region — earlier
  thought to surface post-RTE prints, but offline disasm shows step 4
  print only happens AFTER subroutine returns, so likely still empty.
- (c) **D11 BCMA wrapper reads** (Path B step 1) — requires chip.c bus-ops
  scaffolding; defer until offline disasm exhausts cheap progress.

**Recommend (a) first** — it is strictly free and may eliminate (b) and
narrow (c) to a specific D11 prereq.

**TEST.98 RESULT: step1 = TCM[0x58f08] = 0x00000000 → hang is in si_attach.**

Test.98 probe readings (from `phase5/logs/test.98.journal`, captured via
journalctl -b -1 after the module+script mismatch caused the stage0 log to be
labelled test.97 — raw partial preserved at `phase5/logs/test.98.stage0.partial`):

```
step1 = TCM[0x58f08] = 0x00000000 (D11_obj->field0x18)
step1 out of TCM range → D11_obj->field0x18 not set
(si_attach didn't run / didn't reach D11 obj init)
counter T+200ms = 0x000043b1 RUNNING
counter T+400ms = 0x000043b1 FROZEN (stays frozen through 2s timeout)
clean exit — no host crash
```

**Interpretation:**
- Firmware DOES start and runs some early code (counter reaches 0x43b1).
- Firmware freezes by T+400ms — a very early freeze, well before the D11 PHY
  wait loop at fn 0x1624c (which is several function levels deep inside
  si_attach's D11 bring-up).
- The D11 object pointer at `*0x58f08` is NEVER populated, which means the
  D11 section of si_attach hasn't reached the point where it links its
  object into that global.
- Previous hypothesis — "hang in fn 0x16f60 AHB read" — is INCORRECT; the
  pointer-chain cannot be walked because its root entry is still 0.

**Revised root cause hypothesis:** si_attach cannot bring the D11 core up at
all. A prerequisite (reset/enable/clock/power/interrupt-routing) is not in
the state si_attach expects. Per GitHub issue #11 recommendation #3.

**Pivot: Path B — D11 core prerequisite checks (phase5_progress.md).**

### Revised interpretation (advisor input + test.89 context)

test.89 proved firmware actually freezes at T+12ms — not at T+200–400ms.
The counter at 0x9d000 is a static constant (0x43b1) written exactly once
by fn 0x673cc, not a running tick. Sequence is:

```
T+0ms:  ctr = 0                        (ARM released)
T+2ms:  ctr = 0x58c8c                  (intermediate write)
T+12ms: ctr = 0x43b1 + console init    (fn 0x673cc stores static; firmware
                                        hangs at this exact point)
T+12ms onward: nothing changes         (sharedram never writes)
```

Therefore:
- test.98 reading `*0x58f08 = 0` at T+200ms was taken ~188ms AFTER the real
  freeze. It is consistent with "hang is before D11 obj linkage" but DOES
  NOT pinpoint the hang to D11 init specifically.
- The proven hang location from earlier tests is
  `pciedngl_probe → 0x67358 → 0x670d8 → deep init`; the fn 0x16f60 / fn
  0x1624c chain was called-graph analysis, not execution evidence.
- Jumping straight to D11 BCMA wrapper reads is premature — we need better
  hang localisation first.

### test.99 plan — console ring + multi-timepoint pointer sampling

Goal: narrow the hang location using CHEAP, READ-ONLY probes before
committing to D11 BCMA wrapper reads (which add bus-ops scaffolding and
have a bigger blast radius if anything goes wrong).

Probes (stage0, all read-only BAR2 accesses):

1. **Console ring dump at T+400ms** (highest-signal probe).
   - Read 256 bytes of TCM starting at the console-text base. Decode as ASCII
     to text on the host side (skip unprintable bytes). If firmware printed
     an ASSERT, a function-entry trace, or any identifiable string past
     "pciedngl_probe called", hang location narrows to that call.
   - Base address: locate via `console_ptr[0x9cc5c]` — when firmware is
     running this holds a TCM pointer (e.g. 0x8009ccbe → text at 0x9ccbe).
     Walk back from there to the ring start if needed. (Test.94 already
     identified 0x9CCC0–0x9CDD8 as decoded console strings.)

2. **Multi-timepoint TCM-pointer sampling** at T+20ms, T+200ms, T+400ms,
   T+800ms (T+20ms is the first sample AFTER firmware freezes):
   - `*0x9d000` — the 0x43b1 static (sanity check freeze detection works).
   - `*0x58f08` — D11 obj `field0x18` (was 0 at T+200ms).
   - `*0x62ea8` — wait-struct pointer (was garbage/uninit in test.97).
   - `*0x62a14` — global seen in fn 0x2208 analysis (used by
     `pciedngl_probe` path).
   - If all four are identical across all timepoints → firmware is hard-
     frozen after T+12ms and none of these globals got populated.
   - If any change at T+200/400/800 → firmware has SOME delayed execution
     path (e.g. interrupt-context code, DPC) we haven't accounted for.

3. **Sharedram + fw_init re-check** at the same timepoints (already in the
   existing T+200ms scan; extend to finer granularity).

Implementation notes:
- Reuse existing stage=0 dispatch in `brcmf_pcie_exit_download_state()`.
- `brcmf_pcie_read_ram32()` is the safe TCM read path — reuse, don't write.
- Keep the re-mask loop structure intact (defeats 3s periodic events).
- NO chip.c bus-ops, NO D11 BCMA wrapper reads yet — push that to test.100
  if console + pointer sampling don't narrow the hang.

After test.99 reading:
- If console shows a text past "pciedngl_probe called" → hang is later than
  currently thought; analyse the printed text for the failing subsystem.
- If console is frozen at "pciedngl_probe called" and pointers unchanged →
  hang is in pciedngl_probe BEFORE any subsystem logs → proceed to test.100
  with D11 BCMA wrapper reads (Path B step 1).
- If pointers change between T+20 and T+800 → delayed code path exists;
  characterise which pointer moves and when.

### Files modified / state snapshot
- `PLAN.md` — refactored to phase-level view; Current Status updated for test.98.
- `phase5/notes/phase5_progress.md` — Path B section added; current state block
  updated with test.98 result.
- `phase5/logs/test.98.journal` — full kernel log for test.98 run (NEW).
- `phase5/logs/test.98.stage0.partial` — partial stage0 log (header only before
  the 23:02 shutdown; kept for provenance, not for analysis).
- `phase5/logs/test.97.stage0` — restored to pre-test.98 clean state.
- `phase5/work/drivers/.../pcie.c` — still has test.98 probes (pointer-chain
  reads). Needs rewrite for test.99 D11 wrapper reads before next run.
- `phase5/work/test-staged-reset.sh` — still labelled test.97. Needs update to
  test.99 labels + LOG filename before next run.

## test.96 RESULT: CRASHED after 6 words — HANG CONFIRMED at fn 0x1624c via binary analysis

**test.96 ran in boot -1. CRASHED after only 6 code words (0x5200-0x5214). No RP restore.**
**PIVOT: Used firmware binary directly — 6 TCM words matched binary exactly → binary == TCM image.**

**fn 0x5250 disassembled from binary = nvram_get() — NOT the hang:**
```
5250: push {r4, r5, r6, lr}
5252: r4 = r0 (NVRAM buffer), r6 = r1 (key string)
5256: cmp r1, #0; beq 0x529c     ; if key==NULL, return NULL
525c: bl 0x82e                   ; strlen(key) → r5
5292: r0 = r6; b.w 0x87d4        ; tail call → another nvram lookup
```
Simple NVRAM key string lookup. NOT a hardware polling loop. NOT the hang.

**Vtable data found in firmware binary:**
```
PCIe2 vtable (at 0x58c9c):
  [0x58c9c] = 0x1e91 → fn 0x1E90 (vtable[0])
  [0x58ca0] = 0x1c75 → fn 0x1C74 (vtable[1]) ← CALL 2

D11 vtable (at 0x58f1c):
  [0x58f1c] = 0x67615 → fn 0x67614 (vtable[0])
  [0x58f20] = 0x11649 → fn 0x11648 (vtable[1]) ← CALL 3
```

**fn 0x1C74 (Call 2 = PCIe2_obj->vtable[1]) — NOT the hang:**
```
1c74: push {r4, lr}
1c76: r4 = [r0, #24]     ; load sub-object
1c7c: bl 0xa30            ; printf
1c80: r3 = [r4, #24]     ; nested struct
1c86: r2 = [r3, #36]; r2 |= 0x100; [r3, #36] = r2  ; set bit 8
1c8c: pop {r4, pc}        ; return
```
Trivial: sets bit 8 in BSS struct field, returns 0. NOT the hang.

**fn 0x11648 (Call 3 = D11_obj->vtable[1]) → leads to hang:**
```
1166e: r0 = [r4, #8]
11670: bl 0x18ffc        ← D11 init → eventually hangs
1167e: bl 0x1429c        ; stub returning 0
11682: pop {r2, r3, r4, pc}
```

**fn 0x18ffc (D11 init, called from Call 3) → hang chain:**
```
19024: ldrb r5, [r4, #0xac]  ; init flag
19028: cbz r5, 0x1904e        ; if flag==0: full init path
1904e: bl 0x16f60             ← FIRST D11 SETUP CALL (if first-time init)
19054: bl 0x14bf8
...
1908e: bl 0x17ed4             ; (this fn sets field0xac=1 — marks init done)
```
Flag at [r4+0xac] is 0 on first call → takes full init path starting at 0x16f60.
fn 0x17ed4 (sets init flag) is NEVER REACHED because hang happens before it.

**fn 0x16f60 (first D11 setup) → calls PHY read/write loop:**
- Copies 5 PHY register offsets from 0x4aff8: {0x005e, 0x0060, 0x0062, 0x0078, 0x00d4}
- Runs 5-iteration loop calling fn 0x16476 (PHY read) then fn 0x16d00 (PHY write)
- fn 0x16476: `mov.w r2, #0x10000; b.w 0x1624c` → enters wait loop

**fn 0x1624c = CONFIRMED HANG LOCATION (hardware PHY completion wait loop):**
```
1624c: push {r3, r4, r5, lr}
1624e: r5 = *(0x16298) = 0x62ea8  ; global wait-struct pointer

[SETUP:]
16252: r3 = *0x62ea8               ; wait struct ptr
16258: r3->field24 = 1             ; set "in progress"
1625c: r3->field28 = 0             ; clear completion flag
1625e: b.n 0x16286

[WAIT CHECK LOOP:]
16286: r3 = *0x62ea8
16288: r2 = r3->field20            ; status flag
1628a: cmp r2, #1
1628c: bne → EXIT                  ; if field20 != 1: exit (cancelled)
1628e: r3 = r3->field28            ; completion flag
16290: cmp r3, #0
16292: beq → LOOP (0x16286)        ; if field28==0: keep waiting ← INFINITE LOOP HERE
16294: pop {r3, r4, r5, pc}        ; return when field28 != 0
```
**HANGS WHILE: field20==1 AND field28==0**
**EXIT WHEN: field20!=1 (cancelled) OR field28!=0 (D11 PHY operation complete)**
This is a semaphore/event wait. field28 must be set by D11 PHY completion ISR.
**If D11 ISR never fires → field28 stays 0 → infinite loop.**

Root cause: D11 core not powered/clocked, or its interrupt not routed, so ISR never fires.
Global 0x62ea8 is a wait-struct used by 40+ locations in firmware.

Log: phase5/logs/test.96.journal (only 6 code words captured before crash)

## test.94 RESULT: SURVIVED (vtable read), CRASHED in STACK-LOW at word 154

**test.94 ran in boot -1. Module survived vtable dump, crashed at word 154/192 of STACK-LOW.**
**VTABLE: VT[0x58cf4] = 0x1FC3 → hang function is at 0x1FC2 (Thumb). CONFIRMED.**

**Key findings from VTABLE dump (0x58CD0-0x58D40):**
- VT[0x58cd4] = 0x00058c9c (nested vtable/struct ptr)
- VT[0x58cd8] = 0x00004999 (function at 0x4998)
- VT[0x58cdc] = 0x0009664c (BSS data ptr)
- **VT[0x58cf4] = 0x00001FC3** → Call 1 function (blx r3 at 0x644dc) = 0x1FC2 (Thumb) ← HANG CANDIDATE
- VT[0x58cf8] = 0x00001FB5 → vtable[+8] fn at 0x1FB4
- VT[0x58cfc] = 0x00001F79 → vtable[+12] fn at 0x1F78
- VT[0x58d24] = 0x00000001, VT[0x58d28..0x58d3c] = small fn pointers (0x4167C-0x416E3)

**Disassembly of 0x1FC2 (from arm-none-eabi-objdump on test.87 bytes):**
```
1fc2:  mov  r2, r1
1fc4:  ldr  r1, [r0, #24]  ; r1 = obj->si_ptr (field+0x18)
1fc6:  mov  r3, r0          ; r3 = obj
1fc8:  ldr  r0, [r1, #20]  ; r0 = si_ptr->dev (field+0x14)
1fca:  mov  r1, r3          ; r1 = obj (restore)
1fcc:  b.w  0x2208          ; TAIL CALL → 0x2208
```
→ 0x1FC2 is a TRAMPOLINE, not the actual hang. Rearranges args and tail calls to 0x2208.

**0x1FB4 (vtable[+8]):** identical trampoline → b.w 0x235C
**0x1F78 (vtable[+12]):** real function, calls 0x2E70 and 0x7DC4

**Analysis of 0x2208 (the REAL init function):**
```
push.w {r0,r1,r4,r5,r6,r7,r8,lr}   ; 8 regs = 32 bytes stack frame
r7 = *0x232C = 0x00062A14           ; global state ptr
r4=arg0(obj), r6=arg1, r5=arg2
r3 = *0x62A14 = 0x58CF0             ; vtable/state ptr (from test.93)
if (r3 & 2): optional debug print
if r6==0 || r5==0: error path
...
r8 = 0
bl 0x1FD0           ; allocate 76-byte struct (malloc via 0x7D60)
obj->field12 = result
if (alloc failed): error path
r0 = *0x62A14 & 0x10                ; 0x58CF0 & 0x10 = 0x10 (SET!)
if bit4 NOT set: return early (0x231C)
r1 = *0x2350 (timer priority value)
r0 = 0
bl 0x5250           ; register timer/callback
if (r0 == 0): success path:
    r0 = *0x237c = 0x00000000 (NULL!)
    r6 = 0
    b.w 0x848       ; TAIL CALL → 0x848 = strcmp (C library, NOT hang — CONFIRMED test.95)
```

**0x1FD0 (struct constructor called by 0x2208):**
- mallocs 76 bytes via 0x7D60
- memsets to 0 via 0x91C
- field52 = 0x740 = 1856, field60 = 0x3E8 = 1000, field64 = 28, field68 = 12, field72 = 4
- These look like timer/retry parameters (period_ms, timeout_ms, max_retry)

**STACK-LOW findings (0x9C400-0x9CDFC, crashed at 0x9CDFC):**
- 0x9C400-0x9CC54: ALL STAK fill (0x5354414b) — 0x1454 bytes = 5.2KB unused
- 0x9CC58-0x9CDFC: console ring buffer + BSS data (NOT stack frames)
  - 0x9CC5C = console write ptr (0x8009CCBE)
  - 0x9CCC0-0x9CDD8 = decoded console strings
  - 0x9CC88 = 0x000475B5 (ODD → Thumb fn ptr at 0x475B4 in struct)
- Stack frames NOT yet read (need 0x9CE00-0x9D000 or higher)
- Crash at ~3.25s total (exceeding ~3s PCIe crash window)

## test.95 RESULT: CLEAN EXIT — 0x840-0xB40 ALL C RUNTIME LIBRARY

**test.95 ran in boot -2 (and boot -1). Both SURVIVED with "TIMEOUT — FW silent for 2s — clean exit".**
**CODE DUMP COMPLETE: 192 words at 0x840-0xB40 disassembled (test95_disasm.txt).**

**CRITICAL CORRECTION: 0x848 is NOT a hang site — it is the loop body of strcmp.**
The annotation "b.w 0x848 = likely actual hang location" was WRONG.

**Functions found in 0x840-0xB40:**
- 0x840-0x87a: `strcmp` — entry at 0x840 (b.n 0x848), loop at 0x842-0x856, exit at 0x858-0x87a
- 0x87c-0x916: `strtol`/`strtoul` — whitespace skip, sign handling, 0x prefix, base conversion
- 0x91c-0x968: `memset` — 4-byte aligned stores + byte tail
- 0x96a-0xa2e: `memcpy` — LDMIA/STMIA 32-byte blocks, `tbb` jump table
- 0xa30-0xaaa: console printf — 520-byte stack buffer, calls 0xfd8/0x7c8/0x5ac/0x1848
- 0xabc-0xafa: callback dispatcher — 5-entry loop, `blx r3` dispatch with flag masking
- 0xb04-0xb16: wrapper loading globals for 0xabc
- 0xb18-0xb3f: heap free — adjusts accounting, walks linked list

**0xa4c was wrongly annotated** — it is in the MIDDLE of console printf at 0xa30, not a cleanup fn.

**Call chain from 0x2208:**
  bl 0x5250 (timer/callback reg) → succeeds → b.w 0x848 (tail call into strcmp)
  strcmp completes in microseconds. HANG IS ELSEWHERE.

**si_attach disasm (test91_disasm.txt, 0x64400-0x64ab8):**
- Function at 0x644??-0x64536: contains 3 vtable dispatches
  - Call 1 (0x644dc): *(*(0x62a14)+4) — obj vtable ptr at offset 0 → vtable[1]
  - Call 2 (0x644fc): r6=0x58cc4, ldr r3,[r6,#16] → vtable ptr at obj+16 → vtable[1]  
  - Call 3 (0x6451a): r7=0x58ef0, ldr r3,[r7,#16] → vtable ptr at obj+16 → vtable[1]
- si_attach at 0x64590: EROM-parsing loop, calls 0x2704 (EROM parser) for each core

## test.97 RESULT: fn 0x1624c never ran — hang is earlier
(See full analysis in "Current state" section above. Journal: phase5/logs/test.97.journal)

## test.98 PLAN: Pointer-chain reads to confirm D11 bus hang at fn 0x16f7a

**Goal:** Walk pointer chain at T+200ms to find hw_base_ptr and determine if it's a hardware addr.
Chain: TCM[0x58f08] → +8 → +0x10 → +0x88 → check if ≥ 0x18000000.
Also: stack probe 0x9FE00-0x9FF00 for LR=0x19054 (fn0x18ffc→fn0x16f60) and LR=0x11674.

**Expected results:**
- If step4 >= 0x18000000 → D11 bus hang confirmed. Next: pre-enable D11 core.
- If step4 == 0 → hang even earlier; need to trace si_attach D11 core init.
- If step1 == 0 → D11_obj->field0x18 not set; si_attach didn't initialize D11 obj.

## Run test.98 (to be built):
  cd /home/kimptoc/bcm4360-re/phase5/work && make && sudo ./test-staged-reset.sh 0

## test.93 RESULT: SURVIVED (both runs) — vtable pointer decoded, stack top is NVRAM

**test.93 ran twice (boot -2 at 12:02, boot -1 at 12:10), BOTH SURVIVED.**
Both showed "TIMEOUT — FW silent for 2s — clean exit" and "RP settings restored".

**Key findings from D2 (DATA-62A14) dump:**
- D2[0x62a14] = 0x00058cf0 → vtable pointer for Call 1 (blx r3 at 0x644dc)
- Vtable is at TCM[0x58cf0]; entry [+4] = TCM[0x58cf4] = function pointer for Call 1
- D2[0x62994] = 0x18000000 (ChipCommon base — confirms si_t struct location)
- D2[0x62ab0] = 0x58680001 (chipcaps — matches si_t from console output)
- D2[0x62ad4] = 0x00004360 (chip_id = BCM4360 ✓)
- D2[0x62ad8] = 0x00000003 (chip_rev = 3 ✓)
- D2[0x62ae0] = 0x00009a4d (chipst ✓)

**Key findings from SK (STACK-TOP) dump [0x9F800-0xA000]:**
- 0x9FF1C–0xA0000: NVRAM data ("sromrev=11\0boardtype=0x0552\0boardrev=0x1101\0...")
- 0x9F800–0x9FF1B: random/uninitialized data — NO Thumb LR values in TCM code range
- CONCLUSION: 0x9F800–0xA000 is NOT active stack. Active frames are near STAK fill at 0x9C400.

**What remains unknown:**
- TCM[0x58cf4] = ??? (the actual function being called — not yet read)
- Stack LR values (to confirm call depth and which vtable call hangs)

Log: phase5/logs/test.93.journal

## test.92 RESULT: SURVIVED — STAK fill confirmed above 0x9BC00; EROM parser analyzed

**test.92 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**Stack dump 0x9BC00-0x9C400: ENTIRELY STAK (0x5354414b)**
- Active stack frames are ABOVE 0x9C400
- Stack grows down from 0xA0000; estimated SP ~0x9F800
  (860-byte zeroed struct in 0x670d8 frame + si_attach 60-byte frame + others)

**EROM parser function at 0x2704 (0x2600-0x2900 dumped):**
- Simple loop: loads EROM entries sequentially from TCM, returns when match found
- r1 = &ptr, r2 = mask (or 0), r3 = match value
- NO infinite loops, NO hardware register reads
- CANNOT be the hang location

**Function structure at 0x27ec (core registration, vtable call):**
- `blx r3` at 0x2816 calls a vtable function (potential hang candidate)
- But this is called by si_attach (0x64590) during core enumeration

**Key insight: Vtable calls are in a function BEFORE si_attach in TCM:**
- From test.91 dump (0x64400-0x6458c area):
  - `bl 0x63b38` with r1=0x83c → looks up PCIe2 core object → r6
  - `bl 0x63b38` with r1=0x812 → looks up D11/MAC core object → r7
  - If both found: three vtable calls follow:
    - Call 1 (0x644dc): via [0x62a14][4], args=(PCIe2_obj, D11_obj)
    - Call 2 (0x644fc): PCIe2_obj->vtable[1](), if Call 1 succeeds
    - Call 3 (0x6451a): D11_obj->vtable[1](), if Call 2 succeeds

**test.92 hypothesis: hang is in one of the three vtable calls (PCIe2 or D11 core init)**

Log: phase5/logs/test.92.journal
EROM disasm: phase5/analysis/test92_erom_disasm.txt

## test.90 RESULT: SURVIVED — 0x670d8 disassembled; 0x64590 is next hang candidate

**test.90 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**function 0x670d8 fully disassembled (1344 bytes, 0x66e00-0x67340):**
- Entry: `stmdb sp!, {r0-r9, sl, lr}` (pushes 12 registers)
- Loads 7 args (3 from regs r0/r1/r2/r3, 4 from stack [sp+48..+56])
- memset: zeroes 860 bytes (0x35c) from r4 (the init struct)
- Stores initial values into struct offsets
- Calls 0x66ef4 (tiny function: returns 1 always) — never hangs
- At 0x67156: `mov.w r9, #0x18000000` (ChipCommon base!)
- At 0x6715c: `ldr.w r1, [r9]` = reads ChipCommon chip_id register
- Extracts chip_id, numcores, etc. from register
- **At 0x67190: `bl 0x64590` — FIRST DEEP CALL, likely hang point**
  - Args: r0=struct_ptr, r1=0x18000000 (ChipCommon), r2=r7
  - This is likely `si_attach` or `si_create` (silicon backplane init)
- After return: checks [struct+0xd0] — if NULL, error exit
- If non-NULL: calls 0x66fc4 (function in our dump, enumerates cores)
  - 0x66fc4 loops through [struct+0xd0] cores calling 0x99ac, 0x9964
  - Returns 1 (success) after loop

**call chain established:**
- pciedngl_probe → 0x67358 → 0x672e4 (wrapper) → 0x670d8 → 0x64590

**0x64590 not in dump (below 0x66e00) — MUST DUMP NEXT**
**0x66fc4 analyzed: core-enumeration loop, returns 1 on success**

Disassembly: phase5/analysis/test90_disassembly.txt
Log: phase5/logs/test.90.journal

## test.89 RESULT: SURVIVED — 0x43b1 is STATIC constant (stored once, not incremented)

**test.89 ran in boot -1. Key findings from fast-sampling:**
1. T+0ms: ctr=0x00000000 (ARM just released)
2. T+2ms: ctr=0x00058c8c (CHANGED — firmware running, some intermediate value)
3. T+10ms: ctr=0x00058c8c (held for 8ms)
4. T+12ms: ctr=0x000043b1 AND cons=0x8009ccbe (BOTH changed simultaneously)
5. T+20ms+: ctr=0x000043b1 FROZEN, cons frozen, sharedram=0xffc70038 NEVER changes

**RESOLVED: 0x43b1 IS a static constant, NOT a counter**
- Function at 0x673cc returns MOVW R0, #0x43b1 → firmware stores it to 0x9d000
- Previous "WFI-disproof" based on frozen counter was INVALID for values at T+200ms
- BUT firmware IS genuinely hung: sharedram NEVER changes (even at 2s+)
  - PCI-CDC firmware WOULD write sharedram on successful init
  - Never changing = TRUE HANG, not WFI idle

**TIMELINE reconstructed:**
- T+0ms: ARM released, TCM[0x9d000]=0
- T+2ms: firmware stored 0x58c8c to 0x9d000 (some intermediate init value)
- T+10ms: still 0x58c8c (firmware executing init code)
- T+12ms: firmware stored 0x43b1 to 0x9d000 (function 0x673cc result) AND initialized console
- T+12ms+: EVERYTHING FROZEN — firmware hung at this exact point
  - Console write ptr = 0x8009ccbe = TCM[0x9ccbe] (same as all previous tests)
  - Last message = "pciedngl_probe called" (same as test.78-80 decode)
  - Hang occurs inside pciedngl_probe → 0x67358 (TARGET 1) → 0x670d8 (deep init)

**NEXT: disassemble 0x670d8** — the only unexamined function in the call chain
Log: phase5/logs/test.89.journal

## test.91 RESULT: CRASHED at word 431 — partial si_attach disassembly obtained

**Crash cause:** Unmasked 1280-word code dump loop; at ~7ms/word, 431 × 7ms ≈ 3s hit PCIe crash window.

**Partial disassembly (431 words, 0x64400-0x64ab8) — key findings:**
- **0x64590 (si_attach):** reads ChipCommon+0xfc = EROM pointer register
- Immediately branches to EROM parse loop, calls fn at **0x2704** (EROM entry reader)
- **Vtable dispatch calls at 0x644dc and 0x644fc** (`blx r3`) — these init individual backplane cores
  → Most likely hang points: one core's init fn reads backplane registers for a powered-off core

**Stack location corrected:** STAK marker at 0x9BF00 (from test.88) → active frames near 0x9BC00.

Log: phase5/logs/test.91.journal
Dump: phase5/analysis/test91_dump.txt (431 words: 0x64400-0x64ab8)

## test.88 RESULT: CRASHED cleanup — but all data obtained

**test.88 ran in boot -1 (also partial in boot -2). Key findings:**
1. All three call targets disassembled — NO infinite loops, CPSID, or WFI in any
2. TARGET 1 (0x67358): alloc + calls 0x670d8 (deep init) — most likely hang location
3. TARGET 2 (0x64248): struct allocator (0x4c bytes), returns — clean
4. TARGET 3 (0x63C24): registration function, returns 0 — clean
5. **CRITICAL: Function at 0x673cc returns constant 0x43b1** — same value as "frozen counter"
6. Stack scan 0x9F000-0x9FFF8: mostly zeros, no dense return address cluster
7. "STAK" marker at 0x9bf00 — stack region may be near 0x9c000
8. Counter: T+200ms=0x43b1 (RUNNING), T+400ms=FROZEN
9. CRASHED during cleanup (no RP restore messages)

Full disassembly: phase5/analysis/test88_disassembly.txt

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL → writing during init CRASHES ✗ (test.71/74)
- Firmware prints: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75-80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- select_core after firmware starts → CRASH ✗ (test.66/76 PCIe2, test.86 ARM CR4)
- Core switching after FW start CONFIRMED LETHAL across ALL core types ✗ (test.66/76/86)
- WFI theory DEAD: frozen counter = TRUE HANG, not WFI idle (WFI keeps timers running) ✗
  UPDATE: counter at 0x9d000 is STATIC value (not a counter) — set once to 0x43b1
  BUT: sharedram NEVER changes = firmware NEVER completes init = GENUINE HANG ✓
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- Counter freezes at 0x43b1 between T+200ms and T+400ms — hang is VERY early ✓ (test.87)
- TCM top = 0xA0000 (640KB), stack grows down from there ✓ (test.87 TCB)
- pciedngl_probe calls into 0x67358, 0x64248, 0x63C24 — hang is inside one of these ✓ (test.87 disasm)
- All 3 call targets have NO infinite loops, CPSID, or WFI ✓ (test.88 disasm)
- TARGET 1 (0x67358) calls 0x670d8 (deep init) — most likely hang location ✓ (test.88)
- 0x670d8 calls si_attach (0x64590) which dispatches vtable calls ✓ (test.90)
- si_attach vtable fn at 0x1FC2 = TRAMPOLINE → tail calls 0x2208 ✓ (test.94 disasm)
- 0x2208 allocates struct, calls 0x5250, then tail calls 0x848 ✓ (test.94 disasm)
- 0x848 = strcmp (C runtime), NOT the hang ✓ (test.95 disasm)
- fn 0x5250 = nvram_get() (NVRAM key lookup), NOT the hang ✓ (test.96 binary disasm)
- Call 2 (fn 0x1C74) = trivial bit-set, returns 0, NOT the hang ✓ (test.96 binary disasm)
- Call 3 (fn 0x11648) → fn 0x18ffc → fn 0x16f60 → fn 0x1624c = CONFIRMED HANG ✓ (test.96 binary analysis)
- fn 0x1624c = hardware PHY completion wait loop at global 0x62ea8 ✓
- Loop spins while (*0x62ea8)->field20==1 AND field28==0 ✓
- field28 set by D11 PHY ISR — ISR never fires → infinite loop ✓ (hypothesis)
- D11 PHY register offsets in loop: 0x005e, 0x0060, 0x0062, 0x0078, 0x00d4 (from 0x4aff8) ✓
- Firmware binary matches TCM image exactly (6 words verified) — safe for offline disassembly ✓
- fn 0x1624c NEVER RAN at T+200ms — wait struct fields all garbage (uninitialized) ✓ (test.97)
- fn 0x16476 tail-calls fn 0x162fc (NOT fn 0x1624c) ✓ (corrected from binary)
- fn 0x16f60 @ 0x16f7a does hardware read BEFORE calling fn 0x16476 — AHB hang candidate ✓
- Stack frames are near 0x9FE40 (not 0x9CE00 which is console ring buffer) ✓ (test.97)

## Console text decoded (test.78/79/80/82/83/84 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (static value, set once at T+12ms then firmware freezes)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.95.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.85: CRASHED T+18-20s — STATUS/DevSta cleared, firmware STILL hung; STATUS theory DEAD
- test.86: CRASHED T+2s — ARM core switch (select_core) crashed immediately; core switch LETHAL
- test.87: SURVIVED — counter froze T+200-400ms at 0x43b1; pciedngl_probe disassembled; code dumps obtained
- test.88: CRASHED cleanup — all 3 targets disassembled; NO loops/CPSID/WFI; 0x673cc returns 0x43b1 constant; 0x670d8 is next suspect
- test.89: SURVIVED — 0x43b1 is STATIC (stored once at T+12ms); WFI-disproof RESOLVED; sharedram confirms TRUE HANG
- test.90: SURVIVED — 0x670d8 fully disassembled; calls si_attach (0x64590) at 0x67190; NO loops
- test.91: CRASHED at word 431 — partial si_attach (0x64590) dump; vtable dispatch at 0x644dc
- test.92: SURVIVED — STAK extends 0x9BC00-0x9C400; EROM parser at 0x2704 is benign
- test.93: SURVIVED (×2) — D2[0x62a14]=0x58CF0 (vtable ptr); sk[0x9F800]=NVRAM (not stack)
- test.94: SURVIVED vtable, CRASHED STACK-LOW at ~3.25s — VT[0x58cf4]=0x1FC3; 0x1FC2→0x2208→0x848
- test.95: SURVIVED — 0x840-0xB40 = C runtime (strcmp, strtol, memset, memcpy, printf); 0x848 = strcmp NOT hang
- test.96: CRASHED after 6 words — pivoted to firmware binary analysis; fn 0x1624c confirmed as hang location
- test.97: CRASHED (machine crash) — wait struct fields = garbage → fn 0x1624c never ran; hang is earlier; corrected: fn 0x16476 → fn 0x162fc (not fn 0x1624c directly)

## POST-test.109 (2026-04-17) — probe wedges BEFORE enum block executes

### Result: skip_arm=1, reached "rambase=0x0 ramsize=0xa0000 ... fw_size=442233" then STOP
Log `phase5/logs/test.109.stage0` shows driver path through `brcmf_pcie_reset_device`
(EFI state, PMU, pllcontrol[0..5], test.40 watchdog msg all present — lines 72-80
of log) and `brcmf_fw_alloc_request` + firmware file resolution (line 81-85),
but NOTHING after the `rambase=` debug line. System crashed after "Capture
complete" — no test.101 pre-ARM baseline, no test.109 enum lines, no skip_arm
message, no "Cleaning up brcmfmac".

### Root cause (advisor-confirmed)
Probe thread wedges in `brcmf_pcie_copy_mem_todev` at pcie.c line ~1803, which
writes the 442KB firmware via ~110K iowrite32 calls. ONE posted write that never
completes wedges the probe thread indefinitely.

All downstream code in `brcmf_pcie_download_fw_nvram` is unreachable, including:
- "NVRAM loaded" log (test.108 reached this; test.109 did not)
- test.101 pre-ARM baseline (dev_emerg at line 1883)
- test.109 enum block (lines 1890-1929)
- bcm4360_skip_arm branch (line 1932)

Verified NOT a dmesg-timing artifact by comparison with `journalctl -b -1` which
also stops at same point.

### test.110 plan — move enum to brcmf_pcie_reset_device (pre-FW-download site)
Reset_device already ran successfully in test.109 (EFI/PMU/pllcontrol lines
captured in log). Inserting the 11-slot enum there after the "test.40: allowing
watchdog reset" log line runs the enum BEFORE copy_mem_todev, so the wedge
cannot block it.

Code change (pcie.c):
- ADD: 11-slot enum block inside reset_device's BCM4360 branch, after
  "test.40: allowing watchdog reset" dev_info, before fall-through
- REMOVE: old enum block in download_fw_nvram (unreachable)
- bcm4360_skip_arm=1 retained as safety (unrelated path, avoids ARM release)

Build verified (pcie.c compiles, brcmfmac.ko linked). Ready to run.

### Test run
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected output (stage 0 log):
- EFI state / PMU / pllcontrol lines (same as test.109)
- NEW: "BCM4360 test.110: backplane core enumeration (slot+0 only, 11 slots)"
- NEW: 11 lines "BCM4360 test.110: slot[0xNNNNNNNN] off0=0x........"
- NEW: "BCM4360 test.110: enum complete, BAR0 restored"
- Then probe continues into FW download → wedges at copy_mem_todev (expected)
- System should NOT crash; dmesg capture should include all enum lines

Success criteria: ≥11 enum lines present in dmesg ring buffer.
Failure mode: if system crashes at enum, BAR0 writes are dangerous pre-probe.

## POST-test.110 (2026-04-17) — HARD CRASH, pivot from raw BAR0 sweep

### Result: kernel panic / full host crash, zero log lines persisted
Log `phase5/logs/test.110.stage0` captured only pre-test lspci state; nothing
from the driver's probe path reached disk. Enum block in `brcmf_pcie_reset_device`
that performed an 11-slot raw BAR0 window sweep (`pci_write_config_dword` on
BRCMF_PCIE_BAR0_WINDOW for each slot base, then ioread32 at window+0) was the
trigger — one of those writes wedged the bus so hard the whole machine died
instantly, no journald flush, no kmsg tail.

### Root cause
Raw BAR0 window writes in a tight loop, before any of the driver's usual
serialization (spinlocks, msleep barriers) hit unmapped / uninitialized /
powered-down backplane ranges. Even touching unassigned wrappers on BCMA
SOCI_SB can trigger a bus hang that SERR's the root port. We already saw
related fragility in tests 66/76/86 (post-ARM select_core = lethal); a
pre-ARM raw sweep of slot bases is the same class of hazard with more reads.

### Pivot (test.111)
By the time `brcmf_pcie_reset_device` runs, `brcmf_chip_recognition` has
already populated `ci->cores` (chip.c:1043-1049). We can walk that list
instead of touching MMIO — `brcmf_chip_get_core(ci, coreid)` returns the
registered core struct with id/base/rev. Zero new MMIO, zero hang risk.

## POST-test.111 (2026-04-17) — FW HANG TARGET IDENTIFIED

### Result: clean enum, FW hang target = d11 MAC @ 0x18001000
Log `phase5/logs/test.111.stage0` shows:
```
BCM4360 test.111: id=0x800 CHIPCOMMON   base=0x18000000 rev=43
BCM4360 test.111: id=0x812 80211        base=0x18001000 rev=42  <<< FW HANG TARGET
BCM4360 test.111: id=0x83C PCIE2        base=0x18003000 rev=1
BCM4360 test.111: id=0x83E ARM_CR4      base=0x18002000 rev=2
(INTERNAL_MEM, PMU, ARM_CM3, GCI, DEFAULT all NOT PRESENT)
```
Combined with test.106 evidence (fn 0x1415c spin-polls `*0x180011e0` in FW),
the hang is FW polling d11 MAC core's **clk_ctl_st register** (d11+0x1e0) for
CCS_BP_ON_HT (bit 19) which never sets because HT clock / BBPLL is off.

### Register semantics (from include/chipcommon.h and brcmsmac/aiutils.h)
- offset 0x1e0 = `clk_ctl_st`
- bit 1  = CCS_FORCEHT (driver/FW requests HT clock)
- bit 17 = CCS_HAVEHT (HT clock available)
- bit 18 = CCS_BP_ON_ALP (backplane running on ALP)
- bit 19 = CCS_BP_ON_HT (backplane running on HT) ← FW polls this

Same register layout exists on every core's wrapper; ChipCommon and d11 both
expose clk_ctl_st at +0x1e0. FW's choice to poll d11's copy (not CC's) means
the FW sees its core's clock view, not the chip-global view. But PMU grants
affect the whole backplane.

## Phase 5 CLOSED (2026-04-17)

Chain of evidence now complete:
1. test.87-96:  FW hangs inside pciedngl_probe → si_attach → ... → fn 0x1624c
2. test.106:    offline disasm — fn 0x1415c spin-polls `*0x180011e0`
3. test.111:    0x18001000 = d11 MAC core (BCMA_CORE_80211 id=0x812, rev=42)
4. d11+0x1e0 = d11.clk_ctl_st; FW waits for CCS_BP_ON_HT
5. test.40 EFI dump: clk_ctl_st=0x00010040 → HAVEALP=1, HAVEHT=0, BP_ON_HT=0

EFI left BCM4360 on ALP clock (32MHz). FW needs HT clock (PLL lock) for d11
PHY. Phase 6 goal: make HT clock come up before FW starts. This is a PMU /
BBPLL bring-up problem, not a driver reset or FW-loader problem.

## POST-test.112 (2026-04-17) — CC FORCEHT set BP_ON_ALP, not HT

### Result: FORCEHT persisted on CC, but PMU did not grant HT
Log `phase5/logs/test.112.stage0` (line 92-94):
```
pre-force CC.clk_ctl_st=0x00010040 (HAVEALP=1 HAVEHT=0 BP_ON_HT=0)
wrote CCS_FORCEHT (bit 1) to CC.clk_ctl_st, polling for CCS_BP_ON_HT...
after 100×100us: clk_ctl_st=0x00050042 pmustatus=0x0000002a res_state=0x0000013b -- HT TIMEOUT
```
Delta: 0x00010040 → 0x00050042.
- bit 1 (CCS_FORCEHT) now set (written by us): good
- bit 18 (CCS_BP_ON_ALP) appeared: ALP still granted
- bit 17 (CCS_HAVEHT), bit 19 (CCS_BP_ON_HT): still 0
- pmustatus=0x2a, res_state=0x13b: UNCHANGED from EFI baseline

Reading: PMU accepted that CC wants ALP and left it there. PMU did not
interpret CC FORCEHT as a request for HT/BBPLL.

### Three candidate blockers (advisor-identified)
1. **Wrong core** — FW polls d11.clk_ctl_st, so CC FORCEHT may not
   propagate to d11. Test next: write FORCEHT to d11.clk_ctl_st directly.
2. **Resource mask ceiling** — max_res_mask=0x13f, min_res=0x13b,
   res_state=0x13b. Max-res only adds bit 2 (0x4), and nobody requests
   it. Likely not the blocker (min_res is), but max_res shotgun rules
   it in/out cheaply.
3. **pllcontrol unset** — pllcontrol[0]=0, pllcontrol[1]=0. EFI left
   BBPLL frequency config blank. No amount of FORCEHT will lock a PLL
   with no divider config.

Advisor reviewed pre-commit: test (c) (max_res shotgun) is almost certainly
going to fail — res_state=0x13b = min_res, and widening max_res doesn't
force a request. If steps (b) and (c) both fail, test.114 should widen
**min_res_mask** (e.g. set bit 2 or discover HT-related bits), not jump
straight to pllcontrol programming.

## PRE-test.113 (2026-04-17) — d11 FORCEHT + max_res discriminator

### Code change (pcie.c, brcmf_pcie_reset_device BCM4360 branch)
ADD new test.113 block AFTER the existing test.112 CC FORCEHT block:

Step (a): `brcmf_pcie_select_core(BCMA_CORE_80211)`, read `regs+0x1e0`
          → baseline d11.clk_ctl_st

Step (b): `brcmf_pcie_write_reg32(regs+0x1e0, baseline | 0x2)` — FORCEHT
          poll d11.clk_ctl_st for bit 19 (BP_ON_HT), 100×100us = 10ms
          switch to CC, read pmustatus/res_state/pllcontrol[0..5]
          → if HT up: theory 1 wins (d11 is right core)

Step (c): (if step b failed) save max_res, write max_res=0xFFFFFFFF
          poll CC.clk_ctl_st for bit 19, 100×100us = 10ms
          re-read pmustatus/res_state/pllcontrol[0..5]
          → if HT up: theory 2 wins (max_res was blocking)

Step (d): restore max_res_mask to saved value (do not leave wide open)

Safety:
- brcmf_pcie_select_core() is the same path driver uses elsewhere; NOT
  the raw BAR0 sweep that crashed test.110
- skip_arm=1 retained — FW not running, no write/read race at 0x180011e0
- Existing test.112 block LEFT IN PLACE — CC FORCEHT already showed no
  effect on PMU, so leaving it set doesn't interfere with d11 writes

### Expected outcomes
- Most likely: step (b) fails (d11 is just another wrapper, PMU indifferent)
  → step (c) runs → also fails (min_res not max_res is the ceiling)
  → test.114 = widen min_res_mask or program pllcontrol[0]/[1]
- Small chance: step (b) succeeds → "PMU needed FORCEHT from the core
  that will consume HT (d11)" → driver fix = add d11 FORCEHT to reset path
- Small chance: step (c) succeeds → max_res really was the ceiling →
  driver fix = widen max_res_mask before ARM release

pllcontrol re-reads (added per advisor): after each poll loop, re-read
pllcontrol[0..5]. If any transition from 0 to non-zero between baseline and
step (b)/(c), PMU did touch PLL config. If all stay at [0, 0, 0xc31,
0x133333, 0x06060c03, 0x000606] throughout, theory 3 (PLL programming
genuinely missing) is strongly confirmed.

### Run
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

### Success criteria
- No crash
- Log contains test.113 step-a baseline line
- Log contains test.113 step-b result (HT UP or rejected)
- If step (c) ran, log contains step-c result + step-d restore line
- Clean "test.113: complete" line
- Module cleanly removed (`rmmod brcmfmac` succeeds)

### Failure signatures
- Host crash during step (a) read at d11+0x1e0  → d11 wrapper is already
  hung or powered down; cannot force HT from that core. Implies max_res
  or pllcontrol as only remaining path.
- Host crash during step (c) max_res write        → writing 0xFFFFFFFF to
  max_res_mask while FORCEHT is active destabilizes PMU. Back off to
  specific bit probes instead of shotgun.
- Log stops mid-probe                              → a specific read/write
  hangs the bus; narrow down which step; retry with fewer probes.

---

## TEST.127 EXECUTION — 2026-04-19 (session restart, after crash recovery)

### Pre-test state
- Module rebuilt: Apr 19 00:07 (test.127 pcie.c markers in place)
- Build status: clean, no rebuild markers needed
- PCIe state: clean (MAbort-, CommClk+)
- test.126 crashed during insmod before any markers printed

### Hypothesis (test.127 stage0)
test.126 crashed during insmod before ANY test markers printed. Crash is likely:
- Before brcmf_pcie_probe is called (module load error)
- Or in probe entry before first pr_emerg marker (line ~3871)

test.127 adds pr_emerg markers at:
1. Start of brcmf_pcie_probe (after device ID check)
2. After devinfo kzalloc
3. After devinfo->pdev assignment

**Expected outcome:** markers will show exactly where the crash occurs.

### Running test.127 stage0
Command: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`


---

## TEST.127 EXECUTION PLAN (2026-04-19 session restart)

### State
- Module rebuilt Apr 19 00:07
- PCIe state clean
- test.126 crashed during insmod before any markers

### Hypothesis
Crash occurs before brcmf_pcie_probe starts or very early in probe entry,
before the first test marker at line ~3871.

### Markers added (pcie.c)
1. pr_emerg: Start of brcmf_pcie_probe (device ID check)
2. pr_emerg: After devinfo kzalloc
3. pr_emerg: After devinfo->pdev assignment

Expected: markers will show exactly where crash occurs.

### Test command
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

### Git status
M phase5/logs/test.126.stage0 (from prior test, now clean)

---

## SYSTEMATIC DEBUGGING — Session 2026-04-19 (after crash recovery)

### Evidence Summary
**Pattern:**
- test.109-114: Various diagnostic tests, test.114 completed stage0/stage1
- test.115+: ALL crash during insmod, before any probe markers  
- test.126/127: Still crashing at identical boundary (insmod → crash, no output)

**File sizes (bytes):** 
- Working tests (109, 111, 112, 114): >5000 bytes
- Crashing tests (115-127): ~3650 bytes (just preamble, nothing after "=== Loading brcmfmac...")

### Root Cause Investigation (Phase 1)

**Fact 1: Crash is in module load, not probe**
- insmod call in test script crashes system
- Probe markers at line 3836+ never execute
- No dmesg output captured (script didn't reach capture point)
- System appears to hard panic during insmod

**Fact 2: crash is not from unsafe d11.clk_ctl_st reads**
- unguarded ioread32(devinfo->regs + 0x1e0) at line 2752 is AFTER ARM release
- stage 0 has bcm4360_skip_arm=1, returns at line 1946 before ARM release
- Therefore test.67-107 code never executes in stage 0
- The crash is happening MUCH earlier than that code

**Fact 3: Stage 0 should be minimal and safe**
- SBR at probe entry (line 3879-3896)
- chip_attach via brcmf_chip_attach (line 3898)
- module param setup (line 3933-3949)
- SKIP_ARM=1 return at 1946

**Fact 4: Test.109 baseline was safe**
- test.109 committed "enum moved before skip_arm; skip_arm=1 to avoid crash"
- Commit e590e51 shows test.109 was the baseline for stage 0 safety
- test.115 onward ALL crash

### Search for Regression Between test.114 and test.115

Looking at commit history:
- test.114d (e731310): "skip watchdog write, add 3a discriminator marker"
- Post-test.114d crash message: "chip_attach MMIO dead, power cycle required"
- test.115 (2f3c12a): "remove resetcore from test.114b"
- But test.114b was stage1 (ARM released), test.115 stage0

### HYPOTHESIS: Module Binary Corruption or Build Issue

Since test.109 was safe and test.115+ ALL crash at identical point (before probe), possibility:
1. **Kernel module ABI mismatch** — kbuild/kernel changed, module can't load
2. **Linking failure** — module binary is corrupted or circular dependency
3. **Hardware state** — PCIe/IOMMU permanently corrupted from test.114d crash

### Next Steps (Phase 1 → Phase 2)
1. **Verify module binary is valid**
   - Check module dependencies: `modinfo ./brcmfmac.ko | grep depends`
   - Try loading on clean kernel boot
   - Compare binary size/symbols with test.109 baseline build

2. **Check for kernel/module ABI changes**
   - `uname -r` kernel version
   - Compare module compilation flags
   - Try rebuild with test.109 exact code: `git show e590e51:drivers/.../pcie.c > /tmp/pcie109.c`

3. **Establish Hardware Clean State**
   - Full power cycle (battery drain) if MMIO is corrupted
   - Current MMIO test: UR/I/O error in 6ms (fast, expected) ✓

### Immediate Action: Revert to test.109 Build

Safest fast path to understand crash:
```bash
git stash
git checkout e590e51
make -C phase5/work
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

If test.109 commit works → regression introduced test.110-114
If test.109 also crashes → hardware corruption from earlier crash

---

## DIAGNOSTIC: Fresh rebuild of current code (2026-04-19 post-crash)

### Hypothesis
Tests 116+ all crash during insmod before probe markers.
Fresh rebuild of current code to isolate:
1. Is it a stale module binary issue?
2. Is it a code regression since test.109?

### Current State
- Branch: main (e4a5097)
- Fresh rebuild completed successfully
- About to run: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`
- Expected: either the crash reproduces OR system recovers (no crash)

### test.127 RESULT: CRASHED during insmod (kernel panic) — system recovered via watchdog

**test.127 ran at 2026-04-19 00:54. Module crashed the kernel during insmod, before any probe output. System recovered cleanly.**

**Crash signature (same as test.116-126):**
- Log ends with: `=== Loading brcmfmac (bcm4360_reset_stage=0, bcm4360_skip_arm=1) ---`
- No `insmod returned rc=` output (script halted)
- No probe markers (test.114b code never ran)
- Kernel panic → automatic watchdog recovery

**Evidence the crash is in module load, not probe:**
- insmod call at line 121 of test-staged-reset.sh never returns
- Proof: script sets `set +e` at line 120 to capture RC, but never logs it
- If probe had run, dev_info lines from pcie.c would appear before the crash
- None appear → crash happens in module initialization, before probe entry

**Regression timeline (test.109 working → test.115+ crashing):**
- test.109 (commit e590e51): "enum moved before skip_arm; skip_arm=1 to avoid crash"
  + Baseline safe state, module loads cleanly
- test.110-114: Various diagnostic code added (core enum, d11 wrapper reads, d11 forceht)
- test.115 (commit 2f3c12a): "remove resetcore from test.114b — pure diagnostic control"
  + First crash observed
  + ALL subsequent tests (116-127) crash identically

**Key observation:**
- The code between test.109 and test.115 looks safe (mostly diagnostic reads)
- But the crash is happening BEFORE the probe function entry
- This means either:
  1. **Module initialization** (module_init or static initializers) has unsafe code
  2. **Kernel module ABI** changed (kbuild/kernel incompatibility)
  3. **Symbol resolution failure** causes a late kernel crash during insmod

**Symbol check needed:**
- Verify module dependencies haven't broken
- Confirm brcmutil, cfg80211 are present and compatible
- Check for unresolved symbols that could cause late-stage panic

### NEXT: Isolate the insmod crash

Phase 2a (Hypothesis: kernel module ABI corruption):
1. Check module symbol resolution: `modinfo ./brcmfmac.ko | grep depends`
2. Compare with test.109 baseline: git show e590e51:drivers/.../pcie.c | wc -l
3. If symbols OK → rebuild with test.109 exact code to confirm that works

If test.109 code runs cleanly → regression is in test.110-114 diffs.
If test.109 also crashes → module infrastructure broken (compile flags? kernel version?)

### Files to check
- phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c (line 1-100 for static init)
- Kbuild flags (CFLAGS, module dependencies)
- Compare test.109 binary size vs current binary (if binary bloat suggests symbol table corruption)

### Investigation Update — Crash Hidden from dmesg

**Observations:**
1. BCM4360 device present (lspci confirms 03:00.0)
2. probe() has pr_emerg markers at line 3838 (very early) — NOT LOGGED
3. Module dependencies resolve (cfg80211, brcmutil)
4. dmesg buffer contains no kernel panic / BUG / Oops messages
5. System recovers cleanly (watchdog resets)
6. **Crash signature:** insmod syscall never returns (blocked or hard panic)

**Key insight:** 
- If probe reached, line 3838 pr_emerg would appear (even in a panic)
- It doesn't appear → kernel panic is in pci_register_driver() BEFORE probe
- OR kernel crashes so hard (e.g., NULL deref in insmod itself) that dmesg is lost

**Binary state:** Module size 14MB (Apr 19 00:54), same as test.127 build
- modinfo shows correct dependencies
- Symbol table appears intact

### test.128 PLAN: Surgical diagnostics to isolate crash point

**Hypothesis:** Crash is in pci_register_driver, BEFORE probe is called. Goal: add early pr_emerg messages that survive panics to narrow the crash point.

**Changes made (pcie.c):**
- Line 4261: Added `pr_emerg("BCM4360 test.128: brcmf_pcie_register() entry\n");` at function entry
- Line 4263: Added `pr_emerg("BCM4360 test.128: calling pci_register_driver\n");` before pci_register_driver()
- Line ~3836: Added `pr_emerg("BCM4360 test.128: PROBE ENTRY\n");` at very start of probe function

**Expected results:**
- If "brcmf_pcie_register entry" appears → module init is running
- If "calling pci_register_driver" appears → about to register
- If "PROBE ENTRY" appears → probe was called before crash
- If nothing appears → crash in module init phase before pcie_register runs

**Build:** Use existing module binary if rebuild fails (source changes alone won't cause module load issue anyway)

**After test.128:**
- Match logged messages to crash point
- If "calling pci_register_driver" is last message → crash is in pci_register_driver internals
- If nothing → crash is earlier (module_init → brcmf_core_init → ...)
- If "PROBE ENTRY" appears → we have a new crash location to investigate

### MODULE BUILD STATUS

The module binary (14MB, compiled 2026-04-19 00:54) is a pre-compiled binary NOT rebuilt with the test.128 diagnostic additions. To test with the new pr_emerg markers, the module must be rebuilt.

**Build system:** NixOS/kbuild required. Attempted `make -C phase5/work` failed (no kernel Makefile in that directory). Full build likely requires:
- Kernel headers for 6.12.80
- kbuild environment (via nix-shell or similar NixOS tooling)
- KDIR or KERNELDIR pointing to kernel source

**Options:**
1. **Manual rebuild:** User should run `make -C phase5/work` or equivalent with proper kernel build environment (if previous session established one)
2. **Alternative approach:** Analyze crash WITHOUT rebuild by examining:
   - Binary diffs between test.109 and current (14MB vs prior size)
   - Kernel log from previous tests to find pattern
   - Code audit of test.109→current diffs for module-init-phase issues

**Code audit findings (from diff analysis):**
- test.114b: d11 wrapper reads are GUARDED (check IN_RESET before reading core register) — safe
- test.125/126: PCIE2 mailbox clear now returns early for BCM4360 — avoids known crash
- test.127/128: pr_emerg markers added to probe entry (needs rebuild to take effect)
- No suspicious static initializers or module_init changes found

**Hypothesis update:**
Since the crash happens BEFORE probe even prints its first message, and all code from test.109→current appears safe (diagnostic/read-only), the issue might be:
1. **Stale module cache** — kernel caching old version of .ko file
2. **Binary corruption** — 14MB module might have a corrupted section
3. **Hidden code path** — static initialization or symbol resolution in a code path we haven't examined

---

## CORRECTED ANALYSIS: test.127 Crash Location Found (2026-04-19 session)

### Key Finding: Previous-Boot Log Confirms Probe DID Run

The previous hypothesis "crash before probe entry" was WRONG. The test script does `dmesg -C` BEFORE insmod, so if the machine crashes during insmod, the shell never reaches the dmesg capture. This made it look like probe never ran.

Reading `journalctl -k -b -1` (previous boot log from test.127) shows:
```
brcmfmac: BCM4360 test.127: probe entry (vendor=14e4 device=43a0)
... (all probe steps run including chip_attach, buscore_reset bypass, chip_recognition)
brcmfmac 0000:03:00.0: BCM4360 test.120: before brcmf_fw_get_firmwares
```

The LAST line in the kernel log is "before brcmf_fw_get_firmwares". Machine hard-crashed (MCE/CTO — no BUG/Oops/panic message) immediately after calling `brcmf_fw_get_firmwares`.

### Crash Location: brcmf_pcie_setup async callback

`brcmf_fw_get_firmwares` calls `request_firmware_nowait` which fires the callback `brcmf_pcie_setup` asynchronously (but quickly, since firmware is cached). The callback's first MMIO-unsafe action is `brcmf_pcie_attach` which writes to PCIe2 core config registers.

**Likely cause:** PCIe2 core is in BCMA reset state. Writing to its config registers via the backplane window triggers a PCIe Completion Timeout (CTO) → Machine Check Exception → hard reboot.

### Next Step: Add markers to pinpoint exact crash line

PLAN: Add pr_emerg markers inside `brcmf_pcie_setup` and `brcmf_pcie_attach` to find exact line.

Markers needed:
1. `brcmf_pcie_setup` entry (line 3548)
2. Before `brcmf_pcie_attach(devinfo)` (line 3565)
3. Inside `brcmf_pcie_attach` (line 779), before each MMIO write

After markers → build → test stage 0 → read journalctl -k -b -1 → last marker = crash location.

### Test.128 HYPOTHESIS

Crash is in `brcmf_pcie_attach` → PCIe2 CONFIGADDR write (line 785 of pcie.c). If confirmed, fix is to skip that function for BCM4360 (BAR1 fix not needed; we use BAR2 for firmware download).

This is test.128.

---

## TEST.128 RESULTS — 2026-04-19 (session restart after crash)

Two test.128 runs captured from journal:

### Run A — Boot -2 (00:54, module WITHOUT test.128 pcie_attach markers)
Last BCM4360 marker: `BCM4360 test.120: before brcmf_fw_get_firmwares`
→ Crash is in async callback fired by `brcmf_fw_get_firmwares` (i.e., `brcmf_pcie_setup`)

### Run B — Boot -1 (07:40, module WITH test.128 pcie_attach markers)
Last BCM4360 marker: `BCM4360 test.120: bus wired and drvdata set`
→ Crash earlier than Run A; hardware state variance (worse PCIe state after Run A crash)
→ `brcmf_pcie_setup/brcmf_pcie_attach` markers never reached

### Analysis
- Run A (more informative) confirms crash is in the async `brcmf_pcie_setup` callback
- `brcmf_pcie_setup` immediately calls `brcmf_pcie_attach`
- `brcmf_pcie_attach` writes to PCIe2 CONFIGADDR via backplane window (BAR0)
- PCIe2 core is in BCMA reset at that point → CTO → MCE → hard reboot
- Run B crashed earlier due to cumulative hardware state degradation after Run A

### PCIe State (current)
- MAbort- on endpoint (03:00.0): clean
- MAbort+ in root port (00:1c.2) secondary status: dirty (from prior crash)
- CommClk- in LnkCtl (dirty per CLAUDE.md pre-test checklist)

### Test.128 Second Run Plan (test.128-run2)
Run existing test.128 module binary again (already has pcie_attach markers).
If hardware state permits, Run A behavior should repeat and we'll see:
```
BCM4360 test.128: brcmf_pcie_setup ENTRY
BCM4360 test.128: before brcmf_pcie_attach
BCM4360 test.128: brcmf_pcie_attach ENTRY
BCM4360 test.128: before select_core PCIE2
BCM4360 test.128: before write CONFIGADDR   ← likely last marker before crash
```

Command: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`
Log: phase5/logs/test.128.stage0 (will overwrite)

### Test.129 Plan (implement fix)
Based on evidence from Run A + BCMA reset theory:
- Add BCM4360 early return in `brcmf_pcie_attach` before any MMIO
- The function sets PCIe Command register (bus master enable) via backplane — already set by kernel PCI subsystem via pci_enable_device()
- BCM4360 uses BAR2 for firmware download, so BAR1 config (purpose of pcie_attach) is unnecessary

Fix: In `brcmf_pcie_attach`, before `select_core`, add:
```c
if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
    pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
    return;
}
```

---

## POST-test.128 second run — 2026-04-19 (session restart after crash)

### Result: CRASHED EARLY (hardware state degradation)

Boot -1 (07:41-07:49) ran test.128 second run. Last markers in journal:
- `BCM4360 test.128: brcmf_pcie_register() entry`
- `BCM4360 test.128: calling pci_register_driver`
- `BCM4360 test.128: PROBE ENTRY`
- `BCM4360 test.127: probe entry`
- `BCM4360 test.127: devinfo allocated, before pdev assign`
- **NO** `BCM4360 test.127: devinfo->pdev assigned, before SBR`

Crash is after devinfo kzalloc but before devinfo->pdev = pdev. This is trivially safe code —
crash is almost certainly an asynchronous MCE/NMI from a pending PCIe completion timeout
queued from the previous crash firing during module load.

**Conclusion:** Hardware too degraded after two consecutive crashes for meaningful data.
Per failure signature plan: skip second run, proceed directly to test.129 fix.

**PCIe state (current boot 0):**
- Endpoint (03:00.0): MAbort- (clean), CommClk- (dirty)
- Root port (00:1c.2) secondary: MAbort+ (dirty)

---

## Current state (2026-04-19, PRE test.129 — bypass brcmf_pcie_attach for BCM4360)

### CODE STATE: brcmf_pcie_attach BYPASSED FOR BCM4360

**Evidence supporting bypass:**
- Run A (boot during session at 00:54): last marker `BCM4360 test.120: before brcmf_fw_get_firmwares`
  → crash is in async callback `brcmf_pcie_setup`, which immediately calls `brcmf_pcie_attach`
- `brcmf_pcie_attach` selects PCIe2 core and writes to CONFIGADDR via BAR0
- PCIe2 core is in BCMA reset at that point → CTO → MCE → hard crash

**Code change (pcie.c line ~783):**
Added at start of `brcmf_pcie_attach`, before any MMIO:
```c
if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
    pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
    return;
}
```

**Why safe to skip:**
- BCM4360 uses BAR2 for firmware download, not BAR1
- BAR1 window sizing (the purpose of brcmf_pcie_attach) is unnecessary for BCM4360
- BusMaster already enabled by kernel PCI subsystem via pci_enable_device()
- device_wakeup_enable can be skipped at this stage

**Hypothesis (test.129 stage0):**
- Probe continues through SBR, chip_attach, reset path, firmware download without crashing
- Should see `BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360` in journal
- Then probe continues further into firmware setup
- Possible next crash: in firmware download or OTP access (but more likely clean run)

**Build status:** BUILT — brcmfmac.ko compiled 2026-04-19 (test.129 bypass in place)

**Pre-test requirements:**
1. Build the module
2. Check PCIe state (MAbort+ root port secondary — may need clearing or power cycle)
3. Force runtime PM on if needed

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Success criteria:**
- Journal shows `BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360`
- Probe continues past brcmf_pcie_attach without crash
- Next crash point identified (or no crash — very unlikely but possible)

**Failure signatures:**
- Crash before bypass marker: hardware state too degraded, need power cycle
- Crash after bypass but before firmware download: different code path is the issue

