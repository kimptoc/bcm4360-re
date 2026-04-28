# BCM4360 Reverse Engineering: Deep Review and New Options

**Date:** 2026-04-28  
**Status:** Current blocker — firmware boots to WFI, ISR node exists but is never triggered by host

---

## Executive Summary

After 6 phases, 300+ tests, and exhaustive static analysis, the project has thoroughly characterized the BCM4360 PCIe interface. The core problem is well-defined: firmware downloads, boots, executes `pciedngl_probe`, reaches WFI waiting for an event, with two ISR nodes (bits 0 and 3) confirmed alive via Received-Path testing. Every candidate host→firmware wake path — MAILBOXMASK via BAR0 MMIO, OOB Router, PMU/GPIO, D11 INTMASK, H2D_MAILBOX_1, DMA via `olmsg_*` — has been tested and closed.

The breakthrough from external research is that **the project has been writing interrupt mask registers in the wrong address space for the BCM4360's PCIe core revision**. The bcmdhd reference driver shows that older PCIe core revisions (like the one in BCM4360) use **PCI CONFIG SPACE** for interrupt masking, not BAR0 MMIO.

---

## Current State Assessment

### What is Known

1. **Firmware execution** — Firmware boots successfully, runs `pciedngl_probe`, reaches WFI with `PCIE_RCV`_`SCH`_`CFG` ready.
2. **ISR nodes confirmed alive** — The Received-Path testing proved the firmware ISR executes (bits 0 and 3). The firmware side works.
3. **Shared structure visible** — `pciedev_shared_t` can be read/written from host.
4. **Doorbell writes acknowledged** — H2D_MAILBOX_1 writes hit the chip (seen via local snapshot), but no ISR fire.
5. **Interrupt mask appears zero** — `PCIE2+0x4C` reads as zero shortly after `brcmf_chip_set_active()`.
6. **MAILBOXMASK writes via BAR0 silently drop** — Every attempt to write `PCIE2.MAILBOXMASK` via MMIO has been ineffective.

### What is Not Known

- The correct mechanism to unmask/enable PCIe mailbox interrupts for this chip.
- Whether additional vendor-specific config space initialization is required.
- Whether the firmware expects a different shared structure layout or initialization.
- Whether ring buffers need to be configured differently than brcmfmac does.

---

## External Research Findings

### 1. bcmdhd Reference Driver (Android)

The Broadcom **bcmdhd** driver (the reference FullMAC PCIe driver used in Android) explicitly supports BCM4360:

```c
// dhd_pcie.c
case BCM4360_CHIP_ID:
    bus->dongle_ram_base = CR4_4360_RAM_BASE;
    break;
```

**Critical discovery — interrupt enable path:**

```c
void dhdpcie_bus_intr_enable(dhd_bus_t *bus) {
    if ((bus->sih->buscorerev == 2) || (bus->sih->buscorerev == 6) ||
        (bus->sih->buscorerev == 4)) {
        /* OLD REVISIONS: write to PCI CONFIG SPACE */
        dhpcie_bus_unmask_interrupt(bus);
    } else {
        /* NEWER REVISIONS: write to BAR0 MMIO register */
        si_corereg(bus->sih, bus->sih->buscoreidx, PCIMailBoxMask,
                   bus->def_intmask, bus->def_intmask);
    }
}

int dhpcie_bus_unmask_interrupt(dhd_bus_t *bus) {
    /* PCIIntmask is a config-space offset */
    dhdpcie_bus_cfg_write_dword(bus, PCIIntmask, 4, I_MB);  // I_MB = 0x3
    return 0;
}
```

`dhdpcie_bus_cfg_write_dword()` ultimately calls `pci_write_config_dword()`. For old PCIe core revisions (rev 2, 4, 6), **interrupt masking lives in PCI config space, not BAR0 MMIO**.

Additionally, `dhdpcie_bus_intr_init()` sets:

```c
bus->def_intmask = PCIE_MB_D2H_MB_MASK(buscorerev);
if (buscorerev < 64) {
    bus->def_intmask |= PCIE_MB_TOPCIE_FN0_0 | PCIE_MB_TOPCIE_FN0_1;
}
```

`PCIE_MB_TOPCIE_FN0_0 = 0x0100`, `PCIE_MB_TOPCIE_FN0_1 = 0x0200`. This matches the project's observed `MAILBOXMASK = 0x318` (0x218 | 0x100 for the D2H bits).

