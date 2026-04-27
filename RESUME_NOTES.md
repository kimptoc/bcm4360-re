# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 19:16 BST — PRE-TEST.301 drafted. User cold-cycled at ~19:14 BST; uptime 1 min, lspci clean (03:00.0 ASPM L0s L1 Enabled / 02:00.0 ASPM L1 Enabled / no MAbort / CommClk+). T301 = T300 re-fire UNCHANGED, with insmod targeted at uptime ~10-15 min (middle of row 83's 20-25 min clean window) instead of T300's ~2-min boundary. Discriminator: 3 outcomes per the advisor-blessed plan — wedge again at t+45s (bracket widened) vs wedge at t+90s+ AND sample 2 fires (T300 was n=1 outlier) vs wedge at t+90s+ AND sample 2 wedges (bracket is t+45s..t+90s). Plan committed below; fire scheduled for ~19:25-19:30 BST.

T299 FIRED 15:29:00 BST on boot -1 with full ASPM-disabled chain (cmdline `pcie_aspm.policy=performance` parsed, runtime sysfs flip applied at 15:27:57 before insmod; 03:00.0+02:00.0+root all `ASPM Disabled`). Probe ran clean through all 9 stages — IDENTICAL 2-node ISR readout to T298. Wedged at end-of-t+90s probe (boot -1 ended 15:31:05, ~7s after t+90s SUMMARY). User cold-boot/SMC reset; current uptime now ~30+ min, ASPM back to default. **H1 (ASPM = wedge cause) FALSIFIED.** **Wedge is the known [t+90s, t+120s] bracket** (KEY_FINDINGS row 104, T270-BASELINE pattern, reproduced T276/T287c/T298/T299) — NOT a "rmmod wedge" as POST-TEST.298 mistakenly claimed.

**T300 step 1 — static prep result.** Explore agent pass found: fw reads OOB Router pending-events at `0x18109100` LIVE via `fn@0x9936` (3-insn leaf: `ldr [sched+0x358]; ldr [+0x100]; bx lr`). Zero writers of this register into TCM exist anywhere reached from the live BFS. The ISR-list at `TCM[0x629A4]` (already enumerated by T298/T299) is the only OOB-bit→callback cache in TCM. Per-slot core-ID table at `sched+0xd0..` IS BAR2-readable and would cross-validate against host-side enumeration but does not advance the wake question. Per `t299_next_steps.md` §3, next move is A3 — single-purpose BAR0 OOB Router read with strict scope and exit before t+90s. Full report: `phase6/t300_static_prep.md`.

**Advisor catches that corrected the framing.** Two errors caught in T298/T299 post-test interpretation:
1. **"rmmod wedge" was always wrong.** `journalctl --list-boots` shows boot -5 ended `14:21:34` (T298) and boot -1 ended `15:31:05` (T299). Script `sleep 150` puts rmmod ~150s after insmod return — both boot-ends are well before that. Wedge is at end-of-t+90s probe (~7s after t+90s SUMMARY in T299; same in T298). rmmod never executed. **POST-TEST.298 incorrectly attributed the wedge to rmmod; it was actually the [t+90s, t+120s] bracket per row 104.** Update KEY_FINDINGS row 163 accordingly.
2. **T299 t+90s readout latency rose mid-stage.** T298 t+90s: all 4 readout lines at `14:21:34` (single second). T299 t+90s: `15:30:55→15:30:58` (3-second spread, 1s+ between consecutive prints). Each `printk` taking ~1s is anomalous — TCM read latency was rising for several seconds before silent kernel death. NEW signal vs T298 (which printed instantly then died). Could be the ASPM-disabled chain causing different bus-state behaviour, or could be substrate variation. n=1 fire with this latency pattern; not yet load-bearing.

**Result of T299.** ASPM-disabled chain (full: 03:00.0 + 02:00.0 + root port 00:1c.2) made ZERO difference to either the noise belt (T299 was the second clean fire in a row, BAR2-only path holding) OR to the [t+90s, t+120s] wedge bracket (T299 wedged at the same point T298/T287c/T276/T270-BASELINE did). Per row 104 + row 163 update: this wedge has been observed under 5 different module-param + cmdline combinations now and is fw-side, not host-side ASPM management.

**Cmdline correction history.** Four attempts at the same intent (force ASPM Disabled on the link):
1. v1: `pci=noaspm` — passive, cannot disable BIOS-enabled ASPM. Post-reboot LnkCtl showed L0s L1 still Enabled.
2. v2: `pcie_aspm=off` — *also* passive. Disables the kernel ASPM management subsystem ("PCIe ASPM is disabled" in dmesg) but BIOS-written LnkCtl bits remain. Post-reboot 2026-04-27 evening: 03:00.0 still `ASPM L0s L1 Enabled`, 02:00.0 still `ASPM L1 Enabled`. Per-device `link/` sysfs not created (subsystem disabled), policy knob locked at runtime.
3. v3: `pcie_aspm.policy=performance` — added to cmdline, `nixos-rebuild boot` ran cleanly, /proc/cmdline confirms it post-reboot — but kernel ignored the param. Sysfs `policy` still showed `[default]`, LnkCtl on 03:00.0 still `ASPM L0s L1 Enabled`, 02:00.0 still `ASPM L1 Enabled`. Subsystem WAS live this time (sysfs writable, `link/` dir present), so the param was at least parsed enough to keep the subsystem alive — just not applied. Likely cause: kernel-internal early default committed before `pcie_aspm` saw its module param.
4. **v4: runtime sysfs flip.** `echo performance | sudo tee /sys/module/pcie_aspm/parameters/policy` — actively disables. Verified 2026-04-27 post-third-reboot: policy sysfs now `default [performance] powersave powersupersave`. LnkCtl post-flip: 03:00.0 `ASPM Disabled`, 02:00.0 `ASPM Disabled`, 00:1c.0 root port `ASPM Disabled`. MAbort- everywhere. CommClk+ on 03:00.0 and 02:00.0, CommClk- on root (structural, not a fault).

