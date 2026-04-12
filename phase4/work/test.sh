#!/usr/bin/env bash
# BCM4360 staged test harness
# Usage: sudo ./test.sh [max_level]
#   Levels: 0=bind, 1=config+wake, 2=BAR0 regs, 3=full init
#   Default: auto-advance through 0→1→2, stop before 3
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
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

echo "  Waiting 5s for hardware to quiesce..."
sleep 5

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
    # Auto-advance through levels 0-2
    for level in 0 1 2; do
        if ! run_level "$level"; then
            echo ""
            echo "=== STOPPED at level $level ==="
            echo "Fix the issue and re-run, or try: sudo ./test.sh $level"
            exit 1
        fi
    done
    echo ""
    echo "=== Levels 0-2 PASSED ==="
    echo "Level 3 (full init with ARM release) available: sudo ./test.sh 3"
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
