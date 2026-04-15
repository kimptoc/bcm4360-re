# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.71)

Git branch: main (pushed to origin)

## test.70 RESULT: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path worked

**Key findings:**
- TIMEOUT path completed all 21 final reads without crashing
- sharedram_addr (0x9FFFC) = 0xffc70038 throughout all 30s — firmware NEVER writes it
- fw_init (0x9F0CC) = 0x870ca015 unchanged — olmsg protocol not used either
- TCM[0x9d000] = 0x000043b1 at T+2s (pciedngldev struct written)
- Console write ptr (0x9cc5c) = STAK → 0x8009ccbe at T+2s (console active)
- No IOMMU/DMA faults during entire test
- rambase=0x0, ramsize=0xa0000 confirmed (ramsize-4 = 0x9FFFC)
- EP_CMD=0x0006 throughout — BusMaster maintained

**Critical insight:** Firmware is alive and in its event loop after T+2s, but NEVER writes sharedram_addr. No IOMMU faults, no DMA errors. The deadlock is:
- Host waits for firmware to write sharedram_addr
- Firmware never writes it (unknown why — stuck in pcie_dngl_probe?)

## test.69 RESULT: CRASHED in TIMEOUT path at TCM[0x88000]

**Root cause:** msleep(1) before final scan loop was not enough — no settle time BETWEEN reads crashed at read 8.
- NVRAM token IS correctly at 0x9FFFC (0xffc70038) throughout
- Firmware alive in event loop but never writes sharedram_addr

## test.68 RESULT: SURVIVED 60s then CRASHED in TIMEOUT path

**Dense BSS scan results: firmware active region confirmed as 0x9cc00–0x9d000**
- Console ring buffer at 0x9cc00–0x9ce58
- Firmware banner: "RTE (PCIE-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz"
- Console write ptr at 0x9cc5c (and 0x9cc6c) = 0x8009ccbe → phys 0x9ccbe
- CRASH in TIMEOUT path: no settle time before final BAR2 reads → PCIe error

## test.71 PLAN (about to run)

**Key changes from test.70:**
1. Replace non-zero-only BSS scan with FULL console hex dump (every word 0x9cc00..0x9d100,
   4 words per line with ASCII sidebar) — decodes ring buffer structure completely
2. At T+5s (outer=25): send H2D mailbox signal:
   A) SBMBX doorbell via config space (0x98=1)
   B) H2D_MAILBOX_0=1 via PCIE2 BAR0 (safe at T+5s, past dangerous window)
3. Test number bumped to test.71 throughout

**Module build:** done (warning only: brcmf_pcie_write_ram32 unused)
**Test script:** updated to test.71 (log = test.71.stage0), waits 65s

**Hypotheses being tested:**
- H1: Console dump reveals firmware's last printed message → why pcie_dngl_probe stalled
- H2: H2D mailbox signal triggers firmware to write sharedram_addr (deadlock break)

**Expected outcomes:**
- SURVIVE (no crash) — per-read re-mask proven safe in test.70
- Console dump reveals ring buffer layout + firmware console text
- After H2D signal: maybe sharedram_addr changes (confirms host-ready deadlock)

**After test — what to do:**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.71" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.71.journal'`
3. `sudo chown kimptoc:users phase5/logs/test.71.*`
4. Decode console from "cons:" lines in journal
5. Check if sharedram changed after mailbox signal

## Run test.71 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE: 2000+ reads confirmed ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓

## Console structure (known from test.70 T+3s non-zero scan):
- Region 0x9cc00..0x9d000 = console + BSS runtime data
- 0x9cc00..0x9cc08 = zero (null ptr fields?)
- 0x9cc0c..0x9cc54 = STAK (BSS fill, not written by console)
- 0x9cc58 = 0x00303031
- 0x9cc5c = 0x8009ccbe (virtual write pointer — firmware console active)
- 0x9cc60 = 0x00000001
- 0x9cc64 = 0x0000000a
- 0x9cc68 = 0x0009ccc7 (possible ring buffer physical base)
- 0x9cc6c = 0x8009ccbe (write pointer again)
- 0x9cc70..0x9ccbc = binary/pointer data (linked list? timer queue?)
- 0x9ccc0..beyond = ASCII text from prior run (residual, ring wrapped)
- Write ptr phys = 0x9ccbe

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.71.stage0, test.71.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.67: SURVIVED 60s — TCM[0x9d000] changed at T+2s (0x000043b1); sharedram/fw_init unchanged
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded (firmware banner printed)
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient; per-read settle needed
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT; no IOMMU faults; firmware never writes sharedram
- test.71: DIAGNOSTIC — full console dump + H2D mailbox signal
