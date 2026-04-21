# BCM4360 PMU/PCIe Initialization Gap Analysis

**Date:** 2026-04-21  
**Context:** BCM4360 (chip ID 0x4360, PCI 14e4:43a0) firmware loads and ARM core releases from halt, but then idles indefinitely — no TCM writes, no D11 bringup, no mailbox activity. Hypothesis: missing PMU/PLL/PCIe core initialization register writes that bcma driver performs but brcmfmac skips.

## 1. BCM4360 Initialization Sequence from BCMA

### 1.1 PMU Early Init (`bcma_pmu_early_init` — driver_chipcommon_pmu.c:274)
- **Purpose:** Detect PMU capabilities, locate PMU core.
- **Register reads:** `BCMA_CC_PMU_CAP` (offset 0x04) to get PMU revision (`pmurev`) and capabilities (`caps`).
- **Chip‑specific guard:** None — runs for all chips.
- **File:line:** `driver_chipcommon_pmu.c:274–294`

### 1.2 PMU Main Init (`bcma_pmu_init` — driver_chipcommon_pmu.c:295)
- **Purpose:** Configure PMU control register, then call PLL, resources, workarounds.
- **Register writes:**
  1. **`BCMA_CC_PMU_CTL` (offset 0x0600):** If `pmurev == 1`, clear bit `NOILPONW` (0x00000200); otherwise set it.
  2. **`BCMA_CC_PMU_CTL` (offset 0x0600):** Set bit `PLL_UPD` (0x00000400) after programming PLL.
- **Chip‑specific guard:** None — runs for all chips.
- **File:line:** `driver_chipcommon_pmu.c:295–310`

### 1.3 PLL Init (`bcma_pmu_pll_init` — driver_chipcommon_pmu.c:148)
- **Purpose:** Program PLL control registers for desired clock frequencies.
- **Register writes:**
  1. **`BCMA_CC_PMU_PLLCTL_ADDR` (offset 0x??):** Write PLL register address.
  2. **`BCMA_CC_PMU_PLLCTL_DATA` (offset 0x??):** Write PLL data.
- **Chip‑specific guard:** None — runs for all chips.
- **File:line:** `driver_chipcommon_pmu.c:148–160`

### 1.4 PMU Resources Init (`bcma_pmu_resources_init` — driver_chipcommon_pmu.c:162)
- **Purpose:** Set PMU minimum/maximum resource masks.
- **Register writes:**
  1. **`BCMA_CC_PMU_MINRES_MSK` (offset 0x??):** Write minimum resource mask.
  2. **`BCMA_CC_PMU_MAXRES_MSK` (offset 0x??):** Write maximum resource mask.
- **Chip‑specific guard:** None — runs for all chips.
- **File:line:** `driver_chipcommon_pmu.c:162–229`

### 1.5 PMU Workarounds (`bcma_pmu_workarounds` — driver_chipcommon_pmu.c:230)
- **Purpose:** Apply chip‑specific PMU workarounds.
- **Register writes:** 
  1. **`BCMA_CC_CHIPCTL` (offset 0x??):** Write workaround value.
- **Chip‑specific guard:** `case BCMA_CHIP_ID_BCM4360:` — writes value `0x??`.
- **File:line:** `driver_chipcommon_pmu.c:230–??`

### 1.6 PCIe2 Core Init (`bcma_core_pcie2_init` — driver_pcie2.c:159)
- **Purpose:** Configure PCIe Gen2 core clocks, LTR, power management.
- **Chip‑specific guard:** `switch (bus->chipinfo.id)` includes `BCMA_CHIP_ID_BCM4360`.
- **Register writes executed for BCM4360 (rev > 3):**

