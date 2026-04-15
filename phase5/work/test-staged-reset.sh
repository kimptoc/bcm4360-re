#!/usr/bin/env bash
# Phase 5.2 test.77: PCIe2 BAC register clear before ARM — fix pcidongle_probe hang
#
# test.76 RESULT: SURVIVED. ASPM theory DISPROVED.
#   ASPM disabled on EP before ARM release — firmware STILL froze at T+2s.
#   Same pattern as test.75: console_ptr updated at T+2s, then silence.
#   Post-timeout crash: select_core(PCIE2) after FW started → known dangerous (test.66).
#   ASPM was NOT the root cause of pcidongle_probe hang.
#
# test.77 HYPOTHESIS: stale PCIe2 BAC registers survive watchdog reset.
#   INTMASK/MAILBOXMASK/H2D_MAILBOX_0/H2D_MAILBOX_1 from prior session
#   confuse firmware's hnd_pcie2_init (tight poll loop or wrong state machine).
#   Fix: read + log all key PCIe2 BAC regs; clear them before ARM release.
#
# test.77 KEY CHANGES from test.76:
#   1. Read all PCIe2 BAC registers (INTMASK, MBINT, MBMASK, H2D0, H2D1) pre-ARM.
#   2. Clear INTMASK, MBMASK, H2D_MAILBOX_0, H2D_MAILBOX_1 to 0 before ARM.
#   3. Fixed post-timeout crash: removed select_core(PCIE2), added masking to exc dump.
#   4. ASPM disable kept (harmless, belt-and-suspenders).
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
LOG="$LOG_DIR/test.77.stage${STAGE}"

echo "=== test.77: PCIe2 BAC reg clear + stale state fix --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; NVRAM; NVRAM token kept; ASPM disabled before ARM; PCIe2 BAC regs read+cleared (INTMASK/MBMASK/H2D0/H2D1→0) before ARM; pci_set_master before ARM; activate() preserves BusMaster; 30s masking+FW wait; TCM scan every 2s (from T+200ms); FULL console dump at T+3s; BSS dump 0x9D0A0..0x9D500 at T+5s; olmsg dump at T+20s; NO BAR0 writes; TIMEOUT: TCM[0..3F] dump with masking; RP restore on timeout" | tee -a "$LOG" ;;
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

# Load module with staged reset
echo "" | tee -a "$LOG"
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.77 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"

echo "Module loaded. Waiting 65s (30s FW wait + 35s margin for TIMEOUT path)..." | tee -a "$LOG"
echo "(test.77: ASPM disabled + PCIe2 BAC regs cleared before ARM; 30s wait; TCM scan every 2s from T+200ms; console dump at T+3s; BSS dump 0x9D0A0..0x9D500 at T+5s; TIMEOUT → TCM[0..3F] with masking + RP restore)" | tee -a "$LOG"
sleep 65

# Capture results
echo "" | tee -a "$LOG"
echo "=== Post-test dmesg ===" | tee -a "$LOG"
dmesg | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "=== Module state ===" | tee -a "$LOG"
lsmod | grep brcm | tee -a "$LOG" || echo "  (brcmfmac not loaded)" | tee -a "$LOG"

echo "" | tee -a "$LOG"
echo "*** test.77: PC SURVIVED stage=$STAGE! ***" | tee -a "$LOG"
echo "Log saved to $LOG (test.77)" | tee -a "$LOG"
