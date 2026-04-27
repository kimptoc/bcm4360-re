# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 — PRE-TEST.298 ready: BAR2-only ISR-walk probe, awaiting user go-ahead + cold cycle)

**Model.** The blob carries two runtimes; the live one is HNDRTE/offload, not
the `wl_probe → wlc_*` FullMAC chain. Firmware boots, populates `sched_ctx`,
and idles at WFI as normal. The earlier "wake gate STRUCTURALLY CLOSED"
framing applies to the FullMAC code path, not the live offload runtime.

**What just changed.** User-supplied direction in
[t297_next_steps.md](t297_next_steps.md) selected the BAR2-only relocation
branch with one preceding static pass. Static pass executed
([phase6/t298_static_pass_findings.md](phase6/t298_static_pass_findings.md))
and ANSWERED the load-bearing question: yes, each registered ISR's
OOB-allocated bit is shadowed at `node[+0xC]` of its entry in the linked
list at TCM[0x629A4]. Reading the list via BAR2 gives the chipcommon-wrap
OOB allocation result without touching `wrap+0x100`.

Static enumeration of `hndrte_add_isr` callers in the fw blob found exactly
3 sites:

- pcidongle_probe @ 0x1F28 → pciedngl_isr (0x1C99) — LIVE per T256 (bit 3)
- RTE init @ 0x63CF0 → RTE chipcommon-class ISR thunk fn@0xB04 (0xB05),
  with class arg `r1=0x800=CHIPCOMMON` hard-coded — likely LIVE
- FullMAC `wl_attach` @ 0x67774 → wlc_isr (0x1146D) — DEAD per T299/T306

`bcm4360_test298_isr_walk` driver code added (BAR2-only dynamic walk of
the list, sched_ctx[+0xCC], pending-events word). Built clean; pushed.
PRE-TEST.298 plan written below; awaiting user go-ahead + cold cycle.

**Next discriminator.** `test.298` BAR2-only ISR-walk. Expected outcome
(see PRE-TEST.298 below): 2 nodes — pciedngl_isr + RTE-CC-class ISR. The
chipcommon-class ISR's mask reveals which OOB slot BIT_alloc allocated
from chipcommon-wrap+0x100 at registration — primary-source resolution of
KEY_FINDINGS row 148's wake hypothesis from the TCM side.

**What not to retry blindly.**

- More static-disasm probes against the FullMAC chain — treat it as dead in
  offload mode. The session already hit the convergence-without-progress
  failure mode there.
- More PCIe2 mailbox / D11 INTMASK wake probes — both empirically and
  structurally exhausted (rows 125 / 159-superseded).
- **Any further BAR0-touching probe (chipcommon, PCIE2, or wrapper) before
  the direction decision is on disk.** Row 85's stopping rule remains in
  force after T297; firing another BAR0 read just to "see if substrate is
  better" is the same anti-pattern that produced the 4-null streak.
- Insmod cycles on stale substrate without budgeting for the ~3/4 null-fire
  rate per row 85.

**Substrate state.** lspci clean at 12:58 BST after cold cycle + SMC reset
following T297 wedge. Uptime 15 min, fresh window in principle — but row 85
shows substrate freshness alone does not reliably get past the test.158 /
test.188 / test.193 / test.225 noise belt.

---

## PRE-TEST.297 (2026-04-27 ~11:45 BST — first hardware fire of the new
direction. READ-ONLY probe to characterise wrapper-agent OOB-selector state
at multiple init timings via the never-fired test.288a; reconfirm test.290a
chain-never-populated past n=2 stopping rule; reconfirm test.287c sched_ctx
stability past 90 s.)

### Goal — single bit of information

Does the AI-backplane wrapper agent OOB-selector at chipcommon-wrap+0x100
(`oobselouta30`) carry a non-zero / non-default routing pattern across
init stages? A non-default pattern would identify the wake-routing register
the prior session's row 148 hypothesised but never empirically tested. A
zero / unchanged pattern would weaken the chipcommon-wrap candidate and
push attention to candidate #4 (PCIe MSI plumbing) or #5 (direct memory
polling).

### Hypothesis

The wrapper agent registers will read sensible non-zero values once
`set_active` runs (the scheduler-context wrappers populate at that point,
per test.287c), and will be stable across the t+5/30/90 s timings just
like sched_ctx is. If `oobselouta30` carries a pattern matching `[ARM-CR4
IRQ index] | (chipcommon-source-bit << ofs)`, the chipcommon-wrap wake
candidate strengthens.

### Diff vs T295 fire

- ADD `bcm4360_test288a_wrap_read=1` (the key new probe — never fired
  before)
