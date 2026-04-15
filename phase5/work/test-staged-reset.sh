#!/usr/bin/env bash
# Phase 5.2 test.57: 2000ms sleep after ARM release + diagnostic reads on BAR0 dead state
#
# test.56 RESULT: CRASH at iter=2 (~2010ms after ARM release).
#   "woke up" logged (survived 2s sleep). iter=1: BAR0_WIN=0x18000000 (config OK),
#   CHIPID=0xffffffff (BAR0 MMIO dead after 2s). Two bugs caused the crash:
#   BUG 1: loop_counter=0; loop_counter-- underflowed to 0xFFFFFFFF → loop continued to iter=2.
#   BUG 2: timeout diagnostics (READCC32) ran with dead BAR0 → crash.
#   Key question: is PCI_COMMAND memory enable still set? Were BAR addresses changed?
#
# test.57 STRATEGY: same 2s sleep; fix bugs; add safe config-space reads on CHIPID=0xffffffff.
#   - Read PCI_COMMAND, BAR0_BASE, BAR2_BASE (config reads, always safe) when BAR0 MMIO dead.
#   - If MEM enable was cleared → firmware reset PCIe config space.
#   - If BAR addresses changed → firmware reconfigured BARs during PCIE2 init.
#   - If MEM enable still set + BARs unchanged → BAR0 MMIO dead for other reason (investigate).
#
# Expected outcomes:
#   - PCI_CMD bit1 (MEM) = 0: firmware cleared memory enable → re-enable and retry (test.58).
#   - BAR0/BAR2 addresses changed: firmware reconfigured BARs → need re-ioremap (test.58).
#   - Both fine but BAR0 dead: device in recovery/post-PCIE2 state → extend sleep (test.58).
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
LOG="$LOG_DIR/test.57.stage${STAGE}"

echo "=== test.57: SBR + 2000ms sleep + BAR0-dead diagnostics --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; BAR0 probe; BBPLL; ARM release; 2000ms sleep; BAR0-dead diagnostics; poll BAR0+BAR2" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.57 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 22s (2s sleep + 5s FW wait loop + 15s diagnostics)..." | tee -a "$LOG"
echo "(test.57: if BAR0 dead, returns -ENODEV immediately after iter=1 config-space diagnostics)" | tee -a "$LOG"
sleep 22

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.57: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.57)" | tee -a "$LOG"
