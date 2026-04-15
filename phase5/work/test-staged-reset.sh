#!/usr/bin/env bash
# Phase 5.2 test.69: Fix TIMEOUT crash + add console write-ptr monitoring
#
# test.68 RESULT: Survived 60s but CRASHED in TIMEOUT final TCM scan path.
#   Root cause: no settle time between last re-mask and BAR2 reads in TIMEOUT path.
#   During the 60s loop, each BAR2 read follows msleep(10); TIMEOUT path had zero delay.
#   Console buffer decoded: firmware prints banner then stops — ASSERT or infinite wait.
#   Firmware wrote 50+ non-zero words in upper BSS (got well into BSS init).
#   Console write ptr at 0x9cc5c — monitor this to detect firmware activity.
#
# test.69 KEY CHANGES from test.68:
#   1. TIMEOUT path: add re-mask + RW1C clear + msleep(1) before final TCM scan
#      (same settle-time recipe as the inner loop — proven to prevent crashes)
#   2. Add 0x9cc5c (console ring write pointer) to t66_scan — monitor firmware printf activity
#   3. Reduce wait from 60s to 30s (firmware either signals or dies within 10s)
#   4. Test script waits 45s (30s FW wait + margin)
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
LOG="$LOG_DIR/test.69.stage${STAGE}"

echo "=== test.69: 30s wait + TIMEOUT settle fix + console ptr monitoring --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; NVRAM; NVRAM token kept; pci_set_master before ARM; activate() preserves BusMaster; 30s masking+FW wait; TCM scan every 2s (from T+200ms); console write-ptr at 0x9cc5c in scan; TIMEOUT: re-mask+msleep(1) before final scan; fw_init_done poll (baseline-initialized); RP restore on timeout" | tee -a "$LOG" ;;
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

# Also show root port state (00:1c.2) before the test
echo "=== Pre-test root port (00:1c.2) state ===" | tee -a "$LOG"
if [ -x "$LSPCI" ]; then
    "$LSPCI" -s "00:1c.2" -nn -vv 2>&1 | head -20 | tee -a "$LOG"
fi
echo "" | tee -a "$LOG"

# Flush before loading
echo "=== Flushing to disk ===" | tee -a "$LOG"
sync
echo "Flush complete." | tee -a "$LOG"

# Load module with staged reset
echo "" | tee -a "$LOG"
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.69 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 45s (30s FW wait + margin for full probe)..." | tee -a "$LOG"
echo "(test.69: 30s wait; TCM scan every 2s from T+200ms; console ptr 0x9cc5c monitored; TIMEOUT: re-mask+settle before final scan; FW READY → full probe; TIMEOUT → -ENODEV + RP restore)" | tee -a "$LOG"
sleep 45

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.69: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.69)" | tee -a "$LOG"
