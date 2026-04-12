# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by reverse-engineering the host-to-firmware protocol used by the proprietary `wl` driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded, giving us the ability to trace driver behaviour, read hardware registers, and compare against the existing `brcmfmac` codebase.

## What We Know So Far

### The chip
- BCM4360, PCI ID `14e4:43a0` rev 03, Apple subsystem `106b:0112`
- FullMAC architecture: the 802.11ac stack runs on an ARM Cortex-R4 (or M3) inside the chip
- Contains a proprietary Broadcom "D11 core" for the PHY layer
- Internal cores are connected via a BCMA backplane (same bus used by other Broadcom chips)
- Firmware is split into ROM (baked into silicon) and RAM (loaded by the host driver)
- PCIe interface with two BARs: 32KB control registers (BAR0) and 2MB backplane window (BAR2)

### The existing proprietary driver (`wl`)
- Hybrid driver: open-source shim wrapping two proprietary ELF objects (`wl.o`, `wlc_hybrid.o_shipped`)
- Contains embedded firmware that is loaded onto the chip's ARM core at init
- Shares significant code with the on-chip firmware (per Quarkslab analysis)
- The driver and firmware share APIs — vulnerabilities in one are present in the other
- Currently loaded and functional on this machine

### The existing open-source driver (`brcmfmac`)
- Supports other Broadcom FullMAC chips (BCM4339, BCM4354, BCM4356, BCM43602, BCM4387, etc.)
- Uses `msgbuf` protocol for PCIe devices, `BCDC` for SDIO/USB
- Handles firmware loading, backplane enumeration, and host-firmware messaging
- Maintained by Arend van Spriel at Broadcom
- BCM4360 is explicitly **not supported** — no chip ID, no firmware interface mapping

### Why brcmfmac doesn't support BCM4360 today
- Broadcom has never released FullMAC firmware for this chip separately
- The chip may use an older or different variant of the messaging protocol
- Nobody has mapped the specific firmware interface (commands, events, init sequence)
- Arend van Spriel acknowledged it would require "porting everything from fmac to smac" — though this may refer to a different technical approach than what we're attempting

---

## Phase 1: Reconnaissance (no risk to running system)

### 1.1 — Enumerate BCMA backplane cores
**Goal:** Identify what internal cores exist on the chip and at what addresses.

**Method:** Read the BCMA enumeration ROM via BAR2. The BCMA bus stores a table of core descriptors at a known offset. Each entry identifies a core type (ARM, D11, PCIe, USB, etc.), its address range, and revision.

**Tools:** Python script reading `/sys/bus/pci/devices/0000:03:00.0/resource2`

**Output:** A table of core types, addresses, and revisions — compare against brcmfmac's supported layouts.

**Risk:** Read-only. No writes to hardware. Safe while `wl` is running.

### 1.2 — Extract firmware from `wl.ko`
**Goal:** Pull out the ARM firmware blob embedded in the proprietary driver module.

**Method:** Use `binwalk`, `objdump`, and manual analysis on the `wl.ko` file. The firmware is likely a contiguous ARM binary within one of the ELF sections. Look for ARM vector tables (reset, IRQ, etc.) and known Broadcom firmware headers.

**Tools:** `binwalk`, `objdump`, `readelf`, `hexdump`, custom Python scripts

**Output:** Raw firmware binary, entry point, load address, size. Compare against known brcmfmac firmware file formats (`.bin`, `.clm_blob`).

**Risk:** None — analysing a file on disk.

### 1.3 — Study brcmfmac source for supported chip patterns
**Goal:** Understand what brcmfmac expects from a FullMAC PCIe chip, so we know what we need to provide for BCM4360.

**Method:** Read the kernel source — specifically:
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` — PCIe bus layer
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/msgbuf.c` — host-firmware protocol
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c` — chip identification and core enumeration
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/firmware.c` — firmware loading

