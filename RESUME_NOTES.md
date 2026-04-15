# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.75)

Git branch: main (pushed to origin)

## test.74 RESULT: CRASHED

**Crash point:** Machine died immediately after `brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0, 1)`
Last log line: `BCM4360 test.74: H2D_MAILBOX_0=1 written via PCIE2 BAR0`
Nothing logged after — machine rebooted.

**Root cause:**
- H2D_MAILBOX_0 (BAR0 offset 0x140) is the **ring doorbell** (D2H/H2D DMA notification), NOT the init mailbox
- Writing it during firmware init (before rings are allocated) causes firmware to attempt DMA to uninitialized ring buffer addresses
- IOMMU rejects the DMA → fatal PCIe error → machine crash
- Value 1 = D3_INFORM (host entering D3) — completely wrong meaning for initialization
- Triple fresh masking was irrelevant: crash occurred too fast (microseconds) for masking to help

**Key updated understanding:**
- BAR0 H2D_MAILBOX_0 is the ring doorbell. NEVER write it during init.
- The correct init mailbox is `brcmf_pcie_send_mb_data()`: writes data to TCM[htod_mb_data_addr] then rings SBMBX
- But htod_mb_data_addr is only known AFTER reading pcie_shared — chicken-and-egg
- Firmware never writes pcie_shared despite running to "pcie_dngl_probe called"
- SBMBX alone (test.73) doesn't trigger pcie_shared write either

## test.75 PLAN (built, ready to run)

**Goal:** Pure diagnostic — determine if firmware is alive or dead after T+2s (last known console activity)

**Key changes from test.74:**
1. Remove H2D_MAILBOX_0 BAR0 write entirely — it crashes every time
2. Remove SBMBX write — need cleaner diagnostic baseline
3. At T+5s (outer==25): read console_ptr (0x9cc5c) + dump 0x9D0A0..0x9D100
4. At T+20s (outer==100): second read/dump — compare to T+5s
5. Everything else unchanged (masking, inner loop, TCM scan every 2s)

**Questions test.75 will answer:**
- Q1: Does console_ptr change between T+2s and T+5s? (firmware alive?)
- Q2: Does console_ptr change between T+5s and T+20s? (firmware still alive at T+20s?)
- Q3: What is at 0x9D0A0..0x9D100? (olmsg magic, trap data, or zeros?)
- Q4: Does 0x9D0A0..0x9D100 change between T+5s and T+20s?

**Expected outcomes:**
- SURVIVE: no BAR0 MMIO writes → no DMA crash trigger
- If console_ptr static from T+2s: firmware dead/hung at pcie_dngl_probe
- If console_ptr changes: firmware alive but waiting for something
- If 0x9D0A0..0x9D100 shows trap magic (e.g. 0xDEADBEEF/firmware-specific): firmware crashed with exception
- If olmsg magic 0x555c0631 at 0x9D0A4: olmsg protocol active, look for fw_init_done

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.75 (log = test.75.stage0), waits 65s

## Run test.75 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.75" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.75.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.75.*'`
3. Compare console_ptr at baseline, T+5s, T+20s — is firmware alive?
4. Decode 0x9D0A0..0x9D100 dump — look for olmsg magic, trap data, or pcie_shared variants
5. Check if 0x9D0A0..0x9D100 changed between T+5s and T+20s

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73 confirmed)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL (not init mailbox) — writing it during init CRASHES ✗ (test.71/74)
- Firmware prints console output: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware never writes pcie_shared despite running to pcie_dngl_probe ✓ (all tests)

## Console structure (decoded from test.71/73 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Last messages: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console silent (firmware waiting for something)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.75.stage0, test.75.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded (firmware banner printed)
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → sharedram=0xffffffff (PCIe read error); unmasked second wait loop
- test.72: CRASHED after SBMBX write — stale masking race; H2D_MAILBOX_0 BAR0 write removed in test.73
- test.73: SURVIVED — SBMBX only (fresh masking); firmware never wrote sharedram (SBMBX insufficient)
- test.74: CRASHED — H2D_MAILBOX_0 BAR0 write (ring doorbell during init) → immediate crash
- test.75: PENDING — pure diagnostic: olmsg/trap dump at T+5s+T+20s; NO BAR0 writes
