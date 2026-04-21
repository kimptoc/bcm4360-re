# Downstream Linux Kernel Forks and Community Patches Survey for BCM4360

## 1. List of downstream sources surveyed

*Local project analysis only — internet access unavailable for real-time survey.*

- **OpenWrt `brcmfmac` patches**: Not examined; no local copies present. OpenWrt maintains a separate `broadcom-wl` package for proprietary drivers and may have BCM4360-specific patches in their `brcmfmac` backports. (Mentioned in RESUME_NOTES.md:91 as a planned survey target.)
- **Asahi Linux `brcmfmac` patches for BCM4378/4387**: Not examined; no local copies. Asahi's BCM4387 bring‑up patches are referenced in README.md:49 as the model for this project. The upstream kernel already contains BCM4387 support (chip.c:749, pcie.c:114, etc.) but any chip‑specific PMU/PLL initialisation added by Asahi is not present in the local source tree (no `si_pmu_*` calls found in `drivers/net/wireless/broadcom/brcm80211/brcmfmac/`).
- **Broadcom SDK leaks**: Not available locally; no known SDK‑derived patches in the repository.
- **Kernel mailing list threads (BCM4360 / 14e4:43a0 / 14e4:43a2)**: Not searched.
- **Local reverse‑engineering artifacts**:
  - `phase6/NOTES.md` – clean‑room analysis of the proprietary `wl.ko` driver, listing PMU/PLL/GCI/PCIe WAR functions missing from `brcmfmac`. (Primary source for this survey.)
  - `phase3/patches/0001-brcmfmac-add-BCM4360-support.patch` – adds only device IDs and RAM‑base, no register‑level initialisation.
  - `phase3/work/linux‑6.12.80/` – upstream kernel source with BCM4387 support but no BCM4360‑specific bring‑up code.

## 2. Chip‑specific register writes missing from upstream brcmfmac

Based on the `wl` driver analysis, the following initialisation functions are present in `wl` but **absent** from upstream `brcmfmac`. Each function corresponds to one or more hardware register writes; exact offsets and values are not transcribed (clean‑room rule). The sequence follows the `wl` attach path.

