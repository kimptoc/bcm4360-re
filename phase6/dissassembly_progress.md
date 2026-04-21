# BCM4360 Disassembly & Bring-up Progress

## Status Summary (2026-04-21)
The primary blocker for BCM4360 firmware execution in `brcmfmac` has been identified as a critical gap in **PMU (Power Management Unit) and PLL (Phase-Locked Loop)** initialization. While `brcmfmac` currently attempts a "generic" ARM release, the chip remains in a low-power state with its main high-speed clocks (HT) gated.

**Strategy Shift:** We are pausing further surgical disassembly of `wl.ko` PMU/PLL logic. Instead, we are pivoting to the **GPL-licensed `bcma` driver** as our primary reference for BCM4360 bring-up writes. DeepSeek is currently generating a register-level gap analysis between `bcma` and `brcmfmac` (expected at `phase6/bcma_gap_analysis.md`).

## Key Findings

### 1. Confirmed Root Cause: Clock Stalls
`test.188` logs and `RESUME_NOTES.md` confirmed that after the ARM CR4 is released (CPUHALT YES→NO), the firmware immediately spins at address `0x1415c`. 
- **Evidence:** `pmucontrol` bit 9 (HT request) is set by firmware, but never acknowledged by the hardware.
- **Reference:** `phase5/logs/test.188.journalctl.txt` shows `HT=NO` throughout the 3000ms monitoring window.

### 2. Implementation Reference: bcma Driver
The `bcma` driver contains explicit support for BCM4360 (PMU rev-17 / ChipCommon rev-43) which can be ported directly without clean-room barriers:
- **PCIe2 WARs:** `drivers/bcma/driver_pcie2.c` (line 170) contains BCM4360-specific initialization.
- **PMU/PLL/Resource Masks:** `drivers/bcma/driver_chipcommon_pmu.c` handles the masks and clock-gate logic.

## Planned Next Steps

### Step 1: Review DeepSeek Gap Analysis
Wait for `phase6/bcma_gap_analysis.md`. This table will identify every register write `bcma` performs that `brcmfmac` currently misses.

### Step 2: Narrowed wl Disassembly
Disassemble `wl.ko` **only** for areas `bcma` does not cover:
- Exact timing/handshake for the bit-9 HT resource grant.
- Interaction between PMU and NVRAM/OTP power domains.
- BCM4360-specific spur-avoidance tables (if rev-17 requires it).

### Step 3: Implement Integrated Init Sequence
Port the identified writes into a new BCM4360-specific initialization path in `brcmfmac`. This will combine the `bcma` logic with any residual `wl`-specific findings.

### Step 4: Boot Sequence Reordering
Modify `brcmf_chip_set_active` to ensure the PMU/PLL/PCIe sequence is fully completed *before* the ARM core's reset is de-asserted.

### Step 5: Validation (test.189)
Use the phase 5 monitoring framework to verify:
1. `pmustatus` shows `HAVEHT=YES`.
2. Firmware advances past the spin-loop at `0x1415c`.
3. TCM shared-memory pointers are written by the firmware.
