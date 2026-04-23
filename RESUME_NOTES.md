# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 23:3x BST, PRE-TEST.264 — **Loop-less scaffold. MSI + request_irq + single msleep(2000) + cleanup. No MMIO reads, no loop structure. Discriminates duration-anchor (crash at ~2s into msleep) vs cleanup-path (crash during free_irq/pci_disable_msi) vs loop-content (clean completion → MMIO reads needed for trigger).** Host stable, boot 0 up since 23:24 BST.)

---
## POST-TEST.262 (2026-04-23 23:05 BST run, recovered from boot -1 journal — **Scaffold-only crashes at SAME t+125s boundary; neither register write involved.**)

### Timeline (from `phase5/logs/test.262.journalctl.txt`)

- `23:03:18` insmod; dwell ladder runs through t+120000ms (all probes fine)
- `23:05:31` baseline at t+120000ms: `buf_ptr[0x9CC5C]=8009ccbe` — fw still asleep
- `23:05:31` scaffold entry:
  - `pci_enable_msi=0 prev_irq=18 new_irq=79`
  - `request_irq ret=0`
  - `skipping intr_enable + hostready; starting 50×100ms timeline`
- `23:05:31` → `23:05:36` (5s span): 49 emitted samples from `t+120100ms` through `t+124900ms`
  - every single sample: `mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0`
- `23:05:36` after `t+124900ms` sample: journal ends. No `t+125000ms` line. No `timeline done` summary. Host wedged.
- `23:07` platform watchdog reboot

### What test.262 settled (facts)

- **Both register writes are exonerated.** T262 omitted both `intr_enable` (no MAILBOXMASK write) and `hostready` (no H2D_MAILBOX_1 write), yet died at the same boundary (within ~100ms) as T260 (mask only) and T261 (doorbell only).
- **The trigger is in the shared scaffold.** Scaffold = `pci_enable_msi` + `request_irq` + a 5s loop of `{read MAILBOXINT via BAR0, read buf_ptr via BAR2, msleep(100), pr_emerg}`. One of those OR its duration is the trigger.
- **Firmware never moves during the window.** `MAILBOXINT=0` throughout 49 samples, `buf_ptr` flat, `irq_count=0`. If a fw-side watchdog is firing at t+125s, fw itself is doing nothing we can see first.
- **The crash landing is consistent across T260/T261/T262**: last visible print is ~t+124900ms, next scheduled print is ~t+125000ms, machine dies in between. ~100ms window. Very tight timing suggests a time-anchored event, not a cumulative state drift.

### What test.262 did NOT settle

- Whether the crash time is **fixed from chip-active** (~t+125s absolute from brcmf_chip_set_active) or **fixed from scaffold start** (~5s after pci_enable_msi). T260/T261/T262 all start scaffold at t+120000ms, so the two are indistinguishable on this data.
- Whether removing MSI (keeping only the poll loop) changes the outcome.
- Whether removing the poll-loop MMIO reads (keeping only MSI+request_irq idle) changes the outcome.
- Whether the T258_BUFPTR_PROBE baseline read at t+120000ms (which all T258+ tests do, unlike T256 and earlier) is contributing.

### Surviving candidate mechanisms (none privileged by evidence)

1. **Chip PMU watchdog at ~t+125s absolute**: fw ARM is halted in WFI with bus mastering still on. Some chip-internal watchdog (PMU or PCIE2 core) fires after ~125s of no fw progress, causes chip reset, host's next MMIO gets a TAbort, MCE → silent lockup.
2. **PCIe link L1→L0 retrain timeout**: ASPM L1 is enabled. After some period of low activity the link enters L1. One of our reads forces L1→L0; chip side is dead, retrain fails, RC times out, fatal.
3. **Scaffold-internal duration bomb**: something about holding `request_irq` active for 5s straight while MSI is enabled triggers a kernel or bridge-chipset bug.
4. **Cumulative MMIO effect**: after ~50 reads of MAILBOXINT + buf_ptr, some chip internal state overflows. Weakest — reads are to stable addresses that older tests exercised hundreds of times.

### Recommended next discriminator: PRE-TEST.263 — test the time-anchor hypothesis

**Design goal**: determine whether crash time is fixed from chip-active or fixed from scaffold start. One test gives us the answer.

| Variant | Scaffold start | Scaffold duration | Expected crash time if cand. (1) |
|---|---|---|---|
| T263a: scaffold-at-t+30s | t+30000ms | 100s loop (1000 iter × 100ms) | t+125000ms (95s into loop) |
| T263b: scaffold-at-t+60s | t+60000ms | 70s loop (700 iter × 100ms) | t+125000ms (65s into loop) |
| T263c: scaffold-at-t+120s, 30s loop | t+120000ms | 30s loop (300 iter × 100ms) | t+125000ms (5s into loop) — same as T260-262 |

