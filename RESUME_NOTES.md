# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.54)

Git branch: main (pushed to origin)

## test.53 RESULT: INSTANT CRASH at iter 1 — WRITECC32(watchdog, 0x7FFFFFFF) crash trigger

**test.53 CONFIRMED: SBR worked, device alive, but CRASH after writing 0x7FFFFFFF to watchdog**
- SBR succeeded: bridge_ctrl logged, "SBR complete" logged
- BAR0 probe = 0x15034360 (ALIVE — device responded after SBR)
- Chip_attach succeeded, EFI state logged, BBPLL up (HAVEHT=YES), ARM released
- ARM-release: IOCTL=0x00000001 RESET_CTL=0x00000000 ARM_CLKST=0x070b0040
- iter 1: WDOG_PRE=0x00000000, PMUWDOG=0x00000000 (neither timer running at T+10ms)
- Then WRITECC32(watchdog, 0x7FFFFFFF) → "iter 1" logged → CRASH
- Journal ends at iter 1; no iter 2 logged
- Root cause: writing 0x7FFFFFFF to ChipCommon watchdog register causes device reset or
  AXI fault, which makes subsequent BAR2 TCM read fail (Completion Timeout → NMI → host crash)

**Key questions for test.54:**
1. Is it the WRITE that triggers the crash, or is something wrong with the READS too?
2. Has the ARM firmware changed BAR0_WINDOW between select_core(CHIPCOMMON) at line 1985
   and the poll loop reads? (ARM could change BAR0_WINDOW from its AXI side)
3. If we remove the WRITE, does the crash move back to ~49 iters (natural crash mechanism)?

**What test.54 does:**
- Same SBR + chip_attach + BBPLL + ARM release sequence as test.53
- Poll loop: same PCIe config reads (CMD, MSI_CTRL)
- NEW: read BAR0_WINDOW from PCIe config register 0x80 (tells us if ARM changed window)
- NEW: read BAR0+0 (chip ID = 0x15034360 if still ChipCommon; different if ARM moved window)
- Read WDOG (CC watchdog) and PMUWDOG (PMU watchdog) — same as test.53
- **NO WRITECC32** — removed the 0x7FFFFFFF write to isolate reads from write
- Log: "BCM4360 test.54: iter N val=... CMD=... MSI_CTRL=... BAR0_WIN=... CHIPID=... WDOG=... PMUWDOG=..."

**Expected outcomes:**
- CRASH at ~49 iters + BAR0_WIN=CC_BASE + CHIPID=0x15034360: WRITE was the iter-1 trigger.
  BAR0 reads are safe. Natural crash at ~49 iters = ARM programs a short watchdog that fires.
  → test.55: service both ChipCommon watchdog AND PMU watchdog (WRITE to pmuwatchdog too).
- CRASH at iter 1 + BAR0_WIN != CC_BASE: ARM changed BAR0_WINDOW; reads hit wrong space.
  → test.55: re-call select_core(CHIPCOMMON) at the START of each poll iteration (before reads).
- CRASH at iter 1 + BAR0_WIN == CC_BASE + CHIPID == 0x15034360: reads themselves crash.
  Possible: READCC32(pmuwatchdog) has side effects on BCM4360 that cause reset.
  → test.55: only read CC watchdog, not PMU watchdog. Or only read BAR0_WIN+CHIPID.
- CRASH at iter 1 + BAR0_WIN == CC_BASE + CHIPID != 0x15034360: contradictory; window is CC
  but chipid is wrong — could mean the CC isn't responding, reads return 0xffffffff or garbage.
- PASS (no crash at 5s): all reads are safe without the write. Why did test.49 crash at 49 iters?
  → check TCM tail value in timeout diagnostics.

**After a crash — what to do:**
1. Find the boot: `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.5[34]" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.54.journal'`
3. Check BAR0_WIN column: does it match ChipCommon base (0x18000000)?
4. Check CHIPID column: 0x15034360 = CC; 0xffffffff = dead; other = moved window
5. Check at what iter the crash occurred
6. Check WDOG and PMUWDOG values across iterations — are they counting down?
7. `sudo chown kimptoc:users phase5/logs/test.54.*`
8. git add logs + commit + push

**After a PASS — what to do:**
1. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.54.journal'`
2. Check BAR0_WIN column — did it change across iterations?
3. Check WDOG/PMUWDOG — did they count down then reset?
4. `sudo chown kimptoc:users phase5/logs/test.54.*`
5. git add logs + commit + push
6. Plan test.55: service the watchdog timers identified as countdown

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
- test.52: INSTANT CRASH — crash during chip enumeration BAR0 MMIO reads (device in bad state from 50/51)
- test.53: INSTANT CRASH at iter 1 — WRITECC32(watchdog, 0x7FFFFFFF) → crash after logging iter 1

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.54.stage0, test.54.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.54 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
