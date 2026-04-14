#!/usr/bin/env bash
# Phase 5.2 test.19: CPUHALT isolation test
#
# Clear ARM CR4 reset but keep CPUHALT set. ARM core is electrically
# active but cannot execute instructions.
#
# If PC crashes   → hardware/link event from reset-clear itself
# If PC survives  → crash is from ARM executing firmware code
#
# Usage: sudo ./test-halt-only.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test.19"

echo "=== test.19: CPUHALT isolation — reset-clear without ARM execution ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

echo "=== STEP 0: Module parameter ===" | tee -a "$LOG"
echo "bcm4360_halt_only=1 — ARM will be taken out of reset but CPUHALT prevents execution" | tee -a "$LOG"
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

# Capture pre-test state
echo "=== STEP 1: Pre-test PCIe state ===" | tee -a "$LOG"
LSPCI="/nix/store/hnif0bxpp0p4w3h7gdfmaglmgk0dp6x8-pciutils-3.14.0/bin/lspci"
if [ -x "$LSPCI" ]; then
    "$LSPCI" -s "$PCI_DEV" -nn 2>&1 | tee -a "$LOG"
else
    echo "(lspci not at expected path)" | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# Flush before loading
echo "=== STEP 2: Flushing to disk ===" | tee -a "$LOG"
sync
echo "Flush complete." | tee -a "$LOG"

# Load module with halt_only=1
echo "" | tee -a "$LOG"
echo "=== STEP 3: Loading brcmfmac (bcm4360_halt_only=1) ===" | tee -a "$LOG"
echo "ARM CR4 will be taken out of reset but CPUHALT keeps it from executing." | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_halt_only=1
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 15s..." | tee -a "$LOG"
sleep 15

# Capture results
echo "" | tee -a "$LOG"
echo "=== STEP 4: Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** PC SURVIVED! Reset-clear with CPUHALT did NOT crash. ***" | tee -a "$LOG"
echo "*** This means the crash is caused by ARM EXECUTING firmware, not the reset itself. ***" | tee -a "$LOG"
echo "Log saved to $LOG" | tee -a "$LOG"
