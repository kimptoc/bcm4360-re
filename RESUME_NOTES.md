# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 22:xx BST, PRE-TEST.259 — **Direct-evidence variant: register a safe IRQ handler + enable MSI BEFORE enabling MAILBOXMASK, so any fw-raised IRQ is consumed cleanly and the post-probe can capture buf_ptr drift.** Host stable, boot 0 up since 21:21:01 BST. T258 established circumstantially that enabling IRQ delivery is what wedges the host; T259 aims for direct evidence by handling the IRQ rather than leaving it dangling. Design: T259 uses variant (a) — a minimal IRQ handler that reads MAILBOXINT, ACKs it, masks further IRQs, and counts invocations. No shared-memory dereferences. If counter > 0 AND buf_ptr drifts in the 5s window → (A') causation fully demonstrated.)

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

## PRE-TEST.255 (2026-04-23 19:xx BST, boot 0 after test.253 crash + SMC reset) — **RTE scheduler state probe + drift test + 0x9355C decode.** Primary: four BSS fields (callback list, current task, sleep-flag, context-ptr) at t+100ms AND t+90s — drift + discrimination between (A) bus-stall and (A') WFI-idle. Secondary: 0x58C98 tick-scale, 0x93550..0x9358C struct family.

### Hypothesis

Three fw-hang hypotheses survived T254:
- **(A)** CPU stalled on backplane access (LDR/STR to unclocked SB core backpressures ARM core).
- **(A')** CPU in WFI inside RTE scheduler idle hook (0x115C → 0x11CC → 0x1C0C → 0x1C1E). Would have written the sleep-flag at BSS[0x629B4] before entering WFI.
- **(C)** Tick-scale at TCM[0x58C98] corrupted, making `bl #0x1ADC` delay effectively unbounded.

**Discriminator**: the scheduler-BSS four at 0x6296C/0x629A4/0x6299C/0x629B4 are **blob-zero** at boot (confirmed via blob read). Any non-zero at probe time proves fw's scheduler ran. The sleep-flag specifically (0x629B4) is written ONLY if the scheduler reaches the idle-path fall-through.

### Decision matrix

| BSS[0x629B4] (sleep-flag) | BSS[0x629A4] (cb-head) | BSS[0x6299C] (cur-task) | Reading |
|---|---|---|---|
| 0 @ t+100ms AND t+90s | 0 | 0 | Scheduler never entered main loop → (A) bus-stall very early, OR fw never booted past WFI-less init |
| ≠0 at any dwell | any | any | **(A') confirmed** — scheduler reached sleep path at least once |
| 0 @ both, others non-zero | non-zero | non-zero | Scheduler ran callbacks but never entered idle-path → fw stuck in a callback; (A) bus-stall within a callback |
| Values DIFFER between t+100ms and t+90s | — | — | Scheduler ran between the two probes → NOT bus-stalled, likely (A') in-and-out |
| TCM[0x58C98] != 0x50 | — | — | **(C) tick-scale corrupted** |

### Design

**Primary probes at t+100ms AND t+90s** (drift detection on scheduler state):

| Dwell | Probe | u32 | Rationale |
|---|---|---|---|
| t+100ms | `TCM[0x6296C, 0x629A4, 0x6299C, 0x629B4]` (4 discrete u32) | 4 | Early scheduler-state snapshot |
| t+100ms | `TCM[0x58C98]` (1 u32) | 1 | Tick-scale early check |
| t+90s | `TCM[0x6296C, 0x629A4, 0x6299C, 0x629B4]` (4 discrete u32) | 4 | Late scheduler-state snapshot for drift comparison |
| t+90s | `TCM[0x58C98]` (1 u32) | 1 | Tick-scale late check |
| t+60s | `TCM[0x93550..0x9358C]` (16 u32) | 16 | Secondary: decode 0x9355C family (T253 follow-up) |
| every dwell (23 pts) | `TCM[0x9d000]` (1 u32) | 23 | Continue frozen-ctr poll (n=6 replication) |

Total: 10 + 16 + 23 = 49 reads. Cheaper than T253 (55 reads).

**Runtime config**: `bcm4360_test255_sched_probe=1 bcm4360_test255_sched_late=1 bcm4360_test255_struct_decode=1`.

**Log format**:
```
test.255: t+100ms sched[0x6296C,0x629A4,0x6299C,0x629B4]=... 0x58C98=...
test.255: t+90000ms sched[0x6296C,0x629A4,0x6299C,0x629B4]=... 0x58C98=...
test.255: t+60000ms struct[0x93550..0x9358C] = 16 hex values (0x9355C family)
```

### Next-step matrix

| T255 Observation | Implication | T256 direction |
|---|---|---|
| sleep-flag 0x629B4 != 0 @ any dwell | **(A') WFI-stall confirmed** — scheduler reached idle. Focus shifts to "why no IRQ wakes fw" → PCIe MSI setup, host-fw handshake, intr mask state. | Probe PCIe MSI state; check host-side MSI enable; examine fw IRQ handlers. |
| All 4 BSS fields drift between t+100ms and t+90s | Scheduler alive, cycling through work. Hang is in a callback or a polling site reached from dispatcher. | Decode callback list contents (walk 0x629A4 next-pointers). |
| All 4 BSS fields zero at both dwells | Scheduler never ran → (A) bus-stall before scheduler start. Hang is in very-early-init. | Narrow to pre-scheduler init code; probe ChipCommon / backplane state. |
| 0x58C98 != 0x50 | (C) factor present. Delay loops unbounded. | Check what overwrote it; trace WRITE sites in blob. |
| 0x9355C family shows Thumb-PC pointers or magic | Opens new decode axis. | Chase those pointers in local disasm. |
| Counter 0x9d000 = 0x43b1 across 23 dwells (n=6) | test.89 frozen-ctr holds. | No further action. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 10 + 16 + 23 = 49. Cheaper than T253 (55).
- SMC reset expected after wedge (n=8 streak T247..T255 expected).
- BSS addresses 0x6296C/0x629A4/0x6299C/0x629B4 all within TCM (0..0xA0000) — safe BAR2 targets. Tick-scale 0x58C98 likewise safe.

### Code change outline

1. New module params: `bcm4360_test255_sched_probe`, `bcm4360_test255_sched_late`, `bcm4360_test255_struct_decode`.
2. New macros in pcie.c:
   - `BCM4360_T255_SCHED_PROBE(stage_tag)` — 5 u32 reads (4 BSS + 1 tick-scale) → 1 pr_emerg line. Fires at t+100ms (via `sched_probe` param) and t+90s (via `sched_late` param).
   - `BCM4360_T255_STRUCT_DECODE(stage_tag)` — 16 u32 reads at 0x93550..0x9358C → 1 pr_emerg line. Fires once at t+60s.
3. Extend T239 ctr gate: `if (... || bcm4360_test255_sched_probe || bcm4360_test255_sched_late || bcm4360_test255_struct_decode)`.
4. Invocation: at t+100ms dwell call `BCM4360_T255_SCHED_PROBE("t+100ms")`; at t+60s call struct_decode; at t+90s call sched_probe late.

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
    bcm4360_test255_sched_probe=1 \
    bcm4360_test255_sched_late=1 \
    bcm4360_test255_struct_decode=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T249/T250/T251/T252/T253 params NOT set (already captured).

### Expected artifacts

- `phase5/logs/test.255.run.txt`
- `phase5/logs/test.255.journalctl.txt`

### Pre-test checklist (complete — READY TO FIRE)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `9e70d0aa1ff335bd7cf0e037557ce06b` on `brcmfmac.ko`. `modinfo` shows all 3 new params (`bcm4360_test255_sched_probe`, `bcm4360_test255_sched_late`, `bcm4360_test255_struct_decode`). `strings` confirms all 3 T255 format lines (t+100ms sched, t+60000ms struct-decode, t+90000ms sched-late). Only pre-existing unused-variable warnings (no new regressions).
2. **PCIe state**: `Mem+ BusMaster+`, MAbort-, DEVSEL=fast. Clean.
3. **Hypothesis**: stated above — sleep-flag drift at 0x629B4 discriminates (A) vs (A'); tick-scale check discriminates (C).
4. **Plan**: committed.
5. **Host state**: boot 0 started 18:11:33 BST, stable, no brcm modules loaded.

Advisor-reviewed; T254 follow-through complete. Ready to fire.

---

## POST-TEST.255 (2026-04-23 19:5x BST — boot -1 after test.255 wedge + auto-reboot)

Boot -1 timeline: boot start 18:11:33 → insmod 19:50:19 → t+100ms probe 19:50:20 (all T255 + T239/T240/T247/T249/T242/T243 success) → t+60s probe 19:51:41 (T255 struct_decode + T253 if enabled — wasn't — + others) → t+90s probe 19:52:11 (T248 widescan + T249 ctr + T255 sched_late) → wedge at 19:52:11 (~0-1s after t+90s burst) → boot ended 19:52:11 → **host auto-rebooted** (not SMC reset) → boot 0 up at 19:53:42.

Full journal at `phase5/logs/test.255.journalctl.txt` (459 lines). All 3 T255 probe regions captured successfully.

**Wedge pattern deviation: auto-reboot rather than SMC reset required.** Previous T247..T253 wedges locked the PCIe bus (Mem-/BusMaster-/MAbort+) and needed manual SMC reset. T255 wedge caused a full host reboot. Post-reboot PCIe state dirty (Mem-/BusMaster-/CommClk-/ASPM Disabled) — SMC reset still needed before next HW test.

### What test.255 landed (facts)

**t+100ms TCM sched+tick probe:**
```
sched[0x6296C, 0x629A4, 0x6299C, 0x629B4] = 00062a98 0009627c 00096f2c 00000000
tick[0x58C98] = 000000a0
```

**t+60s TCM[0x93550..0x9358C] — 16 u32 (0x9355C struct family):**
```
0x93550: 04000000 000000ac 00000000 00093610   [+0: 4, +4: 0xAC, +8: 0, +C: TCM 0x93610]
0x93560: 00058ef0 00003151 000934c0 00000000   [+10: str "wl" (T252), +14: 0x3151, +18: TCM 0x934C0, +1C: 0]
0x93570: 00093540 00000418 00000000 00000000   [+20: TCM 0x93540 (sibling), +24: 0x418 (1048), +28: 0, +2C: 0]
0x93580: 00003901 000934c0 00000000 00000000   [+30: 0x3901, +34: TCM 0x934C0, +38: 0, +3C: 0]
```

**t+90s TCM sched+tick probe (drift partner):**
```
sched[0x6296C, 0x629A4, 0x6299C, 0x629B4] = 00062a98 0009627c 00096f2c 00000000
tick[0x58C98] = 000000a0
```

**Counter 0x9D000 = 0x000043B1 across all 22 dwells** (n=6 replication of test.89).

### What test.255 settled (facts)

**Correction (2026-04-23 20:0x BST per advisor audit)**: initial POST-TEST.255 claimed (A') WFI-stall was falsified because sleep-flag = 0. This was WRONG. Re-audit of pcie fn 0x115C disasm at 0x1192 shows `strb r4, [r6]` where r4 is ALWAYS 0 at that program point (r4 is the list-walk terminator, always 0 after the `cmp r4, #0; bne` loop exit at 0x1180). The scheduler ALWAYS writes byte 0 to BSS[0x629B4] on each idle-path pass, so reading 0 at probe time is non-discriminating between "never reached" and "reached many times". (A') is NEITHER confirmed NOR falsified by this probe. WFI reachability re-verified: 0x2408 (boot entry; no BL callers — likely reset vector or exception-vector tail-calls it) tail-calls 0x11D0, a real idle-loop function with push/BL prologue and an infinite `bl 0x11CC; b 0x11DE` loop that reaches WFI at 0x1C1E via two thunks. (A') remains on the table.

- **(C) tick-scale corruption FALSIFIED.** TCM[0x58C98] = 0xA0 at both dwells — runtime-updated from blob default 0x50 (fw's clock-init ran). Not the 0xFFFFFFFF-style corruption that would unbind polling loops. PMCCNTR-backed delays are 2× slower than T254 estimated (0x1722C worst-case ~160ms instead of 82ms) but still bounded.
- **Scheduler BSS was populated before probe time.** BSS[0x6296C] = 0x62A98, BSS[0x629A4] = 0x9627C, BSS[0x6299C] = 0x96F2C (all non-blob-zero). Fw code that writes to these addresses executed at some point between boot and t+100ms.
- **BSS drift test INCONCLUSIVE**, not proof of freeze. All 5 u32 identical between t+100ms and t+90s. These fields are expected to be static in normal operation (list head and current-task ptr don't change unless callbacks register/deregister or tasks switch). Zero drift is consistent with both "running but not mutating these fields" AND "fully stopped". Previous POST-TEST claim "scheduler froze" is stronger than the evidence supports — true drift detection needs probes on fields that change per-iteration.
- **0x9355C is a second-tier driver descriptor** — a struct containing cross-references to the three already-identified family members:
  - `+0x0C = 0x93610` (wl_info)
  - `+0x18, +0x34 = 0x934C0` (central shared object — **referenced TWICE** from this struct)
  - `+0x20 = 0x93540` (a sibling 28 bytes before this dump; explains why 0x93550 pre-header looks "padded")
  - Plus non-pointer fields: 0x93564 = 0x3151, 0x93574 = 0x418, 0x93580 = 0x3901 (state/IDs, exact meaning TBD)
  - Pre-header 0x93550 values `04 00 00 00 AC 00 00 00 00 00 00 00 TCM-ptr` hint at an allocator format: size=4 bytes in +0 (object-ID?) + size=0xAC = 172 bytes total (the struct body after header).
- **Wedge timing consistent with prior streak.** ~0-1s after t+90s probe burst (n=8 streak T247..T255).

### Where the hang is — reading after T255 (uncertainty widened)

1. Fw RTE boot runs, prints RTE banner, initializes clock (tick-scale 0x50→0xA0).
2. Fw scheduler main loop at 0x115C eventually gets entered (BSS fields populated — but we can't prove they were populated by THIS fn vs. by caller init).
3. Fw reaches (α-model) `wlc_attach → wlc_bmac_attach → wlc_phy_attach` call tree per T251 saved LRs.
4. Fw hangs somewhere past that point, either:
   - **(A)** at bus level on an uncompleting LDR/STR to an SB core, OR
   - **(A')** in the idle-loop WFI at 0x1C1E, waiting for an IRQ that never fires, OR
   - **(B)** an inter-task wait we haven't mapped yet.
5. (C) tick-scale corruption is ruled out.

**Both (A) and (A') still have host-observable equivalence** — no code runs either way. A probe that DOES discriminate needs a signal that changes per-scheduler-iteration (which we don't have a probe for yet).

### Next-test direction (T256 — advisor-confirmed + pre-checks done)

Pre-T256 local checks (advisor-requested):

- **0x62A98 (BSS[0x6296C] observed value) appears 2× in blob** at 0x66FC0 and 0x67348 — it's a .data init, reading it at probe time proves nothing about execution. Only the runtime-populated 0x9627C and 0x96F2C support "fw scheduler setup code ran."
- **0x9936 is a pure reader** (3 insns: `ldr r3,[r0+0x358]; ldr r0,[r3+0x100]; bx lr`). No BSS writes → can't use as drift detector.
- **Auto-reboot mechanism**: no panic/Oops/BUG/AER/watchdog messages in boot -1 journal. Silent wedge at 19:52:11 → machine rebooted at 19:53:42 (~1m31s later). Most consistent with platform watchdog / BMC hard reset. Benign at kernel level.

T256 design (refined):

| Dwell | Probe | u32 | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x9627C..0x962BC]` (16 u32, 4 × 16-byte callback nodes) | 16 | Walk first 4 nodes of the scheduler callback list. Each node {next=+0, fn-ptr=+4, arg=+8, flag=+0xC} per pcie fn 0x115C disasm. If any fn-ptr points into wlc_attach / wlc_bmac_attach / wlc_phy_attach (blob 0x68xxx-0x6axxx), hard evidence those are registered callbacks. node[3]→next indicates whether list extends past our window. |
| t+60000ms | `TCM[0x96F2C..0x96F6C]` (16 u32, current-task struct) | 16 | Pcie fn 0x115C: `r3 = *0x6299C; r3 = *r3; r3 = r3->[+4]`. Multi-level struct. Base dump decodes first 64 bytes. Identifies what task type + state. |
| every dwell (23 pts) | `TCM[0x9d000]` (1 u32) | 23 | Continued frozen-ctr poll (n=7 replication). |

Total: 32 + 23 = 55 reads at t+60s burst. Same cost as T253.

Dropping: si_info core-base continuation (deferred to T257 if T256 results point that way).

Advisor-confirmed; proceeding to code change.

---

## PRE-TEST.256 (2026-04-23 20:xx BST, boot 0 after test.255 auto-reboot; need SMC reset first) — **Scheduler callback list walk + current-task struct dereference.** Single t+60s probe, 32 u32. Target: identify registered callback functions (look for wlc_attach family in fn-ptrs) and current-task struct layout.

### Hypothesis

Two live candidates post-T255:
- **(A)** CPU bus-stalled on backplane access during a scheduler-dispatched callback.
- **(A')** CPU WFI'd in idle loop (0x11D0), waiting for never-arriving IRQ.

**Discriminator**: the callback-list head at BSS[0x629A4] = 0x9627C was runtime-populated (not blob-init). Walking nodes starting at 0x9627C reveals REGISTERED callbacks. If any node's fn-ptr falls in wlc_attach / wlc_bmac_attach / wlc_phy_attach blob range, strong evidence for (A) — confirms those functions are scheduler callbacks and consistent with saved LRs from T251 being "stuck in one of them."

Current-task struct at 0x96F2C is dereferenced twice by scheduler (3 levels). Reading 16 u32 at 0x96F2C captures the base + first dereferenced struct. Entry-point fn-ptr within this struct (likely at +4 after first deref) identifies the task.

### Design

| Dwell | Probe | u32 | Purpose |
|---|---|---|---|
| t+60000ms | `TCM[0x9627C..0x962BC]` | 16 | 4 callback nodes × {next, fn, arg, flag} |
| t+60000ms | `TCM[0x96F2C..0x96F6C]` | 16 | Current-task struct base (16 u32) |
| every dwell (23) | `TCM[0x9d000]` | 23 | Per-dwell frozen-ctr poll |

Log format (2 pr_emerg lines at t+60s):
```
test.256: t+60000ms TCM[0x9627c..0x962bc] = 16 hex values (callback list nodes 0..3)
test.256: t+60000ms TCM[0x96f2c..0x96f6c] = 16 hex values (current-task struct)
```

Runtime: `bcm4360_test256_sched_walk=1`. Drops T255 probes (already captured).

### Next-step matrix

| Observation | Implication | T257 direction |
|---|---|---|
| Any callback fn-ptr in 0x68xxx..0x6Axxx (wlc_attach family) | Hard evidence wlc functions are scheduler callbacks. Cross-ref with T251 LRs. Hang is (A) bus-stall in this callback. | Probe SB core-base cache in si_info + potentially sample register via BAR0. |
| All callback fn-ptrs in 0x1xxx..0x3xxx (early-boot only) | wlc_attach wasn't reached via this list. Either (A') idle reached, or wlc_attach runs outside scheduler. | Pivot: disassemble the entry-points of observed fn-ptrs to learn what scheduler dispatches. |
| node[3]→next points into 0x9xxxx (TCM BSS/heap) | List extends past window. More nodes to probe. | T257 reads node[4..N]. |
| node[3]→next = 0 | List ended within our window. | No further action on list length. |
| Current-task struct (+0 field) points into 0x9xxxx | Valid pointer chain. Follow it in T257 if more detail needed. | — |
| Current-task struct (+4 field after first deref) is a Thumb fn-ptr (0x68xxx+1, 0x6Axxx+1) | Task entry point identified. | Disassemble; confirm which fn fw is "currently in" per scheduler state. |
| Counter 0x9d000 = 0x43b1 across 23 dwells (n=7) | test.89 holds. | No further action. |

### Safety

- All BAR2 reads, no register side effects.
- Total: 32 + 23 = 55 reads. Same as T253.
- Wedge expected (n=9 streak T247..T256). Post-T255 auto-reboot behavior suggests platform watchdog may fire again.

### Code change outline

1. New module param `bcm4360_test256_sched_walk` near T255's.
2. New macro `BCM4360_T256_SCHED_WALK(stage_tag)` reading 2 × 16 u32 → 2 pr_emerg lines.
3. Extend T239 ctr gate: `if (...T255 || bcm4360_test256_sched_walk)`.
4. Invocation: right after `BCM4360_T255_STRUCT_DECODE("t+60000ms")` in pcie.c.

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
    bcm4360_test256_sched_walk=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T249/T250/T251/T252/T253/T255 params NOT set.

### Expected artifacts

- `phase5/logs/test.256.run.txt`
- `phase5/logs/test.256.journalctl.txt`

### Pre-test checklist (partial — READY pending SMC reset)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `2b3edee76a132137c66ff3d539f29bc1`. `modinfo` shows new param `bcm4360_test256_sched_walk`. `strings` confirms both T256 format lines (16 u32 at 0x9627c + 16 u32 at 0x96f2c). Only pre-existing unused-variable warnings.
2. **PCIe state**: currently DIRTY (Mem- BusMaster-, CommClk- post-T255 auto-reboot). **SMC reset required before insmod** — user action needed.
3. **Hypothesis**: callback-list fn-ptr addresses discriminate (A) vs (A'). If any fn-ptr is in wlc_attach family (0x68xxx-0x6Axxx), hard evidence for (A).
4. **Plan + code**: committed before test fire.
5. **Host state**: boot 0 started 19:53:42 BST. No brcm loaded.

Advisor-reviewed. Pending SMC reset + test fire.

---

## POST-TEST.256 (2026-04-23 20:4x BST — two boots; first wedged pre-fw, second captured both probes)

### Boot timeline

- **Boot -2 (first T256 fire)**: 20:31:08 → 20:34:59 (wedged at "CC-clk_ctl_st pre-release snapshot", 2m21s after insmod at 20:32:38). **No test.238 dwell-ladder entries, no T256 probe output.** Auto-rebooted.
- **Boot -1 (re-fire with sched_walk_early=1)**: 20:38:03 → 20:45:27 (fw released, survived through t+120000ms dwell, wedged during cleanup 2m22s after insmod at 20:43:05). Both T256 probes fired at t+100ms AND t+60000ms. Auto-rebooted.

Wedge timing pattern has BROKEN: prior T247..T253 and T255 wedged ~1s after t+90s probe burst. T256-1 wedged before fw ran; T256-2 survived entire 2-minute dwell ladder. **Host-side rmmod/cleanup path may be triggering wedge, not fw state.**

### What test.256 landed (facts)

**TCM[0x9627C..0x962BC] — 16 u32 at both dwells (IDENTICAL):**
```
0x9627C: 00096f48 00001c99 00058cc4 00000008   [node[0]: next=0x96F48, fn=0x1C99 (Thumb), arg=0x58CC4, flag=8]
0x9628C: 0000004c 00000000 0009664c 00096690   [node[0] extended +0x10..0x1C: 0x4C, 0, 0x9664C, 0x96690]
0x9629C: 000962e8 00000000 00000000 00000000   [+0x20: 0x962E8, rest zero]
0x962AC: 00000000 00000000 00000000 00000000   [+0x30..0x3C: zeros]
```

**TCM[0x96F2C..0x96F6C] — 16 u32 at both dwells (IDENTICAL):**
```
0x96F2C: 00000000 00000000 00000000 00000000   [first 16B zeros — +0 null → scheduler skips active-task path]
0x96F3C: 00000000 00000010 00000000 00000000   [+0x14 = 0x10 (16)]
0x96F4C: 00000b05 00000000 00000001 00000010   [+0x20 = 0xB05 (2821), +0x28 = 1, +0x2C = 0x10 (16)]
0x96F5C: 00000000 00000001 00000000 00000000   [+0x34 = 1]
```

### What test.256 settled (facts)

- **Node[0] fn-ptr 0x1C98 IS `pciedngl_isr`** — the pcie dongle interrupt service routine. Evidence: function body at 0x1C98 begins with `push.w {r4, r5, r6, r7, r8, sb, lr}` + `ldr r5, [r0, #0x18]` prologue, and its printf fmt strings decode to:
  - blob[0x4069D] = `"pciedngl_isr called\n"` (first trace print)
  - blob[0x406B2] = `"%s: invalid ISR status: 0x%08x"` (error trace)
  - blob[0x40685] = `"pciedngl_isr"` (function name literal)
  - blob[0x406D1] = `"%s: malloc failure\n"`
  - blob[0x406E5] = `"pciedev_msg.c"` (source file, confirms this is pcie-device messaging module)
  - blob[0x406F3] = `"pktlen: %d, nextpktlen %d\n"` (packet trace)
- **Node[0].arg = 0x58CC4 = blob string `"pciedngldev"`** — suspicious: ISR conventions usually pass struct ptr, not string. If ISR dereferences arg+0x18 when arg=literal string addr, it reads bytes beyond "pciedngldev\0" (i.e., from adjacent blob data). Could indicate a separate "ISR is broken" hypothesis, OR this is a design where arg is indeed a named global that resolves correctly. Not investigated further.
- **Scheduler callback registered as dispatch-bit-3** (flag=0x8 tested against r5 via `tst r5, r3` at pcie fn 0x1170). For the ISR to run, r5 (return of `bl 0x9936` at 0x1162) must have bit 3 set.
- **Current-task struct first field is NULL** — scheduler branch at 0x1186 `cbz r3, #0x11AA` taken → active-task dispatch path skipped. Fw is in a "no current task" state at probe time.
- **Node[0] extended layout (beyond +0xC)** includes additional runtime-alloc'd TCM pointers at +0x18 (0x9664C), +0x1C (0x96690), +0x20 (0x962E8). These are not touched by the scheduler dispatch code (which only uses +0..+0xC), so they're ISR-internal state.
- **T256 first run wedged before fw release** — no diagnostic data captured. Wedge point varies between runs.

### What test.256 did NOT settle (advisor correction applied)

- **"Identical at t+100ms and t+60000ms" is NOT evidence fw is stopped.** Node[0] registration fields don't change even if ISR runs 1000 times. We're reading registration state, not execution evidence.
- **"Fw survived t+120s dwell" is NOT evidence fw is running.** TCM BAR2 reads work regardless of fw CPU state.
- **(A') WFI-idle hypothesis is FAVORED but NOT confirmed.** Equally consistent alternatives:
  - IRQ arrives, ISR runs, returns fast, scheduler cycles again (no observable drift)
  - ISR never wired to interrupt controller (registration ≠ wiring)
  - IRQ delivered but masked at PMU/intr-ctrl level
  - ISR arg=literal-string-addr is broken and would hang if invoked

### Next-test direction (T257 — host-side, no new fw probe)

Advisor-suggested: the IRQ-delivery question is answerable from the host side without new probes.

1. **`grep -i 'pci_enable_msi\|pci_alloc_irq' phase5/work/.../pcie.c`** — does our driver enable MSI/MSIx? If no, fw can't receive PCIe interrupts.
2. **`cat /proc/interrupts | grep brcm`** after T256-style insmod — is any IRQ registered for the BCM4360? What's its counter?
3. **Check MAILBOXINT writes**: T242/T243 probes touched MAILBOXMASK. Revisit those captured values — what does our driver write to the fw-side mailbox interrupt register? If we write 0 (mask all), fw-side ISR will never fire.
4. **Cross-check with upstream brcmfmac**: upstream driver's PCIe init sequence shows what MSI / MailboxInt config is normally needed. Our minimal driver may skip that.

Advisor call before committing to T257 design. All T257 work is local reading — no hardware test needed at this stage.

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
