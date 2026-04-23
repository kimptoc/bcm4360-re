# PMU/PCIe Gap Analysis — Reconciliation Against Current Code

**Date:** 2026-04-23 (post-TEST.247)
**Scope:** Track 5 of `phase6/test248_other_work.md`. Annotates
`phase6/pmu_pcie_gap_analysis_final.md` (2026-04-21) against what
`pcie.c` and `chip.c` currently do, after T193, T194, T221–T224, and
T247 landed in code.
**Purpose:** stop stale gap-analysis entries from sending implementation
effort toward writes that have already been attempted. Re-frame the
"what is missing" list around what is actually missing.

---

## 1. Status of the original gap table

The original "Top 5 Ranked Missing Writes" in §4 of
`pmu_pcie_gap_analysis_final.md` is partially out of date. Of the eight
PCIe2-init writes listed in §1.6 and the gap table in §3, several are
now performed by current code. Re-classified below.

### 1.1 Already implemented in current code

| Original gap row | Current implementation | Status note |
|---|---|---|
| `PCIE2_SBMBX` (0x098) = 0x1 | `pcie.c:1173-1178` (test.194) | Done — runs unconditionally for `device == BRCM_PCIE_4360_DEVICE_ID` in `brcmf_pcie_attach`. |
| `PCIE2_PMCR_REFUP` (0x1814) \|= 0x1f | `pcie.c:1180-1191` (test.194) | Done — read-modify-write under same gate as SBMBX. |
| PMU resource masks (HT-grant hypothesis) | `chip.c:1182-1226` (test.224) | Done — `max_res_mask = min_res_mask = 0x7ff`. T221 confirmed `HAVEHT=YES` post-write. Note: 0x7ff was empirically narrowed from 0xffffffff in T223; it is not a wl.ko-derived value. |
| PLL programming (BCM4360-specific) | `chip.c:1146-1180` (test.193) | Done — chipcontrol#1 \|= 0x800 + pllcontrol#6/#7/#0xe/#0xf programmed. Runs unconditionally for `chip == BRCM_CC_4360_CHIP_ID && ccrev > 3`. **Caveat:** PLL_UPD bit (0x400) on `PMU_CTL` is NOT subsequently set — see §1.3. |

### 1.2 Still not implemented (genuinely missing)

| Original gap row | Status | Comment |
|---|---|---|
| `BCMA_CORE_PCIE2_CLK_CONTROL` clear DLYPERST / set DISSPROMLD | Read-only in current code (`pcie.c:1163-1166` reads `CLK_CONTROL` to probe liveness; never writes it). | Highest-priority untried per original §4. Worth a hardware run as a single-variable change. |
| `LTR` config on PCIe2 (LTRENAB at `PCIE2_CAP_DEVSTSCTRL2_OFFSET`) | Not implemented. | Plausibly required for PCIe link-state stability under fw-driven traffic. Less likely to gate fw bring-up before any TCM activity. |
| `BCMA_CORE_PCIE2_LTR_STATE` ACTIVE→SLEEP | Not implemented. | Same caveat as LTR config. |
| `PCIE2_PVT_REG_PM_CLK_PERIOD` = `(2_000_000)/alp_khz` | Not implemented. | If fw uses PM-clock-derived timeouts, an unset period could cause early-stage stall. Worth flagging. |
| `BCMA_CC_PMU_CTL` NOILPONW bit (0x200) | Not implemented. Untouched. | Original §4 ranked #2. ILP-clock-while-waiting state for the chip; if fw reads it during a wait loop, mis-state could explain stall. |
| `BCMA_CC_PMU_CTL` PLL_UPD bit (0x400) | Not implemented. | Convention is "set after programming PLL." Test.193 programs PLL but never asserts PLL_UPD. **New finding** not in the original gap table. |

### 1.3 New observation: PLL_UPD never asserted post-T193

Test.193 writes pllcontrol#6/#7/#0xe/#0xf but does **not** subsequently
set `PMU_CTL.PLL_UPD`. In bcma's flow the PLL_UPD bit is the "commit"
that latches the new PLL programming (`bcma_pmu_pll_init` →
`bcma_pmu_spuravoid_pllupdate`).

This was not flagged in the original analysis because the original
analysis did not yet know we had landed PLL programming. Without the
commit bit, the new PLL values may not actually take effect.

**Suggested cheap follow-up:** add `PMU_CTL |= 0x400` after the test.193
PLL writes, observe whether `pmustatus` / `res_state` change vs the
T224 baseline.

