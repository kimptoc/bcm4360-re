# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-24 08:40 BST, POST-FW-BLOB-DISS REFRAME — **fw-blob diss task landed (phase6/t269_pciedngl_isr.md) and dovetails with the T271 pre-code blocker into a coherent reframe.** The scaffold investigation line (T258–T269) was trying to drive a wake handshake whose fw-side precondition — fw completing `pcidongle_probe` → `hndrte_add_isr(pciedngl_isr, bit=3)` and then publishing `shared.flags |= HOSTRDY_DB1` (0x10000000) — was NEVER met. Upstream's `brcmf_pcie_hostready` explicitly gates on `HOSTRDY_DB1`; our scaffolds skipped that gate and wrote H2D_MAILBOX_1 into a fw state where `pciedev+0x18` was NULL, causing silent fw-side NULL-deref matching our wedge signature. **New bracketing**: fw reaches wlc_bmac_attach (T251/T252) → enters WFI (T257) → does NOT reach pcidongle_probe (T247: TCM[ramsize-4] unchanged 23/23 dwells). The hang is in the init chain between wlc_bmac_attach and pcidongle_probe. T271/Candidate-A-as-framed is moot. New productive thread: T272-FW, trace fw init chain between those two points. Zero hardware fires today since 08:01. Substrate window still open.)

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

## POST-TEST.BASELINE-POSTCYCLE (2026-04-24 06:32 BST run — **Substrate good; crash migrates from scaffold region to late-ladder (t+90→t+120s) under pure ladder config.**)

### Timeline (from `phase5/logs/test.baseline-postcycle.journalctl.txt`)

- `06:32:44` insmod entry
- `06:32:49` full probe path traversed: SBR ✓, chip_attach ✓, **test.125 after reset_device return ✓** (where T268 wedged), get_raminfo ✓, chip_attach returned successfully, ASPM disabled
- `06:33:07` firmware download complete (test.188 fw-sample MATCH entries), `chip_set_active returned TRUE`
- `06:33:07–06:34:35` T238 ladder progression: t+100ms → t+500ms → t+2000ms → t+10s → t+30s → t+45s → t+60s → t+90000ms
- `06:34:35` **LAST MARKER: `t+90000ms dwell`**
- [silent lockup, no further kernel output; expected next marker t+120000ms never fires]
- `06:47` platform watchdog reboot

Crash window: [t+90000ms marker fired, t+120000ms marker never fired] — crashed somewhere in the ~30s gap between these two dwell points.

### What baseline did NOT have (significant)

- NO scaffold (T259/T265/T266/T267/T268 all OFF)
- NO MSI enable, NO request_irq, NO interrupt-handler registration
- NO T239 poll_sharedram, NO T240 wide_poll, NO T247 preplace_shared, NO T248 wide_tcm_scan

Pure T238 ultra-dwell ladder with T236 seed. Minimal config.

### Key reinterpretation

The late-ladder crash window (t+90s → t+120s) is reached under the bare T238 ladder. **Prior test crashes in this same window have been attributed to various scaffold/param combinations, but the ladder alone is sufficient.** This substantially weakens the "scaffold is the crasher" framing that guided T265-T268.

Previous interpretations that should now be questioned:
- T267's "mid t+120000ms probe burst" crashes may be intrinsic to the ladder, not caused by the scaffold.
- T265/T266 msleep-based framing only holds IF the scaffold actually reaches execution — in this pure-ladder run, no scaffold is present.
- T264's "duration-proportional" phrasing conflated scaffold duration with total-elapsed-time; the crash may be elapsed-time-based regardless of scaffold.

### What baseline settled (factually)

- **Cold power cycle cleared the T268-stage host-path drift.** The `after reset_device return` wedge is state-dependent and can be reset by full AC disconnect + 60s wait + SMC reset.
- **The t+90s→t+120s crash window is reproducible WITHOUT the scaffold.** This is a new data point not previously isolated.

### What baseline did NOT settle

- Whether the crash is at a fixed wall-clock time (~2min post-insmod / ~90-120s post-set_active) or depends on cumulative MMIO activity.
- Which operation inside the t+90→t+120 window triggers the crash (the ladder has minimal activity in this interval — mostly sleep).
- Whether simply extending the interval would still crash in the same window if more granular markers were inserted.

