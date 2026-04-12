#!/usr/bin/env bash
#
# Build patched brcmfmac module with BCM4360 support
#
# This script:
# 1. Fetches the matching kernel source from kernel.org
# 2. Applies our BCM4360 patches
# 3. Builds just the brcmfmac module against the running kernel's config
# 4. Outputs the .ko file ready for testing
#
# Usage: nix-shell -p gnumake gcc bc flex bison pkg-config openssl elfutils perl --run "bash phase3/scripts/build-module.sh"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PHASE3_DIR="$PROJECT_DIR/phase3"
OUTPUT_DIR="$PHASE3_DIR/output"
WORK_DIR="$PHASE3_DIR/work"

KERNEL_VERSION=$(uname -r | sed 's/-.*//')
KERNEL_MAJOR=$(echo "$KERNEL_VERSION" | cut -d. -f1,2)

echo "=========================================="
echo "BCM4360 brcmfmac Module Builder"
echo "=========================================="
echo "Running kernel: $(uname -r)"
echo "Kernel version: $KERNEL_VERSION"
echo "Kernel major: $KERNEL_MAJOR"
echo ""

# Find kernel build directory
KBUILD=""
for d in /lib/modules/$(uname -r)/build /nix/store/*linux-$(uname -r)-dev*/lib/modules/$(uname -r)/build /nix/store/*linux-*-dev*/lib/modules/*/build; do
    if [ -f "$d/Makefile" ] 2>/dev/null; then
        KBUILD="$d"
        break
    fi
done

if [ -z "$KBUILD" ]; then
    # Try to find any matching kernel dev
    KBUILD=$(find /nix/store -maxdepth 1 -name "*linux-6.12*-dev" -type d 2>/dev/null | head -1)
    if [ -n "$KBUILD" ]; then
        KBUILD="$KBUILD/lib/modules/$(ls "$KBUILD/lib/modules/")/build"
    fi
fi

echo "Kernel build dir: $KBUILD"

if [ ! -f "$KBUILD/Makefile" ]; then
    echo "ERROR: Cannot find kernel build directory"
    echo "Try: nix-build '<nixpkgs>' -A linuxPackages.kernel.dev"
    exit 1
fi

KBUILD_VERSION=$(make -s -C "$KBUILD" kernelversion 2>/dev/null || echo "unknown")
echo "Kernel build version: $KBUILD_VERSION"
echo ""

# Fetch kernel source for the brcmfmac driver
mkdir -p "$WORK_DIR"

TARBALL_URL="https://cdn.kernel.org/pub/linux/kernel/v6.x/linux-${KBUILD_VERSION}.tar.xz"
TARBALL="$WORK_DIR/linux-${KBUILD_VERSION}.tar.xz"
SRCDIR="$WORK_DIR/linux-${KBUILD_VERSION}"

if [ ! -d "$SRCDIR" ]; then
    echo "Fetching kernel source..."
    if [ ! -f "$TARBALL" ]; then
        echo "  Downloading $TARBALL_URL"
        curl -L -o "$TARBALL" "$TARBALL_URL"
    fi
    echo "  Extracting brcmfmac source (not full kernel)..."
    mkdir -p "$SRCDIR"
    # Extract only what we need
    tar xf "$TARBALL" -C "$WORK_DIR" \
        "linux-${KBUILD_VERSION}/drivers/net/wireless/broadcom/brcm80211/" \
        "linux-${KBUILD_VERSION}/include/linux/bcma/" \
        2>/dev/null || true
    echo "  Done."
fi

BRCMFMAC_SRC="$SRCDIR/drivers/net/wireless/broadcom/brcm80211/brcmfmac"
BRCMSMAC_SRC="$SRCDIR/drivers/net/wireless/broadcom/brcm80211/brcmsmac"
INCLUDE_SRC="$SRCDIR/drivers/net/wireless/broadcom/brcm80211/include"

if [ ! -f "$BRCMFMAC_SRC/pcie.c" ]; then
    echo "ERROR: brcmfmac source not found at $BRCMFMAC_SRC"
    exit 1
fi

echo "brcmfmac source: $BRCMFMAC_SRC"
echo ""

# ============================================================
# Apply BCM4360 patches
# ============================================================
echo "Applying BCM4360 patches..."

# Patch 1: brcm_hw_ids.h — add chip and device IDs
HWIDS="$INCLUDE_SRC/brcm_hw_ids.h"
if ! grep -q 'BRCM_CC_4360_CHIP_ID' "$HWIDS"; then
    echo "  Patching brcm_hw_ids.h..."

    # Add chip IDs
    sed -i '/^#define BRCM_CC_4350_CHIP_ID/a \#define BRCM_CC_4360_CHIP_ID\t\t0x4360\n#define BRCM_CC_4352_CHIP_ID\t\t0x4352' "$HWIDS"

    # Add PCI device IDs
    sed -i '/^#define BRCM_PCIE_4350_DEVICE_ID/a \#define BRCM_PCIE_4360_DEVICE_ID\t0x43a0\n#define BRCM_PCIE_4352_DEVICE_ID\t0x43b1' "$HWIDS"
else
    echo "  brcm_hw_ids.h already patched"
fi

# Patch 2: chip.c — add TCM rambase
CHIPC="$BRCMFMAC_SRC/chip.c"
if ! grep -q 'BRCM_CC_4360_CHIP_ID' "$CHIPC"; then
    echo "  Patching chip.c..."
    sed -i '/case BRCM_CC_4350_CHIP_ID:/a \\tcase BRCM_CC_4360_CHIP_ID:\n\tcase BRCM_CC_4352_CHIP_ID:' "$CHIPC"
else
    echo "  chip.c already patched"
fi

# Patch 3: pcie.c — add firmware defs, table entries, PCI IDs
PCIEC="$BRCMFMAC_SRC/pcie.c"
if ! grep -q 'brcmfmac4360' "$PCIEC"; then
    echo "  Patching pcie.c..."

    # Firmware name definitions
    sed -i '/^BRCMF_FW_DEF(4350C,/a BRCMF_FW_DEF(4360, "brcmfmac4360-pcie");\nBRCMF_FW_DEF(4352, "brcmfmac4352-pcie");' "$PCIEC"

    # Firmware table entries — after 43602
    sed -i '/BRCMF_FW_ENTRY(BRCM_CC_43602_CHIP_ID,/a \\tBRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360),\n\tBRCMF_FW_ENTRY(BRCM_CC_4352_CHIP_ID, 0xFFFFFFFF, 4352),' "$PCIEC"

    # PCI device IDs — before 4350
    sed -i '/BRCMF_PCIE_DEVICE(BRCM_PCIE_4350_DEVICE_ID,/i \\tBRCMF_PCIE_DEVICE(BRCM_PCIE_4360_DEVICE_ID, WCC),\n\tBRCMF_PCIE_DEVICE(BRCM_PCIE_4352_DEVICE_ID, WCC),' "$PCIEC"
else
    echo "  pcie.c already patched"
fi

echo ""
echo "Verifying patches:"
echo "  hw_ids.h:"
grep -n '4360\|4352' "$HWIDS" | grep -v '^[[:space:]]*\*' | head -6
echo "  chip.c:"
grep -n 'BRCM_CC_43[56]' "$CHIPC" | head -6
echo "  pcie.c:"
grep -n '4360\|4352' "$PCIEC" | head -10
echo ""

# ============================================================
# Build the module
# ============================================================
echo "Building brcmfmac module..."
echo "  Kernel build: $KBUILD"

# We need to build brcmfmac as an out-of-tree module
# First, create a Makefile wrapper
cat > "$WORK_DIR/Makefile" << 'MAKEOF'
KDIR ?= /lib/modules/$(shell uname -r)/build
BRCM_SRC := $(src)/brcm80211/brcmfmac

obj-m += brcmfmac.o

brcmfmac-y += $(BRCM_SRC)/core.o
brcmfmac-y += $(BRCM_SRC)/bus.o
brcmfmac-y += $(BRCM_SRC)/proto.o
brcmfmac-y += $(BRCM_SRC)/common.o
brcmfmac-y += $(BRCM_SRC)/firmware.o

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
MAKEOF

# Actually, building out-of-tree brcmfmac is complex due to many internal
# dependencies. The better approach on NixOS is to build in-tree.
# Let's use the kernel's own build system.

cd "$SRCDIR"

# Create a minimal .config if not present
if [ ! -f ".config" ]; then
    # Copy running kernel's config
    if [ -f "$KBUILD/.config" ]; then
        cp "$KBUILD/.config" .config
    elif [ -f /proc/config.gz ]; then
        zcat /proc/config.gz > .config
    else
        echo "ERROR: Cannot find kernel config"
        exit 1
    fi
fi

echo ""
echo "Building with make M=... against $KBUILD"

make -C "$KBUILD" \
    M="$BRCMFMAC_SRC" \
    CONFIG_BRCMFMAC=m \
    CONFIG_BRCMFMAC_PCIE=y \
    CONFIG_BRCMFMAC_SDIO=n \
    CONFIG_BRCMFMAC_USB=n \
    modules -j$(nproc) 2>&1

echo ""

# Find the built module
BUILT_KO=$(find "$BRCMFMAC_SRC" -name 'brcmfmac.ko*' | head -1)
if [ -z "$BUILT_KO" ]; then
    echo "ERROR: Build failed — no brcmfmac.ko found"
    echo "Build output in: $BRCMFMAC_SRC"
    exit 1
fi

echo "SUCCESS: Module built at $BUILT_KO"
echo "  Size: $(ls -lh "$BUILT_KO" | awk '{print $5}')"

# Copy to output
mkdir -p "$OUTPUT_DIR"
cp "$BUILT_KO" "$OUTPUT_DIR/"
echo "  Copied to: $OUTPUT_DIR/$(basename "$BUILT_KO")"

echo ""
echo "=========================================="
echo "Next steps:"
echo "=========================================="
echo "1. Place firmware: sudo cp phase1/output/firmware_4352pci.bin /lib/firmware/brcm/brcmfmac4360-pcie.bin"
echo "2. Unload wl:     sudo modprobe -r wl"
echo "3. Load module:   sudo insmod $OUTPUT_DIR/brcmfmac.ko"
echo "4. Check dmesg:   dmesg | tail -30"
echo ""
echo "Make sure your USB WiFi adapter (wlp0s20u2) is UP before unloading wl!"
