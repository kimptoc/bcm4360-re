# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.58)

Git branch: main (pushed to origin)

## test.57 RESULT: CRASH at iter=1 (~2010ms after ARM release)

**test.57 crashed at iter=1 — same timing as test.56 iter=1, but now FATAL**
- "sleeping 2000ms" logged ✓
- "woke up after 2s sleep, starting poll" logged ✓
- Crash BEFORE any "iter=1" log line (i.e., before the first MMIO read completed)
- NO PCI_CMD / BAR address data captured

**Key finding — sharp timing boundary around 2010-2020ms:**
- test.56 iter=1 at ~2010ms: CHIPID MMIO read returned 0xffffffff (non-fatal, device silent)
- test.56 iter=2 at ~2020ms: CHIPID MMIO read crashed the host
- test.57 iter=1 at ~2010ms: CHIPID MMIO read crashed the host (same read, now fatal)
- Same timing, different outcomes — we are at the exact edge of the PCIE2 init danger window

**Conclusion:** The device is in a sharp transition state at ~2010ms. BAR0 MMIO cannot be read
safely anywhere in this window. Config-space reads (via RC) remain safe.

## test.58 PLAN (about to run)

**Strategy: config-space reads ONLY after 2s sleep — no BAR MMIO whatsoever**

What test.58 does after the 2s sleep (no polling loop for BCM4360):
- `pci_read_config_word(pdev, PCI_COMMAND, &pci_cmd)` — was memory enable cleared?
- `pci_read_config_dword(pdev, PCI_BASE_ADDRESS_0, &bar0_base)` — was BAR0 addr changed?
- `pci_read_config_dword(pdev, PCI_BASE_ADDRESS_2, &bar2_base)` — was BAR2 addr changed?
- `pci_read_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, &bar0_win)` — window register?
- Log all values and `return -ENODEV` immediately (no MMIO reads at all)

**Expected log line:**
```
BCM4360 test.58 config@2s: PCI_CMD=0x???? BAR0_BASE=0x???????? BAR2_BASE=0x???????? BAR0_WIN=0x????????
```
Then: PC SURVIVES (no crash — config reads are RC-routed, always safe)

**Interpreting results:**
- PCI_CMD bit1 (MEM) = 0: firmware cleared memory enable → test.59 re-enables it and tries MMIO
- BAR0_BASE != 0xb0600004: firmware reconfigured BARs → test.59 needs new ioremap
- BAR2_BASE != 0xb0400004: same for BAR2
- BAR0_WIN == 0x18000000: window register unchanged (expected)
- All values unchanged: device config intact, BAR MMIO was just transiently inaccessible

**Pre-test state:**
- Initial lspci: PCI_CMD Mem+, BAR0=0xb0600000 (64-bit, non-prefetch), BAR2=0xb0400000 (64-bit, non-prefetch)
- BAR registers include type bits: BAR0_BASE=0xb0600004, BAR2_BASE=0xb0400004

**Module build:** done (test.58 built successfully, no errors)
**Test script:** updated to test.58 (log = test.58.stage0)

**After test — what to do (whether PASS or crash):**
1. If SURVIVED: `grep "BCM4360 test.58" /home/kimptoc/bcm4360-re/phase5/logs/test.58.stage0`
2. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.58.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.58.*`
4. git add logs + commit + push
5. Analyze PCI_CMD + BAR addresses → plan test.59

**After a crash — what to do:**
1. Check which boot has test.58 messages:
   `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.58" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.58.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.58.*`
4. git add logs + commit + push
5. Determine what config read (if any) triggered the crash

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
  Survived 2s sleep. iter=1: BAR0_WIN=0x18000000 (config OK), CHIPID=0xffffffff (BAR0 MMIO dead)
  PCI_CMD/BAR address state unknown (test.57 was supposed to get these — crashed before)
- test.57: CRASH at iter=1 (~2010ms) — same CHIPID read, now fatal (timing variance)
  At the exact edge of PCIE2 init danger window. test.58: config-space only

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.58.stage0, test.58.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.58 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