**Simplest discriminator: T263a.** Start the scaffold at t+30000ms (90s earlier than T262). If crash still happens at wall-clock t+125000ms (95s into the scaffold loop), candidate (1) chip PMU watchdog is favored. If crash happens 5s into the scaffold (~t+35000ms), the scaffold itself is the trigger regardless of absolute time.

**Complication**: the dwell ladder currently spans t+0 → t+120000ms with many probes. We'd need to either pause it at t+30000ms and resume after scaffold (complex) or run a completely isolated scaffold from the dwell branch. Easier alternative is a new module param that triggers scaffold at t+30s and lets the ladder continue afterward (may or may not be safe post-scaffold).

**Simpler alternative: T263-short.** Keep scaffold at t+120000ms but ONLY 10 iterations (1s loop). If crash happens at t+121s (1s after scaffold start), it's scaffold-start-relative. If crash happens at t+125s (4s after scaffold ends, during post-loop summary or cleanup), it's absolute time from chip-active.

Advisor call before committing to T263 design.

---

## PRE-TEST.263 (2026-04-23 23:xx BST, boot 0 — **Scaffold-short variant: same MSI+request_irq+poll loop as T262 but with only 10 iterations (1s loop) instead of 50. Discriminates absolute-time crash (t+125s) vs scaffold-duration crash (t+scaffold+5s) vs cleanup-path crash (post-loop free_irq/pci_disable_msi).** Advisor-confirmed design: single variable changed (iteration count). All cleanup calls will now execute under t+125s for the first time across T260/T261/T262.)

### Hypothesis

T260/T261/T262 all crash at t+124900ms→t+125000ms regardless of which (or neither) register write is done. The crash is in the shared scaffold. Three surviving candidate mechanisms: (1) chip PMU watchdog at absolute t+125s, (2) PCIe/ASPM state after ~5s of MSI+poll, (3) scaffold-duration bomb.

**Key blind spot** (per advisor): T260/T261/T262 never execute the post-loop summary print, `free_irq`, or `pci_disable_msi` — all three are past the crash point. T263-short moves those calls to ~t+121000ms, giving them their first real execution.

### Next-step matrix

| Crash timing | Reading |
|---|---|
| ~t+121000ms (during 10-iter loop) | scaffold-start triggers something ~1s in. New clock. Candidate (3)b: bounded duration bomb at ~1s, not 5s. |
| ~t+121100–122000ms (just after loop, during `timeline done` print / `free_irq` / `pci_disable_msi`) | **Cleanup path is the crasher.** T260/T261/T262 never reached these — this would be a new, previously invisible failure mode. |
| ~t+125000ms (4s after scaffold ends, rest of path is unchanged) | Absolute-time candidate (1) confirmed: chip-side watchdog fires at ~125s from chip-active, independent of host activity. |
| Past t+125000ms into normal chip cleanup / rmmod | Scaffold's 5s duration in T260/T261/T262 was the trigger. Candidate (3) favored. |

### Design

Single new module param: `bcm4360_test263_short=1`. Behaves EXACTLY like T262 msi_poll_only but with 10 iterations instead of 50. Set by changing the loop bound and the variant label.

**Scaffold**: same as T262 — pci_enable_msi + request_irq (same handler) + NO register writes + loop(10) + timeline-done print + free_irq + pci_disable_msi.

**Log format**: `BCM4360 test.263 short: t+120100ms ... t+121000ms ...` (10 lines), then `timeline done`.

### Safety

- Same envelope as T262 plus shorter duration.
- Cleanup now executes under t+125s — if cleanup itself crashes, we get a new data point BUT also a new failure mode to recover from. Platform watchdog pattern reliable for recovery.
- One variable changed from T262 (iteration count). Everything else identical.

### Code change outline

1. New module param `bcm4360_test263_short`.
2. Extend T239 ctr gate + T258_BUFPTR_PROBE gate + scaffold block gate.
3. Inside scaffold block: `int _max_iter = bcm4360_test263_short ? 10 : 50;`, change loop bound, adjust variant label "short" and test-number string "263" when short.
4. Build, verify modinfo + strings.

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
    bcm4360_test263_short=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

T258/T259/T260/T262 NOT set.

### Expected artifacts

