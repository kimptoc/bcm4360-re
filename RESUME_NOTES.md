# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 09:4x, POST-TEST.243 — wedge moved EARLIER, before dwell ladder; none of T243's probe lines landed) — test.243 with `writeverify_v2=1` captured only 49 BCM4360 breadcrumbs vs test.242's 408. Journal tail cut at "ASPM disabled" (09:36:37.77). None of the test.243 V2 probe's own pr_emerg lines (BAR0_WINDOW before/after, MBM round-trip, BAR2 TCM round-trip) fired to disk. The last breadcrumb that landed is ~7s before set_active in the test.242 timing. Given journald's 15–20s tail-loss budget, the wedge fell somewhere in the window from "root-port LnkCtl dance" through the first dwell ladder iteration — i.e. **earlier than every prior test in this boot series**. Leading hypothesis: the test.243 probe itself, on its first firing at t+100ms, wedges the host before pr_emerg can flush — which would mean `brcmf_pcie_select_core(PCIE2)` (or the MBM write under correct selection) post-set_active is itself a wedge trigger. Alternative: wedge has moved earlier for unrelated reasons (boot-state variance; SMC reset + reboot residue). Need a diagnostic that doesn't depend on surviving to post-set_active to fire.

### Post-test source review — silent defect found in tests 240/241/242

`brcmf_pcie_write_reg32(devinfo, OFFSET, val)` is a plain
`iowrite32(val, devinfo->regs + OFFSET)`. `devinfo->regs` is the
BAR0 mapping; the chip-side register targeted depends on the
current `BRCMF_PCIE_BAR0_WINDOW` PCI-config-space value, which
selects which on-chip core's first 4 KB is visible at the low
part of BAR0. Changing that window is done by
`brcmf_pcie_select_core(devinfo, CORE_ID)`.

**What select_core state was live when each test's write fired:**

| Test | Write location in code | Last select_core before the write | BAR0 window pointing at | Register actually written |
|---|---|---|---|---|
| 240 (DB1 ring at t+2000ms) | dwell ladder, post-`brcmf_chip_set_active` | `brcmf_chip_cr4_set_active` → `brcmf_chip_resetcore(CR4)` uses CR4 wrapbase for its last MMIO | CR4 wrapbase = 0x18102000 | **CR4_wrap+0x144** (NOT H2D_MAILBOX_1) |
| 241 (MBM round-trip pre-FORCEHT) | after BM-dance, pre-FORCEHT | `probe_d11_clkctlst` → `select_core(CHIPCOMMON)` at the end of the helper | CC base = 0x18000000 | **ChipCommon+0x4C** (likely gpio_out; matches 0x318 baseline = GPIO bits 3,4,8,9) |
| 242 (MBM round-trip t+100ms / t+2000ms) | dwell ladder, post-set_active | same as test.240 (CR4 wrapbase) | CR4 wrapbase = 0x18102000 | **CR4_wrap+0x4C** (NOT MAILBOXMASK) |

**Upstream's own test.96 block** (pcie.c:3566-3644) that writes
MBM=0x00FF0300 pre-ARM-release **explicitly**
`brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)` before the
writes (line 3580). Our test.241/242/240 probes did not. That's
the defect.

**Retroactive re-reading of the three runs:**

- **test.240:** "DB1 ring readback=0, no downstream effect" →
  *untested*: we never actually wrote to H2D_MAILBOX_1. The
  doorbell hypothesis is re-open (needs proper selection and
  re-run).
- **test.241:** "MBM baseline=0x318, writes don't latch
  pre-FORCEHT" → *untested for MBM*: we read/wrote ChipCommon+0x4C
  (gpio_out). The 0x318 baseline is a GPIO state, not an MBM state.
  BAR0 write path question for PCIE2 registers remains unresolved.
- **test.242:** "MBM baseline=0 at both t+100ms and t+2000ms,
  writes don't latch post-set_active" → *untested for MBM*: we
  read/wrote CR4_wrap+0x4C. Its 0x00 baseline is a CR4 wrapper
  state. BAR0 write path question for PCIE2 registers still
  unresolved.

**What we DO have evidence for (from test.193 / test.224):** the
plain `brcmf_pcie_write_reg32` path works for *at least one*
on-chip core — ChipCommon: PMU WAR writes at chipcontrol#1
(0x210→0xa10) and max_res_mask (0x13f→0x7ff) DID change the
chip-side value, as observed in journald with before/after
readbacks. Those runs had `select_core(CHIPCOMMON)` set first.
So "BAR0-write-path broken" is inconsistent with direct
evidence for at least the CC window.

### Plan (PRE-TEST.243, details below)

Re-run the MBM round-trip with an explicit
`brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)` before the
round-trip at each of the two dwell points, log the
`BRCMF_PCIE_BAR0_WINDOW` config-space value before AND after the
select (to make the window state evidence not an assumption),
use **invert-and-restore** (`~baseline`) sentinels (more robust
than 0xDEADBEEF against reserved-bit clipping; also removes the
"wrote 0 matches baseline 0 trivially" confound from test.242),
and add a **BAR2 round-trip** at a dead TCM offset (one 4-byte
slot at ~0x90000 — above fw, below NVRAM, unwritten by our code
or fw per test.233) as an independent axis for "is ANY write
landing post-set_active." Restore the prior BAR0_WINDOW before
handing back to the ladder.