| Write Function | Register Macro | Offset | Value Written | Condition |
|----------------|----------------|--------|---------------|-----------|
| `bcma_core_pcie2_war_delay_perst_enab` | `BCMA_CORE_PCIE2_CLK_CONTROL` | 0x?? | Clear `PCIE2_CLKC_DLYPERST`, set `PCIE2_CLKC_DISSPROMLD` | `ci->id == BCMA_CHIP_ID_BCM4360 && ci->rev > 3` |
| `bcma_core_pcie2_hw_ltr_war` | `BCMA_CORE_PCIE2_CONFIGINDADDR` | 0x120 | `PCIE2_CAP_DEVSTSCTRL2_OFFSET` | core_rev >=2 && <=13 |
| | `BCMA_CORE_PCIE2_CONFIGINDDATA` | 0x124 | LTR enable bit set | |
| | `BCMA_CORE_PCIE2_LTR_STATE` | 0x?? | `PCIE2_LTR_ACTIVE` then `PCIE2_LTR_SLEEP` | |
| `pciedev_reg_pm_clk_period` | `BCMA_CORE_PCIE2_CONFIGINDADDR` | 0x120 | `PCIE2_PVT_REG_PM_CLK_PERIOD` | core_rev <=13 |
| | `BCMA_CORE_PCIE2_CONFIGINDDATA` | 0x124 | `(1000000 * 2) / alp_khz` | |
| `pciedev_crwlpciegen2_180` | `BCMA_CORE_PCIE2_CONFIGINDADDR` | 0x120 | `PCIE2_PMCR_REFUP` | always |
| | `BCMA_CORE_PCIE2_CONFIGINDDATA` | 0x124 | `0x1f` | |
| `pciedev_crwlpciegen2_182` | `BCMA_CORE_PCIE2_CONFIGINDADDR` | 0x120 | `PCIE2_SBMBX` | always |
| | `BCMA_CORE_PCIE2_CONFIGINDDATA` | 0x124 | `1 << 0` | |

- **File:line:** `driver_pcie2.c:159–??`

### 1.7 PCIe2 Up (`bcma_core_pcie2_up` — driver_pcie2.c:192)
- **Purpose:** Set PCIe read request size via host PCI config space (not chip registers).
- **No BCM4360‑specific register writes.**
- **File:line:** `driver_pcie2.c:192–??`

## 2. What brcmfmac Already Does

### 2.1 Chip Initialization (`chip.c`)
- **`brcmf_chip_get_raminfo`:** For `BRCM_CC_4360_CHIP_ID` returns hard‑coded RAM base=0, size=0xa0000 (chip.c:764–771).
- **`brcmf_chip_set_passive`:** Called after reset (chip.c:1052,1064). No PMU/PCIe writes.
- **`brcmf_chip_set_active`:** Dispatches to `brcmf_chip_cr4_set_active` (chip.c:1417).
- **`brcmf_chip_cr4_set_active`:** Writes ARM reset vector, releases core from halt — **no PMU/PCIe register writes**.

### 2.2 PCIe Attach (`pcie.c`)
- **`brcmf_pcie_attach`:** For device ID `BRCM_PCIE_4360_DEVICE_ID` (0x43a0) **returns early without any PCIe2 core initialization** (pcie.c:??). This bypasses all PCIe2 clock, LTR, and power‑management writes that bcma performs.

### 2.3 Existing PCIe2 Register Definitions
- **`BRCMF_PCIE_PCIE2REG_INTMASK`, `BRCMF_PCIE_PCIE2REG_MAILBOXINT`, etc.** defined in pcie.c but never used for BCM4360.

## 3. Gap Table – Missing Register Writes in brcmfmac

| Register | Offset (hex) | Value(s) | When in Sequence | BCMA Source | brcmfmac Status |
|----------|--------------|----------|------------------|-------------|-----------------|
| `BCMA_CC_PMU_CTL` (NOILPONW) | 0x0600 | Clear if pmurev==1, else set | After PMU detect | driver_chipcommon_pmu.c:298–301 | **Missing** |
| `BCMA_CC_PMU_CTL` (PLL_UPD) | 0x0600 | Set after PLL programming | After PLL init | driver_chipcommon_pmu.c:143 | **Missing** |
| `BCMA_CC_PMU_MINRES_MSK` | ?? | Chip‑specific mask | Resources init | driver_chipcommon_pmu.c:198 | **Missing** |
| `BCMA_CC_PMU_MAXRES_MSK` | ?? | Chip‑specific mask | Resources init | driver_chipcommon_pmu.c:200 | **Missing** |
| `BCMA_CC_CHIPCTL` | ?? | Workaround value | Workarounds | driver_chipcommon_pmu.c:227 (BCM4360 case) | **Missing** |
| `BCMA_CORE_PCIE2_CLK_CONTROL` | ?? | Clear DLYPERST, set DISSPROMLD | PCIe2 init (rev>3) | driver_pcie2.c:52 | **Missing** |
| `BCMA_CORE_PCIE2_CONFIGINDADDR/DATA` | 0x120/0x124 | LTR configuration | PCIe2 init | driver_pcie2.c:60–101 | **Missing** |
| `BCMA_CORE_PCIE2_LTR_STATE` | ?? | ACTIVE → SLEEP | PCIe2 init | driver_pcie2.c:96,101 | **Missing** |
| `PCIE2_PVT_REG_PM_CLK_PERIOD` | via config | Calculated PM clock period | PCIe2 init | driver_pcie2.c:153–155 | **Missing** |
| `PCIE2_PMCR_REFUP` | via config | 0x1f | PCIe2 init | driver_pcie2.c:134–135 | **Missing** |
| `PCIE2_SBMBX` | via config | 1 << 0 | PCIe2 init | driver_pcie2.c:140–141 | **Missing** |

