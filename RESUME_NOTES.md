# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 20:0x BST, POST-TEST.255 — **(C) tick-scale corruption FALSIFIED; (A') WFI-stall NEITHER confirmed NOR falsified (sleep-flag probe non-discriminating, corrected per advisor); struct-graph extended.** T255 fired at 19:50:19 (all 3 probes captured); wedge at 19:52:11 (~1s after t+90s T248 probe, n=8 streak T247..T255). Host auto-rebooted (not SMC reset); PCIe post-wedge DIRTY (Mem- BusMaster- CommClk-) — SMC reset needed before next HW test. Real T255 findings (after advisor correction): (1) **Tick-scale TCM[0x58C98] = 0xA0 (160) at both dwells** — runtime-updated from blob default 0x50. NOT corrupted. **(C) FALSIFIED.** All PMCCNTR-backed polling loops remain bounded (worst case ~160ms at 0x1722C, double T254's 82ms estimate). (2) **Scheduler BSS state**: 0x6296C = 0x62A98, 0x629A4 = 0x9627C (callback-list head), 0x6299C = 0x96F2C (current-task), 0x629B4 = 0. These are non-blob-zero (except 0x629B4), proving fw boot reached the code that populates them. (3) **BSS drift test INCONCLUSIVE**: all 5 u32 identical between t+100ms and t+90s, but these fields are expected-static in normal operation (list head + current-task typically don't change). Zero drift is consistent with both "running-but-not-list-mutating" and "fully stopped". (4) **Sleep-flag TCM[0x629B4] = 0 — NON-DISCRIMINATING**: r4 always = 0 at the `strb r4, [r6]` at pcie fn 0x1192 (r4 is list-walk terminator), so scheduler always writes 0 to this byte. Reading 0 matches both "never reached sleep path" AND "reached sleep path". (A') NOT falsified by this probe. (5) **WFI IS reachable** (re-verified): 0x2408 (boot entry) → tail-call 0x11D0 (real idle-loop fn, push/BL prologue) → infinite `bl 0x11CC` loop → `b.w 0x1C0C` → `b.w 0x1C1E` (wfi). (6) **0x9355C struct family decoded**: refs to 0x93610 (wl_info), 0x934C0 (central obj, 2×), 0x93540 (sibling), + numeric fields 0x3151/0x418/0x3901. Remaining hang candidates: **(A) bus-stall on backplane access** (still most-consistent) OR **(A') WFI waiting for never-arriving IRQ** (not yet falsifiable with current probes).)


## PRE-TEST.253 (2026-04-23 17:5x BST, boot 0 after test.252 crash + SMC reset) — **central-shared-object probe + list_head validation**. Single t+60s probe reads 16 u32 at 0x934B8 (covers 0x934C0 and 8 pre-bytes for allocator-header check) + 16 u32 at 0x91E50 (list_head peers + context). Advisor-confirmed post-T253 local analysis.

### Hypothesis

Two branches of the saved-state reading need discrimination:

- **Branch (α) — stack-or-call-context reading**: the saved-state region at TCM[0x9CE98..0x9CF34] is an active task's call context, so the LR values there (0x68321 in wlc_bmac_attach area, 0x68D2F in wlc_attach area) reflect the current hung call chain. T252 local analysis narrows the hang to a callee of wlc_phy_attach (likely via 0x34DE0 → 0x6A2D8 dispatcher chain).
- **Branch (β) — task context save / TCB reading**: the saved-state region is a paused task's TCB. The hang is in a DIFFERENT task entirely; the saved LRs just show what this paused task was doing. This makes T253's local analysis of 0x6A2D8 irrelevant (wrong task).

**The 0x934C0 probe discriminates**. If 0x934C0 looks like a TCB — magic/type tag + state field + stack pointer + entry function pointer — then (β) is strongly supported and "which task hung" becomes the question. If it looks like a regular struct (no magic, no state, no sp/entry-fn pattern), (α) remains tenable.

