# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.64)

Git branch: main (pushed to origin)

## test.63 RESULT: SURVIVED 20s — sharedram=0x00000000 throughout

**Machine did NOT crash. TIMEOUT message logged cleanly.**
- Survived 20s with 10ms inner-loop re-masking ✓
- But: sharedram=0x00000000 all 20 seconds — firmware NEVER wrote it

**Root cause A (BusMaster=0):**
- CMD=0x0402 at ARM release = Mem + DisINTx. BusMaster (bit 2) = 0.
- SBR (Secondary Bus Reset) at probe time clears PCI_COMMAND
- pci_enable_device() restores Mem but NOT BusMaster
- Without BusMaster: firmware PCIe2 DMA init fails every ~3s (the periodic events)
- Firmware is caught in a crash-restart loop, never reaches sharedram_addr write

**Root cause B (NVRAM token clobbered):**
- write_ram32(0) after NVRAM zeroed 0xffc70038 at ramsize-4
- 0xffc70038 is the NVRAM length/magic token firmware reads to locate NVRAM
- Without this token, firmware can't parse NVRAM → may fail to init PCIe2 interface

## test.64 PLAN (about to run)

**Two fixes:**
1. **pci_set_master()** before ARM release → firmware can DMA to host memory
2. **No write_ram32(0)** → NVRAM token (0xffc70038) preserved at ramsize-4
   - Firmware reads token, parses NVRAM, inits PCIe2, writes sharedram_addr
   - Detection: poll for value != 0xffc70038 (firmware overwrites it)

**Extra diagnostics:**
- Log EP CMD (endpoint PCI_COMMAND) every 200ms → confirms BusMaster stays set
- IOMMU group 8 protects against rogue DMA (confirmed active from test.39)

**Module build:** done (test.64 built successfully, warning only: write_ram32 unused)
**Test script:** updated to test.64 (log = test.64.stage0), waits 30s

**Expected outcomes:**
- If BusMaster fix works: firmware initializes PCIe2 DMA, writes sharedram_addr
  - We detect change from 0xffc70038 → actual sharedram_addr (e.g. 0x00200000-ish)
  - "FW READY" message logged, fall through to full brcmfmac init
  - WiFi device may appear: `ip link show` or `iw dev`
- If still crashes: check T+Xms when crash occurred (closer to T+0 now since DMA works?)
- If sharedram still 0xffc70038 after 20s: firmware still stuck; more diagnosis needed

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.64" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.64.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.64.*`
4. git add logs + commit + push
5. Analyze: look for "FW READY" vs TIMEOUT, check EP_CMD values

**After FW READY + survived:**
1. Check WiFi: `ip link show` or `iw dev`
2. Check brcmfmac loaded: `lsmod | grep brcm`
3. Test WiFi scanning if possible

**After a crash:**
1. Check T+Xms — if very early (T+0-500ms): BusMaster caused IOMMU DMA fault crash
2. Check if "FW READY" was logged before crash
3. Note EP_CMD values before crash (did BusMaster get cleared?)

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE: 2000+ reads confirmed ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- Survived 20 seconds without crash (test.63) ✓
- BusMaster must be enabled BEFORE ARM release (the missing piece)

## Test history summary
- test.42: PASS — BBPLL only (no ARM) → HAVEHT=YES confirmed
- test.43: CRASHED — BBPLL + ARM + pci_clear_master() once → 19 iters (950ms)
- test.44: CRASHED — B. injected PRE-activate (bug: activate() overwrote it)
- test.45: PASS — B. injected IN activate(), ARM spins safely, 500 iters
- test.46: CRASHED — normal firmware + PCIe error reads → 19 iters, NO error escalation
- test.47: CRASHED — normal firmware + LnkSta reads → 19 iters, LINK STABLE (no drop!)
- test.48: CRASHED — normal firmware + BusMaster reads + forced off → 49 iters, CMD=0x0002; DMA RULED OUT
- test.49: CRASHED — DisINTx=1 + BusMaster=0 throughout → 49 iters, CMD=0x0402; INTx+MSI RULED OUT
- test.50: INSTANT CRASH — WRITECC32(watchdog, 0) = immediate hardware reset; no messages logged
- test.51: INSTANT CRASH — select_core(CHIPCOMMON) in activate() = immediate hardware reset; no messages
- test.52: INSTANT CRASH — crash during chip enumeration BAR0 MMIO reads (device in bad state from 50/51)
- test.53: INSTANT CRASH at iter 1 — WRITECC32(watchdog, 0x7FFFFFFF) → crash after logging iter 1
- test.54: INSTANT CRASH at iter 1 — BAR2 read crashes; BAR0 reads all SAFE
  BAR0_WIN=0x18000000, CHIPID=0x15034360, WDOG=0, PMUWDOG=0 (all normal)
  Root cause: firmware PCIE2 DMA init makes BAR2 inaccessible within 10ms of ARM release
- test.55: CRASH after PRE iter=1 — BAR0 reads ALSO fatal during PCIE2 init window
  PRE phase had NO BAR2 reads; crash at iter=2 (~20ms) during BAR0 reads
  ALL PCIe accesses (BAR0 + BAR2) fail during PCIE2 init danger window
- test.56: CRASH at iter=2 (~2010ms) — bugs: loop_counter underflow + MMIO diagnostics on dead BAR0
  Survived 2s worth of polling. iter=1: BAR0_WIN=0x18000000 (config OK), CHIPID=0xffffffff (BAR0 MMIO dead)
  PCI_CMD/BAR address state unknown (test.57 was supposed to get these — crashed before)
- test.57: CRASH at iter=1 (~2010ms) — same CHIPID read, now fatal (timing variance)
  At the exact edge of PCIE2 init danger window. test.58: config-space only
- test.58: CRASH DURING 2s SLEEP — firmware crashes host with ZERO reads from our side
  Key finding: crash is firmware-driven at ~2000ms after ARM release, not caused by our reads
- test.59: CRASH at tick 24/25 (T+4800-5000ms) — survived 2s window! Second event at ~5s
  BC+DevCtl masking suppressed 2s crash; PCI_CMD=0x0402 throughout; aer_cap=0
- test.60: CRASH at tick 39/40 (T+7800-8000ms) — survived 5s window! Third event at ~8s
  BC/DC always 0x0000; per-tick re-masking suppressed 5s event; RootCtl=0x0000
- test.61: SURVIVED 20s! — status clearing + re-masking defeats all events
  DS=0x0010 (AuxPwr) always; SS/RS always 0; ext_cap0=0x20000000 (ECAM accessible)
- test.62: CRASHED at ~T+20s (two root causes found)
  sentinel=0xffc70038 (NVRAM last bytes); re-masking gap at T+20s (200ms window)
- test.63: SURVIVED 20s — sentinel=0 confirmed; FW never writes sharedram
  ROOT CAUSE FOUND: BusMaster=0 (SBR clears it, never re-enabled) + NVRAM token zeroed

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.64.stage0, test.64.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.64 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
