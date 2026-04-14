# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by reverse-engineering the host-to-firmware protocol used by the proprietary `wl` driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded, giving us the ability to trace driver behaviour, read hardware registers, and compare against the existing `brcmfmac` codebase.

## Current Status (updated 2026-04-14, post test.14)

**Phases 1, 3, and 4 (partial) are complete. Phase 5 is active.**

Phase 5 uses brcmfmac as a **debug/bring-up harness** to boot and introspect the
BCM4360 firmware. Firmware download works reliably. ARM release crashes the host PC.

**Current blockers (two related issues):**

1. **ARM release crashes PC** — every ARM release since test.7 instantly kills the
   host. Tests 8-14 tried: bus mastering on/off, AER/SERR masking, early IRQ handlers,
   INTx disable, stripping all PCIe safety. All crash. The only safe operation is
   firmware download without ARM release (test.12a PASS).

2. **Firmware ASSERTs at hndarm.c:397** (HT clock timeout) — observed in test.7
   (the ONLY successful ARM release). The firmware starts, completes `si_kattach`,
   then ASSERTs ~14.5s later. This ASSERT may trigger behavior that crashes the host.

### Crash investigation summary (tests 7-14)

| Test | Config | Result |
|------|--------|--------|
| 7 | bus_master OFF, no PCIe safety | **PASS** (FW ran, ASSERT, no PC crash) |
| 8-10 | various PMU/watchdog changes | CRASH |
| 11 | identical to test.7 | CRASH |
| 12a | skip ARM release | PASS |
| 12b | AER/SERR masking | CRASH |
| 13 | early IRQ + INTx disable | CRASH |
| 14 | bus_master ON, no PCIe safety | CRASH |

**Bus mastering hypothesis DISPROVED** by test.14 — crash occurs with bus mastering
both enabled and disabled. Something environmental changed between test.7 and test.11+.

**Key discovery:** The `wl` proprietary driver **fails to load** on kernel 6.12.80
("Unpatched return thunk" error). Cannot be used as a reference on this system.

> **Central question: Why does ARM release crash the PC, and what was different about test.7?**

See GitHub issue #9 for architectural assessment.

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

## Phase 3: Patched brcmfmac Bring-up ✅ COMPLETE

A proof-of-concept brcmfmac patch was built and tested through 10 diagnostic iterations.

### 3.1 — Rebuild module against exact running kernel ✅
Module built against kernel 6.12.80 with BCM4360/4352 patches applied.

### 3.2 — Prepare firmware and NVRAM files ✅
Firmware extracted from macOS `wl.ko`: `brcmfmac4360-pcie.bin` (442,233 bytes, v6.30.223.0).
No NVRAM `.txt` file available. CLM blob not needed for basic bring-up.

### 3.3 — Diagnostic testing (10 iterations) ✅

| Test | Result |
|---|---|
| Test 1 (diag.1-2) | Crash — rambase 0x180000 wrong, corrected to 0x0 |
| Test 2 (diag.3) | BAR2 reads OK — TCM at offset 0, 640KB accessible |
| Test 3 (diag.4) | B-bank (idx 4) access hangs PCIe bus |
| Test 4 (diag.5-7) | A-banks powered on, full BAR2 map characterized |
| Test 5 (diag.8) | Single u32 TCM write OK, ARM halt confirmed |
| Test 6 (diag.9) | Bulk iowrite32 OK (256KB), memcpy_toio hangs |
| Test 7 (diag.10-11) | FW download OK, ARM release crashes host |
| Test 8 (diag.12) | Safe abort — FW download verified end-to-end, no crash |
| Test 9 (diag.13) | BCM43602 msgbuf FW — no crash, init timeout |
| Test 10 (diag.14) | BCM43602 FW with timeout logging — confirmed 5s timeout |

### 3.4 — Phase 3 Conclusion

**All driver-side code is working.** The sole blocker is firmware protocol incompatibility:

- BCM4360 firmware uses **BCDC protocol** (bcmcdc.c, rtecdc.c, pciedngl_*)
- brcmfmac PCIe backend requires **msgbuf protocol** (shared ring buffers, version 5-7)
- No msgbuf-compatible firmware exists for BCM4360 (chip predates msgbuf)
- BCM43602 msgbuf firmware loads without crash but can't drive BCM4360 hardware (different D11 core rev 42 vs 44)

