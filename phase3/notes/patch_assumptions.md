# Phase 3 Patch Assumptions

**Date:** 2026-04-12
**Patch:** `phase3/patches/0001-brcmfmac-add-BCM4360-support.patch`

This document tracks the key assumptions made by the proof-of-concept patch, with evidence and verification status.

## Assumption 1: BCM4360 behaves like BCM43602-family chips

**What the patch does:** Groups BCM4360/4352 with the BCM4350/4354/43602 chip family in `chip.c` (shares the same TCM rambase case).

**Evidence for:**
- Same ARM CR4 CPU core (0x83E), rev 2 vs similar revs in 43602
- Same PCIe Gen2 core (0x83C)
- Same BCMA backplane
- Same ChipCommon core (0x800), rev 43
- D11 core rev 42 (close to 43602's rev 44)

**Evidence against:**
- D11 rev 42 vs rev 44 — the wireless core is older, may have init quirks
- USB 2.0 Device core present (unusual for a PCIe card, may need to be disabled)
- Firmware version 6.30.223.0 is from 2013, significantly older than typical 43602 firmware

**Status:** ⚠️ PARTIALLY VERIFIED — chip recognized as BCM4360/3 and firmware loaded, but TCM rambase assumption was wrong (see Assumption 2). Chip is *similar* to BCM43602 but not identical in memory layout.

---

## Assumption 2: TCM RAM base address = 0x180000

**What the patch does:** Falls through to the `0x180000` case in `brcmf_chip_tcm_rambase()`.

**Evidence for:**
- BCM4350, BCM4354, BCM43602 all use `0x180000`
- These are all CR4-based PCIe chips in the same family
- Phase 1.3 analysis concluded this is the likely value

**Evidence against:**
- Phase 1.1 showed ARM CR4 memory at backplane address `0x00000000` (640KB region) — this is the *local* address, the rambase is the *backplane-mapped* address, but they could differ
- No direct confirmation from datasheet or runtime probe

**Status:** ❌ DISPROVEN — Test 1 crashed with page fault in `iowrite32` at `brcmf_pcie_setup+0x1c4`. The write to `tcm + 0x180000 + ramsize - 4` exceeded the 2MB BAR2 mapping. Core enumeration data confirms TCM is at backplane address `0x00000000` (640KB), not `0x180000`. Fix: changed rambase to `0x0` for BCM4360/4352. See `phase3/results/test1_analysis.md`.

---

## Assumption 3: Firmware name mapping is sufficient

**What the patch does:** Maps chip ID 0x4360 → `brcmfmac4360-pcie` firmware files.

**Evidence for:**
- Standard brcmfmac naming convention
- Firmware file placed manually to match

**Evidence against:**
- The firmware was extracted from `wl.ko`, not provided by Broadcom for brcmfmac use
- The firmware may expect a different loading sequence or header format (TRX?)
- The firmware variant selection (4352pci vs 4350pci) is uncertain

**Status:** ✅ PARTIALLY VERIFIED — firmware loaded successfully (`brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3`). Content compatibility not yet tested (crashed before firmware could run).

---

## Assumption 4: Firmware uses msgbuf-compatible protocol (version 5-7)

**What the patch does:** Relies on brcmfmac's hardcoded `BRCMF_PROTO_MSGBUF` for PCIe.

**Evidence for:**
- Firmware contains `pciedev_msg.c` references — this is the dongle side of PCIe message buffering
- Firmware contains `pciedngl_*` function names — PCIe dongle messaging
- BCM4360 has the same PCIe Gen2 core as chips that use msgbuf

**Evidence against:**
- Firmware also contains `bcmcdc.c` references — could indicate BCDC-only protocol
- Firmware is from 2013; msgbuf may have been introduced later
- The `bcmcdc.c` reference may indicate BCDC *encapsulation within* msgbuf (normal) or BCDC *instead of* msgbuf (problem)

**Status:** ⚠️ UNVERIFIED — this is the highest-risk assumption. If the firmware writes a protocol version outside 5-7 to shared memory, brcmfmac will reject it. The dmesg output will show the exact version if this fails.

---

## Assumption 5: No chip-specific init quirks needed

**What the patch does:** Adds the chip ID to existing code paths without any BCM4360-specific initialization.

**Evidence for:**
- Many brcmfmac chips work with just ID additions
- The core layout is standard

**Evidence against:**
- BCM43602 has special handling in `brcmf_pcie_enter_download_state()` and `brcmf_pcie_exit_download_state()` for bank power-down and memory core reset
- The USB 2.0 Device core (unusual for PCIe) may need to be explicitly disabled
- D11 rev 42 may need different PHY init compared to rev 44

**Status:** ⚠️ PARTIALLY ADDRESSED — Diagnostic testing revealed BCM4360 needs bank power-on similar to BCM43602. Added BCM4360-specific bank power-on to `brcmf_pcie_enter_download_state()` (A-banks 0-3). B-bank (idx 4) must NOT be accessed — it hangs the PCIe bus. See `phase3/results/diagnostic_findings.md`.

---

## Verification Plan

All assumptions will be tested simultaneously by loading the patched module. The `dmesg` output will indicate which assumptions hold and which fail:

| Failure message | Assumption invalidated |
|---|---|
| "unknown chip" | Chip ID not recognized (patch didn't apply) |
| "RAM base not provided" | Assumption 2 (TCM rambase) |
| "firmware: failed to load" | Assumption 3 (firmware mapping/format) |
| "Unsupported PCIE version N" | Assumption 4 (protocol version) |
| "Dongle setup failed" | Assumption 5 (init quirks) or Assumption 4 |
| Interface appears | All assumptions validated for probe stage |
