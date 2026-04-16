# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, EXECUTING test.86)

Git branch: main (pushed to origin)

## test.85 RESULT: CRASHED at ~T+18-20s

**test.85 proved STATUS/DevSta clearing theory DEAD — firmware still hangs.**
**CRITICAL: Crash timing scales with loop length (20s loop → crash at ~T+18-20s).**

### test.85 key findings:
1. STATUS cleared successfully: 0x08100006 → 0x00100006 (bit 11 gone) — firmware STILL hangs
2. DevSta cleared: 0x00132c10 → 0x00102c10 — firmware STILL hangs
3. PCIe caps: 0x48(PM id=1), 0x58(MSI id=5), 0x68(VPD id=9), 0xAC(PCIe Express id=0x10)
4. PCIe Express: DevCtl+Sta=0x00132c10 LnkCtl+Sta=0x10110140
5. PM_CSR(0x4C)=0x00004008
6. sharedram=0xffc70038 unchanged for 18s — firmware completely dead
7. TCM[0x9d000] counter went 0→0x43b1 then frozen (same as all tests)
8. TCM[0x9a000-0x9af00] zeroed (firmware BSS init area)
9. CRASHED between T+18s and T+20s (no RP restore messages)
10. STATUS/DevSta clearing theory DEAD

### Firmware disassembly findings (from this session):
- NO spin loops in firmware code except exception handler init at 0x168
- WFI instruction at 0x1C1E (idle helper: WFI; BX LR)
- pciedngl_probe at 0x1E90 — traced full call chain
- Firmware protocol = PCI-CDC (confirmed by RTE banner)
- 0x168 spin loop: loads function pointer from *0x224, spins while NULL, calls through it
  (this is the startup spin — waits for c_init to set up the entry point)
- After init, firmware enters WFI-based idle loop (normal behavior)
- The "hang" is likely: firmware completed init normally, sitting in WFI,
  waiting for host commands via PCI-CDC protocol that our MSGBUF driver never sends

### test.86 PLAN: Read ARM PC via debug registers

**Goal:** Confirm firmware's exact execution location to distinguish:
- PC ≈ 0x1C1E → firmware in WFI idle (protocol mismatch confirmed, firmware is HEALTHY)
- PC = 0x168 → stuck in init spin (function pointer never set)
- PC elsewhere → real hang at identifiable location

**Approach:**
1. Keep all pre-ARM setup from test.85 (BBPLL, BusMaster, ASPM, config clearing)
2. Release ARM, wait 3s for firmware to complete init
3. Select ARM CR4 core (BCMA_CORE_ARM_CR4 = 0x83E)
4. Read ARM debug registers to get PC
5. Quick TCM state check
6. Exit at T+5s MAX to avoid PCH crash (crash scales with loop length)
7. Restore RP cleanly

**Implementation details:**
1. Keep all pre-ARM setup from test.85 (BBPLL, BusMaster, ASPM, STATUS/DevSta clearing)
2. Release ARM, start 3s monitoring loop (15 outer × 200ms)
3. At outer==10 (T+2s):
   - Read TCM counter (0x9d000) before switching cores
   - Select ARM CR4 core, read wrapper IOCTL+RESET_CTL
   - Halt CPU by setting CPUHALT (0x0020) in wrapper IOCTL
   - Dump ARM core registers 0x00-0xFF (64 words)
   - Dump ARM wrapper registers 0x1400-0x14FF
   - Switch back to ChipCommon, re-read TCM counter after halt
4. Exit at T+3s max — crash scales ~90-100% of loop length
5. Restore RP cleanly

**If ARM dump doesn't reveal PC, next step:**
- test.87: Write to SBTOPCIMAILBOX (0x48 in PCIe2 core) to trigger mailbox interrupt
  PCI-CDC firmware should respond if IRQs are enabled

## Run test.86 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.86" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.86.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.86.*'`
3. Key things to check:
   a. Did we SURVIVE? (RP settings restored = yes)
   b. ARM wrapper IOCTL — was CPUHALT already set?
   c. ARM core registers — any recognizable debug register values?
   d. TCM counter frozen or was-running?
   e. Did halting the CPU change anything?

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
- STATUS clearing (bit 11 Signaled Target Abort) does NOT fix firmware hang ✗ (test.85)
- DevSta clearing does NOT fix firmware hang ✗ (test.85)
- STATUS clearing theory DEAD ✗ (test.85)
- Crash timing scales with loop length: 30s→T+28-30s, 20s→T+18-20s (test.82-85)
- PCIe caps: PM@0x48, MSI@0x58, VPD@0x68, PCIe_Express@0xAC ✓ (test.85)
- Firmware has NO spin loops except init handler at 0x168 ✓ (disassembly)
- WFI instruction at 0x1C1E (idle helper) ✓ (disassembly)
- pciedngl_probe at 0x1E90, full call chain traced ✓ (disassembly)
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
- test.85: CRASHED T+18-20s — STATUS/DevSta cleared, firmware STILL hung; STATUS theory DEAD
- test.86: PENDING — read ARM PC via debug registers; 5s max loop
