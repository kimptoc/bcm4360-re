# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.50)

Git branch: main (pushed to origin)

## test.50 is running / was about to run

**test.49 RESULT: CRASHED — INTx RULED OUT, MSI RULED OUT**
- CMD=0x0402 (DisINTx=1, MemEn=1, BusMaster=0) at EVERY iteration — firmware never changed it
- MSI_CTRL=0x0080 throughout — only 64-bit capability bit set, MSI NEVER ENABLED by firmware
- Same ~490ms crash timing (49 iters × 10ms = 490ms)
- Log: phase5/logs/test.49.journal

**All PCIe-level crash mechanisms now ELIMINATED:**
- DMA via Bus Master: RULED OUT (test.48, BusMaster=0 throughout)
- PCIe INTx: RULED OUT (test.49, DisINTx=1 throughout)
- MSI: RULED OUT (test.49, MSI_CTRL never had enable bit set)
- PCIe link drop: RULED OUT (test.47, LnkSta stable)
- PCIe AER errors: RULED OUT (test.46, no error escalation)

**What test.50 does:**
- Same as test.49: BBPLL up, normal firmware at TCM[0], ARM released
- **Key addition**: Disable ChipCommon watchdog (CC+0x80) AND PMU watchdog (CC+0x634)
  - In activate(): write 0 to both before ARM starts
  - In poll loop: write 0 to both every 10ms iteration
- Read watchdog values BEFORE zeroing each iteration to observe countdown
- Keep DisINTx=1 and BusMaster=0 from test.49

**Why test.50 — the watchdog hypothesis:**
- ALL PCIe-level mechanisms ruled out — remaining cause must be hardware timer
- BCM4360 firmware initializes a watchdog timer during startup
- ~490ms crash timing is consistent with ~512ms watchdog (0x80000 ALP clocks @ ~1MHz)
- If not serviced → chip reset → PCIe surprise removal → host hard crash
- No journal entry, no panic trace, no PCIe errors = consistent with chip-level hard reset
- ChipCommon watchdog at CC+0x80: writing 0 disables it (corerev >= 18, BCM4360 corerev=49)
- PMU watchdog at CC+0x634: secondary candidate

**What activate() now does:**
- Sets DisINTx=1, BusMaster=0
- Reads + logs WDOG and PMUWDOG values
- Writes 0 to both (disable before ARM starts)
- Logs: "BCM4360 test.50 activate: rstvec=0x... CMD=0x... WDOG=0x... PMUWDOG=0x... (both zeroed)"

**Per-iteration log format:**
  "BCM4360 test.50: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG=0x... PMUWDOG=0x..."

**Expected outcomes:**
- PASS (no crash, >500 iters): Watchdog confirmed as crash mechanism.
  Next: understand firmware watchdog usage, implement proper watchdog servicing for init.
- CRASH at 49 iters with WDOG=0/PMUWDOG=0 throughout: Watchdog not the cause.
  Check journalctl -b -1 for MCE/NMI entries. Look at platform-level reset mechanisms.
  May need to check ChipCommon RESETCTRL, SPROM, or PMU chipcontrol registers.
- CRASH at 49 iters with non-zero WDOG values visible: Firmware re-armed it but our
  zeroing didn't take effect (e.g., write-protected?). Try a different disable approach.

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.50" | tail -60`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.50.journal'`
3. Check WDOG/PMUWDOG columns: were they 0 or non-zero?
   - If always 0: watchdog was disabled, not the cause
   - If counting down: watchdog is cause but writes didn't prevent it
4. Check for MCE in journal: `journalctl -b -1 | grep -i "mce\|machine check\|nmi"`
5. At what iter did crash occur? Same ~49 or different?
6. `sudo chown kimptoc:users phase5/logs/test.50.journal`
7. git add logs + commit + push
8. Plan test.51 based on result

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() once → 19 iters (950ms)
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 500 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation
- test.47: CRASHED — normal firmware + LnkSta reads → 19 iters, LINK STABLE (no drop!)
- test.48: CRASHED — normal firmware + BusMaster reads + forced off → 49 iters, CMD=0x0002; DMA RULED OUT
- test.49: CRASHED — DisINTx=1 + BusMaster=0 throughout → 49 iters, CMD=0x0402; INTx+MSI RULED OUT

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.50.stage0, test.50.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.50 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
