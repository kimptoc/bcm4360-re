# BCM4360 Reverse Engineering Project

An effort to bring open-source Linux driver support to the Broadcom BCM4360 802.11ac wireless chipset, which currently requires an unmaintained proprietary driver (`wl`/broadcom-sta) with known unpatched security vulnerabilities.

Documentation map: see [DOCS.md](DOCS.md) for where high-level summaries,
pinned findings, live session notes, phase analysis, and raw logs belong.

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

The initial approach was to extend the existing `brcmfmac` kernel driver — the same strategy used by Asahi Linux for BCM4387 (Apple M1). Phase 3 testing proved the driver-side PCIe bring-up works end-to-end, but revealed a **fundamental protocol mismatch**: the BCM4360 firmware uses BCDC protocol while brcmfmac's PCIe backend requires msgbuf. No msgbuf firmware exists for this chip.

The project pivoted to using `brcmfmac` as a **debug/bring-up harness** while reverse-engineering the missing init steps from the proprietary `wl` driver. Phases (see [PLAN.md](PLAN.md) for full detail):

1. ~~**Phase 1** — Chip reconnaissance, firmware extraction from macOS `wl.ko`~~ ✅ Done
2. **Phase 2** — Live MMIO tracing of `wl` driver — *not executed* (fallback path; partial capture in `phase5/logs/wl-trace`)
3. ~~**Phase 3** — Patched brcmfmac bring-up: chip IDs, firmware mappings, TCM rambase, 32-bit iowrite32, CR4 download~~ ✅ Done
4. **Phase 4** — BCDC-over-PCIe transport — ✅ partially done
   - ~~4A: BCDC encapsulation + PCIe messaging mechanics confirmed from `wl.ko` + firmware strings~~ ✅
   - ~~4B: Standalone harness proves firmware download + ARM release work — but firmware crashed host ~100–200ms after release~~ ✅
   - 4C/4D (BCDC command implementation + integration decision) **deferred** — pivoted to Phase 5 since brcmfmac already handles PCIe lifecycle/IRQ/DMA setup
5. **Phase 5** — BCM4360 bring-up via brcmfmac ← **current phase**
   - ~~5.1: Basic chip-support patches (chip ID, firmware mapping, rambase=0, 32-bit iowrite32, INTERNAL_MEM NULL guard)~~ ✅
   - 5.2: **Firmware boot stability & forensics** — *in progress* (test.181 was first clean ARM release; test.196 first ever firmware TCM writes; tests 200+ decoding firmware-side ASSERT at `hndarm.c:397`)
   - 5.3: Firmware protocol bridge (BCDC over PCIe) — *gated on 5.2*
   - 5.4: Functional validation (scan, associate, transfer) — *gated on 5.3*
   - 5.5: Upstream submission to `linux-wireless` and `brcm80211` — *gated on 5.4*
6. **Phase 6** — Clean-room `wl` analysis ← **in progress, parallel to 5.2**
   - ~~6.1: Symbol-level survey of `wl.ko` (call chain, gap identification: `si_pmu_*`, `do_4360_pcie2_war`, OTP/NVRAM path)~~ ✅ first pass
   - 6.2: Register-level extraction (start with `do_4360_pcie2_war`, then `si_pmu_chip_init`/`pll_init`/`res_init`)
   - 6.3: Get `wl` loaded on this kernel (NixOS `retbleed=off` boot param) so `mmiotrace` can record live MMIO sequences
   - 6.4: Side-by-side `wl` vs `brcmfmac` bringup comparison table

No phases beyond 6 are planned; Phase 5.5 (upstream submission) is the project's terminal milestone. Phases 5.2 and 6 work in parallel: each Phase 6 finding feeds back into Phase 5.2 as a new probe or driver patch.

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

This project uses clean-room reverse engineering techniques for interoperability
purposes, which is protected under:
- EU Directive 2009/24/EC (Article 6 — decompilation for interoperability)
- US Copyright Act (17 USC 1201 — reverse engineering exception for interoperability)

**Core principle:** All reverse engineering activity is framed as understanding
behavior to enable interoperability — not reproducing or redistributing
proprietary code.

**What this project does:**
- Documents observed firmware behavior: register access patterns, state
  transitions, call chains, timing
- Implements driver logic from documented behavior and open interfaces
- Uses hardware traces and register dumps as the primary source of truth

**What this project does not do:**
- Publish large disassembly blocks or reconstruct full functions verbatim
- Redistribute firmware blobs (users must obtain firmware from their own `wl`
  driver installation)
- Copy proprietary logic directly from disassembly into driver code

**Methodology:** observe behavior → document in plain language → implement
clean code from that documentation. The disassembly is a diagnostic tool, not
a blueprint.

No Broadcom proprietary source code is used or reproduced.

## License

The driver code produced by this project is intended for upstream inclusion in the Linux kernel and will be licensed under GPL-2.0, consistent with `brcmfmac`.
