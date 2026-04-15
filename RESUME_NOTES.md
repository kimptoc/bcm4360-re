# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.53)

Git branch: main (pushed to origin)

## test.52 RESULT: INSTANT CRASH — crashes during chip enumeration BAR0 MMIO reads

**test.52 CONFIRMED: crash occurs AFTER brcmf_pcie_get_resource() but BEFORE brcmf_pcie_reset_device()**
- Logged: "BCM4360 debug: BAR0=0xb0600000 BAR2=0xb0400000 BAR2_size=0x200000 tcm=..."
- DID NOT log: "BCM4360 EFI state:" (from brcmf_pcie_reset_device in chip_attach → reset callback)
- This means crash is during chip enumeration BAR0 MMIO reads (between prepare and reset callbacks)
- Root cause: tests 50/51 left BCM4360 AXI fabric in bad state → BAR0 MMIO reads fail (Completion Timeout → NMI)
- Watchdog servicing code (the actual test.52 goal) never ran

**Why test.52 crashed earlier than test.49 (which did not crash during chip_attach):**
- test.49 ran on a cleanly initialized device (from normal boot)
- test.52 ran after tests 50+51 caused instant crashes → BCM4360 AXI fabric left in bad state
- PCIe config reads (lspci) still work, but BAR0 MMIO reads do not → Completion Timeout

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

**What test.53 does:**
- Pre-chip_attach: secondary bus reset (SBR) via upstream bridge PCIe config cycles only
  - pci_save_state → bridge SBR bit ON (10ms) → OFF → 200ms recovery → pci_restore_state
  - Resets BCM4360 AXI fabric to clean power-on-reset state without needing BAR0 MMIO
  - Logged as: "BCM4360 test.53: SBR via bridge ... before chip_attach"
- get_resource: BAR0 probe read at CC offset 0 after ioremap (tests MMIO responsiveness)
  - Sets BAR0_WINDOW=0x18000000, reads offset 0 (ChipCommon chip ID)
  - Logged as: "BCM4360 test.53: BAR0 probe ... = 0x..." (0xffffffff = dead, valid = alive)
- activate(): identical to test.49/52 — DisINTx=1, BusMaster=0, write rstvec, NO select_core
- Poll loop: BAR0 already = ChipCommon; read WDOG_PRE, read PMUWDOG, WRITE 0x7FFFFFFF to service
  - Log: "BCM4360 test.52: iter N val=0x... CMD=0x... MSI_CTRL=0x... WDOG_PRE=0x... PMUWDOG=0x..."

**BAR0 state analysis:**
- After SBR + pci_restore_state: BAR0_WINDOW reset to 0, BAR addresses restored
- After brcmf_pcie_buscore_reset(): BAR0 = PCIE2 (last select_core in reset is PCIE2 at ~line 777)
- After activate() (test.53): BAR0 still = PCIE2 (no select_core called)
- ARM-release block (lines 1978-1985): select_core(ARM_CR4), then select_core(CHIPCOMMON)
- Poll loop starts: BAR0 = ChipCommon — READCC32/WRITECC32 work without select_core

**Expected outcomes:**
- SBR logs + BAR0 probe prints valid value + PASS (5s timeout): WATCHDOG CONFIRMED as crash mechanism
- SBR logs + BAR0 probe prints 0xffffffff: device dead even after SBR → need power cycle (full shutdown)
- SBR logs but no BAR0 probe log: MMIO itself crashes after SBR → device deeply broken
- INSTANT CRASH before SBR logs: something in probe pre-SBR crashes → very unlikely
- CRASH at ~49 iters: watchdog not the mechanism; check PMUWDOG column for second timer
- CRASH at ~49 iters but WDOG_PRE stable: PMUWDOG counting? → service both in test.54

**After a crash — what to do:**
1. Find the boot: `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.5[23]" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.53.journal'`
3. Check SBR and BAR0 probe messages: did they log? What was BAR0 probe value?
4. Check WDOG_PRE column values: counting down? stuck at 0? non-zero and stable?
5. Check for MCE: `journalctl -b -1 | grep -i "mce\|machine check\|nmi"`
6. At what iter did crash occur?
7. `sudo chown kimptoc:users phase5/logs/test.53.*`
8. git add logs + commit + push

**After a PASS — what to do:**
1. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.53.journal'`
2. Check WDOG_PRE: did it count down then reset to 0x7FFFFFFF each iter?
3. `sudo chown kimptoc:users phase5/logs/test.53.*`
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
- test.52: INSTANT CRASH — crash during chip enumeration BAR0 MMIO reads (device in bad state from 50/51)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.53.stage0, test.53.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.53 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