- `phase5/logs/test.263.journalctl.txt`
- `phase5/logs/test.263.run.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire (Mem+ BusMaster+ MAbort- CommClk+).
3. **Hypothesis**: stated — crash location splits cleanly across 4 readings.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 23:07 BST.

Advisor-confirmed. Code + build + fire pending.

---

## POST-TEST.263 (2026-04-23 23:19 BST run, recovered from boot -1 journal — **Scaffold-short crashed at scaled-down boundary: 9 prints out of 10 at t+120900ms. Absolute-time watchdog FALSIFIED; crash timing scales with loop duration.**)

### Timeline (from `phase5/logs/test.263.journalctl.txt`)

- `23:17:31` insmod; dwell ladder ran through t+120000ms
- `23:19:47` baseline: `buf_ptr[0x9CC5C]=8009ccbe` — fw still asleep (matches T260/T261/T262)
- `23:19:47` scaffold entry:
  - `pci_enable_msi=0 prev_irq=18 new_irq=79`
  - `request_irq ret=0`
  - `skipping intr_enable + hostready; starting 10×100ms timeline (1s loop)`
- `23:19:47` → `23:19:47` (within same wall-clock second): 9 emitted samples from `t+120100ms` through `t+120900ms`
  - every single sample: `mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0`
- `23:19:47` after `t+120900ms` sample: journal ends. No `t+121000ms` sample. No `timeline done` print. No `free_irq` marker. No `pci_disable_msi` marker. Host wedged.
- `23:24` platform watchdog reboot

### What test.263 settled (facts)

- **Absolute-time watchdog at t+125s is FALSIFIED.** T260/T261/T262 all crashed at wall-clock t+125000ms (which is 5s after scaffold entry AND 125s after chip-active — indistinguishable). T263-short crashed at wall-clock t+121000ms (1s after scaffold entry, 121s after chip-active). These are different wall-clocks. If a fixed-time chip watchdog existed at t+125s, T263 should have emitted all 10 samples and then crashed AFTER the loop ended, during cleanup (at wall-clock ~t+125s, 4s after T263's loop finished). It did not — it crashed during the loop.
- **Crash timing scales with scaffold duration.** T263 scaffold: 1s → crash at ~1s. T260/T261/T262 scaffold: 5s → crash at ~5s. Proportional to loop length.
- **The N-prints-out-of-N-expected pattern is consistent.** 9/10 for T263, 49/50 for T260/T261/T262. Host consistently dies after the last PRINTED iteration — either during the last iteration's body or at loop exit.
- **Cleanup path is still invisible.** None of the post-loop prints fired in T263 either (`timeline done`, `calling free_irq`, `free_irq returned`, `calling pci_disable_msi`, `pci_disable_msi returned`). So either the cleanup code never ran, OR it ran and crashed before its first print.
- **No kernel panic / MCE / AER / "unhandled IRQ" in boot -1 journal.** Silent lockup pattern unchanged.

### Readings (both equally consistent, advisor-framed — do not privilege)

| Reading | Interpretation |
|---|---|
| (X) Duration-anchor | Crash fires at fixed elapsed time from scaffold start, ~= loop duration. Loop length is irrelevant to the trigger — it just determines when the scaffold ends, and the crash is coincident with scaffold end. |
| (Y) Final-iteration-specific | Crash is triggered by something specific to the final iteration of the loop (e.g., scheduler exit from the final msleep/pr_emerg cycle, or the i<N comparison becoming false). |

T263 alone cannot discriminate these. T264 design below.

### Surviving candidate mechanisms (after T263)

1. ~~Chip PMU watchdog at fixed absolute time~~ — **FALSIFIED by T263**.
2. **PCIe/ASPM state after MSI+poll duration**: link enters L1 when scaffold ends, retrain fails. Still live.
3. **Scaffold-duration bomb**: something about the combination of MSI enabled + IRQ bound + wall-clock passing ~= scaffold duration triggers a fault. Still live.
4. **Cumulative MMIO effect**: 50 reads for T260, 10 reads for T263. Crash still happens. Weak, but not fully eliminated.
5. **Loop-structural**: exit from the for-loop cleanup / scheduler rescheduling at that point. Still live.

### Advisor-framed next test: T264 — loop-less scaffold

**Design goal**: remove the loop entirely. If T264 still crashes at ~msleep-duration into the sleep, loop structure is irrelevant (duration-anchor confirmed). If T264 completes cleanly, loop content (MMIO reads) is necessary.

**Scaffold**:
```
pci_enable_msi
request_irq (same safe handler)
pr_emerg "entering msleep(2000)"
msleep(2000)
pr_emerg "msleep done"
pr_emerg "calling free_irq"
free_irq
pr_emerg "free_irq returned"
pr_emerg "calling pci_disable_msi"
pci_disable_msi
pr_emerg "pci_disable_msi returned"
```

No MMIO reads. No loop. Single 2s sleep.

| Outcome | Reading |
|---|---|
| Crash at ~2s into msleep (before "msleep done") | Fixed-duration from MSI-bound state; loop structure is irrelevant. Candidate (2) or (3) favored. |
| Crash during/after free_irq (first time visible) | Cleanup path is the crasher. New failure mode. |
| Clean completion (all markers fire, module unloads) | Loop body (MMIO reads) are necessary for the trigger. T265 will bisect which read (MAILBOXINT vs buf_ptr). |

**Module param**: `bcm4360_test264_noloop=1`. Single variable change from T262 (loop → single msleep).

Ready to implement + fire.

---

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
