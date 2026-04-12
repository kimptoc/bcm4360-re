#!/usr/bin/env bash
# BCM4360 brcmfmac module test script
# Usage: sudo ./test.sh
set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
DIAG_DIR="$WORK_DIR/../../"
MODULE="$WORK_DIR/brcmfmac.ko"
WCC_MODULE="$WORK_DIR/brcmfmac-wcc.ko"

# Find next available diag file number
DIAG_NUM=1
while [ -f "$DIAG_DIR/diag.$DIAG_NUM" ]; do
    DIAG_NUM=$((DIAG_NUM + 1))
done
DIAG_FILE="$DIAG_DIR/diag.$DIAG_NUM"

echo "=== BCM4360 brcmfmac test script ==="
echo "Module:    $MODULE"
echo "Output:    $DIAG_FILE"
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
for mod in brcmfmac-wcc brcmfmac wl; do
    if lsmod | grep -q "^${mod//-/_}"; then
        echo "  Removing $mod..."
        rmmod "$mod" 2>/dev/null || true
        sleep 1
    else
        echo "  $mod not loaded, skipping"
    fi
done

# Step 2: Ensure brcmutil is loaded
echo "--- Step 2: Loading dependencies ---"
if lsmod | grep -q "^brcmutil"; then
    echo "  brcmutil already loaded"
else
    echo "  Loading brcmutil..."
    modprobe brcmutil
fi

# Step 3: Record dmesg position
DMESG_BEFORE=$(dmesg | wc -l)

# Step 4: Load modules
echo "--- Step 3: Loading brcmfmac ---"
insmod "$MODULE"
echo "  brcmfmac loaded OK"

if [ -f "$WCC_MODULE" ]; then
    insmod "$WCC_MODULE"
    echo "  brcmfmac-wcc loaded OK"
fi

# Step 5: Wait for firmware loading and probe
echo "--- Step 4: Waiting 5s for probe to complete ---"
sleep 5

# Step 6: Capture output
echo "--- Step 5: Capturing dmesg ---"
dmesg | tail -n +$((DMESG_BEFORE + 1)) > "$DIAG_FILE"
echo "  Saved to $DIAG_FILE"

# Step 7: Show relevant output
echo ""
echo "=== dmesg output (brcm lines) ==="
grep -i brcm "$DIAG_FILE" || echo "  (no brcm lines found)"

echo ""
echo "=== Network interfaces ==="
ip link show | grep -A1 wl || echo "  (no wl* interfaces found)"

echo ""
echo "=== Module status ==="
lsmod | grep brcm || true

echo ""
echo "Done. Full output in $DIAG_FILE"
