#!/usr/bin/env bash
# BCM4360 staged test harness
# Usage: sudo ./test.sh [max_level]
#   Levels: 0=bind, 1=config+wake, 2=BAR0 regs, 3=TCM+FW,
#           4=ARM release (no DMA), 5=full init (DMA+olmsg)
#   Default: auto-advance through 0→1→2→3, stop before 4
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"

# Find setpci/lspci (may not be on PATH in NixOS)
SETPCI=$(command -v setpci 2>/dev/null || find /nix/store -name "setpci" -path "*/bin/*" 2>/dev/null | head -1)
LSPCI=$(command -v lspci 2>/dev/null || find /nix/store -name "lspci" -path "*/bin/*" 2>/dev/null | head -1)
PCI_DEV="03:00.0"
LOG_DIR="$WORK_DIR/../logs"
MODULE="$WORK_DIR/bcm4360_test.ko"
MAX_LEVEL="${1:-auto}"

mkdir -p "$LOG_DIR"

# Find next log number
LOG_NUM=1
while [ -f "$LOG_DIR/test.$LOG_NUM" ]; do
    LOG_NUM=$((LOG_NUM + 1))
done

echo "=== BCM4360 staged test harness ==="
echo "Module:  $MODULE"
echo "Mode:    $MAX_LEVEL"
echo ""

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (sudo ./test.sh)"
    exit 1
fi

if [ ! -f "$MODULE" ]; then
    echo "ERROR: $MODULE not found — run 'make' first"
    exit 1
fi

# Unload conflicting modules
echo "--- Unloading existing modules ---"
for mod in brcmfmac-wcc brcmfmac wl bcm4360_test; do
    if lsmod | grep -q "^${mod//-/_}"; then
        echo "  Removing $mod..."
        rmmod "$mod" 2>/dev/null || true
        sleep 1
    fi
done

# Unbind from bcma-pci-bridge if it claimed the device (happens on cold
# boot without wl). Our module needs direct PCI access, not BCMA bus.
if [ -e "/sys/bus/pci/devices/0000:$PCI_DEV/driver" ]; then
    BOUND_DRV=$(basename "$(readlink /sys/bus/pci/devices/0000:$PCI_DEV/driver)")
    if [ "$BOUND_DRV" != "bcm4360_test" ]; then
        echo "  Unbinding from $BOUND_DRV..."
        echo "0000:$PCI_DEV" > "/sys/bus/pci/devices/0000:$PCI_DEV/driver/unbind" 2>/dev/null || true
        sleep 1
    fi
fi

echo "  Waiting 10s for hardware to quiesce after module unload..."
sleep 10

# Verify device is still visible and healthy on PCI bus
echo "--- PCI device pre-flight check ---"
if [ -n "$LSPCI" ]; then
    $LSPCI -s $PCI_DEV 2>/dev/null || echo "  WARNING: device not visible!"
else
    echo "  (lspci not found, skipping)"
fi

if [ -n "$SETPCI" ]; then
    # Check vendor ID — 0xFFFF means device is gone
    PCI_VID=$($SETPCI -s $PCI_DEV 0x00.w 2>/dev/null || echo "FAIL")
    echo "  Vendor ID = $PCI_VID (expect 14e4)"
    if [ "$PCI_VID" = "ffff" ] || [ "$PCI_VID" = "FAIL" ]; then
        echo "  *** ABORT: device not responding in config space ***"
        echo "  The device may need a full power cycle (reboot) to recover."
        exit 1
    fi

    # Check power state
    PCI_PM=$($SETPCI -s $PCI_DEV 0x4c.w 2>/dev/null || echo "FAIL")
    echo "  PMCSR = $PCI_PM (D0=xx00/xx08, D3=xx03)"

    # Check AER errors
    AER_UNCORR=$($SETPCI -s $PCI_DEV 0x104+4.l 2>/dev/null || echo "FAIL")
    AER_CORR=$($SETPCI -s $PCI_DEV 0x104+16.l 2>/dev/null || echo "FAIL")
    echo "  AER uncorr=$AER_UNCORR corr=$AER_CORR"

    # Clear AER errors before loading module
    if [ "$AER_UNCORR" != "00000000" ] && [ "$AER_UNCORR" != "FAIL" ]; then
        echo "  Clearing AER uncorrectable errors..."
        $SETPCI -s $PCI_DEV 0x104+4.l=$AER_UNCORR 2>/dev/null
    fi
    if [ "$AER_CORR" != "00000000" ] && [ "$AER_CORR" != "FAIL" ]; then
        echo "  Clearing AER correctable errors..."
        $SETPCI -s $PCI_DEV 0x104+16.l=$AER_CORR 2>/dev/null
    fi