---

## 2. Re-ranked missing writes (post-reconciliation)

Re-ranking after removing already-attempted SBMBX, PMCR_REFUP, PMU
resource-mask widen, and PLL programming from the missing list. Same
ranking criteria as original §4: (a) PMU/HT-clock related, (b)
BCM4360-specific branch, (c) early-init prerequisite.

| Rank | Write | Why it's still suspect | Cost |
|---|---|---|---|
| 1 | **`PMU_CTL` PLL_UPD (0x400)** after test.193 PLL writes | T193 programs PLL but never commits. Without latch, the new PLL values may have no effect. Cheapest of all candidates: one extra register write. | One register write next to existing T193 block. |
| 2 | **`PCIE2_CLK_CONTROL` clear DLYPERST + set DISSPROMLD** | Previously #1 in original ranking. Still untried. BCM4360-specific (rev > 3) path. Directly affects PCIe core clock gating. | One write at `BCMA_CORE_PCIE2 + 0x0`, after the existing T194 read of the same register. |
| 3 | **`PMU_CTL` NOILPONW bit (0x200)** | Previously #2. Untried. ILP-clock-during-wait state — if fw expects ILP on but it's off (or vice versa per pmurev), wait loops stall silently. | One read-modify-write on `PMU_CTL`, conditional on `pmurev == 1`. |
| 4 | **`PCIE2_LTR_STATE` ACTIVE→SLEEP handshake** | Previously #4. Untried. May not gate first-contact stage. | Two writes on `BCMA_CORE_PCIE2 + 0x1A0`. |
| 5 | **`PCIE2_PVT_REG_PM_CLK_PERIOD`** | Previously #5. Untried. PM-clock-period; if fw uses it for wait-loop timeouts an unset value could cause stalls or premature timeouts. | One indirect-config write. Requires `alp_khz` lookup. |

The original §4 entry "PMU resource-mask grant for HT clock" is removed
from this re-ranking because T221+T224 already widened both masks to
0x7ff and confirmed HAVEHT=YES. The wl.ko-derived MINRES/MAXRES values
are still unknown but are now a *refinement*, not a missing
prerequisite.

---

## 3. Required separation per Track 5.2

### 3.1 What has been tried in code

- T193: BCM4360 chipcontrol#1 |= 0x800; pllcontrol#6/#7/#0xe/#0xf
  programmed. (`chip.c:1146-1180`)
- T194: PCIe2 SBMBX = 0x1; PMCR_REFUP |= 0x1f. (`pcie.c:1146-1194`)
- T221–T224: PMU resource-mask widen — max_res_mask, min_res_mask
  driven to 0x7ff. (`chip.c:1182-1226`)
- T235: optional skip of `brcmf_chip_set_active`. (param-gated)
- T236: forced Apple random_seed write before `set_active`. (param-gated)
- T237/T238: dwell ladder out to t+30s / t+120s. (param-gated)
- T239/T240: poll TCM[ramsize-4] and tail-TCM at every dwell. (param-gated)
- T241–T246: BAR0 / MBM / BAR2 round-trip write-verify probes at
  various stages. (param-gated)
- T247: pre-place a 72-byte pcie_shared-shaped struct at TCM[0x80000]
  (version=5 at offset 0, rest=0) at pre-FORCEHT and poll it at every
  dwell. (param-gated)

### 3.2 What has been observed on hardware

- HAVEHT=YES with widened masks (T221).
- pmustatus = 0x2e, res_state = 0x7ff after T224 (matches written
  masks — masks land cleanly).
- BAR2 TCM round-trip is alive at pre-FORCEHT (T245/T246 BAR2 PASS).
- MBM `D2H_DB` bits 16..23 do NOT latch at pre-FORCEHT; FN0 bits 8,9 do
  (T246 — D2H_DB stage-gated to post-shared-init).
- Pre-FORCEHT struct write to TCM[0x80000] lands cleanly (T247
  readback exact).
- Firmware never writes any of the ~80 bytes we observe (struct region,
  ramsize-4, tail-TCM) across 23 dwells out to t+90s (T247).
- Wedge bracket for clean-probe runs: [t+120s, t+150s] (T244 n=1).
  Pre-FORCEHT-probe runs slip ~30s to ~[t+90s, t+120s] (T247 n=3 for
  the 30s slip).

### 3.3 What still lacks implementation

