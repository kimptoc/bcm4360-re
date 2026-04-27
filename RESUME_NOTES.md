# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 — live offload runtime distinguished from FullMAC dead code)

**Model.** The blob carries two runtimes; the live one is HNDRTE/offload, not
the `wl_probe → wlc_*` FullMAC chain. Firmware boots, populates `sched_ctx`,
and idles at WFI as normal. The earlier "wake gate STRUCTURALLY CLOSED"
framing applies to the FullMAC code path, not the live offload runtime.

**What just changed.** T299–T306 (this session) traced the live BFS, ruled
out FullMAC reachability via static heuristics, and reconciled with empirical
test.290a chain-walks (n=2, never populated) and test.287c sched_ctx readings
(stable across t+5/30/90 s). Full synthesis lives in
[phase6/t299_t306_offload_runtime.md](phase6/t299_t306_offload_runtime.md).
Load-bearing facts promoted to KEY_FINDINGS (new row plus SUPERSEDED-SCOPE
markers on rows 159 / 160).

**Next discriminator.** `test.288a` (chipcommon-wrap + PCIe2-wrap OOB-selector
read, already compiled into the driver, never fired). Targets KEY_FINDINGS
row 148's untested chipcommon-wrapper wake hypothesis. Read-only, single
module-param flag, no rebuild required.

**What not to retry blindly.**

- More static-disasm probes against the FullMAC chain — treat it as dead in
  offload mode. The session already hit the convergence-without-progress
  failure mode there.
- More PCIe2 mailbox / D11 INTMASK wake probes — both empirically and
  structurally exhausted (rows 125 / 159-superseded).
- Insmod cycles on stale substrate without budgeting for the ~3/4 null-fire
  rate per row 85.

**Substrate state.** Substrate-null cluster T294/T295/T296 from prior
sessions is unresolved but no longer strategically blocking the new direction.

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
