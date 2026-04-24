# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-24 06:30 BST, PRE-TEST.BASELINE-POSTCYCLE — **Full cold power cycle complete (shutdown + unplug + 60s wait + SMC reset + boot). PCIe clean (Mem+ BusMaster+, no MAbort). Next action: fire the T218 known-good baseline (T236 seed + T238 ultra-dwells, no scaffold, no T259/T265/T266/T267/T268 params) to confirm the substrate traverses the firmware-download path again. If baseline completes → substrate good, re-attempt T268. If baseline crashes at same `after reset_device return` point → hardware needs user escalation. Hypothesis: fresh chip state clears the T265→T268 drift trend. Host up since 06:29 BST.**)

---

## PRE-TEST.BASELINE-POSTCYCLE (2026-04-24 06:30 BST, boot 0 — **Substrate check after cold power cycle; no scaffold, no new params.**)

### Hypothesis

Four consecutive T265-T268 fires crashed progressively earlier, with T268 finally failing on a host-only pre-firmware path that worked 24 minutes earlier. A full cold power cycle (shutdown + unplug + 60s + SMC reset) resets chip/PCIe endpoint rails that platform watchdog reboots don't. Prediction: the baseline T218 ultra-dwell path that was reliable earlier in the session now works again.

### Design

Bare-minimum insmod — only the two params that establish the known-good path:
- `bcm4360_test236_force_seed=1` — standard seeding
- `bcm4360_test238_ultra_dwells=1` — ultra-dwell ladder (the verified-reliable path from session start)

No scaffold (T259/T265/T266/T267/T268 all off). No probe extensions. Module unchanged (ko built at 01:33 for T268; T268 code is gated behind its own param, so leaving `bcm4360_test268_early_scaffold=0` = identical control flow to pre-T268 code).

### Outcome matrix

| Outcome | Reading |
|---|---|
| Reaches end of ultra-dwells, rmmod succeeds | Substrate good. Re-fire T268 next. |
| Crashes at `after reset_device return` again | Hardware in bad state; escalate to user. |
| Crashes elsewhere in mid-ladder | Partial drift; discuss with advisor before next fire. |

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.baseline-postcycle.journalctl.txt`
- `phase5/logs/test.baseline-postcycle.run.txt`

### Pre-test checklist

1. **Build**: already built at 01:33 (T268 code present but gated off via unset param).
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort).
3. **Hypothesis**: cold power cycle restores substrate → baseline path traverses end-to-end again.
4. **Plan**: this block (committed before fire).
5. **Host state**: boot 0, up since 06:29 BST.

---

## PRE-TEST.265 (2026-04-24 00:0x BST, boot 0 — **Identical to T264 scaffold but with msleep(500) instead of msleep(2000).** Single-variable change that decouples "duration-proportional" from "fixed timer post-scaffold-entry".)

### Hypothesis

Across T260/T262/T263/T264, intended_duration = scaffold_duration = elapsed_time_at_crash. Three equally-consistent mechanisms remain:
- **(a)** Duration-proportional: crash fires at `intended_duration` after scaffold entry
- **(b)** Fixed timer at ~2s post-scaffold-entry (coincidentally ≥ all intended durations so far)
- **(c)** Crash tied to msleep-exit transition specifically

T265c changes msleep from 2000ms to 500ms. Three outcomes discriminate cleanly:

| Outcome | Reading |
|---|---|
| Crash within ~500ms (before "msleep done" marker) | **(a) confirmed**: duration-proportional. Timer scales with intended sleep. |
| Crash at ~2s (well after msleep returned, during cleanup) | **(b) confirmed**: fixed timer at ~2s post-scaffold-entry. **CLEANUP PATH BECOMES VISIBLE FOR THE FIRST TIME.** Highest-value outcome. |
| Crash at exactly 500ms (msleep-exit wall-clock) | **(c) confirmed**: msleep-exit transition itself. Different mechanism. |
| Clean completion past 2s | Scaffold-duration was load-bearing somehow. Unlikely but possible. |

### Design

Single new module param `bcm4360_test265_short_noloop`. EXACTLY identical to T264 scaffold (pci_enable_msi + request_irq + msleep + cleanup with markers) but msleep is 500ms instead of 2000ms.

Critically: **NO probes, timer reads, or log markers inside the msleep window**. T264 established "no MMIO during sleep" property — preserve it.

### Safety

- Smallest envelope yet. No loop, no MMIO, no writes. MSI + handler + short sleep + cleanup.
- Cleanup markers will fire if cleanup path runs (first-time visibility if outcome (b)).
- Host crash still expected (n=15+ streak at this point). Platform watchdog reliable.

### Code change outline

1. New module param `bcm4360_test265_short_noloop`.
2. Extend T239 ctr gate + T258 buf_ptr probe gate.
3. Add new invocation block mirroring T264 but with msleep(500). Separate from T264 block to keep both accessible.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test265_short_noloop=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

T258-T264 NOT set.

### Expected artifacts

- `phase5/logs/test.265.journalctl.txt`
- `phase5/logs/test.265.run.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: msleep(500) discriminates duration-proportional vs fixed-timer vs msleep-exit-transition.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 00:03 BST.

