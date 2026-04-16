#!/usr/bin/env bash
# Phase 5.2 test.100: PHY wait-struct field probe (PHY-wait fingerprint check)
#
# test.99 RESULT: pointer sample IDENTICAL across T+200/400/800ms:
#   ctr=0x43b1 d11=0 ws=0x9d0a4 pd=0x58cf0 — firmware frozen by T+200ms.
#   Console ring matched test.80 decode (ChipCommon banner, no post-RTE text).
#   Offline disasm Round 3+4: anchored "wl_probe called" to fn 0x67614;
#   BFS-proved unique path to the test.96 PHY spin-loop goes
#   wl_probe → 0x68a68 → 0x1ab50 → 0x16476 → 0x162fc → 0x1624c.
#
# test.100 PLAN: read wait-struct fields f20/f24/f28 at TCM[*0x62ea8 +
#   0x14/+0x18/+0x1c] at T+200/400/800ms, plus the test.99 control pointer
#   set. Map to matrix:
#     f24=1,f20=1,f28=0 → spin-loop is live freeze (case A)
#     f24=1,f20=0,f28=0 → entered, cancelled exit (case B)
#     f28!=0            → spin completed, hang downstream
#     f24=0             → 0x1624c never entered, upstream hang (case C)
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
LOG="$LOG_DIR/test.100.stage${STAGE}"

echo "=== test.100: PHY wait-struct field probe --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; NVRAM; NVRAM token kept; ASPM disabled before ARM; named reg clears + 0x100-0x108/0x1E0; MSI enabled + IRQ handler before ARM; pci_set_master before ARM; 2s masking+FW wait; TEST.100 PROBES: control pointers {0x9d000,0x58f08,0x62ea8,0x62a14} + wait-struct fields TCM[ws+0x14/0x18/0x1c] at T+200/400/800ms; free_irq+disable_msi+RP restore" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.100 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"
