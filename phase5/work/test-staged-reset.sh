#!/usr/bin/env bash
# Phase 5.2 test.48: BusMaster re-enable test — does firmware re-enable DMA?
#
# test.47 CRASHED at iter 19 (~950ms). Key findings:
#   - DEV_LNKSTA=0x1011 CONSTANT through all 19 iters — PCIe link NEVER drops.
#   - No PCIe error escalation: pre-existing CorrErr+UnsupReq+AuxPwr, unchanged.
#   - Sharedram marker unchanged — firmware never completes initialization.
#   - Link is completely stable — crash is NOT from link drop, NOT from error signaling.
#
# test.43 gap: called pci_clear_master() once, then released ARM. BCM4360 firmware
#   has AXI bus access to its own PCIe2 endpoint registers and CAN write PCI_COMMAND
#   bit2 (BusMaster) from the device side. Test.43 never checked BusMaster during iters.
#   IOMMU group 6 is huge (all PCIe bridges + many devices) — no isolation.
#   If firmware re-enables BusMaster and D11 DMA writes to arbitrary physical address
#   (page tables, GDT/IDT), the host CPU triple-faults: instant crash, no journal entry.
#
# test.48 GOAL: log PCI_COMMAND every 10ms, force BusMaster off every iteration.
#   - Sleep reduced to 10ms (crash at ~iter 95 instead of ~19 if same timing)
#   - pci_clear_master() called every iteration AND just before ARM release
#   Expected outcomes:
#     PASS (no crash): firmware was re-enabling BusMaster → DMA confirmed as mechanism
#     CRASH with CMD logged: check if BusMaster was ever 1 before crash
#       If CMD showed BusMaster=1 at any iter → DMA confirmed
#       If CMD always showed BusMaster=0 → DMA definitively ruled out
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
LOG="$LOG_DIR/test.48.stage${STAGE}"

echo "=== test.48: BusMaster re-enable test — stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: BBPLL up; normal firmware; BusMaster cleared every 10ms; ARM release; monitor" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) — test.48 ===" | tee -a "$LOG"
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
echo "*** test.48: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG" | tee -a "$LOG"