- ADD `bcm4360_test290a_chain=1` (read-only, push n=2 → n>3)
- DROP `bcm4360_test290b_cc_write=1` (the wedge-prone chipcommon-write
  probe; was the cause of T293 firing-#4 wedge)
- DROP `bcm4360_test294_cc_ro_probe=1` (was a discriminator for the
  T290B anomaly; no longer relevant since T290B is dropped)
- KEEP T276/T277/T278 console scaffold, T284 premask, T287/T287c
  sched_ctx, T236/T238 timing scaffold

This makes T297 a fully read-only probe — no MMIO writes other than
BAR0_WINDOW save/restore. Substrate-noise is still possible (per row 85)
but no hardware-write wedge can occur.

### Substrate prerequisites

- ⚠ Uptime is 5h+ (stale substrate). Per KEY_FINDINGS row 85, fresh
  insmod-within-2-min-of-cold-boot gives ~1/4 fires reaching probe site;
  stale is worse. The user should cold-cycle for best signal-to-noise.
  If user prefers to fire on the current stale substrate, that's an
  explicit accept of higher null-fire risk for this attempt.
- Verify `lspci -vvv -s 03:00.0` is clean immediately before insmod
  (already confirmed clean at 11:42).
- Realistic plan: 2-4 attempts, each requiring full cold cycle + likely
  SMC reset on null/wedge.

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
    bcm4360_test290a_chain=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.297.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.297.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.297.journalctl.txt
```

If wedged before journalctl: on next boot,
`sudo journalctl -k -b -1 > phase5/logs/test.297.journalctl.txt`.

### Discriminator outcomes

| `test.288a` chipcommon-wrap+0x100 (oobselouta30) reading | Reading |
|---|---|
| Non-zero, changes across stages | **Wake-routing live and dynamic** — chipcommon-wrap wake hypothesis strengthens; trace which bits change at which stage |
| Non-zero, stable across stages | **Static OOB routing** — captures the routing decision; characterise the bit pattern |
| All zeros at every stage | **Chipcommon-wrap is NOT the wake gate** — push attention to PCIe MSI / direct polling candidates |
| Wedges before any T288a output | Substrate noise; null fire — cold cycle and retry |

`test.290a` (read-only chain walk) outcomes:
- `wrong-node-fn-not-wlc-isr` again at all stages → confirms T304 dead-chain finding past n>3 stopping rule
- `complete` with non-zero base → contradicts T299/T306 dead-chain finding; major reframe needed

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — module built 22:38 same day as source 22:37
2. ✓ Hypothesis stated above
3. ✓ PCIe state checked (clean at 11:42)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → (user) Cold cycle recommended; insmod within ≤2 min of cold-cycle boot

### Risk and recovery

- T297 is fully READ-ONLY (no MMIO writes other than BAR0_WINDOW save/restore)
- No wedge-prone chipcommon write probes enabled
- Substrate-noise null is the realistic mode failure (~75%+ on stale substrate)
- Watchdog n=5/5 NOT auto-recovering recent wedges — user SMC reset will be
  needed if a substrate-noise wedge does occur

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

## POST-TEST.297 (2026-04-27 11:47 BST → recovered ~12:42 BST after user SMC reset)

### Result — substrate-noise null fire #4 (T294/T295/T296/T297 cumulative)

**Wedge point:** `test.188: root-port pci_disable_link_state returned —
reading LnkCtl` — 1319th and final journal line of boot -1 at
11:47:35 BST. The pci_capability_read_word() that should have followed
to print "after=0xNNNN" never returned. Same code site that T295 wedged
on (one operation later in the function), and one operation upstream of
T296's `chip=0x4360 chipid` print. Adds the 7th distinct wedge point
along the Phase 5 init code path.

**Recovery profile:** consistent with the recent cluster — watchdog did
NOT auto-recover; user-initiated SMC reset + cold cycle required;
~55-minute gap between wedge (11:47:35) and clean boot (12:42:43).

**Instrumentation that fired:** zero. Wedge is upstream of test.276
(shared_info), test.284 (premask), test.287/287c (sched_ctx), test.288a
(wrapper-agent OOB read — the new probe), test.290a (chain walk).
**No bit of new information was gathered.** Hypothesis untested,
discriminator outcomes table N/A.

### Hypothesis vs result

PRE-TEST.297 hypothesis was that wrapper-agent OOB-selectors at
`chipcommon-wrap+0x100` would carry sensible values across init stages,
strengthening the row 148 chipcommon-wrap wake candidate. Hypothesis
**not addressed** — fire never reached the probe. No update to row 148.

### Process finding (the load-bearing observation)

T297 was a chipcommon-wrap + PCIE2-wrap BAR0 read. KEY_FINDINGS row 85,
written ~5 hours before T297 fired, had explicitly stopped further BAR0
work: *"pivot to a different MMIO surface (TCM, not chipcommon BAR0)
before further hardware fires."* The PRE-TEST.297 plan acknowledged
substrate-noise risk but did not reconcile with the row 85 stopping
rule. T297's null is the 4th confirmation that the rule was correct —
not a reason to retry the same probe. This bypass pattern is now
documented in row 85.

### Files

- [phase5/logs/test.297.journalctl.txt](phase5/logs/test.297.journalctl.txt) (boot -1 capture)
- [phase5/logs/test.297.run.txt](phase5/logs/test.297.run.txt) (0-byte — insmod wedged before redirect flushed)

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
