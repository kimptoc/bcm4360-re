# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 12:1x BST, POST-TEST.247 — first shared-struct probe landed clean pre-FORCEHT. Struct at TCM[0x80000..0x80047] unchanged across all 23 dwells (t+100ms..t+90000ms); ramsize-4 unchanged at `0xffc70038`; tail-TCM unchanged. Wedge at [90s, 120s] — matches T245/T246 pre-FORCEHT-probe baseline. SMC reset required. Boot 0, uptime ~1 min. Matrix row 3 fired: (S1) minimal-signature falsified, (S2) fw-stalled-pre-allocate consistent. Direction pending advisor on whether to Phase-6-pivot or add cheap intermediate probes first.)

### What test.247 landed (facts)

```
test.247: pre-FORCEHT pre-placed shared-struct at TCM[0x80000] (72 bytes, version=5 @offset 0, rest=0)
test.247: pre-FORCEHT readback = 00000005 00000000 ...00000000   [18 u32s, write landed as intended]

All 23 per-dwell polls (t+100ms..t+90000ms):
  test.247: struct[0x80000..0x80047] = 00000005 00000000 ... 00000000   [UNCHANGED across all dwells]
  test.239: sharedram_ptr=0xffc70038                                     [UNCHANGED across all dwells]
  test.240: tail-TCM[-64..-8] = <NVRAM trailer text>                     [UNCHANGED across all dwells]

Last journal line: Apr 23 11:48:18 t+90000ms dwell ladder entries.
```

### What test.247 settled (facts only — interpretation deferred to advisor)

- **Fw runs ≥90s post-set_active but touches NONE of the observed TCM regions.** Three independent observation windows — struct region `[0x80000..0x80047]`, ramsize-4, ramsize-tail `[-64..-8]` — all report unchanged across 23 polls. This is a stronger statement than "(S1) falsified" alone.
- **BAR2 write of a 72-byte struct into dead TCM lands cleanly at pre-FORCEHT.** Readback matches written bytes; consistent with T245/T246 BAR2 PASS.
- **Probe cost stays constant.** T245 alone, T246 (T245+T246), T247 (T247 only, larger footprint) all reach t+90000ms. Pre-FORCEHT probe insertion costs ~30s of fw runtime regardless of probe size (within the range measured). n=3 now.
- **SMC reset required this time.** T245 no-SMC-reset (n=1), T246 SMC required (n=1), T247 SMC required (n=1). Streak is no clearer.

### Open question to resolve before PRE-TEST.248

**Does "fw touches none of our observed regions" falsify (S1) as a class, or only "(S1) with minimal host-pre-placed signature"?** Observation windows cover ~80 bytes out of 640KB TCM. A wide-scan probe across ~8–16 offsets would cheaply distinguish "fw is stalled doing nothing" from "fw is writing somewhere we're not looking." That vs a Phase-6 pivot is the next decision.

### Advisor response (2026-04-23 12:2x BST, post-T247 reconcile call)

Two cheap intermediate probes to run before any Phase-6 pivot:
1. **Wide-TCM scan** — snapshot ~16 u32 offsets spread across TCM[0..0xA0000) at pre-FORCEHT and at t+90000ms (pre-wedge); diff = "fw wrote here." Distinguishes "fw stalled doing nothing" from "fw writing somewhere we're not looking."
2. **Multi-signature sweep** — our version=5 may be wrong for BCM4360's Apple-variant fw. Try version=5,6,7 (MIN/MAX bounds upstream accepts) or an alternate magic word. Only if T248 wide-scan returns null.

Order: wide-scan first (T248); signature sweep deferred to T249 if T248 null. Rationale: if wide-scan finds fw writing *anywhere*, signature sweep is probably moot — we'd know fw is working, not stalled.

---

## PRE-TEST.248 (2026-04-23 12:2x BST, boot 0 after test.247 crash + SMC reset) — **wide-TCM scan.** Keep T247's pre-placed struct at TCM[0x80000] for continuity; add 16-u32 snapshot at pre-FORCEHT and at t+90000ms across TCM. Discriminator between "fw stalled" and "fw writing somewhere outside our observation windows."

### Hypothesis

T247 null result covers only ~80 bytes (struct region + ramsize-4 + tail-TCM) out of 640KB TCM. Fw may be executing and modifying TCM outside those windows. A wide-scan diff (baseline vs pre-wedge) exposes any such activity. Three outcomes:

- **(W1) Wide-scan null** (all 16 offsets unchanged between baseline and pre-wedge). Strengthens (S2) fw-stalled reading to "fw touches no TCM region we sampled." Next: T249 signature sweep (version=5/6/7 + alternate magic) to falsify (S1) as a class.
- **(W2) Wide-scan shows changes at offset(s) ∉ {0x80000, ramsize-4, tail}**. Falsifies "fw stalled doing nothing." Fw is working; we've just been looking in the wrong place. Next: densify around the changing offset(s); decode what fw is writing.
- **(W3) Wide-scan shows changes inside fw code region [0..0x6bf78]**. Would mean fw is self-modifying or writing to its own code segment — very unlikely. Flag and decompose.

### Design (advisor-to-review before code)

- **Struct continuity**: keep the existing `bcm4360_test247_preplace_shared` param and struct at 0x80000 version=5. No change to T247's block.
- **Wide-scan offsets (16 u32 = 64 bytes total read per snapshot)**: chosen to span the address space with denser coverage in dead region, lighter in fw image:
  - 0x00000 (fw vector table)
  - 0x10000, 0x20000, 0x30000, 0x40000, 0x50000, 0x60000 (inside fw image, 6 samples)
  - 0x68000 (near fw end 0x6bf78)
  - 0x70000, 0x78000, 0x84000, 0x88000, 0x8C000 (dead region spread)
  - 0x90000 (T245/T246 BAR2 round-trip location — adjacent already-observed)
  - 0x98000 (close to NVRAM start 0x9ff1c)
- **Baseline snapshot** at pre-FORCEHT just before the T247 block fires (same stage, same probe cost tier).
- **Pre-wedge snapshot** at the t+90000ms dwell (last dwell we reliably reach). Adding a per-dwell read at all 16 offsets across 23 dwells would be 368 reads total — still cheap BAR2 reads, but only two snapshots keep the ladder pattern identical to T247.
- **Observable**: diff(pre-FORCEHT snapshot, t+90000ms snapshot) per offset.

### Next-step matrix

| Wide-scan diff | Implication | Test.249 direction |
|---|---|---|
| All 16 offsets unchanged | (W1) — "fw stalled doing nothing" strengthened to near-certainty. Fw never writes anywhere we've observed across ~96 bytes spread over 640KB + struct region + ramsize-4 + tail-TCM. | T249: signature sweep (version=5/6/7 + alternate magic at struct [0]) to falsify (S1) as a class. If that also nulls, Phase 6 pivot is justified. |
| Changes only at in-fw-image offsets (0x00000..0x60000) | (W3) — unusual; fw writing its own code segment. | Decompose: does it happen with `set_active` skipped? Was fw image corrupted in download? |
| Changes at dead-region offsets (0x70000..0x98000) outside our old windows | (W2) — fw IS working, just not at the addresses we picked. | Densify around the changing offset(s); decode what's being written. |

### Safety

