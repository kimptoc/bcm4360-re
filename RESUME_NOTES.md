# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.76)

Git branch: main (pushed to origin)

## test.75 RESULT: SURVIVED

**test.75 confirmed:** Firmware runs to "pcie_dngl_probe called" at T+2s, then FREEZES.
- console_ptr changed at T+2s (0x5354414b → 0x8009ccbe = firmware wrote ring ptr)
- After T+2s: ZERO TCM changes in 28 seconds (T+2s..T+30s)
- sharedram[0x9FFFC] = 0xffc70038 (nvram_token) ALWAYS — firmware never wrote pcie_shared
- olmsg/trap region 0x9D0A0..0x9D100: IDENTICAL at baseline, T+5s, T+20s = static firmware binary data
- No trap magic found → firmware is in CPU BUS STALL, not exception

**Root cause identified:**

`brcmf_pcie_reset_device()` reads ASPM state (L0s+L1 = 0x3 from prior session),
disables for watchdog reset, then RESTORES ASPM (L0s+L1 enabled).
ARM is released with ASPM active → PCIe link enters L1 → pipe clock gated.
Firmware's `pcidongle_probe` → `hnd_pcie2_init` accesses PCIe2 LTSSM/pipe-clock
domain registers → CPU bus stall (no instruction executes, no memory writes).

**Why this doesn't happen on fresh boot:**
- Fresh boot: ASPM starts disabled (PCI standard default) → firmware works fine
- SBR: ASPM was enabled by prior session → reset_device restores it → hang

## test.76 PLAN (built, ready to run)

**Goal:** Disable ASPM on EP before ARM release to unblock pcidongle_probe.

**Key changes from test.75:**
1. Disable ASPM bits 0:1 in EP LINK_STATUS_CTRL (0xBC) just before ARM release
2. Log PCIe2 wrapper IOCTL/RESET_CTL before ARM (diagnostic)
3. Extended BSS dump at T+5s: 0x9D0A0..0x9D500 (was ..0x9D100)
4. Post-timeout: dump ARM exception vectors TCM[0x0..0x3F]
5. Post-timeout: PCIe2 wrapper state + EP ASPM verification

**Expected outcomes:**
- SURVIVE (ASPM is safe to disable before ARM)
- IF ASPM was the cause: firmware writes pcie_shared → sharedram changes → FW READY
- IF still hangs: look at extended BSS dump and exception vectors for next clue
- PCIe2 wrapper IOCTL should show CLK_EN=1 (confirming core accessible)

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.76 (log = test.76.stage0), waits 65s

## Run test.76 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.76" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.76.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.76.*'`
3. Check if sharedram changed (FW wrote pcie_shared) — grep for "FW READY" or "FW-ACK"
4. If FW READY: next step is implementing olmsg/FullDongle ring protocol
5. If still hangs: examine exception vectors + PCIe2 wrapper + extended BSS dump

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
- Firmware FREEZES in pcidongle_probe (CPU bus stall, no exception) ✓ (test.75)
- Root cause: ASPM L1 enabled → pipe clock gated → PCIe2 LTSSM register access hangs ✓
- ASPM disable (EP LINK_STATUS_CTRL bits 0:1) is safe before ARM release (test.76 to confirm)

## Console structure (decoded from test.71/73 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe at T+2s)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Last messages: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console frozen (firmware in pcidongle_probe CPU stall)

## BSS data decoded (from test.75 T+3s dump)
- 0x9d000 = 0x000043b1 (changed from 0 at T+2s = some firmware counter/timer)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID at 0x9d068
- 0x9d078 = 0x0009d0a0 (pointer to 0x9d0a0)
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4 = 0x575c2631 (static firmware binary data, NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.76.stage0, test.76.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → immediate crash
- test.72: CRASHED after SBMBX write — stale masking race
- test.73: SURVIVED — SBMBX only (fresh masking); firmware never wrote sharedram
- test.74: CRASHED — H2D_MAILBOX_0 BAR0 write (ring doorbell during init) → immediate crash
- test.75: SURVIVED — pure diagnostic; firmware freezes in pcidongle_probe (ASPM L1 root cause found)
- test.76: PENDING — ASPM disable before ARM release; should unblock pcidongle_probe
