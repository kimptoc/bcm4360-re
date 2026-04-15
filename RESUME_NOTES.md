# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.60)

Git branch: main (pushed to origin)

## test.59 RESULT: CRASH at tick 24/25 (between T+4800ms and T+5000ms)

**MAJOR BREAKTHROUGH: survived the 2s danger window!**
- Ticks 1-24 all logged (T+200ms through T+4800ms)
- Tick 10 (T+2000ms) and tick 11 (T+2200ms) both survived — the 2s event was masking-suppressed
- PCI_CMD stayed 0x0402 throughout — BusMaster (bit 2 = 0x0004) never set by firmware
- aer_cap=0: AER extended capability not found (ECAM broken on this platform?)
- Crash between T+4800ms and T+5000ms — a SECOND firmware event at ~5s

**What masking did:**
- CMD=0x0407→0x0407 (SERR already off in CMD — no change needed)
- BC=0x0002→0x0000 (BridgeCtl SERR forwarding cleared — KEY)
- DevCtl=0x000e→0x0000 (NonFatalErr+FatalErr+UnsupReq cleared — KEY)
- AER_RC: not masked (aer_cap=0, so skipped)

**Conclusion:** BCM4360 firmware has TWO PCIE2 initialization events:
1. Event at ~2000ms — suppressed by BC+DevCtl masking (test.59 survived it)
2. Event at ~5000ms — same mechanism? Different mechanism? Unknown. test.60 investigates.

**Hypothesis for 5s crash:**
- A: Firmware restores BC/DevCtl error bits during the 2s event, then 5s event crashes on them
- B: BC/DevCtl stayed zero; 5s event uses a different escalation path (AER/SMI via aer_cap?)
- Per-tick re-masking in test.60 will discriminate between A and B.

## test.60 PLAN (about to run)

**Strategy: same masking + per-tick re-masking + BC/DC log at each tick**

What test.60 does after ARM release:
1. Same initial masking as test.59 (CMD, BC, DevCtl, AER_RC)
2. 40 × 200ms heartbeat = 8s total (covers 5s event with 3s margin)
3. At each tick: READ BC + DevCtl BEFORE re-masking → log CMD + BC + DC
4. Re-apply BC=0 and DevCtl=0 after reading (in case firmware restored them)
5. If survived: log "SURVIVED 8s!", restore, return -ENODEV

**Expected log lines (if survived):**
```
BCM4360 test.60: root port = 0000:00:1c.2; disabling error escalation
BCM4360 test.60: masked: CMD=0x????→0x???? BC=0x????→0x???? DevCtl=0x????→0x???? AER_RC=...
BCM4360 test.60: starting heartbeat (40×200ms=8s); re-masking each tick
BCM4360 test.60 tick=01/40 T+0200ms CMD=0x???? BC=0x???? DC=0x????
...
BCM4360 test.60 tick=40/40 T+8000ms CMD=0x???? BC=0x???? DC=0x????
BCM4360 test.60: SURVIVED 8s!
BCM4360 test.60: RP error reporting restored
```

**Interpreting results:**
- BC or DC nonzero at tick ~10 (2000ms): firmware restored error bits; re-masking prevents 5s crash
  - If SURVIVED: hypothesis A confirmed; test.61 needs to keep re-masking forever
- BC=0 DC=0 throughout but CRASH at ~5s: hypothesis B; different escalation path
  - test.61: try pci_disable_device(rp) or LNKCTL link disable before ARM release
- SURVIVED 8s + BC/DC always 0: masking alone works; test.61 attempts MMIO reads past 5s

**Module build:** done (test.60 built successfully, no errors)
**Test script:** updated to test.60 (log = test.60.stage0)

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.60" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.60.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.60.*`
4. git add logs + commit + push
5. Analyze BC/DC tick data → plan test.61

**After a crash:**
1. Check for BC/DC values in last few ticks — did firmware restore them?
2. Last tick number × 200ms = crash timing

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
- test.59: CRASH at tick 24/25 (T+4800-5000ms) — survived 2s window! Second event at ~5s
  BC+DevCtl masking suppressed 2s crash; PCI_CMD=0x0402 throughout; aer_cap=0

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.60.stage0, test.60.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.60 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
