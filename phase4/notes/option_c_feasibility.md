# Option C Feasibility Assessment — Offload-Heavy Approach

**Date:** 2026-04-12
**Verdict: NOT VIABLE as a standalone driver**

## Summary

The BCM4360 offload firmware is a **power-management helper**, not an independent WiFi
engine. It requires the full host MAC stack (`wlc_*`) to initialize hardware, associate
with networks, and handle data transfer. The firmware only takes over monitoring duties
(beacon, ARP, WoWL) after the host has established a connection.

Attempting to use just the offload firmware without the host MAC stack will fail because:
1. The D11 ucode (loaded by the host to the D11 core) will be missing
2. PHY calibration and radio configuration won't be done
3. DMA channels for TX/RX frames won't be set up
4. The firmware has no association, authentication, or data path capability

## Detailed Findings

### olmsg Protocol (Fully Reverse-Engineered)

**Ring buffer structure** (64KB DMA-coherent host memory, 0x10000 bytes):

```c
// Two ring buffers: host→firmware (ring 0) and firmware→host (ring 1)
struct olmsg_ring {
    uint32_t data_offset;  // Offset of ring data from buffer start
    uint32_t size;         // Ring data area size (0x7800 = 30KB each)
    uint32_t read_ptr;     // Consumer advances this
    uint32_t write_ptr;    // Producer advances this
};

struct olmsg_buf {
    struct olmsg_ring ring[2];   // [0]=host→fw, [1]=fw→host (32 bytes)
    uint8_t ring0_data[0x7800]; // Host-to-firmware ring data
    uint8_t ring1_data[0x7800]; // Firmware-to-host ring data
};
// Total: 0x20 + 0x7800 + 0x7800 = 0xF020 bytes (fits in 64KB)
```

**Message format** (12-byte header + variable payload):

```c
struct ol_msg {
    uint32_t type;         // BCM_OL_* message type enum
    uint32_t seq;          // Sequence number (set by bcm_olmsg_writemsg)
    uint32_t payload_len;  // Length of payload following header
    uint8_t  payload[];    // Variable-length message data
};
// Total message size = 12 + payload_len
```

### Shared Info Structure (TCM Handshake)

Placed at TCM offset `ramsize - 0x2F5C` (= 0x9D0A4 for BCM4360):

```c
struct ol_shared_info {
    uint32_t magic_start;      // 0x000: 0xA5A5A5A5
    uint32_t olmsg_phys_lo;    // 0x004: DMA physical addr of olmsg_buf (low 32)
    uint32_t olmsg_phys_hi;    // 0x008: DMA physical addr (high 32, usually 0)
    uint32_t olmsg_size;       // 0x00C: 0x10000 (64KB)
    // ...fields at 0x10-0x1F...
    uint32_t field_14;         // 0x014: 0 initially
    uint32_t field_18;         // 0x018: 0 initially
    uint32_t field_20;         // 0x020: config value from wlc
    uint8_t  mac_addr[6];      // 0x024: MAC address
    // ...gap...
    // 0x2028: fw_init_done    // Firmware sets non-zero when ready
    // ...
    uint32_t magic_end;        // 0x2F38: 0x5A5A5A5A
};
// Total structure: ~12KB
```

### Boot Handshake Sequence (from wlc_ol_up)

```
1. Host allocates 64KB DMA-coherent buffer for olmsg
2. Host initializes olmsg ring buffer structure (bcm_olmsg_create)
3. Host halts ARM CR4 (si_core_disable on ARM core)
4. Host downloads offload firmware to TCM:
   - BCM4360/4352: uses 4352pci-bmac variant, 442,233 bytes (0x6BF79)
   - Destination: TCM offset 0x0 (BAR2 base)
   - Method: 32-bit iowrite32 loop (NOT memcpy_toio)
5. Host writes shared_info at TCM offset 0x9D0A4:
   - Magic markers at start and end
   - DMA physical address of olmsg buffer
   - MAC address and config values
   - Clears fw_init_done flag (offset 0x2028)
6. Host writes 0x20 to chip register 0x408 (ARM core control?)
7. Host releases ARM (si_core_reset)
8. Host polls shared_info[0x2028] every 1ms for up to 2 seconds
9. If firmware writes non-zero → init complete, proceed
10. If timeout → firmware failed to initialize
```

### Offload Enable Sequence (from wlc_ol_enable)

**Called ONLY after host MAC has fully associated with an AP.** Sends BSS context:

