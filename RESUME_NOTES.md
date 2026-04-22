# BCM4360 RE — Resume Notes (auto-updated before each test)

## POST-TEST.196 (2026-04-22) — BREAKTHROUGH: bit 6 alone is safe AND firmware finally writes TCM (first ever observation)

Logs: `phase5/logs/test.196.journalctl.txt` (885 brcmfmac lines) +
`test.196.journalctl.full.txt` (920 lines).

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ — system survived test cleanly, module rmmod'd normally |
| `res_state` 0x13b → 0x17b (bit 6 asserted, bit 7 NOT asserted) | ✓ |
| **First ever firmware-originated TCM writes detected** | ✓ |
| `fw-sample` 256-region scan post-dwell | 256 UNCHANGED — firmware code intact, no overwrite |
| `wide-TCM` post-dwell | **2 of 40 regions CHANGED** — firmware wrote scratch |

Specific writes found by post-dwell wide-TCM scan:

```
post-dwell wide-TCM[0x98000]=0x00000000 (was 0x15f3b94d) CHANGED
post-dwell wide-TCM[0x9c000]=0x5354414b (was 0xf39d6dd9) CHANGED
```

`0x9c000` is in the upper TCM (~624 KB from base, near the end of the
640 KB TCM). `0x5354414b` decodes as ASCII "KATS" little-endian / "STAK"
big-endian — looks like part of a firmware initialisation marker
(possibly "STACK" or a stack canary fill pattern). `0x98000` zeroed out.
**This is the first objective evidence in this project that firmware is
executing and writing data on this chip.**

### Bit 6 vs bit 7 decoded

| Signal | test.194 (max=0x13f) | test.195 (max=0x1ff, both 6+7) | test.196 (max=0x17f, bit 6 only) |
|---|---|---|---|
| `res_state` | 0x13b | 0x1fb | **0x17b** |
| `clk_ctl_st` pre-release | 0x00050040 | 0x01070040 | **0x00010040** |
| `clk_ctl_st` post-dwell | 0x00050040 | (crashed) | **0x00050040** (bit 0x40000 set during dwell) |
| `pmustatus` | 0x2a | 0x2e | 0x2a |
| `pmucontrol` post-dwell | 0x01770381 | 0x01770381 | 0x01770381 (NOILPONW set by fw within 250 ms) |
| Crash? | no | YES (mid-dwell freeze) | **no** |
| Firmware TCM writes? | 0 | unknown (crashed before scan) | **2** |

Bit 6 alone is the HT clock the firmware needs to execute. Bit 7 enables
something else (sets `clk_ctl_st` bits 0x10000+0x1000000 even before
`set_active` runs — confirmed by pre-release snapshot delta) and is the
destabiliser. Adding bit 7 to bit 6 simultaneously is what crashed
test.195.

### Firmware progress timeline (from per-tick CC backplane sample)

- t=0 (pre-release): `pmucontrol=0x01770181`, `clk_ctl_st=0x00010040`
- t=250 ms: `pmucontrol=0x01770381` (NOILPONW set), `clk_ctl_st=0x00050040`
  → firmware completed early `si_pmu_init` within first 250 ms
- t=500 ms through t=3000 ms: all CC regs stable (no further changes)
  → firmware then sits idle (or in a polling loop with no register-visible side effects)
- post-dwell: 2 wide-TCM cells found CHANGED
- D11 `RESET_CTL` stayed 0x1 throughout — firmware did NOT advance to D11 bring-up

### What this tells us

1. **Direction is fully validated.** Bit 6 of max_res_mask is THE gate.
   Firmware was waiting for HT clock; once we permit it, firmware runs
   and starts initializing.
2. **Bit 7 is dangerous and unnecessary** for the basic firmware unblock.
   We can leave it gated off for now.
3. **Firmware progress stops short of D11 bring-up.** It runs, completes
   PMU init, writes a small amount of scratch, then stalls. Likely waiting
   on something else: probably NVRAM (we currently don't fully program
   NVRAM), a host doorbell signal, or a second clock-domain enable.