**Hardware state (current, 09:1x BST boot 0 post-SMC-reset from test.242 wedge):**
`lspci -s 03:00.0` shows `Mem+ BusMaster+`, MAbort-, CommClk+,
DEVSEL=fast. No brcm modules loaded. Boot 0 started
2026-04-23 09:15:26 BST.

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

## Prior outcome (test.242 — write-verify at "MAILBOXMASK" FAILed at BOTH t+100ms and t+2000ms post-set_active; see reinterpretation above — probe wrote to CR4_wrap+0x4C, not MBM)

**Latest outcome (test.242):** With `force_seed=1`,
`ultra_dwells=1`, `poll_sharedram=1`, `wide_poll=1`,
`writeverify_postactive=1`, the probe deferred write-verify into
the dwell ladder and logged the MBM round-trip at the FIRST two
ladder breadcrumbs (post-set_active, same stage where test.240
rang DB1). Result:

```
test.242: t+100ms MAILBOXMASK (BAR0+0x4c) baseline=0x00000000 sent=0x00000000 (match=0) cleared=0x00000000 (match=1) RESULT FAIL
test.242: t+2000ms MAILBOXMASK (BAR0+0x4c) baseline=0x00000000 sent=0x00000000 (match=0) cleared=0x00000000 (match=1) RESULT FAIL
```

Set_active returned TRUE at 09:00:17 BST. Ladder then landed
**22 of 23 dwells** (t+100ms..t+90000ms, identical pattern to
tests 238/239/240/241). sharedram_ptr = `0xffc70038` at every
poll; wide-TCM[-64..-8] held NVRAM text at every poll. Journal
ends 09:01:49 BST at t+90000ms; t+120000ms never landed. Wedge
bracket still [t+90s, t+120s]. Host wedged; SMC reset
performed; current boot 0 started 09:15:26 BST.

**Critical discriminator result — FAIL/FAIL row of the PRE-TEST.242 matrix:**
The matrix pre-committed this outcome to
*"BAR0 write path is broken post-set_active too. test.240 DB1
never reached chip; (c) confirmed. Stop all doorbell attempts.
Investigate core-select window / aperture; compare to upstream's
pre-set_active MBMASK writer block."* That pivot is now on the
table for test.243 — detailed framing in PRE-TEST.243.

**But watch the caveats** (surface before deciding on test.243):

- **"cleared match=1" is trivially true at both points.** We wrote
  `0` and read `0`, which matches whether or not our write landed
  (baseline was already 0). The only informative comparison is
  the `sent` readback vs `0xDEADBEEF`, which FAILed at both stages.
- **Baseline changed 0x318 → 0x00** between pre-FORCEHT (test.241)
  and post-set_active (test.242). Something (FORCEHT, chip_set_active,
  fw start, CR4 rstvec, or a combination) cleared MBM's bits. So
  MBM's *read* side responds to stage changes — it's not a dead
  slot — but its *write* side didn't take writes from us at either
  stage we tested.
- **MAILBOXMASK may be specifically write-gated at our probe points.**
  Upstream brcmfmac only *writes* MBM via `brcmf_pcie_intr_enable`
  at pcie.c:1339, which fires post-fw-up and post-shared-init — far
  later than both our stages. So MAILBOXMASK writes may legitimately
  be silently dropped until a specific enable-condition is met
  (interrupt-capability handshake? ring-base programmed? share-magic
  seen?). If that's true, **the FAIL/FAIL result does NOT rule out
  the general BAR0 write path** — it only rules out writes to
  MAILBOXMASK at these two specific stages.
- **No other BAR0 register has been tested for write-verify.** The
  MBM-only evidence is not a comprehensive "BAR0 write path" test.

**Implication for test.243:** before wholesale abandoning doorbells,
test.243 should broaden the write-verify to register(s) we *know*
upstream brcmfmac writes **at or before** our probe stages — e.g.
`PCIe2_IntMask` (MAILBOXINT, `devinfo->reginfo->mailboxint` at
BAR0+0x48) which upstream reads/writes during probe setup, or the
ring-base registers that `brcmf_pcie_init_share` programs. If those
*also* FAIL the round-trip, the BAR0-write-path theory strengthens.
If they PASS, MBM is simply stage-gated and doorbells re-open as a
valid branch. Details in PRE-TEST.243.

---

## Prior outcome (test.241 — write-verify at MAILBOXMASK pre-FORCEHT FAILED; read path works, sentinel writes did not latch; test confounded with stage, not conclusive about (c))

**Test.241 outcome:** With `force_seed=1`,
`ultra_dwells=1`, `poll_sharedram=1`, `wide_poll=1`,
`writeverify=1`, the probe logged the MAILBOXMASK round-trip right
after `pci_set_master` (post-BM-on, pre-FORCEHT, pre-set_active).
Result:

