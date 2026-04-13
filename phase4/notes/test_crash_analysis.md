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

## Next Steps

1. Unmask PCIe interrupts after ARM release so ISR can fire
2. Service the mailbox signals (clear intstatus/mailboxint)
3. Check if fw_init_done changes after interrupt servicing
4. Investigate what the 0x300 / 0x03 interrupt bits mean in Broadcom PCIe core
