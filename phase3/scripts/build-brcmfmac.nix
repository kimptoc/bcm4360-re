# Build a patched brcmfmac module with BCM4360 support
#
# Usage:
#   nix-build phase3/scripts/build-brcmfmac.nix
#
# This builds the brcmfmac kernel module from the current system's kernel
# source with our BCM4360 patches applied. The result is a .ko file that
# can be loaded manually for testing.

{ pkgs ? import <nixpkgs> {} }:

let
  kernel = pkgs.linuxPackages.kernel;
in
pkgs.stdenv.mkDerivation {
  pname = "brcmfmac-bcm4360";
  version = "0.1.0";

  src = kernel.dev;

  nativeBuildInputs = with pkgs; [
    kernel.dev
    gnumake
    gcc
    bc
    flex
    bison
    pkg-config
    openssl
    elfutils
    perl
  ];

  # We patch the kernel source in-place, then build just the brcmfmac module
  buildPhase = ''
    export KERNEL_SRC=${kernel.dev}/lib/modules/${kernel.modDirVersion}/build

    # Create a working copy of the brcmfmac source
    mkdir -p work
    cp -r $KERNEL_SRC/drivers/net/wireless/broadcom/brcm80211 work/ 2>/dev/null || true

    # If full source isn't available, we need another approach
    if [ ! -f "$KERNEL_SRC/Makefile" ]; then
      echo "ERROR: Kernel build directory not available at $KERNEL_SRC"
      echo "Available in kernel.dev: $(ls ${kernel.dev}/lib/modules/*/)"
      exit 1
    fi

    echo "Kernel source: $KERNEL_SRC"
    echo "Kernel version: ${kernel.modDirVersion}"

    # Apply patches to a temporary copy
    TMPKERN=$(mktemp -d)
    cp -a $KERNEL_SRC/* $TMPKERN/ 2>/dev/null || cp -aL $KERNEL_SRC/* $TMPKERN/

    # Patch brcm_hw_ids.h — add chip and device IDs
    HWIDS=$TMPKERN/drivers/net/wireless/broadcom/brcm80211/include/brcm_hw_ids.h

    # Add chip IDs after BRCM_CC_4350_CHIP_ID
    sed -i '/^#define BRCM_CC_4350_CHIP_ID/a #define BRCM_CC_4360_CHIP_ID\t\t0x4360\n#define BRCM_CC_4352_CHIP_ID\t\t0x4352' "$HWIDS"

    # Add PCI device IDs after BRCM_PCIE_4350_DEVICE_ID
    sed -i '/^#define BRCM_PCIE_4350_DEVICE_ID/a #define BRCM_PCIE_4360_DEVICE_ID\t0x43a0\n#define BRCM_PCIE_4352_DEVICE_ID\t0x43b1' "$HWIDS"

    # Patch chip.c — add TCM rambase for 4360/4352
    CHIPC=$TMPKERN/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c
    sed -i '/case BRCM_CC_4350_CHIP_ID:/a \\tcase BRCM_CC_4360_CHIP_ID:\n\tcase BRCM_CC_4352_CHIP_ID:' "$CHIPC"

    # Patch pcie.c — add firmware definitions, table entries, and PCI IDs
    PCIEC=$TMPKERN/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c

    # Add firmware name definitions after the 4350C line
    sed -i '/^BRCMF_FW_DEF(4350C,/a BRCMF_FW_DEF(4360, "brcmfmac4360-pcie");\nBRCMF_FW_DEF(4352, "brcmfmac4352-pcie");' "$PCIEC"

    # Add firmware table entries after the 43602 entry
    sed -i '/BRCMF_FW_ENTRY(BRCM_CC_43602_CHIP_ID,/a \\tBRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360),\n\tBRCMF_FW_ENTRY(BRCM_CC_4352_CHIP_ID, 0xFFFFFFFF, 4352),' "$PCIEC"

    # Add PCI device IDs before BRCM_PCIE_4350_DEVICE_ID entry
    sed -i '/BRCMF_PCIE_DEVICE(BRCM_PCIE_4350_DEVICE_ID,/i \\tBRCMF_PCIE_DEVICE(BRCM_PCIE_4360_DEVICE_ID, WCC),\n\tBRCMF_PCIE_DEVICE(BRCM_PCIE_4352_DEVICE_ID, WCC),' "$PCIEC"

    echo "=== Patches applied. Verifying... ==="
    grep -n '4360\|4352' "$HWIDS" || true
    grep -n '4360\|4352' "$CHIPC" | head -5 || true
    grep -n '4360\|4352' "$PCIEC" | head -10 || true

    # Build just brcmfmac
    echo "=== Building brcmfmac module... ==="
    make -C $TMPKERN M=$TMPKERN/drivers/net/wireless/broadcom/brcm80211/brcmfmac \
      CONFIG_BRCMFMAC=m \
      CONFIG_BRCMFMAC_PCIE=y \
      modules -j$(nproc) 2>&1 | tail -20
  '';

  installPhase = ''
    mkdir -p $out/lib/modules/${kernel.modDirVersion}/kernel/net/wireless
    TMPKERN=$(echo /tmp/nix-build-*)
    find $TMPKERN -name 'brcmfmac.ko*' -exec cp {} $out/lib/modules/${kernel.modDirVersion}/kernel/net/wireless/ \;

    # Also copy the firmware directory layout
    mkdir -p $out/lib/firmware/brcm
    echo "Place brcmfmac4360-pcie.bin here" > $out/lib/firmware/brcm/README

    # Save the patch for reference
    mkdir -p $out/patches
    diff -ruN ${kernel.dev}/drivers/net/wireless/broadcom/brcm80211/include/brcm_hw_ids.h \
              $TMPKERN/drivers/net/wireless/broadcom/brcm80211/include/brcm_hw_ids.h > $out/patches/brcm_hw_ids.patch || true
  '';

  meta = with pkgs.lib; {
    description = "brcmfmac with BCM4360 support";
    license = licenses.gpl2;
  };
}
