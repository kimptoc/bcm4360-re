#!/usr/bin/env bash
# BCM4360 staged brcmfmac test harness.
#
# Stage 0 keeps ARM halted (bcm4360_skip_arm=1) and is the only safe first
# test after recovery. Stage 1 releases ARM and should only be run after a
# clean stage 0.
#
# Usage: sudo ./test-staged-reset.sh [stage]
# Default stage is 0.
set -e

STAGE="${1:-0}"
WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"
PCI_SLOT="0000:$PCI_DEV"

mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/test.148.stage${STAGE}"

echo "=== test.148: brcmf_core_init/brcmf_pcie_register call-site markers — stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: skip_arm=1 — module_init/register markers; no ARM release if probe reaches firmware path." | tee -a "$LOG" ;;
    1) echo "Stage 1: skip_arm=0 — BBPLL bringup + ARM release. Run only after clean stage 0." | tee -a "$LOG" ;;
    *) echo "ERROR: Invalid stage (use 0 or 1)" | tee -a "$LOG"; exit 1 ;;
esac
echo "(test.148: no new MMIO; adds common/core call-site markers; skips brcmf_dbg in brcmf_pcie_register; test.145 buscore_reset ARM halt remains in place if reached)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

# Pre-test MMIO check — distinguish Completion Timeout (CTO) from
# Unsupported Request (UR). CTO means the endpoint is not completing MMIO
# transactions and insmod can hard-crash the host. UR is fast and recoverable:
# the probe-time SBR path is expected to reset the endpoint before chip_attach.
echo "=== Pre-test BAR0 MMIO guard ===" | tee -a "$LOG"
T_START=$(date +%s%3N)
set +e
dd if="/sys/bus/pci/devices/$PCI_SLOT/resource0" bs=4 count=1 of=/dev/null 2>/dev/null
DD_EXIT=$?
set -e
T_END=$(date +%s%3N)
T_MS=$((T_END - T_START))

if [ "$DD_EXIT" -eq 0 ]; then
    echo "BAR0 MMIO OK (${T_MS}ms) — device responding normally." | tee -a "$LOG"
elif [ "$T_MS" -lt 40 ]; then
    echo "BAR0 MMIO UR/I/O error (${T_MS}ms) — device alive; SBR in probe should fix. Proceeding." | tee -a "$LOG"
else
    echo "FATAL: BAR0 MMIO Completion Timeout (${T_MS}ms) — aborting before insmod." | tee -a "$LOG"
    echo "Recovery: full battery-drain power cycle before retry." | tee -a "$LOG"
    exit 1
fi
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

if [ "$STAGE" -eq 0 ]; then
    SKIP_ARM=1
    WAIT_SECS=12  # test.148: module/core/register markers + existing staged-reset/download diagnostics
else
    SKIP_ARM=0
    WAIT_SECS=35
fi

echo "" | tee -a "$LOG"
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE, bcm4360_skip_arm=$SKIP_ARM) --- test.148 ===" | tee -a "$LOG"
sync

# Start streaming kernel messages to a separate file BEFORE insmod.
# Each line is synced to disk immediately so crashes don't lose messages.
# test.141 used plain ">>" append which went through OS page cache — crash lost all messages.
STREAM_LOG="${LOG}.stream"
echo "=== dmesg stream start: $(date) ===" > "$STREAM_LOG"
sync
stdbuf -oL dmesg -wk 2>/dev/null | while IFS= read -r _dmesg_line; do
    echo "$_dmesg_line" >> "$STREAM_LOG"
    sync
done &
DMESG_PID=$!

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
set +e
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE" bcm4360_skip_arm=$SKIP_ARM
INSMOD_RC=$?
set -e
echo "insmod returned rc=$INSMOD_RC" | tee -a "$LOG"

echo "Waiting ${WAIT_SECS}s for firmware init (streaming to $(basename "$STREAM_LOG"))..." | tee -a "$LOG"
for _i in $(seq 1 "$WAIT_SECS"); do
    sleep 1
    sync
done

# Stop the background stream
kill "$DMESG_PID" 2>/dev/null || true
wait "$DMESG_PID" 2>/dev/null || true
echo "=== dmesg stream end: $(date) ===" >> "$STREAM_LOG"
sync

echo "" | tee -a "$LOG"
echo "=== dmesg snapshot (kernel ring buffer) ===" | tee -a "$LOG"
dmesg -k --nopager 2>&1 | grep -iE "BCM4360|brcmfmac" | tee -a "$LOG"
sync
echo "=== Capture complete ===" | tee -a "$LOG"
sync

# Remove module cleanly
if lsmod | grep -q brcmfmac; then
    echo "Cleaning up brcmfmac..." | tee -a "$LOG"
    rmmod brcmfmac-wcc 2>/dev/null || true
    rmmod brcmfmac 2>/dev/null || true
fi