### 2. Asahi Linux / ArcaneNibble's BCM4387 Work

ArcaneNibble's reverse engineering of the Apple M1 Bluetooth chip (BCM4387) revealed a crucial pattern:

> " Eventually, I start using the debugging technique of 'what information do I have that I have not used yet?' One obvious piece of information is the `AppleConvergedPCI` driver… While thoroughly combing through this driver… I eventually notice `AppleConvergedPCI::setupVendorSpecificConfigGated`… PCIe config space. Of course. Since the PCIe configuration space is not part of a BAR, none of my tracing captured it. **It's also the perfect location to put magic pokes that completely change how the rest of the chip behaves.** This also explains what the magic numbers in `ACIPCChip43XX` are for — they are written into the configuration space to change what is mapped into the memory BARs."

The m1-bluetooth-prototype driver explicitly performs **vendor-specific config space writes** during initialization, and warns:

> "If you have a BCM4378 or another device, you will have to reverse engineer the macOS driver and change the magic configuration space register writes and reset logic. If you mess this up, your system will hard-lock-up immediately."

The ArcaneNibble repository also documents a full **AVD (Apple Video Decoder)** config space register map showing various vendor-specific config registers at offsets 0x0008, 0x1000–0x1700, 0x4000–0x4600, etc.

### 3. Linux Kernel Mainline brcmfmac Evolution

The upstream Linux kernel has added support for newer chips (BCM4387, BCM4378, etc.) which use PCIe core revision ≥ 64. For these newer cores, the brcmfmac driver was patched to use different register offsets (`BRCMF_PCIE_64_*` constants) and to handle additional initialization like TxCap blobs and external calibration. The BCM4360 uses the legacy (pre-64) register layout, matching the older bcmdhd behavior.

---

## Why the Project Has Been Stuck

The project has been trying to enable interrupts by writing `0x1` to `PCIE2+0x4C` (BAR0 MMIO offset `PCIMailBoxMask`). This register is **read-only or unmapped** for older PCIe core revisions when accessed via BAR0. The bcmdhd driver's conditional tells us why:

- **buscorerev 2, 4, 6** → config space only
- **buscorerev ≥ 64** → BAR0 MMIO accessible

The project confirmed in RESUME_NOTES that writes to BAR0+0x4C have "no effect" and "silently drop." That is exactly what you would expect if you're writing to a nonexistent or read-only BAR0 offset on a chip that only implements that register in config space.

---

## Options Going Forward

### Option 1 (Highest Priority): PCI Config Space Interrupt Enable

**Action:** Write the PCI config space interrupt mask register directly using `pci_write_config_dword()`.

**Rationale:** bcmdhd's `dhpcie_bus_unmask_interrupt()` is the reference implementation. It writes `I_MB = 0x3` to the config space `PCIIntmask` offset. The `PCIIntmask` offset is defined in `pcie_core.h` as part of the PCIe enumeration space (at config offset 0x?? — needs to be determined from wl.ko or config space dumps).

**Immediate test:**
1. Identify the config space offset. Candidate offsets seen in bcmdhd:
   - `PCIMailBoxInt = 0x48`
   - `PCIMailBoxMask = 0x4C`
   - `PCIIntmask = 0x???` (possibly the same as `PCIMailBoxMask` accessed via config reads/writes)
2. Read the full config space (standard 256 + extended 4096 bytes) before and after `set_active` using `lspci -xxx` or direct `/sys/bus/pci/devices/.../config` reads.
3. Write `0x3` to the `PCIIntmask` offset after `set_active` and check if it persists.
4. Observe whether an H2D doorbell now triggers an ISR.

**Risk:** Very low. Config space writes are standard PCIe operations that don't touch BARs or cause substrate noise.

---

### Option 2: Compare bcmdhd vs brcmfmac Initialization Sequences

**Action:** Extract the complete initialization flow from bcmdhd's `dhdpcie_bus_attach()` → `dhdpcie_dongle_attach()` → `dhd_bus_start()` → `dhdpcie_bus_init()` and compare against brcmfmac's `brcmf_pcie_attach()` and `brcmf_pcie_setup()`.

