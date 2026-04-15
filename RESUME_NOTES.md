# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.80)

Git branch: main (pushed to origin)

## test.79 RESULT: SURVIVED (rebooted to boot -1)

**test.79 cleared unknown PCIe2 regs + dumped TCM stack area.**
Machine SURVIVED. Firmware still hangs in pcidongle_probe — identical pattern.

### test.79 key findings:
1. **PCIe2 core rev=1** — confirms `rev <= 13` config restore applies for BCM4360
2. **Cleared 0x100-0x108 to 0 OK** — readback verified all zero
3. **0x1E0 partially cleared** — wrote 0, read back 0x00070000 (bits [18:16]=0x7 hardwired)
4. **Firmware STILL hangs** — clearing unknown regs did NOT fix pcidongle_probe hang
5. **Stack dump at 0x9E000-0x9F000 = WRONG REGION** — all high-entropy data = firmware
   binary/rodata, NOT stack frames. Need to find actual stack location.
6. **Register-clearing approach exhausted** — tests 76-79 tried ASPM, H2D mailboxes,
   unknown regs; NONE changed outcome. Need new approach.

### Where is the stack?
The 0x0006xxxx values seen in console dump (0x9CE80-0x9D000 area) are likely function
pointers in si_cores enumeration structure, NOT return addresses. The actual ARM stack
grows downward from somewhere in 0x90000-0x9C000 range (below console buffer at 0x9CC00,
above heap). Need to scan for code-range return addresses.

## test.80 HYPOTHESIS

Instead of guessing the stack location, SCAN for it. Read one word every 64 bytes from
0x90000 to 0x9E000 (896 reads). Values in firmware code range (0x00001000-0x00070000)
are likely return addresses on the ARM stack. Clusters of hits reveal the stack.

## test.80 PLAN (about to run)

**Goal:** Locate firmware stack in TCM to find where pcidongle_probe is spinning.

**Key changes from test.79:**
1. REMOVE: Full BAC dump (confirmed identical across tests, not useful)
2. REMOVE: Old stack dump at 0x9E000-0x9F000 (wrong region — firmware binary)
3. ADD: Stack-finder scan: read TCM[0x90000..0x9E000] every 64 bytes (896 reads)
4. ADD: Flag values in code range 0x00001000-0x00070000 as likely return addresses
5. ADD: Probe dump of 0x9AF00-0x9B000 (seen as data pointer in console area)
6. KEEP: ASPM disable, named reg clears (INTMASK/MBMASK/H2D0/H2D1)
7. KEEP: Unknown reg clears (0x100-0x108, 0x1E0)
8. KEEP: Console dump at T+3s, BSS dump at T+5s, olmsg at T+20s

**Expected outcomes:**
- Stack-finder hits clustered in specific region → that's the stack
- Dense dump in next test will reveal exact call chain / busy-wait location
- If NO code-range hits anywhere → stack may be in a region we haven't considered

## Run test.80 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.80" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.80.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.80.*'`
3. Look for "stkHIT" lines — these are the code-range values
4. If clustered in one region → that's the stack. Do dense dump in test.81.
5. If scattered → might be heap function pointers, not stack. Rethink.
6. Check probe dump at 0x9AF00-0x9B000 for stack-like patterns

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
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75/76/77/78/79)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- 0x1E0 bits [18:16] = 0x7 are hardwired (can't be cleared) ✓ (test.79)
- TCM[0x9E000-0x9F000] = firmware binary, NOT stack ✗ (test.79)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console text decoded (test.78/79 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75/76/77/78/79 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (counter/timer, stops at T+2s = firmware hung)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.80.stage0, test.80.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.68: SURVIVED 60s then CRASHED in TIMEOUT path — console buffer decoded
- test.69: CRASHED in TIMEOUT path at TCM[0x88000] — msleep(1) insufficient
- test.70: SURVIVED — per-read re-mask+msleep(10) in TIMEOUT path; no IOMMU faults
- test.71: CRASHED after FW READY — H2D_MAILBOX_0=1 → immediate crash
- test.72: CRASHED after SBMBX write — stale masking race
- test.73: SURVIVED — SBMBX only (fresh masking); firmware never wrote sharedram
- test.74: CRASHED — H2D_MAILBOX_0 BAR0 write (ring doorbell during init) → immediate crash
- test.75: SURVIVED — pure diagnostic; firmware freezes in pcidongle_probe (ASPM L1 theory)
- test.76: SURVIVED (crash in post-timeout cleanup) — ASPM disable did NOT fix hang; theory dead
- test.77: SURVIVED — H2D0/H2D1 stale 0xffffffff cleared to 0; still hangs; theory dead
- test.78: SURVIVED — full PCIe2 BAC dump; DMA theory wrong (0x120/0x124 = CONFIGADDR/CONFIGDATA)
- test.79: SURVIVED — cleared unknown regs 0x100-0x108/0x1E0; stack dump at 0x9E000 = wrong region
- test.80: PENDING — stack-finder scan 0x90000-0x9E000; probe dump 0x9AF00-0x9B000
