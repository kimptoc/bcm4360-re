# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 — POST-TEST.298 RECORDED: BAR2-only ISR-walk FIRED CLEAN, 2-node ISR set captured, late-ladder rmmod wedge as expected)

**Model.** The blob carries two runtimes; the live one is HNDRTE/offload, not
the `wl_probe → wlc_*` FullMAC chain. T298 just provided primary-source
confirmation: only 2 ISRs are registered at runtime (pciedngl_isr + RTE
chipcommon-class ISR). No `wlc_isr` (fn=0x1146D) — the FullMAC chain stays
dead in offload mode as predicted by KEY_FINDINGS row 161.

**What just happened.** PRE-TEST.298 fired ~14:19:30 BST after user cold
cycle. Probe ran cleanly through all 7 stages (pre-write, post-write,
post-set_active, post-T276-poll, post-T278-initial-dump, t+500ms, t+5s,
t+30s, t+90s) — **substrate-noise belt was passed**, first such fire
since T293. Watchdog late-ladder wedge during rmmod attempt (~t+150s)
required user SMC reset; orthogonal to the probe success. Cold-booted
14:31 BST; uptime ~2 min at writeup time.

**Primary-source result.** ISR-list at TCM[0x629A4] = 2 nodes, frozen
across all 5 post-set_active stages (no churn between t+0 and t+90s):

| Node | TCM addr | fn | arg | mask (OOB-slot bit) | Identification |
|---|---|---|---|---|---|
| 0 | 0x0009627c | 0x1c99 | 0x58cc4 | 0x8 (bit 3) | pciedngl_isr (T256 reproduces) |
| 1 | 0x00096f48 | 0x0b05 | 0x0 | 0x1 (bit 0) | RTE chipcommon-class ISR (fn@0xB04+thumb) |

`mask` = `1 << bit_index` where `bit_index` was returned by BIT_alloc
reading chipcommon-wrap+0x100 (`oobselouta30`) at `hndrte_add_isr` time.
**The RTE chipcommon-class ISR was allocated bit 0** — primary-source
identification of the OOB slot. The wake-trigger that SETS bit 0 is
still LIVE; what's confirmed is the routing slot, not the trigger
source.

Auxiliary fields (with caveats):

- `sched+0xCC = 0x1` stable across all stages. **Semantics unclear** —
  not the live class-ID (predicted 0x800/0x812 in PRE-TEST). Could be
  a status/flag word; per row 137, slot counter is at +0xD0 so +0xCC
  is something else.
- `events_p = sched+0x358 = 0x18109000` — chipcommon-wrap MMIO REGION
  address (0x18100000 + 0x9000), NOT a TCM-internal pointer. Outside
  T298_RAMSIZE_BOUND (0xA0000), so the bounds check in the macro
  rejected it and `pending=0` is a CODE-PATH PLACEHOLDER, not a
  measurement. The events_p VALUE is real and meaningful (fw stores
  a backplane MMIO addr at sched+0x358); the pending VALUE is not.
- `+0x88 = 0x18001000` (D11 base) at post-set_active onwards — class
  shift to core[2]/D11 happens earlier than T287c previously sampled
  (already there at post-set_active, not after the 2s poll).

**What the result confirms / weakens / leaves open.**

- **CONFIRMED:** row 161 (live runtime ≠ FullMAC) — only 2 nodes, no
  wlc_isr. wl_attach's hndrte_add_isr call site never executed.
- **CONFIRMED-PARTIAL:** row 148 (chipcommon-wrap is the wake-routing
  surface) — bit 0 of `oobselouta30` is what the chipcommon-class ISR
  was allocated at registration. The mechanism (BIT_alloc reads OOB
  selector to claim a slot) is live and produced a value.
- **STILL LIVE:** what HW event sets `oobselouta30` bit 0 (or any bit)
  to wake fw from WFI. Pending=0 is uninformative (placeholder), so we
  haven't observed any event firing or not firing.
- **STOPPING-RULE VINDICATED:** row 85's "pivot to TCM-only, off BAR0"
  rule worked. T298 is the first probe-bearing fire to clear the
  substrate-noise belt since T293. The 4-null T294→T297 streak was
  caused by BAR0 chipcommon/wrapper touches, not by something in the
  shared scaffold.

**Next discriminator (proposed; not yet planned).** Two complementary
probes both reachable via TCM/BAR2:

