#!/usr/bin/env bash
# Phase 5.2 test.103: targeted LR-slot reads + deep sub-frame sweep
#
# test.102 RESULT: 16-word sweep 0x9FE20..0x9FE5C returned all high-entropy
#   words (>0x70000), NO plausible LRs. Post-analysis: test.97's "frames
#   near 0x9FE40" was actually RTE banner ASCII in the console ring, not
#   live stack. True stack located via offline reset-path disasm:
#   SP_init = 0x9D0A0, stack = [0x9A144..0x9D0A0) growing down.
#
# test.103 PLAN: read seven predicted LR-slot addresses directly (A..G
#   for frames main → c_init → fn 0x63b38 → wl_probe → wlc_attach →
#   fn 0x67358 → fn 0x670d8) and compare against expected values from
#   phase5/notes/test103_lr_table_shallow.md. Plus a 7-word deep sweep
#   below fn 0x670d8's frame to catch the saved LR of the currently-hung
#   sub-call (identifies which 0x670d8 body BL is stuck). Plus 2
#   calibration reads at between-LR slots (should NOT be LR-shaped;
#   if they are, frame-size prediction is off by 4B).
#
# Frame A's LR is EVEN (0x320) — literal load `mov lr, r0` in boot path,
#   not bl/blx, so Thumb bit NOT set. Match exactly; odd-bit filter
#   would reject it. Frames B..G are from bl/blx and satisfy odd-bit.
#
# Pre-registered failure signatures (see RESUME_NOTES.md):
#   ≥5/7 match + sweep hit    → Success, identifies hang sub-BL
#   calibration slot IS LR    → Offset drift, re-disasm that prologue
#   A/B match, C+ miss        → Hang pre-fn 0x63b38 OR prologue wrong
#   all miss                  → SP_init wrong OR stack trashed
#
# Probe count: 19 reads @ 1200ms FW-wait
#   (2 regression + 7 LR + 2 cal + 7 sweep + 1 sanity). Same budget
#   as test.102 (known safe).
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
LOG="$LOG_DIR/test.111.stage${STAGE}"

echo "=== test.111: core list via brcmf_chip_get_core (no MMIO) --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: test.111 — replaced test.110 BAR0 11-slot sweep (which hard-crashed, no logs) with brcmf_chip_get_core() lookups for 9 known core IDs. Zero new MMIO. Expect core list in dmesg + existing EFI/PMU/pllcontrol lines, no crash." | tee -a "$LOG" ;;
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

# Load module with staged reset + skip_arm=1
echo "" | tee -a "$LOG"
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE, bcm4360_skip_arm=1) --- test.111 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
# test.109: bcm4360_skip_arm=1 prevents ARM release so FW never runs =>
#   box does not crash => enum output is safely in kernel ringbuffer.
# insmod will return -ENODEV (clean abort) because the probe bails out
#   after the TCM dump in the skip_arm branch. That's expected.
set +e
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE" bcm4360_skip_arm=1
INSMOD_RC=$?
set -e
echo "insmod returned rc=$INSMOD_RC (expected: non-zero; skip_arm aborts probe cleanly)" | tee -a "$LOG"

# Capture dmesg directly from /dev/kmsg — no journald batching, no sleep
# needed since no crash is expected.
echo "" | tee -a "$LOG"
echo "=== dmesg capture (kernel ring buffer) ===" | tee -a "$LOG"
dmesg -k --nopager 2>&1 | grep -iE "BCM4360|brcmfmac" | tee -a "$LOG"
sync
echo "=== Capture complete ===" | tee -a "$LOG"
sync

# Remove the aborted-probe module cleanly so next test is repeatable
if lsmod | grep -q brcmfmac; then
    echo "Cleaning up brcmfmac..." | tee -a "$LOG"
    rmmod brcmfmac 2>/dev/null || true
fi
