#!/usr/bin/env python3
"""
BCM4360 Firmware Extraction from wl.ko

Extracts the embedded firmware download arrays from the Broadcom STA
proprietary driver module (wl.ko). The wl driver contains ARM firmware
blobs that get loaded onto the chip's ARM CR4 core at initialization.

The driver contains two firmware variants:
  - dlarray_4352pci — for BCM4352/BCM4360 (rev <=3?)
  - dlarray_4350pci — for BCM4350/BCM4360 (rev 3+?)

This script:
  1. Reads the ELF section headers and symbol table from wl.ko
  2. Locates the dlarray_* symbols and metadata (name, version, date, tag)
  3. Maps symbol addresses to file offsets via section headers
  4. Extracts the raw firmware binaries
  5. Performs basic analysis (ARM entry point, size, strings)

The extracted firmware is Broadcom's proprietary IP and is NOT committed
to this repository. Users must extract their own copy from their own
wl.ko installation.

Usage:
  python3 extract_firmware.py [path_to_wl.ko]

If no path given, searches standard NixOS module locations.

References:
  - Quarkslab: "the chip's firmware and the wl driver share a lot of code"
  - Phase 1.1 findings: ARM CR4 has 640KB RAM at 0x00000000
"""

import struct
import sys
import os
import json
from datetime import datetime


def find_wl_ko():
    """Find wl.ko on this system."""
    import subprocess
    result = subprocess.run(["modinfo", "-n", "wl"], capture_output=True, text=True)
    if result.returncode == 0:
        path = result.stdout.strip()
        if os.path.exists(path):
            return path

    # Fallback: search nix store
    import glob
    for ko in sorted(glob.glob("/nix/store/*/lib/modules/*/kernel/net/wireless/wl.ko"), reverse=True):
        if os.path.isfile(ko):
            return ko

    return None


class ElfReader:
    """Minimal ELF64 reader for extracting sections and symbols."""

    def __init__(self, data):
        self.data = data
        self._parse_header()
        self._parse_sections()
        self._parse_symbols()

    def _parse_header(self):
        # ELF64 header
        magic = self.data[:4]
        if magic != b'\x7fELF':
            raise ValueError("Not an ELF file")

        ei_class = self.data[4]
        if ei_class != 2:
            raise ValueError("Not 64-bit ELF")

        # e_shoff: section header table offset
        self.e_shoff = struct.unpack_from("<Q", self.data, 40)[0]
        # e_shentsize: section header entry size
        self.e_shentsize = struct.unpack_from("<H", self.data, 58)[0]
        # e_shnum: number of section headers
        self.e_shnum = struct.unpack_from("<H", self.data, 60)[0]
        # e_shstrndx: section header string table index
        self.e_shstrndx = struct.unpack_from("<H", self.data, 62)[0]

    def _parse_sections(self):
        self.sections = []
        for i in range(self.e_shnum):
            off = self.e_shoff + i * self.e_shentsize
            sh_name = struct.unpack_from("<I", self.data, off)[0]
            sh_type = struct.unpack_from("<I", self.data, off + 4)[0]
            sh_flags = struct.unpack_from("<Q", self.data, off + 8)[0]
            sh_addr = struct.unpack_from("<Q", self.data, off + 16)[0]
            sh_offset = struct.unpack_from("<Q", self.data, off + 24)[0]
            sh_size = struct.unpack_from("<Q", self.data, off + 32)[0]
            sh_link = struct.unpack_from("<I", self.data, off + 40)[0]
            sh_info = struct.unpack_from("<I", self.data, off + 44)[0]
            sh_addralign = struct.unpack_from("<Q", self.data, off + 48)[0]
            sh_entsize = struct.unpack_from("<Q", self.data, off + 56)[0]

            self.sections.append({
                'name_off': sh_name,
                'type': sh_type,
                'flags': sh_flags,
                'addr': sh_addr,
                'offset': sh_offset,
                'size': sh_size,
                'link': sh_link,
                'info': sh_info,
                'addralign': sh_addralign,
                'entsize': sh_entsize,
            })

        # Resolve section names
        shstrtab = self.sections[self.e_shstrndx]
        for sec in self.sections:
            name_start = shstrtab['offset'] + sec['name_off']
            name_end = self.data.index(b'\0', name_start)
            sec['name'] = self.data[name_start:name_end].decode('ascii', errors='replace')

    def _parse_symbols(self):
        self.symbols = {}

        for sec in self.sections:
            if sec['type'] not in (2, 11):  # SHT_SYMTAB=2, SHT_DYNSYM=11
                continue

            strtab = self.sections[sec['link']]
            num_syms = sec['size'] // sec['entsize']

            for i in range(num_syms):
                off = sec['offset'] + i * sec['entsize']
                st_name = struct.unpack_from("<I", self.data, off)[0]
                st_info = self.data[off + 4]
                st_other = self.data[off + 5]
                st_shndx = struct.unpack_from("<H", self.data, off + 6)[0]
                st_value = struct.unpack_from("<Q", self.data, off + 8)[0]
                st_size = struct.unpack_from("<Q", self.data, off + 16)[0]

                # Resolve name
                name_start = strtab['offset'] + st_name
                name_end = self.data.index(b'\0', name_start)
                name = self.data[name_start:name_end].decode('ascii', errors='replace')

                if name:
                    self.symbols[name] = {
                        'value': st_value,
                        'size': st_size,
                        'info': st_info,
                        'shndx': st_shndx,
                    }

    def symbol_to_file_offset(self, sym_name):
        """Convert a symbol's virtual address to a file offset."""
        sym = self.symbols.get(sym_name)
        if not sym:
            return None, None

        shndx = sym['shndx']
        if shndx == 0 or shndx >= len(self.sections):
            return None, None

        section = self.sections[shndx]
        # Symbol value is offset within section (for relocatable objects)
        file_offset = section['offset'] + sym['value']
        return file_offset, sym['size']

    def read_string_at_symbol(self, sym_name, max_len=256):
        """Read a null-terminated string at a symbol's location."""
        offset, size = self.symbol_to_file_offset(sym_name)
        if offset is None:
            return None
        if size > 0:
            max_len = min(size, max_len)
        data = self.data[offset:offset + max_len]
        null_pos = data.find(b'\0')
        if null_pos >= 0:
            data = data[:null_pos]
        return data.decode('ascii', errors='replace')


