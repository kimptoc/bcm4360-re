# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 22:55 BST, PRE-TEST.262 — **Common-scaffold control run needed. T261 proved `H2D_MAILBOX_1` doorbell-alone is also benign through the full emitted 4.9s timeline: 49 emitted samples, `MAILBOXINT=0`, `buf_ptr=0x8009CCBE`, `irq_count=0` throughout, matching T260 mask-only. Therefore neither write alone is the trigger. The surviving common factor behind the crash is now the shared T260 scaffold itself: `pci_enable_msi` + `request_irq` + 50×{read `MAILBOXINT`, read `buf_ptr`, `msleep(100)`, `pr_emerg`}, with the machine dying before the final `t+125000ms` / summary print. Current post-crash PCIe state after SMC reset is clean: root port `00:1c.2` on `03/03`, `<MAbort-`; endpoint `03:00.0` present with BAR0/BAR2 assigned. Boot 0 up since 22:53 BST.**)

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

1. **Code change needed**: add a third T260-family control param/block, e.g. `bcm4360_test262_msi_poll_only=1`, reusing the same T259 safe handler but skipping both writes.
2. **Artifact hygiene**: preserve `phase5/logs/test.260.journalctl.txt` and `phase5/logs/test.261.journalctl.txt` as the paired evidence set.
3. **Current reading**: because both split-write variants failed at the same late boundary, the next test should target the shared scaffold before revisiting any firmware-wake theory.
4. **Git discipline**: commit/push the POST-T261 notes before any new code or `insmod`.

---

## PRE-TEST.259 (2026-04-23 22:xx BST, boot 0 — **Safe IRQ handler + MSI enable + intr_enable + hostready + drift probe**. Direct-evidence variant addressing T258's "wedge during idle sleep" failure mode.)

### Hypothesis