```
test.241: write-verify target MAILBOXMASK offset=0x4c (BAR0)
test.241: MAILBOXMASK baseline=0x00000318 (expect 0x00000000)
test.241: after write=0xDEADBEEF readback=0x00000318 (expect 0xDEADBEEF)
test.241: after write=0x00000000 readback=0x00000318 (expect 0x00000000)
test.241: RESULT FAIL (sentinel-match=0 baseline-zero=0 clear-zero=0)
```

The probe then continued through FORCEHT, set_active (returned
TRUE at 08:30:09 BST), and landed **the same 22 dwells as
test.239/240** (t+100ms..t+90000ms). All 22 sharedram_ptr polls
held `0xffc70038`; all 22 wide-TCM[-64..-8] samples held the same
NVRAM text. Wedge bracket unchanged [t+90s, t+120s]. Host wedged;
SMC reset; current boot 0 started 08:33:44 BST, PCIe clean
(`Mem+ BusMaster+`, MAbort-, CommClk+).

**What test.241 proves and does not prove:**

- **Proves:** at our probe stage immediately after `pci_set_master`
  and before FORCEHT/set_active, writing 0xDEADBEEF (and later 0)
  to `devinfo->reginfo->mailboxmask` (BAR0+0x4c) does NOT change
  the readback value. The readback (0x00000318) is deterministic
  and non-trivial — reads reach a real register, writes don't
  latch there at this stage.
- **Does not prove** that BAR0 writes are broken generally, because:
  - **Stage mismatch with test.240's DB1 write.** Test.240 rang DB1
    at **t+2000ms post-set_active**, i.e. AFTER FORCEHT clocks
    forced and CR4 rstvec set. Test.241 wrote MAILBOXMASK **before**
    any of that. Upstream's own MAILBOXMASK writes
    (`brcmf_pcie_intr_enable`, pcie.c:1339) happen post-shared-init,
    much later than our probe point — so MAILBOXMASK may be in a
    clock/reset domain that's only writable post-set_active.
  - **Our PRE-TEST.241 assumption was wrong.** The plan said
    "MAILBOXMASK defaults to 0 and accepts arbitrary writes." The
    baseline is 0x318 (bits 3,4,8,9), not 0. Unexplained — not
    from any of our current code paths; possible hardware power-
    on default or residual from an earlier boot, but we haven't
    identified the origin.
  - **Dead-code note.** pcie.c:3524+ contains a "test.96" block
    that is supposed to write MAILBOXMASK=0x00FF0300 pre-ARM-release
    and log a readback. That block is inside `brcmf_pcie_download_fw_nvram`
    but downstream of an early-return / different path — zero
    test.96 MBMASK lines appear in this or any recent run's
    journal, so we have no prior evidence either way for whether
    BAR0 writes to MAILBOXMASK ever land.

**Disposition of the three test.240 readings:**

1. **(a) doorbell self-clears / fw saw it and ignored** — still
   plausible.
2. **(b) offset not RAM-backed pre-shared-init** — still plausible.
3. **(c) our BAR0 write did not reach the chip** — *not* cleanly
   confirmed by test.241 because of stage mismatch. Strength of
   (c) is NOT settled; test.241's FAIL is consistent with "MAILBOXMASK
   is gated against writes at our pre-FORCEHT stage" which says
   nothing about H2D_MAILBOX_1 writes at post-set_active stage.

**Next step (test.242 — direct discriminator):** repeat write-verify
at the **same stage DB1 was rung in test.240**, post-set_active,
during the ultra-dwell ladder (e.g. at t+100ms and again at
t+2000ms). Same register (MAILBOXMASK) to keep one axis fixed. If
the writes latch post-set_active, stage-gating is confirmed and
the DB1 null in test.240 is best explained by (a)/(b). If the
writes still fail post-set_active, (c) is a real problem in our
BAR0-write path and we must investigate core-select / aperture /
window state before any more doorbell attempts. Full plan in
PRE-TEST.242 (next).

**Hardware state (current, 08:5x BST boot 0):** `lspci -s 03:00.0`
shows `Mem+ BusMaster+`, MAbort-, CommClk+, DEVSEL=fast. No brcm
modules loaded. SMC reset performed between test.241 wedge and
current boot.

---

## Prior outcome (test.240 — DB1 ring at t+2000ms had zero observable effect; readback=0x00000000; BAR0-write-path itself unverified)

