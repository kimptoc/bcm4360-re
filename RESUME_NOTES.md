# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-24 00:13 BST, POST-TEST.265 — **Fixed-timer-at-2s FALSIFIED. T265's msleep(500) scaffold crashed inside the 500ms sleep window (no "msleep done" marker), same pattern as T264's msleep(2000). This rules out a fixed ~2s trigger (would have fired 1.5s AFTER T265's msleep ended, during cleanup — but we never saw "msleep done"). Does NOT yet confirm duration-proportional: a fixed timer <500ms would fire within both windows and look identical. T266 plan: msleep(50) to shrink the upper bound 10×. Host auto-rebooted 00:12 BST, up 1 min.**)

## PRE-TEST.264 (2026-04-23 23:3x BST, boot 0 — **Loop-less scaffold: MSI + request_irq + single msleep(2000) + cleanup with markers. No MMIO reads. No loop.**)

### Hypothesis

POST-TEST.263 showed crash timing scales with loop duration. Two readings remain: (X) duration-anchor, (Y) final-iteration-specific. T264 discriminates by removing the loop entirely.

### Design

| Stage | Action | Pr_emerg markers |
|---|---|---|
| t+120000ms | same baseline T258 probe | (existing) |
| +immediate | `pci_enable_msi` | "pci_enable_msi=... new_irq=..." |
| +immediate | `request_irq` (same safe handler) | "request_irq ret=..." |
| +immediate | pr_emerg "entering msleep(2000)" | marker |
| msleep(2000) | single 2s sleep, NO reads, NO loop | — |
| +immediate | pr_emerg "msleep done; irq_count=... last_mailboxint=..." | marker |
| +immediate | pr_emerg "calling free_irq" | marker |
| — | `free_irq(pdev->irq, devinfo)` | — |
| +immediate | pr_emerg "free_irq returned" | marker |
| +immediate | pr_emerg "calling pci_disable_msi" | marker |
| — | `pci_disable_msi(pdev)` | — |
| +immediate | pr_emerg "pci_disable_msi returned" | marker |

### Next-step matrix (advisor-framed)

| Observation | Reading | Next test |
|---|---|---|
| Crash before "msleep done" (~2s in) | **Duration-anchor confirmed**. Loop structure was irrelevant. Candidates (2)/(3) still live. | T265: test shorter msleep (e.g., 500ms) — does crash scale with msleep too? |
| Crash between "msleep done" and "free_irq returned" | **Cleanup path is the crasher** (first-time visible). Probably in free_irq itself. | T265: try cleanup reordered, or skip cleanup. |
| Crash between "free_irq returned" and "pci_disable_msi returned" | **pci_disable_msi is the crasher**. | T265: skip pci_disable_msi, leave MSI enabled. |
| All 6 markers fire, module unloads cleanly | **Loop content (MMIO reads) necessary for trigger**. | T265: bisect — loop with just MAILBOXINT reads vs just buf_ptr reads. |

### Safety

- Even smaller envelope than T262/T263 — no loop, no reads.
- Cleanup path markers will print in sequence, giving us position-of-crash visibility for the first time.
- Same MSI+handler safety (consumes any stray IRQ).

### Code change outline

1. New module param `bcm4360_test264_noloop`.
2. Extend T239 ctr gate + T258_BUFPTR_PROBE gate.
3. Add new invocation block inside the ultra-dwells branch, separate from the T260/T262/T263 block (no shared scaffolding — simpler to read).

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
    bcm4360_test264_noloop=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

T258/T259/T260/T262/T263 NOT set.

### Expected artifacts

