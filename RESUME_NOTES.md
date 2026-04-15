# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.47)

Git branch: main (pushed to origin)

## Test.47 is running / was about to run

**What test.47 does:**
- Same as test.46: BBPLL up, normal firmware at TCM[0], ARM released
- Per-iteration monitor loop now reads BOTH DevSta AND LnkSta from device + bridge:
  - `PCI_STATUS` (config 0x06): master/target abort
  - `DEV_DEVSTA` (BCM4360 PCIe DevSta): error bits
  - `DEV_LNKSTA` (BCM4360 PCIe LnkSta): link active, training, speed, width
  - `BR_DEVSTA` (host bridge DevSta): host side errors
  - `BR_LNKSTA` (host bridge LnkSta): host side link state

**Why test.47:**
- test.46 CRASHED at iter 19 (~950ms) — same timing as test.43
- test.46 KEY FINDING: SERR and ALL PCIe error reporting was ALREADY OFF (BusMaster-
  SERR- CorrErr- NonFatalErr- FatalErr- UnsupReq- in lspci pre-state)
- Error registers CONSTANT through all 19 iters: DEV_DEVSTA=0x0011, BR_DEVSTA=0x0010
  (CorrErr bit 0 and AuxPwr bit 4 — pre-existing, no escalation)
- Sharedram marker 0xffc70038 UNCHANGED — firmware never completed initialization
- CONCLUSION: crash is NOT from PCIe error signaling. Mechanism is something else.

**Hypothesis for test.47:**
- 950ms timing matches a firmware watchdog (~1s)
- Firmware watchdog fires (firmware couldn't init properly), resets the internal
  PCIe2 endpoint core from the chip side
- PCIe link drops from endpoint side → host crashes from sudden link failure
- LnkSta should show DLActive=0 or Training=1 in the iteration before crash

**Expected: PC crashes at ~19 iters (~950ms). Journal should show:**
- Iters 1-18: DEV_LNKSTA stable (e.g., 0x5041 = 2.5GT/s x1 Active)
- Iter 18 or 19: DEV_LNKSTA shows link down (DLActive=0) or training

**PCI_EXP_LNKSTA bits (0x12 offset in PCIe cap):**
- bits [3:0] = Current Link Speed (1=2.5GT/s, 2=5GT/s)
- bits [9:4] = Negotiated Link Width (1=x1, 4=x4 etc)
- bit 11 (0x0800) = Link Training
- bit 12 (0x1000) = Slot Clock Configuration
- bit 13 (0x2000) = Data Link Layer Link Active (DLActive)
- bit 14 (0x4000) = Link Bandwidth Management Status
- bit 15 (0x8000) = Link Autonomous Bandwidth Status

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.47" | tail -40`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.47.journal'`
3. Check: was DEV_LNKSTA different in the last iter vs first iters?
4. If LnkSta dropped → firmware watchdog confirmed as crash mechanism
5. If LnkSta stable → crash is from something else (NMI, MCE, hard reset)
6. git add logs + commit + push
7. Plan test.48 based on result

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() → 19 iters
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 100 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.47.stage0, test.47.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.47 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
