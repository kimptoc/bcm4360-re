# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, about to run test.81)

Git branch: main (pushed to origin)

## test.80 RESULT: SURVIVED (rebooted to boot -1)

**test.80 ran the stack-finder scan across TCM[0x90000..0x9E000].**
Machine SURVIVED. Firmware still hangs in pcidongle_probe — identical pattern.

### test.80 key findings:
1. **Stack-finder found only 6 scattered hits** — no dense cluster = no stack
   - 0x91d80=0x1001, 0x93580=0x3901, 0x96280=0x1c99, 0x964c0=0x1000
   - 0x9ce00=0x62910 (console area), 0x9d000=0x43b1 (known BSS timer)
2. **64-byte sampling too coarse** for ARM stack frames (8-16 bytes each)
3. **Values 0x1000/0x1001 are common constants**, not return addresses
4. **Stack-finding approach is a dead end** — 5 tests of diagnosis (76-80) exhausted
5. **0x1E0 readback=0x00030000** (was 0x00070000 in test.79 — boot-state dependent)

### Strategy shift:
Stop diagnosing WHERE the firmware is stuck. Start testing WHAT it's waiting for.

## test.81 HYPOTHESIS

The firmware reads its own PCIe config space during pcidongle_probe via
CONFIGADDR/CONFIGDATA (0x120/0x124). MSI address/data are currently 0x0/0x0.
If pcidongle_probe polls for valid MSI configuration and sees zeros, it hangs.

Enabling MSI (pci_enable_msi) BEFORE ARM release populates the MSI address/data
in config space, which the firmware can then read from the device side.

## test.81 PLAN (about to run)

**Goal:** Test if MSI configuration unblocks pcidongle_probe.

**Key changes from test.80:**
1. ADD: pci_enable_msi(pdev) BEFORE ARM release
2. ADD: Log host-side MSI config before/after enable (0x58/0x5C/0x60/0x64)
3. ADD: Verify device-side MSI view via CONFIGADDR/CONFIGDATA pre-ARM
4. ADD: Wider TCM scan (0x9A000-0x9FFFC every 0x100, ~32 new locations)
5. ADD: Post-timeout MSI state check (did firmware change MSI?)
6. ADD: pci_disable_msi() in all cleanup/return paths
7. REMOVE: Stack-finder scan (failed — dead end)
8. REMOVE: Probe dump at 0x9AF00 (not useful)
9. KEEP: ASPM disable, named reg clears, console+BSS dumps, masking

**Expected outcomes:**
- If MSI fixes it: sharedram gets written, firmware completes probe → BREAKTHROUGH
- If MSI doesn't fix it: we see MSI was successfully configured (addr/data non-zero)
  but firmware still hangs → MSI isn't the issue, try next hypothesis
- Device-side MSI view confirms firmware CAN see the config we set
- Wider TCM scan might catch PCI-CDC writes at non-MSGBUF locations

**If MSI doesn't work, next steps:**
- Force a firmware trap (corrupt a data structure → RTE trap handler dumps
  registers including PC/SP to known location)
- Or try writing a specific value to a known location to signal the firmware

## Run test.81 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.81" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.81.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.81.*'`
3. Look for "MSI BEFORE/AFTER enable" lines — did MSI get configured?
4. Look for "device-side MSI view" — can firmware see MSI config?
5. Check if sharedram changed from NVRAM token → BREAKTHROUGH if so
6. Check wider TCM scan for new CHANGED entries (PCI-CDC handshake?)
7. Check "MSI at TIMEOUT" — did firmware modify MSI state?

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
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75/76/77/78/79/80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- 0x1E0 bits vary by boot (0x00070000 in test.79, 0x00030000 in test.80)
- TCM[0x9E000-0x9F000] = firmware binary, NOT stack ✗ (test.79)
- TCM[0x90000-0x9E000] has no dense stack cluster at 64-byte granularity ✗ (test.80)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console text decoded (test.78/79/80 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (counter/timer, stops at T+2s = firmware hung)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.81.stage0, test.81.journal (after test)
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
- test.80: SURVIVED — stack-finder scan found only 6 scattered hits; no stack cluster
- test.81: PENDING — MSI enable before ARM; wider TCM scan; device-side MSI verification
