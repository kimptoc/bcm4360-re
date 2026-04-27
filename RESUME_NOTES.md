# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-27 ~end-of-session — **T299/T300 series RE-RE-FRAMED the wake-gate question. Static-trace investigation reached convergence-without-progress. Strategic recalibration needed before next probe.**)

**T299 series (a-z) traced from FW reset vector to identify what actually runs:**
- **Bootstrap → fn@0x268 → fn@0x2408 (real C main, 5 insns) → fn@0x11d0 (idle loop)**
- **Idle loop tail-call chain: fn@0x11d0 → bl 0x11cc → b.w 0x1c0c → b.w 0x1c1e (wfi;bx lr)** — verified, fn@0x11cc and 0x1c0c are 4-byte tail-call wrappers without push-lr that fn-start heuristic missed.
- **8 ARM exception vectors all converge to fn@0x138 unified dispatcher** which reads *(0x224) for handler ptr. NO code installs *(0x224); single cpsie ai found at 0x4356e is FALSE POSITIVE (binary data misdisasm).
- **BFS from bootstrap reaches 311 fns, all hndrte.c (HNDRTE = Hardware Native Run-Time Environment) — dongle-side ARM-CR4 PCIe-protocol runtime.**
- **Live BFS does NOT reach: wl_probe, wlc_attach, wlc_bmac_attach, fn@0x142E0 (0x48080-writer), wlc_bmac_up_finish, pciedngl_probe, pciedngl_isr, bcm_olmsg_init, wrap_ARM, wlc_dpc.** All wifi/offload entry points appear orphaned from live execution.
- **wl_probe (0x67614) has 0 direct callers; only 1 fn-ptr in orphaned 0x58F1C handlers table** (which T299g showed has 0 readers).
- **fn@0x142E0 (0x48080 writer) has 2 callers: wlc_bmac_attach (dead) and fn@0x11704 (also reachable only from wl_probe via literal-pool fn-ptr).**

**T300: ZERO live writers to D11+0x16C INTMASK in entire blob.** All 8 +0x16C stores are in fns NOT in live BFS. The dead FullMAC chain is the only known wake-arm path. movw/movt pair scan = 0 (no indirect 32-bit construction).

**T301 (kernel source review):** brcmfmac/pcie.c writes `BRCMF_PCIE_PCIE2REG_INTMASK` at PCIe2 core +0x24 = **0x00FF0300**, NOT D11 INTMASK at +0x16C and NOT 0x48080. The "wake gate at D11+0x16C with mask 0x48080" hypothesis from prior sessions may have been chasing the wrong register entirely.

**Convergence-without-progress signals:** repeated self-corrections on heuristic findings:
- T299s "311 fns / no wifi" → corrected by T299t (need IRQ trace) → 319 still no wifi
- T299t "IRQs disabled forever" → corrected by T299y (cpsie was FP)
- T299z "wfi unreachable" → corrected (wfi IS reachable via tail-call chain heuristic missed)
- Each correction kept the same heuristic stack: push-lr-as-fn-start + direct-bl + bx-via-pool

**Strategic moment:** advisor recommends stopping static-trace. Real questions to resolve:
- (a) Where does host-observed flag_struct[+0x64] = 0x48080 come from? Direct host write? Cache of host-set value? Coincidence with the ONE 0x48080 literal in fw (at file 0x14318)?
- (b) Is the FW actually waiting at wfi for D11 INTMASK events, or for PCIe doorbell from host?
- (c) What does fn@0x11cc (the main loop event processor) actually do?

**T302 (kernel source review, no probe):** brcmfmac/pcie.c contains an extensive H2D mailbox/doorbell wake test series — test.240 (ring H2D_MAILBOX_1), test.258/259/260/262 (MAILBOXMASK + H2D_MAILBOX_1 with no-op IRQ handler), test.279 (H2D_MAILBOX_1 then H2D_MAILBOX_0 to trigger pciedngl_isr per T274), test.280 (enable MAILBOXMASK = 0xFF0300), test.284 (pre-set_active MAILBOXMASK with persistence). These were ALREADY run in prior sessions and per KEY_FINDINGS row 125 "MAILBOXMASK writes silently drop". So the H2D mailbox doorbell wake pathway was empirically tested and failed BEFORE the prior session pivoted to the D11+0x16C/0x48080 hypothesis. This session's T299/T300 now shows the D11 path is structurally dead too. Both hypotheses fail empirically AND structurally — there's a missing piece in the wake-mechanism model.

**T303 (CRUCIAL CLARIFICATION — no probe):** The "flag_struct[+0x64] = 0x48080" claim from KEY_FINDINGS row 160 is a STATIC analysis finding (fw code at fn@0x142E0 INTENDS to write 0x48080 there), NOT a runtime observation. brcmfmac/pcie.c has the BCM4360_T290A_CHAIN macro that walks TCM pointers to read flag_struct + 0x88 = BASE — but NO kernel code reads flag_struct + 0x64. So the "host observes 0x48080" framing this session was based on misreading the prior session's static finding. With the writer fn@0x142E0 in dead FullMAC code (T299 verified), the actual runtime value of flag_struct[+0x64] is likely 0 — fw never executes the write in offload mode. **This means there is NO PARADOX between this session's T299/T300 (FullMAC chain dead) and the prior session's KEY_FINDINGS (wake gate identified as D11+0x16C/0x48080). They're CONSISTENT — the wake-arm path was statically identified, but it's dead code.** What's missing from the prior session's analysis is the recognition that "wake gate identified" ≠ "wake gate ARMED at runtime" in offload-mode fw.

**T304 (EMPIRICAL CONFIRMATION — primary source, no probe):** test.290.journalctl.txt shows the only existing runtime data on the wlc_* chain. test.290a walks `TCM[0x96F48+4]` expecting `0x1146D` (wlc_isr fn ptr). Both n=2 results (pre-write and post-write at pre-set_active timing) returned `wrong-node-fn-not-wlc-isr` with `node_fn=0xae8f1edb` (uninitialized/random data), `wcc=0`, `wpub=0`, `dc=0`, `fs=0`, `base=0`. **The wlc_isr scheduler node at 0x96F48 was NEVER populated.** This is empirical (host runtime read of TCM) confirmation that the FullMAC chain (wl_probe → wlc_attach → ... → install scheduler node) does NOT execute in offload-mode fw, consistent with T299 static-trace findings. Re-enabling test.290a at later stages (post-set_active, post-T276-poll, post-T278) in a future test would strengthen this from n=2 to n>3.

**T305 (SCHED_CTX vs FLAG_STRUCT distinction — primary source from test.287c.journalctl.txt):** test.287c reads sched_ctx fields at multiple stages. Stable readings at t+5s, t+30s, t+90s show sched_ctx IS populated:
- `sched[+0x10]=0x00000011` (small flag)
- `sched[+0x18]=0x58680001` (TCM ptr — likely a sub-struct)
- `sched[+0x88]=0x18001000` (D11 MAC core base)
- `sched[+0x8c]=0x18000000` (chipcommon base)
- `sched[+0x168]=0x00000000` (would-be D11 macintstatus mirror — never fired)
- `sched[+0x254..0x268]=0x18101000/0x18102000/0x18103000/0x18104000` (D11/CC/ARM-CR4/PCIe2 WRAPPER bases)
- `sched[+0x26c..0x270]=0` (post-set_active populates 0x25c-0x268 wrappers)
- MAILBOXMASK=0x00000000, MAILBOXINT=0x00000000 (no PCIe2 mailbox events at any timing)

**Key insight:** sched_ctx ≠ flag_struct. sched_ctx is the silicon-info struct (`si_t`) populated by si_doattach (fn@0x670d8 — IN my live BFS). Both si_t and flag_struct happen to have D11 base at +0x88 (BCM convention). The prior session likely conflated them because of the matching offset. flag_struct (with wake mask at +0x64, allocated/populated by dead wlc_bmac_attach) is a SEPARATE struct that doesn't exist in offload-mode fw.

**Strategic implication:** "fw freezes at WFI" is NORMAL IDLE behavior — fw is alive, sched_ctx stable across 90s, all expected fields populated, just sitting at wfi waiting for events. The mystery isn't "what's wrong with the fw" but "what wake event does fw expect that isn't being generated". sched[+0x168]=0 (D11 macintstatus mirror) confirms NO D11 events ever fired across the test window, so D11 isn't the wake source.