```
Preconditions checked by wlc_ol_enable:
- BSS is associated (bss->associated != 0)
- BSS has a channel (bss->channel != 0)
- OL engine is up (ol_info->is_up != 0)
- OL capability flag set

Message contains:
- Current MAC address and BSSID
- Channel/chanspec
- AID (Association ID)
- DTIM count
- Security parameters (28 bytes at offset 0x2F)
- IE (Information Element) data from current beacon
- PHY configuration
```

### What the Offload Firmware CAN Do

| Capability | Message Types | Independence |
|---|---|---|
| Beacon monitoring | BCM_OL_BEACON_ENABLE/DISABLE | Needs prior association |
| ARP offload | BCM_OL_ARP_ENABLE/DISABLE/SETIP | Needs IP from host |
| ND offload | BCM_OL_ND_ENABLE/DISABLE/SETIP | Needs IP from host |
| WoWL | BCM_OL_WOWL_ENABLE_START/COMPLETE | Needs full BSS context |
| GTK rekeying | BCM_OL_GTK_ENABLE/UPD | Needs security keys |
| Packet filtering | BCM_OL_PKT_FILTER_ADD/ENABLE | Config from host |
| PFN scan | BCM_OL_PFN_ADD, BCM_OL_SCAN_* | Needs HW init by host |
| L2 keepalive | BCM_OL_L2KEEPALIVE_ENABLE | Needs association |
| TCP keepalive | BCM_OL_TCP_KEEP_CONN/TIMERS | Needs association |

### What the Offload Firmware CANNOT Do

- **Scan independently** — PFN scan needs D11 ucode + PHY calibration done by host
- **Associate with AP** — No association/authentication protocol
- **Transmit data frames** — BCM_OL_ARM_TX is for limited offload TX only
- **Receive data frames** — No general-purpose RX path
- **Configure radio/PHY** — All hardware init is done by host's wlc_bmac layer
- **Load D11 ucode** — Host loads ucode to D11 core (separate from ARM firmware)
- **Set up DMA channels** — Host configures D11 DMA via dma_attach

### Why Option C Fails

The offload firmware activation sequence in the `wl` driver is:

```
wl_pci_probe
  └→ wlc_attach → wlc_bmac_attach    (HW enumeration)
      └→ wlc_up → wlc_bmac_up         (Load D11 ucode, calibrate PHY,
          │                              enable radio, set up DMA)
          └→ wlc_ol_up                 (Download OL FW to ARM, start ARM)
              └→ [user associates]
                  └→ wlc_ol_enable     (Send BSS context to ARM)
                      └→ ARM takes over monitoring
```

Steps before `wlc_ol_up` perform ~140 hardware initialization functions (the 139
`wlc_bmac_*` calls). Without this initialization, the ARM firmware finds:
- D11 core without ucode → can't send/receive frames
- PHY uncalibrated → radio doesn't work
- DMA not configured → no frame path
- No BSS context → nothing to monitor

## What We Gained

Although Option C isn't viable as a standalone driver, the reverse engineering produced
valuable results:

1. **Complete olmsg protocol** — message format, ring buffer layout, fully understood
2. **Shared info handshake** — exact TCM offset, magic markers, DMA address passing
3. **Boot sequence** — firmware download, ARM release, init polling (2s timeout)
4. **Firmware selection** — BCM4360 uses 4352pci-bmac variant (442,233 bytes)
5. **Architecture confirmation** — SoftMAC with offload, not FullMAC
6. **Phase 3 crash explained** — Our Phase 3 ARM release crashed because:
   - We loaded the OL firmware but didn't write the shared_info structure
   - Firmware started, couldn't find valid shared_info (no 0xA5A5A5A5 magic)
   - Firmware panicked and corrupted host state

## Revised Assessment of Paths Forward

### Option A: SoftMAC Driver (mac80211 + D11 rev 42)
**Effort:** Very large (10K-50K lines, months of work)
**Feasibility:** High — all necessary code is visible in wl.ko's 5,319 symbols
**Approach:** Extend brcmsmac or build new driver for D11 rev 42 + AC PHY

### Option B: Prove Firmware Communication Works
**Effort:** Small (days)
**Approach:** Build a test module that:
1. Downloads OL firmware to TCM
2. Writes proper shared_info structure
3. Releases ARM with interrupt handler registered
4. Polls for fw_init_done
5. Sends a simple olmsg and reads response

This would prove the communication path works end-to-end and give us a
platform for further experimentation. It's the natural next step regardless
of which larger approach we choose.

### Option D: Hardware Replacement
**Effort:** Minimal ($15-30 for BCM43602 card)
**Feasibility:** Guaranteed
**Drawback:** Doesn't advance the reverse engineering goal
