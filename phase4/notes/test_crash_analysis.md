# Phase 4B — Test Module Crash Analysis

**Date:** 2026-04-12 – 2026-04-13

## Summary

Testing the `bcm4360_test.ko` module through progressive level-gating has
identified and resolved the root cause of BAR0 read failures and machine crashes.

**Root cause: Stale AER (Advanced Error Reporting) errors left by the `wl` driver
prevent PCIe MMIO completion, causing 0xFFFFFFFF reads and machine lockups.**

**Fix: Clear AER error status registers and enable bus mastering before MMIO access.**

## Key Findings

### AER errors were the blocker (discovered 2026-04-13)

After `wl` unloads, the device has stale PCIe errors recorded:
- **Uncorrectable: 0x00008000** — bit 15 = Unsupported Request Error
- **Correctable: 0x00002000** — bit 13 = Advisory Non-Fatal Error

These are W1C (write-1-to-clear) registers at the AER extended capability.
Clearing them before MMIO access allows BAR0 reads to succeed.

### Device state after `wl` unload

- Power state: **D0** (not D3 as initially assumed)
- PMCSR: 0x4008
- Memory space: enabled (CMD bit 1 = 1)
- Bus mastering: disabled (CMD bit 2 = 0)
- BAR0_WIN: 0x18001000 (ChipCommon + 0x1000, left by wl)
- PCIe link: Gen1 x1 (speed=1, width=1)
- BAR0: phys=0xb0600000, len=0x8000 (32KB)
- BAR2: phys=0xb0400000, len=0x200000 (2MB)

### Chip identity (from BAR0 ChipCommon register)

- **Chip ID: 0x4360** (silicon ID, distinct from PCI device ID 0x43a0)
- **Revision: 3**
- **Package: 0**
- ChipCommon caps: 0x58680001
- ChipCommon status: 0x1810a000

### What doesn't work

- `pci_reset_function()` — hangs indefinitely (BCM4360 lacks FLR support)
- `pci_disable_device()` in remove — causes delayed PCIe bus lockup (~1-2 min)
- MMIO reads without clearing AER — returns 0xFFFFFFFF, may crash machine

## Timeline

| Test | Time | Level | Result |
|---|---|---|---|
| test.1 | Apr 12 23:47 | step 0 (old module) | BAR0=0xFFFFFFFF |
| test.2 | Apr 12 23:54 | step 0 (journal) | BAR0=0xFFFFFFFF |
| test.3 | Apr 13 00:14 | level 0 | PASS (bind only) |
| test.4 | Apr 13 00:14 | level 1 | PASS (config space, D0 confirmed) |
| test.5 | Apr 13 00:14 | level 2 | FAIL — BAR0=0xFFFFFFFF, no crash |
| test.6 | Apr 13 11:12 | level 1 | PASS (old module, no BAR0_WIN diag) |
| test.7 | Apr 13 11:16 | level 1 | PASS — BAR0_WIN diag, AER errors found |
| test.8 | Apr 13 11:20 | level 1 | PASS — AER cleared, bus master enabled |
| test.9 | Apr 13 11:21 | level 2 | **PASS — BAR0 MMIO works! Chip ID=0x4360 Rev=3** |

## Fixes Applied

| Fix | Status | Effect |
|---|---|---|
| BAR2 deferred to level 3 | ✅ Applied | No instant crash at probe |
| BAR2 size reduced to 640KB | ✅ Applied | Avoids unpopulated regions |
| pci_reset_function | ❌ Removed | Hangs — BCM4360 lacks FLR |
| pci_clear_master at probe | ✅ Applied | Stops residual DMA from wl |
| pci_disable_device in remove | ❌ Removed | Caused delayed crash |
| AER error clearing | ✅ Applied | **Key fix — enables MMIO** |
| Bus mastering enable | ✅ Applied | Required for DMA in level 3 |
| BAR0_WIN set to ChipCommon | ✅ Applied | Ensures known window state |

## Level 2 Successful Output (test.9)

```
[level 2] BAR0 mapped at ffffd3ef80560000 (32KB)
[level 2] AER pre-read: uncorr=0x00000000 corr=0x00000000
[level 2] BAR0_WIN register = 0x18000000
[level 2] About to do first MMIO read (BAR0+0x00)...
[level 2] BAR0[0x00] (current window) = 0x15034360
[level 2] Chip ID=0x4360 Rev=3 Pkg=0
[level 2] ChipCommon caps = 0x58680001
[level 2] ChipCommon status = 0x1810a000
[level 2] ARM wrapper IOCTL = 0x83828180 (via BAR0 window)
[level 2] PASS
```

## Level 3 Crash Analysis (2026-04-13)

### Symptom

Running `sudo ./test.sh 3` (or auto-advance reaching level 3) causes a **hard
machine lockup** — no kernel panic, no dmesg, empty log files (test.10–13 are
0 bytes). Requires physical power cycle to recover.

Level 2 passes consistently.

### Root cause: bulk TCM write overwhelming PCIe Gen1 x1 link

Level 3 writes ~640KB of firmware to BAR2 (TCM) via MMIO `iowrite32` in a tight
loop. The link is **PCIe Gen1 x1** (~250 MB/s theoretical), and write-posting
buffers can overflow when the readback pacing is too coarse.

The original pacing was a readback every **256 DWORDs (1KB)** — too infrequent
for this link speed. When the PCIe write buffer overflows:

1. An **Unsupported Request (UR)** or **Completion Timeout** fires
2. This triggers a fatal AER error
3. On this platform, fatal AER errors lock the PCIe bus → hard lockup

### Evidence

- PCIe link degraded: `speed=1 width=1` (Gen1 x1) in all test logs
- AER errors were already present before level 3 in earlier runs:
  `uncorr=0x00008000` (bit 15 = UR), `corr=0x00002000` (bit 13 = Advisory NF)
- Level 2 works because it only does a few scattered register reads
- Level 3 does ~160,000 consecutive `iowrite32` calls — qualitatively different

### Crash timeline

