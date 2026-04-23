# Instrumentation Audit: pcie.c (Test 248 Regression Analysis)

**File:** `/home/user/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` (6290 lines)
**Scope:** 58 references to `bcm4360_test*`; 248 test iterations; wedge onset: t+90–120s (no TCM writes observed)

---

## Reviewer corrections (added 2026-04-23 post-audit)

The audit below is preserved as written by the analysis agent so its
methodology and detail can be reused. The following framing errors
should be read alongside it before acting on any "CRITICAL" / "HIGH"
recommendation.

### C1. The "test.188 block" is the BCM4360 attach path, not standalone instrumentation

Section 3's "🔴 CRITICAL" framing of lines 2260–3509 as a "MASSIVE code
redirect" with proposed remediation `bcm4360_test188_enable=0` is
incorrect. Specifically:

- Upstream brcmfmac does not bring BCM4360 up at all on this Apple
  variant — the chip ID gating in `brcmf_pcie_attach` and the absence
  of a `brcmf_chip_set_active` continuation for it are why this project
  exists.
- The block at 2260–3509 is the **BCM4360 download + set_active path
  itself**. It contains the chunked fw write, NVRAM write, FORCEHT,
  pci_set_master, and `brcmf_chip_set_active(...)` call.
- The `return -ENODEV` at line 3509 is the **intentional clean exit**
  after the BCM4360-specific path runs in test-harness mode (no
  `brcmf_bus_start`, no netdev). It is not a "skip normal attach";
  there is no upstream "normal attach" for this device.
- A `bcm4360_test188_enable=0` flag would not isolate a regression —
  it would skip the entire BCM4360 attach. The expected outcome would
  be "no wedge, no boot, nothing happens." That is not a useful
  experiment.

### C2. Real signal worth keeping from the audit

Inside the BCM4360 attach path, the audit *does* surface valid concerns
that align with prior post-test observations:

- **Dwell-ladder probes do real MMIO** (T239 sharedram poll, T240 wide
  poll, T241–T246 write-verify). PRE-TEST.246 already noted "pre-FORCEHT
  probe costs ~30s of fw runtime" (n=3 by T247). The audit's MEDIUM
  finding that 1250 lines of dwell + write-verify create timing
  pressure is consistent with that observation.
- **Test.236 forced-seed write** is acknowledged in PRE-TEST.246 as
  reordering vs upstream. The audit's HIGH finding here is correct that
  it changes boot sequence; the question of whether that helps or
  hinders is what the param-gated A/B is for.
- **T194 SBMBX + PMCR_REFUP writes** — the audit's LOW assessment of
  these as "isolated, intentional" is correct. See
  `phase6/pmu_pcie_gap_analysis_reconciliation.md` for status.

### C3. Genuine open audit questions (re-prioritized)

Things from the audit that are *worth* hardware verification:

1. **Per-dwell write-verify is timing-sensitive.** T245+T246
   demonstrated this: each pre-FORCEHT probe block costs ~30s of fw
   runtime regardless of probe size. The audit recommends "add master
   dwell-enable param" — already implemented as the `test238`/`test239`
   /`test240`/etc. params (all default 0).
2. **FORCEHT placement (T219).** Currently runs unconditionally inside
   the BCM4360 path, before `set_active`. Valid question whether
   moving it later (or removing it) changes anything. Hardware test.
3. **Mid-attach `mdelay` calls** (50ms chunks during fw write, 30ms
   pre-set_active). Plausibly load-bearing; plausibly could be reduced
   or removed. Hardware test required to know.

### C4. What the audit does NOT establish

- It does not establish that the wedge is caused by our edits. The
  null-result evidence from T247 (fw never touches any of ~80 bytes
  across 23 dwells over 90s) is *consistent* with a fw-side stall
  that has nothing to do with our instrumentation timing.
- The proposed "test188=0 to isolate regression" experiment would not
  distinguish "regression in our code" from "fw can't run without our
  attach path" — both produce "no boot, no wedge".

### C5. Recommended next experiments from this audit (not from §3)