4. **The slim dwell harness is a good baseline** for further bring-up
   work — it's safe even with HT clock active and gives clean per-tick
   PMU evolution data.

### Suggested next moves (priority order)

1. **Probe deeper into wide-TCM** — current scan only samples every 16 KB.
   Add a finer scan around `0x98000`–`0x9c000` to find the full extent
   of the firmware-written region. Possibly contains a fw-init structure
   we can decode to learn what state firmware reached.
2. **Test bit 7 alone** (`max_res_mask=0x1bf`) — formally confirm bit 7
   is the destabiliser independent of bit 6 (control test). Even with
   the slim harness, expect a crash; but we'll know.
3. **NVRAM revisit** — firmware in early init typically reads NVRAM for
   board-specific config (PHY calibration tables etc). If our NVRAM
   write is incomplete, fw could be sitting in a "wait for NVRAM ready"
   loop. Worth re-checking what we actually upload vs what wl.ko does.
4. **Forcing bit 6 via min_res_mask** — currently bit 6 is asserted only
   because we permitted it; the chip might cycle it. Setting
   `min_res_mask=0x17b` would FORCE bit 6 to stay on and could help fw
   make further progress.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| Bit 6 + bit 7 simultaneous activation is safe | 195 | falsified — chip freezes |
| Bit 6 alone destabilises the chip | **196** | **falsified** — bit 6 alone is safe |
| Heavy MMIO during dwell is universally safe | 195 | falsified |
| Slim dwell harness can't detect fw writes | **196** | **falsified** — caught both |

---

## PRE-TEST.196 (2026-04-22) — bisect res 6 vs 7 (try bit 6 only, max_res_mask=0x17f) + drastically reduce dwell-time MMIO

### Hypothesis

Test.195 proved widening `max_res_mask` activates resources 6 and 7 (first
ever res_state movement on this chip), but the simultaneous activation
combined with the heavy TCM-poll harness caused an unrecoverable freeze
~half-way through the 3000 ms dwell. Two unknowns to separate:

1. Which resource (6 or 7) destabilised the chip when its clock domain came
   live? Bit 6 only (`max_res_mask=0x17f`) lets us test bit 6 in isolation.
2. Is the freeze caused by the resources themselves, or by the MMIO storm
   the dwell-poll harness produces under a live HT clock? A drastically
   slimmer harness (no fw-sample / wide-TCM / tail-TCM scans during dwell)
   eliminates the harness as a confound — if the chip still freezes with
   bit 6 only and a slim harness, the resource is the gun.

### Implementation

**chip.c** — single-line change:
- `max_res_mask` write changes from `0x1ff` → `0x17f` (drop bit 7)
- Marker line updated: `BCM4360 test.196: max_res_mask 0x... -> 0x... (write 0x17f — bisect: bit 6 only)`

**pcie.c** — slim the dwell harness:
- Dwell stays 3000 ms total but is now split into 12 × 250 ms ticks.
- Each tick does ONLY: ARM/D11 wrapper probes (single MMIO each),
  TCM[0..0x1c] head scan (8 cheap reads), and the existing CC backplane
  sample (8 CC-only reads incl res_state, min_res_mask, max_res_mask,
  pmustatus, clk_ctl_st, pmucontrol, pmutimer, pmuwatchdog).
- The crashy heavy-MMIO loops (wide-TCM 40-read scan, tail-TCM 16-read
  scan, full fw-sample 256-read scan) are REMOVED from per-tick dwell.
- A SINGLE end-of-dwell summary scan runs after all ticks: full
  fw-sample (256 reads) reduced to a 3-bucket count (UNCHANGED /
  REVERTED / CHANGED) plus wide-TCM scan that only logs CHANGED entries.

### Expected outcomes

