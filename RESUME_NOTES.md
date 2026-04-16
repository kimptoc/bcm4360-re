# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, RUNNING test.88)

Git branch: main (pushed to origin)
Module built successfully. About to run test.88.
Test dumps call targets 0x67358, 0x64248, 0x63C24 + stack scan 0x9F000-0x9FFF8.
3s max loop with re-masking every 10ms.

## test.87 RESULT: SURVIVED — counter timing + code dumps obtained

**test.87 survived 3s cleanly. Key findings:**
1. Counter froze between T+200ms and T+400ms (value 0x43b1) — firmware hangs within 400ms
2. pciedngl_probe disassembled: linear function making calls to 0x67358, 0x64248, 0x63C24
3. No polling loops in pciedngl_probe itself — hang is inside a called function
4. TCB at 0x9d080 = 0x000A0000 (top of 640KB TCM)
5. Code at 0x2100-0x24FF disassembled — downstream callees, no obvious polling loops either
6. Init spin at 0x168 confirmed: `beq #0x168` (spin while *0x224 == NULL)
7. WFI at 0x1C1E confirmed in disassembly (idle helper function)

### test.88 PLAN: Dump call targets + stack area to find hang location

**Goal:** Identify EXACTLY which function the firmware is stuck in by:
1. Dumping code at the three call targets from pciedngl_probe:
   - 0x67340-0x67500 (target 0x67358: register_bus/attach call with many args)
   - 0x64200-0x64400 (target 0x64248: result-checked call)
   - 0x63C00-0x63D00 (target 0x63C24: conditional second call)
2. Scanning stack area 0x9F000-0x9FFF8 for Thumb return addresses
3. Looking for LDR+CMP+BNE polling loops, WFI, or CPSID in the call targets

**Approach:** Same as test.87 — 3s max, re-mask every 10ms, dump at T+1s, no core switch.

## test.86 RESULT: CRASHED at T+2s (ARM core switch)

**test.86 crashed immediately when select_core(ARM_CR4) was called at T+2s.**
**Core switching after firmware starts is CONFIRMED LETHAL (tests 66/76/86).**
**WFI theory DISPROVEN: frozen counter at 0x9d000 means TRUE HANG, not WFI idle.**
(WFI only halts CPU core — timers/peripherals keep running. Counter froze = real hang.)

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

### test.87 PLAN: TCM firmware code dump + counter timing (NO core switch)

**Goal:** Find what pciedngl_probe is polling/waiting for by:
1. Tracking exact counter freeze timing (when does the hang happen?)
2. Dumping firmware code around pciedngl_probe for deeper disassembly
3. Finding the stack pointer in TCM to trace the call chain

**Approach:**
1. Keep all pre-ARM setup from test.85 (BBPLL, BusMaster, ASPM, config clearing)
2. Release ARM, start 3s monitoring loop (15 outer × 200ms)
3. Every 200ms: read TCM counter at 0x9d000, log RUNNING/FROZEN
4. At outer==5 (T+1s): dump firmware code + TCB via BAR2 (safe reads):
   - pciedngl_probe code: 0x1E90-0x20FF (~0x170 bytes)
   - Init spin loop: 0x0160-0x022F
   - WFI idle helper: 0x1C00-0x1C3F
   - Thread control block / si_t: 0x9d020-0x9d0FF
   - Extended callees: 0x2100-0x24FF
5. Exit at T+3s max — crash scales ~90-100% of loop length
6. Restore RP cleanly
7. NO core switching (lethal per tests 66/76/86)

## Run test.88 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.88" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.88.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.88.*'`
3. Key things to check:
   a. Did we SURVIVE? (RP settings restored = yes)
   b. Code at 0x67358: look for LDR+CMP+BNE polling loops or CPSID
   c. Code at 0x64248: same — polling loops or infinite waits
   d. Code at 0x63C24: same
   e. Stack scan: Thumb return addresses (0x0001xxxx-0x0006Fxxx, bit 0 set) reveal call chain

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
- select_core after firmware starts → CRASH ✗ (test.66/76 PCIe2, test.86 ARM CR4)
- Core switching after FW start CONFIRMED LETHAL across ALL core types ✗ (test.66/76/86)
- WFI theory DEAD: frozen counter = TRUE HANG, not WFI idle (WFI keeps timers running) ✗
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓
- Counter freezes at 0x43b1 between T+200ms and T+400ms — hang is VERY early ✓ (test.87)
- TCM top = 0xA0000 (640KB), stack grows down from there ✓ (test.87 TCB)
- pciedngl_probe calls into 0x67358, 0x64248, 0x63C24 — hang is inside one of these ✓ (test.87 disasm)

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
- test.86: CRASHED T+2s — ARM core switch (select_core) crashed immediately; core switch LETHAL
- test.87: SURVIVED — counter froze T+200-400ms at 0x43b1; pciedngl_probe disassembled; code dumps obtained
- test.88: PENDING — dump call targets (0x67358, 0x64248, 0x63C24) + stack scan; find exact hang location
