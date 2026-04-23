# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 20:5x BST, POST-TEST.256 — **pciedngl_isr identified as node[0] scheduler callback; (A') WFI-idle FAVORED but not confirmed**. Host stable, boot 0 up since 20:48:20 BST. T256 fired twice: first run (20:32:38) wedged BEFORE fw was released — zero probe data. Second run (20:43:05, build `cc6e9304e7fbf287b4e68facd036dd47` with added sched_walk_early) fired both probes successfully, survived through t+120000ms dwell (!), wedged during cleanup at 20:45:27. PCIe auto-recovered clean after both reboots. Key findings: (1) **Callback node[0] = pciedngl_isr**: fn-ptr 0x1C99 → Thumb target 0x1C98. Blob-refed strings: `"pciedngl_isr called\n"` at 0x4069D, `"pciedngldev"` at 0x58CC4 (the arg). Flag=0x8 is dispatch-mask bit 3. Invoked only via scheduler `blx r3` at 0x117A — no direct BL callers. This IS the pcie dongle ISR registered as scheduler callback. (2) **Current-task struct at 0x96F2C**: first u32 is 0 — scheduler's `cbz r3, #0x11AA` branch falsifies the "active task dispatch" path. Sparse numeric state fields at offsets +0x14/+0x20/+0x28/+0x2C/+0x34 (values 0x10, 0xB05, 1, 0x10, 1), no fn-ptrs. Consistent with "no active task" state. (3) **Callback state IDENTICAL at t+100ms and t+60000ms** — BUT per advisor, this is NOT evidence of fw stopping: node[0]'s registration fields (next/fn/arg/flag) wouldn't change even if the ISR ran 1000 times. Drift on these fields is not a discriminator. (4) **"Fw survived 120s dwell ladder" is ambiguous**: TCM reads work via BAR2 regardless of fw CPU state, so not evidence of fw execution. Hang candidates STILL open: (A) bus-stall, (A') WFI-idle waiting for IRQ, also possible: ISR arg looks wrong (literal string addr, not struct) — ISR might be broken. T257 direction: host-side IRQ-delivery check — does our driver wire MSI / write MailboxInt / does /proc/interrupts show activity? No new fw probe needed.)

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
