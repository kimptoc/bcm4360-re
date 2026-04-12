# BCM4360 Core Enumeration Results — Analysis

**Date:** 2026-04-12
**Chip:** BCM4360 (0x4360), rev 3, package 0

## Core Map

The chip has **9 cores** on its BCMA backplane (the ChipCommon ID field said 5, but the EROM reveals 9 — the field only holds 4 bits, so >15 wraps to 0 and values like 5 may only count major cores):

| # | Manufacturer | Core ID | Name | Rev | Address | Wrapper | Notes |
|---|---|---|---|---|---|---|---|
| 0 | Broadcom | 0x800 | **ChipCommon** | 43 | 0x18000000 | 0x18100000 | Main control, clock, GPIO. 2 slave ports: 4KB + 16MB |
| 1 | Broadcom | 0x812 | **IEEE 802.11 (D11)** | 42 | 0x18001000 | 0x18101000 | The wireless MAC/PHY core — the important one |
| 2 | Broadcom | 0x83E | **ARM CR4** | 2 | 0x18002000 | 0x18102000 | The CPU that runs the firmware |
| 3 | Broadcom | 0x83C | **PCIe Gen2** | 1 | 0x18003000 | 0x18103000 | Host interface |
| 4 | Broadcom | 0x81A | **USB 2.0 Device** | 17 | 0x18004000 | 0x18104000 | Possibly unused in this PCIe card |
| 5 | ARM | 0x135 | **AMBA AXI** (bridge) | 0 | 0x18000000 | 0x18108000 | Interconnect fabric |
| 6 | ARM | 0x367 | **OOB Router** | 0 | 0x18109000 | — | Out-of-band signaling router |
| 7 | ARM | 0x366 | **Unknown** | 0 | 0x1810A000 | — | Possibly EROM itself or debug |
| 8 | ARM | 0x301 | **Unknown** | 0 | 0x18200000 | — | 1MB region — possibly SRAM? |

## Key Findings

### 1. ARM CR4 confirmed
The chip uses an **ARM Cortex-R4** (core 0x83E, rev 2), not CM3. This matches Quarkslab's analysis of newer Broadcom chips. The CR4 is a real-time processor — fast, no MMU, suitable for firmware.

The CR4 has two memory regions on slave port 1:
- **0x00000000 — 0x000A0000** (640KB) — likely the main RAM where firmware is loaded
- **0x000E0000 — 0x000E8000** (32KB) — likely TCM (Tightly Coupled Memory) or ROM

### 2. D11 core rev 42
The wireless core is **D11 rev 42**. This is important — brcmfmac and b43 both key off D11 core revision to determine capabilities. Rev 42 is an 802.11ac-era core.

For comparison:
- BCM43602 (supported by brcmfmac) has D11 rev 44
- BCM4339 (supported by brcmfmac) has D11 rev 37
- Older b43-supported chips have D11 rev < 30

### 3. PCIe Gen2 core
The chip uses **PCIe Gen2** (core 0x83C), the same as used by brcmfmac-supported chips. This is very promising — brcmfmac already knows how to talk to this PCIe core type.

### 4. Memory layout
The PCIe core has a large BAR mapping:
- 0x08000000 — 128MB host-visible window
- Plus a 64-bit DMA region (high bit 0x80000000)

The ARM CR4's 640KB RAM at 0x00000000 is where the firmware lives. The firmware blob extracted from `wl.ko` should be approximately this size.

### 5. ChipCommon rev 43
A mature ChipCommon revision with PMU, clock control, GPIO, and EROM support.

## Comparison with brcmfmac-supported chips

The core layout is **very similar** to chips already supported by brcmfmac:
- Same backplane bus (BCMA)
- Same PCIe Gen2 core (0x83C)
- Same ARM CR4 CPU core (0x83E)
- Same ChipCommon core (0x800)
- Same D11 wireless core (0x812), just a different revision

This strongly suggests that the BCM4360 speaks the same or very similar protocol to brcmfmac-supported PCIe chips. The main unknowns are:
1. The exact firmware format expected
2. Any D11 rev 42-specific initialization quirks
3. The message protocol version (msgbuf vs older BCDC over PCIe)

## Next Steps

1. **Extract firmware from `wl.ko`** — look for a ~640KB ARM binary
2. **Compare D11 rev 42 against brcmfmac's supported revisions** — check `chip.c` for how close our chip is to supported ones
3. **Check if brcmfmac's PCIe init code can handle this chip** — the PCIe Gen2 core is the same, so the bus layer should work