Key hardware discoveries:
- BAR2 maps TCM at offset 0 (2MB window, only 640KB populated)
- ARM CR4: 4 A-banks (128KB each) + 1 B-bank (must NOT access via BANKIDX)
- BCM4360 requires 32-bit iowrite32 only — memcpy_toio (64-bit rep movsq) hangs PCIe bus
- `brcmf_pcie_memcpy_toio32()` helper added for 32-bit firmware download

See: `phase3/results/diagnostic_findings.md`, `phase3/logs/diag.1-14`

---

## Phase 4: BCDC-over-PCIe Host Transport ✅ PARTIALLY COMPLETE

Phase 3 proved the driver-side PCIe bring-up works. The blocker is that brcmfmac speaks
msgbuf but the BCM4360 firmware speaks BCDC. This phase investigated whether a BCDC-over-PCIe
host transport can be built to communicate with the existing BCM4360 firmware.

See: GitHub issue #4 for the original proposal.

**Phase 4 Outcome:** The standalone test harness (Phase 4B) proved firmware download and
ARM release work, but the firmware crashes the host ~100-200ms after ARM release — likely
due to firmware writing to PCIe control registers or initiating DMA without host-side rings
being set up. The decision was made to pivot to Phase 5 (patching brcmfmac directly) since
brcmfmac already handles interrupt registration, DMA setup, and chip lifecycle properly.

### 4A — Transport Discovery

**Goal:** Understand how BCDC is transported over PCIe by reverse-engineering the `wl` driver.

#### 4A.1 — Static analysis of `wl.ko`
Disassemble/decompile `wl.ko` to identify PCIe init functions, register definitions,
doorbell/mailbox offsets, DMA ring setup, and BCDC transport code. The module has symbols,
so this should be productive. This can shortcut or guide the live tracing work.

#### 4A.2 — Firmware binary analysis
Deeper analysis of BCM4360 firmware strings and binary structure. We already found
`bcmcdc.c`, `rtecdc.c`, `pciedngl_*`. Look for shared memory layout definitions,
ring descriptors, doorbell offsets, and handshake sequences the firmware expects.

#### 4A.3 — Live tracing of `wl` driver
Trace `wl` with `mmiotrace`/`ftrace` during:
- Firmware release (ARM start)
- Initial handshake
- Interface creation
- First scan

Capture: MMIO register accesses (doorbells/mailboxes), interrupt behavior, DMA/ring
setup, first host→firmware and firmware→host messages.

**Deliverable:** Document describing boot handoff sequence, control path structure,
data path (if observable), interrupt model, and buffer ownership rules.

### 4B — Minimal PCIe + Firmware Harness

**Goal:** Prove controlled host ↔ firmware communication.

Build a minimal standalone kernel module that:
- Reuses Phase 3 proven code: PCIe mapping, TCM access, iowrite32 path, ARM CR4 control
- Loads firmware and releases ARM
- Registers an interrupt handler (even a stub that acks and logs) **before** ARM release —
  the wl firmware fires interrupts/DMA immediately, which is what crashed us in Phase 3
- Performs a single control exchange based on Phase 4A findings
- Logs all interactions

**Success criteria:**
- Firmware runs without crashing host
- At least one control message exchanged successfully
- Responses are stable and repeatable

### 4C — Minimal BCDC Control Implementation

**Goal:** Implement enough BCDC functionality for basic WiFi interaction.

Implement:
- BCDC command framing (request/response)
- Query firmware version
- Query MAC address
- Bring interface up/down
- Trigger scan

**Success criteria:**
- Commands return valid responses
- Interface can be brought up
- Scan completes or produces expected output

### 4D — Integration Decision

Based on Phase 4C results, choose direction:

**Option 1: Standalone out-of-tree driver**
- Clean architecture, avoids brcmfmac constraints
- Faster to iterate on, but no shared code reuse

**Option 2: Extend/fork brcmfmac**
- Reuse shared code (chip recognition, BCMA, firmware loading)
- Add alternate PCIe protocol path alongside msgbuf
- Harder to land upstream but more maintainable long-term

