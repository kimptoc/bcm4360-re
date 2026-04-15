# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-15, about to run test.79)

Git branch: main (pushed to origin)

## test.78 RESULT: SURVIVED

**test.78 was a full PCIe2 BAC register dump (0x000-0x1FF) pre-ARM.**
Machine SURVIVED. Firmware still hangs in pcidongle_probe — identical pattern.

### PCIe2 BAC dump analysis (CORRECTED register map):

Key: register offsets confirmed against brcmfmac defines (INTMASK=0x024, MBINT=0x048,
MBMASK=0x04C, CONFIGADDR=0x120, CONFIGDATA=0x124, H2D0=0x140, H2D1=0x144).

Non-0xffffffff registers (0xffffffff = unimplemented/absent):
```
0x000: 0x00000182  (PCIe2 core control)
0x004: 0x0000003c  (PCIe2 intstatus)
0x024: 0x00000000  (INTMASK — confirmed zero ✓)
0x02C: 0x00000005  (unknown)
0x040: 0x00000003  (SBMBX area)
0x044: 0x18003008  (unknown — PCIe2 internal config?)
0x048: 0x00000000  (MAILBOXINT — confirmed zero ✓)
0x04C: 0x00000000  (MAILBOXMASK — confirmed zero ✓)
0x050: 0x01f401f4  (timer/config — 500/500)
0x054: 0x00200020  (timer/config — 32/32)
0x100: 0x0000000c  (UNKNOWN — not DMA as originally assumed)
0x104: 0x0000000c  (UNKNOWN — three consecutive regs same value)
0x108: 0x0000000c  (UNKNOWN)
0x120: 0x000004e0  (CONFIGADDR → points to BAR2_CONFIG ✓)
0x124: 0x00000016  (CONFIGDATA → BAR2_CONFIG value ✓)
0x140: 0xffffffff  (H2D_MAILBOX_0 — stale ✓, matches named read)
0x144: 0xffffffff  (H2D_MAILBOX_1 — stale ✓, matches named read)
0x1E0: 0x00070040  (UNKNOWN)
```

**CRITICAL CORRECTION:** The RESUME_NOTES DMA register layout was WRONG.
- 0x120/0x124 are CONFIGADDR/CONFIGDATA (indirect PCIe config access), NOT DMA RX regs
- 0x100-0x108 are unknown PCIe2 core registers, NOT DMA TX regs
- The "DMA channel state" theory from test.78 hypothesis was based on wrong register map
- All three 0x100-0x108 reading 0x0000000c (identical value) is suspicious — likely
  hardware default or some PCIe2 internal state, not stale DMA descriptors

## test.79 HYPOTHESIS

The unknown registers at 0x100-0x108 (value 0x0c) and 0x1E0 (value 0x00070040) MIGHT
have stale state that affects firmware's pcidongle_probe initialization. Clearing them
before ARM release is low-risk and might help.

Additionally, we need to find WHERE in pcidongle_probe the firmware is stuck. Adding a
wider TCM stack dump at timeout should reveal the call chain/stack frames.

## test.79 PLAN (about to build)

**Goal:** Clear unknown regs + find firmware hang location via stack dump.

**Key changes from test.78:**
1. ADD: Print PCIe2 core revision (answers rev <= 13 config restore question)
2. ADD: Clear 0x100, 0x104, 0x108 to 0 (unknown purpose, was 0x0000000c)
3. ADD: Clear 0x1E0 to 0 (unknown purpose, was 0x00070040)
4. ADD: At timeout, dump TCM[0x9E000..0x9F000] (likely firmware stack area)
5. KEEP: BAC full dump 0x000-0x1FF (compare pre-clear vs post-clear)
6. KEEP: named register reads + H2D0/H2D1/INTMASK/MBMASK clears
7. KEEP: ASPM disable, console dump at T+3s, BSS dump at T+5s
8. NOT attempting select_core(PCIE2) post-timeout (crashes — test.66/76)

**Expected outcomes:**
- If clearing 0x100-0x108/0x1E0 fixes hang → firmware advances past pcidongle_probe
- If still hangs → stack dump shows where firmware is stuck
- PCIe2 core rev answers whether upstream config restore loop runs for BCM4360

## Run test.79 (after build):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.79" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.79.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.79.*'`
3. Check PCIe2 core rev from log
4. Check if stack dump at 0x9E000..0x9F000 shows return addresses (look for 0x000xxxxx values = TCM code addresses)
5. If firmware advanced → test.80: let it run longer, check if pcie_shared gets written
6. If still hangs → analyze stack dump to identify the exact function/loop

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
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75/76/77/78)
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- select_core(BCMA_CORE_PCIE2) after firmware starts → CRASH ✗ (test.66/76)
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- PCIe2 BAC pre-ARM: INTMASK=0x0, MBMASK=0x0, H2D0=0xffffffff, H2D1=0xffffffff ✓

## Console text decoded (test.78 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75/76/77/78 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (changed from 0 at T+2s = some firmware counter/timer, stops at T+2s)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic, values stable across runs but vary slightly)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.79.stage0, test.79.journal (after test)
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
- test.79: PENDING — clear unknown regs 0x100-0x108/0x1E0; stack dump at timeout
