#!/usr/bin/env python3
"""
BCM4360 BCMA Backplane Core Enumeration

Reads the BCMA Enumeration ROM (EROM) from the BCM4360's PCI BAR0 to
discover all internal cores on the chip's backplane bus.

This is a read-only operation that does not modify any hardware state.
It replicates what the kernel's drivers/bcma/scan.c does during bus scanning.

How it works:
  1. Read ChipCommon ID register (offset 0x000) via BAR0 to identify the chip
  2. Read EROM base address from ChipCommon (offset 0x0FC)
  3. Switch BAR0 window to point at the EROM address
  4. Parse the EROM table entries to discover cores

The BAR0 window is a 32KB window into the chip's backplane address space.
The window target is set via PCI config register 0x80 (BCMA_PCI_BAR0_WIN).
We save and restore the original window value.

Requires root access to read PCI config space and BAR mappings.

Usage:
  sudo python3 enumerate_cores.py

References:
  - Linux kernel: drivers/bcma/scan.c, drivers/bcma/scan.h
  - Linux kernel: include/linux/bcma/bcma.h
  - Linux kernel: include/linux/bcma/bcma_regs.h
  - Linux kernel: include/linux/bcma/bcma_driver_chipcommon.h
"""

import mmap
import struct
import sys
import os
import json
from datetime import datetime

# --- PCI device path ---
PCI_SLOT = "0000:03:00.0"
PCI_SYSFS = f"/sys/bus/pci/devices/{PCI_SLOT}"
BAR0_PATH = f"{PCI_SYSFS}/resource0"
CONFIG_PATH = f"{PCI_SYSFS}/config"

# --- BCMA constants (from kernel headers) ---
BCMA_ADDR_BASE = 0x18000000      # ChipCommon base address on backplane

# ChipCommon registers
BCMA_CC_ID = 0x0000
BCMA_CC_ID_ID_MASK = 0x0000FFFF
BCMA_CC_ID_REV_MASK = 0x000F0000
BCMA_CC_ID_REV_SHIFT = 16
BCMA_CC_ID_PKG_MASK = 0x00F00000
BCMA_CC_ID_PKG_SHIFT = 20
BCMA_CC_ID_NRCORES_MASK = 0x0F000000
BCMA_CC_ID_NRCORES_SHIFT = 24

BCMA_CC_EROM = 0x00FC            # EROM base pointer register

# PCI config space
BCMA_PCI_BAR0_WIN = 0x80         # BAR0 window register in PCI config

# BCMA core size
BCMA_CORE_SIZE = 0x1000          # 4KB per core

# EROM entry parsing (from drivers/bcma/scan.h)
SCAN_ER_VALID = 0x00000001
SCAN_ER_TAGX = 0x00000006
SCAN_ER_TAG = 0x0000000E
SCAN_ER_TAG_CI = 0x00000000
SCAN_ER_TAG_MP = 0x00000002
SCAN_ER_TAG_ADDR = 0x00000004
SCAN_ER_TAG_END = 0x0000000E

SCAN_CIA_CLASS_MASK = 0x000000F0
SCAN_CIA_CLASS_SHIFT = 4
SCAN_CIA_ID_MASK = 0x000FFF00
SCAN_CIA_ID_SHIFT = 8
SCAN_CIA_MANUF_MASK = 0xFFF00000
SCAN_CIA_MANUF_SHIFT = 20

SCAN_CIB_NMP_MASK = 0x000001F0
SCAN_CIB_NMP_SHIFT = 4
SCAN_CIB_NSP_MASK = 0x00003E00
SCAN_CIB_NSP_SHIFT = 9
SCAN_CIB_NMW_MASK = 0x0007C000
SCAN_CIB_NMW_SHIFT = 14
SCAN_CIB_NSW_MASK = 0x00F80000
SCAN_CIB_NSW_SHIFT = 19
SCAN_CIB_REV_MASK = 0xFF000000
SCAN_CIB_REV_SHIFT = 24

SCAN_ADDR_AG32 = 0x00000008
SCAN_ADDR_SZ = 0x00000030
SCAN_ADDR_SZ_SZD = 0x00000030
SCAN_ADDR_TYPE_MASK = 0x000000C0
SCAN_ADDR_TYPE_SLAVE = 0x00000000
SCAN_ADDR_TYPE_BRIDGE = 0x00000040
SCAN_ADDR_TYPE_SWRAP = 0x00000080
SCAN_ADDR_TYPE_MWRAP = 0x000000C0
SCAN_ADDR_PORT_MASK = 0x00000F00
SCAN_ADDR_PORT_SHIFT = 8
SCAN_ADDR_ADDR_MASK = 0xFFFFF000

