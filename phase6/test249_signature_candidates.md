# Test.249: Signature/Version Sweep — Candidate Selection

## 1. Upstream PCIE Shared-Struct Version Constants

| Constant Name | File:Line | Value | Purpose |
|---|---|---|---|
| `BRCMF_PCIE_SHARED_VERSION_7` | pcie.c:408 | 7 | Named constant for version 7 (highest supported) |
| `BRCMF_PCIE_MIN_SHARED_VERSION` | pcie.c:409 | 5 | Minimum version host accepts (gate for entry) |
| `BRCMF_PCIE_MAX_SHARED_VERSION` | pcie.c:410 | (= SHARED_VERSION_7) | Maximum version (evaluates to 7) |
| `BRCMF_PCIE_SHARED_VERSION_MASK` | pcie.c:411 | 0x00FF | Mask to extract version byte from flags field |

**Version guard logic** (pcie.c:2133-2137):
```c
if ((shared->version > BRCMF_PCIE_MAX_SHARED_VERSION) ||
    (shared->version < BRCMF_PCIE_MIN_SHARED_VERSION)) {
    brcmf_err(bus, "Unsupported PCIE version %d\n", shared->version);
    return -EINVAL;
}
```

**Version-gated behavior** (pcie.c:1741-1750):
- **Version < 6**: Uses legacy ring-item-size table (`brcmf_ring_itemsize_pre_v7`)
- **Version ≥ 6**: Uses newer ring-item-size table (`brcmf_ring_itemsize`); also changes ring-info struct field interpretation

---

## 2. Direction-of-Flow Analysis: Who Publishes the Shared Struct?

### Standard Firmware Protocol (per upstream code comments)

The shared-struct version field travels in the **firmware-to-host direction**:

1. **Host writes NVRAM** → ramsize-4 contains NVRAM trailer magic `0xffc70038`
   - pcie.c:3589-3591 comment: *"host writes NVRAM → 0xffc70038 sits at ramsize-4"*

2. **Firmware reads NVRAM**, parses it, and initializes PCIe2

3. **Firmware overwrites ramsize-4** with `sharedram_addr` (the address of the shared struct it has written into TCM)
   - pcie.c:3593 comment: *"firmware *overwrites* ramsize-4 with sharedram_addr"*

4. **Host detects change** by polling ramsize-4 (pcie.c:4593-4638):
   - Reads `ramsize-4` in a loop
   - When value != initial `0xffc70038`, treats it as firmware-published `sharedram_addr`
   - Firmware has written the struct and host can read it

5. **Host reads struct fields** from the address firmware published
   - `brcmf_pcie_init_share_ram_info()` reads the struct at offset 0:
   - pcie.c:2130: `shared->flags = brcmf_pcie_read_tcm32(devinfo, sharedram_addr);`
   - Version extracted at pcie.c:2131: `shared->version = (u8)(shared->flags & BRCMF_PCIE_SHARED_VERSION_MASK);`

### Direction Summary

| Field | Publisher | Consumer |
|---|---|---|
| `version` (at struct offset 0) | **Firmware publishes** | Host reads and validates |
| `BRCMF_PCIE_MIN_SHARED_VERSION` (value 5) | (N/A — host constant) | Host uses as **minimum acceptance threshold** |

**Critical insight for Test.247 reversal**: In Test.247, we are **pre-placing a version value at TCM[0x80000]** hoping firmware will read it. But upstream protocol has firmware *publishing* the version. A pre-placed value would only be useful if:
- (S1) This Apple-variant BCM4360 firmware reads a pre-allocated shared-struct provided by host, OR
- (S2) Firmware publishes a version but it is **stalled before allocation**, and we are trying to short-circuit that wait.

---

## 3. Chip-Specific Version Handling

**No BCM4360-specific version override found in upstream code.**

Grep results show only two version comparisons in pcie.c:
- pcie.c:1643: `if (devinfo->shared.version < BRCMF_PCIE_SHARED_VERSION_7)` — applies to all chips
- pcie.c:1741: `if (devinfo->shared.version >= 6)` — applies to all chips; switches ring-info struct layout

**Conclusion:** Version `5`, `6`, `7` handling is **generic across all BCM PCIE devices**. No Apple-variant or BCM4360-only version masks found.

---

## 4. Phase 6 Reverse-Engineering Notes: Signature Search

Searched local notes for shared-struct magics, version markers, HND RTE console signatures.