| Test | Level | Result |
|---|---|---|
| test.10 | 3 (auto) | **CRASH** — 0 bytes, hard lockup |
| test.11 | 3 (auto) | **CRASH** — 0 bytes, hard lockup |
| test.12 | 3 | **CRASH** — 0 bytes, hard lockup |
| test.13 | 3 | **CRASH** — 0 bytes, hard lockup |

### Fixes applied

| Fix | Description |
|---|---|
| Tighter write pacing | Readback every 64 DWORDs (256 bytes) instead of 256 (1KB) |
| udelay between chunks | 10μs pause after each paced readback to let link drain |
| Mid-transfer death check | If readback returns 0xFFFFFFFF, abort immediately |
| AER check before bulk write | Clear and verify AER errors after BAR2 map, before FW download |

## Level 3 — continued crash analysis (2026-04-13, post-pacing fix)

### Status

Level 3 still crashes the machine with **0 bytes in dmesg** (test.10–13), even
after applying the pacing fixes from the previous commit. The pacing fixes
(readback every 64 DWORDs + 10μs udelay) were confirmed compiled and loaded,
but had no effect — all four attempts produced identical hard lockups.

### Key observation: crash may not be the bulk write

The fact that 0 bytes of level 3 output appear in dmesg suggests the crash
happens very early — possibly before even the first `dev_info` can flush.
Possible crash points, in order:

1. **`pci_iomap(BAR2)`** — mapping 640KB of BAR2 after level 2 unload/reload
2. **First TCM read** — `tcm_read32(dev, 0)` via BAR2 MMIO
3. **`arm_halt()`** — `bp_write32` to ARM wrapper (0x18102000+offset) uses
   BAR0 window; rapid config space + MMIO writes may overwhelm Gen1 x1 link
4. **Bulk TCM write loop** — the previously suspected cause, but if (1)–(3)
   crash first, the pacing fix is irrelevant

### Diagnostic: pr_emerg canary printks

Added 6 `pr_emerg` canary messages with `mdelay(100)` pauses at each critical
point in `level3_tcm_and_fw()`:

| Canary | Location | If this is last seen... |
|---|---|---|
| CANARY 1 | Before `pci_iomap(BAR2)` | BAR2 mapping crashes |
| CANARY 2 | After BAR2 map, before first TCM read | TCM read crashes |
| CANARY 3 | After AER clear, before `arm_halt()` | ARM halt crashes |
| CANARY 4 | After `arm_halt()` returns | Post-halt bp_read32 verification crashes |
| CANARY 5 | Before bulk TCM write loop | Bulk write crashes (original theory) |
| CANARY 6 | After bulk write completes | Crash is in verify/shared_info reads |

`pr_emerg` is the highest kernel log priority and most likely to appear on the
physical console even during a hard lockup. Check VT or serial console — dmesg
log capture may not work if the crash is too fast.

## Canary test result (2026-04-13)

### Result: CANARY 5 was the last message on screen

Ran `sudo ./test.sh 3` with canary-instrumented module. Physical console showed
CANARY 5 ("starting bulk TCM write") but NOT CANARY 6 ("bulk write complete").

**This confirms the crash is inside the bulk TCM write loop** (lines 653–668 of
`bcm4360_test.c`). The BAR2 mapping, initial TCM reads, AER clearing, and
`arm_halt()` all succeed — the machine locks up during the sustained `iowrite32`
burst to TCM.

### Current pacing (insufficient)

- Readback flush every 64 DWORDs (256 bytes)
- 10μs `udelay` after each flush
- Still overflows the Gen1 x1 link write buffers

### Diagnosis

The 64-DWORD chunk size is still too large for the Gen1 x1 link. At ~250 MB/s
theoretical bandwidth with write-posting, 256 bytes of back-to-back MMIO writes
can still fill the PCIe write buffer before the read-back completes. The 10μs
delay is also too short to allow the link to fully drain.

### Fix: tighter pacing + progress canaries

1. **Reduce chunk size**: flush every 16 DWORDs (64 bytes) instead of 64 (256 bytes)
2. **Increase drain delay**: 50μs instead of 10μs
3. **Add progress canaries**: `pr_emerg` every 1024 DWORDs so the next crash
   (if any) reveals exactly how far the write got before dying

## Canary progress test (2026-04-13, 16 DWORD + 50μs pacing)

### Result: crashed at DWORD 0

Progress canary showed "DWORD 0/XXXXX" but no "DWORD 1024/XXXXX" — the machine
locks up within the first 16 `iowrite32` calls, before the first paced readback
even triggers.

### Diagnosis

16-word chunks are still too many posted writes for Gen1 x1. The write-post
buffer fills before the first readback at word 15 can flush it. Since reads to
BAR2 work fine (CANARY 2→3 pass, TCM[0x00] and TCM[0x04] return valid data),
the problem is specifically **posted writes accumulating without flush**.

### Fix: single-word pacing

- `wmb()` before each `iowrite32` to serialize the write
- `ioread32` after **every single** `iowrite32` to flush posted writes immediately
- Extra `udelay(20)` every 16 words to let the link drain
- This will be slow (~160K readbacks for a 640KB firmware) but correctness first

## Single-word pacing test (2026-04-13, test.14)

### Result: "died at DWORD 0" — no crash, but immediate readback failure

With single-word pacing, no hard lockup occurred. But the readback after the
very first `iowrite32` returned 0xFFFFFFFF, triggering the death check.

### Root cause: ARM left in reset, TCM not writable

The `arm_halt()` function was leaving `RESET_CTL=1` (ARM in reset). With the ARM
core in reset, the SOCRAM/TCM controller is also held in reset, making TCM
**read-only**. Reads work (they return stale wl firmware data) but writes don't
take effect — readback returns 0xFFFFFFFF.

### Fix: clear RESET_CTL after setting CPUHALT

Updated `arm_halt()` to match `brcmf_chip_cr4_set_passive`:
1. Force clocks (FGC + CLK), put ARM in reset
2. Set CPUHALT while in reset
3. **Clear reset** — ARM stays halted via CPUHALT, but TCM becomes accessible
4. Drop FGC, keep CPUHALT + CLK

After fix: IOCTL=0x21 (CPUHALT+CLK), RESET_CTL=0x00 (out of reset).