POST-TEST.258 established (A') causation circumstantially: enabling MAILBOXMASK+hostready wedged the host during idle sleep, consistent with fw waking from WFI → raising an IRQ → no registered handler → kernel deadlock. T259 closes the evidence gap by registering a minimal handler first.

**If handler counter > 0 and buf_ptr advances in the 5s post-enable window**, (A') is directly confirmed: fw woke, ran scheduler, dispatched ISR, printed to ring.

**If handler counter == 0 and no wedge**, the T258 wedge mechanism was something other than unhandled IRQ (needs further investigation).

**If still wedges despite handler**, fw-raised IRQ is not the wedge cause; bus-level side effect of MAILBOXMASK/H2D_MAILBOX_1 writes is the more likely explanation.

### Design

| Stage | Action | Purpose |
|---|---|---|
| t+120000ms | `BCM4360_T258_BUFPTR_PROBE("t+120000ms")` | Baseline buf_ptr (pre-enable), same as T258 |
| +immediate | `pci_enable_msi(pdev)` | Allocate MSI vector (so new_irq is ours, not shared with other devices) |
| +immediate | `request_irq(pdev->irq, bcm4360_t259_safe_handler, IRQF_SHARED, "t259_safe", devinfo)` | Register handler BEFORE enabling MAILBOXMASK |
| +immediate | `brcmf_pcie_intr_enable(devinfo)` | Unmask fw-side IRQ output (MAILBOXMASK=0xFF0300) |
| +immediate | `brcmf_pcie_hostready(devinfo)` | Doorbell fw (H2D_MAILBOX_1=1) |
| +5000ms wait | `msleep(5000)` | Let fw wake, run, print |
| t+125000ms | Read `bcm4360_t259_irq_count` + `bcm4360_t259_last_mailboxint`, then `BCM4360_T258_BUFPTR_PROBE("t+125000ms")` | Direct evidence: IRQ arrived + fw printed |
| cleanup | `brcmf_pcie_intr_disable` → `free_irq` → `pci_disable_msi` | Clean shutdown before rmmod |

**Safe handler behavior**:
- Reads MAILBOXINT (returns IRQ_NONE if 0 — cooperates with shared IRQ)
- ACKs by writing status back
- Masks MAILBOXMASK=0 to prevent IRQ storm
- Increments atomic counter
- Returns IRQ_HANDLED

**Module param**: `bcm4360_test259_safe_enable_irq=1`. Gates the entire enable block.

### Next-step matrix

| Observation | Implication | T260 direction |
|---|---|---|
| irq_count > 0 AND buf_ptr @ t+125s > buf_ptr @ t+120s | **(A') directly confirmed.** Fw woke, ran scheduler, ISR fired, ring advanced. Decode `last_mailboxint` to see which doorbell bits fw pulsed. | Decode ring content. Design T260 to let fw progress further (supply shared-struct fields ISR needs). |
| irq_count > 0 AND buf_ptr unchanged | Fw woke the CPU (IRQ fired) but no console print. ISR may have run but not called a tracing path. | Read `last_mailboxint`, correlate with pciedngl_isr ACK bits. |
| irq_count == 0 AND buf_ptr unchanged AND no wedge | Fw did not wake, but host survived. (A') still favored but IRQ delivery path to host is broken. | Investigate MSI target setup, MailboxInt register, intr-ctrl. |
| Host wedges again (like T258) | Wedge not caused by unhandled IRQ. Something about the register writes themselves triggers the hang. | Split enable sequence: try MAILBOXMASK-only vs hostready-only variants. |
| Counter 0x9d000 = 0x43b1 across 23 dwells | test.89 frozen-ctr still holds (n=8 replication). | No action. |

### Safety

- Handler never dereferences `devinfo->shared.*` (the T258 concern with brcmf_pcie_isr_thread's handle_mb_data → TCM[0] corruption).
- Handler only touches `devinfo->reginfo->{mailboxint, mailboxmask}` — identical registers to brcmf_pcie_intr_disable (already well-tested in our codebase).
- MSI enable uses stock kernel infrastructure (pci_enable_msi). IRQF_SHARED cooperates with any other driver on the line.
- If request_irq fails, we bail out WITHOUT calling intr_enable/hostready. No wedge risk.
- Cleanup path disables intr + frees IRQ + disables MSI before returning. No dangling state.
- Wedge possibility: if the wedge is not IRQ-related, we still wedge. Platform watchdog expected to recover (n=3 streak now).

### Code change outline

1. **(done)** Module param `bcm4360_test259_safe_enable_irq` + atomic counters + `bcm4360_t259_safe_handler` already added at pcie.c:692-725.
2. **(pending)** Add T259 invocation block in ultra-dwells branch right after the T258 block (pcie.c:3741-ish).
3. **(pending)** Extend T239 ctr gate at pcie.c:3542 to include test259_safe_enable_irq.
4. **(pending)** Build + verify modinfo + strings.

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
    bcm4360_test259_safe_enable_irq=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T258 NOT set (mutually exclusive — only one enable variant fires). Older test params (T249/T250/T251/T252/T253/T255/T256) NOT set.

### Expected artifacts

- `phase5/logs/test.259.run.txt`
- `phase5/logs/test.259.journalctl.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet rebuilt — T259 invocation block + ctr-gate extension still to add.
2. **PCIe state**: expected clean (Mem+ BusMaster+, MAbort-) — check before fire.
3. **Hypothesis**: stated — `irq_count > 0 AND buf_ptr drift` = (A') directly confirmed; no wedge with handler = unhandled-IRQ was T258 wedge cause.
4. **Plan**: this block (committed before code change).
5. **Host state**: boot 0 started 21:21:01 BST, no brcm loaded.

Advisor-reviewed design. Code + build + fire pending.

---

## POST-TEST.259 (2026-04-23 21:4x BST — T259 fired; surpassed T258, captured irq_count+last_mailboxint, then wedged just after post-wait probe)

### Timeline

Boot -1: 21:21:01 → 21:48 (auto-reboot). Insmod 21:39:27, ultra-dwell ladder ran fully through t+120000ms, enable sequence + 5s sleep + post-wait probe all completed. Machine wedged immediately after the post-wait pr_emerg (before the t+125s dwell log could print).

### What test.259 landed (facts)

**Baseline at t+120000ms (pre-enable, same as T258):**
```
buf_ptr[0x9CC5C] = 0x8009CCBE
ring_tail[0x9CC20..0x9CC5C] = 14 × STAK canary + "100\0" + buf_ptr copy
```

**Enable sequence:**
```
test.259: pci_enable_msi=0 prev_irq=18 new_irq=79
test.259: request_irq ret=0
test.259: triggering intr_enable + hostready at t+120s (handler registered)
test.259: intr_enable + hostready done; sleeping 5s
test.259: post-wait irq_count=0 last_mailboxint=0x00000000
[WEDGE — no further lines]
```

All 5 setup/probe lines printed. MSI was successfully allocated (old IRQ 18 → new IRQ 79). Handler registered. Both register writes completed (identical to T258's success). 5-second sleep completed. Post-wait probe read atomic counters cleanly.

### What test.259 settled (facts)

- **No IRQ arrived in the 5s post-enable window.** `irq_count=0` AND `last_mailboxint=0x00000000` — handler never fired, OR fired and always saw MAILBOXINT=0 (returning IRQ_NONE with no atomic_inc). Shared-IRQ semantics + atomic nature of the counter make it very unlikely an IRQ was missed silently.
- **T258's circumstantial "unhandled IRQ caused wedge" reading is REFUTED.** With MSI enabled + IRQF_SHARED handler registered, any fw-raised IRQ would have been consumed via MSI vector 79. irq_count=0 says no IRQ was delivered; host still wedged at the same ~5s mark as T258. Therefore the wedge mechanism is not "unhandled IRQ storm."
- **Fw ARM core did not wake the host side via IRQ** — whether because it didn't wake at all, OR it woke but didn't set any bit in the MAILBOXINT register, OR its MSI target wasn't configured (MSI capability on the chip needs configuration fw-side that our driver doesn't do in this test path).
- **The wedge happens in a very narrow window**: between pr_emerg #5 (post-wait, 21:41:53) and pr_emerg #6 (t+125000ms post-enable dwell, never printed). Code between them is trivial (string formatting + printk plumbing). The wedge cause is either delayed from an earlier operation (register write side-effect) or something non-local (fw-side ARM wake → PCIe-link disturbance).
- **Candidate wedge mechanisms (none privileged by evidence yet)** — all are consistent with the captured data:
  1. **Posted-write completion timeout**: MAILBOXMASK or H2D_MAILBOX_1 write bounced back as a chipset-level fault ~5s later (5s is suspiciously close to default PCIe completion timeouts).
  2. **MSI vector mis-routing**: `pci_enable_msi` changed vector 18→79; a fatal chipset MCE after MSI retarget.
  3. **ASPM L1→L0 transition**: bus activity from the doorbell forces an L-state transition that hits a chipset bug.
  4. **Fw wake + DMA to unconfigured ringbuffer**: ringbuffers aren't set up in our test path (T257), so if fw woke and tried any DMA it'd write to random PCIe addresses → fatal.
  5. **Fw wake + unclocked backplane access → TAbort**: fw ARM woke, tried SB access before PMU clock gated that core, TAbort propagated via chip's PCIe core as fatal.
- **buf_ptr = 0x8009CCBE at t+120s (unchanged from start)** — ring didn't advance during the dwell ladder (same as T258), consistent with fw asleep in WFI.

### What test.259 did NOT settle

- Whether fw actually woke or not (no post-enable buf_ptr reading captured).
- Which register write is the root trigger (MAILBOXMASK vs H2D_MAILBOX_1). Both fire, both complete, but one of them starts the chain that wedges the host ~5s later.
- Whether the ~5s delay is a PCIe transaction timeout, a firmware timer, or ASPM-related (L1 → L0 transition).

### Outstanding hypotheses

- **(A')**: fw CPU is in WFI waiting for IRQ. REMAINS THE FW HANG MECHANISM (per T257 host-side audit — no MSI/MAILBOXMASK/hostready in our test path).
- **Host-wedge mechanism (undetermined)**: enabling MAILBOXMASK and/or pulsing H2D_MAILBOX_1 starts a chain that wedges the host ~5s later. Multiple candidate mechanisms listed above, none privileged by current evidence. Host-wedge is separate from the fw hang.

### Next-test direction (T260 — split enable + timeline probes, advisor-confirmed)

Advisor-confirmed approach:

1. **Mask-only first (safest).** Module param `bcm4360_test260_mask_only=1` — write MAILBOXMASK=0xFF0300 but DO NOT write H2D_MAILBOX_1. Fw stays asleep (no doorbell). If this alone wedges after 5s, the trigger is purely host-side (posted-write side-effect or chipset fault), and we eliminate candidates (4) and (5).
2. **Doorbell-only second, conditional on mask-only being benign.** Module param `bcm4360_test260_doorbell_only=1` — skip MAILBOXMASK, write H2D_MAILBOX_1=1. Discriminates whether the fw wake path is the trigger.
3. **Replace msleep(5000) with a 50× timeline probe**: `for (i=0; i<50; i++) { msleep(100); buf_ptr = read_ram32(0x9CC5C); mailboxint = read_reg32(MAILBOXINT); log("t+%dms buf_ptr=0x%x mailboxint=0x%x", ...); }`. If wedge happens before all 50 iterations finish, we get a partial timeline of what happened. Also lets us see whether fw EVER set a bit in MAILBOXINT (which would discriminate "handler never called" vs "handler called with status=0" — the key missing probe from T259).
4. **Also read host-side MAILBOXINT in post-wait block** (even in T259-style variants) — resolves the irq_count=0 ambiguity.

### Safety for T260

- Same envelope as T259 (MSI + handler + ACK-and-mask + clean free_irq/pci_disable_msi). 
- Mask-only is safer than doorbell-only — do it first.
- If mask-only is benign (no wedge in 5s+ of probing), it gives us a stable observation point we can run future tests from (e.g., re-test with doorbell after mask).
- Host-wedge still expected in at least one variant. Plan for 2+ test runs (n=10+ wedges at this point, SMC reset pattern now well-established).

---

## POST-TEST.257 (2026-04-23 21:0x BST — local host-side audit, no hardware test)

T257 was a pure local audit per advisor guidance. No module load, no crash. Deliverable: this block + `phase5/analysis/t257_audit.md` (to be extracted from this section into a standalone doc later if useful).

### What T257 settled (facts)

**Our test harness bypasses the entire normal IRQ/MSI setup.** Evidence:

1. **`brcmf_pcie_request_irq` (pcie.c:1937) calls `pci_enable_msi` + `request_threaded_irq`** — NOT CALLED in our test path. Its guard log `test.130: before brcmf_pcie_request_irq` never appears in T256 boot-1 journal.
2. **`brcmf_pcie_intr_enable` (pcie.c:1883) unmasks IRQs by writing `int_d2h_db | int_fn0 = 0x00FF0300` to MAILBOXMASK** — NOT CALLED in our path. MAILBOXMASK stays 0 (the intr_disable state).
3. **`brcmf_pcie_hostready` (pcie.c:1890) signals host-ready by writing 1 to H2D_MAILBOX_1** — NOT CALLED.
4. **Where our path ends**: the T238 ultra-dwells branch is at pcie.c:3427, inside `brcmf_pcie_download_fw_nvram` (starts pcie.c:2662). After the 120s dwell ladder it exits the if-else chain at pcie.c:3668 with a `t+120000ms dwell done` log, then returns from `download_fw_nvram`.
5. **The log sequence in T256 boot-1 confirms the bypass**: `test.130: after brcmf_chip_get_raminfo` (line 5888-ish) → `test.130: after brcmf_pcie_adjust_ramsize` → **no further test.130 logs** (init_ringbuffers, init_scratchbuffers, request_irq would each log but none appear). Then `test.163: before brcmf_pcie_download_fw_nvram` fires, we go INTO download_fw_nvram, take the test.238 branch, and the function returns without the rest of pcie_setup running.

### What T257 settled for the hang mechanism

**(A') WFI-idle is now DEFINITIVE, not just favored.** Causal chain:

1. Fw download completes, ARM core released via `brcmf_chip_set_active`.
2. Fw boots, prints RTE banner, runs its init including scheduler setup.
3. Fw registers `pciedngl_isr` (and possibly others) as scheduler callbacks, expecting host-driven IRQs.
4. Fw scheduler's main loop at 0x115C walks callback list. For each node, `tst r5, flag`. r5 is the return of `bl 0x9936` — an interrupt-status / event mask. **With no host-side IRQ delivery wired (no MSI, no MAILBOXMASK set), r5 never has any bit set**. No flag matches. All callbacks skipped.
5. Scheduler falls through to sleep-path at pcie fn 0x1182+, writes 0 to sleep-flag, calls barrier 0x1038, re-reads, and eventually tail-calls into the idle-loop at 0x11D0.
6. Idle-loop at 0x11D0 executes `bl 0x11CC` → `b.w 0x1C0C` → `b.w 0x1C1E` → **WFI**. CPU halts waiting for interrupt.
7. **Host never generates one.** MSI not enabled, no IRQ line registered, MAILBOXMASK = 0. Host's `brcmf_pcie_hostready` never fires to signal "host ready."
8. Fw sleeps indefinitely in WFI. TCM reads work (BAR2 accesses are memory-controller-level, don't need fw CPU awake).

### Separately: what causes the HOST wedge?

Fw-side is not the host-side wedge cause. The host wedge pattern varies:
- T247..T253, T255: wedge ~1s after t+90s probe burst (n=7 pattern)
- T256-1: wedge BEFORE fw release (no probes captured)
- T256-2: wedge ONLY during cleanup after t+120s dwell

The host wedge is likely in one of:
- rmmod cleanup touching a PCIe register after fw went idle
- AER escalation from a stale posted write
- Driver release path (pci_clear_master, ARM CR4 halt writes to a clock-gated core)

This is a SEPARATE issue from the fw WFI hang.

### Next-test direction (T258 — local code work + careful hardware test)

Two independent lines:

1. **Add IRQ-setup trigger option** (local code): enable `brcmf_pcie_request_irq` + `brcmf_pcie_intr_enable` + `brcmf_pcie_hostready` in a new test path gated by a module param (e.g., `bcm4360_test258_enable_msi=1`). Fire it AFTER the dwell ladder's t+120s probe. Observation: if fw's scheduler state drifts after enabling IRQ delivery, (A') is confirmed as NOT just "favored" but "causal." If drift still absent, there's a more subtle issue (MSI target address wrong, etc.).

2. **Host-wedge diagnosis** (orthogonal): add verbose dmesg / AER captures around rmmod path to see which register access triggers the host hang. Lower priority since the fw investigation is converging.

Advisor call recommended before committing to T258 code.

---

## PRE-TEST.258 (2026-04-23 21:xx BST, boot 0 — **IRQ-enable drift test**. Write MAILBOXMASK + H2D_MAILBOX_1 after the t+120s dwell. If fw's console buf_ptr advances in the 5s after, (A') causation fully demonstrated. Variant B (safe) — skip request_irq to avoid handle_mb_data corrupting TCM[0] reset vector.)

### Hypothesis

(A') WFI-idle is now confirmed: fw sleeps at 0x1C1E because host's test harness bypasses the normal IRQ-delivery setup (POST-TEST.257). **If we write MAILBOXMASK=0xFF0300 and then write H2D_MAILBOX_1=1, the fw-side doorbell should wake the CPU from WFI and make its scheduler run.** Fw's `bl 0x9936` would then see a non-zero pending-mask, node[0].flag=0x8 might match, pciedngl_isr fires and prints "pciedngl_isr called\n" into the console ring.

**Observable drift**: console buf_ptr at TCM[0x9CC5C] advances if ANY printf runs. This is unambiguous — the ring is fw-only-writer, host-read-only.

**Safety variant B**: skip `brcmf_pcie_request_irq` (which would register `brcmf_pcie_isr_thread` — that handler's `brcmf_pcie_handle_mb_data` reads `shared.dtoh_mb_data_addr` which is uninitialized in our test path, reads TCM[addr=0]=fw reset vector 0xb80ef000, then WRITES 0 TO TCM[0], corrupting the reset vector). Only do MAILBOXMASK + hostready writes — no host-side handler registration.

### Design

| Dwell | Action | Purpose |
|---|---|---|
| t+120000ms | existing probes + **read buf_ptr TCM[0x9CC5C]** | baseline (pre-enable) |
| t+120000ms +immediate | Call `brcmf_pcie_intr_enable(devinfo)` → writes MAILBOXMASK = 0xFF0300 | unmask IRQs on host side |
| +immediate | Call `brcmf_pcie_hostready(devinfo)` → writes H2D_MAILBOX_1 = 1 | fw-doorbell signal |
| +5000ms wait | `msleep(5000)` | let fw wake, process, print |
| t+125000ms | **Re-read buf_ptr TCM[0x9CC5C]** + 64B ring content ending at buf_ptr | observe drift |

**Probes added**: 2 × 1 u32 buf_ptr reads + 1 × 16 u32 ring content. Total 18 u32 — cheapest probe since T248.

**Module param**: `bcm4360_test258_enable_irq=1`. Gates both the register writes AND the new probe.

### Next-step matrix

| Observation | Implication | T259 direction |
|---|---|---|
| buf_ptr @ t+125s == buf_ptr @ t+120s AND ring content unchanged | Fw did NOT wake. Doorbell didn't reach CPU, OR CPU woke but found no work (flag mismatch). **(A') narrow reading weakened.** | Probe fw-side MailboxInt register (BAR0+0x48 PCIE2). See if fw's intr-pending bit is actually set. |
| buf_ptr @ t+125s > buf_ptr @ t+120s | **Fw ran code after doorbell.** (A') causation confirmed. Decode ring content to see what fw did. | Read decoded log; if "pciedngl_isr called\n" appears, node[0] dispatch path is live. Plan T259 to let fw progress further by supplying the shared-struct fields ISR needs. |
| Host wedges during write to MAILBOXMASK or H2D_MAILBOX_1 | Writes themselves wedge the bus. Different failure mode. | Back off; investigate BAR0 register accessibility more carefully. |

### Safety

- **Variant B skips request_irq** — no shared-memory dereferences, no posted-IRQ handler registered. Host just does two register writes.
- **Writes are to PCIE2 core at BAR0 window**: MAILBOXMASK=BAR0+0x4C, H2D_MAILBOX_1=BAR0+0x144. Both writes done in production brcmf_pcie_setup; they're the SAME writes that would happen in normal init.
- All BAR2 TCM reads safe as always.
- Wedge expected during cleanup (same pattern as T247..T256). Wedge is separate issue from fw state.

### Code change outline

1. New module param `bcm4360_test258_enable_irq`.
2. New invocation right after `test.238: t+120000ms dwell done` log:
   - `BCM4360_T258_BUFPTR_PROBE("t+120000ms")` — 1 u32 read
   - `if (bcm4360_test258_enable_irq) { brcmf_pcie_intr_enable(devinfo); brcmf_pcie_hostready(devinfo); msleep(5000); BCM4360_T258_BUFPTR_PROBE("t+125000ms"); BCM4360_T258_RING_DUMP("t+125000ms"); }`
3. Extend T239 ctr gate to include T258.

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
    bcm4360_test258_enable_irq=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts
- `phase5/logs/test.258.run.txt`
- `phase5/logs/test.258.journalctl.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet built — need to add T258 param + macros + invocation.
2. **PCIe state**: clean (Mem+ BusMaster+ MAbort- CommClk+).
3. **Hypothesis**: stated — buf_ptr drift after mask+hostready = (A') causation confirmed.
4. **Plan**: committed before code change.
5. **Host state**: boot 0 started 20:48:20 BST, uptime ~18 min, no brcm loaded.

Advisor-reviewed; variant B chosen for safety. Code + build + fire pending.

---

## POST-TEST.258 (2026-04-23 21:1x BST — enable sequence completed, novel wedge during 5s post-enable sleep)

### Timeline

Boot -1: 20:48:20 → 21:14:01 (25m41s; insmod at 21:11:39, wedge at 21:14:01, 2m22s into probe sequence). Host auto-rebooted (platform watchdog pattern continues). PCIe recovered clean.

### What test.258 landed (facts)

**Baseline probe at t+120000ms (pre-enable):**
```
buf_ptr[0x9CC5C] = 0x8009CCBE
ring_tail[0x9CC20..0x9CC5C] = 14 × 0x5354414B (STAK canary) + 0x00303031 ("100\0") + 0x8009CCBE (buf_ptr copy)
```

Nothing new in the ring tail — consistent with fw being asleep throughout the dwell ladder.

**Enable sequence:**
```
test.258: triggering intr_enable + hostready at t+120s          [both log lines fired]
test.258: intr_enable + hostready done; sleeping 5s             [both writes completed]
```

Both register writes (`brcmf_pcie_write_reg32` to MAILBOXMASK = 0xFF0300, and to H2D_MAILBOX_1 = 1) returned without error. msleep(5000) started.

**Wedge during msleep:**
- No `post-enable dwell` log
- No t+125s buf_ptr probe
- No kernel panic / Oops / AER / "unhandled IRQ" messages in boot -1 journal
- Host silently froze; platform watchdog rebooted ~7 min later at 21:21:01

### What test.258 settled (facts)

- **The register writes themselves succeeded.** MAILBOXMASK unmask + H2D_MAILBOX_1 doorbell both completed. The wedge happened AFTER both writes, during the 5s wait.
- **Novel wedge mechanism, triggered by the enable sequence.** T247..T253/T255 wedged ~1s after t+90s T248 probe (cleanup path). T256 wedged pre-fw-release (T256-1) or during post-dwell cleanup (T256-2). T258 wedged during a 5-second sleep with NO probe activity, NO cleanup path running — only the just-completed IRQ enable.
- **Strong circumstantial evidence for (A') causation.** The only difference between T258 and prior runs is the IRQ-enable sequence. Prior runs survived this same time window without issue (T256-2 reached t+120s + some cleanup before wedging). T258's wedge during the idle 5s wait means *something triggered by enabling IRQs* caused the host hang. Most consistent with: fw doorbell woke fw CPU → fw scheduler ran → some state change raised an interrupt on PCIe INTx line → host had no registered handler (no request_irq was called in our path) → kernel-level deadlock from unhandled/spurious interrupt.
- **Direct confirmation (buf_ptr drift) NOT captured** — post-probe never fired because wedge happened first. Wedge may have been within 0-100ms of fw waking.

### What test.258 did NOT settle

- Whether fw actually wrote new log entries to the ring after enable (couldn't capture post-probe).
- Which register write specifically causes the wedge (MAILBOXMASK or H2D_MAILBOX_1). The current test fires both before probing.
- Whether the wedge mechanism is "unhandled IRQ on INTx line" vs. something else. No kernel log evidence either way.

### Next-test direction (T259 — safer enable variant)

Two approaches to close the direct-evidence gap:

1. **T259a (safest): register a no-op IRQ handler BEFORE enabling MAILBOXMASK.** Add a tiny `irqreturn_t t259_dummy_handler(int irq, void *arg) { return IRQ_HANDLED; }` registered via `request_irq(pdev->irq, t259_dummy_handler, IRQF_SHARED, "t259_dummy", devinfo);` prior to the MAILBOXMASK write. Consumes any IRQ that arrives without wedging. Should then allow the post-probe to fire and capture buf_ptr drift directly.

2. **T259b (finer-grained): split the enable sequence into MAILBOXMASK-only and hostready-only variants.** Isolates which write triggers the wedge. Might inform whether fw reacts to mask or to doorbell.

Advisor call before committing to T259.

---