| Observation | Interpretation | Next |
|---|---|---|
| `max_res_mask 0x13f -> 0x17f` AND `res_state` advances to 0x17b (bit 6 only) | bit 6 alone activates cleanly; chip survives the dwell | follow up with bit 7 alone (`max_res_mask=0x1bf`) and confirm which destabilises |
| `res_state 0x17b` AND fw-sample summary shows CHANGED count > 0 | firmware finally writing TCM with HT clock alone | analyse what changed; pivot to per-region tracking |
| `res_state 0x17b` AND fw-sample all UNCHANGED, no crash | bit 6 unblocks resources but firmware still stalls; need more (min_res_mask widen, NVRAM, OTP) | widen min_res_mask to 0x17b in test.197 |
| Hard crash again with bit 6 alone and slim harness | bit 6 itself destabilises the chip independent of MMIO load | bit 7 alone next (`0x1bf`); if both crash, problem is the resources colliding with our PCIe state |
| `res_state` does NOT change to 0x17b | something else changed; investigate (or harness regression) | re-read code path |

### Build + pre-test

- chip.c, pcie.c edited; module built clean (one pre-existing unused-function
  warning unrelated to this change).
- PCIe state (verified post crash + SMC reset, current boot 0):
  - `MAbort-`, `CommClk+`, `LnkSta` Speed 2.5GT/s Width x1 — clean
  - `UESta` all clear; `CESta` AdvNonFatalErr+ (benign accumulator)
  - `DevSta` `CorrErr+ UnsupReq+` — benign post-boot noise
