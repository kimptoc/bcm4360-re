# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 23:26 BST, POST-TEST.263 — **Absolute-time chip-watchdog hypothesis FALSIFIED. T263-short (10-iter scaffold, 1s loop) crashed after 9 prints at t+120900ms — SAME N-1 / N pattern as T260/T261/T262 (49/50), but at wall-clock t+121000ms instead of t+125000ms. Crash timing SCALES with loop duration, not fixed time. Two equally-consistent readings: (a) crash fires at scaffold-elapsed-time ~= loop duration (duration-anchor), or (b) crash fires at the final loop iteration specifically. Neither privileged by current evidence. Advisor-framed T264 plan: drop the loop entirely, just MSI + request_irq + single msleep(2000) + cleanup — discriminates loop-structure vs duration-of-MSI-bound. Host auto-rebooted 23:24 BST, up 2 min.**)

---

## POST-TEST.260 (2026-04-23 22:08 BST run, recovered after reboot via `journalctl -b -1` — **Mask-only variant stayed benign through the emitted timeline; no firmware movement, no IRQs, no mailbox bits.**)

### Timeline

- `22:08:55`:
  - `pci_enable_msi=0 prev_irq=18 new_irq=79`
  - `request_irq ret=0`
  - `calling intr_enable (MAILBOXMASK write) — NO doorbell`
  - `intr_enable done; starting 50×100ms timeline`
- `22:08:55` through `22:09:00`:
  - emitted samples from `t+120100ms` through `t+124900ms`
  - every emitted sample was `mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0`
- No `timeline done` summary line was emitted.
- Userspace redirect file `phase5/logs/test.260.run.txt` is empty, but kernel messages were recovered into `phase5/logs/test.260.journalctl.txt`.

### What test.260 settled

| Observation | Reading |
|---|---|
| `MAILBOXMASK` write completed, MSI vector allocated, handler installed, and 49 emitted samples remained stable | `MAILBOXMASK=0xFF0300` alone is not the immediate trigger from T259. |
| `MAILBOXINT` stayed `0` throughout | Firmware never asserted mailbox-pending bits during the observed window. MSI delivery is irrelevant here because nothing fired. |
| `buf_ptr` stayed `0x8009CCBE` throughout | Firmware console ring did not advance. `(A')` still holds: firmware appears stuck/asleep until explicitly doorbelled. |
| Host still died before the final summary/cleanup print | The remaining likely trigger is the `hostready` doorbell from T259, not the mask write. A weaker alternative is late cleanup/teardown immediately after the loop, but T259's wedge happened after `hostready`, so the doorbell is still the main suspect. |

### Recommended next discriminator: PRE-TEST.261

**Goal:** isolate the `H2D_MAILBOX_1` write directly now that `MAILBOXMASK` has been cleared.

| Stage | Action | Purpose |
|---|---|---|
| t+120000ms | same baseline probes as T260 | Preserve comparability |
| +immediate | `pci_enable_msi` + `request_irq` | Keep the same safe host-side instrumentation envelope |
| +immediate | `brcmf_pcie_hostready(devinfo)` only | Directly test whether doorbell alone triggers wake/wedge |
| 50× iteration | same `msleep(100)` timeline logging `MAILBOXINT`, `buf_ptr`, `irq_count` | Observe whether doorbell causes mailbox traffic, ring drift, IRQs, or immediate death |
| post-loop | log final counters | Distinguish clean completion vs late wedge |
| cleanup | `free_irq` + `pci_disable_msi` | No mask disable needed because mask write is skipped |

### PRE-TEST.261 checklist

1. **Code state**: already in tree at `HEAD` (`1580e3e`, pushed) via `bcm4360_test260_doorbell_only=1`; no new code needed unless we decide to add even tighter post-loop markers.
2. **Artifact hygiene**: preserve `phase5/logs/test.260.journalctl.txt` as the recovered ground truth for T260.
3. **PCIe state**: re-check immediately before firing. Current post-reset snapshot is clean (`00:1c.2` secondary/subordinate `03/03`, `<MAbort-`; `03:00.0` present with BAR0/BAR2).
4. **Git discipline**: commit/push notes before any next `insmod`.
5. **Run choice**: first fire should be `bcm4360_test260_doorbell_only=1` with `T258/T259/T260_mask_only` unset.

---

## POST-TEST.261 (2026-04-23 22:39 BST run, recovered after reboot via `journalctl -b -1` — **Doorbell-only variant matched T260 mask-only exactly through the emitted timeline; still no firmware movement, no IRQs, no mailbox bits.**)

### Timeline

- `22:39:41`:
  - `pci_enable_msi=0 prev_irq=18 new_irq=79`
  - `request_irq ret=0`
  - `calling hostready (H2D_MAILBOX_1 write) — NO mask`
  - `hostready done; starting 50×100ms timeline`
- `22:39:41` through `22:39:46`:
  - emitted samples from `t+120100ms` through `t+124900ms`
  - every emitted sample was `mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0`
- No `t+125000ms` line and no `timeline done` summary line were emitted.
- Userspace redirect file `phase5/logs/test.261.run.txt` is empty; recovered kernel messages are saved in `phase5/logs/test.261.journalctl.txt`.

### What test.261 settled

| Observation | Reading |
|---|---|
| Doorbell-only emitted the same 49 stable samples as mask-only | `H2D_MAILBOX_1=1` alone is not the immediate trigger either. |
| `MAILBOXINT`, `buf_ptr`, and `irq_count` all remained flat | Firmware still did not wake, print, or raise any observable host interrupt. `(A')` remains intact. |
| T260 and T261 both die at the same late point, before `t+125000ms` and before the summary print | The crash is tied to the **shared scaffold** rather than to either individual write. Most likely candidates: MSI/request_irq state itself, the repeated 100ms sleep+poll loop, or the final loop boundary around the missing 50th sample. Cleanup is less likely because execution never reaches the summary print that precedes cleanup. |

### Recommended next discriminator: PRE-TEST.262

**Goal:** remove *both* writes and test the common scaffold by itself.

| Stage | Action | Purpose |
|---|---|---|
| t+120000ms | same baseline probes as T260/T261 | Preserve comparability |
| +immediate | `pci_enable_msi` + `request_irq` | Keep the suspected common factor |
| +immediate | **NO `intr_enable`, NO `hostready`** | Eliminate both register writes entirely |
| 50× iteration | same `MAILBOXINT` + `buf_ptr` + `msleep(100)` + `pr_emerg` loop | Test whether the crash comes from the shared instrumentation scaffold alone |
| post-loop | summary print | Determine whether execution can finally cross the 5.0s boundary cleanly |
| cleanup | `free_irq` + `pci_disable_msi` | Minimal teardown |

### PRE-TEST.262 checklist

1. **Code state**: done. Added `bcm4360_test262_msi_poll_only=1` in `pcie.c`, rebuilt `brcmfmac.ko`, and verified the new param via `modinfo`.
2. **Artifact hygiene**: preserve `phase5/logs/test.260.journalctl.txt` and `phase5/logs/test.261.journalctl.txt` as the paired evidence set.
3. **Current reading**: because both split-write variants failed at the same late boundary, the next test should target the shared scaffold before revisiting any firmware-wake theory.
4. **Git discipline**: commit/push the T262 code + pre-test notes before any new `insmod`.

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
