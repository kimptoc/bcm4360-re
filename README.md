# BCM4360 Reverse Engineering Project

An effort to bring open-source Linux driver support to the Broadcom BCM4360 802.11ac wireless chipset, which currently requires an unmaintained proprietary driver (`wl`/broadcom-sta) with known unpatched security vulnerabilities.

## Motivation

The Broadcom BCM4360 is found in many MacBook Air/Pro models (2013-2015) and some PCIe WiFi cards (e.g., ASUS PCE-AC68). It is currently the only 802.11ac Broadcom chip with **no open-source driver support**.

The proprietary `broadcom-sta` driver:
- Last upstream release: **September 2015** (version 6.30.223.271)
- Contains known unpatched RCEs: CVE-2019-9501, CVE-2019-9502 (heap buffer overflows)
- Is a hybrid driver: small open-source shim + proprietary binary blob
- Requires ongoing kernel-compatibility patches from distro maintainers
- Is packaged by ~15 Linux distributions despite being unmaintained
- Is incompatible with Linux kernel security mitigations
- Does not support WPA3

Broadcom has shown no intention of open-sourcing this driver or releasing firmware for use with the existing open-source `brcmfmac` driver. The firmware contains shared IP with current-generation chips, which is likely the blocker.

## Target Hardware

- **Chip:** Broadcom BCM4360 (PCI ID `14e4:43a0`, rev 03)
- **Subsystem:** Apple Inc. (106b:0112) — MacBook variant
- **Architecture:** FullMAC — 802.11ac stack runs on an ARM core inside the chip
- **Internal bus:** BCMA backplane (shared with other Broadcom chips)
- **PCIe BARs:**
  - BAR0: 32KB at `0xb0600000` (control registers)
  - BAR2: 2MB at `0xb0400000` (backplane/core window)
- **Current driver:** `wl` (proprietary, loaded as kernel module)
- **Kernel modules available:** `bcma`, `wl`

## Approach

Rather than writing a driver and firmware from scratch, the goal is to **extend the existing `brcmfmac` kernel driver** to support the BCM4360 — the same approach used by the Asahi Linux project to add BCM4387 (Apple M1) support.

This requires:
1. Understanding the host-to-firmware protocol the BCM4360 uses
2. Extracting the firmware blob from the existing `wl` driver module
3. Mapping the chip's internal core layout via BCMA backplane enumeration
4. Adapting `brcmfmac` to load the firmware and speak the chip's protocol variant

See [PLAN.md](PLAN.md) for the detailed execution plan.

## Prior Art and References

- [Quarkslab — Reverse-engineering Broadcom wireless chipsets](https://blog.quarkslab.com/reverse-engineering-broadcom-wireless-chipsets.html) — detailed analysis of Broadcom chip architecture, firmware structure, and code sharing between driver/firmware
- [Asahi Linux BCM4387 patches](https://lore.kernel.org/asahi/20230214092423.15175-1-marcan@marcan.st/T/) — Hector Martin's work adding Apple M1 WiFi support to brcmfmac, the model for this project
- [brcmfmac kernel documentation](https://wireless.docs.kernel.org/en/latest/en/users/drivers/brcm80211.html) — official docs for the open-source Broadcom FullMAC driver
- [b43 reverse-engineered specification](http://bcm-v4.sipsolutions.net/) — community-generated docs from the older SoftMAC reverse engineering effort
- [antoineco/broadcom-wl](https://github.com/antoineco/broadcom-wl) (archived) — the now-archived community wrapper for the proprietary driver
- [NixOS broadcom-sta package](https://github.com/NixOS/nixpkgs/blob/master/pkgs/os-specific/linux/broadcom-sta/default.nix) — one of ~15 distro packages maintaining kernel-compat patches
- [Linux kernel MAINTAINERS — brcm80211](https://www.kernel.org/doc/html/latest/process/maintainers.html) — Arend van Spriel (Broadcom) maintains the open-source brcmfmac/brcmsmac drivers

## Hardware Details Discovered

From probing the live device on a NixOS system (kernel 6.12.x):

```
$ lspci -vvv -s 03:00.0
03:00.0 Network controller: Broadcom Inc. and subsidiaries BCM4360 802.11ac Dual Band Wireless Network Adapter (rev 03)
    Subsystem: Apple Inc. Device 0112
    Region 0: Memory at b0600000 (64-bit, non-prefetchable) [size=32K]
    Region 2: Memory at b0400000 (64-bit, non-prefetchable) [size=2M]
    Kernel driver in use: wl
    Kernel modules: bcma, wl
```

PCI config space confirms: Vendor `14e4`, Device `43a0`, Subsystem `106b:0112`.

## Legal Notes

This project uses clean-room reverse engineering techniques for interoperability purposes, which is protected under:
- EU Directive 2009/24/EC (Article 6 — decompilation for interoperability)
- US Copyright Act (17 USC 1201 — reverse engineering exception for interoperability)

No Broadcom proprietary source code is used. Firmware binaries extracted from the `wl` driver are Broadcom's property and are not redistributed — users must extract their own copy.

## License

The driver code produced by this project is intended for upstream inclusion in the Linux kernel and will be licensed under GPL-2.0, consistent with `brcmfmac`.