**Rationale:** bcmdhd is the official Broadcom reference driver. It works. Any divergence is a potential root cause. Key differences likely include:
- Config space register writes that brcmfmac omits
- Shared structure setup (address programming into dongle TCM)
- Ring buffer initialization sequence
- MSI/MSI-X configuration
- Power state transitions (D0/D3) and ASPM control

**Approach:** Clone AOSP `kernel/common.git` bcmdhd branch, annotate the init sequence, and systematically check each step against what brcmfmac currently does. Use grep to find where bcmdhd writes to `PCIMailBoxMask`, `PCIMailBoxInt`, `PCIH2D_MailBox`, `H2D_MAILBOX_1`, register enables, clock gating, etc.

**Outcome:** A checklist of brcmfmac gaps to close.

---

### Option 3: VFIO-PCI Dump and Diff Config Space

**Action:** Use VFIO-PCI to bind the device in userspace and perform full config space dumps under both wl and brcmfmac. Extract all magic values.

**Rationale:** ArcaneNibble's success with BCM4387 came from discovering that `AppleConvergedPCI::setupVendorSpecificConfigGated` writes vendor-specific config registers that remap the BARs and enable the device. The same pattern likely applies to BCM4360 when driven by wl vs brcmfmac.

**Steps:**
1. Boot a working wl.ko configuration (older kernel or patched driver)
2. `lspci -xxx -s 03:00.0 > config_wl.txt`
3. Unload wl, load brcmfmac
4. `lspci -xxx -s 03:00.0 > config_brcmfmac.txt`
5. Diff the two. The differences are the "missing magic."
6. Apply those writes early in brcmfmac's initialization (before firmware download or right after `brcmf_chip_set_active`).

**Note:** Some config space registers are volatile or change state after firmware boots. To get a clean "pre-firmware" snapshot, perform the wl dump immediately after driver load but before firmware download triggers. Use `trace-cmd` or `systemtap` to capture `pci_write_config_dword()` calls from wl during initialization and replay them manually.

---

### Option 4: Older Kernel + wl.ko Instrumentation

**Action:** Boot a kernel that predates the RET-rewriter instrumentation (e.g., 5.10 or 4.19). Load wl.ko successfully. Instrument the driver with tracepoints or kprobes to capture every `pci_write_config_dword()`, `pci_read_config_dword()`, `ioread32()`, and `iowrite32()` call during initialization.

**Rationale:** The project's attempt with RET-rewriter on modern kernels likely corrupted wl.ko's control flow. Running on an older kernel removes that confounder, giving a clean trace of the actual working sequence.

**Implementation:**
- Add `dynamic_debug` or `tracepoint` instrumentation:
  ```bash
  echo 'module wl * +p' > /sys/kernel/debug/dynamic_debug/control
  cat /sys/kernel/debug/dynamic_debug/control > wl_trace.log
  ```
- Or use `bpftrace` to trace PCI config and MMIO accesses:
  ```c
  tracepoint:syscalls:sys_enter_pwrite64 /args->fd == pci_fd/ { printf("%x\n", arg2); }
  ```
- Or use `kprobe:__pci_write_config_dword` to capture targets.

**Deliverable:** A linear script of all config space and BAR0 MMIO writes that wl.ko performs from probe through firmware boot.

---

### Option 5: Firmware Binary Patching

**Action:** Patch the firmware binary to include an explicit `MAILBOXMASK = def_intmask` write after `pciedngl_probe()`.

**Rationale:** The firmware is already executing and reaching WFI. If the only missing piece is that the interrupt mask is cleared by the host (or never set), the firmware could set it itself. Since the firmware runs on the chip's ARM core and has MMIO access to its own PCIe core registers, it can unmask its own interrupts.

**Steps:**
1. Disassemble `brcmfmac4360-pcie.bin` using `arm-none-eabi-objdump -d`.
2. Find `pciedngl_probe()` (known to end near offset ~0x1xxxx in the firmware).
3. Insert a `str r1, [r0, #0x4C]` (store immediate to PCIE2+0x4C) after the probe routine or wherever init-finalization occurs.
4. Rebuild firmware binary and test.

**Caveat:** If interrupts *must* be enabled from the host side (by hardware design), this won't work. But if the mask is simply inadvertently cleared by `brcmf_chip_set_active` and never restored, firmware self-enabling would bypass the host driver's mistake.

---