SCAN_SIZE_SG32 = 0x00000008
SCAN_SIZE_SZ_MASK = 0xFFFFF000

# Manufacturer IDs
BCMA_MANUF_ARM = 0x43B
BCMA_MANUF_BCM = 0x4BF
BCMA_MANUF_MIPS = 0x4A7

# Known core IDs (from include/linux/bcma/bcma.h)
CORE_NAMES = {
    0x367: "OOB Router",
    0x500: "BCM4706 ChipCommon",
    0x501: "PCIe Gen 2 (NS)",
    0x502: "DMA (NS)",
    0x503: "SDIO3 (NS)",
    0x504: "USB 2.0 (NS)",
    0x505: "USB 3.0 (NS)",
    0x506: "ARM Cortex A9 JTAG (NS)",
    0x507: "DDR2/3 (NS)",
    0x508: "ROM (NS)",
    0x509: "NAND (NS)",
    0x50A: "QSPI (NS)",
    0x50B: "ChipCommon B (NS)",
    0x50E: "SOC RAM (4706)",
    0x510: "ARM Cortex A9",
    0x52D: "GBit MAC (4706)",
    0x52E: "AMEMC (DDR)",
    0x534: "ALTA (I2S)",
    0x5DC: "GBit MAC Common (4706)",
    0x700: "Invalid",
    0x800: "ChipCommon",
    0x801: "ILine 20",
    0x802: "SRAM",
    0x803: "SDRAM",
    0x804: "PCI",
    0x805: "MIPS",
    0x806: "Fast Ethernet",
    0x807: "V90",
    0x808: "USB 1.1 Hostdev",
    0x809: "ADSL",
    0x80A: "ILine 100",
    0x80B: "IPSEC",
    0x80C: "UTOPIA",
    0x80D: "PCMCIA",
    0x80E: "Internal Memory",
    0x80F: "MEMC SDRAM",
    0x810: "OFDM",
    0x811: "EXTIF",
    0x812: "IEEE 802.11 (D11)",
    0x813: "PHY A",
    0x814: "PHY B",
    0x815: "PHY G",
    0x816: "MIPS 3302",
    0x817: "USB 1.1 Host",
    0x818: "USB 1.1 Device",
    0x819: "USB 2.0 Host",
    0x81A: "USB 2.0 Device",
    0x81B: "SDIO Host",
    0x81C: "Roboswitch",
    0x81D: "PATA",
    0x81E: "SATA XOR-DMA",
    0x81F: "GBit Ethernet",
    0x820: "PCIe",
    0x821: "PHY N",
    0x822: "SRAM Controller",
    0x823: "Mini MACPHY",
    0x824: "ARM 1176",
    0x825: "ARM 7TDMI",
    0x826: "PHY LP",
    0x827: "PMU",
    0x828: "PHY SSN",
    0x829: "SDIO Device",
    0x82A: "ARM CM3",
    0x82B: "PHY HT",
    0x82D: "GBit MAC",
    0x82E: "DDR1/2 Memory Controller",
    0x82F: "PCIe Root Complex",
    0x830: "OCP-OCP Bridge",
    0x831: "Shared Common",
    0x832: "OCP-AHB Bridge",
    0x833: "SPI Host",
    0x834: "I2S",
    0x835: "SDR/DDR1 Memory Controller",
    0x837: "SHIM",
    0x83C: "PCIe Gen2",
    0x83E: "ARM CR4",
    0x840: "GCI",
    0x846: "CNDS DDR2/3",
    0x847: "ARM CA7",
    0xFFF: "Default",
}

MANUF_NAMES = {
    BCMA_MANUF_ARM: "ARM",
    BCMA_MANUF_BCM: "Broadcom",
    BCMA_MANUF_MIPS: "MIPS",
}


def read32(mm, offset):
    """Read a 32-bit little-endian value from mmap at offset."""
    mm.seek(offset)
    return struct.unpack("<I", mm.read(4))[0]