**Wake-mechanism candidates (renumbered per this session's understanding):**
1. **PCIe2 mailbox doorbell (H2D_MAILBOX_0/1)** — empirically tested, "silently drops" per row 125
2. **D11 macintstatus events** — sched[+0x168]=0 across 90s, no events generated
3. **Chipcommon INT path** — never empirically tested with the right register
4. **PCIe MSI** — host enables MSI in some tests; need to verify which IRQ vector connects
5. **Direct memory polling** — fw's main loop fn@0x11cc may poll a host-shared structure, no IRQ needed

**T306 (READY-TO-FIRE OPPORTUNITY for next session):** test.288a (chipcommon-wrap + PCIE2-wrap register read) has NEVER been run — checked all phase5/logs/*.txt. It's a READ-ONLY probe that reads:
- chipcommon-wrap (0x18100000) +0x000 (oobselina30) and +0x100 (oobselouta30)
- PCIE2-wrap (0x18103000) +0x000 and +0x100

These are the **AI-backplane wrapper agent OOB-selector registers** — the leading candidate for "chipcommon-side wake target" per KEY_FINDINGS row 148. test.288a fires at every T287 stage, giving runtime values across pre-set_active, post-set_active, t+5s/30s/90s timings. Adding `bcm4360_test288a_wrap_read=1` to the next insmod (no rebuild needed — test is already compiled in) would close candidate #3 with primary-source data. Substrate noise risk applies (per row 85); 2-4 attempt budget likely needed.

**Search of brcmfmac source for D11 INTMASK / 0x48080 / macintstatus / 0x16c**: ZERO matches. The host driver only writes the PCIe2-core INTMASK at +0x24 (0x00FF0300) and touches D11 only for reset/coredisable via `wrapbase + BCMA_IOCTL/BCMA_RESET_CTL`. Host driver never writes D11+0x16C or 0x48080.

**Strategic recommendation for next session:**
1. **Audit prior wake-gate KEY_FINDINGS rows** (especially rows 158/159/160) given the structural-dead-code finding. The wake-gate identification at "D11+0x168 with mask 0x48080" was technically correct as a finding ABOUT THE FullMAC code, but NOT load-bearing for offload-mode fw runtime behavior.
2. **Look elsewhere for the wake gate** — chipcommon INTMASK at +0x104, ARM-CR4 wrapper-side gate, or PCIe doorbell mechanism not yet tested. Also: the chipcommon-wrapper write hypothesis at row 148 ("wrap+0x100" wake target) was untested — that may be the actual gate.
3. **Avoid more static-disasm probes** until a runtime data point is gathered — convergence-without-progress is the failure mode.

**Unresolved from prior session:** substrate-null cluster (T294/T295/T296), n=3 stopping rule triggered. No hardware fires this session.

## Prior state (2026-04-26 23:35 BST — POST-TEST.295 NULL FIRE; n=2 of 3-stopping-rule; PRE-TEST.296 plan was a plain re-fire on tight-freshness substrate.)

---

## PRE-TEST.295 (2026-04-26 23:25 BST — **PLAIN RE-FIRE of T294 on tight-freshness substrate. Same binary, same params, no rebuild. Goal: land the 11-anchor read-only chipcommon discriminator probe to resolve T293 firing-#4's `orig=0xffffffff` into (a)/(b)/(c). T290B-wedge confound is structurally absent — T294 fires BEFORE T290B at the same site. Advisor recommended path.**)

### Goal — single bit of information

Resolve T293 firing-#4 `orig=0xffffffff` anomaly per PRE-TEST.294's discriminator table:
- (a) `select_core(CHIPCOMMON)` silently failed at post-T276-poll → window stayed at 0x18102000 (ARM-CR4 wrapper); read at "CC+0x54" hit the wrapper, write wedged ARM-CR4 wrapper
- (b) Chipcommon BCAST_DATA genuinely went 0 → 0xffffffff during 2s poll (fw wrote it during init)
- (c) Chipcommon access path itself degraded after fw scheduler dispatch (all-1s reads, write hangs)

### Why re-fire instead of rebuild (advisor)

T294 fires the read-only probe **BEFORE** T290B at the same post-T276-poll site (PRE-TEST.294 line 43). The SUMMARY values are captured first; the post-T294 T290B firing is just expected n-replication on the existing T293 wedge finding. It does NOT poison T294's read-only data. Building "T294 minus T290B" would burn time for zero information gain.

### Substrate prerequisites — STRICT

- ⚠️ **Tight freshness REQUIRED**: insmod within ≤2 min of cold-cycle boot. T294 fired at uptime ~1h53min and wedged.
- ⚠️ T288c proved fresh substrate can still wedge — freshness shifts the probability, doesn't guarantee success.
- ⚠️ Verify `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'` is clean immediately before insmod.
- Per KEY_FINDINGS row 85: ~1/4 fires reach the probe site. Realistic plan: **2-4 attempts**, each requiring full cold cycle + likely SMC reset on null/wedge.
- Per KEY_FINDINGS row 84: watchdog n=5/5 NOT auto-recovering recent fires; user SMC reset cost is fixed per attempt.

### Discriminator outcomes

Identical to PRE-TEST.294's table (lines 26-37 above). Re-stated for completeness:

| `bar0_after_select` | `chipid` | `bcast1`/`bcast2` | Reading |
|---|---|---|---|
| ≠ `0x18000000` | (irrelevant) | (irrelevant) | **(a) CONFIRMED** — select_core silently failed |
| `0x18000000` | valid | both `0xffffffff` | **(b) CONFIRMED** — BCAST_DATA genuinely flipped |
| `0x18000000` | `0xffffffff` | `0xffffffff` | **(c) CONFIRMED** — chipcommon path degraded |
| `0x18000000` | valid | both `0x00000000` | **NONE** — T293 was a one-off; need T296 re-fire |
| Wedges before t294 a3 | — | — | select_core wedges at config_dword (distinct from (a)) |
| Wedges between a4 and a5 | — | — | chipid READ wedges — (c)-strong |
| Wedges between a6 and a7 | — | partial | First BCAST_DATA read wedges — (c)-strong |
| Wedges UPSTREAM of T294 fire (test.158, etc.) | — | — | NULL — substrate noise; re-fire as T296 with same params |

### Diff vs T294 fire

ZERO. Same binary (anchors verified by `strings | grep 't294 '` — all 11 + SUMMARY present). Same insmod params:
- `bcm4360_test236_force_seed=1`, `bcm4360_test238_ultra_dwells=1`
- `bcm4360_test276_shared_info=1`, `bcm4360_test277_console_decode=1`, `bcm4360_test278_console_periodic=1`
- `bcm4360_test284_premask_enable=1`
- `bcm4360_test287_sched_ctx_read=1`, `bcm4360_test287c_extended=1`
- `bcm4360_test290a_chain=0`, `bcm4360_test290b_cc_write=1`
- `bcm4360_test294_cc_ro_probe=1`

### Fire command (identical to T294)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test290a_chain=0 \
    bcm4360_test290b_cc_write=1 \
    bcm4360_test294_cc_ro_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.295.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.295.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.295.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.295.journalctl.txt`.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same brcmfmac.ko binary as T294 (anchors verified via strings)
2. ✓ Hypothesis stated above (resolve (a)/(b)/(c))
3. (user) PCIe state check: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
4. ✓ Plan committed and pushed BEFORE fire (this commit)
5. ✓ FS sync after push
6. (user) Cold cycle done; insmod within ≤2 min of cold-cycle boot for tightest freshness

### Risk and recovery

- T295's READ-ONLY phase carries no wedge risk if it reaches a0..a10
- T290B firing AFTER T294 at post-T276-poll is expected to wedge (T293 pattern). Cold cycle + SMC reset will be needed regardless of (a)/(b)/(c) outcome
- Watchdog n=5/5 NOT auto-recovering — user SMC reset will be needed
- Substrate-noise null is the realistic mode failure (~75% per row 85)

### Stopping rule for T295 series

If T295/T296/T297 all null at upstream wedges (3 consecutive substrate nulls at probe-block-1+ stages), per KEY_FINDINGS row 85 stopping rule: pivot to (γ-c) — pick a different MMIO surface for the wake-gate experiment (TCM-scribble at `[node+0xc]` per row 148 is the leading candidate). Don't burn 5+ SMC resets chasing one bit on a substrate-pathological week.

### What this fire DOES NOT test

- ❌ Whether removing T290B from post-T276-poll prevents the wedge (T290B left enabled — leave for downstream test if (a)/(b)/(c) settled)
- ❌ Whether T290B at post-set_active wedges on multiple firings (n=1 clean so far)
- ❌ Anything about the PCIe MAILBOXMASK confound from POST-TEST.293's side-observation

---

## POST-TEST.295 (2026-04-26 23:24:09 BST fire, boot -1 — **NULL FIRE. Wedged AFTER `test.188 root port 0000:00:1c.2 LnkCtl after=0x0040 ASPM=0x0 CLKREQ=off` (line 1103 of journal). Made it ~1s further than T294 (which wedged AT `test.158 LnkCtl read before=0x0143`). ZERO `t294` anchors, ZERO set_active markers, ZERO T276/T290B markers. Watchdog did NOT auto-recover; user SMC reset (n=6/6 cluster across T288c/T290/T292/T293/T294/T295). T293 firing-#4 `orig=0xffffffff` anomaly UNRESOLVED.**)

### Comparison to T294 fire

| Stage | T294 (21:25 BST) | T295 (23:24 BST) |
|---|---|---|
| `test.158 about to read LnkCtl before ASPM disable` | ✓ logged | ✓ logged |
| `test.158 LnkCtl read before=0x0143 — disabling ASPM` | ✓ LAST | ✓ logged |
| `test.158 pci_disable_link_state returned — reading LnkCtl` | — wedged | ✓ logged |
| `test.158 ASPM disabled; LnkCtl before=0x0143 after=0x0140` | — | ✓ logged |
| `test.188 root port LnkCtl before=0x0040 — disabling L0s/L1/CLKPM` | — | ✓ logged |
| `test.188 root-port pci_disable_link_state returned` | — | ✓ logged |
| `test.188 root port LnkCtl after=0x0040` | — | ✓ LAST |
| Anything past root-port-ASPM | — | — wedged |

T295 progressed ~5 lines further than T294. Still **fully upstream** of `test.276` (set_active+share_info path) and `t294 a0..a10` discriminator anchors. Maps to PRE-TEST.295 discriminator table row "Wedges UPSTREAM of T294 fire (test.158, etc.) — NULL — substrate noise; re-fire as T296 with same params."

### Substrate-noise null cluster (cumulative, same binary path)

| Test | Wedge site | Site relative to T294 probe |
|---|---|---|
| T294 | test.158 LnkCtl read | UPSTREAM |
| T295 | test.188 root port LnkCtl after=0x0040 (just after) | UPSTREAM (1s further) |

**n=2 substrate nulls** of 3-stopping-rule (KEY_FINDINGS row 85 + PRE-TEST.295 stopping rule). Wedge points differ — both are PCIe config-space adjacent (LnkCtl reads via pci_disable_link_state). Confirms KEY_FINDINGS row 85 extension: "Substrate-noise null fires can wedge at ANY config-space write or BAR write the host issues during pre-set_active."

### Watchdog recovery trend

n=6/6 user SMC resets required since 09:57 BST 2026-04-26 (T288c/T290/T292/T293/T294/T295). Earlier auto-recovery baseline still holds for older fires. Cluster confined to recent host-side chipcommon-RMW / LnkCtl / probe-during-fw-dispatch fires. Update KEY_FINDINGS row 84 from n=5/5 → n=6/6.

### Decision: T296 plan

Per stopping rule (n=3 substrate nulls → pivot), one more attempt is on the documented path. Substrate freshness was tight for T295 (insmod ~5 min from cold boot per `Apr 26 23:24:09` vs `Apr 26 23:09:55` boot); even tighter freshness for T296 would only marginally shift the probability. PRE-TEST.296 = plain re-fire of T295 (which was a plain re-fire of T294 — same binary, same params).

---

## PRE-TEST.296 (2026-04-26 23:35 BST — **PLAIN RE-FIRE of T295 on tight-freshness substrate (~10 min uptime now). Same binary, same params, no rebuild. Goal: land the 11-anchor read-only chipcommon discriminator probe. n=3 of 3-stopping-rule — if this also nulls, pivot to (γ-c) per KEY_FINDINGS row 85.**)

### Diff vs T295 fire

ZERO. Same brcmfmac.ko binary (anchors verified in T294/T295 — no rebuild). Same insmod params:
- `bcm4360_test236_force_seed=1`, `bcm4360_test238_ultra_dwells=1`
- `bcm4360_test276_shared_info=1`, `bcm4360_test277_console_decode=1`, `bcm4360_test278_console_periodic=1`
- `bcm4360_test284_premask_enable=1`
- `bcm4360_test287_sched_ctx_read=1`, `bcm4360_test287c_extended=1`
- `bcm4360_test290a_chain=0`, `bcm4360_test290b_cc_write=1`
- `bcm4360_test294_cc_ro_probe=1`

### Discriminator outcomes (unchanged from T294/T295)

See PRE-TEST.295 table above. Same (a)/(b)/(c)/NONE/wedge-class outcomes.

### Substrate prerequisites

- ✓ Cold cycle done (~23:30 BST per uptime ~5min when run)
- ✓ PCIe state verified clean: `<MAbort-` `CommClk+` `LnkSta: 2.5GT/s x1`
- Tight freshness desirable; current uptime acceptable (~10 min)

### Fire command (identical to T295)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test290a_chain=0 \
    bcm4360_test290b_cc_write=1 \
    bcm4360_test294_cc_ro_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.296.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.296.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.296.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.296.journalctl.txt`.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same brcmfmac.ko binary as T294/T295
2. ✓ Hypothesis stated above (resolve (a)/(b)/(c); n=3 of stopping rule)
3. ✓ PCIe state checked clean (`<MAbort-` `CommClk+`)
4. (will commit and push this PRE-TEST.296 block before fire — this commit)
5. ✓ FS sync after push
6. (user) Awaiting fire clearance — substrate fresh from cold boot

### Stopping rule for T296

If T296 also nulls at upstream wedge: cumulative n=3 substrate-noise nulls. Per KEY_FINDINGS row 85, pivot to **(γ-c) — TCM-scribble at `[node+0xc]` per KEY_FINDINGS row 148** (test the wake-gate hypothesis on a different MMIO surface that doesn't share PCIe-config-space wedge mode). Don't burn a 4th SMC reset re-firing the same probe path.

If T296 lands: record (a)/(b)/(c) outcome per discriminator table; mark KEY_FINDINGS row 159 LIVE n=1 anomaly resolved.

---

## POST-TEST.296 (2026-04-26 23:43:45 BST fire, boot -2 — **NULL FIRE. Wedged silently after `test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11` (line 1106 of journal). Furthest of the 3 substrate-noise null fires (T294=test.158, T295=test.188, T296=test.193). Reached chip_attach completion + ARM CR4 halt + raminfo + chipid lookup, but wedged before NVRAM/fw download (test.225) and upstream of every T276/T284/T287/T290B/T294 anchor. Watchdog did NOT auto-recover; user did cold boot + SMC reset (n=7/7 cumulative). T293 firing-#4 `orig=0xffffffff` anomaly UNRESOLVED. Stopping-rule triggered: per PRE-TEST.296, pivot to (γ-c) — TCM-scribble at `[node+0xc]`.**)

### Timeline (from `phase5/logs/test.296.journalctl.txt`, boot -2 — 23:30:57→23:44:04)

- `23:30:57` boot -2 start (recovery from T295 cold cycle)
- [~13 min idle uptime — fire at modest freshness, well within KEY_FINDINGS row 84's window; tighter than T294 but looser than the optimum ≤2 min target]
- `23:43:45` insmod entry → `module_init entry — extended post-release TCM sampling`
- `23:43:45` brcmf_core_init / brcmf_sdio_register (no-op for our chip)
- `23:43:47` brcmf_pcie_register / pci_register_driver
- `23:43:48` `test.128: PROBE ENTRY (device=43a0 vendor=14e4 ...)`
- `23:43:49` `test.158: probe entry flush done — proceeding` ← past the T294 wedge point
- `23:43:50` devinfo allocated; pdev assigned
- `23:43:51` SBR via bridge → bridge_ctrl restored → before brcmf_chip_attach
- `23:43:52` BAR0=0xb0600000 BAR2=0xb0400000; BAR0 probes (CC@0x18000000) `0x15034360` x2 — chip alive
- `23:43:53`–`23:43:55` `test.218` host-side core enum (cores 1..5) — bit-identical to T287c/T293
- `23:44:04` `test.218 core[6 ]` + `enumerated 6 cores total` — slow gap then completion
- `23:44:04` buscore_reset → reset_device skipped (probe-start SBR already done)
- `23:44:04` `test.145: halting ARM CR4 after second SBR` → `test.145: ARM CR4 halt done`
- `23:44:04` `test.188: post-145 ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`
- `23:44:04` `test.121: using fixed RAM info rambase=0x0 ramsize=0xa0000 srsize=0x0`
- `23:44:04` `test.125: get_raminfo returning 0`
- `23:44:04` `test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11` ← **LAST LOG LINE**
- [silent backplane hang — no NVRAM print, no test.225 fw chunks, no setup-entry, no T276/T284/T287/T290B/T294]
- (multi-hour gap; user away)
- `06:29:20` (Mon 2026-04-27) brief boot -1 (~2.5 min, kernel-only — no brcmfmac fire)
- `06:39:28` boot 0 — recovery clean

### Critical primary-source findings

**Finding 1 (LOAD-BEARING — substrate-null cluster grows to n=3):** T296 wedged silently mid-host-side init at `test.193` (chipid printout). ZERO `t294 a*` lines, ZERO T276/T284/T290B markers. Combined with T294 (wedge at test.158) and T295 (wedge at test.188), this completes 3 consecutive substrate-noise null fires on the same binary path. Wedge points span the host's pre-set_active config-space + chip_attach window. PRE-TEST.296's stopping rule fires.

**Finding 2 (substrate-null progression depth varies):** T294 wedged early (test.158, ~17 lines into probe), T295 a bit later (test.188, ~25 lines), T296 deeper (test.193, ~40 lines past probe entry). All three sites are different. Confirms KEY_FINDINGS row 85 wording: "Substrate-noise null fires can wedge at ANY config-space write or BAR write the host issues during pre-set_active." T296 added a NEW wedge point (test.193 chipid printout — completes chip_attach but wedges before fw_download / NVRAM).

**Finding 3 (UNRESOLVED — T293 firing-#4 `orig=0xffffffff` discriminator):** No T294 anchor (a0..a10) printed across T294/T295/T296 — three attempts, zero discriminator data. The (a) select-core silent-fail / (b) genuine BCAST_DATA flip / (c) chipcommon path degraded question stays LIVE. Per stopping rule, abandoning this probe path.

**Finding 4 (negative — no new chipcommon information):** KEY_FINDINGS row 159 unchanged. Three null fires, zero new T290B firing data on either side.

**Finding 5 (watchdog cluster grows to 7/7):** User SMC reset required again (n=7 since 09:57 BST 2026-04-26). Earlier auto-recovery baseline (n>30) still holds for older fires. Cluster confined to recent chipcommon-RMW / probe-during-fw-dispatch fires. Update KEY_FINDINGS row 84 from n=6/6 → n=7/7.

### Discriminator outcome (per PRE-TEST.296 / PRE-TEST.295 table)

Closest match: "Wedges UPSTREAM of T294 fire (test.158, etc.) — NULL — substrate noise; re-fire as T296 with same params." T296 *was* that re-fire; n=3 nulls reached. Stopping rule activates.

### Crash markers — what's NOT present

- ❌ No AER UR/CE markers (`pci=noaer` blinds us)
- ❌ No NMI / hardlockup / softlockup / panic / Oops / BUG / Call Trace
- ❌ No PCIe link state events
- ❌ No T294 anchor (a0..a10), no T290B/T287/T276/T284 anchor
- Pure silent backplane hang at chipid print — consistent with the T294/T295 wedges and the wider T288a'/T288c upstream-wedge family

### Substrate (current — recovery boot 0)

- Boot 0 since 06:39:28 BST, uptime ~3 min at this writeup
- PCIe state: `<MAbort-` (clean) — cold cycle was effective
- 0 brcmfmac modules loaded, 0 fires this boot
- Per CLAUDE.md: pivot decision next, not another T296-style fire

### KEY_FINDINGS impact

- **Row 84** — update n=6/6 → n=7/7 (T288c/T290/T292/T293/T294/T295/T296 all required user SMC reset).
- **Row 85** — extend the cumulative wedge-point list to 6 (post-T276 / OTP-bypass / fw chunk-1 / LnkCtl-ASPM-disable / root-port-LnkCtl / chipid-print). T296 adds the chipid-print wedge — deepest into chip_attach yet for the substrate-null cluster.
- **Row 159** — UNCHANGED (no new T290B firing data this fire).

### Decision (per stopping rule + PRE-TEST.296)

n=3 substrate-noise nulls. Burning a 4th cold-cycle + SMC reset on the same probe path is explicitly disallowed by the stated rule. Two options:

- **(γ-c) TCM-scribble at `[node+0xc]`** (PRE-TEST.296 default pivot) — test wake-gate hypothesis on a different MMIO surface (TCM, not chipcommon BAR0). Avoids the PCIe-config-space wedge family because the only host writes are TCM (BAR2-mapped iowrite32). Per KEY_FINDINGS row 148, `[node+0xc]` is the scheduler-side software flag mask; writing a bit into it could conceivably flip a pending-event for fn@0x1146C's dispatch. Caveat: row 148 itself is now "STRUCTURALLY WEAKER" per row 158 — without identifying flag_struct's allocation point and its [+0x88] writer, the wake-gate base address is not statically determinable. The TCM target may be wrong.
- **(δ) Build broader observability before another fire** — defer hardware fires; do disasm / blob-static work to identify flag_struct's allocation point (per row 158's call to "trace flag_struct's allocation point and find the writer of its [+0x88] field"). Lower wedge risk; advances row 158 toward CONFIRMED.

Both are LIVE. Advisor consult next — present the choice between (γ-c) and (δ) with the row 158 caveat that the wake-gate target itself is shaky.

### What was NOT settled

- ❌ The (a)/(b)/(c) discriminator for T293 firing-#4 `orig=0xffffffff` — STILL OPEN, abandoned per stopping rule.
- ❌ Whether T290B at post-T276-poll wedges reproducibly (n=1 from T293 alone — never re-fired successfully).
- ❌ Wake-gate target identity (row 148 / row 158 LIVE).

### Next-fire candidates (advisor consult required)

- **(γ-c) TCM-scribble probe at scheduler-node [+0xc]** — minimal write, BAR2-mapped (different wedge mode than BAR0 config space). Read-then-write-then-readback protocol. Probe site: post-T276-poll where T293 anomaly fired. **Builds on row 148 which is now structurally weaker** (row 158).
- **(δ) Static disasm pivot — find flag_struct allocator + [+0x88] writer** — zero hardware fires until row 158 promotes CONFIRMED. Advances wake-gate target identification before the next live experiment.
- **(ε) Different post-T276-poll probe target — ARM-CR4 wrapper RMW** — directly tests the (a) reading from T294's discriminator (whether select_core silent-fail leaves writes hitting ARM-CR4 wrapper). Different MMIO surface than chipcommon; probably safer than re-firing T290B at post-T276-poll. Same set_active wedge confound family as before.

---

## PRE-TEST.294 (2026-04-26 21:25 BST — **READ-ONLY CHIPCOMMON DISCRIMINATOR at post-T276-poll. Resolves T293 firing-#4's `orig=0xffffffff` anomaly into (a)/(b)/(c). REBUILT — 11 new anchors (a0..a10) verified in module. Same baseline params as T293, plus `bcm4360_test294_cc_ro_probe=1`.**)

### Hypotheses (carryover from POST-TEST.293)

T293 firing #4 (post-T276-poll T290B): wedged at anchor-3→anchor-4 (during write of 0xDEADBEEF) with anomalous `orig=0xffffffff` at anchor-3. Three live readings:

- **(a) `select_core(CHIPCOMMON)` silently failed** — config_dword write didn't take, BAR0_WINDOW stayed at 0x18102000 (ARM-CR4 wrapper at this timing); the read at T290B's anchor-2→3 actually hit `0x18102000+0x54` (ARM-CR4 wrapper offset) which returned 0xffffffff because that wrapper word is unmapped; the subsequent write went to ARM-CR4 wrapper while ARM was running → wedge.
- **(b) Chipcommon BCAST_DATA genuinely went 0→0xffffffff during the 2s poll** (fw wrote it during init).
- **(c) Chipcommon access path itself is degraded after fw scheduler dispatch** — reads return all-1s, writes hang; chipcommon as a backplane core is structurally compromised.

### Discriminator outcomes (single fire)

T294 captures 5 SUMMARY values: `saved_win`, `bar0_after_select`, `chipid`, `bcast1`, `bcast2`. Decision table:

| `bar0_after_select` | `chipid` | `bcast1`/`bcast2` | Reading | Next action |
|---|---|---|---|---|
| ≠ `0x18000000` (e.g. stays at 0x18102000) | (irrelevant — wrong core) | (irrelevant) | **(a) CONFIRMED** — select_core silently failed at post-T276-poll. T293's wedge was a write to ARM-CR4 wrapper while ARM was running. | KEY_FINDINGS row 159 corrects — "wedge" → "select_core silent-fail at post-T276-poll". Investigate why select_core fails (config_dword write to BAR0_WINDOW) — separate phenomenon from chipcommon writability. |
| `0x18000000` | valid (~`0x15034360`, low 16 bits = `0x4360`) | `0xffffffff` (both reads) | **(b) CONFIRMED** — BCAST_DATA genuinely went 0→0xffffffff during 2s poll. Chipcommon access works. T293's wedge was: host wrote to a register fw was mid-modifying. | Row 159: "post-T276-poll WEDGE" reframed — host CC writes during fw scheduler dispatch are genuinely unsafe. T290B's design needs to avoid concurrent fw activity on the same register. |
| `0x18000000` | `0xffffffff` | `0xffffffff` | **(c) CONFIRMED** — chipcommon access path degraded after fw dispatch. All CC reads return all-1s, writes plausibly hang. | Row 159: "post-T276-poll WEDGE" reframed — chipcommon as a target is structurally unavailable post-fw-dispatch. Chase a different MMIO surface for wake-gate experiments. |
| `0x18000000` | valid | `0x00000000` (both reads) | **NONE OF (a)/(b)/(c)** — T293 firing #4 was a one-off; orig=0xffffffff was a transient. | Re-fire T290B at post-T276-poll (T295) to test reproducibility. Possibly a one-off PCIe glitch. |
| `0x18000000` | valid | one read 0x00000000, other 0xffffffff (or other unstable) | **PARTIAL (b)** with timing-sensitivity — fw is actively writing during the read window. | Refine probe with multiple back-to-back reads to capture the transition. |
| Wedges before t294 a3 (no `BAR0_WINDOW after select` print) | — | — | select_core itself wedges at config_dword write (rather than silently fail) — distinct from (a). | Investigate config_dword path; possibly chip cannot tolerate window-switch-back-to-CC at this timing. |
| Wedges between t294 a4 and a5 | — | — | chipid READ wedges — chipcommon read access itself wedges, not just write. | Chipcommon-degraded reading; relate to (c) but stronger. |
| Wedges between t294 a6 and a7 | — | partial | First BCAST_DATA read wedges — wedge is read-side; even reading scratch register hangs at this timing. | Same family as previous. Strong (c). |

### Diff vs T293 fire

- ADD module param: `bcm4360_test294_cc_ro_probe` (default 0)
- ADD macro: `BCM4360_T294_CC_RO_PROBE(tag)` — 11 anchors + summary line, ZERO writes to chipcommon (only PCI config_dword save/restore of BAR0_WINDOW)
- WIRE T294 at post-T276-poll site (pcie.c:4421) — fires BEFORE T290B at the same site
- KEEP T290B wired at all 4 sites (pre-set_active pre+post-write, post-set_active, post-T276-poll) for continued n-replication
- Insmod params: same as T293 + `bcm4360_test294_cc_ro_probe=1`
- T290B remains `bcm4360_test290b_cc_write=1` — will fire AFTER T294 at post-T276-poll. If T294 reads suggest (a) or (c), T290B wedge is expected (consistent with T293). If T294 reads suggest (b), T290B wedge is also expected. T294's job is to characterize the chip state; T290B's job is to attempt the write again to add to n on the wedge mechanism.

### Substrate prerequisites — REQUIRED

- Boot 0 since 21:08:58 BST. Uptime at writeup ~17 min (within 20–25 min window; past ≤2 min optimal).
- ⚠️ NO COLD-CYCLE NEEDED if firing on current boot 0 (already cold-cycled by user post-T293).
- ⚠️ T294 itself is read-only and should not wedge BUT T290B fires after T294 at the same post-T276-poll site, so the fire is expected to wedge during T290B (just as T293 did). Cold cycle WILL be needed AFTER fire.

### Fire command (T294 added to T293's params)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test290a_chain=0 \
    bcm4360_test290b_cc_write=1 \
    bcm4360_test294_cc_ro_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.294.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.294.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.294.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.294.journalctl.txt`.

### Pre-fire checklist (CLAUDE.md)

1. ✓ REBUILT — module built clean (only pre-existing warnings)
2. ✓ Anchors verified — 11 `t294 a[0-9]+` strings present + 1 SUMMARY string
3. ✓ Hypotheses (a)/(b)/(c) stated above
4. (user) PCIe state check: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
5. ✓ Plan committed and pushed BEFORE fire (on next commit)
6. ✓ FS sync after push

### Risk and recovery

- T294's READ-ONLY phase (a0..a10) carries no wedge risk — read-only PCI config_dword + BAR0 reads on cores already touched by other tests this session.
- T290B firing AFTER T294 at post-T276-poll is expected to wedge (T293 pattern). Cold cycle + SMC reset will be needed.
- If watchdog fails to auto-recover (n=4/4 such events for T288c/T290/T292/T293), user SMC reset will be needed.
- T294 anchor lines are pr_emerg priority — best-effort eager flush.

### What this fire DOES NOT test

- ❌ Whether removing T290B from post-T276-poll prevents the wedge (T290B left enabled — leave that for T295 if T294 picks (a)/(b)/(c))
- ❌ Whether T290B at post-set_active wedges on second/third firing (n=1 clean at post-set_active so far — needs more samples eventually)

---

## POST-TEST.294 (2026-04-26 23:02:25 BST fire, boot -1 — **NULL FIRE. Wedged at `test.158: LnkCtl read before=0x0143 — disabling ASPM` (line 1133). UPSTREAM of any T294/T290B anchor — ZERO discriminator data captured. T293 firing-#4 `orig=0xffffffff` anomaly UNRESOLVED. Watchdog did NOT auto-recover; user SMC reset (n=5/5 such events for T288c/T290/T292/T293/T294).**)

### Timeline (from `phase5/logs/test.294.journalctl.txt`, boot -1 — 21:08:58→23:02:25)

- `21:08:58` boot -1 start (recovery from T293 cold-cycle)
- [~1h53min idle uptime — fire NOT in PRE-TEST.294's recommended ≤2 min freshness window; near upper edge of KEY_FINDINGS row 84's 20–25 min window]
- `23:02:05` insmod entry → SDIO module init → PCIe register → PROBE ENTRY
- `23:02:09` SBR via bridge → chip_attach
- `23:02:11` BAR0 probes alive (CC@0x18000000 returns `0x15034360` twice — chip alive)
- `23:02:11`–`23:02:13` test.218 host-side core enum (6 cores, all expected — bit-identical to T293/T287c)
- `23:02:15`–`23:02:17` buscore_reset → ARM CR4 halt → CPUHALT=YES
- `23:02:17`–`23:02:18` get_raminfo (rambase=0x0 ramsize=0xa0000 srsize=0x0 — match)
- `23:02:19`–`23:02:21` PMU WARs + max/min res_mask programming + post-settle (matches baseline)
- `23:02:22` brcmf_chip_attach returned successfully
- `23:02:23` ARM CR4 core->base=0x18002000 (no MMIO issued)
- `23:02:23`–`23:02:24` pci_clear_master → BusMaster cleared
- `23:02:24` test.158: about to read LnkCtl before ASPM disable
- `23:02:25` test.158: LnkCtl read before=0x0143 — disabling ASPM ← **LAST LOG LINE**
- [silent backplane hang — no `disabled` confirmation, no setup-entry, no T276/T284/T287/T290B/T294 anchor]
- `23:09:55` boot 0 (recovery — only after user SMC reset; watchdog did NOT auto-recover, n=5/5 cumulative)

### Critical primary-source findings

**Finding 1 (LOAD-BEARING — substrate-null pattern continues): T294 wedged at LnkCtl/ASPM-disable, UPSTREAM of every T294 and T290B anchor.** ZERO `t294 a*` lines, ZERO `t290b ` lines in the journal. The wedge happened during the host's PCI config-space write to disable ASPM (test.158, between log line "about to read LnkCtl" and any subsequent "disabled" confirmation). This is bit-identical to the T288a'/T288c upstream-wedge pattern: both wedged at PCI config-space writes (OTP-bypass / fw chunk-1) before any probe code reached its instrumentation. Substrate flakiness (KEY_FINDINGS row 85) wedges at random points along the same code path even within the "clean window" — T294 confirms the row's claim n+1 times.

**Finding 2 (UNRESOLVED): T293 firing-#4 `orig=0xffffffff` discriminator question (a)/(b)/(c) was NOT touched by this fire.** No T294 anchor (a0..a10) printed; no SUMMARY line. T294 read `chipid` and `bcast1`/`bcast2` were never sampled. The discrimination between (a) select_core silent-fail / (b) genuine BCAST_DATA flip during 2s poll / (c) chipcommon access path degraded remains LIVE.

**Finding 3 (substrate observation): Fire at uptime ~1h53min (well past optimal ≤2 min freshness) preceded the wedge.** Cannot conclude staleness caused this fire's wedge — T288c wedged at uptime ~1.5 min on a fresh post-cold-cycle boot. But re-firing on tight-freshness substrate (≤5 min from cold cycle) is cheap insurance for any T295.

**Finding 4 (negative — no new chipcommon information): KEY_FINDINGS row 159 (n=3 pre-set_active clean / n=1 post-set_active clean / n=1 post-T276-poll WEDGE) is unchanged.** T294 did not add to either positive or wedge counts.

### Discriminator outcome (per PRE-TEST.294 table)

The closest match in the discriminator table:
> **Wedges before t294 a3 (no `BAR0_WINDOW after select` print)**: select_core itself wedges at config_dword write (rather than silently fail) — distinct from (a). Investigate config_dword path; possibly chip cannot tolerate window-switch-back-to-CC at this timing.

**This row does NOT apply** — the wedge happened BEFORE the T294 macro could fire at all (BEFORE setup callback, BEFORE T276/T284/T287/T290B). The wedge is in the host's pre-setup ASPM-disable path, orthogonal to T294's probe target. Discriminator table simply did not get a chance to apply.

### KEY_FINDINGS impact

- **Row 85 (substrate flakiness wedges at random progress points)** — T294 adds another within-clean-window null data point. List grows: T288a (post-T276 wedge), T288a' (OTP-bypass wedge), T288c (fw chunk-1 wedge), T294 (LnkCtl/ASPM-disable wedge). Different upstream wedge points across same Phase 5 binary path. Row to be edited to include T294.
- **Row 159 (chipcommon writes / orig=0xffffffff anomaly)** — UNCHANGED. T294 added zero data on either side.

### What was NOT settled

- ❌ The (a)/(b)/(c) discriminator for T293 firing-#4 `orig=0xffffffff` — STILL OPEN.
- ❌ Whether removing T290B from post-T276-poll prevents the wedge — STILL OPEN.
- ❌ Whether the wedge mechanism reproduces (n=1 post-T276-poll wedge from T293 alone).

### Crash markers — what's NOT present

- ❌ No AER UR/CE markers (`pci=noaer` blinds us)
- ❌ No NMI / hardlockup / softlockup / panic / Oops / BUG / Call Trace
- ❌ No PCIe link state events
- ❌ No T294 anchor (a0..a10) — none of the discriminator lines printed
- ❌ No T290B anchor — no `t290b ` lines printed at all
Pure silent backplane hang at LnkCtl write — consistent with all prior pre-set_active wedges under `pci=noaer`.

### Substrate (current — recovery boot)

- Boot 0 since 23:09:55 BST, uptime ~5 min at this writeup
- PCIe state: `Status` clean (`<MAbort-`), `LnkCtl: CommClk+` — cold cycle was effective
- 0 brcmfmac modules loaded, 0 fires this boot
- Per CLAUDE.md substrate rule: T295 will need cold cycle; user already done.

### Build verification

- T294 binary unchanged from PRE-TEST.294 build (no edits since fire). All 11 anchors + SUMMARY string still present in `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko` per pre-fire verification (PRE-TEST.294 step 2).
- For T295: depending on advisor decision, may rebuild (e.g. disable T290B at post-T276-poll site) or re-fire unchanged.

### Next-fire candidates (ordered by information yield, advisor consult required)

- **(α) T295 = T294 with T290B at post-T276-poll DISABLED** — cleanest discriminator. If read-only T294 probe still wedges at post-T276-poll with T290B off → strong (c) (chipcommon access degraded). If probe lands cleanly → unambiguous (a)/(b) discrimination via the SUMMARY values. Removes the known T290B-wedger confound. Requires rebuild + maybe a second module param.
- **(β) Re-fire T294 unchanged on tight-freshness substrate** — cheaper but T290B at post-T276-poll is expected to wedge; discriminator only fires if substrate cooperates AND sequence reaches the post-T276-poll site. Lower yield per fire than (α).
- **(γ) Pivot away from chipcommon path** — defer (a)/(b)/(c) and chase a different MMIO surface (e.g. TCM-scribble at `[node+0xc]` per row 148, or ARM-CR4 wrapper register exploration). Lowest yield right now if (a)/(b)/(c) is genuinely close to settling.

Advisor consult before choosing.

---

## PRE-TEST.293 (2026-04-26 16:35 BST — **PLAIN RE-FIRE of T292. Same binary, same params, no rebuild. Goal: build n=2 on T292's two observations.**)

### Hypotheses

- **H1 (REPLICATION OF POSITIVE)**: First pre-set_active T290B firing's chipcommon BCAST_DATA RMW landed clean in T292 (n=1). T293 should reproduce — `wrote=0xDEADBEEF readback=0xdeadbeef restored=0x00000000`. If yes → n=2 → strong signal that chipcommon writes work; KEY_FINDINGS row promotion candidate after T294.
- **H2 (REPLICATION OF WEDGE)**: Second pre-set_active T290B firing wedged at brcmf_pcie_select_core(CHIPCOMMON) in T292 (n=1). T293 should reveal:
  - **If wedge at same point** (anchor-1→anchor-2 of second firing) → repeatable mechanism, not pure substrate noise → strong reason to add intr_enable-removed variant (B) as T294.
  - **If wedge at different point or no wedge** → substrate noise dominant; row 85 reaffirmed; expand to post-set_active testing.
- **H3 (POST-SET_ACTIVE T290B never tested)**: PRE-TEST.292's H_main is still untested if pre-set_active wedge happens again. Needs separate fire after H1/H2 settle.

### Discriminator outcomes (single fire)

| What we observe | Reading | Next action |
|---|---|---|
| Both pre-set_active firings clean + post-set_active T290B clean + ladder reaches t+90s | **GREEN — full replication + extension** (best case); n=2 chipcommon-writes-land | Promote KEY_FINDINGS row to CONFIRMED-narrow after T294 (n=3); pivot to write-side wake gate experiments. |
| First pre-set_active firing clean, second wedges (T292 EXACT replay) | **H1 + H2 BOTH replicated** | Plan T294 = T293 with intr_enable removed between firings → tests H_B (intr_enable fragility). |
| First pre-set_active firing clean, second clean, post-set_active wedges | **H1 replicated; pre-set_active multi-firing OK; post-set_active wedge replicates POST-TEST.290 H1** | KEY_FINDINGS finding "post-set_active chipcommon writes wedge" → LIVE n=1 → re-fire as T294. |
| First pre-set_active firing wedges (any anchor 0–7) | **H1 NOT replicated; chipcommon writes don't reliably work** | Re-evaluate; T292's first firing was lucky. Pivot to (γ-c) TCM-scribble per stopping rule. |
| Wedge upstream of pre-set_active probe block (test.159, test.225, test.160, etc.) | **3rd consecutive substrate null** | KEY_FINDINGS row 85 stopping rule fires; pivot to (γ-c) TCM-scribble. |
| All probes drain through t+90s late-ladder wedge (T270-BASELINE pattern) | n=2 success on probes; substrate late-wedge is orthogonal | Same as GREEN — re-fire T294 same params. |

### Diff vs T292 fire

ZERO. Same binary (build verified by string scan; no source changes). Same insmod params:
- `bcm4360_test236_force_seed=1`, `bcm4360_test238_ultra_dwells=1`
- `bcm4360_test276_shared_info=1`, `bcm4360_test277_console_decode=1`, `bcm4360_test278_console_periodic=1`
- `bcm4360_test284_premask_enable=1`
- `bcm4360_test287_sched_ctx_read=1`, `bcm4360_test287c_extended=1`
- `bcm4360_test290a_chain=0`, `bcm4360_test290b_cc_write=1`

### Substrate prerequisites — REQUIRED

- Boot 0 since 16:30:03 BST. Uptime ~5 min at this writeup. Within "fresh" window.
- **Recommended**: fire NOW (<2 min from this writeup) for maximum substrate freshness — T292 fired at uptime ~13.5 min and produced partial data; T293 should aim earlier.
- ⚠️ NO COLD-CYCLE NEEDED if firing on current boot 0 (already cold-cycled by user post-T292).
- ⚠️ T293 may wedge per H_main. Another cold cycle will be required AFTER T293 fires if it wedges.

### Fire command (identical to T292)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test290a_chain=0 \
    bcm4360_test290b_cc_write=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.293.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.293.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.293.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.293.journalctl.txt`.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same brcmfmac.ko binary as T292
2. ✓ Hypothesis stated above
3. (user) PCIe state check: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
4. ✓ Plan committed and pushed BEFORE fire (this file)
5. ✓ FS sync after push

### Risk and recovery

- T293 fire risk profile: identical to T292.
- If watchdog fails to auto-recover (n=3/3 such events for T288c+T290+T292), user SMC reset will be needed.
- Anchor lines are pr_emerg priority — best-effort eager flush.

### Side-observation noted (not blocking T293)

T292 analysis surfaced: `BCM4360_T284_READ_MBM` (line 895) and `brcmf_pcie_intr_enable` (line 2546) both call bare `brcmf_pcie_read_reg32`/`write_reg32(0x4C)` WITHOUT `select_core(PCIE2)` first. If BAR0_WINDOW happens to be at chipcommon (e.g. after a T290B restore-back-to-saved), those reads/writes target chipcommon+0x4C, not PCIE2+0x4C. T292's "MBM=0x318" reads on lines 1411 + 1425 may have been reading chipcommon+0x4C all along. This is a confound for KEY_FINDINGS row 125's "MBM silently drops" claim — needs separate review (T295+ design). NOT blocking T293's plain re-fire.

---

## POST-TEST.293 (2026-04-26 20:41:58 BST fire, boot -1 — **SUBSTANTIVE FIRE — deepest T290B coverage to date. 4 T290B firings: pre-set_active CLEAN x2 + post-set_active CLEAN x1 + post-T276-poll WEDGE at anchor-3→anchor-4 with anomalous `orig=0xffffffff` at anchor-3. Watchdog did NOT auto-recover; user SMC reset (n=4/4 such events for T288c+T290+T292+T293).**)

### Timeline (from `phase5/logs/test.293.journalctl.txt`, boot -1 — 16:30:03→20:42:00)

- `16:30:03` boot -1 start (recovery from T292 cold-cycle)
- [~4 hours of idle uptime — fire NOT in PRE-TEST.293's recommended ≤2 min freshness window; far past the 20–25 min general window]
- `20:41:58` insmod entry → SBR → chip_attach → core enum → buscore_reset → ARM CR4 halt → fw download (110558 words, all OK) → ASPM/LnkCtl/setup callback → setup-entry → cold-init → BusMaster on → FORCEHT
- `20:41:58` (line 1393–1395) **test.276 PRE-WRITE shared_info written + readback PASS** (matches T287c/T288b/T292 baseline)
- `20:41:58` (line 1396) test.284 pre-write MBM=0x00000318 (matches baseline)
- `20:41:58` (line 1397–1398) test.287/T287c pre-write sched=0 (uninitialized expected)
- `20:41:58` (line 1399–1407) **TEST.290B FIRING #1 (pre-write, pre-set_active) — ALL 8 ANCHORS CLEAN**:
  - anchor-1: saved BAR0_WINDOW=0x18000000
  - anchor-3: orig=0x00000000
  - anchor-5: readback=0xdeadbeef ← write LANDED
  - anchor-7: restore_check=0x00000000 ← restore LANDED
  - summary: `CC.BCAST_DATA orig=0x00000000 wrote=0xDEADBEEF readback=0xdeadbeef restored=0x00000000 (saved_win=0x18000000)`
- `20:41:58` (line 1408–1410) test.284 brcmf_pcie_intr_enable returned → MBM=0x00000318 (silent-drop baseline)
- `20:41:58` (line 1411–1412) T287/T287c post-write sched=0 (still uninitialized)
- `20:41:58` (line 1413–1421) **TEST.290B FIRING #2 (post-write, pre-set_active) — ALL 8 ANCHORS CLEAN, identical pattern to firing #1**:
  - saved_win=0x18000000, orig=0x00000000, readback=0xdeadbeef, restored=0x00000000
  - **REPLICATION ACHIEVED for pre-set_active T290B firing.** T292's firing-#2 wedge at anchor-1 did NOT recur.
- `20:41:58` (line 1422–1424) test.238 brcmf_chip_set_active called → returned TRUE → CMD=0x0006 (BusMaster preserved)
- `20:41:58` (line 1425–1427) test.284 post-set_active MBM=0 (matches T284 baseline — set_active clears 0x318→0); T287/T287c post-set_active sched=0 still
- `20:41:58` (line 1428–1436) **TEST.290B FIRING #3 (post-set_active) — ALL 8 ANCHORS CLEAN**:
  - anchor-1: **saved BAR0_WINDOW=0x18102000** (ARM-CR4 wrapper — note class-table is now populated post-EROM walk)
  - anchor-3: orig=0x00000000
  - anchor-5: readback=0xdeadbeef ← write LANDED
  - anchor-7: restore_check=0x00000000 ← restore LANDED
  - summary: `CC.BCAST_DATA orig=0x00000000 wrote=0xDEADBEEF readback=0xdeadbeef restored=0x00000000 (saved_win=0x18102000)`
  - **NOVEL DATA POINT — first time T290B has run cleanly at post-set_active. Refutes a strict reading of POST-TEST.290's H1 ("T290B's chipcommon RMW at post-set_active wedges").**
- `20:41:58` (line 1437–1440) test.276 entering 2s poll → t+0ms si[+0x010]=0; t+10ms si[+0x010]=0x0009af88 (Phase 4B fw response reproduced — KEY_FINDINGS row 40); poll-end same
- `20:42:00` (line 1441) test.284 post-T276-poll MBM=0
- `20:42:00` (line 1442–1443) **test.287/T287c post-T276-poll sched_ctx FULLY POPULATED** matching KEY_FINDINGS row 132 EXACTLY:
  - `+0x10=0x00000011 +0x18=0x58680001 +0x88=0x18001000 +0x8c=0x18000000`
  - `+0x254=0x18101000 +0x258=0x18100000 +0x25c=0x18101000 +0x260=0x18102000 +0x264=0x18103000 +0x268=0x18104000 +0x26c=0x00000000 +0x270=0x00000000`
  - **Class-table replication — independent reproduction of KEY_FINDINGS row 132's class-dispatch finding.**
- `20:42:00` (line 1444–1447) **TEST.290B FIRING #4 (post-T276-poll) — WEDGED at anchor-3→anchor-4** (during write of 0xDEADBEEF):
  - anchor-1: saved BAR0_WINDOW=0x18102000 (ARM-CR4 wrapper — same as firing #3)
  - anchor-2: selected CHIPCOMMON; about to read 0x54
  - anchor-3: **orig=0xffffffff** ← ANOMALOUS — prior firings read 0x00000000
  - [no anchor-4; backplane wedged silently during write]
- `20:42:00` boot -1 ended (silent backplane hang — no AER under `pci=noaer`, no NMI/Oops/Call Trace)
- `21:08:58` boot 0 (recovery — only after user SMC reset; watchdog did NOT auto-recover, n=4/4 such wedges since T288c)

### Critical primary-source findings

**Finding 1 (LOAD-BEARING — replication): Pre-set_active T290B chipcommon BCAST_DATA RMW lands cleanly on consecutive firings.** T293 fired 2 RMWs back-to-back (firing #1 + firing #2) — both clean; orig=0 → wrote 0xDEADBEEF → readback=0xdeadbeef → restored=0 → restore_check=0. This is **n=2** for "host-side chipcommon writes land at pre-set_active". Combined with T292's firing #1 → **n=3 cumulative** clean pre-set_active chipcommon writes. KEY_FINDINGS row 159 should be promoted to a stronger LIVE/CONFIRMED-narrow status.

**Finding 2 (LOAD-BEARING — refutes strict reading of T290's H1): Post-set_active T290B fired cleanly.** Firing #3 (saved_win=0x18102000 = ARM-CR4 wrapper at this timing) executed all 8 anchors with the same clean RMW result. **The wedge in T290 is not "any post-set_active chipcommon write wedges"**; it must be more specific. Per advisor reconcile: T290's wedge timing maps to the post-T276-poll slot in T293's lens, not to the post-set_active slot. Reframe as "host chipcommon writes during fw scheduler dispatch wedge" rather than "post-set_active wedge".

**Finding 3 (LOAD-BEARING — new wedge mechanism): Post-T276-poll T290B wedges with anomalous `orig=0xffffffff` read at anchor-3.** All prior firings read orig=0x00000000. After the 2s poll (during which fw scheduler-ctx populated per KEY_FINDINGS row 132), select_core(CHIPCOMMON) was called, then read 0x54 returned 0xffffffff (canonical "PCI read failed" pattern under `pci=noaer`), then the write of 0xDEADBEEF wedged. Three live hypotheses (advisor):
- **(a) `select_core(CHIPCOMMON)` silently failed at firing #4** — the config_dword write didn't take, BAR0_WINDOW stayed at 0x18102000 (ARM-CR4 wrapper); read at anchor-2→3 actually hit `0x18102000+0x54` (ARM-CR4 wrapper offset) which returned 0xffffffff because that wrapper-page word is unmapped or read-as-0xff; the subsequent write went to ARM-CR4 wrapper while ARM was running → wedge.
- **(b) Chipcommon BCAST_DATA genuinely went 0 → 0xffffffff during the 2s poll** (fw wrote it during init).
- **(c) Chipcommon access path itself is degraded after fw scheduler dispatch** — reads return all-1s, writes hang; chipcommon as a backplane core is structurally compromised after fw becomes active.

These have very different next-step implications. (a) means the "post-T276-poll chipcommon writes wedge" headline is wrong — it's "select_core silently fails after T276 poll, write went elsewhere". Need a discriminator probe (T294).

**Finding 4 (independent replication): KEY_FINDINGS row 132 class-table fully reproduced.** sched_ctx +0x254..+0x268 read at post-T276-poll stage matches T287c findings BIT-EXACT. Confirms the runtime layout claim across two independent fires.

**Finding 5 (negative — T292 wedge not replicated): T292's firing-#2 wedge at anchor-1→anchor-2 did NOT recur in T293.** T293 firing #2 (immediately following firing #1, identical conditions) was clean. Per advisor: framed as "did not reproduce", not "ruled out" — n=1 negative is weak evidence. Substrate-noise interpretation (T292 H_A) is now favoured over intr_enable-fragility (T292 H_B) and config-space-write-fragility (T292 H_C), but neither H_B nor H_C is excluded.

### Discriminator outcome (per PRE-TEST.293 table)

The closest match in the discriminator table:
> **GREEN — full replication + extension**: Both pre-set_active firings clean + post-set_active T290B clean + ladder reaches t+90s → Promote KEY_FINDINGS row to CONFIRMED-narrow after T294 (n=3); pivot to write-side wake gate experiments.

**PARTIAL GREEN**: All firings except #4 clean. Firing #4 wedge is not in the table — it's a NEW data point. But the pre-set_active replication AND the post-set_active clean AND the class-table replication all hit the GREEN row's preconditions. Promotion-eligible after T294 once orig=0xffffffff is explained.

### KEY_FINDINGS impact

- **Row 159 (chipcommon-writes-land at pre-set_active)** — n=3 cumulative now. Promote LIVE → CONFIRMED-narrow at pre-set_active timing. Add `+ post-set_active n=1 clean` as new sub-claim. Add `post-T276-poll wedge at anchor-3→anchor-4 with orig=0xffffffff` as new sub-claim with the (a)/(b)/(c) hypotheses noted.
- **Row 132 (sched_ctx class-table)** — independently replicated by T293 line 1442–1443. Already CONFIRMED; T293 strengthens.
- **Row 85 (substrate flakiness)** — T292's firing-#2 wedge looking more substrate-shaped after T293's clean replication. No row update needed yet; the row is already CONFIRMED.
- **POST-TEST.290 H1 ("post-set_active T290B is the wedger")** — falsified at strict reading. Reframed as "host chipcommon writes during fw scheduler dispatch" — maps T290's wedge to firing-#4-equivalent timing. Note in row 159.

### What was NOT settled

- ❌ Whether `orig=0xffffffff` at firing #4 reflects (a) select_core silent-fail, (b) genuine chipcommon BCAST_DATA shift during 2s poll, or (c) chipcommon access path degradation. **T294 must discriminate.**
- ❌ Whether the wedge mechanism reproduces (n=1).
- ❌ Whether intr_enable's silent-drop write is implicated in any wedge (T292 H_B still untested).

### Crash markers — what's NOT present

- ❌ No AER UR/CE markers (`pci=noaer` blinds us)
- ❌ No NMI / hardlockup / softlockup / panic / Oops / BUG / Call Trace
- ❌ No PCIe link state events
Pure silent backplane hang — consistent with all prior wedges under `pci=noaer`.

### Substrate (current — recovery boot)

- Boot 0 since 21:08:58 BST, uptime ~1 min at this writeup
- PCIe state: `Status` clean (`<MAbort-`) — cold cycle was effective
- 0 brcmfmac modules loaded
- 0 fires this boot
- Per CLAUDE.md substrate rule: T294 REQUIRES fresh cold cycle (already done by user). Currently within 20–25 min fresh window.

### Build verification

- `brcmfmac.ko` was the unchanged T292/T293 binary. T293 fire executed all 8 anchors of T290B in 4 distinct slots — macro mechanism well-validated.
- For T294: NEEDS REBUILD to add an explicit BAR0_WINDOW readback line after select_core inside T290B macro (and a dedicated read-only T290B variant for surgical post-T276-poll discrimination).

### Next-fire candidates (ordered by information yield)

- **(α) T294 = read-only chipcommon probe at post-T276-poll with explicit BAR0_WINDOW readback after select_core** — discriminator for (a)/(b)/(c). Single-fire, surgical. ENABLES promotion of row 159 once orig=0xffffffff is explained.
- **(β) Re-fire T293 unchanged** — builds n further on each slot; cheap if (α) is delayed by build time.
- **(γ) Pivot to TCM-scribble at `[node+0xc]`** per KEY_FINDINGS row 148 — defers chipcommon path. Lower yield than (α) right now.

Advisor consult before choosing.

---

## POST-TEST.292 (2026-04-26 16:26 BST fire, boot -1 — **SUBSTANTIVE FIRE. First pre-set_active T290B firing landed a CLEAN chipcommon BCAST_DATA RMW: orig=0, wrote=0xDEADBEEF, readback=0xdeadbeef, restored=0. SECOND pre-set_active T290B firing wedged at anchor-1→anchor-2 inside brcmf_pcie_select_core(CHIPCOMMON). Post-set_active T290B never ran (wedge upstream). Watchdog did NOT auto-recover; user SMC reset.**)

### Timeline (from `phase5/logs/test.292.journalctl.txt`, boot -1 — 16:12:40→16:26:12)

- `16:12:40` boot start (post-T291 cold-cycle clean substrate)
- `~16:26:12` insmod entry (uptime ~13.5 min — past PRE-TEST.292's recommended ≤2 min freshness window; within KEY_FINDINGS row 84's 20–25 min window)
- `16:26:12` test.218 host-side core enum → buscore_reset → ARM CR4 halt → get_raminfo → PMU/RAM probes → ASPM/LnkCtl/setup callback → setup-entry → fw download (ramwrite, all OK) → INTERNAL_MEM core not-found (expected) → pre-set-active probes: ARM CR4 IOCTL/IOSTATUS/RESET_CTL/CPUHALT=YES; D11 IN_RESET=YES; CR4 clk_ctl_st=0x07030040; pre-BM mailboxint guard=0; pci_set_master → BM=ON → FORCEHT write applied
- `16:26:12` (line 1407-1413) **PRE-WRITE (pre-set_active) probe drain BEGAN**:
  - test.277 PRE-WRITE struct@0x9af88 = uninitialized garbage (expected — fw not yet running)
  - test.276 shared_info written + readback PASS (magic_start, dma_lo/hi, buf_size, fw_init_done=0, magic_end — all match expected)
  - test.284 pre-write MBM=0x00000318 MBI=0x00000000 (matches T284 baseline)
  - test.287/T287c pre-write sched=0 (uninitialized expected)
- `16:26:12` (line 1414-1422) **TEST.290B FIRST FIRING — CLEAN COMPLETION** (all 8 anchors + summary):
  - anchor-0: entry; about to save BAR0_WINDOW
  - anchor-1: saved BAR0_WINDOW=0x18000000; about to select_core(CHIPCOMMON)
  - anchor-2: selected CHIPCOMMON; about to read 0x54
  - anchor-3: orig=0x00000000; about to write 0xDEADBEEF
  - anchor-4: wrote 0xDEADBEEF; about to readback
  - anchor-5: **readback=0xdeadbeef** ← write LANDED on chipcommon BCAST_DATA
  - anchor-6: restored orig; about to verify
  - anchor-7: **restore_check=0x00000000** ← restore LANDED
  - summary: `CC.BCAST_DATA orig=0x00000000 wrote=0xDEADBEEF readback=0xdeadbeef restored=0x00000000 (saved_win=0x18000000)`
- `16:26:12` (line 1423-1425) test.284 calling brcmf_pcie_intr_enable → returned → post-write MBM=0x00000318 (still 0x318 — matches T284 silent-drop baseline at PCIE2+0x4C)
- `16:26:12` (line 1426-1427) test.287/T287c post-write sched=0 (still uninitialized)
- `16:26:12` (line 1428-1429) **TEST.290B SECOND FIRING — WEDGED at anchor-1→anchor-2**:
  - anchor-0: entry
  - anchor-1: saved BAR0_WINDOW=0x18000000; about to select_core(CHIPCOMMON)
  - [NO anchor-2; backplane wedged silently]
- boot -1 ended same second
- `~16:30:03` boot 0 (recovery — after user SMC reset; watchdog did NOT auto-recover, n=3/3 such events for T288c+T290+T292)

### Critical primary-source findings

**Finding 1 (LOAD-BEARING NEW): Host-side chipcommon BAR0+0x54 write at pre-set_active (ARM halted) DOES land.** First T290B firing wrote 0xDEADBEEF and read back 0xDEADBEEF cleanly, then restored to 0 with verified readback. This is a structurally different behaviour from KEY_FINDINGS row 125 (PCIE2 MAILBOXMASK at BAR0+0x4C silently drops). **Chipcommon MMIO writes are NOT universally write-locked on this chip.** First positive evidence that host-side writes to chip MMIO can land at all.

**Finding 2 (anomalous, n=1): Second T290B firing in immediate succession wedged at brcmf_pcie_select_core(CHIPCOMMON).** Same code path, second invocation. saved_win was 0x18000000 (i.e. BAR0_WINDOW already pointed at chipcommon — would-be no-op write). Wedge happens inside select_core which does pci_write_config_dword(BAR0_WINDOW, core->base) followed by pci_read_config_dword + conditional re-write (pcie.c:1985–1996). The wedge is at config-space access, NOT at the chipcommon MMIO read/write itself.

**Finding 3 (gating): Post-set_active T290B never ran.** Wedge happened in pre-set_active phase (line 1429 / log truncation). The post-set_active T290B firing scheduled at pcie.c:4372 was never reached. This means H_main from PRE-TEST.292 ("post-set_active T290B wedges; pre-set_active works") is NOT directly tested by this fire.

**Finding 4 (uptime context):** Fire happened at uptime ~13.5 min, past the recommended ≤2 min "fresh" window but within the 20–25 min general window. Not a freshness-violation, but not an optimal-fresh fire either.

### Discriminator outcome (per PRE-TEST.292 table)

| Row hit | Reading |
|---|---|
| Row 3: "Pre-set_active T290B wedges at some `anchor-N` (one of 0..7)" → H_alt1 | **PARTIAL**: it IS pre-set_active, but it's the SECOND firing of the same probe; the FIRST firing succeeded. H_alt1 ("chipcommon writes globally bad on this chip") is contradicted by the first firing's success. |

The discriminator table did not anticipate "pre-set_active T290B works on first firing, wedges on identical second firing in same insmod". This is novel.

### Hypotheses (post-T292)

**H_A (LEADING — substrate noise of the same flavour as KEY_FINDINGS row 85, but landing at a non-random point):** The first firing was substrate-cooperative and produced load-bearing data; the second firing hit substrate noise that happened to manifest at the next config_dword write. Supports row 85 — single-fire trials don't replicate. Implies T293 should re-fire to gather n>1 on chipcommon RMW (and try to land it twice cleanly).

**H_B (state-corruption from intermediate intr_enable):** Between firings 1 and 2, brcmf_pcie_intr_enable wrote MAILBOXMASK = 0xFF0300 via select_core(PCIE2)+write_reg32(0x4C). KEY_FINDINGS row 125 says this write silently drops. But the act of "select PCIE2 → attempt write → reselect chipcommon (in helper)" may leave the AI backplane in a transient state that cannot tolerate the next config_dword. Plausible mechanism but no direct evidence. Implies T293 should disable intr_enable between firings to test.

**H_C (cumulative config-space-write fragility):** PCI config-space writes themselves degrade after some number of accesses (n=4 BAR0_WINDOW writes happened during the first firing's run, plus 1 in intr_enable's select_core, plus 1 in the second firing's anchor-2 = 6 cumulative). Less plausible — config-space access is well-trodden in many probes.

**H_D (fw-state-dependent — not yet ruled out):** Even though ARM is halted, fw_data has been ramwritten to TCM. Some chipcommon side-channel may "see" fw payload in TCM and react. Hard to test.

### KEY_FINDINGS impact

- **Candidate new row (CONFIRMED, n=1 — must be replicated to promote): "Host-side chipcommon BAR0+0x54 (BCAST_DATA) RMW at pre-set_active timing DOES land cleanly. Wrote 0xDEADBEEF, read back 0xDEADBEEF, restored 0, verified."** First positive primary-source evidence that chipcommon MMIO writes can land — sharply distinguished from PCIE2 MAILBOXMASK at BAR0+0x4C (KEY_FINDINGS row 125, write-locked at all timings). Direction: **chipcommon-wrapper offsets and chipcommon-register offsets are different from PCIE2 in writeability**. Promotes "find wake gate then poke chipcommon-side" as still-viable. Defer KEY_FINDINGS update until n≥3.
- **Row 85 (substrate flakiness)**: REAFFIRMED for the third consecutive fire. T288c, T291, T292-second-firing all wedged at semi-random points. T292 still scored partial information (the first firing).
- **Row 88 (POST-TEST.290 H1 candidate "T290B's chipcommon RMW at post-set_active wedges"):** NOT directly addressable by T292 — post-set_active T290B never ran. Still LIVE n=1.

### What was NOT settled

- ❌ Whether post-set_active T290B wedges (PRE-TEST.292's H_main) — wedge happened pre-set_active before that probe could run.
- ❌ Whether the second-firing wedge is reproducible (n=1).
- ❌ Whether intr_enable's select_core(PCIE2)+silent-drop leaves chip in a fragile state.

### Crash markers — what's NOT present

- ❌ No AER UR/CE markers (`pci=noaer`)
- ❌ No NMI / hardlockup / softlockup / panic / Oops / BUG / Call Trace
- ❌ No PCIe link state events
Pure silent backplane hang — consistent with all prior wedges under `pci=noaer`.

### Substrate (current — recovery boot)

- Boot 0 since 16:30:03 BST, uptime ~1 min at this writeup
- PCIe state: Status clean (`<MAbort-`)
- 0 brcmfmac modules loaded
- 0 fires this boot

### Next-fire candidates (ordered by information yield)

- **(A) Re-fire T292 unchanged** — tests whether T290B-first-firing-clean reproduces; tests whether second-firing-wedge reproduces. n=2 builds quickly.
- **(B) T293 = T292 with intr_enable removed between firings** — tests H_B (intr_enable's silent-drop fragility hypothesis). If second firing now succeeds, intr_enable is implicated.
- **(C) Pivot to TCM-scribble at `[node+0xc]`** per KEY_FINDINGS row 148 — defers chipcommon path; tests software wake-gate write via TCM (different mechanism, different surface).

Advisor consult before choosing.

---

## POST-TEST.288c (2026-04-26 09:57 BST fire, boot -1 — **NULL FIRE. Wedge at `test.225: wrote 1024 words` — chunk-1 of fw download (~108 chunks total). ZERO anchor lines. ZERO T276/T284/T287/T288a markers. Macro never reached. Cannot test H1 (which sub-step in wrap-read macro wedges) because wrap-read macro never fires. The discriminator table's "implausible — T288b proved upstream is clean" row materialized; T288b's clean upstream is now provably an n=1 sample, not a property of the path.**)

### Timeline (from `phase5/logs/test.288c.journalctl.txt`, boot -1)

- `09:52:17` boot start (fresh after user cold cycle + SMC reset)
- `09:57:09` insmod entry (`test.188 module_init entry`) — 5 min uptime, well within widest-clean-window
- `09:57:09..16` chip_attach → core enumeration (test.218 6 cores) → buscore_reset → ARM CR4 halt → get_raminfo → PMU WARs → ASPM/LnkCtl/settings/bus alloc → brcmf_alloc → fw_get_firmwares (NORMAL — same trajectory as T288b)
- `09:57:16..17` `test.162 brcmf_pcie_setup CALLBACK INVOKED ret=0` → setup-entry → pre-attach → test.128 brcmf_pcie_attach ENTRY/RETURN → CLK_CONTROL/SBMBX/PMCR_REFUP (test.194)
- `09:57:18..20` post-attach → fw-ptr-extract → get_raminfo → adjust_ramsize → pre-download
- `09:57:21..22` test.218 pre-download CR4 clk_ctl_st=`0x07030040` → D11 IN_RESET=YES (clock-control verified)
- `09:57:22..23` `test.163 before brcmf_pcie_download_fw_nvram (442KB BAR2 write)` → test.142 enter_download_state → debug rambase=0x0 ramsize=0xa0000
- `09:57:24` `test.138 pre-BAR2-ioread32 = 0x02dd4384 (real value — BAR2 accessible)`
- `09:57:25` test.233 PRE-READ TCM[0x90000]=`0xa42709e1` TCM[0x90004]=`0xb0dd4512` (uninitialized noise — not preserved markers, normal post-cold-cycle)
- `09:57:25` test.218 pre-halt CR4 clk_ctl_st unchanged → D11 IN_RESET=YES
- `09:57:25` `test.188 re-halting ARM CR4 via brcmf_chip_set_passive` → post-halt CPUHALT=YES (chip ready for ramwrite)
- `09:57:25` `test.188 starting chunked fw write, total_words=110558 (442233 bytes)` (~108 chunks @ 4096 bytes each expected)
- `09:57:26` **LAST LINE: `test.225: wrote 1024 words (4096 bytes) last=0xb19c6018 readback=0xb19c6018 OK`** (chunk 1 of ~108)
- [no further log output; machine wedged silently — boot ended same second]
- `09:57:26` boot -1 ended (per journalctl --list-boots)
- `10:02:22` boot 0 (recovery — but only after user-initiated SMC reset; watchdog did not auto-recover here)

### Discriminator outcome (per PRE-TEST.288c table)

The "Last anchor seen" column has NO match — zero anchors fired. The fallback row "(none — wedge before macro) → upstream of T288a — implausible (T288b proved upstream is clean with this binary)" is the row that fired. **The "implausible" classification was based on n=1; primary source has now contradicted it.**

Three crystallised facts that SUPERSEDE / WEAKEN POST-TEST.288b's inferences:

1. **The path upstream of the T288a macro is NOT reliably clean even on cold-cycled substrate.** T288c shows wedge at fw-download chunk-1 — the same chunked-write path T288b traversed cleanly through ~108 chunks. Same binary, same flag-0/flag-1 difference (which only affects code AFTER chunk write completes), same substrate-pre-fire markers. **Substrate flakiness wedges at random points along the same code path.**

2. **The "T288a binary innocent" claim from POST-TEST.288b rested on n=1 success.** With 4 fires (T288a, T288a', T288b, T288c) all using the same binary and 3 of 4 wedging at three different upstream points (after T276; at OTP-bypass; at fw chunk-1), the success rate is 25% under "cold-cycle substrate" conditions. n=1 is not sufficient evidence to declare the macro the cause of T288a's wedge.

3. **The "T288a wrapper-read wedges backplane" (H1) confirmation-by-exclusion is FALSIFIED at the inference level.** The exclusion required a clean baseline + a wedging variant; the baseline has been shown not to be reliable. H1 may still be true, but T288b alone cannot prove it. Need either (a) multiple flag=0 baselines to characterize substrate noise floor, or (b) a probe earlier in the path to fire before the fragile section.

### Crash characterisation (chunk-1 wedge)

- Final journal line at 09:57:26 (test.225 chunk-1 OK), boot ended same second → wedge essentially instant after chunk-1 logged
- ZERO crash markers in journal (no AER UR/CE — `pci=noaer`; no NMI; no Oops; no Call Trace) — silent backplane hang
- BAR2 ramwrite path ran chunk-1 successfully with valid readback (`0xb19c6018` matches) — chunk-1 ITSELF is not the trigger; the wedge happens between chunk-1 logged and chunk-2 starting
- This is structurally similar to T288a' (silent wedge before macro fires); progress point is different (T288a' at OTP-bypass test.160, T288c at chunk-1 test.225)
- Watchdog did NOT auto-recover this fire; user had to SMC-reset. New observation — prior wedges had auto-recovery (KEY_FINDINGS substrate row says "n>30 watchdog recoveries today"). This wedge style may be different.

### KEY_FINDINGS impact (load-bearing)

DOWNGRADE: KEY_FINDINGS row "T288a runtime wrapper-base BAR0 reads at PRE-set_active wedge BCM4360 backplane" from **CONFIRMED (by exclusion)** → **LIVE / UNDER-EVIDENCED**. Current evidence base is n=1 baseline (T288b) vs n=3 wedges with no anchor-discrimination. Substrate noise dominates. Rewrite will be done in this session.

ADD: New finding — substrate flakiness on cold-cycled BCM4360 produces wedges at random progress points along the same code path. T288 series under same binary: 1/4 fires reach t+90s. The "20–25 minute clean-window" claim in KEY_FINDINGS is too coarse — even within that window, wedges can hit at chip_attach, OTP-bypass, fw-download, post-T276, or only at the late-ladder.

### Substrate (current — recovery boot)

- Boot 0 since 10:02:22 BST, uptime ~3 min at this writeup
- 0 brcmfmac modules loaded
- 0 fires this boot
- ⚠️ Per CLAUDE.md substrate rule: any next hardware test REQUIRES a fresh cold cycle (shutdown ≥60 s + SMC reset). User just did one for T288c; would need another. **But the substrate-noise problem can't be solved with another cold cycle alone — design needs reconciliation first.**

### Build verification

- `brcmfmac.ko`: 15 085 568 B, mtime 2026-04-26 00:24, identical to T288b/T288c — anchors compiled in
- No rebuild needed for next fire IF design stays compatible

### Decision needed before next fire — advisor reconcile (2026-04-26)

**Two findings from advisor's reconcile call:**

1. **H1 is more falsified than my downgrade implied.** Within flag=1 fires alone:
   - T288a' (08:53 BST) wedged at OTP-bypass (test.160) — BEFORE the macro's earliest invocation site
   - T288c (09:57 BST) wedged at fw chunk-1 (test.225) — BEFORE the macro's earliest invocation site
   - T288a (00:11 BST) wedged after T276 markers — AFTER the macro fires
   2 of 3 flag=1 fires wedged at points where the flag's effect could not have been the cause. That's direct positive evidence the macro is NOT the wedger (it never ran in those 2 fires). Only T288a is consistent with macro-as-wedger, and one data point can't distinguish that from substrate. **H1 should be treated as LIKELY-FALSE, not just LIVE.**

2. **Sanity-check whether T288 wrap-read line is still highest-leverage** before spending the substrate budget. Three flag=0 baselines = 3 cold cycles + 3 crashes (T288c took user SMC reset, watchdog exception). KEY_FINDINGS has cheaper open questions:
   - **MSI-subscription wedge fix** (KEY_FINDINGS row 151, LIVE): "known fix via `pci=noaspm` or different MSI setup. Phase6/t269 §Candidates B/C — not tested." Would require fire but not necessarily a crash if approach works.
   - **`hndrte_add_isr` per-class unmask thunk** (row 118, LIVE): "Either the thunk writes to a different register, was not invoked, or its effect is gated on a condition we haven't satisfied." Pure static-analysis question — disasm only, ZERO fires needed. Could identify the actual register that controls fw's wake gate.
   - **Software wake gate** (row 148): "the mask in fn@0x1146C's dispatch is scheduler-side software flag mask `[node+0xc] & pending_events`, NOT the PCIE2 MAILBOXMASK." If we can identify which TCM offset `[node+0xc]` lands at, a TCM scribble might wake fw — no register-write contortions needed.

**Decision (next session):**
- (a) Spend 3 fires on N=3 flag=0 baselines with stop rule: 3/3 reach t+90s → re-fire flag=1 with meaningful S/N; 2/3 or worse → abandon T288 wrap-read line entirely
- (b) Pivot to static-analysis paths (per-class unmask thunk disasm + scheduler software-mask offset identification) — ZERO fires, may identify the actual wake gate
- (c) Try MSI-subscription fix candidates (different fragility surface, but at least new information)

Advisor recommends (a) only after sanity-checking that (b) isn't cheaper. Strong leaning: **start with (b)** — disasm the per-class unmask thunk before spending substrate budget on a hypothesis that timing already partially falsifies.

**Status:** No fire pending. Next session should read KEY_FINDINGS row "T288a wrapper-read" (LIKELY-FALSE) and decide design before any hardware work.

---

## POST-TEST.288b (2026-04-26 09:19 BST fire, boot -1 — **CLEAN BASELINE THROUGH T+90s. Discriminator outcome: substrate was the only confound for T288a/T288a' wedges. T288a binary innocent. H1 from POST-TEST.288a (T288a runtime wrapper-base BAR0 reads at PRE-set_active wedge the backplane) survives by exclusion. Wedge at ~t+95s = the known T270-BASELINE late-ladder fault, orthogonal to T288 work.**)

### Timeline (from `phase5/logs/test.288b.journalctl.txt`, boot -1)

- `09:13:48` boot start
- `09:19:30..31` insmod entry → SBR → chip_attach → core enumeration (test.218 6 cores) → buscore_reset → ARM CR4 halt → get_raminfo → PMU WARs → ASPM/LnkCtl/settings/bus alloc → brcmf_alloc → fw_get_firmwares → setup callback INVOKED → setup-entry → pre-attach → cold-init → ramwrite → BusMaster on → FORCEHT
- `09:19:31` **`test.276: shared_info written at TCM[0x9d0a4]`** + readback PASS (magic/dma/size/init_done/end all match)
- `09:19:31` `test.284: pre-write (pre-set_active) MAILBOXMASK=0x00000318 MAILBOXINT=0x00000000` (matches T284 baseline)
- `09:19:31` `test.287: pre-write (pre-set_active) sched[...]=0` (uninitialized — fw hasn't been released yet — matches T287b/c baseline)
- `09:19:31` `test.287c: pre-write (pre-set_active) sched[+0x25c..+0x270]=0` (uninitialized — matches baseline)
- `09:19:31` ZERO `anchor-N` lines (T288a flag=0 — gate held — confirms binary cleanliness)
- `09:19:31` `test.238: calling brcmf_chip_set_active resetintr=0xb80ef000`
- `09:19:31` `test.276: t+0ms si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000` (T276 protocol anchor — exact match of T276/T277/T278/T287c)
- `09:19:31` `test.276: poll-end si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000` (matches T276 baseline)
- `09:19:31` `test.277: POST-POLL struct@0x0009af88 buf_addr=0x00096f78 buf_size=0x00004000 write_idx=0x0000024b read_addr=0x00096f78` (exact T277 match — write_idx=587 bytes)
- `09:19:31` test.278 POST-POLL full dump 587 B = exact T278 fw console (`Found chip type AI` … `wl_probe called`)
- `09:19:31..32` test.238 dwell ladder: t+100ms..t+30000ms — all stage hooks fired (T284 MBM=0, T287 sched_ctx settled to post-set_active values, T287c class-table at +0x25c..+0x268 = 0x18101000..0x18104000, T278 wr_idx=587 unchanged at every stage)
- `09:19:32` `t+45000ms`, `t+60000ms` dwells
- `09:19:39` **`t+90000ms dwell` + T278/T284/T287/T287c stage hooks fired**
- [no further log output; machine wedged silently]
- `09:19:44` boot -1 ended (per journalctl --list-boots)
- `09:24:50` boot 0 (current — recovery from watchdog reboot)

### Discriminator outcome (per PRE-TEST.288b table)

Row 1 of the discriminator table fired:
> Reaches t+90s with full T287c-style trace → Substrate was the only confound. T288a binary innocent. → Re-fire with `bcm4360_test288a_wrap_read=1` on a cold-cycled substrate.

Two facts crystallised:

1. **Substrate was the confound for T288a (00:11 BST) and T288a' (08:53 BST) wedges.** Same binary, T288a runtime gated off, with a properly cold-cycled substrate → reaches t+90s. Substrate degradation explains both prior wedges' progressively-earlier failures.
2. **T288a binary is INNOCENT.** Anchor strings are compiled in (verified via `strings ... | grep anchor-` = 8 hits) but the runtime gate held them silent. No anchor lines logged. The added macro definitions and module_param do not perturb the late-ladder trace.

By exclusion (only one untested variable remains — the runtime wrapper-base BAR0 reads themselves):

3. **H1 from POST-TEST.288a survives**: T288a's `BCM4360_T288A_READ_WRAPS` macro body — the actual BAR0 reads at chipcommon-WRAPPER (0x18100000) and PCIE2-WRAPPER (0x18103000) at PRE-set_active timing — wedges the backplane.

### Crash characterisation (post-90s wedge)

- Final journal line at 09:19:39, boot ended at 09:19:44 = ~5 s gap → wedge at ~09:19:44, well inside the **T270-BASELINE t+90..120s late-ladder window**
- ZERO crash markers in journal (no AER UR/CE — `pci=noaer`; no NMI; no Oops; no Call Trace) — silent backplane hang, fw-side
- Substrate at fire was 2 min uptime, post-cold-cycle; this is the same wedge T270-BASELINE/T276/T277/T278/T287c all hit
- This is the known `late-ladder substrate-bound fault` (KEY_FINDINGS row "T276 did not alter the late-ladder crash window") — orthogonal to T288 series of probes

### KEY_FINDINGS impact (load-bearing)

ADD: **CONFIRMED — T288a runtime wrapper-base BAR0 reads at PRE-set_active wedge BCM4360 backplane.** Mechanism inferred by exclusion (T288b baseline reached t+90s with same binary, gate off; T288a/T288a' wedged with gate on). Sub-step (which of the 8 anchor lines fires last) NOT YET identified — that's T288c's job.

The new fact removes a major candidate from the LIVE list: prior PRE-TEST.288a hypothesis "wrapper-page reads at PRE-set_active are novel and may stall the backplane" is upgraded from speculation to confirmed-by-exclusion.

### Substrate (current — recovery boot)

- Boot 0 since 09:24:50 BST, uptime ~5 min at this writeup
- PCIe state: `Status` clean (no MAbort/etc.); `DevSta: UnsupReq+ CorrErr+ AuxPwr+` — leftovers from the wedge that DON'T clear without SMC reset
- `LnkCtl: ASPM L0s L1 Enabled, CommClk+`; `LnkSta: Speed 2.5GT/s, Width x1` — link trained correctly
- 0 brcmfmac modules loaded
- 0 fires this boot
- ⚠️ Per CLAUDE.md substrate rule: T288c REQUIRES a fresh cold cycle (shutdown ≥60 s + SMC reset). Recovery boot is not a clean substrate.

### Build verification

- `brcmfmac.ko`: 15 085 568 B, mtime 2026-04-26 00:24 — anchors compiled in (verified `strings ... | grep -i 'anchor-' | head -10` returns 8 format strings, gated on `bcm4360_test288a_wrap_read`)
- T288c needs NO rebuild — flip flag from 0 to 1, identical fire command otherwise

---

## POST-TEST.288a' (2026-04-26 08:53 BST fire, boot -1 — **HARD WEDGE EARLIER than T288a. Cutoff at `test.160 OTP-bypass` — BEFORE the firmware-loaded setup callback fired. Zero `anchor-` lines, zero `setup-entry`, zero `test.162`. T288a' macro body had no opportunity to run; this fire is NOT evidence about H1 (wrapper read wedge) vs H2 (upstream-of-T288a setup-body wedge). Substrate confound is the leading explanation. Watchdog reboot at ~08:56 BST after ~17-min unflushed-printk gap.**)

### Timeline (from `phase5/logs/test.288a-prime.journalctl.txt`, boot -1)

- `08:53:21` insmod entry (`test.188 module_init entry`)
- `08:53:22..27` PROBE ENTRY → SBR → chip_attach → core enumeration (test.218 6 cores)
- `08:53:29..32` buscore_reset, ARM CR4 halt, get_raminfo, PMU WARs (test.193/224)
- `08:53:33..36` ASPM disable, root-port LnkCtl, settings/bus/msgbuf alloc
- `08:53:37..38` brcmf_alloc complete, drvdata set
- `08:53:39` **LAST LINE: `test.160: brcmf_alloc complete — wiphy allocated` then `OTP read bypassed — OTP not needed`**
- [no further log output; machine wedged silently]
- `08:53:53` (run.txt: INSMOD_RC=0 written — module_init's synchronous return chain completed)
- `~08:56` watchdog reboot to current boot 0 (uptime now 5 min)

### What was missing (vs T288a's already-broken fire)

T288a's last journal line was `test.156: after brcmf_core_init() err=0` at 00:12:10 — AFTER `test.162 CALLBACK INVOKED` and `setup-entry` markers fired. T288a' cut off ~5 markers EARLIER, before:
- `prepare_fw_request` / `brcmf_fw_get_firmwares` (async fw load kickoff)
- `Direct firmware load for clm_blob/txcap_blob failed -2` (normal noise)
- `test.162 brcmf_pcie_setup CALLBACK INVOKED ret=0`
- `setup-entry ARM CR4 IOCTL=0x21 ...`
- `test.156: after brcmf_core_init() err=0`

**Crucially: zero anchor-N lines.** The T288a_READ_WRAPS macro is invoked from inside `brcmf_pcie_download_fw_nvram`, which runs INSIDE the setup callback. If the setup callback never fired, the macro never had a chance to fire either. The crash is upstream of T288a's runtime path entirely.

### Diagnostic markers — what's NOT present

- ❌ No AER UR/CE markers
- ❌ No NMI / hardlockup / softlockup
- ❌ No Oops / BUG: / Call Trace
- ❌ No PCIe link state events
- ❌ No `setup-entry` / `pre-attach` / `test.162` callback
- ❌ No anchor-N lines from T288a's macro

### Build verification (rules out T288a-binary corruption hypothesis)

- `brcmfmac.ko` mtime 2026-04-26 00:24 (rebuilt with anchors) — 15.1 MB
- `pcie.c` mtime 2026-04-26 00:23 — sources newer than build target's predecessor; module is fresh
- `strings brcmfmac.ko | grep 'anchor-'` returns all 8 anchor format strings — code IS compiled in
- INSMOD_RC=0 written to `test.288a-prime.run.txt` (module_init's synchronous return chain completed)

### Why "substrate confound" leads

1. T287c (immediate prior fire, 2026-04-25 23:39 BST, boot -2 of THAT timeline = pre-SMC-reset) ran cleanly to t+90s with the EXACT same setup() body and prior infrastructure
2. T288a (2026-04-26 00:11 BST, post-SMC-reset substrate, ~26 min uptime) wedged AFTER setup-entry but BEFORE pre-attach
3. T288a' (2026-04-26 08:53 BST, post-watchdog-reboot from T288a wedge, then user reboot + SMC reset, ~2 min uptime per Current state at fire time) wedged BEFORE setup-entry
4. Each successive fire wedges progressively earlier — consistent with substrate degradation, not with a deterministic code-path issue
5. Previous CLAUDE.md substrate rule: cold cycle (shutdown + ≥60 s + SMC reset) is required for clean window; user did "reboot + SMC reset" (no shutdown gap). May not have been fully effective.

### Hypotheses (ordered by probability)

**H1' (leading): Substrate degraded across the fire chain T287c → T288a → T288a'.** Each fire wedges earlier than the last. T288a's wedge poisoned the chip; the user's reboot+SMC-reset cleared the host kernel state but not enough chip-side state to recover the clean window.

**H2' (alternative): A code-path between OTP-bypass and prepare_fw_request silently regressed.** Implausible — diff between T287c's working build and T288a/T288a' is purely additive (new module_param + new macro definition + new macro call sites inside `brcmf_pcie_download_fw_nvram`). None of those code paths run before OTP-bypass. The new pr_emerg anchor lines added in T288a' would also not run before OTP-bypass.

**H3' (long shot): Linker layout regression.** The added macro/anchor strings shifted code addresses. Some prior fragile timing window now lands on a worse cycle. Quantifiable via `size brcmfmac.ko` comparison vs T287c-clean build.

### Decision: revised plan

Per advisor: T288a' is not evidence about H1/H2 (wrapper-read wedge vs setup-body-upstream wedge). The cheapest discriminator is to fire BASELINE with `bcm4360_test288a_wrap_read=0` on a cold-cycled substrate. Same binary, T288a runtime code disabled. If baseline reaches t+90s with normal T287c-style trace → substrate is the only variable, T288a binary is innocent, then re-fire with =1. If baseline still wedges early → T288a binary itself or substrate-only confound; investigate `size brcmfmac.ko` delta vs T287c-clean.

### Substrate (current — recovery boot)

- Boot 0 (current) post-watchdog-reboot from T288a' wedge
- Uptime ~5 min at journal capture
- PCIe state: Status flag clean, no MAbort/CommClk drift visible
- 0 fires this boot
- Per CLAUDE.md: cold cycle (shutdown + ≥60 s + SMC reset) is REQUIRED before next fire — recovery boot is not a clean substrate

### KEY_FINDINGS impact

None. Nothing load-bearing came out of T288a'. The fire produced no fw-state data, no register data, and no discrimination between H1/H2. Do NOT update KEY_FINDINGS based on this fire.

---

## POST-TEST.288a (2026-04-26 00:11 BST fire, boot -1 — **HARD WEDGE BEFORE set_active. Setup callback invoked, no markers from its body (T276/T284/T287/T288a all silent). Watchdog reboot, no crash markers. Hypothesis: BAR0 reads of chipcommon-WRAPPER (0x18100000) at PRE-set_active wedge the backplane.**)

### Timeline (from `phase5/logs/test.288a.journalctl.txt`, boot -1)

- `00:11:51` insmod entry (`test.188 module_init entry`)
- `00:11:52` PROBE ENTRY → SBR → chip_attach → core enumeration (test.218 6 cores)
- `00:11:53` buscore_reset, ARM CR4 halt, get_raminfo, PMU WARs (test.193/224)
- `00:11:53..58` ASPM disable, root-port LnkCtl, settings/bus/msgbuf alloc
- `00:12:00` brcmf_alloc, prepare_fw_request, brcmf_fw_get_firmwares
- `00:12:01` Direct firmware load for clm_blob/txcap_blob failed -2 (normal)
- `00:12:01` **`test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0`**
- `00:12:01` `setup-entry ARM CR4 IOCTL=0x21 IOSTATUS=0 RESET_CTL=0 CPUHALT=YES`
- `00:12:01` pci_register_driver returned ret=0 (sync — fw was preloaded)
- `00:12:04` after brcmf_pcie_register() err=0
- `00:12:10` post-PCI sync (skipping USB)
- `00:12:10` **LAST LINE: `test.156: after brcmf_core_init() err=0`**
- [no further log output; machine wedged silently]
- `00:12:53` watchdog reboot to current boot 0 (uptime now 5 min)

### What was missing (vs successful T287c run)

T287c's first marker after `setup-entry` was `test.128: before brcmf_pcie_attach` (at +1 s post-callback). T288a never logged this. setup() body went silent immediately after the `msleep(300)` at line 7047 — i.e. somewhere between `setup-entry` and `pre-attach` log markers. Setup callback DID enter (line 7045) but NEVER reached `brcmf_pcie_probe_armcr4_state(devinfo, "pre-attach")` at line 7053.

**No T276 shared_info written. No T284 MBM read. No T287 sched_ctx read. No T288a wrap read. No set_active.** The wedge is upstream of all probes.

### Diagnostic markers — what's NOT present

- ❌ No AER UR/CE markers
- ❌ No NMI / hardlockup / softlockup
- ❌ No Oops / BUG: / Call Trace
- ❌ No PCIe link state events
- ❌ No `brcmf_pcie_attach`-body markers (test.128, test.134, test.130)

Pure silent backplane hang; consistent with prior wedges that aren't visible to AER under `pci=noaer`.

### Hypotheses

**H1 (leading): T288a's pre-set_active wrapper-base BAR0 reads wedge the AI backplane.**
T287c successfully ran the same setup() body. Only addition in T288a is the two `BCM4360_T288A_READ_WRAPS` invocations at "pre-write" and "post-write" (pre-set_active). Both fire BEFORE `brcmf_chip_set_active`, when ARM CR4 is HALTED. The macro:
1. config_dword save BAR0_WINDOW
2. config_dword set BAR0_WINDOW = `0x18100000` (chipcommon WRAPPER)
3. BAR0 read +0x000 (oobselina30)
4. BAR0 read +0x100 (oobselouta30)
5. config_dword set BAR0_WINDOW = `0x18103000` (PCIE2 WRAPPER)
6. BAR0 read +0x000
7. BAR0 read +0x100
8. select_core(PCIE2) (config_dword write to 0x18003000)

**Wrapper-page reads at PRE-set_active are novel.** All prior pre-set_active probes (T241, T280, T284, T285) read register-bases (`0x18000xxx` chipcommon, `0x18003xxx` PCIE2). T288a is the first to read wrapper pages (`0x181xxxxx`) at this stage. Wrapper register reads while ARM is halted may stall the backplane for the same reason post-set_active wrapper reads behave differently from register-base reads.

But wait — but the setup callback's `pre-attach` log marker should fire BEFORE the T288a invocations (which are deep inside attach → cold-init → ramwrite → pre-set-active). If T288a wedged the backplane, we'd expect `pre-attach` and many more markers to fire FIRST. Yet `pre-attach` never logged. So H1 alone doesn't explain the silent gap from `setup-entry` to nothing.

**H2 (alternative): The wedge is NOT in T288a's macro at all — it's in something setup() does between line 7045 (CALLBACK INVOKED) and line 7053 (pre-attach log).**
Lines 7046-7052: `brcmf_pcie_probe_armcr4_state(devinfo, "setup-entry")` (ran — logged), `msleep(300)`, error check, then pre-attach log. The msleep(300) cannot itself wedge. The `setup-entry` log fired — so `brcmf_pcie_probe_armcr4_state` returned. Then msleep(300) → pre-attach log. Why doesn't pre-attach fire?

Possible: a race or hang AFTER the msleep but BEFORE the `brcmf_pcie_probe_armcr4_state(devinfo, "pre-attach")` call. The next operation is `brcmf_pcie_probe_armcr4_state` itself (which probes ARM state via core-switching reads). On boot -1 (post-SMC-reset substrate, very fresh), this hasn't wedged before — and T287c on the same boot ran fine.

**H3: Substrate drift independent of T288a.**
The substrate WAS post-SMC-reset 23:45 BST (boot -1 = boot post-SMC-reset). Uptime at fire was ~26 min. T287c ran at 23:39 on boot -2 (BEFORE SMC reset) reaching t+90s. Boot -1 was a **fresh** post-SMC-reset substrate — usually best-case. Substrate drift is a weak hypothesis given the fresh-boot context.

### Hypotheses are mutually exclusive — current data can't discriminate

H1 says T288a wrapper-base reads wedged the backplane (a real runtime difference: `bcm4360_test288a_wrap_read=1` was set). H2 says wedge was UPSTREAM of T288a. These can't both be true. Current journal cuts off at module_init's last marker (test.156) — but that's the synchronous thread, not setup() body. Setup() body could have run silently for tens of seconds with journald buffering output before the hard hang ate the buffered lines.

**Verdict: cannot tell from this fire whether T288a code was ever entered.** Need anchor pr_emerg lines to discriminate next time.

### Diff vs T287c's working build (verified)

`git diff 7cc6d76..c902c06 -- phase5/work/.../pcie.c` is purely additive:
- New `bcm4360_test288a_wrap_read` module_param + `BCM4360_T288A_READ_WRAPS` macro definition
- 5 new invocations of `BCM4360_T288A_READ_WRAPS(...)` appended to existing T287/T284 invocation lines (pre-write, post-write, post-set_active, post-T276-poll, post-T278-initial-dump)
- 1 new invocation inside `BCM4360_T278_HOOK` (fires at t+500ms / t+5s / t+30s / t+90s)

**No changes between `setup-entry` and `pre-attach` log markers.** T288a code only runs inside `brcmf_pcie_download_fw_nvram` (deep inside attach). Either:
- T288a code never ran AND the wedge is somewhere upstream (but that wedge wouldn't be caused by T288a-the-feature, it'd be a substrate or build-link side effect of adding the macro definitions — a long shot)
- OR setup() body produced many log lines that journald buffered, and the wedge fired in T288a's macro body, eating the buffered lines

### Next step (T288a' — anchored re-fire, after substrate clear)

1. ✓ Add `pr_emerg` anchor lines BEFORE each sub-step inside `BCM4360_T288A_READ_WRAPS` macro (8 anchors per invocation: BAR0_WINDOW save, set CC-wrap window, read +0x000, read +0x100, set PCIE2-wrap window, read +0x000, read +0x100, select_core(PCIE2)).
2. ✓ Build clean (done 2026-04-26).
3. (user) Cold cycle preferred — current boot is recovery from hard wedge, substrate uncertain. CLAUDE.md substrate rule: only cold cycle (shutdown + ≥60 s + SMC reset) buys clean ~20–25 min window.
4. (user) Fire same command as PRE-TEST.288a (no param changes — new code is in macro body, gated on existing flag).
5. Read anchor sequence from journal to pinpoint sub-step where wedge happens.

### Discriminator table for T288a' fire

| Anchors that DO appear in journal | Reading |
|---|---|
| (none past T287c-baseline markers) | H2 wins: wedge is upstream of T288a; T288a code never ran. Disable T288a + re-fire baseline to confirm. |
| `pre-write anchor-1` only | H1 confirmed at first sub-step (BAR0_WINDOW save fails — implausible, config-space read shouldn't wedge). |
| Through `pre-write anchor-3` | Wedge on chipcommon-WRAPPER read at +0x000. |
| Through `pre-write anchor-4` | Wedge on chipcommon-WRAPPER read at +0x100 (the BIT_alloc target). |
| Through `pre-write anchor-6` | Wedge on PCIE2-WRAPPER read at +0x000. |
| Through `pre-write anchor-8` | Wedge on `select_core(PCIE2)` (config-space write). |
| Full pre-write sequence + `post-write anchor-N` | Wedge in second invocation (post-intr_enable). |
| Full pre-set_active + post-set_active anchors | Wedge in T276 poll or later — back to baseline late-ladder behavior. |

### Substrate (current — recovery boot)

- Boot 0 (current) post-watchdog-reboot from T288a wedge (boot -1)
- Uptime 5 min
- PCIe state: Status flag clean, no MAbort/CommClk drift visible
- 0 fires this boot
- Recommend: cold cycle before next fire — substrate is uncertain after a hard wedge

---

## PRE-FIRE.288c (2026-04-26 09:55 BST — substrate ready) [SUPERSEDED — fired and POST-TEST.288c recorded above; the "expected wedge per H1" did not materialize at H1's predicted site — wedge happened upstream of macro at fw chunk-1]

- User completed cold cycle + SMC reset
- Uptime at substrate verification: 3 min
- PCIe state (sudo lspci -vvv -s 03:00.0):
  - Status: Cap+ ... >TAbort- <TAbort- <MAbort- >SERR- <PERR- (no aborts)
  - DevSta: CorrErr+ NonFatalErr- FatalErr- UnsupReq+ AuxPwr+ TransPend- (sticky bits from boot training; canonical wedge markers MAbort/CommClk- are clean)
  - LnkCtl: ASPM L0s L1 Enabled, CommClk+ (clean clock)
  - LnkSta: Speed 2.5GT/s, Width x1 (Gen1 x1 trained correctly)
- 0 brcmfmac modules loaded (only mt76 stack on cfg80211)
- Module: brcmfmac.ko 15 085 568 B, mtime 2026-04-26 00:24, 8 anchor strings compiled in
- 0 fires this boot
- About to fire per PRE-TEST.288c "Fire command" block below — `bcm4360_test288a_wrap_read=1`

---

## PRE-TEST.288c (2026-04-26 09:30 BST — **READY ON USER COLD-CYCLE CLEARANCE. Re-fire of T288a anchored variant — same binary as T288b but with `bcm4360_test288a_wrap_read=1`. Identifies WHICH sub-step in the wrapper-read macro wedges the backplane. WILL CRASH THE MACHINE per H1; cold cycle required again afterwards.**) [SUPERSEDED — fire wedged upstream of macro at fw chunk-1; discriminator table did not apply. POST-TEST.288c above.]

### Hypothesis

H1 (CONFIRMED-BY-EXCLUSION via T288b): T288a's `BCM4360_T288A_READ_WRAPS` macro wedges the backplane at one specific sub-step. T288c uses the 8-anchor instrumentation already built into the macro to identify WHICH sub-step:

| Last anchor seen | Sub-step that wedged |
|---|---|
| (none — wedge before macro) | upstream of T288a — implausible (T288b proved upstream is clean with this binary) |
| `pre-write anchor-1` only | BAR0_WINDOW save (config-space read) — implausible |
| `pre-write anchor-2` | set CC-wrap window (config-space write to BAR0_WINDOW reg) |
| `pre-write anchor-3` | BAR0 read of `oobselina30` at chipcommon-wrap +0x000 |
| `pre-write anchor-4` | BAR0 read of `oobselouta30` at chipcommon-wrap +0x100 (BIT_alloc's actual target) |
| `pre-write anchor-5` | set PCIE2-wrap window (config-space write) |
| `pre-write anchor-6` | BAR0 read of PCIE2-wrap +0x000 |
| `pre-write anchor-7` | BAR0 read of PCIE2-wrap +0x100 |
| `pre-write anchor-8` | `select_core(PCIE2)` end-of-macro (config-space writes) |
| Full `pre-write` 1-8 + `post-write anchor-N` | wedge in 2nd invocation (post-intr_enable) |
| Full pre-write + post-write + post-set_active anchors | wedge in T276 poll or later — back to baseline late-ladder |

If the wedge happens at anchor-3 or anchor-4 (chipcommon-wrap reads while ARM CR4 is HALTED), that's the load-bearing finding: **wrapper-page reads pre-set_active stall the backplane on BCM4360**. This explains the T270-BASELINE late-ladder fault as a separate issue and reframes T288 work toward post-set_active wrapper reads only.

### Discriminator outcomes

| Result | Reading | Next step |
|---|---|---|
| Last anchor = `pre-write anchor-3` or `-4` | CC-wrap reads pre-set_active wedge backplane while ARM halted | T288d: skip pre-write invocation, only invoke post-set_active and later |
| Last anchor = `pre-write anchor-6` or `-7` | PCIE2-wrap reads pre-set_active wedge backplane | Same as above |
| Last anchor = `pre-write anchor-8` | end-of-macro `select_core(PCIE2)` is the wedger | Replace select_core with raw config-space restore of saved BAR0_WINDOW |
| Reaches `post-set_active anchor-X` | wrapper reads safe pre-set_active; wedge happens later (likely post-set_active iteration 1) | Pursue post-set_active sub-step |
| Reaches all anchors at all stages then late-ladder wedge | (unlikely given T288a/T288a' wedges) — implies prior wedges were also substrate. Re-evaluate. | Treat T288 instrumentation as production-safe; pursue late-ladder wedge as the live problem |

### Diff vs T288b fire

Identical command except `bcm4360_test288a_wrap_read=1` (was `=0`). Same .ko. No rebuild.

### Substrate prerequisites — REQUIRED

⚠️ Current boot (boot 0, since 09:24:50 BST) is recovery from T288b's late-ladder wedge. `DevSta: UnsupReq+ CorrErr+ AuxPwr+` are leftovers from the wedge that don't clear without SMC reset.

- **REQUIRED**: full cold cycle = `shutdown -h now`, wait ≥60 s power-off, SMC reset, then power on.
- After cold cycle: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta|DevSta'` (expect `DevSta` flags clean OR at most `AuxPwr+`; no MAbort; LnkSta trained Gen1 x1).
- Uptime should be ≤2 min at fire — clean window is widest right after cold cycle (per KEY_FINDINGS substrate row).
- ⚠️ T288c WILL crash the machine again per H1. Another cold cycle will be required AFTER T288c fires before any further hardware test.

### Fire command (T288a flag = 1)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test288a_wrap_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.288c.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.288c.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.288c.journalctl.txt
```

If the machine wedges before journalctl runs (expected): on next boot, run `sudo journalctl -k -b -1 > phase5/logs/test.288c.journalctl.txt` to capture the wedged-boot log.

### Anchor format (8 lines per macro invocation, all `pr_emerg` priority)

The macro logs at `pr_emerg` (priority 0) which bypasses normal printk filtering and tries to flush eagerly to console — gives the best chance of surviving even a hard wedge:

```
brcmfmac: BCM4360 test.288a': <tag> anchor-1 (about to save BAR0_WINDOW)
brcmfmac: BCM4360 test.288a': <tag> anchor-2 (saved=0x........; about to set CC-wrap window)
brcmfmac: BCM4360 test.288a': <tag> anchor-3 (CC-wrap window set; about to read +0x000)
brcmfmac: BCM4360 test.288a': <tag> anchor-4 (CC.wrap[0x000]=0x........; about to read +0x100)
brcmfmac: BCM4360 test.288a': <tag> anchor-5 (CC.wrap[0x100]=0x........; about to set PCIE2-wrap window)
brcmfmac: BCM4360 test.288a': <tag> anchor-6 (PCIE2-wrap window set; about to read +0x000)
brcmfmac: BCM4360 test.288a': <tag> anchor-7 (PCIE2.wrap[0x000]=0x........; about to read +0x100)
brcmfmac: BCM4360 test.288a': <tag> anchor-8 (PCIE2.wrap[0x100]=0x........; about to select_core(PCIE2))
```

Stage tags (in order):
1. `pre-write (pre-set_active)` — BEFORE intr_enable, ARM CR4 halted
2. `post-write (pre-set_active)` — AFTER intr_enable, ARM CR4 halted
3. `post-set_active` — AFTER ARM CR4 release
4. `post-T276-poll` — after 2 s post-set_active poll
5. `post-T278-initial-dump` — after console dump
6-9. `t+500ms`, `t+5s`, `t+30s`, `t+90s` (T287 dwell stages)

### Pre-fire checklist (CLAUDE.md)

1. ✓ Build verification: anchor strings present in .ko (`strings ... | grep anchor-` = 8 hits) — no rebuild needed
2. (user) Cold cycle: shutdown ≥60 s + SMC reset
3. (user) PCIe state check after cold cycle (per Substrate prerequisites above)
4. ✓ Hypothesis stated above
5. ✓ Plan committed and pushed BEFORE fire (this file)
6. ✓ FS sync after push

### Risk and recovery

- Expected wedge per H1; recovery is watchdog reboot (~3 min) — no manual intervention historically required (KEY_FINDINGS substrate row: n>30 watchdog recoveries today)
- Worst case: hard hang requiring user-initiated power cycle. Mitigate by NOT being mid-edit at fire time.
- Anchor lines are written via `pr_emerg` (priority 0) — best-effort eager flush. Even with hard wedge, anchors LOGGED before the wedging instruction should make it to journal.

---

## PRE-FIRE.288b (2026-04-26 09:16 BST — substrate ready) [SUPERSEDED — fired and POST-TEST.288b recorded above]

- User completed cold cycle (shutdown + ≥60 s) + SMC reset
- Uptime at substrate verification: 2 min (within widest clean window per CLAUDE.md)
- PCIe state (sudo lspci -vvv -s 03:00.0):
  - Status: no aborts (>TAbort- <TAbort- <MAbort- >SERR- <PERR-)
  - D0 NoSoftRst+
  - LnkCtl: ASPM L0s L1 Enabled, CommClk+ (clean clock)
  - LnkSta: Speed 2.5GT/s, Width x1 (Gen1 x1 trained correctly)
- No brcmfmac modules loaded; cfg80211 already loaded (mt76 stack — irrelevant to BCM4360 path)
- Module: brcmfmac.ko 15.1 MB, mtime 2026-04-26 00:24 (anchors compiled in but T288a flag will be 0)
- 0 fires this boot
- About to fire per PRE-TEST.288b "Fire command" block below

---

## PRE-TEST.288b (BASELINE-FIRST, 2026-04-26 — **READY TO FIRE on user cold-cycle clearance. Same module binary as T288a/T288a' — but T288a runtime code DISABLED (`bcm4360_test288a_wrap_read=0`). Discriminates substrate vs T288a-runtime as the wedge cause. Per advisor: cheapest single-fire test that can disprove either confound.**)

### Hypothesis

If T288a' wedge was caused by substrate degradation (H1' from POST-TEST.288a'): then firing the same binary with T288a runtime code OFF on a cold-cycled substrate should reach t+90s with normal T287c-style trace.

If T288a' wedge was caused by T288a binary changes (H3' linker layout regression, or some unforeseen build-state side effect): then this fire will ALSO wedge early, even with T288a flag off — implicating the build, not the runtime path.

### Discriminator outcomes

| Result | Reading | Next step |
|---|---|---|
| Reaches t+90s with full T287c-style trace | Substrate was the only confound. T288a binary innocent. | Re-fire with `bcm4360_test288a_wrap_read=1` (= original T288a' plan with anchors) on a cold-cycled substrate |
| Wedges early like T288a' (cutoff at OTP-bypass or earlier) | T288a binary itself regresses something. NOT a runtime issue. | Compare `size brcmfmac.ko` and `git diff --stat 7cc6d76..HEAD -- phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`. Consider rebuilding from a cleaner tree state. |
| Wedges late (t+30s..t+120s) — like T287c-baseline late-ladder | Substrate clean, T288a binary innocent. Late-ladder fw wedge is the genuine recurring fault. | Re-fire with `=1` for the actual H1/H2 discrimination |
| Wedges between OTP-bypass and setup-entry | Same upstream cutoff as T288a'. T288a binary suspect, but timing isolation needed (e.g., `dmesg --console-level 8`, or sysrq for a forced backtrace) | Build-state investigation |

### Fire command (T288a flag = 0)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test288a_wrap_read=0 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.288b.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.288b.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.288b.journalctl.txt
```

**Diff vs T287c (last clean fire):** identical params; T287c didn't have `bcm4360_test288a_wrap_read` in its module. Same binary as T288a/T288a' but with T288a path inert.

**Diff vs T288a':** flip `bcm4360_test288a_wrap_read` from 1 to 0. No code change; same module file (mtime 2026-04-26 00:24, 15.1 MB, anchors compiled in but gated off).

### Substrate prerequisites — REQUIRED

- ⚠️ Current boot is recovery from T288a' wedge — DO NOT fire on this substrate.
- **REQUIRED**: full cold cycle = `shutdown -h now`, wait ≥60 s power-off, SMC reset, then power on.
- After cold cycle: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'` (expect Status flags empty, LnkSta showing trained Gen1 x1, no errors).
- Uptime should be ≤2 min at fire — clean window is widest right after cold cycle.

### Expected log sequence (if substrate clean & binary innocent)

Same as T287c late-ladder baseline:
- module_init through `test.156: after brcmf_core_init() err=0` (~10 s)
- `test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0` then `setup-entry`
- `test.128: before brcmf_pcie_attach` (~+1 s post-callback)
- T287/T276/T278 stage hooks at pre-write, post-write, post-set_active, post-T276-poll
- T278_HOOK at t+500ms / t+5s / t+30s / t+90s (final = "final/dwell")
- Late-ladder wedge at t+90..120s (orthogonal to readback)

**ZERO `anchor-N` lines expected** (T288a path is gated off). If any anchor- line appears, the gate is broken — diagnose code, don't trust the fire.

### Pre-fire checklist (CLAUDE.md)

1. ✓ Build (no rebuild needed — using existing 2026-04-26 00:24 binary with anchors compiled in)
2. (user) Cold cycle: shutdown ≥60 s + SMC reset
3. (user) PCIe state check after cold cycle
4. ✓ Hypothesis stated
5. ✓ Plan committed and pushed BEFORE fire (this document)
6. ✓ FS sync after push

### Why this fire instead of re-firing T288a' as planned

T288a' produced ZERO discrimination: no anchor lines, no setup-entry, cutoff at OTP-bypass. The original anchor design assumes the macro body executes — but T288a' showed the macro is never reached because the wedge is upstream. Re-firing T288a' on another substrate could either (a) succeed and leave us guessing whether T288a' code is innocent, or (b) wedge again at varying upstream points and still leave us guessing. **The baseline fire is the only fire that uniquely discriminates substrate vs T288a binary.** Once that's known, the next fire (with the right configuration) is informative.

---

## PRE-TEST.288a (2026-04-26 — **READY TO FIRE on user clearance. Reads chipcommon-wrap + PCIE2-wrap agent regs (oobselina30 +0x000 / oobselouta30 +0x100) at every T287 stage. End-of-macro select_core(PCIE2) — applies the lesson from T287b's window-leak.** [SUPERSEDED by POST-TEST.288a above — fire wedged the machine before set_active. Block kept here for diff context.])

### Hypothesis

BIT_alloc dereferences `[sched+0x254]+0x100` per T283 chain. T287c confirmed
`sched+0x254` holds `0x18100000` (chipcommon-wrap) post-set_active and
`0x18101000` (core[2]-wrap) after T276 poll. PCIE2-wrap is at sched+0x264.
T288a reads `oobselouta30` (offset 0x100, the AI-backplane OOB-routing
output register) and `oobselina30` (offset 0x000, OOB-routing input) at
both chipcommon-wrap and PCIE2-wrap on every T287 stage.

Expected primary readings:
- **CC.wrap[0x100]** is what BIT_alloc reads at class=0. Will reveal what
  routing-slot bits are set/free.
- **PCIE2.wrap[0x100]** would be BIT_alloc's read at class=4 (PCIE2-class)
  if active.
- Comparing **+0x000 vs +0x100** at each wrap reveals input vs output
  routing state.

Discriminations:
- All 4 reads = 0x00000000 → no OOB routing configured anywhere; BIT_alloc
  finds 5-bit field=0 → "no slot allocated" interpretation; fw waiting on
  a host-side action to populate routing.
- Some bits set in CC.wrap[0x100] → routing IS configured; BIT_alloc would
  return a non-zero slot index → fw potentially making progress past
  BIT_alloc but waiting on the slot's destination.
- Bits change between stages (pre-set_active vs post-set_active vs after
  T276 poll) → fw is actively writing OOB routing state.
- All 4 = 0xFFFFFFFF or readback artefact → wrong page selected; need to
  verify BAR0_WINDOW state.

### Substrate

- Boot 0 (current) post-SMC-reset (23:45 BST 2026-04-25). Uptime now ~7h.
- 1 fire on this boot (none — last fire was T287c on boot -1).
- PCIe state: clean (Status flag empty, no MAbort/CommClk/LnkSta drift).
- Build: brcmfmac.ko rebuilt 2026-04-26 with T288a wired (clean compile).

### Fire command

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test288a_wrap_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.288a.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.288a.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.288a.journalctl.txt
```

**Diff vs T287c fire:** add `bcm4360_test288a_wrap_read=1` (one extra param).
T285 stays disabled (chipcommon-target was wrong AND its window-leak burned T287b).

### What T288a writes / reads

Per stage (9 stages): save BAR0_WINDOW (1 config-space read), set window to
chipcommon-wrap (1 config-space write), 2 BAR0 reads, set window to
PCIE2-wrap (1 config-space write), 2 BAR0 reads, select_core(PCIE2) (1
config-space read + up to 2 writes inside the helper). Total per stage:
~9 config-space ops + 4 BAR0 reads. Across 9 stages: ~81 config ops + 36
BAR0 reads. Substrate cost similar to T285 (which ran cleanly at every
stage modulo the leak); the difference is the END-OF-MACRO select_core(PCIE2)
that closes the leak window.

### Expectations vs prior wedge pattern

- t+0ms wedge expected: NO. Lesson from T287c: with clean BAR0 state at
  poll start, no t+0ms wedge.
- Late-ladder wedge expected: YES, ~t+90s..120s as in T276/T277/T278/T287c.
  Orthogonal to readback; fw-side root cause.
- If T288a wedges at t+0ms: T288a's window-restoration logic is broken.
  Falsifies the design — diagnose before re-fire.
- If T288a reaches t+90s and adds primary-source data: same baseline as
  T287c. Compare wrapper register values across stages and against
  pre-set_active baseline.

### Pre-fire checklist (CLAUDE.md)

1. ✓ Build (done 2026-04-26 — clean compile)
2. (user) PCIe state check: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
3. ✓ Hypothesis stated above
4. ✓ Plan committed and pushed BEFORE fire
5. ✓ FS sync (will run after commit)

---

## POST-TEST.287c (2026-04-25 23:39 BST fire, boot -1 — **BOTH HYPOTHESES CONFIRMED. T287c reached t+90s, matching T276/T277/T278 baseline. Class-table layout = strongest design reading. First runtime evidence of fw class-dispatch.**)

### Timeline (from `phase5/logs/test.287c.journalctl.txt`, boot -1)

- `23:39:47` insmod → normal probe path (FORCEHT, NVRAM, T276 shared_info written and readback PASS — all markers identical to prior fires through pre-set_active)
- `23:40:17` T287 pre-write (pre-set_active): all 7 offsets = 0
- `23:40:17` T287c pre-write (pre-set_active): all 6 extras = 0 (BSS-clear before ARM release — confirms expected)
- `23:40:17` T284 pre-write MBM=0x318 (normal), INT=0
- `23:40:17` `brcmf_pcie_intr_enable` called, returned cleanly; T284/T287/T287c post-write unchanged (intr_enable doesn't populate sched_ctx)
- `23:40:17` `brcmf_chip_set_active returned TRUE`
- `23:40:17` **T287 post-set_active** (matches T287b exactly):
  - `+0x10 = 0x00000011` (flag-like)
  - `+0x18 = 0x58680001` (chipc.caps — readback infra proven)
  - `+0x88 = 0x18000000` (CHIPCOMMON register base)
  - `+0x8c = 0x18000000` (twin)
  - `+0x168 = 0x00000000`
  - `+0x254 = 0x18100000` (CHIPCOMMON wrapper)
  - `+0x258 = 0x18100000` (twin)
- `23:40:17` **T287c post-set_active (NEW DATA — strongest layout reading):**
  - `+0x25c = 0x18101000` (core[2] wrapper, id=0x812)
  - `+0x260 = 0x18102000` (core[3] wrapper = ARM-CR4, id=0x83e)
  - `+0x264 = 0x18103000` (core[4] wrapper = **PCIE2**, id=0x83c)
  - `+0x268 = 0x18104000` (core[5] wrapper, id=0x81a)
  - `+0x26c = 0x00000000` (core[6] id=0x135 has no register base; table truncates here)
  - `+0x270 = 0x00000000` (beyond table)
- `23:40:17` T276 2s poll entered; `t+0ms si[+0x010]=0x0009af88 fw_done=0 mbxint=0` — reproduces prior si[+0x010] response. **NO t+0ms wedge — poll completed cleanly to poll-end.**
- `23:40:17` post-T276-poll: `+0x88 = 0x18001000` **(shifted from chipcommon-base → core[2]-base)**, `+0x254 = 0x18101000` **(shifted from chipcommon-wrap → core[2]-wrap)** — first runtime evidence of fw class-thunk dispatch
- `23:40:17` T277 console struct decoded as before (587 B written: chipc dump, kattach, RTE banner, pciedngl_probe, wl_probe)
- `23:40:17` T278 t+500ms / `23:40:17` t+5s / `23:40:17` t+30s / **`23:41:42` t+90s** — all stable, no new console content, all sched_ctx values frozen (matches T257 WFI reading)
- `23:41:42` LAST log line — wedge silently sometime after t+90000ms dwell
- `23:45` user SMC reset → boot 0

### Hypotheses outcome

**Primary (#40 wedge-timing): CONFIRMED.** Disabling T285 eliminated the t+0ms wedge. T287b's anomaly was the T285 macro leaking BAR0_WINDOW = 0x18102000, causing T276 PCIE2 reads to hit the wrong backplane address. With T285 off, baseline late-ladder wedge restored (~t+90s..120s), matching T276/T277/T278.

**Secondary (class-table layout): STRONGEST reading CONFIRMED.** sched+0x254..+0x268 is a per-class wrapper-base table indexed by class, populated in EROM walk order. Chipcommon takes BOTH +0x254 (scratch per T283) AND +0x258 (table[0]) — they happen to start identical because class=0 was active. Cores 2..5 occupy +0x25c through +0x268 in EROM order. Core[6] (id=0x135, no register base) is excluded from the table.

**Bonus — fw class-dispatch is active.** Between post-set_active and post-T276-poll (a ~2 s window), fw shifted scratch (+0x254 / +0x88) from chipcommon-context to core[2]-context. This is the first DIRECT evidence of fw class-thunk dispatching during post-set_active. Either (a) fw class-1 thunk runs spontaneously during scheduler init, or (b) the host's polling activity (BAR0_WINDOW switching during T276/T284 reads) somehow triggers a wake. (a) more likely given +0x88 also shifted (BAR0_WINDOW reads use a different mechanism that wouldn't touch scratch).

### Address corrections in KEY_FINDINGS

- **Sched+0x264 = 0x18103000 = PCIE2 wrapper.** This is the slot where BIT_alloc would land if class=4 (PCIE2-class) was active. Currently runtime shows class=1 (core[2]) active during/after T276 poll.
- **Class table is per-WRAPPER, not per-register-base.** Aligns with T283's `[sched+0x254]+0x100` chain — +0x100 is the AI-backplane agent-register offset (`oobselouta30`), only valid on wrapper pages.
- T287b's claim "+0x254 = 0x18100000 = PCIE2 base" was already corrected to "= chipcommon WRAPPER" in 2026-04-24 evening. T287c reinforces: the slot for PCIE2 wrapper is +0x264, not +0x254.

### Next step

**T288a — read-only probe of PCIE2-wrapper +0x100 AND chipcommon-wrapper +0x100, with proper saved_win restore.** Reads what BIT_alloc actually sees at runtime under whatever class is currently active. Fires alongside T287/T287c (no removal) and T284. Read-only, low substrate cost — but MUST restore BAR0_WINDOW after each read (lesson from T285).

Open: design probe-stage placement. Best candidates: post-set_active + post-T276-poll (where +0x254 transitions). Skip pre-set_active (table empty).

### Pre-fire substrate notes (for next fire)

- Boot 0 (current) post-SMC-reset, fresh substrate.
- 2 fires today (T287b + T287c) both wedged late-ladder; substrate burn moderate.
- Wait for clean cold-power-cycle window before T288a fire if possible.

---

## PRE-TEST.287c (2026-04-25 23:30 BST — **FIRE: T287c extended class-table dump + T285 disabled. Tests both wedge-timing hypothesis (#40) AND class-table layout reading.**)

### Hypothesis — dual

**Primary (wedge-timing #40):** With T285 disabled, BAR0_WINDOW will not be left at 0x18102000 by any probe. T276's poll PCIE2 reads will land on the correct backplane window. Expected: NO t+0ms wedge; poll continues to t≥90 s as in T276/T277/T278 (which all reached late-ladder, not t+0ms). If wedge still occurs at t+0ms, hypothesis falsified — investigate readback-volume or substrate next.

**Secondary (class-table layout):** T287c dumps sched+0x25c, 0x260, 0x264, 0x268, 0x26c, 0x270 at every T287 stage. At post-set_active stage, expected layouts:

| Layout (post-set_active) | Reading |
|---|---|
| `+0x25c=0x18101000, +0x260=0x18102000, +0x264=0x18103000, +0x268=0x18104000, +0x26c=0x18108000, +0x270=0` | **Strongest:** class table is per-core wrapper, indexed by class. 6 cores → 6 entries (0x254 is scratch, 0x258..0x26c hold wrapper bases of cores 1..6). |
| `+0x25c..+0x270` all zero | Only class-0 is populated; later classes unused. Wake-path investigation focused on chipcommon-wrapper alone. |
| `+0x25c..+0x270` hold non-MMIO values (TCM addresses, function pointers, struct addresses) | Layout is NOT a wrapper-base table. Re-think class table interpretation. |
| `+0x25c..+0x270` mix wrapper bases with other values | Partial table — class indices are sparse; need to dump more offsets. |

### Substrate

- Fresh boot, uptime 21 min at fire time
- No brcmfmac modules loaded
- PCIe state: D0, Gen1 x1, no Status flags (clean)
- BAR0_WINDOW state: irrelevant pre-load (driver hasn't touched it)

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.287c.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.287c.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.287c.journalctl.txt
```

**Crucial differences from T287b run:**
- `bcm4360_test285_chipcommon_read=0` (omitted — default 0). Removes both the chipcommon target (now confirmed wrong) AND its window-leak.
- `bcm4360_test287c_extended=1` (NEW). 6 extra BAR2 reads per T287 stage.
- Everything else (T236/T238/T276/T277/T278/T284/T287) identical to T287b.

### Fire expectations

- Same probe-path entry markers as T287b (insmod, brcmf_pcie_register, buscore_reset, FORCEHT, NVRAM, etc.)
- T287 pre-write (pre-set_active): all offsets = 0 (BSS-clear before ARM release)
- T287c at same stage: all 6 extras = 0 (same BSS region)
- T287 post-set_active: same values as T287b (+0x10=0x11, +0x18=0x58680001, +0x88/0x8c=0x18000000, +0x254/0x258=0x18100000)
- T287c post-set_active: **NEW DATA** — first observation of these offsets
- T276 poll: should reach t+10ms tick if window-leak hypothesis correct; probably reaches late-ladder (t+90s..120s) like T276/T277/T278 baseline
- Wedge: probably late-ladder (chip wedges due to other root cause — orthogonal to readbacks). NOT at t+0ms if hypothesis correct.

### Pre-fire sync

Commit + push this PRE-TEST block before fire. fs sync after push.

### Static finding: writer-of-sched+0x258 settled by exhaustive negation

Six scans across the full code region (0x800..0x6bf78) using per-2-byte-aligned
Thumb decode (immune to capstone's linear-decode failures):

| Pattern | Hits | Script |
|---|---|---|
| Literal pool entry = 0x18100000 (or any wrapper base) | 0 | t288_find_258_writers.py + t288_wrapper_origin.py |
| Literal pool entry = 0x18000000 (chipcommon base, baseline) | 1 (at file-offset 0x328) | same |
| `mov.w rN, #0x18100000` | 0 | t288_find_class_table_writer.py |
| `movw rN, #imm; movt rN, #imm` constructing 0x18100000 | 0 | same |
| `lsl rN, rM, #20` (bit-20 set) | 0 | t288_wrapper_origin.py |
| `orr/add #0x100000` (chipcommon-base → wrapper-base conversion) | 0 | same + t288_wrapper_origin.py |
| `str* rN, [rM, #0x258]` (direct store at offset 0x258) | 0 | t288_find_258_writers.py + t288_robust_offset_scan.py + t288_indirect_pointer_scan.py |
| `str* rN, [rM, #0x254]` (direct store, includes the existing class-0 thunk write at 0x2880) | 2 (only 0x2880 + an unrelated `strh.w` at 0x284a4) | t288_robust_offset_scan.py |
| `strd` paired writes anywhere | 28 (all in unrelated areas; none at 0x254/0x258 vicinity) | same |
| `stm rN, {rX, rX}` (twin-write same value) | 0 | t288_stm_scan.py |
| `add rN, rM, #imm` where imm in 0x240..0x280 (pointer arith into class-table region) | 14 (ALL `add rN, sp, #imm` — stack frame, NOT sched_ctx) | t288_indirect_pointer_scan.py |

**Conclusion (now CONFIRMED in KEY_FINDINGS):**
- The exact instruction that writes `sched+0x258 = 0x18100000` cannot be located by any of the patterns we'd expect a compile-time constant to use.
- Only the chipcommon **register base** `0x18000000` appears as a literal — every other backplane address (5 other core bases, 5 other wrapper bases) is constructed at runtime from EROM walks.
- Architecturally this is consistent with BCMA: each core's EROM section advertises register-base AND wrapper-base; the enumerator reads them via base-register addressing where the offset doesn't appear as a regex-matchable literal.
- This is a **load-bearing finding** but NOT a blocker: the value at `sched+0x258` is what BIT_alloc dereferences, so the runtime value (T287b: 0x18100000) is what matters for the wake-path investigation, not the writer.

Closes the "open static question" from POST-TEST.287b. Two new CONFIRMED rows added to KEY_FINDINGS (negative-result + architectural-origin).

### Wedge-timing anomaly (#40) — leading hypothesis

T287b wedged at t+0ms of the 2 s poll — earliest wedge in the test series, with no AER/NMI/MCE/Oops markers.

**Leading hypothesis: T285 macro leaked BAR0_WINDOW.**

Evidence from T287b log (RESUME_NOTES.md line 34):
- `T285 post-set_active CC.INTSTATUS=0xFFFFFFFF INTMASK=0xFFFFFFFF saved_win=0x18102000`
  — i.e. BAR0_WINDOW was at `0x18102000` (ARM-CR4 wrapper) when T285 finished, but never restored.
- T276 poll then enters and tries to read `PCIE_MAILBOXINT` (a PCIE2-core register) via BAR0.
- BAR0_WINDOW still on ARM-CR4 wrapper → the read goes to the wrong backplane address.
- **PCIe transactions to non-responsive backplane targets can hang silently** without surfacing an AER UR (especially with `pci=noaer` in cmdline). Matches the "no crash markers, t+0ms wedge" signature exactly.

Alternative hypotheses (lower-ranked):
- **7 extra TCM reads/stage as load** — implausible. T245/T246/T277 all did multi-read TCM probes without wedge; BAR2 direct reads are routine.
- **Substrate drift** — possible but non-discriminating; no specific signal differentiates this from #1.

**Discriminator on next fire:** disable T285 entirely. If T287c (T287's BAR2-only sched_ctx dump) plus T284 (single PCIE2 read with proven restore-window pattern) plus T276 (poll) runs to t≥90s without wedge, the window-leak hypothesis is confirmed. If it still wedges at t+0ms, hypothesis falsified — investigate readback-volume next.

### T287c — design (extends T287's class-table dump)

**Goal:** characterize the class table at sched_ctx+0x254..0x270 to confirm the
"per-class wrapper-base table" reading. Currently we only know +0x254/+0x258
both = 0x18100000. Knowing +0x25c, +0x260, +0x264, +0x268 entries discriminates:

| Layout in sched+0x254..0x270 | Reading |
|---|---|
| +0x254=0x18100000, +0x258=0x18100000, +0x25c=0x18101000, +0x260=0x18102000, +0x264=0x18103000, +0x268=0x18104000 | "Class table is per-core wrapper-base, indexed by class — class 0..N maps to discovered cores in EROM order." Strongest reading. |
| +0x254 ≠ +0x258 (after a fresh class-N thunk run) | +0x254 IS the scratch (per T283); +0x258 onwards IS the table. |
| +0x25c..+0x268 all zero | Only class-0 is populated; other classes' wrapper-base slots are unused. |
| +0x25c..+0x268 hold non-wrapper values (e.g. function pointers, struct addrs) | Layout is NOT a wrapper-base table; the +0x254/+0x258 twin is coincidental — re-think. |

**Implementation:**
- Reuse existing T287 macro pattern (`brcmf_pcie_read_ram32` BAR2 direct, no
  core-switching, no BAR0_WINDOW state).
- Add 6 more offsets to the read list: `0x25c, 0x260, 0x264, 0x268, 0x26c, 0x270`.
- Probe at the SAME 9 stages T287 currently probes (no new probe sites).
- Total cost: 6 extra 32-bit BAR2 reads × 9 stages = 54 reads on top of T287's
  63 reads (≈25 µs of bus time per stage; well under T276 poll cadence).
- Module-param: rename existing `bcm4360_test287_sched_ctx_read` to
  cover T287c automatically; or add `bcm4360_test287c_extended=1` gate for
  surgical opt-in.

**Disable for next fire:**
- `bcm4360_test285_chipcommon_read=0` — removes chipcommon target (now
  confirmed wrong) AND removes the window-leak.
- T284 stays (single PCIE2 MBM read, proven restore pattern, 1 reg).
- T287c on (extended sched ctx dump, BAR2-only).
- T276/T277/T278 unchanged.

**Pre-test checklist (when user clears for next fire):**
1. ✓ Build (run `make -C phase5/work` after editing `bcm4360_test.c`).
2. ✓ PCIe state check: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`.
3. ✓ Hypothesis: "T287c will dump 6 more class-table words and reveal a per-core
   wrapper-base layout. Disabling T285 will avoid the t+0ms wedge."
4. ✓ Plan committed and pushed BEFORE fire.
5. ✓ FS sync (`sync`).

NOT YET BUILT — next session needs the code edit + build.

### Discord/access notes

User said "out tomorrow" on 2026-04-24 close. Today is 2026-04-25. Treat as
no-fire window unless user confirms otherwise. Static + design committed and
pushed; resumes ready for either continued static work or first fire of T287c.

---

## POST-TEST.287b (2026-04-24 20:44 BST fire, boot -1 — **SUBSTANTIVE FIRE: 3 T287 stages captured. Primary-source scheduler ctx values. T283 BIT_alloc chipcommon claim FALSIFIED — `+0x254 = 0x18100000 (PCIE2)`, not 0x18000000 (chipcommon). Wedge at t+0ms of 2s poll (earlier than prior fires — timing anomaly noted, not diagnosed).**)

### Timeline (from `phase5/logs/test.287b.journalctl.txt`)

- `20:45:03` insmod → normal probe path (all markers identical to prior fires up through FORCEHT)
- `20:45:03` T276 shared_info written, readback PASS
- `20:45:03` **T287 pre-write (pre-set_active): all 7 offsets = 0** — scheduler ctx BSS-clear before ARM release
- `20:45:03` T284 pre-write MBM=0x318 (normal), INT=0
- `20:45:03` T285 pre-write CC.INTSTATUS=0xFFFFFFFF, INTMASK=0xFFFFFFFF, CC[0x168]=0 (`saved_win=0x18000000`)
- `20:45:03` `brcmf_pcie_intr_enable` called, returned cleanly
- `20:45:03` **T287 post-write (pre-set_active): still all 7 offsets = 0** — sched_ctx NOT populated by intr_enable
- `20:45:03` T284 post-write MBM=0x318 (write dropped, matches T284 finding)
- `20:45:03` `brcmf_chip_set_active returned TRUE`
- `20:45:03` **T287 post-set_active (CRITICAL):**
  - `+0x10 = 0x00000011` (non-zero flag-like)
  - `+0x18 = 0x58680001` **← matches chipc.caps (T277/T278 console)** — readback infra proven
  - `+0x88 = 0x18000000` (CHIPCOMMON MMIO base)
  - `+0x8c = 0x18000000` (CHIPCOMMON MMIO base, twin)
  - `+0x168 = 0x00000000` (remains zero — not the pending-events word here)
  - `+0x254 = 0x18100000` **(PCIE2 MMIO base, NOT CHIPCOMMON)**
  - `+0x258 = 0x18100000` **(PCIE2 MMIO base, twin)**
- `20:45:03` T284 post-set_active MBM=0 (matches T284 — set_active clears MBM)
- `20:45:03` T285 post-set_active CC.INTSTATUS=0xFFFFFFFF INTMASK=0xFFFFFFFF **`saved_win=0x18102000`** (window unrestored after macro — noted, not fatal)
- `20:45:03` T276 2s poll entered; `t+0ms si[+0x010]=0x0009af88 fw_done=0 mbxint=0` — reproduces prior si[+0x010] response
- [silent wedge; no further poll ticks; no AER/MCE/NMI/Oops]
- `20:47` watchdog reboot to current boot 0

### Key finding — T283 partial correction

**T283 static disasm claimed** BIT_alloc reads `[scheduler_ctx+0x254]+0x100 = 0x18000100 (chipcommon INTSTATUS)`. **Primary-source RUNTIME value** shows `+0x254 = 0x18100000` = **PCIE2 MMIO base**. Therefore BIT_alloc's target is `0x18100100` = PCIE2 core + 0x100, not chipcommon.

- T283's *structural* claim (BIT_alloc reads `[sched+0x254]+0x100`) appears to hold — offset chain matches. Just the BASE was misidentified.
- Chipcommon IS still present in sched_ctx, but at `+0x88/+0x8c`, not `+0x254`. Different path, different purpose (allocator registration area?).
- PCIE2 core + 0x100 is not one of the documented register names in pcie.h prior notes (those are MAILBOXINT=0x48, MAILBOXMASK=0x4C, H2D_MAILBOX_{0,1}=0x140/0x144). **Next task: grep pcie.h for 0x100/0x104/0x108 semantics.**

### Cross-validation

`sched[+0x18] = 0x58680001` is byte-for-byte the **chipc.caps** value fw's own console printed in T277/T278 runs. This proves the T287 TCM read machinery works — we're seeing real fw-written data.

### What's now SUPERSEDED in KEY_FINDINGS

- Row "BIT_alloc reads chipcommon INTSTATUS at absolute `0x18000100`" → **SUPERSEDED**. Correct target is PCIE2 core + 0x100.
- Row claiming T283's chipcommon hypothesis fully holds → **PARTIAL** — offset chain structurally correct, base was wrong.
- T285's chipcommon INTSTATUS=0xFFFFFFFF readings are now of unclear value (T283's chipcommon hypothesis is falsified, so T285 was probing the wrong register). Not a new target.

### Wedge-timing anomaly (noted, not diagnosed)

T276/T280/T284 wedge at t+90s–120s (late-ladder). T287b wedged at t+0ms of the 2s poll — FIRST tick. No crash markers (no AER, no NMI, no MCE, no Oops). Possible causes:
- Substrate drift compounding across this session's fires (plausible — today's n is high).
- 7 extra TCM reads per stage (BAR2 direct, microseconds each) tripping something not seen in smaller-scope probes.
- The `saved_win=0x18102000` carry-over from T285 macro affecting subsequent reads.

Don't refire on this boot. Static work (pcie.h grep) produces next-step info without substrate cost.

### Next step (Option C per PRE-TEST.285)

1. ✓ Grep pcie.h: PCIE2+0x100 **not named** in brcmfmac (gap 0x4C→0x120). Upstream `bcma_driver_pcie2.h` calls it `RC_AXI_CONFIG`, but that is the ROOT-COMPLEX-side view, NOT the endpoint-side view the fw sees — so `RC_AXI_CONFIG` does NOT apply here. EP-side register at PCIE2+0x100 is unnamed in-tree.
2. ✓ Fw blob primary-source grep for absolute `0x18100100` / `0x18100048` / `0x18100140` / `0x18100000` / `0x18000100` etc.: **ZERO hits for every PCIE2 absolute**. 2 hits for `0x18000000` only (literal pool). Fw uses base+offset pattern throughout; no absolute-address immediate grep will resolve this.
3. ✓ T283 arithmetic re-verified (see `phase6/t283_mbm_register_resolution.md` §2): `ldr r3, [r0, #0x254]; ldr r0, [r3, #0x100]` at 0x2890 is solid. **The arithmetic chain holds — only T283's inference about WHAT POINTER lives at +0x258 was wrong.**
4. Updated KEY_FINDINGS with supersessions.
5. Committed + pushed `9c6dbb8`, `7aba816`.

### Open static question for next session

**Who writes sched_ctx+0x258 = 0x18100000 (PCIE2 base)?** T283 assumed fn@0x672e4's literal `0x18000000` (chipcommon) propagated through fn@0x670d8 (scheduler init helper) into sched_ctx+0x258. Runtime falsifies that; the actual store of PCIE2-base into +0x258 happens elsewhere in the chain. Candidates:
- fn@0x670d8 receives MULTIPLE args (not just chipcommon base) and stores them at different sched_ctx offsets. +0x258 may be a different arg.
- Or a different initializer (not fn@0x672e4) stores there.

A quick str.w-wide scan for writes at `#0x258` offset to non-sp register was inconclusive in this session (only stack stores found). Need a fuller disasm pass through fn@0x670d8 and any function that takes sched_ctx as argument. **Task #39** in task list.

### Secondary open question

**Wedge-timing anomaly.** T287b wedged at t+0ms of the 2s poll (earlier than T276/T280/T284's t+90s–120s). No AER/NMI/MCE markers. Hypotheses recorded in task list as #40; diagnose via clean-substrate re-fire after 24h power-off (not today).

### Next test: T288 design (deferred — not designed yet)

Candidates per advisor guidance:
- **T288a — read-only probe of PCIE2 core at {0x100,0x104,0x108,0x168} at each T278 stage.** Same macro pattern as T285 but core=PCIE2 instead of CHIPCOMMON. Purely diagnostic; tells us what BIT_alloc sees at runtime. Low substrate cost (read-only, fast).
- **T288b — write probe: set PCIE2+0x100 bits 0-4 to non-zero during WFI dwell and watch MAILBOXINT/console for a scheduler-wake reaction.** Speculative and risky — do NOT design until T288a data lands.

Do T288a design after a clean-substrate fresh-boot day, OR after the static "who writes +0x258" question is resolved. Either is progress.

---



---

## PRE-TEST.287 (2026-04-24 19:10 BST — **Runtime scheduler-ctx probe. Read TCM[0x62A98 + {0x10,0x18,0x88,0x8c,0x168,0x254,0x258}] at every T284/T285 stage. Resolves T286's static-trace wall.**)

### Hypothesis

T283 static analysis resolved:
- `scheduler_ctx+0x258 = [something]`, copied to `+0x254`.
- `[scheduler_ctx+0x254]+0x100` = BIT_alloc's register read = strongly inferred to be CHIPCOMMON INTSTATUS (0x18000100).
- `scheduler_ctx+0x88 = [scheduler_ctx+0x8c]`, copied by class-0 thunk.

T286 confirmed the scheduler ctx is zero-init BSS at 0x62A98 statically, so we can only resolve the pointer values at RUNTIME.

T287 reads the actual runtime values. Expected discrimination:

| `+0x258` value | `+0x88` value | `+0x168` value | Reading |
|---|---|---|---|
| `0x18000000` (CHIPCOMMON) | `0x18000xxx` or similar | Any | T283 hypothesis fully verified. Pending-events word is at `[+0x88]+0x168` = a chipcommon offset. |
| `0x18000000` | `0x18100000` (PCIE2) or other | Any | Bit-pool is chipcommon but pending-events is a different core. Tells us which. |
| Not MMIO (TCM or 0) | Any | `0x` pattern non-zero | pending-events may be TCM-backed. Host can directly write it. |
| All zeros | All zeros | All zeros | Scheduler ctx hasn't been initialized (class-0 thunk didn't run or crashed silently). Would be unexpected given T255 shows callbacks registered. |
| `+0x18` non-zero | — | — | dispatch_ctx_ptr populated at runtime — T286's chain can be walked further via TCM reads at the dumped pointer values. |

### Design

Code landed. New param `bcm4360_test287_sched_ctx_read`. Helper macro `BCM4360_T287_READ_SCHED(tag)` reads 7 specific offsets in one pr_emerg line. Piggybacks on 5 T284/T285 sites + 4 T278 stage hooks (total 9 readback points).

All reads are `brcmf_pcie_read_ram32` (BAR2 direct TCM access) — independent of BAR0_WINDOW state. No core-switching needed.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test285_chipcommon_read=1 \
    bcm4360_test287_sched_ctx_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.287.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.287.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.287.journalctl.txt
```

All previous readback infrastructure enabled (T284 MBM + T285 CC registers + T287 sched ctx fields) for aligned time-series across the full fw init.

### Substrate note

**Previous fire (T285) was null at T268 pattern.** Before T287 fire, user should do a full cold cycle (shutdown, unplug, wait ≥5 min, SMC reset, plug, boot). T268 pattern suggests substrate drift even despite SMC reset when power-off is short.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test287_sched_ctx_read`; T287 pr_emerg string present.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Substrate**: **longer cold cycle required** (≥5 min power-off per T268/T285 pattern).
6. **Fire log**: all previous readback + new T287 per-stage row.

### Outcome interpretation notes

- If T287 reveals `+0x258 = 0x18000000`, advisor's T283 hypothesis is fully confirmed and T289 (write chipcommon to wake fw) becomes the direct next step.
- If `+0x258` is something else, T283's chipcommon-INTSTATUS claim needs revision — we'd expand T287 to dump more offsets or trace the allocator path.

### Fire expectations

Same envelope as T284/T285 fires (~115-145 s to late-ladder wedge). T287 data lands in first ~3 s after set_active. 9 readback stages × 7 values = 63 data points per fire; all in journal regardless of late-ladder wedge.

---

## POST-TEST.285 (2026-04-24 18:23 BST fire, boot -1 — **NULL FIRE. Host wedged at `test.125: after reset_device return`, ~20 s into insmod — BEFORE any T285/T284 code executes. T268-pattern host-side wedge recurrence. No chipcommon data captured. Retry after longer cold-cycle.**)

### Timeline (from `phase5/logs/test.285.journalctl.txt`, boot -1)

- `18:23:34` insmod starts, `test.188: module_init entry`
- `18:23:36` `brcmf_pcie_register() entry` + `before pci_register_driver`
- `18:23:54` `test.125: buscore_reset entry, ci assigned` (~20 s into insmod, normal probe path)
- `18:23:55` **`test.125: after reset_device return`** — LAST MARKER
- [silent lockup; expected next marker `test.125: after reset, before get_raminfo` never fires]
- `18:23:55` boot ended (watchdog reboot)
- `18:39:10` boot 0 (user cold-cycled)

### What T285 DID NOT settle

- **Zero T285 data captured.** The probe block lives in `brcmf_pcie_download_fw_nvram`, which sits FAR after `buscore_reset`. We never got past buscore_reset → get_raminfo. No chipcommon INTSTATUS/INTMASK/0x168 values collected.
- **T284 MBM readbacks also not collected** for the same reason.

### What T285 DID observe (indirectly)

- **T268's pre-firmware wedge is REPRODUCIBLE**. The `test.125: after reset_device return → get_raminfo` window is a known host-side failure point. Previously observed 2026-04-24 01:33 (T268's fire). Today 2026-04-24 18:23 same marker pattern, same wedge.
- **Substrate was NOT fully clean despite cold cycle with SMC reset**. Boot -2 ran 16:26 → 18:20 (2 hours, likely system idle), then boot -1 started 18:22 (only ~2 min gap). Short power-off window may not have given chip sufficient cool-down. Prior reliable cold cycles in this project (T270-BASELINE, baseline-postcycle) may have had longer power-off durations.

### Code status

- **No T285 code changes required.** T285 code is correct; it just never ran.
- Build at commit `543eaa2` is still valid.
- Fire command unchanged.

### Next-test direction

**Option A (fastest, advisor-unneeded): immediate retry after longer cold cycle.**
- User performs ≥5 min full power-off (unplug preferred, per CLAUDE.md "full cold power cycle (shutdown + ≥60 s + SMC reset)") before retry.
- Re-verify substrate via lspci + lsmod before insmod.
- Fire the exact same T285+T284+T278+T277+T276 combo.
- If host wedges at same `test.125` point again, substrate is genuinely degraded and we escalate to the user.

**Option B: stop for the day; resume later with cooler chip.**
- Session has accumulated ~8 fires since 07:54 BST. Today's n-of-wedges reaches into double digits.
- Tomorrow's fresh chip likely reaches the T285 probe code.

**Option C: static work instead (no substrate cost).**
- Deep-trace wlc-probe r7 setup (the T286 candidate from T283). Would resolve fn@0x2309c's pending-events word absolute address without firing anything.
- Would produce additional info for T287 design even if T285 fires cleanly later.

### Post-fire checklist

- Journal captured: ✓ `phase5/logs/test.285.journalctl.txt` (1077 lines — truncated by early wedge).
- Run output captured: ✓ `phase5/logs/test.285.run.txt` (insmod start only — no "returned" timestamp).
- Null-fire recorded: ✓ this block.
- No KEY_FINDINGS updates needed (no new primary-source data).

---

## PRE-TEST.285 (2026-04-24 17:25 BST — **Chipcommon register read-only probe across T278 stages. Confirm/falsify T283's inference that fw's wake path is chipcommon-side. 3 targeted registers: INTSTATUS (0x100), INTMASK (0x104), 0x168.**)

### Hypothesis

T283 static disasm resolved:
- BIT_alloc reads chipcommon INTSTATUS at `0x18000100`.
- Scheduler ctx links to CHIPCOMMON MMIO base.
- Strong inference: fn@0x2309c's pending-events word is another chipcommon-side register, plausibly at `0x18000168`.

If correct, T285 observations will show:
- INTSTATUS with some bits set at/after set_active (fw has outstanding interrupt bits).
- INTMASK either open (bits 3/4 set = unmasked) or closed (explaining why fw doesn't wake).
- `0x168` matching pattern with INTSTATUS (if it's indeed the pending-events reg for fn@0x2309c).

### Outcome matrix (advisor-framed)

| INTSTATUS @set_active | INTMASK @set_active | 0x168 @set_active | Reading |
|---|---|---|---|
| Non-zero w/ bits 3/4 set | Non-zero w/ bits 3/4 set | Any | Trigger bits ARE set AND unmasked — fw should be wakeable. Something else gating (maybe node linkage timing). Narrow via T286. |
| Non-zero w/ bits 3/4 set | 0 (masked) | Any | **Chipcommon INTMASK is the gate.** T287 writes unmask there; high-value fix. |
| 0 or unrelated bits | Any | Any | Trigger bits NOT in chipcommon. T283 hypothesis wrong; different register entirely. T286 deep wlc-trace becomes next. |
| 0x168 reads != INTSTATUS pattern | — | — | 0x168 isn't the pending-events word. Narrows where it actually is. |
| 0x168 == INTSTATUS | — | — | 0x168 is a mirror/alias. Reading it is free information; not a new target. |

### Design (advisor-approved)

Code landed. Gated behind `bcm4360_test285_chipcommon_read=1`; requires T276+T277+T278+T284.

1. Window-safe helper macro `BCM4360_T285_READ_CC(tag)`:
   ```c
   save BAR0_WINDOW → select_core(CHIPCOMMON) → read 0x100/0x104/0x168 → restore BAR0_WINDOW
   ```
   All 4 operations are in-macro so no caller can forget the restore.
2. Piggybacks on 5 T284 MBM readback sites:
   - pre-write (pre-set_active)
   - post-write (pre-set_active)
   - post-set_active (CRITICAL)
   - post-T276-poll
   - post-T278-initial-dump
3. Plus 4 T278 stage hooks (t+500ms, t+5s, t+30s, t+90s) — the `BCM4360_T278_HOOK` macro extended to call T285 after T284.

Total: 9 chipcommon readback points per fire, each emitting `INTSTATUS / INTMASK / 0x168` plus a `saved_win` sanity value.

READ-ONLY. No writes anywhere. No state mutation.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test285_chipcommon_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.285.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.285.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.285.journalctl.txt
```

T284 stays enabled so MBM time-series + chipcommon time-series line up one-to-one. T279 intentionally OFF (would add MMIO noise; not the question this fire).

### Safety

- Read-only probe. 9 × 3 reads = 27 values. Each operation is microseconds.
- Window save/restore discipline inside macro protects other BAR0 accesses.
- Late-ladder wedge expected same as prior fires — T285 data lands in first ~3 s.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test285_chipcommon_read`; 1 T285 pr_emerg string present (all 9 stages use same format string).
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: needs fresh cold cycle (previous was for T284).
6. **Log attribution**: `saved_win` field in each T285 line = sanity (if it changes unexpectedly, the window restoration isn't working).

### Fire expectations

- Insmod + path to set_active: ~20 s
- T284+T285 reads across 9 stages: ~1 s total
- T238 ladder to wedge: ~90-120 s
- Total ~115-145 s before wedge

T285's diagnostic value lands in the first ~3 s after set_active. If the late-ladder wedge fires, all data is already in the journal.

---

## POST-TEST.284 (2026-04-24 16:16 BST fire, boot -1 — **Multi-finding result: MBM has non-zero default 0x318, pre-set_active writes also silently drop, set_active clears MBM to 0, write-locked at all tested timings. Reconciles with T241 (which was FAIL, not PASS as I'd misremembered). MBM at BAR0+0x4C is not writable on BCM4360 via the upstream-canonical helper.**)

### Timeline (from `phase5/logs/test.284.journalctl.txt`, boot -1)

- `16:16:36` insmod
- `16:16:46` insmod returned
- `16:17:59` chip_attach + fw download + FORCEHT complete (identical path to T278-T280)
- `16:17:59` **T284 pre-write (pre-set_active): `MAILBOXMASK=0x00000318 MAILBOXINT=0x00000000`** ← NON-ZERO default!
- `16:17:59` T284: "calling brcmf_pcie_intr_enable" marker
- `16:17:59` T284: "brcmf_pcie_intr_enable returned" marker (no mid-call wedge)
- `16:17:59` **T284 post-write (pre-set_active): `MAILBOXMASK=0x00000318`** ← unchanged; write of 0xFF0300 silently dropped
- `16:17:59` `brcmf_chip_set_active returned TRUE`
- `16:17:59` **T284 post-set_active: `MAILBOXMASK=0x00000000`** ← set_active cleared it
- `16:17:59` T276 2s poll: identical (si[+0x010]=0x9af88)
- `16:17:59` T284 post-T276-poll: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:17:59` T278 POST-POLL (full): 587 B (identical to T278)
- `16:17:59` T284 post-T278-initial-dump: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:17:59` T279 H2D probes: identical null (no fw response, console unchanged)
- `16:17:59 → 16:18:30` T238 ladder to t+90s with T284 stage readbacks:
  - `t+500ms`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+5s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+30s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+90s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:26:06` boot 0 (cold-cycled by user)

### Reconciliation with T241 (2026-04-23 fire)

Grep of `phase5/logs/test.241.journalctl.txt` shows T241 observed:
- MAILBOXMASK baseline = `0x00000318` (pre-set_active)
- After write 0xDEADBEEF: readback 0x318 (write dropped)
- After write 0 to restore: readback 0x318 (write dropped)
- **RESULT: FAIL** (sentinel-match=0, baseline-zero=0, clear-zero=0)

**My earlier writeups (T280, PRE-TEST.284) claimed "T241 proved MBM writes work pre-set_active". That's WRONG.** T241 was FAIL — writes have been silently dropping at BAR0+0x4C since 2026-04-23. Today's T284 rediscovers that finding plus adds the post-set_active time-series.

Correcting the framing: MBM at BAR0+0x4C is **write-locked on BCM4360 across all tested timings** (pre-set_active T241/T284 FAIL; post-set_active T280 FAIL). 0x318 is a chip default (or set by some pre-attach code we haven't identified). `brcmf_chip_set_active` clears it to 0.

### What T284 settled (factually)

1. **MAILBOXMASK has a non-zero default `0x00000318` at pre-set_active** on a fresh BCM4360 boot. Not 0 as I'd repeatedly claimed.
2. **0x318 decode**: `FN0_0 (0x100) | FN0_1 (0x200) | bits 3+4 (0x018)`. Bits 3/4 may correspond to T273/T274's scheduler-callback flags (pciedngl_isr got flag=0x8 = bit 3; fn@0x1146C candidate = bit 4 = 0x010).
3. **Pre-set_active MBM writes silently fail** (T241 + T284). Register is write-locked even before ARM release.
4. **`brcmf_chip_set_active` clears MBM to 0.** ARM-release side effect. Persistent across all subsequent readbacks (6 post-set_active reads through t+90s all show 0).
5. **Post-set_active MBM writes also silently fail** (T280 + T284 confirm).
6. **Write mechanism (`brcmf_pcie_write_reg32` → `iowrite32` at BAR0+0x4C) is not broken** — it wrote H2D registers fine in T279 (those saw the writes land even if fw didn't respond). MBM specifically is the locked register.
7. **No T85/T96 markers in the T284 journal.** The pre-ARM-release MBM-write code at pcie.c:5411 DID NOT EXECUTE — it's in a code path the T238 early-exit bypasses. So our code never wrote MBM in this run; the 0x318 came from somewhere else (chip default, buscore_reset, or chip_attach internals).

### Decoded bit-level significance

- `0x318 = 0x008 | 0x010 | 0x100 | 0x200`
- Bit 3 (0x008): T274 said pciedngl_isr's scheduler flag is 0x8. Suggestive match.
- Bit 4 (0x010): fn@0x1146C candidate (next sequential bit). Suggestive match.
- Bit 8 (0x100): `BRCMF_PCIE_MB_INT_FN0_0` — HW interrupt for pciedngl_isr.
- Bit 9 (0x200): `BRCMF_PCIE_MB_INT_FN0_1` — HW interrupt for hostready/WLC.

**If bits 3/4 in HW MAILBOXMASK mirror the software scheduler flags, the default 0x318 has EXACTLY the bits needed to wake BOTH pciedngl_isr and fn@0x1146C.** set_active clearing the mask to 0 is what blocks fw from waking. The 0x318 default looks like a chip-level "proper" wake configuration.

### Critical next question

**What does `brcmf_chip_set_active` do that clears MBM, and can we either prevent it or restore MBM after?**

Static analysis angles:
- Trace `brcmf_chip_set_active` → likely writes to ARM CR4 CPUHALT bit → possibly triggers a PCIe2 core reset side-effect that clears MAILBOXMASK.
- Fw's own init code might write MBM back to 0x318 as part of hndrte_add_isr's per-class unmask thunk (T274 hypothesis). Our T284 readings show it doesn't — but maybe the fw's write target isn't BAR0+0x4C (which is the upstream-defined offset). Could be a backplane-side register.

Hardware test angles (next after static, if needed):
- T285: write MBM immediately post-set_active (but BEFORE T276 poll) to see if there's a brief window where writes land.
- T286: write MBM via buscore-prep-addr path (different access mechanism).
- T287: write a different register that might mirror into MBM (BAR0+0x24 INTMASK, chipcommon-side mailbox).

### What T284 did NOT settle

- **What writes 0x318 at boot.** Chip default vs pre-attach code. Need to grep pcie.c + chip.c for any pre-attach MBM writes.
- **Whether there's a writable mirror of MBM** (different BAR0 offset, or backplane register).
- **What specifically in `brcmf_chip_set_active` clears MBM.** Source disasm needed.

### Next-test direction (advisor required before committing)

Three candidates:
- **T283 (static blob disasm)**: was deferred for T284. Now more valuable: find fw's MBM-writer (or evidence that fw uses a different register entirely). Goal: identify the REAL mask register, if different from BAR0+0x4C.
- **T285 (very-early post-set_active write)**: insmod→set_active→IMMEDIATE MBM write before any further code runs. Tests whether clear-by-set_active is immediate or has a settle window.
- **T286 (alternative write path)**: try writing MBM via buscore_prep_addr access or through a different PCIE2 core selection. If the register is backplane-gated, switching backplane window might enable the write.

T283 is highest-info-per-cost (static, no substrate) and has a clear decision tree based on findings.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.284.journalctl.txt` (1450 lines).
- Run output captured: ✓ `phase5/logs/test.284.run.txt`.
- Outcome matrix resolved: ✓ **row 3** ("Resets to 0 at some readback point" — specifically at post-set_active).
- T241 reconciliation complete (corrected my earlier-framing error).
- Ready to commit + push + sync.

---

## PRE-TEST.284 (2026-04-24 16:05 BST — **Move `brcmf_pcie_intr_enable` call to BEFORE `brcmf_chip_set_active`. 8-point MBM readback tracks whether pre-set mask persists through fw init. Potential home-run single-fire test.**)

### Hypothesis

- T241 (pre-set_active): MBM round-trip PASS — write lands.
- T280 (post-set_active): MBM write silently drops — register unresponsive.
- Hypothesis: chip state during `brcmf_chip_set_active` transitions the register from writable to unwritable. A pre-set_active write may either (a) persist into fw runtime (home run — fw wakes), (b) get reset by fw's init (tells us WHEN it resets), or (c) be preserved but produce no wake (mask was not the whole gate; H2D probes next).

### Outcome matrix

| MBM persistence | Console advance past wr_idx=587 | Reading |
|---|---|---|
| Stays `0xFF0300` all 8 reads | **New log at t+500ms or earlier** | **HOME RUN.** Pre-set mask survives; fw wakes. Driver fix: move `brcmf_pcie_intr_enable` before `brcmf_chip_set_active`. |
| Stays `0xFF0300` | No new log | Mask survived but no latched bits to wake. T279 H2D probes will fire productively now — can run in same fire if both enabled. |
| Resets to 0 at some readback point | Any | **Diagnostic gold.** Pinpoints WHEN the reset happens (pre- or post-set_active timestamp). T283 static analysis follows to find the reset writer. |
| Mid-fire wedge with pre-set_active MBM logged | — | Novel wedge: pre-set mask + ARM release trips fw's early ISR into NULL-deref or similar. Fall back to narrow `0x100` in T284b. |

### Design

Code landed. Gated behind `bcm4360_test284_premask_enable=1`; requires T276+T277+T278.

1. After T276 shared_info write (if enabled), BEFORE `brcmf_chip_set_active`:
   - Read MBM ("pre-write (pre-set_active)") — expect 0.
   - `pr_emerg "calling brcmf_pcie_intr_enable (pre-set_active)"` — safety marker.
   - Call `brcmf_pcie_intr_enable(devinfo)` (writes MBM = 0xFF0300).
   - `pr_emerg "brcmf_pcie_intr_enable returned"`.
   - Read MBM ("post-write (pre-set_active)") — expect 0xFF0300 (T241-consistent).
2. `brcmf_chip_set_active` runs.
3. Read MBM ("post-set_active") — CRITICAL persistence check.
4. T276 2 s poll runs (if enabled) — reads si[+0x010], fw_done, mbxint.
5. After T276 poll-end: Read MBM ("post-T276-poll").
6. T277 decode runs (if enabled).
7. T278 POST-POLL full dump runs (if enabled).
8. After T278 initial dump: Read MBM ("post-T278-initial-dump").
9. Ladder runs; at each T278 stage hook (t+500ms, t+5s, t+30s, t+90s): MBM read piggybacks the console delta dump ("stage t+Xs").

Total: 8 MBM readback points across the full init → ladder timeline. `pr_emerg` for each → in journal even on wedge.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.284.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.284.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.284.journalctl.txt
```

T279 also enabled: if mask persists and console doesn't advance on its own, H2D probes run with mask=0xFF0300 → expected to produce MAILBOXINT latch and (hopefully) new fw console content. T280 NOT enabled (redundant — T284 already opens mask earlier).

### Safety (advisor-flagged)

Pre-set mask + ARM release is a new state in this harness. Two specific wedge paths:
- Fw's ISR fires immediately on ARM release (if any bit was already latched before we wrote the mask); handler may not be fully initialized → NULL deref → fw TRAP.
- ISR handler writes to TCM region we also read → races.

Mitigation: readback markers at each stage give visibility up to wedge point. Pre-set_active MBM log line is already in the journal before ARM release, so any wedge-during-set_active is attributable.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test284_premask_enable`; strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: needs fresh cold cycle (previous was for T280 fire).
6. **Log attribution**: pre/post-call markers discriminate mid-call wedge from later wedges.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT: ~20 s
- T276 shared_info write: ~50 ms
- T284 pre-write / intr_enable / post-write: ~10 ms
- brcmf_chip_set_active + post-set_active read: ~100 ms
- T276 2s poll + T277 + T278 initial dump + post-T278 read: ~3 s
- T279 H2D probes: ~250 ms
- T238 ladder with 4 more MBM reads + potential wake: variable
- Total: ~25 s before ladder; T238 ladder for 120 s; wedge or clean completion

If HOME RUN (fw wakes), the late-ladder wedge may not happen — fw running normally consumes the ladder differently. Need to watch for that.

---

## POST-TEST.280 (2026-04-24 15:31 BST fire, boot -1 — **MAILBOXMASK write SILENTLY DROPS at post-set_active. `brcmf_pcie_intr_enable` runs cleanly but the register doesn't change. Matrix row 5. Blocks the "unblock mask → wake fw" approach via this register/path/timing.**)

### Timeline (from `phase5/logs/test.280.journalctl.txt`, boot -1)

- `15:31:39` insmod
- `15:31:49` insmod returned
- `15:32:12` chip_attach + fw download + FORCEHT + set_active (identical to T278/T279 path)
- `15:32:12` T276 si[+0x010]=0x0009af88 at t+0ms (identical fw response — consistent across all 4 fires today)
- `15:32:12` T278 POST-POLL (full): 587 B dumped (identical fw console content)
- `15:32:12` **T280: pre-enable `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`** (matches T279)
- `15:32:12` T280: "calling brcmf_pcie_intr_enable" marker
- `15:32:12` T280: "brcmf_pcie_intr_enable returned" marker — **no mid-call wedge; helper completed**
- `15:32:12` **T280: post-enable `MAILBOXMASK=0x00000000` (expected 0xFF0300)** — **WRITE SILENTLY DROPPED**
- `15:32:12` T280: post-enable MAILBOXINT=0 (consistent with mask still closed)
- `15:32:12` T280 post-mask-enable delta: `no new log (wr_idx=587 unchanged)` — fw did NOT wake
- `15:32:12` T280: +100ms MAILBOXINT=0 (no late-arriving signals)
- `15:32:12` T279 ran with MAILBOXMASK still 0: both H2D writes produced `MAILBOXINT=0`, `no new log` — identical to T279 fire
- `15:32:12 → 15:33:33` T238 ladder to `t+90000ms dwell`, then wedge [t+90s, t+120s] (unchanged)
- `15:48:28` boot 0 (user cold-cycled)

### What T280 settled (factually)

1. **`brcmf_pcie_intr_enable` (the upstream-canonical helper) does NOT modify MAILBOXMASK on this chip in the post-set_active state.** Both pre/post markers fired, no wedge; MBM readback shows the register unchanged at 0x00000000.

2. **New class of silent-failure finding.** Unlike prior T258/T259 which WEDGED the host when writing MAILBOXMASK (with different timing — t+120s ladder, plus MSI subscription), T280's MBM write produced zero effect, zero wedge. Either:
   - (a) The write never reached the register (BAR0 access issue at this time / state).
   - (b) The write reached but the register is read-only / write-masked in this state.
   - (c) The write landed briefly, then something reset the register to 0 before readback.

3. **Clean call chain.** `brcmf_pcie_intr_enable` is a 2-line helper that calls `brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxmask, devinfo->reginfo->int_d2h_db | devinfo->reginfo->int_fn0)`. We have no indication `reginfo->mailboxmask` is wrong (it's `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = 0x4C`). The write path is the same one T241 verified passing at pre-set_active.

4. **Pre-latched bits confirmed zero.** `MAILBOXINT=0` both pre and post — fw has NOT pre-latched any H2D bits waiting for the mask to open. Even if we could open the mask, there's nothing currently waiting.

5. **T279 probes re-ran under mask=0 and reproduced T279's null response.** Consistent across fires. No drift in the diagnostic itself.

### What changes between pre-set_active (T241 PASS) and post-set_active (T280 FAIL)?

During `brcmf_chip_set_active`:
- ARM CR4 reset de-asserted (fw starts executing).
- Clock states change (FORCEHT already applied pre-call; other clocks may switch).
- Fw takes ownership of some HW state.

Candidate causes for MBM write silent failure:
- **PCIE2 core in a different reset/clock state after fw runs.** Fw could disable the PCIE2 register block's write enable after init.
- **Backplane window shift.** BAR0 window's mapping could change if fw writes to the BAR0_WINDOW register; pcie.c's `buscore_prep_addr` handles this but only for buscore reads/writes, not for the MBM path which uses a fixed offset into BAR0.
- **ARM-owned bit.** Some PCIe2 registers have ARM-only write access once fw is running — would be a HW design decision not documented.

### Implications

- The whole "host writes MAILBOXMASK to wake fw" approach is blocked at this register/timing/method.
- Prior T258/T259 wedges were probably a DIFFERENT failure mode (MSI-subscription related, which IS gated by time-in-MSI-bound-state per T264-T266). The MBM write itself may also have silently dropped in those runs; we just didn't read back.

### What T280 did NOT settle

- Whether MAILBOXMASK at a DIFFERENT offset works (e.g., BAR0+0xC34 = `BRCMF_PCIE_64_PCIE2REG_MAILBOXMASK` — but that's 64-bit-addressing variant, shouldn't apply to BCM4360).
- Whether the write works via a DIFFERENT access method (buscore prep addr, window-mapped access, direct TCM-shadow write).
- Whether the write works at DIFFERENT timing (pre-set_active via an earlier probe extension; mid-ladder; post-ladder).
- Whether fw's own init ever unmasks (it apparently doesn't, based on T279/T280 readings).

### Next-test direction (advisor required)

Candidates, small-to-large:

- **T282-MBM-WRITE-VARIANTS**: fire with multiple attempted MBM writes at post-set_active time — different values (narrow 0x100 vs full 0xFF0300), different helpers (raw iowrite32 bypassing reginfo, buscore-prepped write), different timings (immediately post-set_active, after a delay). Small, diagnostic-first.

- **T283-FW-MBM-TRACE**: blob disasm for the actual mask-register writes fw's init code performs. If fw writes the mask itself but at a different offset, we know where the "real" mask register is. Static analysis; no substrate cost.

- **T284-PRE-SET-ACTIVE-MBM**: Call `brcmf_pcie_intr_enable` BEFORE `brcmf_chip_set_active`. T241 verified MBM write works at this stage. Open question: does fw's ARM-release clear the mask we just set, or does our pre-set-active mask survive into fw runtime?

T283 is the highest-info-per-cost (pure static, likely reveals the right register). T284 is the highest-payoff-if-it-works (direct fix). T282 is detailed narrowing.

Advisor call before committing to shape.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.280.journalctl.txt` (1467 lines).
- Run output captured: ✓ `phase5/logs/test.280.run.txt`.
- Outcome matrix resolved: ✓ **row 5** ("MBM readback mismatch — write didn't land").
- Ready to commit + push + sync.

---

## PRE-TEST.280 (2026-04-24 15:05 BST — **Host-side MAILBOXMASK unblock. Call brcmf_pcie_intr_enable between T278 dump and T279 H2D probes; see if the mask alone wakes fw or pre-latched bits fire.**)

### Hypothesis

T279 observed MAILBOXMASK=0 — fw's own init did NOT unmask, so no H2D write can propagate. Two candidate explanations:
1. **Mask unmask is supposed to happen, didn't.** If fw set the *software* flag-mask when hndrte_add_isr registered pciedngl_isr and fn@0x1146C (T273/T274 evidence), but never propagated that to the HW MAILBOXMASK register, fw has a "latent ready" state: internal MAILBOXINT would latch an H2D bit, but the ARM never wakes because mask is 0.
2. **Mask unmask requires a host action we haven't made.** Upstream brcmfmac's `brcmf_pcie_intr_enable` writes MAILBOXMASK; fw expects the host to do this.

Both cases: writing MAILBOXMASK ourselves is the discriminator.

Per advisor: if bits were ALREADY pre-latched in MAILBOXINT (waiting for the mask to open), the mask-enable alone will wake fw without any H2D write. This is the highest-value outcome and we lose it if T280 is merged with T279's H2D probes.

### Outcome matrix

| Post-mask-enable delta | Post-mask MBXINT | Post H2D_MBX_1 delta | Post H2D_MBX_0 delta | Reading |
|---|---|---|---|---|
| **New fw log** | Non-zero pre-latched | — | — | **Home run: mask was the sole gate; fw had bits pre-latched; unblocking wakes it.** Driver fix: call `brcmf_pcie_intr_enable` during setup. |
| "no new log" | 0 | New wl/bmac/wl_rte.c log | (bonus) | fn@0x1146C's trigger = H2D_MBX_1 under open mask. Driver fix: mask enable + H2D_MBX_1. |
| "no new log" | 0 | "no new log" | `"pciedngl_isr called"` | Positive control OK; fn@0x1146C's bit is neither H2D_MBX_0 nor H2D_MBX_1. Narrow search (T281b — enumerate other wake mechanisms). |
| "no new log" | 0 | "no new log" | "no new log" | MBM readback will show whether write landed. If landed, mask not gating; deeper issue (INTMASK at 0x24? ARM vector at [0x224]?). Pivot to static analysis. |
| readback mismatch (post MBM ≠ 0xFF0300) | — | — | — | MBM write didn't land. BAR0 write-path issue; prior T241/T243 had MBM round-trip tests — re-check. |
| Mid-call wedge (only "calling brcmf_pcie_intr_enable" marker fires, "returned" does not) | — | — | — | Novel finding: `brcmf_pcie_intr_enable` itself wedges HW under shared_info-present conditions. Prior T258/T259 wedges had no shared_info. New class of wedge; fall back to raw write of narrower mask in T280b. |

### Design

Code landed. Gated on `bcm4360_test280_mask_enable=1`; requires T276+T277+T278.

1. Read MAILBOXMASK (expect 0 per T279). Log.
2. Read MAILBOXINT (expect 0). Log — shows any pre-latched bits.
3. `pr_emerg "calling brcmf_pcie_intr_enable"` — safety marker for mid-call wedge attribution.
4. Call `brcmf_pcie_intr_enable(devinfo)` (upstream helper — writes int_d2h_db | int_fn0 = 0xFF0300 to MAILBOXMASK).
5. `pr_emerg "returned"` — confirms call didn't wedge.
6. Read MAILBOXMASK (verify 0xFF0300). Log.
7. Read MAILBOXINT (check for pre-latched bits). Log.
8. msleep(100).
9. T278 delta console dump — **critical observation: did mask enable alone wake fw?**
10. Read MAILBOXINT again (log any late-arriving signals).
11. If `bcm4360_test279_mbx_probe=1` also set: T279's H2D probes run AFTER this block.

NO MSI, NO request_irq, NO hostready call. All orthogonal to the mask question.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test280_mask_enable=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.280.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.280.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.280.journalctl.txt
```

Both T279 and T280 enabled so one fire discriminates all matrix outcomes.

### Safety

- Prior T258/T259 wrote MAILBOXMASK via the same helper and wedged host. Those runs lacked shared_info; T280 has shared_info + console + pre-write log marker. That's a real conditions delta but not a guarantee.
- Pre-log marker `"calling brcmf_pcie_intr_enable"` + post-log `"returned"` discriminates "wedge during MMIO write" from "wedge during subsequent probe reads" from "wedge during H2D write" from "wedge much later in ladder".
- Expect wedge. Budget one cold cycle per fire.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test280_mask_enable`; 6 T280 strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since ~14:55 BST (~10 min, inside T270's 20-min clean window). **Recommended: fresh cold cycle before fire** for cleanest read.
6. **Log attribution markers**: pre/post-call `pr_emerg` lines make wedge-location diagnosable.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT + set_active: ~20 s
- T276 2s poll + T277 decode + T278 full dump: ~3 s
- T280 mask-enable + 100 ms dwell + delta dump: ~150 ms
- T279 H2D probes: ~250 ms
- T238 ladder to wedge: ~90-120 s
- Total: ~115-145 s before wedge

T280's diagnostic lands in the first ~3.2 seconds after set_active. Wedge after that still leaves all diagnostic data in the journal.

---

## POST-TEST.279 (2026-04-24 13:51 BST fire, boot -1 — **Decisive finding: `MAILBOXMASK = 0x00000000`. Both H2D mailbox writes landed with zero MAILBOXINT response and zero new console content. Advisor's sanity check identified the root cause: fw's mask blocks any wake interrupt. Major reframe.**)

### Timeline (from `phase5/logs/test.279.journalctl.txt`, boot -1)

- `13:51:22` insmod
- `13:51:32` insmod returned
- `13:51:55` chip_attach + fw download + FORCEHT + set_active complete
- `13:51:55` T276 si[+0x010]=0x0009af88 at t+0ms (identical to T276/T277/T278 — fw response is stable across runs)
- `13:51:55` T278 POST-POLL (full): wr_idx=587, 5 chunks dumped (identical 587 B fw console content as T278)
- `13:51:55` **T279: pre-probe `MAILBOXMASK = 0x00000000` (0 = all fw ints masked)**
- `13:51:55` T279: writing `H2D_MAILBOX_1 = 1` (hypothesis: fn@0x1146C trigger?)
- `13:51:55` **Post-H2D_MBX_1 (+100ms): `MAILBOXINT = 0x00000000`** (D2H mirror stayed 0)
- `13:51:55` **T278 POST-H2D_MBX_1 (+100ms): `no new log (wr_idx=587 unchanged)`**
- `13:51:55` T279: writing `H2D_MAILBOX_0 = 1` (positive control: pciedngl_isr)
- `13:51:55` **Post-H2D_MBX_0 (+100ms): `MAILBOXINT = 0x00000000`** (D2H mirror stayed 0)
- `13:51:55` **T278 POST-H2D_MBX_0 (+100ms): `no new log (wr_idx=587 unchanged)`**
- `13:51:55 → 13:53:15` T238 ladder runs t+100ms → t+90000ms (22 markers; standard wedge window at [t+90s, t+120s])
- `13:53:15` boot ended (late-ladder wedge → watchdog reboot)

### What T279 settled (factually)

1. **`MAILBOXMASK = 0x00000000` in Phase 5's fw state.** All fw-side mailbox interrupt bits are masked. First time this has been primary-source measured.

2. **Both H2D_MAILBOX writes landed but produced NO MAILBOXINT latch.** `H2D_MBX_1=1` and `H2D_MBX_0=1` are both valid writes (the register addresses are known to work per pcie.c constants + prior T240 attempts); fw saw them; fw's mask kept them from propagating to the ARM interrupt line.

3. **Fw console stayed at `wr_idx=587`.** No fw code ran in the 100 ms windows — not fn@0x113b4 (which would produce printf output per T281), not pciedngl_isr (which would produce `"pciedngl_isr called"` per T274 blob analysis). This confirms fw's ARM is in WFI and the mailbox writes did not wake it.

4. **Positive control failed as expected under MAILBOXMASK=0.** H2D_MBX_0 is the **known-good** path for pciedngl_isr per T274, but with MAILBOXMASK=0 even this known-good path is silent. The observation pipeline (console + delta cursor + pr_emerg) is NOT broken; the wake path is.

5. **Late-ladder wedge unchanged** (orthogonal).

### The reframe

Prior assumption: fn@0x1146C's trigger is an unknown specific bit; T279 would identify it. Result: ANY bit we might write is blocked by MAILBOXMASK=0 before it reaches fw. Therefore:

- The question "which bit triggers fn@0x1146C" is moot until the mask is opened.
- The question BECOMES: "why is MAILBOXMASK=0, and what happens if we open it ourselves?"

### What this tells us about fw init

- T274's analysis of hndrte_add_isr said it "dispatches a class-specific unmask via a 9-entry thunk vector". The thunks (0x27EC region) should unmask the relevant MAILBOXINT bit for each registered ISR.
- pciedngl_isr was registered (T255/T274 confirmed). But MAILBOXMASK=0 at our observation point means **either (a) the unmask didn't happen, (b) it happened to a different register, or (c) it was reset somehow.**
- Prior framing: "fn@0x1146C waits for a trigger that never fires." True but the reason it never fires is a STEP EARLIER — fw's own init didn't unmask the interrupt line that would carry the trigger.

This changes the investigation direction. Possible causes for the mask being 0:
1. **Something resets MAILBOXMASK** after fw's init (PCIe link state, ARM reset, clock gate reset). Unlikely but possible.
2. **hndrte_add_isr's unmask thunk writes to a different register** (not BAR0 PCIE2REG_MAILBOXMASK but perhaps a backplane-side register, or the INTMASK at BAR0+0x24).
3. **Fw DOES unmask, but only after some further init step we haven't passed.** The unmask might be gated on a condition we haven't satisfied (e.g., host must set a specific register first to indicate readiness).
4. **MAILBOXMASK gets reset on entry to WFI** (unlikely; masks are typically persistent).

### Next-test direction (T280 candidate)

**T280 — Set MAILBOXMASK ourselves and re-probe**: After T279's zero-response observation, write `MAILBOXMASK = 0x300` (enables FN0_0 + FN0_1 per upstream brcmfmac convention), then re-run the T279 sequence. Three outcomes:

| T280 outcome | Reading | Follow-up |
|---|---|---|
| H2D_MBX_0=1 → fw logs `"pciedngl_isr called"` AND MAILBOXINT shows 0x100 latched | **Host-side mask unblocking works.** Fw's init path didn't unmask but host CAN do it. Test H2D_MBX_1 next; follow wherever it leads. | Stage a "patch: enable mailboxes post-set_active" and test if fw completes init naturally. |
| H2D writes still produce 0 MAILBOXINT | Either MAILBOXMASK write didn't land (read back to verify) OR H2D writes don't latch regardless of mask. Deeper issue. | Read MAILBOXMASK after writing; investigate BAR0 write-path (prior T241/T243 had MBM round-trip tests). |
| Host wedges on MAILBOXMASK write | Same wedge mode T258-T269 hit. Observation: those lacked shared_info; T280 has it. If still wedges, MAILBOXMASK write itself is toxic on this HW. | Fall back to INTMASK (BAR0+0x24) instead of MAILBOXMASK, or a different approach. |

Safety: prior MAILBOXMASK-write scaffolds wedged host. T280 adds observability (T278 console + T279 MAILBOXINT reads) BEFORE the mailbox write, so even if the MAILBOXMASK write itself wedges, we have pre-wedge state captured. Also prior scaffolds wrote 0xFF0300; T280 should try a narrower 0x300 first.

Alternative T280b: **Pre-write mask-enable EARLIER, before set_active**, so fw observes it during init. Might influence fw's behavior differently than a post-init override.

Advisor call before committing to T280's exact shape.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.279.journalctl.txt` (1447 lines).
- Run output captured: ✓ `phase5/logs/test.279.run.txt` (3 lines — fire/insmod/return).
- Outcome matrix resolved: ✓ row 3 ("No new log on either probe") — with root cause identified: MAILBOXMASK=0.
- Ready to commit + push + sync.

---

## PRE-TEST.279 (2026-04-24 13:30 BST — **Directed mailbox probe. H2D_MBX_1 hypothesis + H2D_MBX_0 positive control, console observation between. Single fire.**)

### Hypothesis

T278 confirmed fw enters silent WFI after wl_probe registers `fn@0x1146C` as a scheduler callback. T281 static analysis showed the callback dispatcher reads a HW-mapped pending-events word and fires fn@0x113b4 (which contains `printf` + `printf/assert`) when a matching bit is set.

Two candidate writes:
1. **H2D_MAILBOX_1=1** (BAR0 + 0x144): upstream's "hostready" signal. If this is fn@0x1146C's trigger, fw will log (from fn@0x113b4's printf chain) within ~100 ms.
2. **H2D_MAILBOX_0=1** (BAR0 + 0x140): known-positive control — fw's MAILBOXINT.FN0_0 (bit 0x100) latches → fires pciedngl_isr per T274. Fw's pciedngl_isr logs `"pciedngl_isr called"` (string at blob 0x40685).

### Outcome matrix

| H2D_MBX_1 console delta | H2D_MBX_0 console delta | Reading |
|---|---|---|
| New log w/ `wl` / `bmac` / `intr` / `wl_rte.c` strings | any | **Home run.** fn@0x1146C's trigger = H2D_MBX_1. |
| `"no new log"` | `"pciedngl_isr called"` or similar | Positive control confirmed; fn@0x1146C needs something else. T280 narrows (MAILBOXMASK bit enable? different H2D register?). |
| `"no new log"` | `"no new log"` | Either observation path broken, MAILBOXMASK=0 keeps fw masked, OR fw doesn't latch on H2D at all. Decode from MAILBOXMASK pre-probe value + any post-MAILBOXINT change. |
| New log on BOTH probes | — | Multi-bit response; both triggers valid. |
| Host wedges on H2D_MBX_1 | — | MMIO-write wedge independent of MSI; new finding. Prior-probe console delta still captured if it fired before wedge. |
| Host wedges on H2D_MBX_0 | — | Wedge is specific to pciedngl_isr path (MSI-orthogonal). |

### Design

Code landed (see previous commit). Runs in `brcmf_pcie_download_fw_nvram`'s post-set_active block, AFTER T276 2s poll + T277 struct decode + T278 initial full dump:

1. Read `MAILBOXMASK` (sanity check — if 0, fw has everything masked).
2. Write `H2D_MAILBOX_1 = 1`.
3. `msleep(100)`.
4. Read `MAILBOXINT` (D2H mirror — non-zero means fw signalled back).
5. T278 delta console dump.
6. Write `H2D_MAILBOX_0 = 1`.
7. `msleep(100)`.
8. Read `MAILBOXINT`.
9. T278 delta console dump.

No MSI, no request_irq — per T264-T266, host-side MSI subscription is the wedge trigger, not the write itself.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.279.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.279.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.279.journalctl.txt
```

### Safety

- Same envelope as T276/T277/T278 + 2 mailbox writes + 200 ms added dwell.
- No MSI subscription (orthogonal to T264-T266 wedge).
- Platform watchdog expected to recover late-ladder wedge.
- H2D writes without prior MSI setup HAVE NEVER been fired in Phase 5 — they could trigger a novel wedge mode, but the T258-T269 scaffolds wrote H2D without shared_info present; T279 has shared_info in place, matching Phase 4B's Test.28 conditions more closely.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test279_mbx_probe`; 6 T279 strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (committing before fire).
5. **Host state**: boot 0 up since 13:04 BST (~30 min old; past T270's 20 min clean window).
6. **Recommendation**: **cold cycle before fire** for cleanest substrate; the two mailbox writes are a new stress pattern.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT + set_active: ~20 s
- T276 2 s poll + T277 decode + T278 full dump + T279 probe sequence: ~3 s
- T238 ladder to crash: ~90-120 s
- Total: ~115-145 s before wedge

T279's diagnostic value lands in the first 3 seconds after set_active. Even if the host wedges during or after the probes, the console delta dumps will already be in the journal.

---

## POST-TEST.278 (2026-04-24 12:50 BST fire, boot -1 — **Full 587 B fw console captured; all 4 stage hooks report silence. Matrix row 1: fw logs only during first ~2s. Primary-source confirmation of T257's WFI reading. Hang bracket refined to inside wl_probe.**)

### Timeline (from `phase5/logs/test.278.journalctl.txt`, boot -1)

- `12:50:54` insmod fire (post cold-cycle)
- `12:51:04` insmod returned (10 s)
- `12:51:19` chip_attach + fw download + NVRAM + FORCEHT + set_active complete
- `12:51:19` T276 si[+0x010]=0x0009af88 at t+0ms (same response as T276/T277)
- `12:51:19` T278 **POST-POLL (full) wr_idx=587 prev=0 delta=587 dumping=587 bytes** across 5 chunks (128+128+128+128+75 B)
- `12:51:19` T278 t+500ms: `no new log (wr_idx=587 unchanged)`
- `12:51:21` T278 t+5s: `no new log (wr_idx=587 unchanged)`
- `12:51:47` T278 t+30s: `no new log (wr_idx=587 unchanged)`
- `12:52:48` T278 t+90s: `no new log (wr_idx=587 unchanged)`
- [wedge in [t+90s, t+120s]; boot ended 12:52:48]

### Reassembled fw console (full 587 B)

```
Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
125888.000 
RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz
125888.000 pciedngl_probe called
125888.000 Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
125888.000 wl_probe called
125888.000 Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
```

### What T278 settled (factually)

1. **Fw reaches `wl_probe` (WLC device probe = T273's `fn@0x67614`).** Primary-source confirmation. Earlier indirect evidence (scheduler callback registered for `fn@0x1146C`) suggested this; T278's log text makes it direct.

2. **Fw reaches `pciedngl_probe`** and completes it (advances past into wl_probe). Confirms T274's finding that pcidongle_probe's body runs through without hangs.

3. **Fw completes `si_kattach`** before RTE banner is printed. Kernel-attach stage done; chipcommon register access is working.

4. **Watchdog tick = 32 ms** (`wd_msticks = 32` from `si_kattach` log). New primary-source timing fact. Relevant for future analysis of fw-side watchdog behaviour.

5. **RTE banner**: `"RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz"`. Clock rates 40 MHz XTAL / 160 MHz backplane / 160 MHz ARM CPU, consistent with chipst 0x9a4d decode.

6. **Fw goes silent after wl_probe's initial chipc dump.** No subsequent log output across the full dwell ladder — t+500ms through t+90s all show `wr_idx=587 unchanged`.

7. **T257's WFI reading is now primary-source confirmed.** The scheduler isn't busy-looping (would produce log entries over time); fw isn't asserting (no "ASSERT" / "TRAP" / "PC=" strings); fw isn't timing out (no watchdog print despite 32 ms tick). The silence is consistent only with "scheduler idle via WFI, waiting for an event".

8. **No fw-side self-diagnosis string.** Fw doesn't self-identify a missing input. Unlike many embedded systems that print "waiting for X" or "timeout on Y", this fw just returns to scheduler and idles. Means we can't learn the missing trigger from the log alone — we have to either disasm the wl_probe tail (T273 territory) or induce triggers on hardware (T279 territory).

### Hang bracket — tightened to wl_probe's tail

Prior reading (from T272-FW / T273-FW): "hang is somewhere in wl_probe's tail, inside sub-functions we haven't fully traced."

T278 refines: wl_probe PRINTS "wl_probe called" → "Found chip type AI" → "Chipc: rev 43..." then goes quiet. There are two orderings for the quiet region:

- **(A)** wl_probe's sub-calls (including `hndrte_add_isr(fn@0x1146C, ...)`) do NOT log. They just complete their work (registrations, init) and wl_probe returns. Scheduler sees no runnable events → WFI.
- **(B)** wl_probe enters an inner sub-call that is silent AND happens to never return (a HW-dependent stall that the T273/T274 disasm failed to identify).

T257's WFI-via-scheduler-state finding favours (A): the scheduler's frozen node state means RTE's scheduler is running idle, which only happens after all probes return. (B) would leave wl_probe mid-execution on the call stack — scheduler wouldn't be reached.

**Conclusion: wl_probe completes normally (no assert, no hang). Fw reaches the scheduler idle state and WFI-waits for `fn@0x1146C`'s callback trigger, which never fires in our test harness.**

### What T278 did NOT settle

- **What trigger fn@0x1146C is waiting on.** T273 identified the callback registration but the specific MAILBOXINT bit / HW event / host action that fires it is unknown.
- Why Test.28 saw MAILBOXINT=0x3 in Phase 4B harness but T276/T277/T278 see 0 under Phase 5 patches. The console log suggests fw does not self-initiate mailbox signals during init; Test.28's signals may have been host-driven by Phase 4B harness writing something we don't.
- Whether writing to a specific MAILBOXINT bit in the scheduler's pending-events word would wake fn@0x1146C. T274 looked for writers of this word and found none — suggesting the bit IS HW-mapped and requires a PCIe-side action, not a TCM write.

### Next-test direction (advisor required)

Candidates:

- **T279-MBXINT-PROBE**: With T278 periodic console running, fire a single MAILBOXINT write (e.g., bit 0x1 = FN0_0 = pciedngl_isr trigger; or bit 0x2; or H2D_MAILBOX_0) AFTER set_active + T276 poll, and watch the console for fw response. Observable: if fw logs `"pciedngl_isr called"` (string at blob 0x40685 per T274 analysis), we've confirmed the FN0_0 mapping AND woken up fw partially. Safety concern: prior scaffolds (T258-T269) that wrote MAILBOXINT without console access all wedged the host; now with console readable via T278, we can observe even a short fw activity before any wedge.

- **T280-MBXMASK-WIDE-POLL**: Still observation-only. Read not just `MAILBOXINT` but also `MAILBOXMASK`, `H2D_MAILBOX_0/1/2`, `D2H_MAILBOX_0/1/2` during the T278 stages. Discriminates whether any of these registers change passively across the ladder. Low-risk, low-reward — probably all zero.

- **T281-POKE-FN1146C**: Blob-disasm fn@0x1146C more carefully to identify the specific flag bit or event it responds to. Static analysis, no fire. Could make T279's write target specific rather than guessed.

Highest-value-per-fire: **T279** (console-observed mailbox poke). Safest: **T281** (static). Between them, probably T281 first (cheap, directed), then T279 (directed fire) after.

### Safety + substrate

- T278 ran the same ~150 s envelope as T270-BASELINE. Late-ladder wedge consumed one cold-cycle substrate budget.
- Current boot 0 is post-T278-wedge cold cycle (user performed SMC reset). Clean substrate available for next fire.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.278.journalctl.txt` (1449 lines).
- Run output captured: ✓ `phase5/logs/test.278.run.txt`.
- Outcome matrix resolved: ✓ **row 1** ("Fw logged ONLY during first ~2s; silence across all 4 stage hooks").
- Full fw console reassembled above; key facts extracted.
- Ready to commit + push + sync.

---

## PRE-TEST.278 (2026-04-24 12:10 BST — **Periodic console dump across the dwell ladder. Post-poll full dump + deltas at t+500ms, t+5s, t+30s, t+90s. Single fire, combined axes per advisor.**)

### Hypothesis

T277 captured the first 128 B of 587 B fw wrote at ~t+2s post-set_active. Three questions remain open:

1. **What's in bytes 128..587?** (near-certain: more chipc decode / init messages; potentially assertions)
2. **Does fw continue logging past t+2s?** If yes, we see what fw does during the dwell ladder (up to the late-ladder wedge).
3. **Is there a log entry around t+90s just before the wedge?** If yes, that's likely the decisive diagnostic.

T278 answers all three in one fire: post-poll seeds the delta cursor with prev=0 so the first call dumps the full current window; then 4 per-stage hooks dump deltas at t+500ms, t+5s, t+30s, t+90s.

### Outcome matrix

| Observation | Interpretation | Follow-up |
|---|---|---|
| Post-poll dumps full 587 B; stage hooks all "no new log (wr_idx=587 unchanged)" | Fw logged ONLY during the first ~2 s post-set_active. It went quiet for the rest of the ladder — consistent with WFI per T257. Log content from bytes 128..587 may still reveal the init end-state. | Decode bytes 128..587 for assert/trap strings; decide if further FW wake-up is needed. |
| Post-poll dumps 587 B; t+5s/t+30s deltas non-zero | Fw keeps logging during early ladder but stops before t+30s. | Content of each delta tells us what fw logged and when. |
| Post-poll dumps 587 B; t+90s delta non-zero | **Fw logs right before the late-ladder wedge.** Highest-value. The t+90s delta content is the most likely to explain the wedge mechanism (assert, timeout, state dump). | Decode carefully. Could redirect the investigation immediately. |
| Post-poll: struct becomes invalid between T277 capture and T278 read | Struct moved or got corrupted. Unlikely but the validator catches it. | Log shows reason; rethink. |
| Some t+Xs delta contains known Broadcom trap string (`"ASSERT"`, `"TRAP"`, `"PC=0x"`) | **Smoking gun.** Fw self-reported a trap/assert. | Decode trap location against blob disasm; likely points to the exact fw state when wedge fires. |

### Design

Code landed; gated behind `bcm4360_test278_console_periodic=1` (requires `test276 + test277`). Helper function `bcm4360_t278_dump_console_delta` does all work:

- Re-reads struct at `si[+0x010]` pointer (not hardcoded — robust to any offset change).
- Validates `buf_addr / buf_size / write_idx` against `devinfo->ci->ramsize`.
- Tracks delta via `devinfo->t278_prev_write_idx` (struct field, lifetime = devinfo).
- Dumps in 128 B chunks with `%*pE` ASCII escape; hard cap at 1024 B per call to avoid printk truncation.
- Prints `"no new log"` on empty delta (silence is data).

Per-stage hooks use a small macro `BCM4360_T278_HOOK(tag)` inlined next to the 4 dwell pr_emerg lines.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.278.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.278.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.278.journalctl.txt
```

### Substrate note

Current boot 0 is post-T277 recovery. Like PRE-TEST.277 noted, a fresh cold cycle before fire keeps results substrate-clean. **Recommended: cold cycle before T278 fire.**

### Expected artifacts

- `phase5/logs/test.278.run.txt`
- `phase5/logs/test.278.journalctl.txt`

### Safety

- Same envelope as T276/T277 (existing shared_info write + DMA alloc + reads only).
- 4 additional reads + ~4×(4+32)=144 read_ram32 calls during ladder (~2 ms added per stage — well under dwell granularity).
- Platform watchdog expected to recover late-ladder wedge.

### Pre-test checklist

1. **Build**: ✓ committed once we push (next); modinfo shows `bcm4360_test278_console_periodic`; 8 T278 pr_emerg strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since ~12:02 BST (~10 min — inside T270-BASELINE's 20 min clean window, but consumed by T277 fire and recovery).
6. **Recommendation**: cold cycle before fire (user-initiated).

### Fire expectations

~150 s total run time (same as T270-BASELINE / T276 / T277). Expected to wedge in [t+90s, t+120s] (orthogonal to T278). T278's diagnostic value lies in what the logs contain, not whether the ladder completes.

---

## POST-TEST.277 (2026-04-24 11:55 BST fire, boot -1 — **Fw's live console captured: 587 B of fw-written log at TCM[0x96f78]. `buf_addr/size/wr_idx/rd_addr` struct layout Phase 4B proposed is CONFIRMED. Console is a real ring with timestamps. First 128 B decoded — rest unread (extend in T278).**)

### Timeline (from `phase5/logs/test.277.journalctl.txt`, boot -1)

- `11:55:14` insmod fire (post cold-cycle)
- `11:55:34` fw download + NVRAM + FORCEHT complete (20 s into fire)
- `11:55:34` **T277 PRE-WRITE struct@0x9af88**: `buf_addr=0xad9afa8b buf_size=0x02d5bf1b write_idx=0x5370158c read_addr=0x23535c0b` — ALL GARBAGE (uninitialized memory, struct not yet populated)
- `11:55:34` T276 shared_info written at TCM[0x9d0a4] (olmsg_dma=0x89b10000, all 6 fields verified)
- `11:55:34` `brcmf_chip_set_active returned TRUE`
- `11:55:34` T276 t+0ms: `si[+0x010]=0x0009af88 fw_done=0 mbxint=0` (same response as T276)
- `11:55:37` T276 poll-end: unchanged
- `11:55:37` **T277 POST-POLL struct@0x0009af88**: `buf_addr=0x00096f78 buf_size=0x00004000 write_idx=0x0000024b read_addr=0x00096f78` — **ALL FIELDS VALID TCM ADDRESSES**
- `11:55:37` **T277 buffer@0x00096f78 (first 128 B) ASCII**: `"Found chip type AI (0x15034360)\r\n125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11\r\n125888."`
- `11:55:37 → 11:57:08` T238 ladder: t+100ms → ... → t+90000ms dwell (22 markers, same pattern as T276/T270-BASELINE)
- `11:57:08` **LAST MARKER: `t+90000ms dwell`** — wedge in [t+90s, t+120s]
- `12:02:28` boot 0 (user cold-cycled during recovery)

### What T277 settled (factually)

1. **Phase 4B's struct layout interpretation is CONFIRMED.** 4 dwords at fw-published pointer = `{buf_addr, buf_size, write_idx, read_addr}`. All four fields make internal sense: buf_addr and read_addr both point to 0x96f78 (ring's fresh-read state — nothing consumed yet); buf_size is a plausible 16 KB ring size; write_idx is plausible <buf_size.

2. **Fw DOES populate the struct during post-set_active init.** Pre-write struct at 0x9af88 was uninitialized garbage; post-poll it's fully populated with valid values. Row 1 of the pre/post matrix ("struct populated by fw during post-set_active init") — CONFIRMED.

3. **Fw writes real log content during init.** 587 bytes of genuine ASCII text including:
   - chip identification: `"Found chip type AI (0x15034360)"` (AI = AXI Interconnect — matches Phase 4's chip architecture observations)
   - timestamped register dump: `"125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"`
   - Second timestamp `125888.` starts at byte 128 (our dump cuts mid-line)

4. **The timestamp unit is an open question.** `125888.000` appears at the first log line — too large for microseconds-since-boot, too large for milliseconds. Possibilities: PMU free-running counter value (chipc has one); arbitrary tick counter; or the buffer isn't starting at position 0 of the boot sequence. Not load-bearing for the next-step decisions.

5. **Buffer has NOT wrapped.** write_idx = 0x24b = 587 bytes << buf_size = 16 KB. read_addr = buf_addr = no host has consumed any entries. A dump of `buf_addr..buf_addr+write_idx` captures the full fw log so far.

6. **Late-ladder wedge unchanged.** Same `t+90000ms` last marker as T270-BASELINE and T276. T277 is pure read-only; doesn't affect the wedge mechanism.

### What T277 did NOT settle

- **What's in bytes 128..587** of fw's console. Our 128 B dump cuts mid-line (second `125888.` timestamp truncates). The remaining 459 bytes likely contain more register dumps, init-phase messages, and may contain the decisive clue about where/why fw enters WFI. **This is the T278 target.**
- Whether fw writes MORE log content during the ladder (t+100ms → t+90s window). The 587-byte snapshot is from ~2 s post-set_active; if fw continues to log during the ladder, periodic reads would catch that.
- What `0x00096f78` as `buf_addr` means in the TCM layout. It's 0x9af88 - 0x96f78 = 0x4010 below the console struct; 16 KB ring stops at 0x96f78 + 0x4000 = 0x9af78, which is 0x10 below the struct at 0x9af88. So the buffer is contiguous: `[0x96f78 .. 0x9af78)` then a 16 B gap, then the struct at 0x9af88. Neat layout.

### Decoded chip-identity from fw's log (cross-check)

Fw reports: chip type AI, `0x15034360` (full chip ID with rev/pkg bits), Chipc rev 43, caps `0x58680001`, chipst `0x9a4d`, pmurev 17, pmucaps `0x10a22b11`.

Cross-ref with Phase 4 identity from Python probe scripts + T252: chip 4360 / rev 3 / pkg 0, so `0x15034360` decoded = `0x1500_4360 | (rev 3 << 16) | (pkg 0 << 28)`. Consistent. The `0x58680001 ` Chipc caps + `0x9a4d` chipst haven't been recorded in our prior probes — new primary-source facts from fw itself, worth saving.

### Next-test direction

T278-CONSOLE-EXTENDED — two-axis extension of T277:

1. **Dump size**: use `min(write_idx, 4096)` (or even the full `buf_size` for completeness) in post-poll. Captures the entire current log, not just the first 128 B. Multiple pr_emerg lines with 128 B chunks per line (kernel printk line length limits). Expected payoff: **full fw init log** in one fire.

2. **Periodic reads during dwell ladder**: at t+500ms, t+5s, t+30s, t+60s, t+90s — re-read struct + dump newly-written region (bytes `write_idx_prev..write_idx_current`). If write_idx advances, we see what fw logs during the ladder and — critically — may see what fw logs right before the wedge.

Two independent axes; combine into one test or separate into T278+T279. Advisor call on which to prefer.

### What opens up

If fw keeps writing to the console, we have a primary-source channel for fw internal state that didn't exist before. Examples of things we could now learn:

- What init phase fw reaches (specific function/subsystem names in log lines).
- Whether fw self-reports ASSERT/TRAP messages (these are usually verbose in Broadcom fw).
- When (and whether) fw tries to read something from shared_info that we haven't provided.
- When fw transitions from init to "ready" state (if ever).

This is potentially the biggest lever we've had in Phase 5. Progress it carefully.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.277.journalctl.txt` (1436 lines).
- Run output captured: ✓ `phase5/logs/test.277.run.txt`.
- Pre/post matrix resolved: ✓ row 1 ("struct populated by fw during post-set_active init").
- Buffer matrix resolved: ✓ row 1 ("readable log text").
- Ready to commit + push + sync.

---

## PRE-TEST.277 (2026-04-24 11:18 BST — **Console-struct decode at the pointer T276 captured. Two-point read (pre-write + post-poll) + 128 B ASCII-escaped buffer dump. Advisor-approved.**)

### Hypothesis

T276 showed fw responds at shared_info[+0x010] with `0x0009af88` — a TCM address Phase 4B called a "console struct pointer". Phase 4B's interpretation is 4 dwords: `{buf_addr, buf_size, write_idx, read_addr}`. T277 tests the interpretation AND extracts whatever log text the buffer contains.

Two-point read discriminates three possibilities for how the struct exists:

| Pre-write struct | Post-poll struct | Reading |
|---|---|---|
| all zeros | populated (non-zero fields) | **Struct populated by fw during post-set_active init** (expected interpretation). |
| populated | identical | **Struct pre-existed in fw image**; post-set_active fw just copied the pointer to si[+0x010]. |
| populated | `write_idx` advanced (others unchanged) | **Fw is actively logging in our 2 s poll window.** Highest-value: the buffer is a live ring and our dump has fresh content. |
| garbage both | — | Struct offset is not at 0x9af88 in this layout; interpretation needs revising. |

### Outcome matrix

| Buffer ASCII dump | Reading | Follow-up |
|---|---|---|
| Readable log text (trap strings, printf fragments, `bmac`, `phy`, timing) | **Fw internal log captured.** Content may reveal what fw's doing between set_active and the late-ladder wedge. | Decode trap line; cross-ref with T272-FW init chain. If late-ladder wedge has a fw-side cause, the log will show it in subsequent reads. |
| Readable but only one or two lines, then zeros | Log is young — fw wrote a few lines then went quiet. | Extend dump to larger window (256 B–4 KB); track `write_idx` across ladder dwells. Design T278 around periodic console reads during the dwell ladder. |
| Non-ASCII but structured (fixed-size records, pointers) | Not a text console — maybe a circular message struct (olmsg pre-ring?). | Re-decode as structured records; if records carry fw→host messages, this could be the actual response channel. |
| All zeros or garbage | Struct is not at 0x9af88, OR `buf_addr` points somewhere uninitialized. | Check the struct fields — if buf_addr is 0, fw hasn't assigned one; if buf_addr is non-zero but points to zero bytes, log is genuinely empty (unexpected since fw is supposedly running code). |
| `buf_addr` not in `[0, ramsize)` | Address out of TCM — pointer is a DMA address? A garbage/uninitialized value? Log to confirm. | Don't dereference; add separate check for PCIe BAR / DMA addr interpretation in T278. |

### Design

Code landed alongside T276 (same commit will wrap both). Gated behind `bcm4360_test277_console_decode=1`; requires `bcm4360_test276_shared_info=1` (reads si[+0x010] as the struct pointer).

1. **Pre-shared_info-write**: read 4 dwords at TCM[0x9af88] (Phase 4B's observed pointer — hardcoded only for the pre-write read since fw hasn't published si[+0x010] yet). Logs `buf_addr / buf_size / write_idx / read_addr`.
2. **Post-2s-poll**: read si[+0x010] dynamically; if in `[1, ramsize)` read 4 dwords at that address. Same labels.
3. **If `buf_addr` ∈ (0, ramsize)**: read 128 B (32 dwords) starting at `buf_addr`, print as `%*pE` (ASCII escape) AND `%*ph` (hex). Escape form makes trap/log strings readable; hex form catches control bytes that `%*pE` hides.
4. **If any pointer invalid**: skip the follow, log the value. Safe.

No writes anywhere beyond the existing T276 writes. Pure read-only observation.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.277.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.277.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.277.journalctl.txt
```

### Substrate note (advisor caveat)

Current boot 0 is a watchdog recovery from the T276 crash, NOT a fresh cold cycle. T269 pattern: drift within ~25 min of post-wedge boots. If T277 differs from T276 on the `si[+0x010] = 0x0009af88` anchor value (e.g., 0 post-poll, or a different pointer), drift is a possible confound. Recommended: request cold cycle before T277 fire for cleanest comparison. If firing on current boot, accept and note in POST-T277 that substrate was post-wedge-recovery, not cold-cycle.

### Expected artifacts

- `phase5/logs/test.277.run.txt`
- `phase5/logs/test.277.journalctl.txt`

### Safety

- Same envelope as T276 (existing shared_info write + DMA alloc) + new reads only.
- No new writes, no MSI, no request_irq.
- Host wedge in [t+90s, t+120s] still expected (orthogonal to T277); platform watchdog recovers.

### Pre-test checklist

1. **Build**: pending code commit + build verification (next action).
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since 11:09:35 BST (watchdog-recovered, not cold-cycled).
6. **Recommendation**: cold cycle before fire so result is not substrate-noise-polluted.

---

## PRE-TEST.276 (2026-04-24 10:50 BST, boot 0, substrate stale — **Port Phase 4B test.28's shared_info write into Phase 5; diagnostic observation of fw response under current patches. Not a claimed fix.**)

### Hypothesis

Phase 4B Test.28 (2026-04-13) proved: writing a valid `shared_info` struct at TCM[ramsize-0x2F5C] before ARM release prevents the 100 ms panic AND causes fw to (a) write a non-zero pointer to `shared_info[+0x010]` (observed value `0x0009af88`), and (b) send 2 PCIe mailbox signals (`PCIE_MAILBOXINT` = `0x00000003`).

Phase 5 passes the panic point via NVRAM + random_seed + FORCEHT (different path), but currently makes **zero shared_info writes** (`grep 0xA5A5A5A5 pcie.c` → no matches). Fw enters WFI by ~t+12 ms; scheduler frozen across 23 dwells (T255); sharedram_addr never published (T247).

T276 adds the missing shared_info write. Under Phase 5's patches (fw already past Phase 4B's panic point), does the fw still exhibit Test.28's response pattern, or does the different fw init state (further-along) change what it does?

### Outcome matrix

| Observation | Interpretation | Follow-up |
|---|---|---|
| `si[+0x010]` becomes non-zero AND ≥1 `mbxint` bit set within 2 s | **Test.28 reproduces under Phase 5 patches.** Fw is listening to shared_info even past panic point. Protocol anchor confirmed. | Decode pointer at si[+0x010]; probe referenced TCM region; consider next handshake step (fw_init_done, or olmsg ring poke). |
| Only `mbxint` becomes non-zero (no si[+0x010] update) | Partial response — fw notices handshake but doesn't complete the status-write step Test.28 saw. Fw state is genuinely further than Phase 4B. | Check scheduler state [0x6296C..0x629B4] — does it differ from T255 frozen baseline? Probe WLC-side register writes. |
| Only `si[+0x010]` becomes non-zero (no `mbxint`) | Inverse partial — fw writes status but doesn't signal. Unusual. | Check if fw wrote anywhere else in shared_info region; scan for additional pointer updates. |
| Both stay zero across 2 s | **Test.28 does NOT reproduce under Phase 5 patches.** Protocol model for this fw state needs rethinking. | Verify readbacks (rule out failed writes); compare scheduler state vs T270-BASELINE; reframe based on evidence. |
| `fw_init_done` becomes non-zero | Full init — would be a significant surprise given Test.29. | Switch from diagnostic to communication — probe olmsg ring for fw→host messages, try sending a command. |
| Host wedges earlier than T270-BASELINE's t+90-120s window | Regression from T276's bus-master + DMA alloc interacting with drifted substrate | Disable T276; re-fire T270-BASELINE to confirm drift vs T276-caused. |
| Readback magic check fails | Write path issue (not a fw-response issue) | Debug write_ram32 semantics for our specific offset; re-derive rambase assumption. |

### Design

Code already landed in commit `e866f7c`. When `bcm4360_test276_shared_info=1`:
1. Before `brcmf_chip_set_active` (after FORCEHT): `dma_alloc_coherent(64 KB)` + memset zero + write olmsg ring header (2 rings × 16 B + 2×30 KB data areas).
2. Zero shared_info TCM region `[ramsize-0x2F5C..ramsize-0x20)` (0x2F3C bytes).
3. Write 6 fields: magic_start (0xA5A5A5A5), dma_lo, dma_hi, buf_size (0x10000), fw_init_done (0), magic_end (0x5A5A5A5A).
4. Readback-verify ALL 6 fields (not just magic — DMA_LO/HI are what fw uses).
5. Call `brcmf_chip_set_active` (standard T238 path).
6. Poll post-release at 10 ms intervals for 2 s: read si[+0x010], fw_init_done, MAILBOXINT. Log on any change (don't break — Phase 4B saw multiple signals). Print final snapshot always.
7. Proceed into T238 ultra-dwell ladder as normal.

Cleanup: `dma_free_coherent` in `brcmf_pcie_release_resource` (covers remove + probe-failure paths).

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.276.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.276.run.txt || true
sudo journalctl -k --since "5 minutes ago" > /home/kimptoc/bcm4360-re/phase5/logs/test.276.journalctl.txt
```

Same skeleton as T270-BASELINE + the T276 param. 150 s covers chip_attach + shared_info write (~1 s) + set_active + 2 s T276 poll + full T238 ladder to t+120s = ~140 s expected.

### Expected artifacts

- `phase5/logs/test.276.run.txt`
- `phase5/logs/test.276.journalctl.txt`

### Safety

- Same T270-BASELINE envelope + DMA alloc + TCM writes into a region no other Phase 5 code touches (T234 gated off when test236=1, verified).
- No MSI, no `request_irq` — deliberately orthogonal to the T264-T266 MSI-wedge issue.
- Worst case: host wedge in [t+90s, t+120s] matching T270-BASELINE; platform watchdog recovers.

### Pre-test checklist

1. **Build**: ✓ committed (e866f7c); modinfo shows `bcm4360_test276_shared_info`; 5 test.276 strings visible.
2. **PCIe state** (at 10:50 BST): `Mem+ BusMaster+`, no MAbort+. **Clean per registers.**
3. **Substrate**: ⚠ ~3 h post-cycle (boot 0 up since 07:59 BST). **Outside T270-BASELINE's 20-min clean window.** T269 drift pattern: at 23 min post-cycle, crash window halved. At 3 h, drift is expected dominant. Signal likely muddied.
4. **Hypothesis**: this block.
5. **Plan**: this block (committed before fire).
6. **Recommendation**: **cold power cycle before fire** for cleanest read. Without a cold cycle, a null result would be ambiguous (drift vs no-response); firing inside the clean window gives the diagnostic its full power.

### Fire conditions

Do NOT fire until: (a) fresh cold cycle completed (boot 0 of a power-off session), and (b) fire within ~20 min of that boot. If substrate budget is limited, this test gets priority over any scaffold variant — T276 is the next gating evidence for the whole Phase 5 protocol model.

---

## POST-TEST.276 (2026-04-24 11:06 BST fire, boot -1 — **Phase 4B Test.28 handshake REPRODUCES: si[+0x010]=0x0009af88 (exact match). Row 3 outcome: fw wrote status, NO mailbox signals. Protocol anchor confirmed under Phase 5 patches. Late-ladder wedge unchanged from T270-BASELINE.**)

### Timeline (from `phase5/logs/test.276.journalctl.txt`, boot -1)

- `11:06:03` module_init entry
- `11:06:05` pci_register_driver
- `11:06:13..21` SBR, chip_attach, 6 cores enumerated, fw download (test.225 chunked 110558 words ✓), NVRAM write (228 bytes), random_seed footer (magic 0xfeedc0de, len 0x100)
- `11:06:22` FORCEHT applied — clk_ctl_st `0x01030040 → 0x010b0042` (HAVEHT=YES, ALP_AVAIL=YES, FORCEHT=YES)
- `11:06:22` **T276 shared_info written at TCM[0x9d0a4], olmsg_dma=0x8a160000, size=65536**
- `11:06:22` **T276 readback verified ALL 6 fields**: magic_start=0xa5a5a5a5 ✓, dma_lo=0x8a160000 ✓, dma_hi=0x00000000 ✓, buf_size=0x00010000 ✓, fw_init_done=0 ✓, magic_end=0x5a5a5a5a ✓
- `11:06:22` test.238: `brcmf_chip_set_active returned TRUE`
- `11:06:22` **T276 poll t+0ms: `si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000`** ← fw responded immediately
- `11:06:25` **T276 poll-end (2s later): `si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000`** — no further change
- `11:06:25 → 11:07:56` T238 ladder: t+100ms → t+300 → t+500 → t+700 → t+1s → t+1.5s → t+2s → t+3s → t+5s → t+10s → t+15s → t+20s → t+25s → t+26-30s → t+35s → t+45s → t+60s → **t+90000ms**
- `11:07:56` **LAST MARKER: `t+90000ms dwell`** — 22 dwells completed (matches T270-BASELINE)
- [silent wedge; expected t+120000ms never fired]
- `11:09:35` platform watchdog reboot

### Direct comparison vs T270-BASELINE (2026-04-24 07:54 fire)

| Metric | T270-BASELINE | T276 | Delta |
|---|---|---|---|
| last marker | t+90000ms dwell | t+90000ms dwell | **identical** |
| elapsed set_active → last marker | 91 s | 94 s | +3 s (jitter) |
| wedge window | (t+90s, t+120s] | (t+90s, t+120s] | **identical** |
| si[+0x010] pre-fire | (no write, field was pre-existing/0) | **0x0009af88 at t+0ms** | **fw responded** |
| MAILBOXINT | (not polled) | **0 for 2 s** | new negative data |
| recovery | watchdog + cold cycle | watchdog | clean so far |

### Direct comparison vs Phase 4B Test.28 (2026-04-13, different code path)

| Observation | Phase 4B Test.28 | T276 | Match? |
|---|---|---|---|
| si[+0x010] value | **0x0009af88** | **0x0009af88** | ✓ **EXACT MATCH** |
| Timing of si[+0x010] write | "within ≥2 s stable window" | **t+0ms (before first 10 ms poll tick)** | T276 tighter bound |
| MAILBOXINT post-run | `0x00000003` (2 bits set) | `0x00000000` | ✗ differs |
| fw_init_done | 0 (not set) | 0 | ✓ both unset |
| Fw stable for ≥2 s after ARM release | YES | YES | ✓ |

### What T276 settled (factually)

1. **The shared_info protocol anchor is REAL and consistent across fw states.** Whatever code in fw consumes shared_info and writes back `0x0009af88` at `+0x010` ran identically at 2026-04-13 (Phase 4B test module, minimal harness) and 2026-04-24 (Phase 5, with NVRAM/random_seed/FORCEHT patches layered on). The response is identical to the bit. Fw is genuinely listening at this interface.
2. **The response is very early post-ARM-release.** Inside our first 10 ms poll tick — well before most fw init steps. Consistent with shared_info being a startup gate, not a late-init feature.
3. **Phase 5's added patches do NOT reroute fw past this check-point.** The earlier belief ("Phase 5 fw is further along so Phase 4B observations may not apply") is weakened — at least for the shared_info field, Phase 5 fw behaves the same.
4. **T276 did NOT reproduce Test.28's mailbox signals.** Test.28 ended with `MAILBOXINT=0x00000003` (bits 0+1 set). T276 saw 0 bits set across the full 2 s poll. Plausible reasons:
   - Test.28 did additional steps after ARM release that T276 doesn't (the Phase 4B harness may have driven extra writes that triggered these signals).
   - Our 2 s poll missed a transient (fw set-and-cleared within <10 ms) — unlikely since fw is supposedly stable in this window.
   - Phase 5 fw state differs in a way that produces si[+0x010] response but not mailbox signals — possible but counter to point 3.
5. **T276 did NOT avoid or change the late-ladder crash.** Same wedge window `[t+90s, t+120s]` as T270-BASELINE. Whatever is wedging the host in that window is orthogonal to the shared_info handshake.
6. **The 64 KB olmsg DMA buffer was allocated, published to fw, and fw did NOT read or write it** (no pointer updates in si[+0x010] beyond the immediate 0x0009af88, which is a TCM address — 0x9af88 is below ramsize 0xa0000 — not our DMA address 0x8a160000). Same observation as Phase 4B Test.29 (ring unused).

### Pointer 0x0009af88 — what is it?

`0x9af88` is a TCM address (< ramsize 0xa0000). Note: this is **inside** the TCM but 0x211C bytes BEFORE shared_info base (0x9d0a4). Phase 4B called it a "console struct pointer." We can't probe it post-crash, but next run could read TCM[0x9af88..0x9aff0] to decode (likely `{buf_addr, buf_size, write_idx, read_addr}` struct per Phase 4B notes).

### What T276 did NOT settle

- Whether the late-ladder crash in [t+90s, t+120s] is fw-side or host-side (T270-BASELINE already raised this; T276 inherits the same gap).
- Why the mailbox signals differ from Test.28 (Phase 5 vs Phase 4 harness diverges somewhere between ARM release and t+2s).
- Whether sending a host action (e.g., writing H2D_MAILBOX_1, or writing into the TCM[0x9af88] console ring) would advance fw further.

### Next-test direction (advisor required)

Several candidates, each diagnostic:

- **T277-CONSOLE-DECODE**: Add a console-struct read at T276 poll time — dump 16 dwords starting at TCM[0x0009af88]. Cheap add to existing T276 code. Decodes the fw-provided pointer, should reveal buf_addr / buf_size / pointer fields matching Phase 4B's console-struct interpretation. Tells us where fw logs go (trap strings, printfs) → we can then READ fw's post-ARM-release internal log, which is far more informative than register polling.
- **T278-MBXINT-WIDEPOLL**: Re-run T276 with finer-granularity MAILBOXINT polling (every 1 ms × 100 iterations + every 10 ms × 200 iterations, plus H2D/D2H mailbox-mask registers). Tests whether Test.28's 2-bit mailbox signal is a transient we missed, or truly absent in the Phase 5 path.
- **T279-OLMSG-READ**: Add DMA-buffer readback to T276 — scan the 64 KB olmsg buffer for any fw writes. Confirms the Test.29 finding ("fw did not write olmsg") under Phase 5 conditions.
- **T280-STICK-WAIT**: Extend post-release wait to 10-30 s instead of 2 s, then probe shared_info + MAILBOXINT. Tests whether fw's signal was outside our 2 s window.

T277 is likely the highest-value (opens up the fw's internal console; may reveal assert/trap messages explaining the late-ladder wedge).

### Safety + substrate

- T276 consumed ~2 min of substrate; we're now ~5 min into boot 0. Substrate window is still fresh if we want another fire soon.
- T270-BASELINE finding holds: cold cycle → ~20 min clean window → drift reasserts. Current boot 0 is a post-crash watchdog recovery, not a cold cycle; substrate integrity for a second fire is uncertain (in T269 the 2nd post-cycle fire had drift; T270's 2nd cycle was user-cold-cycled for cleanness).

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.276.journalctl.txt` (1417 lines).
- Run output captured: ✓ `phase5/logs/test.276.run.txt` (2 lines — insmod entry/return).
- Outcome matrix resolved: ✓ **row 3** ("Only si[+0x010] nonzero; no mbxint") — with the added refinement that si[+0x010] value is the EXACT Phase 4B Test.28 value.
- Ready to commit + push + sync.

---

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

### Updated hang bracket (tighter than session start — **REVISED by T274-FW**)

| Point | Evidence |
|---|---|
| RTE boot banner | T250 ring-dump (`"RTE (PCIE-CDC) 6.30.223 (TOB)"`) |
| si_attach completes | T252 decode of 0x92440 (si_info-class struct with CC base 0x18001000 cached) |
| wlc attach / bmac attach entered | T251 saved-LR 0x68D2F / 0x68321 near those function bodies (α branch, now supported but not proven) |
| **pcidongle_probe COMPLETED through hndrte_add_isr + fn@0x1E44 + fn@0x1DD4** | T274-FW: T255/T256 show pciedngl_isr IS registered as scheduler node[0] at 0x9627C; pcidongle_probe's body maps to alloc→register→init→return with no hangs |
| **fw enters WFI** | T257 DEFINITIVE (host harness bypasses MSI setup; no IRQ ever arrives) |
| **sharedram publish NOT reached** | T247: TCM[ramsize-4] unchanged 23/23 dwells. T274-FW finding: sharedram publish is NOT inside pcidongle_probe — it must be in a LATER phase of fw init gated on an event that never fires. |

Hang location: AFTER pcidongle_probe returns to its caller (the device-probe-iterator). Fw enters a scheduler state with registered callbacks (pciedngl_isr + wlc's fn@0x1146C) but no runnable flag bits → WFI. Sharedram publish is gated behind an event fw expects but never receives.

**Earlier reading "pcidongle_probe never reached" was WRONG and is superseded by T274-FW.**

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

---

## POST-T272-FW (2026-04-24 09:30 BST — **Init chain mapped. Hang bracket tightened to a 2–3-call sub-tree inside wlc_bmac_attach's tail. Next static-analysis step named. No hardware fires.**)

### What T272-FW settled

Full doc: `phase6/t272_init_chain.md`. Key facts:

- **Device-registration struct layout identified.** Both `wlc` (base `0x58EFC`) and `pciedngldev` (base `~0x58C88`) use Broadcom hndrte-style fn-pointer tables. Probe slots: `[0x58F1C] → fn@0x67614` (wlc) and `[0x58C9C] → pcidongle_probe (0x1E90)` (pciedngldev).
- **Both probes reached ONLY via indirect dispatch** through a (static-linked) device-list iterator. No direct BL callers for `fn@0x67614` or `pcidongle_probe`. RTE walks the device list and invokes each probe in registration order.
- **Direct call chain** (innermost first): `wlc_phy_attach (0x6A954) ← wlc_bmac_attach (0x6820C) ← fn@0x68A68 ← fn@0x67614 ← indirect`.
- **"wlc_attach" is a stage-name, not a function**. The `"wlc_attach"` ASCII string at `0x4B1FF` is referenced only from trace strings inside `wlc_bmac_attach`'s error paths. No dedicated `wlc_attach` function body in this blob.
- **Saved-LR 0x68321 from T251 resolves to**: return from `bl #0x1415C` at 0x6831C (SB-core-reset waiter; bounded 20ms per T253/T254). fw had reached at least that point inside `wlc_bmac_attach`, and fn_1415C had returned.

### Hang bracket — tightened

After the T251 saved-LR return point (0x68320), wlc_bmac_attach continues with these sub-calls:

```
0x68326:  bl #0x15940        ; T254 already cleared (no loops)
0x6832C:  bl #0x179C8        ; UNTRACED — HIGHEST PRIORITY candidate
0x68330:  cbnz r0, +0x28     ; error check
0x6835E:  bl #0x52A2         ; lookup helper
0x6836E:  bl #0x67E1C        ; UNTRACED — second priority
```

Also (but lower priority since fw already passed it to reach the saved-LR point):

```
0x68ACA:  (inside fn@0x68A68, before bl wlc_bmac_attach)
          bl #0x67F2C        ; UNTRACED — tertiary
```

### The 3 untraced sub-calls that could contain the hang

| Addr | Pattern heuristic | Priority |
|---|---|---|
| `0x179C8` | First BL after T251-observed saved-LR; position suggests HW/MAC bringup | HIGH |
| `0x67E1C` | Second BL in continuation chain | MEDIUM |
| `0x67F2C` | In fn@0x68A68 wrapper, before wlc_bmac_attach call | LOW (likely completed) |

If `0x179C8` contains an unbounded polling loop with a host-dependent condition (bit that only flips when host writes to a specific register), the hang location is identified and the fix is "set that bit before fw reaches 0x179C8."

### Observations on probe ordering

If device-probe-iterator invokes `wlc` before `pciedngldev` (order in static linked list), and `wlc`-probe hangs, `pciedngldev`-probe never runs → `pcidongle_probe` never runs → no `hndrte_add_isr(pciedngl_isr, bit=3)` → no sharedram publish → no HOSTRDY_DB1 advertising → host cannot safely ring doorbell. This is exactly what T247/T255/T257 observed.

### Why this is a reasonable stopping point for today

- T272-FW narrowed the hang window from "somewhere between si_attach and pcidongle_probe" to "inside one of three specific sub-functions, all in wlc_bmac_attach's tail."
- Continuing would be T273-FW: disassemble `0x179C8`, `0x67E1C`, `0x67F2C` bodies; classify each as bounded / unbounded-polling / dispatcher-tail-call. That's the natural next analytical step.
- No hardware fires today since 08:01 (T270-BASELINE). Substrate window has likely closed (boot uptime 1h40m+, drift expected). Next hardware fire needs another cold cycle.
- If T273-FW identifies an unbounded polling loop in any of these calls, a targeted T274 hardware probe becomes designable: peek at the specific register the loop reads, confirm the hang point on live hardware.

### What T272-FW did NOT settle

- Exact hang address within the bracket — need T273-FW to disassemble the 3 sub-calls.
- Which specific event / register / HW-state transition fw is waiting on — same answer.
- Whether our scaffold investigation could ever produce a valid wake — still blocked by the shared-publish gap. That gap closes only if fw reaches pcidongle_probe, which requires the hang in wlc_bmac_attach's tail to be resolved first.

---

## POST-T273-FW (2026-04-24 10:10 BST — **All 3 T272 candidates cleared; full wlc_bmac_attach first-level scan confirms no unbounded HW-polling. Scheduler-callback lead identified: fn@0x1146C registered via hndrte_add_isr at 0x67774 inside wlc-probe.**)

Full writeup: `phase6/t273_subcall_triage.md`. Scripts: `phase6/t273_*.py`.

### What T273-FW settled

1. **All 3 T272 candidates are non-polling**:
   - `0x179C8` = `wlc_bmac_validate_chip_access` (96 insns, no backward branches; string xref confirms identity).
   - `0x67E1C` = tiny field-reader (2 insns).
   - `0x67F2C` = 10-insn dispatcher (tail-calls one of two targets).

2. **Full wlc_bmac_attach body scan** (44 unique BL targets, 2140 bytes): every tight loop at first-level has a **fixed bounded iteration count**:
   - `0x1415C` — SB-core reset waiter, 20ms via delay helper (T253/T254).
   - `0x5198` — 6-iter MAC-address copy.
   - `0x67F8C` — 6-iter txavail setup (string `&txavail`, `wlc_bmac.c`).
   - `0x68D7C` — 30-iter init loop (string `wlc_macol_attach`).

3. **Negative-result signal**: hang is NOT a simple tight HW-polling loop. Combined with T255 (frozen scheduler state) and T257 (WFI DEFINITIVE), the mechanism is "fw enters scheduler with no runnable callback → WFI waiting for an interrupt that never fires."

4. **Advisor-flagged lead (followed)**: `fn@0x67614` (wlc-probe top) calls `hndrte_add_isr` at 0x67774, registering `fn@0x1146C` as a scheduler callback.
   - Args observed: r3 = 0x1146D (fn-ptr); r0 = sb = 0 (NULL ctx); r1/r2/r7/r8 carry name/arg/class metadata.
   - fn@0x1146C is 10 insns, NO HW register reads — purely dispatches to `bl #0x23374` (helper sets byte flag) → conditional `bl #0x113b4` (action).
   - Appears as the last slot in the wlc device fn-table (0x58F38 = 0x1146D).
   - Trigger flag bit allocated by hndrte_add_isr from the class-dispatch pool (per T269 analysis). Scheduler tests the pending-events word `*(ctx+0x358)+0x100` against each node's flag.

### Strong circumstantial case: fn@0x1146C's flag is host-driven

| Evidence | What it tells us |
|---|---|
| T255: scheduler state [0x6296C..0x629B4] identical across 23 dwells | Rules out periodic timer tick (would drift) |
| T257: WFI DEFINITIVE (host bypass of MSI/IRQ setup) | Matches "host should be signaling something but isn't" |
| Upstream brcmfmac protocol: hostready gate on HOSTRDY_DB1 | Confirms pattern where host triggers fw wake events |
| fn@0x1146C body: no HW regs, pure event-driven dispatch | Matches "await external event" — not HW-state polling |

These all point to: **fn@0x1146C waits for a specific host-driven trigger** that our test harness never generates. Unlike pciedngl_isr (bit 3 = FN0_0 mailbox), we don't yet know which trigger — it's allocated from the same pool but via a different class-dispatch path.

### What this means for next moves

**Scaffold line (T258–T269) was doubly blocked**:
1. The scaffold rang H2D_MAILBOX_1 without the HOSTRDY_DB1 gate — which wouldn't have mattered even with the gate, because fw never reaches pciedngldev-probe to advertise HOSTRDY_DB1.
2. The scaffold would have fired bit 3 (FN0_0 = pciedngl_isr) which isn't even registered yet at the time of our scaffold firing (since pcidongle_probe hasn't run).
3. The right wake-trigger for the CURRENT fw state is whatever fn@0x1146C's flag responds to — a DIFFERENT mailbox bit that we haven't been writing.

### Next cheap static-analysis steps

Each ~30 min:

1. **Trace writers of `*(ctx+0x358)+0x100`** — which function(s) in the blob STORE to this pending-events word? The arguments / bit-patterns reveal what triggers fire the word.
2. **Disasm the 9-thunk vector's WLC slot** (the one for WLC's `*(ctx+0xCC)` class index) — identifies which HW interrupt class WLC is attached to.
3. **Disasm helpers `0x23374` and `0x113b4`** (called from fn@0x1146C body) — verify they don't have hidden HW reads.

### Next hardware direction (only if static step 1 or 2 identifies a register)

Design T274 scaffold to write the specific mailbox/doorbell/status register that fires fn@0x1146C's bit. If fw advances past the WFI, pciedngldev-probe may run → sharedram publish → HOSTRDY_DB1 → then the original scaffold design might work.

BUT: the separate "MSI subscription itself wedges host" issue (code audit §4) remains. Even with a correct fw-wake trigger, the host-side wedge modes from T264/T265/T266 would still need to be addressed. Probably via `pci=noaer` removal or `pci=noaspm` (audit candidates B/C).

### Session status

- Zero hardware fires since 08:01 BST (T270-BASELINE).
- Substrate window is closed (boot 0 uptime ~2h+; drift reliable within 25 min of cold cycle).
- No hardware action planned until static analysis identifies a specific register to target.
- fw-blob side: T273 concluded. T274-FW would be the pending-events-word writer trace.

---

## POST-T274-FW (2026-04-24 11:00 BST — **Architectural mismatch discovered. Major reframe.**)

Full writeup: `phase6/t274_events_investigation.md`. Scripts: `phase6/t274_*.py` + `/tmp/t274_*.py`.

### What T274-FW settled

1. **T255/T256 data reinterpreted**: pciedngl_isr IS registered (node[0] at TCM[0x9627C]: next=0x96F48, fn=0x1C99, arg=0x58CC4, flag=0x8). Therefore **pcidongle_probe ran PAST hndrte_add_isr successfully**. My earlier reading "pcidongle_probe never reached" was WRONG.

2. **pcidongle_probe full body mapped** (0x1E90..0x1F78, 232 bytes):
   - alloc devinfo(0x3c) → memset → 5 sub-call helpers populating struct
   - `bl #0x63C24` (hndrte_add_isr) at 0x1F28 — registers pciedngl_isr
   - `bl #0x1E44` at 0x1F38 — post-registration finalize
   - return

3. **fn@0x1E44 (post-reg finalize, 68 bytes)**:
   - Initializes ISR_STATUS mirror at `[devinfo_substruct + 0x100]` with `(config & 0xfc000000) | 0xc`
   - Calls `bl #0x2F18` (struct-init helper, ~116B clean) and `bl #0x2DF0` (1-insn `bx lr` no-op)
   - Tail-calls `bl #0x1DD4`

4. **fn@0x1DD4 (114 bytes, tail-called from fn@0x1E44)**:
   - Allocates 196-byte msg buffer, stores at devinfo+0x20
   - Calls `bl #0x66a60` (shared msg-queue init — T273 also considered via different path; verified bounded below)
   - Returns

5. **bl #0x66a60 is NOT a polling loop** (verified per advisor's 20-min cheap check):
   - 208 bytes, 1 backward branch (a 30-iter bounded list-init loop)
   - Allocates up to 30 descriptors via `bl #0x7d74` and links them into a message-queue list
   - String reference `'bcmutils.c'` — a bcmutils init helper
   - No waits, no HW register polls

6. **pcidongle_probe completes fully with no hangs in its body or sub-tree**. Hang is AFTER it returns.

7. **HOSTRDY_DB1 (0x10000000) is NOT referenced in fw code** (critical finding):
   - 5 literal-pool-aligned byte matches exist in the blob.
   - ZERO of them have direct LDR pc-rel references or MOVW/MOVT pairs encoded elsewhere in code.
   - `movt r?, #0x1000` scan of entire blob: zero matches.
   - **Therefore: this fw does NOT advertise HOSTRDY_DB1 as part of its shared.flags protocol.**

8. **Implication — architectural mismatch**:
   - Upstream brcmfmac `brcmf_pcie_hostready` (pcie.c:2044) is gated on `shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1`. If fw never sets that bit, upstream's normal probe would NEVER write H2D_MAILBOX_1.
   - The fw banner literally says `"RTE (PCIE-CDC) 6.30.223 (TOB)"` — **CDC-PCIe**, not msgbuf.
   - Upstream brcmfmac's PCIe driver path is **msgbuf-only**. BCM4360's CDC-PCIe fw may be architecturally incompatible with upstream's probe path.

9. **Writers of pending-events word NOT found**:
   - Zero stores at offset #0x100 with preceding ctx+0x358 load.
   - Zero stores at offset #0x458 (flat).
   - Zero stores at offset #0x358 (ctx setup).
   - Strongly suggests the word at `*(ctx+0x358)+0x100` is **HW-mapped**, not software-maintained. T269's "software-maintained pending events" reading needs correction.

10. **IRQ handler finding**:
    - ARM vector at 0x18 → handler at 0xF8 → calls `[*0x224]` (ISR dispatcher).
    - `[0x224]` = 0 in static blob; no code writes to 0x224 via direct lit-ref.
    - Implies fw either runs with IRQs disabled, or uses a VBAR-remapped ARM vector path, or [0x224] is written via an addressing mode we missed. Non-blocking but notable.

### Major reframe

The scaffold investigation's whole premise (that fw would wake via a doorbell if the right host-side state is set) may be **architecturally mismatched** with this fw. The banner indicates CDC-PCIe. Upstream brcmfmac's PCIe path is msgbuf-only. We've been trying to drive CDC firmware with a msgbuf driver.

### New productive direction (advisor-confirmed)

**Upstream audit.** Specific question:

- Is there any version of brcmfmac (past or present) that drove PCIe-CDC fw?
- If YES: that path is our reference. We need to port/port-forward that driver path or re-enable it.
- If NO: upstream brcmfmac was never designed for BCM4360's legacy fw. The project reframes as "port or write a CDC-PCIe driver," not "patch the existing msgbuf driver."

Either answer unblocks. Continuing blob spelunking at this depth has diminishing returns.

### What remains valid

- T270-BASELINE substrate reproducibility (unaffected).
- T257 WFI-DEFINITIVE observation (unaffected — fw IS in WFI).
- The scaffold-line host-wedge modes (T258–T269) — those are host-side issues independent of fw protocol. Still need to be addressed if/when we have a wake sequence that matches the fw.
- T253/T254's polling-loop-classification of wlc_phy_attach's subtree (unaffected — that was thorough and correct).

### What is invalidated / needs updating

- The "pcidongle_probe never reached" claim (from POST-FW-BLOB-DISS REFRAME) — WRONG. Reconciled in the bracket table above.
- T269's "software-maintained pending events word" reading — probably HW-mapped based on the zero-writer finding. Noted in T274 §6.1.
- The "host needs to ring the right mailbox to wake fw" framing for T273's fn@0x1146C analysis — possibly true, possibly architectural mismatch. We don't yet know what CDC-PCIe's wake protocol expects.

### Session status

- No hardware fires planned.
- Static analysis at diminishing-return depth.
- Next action: upstream audit for CDC-PCIe driver support (possibly in git history of brcmfmac, or in broadcom/brcmsmac, or in the out-of-tree broadcom drivers).

---

## POST-T275-UPSTREAM-AUDIT (2026-04-24 11:45 BST — **Phase 4 rediscovery + engineering path identified. Full writeup at phase6/t275_upstream_audit.md.**)

### What T275 settled

1. **Upstream brcmfmac PCIe is msgbuf-only.** `pcie.c:6877` hardcodes `proto_type = BRCMF_PROTO_MSGBUF`. Kconfig's `BRCMFMAC_PCIE` selects `BRCMFMAC_PROTO_MSGBUF`. No upstream version ever drove PCIe-CDC.
2. **But BCDC code is in brcmfmac**, wired to SDIO (`bcmsdh.c:1081`) and USB (`usb.c:1263`). BCDC talks to bus via standard `txctl`/`rxctl`/`txdata` callbacks defined in `brcmf_bus_ops`.
3. **Critical observation**: PCIe's `brcmf_pcie_tx_ctlpkt` and `brcmf_pcie_rx_ctlpkt` (pcie.c:2597/2604) are **stubs returning 0**. Msgbuf doesn't call them; they exist only to satisfy the bus_ops struct.
4. **Phase 4B already reached this conclusion** (commit `fc73a12`, 2026-04-12): "BCM4360 wl firmware uses BCDC protocol… No msgbuf firmware exists for BCM4360 in any known source… Driver patches are proven working — firmware compatibility is the sole blocker." T258-T274 was ~2 weeks of rediscovery work.
5. **T274's misread corrected**: "fw never references HOSTRDY_DB1" is correct fact, but my interpretation "fw expects some other mystery wake trigger" was wrong. Simpler: **fw expects host to send the first CDC command, which starts the init state machine**. We don't send one because we use msgbuf proto, not BCDC.

### The engineering path (novel contribution of T275)

Minimal patchset:

1. New Kconfig option `BRCMFMAC_PCIE_BCDC` (or per-chip flag for BCM4360).
2. Modify pcie.c:6877 to set `proto_type = BRCMF_PROTO_BCDC` for BCM4360.
3. Implement `brcmf_pcie_tx_ctlpkt`:
   - Copy CDC command bytes into a TCM buffer (pcidongle_probe's allocated buffer per T274 §4).
   - Write H2D_MAILBOX_1 = 1 → fires fw's pciedngl_isr (bit 0x100 = FN0_0).
   - Wait for completion.
4. Implement `brcmf_pcie_rx_ctlpkt`:
   - Register D2H mailbox IRQ handler (needed before first command).
   - Handler copies CDC response bytes from TCM + wakes waitqueue.
   - `rx_ctlpkt` sleeps until handler signals, copies to caller's `msg` buffer.
5. First test: `WLC_GET_VERSION` dcmd round-trip. Success = response with valid version + sharedram_addr subsequently published (side-effect of fw advancing past CDC-wait).

### Why this should work when scaffolds didn't

Scaffolds (T258-T269) wrote H2D_MAILBOX_1 into a fw state with no valid command buffer. Fw's `pciedngl_isr` fired on the doorbell, read nonsense from the command buffer, and either ignored it or crashed silently.

With BCDC wiring, the command buffer contains a real CDC command BEFORE the doorbell. Fw reads a valid command, processes it, returns a response. Standard CDC operation that the fw was built for.

### What this re-frames

- **T274's "mystery wake trigger"** — resolved. It's just "host sends CDC command".
- **T273's fn@0x1146C** — the wlc-side scheduler callback. Probably fires when WLC init messages arrive via CDC (once the host sends them). Not a blocker to get initial CDC working.
- **The T258-T269 scaffold line** — fundamentally wrong approach. Writing mailbox doorbells without valid command bytes in the buffer can't wake fw productively.
- **The host-side MSI-wedge issue** (from code audit) — orthogonal, still live. Need to solve it as part of this work (MSI subscription is required to receive D2H responses).

### Open questions for advisor / next session

1. **Sanity-check the rediscovery**: Phase 4 ended with "fw compat is the blocker". T275 says "actually, the BCDC proto layer + the empty PCIe stubs give us a clean path without needing new fw". Why did Phase 4 not take this path? Either we missed something Phase 4 knew, or Phase 4 didn't realize the stubs existed.
2. **CDC bringup sequence**: what's the first few commands to send? (Possibly inferable from wl.ko or from Broadcom docs; brcmfmac's SDIO path must do the same dialog.)
3. **Where is pcidongle_probe's command-input buffer** in TCM? `devinfo->[0x10]` at runtime — needs live lookup or further blob analysis to find its TCM offset.
4. **MSI-wedge on BCM4360** (code audit §4): independent of proto choice; needs its own fix before D2H responses can be received.

### Session-level summary

Two full days of blob spelunking (T250-T274) converged on a conclusion that Phase 4B (2026-04-12) had already reached. The unique contribution of this session is:

- **Direct evidence** for the architectural mismatch (T274: zero HOSTRDY_DB1 refs, pciedngl_isr/hndrte_add_isr fully characterized, all scheduler state mapped).
- **The specific stub-implementation path** (T275: txctl/rxctl exist as empty stubs, BCDC proto attach already handles everything else).
- **Clean re-grounding** of the engineering plan: patch 2 stubs + 1 line to switch proto_type = concrete code change, not a vague "fw compat is the blocker."

### Session status

- No hardware fires today since 08:01 BST (T270-BASELINE).
- All commits pushed and filesystem synced.
- Ready to advisor-check the engineering plan. If approved, next session implements the 2-stubs + Kconfig change.

---

## POST-T275-CORRECTION (2026-04-24 12:30 BST — **Advisor blocked T275's BCDC plan. Primary sources in phase4/notes show olmsg/shared_info is the right protocol.**)

### What happened

Advisor flagged two unreconciled things before any code:

1. **Phase 4A (`phase4/notes/transport_discovery.md`) says BCM4360 is SoftMAC NIC + offload engine, NOT FullMAC dongle.** "There is no BCDC-over-PCIe transport protocol to reverse-engineer" — explicitly ruling out what T275 proposed.
2. **Phase 4B's conclusion doc (`phase4/notes/test_crash_analysis.md`, added by commit `a8007d2`) had specific runtime findings I hadn't read.**

Reading the Phase 4B conclusion doc revealed:

- **Test.28 (2026-04-13)**: writing a valid `shared_info` struct at **TCM[0x9D0A4]** before ARM release completely prevents the 100 ms panic. Fw runs stably for ≥2 s, finds magic markers, reads the olmsg DMA buffer address, writes status (`0x0009af88`) to `shared_info[0x10]`, sends 2 PCIe mailbox signals.
- Layout (`phase4/notes/level4_shared_info_plan.md`):
  - `+0x000` magic_start `0xA5A5A5A5`
  - `+0x004..+0x00B` olmsg DMA addr (lo + hi 32-bit)
  - `+0x00C` buffer size `0x10000` (64 KB)
  - `+0x010` fw-writable status
  - `+0x2028` fw_init_done (fw sets when ready)
  - `+0x2F38` magic_end `0x5A5A5A5A`

### The correct protocol

**olmsg** (offload messaging) over a DMA ring buffer, address published via `shared_info` in TCM. NOT BCDC.

`bcm_olmsg_*` symbols in the fw blob correspond to Phase 4A's wl.ko-side `bcm_olmsg_writemsg`/`bcm_olmsg_readmsg` helpers. This is the protocol wl.ko (Broadcom's proprietary driver) uses for BCM4360. The BCDC strings (`bcmcdc`, `pciedngl_*`) in the blob are shared-codebase artifacts — fw CAN parse CDC but the HOST-observable runtime protocol is olmsg.

### Phase 4A vs 4B reconciled

- **Phase 4A** analyzed `wl.ko` host-side. Saw offload usage. Correctly concluded the runtime protocol is olmsg.
- **Phase 4B** analyzed the fw blob. Saw wlc_*, pciedngl_*, bcmcdc. Concluded "FullMAC CDC" — but this described the *fw binary's compiled capabilities*, not the runtime protocol the host drives.
- **The two readings are compatible**: fw binary has both FullMAC and offload code; wl.ko chose offload path; we should too.

### Why T275 went off course

I reached for the familiar framework (brcmfmac + BCDC/msgbuf dispatch) without reconciling against Phase 4's specific runtime findings. T274's "fw expects some mystery wake" should have triggered a Phase 4 lookup — it didn't. Rediscovered the mismatch from first principles over T250-T274, then proposed a plan that contradicted Phase 4's own conclusion.

### New pinned file: `KEY_FINDINGS.md`

Created at repo root. Schema: Fact | Status (CONFIRMED / RULED-OUT / LIVE / SUPERSEDED) | Evidence | Date. Seeded with ~40 cross-phase facts including the shared_info offsets, olmsg ring layout, Phase 4B's test.28 evidence, Phase 5's current progression, and what's been ruled out (BCDC-over-PCIe, tight HW-poll, writing doorbells without shared_info).

**CLAUDE.md updated** to require reading KEY_FINDINGS.md first, and to instruct "grep prior phases before declaring a new finding". Final section of KEY_FINDINGS.md is a self-review reminder for end-of-session updates.

### Corrected engineering path

Not "wire BCDC via two stubs." Instead:

1. **In Phase 5's `brcmf_pcie_setup` (before the early return for BCM4360)**: write Phase 4B's `shared_info` struct to TCM[0x9D0A4] after allocating a 64 KB DMA coherent buffer for olmsg.
2. After ARM release: poll `shared_info[+0x2028]` (fw_init_done) for up to ~2 s. If fw sets it, handshake succeeded.
3. Parse olmsg ring structure (ring 0 = host→fw, ring 1 = fw→host, each 30 KB data area + 16-byte header).
4. Send a `BCM_OL_*` command via olmsg ring 0 (e.g., `BCM_OL_BEACON_ENABLE` or similar bringup command — requires further cross-ref to enumerate the early-init command set).
5. Wait for response on ring 1 via PCIe mailbox signal.

This is closer to what wl.ko does. Patch it into brcmfmac-PCIe as a "BCM4360-specific olmsg attach" path — parallel to (not replacing) the msgbuf attach.

### What T275 still contributes

The STUB observation (PCIe's `tx_ctlpkt`/`rx_ctlpkt` return 0) is factually correct but irrelevant. Msgbuf doesn't use them and BCDC wiring wouldn't work because BCDC is the wrong protocol. The T275 writeup should be read with a correction header saying "BCDC direction is wrong — olmsg is right; see POST-T275-CORRECTION and KEY_FINDINGS.md."

### Session status (updated)

- KEY_FINDINGS.md and CLAUDE.md pointer added.
- T275 is recorded but flagged as SUPERSEDED-CORRECT (the stub observation stands; the BCDC conclusion doesn't).
- olmsg handshake path identified as the next LIVE hypothesis.
- No hardware fires since 08:01 BST.
- Advisor-check on olmsg port before coding (the patch is bigger than "two stubs" — needs DMA buffer alloc, TCM write, fw_init_done poll, olmsg ring parsing, mailbox handler).
