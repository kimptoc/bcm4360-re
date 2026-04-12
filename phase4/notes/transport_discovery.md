# Phase 4A — Transport Discovery Findings

**Date:** 2026-04-12

## Executive Summary

**The BCM4360 is NOT a FullMAC dongle device.** Static analysis of `wl.ko` (5,319 symbols,
7.3MB) reveals a fundamentally different architecture than what was assumed in the Phase 4 plan.

The `wl` driver operates as a **SoftMAC NIC driver with an offload engine**:
- **Host** runs the complete 802.11 MAC stack (`wlc_*`, 2,958 functions)
- **D11 core** runs microcode for low-level frame timing/ACK/retransmission
- **ARM CR4** runs a thin offload firmware for power-saving tasks only
- **DMA** is through D11 TX/RX FIFOs (standard Broadcom DMA64), not protocol transport

There is **no BCDC-over-PCIe transport protocol** to reverse-engineer. The "BCDC" references
found in the firmware during Phase 1 are likely part of internal firmware messaging or dead
code from a shared Broadcom codebase — not a host-firmware command protocol.

This finding invalidates the Phase 4 plan as originally conceived.

---

## Architecture: Split-MAC NIC with Offload Engine

```
┌─────────────────────────────────────────────────────┐
│                    HOST (wl.ko)                      │
│                                                      │
│  cfg80211 ←→ wlc_* (full 802.11 MAC)               │
│                  │                                   │
│          wlc_bmac_* (bus-side MAC)                   │
│           ╱           ╲                              │
│    Direct MMIO      wlc_ol_* (offload control)      │
│    (BAR0/BAR2)        │                              │
│         │          bcm_olmsg_* (shared TCM msgs)     │
│         │              │                             │
│    ┌────┴────┐    ┌────┴────┐                       │
│    │ D11 core│    │ ARM CR4 │                       │
│    │ (ucode) │    │  (OL FW)│                       │
│    │ rev 42  │    │  "bmac" │                       │
│    └─────────┘    └─────────┘                       │
│         │                                            │
│    DMA64 engine (dma_attach, dma64proc)             │
│    TX/RX frame DMA through D11 FIFOs                │
└─────────────────────────────────────────────────────┘
```

### Evidence for NIC Mode (Direct Hardware Access)

1. **139 `wlc_bmac_*` functions** with full implementations (not RPC stubs):
   - `wlc_bmac_read_shm` / `wlc_bmac_write_shm` — direct SHM register access
   - `wlc_bmac_corereset` — direct core reset via si_* backplane
   - `wlc_bmac_txfifo` — direct D11 FIFO DMA submission
   - `wlc_bmac_init` — full hardware initialization

2. **D11 ucode embedded in host driver** (loaded to D11 core, NOT ARM):
   - `d11ucode42` — 42.4 KB of D11 microcode for rev 42
   - `d11ac1initvals42` — 4.8 KB of register init values
   - `d11ucode_wowl42` — 35.0 KB of WoWL ucode
   - Host loads ucode directly via `wlc_bmac_write_template_ram`

3. **DMA engine in host driver**:
   - `dma_attach` — sets up DMA64 channels for D11 FIFOs
   - `dma64proc` — DMA64 processing procedures (rodata jump table)
   - `osl_dma_alloc_consistent` / `osl_dma_map` — Linux DMA mapping wrappers
   - This is D11 frame DMA, not a protocol transport

4. **Standard PCI ISR model**:
   - `wl_isr` → `wlc_isr` → `wlc_intrsoff/on/restore/upd`
   - Uses `request_threaded_irq` / `free_irq`
   - Interrupts from D11 core (TX complete, RX ready, etc.)

### Evidence for Offload Engine on ARM CR4

The ARM CR4 firmware ("4352pci-bmac") runs as a thin offload helper:

