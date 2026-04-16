# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, EXECUTING test.85)

Git branch: main (pushed to origin)

## test.84 RESULT: CRASHED at ~T+30s (between T+28s and timeout message)

**test.84 proved BAR hypothesis DEAD — device-side BARs are valid after SBR.**

### test.84 key findings:
1. Device-side config dump: CMD_STA=0x08100006 BAR0=0xb0600004 BAR1=0x00000000 BAR2=0xb0400004
2. BAR2_CONFIG(0x4E0)=0x00000016 BAR3_CONFIG(0x4F4)=0x00000000
3. **STATUS bit 11 (Signaled Target Abort) is SET** — residual error from SBR
4. BARs are valid (non-zero, proper addresses) — BAR-zero hypothesis DEAD
5. Firmware still freezes: sharedram=0xffc70038 unchanged across 28s
6. Machine crashed at ~T+30s (same as test.82/83 — crash at loop end)
7. Console text unchanged from previous tests (pciedngl_probe called, firmware hung)

### test.84 cleanup applied to test.85:
- BAR hypothesis DEAD — BARs valid
- NEW THEORY: STATUS error bits (bit 11 = Signaled Target Abort) may cause firmware to spin
- Clear STATUS RW1C error bits via CONFIGADDR/CONFIGDATA before ARM release
- Walk device-side capability list and dump PCIe Express cap registers (DevSta, LnkSta)
- Clear DevSta RW1C error bits too
- Reduce loop from 30s to 20s to avoid the T+30s crash

## test.85 PLAN (about to run)

**Goal:** Clear device-side STATUS/DevSta error bits and dump full PCIe caps before ARM release.
Hypothesis: After SBR, STATUS bit 11 (Signaled Target Abort) is set. Firmware reads its own
config STATUS in pcidongle_probe, sees the error, and spins/aborts PCIe init.

**Evidence:** test.84 CMD_STA=0x08100006 has STATUS=0x0810, bit 11 (Signaled Target Abort) SET.
brcmf_pcie_reset_device() saves/restores config regs after watchdog reset, but doesn't clear
STATUS error bits — our SBR path does even less.

**Key changes from test.84:**
1. ADD: Clear STATUS RW1C error bits (write 0xFFFF0000 | CMD to offset 0x04) before ARM release
2. ADD: Walk device-side capability list, dump PCIe Express cap registers (DevCtl+Sta, LnkCtl+Sta)
3. ADD: Clear DevSta RW1C error bits if any set
4. ADD: Read PM_CSR (offset 0x4C) for power management state
5. FIX: Reduce loop from 150 (30s) to 100 (20s) — firmware dead by T+2s, avoids T+30s crash
6. FIX: Remove T+20s diagnostic (unreachable with 20s loop)
7. KEEP: Everything from test.84 (config dump, INTMASK/MBMASK, no BAR2 in timeout)

**Expected outcomes:**
- Machine SURVIVES (20s loop avoids the T+30s crash)
- STATUS cleared successfully (readback shows bit 11 gone)
- PCIe cap dump shows additional context (link state, device status)
- If firmware STILL hangs: STATUS clearing alone doesn't fix it → need to look at
  SBTOPCIE translation or get ARM PC via debug registers
- If firmware PROCEEDS: STATUS clearing is the fix → BREAKTHROUGH

**If firmware still hangs, next hypotheses (in priority order):**
1. Get ARM PC via debug registers (halt CPU, read PC to find exact spin location)
2. Force firmware trap to dump CPU state
3. SBTOPCIE translation window setup (firmware may fail to write these)
4. Disassemble firmware binary near "pciedngl_probe" to find spin loop
5. Try intel_iommu=off kernel parameter

## Run test.85 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.85" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.85.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.85.*'`
3. Key things to check:
   a. Did we SURVIVE? (RP settings restored = yes)
   b. STATUS cleared? (before=0x08100006 → after should have bit 11 gone)
   c. PCIe cap dump — any additional error bits in DevSta/LnkSta?
   d. Did sharedram change? → BREAKTHROUGH if so
   e. Console dump — any different from test.84?

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
- INTMASK/MBMASK: wrote 0x00FF0300, readback 0x00000300 (0xFF0000 rejected, PCIe2 rev=1) ✗ (test.83)
- INTMASK/MBMASK theory DEAD ✗ (test.83)
- ALL BAR2 reads in timeout path crash (test.82 + test.83 both crashed at "minimal" scan)
- Device-side BARs valid after SBR: BAR0=0xb0600004 BAR1=0 BAR2=0xb0400004 ✓ (test.84)
- Device-side STATUS has Signaled Target Abort (bit 11) SET after SBR ✓ (test.84)
- BAR hypothesis DEAD (BARs valid) ✗ (test.84)
- Loop crashes at ~T+30s consistently (test.82/83/84 all crashed between T+28s and timeout)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console text decoded (test.78/79/80/82/83/84 T+3s)
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
- Logs: phase5/logs/test.85.journal (after test)
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
- test.83: CRASHED in timeout path — INTMASK/MBMASK theory DEAD; even 3-read final scan crashes
- test.84: CRASHED at ~T+30s — BARs valid, STATUS bit 11 SET; BAR hypothesis DEAD
- test.85: PENDING — clear STATUS/DevSta error bits; walk PCIe caps; 20s loop