T299 fire premise (PRE-TEST verification step 5) now satisfied via runtime path instead of boot path. The single-bit hypothesis is unchanged.

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

**Next discriminator (post-A1 resolution).** A1 was resolved via static
docs/EROM cross-check: `events_p = sched+0x358 = 0x18109000` is the
**ARM OOB Router core (BCMA core ID 0x367)**, per phase1 EROM walk +
Linux `bcma.h:76`. Distinct backplane agent (NOT chipcommon-wrap
interior). Host-side bcma enumeration (test.218) misses this core; fw
uses it via direct backplane access. Its `+0x100` register is the
pending-events bitmap fw reads to decide which OOB-routed ISR to wake.

What this resolution changes for direction-picking:

- "Candidate A — TCM-side `oobselouta30` shadow" was largely answered
  by T298 already: node[+0xC] mask values ARE the OOB allocation
  result. There is no separate "live oobselouta30 value" to chase
  (the register is routing config, not pending flags).
- The newly-identified target is the OOB Router pending register at
  0x18109100. Reading it is what would tell us which OOB lines are
  asserted at runtime. But that's a BAR0 read — and we don't yet know
  whether the BAR0 row 85 noise belt is chipcommon-wrap-specific or
  generalises to all backplane reads (T297 wedge was specifically on
  chipcommon-wrap+PCIE2-wrap; OOB Router is a different agent).

Three remaining candidates, awaiting user steer:

1. **A2 — More BAR2 sched_ctx mapping.** Cheap, speculative. Read
   sched+0xD0 (slot counter per row 137), +0xD4-table (per-slot core-id
   per row 138), the +0x300–0x350 gap, +0x35C onwards. Might find a
   TCM-resident dispatch table tying OOB bits → ISR nodes. Risk: low;
   yield: speculative.
2. **A3 — Read OOB Router pending-events at 0x18109100 via BAR0.**
   The actual wake-state register. Risk: row 85 noise belt may bite at
   any BAR0 chipcommon-wrap-region read — though OOB Router is a
   different agent than the chipcommon/PCIE2 wraps that wedged in T297.
   Single read, 1-shot scaffold; cold-cycle budget needed.
3. **B — Host-side wake-event injection.** DMA transfer over Phase 4B
   olmsg ring (already plumbed at shared_info), MSI assert, or
   `pci=noaspm` upstream lead from row 152. Most ambitious; biggest
   information yield if it works.

The user's earlier "1 pls" picked A as written in PLAN.md. With A1
resolved and the framing collapsed, the choice has changed shape. New
question to user: A2, A3, or B?

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

## PRE-TEST.299 (drafted 2026-04-27 ~15:00 BST — single-variable re-fire of T298 with `pci=noaspm` added to kernel cmdline. Tests whether ASPM is the cause of the KEY_FINDINGS row 85 substrate-noise belt. **REQUIRES USER ACTION:** edit `/etc/nixos/configuration.nix`, rebuild, reboot.)

### Goal — single bit of information

Does adding `pci=noaspm` to kernel cmdline change the substrate-noise / wedge profile observed in T288c/T294/T295/T296/T297/T298-rmmod? The leading hypothesis (KEY_FINDINGS row 152) is that ASPM-related PCIe link transitions cause the silent wedges; T269 listed `pci=noaspm` as candidate B but it was never tested.

### Hypothesis

