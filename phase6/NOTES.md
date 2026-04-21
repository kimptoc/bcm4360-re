# Phase 6: wl Clean-Room Analysis

## Goal
Identify register writes that proprietary `wl` driver performs during chip
bringup that `brcmfmac` does not, specifically between the point where
`brcmf_chip_set_active` releases ARM and where firmware reaches normal
operation.

## Methodology

1. Extract `wl.ko` from Nix store (broadcom-sta-6.30.223.271-59, kernel 6.12.80)
2. Symbol extraction via `readelf -s` → `wl_function_symbols.txt`
3. Disassembly via `objdump -d -r` to see relocation targets
4. Map relocation call-sites (e.g. `si_core_reset-0x4`) back to
   containing functions using symbol table
5. Strings extraction to identify which init-path routines touch which
   registers

Artifact: `find_callers.py` — maps relocation addresses to function names
using `wl_function_symbols.txt`.

## Findings

### WL driver structure

The `wl.ko` (7.3 MB, ELF64 x86-64, 2821 function symbols) is a **merged
driver** (not PCI-specific or PCIe-specific). It contains support for
PCI(E) chips 4350/4352/4360 via a unified path.

### Init-path call chain (from objdump relocation scan)

```
wl_pci_probe(0xc0)
  → wlc_attach(0x37d10)
      → wlc_bmac_si_attach(0x66e05)
          → si_attach(0x23844)       // SI backplane (backcompat wrapper)
      → wlc_bmac_attach(0x6984f)
          → wlc_hw_attach(0x798ff)
              → wlc_bmac_corereset(0x65e12)   ← main ARM/D11 release path
                  → si_core_reset
                      → ai_core_reset(0x1738)
                  → si_core_disable
                  → ai_iscoreup
              → wlc_bmac_radio_reset  → si_core_reset (radio path)
              → wlc_bmac_set_clk      → si_core_reset (D11 clock change)
              → wlc_bmac_up_prep      → si_core_reset (prepare before up)
              → wlc_bmac_reset         → si_core_reset (full bmac reset)
              → wlc_bmac_set_chanspec → si_core_reset (channel change)
              → wlc_bmac_process_d11rev → si_core_reset (D11 revision)
```

`wlc_bmac_corereset` is THE function that releases ARM and D11 on chip
bringup. It calls `si_core_reset` which calls `ai_core_reset`. This is
the code path that `brcmfmac`'s `brcmf_chip_set_active` replaces — but
`brcmf_chip_set_active` may NOT do the same PMU/PLL/GCI prep work that
`wlc_bmac_corereset`'s caller chain does first.

Call-site mapping — every `si_core_reset` relocation in the binary:

```
  si_core_reset callers:
    0x2023d → si_tcm_size              // TCM size detection
    0x2099e → si_socram_size           // SOC RAM size
    0x20b38 → si_socdevram_rem[...]    // DEV RAM remap
    0x20ca3 → si_socdevram_size        // DEV RAM size
    0x20dcc → si_socdevram_rem[...]    // DEV RAM remap
    0x20f2a → si_socdevram             // DEV RAM access
    0x651f1 → wlc_bmac_radio_reset     // Radio reset path
    0x65f02 → wlc_bmac_corereset       // *** MAIN CHIP CORE RESET ***
    0x66ef1 → wlc_bmac_process_d11rev  // D11 revision processing
    0x679cf → wlc_bmac_set_chanspec    // Channel spectrum change
    0x7ec1c → wlc_ol_arm_halt          // Offload ARM halt
```

Note: 6 of 11 callers are memory-size detection functions in the `si_*`
module. The 5 Bmac-level callers are the ones relevant to firmware boot.
`brcmfmac`'s `brcmf_chip_set_active` replaces only the ARM/D11 core
reset, potentially skipping the PMU/PLL/Radio prep work that happens
before `wlc_bmac_corereset` is reached.

### Call-site mapping for other key functions

```
  wlc_bmac_corereset callers:
    0x026f64 → wlc_corereset           // wlc-level core reset
    0x06605d → wlc_bmac_set_clk         // Clock change reset
    0x066561 → wlc_bmac_up_prep         // Pre-up reset
    0x066b74 → wlc_bmac_reset            // Full Bmac reset
    0x069b1d → wlc_bmac_attach           // Attach-time reset
    0x152ac6 → wlapi_bmac_corereset     // API wrapper

  wlc_bmac_si_attach callers:
    0x037d77 → wlc_attach               // Single caller

  wlc_bmac_attach callers:
    0x037f8f → wlc_attach               // Single caller

  wlc_hw_attach callers:
    0x069895 → wlc_bmac_attach           // Single caller

  si_attach callers:
    0x066e16 → wlc_bmac_si_attach        // From Bmac SI attach
    0x066e8e → wlc_bmac_process_d11rev   // From D11 revision processing
```

### do_4360_pcie2_war callers (BCM4360-specific PCIe WAR)

```
  0x1ecf9 → si_pci_sleep               // Power management sleep
  0x653a3 → wlc_bmac_4360_pcie2_war    // BMAC-level WAR, call 1
  0x653b0 → wlc_bmac_4360_pcie2_war    // BMAC-level WAR, call 2 (same fn)
```