else
    echo "  (setpci not found, skipping hardware checks)"
fi

# Install NVRAM file if present and not already installed
NVRAM_SRC="$WORK_DIR/brcmfmac4360-pcie.txt"
NVRAM_DST="/lib/firmware/brcm/brcmfmac4360-pcie.txt"
if [ -f "$NVRAM_SRC" ]; then
    if [ ! -f "$NVRAM_DST" ] || ! cmp -s "$NVRAM_SRC" "$NVRAM_DST"; then
        echo "--- Installing NVRAM file ---"
        cp "$NVRAM_SRC" "$NVRAM_DST"
        echo "  Copied to $NVRAM_DST"
    fi
fi

echo ""

run_level() {
    local level=$1
    local log_file="$LOG_DIR/test.$LOG_NUM"
    local dmesg_before

    echo ""
    echo "=== Level $level ==="
    dmesg_before=$(dmesg | wc -l)

    # Unload if still loaded from previous level
    if lsmod | grep -q "^bcm4360_test"; then
        rmmod bcm4360_test 2>/dev/null || true
        sleep 1
    fi

    echo "  Loading module with max_level=$level..."

    # Use timeout to catch hangs (15s should be plenty)
    if ! timeout 15 insmod "$MODULE" max_level="$level" 2>&1; then
        echo "  *** HANG or FAIL — insmod did not complete in 15s ***"
        dmesg | tail -n +$((dmesg_before + 1)) > "$log_file"
        echo "  dmesg saved to $log_file"
        echo ""
        echo "=== dmesg output ==="
        cat "$log_file"
        return 1
    fi

    # Wait a moment for any deferred work
    sleep 2

    # Capture dmesg
    dmesg | tail -n +$((dmesg_before + 1)) > "$log_file"
    echo "  Log saved to $log_file"

    # Show output
    echo ""
    echo "--- dmesg (level $level) ---"
    cat "$log_file"
    echo "--- end ---"
    echo ""

    # Check for FAIL markers
    if grep -q "FAIL" "$log_file"; then
        echo "  *** Level $level FAILED ***"
        # Check specifically for dead device
        if grep -q "0xFFFFFFFF\|dead\|D3" "$log_file"; then
            echo "  Device appears dead or in D3 power state"
        fi
        return 1
    fi

    # Check for PASS marker
    if grep -q "PASS" "$log_file"; then
        echo "  Level $level PASSED"
        LOG_NUM=$((LOG_NUM + 1))
        return 0
    fi

    echo "  Level $level completed (no explicit PASS/FAIL)"
    LOG_NUM=$((LOG_NUM + 1))
    return 0
}

if [ "$MAX_LEVEL" = "auto" ]; then
    # Auto-advance through levels 0-3 (safe levels)
    for level in 0 1 2 3; do
        if ! run_level "$level"; then
            echo ""
            echo "=== STOPPED at level $level ==="
            echo "Fix the issue and re-run, or try: sudo ./test.sh $level"
            exit 1
        fi
    done
    echo ""
    echo "=== Levels 0-3 PASSED ==="
    echo "Level 4 (ARM release, no DMA): sudo ./test.sh 4"
    echo "Level 5 (full init with DMA):  sudo ./test.sh 5"
else
    run_level "$MAX_LEVEL"
fi

# Cleanup
if lsmod | grep -q "^bcm4360_test"; then
    echo ""
    echo "Unloading module..."
    rmmod bcm4360_test 2>/dev/null || true
fi

echo "Done. Logs in $LOG_DIR/"