H1 (primary): `pci=noaspm` reduces or eliminates the row 85 noise belt. Predictions:
- T298 probe still fires clean (sanity — same code path, only cmdline differs)
- ISR-list result identical to T298's (deterministic baseline)
- **rmmod completes without wedge** (T298's late-ladder wedge stops happening; run.txt becomes non-empty)
- Possibly: T298 fires clean even on stale substrate (would be a bonus — testable later)

H2 (alternative): `pci=noaspm` has no effect on the wedge profile — ASPM unrelated to the noise.

H3 (worst): `pci=noaspm` introduces NEW wedge mode (e.g. fw timeout because PCIe link can't power-manage). Recovery: revert cmdline, reboot.

### Diff vs T298 fire (2026-04-27 14:19 BST, fired CLEAN)

- IDENTICAL module params (T236, T238, T276, T277, T278, T284, T287, T287c, T298)
- IDENTICAL fire script
- IDENTICAL build (no rebuild needed; module unchanged)
- ONLY DIFFERENCE: kernel cmdline gains `pci=noaspm`

### REQUIRED USER ACTION

Cmdline edit + first rebuild done by Claude. User just needs to reboot.

After reboot, verify:
1. `cat /proc/cmdline | grep pcie_aspm` should show `pcie_aspm.policy=performance`
2. `sudo lspci -vvv -s 03:00.0 | grep LnkCtl` should show `ASPM Disabled` (NOT `ASPM L0s L1 Enabled`)
3. `sudo lspci -vvv -s 02:00.0 | grep LnkCtl` (parent bridge) should also show `ASPM Disabled`
4. lspci clean: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk'` should show no MAbort+/CommClk-
5. `cat /sys/module/pcie_aspm/parameters/policy` should show `default performance [powersave] powersupersave` form with `[performance]` selected (or similar — square brackets around `performance`)

If any of those fail, do NOT fire T299 — investigate first (the test premise depends on ASPM actually being off).

### Fire command (run AFTER reboot + cmdline verify)

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
    > /home/kimptoc/bcm4360-re/phase5/logs/test.299.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.299.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.299.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.299.journalctl.txt`.

### Discriminator outcomes

| Outcome | Interpretation | Next step |
|---|---|---|
| Clean fire + clean rmmod (run.txt non-empty + ISR list matches T298) | **H1 confirmed.** ASPM was the substrate-noise cause. Massively de-risks B1 (DMA injection) and A3 (OOB Router BAR0 read). | Pick B1, A2, or A3 with high confidence; proceed |
| Clean fire + late rmmod wedge (run.txt 0 bytes again, journalctl t+90s last) | **H1 partial.** ASPM not the cause of late-ladder wedge; row 85 noise belt may be unaffected. | Revert cmdline; pick A2 (cheap BAR2 mapping) as next-cheapest |
| Wedge upstream of T276 (substrate-noise null) | **H1 falsified.** ASPM not the cause; noise is something else. Independent confirmation that the noise belt is robust to this setting. | Revert cmdline; reconsider direction (A2 only safe choice) |
| New wedge mode (NixOS boot fails / PCIe link issues) | **H3.** Revert cmdline immediately; ASPM is load-bearing for system stability. | Revert and pick A2 |

### Substrate prerequisites

- After reboot, fresh substrate window per row 83 (~20-25 min).
- lspci verify before insmod.
- Single fire is sufficient — discriminator is binary on the rmmod-completion question.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same module that fired T298 clean
2. ✓ Hypothesis stated above
3. → PCIe state checked AFTER reboot (user)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → (user) Reboot with new cmdline; insmod within ≤2 min of boot for best substrate
7. → (no advisor call needed — this is a single-variable re-fire, plan is short)

### Risk and recovery

- T299 has no new probe code; risk profile is identical to T298 except for cmdline.
- If `pci=noaspm` itself breaks the system → revert `/etc/nixos/configuration.nix` line 22, `sudo nixos-rebuild boot`, reboot.
- If T299 fires identically to T298 but with a clean rmmod → strong signal to add `pci=noaspm` to project recommended setup.

### Why this is the right cheapest test

- One config edit + reboot. No new code, no new probe risk.
- Tests a hypothesis (row 152) that's been LIVE for ~3 days untested.
- Either result improves the next-step decision quality. H1-confirmed dramatically lowers B1/A3 risk; H1-falsified at least removes one variable.

## PRE-TEST.300 (drafted 2026-04-27 17:30 BST — A3 single-shot BAR0 read of ARM OOB Router pending-events at `0x18109100`. NO new probe types, NO BAR2 add-on, NO new module params beyond test300_oob_pending and test269_early_exit. Module REBUILT 2026-04-27 — verified test300 param via modinfo. **REQUIRES USER GO/NO-GO BEFORE FIRE.**)

### Goal — single bit of information

Is `OOB Router + 0x100` (the pending-events bitmap fw reads via `fn@0x9936`) ever non-zero between post-set_active and t+60s? Two readings:
- Sample 1 (post-set_active): immediately after `brcmf_chip_set_active` returns
- Sample 2 (t+60s): 60s into the dwell ladder, just before `bcm4360_test269_early_exit` jumps to ultra_dwells_done

Any non-zero value identifies which OOB bits hardware events have asserted — direct primary-source observation of the wake-trigger source for OOB bit 0 (RTE-CC ISR) or bit 3 (`pciedngl_isr`). Both samples zero tightens the "fw genuinely in WFI with no event delivery" reading.

### Hardware Fire Gate (per `t299_next_steps.md`)

| Gate item | Answer |
|---|---|
| Touches BAR0? | **YES** — single `pci_write_config_dword(BAR0_WINDOW, 0x18109000)` per sample, then `brcmf_pcie_read_reg32(devinfo, 0x100)`, then restore |
| BAR0 address + expected value | `BAR0 + 0x100` after window=0x18109000 → reads OOB Router pending-events register (offset 0x100 per fn@0x9936). Expected: 0x00000000 (fw in WFI) per row 116; non-zero ANY value identifies asserted OOB bits |
| Why OOB Router ≠ T297 wedge surfaces | OOB Router = BCMA core 0x367 at backplane 0x18109000 (per phase1 EROM walk + Linux `bcma.h:76`). T297 wedged at root-port `pci_disable_link_state` then T288A's wraps targeted chipcommon-wrap (0x18100000) and PCIE2-wrap (0x18103000) — **distinct backplane agents** in the same 0x181xx000 region. Whether the entire 0x181xx000 region is noise-belt territory or only chipcommon/PCIE2-wrap-specific is part of what this fire tests |
| Exit before [t+90s, t+120s] bracket | YES — `bcm4360_test269_early_exit=1` causes `goto ultra_dwells_done` at t+60s, skipping all further probes |
| Single bit of info | YES — "any non-zero across 2 samples?" |

### Module params (fire command)

- ENABLE: T236 (force seed), T238 (ultra dwells), T276 (shared_info), T277 (console decode), T278 (console periodic), T287 + T287c (sched_ctx fields), T298 (BAR2-only ISR walk — keep enabled to give the T298/T299 ISR-list reproduction baseline; if T300 wedges, journalctl will show whether T298's BAR2-only readout still matched the 2-node result), **T300 (the new BAR0 OOB Router read)**, **T269 early-exit (skips t+90s/t+120s/scaffolds)**
- DROP: T284 premask (no value-add for this fire); T288A wraps (RETIRED per row 85); T290A/B chain (BAR2-only, lower priority); T294/295/296/297 (all retired)

### Probe code (pcie.c lines 1098..1133, hooks at 4569 + 4942)

```c
#define BCM4360_T300_OOB_PENDING_READ(tag) do { \
    if (bcm4360_test300_oob_pending) { \
        u32 _t300_saved = 0xDEADC0DE, _t300_pending = 0xDEADC0DE; \
        pr_emerg("BCM4360 test.300: %s anchor-1 (about to save BAR0_WINDOW)\n", tag); \
        pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW, &_t300_saved); \
        pr_emerg("BCM4360 test.300: %s anchor-2 (saved=0x%08x; about to set OOB Router window=0x18109000)\n", tag, _t300_saved); \
        pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW, 0x18109000); \
        pr_emerg("BCM4360 test.300: %s anchor-3 (window set; about to read +0x100)\n", tag); \
        _t300_pending = brcmf_pcie_read_reg32(devinfo, 0x100); \
        pr_emerg("BCM4360 test.300: %s anchor-4 (pending=0x%08x; about to restore BAR0_WINDOW=0x%08x)\n", tag, _t300_pending, _t300_saved); \
        pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW, _t300_saved); \
        pr_emerg("BCM4360 test.300: %s SUMMARY pending@0x18109100 = 0x%08x (saved_win=0x%08x restored)\n", tag, _t300_pending, _t300_saved); \
    } \
} while (0)
```

Anchors-1..-4 fire at sub-step granularity so a wedge between any two anchors is observable in journalctl. Final `restore` is straight-line (no early return between save and restore). NO `brcmf_pcie_select_core` is called — bare BAR0_WINDOW save / write / read / restore.

### Hypothesis matrix

| Outcome | Interpretation | Updates |
|---|---|---|
| Sample 1 reads cleanly (0 or non-zero), Sample 2 also reads cleanly, BOTH zero | **H1: fw genuinely in WFI, no HW events delivered.** Tightens row 116. Forces project back to wake-injection (B), where the constraint walk says no enumerated sub-option has a mechanism — real impasse, may force a deeper re-read of the fw's expected event source | KEY_FINDINGS row 116 strengthens; row 148 wake-trigger question stays LIVE |
| Sample 1 or Sample 2 NON-ZERO | **MAJOR FINDING.** Identifies which OOB bits HW has asserted. AND with each ISR node's mask (T298 result: 0x1 = RTE-CC, 0x8 = pciedngl_isr) to identify which ISR's bit fired | row 148 wake-trigger source identified at primary-source level |
| Sample 1 wedges (last log = anchor-2 or anchor-3) | **OOB Router region IS noise-belt territory.** A3 fails. Forces project back to wake-injection (B) — which has the same constraint-walk problem as outcome 1. **Real impasse.** | KEY_FINDINGS row 85 widens (BAR0 noise belt covers OOB Router region too, not just chipcommon/PCIE2-wrap); A3 retired |
| Sample 1 reads cleanly, Sample 2 wedges | OOB Router region reachable at post-set_active but degrades by t+60s. Substrate-bound. Sample 1 result still load-bearing; project pivots based on it | row 85 nuance: OOB Router region reachable only early |
| Sample 1 anchor-2 or anchor-3 reads value 0xffffffff | window set silently failed OR OOB Router agent silently rejected the access. Discriminator: anchor-2 succeeded → window write happened → 0xffffffff is the agent's response. Anchor pattern lets us decide | row 85 widens with finer detail |
| New wedge mode upstream of post-set_active (substrate noise) | falls into the existing row 85 noise belt; T300 not the culprit. Cold cycle and re-fire | substrate variance |

### Recovery section

If sample 1 wedges (last journalctl entry = anchor-1, -2, or -3):
- Outcome 3: A3 fails. The next probe candidate is wake-injection (B), but the constraint walk says no enumerated sub-option has a mechanism. **Real impasse.** Options at that point:
  - re-read the fw's reset/init disasm for any host-side event the OOB Router DOES route from PCI config space (would need a new static pass)
  - try a B variant nobody has named yet (e.g., DMA-capable host write to a specific TCM region the fw polls outside ISRs)
  - accept the project is information-bounded at this point and move to the wl-comparison thread

If samples read cleanly with both zero:
- Outcome 1: most likely outcome per row 116. Same impasse path as above (B without mechanism), but with stronger confidence the fw is waiting on a real HW event vs spinning on something we missed. Worth one more advisor consult before pivoting

If sample 1 or 2 reads NON-ZERO:
- Outcome 2: jackpot. Decode bits via T298 mask map (bit 0 = RTE-CC ISR; bit 3 = pciedngl_isr; other bits = unidentified). Next probe would target identifying which HW event sets that specific bit (likely doable via static analysis of the ISR callback's argument struct)

### Substrate prerequisites

- Cold-boot was at 16:26:22 BST; uptime now ~1h+ — past the optimal 20-25 min clean window per KEY_FINDINGS row 83. **Recommend cold cycle before fire.**
- After cold-cycle reboot: `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'` — verify clean state
- insmod within ≤2 min of cold-cycle boot per row 83
- Single fire is sufficient — the discriminator is binary at sample 1

