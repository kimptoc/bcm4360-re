# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.72)

Git branch: main (pushed to origin)

## test.71 RESULT: CRASHED after "FW READY" — but H2D_MAILBOX_0 worked!

**Key finding (breakthrough):**
- H2D_MAILBOX_0=1 at T+5s triggered sharedram → 0xffffffff within 10ms
- Firmware was WATCHING the mailbox register and responded immediately
- But: crash occurred after t66_fw_ready: restored RP → unmasked second wait loop
- 0xffffffff could be: (a) real firmware ACK or (b) PCIe bus error from BAR0 write

**Console messages decoded (from ring buffer dump):**
- "125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pcie_dngl_probe called"  
- "125888.000 \nRTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
- Console is a ring buffer (~0x200 bytes), write ptr at 0x9ccbe, ring start at 0x9ccc7

**Root cause of crash:** t66_fw_ready: restored RP then fell through to second wait
loop (lines 2418-2424) which does bare BAR2 reads without masking → crash.

## test.72 PLAN (about to run)

**Key changes from test.71:**
1. Validation reads when sharedram changes: read TCM[0x9d000], TCM[0x9D0A4], TCM[0x9cc5c]
   - If ALL 0xffffffff: PCIe bus error (BAR0 write disrupted device) — continue polling
   - If device-ok and sharedram is valid RAM addr: goto t66_fw_ready
   - If device-ok and sharedram = 0xffffffff (ACK): update baseline, send H2D_MAILBOX_1
2. H2D_MAILBOX_1 sent after seeing 0xffffffff ACK (HOSTRDY_DB1 protocol)
3. t66_fw_ready: bypass unmasked second wait loop by calling brcmf_pcie_init_share_ram_info
   directly and returning — fixes the crash

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.72 (log = test.72.stage0), waits 65s

**Hypotheses being tested:**
- H1: 0xffffffff was a real firmware ACK (validation reads will confirm)
- H2: After H2D_MAILBOX_1, firmware writes a valid pcie_shared address
- H3: Bypassing the second wait loop allows probe init to complete

**Expected outcomes:**
- SURVIVE (masking maintained throughout)
- Validation distinguishes PCIe error vs real firmware write
- If real: H2D_MAILBOX_1 triggers firmware to write valid sharedram address
- If valid address found: init_share_ram_info gets called successfully

**After test — what to do:**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.72" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.72.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.72.*'`
3. Check validation messages: "PCIe-ERR" vs "dev-ok"
4. Check if H2D_MAILBOX_1 triggered a second sharedram change
5. Check if init_share_ram_info was called and what it returned

## Run test.72 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- H2D_MAILBOX_0=1 triggers firmware response (sharedram→0xffffffff or PCIe error) ✓
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
- Logs: phase5/logs/test.72.stage0, test.72.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded (firmware banner printed)
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → sharedram=0xffffffff; second wait loop unmasked
- test.72: DIAGNOSTIC — validate 0xffffffff + H2D_MAILBOX_1 + direct init_share_ram_info
