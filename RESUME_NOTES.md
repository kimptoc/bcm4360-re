# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.55)

Git branch: main (pushed to origin)

## test.54 RESULT: INSTANT CRASH at iter 1 — BAR2 read crashes, NOT the write

**test.54 CONFIRMED: BAR0 reads all safe; crash is the unconditional BAR2 read after iter log**
- SBR succeeded: bridge_ctrl logged, "SBR complete" logged
- BAR0 probe = 0x15034360 (ALIVE after SBR)
- Chip_attach OK, BBPLL up (HAVEHT=YES), ARM released
- iter 1: BAR0_WIN=0x18000000, CHIPID=0x15034360, WDOG=0x00000000, PMUWDOG=0x00000000 (all good)
- Then brcmf_pcie_read_ram32(TCM[0x9fffc]) → PCIe Completion Timeout → NMI → host crash
- Root cause: real BCM4360 firmware (rstvec=0xb80ef000) initializes PCIE2 DMA within 10ms
  of ARM release (SBR gives clean state), making BAR2 temporarily inaccessible.
- With SBR: firmware reaches PCIE2 init in <10ms every time.
- Without SBR (test.43-49): firmware took 190-490ms, BAR2 reads worked for first ~19-49 iters.

## IMPORTANT CORRECTION: "B. injection" was only test.45

The RESUME_NOTES previously said "B. injected via activate()". This is WRONG.
- rstvec=0xb80ef000 is REAL BCM4360 firmware loaded from /lib/firmware
- The "B. injected" log string in brcmf_pcie_buscore_activate() is STALE from test.47 era
- The busyloop (0xEAFFFFFE) was only active in test.45
- Tests 46-54 all ran real firmware
- The pcie_shared marker 0xffc70038 = NVRAM data written to TCM[0x9fffc], NOT pcie_shared
  (pcie_shared would be a pointer into TCM, e.g. 0x000XXXXX)

## test.55 PLAN (about to run)

**What test.55 does:**
- Same SBR + chip_attach + BBPLL + ARM release sequence as test.54
- PRE-PHASE (iters 1-150, 0-1.5s): BAR0-only reads, NO BAR2
  - pci_read_config_dword BAR0_WINDOW (PCIe config)
  - brcmf_pcie_read_reg32(devinfo, 0) for CHIPID (BAR0+0)
  - READCC32(watchdog) and READCC32(pmuwatchdog) — guarded by BAR0_WIN==0x18000000 && CHIPID!=0xffffffff
  - Log at iters 1, 5, 10, 25, 50, 100, 150
  - Early exit (loop_counter=0) if CHIPID==0xffffffff
- POST-PHASE (iters 151-500, 1.5-5s): same BAR0 reads + BAR2
  - brcmf_pcie_read_ram32(TCM[ramsize-4]) for pcie_shared pointer
  - Log every 10 iters and immediately when BAR2 value changes from sharedram_addr_written
  - When BAR2 changes -> firmware wrote pcie_shared -> normal driver init proceeds

**Module build:** need to run make after this update
**Test script:** updated to test.55 (log = test.55.stage0)

**Expected outcomes:**
- PASS + BAR2 changes in post-phase iter ~20-100: firmware PCIE2 init takes ~200-1000ms.
  Normal driver init continues. wlan0 should appear.
  -> Study journal for timing. This is the goal: let driver fully initialize.
- CRASH in post-phase: BAR2 still not ready at 1.5s. Extend pre-phase.
  -> test.56: extend pre-phase to 300 or 400 iters.
- CRASH in pre-phase: BAR0 reads unsafe (unexpected — test.54 showed safe).
- 5s timeout (no BAR2 change): firmware never wrote pcie_shared. Check DMA/TCM.

**After a crash — what to do:**
1. Find the boot: `for b in -9 -8 -7 -6 -5 -4 -3 -2 -1; do echo "=== $b ==="; journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.5[56]" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.55.journal'`
3. Check which phase crashed (PRE or POST in log prefix)
4. Check at what iter the crash occurred
5. Check BAR0_WIN and CHIPID values — did ARM move the window?
6. `sudo chown kimptoc:users phase5/logs/test.55.*`
7. git add logs + commit + push

**After a PASS (wlan0 registered) — what to do:**
1. Save journal: `sudo bash -c 'journalctl -b 0 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.55.journal'`
2. Find when BAR2 changed: `grep "CHANGED" phase5/logs/test.55.stage0`
3. Check what iter that was -> tells us PCIE2 init duration
4. Check if wlan0 appeared: `ip link show wlan0`
5. `sudo chown kimptoc:users phase5/logs/test.55.*`
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

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.55.stage0, test.55.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.55 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