## 4. Top 5 Ranked Missing Writes

**Ranking criteria:** (a) PMU resource/HT grant related, (b) BCM4360‑specific branch, (c) early‑init prerequisite.

1. **`BCMA_CORE_PCIE2_CLK_CONTROL` (DLYPERST/DISSPROMLD)** — Highest priority. BCM4360‑specific workaround for rev>3; directly controls PCIe core clock gating and reset delay. Firmware may be waiting for this clock to be stable.
2. **`BCMA_CC_PMU_CTL` (NOILPONW)** — PMU control bit that determines whether ILP clock stays on during wait states. If firmware expects ILP to be on but it's off, core may hang.
3. **`BCMA_CC_PMU_MINRES_MSK` / `MAXRES_MSK`** — PMU resource masks grant HT/ALP requests. Firmware flips PMUControl bit‑9 (HT request) and stalls; missing grant could cause infinite wait.
4. **`BCMA_CORE_PCIE2_LTR_STATE` (ACTIVE→SLEEP)** — LTR (Latency Tolerance Reporting) handshake required before PCIe link can enter low‑power states. Missing LTR may block PCIe transactions.
5. **`PCIE2_PVT_REG_PM_CLK_PERIOD`** — Clock period for power‑management timers. Incorrect period could cause timeouts in firmware wait loops.

## 5. Implementation Sketch

### 5.1 Insertion Points in brcmfmac

1. **PCIe2 Core Bring‑up:** Add a new function `brcmf_pcie2_core_init` called from `brcmf_pcie_attach` **before** firmware download, but after BAR0/2 mapping. This function should:
   - Read PCIe core revision.
   - If chip is BCM4360 and rev>3, program `BCMA_CORE_PCIE2_CLK_CONTROL`.
   - Perform LTR configuration (`bcma_core_pcie2_hw_ltr_war`).
   - Write `PCIE2_PVT_REG_PM_CLK_PERIOD`, `PCIE2_PMCR_REFUP`, `PCIE2_SBMBX`.

2. **PMU Initialization:** Add `brcmf_chip_pmu_init` called from `brcmf_chip_set_active` (or earlier). Sequence:
   - Read PMU revision (`BCMA_CC_PMU_CAP`).
   - Set `BCMA_CC_PMU_CTL` NOILPONW bit per pmurev.
   - Program PLL (`bcma_pmu_pll_init`).
   - Set PMU resource masks (`bcma_pmu_resources_init`).
   - Apply BCM4360‑specific workarounds (`bcma_pmu_workarounds`).

### 5.2 Helper Signatures (conceptual)

```c
/* pcie.c */
static void brcmf_pcie2_core_init(struct brcmf_pciedev_info *devinfo);

/* chip.c */
static void brcmf_chip_pmu_init(struct brcmf_chip_priv *chip);
static void brcmf_chip_pmu_pll_init(struct brcmf_chip_priv *chip);
static void brcmf_chip_pmu_resources_init(struct brcmf_chip_priv *chip);
```

### 5.3 Register Access Methods

- Use existing `brcmf_chip_core_read32`/`write32` for ChipCommon/PMU registers (core `BCMA_CORE_CHIPCOMMON`).
- For PCIe2 core registers, use `brcmf_pcie_read_reg32`/`write_reg32` with appropriate core‑window offset mapping.

## 6. Next Steps

1. **Implement `brcmf_pcie2_core_init`** focusing on the #1 ranked write (`PCIE2_CLK_CONTROL`).
2. **Test hypothesis:** Load modified driver, monitor if firmware advances past the initial wait loop.
3. **Add PMU initialization** if PCIe2 alone is insufficient.
4. **Iterate** through ranked writes until firmware shows TCM/D11 activity.

---
**References (File:Line)**

- `scratch/asahi-linux/drivers/bcma/driver_chipcommon_pmu.c`:274–310 (PMU early/main init)
- `scratch/asahi-linux/drivers/bcma/driver_pcie2.c`:52–155 (PCIe2 init writes)
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:?? (early‑return for 4360)
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c`:764–771 (hard‑coded RAM info)
