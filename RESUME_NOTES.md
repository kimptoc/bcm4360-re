# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.69)

Git branch: main (pushed to origin)

## test.66 RESULT: CRASHED before T+0000ms — PCIe2 select_core crash

**Root cause: `brcmf_pcie_select_core(PCIE2)` at outer=0 before first msleep**
- `brcmf_pcie_select_core()` does `pci_write_config_dword(EP, BAR0_WINDOW, ...)` — same mechanism as test.51 instant crash
- Baseline PCIe2 reads at T+~0ms worked (firmware hadn't started PCIe2 init yet)
- outer=0 loop PCIe2 reads failed at T+~5ms (after 20 TCM baseline reads)
- Machine crashed before T+0000ms was logged — no journal evidence of TCM changes

**Baseline TCM values (read at T+~0ms, firmware not yet running):**
- sharedram[0x9FFFC] = 0xffc70038 (NVRAM token — kept)
- magic[0x9D0A4] = 0x555c0631 (firmware binary constant, not runtime)
- fw_init[0x9F0CC] = 0x870ca017 (firmware binary constant, not runtime)
- PCIe2: MAILBOXINT=0x00000000, MAILBOXMASK=0x00000000

**Key secondary finding:** fw_init_done_last was initialized to 0, but baseline reads 0x870ca017 at that address — it's firmware binary data. Must initialize from baseline to detect runtime changes.

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

## test.67 RESULT: SURVIVED 60s — firmware alive but crashed before sharedram init

**TCM[0x9d000] changed at T+2s from 0x00000000 → 0x000043b1**
- 0x000043b1 with bit 0 set = ARM Thumb function pointer to address 0x43b0
- Firmware binary at 0x43b0: pointer table with values like 0x00058E30, 0x00042536
- NOT a valid sharedram_addr: version byte = 0xb1 = 177 (valid range 5–7)
- Address 0x9d000 is beyond firmware binary end (0x6BF79) → was zeroed, then written by firmware runtime
- Only 1 word changed in entire 60s → firmware crashed very early (before BSS/sharedram init)

**sharedram=0xffc70038 and fw_init=0x870ca017 throughout all 60s**
- Neither protocol signaled (FullDongle nor olmsg)
- EP_CMD=0x0006 throughout — BusMaster maintained correctly

**Root cause hypothesis: firmware crashes before sharedram write phase**
- 0x43b0 is a pointer table entry, likely written during C runtime init (BSS/data init before main())
- Firmware writes one function pointer, then crashes before reaching WiFi init
- Possible causes: missing NVRAM calibration params, hardware resource not available, assert/trap

## test.68 RESULT: SURVIVED 60s — firmware prints banner, then TIMEOUT path crashed

**Dense BSS scan results: 50+ non-zero words in upper BSS — firmware got well into BSS init**
- Lower BSS (0x6C000–0x9C000): 2 non-zero words: TCM[0x6c000]=0x008965f8, TCM[0x70000]=0xc0c900e2
  - These are RESIDUAL values from prior firmware run (SBR doesn't clear TCM SRAM)
- Upper BSS: 50+ non-zero words — firmware active region confirmed as 0x9cc00–0x9d000

**Console ring buffer decoded at 0x9cc00–0x9ce58:**
- Virtual write pointer stored at 0x9cc5c (and 0x9cc6c) = 0x8009ccbe → phys 0x9ccbe
- Firmware banner: "RTE (PCIE-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz"
- Sequence: Chipc info → wl_probe called → pcie_dngl_probe called → firmware banner → STAK fill
- No ASSERT message found (either overwritten by ring wrap or assert in separate struct)

**Region 0x9ce8c–0x9d000: linked list of event/timer objects**
- Contains function pointers (0x43b1, 0x68d2f, 0x68321...) — not an ASSERT structure
- This is normal firmware runtime data (timer/event dispatch tables)

**TIMEOUT path CRASHED during final TCM scan at TCM[0x74000]:**
- Root cause: zero settle time between last re-mask and BAR2 reads in TIMEOUT path
- During 60s loop: every BAR2 read follows msleep(10) — settle time proven safe
- TIMEOUT path: no delay → BAR2 read at [0x74000] triggered PCIe error → crash
- Fix: add re-mask + RW1C clear + msleep(1) before final scan

## test.69 RESULT: Crashed in TIMEOUT path at TCM[0x88000] (8th of 21 final reads)

**Root cause of crash:** msleep(1) before the final scan loop was not enough — no settle time BETWEEN reads crashed at read 8 (0x88000).

**Key findings from test.69 journal:**
- NVRAM token IS correctly at 0x9FFFC (0xffc70038) throughout — the "missing NVRAM" hypothesis was wrong
- The baseline print "sharedram[0x9FFFC]=0x5354414b" was an INDEX BUG: t66_prev[19] = 0x9cc5c (console ptr, had STAK from prior run), not 0x9FFFC (index 20)
- 0x9cc5c (console write ptr) CHANGED at T+2000ms: 0x5354414b → 0x8009ccbe (firmware console active)
- 0x9d000 CHANGED at T+2000ms: 0x00000000 → 0x000043b1 (pciedngldev struct written)
- sharedram (0x9FFFC) = 0xffc70038 throughout ALL 30 seconds — firmware NEVER writes sharedram_addr
- fw_init (0x9F0CC) = 0x870ca017 throughout — olmsg protocol not used either
- Firmware is alive and stable in event loop after T+2s; no changes for 28 seconds

**Critical insight:** The firmware enters its event loop at T+2s but never writes the FullDongle sharedram_addr pointer to 0x9FFFC. The normal brcmfmac flow times out waiting for this write. This is WHY BCM4360 doesn't work upstream.

## test.70 PLAN (about to run)

**Key changes from test.69:**
1. TIMEOUT final scan: per-read re-mask + msleep(10) BETWEEN EACH READ (not just once before loop) — same proven recipe as inner loop
2. Fix baseline print: use t66_prev[20] for 0x9FFFC (was incorrectly t66_prev[19] = 0x9cc5c); also print console_ptr[0x9cc5c] = t66_prev[19]
3. Test script waits 65s (30s FW wait + 35s margin for TIMEOUT path — 21 reads × ~10ms each = ~210ms)

**Module build:** done (test.70 built successfully, warning only: write_ram32 unused)
**Test script:** updated to test.70 (log = test.70.stage0), waits 65s

**Expected outcomes:**
- SURVIVE (no crash in TIMEOUT path) — per-read re-mask should prevent crash
- sharedram/fw_init still stuck: firmware never writes sharedram_addr
- console ptr 0x9cc5c should be 0x8009ccbe (unchanged, no new console output)
- Baseline print now correctly shows 0x9FFFC = 0xffc70038

**After test — what to do:**
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.70" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.70.journal'` (or -b 0 if survived)
3. `sudo chown kimptoc:users phase5/logs/test.70.*`
4. git add logs + commit + push
5. Next question: WHY does firmware never write sharedram_addr? Does it need a PCIe mailbox write from the host first?

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
- test.66: CRASHED before T+0000ms — PCIe2 select_core EP config write during firmware init
- test.67: SURVIVED 60s — TCM[0x9d000] changed at T+2s (0x000043b1 = Thumb ptr to 0x43b0); sharedram/fw_init unchanged; only 1 word changed → firmware crashes before sharedram init
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — dense BSS scan: 50+ non-zero words in upper BSS; console buffer decoded (firmware banner printed); crash root cause: no settle delay before final BAR2 reads in TIMEOUT path
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) before loop insufficient; per-read settle needed; INDEX BUG in baseline print (t66_prev[19]=0x9cc5c not 0x9FFFC); NVRAM token IS at 0x9FFFC (0xffc70038) throughout; firmware alive in event loop but never writes sharedram_addr
- test.70: DIAGNOSTIC — per-read re-mask+msleep(10) in TIMEOUT scan; fix baseline print index; 65s script wait

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.70.stage0, test.70.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Run test.70 (if not yet run):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0
