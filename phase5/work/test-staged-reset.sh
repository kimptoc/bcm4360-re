#!/usr/bin/env bash
# Phase 5.2 test.102: stack-locator dense-narrow sweep (LR chain fingerprint)
#
# test.101 RESULT (Case 0): *0x62e20 == 0 → fn 0x68a68 (wlc_attach) hung
#   UPSTREAM of 0x68bbc. Offline disasm of body + 6 body-BL targets found
#   no discriminating fixed-TCM breadcrumb exists in wlc_attach descent
#   (all stores r4/r3-relative into alloc'd structs). The first body BL
#   (bl 0x67f2c @ 0x68aca) is a 4-insn tail-call trampoline to 0x67358 —
#   the same si_attach descent already entered once from pciedngl_probe.
#
# test.102 PLAN: pivot to stack walk. ARM Thumb `bl` pushes LR on stack
#   via `push {..., lr}` prologues. While CPU is stuck mid-call, the
#   live frame chain persists in RAM. test.97 located active frames
#   near 0x9FE40. Sweep 64B there, filter for odd-bit words in
#   [0x800..0x70000] → LR candidates. Each maps (via phase5/notes/
#   test102_lr_table.md) to a specific BL site.
#   Confirmation criteria:
#     ≥2 table-LRs chained (e.g. 0x68acf + 0x6739d) → STRONG
#     1 table-LR                                    → MODERATE
#     0 table-LRs                                   → relocate sweep in test.103
#
# Probe count: 19 reads @ 1200ms FW-wait (2 regression + 16 stack + 1 sanity).
# 1.5× test.101's clean 5-read baseline, well below test.100's 13-read regression.
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
LOG="$LOG_DIR/test.102.stage${STAGE}"

echo "=== test.102: stack-locator dense-narrow sweep --- stage=$STAGE ===" | tee "$LOG"
echo "Date: $(date)" | tee -a "$LOG"
echo "" | tee -a "$LOG"

case "$STAGE" in
    0) echo "Stage 0: SBR; NVRAM; NVRAM token kept; ASPM disabled before ARM; named reg clears + 0x100-0x108/0x1E0; MSI enabled + IRQ handler before ARM; pci_set_master before ARM; 1.2s masking+FW wait; TEST.102 PROBES: 2 regression {0x9d000,0x62a14} + 16 dense stack words 0x9FE20..0x9FE5C stride 4B + 1 sanity *0x62e20 at T+200ms; free_irq+disable_msi+RP restore" | tee -a "$LOG" ;;
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
echo "=== Loading brcmfmac (bcm4360_reset_stage=$STAGE) --- test.102 ===" | tee -a "$LOG"
sync

dmesg -C
modprobe brcmutil 2>/dev/null || true
modprobe cfg80211 2>/dev/null || true
insmod "$FMAC_DIR/brcmfmac.ko" bcm4360_reset_stage="$STAGE"
insmod "$FMAC_DIR/wcc/brcmfmac-wcc.ko"
