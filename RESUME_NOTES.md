# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.61)

Git branch: main (pushed to origin)

## test.60 RESULT: CRASH at tick 39/40 (~T+7800-8000ms)

**MAJOR FINDING: per-tick re-masking pushed crash from 5s → 8s (one more event suppressed)**
- Ticks 1-39 all logged (T+200ms through T+7800ms)
- BC=0x0000 DC=0x0000 at ALL ticks — firmware never restored error bits
- Tick 25 (T+5000ms) survived — 5s event was suppressed by per-tick re-masking!
- Crash at tick 39/40 — a THIRD firmware event at ~8s
- Pattern: periodic firmware PCIE2 events at ~2s, ~5s, ~8s (every ~3s)
- RootCtl confirmed 0x0000 at boot (SECEE/SENFEE/SEFEE all 0 — not the missing path)

**Per-tick re-masking suppresses one event per 3s run, even though BC/DC read as 0:**
- The act of writing BC=0 / DevCtl=0 is side-effecting something (PCH internal state?)
- Or we're racing a brief firmware set+clear within the 200ms tick interval

## test.61 PLAN (about to run)

**Strategy: same masking + per-tick status register clearing + 20s heartbeat**

New additions vs test.60:
1. Log RootCtl at init (confirming 0x0000)
2. Probe ext config at 0x100 to check ECAM accessibility
3. Per tick: read+RW1C-clear DevSta (RP), SecSta, RootSta (in addition to BC/DC re-mask)
4. Per tick: also re-mask CMD SERR bit
5. 100 × 200ms = 20s heartbeat (covers 6+ periodic events)

**Hypothesis:** Status registers (DevSta/SecSta/RootSta) accumulate error flags during
firmware PCIE2 reinit events. Intel PCH SMM handler polls these and triggers system
reset when it sees persistent errors. Per-tick RW1C clearing prevents accumulation.

**Expected log per tick:**
```
BCM4360 test.61 tick=NNN/100 T+NNNNNms CMD=0x???? BC=0x???? DC=0x???? DS=0x???? SS=0x???? RS=0x????????
```
DS=DevSta, SS=SecSta (Secondary Status), RS=RootSta

**Interpreting results:**
- Any DS/SS/RS nonzero at crash tick → confirms SMM polling that register
- SURVIVED 20s: status clearing is the key; test.62 integrates into normal init
- Crash at ~11s: one more suppressed; check which status reg shows nonzero at last tick
- Crash at ~8s: status clearing didn't help; AER or completion timeout is remaining path

**Module build:** done (test.61 built successfully, no errors)
**Test script:** updated to test.61 (log = test.61.stage0)

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.61" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.61.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.61.*`
4. git add logs + commit + push
5. Analyze DS/SS/RS tick data → plan test.62

**After a crash:**
1. Check DS/SS/RS at last few ticks — any nonzero values = found escalation path
2. Check ext_cap0 value — if not 0/0xFFFFFFFF, ECAM is accessible and test.62 can mask AER
3. Last tick number × 200ms = crash timing (should be ~11s if pattern holds)

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

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.61.stage0, test.61.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.61 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
