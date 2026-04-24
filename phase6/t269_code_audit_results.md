# T269-CODE — Host-side scaffold failure audit (T258–T269)

**Task brief:** `phase6/t269_code_audit.md`
**Pure static analysis.** No hardware fire, no module build, no `pcie.c` edits.
**Sources:** `phase5/work/.../brcmfmac/pcie.c`, `phase5/logs/test.258..269.journalctl.txt`, RESUME_NOTES.

---

## 1. Summary table: test → last marker → wedge point → recovery

| Test | Scaffold shape | Last marker | Scaffold-exec? | Wedge phase | Recovery |
|------|----------------|-------------|----------------|-------------|----------|
| T258 | `MAILBOXMASK` write + `H2D_MAILBOX_1` doorbell + `msleep(5000)` — NO `request_irq` | `"intr_enable + hostready done; sleeping 5s"` (post-write, pre-5s-sleep) | yes, mid-scaffold | inside 5s idle sleep (no `post-wait` marker) | watchdog reboot |
| T259 | `pci_enable_msi` + `request_irq(safe_handler)` + mask + doorbell + `msleep(5000)` | `"post-wait irq_count=0 last_mailboxint=0x00000000"` (sleep finished) | yes, full | crash in cleanup after `post-wait` (next marker `t+125000ms post-enable dwell` never fires) | watchdog reboot |
| T260 `mask_only` | MSI + request_irq + MAILBOXMASK + 50×{`msleep(100)` + MMIO-read} | `t+124900ms` (iter 49 / 50) | yes, loop ran to last iter | before `"timeline done"` — cleanup path | watchdog reboot |
| T260 `doorbell_only` | MSI + request_irq + doorbell + 50-iter poll | `t+124900ms` | yes | same as above | watchdog reboot |
| T262 | MSI + request_irq + 50-iter poll (NO mask/doorbell) | `t+124900ms` | yes | same — crashes during cleanup | watchdog reboot |
| T263 | MSI + request_irq + 10-iter poll (1 s total) | `t+120900ms` | yes | same — crashes during cleanup | watchdog reboot |
| T264 | MSI + request_irq + `msleep(2000)` (no MMIO) | `"entering msleep(2000)"` | partial — msleep never returned | inside the 2 s idle sleep | watchdog reboot |
| T265 | Same, `msleep(500)` | `"entering msleep(500)"` | partial | inside 500 ms idle sleep | watchdog reboot |
| T266 | Same, `msleep(50)` | `"entering msleep(50)"` | partial | inside 50 ms idle sleep | watchdog reboot |
| T267 #1 | MSI + request_irq + immediate cleanup (no sleep) | mid t+120 s probe burst (`test.247 → test.249` gap) | **no** — crash before scaffold entry | inside probe path preceding scaffold | watchdog reboot |
| T267 #2 | Same | mid t+120 s probe burst (earlier position) | **no** | same | watchdog reboot |
| T268 | T267 scaffold moved pre-dwell (right after `chip_set_active`) | `test.125: after reset_device return` (pre-firmware-download) | **no** — crash before `chip_set_active` | in `buscore_reset → get_raminfo` gap | watchdog reboot |
| BASELINE-POSTCYCLE (post-cold-cycle) | no scaffold, pure T238 ladder | `t+90000ms dwell` | n/a | t+90 s → t+120 s dwell gap | watchdog reboot |
| T269 | T238 ladder with early-exit at t+60 s (scaffold-free) | `t+45000ms dwell` | **no** — crash before early-exit branch point | t+45 s → t+50 s dwell gap | watchdog reboot |

### Immediate observations