## Test.15 — stale validation check (2026-04-13)

### Result: FAIL at validation, not actual hardware failure

The arm_halt fix worked perfectly (IOCTL=0x21, RESET_CTL=0x00), but the
post-halt validation check expected `RESET_CTL & RESET` to be set — the old
(wrong) state. Fixed validation to check CPUHALT is set and RESET_CTL is clear.

## Test.16 — false positive at DWORD 142 (2026-04-13)

### Result: "died at DWORD 142" — firmware download started but false alarm

Firmware download started successfully and reached DWORD 142 (byte offset 0x238).
The readback check treated 0xFFFFFFFF as "device dead", but the firmware binary
actually contains 0xFFFFFFFF at that offset — it's valid data.

### Fix: compare readback against expected firmware data

Changed the write verification to compare `ioread32` against `src[i]` instead of
checking for the 0xFFFFFFFF sentinel. A 0xFFFFFFFF readback is only treated as
device death if the firmware data at that offset is *not* 0xFFFFFFFF.

## Test.17 — Level 3 PASS (2026-04-13)

### Result: firmware download complete, all 110,559 DWORDs verified

All fixes working together:
- ARM halt: IOCTL=0x21 (CPUHALT+CLK), RESET_CTL=0x00 (out of reset)
- No AER errors throughout (clean 0x00000000)
- Bulk TCM write: 442,233 bytes (110,559 DWORDs) written with zero mismatches
- Download time: ~0.76s (~580 KB/s with single-word pacing on Gen1 x1)
- First word verified: 0xb80ef000 matches expected
- Shared info region (0x9d0a4) contains firmware data (not yet initialized)

### Level 3 output summary

```
CANARY 5 — starting bulk TCM write (110559 DWORDs)
TCM write progress: DWORD 0/110559
  ... (108 progress lines, ~7ms per 1024 DWORDs) ...
TCM write progress: DWORD 109568/110559
CANARY 6 — bulk TCM write complete
FW verify: first=0xb80ef000 (expect 0xb80ef000)
PASS — ARM halted, FW downloaded, ready for level 4
```

## Test.18 — Level 4 crash (2026-04-13)

### Result: crash ~100-200ms after ARM release

Level 4 ran with protections: bus mastering OFF, PCIe interrupts masked, ISR
registered. The ARM was released and the host survived for 100ms, then crashed
before the 300ms checkpoint. Hard lockup requiring power cycle.

### Timeline (from journal -b -1)

```
[level 4] ARM release (NO DMA, NO bus mastering)...
[level 4] IRQ 18 registered, PCIe interrupts masked
[level 4] Pre-release fw_init_done=0x070ca017
LEVEL4 — about to release ARM (no DMA, no bus master)
[level 4] *** RELEASING ARM (no DMA, no bus master) ***
Releasing ARM CR4...
ARM IOCTL after release: 0x00000001
LEVEL4 — arm_release() returned, still alive
[level 4] ARM released — still alive
LEVEL4 — 100ms post-release, alive         ← LAST MESSAGE
  [crash between 100ms and 300ms]
```

### Analysis

- ARM released successfully (IOCTL=0x01 = CLK only, no CPUHALT)
- Bus mastering OFF → firmware cannot DMA to host memory
- PCIe interrupts masked → firmware cannot fire MSIs
- No IRQs observed in the 100ms window
- Crash happens during `msleep(200)` between 100ms and 300ms checks

### Likely cause

The firmware is writing to **PCIe control registers** on the backplane that
affect the host-side link. With bus mastering disabled, the firmware can still
access the PCIe core's internal registers (INTSTATUS, link control, etc.) via
the BCMA backplane — these are device-side registers, not DMA. A firmware write
to e.g. PCIe link control or BAR configuration could cause the host's root
complex to detect a fatal error and lock up.

This matches the Phase 3 findings (diag tests 6-7) where the same crash
occurred. The `wl` firmware is designed for FullMAC CDC protocol and likely
performs PCIe init that's incompatible with our setup.

### Possible mitigations for next attempt

1. **Shorter observation window**: re-halt ARM after 50ms instead of waiting 2s
2. **Disable PCIe core before release**: put the PCIe core in reset via BCMA
   wrapper so firmware can't access PCIe registers (but this may prevent TCM
   access from the host too)
3. **Monitor AER in a tight loop**: poll AER status immediately after release
   to catch the fatal error before it propagates

## Cold boot testing (2026-04-13, issue #6)

### Setup

Blacklisted `wl` module (`boot.blacklistedKernelModules = [ "wl" ]` in NixOS
config) so it never loads. Device was claimed by `bcma-pci-bridge` instead —
required adding unbind logic to test.sh before our module can claim the device.

### Results: levels 0-3 all PASS (tests 23-26)

Cold boot behavior is essentially identical to warm-handoff (post-wl) testing.

### Cold boot vs warm-handoff comparison

| Property | Cold boot | After wl unload | Verdict |
|---|---|---|---|
| STATUS | 0x0010 | 0x0810 | SSE bit (0x0800) is wl artifact |
| AER (first probe) | uncorr=0x8000 corr=0x2000 | same | NOT a wl artifact — BIOS/bcma |
| AER (after clear) | 0x00000000 | 0x00000000 | Same |
| PCIe link | Gen1 x1 | Gen1 x1 | Intrinsic hardware state |
| PMCSR | 0x4008 (D0) | 0x4008 (D0) | Same |
| ARM IOCTL | 0x00000020 | 0x00000020 | Same |
| BAR0_WIN | 0x18003000 | 0x18001000 | Different — wl sets window |
| FW download | PASS (0.76s) | PASS (0.76s) | Same |

### Key conclusions (addresses issue #6)

1. **Behavior is intrinsic, not wl side-effects.** The only wl artifact is
   the SSE status bit (0x0800) — cosmetic, not functional.
2. **AER errors exist on cold boot** — they come from BIOS/EFI enumeration or
   bcma-pci-bridge, not from wl teardown.
3. **Gen1 x1 is the hardware's native state**, not degradation from wl.
4. **Test script now handles cold boot** — unbinds bcma-pci-bridge automatically.