Advisor-confirmed. Code + build + fire pending. **Duration-anchor framing in POST-TEST.264 should be treated as hypothesis with circumstantial support — T265c is the test that will actually confirm or refute it.**

---

## POST-TEST.265 (2026-04-24 00:11 BST run — **Fixed-timer-at-2s FALSIFIED; duration-proportional NOT yet confirmed.**)

### Timeline (from `phase5/logs/test.265.journalctl.txt`)

- `00:11:31` scaffold entry — `pci_enable_msi=0 prev_irq=18 new_irq=79`, `request_irq ret=0`
- `00:11:31` `entering msleep(500) — no loop, no MMIO`
- [crash]
- `00:12` platform watchdog reboot (host up 00:12)

**No "msleep done" marker**, no `free_irq` or `pci_disable_msi` markers. Silent lockup (no panic/MCE/AER — same pattern as T264).

### What T265 settled (factually)

- **Host crashed inside the 500ms msleep window** (before "msleep done" could fire).
- **Fixed timer at ~2s after scaffold entry is FALSIFIED.** If the trigger were a fixed ~2s timer, T265's 500ms msleep would end at 500ms, cleanup would run, and "msleep done" / `free_irq` markers would print ~1.5s before the crash. They did not. So the trigger fired at some point in [0, 500ms].

### What T265 did NOT settle (advisor calibration)