### Next-test direction (advisor required)

The framing shift is large enough that I shouldn't pick the next test alone. Options:
- **B-variant: bisect the t+90→t+120 window** with extra dwell markers at t+95s, t+100s, t+105s, t+110s, t+115s, t+120s. Single-param change to T238. Tells us whether the crash is at a specific sub-window.
- **B-variant: cut the ladder short at t+90s and rmmod cleanly.** Does the cleanup path work if we exit before the crash window? High-value — if rmmod succeeds, confirms the crash is elapsed-time/ladder-work related, and gives us a stable baseline to build on.
- **Reconcile with old "known-good" T218**: earlier in the project T218 was said to reach end-of-ladder reliably. Need to verify that claim vs today's crash.

Consulting advisor next.

### Reconciliation with history (added post-advisor)

Grep across `test.2*.journalctl.txt`:

| Logs reaching `t+120000ms dwell` | Logs with actual clean rmmod |
|---|---|
| 12/13 (244, 249, 256, 258, 259, 261, 262, 263, 264, 265, 266, 267; only 260 didn't) | **0/13** (cleanup_markers=1 matches were false-positives from unrelated `sd sdb: Media removed` lines) |

So the "T218 / baseline reliably reaches end of ladder" claim that anchored POST-TEST.268's drift framing holds HALFWAY: prior runs do reach t+120000ms dwell marker, but none of them unload cleanly afterward. Every test since 244 crashed somewhere past the t+120000ms marker. Today's baseline-postcycle crashing at t+90→t+120 is slightly earlier than historical (which crashed past t+120), but the crash window is in the same general neighborhood.

Implication: T265-T268 scaffold-attributed crashes were likely the **same late-window host-wedge mechanism** that affects the baseline. The scaffold was never the primary crasher. This validates the framing shift.

---

## PRE-TEST.269 (2026-04-24 06:55 BST, boot 0 — **Early-exit variant: stop the T238 ladder at t+60000ms and return, enabling clean rmmod.**)

### Hypothesis

Baseline reached `t+90000ms dwell` and crashed before `t+120000ms dwell` — a ~30s window that's never been safely traversed. Three mechanisms remain consistent with all evidence to date:

1. **Wall-clock timer**: something fires at ~111-143s after insmod regardless of what code is doing.
2. **Activity-accumulation**: cumulative PCIe/MMIO activity crosses some threshold at this time.
3. **Cleanup-path trigger**: the real crasher is in the BM-clear/release path that runs after the ladder, and the ladder is just "time before cleanup fires".

T269 discriminates cleanly:

| Outcome | Reading |
|---|---|
| Ladder stops at t+60s, BM-clear + chip release + rmmod succeed | **Activity/late-ladder crash avoidable by early exit.** Stable reproducer found. (a) and (b) both consistent; (c) refuted. |
| Ladder stops at t+60s but crash fires ~111-143s after insmod (during BM-clear or after) | **Wall-clock timer confirmed.** (a) confirmed. |
| Crash during rmmod or in BM-clear path itself | **Cleanup path is the real crasher.** (c) confirmed. Rewrites the T265-T268 framing entirely. |

### Design

New param `bcm4360_test269_early_exit`. When set, the T238 ultra-dwells branch:
1. Runs t+100ms through t+60000ms dwells as normal (with all probe helpers invoked at t+60000ms).
2. **`goto ultra_dwells_done`** right after the t+60000ms probes, skipping t+90000ms, t+120000ms, and all scaffold blocks.
3. Normal flow resumes at `ultra_dwells_done:` which runs BM-clear + chip release.

Single variable change from baseline-postcycle: the ladder returns early.

### Safety

- Smallest exposure yet: 60s of ladder vs 120s (baseline-postcycle ran 90s before crash).
- No scaffold, no MSI, no request_irq.
- Platform watchdog reliable on host lockup.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test269_early_exit=1
sleep 100
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

insmod probe thread runs: chip_attach (~25s) + T238 ladder to t+60s (~60s) = ~85s before probe returns. `sleep 100` gives margin, then rmmod.

### Expected artifacts

- `phase5/logs/test.269.journalctl.txt`
- `phase5/logs/test.269.run.txt`

### Pre-test checklist

1. **Build**: module rebuilt; `bcm4360_test269_early_exit` param visible via modinfo; `test.269: early-exit at t+60000ms` marker in .ko strings.
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort) at 06:48 BST.
3. **Hypothesis**: this block.
4. **Plan**: this block (committed before fire).
5. **Host state**: boot 0, up since 06:47 BST.

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