From the audit's signal that *is* useful:

1. After T248 wide-TCM scan (already planned): if W1 (null), one
   targeted hardware test could be "T247 path with `test239=0
   test240=0 test238=0`" (no per-dwell polling at all) to isolate
   whether the wedge timing changes when no per-dwell MMIO happens.
   Cheap discriminator.
2. After T249 signature sweep (deferred): if all-null, then revisit the
   FORCEHT-placement question and whether the mid-attach `mdelay`
   calls have observable effect on wedge bracket.

The audit below is otherwise a reasonable inventory of the
instrumentation surface; treat its severity labels as advisory rather
than load-bearing.

---

## Section 1: Safe Scaffolding (No Behavioral Risk)

### Pure Logging
All `pr_emerg` breadcrumbs are read-only. Examples:
- **Lines 1150, 1197–1208:** test.128 attach entry/exit markers (no-op for non-4360)
- **Lines 2367–2456, 2478–2556:** test.188 pre-release probes; all `brcmf_pcie_read_*` only
- **Lines 2686, 2751, 2800, 2840:** test.241–247 probe logging; restore operations restore state
- **Lines 3076–3213:** test.238/237/234 dwell logging in gated block

### Module Parameters (Default 0, All Gated)
Lines 89–259 declare 10 module params with default-off gating:
```
bcm4360_test235_skip_set_active          = 0  (line 89)
bcm4360_test236_force_seed               = 0  (line 102)
bcm4360_test237_extended_dwells          = 0  (line 115)
bcm4360_test238_ultra_dwells             = 0  (line 127)
bcm4360_test239_poll_sharedram           = 0  (line 139)
bcm4360_test240_ring_h2d_db1             = 0  (line 153)
bcm4360_test240_wide_poll                = 0  (line 164)
bcm4360_test241_writeverify              = 0  (line 178)
bcm4360_test242_writeverify_postactive   = 0  (line 192)
bcm4360_test243_writeverify_v2           = 0  (line 212)
bcm4360_test245_writeverify_preforcehttp = 0  (line 224)
bcm4360_test246_writeverify_legal        = 0  (line 243)
bcm4360_test247_preplace_shared          = 0  (line 257)
```

---

## Section 2: Intended Behavioral Changes (Permanent, By Design)

### Test.194: BCM4360 SBMBX/PMCR_REFUP Initialization (Attach Entry)
**Lines 1160–1193:** Unconditional on-4360 init sequence
```c
if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
    // Probe PCIe2 CLK_CONTROL (line 1164)
    // Write SBMBX=0x1 @ 0x098 (lines 1174–1177)
    // Write PMCR_REFUP |= 0x1f @ 0x1814 (lines 1181–1189)
    return;  // Early exit on 4360 (line 1193)
}
```
**Rationale:** BCM4360 PMU bring-up. Upstream brcmfmac skips this due to chiprev=3/pcie2_rev=1 gating; this is a **permanent** fix for 4360, intentional.  
**Risk:** LOW — isolated, probed before writes, early-return prevents downstream duplication.

### Test.161: BCM4360 rmmod Short-Circuit (Cleanup Path)
**Lines 6057–6078:** State-gated cleanup in `brcmf_pcie_remove()`
```c
if (pdev->device == BRCM_PCIE_4360_DEVICE_ID && devinfo->state != UP) {
    pr_emerg("test.161: remove() short-circuit — state=%d != UP\n", devinfo->state);
    msleep(300);
    [skip MMIO-touching cleanup]
    return;
}
```
**Rationale:** When firmware boot fails (state != UP), MMIO accesses hang. Intentional bypass.  
**Risk:** LOW — guards against CTO; only runs when attach didn't complete.

### Test.64 Comment: NVRAM Marker Preservation
**Lines 3587–3595:** Preserved comment documenting why `ramsize-4` is never zeroed.
**Risk:** NONE — commentary only; reflects upstream protocol (NVRAM marker → sharedram handshake).

---

## Section 3: SUSPICIOUS Changes (Potential Regressions)

### 🔴 CRITICAL: Test.188 Early-Return Block (Firmware Download Redirection)
**File:Line Range:** 2260–3509  
**Impact:** MASSIVE code redirect on all BCM4360 probes

**What it does:**
- Lines 2260–2261: Conditionally gates entire firmware download/test path (`if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)`)
- Lines 2276–2403: **Halts ARM, writes firmware in chunked 4KB blocks** (test.167, test.225)
- Lines 2424–2556: **Writes NVRAM in chunks with 50ms delays** (test.188)
- Lines 2468–2498: **Forces random_seed write** (test.236, see below)
- Lines 2640–2880: **Enables pci_set_master, sets FORCEHT** (test.226, test.219)
- Lines 2894–3470: **Mega-dwell block**: optional zeros TCM[0x9FE00..0x9FF1C], calls set_active, then multi-tier post-set_active probes (test.234–243)
- **Line 3509:** **Early return -ENODEV** (aborts normal attach completely)

**Test Added For:** test.167–test.248 series (firmware stability & wedge diagnosis)

**Why Suspicious:**

1. **Timing Cascade:** Every step has explicit delays (msleep, mdelay, 50ms chunks)
   - Line 2418: `msleep(100)` post-fw
   - Line 2442: `mdelay(50)` every 1024 words in NVRAM
   - Line 2597: `msleep(5)` before INTERNAL_MEM lookup
   - Line 2681: `msleep(5)` before pci_set_master
   - Line 2851: `msleep(5)` before FORCEHT block
   - Line 2879: `msleep(5)` before set_active call
   - Line 2888: `mdelay(30)` immediately before set_active
   - Tiers (lines 3084–3470): 12×250ms + 100ms spreads = ~3500ms
   
   **Concern:** These delays may mask or compound a race condition. Removing them could change wedge timing or suppress it entirely. **Default behavior is fundamentally altered.**

2. **Register State Changes Before set_active:**
   - Lines 2680–2697: pci_set_master moved **earlier** than in normal path (test.226)
   - Lines 2854–2878: FORCEHT write placed **here** (test.219)
   - Lines 2732–2849: Three MBM + TCM write-verify blocks run (test.245, test.246, test.247)
   
   Normal upstream path: pci_set_master & FORCEHT run **much later** (after fw download). Test.188 does them **before set_active call**. **Ordering changed.**

3. **TCM Writes Overlap Risk:**
   - Line 2827–2849: test.247 pre-places 72B struct at TCM[0x80000], version=5
   - Line 2911–2935: test.234 zeros TCM[0x9FE00..0x9FF1C] (if `!bcm4360_test236_force_seed`)
   - **0x80000 is where our test.247 struct sits.** If test.234 scans and zeros that region later, struct corrupts. The guard on line 2894 (`if (!bcm4360_test236_force_seed)`) tries to prevent overlap, but if someone runs test247=1 AND test236=1, then test234 zeros don't run, yet later probes still try to poll the struct. **Gating logic is fragile.**

4. **Conditional Versus Always-On Danger:**
   - The entire block 2260–3509 **is** gated on `devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID` (line 2260)
   - But inside, further conditionals (test235–247 module params) control probes and dwell timing
   - **If ANY test param defaults to 1, or if test.188 itself has no explicit test param, it runs on EVERY probe.**
   
   Looking at lines 2260–3509, there is **NO explicit module_param gate for test.188 itself.** It is enabled by default **purely on chip ID.** Lines 1–88 show no `bcm4360_test188_*` param declared.
   
   **This means test.188 (entire 1250-line block) runs UNCONDITIONALLY on BCM4360, bypassing normal attach entirely.**

5. **Firmware Stack Consumption:**
   - Heap allocations at lines 2336–2349 (fw_sample, pre_fine): 66 KB total
   - Stack variables at lines 2282–2318: ~180 B
   - **Every alloc failure is non-fatal (lines 2338–2343, 2348), but if successful, we carry large buffers through 3500ms of dwells, then free them at line 3505–3507.**
   - **Could this memory pressure change GFP behavior and mask/reveal a firmware race?**

6. **Early Return Skips Normal Boot:**
   - Line 3509: `return -ENODEV;` in the test.188 path means firmware **never progresses to normal attach**
   - No `brcmf_bus_add_txctl_pktq()`, no `brcmf_bus_start()`, no firmware actually runs
   - **We are running a dead-attach test, not a real boot.** The wedge we observe is **firmware attempting to initialize during our probes, not during normal operation.**

**Proposed Remediation:** HIGH priority
- Add explicit `bcm4360_test188_enable` module param (default 0) to gate the entire 2260–3509 block
- Remove all unconditional mdelay/msleep calls from critical path (lines 2681–2888 pci_set_master/FORCEHT region)
- Separate test.247 pre-place struct from test.234 zero range: ensure they don't overlap (0x80000 vs 0x9FE00)
- **Test:** Boot with test.188=0 and verify no wedge at t+120s; if wedge still occurs, it's firmware; if gone, test.188 instrumentation is the regression

---

### 🟠 HIGH: Test.236 Forced random_seed Write (Embedded in Normal Path)
**File:Line Range:** 2468–2498  
**When Runs:** Only inside test.188 block (line 2468: `if (bcm4360_test236_force_seed)`)

**What it does:**
```c
if (bcm4360_test236_force_seed) {
    // Write 256B random data + footer at ramsize-8 (lines 2481–2487)
    // Verify footer magic (lines 2490–2497)
}
```

**Test Added For:** test.236 (seed-present comparison run)

**Why Suspicious:**

1. **Gated BUT Embedded in test.188:**
   - The conditional is gated on `bcm4360_test236_force_seed=1` (default 0)
   - But it runs **only inside the test.188 block** (line 2468 indentation)
   - **If test.188=1 (implicit default for 4360) and test236=1, seed is force-written early**
   - Upstream only writes seed **if `devinfo->otp.valid`** and **in post-set_active dead-path** (lines 3563–3581)
   - **Test.236 writes it BEFORE set_active.** This reorders the boot sequence and may explain T.236 observation: "seed SHIFTS the wedge later — fw reaches ≥t+700ms post-set_active" (test.236 notes)

2. **Memory Overlap with NVRAM:**
   - Line 2474: footer at `address - sizeof(footer)` = `(ramsize - nvram_len) - 8`
   - Line 2475: random bytes at `footer_addr - rand_len` = `(ramsize - nvram_len) - 8 - 256`
   - NVRAM typically 4–8 KB at `ramsize - nvram_len`
   - **Seed buffer sits just **below** NVRAM. If NVRAM parsing or firmware writes touch that region, seed buffer is trashed. Or vice versa.**

3. **No Fallback:**
   - Line 2486: `brcmf_pcie_provide_random_bytes()` silently succeeds
   - No gating on `devinfo->otp.valid` (unlike upstream line 3563)
   - **Firmware may not expect seed present before set_active; forcing it early could confuse initialization.**

**Proposed Remediation:** MEDIUM priority
- Move seed write **outside the test.188 block entirely**, to match upstream timing (post-set_active dead-path, lines 3563–3581)
- OR add explicit check: `if (bcm4360_test236_force_seed && !devinfo->otp.valid) { ... }` to match upstream gating
- **Test:** Boot with test236=1 and measure wedge-onset time vs baseline; if shifts or prevents wedge, seed write is interfering with firmware init

---

### 🟠 HIGH: Test.234 TCM Zero Block (Conditional but Overlaps Struct Zone)
**File:Line Range:** 2894–2948  
**When Runs:** Inside test.188 block; **only if `!bcm4360_test236_force_seed`** (line 2894)

**What it does:**
```c
if (!bcm4360_test236_force_seed) {
    // Zero TCM[0x9FE00..0x9FF1C) — 71 dwords (lines 2915–2946)
    // Hypothesis: FW reads a value there and uses as DMA target
}
```

**Test Added For:** test.234 (shared-memory-struct probe)

**Why Suspicious:**

1. **Gating Fragility:**
   - Zeros only if **test236=0 (seed NOT forced)**
   - Reason: seed footer lives just below NVRAM, zero range overlaps it (lines 2890–2892 comment)
   - But **test247 pre-places struct at 0x80000** (line 2827), which is **above** the zero range (0x9FE00)
   - **No explicit gating between test234 and test247; both can run independently**
   - If test247=1 and test234=1, struct at 0x80000 is not affected; **no actual overlap**
   - But if future tests add writes in 0x9FE00..0x9FF1C, test234's zeros could trash them. **Fragile layout assumption.**

2. **Timing Before set_active:**
   - Zeros run **immediately before set_active call** (line 2950)
   - Firmware expects a value in this region; zeroing it is **a deliberate behavioral change**
   - If FW reads 0 and NULL-DMA instead of dereferencing a bogus pointer, behavior changes
   - **Upside: might prevent wedge if FW crashes on bad pointer. Downside: FW might interpret 0 as "no DMA" and skip initialization, hanging later**

3. **No Verification:**
   - Lines 2936–2945: Post-zero verification reads region back and logs non-zeros
   - But **no subsequent check** that firmware saw the zeros or behaved differently
   - Just logs the state and proceeds to set_active

**Proposed Remediation:** MEDIUM priority
- Add explicit documentation of the TCM layout: which test uses which region, and what the safe exclusion zones are (lines 2890–2912 comment is good, but doesn't cover test247)
- Consider adding a **gating param** `bcm4360_test234_zero` (currently implicit in the `!test236` conditional) to decouple from test236
- **Test:** Boot with test234=1, test236=0, test247=0 (isolate test234); measure if zero-delay changes wedge; if yes, test234 is interfering

---

### 🟡 MEDIUM: pci_set_master Moved Earlier (Sequencing Change)
**File:Line Range:** 2680–2697 (test.188 block)  
**Upstream Normal:** Would run much later in brcmf_pcie_exit_download_state or during normal attach

**What it does:**
```c
pr_emerg("BCM4360 test.226: before pci_set_master\n");
msleep(5);
pci_set_master(devinfo->pdev);
pr_emerg("BCM4360 test.226: after pci_set_master\n");
msleep(5);
```

**Test Added For:** test.226 (BusMaster enable sequencing); test.233 (restore for TCM persistence probe)

**Why Suspicious:**

1. **Timing:** Happens **300ms+ after firmware load** (line 2418 post-fw msleep + chunked writes + NVRAM) and **before set_active** (line 2886)
   - Upstream: pci_set_master happens **during normal attach** (after set_active succeeds)
   - **Early enable could allow firmware DMA to start before our probes expect it**

2. **Dwell Assumption:**
   - Test.233 comment (lines 2671–2678) says test.233 wanted to restore "proven-safe probe path" (test.230, where BM=on)
   - But test.230 itself was a **probe of whether set_active is sole wedge trigger** (not a baseline for normal operation)
   - **Confusing: we're using a test-harness baseline, not the upstream baseline**

3. **msleep(5) Before/After:**
   - Lines 2681, 2684: Two `msleep(5)` calls surround the actual `pci_set_master()` call
   - **No clear reason why 5ms delays help; could be masking a race**
   - If race is "FW reads BAR2 before BM is enabled," delays mask it

**Proposed Remediation:** MEDIUM priority
- Remove the early pci_set_master from test.188 block (lines 2680–2697)
- Move back to downstream, after set_active call (in normal path, line ~3515)
- **Test:** Boot with and without the early pci_set_master; if wedge timing changes, sequencing matters

---

### 🟡 MEDIUM: FORCEHT Write Placed in test.188 Block (Sequencing Change)
**File:Line Range:** 2851–2878  
**Upstream Normal:** FORCEHT write would happen at a different point (likely during set_active call or earlier in normal attach)

**What it does:**
```c
pr_emerg("BCM4360 test.226: past BusMaster dance — entering FORCEHT block\n");
brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
WRITECC32(devinfo, clk_ctl_st, ccs_pre | BIT(1));  // Set FORCEHT (bit 1)
udelay(50);
ccs_post = READCC32(devinfo, clk_ctl_st);
pr_emerg("BCM4360 test.219: FORCEHT write CC clk_ctl_st pre=0x%08x post=0x%08x ...\n", ...);
```

**Test Added For:** test.219 (HT clock forcing); test.226 integration

**Why Suspicious:**

1. **Placement:** 
   - Runs **immediately before set_active call** (line 2886: `brcmf_chip_set_active(..., resetintr)`)
   - Upstream: If FORCEHT write happens at all, likely happens **outside of this attach probe, during normal init**, not in firmware download
   - **test.219 hypothesis** (lines 2854–2859): HAVEHT stuck CLEAR; set FORCEHT to force HT clock up. But does FW expect to see FORCEHT **pre-set-active** or **post-set-active**?

2. **udelay(50) Assumption:**
   - Line 2871: One `udelay(50)` between WRITECC32 and READCC32
   - **Is this delay necessary? Is PMU clocking up?** No comment explaining why
   - **Could timing-sensitive; removing delay might change outcome**

3. **No Verification of Effect:**
   - READCC32 at line 2872 logs the result but doesn't **verify HAVEHT came up**
   - Test.219 comment (line 2873) just logs presence of HAVEHT, doesn't assert it
   - **Unknown if FORCEHT actually fixes the HAVEHT stuck CLEAR issue, or if we're just logging it**

**Proposed Remediation:** MEDIUM priority
- Add a **gating param** `bcm4360_test219_forceht` (default 0) to decouple FORCEHT from test.226/test.188
- Validate that HAVEHT comes up after FORCEHT write: add assert or early-return if HAVEHT still stuck
- **Test:** Boot with test219=0 (skip FORCEHT) and test219=1; measure wedge timing; if different, FORCEHT is a variable

---

### 🟡 MEDIUM: Dwell Ladder & Tier Probes (Timing Sensitivity)
**File:Line Range:** 2950–3470  
**Code:** 1250+ lines of dwell ladders (test.235–243, extended/ultra variants)

**What it does:** Post-set_active probes in multiple tiers, from t+100ms to t+120s, with breadcrumbs and optional MMIO write-verify

**Why Suspicious:**

1. **Giant Timing-Sensitive Block:**
   - test.237: extended dwell to t+30s (lines 3170–3470, ~300 lines)
   - test.238: ultra dwell to t+120s (lines 2954–3083, ~130 lines)
   - **Between set_active call (line 3079) and end of probes (line 3470), firmware is running and we're sampling every 100–300ms**
   - **If any probe MMIO touches a register that firmware is also touching, we could cause a CTO or race condition**

2. **No Exit on Failure:**
   - Lines 3078–3082: Call set_active, log result (TRUE/FALSE)
   - **But continue probing regardless of success**
   - If set_active fails (returns FALSE), we still dwell for 3000–120000ms watching a dead firmware
   - **Wedge-hang at t+90-120s could be from us polling a firmware that already died, not from firmware itself**

3. **Write-Verify Macros Run in Dwell:**
   - Lines 3008–3024 (`BCM4360_T242_WRITEVERIFY`): write 0xDEADBEEF to MAILBOXMASK, read back, clear
   - Lines 3033–3074 (`BCM4360_T243_WRITEVERIFY`): select PCIE2, write/read MAILBOXMASK and BAR2 TCM[0x90000]
   - **These run at every dwell point (t+100ms, t+300ms, ... t+3000ms) IF the corresponding test param is ON**
   - If `test242=1` or `test243=1`, we're doing **register writes every 100–300ms for 3 seconds**
   - **Could this disturb firmware's own register access and cause the hang?**

4. **Dwell-Poll of TCM[ramsize-4] and TCM[0x80000]:**
   - Lines 2961–2998 macro `BCM4360_T239_POLL`: reads TCM[ramsize-4] (sharedram pointer) and optionally TCM[0x80000] (test.247 struct)
   - **Firmware is supposed to write sharedram_ptr at ramsize-4 during boot. We're polling it every dwell.**
   - **If polling happens to read at the exact moment firmware is writing, we could see a torn read or cause the write to fail**

**Proposed Remediation:** MEDIUM priority
- Add a **master dwell-enable param** `bcm4360_test_dwells` (default 0) to gate the entire dwell block (lines 2950–3470)
- Add early-exit: if `!brcmf_chip_set_active(...)` returned FALSE, skip dwell ladders and go straight to cleanup (line 3489)
- Separate write-verify probes into their own param guards: don't run them at every dwell, only at first dwell or under explicit request
- **Test:** Boot with dwells=0 (skip all post-set_active probes); if wedge is gone, probes are the problem

---

### 🟡 MEDIUM: Test.161 msleep(300) in rmmod Short-Circuit
**File:Line Range:** 6061  

**What it does:** Explicit 300ms delay before cleanup when firmware didn't boot
```c
if (pdev->device == BRCM_PCIE_4360_DEVICE_ID && devinfo->state != UP) {
    pr_emerg("BCM4360 test.161: remove() short-circuit — state=%d != UP\n", devinfo->state);
    msleep(300);  // <-- Why?
    [cleanup]
}
```

**Why Suspicious:** No comment explaining why 300ms is needed. Could be masking a race; could be accidental copy-paste from test.188 dwelling.

**Proposed Remediation:** LOW priority (not in attach path)
- Remove or document: add comment explaining if this delay is necessary or if it's diagnostic only
- **Test:** rmmod with and without delay; measure exit time

---

## Summary Table: Changes Requiring Action

| Test | Lines | Severity | Issue | Remediation |
|------|-------|----------|-------|-------------|
| T.188 | 2260–3509 | 🔴 CRITICAL | Early-return w/ mega-dwell, no gating param, timing cascade | Add `test188_enable=0` param; remove mdelay calls; test with =0 |
| T.226 | 2680–2697 | 🟡 MEDIUM | pci_set_master moved early, sequencing changed | Remove early call; restore to upstream order |
| T.219 | 2851–2878 | 🟡 MEDIUM | FORCEHT write in probe path, no effect validation | Add `test219_forceht=0` param; verify HAVEHT comes up |
| T.234 | 2894–2948 | 🟡 MEDIUM | TCM zero at fragile offset, no param gating | Add explicit `test234_zero=0` param; document layout |
| T.236 | 2468–2498 | 🟠 HIGH | Forced seed write before set_active, reorders boot | Move to post-set_active dead-path; gate on `otp.valid` |
| T.235–247 | Various | 🟢 LOW | Per-dwell probe macros | All gated; safe if params stay =0 |
| T.161 | 6061 | 🟡 MEDIUM | Unexplained msleep(300) in rmmod | Document or remove |
| Dwells | 2950–3470 | 🟡 MEDIUM | 3000–120000ms of polling & write-verify, timing-sensitive | Add master dwell param; exit early if set_active fails |

---

## Priority Action Plan

1. **IMMEDIATE (before next hardware test):**
   - Add `bcm4360_test188_enable` module param (default 0)
   - With test188=0, normal attach path should resume; measure if wedge is gone
   - If gone: test.188 instrumentation is the regression
   - If persists: wedge is firmware, not our edits

2. **IF test188=0 FIXES wedge:**
   - Isolate which sub-test inside test.188 causes the hang (T.226 pci_set_master? T.219 FORCEHT? Dwell ladder?)
   - Remove non-critical delays (msleep/mdelay) from attach path
   - Restore sequencing to match upstream

3. **IF test188=0 DOES NOT FIX wedge:**
   - Problem is firmware or permanent bring-up changes (T.194 SBMBX/PMCR_REFUP)
   - Keep test.188 isolated behind param; focus on PMU/TCM access patterns

---

**Document Version:** Initial audit for test.248  
**Assessment:** ~1250 lines of test.188 + derivatives are the primary regression risk; everything else is either safe scaffolding or secondary to test.188