- Whether the trigger is:
  - (a) Duration-proportional (crashes at ~msleep_duration regardless of what duration is set), OR
  - (a') Fixed timer somewhere in [0, 500ms] (any msleep long enough to contain the timer crashes in the same way)
- These two are indistinguishable with T264 (2000ms) + T265 (500ms) alone. T266 shrinks the bound.

### Surviving candidate mechanisms (after T265)

1. ~~Fixed timer at ~2s post-entry~~ — **FALSIFIED by T265**.
2. Duration-proportional trigger: fires at `~intended_msleep_duration` after scaffold entry.
3. Fixed timer at some time < 500ms after scaffold entry.
4. Msleep-exit-transition specific (crash fires precisely when msleep schedules back in).
5. Cleanup path is crasher (still invisible — no positive evidence either way).
6. PCIe/ASPM L1→L0 retrain during idle msleep (ASPM L1 enabled in LnkCtl).

### Next-test direction (T266 — advisor-confirmed)

Single-variable change from T265: msleep(500) → msleep(50). Shrinks upper bound 10×.

| T266 outcome | Reading |
|---|---|
| Crash within 50ms (no "msleep done") | Trigger fires in [0, 50ms]. Either fixed-timer-<50ms or proportional. At this point the distinction matters less — "soon after request_irq" is the mechanism. |
| Crash at ~500ms (msleep done fires, but before cleanup finishes) | **Fixed timer ∈ [50ms, 500ms]. Duration-proportional FALSIFIED.** Plus cleanup path becomes visible for first time — high-value. |
| Crash at ~2s (msleep done fires AND cleanup runs cleanly, then crashes much later) | Unlikely (contradicts T265 which would have seen same timing) — but would revive candidate (1) indirectly. |
| Clean completion past 2s | Very short scaffold survives. Opens new questions. |

### Safety

- Same safety envelope as T264/T265. Smaller msleep = less time in MSI-bound state.
- Host crash likely (n=16+ streak). Watch for hardware drift (advisor flagged): if T266 produces non-reproducible results, re-fire before building on them.

### Code change

Extension of existing T265 block OR new param. Simplest: add `bcm4360_test266_ultra_short_noloop` mirroring T265 but msleep(50).

---

## PRE-TEST.266 (2026-04-24 00:1x BST, boot 0 — **msleep(50) variant to shrink upper bound of trigger time 10×.**)

### Hypothesis

T264 (msleep 2000) + T265 (msleep 500): crash within the intended sleep window. Fixed-timer-at-2s falsified. Still coupled: duration-proportional vs fixed-<500ms. T266 = msleep(50) shrinks bound.

### Design

Mirror of T265 block with msleep(50). No other changes. Same markers. Same cleanup.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test266_ultra_short_noloop=1
sleep 200
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.266.journalctl.txt`
- `phase5/logs/test.266.run.txt`

### Pre-test checklist

1. **Build**: NOT yet rebuilt.
2. **PCIe**: verify clean before fire.
3. **Hypothesis**: msleep(50) outcome discriminates proportional vs fixed-<500ms.
4. **Plan**: this block (committed before code).
5. **Hardware drift awareness**: n=16+ crashes today — if T266 produces weird results, re-fire once before claiming anything.

Advisor-confirmed. Code + build + fire pending.

### PCIe state check before T266 fire (2026-04-24 00:1x BST)

**PCIe DIRTY after T265 auto-reboot**: `03:00.0 Control: Mem- BusMaster-`, BARs `[disabled]`, `LnkCtl: ASPM Disabled`, `CommClk-`. BCM4360 endpoint unresponsive. Platform watchdog reboot did not fully recover chip state.

**SMC reset needed** before firing T266. *SMC reset completed by user at 00:23 BST; boot 0 came up with device visible at config space. Firing T266.*

---

## POST-TEST.266 (2026-04-24 00:26 BST run — **msleep(50) also crashes inside its own sleep window. Upper bound now ≤50ms.**)

### Timeline (from `phase5/logs/test.266.journalctl.txt`)

- `00:26:14` dwell ladder reached t+120000ms normally (baseline buf_ptr=0x8009CCBE, same as prior runs)
- `00:26:14` scaffold entry — `pci_enable_msi=0 prev_irq=18 new_irq=79`, `request_irq ret=0`
- `00:26:14` `entering msleep(50) — no loop, no MMIO`
- [crash inside 50ms window]
- `00:27` platform watchdog reboot

**No "msleep done" marker.** No free_irq, no pci_disable_msi. Silent lockup — no panic/MCE/AER.

### What test.266 settled (factually)

- Trigger fires somewhere in [0, 50ms] after scaffold entry (after `request_irq` returned).
- Same pattern as T264 (2s) and T265 (500ms): crash always within the intended msleep window; "msleep done" never fires.
- **Upper bound compressed 40× across three tests** (T264 2000ms → T265 500ms → T266 50ms).

### What test.266 did NOT settle

- Still coupled: duration-proportional trigger vs fixed-timer-<50ms. At this bound the distinction starts mattering less — any fixed timer under 50ms looks "nearly immediate".
- Which of `pci_enable_msi`, `request_irq`, or "being MSI-bound" is the essential trigger component.
- Whether crash fires during the msleep, or precisely at msleep-exit (<50ms granularity is insufficient here).

### Surviving candidate mechanisms (after T266)

1. ~~Fixed timer at ~2s~~ — FALSIFIED by T265.
2. **Near-instant trigger within [0, 50ms] of request_irq returning.** Mechanism unknown — could be MSI routing, first IRQ arrival, ASPM state transition, or something else tied to the IRQ subscription.
3. **Duration-proportional trigger** (crash at ~intended_duration). Still plausible but narrowing — at msleep(50) the delta from request_irq is only 50ms.
4. **Msleep-exit-transition specific**: the moment the scheduler resumes the task after msleep completes, some state is fatal.
5. **Cleanup path still invisible**: we've never seen cleanup markers fire, which is consistent with either "crash happens first" (candidates 2/3/4) or "cleanup fires the crash".

### Next-test direction (T267 — advisor call before committing)

Candidate tests to isolate the trigger component:

- **T267a: no msleep at all.** Scaffold = pci_enable_msi + request_irq + IMMEDIATE free_irq + pci_disable_msi. If cleanup markers fire → trigger requires "being MSI-bound for some time". If crashes before any marker → trigger is immediate upon request_irq.
- **T267b: pci_enable_msi only** (no request_irq). Enables MSI, small sleep, disables MSI. Tests whether MSI enablement alone triggers.
- **T267c: request_irq on legacy INTx** (no pci_enable_msi). Tests whether request_irq alone (without MSI) triggers. Requires driver code restructuring.

Most discriminating single test: probably T267a (smallest envelope, fastest check, directly answers "is msleep necessary").

Advisor call before committing to T267 design.

---

## PRE-TEST.267 (2026-04-24 00:3x BST, boot 0 — **No-msleep variant: MSI + request_irq + IMMEDIATE free_irq + pci_disable_msi. Existing cleanup markers give 5-position crash discrimination. Clean completion = msleep-duration is necessary (highest-value outcome).**)

### Hypothesis

T264/T265/T266 all crash inside intended msleep window; upper bound ≤50ms. Remaining question: is msleep's duration essential, or is the trigger fired by request_irq / MSI setup itself?

T267a removes msleep entirely. The sequence becomes purely: request_irq → free_irq → pci_disable_msi. Each transition has an existing marker.

### Design (no code size change — reuse T264 block pattern)

```
pci_enable_msi                          [marker A: pci_enable_msi=...]
request_irq                             [marker B: request_irq ret=...]
pr_emerg "skipping msleep; calling free_irq immediately"   [NEW marker]
pr_emerg "calling free_irq"             [marker C]
free_irq                                 —
pr_emerg "free_irq returned"            [marker D]
pr_emerg "calling pci_disable_msi"      [marker E]
pci_disable_msi                          —
pr_emerg "pci_disable_msi returned"     [marker F]
```

### Next-step matrix (advisor-framed)

| Last marker seen | Reading |
|---|---|
| A, B only (no "skipping msleep" print) | Crash between request_irq and next pr_emerg. Very tight window — trigger is ~immediate upon request_irq return. |
| B + "skipping msleep" + C | Crash in free_irq. |
| C + D | Crash between free_irq and pci_disable_msi — unexpected. |
| D + E | Crash in pci_disable_msi. |
| D + E + F (all markers fire, module unloads) | **msleep duration is necessary for crash trigger.** Highest-value outcome. Time-in-MSI-bound-state matters. Re-fire once to confirm (n=2). |

### Safety

- Smallest scaffold yet — no sleep between request_irq and free_irq.
- Cleanup path runs under every conceivable timer-firing-time <50ms.
- Host crash still likely but uncertain. Re-fire required if all markers fire (first clean completion would be headline finding; n=1 insufficient).

### Code change outline

1. New param `bcm4360_test267_no_msleep`.
2. Extend T239 ctr gate + T258 buf_ptr probe gate.
3. Add scaffold block mirroring T264 but with msleep call REPLACED by a new "skipping msleep" pr_emerg marker.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test267_no_msleep=1
sleep 200
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.267.journalctl.txt`
- `phase5/logs/test.267.run.txt`

### Pre-test checklist

1. **Build**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: stated — 5-position discrimination of crash location.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 00:27 BST.

Advisor-confirmed. Code + build + fire pending.

### T267 first fire (2026-04-24 00:36 BST) — **NULL TEST**

Reached t+120000ms probe burst, printed test.238/239/240/247, crashed before test.249. Normal pacing.

### T267 re-fire (2026-04-24 01:08 BST) — **ALSO NULL TEST, different crash position**

Reached t+120000ms probe burst, printed test.238/239/240, crashed before test.247 (earlier than first fire). Normal pacing. Scaffold never ran again.

### Consolidated observation: hardware drift

Two consecutive null-test fires of T267 crashed at DIFFERENT positions within the t+120000ms probe burst (after test.247 vs after test.240). Earlier today T264-rerun, T265, T266 all successfully ran their scaffolds at this same point.

Interpretation: **hardware drift is now actively polluting signal.** Advisor flagged this risk at n=16+ wedges. We're now at n=22+. The BCM4360 chip and/or PCIe bridge state is degraded.

Options:
1. Extended idle period + SMC reset + full power cycle (let chip cool, let BMC fully reset state).
2. Pivot test strategy: run tests that don't need the full 120s dwell ladder — move the scaffold much earlier to minimize accumulated stress per test.
3. Accept this investigation has reached its practical limit for today; preserve state and resume after longer cool-down.

**Not firing again without advisor consultation.** Pausing here to avoid further hardware stress while state is drifting.

### Advisor reframe + T268 pivot (2026-04-24 01:2x BST)

Advisor pushed back on "hardware drift" framing. Real read: t+120000ms probe burst region is **marginal** (6/9 pass today). Fix is the same either way: **pivot the scaffold out of the flaky region entirely.**

The scaffold is a pure host-side MSI/request_irq test. It doesn't need the 120s dwell ladder (which exists for fw-state probing, a different question). Move the scaffold to run **right after `brcmf_chip_set_active()` returns TRUE**, before the dwell ladder starts. ~10× less exposure per test, identical scaffold evidence, duration-scaling results from T264/T265/T266 still compose.

---

## PRE-TEST.268 (2026-04-24 01:2x BST, boot 0 — **Early-scaffold pivot: run T267-style MSI + request_irq + immediate cleanup RIGHT AFTER `brcmf_chip_set_active` returns, skip the dwell ladder entirely.** 10× less exposure; same scaffold test.)

### Hypothesis

T267's scaffold would have given 5-position crash discrimination, but two consecutive T267 fires both crashed in the t+120000ms probe burst (the shared dwell-ladder exit region). T268 moves the scaffold to a quieter time window: right after chip activation, before any dwell probes.

If T268 crashes inside scaffold: we get the same discrimination T267 was meant to provide. 
If T268 completes cleanly: the msleep-duration hypothesis from T264-T266 stands — crash requires being MSI-bound long enough for a timer to fire.

### Design

New param `bcm4360_test268_early_scaffold`. When set:

1. Dwell ladder entry prints `brcmf_chip_set_active` call + TRUE/FALSE marker (unchanged).
2. **Skip the entire dwell ladder.** `goto ultra_dwells_done`.
3. Run the exact same scaffold as T267: `pci_enable_msi` + `request_irq` + IMMEDIATE `free_irq` + `pci_disable_msi`, all markers bracketed.
4. Proceed to BM-clear + chip release (unchanged — this is what runs after `#undef BCM4360_T239_POLL`).

Conceptually this is `bcm4360_test267_no_msleep=1` but with the scaffold running 2 minutes earlier (right after chip activation, ~15s into insmod instead of ~2min).

### Next-step matrix

| Outcome | Reading |
|---|---|
| All 6 scaffold markers fire, module unloads | **msleep duration is necessary** for crash trigger. Headline finding. Re-fire once. |
| Crash between markers A-B, B-C, C-D, D-E, or E-F | 5-position discrimination fires — tells us exactly where in pci_enable_msi / request_irq / free_irq / pci_disable_msi the crash happens. |
| Crash before scaffold entry (in probe path earlier than scaffold) | Same flaky region hit again; investigate further. |

### Safety

- Scaffold envelope unchanged from T267; just moved earlier.
- Skips 120s of MMIO reads — less exposure to the marginal region that failed T267 twice.
- Same cleanup (free_irq + pci_disable_msi) before BM-clear/chip release.

### Code change outline

1. New module param `bcm4360_test268_early_scaffold`.
2. Insert `if (bcm4360_test268_early_scaffold) { scaffold; goto ultra_dwells_done; }` right after `brcmf_chip_set_active returned TRUE/FALSE` prints at line ~3713.
3. Add label `ultra_dwells_done: ;` right before `#undef BCM4360_T239_POLL` at line ~4048.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test268_early_scaffold=1
sleep 30
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

No probe params needed — we're skipping the ladder. `sleep 30` gives init + chip_set_active + scaffold time to run (should be <20s).

### Expected artifacts

- `phase5/logs/test.268.journalctl.txt`
- `phase5/logs/test.268.run.txt`

### Pre-test checklist (pending code+build)

1. **Build**: NOT yet rebuilt.
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort).
3. **Hypothesis**: move scaffold out of marginal ladder region; 5-position discrimination retained.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 01:15 BST.

