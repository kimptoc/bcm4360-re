# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.56)

Git branch: main (pushed to origin)

## test.55 RESULT: CRASH after PRE iter=1 — even BAR0 reads are fatal during PCIE2 init window

**test.55 showed: EVEN BAR0 reads crash the host during PCIE2 init**
- Logged: "BCM4360 test.55 PRE iter=1 BAR0_WIN=0x18000000 CHIPID=0x15034360 WDOG=0x00000000 PMUWDOG=0x00000000"
- PRE phase had NO BAR2 reads — only BAR0 config + MMIO reads
- Journal ends immediately after iter=1 log → crashed at ~20ms (iter=2) during BAR0 reads
- CONCLUSION: PCIE2 init makes ALL PCIe accesses fail (not just BAR2 as previously thought)
  - Even pci_read_config_dword / brcmf_pcie_read_reg32 (BAR0+0) → PCIe Completion Timeout → NMI → host crash
  - The danger window starts at <10ms after ARM release (firmware begins PCIE2 init immediately with SBR)
  - Duration of danger window: UNKNOWN — but must be < 2s (that's what test.56 tests)

## IMPORTANT CORRECTION: "B. injection" was only test.45

The RESUME_NOTES previously said "B. injected via activate()". This is WRONG.
- rstvec=0xb80ef000 is REAL BCM4360 firmware loaded from /lib/firmware
- The "B. injected" log string in brcmf_pcie_buscore_activate() is STALE from test.47 era
- The busyloop (0xEAFFFFFE) was only active in test.45
- Tests 46-55 all ran real firmware
- The pcie_shared marker 0xffc70038 = NVRAM data written to TCM[0x9fffc], NOT pcie_shared
  (pcie_shared would be a pointer into TCM, e.g. 0x000XXXXX)

## test.56 PLAN (about to run)

**Strategy: sleep 2000ms with ZERO PCIe reads after ARM release, then poll BAR0+BAR2**

Why 2000ms:
- With SBR, PCIE2 init starts at <10ms (much faster than without SBR where it was 190ms+)
- PCIE2 init duration unknown, but likely < 200ms based on firmware behavior
- 2000ms gives very large safety margin
- If crash happens DURING sleep → firmware-initiated crash (new mechanism to investigate)
- If crash happens on FIRST READ after sleep → 2s wasn't enough (extend to 5s)
- If PASS → firmware wrote pcie_shared during 2s window → normal driver init proceeds

**What test.56 does:**
- Same SBR + chip_attach + BBPLL + ARM release sequence
- After ARM release: log "sleeping 2000ms", msleep(2000), log "woke up"
- Zero PCIe reads during the 2000ms sleep
- Then poll BAR0+BAR2 every 10ms (500 iters = 5s total)
  - pci_read_config_dword BAR0_WINDOW
  - brcmf_pcie_read_reg32(devinfo, 0) CHIPID (BAR0+0)
  - READCC32(watchdog) and READCC32(pmuwatchdog) (guarded by bar0_ok)
  - brcmf_pcie_read_ram32(TCM[ramsize-4]) for pcie_shared pointer
  - Log at iters 1, 5, 10, 25, 50, 100 and immediately when BAR2 changes
  - Early exit if CHIPID=0xffffffff

**Module build:** done (test.56 built successfully)
**Test script:** updated to test.56 (log = test.56.stage0)

**Expected outcomes:**
- PASS + "woke up" logged + BAR2 changes in early iters (iter 1-10): PCIE2 init done within 2s.
  Normal driver init continues. wlan0 should appear.
  -> SUCCESS: study journal for timing, check if wlan0 registered.
- Crash BEFORE "woke up" log: firmware is ACTIVELY crashing the host (TLP, MSI, DMA).
  Not a PCIe read timeout. Need different approach (PCIe error containment, etc.)
  -> test.57: investigate firmware-initiated crash mechanism.
- Crash AFTER "woke up" on FIRST reads (iter=1): 2s wasn't enough; PCIE2 init takes >2s.
  -> test.57: extend sleep to 5000ms.
- 5s timeout (no BAR2 change): firmware never wrote pcie_shared. Investigate DMA/TCM.

**After a crash — what to do:**
1. Check if "woke up" was logged:
   `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.5[67]" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.56.journal'`
3. Check: did "sleeping 2000ms" appear? Did "woke up" appear? Did iter=1 appear?
4. `sudo chown kimptoc:users phase5/logs/test.56.*`
5. git add logs + commit + push

**After a PASS (wlan0 registered) — what to do:**
1. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.56.journal'`
2. Find BAR2 change: `grep "CHANGED" phase5/logs/test.56.stage0`
3. Check iter number → tells us how long firmware took to write pcie_shared AFTER 2s window
4. Check if wlan0 appeared: `ip link show wlan0`
5. `sudo chown kimptoc:users phase5/logs/test.56.*`
6. git add logs + commit + push
7. If wlan0 appeared: SUCCESS! Move to full firmware integration testing.

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

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.56.stage0, test.56.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.56 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