- No brcmfmac currently loaded.
- Hypothesis stated above.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.196.journalctl.txt`.

---

## POST-TEST.195 (2026-04-22) — max_res_mask widening WORKED (resources 6+7 asserted) but chip became unstable mid-dwell → hard crash (SMC reset required)

Logs: `phase5/logs/test.195.journalctl.txt` (792 brcmfmac lines) + `test.195.journalctl.full.txt` (2123 lines, full boot). Captured from journalctl boot -1 history after recovery — boot ended mid-dwell with no panic/MCE in dmesg (silent freeze).

### Key result — first ever observation of res_state advancing past 0x13b

| Register | test.194 (max=0x13f) | test.195 (max=0x1ff) | Delta |
|---|---|---|---|
| `max_res_mask` | 0x13f | **0x1ff** | widened by our write ✓ |
| `res_state` | 0x13b | **0x1fb** | **bits 6 + 7 newly asserted** (HT clock + backplane HT) |
| `clk_ctl_st` | 0x00050040 | **0x01070040** | new bits 0x01020000 set |
| `pmustatus` | 0x2a | **0x2e** | bit 0x4 set |
| `min_res_mask` | 0x13b | 0x13b | unchanged (we did not touch min) |

Diagnostic line in dmesg confirms write landed:
```
brcmf_chip_setup: BCM4360 test.195: max_res_mask 0x0000013f -> 0x000001ff (write 0x1ff)
```

**The hypothesis was correct in mechanism:** widening max_res_mask DID cause the chip to grant resources 6 and 7. This is the first time ever in this project that res_state has changed past the POR value of 0x13b.

### But — TCM never advanced AND chip became unstable

| Signal | Observation |
|---|---|
| TCM dwell-pre samples | UNCHANGED from baseline |
| TCM dwell-3000ms samples (got ~56 of 271 before crash) | ALL UNCHANGED — fw still not writing scratch |
| D11 RESET_CTL | 0x1 (still in reset) |
| ARM CR4 CPUHALT | NO (still running) |

**Box hard-crashed mid-dwell** (boot -1 ended at 00:53:12 BST, exactly when the TCM-sample stream stops at fw-sample[0x238f8]). No MCE, no panic, no oops in dmesg — the kernel just stopped logging. Required SMC reset to recover. Boot 0 (current, 00:54:26) is fresh, no module loaded; PCIe state clean (`MAbort-`, no FatalErr, link x1/2.5GT/s).

### Interpretation

Resources 6 and 7 control HT-clock domains. Enabling them simultaneously (the only delta vs test.194) caused the chip to switch into a state where the heavy TCM-poll loop (running every ~10ms during the 3s dwell) eventually triggered a fatal MMIO fault that the host couldn't recover from. Likely root cause: chip changed PCIe ref-clock or backplane clock once HT became available; the host's continued indirect-MMIO reads then collided with that transition and produced an unrecoverable CTO.

### Implications

1. **The unblock direction is right.** First res_state movement in 30+ tests means we're touching the actual gate.
2. **The diagnostic harness is now the liability.** The same TCM-poll loop that was safe in test.194 (resources gated off) is unsafe once resources are live.
3. **Firmware still hasn't started writing TCM** even with HT resources asserted. Either it needs more time than 3s, more resources (min_res_mask widening to *force* 6/7 to stay asserted), or a different trigger (NVRAM/OTP).

### Next test (test.196) — staged, low-poll diagnostic

Plan:
1. Keep `max_res_mask = 0x1ff` (proven to work).
2. Bisect bits 6 vs 7: try `max_res_mask = 0x17f` first (bit 6 only) — if safe, follow with bit 7. Identifies which resource destabilises the chip.
3. **Drastically reduce TCM-poll volume** during dwell — sample once at start, once at end. Replace with PMU/clk-state samples every 200ms (no-op MMIO of CC regs is cheap and stays in CC core which we know is safe).
4. Add `min_res_mask` and `max_res_mask` to the periodic PMU sample so we can see if firmware writes them.
5. If bit-6-only is also unstable, try widening *min_res_mask* to 0x17b (force bit 6 always asserted) — that may give firmware a stable HT clock long enough to write something.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| `max_res_mask = 0x1ff` widening doesn't matter | 195 | **falsified** — measurably activates resources 6+7 |
| 3s dwell with heavy TCM poll is universally safe | 195 | **falsified** — safe at res_state=0x13b but unsafe at 0x1fb |

---

## PRE-TEST.195 (2026-04-22) — widen max_res_mask from 0x13f (POR) to 0x1ff (wl.ko value)

### Hypothesis

Firmware is running (confirmed in test.194 post-mortem: ARM CR4 CPUHALT=NO
for 3s after set_active) but stalls on HT-clock polling. `res_state=0x13b`
and `max_res_mask=0x13f` throughout the dwell — the chip cannot grant
resources beyond bits 0..5 + bit 8 because max_res_mask forbids them.

Wl.ko's final PMU write programs `max_res_mask = 0x1ff` (bits 0..8). If
HT clock is driven by one of the bits the POR value of 0x13f masks out
(namely bits 6 and 7 — 0x40 and 0x80), widening to 0x1ff should allow
HT to assert and unblock the firmware poll.

### Implementation

One new write in `brcmf_chip_setup` (chip.c) after the PMU WAR block,
gated on `chip == BCM4360`:

```c
write(CORE_CC_REG(pmu->base, max_res_mask), 0x1ff);
```

Logged via `brcmf_err` with read-back before/after for proof.

### Expected outcomes

| Observation | Interpretation |
|---|---|
| `max_res_mask 0x0000013f -> 0x000001ff` AND TCM scratch shows CHANGED bytes | HT clock gate was the blocker; firmware advancing |
| `max_res_mask 0x0000013f -> 0x000001ff` AND res_state grows past 0x13b | resources 6/7 activated; firmware may still stall later |
| `max_res_mask 0x0000013f -> 0x000001ff` AND everything else identical to test.194 | max widening wasn't the gate; try min widening or OTP |
| Hard crash | unexpected — widening max_res_mask is documented behavior |

### Build + pre-test

- chip.c edited, built clean (brcmfmac.ko + chip.c timestamps match @ 2026-04-22 00:46)
- PCIe state (verified pre-run after crash + SMC reset):
  - `MAbort-`, `CommClk+`, LnkSta Speed 2.5GT/s Width x1 — clean
  - DevSta has `CorrErr+ UnsupReq+` — benign post-boot noise, no FatalErr
- Session context: prior session ended with a crash; user performed SMC reset
  before this run. Boot 0 (2026-04-22 00:49) is fresh, no prior module load.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.195.journalctl.txt`.

