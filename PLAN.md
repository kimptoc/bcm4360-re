# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by
reverse-engineering the host-to-firmware protocol used by the proprietary `wl`
driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded,
giving us the ability to trace driver behaviour, read hardware registers, and
compare against the existing `brcmfmac` codebase.

> **Scope of this document:** high-level phase status only. Per-test detail
> (what was tried, what log was captured, what it proved) lives in
> `phase5/notes/phase5_progress.md`, commit messages, and `phase5/logs/`.

> **Legal constraint:** All reverse engineering follows clean-room methodology
> — observe behavior, document in plain language, implement from that
> documentation. Do not copy disassembly structure directly into driver code.
> See README.md and CLAUDE.md for full guidelines (ref: issue #12).

## Current Status (2026-04-20)

**Active phase:** Phase 5.2 — probe-path stability regression recovery after
hard-crash sessions (tests 149–157).

**Completed in this recovery (2026-04-20):**
- **test.157 CRASH PINPOINTED:** per-marker `msleep(300)` discipline identified
  the MCE trigger — duplicate probe-level ARM halt caused `RESET_CTL=1` to wedge
  the ARM core's BAR0 window, and the next MMIO write triggered the MCE
  (iommu=strict likely escalates bad MMIO to a hard fault).
- **test.158 SUCCESS:** removed the duplicate ARM halt; BusMaster clear and
  ASPM disable (both config-space ops) are safe.
- **test.159 SUCCESS:** reginfo selection + pcie_bus_dev/settings/bus/msgbuf
  kzalloc + struct wiring + pci_pme_capable + dev_set_drvdata all safe.
- **test.160 SUCCESS:** brcmf_alloc (wiphy_new + cfg80211 ops) + OTP bypass +
  brcmf_pcie_prepare_fw_request all safe. Firmware name resolved:
  `brcm/brcmfmac4360-pcie` for chip BCM4360/3.
- **test.161 SUCCESS:** `brcmf_fw_get_firmwares` async path + setup callback
  entry + BCM4360 early-return stub + `brcmf_pcie_remove` BCM4360 short-circuit
  guard (skips MMIO cleanup when `state != UP`). Firmware blobs loaded:
  CODE 442233 B, NVRAM 228 B (CLM/TXCAP absent — optional). Clean rmmod.

**Next boundary:** In setup callback, begin doing BAR2 MMIO — starting with
`brcmf_pcie_attach(devinfo)` (mailbox sizes, shared structure setup). This
is the entry to the historical crash-prone path that gated the pre-regression
Phase 5.2 work (TCM[0x58f08] D11 probe).

**Re-entering the old 5.2 investigation:** once the probe-path restore is
complete (i.e. firmware download and ARM release can run without host crash),
the TCM[0x58f08] D11-object-not-linked finding from test.98 still applies —
the path-B D11 core bring-up probe plan remains valid, just currently gated
behind getting firmware boot to run again.

**What is proven working:**
- Chip recognition, BAR0/BAR2 mapping, firmware download, NVRAM placement.
- ARM release without host crash (after extended crash-isolation work in 5.2).
- Firmware reaches early init; `si_kattach` completes; console output visible.

**What is not yet working:**
- Firmware never progresses past the D11 PHY wait loop → no shared-memory
  handshake → no driver-to-firmware communication.

See also GitHub issues #9 (architecture assessment) and #11 (direction review).

---

## Phase 1: Reconnaissance ✅ COMPLETE

**Goal:** Understand the chip and extract the firmware.

**Outcome:**
- 9 BCMA cores identified (ARM CR4, D11 rev 42, PCIe Gen2, ChipCommon rev 43,
  USB 2.0 Device, plus infrastructure cores).
- Firmware extracted from macOS `wl.ko`: `brcmfmac4360-pcie.bin` (442KB,
  v6.30.223.0, Dec 2013). Thumb-2 ARM, hndrte RTOS.
- brcmfmac delta scoped to ~10 lines for basic support.

Details: `phase1/notes/`.

---

## Phase 2: MMIO Tracing (fallback, not executed)

**Goal:** Capture the `wl` driver's MMIO sequence if Phase 3 fails in ways
that can't be diagnosed from dmesg alone.

**Status:** Not needed during Phase 3 (which succeeded at driver-side bring-up).
Was re-considered during Phase 5 crash investigation; `phase5/logs/wl-trace`
holds a partial capture for reference when/if the D11 reset sequence needs to
be compared against `wl`.

---

## Phase 3: Patched brcmfmac Bring-up ✅ COMPLETE

**Goal:** Prove the driver-side PCIe/TCM/ARM-control path works on BCM4360.

**Outcome:**
- Patches to `brcm_hw_ids.h`, `pcie.c`, `chip.c` add chip ID, firmware mapping,
  TCM rambase (corrected to `0x0`), and CR4 download handlers.
- Hardware characterized: BAR2 maps TCM at offset 0 (640KB populated);
  BCM4360 requires 32-bit `iowrite32` only (64-bit `memcpy_toio` hangs PCIe);
  B-bank must not be accessed via BANKIDX.
- Firmware download end-to-end verified.

**Key finding:** brcmfmac assumes msgbuf protocol but BCM4360 firmware speaks
BCDC. No msgbuf-compatible firmware exists for this chip.

Details: `phase3/results/diagnostic_findings.md`, `phase3/logs/`.

---

## Phase 4: BCDC-over-PCIe Host Transport ✅ PARTIALLY COMPLETE

**Goal:** Decide whether to build a BCDC-over-PCIe host transport (since
brcmfmac speaks msgbuf and BCM4360 firmware speaks BCDC).

**Outcome:**
- 4A (transport discovery): confirmed BCDC encapsulation + PCIe messaging
  mechanics from `wl.ko` and firmware strings.
- 4B (standalone harness): firmware download + ARM release work standalone
  but firmware crashed the host ~100–200ms after release.
- **Decision:** pivot to Phase 5 — patch brcmfmac directly rather than build
  a standalone driver, because brcmfmac already handles PCIe lifecycle,
  interrupts, and DMA setup.

4C (BCDC command implementation) and 4D (integration decision) deferred until
firmware boots cleanly in Phase 5.

Details: GitHub issue #4.

---

## Phase 5: BCM4360 Bring-up via brcmfmac ← **CURRENT PHASE**

**Goal:** Boot the BCM4360 firmware to a steady state where shared-memory
communication is possible, then establish a BCDC control path.

brcmfmac is being used as a **debug/bring-up harness**. Final driver
architecture (SoftMAC vs. offload) remains open — see GitHub issue #9.

### 5.1 — Basic chip support patches ✅ COMPLETE

Minimum viable patches applied (chip ID, firmware mapping, rambase=0,
32-bit iowrite32, INTERNAL_MEM NULL guard). Firmware downloads; ARM used to
crash the host on release.

### 5.2 — Firmware boot stability & forensics ← **IN PROGRESS**

Iterative debug-harness work driven by hypothesis → probe → log → commit.

**Resolved:**
- Host-crash-on-ARM-release root cause isolated (BAR2 wait-loop PCIe
  completion timeout + BCMA resetcore register sequencing).
- Firmware now reaches early init reliably.

**Open:**
- Firmware counter freezes at T+200–400ms; test.98 pointer-chain probe shows
  `TCM[0x58f08] == 0` (D11 object `field0x18` never set).
- Interpretation: hang is in si_attach's D11 core bring-up, upstream of the
  previously hypothesised PHY wait loop. fn 0x1624c is NOT the hang site.
- Next: Path B — D11 core prerequisite checks (core reset/enable, clock
  request, PMU resources, interrupt mask/routing). First probe (test.99):
  D11 core BCMA state via chip.c bus ops. See `phase5_progress.md` for the
  full probe order.

**Exit criterion for 5.2:** firmware reaches a state where it writes a valid
shared-memory handshake structure (pcie_shared / BCDC control ring), or we
have a clear characterization of why it cannot.

### 5.3 — Firmware protocol bridge

**Goal:** Replace the msgbuf handshake with BCDC-over-PCIe so brcmfmac can
talk to BCM4360 firmware.

Gated on 5.2 completion.

### 5.4 — Functional validation

Scan, associate, transfer data. Gated on 5.3.

### 5.5 — Upstream submission

Patches to `linux-wireless@vger.kernel.org` and `brcm80211@lists.linux.dev`.

---

## Tools and Environment

- **OS:** NixOS, kernel 6.12.x
- **Target device:** BCM4360 at PCI 03:00.0
- **Backup connectivity:** USB WiFi adapter (MT76x2u) at wlp0s20u2
- **Languages:** Python (probing/analysis), C (kernel module)
- **Key tools:** `ftrace`, `mmiotrace`, `trace-cmd`, `binwalk`, `objdump`,
  `readelf`, Ghidra (firmware analysis)
- **`wl` proprietary driver:** fails to load on kernel 6.12.80
  ("Unpatched return thunk") — cannot be used as a live reference on this host.

## Success Criteria

- BCM4360 works with an open-source Linux driver (scan, connect, data transfer).
- No proprietary code in the driver (firmware loaded as a separate binary).
- Patch accepted upstream or viable for out-of-tree use.
- BCDC-over-PCIe transport documented for community reference.

Even a partial result (e.g., control path works but data path proves
infeasible) is valuable — it documents the protocol and informs future efforts.
