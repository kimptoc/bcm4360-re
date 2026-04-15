#!/usr/bin/env bash
# Phase 5.2 test.58: 2000ms sleep after ARM release + config-space reads ONLY (no BAR MMIO)
#
# test.57 RESULT: CRASH at iter=1 (~2010ms after ARM release).
#   test.56 iter=1 at ~2010ms: CHIPID=0xffffffff (non-fatal, device silent).
#   test.57 iter=1 at ~2010ms: CHIPID read itself crashed host (fatal PCIe error).
#   Both tests at ~2010ms; outcome timing-dependent — at the sharp edge of PCIE2 init danger window.
#   No PCI_CMD/BAR diagnostic data captured — crashed before those reads.
#
# test.58 STRATEGY: skip all BAR MMIO reads after the 2s sleep.
#   - pci_read_config_* reads are routed via root complex, safe even when BAR MMIO is fatal.
#   - Read PCI_COMMAND, PCI_BASE_ADDRESS_0, PCI_BASE_ADDRESS_2, BRCMF_PCIE_BAR0_WINDOW.
#   - Log and return -ENODEV. No MMIO polling loop.
#
# Expected outcomes (config state 2s after ARM release):
#   - PCI_CMD bit1 (MEM) = 0: firmware cleared memory enable → firmware reset config space.
#   - BAR0_BASE != 0xb0600004: firmware reconfigured BARs during PCIE2 init.
#   - BAR2_BASE != 0xb0400004: same for BAR2 (BAR2 type=64-bit, so bit2+bit1=0b10 → +4).
#   - BAR0_WIN != 0x18000000: firmware changed the window register.
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
LOG="$LOG_DIR/test.58.stage${STAGE}"

echo "=== test.58: SBR + 2000ms sleep + config-space only (no BAR MMIO) --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; BAR0 probe; BBPLL; ARM release; 2000ms sleep; config-space only (no BAR MMIO)" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.58 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 10s (2s sleep + fast return after config reads)..." | tee -a "$LOG"
echo "(test.58: returns -ENODEV immediately after config-space reads, no MMIO polling)" | tee -a "$LOG"
sleep 10

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.58: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.58)" | tee -a "$LOG"