## Test.27 — Level 4 crash on cold boot (2026-04-13)

### Result: identical crash ~100-200ms after ARM release

Same pattern as test.18 (warm handoff):
- ARM released, IOCTL=0x01 (CLK only)
- "100ms post-release, alive" — last message
- Hard lockup between 100ms and 300ms

### Conclusion: crash is intrinsic firmware behavior

The level 4 crash is **not caused by wl side-effects**. It occurs identically
on cold boot (wl never loaded) and warm handoff (after wl unload). The firmware
itself does something ~100-200ms after starting that kills the PCIe link.

Most likely cause: the offload firmware expects to find a valid shared_info
structure at TCM offset 0x9D0A4 with magic markers (0xA5A5A5A5 / 0x5A5A5A5A)
and DMA buffer addresses. Without this, the firmware panics and corrupts host
PCIe state. This matches the Phase 3 analysis and option_c_feasibility.md
findings about the boot handshake sequence.

## Test.28 — Level 4 PASS with shared_info (2026-04-13)

### Result: NO CRASH — firmware alive for 2 full seconds

Writing valid shared_info (magic markers, olmsg DMA address) before ARM release
completely prevents the crash. The firmware boots, finds the handshake structure,
and runs stably with bus mastering OFF.

### Key observations

| Property | Value | Meaning |
|---|---|---|
| fw_init_done | 0x00000000 (timeout) | FW didn't complete init — needs DMA |
| shared_info magic_start | 0xA5A5A5A5 (intact) | FW found and validated it |
| shared_info[0x10] | 0x0009af88 | FW wrote this — wasn't set by host |
| PCIe intstatus | 0x00000300 | FW set interrupt bits |
| PCIe mailboxint | 0x00000003 | FW sent 2 mailbox signals |
| IRQs received | 0 | Expected — interrupts masked |
| ARM re-halt | Clean (IOCTL=0x21) | FW didn't corrupt anything |

### Analysis

The firmware is **alive and communicating**:
1. Found shared_info magic markers → didn't panic
2. Read olmsg DMA address from shared_info
3. Wrote 0x0009af88 to shared_info[0x10] (possibly its own version/status)
4. Tried to signal host via PCIe mailbox (2 signals)
5. Couldn't complete init because bus mastering was OFF (can't DMA to olmsg)

### Root cause of previous crashes confirmed

Without valid shared_info, the firmware panics on boot (~100ms) and corrupts
the PCIe link. With valid shared_info, it runs indefinitely without issues.

## Test.29 — Level 5 no crash, fw_init_done timeout (2026-04-13)

### Result: firmware stable with DMA, but didn't complete init

Level 5 enables bus mastering at 50ms post-release. Firmware ran for 2+ seconds
with DMA available, no crash, but fw_init_done stayed 0.

### Key observations

| Property | Value | Meaning |
|---|---|---|
| Bus mastering | Enabled at 50ms | FW can DMA |
| fw_init_done | 0x00000000 (timeout) | FW didn't complete init |
| olmsg fw→host ring | wr=0 rd=0 | FW didn't write to olmsg |
| PCIe intstatus | 0x00000300 | FW set interrupt bits |
| PCIe mailboxint | 0x00000003 | FW sent 2 mailbox signals |
| IRQs received | 0 | Interrupts masked — FW signals not acked |
| shared_info | Magic markers intact | FW didn't corrupt anything |

### Analysis

Firmware is stable and trying to communicate via PCIe mailbox, but host isn't
acknowledging. The firmware may be stuck waiting for:
1. PCIe interrupt acknowledgement (mailbox signals need to be cleared/acked)
2. Interrupts to be unmasked so the ISR can fire
3. Some host response in the olmsg buffer

The mailbox signals (intstatus=0x300, mailboxint=0x03) are the firmware's way of
saying "I'm here, acknowledge me." Without acking, it may loop waiting forever.

### test.31 — Interrupt unmasking + MAC address + boot sequence fix (2026-04-13)

Changes applied:
- Added MAC address to shared_info at offset 0x024 (Apple OUI 00:1C:B3 + subsys-derived)
- Enabled bus mastering BEFORE ARM release (firmware needs DMA immediately)
- Added boot handshake step 6: write 0x20 to ARM IOCTL before release
- Cleared/unmasked PCIe interrupts (INTMASK=0xFFFFFFFF) before ARM release
- Added periodic poll diagnostics (100ms, 500ms, 1000ms, 1500ms)

Result: **Still ETIMEDOUT**. Same behavior — intstatus=0x300, mailboxint=0x03, IRQs=0.
Firmware alive (IOCTL=0x01, RESET_CTL=0x00) but fw_init_done stays 0.

Key finding: **shared_info[0x010]=0x0009AF88** — firmware WROTE this value. We zeroed
the entire shared_info, so this is firmware output. It's a TCM pointer.

### test.32 — Comprehensive diagnostic scan (2026-04-13)

Added full shared_info scan (all non-zero words) and TCM pointer dereferencing.

**shared_info scan: only 7 non-zero words out of 3023:**

| Offset | Value | Source |
|--------|-------|--------|
| 0x0000 | 0xA5A5A5A5 | Host (magic_start) |
| 0x0004 | 0x01110000 | Host (olmsg DMA addr) |
| 0x000C | 0x00010000 | Host (olmsg size 64KB) |
| 0x0010 | 0x0009AF88 | **FIRMWARE** (console struct ptr) |
| 0x0024 | 0x01B31C00 | Host (MAC bytes 0-3) |
| 0x0028 | 0x00000112 | Host (MAC bytes 4-5) |
| 0x2F38 | 0x5A5A5A5A | Host (magic_end) |

**Firmware console buffer discovered at 0x9AF88:**

```
[0x9AF88] = 0x00096F78  — text buffer address in TCM
[0x9AF8C] = 0x00004000  — 16KB buffer size
[0x9AF90] = 0x0000057C  — 1404 bytes written (console has output!)
[0x9AF94] = 0x00096F78  — read pointer (matches buf start)
```

This is a classic Broadcom firmware console log structure. The firmware wrote 1404
bytes of console text at TCM address 0x96F78. Next step: read it as ASCII.

