# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.63)

Git branch: main (pushed to origin)

## test.62 RESULT: CRASHED at ~T+20s — two root causes identified

**Survived T+0..T+19s (2000+ BAR2 reads), then crashed**
- Crash is the 7th ~3s periodic firmware event hitting a re-masking gap at T+20s
- Firmware NEVER wrote sharedram_addr throughout 20s

**Root cause 1 (sentinel bug):** write_ram32(0) was at line 1808 BEFORE the NVRAM copy at line 1816.
- NVRAM (228 bytes) written at offset 0x9ff1c covers 0x9ff1c..0x9ffff, including 0x9fffc (ramsize-4)
- Last 4 bytes of NVRAM blob = 0xffc70038, which OVERWROTE our zero
- So sharedram_addr_written = 0xffc70038 (not 0)
- Firmware checks ramsize-4 == 0 before writing sharedram_addr; sees 0xffc70038 → skips write
- Detection loop compared against 0xffc70038 → never detects firmware's actual write

**Root cause 2 (re-masking gap):** Masking was only per outer tick (every 200ms).
- The 7th periodic event at ~T+20s hit a gap between outer=95 (T+19s mask) and outer=96 (T+19.2s mask)
- Machine crashed before TIMEOUT message was logged

**Key confirmed findings from test.62:**
- BAR2 reads (brcmf_pcie_read_ram32 via TCM) are SAFE: 2000+ reads, no crash during loop
- 0xffc70038 = last 4 bytes of NVRAM blob (not a firmware-written sharedram address)
- 6 periodic PCIE2 events at T+2,5,8,11,14,17s all suppressed successfully

## test.63 PLAN (about to run)

**Two fixes + full probe:**
1. **Sentinel fix**: write_ram32(0) moved to AFTER NVRAM write (code at line ~1808 area, now after line 1817)
   - Firmware will see 0 at ramsize-4 → writes actual sharedram_addr
2. **Tighter masking**: re-mask every 10ms (inner loop) instead of every 200ms
   - Closes the ~200ms window that the 7th event exploited
3. **Full probe on FW READY**: no return -ENODEV on fw_ready path
   - Sets sharedram_addr_written = fw_sharedram; falls through to normal init
   - brcmf_pcie_init_share_ram_info(devinfo, sharedram_addr) will be called
4. **TIMEOUT**: returns -ENODEV (investigate if firmware still doesn't write)

**Expected outcome if sentinel fix works:**
- Firmware writes sharedram_addr within 2-3s of ARM release (maybe even sooner with correct sentinel)
- Full brcmfmac init proceeds: ring buffers, IRQs, etc.
- WiFi device appears operational
- BCM4360 802.11ac finally works on this MacBook Pro

**Module build:** done (test.63 built successfully, no errors)
**Test script:** updated to test.63 (log = test.63.stage0), waits 30s

**After test — what to do (whether PASS or crash):**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.63" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.63.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.63.*`
4. git add logs + commit + push
5. Analyze results

**After a crash:**
1. Check if "FW READY" was logged → sentinel fix worked, crash is in full probe
2. Check if sharedram=0 always → firmware still doesn't write even with fixed sentinel → deeper issue
3. Note the T+Xms when crash occurred

**After success (FW READY + survived 30s):**
1. Check if WiFi device appears: `ip link show` or `iw dev`
2. Check if brcmfmac is loaded: `lsmod | grep brcm`
3. Test WiFi scanning if possible

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
- test.62: CRASHED at ~T+20s (two root causes found — see above)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.63.stage0, test.63.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.63 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