### Key Risks

- PCIe transport may be more complex than BCDC-over-USB (the well-understood path)
- `wl` firmware may rely on opaque driver-specific setup during init
- DMA/interrupt behavior may cause instability under load
- Data path (actual WiFi frames) will be significantly harder than control path
- The control path may work but data path may prove infeasible

---

## Phase 5: BCM4360 Bring-up via brcmfmac ← CURRENT PHASE

> **Important:** brcmfmac is being used as a **debug/bring-up harness**, not
> necessarily as the final driver architecture. Phase 4A concluded BCM4360
> behaves as a SoftMAC/offload device. The final driver may require a different
> approach (host-driven MAC/D11). See "Architecture Tracks" below.

### Architecture Tracks

**Track A — brcmfmac as debug harness (current focus):**
- Used for firmware boot, introspection, and ASSERT investigation
- Leverages brcmfmac's PCIe lifecycle, interrupt, and DMA handling
- May not reflect final driver architecture

**Track B — Driver architecture direction (deferred):**
- SoftMAC/offload model still under consideration (Phase 4A findings)
- May require host-driven MAC/D11 implementation
- Architecture decision depends on ASSERT investigation outcomes

### 5.1 — Basic chip support patches ✅ COMPLETE

Patches applied to 3 files (brcm_hw_ids.h, pcie.c, chip.c):
- PCI device ID 14e4:43a0, chip ID 0x4360
- Firmware mapping `brcmfmac4360-pcie`
- rambase=0 (BAR2 maps TCM directly, no offset)
- 32-bit iowrite32 for firmware/NVRAM download (memcpy_toio hangs BCM4360)
- NULL-check INTERNAL_MEM core in exit_download_state (BCM4360 has no such core)
- Enter/exit download state handlers (same as BCM43602 — ARM CR4)

**Result:** Firmware downloads, ARM boots to early init, then **asserts at
hndarm.c:397** (HT clock timeout). This is NOT a clean boot — the firmware
reaches `si_kattach` and emits console output but fails during ARM init.

### 5.2 — Firmware boot stability & ASSERT investigation ← CURRENT

Iterative work to stabilize early boot and diagnose the ASSERT:

**Completed work:**
- Added TCM/console/sharedram debug dumps for firmware introspection
- Added NVRAM debug logging
- Disabled bus mastering before ARM release (prevents firmware DMA crash)
- Disabled ASPM L0s/L1 before ARM release (prevents PCIe link interference)
- (test.8/test.9) Allow watchdog reset, then re-init PMU/HT clock — **both crashed PC**
- (test.10) Skip watchdog reset entirely, preserve EFI state — **also crashed PC**

**Test log:**
| Test | Approach | Result |
|------|----------|--------|
| test.7 | bus mastering disabled, watchdog allowed | ASSERT hndarm.c:397, no crash |
| test.8 | + PMU debug logging, + ForceHT post-reset | **Crashed PC** (no log) |
| test.9 | same as test.8 (committed at 3d96dbc) | **Crashed PC** (no log) |
| test.10 | skip watchdog reset entirely (committed 72235c4) | **Crashed PC** (no log) |
| test.11 | revert to test.7 safe baseline (a3dbbb3) | **Crashed PC** — journal captured up to ARM release |
| test.12a | skip ARM release (bcm4360_skip_arm=1) | **PASS** — FW download verified, no crash |
| test.12b | PCIe AER/SERR masking before ARM release | **Crashed PC** (no log) |
| test.13 | early IRQ handler + INTx disable | **Crashed PC** (no log) |
| test.14 | bus mastering ON, no PCIe safety | **Crashed PC** — bus mastering hypothesis disproved |
| test.15 | ForceHT before ARM release | **Crashed PC** — HT_AVAIL already set (0x10000), ForceHT was no-op |

**Key conclusions from test.8–15:**
- All tests that release the ARM crash the PC (tests 8-15)
- Skipping ARM release (test.12a) is safe
- Bus mastering on/off doesn't matter (test.14 vs earlier tests)
- PCIe error masking doesn't help (test.12b)
- IRQ handlers don't help (test.13)
- ForceHT irrelevant — HT_AVAIL already set before ARM release (test.15)
- **test.7 was the ONLY success — run at uptime ~6041s after 6 prior module loads**