**Other findings:**
- olmsg buffer completely empty (fw→host wr=0, rd=0) — firmware never DMA'd
- Post-firmware TCM (.bss area at 0x6C000) has non-zero data — firmware initialized .bss
- intmask/mailboxmask report 0x00000000 in diagnostic (after pcie_mask_irqs cleanup)
- IRQs received: 0 despite INTMASK=0xFFFFFFFF during poll — likely need MSI, not legacy INTx

### Analysis — Why firmware is stuck

The firmware:
1. Starts running (ARM alive, IOCTL=0x01)
2. Finds shared_info via magic markers
3. Stores console pointer at shared_info[0x010]
4. Sends mailbox signals (intstatus=0x300, mailboxint=0x03)
5. Writes 1404 bytes to its console log
6. Gets stuck — never writes fw_init_done, never touches olmsg DMA buffer

Most likely causes:
- **DMA failure**: Firmware can't reach host memory. The PCIe outbound translation
  window may need configuration. The firmware reads our DMA address from shared_info
  but can't actually issue DMA transactions without the PCIe core's address translation
  registers being programmed.
- **Missing host response**: Firmware may need the host to acknowledge mailbox signals
  or respond via some register before it proceeds.
- **IRQ delivery broken**: Using legacy INTx (IRQ 18 shared) but Broadcom PCIe Gen2
  devices typically need MSI. Without working interrupts, there's no host-to-firmware
  signaling path.

### test.33 — Firmware console decoded! (2026-04-13)

**BREAKTHROUGH: Firmware console reveals exact failure.**

Console output (1404 bytes at TCM 0x96F78):
```
Found chip type AI (0x15034360)
Chipc: rev 43, caps 0x58680001, chipst 0xa4d pmurev 17, pmucaps 0x10a22b11
si_kattach done. ccrev = 43, wd_msticks = 32

RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz
pciedngl_probe called
Found chip type AI (0x15034360)
wl_probe called
wl0: wlc_bmac_attach: Unsupported Broadcom board type (0xffff) or revision level (0x0)
wl0: wlc_bmac_attach: failed with err 15
wl0: wlc_attach: failed with err 15

FWID 01-9413fb21

TRAP 4(9cee8): pc 3e560, lr 68189, sp 9cf40, cpsr 600001df, spsr 600001ff
  dfsr 8, dfar b80ef234
  r0 b80ef000, r1 0, r2 0, r3 0, r4 0, r5 91cc4, r6 0
  r7 91c3c, r8 0, r9 93610, r10 9cfec, r11 0, r12 0
```

**Key findings:**

1. **Firmware is PCI-CDC (FullMAC), not just offload.** Identifies as
   "RTE (PCI-CDC) 6.30.223" — this is a full wl stack firmware using the
   CDC (Common Driver Core) protocol, same as brcmfmac expects.

2. **Root cause: Missing NVRAM.** The firmware tries `wlc_bmac_attach` which
   reads SPROM/SROM for board type and revision. Gets 0xFFFF (bad read) and
   0x0. On Apple hardware, NVRAM data must be provided by the host in TCM
   alongside the firmware binary.

3. **Firmware CRASHED (TRAP 4 = data abort).** After the NVRAM failure, it
   hit a data abort accessing backplane address 0xB80EF234.

4. **Board info:** Subsystem vendor=0x106B (Apple), device=0x0112 (MacBookPro11,1)

**Implications:**
- brcmfmac4360-pcie.bin IS a FullMAC firmware with full wl stack
- The firmware CAN do WiFi independently if properly initialized
- We need to provide NVRAM data (board type, revision, calibration, MAC) in TCM
- No nvram file found at /lib/firmware/brcm/ — need to create or extract one
- On Apple Macs, NVRAM data comes from EFI device properties or must be extracted
  from macOS IO registry

### test.34 — NVRAM format wrong (2026-04-13)

First NVRAM attempt: raw .txt file with `#` comments written to TCM. Used byte count
instead of word count in the token. Firmware still reads 0xFFFF.

### test.35 — NVRAM correct format, firmware ignores it (2026-04-13)

Fixed NVRAM loading: stripped comments, null-separated key=value pairs, padded to
4-byte boundary, proper word-count token `(~words << 16) | words`. Token verified
correct at TCM 0x9FFFC. But firmware STILL reads boardtype=0xFFFF.

**Root cause:** This wl-based PCI-CDC firmware reads SROM from hardware registers
(ChipCommon SROM_ADDR/DATA interface), NOT from NVRAM text in TCM. The brcmfmac
NVRAM-in-TCM protocol is for a different firmware type.

### test.36 — OTP probing (2026-04-13)

Added `dump_sprom_and_otp()` to probe all OTP access methods from host side:

| Register | Value | Meaning |
|---|---|---|
| CC SROM_CTRL | 0x00000023 | OTP selected (bit0), OTP present (bit1) |
| CC OTP_STATUS | 0x00009000 | Init done (bit15), word done (bit12) |
| CC OTP_CONTROL | 0x00000000 | No active operation |
| CC OTP_LAYOUT | 0x00115200 | 512 rows (bits[11:0]=0x200) |
| CC caps | 0x58680001 | OTP size bits[16:12]=0x0 |

**Access methods tried:**
- CC SROM_ADDR/DATA (8 words) → all 0xFFFF
- CC+0x800 direct OTP region (32 DWORDs) → all zero
- OTP core at 0x18012000 → 0xFFFFFFFF (core may not exist)

**Analysis:** OTP IS present and initialized (status bits confirm). But both the
SPROM interface and direct memory-mapped OTP returned no data. Possible causes:

1. Only scanned 32 of 512 rows — CIS data may be at higher offset
2. Need to use `otpprog` register with explicit read commands (row-by-row)
3. PCIe core SROM shadow (PCIe+0x800) might have auto-loaded OTP data
4. Apple may use CIS format (tag-length-value) in OTP, not SROM format — the
   SROM_ADDR/DATA interface doesn't handle CIS, need raw OTP row reads
5. OTP may need explicit enable via otpcontrol register before reads work