---

## POST-TEST.269 (2026-04-24 06:56-06:57 BST run — **Ladder crashed at `t+45000ms dwell`; never reached the t+60000ms early-exit. Zero evidence for or against the early-exit hypothesis. Significantly EARLIER than baseline-postcycle 23 min prior on identical code — hardware drift signal reasserted.**)

### Timeline (from `phase5/logs/test.269.journalctl.txt`, boot -1)

- `06:56:24` insmod entry, SBR, chip_attach, FORCEHT, `brcmf_chip_set_active returned TRUE`
- `06:56:24 → 06:57:10` T238 ladder progressed t+100ms → t+300 → t+500 → t+700 → t+1000 → t+1500 → t+2000 → t+3000 → t+5000 → t+10000 → t+15000 → t+20000 → t+25000 → t+26s → t+27s → t+28s → t+29s → t+30000 → t+35000 → **t+45000ms** dwell
- `06:57:10` **LAST MARKER: `t+45000ms dwell`**
- [silent lockup; no further kernel output; expected next markers t+50000ms / t+60000ms never fired]
- `07:02:51` platform watchdog reboot (boot 0)

### What T269 settled (factually)

- **The crash time halved vs baseline-postcycle.** Comparison of runs on identical code (T269 diverges from baseline only at t+60000ms; crash happened at t+45000ms before the divergence):
  - `baseline-postcycle` (06:33:07 set_active) → crashed between `t+90000ms` (06:34:35) and `t+120000ms` → **survived ~88s of ladder**
  - `T269` (06:56:24 set_active) → crashed between `t+45000ms` (06:57:10) and `t+50000ms` → **survived ~46s of ladder**
  - Same host, same hardware, same code up to the crash point, runs 23 minutes apart → clear drift signal.

- **Early-exit hypothesis: UNTESTED.** T269 never reached the t+60000ms branch point. All three outcomes enumerated in PRE-TEST.269 are neither confirmed nor refuted.

- **PCIe state clean on next boot.** Post-crash boot 0 shows `Mem+ BusMaster+`, no MAbort — the lockup left PCI config space intact (watchdog reboot cleared it).

### What T269 did NOT settle

- Whether the crash is wall-clock-based (fires ~N seconds after insmod regardless of what code does), activity-accumulation-based (crosses a cumulative-MMIO threshold), or cleanup-path-based.
- Whether the early-exit would have completed cleanly had the ladder reached it — cannot test this path under current hardware state.

### Drift pattern (today's run history)

| Run | Time | set_active | Last marker | Elapsed-at-crash |
|---|---|---|---|---|
| T267 #1 | 00:36 BST | ✓ | mid t+120000ms probe burst | ~130s |
| T267 #2 | 01:08 BST | ✓ | mid t+120000ms probe burst (earlier position) | ~125s |
| T268 | 01:33 BST | ✗ (never reached) | `after reset_device return` (pre-fw) | ~3s |
| baseline-postcycle | 06:33 BST (post cold power cycle) | ✓ | t+90000ms dwell | ~88s |
| T269 | 06:56 BST | ✓ | t+45000ms dwell | ~46s |

Cold power cycle at 06:30 BST gave **one** clean late-ladder traversal (baseline-postcycle), then drift restored within 23 min. This is consistent with T267's "hardware drift actively polluting signal" finding — the cold cycle's effect is transient.

### Surviving candidate mechanisms (unchanged from POST-BASELINE-POSTCYCLE, still no evidence for any)

- Wall-clock timer (but now timing varies widely — 46s vs 88s — suggesting not fixed)
- Activity-accumulation (plausible but the two runs had very similar MMIO patterns up to t+45s)
- Cleanup-path crasher (still unreachable)

### Next-test direction (advisor required — drift dominates signal)

Options to consider:

1. **Another cold power cycle + immediate re-fire of T269** (n=2 reproducibility check of the early-exit hypothesis). If hardware behaves like baseline-postcycle did (one clean run after cold cycle), T269 may succeed. Risk: drift back by second fire.
2. **Re-fire baseline (no T269 variant) after cold cycle**, to check whether the drift reading holds (is the "clean run" reproducible at all, or did baseline-postcycle get lucky?).
3. **Pause hardware tests entirely**; pivot to firmware-blob analysis (the T253-T255 thread on wlc_phy_attach internals was deferred when hardware leads opened). This is the lowest-cost option and doesn't consume hardware state.
4. **Extended cool-down** (hours, not minutes) before any further hardware fire.

Today's n-of-wedges is now 23+. Hardware signal is noisy and getting noisier.

Consulting advisor next.

---

## PRE-TEST.270-BASELINE (2026-04-24 07:52 BST, boot 0 after second cold power cycle at ~07:47 BST — **Reproducibility check: fire bare baseline config (no T269, no scaffold, no probes) and see if baseline-postcycle's t+90s clean traversal reproduces post-cold-cycle.**)

### Hypothesis

The 06:33 BST baseline-postcycle run reached `t+90000ms dwell` cleanly after a cold power cycle at 06:30 BST. T269 fired 23 min later (still within same cold-cycle session) crashed at `t+45000ms` — drift returned within ~25 min.

If baseline-postcycle's clean run was substrate-driven (post-cold-cycle is reliably clean for ~20 min), this fire will reproduce: ladder runs t+100ms → t+90000ms cleanly, host wedges in [t+90s, t+120s], platform watchdog reboots.

If it was circumstantial (one lucky roll), this fire will wedge earlier — anywhere from mid-probe-path to mid-ladder — and the whole T265–T269 framing built on "cold cycle restores substrate" needs re-examination.

### Design

Single-variable — strict reproduction of 06:33 BST config:
- `bcm4360_test236_force_seed=1` — standard seeding.
- `bcm4360_test238_ultra_dwells=1` — ultra-dwell ladder to t+120s.
- No probe params, no scaffold params (T259/T265/T266/T267/T268/T269 all OFF).

Same module .ko (built 01:33, bit-for-bit identical to baseline-postcycle's and T269's). All new params gated off = identical control flow.

### Outcome matrix

| Outcome | Reading | Follow-up |
|---|---|---|
| Reaches `t+90000ms dwell`, wedges in [t+90s, t+120s] like 06:33 | Substrate-bounded. Clean post-cold-cycle run reproducible. Can build on this substrate (careful). | Advisor + consider T270 with scaffold variant on this now-validated substrate. |
| Crashes earlier in ladder (t+X000ms, X<90) | 06:33 was lucky; drift already active. Scaffold-driven framing of T265–T269 needs re-examination. | Stop firing today; pivot to fw-blob (task phase6/t269_fw_blob_diss.md). |
| Crashes in probe path before set_active | Different hardware state from 06:33; chip/bridge in a harder-to-recover state. | Escalate to user; longer cool-down; no more fires today. |

### Pre-test checklist