- **Every T258–T269 wedge is a silent host lockup.** No further kernel lines after the last marker; only the platform watchdog reboot recovers. No `Oops`, `BUG`, `panic`, `hung task`, `call trace`, `softlockup` or MCE appears in any journal. (The `grep -c` counts in the 20-range for boot -1 / -0 are all boot-boilerplate: `ACPI: LAPIC_NMI`, `Firmware Bug`, `drm panic` etc. — not real crash traces.)
- **The kernel cmdline for every boot is `… pci=noaer …`.** AER reporting is disabled system-wide, so no upstream PCIe uncorrectable-error would ever be logged. Whatever the chip is doing to the link, we are **deliberately blindfolded.**
- **Two distinct crash regimes** emerge:
  1. **T258 / T264 / T265 / T266: wedge inside an idle sleep** (5 s / 2 s / 500 ms / 50 ms — no MMIO during the sleep). "msleep done" never fires.
  2. **T259 / T260 / T261 / T262 / T263: wedge during *cleanup* after an active MMIO poll loop completed.** The last in-loop print fires; the post-loop `"timeline done"` / `"free_irq"` / `"pci_disable_msi returned"` markers do not.
- **T267 / T268 / T269 are not scaffold-related failures.** The scaffold never executed. These crashed in the probe path or dwell ladder *before* the scaffold site, and correlate with the "hardware drift" signal that emerged at n=20+ wedges.

---

## 2. Upstream init-order vs our harness — what the scaffolds skip

### 2.1 Canonical upstream path (`brcmf_pcie_setup`, post-download branch, line ~6378–6437)

```
devinfo->state = BRCMFMAC_PCIE_STATE_UP
brcmf_pcie_init_ringbuffers        → allocs DMA-coherent common rings; memcpy_toio's host ring addrs into TCM shared struct at ring_info_addr
brcmf_pcie_init_scratchbuffers     → allocs DMA scratch + ringupd buffers; publishes dma_handle + length at fixed offsets in shared struct
brcmf_pcie_select_core(PCIE2)
brcmf_pcie_request_irq             → pci_enable_msi + request_threaded_irq(quick_check_isr, isr_thread, IRQF_SHARED)
  - quick_check_isr: reads MAILBOXINT, if non-zero: intr_disable, return IRQ_WAKE_THREAD
  - isr_thread:      reads/acks MAILBOXINT, dispatches handle_mb_data / msgbuf_rx_trigger, re-enables intr
hook msgbuf commonrings (bus->msgbuf->commonrings[i])
init flowrings
init_waitqueue_head(mbdata_resp_wait)
brcmf_attach                       → builds netdev + protocol stack
brcmf_pcie_bus_console_read
brcmf_pcie_fwcon_timer(true)
…
// later, via brcmf_pcie_preinit (bus op) at line 2578:
brcmf_pcie_intr_enable             → writes MAILBOXMASK = int_d2h_db | int_fn0
brcmf_pcie_hostready               → writes H2D_MAILBOX_1 = 1  (only if SHARED_HOSTRDY_DB1)
```

### 2.2 Our BCM4360 path

The modified `brcmf_pcie_setup` (line ~6266) runs `download_fw_nvram` then **returns early at line ~6368** inside `if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)`. `state` remains `BRCMFMAC_PCIE_STATE_UP`-not-set; `init_ringbuffers`, `init_scratchbuffers`, `select_core(PCIE2)`, `request_irq`, attach — all skipped. The test harness then relies on the probe-path dwell ladder + the T258–T267 scaffolds to do "just enough" of the upstream init at t+120 s.

### 2.3 What the scaffolds do and do NOT do

| Upstream step | In our scaffolds? | Consequence of skip |
|---------------|-------------------|---------------------|
| `init_ringbuffers` — populate ring-info shared struct with host DMA addresses | **NO** | Shared struct's ring-info fields retain whatever the firmware wrote at boot (chip-local pointers, not host DMA). Firmware, after doorbell, has no valid host address to DMA ring entries to. |
| `init_scratchbuffers` — populate scratch + ringupd DMA addrs | **NO** | Same class of issue: firmware DMAs targeting unresolved addresses. |
| `select_core(PCIE2)` before `request_irq` | **NO** (last core selected by probe path is whatever dwell probes left it on) | Register offsets referenced by `brcmf_pcie_read_reg32` use PCIE2 core base — if not selected, writes land in the wrong core's register window. |
| `request_threaded_irq(quick_check, isr_thread)` | **NO** — we register a non-threaded `bcm4360_t259_safe_handler` that just masks and ACKs | Functionally similar (we ACK MAILBOXINT and force mask=0 on entry), but we never invoke `handle_mb_data`. Firmware's mb-data handshake (e.g. `BRCMF_H2D_HOST_D3_INFORM`, fw-ready signalling) is silently dropped. |
| `brcmf_pcie_intr_enable` (MAILBOXMASK = `int_d2h_db \| int_fn0`) | T258/T259/T260-mask_only only | T262/T263/T264/T265/T266/T267 omit this — IRQs masked the whole time. |
| `brcmf_pcie_hostready` (H2D_MAILBOX_1 = 1) | T258/T259/T260-doorbell_only only | Doorbell to wake fw from WFI only fires in those three. |
| `brcmf_pcie_preinit` ordering (intr_enable + hostready AFTER attach + msgbuf hook) | **inverted** — our scaffolds do intr_enable+hostready BEFORE any ring setup | Inverted dependency: fw sees doorbell before host has published ring addresses. |