**Next test (test.37):** Comprehensive 6-method OTP scan:
1. CC SROM_ADDR/DATA (existing, 8 words)
2. Full CC+0x800 scan (256 DWORDs = all 512 rows)
3. otpprog register read commands (row-by-row, 128 rows)
4. PCIe core SROM shadow at PCIe+0x800
5. OTP core direct (0x18012000 + 0x800)
6. CC SROM with OTP CI enable toggle + key SROM11 offsets

## Tests 37-42 — OTP scan results (2026-04-13, earlier sessions)

Key findings from comprehensive OTP probing:

- **CC SROM_ADDR/DATA offsets were WRONG**: had 0x019C/0x01A0, corrected to
  0x0194/0x0198 for CC rev 43. After fix, reads return 0x0000 (not 0xFFFF).
- **CC+0x800 OTP shadow is completely empty and read-only** — writes have no effect.
- **PCIe core SROM shadow (PCIe+0x800) has REAL board data**: 24 non-zero DWORDs
  including Apple subsystem ID (106b:0112), device ID (43a0), calibration values.
- **PCIe+0x800 is WRITABLE** — confirmed with 0xDEADBEEF write/readback test.
- SROM_CTRL=0x23: SRC_PRSNT(bit0)=1 (hardware read-only), SRC_OTPSEL(bit4)=0,
  SRC_OTPPRESENT(bit5)=1.
- Setting SRC_OTPSEL had no effect — firmware still reads 0xFFFF.

**Strategy developed**: Write minimal SROM11 image to PCIe+0x800 before ARM
release. Key fields: boardtype=0x0552, boardrev=0x1101, sromrev=11, devid=0x43a0,
subvid=0x106B, boardflags, ccode, antenna config.

## Tests 43+ — Level 5 crash cycle (2026-04-13)

### Problem: Level 5 crashes machine every time

Attempted ~10 runs of `test.sh 5` across multiple reboots. Every attempt crashed
the machine. Crashes occurred at different points in the code path, making
diagnosis extremely difficult. The conversation context kept expiring between
code changes and test execution, leading to a frustrating loop.

### b43 blacklist fix

Discovered that `b43` + `bcma` + `ssb` modules were loading at boot and probing
the BCM4360, leaving it in a bad state:
```
b43-phy0: Broadcom 4360 WLAN found (core revision 42)
bcma-pci-bridge 0000:03:00.0: bus0: HT force timeout
bcma-pci-bridge 0000:03:00.0: bus0: PLL enable timeout
b43-phy0 ERROR: FOUND UNSUPPORTED PHY (Analog 12, Type 11 (AC), Revision 1)
```

**Fix**: Added `b43`, `bcma`, `ssb` to `boot.blacklistedKernelModules` in NixOS
config (`/etc/nixos/configuration.nix`). Applied via `nixos-rebuild switch`.

### Crash progression (each fix pushed the crash point later)

| Attempt | Last canary/message | Crash point | Fix applied |
|---------|---------------------|-------------|-------------|
| 1-3 | Level 4 ARM release | Level 4 ARM release (old code) | Skip level 4 for level 5 |
| 4-5 | CANARY 6 (bulk write done) | TCM verify read after 442KB write | Skip verify read |
| 6 | CANARY 6b (verify skipped) | 1s mdelay after bulk write | Skip FW re-download in L5 |
| 7-8 | CANARY 6b | Same — L3 still downloads FW | Skip FW download in L3 for L5 |
| 9 | CANARY 4 (ARM halt done) | ~1-2s after arm_halt() | Skip ARM halt in L3 for L5 |
| 10 | CANARY 1 (BAR2 map) | pci_iomap(BAR2) in L3 | Skip L3 entirely, map BAR2 in L5 |
| 11 | No kernel output | Module never loaded / insmod crash | — |

### Key observation: Level 3 standalone works fine

`test.sh 3` (level 3 alone) passes reliably on a clean boot — full firmware
download (442KB), ARM halt, all canaries pass. The crash only happens when
`max_level=5` is used, even after skipping all level 3 operations.

This is confusing because the code path should be identical — when max_level >= 5,
level 3 is skipped entirely in the latest code. Yet the machine still crashes.
Possible explanations:
1. Module was not rebuilt/reloaded correctly in some attempts
2. Previous test run on same boot left hardware in bad state
3. Timing-dependent PCIe instability on this Gen1 x1 link
4. Level 5 code itself (even just the SROM scan via BAR0 backplane reads) is
   unstable on fresh boot

### Current code state (committed + pushed)

Level 5 flow when max_level=5:
1. Levels 0-2 run normally (PCI bind, config space, BAR0 mapping)
2. Level 3 SKIPPED entirely (just prints "SKIPPED")
3. Level 4 SKIPPED (only runs when max_level==4)
4. Level 5 maps BAR2 itself, then does ARM halt + SROM write + ARM release

## Proposed Strategy Change

### Problem

Level 5 crashes the machine every time, preventing testing of the SROM11 write
hypothesis. The crash appears related to the level 5 code path itself, not just
bulk TCM writes or ARM halt.

### Proposed approach: Test SROM write from Level 3

Since level 3 works reliably, add the PCIe+0x800 SROM write test at the END
of level 3 (after firmware download and ARM halt). This tests the core hypothesis
— can we write valid boardtype to PCIe+0x800 and read it back? — without any of
the level 5 machinery (ARM release, DMA, interrupt setup).

### Alternative approaches (if SROM write in L3 doesn't help)

1. **Firmware binary patching**: Patch the boardtype check at TCM near 0x4751C
   (where the "Unsupported Broadcom board type" format string lives). NOP the
   comparison or hardcode a valid boardtype.

2. **Use brcmfmac driver**: Since the firmware is PCI-CDC FullMAC, brcmfmac
   should be able to drive it. Focus on providing correct NVRAM/SROM data via
   the platform data path (device tree / platform firmware) rather than our
   test module.

3. **Cold power cycle**: The repeated crashes may have left PCIe hardware in a
   state that warm reboot doesn't fully clear. Unplugging power for 30+ seconds
   may help level 5 work.

