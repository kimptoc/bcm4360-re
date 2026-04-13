# Web Sources and Licensing Notes

**Date:** 2026-04-13

## Sources Referenced

### 1. BCM43602 NVRAM Example (brcmfmac43602-pcie.txt)
- **URL:** https://gist.github.com/MikeRatcliffe/9614c16a8ea09731a9d5e91685bd8c80
- **What:** Example NVRAM config file for BCM43602 on MacBook Pro, showing
  key=value format, field names (sromrev, boardtype, boardrev, boardflags, etc.)
- **Used for:** Understanding NVRAM file format and required field names
- **License:** No license specified on the gist. NVRAM files are hardware
  configuration data (board-specific calibration values), not copyrightable code.

### 2. Linux Kernel Patch: brcmfmac Apple OTP Reading
- **URL:** https://lkml.kernel.org/linux-wireless/20220104072658.69756-8-marcan@marcan.st/
- **What:** Kernel patch by Hector Martin (marcan) for reading Apple OTP
  (One-Time Programmable) information from Broadcom WiFi chips
- **Used for:** Understanding how Apple platforms store board calibration data
  (in OTP via ChipCommon core, parsed as tag-length-value records)
- **License:** GPL-2.0 (Linux kernel patch)
- **Note:** We did NOT copy any code from this patch. Used only for understanding
  the hardware access method (OTP via ChipCommon registers).

### 3. Linux Kernel Wireless Documentation
- **URL:** https://wireless.docs.kernel.org/en/latest/en/users/drivers/brcm80211.html
- **What:** Official brcmfmac driver documentation explaining firmware file
  naming conventions and NVRAM loading
- **Used for:** Understanding that brcmfmac loads NVRAM .txt files alongside
  firmware .bin files, and the file naming pattern
- **License:** Linux kernel documentation (GPL-2.0)

### 4. Arch Linux Forums — BCM4360 discussions
- **URLs:**
  - https://bbs.archlinux.org/viewtopic.php?id=249038
  - https://bbs.archlinux.org/viewtopic.php?id=305252
- **What:** Community discussions about BCM4360 (14e4:43a0) driver support
- **Used for:** Confirming that BCM4360 on Apple hardware typically requires
  proprietary wl driver, and understanding community experience
- **License:** Forum posts, factual information only

### 5. Linux Kernel Patchset: brcmfmac Apple T2/M1 Support
- **URL:** https://lore.kernel.org/netdev/1f37951b-aed7-64ca-7452-7332df791931@broadcom.com/t/
- **What:** Patchset for Apple platform support in brcmfmac
- **Used for:** Understanding firmware selection on Apple platforms
- **License:** GPL-2.0 (Linux kernel patches)
- **Note:** No code copied.

## NVRAM File (brcmfmac4360-pcie.txt) — Licensing

The NVRAM file we created (`phase4/work/brcmfmac4360-pcie.txt`) contains:
- **Format:** Standard Broadcom NVRAM key=value pairs, same format used by all
  brcmfmac .txt files in the Linux firmware tree
- **Values:** Initial values are guesses/placeholders that will be updated once
  we read the real SPROM from the chip hardware
- **boardtype=0x0552:** Common BCM4360 reference board type, used as starting
  point. Will be replaced with actual hardware value from SPROM dump.
- **MAC address:** Synthetic (Apple OUI + subsystem-derived), not a real MAC
- **Status:** This is a minimal test file, NOT production calibration data.
  Real calibration values must come from the chip's SPROM/OTP.

**No copyrighted code was copied.** The NVRAM format is a standard interface
defined by Broadcom hardware. Field names are part of the hardware specification
(SROM revision 11 format). The specific calibration VALUES are hardware-specific
and come from the chip itself.

## SPROM/TCM Loading Approach

The NVRAM-to-TCM loading code in bcm4360_test.c implements the standard
brcmfmac NVRAM loading protocol:
- NVRAM placed at end of TCM (ramsize - padded_len - 4)
- Length token at (ramsize - 4) with bit pattern (~len << 16) | len
- This is the documented interface between host driver and firmware

This protocol is described in the GPL-licensed brcmfmac driver source code
(drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c). Our implementation
is written from scratch based on understanding the protocol, not copied from
brcmfmac source.
