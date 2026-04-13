# Level 4 Revised Plan — Shared Info Handshake

**Date:** 2026-04-13
**Status:** In progress

## Problem

Level 4 (ARM release) crashes the host ~100-200ms after ARM release, both on
cold boot and warm handoff. The firmware expects a valid shared_info structure
at TCM offset 0x9D0A4. Without it, the firmware panics and corrupts the PCIe
link, causing a hard host lockup.

## Plan

Modify level 4 to write the proper shared_info structure before ARM release,
matching the wlc_ol_up boot handshake. Keep bus mastering OFF for safety — the
firmware needs DMA to use the olmsg buffer, but we want to see if the shared_info
alone prevents the crash.

### Step 1: Allocate DMA buffer (olmsg)

- `dma_alloc_coherent()` — 64KB coherent buffer
- Initialize olmsg ring structure (2 rings, host→fw and fw→host)
- This gives us a valid physical address to put in shared_info

### Step 2: Write shared_info to TCM

At TCM offset 0x9D0A4 (SHARED_INFO_OFFSET):

| Offset | Value | Purpose |
|--------|-------|---------|
| 0x000 | 0xA5A5A5A5 | magic_start |
| 0x004 | olmsg_dma_lo | DMA physical address (low 32) |
| 0x008 | olmsg_dma_hi | DMA physical address (high 32) |
| 0x00C | 0x10000 | olmsg buffer size (64KB) |
| 0x2028 | 0x00000000 | fw_init_done (cleared, firmware sets) |
| 0x2F38 | 0x5A5A5A5A | magic_end |

Zero the entire 12KB structure first, then write fields.

### Step 3: Release ARM (no DMA, no bus master)

- Bus mastering stays OFF — firmware can't actually DMA
- PCIe interrupts masked
- ISR registered as safety net

### Step 4: Observe

- Poll fw_init_done every 1ms for 2s
- If firmware writes non-zero → it initialized successfully (even without DMA)
- If crash still happens at ~100ms → firmware tries DMA immediately and the
  missing bus master causes it to panic
- If timeout → firmware may need DMA to complete init

### Step 5: If no crash, enable DMA

- Enable bus mastering after firmware stabilizes
- Re-poll fw_init_done
- Read olmsg buffer for any firmware→host messages

## Expected Outcomes

1. **Best case**: shared_info prevents crash, firmware initializes, fw_init_done
   becomes non-zero. We can then communicate via olmsg.
2. **Likely case**: firmware stabilizes briefly but times out because DMA doesn't
   work (bus master OFF). No crash though — a controlled failure.
3. **Worst case**: crash still happens at ~100ms — firmware does something fatal
   even with valid shared_info (e.g., tries to configure PCIe link regardless).

## Source

Code for shared_info setup already exists in `level5_full_init()` (lines 890-936
of bcm4360_test.c). We're moving the shared_info portion into level 4.