**Output:** Documentation of the init sequence, protocol handshake, and chip-specific hooks.

**Risk:** None — reading source code.

---

## Phase 2: Active Tracing

### 2.1 — Trace `wl` driver MMIO access during initialization
**Goal:** Capture the complete sequence of register reads/writes the `wl` driver performs during module load and device init.

**Method:** Unload and reload the `wl` module with `ftrace` or `kprobes` active on `ioread32`/`iowrite32`. Alternatively, use `mmiotrace` (kernel's MMIO tracing facility) which logs all MMIO access.

**Tools:** `trace-cmd`, `mmiotrace`, custom `ftrace` setup

**Output:** A timestamped log of every register address read/written, with values. This is the chip's initialization sequence.

**Risk:** Moderate — requires reloading the WiFi driver. Will temporarily lose WiFi on that interface. The USB adapter can provide connectivity during this work.

### 2.2 — Trace `wl` driver during scan, associate, and data transfer
**Goal:** Capture the host-firmware command/response protocol for key operations.

**Method:** Same MMIO tracing, but trigger WiFi operations (scan for networks, connect to AP, transfer data) while tracing is active.

**Output:** Command structures, event formats, ring buffer usage patterns — the protocol we need to replicate.

**Risk:** Same as 2.1 — WiFi disruption during tracing.

### 2.3 — Compare traced patterns against brcmfmac msgbuf protocol
**Goal:** Determine whether BCM4360 uses standard `msgbuf` protocol or a variant.

**Method:** Align traced MMIO sequences against brcmfmac's `msgbuf` implementation. Look for shared ring buffer structures, doorbell registers, and message types.

**Output:** A mapping of BCM4360's protocol to brcmfmac concepts — what's the same, what differs.

**Risk:** None — analysis work.

---

## Phase 3: Proof of Concept

### 3.1 — Write a userspace probe tool
**Goal:** A tool that can initialize the chip, enumerate cores, and send basic commands — without the `wl` driver loaded.

**Method:** Python or C tool using `/dev/mem` or a small kernel module to access MMIO. Replay the initialization sequence captured in Phase 2.

**Output:** Evidence that we can bring the chip up and communicate with the firmware independently of `wl`.

**Risk:** High — writing to hardware registers with `wl` unloaded. Could hang the chip or PCIe bus. Mitigated by having the USB adapter for recovery and using PCI reset to recover the device.

### 3.2 — Attempt firmware load via brcmfmac path
**Goal:** Try loading the extracted firmware using brcmfmac's firmware loading code path.

**Method:** Add BCM4360's PCI ID to brcmfmac, place the extracted firmware where brcmfmac expects it, and attempt to load the module.

**Output:** Either it works (partially or fully) or it fails with specific errors that guide further work.

**Risk:** Moderate — loading an experimental kernel module. Worst case: kernel panic, reboot required.

---

## Phase 4: Driver Development

### 4.1 — Patch brcmfmac for BCM4360 support
**Goal:** A working brcmfmac patch that supports BCM4360.

**Method:** Based on findings from Phases 1-3:
- Add chip ID and core table to `chip.c`
- Add firmware file mapping to `firmware.c`
- Add any protocol quirks to `pcie.c` / `msgbuf.c`
- Handle any BCM4360-specific initialization

**Output:** A kernel patch that can be tested and submitted for review.

### 4.2 — Test basic functionality
**Goal:** Verify scanning, association, and data transfer work.

**Method:** Load patched brcmfmac, scan for networks, connect, run throughput tests.

**Output:** Test results, any remaining issues documented.

### 4.3 — Submit upstream
**Goal:** Get the patch accepted into the Linux kernel.

**Method:** Submit to `linux-wireless@vger.kernel.org` and `brcm80211@lists.linux.dev`, CC Arend van Spriel. Follow kernel patch submission process.

**Output:** BCM4360 support in mainline Linux.

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