def analyze_arm_firmware(data, name):
    """Perform basic analysis of an ARM firmware blob."""
    info = {
        'size': len(data),
        'size_hex': f"0x{len(data):X}",
        'size_kb': f"{len(data) / 1024:.1f}KB",
    }

    # Check for ARM vector table at the start
    # ARM CR4 vector table: reset, undefined, SWI, prefetch abort, data abort, -, IRQ, FIQ
    if len(data) >= 32:
        vectors = struct.unpack_from("<8I", data, 0)
        info['vector_table'] = [f"0x{v:08X}" for v in vectors]

        # ARM branch instructions start with 0xEA (unconditional branch)
        # or could be LDR PC instructions (0xE59FF...)
        arm_branch = all((v >> 24) in (0xEA, 0xE5) for v in vectors[:4])
        info['has_arm_vectors'] = arm_branch

        # Check for Thumb mode entry (bit 0 of reset vector destination)
        if vectors[0] >> 24 == 0xEA:
            branch_offset = (vectors[0] & 0x00FFFFFF)
            if branch_offset & 0x800000:
                branch_offset |= 0xFF000000  # sign extend
            entry_point = 8 + (branch_offset << 2)
            info['entry_point'] = f"0x{entry_point & 0xFFFFFFFF:08X}"

    # Look for readable strings (firmware version, build info)
    strings = []
    current = b''
    for i, byte in enumerate(data):
        if 32 <= byte < 127:
            current += bytes([byte])
        else:
            if len(current) >= 8:
                strings.append((i - len(current), current.decode('ascii', errors='replace')))
            current = b''

    # Find interesting strings
    version_strings = [s for _, s in strings if any(k in s.lower() for k in
                       ['version', 'build', 'date', 'broadcom', 'bcm', 'firmware',
                        'wl_', 'Copyright', '802.11', 'pci', 'cr4'])]
    info['notable_strings'] = version_strings[:20]

    # Count total readable strings
    info['total_strings'] = len(strings)

    # Check for common ARM instruction patterns
    # Look for BL (branch-and-link) instructions as indicator of ARM code
    bl_count = 0
    for i in range(0, min(len(data), 0x10000), 4):
        word = struct.unpack_from("<I", data, i)[0]
        if (word >> 24) == 0xEB:  # BL instruction
            bl_count += 1
    info['arm_bl_instructions_first_64k'] = bl_count

    return info


