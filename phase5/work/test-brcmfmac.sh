#!/usr/bin/env bash
# Phase 5: Test patched brcmfmac with BCM4360 support
# Usage: sudo ./test-brcmfmac.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"

mkdir -p "$LOG_DIR"

# Find next log number
LOG_NUM=1
while [ -f "$LOG_DIR/test.$LOG_NUM" ]; do
    LOG_NUM=$((LOG_NUM + 1))
done

echo "=== Phase 5: brcmfmac BCM4360 test ==="
echo "Log: $LOG_DIR/test.$LOG_NUM"
echo ""

# Check modules exist
for mod in brcmfmac.ko wcc/brcmfmac-wcc.ko cyw/brcmfmac-cyw.ko bca/brcmfmac-bca.ko; do
    if [ ! -f "$FMAC_DIR/$mod" ]; then
        echo "ERROR: $FMAC_DIR/$mod not found — run make first"
        exit 1
    fi
done

# Check firmware and NVRAM exist
if [ ! -f /lib/firmware/brcm/brcmfmac4360-pcie.bin ]; then
    echo "ERROR: /lib/firmware/brcm/brcmfmac4360-pcie.bin not found"
    exit 1
fi
if [ ! -f /lib/firmware/brcm/brcmfmac4360-pcie.txt ]; then
    echo "ERROR: /lib/firmware/brcm/brcmfmac4360-pcie.txt not found"
    exit 1
fi

echo "Firmware: $(ls -l /lib/firmware/brcm/brcmfmac4360-pcie.bin)"
echo "NVRAM:    $(cat /lib/firmware/brcm/brcmfmac4360-pcie.txt | head -1)"
echo ""

# Unbind any existing driver from BCM4360
if [ -e "/sys/bus/pci/devices/0000:$PCI_DEV/driver" ]; then
    CURRENT=$(basename "$(readlink /sys/bus/pci/devices/0000:$PCI_DEV/driver)")
    echo "Unbinding $CURRENT from $PCI_DEV..."
    echo "0000:$PCI_DEV" > "/sys/bus/pci/devices/0000:$PCI_DEV/driver/unbind" 2>/dev/null || true
    sleep 1
fi

# Remove stock brcmfmac if loaded
if lsmod | grep -q brcmfmac; then
    echo "Removing stock brcmfmac..."
    rmmod brcmfmac-wcc 2>/dev/null || true
    rmmod brcmfmac-cyw 2>/dev/null || true
    rmmod brcmfmac-bca 2>/dev/null || true
    rmmod brcmfmac 2>/dev/null || true
    sleep 1
fi

# Remove our phase4 test module if loaded
if lsmod | grep -q bcm4360_test; then
    echo "Removing bcm4360_test..."
    rmmod bcm4360_test 2>/dev/null || true
    sleep 1
fi

# Pre-test MMIO check — distinguish Completion Timeout (CTO) from Unsupported Request (UR).
# CTO: device ignores transaction → ~50ms timeout → MCE → hard crash. DO NOT insmod.
# UR:  device responds "no" in ~50µs → clean I/O error, no crash. SBR in probe fixes it.
# Timing threshold: <5ms = UR (safe), >5ms = CTO (unsafe, power cycle required).
echo "Pre-test: checking BAR0 MMIO (resource0)..."
# Timing distinguishes CTO from UR:
# UR (device alive, rejects immediately): PCIe transaction ~65µs + ~20ms bash overhead = ~21ms total
# CTO (device dead, no response): 50ms PCIe timeout + ~20ms bash overhead = ~70ms total
# Threshold 40ms reliably separates the two.
T_START=$(date +%s%3N)
set +e
dd if=/sys/bus/pci/devices/0000:$PCI_DEV/resource0 bs=4 count=1 of=/dev/null 2>/dev/null
DD_EXIT=$?
set -e
T_END=$(date +%s%3N)
T_MS=$((T_END - T_START))

if [ $DD_EXIT -eq 0 ]; then
    echo "BAR0 MMIO OK — device responding normally."
elif [ $T_MS -lt 40 ]; then
    echo "BAR0 MMIO: Unsupported Request (${T_MS}ms) — device alive, SBR in probe should fix. Proceeding."
else
    echo ""
    echo "FATAL: BAR0 MMIO Completion Timeout (${T_MS}ms) — device dead, insmod will hard-crash."
    echo "Recovery (MacBook): drain battery to 0%, wait after shutdown, recharge, boot."
    exit 1
fi
echo ""

echo "Loading patched brcmfmac modules..."
dmesg -C  # Clear kernel log

# Ensure dependencies are loaded
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true

# Load brcmfmac + vendor module (WCC = Broadcom WCC)
insmod "$FMAC_DIR/brcmfmac.ko"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Modules loaded. Waiting 15s for probe + FW init timeout + debug dump..."
sleep 15

# Capture dmesg output
echo "=== dmesg output ===" | tee "$LOG_DIR/test.$LOG_NUM"
dmesg | tee -a "$LOG_DIR/test.$LOG_NUM"

echo ""
echo "=== Network interfaces ==="
ip link show 2>/dev/null | grep -A1 "wl\|brcm\|wlan" || echo "  (no wireless interfaces found)"

echo ""
echo "=== Module state ==="
lsmod | grep brcm || echo "  (brcmfmac not loaded)"

echo ""
echo "Log saved to $LOG_DIR/test.$LOG_NUM"