### 2.4 Load-bearing ranking of skips

1. **`init_ringbuffers` (CRITICAL).** `memcpy_fromio` reads fw-published ringinfo from TCM, writes ring host DMA addresses back. Without it, fw has no legal DMA target for any ring descriptor — any fw TLP to host post-doorbell hits an unmapped address. With AER masked, this produces a silent wedge rather than a logged UR/CA.
2. **`init_scratchbuffers` (CRITICAL).** Same class — scratch + ringupd buffers must be published before fw can DMA mb-data updates or ring state.
3. **`state = BRCMFMAC_PCIE_STATE_UP` gating (HIGH).** `isr_thread` guards `msgbuf_rx_trigger` and `intr_enable` on `state == BRCMFMAC_PCIE_STATE_UP`. Our state stays `DOWN` (we bail before the assignment at 6378), but we bypass isr_thread anyway — still, any upstream helper we call may silently no-op or take wrong branch.
4. **Threaded-IRQ split (MEDIUM).** Cosmetic vs state-UP test. Our safe handler does ACK + mask so at least IRQ vector doesn't storm, but we never dispatch `handle_mb_data`.
5. **`select_core(PCIE2)` before MMIO register writes (MEDIUM).** The dwell ladder does leave the core in a probed state; worth verifying the selected core at scaffold entry matches PCIE2.
6. **`brcmf_pcie_preinit` ordering (LOW-MEDIUM).** Upstream calls attach + all ring/scratch setup *before* intr_enable + hostready. Our T258/T259 flip this — we ring the doorbell before publishing any host DMA state.

---

## 3. Wedge modality — what we can and cannot say from journals

### 3.1 No kernel crash trace in any wedge

Across T258–T269 (excluding boot boilerplate):

```
grep -E 'AER|MCE |Oops|BUG|panic|hung task|general protection|call trace|unable to handle|softlockup'
```

returns **zero** post-boot-0 kernel crash indicators in any log. Every wedge manifests as: last driver `pr_emerg` prints, then the journal goes silent until the next boot (`Apr ... Command line: …`).

### 3.2 Kernel cmdline disables AER

Every journal shows the kernel cmdline `... pci=noaer intel_iommu=on iommu=strict ...`. AER is disabled by boot parameter, so:

- Uncorrectable PCIe errors (TLP UR, completer abort, ECRC, etc.) produce no `pcieport … AER` lines. They are still *handled* by the RC hardware, but nothing is logged.
- Fatal errors that would normally cascade to `device_release_driver` via AER do not do so. The chip is simply "gone" from the host's perspective.

With AER disabled, a silent wedge is consistent with **any** of:

- (a) **Bad upstream DMA** from chip to host (ring addr = 0 or junk) — RC drops, fw stalls waiting, host eventually hangs on next MMIO read to the stalled chip.
- (b) **PCIe link retrain / L1 exit failure** — chip drops link, host next MMIO to BAR0 hangs CPU in MMIO read abort.
- (c) **Kernel spinlock / IRQ-ctx deadlock** caused by our non-threaded handler. This should show a `hung task` entry eventually, but hung-task detection lives behind a 120 s watchdog; platform watchdog fires sooner.
- (d) **CPU stuck in an NMI-like condition** (CPU SMM, machine-check on bad MMIO). NMI watchdog *is* enabled — line 282 of T263 etc: `NMI watchdog: Enabled. Permanently consumes one hw-PMU counter.` — but no NMI-attributed print appears, so the NMI watchdog didn't fire either.

