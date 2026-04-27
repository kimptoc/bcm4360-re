# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

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

## Archived detail

Older PRE/POST test blocks have been migrated to
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).

Current policy for this file:

- keep the current-state block above
- keep only the latest 2-3 active PRE/POST test pairs when a hardware campaign
  is in flight
- move older chronology to history
- move broader synthesis into phase notes or `KEY_FINDINGS.md`

For the recent T290/T294/T296-era chronology, see:
- [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md)
- [phase5/notes/phase5_progress.md](phase5/notes/phase5_progress.md)
- [KEY_FINDINGS.md](KEY_FINDINGS.md)

The next action remains the read-only `test.288a` runtime discriminator already
summarized in the current-state block above.