This WAR is specific to BCM4360's PCIe2 core. `brcmfmac` does NOT call
this. Other PCIe WAR functions present in wl but absent in brcmfmac:
- `si_pci_war16165`
- `si_pcie_war_ovr_update`
- `pcie_war_ovr_aspm_update`
- `pcie_survive_perst`
- `pcie_disable_TL_fastExit`

### PMU/PLL initialization gap — THE KEY FINDING

`wl` has ~50 PMU/clock initialization functions that `brcmfmac` does NOT
call. These are organized in a clear init dependency chain:

```
Chip attach phase:
  si_pmu_chip_init        - chip-level PMU init (before any core reset)
  si_pmu_pll_init         - PLL configuration
  si_pmu_pllreset         - PLL reset sequence
  si_pll_reset            - Top-level PLL reset
  si_pmu_res_init         - Resource request/mask init
  si_pmu_init             - Main PMU init (entry point)
  si_clkctl_init          - Clock control init
  si_clkctl_xtal          - XTAL clock setup
  si_clkctl_cc            - Core clock control
  si_alp_clock            - ALP (alternate low-power) clock
  si_ilp_clock            - ILP (internal low-power) clock

Power/rail init:
  si_pmu_swreg_init       - Switching regulator init
  si_pmu_rfldo            - RF LDO configuration
  si_pmu_synth_pwrsw      - Synth power switch
  si_pmu_set_ldo_voltage  - LDO voltage setup
  si_pmu_set_switcher_voltage
  si_pmu_otp_power        - OTP power control
  si_pmu_radio_enable     - Radio power enable

Resource/timing:
  si_pmu_force_ilp        - Force ILP clock (override)
  si_pmu_gband_spurwar    - G-band spur avoidance
  si_pmu_minresmask_*     - Min resource mask setup
  si_pmu_res_req_timer_*  - Resource request timer
  si_pmu_waitforclk       - Wait for clock ready
  si_pmu_spuravoid        - Spur avoidance init
  si_pmu_update_pmu_ctrlreg - Update PMU control register
  si_pmu_chipcontrol      - Chip-level PMU control writes
  si_pmu_set_4330_pmuslowclk - Slow clock config

PCIe clock:
  si_pcieclkreq           - PCIe clock request setup
  si_pcie_ltr_war         - LTR (Latency Tolerance Reporting) WAR

PCIe core bringup:
  pcicore_hwup            - PCIe core hardware bringup
  pcicore_up              - PCIe core power-up
  pcicore_attach          - PCIe core attach
  pcicore_init            - PCIe core init
  pcicore_down            - PCIe core power-down
  pcicore_deinit          - PCIe core teardown
  pcicore_sleep           - PCIe core sleep entry
```

**Our test.188 data:** firmware flips PMU control bit-9 (0x200) then
idles with `IOSTATUS=0x00000000` for the entire 3-second observation
window. Bit-9 of `pmucontrol` is the "HT availability" request on
BCM4360. This is consistent with firmware requesting HT clock and never
getting a response because the host hasn't properly configured the PMU
resource masks or PLL before releasing ARM.

### OTP/NVRAM path

`wl` calls `otp_init`, `otp_nvread`, `otp_read_region`, and
`ipxotp_init` as part of the NVRAM loading path. `brcmfmac` uses
direct NVRAM text injection (228 B hardcoded string). The OTP init
path also configures `si_pmu_otp_power` and `si_pmu_otp_regcontrol`,
which may enable OTP-related resources in the PMU that the firmware
expects to find active.

### wl trace data (pre-existing)

Located at `phase5/logs/wl-trace/`:
- `ftrace_wl_load.txt` — function_graph trace of wl modprobe (PCI config +
  init calls, showing `pci_enable_device`, `pci_set_master`, then many
  `pci_bus_read|write_config_dword` calls that configure the endpoint)
- `post_wl_dmesg.txt` — dmesg after wl load (shows wl loaded with
  "Unpatched return thunk" warning on kernel 6.12.80)
- `post_unload_dmesg.txt` — dmesg after wl unload
- `bridge_config_diff.txt` — root port config change across wl load
  (bridge BAR config diff: bytes at 0x320-0x350 changed)
- `pre_0000_03_00_0_config.{hex,od}` — device config before wl load
- `post_0000_03_00_0_config.{hex,od}` — device config after wl load
- `pre/post_0000_00_1c_2_config` — root port config before/after wl

### What to look for next

1. **PMU/PLL initialization sequence** — specific register writes to
   ChipCommon PMU before ARM release; compare offsets against
   `brcmf_chip_set_active`
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

1. **Disassemble `si_pmu_chip_init` and `si_pmu_pll_init`** — extract
   specific register offsets and values they write before ARM release.
2. **Disassemble `wlc_bmac_corereset`** — trace the full path including
   all `si_pmu_*`, `si_gci_*`, and `pcicore_*` calls that happen before
   the ARM core reset.
3. **Compare against `brcmf_chip_set_active`** in `linux/drivers/net/
   wireless/broadcom/brcm80211/brcmfmac/chip.c` — identify each missing
   register write, its offset, its value, and its purpose.
4. **Prototype missing writes** — add them to `brcmfmac`'s chip_attach
   path before `set_active` and test.