**Findings:**
- No hardcoded version constants found in disassembly notes
- No alternate magic-word candidates (`HNDR`, `BRCM`, etc.) identified in firmware observations
- Console and PMU-state logging (dissassembly_progress.md, wl_pmu_res_init_analysis.md) focus on PMU clock-gate stalls, not version negotiation
- Test.247 result (firmware idle for 90s, then wedge) is consistent with **firmware stalled waiting for PMU/PLL initialization**, not version mismatch

**No evidence found for alternate signature words at offset 0.** Firmware does not appear to read a pre-placed version field; rather, it stalls before publishing its own.

---

## 5. Ranked Test.249 Candidates

### High-Confidence: Core Upstream Versions

These three versions are the only ones explicitly supported by upstream brcmfmac code.

#### Candidate A: Version = 5

- **Value:** `5` (decimal)
- **Rationale:** `BRCMF_PCIE_MIN_SHARED_VERSION` — the minimum host accepts. If this Apple BCM4360 firmware is derived from upstream Broadcom code and publishes a version, this is the **oldest compatible version** in the upstream contract.
- **Why this run:** If Test.247's frozen state is caused by firmware reading a pre-placed version and rejecting version 5, a version 5 read here would confirm that the firmware rejects the minimum-acceptable upstream value. If version 5 works, it eliminates "version too low" as a hypothesis.

#### Candidate B: Version = 6

- **Value:** `6` (decimal)
- **Rationale:** Between MIN (5) and MAX (7). Version ≥ 6 triggers a **different ring-info struct layout** in the host (pcie.c:1741-1750). Firmware built to match upstream ring-info expectations would publish version 6 or 7. If this firmware is from a generation that uses the v6 ring layout, it expects host to interpret ring-info differently.
- **Why this run:** A middle-ground test to check whether firmware responds to version 6 the way it would to version 5, or whether the ring-info layout change (pcie.c:1742-1750) has downstream consequences in TCM activity.

#### Candidate C: Version = 7

- **Value:** `7` (decimal)
- **Rationale:** `BRCMF_PCIE_MAX_SHARED_VERSION` — the newest supported by upstream. If firmware is modern and expects the v7 ring-item-size tables, it would publish version 7. This is the **highest plausible value** in the current Linux codebase.
- **Why this run:** If firmware silently rejects versions 5 and 6, version 7 is the last upstream-sanctioned option. If all three fail and hardware remains stuck, it confirms version field rejection as the blocker (not field-content semantics).

---

### Medium-Confidence: Zero-Byte Alternative (Speculative)

#### Candidate D: Version = 0 (zero)

- **Value:** `0` (decimal)
- **Rationale:** Pre-Test.247 code comment (pcie.c:250) describes struct as "version byte (=5, BRCMF_PCIE_MIN_SHARED_VERSION) at offset 0; **all other 17 u32s zero**." A firmware derived from an older Broadcom SDK (pre-v5 versioning era) might not yet understand version 5 and could treat offset 0 as a different field entirely (e.g., reserved or chip ID). Pre-placing zero would revert to "no version guarding."
- **Why defer:** Upstream code explicitly gates on version ≥ 5; no evidence that firmware understands version 0. This is speculative and should wait until all versions 5–7 are tried.

---

### Low-Confidence: Non-Standard Magics (Do Not Run)

No magic-word alternatives (`BRCM`, `HNDR`, etc.) found in upstream or notes. Firmware does **not read** a pre-placed struct in upstream protocol (firmware publishes). Attempting arbitrary magic words would be guesswork.

**Recommendation:** Skip non-standard candidates until PMU/PLL analysis clarifies whether pre-placed struct is even the right approach.

---

## Summary: Test.249 Plan

**Run 3 boots, in order:**
1. **Boot A:** `version=5` — upstream minimum, baseline from Test.247
2. **Boot B:** `version=6` — ring-info struct layout trigger; medium confidence
3. **Boot C:** `version=7` — upstream maximum; last upstream option

**Success criterion:** Any version produces **new TCM activity** (detected by dwell-ladder reads) or **changes failure mode** (e.g., later wedge time, different SMC-reset recover pattern). If all three freeze at identical times with identical TCM state, version field rejection is likely **not the primary blocker**, and next phase should pivot to PMU/PLL.

**Deferral:** Version 0 and any alternate magic words (Candidate D+) should wait for PMU/PLL gap analysis results.

---

## References

- pcie.c:408-411 — version constant definitions
- pcie.c:2130-2138 — version reading and validation logic
- pcie.c:1641-1750 — version-gated ring-info handling
- pcie.c:3589-3595 — standard protocol comment (firmware overwrites ramsize-4 with struct address)
- dissassembly_progress.md — confirms stall is PMU-related, not version-negotiation
- test248_decision.md — rationale for signature/version sweep as next phase

