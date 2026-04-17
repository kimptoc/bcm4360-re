# Post-crash recovery checklist

BCM4360 MMIO is dead. Requires full hardware power cycle.

## Step 1: Full power cycle

```
sudo shutdown -h now
```

Wait **30+ seconds** after power LED goes off, then power on.
A reboot (`-r`) won't work — only full shutdown cuts PCIe slot power.

## Step 2: Verify MMIO before loading anything

```bash
sudo dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd
```

**Right now this returns I/O error — that is the broken state you're trying to fix.**
After a successful power cycle it should return 4 bytes of data (any value, not an error).
If it still returns I/O error after power cycle → power off and wait longer, then try again.

## Step 3: Rebuild module

```bash
make -C /home/kimptoc/bcm4360-re/phase5/work
```

## Step 4: Run test.116 stage0

The d11 guard code has never been reached — this is the first real test of it.
Expected: BAR0 probe returns alive, d11 IN_RESET=YES, guard skips 0x1e0 read, stage0 completes cleanly.

Only after stage0 clean: run stage1 (skip_arm=0).