1. **TCM-side `oobselouta30` shadow.** If fw maintains a TCM cache of
   the OOB-selector value (likely — BIT_alloc is called many times per
   init), reading that cache via BAR2 gives us the LIVE `oobselouta30`
   bit pattern without touching chipcommon-wrap MMIO. T298 only gave
   us the RESULT of a single past read; we want the live state.
2. **Inject a wake event from host that doesn't require chipcommon-wrap
   writes.** Candidates: DMA transfer (Phase 4B's olmsg ring path —
   already plumbed but never fired with a real transfer), MSI assert
   via PCIe config-space, or the upstream `pci=noaspm` candidate from
   row 152.

Defer choice until KEY_FINDINGS rows 148/161 are updated and an
advisor-reviewed plan is written.

**What not to retry blindly.**

- Same as before: BAR0 chipcommon/PCIE2/wrapper reads at any timing
  (row 85), PCIe2 mailbox / D11 INTMASK wake probes (rows 125/159).
- **Don't claim "wake gate identified at chipcommon-wrap+0x100 bit 0".**
  That conflates the OOB allocation slot (now known) with the trigger
  source (still unknown).
- Don't burn another fire just to re-read T298 — the 2-node result is
  primary-source and stable. Need a NEW probe, not a re-fire.

**Substrate state.** Cold-booted 14:31 BST, lspci clean as of 14:32.
Uptime 2 min — fresh window. Next plan should be drafted while still
fresh; don't fire again without one.

---

## PRE-TEST.298 (2026-04-27 ~13:30 BST — first BAR2-only fire of the new direction. ISR-list dynamic walk + sched_ctx[+0xCC] + pending-events word at 5 stages. ZERO BAR0 touches.)

### Goal — single bit of information

Walk the ISR linked list at TCM[0x629A4] and read the per-node OOB-allocation
shadow (`node[+0xC]`) for every registered ISR. The value at `+0xC` is
`1 << bit_index` where `bit_index` was returned by BIT_alloc reading
chipcommon-wrap+0x100 (oobselouta30) at the time `hndrte_add_isr` ran. This
gives us the chipcommon-wrap OOB allocation result without ever touching
chipcommon-wrap from the host — addressing KEY_FINDINGS row 148's wake
hypothesis from the TCM side instead of the failed BAR0 side.

### KEY_FINDINGS row 85 attestation (per t297_next_steps.md "Hardware Fire Gate")

- Row 85 stopping rule cited and respected: this fire pivots OFF chipcommon
  BAR0, onto BAR2 TCM-side reads only.
- **test.298 does NOT touch BAR0:**
  - does NOT write `BAR0_WINDOW`
  - does NOT call `brcmf_pcie_select_core`
  - does NOT read chipcommon, PCIE2, or wrapper MMIO
  - uses ONLY `brcmf_pcie_read_ram32` (verified BAR2-direct ioread at
    pcie.c:1875: `ioread32(devinfo->tcm + ci->rambase + offset)`)
- Acknowledgement: BAR2-only does NOT bypass the upstream noise belt
  documented in row 85 (test.158/188/193/225 wedge points). The probe
  needs fw to reach post-set_active before its first stage even runs.

### Module params

- ENABLE: T236 (force seed), T238 (ultra dwells), T276 (shared_info), T277
  (console decode), T278 (console periodic), T284 (premask), T287 + T287c
  (sched_ctx fields), **T298 (the new BAR2 ISR-walk + sched/pending probe)**
