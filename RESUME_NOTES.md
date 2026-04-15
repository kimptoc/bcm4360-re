# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, running test.48)

Git branch: main (pushed to origin)

## Test.48 is running / was about to run

**What test.48 does:**
- Same as test.47: BBPLL up, normal firmware at TCM[0], ARM released
- Key addition: reads PCI_COMMAND every 10ms to check if firmware re-enables BusMaster
- pci_clear_master() called just before ARM release AND every 10ms iteration
- Sleep reduced from 50ms to 10ms for finer timing resolution
- Expected crash at ~iter 95 (~950ms) if same mechanism as test.47

**Why test.48:**
- test.47 CRASHED at iter 19 (~950ms). CRITICAL FINDING: DEV_LNKSTA=0x1011 CONSTANT
  through all 19 iters. PCIe link NEVER dropped, no training, no link state change.
- No PCIe error escalation (confirmed from test.46/47).
- Crash mechanism is NOT link drop, NOT PCIe error signaling.

**Gap in test.43 analysis:**
- test.43 called pci_clear_master() ONCE before ARM release, then assumed BusMaster stayed off.
- BCM4360 firmware has AXI bus access to its own PCIe2 endpoint registers.
- Firmware CAN write PCI_COMMAND bit2 (BusMaster) from device side at any time.
- test.43 never READ PCI_COMMAND during iterations to verify it stayed disabled.
- IOMMU group 6 is huge (PCIe root ports + many devices) — provides ZERO isolation.
- If firmware re-enables BusMaster and D11 DMA writes to arbitrary physical address
  (page tables, GDT, IDT), host CPU triple-faults: instant crash, no journal entry.
  This matches the crash signature perfectly.

**Expected outcomes:**
- PASS (no crash): firmware was re-enabling BusMaster → DMA is confirmed mechanism.
  Next: test with BusMaster always off but allow firmware to init normally otherwise.
- CRASH with CMD logged BusMaster=1 at some iter: DMA confirmed, iterate.
- CRASH with CMD always showing BusMaster=0: DMA definitively ruled out.
  Next: investigate MSI/interrupt mechanism or internal platform trigger.

**After a crash — what to do:**
1. Check journal: `journalctl -b -1 -k | grep "BCM4360 test.48" | tail -50`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.48.journal'`
3. Check: did CMD ever show BusMaster=1 (bit 2, 0x0004 in PCI_COMMAND)?
   - If CMD was ever non-zero bit2: BusMaster re-enabled by firmware → DMA mechanism confirmed
   - If CMD always 0x0002 (MemEN only): BusMaster stayed off → DMA ruled out
4. Check timing: at what iter did crash occur? 
   - If ~iter 95 (~950ms): same timing, BusMaster wasn't the determinant
   - If PASS (>500 iters, 5s): crash prevented! BusMaster suppression was the fix
5. git add logs + commit + push
6. Plan test.49 based on result

**Test history summary:**
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() once → 19 iters
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 100 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation
- test.47: CRASHED — normal firmware + LnkSta reads → 19 iters, LINK STABLE (no drop!)

**PCI_COMMAND bits (offset 0x04):**
- bit 0 (0x0001) = I/O Space Enable
- bit 1 (0x0002) = Memory Space Enable  
- bit 2 (0x0004) = Bus Master Enable ← this is what we're watching

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.48.stage0, test.48.journal (after crash)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.48 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