1. **Build status**: VERIFIED. modinfo shows `bcm4360_test236_force_seed` and `bcm4360_test238_ultra_dwells`. No rebuild.
2. **PCIe state**: VERIFIED clean at 07:52 BST — `Mem+ BusMaster+`, no `MAbort+` / `CommClk-` / `>SERR-` / `<PERR-`.
3. **Hypothesis**: this block.
4. **Plan**: this block (committing before fire).
5. **Host state**: boot 0, up since 07:50 BST. Fresh cold cycle completed at ~07:47 BST (boot -1 was a transient 17s boot, then cold cycle, then boot 0).
6. **Task brief**: `phase6/t269_baseline.md` (committed 6e9645d).

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.270-baseline.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.270-baseline.run.txt || true
```

### Expected artifacts

- `phase5/logs/test.270-baseline.journalctl.txt`
- `phase5/logs/test.270-baseline.run.txt`

### Safety

- Smallest envelope available. No scaffold. No MSI. No request_irq.
- Platform watchdog has been reliable (n=4+ of 4 for host-lockup recovery today).
- Expected worst case: host wedge → watchdog reboot. User not needed unless recovery fails.

---

## POST-TEST.270-BASELINE (2026-04-24 07:54-07:55 BST run — **Reaches `t+90000ms dwell` cleanly, wedges in [t+90s, t+120s] — reproduces 06:33 BST baseline-postcycle within measurement noise. Substrate-bounded reading CONFIRMED.**)

### Timeline (from `phase5/logs/test.270-baseline.journalctl.txt`, boot -1)

- `07:54:05` insmod (per run.txt), FORCEHT, chip_attach, T238 ladder entry
- `07:54:25` `brcmf_chip_set_active returned TRUE`
- `07:54:25 → 07:55:56` T238 ladder traversed t+100ms → t+300 → t+500 → t+700 → t+1000 → t+1500 → t+2000 → t+3000 → t+5000 → t+10000 → t+15000 → t+20000 → t+25000 → t+26000 → t+27000 → t+28000 → t+29000 → t+30000 → t+35000 → t+45000 → **t+60000ms** → **t+90000ms** dwell
- `07:55:56` **LAST MARKER: `t+90000ms dwell`** (22 dwells completed)
- [silent lockup; t+120000ms dwell never fires]
- `07:58:23` platform watchdog reboot (boot 0); user performed cold-cycle between boots based on boot gap

### Direct comparison vs 06:33 BST baseline-postcycle

| Metric | baseline-postcycle (06:33) | T270-BASELINE (07:54) | Delta |
|---|---|---|---|
| set_active TRUE at | 06:33:07 | 07:54:25 | (absolute time only) |
| last marker | `t+90000ms dwell` | `t+90000ms dwell` | **identical** |
| elapsed from set_active to last marker | 88s (06:33:07 → 06:34:35) | 91s (07:54:25 → 07:55:56) | +3s (within ladder-step jitter) |
| wedge window | (t+90s, t+120s] | (t+90s, t+120s] | **identical** |
| ladder markers landed | 22 | 22 | **identical** |
| kernel crash trace | none | none | **identical** |
| recovery | watchdog | watchdog + cold-cycle | (user cold-cycled between boots for cleanness) |

### What T270-BASELINE settled (factually)

- **Clean post-cold-cycle substrate IS reproducible.** Two independent cold-cycle firings, same .ko, same params, ~90 minutes apart, both reach t+90000ms dwell and crash in the same [t+90s, t+120s] window.
- **The 06:33 BST baseline-postcycle run was NOT circumstantial.** The "cold cycle buys ~20-25 min of clean substrate" reading is now substantiated.
- **The T269 result (46s of ladder, 44 min post-cold-cycle, after two watchdog reboots) IS consistent with drift accumulation, not with "baseline is inherently unreliable".**

### What T270-BASELINE did NOT settle

- The t+90→t+120 wedge mechanism itself — still unknown (activity accumulation? wall-clock watchdog? fw-side timer?).
- How many fires the clean substrate tolerates before drift resets (n=1 post-cycle confirmed clean for this cycle; n=2+ behavior unknown).
- Whether the substrate is "clean for time X" or "clean for Y operations" — 06:33 → 06:56 T269 crashed earlier after one intervening boot; was it the time (23 min) or the boot?

### Next-test direction

Code audit (phase6/t269_code_audit_results.md) recommends **Candidate A** as highest-probability scaffold fix: add `init_ringbuffers + init_scratchbuffers` before any T258-style scaffold. Rationale:

- Candidate A addresses the biggest load-bearing skip in our harness vs upstream brcmfmac.
- Without ring+scratch DMA buffers published to TCM, fw has no valid DMA target; any post-doorbell TLP hits unmapped address → with `pci=noaer` cmdline, result is silent wedge (matches observed pattern).
- Cleanly discriminative: if scaffold now completes (markers fire, rmmod succeeds), ring-init was the load-bearing skip. If still wedges, ring-init is ruled out and we focus on ASPM L1 or PMU watchdog.

Audit-recommended fire order now validated (step 1 complete):
1. ✓ Baseline re-fire → substrate confirmed (THIS TEST).
2. **T271**: T266 scaffold + Candidate A (init_ringbuffers + init_scratchbuffers before scaffold).
3. Depending on (2), remove `pci=noaer` (Candidate B) or add readback markers (Candidate E).

Constraint from substrate finding: each scaffold test consumes clean-substrate time; if we want T271 to be readable, fire it soon after a cold cycle (within ~20 min window based on the T269 vs baseline-postcycle gap). Sequence: cold cycle → T271 → if wedge, accept as-is and analyze; do NOT re-fire without another cold cycle.

Advisor + T271 code design before next fire.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.270-baseline.journalctl.txt` (1411 lines).
- Run output captured: ✓ `phase5/logs/test.270-baseline.run.txt`.
- Matrix outcome resolved: ✓ row 1 — "Reaches t+90000ms, wedges [t+90s, t+120s] — substrate-bounded."
- Ready to commit + push + sync.