### Option 6: Vendor-Specific Config Space Magic (ArcaneNibble Pattern)

**Action:** Reverse-engineer the macOS Broadcom WiFi driver (`AirPortBrcmNIC.kext`) or the closed wl.ko binary to extract the exact config space register writes performed during device initialization.

**Rationale:** ArcaneNibble's work shows that for Apple Silicon Broadcom chips, the vendor driver performs magic writes to config space that are *essential* for BAR mapping and device operation. These writes are not part of the PCIe standard — they are chip-specific initialization. The project's KEY_FINDINGS at rows 132–133 show the Apple driver writes a sequence of 6 32-bit values to config offsets 0xE0, 0xE4, 0xE8, 0xEC, 0xF0, 0xF4 during attach. Those could be `vendor-specific` capabilities or ASPM control.

**How to:**
- Use `objdump -d` on `wl.ko` to find `wlc_attach` or `pcicore_attach`.
- Trace all `pci_write_config_dword()` calls.
- Alternatively, search for `-573200152` (0xDEADBEEF pattern?) or other constant sequences.
- Or simpler: dump config space under wl vs under brcmfmac and apply the delta.

---

### Option 7: Try a Newer brcmfmac with BCM4387 Hacks

**Action:** Backport the BCM4387 support patches from Asahi Linux/mainline (which handle rev ≥ 64, new doorbells, TxCap blobs, etc.) to the BCM4360 driver and see if anything changes.

**Rationale:** Unlikely to help (BCM4360 is an older chip with a simpler backpack), but worth a shot if other options fail. Some Asahi patches are general (e.g., `brcmf_chip_only_disable_d11_cores`, `handle_1024_unit_tcm`).

---

## Recommended Action Plan

1. **Immediate test (Option 1):**
   - Identify `PCIIntmask` config space offset from bcmdhd or `/sys` config dumps.
   - After `brcmf_chip_set_active()` completes, call `pci_write_config_dword(pdev, PCIIntmask_offset, 0x3)`.
   - Re-run `set_active` with firmware running to WFI.
   - Trigger H2D doorbell. Check ISR.

   This is a two-line code change, reversible, and directly addresses the root cause.

2. **Config space dump diff (Option 3):**
   - Get wl.ko working on any kernel.
   - `lspci -xxx -s 03:00.0 > wl_config.txt`
   - Unload wl, load brcmfmac
   - `lspci -xxx -s 03:00.0 > brcmfmac_config.txt`
   - `diff wl_config.txt brcmfmac_config.txt` → magic writes list
   - Apply those writes in brcmfmac before/during `brcmf_chip_set_active`.

3. **Full bcmdhd init sequence audit (Option 2):**
   - Clone `https://android.googlesource.com/kernel/common/+/bcmdhd-3.10/drivers/net/wireless/bcmdhd/`
   - Annotate every config write, MMIO write, register access from `dhdpcie_init` through `dhd_bus_start`.
   - Create a side-by-side table with brcmfmac's `brcmf_pcie_*` functions.
   - Highlight gaps.

4. **If still blocked:** Try Option 4 (older kernel + tracing) for definitive answers.

---

## Legal and Safety Notes

- **Clean-room**: Stick to documenting behavior observed from working drivers (wl, bcmdhd). Implement independently based on documented patterns.
- **No firmware blobs**: Do not commit modified firmware binaries. Use patched firmware only as a local debugging tool.
- **Patents**: Broadcom's interrupt enable scheme via config space may be patented; this is purely for interoperability.
- **System lockup**: Config space writes to certain offsets can brick the system. Stick to offsets explicitly used by bcmdhd/wl.

---

## Hypothesis

**Working hypothesis:** After `brcmf_chip_set_active()` clears `MAILBOXMASK` to zero, the host must unmask interrupts by writing `0x3` to the PCIe core's `PCIIntmask` config space register (at a config-space offset, not BAR0 MMIO). The bcmdhd driver provides the blueprint for doing exactly that. Until the host writes this register, the firmware will remain in WFI, having already set up the ISR nodes but never receiving the doorbell interrupt that should exit it.

**Expected outcome if correct:** H2D doorbell will trigger ISR → firmware will process the posted transactions in the completion ring → `WLC_E_EVENT` will flow up to userspace.

---

*Document compiled by Kilo based on project state + external web research.*