1. **Offload message types** (`BCM_OL_*`):
   - Beacon: `BCM_OL_BEACON_ENABLE/DISABLE`, `BCM_OL_BCNS_PROMISC`
   - ARP/ND: `BCM_OL_ARP_ENABLE/DISABLE/SETIP`, `BCM_OL_ND_*`
   - WoWL: `BCM_OL_WOWL_ENABLE_START/COMPLETE`
   - Scan: `BCM_OL_SCAN`, `BCM_OL_SCAN_CONFIG/PARAMS/RESULTS/CHANSPECS`
   - GTK: `BCM_OL_GTK_ENABLE/UPD`
   - Packet filter: `BCM_OL_PKT_FILTER_ADD/ENABLE/DISABLE`
   - Power: `BCM_OL_L2KEEPALIVE_ENABLE`, `BCM_OL_TCP_KEEP_*`

2. **Offload messaging interface** (`bcm_olmsg_*`):
   - `bcm_olmsg_init` / `bcm_olmsg_create` / `bcm_olmsg_deinit`
   - `bcm_olmsg_writemsg` / `bcm_olmsg_readmsg`
   - `bcm_olmsg_peekbytes` / `bcm_olmsg_peekmsg_len`
   - Ring buffer in shared TCM memory, NOT DMA

3. **TCM semaphore for synchronization**:
   - `tcm_sem_enter` / `tcm_sem_exit` / `tcm_sem_cleanup`
   - Protects shared TCM regions between host and ARM

4. **ARM control**:
   - `wlc_ol_arm_halt` / `wlc_ol_is_arm_halted`
   - `wlc_ol_enable` / `wlc_ol_disable`
   - `wlc_ol_up` / `wlc_ol_down` / `wlc_ol_restart`
   - `wlc_ol_mb_poll` — mailbox poll for ARM events
   - `wlc_ol_dpc` — deferred procedure call for offload processing

### Dead Code: RPC Infrastructure

The binary contains RPC infrastructure (`WLRPC_WLC_BMAC_*_ID` command IDs, `bcm_rpc_call`,
`bcm_rpc_tp_*`) that is NOT used in NIC/PCIe mode. This is from Broadcom's shared codebase
that supports both NIC mode and dongle/RPC mode:

- `wlc_high_stubs.c` — compiled-in stubs for the split-MAC RPC path
- `bcm_rpc_tp_rte.c` — firmware-side RPC transport (from embedded firmware blob)
- `WLRPC_WLC_BMAC_*_ID` — ~100 RPC command IDs (unused in NIC mode)

In NIC mode, `wlc_bmac_*` functions access hardware directly via MMIO.
In dongle mode (USB/SDIO, not PCIe NIC), they would be RPC stubs.

---

## Embedded Resources in wl.ko

### D11 Microcode (for BCM4360 D11 rev 42)

| Resource | Symbol | Size | Purpose |
|---|---|---|---|
| D11 ucode | `d11ucode42` | 42.4 KB | Normal operation microcode |
| Init values | `d11ac1initvals42` | 4.8 KB | Register initialization |
| BS init values | `d11ac1bsinitvals42` | ~5 KB | Band-specific init values |
| WoWL ucode | `d11ucode_wowl42` | 35.0 KB | Wake-on-WLAN microcode |
| BOM version | `d11ucode_ge40_bommajor/minor` | 8 bytes | Bill of materials version |

The driver also embeds ucode for many other D11 revisions (4 through 46), plus WoWL
variants — the codebase supports a wide range of Broadcom chips.

### ARM CR4 Firmware (offload engine)

| Resource | Name | Size | Purpose |
|---|---|---|---|
| FW variant 1 | `4352pci-bmac` | 431.9 KB | Offload FW for BCM4352/4360 |
| FW variant 2 | `4350pci-bmac` | 435.3 KB | Offload FW for BCM4350 |

Both are v6.30.223.0 (Dec 2013), Thumb-2 ARM binaries running hndrte RTOS.

---

## Implications for the Project

### What Phase 4's Original Plan Got Wrong