**The 0x91E54/0x91E84 probe validates the list_head pair reading**. An empty doubly-linked list embedded in a struct has prev=self+offset, next=self+offset (pointing back to the slot). If `[0x91E54]={next=0x92460, prev=0x92460}` (or similar, pointing back to the si_info struct's list-head slot at 0x92460/0x92468), the list is empty and our "embedded list_head" inference is correct. If they point elsewhere, the list has members and we can walk them (new info). If they're garbage, list-head reading needs revision.

### Design

**Single probe at t+60000ms** (T252 phy_data is OFF — already captured):

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x934B8..0x934F8]` (16 u32 = 64 B) | 16 | Central-shared-object decode. 8 pre-bytes (0x934B8..0x934BF) catch allocator header if present; main region 0x934C0..0x934F8 holds the object. |
| t+60000ms | `TCM[0x91E50..0x91E90]` (16 u32 = 64 B) | 16 | list_head peer probe. Reads 0x91E54 (peer A) + 0x91E84 (peer B) + surrounding context. |
| every dwell (23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Per-dwell ctr poll. n=5 replication of test.89. |

Total: 32 + 23 = 55 reads. Cheaper than T252 (71) and T251 (99).

**Log format (2 pr_emerg lines at t+60s):**
```
test.253: t+60000ms TCM[0x934b8..0x934f4] = 16 hex values (central shared object + header)
test.253: t+60000ms TCM[0x91e50..0x91e8c] = 16 hex values (list_head peer pair + context)
```
Each line ~190 chars. Under LOG_LINE_MAX 1024.

**Runtime config**: `bcm4360_test253_shared_obj=1`. Drops T249/T250/T251/T252 probes (all already captured).

### Next-step matrix

| Observation at 0x934C0 | Implication | T254 direction |
|---|---|---|
| Magic/type tag + state + sp + entry-fn pattern | Branch (β) confirmed: saved-state is a **paused task TCB**. Hang is in a different task. | Enumerate RTOS task list; probe the other TCBs. |
| Regular struct (no magic, no sp/entry-fn) — e.g., config or routing table | Branch (α) still tenable. | Resume local disassembly: 0x6A2D8 (real PHY worker) for polling loops. |
| Sparse zeros / garbage | 0x934C0 ref across structs was coincidental or a stale pointer. | Revisit: reread T251/T252 decodes. |

| Observation at 0x91E54 / 0x91E84 | Implication | T254 direction |
|---|---|---|
| prev/next point back to 0x92460/0x92468 | Empty list_head embedded in si_info. Confirms reading. | No further action on this axis. |
| prev/next point to other TCM addresses (e.g., 0x91E54/0x91E84 themselves, or other peers) | List has members — can walk to enumerate. | Walk list from 0x91E54 to enumerate members. |
| Garbage values | list_head reading wrong. | Revisit si_info-class inference. |

| Counter 0x9d000 = 0x43b1 across all 23 dwells (n=5 replication) | test.89 single-write confirmed at n=5. Reframe holds. | No further action. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 32 at t+60s + 23 per-dwell = 55 reads (cheapest probe since T248).
- SMC reset expected after wedge (n=7 streak T247..T253 expected).

### Code change outline

1. New module param `bcm4360_test253_shared_obj` near T252's.
2. New macro `BCM4360_T253_SHARED_PROBE(stage_tag)` reading 2 × 16 u32 → 2 pr_emerg lines.
3. Extend T239 ctr gate: `if (...T252 || bcm4360_test253_shared_obj)`.
4. Invocation: right after `BCM4360_T252_DATA_PROBE("t+60000ms")` in pcie.c.

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
    bcm4360_test253_shared_obj=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T249/T250/T251/T252 params NOT set (already captured those windows).

### Expected artifacts

- `phase5/logs/test.253.run.txt`
- `phase5/logs/test.253.journalctl.txt`

### Pre-test checklist (complete — READY TO FIRE)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `bce1d0f08e661f1b0df50c0fdc3a04f4` on `brcmfmac.ko`. `modinfo` shows new param `bcm4360_test253_shared_obj`. `strings` confirms both T253 format lines (16 u32 each at 0x934b8 / 0x91e50). Only pre-existing unused-variable warnings.
2. **PCIe state**: `Mem+ BusMaster+`, MAbort-, CommClk+, UESta clean, CESta AdvNonFatalErr+ (sticky). Re-verified 17:5x BST.
3. **Hypothesis**: stated above — if 0x934C0 looks like a TCB, the saved-state is a paused task (reframes hang as "which task") → (β); if regular struct, stack-like-reading (α) tenable. list_head peer self-ref confirms empty-list inference.
4. **Plan**: this block + code change to be committed and pushed before insmod.
5. **Host state**: boot 0 started 17:28 BST, stable. No brcm modules loaded.

---

## POST-TEST.253 (2026-04-23 18:0x BST — boot -1 after test.253 crash + SMC reset)

Boot -1 timeline: boot start 17:28:11 → insmod 18:00:54 → t+60s probe 18:02:17 (T253 + T247/238/239/240/248/249 success) → t+90s probe 18:02:46 (T248 + T249 ctr final) → wedge ≤1s after → boot ended 18:03:03. Wedge n=7 streak T247..T253. PCIe cleanly recovered after SMC reset (Mem+ BusMaster+ MAbort- UESta clean, CESta AdvNonFatalErr+ sticky). Full journal at `phase5/logs/test.253.journalctl.txt` (458 lines). Both T253 probe regions captured successfully.

### What test.253 landed (facts)

**TCM[0x934B8..0x934F4] — 16 u32 (central shared object + pre-header):**
```
0x934B8: 00000078 00000000 00000000 0009355c   [+0: 0x78=120, +8: zero, +12: TCM ptr 0x9355C]
0x934C8: 00000000 00000000 00000000 00000000   [+0x10..+0x1C zeros]
0x934D8: 00000000 00000000 00000000 00006908   [+0x20..+0x28 zeros, +0x2C: 0x6908 (26888)]
0x934E8: 00000000 00000000 00000000 00000003   [+0x30..+0x38 zeros, +0x3C: 0x3]
```

Mapping with 0x934B8 as base:
- 0x934B8 = 0x00000078 (= 120 dec) — looks like an allocator size header (next struct = 120 bytes).
- 0x934C0 (the "central shared object") is 8 bytes later. Contents 0x40-byte tail shown:
  - 0x934C0 = 0 (object base)
  - +0x04 = 0x0009355C (TCM ptr — new, forward into the struct family)
  - +0x08 = 0
  - +0x0C = 0
  - +0x10..+0x20 = 0 (all zero across 5 u32)
  - +0x24 = 0x00006908 (= 26888)
  - +0x28 = 0
  - +0x2C = 0
  - +0x30 = 0
  - +0x34 = 0x00000003

**TCM[0x91E50..0x91E8C] — 16 u32 (list_head peer pair region, probing targets 0x91E54 + 0x91E84):**
```
0x91E50: 00000000 00000000 00000000 00000000   [all zeros]
0x91E60: 00000000 00000000 00000000 00000000   [all zeros]
0x91E70: 00000000 00000000 00000000 00000030   [+0x28: 0x30 (48)]
0x91E80: 00000000 00000000 00000000 00000000   [all zeros]
```
- 0x91E54 = 0 (expected "peer A" — was referenced from 0x92460 in T252 as list_head next).
- 0x91E84 = 0 (expected "peer B" — was referenced from 0x92464 in T252 as list_head prev).
- Only non-zero in the 64-byte window: 0x91E7C = 0x30.

**Counter 0x9D000 = 0x000043B1 for all 22 dwells** this run (n=5 replication of test.89 single-write reading).

### What test.253 settled (facts)

- **Branch (α) — saved-state region is a call-context snapshot — CONFIRMED.** 0x934C0 TCB-pattern test was the pre-test discriminator. All three TCB signals absent (no magic, no LSB=1 fn-pointer in the 16-u32 dump, no sp-like value). Reading "the saved-state region at 0x9CE98..0x9CF34 is a task's call context, and the LR values 0x68321/0x68D2F there reflect the hung call chain" **stands unrevised**. The T251-era β alternative ("paused TCB reading, hang in different task") is **falsified** — T253 closes this fork.
- **0x934C0 is a partially-initialized 120-byte struct** (size 0x78 in the pre-header at 0x934B8 is consistent with an ARM-style allocator prefix). Only three fields populated out of ~30 u32 slots. Consistent with fw being stuck mid-init — the allocator ran and a few fields were written, but fw hung before completing this struct's initialization. Fields that ARE populated:
  - +0x04 = 0x9355C — another TCM ptr into the struct family (cheap probe target).
  - +0x24 = 0x6908 — unexplained constant (not a blob offset, not in 0x18xxxxxx range, fits "count / index / token").
  - +0x34 = 0x3 — small integer (state, index, or flag set).
- **list_head peer-pair reading DOWNGRADED.** T253 probe at 0x91E50..0x91E8C shows both 0x91E54 and 0x91E84 are zero. Linux empty-list convention requires self-reference; non-empty requires populated peers; both-zero is neither. The T252 "two adjacent embedded list_head pairs at 0x92460" claim is **not confirmed** by T253. Plausible alternatives: (a) non-Linux list convention with NULL terminators; (b) uninitialized BSS read via stale pointers in 0x92440; (c) those 0x92460 fields are not list_head pointers at all — possibly integer values or different-sized record offsets. This does NOT change the si_info-class reading of 0x92440 (CC core base 0x18001000 evidence still holds) — only the list_head sub-inference.
- **0x9355C is now the cheapest next-probe target** — same family as 0x934C0, forward linkage, same risk profile as T253.
- **n=5 replication of test.89 frozen-ctr.** 0x43B1 at 0x9D000 stable across 22 dwells × 5 boots.
- **n=7 wedge streak T247..T253.** Probe costs remain flat (not cumulative).
- **SMC reset required.**

### Where the hang is — reading after T253

Consolidated picture (no contradictions in observed data):

1. wlc_attach entered (LR 0x68D2F in saved-state).
2. wlc_bmac_attach entered (LR 0x68321 in saved-state).
3. si_info (0x92440) populated with CC core base 0x18001000 → si_attach() completed before hang.
4. wlc_attach printed the RTE banner + BCM4360 r3 40/160/160MHz line (T251). Next line (chiprev banner, printed after wlc_phy_attach returns) never fires.
5. 0x934C0 partially initialized — allocator ran, first few fields written, struct body unfinished.
6. Hang is inside a callee reached from wlc_bmac_attach → wlc_phy_attach → [callee]. Per T253 local analysis (phase5/analysis/T253_wlc_phy_attach.md), the most likely sub-tree is the 0x34DE0 dispatcher chain → 0x6A2D8 (real PHY worker) → 0x38A50/0x38A24 dispatch tables (PHY-op vtable entries).

### Next-test direction (T254 — candidates for advisor review)

Two tracks, both cheap:

1. **T254 LOCAL (preferred, no hardware)**: disassemble 0x6A2D8 (the real PHY worker that 0x34DE0 tail-calls 8× from inside wlc_phy_attach). Look for tight polling loops (`ldr/tst/bne-back`) targeting PHY-core registers. This is the next narrowing step after T253's local analysis. Output: identify specific register/mask fw is polling. Deliverable: `phase5/analysis/T254_6a2d8_worker.md`.

2. **T254 HARDWARE (if local work leaves gaps)**: probe TCM[0x93550..0x9358C] (16 u32) to decode 0x9355C — the only unfollowed pointer in 0x934C0's populated fields. Same cost as T253 (~32 reads), same wedge expectation. Deferred until local analysis of 0x6A2D8 is done, since local work may change what we want to know about 0x9355C.

Advisor call before committing to T254 design.

---

## POST-TEST.254 (2026-04-23 19:0x BST — local disassembly only, no hardware test)

T254 was a local-analysis pass (no kernel module load, no crash). Deliverable: `phase5/analysis/T254_phy_subtree.md`. Scripts: `t254_6a2d8_worker.py`, `t254_dispatch_scan.py`, `t254_poll_detail.py`.

### What test.254 landed (facts)

- **0x6A2D8 has no backward branches** — no loops, cannot be the hang. Structured as setup + tail-call to 0x52B8 (a comma-separated-string iterator — not hardware).
- **wlc_phy_attach's dispatch-table exposure is narrow**: only TWO direct calls into 0x38A50 table, both at index 0 → target 0x15940 (also loop-free).
- **Scanned all 17 dispatch-table targets reachable via 0x38A50/0x38A24**: only one tight hardware-poll candidate, at target **0x1722C**.
- **0x1722C is `wlc_bmac_suspend_mac_and_wait`** (function name string at blob[0x4B189]). Polling loop at 0x173D8..0x173EC (8 insns) reads `[r4 + 0x128]` bit 0 with r7 countdown from 0x14441. On timeout **falls through without assert** — and uses the bounded `bl #0x1ADC` delay.
- **Delay helper 0x1ADC is bounded via PMCCNTR** (CP15 `mrc p15,0,r0,c9,c13,0` at 0x1EC). PMCCNTR is enabled early in boot (PMCR writes at 0x1D6 and 0x1DC: `mcr p15,0,r1,c9,c12,0/1`). Blob init tick-scale at TCM[0x58C98] = 0x50 → `delay(10)` ≈ 10 µs → 82ms total wall-clock for the 0x1722C poll.
- **"40/160/160MHz" line IS the RTE boot banner** at blob[0x6BAE5]: `"RTE (%s-%s%s%s) %s on BCM%s r%d @ %d.%d/%d.%d/%d.%dMHz"` — printed very early in fw boot, NOT by wlc_attach. T251 reading "last printed line is wlc_attach banner" is **revised**. Fw hung AFTER RTE banner, anywhere in the remaining init.
- **Chiprev banner call site pinpointed**: blob[0x06876E] LDR + blob[0x06877A] BL to printf 0xA30. Uses format at blob[0x4C534]. Same function references `"wlc_bmac_attach"` string at blob[0x4B121] from 0x68778 → **confirmed inside wlc_bmac_attach**. Fw never reached this printf → hang is in wlc_bmac_attach's execution BEFORE byte 0x06877A.
- **WFI check (revised)**: 1 WFI (0xBF30) at blob[0x001C1E] — a 4-byte leaf function (`wfi; bx lr`). **IS REACHABLE** via tail-call chain: 0x1C1E ← b.w 0x1C0C (thunk) ← b.w 0x11CC (inside fn 0x115C — the RTE scheduler main loop). 0x115C walks a callback list at BSS[0x629A4], dispatches matching callbacks, falls through to a sleep path (writes flag at BSS[0x629B4], calls 0x1038 barrier, rechecks), returns or loops. If no runnable work → WFI. Classic RTOS idle hook. Initial T254 "not reachable" reading was WRONG (based on address-range guessing; advisor flagged this for explicit check).
- **WFE (0xBF20) check**: no valid WFE instructions found in code region.
- **Self-loop (`b .` = 0xE7FE) check**: 6 occurrences total. Four at 0x25E/0x290/0x326/0x53E are real early-boot fault handlers. Two at 0x464F6/0x468F4 are false positives (data region, no callers, junk strings nearby).
- **α caveat**: T253 falsified "0x934C0 is a TCB" but did NOT fully settle "saved-state region is a call-context snapshot vs. a paused-task save frame." α remains the working model but is not load-bearing evidence. Downstream claims ("fw was executing inside 0x1415C at hang time") carry this uncertainty.

