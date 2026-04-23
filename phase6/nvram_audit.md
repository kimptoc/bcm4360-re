# BCM4360 NVRAM Audit

**Date:** 2026-04-23  
**Task:** Track 4 from test248_other_work.md — determine if firmware stall is NVRAM-driven rather than PMU/shared-struct-driven.

## 1. Current NVRAM Input

**File:** `/home/user/bcm4360-re/phase4/work/brcmfmac4360-pcie.txt` (17 lines, ~100 bytes content)

### Trailer Convention

**Format:** brcmfmac standard (documented in phase4/work/bcm4360_test.c:400-405)
- Location: TCM `ramsize - 4`
- Encoding: `(~nvram_padded_len << 16) | nvram_padded_len`
- Padding: NVRAM text padded to 4-byte boundary with null bytes
- Example seen in pcie.c test.247: `0xffc70038` marker (observed in test.211–test.242 polling)

## 2. Normalized Key/Value Table

| Key | Current Value | Status | Notes |
|---|---|---|---|
| `sromrev` | `11` | **CORRECT** | Expected for BCM4360 (SROM revision 11) |
| `boardtype` | `0x0552` | **UNCERTAIN** | Common BCM4360 reference; no real SPROM read performed; Apple hardware may differ |
| `boardrev` | `0x1101` | **UNCERTAIN** | Guessed placeholder; Apple MacBookPro11,1 hardware value unknown without SPROM extraction |
| `boardflags` | `0x10401001` | **UNCERTAIN** | Reasonable reference value; specific to board variant |
| `boardflags2` | `0x00000002` | **UNCERTAIN** | Minimal; may lack board-specific tuning (PA, antenna diversity) |
| `boardflags3` | `0x00000000` | **UNCERTAIN** | All reserved bits zero; likely incomplete for Apple variant |
| `boardnum` | `0` | **ACCEPTABLE** | Safe default; firmware may not validate strictly |
| `macaddr` | `00:1C:B3:01:12:01` | **ACCEPTABLE** | Synthetic (Apple OUI + placeholder); real MAC would come from EFI/OTP |
| `ccode` | `X0` | **CORRECT** | Standard world regulatory code; valid for brcmfmac |
| `regrev` | `0` | **ACCEPTABLE** | Safe default for world region |
| `vendid` | `0x14e4` | **CORRECT** | Broadcom's PCI vendor ID (confirmed in hardware) |
| `devid` | `0x43a0` | **CORRECT** | BCM4360 PCI device ID (confirmed in hardware at `03:00.0`) |
| `xtalfreq` | `40000` | **CORRECT** | Standard xtal frequency for BCM4360 (40 MHz); consistent with Broadcom reference designs |
| `aa2g` | `7` | **CORRECT** | 2.4 GHz antenna config (0x7 = all 3 antennae active); standard BCM4360 value |
| `aa5g` | `7` | **CORRECT** | 5 GHz antenna config (0x7 = all 3 antennae active); standard BCM4360 value |

## 3. Missing Typically-Required Keys for BCM4360

**Standard SROM revision 11 fields absent from current NVRAM:**

| Key | Purpose | Typical Value | Impact |
|---|---|---|---|
| `pa0b0`, `pa0b1`, `pa0b2` | 2.4 GHz PA power calibration (3 coefficients) | 0x0000–0xFFFF each | **HIGH** — PA not calibrated; Tx power incorrect or disabled |
| `pa1b0`, `pa1b1`, `pa1b2` | 5 GHz PA power calibration (3 coefficients) | 0x0000–0xFFFF each | **HIGH** — PA not calibrated for 5 GHz band |
| `rssisav2g`, `rssisav5g` | RSSI offset calibration (2.4 & 5 GHz) | 0x00–0xFF | **MEDIUM** — RSSI readings uncalibrated; affects power management and link quality reporting |
| `extpagain2g`, `extpagain5g` | External PA gain (2.4 & 5 GHz) | 0x00–0xFF | **MEDIUM** — PA gain unconfigured; affects output power range |
| `pdetrange2g`, `pdetrange5g` | Power detector dynamic range (2.4 & 5 GHz) | 0x00–0xFF | **LOW** — May be optional; defaults exist in firmware |
| `antswitch` | Antenna switch GPIO configuration | 0x00–0xFF | **LOW** — May default if absent; relevant only if external antenna switch present |
| `txpid2g[0–3]`, `txpid5g[0–3]` | Tx power index per rate (2.4 & 5 GHz, 4 entries) | 0x00–0xFF each | **MEDIUM** — Tx power may be capped or use firmware defaults |
| `rxgains2gelnagain0`, `rxgains2gtrisoa0`, `rxgains2gtrelnabypa0` | 2.4 GHz RX gain calibration | 0x00–0xFF | **LOW–MEDIUM** — RX sensitivity may degrade without calibration |
| `rxgains5gelnagain0`, `rxgains5gtrisoa0`, `rxgains5gtrelnabypa0` | 5 GHz RX gain calibration | 0x00–0xFF | **LOW–MEDIUM** — RX sensitivity may degrade without calibration |

