# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.57)

Git branch: main (pushed to origin)

## test.56 RESULT: CRASH at iter=2 — two bugs caused crash after survived 2s sleep

**test.56 survived the 2s sleep, then crashed at iter=2 (~2010ms)**
- "sleeping 2000ms" logged ✓
- "woke up after 2s sleep" logged ✓
- iter=1: BAR0_WIN=0x18000000 (config read fine), CHIPID=0xffffffff (BAR0 MMIO dead)
- Crash at iter=2 — NOT logged

**TWO BUGS caused the crash:**

BUG 1: `loop_counter = 0; loop_counter--` → unsigned underflow to 0xFFFFFFFF
- Loop never exited as intended; continued to iter=2
- iter=2 `brcmf_pcie_read_reg32(devinfo, 0)` caused deferred PCIe error → NMI → crash
- FIX: replaced `loop_counter = 0` with `break`

BUG 2: Timeout diagnostics (READCC32 etc.) ran even when BAR0 MMIO dead
- After while loop: `if (sharedram_addr == sharedram_addr_written)` fires → READCC32 → crash
- FIX: `bar0_dead` flag → `return -ENODEV` before diagnostics block when BAR0 dead

**Key observation from test.56:**
- BAR0 config reads (pci_read_config_dword) WORK: BAR0_WIN=0x18000000
- BAR0 MMIO reads (brcmf_pcie_read_reg32) FAIL: 0xffffffff at 2010ms after ARM release
- This is DIFFERENT from test.55 where BAR0 MMIO was valid at 10ms (CHIPID=0x15034360)
- After 2s, firmware's PCIE2 init has done SOMETHING to make BAR0 MMIO inaccessible
- Key question: was PCI_COMMAND memory enable bit cleared? Were BAR addresses changed?

## test.57 PLAN (about to run)

**Strategy: same 2s sleep; fix both bugs; add safe config-space diagnostic reads**

What test.57 adds when CHIPID=0xffffffff:
- `pci_read_config_word(pdev, PCI_COMMAND, &pci_cmd)` — was memory enable cleared?
- `pci_read_config_dword(pdev, PCI_BASE_ADDRESS_0, &bar0_base)` — was BAR0 address changed?
- `pci_read_config_dword(pdev, PCI_BASE_ADDRESS_2, &bar2_base)` — was BAR2 address changed?
- All config space reads (safe even with dead MMIO)
- Then `bar0_dead=true; break` → safe exit → `return -ENODEV` (no MMIO diagnostics)

**Expected log line at iter=1:**
```
BCM4360 test.57 iter=1 BAR0_WIN=0x18000000 CHIPID=0xffffffff (BAR0 MMIO dead)
  PCI_CMD=0x???? BAR0_BASE=0x???????? BAR2_BASE=0x????????
```
Then: "BAR0 MMIO dead after 2s sleep — skipping MMIO diagnostics, returning -ENODEV"
Then: PC SURVIVES (no crash)

**Interpreting results:**
- PCI_CMD bit1 (MEM) = 0: firmware cleared memory enable → test.58 re-enables and retries
- BAR0_BASE != 0xb0600004: firmware reconfigured BARs → test.58 needs re-ioremap
- PCI_CMD bit1 = 1 + BARs unchanged: BAR0 MMIO dead for other reason → extend sleep to 5s in test.58

**Module build:** done (test.57 built successfully, no errors)
**Test script:** updated to test.57 (log = test.57.stage0)

**After test — what to do (whether PASS or crash):**
1. If SURVIVED: `grep "BCM4360 test.57" /path/dmesg` — check PCI_CMD + BAR values
2. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.57.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.57.*`
4. git add logs + commit + push
5. Analyze PCI_CMD + BAR addresses → plan test.58

**After a crash — what to do:**
1. Check which boot has test.57 messages:
   `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.57" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.57.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.57.*`
4. git add logs + commit + push
5. Analyze what was logged before crash — what read triggered it?

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
  PCI_CMD/BAR address state unknown (test.57 adds these reads)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.57.stage0, test.57.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.57 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
