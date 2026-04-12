# Phase 3: Testing the Patched brcmfmac Module

**Date:** 2026-04-12
**Module built against:** kernel 6.12.80 (running: 6.12.78 — minor mismatch, may need rebuild)

## Built Modules

- `phase3/output/brcmfmac.ko` — main brcmfmac driver with BCM4360/4352 support
- `phase3/output/brcmfmac-wcc.ko` — WCC firmware vendor module (needed for our chip)

## Kernel Version Note

The module was built against 6.12.80 but the running kernel is 6.12.78. The `insmod` may reject it with a version mismatch. If so, options are:
1. Force load: `sudo insmod --force brcmfmac.ko` (risky)
2. Rebuild against the exact running kernel headers
3. Update NixOS to get 6.12.80 kernel, then test

## Pre-test Checklist

1. Ensure USB WiFi adapter is UP and connected:
   ```
   ip link show wlp0s20u2
   # If DOWN: sudo ip link set wlp0s20u2 up
   # Connect to WiFi via NetworkManager using the USB adapter
   ```

2. Prepare firmware files:
   ```
   # We don't know which variant the chip needs — try 4352pci first
   sudo mkdir -p /lib/firmware/brcm
   sudo cp phase1/output/firmware_4352pci.bin /lib/firmware/brcm/brcmfmac4360-pcie.bin
   ```

3. Note: we may also need an NVRAM file. Without it, brcmfmac may use defaults or fail. The NVRAM contains board-specific calibration data. It may be:
   - In the chip's SPROM (brcmfmac can read it)
   - Embedded in the wl driver (would need extraction)
   - Not needed if the firmware has built-in defaults

## Test Procedure

```bash
# 1. Switch to USB WiFi for connectivity
sudo nmcli device disconnect wlp3s0 2>/dev/null || true

# 2. Unload the proprietary wl driver
sudo modprobe -r wl

# 3. Load our patched brcmfmac
sudo insmod phase3/output/brcmfmac.ko
sudo insmod phase3/output/brcmfmac-wcc.ko

# 4. Check dmesg for results
dmesg | tail -50

# 5. Check if interface appeared
ip link show
```

## Expected Outcomes

### Best case: it works
- A new wireless interface appears (probably `wlan0` or `wlp3s0`)
- `dmesg` shows firmware loading and chip initialization
- Can scan for networks

### Likely case: informative failure
The dmesg output will tell us exactly what went wrong:
- **"Unsupported PCIE version N"** — firmware uses a protocol version we need to support
- **"firmware: failed to load brcm/brcmfmac4360-pcie.bin"** — firmware file issue
- **"RAM base not provided"** — rambase address wrong
- **"unknown chip"** — chip ID not recognized (patch didn't apply)
- **"Dongle setup failed"** — firmware loaded but failed init handshake

### Worst case: kernel panic
- Unlikely but possible if hardware init goes wrong
- Reboot, the USB adapter will still work, and wl can be reloaded

## Recovery

If things go wrong:
```bash
# Remove brcmfmac
sudo rmmod brcmfmac-wcc 2>/dev/null
sudo rmmod brcmfmac 2>/dev/null

# Reload wl
sudo modprobe wl

# Reconnect
sudo nmcli device connect wlp3s0
```

## After Testing

Save `dmesg` output regardless of result:
```bash
dmesg > phase3/output/dmesg_test_$(date +%Y%m%d_%H%M%S).log
```
