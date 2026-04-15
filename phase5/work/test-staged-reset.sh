#!/usr/bin/env bash
# Phase 5.2 test.40: PMU pllcontrol diagnostic + ARM wrapper state
#
# test.39 SURVIVED: Watchdog reset completed on IOMMU group 8 without crash.
# PMU always-on: min/max/res_state unchanged at 0x13f after watchdog.
# clk_ctl_st: HAVEALP=1, BP_ON_ALP=1, HAVEHT=0 (BBPLL still OFF after watchdog).
# pmustatus: HAVEHT (bit 2=0x04) NOT set, HAVEALP (bit 3=0x08) set.
# Watchdog does NOT bring BBPLL up; PMU domain preserved through watchdog.
# ARM released but not executing: TCM completely unchanged after 5s.
# bcma.ko: "PMU resource config unknown or not needed for 0x43A0".
#
# test.40: diagnostic — read pllcontrol[0..5] before+after watchdog.
# Read ARM wrapper registers (IOCTL/RESET_CTL) immediately after ARM release.
# Read pmustatus every 20 iterations during 5s wait to detect BBPLL startup.
# Goal: determine if EFI programmed PLL dividers, confirm ARM state at release.
#
# Usage: sudo ./test-staged-reset.sh [stage]
# Default stage is 0 (full 5000ms wait loop)
set -e

STAGE="${1:-0}"
WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test.40.stage${STAGE}"

echo "=== test.40: pllcontrol diagnostic + ARM wrapper state — stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: watchdog reset; pllcontrol[0..5] + ARM wrapper diagnostic; periodic pmustatus" | tee -a "$LOG" ;;
    *) echo "ERROR: Invalid stage (use 0)" | tee -a "$LOG"; exit 1 ;;
esac
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) — test.40 ===" | tee -a "$LOG"
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
echo "*** test.40: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG" | tee -a "$LOG"