1. **`PMU_CTL` PLL_UPD bit** after the T193 PLL programming.
2. **`PCIE2_CLK_CONTROL`** clear DLYPERST / set DISSPROMLD.
3. **`PMU_CTL` NOILPONW bit** per pmurev.
4. **`PCIE2_LTR_STATE`** ACTIVE→SLEEP handshake.
5. **`PCIE2_PVT_REG_PM_CLK_PERIOD`** programming.
6. wl.ko-derived MINRES/MAXRES values to replace the T224 0x7ff
   empirical widen (refinement, not blocker).
7. A real `brcmf_pcie2_core_init` and `brcmf_chip_pmu_init` (the
   "implementation sketch" §5 in the original gap doc) are still
   one-off inline blocks, not factored helpers.

### 3.4 What still lacks validation (hardware)

1. Whether the existing T193 PLL writes have any effect without a
   subsequent PLL_UPD commit. (Not yet testable — PLL_UPD not
   implemented; observed PMU state is consistent with pre-T193 because
   T193 doesn't include any pre/post PMU-state diff beyond the register
   readback.)
2. Whether `PCIE2_CLK_CONTROL` gating change moves the wedge.
3. Whether `NOILPONW` change moves the wedge.
4. Whether T247-style shared-struct publication with a different
   signature/version moves the wedge (Test.249 sweep, deferred per
   PRE-TEST.248 matrix).

---

## 4. How this changes the PMU/PCIe path priority

Original §4 implied PCIe2 core init was the highest-leverage missing
piece. Reconciliation changes this:

- **Highest leverage now:** PLL_UPD commit. One register write, low
  risk, directly tests whether the existing T193 PLL programming is
  load-bearing or inert.
- **Second:** `PCIE2_CLK_CONTROL` write. Same priority as the original
  §4 #1. Bounded risk (one register).
- **Third:** depends on T248/T249 outcome:
  - If T248 wide-TCM scan is null AND T249 signature sweep is null,
    NOILPONW + LTR + PM_CLK_PERIOD become the next batch.
  - If T249 produces TCM activity for some signature, PMU/PCIe
    refinement deprioritizes vs decoding what fw is publishing.

---

## 5. Concrete consequences for `pmu_pcie_gap_analysis_final.md`

The original document should be read with the following annotations:

- §1.4 "PMU Resources Init" — still accurate that bcma supplies no
  BCM4360 mask; supplemented by T224's empirical 0x7ff widen.
- §1.6 "PCIe2 Core Init" table — SBMBX and PMCR_REFUP rows are now
  done. CLK_CONTROL, LTR, LTR_STATE, PM_CLK_PERIOD remain.
- §2.2 "PCIe Attach" — claim that `brcmf_pcie_attach` "returns early
  without any PCIe2 core initialization" is now misleading. The early
  return is still there for BCM4360 but now happens **after** the T194
  SBMBX + PMCR_REFUP writes. Other PCIe2 init writes are still missing.
- §3 "Gap Table" — SBMBX and PMCR_REFUP rows should be marked Done.
- §4 "Top 5 Ranked Missing Writes" — superseded by the re-ranking in
  §2 of this reconciliation note.
- §5 "Implementation Sketch" — partially realized as inline blocks in
  T193 / T194 / T224, not as the proposed `brcmf_pcie2_core_init` and
  `brcmf_chip_pmu_init` helpers. Refactor into helpers is desirable
  but not load-bearing.
- §6 "Next Steps" — outdated. The actual next steps are gated by
  T248 (wide-TCM scan) and T249 (signature sweep) outcomes, with the
  PLL_UPD commit a cheap discriminator that can run in parallel with
  either.

---

## 6. Assumptions and caveats

- This reconciliation reads only `pcie.c` and `chip.c` in
  `phase5/work/.../brcmfmac/` as of HEAD on
  `claude/phase6-test248-work-jhLyY`.
- "Already done" means the code path executes when the BCM4360
  attach path runs; it does not certify the writes had the intended
  hardware effect. Hardware-effect questions are deferred to §3.4.
- T193's PLL values (0x080004e2, 0x0e) come from
  `wl_pmu_res_init_analysis.md §6.2` and are wl.ko-derived. They are
  not validated against a known-good Apple boot trace.
- T224's 0x7ff was selected because T223 with mask=0xffffffff converged
  to res_state=0x7ff. It is not a wl.ko-derived MINRES/MAXRES.
