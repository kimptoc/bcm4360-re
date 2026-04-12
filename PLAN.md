# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by reverse-engineering the host-to-firmware protocol used by the proprietary `wl` driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded, giving us the ability to trace driver behaviour, read hardware registers, and compare against the existing `brcmfmac` codebase.

## Current Status

**Phase 1 is complete.** Phase 1 analysis revealed that the BCM4360 is architecturally near-identical to the already-supported BCM43602 — same ARM CR4 CPU, same PCIe Gen2 core, same BCMA backplane. A minimal brcmfmac patch adding PCI/chip IDs, TCM rambase, and firmware mappings has been written, a build system exists, and testing instructions are documented.

**The project has moved directly to patched brcmfmac bring-up** (Phase 3), bypassing MMIO tracing (Phase 2). The central question is now:

> **How far does the real probe get, and where exactly does it fail?**

The answer determines whether this is a small compatibility gap or a deeper reverse-engineering effort.

---

## Phase 1: Reconnaissance ✅ COMPLETE

### 1.1 — Enumerate BCMA backplane cores ✅
**Result:** 9 cores identified — ARM CR4 (rev 2), D11 (rev 42), PCIe Gen2 (rev 1), ChipCommon (rev 43), USB 2.0 Device, plus ARM infrastructure cores. Layout is very similar to brcmfmac-supported chips.

See: `phase1/notes/core_enumeration_analysis.md`

### 1.2 — Extract firmware from `wl.ko` ✅
**Result:** Two firmware variants extracted — `4352pci` (432KB) and `4350pci` (435KB), both version 6.30.223.0 (Dec 2013). Thumb-2 ARM binaries running hndrte RTOS. Firmware contains both `bcmcdc.c` and `pciedev_msg.c` references — BCDC encapsulation within PCIe dongle messaging.

See: `phase1/notes/firmware_extraction_analysis.md`

### 1.3 — Study brcmfmac source for supported chip patterns ✅
**Result:** BCM4360 needs only ~10 lines of code to add to brcmfmac: PCI device ID, chip ID, TCM rambase (0x180000), and firmware name mapping. The biggest unknown is the shared memory protocol version (must be 5-7 for msgbuf).

See: `phase1/notes/brcmfmac_analysis.md`

---

## Phase 2: MMIO Tracing (fallback — use if Phase 3 hits a wall)

> **Note:** This phase was originally the planned path before attempting brcmfmac. Since Phase 1 analysis showed the chip is close to supported chips, the project jumped directly to Phase 3. MMIO tracing remains available as a diagnostic tool if the patched module fails in ways that can't be diagnosed from dmesg alone.

### 2.1 — Trace `wl` driver MMIO access during initialization
**Goal:** Capture the complete register read/write sequence during `wl` module load.

**Method:** Unload and reload `wl` with `mmiotrace` or `ftrace` on `ioread32`/`iowrite32`.

**When to use:** If Phase 3 produces failures related to chip initialization, register access patterns, or undocumented hardware behavior.

**Risk:** Moderate — requires reloading WiFi driver. USB adapter provides backup connectivity.

### 2.2 — Trace `wl` during scan, associate, and data transfer
**Goal:** Capture host-firmware command/response protocol for key WiFi operations.

**When to use:** If the chip probes successfully but protocol-level operations fail (scan, associate, data path).

### 2.3 — Compare traced patterns against brcmfmac msgbuf protocol
**Goal:** Determine whether BCM4360 uses standard `msgbuf` or a variant.

**When to use:** If protocol version mismatch or unexpected message formats are observed.

---

## Phase 3: Patched brcmfmac Bring-up ← CURRENT PHASE

This is now the primary path. A proof-of-concept patch exists; the focus is on running a clean test and capturing results.

### 3.1 — Rebuild module against exact running kernel ✅
**Goal:** Eliminate kernel version mismatch as a failure mode.

**Status:** Complete. Host kernel updated to 6.12.80, matching module vermagic. Out-of-tree Makefile rewritten to compile the full brcmfmac source tree (all bus backends, protocols, platform modules) and the WCC vendor module, matching the running kernel config. BCM4360/4352 patch applied to pcie.c (chip.c and brcm_hw_ids.h were already patched).

