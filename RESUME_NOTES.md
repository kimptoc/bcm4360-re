# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.74)

Git branch: main (pushed to origin)

## test.73 RESULT: SURVIVED — but firmware never wrote sharedram

**Key finding:**
- Machine survived! No crash. Fresh pre-SBMBX masking worked.
- SBMBX written at T+5s (config 0x98=1)
- Sharedram stayed at 0xffc70038 (baseline/nvram_token) throughout 30s wait
- Firmware DID run: console output at T+2s showed "wl_probe called", "pcie_dngl_probe called",
  RTE banner "RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
- After console output, firmware went silent — never wrote pcie_shared ptr
- TIMEOUT at T+28s, RP restored, returned -ENODEV

**Root cause:**
- SBMBX alone does NOT trigger firmware to write pcie_shared ptr
- Comparison with test.71 confirms: test.71 wrote BOTH SBMBX + H2D_MAILBOX_0, and FW READY
  was detected immediately (sharedram→0xffffffff at T+5010ms — likely a PCIe error read)
- H2D_MAILBOX_0 via BAR0 is the required "host-alive" signal for pcie_dngl_probe to proceed

**Implication:**
- Firmware waits for H2D_MAILBOX_0 before writing pcie_shared and completing init
- The sharedram=0xffffffff in test.71 was a PCIe read error (stale masking during read)
- test.71's crash was in the "second wait loop" (unmasked), not from H2D_MAILBOX_0 write itself

## test.74 PLAN (built, ready to run)

**Key changes from test.73:**
1. Restore H2D_MAILBOX_0 BAR0 write after SBMBX in outer==25 block
2. Triple fresh re-mask:
   - Before SBMBX (already in test.73)
   - Before H2D_MAILBOX_0 (brcmf_pcie_select_core is also a BAR0 write — mask before it)
   - After H2D_MAILBOX_0 (firmware responds with DMA to uninitialised host rings → PCIe errors)
3. Keep masking active through init_share_ram_info at t66_fw_ready
   - Moved RP restore to AFTER init_share_ram_info returns (not before it)
   - init_share_ram_info is all BAR2/TCM reads — works fine masked
   - Firmware may DMA immediately after writing pcie_shared (D2H doorbell)
4. Inner loop per-read masking already in place (from test.73)

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.74 (log = test.74.stage0), waits 65s

**Hypotheses being tested:**
- H1: Fresh masking before H2D_MAILBOX_0 prevents crash
- H2: H2D_MAILBOX_0 triggers firmware to write pcie_shared within 10ms (test.71 timing)
- H3: Post-H2D re-mask + inner loop masking → valid pcie_shared read (not 0xffffffff)
- H4: init_share_ram_info completes successfully with valid pcie_shared ptr
- H5: Keeping masking through init prevents crash from firmware D2H DMA errors

**Expected outcomes:**
- SURVIVE: triple fresh masking + post-write masking prevents crash
- T+5s: sharedram changes from 0xffc70038 to valid TCM address (0x9xxxx)
- FW READY detected, init_share_ram_info called
- Probe proceeds to DMA ring setup

**After test — what to do:**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.74" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.74.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.74.*'`
3. Check for "FW READY" message
4. Check sharedram value: was it a valid TCM address or 0xffffffff (PCIe error)?
5. If FW READY + valid: check if init_share_ram_info succeeded

## Run test.74 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX write triggers firmware response (within 10ms) ✓ (but firmware still needs H2D_MAILBOX_0)
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73 confirmed)
- H2D_MAILBOX_0 via BAR0 is required to wake pcie_dngl_probe ✓ (test.71+73 confirmed)
- BAR0 MMIO write to H2D_MAILBOX_0 causes crash with stale masking ✗ (test.71/72)
- Firmware prints console output: RTE banner + wl_probe + pcie_dngl_probe ✓

## Console structure (decoded from test.71/73 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Last messages: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console silent (firmware waiting for H2D_MAILBOX_0)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.74.stage0, test.74.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded (firmware banner printed)
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → sharedram=0xffffffff (PCIe read error); unmasked second wait loop
- test.72: CRASHED after SBMBX write — stale masking race; H2D_MAILBOX_0 BAR0 write removed in test.73
- test.73: SURVIVED — SBMBX only (fresh masking); firmware never wrote sharedram (SBMBX insufficient)
- test.74: PENDING — SBMBX + H2D_MAILBOX_0 with triple fresh masking; RP restore deferred past init
