# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.78)

Git branch: main (pushed to origin)

## test.77 RESULT: SURVIVED

**test.77 confirmed:** Stale H2D mailbox theory is DEAD.
- H2D0=0xffffffff, H2D1=0xffffffff pre-ARM (stale from previous session) ✓ (logged)
- Cleared H2D0/H2D1/INTMASK/MBMASK to 0 before ARM release ✓
- Firmware STILL froze in pcie_dngl_probe at T+2s — identical pattern to test.75/76
- console_ptr updated at T+2s (0x5354414b → 0x8009ccbe), then silence for 30s
- sharedram[0x9FFFC] = 0xffc70038 throughout (firmware never wrote pcie_shared)
- TIMEOUT at T+30s — but POST-TIMEOUT SURVIVED! (select_core crash fixed)
- PCIe2 pre-ARM: INTMASK=0x0, MBINT=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff
- PCIe2 wrapper pre-ARM: IOCTL=0x1, RESET=0x0

**Stale H2D mailbox hypothesis is WRONG:** clearing all four BAC regs did not fix hang.

## test.78 HYPOTHESIS

The PCIe2 BAC has many more registers beyond INTMASK/MBMASK/H2D0/H2D1.
The DMA channel registers (offsets 0x100-0x1FF) may have stale state:
- Enable bits set (DMA_EN, bit 0) from previous session's initialized DMA channels
- Error or busy status from incomplete DMA transactions at watchdog reset

When firmware's hnddma_attach (in pcie_dngl_probe) tries to initialize these DMA
channels, it may hang waiting for them to go idle. Or the ARM may freeze on an
AXI bus transaction to a busy/hung DMA sub-block.

**This test is purely diagnostic** — dump all 128 BAC registers (0x000-0x1FF) and
examine the DMA channel state. No new writes until we see what needs clearing.

## test.78 PLAN (built, ready to run)

**Goal:** Full PCIe2 BAC register dump (0x000-0x1FF) to reveal DMA channel state.

**Key changes from test.77:**
1. ADD: full PCIe2 BAC dump — all 128 regs at offsets 0x000-0x1FF (4 per log line)
2. KEEP: named register reads (INTMASK/MBINT/MBMASK/H2D0/H2D1/IOCTL/RESET)
3. KEEP: H2D0/H2D1/INTMASK/MBMASK clears (confirmed safe from test.77)
4. NOT clearing DMA channel regs yet — need dump first

**Expected outcomes:**
- DMA registers non-zero → clear them in test.79, see if firmware advances
- DMA registers zero → DMA state is not the issue; need another hypothesis
- Post-timeout: should SURVIVE (fixed in test.77)

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.78 (log = test.78.stage0), waits 65s

## Run test.78 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.78" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.78.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.78.*'`
3. Extract PCIe2 BAC dump: `grep "pcie2reg:" phase5/logs/test.78.journal`
4. Check DMA channel registers at 0x100-0x1FF for non-zero values
5. Key DMA regs to check:
   - 0x100: DMA TX channel 0 control (bit 0 = DMA_EN)
   - 0x104: DMA TX channel 0 pointer
   - 0x108: DMA TX channel 0 rx-pointer/status
   - 0x200: DMA RX channel 0 (if present)
6. If DMA regs non-zero → test.79: clear DMA channels before ARM release
7. If DMA regs zero → need another hypothesis (see below)

## PCIe2 BAC DMA register layout (BCM4360, from hnddma):
- 0x000: Control
- 0x004: Interrupt Status
- 0x008: Interrupt Mask
- 0x00C: (reserved)
- 0x010..0x01F: more control
- 0x020..0x03F: more status/control
- 0x040: SBMBX / interrupt status
- 0x048: MAILBOXINT (interrupt from host)
- 0x04C: MAILBOXMASK
- 0x100: TX DMA0 Control (H2D ring 0)
- 0x104: TX DMA0 Ptr
- 0x108: TX DMA0 Addr Low
- 0x10C: TX DMA0 Addr High
- 0x110: TX DMA0 Status0
- 0x114: TX DMA0 Status1
- 0x118..0x11F: TX DMA0 extended
- 0x120: RX DMA0 Control (D2H ring 0)
- ...continuing to 0x1FF

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
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75/76/77)
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console structure (decoded from test.71/73 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe at T+2s)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Last messages: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console frozen (firmware in pcidongle_probe stall)

## BSS data decoded (from test.75/76/77 T+3s dump)
- 0x9d000 = 0x000043b1 (changed from 0 at T+2s = some firmware counter/timer, stops at T+2s)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4 = 0x55582631 (static firmware binary data, NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.78.stage0, test.78.journal (after test)
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
- test.78: PENDING — full PCIe2 BAC dump 0x000-0x1FF to diagnose DMA channel state