def pci_config_read32(config_fd, offset):
    """Read 32-bit value from PCI config space."""
    os.lseek(config_fd, offset, os.SEEK_SET)
    data = os.read(config_fd, 4)
    return struct.unpack("<I", data)[0]


def pci_config_write32(config_fd, offset, value):
    """Write 32-bit value to PCI config space."""
    os.lseek(config_fd, offset, os.SEEK_SET)
    os.write(config_fd, struct.pack("<I", value))


class EromReader:
    """Reads and parses BCMA Enumeration ROM entries from a memory-mapped BAR."""

    def __init__(self, mm, base_offset=0):
        self.mm = mm
        self.pos = base_offset

    def read_entry(self):
        val = read32(self.mm, self.pos)
        self.pos += 4
        return val

    def push_back(self):
        self.pos -= 4

    def get_ci(self):
        """Read a Component Identification entry. Returns (cia, cib) or None."""
        ent = self.read_entry()
        if not (ent & SCAN_ER_VALID):
            self.push_back()
            return None
        if (ent & SCAN_ER_TAG) != SCAN_ER_TAG_CI:
            self.push_back()
            return None
        cia = ent
        cib = self.read_entry()
        return (cia, cib)

    def is_end(self):
        ent = self.read_entry()
        self.push_back()
        return ent == (SCAN_ER_TAG_END | SCAN_ER_VALID)

    def skip_component(self):
        """Skip entries until the next CI or END."""
        while True:
            ent = self.read_entry()
            if (ent & SCAN_ER_VALID) and ((ent & SCAN_ER_TAG) == SCAN_ER_TAG_CI):
                self.push_back()
                return
            if ent == (SCAN_ER_TAG_END | SCAN_ER_VALID):
                self.push_back()
                return

    def get_addr_desc(self):
        """Read an address descriptor. Returns (addr, type, port, size) or None."""
        ent = self.read_entry()
        if not (ent & SCAN_ER_VALID):
            self.push_back()
            return None
        if (ent & SCAN_ER_TAGX) != SCAN_ER_TAG_ADDR:
            self.push_back()
            return None

        addr_type = ent & SCAN_ADDR_TYPE_MASK
        port = (ent & SCAN_ADDR_PORT_MASK) >> SCAN_ADDR_PORT_SHIFT
        addr = ent & SCAN_ADDR_ADDR_MASK

        # Handle 64-bit address
        if ent & SCAN_ADDR_AG32:
            self.read_entry()  # high 32 bits (ignore for our purposes)

        # Handle explicit size descriptor
        size = 0x1000  # default 4KB
        sz_field = ent & SCAN_ADDR_SZ
        if sz_field == SCAN_ADDR_SZ_SZD:
            size_ent = self.read_entry()
            size = size_ent & SCAN_SIZE_SZ_MASK
            if size_ent & SCAN_SIZE_SG32:
                self.read_entry()  # high 32 bits of size
        elif sz_field == 0x00:
            size = 0x1000       # 4KB
        elif sz_field == 0x10:
            size = 0x2000       # 8KB
        elif sz_field == 0x20:
            size = 0x4000       # 16KB

        return (addr, addr_type, port, size)


def addr_type_name(t):
    return {
        SCAN_ADDR_TYPE_SLAVE: "slave",
        SCAN_ADDR_TYPE_BRIDGE: "bridge",
        SCAN_ADDR_TYPE_SWRAP: "slave_wrap",
        SCAN_ADDR_TYPE_MWRAP: "master_wrap",
    }.get(t, f"unknown(0x{t:02x})")


