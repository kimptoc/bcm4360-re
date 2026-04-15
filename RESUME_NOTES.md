# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.66)

Git branch: main (pushed to origin)

## test.65 RESULT: SURVIVED 20s — BusMaster fix confirmed, sharedram still stuck

**BusMaster fix confirmed: EP_CMD=0x0006 (Mem+BusMaster) throughout all 20s**
- TCM[0]=0xb80ef000 stable — ARM alive, no crash-restarts detected
- sharedram=0xffc70038 ENTIRE 20s — firmware never writes ramsize-4
- RP restored on timeout — no crash during cleanup (test.64 fix works)

**Root issue: firmware never signals ready via FullDongle protocol (ramsize-4)**
- Phase4 analysis: firmware is "PCI-CDC (FullMAC), NOT olmsg offload"
- BUT firmware reads board config from SROM/OTP (not TCM NVRAM)
- Two candidate protocols to test:
  A) FullDongle: firmware writes sharedram_addr to 0x9FFFC (ramsize-4)
  B) olmsg offload: firmware writes fw_init_done at 0x9F0CC (SHARED_INFO_OFFSET+0x2028)
- Previous test.65 only polled 0x9FFFC — missed if firmware uses protocol B

## test.64 RESULT (earlier): sharedram=0xffc70038 throughout — firmware never wrote it; crash at T+20s

**Machine SURVIVED 20s but crashed at TIMEOUT path. NVRAM token unchanged.**
- sharedram=0xffc70038 all 20 seconds — firmware never wrote sharedram_addr ✗
- EP_CMD=0x0402 the ENTIRE TIME — BusMaster=0 despite pci_set_master() call ✗
- Machine crashed between "ABOUT TO TIMEOUT" and "TIMEOUT" messages ✗

**Root cause: activate() CMD manipulation (leftover from test.49)**
- `brcmf_pcie_buscore_activate()` had leftover code from test.49 investigation
- It was doing: `cmd &= ~PCI_COMMAND_MASTER` (clears BusMaster!) right before ARM release
- pci_set_master() was called correctly, then activate() immediately undid it
- Without BusMaster, firmware PCIe2 DMA init fails → crash-restart loop every ~3s
- Firmware never reaches sharedram_addr write because it keeps crash-restarting

**Secondary root cause: no RP restoration on timeout path**
- `return -ENODEV` at T+20s left RP masking in a modified state
- Driver cleanup path then accessed device with firmware still generating errors
- This caused the crash between "ABOUT TO TIMEOUT" and "TIMEOUT" messages

## test.66 PLAN (about to run)

**Key diagnostics added:**
1. **60s wait** (300 outer × 200ms) — more time for slower firmware init
2. **TCM memory scan every 2s**: 20 strategic locations:
   - 0x9D0A4: olmsg shared_info magic_start
   - 0x9F0CC: olmsg fw_init_done (SHARED_INFO_OFFSET + 0x2028)
   - 0x9FFFC: FullDongle sharedram pointer (ramsize-4)
   - 0x6C000..0x9C000: firmware heap/stack activity detection
3. **PCIe2 mailbox reads every 10s**: detect if firmware tries to signal host via interrupt
4. **Poll fw_init_done in inner loop**: catches olmsg protocol alongside FullDongle

**Module build:** done (test.66 built successfully, warning only: write_ram32 unused)
**Test script:** updated to test.66 (log = test.66.stage0), waits 75s

**Expected outcomes:**
- If FullDongle: ramsize-4 (0x9FFFC) changes from 0xffc70038 → sharedram_addr
  → "FW READY (FullDongle)" logged, full brcmfmac init proceeds
- If olmsg: fw_init_done (0x9F0CC) becomes non-zero
  → "FW_INIT_DONE" logged, need to implement olmsg protocol
- If TCM changes in 0x6C000-0x9C000 region: firmware IS running but using different address
- If PCIe2 MAILBOXINT changes: firmware tried to signal host via mailbox interrupt
- If nothing changes for 60s: fundamental initialization issue (SROM/OTP? different protocol?)

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.66" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.66.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.66.*`
4. git add logs + commit + push
5. Analyze: check for TCM changes (what did firmware write?), fw_init_done, PCIe2 mailbox

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE: 2000+ reads confirmed ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- Survived 20 seconds without crash (test.63) ✓
- BusMaster must be enabled BEFORE ARM release (the missing piece) ✓
- activate() from test.49 was clearing BusMaster — now fixed in test.65 ✓

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
- test.64: SURVIVED 20s then CRASHED at timeout — sharedram=0xffc70038 throughout
  BusMaster=0 entire time (activate() leftover from test.49 was clearing it)
  CRASH at T+20s: RP masking not restored before return -ENODEV → cleanup crash
- test.65: SURVIVED 20s — BusMaster fix confirmed (CMD=0x0006), sharedram still stuck
- test.66: DIAGNOSTIC — 60s wait + TCM scan (20 locations) + PCIe2 mailbox + fw_init_done poll

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.66.stage0, test.66.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.66 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
