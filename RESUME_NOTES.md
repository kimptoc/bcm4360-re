# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.62)

Git branch: main (pushed to origin)

## test.61 RESULT: SURVIVED 20s — MAJOR MILESTONE

**All 100 ticks logged (T+200ms through T+20000ms), 6+ periodic PCIE2 events suppressed**
- DS=0x0010 (AuxPwr only) throughout — no error bits in DevSta/SecSta/RootSta
- SS=0x0000 and RS=0x00000000 throughout — status registers stayed clean
- ext_cap0=0x20000000 — ECAM is accessible! (Cap ID=0 at 0x100, next ptr=0x200)
- Key insight: unconditional RW1C writes reset PCH internal state (not bit values)
- Per-tick BC/DevCtl/CMD re-masking + status clearing defeats ALL periodic ~3s events
- Masking NOT restored on exit (to avoid re-triggering crashes post-module)

## test.62 PLAN (about to run)

**Strategy: same masking + combined FW wait loop (test -ENODEV still returned)**

Goal: confirm two things:
1. BAR0 MMIO reads (brcmf_pcie_read_ram32) are safe under masking
2. BCM4360 firmware actually writes sharedram_addr within 20s

Design:
- Initial masking identical to test.61 (CMD, BC, DevCtl, AER, status regs)
- Outer loop: 200ms masking tick; inner loop: 20×10ms sharedram polls
- Sentinel = 0 (driver wrote 0 to ramsize-4 at line 1808 before ARM release)
- Filter 0xFFFFFFFF (transient PCIE2 completion timeout)
- On FW ready: log sharedram_addr + timing; return -ENODEV ("test.63 next")
- Masking NOT restored on exit

**Module build:** done (test.62 built successfully, no errors)
**Test script:** updated to test.62 (log = test.62.stage0)

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.62" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.62.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.62.*`
4. git add logs + commit + push
5. Analyze: did FW write sharedram? At what time? → plan test.63

**After a crash:**
1. Look for last logged T+ time — crash during FW wait means BAR0 reads still unsafe
2. Check if crash happened during inner loop (10ms polls) or outer loop (masking)
3. Compare crash timing to 3s periodic pattern (2s, 5s, 8s...)

**After success (FW READY logged):**
1. Note the T+Xms when sharedram was detected (typically 2-3s after ARM release)
2. Note the sharedram_addr value — should be in [rambase, rambase+ramsize)
3. test.63: remove the -ENODEV and let full probe continue

## Test history summary
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
- test.59: CRASH at tick 24/25 (T+4800-5000ms) — survived 2s window! Second event at ~5s
  BC+DevCtl masking suppressed 2s crash; PCI_CMD=0x0402 throughout; aer_cap=0
- test.60: CRASH at tick 39/40 (T+7800-8000ms) — survived 5s window! Third event at ~8s
  BC/DC always 0x0000; per-tick re-masking suppressed 5s event; RootCtl=0x0000
- test.61: SURVIVED 20s! — status clearing + re-masking defeats all events
  DS=0x0010 (AuxPwr) always; SS/RS always 0; ext_cap0=0x20000000 (ECAM accessible)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.62.stage0, test.62.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.62 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
