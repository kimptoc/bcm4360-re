#!/usr/bin/env bash
# Phase 5.2 test.18: IOMMU-protected ARM release
#
# Previous tests 8-17 all crashed the PC on ARM release. No IOMMU DMA
# translation was active — firmware DMA went directly to physical memory.
#
# test.18 runs AFTER enabling intel_iommu=on + iommu=strict in kernel
# params. If firmware tries rogue DMA, IOMMU should catch it and report
# DMAR faults instead of crashing the PC.
#
# Usage: sudo ./test-iommu.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"
LSPCI="/nix/store/hnif0bxpp0p4w3h7gdfmaglmgk0dp6x8-pciutils-3.14.0/bin/lspci"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test.18"

echo "=== test.18: IOMMU-protected ARM release ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# ===== STEP 0: Verify IOMMU DMA translation is active =====
echo "=== STEP 0: IOMMU verification ===" | tee -a "$LOG"
echo "Kernel cmdline:" | tee -a "$LOG"
cat /proc/cmdline | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "IOMMU status:" | tee -a "$LOG"
dmesg | grep -i -E "iommu|DMAR" | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "IOMMU groups:" | tee -a "$LOG"
ls /sys/kernel/iommu_groups/ 2>/dev/null | wc -l | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Check BCM4360 is in an IOMMU group
if [ -e "/sys/bus/pci/devices/$PCI_SLOT/iommu_group" ]; then
    IOMMU_GRP=$(basename "$(readlink /sys/bus/pci/devices/$PCI_SLOT/iommu_group)")
    echo "BCM4360 IOMMU group: $IOMMU_GRP" | tee -a "$LOG"
else
    echo "WARNING: BCM4360 NOT in any IOMMU group! DMA is unprotected." | tee -a "$LOG"
    echo "ABORTING — enable intel_iommu=on first." | tee -a "$LOG"
    sync
    exit 1
fi

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

# ===== STEP 1: Capture pre-test state =====
echo "" | tee -a "$LOG"
echo "=== STEP 1: Pre-test PCIe state ===" | tee -a "$LOG"
if [ -x "$LSPCI" ]; then
    "$LSPCI" -s "$PCI_DEV" -vvv 2>&1 | tee -a "$LOG"
else
    echo "(lspci not at expected path)" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# ===== STEP 2: Flush pre-test data =====
echo "=== STEP 2: Flushing to disk ===" | tee -a "$LOG"
sync
echo "Flush complete." | tee -a "$LOG"

# ===== STEP 3: Load module (ARM release will happen during probe) =====
echo "" | tee -a "$LOG"
echo "=== STEP 3: Loading brcmfmac (ARM RELEASE with IOMMU protection) ===" | tee -a "$LOG"
echo "If IOMMU catches rogue DMA, look for DMAR fault messages in dmesg." | tee -a "$LOG"
sync  # one more sync

dmesg -C  # Clear kernel log
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 20s for probe + FW init..." | tee -a "$LOG"
sleep 20

# ===== STEP 4: Capture results =====
echo "" | tee -a "$LOG"
echo "=== STEP 4: Post-ARM dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== DMAR faults (if any) ===" | tee -a "$LOG"
dmesg | grep -i -E "DMAR|fault|DMA" | tee -a "$LOG" || echo "  (no DMAR faults)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Network interfaces ===" | tee -a "$LOG"
ip link show 2>/dev/null | grep -A1 "wl\|brcm\|wlan" | tee -a "$LOG" || echo "  (no wireless interfaces found)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "If you're reading this, the PC survived ARM release with IOMMU!" | tee -a "$LOG"
echo "Log saved to $LOG" | tee -a "$LOG"