---

## T271 PRE-CODE-CHECK (2026-04-24 08:10 BST — **Advisor-flagged pre-code grep surfaces a blocker. No code written; no hardware fired.**)

### The check

Per advisor (prior to this session): before coding T271 (T266 scaffold + Candidate A ring-init), verify that `devinfo->shared.ring_info_addr` is populated on our code path before the scaffold point. If not, `brcmf_pcie_init_ringbuffers` would read garbage from TCM[0] and the experiment is unreadable.

### Primary-source findings

Grep of `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:

1. **`shared.ring_info_addr` is populated ONLY inside `brcmf_pcie_init_share_ram_info`** (line 2784: `shared->ring_info_addr = brcmf_pcie_read_tcm32(devinfo, addr);`).
2. **`init_share_ram_info` is called from two sites inside `brcmf_pcie_download_fw_nvram`**: line 5700 (the T96/FullDongle-ready direct init) and line 5804 (the wrapper fallthrough at end of function).
3. **Our T238 ultra_dwells branch at line 3581 exits `brcmf_pcie_download_fw_nvram` BEFORE lines 5700..5804.** We never reach either init_share_ram_info call.
4. **T47/T96 markers** (which test.130 setup would log if either init_share_ram_info path executed) are **absent** from the T270-BASELINE journal — confirmed by grep.
5. **`init_share_ram_info` itself requires `sharedram_addr` (fw-published at TCM[ramsize-4])** via the loop at line 5723-5727.
6. **T247 primary-source observation (recorded in RESUME_NOTES_HISTORY line 830)**: TCM[ramsize-4] stayed at `0xffc70038` (NVRAM trailer marker) across all 23 dwells through t+120s. **Fw never publishes sharedram_addr.**

### Implication: Candidate A is blocked upstream

`init_ringbuffers → reads shared.ring_info_addr → populated only by init_share_ram_info → requires sharedram_addr → fw never publishes it.` The chain is broken at the source, not the sink. Candidate A as framed (add two function calls) is not a minimal-change test; the preconditions the audit presumed are absent.

### Tightening the hang reading (new evidence)

This evidence bounds the hang window tighter than before:

- si_attach completes (T252: 0x92440 struct populated).
- Fw enters WFI (T257: DEFINITIVE via scheduler path).
- Fw does NOT publish sharedram_addr at TCM[ramsize-4] before entering WFI (primary-source via T247 probe across 23 dwells).

Conclusion: **fw's WFI entry happens BEFORE the shared-info-publish step.** The init sequence reaches further than wlc_bmac_attach (per T251/T252) but stops before reaching shared-info publish. This narrows where in the init sequence the WFI-entry happens.

### Advisor directive (current session)

> "Don't code yet — fw-blob diss task is still running on another host; its results will almost certainly redirect T271 anyway — because 'what wakes pciedngl_isr' and 'what triggers shared-publish' are likely the same protocol question viewed from two sides."

Action: park T271 coding. Wait for fw-blob diss task to land. When results arrive, redesign T271 with the wake/publish protocol in mind.

### What this does NOT invalidate

- The code audit (phase6/t269_code_audit_results.md) is still useful — its wedge-timing analysis, `pci=noaer` observation, threaded-IRQ analysis, and Candidates B/C/D/E/F are independent of this blocker.
- The T270-BASELINE finding (substrate reproducibility) is unaffected.
- Candidates B (remove `pci=noaer`) and C (add `pci=noaspm`) become higher-priority because they don't require shared-info to be populated.

### Substrate budget status

No hardware fired. Cold-cycle window still ~open (boot 0 at 07:58 BST, ~15 min old). If we want to fire anything soon: Candidate B (remove `pci=noaer` from boot cmdline) or Candidate C (add `pci=noaspm`) are the viable single-variable next tests, but both require reboot config changes and possibly another cold cycle.

No immediate fire needed. Waiting for fw-blob diss + user direction.

---

## POST-FW-BLOB-DISS REFRAME (2026-04-24 08:40 BST — **fw-blob diss task landed and dovetails with T271 pre-code blocker into a coherent reframe. No new hardware fires; pure documentation update.**)

### What the fw-blob diss settled

Full analysis: `phase6/t269_pciedngl_isr.md`. Key factual outcomes:

1. **pciedngl_isr entry at blob 0x1C98** (Thumb). Confirmed via string cross-refs `"pciedngl_isr called\n"`, `"pciedngl_isr"`, `"pciedev_msg.c"`, `"pciedngl_isr exits"` at 0x40685/0x4069D/0x406B2/0x406E5/0x40733 — all referenced by this function's body.
2. **Wake bit**: `pciedngl_isr` tests bit 0x100 of a software ISR_STATUS at `*(pciedev+0x18)+0x18)+0x20`. Value 0x100 matches `BRCMF_PCIE_MB_INT_FN0_0` in upstream brcmfmac (pcie.c:954). ACK via W1C (write-one-to-clear) of the same bit.
3. **No fw-side host-facing register writes** on wake. All response via TCM ring writes that host polls. Doorbell W1C is the only MAILBOXINT mirror access.
4. **No panic/reboot/host-watchdog string in blob**. Fw can sit in WFI indefinitely without self-destructing. The host wedge is NOT fw-initiated. All `"watchdog"` strings refer to periodic soft-timers (`wlc_phy_watchdog`, `wlc_bmac_watchdog`, `wlc_dngl_ol_bcn_watchdog`, etc.), not "host must respond" timers.
5. **Bit allocation**: `hndrte_add_isr` at 0x63C24 allocates the scheduler callback node, dispatches a class-specific unmask via a 9-entry thunk vector at 0x99AC..0x99C8 (→ 0x27EC region). For pciedngl_isr the allocated bit is 3 (flag=0x8).
6. **Upstream handshake protocol** (from reading our own `pcie.c` — not the blob):
   - Fw publishes `shared.flags |= BRCMF_PCIE_SHARED_HOSTRDY_DB1` (0x10000000, pcie.c:1016) as part of its init.
   - Host reads `shared.flags` (after `brcmf_pcie_init_share_ram_info` populates `devinfo->shared`).
   - ONLY if HOSTRDY_DB1 observed, host calls `brcmf_pcie_hostready` (pcie.c:2044) which writes H2D_MAILBOX_1 = 1.
   - Fw's already-unmasked FN0_0 bit fires → scheduler dispatches `pciedngl_isr` → handshake proceeds.

### Why the scaffold investigation (T258–T269) was doomed

Every scaffold (T258, T259, T260, T261, T262, T263) that wrote H2D_MAILBOX_1 did so **without observing HOSTRDY_DB1 first** — none of them even read `shared.flags`. Three possibilities:
- Fw had unmasked FN0_0 but not populated `pciedev+0x18` sub-struct → ISR NULL-derefs on its first read → fw ARM crashes silently mid-ISR → bus stops responding → host MMIO wedges.
- Fw had not yet unmasked FN0_0 → early doorbell lost (edge-sensitive) or latched (level-sensitive) — either way, harmless, but…
- …The fact that T262/T263 (no doorbell at all) also wedged rules out "only the doorbell ring wedges" — the scaffold-line mere act of subscribing MSI + IRQ on BCM4360 is already producing a wedge.

Net: even with perfect handshake, the scaffold line was hitting a secondary wedge mode. Given (4), it is not fw-initiated. Most likely it's host-side: ASPM-L1 exit timing, MSI-vector routing, or a kernel spinlock path that depends on a device state that doesn't exist because fw hasn't initialized it. Candidates B/C/E from the code audit address some of these.

### Dovetail with T271 pre-code blocker

The pre-code check surfaced: **sharedram_addr at TCM[ramsize-4] is never populated by fw** (T247 observed 0xffc70038 NVRAM trailer unchanged across all 23 dwells through t+120s). Per the fw-blob analysis section 5.2, sharedram publish happens as part of pcidongle_probe — which happens AFTER `hndrte_add_isr(pciedngl_isr, ...)` and BEFORE fw advertises HOSTRDY_DB1. Logical chain:

```
si_attach (T252: 0x92440)
   → wlc attach (T251: saved-LR 0x68D2F)
   → wlc_bmac_attach (T251: saved-LR 0x68321)
   → ... gap we can't see ...
   → pcidongle_probe
     → hndrte_add_isr(pciedngl_isr) — allocates bit 3, unmasks FN0_0
     → publishes sharedram_addr at ramsize-4
     → publishes shared.flags |= HOSTRDY_DB1
     → (now host would see flags and safely ring doorbell)