### What test.254 settled (facts)

- **The hang is NOT a direct polling loop in the fw code region**. All three candidate polling loops (0x1415C, 0x1722C, 0x14CAC) are built on PMCCNTR-backed `bl #0x1ADC` and have finite wall-clock timeouts ≤ 82ms. Bounded loops do not silently hang for 60+ seconds.
- **Saved LR 0x68321 is the return address of `bl #0x1415C` at 0x6831E** inside wlc_bmac_attach (T253 identified 0x1415C as SB-core reset waiter; T254 confirms caller context). So fw was inside 0x1415C or one of its transitive callees at capture time — but those are also all bounded.
- **Remaining hang candidates** (priority revised post-WFI reachability finding):
  - **(A) Cross-core / backplane wait** — fw issued a transaction to an unclocked/stuck SB core; bus read backpressures the ARM core indefinitely. CPU stalled at memory-subsystem level.
  - **(A') RTE scheduler WFI-stall** — fw's scheduler at 0x115C ran out of runnable callbacks, wrote the sleep-flag, fell through to `wfi` at 0x1C1E. If no IRQ fires (e.g., PCIe MSI not set up because host-fw protocol handshake is incomplete), fw sleeps indefinitely. **Now a first-class candidate** — indistinguishable from (A) on host-side observables (no code runs = no TCM drift).
  - **(B) Inter-thread wait** — an RTOS task blocked on a semaphore/queue. If scheduler is also in WFI, collapses to (A'). Otherwise observed stasis (no TCM drift at T247/T239/T240 across 22 dwells in T252 journal) argues against mixed case.
  - **(C) Tick-scale corruption** — TCM[0x58C98] (blob default 0x50) overwritten to an extreme value, making `target = units * scale` overflow and inner delay loop effectively unbounded. Cheap to falsify.
- **Drift test in captured data (weak)**: T247/T239/T240 values are IDENTICAL across all 22 dwells within the T252 boot (verified by sort -u). But these regions aren't touched by a running-scheduler-in-idle-loop either, so "no drift here" is consistent with both "CPU stopped" AND "CPU running idle-loop that doesn't touch these regions." This evidence does NOT discriminate (A) vs (A'); the T255 sleep-flag probe is the real discriminator.
- **wlc_phy_attach's own body NOT under suspicion**: 213 insns, only 2 direct dispatch calls both to idx-0 (benign), no tight loops, all BL targets have bounded loops or no loops. Moves emphasis AWAY from the "inside wlc_phy_attach" reading.

### Next-test direction (T255 — candidates for advisor review)

Hardware probe, informed by T254 narrowing + WFI reachability:

1. **PRIMARY: RTE scheduler state probe** — 3 u32 reads:
   - TCM[0x629A4]: callback-list head (if zero, no runnable callbacks — idle)
   - TCM[0x6299C]: current-task pointer (if zero or points-at-zero struct → idle)
   - TCM[0x629B4]: sleep-flag (if nonzero, scheduler wrote it before falling through to WFI)
   If list empty AND sleep-flag set → **(A') WFI-stall confirmed**. High-info per u32.
2. **Tick-scale check**: TCM[0x58C98..+4] — 1 u32. If value != 0x50, (C) is a factor.
3. **Decode 0x9355C family**: TCM[0x93550..0x9358C] — 16 u32. Extends the 0x934C0 struct-graph mapping.
4. **Deferred**: PHY/MAC register probe via BAR0 (higher-risk, needs gate-on-reset check). Only if (1)+(2)+(3) don't converge.
5. **Deferred**: RTOS task-table enumeration (need TCB layout).

Proposed T255 payload: probes (1) + (2) + (3) at t+60s = 20 u32 total. Cheaper than T253 (32 u32). Discriminates (A) vs (A') vs (C).

Advisor call before committing to T255 design.

---

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