**Warm-up hypothesis:** test.7 succeeded because prior module load/unload cycles
left PCIe device config in a beneficial state. Fresh-boot state is hostile.

**Current test (test.16): warm-up + PCIe config diff**
1. Dump cold PCIe config space (lspci -xxx)
2. Load with skip_arm=1 (safe), wait for probe, unload
3. Dump warm PCIe config space, diff against cold
4. Flush all state to disk
5. Load again WITHOUT skip_arm (ARM release attempt)
6. If succeeds: the diff shows which config registers matter
7. If crashes: warm-up hypothesis disproved, move to next approach

**Remaining next steps (if warm-up fails):**
1. **MMIO trace of `wl` driver** — trace what PCIe setup `wl` does before ARM
   release. The `wl` driver loads this firmware successfully, so it must set up
   the PCIe environment correctly. Key question: what does `wl` do that we don't?
2. **Consider firmware DMA region setup** — `wl` may pre-allocate DMA buffers
   and write their addresses to shared memory before ARM release. The firmware
   may immediately attempt DMA to an expected host address on boot.
3. **Try `pci=nomsi,noaer` kernel parameters** — boot with PCIe error handling
   fully disabled at kernel level, not just per-device
4. **Try keeping interrupts registered** — the firmware may fire an interrupt
   immediately, and with no handler the CPU takes an unhandled interrupt/NMI
5. **Consider virtual machine isolation** — run the test in a VM with PCIe
   passthrough so the crash doesn't take down the host

**⚠ Note:** Previous hypotheses about "BCDC vs msgbuf" as the primary blocker
may be premature. The firmware ASSERTs before reaching any protocol handshake.
The immediate blocker is the firmware's inability to complete its own init.

### 5.3 — Firmware protocol bridge

Once firmware boots past the ASSERT, establish communication:

1. **Investigate firmware's post-boot behavior** — read TCM shared memory region
   to see if firmware wrote anything (BCDC shared info structure, etc.)
2. **Add BCDC-over-PCIe transport to brcmfmac** — bypass msgbuf, use the BCDC
   protocol that the firmware expects (similar to how brcmfmac handles USB/SDIO)
3. **Trace wl driver handshake** — use mmiotrace to capture what wl does after
   ARM release to establish communication

### 5.4 — Test basic functionality
Verify scanning, association, and data transfer work.

### 5.5 — Submit upstream
Submit to `linux-wireless@vger.kernel.org` and `brcm80211@lists.linux.dev`,
CC Arend van Spriel. Follow kernel patch submission process.

---

## Patch Assumptions (Phase 3 outcomes)

See `phase3/notes/patch_assumptions.md` for the full list.

- BCM4360 behaves like BCM43602-family chips — **partially true** (same BCMA/CR4/PCIe, different memory layout and protocol)
- ~~TCM rambase = `0x180000`~~ — **disproven**, corrected to `0x0`
- Firmware mapping `brcmfmac4360-pcie` is sufficient for probe — **verified**
- The extracted firmware uses msgbuf protocol — **disproven** (uses BCDC, the fundamental blocker)
- memcpy_toio works for TCM writes — **disproven** (requires 32-bit iowrite32 only)

---

## Tools and Environment

- **OS:** NixOS, kernel 6.12.x
- **Target device:** BCM4360 at PCI 03:00.0
- **Backup connectivity:** USB WiFi adapter (MT76x2u) at wlp0s20u2
- **Languages:** Python (probing/analysis scripts), C (kernel module work)
- **Key tools:** `ftrace`, `mmiotrace`, `trace-cmd`, `binwalk`, `objdump`, `readelf`, Ghidra (firmware analysis)

## Success Criteria

- BCM4360 works with an open-source Linux driver (scan, connect, transfer data)
- No proprietary code in the driver (firmware loaded as a separate binary)
- Patch accepted upstream or viable for out-of-tree use
- BCDC-over-PCIe transport protocol documented for community reference

Even a partial result (e.g., control path works but data path proves infeasible) is
valuable — it documents the protocol and informs future efforts.