Test.240 ran with `force_seed=1 ultra_dwells=1 poll_sharedram=1
ring_h2d_db1=1 wide_poll=1`. Probe was clean through fw download,
NVRAM, seed, FORCEHT, `pci_set_master`, `brcmf_chip_set_active`
(returned TRUE at 08:02:46 BST). At the t+2000ms dwell, the
driver wrote `1` to `devinfo->reginfo->h2d_mailbox_1` (BAR0+0x144)
via `brcmf_pcie_write_reg32`; readback immediately after was
`0x00000000`. The ladder then landed 22 of 23 dwells
(t+100ms..t+90000ms) matching test.238/239 exactly; sharedram_ptr
and wide-TCM[-64..-8] unchanged throughout. Wedge same bracket
[t+90s, t+120s]. See **POST-TEST.240** block below for full
evidence.

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
| `brcmf_pcie_write_reg32` BAR0 write path reaches chip when BAR0_WINDOW is explicitly `select_core`d first | 193, 224 | **confirmed (partial)** — test.193 PMU WAR chipcontrol#1 write 0x210→0xa10 and test.224 max_res_mask 0x13f→0x7ff both had visible before/after change in journald readbacks. Both used `WRITECC32` = `brcmf_pcie_write_reg32` under `select_core(CHIPCOMMON)`. So BAR0-write path works for CC under correct selection. Evidence for PCIE2-core writes still pending test.243. |

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


## POST-TEST.242 (2026-04-23 09:01 BST, boot -1 — write-verify at MAILBOXMASK **post-set_active** at t+100ms AND t+2000ms both FAILED; baseline cleared 0x318→0x00 across stage boundary; write side still non-responsive; dwell ladder + wedge unchanged)

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1
bcm4360_test242_writeverify_postactive=1`. test.241's pre-FORCEHT
write-verify was disabled for this run; test.240's DB1 ring was
also disabled. Probe reached `brcmf_chip_set_active`; it returned
TRUE at 09:00:17 BST. Write-verify fired at the t+100ms and
t+2000ms ladder breadcrumbs:

```
Apr 23 09:00:17 test.242: t+100ms  MBM baseline=0x00000000 sent=0x00000000 (match=0) cleared=0x00000000 (match=1) RESULT FAIL
Apr 23 09:00:19 test.242: t+2000ms MBM baseline=0x00000000 sent=0x00000000 (match=0) cleared=0x00000000 (match=1) RESULT FAIL
```

Ladder ran normally after each probe: 22 of 23 dwells landed
(t+100, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000, 15000,
20000, 25000, 26000, 27000, 28000, 29000, 30000, 35000, 45000,
60000, 90000 ms). Last line 09:01:49 BST. `t+120000ms` never
landed. Host wedged; user performed SMC reset; current boot 0
started 09:15:26 BST.

### Matrix outcome (per PRE-TEST.242)

FAIL / FAIL row: *"BAR0 write path is broken post-set_active too.
test.240 DB1 never reached chip; (c) confirmed. Stop all doorbell
attempts. Investigate core-select window / aperture."* That is the
strong reading — but the caveats in "Current state" above apply:
the evidence is specific to MAILBOXMASK and does not yet
generalise to "all BAR0 writes" until we test at least one other
BAR0 register that upstream brcmfmac writes at a stage ≤ ours.

### Stage-transition signal (new)

| Stage | Baseline read of MBM |
|---|---|
| After `pci_set_master`, pre-FORCEHT (test.241) | `0x00000318` (bits 3,4,8,9) |
| First dwell post-set_active (test.242 t+100ms) | `0x00000000` |
| Second dwell post-set_active (test.242 t+2000ms) | `0x00000000` |

Something between "post-BM-on pre-FORCEHT" and "post-set_active
t+100ms" clears MBM's read-side bits. Candidates (not yet
distinguished): FORCEHT turning on HT clocks; the BAR window
reselect that `brcmf_chip_set_active` performs; fw executing a
mask clear immediately after CR4 rstvec. The chipcontrol /
backplane indirection is NOT in our MMIO-32 path, so the change
has to be mediated by chip-side logic, not by our code writing to
MBM (which we couldn't do). This is additional evidence that MBM
*state* is real and stage-sensitive — the register is not a dead
address.

### "cleared match=1" caveat

Both dwell probes report `cleared match=1` (wrote 0, read 0). This
is trivially true because the baseline was already 0 — the write
of 0 is indistinguishable from a silent drop at readback time. The
only informative signal in this run is the sentinel compare, which
is `match=0` at both stages.

### Wedge / ladder behaviour

Same as test.238/239/240/241:

- Dwell breadcrumbs: 22 of 23, missing only t+120000ms.
- `sharedram_ptr`: `0xffc70038` at every poll (fw never advances
  to shared-struct allocation within the observed ≥90s window).
- Wide-TCM[ramsize-64..-8]: NVRAM text unchanged at every poll.
- Journal ends 09:01:49 BST → wedge in same [t+90s, t+120s]
  bracket. No Oops / Call Trace / softlockup / hardlockup in
  boot -1 journal.

Adding the post-set_active write-verify (two round-trips during
the ladder) did NOT shift the wedge timing — consistent with
every prior incremental instrumentation addition being invisible
to the wedge trigger.

### Artifacts

- `phase5/logs/test.242.run.txt` — PRE harness + insmod output
  (truncated at "sleeping 240s" as expected; host wedged during
  sleep).
- `phase5/logs/test.242.journalctl.full.txt` (1504 lines) — full
  boot -1 journal.
- `phase5/logs/test.242.journalctl.txt` (422 lines) — filtered
  BCM4360 / brcmfmac / watchdog subset.

### What test.243 must settle (framing for PRE block)

Before pivoting wholesale to "core-select window / aperture"
investigation, verify whether MAILBOXMASK specifically is
stage-gated vs. whether BAR0 writes are broken in general. One
extra register round-trip at both ladder points (t+100ms,
t+2000ms) against a register upstream brcmfmac writes at or
before our probe stage — candidates: `devinfo->reginfo->mailboxint`
(BAR0+0x48), or the PCIe2 INT_MASK / PCIE2_INTMASK registers
which `brcmf_pcie_intr_disable`/_attach_bus/_probe touch earlier
— would give a clean discriminator. If the second register
PASSes, MBM is register-gated and doorbells remain on the table.
If the second register also FAILs, the BAR0 write path theory
strengthens and core-select / aperture investigation becomes
the right path.

---


## POST-TEST.241 (2026-04-23 08:29 BST, boot -1 — write-verify at MAILBOXMASK pre-FORCEHT FAILED; read path live, writes did not latch; result confounded with stage)

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1
bcm4360_test241_writeverify=1`. `bcm4360_test240_ring_h2d_db1` was
intentionally OFF for this run (goal was to measure bare
write-verify, not re-mix a doorbell). Probe reached
`brcmf_chip_set_active` (returned TRUE at 08:30:09 BST). Write-verify
lines fired between the post-BM-on MMIO guard and the FORCEHT block:

```
test.241: write-verify target MAILBOXMASK offset=0x4c (BAR0)
test.241: MAILBOXMASK baseline=0x00000318 (expect 0x00000000)
test.241: after write=0xDEADBEEF readback=0x00000318 (expect 0xDEADBEEF)
test.241: after write=0x00000000 readback=0x00000318 (expect 0x00000000)
test.241: RESULT FAIL (sentinel-match=0 baseline-zero=0 clear-zero=0)
```

All three match bits zero. Ladder then ran 22 dwells
(t+100ms..t+90000ms); last line 08:31:41 BST. `t+120000ms` never
landed. Host wedged; SMC reset performed by user; current boot 0
started 08:33:44 BST.

### What the FAIL signals

The **read** path to BAR0+0x4c is live: returns a deterministic
non-trivial value (0x318, not 0 and not 0xffffffff). The **write**
path at this stage does not change that value. Two candidate
interpretations, neither ruled out by this run alone:

1. **Stage-gated register.** MAILBOXMASK sits in a clock or reset
   domain that's dormant until FORCEHT / set_active. Writes are
   silently dropped at this stage but would land later. Consistent
   with upstream brcmfmac: the only production writer is
   `brcmf_pcie_intr_enable` (pcie.c:1339), which runs post-fw-up
   / post-shared-init — far later than our probe insertion point.
2. **Generally broken BAR0 write path.** Our
   `brcmf_pcie_write_reg32(devinfo, offset, val)` =
   `iowrite32(val, devinfo->regs + offset)` is somehow not landing
   on-chip (wrong window, posted-write blocked, aperture issue).
   If true, the DB1 write in test.240 also didn't land, making the
   readback=0 there trivial and test.240 re-opens.

These are different claims with different implications — test.241
does not pick between them because it tested at a stage where
MAILBOXMASK writes may legitimately be non-functional. The
discriminator is to re-run write-verify **post-set_active** at
the same ladder points where test.240's DB1 fired. That is
PRE-TEST.242.

### Wedge / ladder behaviour

Identical to test.239 and test.240:

- Dwell breadcrumbs: 22 of 23 landed (t+100ms .. t+90000ms).
- sharedram_ptr: `0xffc70038` at every poll (no fw write).
- Wide-TCM[ramsize-64..ramsize-8]: NVRAM text unchanged at every
  poll (no fw write).
- Journal ends 08:31:41 BST; wedge in same [t+90s, t+120s] bracket.
- No Oops / Call Trace / softlockup / hardlockup in boot -1.

Adding the write-verify sequence did NOT shift the wedge timing —
three extra BAR0 MMIO ops pre-FORCEHT are invisible to the wedge
trigger (consistent with all prior evidence that the wedge is
set_active-gated, not pre-set_active path).

### Unexplained signal

The baseline value `0x00000318` = bits 3, 4, 8, 9. `grep 0x318` in
pcie.c finds no current writer of this specific value. Possible
origins: hardware power-on reset state of MAILBOXMASK for PCIE2
rev=1 on BCM4360; residual state left by a prior boot's driver
before the SMC reset (though SMC reset is supposed to wipe this);
or bits set by early chip init we don't instrument. Noted but
not blocking — what matters for test.242 is that the READ is
deterministic and stable, so a subsequent round-trip will produce
a clean pass/fail regardless of the baseline value.

### PRE-TEST.241 assumption that was wrong

The PRE block claimed "MAILBOXMASK defaults to 0 and accepts
arbitrary writes." Baseline ≠ 0 (it's 0x318), and writes don't
latch. Both halves of the assumption failed. The choice of
MAILBOXMASK as a discriminator register was also weak in
retrospect: upstream only writes it post-shared-init, so we had
no precedent showing writes to this register are even meant to
land at our probe stage.

