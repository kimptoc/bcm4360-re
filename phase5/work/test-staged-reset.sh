#!/usr/bin/env bash
# Phase 5.2 test.101: single-breadcrumb probe of *0x62e20 (upstream-hang fingerprint)
#
# test.100 RESULT (Case C'): wait-struct fields = pre-init garbage,
#   byte-stable across T+200/400/800ms → fn 0x1624c NEVER ran. Hang is
#   strictly UPSTREAM of the PHY spin-loop, inside wl_probe.
#
# test.100 also regressed at ~1.9s (machine crashed between T+1800 and
# T+2000ms) — ~30–90ms of extra read_ram32 latency nudged the masking
# loop past a PCIe periodic event. test.101 reduces probe count AND
# shortens FW-wait cap 2000→1200ms to widen the safety margin.
#
# test.101 PLAN: single read of TCM[0x62e20] at T+200ms (+ 4 pointer
#   controls). fn 0x68a68 writes wl_ctx ptr to 0x62e20 at PC 0x68bbc,
#   8 bytes before bl 0x1ab50 (PHY descent). Image at 0x62e20 = 0;
#   only attach-path writer is fn 0x68a68@0x68bbc (fn 0x681bc@0x681cc
#   is detach-path, does not run during probe).
#   Matrix:
#     *0x62e20 == 0      → fn 0x68a68 hung before 0x68bbc
#                         (Case U1: in its prefix, or in wl_probe's
#                          other 5 sub-BLs before bl 0x68a68)
#     *0x62e20 != 0      → fn 0x68a68 reached 0x68bbc, hang is in
#                         bl 0x1ab50 or one of its pre-spin sub-BLs
#                         (fn 0x16476 / fn 0x162fc body; not 0x1624c)
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
LOG="$LOG_DIR/test.101.stage${STAGE}"

echo "=== test.101: single breadcrumb *0x62e20 --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; NVRAM; NVRAM token kept; ASPM disabled before ARM; named reg clears + 0x100-0x108/0x1E0; MSI enabled + IRQ handler before ARM; pci_set_master before ARM; 1.2s masking+FW wait (shortened from 2s); TEST.101 PROBES: control pointers {0x9d000,0x58f08,0x62ea8,0x62a14} + breadcrumb TCM[0x62e20] at T+200ms only; free_irq+disable_msi+RP restore" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.101 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"