The absence of hung-task AND NMI-watchdog output is the strongest signal that the CPU is not just spinning in kernel context — it's **unresponsive**, likely in an MMIO-abort-stall where the kernel never gets control back to print anything. This is consistent with (a) / (b) but not (c) / (d).

### 3.3 Two wedge sub-modes correlate with "activity vs idle"

- **Idle-sleep wedges** (T258, T264, T265, T266): no MMIO during the sleep window; wedge mid-sleep. The host CPU is not accessing the chip, so we'd expect sleep to complete cleanly — the fact that `msleep done` never fires suggests the scheduler tick itself (which does no MMIO to BCM4360) is being blocked by something else, or the timer interrupt path is blocked.
- **Active-poll wedges** (T259, T260, T261, T262, T263): MMIO every 100 ms keeps the chip "poked"; wedge happens during cleanup, i.e. the transition from active-poll into `free_irq` / `pci_disable_msi`. In those transitions the first action (in our code) is `brcmf_pcie_intr_disable` (for mask_only) or direct `free_irq` — neither of which should be enough to wedge a normal system.

One reading: continuous MMIO to BAR0 keeps BCM4360 ARM out of WFI (it sees reads/writes and stays responsive). Ending the MMIO stream (either by entering `msleep` or by exiting the poll loop) lets the chip drift into a WFI-waiting-for-ring-state that was never provided, at which point an internal Broadcom watchdog (visible in the fw-blob at the PMU `pmuwatchdog` register we already read as 0x00000000 in T188) fires, resets the PCIe endpoint, and the host's next MMIO (either via timer IRQ hitting a PCI barrier, or explicit cleanup) stalls forever.

### 3.4 Why T267/T268/T269 are different

These three never reached the scaffold. Their wedges are in earlier probe-path code:

- T267 (both fires): mid `t+120000ms` probe burst — the dwell ladder itself, not the scaffold.
- T268: `test.125: after reset_device return`, deep in `brcmf_pci_buscore_reset → get_raminfo`. This is pre-firmware-download host code.
- T269: `t+45000ms dwell`, halfway up the dwell ladder — again in the ladder, before the `ultra_dwells_done` early-exit could even be reached.

These wedges are **hardware/state drift** symptoms. Earlier test runs today successfully traversed the same code paths. Accumulating chip state between fires (PCIe endpoint entering an unclean state after prior wedges) is the likeliest read. A cold AC power cycle at 06:30 bought exactly one clean late-ladder traversal (BASELINE-POSTCYCLE, 88 s of ladder), then drift restored within 23 min (T269, 46 s of ladder). These do not inform the scaffold-design question directly.

---

## 4. Host wedge "trigger component" — what we learned from T260-T266

Progressively peeling components out of the scaffold:

| Test | MSI | request_irq | MAILBOXMASK | doorbell | active poll | sleep | Wedge point |
|------|-----|-------------|-------------|----------|-------------|-------|-------------|
| T258 | — | — | **yes** | **yes** | — | 5 s | mid-sleep |
| T259 | **yes** | **yes** | **yes** | **yes** | — | 5 s | post-sleep, cleanup |
| T260 mask | **yes** | **yes** | **yes** | — | 50×100ms | — | cleanup |
| T261 doorbell | **yes** | **yes** | — | **yes** | 50×100ms | — | cleanup |
| T262 neither | **yes** | **yes** | — | — | 50×100ms | — | cleanup |
| T263 short | **yes** | **yes** | — | — | 10×100ms | — | cleanup |
| T264 noloop | **yes** | **yes** | — | — | — | 2000 ms | mid-sleep |
| T265 short | **yes** | **yes** | — | — | — | 500 ms | mid-sleep |
| T266 ultra | **yes** | **yes** | — | — | — | 50 ms | mid-sleep |

Read across T262 / T263 / T264 / T265 / T266: the *minimum* scaffold that still wedges is **`pci_enable_msi + request_irq + arbitrary idle interval`**, with or without any mailbox/doorbell writes. MSI + IRQ line subscription, on its own, is the scaffold's wedge-necessary condition.

