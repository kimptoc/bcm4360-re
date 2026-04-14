#!/usr/bin/env bash
# Phase 5.2 test.16: Warm-up hypothesis test
#
# test.7 (the ONLY successful ARM release) ran after 6 prior module
# load/unload cycles. All post-reboot tests crash immediately.
#
# This script:
# 1. Captures cold PCIe config space
# 2. Loads module with skip_arm=1 (safe warm-up)
# 3. Unloads module
# 4. Captures warm PCIe config space + diffs
# 5. Flushes everything to disk
# 6. Loads module again WITHOUT skip_arm (ARM release)
#
# Usage: sudo ./test-warmup.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"

mkdir -p "$LOG_DIR"

LOG="$LOG_DIR/test.16"

echo "=== test.16: warm-up hypothesis test ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Check modules exist
for mod in brcmfmac.ko wcc/brcmfmac-wcc.ko; do
    if [ ! -f "$FMAC_DIR/$mod" ]; then
        echo "ERROR: $FMAC_DIR/$mod not found — run make first" | tee -a "$LOG"
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

# ===== STEP 1: Capture COLD PCIe config space =====
echo "" | tee -a "$LOG"
echo "=== STEP 1: Cold PCIe config space ===" | tee -a "$LOG"
lspci -s "$PCI_DEV" -xxx 2>&1 | tee "$LOG_DIR/test.16.pcie-cold" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ===== STEP 2: Load with skip_arm=1 (safe warm-up) =====
echo "=== STEP 2: Loading brcmfmac with bcm4360_skip_arm=1 (warm-up) ===" | tee -a "$LOG"
dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_skip_arm=1
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Waiting 10s for probe to complete..." | tee -a "$LOG"
sleep 10

echo "--- warm-up dmesg ---" | tee -a "$LOG"
dmesg | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ===== STEP 3: Unload module =====
echo "=== STEP 3: Unloading brcmfmac (warm-up complete) ===" | tee -a "$LOG"
rmmod brcmfmac-wcc 2>/dev/null || true
rmmod brcmfmac 2>/dev/null || true
sleep 2

# ===== STEP 4: Capture WARM PCIe config space =====
echo "=== STEP 4: Warm PCIe config space ===" | tee -a "$LOG"
lspci -s "$PCI_DEV" -xxx 2>&1 | tee "$LOG_DIR/test.16.pcie-warm" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Diff cold vs warm
echo "=== PCIe config diff (cold -> warm) ===" | tee -a "$LOG"
diff "$LOG_DIR/test.16.pcie-cold" "$LOG_DIR/test.16.pcie-warm" | tee -a "$LOG" || true
echo "" | tee -a "$LOG"

# ===== STEP 5: Flush to disk =====
echo "=== STEP 5: Flushing all data to disk ===" | tee -a "$LOG"
sync
echo "Flush complete." | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ===== STEP 6: Load again WITHOUT skip_arm (ARM release!) =====
echo "=== STEP 6: Loading brcmfmac WITHOUT skip_arm (ARM RELEASE!) ===" | tee -a "$LOG"
echo "WARNING: If the warm-up hypothesis is wrong, this WILL crash the PC." | tee -a "$LOG"
sync  # one more sync before the dangerous part

dmesg -C
insmod "$FMAC_DIR/brcmfmac.ko"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded with ARM release. Waiting 15s..." | tee -a "$LOG"
sleep 15

echo "" | tee -a "$LOG"
echo "=== ARM release dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Network interfaces ===" | tee -a "$LOG"
ip link show 2>/dev/null | grep -A1 "wl\|brcm\|wlan" | tee -a "$LOG" || echo "  (no wireless interfaces found)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "If you're reading this, the PC survived ARM release!" | tee -a "$LOG"
echo "Log saved to $LOG" | tee -a "$LOG"
