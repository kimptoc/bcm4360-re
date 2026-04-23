# Current crash recovery snapshot - 2026-04-23 POST test.261 / PRE test.262

The machine restarted after the `test.261` run and SMC has been reset.
Recovered current PCIe state on the new boot is clean:

```text
00:1c.2 secondary/subordinate = 03/03, Mem+, BusMaster+, <MAbort-
03:00.0 BCM4360 present, BAR0=b0600000, BAR2=b0400000, Mem+, BusMaster+
```

`test.261` was the split-enable **doorbell-only** discriminator using the
already-landed `bcm4360_test260_doorbell_only=1` path from `1580e3e`
(`PRE-TEST.260 code: split-enable + timeline probe`). The redirected run log
stayed empty, but the prior-boot kernel journal was recoverable and has been
saved to `phase5/logs/test.261.journalctl.txt`.

Recovered `test.261` result:

```text
BCM4360 test.260 doorbell_only: pci_enable_msi=0 prev_irq=18 new_irq=79
BCM4360 test.260 doorbell_only: request_irq ret=0
BCM4360 test.260 doorbell_only: calling hostready (H2D_MAILBOX_1 write) — NO mask
BCM4360 test.260 doorbell_only: hostready done; starting 50×100ms timeline
BCM4360 test.260 doorbell_only: t+120100ms ... mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0
...
BCM4360 test.260 doorbell_only: t+124900ms ... mailboxint=0x00000000 buf_ptr=0x8009ccbe irq_count=0
```

Interpretation:

- `H2D_MAILBOX_1=1` alone is benign for the full emitted 4.9s timeline.
- Firmware did **not** wake: `MAILBOXINT` remained `0`, `buf_ptr` stayed
  `0x8009CCBE`, `irq_count` stayed `0`.
- This matches `test.260` mask-only exactly: both split-write variants survive
  through `t+124900ms` and then die before the missing `t+125000ms`/summary.
- The surviving common suspect is now the shared scaffold itself:
  `pci_enable_msi` + `request_irq` + the 50×100ms poll/sleep loop.
  Cleanup is less likely because the crash happens before the summary line that
  precedes teardown.

Recommended next step is a new control run, `test.262` in practice: add a
T260-family path that keeps `pci_enable_msi` + `request_irq` + the timeline
loop, but performs **no** `MAILBOXMASK` write and **no** `hostready` write.
Commit and push the notes update before any new code or `insmod`.

Update: the `test.262` control path is now implemented in
`phase5/work/.../brcmfmac/pcie.c` as `bcm4360_test262_msi_poll_only=1`,
rebuilt successfully, and verified via `modinfo`. The next action is to commit
and push this pre-test state, re-check PCIe state, and fire the run.

---

# Previous crash recovery snapshot - 2026-04-19 PRE test.147

Test.147 is the next no-hardware-access discriminator after the test.146 crash.
It skips the early:

```
brcmf_dbg(PCIE, "Enter\n");
```

inside `brcmf_pcie_register()`, while preserving emergency markers immediately
before `pci_register_driver()` and after it returns. It does not add BAR0 MMIO,
BAR2 MMIO, or PCI config pokes.

Expected test.147 marker sequence:

```
BCM4360 test.147: module_init entry (no BAR0 MMIO)
BCM4360 test.147: brcmf_pcie_register() entry
BCM4360 test.147: skipping brcmf_dbg in brcmf_pcie_register
BCM4360 test.147: after skipped brcmf_dbg, before pci_register_driver
BCM4360 test.147: pci_register_driver returned ret=...
```

The module has been rebuilt successfully for test.147. Build output linked
`brcmfmac.ko`, repeated the existing unused `brcmf_pcie_write_ram32` warning,
and skipped BTF because `vmlinux` is unavailable.

Before running, commit and push this PRE-test.147 state, then verify clean PCIe
state. Run stage0 only. Stage1 remains forbidden.

---

# Previous crash recovery snapshot - 2026-04-19 POST test.146

The machine restarted after `test.146` stage0 and SMC has been reset. Current
visible PCIe state after reboot is restored: root port `00:1c.2` has
secondary/subordinate `03/03` with MAbort clear, and endpoint `03:00.0`
(`14e4:43a0` rev `03`) is present with BAR0/BAR2 assigned and MAbort clear.

`test.146` crashed before `pci_register_driver()`. The stream log captured:

```
brcmfmac: loading out-of-tree module taints kernel.
brcmfmac: BCM4360 test.146: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.146: brcmf_pcie_register() entry
brcmfmac: BCM4360 test.146: before brcmf_dbg in brcmf_pcie_register
```

It did not capture:

```
BCM4360 test.146: after brcmf_dbg, before pci_register_driver
BCM4360 test.146: pci_register_driver returned ret=...
BCM4360 test.128: PROBE ENTRY
```

The immediate source statement after the last marker is:

```
brcmf_dbg(PCIE, "Enter\n");
```

With tracing/debug enabled, `brcmf_dbg()` enters `__brcmf_dbg()`, conditionally
uses `pr_debug()`, and always emits `trace_brcmf_dbg(...)`. There is no intended
BCM4360 BAR0/BAR2 MMIO or new PCI config access in this window.

Recommended next step is `test.147`: make a no-hardware-access discriminator by
removing/skipping the early `brcmf_dbg(PCIE, "Enter\n")` in
`brcmf_pcie_register()`, keeping emergency markers before `pci_register_driver`
and after it returns. Rebuild, update notes, commit, and push before running
stage0. Stage1 remains forbidden.

---

# Previous crash recovery snapshot - 2026-04-19 PRE test.146

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

Post-SMC check at 2026-04-19 22:49 BST: root port is restored to secondary /
subordinate `03/03`, endpoint `03:00.0` is present, MAbort is clear, CommClk is
set, AER completion timeout is clear, and the BAR0 probe returned fast I/O
error in 29ms. This is the expected fast-UR state, not the slow CTO state.

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