---

## POST-TEST.194 (2026-04-22) — PCIe2 writes landed cleanly, firmware executes but stalls on HT-clock polling

Log: `phase5/logs/test.194.journalctl.txt` (727 lines visible in dmesg) +
`test.194.journalctl.full.txt` (977 lines journalctl capture).

### Diagnostic output

```
test.194: PCIe2 CLK_CONTROL probe = 0x00000182   ← PCIe2 core alive, probe passed
test.194: SBMBX write done                        ← CONFIGIND 0x098 = 0x1 ✓
test.194: PMCR_REFUP 0x00051852 -> 0x0005185f    ← read back confirms +0x1f bits set
```

### Key finding — ARM CR4 IS RUNNING, firmware stalls on HT clock

Mis-read the earlier logs; ARM CR4 *is* released via `brcmf_chip_set_active`:

```
calling brcmf_chip_set_active resetintr=0xb80ef000 (BusMaster ENABLED)
brcmf_chip_set_active returned true
post-set-active-20ms   ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← ARM released
post-set-active-3000ms ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← still running
```

**Firmware executes but makes no observable progress.** Consistent with the
stall described in `phase6/wl_pmu_res_init_analysis.md §1`: firmware writes
`NOILPONW` (pmucontrol bit 0x200) early in `si_pmu_init` — we see
pmucontrol change from 0x01770181 → 0x01770381 over the dwell — then
polls for HT clock availability and never sees it.

### Evidence that ARM is running but stalled

| Signal | Value | Interpretation |
|---|---|---|
| ARM CR4 IOCTL | 0x0021 → 0x0001 | CPUHALT cleared ✓ |
| pmucontrol | 0x01770181 → 0x01770381 | NOILPONW bit 0x200 was set by firmware `si_pmu_init` |
| pmustatus | 0x2a (stable) | no progress (expect HT_AVAIL bits to appear) |
| res_state | 0x13b (stable) | HT resource never asserted |
| min_res_mask | 0x13b | unchanged |
| max_res_mask | 0x13f | unchanged — **HT resources likely gated OUT** |
| D11 RESET_CTL | 0x0001 (stable) | D11 still in reset — firmware never gets far enough to initialise D11 |
| TCM | all stable | firmware isn't writing scratch/heap → stuck in polling loop |

### Next hypothesis — widen max_res_mask to 0x1ff

Wl.ko's final writes at +0x153ed/+0x15401 program `min_res_mask` and
`max_res_mask`. POR leaves max_res_mask=0x13f (bits 0..5, 8). Wl.ko
widens max to **0x1ff** (bits 0..8 all permitted). If the HT clock
resource sits at bit 6 or bit 7, the chip can never grant it without
the wider mask, so the firmware's HT-avail poll will never succeed.

Planned test.195:

