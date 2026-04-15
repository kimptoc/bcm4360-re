#!/usr/bin/env bash
# Phase 5.2 test.55: two-phase polling — BAR0-only first 1.5s, then BAR2 reads
#
# test.54 RESULT: INSTANT CRASH at iter 1 (BAR2 read fails after ARM release).
#   BAR0 reads all succeeded: BAR0_WIN=0x18000000, CHIPID=0x15034360, WDOG=0, PMUWDOG=0.
#   Root cause: real BCM4360 firmware (rstvec=0xb80ef000) runs and initializes the PCIE2
#   DMA engine within 10ms of ARM release (SBR gives clean state), making BAR2 temporarily
#   inaccessible. Unconditional brcmf_pcie_read_ram32() after log -> PCIe Completion Timeout.
#   Note: rstvec is REAL firmware, not the busyloop B. injection (that was only test.45).
#   The pcie_shared marker 0xffc70038 was NVRAM written to TCM[0x9fffc], not pcie_shared.
#
# test.55 CHANGES:
#   - PRE-PHASE (iters 1-150, 0-1.5s): BAR0-only reads. No BAR2. Log at 1,5,10,25,50,100,150.
#     BAR0_WINDOW, CHIPID, WDOG, PMUWDOG (guarded: only if BAR0_WIN==0x18000000 and CHIPID valid).
#     Early exit if CHIPID=0xffffffff (device dead).
#   - POST-PHASE (iters 151-500, 1.5-5s): same BAR0 reads + BAR2 (brcmf_pcie_read_ram32).
#     Log every 10 iters and immediately when BAR2 value changes (= pcie_shared written).
#   - Hypothesis: firmware PCIE2 init completes within ~200ms. BAR2 safe from iter ~20 of post-phase.
#
# Expected outcomes:
#   - PASS + BAR2 changes in post-phase: firmware wrote pcie_shared. Normal init proceeds.
#     Log shows at what iter BAR2 changed -> tells us how long PCIE2 init took.
#     -> Normal driver init should complete (device registered, wlan0 appears).
#   - CRASH in post-phase: BAR2 still not ready at 1.5s. Extend pre-phase delay.
#     -> test.56: extend pre-phase to 300 or 400 iters (3-4s).
#   - CRASH in pre-phase: BAR0 reads themselves unsafe (unexpected -- test.54 showed they're safe).
#   - 5s timeout (no BAR2 change): firmware never wrote pcie_shared. Investigate TCM/DMA.
#
# Usage: sudo ./test-staged-reset.sh [stage]
# Default stage is 0
set -e

STAGE="${1:-0}"
WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test.55.stage${STAGE}"

echo "=== test.55: SBR + two-phase polling (BAR0-only 0-1.5s, BAR2 1.5-5s) --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; BAR0 probe; BBPLL; ARM release; PRE-PHASE BAR0-only 150 iters; POST-PHASE BAR0+BAR2" | tee -a "$LOG" ;;
    *) echo "ERROR: Invalid stage (use 0)" | tee -a "$LOG"; exit 1 ;;
esac
echo "" | tee -a "$LOG"

# Check modules exist
for mod in brcmfmac.ko wcc/brcmfmac-wcc.ko; do
    if [ ! -f "$FMAC_DIR/$mod" ]; then
        echo "ERROR: $FMAC_DIR/$mod not found -- run make first" | tee -a "$LOG"
        exit 1
    fi
done

# Clean up any existing module
if lsmod | grep -q brcmfmac; then
    echo "Removing existing brcmfmac..." | tee -a "$LOG"
    rmmod brcmfmac-wcc 2>/dev/null || true
    rmmod brcmfmac-cyw 2>/dev/null || true
    rmmod brcmfmac-bca 2>/dev/null || true
    rmmod brcmfmac 2>/dev/null || true
    sleep 1
fi

# Unbind any existing driver
if [ -e "/sys/bus/pci/devices/$PCI_SLOT/driver" ]; then
    CURRENT=$(basename "$(readlink /sys/bus/pci/devices/$PCI_SLOT/driver)")
    echo "Unbinding $CURRENT from $PCI_DEV..." | tee -a "$LOG"
    echo "$PCI_SLOT" > "/sys/bus/pci/devices/$PCI_SLOT/driver/unbind" 2>/dev/null || true
    sleep 1
fi

# Capture pre-test PCIe state
echo "=== Pre-test PCIe state ===" | tee -a "$LOG"
LSPCI="/nix/store/hnif0bxpp0p4w3h7gdfmaglmgk0dp6x8-pciutils-3.14.0/bin/lspci"
if [ -x "$LSPCI" ]; then
    "$LSPCI" -s "$PCI_DEV" -nn -vv 2>&1 | head -30 | tee -a "$LOG"
else
    echo "(lspci not available)" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# Flush before loading
echo "=== Flushing to disk ===" | tee -a "$LOG"
sync
echo "Flush complete." | tee -a "$LOG"

# Load module with staged reset
echo "" | tee -a "$LOG"
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.55 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 15s (5s FW wait loop + 10s diagnostics)..." | tee -a "$LOG"
sleep 15

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.55: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.55)" | tee -a "$LOG"
