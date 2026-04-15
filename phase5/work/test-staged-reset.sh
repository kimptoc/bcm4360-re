#!/usr/bin/env bash
# Phase 5.2 test.53: secondary bus reset + watchdog active servicing
#
# test.52 INSTANT CRASH finding:
#   Crash during chip enumeration BAR0 MMIO reads, after get_resource but before
#   reset_device. Root cause: tests 50/51 left BCM4360 in bad state where BAR0 MMIO
#   reads cause PCIe Completion Timeout → NMI → host crash.
#
# test.53 CHANGES (two independent parts):
#   1. Secondary bus reset (SBR) via upstream bridge in brcmf_pcie_probe() BEFORE chip_attach.
#      Resets BCM4360 AXI fabric without needing BAR0 MMIO; uses only PCIe config cycles.
#      After SBR + pci_restore_state: device should be in clean power-on-reset state.
#   2. BAR0 MMIO probe read in brcmf_pcie_get_resource() after ioremap: reads CC@0x18000000.
#      0xffffffff = device dead; valid value = chip alive; if no log line = MMIO itself crashes.
#   3. Watchdog active servicing in poll loop (unchanged from test.52 design).
#
# Expected outcomes:
#   - SBR logged + BAR0 probe prints valid value → SBR works, chip alive, proceed to poll
#   - PASS (5s timeout): watchdog CONFIRMED as crash mechanism for tests 43-49
#   - CRASH ~49 iters: watchdog not the cause
#   - INSTANT CRASH after SBR logged: SBR didn't fix it → power cycle needed
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
LOG="$LOG_DIR/test.53.stage${STAGE}"

echo "=== test.53: SBR + BAR0 probe + watchdog active servicing — stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR before chip_attach; BAR0 probe read; BBPLL; watchdog serviced every 10ms; ARM release" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) — test.53 ===" | tee -a "$LOG"
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
echo "*** test.53: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.53)" | tee -a "$LOG"
