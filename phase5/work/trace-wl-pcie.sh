#!/usr/bin/env bash
# Trace what the wl driver sets up in PCIe config space and BAR regions
# before and after loading. This tells us what our brcmfmac is missing.
# Usage: sudo ./trace-wl-pcie.sh
set -e

PCI_DEV="0000:03:00.0"
BRIDGE_DEV="0000:00:1c.2"  # upstream bridge
OUT_DIR="$(cd "$(dirname "$0")" && pwd)/../logs/wl-trace"

mkdir -p "$OUT_DIR"

echo "=== wl driver PCIe trace ==="
echo "Output: $OUT_DIR"

# Helper: dump PCI config space
dump_pci_config() {
    local dev=$1 label=$2
    echo "--- $label: $dev config space ---"
    # Full 256-byte config space
    xxd /sys/bus/pci/devices/$dev/config > "$OUT_DIR/${label}_${dev//[:.]/_}_config.hex"
    # Human-readable
    cat /sys/bus/pci/devices/$dev/config | od -A x -t x1z > "$OUT_DIR/${label}_${dev//[:.]/_}_config.od"
    echo "  Saved to $OUT_DIR/${label}_${dev//[:.]/_}_config.hex"
}

# Helper: dump BAR info
dump_bar_info() {
    local dev=$1 label=$2
    echo "--- $label: $dev resource info ---"
    cat /sys/bus/pci/devices/$dev/resource > "$OUT_DIR/${label}_${dev//[:.]/_}_resource.txt"
    # Read PCI command register
    local cmd=$(setpci -s ${dev#0000:} COMMAND 2>/dev/null || od -A n -t x2 -j 4 -N 2 /sys/bus/pci/devices/$dev/config)
    echo "  PCI COMMAND: $cmd"
    echo "$cmd" > "$OUT_DIR/${label}_${dev//[:.]/_}_command.txt"
}

# Helper: capture dmesg
capture_dmesg() {
    local label=$1
    dmesg > "$OUT_DIR/${label}_dmesg.txt"
    echo "  dmesg saved"
}

# Ensure no driver is bound
if [ -e "/sys/bus/pci/devices/$PCI_DEV/driver" ]; then
    CURRENT=$(basename "$(readlink /sys/bus/pci/devices/$PCI_DEV/driver)")
    echo "Unbinding $CURRENT from $PCI_DEV..."
    echo "$PCI_DEV" > "/sys/bus/pci/devices/$PCI_DEV/driver/unbind" 2>/dev/null || true
    sleep 1
fi

echo ""
echo "=== Phase 1: Pre-wl state ==="
dmesg -C
dump_pci_config "$PCI_DEV" "pre"
dump_pci_config "$BRIDGE_DEV" "pre"
dump_bar_info "$PCI_DEV" "pre"

echo ""
echo "=== Phase 2: Loading wl driver ==="

# Set up ftrace to capture PCI config writes
echo 0 > /sys/kernel/tracing/tracing_on
echo function_graph > /sys/kernel/tracing/current_tracer
# Trace pci config access functions
echo 'pci_bus_read_config*' > /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_bus_write_config*' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_enable_msi*' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_set_master' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_clear_master' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_enable_device*' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'request_irq' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'dma_alloc*' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo 'pci_alloc*' >> /sys/kernel/tracing/set_ftrace_filter 2>/dev/null || true
echo > /sys/kernel/tracing/trace  # clear buffer
echo 1 > /sys/kernel/tracing/tracing_on

echo "ftrace enabled, loading wl..."
modprobe wl 2>/dev/null || insmod /run/booted-system/kernel-modules/lib/modules/6.12.80/kernel/net/wireless/wl.ko
echo "wl loaded, waiting 5s for init..."
sleep 5

echo 0 > /sys/kernel/tracing/tracing_on
cat /sys/kernel/tracing/trace > "$OUT_DIR/ftrace_wl_load.txt"
echo nop > /sys/kernel/tracing/current_tracer
echo "  ftrace captured: $(wc -l < "$OUT_DIR/ftrace_wl_load.txt") lines"

echo ""
echo "=== Phase 3: Post-wl state ==="
dump_pci_config "$PCI_DEV" "post"
dump_pci_config "$BRIDGE_DEV" "post"
dump_bar_info "$PCI_DEV" "post"
capture_dmesg "post_wl"

# Check what wl set up
echo ""
echo "=== Phase 4: Analysis ==="

# Diff config spaces
echo "--- Device config space diff ---"
diff "$OUT_DIR/pre_${PCI_DEV//[:.]/_}_config.hex" \
     "$OUT_DIR/post_${PCI_DEV//[:.]/_}_config.hex" > "$OUT_DIR/device_config_diff.txt" 2>&1 || true
cat "$OUT_DIR/device_config_diff.txt"

echo ""
echo "--- Bridge config space diff ---"
diff "$OUT_DIR/pre_${BRIDGE_DEV//[:.]/_}_config.hex" \
     "$OUT_DIR/post_${BRIDGE_DEV//[:.]/_}_config.hex" > "$OUT_DIR/bridge_config_diff.txt" 2>&1 || true
cat "$OUT_DIR/bridge_config_diff.txt"

# Check IRQ info
echo ""
echo "--- IRQ assignment ---"
cat /proc/interrupts | grep -i "wl\|brcm\|03:00" || echo "  (no matching interrupts)"

# Check DMA allocations
echo ""
echo "--- IOMMU/DMA info ---"
ls /sys/bus/pci/devices/$PCI_DEV/iommu* 2>/dev/null || echo "  (no IOMMU)"
cat /sys/bus/pci/devices/$PCI_DEV/dma_mask_bits 2>/dev/null || echo "  (no dma_mask_bits)"

# Check if wl set up any network interfaces
echo ""
echo "--- Network interfaces ---"
ip link show 2>/dev/null | grep -A2 "wl\|eth" || echo "  (none)"

echo ""
echo "=== Phase 5: Unloading wl ==="
rmmod wl 2>/dev/null || true
sleep 1

dump_pci_config "$PCI_DEV" "post_unload"
capture_dmesg "post_unload"

echo ""
echo "=== Complete ==="
echo "Key files to examine:"
echo "  $OUT_DIR/device_config_diff.txt   — what wl changed in device config"
echo "  $OUT_DIR/bridge_config_diff.txt   — what wl changed in bridge config"
echo "  $OUT_DIR/ftrace_wl_load.txt       — PCI function calls during wl load"
echo "  $OUT_DIR/post_wl_dmesg.txt        — kernel messages"