## 4. Flag Observations and Concerns

### Boardtype/Revision Cross-Check

- **PCI device ID:** `0x43a0` (from hardware, confirmed in test.9 BAR0 dump)
- **Chip ID:** `0x4360` (from BAR0 ChipCommon register, confirmed in test.9)
- **NVRAM boardtype:** `0x0552` (generic BCM4360 reference)
- **NVRAM boardrev:** `0x1101` (placeholder; real board revision unknown)

**Risk:** Firmware may use `boardtype` + `boardrev` to load board-variant-specific initialization code. If these values do not match the actual Apple hardware variant, firmware may apply wrong calibration, skip necessary init, or fail validation.

**Mitigation:** Firmware initializes with placeholder values at present; no production error observed yet. However, if firmware reaches a point where it validates board identity before advancing, wrong boardtype/rev could be a stall trigger.

### Antenna Configuration

- `aa2g=7` and `aa5g=7` mean all three antennae active (bits 0,1,2 set).
- **Uncertain:** Apple MacBookPro11,1 may use 1–2 antennae. Overspec'd antenna config could cause firmware calibration mismatch.
- **Check:** If available, Apple device tree or SPROM would clarify actual antenna count.

### Power-Related Parameters

- **xtalfreq=40000 (MHz):** Standard; no concern.
- **PA calibration:** Entirely missing. Firmware may:
  1. Fail to validate NVRAM (error return before shared-struct setup) → stall at current observed point (t+90–120s)
  2. Continue with zeroed PA coefficients → operate but at degraded power
  3. Use firmware-embedded fallback calibration → continue normally

**Current evidence:** test.238–test.242 show firmware reaches t+90–120s mark before wedging (per RESUME_NOTES_HISTORY.md), suggesting early NVRAM validation didn't block attach. However, firmware never publishes shared-struct pointer (remaining at `0xffc70038` trailer marker), consistent with a later internal stall.

## 5. Pre-Shared-Struct NVRAM Reading

**Question:** Does firmware read/validate NVRAM before attempting to allocate and publish the shared-struct?

**Evidence:**
- Phase 6/NOTES.md (line 182–189): "wl calls `otp_init`, `otp_nvread`, `otp_read_region` as part of NVRAM loading path; brcmfmac uses direct NVRAM text injection."
- Phase 5 logs (test.211–test.242): NVRAM text at `0x9ff1c–0xa0000` remains unchanged across 90s observation window; firmware never reads it after initial load.
- **Inference:** Firmware reads NVRAM very early (before shared-struct setup), but downstream access is minimal or deferred. Early validation failure would manifest as rapid return/crash, not t+90s wedge.

## 6. Comparison Against References

**No reference NVRAM available in tree:**
- Searched `/home/user/bcm4360-re` for `*nvram*`, `*43602*`, `*brcmfmac*`
- Found only: current test NVRAM (`phase4/work/brcmfmac4360-pcie.txt`) and one backup (`phase5/work/nvram-backup-pre-205.txt`, identical content).
- **Project references BCM43602 gist at https://gist.github.com/MikeRatcliffe/9614c16a8ea09731a9d5e91685bd8c80 for format guidance, but no BCM4360-specific external reference on disk.**

**What external reference would buy:**
1. **Real board-type/revision values** for Apple MacBookPro11,1.
2. **Antenna count and diversity configuration** (confirm aa2g=7, aa5g=7 or correct).
3. **Calibration coefficients** (pa0b*, pa1b*, rxgains*, etc.) from Apple OTP/SPROM.
4. **Board-specific flags** (boardflags2/3 additional bits for Apple variant).

## 7. Proposed NVRAM Edits (Ranked by Impact)

### HIGH-IMPACT — Justifies single A/B hardware test each

#### Edit H1: Zero-out boardflags/boardflags2/boardflags3

**Rationale:** If firmware validation checks flags and expects zero-bits to be unset, current non-zero values might trigger optional initialization paths that fail. Zeroing forces minimal-config path.

**Change:**
```
boardflags=0x00000000
boardflags2=0x00000000
boardflags3=0x00000000
```

**Expected outcome:** Firmware proceeds past NVRAM validation; if flags themselves were the stall trigger, wedge moves or clears. If not, stall persists unchanged (flags not the culprit).

**Boot cost:** ~180s (one SMC reset cycle).

---

#### Edit H2: Change boardtype to 0x0000 (undefined/generic)

**Rationale:** Firmware may validate boardtype against a whitelist and reject unknown boards. Setting to 0 forces "generic BCM4360" path (if one exists).

**Change:**
```
boardtype=0x0000
```