### Dead-code clarification

pcie.c lines 3524+ ("test.96") write MAILBOXMASK=0x00FF0300 and
log a readback. Same function as our test.241 insertion
(`brcmf_pcie_download_fw_nvram`), but downstream of a branch/return
that is taken in our current flow — zero `test.96 MBMASK`
lines appear in this run's journal or any recent run's journal.
So no historical BAR0-write verification to lean on.

### Artifacts

- `phase5/logs/test.241.run.txt` — PRE harness + insmod output
  (truncated at "sleeping 240s" because host wedged during sleep).
- `phase5/logs/test.241.journalctl.full.txt` (1488 lines) — full
  boot -1 journal.
- `phase5/logs/test.241.journalctl.txt` (417 lines) — filtered
  BCM4360 / brcmfmac / watchdog subset.

---


## PRE-TEST.242 (2026-04-23 08:5x BST, boot 0 post-SMC-reset from test.241) — move write-verify POST set_active, ladder-timed, to directly discriminate (c) from stage-gating of MAILBOXMASK

### Hypothesis

Test.241 showed MAILBOXMASK writes don't latch at the pre-FORCEHT
stage, but that doesn't tell us whether BAR0 writes work
**post-set_active** (the stage where test.240 rang DB1). The two
candidate interpretations of test.241's FAIL differ *only* in
how they respond to a stage change:

| Claim | Expected post-set_active write-verify result |
|---|---|
| (1) MAILBOXMASK is stage-gated; BAR0 writes generally fine | PASS — sentinel round-trip works post-set_active |
| (2) BAR0 write path is broken for this register / generally | FAIL — sentinel round-trip still doesn't latch |

Test.242 resolves this by relocating the write-verify from the
pre-FORCEHT insertion point to **inside the dwell ladder**, at
early dwell points post-set_active. If PASS emerges, test.240's
DB1 readback=0 collapses to reading (a) or (b) and we can pivot
to the next doorbell-or-shared-struct branch with confidence. If
FAIL persists, we stop chasing doorbells and investigate the
BAR0-write path (core-select window, aperture, iowrite32 ordering,
etc.) before any further host→fw signalling.

### Plan

1. **New module param** `bcm4360_test242_writeverify_postactive`
   (default 0). When set, inject write-verify round-trips at
   TWO dwell points inside the ultra ladder:
   - **t+100ms** (first dwell after set_active returns)
   - **t+2000ms** (same point where test.240 rang DB1)
2. **Register choice.** Keep MAILBOXMASK (`devinfo->reginfo->mailboxmask`
   = BAR0+0x4c on our pcie2 non-64 variant) to keep ONE axis
   changed (stage) vs test.241. Same baseline / sentinel /
   clear sequence:
   ```c
   baseline    = read_reg32(MBM);
   write_reg32(MBM, 0xDEADBEEF);
   after_sent  = read_reg32(MBM);
   write_reg32(MBM, 0);
   after_clear = read_reg32(MBM);
   pr_emerg("... t+Xms RESULT %s (sent-match=%d clear-zero=%d)\n",
            ...);
   ```
3. **No DB1 ring in test.242.** Keep `ring_h2d_db1=0`. The goal
   is to isolate the write-path variable only.
4. **Preserve all other ladder instrumentation** — force_seed,
   ultra_dwells, poll_sharedram, wide_poll — so dwell / sharedram /
   tail-TCM comparisons to test.239/240/241 remain valid. Skipping
   test.241's pre-FORCEHT writeverify (=0 for this run).
5. If t+100ms PASSes but t+2000ms FAILs (or vice versa), that's a
   strong signal that post-set_active chip state evolves fast
   enough to close the write path mid-ladder — flag for test.243
   but still a clean discriminator for DB1-at-t+2000ms.

### Expected outcomes

| t+100ms | t+2000ms | Interpretation | Test.243 direction |
|---|---|---|---|
| PASS | PASS | BAR0 write path works post-set_active. test.241 FAIL was stage-gating of MAILBOXMASK. test.240's DB1 null = (a) or (b). | ring DB0 at t+2000ms; if also null, pivot to shared-struct pre-alloc in TCM. |
| PASS | FAIL | Write path starts working post-set_active but closes again later. Would explain why DB1 at t+2000ms was invisible. | Test.243 maps when write path is open — spread write-verify across dwell ladder (10 points). |
| FAIL | FAIL | BAR0 write path is broken post-set_active too. test.240 DB1 never reached chip; (c) confirmed. | Stop all doorbell attempts. Investigate core-select window / aperture; compare to upstream's pre-set_active MBMASK writer block. |
| FAIL | PASS | Write path opens later than t+100ms — unusual, but discrimiator for DB1-at-t+2000ms is still clean (writes work there). | Same as PASS/PASS branch for test.243. |

### Code change

1. Add module param `bcm4360_test242_writeverify_postactive` near
   existing test.241 param.
2. At the t+100ms dwell breadcrumb (inside the ultra ladder),
   gated on this param, emit the 5-line round-trip + RESULT line.