```

T247 evidence: TCM[ramsize-4] never changes → sharedram never published → **pcidongle_probe did not complete its publish phase** (or ran but never got that far).

T257 evidence (WFI is DEFINITIVE): the scheduler reached a point where no callback's flag bit matched, so it went to idle loop → WFI.

Combined: **fw is stuck in WFI somewhere BEFORE pcidongle_probe's sharedram-publish point**. The scheduler is waiting on a pending-events bit that never fires — a bit that something else should have set during init.

### Updated hang bracket (tighter than session start)

| Point | Evidence |
|---|---|
| RTE boot banner | T250 ring-dump (`"RTE (PCIE-CDC) 6.30.223 (TOB)"`) |
| si_attach completes | T252 decode of 0x92440 (si_info-class struct with CC base 0x18001000 cached) |
| wlc attach / bmac attach entered | T251 saved-LR 0x68D2F / 0x68321 near those function bodies (α branch, now supported but not proven) |
| **fw enters WFI** | T257 DEFINITIVE (host harness bypasses MSI setup; no IRQ ever arrives) |
| **pcidongle_probe publish NOT reached** | T247 × T269-FW dovetail (ramsize-4 unchanged; fw-blob says publish happens inside pcidongle_probe) |

Hang region: between wlc_bmac_attach completion and pcidongle_probe's publish step. Inside that region, fw runs its scheduler, dispatches enough init callbacks to reach some waiting point, then the scheduler's pending-events word has no bit set → scheduler goes to WFI.

### What this invalidates / moots / keeps

| Item | Status |
|---|---|
| T271 / Candidate A (add init_ringbuffers before scaffold) | **MOOT** — pcidongle_probe-gated shared-publish was assumed and doesn't happen. |
| Scaffold-line investigation (T258–T269 shape) | **BLOCKED** pending fw reaching pcidongle_probe. Not abandoned; paused. |
| T270-BASELINE substrate reproducibility | **UNAFFECTED** — still holds. |
| Code audit (phase6/t269_code_audit_results.md) | Mostly still useful; specific scaffold-fix candidates A–F are now: A moot; B/C/E still live for "why does the *scaffold act of MSI subscription* also wedge"; D/F deprioritized. |
| fw-blob diss (phase6/t269_pciedngl_isr.md) | **Done.** No further work on pciedngl_isr needed until fw reaches it. |
| Hardware substrate | Still clean-ish (~40 min into boot; drift may have started); no fires pending. |

### New productive thread: T272-FW

Trace the fw init chain between wlc_bmac_attach completion and pcidongle_probe entry. Goals:

- Find wlc_attach's return point in the caller, and what function is called next.
- Map the init sequence from there up to pcidongle_probe.
- Identify any step in that sequence that:
  - reads a HW register in a way that could block on unclocked-core access, or
  - schedules an RTE callback + returns to scheduler (legitimate — but then something must set that callback's flag bit), or
  - tail-calls into a dispatcher that's waiting on an event bit that requires a host action we haven't taken.

Output: `phase6/t272_init_chain.md` describing the gap + specific init-step candidates.

Advisor call if the gap is large or ambiguous. No new hardware fires until this analysis produces a concrete candidate.