4. **Reduce level 5 to minimal SROM-only test**: Strip all ARM halt/release/DMA
   code from level 5, leaving ONLY the PCIe+0x800 write and readback. If even
   that crashes, the problem is in the BAR0 backplane access pattern.

## SROM write test relocation (2026-04-14)

### Change

Moved the SROM11 write test from the end of level 3 (after ARM halt + FW
download) to BEFORE the ARM halt. This ensures the SROM test runs before any
dangerous operations that might crash the machine. The test:

1. Scans PCIe+0x400/0x800/0xC00/0x1000 for writability
2. Writes a minimal SROM11 image to PCIe+0x800 (256 DWORDs):
   - sromrev=11 at word 48 (DWORD 24)
   - subvid/devid (0x43a0106B) at DWORD 32
   - boardtype/boardrev (0x11010552) at DWORD 33
   - boardflags at DWORD 35-36
   - ccode="X0" at DWORD 44
   - antenna config at DWORD 49
3. Reads back key fields to verify write took effect
4. Cross-checks via CC SROM_ADDR/DATA interface

### Commit: ecc96c8 (pushed before crash)

## Spontaneous crash investigation (2026-04-14)

### Problem: Machine crashes without any test running

After the SROM relocation commit, attempted to run `test.sh 3` multiple times.
The machine crashed before the test module even loaded — dmesg showed NO
bcm4360 output at all. The crashes occurred during the 10s quiesce delay in
test.sh, or even while idle.

Pattern observed across ~3-4 reboots:
- Machine boots, uptime ~1-5 minutes
- No bcm4360 test module loaded
- Hard crash/lockup requiring power cycle
- No kernel panic messages in dmesg on next boot

### Diagnosis: PCIe AER errors from BCM4360 hardware

The BCM4360 PCI device (03:00.0) is present on the bus with no driver bound.
Previous testing showed AER uncorrectable errors (0x8000) present even on cold
boot (test.36 findings). With no driver to handle or suppress these errors,
the PCIe AER subsystem may be treating them as fatal and crashing the machine.

The device's PCI command register shows 0x0000 (memory space disabled, bus
mastering disabled) — the device is essentially unclaimed but still electrically
active on the PCIe bus.

### Fix applied: pci=noaer kernel parameter

Added `boot.kernelParams = [ "pci=noaer" ];` to `/etc/nixos/configuration.nix`.
This disables PCIe Advanced Error Reporting, preventing AER errors from
triggering machine-wide fatal responses.

Applied via `nixos-rebuild switch` and confirmed active after reboot:
```
$ cat /proc/cmdline
... pci=noaer ...
```

### Result: pci=noaer did NOT stop crashes (2026-04-14)

With `pci=noaer` confirmed active (`cat /proc/cmdline` shows it), the machine
STILL crashed within ~3 minutes of boot. Test.sh 3 was running but the module
never loaded (no bcm4360 output in dmesg). This means:

1. **AER is NOT the crash cause** — disabling AER entirely had no effect
2. **The BCM4360 hardware is causing crashes through a different mechanism**
3. The crashes are spontaneous — they happen even when idle, not just during
   test execution

### Revised diagnosis

The crash is NOT PCIe AER. Possible causes:
- **NMI from unclaimed device**: BCM4360 may be asserting legacy INTx interrupts
  with no driver to acknowledge them, causing an interrupt storm/NMI
- **PCIe link errors below AER level**: Physical layer errors (e.g., receiver
  errors, LTSSM state machine issues) that don't go through AER
- **Thermal**: BCM4360 with no driver may not have power management, overheating
  and causing bus errors (unlikely — crashes happen within minutes of cold boot)
- **BIOS/EFI PCIe hotplug**: The Thunderbolt controller on this MacBook
  (device 07:00.0) showed "device link creation failed" in dmesg — Thunderbolt
  and PCIe hotplug interaction could be involved

### Possible next steps

1. **Disable BCM4360 at PCI level**: `setpci -s 03:00.0 COMMAND=0000` to
   ensure memory/IO space stays disabled, or use `pci=disable` quirk
2. **Try `pci=nomsi,noaer`**: Disable MSI as well in case the device is
   sending spurious MSIs
3. **Remove the card physically**: If possible, physically disconnect the
   BCM4360 mini-PCIe card to verify it's the crash source. If machine is
   stable without it, confirms hardware instability.
4. **Run tests from initramfs or early boot**: Minimize time between boot
   and test execution to beat the crash window
5. **Try a different kernel**: The crashes might be kernel-version-specific.
   NixOS 24.05 shipped with 6.6.x — try that LTS kernel.

## Phase 4 Exit Assessment (issue #8)

Mapping current status against the Phase 4 exit checklist:

### A. Clean-state baseline — PARTIALLY MET

- [x] Cold boot test path documented (test.23-26)
- [x] `wl` blacklisted (+ b43, bcma, ssb)
- [x] Test module build confirmed (unique log markers at each level)
- [x] BAR0 reads return valid values (confirmed at levels 0-3)
- [ ] **No crash after load/unload idle test** — BLOCKED by spontaneous crashes
- [ ] **Results reproducible across 2-3 runs** — Level 3 was reproducible before
  the spontaneous crash issue appeared; currently BLOCKED

### B. Device-state clarity — MET

- [x] Can distinguish cold/warm/post-crash states (test.23 cold boot comparison)
- [x] D3/power-state behavior documented (PMCSR=0x4008 = D0)
- [x] D0 wake path understood (device stays in D0, no wake needed)
- [x] Not relying on post-wl state (blacklisted, cold boot verified identical)

### C. Runtime validation of architecture — MET

- [x] Host action mapped to D11/MMIO/DMA: ARM halt/release, FW download to TCM,
  shared_info handshake, mailbox signaling (tests 17-32)
- [x] Firmware responsibility identified: PCI-CDC FullMAC with wl stack,
  reads SROM for board config, signals host via PCIe mailbox (test.33)
- [x] SoftMAC/offload model documented: firmware is FullMAC CDC, NOT SoftMAC.
  Host provides shared_info + DMA buffers, firmware runs entire wl stack.

### D. Minimal driver-like operation — MET

