# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.46)

Git branch: main (pushed to origin)

## Test.46 is running / was about to run

**What test.46 does:**
- BBPLL brought up (max_res_mask+min_res_mask=0xFFFFF)
- Normal firmware: rstvec=0xb80ef000 written to TCM[0] (no B. injection)
- ARM is released — real firmware runs
- Wait loop reads PCIe error registers at EVERY iteration (50ms intervals):
  - `PCI_STATUS` (config offset 0x06): master/target abort, parity error
  - `DEV_DEVSTA` (BCM4360 PCIe DevSta): correctable/uncorrectable/fatal error bits
  - `BR_DEVSTA` (host bridge PCIe DevSta): same from host side
  - All via pci_read_config_word() — config space, survives device errors

**Why test.46:**
- test.45 PASSED: B. at TCM[0] survived 5s, 100 iters — ARM safe when not running firmware
- Confirmed: firmware execution IS the crash mechanism
- test.46 runs real firmware + captures PCIe error type at each iteration

**Expected: PC crashes at ~19 iters (~950ms). Journal should show:**
- Iters 1-18 with DEV_DEVSTA/BR_DEVSTA values
- Non-zero error register at crash iter indicates PCIe error type

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.46" | tail -40`
2. Save journal: `sudo journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.46.journal`
   (Note: phase5/logs/ owned by root — needs sudo)
3. Check: what iter was last, were DEV_DEVSTA/BR_DEVSTA non-zero?
4. PCI_EXP_DEVSTA bits: bit 0=correctable, bit 1=non-fatal uncorr, bit 2=fatal, bit 3=unsupported req
5. PCI_STATUS bits: bit 13 (0x2000)=parity, bit 12 (0x1000)=sig target abort,
   bit 11 (0x0800)=recv master abort, bit 9 (0x0200)=sig SERR
6. git add logs + commit + push
7. Plan test.47 based on error type

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() → 19 iters
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 100 iters
- test.46: IN PROGRESS — normal firmware + PCIe error diagnostic reads

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.46.stage0, test.46.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.46 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