### Pre-fire checklist (CLAUDE.md)

1. ✓ Module REBUILT 2026-04-27 17:25 BST after T300 source edits — verified via `modinfo` (test300_oob_pending param visible)
2. ✓ Hypothesis matrix above
3. → PCIe state checked AFTER cold cycle (user)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → User cold cycle; insmod within ≤2 min of cold-boot
7. ✓ Final advisor call done (2026-04-27 evening) — design revised from 7 samples to 2

### Fire command (run AFTER cold cycle + lspci verify)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test298_isr_walk=1 \
    bcm4360_test300_oob_pending=1 \
    bcm4360_test269_early_exit=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.300.run.txt 2>&1
sleep 75
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.300.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.300.journalctl.txt
```

Note: `sleep 75` (vs T298/T299's `sleep 150`) because `test269_early_exit=1` should make the probe complete by ~t+62s and exit cleanly before the [t+90s, t+120s] bracket. If the early-exit works, rmmod should actually run for the first time in this campaign.

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.300.journalctl.txt`.

### Risk and recovery

- T300 BAR0 risk per row 85: OOB Router region untested; if same noise belt, sample 1 wedges (Outcome 3 above)
- If `test269_early_exit` works AND T300 reads cleanly: this would be the FIRST fire to complete rmmod since T269 baseline (a useful side-result regardless of T300 value)
- Worst case: cold-boot + SMC reset cycle (~30-60s wall clock for user)

