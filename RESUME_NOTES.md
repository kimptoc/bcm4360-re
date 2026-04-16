# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, EXECUTING test.83)

Git branch: main (pushed to origin)

## test.82 RESULT: SURVIVED 30s, then CRASHED in final TCM scan

**test.82 proved MSI theory DEAD. Machine survived the masking loop but
crashed during the oversized final TCM scan (50+ BAR2 reads).**

### test.82 key findings:
1. MSI_count=0 at EVERY 2s sample (T+2s through T+28s) → firmware NEVER fires MSIs
2. MSI_EN=1 confirmed (MSGCTL=0x0081), IRQ handler registered, no crash during 30s loop
3. sharedram=0xffc70038 unchanged — firmware still hangs in pcidongle_probe
4. TCM[0x9a000-0x9af00] zeroed by T+2s (firmware clearing BSS)
5. TCM[0x9d000] changed to 0x000043b1 (counter/timer stopped = firmware hung)
6. Console text identical to previous tests: pciedngl_probe called, then hung
7. CRASHED reading TCM[0x78000] during final scan (4th address in 50+ loop)

### test.82 cleanup:
- MSI code entirely removed (theory dead)
- Final TCM scan reduced to 3 reads: sharedram, console_ptr, fw_init_done

## test.83 PLAN (about to run)

**Goal:** Test whether firmware's pcidongle_probe is polling PCIe2 INTMASK/MBMASK
waiting for the host to signal interrupt readiness.

**Key changes from test.82:**
1. SET INTMASK=0x00FF0300 and MBMASK=0x00FF0300 pre-ARM (was cleared to 0)
   - Values from brcmf_pcie_intr_enable(): int_d2h_db (0xFF0000) | int_fn0 (0x0300)
   - Normal driver sets these AFTER sharedram, but PCI-CDC firmware may expect BEFORE
2. REMOVE: all MSI code (proven irrelevant by test.82)
3. FIX: final scan reduced from 50+ reads to 3 (sharedram, console_ptr, fw_init_done)
   - test.82 crashed at TCM[0x78000] during the oversized final scan

**Expected outcomes:**
- Machine SURVIVES (final scan fix)
- If sharedram changes: INTMASK/MBMASK was the missing piece → BREAKTHROUGH
- If firmware still hangs: INTMASK/MBMASK not what it's waiting for

**If INTMASK/MBMASK doesn't fix the hang, next hypotheses:**
- SB-to-PCIe translation window registers (firmware can't map host memory)
- DMA/IOMMU: firmware tries DMA during pcidongle_probe, IOMMU blocks it
  (test: intel_iommu=off kernel parameter)
- Force firmware trap: corrupt a data structure to trigger RTE trap handler

## Run test.83 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.83" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.83.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.83.*'`
3. Key things to check:
   a. Did we SURVIVE? (RP settings restored = yes)
   b. INTMASK/MBMASK readback — did the writes stick?
   c. Did sharedram change? → BREAKTHROUGH if so
   d. Console dump — different from previous tests?

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL → writing during init CRASHES ✗ (test.71/74)
- Firmware prints: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75-80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- 0x1E0 bits vary by boot (0x00070000 in test.79, 0x00030000 in test.80/81)
- TCM[0x9E000-0x9F000] = firmware binary, NOT stack ✗ (test.79)
- TCM[0x90000-0x9E000] has no dense stack cluster at 64-byte granularity ✗ (test.80)
- MSI enable without IRQ handler → CRASH in cleanup (RP restore while MSI active) ✗ (test.81)
- pci_enable_msi works (ret=0), device-side sees ADDR=0xfee00738 ✓ (test.81)
- MSI with IRQ handler: MSI_count=0 across 30s → firmware NEVER fires MSIs ✗ (test.82)
- MSI theory DEAD ✗ (test.82)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console text decoded (test.78/79/80/82 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (counter/timer, stops at T+2s = firmware hung)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.83.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → immediate crash
- test.72: CRASHED after SBMBX write — stale masking race
- test.73: SURVIVED — SBMBX only (fresh masking); firmware never wrote sharedram
- test.74: CRASHED — H2D_MAILBOX_0 BAR0 write (ring doorbell during init) → immediate crash
- test.75: SURVIVED — pure diagnostic; firmware freezes in pcidongle_probe (ASPM L1 theory)
- test.76: SURVIVED (crash in post-timeout cleanup) — ASPM disable did NOT fix hang; theory dead
- test.77: SURVIVED — H2D0/H2D1 stale 0xffffffff cleared to 0; still hangs; theory dead
- test.78: SURVIVED — full PCIe2 BAC dump; DMA theory wrong (0x120/0x124 = CONFIGADDR/CONFIGDATA)
- test.79: SURVIVED — cleared unknown regs 0x100-0x108/0x1E0; stack dump at 0x9E000 = wrong region
- test.80: SURVIVED — stack-finder scan found only 6 scattered hits; no stack cluster
- test.81: CRASHED — MSI enable without IRQ handler; crash in cleanup (RP restore while MSI active)
- test.82: SURVIVED 30s, CRASHED in final scan — MSI_count=0 across 30s; MSI theory DEAD
- test.83: PENDING — INTMASK/MBMASK set to 0x00FF0300 pre-ARM; minimal final scan; no MSI