3. At the t+2000ms dwell breadcrumb, same treatment.
4. Keep the test.241 pre-FORCEHT block code in place but run
   with `bcm4360_test241_writeverify=0` so it doesn't fire —
   we keep the option to run it again later for cross-check.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test242_writeverify_postactive=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Safety

- Post-set_active MAILBOXMASK writes at t+100ms and t+2000ms are
  during the exact window upstream's `brcmf_pcie_intr_disable`
  (pcie.c:1333) writes 0 to the same register in production
  (called during cleanup). So write + immediate restore to 0 is
  a safe no-op IF writes land. If writes don't land, the register
  state is unchanged — same outcome as test.241 — still safe.
- Two extra 5-op round-trips during the dwell ladder add <100 µs
  total MMIO time; indistinguishable from the existing per-dwell
  read load. Does not affect wedge timing (test.239/240/241 all
  showed the same 22-of-23 pattern despite incremental MMIO
  additions).

### Hardware state (current, 08:5x BST boot 0 post-SMC-reset)

- `sudo lspci -vvv -s 03:00.0`: Control `Mem+ BusMaster+`, Status
  MAbort-, DEVSEL=fast, LnkCtl CommClk+, LnkSta 2.5GT/s x1.
- No brcm modules loaded.
- Boot 0 started 2026-04-23 08:33:44 BST.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~08:58 BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
Verified in module:
- `strings` shows both test.242 round-trip format lines
  (`t+100ms MAILBOXMASK ...`, `t+2000ms MAILBOXMASK ...`).
- `modinfo` reports `parm: bcm4360_test242_writeverify_postactive: ...`.
Only pre-existing unused-variable / unused-function warnings;
no new regressions.

### Expected artifacts

