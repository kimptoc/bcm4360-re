# Phase 3 Firmware Workstreams

**Date:** 2026-04-12

Each component needed for a successful brcmfmac probe is tracked separately. All three must be resolved before a clean test.

---

## 1. Firmware Binary (`brcmfmac4360-pcie.bin`)

**Status:** Available, variant uncertain

**What we have:**
- Two extracted variants from `wl.ko` 6.30.223.271:
  - `phase1/output/firmware_4352pci.bin` — 431.9KB, CRC ff98ca92
  - `phase1/output/firmware_4350pci.bin` — 435.3KB, CRC ffcf9e98
- Both are version 6.30.223.0, built 2013-12-15
- Thumb-2 ARM binaries targeting ARM CR4

**Open questions:**
- [ ] Which variant does BCM4360 (0x43a0) actually use? Testing instructions default to `4352pci` based on chip family proximity, but this is a guess.
- [ ] Does brcmfmac expect a TRX header on the firmware? If so, our raw binary may need wrapping.
- [ ] Is the 2013-era firmware compatible with brcmfmac's msgbuf protocol (version 5-7)?

**Install path:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin`

**First test plan:** Use `firmware_4352pci.bin`. If it fails, try `firmware_4350pci.bin`.

---

## 2. NVRAM (`brcmfmac4360-pcie.txt`)

**Status:** Not yet sourced

**What NVRAM provides:**
Board-specific calibration data — TX power levels, antenna configuration, regulatory domain, MAC address, crystal frequency, PA parameters. Without it, brcmfmac may:
- Use defaults (may work poorly or not at all)
- Read from SPROM on the card (if present and if brcmfmac supports it for this chip)
- Fail probe entirely

**Possible sources:**
- [ ] **SPROM on the PCIe card** — brcmfmac can read SPROM for some chips. Check if BCM4360 SPROM reading is supported.
- [ ] **Embedded in `wl.ko`** — the proprietary driver may contain default NVRAM. Look for `boardtype=`, `macaddr=`, `pa2gw0a0=` patterns in the binary.
- [ ] **macOS nvram** — Apple stores WiFi calibration in NVRAM on Macs. If this is a MacBook, it may be accessible via `nvram` or firmware tables.
- [ ] **None needed** — some firmwares have built-in defaults. Unlikely for production hardware.

**Install path:** `/lib/firmware/brcm/brcmfmac4360-pcie.txt`

**First test plan:** Attempt without NVRAM first. If brcmfmac complains about missing NVRAM, investigate SPROM and extraction options.

---

## 3. CLM Blob (`brcmfmac4360-pcie.clm_blob`)

**Status:** Not investigated

**What CLM provides:**
Country Locale Matrix — regulatory data specifying allowed channels, power levels, and bandwidth per country. Used by newer brcmfmac firmwares for regulatory compliance.

**Possible sources:**
- [ ] **Embedded in firmware** — older firmwares (like our 2013 build) may have CLM data built-in rather than as a separate file.
- [ ] **Extracted from `wl.ko`** — look for CLM signatures in the binary.
- [ ] **Not needed** — if the firmware predates the CLM split, it won't request one.

**Install path:** `/lib/firmware/brcm/brcmfmac4360-pcie.clm_blob`

**First test plan:** Attempt without CLM. If brcmfmac logs a CLM-related error, investigate extraction.

---

## Test Firmware Layout

For the first test, the `/lib/firmware/brcm/` directory should contain:

```
/lib/firmware/brcm/
├── brcmfmac4360-pcie.bin       ← firmware_4352pci.bin (first attempt)
├── brcmfmac4360-pcie.txt       ← (omit on first test, add if needed)
└── brcmfmac4360-pcie.clm_blob  ← (omit on first test, add if needed)
```

Record the exact layout used in each test run under `phase3/results/`.