- BAR2 reads only (no writes beyond T247's existing struct placement); no register touch beyond T247 baseline.
- +32 BAR2 reads total vs T247 (16 pre-FORCEHT, 16 at t+90000ms). Well within T247's probe-cost envelope.
- Reads from fw image offsets do not perturb fw execution (read-only).
- SMC reset expected to be required after wedge (consistent with T247).

### Code change outline

1. **New module param** `bcm4360_test248_wide_tcm_scan` (default 0) near T247's param (pcie.c).
2. **New macro** `BCM4360_T248_WIDESCAN(stage_tag)` — reads 16 u32s from fixed offset list; logs single `pr_emerg` line.
3. **Two invocation sites**:
   - Right after T247's pre-FORCEHT block (before FORCEHT).
   - Right after the existing t+90000ms dwell poll (add a `if (bcm4360_test248_wide_tcm_scan)` conditional).

### Run sequence (after build+verify)

```bash
sudo modprobe cfg80211
sudo modprobe brcmutil
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Pre-test checklist status

1. Build status: **PENDING** — new param + macro + 2 invocation sites; `make`, verify via `modinfo`/`strings` before insmod.
2. PCIe state: clean (captured above, boot 0 uptime ~1 min after SMC reset).
3. Hypothesis: (W1)/(W2)/(W3) matrix.
4. Plan: this block. Commit + push + sync before code changes.
5. Advisor final review after code + build, before insmod.

---

### Hardware state (current, 2026-04-23 12:1x BST, boot 0 after test.247 crash **with SMC reset**)

`lspci -s 03:00.0` (sudo): `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1. No brcm modules loaded. Boot 0 started 12:13:29 BST, uptime ~1 min at write time. Host healthy.

---

## Prior outcome (test.246 — pre-FORCEHT MBM legal-pattern probe landed; readback 0x00000300. Matrix row (II) stage-gating of D2H_DB half of MBM confirmed: FN0 bits 8,9 latch at pre-FORCEHT; D2H_DB bits 16..23 do not. Ladder ran to t+90000ms, SMC reset required.)

### What test.246 landed

```
test.245: pre-FORCEHT BAR0_WINDOW before=0x18000000 after=0x18003000 (expect PCIE2 core base)
test.245: pre-FORCEHT MBM baseline=0x00000000 sent=0x00000300 (match=0) restored=0x00000000 (match=1) RESULT FAIL
test.245: pre-FORCEHT BAR2 TCM[0x90000] baseline=0xa4270be1 sent=0x5bd8f41e (match=1) restored=0xa4270be1 (match=1) RESULT PASS
test.246: pre-FORCEHT BAR0_WINDOW before=0x18000000 after=0x18003000 (expect PCIE2 base)
test.246: pre-FORCEHT MBM legal-pattern baseline=0x00000000 wrote=0x00ff0300 readback=0x00000300 (exact=0 d2h_db_latched=0 fn0_latched=1) restored=0x00000000 (restore_match=1) RESULT FAIL
```

### What test.246 settled

- **Matrix row (II) confirmed.** Writing upstream's exact production value `int_d2h_db | int_fn0` = 0x00FF0300 produced readback 0x00000300. FN0 bits (8,9) latched; D2H_DB bits (16..23) did not. Reading (I) "reserved-bits-clipping" falsified (D2H_DB bits must latch on legal writes if that reading were right). Reading (III) "write never reached chip" falsified (restore to 0 round-trips cleanly, FN0 bits do change under the write). **The D2H_DB half of MBM is in a clock or reset domain that is write-gated at pre-FORCEHT.** Upstream's MBM D2H enable write belongs later in the flow (post-shared-init) — consistent with upstream calling it from `brcmf_pcie_intr_enable` which runs post-fw-up.
- **Probe cost is constant, not cumulative.** T245 alone reached t+90000ms (~6 pre-FORCEHT MMIO ops). T246 adds another T246 probe block (~6 more ops) for ~12 ops total, and still reached t+90000ms. The 30s ladder slip vs T244's t+120000ms clean run is a **fixed cost of inserting a pre-FORCEHT probe**, not per-op. n=2 now for "pre-FORCEHT probe costs ~30s of fw runtime."
- **Baseline MBM=0 at T245 AND T246 (both this boot).** T241 saw baseline 0x00000318 at the same stage pre-FORCEHT; T245 and T246 (same boot, same binary, re-read post-select_core) both saw 0x00000000. Consistent with 0x318 being residue from a prior driver attempt or SMC-reset state that clears on clean reboot, and/or with MBM baseline genuinely being 0 at pre-FORCEHT when the chip is in its cleanest init state. Minor point but reinforces row (II).
- **BAR2 TCM[0x90000] baseline changed slightly vs test.245.** Test.245 (boot -2): 0x842709e1. Test.246 (boot -1, also re-run of T245): 0xa4270be1. Bit 29 toggled; rest same. SRAM power-on fingerprint is boot-to-boot *nearly* deterministic with single-bit jitter. Not alarming — still a clear "not zero, not all-ones" deterministic-ish value.
- **SMC reset required this time (n=1 break in streak).** T244 recovered without SMC reset (n=1); T245 also without (n=2); T246 required SMC reset (n=1 break). T246 had one additional probe block (~6 MMIO ops) vs T245. Two equally consistent readings: (a) cumulative pre-FORCEHT perturbation crossed a threshold at T246; (b) boot-variance — the no-SMC-reset recoveries were the lucky coin-flips, not T246 the unlucky one. Cannot distinguish at n=1 each. **Flag and move on.**
- **First-attempt harness bug.** T246's first insmod attempt failed at 10:40:37 with `Unknown symbol brcmu_*` (brcmutil not loaded). Fixed by adding `modprobe brcmutil` before insmod; retry at 10:45:41 ran correctly. Artifacts from the failed attempt preserved as `test.246.*.attempt1.txt`; successful-run artifacts are the unsuffixed files.

### Key implication for the investigation

**The post-set_active doorbell ring branch is now effectively closed at pre-set_active stages:**
- D2H_DB bits can only be enabled post-shared-init (MBM stage-gated per T246).
- Post-set_active PCIE2-register writes are a wedge trigger (per T243/T244 null-run discriminator).
- ⇒ Doorbells / MBM handshake cannot be driven from the host until fw itself has progressed past shared-struct init.

Per PRE-TEST.246 matrix + advisor: **pivot to shared-struct forward step.** Build a minimal `brcmf_pcie_init_share` equivalent: pre-allocate a pcie_shared struct in TCM and write its address to TCM[ramsize-4] BEFORE `brcmf_chip_set_active`, so fw has a valid DMA target when it activates. This is both a discriminator (if wedge moves or lifts, we've found what fw was blocked on) and a forward step regardless.

### Plan (PRE-TEST.247 — TO BE DRAFTED)

Pivot to shared-struct forward step. Next concrete actions:

1. Update PLAN.md — currently dated 2026-04-21, predates T233–T246. Add the shared-struct pivot to Phase 5.2; document the arc of probe findings that converged on this.
2. Study upstream's `brcmf_pcie_init_share` and `brcmf_pcie_bus_console_init` to identify the minimum viable struct layout and TCM placement.
3. Draft a PRE-TEST.247 that pre-writes the struct into TCM (via BAR2 writes — proven alive by T245/T246 BAR2 PASS) and writes its address to TCM[ramsize-4] instead of our current NVRAM marker (`0xffc70038`).
4. Advisor review of the struct design before code + boot-burn.

### Hardware state (current, 2026-04-23 11:20 BST, boot 0 after test.246 crash **with SMC reset**)

`lspci -s 03:00.0` (sudo): `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1, AER `UESta`/`CESta` zero. No brcm modules loaded. Boot 0 started 10:50:28 BST, uptime ~30 min. Host healthy.

---

## Prior outcome (test.244 — null-run discriminator; confirmed T243 post-set_active PCIE2 probe IS the wedge cause; clean-probe wedge bracket [t+120s, t+150s], host recovered without SMC reset)

**Test.244 setup:** Same binary as test.243 (commit 22a8dcb) with `writeverify_v2=0` (all other params same as test.240 baseline). Null-run: T243 probe path gated off at runtime, no rebuild. Goal: split hypothesis (a) "T243 probe wedged us at t+100ms" from (b) "something drifted boot-to-boot."

**Outcome:** Probe path executed through fw download, NVRAM, seed, FORCEHT, `pci_set_master`, `brcmf_chip_set_active` (TRUE at 09:58:26 BST). Ladder landed **all 23 dwells** t+100ms..t+120000ms plus the *first ever* "proceeding to BM-clear + release" line at 09:58:31.27 BST. Journal cut shortly after. Wedge happened in [t+120s, t+150s]; host recovered with a plain reboot — PCIe clean, no SMC reset required.

**Conclusion:** Hypothesis (a) confirmed. T243 V2 probe (at t+100ms post-set_active, under `select_core(PCIE2)` + MBM + BAR2 round-trip) is a wedge trigger that fires fast enough to swallow its own `pr_emerg` lines in the journal-tail truncation window. Which of the three sub-ops (select_core, MBM write, BAR2 round-trip) is the hazard is not isolated by this pair — that's a separate decomposition test if we ever need it.

**Historic wedge bracket reinterpretation.** Tests 238/239/240/241/242 last-landed at t+90000ms; tests 240/242's writeverify probes hit CR4_wrap+0x144 / CR4_wrap+0x4C at t+100ms/t+2000ms (silent BAR0_WINDOW defect), perturbing CR4 state. Clean-probe bracket = **[t+120s, t+150s]** (n=1, needs replication). Prior [t+90s, t+120s] was probe-contaminated.

**No-SMC-reset recovery** was novel at the time (n=1); test.245 now replicates it (n=2). Possible interpretation: the later, less-perturbed wedge leaves the PCIe link healthier. Or boot variance.

---

## Prior outcome (test.243 — host wedged before any T243 breadcrumb landed; journal truncated at "ASPM disabled" 09:36:37.77; 49 lines vs test.242's 408; wedge window moved earlier in the probe path)

**Test.243 outcome:** With `force_seed=1 ultra_dwells=1 poll_sharedram=1 wide_poll=1 writeverify_v2=1`, boot -1 ran from 09:15:26 to 09:36:37 BST. Insmod at 09:36:18.596. Journal tail last line at 09:36:37.771506: `BCM4360 test.158: ASPM disabled; LnkCtl before=0x0143 after=0x0140 ASPM-bits-after=0x0`. NO subsequent breadcrumbs landed — specifically, none of these expected lines:

- root-port LnkCtl dance (test.188)
- pre-download CR4 clk_ctl_st (test.218)
- `brcmf_pcie_download_fw_nvram` entry (test.163)
- FORCEHT write (test.219)
- `brcmf_chip_set_active returned TRUE` (test.238)
- Any dwell-ladder line (test.238 t+Xms)
- Any test.243 V2 line (BAR0_WINDOW before/after, MBM, BAR2 TCM)

By the same second in test.242's run, the probe was already in the dwell ladder at ≥t+500ms post-set_active. So test.243's wedge happened 1.5–2 minutes earlier in wall-clock terms than test.242's.

User SMC-reset + rebooted; current boot 0 started 09:43:30 BST.

**What test.243 proves and does not prove:**

- **Does not prove** that the test.243 V2 probe is innocent. The probe fires at t+100ms dwell. If the first `brcmf_pcie_select_core(PCIE2)` or the subsequent MBM write under correct core selection causes an instantaneous wedge, the `pr_emerg` buffer for the BAR0_WINDOW line would never be flushed — consistent with what we see.
- **Does not prove** that the probe wedged the system either. The wedge could have happened earlier for unrelated reasons (boot variance, SMC-reset residue, downstream effects of the extra module-param registration — unlikely but not excluded).
- **Does rule out** that test.243's probe landed any diagnostic data. The MBM-under-correct-selection question is still unanswered.

**What to do about it:** move the MBM / BAR2 diagnostic to a point we KNOW landed in every prior run. A natural candidate is **pre-FORCEHT** (same stage as test.241 but with correct `select_core(PCIE2)`), which all of tests 240/241/242/243 reached per journal. Write-verify at that stage, log the result, then step forward from there. Full plan in PRE-TEST.244.

### Hardware state (current, boot 0, 09:4x BST post-SMC-reset from test.243 wedge)

`lspci -s 03:00.0` shows `Mem+ BusMaster+`, MAbort-, CommClk+, DEVSEL=fast. Uptime ~5 min. No brcm modules loaded. No pstore available (watchdog frozen, as before).

---

**Prior outcome (test.234):** Test wedged. Same tail-truncation
pattern as test.231/232. Last journald line at 23:12:50 BST was
`BCM4360 test.158: BusMaster cleared after chip_attach` — that's
inside `brcmf_pcie_attach` BEFORE `brcmf_pcie_download_fw_nvram`
even starts. **Zero test.234 breadcrumbs landed in journald** (no
PRE-ZERO scan, no zeroing log, no verify, no set_active call/return,
no dwells). The retained test.233 PRE-READ continuity log also
didn't land. So we cannot tell from this run alone whether:
- the zero loop ran or completed
- set_active was called
- the wedge point shifted relative to test.231/232

This is the **expected** journald blackout behavior (tail loss
~15-20s) and matches every prior set_active-enabled run. Host had
to be SMC-reset + rebooted (~28 min downtime). PCIe state on this
boot (boot 0, started 23:41:20 BST) is clean — Mem+ BusMaster+,
MAbort-, CommClk+. No pstore (watchdog frozen by bus stall, as before).

**Conclusion forced by this run:** test.234 cannot be interpreted
on its own. We need a logging transport that survives the wedge
window. Per test.233, TCM survives within-boot SBR+rmmod+insmod
(Run 2) but is wiped by SMC reset (Run 3). And we *always* need
SMC reset to recover from the wedge. So the next test must
**decompose** the experiment into observable pieces — at minimum,
a test.235 that runs the zero+verify path **without** set_active
(test.230 baseline) so we can confirm the zero loop works at all,
then a separate run that adds set_active back. Detailed plan in
PRE-TEST.235 (next).

---

**Prior outcome (test.233):** TCM persistence probe answered the
advisor-blocking question. 3 runs on test.230 baseline (set_active
SKIPPED, no wedge). Wrote 0xDEADBEEF/0xCAFEBABE magic to
TCM[0x90000/4] in each run, pre-read the same offsets at probe
entry:

| Run | Context | Pre-read | Interpretation |
|---|---|---|---|
| 1 | fresh post-SMC-reset boot | 0x842709e1 / 0x90dd4512 | **non-zero** residue — fingerprint-like |
| 2 | same boot, after rmmod | 0xDEADBEEF / 0xCAFEBABE | **MATCH** — TCM survives SBR + rmmod/insmod within boot |
| 3 | post-SMC-reset + reboot | 0x842709e1 / 0xb0dd4512 | magic GONE; near-identical to Run 1 baseline |

**Binary conclusion:** SMC reset + reboot wipes our magic.
**TCM ring-buffer logger is NOT viable for cross-SMC-reset data
retention** — and every wedge in this investigation has required an
SMC reset to recover. So TCM logger can't carry wedge-timing data
through the recovery path we actually use.

**Side observations worth keeping:**
- Run 2 confirmed TCM persists across rmmod/insmod + probe-start
  SBR. If a wedge ever leaves host recoverable without SMC reset,
  the logger *would* help — but that hasn't happened in any test.
- Run 1 and Run 3 pre-reads are near-identical (one word byte-
  identical, one word off by one bit). These are NOT zeros or
  all-0xFF — they look like a deterministic SRAM/fingerprint
  pattern or residue of an early init routine that runs fresh on
  each SMC-reset boot. Offset 0x90000 is past fw image (0..0x6bf78)
  and before NVRAM (0x9ff1c), so our code never writes there in
  normal flow. Could be a BCM4360 SRAM power-on signature.

**Pivot: shared-memory struct forward step.** With TCM logger ruled
out as the timing transport, the path advisor already identified
as the natural next step becomes primary: study upstream brcmfmac's
`brcmf_pcie_init_share` + PCIE2 ring infrastructure, then build a
minimal shared-memory struct in TCM BEFORE `brcmf_chip_set_active`
so that when fw activates, it has valid DMA targets to dereference.
This is both a discriminator (if wedge stops or shifts, we've found
the missing piece) and a forward step regardless of logging.

**Prior fact (test.232):** BM=OFF did NOT prevent the wedge, so
pure DMA-completion-waiting theory is falsified. Wedge may still
be DMA-rooted via fw's reaction to UR responses (AXI fault, retry
storms, pcie2 bring-down internally), but it's not plain
completion-starvation.

**Prior fact (test.230):** `brcmf_chip_set_active` is the **SOLE
trigger** for the bus-wide wedge. With that call skipped, the host
survived the entire probe path cleanly — both breadcrumbs landed,
driver returned -ENODEV, rmmod worked, host alive ≥30 s after, BAR0
still fast-UR. First-ever clean full run.

**Prior fact (test.229):** Post-set_active probe MMIO is innocent —
probes `#if 0`'d, host still wedged. Narrowed the trigger to
"set_active itself"; test.230 confirmed.

**Hardware invariants:**
- Chip: BCM4360, chiprev=3, ccrev=43, pmurev=17
- Cores: pcie2 rev=1, ARM CR4 @ 0x18002000
- Firmware: 442,233 bytes; rambase=0x0, ramsize=0xA0000 (640 KB TCM)
- BAR0=0xb0600000, BAR2=0xb0400000 (TCM window)
- Firmware download: full 442 KB writes successfully; TCM verify 16/16 MATCH
- set_active: reaches CR4, returns true; CPUHALT clears; fw starts executing

**Ruled-out hypotheses (cumulative):**

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/7/0xe/0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |
| Wedge at test.158 ARM CR4 probe line | 226, 227 | ruled out — tail-truncation illusion; journal kept going after that line once NMI watchdog enabled |
| Chunked-write regression (wedge at chunk 27) | 228 | ruled out — was also tail-truncation; full 107 chunks in journal once we survive long enough |
| Wedge caused by probe_armcr4_state MMIO 0x408 (H1) | 229 | ruled out — probes disabled, wedge still occurred |
| Wedge caused by any tier-1/2 fine-grain probe | 229 | ruled out — gated `#if 0`, wedge still occurred |
| Wedge caused by 3000 ms dwell polling | 229 | ruled out — replaced with msleep(1000), still wedged |
| Wedge caused by pre-set_active path (FORCEHT / pci_set_master / fw write) | 230 | ruled out — skipped set_active, host survived cleanly end-to-end |
| Wedge caused by anything OTHER than `brcmf_chip_set_active` | 230 | ruled out — that call is the single-point trigger |
| Sub-second wedge window measurable via journald tail | 231 | ruled out — tail-truncation budget (~15–20 s) >> wedge window |
| Wedge is pure DMA-completion-starvation (fw stalls waiting for response to TLP with bad host address) | 232 | ruled out — BM=OFF forces UR responses instead of completion-waiting, host still wedged |
| TCM ring-buffer logger viable across wedge recovery | 233 | ruled out — TCM magic survives within-boot SBR+insmod (Run 2) but wiped by SMC reset + reboot (Run 3) — every wedge-recovery in this investigation used SMC reset |
| Wedge caused by fingerprint values in [0x9FE00..0x9FF1C) (cheap tier) | 234, 235 | ruled out — zeroing the region did not prevent test.234's wedge |
| Fw-wedge independent of Apple random_seed footer presence | 236 | ruled out — writing `magic=0xfeedc0de` + 256-byte buffer at [0x9FE14..0x9FF1C) shifts the wedge noticeably later: fw reaches ≥t+700ms post-set_active, vs. test.234's pre-fw-download cutoff |
| Wedge is instantaneous at/near set_active return (sub-second) | 237 | ruled out — with seed present and an extended msleep ladder, fw runs ≥25 s post-set_active; dwells at t+100..t+25000ms all landed live, driver thread schedulable throughout. |
| Wedge is a fw-timeout at ~t+30 s (Model A from PRE-TEST.238) | 238 | ruled out — fine-grain 1 s ladder through [t+25..t+30 s] all landed; dwells at t+35, 45, 60, 90 s all landed. Wedge is not near t+30 s. |
| Wedge happens within ~t+40-45 s of set_active (Model B from PRE-TEST.238) | 238 | ruled out — `t+60 s dwell` and `t+90 s dwell` both landed live. True wedge window is [t+90 s, t+120 s]. |
| Fw completes shared-struct init before wedge (i.e. writes `sharedram_addr` to TCM[ramsize-4]) | 239 | ruled out — 22 consecutive polls at t+100ms..t+90s all returned the pre-set_active NVRAM marker `0xffc70038`. Fw is executing for ≥90s but has not reached / not exited the step that normally overwrites this slot. |
| Fw writes ANY of the last 60 bytes of TCM (not just ramsize-4) during the ≥90 s pre-wedge window | 240 | ruled out — a 15-dword wide-poll at ramsize-64..ramsize-8, sampled at 22 ladder points, returned the unchanged NVRAM tail text every time. Fw's post-init work, if any, does not touch the tail region. |
| Ringing H2D_MAILBOX_1 (upstream "HostRDY" offset, BAR0+0x144) at t+2000ms releases fw's pre-shared-alloc stall | 240 | **invalid — hypothesis never actually tested.** Post-test review of pcie.c found the probe wrote to BAR0+0x144 with BAR0_WINDOW still pointing at CR4 wrapbase (0x18102000; left there by `brcmf_chip_cr4_set_active` → `brcmf_chip_resetcore(CR4)`). Write hit CR4_wrap+0x144, not H2D_MAILBOX_1. DB1-null reading retracted; hypothesis re-opens for test.244 after test.243 confirms the BAR0-write path via correct core-selection. |
| BAR0 write path via `brcmf_pcie_write_reg32` reaches chip at our **pre-FORCEHT** probe stage (using MAILBOXMASK round-trip) | 241 | **invalid — wrote to the wrong register.** Post-test review: probe fired with BAR0_WINDOW at ChipCommon (left there by `probe_d11_clkctlst` ending with `select_core(CHIPCOMMON)`). Write hit CC+0x4C (likely gpio_out — value 0x318 = GPIO bits 3,4,8,9). MBM was not tested. |
| BAR0 write to MAILBOXMASK latches **post-set_active** (t+100ms or t+2000ms) | 242 | **invalid — wrote to the wrong register.** Post-test review: probe fired with BAR0_WINDOW at CR4 wrapbase (same defect as test.240). Write hit CR4_wrap+0x4C, not MBM. The "0x318→0x00 baseline flip across stages" was a GPIO-vs-CR4-wrapper comparison, not an MBM state-evolution signal. MBM latching under PCIE2 core-selection remains **untested**. |
| `brcmf_pcie_write_reg32` BAR0 write path reaches chip when BAR0_WINDOW is explicitly `select_core`d first | 193, 224, 245 | **confirmed for CC and PCIE2 cores.** CC: test.193 chipcontrol#1 write 0x210→0xa10 and test.224 max_res_mask 0x13f→0x7ff both visible-changed readbacks under `select_core(CHIPCOMMON)`. PCIE2: test.245 pre-FORCEHT MBM round-trip wrote 0xFFFFFFFF → readback 0x00000300 (bits 8,9 latched), restore 0 → readback 0 — partial-mask latch consistent with MAILBOXMASK's reserved-bits layout. So BAR0 writes to *both* CC and PCIE2 core registers land at pre-FORCEHT under correct `select_core`. |
| Writing 0xFFFFFFFF to MAILBOXMASK @ PCIE2+0x4c latches as 0xFFFFFFFF (naïve "all bits writable") | 245 | **ruled out** — only bits 8,9 latched (readback 0x00000300). Register has many reserved-read-as-zero bits. Invert-and-restore sentinel was a poor fit for this register; a specific-legal-bitmask write would be definitive. |
| T243 post-set_active probe (`select_core(PCIE2)` + MBM round-trip + BAR2 TCM round-trip at t+100ms/t+2000ms) is innocent of the early wedge in test.243 | 243, 244 | **ruled out — probe IS the wedge cause.** Null-run discriminator (test.244, same binary, `writeverify_v2=0`) reached t+120000ms "dwell done" cleanly; test.243 (`writeverify_v2=1`) wedged before set_active even fired. Hypothesis (a) confirmed. Which sub-op (select_core / MBM write / BAR2 round-trip) triggers the wedge is not isolated by this pair. |
| Historic wedge bracket `[t+90s, t+120s]` reflects the "clean probe" wedge timing | 238–242, 244 | **qualified/narrowed.** Tests 238–242 last-landed at t+90000ms dwell, but tests 240/242's writeverify probes hit CR4_wrap+0x144 and CR4_wrap+0x4C at t+100ms/t+2000ms (silent defect above), perturbing CR4 state mid-ladder. Test.244's clean no-probe path reached t+120000ms AND the "dwell done" line (~30 s later than the historic bracket). Clean-probe wedge bracket = **[t+120s, t+150s]** (n=1; needs replication). Prior bracket was probe-contaminated. |

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — fw blocked on host handshake (still standing,
but not freshly strengthened by test.240):**
Fw never advances to shared-struct allocation within ≥90 s
post-set_active (upstream timeout is 5 s). Test.240 attempted the
upstream HostRDY doorbell (DB1) as the cheapest handshake probe;
result was inconclusive for the reasons in *Three readings* above.

**Next test direction (test.241):**
Per advisor — pivot to "write-verify first, then doorbell". Before
another boot-burn on DB0, instrument one or more known-RAM-backed
BAR0 MMIO locations with a write-then-immediate-readback pattern
inside the probe, after `pci_set_master` and before `set_active`,
to prove the driver's BAR0 write path lands correctly with the
current core-select window. If that passes, ring DB0 at t+2000ms
as the original decision tree had. If that fails, the whole
"doorbell" branch is suspect and we pivot to (a) investigate core-
select window handling, and/or (b) pre-allocate a shared-memory
struct in TCM `brcmf_pcie_init_share`-style and write its address
to TCM[ramsize-4] before set_active (the advisor's prior "jump"
suggestion). Details in PRE-TEST.241.

**Logging transport status (updated after test.233):**
- journald: drops ~15–20 s of tail when host loses userspace (confirmed tests 226/227/231/232).
- pstore: doesn't fire — bus-wide stall freezes watchdog CPU (tests 227/228/229).
- netconsole: user declined second-host setup.
- **TCM ring buffer: ruled out** — TCM magic wiped by SMC reset +
  reboot (test.233 Run 3). Survives within-boot rmmod/insmod (Run 2),
  but every wedge in this investigation has required an SMC reset.
- `earlyprintk=serial`: `/dev/ttyS0..3` exist but MacBook has no
  exposed port — likely bit-bucket without USB-serial adapter.

Logging for test.234 falls back to journald tail-truncation as
before. Resolution ≥15-20 s is fine because the goal is shape-
comparison (does the wedge still happen? at the same place?),
not sub-second timing.

---


## PRE-TEST.247 (2026-04-23 11:3x BST, boot 0 after test.246 crash + SMC reset) — **first shared-struct probe.** Pre-place a ~72-byte `brcmf_pcie_shared_info`-shaped struct (version=5 at offset 0, rest zero) at TCM[0x80000] via BAR2 at the pre-FORCEHT stage. Leave NVRAM trailer at ramsize-4 (`0xffc70038`) unchanged — NVRAM-parser load-bearing per our own pcie.c test.64 note. Add a per-dwell poll of `[0x80000..0x80047]` (18 u32s, 72 bytes) to observe whether fw reads or writes any struct field across ≥90s. Discriminator between **(S1) BCM4360 fw expects host-pre-placed struct** and **(S2) fw follows upstream and is stalled upstream of allocate-and-publish step**.

### Hypothesis

T239 proved fw never overwrites TCM[ramsize-4] within ≥90s — slot stays at our NVRAM marker `0xffc70038`. Per upstream protocol (`brcmf_pcie_init_share_ram_info`, pcie.c:2106), fw is supposed to allocate its own `pcie_shared` struct in TCM and write that address to `ramsize-4`; host reads from it. So either:

- **(S1) BCM4360 fw reads a host-pre-placed struct.** Some firmware variants (Apple's in-tree `wl` driver behavior, older SDKs) expect the host to pre-place signature/version fields at a known offset. If so, placing a plausible struct in TCM should cause fw to touch it or to progress further (wedge shift, struct-field changes, or ramsize-4 finally being written).
- **(S2) Fw follows upstream protocol.** T239's no-overwrite then reflects fw stalled before the allocate-and-publish step — struct placement is ignored. Discriminator: no fw activity in our struct region, ramsize-4 still at `0xffc70038`, wedge unchanged — same as T244/T245/T246 baseline.

### Design (advisor-reviewed)

- **Struct layout:** 72 bytes (0x48), u32 at offset 0 = `BRCMF_PCIE_MIN_SHARED_VERSION` (= 5). All other 17 u32s (offsets 4..68) = 0. Covers the full range of offsets upstream reads (0, 20, 34, 36, 40, 44, 48, 52, 56, 64, 68).
- **TCM placement:** base at `0x80000` inside the dead region `[0x6C000..0x9FE00]` (above fw end 0x6BF78, below random_seed region start 0x9FE14). T233 proved this region is untouched by fw and host in normal flow; T245/T246 proved BAR2 writes land there.
- **ramsize-4 NOT overwritten.** 0xffc70038 is the NVRAM length/magic token per our own test.64 comment (pcie.c:3527); T63 zeroed it and broke NVRAM discovery. Fw is expected to overwrite it itself if following upstream protocol.
- **Observables:**
  1. Pre-FORCEHT write + readback of all 18 u32s (confirms BAR2 write landed and struct looks as intended on chip).
  2. Per-dwell poll of all 18 u32s at every existing T239 breadcrumb (t+100ms..t+120000ms) — any change vs baseline = fw touched our struct.
  3. Existing `poll_sharedram=1` continues to track ramsize-4 — any change from 0xffc70038 to another value = fw wrote its own sharedram_addr (upstream path).
  4. Existing `wide_poll=1` continues to track ramsize-64..ramsize-4.

### Next-step matrix

| ramsize-4 | Struct fields (at 0x80000..0x80047) | Interpretation | Test.248 direction |
|---|---|---|---|
| changes (fw writes sharedram_addr) | unchanged | **(S2) confirmed.** Fw followed upstream; struct pre-placement was ignored. Our sharedram_addr-waiting loop timeout was probably just too short before T238's ultra_dwells. | Feed fw-written sharedram_addr into `brcmf_pcie_init_share_ram_info`; observe what fw has populated (signature/version, ring pointers, console addr, mb data addrs). Major forward step regardless. |
| unchanged (still 0xffc70038) | some word(s) change | **(S1) confirmed.** Fw reads from host-pre-placed struct. Iterate: study which fields changed to learn what fw needs populated and what it populates itself. | Populate the fields fw wrote to; observe whether it progresses further. |
| unchanged | unchanged | (S1) falsified AND (S2) consistent with fw stalled pre-allocate. Pivot to Phase-6 `wl`-trace work, IMEM inspection at BAR2[0xef000], or NVRAM-parameter audit. | Phase 6 study / register trace / NVRAM-dump comparison against Apple macOS config. |
| changes | AND fields change | Both channels active — surprising but informative. Fw may have read struct, then allocated its own and told us. | Read fw-written struct; compare against what we pre-placed. |

### Expected wedge behavior

Keep `ultra_dwells=1` so the ladder runs to t+120000ms. Probe adds ~20 BAR2 writes at pre-FORCEHT and 18 BAR2 reads per dwell (vs T245/T246's ~12 BAR2 MMIO ops). Still comfortably within the noise of pre-FORCEHT probe cost that T246 pegged at ~30s. Wedge bracket expected [t+90s, t+150s]; not a primary observable per advisor — **fw activity is primary, timing is noise at n=1**.

### Code change outline

1. **New module param** `bcm4360_test247_preplace_shared` (default 0) near the test.246 param block (pcie.c:243).
2. **New pre-FORCEHT probe block** after the existing test.246 block (pcie.c:2805) and before `pr_emerg("BCM4360 test.226: past BusMaster dance...")` (pcie.c:2807). Logic:
   - For i=0..17: `brcmf_pcie_write_ram32(devinfo, 0x80000 + i*4, 0);`
   - `brcmf_pcie_write_ram32(devinfo, 0x80000, BRCMF_PCIE_MIN_SHARED_VERSION);` (= 5)
   - Readback all 18 u32s; log as a single `pr_emerg` line.
3. **Extend `BCM4360_T239_POLL` macro** (pcie.c:2916) with a third conditional `if (bcm4360_test247_preplace_shared)`:
   - Read 18 u32s from `[0x80000..0x80047]`;
   - Log as single line with the `test.247: t+XXXms struct[0x80000..0x80047] = ...` prefix.

### Safety

- Struct write is pure TCM memory (BAR2), no register side-effect. Same class as NVRAM and random_seed writes, which are known safe.
- Struct region `[0x80000..0x80047]` is inside the dead zone proven untouched by fw and host in normal flow (T233).
- ramsize-4 is NOT overwritten — NVRAM trailer intact, NVRAM parser unaffected.
- Each dwell-poll adds 18 BAR2 reads — pure reads, no side effects.
- T245/T246 probes OFF for this run (one new-variable rule): ~20 pre-FORCEHT writes + 18 reads, then 18 reads per dwell × 23 dwells = 414 reads total + 20 writes. All BAR2, no register touch.

### Run sequence

```bash
sudo modprobe cfg80211
sudo modprobe brcmutil
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: `modprobe brcmutil` before insmod is required (T246 attempt 1 failed without it).

### Hardware state (current, 11:2x BST boot 0, post-SMC-reset from test.246)

`lspci -s 03:00.0` (sudo): `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1, AER `UESta`/`CESta` zero. No brcm modules loaded. Boot 0 started 10:50:28 BST; uptime ~47 min at planning time.

### Build status — REBUILT

Module rebuilt 2026-04-23 ~11:40 BST via
`make -C /nix/store/.../linux-6.12.80/build M=.../brcmfmac modules`.
Verified:
- `modinfo` reports `parm: bcm4360_test247_preplace_shared: ...`.
- `strings brcmfmac.ko | grep "test.247"` returns the pre-FORCEHT
  format line plus all 23 dwell-poll format lines (one per dwell
  tag: t+100ms, t+300ms, t+500ms, t+700ms, ...).
- Only pre-existing unused-variable warnings (dump_ranges,
  dwell_labels_ms/dwell_increments_ms in `test.188` dead block, j/d
  in `test.188` dead block); no new regressions.

### Expected artifacts

- `phase5/logs/test.247.run.txt`
- `phase5/logs/test.247.journalctl.full.txt`
- `phase5/logs/test.247.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + modinfo/strings verify before insmod.
2. PCIe state: verified clean above.
3. Hypothesis: stated above — (S1) vs (S2) discriminator matrix.
4. Plan: this block; commit + push + fsync before insmod.
5. Advisor final sanity check after code + build, before insmod.

---

## PRE-TEST.246 (2026-04-23 10:3x BST, boot 0 after test.245 crash **without** SMC reset) — disambiguate test.245's MBM partial-latch by writing upstream's exact production MBM value (`int_d2h_db | int_fn0` = 0x00FF0300) at the same pre-FORCEHT stage. Single-focus probe, no BAR2 round-trip (already proven PASS), no post-set_active work (known-hazardous per test.244). **OUTCOME: matrix row (II) confirmed — write=0x00FF0300 readback=0x00000300 (fn0_latched=1, d2h_db_latched=0). D2H_DB bits of MBM are stage-gated at pre-FORCEHT. T245 re-run reproduced (same MBM FAIL, BAR2 PASS with slight fingerprint jitter). Ladder ran to t+90000ms — same as T245 alone, confirming pre-FORCEHT probe cost is constant, not cumulative. SMC reset required this time (break in T244/T245 no-SMC-reset streak). See Current state at top. T247 direction: pivot to shared-struct forward step per matrix + advisor.**

### Hypothesis

Test.245 wrote 0xFFFFFFFF to MBM at pre-FORCEHT; readback was 0x00000300 — bits 8,9 (FN0_0, FN0_1) latched, but the documented-legal D2H_DB bits 16..23 (0x00FF0000) did NOT. Two readings are both consistent with the data:

- **(I) Reserved-bits-clipping.** BAR0 write landed as-issued; MBM reserved bits 10..15 and 24..31 read-as-zero; D2H_DB bits 16..23 must actually be `reserved` too despite the header naming them "legal." Writing upstream's exact production value (0x00FF0300) should latch byte-for-byte if this reading is right… unless bits 16..23 are genuinely non-writable, in which case readback=0x00000300 again.
- **(II) Stage-gating of D2H_DB half of MBM.** BAR0 writes do reach the chip, but D2H_DB bits (16..23) are in a clock/reset domain that's write-gated at pre-FORCEHT (not yet clocked, or pre-shared-init behavior). FN0_0/FN0_1 bits (8,9) are in a different domain and accept writes. Readback=0x00000300 on an upstream-legal write would confirm this.
- **(III) Write never reached chip, 0x300 was hw state.** Ambient state happens to be 0x300 and our 0xFFFFFFFF dropped. Readback on 0x00FF0300 → 0x00000300 would be ambiguous between (II) and (III). Readback = something else entirely (say 0x0) would favor (III).

Test.246 writes exactly `int_d2h_db | int_fn0` = 0x00FF0300 and reports whether bits 8,9 and/or bits 16..23 latched, plus a full restore check.

### Next-step matrix

| Readback | Fn0 latched? | D2H_DB latched? | Interpretation | Test.247 direction |
|---|---|---|---|---|
| 0x00FF0300 | YES | YES | Upstream MBM writes work at pre-FORCEHT. Reading (I) correct; doorbell branch fully re-opened. | Pivot to shared-struct forward step (deferred from test.233). Build minimal `brcmf_pcie_init_share` equivalent in TCM before set_active. |
| 0x00000300 | YES | NO | D2H_DB bits stage-gated. Reading (II) correct. Upstream's MBM write will fail at pre-FORCEHT; it belongs later (post-shared-init, matching upstream's placement). | Pivot to shared-struct; note MBM D2H enables only writable post-share-init. Doorbell ring (DB0/DB1) at post-set_active remains hazardous — stay in pre-set_active forward work. |
| 0x00000000 | NO | NO | Write didn't reach chip; test.245's 0x300 was ambient. Contradicts test.245's restore-match. | Stop, re-examine. Something probe-order-sensitive. Compare to test.245 behavior; may need decomposition test. |
| other | partial | partial | Unexpected bit layout. | Report and decide with advisor. |

### Code change (committed before build)

1. New param `bcm4360_test246_writeverify_legal` (default 0) declared next to test.245 param.
2. New probe block right after the test.245 block at the same pre-FORCEHT location (after `pci_set_master` + BM-MMIO-guard, before FORCEHT write). Gated on the new param.
3. Probe: `select_core(PCIE2)` (with BAR0_WINDOW before/after log), read baseline, write `int_d2h_db | int_fn0`, read-back, write baseline (restore), read-back, log exact/d2h_db_latched/fn0_latched/restore_match.
4. No change to test.245 block — this is additive.

### Safety

- `select_core(PCIE2)` is routine at this stage (proven by test.245 — BAR0_WINDOW moved cleanly).
- Write value is upstream's exact production value; if it damages state, upstream damages the same state at its corresponding call site.
- BAR0_WINDOW saved/restored across the probe.
- No post-set_active work. No BAR2 round-trip. No doorbell ring. This is the smallest possible additional perturbation on top of test.245's already-validated pre-FORCEHT probe — about 6 extra MMIO ops.

### Awareness carryover from advisor

- **30s bracket slip is evidence, not variance.** Test.244 (no probe) reached t+120000ms; test.245 (pre-FORCEHT probe) reached t+90000ms. Track test.246's ladder last-landed dwell: if earlier than t+90000ms, pre-FORCEHT probe load is cumulatively perturbing; if at or past t+90000ms, single-probe cost is roughly constant.
- **Arc check.** Shared-memory-struct forward step has been deferred since test.233's pivot note. Test.246 is the **last single-probe diagnostic** — regardless of outcome, test.247 should start on shared-struct construction (or at minimum a planning document in PLAN.md). Advisor explicitly flagged "don't stay in probe-refinement mode without checking the arc."

### Run sequence

```bash
sudo insmod phase5/work/drivers/.../brcmutil.ko
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test245_writeverify_preforcehttp=1 \
    bcm4360_test246_writeverify_legal=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: running T245 AND T246 together keeps cost roughly constant (both at same stage, ~12 total MMIO ops) and lets us directly compare the readbacks without a binary-rebuild axis.

### Hardware state (current, 10:3x BST boot 0, no SMC reset from test.245)

- `lspci -s 03:00.0` (sudo): `I/O- Mem- BusMaster-`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1, AER UESta/CESta zero, Region 0/2 `[disabled]`. Clean.
- No brcm modules loaded.
- Boot 0 started ~10:23 BST; uptime ~10 min at test firing.

### Build status — REBUILT

Module built from updated pcie.c (param + probe block both present per `modinfo`/`strings` verify). Rebuild completed after PRE-TEST.246 plan was drafted; commit captures both plan and code.

### Expected artifacts

- `phase5/logs/test.246.run.txt`
- `phase5/logs/test.246.journalctl.full.txt`
- `phase5/logs/test.246.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: REBUILT and verified via `modinfo` (param present) + `strings` (two test.246 format strings present).
2. PCIe state: verified clean above.
3. Hypothesis: stated above — (I)/(II)/(III) matrix.
4. Plan: this block; commit + push + sync before insmod.
5. Filesystem sync on commit.

---

## PRE-TEST.245 (2026-04-23 10:1x BST, boot 0 after test.244 crash **without** SMC reset) — relocate T243's MBM + BAR2 round-trip probe to **pre-FORCEHT** stage under explicit `select_core(PCIE2)`. **OUTCOME: 3 T245 lines flushed pre-FORCEHT — BAR0_WINDOW moved to 0x18003000 on command, MBM partial latch (bits 8,9), BAR2 round-trip PASS. Ladder ran to t+90000ms then wedged; no SMC reset needed to recover. See Current State at top for full analysis. The matrix row "FAIL/PASS = writes don't latch" was wrong — BAR0 writes to PCIE2 regs DO land, MBM is a partially-writable mask register.**

### Hypothesis

Test.244 proved T243's post-set_active probe (`select_core(PCIE2)` + MBM round-trip + BAR2 round-trip at t+100ms) wedges the host fast enough that none of its `pr_emerg` lines flush. Moving that same round-trip to **pre-FORCEHT** — after `pci_set_master`, before the FORCEHT write, before `brcmf_chip_set_active` — should be safer because:
- ARM CR4 is not executing firmware (set_active hasn't fired). The post-set_active wedge mechanism doesn't apply.
- Upstream brcmfmac calls `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)` at multiple points during probe (pcie.c:1030, 1053, 3226, 3580) including at this exact stage in its own MBMASK writer block. Not a novel operation.
- Every test 240..244 landed the pre-FORCEHT stage cleanly (confirmed in journal).

### Expected outcomes / next-step matrix

| MBM result | BAR2 result | Interpretation | Test.246 direction |
|---|---|---|---|
| PASS | PASS | BAR0 writes to PCIE2 regs work under correct `select_core`. Doorbell branch re-opens cleanly. Tests 240/241/242's nulls were all the silent-defect. | Test.246: ring DB1 pre-FORCEHT with explicit `select_core(PCIE2)` wrapper; observe fw response. (Ringing DB1 post-set_active is now known-hazardous — skip that.) |
| FAIL | PASS | Pre-FORCEHT BAR0 writes to PCIE2 regs specifically don't latch. BAR2 TCM writes work, so general MMIO path is alive. PCIE2 core may be held in reset or clock-gated at this stage. | Test.246: probe PCIE2 wrapper reset/clock state (IOCTL / clk_ctl_st for PCIE2) and compare to ChipCommon (where test.193/224 succeeded). |
| PASS | FAIL | Very unlikely — BAR0 works, BAR2 TCM doesn't. Would contradict 442 KB fw-download BAR2 writes that verified 16/16 pre-FORCEHT. | Investigate BAR2 collapse; re-verify BAR2 base in config space. |
| FAIL | FAIL | Both fail at pre-FORCEHT — contradicts test.193/224 CC writes which DID land at this stage. Unlikely; if it happens, the probe itself might be broken. | Add a CC-write-verify at the same stage as a belt-and-suspenders sanity check before reshaping the investigation. |

### Code plan

1. **New module param** `bcm4360_test245_writeverify_preforcehttp` (default 0).
2. **New macro** `BCM4360_T245_WRITEVERIFY(stage_tag)` next to the existing `BCM4360_T243_WRITEVERIFY` — same logic (BAR0_WINDOW before/after, `select_core(PCIE2)`, MBM invert-and-restore, restore window, BAR2 TCM[0x90000] invert-and-restore) but with `test.245:` log prefix.
3. **Invocation site:** right after the existing test.241 writeverify block (pcie.c:2681) and before the "past BusMaster dance" line (2682). I.e. after `pci_set_master` + BM-MMIO-guard, before FORCEHT. Gated on the new param.
4. Leave all existing macros (`BCM4360_T241_WRITEVERIFY`, `BCM4360_T242_WRITEVERIFY`, `BCM4360_T243_WRITEVERIFY`) in place but gate them off via unset params for this run.

### Safety

- `select_core(PCIE2)` is routine at this stage — upstream does it (pcie.c:3580) for its own MBMASK writer. Not a new operation.
- Invert-and-restore limits the live-disturbance window to ≤1 µs per register.
- BAR2 TCM[0x90000] is a dead region (above fw end 0x6bf78, below NVRAM start 0x9ff1c; test.233 proved not touched by fw/host in normal flow). Immediate restore.
- ≤10 MMIO ops total at pre-FORCEHT — within the noise of existing pre-FORCEHT load.

### Run sequence

```bash
sudo insmod phase5/work/drivers/.../brcmutil.ko
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test245_writeverify_preforcehttp=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Hardware state (current, 10:0x BST boot 0, **post-test.244 crash with NO SMC reset**)

- `lspci -s 03:00.0` (sudo): `I/O- Mem- BusMaster-`, MAbort-, DEVSEL=fast; AER `UESta`/`CESta` all zero; LnkSta Speed 2.5GT/s Width x1. Clean.
- Boot 0 started 2026-04-23 10:00:09 BST.
- No brcm modules loaded.
- **Note**: This is the first boot in this investigation where wedge recovery did NOT need SMC reset. If the pre-FORCEHT probe triggers another wedge, we may learn whether SMC reset becomes necessary as severity grows, or stays optional.

### Build status — PENDING REBUILD

New param + new macro + new invocation site in pcie.c. Rebuild via `make -C /home/kimptoc/bcm4360-re/phase5/work`. Verify via `modinfo` (param present) and `strings | grep 'test.245'` (format lines present) before insmod.

### Expected artifacts

- `phase5/logs/test.245.run.txt`
- `phase5/logs/test.245.journalctl.full.txt`
- `phase5/logs/test.245.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — `make` + `modinfo`/`strings` verify before insmod.
2. PCIe state: verified clean above.
3. Hypothesis: stated above — MBM writes latch pre-FORCEHT under correct select.
4. Plan: this block; commit + push + sync before insmod.
5. Filesystem sync on commit.

---


## PRE-TEST.244 (2026-04-23 09:5x BST, boot 0 post-SMC-reset from test.243) — **null-run discriminator, no rebuild.** Rerun the existing test.243 binary with `writeverify_v2=0` and all other params identical. **OUTCOME: hypothesis (a) confirmed — see current state block at top.** If wedge returns to `[t+90s, t+120s]`, T243 V2 probe is confirmed as the wedge cause (hypothesis (a)); if wedge stays early, something drifted (hypothesis (b)) and we need a different investigation before any pre-FORCEHT reroute.

### Hypothesis

Test.243's journal cut at "ASPM disabled" (09:36:37.77) with zero T243 breadcrumbs landed. Two plausible explanations:

- **(a)** T243 V2 probe fires at t+100ms dwell; `brcmf_pcie_select_core(PCIE2)` → MBM write under correct selection triggers a wedge faster than `pr_emerg` can flush. Result: ~15–20s of tail truncation swallows set_active, t+100ms dwell, and all T243 lines together.
- **(b)** Wedge moved earlier for unrelated reasons — boot variance, SMC-reset residue, or a compile artifact outside the macro itself. T243 probe never fired.

The cheapest way to split (a) from (b) is to run the **same binary** with `writeverify_v2=0` (T243 probe gated off). If wedge comes at [t+90s, t+120s] like test.240/241/242, (a) is confirmed and we can design test.245 around "post-set_active PCIE2-register writes are a wedge trigger" with proper safety. If wedge comes early again, (b) is confirmed and we investigate further.

### Plan

1. **Do not rebuild.** The module (commit 22a8dcb) already has the T243 V2 param with default 0. The `BCM4360_T243_WRITEVERIFY` macro is only expanded at t+100ms and t+2000ms dwell invocation sites, and both are gated on `if (bcm4360_test243_writeverify_v2)`. With the param at 0, the macro body does not execute and the probe path is functionally identical to test.240's (which landed 22/23 dwells through t+90s).
2. **Use the exact param set as test.240** (as the shape-match baseline): `force_seed=1 ultra_dwells=1 poll_sharedram=1 wide_poll=1` — no write-verify, no DB1 ring, no ring doorbell, no T242 writeverify. Everything else default (0).
3. **Expected per hypothesis:**

| Outcome | Interpretation | Next step |
|---|---|---|
| Journal reaches t+60000ms or later dwell (≥t+60s post-set_active); wedge in [t+90s, t+120s] | (a) confirmed — T243 probe is the wedge cause. Post-set-active PCIE2 write (MBM or select_core) is hazardous. | Design test.245: move MBM / BAR2 diagnostic to **pre-FORCEHT** (test.241's stage, known to land every run) under `select_core(PCIE2)`. Safer because ARM isn't running, and upstream does select_core(PCIE2) there routinely. |
| Journal cuts before set_active or early in dwell (≤t+5000ms) | (b) — something drifted. Probe was never the culprit; need a separate investigation. | Re-verify binary (md5 modinfo, strings for T243 lines still present, param list unchanged); check dmesg for early-boot signals; consider rmmod + re-insmod on same boot to test for boot-state residue. |
| Journal lands through t+10..60s but cuts before t+90s | Intermediate — wedge window shifted. Not classic (a) or (b). | Capture everything and decide from the data. |

### Run sequence

```bash
sudo insmod phase5/work/drivers/.../brcmutil.ko
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: `writeverify_v2` is omitted, relying on its `static int ... = 0` default.

### Hardware state (current, 09:5x BST boot 0 post-SMC-reset from test.243)

- `lspci -s 03:00.0`: `I/O- Mem- BusMaster-` (steady state with no driver), MAbort-, DEVSEL=fast — clean; no dirty-state residue (no MAbort+).
- No brcm modules loaded.
- Boot 0 started 2026-04-23 09:43:30 BST.

### Build status — NO REBUILD NEEDED

This is a null-run of the existing commit 22a8dcb binary. The T243 param defaults to 0 when omitted at insmod. No source change.

### Expected artifacts

- `phase5/logs/test.244.run.txt`
- `phase5/logs/test.244.journalctl.full.txt`
- `phase5/logs/test.244.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: NO REBUILD (same binary as test.243).
2. PCIe state: verified clean above.
3. Hypothesis: stated above — (a) vs (b) null-run discriminator.
4. Plan: this block; commit + push + sync before insmod.
5. Filesystem sync on commit.

---


## PRE-TEST.243 (2026-04-23 09:2x BST, boot 0 post-SMC-reset from test.242) — re-run MBM write-verify **under explicit `select_core(PCIE2)`** at the same two dwell points, add BAR0_WINDOW config-space logging, switch to invert-and-restore sentinel, add BAR2-TCM round-trip at a dead offset

### Hypothesis

Source review after test.242 identified that tests 240/241/242 all
wrote through BAR0 with the window pointing at the wrong core
(see *Current state* block for details). None of those writes
tested what they claimed to test. Test.243 re-tests the original
"can we write MAILBOXMASK?" question with correct core-selection
so we can finally tell whether:

| Claim | Expected with correct select |
|---|---|
| BAR0 write path via `brcmf_pcie_write_reg32` works for PCIE2 registers after explicit `select_core(PCIE2)` | MBM round-trip PASSes under invert-and-restore; BAR0_WINDOW log shows 0x18003000 (PCIE2 base) during the writes |
| BAR0 write path is broken for PCIE2 registers even under correct selection | MBM round-trip FAILs even with window confirmed at 0x18003000; BAR2 round-trip PASSes → contrast = specifically-PCIE2-gated |
| All post-set_active MMIO writes are silently dropped | Both MBM and BAR2 round-trips FAIL. (Contradicts test.229 probe evidence — unlikely — but the BAR2 check is the blind-spot cover.) |

### Plan

1. **New module param** `bcm4360_test243_writeverify_v2` (default 0).
2. **Gating:** when set, the probe runs the V2 round-trip at the
   same two dwell points as test.242 (t+100ms, t+2000ms). The old
   test.242 round-trip is disabled for this run
   (`writeverify_postactive=0`) so we have exactly one write-verify
   path active per dwell.
3. **BAR0_WINDOW confirmation (before → after):**
   ```c
   u32 win_before, win_after;
   pci_read_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, &win_before);
   brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
   pci_read_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, &win_after);
   ```
   Log both. `win_after` should be 0x18003000 (PCIE2 base per
   test.218's core map).
4. **MBM round-trip (invert-and-restore):**
   ```c
   baseline = read_reg32(MBM);
   write_reg32(MBM, ~baseline);      /* guaranteed differs from baseline */
   after_sent = read_reg32(MBM);
   write_reg32(MBM, baseline);        /* restore */
   after_restore = read_reg32(MBM);
   ```
   PASS = `after_sent == ~baseline` AND `after_restore == baseline`.
   (Using invert rather than a fixed sentinel 0xDEADBEEF avoids
   reserved-bit-clipping corner cases, and ensures the test is
   informative even if baseline happens to be 0.)
5. **Restore prior window** via
   `pci_write_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, win_before)`
   after the round-trip so the ladder's downstream state is
   unperturbed (not strictly needed since `read_ram32` uses BAR2,
   but "don't leave global state changed by probe code" is a cheap
   principle).
6. **BAR2 round-trip at TCM[0x90000]** — same dwell points. Per
   test.233, this offset sits above fw (ends at 0x6bf78) and
   below NVRAM (0x9ff1c), and is never written by our driver code
   or by fw in normal flow. Use `brcmf_pcie_write_ram32` /
   `brcmf_pcie_read_ram32` (BAR2, not affected by BAR0_WINDOW):
   ```c
   bar2_base = read_ram32(0x90000);
   write_ram32(0x90000, ~bar2_base);
   bar2_sent = read_ram32(0x90000);
   write_ram32(0x90000, bar2_base);  /* restore */
   bar2_restore = read_ram32(0x90000);
   ```
   Log four values plus PASS/FAIL. BAR2 TCM writes were proven
   during fw download (16/16 MATCH verify); this confirms the write
   path is still open post-set_active — a clean independent axis.

### Log format (per dwell)

```
test.243: t+Xms BAR0_WINDOW before=0xYYYYYYYY after=0x18003000 (expected PCIE2 base)
test.243: t+Xms MBM baseline=0x... sent=0x... (match=%d) restored=0x... (match=%d) RESULT ...
test.243: t+Xms BAR2 TCM[0x90000] baseline=0x... sent=0x... (match=%d) restored=0x... (match=%d) RESULT ...
```

### Expected outcomes / next-step matrix

| MBM result | BAR2 result | Interpretation | Test.244 direction |
|---|---|---|---|
| PASS | PASS | BAR0 writes to PCIE2 registers work when core is correctly selected. Tests 240/241/242's nulls were all this defect. Doorbell branch re-opens cleanly. | Ring DB1 at t+2000ms (with explicit `select_core(PCIE2)` wrapper); observe fw response. |
| FAIL | PASS | BAR0-PCIE2 writes are specifically gated post-set_active. BAR0 path generally is fine (test.193/224), BAR2 TCM writes work. Interesting — could mean PCIE2 core enters a reset or clock-gated state once ARM runs. | Test a write at t+100ms vs t+2000ms separately; try MBM during a dwell with `FORCEHT` just reapplied; inspect PCIE2 wrapper IOCTL state (is it in reset?). |
| PASS | FAIL | Very unlikely — BAR0 writes work but BAR2 TCM writes fail post-set_active. Would suggest fw or chip has unmapped TCM at t+100ms. | Re-check BAR2 base in config space; may indicate BAR window collapse. |
| FAIL | FAIL | All MMIO writes silently dropped post-set_active. Would contradict test.193/224 CC writes that DID land pre-FORCEHT — so more likely suggests MMIO accessible pre-set_active but not post-. Would reshape the investigation. | Focus on post-set_active MMIO survival; re-run the round-trips at t+100ms with ARM held (test.230 baseline) to isolate set_active dependence. |

### Code change outline

1. In pcie.c near the existing test.242 params, add
   `bcm4360_test243_writeverify_v2` param block.
2. Add a new macro `BCM4360_T243_WRITEVERIFY(ms_tag)` next to
   `BCM4360_T242_WRITEVERIFY`. Implements steps 3-6 above.
3. In the dwell ladder (lines 2829-onwards), call
   `BCM4360_T243_WRITEVERIFY("100ms")` after the existing t+100ms
   dwell breadcrumb (and remove test.242 call for this run) —
   similarly for t+2000ms.
4. Keep `BCM4360_T242_WRITEVERIFY` in the code path but gate it
   on its own param (which we'll leave off for test.243 runs).
5. Preserve all other module params (force_seed, ultra_dwells,
   poll_sharedram, wide_poll) so dwell / sharedram / tail-TCM
   signals remain directly comparable to prior tests.

### Safety

- `select_core(PCIE2)` sets BAR0_WINDOW to the PCIE2 core base
  (0x18003000). Upstream brcmfmac does this routinely at probe
  and attach paths (pcie.c:1030, 1053, 3226, 3580, etc). Its only
  side effect for our flow is that BAR0's low 4 KB now maps
  PCIE2 core instead of whatever it was. After round-trip,
  we restore the prior window.
- Writing `~baseline` to MBM briefly flips all bits before the
  immediate restore to baseline. Upstream's `brcmf_pcie_intr_enable`
  writes non-zero values to MBM in normal flow, so whatever
  ~baseline happens to be is within the register's usable range.
  Immediate restore limits the live-disturbance window to ~1 µs.
- Writing to TCM[0x90000] writes to a dead region of on-chip
  RAM (above fw, below NVRAM, never touched by host or fw in
  normal flow per test.233). Immediate restore in case fw does
  look at it.
- Both round-trips together add ≤10 MMIO ops per dwell (≤20 total
  at two dwell points). Within the noise of existing per-dwell
  load; should not shift the wedge.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test243_writeverify_v2=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Hardware state (current, 09:2x BST boot 0 post-SMC-reset from test.242)

- `lspci -s 03:00.0`: `Mem+ BusMaster+`, MAbort-, CommClk+,
  DEVSEL=fast (captured pre-test.242 log; verify again pre-insmod).
- No brcm modules loaded.
- Boot 0 started 2026-04-23 09:15:26 BST.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~09:3x BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
Verified:
- `modinfo` reports `parm: bcm4360_test243_writeverify_v2: ...`.
- `strings` shows all six test.243 format lines (BAR0_WINDOW +
  MBM + BAR2 TCM at both t+100ms and t+2000ms).
Only pre-existing unused-variable warnings; no new regressions.

### Expected artifacts

- `phase5/logs/test.243.run.txt`
- `phase5/logs/test.243.journalctl.full.txt`
- `phase5/logs/test.243.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + strings verify before insmod.
2. PCIe state: clean per above; re-verify pre-insmod.
3. Hypothesis: stated above.
4. Plan: in this block; commit + push + sync before code change.
5. Filesystem sync on commit.

---


## Older test history (test.240 and earlier)

Full detail for test.240 and all earlier tests →
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