- `phase5/logs/test.242.run.txt`
- `phase5/logs/test.242.journalctl.full.txt`
- `phase5/logs/test.242.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + strings verify before insmod.
2. PCIe state: clean per above.
3. Hypothesis: stated above.
4. Plan: in this block; commit + push + sync before any code change.
5. Filesystem sync on commit.

---


## PRE-TEST.241 (2026-04-23 08:2x BST, boot 0 post-SMC-reset from test.240) — write-verify BAR0 path BEFORE ringing another doorbell; de-confound the "DB1 null" reading

### Hypothesis

Test.240's DB1 ring produced readback=0 and zero downstream effect.
Advisor flagged a three-way ambiguity: (a) doorbell self-clears / fw
saw it and ignored pre-shared-init; (b) offset not RAM-backed pre-
shared-init; (c) our `brcmf_pcie_write_reg32` call at BAR0+0x144
didn't reach the intended register (wrong core-select window, or
wrong aperture). Reading (c) would make a test.241-tries-DB0 run
null-and-uninterpretable for the same reason. We must de-confound
*before* another doorbell attempt.

### Write-verify plan

Inside `brcmf_pcie_attach` / equivalent, immediately after
`pci_set_master` and well BEFORE `brcmf_chip_set_active`, do the
following gated on new module param `bcm4360_test241_writeverify`:

1. **Probe a known-RAM-backed BAR0 scratch** — upstream brcmfmac
   accesses several BAR0-resident registers (e.g. PCIE2 scratch
   slots, intmask register) that are backed by on-chip RAM /
   flip-flops and ARE readable pre-fw-run. Select one from upstream
   where we have confidence about readback semantics (decide exact
   register during code write). Log a read-back BEFORE the test
   write (baseline).
2. **Write a sentinel (0xDEADBEEF)** to that scratch register via
   `brcmf_pcie_write_reg32(devinfo, OFFSET, 0xDEADBEEF)`. Log the
   write.
3. **Immediately read-back** via `brcmf_pcie_read_reg32`. Log the
   result. Expected: `0xDEADBEEF` (confirms BAR0 write path lands).
4. **Write 0** and read-back to confirm the write path is not
   stuck (idempotency check).
5. Only after that, preserve all the test.240 flags (force_seed,
   ultra_dwells, poll_sharedram, wide_poll) but DISABLE
   `ring_h2d_db1` for this run. The purpose of test.241 is to
   establish the write-path works — not yet to re-try a doorbell.

### Expected outcomes

| Write-verify result | Interpretation | Next step |
|---|---|---|
| Step 3 reads `0xDEADBEEF` | BAR0 write path is live for that scratch register. Strengthens (a)/(b) over (c) for test.240. | test.242: ring DB0 at t+2000ms with otherwise identical run. If DB0 also null-and-quiet → "doorbell handshake pre-shared-init" is not the key; pivot to shared-struct pre-alloc. |
| Step 3 reads something other than `0xDEADBEEF` (0, scratch baseline, scrambled) | BAR0-write path is confounded at some offsets. DB1 null (c) supported. Must diagnose core-select window / aperture / indirection. | test.242: add core-select window read+log around write points; also try different scratch offsets to map what's writable. |
| Step 3 read itself returns `0xffffffff` (bus error) | Chip in a bad PCIe state even pre-set_active — would explain a lot of prior noise. | SMC reset + reboot, retest; if reproducible, PCIe link-up / config inspection. |

### Discriminator budget for this boot

- Entire write-verify sequence is ≤5 MMIO ops and a few log lines;
  adds <1 ms to probe execution.
- Keeping ultra-dwells ON costs ≤120 s run-time (wedge expected in
  same [t+90s, t+120s] window), which matters only for prolonging
  the wedge-window wait; write-verify result is logged at probe
  entry and lands in journald long before any wedge.

### Code change (IMPLEMENTED)

1. Module param `bcm4360_test241_writeverify` (default 0) added in
   pcie.c near the test.240 params.
2. Insertion point: inside the BusMaster dance block, immediately
   after the "post-BM-on MMIO guard mailboxint" read at the
   `pr_emerg("BCM4360 test.188: post-BM-on ...")` line, and BEFORE
   the "past BusMaster dance — entering FORCEHT block" line. This
   is after `pci_set_master` succeeds and well before
   `brcmf_chip_set_active`, so write-verify lines hit journald at
   fresh probe entry (pre-wedge) and will land even if the wedge
   bracket is unchanged.
3. Target register: `devinfo->reginfo->mailboxmask` which on BCM4360
   resolves to `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = 0x4C` (non-64
   variant). Upstream already reads/writes this at brcmf_pcie_*
   attach+setup paths (lines 3514/3536 in our tree), so it's a
   proven R/W, RAM-backed mask register that defaults to 0 and
   accepts arbitrary 32-bit writes.
4. Round-trip sequence:
   ```c
   const u32 MBM = devinfo->reginfo->mailboxmask;
   baseline    = read_reg32(MBM);                        /* expect 0 */
   write_reg32(MBM, 0xDEADBEEF);
   after_sent  = read_reg32(MBM);                        /* expect 0xDEADBEEF */
   write_reg32(MBM, 0);
   after_clear = read_reg32(MBM);                        /* expect 0 */
   ```
   Each step emitted via `pr_emerg()`; final line emits a PASS/FAIL
   RESULT with three individual match bits, so the result is
   unambiguous regardless of journald formatting.
5. `ring_h2d_db1` is NOT set at insmod for this run — the goal is
   to measure the bare write-verify, not re-mix DB1 disturbance
   into the result.
6. All other test.236/238/239 paths preserved unchanged.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test241_writeverify=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Write-verify lines land in journald at probe entry (well before any
set_active-triggered wedge), so the RESULT will be retrievable
even if the host wedges again. The ultra-dwell ladder continues
to run after write-verify so we also capture whether the 22-of-23
dwell pattern is steady (same wedge bracket) or has shifted.

### Safety notes

- Write-verify happens BEFORE set_active, so it's inside the
  already-safe pre-set_active path (test.230 confirmed full
  clean run without set_active). Any sentinel we leave on a
  scratch register will be overwritten by fw once fw runs (and
  set_active still runs unchanged after write-verify).
- If we pick a scratch register that is ACTUALLY a control
  register, we could disrupt fw startup. Mitigation: pick a slot
  upstream's brcmfmac treats as benign scratch, or restrict to an
  intmask register where a round-trip of 0xdeadbeef→0 is a no-op
  once we clear it.

### Open items — resolved during code implementation

- **Exact BAR0 offset**: MAILBOXMASK (0x4C on BCM4360, accessed via
  `devinfo->reginfo->mailboxmask`). Picked because upstream
  actively uses this register (proven R/W) and it defaults to 0
  at our pre-init stage, so sentinel round-trip + restore to 0 is
  a true no-op on chip state.
- **Core-select window concern**: `brcmf_pcie_write_reg32` is
  `iowrite32(value, devinfo->regs + offset)` — a plain linear BAR0
  write with NO core-select indirection. So interpretation (c)
  sub-case "wrong core window" does not apply at the MMIO layer.
  (c) can still fire if the specific offset returns 0 by design
  or isn't RAM-backed — which is exactly what MAILBOXMASK
  round-trip rules out (or in, cleanly).

### Hardware state (current, 08:15 BST boot 0 post-SMC-reset)

- `lspci -s 03:00.0`: `Mem+ BusMaster+`, MAbort-, DEVSEL=fast.
- No brcm modules loaded.
- Boot 0 started 2026-04-23 08:09:57 BST.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~08:45 BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
Confirmed in built module:
- `strings` shows all 5 test.241 format lines + param name.
- `modinfo` reports `parm: bcm4360_test241_writeverify: ...`.
Only pre-existing unused-variable and `brcmf_pcie_write_ram32`
warnings — no new regressions.

### Expected artifacts

- `phase5/logs/test.241.run.txt`
- `phase5/logs/test.241.journalctl.full.txt`
- `phase5/logs/test.241.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING.
2. PCIe state: clean per above.
3. Hypothesis: stated above.
4. Plan: in this block; commit+push+sync before any code change.
5. Filesystem sync on commit.

---


## Older test history (test.240 and earlier)

Full detail for test.240 and all earlier tests →
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
