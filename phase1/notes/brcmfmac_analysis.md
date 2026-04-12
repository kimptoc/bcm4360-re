# Phase 1.3: brcmfmac Source Analysis for BCM4360 Compatibility

**Date:** 2026-04-12

## Summary

After studying the brcmfmac kernel driver source, the BCM4360 is **closer to being supported than expected**, but there are several gaps to bridge. The biggest surprise: the BCDC protocol finding from Phase 1.2 may be less of a problem than feared.

## What brcmfmac needs to support a chip

1. **PCI Device ID** in the probe table (`pcie.c`)
2. **Chip ID** in the firmware name lookup table (`pcie.c`)
3. **TCM RAM base address** in `brcmf_chip_tcm_rambase()` (`chip.c`)
4. **TCM RAM size** — auto-detected from CR4 bank registers (already generic)
5. **Firmware files** — `.bin`, `.txt` (NVRAM), `.clm_blob` (optional)
6. **Shared memory protocol version** — must be between 5 and 7
7. **Ring buffer protocol** — msgbuf over PCIe

## Gap Analysis

### Gap 1: PCI Device ID (trivial)
Our BCM4360 has PCI device ID `0x43a0`. This just needs adding to:
- `brcm_hw_ids.h` — define `BRCM_PCIE_4360_DEVICE_ID 0x43a0`
- `pcie.c` — add to `brcmf_pcie_devid_table[]`

**Effort: 2 lines of code.**

### Gap 2: Chip ID and firmware mapping (trivial)
Chip ID `0x4360` needs:
- Define `BRCM_CC_4360_CHIP_ID 0x4360` in `brcm_hw_ids.h`
- Add firmware name entry: `BRCMF_FW_DEF(4360, "brcmfmac4360-pcie")`
- Add to firmware table: `BRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360)`

**Effort: 3 lines of code.**

### Gap 3: TCM RAM base address (trivial, needs verification)
The `brcmf_chip_tcm_rambase()` function needs a case for BCM4360. The similar chips (BCM4350, BCM4354, BCM43602) all use `0x180000`. Our chip's EROM showed ARM CR4 memory at `0x00000000` with 640KB — but the rambase is the *backplane* address, which is likely `0x180000` for this chip family.

**Effort: 1 line of code, but needs verification.**

### Gap 4: Protocol — msgbuf vs BCDC (the key question)

brcmfmac's PCIe path **hardcodes** `bus->proto_type = BRCMF_PROTO_MSGBUF` (pcie.c:2515). All PCIe communication goes through msgbuf ring buffers.

The firmware we extracted from `wl.ko` references `bcmcdc.c`, which initially suggested BCDC protocol. However, looking more carefully:

**The firmware ALSO contains `pciedev_msg.c` references**, which is the dongle side of the PCIe message buffer protocol. The `bcmcdc.c` reference may be for the BCDC *encapsulation* of data frames within msgbuf messages — this is normal. In brcmfmac, BCDC headers are used to encapsulate data packets even over msgbuf (see `bcdc.c` which wraps data frames).

**Critical check needed:** After loading firmware, brcmfmac reads a shared memory structure from the chip's TCM. The first word contains the protocol version (must be 5-7). If our firmware writes a compatible version there, it'll work. If not, we need to understand what it writes.

### Gap 5: Firmware format (moderate risk)
brcmfmac expects:
- **`.bin`** — raw ARM binary loaded to TCM RAM
- **`.txt`** — NVRAM key-value pairs (board calibration)
- **`.clm_blob`** — regulatory data (optional)

Our extracted firmware is a raw ARM binary, which matches. But:
- Some firmwares have a TRX header that brcmfmac strips
- We need an NVRAM file — may be embedded in the `wl` driver or in SPROM on the card
- CLM data may be embedded in the firmware or separate

### Gap 6: Chip-specific init quirks (low risk)
BCM43602 has special handling in `brcmf_pcie_enter_download_state()` and `brcmf_pcie_exit_download_state()` — setting bank power-down registers and resetting an internal memory core.

BCM4360 may need similar quirks. The EROM shows it has USB 2.0 Device core (unusual for a PCIe card) which might need to be disabled.

## Comparison: BCM4360 vs BCM43602 (closest supported chip)

| Aspect | BCM4360 (ours) | BCM43602 (supported) |
|---|---|---|
| CPU | ARM CR4 rev 2 | ARM CR4 |
| D11 | rev 42 | rev 44 |
| PCIe | Gen2 rev 1 | Gen2 |
| ChipCommon | rev 43 | similar |
| TCM rambase | 0x180000 (probable) | 0x180000 |
| TCM size | ~640KB (from EROM) | auto-detected |
| Protocol | msgbuf (confirmed via pciedev_msg.c in FW) | msgbuf |
| FW version | 6.30.223.0 (2013) | newer |

## Revised Assessment

The BCM4360 is architecturally nearly identical to BCM43602. The minimal patch to try would be:

1. Add PCI device ID `0x43a0`
2. Add chip ID `0x4360`
3. Add TCM rambase `0x180000`
4. Add firmware name mapping
5. Place extracted firmware as `brcmfmac4360-pcie.bin`
6. Create or extract NVRAM data

**The biggest unknown is the shared memory protocol version.** If the firmware initializes a protocol version between 5-7, the whole msgbuf machinery should just work. If it uses an older version (e.g., the firmware is from 2013), we may need to handle an older protocol.

## Recommended Next Step

**Try loading brcmfmac with the BCM4360 patch** — add the chip IDs, place the firmware, unload `wl`, load patched `brcmfmac`, and see what happens. The worst case is a protocol version mismatch error, which would tell us exactly what to fix.

This could potentially be done in Phase 3.2 without needing all of Phase 2 (MMIO tracing). The tracing would be our fallback if the simple approach fails.

## Key Source Files Studied

- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` (2784 lines) — PCIe bus layer, device probe, firmware download, ring buffer init
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c` (1472 lines) — chip identification, RAM detection, core management
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/firmware.c` (863 lines) — firmware file loading
- `drivers/net/wireless/broadcom/brcm80211/brcmfmac/proto.c` — protocol selection (BCDC vs msgbuf)
- `drivers/net/wireless/broadcom/brcm80211/include/brcm_hw_ids.h` — chip and device ID definitions