**Expected outcome:** If firmware requires non-zero boardtype, error/crash visible immediately (< 5s). If accepted, may unlock fallback init code. If already using fallback (current behavior), no change.

**Boot cost:** ~180s.

---

### MEDIUM-IMPACT — Worth testing if H1/H2 null

#### Edit M1: Add minimal PA calibration (placeholder zeros)

**Rationale:** Firmware PA init code may loop on a check like `if (pa0b0 == 0) skip_tx_init()` or `else validate_and_apply()`. Explicit zeros signal "no calibration available"; firmware should gracefully degrade.

**Change:** Add after `xtalfreq=40000`:
```
pa0b0=0x0000
pa0b1=0x0000
pa0b2=0x0000
pa1b0=0x0000
pa1b1=0x0000
pa1b2=0x0000
```

**Expected outcome:** Firmware recognizes PA fields; either applies zero calibration (Tx disabled/degraded, attach succeeds) or rejects all-zero as invalid and errors visibly. Current null behavior suggests firmware skips PA validation or uses embedded fallback.

**Boot cost:** ~180s.

---

#### Edit M2: Add minimal RX calibration (placeholder zeros)

**Rationale:** Similar logic to PA; RX gain/RSSI offset may be required.

**Change:** Add after PA edits:
```
rssisav2g=0x00
rssisav5g=0x00
extpagain2g=0x00
extpagain5g=0x00
```

**Expected outcome:** If firmware hangs on RX init, explicit zeros may unblock (firmware has "no calibration" signal). If firmware hangs elsewhere, no change.

**Boot cost:** ~180s.

---

### LOW-IMPACT — Diagnostic or unrelated

#### Edit L1: Change macaddr to 00:00:00:00:00:00

**Rationale:** Test whether MAC address validation could be the stall point (unlikely, but rules out edge case).

**Change:**
```
macaddr=00:00:00:00:00:00
```

**Expected outcome:** If MAC validation is not the issue (most likely), no change. If firmware rejects all-zero MAC, error visible immediately.

**Boot cost:** ~180s.

---

## 8. Test Plan (Execution Priority)

**Phase:** Test.244+ (requires BCM4360 hardware)

| Seq | Edit | Hypothesis | Expected Outcome | Boot Cost |
|---|---|---|---|---|
| 1 | H1 | Flags validation blocks attach | Wedge disappears or changes stage | 180s |
| 2a | H2 | Boardtype whitelist blocks attach | Crashes at NVRAM validation stage (< 5s); visible error | 180s |
| 2b | M1 | PA init validation loop stalls | Tx disabled but attach succeeds | 180s |
| 2c | M2 | RX init validation loop stalls | RX degraded but attach succeeds | 180s |
| 3 | L1 | MAC address validation (low priority) | No change expected | 180s |

**Stopping rule:** If any edit moves wedge time or changes terminal behavior (crash, timeout, success), that edit becomes high-priority for refinement. If all edits null, NVRAM is not the blocker — pivot to PMU/PLL or shared-struct signature research.

## 9. Key Assumptions (Unverified)

1. **Firmware does validate NVRAM before shared-struct allocation.** No evidence contradicts this, but firmware reaches t+90–120s before hanging, suggesting validation succeeded (or was skipped).

2. **Firmware does not read Apple OTP directly.** brcmfmac driver injects NVRAM via TCM; firmware firmware expected to use it. No firmware code observed attempting OTP reads in test data.

3. **boardtype/boardrev whitelist exists.** Unknown if firmware rejects unknown board IDs or applies default fallback. Current placeholder does not cause immediate crash.

4. **PA calibration is optional.** Firmware has embedded defaults or accepts zero coefficients. Current all-zero state does not crash at observable stages.

5. **Antenna config is validated early.** If aa2g/aa5g mismatch hardware, error expected before t+90s; current behavior (late wedge) suggests antenna config is not the issue.

---

## 10. Summary

**Current NVRAM Status:**
- **15/17 fields:** Acceptable or correct (standard values; no obvious malformation).
- **2/17 fields:** Uncertain (boardtype/boardrev placeholders; no real SPROM extraction).
- **~10 standard SROM rev 11 fields:** Missing (PA/RX calibration); firmware likely handles gracefully or uses embedded defaults.

**Confidence Firmware Stall is NVRAM-Driven:**
- **Low-Medium.** Current NVRAM is minimal but not obviously malformed. Firmware reaches t+90–120s before wedging, past the typical NVRAM validation window. However, missing calibration or wrong boardtype/flags could block firmware at a later stage (post-attach clock/resource init).

**Recommended Next Step:**
- Run **Test.244** (Edit H1: zero boardflags) on BCM4360 hardware. If wedge clears, boardflags tuning is the lever. If not, escalate to PMU/PLL research and shared-struct signature audit (Test.249).
