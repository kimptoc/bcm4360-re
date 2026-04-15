# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.52)

Git branch: main (pushed to origin)

## test.51 RESULT: INSTANT CRASH — select_core in activate() = immediate reset

**test.51 CONFIRMED: Calling select_core(CHIPCOMMON) inside activate() causes instant hardware reset**
- Machine crashed before ANY test.51 kernel message was logged
- Log file (test.51.stage0) cut off right after insmod; no journal messages either
- Boot -1: wlp0s20u2 messages, then sudo running test-staged-reset.sh at 09:32:01, then nothing
- Current boot started at 09:32 = machine rebooted instantly during insmod

**Root cause of test.51 crash:**
- activate() is called from brcmf_chip_cr4_set_active() during ARM init (chip.c line 1329)
- Calling select_core(CHIPCOMMON) inside activate() changes BAR0_WINDOW to ChipCommon base
- Something in the READCC32(devinfo, watchdog) or READCC32(devinfo, pmuwatchdog) read at this
  critical moment during ARM init causes an immediate hardware reset
- Test.49 activate() does NOT call select_core and runs fine for 49 iterations
- Conclusion: DO NOT call select_core or READCC32/WRITECC32 inside activate()

**What test.52 does:**
- activate(): IDENTICAL to test.49 — DisINTx=1, BusMaster=0, log message, write rstvec. NO select_core.
- Poll loop: BAR0 is already ChipCommon (set at ARM-release diagnostics block around line 1985)
  - Read WDOG pre-write value with READCC32(devinfo, watchdog) — NO select_core needed
  - Read PMUWDOG with READCC32(devinfo, pmuwatchdog) — NO select_core needed
  - SERVICE watchdog: WRITECC32(devinfo, watchdog, 0x7FFFFFFF) — resets countdown to ~107s
  - Log: "BCM4360 test.52: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG_PRE=0x... PMUWDOG=0x..."
- Keep DisINTx=1 and BusMaster=0 each iteration from test.49

**Why test.52 — active watchdog servicing:**
- Need to confirm watchdog as crash mechanism by PREVENTING it from firing
- Expected: PASS (no crash at 5s timeout, firmware still times out) = watchdog CONFIRMED
- If PASS: watchdog prevented crash; need to understand why firmware doesn't write shared RAM
- If CRASH at ~49 iters: watchdog NOT the mechanism (or something else also triggers)
- If INSTANT CRASH: something else in poll loop is wrong

**BAR0 state analysis:**
- After brcmf_pcie_buscore_reset(): BAR0 = PCIE2 (last select_core in reset is PCIE2 at ~line 777)
- After activate() (test.52): BAR0 still = PCIE2 (no select_core called)
- ARM-release block (lines 1978-1985): select_core(ARM_CR4), then select_core(CHIPCOMMON)
- Poll loop starts: BAR0 = ChipCommon — READCC32/WRITECC32 work without select_core

**Watchdog service value: 0x7FFFFFFF**
- BCM4360 watchdog at CC+0x080 is a countdown timer; write N = reset in N ALP ticks
- At ~20MHz ALP: 0x7FFFFFFF = 2,147,483,647 ticks = ~107 seconds
- Writing every 10ms poll keeps countdown far above 0, preventing expiry

**Per-iteration log format:**
  "BCM4360 test.52: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG_PRE=0x... PMUWDOG=0x..."

**Expected outcomes:**
- PASS (no crash, 5s timeout): Watchdog CONFIRMED as the crash mechanism for tests 43-49.
  Next: understand why firmware doesn't write shared RAM (pcie_shared ptr).
  Investigate: firmware console, TCM contents after timeout, ARM clk state.
- CRASH at ~49 iters, WDOG_PRE counts down to 0: watchdog not serviced (write broken?).
  Check if WRITECC32(devinfo, watchdog, val) actually works with current BAR0 state.
- CRASH at ~49 iters, WDOG_PRE stable or non-zero: second timer or different mechanism.
  Check PMUWDOG column — if counting, service that too in test.53.
- INSTANT CRASH (no messages): poll loop code broken. Compare line-by-line with test.49.

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.52" | tail -60`
   OR find the right boot: `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.52" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.52.journal'`
3. Check WDOG_PRE column values: counting down? stuck at 0? non-zero and stable?
4. Check for MCE: `journalctl -b -1 | grep -i "mce\|machine check\|nmi"`
5. At what iter did crash occur?
6. `sudo chown kimptoc:users phase5/logs/test.52.*`
7. git add logs + commit + push
8. Plan test.53 based on result

**After a PASS — what to do:**
1. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.52.journal'`
2. Check WDOG_PRE: did it count down then reset to 0x7FFFFFFF each iter?
3. `sudo chown kimptoc:users phase5/logs/test.52.*`
4. git add logs + commit + push
5. Investigate why firmware didn't write shared RAM — check TCM contents, ARM state

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
- test.51: INSTANT CRASH — select_core(CHIPCOMMON) in activate() = immediate hardware reset; no messages

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.52.stage0, test.52.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.52 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
