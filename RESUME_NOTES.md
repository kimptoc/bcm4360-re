# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.59)

Git branch: main (pushed to origin)

## test.58 RESULT: CRASH DURING 2s SLEEP

**The crash is FIRMWARE-DRIVEN — happens with zero PCIe reads from our side.**
- "sleeping 2000ms — NO PCIe reads" logged ✓
- Machine crashed DURING the 2s sleep — no "woke up" message, no config reads logged
- NO AER errors, NO NMI, NO MCE — journal just stops cold (same as all prior crashes)
- This proves our MMIO reads were NOT causing the crash; the firmware does it independently

**Timing consistency:**
- test.56/57: crashed at ~2010ms during MMIO reads (mistakenly attributed to reads)
- test.58: crashed at <2000ms during sleep (same event, 10-50ms earlier = timing variance)
- The firmware crash event happens at ~1900-2100ms after ARM release (±100ms variance)

**Conclusion:** BCM4360 firmware PCIE2 core initialization at ~2s causes a fatal PCIe event
that the Intel root port escalates before any kernel log can be written.

**Likely mechanism:** Firmware resets/re-inits its PCIE2 endpoint controller, causing:
- Surprise link-down at root port, OR
- Malformed TLP / unexpected completion escalated via AER → SERR → fatal reset

## test.59 PLAN (about to run)

**Strategy: disable root-port error escalation before the 2s danger window**

What test.59 does after ARM release:
1. Find root port (bus->self = 0000:00:1c.2); log its BDF for confirmation
2. Disable four error escalation paths:
   a. `PCI_COMMAND_SERR = 0` on root port
   b. `PCI_BRIDGE_CTL_SERR = 0` on root port
   c. `DevCtl bits 0-3 = 0` (CERE/NFERE/FERE/URRE) on root port
   d. `AER root error command = 0` on root port
   → Log before/after values of all four registers
3. Heartbeat: 25 × 200ms = 5s, reading PCI_CMD at each tick
4. If survived: log "SURVIVED", restore error reporting, return -ENODEV

**Expected log lines (if survived):**
```
BCM4360 test.59: root port = 0000:00:1c.2; disabling error escalation
BCM4360 test.59: masked: CMD=0x????→0x???? BC=0x????→0x???? DevCtl=0x????→0x???? AER_RC=0x????????→0x00000000
BCM4360 test.59: starting heartbeat (25×200ms=5s); watching PCI_CMD
BCM4360 test.59 tick=01/25 T+0200ms PCI_CMD=0x????
...
BCM4360 test.59 tick=25/25 T+5000ms PCI_CMD=0x????
BCM4360 test.59: SURVIVED 5s!
BCM4360 test.59: RP error reporting restored
```

**Interpreting results:**
- SURVIVED: error escalation was crash mechanism; PCI_CMD ticks show BusMaster state
  - PCI_CMD bit 2 set after tick ~10: firmware re-enabled BusMaster → test.60 disables it again
  - PCI_CMD constant 0x0402: firmware never changes it → start MMIO reads after 5s
- STILL CRASHES at tick N: mechanism ≠ PCIe error escalation; timing = N×200ms from ARM release
  - test.60: try disabling link (LNKCTL.LD=1) or D3cold before ARM release
- No "masked:" log before "starting heartbeat": root port not found → check bus topology

**Module build:** done (test.59 built successfully, no errors)
**Test script:** updated to test.59 (log = test.59.stage0)

**After test — what to do (whether PASS or crash):**
1. If SURVIVED: `grep "BCM4360 test.59" /home/kimptoc/bcm4360-re/phase5/logs/test.59.stage0`
2. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.59.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.59.*`
4. git add logs + commit + push
5. Analyze tick data → plan test.60

**After a crash — what to do:**
1. Check which boot has test.59 messages:
   `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.59" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.59.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.59.*`
4. git add logs + commit + push
5. Check last tick logged + whether "masked:" line appeared → diagnose

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
- test.54: INSTANT CRASH at iter 1 — BAR2 read crashes; BAR0 reads all SAFE
  BAR0_WIN=0x18000000, CHIPID=0x15034360, WDOG=0, PMUWDOG=0 (all normal)
  Root cause: firmware PCIE2 DMA init makes BAR2 inaccessible within 10ms of ARM release
- test.55: CRASH after PRE iter=1 — BAR0 reads ALSO fatal during PCIE2 init window
  PRE phase had NO BAR2 reads; crash at iter=2 (~20ms) during BAR0 reads
  ALL PCIe accesses (BAR0 + BAR2) fail during PCIE2 init danger window
- test.56: CRASH at iter=2 (~2010ms) — bugs: loop_counter underflow + MMIO diagnostics on dead BAR0
  Survived 2s worth of polling. iter=1: BAR0_WIN=0x18000000 (config OK), CHIPID=0xffffffff (BAR0 MMIO dead)
  PCI_CMD/BAR address state unknown (test.57 was supposed to get these — crashed before)
- test.57: CRASH at iter=1 (~2010ms) — same CHIPID read, now fatal (timing variance)
  At the exact edge of PCIE2 init danger window. test.58: config-space only
- test.58: CRASH DURING 2s SLEEP — firmware crashes host with ZERO reads from our side
  Key finding: crash is firmware-driven at ~2000ms after ARM release, not caused by our reads

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.59.stage0, test.59.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.59 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
