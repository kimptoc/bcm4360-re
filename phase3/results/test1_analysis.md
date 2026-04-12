# Test 1 Results — 2026-04-12

## Summary

Module loaded, chip recognized, firmware loaded, but **crashed during firmware download to TCM** due to BAR2 size limitation.

## Timeline

1. `brcmfmac` loaded successfully (PCIe-only build, depends on cfg80211 + brcmutil)
2. Chip identified as **BCM4360/3** on MacBookPro11,1
3. Firmware allocated: `brcm/brcmfmac4360-pcie` for chip BCM4360/3
4. Board-specific firmware (`...Apple Inc.-MacBookPro11,1.bin`) — not found (non-fatal)
5. Generic firmware (`brcmfmac4360-pcie.bin`) — loaded from `firmware_4352pci.bin`
6. NVRAM (`.txt`), CLM (`.clm_blob`), txcap (`.txcap_blob`) — not found (non-fatal)
7. **CRASH** in `brcmf_pcie_setup` -> `brcmf_pcie_download_fw_nvram` -> `brcmf_pcie_write_ram32` -> `iowrite32`

## Crash Analysis

**Faulting instruction:** `iowrite32(0, addr)` at `brcmf_pcie_setup+0x1c4`

**What it was doing:** Writing zero to the last 4 bytes of TCM RAM — this is the shared memory flag that brcmfmac uses to detect when firmware starts running. Code: `brcmf_pcie_write_ram32(devinfo, devinfo->ci->ramsize - 4, 0)` at `pcie.c:1713`.

**Address calculation:** `addr = devinfo->tcm + rambase + ramsize - 4`

**Register state at crash:**
- RAX = `0x180000` (rambase)
- RDI = `0x0` (value being written)
- RSI = CR2 = `ffffcff9c461fffc` (target address — unmapped!)
- PTE = 0 (completely unmapped page)

**BCM4360 PCI BAR layout:**
- BAR0: `0xb0600000 - 0xb0607fff` (32KB) — PCIe registers
- BAR2: `0xb0400000 - 0xb05fffff` (2MB / 0x200000) — TCM

**The problem:**
- rambase = `0x180000` (from our patch, same as BCM43602)
- ramsize = ~`0xA0000` (640KB, detected from hardware via ARM CR4 capabilities)
- rambase + ramsize = `0x220000` — **exceeds BAR2 size (0x200000) by 128KB**
- The `iowrite32` at offset `0x21FFFC` hits an unmapped page

## Root Cause

The BCM4360 has a **2MB BAR2**, smaller than newer chips like BCM43602 (which typically have 8MB+). Our assumed rambase of `0x180000` leaves only 512KB of addressable TCM, but the chip has ~640KB of RAM.

## Possible Fixes

1. **Wrong rambase** — BCM4360 may use a lower rambase than BCM43602. Need to determine the actual value from hardware or the wl driver.

2. **Backplane window register** — Some Broadcom chips use a register in BAR0 to shift which backplane address range BAR2 maps. BCM4360 may need this.

3. **Different firmware upload path** — The BCM4360 may load firmware differently from pure dongle chips. The `memcpy_toio` to `tcm + rambase` may not be the right mechanism.

## Key Positive Findings

- The module loads and the chip is recognized
- The firmware file is found and loaded into memory
- The driver gets past chip enumeration and enters PCIe setup
- The crash is well-understood and deterministic

## Next Steps

- Investigate the BCM4360's actual TCM memory map (MMIO trace of `wl` driver, or analysis of `wl.ko` firmware upload code)
- Check if BCM4360 uses a backplane window for TCM access
- Determine correct rambase by reading hardware registers or tracing `wl`
