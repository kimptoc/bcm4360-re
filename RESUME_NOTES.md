# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.51)

Git branch: main (pushed to origin)

## test.50 RESULT: INSTANT CRASH — watchdog write = immediate reset

**test.50 CONFIRMED: Writing 0 to ChipCommon watchdog triggers INSTANT hardware reset**
- Machine crashed before ANY test.50 kernel message was logged
- Log file (test.48.stage0 — script bug, wrote to wrong log) cut off right after insmod
- Boot -1: started 09:15:24, test run at 09:21:30, next boot at 09:22:10 (40s gap = crash)
- WDOG write root cause: BCM4360 watchdog register at CC+0x80 is a pure countdown timer
  - Writing 4 = reset in 4 ALP ticks (~4µs) — this is test.40's intentional reset mechanism
  - Writing 0 = reset in 0 ALP ticks = IMMEDIATE (not "disable")
  - Writing 0 does NOT disable the watchdog on BCM4360 (corerev 49)
- Same issue with PMUWDOG at CC+0x634: writing 0 = immediate reset

**What test.51 does:**
- Same as test.49: BBPLL up, normal firmware at TCM[0], ARM released
- Key change: READ-ONLY watchdog monitoring — NO writes to WDOG or PMUWDOG
- In activate(): read both registers, log them, DO NOT WRITE
- In poll loop: read both registers every 10ms, DO NOT WRITE
- Keep DisINTx=1 and BusMaster=0 from test.49
- Log format: "BCM4360 test.51: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG=0x... PMUWDOG=0x..."

**Why test.51 — read-only watchdog observation:**
- Need to confirm watchdog as crash mechanism by observing countdown in logs
- Expected: crash at ~490ms like tests 46-49, but WDOG values visible in log
- If WDOG counts down toward 0 at crash: CONFIRMED, watchdog is the mechanism
- test.52 will then service watchdog by writing a LARGE value (e.g., 0xFFFFFF) each iteration
  instead of 0 — extend the timeout continuously

**What activate() now does:**
- Sets DisINTx=1, BusMaster=0
- Reads + logs WDOG and PMUWDOG values (READ-ONLY)
- Logs: "BCM4360 test.51 activate: rstvec=0x... CMD=0x... WDOG=0x... PMUWDOG=0x... (read-only)"

**Per-iteration log format:**
  "BCM4360 test.51: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG=0x... PMUWDOG=0x..."

**Expected outcomes:**
- CRASH at ~49 iters, WDOG counts from non-zero to near 0: Watchdog CONFIRMED as mechanism.
  Next (test.52): service watchdog every iteration by writing a large value.
- CRASH at ~49 iters, WDOG=0 throughout: watchdog not the cause. Check other mechanisms.
  Next: investigate PMU reset, CPU exceptions, or firmware-triggered resets.
- PASS (no crash): something from test.49 that's NOT watchdog was causing the crash.
  Investigate what test.51 does differently.
- INSTANT CRASH (no messages): select_core call is causing the crash. Skip select_core.

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.51" | tail -60`
   OR find the right boot: `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.51" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.51.journal'`
3. Check WDOG column values: counting down? stuck at 0? non-zero and stable?
4. Check for MCE: `journalctl -b -1 | grep -i "mce\|machine check\|nmi"`
5. At what iter did crash occur?
6. `sudo chown kimptoc:users phase5/logs/test.51.*`
7. git add logs + commit + push
8. Plan test.52 based on result

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() once → 19 iters (950ms)
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 500 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation
- test.47: CRASHED — normal firmware + LnkSta reads → 19 iters, LINK STABLE (no drop!)
- test.48: CRASHED — normal firmware + BusMaster reads + forced off → 49 iters, CMD=0x0002; DMA RULED OUT
- test.49: CRASHED — DisINTx=1 + BusMaster=0 throughout → 49 iters, CMD=0x0402; INTx+MSI RULED OUT
- test.50: INSTANT CRASH — WRITECC32(watchdog, 0) = immediate hardware reset; no messages logged

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.51.stage0, test.51.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.51 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