Advisor-confirmed. Code + build + fire pending.

---

## POST-TEST.268 (2026-04-24 01:33 BST run — **Null test: crashed before scaffold could run, before firmware download, before `chip_set_active`.**)

### Timeline (from `phase5/logs/test.268.journalctl.txt`)

- `01:33:32` insmod entry, test.188 module_init entry
- `01:33:33–01:33:43` normal path: SDIO register, PCI register, probe entry, SBR, chip_attach, BAR0 probes, 6 cores enumerated
- `01:33:43` `test.125: buscore_reset entry, ci assigned`
- `01:33:43` `test.122: reset_device bypassed; probe-start SBR already completed`
- `01:33:46` `test.125: after reset_device return` — **LAST MARKER**
- [silent lockup, no further kernel output]
- `01:34+` platform watchdog reboot

### Key observation

The next expected marker after `after reset_device return` is `test.125: after reset, before get_raminfo` (seen in T267 journal at 01:09:00 → 01:09:03, a ~3s gap). T268 never produced that marker.

Crash happened in the 3-second window between `buscore_reset` returning and `get_raminfo` being called — **host-side code path with zero involvement of firmware, scaffold, or dwell ladder**. The plainest failure path seen so far.

### What T268 did NOT settle

- **T268 scaffold never executed.** Any msleep-duration / cleanup-path / fixed-timer claim remains unresolved from T264-T266.