- `phase5/logs/test.264.journalctl.txt`
- `phase5/logs/test.264.run.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: duration-anchor vs cleanup-path vs loop-content — 3 outcomes give clean discrimination.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 23:24 BST.

Advisor-confirmed. Code + build + fire pending.

### T264 first fire (2026-04-23 23:42 BST) — **NULL TEST, scaffold never ran**

Crashed during test.188 pre-release TCM tail-snapshot, ~2 minutes BEFORE the dwell ladder or T264 scaffold would have started. Last event: `tail-TCM[0x9ffec]` at 23:44:44. No scaffold markers fired.

**Anomalous pacing**: in T263 (success), all 16 tail-TCM cells read in the same second (23:18:37 — <1ms each). In T264 (crash), 12 cells spread across 6 seconds (23:44:38 → 23:44:44 — ~500ms each). **Single MMIO reads were ~500× slower than T263**. Either the PCIe link was already struggling with L1→L0 retrains/timeouts, or the chip's PCIE2 core was stuck waiting.

Advisor read: this is a null test, not a failed test. Re-fire T264 unchanged. Two outcomes:
- Crashes again at test.188 → reproducible new failure mode; investigate chip state
- Reaches scaffold → first crash was one-off noise; scaffold gives real discrimination

Re-firing pending.

### T264 re-fire (2026-04-24 00:02 BST) — **scaffold DID fire; crashed during msleep(2000)**

- 00:02:10: scaffold entry — `pci_enable_msi=0 prev_irq=18 new_irq=79`, `request_irq ret=0`
- 00:02:10: `entering msleep(2000) — no loop, no MMIO`
- [crash]
- 00:03 auto-reboot (platform watchdog)

**No "msleep done" marker.** Crash happened during the 2s sleep — no MMIO reads, no loop, no cleanup code executed.

Also: test.188 tail-TCM pacing in the re-fire = all 16 cells in <1ms each (same as T263 baseline). The first-fire's 500ms/read was one-off noise.

### POST-TEST.264 findings (consolidated)

Advisor-framed matrix: which of the three outcomes fired?

| Outcome | Observed? | Reading |
|---|---|---|
| Crash before "msleep done" (within the 2s sleep) | ✓ YES | **Duration-anchor with no loop. Loop structure + MMIO reads are NOT required for the trigger.** The MSI+request_irq idle state for ~2s is sufficient. |
| Crash between "msleep done" and "free_irq returned" | — | N/A — "msleep done" never fired |
| Crash between "free_irq returned" and "pci_disable_msi returned" | — | N/A |
| Clean completion | — | N/A |

### What test.264 settled

- **Loop content (MMIO reads, pr_emerg, 100ms msleeps) is NOT required.** T264's single `msleep(2000)` with no reads triggered the same crash pattern.
- **The trigger is proportional to "scaffold duration" even when there's no loop.** Intended duration 2s → crash within the 2s window.
- **The cleanup path is STILL invisible.** None of `msleep done`, `calling free_irq`, `free_irq returned`, `calling pci_disable_msi`, `pci_disable_msi returned` fired. We still cannot discriminate "crash happens before cleanup would run" vs "cleanup runs and crashes".

### What test.264 did NOT settle

- Whether the crash is at a fixed time from scaffold start (e.g., always ~N seconds) OR proportional to intended duration (~duration). T260-T263 all had scaffold = intended_duration; T264 same. Still one-variable-coupled.
- Whether MSI enable, request_irq registration, or just "time passing" is the necessary ingredient. T264 has all three.
- Whether pr_emerg calls in the loop were contributing (e.g., printk overhead). T264 has none in its sleep window — still crashed, so pr_emerg is not required.

### Surviving candidate mechanisms (after T264)

1. ~~Loop-content necessary~~ — **FALSIFIED by T264**.
2. **PCIe/ASPM L1→L0 retrain after idle period**: link goes to L1 when CPU sleeps in msleep, then when it tries to wake, chip-side is unresponsive, retrain fails, MCE. Duration-anchor through L1-entry timer.
3. **Scaffold-duration bomb**: something about MSI+request_irq bound + wall-clock passing ~= intended duration triggers a fault. Still live, mechanism unknown.
4. ~~Cumulative MMIO effect~~ — **FALSIFIED by T264** (no reads in the sleep window).
5. **Cleanup path is crasher**: still live but currently has no positive evidence (we just never see its markers fire).
6. **Platform/root-port watchdog on the bridge**: the Intel PCH root port might have a timeout on the BCM4360 endpoint; after some period with no DMA or MMIO traffic, it flags the device bad.

### T265 direction (advisor call before committing)

Three candidate variants, one-variable-each:

- **T265a: msleep alone** (no MSI, no request_irq). If msleep(2000) alone crashes, time alone is enough. If it completes cleanly, MSI/request_irq matters.
- **T265b: MSI only** (pci_enable_msi + msleep, no request_irq). If crashes, MSI enable is sufficient trigger. If clean, request_irq matters.
- **T265c: short msleep** (msleep(500) with MSI + request_irq). Tests whether crash scales with msleep duration. If crash at 2s regardless, there's an absolute timer. If crash at 500ms, it's duration-proportional.

Most-discriminating: probably T265a (isolates whether time alone or MSI-bound matters). Calling advisor before committing.

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

**SMC reset needed** before firing T266.