The plan assumed:
1. ❌ BCM4360 firmware runs a FullMAC stack speaking BCDC protocol
2. ❌ The host sends BCDC commands and receives responses over PCIe
3. ❌ We need to reverse-engineer a "BCDC-over-PCIe transport"
4. ❌ brcmfmac is the right framework (just needs a new protocol backend)

Reality:
1. ✅ BCM4360 firmware is a thin offload engine, NOT a FullMAC firmware
2. ✅ The host runs the ENTIRE 802.11 MAC stack and directly programs hardware
3. ✅ Host-firmware communication is simple olmsg over shared TCM
4. ✅ The correct framework is mac80211 + a SoftMAC driver (like brcmsmac)

### What This Means for Building an Open Driver

**The effort required is dramatically larger than originally estimated.**

Instead of building a thin transport layer, we need to implement:

1. **D11 core programming** — load ucode, configure registers, manage state machine
2. **PHY driver** — AC PHY (rev 42) calibration, channel switching, TX power control
3. **DMA engine** — D11 TX/RX FIFO DMA setup and frame processing
4. **802.11ac MAC** — or integrate with Linux mac80211 (preferred)
5. **Offload engine control** — optional, for power management features

This is comparable to what brcmsmac does for older chips (BCM43xx, D11 rev ≤ 30),
but for a newer 802.11ac chip with different register maps, PHY, and DMA layout.

### Possible Paths Forward

**Option A: Extend brcmsmac for D11 rev 42 (802.11ac)**
- brcmsmac already integrates with mac80211
- Add D11 rev 42 ucode handling, AC PHY driver, updated DMA
- Very large effort (~10K-50K lines) but builds on existing infrastructure
- Requires deep understanding of AC PHY programming

**Option B: Minimal standalone SoftMAC driver**
- Start from scratch with just BCM4360 support
- Use mac80211 for the 802.11 MAC stack
- Focus on D11+DMA+PHY from wl.ko reverse engineering
- Cleaner but no code reuse

**Option C: Offload-heavy approach (speculative)**
- The ARM firmware supports scan offload (`BCM_OL_SCAN_*`)
- If the firmware can handle enough operations via olmsg...
- This might be a simpler path but is VERY speculative
- Need to test: does `wlc_ol_enable` + scan offload actually produce results?

**Option D: Hardware replacement**
- Replace BCM4360 with BCM43602 (same PCIe slot, supported by brcmfmac)
- ~$15-30 for the card
- Guaranteed working solution but doesn't advance the project goal

### Key Assets We Now Have

1. **D11 ucode for rev 42** — extractable from wl.ko (~42KB)
2. **D11 init values** — register programming sequences
3. **5,319 symbols** in wl.ko — complete function-level reference
4. **PHY programming code** — `wlc_phy_*` functions (~1000+ symbols)
5. **DMA engine code** — `dma_attach`, `dma64proc`
6. **Offload interface** — `bcm_olmsg_*` protocol fully enumerated
7. **Offload firmware** — already extracted and downloadable to ARM CR4

---

## Next Steps

Before deciding on a path, we should:

1. **Test the offload engine** — Load the OL firmware, set up `bcm_olmsg` in TCM,
   send `BCM_OL_SCAN` to see if the ARM can independently scan
2. **Extract D11 ucode42** — Pull the binary from wl.ko for analysis
3. **Map the D11 register interface** — Using `d11ac1initvals42` and `wlc_bmac_*` disassembly
4. **Study brcmsmac** — Understand how far it can be extended toward D11 rev 42
5. **Compare with b43 community effort** — The b43 project reverse-engineered older D11 cores;
   their documentation at bcm-v4.sipsolutions.net may inform our approach

---

## Source

- **Binary analyzed:** `wl.ko` 6.30.223.271 (broadcom-sta, kernel 6.12.80)
- **Path:** `/nix/store/5z70mn754m7flxs8kll77y631v2aldvq-broadcom-sta-6.30.223.271-59-6.12.80/lib/modules/6.12.80/kernel/net/wireless/wl.ko`
- **Format:** ELF 64-bit x86-64, not stripped, 5,319 symbols
