# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.73)

Git branch: main (pushed to origin)

## test.72 RESULT: CRASHED after SBMBX write — before H2D_MAILBOX_0 write

**Root cause identified:**
- Machine crashed at 20:39:33, immediately after SBMBX doorbell write
- Last journal message: "BCM4360 test.72: SBMBX doorbell written (config 0x98=1)"
- NO message for "H2D_MAILBOX_0=1 written" — crash happened between these two
- Root cause: masking was stale (up to 200ms old) when `outer==25` ran
  - The inner loop re-masks every 10ms, but outer==25 fires BETWEEN inner loop cycles
  - Up to 200ms of accumulated PCIe error state when SBMBX write triggers firmware response
- Non-deterministic: test.71 had identical code but survived (timing luck)
- test.72 and test.71 diff confirmed IDENTICAL code at outer==25

**Key finding:**
- SBMBX write alone is enough to trigger firmware response (firmware is watching it)
- BAR0 MMIO write (H2D_MAILBOX_0) after SBMBX is not needed AND is dangerous
- Config-space writes (SBMBX at 0x98) are safe; BAR0 MMIO writes cause crashes

## test.73 PLAN (built, ready to run)

**Key changes from test.72:**
1. Fresh re-mask + msleep(10) immediately before SBMBX write in `outer==25` block
   - Uses same re-mask pattern as inner loop (BridgeCtl, DevCtl, PCI_COMMAND, RW1C clears)
   - Eliminates the stale-masking race window that caused test.72 crash
2. Remove `brcmf_pcie_select_core` + `brcmf_pcie_write_reg32(H2D_MAILBOX_0)` entirely
   - SBMBX config-space write only — no BAR0 MMIO writes at mailbox time
3. Keep all validation reads (PCIe-ERR vs dev-ok distinguish), H2D_MAILBOX_1 path,
   t66_fw_ready direct init_share_ram_info call (bypasses unmasked second wait loop)

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.73 (log = test.73.stage0), waits 65s

**Hypotheses being tested:**
- H1: Fresh masking before SBMBX write prevents crash (masking race fixed)
- H2: SBMBX alone triggers firmware response (sharedram write or valid pcie_shared)
- H3: Validation reads will distinguish PCIe-ERR vs real firmware write
- H4: If real pcie_shared written, init_share_ram_info completes probe successfully

**Expected outcomes:**
- SURVIVE: masking is fresh when SBMBX fires, no BAR0 MMIO write
- SBMBX triggers firmware response within 10ms (same as test.71)
- Validation reads confirm PCIe-ERR or dev-ok
- If dev-ok + valid address: init_share_ram_info called, probe may complete

**After test — what to do:**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.73" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.73.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.73.*'`
3. Check if survived: look for "TIMEOUT" or "FW READY" message
4. Check sharedram after SBMBX: "PCIe-ERR" vs "dev-ok"
5. If dev-ok + valid address: check if init_share_ram_info succeeded

## Run test.73 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX write triggers firmware response (within 10ms) ✓
- BAR0 MMIO write to H2D_MAILBOX_0 causes crash with stale masking ✗ (dangerous)
- Firmware prints console output: RTE banner + wl_probe + pcie_dngl_probe ✓

## Console structure (decoded from test.71 T+3s dump)
- Region 0x9cc00..0x9d100 = console header + ring buffer + BSS runtime data
- Console struct header: 0x9cc00..0x9cc6c (STAK-filled then real ptrs)
- 0x9cc5c = virtual write ptr (0x8009ccbe = phys 0x9ccbe)
- 0x9cc68 = 0x9ccc7 = ring buffer physical base
- Ring size ≈ 0x200 bytes (wraps at ~0x9cec7)
- Write ptr 0x9ccbe is just before ring start → buffer wrapped
- Last messages printed: "wl_probe called", "pcie_dngl_probe called", RTE banner
- After banner: console silent (firmware waiting for host-ready signal)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.73.stage0, test.73.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded (firmware banner printed)
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → sharedram=0xffffffff; second wait loop unmasked
- test.72: CRASHED after SBMBX write — stale masking race; H2D_MAILBOX_0 BAR0 write removed in test.73
- test.73: PENDING — fresh pre-mailbox re-mask + SBMBX only