1. In `brcmf_chip_setup` (before the PMU WAR block), write
   `max_res_mask = 0x1ff` (offset 0x61c). Leave min_res_mask alone
   (POR=0x13b matches wl.ko's resolved value).
2. Use `brcmf_err`/`pr_emerg` for the write log so it's visible.
3. Expected signature of success: either (a) res_state grows beyond
   0x13b over the dwell, or (b) D11 RESET_CTL changes from 0x1 to 0x0
   (fw advances to core init), or (c) TCM scratch regions show writes.

### Ruled out so far

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/#7/#0xe/#0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |

### Remaining untested candidates (priority order)

1. **max_res_mask = 0x1ff** (test.195 — planned above, cheap bit widen)
2. **OTP init / radio calibration** — brcmfmac skips OTP entirely; firmware
   might need OTP-derived values before HT can assert
3. **min_res_mask = 0x1ff** also (go nuclear after max)
4. **D11 core passive init** — brcmfmac doesn't explicitly do anything to D11
   core before set_active; maybe firmware expects clock-enable

---

## PRE-TEST.194 (2026-04-22) — minimal PCIe2 init (SBMBX + PMCR_REFUP) re-enabled with liveness probe

**Status:** pcie.c edited, module built clean, ready to run.

### Hypothesis

After ruling out PMU WARs in test.193, next candidate is the PCIe2 core
bring-up that `brcmf_pcie_attach` currently bypasses entirely for BCM4360.
Auditing bcma's `bcma_core_pcie2_init` against our actual silicon
(chiprev=3, pcie2 core rev=1) eliminates 4 of 6 workarounds (DLYPERST, LTR,
crwlpciegen2, crwlpciegen2-gated) because their revision gates aren't met.

The only UNCONDITIONAL writes bcma does are:
- `PCIE2_SBMBX (0x098) = 0x1` — PCIe2 soft-mbox kick
- `PCIE2_PMCR_REFUP (0x1814) |= 0x1f` — power-management refup timing

If either of these is what gets PCIe2 to assert the signal the ARM CR4
firmware is polling, we may see first-ever TCM/D11 state change.

### Implementation (pcie.c brcmf_pcie_attach)

Replaced the full `if (BCM4360) return;` bypass with:
1. `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)`
2. Read `BCMA_CORE_PCIE2_CLK_CONTROL` (offset 0x0 of PCIe2 core) as a
   liveness probe. If it reads back `0xFFFFFFFF` or `0x00000000`, abort
   without doing any writes (PCIe2 core is dead/in reset).
3. Otherwise, perform the two writes via the indirect-config addr/data
   register pair (`CONFIGADDR = 0x120`, `CONFIGDATA = 0x124`):
   - `CONFIGADDR = 0x098; CONFIGDATA = 0x1`   (SBMBX)
   - `CONFIGADDR = 0x1814; DATA = read | 0x1f`  (PMCR_REFUP RMW)

All steps emit `pr_emerg` so output is visible without INFO debug enabled.

### Safety notes

- The original bypass was added to avoid a CTO→MCE crash caused by accessing
  PCIe2 MMIO while the PCIe2 core is in BCMA reset. The bypass condition was
  discovered empirically. Current flow (test.188 baseline + test.193 PMU WARs)
  has already successfully accessed BAR0 MMIO many times in buscore_reset /
  chip_attach / reset_device-bypass paths. The liveness probe catches the
  legacy failure mode if it returns.
- If the CLK_CONTROL probe returns an anomalous value (e.g. 0xDEADBEEF or a
  very bit-stuck pattern), that still indicates some form of "alive" and we
  will proceed with writes. The 0x0 / 0xFFFFFFFF guard is specifically for
  "device response missing" (CTO hardware default).
- The writes are to indirect config space via the on-chip CONFIGADDR/DATA
  pair; they do not touch PCIe link parameters and cannot break the bus.

### Decision tree

| Observation | Meaning | Next |
|---|---|---|
| Probe returns 0xffffffff or 0 | PCIe2 core in reset — writes skipped | Need to release PCIe2 BCMA reset first (test.195) |
| Probe returns real value, writes succeed, firmware boots (TCM CHANGED) | PMCR_REFUP/SBMBX was the gate | Follow firmware startup, enable remaining probe steps |
| Probe returns real value, writes succeed, firmware still silent | PCIe2 unconditional writes not the blocker either | Pivot to OTP init (option B) or D11 core (option C) |
| Hard crash | Something in the write path trips the CTO regression | Restore bypass, investigate core reset state |

### Pre-test checklist

1. Build status: REBUILT CLEAN
2. PCIe state: MAbort-, CommClk+, link up x1/2.5GT/s (verified before test.193)
3. Hypothesis stated: see above
4. Plan committed and pushed: this commit
5. Filesystem synced in commit step

### Run command

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.194.journalctl.txt`.

---

## POST-TEST.193 (2026-04-22) — WARs confirmed landing but produce no firmware progress → PMU WARs ruled out as blocker

Log: `phase5/logs/test.193.journalctl.txt` (974 lines) + `.full.txt`.

### Diagnostic output confirmed

```
test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11
test.193: PMU WARs applied — chipcontrol#1 0x00000a10->0x00000a10
          pllcontrol#6=0x080004e2 #0xf=0x0000000e
```

| Fact | Evidence |
|---|---|
| Gate condition met (`chip==4360 && ccrev>3`) | ccrev=43, prints "applied" not "SKIPPED" |
| pmurev=17, pmucaps=0x10a22b11 | matches wl.ko expectations for BCM4360 |
| chipcontrol #1 already has bit 0x800 SET at probe time | read-back 0x00000a10 both before AND after OR-0x800 |
| pllcontrol #6 write landed | read-back 0x080004e2 matches value we wrote |
| pllcontrol #0xf write landed | read-back 0x0000000e matches value we wrote |
| Firmware still blocked | all TCM/D11 scratch UNCHANGED, res_state=0x13b UNCHANGED |

**Bottom line:** chip_pkg=0 PMU WARs are NOT the firmware-stall blocker.
Bit 0x800 of chipcontrol #1 is already set by POR/bootrom; the pllcontrol
#6/#7/#0xe/#0xf writes land cleanly but have no visible downstream effect
on pmustatus / res_state / clk_ctl_st / TCM.

### Comparison vs test.192 (WARs off) and test.191 (baseline)

All PMU/TCM samples IDENTICAL to test.191 baseline. The WARs changed **nothing
visible** in any register we currently sample. Likely explanations:

1. The pllcontrol writes are regulator voltage targets — effect is only
   observable on an oscilloscope / by downstream resources drawing that rail.
   No register snapshot would show it.
2. The WARs enable capabilities the firmware needs **later**, once it's
   running; but firmware never starts because a **different** prerequisite
   is still missing.

Either way, we've exhausted the PMU-WAR hypothesis.

### Next gap to investigate — PCIe2 core bring-up

Log line at test.193 t=2219ms: `BCM4360 test.129: brcmf_pcie_attach bypassed
for BCM4360` — brcmfmac's `brcmf_pcie_attach` returns early for BCM4360 at
pcie.c:895, skipping:

- **PCIE2_CLK_CONTROL DLYPERST/DISSPROMLD** workaround for rev>3
  (this is THE BCM4360-specific PCIe workaround from bcma; phase6 gap analysis
  ranked it #1 of missing writes)
- LTR (Latency Tolerance Reporting) config
- Power-management clock-period, PMCR_REFUP, SBMBX writes

Our earlier decision to bypass brcmf_pcie_attach was to avoid a crash during
development; now that the chip is stable through fw-download, we can re-enable
selective parts. Recommend test.194: implement just the **PCIE2_CLK_CONTROL
DLYPERST/DISSPROMLD** write (bcma `bcma_core_pcie2_workarounds` for BCM4360
corerev>3) as the next candidate unblock.

### Preserved evidence

- `phase5/logs/test.192.journalctl.txt` — WARs silent (INFO filtered)
- `phase5/logs/test.193.journalctl.txt` — WARs confirmed via brcmf_err
- `phase6/wl_pmu_res_init_analysis.md` — PMU WAR analysis with §0/§0.1 corrections

### Action items (next session)

1. Re-read `phase6/downstream_survey.md` and the bcma `driver_pcie2.c`
   DLYPERST/DISSPROMLD workaround.
2. Find the PCIE2 core in chip->cores (PCIE2 coreid / pci_dev base address).
3. Implement the workaround in a new callsite (before set_active / fw download),
   gated on BCM4360 && corerev>3.
4. Test as test.194.

---

## PRE-TEST.193 (2026-04-22) — diagnostic build to confirm WARs land

(Now superseded by POST-TEST.193 above. Original plan retained for context.)

### Test.192 result — no crash, no visible state delta

Log: `phase5/logs/test.192.journalctl.txt` (also `test.192.journalctl.full.txt`,
972 + 971 lines respectively).

**Good news:** the probe path ran end-to-end, reached firmware download (442233
bytes to TCM), completed the 3000ms dwell, cleared bus-master, returned clean
-ENODEV. **No hard crash.**

**Observed state at dwell-3000ms (BASELINE vs WAR-enabled, side-by-side):**

| Register | test.191 (no WARs) | test.192 (WARs) | Delta |
|---|---|---|---|
| `CC-clk_ctl_st` | 0x00050040 | 0x00050040 | UNCHANGED |
| `CC-pmucontrol` pre-release | 0x01770181 | 0x01770181 | same |
| `CC-pmucontrol` post-dwell | 0x01770381 | 0x01770381 | **same CHANGED bit-0x200** |
| `CC-pmustatus` | 0x0000002a | 0x0000002a | UNCHANGED |
| `CC-res_state` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-min_res_mask` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-max_res_mask` | 0x0000013f | 0x0000013f | UNCHANGED |
| `CC-pmutimer` | 0x0457e14b → ... | 0x0457e14b → ... | (free-running) |
| All ~30 TCM/D11 scratch regions | all UNCHANGED | all UNCHANGED | UNCHANGED |

Conclusion: **the WAR writes had zero observable effect on any sampled
register.** Either (a) the writes never executed (gate condition false), or
(b) they executed but don't produce any side effect we're currently sampling.

### Diagnostic gap

`brcmf_dbg(INFO, "BCM4360 test.192: applied chip_pkg=0 PMU WARs")` was
silent — INFO-level debug is filtered out of dmesg by default. Every
previous test's `brcmf_dbg(INFO, ...)` output (e.g. `ccrev=%d pmurev=%d`
at chip.c:1131) is also missing from test.188/191/192 logs. So I cannot
distinguish "WARs skipped because `cc->pub.rev ≤ 3`" from "WARs ran but
had no effect".

### Test.193 — diagnostic upgrade (rebuilt clean, ready to run)

Changed `brcmf_dbg(INFO, ...)` → `brcmf_err(...)` for the test.192 marker,
added a chip/rev dump before the gate, and added read-back of
`chipcontrol #1`, `pllcontrol #6`, `pllcontrol #0xf` after the writes to
prove the indirect address/data pair is actually landing values.

Expected new log lines (all via `brcmf_err` so always print):

```
BCM4360 test.193: chip=0x4360 ccrev=<N> pmurev=<M> pmucaps=0x<caps>
BCM4360 test.193: PMU WARs applied — chipcontrol#1 0x<pre>->0x<post> pllcontrol#6=0x080004e2 #0xf=0x0000000e
```
(or `PMU WARs SKIPPED` with the reason.)

### Decision tree after test.193

| Log line | Interpretation | Next |
|---|---|---|
| `WARs SKIPPED (chip=0x4360 ccrev=<N>)` with N ≤ 3 | gate too strict; wl.ko path does not actually require corerev > 3 for chip_pkg=0 | drop the `ccrev>3` constraint, rebuild |
| `WARs SKIPPED` with chip ≠ 0x4360 | unexpected chip id match failure — investigate BRCM_CC_4360_CHIP_ID constant | grep the header |
| `WARs applied` but pllcontrol readbacks show 0x00000000 | write-ignore — wrong offsets or wrong corerev gating in hardware | re-audit, try raw 0x660/0x664 via ops->write32 with absolute offset |
| `WARs applied` with correct readbacks, state still all UNCHANGED | WARs did land but firmware still blocked by something else | pivot to next gap: PCIe2 init (DLYPERST/DISSPROMLD) or min/max_res_mask widen |
| `WARs applied` with correct readbacks, res_state or pmustatus CHANGED | first sign of progress; follow the signal | sample additional resources, keep going |

### Run command (same as test.192)

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected log: `phase5/logs/test.<N>` (script auto-increments; rename to `test.193.journalctl.txt`).

---

## Older test history

Tests prior to test.193 have been moved to [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md) to keep this file small for fresh-session pickup. When a new POST-TEST is recorded here, the oldest PRE/POST pair gets pushed to the top of the history file so this file always holds the latest 3 tests.
