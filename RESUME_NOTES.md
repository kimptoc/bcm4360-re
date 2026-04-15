# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.77)

Git branch: main (pushed to origin)

## test.76 RESULT: SURVIVED (but crashed in post-timeout cleanup)

**test.76 confirmed:** ASPM theory is DEAD.
- ASPM disabled on EP before ARM release (was 0x3, cleared to 0x0) ✓
- Firmware STILL froze at T+2s, same as test.75
- console_ptr updated at T+2s (0x5354414b → 0x8009ccbe), then silence for 30s
- sharedram[0x9FFFC] = 0xffc70038 throughout (firmware never wrote pcie_shared)
- TIMEOUT at T+30s
- Post-timeout crash: `brcmf_pcie_select_core(BCMA_CORE_PCIE2)` crashed machine
  (known dangerous after firmware starts — same as test.66)
  Only 1 exc line logged before crash (4 words at 0x0000)
- PCIe2 wrapper pre-ARM: IOCTL=0x00000001 RESET_CTL=0x00000000

**ASPM hypothesis is WRONG:** disabling ASPM on EP did not fix pcidongle_probe hang.

## test.77 HYPOTHESIS

Stale PCIe2 BAC registers from prior firmware session may persist through
the watchdog reset (or be set to unexpected values by brcmf_pcie_buscore_setup).
The firmware's hnd_pcie2_init reads INTMASK/MAILBOXMASK/H2D_MAILBOX_0/1
and gets confused by non-zero stale values → tight polling loop or wrong state.

Fix: read and log all key PCIe2 BAC registers pre-ARM; clear INTMASK,
MAILBOXMASK, H2D_MAILBOX_0, H2D_MAILBOX_1 to 0 before ARM release.

Also fixed in test.77:
- Post-timeout crash: removed `brcmf_pcie_select_core(BCMA_CORE_PCIE2)` from
  TIMEOUT path (was crashing machine)
- Exception vector reads now have per-read masking
- Updated all log messages from test.76 → test.77

## test.77 PLAN (built, ready to run)

**Goal:** Clear stale PCIe2 BAC registers before ARM release; see if firmware
advances past pcidongle_probe hang.

**Key changes from test.76:**
1. Read PCIe2: INTMASK(0x24), MBINT(0x48), MBMASK(0x4C), H2D0(0x140), H2D1(0x144)
2. Clear INTMASK, MBMASK, H2D_MAILBOX_0, H2D_MAILBOX_1 to 0 before ARM
3. Fixed post-timeout: remove select_core(PCIE2), add masking to TCM[0..3F] reads
4. ASPM disable kept (harmless)

**Expected outcomes:**
- IF stale BAC regs were the cause: firmware writes pcie_shared → FW READY
- IF still hangs: log the PCIe2 register values to inform next theory
- Post-timeout should now SURVIVE (no more select_core crash)

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.77 (log = test.77.stage0), waits 65s

## Run test.77 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.77" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.77.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.77.*'`
3. Check PCIe2 BAC register values: grep for "PCIe2 pre-ARM"
4. Check if sharedram changed (FW wrote pcie_shared) — grep for "FW READY" or "FW-ACK"
5. If FW READY: next step is implementing olmsg/FullDongle ring protocol
6. If still hangs: examine PCIe2 register values + next theory

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
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75/76)
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC regs pre-ARM: INTMASK/MBMASK/H2D0/H2D1 values TBD (test.77 will reveal)

## Console structure (decoded from test.71/73 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe at T+2s)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Last messages: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console frozen (firmware in pcidongle_probe stall)

## BSS data decoded (from test.75/76 T+3s dump)
- 0x9d000 = 0x000043b1 (changed from 0 at T+2s = some firmware counter/timer)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4 = 0x575c2631 (static firmware binary data, NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.77.stage0, test.77.journal (after test)
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
- test.77: PENDING — PCIe2 BAC reg clear before ARM; post-timeout crash fixed