### Crash-stage trend (hardware marginality escalating)

| Fire | Last marker before crash | Stage |
|---|---|---|
| T265 | `entering msleep(500)` (scaffold running) | post-firmware-download, inside scaffold window |
| T266 | `entering msleep(50)` (scaffold running) | same |
| T267 #1 | mid t+120000ms probe burst | dwell ladder late |
| T267 #2 | mid t+120000ms probe burst (different position) | dwell ladder late |
| T268 | `test.125: after reset_device return` | pre-firmware-download host path |

Four consecutive fires crashed progressively earlier. T268's crash is in a host-only code path — no scaffold, no firmware, no probes.

### Surviving hypotheses (unchanged from POST-TEST.266)

1. Duration-proportional trigger in scaffold window
2. Fixed timer in [0, 50ms]
3. Msleep-exit transition
4. Cleanup path crasher
5. PCIe/ASPM L1 retrain

**None of these were tested by T268.**

### Next-test direction (advisor required)

Possible pivots:
- **Cold-baseline re-fire**: fire T218 baseline (no scaffold) to see if plain probe path is reliably failing.
- **Even-earlier scaffold (T269)**: scaffold right after SBR — but T268's crash is in buscore_reset→get_raminfo, so scaffold would need to move even earlier in the probe path.
- **Abandon scaffold line temporarily**: step back to passive T218 observation.
- **Full power cycle / longer cool-down** before next fire — hardware thermal/state drift.

Consulting advisor next.
