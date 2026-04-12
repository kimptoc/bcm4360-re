# BCM4360 Firmware Extraction — Analysis

**Date:** 2026-04-12
**Source:** wl.ko 6.30.223.271 (broadcom-sta, kernel 6.12.78)

## Firmware Variants Found

Two firmware blobs are embedded in the `wl.ko` module:

| Variant | Name | Size | Build Date | CRC | FWID |
|---|---|---|---|---|---|
| 4352pci | 4352pci-bmac/debug-ag-nodis-aoe-ndoe | 431.9KB | 2013-12-15 19:30:36 | ff98ca92 | 01-9413fb21 |
| 4350pci | 4350pci-bmac/debug-ag-nodis-aoe-ndoe | 435.3KB | 2013-12-15 19:54:33 | ffcf9e98 | 01-518e42f8 |

Both are version **6.30.223.0**, built on the same day (Dec 15, 2013). The "debug-ag-nodis-aoe-ndoe" suffix suggests: debug build, a/g bands, no display, ARP offload engine, no dongle offload engine.

## Key Findings

### 1. These are Thumb-mode ARM binaries, not ARM32

The vector table doesn't match standard ARM32 vectors (expected `0xEAxxxxxx` branch instructions). Instead we see patterns like `0xB80EF000` which are **Thumb-2 branch instructions**. The ARM CR4 supports Thumb-2, and Broadcom uses it for denser code.

The first bytes of 4352pci: `00 f0 0e b8` — this is a Thumb-2 `B.W` (wide branch) instruction, branching forward to the reset handler. This confirms the firmware starts with a Thumb-2 vector table.

### 2. Protocol: BCDC (not msgbuf)

A critical finding from the strings: the firmware contains references to **`bcmcdc.c`** — this is the **Broadcom CDC (Common Data Channel)** protocol, NOT the newer `msgbuf` protocol used by newer PCIe chips.

This is significant because:
- brcmfmac supports BCDC for SDIO/USB devices
- brcmfmac supports msgbuf for PCIe devices
- The BCM4360 appears to use **BCDC over PCIe** — a combination brcmfmac may not currently handle

However, the firmware also contains `pciedev_msg.c` and `pciedngl_*` (PCIe dongle) functions, confirming it's a PCIe device that uses dongle-style messaging.

### 3. Offload engine references

The firmware contains references to offload capabilities:
- `BCM_OL_BEACON_ENABLE` — beacon offload
- `BCM_OL_UNUSED`
- `bcm_olmsg_init`, `bcm_olmsg_peekbytes` — offload messaging

This is the "offload" architecture where the firmware handles beacons, ARP, etc. to let the host CPU sleep — typical FullMAC behaviour.

### 4. The firmware is an RTOS ("hndrte")

The string `pcidongle_probe:hndrte_add_isr failed` reveals the firmware runs on **hndrte** — Broadcom's proprietary RTOS for wireless chipsets. This is the same RTOS found by Quarkslab in their reverse engineering work.

### 5. Both firmwares are very similar

The 4352pci and 4350pci variants have:
- Nearly identical sizes (432KB vs 435KB)
- Same string count (~2700)
- Same notable strings
- Same build date, same version
- Slight differences likely for chip-specific register addresses

## Which firmware does BCM4360 use?

Our chip is BCM4360 rev 3 (PCI ID 14e4:43a0). Based on the naming:
- **4352pci** likely targets BCM4352 (PCI ID 14e4:43b1) and BCM4360 (14e4:43a0)
- **4350pci** likely targets BCM4350 (14e4:43a3) and variants

The `wl` driver source would select between them based on chip ID. We'll need to trace the driver init or examine the binary to confirm which one is loaded on our hardware. Given our chip is "4360", either could apply — the naming is by chip family, not exact chip ID.

## Firmware format for brcmfmac

brcmfmac expects firmware files in a specific format:
- Raw binary (`.bin`) loaded to the ARM core's RAM
- CLM blob (`.clm_blob`) for regulatory data
- NVRAM file (`.txt`) for board-specific calibration

Our extracted binaries appear to be raw ARM code. We'll need to determine:
1. Whether the format is compatible with brcmfmac's firmware loader
2. Whether there's a header that brcmfmac expects (e.g., TRX header)
3. Whether CLM and NVRAM data is embedded or separate

## Next Steps

1. **Determine which firmware variant our chip uses** — trace `wl` driver init or disassemble the selection logic
2. **Compare firmware header format** against what brcmfmac expects in `firmware.c`
3. **Disassemble the vector table** — confirm Thumb-2 entry points, map the ISR handlers
4. **The BCDC-over-PCIe finding is critical** — investigate whether brcmfmac can handle this or if we need to add this combination