Read across T258 vs T259/T260-T263: **duration of "MSI-bound + idle" is what matters, not the mailbox/doorbell writes.** Writing MAILBOXMASK+doorbell (T258) wedges mid-sleep. Writing nothing but staying MSI-bound (T262/T263/T264/T265/T266) also wedges. The common thread is that between `request_irq` and `free_irq`, the host is MSI-subscribed on the BCM4360 line.

This strongly suggests the trigger is **not** fw-side mailbox-driven (since T262/T263 don't write mailboxes at all, yet wedge). Candidate triggers surviving this analysis:

- **MSI storm / unhandled-irq escalation.** Disfavoured — `irq_count=0` in every log, handler never fires.
- **PCIe ASPM L1 entry while MSI is subscribed.** Enabled per LnkCtl readback. The chip may attempt L1 entry after 7 µs idle; the MSI vector subscription may interact badly with L1 exit latency tuning. Worth testing with `pci=noaspm` on the cmdline.
- **Chip-internal watchdog tripping after N ms of "host MSI-armed but no message" state.** Would fit: continuous-poll variants survive longer than idle-sleep variants (T260/T262 50 iters = 5 s vs T264 = 2 s, both wedge; but T260 wedges in cleanup ~5 s after scaffold entry, while T264 wedges inside the 2 s sleep). No tight time law.
- **Broadcom PMU watchdog** (`pmuwatchdog` register = `0x00000000` per T188 snapshot — already zero, so not counting; but some Broadcom designs arm PMU watchdog via fw-side write on wake-from-WFI). If fw arms a watchdog on wake and the host never serves the request, the chip self-resets → PCIe link torn down → host MMIO stall.

---

## 5. Specific code-change candidates (ranked)

No code changes in this task — these are hypotheses for future T270+ tests. Each is a **single minimal-change** discriminator that narrows the remaining candidate space.

### Candidate A (HIGH probability) — add `init_ringbuffers + init_scratchbuffers` before scaffold

**Design.** Before any T258/T259/T264-style scaffold block, call (inline, not via upstream helper if that simplifies the test gate):

```c
if (bcm4360_test270_ring_init) {
    int r = brcmf_pcie_init_ringbuffers(devinfo);
    pr_emerg("BCM4360 test.270: init_ringbuffers ret=%d\n", r);
    r = brcmf_pcie_init_scratchbuffers(devinfo);
    pr_emerg("BCM4360 test.270: init_scratchbuffers ret=%d\n", r);
}
// … then existing T264-style scaffold …
```

**Preconditions.** `devinfo->state` must be `BRCMFMAC_PCIE_STATE_UP` before `init_ringbuffers` is called (used by `brcmf_pcie_ring_mb_write_rptr`). Set it explicitly before the call — this single assignment may itself alter behaviour, which is informative.

**Discrimination.**
- If scaffold now completes cleanly (`free_irq` + `pci_disable_msi` markers fire, module unloads): **uninitialized ring/scratch buffers were the wedge cause.** Full headline.
- If scaffold still wedges at same bound (≤50 ms post request_irq for T266-shape): **ring-init is not the load-bearing skip**; look at ASPM or PMU watchdog next.
- If `init_ringbuffers` itself fails (returns ≠0): the fw-published ring info was corrupt — an earlier problem than we thought.

**Risk.** `init_ringbuffers` allocs DMA coherent memory, so failure mode if fw didn't land is a clean `-ENOMEM`, not a wedge. Safe to try.

### Candidate B (MEDIUM) — remove `pci=noaer` from kernel cmdline

**Design.** Edit NixOS boot config; remove `pci=noaer`. Refire T266 (simplest wedging variant).

**Discrimination.**
- If we now get `pcieport 0000:00:1c.0: AER: …` lines in the journal showing UR / CA / completer abort before the wedge: **candidate (a) confirmed** — chip is issuing bad TLPs upstream.
- If we get AER-correctable errors only (not fatal): informative, not wedge-cause.
- If journal still silent: AER is genuinely not firing; it's a different class of failure.

**Risk.** `pci=noaer` was presumably added for a reason (likely boot-time noise on this platform). Worth discussing with user before changing boot config; may add transient noise but makes the chip audible during tests.

### Candidate C (MEDIUM) — add `pci=noaspm` to kernel cmdline

**Design.** Boot with `pci=noaspm` appended.

**Discrimination.**
- If T266 no longer wedges: **ASPM L1 interaction** is the mechanism; BCM4360 on Mac firmware may have L1 entry tuning that's incompatible with the host RC at these latencies.
- If still wedges: ASPM is ruled out.

**Risk.** Minimal — ASPM is a power-saving knob, disabling costs idle power only. Zero risk to test state.

### Candidate D (LOW) — replace handwritten MSI+request_irq with `brcmf_pcie_request_irq()`

**Design.** In the scaffold, call upstream's `brcmf_pcie_request_irq(devinfo)` (which internally does `intr_disable`, `pci_enable_msi`, `request_threaded_irq(quick_check, isr_thread, …)`). On cleanup, call `brcmf_pcie_release_irq(devinfo)`.

**Discrimination.**
- If the threaded-IRQ split fixes it: our non-threaded handler is the culprit (unlikely given `irq_count=0` in every log).
- If still wedges: our handler shape is not load-bearing.

**Risk.** Upstream's `isr_thread` dispatches `handle_mb_data` and `msgbuf_rx_trigger`. Both deref `devinfo->shared` state that may not be populated. Very likely to *also* crash if ring-init hasn't been done. Better to combine with candidate A.

### Candidate E (LOW — diagnostic only) — add pre/post register read-verify around every scaffold write

**Design.** For T258/T259 mask+doorbell writes, add a readback immediately after each write, and log both the value written and the value read back. Today we write and move on.

**Discrimination.**
- If the readback shows the write didn't land (e.g. reads 0x0 after writing 0xFF0300 to MAILBOXMASK): upstream assumption about register offsets / core selection is wrong for BCM4360 and we need to fix `reginfo` binding.
- If reads match writes: the writes are arriving; the wedge is downstream.

**Risk.** None. Adds a few µs of MMIO per scaffold.

### Candidate F (LOW — scope pruning) — gate the dwell ladder behind a flag and fire T266 with `bcm4360_test238_ultra_dwells=0`

**Design.** Skip the entire 120 s ladder and run T266 scaffold immediately after `chip_set_active`.

**Discrimination.**
- If T266 now completes (`msleep done` fires): the ladder's accumulated state is what causes the msleep wedge.
- If still wedges: scaffold wedge is independent of ladder.

**Risk.** This is effectively what T268 tried to do (with T267-style scaffold); T268 crashed in buscore_reset before reaching scaffold. The hardware-drift issue may make this hard to test until substrate is verified clean.

---

## 6. Clean-room note

This audit describes **host-side kernel-driver behaviour**: what our modified `pcie.c` does and doesn't do vs upstream brcmfmac. It does not touch, describe, or quote proprietary firmware. All observations of firmware-side behaviour are inferred from externally-visible side-effects (MMIO reads, register values, DMA activity, IRQ counts) — no disassembly, no reconstructed fw code. Clean-room discipline preserved.

---

## 7. Recommended next step

**Candidate A (add `init_ringbuffers` + `init_scratchbuffers` before scaffold) is the highest-probability minimal-change fix.** It directly addresses the biggest load-bearing skip between our harness and upstream, and it discriminates cleanly: if the scaffold then completes, we've identified the cause in one test; if it still wedges, we've ruled out the single biggest remaining divergence.

However, this should only be fired once the **hardware-drift problem (T267/T268/T269-class probe-path wedges) is understood or mitigated**, since candidate A adds DMA allocations to the probe path and becomes unreadable if the fire also hits a drift-induced early wedge. The baseline re-fire task (briefed separately in phase6) should go first: if baseline still wedges in late ladder post-cold-cycle, we know scaffold-class tests are untestable until substrate is recovered.

If hardware substrate can be re-verified clean, the fire order is:
1. Baseline re-fire → confirm substrate is good.
2. T266 with candidate A spliced in (minimal scaffold + ring_init) → either fixes it, or ring_init itself fails, or wedges identically.
3. Depending on (2), either remove `pci=noaer` (candidate B) or add `pci=noaer` audit markers (candidate E).
