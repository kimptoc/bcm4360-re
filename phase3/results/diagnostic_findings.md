# BCM4360 Diagnostic Findings — 2026-04-12

## Overview

After Test 1 (crash due to wrong rambase) and Test 2 (freeze writing firmware to
active TCM), we built a read-only diagnostic module to characterize the BCM4360's
BAR2 memory layout before attempting firmware download.

## Hardware Facts Established

| Property | Value |
|---|---|
| Chip | BCM4360/3 (MacBookPro11,1) |
| BAR0 | phys=0xb0600000 size=0x8000 (32KB, register window) |
| BAR2 | phys=0xb0400000 size=0x200000 (2MB, TCM direct access) |
| rambase | 0x0 (corrected from 0x180000) |
| ramsize | 0xA0000 (640KB) |
| ARM CR4 CAP | 0x00000214 — 4 A-banks, 1 B-bank |

## ARM CR4 TCM Banks

The ARM CR4 has 5 memory banks total:
- **A-banks (idx 0-3)**: info=0x00000c0f, PDA=0x00000000 (powered on)
- **B-bank (idx 4)**: Accessing via BANKIDX register **hangs the bus** — must NOT be accessed

Bank info 0x00000c0f decoding (BANKINFO register at offset 0x44):
- Bits [3:0] = 0xF → bank size encoding
- Bits [11:8] = 0xC → bank type/config

Each A-bank is 128KB × 4 = 512KB total A-bank TCM. The full TCM is 640KB
(ramsize=0xA0000), so 128KB remains in the B-bank at backplane 0xE0000.

## BAR2 Memory Map

BAR2 maps TCM directly starting at offset 0:

| BAR2 Offset | Content | Notes |
|---|---|---|
| 0x000000 | 0x025d4304 | TCM start — wl firmware residue |
| 0x010000 | 0x260f0327 | TCM data |
| 0x020000 | 0x3081503f | TCM data |
| 0x030000 | 0x04c40174 | TCM data |
| 0x040000 | 0xa019644a | TCM data |
| >0x0A0000 | **HANGS** | Beyond ramsize, reads cause bus hang |

Confirmed: BAR2 offset 0 = TCM backplane address 0 = rambase. The first 640KB
(0x0-0x9FFFF) is accessible TCM. Reads beyond this range hang the PCIe bus
worker thread (but don't crash the system).

## Key Findings

1. **rambase=0x0 is correct** — BAR2[0] contains valid TCM data (wl firmware residue)
2. **Banks are already powered on** — PDA=0 for all A-banks on fresh probe
3. **B-bank is inaccessible via BANKIDX** — accessing index 4 hangs the bus
4. **BAR2 reads beyond 640KB hang** — the 2MB BAR2 is only populated for the first 640KB
5. **The ARM CR4 is properly halted** by `brcmf_chip_cr4_set_passive` during chip recognition

## Critical: memcpy_toio Hangs, iowrite32 Works

**Test 4 (diag.8)**: Single u32 write to TCM[0] — OK (0xDEADBEEF readback matched)

**Test 5 (diag.9)**: Bulk write test:
- 4KB via iowrite32 loop: 0 errors in 1,024 words
- 64KB via iowrite32 loop: 0 errors in 16,384 words
- 256KB via iowrite32 loop: 0 errors in 65,536 words
- `memcpy_toio` of 442KB firmware: **HANGS** (worker thread stalls, system stays up)

**Root cause**: `memcpy_toio` on x86-64 uses `rep movsq` (64-bit transfers) or wider
SIMD instructions. The BCM4360's PCIe interface only supports 32-bit write transactions
to TCM. Wider transactions cause a bus hang.

**Fix**: Replace `memcpy_toio` with 32-bit `iowrite32` loop for BCM4360 firmware and
NVRAM download. Implemented as `brcmf_pcie_memcpy_toio32()`.

## Test 6: Firmware Download with iowrite32

Firmware download using iowrite32 loop was attempted. System crashed — likely during
ARM CR4 restart in `brcmf_pcie_exit_download_state` or early firmware execution.
The firmware download itself should have succeeded (based on bulk write tests passing).
Investigation ongoing.

## Implications for Firmware Download

- Firmware (442KB) fits within 640KB TCM
- **Must use 32-bit writes only** — no memcpy_toio, no 64-bit transactions
- Bank power-on added to `brcmf_pcie_enter_download_state` (A-banks 0-3, skip B-bank)
- No need to access B-bank for basic operation
- NVRAM is placed at end of TCM (rambase + ramsize - nvram_len)
- Other memcpy_toio calls (ring info, random seed) may also need 32-bit conversion

## Diagnostic Versions

1. **v1 (diag.3)**: BAR2 reads at 0x000000-0x040000, 5 offsets — all readable
2. **v2 (diag.4)**: Added CR4 bank reads — hung on B-bank (index 4)
3. **v3 (diag.5/6)**: A-banks only (0-3), bank power-on, full BAR2 scan — scan hung past TCM range
4. **v4 (diag.8)**: Single u32 write test — OK, ARM halted confirmed (IOCTL=0x21)
5. **v5 (diag.9)**: Bulk iowrite32 OK, memcpy_toio hangs
6. **v6 (diag.10)**: Full firmware download with iowrite32 — crash during ARM restart or FW exec

## Source Files

- Diagnostic output: `phase3/logs/diag.3` through `phase3/logs/diag.10`
- Full dmesg captures: `phase3/logs/dmesg.1`, `phase3/logs/dmesg.2`