def main():
    # Find wl.ko
    if len(sys.argv) > 1:
        wl_path = sys.argv[1]
    else:
        wl_path = find_wl_ko()

    if not wl_path or not os.path.exists(wl_path):
        print("ERROR: Cannot find wl.ko")
        print("Usage: python3 extract_firmware.py [path_to_wl.ko]")
        sys.exit(1)

    print(f"BCM4360 Firmware Extraction")
    print(f"===========================")
    print(f"Source: {wl_path}")
    print(f"Size: {os.path.getsize(wl_path)} bytes")
    print()

    # Read entire file
    with open(wl_path, 'rb') as f:
        data = f.read()

    elf = ElfReader(data)

    results = {
        'timestamp': datetime.now().isoformat(),
        'source': wl_path,
        'source_size': len(data),
        'firmwares': [],
    }

    # Extract each firmware variant
    for variant in ['4352pci', '4350pci']:
        dlarray_sym = f'dlarray_{variant}'
        name_sym = f'dlimagename_{variant}'
        ver_sym = f'dlimagever_{variant}'
        date_sym = f'dlimagedate_{variant}'
        tag_sym = f'dlimagetag_{variant}'

        print(f"--- Firmware variant: {variant} ---")

        # Read metadata strings
        fw_name = elf.read_string_at_symbol(name_sym)
        fw_ver = elf.read_string_at_symbol(ver_sym)
        fw_date = elf.read_string_at_symbol(date_sym)
        fw_tag = elf.read_string_at_symbol(tag_sym)

        print(f"  Name:    {fw_name}")
        print(f"  Version: {fw_ver}")
        print(f"  Date:    {fw_date}")
        print(f"  Tag:     {fw_tag}")

        # Locate and extract firmware binary
        offset, size = elf.symbol_to_file_offset(dlarray_sym)
        if offset is None:
            print(f"  ERROR: Cannot locate {dlarray_sym}")
            continue

        print(f"  Symbol offset: 0x{offset:X}")
        print(f"  Symbol size:   0x{size:X} ({size} bytes, {size/1024:.1f}KB)")

        # Extract the raw firmware
        fw_data = data[offset:offset + size]

        # First bytes
        print(f"  First 32 bytes: {fw_data[:32].hex()}")
        print(f"  Last 16 bytes:  {fw_data[-16:].hex()}")

        # Analyze
        print(f"\n  Analyzing ARM firmware...")
        analysis = analyze_arm_firmware(fw_data, variant)
        for key, value in analysis.items():
            if key == 'vector_table':
                print(f"  Vector table: {' '.join(value[:4])}")
                print(f"                {' '.join(value[4:])}")
            elif key == 'notable_strings':
                print(f"  Notable strings ({len(value)}):")
                for s in value:
                    print(f"    - {s}")
            else:
                print(f"  {key}: {value}")

        # Save extracted firmware
        output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
        os.makedirs(output_dir, exist_ok=True)
        fw_path = os.path.join(output_dir, f"firmware_{variant}.bin")
        with open(fw_path, 'wb') as f:
            f.write(fw_data)
        print(f"\n  Saved to: {fw_path}")

        fw_info = {
            'variant': variant,
            'name': fw_name,
            'version': fw_ver,
            'date': fw_date,
            'tag': fw_tag,
            'symbol': dlarray_sym,
            'file_offset': f"0x{offset:X}",
            'size': size,
            'size_hex': f"0x{size:X}",
            'output_file': fw_path,
            'analysis': analysis,
        }
        # Remove non-serializable items
        fw_info['analysis'].pop('notable_strings', None)
        results['firmwares'].append(fw_info)
        print()

    # Save results JSON
    output_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "output")
    results_path = os.path.join(output_dir, "firmware_extraction.json")
    with open(results_path, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"Results saved to: {results_path}")

    # IMPORTANT: Do not commit the .bin files — they are proprietary
    gitignore_path = os.path.join(output_dir, ".gitignore")
    with open(gitignore_path, 'w') as f:
        f.write("# Proprietary firmware binaries — do not commit\n")
        f.write("*.bin\n")
    print(f"Added .gitignore to exclude firmware binaries from git")


if __name__ == "__main__":
    main()