| Function / register group | Offset (approx.) | Value(s) written | When in sequence | Source citation |
|---------------------------|------------------|------------------|------------------|-----------------|
| `si_pmu_chip_init`        | ChipCommon PMU   | Chip‑specific PMU enables | Before any core reset | phase6/NOTES.md:129 |
| `si_pmu_pll_init`         | PLL control registers | PLL dividers, LDO voltages | After PMU chip init | phase6/NOTES.md:130 |
| `si_pmu_pllreset`         | PLL reset bit    | Assert/de‑assert reset | Following PLL config | phase6/NOTES.md:131 |
| `si_pll_reset`            | Top‑level PLL reset | Reset pulse | After `si_pmu_pllreset` | phase6/NOTES.md:132 |
| `si_pmu_res_init`         | PMU resource request/mask registers | `min_res_mask`, `max_res_mask` | Before ARM release | phase6/NOTES.md:133 |
| `si_pmu_init`             | PMU control register | PMU global enable | After resource masks | phase6/NOTES.md:134 |
| `si_clkctl_init`          | Clock‑control registers | Core clock source selection | Early in attach | phase6/NOTES.md:135 |
| `si_clkctl_xtal`          | XTAL oscillator control | XTAL enable, bias | After clock‑control init | phase6/NOTES.md:136 |
| `si_clkctl_cc`            | ChipCommon clock control | CC clock divider | After XTAL ready | phase6/NOTES.md:137 |
| `si_alp_clock` / `si_ilp_clock` | ALP/ILP clock registers | Low‑power clock enables | Before ARM release | phase6/NOTES.md:138‑139 |
| `si_pmu_swreg_init`       | Switching regulator control | Regulator enable/voltage | Power‑rail setup | phase6/NOTES.md:142 |
| `si_pmu_rfldo`            | RF LDO control   | LDO bias, voltage | After regulator init | phase6/NOTES.md:143 |
| `si_pmu_synth_pwrsw`      | Synthesizer power switch | Power‑gate control | Before radio enable | phase6/NOTES.md:144 |
| `si_pmu_set_ldo_voltage`  | LDO voltage register | Voltage setting | Per‑rail tuning | phase6/NOTES.md:145 |
| `si_pmu_set_switcher_voltage` | Switcher voltage register | Voltage setting | Per‑rail tuning | phase6/NOTES.md:146 |
| `si_pmu_otp_power`        | OTP power control | OTP power enable | Before OTP read | phase6/NOTES.md:147 |
| `si_pmu_radio_enable`     | Radio power gate | Radio power on | After all rails stable | phase6/NOTES.md:148 |
| `si_pmu_force_ilp`        | ILP force bit    | Force ILP clock (override) | After clock ready | phase6/NOTES.md:151 |
| `si_pmu_gband_spurwar`    | Spur‑avoidance registers | G‑band spur mitigation | After radio enable | phase6/NOTES.md:152 |
| `si_pmu_minresmask_*`     | PMU min‑resource mask | Mask of always‑on resources | Before ARM release | phase6/NOTES.md:153 |
| `si_pmu_res_req_timer_*`  | Resource‑request timer | Timer value for HT request | Before ARM release | phase6/NOTES.md:154 |
| `si_pmu_waitforclk`       | Clock‑ready poll register | Wait for clock stable | After PLL config | phase6/NOTES.md:155 |
| `si_pmu_spuravoid`        | Spur‑avoidance control | Spur‑avoid enable | After radio enable | phase6/NOTES.md:156 |
| `si_pmu_update_pmu_ctrlreg` | PMU control register | Update PMU control bits | After resource masks | phase6/NOTES.md:157 |
| `si_pmu_chipcontrol`      | ChipControl register | Chip‑level PMU writes | Late attach | phase6/NOTES.md:158 |
| `si_pmu_set_4330_pmuslowclk` | Slow‑clock register | Slow‑clock divider | After PMU init | phase6/NOTES.md:159 |
| `si_pcieclkreq`           | PCIe clock‑request register | Clock‑request enable | PCIe core bring‑up | phase6/NOTES.md:162 |
| `si_pcie_ltr_war`         | LTR WAR register | Latency‑tolerance fix | PCIe core bring‑up | phase6/NOTES.md:163 |
| `pcicore_hwup`            | PCIe core hardware‑up | Core power‑up sequence | Before ARM release | phase6/NOTES.md:166 |
| `pcicore_up`              | PCIe core power‑up | Core enable | After `pcicore_hwup` | phase6/NOTES.md:167 |
| `pcicore_attach`          | PCIe core attach | Core configuration | After `pcicore_up` | phase6/NOTES.md:168 |
| `pcicore_init`            | PCIe core init | Core initialisation | After attach | phase6/NOTES.md:169 |
| `do_4360_pcie2_war`       | PCIe2 WAR registers | BCM4360‑specific PCIe2 work‑around | Before PCIe core enable | phase6/NOTES.md:110‑111 |
| `si_pci_war16165`         | PCI WAR 16165 register | Legacy PCI work‑around | Early PCI config | phase6/NOTES.md:116 |
| `si_pcie_war_ovr_update`  | PCIe WAR override | Override update | After PCIe core init | phase6/NOTES.md:117 |
| `pcie_war_ovr_aspm_update`| ASPM WAR override | ASPM configuration | After PCIe core init | phase6/NOTES.md:118 |
| `pcie_survive_perst`      | PERST survival register | Survive PERST assertion | Early PCIe bring‑up | phase6/NOTES.md:119 |
| `pcie_disable_TL_fastExit`| TL fast‑exit disable | Disable fast exit | Early PCIe bring‑up | phase6/NOTES.md:120 |
| `si_gci_init`             | GCI control registers | General Chip Interface init | After PMU, before ARM release | phase6/NOTES.md:211 |
| `otp_init` / `otp_nvread` | OTP control registers | OTP power, read sequence | After PMU OTP power | phase6/NOTES.md:184‑187 |