**Output:** `phase3/output/brcmfmac.ko` and `phase3/output/brcmfmac-wcc.ko` with correct vermagic and BCM4360 device aliases.

### 3.2 — Prepare firmware and NVRAM files
**Goal:** Ensure the correct firmware layout is in place before testing.

**Method:** See the firmware workstreams tracker (`phase3/notes/firmware_workstreams.md`) for the full status of each component:
- **Firmware binary** — place extracted firmware as `/lib/firmware/brcm/brcmfmac4360-pcie.bin`
- **NVRAM** — determine source (SPROM, extracted, or none) and place as `.txt` if available
- **CLM blob** — determine if needed and provide if so

**Output:** Complete `/lib/firmware/brcm/` layout documented in test results.

### 3.3 — Run first real test and capture results
**Goal:** Load the patched module and determine exactly where probe succeeds or fails.

**Method:**
1. Switch to USB WiFi adapter for connectivity
2. Unload `wl` driver
3. Load patched `brcmfmac.ko` and `brcmfmac-wcc.ko`
4. Capture full `dmesg` output

**Output:** Full logs saved to `phase3/results/`, with a summary of the exact failure point:
- Module load failure
- Firmware load failure
- NVRAM missing
- Protocol version mismatch
- Dongle setup failure
- Interface successfully created

See: `phase3/notes/testing_instructions.md`

### 3.4 — Analyze results and iterate
**Goal:** Based on the first test, determine the next action.

**Decision tree:**
- **Protocol version mismatch** → investigate firmware's shared memory format, may need Phase 2 tracing
- **Firmware load failure** → check firmware format (TRX header?), try alternate variant
- **NVRAM missing** → extract from SPROM or `wl` driver
- **Dongle setup failure** → firmware loaded but init handshake failed, investigate with tracing
- **Interface created** → proceed to Phase 4

---

## Phase 4: Driver Development and Upstreaming

### 4.1 — Validate and harden the patch
**Goal:** Move from proof-of-concept to review-ready patch.

**Actions:**
- Separate BCM4360 and BCM4352 support unless both are strictly needed
- Regenerate patch from a clean kernel tree (not from approximate hunks)
- Update commit message with observed runtime behavior
- Add any chip-specific quirks discovered during testing
- Handle any BCM4360-specific initialization (e.g., USB core disable)

### 4.2 — Test basic functionality
**Goal:** Verify scanning, association, and data transfer work.

**Method:** Load patched brcmfmac, scan for networks, connect, run throughput tests.

**Output:** Test results, any remaining issues documented.

### 4.3 — Submit upstream
**Goal:** Get the patch accepted into the Linux kernel.

**Method:** Submit to `linux-wireless@vger.kernel.org` and `brcm80211@lists.linux.dev`, CC Arend van Spriel. Follow kernel patch submission process.

**Output:** BCM4360 support in mainline Linux.

---

## Patch Assumptions

The current proof-of-concept patch makes several assumptions that need validation. See `phase3/notes/patch_assumptions.md` for the full list with evidence and verification status.

Key assumptions:
- BCM4360 behaves like BCM43602-family chips
- TCM rambase = `0x180000`
- Firmware mapping `brcmfmac4360-pcie` is sufficient for probe
- The extracted firmware uses msgbuf-compatible shared memory protocol (version 5-7)

---

## Tools and Environment

- **OS:** NixOS, kernel 6.12.x
- **Target device:** BCM4360 at PCI 03:00.0
- **Backup connectivity:** USB WiFi adapter (MT76x2u) at wlp0s20u2
- **Languages:** Python (probing/analysis scripts), C (kernel module work)
- **Key tools:** `ftrace`, `mmiotrace`, `trace-cmd`, `binwalk`, `objdump`, `readelf`, Ghidra (firmware analysis)

## Success Criteria

- BCM4360 works with `brcmfmac` (scan, connect, transfer data)
- No proprietary code in the driver (firmware is loaded as a separate binary, same as other brcmfmac chips)
- Patch accepted upstream or viable for out-of-tree use
- Documented protocol for community reference
