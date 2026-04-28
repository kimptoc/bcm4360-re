#!/usr/bin/env bash
# Fire T305 (pre-set_active MBM with select_core(PCIE2)) + T306 (PCI cfg dump).
# Single combined fire — independent surfaces, both print SUMMARY at pre-
# set_active timing well before any wedge.
#
# Substrate prerequisites (per CLAUDE.md pre-test checklist):
#   - rebooted into the clean boot config (wl blacklisted, mitigations restored)
#   - lspci -vvv -s 03:00.0 shows MAbort-, CommClk+
#   - brcmfmac.ko built with T305 + T306 (rebuild if not)
#
# Usage: sudo phase5/work/fire-t305-t306.sh

set -e

WORK_DIR="$(cd "$(dirname "$0")" && pwd)"
FMAC_DIR="$WORK_DIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
LOG_DIR="$WORK_DIR/../logs"
PCI_DEV="03:00.0"

# Find next log number — T305 + T306 = test.305
LOG="$LOG_DIR/test.305.journalctl.txt"

echo "=== Fire T305 + T306 ==="
echo "Log: $LOG"
echo ""

# Sanity: brcmfmac.ko must exist + have T305/T306 symbols
for mod in brcmfmac.ko wcc/brcmfmac-wcc.ko; do
    if [ ! -f "$FMAC_DIR/$mod" ]; then
        echo "ERROR: $FMAC_DIR/$mod not found — run make first"
        exit 1
    fi
done

if ! modinfo "$FMAC_DIR/brcmfmac.ko" | grep -q 'bcm4360_test305_premask_with_select'; then
    echo "ERROR: brcmfmac.ko missing T305 param — rebuild required"
    exit 1
fi
if ! modinfo "$FMAC_DIR/brcmfmac.ko" | grep -q 'bcm4360_test306_cfg_dump'; then
    echo "ERROR: brcmfmac.ko missing T306 param — rebuild required"
    exit 1
fi
echo "Module has T305 + T306 params: OK"

# Substrate check
echo ""
echo "=== PCIe state ==="
lspci -vvv -s "$PCI_DEV" 2>/dev/null | grep -E 'MAbort|CommClk|LnkSta|LnkCtl' || true

echo ""
echo "=== Cmdline (verify mitigations=off NOT present) ==="
grep -oE 'mitigations=[a-z]+' /proc/cmdline || echo "  mitigations: default (good)"

# Unbind any existing driver from BCM4360
if [ -e "/sys/bus/pci/devices/0000:$PCI_DEV/driver" ]; then
    CURRENT=$(basename "$(readlink /sys/bus/pci/devices/0000:$PCI_DEV/driver)")
    echo "Unbinding $CURRENT from $PCI_DEV..."
    echo "0000:$PCI_DEV" > "/sys/bus/pci/devices/0000:$PCI_DEV/driver/unbind" 2>/dev/null || true
    sleep 1
fi

# Remove any loaded brcmfmac
if lsmod | grep -q brcmfmac; then
    echo "Removing loaded brcmfmac stack..."
    rmmod brcmfmac-wcc 2>/dev/null || true
    rmmod brcmfmac-cyw 2>/dev/null || true
    rmmod brcmfmac-bca 2>/dev/null || true
    rmmod brcmfmac 2>/dev/null || true
    sleep 1
fi

# Pre-test BAR0 MMIO check (CTO vs UR distinguisher — see test-brcmfmac.sh comments)
echo ""
echo "Pre-test: BAR0 MMIO probe..."
T_START=$(date +%s%3N)
set +e
dd if=/sys/bus/pci/devices/0000:$PCI_DEV/resource0 bs=4 count=1 of=/dev/null 2>/dev/null
DD_EXIT=$?
set -e
T_END=$(date +%s%3N)
T_MS=$((T_END - T_START))

if [ $DD_EXIT -eq 0 ]; then
    echo "BAR0 MMIO OK — device responding."
elif [ $T_MS -lt 40 ]; then
    echo "BAR0 MMIO: UR (${T_MS}ms) — alive, SBR will fix. Proceeding."
else
    echo "FATAL: BAR0 MMIO CTO (${T_MS}ms). Recover via battery drain."
    exit 1
fi

# Fire
echo ""
echo "=== Loading brcmfmac with T305 + T306 + supporting probes ==="
dmesg -C  # Clear kernel log for clean capture

modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true

# Param choice rationale:
#   test276=1 — gates the pre-set_active block where both T305 and T306 fire
#   test277=1 — console decoder (precondition for T278)
#   test278=1 — periodic console reads at t+500ms..t+90s (so we can see if fw wakes)
#   test298=1 — ISR-list walk (baseline; useful to compare with prior fires)
#   test305=1 — THE PROBE: pre-set_active MBM enable WITH select_core(PCIE2)
#   test306=1 — THE PROBE: PCI cfg dump 0x40..0xFF at 3 stages
# Explicitly NOT setting:
#   test284=0 — would write MBM at pre-set_active WITHOUT select_core; conflict with T305
#   test280=0 — would write MBM at post-set_active without select_core; same conflict
#   test300=0 — OOB Router pending read (shifts wedge bracket per row 104)
#   test304=0 — gate-1 OOB Router write probe (already done T304)
echo "insmod brcmfmac.ko \\"
echo "    bcm4360_test276_shared_info=1 \\"
echo "    bcm4360_test277_console_decode=1 \\"
echo "    bcm4360_test278_console_periodic=1 \\"
echo "    bcm4360_test298_isr_walk=1 \\"
echo "    bcm4360_test305_premask_with_select=1 \\"
echo "    bcm4360_test306_cfg_dump=1"

insmod "$FMAC_DIR/brcmfmac.ko" \
    bcm4360_test276_shared_info=1 \
    bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test298_isr_walk=1 \
    bcm4360_test305_premask_with_select=1 \
    bcm4360_test306_cfg_dump=1

insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo ""
echo "Modules loaded. Sleeping 150s for full T276/T278 ladder..."
sleep 150

# Capture
echo ""
echo "=== Capturing dmesg → $LOG ==="
dmesg > "$LOG"

# Quick highlight of the key SUMMARY lines
echo ""
echo "=== T305 SUMMARY ==="
grep -E 'BCM4360 test\.305:.*SUMMARY|BCM4360 test\.305:.*verdict' "$LOG" || echo "  (no T305 SUMMARY found — check if pre-set_active block ran)"

echo ""
echo "=== T306 SUMMARY (cfg94/B4/B8 at 3 stages) ==="
grep -E 'BCM4360 test\.306:.*SUMMARY' "$LOG" || echo "  (no T306 SUMMARY found)"

echo ""
echo "=== T306 cfg[0xA0..0xBC] line (highlights 0xB4+0xB8) ==="
grep -E 'BCM4360 test\.306:.*cfg\[0xA0\.\.0xBC\]' "$LOG" || echo "  (no T306 cfg dump found)"

echo ""
echo "=== Console wr_idx at end-of-poll ==="
grep -E 'wr_idx=[0-9]+' "$LOG" | tail -3

echo ""
echo "=== ISR list count via T298 (last sample) ==="
grep -E 'test\.298:.*head=' "$LOG" | tail -2

echo ""
echo "Full log: $LOG ($(wc -l < "$LOG") lines)"
echo "Network state:"
ip link show 2>/dev/null | grep -A1 'wl\|wlan' || echo "  (no wireless interface)"
echo ""
echo "Module state:"
lsmod | grep brcm || echo "  (brcmfmac unloaded)"
