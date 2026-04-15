#!/usr/bin/env bash
# Phase 5.2 test.56: 2000ms sleep after ARM release, then poll BAR0+BAR2
#
# test.55 RESULT: CRASH after PRE iter=1 even though PRE phase had NO BAR2 reads.
#   Logged: "BCM4360 test.55 PRE iter=1 BAR0_WIN=0x18000000 CHIPID=0x15034360 WDOG=0 PMUWDOG=0"
#   Then journal ends — crash at ~20ms (iter=2), during BAR0 reads (not BAR2!).
#   Conclusion: PCIE2 init makes ALL PCIe accesses fail (BAR0 + BAR2 + config space).
#   Even BAR0 reads cause PCIe Completion Timeout → NMI → host crash during the PCIE2 init window.
#
# test.56 STRATEGY: sleep 2000ms after ARM release with ZERO PCIe reads.
#   - Log BEFORE and AFTER sleep to distinguish: crash-during-sleep vs crash-on-first-read.
#   - After 2s: poll BAR0+BAR2 every 10ms. Log at iters 1,5,10,25,50,100 + on BAR2 change.
#   - When BAR2 != initial marker (0xffc70038) → firmware wrote pcie_shared → normal init.
#
# Expected outcomes:
#   - PASS: BAR2 changes within a few iters → wlan0 registered. SUCCESS!
#   - Crash BEFORE "woke up" log → firmware-initiated crash during sleep (different mechanism).
#   - Crash AFTER "woke up" on first reads → 2s wasn't enough; need to extend sleep.
#   - 5s timeout (no BAR2 change) → firmware never wrote pcie_shared; investigate TCM/DMA.
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
LOG="$LOG_DIR/test.56.stage${STAGE}"

echo "=== test.56: SBR + 2000ms sleep + poll BAR0+BAR2 --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; BAR0 probe; BBPLL; ARM release; 2000ms sleep; poll BAR0+BAR2" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.56 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 22s (2s sleep + 5s FW wait loop + 15s diagnostics)..." | tee -a "$LOG"
sleep 22

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.56: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.56)" | tee -a "$LOG"
