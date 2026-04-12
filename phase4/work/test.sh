#!/usr/bin/env bash
# BCM4360 offload firmware communication test script
# Usage: sudo ./test.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="$WORK_DIR/../logs"
MODULE="$WORK_DIR/bcm4360_test.ko"

# Create log dir if needed
mkdir -p "$LOG_DIR"

# Find next available log file number
LOG_NUM=1
while [ -f "$LOG_DIR/test.$LOG_NUM" ]; do
    LOG_NUM=$((LOG_NUM + 1))
done
LOG_FILE="$LOG_DIR/test.$LOG_NUM"

echo "=== BCM4360 offload FW communication test ==="
echo "Module:    $MODULE"
echo "Output:    $LOG_FILE"
echo ""

# Check we're root
if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: must run as root (sudo ./test.sh)"
    exit 1
fi

# Check module exists
if [ ! -f "$MODULE" ]; then
    echo "ERROR: $MODULE not found — run 'make' first"
    exit 1
fi

# Step 1: Unload conflicting modules
echo "--- Step 1: Unloading existing modules ---"
for mod in brcmfmac-wcc brcmfmac wl bcm4360_test; do
    if lsmod | grep -q "^${mod//-/_}"; then
        echo "  Removing $mod..."
        rmmod "$mod" 2>/dev/null || true
        sleep 1
    else
        echo "  $mod not loaded, skipping"
    fi
done

# Step 2: Record dmesg position
echo "--- Step 2: Recording dmesg position ---"
DMESG_BEFORE=$(dmesg | wc -l)

# Step 3: Load test module
echo "--- Step 3: Loading bcm4360_test ---"
insmod "$MODULE"
echo "  bcm4360_test loaded OK"

# Step 4: Wait for firmware download, ARM release, and init poll (2s timeout + margin)
echo "--- Step 4: Waiting 5s for test to complete ---"
sleep 5

# Step 5: Capture output
echo "--- Step 5: Capturing dmesg ---"
dmesg | tail -n +$((DMESG_BEFORE + 1)) > "$LOG_FILE"
echo "  Saved to $LOG_FILE"

# Step 6: Show relevant output
echo ""
echo "=== dmesg output (bcm4360 lines) ==="
grep -i "bcm4360" "$LOG_FILE" || echo "  (no bcm4360 lines found)"

echo ""
echo "=== All new dmesg ==="
cat "$LOG_FILE"

echo ""
echo "=== Module status ==="
lsmod | grep bcm4360 || echo "  (bcm4360_test not loaded — may have failed to probe)"

echo ""
echo "Done. Full output in $LOG_FILE"
echo "To unload: sudo rmmod bcm4360_test"