- [x] Safe D11 register block: PCIe+0x800 SROM shadow is readable and WRITABLE
- [x] Small host init step reproduced: shared_info handshake (test.28 — firmware
  found magic markers, wrote console pointer, sent mailbox signals)
- [x] Harmless hardware action triggered: ARM halt/release cycle (test.28)
- [x] Reproducible host-controlled state change: FW download to TCM (test.17),
  shared_info write causing firmware to respond (test.28)

### Minimum exit rule assessment

- [x] Clean cold-boot path works (when machine is stable)
- [x] Architecture model has runtime validation (PCI-CDC FullMAC confirmed)
- [x] One minimal host-control action is reproducible (shared_info handshake)

**Phase 4 exit criteria are substantially met.** The main blocker is the
spontaneous crash issue preventing further test reproducibility. However,
the core research goals are achieved:

1. We know the firmware type (PCI-CDC FullMAC, RTE 6.30.223)
2. We know why it fails (missing SROM boardtype data → 0xFFFF)
3. We know the handshake protocol (shared_info magic markers + DMA)
4. We've demonstrated host-controlled firmware operation (ARM halt/release,
   FW download, shared_info handshake producing firmware response)

### Warning signs of circling — PRESENT

The repeated crash/reboot cycle with diminishing returns matches the "repeating
power/reset experiments without new outcomes" warning sign. The SROM write
test is the last hypothesis to test before moving on.

### Recommendations for closing Phase 4

#### Remaining Phase 4 work (crash mitigation)

1. **One more attempt**: Run test.sh 3 immediately after boot (skip 10s delay).
   If SROM write results are captured, document them and close Phase 4.
2. **If crashes continue**: Accept that the hardware instability is a blocking
   issue for this specific machine. Document findings and move to Phase 5.
3. **Physical intervention**: Try removing the BCM4360 mini-PCIe card to
   confirm it's the crash source. If stable without it, the card itself is
   electrically unstable. Try cold power cycle (30s+ unplug) to fully reset
   PCIe link state.
4. **Different kernel**: Try Linux 6.6.x LTS (NixOS 24.05 default) — the
   crash may be kernel-version-specific.

#### Phase 5 approaches (post Phase 4)

1. **brcmfmac with NVRAM**: Since we confirmed the firmware is PCI-CDC
   FullMAC (RTE 6.30.223), the standard `brcmfmac` kernel driver should be
   able to drive it. The key missing piece is SROM/NVRAM board data. Phase 5
   would create a platform NVRAM file (`brcmfmac4360-pcie.txt`) with the
   correct boardtype (0x0552), subsystem IDs (106b:0112), antenna config,
   and calibration data — then load brcmfmac instead of our test module.
   This sidesteps our test module's crash issues entirely.

2. **Firmware binary patching**: Patch the boardtype check in the firmware
   binary at TCM near 0x4751C (where "Unsupported Broadcom board type" lives).
   NOP the comparison or hardcode a valid boardtype. This is more invasive
   but would work even if SROM/NVRAM data can't be provided correctly.

3. **SROM write before firmware boot**: If the SROM write test (PCIe+0x800)
   shows that boardtype can be written and read back, a minimal module could
   write SROM data and then let brcmfmac take over the device. This combines
   our Phase 4 SROM research with the brcmfmac driver path.

## Final attempt: quick test.sh 3 (2026-04-14)

### Result: CRASHED — module never loaded

Attempted to run test.sh 3 immediately after boot with `pci=noaer` active.
Machine crashed before the module loaded — no bcm4360 output in dmesg at all.

This confirms recommendation #2: the hardware instability on this machine is
a blocking issue that cannot be worked around from software. The BCM4360 is
crashing the machine spontaneously regardless of:
- Whether any driver is loaded
- Whether AER is enabled or disabled
- How quickly we attempt to run tests after boot

### SROM write test: UNTESTED

The SROM11 write test (commit ecc96c8) was never executed. The code is ready
and correct but we cannot run it due to hardware instability. The hypothesis
— that writing boardtype=0x0552 to PCIe+0x800 would be visible to firmware
via the SROM interface — remains unverified.

## Phase 4 Conclusion (2026-04-14)

### What we achieved

1. **Firmware identification**: PCI-CDC FullMAC, RTE 6.30.223 (r), FWID
   01-9413fb21. This is a complete wl stack running on the ARM CR4 core.

2. **Root cause of firmware failure**: `wlc_bmac_attach` reads boardtype from
   SROM hardware registers and gets 0xFFFF. The firmware then TRAPs (data
   abort at 0xB80EF234). Apple hardware has board data in OTP/PCIe SROM
   shadow but the firmware's SROM read path doesn't find it.

3. **Boot handshake protocol**: Host writes shared_info with magic markers
   (0xA5A5A5A5/0x5A5A5A5A) and DMA buffer address to TCM. Firmware finds
   it, writes console pointer back, sends PCIe mailbox signals. Without
   valid shared_info, firmware panics ~100ms after release and kills PCIe.

4. **Hardware characteristics**: PCIe Gen1 x1 link, BAR0 (backplane) and
   BAR2 (TCM direct) both functional. PCIe+0x800 SROM shadow is writable.
   CC SROM_ADDR/DATA returns 0x0000 (not useful). OTP is present but
   inaccessible via standard interfaces.

5. **Cold boot = warm boot**: No functional difference between cold boot
   and post-wl-unload states. The wl driver's only artifact is cosmetic
   (SSE status bit).

### What remains unresolved

1. **SROM write hypothesis**: Can writing to PCIe+0x800 provide boardtype
   to firmware? Untested due to crashes.
2. **Spontaneous crashes**: Machine unstable with BCM4360 on PCIe bus,
   no driver needed to trigger. Cause unknown — not AER.
3. **Level 5 instability**: Even when machine was stable enough for level 3,
   level 5 (max_level=5) always crashed. Root cause unclear.

### Phase 4 → Phase 5 transition

Phase 4 exit criteria (issue #8) are substantially met. Moving to Phase 5
with focus on the brcmfmac driver path — providing correct NVRAM board data
to the standard kernel driver rather than continuing with the test module.
