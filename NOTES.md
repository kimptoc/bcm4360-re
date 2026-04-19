# Current crash recovery snapshot - 2026-04-19 PRE test.146

Test.146 is instrumentation only. It adds narrow emergency markers inside
`brcmf_pcie_register()` to distinguish a crash before `pci_register_driver()`
from a crash inside PCI registration/enumeration. It does not add BAR0 MMIO or
new PCI config accesses. The test.146 module has been rebuilt and commit
`5021abb` has been pushed.

Latest run was `test.145` stage0. It crashed after these stream markers:

```
brcmfmac: loading out-of-tree module taints kernel.
brcmfmac: BCM4360 test.145: module_init entry
brcmfmac: BCM4360 test.128: brcmf_pcie_register() entry
```

It did NOT reach `calling pci_register_driver`, `PROBE ENTRY`, or the
test.145 `buscore_reset` ARM halt. Therefore the current buscore-reset ARM
halt point is too late for this failure mode, and test.144 already showed that
raw BAR0 MMIO from module_init is too early/unsafe on fresh hardware.

Test.145 logs and notes are preserved in commit `30a33bd` and pushed. Before
any further testing, use SMC reset/full hardware power cut and verify clean PCIe
state. Test.146 code and notes are committed/pushed; after hardware recovery
and PCIe-state verification, run stage0 only.

# Post-crash recovery checklist

BCM4360 MMIO is dead. Requires full hardware power cycle.

## Step 1: Full power cycle

```
sudo shutdown -h now
```

Wait **30+ seconds** after power LED goes off, then power on.
A reboot (`-r`) won't work — only full shutdown cuts PCIe slot power.

## Step 2: Verify PCIe state before loading anything

```bash
sudo lspci -s 00:1c.2 -nn -vv
sudo lspci -s 03:00.0 -nn -vv
```

Expected: root port secondary/subordinate `03/03`, endpoint present, MAbort
clear, CommClk+.

Optional BAR0 probe:

```bash
sudo dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd
```

For this project, a fast I/O error/UR can still mean the endpoint is alive but
the BAR0 backplane bridge is not initialized. A slow completion timeout is not
safe for insmod. Prefer the current `test-staged-reset.sh` timing guard before
loading the module.

## Step 3: Prepare test.146, then commit/push before running

Test.146 code is instrumentation only: ultra-narrow emergency markers inside
`brcmf_pcie_register()` around the pre-`pci_register_driver` window. The
PRE-test.146 plan is saved in `RESUME_NOTES.md` and the module is rebuilt.
Commit `5021abb` is pushed. Do not execute the test harness until hardware
recovery and PCIe-state verification are done.

## Step 4: Run test.146 stage0 only

Use stage0 only. Stage1 remains forbidden until a stage0 run reaches the
intended safe stopping point cleanly.