**FIRED CLEAN through all 9 probe stages with ASPM fully disabled chain (cmdline `pcie_aspm.policy=performance` + runtime sysfs `policy=performance` flip applied 15:27:57 before insmod). ISR-list = 2 nodes, IDENTICAL to T298. Wedged at end-of-t+90s probe — same [t+90s, t+120s] bracket as T270-BASELINE/T276/T287c/T298. H1 (ASPM = wedge cause) FALSIFIED. T299 t+90s readout latency rose mid-stage (1s/print vs T298's all-same-second).**)

### ASPM state at fire time (boot -1)

Verified from `journalctl -b -1`:
- `15:25:20` Kernel cmdline: `pci=noaer pcie_aspm.policy=performance intel_iommu=on iommu=strict ...`
- `15:27:57` `sudo tee /sys/module/pcie_aspm/parameters/policy` (Claude ran this after first verifying boot, before insmod — runtime flip ACTIVE)
- `15:29:00` insmod
- During probe: `test.158: ASPM disabled; LnkCtl ... ASPM-bits-after=0x0` (driver-side disable on 03:00.0, always-on)
- During probe: `test.188: root port 0000:00:1c.2 ASPM=0x0 CLKREQ=off` (driver-side disable on root port)
- Plus runtime sysfs flip → 02:00.0 bridge ASPM Disabled (extra coverage vs T298 baseline)

**T299 had strictly more ASPM-disabled coverage than T298**, both for kernel cmdline (T299: `pcie_aspm.policy=performance` parsed; T298: nothing) and for 02:00.0 bridge (T299: sysfs flip → Disabled; T298: bridge unchanged). T298 already had 03:00.0 + root port disabled by always-on driver code. The delta T299 added did not change wedge behaviour — **wedge is independent of ASPM state on the entire upstream chain**.

### Timeline (from `phase5/logs/test.299.journalctl.txt`, boot -1, 1502 lines)

- `15:29:00` insmod → SBR → chip_attach → ramwrite → BusMaster on → FORCEHT → all pre-set_active probes fired clean
- `15:30:10` post-set_active, post-T276-poll, post-T278-initial-dump, t+500ms — **identical 2-node readout to T298, no churn**
- `15:30:11` t+5s, t+30s, t+35s, t+45s — identical
- `15:30:23` t+60s (no probe output — T249/T250/T251/T252/T253/T255/T256 all disabled in this fire)
- `15:30:54` t+90000ms dwell + t+90s test.278/284/287/287c readout (1-second prints)
- `15:30:55-58` t+90s test.298 readout — **lines spread across 3 seconds (1s+ between consecutive node[0]/node[1]/end/SUMMARY prints)** — TCM read latency rising
- `15:30:58` t+90s test.298 SUMMARY — **last log line**
- `15:31:05` boot -1 ends (silent kernel death; ~7s of no output)
- Cold boot at `16:26:22` (user SMC reset)

The script's `sleep 150` would put rmmod at ~`15:32:00`; rmmod NEVER ran. T298's `~14:22:32 rmmod attempt → wedge` framing was incorrect inference — boot -5 (T298) ended `14:21:34`, in the same end-of-t+90s position as T299.

### Result table (primary-source, frozen across all 5 post-set_active stages)

| Node | TCM addr | next | fn | arg | mask (`1<<bit`) | Identification |
|---|---|---|---|---|---|---|
| 0 | 0x0009627c | 0x00096f48 | 0x00001c99 | 0x00058cc4 | **0x8 (bit 3)** | pciedngl_isr (T256 reproduces; **identical to T298**) |
| 1 | 0x00096f48 | 0x00000000 | 0x00000b05 | 0x00000000 | **0x1 (bit 0)** | RTE chipcommon-class ISR (**identical to T298**) |

Summary line at every stage: `count=2 sched_cc=0x1 events_p=0x18109000 pending=0x0` — bit-for-bit identical to T298.

### Hypothesis vs result

| H | Predicted | Observed | Verdict |
|---|---|---|---|
| H1 (primary, row 152): pcie_aspm disable reduces noise belt + clears late wedge | clean fire + clean rmmod | clean fire (✓), late wedge identical to T298 (✗) | **FALSIFIED** for the [t+90s, t+120s] wedge bracket; INDETERMINATE for noise belt (only n=2 clean fires in a row, both BAR2-only — the BAR2-only-vs-ASPM signals are confounded) |
| H2 (alt): no effect | mixed | matches | weakly supported |
| H3 (worst): new wedge mode | revert immediately | did not occur | rejected |

### What this changes

- **KEY_FINDINGS row 152 update needed:** ASPM-as-wedge-cause is FALSIFIED for the [t+90s, t+120s] bracket. The hypothesis stood untested for ~3 days; T299 is the first direct test and it negates.
- **KEY_FINDINGS row 163 update needed:** T298 entry's "Late-ladder rmmod wedge (T270-BASELINE pattern)" framing is wrong — wedge is at end-of-t+90s probe, not rmmod. Cite boot-end timestamps. **Crucial correction** — rmmod never even ran in T298, T299, or any of the [t+90s, t+120s] bracket fires. The "late ladder" IS the [t+90s, t+120s] bracket; there's no separate rmmod wedge phenomenon to worry about.
- **KEY_FINDINGS row 104 update:** add T299 to the reproduction list (now: T270-BASELINE, T276, T287c, T298, T299 — 5 fires). Robust phenomenon.
- **NEW signal (n=1, weak):** T299 t+90s readout TCM latency was ~1s/print (T298 was instant). Could indicate ASPM-disabled state changes bus latency in a way that's neutral for clean fire but visible at the specific bus-state moment we're sampling. Worth re-checking on next fire (if next fire shows instant t+90s prints with ASPM left at default, signal narrows; if also slow, signal weakens).
- **What is NOT changed:** The 2-node ISR list and OOB allocations (mask=0x8 / mask=0x1) reproduce exactly. Those are robust facts. The wake-trigger source for OOB bit 0 is still LIVE — T299 added zero information toward it.

### Files

- [phase5/logs/test.299.journalctl.txt](phase5/logs/test.299.journalctl.txt) (boot -1, 1502 lines, ends at t+90s SUMMARY)
- [phase5/logs/test.299.run.txt](phase5/logs/test.299.run.txt) (0 bytes — silent kernel death prevented redirect flush)

### Next direction (still candidates A2 / A3 / B per RESUME_NOTES current-state list)

T299 closes the row 152 question. The choice of next probe is unchanged shape — A2 (BAR2 sched_ctx mapping), A3 (OOB Router pending-events at 0x18109100 via BAR0), or B (host-side wake-event injection). H1-falsified does NOT make B more likely (ASPM was supposed to *de-risk* B; falsified means B is at the same risk it was before T299).

Awaiting user steer on direction. The advisor flagged a cheaper precursor: re-fire with `bcm4360_test269_early_exit=1` (skip everything past t+60s) to discriminate "[t+90s, t+120s] wedge is probe-induced" vs "[t+90s, t+120s] wedge is substrate-side regardless of probe activity". If that single param flip avoids the wedge → next probe should not include t+90s readout. If wedge persists → fw-side, ignore probe, pick A/B normally.

## POST-TEST.300 (2026-04-27 17:41 BST — A3 OOB Router pending read FIRED. Sample 1 SUCCEEDED with `pending=0x00000000`. Sample 2 NEVER RAN — silent kernel wedge at ~t+45s, well before the t+60s sample 2 hook. Machine auto-rebooted (no SMC reset needed) — boot -1 ended 17:42:30, boot 0 started 17:43:23.)

### Headline result

- **OOB Router agent at backplane 0x18109000 IS reachable via BAR0 window without wedging.** Sample 1 completed all 4 anchors cleanly:
  - anchor-1: about to save BAR0_WINDOW
  - anchor-2: saved=0x18102000; about to set window=0x18109000
  - anchor-3: window set; about to read +0x100
  - anchor-4: pending=0x00000000; about to restore
  - SUMMARY: `pending@0x18109100 = 0x00000000 (saved_win=0x18102000 restored)`
  - **No t+0 wedge.** Distinct from T297-style chipcommon-wrap (0x18100000) / PCIE2-wrap (0x18103000) BAR0 noise belt. The OOB Router (BCMA core 0x367) is BAR0-reachable.
- **Sample 1 reads `pending=0` at post-set_active.** No HW OOB events asserted at that moment. Per T298 mask map: bit 0 (RTE-CC ISR) NOT pending, bit 3 (pciedngl_isr) NOT pending.
- **Sample 2 at t+60s never ran.** Silent kernel wedge at ~t+45s, before T269 early-exit could fire.

### ASPM state at fire time

03:00.0 `ASPM L0s L1 Enabled`, 02:00.0 `ASPM L1 Enabled` (defaults; no runtime sysfs flip this fire — T299 falsified the ASPM-as-cause hypothesis, so reverted to default).

### Timeline (boot -1, `phase5/logs/test.300.journalctl.txt`, 1472 lines)

- `17:39:21` boot start
- `17:41:22` insmod (`module_init` entry)
- `17:41:25` brcmf_chip_attach, BAR0 alive (0x15034360)
- `17:41:41` post-set_active stage — **T298 count=1** (only RTE-CC ISR registered yet — pciedngl_isr not yet added; T298/T299 saw count=2 at this stage; timing variance vs `hndrte_add_isr` ordering, **first observation of count=1 at post-set_active in this campaign**)
- `17:41:41` **T300 sample 1: 4 anchors + SUMMARY all clean — `pending=0x00000000`**
- `17:41:43` post-T276-poll → count=2 (pciedngl_isr now registered, mask=0x8). Steady state for the rest of the run.
- `17:41:43→49` post-T278-initial-dump, t+500ms, t+5s — all clean, count=2 stable
- `17:42:14` t+30s probes — all clean, count=2 stable
- `17:42:20` t+35000ms dwell
- `17:42:30` **t+45000ms dwell — LAST LOG LINE**
- `17:42:30` boot -1 ends (silent kernel death between t+45s dwell print and the would-be next probe stage)
- `17:43:23` boot 0 starts (auto-recovery, no SMC reset)

### Hypothesis matrix vs result

| Outcome (from PRE-TEST.300) | Observed? |
|---|---|
| Sample 1 + Sample 2 BOTH zero (H1: WFI, no event) | **Partial** — sample 1 = 0; sample 2 missing |
| Sample 1 NON-ZERO | NO |
| Sample 1 wedges (anchor-2/3) — OOB Router IS noise belt | **NO — falsifies row 85 extension to OOB Router** |
| Sample 1 clean, Sample 2 wedges | NOT applicable (wedge was earlier than sample 2, not at sample 2) |
| anchor-2/3 reads 0xffffffff | NO — pending was the canonical 0x00000000 |
| New wedge mode | wedge happened at ~t+45s, **EARLIER than usual [t+90s, t+120s] bracket** — new datapoint |

### What this changes / leaves open

- **KEY_FINDINGS row 85 narrows.** BAR0 noise belt is real for chipcommon-wrap (0x18100000) and PCIE2-wrap (0x18103000) but does NOT extend to OOB Router (0x18109000). OOB Router BAR0 read worked first try at post-set_active. Row 85 needs a "scope" qualifier added.
- **KEY_FINDINGS row 116 strengthened (n=1).** Sample 1 reads pending=0 — concrete primary-source evidence that no OOB events are asserted at post-set_active. Combined with row 161 (no FullMAC `wlc_isr` registered) this further tightens the "fw genuinely in WFI" reading.
- **NEW signal: wedge at ~t+45s, not [t+90s, t+120s].** First fire to wedge before t+90s in this campaign. Possible causes (n=1, can't choose):
  1. Substrate variance — wedge bracket may be wider than [t+90s, t+120s]
  2. T300 BAR0 read at post-set_active had a delayed effect, brought wedge forward
  3. Different ASPM state (T300 = default Enabled; T299 = sysfs flip Disabled) shifted timing
  4. Cold-cycle window timing — insmod at 17:41:22 was ~2 min after boot at 17:39:21, ON the row 83 boundary
- **T269 early-exit DID NOT GET A CHANCE TO RUN.** The wedge fired at t+45s, before the early-exit hook at t+60s. So the original T269-precursor question (probe-induced vs substrate wedge) is still unanswered for the [t+90s, t+120s] bracket — this fire wedged earlier instead.
- **Sample 2 question still LIVE.** Whether OOB pending ever transitions from 0 to non-zero between post-set_active and ~t+90s is unanswered; we got 1 of 2 planned samples.

### Files

- [phase5/logs/test.300.journalctl.txt](phase5/logs/test.300.journalctl.txt) (boot -1, 1472 lines, ends at t+45000ms dwell)
- [phase5/logs/test.300.run.txt](phase5/logs/test.300.run.txt) (0 bytes — silent kernel death)

### Substrate state at writeup

Boot 0 started 17:43:23, uptime ~2 min. PCIe clean: 03:00.0 ASPM L0s L1 Enabled (default), 02:00.0 ASPM L1 Enabled (default), MAbort- everywhere, CommClk+ on bridge. No leftover dirt.

### Next direction (recommended — option 1, after advisor consult)

**Recommendation: re-fire T300 UNCHANGED with stricter substrate-window discipline.** Advisor pushed back on the earlier "move sample-2 to t+30s" inclination, on these grounds:

- The early wedge at ~t+45s is **n=1**. Five prior bracket reproductions all hit at t+90s+. Treating t+45s as a confirmed bracket-widening on n=1 means redesigning around a possibly-phantom signal.
- Re-fire unchanged is the **discriminator**: 3 distinguishable outcomes (a) wedge again at t+45s → bracket really widened; (b) wedge at t+90s+ AND sample 2 fires → got the missing data + n=2 on sample 1; (c) wedge at t+90s+ AND sample 2 wedges → narrows the wedge bracket to the t+60s..t+90s region.
- Moving sample 2 earlier doesn't add **content** information (fw is silent — `pending` should stay 0 at any sample point absent an externally-injected event), only sample-collection-reliability. We don't yet know we need that reliability.

**Pre-fire constraint:** target the MIDDLE of row 83's 20-25 min clean window (insmod ~10-15 min after cold-boot), not the edge. T300 fired at ~2 min uptime, on the boundary — that removes one of the four candidate explanations (cold-boot timing) for the early wedge.

### Other candidates (held)

- **Move sample 2 earlier in the dwell ladder** — held until option 1 produces n=2 on the wedge timing. Then make the call with data.
- **A2 — BAR2 sched_ctx mapping** (sched+0xD0 slot counter, +0xD4 per-slot core-id) — held; cheap and no BAR0 risk, but speculative yield. Better discriminator value comes from option 1.

Awaiting user **GO/NO-GO on T301 (T300 re-fire, no code change)**. If GO, the fire steps are:
1. User cold cycle (or this boot, but row 83 says cleanest is post-cold-boot)
2. lspci verify (this Claude can do)
3. Wait until ~10-15 min uptime
4. Same fire command as PRE-TEST.300 (no rebuild, no params changed)
5. Auto-capture journalctl post-recovery

## PRE-TEST.301 (drafted 2026-04-27 19:16 BST — T300 re-fire UNCHANGED, with stricter substrate-window discipline. Cold cycle done by user at ~19:14 BST; insmod targeted for ~19:25-19:30 (uptime ~10-15 min, middle of row 83's 20-25 min clean window). NO code changes, NO param changes vs T300. Tests whether T300's t+45s wedge was n=1 substrate variance vs a real bracket-widening.)

### Goal — single bit of information

Three distinguishable outcomes (per advisor consult preserved in POST-TEST.300):

| Outcome | Interpretation | Next step |
|---|---|---|
| Wedge again at ~t+45s, sample 2 still missing | **Bracket widened to t+45s.** T300 result was not an outlier; substrate wedge bracket is wider than [t+90s, t+120s] | Move sample 2 earlier (t+30s) on T302 |
| Wedge at t+90s+ AND sample 2 fires cleanly | T300 wedge was n=1 substrate variance. Got the missing data + n=2 on sample 1 = 0 | If sample 2 also = 0, project pivots back to wake-injection (B); if non-zero, identify which OOB bit |
| Wedge at t+90s+ AND sample 2 wedges | Wedge bracket really is [t+45s..t+90s]; T300 hit early edge of it | Sample 1 reliable, Sample 2 unreliable — rethink ladder placement |

### Diff vs T300 fire (2026-04-27 17:41 BST, sample 1 clean / sample 2 missing / wedge at ~t+45s)

- IDENTICAL module (no rebuild — T300 params already in `phase5/work/.../brcmfmac.ko`)
- IDENTICAL fire script
- IDENTICAL kernel cmdline (default ASPM — T299 falsified ASPM-as-cause, no need to flip)
- ONLY DIFFERENCE: insmod timing. T300 fired at uptime ~2 min (boundary of row 83 clean window). T301 targets uptime ~10-15 min (middle of window). Removes the "cold-boot timing" cause from POST-TEST.300's 4 candidate explanations for the t+45s wedge.

### Substrate state at writeup (19:16 BST)

- Cold-boot at 19:14:57 BST; uptime 1 min
- 03:00.0: `ASPM L0s L1 Enabled` (default), MAbort-, CommClk+, x1 @2.5GT/s
- 02:00.0: `ASPM L1 Enabled` (default), MAbort-, CommClk+, x1 @5GT/s
- modinfo confirms `bcm4360_test300_oob_pending` and `bcm4360_test269_early_exit` params present

Verified clean. No reboot required between writeup and fire.

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same module bits that fired T300 clean
2. ✓ Hypothesis matrix above (re-stated from POST-TEST.300 advisor consult)
3. ✓ PCIe state checked (just done — clean)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → Wait for uptime ~10-15 min, then insmod
7. ✓ No advisor call needed — re-fire of an advisor-blessed plan

### Fire command (run when uptime hits ~10-15 min, i.e. ~19:25-19:30 BST)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test298_isr_walk=1 \
    bcm4360_test300_oob_pending=1 \
    bcm4360_test269_early_exit=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.301.run.txt 2>&1
sleep 75
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.301.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.301.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.301.journalctl.txt`.

### Risk and recovery

- Identical risk profile to T300. Worst case: another silent kernel wedge requiring auto-recovery or SMC reset.
- T300 was the FIRST successful BAR0 read of OOB Router (0x18109000). Reproduces the same scaffold; high confidence sample 1 will read cleanly again.

### What this fire does NOT do

- Does not advance the wake-trigger source identification (sample 1 = 0 was already observed)
- Does not test ASPM hypothesis (T299 already falsified)
- Does not move sample 2 timing (held until n=2 on the wedge bracket)
- Does not test A2 (BAR2 sched_ctx mapping) or B (host-side wake-event injection)

Pure timing/substrate discriminator. Cheap (no code change) + necessary (need n=2 before redesigning around t+45s).

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