def main():
    if os.geteuid() != 0:
        print("ERROR: This script requires root access to read PCI BAR mappings.")
        print("Usage: sudo python3 enumerate_cores.py")
        sys.exit(1)

    # Check device exists
    if not os.path.exists(BAR0_PATH):
        print(f"ERROR: PCI device not found at {PCI_SYSFS}")
        sys.exit(1)

    results = {
        "timestamp": datetime.now().isoformat(),
        "pci_slot": PCI_SLOT,
        "chip": {},
        "erom_base": None,
        "cores": [],
        "raw_erom": [],
    }

    print(f"BCM4360 BCMA Backplane Core Enumeration")
    print(f"========================================")
    print(f"PCI device: {PCI_SLOT}")
    print(f"BAR0 resource: {BAR0_PATH}")
    print()

    # Open PCI config space
    config_fd = os.open(CONFIG_PATH, os.O_RDWR)

    # Save current BAR0 window value
    original_bar0_win = pci_config_read32(config_fd, BCMA_PCI_BAR0_WIN)
    print(f"Current BAR0 window: 0x{original_bar0_win:08X}")

    # Open BAR0 for memory-mapped access
    bar0_fd = os.open(BAR0_PATH, os.O_RDWR | os.O_SYNC)
    bar0_size = os.fstat(bar0_fd).st_size
    print(f"BAR0 size: {bar0_size} bytes ({bar0_size // 1024}KB)")

    mm = mmap.mmap(bar0_fd, bar0_size, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE)

    try:
        # Step 1: Point BAR0 window at ChipCommon (0x18000000)
        print(f"\nSwitching BAR0 window to ChipCommon (0x{BCMA_ADDR_BASE:08X})...")
        pci_config_write32(config_fd, BCMA_PCI_BAR0_WIN, BCMA_ADDR_BASE)

        # Step 2: Read ChipCommon ID
        cc_id_raw = read32(mm, BCMA_CC_ID)
        chip_id = (cc_id_raw & BCMA_CC_ID_ID_MASK)
        chip_rev = (cc_id_raw & BCMA_CC_ID_REV_MASK) >> BCMA_CC_ID_REV_SHIFT
        chip_pkg = (cc_id_raw & BCMA_CC_ID_PKG_MASK) >> BCMA_CC_ID_PKG_SHIFT
        chip_ncores = (cc_id_raw & BCMA_CC_ID_NRCORES_MASK) >> BCMA_CC_ID_NRCORES_SHIFT

        chip_id_str = f"0x{chip_id:04X}" if chip_id <= 0x9999 else str(chip_id)
        print(f"\nChip ID register: 0x{cc_id_raw:08X}")
        print(f"  Chip ID:     {chip_id_str} ({'BCM' + str(chip_id) if chip_id <= 0x9999 else chip_id_str})")
        print(f"  Revision:    0x{chip_rev:02X}")
        print(f"  Package:     0x{chip_pkg:02X}")
        print(f"  Num cores:   {chip_ncores} (may be 0 if >15 cores, use EROM to count)")

        results["chip"] = {
            "raw": f"0x{cc_id_raw:08X}",
            "id": chip_id,
            "id_str": chip_id_str,
            "revision": chip_rev,
            "package": chip_pkg,
            "ncores_field": chip_ncores,
        }

        # Step 3: Read EROM base address
        erom_base = read32(mm, BCMA_CC_EROM)
        print(f"\nEROM base address: 0x{erom_base:08X}")
        results["erom_base"] = f"0x{erom_base:08X}"

        if erom_base == 0 or erom_base == 0xFFFFFFFF:
            print("ERROR: Invalid EROM base address. Cannot enumerate cores.")
            return

        # Step 4: Switch BAR0 window to EROM
        print(f"Switching BAR0 window to EROM (0x{erom_base:08X})...")
        pci_config_write32(config_fd, BCMA_PCI_BAR0_WIN, erom_base)

        # Step 5: Parse EROM entries
        print(f"\n--- Raw EROM entries (first 64) ---")
        raw_entries = []
        for i in range(64):
            val = read32(mm, i * 4)
            raw_entries.append(val)
            if val == (SCAN_ER_TAG_END | SCAN_ER_VALID):
                print(f"  [{i:3d}] 0x{val:08X}  <END>")
                break
            print(f"  [{i:3d}] 0x{val:08X}")
        results["raw_erom"] = [f"0x{v:08X}" for v in raw_entries]

        # Step 6: Parse cores from EROM
        print(f"\n--- Discovered Cores ---")
        print(f"{'#':>3s}  {'Manuf':>10s}  {'ID':>6s}  {'Rev':>4s}  {'Class':>5s}  {'Name':<30s}  {'Address':>12s}  {'Wrapper':>12s}")
        print("-" * 100)

        reader = EromReader(mm)
        core_num = 0

        while not reader.is_end():
            ci = reader.get_ci()
            if ci is None:
                # Skip non-CI entries
                reader.read_entry()
                continue

            cia, cib = ci

            core_class = (cia & SCAN_CIA_CLASS_MASK) >> SCAN_CIA_CLASS_SHIFT
            core_id = (cia & SCAN_CIA_ID_MASK) >> SCAN_CIA_ID_SHIFT
            core_manuf = (cia & SCAN_CIA_MANUF_MASK) >> SCAN_CIA_MANUF_SHIFT
            num_mports = (cib & SCAN_CIB_NMP_MASK) >> SCAN_CIB_NMP_SHIFT
            num_sports = (cib & SCAN_CIB_NSP_MASK) >> SCAN_CIB_NSP_SHIFT
            num_mwrap = (cib & SCAN_CIB_NMW_MASK) >> SCAN_CIB_NMW_SHIFT
            num_swrap = (cib & SCAN_CIB_NSW_MASK) >> SCAN_CIB_NSW_SHIFT
            core_rev = (cib & SCAN_CIB_REV_MASK) >> SCAN_CIB_REV_SHIFT

            manuf_name = MANUF_NAMES.get(core_manuf, f"0x{core_manuf:03X}")
            core_name = CORE_NAMES.get(core_id, f"Unknown(0x{core_id:03X})")

            # Skip non-core components (ARM default, no slave ports)
            if (core_manuf == BCMA_MANUF_ARM and core_id == 0xFFF) or num_sports == 0:
                reader.skip_component()
                core_num += 1
                continue

            # Read master ports
            for _ in range(num_mports):
                reader.read_entry()

            # Read address descriptors
            addresses = []
            wrappers = []

            # Read slave addresses
            for port in range(num_sports):
                while True:
                    desc = reader.get_addr_desc()
                    if desc is None:
                        break
                    addr, atype, aport, size = desc
                    if atype == SCAN_ADDR_TYPE_SLAVE:
                        addresses.append({"addr": f"0x{addr:08X}", "port": aport, "size": f"0x{size:X}"})
                    elif atype == SCAN_ADDR_TYPE_BRIDGE:
                        addresses.append({"addr": f"0x{addr:08X}", "type": "bridge", "port": aport, "size": f"0x{size:X}"})
                    else:
                        # Not a slave/bridge — push back, it's a wrapper
                        reader.push_back()
                        break

            # Read master wrappers
            for i in range(num_mwrap):
                while True:
                    desc = reader.get_addr_desc()
                    if desc is None:
                        break
                    addr, atype, aport, size = desc
                    if atype == SCAN_ADDR_TYPE_MWRAP:
                        wrappers.append({"addr": f"0x{addr:08X}", "type": "master", "port": aport})
                    else:
                        reader.push_back()
                        break

            # Read slave wrappers
            for i in range(num_swrap):
                hack = 0 if num_sports == 1 else 1
                while True:
                    desc = reader.get_addr_desc()
                    if desc is None:
                        break
                    addr, atype, aport, size = desc
                    if atype == SCAN_ADDR_TYPE_SWRAP:
                        wrappers.append({"addr": f"0x{addr:08X}", "type": "slave", "port": aport})
                    else:
                        reader.push_back()
                        break

            main_addr = addresses[0]["addr"] if addresses else "N/A"
            main_wrap = wrappers[0]["addr"] if wrappers else "N/A"

            print(f"{core_num:3d}  {manuf_name:>10s}  0x{core_id:03X}  0x{core_rev:02X}  0x{core_class:02X}   {core_name:<30s}  {main_addr:>12s}  {main_wrap:>12s}")

            core_info = {
                "index": core_num,
                "manufacturer": manuf_name,
                "manufacturer_id": f"0x{core_manuf:03X}",
                "id": f"0x{core_id:03X}",
                "id_decimal": core_id,
                "name": core_name,
                "revision": core_rev,
                "class": core_class,
                "master_ports": num_mports,
                "slave_ports": num_sports,
                "master_wrappers": num_mwrap,
                "slave_wrappers": num_swrap,
                "addresses": addresses,
                "wrappers": wrappers,
            }
            results["cores"].append(core_info)
            core_num += 1

        print(f"\nTotal cores discovered: {len(results['cores'])}")

    finally:
        # IMPORTANT: Restore original BAR0 window so the wl driver keeps working
        print(f"\nRestoring BAR0 window to 0x{original_bar0_win:08X}...")
        pci_config_write32(config_fd, BCMA_PCI_BAR0_WIN, original_bar0_win)
        mm.close()
        os.close(bar0_fd)
        os.close(config_fd)
        print("Done. BAR0 window restored.")

    # Save results as JSON
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "core_enumeration.json")
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {output_path}")

    return results


if __name__ == "__main__":
    main()