**Note:** Offsets and exact values are not listed in accordance with clean‑room rules. The above table documents *which* register groups are touched, not the precise instruction stream. The `wl` driver analysis shows that all these functions are called before `wlc_bmac_corereset` (the equivalent of `brcmf_chip_set_active`), whereas `brcmfmac` calls none of them.

## 3. Specific look‑for items (as requested)

### PMU resource requests (`si_pmu_res_request`)
- **Purpose:** Configures the PMU resource mask that determines which clocks/power rails are available to firmware.
- **Evidence:** Firmware flips PMU control bit‑9 (HT availability request) and spins waiting for HT clock (phase6/NOTES.md:175‑180). This indicates the host never set the resource mask that grants HT clock.

### PLL init (`si_pmu_pll_init`)
- **Purpose:** Programs PLL dividers, LDO voltages, and lock parameters for the core (ARM) and D11 MAC clocks.
- **Evidence:** Without PLL init, the D11 MAC clock‑control status bit (`d11.clk_ctl_st`) never transitions to “HT” mode, causing firmware to hang at function 0x1415c (phase5/logs/…).

### PCIe WARs (`do_4360_pcie2_war` and variants)
- **Purpose:** Work‑arounds for BCM4360’s PCIe2 core errata.
- **Evidence:** The `wl` driver calls `do_4360_pcie2_war` twice via `wlc_bmac_4360_pcie2_war` (phase6/NOTES.md:110‑111). `brcmfmac` has no equivalent.

### GCI/OTP init
- **Purpose:** Initialises General Chip Interface and OTP (one‑time programmable) memory power/read interface.
- **Evidence:** `wl` calls `si_gci_init` and `otp_init`; `brcmfmac` uses a hard‑coded NVRAM string and skips OTP power‑up (phase6/NOTES.md:184‑187).

### Backplane clock setup
- **Purpose:** Configures the backplane (ALP/ILP) clocks before releasing ARM.
- **Evidence:** `si_alp_clock` and `si_ilp_clock` are listed in the PMU/clock init chain (phase6/NOTES.md:138‑139). Missing in `brcmfmac`.

## 4. Rank findings by likelihood of being the missing prerequisite

1. **PMU resource‑mask and PLL init (highest likelihood)** – Firmware explicitly requests HT clock (PMU control bit‑9) and spins waiting for `d11.clk_ctl_st` to indicate HT clock ready. This is a direct clock‑gate dependency; without the host programming the PMU resource mask and starting the PLL, the firmware can never proceed.
2. **PCIe2 core WARs (medium likelihood)** – BCM4360‑specific PCIe2 errata work‑arounds may be required for the PCIe core to respond correctly to MMIO accesses after ARM release. Missing WARs could cause silent MMIO timeouts or corrupt reads/writes that stall firmware.
3. **GCI/OTP init (lower likelihood)** – OTP power‑up may be needed for NVRAM reads, but `brcmfmac` already supplies NVRAM via a host‑side string. GCI init may be required for certain chip‑control features, but firmware may still boot without it.
4. **Backplane clock setup (lowest likelihood)** – ALP/ILP clocks are likely derived from the same PMU/PLL configuration; if the PLL is not running, these clocks are also absent. Fixing the PMU/PLL likely resolves this.

## 5. Recommended next step

Implement the missing PMU resource‑mask and PLL initialisation sequence in `brcmfmac` by:
1. Disassembling `si_pmu_res_init` and `si_pmu_pll_init` from `wl.ko` to extract register offsets and values (clean‑room: observe behavior, document in plain language, then implement).
2. Adding a BCM4360‑specific `brcmf_pmu_init` function that calls the equivalent of `si_pmu_chip_init`, `si_pmu_pll_init`, `si_pmu_res_init`, and `si_pmu_init` before `brcmf_chip_set_active`.
3. Testing with the existing phase‑5 monitoring framework to verify that firmware now sees HT clock available and proceeds past the spin loop at function 0x1415c.

---
*Survey performed using local project artifacts only; internet‑based downstream sources were not accessible at the time of writing.*
