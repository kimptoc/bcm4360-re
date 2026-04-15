# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.49)

Git branch: main (pushed to origin)

## test.49 is running / was about to run

**test.48 RESULT: CRASHED — BusMaster=0 throughout all 49 iters**
- CMD=0x0002 (MemEn only, BusMaster=0) at EVERY iteration
- Firmware DID NOT re-enable BusMaster from device side
- **DMA theory DEFINITIVELY RULED OUT**
- Machine crashed ~490ms (49 iters × ~10ms effective per iter)
- 490ms ≈ 950ms: timing consistent (10ms sleep + ~8 config reads/iter ≈ 20ms/iter effective)
- Log: phase5/logs/test.48.journal

**What test.49 does:**
- Same as test.48: BBPLL up, normal firmware at TCM[0], ARM released
- **Key addition**: set PCI_COMMAND_INTX_DISABLE (bit 10 = 0x0400) before ARM release
  AND re-enforce DisINTx=1 every 10ms iteration
- Also reads MSI Message Control each iter to detect if firmware enables MSI
- BusMaster still cleared (retained from test.48)

**Why test.49 — the INTx hypothesis:**
- INTx does NOT require Bus Master — uses PCIe OrderedMessages (Assert_INTx), not TLPs
- Pre-test state: DisINTx- (INTx enabled), MSI: Enable- (INTx is the only active interrupt path)
- "Interrupt: pin A routed to IRQ 0" — level-triggered, no handler registered by our test module
- Level-triggered INTx with no handler → interrupt storm → hard lockup, no journal entry
- This matches all crash signatures: no journal, no panic trace, hard reset
- test.45 (B. loop) PASS: firmware never reaches interrupt-assertion point in init sequence
- All previous tests with real firmware: CRASH at ~950ms — consistent firmware init timer

**What activate() now does:**
- pci_read_config_word → clear MASTER bit → set INTX_DISABLE bit → write back
- Logs: "BCM4360 test.49 activate: rstvec=0x... to TCM[0]; DisINTx=1 BusMaster=0 CMD=0x..."

**Expected outcomes:**
- PASS (no crash, >500 iters): INTx storm CONFIRMED as crash mechanism.
  Next: understand when firmware fires INTx, implement proper IRQ handling for normal init.
- CRASH with DisINTx=1 logged throughout: INTx ruled out.
  Next: check MSI_CTRL log — did firmware enable MSI? (MSI also can't DMA without BusMaster
  but MSI Enable bit could indicate interrupt-related path). If MSI also off: look for NMI,
  MCE, or platform reset mechanism. May need to read watchdog register (ChipCommon+0x044).
- CRASH with DisINTx=0 logged at some iter: firmware cleared DisINTx bit.
  Next: also enforce DisINTx on the config write side OR disable MSI cap simultaneously.

**PCI_COMMAND bits (offset 0x04):**
- bit 0 (0x0001) = I/O Space Enable
- bit 1 (0x0002) = Memory Space Enable
- bit 2 (0x0004) = Bus Master Enable ← kept=0
- bit 10 (0x0400) = INTx Emulation Disable ← NEW for test.49

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.49" | tail -60`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.49.journal'`
3. Check: was CMD ever 0x0402 (DisINTx=1, MemEn=1)? If so DisINTx was active → INTx ruled out
4. Check: was MSI_CTRL ever non-zero? If MSI_CTRL bit0=1 (MSI Enable) → firmware tried MSI
5. At what iter did crash occur? Earlier or same ~49 iters?
6. git add logs + commit + push
7. Plan test.50 based on result

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() once → 19 iters (950ms)
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 500 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation
- test.47: CRASHED — normal firmware + LnkSta reads → 19 iters, LINK STABLE (no drop!)
- test.48: CRASHED — normal firmware + BusMaster reads + forced off → 49 iters, CMD=0x0002 throughout; DMA RULED OUT

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.49.stage0, test.49.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.49 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