- DROP: T288A (chipcommon-wrap BAR0 read — the wedge surface from T297),
  T290A (superseded by T298's dynamic walk), T290B (cc-write wedge-prone),
  T294 (cc BAR0 ro probe — same surface as 288A)

### Hypothesis

Most likely outcome: **2 nodes in the list**. Node[0] = pciedngl_isr (fn=0x1C99,
mask=0x8 = bit 3) confirming T256 reproduces. Node[1] = the RTE chipcommon-class
ISR (fn=0x0B05, with class=0x800 hard-coded at registration) — its mask reveals
which OOB slot BIT_alloc allocated from chipcommon-wrap+0x100 at registration.

Pending events word (`*(*(sched+0x358))+0x100`) expected = 0 (fw in WFI per
row 116; no HW events firing). Non-zero would be a major signal.

sched_cc (sched+0xCC) expected to track T287c's observed class shifts: 0x800
(chipcommon class) at post-set_active, 0x812 (core[2]) after first dispatch.

### Discriminator outcomes

| ISR-walk count | Interpretation | Updates |
|---|---|---|
| 0 nodes | Head ptr 0; fw never reached pcidongle_probe. Falsifies T256 reproduction. | row 161 weakens |
| 1 node (pciedngl_isr) | RTE init helper @ 0x63CF0 didn't execute. Live offload runtime narrower than thought. | row 161 strengthens; row 148 chipcommon-wrap candidate weakens |
| **2 nodes (pciedngl_isr + fn@0x0B04)** | **EXPECTED.** Full live offload ISR set. Node[1].mask = chipcommon-wrap OOB slot. | row 161 confirmed; row 148 candidate identified with primary-source bit allocation |
| 3 nodes (incl. wlc_isr fn=0x1146D) | FullMAC chain ALSO ran. T299/T306 reframe needed. | row 161 falsified |
| 3+ unknown nodes | Unknown ISRs registered via indirect calls not caught by static reach. Worth identifying. | mixed |

| Pending-events word | Interpretation |
|---|---|
| 0 | Fw quiet, no HW events delivered. Consistent with WFI. |
| Non-zero | Major signal: HW event fired but never processed. AND with each node's mask to identify which ISR's bit fired. |

| sched_cc | Interpretation |
|---|---|
| 0x800 | Chipcommon class active. Consistent with T287c sched+0x88=0x18000000 at post-set_active. |
| 0x812 | core[2]/D11 class active. Consistent with T287c shift to 0x18001000 at post-T276-poll. |

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
    bcm4360_test298_isr_walk=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.298.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.298.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.298.journalctl.txt
```

If wedged before journalctl: on next boot,
`sudo journalctl -k -b -1 > phase5/logs/test.298.journalctl.txt`.

### Substrate prerequisites

- ⚠ Uptime is 46 min as of plan-write (13:30 BST), past the optimal 20-25 min
  clean window per KEY_FINDINGS row 83. **Cold cycle recommended before fire.**
- lspci was clean at 13:28 BST.
- Realistic plan: even on fresh substrate, row 85's noise belt sits upstream
  of every probe. Budget 2-4 attempts, each with cold cycle + likely SMC
  reset on null/wedge.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — module built 13:26 BST same session as source edits
2. ✓ Hypothesis stated above
3. ✓ PCIe state checked clean at 13:28 BST
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → (user) Cold cycle recommended; insmod within ≤2 min of cold-cycle boot
7. → Final advisor call BEFORE insmod (per advisor's PRE-T298 protocol note)

### Risk and recovery

- T298 is fully READ-ONLY w.r.t. BAR0 (no MMIO writes other than what other
  enabled tests do — T276 shared_info write, T284 premask attempt)
- T288A/T290B/T294 (the wedge-prone BAR0 probes) all DISABLED
- Substrate-noise null is the realistic mode failure (~75%+ on stale substrate)
- Watchdog cluster recovery rate downgraded per row 85; user SMC reset likely
  needed on wedge
- Worst case: same 4-null pattern as T294-T297. New information value would
  then be zero again, and we'd need to rethink (e.g., move probes earlier in
  init path, or pivot to truly substrate-independent static analysis).

## POST-TEST.298 (2026-04-27 14:19:30 BST fire, boot -1 — **FIRED CLEAN through all 9 probe stages. ISR-list = 2 nodes, frozen across post-set_active → t+90s. Substrate-noise belt PASSED on first attempt after 4-null T294→T297 streak — BAR2-only pivot vindicated. Late-ladder rmmod wedge required user SMC reset (orthogonal to probe success, T270-BASELINE pattern).**)

### Timeline (from `phase5/logs/test.298.journalctl.txt`, boot -1)

- `14:20:02` insmod → SBR → chip_attach → ramwrite → BusMaster on → FORCEHT → all pre-set_active probes (T276 shared_info, T284 premask, T287/287c sched_ctx, T298 ISR-walk) fired clean
- `14:20:02` `test.298 pre-write (pre-set_active) head=0 sched=0` (uninitialized — expected pre-ARM-release)
- `14:20:02` `test.219: calling brcmf_chip_set_active resetintr=0xb80ef000`
- `14:20:02` `test.276: shared_info written` + readback PASS
- `14:20:02` `test.298 post-set_active head=0x9627c sched=0x62a98 count=2 sched_cc=0x1 events_p=0x18109000` (ISR list populated; 2 nodes captured)
- `14:20:03` post-T276-poll, post-T278-initial-dump, t+500ms — **identical 2-node readout, no churn**
- `14:20:07` t+5s — identical
- `14:20:33` t+30s — identical
- `14:21:34` t+90s — identical (line 1514, last in journal)
- `~14:22:32` rmmod attempt → wedge (no entries past t+90s; user SMC reset required)

### Result table (primary-source, frozen across all 5 post-set_active stages)

| Node | TCM addr | next | fn | arg | mask (`1<<bit`) | Identification |
|---|---|---|---|---|---|---|
| 0 | 0x0009627c | 0x00096f48 | 0x00001c99 | 0x00058cc4 | **0x8 (bit 3)** | pciedngl_isr (T256 reproduces exactly) |
| 1 | 0x00096f48 | 0x00000000 | 0x00000b05 | 0x00000000 | **0x1 (bit 0)** | RTE chipcommon-class ISR (fn@0xB04+thumb) |

Summary line at every stage: `count=2 sched_cc=0x1 events_p=0x18109000 pending=0x0`.

### Hypothesis vs result

PRE-TEST.298 H1 ("2 nodes, pciedngl_isr + RTE-CC-class ISR") **CONFIRMED exactly**. Discriminator outcome: row 161 confirmed (live runtime ≠ FullMAC; no wlc_isr=0x1146D in list); row 148 candidate identified at primary-source level (RTE-CC-class ISR was allocated bit 0 of `oobselouta30` by BIT_alloc at registration).

### What's solid vs what needs care in interpretation

**Solid (primary-source, n=1 but stable across 5 timing stages within one fire):**
- 2-node ISR list, no FullMAC ISR — kills the "did wl_attach run?" question
- `pciedngl_isr` mask=0x8 reproduces T256 (strong cross-validation of probe mechanism)
- RTE-CC-class ISR fn=0x0b05 matches static reach analysis (hndrte_add_isr caller @ 0x63CF0 with class=0x800)
- Both ISR mask values are LIVE TCM-side OOB-allocation results — no chipcommon-wrap MMIO touched

**Needs care:**
- `pending=0` is **NOT a real read**. The macro's bounds check (`_t298_evp < 0xA0000`) rejected events_p=0x18109000 (it's a backplane MMIO addr, not a TCM offset), so `_t298_pending` stayed at its initial 0. Pending value is meaningless; only the events_p VALUE is informative.
- `sched_cc = 0x1` doesn't match the predicted class IDs (0x800/0x812). Per row 137 the slot counter is at +0xD0; +0xCC's semantics are unknown. Treat as new question, not as an answer.
- `events_p = 0x18109000` is chipcommon-wrap region (0x18100000+0x9000). Doesn't match any enumerated wrap stride from row 142. Worth identifying which register is at chipcommon-wrap+0x9000 (likely an interior CC-wrap reg — bcma docs).

### What this changes for next steps

- **KEY_FINDINGS row 148 update:** chipcommon-wrap OOB-selector mechanism is LIVE; RTE-CC-class ISR was allocated bit 0 at registration time. Wake-trigger source for bit 0 still unidentified.
- **KEY_FINDINGS row 161 update:** "live runtime ≠ FullMAC" CONFIRMED with primary-source ISR-list count (was previously CONFIRMED via reach analysis + test.290a chain walks; now also via direct ISR enumeration).
- **KEY_FINDINGS row 85 update:** stopping rule worked — first probe-bearing fire to clear noise belt since T293.
- **No need to re-fire T298** — result is stable. Need a NEW probe to make further progress.

### Files

- [phase5/logs/test.298.journalctl.txt](phase5/logs/test.298.journalctl.txt) (boot -1, 1514 lines, ends at t+90s readout)
- [phase5/logs/test.298.run.txt](phase5/logs/test.298.run.txt) (0 bytes — wedge during rmmod prevented redirect flush)

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

The next action is to draft a follow-on probe (TCM-side `oobselouta30`
shadow OR a host-side wake-event injection) — see "Next discriminator" in
the current-state block above. Do NOT fire test.288a (BAR0 chipcommon-wrap
read) — KEY_FINDINGS row 85 stopping rule confirmed valid by T298.
