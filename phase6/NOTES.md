# Phase 6: wl Clean-Room Analysis

## Goal
Identify register writes that proprietary `wl` driver performs during chip
bringup that `brcmfmac` does not, specifically between the point where
`brcmf_chip_set_active` releases ARM and where firmware reaches normal
operation.

## Findings so far

### WL driver structure

The `wl.ko` from broadcom-sta-6.30.223.271-59 (kernel 6.12.80, 7.3MB)
is a **merged driver** (not PCI-specific or PCIe-specific). It contains
support for PCI(E) chips 4350/4352/4360 via a unified path.

Key init call chain (derived from symbol analysis):
```
wl_pci_probe
  → wl_attach
    → wlc_attach
      → wlc_bmac_si_attach
        → si_attach              /* SI backplane (backcompat wrapper) */
      → wlc_bmac_attach
        → wlc_hw_attach
          → wlc_bmac_corereset   /* Core reset (including D11/ARM) */
          → wlc_bmac_radio_reset
          → wlc_bmac_set_clk
          → wlc_bmac_up_prep
          → wlc_bmac_process_d11rev
          → wlc_bmac_set_chanspec
```

### Critical observation: PMU/PLL initialization gap

`wl` has extensive PMU initialization functions that `brcmfmac` does NOT
call:
```
si_pmu_chip_init
si_pmu_pll_init
si_pmu_res_init
si_pmu_init
si_pmu_force_ilp
si_pmu_gband_spurwar
si_pmu_minresmask_*
si_pmu_res_req_timer_*
si_pmu_set_4330_pmuslowclk
si_pmu_waitforclk
si_pmu_spuravoid
si_pmu_update_pmu_ctrlreg
si_pmu_chipcontrol
```

Our test.188 data shows firmware flips PMU control bit-9 (0x200) then
idles. This is consistent with firmware doing a resource request (PMU
slow-clock or HT-availability wait) and never getting a response because
the host hasn't configured the PMU/PLL correctly.

### PCIe2 WAR for BCM4360

`wl.ko` contains `do_4360_pcie2_war` which is called from:
- `si_pci_sleep` (power management)
- `wlc_bmac_4360_pcie2_war` (BMAC-level WAR)

This WAR is specific to BCM4360's PCIe2 core. `brcmfmac` does NOT call
this.

### OTP/NVRAM path

`wl` calls `otp_init` and `otp_nvread` as part of the NVRAM loading path.
`brcmfmac` uses direct NVRAM text injection (228 B hardcoded string).
The `wl` OTP path may set up additional chip state that our NVRAM bypass
skips.

### What to look for next

1. **PMU/PLL initialization sequence** — specific register writes to
   ChipCommon PMU before ARM release
2. **si_gci_init** — GCI (General Chip Interface) init
3. **pcicore_up / pcicore_hwup** — PCIe core bringup sequence
4. **si_pcieclkreq** — PCIe clock request setup
5. **BCDC ring init** — firmware/handshake ring setup

### OpenWrt / Asahi / SDK patch survey (Option F)

Deferred pending initial wl analysis. Would look for BCM4360-specific
patches in:
- OpenWrt `brcmfmac` patches
- Asahi Linux `brcmfmac` patches for BCM4378/4387
- Broadcom SDK (if available)

## Next Steps

1. **Disassemble the PMU init path** — look at `si_pmu_chip_init` and
   `si_pmu_pll_init` specifically, comparing register offsets and values
   against what brcmfmac does.
2. **Trace the ARM release path** — from `wlc_bmac_corereset` through
   `wlc_hw_attach` to find what PMU/PLL registers are touched before
   ARM is released.
3. **Compare against brcmfmac's path** through `brcmf_chip_set_active`
   and identify missing writes.
