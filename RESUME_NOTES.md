# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-20, POST test.176 — host resetintr SUCCESS)

### TEST.176 RESULT — host resetintr extraction after safe sleep survives

Captured artifacts:
- `phase5/logs/test.176.stage0`
- `phase5/logs/test.176.stage0.stream`

Result: **SUCCESS / no crash.** test.176 completed the full 442233-byte BAR2
firmware write, slept for 100 ms after `fw write complete` with no device MMIO,
read resetintr from host firmware memory, released `fw`/`nvram`, returned
`-ENODEV`, waited the harness's 30 seconds, and cleaned up `brcmfmac` without
freezing.

Key persisted markers:
```
BCM4360 test.176: all 110558 words written, before tail (tail=1)
BCM4360 test.176: tail 1 bytes written at offset 442232
BCM4360 test.176: fw write complete (442233 bytes)
BCM4360 test.176: before post-fw msleep(100)
BCM4360 test.176: after post-fw msleep(100)
BCM4360 test.176: host resetintr=0xb80ef000 before release
BCM4360 test.176: released fw/nvram after host resetintr; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
```

### Interpretation

The host-side `resetintr = get_unaligned_le32(fw->data)` boundary is safe.
The observed resetintr value is `0xb80ef000`, matching the first firmware word
also seen by the BAR2 ioread32 probe in this run. This was all host memory work
after the safe `msleep(100)`, so the next real risk boundary is the NVRAM BAR2
write.

The old tests 170-173 froze before resetintr/NVRAM because they used post-write
`mdelay` dwell. With `msleep(100)`, we have safely advanced through resetintr
extraction and release. Continue adding one downstream boundary at a time.

### Current HW state after test.176

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled from the test path.
- Endpoint AER again shows `CESta Timeout+ AdvNonFatalErr+`; UESta is clear.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### Recommended next step — PRE test.177

Do **not** run another hardware test until this note and the test.176 artifacts
are committed, pushed, and synced.

Best next discriminator: add the NVRAM BAR2 write after the safe `msleep(100)`
and host resetintr extraction, then return before readback/ARM release:

1. After `fw write complete`, `msleep(100)` as test.175/176 did.
2. Read and log host `resetintr`.
3. Write NVRAM to BAR2 using the existing chunked iowrite32 NVRAM loop.
4. Release `fw`/`nvram` and return `-ENODEV`.
5. Still skip post-write ARM probe, resetintr device write/use, NVRAM marker
   readback, TCM dump, and ARM release.

Expected interpretation:
- Survives: NVRAM BAR2 write is safe when preceded by sleeping dwell; next test
  can add the NVRAM marker/readback boundary.
- Freezes: NVRAM write is the next unsafe BAR2 operation; then either reduce
  NVRAM write granularity/delays or quiesce/reset before NVRAM.

---

## Previous state (2026-04-20, POST test.175 — msleep dwell SUCCESS)

### TEST.175 RESULT — `msleep(100)` after fw write survives

Captured artifacts:
- `phase5/logs/test.175.stage0`
- `phase5/logs/test.175.stage0.stream`

Result: **SUCCESS / no crash.** test.175 completed the full 442233-byte BAR2
firmware write, slept for 100 ms after `fw write complete` with no device MMIO,
released `fw`/`nvram`, returned `-ENODEV`, waited the harness's 30 seconds, and
cleaned up `brcmfmac` without freezing.

Key persisted markers:
```
BCM4360 test.175: all 110558 words written, before tail (tail=1)
BCM4360 test.175: tail 1 bytes written at offset 442232
BCM4360 test.175: fw write complete (442233 bytes)
BCM4360 test.175: before post-fw msleep(100)
BCM4360 test.175: after post-fw msleep(100)
BCM4360 test.175: released fw/nvram after msleep; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
```

### Interpretation

This is a strong result: the post-write failure in tests 170-173 is not caused
by elapsed post-write time alone. A sleeping 100 ms dwell after the complete
firmware write is safe. That makes the old `mdelay(100)` / busy-wait dwell, or
something that happens after that dwell, the current suspect.

test.174 showed immediate return is safe; test.175 shows sleeping dwell is safe.
The next discriminator should keep `msleep(100)` and then touch the next
boundary that tests 170-173 never reached: `resetintr = get_unaligned_le32()`
from host firmware memory plus `release_firmware(fw)`, still without any device
MMIO, NVRAM write, readback, or ARM release.

### Current HW state after test.175

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled from the test path.
- Endpoint AER again shows `CESta Timeout+ AdvNonFatalErr+`; UESta is clear.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### PRE test.176 — host resetintr extraction after safe sleep

Do **not** run another hardware test until this note and the test.176 code/build
checkpoint are committed, pushed, and synced.

Implemented test.176 discriminator:
1. Relabeled active breadcrumbs to `test.176`.
2. Kept endpoint/root-port link-state logging and the existing chunked 442233 B
   firmware write unchanged for comparability.
3. Preserved test.175's safe `msleep(100)` after `fw write complete`.
4. Added only `resetintr = get_unaligned_le32(fw->data)` from host firmware
   memory and a log of that value.
5. Then releases `fw`/`nvram` and returns `-ENODEV`.
6. Still skips post-write ARM probe, resetintr device write/use, NVRAM write,
   readback, and ARM release. Stage0 remains the only intended run.

Hypothesis:
- Clean return/unload: host-side `resetintr` extraction/release is safe; next
  test should add NVRAM write after `msleep(100)`.
- Freeze: surprising, because this is host memory only; inspect for lifetime or
  scheduling interactions rather than device MMIO.

Pre-test checklist:
- [x] Code changed for host resetintr extraction after safe `msleep(100)`.
- [x] Build module via kbuild. Result OK; existing warning only:
  `brcmf_pcie_write_ram32` defined but not used. BTF skipped because `vmlinux`
  is unavailable.
- [x] Verified `brcmfmac.ko` contains `test.176`, `host resetintr`, and
  `released fw/nvram after host resetintr` markers.
- [x] Commit + push + sync this checkpoint.
- [ ] Run only stage0:
  `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-20, POST test.174 — immediate return SUCCESS)

### TEST.174 RESULT — clean unwind after complete fw write

Captured artifacts:
- `phase5/logs/test.174.stage0`
- `phase5/logs/test.174.stage0.stream`

Result: **SUCCESS / no crash.** test.174 completed the full 442233-byte BAR2
firmware write, released `fw`/`nvram` immediately after `fw write complete`,
returned `-ENODEV`, waited the harness's 30 seconds, and cleaned up `brcmfmac`
without freezing.

Key persisted markers:
```
BCM4360 test.174: all 110558 words written, before tail (tail=1)
BCM4360 test.174: tail 1 bytes written at offset 442232
BCM4360 test.174: fw write complete (442233 bytes)
BCM4360 test.174: released fw/nvram immediately after fw write; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
```

This is a strong discriminator: the completed firmware image in TCM is **not**
by itself enough to trigger the host freeze. The test survived for at least 30 s
after the completed write. The crash in tests 170-173 requires the driver to
remain in the post-write path long enough to hit the bad condition.

### Current HW state after test.174

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled from the test path.
- Endpoint AER shows `CESta Timeout+ AdvNonFatalErr+`; UESta is clear. This is
  new useful post-test evidence: no fatal/uncorrectable error, but at least one
  correctable completion-timeout style event was recorded.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### Interpretation

The current failure is no longer "complete firmware image causes inevitable
async host death." test.174 proves the host can remain alive after the complete
write if the driver returns immediately. The next highest-value distinction is
whether the old post-write failure is specifically caused by `mdelay()`/busy
waiting after heavy BAR2 writes, or by the next device MMIO operation after some
settle time.

### PRE test.175 — sleeping post-write dwell

Do **not** run another hardware test until this note and the test.175 code/build
checkpoint are committed, pushed, and synced.

Implemented test.175 discriminator:
1. Relabeled active breadcrumbs to `test.175`.
2. Kept endpoint/root-port link-state logging and the existing chunked 442233 B
   firmware write unchanged for comparability.
3. After `fw write complete`, the BCM4360 path now logs before/after a
   `msleep(100)` with no device MMIO.
4. It then releases `fw`/`nvram` and returns `-ENODEV` exactly like test.174.
5. Still skips post-write ARM probe, resetintr read, NVRAM write, readback, and
   ARM release. Stage0 remains the only intended run.

Hypothesis:
- `after post-fw msleep(100)` + clean return/unload: the old freeze is likely
  tied to post-write `mdelay()`/busy-wait dwell or CPU/context starvation after
  BAR2 writes. Next test can add the resetintr boundary after `msleep(100)`.
- Freeze before `after post-fw msleep(100)`: the bad condition is elapsed
  post-write time inside the callback, independent of whether the delay is busy
  or sleeping. Next step should quiesce/reset the chip immediately after the
  write before any dwell.

Pre-test checklist:
- [x] Code changed for `msleep(100)` after `fw write complete`.
- [x] Build module via kbuild. Result OK; existing warning only:
  `brcmf_pcie_write_ram32` defined but not used. BTF skipped because `vmlinux`
  is unavailable.
- [x] Verified `brcmfmac.ko` contains `test.175`, before/after
  `post-fw msleep(100)`, and `released fw/nvram after msleep` markers.
- [x] Commit + push + sync this checkpoint.
- [ ] Run only stage0:
  `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-20, POST test.173 — rebooted + SMC reset)

### TEST.173 RESULT — no-MMIO post-write idle loop still freezes

Captured artifacts:
- `phase5/logs/test.173.stage0`
- `phase5/logs/test.173.stage0.stream` (post-crash reboot stream only)
- `phase5/logs/test.173.journalctl.txt` (authoritative previous-boot journal)
- `phase5/logs/test.173.pstore.txt` (old EFI pstore entries; appears to be test.149-era
  rmmod/unregister noise, not this crash)

test.173 completed the same full BAR2 firmware write:
- `all 110558 words written, before tail (tail=1)`
- `tail 1 bytes written at offset 442232`
- `post-write ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`
- `fw write complete (442233 bytes)`

The no-device-MMIO idle loop then logged:
- `idle-0 before/after no-MMIO mdelay(10)`
- `idle-1 before/after no-MMIO mdelay(10)`
- ...
- `idle-7 before/after no-MMIO mdelay(10)`
- `idle-8 before no-MMIO mdelay(10)` was the last persisted marker.

No `idle-8 after`, no `idle-9`, no `post-idle-loop`, no resetintr read, no NVRAM
write, no MCE, no panic, and no PCIe/AER error were captured before the host
froze. SMC reset was required.

### Interpretation

The BAR0 ARM CR4 probes in tests 171/172 are not required to trigger the
post-write crash. test.173 removed device MMIO from the idle loop and still
froze in the same broad window: after a complete 442233-byte BAR2 firmware
write, while ARM CR4 was still halted, before resetintr/NVRAM/readback work.

The current best bound is approximately 80-90 ms after `fw write complete` in
test.173, with similar timing to test.172 and later than test.171. That supports
an asynchronous post-write chip/host event more than a specific BAR0 probe side
effect. Endpoint/root-port ASPM/CLKPM remains weak as a primary explanation
because test.172 showed root-port `LnkCtl=0x0040` during the run.

### Current HW state after SMC reset

- Endpoint 03:00.0 is visible: `Mem+ BusMaster+`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1. Sticky `CorrErr+ UnsupReq+ AuxPwr+` remain.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1.
- `lsmod | rg '^brcm|^bcma'` is empty; only external USB Wi-Fi stack modules
  (`mac80211`, `cfg80211`, mt76 users) are loaded.
- Note: after reboot, config space naturally shows endpoint/root-port ASPM
  enabled again. The test code disables/checks those during module load.

### PRE test.174 — immediate return after complete fw write

Do **not** run another hardware test until this note and the test.174 code/build
checkpoint are committed, pushed, and synced.

Implemented test.174 discriminator:
1. Relabeled active breadcrumbs to `test.174`.
2. Kept endpoint/root-port link-state logging and the existing chunked 442233 B
   firmware write unchanged for comparability.
3. Removed the post-write ARM CR4 probe and the 10 x 10 ms no-MMIO idle loop.
4. Immediately after `fw write complete`, the BCM4360 path now:
   - `release_firmware(fw)`,
   - `brcmf_fw_nvram_free(nvram)`,
   - logs `released fw/nvram immediately after fw write; returning -ENODEV`,
   - returns `-ENODEV`.
5. Skips resetintr read, NVRAM write, NVRAM marker readback, TCM dump, and ARM
   release. Stage0 remains the only intended run.

Hypothesis:
- Clean `-ENODEV` unwind + rmmod succeeds: the crash needs post-write dwell
  time inside or after `download_fw_nvram`; next test can progressively add
  `mdelay(1/5/10/20/50)` before return, or immediately quiesce/reset the chip.
- Freeze even with immediate return: the completed firmware image in TCM triggers
  an asynchronous failure regardless of driver dwell; next step should be a
  post-write chip/PCIe quiesce before returning.
- Clean return but freeze later during module unload: focus on remove/unregister
  path state after a completed write.

Pre-test checklist:
- [x] Code changed for immediate post-fw-write return.
- [x] Build module via kbuild. Result OK; existing warning only:
  `brcmf_pcie_write_ram32` defined but not used. BTF skipped because `vmlinux`
  is unavailable.
- [x] Verified `brcmfmac.ko` contains `test.174` and the immediate-return
  marker; no `idle-` / `post-idle-loop` strings remain.
- [x] Commit + push + sync this checkpoint.
- [ ] Run only stage0:
  `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Current state (2026-04-20, POST test.169 — DUAL BREAKTHROUGH; rebooted + SMC reset)

### TEST.169 RESULT — TWO MAJOR FINDINGS

**Finding 1: probe-address mismatch RESOLVED.**
```
post-145    loW IOCTL=0x00000001 RESET_CTL=0x0  |  hiW IOCTL=0x00000021 RESET_CTL=0x0
setup-entry loW IOCTL=0x00000001 RESET_CTL=0x0  |  hiW IOCTL=0x00000021 RESET_CTL=0x0
pre-attach   ... same loW=0x01/0 ... hiW=0x21/0
post-attach  ... same loW=0x01/0 ... hiW=0x21/0
post-raminfo ... same loW=0x01/0 ... hiW=0x21/0
pre-download ... same loW=0x01/0 ... hiW=0x21/0
pre-halt     ... same loW=0x01/0 ... hiW=0x21/0
post-halt    ... same loW=0x01/0 ... hiW=0x21/0
post-write   ... same loW=0x01/0 ... hiW=0x21/0
```
hiW (BAR0 window=base+0x100000, offsets 0x408/0x800) sees IOCTL bit 0x20 set =
**CPUHALT=1** consistently. loW (base+0x1000) reads a different register that
shows CLK=1 only. **Conclusion:** BCM4360 ARM CR4 wrapper is at the canonical
BCMA AI offset (`base + 0x100000`), NOT at `base + 0x1000`. test.142/146/167/168
loW probes were reading the wrong register. ARM CR4 has actually been halted
correctly by `brcmf_chip_set_passive` since test.145 the entire time.

**Finding 2: 442KB fw write COMPLETED for the first time across tests 163–169.**
All 110558 words + 1 tail byte iowrite32'd; "fw write complete" logged at 12:25:06.
ARM CR4 hiW view = CPUHALT=1 *after* the write — write did not un-halt CR4.

→ **The "ARM running garbage" theory is dead.** ARM was halted throughout
  every prior crash. The 163–168 mid-write crashes were a different cause —
  likely intermittent (maybe timing/MMIO ordering, possibly async PCIe
  completion variance). The added dual-view probes inserted small MMIO
  read pauses across the path which may have had a quietening effect.

**Crash now happens AFTER "fw write complete" and BEFORE any post-write log.**
No NVRAM-loaded marker, no TCM verify dump, no ramsize-4 marker, no
pre-ARM clk_ctl_st marker. → Crash is in the brief code window:
  `mdelay(100)` → `get_unaligned_le32(fw->data)` → `release_firmware(fw)` →
  `if (nvram) { copy_mem_todev(NVRAM); ... }` → `read_ram32(ramsize-4)`.
NVRAM `copy_mem_todev` is the most likely site (next host→TCM bulk write,
and the only one of these calls that does substantial MMIO).

### POST-TEST PCIe STATE (2026-04-20, reboot + SMC reset — NOW)
- `lspci -vvv -s 03:00.0`: `Mem+ BusMaster+`, `MAbort-`, `<MAbort-`,
  `LnkSta 2.5GT/s x1`, `CommClk+`, sticky `CorrErr+ UnsupReq+ AuxPwr+`.
- `lsmod | grep brcm` → empty. `ls /sys/fs/pstore/` → empty (no new oops).
- Module not yet rebuilt for test.170 (NOT yet rebuilt after edits).

### PLAN FOR TEST.170 — LOCALIZE POST-FW CRASH + DROP loW probe
**Goal:** Pinpoint which post-fw step crashes the host. Read-only diagnostics
plus existing chunked-write pattern for NVRAM.

**Code changes (all inside `brcmf_pcie_download_fw_nvram` after line 1960):**
1. After `mdelay(100)` after "fw write complete" → log
   `BCM4360 test.170: post-mdelay100`.
2. After `get_unaligned_le32` and `release_firmware` → log
   `BCM4360 test.170: after release_firmware resetintr=0x%08x`.
3. Inside the `if (nvram)` block before `copy_mem_todev` → log
   `BCM4360 test.170: pre-NVRAM write address=0x%x len=%u`.
4. Replace the NVRAM `copy_mem_todev` with a chunked iowrite32 loop
   identical in shape to the 442KB writer (4 KB or 8 KB chunks with
   per-chunk breadcrumbs + 50 ms `mdelay` between chunks). NVRAM is
   small (a few KB) so this is at most a few breadcrumbs.
5. After NVRAM write → log
   `BCM4360 test.170: post-NVRAM write done`.
6. After `brcmf_pcie_read_ram32(ramsize-4)` → keep existing
   "NVRAM marker" log; nothing new here.

**Other changes:**
- Drop the loW probe from the dual-view helper (it reads garbage and
  doubles MMIO traffic). Just print the hiW view as the canonical view.
- Keep all the setup-path probe call sites; they're a useful sanity
  check that ARM stays halted.
- Bump banner test.169 → test.170 across pcie.c and test-staged-reset.sh.

**Risk review:** all additions are read-only OR mirror the proven 442KB
chunked write pattern. NVRAM writes were doing the same loop in 1 shot
before — chunking just adds breadcrumbs. Crash blast-radius unchanged.

### HYPOTHESIS for test.170
Expect to see `post-mdelay100` and `after release_firmware` (host-only
work). The crash candidate set narrows to one of:
- `pre-NVRAM write` printed but no `wrote N bytes` chunk → crash in the
  *first* NVRAM iowrite32 (likely TCM-side address fault or PCIe abort).
- Some chunks printed, then a hang → crash mid-NVRAM-write (less likely;
  fw-write was 442KB without crashing in test.169).
- All chunks + `post-NVRAM write done` printed, then hang → crash in
  the post-NVRAM `read_ram32` or the BCM4360-block reads of clk_ctl_st.

Ideally the 4 KB-or-so NVRAM writes complete and we get our first ever
"NVRAM marker at ramsize-4" line — confirming end-to-end FW + NVRAM
load against a halted ARM. Then we'd need to start releasing ARM.

### PRE-TEST.170 CHECKLIST
- [x] Save test.169 journal to `phase5/logs/test.169.journalctl.txt`
- [x] PCIe state checked: clean (`Mem+ BusMaster+ MAbort- <MAbort- LnkSta 2.5GT/s x1`)
- [x] Edit pcie.c: probe helper collapsed to single hi-window read (drop loW),
      added post-fw-write breadcrumbs (post-mdelay100 / after release_firmware /
      pre-NVRAM write / chunked NVRAM iowrite32 with breadcrumbs / post-NVRAM done)
- [x] Bumped banners test.169 → test.170 across pcie.c, test-staged-reset.sh
- [x] Built via kbuild — `brcmfmac.ko` contains 16 test.170 format strings,
      1 unrelated unused-function warning
- [x] Commit + push pre-test state + `sync`
- [ ] Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-20, POST test.168 CRASH — machine rebooted + SMC reset)

### TEST.168 RESULT — ALL 6 PROBES SHOW CPUHALT=0 / RESET_CTL=0

**Captured markers from `journalctl -k -b -1`** (saved to
`phase5/logs/test.168.journalctl.txt`):
```
test.168: setup-entry   ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.168: pre-attach    ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.168: post-attach   ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.168: post-raminfo  ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.168: pre-download  ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.142: RESET_CTL=0 IOCTL=0x0001 CPUHALT=NO FGC=NO CLK=YES   (enter_download_state)
test.168: pre-halt      ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.168: re-halting ARM CR4 via brcmf_chip_set_passive
test.168: post-halt     ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)   <-- halt call NOT visible
test.168: starting chunked fw write
test.168: wrote 4096 words ... test.168: wrote 98304 words (393216 bytes)
<CRASH at 98304 words — same pattern as test.164/165/166>
```

**Two major observations:**

1. **CPUHALT is clear at EVERY probe point** — IOCTL=0x0001 (CLK=1, CPUHALT=0, FGC=0)
   from the very first probe (`setup-entry`, which runs as soon as the async
   fw-request callback fires). So by the time the callback fires, ARM CR4 is already
   un-halted — or never was halted at a register the probe can see.
2. **The pre-halt / set_passive / post-halt triple is a no-op as seen by the probe** —
   pre-halt=0x0001/0, set_passive runs, post-halt=0x0001/0. The probe sees ZERO state
   change from set_passive. Either (a) set_passive's MMIO writes target a different
   address than our probe reads from, or (b) the chip hardware ignored the writes,
   or (c) some side-effect immediately reverted them.

**Probe-address discrepancy hypothesis (high priority to verify in test.169):**
- Our probe: BAR0 window = `core->base` (0x18002000 for CR4), reads offsets 0x1408
  (IOCTL) and 0x1800 (RESET_CTL). Implicitly assumes the CR4 wrapper registers
  are at `core->base + 0x1000`.
- `brcmf_chip_set_passive` → `brcmf_chip_disable_arm` → `brcmf_chip_resetcore`
  writes IOCTL/RESET_CTL at `cpu->wrapbase + BCMA_IOCTL (0x408)` and
  `cpu->wrapbase + BCMA_RESET_CTL (0x800)`. `wrapbase` is populated by
  the BCMA erom scan and is **not** necessarily `core->base + 0x1000`.
- Historical note: test.142 (commit 743c86d) wrote RESET_CTL=1 at BAR0+0x1800
  (window=core->base) and read back 0x1 → the probe offsets *did* move RESET_CTL
  for that one write. That means either (i) wrapbase really IS at base+0x1000 on
  BCM4360 CR4, OR (ii) the 0x1800 MMIO hit some separate register that happened
  to also read as 1 after a write of 1 (unlikely for RESET_CTL-shaped behaviour).

**Crash repeats the pattern:** last breadcrumb 98304 words (393216 B) at 11:57:40.
test.164/165/166/168 all crashed at ~340–400 KB into the 442 KB write. Offsets
are not identical but are tightly clustered — consistent with ARM executing
partially-written garbage that asynchronously breaks the host link. Host hang,
no pstore oops.

### POST-TEST PCIe STATE (2026-04-20, reboot + SMC reset — NOW)

- `git status`: clean main at `91b61fc`; untracked test.168 stage0 / stream logs.
- Module not re-built yet post-reboot; need `make -C phase5/work` before any
  additional `insmod`.
- `lspci` not yet re-checked for this boot (pre-test-169 checklist).

### PLAN FOR TEST.169 — RESOLVE PROBE-ADDRESS VS set_passive DISCREPANCY

**Goal:** Determine whether `brcmf_chip_set_passive` actually halts CR4 at the
register address *we think it does*. Two independent diagnostics, both read-only.

**Change A: add an immediate-post-set_passive probe inside buscore_reset**
(tag `test.169: post-145` — runs 1 line after test.145's `brcmf_chip_set_passive(chip)`).
This is the narrowest possible time window after a halt call; if CPUHALT is ever
going to read as 1, it will read as 1 here.

**Change B: in the probe helper, additionally read IOCTL/RESET_CTL using chip.c's
authoritative path** — `ci->ops->read32(ci->ctx, cpu->wrapbase + BCMA_IOCTL)` and
`... + BCMA_RESET_CTL`. Log both (probe-addr view + chip.c view) side-by-side.
If the two views disagree, we have a definitive address mismatch.

**Hypothesis matrix for test.169:**
| post-145 probe-view | post-145 chip.c-view | Interpretation                     |
|---------------------|----------------------|------------------------------------|
| CPUHALT=1           | CPUHALT=1            | set_passive worked; un-halt happens *between* test.145 and setup-entry — narrow the gap with more probes |
| CPUHALT=0           | CPUHALT=1            | probe address is wrong; real halt is holding, crash theory needs revisiting |
| CPUHALT=0           | CPUHALT=0            | set_passive does not in fact halt CR4 on BCM4360; need a manual halt sequence (as test.142 did at probe time) |
| CPUHALT=1           | CPUHALT=0            | extremely unlikely — chip.c's own read sees no halt but the probe does |

**Risk review:** both changes are read-only. No new writes. Blast-radius identical
to test.168. Keep the re-halt call in download_fw_nvram unchanged so we still
get the pre-halt/post-halt data point.

**Kept unchanged from test.168:** chunked 16 KB/50 ms fw write, NVRAM write,
TCM verify dump, `-ENODEV` early return, `bcm4360_skip_arm=1` default, 6 setup-path
probes.

### PRE-TEST.169 CHECKLIST

- [x] Save test.168 journal to `phase5/logs/test.168.journalctl.txt`
- [x] Edit pcie.c: extended probe helper to a dual-view read (loW=base+0x1000
      and hiW=base+0x100000). Added `post-145` probe immediately after
      `brcmf_chip_set_passive` inside buscore_reset. pre-halt/post-halt/post-write
      blocks inside download_fw_nvram converted to dual-view probe calls.
- [x] Bumped test.168 → test.169 across pcie.c, test-staged-reset.sh banners.
- [x] Build OK (kbuild, 1 unrelated warning). `brcmfmac.ko` contains 11 test.169
      format strings including the new dual-view log line and post-145/pre-halt/
      post-halt/post-write/probe-site tags.
- [x] PCIe 03:00.0: `Mem+ BusMaster+ MAbort- <MAbort-`, `LnkSta 2.5GT/s x1`,
      `CommClk+`, sticky `CorrErr+ UnsupReq+` from test.168 crash (harmless).
      `lsmod | grep brcm` empty. Safe to insmod.
- [ ] Commit + push this pre-test state + `sync`
- [ ] Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

### HYPOTHESIS for test.169

Expect the 7+ dual-view probe lines (post-145, setup-entry, pre-attach,
post-attach, post-raminfo, pre-download, pre-halt, post-halt, post-write) to
report BOTH views on a single log line. The critical diagnostic is the
**hiW view at `post-145`** — immediately after set_passive:

- If `hiW IOCTL` shows CPUHALT=1 (bit 0x20 set) → set_passive is working;
  the probe address is wrong; crash theory needs re-examination.
- If `hiW IOCTL` shows CPUHALT=0 like the loW view → set_passive genuinely
  does not halt CR4 on BCM4360; need a manual halt sequence mirroring
  test.142's probe-time IOCTL|FGC|CLK write path.
- If one view errors or reads 0xffffffff → wrapbase is neither of the
  candidates; need erom dump to find it.

---

## Previous state (2026-04-20, POST test.167 CRASH — machine rebooted + SMC reset)

### TEST.167 RESULT — setup callback crashed BEFORE any fw-write code

**Captured markers from `journalctl -k -b -1`** (saved to
`phase5/logs/test.167.journalctl.txt`):
```
11:25:13 BCM4360 test.167: module_init entry — re-halt ARM CR4 before 442KB BAR2 fw write
11:25:14 BCM4360 test.167: before pci_register_driver
11:25:14 BCM4360 test.128: PROBE ENTRY
11:25:15 BCM4360 test.53:  SBR via bridge (probe-start SBR complete)
11:25:15 BCM4360 test.158: before brcmf_chip_attach
11:25:16 BCM4360 test.125: buscore_reset entry / reset_device bypassed
11:25:16 BCM4360 test.145: halting ARM CR4 after second SBR (buscore_reset)    <-- ARM halted here
11:25:16 BCM4360 test.145: ARM CR4 halt done — skipping PCIE2 mailbox clear; returning 0
11:25:16 BCM4360 test.119: brcmf_chip_attach returned successfully
11:25:16 BCM4360 test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)
... (test.158 ASPM disable, test.159 reginfo/alloc, test.160 alloc+fw_request, test.161 get_firmwares)
11:25:22 BCM4360 test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0   <-- LAST USEFUL MARKER
11:25:22 BCM4360 test.167: pci_register_driver returned ret=0
<no further log — system frozen>
```

**Missing markers (expected per pcie.c:3727-3802):**
`test.128: before brcmf_pcie_attach`, `test.128: after brcmf_pcie_attach`,
`test.134: post-attach before fw-ptr-extract`, `test.134: after kfree(fwreq)`,
`test.130: before brcmf_chip_get_raminfo`, `test.130: after brcmf_chip_get_raminfo`,
`test.130: after brcmf_pcie_adjust_ramsize`, `test.163: before brcmf_pcie_download_fw_nvram`,
and ALL test.167-specific fw-write markers (pre-halt, post-halt, write breadcrumbs,
post-write). → Crash hit inside the setup callback during the `msleep(300)` that
follows test.162's log line, or inside `brcmf_pcie_attach` before the first
post-attach marker flushed.

**No new pstore dump.** The existing `/sys/fs/pstore/dmesg-efi_pstore-*` entries
are from Mon 2026-04-20 07:46 (an earlier crash, `[ 588s]` after that boot).
No panic message was written for the 11:25 crash → pure CPU hang, not an oops.

**Interpretation (hypothesis, high confidence):**
test.166 established that ARM CR4 is running (RESET_CTL=0x0) at fw-write time
despite having been halted at buscore_reset (test.145). That means ARM un-halts
somewhere between test.145 and fw-write. If ARM runs *garbage* firmware, it
can execute MMIO reads/writes or DMA that crash the host at a non-deterministic
point. test.166 crashed during fw-write; **test.167 crashed earlier, during the
msleep(300)+mdelay(300) chain at the start of `brcmf_pcie_setup`**, which fits
the same root cause. The code change in test.167 was entirely inside
`brcmf_pcie_download_fw_nvram`, which was never reached, so the new code
cannot be the crash trigger.

### POST-TEST PCIe STATE (2026-04-20, reboot + SMC reset — NOW)

- `sudo lspci -vvv -s 03:00.0`:
  - `Mem+ BusMaster+`, `MAbort-`, `<MAbort-`
  - `LnkSta 2.5GT/s x1`, `LnkCtl ASPM L0s/L1 Enabled; CommClk+`
  - `DevSta CorrErr+ UnsupReq+ AuxPwr+` (CorrErr+/UnsupReq+ sticky from prior crash, harmless)
- `lsmod | grep brcm` → empty. Device safe to insmod.

### PLAN FOR TEST.168 — MAP WHERE ARM CR4 UN-HALTS IN SETUP

**Goal:** pinpoint the exact setup-callback stage at which ARM CR4 RESET_CTL
transitions 0x1 → 0x0 (halted → running). Read-only diagnostic — no behavioral
change, so crash blast-radius is identical to test.167 (still a host hang
candidate if ARM is already running garbage at callback entry).

**Code changes (all inside `brcmf_pcie_setup`, pcie.c ~3712-3802):**
Add an inline helper `brcmf_pcie_probe_armcr4(devinfo, "<tag>")` that:
  1. Saves the current BAR0 window register.
  2. Points the BAR0 window at `ci->pub.ccrev < X ? 0x18002000 : core->base`
     (the ARM_CR4 core we already located — pcie.c:3404 area).
  3. Reads IOCTL and RESET_CTL via a BAR0-window read (same technique as the
     test.166 pre-write read that worked).
  4. Restores the saved BAR0 window.
  5. `pr_emerg("BCM4360 test.168: <tag> ARM CR4 IOCTL=0x%x RESET_CTL=0x%x (IN_RESET=%s)\n", ...)`.

Call sites inside `brcmf_pcie_setup`:
  (a) Right after `test.162: CALLBACK INVOKED` log → tag `setup-entry`
  (b) Right before `test.128: before brcmf_pcie_attach` → tag `pre-attach`
  (c) Right after `test.128: after brcmf_pcie_attach` → tag `post-attach`
  (d) Right before `test.130: before brcmf_chip_get_raminfo` → tag `pre-raminfo`
  (e) Right after `test.130: after brcmf_chip_get_raminfo` → tag `post-raminfo`
  (f) Right before `test.163: before brcmf_pcie_download_fw_nvram` → tag `pre-download`
Plus keep the existing pre-write probe inside `download_fw_nvram` (tag
`pre-write`) — that's the 7th measurement point.

**Hypothesis matrix for test.168:**
| Stage   | Expected if  | Expected if un-halted    | Meaning                            |
|---------|--------------|--------------------------|------------------------------------|
| setup-entry | 0x1       | 0x0                      | un-halt happened DURING the ~6s between test.145 and the fw-request async callback (most likely candidate) |
| pre-attach  | 0x1       | 0x0 (if setup-entry=0x1) | un-halt during brcmf_pcie_attach internals |
| post-attach | 0x1       | 0x0                      | un-halt inside brcmf_pcie_attach |
| pre-raminfo | 0x1       | 0x0                      | un-halt between attach and raminfo (mdelay window) |
| post-raminfo| 0x1       | 0x0                      | un-halt inside brcmf_chip_get_raminfo |
| pre-download| 0x1       | 0x0                      | un-halt in ramsize adjust |
| pre-write (existing) | 0x0 (per test.166) |            | confirmed previously |

**Risk review for the probe itself:**
- Reading RESET_CTL via BAR0 window is proven (test.166 did it once and lived
  long enough to start the fw write). Six additional reads are an extra ~150
  config-space writes + 6 BAR0 MMIO reads — negligible.
- `brcmf_chip_set_passive` has a side effect (actually halts ARM). A plain
  RESET_CTL read does NOT. So the probe is truly diagnostic.
- We will NOT re-halt ARM in test.168 — that is test.169's job, once we know
  WHERE to put the halt.

**Kept from test.167 (unchanged):**
- chunked 16KB fw-write loop (will be reached only if ARM stays halted long
  enough; if pre-write probe shows RESET_CTL=0x0 we'll expect a mid-write
  crash again).
- NVRAM write + TCM verify dump + early `-ENODEV` return.
- `bcm4360_skip_arm=1` module-param default.

### PRE-TEST.168 CHECKLIST

- [x] Save test.167 journal to phase5/logs/test.167.journalctl.txt
- [x] Commit + push test.167 logs and this post-crash analysis (commit `de73d72`)
- [x] Implement test.168 probe helper + 5 new call sites in pcie.c (setup-entry,
      pre-attach, post-attach, post-raminfo, pre-download) — plus the existing
      pre-halt/post-halt/pre-write/post-write probes inside download_fw_nvram
- [x] Bump module_init + register banners + download_fw_nvram log lines to test.168
- [x] Bump `test-staged-reset.sh` log prefix test.167 → test.168
- [x] Build OK (kbuild, 1 unrelated warning). `strings brcmfmac.ko` shows 14
      test.168 format strings + all 5 new probe-site tags (setup-entry,
      pre-attach, post-attach, post-raminfo, pre-download)
- [x] PCIe 03:00.0: `Mem+ BusMaster+ MAbort- <MAbort-`, `LnkSta 2.5GT/s x1`,
      `CommClk+`, sticky `CorrErr+ UnsupReq+` from test.167 crash (harmless).
      `lsmod | grep brcm` empty. Safe to insmod.
- [ ] Commit + push pre-test state + `sync`
- [ ] Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-20, POST test.166 CRASH — machine rebooted + SMC reset)

### TEST.166 RESULT — DECISIVE: ARM CR4 IS NOT HALTED AT FW-WRITE TIME

**Captured markers from journal -b -1 (saved to `phase5/logs/test.166.journalctl.txt`):**
```
test.166: pre-write ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 (IN_RESET=NO)
test.166: starting chunked fw write, total_words=110558 (442233 bytes) tail=1
test.166: wrote 4096 words (16384 bytes)   <- breadcrumb 1
...
test.166: wrote 90112 words (360448 bytes) <- breadcrumb 22 (last surviving)
<no further log — system frozen>
```

**Interpretation:**
- **ARM CR4 is RUNNING, not halted** — `RESET_CTL=0x0000000` + `IN_RESET=NO` at the moment
  the fw write begins. Despite test.145 halting ARM after buscore_reset, something in the
  setup path between then and download_fw_nvram un-halted it (candidates: fw_get_firmwares
  async wait ~1-3s, setup callback, msleep(300)s, a HW watchdog).
- **Crash offset is non-deterministic** — test.164 crashed at 425984 B, test.165 at
  340992 B, test.166 at 360448 B (between 90112 and 94208 words). The spread
  (~16–85 KB) is incompatible with a fixed TCM boundary; it is consistent with ARM
  running partially-written firmware, which eventually executes something that crashes
  the host (e.g. MMIO abort on BAR2, link drop, DMA into driver memory).
- **Crash theory #1 (ARM auto-resume) is CONFIRMED** (for this phase). Theory #2 (async
  watchdog) not ruled out but less likely — the spread is byte-count driven, not
  wall-clock driven (test.165 used 20 ms × 340 chunks ≈ 7 s; test.166 used 50 ms × 22
  chunks ≈ 1 s — very different wall-clock windows, similar-ish byte offsets).

### CODE STATE

- Branch main at `5fcdd93` (test.166 implementation). Module built.
- Untracked log files: `phase5/logs/test.166.stage0`, `test.166.stage0.stream`,
  `test.166.journalctl.txt`.

### POST-TEST PCIe STATE (2026-04-20, reboot + SMC reset)

- `sudo lspci -vvv -s 03:00.0` shows: `Mem+ BusMaster+` (stale), `MAbort-`, `LnkSta
  2.5GT/s x1`, `LnkCtl CommClk+ ASPM L0s/L1 Enabled`, `DevSta CorrErr+ UnsupReq+`.
- The UnsupReq+/CorrErr+ are sticky leftovers from the crash (expected post-SMC on
  the link). MAbort-/LnkSta are clean — safe to reload.
- `lsmod | grep brcm` → nothing loaded.

### PLAN FOR TEST.167 — RE-HALT ARM CR4 JUST BEFORE FW WRITE

**Goal:** Verify whether halting ARM CR4 immediately prior to the 442 KB BAR2 write
(with post-halt/post-write RESET_CTL checks) stops the crash. This isolates "ARM
running garbage firmware" from "async watchdog / link teardown".

**Code changes (pcie.c `brcmf_pcie_download_fw_nvram`, BCM4360 branch around line
1860–1915):**
1. Keep the existing pre-write RESET_CTL read (shows `0x0` — ARM running).
2. After the pre-read, call `brcmf_chip_set_passive(devinfo->ci)` to re-halt ARM CR4.
   Using the public chip API avoids the direct-RESET_CTL-write wedging seen in
   test.157/test.158 (that was a probe-time duplicate halt; this is after a
   ~4-second gap since test.145, different context).
3. `mdelay(100)` to let halt settle.
4. Read RESET_CTL again — expect `0x0001` (`IN_RESET=YES`). Log as
   `test.167: post-halt`.
5. Do the chunked 16 KB/50 ms fw write (identical to test.166).
6. After the write loop + tail, read RESET_CTL once more — log as `test.167:
   post-write`. This catches the case where the write itself un-halts ARM partway.
7. Keep NVRAM write + TCM verify + -ENODEV return unchanged from test.166.

**Hypothesis for test.167:**
- **Success case:** post-halt=0x1, write completes, post-write=0x1, line
  `test.167: fw write complete (442233 bytes)` prints. → ARM-resume is the root
  cause. Next step: figure out what un-halts ARM in the setup path OR move the halt
  to immediately before download (and keep it there permanently).
- **Write crashes mid-way with post-halt=0x1:** something un-halts ARM during the
  write, OR a separate mechanism (watchdog) crashes the host independently. Need
  mid-write RESET_CTL polls.
- **post-halt=0x0 (halt failed):** `brcmf_chip_set_passive` no-op at this point
  (unexpected; chip core still registered). Fall back to direct RESET_CTL=1 write
  via BAR0 window.

**Risk:** Duplicate halt wedged ARM-core BAR0 window in test.157 (per pcie.c:4141
comment). This was at probe entry; test.167 halts much later after chip is fully
enumerated and ARM has been released/re-halted several times. Accept the risk —
crash blast radius is identical to test.166 (hard reboot).

### PRE-TEST CHECKLIST

- [x] Save test.166 journal to phase5/logs/test.166.journalctl.txt
- [x] Commit + push test.166 logs and this post-analysis (`453e2b5`)
- [x] Implement test.167 in pcie.c (halt + post-halt RESET_CTL read + post-write)
- [x] Bump module_init + register banners to test.167
- [x] Bump `test-staged-reset.sh` log prefix test.166 → test.167
- [x] Build OK (kbuild), .ko contains all 13 test.167 markers
- [x] PCIe 03:00.0 clean: MAbort-, CommClk+, LnkSta 2.5GT/s x1; sticky
      CorrErr+/UnsupReq+ from test.166 crash (harmless). brcmfmac NOT loaded.
- [ ] Commit + push pre-test state + `sync`
- [ ] Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-20, POST test.164 CRASH — machine rebooted, no SMC reset)

### RESULT: test.164 CRASHED in the FINAL 16KB chunk of the 442KB fw write

**Breadcrumbs captured (journal -b -1):**
- All 26 × 16KB breadcrumbs fired cleanly up to word 106,496 / 425,984 bytes.
- Crash happened between word 106,497 and word 110,558 (tail word) — i.e.,
  somewhere in bytes **425,984..442,233** of the firmware.
- Crash range = last 4,062 words (16,248 bytes) + 1 tail byte.

**Post-crash state (2026-04-20 ~11:00):**
- Hard reboot performed; NO SMC reset.
- Device enumerates cleanly (BAR0=0xb0600000, BAR2=0xb0400000 [disabled]).
- 03:00.0: Control Mem- BusMaster-, MAbort-, LnkSta 2.5GT/s x1, CommClk-.
- brcmfmac not loaded.

**Logs preserved:**
- `phase5/logs/test.164.stage0` — harness stage 0 log (minimal, crash killed stream)
- `phase5/logs/test.164.stage0.stream` — post-reboot kernel boot log (no test markers)
- `phase5/logs/test.164.journalctl.txt` — prior-boot journal WITH all test.164 breadcrumbs

### Interpretation

1. **Writes 0..425,984 bytes are safe.** 26 consecutive 16KB breadcrumbs show
   the BAR2 iowrite32 loop works fine for the first 425KB.
2. **The LAST ~16KB of firmware triggers the crash.** Either:
   (a) a specific word in 425,984..442,232, or
   (b) the tail byte write (single iowrite32 of partial word), or
   (c) something after the write completes but before the next breadcrumb lands
       (e.g. if the write barrier flush itself is what crashes).
3. rambase=0 ramsize=0xa0000 (640KB). fw ends at offset 442,233 — WELL below
   top-of-TCM. This is not a TCM-overflow.
4. **Possible theories:**
   - TCM has an internal boundary around 0x68000 (425,984) — writes crossing
     it fail. Speculative but the round number is suggestive.
   - Specific firmware data triggers a hardware state change (unlikely in
     halted-ARM TCM — should just be dumb RAM).
   - Cumulative timing/state effect after ~100K writes.
   - Tail-word write path (single 1-byte payload packed into u32) is buggy.

### Plan for test.165 — narrow the crash to exact word

**Changes:**
1. Reduce `chunk_words` from 4096 (16KB) → **256 (1KB)**. Gives ~432
   breadcrumbs over the 442KB, landing the crash into a ≤1KB window.
2. Reduce `mdelay(50)` between chunks → `mdelay(20)`. 432 × 20ms = 8.6s —
   fine, still flushes reliably.
3. Add explicit pre-tail and post-tail breadcrumbs (already have a tail
   breadcrumb; add one BEFORE the tail iowrite32 as well).
4. Add a breadcrumb AFTER the final word write but BEFORE the tail, so we
   distinguish "crashed in last word" vs "crashed in tail byte".
5. Keep everything else identical (bcm4360_skip_arm=1, post-download fail
   bypass, NVRAM write, TCM dump, -ENODEV return).

**Hypothesis for test.165:**
- If crash is deterministic at a specific word offset → we'll pinpoint to 1KB.
- If crash is timing/cumulative → we may see it move (or vanish with slower
  pacing from more mdelays).
- If crash is in the tail byte path → pre-tail breadcrumb survives, post-tail
  does not.

**Risk:** Still a hardware-contact test. Machine may crash again.

### Pre-test checklist

- [x] Implement test.165 changes in pcie.c
- [x] Build (`make -C phase5/work`)
- [x] Verify .ko contains test.165 markers
- [x] Re-check PCIe state of 03:00.0 (MAbort-, LnkSta 2.5GT/s, clean)
- [x] Commit + push plan before insmod
- [x] `sync` filesystem

---

## Previous state (2026-04-20, PRE test.164 — REBUILT, ready for insmod)

### CODE STATE: test.164 implemented — chunked 442KB fw write with per-16KB breadcrumbs

**What test.164 changes vs test.163:**
- In `brcmf_pcie_download_fw_nvram`, the BCM4360 path no longer calls
  `brcmf_pcie_copy_mem_todev` for the firmware copy. Instead it runs an
  inline 32-bit iowrite32 loop (same write pattern as copy_mem_todev) that
  emits a `pr_emerg` breadcrumb every 16KB (every 4096 words) + `mdelay(50)`
  to ensure the line reaches the console before the next chunk starts.
- 442233 bytes / 16384 ≈ 27 breadcrumbs before the tail.
- NVRAM write, TCM dump, and -ENODEV return all unchanged from test.163.
- Module_init / pcie_register banners updated from test.163 → test.164.

**Hypothesis for test.164:**
- If the crash is triggered by a specific word offset (say, the first one that
  touches a bad region of TCM), the last-surviving breadcrumb pins it to a
  16KB band. We expect to see either:
    (a) all 27 breadcrumbs + the "fw write complete" line → crash is later
        (NVRAM write or readback), OR
    (b) crash after breadcrumb N → failure lies in words 4096·N .. 4096·(N+1).
- If (a), we keep narrowing by moving the breakpoint forward.
- If (b), the offset lets us decide whether to try smaller chunks, delays,
  or suspect a specific TCM region (e.g., near the top where NVRAM lands).

**Not addressed in test.164 (keep on list):**
- test.142 still reads RESET_CTL at core->base+0x1800 which is the wrong
  register. We still don't have a reliable ARM-halt check at download time.
  Will fix later (likely test.165) with a proper wrapbase-based read.

**Pre-test PCIe state (2026-04-20 ~10:30):**
- 03:00.0: Control Mem- BusMaster- (no driver bound — normal).
- DevSta: CorrErr- NonFatalErr- FatalErr- UnsupReq- (clean).
- MAbort-, LnkSta 2.5GT/s Width x1, LnkCtl ASPM Disabled CommClk-.

**Build status:** REBUILT; .ko contains test.164 markers (module_init,
chunked-write breadcrumbs, etc.). No build warnings of concern.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Note:** NO SMC reset was done after the test.163 crash. Device enumerates
cleanly, so we proceed. If test.164 also crashes, may need to try SMC reset
before further attempts.

---

## Previous state (2026-04-20, POST test.163 CRASH — machine rebooted, no SMC reset)

### RESULT: test.163 CRASHED during the 442KB BAR2 iowrite32 (copy_mem_todev)

**Last markers captured (stream + journal-b-minus-1 agree):**
```
test.163: before brcmf_pcie_download_fw_nvram (442KB BAR2 write)
test.142: enter_download_state — confirming ARM CR4 reset state
test.142: ARM CR4 state RESET_CTL=0x00000000 IN_RESET=NO/BAD IOCTL=0x0001 CPUHALT=NO FGC=NO CLK=YES
BCM4360 debug: rambase=0x0 ramsize=0xa0000 srsize=0x0 fw_size=442233 tcm=ffffcab302600000
test.138: pre-BAR2-ioread32 (tcm=ffffcab302600000)
test.138: post-BAR2-ioread32 = 0x024d4304 (real value — BAR2 accessible)
<no further log — machine died, hard reboot required>
```

**Post-crash state (2026-04-20 ~10:26):**
- Hard reboot performed; NO SMC reset.
- Device enumerates cleanly (BAR0=0xb0600000, BAR2=0xb0400000).
- Control I/O-/Mem-/BusMaster- and BARs [disabled] as expected (no driver bound).
- MAbort-, link clean.
- brcmfmac not loaded.

**Logs preserved:**
- `phase5/logs/test.163.stage0` — harness stage 0 log
- `phase5/logs/test.163.stage0.stream` — live dmesg stream
- `phase5/logs/test.163.journalctl.txt` — full prior-boot journal (brcmf + bcm4360)

### Crash analysis

1. **BAR2 is alive just before the crash** — the ioread32 at offset 0 returns
   0x024d4304 (real TCM contents), so BAR2 mapping is valid.
2. **copy_mem_todev starts writing 442,233 bytes (110,558 × iowrite32)** —
   no breadcrumb inside the loop, so crash is somewhere in those writes.
   No further log lands before the machine dies.
3. **ARM CR4 state reading is UNRELIABLE in test.142** — the current code does:
   ```
   brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4);
   reset_ctl = brcmf_pcie_read_reg32(devinfo, 0x1800);
   ```
   `select_core` sets BAR0 window to CR4 `core->base`, but RESET_CTL lives at
   **wrapbase + BCMA_RESET_CTL (0x800)**, not base + 0x1800. So RESET_CTL=0 is
   a bogus read — we cannot trust it to mean "ARM is running". test.145 used
   the BCMA-aware `brcmf_chip_set_passive` → `brcmf_chip_disable_arm` path
   which writes wrapbase correctly.
4. **So the ARM might in fact be halted** from test.145. Cause of the crash is
   not proven to be runaway ARM firmware.

### Open questions for test.164

a. Is the ARM actually halted at download time? — need a correct wrapbase read.
b. Is BAR2 silently going away mid-copy (link drop, bridge error)?
c. Is there a timing/throughput issue with 110K sequential uncached writes?
d. Does splitting the copy into smaller chunks with breadcrumbs survive long
   enough to pinpoint the failing offset?

### Plan for test.164 (NOT YET IMPLEMENTED — CODE NOT REBUILT)

**Goal:** pinpoint where in the 442KB write the crash occurs, and verify ARM
halt state via correct register path.

**Proposed changes:**
1. Fix test.142 to read RESET_CTL via the BCMA-aware chip ops (same path as
   `brcmf_chip_disable_arm`), OR via the wrapbase window selection, so the
   reported halt state is accurate.
2. Add chunked breadcrumbs to the 442KB copy_mem_todev slice:
   - Log BAR0 window/CC probe every 16KB (or every N writes).
   - Record byte offset so we know exactly where the crash lands.
3. Keep `bcm4360_skip_arm=1` so no ARM release is attempted.
4. Keep the test.163 post-download fail-path bypass.

**Risk:** This is still a hardware-contact test and may crash again. The
breadcrumbs should narrow the failure to an offset range, letting us decide
whether to try tiny chunks, delays, or an alternative transfer approach.

### Pre-test checklist (NOT READY YET)

- [ ] Implement test.164 changes in pcie.c
- [ ] Build (`make -C phase5/work`)
- [ ] Verify .ko contains test.164 markers
- [ ] Re-check PCIe state of 03:00.0
- [ ] Commit + push plan before insmod

---

## Previous state (2026-04-20, PRE test.163 — REBUILT, ready for insmod)

### CODE STATE: test.163 implemented — setup callback now enters brcmf_pcie_download_fw_nvram

**What test.163 adds over test.162:**
- Removes test.162 early-return (before download_fw_nvram).
- Setup callback now calls `brcmf_pcie_download_fw_nvram(devinfo, fw, nvram, nvram_len)`.
- With `bcm4360_skip_arm=1`, that function:
  1. `brcmf_pcie_enter_download_state`: reads ARM CR4 state (test.142), no MMIO writes.
  2. Pre-BAR2 `ioread32(devinfo->tcm)` probe (test.138).
  3. `brcmf_pcie_copy_mem_todev(rambase=0, fw->data, 442233)` — 110,558 × 32-bit iowrite32.
  4. Releases `fw` and sets address=`ramsize - nvram_len` for NVRAM.
  5. Writes NVRAM (228 bytes) via copy_mem_todev.
  6. Frees `nvram`.
  7. Reads back NVRAM marker at `ramsize-4`.
  8. Reads PMU/HT state (read-only).
  9. Reads *0x62e20 baseline (should be 0).
  10. d11 wrap RESET_CTL/IOCTL read-only diagnostics.
  11. `bcm4360_skip_arm=1` → dump first 64 bytes of TCM → return -ENODEV.
- New BCM4360 early-return AFTER download_fw_nvram using return value:
  - logs ret
  - releases CLM/TXCAP (both NULL, no-op)
  - returns — skips the fail: path (which would call coredump + bus_reset + device_release_driver)

**Hypothesis for test.163:**
- 442KB BAR2 iowrite32 is proven safe from Phase 3, and test.158 changes
  (removing duplicate ARM halt) shouldn't affect BAR2 writes.
- ARM is halted (buscore_reset/test.145) so it cannot interfere during the write.
- Expect clean 442KB download + NVRAM write + TCM dump + -ENODEV return + clean rmmod.
- If crash: will pinpoint exactly where (pre-BAR2 probe, during copy_mem_todev,
  or NVRAM write, etc. — enter_download_state's mdelay will flush each breadcrumb).

**Key log markers to watch for:**
```
test.163: module_init entry
test.163: brcmf_pcie_register() entry
[probe chain through test.160]
test.161: calling brcmf_fw_get_firmwares → returned 0
test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0
test.128: before/after brcmf_pcie_attach (BCM4360 no-op)
test.134: post-attach / after kfree(fwreq)
test.130: before/after brcmf_chip_get_raminfo
test.130: after brcmf_pcie_adjust_ramsize
test.163: before brcmf_pcie_download_fw_nvram (442KB BAR2 write)
test.142: enter_download_state — ARM CR4 state read-only check
test.138: pre-BAR2-ioread32
test.138: post-BAR2-ioread32 = <non-ffffffff>  ← KEY MARKER: BAR2 alive
(copy_mem_todev — may take seconds at BAR2 write speeds)
BCM4360 debug: NVRAM loaded, len=228, writing to TCM 0x...
BCM4360 debug: NVRAM marker at ramsize-4 = ...
BCM4360 pre-ARM: clk_ctl_st=... res_state=... HT=NO
test.101 pre-ARM baseline: *0x62e20=0x00000000 ZERO (expected)
test.114b: wrap_RESET_CTL=... d11 wrap/IOCTL state
test.12: skipping ARM release (bcm4360_skip_arm=1)
test.12: FW downloaded OK, dumping TCM state
BCM4360 TCM[0x0000]: <fw bytes visible>
test.12: sharedram[...] = 0x...
test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
test.163: fw released; returning from setup (state still DOWN)
[rmmod]
test.161: remove() short-circuit — state=0 != UP
test.161: remove() short-circuit complete
```

**Pre-test PCIe state (2026-04-20 ~10:17):**
- 03:00.0: MAbort-, DevSta clean, LnkSta 2.5GT/s Width x1.

**Build status:** REBUILT; .ko test.163 markers verified.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.162 SUCCESS — ready for test.163)

### MILESTONE: setup callback safely reaches door of download_fw_nvram

**test.162 log entries (dmesg, all markers hit cleanly):**
```
test.162: module_init entry
test.162: brcmf_pcie_register() entry → pci_register_driver returned ret=0
[probe chain through test.160 scope: ALL SUCCESS]
test.161: calling brcmf_fw_get_firmwares → returned 0 (async)
test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0
test.128: before brcmf_pcie_attach → test.129: bypassed for BCM4360 → test.128: after
test.134: post-attach before fw-ptr-extract
test.134: after kfree(fwreq)
test.130: before brcmf_chip_get_raminfo
test.121: using fixed RAM info rambase=0x0 ramsize=0xa0000 srsize=0x0
test.130: after brcmf_chip_get_raminfo
test.130: after brcmf_pcie_adjust_ramsize
test.162: early return BEFORE brcmf_pcie_download_fw_nvram
test.162: releasing fw (fw=<ptr> size=442233) nvram=<ptr> len=228 clm=0 txcap=0
test.162: fw released; returning from setup (state still DOWN)
[rmmod]
test.161: remove() short-circuit — state=0 != UP; skipping MMIO cleanup
test.161: remove() short-circuit complete
```

**Key findings:**
- Setup callback ran ALL memory-ops fine: attach no-op, fw-ptr extract,
  kfree(fwreq), get_raminfo (fixed BCM4360 info), adjust_ramsize.
- `brcmf_pcie_adjust_ramsize` parsed fw->data (442KB) header without issue.
- Early-return cleanly released fw/nvram/clm/txcap.
- rmmod short-circuit worked again; DevSta fully clean after test.

**Post-test PCIe state (2026-04-20 ~10:14):**
- Endpoint 03:00.0: DevSta `CorrErr- NonFatalErr- FatalErr- UnsupReq-` (clean).
- MAbort-, LnkSta 2.5GT/s Width x1.

**What this proves:**
- Entire probe + setup-up-to-download path is now safe/reproducible on BCM4360.
- We can reach the door of `brcmf_pcie_download_fw_nvram` without any MMIO side-effects.
- This test established the "waiting room" baseline for test.163.

### Next: test.163 — `brcmf_pcie_download_fw_nvram` (THE BIG BAR2 WRITE)

**Scope:** Call `brcmf_pcie_download_fw_nvram(devinfo, fw, nvram, nvram_len)`
in the setup callback. This function:
1. Calls `brcmf_pcie_enter_download_state` — currently for BCM4360 just reads
   ARM CR4 state and logs (test.142) — no MMIO writes.
2. Writes 442233 bytes of firmware to TCM at rambase=0 via BAR2 (32-bit iowrite32).
3. Writes NVRAM (228 bytes) at top of TCM.
4. Calls `brcmf_pcie_exit_download_state` — ARM release region (skipped via
   `bcm4360_skip_arm=1` at stage 0).

**Risk surface:**
- 442KB of 32-bit iowrite32 to BAR2 — this is the core activity that Phase 3
  already demonstrated works. But post-regression recovery means we need to
  re-verify.
- NVRAM write to top of TCM — known-safe pattern.
- `bcm4360_skip_arm=1` means ARM stays halted, no firmware boot → no runaway MMIO.

**Expected hypothesis:** All writes complete, no crash; test still early-exits
before `brcmf_pcie_init_ringbuffers`. If a crash occurs, it will pinpoint
whether BAR2 has been re-broken by test.158's changes or whether it's been
stable all along.

**Build status:** Current .ko is test.162 build. test.163 requires rebuild.

---

## Previous state (2026-04-20, PRE test.162 — REBUILT, ready for insmod)

### CODE STATE: test.162 implemented — setup callback runs attach→fw-extract→raminfo→adjust_ramsize, early-return before download

**What test.162 adds over test.161:**
- Removes the test.161 entry-stub in `brcmf_pcie_setup`.
- Flow now runs through:
  1. `brcmf_pcie_attach(devinfo)` — BCM4360 returns immediately (no-op per test.129).
  2. test.134 post-attach marker + mdelay.
  3. `fw = fwreq->items[...].binary` etc. — pure memory ops.
  4. `kfree(fwreq)`.
  5. `brcmf_chip_get_raminfo` — returns BCM4360 fixed info (rambase=0, ramsize=0xa0000) per test.121.
  6. `brcmf_pcie_adjust_ramsize` — parses fw header (memory op on fw->data).
- New BCM4360 early-return BEFORE `brcmf_pcie_download_fw_nvram` (the 442KB
  BAR2 write + enter_download_state, historically the crash site).
- Releases fw/nvram/clm/txcap so rmmod short-circuit stays clean.

**Hypothesis for test.162:** All markers should appear cleanly. No BAR2 MMIO
happens in this slice (BCM4360 attach is no-op; get_raminfo uses fixed info;
adjust_ramsize is memory-only). Expect:
```
test.162: module_init entry
test.162: brcmf_pcie_register() entry → pci_register_driver returned ret=0
[probe chain through test.160]
test.161: calling brcmf_fw_get_firmwares (async)
test.161: brcmf_fw_get_firmwares returned 0
test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0
test.128: before brcmf_pcie_attach → test.129: bypassed for BCM4360 → test.128: after
test.134: post-attach before fw-ptr-extract
test.134: after kfree(fwreq)
test.130: before brcmf_chip_get_raminfo → test.121: fixed info → test.130: after
test.130: after brcmf_pcie_adjust_ramsize
test.162: early return BEFORE brcmf_pcie_download_fw_nvram
test.162: releasing fw (fw=<ptr> size=442233) nvram=<ptr> len=228 clm=0 txcap=0
test.162: fw released; returning from setup (state still DOWN)
[rmmod]
test.161: remove() short-circuit — state=0 != UP; skipping MMIO cleanup
test.161: remove() short-circuit complete
```

**Why this is the right slice:** Pure memory ops post-attach, no BAR2 MMIO.
Confirms we can reach the door of download_fw_nvram without any trouble.
The NEXT test (test.163) will step INTO download_fw_nvram — the real crash
frontier.

**Pre-test PCIe state (2026-04-20 ~10:11):**
- Endpoint 03:00.0: MAbort-, DevSta fully clean, LnkSta 2.5GT/s Width x1.

**Build status:** REBUILT; .ko markers verified (test.162 strings present).

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.161 SUCCESS — ready for test.162)

### HUGE MILESTONE: async firmware loader + setup callback + remove short-circuit all clean

**test.161 log entries (dmesg):**
```
test.161: module_init entry — fw_get_firmwares + setup-callback stub + remove short-circuit
test.161: brcmf_pcie_register() entry → before pci_register_driver → pci_register_driver returned ret=0
[probe chain through test.160 scope SUCCESS]
test.160: before prepare_fw_request → firmware request prepared
test.161: calling brcmf_fw_get_firmwares — async callback expected
test.161: brcmf_fw_get_firmwares returned 0 (async/success; callback will fire)
[async fw loader runs]
Direct firmware load for brcm/brcmfmac4360-pcie.clm_blob failed with error -2
Direct firmware load for brcm/brcmfmac4360-pcie.txcap_blob failed with error -2
test.161: brcmf_pcie_setup CALLBACK INVOKED ret=0
test.161: fw CODE size=442233
test.161: NVRAM data=<ptr> len=228
test.161: CLM=NULL TXCAP=NULL
test.161: fw released; returning from setup (ret=0)
[rmmod]
test.161: remove() short-circuit — state=0 != UP; skipping MMIO cleanup
test.161: remove() short-circuit complete
```

**Key findings:**
- Async firmware loader path WORKS on BCM4360 — no crash, callback fires cleanly.
- **Firmware sizes CONFIRMED:**
  - `brcmfmac4360-pcie.bin` = **442233 bytes (432 KB)** ✓ matches Phase 1 extraction
  - `brcmfmac4360-pcie.txt` (NVRAM) = **228 bytes** ✓ NVRAM file IS present
  - `.clm_blob` and `.txcap_blob` NOT present (ENOENT) — OPTIONAL flag means no error.
- `brcmf_pcie_setup` successfully entered with ret=0 and populated fwreq.
- BCM4360 early-return stub released all fw handles without MMIO.
- `brcmf_pcie_remove` short-circuit path worked: state=0 (DOWN), MMIO skipped.
- **Clean rmmod** — no crash, machine stable.

**Post-test PCIe state (2026-04-20 ~10:10):**
- Endpoint 03:00.0: DevSta `CorrErr- NonFatalErr- FatalErr- UnsupReq-` (FULLY CLEAN).
- MAbort-, LnkSta 2.5GT/s Width x1.

**What this proves:**
- The ENTIRE probe path from `insmod` through `brcmf_fw_get_firmwares` +
  async callback entry is now safe and reproducible on BCM4360.
- firmware bytes sit in RAM ready for TCM download.
- Next slice can start doing BAR2 MMIO (the historically crash-prone work).

### Next: test.162 — `brcmf_pcie_attach` (first BAR2 MMIO of setup callback)

**Scope:** In the setup callback (instead of early-return), call ONLY
`brcmf_pcie_attach(devinfo)` — which does IRQ prep, mailbox sizes, shared
memory structure setup. Then still early-return. No firmware download yet.

**Why carefully:** `brcmf_pcie_attach` is the entry point into the BAR2 MMIO
era. If it crashes, we know exactly where. If it succeeds, test.163 can do
`brcmf_chip_get_raminfo` (already known safe — fixed RAM info).

**Build status:** Current .ko is test.161 build. test.162 will require rebuild.

---

## Previous state (2026-04-20, PRE test.161 — REBUILT, ready for insmod)

### CODE STATE: test.161 implemented, built, markers verified in .ko strings

**What test.161 does:**
1. Probe path runs unchanged through test.160 scope (all SUCCESS markers).
2. At end of probe: `brcmf_fw_get_firmwares(bus->dev, fwreq, brcmf_pcie_setup)` now
   called (test.160's early-return removed). This is an async firmware request
   that loads `brcmfmac4360-pcie.bin/.txt/.clm_blob/.txcap_blob`.
3. Async callback `brcmf_pcie_setup()` fires. Entry marker logs `ret=` and
   firmware sizes (CODE/NVRAM/CLM/TXCAP).
4. BCM4360 early-return stub in setup: releases all fw resources via
   `release_firmware()` + `brcmf_fw_nvram_free()` + `kfree(fwreq)`, then
   `return` — NO `brcmf_pcie_attach`, NO BAR2 writes, NO `brcmf_pcie_download_fw_nvram`.
5. Device stays bound until `rmmod`. `brcmf_pcie_remove()` has a new BCM4360
   short-circuit guard: when `state != UP`, skip MMIO-touching cleanup
   (`console_read`, `intr_disable`, `release_ringbuffers`, `reset_device`) —
   only do memory cleanup (`brcmf_detach`, `brcmf_free`, `kfree(bus)`,
   `release_firmware(clm/txcap)`, `chip_detach`, `kfree(devinfo)`).

**Why this slice is the right next step:**
- Confirms async firmware loader path works on BCM4360 (VFS + request_firmware).
- Proves `brcmf_pcie_setup` entry is reached and the fw pointers look sane.
- Establishes clean baseline for next slice (test.162: `brcmf_pcie_attach` —
  starts doing BAR2 MMIO, which is where real crashes begin).
- Avoids firing any BAR2 MMIO (which is historically the crash trigger).

**Hypothesis:** test.161 will log:
- Probe path through test.160 scope
- "calling brcmf_fw_get_firmwares — async callback expected"
- "brcmf_fw_get_firmwares returned 0 (async/success; callback will fire)"
- (brief delay while request_firmware loads)
- "brcmf_pcie_setup CALLBACK INVOKED ret=0"
- "fw CODE <ptr> size=452488" (~442 KB)
- "NVRAM data=<ptr> len=<N>" (non-zero if nvram present; CODE-only if not)
- "CLM=..." (NULL if .clm_blob not present)
- "fw released; returning from setup (ret=0)"
- On rmmod: "remove() short-circuit — state=0 != UP; skipping MMIO cleanup"
- "remove() short-circuit complete"
- Clean rmmod exit.

**Possible failure modes:**
- `request_firmware` fails for .txt/.clm_blob/.txcap_blob — NVRAM is OPTIONAL
  so should not block; CLM/TXCAP are similarly optional.
- Callback never fires (async hang) — test will just time out after 60s.
- Crash inside `request_firmware` — unlikely since nothing MMIO.
- rmmod crashes — this is the risky part: even with MMIO short-circuit,
  `brcmf_detach` / `brcmf_free` touches driver state, and `chip_detach`
  unmaps chip. These are memory ops and should be safe.

**Build status:** REBUILT at 2026-04-20; .ko markers verified: test.161 strings
present in module_init, register, setup-callback, setup-return, remove-short-circuit.

**Pre-test PCIe state (2026-04-20):**
- Endpoint 03:00.0: `MAbort-`, `LnkSta 2.5GT/s Width x1`, `ASPM Disabled`.
- Bridge 00:1c.2 secondary status has `<MAbort+` (sticky from test.160 cleanup).
  SBR in probe resets bridge; not a blocker.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.160 SUCCESS — DECISION POINT before test.161)

### CODE STATE: test.160 ran cleanly. Considering scope of test.161 carefully.

**test.160 key log entries (dmesg):**
```
test.160: module_init entry — brcmf_alloc + OTP bypass + prepare_fw_request
(probe chain through SBR, chip_attach, BusMaster/ASPM, reginfo, allocs/wiring)
test.160: drvdata set — before brcmf_alloc
test.160: brcmf_alloc complete — wiphy allocated
test.160: OTP read bypassed — OTP not needed
test.160: before prepare_fw_request
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3
test.160: firmware request prepared
test.160: early return before brcmf_fw_get_firmwares
```

**Key findings:**
- brcmf_alloc succeeded — wiphy allocated, cfg80211 ops set.
- prepare_fw_request populated the firmware name `brcm/brcmfmac4360-pcie` (chip rev 3).
- DevSta post-test: fully clean (CorrErr- NonFatalErr- FatalErr- UnsupReq-).
- Clean rmmod, machine stable.
- Firmware file exists at `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442 KB).

**Probe path CONFIRMED SAFE (tests 158→160):**
- Module init → SDIO register (no-op) → PCI register
- Probe: SBR → chip_attach (which halts ARM internally via test.145 path)
- BusMaster clear + ASPM disable (config-space only)
- PCIE2 core get + reginfo selection (default for rev=1)
- Allocations (pcie_bus_dev, settings dummy, bus, msgbuf)
- Struct wiring + pci_pme_capable (wowl=1) + dev_set_drvdata
- brcmf_alloc (wiphy_new + cfg80211 ops)
- OTP read bypass (BCM4360 has OTP but we skip)
- brcmf_pcie_prepare_fw_request

### ⚠️ test.161 — DANGER ZONE: firmware download path

**Why pause here:**
- `brcmf_fw_get_firmwares()` kicks off an async firmware request.
- Its completion callback is `brcmf_pcie_setup()`, which does the REAL work:
  firmware download to TCM via BAR2, NVRAM placement, ring buffer setup,
  ARM release (bcm4360_skip_arm controls whether to actually release), IRQ enable.
- This is where ALL the earlier phase-5.2 crashes originated (MCE on firmware
  hang, wild MMIO from booted firmware, D11 PHY wait, etc.).
- A single jump to "full firmware download + ARM release" will be too wide —
  we'd bundle firmware-load + setup + release in one step, losing bisection value.

**Proposed test.161 (narrow discriminator):**
- Invoke `brcmf_fw_get_firmwares()` but with a replaced callback that only logs
  the firmware size and immediately returns `-ENODEV` (skips setup).
- Rationale: async firmware request is pure VFS + request_firmware — should be
  safe. Prior tests (103+) already requested firmware successfully.
- OR simpler: just re-enable the call and let it run to brcmf_pcie_setup entry,
  add very early marker, and early-return inside brcmf_pcie_setup before any
  BAR2 writes.

**Pre-test PCIe state (2026-04-20 ~09:46):**
- `BusMaster-`, `ASPM Disabled`, `MAbort-`, `LnkSta 2.5GT/s Width x1`.
- DevSta fully clean (all error flags -).

**Build status:** test.160 is the current built .ko. Any test.161 changes need rebuild.

**Test command (if approved by user):**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.159 SUCCESS — test.160 ready)

### CODE STATE: test.159 ran cleanly — all 22 markers appeared; clean rmmod

**test.159 key log entries (dmesg):**
```
test.159: module_init entry — reginfo + allocs + wiring slice
test.159: brcmf_pcie_register() entry → pci_register_driver returned ret=0
[probe chain through SBR, chip_attach, BusMaster/ASPM as test.158]
test.159: before PCIE2 core/reginfo setup
test.159: reginfo selected (pcie2 rev=1)
test.159: pcie_bus_dev allocated
test.159: settings allocated (BCM4360 dummy path)
test.159: bus allocated
test.159: msgbuf allocated
test.159: struct wiring done — before pci_pme_capable
test.159: after pci_pme_capable wowl=1
test.159: drvdata set — before early return
test.159: early return after allocs/wiring — before brcmf_alloc
```

**Key findings:**
- PCIE2 core rev=1 (uses brcmf_reginfo_default — not rev≥64).
- All 4 allocations succeeded: pcie_bus_dev, settings (dummy), bus, msgbuf.
- pci_pme_capable returned wowl=1 (D3hot wake capable).
- DevSta post-test: CorrErr- NonFatalErr- FatalErr- UnsupReq- (FULLY CLEAN — all flags cleared).
- Clean rmmod, machine stable.

**Post-test PCIe state (2026-04-20 ~09:42):**
- `BusMaster-`, `ASPM Disabled`, `MAbort-`, `LnkSta 2.5GT/s Width x1`.
- DevSta fully clean (all error flags -).

### test.160 plan — ADD brcmf_alloc + OTP bypass + prepare_fw_request

**Rationale:**
- Next probe steps: brcmf_alloc (wiphy_new + ops) → OTP read (bypassed) → prepare_fw_request.
- brcmf_alloc is pure memory: cfg80211 ops alloc + wiphy_new + pointer wiring.
- prepare_fw_request builds a firmware request struct (no hardware access).
- Existing test.155 early return at `brcmf_fw_get_firmwares` is the natural stopping point.

**test.160 scope:**
- Remove test.159 early return.
- Add msleep(300) + markers around: before brcmf_alloc, after brcmf_alloc, OTP bypass
  markers, before prepare_fw_request, after prepare_fw_request.
- KEEP test.155 early return before brcmf_fw_get_firmwares (that's the next boundary).
- Update module_init / register markers to test.160.

**Expected outcomes:**
- Clean run through brcmf_alloc + OTP bypass + prepare_fw_request to the test.155 early return.
- If crash: per-marker sleeps identify which step (likely kernel memory helpers).

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.158 SUCCESS — test.159 ready)

### CODE STATE: test.158 ran cleanly — all markers appeared, no crash, clean rmmod

**test.158 key log entries (from dmesg snapshot):**
```
test.158: module_init entry — no-ARM-halt; BusMaster/ASPM slice
test.128: PROBE ENTRY (device=43a0 vendor=14e4 ...)
test.53: SBR via bridge 0000:00:1c.2 (bridge_ctrl=0x0002)
test.53: SBR complete — bridge_ctrl restored
test.158: before brcmf_chip_attach
test.53: BAR0 probe (CC@0x18000000 off=0) = 0x15034360 — alive
test.145: halting ARM CR4 after second SBR (buscore_reset)
test.145: ARM CR4 halt done
test.119: brcmf_chip_attach returned successfully
test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)
test.158: about to pci_clear_master (config-space write)
test.158: BusMaster cleared after chip_attach
test.158: about to read LnkCtl before ASPM disable
test.158: LnkCtl read before=0x0143 — disabling ASPM
test.158: pci_disable_link_state returned — reading LnkCtl
test.158: ASPM disabled; LnkCtl before=0x0143 after=0x0140 ASPM-bits-after=0x0
test.158: early return after BusMaster/ASPM — before reginfo
test.158: pci_register_driver returned ret=0
```

**Key findings:**
- Duplicate ARM halt CONFIRMED as the sole crash trigger (test.157 thesis validated).
- pci_clear_master: safe (config-space write).
- pci_disable_link_state(ASPM_ALL): safe. LnkCtl 0x0143 → 0x0140 (ASPM bits 0x3 cleared).
- DevSta post-test: UnsupReq- (cleared! previous runs had UnsupReq+).
- Clean rmmod, machine stable.

**Post-test PCIe state (2026-04-20 ~09:40):**
- `BusMaster-` (cleared by driver — persists post-rmmod).
- `LnkCtl: ASPM Disabled; CommClk+` (ASPM cleared by driver — persists post-rmmod).
- `DevSta: CorrErr+ UnsupReq- AuxPwr+` (UnsupReq cleared).
- `LnkSta: Speed 2.5GT/s, Width x1` — stable.
- `MAbort-` — clean.

### test.159 plan — ADD reginfo selection + bus/devinfo allocations + wiring

**Rationale:**
- Upstream probe continues from ASPM disable → select PCIE2 core + reginfo → kzalloc
  pcie_bus_dev → kzalloc settings (dummy for BCM4360) → kzalloc bus → kzalloc bus->msgbuf →
  wire up pointers → pci_pme_capable (config-space read) → dev_set_drvdata.
- All these are pure kernel memory alloc + config-space read.  No BAR0 MMIO, no DMA setup.
- Existing markers already present (test.120/123/132) — just need per-marker msleep(300)
  and move the early-return AFTER the wiring step, before `brcmf_alloc()`.

**test.159 scope:**
- Remove test.158 early return.
- Add msleep(300) to each existing marker in the reginfo→drvdata section.
- Add new early return right BEFORE `brcmf_alloc(&devinfo->pdev->dev, devinfo->settings)`.
- brcmf_alloc is the next known HW/core boundary — isolate it for test.160.

**Expected outcomes:**
- Clean run through all markers, early-return before brcmf_alloc.
- If crash: per-marker sleeps identify the exact kzalloc/wiring step (very unlikely).

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-20, POST test.157 CRASH PINPOINTED — test.158 ready)

### CODE STATE: test.158 prepared — duplicate ARM halt removed; BusMaster/ASPM slice

**test.157 CRASH ANALYSIS (boot -1, 09:09–09:29):**
- test.157 RAN cleanly through all markers; crash pinpointed precisely by per-marker msleep(300).
- `journalctl -k -b -1` captured the complete marker trail through to the wedge detection.
- Full log: `phase5/logs/test.157.boot-1.journalctl.txt` (1096 lines).

**Last flushed markers (copied verbatim from journalctl):**
```
09:28:19 test.145: halting ARM CR4 after second SBR (buscore_reset)
09:28:19 test.145: ARM CR4 halt done — skipping PCIE2 mailbox clear; returning 0   ← chip_attach's halt
09:28:19 test.119: brcmf_chip_attach returned successfully
09:28:19 test.142: ARM CR4 core->base=0x18002000 (for early-reset hardcode)
09:28:19 test.157: about to select ARM core (BAR0 window change)
09:28:20 test.157: ARM select_core done — reading IOCTL
09:28:20 test.157: IOCTL read done (0x0001) — writing CPUHALT|FGC|CLK
09:28:20 test.157: IOCTL write done — flush-reading IOCTL
09:28:21 test.157: IOCTL flush done (0x0023) — asserting RESET_CTL
09:28:21 test.157: RESET_CTL write done — waiting 1ms
09:28:21 test.157: RESET_CTL readback=0xffffffff IN_RESET=NO/WEDGED — writing in-reset IOCTL
[CRASH — MCE before next marker]
```

**Pinpointed root cause:**
- `brcmf_chip_set_passive()` was ALREADY called inside `buscore_reset` (test.145 path) —
  ARM was halted cleanly during `chip_attach`.  The test.157 probe-level ARM halt is a
  **DUPLICATE halt** performed on an already-halted core.
- The duplicate halt's `RESET_CTL = 1` MMIO write appears to succeed, but the readback
  returns `0xffffffff` — the BAR0 window to the ARM CR4 core is now **WEDGED** (Unsupported
  Request / all-ones response).  This is the first time we see the wedge.
- The **next MMIO write** to the wedged window (the in-reset IOCTL write) triggers an MCE.
  On this host `iommu=strict` likely escalates the bad MMIO to a hard fault/machine check.
- Read access after wedge returns UR (no crash).  **Write access after wedge crashes the box.**

**Key takeaway:** `RESET_CTL=1` on the ARM CR4 core disconnects that core's BAR0 window.
No MMIO to that core is safe after the RESET_CTL assert until reset is released.  But
releasing requires writing `RESET_CTL=0` — through the same wedged window.  So once wedged,
you cannot recover via this window.

**Pre-test PCIe state (post-test.157 crash + SMC reset, 2026-04-20 ~09:30):**
- Endpoint `03:00.0`: `MAbort-`, `CommClk+`, `LnkSta: Speed 2.5GT/s Width x1` — CLEAN.
- `DevSta: CorrErr+ UnsupReq+ AuxPwr+` (mask states; non-dangerous).
- `CESta: AdvNonFatalErr+` (masked).
- `BusMaster+`, `ASPM L0s L1 Enabled`.
- No brcm modules loaded.

### test.158 plan — REMOVE the duplicate probe-level ARM halt; extend scope to BusMaster/ASPM

**Rationale:**
- The existing probe-level ARM halt (lines ~4042–4095 of pcie.c) is REDUNDANT — chip_attach
  already halted the core via buscore_reset→set_passive (test.145 path).
- Remove the duplicate halt entirely (guard with `#if 0 /* test.158 remove dup halt */`).
- With the dup halt gone, proceed past it to the next probe steps:
  - `pci_set_master()` / BusMaster handling
  - ASPM L1 disable (driver normally does this pre-firmware)
  - reginfo / aligned DMA alloc preparation (maybe next test)
- For test.158, ONLY remove dup halt and add a new explicit BusMaster/ASPM slice with markers.
  Keep per-marker msleep(300) discipline.
- Early return after BusMaster/ASPM slice — do NOT continue into reginfo/allocs yet.

**Expected outcomes:**
- If test.158 runs cleanly to "early return after BusMaster/ASPM": duplicate halt theory confirmed.
- If crash in BusMaster/ASPM slice: per-marker sleep identifies the exact step.

**Test command (unchanged):**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```
Stage1 remains forbidden.

---

## Previous state (2026-04-20, POST test.156 CRASH — preparing test.157)

### CODE STATE: test.157 source prepared — same scope as test.156 + msleep(300) between markers

**test.156 CRASH ANALYSIS (boot -1, 08:54–09:06):**
- test.156 RAN in boot -1 (started 09:06:38) and CRASHED — machine required SMC reset.
- Last journalctl -b -1 marker: `test.155: before brcmf_pcie_register()` (09:06:39).
- CRITICAL INSIGHT — journald flush lag: journald polls the ring buffer at intervals (~200-500ms).
  If the crash happened within one polling cycle of the last marker, later markers were written
  to the ring buffer but NOT flushed to disk before the MCE killed the system.
  - This means the crash could be ANYWHERE after `before brcmf_pcie_register()` —
    including inside `brcmf_pcie_register()` itself, inside probe, or inside ARM halt MMIO writes.
  - We CANNOT conclude the crash was at PCI registration — we only know it was at or after it.
- pstore (EFI): `sudo mount -t pstore pstore /sys/fs/pstore` works!
  - pstore captured an older Oops (test.149 era, uptime ~588s) — a rmmod crash in
    `pci_unregister_driver → driver_unregister → "Unexpected driver unregister!"` (NULL deref).
  - This older bug is already fixed: brcmf_core_exit() has `brcmf_pcie_was_registered` guard.
  - MCE-level hard freezes (test.155/156) do NOT write pstore — only kernel Oops/panic does.
- Stream log (`phase5/logs/test.156.stage0.stream`) captured boot messages but no test markers
  — crash was too fast for the stream sync loop to capture new messages.
- Full journalctl -b -1 saved to: `phase5/logs/test.156.boot-1.journalctl.txt`
- pstore dump saved to: `phase5/logs/pstore-crash-dump-2026-04-20.txt`

**test.157: same ARM halt scope + msleep(300) between markers for precise crash location.**
- Root cause: journald flush lag means we can't locate crash without marker-flush discipline.
- Fix: add `msleep(300)` after each key marker so journald flushes before the next step.
- Scope unchanged: SBR → chip_attach → ARM halt MMIO writes → early return.
- With 300ms sleeps, the LAST FLUSHED marker before a crash tells us the exact crash location.

**Pre-test PCIe state (post-test.156 crash + SMC reset, 2026-04-20 ~09:09):**
- Endpoint `03:00.0`: `MAbort-`, `CommClk+`, `LnkSta: Speed 2.5GT/s Width x1` — CLEAN.
- `DevSta: CorrErr+ UnsupReq+`, `CESta: AdvNonFatalErr+` (masked, non-dangerous).
- `LnkCtl: ASPM L0s L1 Enabled`, `BusMaster+` — normal post-SMC state, no driver bound.
- Config space readable; no completion timeout.
- No brcm modules loaded.

**Hypothesis (unchanged from test.156):**
- ARM halt MMIO writes likely crash the machine.
- With per-marker msleep(300), the exact failing MMIO step will be captured in journalctl.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```
Stage1 remains forbidden.

**Interpretation matrix (test.157 with per-marker sleeps):**
- Last marker `test.157: before brcmf_pcie_register() entry` + crash: crash in pci_register_driver kernel code (unlikely but possible — config space timeout).
- Last marker `test.128: PROBE ENTRY` + crash: crash in early probe (before chip_attach setup).
- Last marker `test.156: before brcmf_chip_attach` + crash: crash in chip_attach (regression from test.154).
- Last marker `test.119: chip_attach returned successfully` + crash: crash in select_core for ARM.
- Last marker `test.157: ARM select_core done` + crash: crash in IOCTL read (0x1408).
- Last marker `test.157: IOCTL read done` + crash: crash in IOCTL write (0x1408 = 0x0023).
- Last marker `test.157: IOCTL write done` + crash: crash in IOCTL flush-read.
- Last marker `test.157: IOCTL flush done` + crash: crash in RESET_CTL write (0x1800 = 1).
- Last marker `test.157: RESET_CTL write done` + crash: crash in RESET_CTL read-back.
- All markers appear incl `test.156: early return after ARM halt`: ARM halt safe, next test adds BusMaster/ASPM.

---

## Previous state (2026-04-20, POST test.155 CRASH — preparing test.156)

### CODE STATE: test.156 source prepared, rebuilt, committed

**test.155 CRASH ANALYSIS:**
- test.155 RAN but CRASHED — machine required SMC reset to recover.
- Stream log (`phase5/logs/test.155.stage0.stream`) only has 13 lines, cut short by crash.
- Stream interpretation (KEY INSIGHT): the test.154 module_init markers in the stream
  are **residual ring-buffer messages** from the earlier test.154 run, captured by
  `dmesg -wk` before `dmesg -C` cleared the buffer. The actual test.155 binary ran.
  - Confirmed by `strings brcmfmac.ko | grep "module_init entry"` → shows test.155 marker.
  - .ko built at 08:51:00, sources modified at 08:49:56, test started at 08:52:11.
- The probe entry markers (test.128/test.127 at uptime 1740.586xxx) ARE from test.155.
- Crash happened SOMEWHERE in test.155 probe after probe entry. The crash was catastrophic
  (MCE or NMI) — the dmesg subprocess was killed before it could flush subsequent ring
  buffer entries to the stream file.
- Pre-test BAR0 MMIO guard showed "UR/I/O error (6ms)" — endpoint returning UR (normal
  when no driver bound, device not power-on initialized). Script proceeded correctly.
- **Root cause unknown**: crash could be in SBR, chip_attach, or ARM halt MMIO writes.
  test.154 showed SBR+chip_attach safe, so ARM halt is the most likely suspect.
  However, PCIe state may also have been worse than after test.154's clean run.

**test.155 was too wide a step.** It bundled ARM halt + BusMaster/ASPM + reginfo +
allocs + OTP + fwreq in one jump. A crash can only be attributed to "somewhere in that span."

**test.156: ARM halt ONLY — narrow the bisection.**
- `brcmf_pcie_probe()` runs SBR → chip_attach → ARM halt MMIO writes → early return.
- Early return added INSIDE the BCM4360 ARM halt if-block, right after RESET_CTL write
  and IOCTL_before/IOCTL_fgc/RESET_CTL diagnostic log (test.142), before BusMaster clear.
- All test.142 ARM halt markers remain; new test.156 early return marker added.
- `fail` label used (same as chip_attach path) — minimal cleanup, safe.

**Hypothesis:**
- ARM halt MMIO writes (brcmf_pcie_select_core → brcmf_pcie_write_reg32 to 0x1408, 0x1800)
  on a chip that just completed chip_attach should be safe — chip_attach already mapped
  the BAR0 window to the ARM core (brcmf_pcie_select_core does this).
- If NO crash, `test.142: ARM CR4 reset: IOCTL_before=... RESET_CTL=...` appears + `test.156 early return`: ARM halt is safe; next test: BusMaster/ASPM + rest of allocs.
- If crash: ARM halt MMIO write (0x1408 or 0x1800) is the crash trigger.

**Pre-test PCIe state (post-crash + SMC reset, 2026-04-20 ~09:XX):**
- Endpoint `03:00.0`: `MAbort-`, `CommClk+`, `LnkSta: Speed 2.5GT/s Width x1` — CLEAN after SMC reset.
- `DevSta: CorrErr+ UnsupReq+` — UnsupReq+ is expected (from pre-test guard reads), not dangerous.
- No brcm modules loaded.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```
Stage1 remains forbidden.

**Interpretation matrix:**
- No crash, `test.142: ARM CR4 reset` marker appears + `test.156: early return after ARM halt`: ARM halt safe; next test covers BusMaster/ASPM + allocs + OTP + fwreq.
- Crash before `test.155: before brcmf_chip_attach`: crash in probe setup or SBR (unexpected — same as test.154/153).
- Crash after `chip_attach returned successfully` but before `test.142: ARM CR4 reset`: crash in brcmf_pcie_select_core() for ARM core (BAR0 window change).
- Crash during `test.142: ARM CR4 reset` block: crash in IOCTL or RESET_CTL MMIO write.

---

## Previous state (2026-04-20, POST test.154 SUCCESS — chip_attach safe; ARM halt + allocs next)

### CODE STATE: test.154 ran cleanly — all markers appeared, chip fully enumerated

**test.154 key log entries (from stream log):**
```
brcmfmac: BCM4360 test.155: before brcmf_chip_attach  [NOTE: marker was test.154 at run time]
brcmfmac 0000:03:00.0: BCM4360 test.119: brcmf_chip_attach returned successfully
brcmfmac: BCM4360 test.154: chip_attach OK — early return before ARM halt
brcmfmac: BCM4360 test.154: pci_register_driver returned ret=0
brcmfmac: BCM4360 test.154: post-PCI sync (skipping USB)
brcmfmac: BCM4360 test.154: after brcmf_core_init() err=0
```
- chip_attach fully succeeded: chip ID 0x15034360 (BCM4360), RAM base=0x0 size=0xa0000 (640KB).
- ARM CR4 core base logged for future reference.
- SBR timing: ~518ms. BAR0 MMIO reads in chip_attach did NOT crash the machine.
- Clean rmmod after test. dmesg kill fix working correctly.

---

## Previous state (2026-04-20, POST test.153 SUCCESS — SBR safe; chip_attach next)

### CODE/LOG STATE: test.153 ran cleanly — all markers appeared; SBR took 518ms

**test.153 key log entries:**
```
brcmfmac 0000:03:00.0: BCM4360 test.53: SBR via bridge 0000:00:1c.2 (bridge_ctrl=0x0002) before chip_attach
brcmfmac 0000:03:00.0: BCM4360 test.53: SBR complete — bridge_ctrl restored
brcmfmac: BCM4360 test.153: SBR complete — early return before chip_attach
brcmfmac: BCM4360 test.153: pci_register_driver returned ret=0
brcmfmac: BCM4360 test.153: post-PCI sync (skipping USB)
brcmfmac: BCM4360 test.153: after brcmf_core_init() err=0
```

**Key findings:**
- Full SBR (assert + 10ms hold + deassert + 500ms wait + pci_restore_state) is SAFE.
- bridge_ctrl=0x0002 → PCI_BRIDGE_CTL_ISA bit set; SBR bit not stuck — bridge is clean.
- SBR timing: ~518ms (10ms + 500ms + overhead) — consistent with expected.
- Crash trigger is `brcmf_chip_attach()` (BAR0 MMIO reads) or later probe operations.
- rmmod completed cleanly; dmesg kill fix working (no hung script).

---

## Previous state (2026-04-20, POST test.152 SUCCESS — probe safe without HW; SBR next)

### CODE/LOG STATE: test.152 ran cleanly — all markers appeared

**test.152 stream log captured:**
```
brcmfmac: BCM4360 test.152: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.152: before brcmf_core_init()
brcmfmac: BCM4360 test.152: brcmf_core_init() entry
brcmfmac: BCM4360 test.152: before brcmf_sdio_register()
brcmfmac: BCM4360 test.152: after brcmf_sdio_register() err=0
brcmfmac: BCM4360 test.152: post-SDIO sync (before PCI)
brcmfmac: BCM4360 test.152: before brcmf_pcie_register()
brcmfmac: BCM4360 test.152: brcmf_pcie_register() entry
brcmfmac: BCM4360 test.152: skipping brcmf_dbg in brcmf_pcie_register
brcmfmac: BCM4360 test.152: after skipped brcmf_dbg, before pci_register_driver
brcmfmac: BCM4360 test.128: PROBE ENTRY (device=43a0 vendor=14e4 id=...)
brcmfmac: BCM4360 test.127: probe entry (vendor=14e4 device=43a0)
brcmfmac: BCM4360 test.127: devinfo allocated, before pdev assign
brcmfmac: BCM4360 test.127: devinfo->pdev assigned, before SBR
brcmfmac: BCM4360 test.152: probe early-return — before SBR, no HW access
brcmfmac: BCM4360 test.152: pci_register_driver returned ret=0
brcmfmac: BCM4360 test.152: after brcmf_pcie_register() err=0
brcmfmac: BCM4360 test.152: post-PCI sync (skipping USB)
brcmfmac: BCM4360 test.152: after brcmf_core_init() err=0
```

**Key findings:**
- Probe IS called by pci_register_driver() — `PROBE ENTRY` confirmed.
- Probe entry up to (and including) kzalloc + devinfo->pdev assignment is safe.
- No crash: crash trigger is in the SBR block or chip_attach.
- rmmod completed cleanly (pci_unregister_driver with no bound device).
- dmesg kill bug in test script: `kill -9 $DMESG_PID` killed only the while-subshell,
  not the `dmesg -wk` subprocess → 20min hang fixed by adding pkill of subprocess.

---

## Previous state (2026-04-20, POST test.151 CRASH — PCI probe confirmed crash trigger)

### CODE/LOG STATE: test.151 crashed — only 3 markers in journalctl -b -1

**test.151 stream log captured (2 markers only):**
```
brcmfmac: BCM4360 test.151: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.151: before brcmf_core_init()
```

**journalctl -b -1 captured (3 markers):**
```
brcmfmac: BCM4360 test.151: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.151: before brcmf_core_init()
brcmfmac: BCM4360 test.151: brcmf_core_init() entry
```

**Key findings:**
- Hard freeze confirmed: no kernel panic output in journalctl (SMC reset required).
- SDIO markers (from line 1553+) completely absent — hard freeze froze journald before
  it could flush ring buffer entries past `brcmf_core_init() entry`.
- SDIO itself is NOT the crash trigger (confirmed safe in test.150).
- PCI probe IS the crash trigger: adding `brcmf_pcie_register()` → `pci_register_driver()`
  → `brcmf_pcie_probe()` causes the machine to hard-freeze.
- The freeze happened fast enough that the ring buffer lost the SDIO markers,
  indicating the freeze occurred within milliseconds of `brcmf_core_init() entry`.

**Pre-test PCIe state (2026-04-20):**
- Root port `00:1c.2`: `DLActive+`, `CommClk+`, `MAbort-`, bus `03/03` — clean.
- Endpoint `03:00.0`: present, `MAbort-`, AER clear, `DevSta: CorrErr+ UnsupReq+` (expected from UR guard).
- No driver bound to 03:00.0; no bcma/wl/brcm modules loaded.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```
Stage1 remains forbidden.

**Interpretation matrix:**
- No crash, all markers appear: SDIO safe; add USB next (test.151 = SDIO+USB, skip PCI).
- Crash before/during `brcmf_sdio_register()`: SDIO init is the trigger; investigate SDIO subsystem.
- Crash after SDIO but before `post-SDIO sync`: SDIO side effects (async) are the trigger.

---

## Previous state (2026-04-20, POST test.150 SUCCESS — SDIO safe; PCI registration is next)

### CODE/LOG STATE: test.150 ran cleanly — all markers appeared, clean rmmod

**Stream log captured:**
```
brcmfmac: BCM4360 test.150: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.150: before brcmf_core_init()
brcmfmac: BCM4360 test.150: brcmf_core_init() entry
brcmfmac: BCM4360 test.150: before brcmf_sdio_register()
brcmfmac: BCM4360 test.150: after brcmf_sdio_register() err=0
brcmfmac: BCM4360 test.150: post-SDIO sync (skipping USB and PCI)  [50ms after SDIO]
brcmfmac: BCM4360 test.150: after brcmf_core_init() err=0
```

**Key findings:**
- SDIO registration is safe — no crash.
- Registration guards work — rmmod completed cleanly.
- `dmesg -wk` stuck on SIGTERM (7-minute hang) → fixed to `kill -9` for future tests.
- PCIe is the next discriminator (historically the crash window in tests 146-148).

---

## Previous state (2026-04-20, POST test.149 SUCCESS — no crash; SDIO-only is next)

### CODE/LOG STATE: test.149 ran cleanly — all markers appeared

**Stream log captured:**
```
brcmfmac: BCM4360 test.149: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.149: before brcmf_core_init()
brcmfmac: BCM4360 test.149: brcmf_core_init() entry
brcmfmac: BCM4360 test.149: pre-return sync (no registrations)   [after 50ms mdelay]
brcmfmac: BCM4360 test.149: after brcmf_core_init() err=0
```

**Key findings:**
1. **No crash**: brcmf_core_init() with no registrations is safe — module load alone does not trigger the crash.
2. **Printk persistence confirmed**: both `entry` and `pre-return sync` appeared after a 50ms delay; the test.148 missing marker was not a persistence issue but a crash-during-registration event.
3. **Root cause narrowed**: crash is triggered by SDIO, USB, or PCI registration (or probe side effects).

---

## Previous state (2026-04-19 23:18 BST → 2026-04-20 POST test.148 crash; SMC reset complete)

### CODE/LOG STATE: test.148 ran and crashed after brcmf_core_init() entry, before brcmf_sdio_register() marker

**Repository state:**
- Branch: `main`
- Untracked after reboot: `phase5/logs/test.148.stage0`, `phase5/logs/test.148.stage0.stream`

**test.148 stream log captured:**
```
brcmfmac: loading out-of-tree module taints kernel.
brcmfmac: BCM4360 test.148: module_init entry (no BAR0 MMIO)
brcmfmac: BCM4360 test.148: before brcmf_core_init()
brcmfmac: BCM4360 test.148: brcmf_core_init() entry
```

**Missing markers:**
- `BCM4360 test.148: before brcmf_sdio_register()` — immediately the next line (core.c:1544)
- `BCM4360 test.148: before brcmf_pcie_register()`
- All subsequent markers

**Key finding:** `brcmf_core_init() entry` (line 1543) and `before brcmf_sdio_register()` (line 1544) are consecutive `pr_emerg` calls with no code between them. Missing the second despite the first surviving means either:
- Printk persistence loss: crash during `brcmf_sdio_register()` was so fast the preceding marker didn't flush to the stream reader.
- Async HW crash between two consecutive C statements (very fast hardware event).

**Post-SMC PCIe state (2026-04-20):**
- Root port `00:1c.2`: `DLActive+`, `CommClk+`, `MAbort-`, bus `03/03` — clean.
- Endpoint `03:00.0`: present, `MAbort-`, AER clear, `DevSta: CorrErr+ UnsupReq+` (expected from UR guard).
- No driver bound to 03:00.0; no bcma/wl/brcm modules loaded.

---

## Previous state (2026-04-19 23:18 BST, PRE test.148 — PCIe clean; ready to run stage0)

### CODE STATE: test.148 source prepared, rebuilt, committed, and pushed

**test.148 change: no-hardware-access discriminator**
- No new BAR0 MMIO, BAR2 MMIO, PCI config accesses, or pre-probe mitigation.
- `brcmf_pcie_early_arm_halt()` remains a module_init marker only:
  - `BCM4360 test.148: module_init entry (no BAR0 MMIO)`
- `brcmfmac_module_init()` now logs around the bus-registration fanout:
  - `BCM4360 test.148: before brcmf_core_init()`
  - `BCM4360 test.148: after brcmf_core_init() err=%d`
- `brcmf_core_init()` now logs:
  - `BCM4360 test.148: brcmf_core_init() entry`
  - before/after `brcmf_sdio_register()`
  - before/after `brcmf_usb_register()`
  - before/after `brcmf_pcie_register()`
- `core.c` is now included in the tracked brcmfmac source allowlist because the PCI call-site lives there.
- `brcmf_pcie_register()` still skips the early `brcmf_dbg(PCIE, "Enter\n")` call and logs:
  - `BCM4360 test.148: brcmf_pcie_register() entry`
  - `BCM4360 test.148: skipping brcmf_dbg in brcmf_pcie_register`
  - `BCM4360 test.148: after skipped brcmf_dbg, before pci_register_driver`
  - `BCM4360 test.148: pci_register_driver returned ret=%d`
- `test-staged-reset.sh` now writes `phase5/logs/test.148.stage0` and `.stream`.
- test.145 buscore_reset ARM halt remains in place if probe/chip_attach gets that far.

**Purpose:**
- test.147 skipped early `brcmf_dbg()` but only persisted the module-init entry marker.
- test.148 distinguishes:
  1. crash before `brcmf_core_init()`
  2. crash in SDIO/USB registration before PCI registration
  3. crash at/around the call to `brcmf_pcie_register()`
  4. crash inside `brcmf_pcie_register()` before `pci_register_driver()`
  5. successful PCI registration followed by probe/chip_attach progress

**Build status:**
- Rebuild completed with:
  `make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
- Build output: `brcmfmac.ko` linked; existing `brcmf_pcie_write_ram32` unused warning; BTF skipped because `vmlinux` is unavailable.

**Required before running test.148:**
- PRE-test.148 source/notes/harness state is committed and pushed:
  - `2924ae6 test.148: instrument core registration path`
- PCIe state verified clean immediately before running:
  - root port `00:1c.2` secondary/subordinate `03/03`, MAbort clear, `DLActive+`
  - endpoint `03:00.0` present, BAR0 `b0600000` size `32K`, BAR2 `b0400000` size `2M`
  - endpoint `Status` shows `<MAbort-`; AER `UESta` is clear, including `CmpltTO-` and `UnsupReq-`
  - endpoint `DevSta` still shows `CorrErr+` / `UnsupReq+`, matching prior fast-UR guard behavior

**Interpretation matrix:**
- Last marker `module_init entry`: crash before the `brcmf_core_init()` call-site marker; consider an ultra-minimal module-init/no-core-init discriminator.
- Last marker `before brcmf_core_init()`: crash entering `brcmf_core_init()` or marker persistence loss.
- Last marker before/after SDIO or USB registration: non-PCI bus registration side effect is implicated.
- Last marker `before brcmf_pcie_register()`: crash at/around the PCI registration call transition.
- Reaches `brcmf_pcie_register() entry`: continue interpreting the register-body markers.
- Reaches `after skipped brcmf_dbg, before pci_register_driver`: old `brcmf_dbg()` path is not the blocker; `pci_register_driver()` / probe becomes next suspect.
- Reaches `PROBE ENTRY`: registration path is past the current blocker; continue with existing buscore-reset/probe markers.

**Test command after rebuild/commit/push only:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Stage1 remains forbidden.

---

## Previous state (2026-04-19 23:07 BST, POST test.147 crash; SMC reset complete)

### CODE/LOG STATE: test.147 ran and crashed after module_init entry only

**Repository state before saving this snapshot:**
- Branch: `main`
- Remote tracking before notes/log commit: `main...origin/main`
- Source tree is unchanged from pushed commit `fdf5696 test.147: skip early PCIe debug trace`.
- New uncommitted files found after reboot:
  - `phase5/logs/test.147.stage0`
  - `phase5/logs/test.147.stage0.stream`
- User reports the machine restarted after the crash and SMC has been reset.

**Post-SMC PCIe state checked after reboot (2026-04-19 23:07 BST):**
- Root port `00:1c.2`:
  - Bus hierarchy is restored: primary `00`, secondary `03`, subordinate `03`.
  - `Status`, `Secondary status`, and `BridgeCtl` all show `<MAbort-` / `MAbort-`.
  - Link is up: `CommClk+`, `DLActive+`, speed `2.5GT/s`, width `x1`.
  - Kernel driver in use: `pcieport`.
- Endpoint `03:00.0`:
  - BCM4360 present: `14e4:43a0` rev `03`.
  - BAR0 `b0600000` size `32K`; BAR2 `b0400000` size `2M`.
  - `Status` shows `<MAbort-`; AER `UESta` is clear, including `CmpltTO-` and `UnsupReq-`.
  - `DevSta` still shows `CorrErr+` / `UnsupReq+`, consistent with prior deliberate BAR0 guard behavior.
  - Kernel modules listed: `bcma`, `wl`; no driver bound in the visible lspci output.

**test.147 RESULT (stage0 crash before `brcmf_pcie_register()` entry marker):**
- Pre-test BAR0 guard: fast UR/I/O error (`7ms`), not completion timeout; script proceeded.
- Pre-test PCIe/root-port state: endpoint present at `03:00.0`, bridge bus window `03/03`, MAbort clear.
- Stream log captured:
  - `brcmfmac: loading out-of-tree module taints kernel.`
  - `brcmfmac: BCM4360 test.147: module_init entry (no BAR0 MMIO)`
- Missing markers:
  - `BCM4360 test.147: brcmf_pcie_register() entry`
  - `BCM4360 test.147: skipping brcmf_dbg in brcmf_pcie_register`
  - `BCM4360 test.147: after skipped brcmf_dbg, before pci_register_driver`
  - `BCM4360 test.147: pci_register_driver returned ret=...`
  - `BCM4360 test.128: PROBE ENTRY`
  - `BCM4360 test.145: halting ARM CR4 after second SBR`

**Interpretation:**
- test.147 rules out the early `brcmf_dbg(PCIE, "Enter\n")` call as the immediate crash source for this run.
- The crash window has moved earlier than test.146: after the module-init entry marker and before the first statement in `brcmf_pcie_register()` emits.
- No intentional BAR0 MMIO, BAR2 MMIO, PCI config access, or `pci_register_driver()` call is reached in the visible log window.
- Best current inference: a host/asynchronous hardware failure is being triggered immediately by module insertion/initialization, or by work outside the visible PCIe registration code path between the module init marker and the function body marker. The exact ordering could also be affected by printk persistence across the crash, so one more marker at the call site is warranted.

**Recommended next candidate test (PRE test.148):**
1. Preserve and push this post-test.147 snapshot first.
2. Add a marker in `common.c` module init immediately before and immediately after the call to `brcmf_pcie_register()`.
3. Optionally make test.148 return before calling `brcmf_pcie_register()` as an ultra-safe host-only discriminator, but only after capturing the call-site marker layout in notes.
4. Do not add BAR0 MMIO, BAR2 MMIO, PCI config pokes, or any pre-probe mitigation yet.
5. Rebuild, then commit and push PRE-test.148 source/notes/harness before any run.

**Interpretation matrix for test.148:**
- Reaches `before brcmf_pcie_register call` but not `brcmf_pcie_register() entry`: crash is at/around the call transition or printk persistence lost the callee marker.
- Reaches `brcmf_pcie_register() entry`: test.147 likely lost later markers due to crash persistence; continue with narrower register-body markers.
- If a no-call variant returns safely: registering the PCI driver, or side effects around that call, are implicated.
- If a no-call variant still crashes: module insertion/taint/module-init plumbing or unrelated asynchronous hardware state is implicated before brcmfmac PCI registration.

**Hard rule remains:**
- Do not run stage1.
- Before running any future test, save notes, commit, and push.

---

## Previous state (2026-04-19 23:00 BST, PRE test.147 — skip early brcmf_dbg before PCI registration)

### CODE STATE: test.147 source prepared and rebuilt; commit/push required before running

**test.147 change: no-hardware-access discriminator**
- No new BAR0 MMIO, BAR2 MMIO, or PCI config accesses.
- `brcmf_pcie_early_arm_halt()` remains a module_init marker only:
  - `BCM4360 test.147: module_init entry (no BAR0 MMIO)`
- `brcmf_pcie_register()` now skips the early `brcmf_dbg(PCIE, "Enter\n")` call that immediately followed the last surviving test.146 marker.
- `brcmf_pcie_register()` now logs:
  - `BCM4360 test.147: brcmf_pcie_register() entry`
  - `BCM4360 test.147: skipping brcmf_dbg in brcmf_pcie_register`
  - `BCM4360 test.147: after skipped brcmf_dbg, before pci_register_driver`
  - `BCM4360 test.147: pci_register_driver returned ret=%d`
- `test-staged-reset.sh` now writes `phase5/logs/test.147.stage0` and `.stream`.
- test.145 buscore_reset ARM halt remains in place if probe/chip_attach gets that far.

**Purpose:**
- test.146 crashed after `before brcmf_dbg in brcmf_pcie_register` and before `after brcmf_dbg, before pci_register_driver`.
- Since `brcmf_dbg()` may always emit `trace_brcmf_dbg(...)` in this build, test.147 distinguishes a tracing/debug-path crash from an asynchronous hardware crash in the same tiny window.

**Build status:**
- Rebuild completed with:
  `make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
- Build output: `brcmfmac.ko` linked; existing `brcmf_pcie_write_ram32` unused warning; BTF skipped because `vmlinux` is unavailable.

**Required before running test.147:**
- Commit and push the PRE-test.147 source/notes/harness state.
- Verify PCIe state is still clean:
  - root port `00:1c.2` secondary/subordinate `03/03`, MAbort clear
  - endpoint `03:00.0` present, MAbort clear

**Interpretation matrix:**
- Reaches `after skipped brcmf_dbg, before pci_register_driver`: `brcmf_dbg()`/tracepoint path is implicated; keep early registration free of `brcmf_dbg()` while isolating the tracing hazard.
- Crashes before that marker despite the skipped `brcmf_dbg()`: asynchronous hardware crash remains likely immediately after module_init/register entry.
- Reaches `pci_register_driver returned ret=...`: registration returned; inspect following markers for probe/chip_attach/buscore_reset progress.
- Reaches `PROBE ENTRY`: registration path is past the previous blocker; continue interpreting probe path with the existing buscore-reset ARM halt markers.

**Test command after rebuild/commit/push only:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Stage1 remains forbidden.

---

## Previous state (2026-04-19 22:57 BST, POST test.146 crash; SMC reset complete)

### CODE/LOG STATE: test.146 ran and crashed in the brcmf_dbg() registration window

**Repository state before saving this snapshot:**
- Branch: `main`
- Remote tracking: `main...origin/main`
- New uncommitted files found after reboot:
  - `phase5/logs/test.146.stage0`
  - `phase5/logs/test.146.stage0.stream`
- User reports the machine restarted after the crash and SMC has been reset.

**Post-SMC PCIe state checked after reboot:**
- Root port `00:1c.2`:
  - Bus hierarchy is restored: primary `00`, secondary `03`, subordinate `03`.
  - Status/secondary status/BridgeCtl show `<MAbort-` / `MAbort-`.
  - Kernel driver in use: `pcieport`.
  - Non-root lspci showed capability details as `<access denied>`, but the visible bridge state is clean enough for planning.
- Endpoint `03:00.0`:
  - BCM4360 present: `14e4:43a0` rev `03`.
  - BAR0 `b0600000` size `32K`; BAR2 `b0400000` size `2M`.
  - Status shows `<MAbort-`.
  - Kernel modules listed: `bcma`, `wl`; no driver bound in the visible lspci output.

**test.146 RESULT (stage0 crash before `pci_register_driver()`):**
- Pre-test BAR0 guard: fast UR/I/O error (`6ms`), not completion timeout; script proceeded.
- Pre-test PCIe/root-port state: endpoint present at `03:00.0`, bridge bus window `03/03`, MAbort clear.
- Stream log captured:
  - `brcmfmac: loading out-of-tree module taints kernel.`
  - `brcmfmac: BCM4360 test.146: module_init entry (no BAR0 MMIO)`
  - `brcmfmac: BCM4360 test.146: brcmf_pcie_register() entry`
  - `brcmfmac: BCM4360 test.146: before brcmf_dbg in brcmf_pcie_register`
- Missing markers:
  - `BCM4360 test.146: after brcmf_dbg, before pci_register_driver`
  - `BCM4360 test.146: pci_register_driver returned ret=...`
  - `BCM4360 test.128: PROBE ENTRY`
  - `BCM4360 test.145: halting ARM CR4 after second SBR`

**Interpretation:**
- The crash is before `pci_register_driver()`, not in PCI registration/enumeration and not in probe.
- The next statement after the last marker is `brcmf_dbg(PCIE, "Enter\n")`.
- In this build, `brcmf_dbg()` maps to `__brcmf_dbg()` when `CONFIG_BRCM_TRACING` or `CONFIG_BRCMDBG` is enabled. `__brcmf_dbg()`:
  - conditionally calls `pr_debug()` only if `brcmf_msg_level & level`
  - always calls `trace_brcmf_dbg(level, func, &vaf)`
- There is no intentional BCM4360 BAR0/BAR2 MMIO or new PCI config access in this window.
- Best current inference: the crash is either inside the tracing/debug path itself, or an external asynchronous hardware crash happens in the tiny interval between the pre-`brcmf_dbg` marker and the next marker. Since test.145 stopped after only the register-entry marker and test.146 got to the pre-`brcmf_dbg` marker, the instrumentation has narrowed the immediate code window substantially.

**Recommended next candidate test (PRE test.147):**
1. Preserve and push this post-test.146 snapshot first.
2. Make test.147 a no-hardware-access discriminator:
   - remove or compile out the `brcmf_dbg(PCIE, "Enter\n")` call in `brcmf_pcie_register()`
   - keep emergency markers before and immediately before `pci_register_driver()`
   - add a marker immediately after `pci_register_driver()` returns
   - do not add BAR0 MMIO, BAR2 MMIO, PCI config pokes, or any pre-probe mitigation yet
3. Rebuild module.
4. Commit and push test.147 code/notes before running.
5. Run stage0 only after clean PCIe verification.

**Interpretation matrix for test.147:**
- Reaches `after skipped brcmf_dbg, before pci_register_driver`: `brcmf_dbg()`/tracepoint path is implicated; continue avoiding early `brcmf_dbg()` and then isolate why tracing is unsafe this early.
- Crashes before that marker despite removing `brcmf_dbg()`: asynchronous hardware crash is still possible immediately after module_init/register entry; consider even earlier host-only mitigation or deferring more module init work.
- Reaches `pci_register_driver returned ret=...`: registration completed; inspect subsequent probe markers.
- Reaches `PROBE ENTRY`: the old buscore-reset ARM halt may still be too late for some runs, but test.147 will have proven that `brcmf_dbg()` was blocking progress before registration.

**Hard rule remains:**
- Do not run stage1.
- Before running any future test, save notes, commit, and push.

---

## Previous state (2026-04-19, PRE test.146 — brcmf_pcie_register() window instrumentation)

### CODE STATE: test.146 source prepared, module rebuilt, committed and pushed

**test.146 change: instrumentation only**
- No new BAR0 MMIO and no new PCI config accesses.
- `brcmf_pcie_early_arm_halt()` remains a module_init marker only.
- `brcmf_pcie_register()` now logs:
  - `BCM4360 test.146: brcmf_pcie_register() entry`
  - `BCM4360 test.146: before brcmf_dbg in brcmf_pcie_register`
  - `BCM4360 test.146: after brcmf_dbg, before pci_register_driver`
  - `BCM4360 test.146: pci_register_driver returned ret=%d`
- `test-staged-reset.sh` now writes `phase5/logs/test.146.stage0` and `.stream`.
- test.145 buscore_reset ARM halt remains in place if probe/chip_attach gets that far.
- Rebuild completed with:
  `make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
- Build output: `brcmfmac.ko` linked; existing `brcmf_pcie_write_ram32` unused warning; BTF skipped because `vmlinux` is unavailable.
- Commit pushed: `5021abb test.146: instrument PCI register window`

**Purpose:**
- test.145 last stream marker was `brcmf_pcie_register() entry`; it did not show the old `calling pci_register_driver` marker.
- This test distinguishes:
  1. crash in/around `brcmf_dbg(PCIE, "Enter")`
  2. crash immediately before or inside `pci_register_driver()`
  3. successful return from `pci_register_driver()` followed by later async/probe crash

**Hardware recovery before running test.146:**
- User will perform SMC reset first.
- SMC reset is expected to be sufficient because previous SMC reset restored clean `03/03` PCIe hierarchy when normal cold reboot did not.
- Battery drain/full extended power removal is fallback only if SMC reset does not restore clean root-port/endpoint state or if the BAR0 timing guard indicates slow completion timeout.

**Pre-test checklist:**
- [x] SMC reset performed
- [x] `lspci -s 00:1c.2 -nn -vv` shows secondary/subordinate `03/03`, MAbort clear
- [x] `lspci -s 03:00.0 -nn -vv` shows endpoint present, MAbort clear, CommClk+
- [x] test.146 module rebuilt
- [x] PRE-test.146 code and notes committed/pushed

**Post-SMC chip status (2026-04-19 22:49 BST):**
- Git state before status check: clean, `main...origin/main`.
- Root port `00:1c.2`:
  - Bus hierarchy restored: primary `00`, secondary `03`, subordinate `03`.
  - `Status`: `<MAbort-`; secondary status `<MAbort-`.
  - `BridgeCtl`: `MAbort-`.
  - Link: `CommClk+`, `DLActive+`, speed `2.5GT/s`, width `x1`.
- Endpoint `03:00.0`:
  - BCM4360 present: `14e4:43a0` rev `03`.
  - BARs present: BAR0 `b0600000` size `32K`, BAR2 `b0400000` size `2M`.
  - `Status`: `<MAbort-`; `LnkCtl`: `CommClk+`; `LnkSta`: speed `2.5GT/s`, width `x1`.
  - AER UESta all clear, including `CmpltTO-` and `UnsupReq-`.
  - `DevSta` shows `CorrErr+` / `UnsupReq+` after the deliberate BAR0 timing probe; this is expected for the fast-UR probe and is not the slow completion-timeout failure.
- Timed BAR0 probe:
  - `sudo dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 of=/dev/null`
  - Result: exit `1`, `Input/output error`, elapsed `29ms`.
  - Interpretation: fast UR/I/O error, not slow CTO. Device is alive but BAR0 backplane bridge is not initialized; this is acceptable for test.146 stage0 because the harness guard treats `<40ms` as proceed.

**Interpretation matrix:**
- Last marker `module_init entry` only: crash before/inside `brcmf_pcie_register()`.
- Last marker `brcmf_pcie_register() entry`: crash before second marker; very small window after first printk.
- Last marker `before brcmf_dbg`: crash in `brcmf_dbg()` (unexpected, no hardware access intended).
- Last marker `after brcmf_dbg, before pci_register_driver`: crash inside `pci_register_driver()` / PCI enumeration before probe.
- `pci_register_driver returned ret=...`: registration returned; inspect following markers for probe/chip_attach/buscore_reset progress.
- `PROBE ENTRY` and buscore_reset test.145 markers appear: continue interpreting as test.145 path with more precise pre-register evidence.

**Test command after rebuild/commit/push only:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Stage1 remains forbidden.

---

## Previous state (2026-04-19 22:13 BST, POST test.145 crash)

### CODE STATE: test.145 binary was built and run

**Repository state at crash recovery:**
- `main` is clean and pushed to `origin/main`
- Preservation commit: `30a33bd test.145: capture post-crash state`
- Test.145 code commit: `a79d4c4 test.145: move ARM halt after second SBR`
- Test.145 crash logs are committed: `phase5/logs/test.145.stage0`, `phase5/logs/test.145.stage0.stream`
- Next action before any further test: commit/push the PRE-test.146 code and notes

**test.145 RESULT (stage0 crash during/after PCI registration):**
- Pre-test BAR0 guard: fast UR/I/O error (7ms), not CTO; script proceeded
- Pre-test PCIe state: endpoint present at `03:00.0`, root port `00:1c.2` had secondary/subordinate `03/03`, MAbort clear
- Stream log captured:
  - `brcmfmac: loading out-of-tree module taints kernel.`
  - `brcmfmac: BCM4360 test.145: module_init entry`
  - `brcmfmac: BCM4360 test.128: brcmf_pcie_register() entry`
- Missing markers:
  - `BCM4360 test.128: calling pci_register_driver`
  - `BCM4360 test.128: PROBE ENTRY`
  - `BCM4360 test.125: buscore_reset entry`
  - `BCM4360 test.145: halting ARM CR4 after second SBR`

**Crash window:**
- Later than test.143's "taint only" failure because `module_init entry` and `brcmf_pcie_register() entry` both printed.
- Earlier than the intended test.145 intervention point because `buscore_reset` was never reached.
- Likely inside `brcmf_pcie_register()` before or at the `pci_register_driver()` printk, or an asynchronous hardware/AER crash immediately after the register-entry printk.

**Interpretation:**
- Moving the second ARM halt to `buscore_reset()` is too late for this failure mode.
- Direct BAR0 MMIO in module_init is also unsafe on fresh hardware (test.144 UR crash).
- The next discriminator should instrument the tiny window inside `brcmf_pcie_register()` with synced/emergency markers around any work before `pci_register_driver()`, especially immediately before and after the "calling pci_register_driver" printk.
- Do NOT run stage1. Stage0 did not complete.

**Hardware recovery before next test:**
- Assume BCM4360/root port may be wedged after test.145 crash.
- Do SMC reset / full hardware power cut, not warm reboot.
- Verify root port and endpoint are clean before loading anything:
  - `lspci -s 00:1c.2 -nn -vv` shows secondary/subordinate `03/03`, MAbort clear
  - `lspci -s 03:00.0 -nn -vv` shows endpoint present, MAbort clear, CommClk+

**Next candidate test (PRE test.146):**
1. Keep test.145 behavioral change? Not useful yet, since crash is before buscore_reset.
2. Add ultra-narrow instrumentation inside `brcmf_pcie_register()`:
   - entry marker already exists
   - marker immediately before any statement after entry
   - marker immediately before `pci_register_driver`
   - marker immediately after `pci_register_driver` returns
   - sync-friendly stream logging remains mandatory
3. If crash is reproducibly before `pci_register_driver`, inspect pre-registration calls/data touched by `brcmf_pcie_register()`.
4. If crash is at/after `pci_register_driver` before probe, buscore_reset remains too late; need a no-BAR0 pre-probe mitigation or a PCI config-space-only reset/gating approach.
5. Commit and push test.146 notes/code before running the test.

---

## Previous current state (2026-04-19, PRE test.145 — ARM halt moved to buscore_reset after second SBR)

### CODE STATE: test.145 binary — REBUILD NEEDED

**test.144 RESULT (crash — UR at iowrite32 in brcmf_pcie_early_arm_halt):**
- Stream log: only "loading out-of-tree module taints kernel." then crash
- Journal (-b -1): confirmed "BCM4360 test.144: early ARM halt — module_init entry" then crash
- Root cause: `iowrite32(0x0023, bar0 + 0x1408)` in module_init hits UR on fresh chip (no prior driver run)
  - Fresh chip: PCIe-to-backplane bridge not yet initialized → BAR0 MMIO → UR → AER → host crash
  - Device IS alive (UR not CTO: 7ms pre-test, clean MAbort-) but backplane not accessible yet
- Fix: remove ioremap/iowrite32 from early_arm_halt (neutered to entry log only)
- Fix: add `brcmf_chip_set_passive(chip)` in `brcmf_pcie_buscore_reset()` after second SBR
  - chip_attach() calls set_passive once before SBR; second SBR releases ARM again
  - BCM4360 skipped second set_passive (legacy test.121); now done in buscore_reset instead
  - bridge is initialized by chip_attach before buscore_reset is called → MMIO safe

**test.145 plan: ARM halt in buscore_reset (after chip_attach initializes bridge)**
- `brcmf_pcie_early_arm_halt()`: neutered to entry log only (no MMIO)
- `brcmf_pcie_buscore_reset()`: for BCM4360, call `brcmf_chip_set_passive(chip)` after `brcmf_pcie_reset_device()`
- This is the same infrastructure as test.131+: set_passive already confirmed working in chip_attach path

**Hypothesis (test.145):**
- "BCM4360 test.145: module_init entry" appears ✓ (no MMIO crash)
- "BCM4360 test.145: halting ARM CR4 after second SBR (buscore_reset)" appears ✓
- "BCM4360 test.145: ARM CR4 halt done" appears ✓ → ARM halted, no more async crashes
- Probe completes, enter_download_state reached, firmware loads

**Interpretation matrix (test.145):**
- All three test.145 markers appear + enter_download_state → ARM halt worked; proceed to stage 1
- Crash between "halting ARM CR4 after second SBR (buscore_reset)" and "ARM CR4 halt done" → crash IN set_passive (unexpected)
- Crash after "ARM CR4 halt done" but before enter_download_state → ARM halted but other crash
- Only module_init entry appears + crash → something else crashed (not the MMIO we fixed)

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## test.144 RESULT (2026-04-19 crash — UR at iowrite32 in module_init early_arm_halt):

**Stream log (test.144.stage0.stream):**
- [1191.973808] brcmfmac: loading out-of-tree module taints kernel. ✓
- **CRASH** — "BCM4360 test.144: early ARM halt — module_init entry" never appeared in stream
  (confirmed via journal -b -1: entry log DID fire, crash was at the first iowrite32)
- Root cause: BAR0 MMIO on uninitialized chip → UR → AER FatalErr → host crash
- Pre-test state: clean (MAbort-, CommClk+, UR/I/O error 7ms)

---

## PRE-test.144 (2026-04-19, after SMC reset from test.143 crash)

**Hardware state (verified):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN) — fresh boot after test.142 crash

**test.142 RESULT (crash — BEFORE probe() — ARM killed host during PCIe enumeration window):**
- Stream log captured 5 lines then stopped:
  - [904.845] loading out-of-tree module taints kernel. ✓
  - [904.851] brcmf_pcie_register() entry ✓
  - [904.851] calling pci_register_driver ✓
  - [905.909] pcieport 0000:00:1c.2: Enabling MPC IRBNCE ✓
  - [905.909] pcieport 0000:00:1c.2: Intel PCH root port ACS workaround enabled ✓
  - **CRASH** — "BCM4360 test.128: PROBE ENTRY" never appeared
- Crash window: ~1s after insmod, during PCI driver enumeration (before probe() called)
- streaming fix WORKED — we got 5 lines instead of 0
- CONCLUSION: earlier-than-ever crash; but tests 137-141 all reached further; this is bad luck
- ARM executed garbage during the ~1s between pci_register_driver and probe() callback

**test.143 plan: RE-RUN test.142 code (no code change)**
- Same module, same parameters — we just need a surviving run to get ARM CR4 core->base
- Tests 137-141 all reached enter_download_state or later; test.142 crash was outlier bad luck
- Advisor: ~70% chance of getting core->base in one re-run
- If test.143 also crashes before probe(): implement EROM-walking ARM halt in module_init

**Hypothesis (test.143):**
- Likely (~70%) probe() is reached: "ARM CR4 core->base=0x180XXXXX" log appears after chip_attach
- If ARM reset block executes: RESET_CTL=0x00000001 (proper sequence with IOCTL=FGC|CLK first)
- If crashes before probe() again: need pre-chip_attach EROM-based ARM halt approach
- Streaming fix confirmed working (test.142 got 5 lines); will capture any probe-time messages

**Interpretation matrix (test.143):**
- "ARM CR4 core->base=0x180XXXXX" appears → use base in test.144 for pre-chip_attach reset
- Reset block fires + RESET_CTL=0x1 → ARM halted; proceed to BAR2 test (stage 1)
- Reset block fires + RESET_CTL=0xffffffff → wedged (unexpected with IOCTL=FGC|CLK first)
- Crashes before probe() again → implement EROM-walking ARM halt in module_init/earlier probe

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## test.142 RESULT (crash — BEFORE probe(); ARM crashed during PCIe enumeration window):

**Stream log (test.142.stage0.stream) — all 5 lines captured:**
- [904.845] brcmfmac: loading out-of-tree module taints kernel. ✓
- [904.851] BCM4360 test.128: brcmf_pcie_register() entry ✓
- [904.851] BCM4360 test.128: calling pci_register_driver ✓
- [905.909] pcieport 0000:00:1c.2: Enabling MPC IRBNCE ✓
- [905.909] pcieport 0000:00:1c.2: Intel PCH root port ACS workaround enabled ✓
- **CRASH** — "PROBE ENTRY" never appeared; crash ~1s after insmod
- Streaming fix CONFIRMED working (vs test.141 which captured 0 lines)
- CONCLUSION: ARM crash window struck during PCI enumeration delay, BEFORE probe() callback

---

## test.141 RESULT (crash — too early; logging failed; random async ARM crash):

**Stream log (test.141.stage0.stream):** null bytes after header — OS page cache lost on crash
**Journal (-b -1) last brcmf messages:**
- "BCM4360 test.128: PROBE ENTRY" ✓
- "BCM4360 test.127: probe entry" ✓
- "BCM4360 test.127: devinfo allocated, before pdev assign" ✓ [19:41:39]
- **CRASH** — all subsequent messages lost (crash at random point in 500ms SBR window)
- Machine rebooted at ~19:42:09 (35s after insmod)
- CONCLUSION: pure random async ARM crash; test.141 code correct but not reached

---

## test.140 RESULT (crash — wrapper wedged, missing IOCTL=FGC|CLK pre-step):

**Stream log (test.140.stage0.stream) — last entries:**
- All probe markers through ASPM-disable ✓
- "BCM4360 test.140: probe-time ARM CR4 reset asserted RESET_CTL=0xffffffff IN_RESET=YES" ← WEDGED
- Machine continued (probe setup kept running: PCIE2 setup, alloc, OTP bypass, fw request prep)
- CRASH — stream truncated mid-line at "before brcmf_fw_get_firmwares" (4096-byte FS block write)
- "brcmf_fw_get_firmwares returned async/success" NEVER appeared
- CONCLUSION: wrapper wedged by incomplete reset sequence; ARM likely still running; crash earlier than test.139

---

## test.139 RESULT (crash — async before firmware callback):

**Stream log (test.139.stage0.stream) — last entry:**
- All sync probe markers through "brcmf_fw_get_firmwares returned async/success" ✓
- **CRASH** — firmware load callback never fired; no enter_download_state markers
- CONCLUSION: ARM CR4 garbage killed host within ~1s of async fw request during disk load

---

## test.138 RESULT (crash — ASYNC confirmed: ARM_CR4 IOCTL read never reached):
- Markers appeared in stream:
  - "enter_download_state top" ✓ [488.082s]
  - "after select_core(ARM_CR4)" ✓ [488.382s]
  - "after RESET_CTL read = 0x0000" ✓ [488.682s]
  - **CRASH** — "ARM_CR4: RESET_CTL=..." diagnostic never appeared (300ms mdelay after RESET_CTL read)
- Neither "pre-BAR2-ioread32" nor "post-BAR2-ioread32" appeared
- CONCLUSION: **ASYNC crash** — ARM CR4 CPU executing garbage generates random PCIe errors
  - Crash window is non-deterministic: test.137 got further (through IOCTL read + diagnostic)
  - test.138 crashed earlier (between RESET_CTL read and IOCTL read)
  - This rules out a SYNC crash at ioread32(tcm) — crash is earlier, in a mdelay()
  - Root cause: ARM CR4 running without firmware → random garbage bus errors at any time

**Root cause confirmed:** ARM CR4 is running after SBR with RESET_CTL=0 (not in reset),
IOCTL=0x0001 (CLK=YES, CPUHALT=NO). It executes garbage, generating random PCIe errors
that crash the host. The crash window is any mdelay() or other time after insmod.

**test.139 plan: assert ARM CR4 reset immediately in enter_download_state**
- Put RESET_CTL=1 write at the top of the BCM4360 branch, with only select_core before it
- No diagnostic reads or mdelays BEFORE the reset write — minimize async crash window
- After write: mdelay(100), read back RESET_CTL to confirm, read IOCTL for diagnostics
- Keep test.138 BAR2 probe markers — if reset works, BAR2 should be accessible next

**Hypothesis (test.139):**
- After asserting RESET_CTL=1, ARM CR4 stops executing garbage → no more async crashes
- "post-reset RESET_CTL=..." marker should appear confirming reset asserted
- Then "pre-BAR2-ioread32" and "post-BAR2-ioread32" should both appear
- BAR2 probe may return real value (TCM accessible) or 0xffffffff (still not ready)

**Code changes for test.139 (enter_download_state BCM4360 branch):**
1. Remove all test.137 diagnostic read markers from enter_download_state
2. select_core(ARM_CR4) immediately
3. Write RESET_CTL=0x1 to assert reset (no mdelay before this)
4. mdelay(100) to allow reset propagation
5. Read back RESET_CTL and IOCTL to confirm state
6. Log "post-reset RESET_CTL=0x... IN_RESET=... IOCTL=0x... CPUHALT=... CLK=..."
7. mdelay(300) for journal flush, return 0
8. test.138 BAR2 probe block in download_fw_nvram unchanged

**Interpretation matrix (test.139):**
- "post-reset RESET_CTL..." appears, "pre-BAR2" appears, "post-BAR2" has real value → SUCCESS, proceed to copy_mem_todev
- "post-reset" appears, "pre-BAR2" appears, "post-BAR2" = 0xffffffff → BAR2 CTO (need more reset work)
- "post-reset" appears, "pre-BAR2" appears, "post-BAR2" never appears → sync crash at ioread32(tcm)
- "post-reset" appears, "pre-BAR2" never appears → async crash persists despite reset (need earlier reset)
- "post-reset" never appears → crash during RESET_CTL write or mdelay(100) → need earlier reset (probe time)

**If test.139 crashes before "post-reset":**
- Assert ARM CR4 reset even earlier — at end of probe right after SBR, not in enter_download_state

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Post-test: check both test.139.stage0 AND test.139.stage0.stream for markers.**

---

## test.138 RESULT (crash — ASYNC confirmed, ARM CR4 running garbage):

**Stream log (test.138.stage0.stream) — last entries:**
- "enter_download_state top" ✓ [488.082s]
- "after select_core(ARM_CR4)" ✓ [488.382s]
- "after RESET_CTL read = 0x0000" ✓ [488.682s]
- **CRASH** — "ARM_CR4: RESET_CTL=..." IOCTL diagnostic never appeared
- "pre-BAR2-ioread32" never appeared
- CONCLUSION: async crash during mdelay(300) after RESET_CTL read (or at IOCTL read)
- Non-deterministic: test.137 got further (IOCTL read succeeded), test.138 crashed earlier

---

## test.137 RESULT (crash — all ARM_CR4 BAR0 reads succeeded):

**Stream log (test.137.stage0.stream) — markers appeared:**
- All previous barriers ✓
- "post-mdelay — calling brcmf_pcie_download_fw_nvram" ✓ at [531.108655s]
- "enter_download_state top" ✓ at [531.108697s]
- "after select_core(ARM_CR4)" ✓ at [531.408774s]
- "after RESET_CTL read = 0x0000" ✓ at [531.708860s]
- "ARM_CR4: RESET_CTL=0x0000 IN_RESET=NO IOCTL=0x0001 CPUHALT=NO CLK=YES" ✓ at [532.008945s]
- **CRASH** — stream ends, "pre-BAR2-ioread32" never appeared

**ARM_CR4 state learned:**
- Core is running (not in reset, not halted) — executing garbage (no firmware loaded)
- All BAR0 wrapper register reads are STABLE and SAFE

---

## test.136 RESULT (crash — streaming confirms crash after "before brcmf_pcie_download_fw_nvram"):

**Stream log (test.136.stage0.stream) — last entry:**
- All markers through "before brcmf_pcie_download_fw_nvram" at [604.504043s] ✓
- **CRASH** — no further markers in stream
- ARM_CR4 diagnostic never appeared (brcmf_pcie_enter_download_state markers absent)

**Root cause: crash happens inside brcmf_pcie_download_fw_nvram, between the marker and first MMIO**

---

## Previous state (2026-04-19, PRE test.136 — streaming dmesg capture to catch crash markers)

### CODE STATE: test.135 binary (unchanged for test.136) — ARM_CR4 diagnostic + BAR2 probe

**Hardware state (verified):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN) — fresh boot after test.135 crash
- Fresh boot (boot 0 after test.135 crash)
- **Module IS built** — test.135 code in brcmfmac.ko (12:49 timestamp), no rebuild needed

**test.135 RESULT (INCONCLUSIVE — capture window too narrow, crash markers missed):**
- test.135 ran with the correct binary (verified: ARM_CR4 wrapper/BAR2 probe strings in .ko)
- Markers captured: all through "after brcmf_chip_get_raminfo" ✓ (same as test.134)
- Crash happened AFTER "after brcmf_chip_get_raminfo" at ~boot+273.4s
- ARM_CR4 reads at ~boot+274.3s and BAR2 probe at ~boot+274.6s BOTH missed by 2s capture window
- Machine crashed (rebooted) — journal only has 15 messages (hard reset lost later journal)
- ROOT CAUSE STILL UNKNOWN: could be ARM_CR4 reads, BAR2 probe, or copy_mem_todev

**Analysis of timing failure:**
- insmod at boot+271s → 2s sleep → dmesg snapshot at boot+273s
- "after brcmf_chip_get_raminfo" logged at boot+273.385s (just entered dmesg buffer)
- ARM_CR4 reads + "ARM_CR4 wrapper:" marker at boot+274.3s → MISSED
- BAR2 probe ioread32 + "BAR2 probe at offset 0x0" at boot+274.6s → MISSED
- Snapshot capture is the wrong approach when crash races with sleep

**Fix for test.136 — streaming capture:**
- Use `stdbuf -oL dmesg -wk >> log.stream &` started BEFORE insmod
- Add `sync` every second during 6s wait
- Kill stream background process after wait
- On crash: stream data already on disk up to crash moment
- Increase WAIT_SECS from 2 to 6 for stage 0 (ARM_CR4+BAR2 at insmod+3-4s)

**Hypothesis (test.136 / repeating test.135 with better capture):**
- ARM_CR4 reads via BAR0: BAR0 has been stable throughout, unlikely to crash
- BAR2 probe ioread32: FIRST ever BAR2 access — likely crash point OR returns 0xffffffff (CTO)
- If BAR2 probe crashes: BAR2 totally inaccessible → need to understand why
- If BAR2 probe returns 0xffffffff: CTO — ARM_CR4 not in correct state for TCM access
- If BAR2 probe returns real value: crash must be elsewhere (iowrite32 issue, not ioread32)

**No code changes needed — test.135 binary is correct, only test script updated.**

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Post-test: check both test.136.stage0 AND test.136.stage0.stream for markers.**

---

## test.135 RESULT (crash — capture window missed critical markers):

---

## test.134 RESULT (crash at first BAR2 write — brcmf_pcie_copy_mem_todev):

**Markers observed (from stage0 AND previous-boot journal):**
- All previous barriers passed ✓
- `BCM4360 test.134: post-attach before fw-ptr-extract` ✓
- `BCM4360 test.134: after kfree(fwreq)` ✓
- `BCM4360 test.130: before brcmf_chip_get_raminfo` ✓
- `BCM4360 test.130: after brcmf_chip_get_raminfo` ✓
- `BCM4360 test.130: after brcmf_pcie_adjust_ramsize` ✓
- `BCM4360 test.134: BusMaster re-enabled before fw-download; LnkCtl=0x0140 ASPM-bits=0x0` ✓
- `BCM4360 test.130: before brcmf_pcie_download_fw_nvram` ✓ (journal only)
- `BCM4360 test.130: brcmf_pcie_enter_download_state bypassed for BCM4360` ✓ (journal only)
- **CRASH** — no further markers

**Crash site: brcmf_pcie_copy_mem_todev — first iowrite32 to BAR2/TCM**

---

## Previous state (2026-04-19, PRE test.134 — mdelay flush markers + ASPM verify + BusMaster restore)

### CODE STATE: test.134 — mdelay(300) after every marker in brcmf_pcie_setup to force journal flush

**Hardware state (verified):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN) — fresh boot after test.133 crash
- Fresh boot (boot 0 after test.133)
- Module rebuilt: brcmfmac.ko compiled for test.134

**test.133 RESULT (MAJOR BREAKTHROUGH — new crash territory):**
- HYPOTHESIS CONFIRMED: BusMaster clear + ASPM disable eliminated the async crash barrier
- Got through ALL previous barriers: chip_attach, msgbuf alloc, pci_pme_capable, brcmf_alloc,
  firmware load, brcmf_pcie_setup entry, brcmf_pcie_attach bypass
- **Last marker seen: "BCM4360 test.128: after brcmf_pcie_attach" (pcie.c line 3601)**
- No markers after line 3601 visible in journal — but this may be message loss, NOT actual crash site
- Code between line 3601 and next marker (3610) is pure memory ops + kfree — no MMIO
- Most likely: crash is LATER (brcmf_pcie_download_fw_nvram MMIO write, ring buffer DMA, or IRQ setup)
  and earlier journal flush prevented those markers from being captured

**ASPM verification added for test.134:**
- Read LnkCtl register before and after pci_disable_link_state to confirm it actually disabled ASPM
- Previous test.133 had ASPM L0s L1 still visible in lspci pre-test (BIOS default), unknown if disabled

**Root cause hypothesis (test.134):**
- The crash site is likely brcmf_pcie_download_fw_nvram (line 3629) writing firmware to BAR2/TCM
  OR brcmf_pcie_select_core(BCMA_CORE_PCIE2) MMIO at line 3652
  OR brcmf_pcie_request_irq MSI setup at line 3654
- mdelay(300) after each marker will force journal to persist each step before the next risky operation

**Code changes for test.134 (pcie.c):**
1. ASPM verification: read LnkCtl before/after pci_disable_link_state, log the result
2. New bisection markers after "after brcmf_pcie_attach": "post-attach before fw-ptr-extract" + "after kfree(fwreq)"
3. mdelay(300) after EVERY pr_emerg in brcmf_pcie_setup (lines 3601-3660)
4. Re-enable BusMaster (pci_set_master) before firmware download with LnkCtl diagnostic print
5. All existing test.130 markers retained with mdelay(300) added after each

**Build status:** REBUILT — test.134 pcie.c compiled, brcmfmac.ko ready

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## test.133 RESULT (MAJOR BREAKTHROUGH — new crash territory after brcmf_pcie_attach):

**Markers observed (ALL new territory):**
- All markers through chip_attach (test.119) ✓
- `BCM4360 test.133: BusMaster cleared after chip_attach` ✓
- `BCM4360 test.133: ASPM disabled after chip_attach` ✓
- All struct wiring (test.132 markers: before/after pci_pme_capable) ✓
- `BCM4360 test.120: bus wired and drvdata set` ✓
- `BCM4360 test.120: brcmf_alloc complete` ✓
- OTP bypassed ✓
- `BCM4360 test.120: firmware request prepared` ✓
- `BCM4360 test.120: brcmf_fw_get_firmwares returned async/success` ✓
- Direct firmware load for clm_blob/txcap_blob FAILED (-2) — expected, files not present
- `BCM4360 test.128: brcmf_pcie_setup ENTRY ret=0` ✓
- `BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360` ✓
- `BCM4360 test.128: after brcmf_pcie_attach` ✓
- **CRASH** — no test.130 markers visible (may be journal message loss, not crash site)

**Key finding:**
- BusMaster clear + ASPM disable after chip_attach WORKED — completely eliminated the previous async crash
- This is the farthest we have ever gotten — into brcmf_pcie_setup firmware callback
- Journal log saved: phase5/logs/test.133.journal

---

## Previous state (2026-04-19, PRE test.133 — pci_clear_master + ASPM disable after chip_attach)

### CODE STATE: test.133 — BusMaster cleared and ASPM disabled immediately after chip_attach

**Hardware state (verified):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN)
- Fresh boot (boot 0 after test.132 crash)
- Module rebuilt: brcmfmac.ko compiled for test.133

**test.132 RESULT (previous crash):**
- Got to "bus allocated" (line 4018) then crashed — EARLIER than test.131-rerun which reached "msgbuf allocated"
- Confirmed crash is ASYNCHRONOUS — no hardware access between "bus allocated" and "msgbuf allocated"
- Journal showed no AER (pci=noaer suppresses logging) and no MCE oops → hard reset from SERR→NMI
- Stage0 log had "test.131" in loading message (typo, fixed for test.133)

**Root cause hypothesis (test.133):**
- After chip_attach, BusMaster is ON (set by pci_set_master in brcmf_pcie_buscoreprep)
- ASPM L0s/L1 is still enabled (reset_device bypassed, no ASPM disable)
- With BusMaster+ and no DMA mappings, BCM4360 may attempt stray DMA or the PCIe link may
  re-enter L1 during kernel allocations, causing completion errors that escalate via SERR→MCE
- Primary fix: pci_clear_master(pdev) immediately after chip_attach returns
- Secondary fix: pci_disable_link_state(PCIE_LINK_STATE_ASPM_ALL) after chip_attach

**Code changes for test.133 (pcie.c):**
- After chip_attach returns (after test.119 marker):
  1. pci_clear_master(pdev) — "BCM4360 test.133: BusMaster cleared after chip_attach"
  2. pci_disable_link_state(pdev, PCIE_LINK_STATE_ASPM_ALL) — "BCM4360 test.133: ASPM disabled"
- BusMaster is re-enabled at line 2051 (before ARM release) which is unchanged

**Hypothesis (test.133):**
- With BusMaster cleared and ASPM disabled, the async crash source is eliminated
- Should get past bus/msgbuf kzalloc, through struct wiring, through pci_pme_capable
- Should reach "bus wired and drvdata set" marker and continue into brcmf_alloc
- If crash still happens: root cause is something other than async DMA or ASPM

**Build status:** REBUILT — test.133 pcie.c compiled, brcmfmac.ko ready

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## test.132 RESULT (boot 0, crash — regressed earlier than test.131-rerun):

**Markers observed:**
- All markers through `BCM4360 test.119: brcmf_chip_attach returned successfully` ✓
- `BCM4360 test.120: reginfo selected (pcie2 rev=1)` ✓
- `BCM4360 test.120: pcie_bus_dev allocated` ✓
- `BCM4360 test.120: module params loaded` ✓
- `BCM4360 test.120: bus allocated` ✓
- **CRASH** — no "msgbuf allocated", no test.132 markers

**Analysis:**
- Crashed EARLIER than test.131-rerun (which got to "msgbuf allocated")
- Zero hardware access between "bus allocated" and "msgbuf allocated" → crash is ASYNC
- No AER events (pci=noaer), no MCE oops → hard reset from SERR#→NMI escalation
- BusMaster is ON after chip_attach (set in buscoreprep), ASPM is ON (never disabled)
- Async crash source: stray chip DMA or ASPM link re-entry → UR → SERR → MCE hard reset
- test.133 will clear BusMaster + disable ASPM after chip_attach to eliminate async sources

---

## Previous state (2026-04-19, PRE test.132 — bisect crash between msgbuf-alloc and bus-wired)

### CODE STATE: test.132 — marker-only bisection of crash gap after msgbuf allocation

**Hardware state (verified):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN)
- Fresh boot (boot 0, crash cycle 0)
- Module is built: brcmfmac.ko rebuilt for test.132

**Hypothesis (test.132):**
- test.131 re-run (boot -1, fresh hardware) crashed after "msgbuf allocated" marker (line 4027)
  before "bus wired and drvdata set" (line 4042).
- The 10-line gap contains only pure memory ops EXCEPT `pci_pme_capable(pdev, PCI_D3hot)` (line 4038)
  which reads PCI config space.
- Root port has SERR+ — a UR on config read from flaky endpoint could escalate to MCE → hard reset
- Primary suspect: pci_pme_capable() is the crash trigger
- Test.132 adds pr_emerg markers around each operation in the gap to bisect exactly

**Plan (test.132):**
Add markers at:
1. After msgbuf null-check (line ~4029): "before struct wiring"
2. After bus->chip = devinfo->coreid (line ~4038): "before pci_pme_capable"
3. After pci_pme_capable (line ~4039): "after pci_pme_capable"
4. After dev_set_drvdata (line ~4040): "bus wired" (already exists)

**Build status:** REBUILT — test.132 pcie.c compiled, brcmfmac.ko ready

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## test.131 RE-RUN RESULT (boot -1, crash cycle 0 — MAJOR PROGRESS):

**Markers observed:**
- `BCM4360 test.127: probe entry` ✓
- `BCM4360 test.53: SBR complete` ✓
- `BCM4360 test.53: BAR0 probe = 0x15034360 — alive` ✓
- `BCM4360 test.131: BAR0 2nd probe = 0x15034360 — stable` ✓ (stability check passed!)
- `BCM4360 test.125: buscore_reset entry` ✓
- `BCM4360 test.122: reset_device bypassed` ✓
- `BCM4360 test.126: skipping PCIE2 mailbox clear` ✓
- `BCM4360 test.119: brcmf_chip_attach returned successfully` ✓
- `BCM4360 test.120: reginfo selected (pcie2 rev=1)` ✓
- `BCM4360 test.120: pcie_bus_dev allocated` ✓
- `BCM4360 test.120: bus allocated` ✓
- `BCM4360 test.120: msgbuf allocated` ✓
- **CRASH** — no further markers

**Analysis:**
- HYPOTHESIS CONFIRMED: 500ms delay on fresh hardware (crash cycle 0) succeeded past BAR0 probe
- BAR0 2nd probe stable confirms the delay doesn't cause ASPM regression on clean HW
- chip_attach succeeded — this is the farthest we've ever gotten
- Crash moved from "before BAR0 probe" → "after msgbuf allocation" — enormous progress
- Crash point is now in the 10-line gap (pcie.c ~4029-4042) between msgbuf kzalloc and bus wiring
- Most likely culprit: `pci_pme_capable(pdev, PCI_D3hot)` (only PCI config read in that block)
- Hard reset (no oops) consistent with MCE from UR on PCIe config access

**Journal saved:** phase5/logs/test.131-rerun.journal

---

## test.131 RESULT (boot -1, crash cycle #3 from previous session):

Boot -1 journal markers:
- `BCM4360 test.128: brcmf_pcie_register() entry`
- `BCM4360 test.127: probe entry / devinfo allocated / devinfo->pdev assigned`
- `BCM4360 test.53: SBR via bridge 0000:00:1c.2 (bridge_ctrl=0x0002) before chip_attach`
- `BCM4360 test.53: SBR complete — bridge_ctrl restored`
- **NO** BAR0 probe marker, NO chip_attach marker → crashed in brcmf_pcie_get_resource

**Analysis — same crash point as test.130 re-run (crash cycle #2):**
- test.131 crashed BEFORE the first BAR0 probe print (line 3184 ioread32 or earlier)
- test.130 re-run (200ms) had same crash point: SBR complete, no BAR0 probe
- CONFOUND: test.131 had BOTH 500ms delay AND was crash cycle #3 — can't attribute to delay alone
- To isolate: must re-run test.131 code on fresh hardware (boot 0, zero prior crashes this session)

**Fresh boot state (boot 0, current):**
- Endpoint (03:00.0): MAbort- — CLEAN
- Module not built (out-of-tree modules don't survive reboot) — MUST REBUILD before test

**Hypothesis (test.131 re-run on fresh boot):**
- On fresh hardware (0 prior crashes), 500ms delay should allow BAR0 probe to succeed
- If BAR0 probe prints and chip_attach completes → confirms cumulative degradation is the real enemy
- If crash happens at same point (before BAR0 probe) → 500ms delay genuinely broke something
  (possible cause: ASPM L1 engages during 500ms wait, first config access fails on link wakeup)

**Build status:** NOT YET REBUILT — run make before test

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## TEST.130 RE-RUN RESULT — 2026-04-19 (this session, after second crash)

### HARDWARE VARIANCE CRASH: chip_attach MMIO before buscore_reset (2nd consecutive)

**Boot -1 journal (test.130 re-run):**
- `BCM4360 test.53: SBR complete`
- `BCM4360 test.53: BAR0 probe = 0x15034360 — alive`
- CRASH (no chip_attach markers)

**Comparison:**
- test.130 run 1: got to `buscore_reset entry, ci assigned`, then crash
- test.130 re-run: crashed BEFORE buscore_reset (earlier than run 1)
- test.129 (previous session): got all the way to `brcmf_pcie_attach` (async callback)

**Conclusion:** test.130 code is correct. Hardware is experiencing cumulative timing degradation
after multiple crash cycles within the same session. Need longer post-SBR stabilization delay.

---

## PRE-TEST.130 RE-RUN (2026-04-19 session restart)

### CODE STATE: EARLY PROBE MARKERS ADDED FOR BCM4360

**test.126 stage0 result — crash with PCIE2 mailbox clear skipped:**

Test log (`phase5/logs/test.126.stage0`) cuts off during insmod, before any markers printed.
Unlike test.125 which printed buscore_reset entry, test.126 didn't print ANY test markers.

**Analysis:**
- test.125: crashed at PCIE2 mailbox write (got to buscore_reset)
- test.126: skipped PCIE2 mailbox write, but still crashed before buscore_reset
  
**Hypothesis:**
Crash is happening BEFORE buscore_reset, likely:
1. In brcmf_chip_attach (called before buscore_reset)
2. Or even earlier in probe before chip_attach (in SBR, devinfo allocation, etc.)

The test.126.stage0 log cuts off during "Loading brcmfmac ..." with no marker output.
This suggests either:
- Probe is never called (module load error)
- Probe crashes very early (before first dev_emerg statement at line 3871)

**Code changes for test.127 (pcie.c):**
Add pr_emerg markers at:
1. Very start of brcmf_pcie_probe (after device ID check) — `test.127: probe entry`
2. After devinfo kzalloc — `test.127: devinfo allocated`
3. After devinfo->pdev assign — `test.127: devinfo->pdev assigned, before SBR`
4. Keep test.126: early return to skip PCIE2 mailbox clear

**Hypothesis (test.127 stage0):**
test.126 crashed during insmod before ANY test markers printed. Crash is likely:
- In probe before first dev_emerg (line 3871 with SBR logging)
- Or possibly in module load/device binding before probe is even called

test.127 adds pr_emerg (printk) markers at the very start of probe to determine
if probe is called and how far we get. Expected result: markers will show exactly
where the crash occurs (likely at a kzalloc, pci_match_id, or pci_save_state call
that's racing with hardware still in recovery).

**Run:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Success criteria:**
- No crash
- Log contains test.127 probe entry marker (proves probe is called)
- Log shows all three test.127 markers (entry, devinfo allocated, devinfo->pdev assigned)
- If all three markers printed: crash is in SBR code, next test will isolate that

**Failure signatures:**
- No test.127 markers: probe not called or crashes before first pr_emerg
- Markers stop at specific point: identifies exact crash boundary

---

## TEST.127 EXECUTION — 2026-04-19 (session 2, after crash recovery)

**PRE-TEST STATE (verified):**
- test.126 crashed during insmod before any markers printed
- test.127 code compiled at 00:07 (pcie.c markers added, brcmfmac.ko built)
- Module built: Apr 19 00:07
- PCIe state verified clean: MAbort-, CommClk+
- test-staged-reset.sh updated with test.127 labels
- Hardware ready to test

**PLAN:**
Run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0` to execute test.127 stage0.

**HYPOTHESIS:**
test.126 crashed during insmod before ANY markers were printed. Crash occurs before `buscore_reset`.
test.127 adds pr_emerg markers at:
1. Probe entry (after device match)
2. After devinfo kzalloc
3. After pdev assignment

If these markers print, we know probe is being called and can identify exactly where the crash occurs.
If no markers print, crash is either in module initialization or in probe before first statement.

**EXPECTED OUTCOMES:**
- All 3 markers print → crash is in SBR code or after pdev assignment (next test: isolate SBR)
- Markers stop at marker 2 → crash in `pdev = pdev->bus->self` or nearby assignment
- Stops at marker 1 or no markers → crash in very early probe or module-level code

**SUCCESS CRITERIA:**
- Hardware survives insmod without hard crash
- At least marker 1 (probe entry) is visible in dmesg
- Log clearly identifies the crash boundary

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## Previous state (2026-04-19, POST test.126 stage0 crash — PCIE2 mailbox skipped, still crashed)

### CODE STATE: PCIE2 MAILBOX CLEAR BYPASSED FOR BCM4360

**test.125 stage0 result — crash at PCIE2 mailbox write:**

Journal markers from boot -1:
- `test.125: buscore_reset entry, ci assigned`
- `test.122: reset_device bypassed`
- `test.125: after reset_device return`
- `test.125: PCIE2 core found rev=1`
- `test.125: before PCIE2 reg read (reg=0x48)`
- `test.125: after PCIE2 reg read val=0x00000000`
- **NO** `test.125: before PCIE2 reg write` — crash occurred at/after the write

**Interpretation:**
PCIE2 mailbox read (reg=0x48) succeeded and returned 0x00000000 (mailbox already clear).
The write back to that register (`brcmf_pcie_write_reg32(devinfo, reg, val)`) crashed the machine —
MCE/completion timeout from writing to the PCIE2 core before it is ready.

Since val=0x00000000 (mailbox was already clear), the write is both unnecessary and lethal for BCM4360.

**Code changes for test.126 (pcie.c):**
- In `brcmf_pcie_buscore_reset`: after the reset_device bypass marker, add an early return for BCM4360
  before the PCIE2 core lookup and mailbox clear. Log `test.126: skipping PCIE2 mailbox clear; returning 0`.
- All other bypasses remain: reset_device body, RAM info fixed, module-params dummy, OTP bypass.
- Test script updated to log `test.126.stage0`.

**Hypothesis (test.126 stage0):**
- buscore_reset returns 0 cleanly for BCM4360.
- chip_attach continues: `after reset, before get_raminfo` (chip.c marker), then `get_raminfo returning 0`.
- `brcmf_chip_attach returned successfully` (test.119 marker).
- Probe continues past chip_attach. Next crash point unknown; may be in OTP or probe setup.
- If chip_attach marker is reached and crash happens later, we will continue narrowing.

**PCIe state (post-crash):** MAbort-, CommClk+, LnkSta 2.5GT/s x1 — clean.
**Build:** clean, only expected `brcmf_pcie_write_ram32` unused warning.

---

## Previous state (2026-04-18, POST test.125 stage0 crash — PCIE2 mailbox write)

### HARDWARE STATUS: STAGE0 CRASHED DURING CHIP_ATTACH, BEFORE RETURN

### HARDWARE STATUS: STAGE0 CRASHED DURING CHIP_ATTACH, BEFORE RETURN

`test.124.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.124.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~8ms) and proceeded.
- Root port bus numbering was sane (`secondary=03, subordinate=03`).
- Script reached `insmod`, then host crashed before `insmod returned`.

**Kernel journal markers (boot -1):**
- SBR worked; BAR0 probe `0x15034360 — alive`.
- `test.122: reset_device bypassed` ← LAST MARKER
- **No test.121** (post-reset passive skipped)
- **No test.119** (chip_attach returned)
- **No test.120/123/124** markers after that.

**Interpretation:**
Crash occurs after `reset_device` returns but before `brcmf_chip_attach` returns. This is within `brcmf_pcie_buscore_reset` (after reset call) or the subsequent `brcmf_chip_get_raminfo` call. `test.123` (identical code through this point) succeeded and reached "before OTP read". The regression indicates hardware state variance between runs, not code change.

**Candidate failure point:** `brcmf_pcie_buscore_reset`'s first post-reset MMIO:
```c
val = brcmf_pcie_read_reg32(devinfo, reg);  // PCIE2 mailbox read
```
This is the first BAR0 access after reset. If the device is not yet ready, a completion timeout → MCE could occur.

**Next code change (test.125):**
Add boundary markers to pinpoint crash site:
- In `brcmf_pcie_buscore_reset`: log at entry, after setting `devinfo->ci`, after `reset_device` returns, before PCIE2 reg read, after read, before write, after write.
- In `brcmf_chip_attach` (chip.c): log immediately after `ci->ops->reset` returns, before `brcmf_chip_get_raminfo` call, and before return.
- Keep all existing bypasses (reset_device body, RAM info, module-params dummy, OTP bypass).
- Keep `bcm4360_skip_arm=1`; stage1 forbidden.

**Hypothesis:** If crash is in PCIE2 mailbox MMIO, we'll see markers up to "after reset_device" but not "before PCIE2 reg read". In that case, we may need to skip that PCIE2 access for BCM4360 or delay until link stabilizes.

**Build:** clean via kernel build tree.

**Pre-run:** Force runtime PM on for bridge (00:1c.2) and endpoint (03:00.0), verify root port bus numbering.

---

## Previous state (2026-04-18, POST test.121 stage0 crash — early reset_device)

### HARDWARE STATUS: STAGE0 CRASHED INSIDE RESET_DEVICE BEFORE PCIE2 MARKER

`test.121.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.121.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Root port bus numbering was sane before test (`secondary=03, subordinate=03`).
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- Last persisted BCM4360 marker: `test.118: reset_device entering minimal reset path`.
- No `test.118: PCIE2 selected, ASPM disabled` marker persisted.
- No `test.121` fixed-RAM marker persisted.

**Post-crash hardware state:**
- PCI config still responds: BCM4360 `14e4:43a0`, COMMAND=0x0006.
- Root port bus numbering is sane after forcing runtime PM `on`.
- BAR0 direct read still fails fast (~7ms), not a slow completion timeout.

**Interpretation:**
- `test.121` did not test the fixed-RAM path; it crashed earlier.
- The crash boundary is now inside `brcmf_pcie_reset_device()` after the entry marker and before the PCIE2-selected marker.
- The suspect operation is the first reset-device PCIE2 core select and/or immediate ASPM config read/write.
- Probe-start SBR already reset the endpoint and made BAR0 alive, so the in-driver reset-device body is now a liability for BCM4360.

**Next code change:**
- Add `test.122`: for BCM4360, return early from `brcmf_pcie_reset_device()` after SBR/chip attach setup, skipping PCIE2 core select, ASPM toggles, watchdog, and PCIE2 config replay.
- Keep `test.121` fixed RAM info in place.
- Keep `bcm4360_skip_arm=1`; stage1 remains forbidden.

---

## Previous state (2026-04-18, PRE test.121 stage0 — fixed BCM4360 RAM info)

### CODE STATE: BCM4360 RAM-SIZING MMIO BYPASSED

`test.120` crashed after the post-reset passive skip and before any post-chip-attach probe setup markers. The next likely unsafe path is RAM sizing after reset.

**Code changes for test.121:**
- `brcmf_chip_get_raminfo()` now special-cases BCM4360 and uses the known RAM map directly:
  `rambase=0`, `ramsize=0xa0000`, `srsize=0`.
- This bypass applies to both the chip-recognition call and the later firmware-callback call.
- The post-reset passive skip marker was updated to `test.121`.
- Staged script now writes `phase5/logs/test.121.stage0`.

**Hypothesis (test.121 stage0):**
- If RAM-sizing MMIO caused the crash, journal should show:
  `test.121: post-reset passive skipped; using fixed RAM info next`,
  `test.121: using fixed RAM info ...`,
  `test.119: brcmf_chip_attach returned successfully`,
  and then the existing `test.120` post-chip-attach setup markers.
- If it still crashes before the fixed-RAM marker, the fault is asynchronous immediately after `reset_device`.
- If it reaches firmware download, keep `bcm4360_skip_arm=1` and stop at the safe no-ARM path; stage1 remains forbidden.

**Pre-run requirement:** force runtime PM `on` for `00:1c.2` and `03:00.0` if either is suspended, then verify root port bus is `secondary=03, subordinate=03`.

**Build:** clean via kernel build tree. Only note: BTF skipped because `vmlinux` is unavailable.

---

## Previous state (2026-04-18, POST test.120 stage0 crash — before RAM-info marker)

### HARDWARE STATUS: STAGE0 CRASHED IMMEDIATELY AFTER POST-RESET PASSIVE SKIP

`test.120.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.120.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Root port bus numbering was sane before test (`secondary=03, subordinate=03`).
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- `test.118: reset_device complete`.
- Last persisted BCM4360 marker: `test.119: skipping post-reset passive call`.
- No `test.119: entering raminfo after reset` marker persisted.
- No `test.120` post-chip-attach probe setup markers persisted.

**Interpretation:**
- `test.120` did not reach the post-chip-attach probe setup path.
- Compared with `test.119`, the crash boundary moved back into the tiny region after the post-reset passive skip and before/inside RAM-info handling.
- The remaining likely unsafe operation is `brcmf_chip_get_raminfo()`, which performs fresh core MMIO reads to size memory after reset.
- Earlier firmware-download work already established the BCM4360 RAM map: `rambase=0`, `ramsize=0xa0000`, `srsize=0`.

**Next code change:**
- Add `test.121`: for BCM4360, skip `brcmf_chip_get_raminfo()` during chip recognition and use the known RAM map directly.
- Keep `bcm4360_skip_arm=1`; stage1 remains forbidden.
- Continue to force runtime PM `on` before any future insmod if root port/endpoint are suspended.

---

## Previous state (2026-04-18, PRE test.120 stage0 — instrument post-chip-attach probe setup)

### CODE STATE: POST-CHIP-ATTACH PROBE SETUP MARKERS ADDED

`test.119` proved `brcmf_chip_attach()` returns successfully. Crash is now later in `brcmf_pcie_probe()` before firmware request/download.

**Code changes for test.120:**
- Added markers around PCIE2 core lookup/reginfo selection.
- Added markers around `pcie_bus_dev`, `bus`, and `msgbuf` allocation.
- Added marker after bus wiring / `dev_set_drvdata`.
- Added markers before/after `brcmf_alloc`.
- Added markers before/after OTP read.
- Added markers before/after firmware request preparation and firmware async request.
- Staged script now writes `phase5/logs/test.120.stage0`.

**Hypothesis (test.120 stage0):**
- If probe setup is safe, markers should reach `before brcmf_fw_get_firmwares` or `brcmf_fw_get_firmwares returned async/success`, then firmware request path should start.
- If a specific non-MMIO setup step unexpectedly crashes, the last marker identifies it.
- If firmware request starts but later crashes before callback, the boundary has moved into firmware loading/callback setup.

**Pre-run requirement:** force runtime PM `on` for `00:1c.2` and `03:00.0` if either is suspended, then verify root port bus is `secondary=03, subordinate=03`.

**Build:** clean via kernel build tree. Only warning: existing unused `brcmf_pcie_write_ram32`.

---

## Previous state (2026-04-18, POST test.119 stage0 crash — after chip_attach returns)

### HARDWARE STATUS: STAGE0 CRASHED AFTER CHIP_ATTACH RETURNED

`test.119.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.119.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~8ms) and proceeded.
- Root port bus numbering was sane before test after forcing runtime PM `on`.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked; BAR0 probe returned `0x15034360 — alive`.
- `test.118: reset_device complete`.
- `test.119: skipping post-reset passive call`.
- `test.119: entering raminfo after reset`.
- `test.119: brcmf_chip_attach returned successfully`.
- No later brcmfmac/BCM4360 markers persisted.

**Interpretation:**
- Skipping the second post-reset passive call worked.
- RAM info completed and `brcmf_chip_attach()` returned.
- Crash is now in the next part of `brcmf_pcie_probe()`, before firmware request/download and still before ARM release.
- Next suspect block: PCIE2 core lookup/reginfo setup, allocations, module params, `brcmf_alloc()`, OTP check, or firmware request preparation.

**Next code change:**
- Add `test.120` markers through the post-chip_attach probe setup path:
  PCIE2 core lookup/reginfo, `pcie_bus_dev` allocation, module params, bus/msgbuf allocation, `dev_set_drvdata`, `brcmf_alloc`, OTP, firmware request, and `brcmf_fw_get_firmwares`.
- No behavior change yet; just narrow the next crash boundary.
- Continue to force runtime PM `on` before any future insmod if root port/endpoint are suspended.

---

## Previous state (2026-04-18, PRE test.119 stage0 — skip post-reset passive)

### CODE STATE: POST-RESET PASSIVE CALL SKIPPED FOR BCM4360

`test.118` proved `brcmf_pcie_reset_device()` now completes. The next suspected operation is the second `brcmf_chip_set_passive()` in `brcmf_chip_recognition()` immediately after `ci->ops->reset()`.

**Code changes for test.119:**
- In `chip.c`, BCM4360 skips the post-reset passive call after `ops->reset`.
- Added marker before RAM info: `BCM4360 test.119: entering raminfo after reset`.
- Added marker after `brcmf_chip_attach()` returns in `pcie.c`.
- Staged script now writes `phase5/logs/test.119.stage0`.

**Hypothesis (test.119 stage0):**
- If post-reset passive caused the crash, journal should show `entering raminfo after reset`, `brcmf_chip_attach returned successfully`, then continue into firmware request/download.
- If RAM info probing is unsafe after skipping passive, the last marker will be `entering raminfo after reset`.
- If later probe setup is unsafe, the last marker will be `brcmf_chip_attach returned successfully`.
- ARM remains skipped; stage1 is still forbidden.

**Build:** clean via kernel build tree. Only warning: existing unused `brcmf_pcie_write_ram32`.

**Do not run until platform PCIe state is recovered:** after the test.118 crash, root port 00:1c.2 showed invalid bus numbering (`secondary=ff, subordinate=fe`). Reboot or full power-cycle before the next insmod; then verify root port bus is `secondary=03, subordinate=03` and BAR0 guard is fast UR/OK.

---

## Previous state (2026-04-18, POST test.118 stage0 crash — after reset_device complete)

### HARDWARE STATUS: STAGE0 CRASHED AFTER MINIMAL RESET_DEVICE COMPLETED

`test.118.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.118.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~5ms) and proceeded.
- Endpoint COMMAND was already `0x0000`; BARs disabled before test.
- Root port had `MAbort+` before test.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked: `test.53: SBR complete`
- BAR0 came alive after SBR: `test.53: BAR0 probe ... = 0x15034360 — alive`
- `test.118: reset_device entering minimal reset path`
- `test.118: PCIE2 selected, ASPM disabled`
- `test.118: ChipCommon watchdog skipped`
- `test.118: ASPM restored, entering PCIE2 cfg replay`
- `test.118: reset_device complete`
- No later brcmfmac/BCM4360 markers persisted.

**Current post-crash checks:**
- PCI config space still responds: BCM4360 `14e4:43a0`
- Endpoint COMMAND is `0x0000`; BARs disabled
- Root port config is damaged: bus shows `primary=00, secondary=ff, subordinate=fe`
- BAR0 userspace read still fails quickly (~7ms), not a slow CTO

**Interpretation:**
- The old reset-time diagnostics were not the final crash source.
- The minimal `brcmf_pcie_reset_device()` path now completes.
- The next code executed inside `brcmf_chip_recognition()` is the second `brcmf_chip_set_passive(&ci->pub)` immediately after `ci->ops->reset(...)`.
- Suspect: the second passive pass touches or disables a core that is unsafe after BCM4360 SBR/reset_device, causing the hard crash before `brcmf_chip_attach()` returns.

**Next code change before any more hardware tests:**
- Add `test.119` markers in `chip.c` around the post-reset passive step.
- For BCM4360, skip the second `brcmf_chip_set_passive()` after `ops->reset` and proceed to RAM info, because the initial passive call already ran before reset and the bus reset path completed.
- Add a `test.119` marker after `brcmf_chip_attach()` returns in `pcie.c` so the next test distinguishes chip-attach completion from later probe/setup work.
- Do not run stage1.

---

## Previous state (2026-04-18, PRE test.118 stage0 — minimal reset_device path)

### CODE STATE: OLD RESET-TIME DIAGNOSTICS REMOVED/GATED

`brcmf_pcie_reset_device()` has been simplified for BCM4360:
- Removed completed `test.111` core-list diagnostic from the reset path.
- Removed `test.112` ChipCommon FORCEHT write/poll from the reset path.
- Removed `test.114a` D11 wrapper read from the reset path.
- BCM4360 no longer selects ChipCommon solely to skip the watchdog write.
- New `test.118` markers bracket the remaining path: enter reset, PCIE2/ASPM, watchdog skipped, ASPM restore, PCIE2 cfg replay, reset complete.

**Hypothesis (test.118 stage0):**
- Pre-test BAR0 guard should see fast UR or normal MMIO and allow the run.
- SBR should restore BAR0; `test.53` should report `0x15034360 — alive`.
- The new `test.118` reset markers should reach `reset_device complete`.
- Firmware download should run and the `bcm4360_skip_arm=1` branch should return cleanly without ARM release.
- Module unload should complete.

**Run after build/commit/push:**
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

**Build:** clean via kernel build tree:
`make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
Only warning: existing unused `brcmf_pcie_write_ram32`.

---

## Previous state (2026-04-18, POST test.117 stage0 crash — reset_device diagnostic crash)

### HARDWARE STATUS: STAGE0 CRASHED; CURRENT BAR0 FAST I/O ERROR, ROOT PORT MAbort+

`test.117.stage0` was run with `bcm4360_skip_arm=1`; ARM was not released.

**Persisted script log:** `phase5/logs/test.117.stage0`
- Pre-test BAR0 guard saw fast UR/I/O error (~6ms) and proceeded.
- Script reached `insmod`, then the host crashed before `insmod returned`.

**Previous boot journal markers:**
- SBR worked: `test.53: SBR complete`
- BAR0 came alive after SBR: `test.53: BAR0 probe ... = 0x15034360 — alive`
- chip_attach completed far enough to enter `brcmf_pcie_reset_device`
- reset_device printed EFI/PMU/pllcontrol baseline
- last persisted BCM4360 line: `test.111: id=0x827 PMU NOT PRESENT`
- no `test.111` lines after PMU and no `test.112` / `test.114a` markers persisted

**Current post-crash checks:**
- PCI config space still responds: BCM4360 `14e4:43a0`
- Endpoint COMMAND is now `0x0000`; BARs are disabled
- Root port secondary status has `MAbort+`
- BAR0 userspace read still fails quickly (~8ms), not a slow CTO

**Interpretation:**
- The battery-drain recovery worked enough for probe-time SBR to restore BAR0 and for chip_attach to run.
- The crash is now inside or immediately after the old reset-time diagnostic area, not in ARM release and not in firmware execution.
- `test.111` had already served its purpose; keeping the core-list diagnostic and older `test.112` / `test.114a` probes in every reset path is now counterproductive.

**Next code change before any more hardware tests:**
- Remove or gate off the completed reset_device diagnostics (`test.111`, `test.112`, and `test.114a`) for BCM4360.
- Keep only the minimal production-relevant reset behavior: SBR before chip_attach, skip ChipCommon watchdog for BCM4360, ASPM handling if still needed, and the BAR0 guard.
- Add a new stage0 marker immediately before standard reset code and another immediately after reset_device returns, so the next test isolates whether standard reset still crashes once old diagnostics are removed.
- Do not run stage1 until a clean stage0 completes and the module unloads.

---

## Previous state (2026-04-18, PRE test.117 stage0 — battery-drain recovery, BAR0 UR)

### HARDWARE STATUS: CONFIG/LINK RECOVERED; BAR0 MMIO FAST I/O ERROR (UR), NOT CTO

Battery-drain recovery completed. Post-boot checks:
- PCI config space responds: BCM4360 `14e4:43a0`, COMMAND=0x0006.
- Root port 00:1c.2 is clean: no MAbort, link up, CommClk+.
- Userspace BAR0 read returns I/O error quickly (~6ms), not a slow Completion Timeout.
- Interpretation: adapter is in the recoverable UR/alive state; probe-time SBR should reset it before chip_attach.

**Harness fix before test:**
- `phase5/work/test-staged-reset.sh` now has the BAR0 timing guard from `test-brcmfmac.sh`.
- Stage0 uses `bcm4360_skip_arm=1`; ARM must not be released in this first recovery test.

**Hypothesis (test.117 stage0):**
- Pre-test BAR0 guard reports UR/I/O error under 40ms and allows the run.
- Probe-time SBR restores BAR0 MMIO; `test.53` BAR0 probe reports `0x15034360 — alive`.
- chip_attach completes, reset_device reaches `test.114c.1` through `.5`, watchdog is skipped for BCM4360, firmware download completes, skip_arm branch aborts cleanly, and module unload succeeds.

**Run:**
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Previous state (2026-04-18, POST test.114d crash — BAR0 MMIO dead, power cycle needed)

### HARDWARE STATUS: BAR0 MMIO DEAD — config space accessible, MMIO I/O error

**POST test.114d result (2026-04-18):**
- Last marker printed: test.53 "BAR0 probe = 0x15034360 — alive"
- No test.114c.X markers printed — crash during chip_attach MMIO (before brcmf_pcie_reset_device)
- BAR0 MMIO now dead (dd resource0 → I/O error). Config space accessible (COMMAND=0x0006)
- Log saved: phase5/logs/test.114d.stage0

**Root cause analysis:**
- test.114c's watchdog write (`WRITECC32(watchdog, 4)`) crashed the PCIe link → MCE → reboot
- Machine rebooted but NOT a power cycle (battery keeps VAUX alive)
- BCM4360 was left in partial watchdog-reset state: ChipCommon accessible, other BCMA cores broken
- test.114d: SBR at probe start ran, BAR0 probe @ ChipCommon = 0x15034360 (alive), but
  chip_attach scans ALL BCMA core wrappers via MMIO → hit broken core → CTO → MCE → crash
- SBR is insufficient to recover from a watchdog-mid-reset state. Full power cycle required.

**HARDWARE STATUS: POWER CYCLE REQUIRED (battery drain)**

**Next steps after power cycle:**
1. Module already built with test.114d changes (watchdog skip for BCM4360, marker 3a)
2. No rebuild needed after power cycle — just run test
3. Run `sudo ./test-brcmfmac.sh` (stage0, skip_arm=1)
4. Expect: test.114c.1 through test.114c.5 all print, no crash (watchdog skipped for BCM4360)
5. If stage0 clean: run stage1 (skip_arm=0) for BBPLL + ARM release test

**Hypothesis (test.114d after power cycle):**
- With fresh power-on reset state, chip_attach MMIO will succeed (all cores accessible)
- Markers .3, .3a, .4, .5 all print (ASPM disabled, CC selected, watchdog SKIPPED, PCIE2 reselected)
- Stage0 completes without crash

---

## Previous state (2026-04-18, POST recovery crash — brcmf_pcie_reset_device watchdog crash)

### HARDWARE STATUS: BCM4360 MMIO UR (alive, recoverable) — SBR should fix for next test

**Test run (2026-04-18, ~10:43):** After battery-drain recovery, device was alive. Ran test
with SBR-in-probe + BAR0 abort guard. Device got further than ever (chip_attach succeeded,
core enumeration complete) but crashed silently after test.114a log line.

**Observations vs hypothesis:**
- BAR0 probe AFTER SBR = 0x15034360 — ALIVE. SBR worked correctly.
- BAR0 abort guard did NOT fire (correct — BAR0 was alive, guard only fires on 0xffffffff).
  User framing "guard should have fired" was mistaken — guard worked as designed.
- HT TIMEOUT at test.112: FORCEHT written, 100×100µs poll, clk_ctl_st=0x00050042, never got HAVEHT.
- test.114a: d11 wrap_RESET_CTL=0x00000000 IN_RESET=NO wrap_IOCTL=0x00000001
  UNEXPECTED: set_passive should leave d11 IN reset. IN_RESET=NO means d11 already out of reset
  before our test.114a ran (either SBR didn't reset BCMA state, or set_passive didn't coredisable).
- Crash: silent MCE-level, after test.114a log, NO further kernel output.
- Current MMIO: I/O error in ~0.5ms (UR = fast, Unsupported Request). Device alive, SBR will fix.

**Crash location: somewhere in brcmf_pcie_reset_device after test.114a block (lines 895–932).**
Candidates (in order executed after test.114a):
  - L895: select_core(CHIPCOMMON) — BAR0 write, right after test.114a log
  - L901: select_core(PCIE2) — BAR0 write
  - L909: select_core(CHIPCOMMON) — BAR0 write
  - L910: WRITECC32(watchdog, 4) — resets chip in ~200ns
  - L914: select_core(PCIE2) — first BAR0 write after watchdog fires
  - L918+: more MMIO if PCIE2 rev <= 13
Best guess: watchdog=4 kills PCIe link, then L914 select_core(PCIE2) fires → CTO → MCE.
NOT CONFIRMED — bisection markers added to next build.

**Log saved:** phase5/logs/test_20260418_watchdog_crash.log

**Next test hypothesis:** Markers will tell us the exact crash site. Last marker printed = instruction before crash.

**Next steps:**
1. Build: `make -C /home/kimptoc/bcm4360-re/phase5/work` (bisection markers added to pcie.c)
2. Run test script — look for last test.114c.N marker in dmesg
3. If last marker is test.114c.3 (pre-watchdog): watchdog write itself crashes → skip watchdog for BCM4360
4. If last marker is test.114c.4 (post-watchdog-sleep): link didn't recover in 100ms → extend sleep
5. If last marker is test.114c.1 or .2: crash is at CC or PCIE2 select_core BEFORE watchdog

---

## Previous state (2026-04-17, POST test.116 stage0 crash x2 — MMIO DEAD, DRAINING BATTERY FOR RECOVERY)

### HARDWARE STATUS (RESOLVED): BCM4360 MMIO NON-RESPONSIVE — POWER CYCLE REQUIRED

**Diagnosis (2026-04-17, post-second-crash):** BCM4360 BAR0 MMIO is completely non-responsive.
Confirmed via direct userspace probe:
- `setpci -s 03:00.0 COMMAND` = 0x0006: config space IS accessible (device visible)
- `dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1` → **I/O error**: MMIO DEAD
- This was reproduced across: manual SBR via setpci, kernel device reset (`echo 1 > reset`),
  device remove+rescan. Nothing recovers MMIO.
- `FLReset-` in DevCap: BCM4360 has no Function Level Reset capability.

**Root cause confirmed:** The test.114 stage1 firmware execution (ARM release + ~400ms hang wait)
left the BCM4360's PCIe endpoint or BCMA AXI fabric in a state that soft reset cannot clear.
A system reboot does NOT cut PCIe slot power (VAUX stays on). Only a full hardware power cycle
(complete shutdown, wait, power on) will clear this state.

**"Reboot fixes it" hypothesis was WRONG.** test.116 stage0 was run TWICE after full reboots;
both times it crashed hard (no kernel output, MCE-level crash). Userspace now confirms the
device itself is not responding to MMIO at all — the crashes were always Completion Timeout → MCE.

**Next step: FULL POWER CYCLE — MacBook-specific recovery procedure**

This machine is a pre-2018 MacBook with non-removable battery. Standard shutdown does NOT
cut PCIe slot power (VAUX stays on via battery). Attempted recovery methods, in order tried:

1. `shutdown -h now` + wait — FAILED (battery keeps VAUX alive)
2. Unplug mains — IRRELEVANT (laptop on battery anyway)
3. SMC reset (Shift+Ctrl+Option+Power, 10s) — FAILED (state too deep in BCM4360 hardware)
4. Boot macOS to let Apple kext reinitialize card — NOT POSSIBLE (no macOS partition)

**Only remaining option: drain battery to 0%**
Run `stress-ng --cpu 0 --vm 2 --vm-bytes 80%` with no charger until machine shuts off from
empty battery. Wait 2-3 minutes. Plug in charger. Power on. Test MMIO.

After recovery, verify BEFORE any test:
`dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd`
Must return 4 bytes (no I/O error). If still dead → something is wrong at the PCIe root port level.

### What to do after power cycle

After power cycle, before ANY test:

1. **Verify MMIO works:** `dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1 | xxd`
   Should return 4 bytes (any value, not I/O error). If I/O error → power cycle again.

2. **Module NOT built.** Run: `make -C /home/kimptoc/bcm4360-re/phase5/work`
   (no .ko file survived the crash)

3. **Run test.116 stage0.** With MMIO restored, the d11 guard should finally be testable.
   Hypothesis: BAR0 probe returns alive, d11 IN_RESET=YES (no wl driver), guard skips 0x1e0
   read, stage0 completes cleanly.

4. **Only after stage0 clean:** run stage1 with skip_arm=0.
   CRITICAL FOR STAGE1: After ARM is released and test completes, do NOT leave module loaded
   long-term. Unload promptly to avoid another firmware-induced MMIO corruption.

### Prevention for future stage1 tests — CRITICAL on MacBook

**On this MacBook, MMIO corruption = hours of recovery time** (battery drain is the only fix).
The cost of another stage1 crash is very high. Before running stage1 again:

1. **Understand why stage0 crashes at BAR0 probe** — the d11 guard was never reached because
   both test.116 runs crashed in `brcmf_pcie_get_resource` (BAR0 ioread32) before reset_device.
   This suggests the MMIO was already dead BEFORE insmod — the pre-test MMIO check is mandatory.

2. **Add userspace MMIO check to test script** — script should abort if resource0 returns I/O
   error before attempting insmod.

3. **After any stage1 ARM release:** rmmod within the observation window. Do NOT leave loaded.
   If stage1 crashes: expect battery-drain recovery required before next run.

4. **Consider a SBR in the test script** before insmod (1000ms wait) to clear CommClk- state.

### Test.116 stage0 crash analysis (both crashes)

test.116 stage0 crashed TWICE. Both crashes produced NO kernel output (hard MCE-level crash).
The SBR in `brcmf_pcie_probe` may or may not have logged "SBR complete" — the dmesg capture
only runs if insmod returns, but both runs had insmod hard-crash the machine. The userspace
MMIO test confirms the crash was at `ioread32(devinfo->regs)` in brcmf_pcie_get_resource
(test.53 BAR0 probe) — PCIe Completion Timeout → MCE. With `pci=noaer` in boot params and
`FatalErr+` on root port, there is NO soft error recovery for this path.

**The d11 guard was never reached.** Both test.116 crashes happened in get_resource (prepare
callback), before reset_device (reset callback) where the guard lives.

**Module status:** pcie.c has d11 guard. Module NOT built (.ko was cleared by crash).
Rebuild required: `make -C /home/kimptoc/bcm4360-re/phase5/work`

**MAbort+ on root port secondary status is BASELINE** (present since test.100).

### Analysis of test.114 stage1 + test.115 crash (completed 2026-04-17)

**test.114 stage1 key results:**
- d11 wrap_RESET_CTL=0x00000000 IN_RESET=NO (d11 was already out of BCMA reset)
- test.47 BBPLL bringup succeeded: pmustatus=0x0000002e, clk_ctl_st=0x01030040 HAVEHT=YES
- test.107 T+200ms: d11.clk_ctl_st=0x070b0042 — this means:
  - Bit 19 (BP_ON_HT) = 0x070b0042 & 0x00080000 = 0x00080000 ≠ 0 → **BP_ON_HT=YES**
  - Bit 17 (HAVEHT) = YES, Bit 1 (FORCEHT) = YES
  - **CORRECTION:** earlier pice.c comment claimed BP_ON_HT=0 — this was wrong
- FW wrote FORCEHT and BP_ON_HT was granted → fn 0x1415c (the d11 clock poll) likely EXITED
- Anchor F at T+200ms: [0x9CF6C]=0x00068c49 (exp 0x68b95) MISMATCH
  - Frame pointer shifted — hang has MOVED downstream to ~FW address 0x68c49
- Counter still at 0x43b1 at T+400ms → FW blocked in si_attach nested call (different site)

**test.115 stage0 crash:**
- PCIe state showed CommClk-, MAbort+ (bad state left by test.114 stage1 ARM release)
- Crashed during insmod (hard crash, no kernel logs)
- Machine has since rebooted; PCIe state should be clean now

**pcie.c changes made (this session):**
- test.114b comment: corrected BP_ON_HT analysis (was wrong; BP_ON_HT IS set in test.114 stage1)
- test.114b block: added `d11_wrap_ioctl` readback from wrapper offset 0x1408 (was missing)
  - Now logs: `wrap_RESET_CTL=... IN_RESET=... wrap_IOCTL=... CLK=...`
  - CLK=YES means BCMA_IOCTL_CLK (bit 0) is set → AXI slave accessible

**Outstanding question:**
- With BBPLL up and d11 out of reset, FW exits fn 0x1415c. What is the NEW hang site near 0x68c49?
- Need to re-probe: run test.115 stage0 (clean d11 IOCTL snapshot), then stage1 to see if counter advances

**Module status:** pice.c edited, NOT yet rebuilt. Run `make` in phase5/work/ before testing.

**Next steps:**
1. Build: `make -C /home/kimptoc/bcm4360-re/phase5/work`
2. Run test.115 stage0 (skip_arm=1) → get clean d11 IOCTL value after cr4_set_passive
3. Run test.115 stage1 (skip_arm=0, BBPLL up, no resetcore) → does counter advance past 0x43b1?
   - YES → hang moved; need new stack frame probes for FW ~0x68c49
   - NO  → something else blocks (check IOCTL value from stage0)

---

## Previous state (2026-04-17, PRE test.114 — d11 enable before ARM release, module built)

### Test.113 crash analysis (completed 2026-04-17)

test.113 was designed to read d11.clk_ctl_st and write FORCEHT to it.
It crashed immediately with **zero journal output** — a hard machine crash
from accessing d11 core registers while d11 was in BCMA reset.

**Root cause of test.113 crash:**
`brcmf_chip_set_passive` runs BEFORE `ops->reset` (in chip.c:1040-1048).
`brcmf_chip_cr4_set_passive` calls `brcmf_chip_coredisable` on d11 (not
`resetcore`), leaving d11 in BCMA reset. Then ops->reset runs test.113.
`brcmf_pcie_select_core(BCMA_CORE_80211)` + `read_reg32(0x1e0)` accesses
d11's core AXI slave while it's non-responsive → PCIe SLVERR → crash.

**Root cause of FW hang (still the same):**
`brcmf_chip_cr4_set_passive` also leaves d11 in BCMA reset at ARM release.
FW polls d11.clk_ctl_st (0x180011e0) for BP_ON_HT → AXI SLVERR → data
abort → FW hang. This is the hang at fn 0x1415c seen in test.106.

**Fix (test.114):**
- test.114a (`brcmf_pcie_reset_device`): replaced unsafe core register read
  with wrapper-only read (BAR0+0x1800 = d11_wrapbase+BCMA_RESET_CTL, always
  safe regardless of BCMA reset state).
- test.114b (`brcmf_pcie_load_firmware`, before skip_arm check):
  call `brcmf_chip_resetcore(d11core, 0x000c, 0x0004, 0x0004)` to take d11
  out of BCMA reset. Verify via wrapper RESET_CTL before/after. Read
  d11.clk_ctl_st safely after reset cleared.
  Runs with BOTH skip_arm=1 (diagnostic) and skip_arm=0 (full ARM release).

**Expected results:**
- test.114a: `wrap_RESET_CTL=0x00000001 IN_RESET=YES` (d11 in reset during ops->reset) ✓
- test.114b pre: `wrap_RESET_CTL=0x00000001 IN_RESET=YES` (still in reset before resetcore)
- test.114b post: `wrap_RESET_CTL=0x00000000 IN_RESET=NO` (reset cleared) ← key discriminator
- test.114b d11 clk_ctl_st: with skip_arm=1, BBPLL not up → BP_ON_HT may be NO
  With skip_arm=0 + test.47 BBPLL bringup, expect BP_ON_HT=YES

**Plan:**
1. Run with skip_arm=1 first → confirm no crash, verify wrapper reads
2. If clean: run with skip_arm=0 → test.47 brings BBPLL up, d11 out of
   reset, ARM released → FW should see BP_ON_HT and proceed past fn 0x1415c

**Build:** clean, `brcmfmac.ko` rebuilt (commit 63ee5fc).

**Test script:** `test-staged-reset.sh` — update LOG_NAME to `test.114`.

**Risk:** medium. `brcmf_chip_resetcore` on d11 is the same operation
`brcmf_chip_cm3_set_passive` does for other chips. Safe with skip_arm=1
(ARM never released). Wrapper register reads are always safe.

**Workflow:** commit + push before insmod (already done).

---

## Previous state (2026-04-17, POST test.111 + offline research — HANG REG IDENTIFIED)

**COMPLETE CHAIN OF EVIDENCE:**
- test.106: FW's fn 0x1415c hangs polling MMIO at `0x180011e0`.
- test.111: `0x18001000` = `BCMA_CORE_80211` (d11 MAC core), rev 42.
- brcmsmac/d11.h:168 `u32 clk_ctl_st; /* 0x1e0 */` — offset 0x1e0 in the
  d11 MAC core is the **per-core clock control/status register**.
- brcmsmac/aiutils.h:55-66:
  - `CCS_FORCEHT     = 0x00000002` (WRITE: force HT clock request)
  - `CCS_BP_ON_HT    = 0x00080000` (RO:    backplane running on HT clock)

**The hang, fully explained:** FW writes `CCS_FORCEHT` to d11's
clk_ctl_st, then spin-polls waiting for `CCS_BP_ON_HT`. On BCM4360 the
BBPLL is off post-EFI (test.40: HAVEHT=0, HAVEALP=1), and `brcm80211`'s
bcma backend has no PMU resource config for chip `0x43A0` ("PMU resource
config unknown or not needed for 0x43A0"). Result: HT clock never comes
up → `CCS_BP_ON_HT` never sets → FW poll runs forever at fn 0x1415c.

**Core map (for reference):**

| id    | name       | base        | rev |
|-------|------------|-------------|-----|
| 0x800 | CHIPCOMMON | 0x18000000  | 43  |
| 0x812 | 80211      | 0x18001000  | 42  | ← hang is at +0x1e0 = clk_ctl_st |
| 0x83e | ARM_CR4    | 0x18002000  | 2   |
| 0x83c | PCIE2      | 0x18003000  | 1   |

**This closes Phase 5.** Root cause of FW hang is definitively isolated
to "BBPLL/HT clock absent when FW runs."

**Phase 6 direction — bring up BBPLL/HT before releasing ARM:**
Options, roughly easiest → hardest:
1. **Host-side force HT via ChipCommon.clk_ctl_st:** write `CCS_FORCEHT`
   (bit 1) to CC before ARM release, wait for `CCS_BP_ON_HT` (bit 19).
   This is what brcmsmac does on similar chips (see main.c:1230-1240).
2. **Host-side PMU resource/pllcontrol programming:** program pllcontrol[0..5]
   and min/max_res_mask to match known-good EFI state, trigger BBPLL
   start. Requires pllcontrol register-map for BCM4360 rev-3.
3. **FW patching:** skip the poll loop at fn 0x1415c (hardest; still
   doesn't fix the underlying clock problem).

**Recommended next test: test.112 — host writes CCS_FORCEHT to CC and
polls CCS_BP_ON_HT.** Read-only pollers (a few reads on CC), no new
state mutation past the single force write. Observe whether BBPLL comes
up with the simple force-write alone.

**Workflow:** test.112 touches HW (a single CC write + polls) — RESUME
plan + commit + push before insmod.

---

## Test.111 raw result (2026-04-17 18:47, POST — FW HANG TARGET IDENTIFIED)

**`0x18001000` = `BCMA_CORE_80211` (d11 MAC core), rev 42.**

Full BCM4360 backplane core map (from driver's own enumeration,
`phase5/logs/test.111.stage0`):

| id    | name       | base        | rev |
|-------|------------|-------------|-----|
| 0x800 | CHIPCOMMON | 0x18000000  | 43  |
| 0x812 | 80211      | 0x18001000  | 42  | ← **FW HANG TARGET** |
| 0x83e | ARM_CR4    | 0x18002000  | 2   |
| 0x83c | PCIE2      | 0x18003000  | 1   |

Missing (not present): INTERNAL_MEM, PMU, ARM_CM3, GCI, DEFAULT.

**Interpretation:** the FW's `fn 0x1415c` (per test.106) reads register
`0x180011e0` — that's the d11 MAC core at offset `0x1e0`. The
80211/d11 core has a register bank starting at its base; `0x1e0` is a
well-known register range in brcm80211 — typically
`D11_MACCONTROL`/`MACCONTROL1`/`MACINTSTATUS` depending on rev. Need to
cross-reference with brcmsmac or brcm80211 headers for rev-42 d11.

**Run behaviour:** insmod rc=0 (not -ENODEV). skip_arm branch lives
inside `brcmf_pcie_download_fw_nvram`, but probe's firmware files are
missing (Apple-branded `.bin`, `clm_blob`, `txcap_blob` all load with
`-ENOENT`), so `copy_mem_todev` never runs and the probe returns a
clean 0 from the fw-request callback path. Host did NOT crash. dmesg
captured everything cleanly.

**Next direction — resolve what d11 register 0x1e0 is:**
1. Grep brcmsmac + brcm80211 sources for d11 MAC register headers
   (`d11.h`, `d11ucode.h`, etc.) and find the name/semantics of offset
   0x1e0.
2. Likely candidates on rev-42 d11: MACINTSTATUS (status poll),
   MACCONTROL (MAC enable latch), PHY_VERSION, PMU/clock status mirror.
3. The FW read at 0x1e0 is a spin loop (test.106 established a poll
   loop at fn 0x1415c). So it's waiting for a bit to set — likely a
   PHY or MAC-ready indication that never asserts because BBPLL/HT
   clock is off (PMU/pllcontrol evidence from test.40/109).

**Secondary line:** BBPLL/HT initialization — even if we identify
register 0x1e0 semantics, the root cause is probably still
"BBPLL isn't running so d11 can't produce the status bit FW is waiting
for." The d11 core requires HT clock. Test.40 already established
`HAVEALP=1 HAVEHT=0` after watchdog. We'd need to either (a) bring up
BBPLL before ARM release, or (b) patch FW to skip this specific poll.

**Workflow:** next step is offline research (grep d11 headers) — no HW
touch, no insmod.

---

## Previous state (2026-04-17, PRE test.111 — module built, about to run)

**Goal (unchanged):** identify the core at backplane slot 0x18001000 (the
FW-hang target from test.106: FW reads *0x180011e0 and never returns).

**test.110 outcome: BOX CRASHED HARD, ZERO KERNEL LOGS PERSISTED.**
- `phase5/logs/test.110.stage0` stops at the `=== Loading brcmfmac ===`
  header — no `insmod returned` line, no dmesg capture → insmod itself
  never returned, the script was never resumed.
- `journalctl -b -1 -k | grep BCM4360` → empty. Boot -1 (18:21:57 →
  18:34:49) persisted nothing for brcmfmac. Faster crash than test.109
  which at least got EFI/PMU/pllcontrol lines through to the journal.
- System rebooted into boot 0 at 18:35:22 cleanly.
- `.git.broken/` is a stale .git backup from 2026-04-17 16:14 (Pre-test.105
  COMMIT_EDITMSG inside); unrelated to test.110. Leave it alone for now.

**Diagnosis (advisor-informed):** the 11-slot BAR0-remap loop added to
`brcmf_pcie_reset_device` (pcie.c:762-801) either crashed synchronously on
entry, or triggered a PCIe completer error so severe journald could not
flush. Root cause is raw BAR0 sweeping during buscore_reset — unsafe.

**Pivot for test.111: use the driver's already-enumerated cores list.**
`brcmf_chip_recognition()` runs BEFORE `ops->reset` (see chip.c:1043-1049),
so by the time `brcmf_pcie_reset_device` executes via callsite 3244, the
chip's core list is fully populated. Public API
`brcmf_chip_get_core(ci, coreid)` returns each core with its `id`, `base`,
`rev` — NO MMIO, NO hang risk. This is exactly the data we need.

**Code change plan (pcie.c):**
- REPLACE the BAR0 11-slot sweep block (762-801) with a lookup over known
  core IDs: CHIPCOMMON, PCIE2, 80211, ARM_CR4, ARM_CM3, PMU, GCI, SOCRAM,
  DEFAULT (plus any others we know about). For each, `dev_emerg` log
  `id=0x%03x base=0x%08x rev=%u` OR `not present`.
- FLAG any core whose `base == 0x18001000` (FW-hang target).
- Keep `dev_emerg` (guaranteed flush, highest priority).
- `bcm4360_skip_arm=1` retained as safety (avoids FW hang after enum).

**Expected outcome:** probe prints the core list via dev_emerg, then
either skip_arm returns cleanly (clean log), or probe continues and wedges
at copy_mem_todev like test.109 (still have enum data in journal).

**Hypothesis:** slot 0x18001000 is likely `BCMA_CORE_80211` (d11 MAC),
based on chip.c:1022 which registers BCMA_CORE_80211 at 0x18001000 under
the SOCI_SB branch. If BCM4360 is SOCI_AI (EROM scan), actual layout comes
from EROM and could differ — we'll see in the log.

**Build status:** clean. `brcmfmac.ko` rebuilt at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/`. Only
pre-existing `brcmf_pcie_write_ram32 unused` warning (unrelated).

**Test script:** `phase5/work/test-staged-reset.sh` updated:
- LOG → `test.111.stage${STAGE}`
- banners/stage header reworded for test.111
- insmod args unchanged (`bcm4360_reset_stage=0 bcm4360_skip_arm=1`)

**Expected stage0 log:**
- Pre-test PCIe/root-port state (lspci)
- Loading banner
- insmod rc (likely 0 now — with cores populated skip_arm branch returns
  after TCM dump, but behaviour depends on exact path)
- dmesg BCM4360 lines including: EFI/PMU/pllcontrol + NEW 9 "test.111:
  id=0x... name=... base=0x... rev=..." lines + "core enum complete"
- Cleaning up brcmfmac

**Success criterion:** identify which core (if any) has `base=0x18001000`
— this is the FW-hang target from test.106. Hypothesis: BCMA_CORE_80211.

**Workflow:** this run touches HW — commit + push before insmod.

---

## Previous state (2026-04-17, PRE test.109 — module built, about to run)

**Goal:** capture the pre-ARM backplane core enumeration (11 slots from
0x18000000 to 0x1800A000) without crashing the host. Identifies what
core lives at slot 0x18001000 (FW-hang target per test.106).

**Why this run differs from test.107/108 (both lost all enum output):**
1. **Enum block moved** from pcie.c:~2305 (after skip_arm check) to
   pcie.c:~1889 (BEFORE skip_arm check). Now reachable in both paths.
2. **bcm4360_skip_arm=1** passed to insmod. Probe does test.101 baseline
   + the new enum + a 64B TCM dump, then returns -ENODEV cleanly.
   **No ARM release → no FW hang → no PCIe wedge → no crash.**
3. **dmesg -k --nopager** replaces journalctl in the capture step. Reads
   /dev/kmsg directly, no journald batching.
4. **No sleep in capture** — skip_arm=1 means no crash race; we can take
   as long as we want. dmesg runs synchronously post-insmod.
5. **rmmod after capture** so next run is repeatable.

**Files changed (post test.108):**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  - NEW test.109 enum block at ~line 1889 (after test.101 baseline,
    before `if (bcm4360_skip_arm)`). All logs are dev_emerg.
  - OLD test.108 enum block at ~line 2305 replaced with a short
    breadcrumb comment pointing to the new location.
- `phase5/work/test-staged-reset.sh`:
  - LOG → test.109.stageN, headers updated.
  - insmod invocation adds `bcm4360_skip_arm=1`.
  - insmod wrapped in set+e/set-e (expected non-zero rc from skip_arm).
  - Post-insmod capture uses `dmesg -k --nopager | grep BCM4360`
    instead of `sleep 2 + journalctl | grep`.
  - rmmod at end for repeatability.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected output:** `phase5/logs/test.109.stage0` contains:
- Pre-test PCIe state (lspci)
- Loading banner
- insmod rc=non-zero message
- BCM4360 kernel lines up through test.109 slot enum (11 lines)
- "Cleaning up brcmfmac..." from rmmod

**Decision tree:**
- All 11 slot reads logged → core map obtained; identify slot 0x18001000
  ID and cross-reference to EROM/datasheet.
- Script prints the loading banner but NO BCM4360 enum lines AND box
  crashes → slot+0 reads themselves are unsafe pre-ARM (previously
  unsuspected). Next step: try an even earlier probe with fewer reads.
- Script runs to completion but slot 0x18001000 off0=0xffffffff → slot is
  DEAD pre-ARM (no core present or unpowered). Implication: FW accesses
  a non-existent core → hang. Next step: try to identify the core via
  EROM walk or find evidence FW expects a different slot.
- Script runs but slot 0x18001000 off0=live non-ff value → core exists,
  is responsive to host-side MMIO. FW hang is specifically on 0x1e0
  register read. Next step: compare with neighbour cores' 0x1e0 value.

**Workflow:** this run touches HW — commit + push before insmod.

---

## Previous state (2026-04-17, POST test.108 — CRASHED AGAIN, plan pivots to skip_arm + dmesg)

**Outcome:** journal recovery from boot -1 shows only 27 BCM4360 lines,
last is `test.101 pre-ARM baseline: *0x62e20=0x00000000 ZERO (expected)`.
**NO test.108 enum output.** Stage0 script log got to header
`=== Post-insmod journal capture (boot 0) ===` then stopped — crash hit
during the `sleep 2 + journalctl | tee` capture window, wiping the
kernel ringbuffer before it reached persistent storage.

**Root cause (confirmed):** insmod with bcm4360_reset_stage=0 and no
skip_arm does a full ARM release → FW hangs on 0x180011e0 → PCIe root
port wedges → box hard-locks within ~1-2s of insmod returning.
Script-side `sleep 2 + journalctl | tee` loses the race.

**Pivot: new approach for test.109.** Stop depending on post-insmod
journal recovery. Instead:
1. **Skip ARM release via `bcm4360_skip_arm=1`.** The existing branch
   at pcie.c:1890-1919 returns -ENODEV cleanly without releasing ARM,
   so there's no FW hang, no root-port wedge, no crash. This path was
   last exercised in test.16 (commit d595029, 2026-04-14) — rot risk
   minimal (trivial reads + return -ENODEV).
2. **Move test.108 enum block from its current site (line 2305, AFTER
   the skip_arm branch, thus unreachable when skip_arm=1) to right
   after test.101 baseline (~line 1889).** This puts enum in the path
   for BOTH skip_arm=1 AND skip_arm=0.
3. **Replace journalctl capture with `dmesg -k --nopager`** in
   test-staged-reset.sh. dmesg reads /dev/kmsg directly — no journald
   batching, faster. With skip_arm=1 we also have unlimited time since
   no crash expected.

**Risk analysis:**
- If slot+0 reads on a dead slot DO crash the box (not just slot+0x1e0),
  we'll learn that with skip_arm=1 = no ARM release path → crash source
  is narrowed to the specific slot read.
- skip_arm branch does a TCM dump (64B) then returns. Should be safe.

**Next file edits planned:**
- `pcie.c`: move test.108 enum block (2278-2328) to line ~1889, renumber to test.109
- `test-staged-reset.sh`: LOG → test.109, pass `bcm4360_skip_arm=1`, switch capture to dmesg

---

## Previous state (2026-04-17, PRE test.108 — module built, about to run)

**Goal:** same as test.107 — identify what core lives at slot 0x18001000
and whether it's MMIO-responsive host-side while ARM is stuck. This time
with a probe that (a) won't crash the host bus pre-ARM, and (b) captures
its own log before any later crash can wipe it.

**Changes vs test.107:**
1. **Pre-ARM enum reads slot+0 only.** Dropped the slot+0x1e0 read —
   for slot 0x18001000 that targets 0x180011e0, the exact register FW
   hangs on. Host read of a hung backplane reg can stall root-port
   completions and kill the box before dev_emerg flushes. Presence probe
   via slot+0 is enough to answer "is a core there".
2. **FW-wait probe of 0x180011e0 preserved** inside the outer==1 branch
   with T106_REMASK (MAbort masking active). If this probe hangs, we
   survive thanks to re-mask.
3. **test-staged-reset.sh captures `journalctl -b 0 | grep BCM4360`
   into the stage0 log immediately after insmod.** Survives the later
   ~30s crash pattern. Adds `sleep 2 + sync` around the capture.

**Expected output per slot (from EROM knowledge):**
Slot numbers vs core types are unknown pre-run — the whole point of the
enum. Reading slot+0 on a dead slot returns 0xffffffff (master-abort).
On a live core it typically returns some structured ID/config word.

**Files changed:**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  pre-ARM enum no longer reads 0x1e0; renamed test.107→test.108 header
  and slot lines; FW-wait 0x180011e0 probe unchanged (keeps test.107 tag).
- `phase5/work/test-staged-reset.sh`: LOG path → test.108; added
  post-insmod journal capture block with sync + sleep + tee.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected log capture:** stage0 log should contain full dmesg in-line
(new capture block). If box crashes before sync, recover via
`journalctl -b -1 | grep -iE "BCM4360|brcmfmac" > phase5/logs/test.108.journal`
after reboot.

---

## Previous state (2026-04-17, POST test.107 — CRASHED EARLY, zero enum data)

**Outcome:** host crashed during or shortly after the pre-ARM test.107
block. Recovered journal (`phase5/logs/test.107.journal`) captured only 4
BCM4360 kernel lines:
- SBR via bridge 0000:00:1c.2
- SBR complete — bridge_ctrl restored
- BAR0/BAR2/tcm debug line
- test.53 BAR0 probe alive = 0x15034360

**NO test.107 enumeration output** (no "slot[0x...]" lines). **NO test.96
pre-ARM baseline** either — the crash beat the next batch of dev_info
calls to console. Session closed 17:59:45 (same second as the load).

**Hypothesis:** the pre-ARM enumeration loop reads `ioread32(regs + 0x1e0)`
for every slot. For slot 0x18001000 that targets `0x180011e0` — the exact
register the FW hangs on (test.106). Host-side read of an unresponsive
backplane register likely triggered a PCIe completion timeout that hung
the root port / bridge, killing the box before the next dev_emerg flushed.

**Next step (test.108): safer probe.**
- Pre-ARM enum reads **slot+0 only** (canonical first register; safe, just
  a presence probe). Skip slot+0x1e0 entirely pre-ARM.
- Defer the `0x180011e0` read to the existing FW-wait `outer==1` branch,
  where MAbort masking + re-mask every 10ms is already active (that's the
  regime the other test.106/107 probes survived in).
- If a pre-ARM read of slot+0 also crashes the box, we'll know that one
  read ≠ one write matters and we need a completely different strategy
  (e.g., use the EROM walk in si_attach to read core IDs indirectly).

---

## Previous state (2026-04-17, PRE test.107 — module built, about to run)

**Goal:** identify what core lives at backplane slot `0x18001000` (where fn
0x1415c's first MMIO read hangs) and whether that core is MMIO-responsive
from the host side while the ARM is stuck.

**Probe design (all READ-ONLY, no backplane writes):**

1. **Pre-ARM enumeration (11 slots):** loop `N = 0..10`, point BAR0 window
   at `0x18000000 + N*0x1000`, read offset 0 + offset 0x1e0 at each. Logs
   11 lines in stage-0 dmesg. Slot 0x18001000 is the FW-hang target.
2. **T+200ms hang-target probe:** during the existing FW-wait outer==1
   window, redirect BAR0 to `0x18001000`, read offset `0x1e0`, restore
   window to CC. One additional read. Compares host-side result to
   FW-side hang state.

**Files changed:**
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:
  inserted test.107 block after the pre-ARM `brcmf_pcie_select_core(CC)`
  (before ARM release) and a hang-target probe in the existing
  outer==1 branch.
- `phase5/work/test-staged-reset.sh`: LOG path + header → test.107.

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Expected log capture:** host crashes ~30s post-exit (pattern from t.101-106).
If stage0 log missing, recover via
`journalctl -b -1 | grep BCM4360 > phase5/logs/test.107.stage0`
after reboot.

---

## Previous state (2026-04-17, POST test.106 — PROLOGUE-HANG CONFIRMED)

**HEADLINE RESULT:** fn 0x1415c hangs on its first MMIO read (ldr.w at
0x14176). Target register = **0x180011e0** = backplane core slot #1 base
0x18001000 + offset 0x1e0. No sub-BL ever executes.

**Evidence (test.106, all 3 time samples identical):**
- T3@0200ms/0600ms/1000ms [0x9CEC4] = **0x00091cc4** (NOT LR-shaped)
- T1[0x9CED4] = 0x00068321 (fn 0x1415c saved LR — frame live)
- STRUCT_PTR[0x9CEC8] = 0x00091cc4 (TCM-shaped, valid struct ptr)
- MMIO_BASE[struct+0x88] = **0x18001000** (read BEFORE the hang)
- Anchors E/F stable at 0x67705 / 0x68b95
- Counter frozen at 0x43b1 throughout the 1.2s wait
- *0x62e20 = 0 (FW never wrote it — consistent with early hang)

**Interpretation:** the MMIO_BASE read (at offset 0x88 of struct) completed
successfully, so the struct is reachable. The HANG is on the *next* MMIO —
the ldr.w at 0x14176 reading `[r3, #0x1e0]` where r3=0x18001000. The ARM
stalls indefinitely because core 0x18001000 is either: (a) held in reset,
(b) not clocked, (c) not powered, or (d) not present on this chip variant
and no bus-error acceptor exists.

**Next phase — identify the core at 0x18001000 (NO HW COST):**
1. **EROM walk (disasm, subagent):** traverse EROM starting at some
   known-good core to enumerate cores + their backplane addresses on
   BCM4360. Need to find which core ID is at slot 0x18001000.
2. **Cross-ref with test.96 log:** "PCIe2 core id=0x83c rev=1" — we don't
   yet know its wrapper vs regset addresses. Possible that 0x18001000 is
   the PCIe2 core *from the ARM side* (different address than PCIe2 host-
   side BAR). Verify from disasm of `si_setcore` / EROM walker.
3. **FW disasm at fn 0x6820c's r0 setup:** the struct at 0x91cc4 with +0x88
   pointing to a core base looks like a `si_info` or core-handle structure.
   Find where it's populated — that will tell us the expected core type.

**Planned HW test (post-disasm):** if we identify the core, try (a)
holding it in reset via CC→resetcore before ARM release, or (b) forcing
its clock gate on, or (c) setting up a "fake" presence bit in SROM/OTP to
make FW skip the init path.

**Workflow rule:** commit + push RESUME_NOTES before editing pcie.c or
running any new test (host crashes ~30s post-exit; pre-commit preserves
state).

---

## Previous state (2026-04-17, PRE test.106 — test executed successfully)

**Goal:** discriminate **prologue-hang at fn 0x1415c's ldr.w 0x14176**
(first MMIO touch of `[[r0+0x88]+0x1e0]`) vs **poll-hang inside fn 0x1adc**
(called from fn 0x1415c's bit-17 poll loop).

**Discriminator:** sample T3 [0x9CEC4] at 3 time points (T+200ms, T+600ms,
T+1000ms). If any sample catches fn 0x1adc active, we'll see LR=0x1418f or
0x14187. If T3 stays non-LR-shaped across all 3 samples, prologue-hang is
confirmed.

**Disasm findings (subagent, 2026-04-17):**
- `phase5/notes/offline_disasm_6820c_r0_setup.md`: fn 0x6820c never spills
  r0 — struct pointer is held live in its callee-saved r4. When fn 0x1415c's
  prologue `push {r4,r5,r6,lr}` runs, it saves caller-r4 at its body_SP.
  So **[0x9CEC8] IS the struct pointer**. [struct+0x88] is the MMIO base.
- `phase5/notes/offline_disasm_15940_prologue.md`: fn 0x15940 pushes
  {r4..r8,lr} (N=6), body_SP=0x9CEC0, saved-LR slot=0x9CED4. If it were
  active, [0x9CED4]=0x6832b, not 0x68321. **T1=0x68321 still proves fn
  0x1415c is active.**

**Probe reads (14 total):**
- T+200ms (outer==1, 12 reads): ctr[0x9d000], pd[0x62a14], anc_E[0x9CFCC],
  anc_F[0x9CF6C], T1[0x9CED4], T3@200[0x9CEC4], struct_ptr[0x9CEC8],
  mmio_base[struct+0x88] (conditional on TCM-shaped struct_ptr), sweep
  [0x9CEC0]/[0x9CEBC]/[0x9CEB8], sanity *0x62e20
- T+600ms (outer==3, 1 read): T3@600[0x9CEC4]
- T+1000ms (outer==5, 1 read): T3@1000[0x9CEC4]

**Build:** clean. Module at
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

**Test script:** `phase5/work/test-brcmfmac.sh` (requires sudo).

**Expected log capture:** host crashes ~30s post-exit (pattern from t.101-105).
If stage0 log missing, recover via `journalctl -b -1 | grep BCM4360 >
phase5/logs/test.106.stage0` after reboot.

**Decision tree for test.106 results:**
- All 3 T3 samples non-LR-shaped → **prologue-hang CONFIRMED**; next test:
  inject a new probe before fn 0x1415c is reached (earlier callsite) OR
  look at the struct pointer value to identify the HW block. If MMIO base
  is a known PHY/PMU core register range, we can try holding that core in
  reset before ARM release.
- Any T3 sample == 0x1418f or 0x14187 → **poll-hang CONFIRMED** (fn 0x1adc
  delay inside poll loop or pre-loop). Next test: intercept at the poll
  itself, look at counter r6 saved at [0x9CED0] for progress.
- T1 changed → frame shifted, different analysis needed (unlikely given 5
  consecutive tests with T1 stable).

## Historical state (2026-04-17, POST test.105 — initial interpretation, now superseded)

Git branch: main. **Session recovery note:** prior session crashed during/after
test.105 run (16:14); .git had 15+ empty objects (refs/heads/main included).
Working tree was intact. Recovered by re-cloning from origin (which matched
the pre-crash HEAD 0ffaaf3). Broken .git preserved as `.git.broken/`. Working
tree backup at `/tmp/bcm4360-salvage/`. Git fully healthy now.

Test.105 captured from `journalctl -b -1` → `phase5/logs/test.105.stage0`
(63 lines, complete through 2s FW-silent timeout exit). Host crashed ~30s
after test clean exit, same post-exit pattern as t.101-104.

### TEST.105 RESULT — fn 0x1adc already returned

Raw probe output:
```
test.105 T+0200ms: ctr[0x9d000]=0x000043b1 pd[0x62a14]=0x00058cf0
test.105 ANCH  E[0x9CFCC]=0x00067705 F[0x9CF6C]=0x00068b95 (MATCH E=1 F=1)
test.105 T1[0x9CED4]=0x00068321 MATCH stable (fn 0x1415c saved LR)
test.105 T3[0x9CEC4]=0x00091cc4 NOT LR-shaped → fn 0x1adc already returned
test.105 SWEEP 0x9CEC0↓: 00000000 00068d2f 00091cc4 00092440
test.105 SWEEP LR-CAND [0x9cebc]=0x00068d2f
test.105 T+0200ms: SANITY *0x62e20=0x00000000
```

**Interpretation (per PLAN decision table):**
- Regression + anchors E/F stable — same hang site as t.101/102/103/104.
- T1 stable at 0x68321 — fn 0x1415c confirmed active (body SP still 0x9CED8).
- T3=0x91cc4 is **NOT LR-shaped** (not Thumb-odd, not in code range).
  Per plan, this rules out: bit-17 poll loop (0x1418f), pre-loop delay
  (0x14187), and poll-timeout/assert (0x141b7).
- **Decision: fn 0x1adc has already returned. Hang is elsewhere in fn 0x1415c's
  body, AFTER the BL to fn 0x1adc.**
- 0x91cc4 at 0x9CEC4 is stale (appears again at 0x9CEB8, and 0x68d2f at
  0x9CEBC is the same t.104-era fn 0x68cd2 leftover — body SP of whatever
  is currently running sits above 0x9CEC4).
- Sanity *0x62e20 still 0x00000000 — FW never wrote that word.

### Refined hypothesis (advisor insight, 2026-04-17)

**The absence of any LR-shaped value at [0x9CEC4] across t.101–105 is the signal,
not noise.** If fn 0x1415c had ever called any of its sub-BLs (0x1adc ×3 or
0x11e8) and returned, [0x9CEC4] would hold an LR-shaped value (0x14187,
0x1418f, or 0x141b7) as stale pop-didn't-clear. It doesn't — 0x91cc4 is
pre-fn-0x1415c stack garbage, meaning **fn 0x1415c has not called any sub-BL
yet**.

Combined with T1 [0x9CED4]=0x68321 (fn 0x1415c still the active frame of
fn 0x6820c), the hang is in fn 0x1415c's prologue, BEFORE 0x14182 (first BL
to 0x1adc).

**Prime candidate: ldr.w at 0x14176** — `ldr.w r2, [r3, #0x1e0]` — the first
MMIO touch of the status register `[r3+0x1e0]` (same register the later poll
would read). If this register's bus access stalls, CPU is frozen on this load.
(Write-back at 0x1417e is also possible if the read completes but the store
stalls.)

### Test.106 plan — discriminate prologue-hang vs poll-hang

**Primary discriminator: time-evolve T3.** Sample [0x9CEC4] at 3 time points
across the FW-wait (e.g. T+200ms, T+600ms, T+1000ms). If fn 0x1415c were
actually in the poll loop, we'd *occasionally* catch fn 0x1adc active and see
0x1418f (stochastic over many iterations × many time-samples). If T3 stays
0x91cc4 across all samples, prologue-hang is confirmed.

**Probe reads (≤ 14 total):**
1. Regression: ctr[0x9d000], pd[0x62a14] — continuity
2. Anchors: E[0x9CFCC] (exp 0x67705), F[0x9CF6C] (exp 0x68b95),
   T1[0x9CED4] (exp 0x68321) — chain stability
3. T3 × 3 times: [0x9CEC4] at T+200ms, T+600ms, T+1000ms — key discriminator
4. Struct pointer: [0x9CEC8] (saved r4 = r0 on entry = struct pointer). This
   tells us which HW block fn 0x1415c is touching.
5. Sweep 0x9CEC0 ↓ 0x9CEB8 — pre-call stack garbage context (not written
   by fn 0x1415c if hypothesis holds)
6. Sanity *0x62e20

**Pre-test disasm tasks (subagent, no HW cost):**
- **fn 0x6820c around 0x6831c:** find instructions that set r0 before
  `bl #0x1415c`. Tells us the expected struct pointer value → we can
  compute the actual MMIO register address [r0+0x88]+0x1e0 being hit.
- **fn 0x15940 prologue:** verify push count. If fn 0x15940 pushes exactly
  3 regs (rare), its body SP would land ABOVE 0x9CED4 and T1 would not be
  overwritten by a call to fn 0x15940 — in which case T1 stable doesn't
  prove fn 0x1415c is still active. (Expected: push includes LR + ≥2 regs
  so body SP ≤ 0x9CECC, T1 anchor is live.)

**Workflow rule:** commit + push RESUME_NOTES before editing pcie.c or
running test.106 (host crashes ~30s post-exit; pre-commit preserves state).

---

## Previous state (2026-04-17, PRE test.105 — module built, about to run)

**TEST.105 PLAN** (verified against raw firmware bytes, see pcie.c @ if (outer==1) block):
- Disasm source: `phase5/notes/offline_disasm_1415c.md` + prologue of fn 0x1adc
  manually verified (0xb538 = push {r3,r4,r5,lr}).
- Frame math: fn 0x1415c body_SP=0x9CEC8, fn 0x1adc body_SP=0x9CEB8, saved LR
  of fn 0x1adc at 0x9CEC4.
- **Key reading: T3 [0x9CEC4]** decides the hang state:
  - `0x1418f` → parked in fn 0x1adc from the bit-17 POLL LOOP (most likely)
  - `0x14187` → parked in fn 0x1adc from the pre-loop `delay(0x40)` call
  - `0x141b7` → poll TIMED OUT → hung inside fn 0x11e8 (assert/svc)
  - not LR-shaped → fn 0x1adc already returned, hang elsewhere in fn 0x1415c body
- 12 reads total (well under the safe 19-budget), 1200ms FW-wait, T104_REMASK
  equivalent macro throughout.
- **RESULT: T3 = 0x91cc4, NOT LR-shaped → fn 0x1adc returned. See POST section above.**

---

## Previous state (2026-04-17, POST test.104 — HANG LOCALIZED to fn 0x1415c)

Git branch: main. Host had a hard crash after test.104 ran (at 11:49); the
probe output was captured via `journalctl -b -1` and saved to
`phase5/logs/test.104.stage0`. Test.104 ran **twice** (boots -1 and -2), both
identical — result is deterministic.

### TEST.104 RESULT — CASE 1 (known-safe): T1 LR-shaped, maps to `bl 0x1415c`

**Raw output (identical both runs):**
```
test.104 T+0200ms: ctr[0x9d000]=0x000043b1 pd[0x62a14]=0x00058cf0
test.104 ANCH E[0x9CFCC]=0x00067705 F[0x9CF6C]=0x00068b95 (MATCH E=1 F=1)
test.104 T1[0x9CED4]=0x00068321 — LR-shaped → different sub-BL of fn 0x6820c
test.104 T2[0x9CEBC]=0x00068d2f — MATCH fn 0x68cd2 sub-BL candidate (STALE, see below)
test.104 SWEEP 0x9CEB8↓: 00091cc4 00092440 00093610 00000000 0009cf44 00012c69
test.104 SWEEP LR-CAND [0x9cea4]=0x00012c69
test.104 T+0200ms: SANITY *0x62e20=0x00000000
```

**Interpretation:**
- Regression + anchors E/F stable (= same hang site as t.101/102/103).
- **T1=0x68321 maps to BL row 14 in `offline_disasm_6820c.md`: `bl 0x1415c at
  0x6831c` → LR=0x68321.** CPU is inside fn 0x1415c, the 14th sub-BL of
  fn 0x6820c's body (not fn 0x68cd2 — that returned successfully).
- T2=0x68d2f at 0x9CEBC is **stale** — fn 0x68cd2 (at 0x68258) ran, pushed
  this LR on its descent, then returned. Its stack area is below fn 0x6820c's
  current body SP (0x9CED8) and 0x9CEBC holds unreclaimed data.
- Sweep values (0x91cc4, 0x92440, 0x93610, 0, 0x9cf44, 0x12c69) are mostly
  out-of-code-range; 0x12c69 is in range and odd (points ~0x12c68 in code),
  but sits OUTSIDE fn 0x1415c's body (0x1415c..). It's either a deeper-frame
  saved LR (fn 0x1415c → X → something-at-0x12c68), or stale. Do NOT anchor
  test.105 on 0x12c69 — treat as informational only.

**Free frame-size bound from T2 staleness:** 0x68d2f surviving at 0x9CEBC
means fn 0x1415c's live frame does NOT extend down past 0x9CEC0. So:
- fn 0x1415c body SP ≥ 0x9CEC0 ⇒ push_bytes + sub_sp ≤ 24 B
- LR-slot at [0x9CED0] (top of push block); pushed regs ≤ 6
If disasm reports a larger frame, something is inconsistent — verify.

**Falsified hypotheses (from 6820c disasm executive summary):**
- ★ fn 0x68cd2 is NOT the hang site (ruled out by T1 value)
- ★ fn 0x67f44 at 0x68308 is also past (LR would be 0x6830d, not 0x68321)

**New primary target: fn 0x1415c** — described in disasm as "HW init (unknown
target)". Not yet traced. Needs offline disasm to understand what it does
and to find breadcrumb / frame-size info for test.105.

### Next steps (test.105)

1. **Offline disasm fn 0x1415c** (subagent, no HW cost):
   - prologue → frame size
   - BL list → LR-candidate table for its sub-BLs
   - any polling loops / fixed-TCM writes
2. **Test.105 probe plan:**
   - 2 regression reads (ctr, pd) — continuity
   - 2 anchor reads (E, F) — chain stable
   - 1 read @ 0x9CED4 (T1 anchor, confirm still 0x68321)
   - Saved-LR slot of fn 0x1415c's current sub-BL (computed from its
     frame size; likely 0x9CED0 - frame_size)
   - Short sweep below that slot for deeper frames
   - 1 sanity `*0x62e20`
3. **Note:** the saved-LR slot for fn 0x1415c's current sub-BL = 0x9CED0
   (fn 0x1415c's body SP) - 4. Requires fn 0x1415c's prologue push count to
   compute exactly. Placeholder until disasm: probe 0x9CED0..0x9CEB8 densely.

### POST-EXIT CRASH PATTERN (observed in t.101/102/103/104)

Each test exits cleanly after its FW-silent timeout (2s). Approximately 30s
later, the host crashes / reboots. This is **unrelated to the probe itself**
— test completes and logs are written before the crash. Recovery:
`journalctl -b -1` on next boot gives full dmesg from the previous session.
Workflow rule: commit + push before running.

---

## Previous state (2026-04-17, PRE test.104 — module built)

### TEST.104 PLAN — zoom in on fn 0x6820c sub-frame

**Frame math (primary-source verified from firmware hex + disasm):**
- fn 0x6820c prologue: `push.w {r4..r8,sb,sl,fp,lr}` (9 regs = 36 B) + `sub sp,#0x74` (116 B)
- fn 0x6820c body SP = 0x9CED8 (= 0x9CF70 − 36 + 4 − 0x74, verified from LR@0x9CF6C=0x68b95)
- Any sub-callee of fn 0x6820c that pushes LR ⇒ saved LR at **0x9CED4**
- fn 0x68cd2 (first BL in fn 0x6820c, @ 0x68258): `push.w {r4..r8,lr}` (6 regs = 24 B), no sub sp
- fn 0x68cd2 body SP = 0x9CEC0; any sub-callee saved LR at **0x9CEBC**
- fn 0x68cd2 has 4 BLs; candidate saved-LR values: 0x68ceb, 0x68d05, 0x68d19, 0x68d2f

**Disasm subagent note:** `offline_disasm_68cd2.md` was generated by Haiku subagent; its
"LR@0x9CEBC" line is **wrong** (arithmetic slip: 0x9CED8−24=0x9CEC0 not 0x9CEBC, and LR
is at push-block top offset +20 not +0). Correct LR-slot for fn 0x68cd2 is **0x9CED4**.
The secondary slot 0x9CEBC still appears in the plan but as fn 0x68cd2's sub-callee LR
(coincidental address match).

**Probe plan (13 reads @ 1200ms FW-wait):**
- 2 regression reads: `ctr[0x9d000]`, `pd[0x62a14]` — continuity with t.101/102/103
- 2 anchors: E `[0x9CFCC]` (exp 0x67705), F `[0x9CF6C]` (exp 0x68b95) — chain stability
- T1 `[0x9CED4]` — sub-BL-of-0x6820c LR. If 0x6825d → hung inside fn 0x68cd2.
  Other LR-shaped values map to later BLs in fn 0x6820c.
- T2 `[0x9CEBC]` — sub-BL-of-0x68cd2 LR. Only meaningful if T1=0x6825d. Matches
  vs 0x68ceb/0x68d05/0x68d19/0x68d2f tell which fn 0x68cd2 body-BL is pending.
- 6-word sweep 0x9CEB8↓ — catches 3+ levels deep; flags LR-shaped (Thumb bit + code range)
- 1 sanity `*0x62e20`

Total reads 13 < test.103's 19 (known-safe budget).

### POST-EXIT CRASH PATTERN (observed in t.101/102/103)

Each test exits cleanly after its FW-silent timeout (2s). Approximately 30s later,
the host crashes / reboots. This is **unrelated to the probe itself** — test completes
and logs are written before the crash. Recovery: `journalctl -b -1` on next boot gives
full dmesg from the previous session. Workflow rule: commit + push before running.

---

## Previous state (2026-04-17, POST test.103 — frames A-E CONFIRMED, hang localized to fn 0x6820c)

Git branch: main. Host crashed ~30s after test.103 clean exit (same pattern as
test.101/102 — unrelated post-exit crash, test itself completed). Probe output
was captured via `journalctl -b -1` and appended to `phase5/logs/test.103.stage0`.

### TEST.103 RESULT — shallow chain confirmed, deeper hypothesis FALSIFIED

Module loaded 10:32:22, ran full probe, exited cleanly after 2s FW-silent
timeout (`brcmfmac ... TIMEOUT — FW silent for 2s — clean exit`). Host reset
followed ~30s later (not in journal; survived 2s of FW silence).

**Regression reads (stable vs t.101/102):**
- `ctr[0x9d000] = 0x000043b1` ✓
- `pd[0x62a14]  = 0x00058cf0` ✓
- counter frozen at 0x43b1 through T+1000ms → hang still present
- sanity `*0x62e20 = 0x00000000` ✓ (no progress past 0x68bbc, as expected)

**LR-slot reads (A..G) vs predicted:**

| Slot | Addr    | Read       | Expected    | Match | Meaning |
|------|---------|------------|-------------|-------|---------|
| A    | 0x9D09C | 0x00000320 | 0x320 EVEN  | ✓     | main frame (boot anchor) |
| B    | 0x9D094 | 0x00002417 | 0x2417      | ✓     | main → c_init |
| C    | 0x9D02C | 0x000644ab | 0x644ab     | ✓     | c_init → fn 0x63b38 |
| D    | 0x9D014 | 0x00063b7b | 0x63b7b     | ✓     | fn 0x63b38 → wl_probe |
| E    | 0x9CFCC | 0x00067705 | 0x67705     | ✓     | wl_probe → fn 0x68a68 |
| F    | 0x9CF6C | 0x00068b95 | 0x68acf     | ✗     | **NOT 0x67358 descent — deeper in fn 0x68a68 body** |
| G    | 0x9CF3C | 0x00092440 | 0x6739d     | ✗     | out-of-code-range; frame position was wrong |

**Calibrations (should NOT be LR-shaped by strict Thumb-odd filter):**
- `[0x9D028] = 0x00058cc4` — EVEN, so fails Thumb filter → not LR (likely saved r6 pointer into .rodata). Log text "offset error" is misleading; strict filter says fine.
- `[0x9CFC8] = 0x000043b1` — odd, in range, but equals the counter value at T+200ms → coincidence, not an LR.

**Deep sweep 0x9CF0C↓:** `00000004 000000c4 00093610 00000000 0009238c 00000000 00000004` — no code-range LRs; frame position was wrong (predicted for 0x67358, but actual descent uses different prolog sizes).

### NEW HYPOTHESIS — hang is in fn 0x6820c, not 0x67358

**Previous hypothesis RETRACTED:** "hang in wlc_attach's `bl 0x67f2c` → 0x67358 → 0x670d8 si_attach descent" is **falsified**. For LR F to be 0x68b95, fn 0x68a68 must have RETURNED FROM all four earlier body-BLs successfully:
- `bl 0x67f2c` @ 0x68aca (tail-call to 0x67358) → returned
- `bl 0x5250` @ 0x68b02 (nvram_get) → returned
- `bl 0x50e8` @ 0x68b0c (strtoul) → returned
- `bl 0x67cbc` @ 0x68b42 (struct setup) → returned

**LR math:** `bl 0x6820c` at 0x68b90 is a 4-byte BL → return addr = 0x68b94; Thumb bit set → saved LR = **0x68b95**. Matches F exactly.

**Current hang localization:** CPU is executing somewhere inside fn 0x6820c
(called from 0x68b90 in fn 0x68a68). Per `offline_disasm_68a68_body.md`,
fn 0x6820c "calls 0x68cd2, 0x142e0, fn 0x191dc, 0x9990, 0x9964 — not yet
fully traced" with MEDIUM hang capacity. This was previously ranked LOW
priority; now promoted to PRIMARY target.

### Next steps (test.104)

1. **Offline disasm fn 0x6820c** (subagent, no HW cost): prolog → frame size,
   BL list → LR-candidate table for the current frame's sub-BLs.
2. **Test.104 probe plan:**
   - 2 regression reads (ctr, pd) — continuity
   - 5 anchor reads A..E — cheap confirmation stack didn't shift
   - **Dense sweep 0x9CF68..0x9CF40** (10 words unprobed between F and mispositioned G) — catch fn 0x6820c's saved-LR if its sub-BL is pending
   - Informed-by-disasm: targeted read at predicted fn 0x6820c sub-frame LR slot
   - 1 sanity `*0x62e20`
   - Total ~20 reads, same order as test.103 — known-safe budget.

### Pre-test.103 state retained below for context.

---

## Previous state (2026-04-17, POST test.102 — stack sweep NULL, premise corrected, planning test.103)

Git branch: main. Last pushed commit 714c24f (Offline disasm: firmware stack located).
All test.102 work committed & pushed. Session resumed after unrelated host crash.

### TEST.102 RESULT — Case WEAK/NULL: 0 plausible LRs, premise was wrong

Test.102 ran cleanly (09:53:23 → 09:53:25 exit, RP restored). The
unrelated host crash came ~30min after the test completed.

**Readings at T+200ms:**
- Regression (vs test.101): `ctr[0x9d000]=0x43b1`, `pd[0x62a14]=0x58cf0` — matches
- Sanity: `*0x62e20=0x00000000` — matches test.101 (no progress past 0x68bbc still)
- Dense stack sweep at 0x9FE20..0x9FE5C (16 words × 4B):
```
0x9FE20: 1d9522f9 e6f20132 0bb91c6f 563dc9f8
0x9FE30: eb60c52c 1da991aa 21323bfa f3f5d5f6
0x9FE40: f992d3bc cfc5e975 f784a2ae 6ca7e38c
0x9FE50: 808b62f8 54b85687 55320d7b 98c8c797
```
All 16 words fail the LR filter (`∈[0x800..0x70000] AND LSB set`) — every
value > 0x70000 as 32-bit. **No match to any LR in the pre-computed table.**

### The premise was wrong — 0x9FE20 is not stack

Investigation after the null result: RESUME_NOTES (and test.102 plan)
claimed "test.97 located active stack frames near 0x9FE40". This was a
misread. Test.97's actual probe was at **0x9CE00..0x9CE1C**, not 0x9FE40,
and the values it captured were:
```
0x9CE08..0x9CE1C:  "1258" "88.0" "00 \n" "RTE " "(PCI" "-CDC"  (ASCII)
```
That's the RTE banner string IN THE CONSOLE RING (ptr = 0x9CC5C per test.96
baseline). Test.97 wasn't reading a stack — it was reading `printf` output.
The 0x9FE40 target has no provenance at all. Test.102 probed uninitialized
memory well above the actual stack.

### Offline disasm (POST test.102) — real SP location found

`phase5/notes/offline_disasm_fw_stack_setup.md` — full report.

Subagent disasm of firmware boot at offset 0..0x400 identified the actual
SP setup at firmware offset 0x2FC: `mov sp, r5`, r5 = 0xA0000 - 0x2F60 =
**0x9D0A0**. This is the SYS-mode stack pointer, used for everything
(hndrte RTOS pattern — all exception vectors redirect to SYS stack via
srsdb, no separate per-mode stacks).

**Firmware stack: [0x9A144 .. 0x9D0A0), grows DOWN, 0x2F5C bytes.**

- Entirely inside TCM → still readable via `brcmf_pcie_read_ram32`.
- Corroborating evidence (all from prior probes):
  - `ws[0x62ea8] = 0x9D0A4` = SP_init + 4 (static struct just above top)
  - `ramsize = 0xA0000` matches the r7 literal used in the size constant
  - Console ring at 0x9CCC0 is just BELOW stack bottom — classic hndrte
    layout (stack at top, printf ring beneath, BSS below)

### Premise for test.103 (advisor-validated)

Two LR-table issues to resolve BEFORE next test:

1. **Sweep location** — target the top of the stack (0x9D0A0 down) for
   shallow frames, OR target ~0x9CFD0 (approx 200 bytes down) for the
   deep descent frames listed in `test102_lr_table.md`. Advisor's
   preferred order: extend the LR table to the SHALLOW frames FIRST (no
   hardware cost), so a top-64-bytes sweep becomes directly interpretable.

2. **LR-table gap** — existing table covers deep descent
   (wl_probe → 0x68a68 → 0x67358 → 0x670d8 → si_attach children). The
   SHALLOW path (boot → main → c_init → fn 0x63b38 → wl_probe's caller)
   has NO entries yet. A subagent run is currently populating
   `phase5/notes/test103_lr_table_shallow.md` (disasm of c_init body,
   fn 0x63b38 body, and boot init from 0x2FC forward).

### test.103 PLAN — targeted LR-slot reads + deep sub-frame sweep

**Goal:** confirm the predicted frame chain (A..G) AND read the saved LR
of the 0x670d8 sub-BL that is currently hung — the one new piece of
information we need to isolate the hang site.

**Predicted stack layout** (from `test103_lr_table_shallow.md`):

| Frame | Addr    | Expected LR value | What it confirms |
|-------|---------|-------------------|------------------|
| A main       | 0x9D09C | 0x00000320 | outermost (boot tail) — **EVEN, exact-match only** (literal `mov lr, r0`, not bl/blx — Thumb bit NOT set) |
| B c_init     | 0x9D094 | 0x00002417 | main → c_init active |
| C fn 0x63b38 | 0x9D02C | 0x000644ab | c_init's wl bl active |
| D wl_probe   | 0x9D014 | 0x00063b7b | fn 0x63b38 → wl_probe active |
| E wlc_attach | 0x9CFCC | 0x00067705 | wl_probe → fn 0x68a68 active |
| F fn 0x67358 | 0x9CF6C | 0x00068acf | wlc_attach descent active |
| G fn 0x670d8 | 0x9CF3C | 0x0006739d | deep init active |
| sub LR (hung)| ~0x9CF0C or lower | one of {0x67195 / 0x671b5 / 0x671c1 / 0x671d5 / 0x671f7} | identifies WHICH 0x670d8 BL is stuck |

**Probe design (19 reads total, T+200ms only):**

- **7 targeted LR-slot reads** (A..G): read each predicted-LR address,
  check against expected value. Each is a single word, direct hit.
- **2 calibration reads** (advisor-recommended): read "between-LR" slots
  0x9D028 (frame C mid — saved r6) and 0x9CFC8 (frame E mid — saved r8).
  Both should NOT be LR-shaped. If either IS LR-shaped, that's unambiguous
  evidence of a 4-byte offset error in the corresponding frame-size
  prediction (cheap diagnostic).
- **7 deep sweep words** at 0x9CF0C..0x9CEF0 (4B stride): catches the
  saved LR of whatever 0x670d8 sub-call is currently running. Expected
  to find ONE of the five candidate LRs listed above.
- **2 regression reads**: ctr[0x9d000] (expect 0x43b1), pd[0x62a14]
  (expect 0x58cf0) — continuity with test.101/102.
- **1 sanity**: *0x62e20 (expect 0 — confirms breadcrumb still not written).

**Pre-registered failure signatures (set before run so we can't
post-hoc rationalize):**

1. **Success**: ≥5 of 7 LR-slot reads match predicted values AND deep
   sweep contains ≥1 LR from the 0x670d8-sub candidates. → test.104
   is "pin down which sub-BL via disasm of that sub's body for
   breadcrumb candidates or deeper stack walk".
2. **Offset drift**: calibration read (0x9D028 or 0x9CFC8) IS LR-shaped,
   AND the aligned target is NOT. → frame-size prediction is off by 4B
   starting at that frame. Re-disasm that function's prologue offline.
   DO NOT trust deeper reads.
3. **Shallow only**: A/B match (0x9D09C=0x320 **EVEN**, 0x9D094=0x2417) but C+
   don't. → hang happened before reaching fn 0x63b38, OR fn 0x63b38's
   prologue is different. Either way, outer chain anchor confirms the
   model; localize the divergence.
4. **All miss**: no predicted LR at any target address AND no LR-shaped
   words in deep sweep. → SP_init is wrong (stack is elsewhere), OR
   stack was trashed by an early fault. test.104 = sparse survey across
   whole [0x9A000..0x9D100) range to locate it.

**Budget:** 19 reads — exactly at test.102's known-safe count.
FW-wait stays at 1200ms. No new regression risk.

**Implementation notes:**
- Replace test.102's 16-word sweep block with the 19-read block above.
- Each read via existing `brcmf_pcie_read_ram32` path.
- Masking (T101_REMASK) called before each read — same as test.101/102.
- Log lines: group A-G in one table-like print, calibrations in another,
  deep sweep in a third.
- **LR-filter caveat:** Frame A (0x9D09C) is a permanent static anchor
  of value **0x320 (EVEN)** because the boot code loaded LR via literal
  `mov lr, r0` (not a bl/blx, so Thumb bit is not set). Do NOT apply
  an odd-bit filter to the 0x9D09C slot — match it exactly against
  0x320. Frames B..G are all from bl/blx, so odd-bit holds for them.

### After running test.103
- Apply failure signature matrix above.
- Stage1 = none (this is a pure read-only probe; no second stage needed).

**Pre-test.102 state retained below for full context.**

---

## Previous state: POST test.101 — Case 0: breadcrumb ZERO, hang UPSTREAM of 0x68bbc

### TEST.101 RESULT — Case 0 (matrix row 1): breadcrumb ZERO

Test.101 ran cleanly in boot -1 (07:42:59 → 07:43:01 clean exit). Machine
then crashed/rebooted ~30 min later (08:13:05 boot 0) — unrelated to the
test run itself; the test completed with "RP settings restored".

Key readings:
```
Pre-ARM baseline: *0x62e20 = 0x00000000  ZERO (expected — no stale TCM) ✓
T+200ms:          *0x62e20 = 0x00000000  ZERO
```

Control pointers (as test.100):
```
ctr[0x9d000]  = 0x000043b1
d11[0x58f08]  = 0x00000000
ws [0x62ea8]  = 0x0009d0a4
pd [0x62a14]  = 0x00058cf0
```
Counter frozen at 0x43b1 from T+200ms onward, confirming hard freeze by
T+12ms (per test.89 timeline) still holds.

**Interpretation per test.101 matrix row 1:** baseline=0 means no stale
TCM (interpretation is clean); T+200ms=0 means fn 0x68a68 NEVER wrote
*0x62e20 at 0x68bbc. Therefore fn 0x68a68 did NOT reach 0x68bbc.

Combined with test.100 (Case C′: fn 0x1624c never ran), the freeze is:
- Inside fn 0x68a68 prefix/body BEFORE bl 0x1ab50 at 0x68bcc
  (specifically the unexamined body region 0x68aca–0x68bbc), OR
- Upstream in wl_probe (fn 0x67614), in one of the earlier sub-BLs
  BEFORE bl 0x68a68 at 0x67700.

Per the earlier subagent offline disasm (`offline_disasm_wl_subbls.md`),
the five wl_probe sub-BLs (fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c,
plus fn 0x68a68 prefix through 0x68aca) contain NO spin loops, HW-register
polling, or fixed-TCM stores in their direct bodies. The hang must
therefore be in one of their DESCENDANTS, or in fn 0x68a68's UNEXAMINED
body 0x68aca–0x68bbc.

### Offline disasm result (POST test.101, 2026-04-17)

`phase5/notes/offline_disasm_68a68_body.md` — full report of fn 0x68a68
body 0x68a68..0x68bcc and all 6 body-BL targets.

**Key finding:** fn 0x68a68's first body BL (`bl 0x67f2c` at 0x68aca) is a
4-insn trampoline that **tail-calls 0x67358** — the SAME si_attach descent
entered from pciedngl_probe (which succeeded). So wlc_attach's failure is
a re-entry into 0x67358 → 0x670d8 → 0x64590 (si_attach) → core-register
dispatches → deeper.

**No discriminating fixed-TCM breadcrumb exists in this descent.** Every
store in fn 0x68a68 body, fn 0x670d8 body, and fn 0x64590 (si_attach) is
r4/r3-relative into freshly-alloc'd structs. The ONLY fixed-TCM write in
the descent (fn 0x66e90: `str r0, [*0x62a88]`) is a LATCH — populated by
pciedngl's first entry, SKIPPED by wlc_attach's second entry (list is
already non-empty; takes the error-printf path without overwriting).

Advisor verdict: "Don't extend disasm further looking for a breadcrumb.
That IS the evidence." → Pivot to **stack-walk approach** for test.102.

### test.102 PLAN — stack-locator sparse sweep

**Goal:** Identify the function whose `bl` is currently pending-return by
reading the stack region and filtering for saved LR values. Each LR
candidate maps (via pre-computed table, see below) to a specific call
site — naming the function whose call is currently suspended.

**Rationale for stack walk (not more breadcrumbs):**
- The wlc_attach descent has no discriminating fixed-TCM stores.
- Each nested `bl` in ARM Thumb pushes lr on the stack (part of
  `push {..., lr}` prologues). When the CPU is stuck mid-call, its live
  frame chain is persistent in RAM.
- Test.97 located active stack frames "near 0x9FE40". TCM end is 0xA0000.
- Filter: `word ∈ [0x800..0x70000]` AND LSB set (Thumb bit) → plausible LR.
- Confirmation: ≥2 LRs forming a known caller→callee chain. A lone
  hit is data-shaped-like-LR — not confirmed. A chain is strong.

**Probe design (read-only, all via `brcmf_pcie_read_ram32`):**
- Baseline pre-ARM: `*0x62e20` — continuity check vs test.101
- T+200ms: 2 regression reads — ctr (0x9d000), pd (0x62a14) — dropped d11
  and ws (test.101 showed d11=0 stable, ws=0x9d0a4 stable, not interpretation-gating)
- T+200ms: **dense stack sweep — 16 reads × 4B stride at 0x9FE20..0x9FE60**
  (64B region centered on test.97's 0x9FE40 frame-density locator)
- T+200ms: 1 re-read of `*0x62e20` (sanity vs test.101)
- Total: **19 reads** at the single T+200ms timepoint.

**Budget analysis** (per advisor linear-scaling assumption — no data
between 5 and 13 reads, and nothing above 13):
- test.101: 5 reads @ 1200ms FW-wait → clean
- test.100: 13 reads @ 2000ms FW-wait → ~1.9s regression
- test.102: 19 reads @ 1200ms FW-wait → ~1.5× test.101, **well below** the
  known regression point at 13. Staying dense+narrow buys the ability to
  see a chained LR pair, at the cost of SP-location precision.

**FW-wait:** keep at 1200ms (same as test.101 — per advisor, budget is
probe count, not outer loop).

**Pre-computed LR → function interpretation table:**
See `phase5/notes/test102_lr_table.md` — built from existing disasm
(test88/90/91, offline_disasm_68a68_body). Expected live chain top-down:
1. wl_probe's `bl 0x68a68` @ 0x67700 → LR = **0x67705** (Thumb bit set)
2. wlc_attach's `bl 0x67f2c` @ 0x68aca → LR = **0x68acf**
3. (0x67f2c is tail-call trampoline → no frame)
4. fn 0x67358's `bl 0x670d8` @ 0x67398 → LR = **0x6739d**
5. fn 0x670d8's `bl 0x64590` @ 0x67190 → LR = **0x67195**, or a later
   child call (0x671b5, 0x671c1, 0x671d5, 0x671f7)
6. Depending on depth: LRs inside si_attach body (0x645b3, 0x645c7,
   0x6463d, 0x64679, 0x6468f — from test91_disasm BL list)
   All pushed-LR values are **odd** (Thumb bit set) — filter accordingly.

**Confirmation criteria:**
- **Strong:** ≥2 LRs from the table appear in the 16-word sweep.
- **Moderate:** 1 LR from table + nearby word in a plausible range but
  not listed (may be a deeper child not yet disassembled).
- **Weak/null:** 0 LRs from table → sweep missed the SP region; dense
  follow-up in test.103.

**Deferred to test.103 (per budget):**
- Full console ring dump (firmware may have printed an error before hang)
- Dense 32-word sweep at the LR-rich 128B region identified by test.102

**Crash-safety checks:**
- All 16 sweep addresses are inside TCM (< 0xA0000).
- No HW register reads, no core switching.
- Masking (T101_REMASK) called before each read — same pattern as test.101.

### Pre-test.101 state (retained for context below)

---

### Advisor refinement #1 (added 2026-04-17, pre-run)

Per advisor, the pre-ARM baseline read was the missing piece from the
earlier test-plan review — without it, a non-zero post-FW breadcrumb
could reflect residual TCM state from a prior in-same-boot modprobe,
not a fresh FW write. Code change: 3-line probe in pcie.c inside the
existing pre-ARM logging block (before ARM release, zero masking-loop
impact). Emits `dev_emerg "BCM4360 test.101 pre-ARM baseline: *0x62e20=...
ZERO (expected) / NON-ZERO (stale TCM, breadcrumb reading is unreliable)"`.

Matrix interpretation rule: if baseline != 0, the T+200ms breadcrumb
reading is UNRELIABLE and the run should be re-done after fresh power
cycle. If baseline == 0 and T+200 == 0 → Case U1 (hang before 0x68bbc).
If baseline == 0 and T+200 != 0 → Case D (hang at/past bl 0x1ab50).

### Offline disasm result (subagent, 2026-04-17)

`phase5/notes/offline_disasm_wl_subbls.md` — full report.

Disassembled wl_probe's 5 untraced sub-BLs (fn 0x66e64, fn 0x649a4,
fn 0x4718, fn 0x6491c) and fn 0x68a68's prefix. **None contain spin loops,
HW-register polling, or fixed-TCM stores** — every memory write is
r4-relative into the freshly-malloc'd wl_ctx. fn 0x4718 is a 3-instruction
leaf. Therefore the hang is NOT internally in any of those five.

**Most-likely hang site:** fn 0x68a68 (wlc_attach) BODY between its prefix
end at 0x68aca and `bl 0x1ab50` at 0x68bcc — an unexamined region (test.100
only excluded fn 0x1624c, a deeper descendant).

**Hot breadcrumb identified: `*0x62e20`.** Spot-verified:
```
0x68bb6: ldr  r3, [pc, #200]   ; literal at 0x68c80 = 0x00062e20 ✓
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, 0x68bbe       ; skip if already set
0x68bbc: str  r4, [r3]           ; *0x62e20 = wl_ctx ptr
0x68bcc: bl   0x1ab50            ; PHY descent (8 bytes later)
```
`*0x62e20` is zero in the firmware image. After firmware reset:
- **non-zero** → fn 0x68a68 advanced to within 8 bytes of bl 0x1ab50;
  hang is inside bl 0x1ab50 (or the 2-insn gap before it). test.100
  already excluded fn 0x1624c, so the hang would be in fn 0x1ab50 BEFORE
  it reaches fn 0x16476.
- **zero** → fn 0x68a68 did not reach 0x68bbc. Hang is in one of its
  earlier BLs (0x68a68 prefix/body), or in wl_probe BEFORE bl 0x68a68 at
  0x67700 — i.e. in fn 0x66e64 / fn 0x649a4 / fn 0x4718 / fn 0x6491c's
  DESCENDANTS (since their direct bodies are bounded).

### test.101 PLAN — minimal single breadcrumb probe

**Goal:** narrow hang to "past 0x68bbc" vs "before 0x68bbc" with MINIMUM
loop-overhead impact. Test.100 added 9 extra `read_ram32` calls and
regressed (boot ended between T+1800ms and T+2000ms).

**Probe changes from test.99 baseline:**
- REMOVE test.100's triple-timepoint 3-field wait-struct reads (already
  answered — Case C′ confirmed, struct never touched).
- REMOVE test.100's T+400ms+T+800ms duplicate pointer probes (test.99
  already proved pointers are byte-identical across those windows).
- ADD one new read: `TCM[0x62e20]` at T+200ms only.

Net: test.101 probe count = test.99 - 2 + 1 = **fewer reads than
test.99**. Should not regress on the masking-loop budget.

**Also:** shorten FW-wait from 2000ms to 1200ms to widen safety margin
against whatever periodic event killed test.100 at ~1.9s.

**Matrix (after reading *0x62e20):**

| *0x62e20 | Conclusion | Next action |
|----------|------------|-------------|
| 0          | fn 0x68a68 did NOT reach 0x68bbc. Hang is in 0x68a68 prefix/body before the breadcrumb, or upstream in wl_probe sub-BL descendants. | test.102: probe wl_ctx fields (needs wl_ctx ptr discovery first) OR disasm fn 0x68a68 prefix + descendants of fn 0x6491c. |
| non-zero, value plausible as heap ptr (TCM range 0x0..0xA0000, typically 0x9xxxx) | fn 0x68a68 reached 0x68bbc. Hang is inside the window `bl 0x1ab50 → bl 0x16476 → b.w 0x162fc → bl 0x1624c` but NOT inside fn 0x1624c itself (test.100 excluded that). So hang is in the body of fn 0x1ab50, fn 0x16476, or fn 0x162fc pre-spin. | test.102: disasm those three fn bodies pre-bl; probe their breadcrumbs. |
| non-zero, value implausible (random)    | Either TCM read failed or breadcrumb theory is wrong. | Re-check read path; verify literal pool claim with second tool. |

**Pre-flight reminders:**
- Probe is read-only via `brcmf_pcie_read_ram32` (same safe path as test.99/100).
- FW-wait shortened to 1200ms. No other change to cleanup order.
- If machine crashes anyway, that's still informative — different cadence
  than test.100 would pinpoint what the ~1.9s event is.

### Hardening checks completed before build

**Firmware image at offset 0x62e20**: 0x00000000 (surrounding .bss-like
region also zero). So post-FW non-zero at 0x62e20 unambiguously means
FW wrote it.

**All writers of 0x62e20 in the firmware** (grepped literal 0x00062e20,
3 aligned hits in pools at 0x149b0 / 0x68208 / 0x68c80):
1. `fn 0x68a68 @ 0x68bbc` — `str r4, [r3]` sets wl_ctx ptr (attach path,
   on wl_probe lineage). **This is the breadcrumb.**
2. `fn 0x681bc @ 0x681cc` — `str r2, [r3]` where r2=0, conditional clear.
   Prologue at 0x681bc; only runs on detach/cleanup (guarded by `arg ==
   *0x62e20`). **Does NOT run during wl_probe.**
3. `fn at 0x14948 uses literal at 0x149b0` — READ-ONLY
   (`ldr r3,[pc,#88]; ldr r3,[r3,#0]; cbz r3,err; ldr r3,[r3,#12]`).
   Diagnostic/logging helper. **Not a writer.**

→ During wl_probe attach, only writer of 0x62e20 is fn 0x68a68 @ 0x68bbc.
Breadcrumb semantics are preserved: non-zero at T+200ms ⇒ that single
instruction ran.

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.100 probe block with
  test.101: single read of TCM[0x62e20] at T+200ms. Drop duplicate
  pointer reads at T+400/800ms. Change FW-wait cap from 2000ms to 1200ms.
- `phase5/work/test-staged-reset.sh` — relabel test.100 → test.101,
  LOG filename accordingly.

### After running test.101
- Apply matrix, choose test.102.
- Most-likely outcome (per subagent analysis) is *0x62e20 non-zero →
  hang is in fn 0x1ab50 pre-bl body.

### TEST.100 RESULT — Case C′ (matrix row 5): wait-struct = pre-init garbage, stable

test.100 ran in boot -1 (23:31:37 → 00:46:48). Probes at T+200/400/800ms
captured identical values (stability check PASSED). Firmware hard-frozen
at T+12ms per test.89 timeline; nothing on-chip changed across 600ms.

Control pointers (identical across T+200/400/800ms):
```
ctr[0x9d000]  = 0x000043b1    (static constant from fn 0x673cc)
d11[0x58f08]  = 0x00000000    (D11 obj never linked)
ws [0x62ea8]  = 0x0009d0a4    (wait-struct pointer — static, from BSS)
pd [0x62a14]  = 0x00058cf0    (pciedngl vtable, matches test.93/99)
```

Wait-struct field reads at ws=0x9d0a4 (identical across T+200/400/800ms):
```
f20 [ws+0x14] = 0x66918f11
f24 [ws+0x18] = 0x5bebcbeb
f28 [ws+0x1c] = 0x84f54b2a
```

**None of these are {0,1}** — they are arbitrary 32-bit values. Per the
test.100 matrix (row 5): `f24 ∉ {0,1}` → **Case C′: struct never touched,
pre-init garbage**. fn 0x1624c's setup code (`r3->field24=1;
r3->field28=0`) never ran, therefore fn 0x1624c itself never ran.

**Conclusion:** the freeze is strictly upstream of fn 0x1624c — inside
wl_probe (fn 0x67614), before it reaches the D11 PHY wait chain. The
bl-graph says exactly one path from wl_probe reaches fn 0x1624c; that path
is fn 0x67700→0x68a68→…→0x1624c. The hang must be in either the body of
fn 0x68a68 before its call to fn 0x1ab50, or in one of the 6 other sub-BLs
wl_probe invokes BEFORE bl 0x68a68 (at offsets 0x67700 and earlier).

This corroborates test.97's hint (same "garbage" reading) and definitively
rules out the PHY-completion-wait hypothesis as the LIVE freeze site.

### Test.100 ALSO produced a new regression

The run died between T+1800ms and T+2000ms (journal ends at T+1800ms
FROZEN, no TIMEOUT / RP-restore lines, machine powercycled). test.99 used
the same FW-wait loop and exited cleanly at T+2000ms. The delta is 3 extra
`read_ram32` calls at each of T+200/400/800ms (≈30–90ms total extra time
in the masking loop). That evidently nudged past a re-mask window and a
periodic PCIe event slipped through.

**Implication for test.101:** the masking loop must be re-audited or the
FW-wait shortened (e.g. 1000ms) before adding any more probes. Do NOT
stack further reads on top of the current loop without budget work.

### Next step — offline-only progress before test.101

Per advisor review, the cheap-progress ordering is:

1. **Firmware-binary sanity check** (30 seconds, offline): dump firmware
   image bytes at offset 0x9d0b8, 0x9d0bc, 0x9d0c0. If they match the read
   values 0x66918f11 / 0x5bebcbeb / 0x84f54b2a → "Case C′ = firmware image
   static data" confirmed. If they don't match → new puzzle (uninit RAM?
   wrong address translation?).

2. **Offline disasm of wl_probe's 6 untraced sub-BLs**. wl_probe has 7
   sub-BLs; only bl 0x68a68 at 0x67700 (→ PHY chain) is currently mapped.
   The other 6 are unknown. Find each, note its reads/writes (globals or
   fields of wl_struct). The hang is in one of them (or in fn 0x68a68's
   body before bl 0x1ab50). This narrows test.101 to concrete breadcrumbs
   instead of the hypothetical wl_struct[+0x90] placeholder.

3. **Masking-loop audit**: ensure re-mask fires every iteration when probe
   block inflates the body; consider dropping FW-wait from 2000ms to
   1000ms for test.101 to widen margin.

4. Only THEN design test.101 probes from concrete breadcrumb sites.

---

## Pre-test.100 state (retained for context below)

### Offline disasm — wl_probe and freeze chain (no hardware test)

`phase5/notes/offline_disasm_c_init.md` Round 3 + Round 4 (full detail).

Anchored "wl_probe called\n" print site to fn 0x67614 (LDR-literal scan
matched "wl_probe" string at 0x4a1ea via *0x67890). **fn 0x67614 IS
wl_probe()**. It is called as `wl_struct.ops[0]` from inside fn 0x63b38 in
c_init's wl-device registration step.

Brute-force callgraph BFS (depth ≤ 6) from each of wl_probe's 7 sub-BLs
shows EXACTLY ONE reaches the test.96 D11 PHY wait chain:

```
wl_probe @ 0x67614
 → bl 0x68a68 @ 0x67700           (5 stack args + 4 reg args)
   → bl 0x1ab50 @ 0x68bcc
     → bl 0x16476 @ 0x1ad2e        (PHY register access wrapper)
       → b.w 0x162fc                (PHY-completion wrapper)
         → bl 0x1624c @ 0x1632e     (SPIN: while ws->f20==1 && ws->f28==0)
```

`fn 0x68a68` has exactly ONE caller — wl_probe at 0x67700 — so the entry to
the spin-loop subtree is unique through wl_probe. The freeze fingerprint
matches test.96's analysis (D11 PHY ISR never fires → field28 stays 0). The
EARLIER claim that the hang was via c_init's "Call 3" (0x6451a) was wrong —
that dispatch chain only runs AFTER wl_probe RETURNS, and wl_probe never
returns (so wl_struct[+0x18] stays 0, as observed in test.99).

Open questions remaining (will be answered by test.100):
- Is the live freeze actually inside the fn 0x1624c spin-wait, or earlier
  in the wl_probe path (e.g. inside fn 0x66e64 / fn 0x649a4 / fn 0x68a68
  body before reaching the PHY chain)?
- Wait struct address: test.99 read `*0x62ea8 = 0x9d0a4` — the static BSS
  struct that fn 0x1624c spins on. We can probe its field20/24/28 directly.

### test.100 PLAN — wait-struct field probe (cheap PHY-wait fingerprint check)

**Goal:** decide between three concrete hypotheses with ONE more cheap
read-only hardware cycle:

1. PHY spin-loop is the live freeze location (advisor's "case A").
2. fn 0x1624c entered then exited via the cancel path (case B).
3. fn 0x1624c never entered — freeze is upstream in wl_probe (case C).

**Probes (stage0, all read-only TCM accesses via brcmf_pcie_read_ram32):**

Wait struct: addr = `*0x62ea8 = 0x9d0a4` (confirmed in test.99). Read fields
at offsets +0x14/+0x18/+0x1c (= field20 / field24 / field28 in test.96
analysis) at T+200/400/800ms to confirm stability:

```
ws_addr  = *0x62ea8                        ; should be 0x9d0a4
field20  = TCM[ws_addr + 0x14]             ; status flag (loop var)
field24  = TCM[ws_addr + 0x18]             ; "in progress" flag
field28  = TCM[ws_addr + 0x1c]             ; completion flag (set by ISR)
```

Also keep the test.99 pointer-sample probes (ctr/d11/ws/pd) as control — if
those CHANGE between test.99 and test.100 it would invalidate the read.

**Pre-flight stability check (READ FIRST before applying matrix):**

test.89 established firmware hard-freezes by T+12ms. test.99 confirmed
control pointers are byte-identical across T+200/400/800ms. Therefore
field20/field24/field28 MUST also be byte-identical across the three
timepoints. **If they vary, that itself is the bigger story** (delayed
code path, or the read isn't doing what we think — e.g. probe disturbing
state, addr translation wrong). Stop, characterise the variation, and DO
NOT apply the matrix to T+200ms values alone.

**Matrix interpretation (advisor, refined):**

| field24 | field20 | field28 | Conclusion |
|---------|---------|---------|------------|
| 1 | 1 | 0 | **Case A — spin-loop is live freeze.** Path B step 1 (D11 BCMA wrapper bring-up to enable D11 core / route ISR). |
| 1 | 0 | 0 | **Case B — entered then cancelled.** Hang is in fn 0x162fc body AFTER bl 0x1624c returned via cancel path. Re-examine fn 0x162fc continuation. |
| 1 | * | !=0 | Spin completed (field28 set), but firmware still hung downstream. Hang is past PHY wait — need to trace fn 0x1ab50 / fn 0x68a68 callees beyond the PHY register loop. |
| 0 | * | * | **Case C — fn 0x1624c never entered, struct zero-initialised.** Freeze is upstream in wl_probe. Probe candidates: fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c, or fn 0x68a68 body before bl 0x1ab50. |
| ∉{0,1} | * | * | **Case C′ — struct never touched, pre-init garbage** (test.97 saw garbage values here). Same upstream-freeze conclusion as C, but distinguishable from "BSS-zero never-entered" — different next-test framing. |

**Risk profile:** identical to test.99. All probes are TCM reads via
existing `brcmf_pcie_read_ram32` path, gated by the same masking macro.
test.99 ran cleanly (clean exit, RP restored) so test.100 should too. If
the machine crashes anyway, that itself is a useful signal (different from
test.99's clean exit).

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.99 probe block (lines
  ~2516-2621) with test.100: 3-field wait-struct probes + control pointer
  re-reads at T+200/400/800ms. Drop the console ring dump (test.99 already
  read it; nothing changed).
- `phase5/work/test-staged-reset.sh` — labels test.99 → test.100, LOG
  filename test.99.stage${STAGE} → test.100.stage${STAGE}.

### After running test.100
- Map readings to the matrix above to choose next test.
- Common-case (A) follow-up = test.101 = D11 core wrapper bring-up via
  chip.c bus-ops (Path B step 1).
- (B) follow-up = offline-disasm fn 0x162fc continuation past 0x16332.
- (C) follow-up = test.101 = probe wl_probe sub-allocations (e.g. write a
  "breadcrumb" by reading r4 alloc result via TCM probe of wl_struct[+0x90]).

---

## Pre-test.99 state (2026-04-17, retained for context)

Git branch: main. Last pushed commit 75b52a1 (Post-test.99 doc).
Pending commit: offline disasm of c_init() + corrected freeze location.

**TEST.99 RESULT: firmware hard-frozen, no delayed code path, D11 obj still unlinked.**

Test.99 ran cleanly at 23:28:52–23:28:56 (boot -1, journal
`phase5/logs/test.99.journal`). "RP settings restored" — no host crash.

Pointer sample — **IDENTICAL across T+200/400/800ms**:
```
ctr[0x9d000]  = 0x000043b1    (static, matches test.89)
d11[0x58f08]  = 0x00000000    (D11 obj never linked — matches test.98)
ws [0x62ea8]  = 0x0009d0a4    (TCM ptr to static struct in BSS)
pd [0x62a14]  = 0x00058cf0    (vtable, matches test.93)
```
→ firmware is frozen by T+200ms with NO runtime change for the next 600ms.
Eliminates any "delayed DPC/ISR writes" hypothesis for these globals.

Console ring (256 bytes from 0x9ccc0): ChipCommon banner truncated. The
test.80 console captured the printed sequence:
ChipCommon → "wl_probe called" → "pciedngl_probe called" → **RTE banner**
(`RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz`)
then KATS fill — i.e. **freeze is AFTER the RTE banner print**, not at
"pciedngl_probe called" as earlier notes incorrectly stated.

### Offline disasm finding (2026-04-17, no hardware test)

`phase5/notes/offline_disasm_c_init.md` — full breakdown.

**`c_init()` lives at TCM 0x642fc.** Its literal pool (0x64540-0x6458c)
reveals the function's full call structure:

| Step | What c_init does | Observed? |
|------|------------------|-----------|
| 1 | Print RTE banner (format @ 0x6bae4, version @ 0x40c2f) | ✓ test.80 |
| 2 | Print `"c_init: add PCI device"` (@ 0x40c42) | ✗ |
| 3 | Store `*0x62a14 = 0x58cf0` (pciedngl_probe vtable) | ✓ test.99 |
| 4 | Print `"add WL device 0x%x"` (@ 0x40c61) | ✗ |
| 5 | Failure paths: `binddev failed` / `device open failed` / `netdev open failed` | ✗ none |

So execution definitely reaches step 3 (vtable populated). It does NOT
reach the failure paths. Freeze is between step 3 and the WL print, inside
either pciedngl_probe init or a subroutine called from c_init.

### Next decision (test.100) — three options

- (a) **Continue offline disasm** (free, no hardware test): trace c_init
  body 0x642fc–0x6453e (~322 bytes Thumb-2) to identify the exact BL after
  the vtable store. May pinpoint the failing subroutine without any
  hardware cycle.
- (b) **Wider/relocated console dump** to capture KATS region — earlier
  thought to surface post-RTE prints, but offline disasm shows step 4
  print only happens AFTER subroutine returns, so likely still empty.
- (c) **D11 BCMA wrapper reads** (Path B step 1) — requires chip.c bus-ops
  scaffolding; defer until offline disasm exhausts cheap progress.

**Recommend (a) first** — it is strictly free and may eliminate (b) and
narrow (c) to a specific D11 prereq.

**TEST.98 RESULT: step1 = TCM[0x58f08] = 0x00000000 → hang is in si_attach.**

Test.98 probe readings (from `phase5/logs/test.98.journal`, captured via
journalctl -b -1 after the module+script mismatch caused the stage0 log to be
labelled test.97 — raw partial preserved at `phase5/logs/test.98.stage0.partial`):

```
step1 = TCM[0x58f08] = 0x00000000 (D11_obj->field0x18)
step1 out of TCM range → D11_obj->field0x18 not set
(si_attach didn't run / didn't reach D11 obj init)
counter T+200ms = 0x000043b1 RUNNING
counter T+400ms = 0x000043b1 FROZEN (stays frozen through 2s timeout)
clean exit — no host crash
```

**Interpretation:**
- Firmware DOES start and runs some early code (counter reaches 0x43b1).
- Firmware freezes by T+400ms — a very early freeze, well before the D11 PHY
  wait loop at fn 0x1624c (which is several function levels deep inside
  si_attach's D11 bring-up).
- The D11 object pointer at `*0x58f08` is NEVER populated, which means the
  D11 section of si_attach hasn't reached the point where it links its
  object into that global.
- Previous hypothesis — "hang in fn 0x16f60 AHB read" — is INCORRECT; the
  pointer-chain cannot be walked because its root entry is still 0.

**Revised root cause hypothesis:** si_attach cannot bring the D11 core up at
all. A prerequisite (reset/enable/clock/power/interrupt-routing) is not in
the state si_attach expects. Per GitHub issue #11 recommendation #3.

**Pivot: Path B — D11 core prerequisite checks (phase5_progress.md).**

### Revised interpretation (advisor input + test.89 context)

test.89 proved firmware actually freezes at T+12ms — not at T+200–400ms.
The counter at 0x9d000 is a static constant (0x43b1) written exactly once
by fn 0x673cc, not a running tick. Sequence is:

```
T+0ms:  ctr = 0                        (ARM released)
T+2ms:  ctr = 0x58c8c                  (intermediate write)
T+12ms: ctr = 0x43b1 + console init    (fn 0x673cc stores static; firmware
                                        hangs at this exact point)
T+12ms onward: nothing changes         (sharedram never writes)
```

Therefore:
- test.98 reading `*0x58f08 = 0` at T+200ms was taken ~188ms AFTER the real
  freeze. It is consistent with "hang is before D11 obj linkage" but DOES
  NOT pinpoint the hang to D11 init specifically.
- The proven hang location from earlier tests is
  `pciedngl_probe → 0x67358 → 0x670d8 → deep init`; the fn 0x16f60 / fn
  0x1624c chain was called-graph analysis, not execution evidence.
- Jumping straight to D11 BCMA wrapper reads is premature — we need better
  hang localisation first.

### test.99 plan — console ring + multi-timepoint pointer sampling

Goal: narrow the hang location using CHEAP, READ-ONLY probes before
committing to D11 BCMA wrapper reads (which add bus-ops scaffolding and
have a bigger blast radius if anything goes wrong).

Probes (stage0, all read-only BAR2 accesses):

1. **Console ring dump at T+400ms** (highest-signal probe).
   - Read 256 bytes of TCM starting at the console-text base. Decode as ASCII
     to text on the host side (skip unprintable bytes). If firmware printed
     an ASSERT, a function-entry trace, or any identifiable string past
     "pciedngl_probe called", hang location narrows to that call.
   - Base address: locate via `console_ptr[0x9cc5c]` — when firmware is
     running this holds a TCM pointer (e.g. 0x8009ccbe → text at 0x9ccbe).
     Walk back from there to the ring start if needed. (Test.94 already
     identified 0x9CCC0–0x9CDD8 as decoded console strings.)

2. **Multi-timepoint TCM-pointer sampling** at T+20ms, T+200ms, T+400ms,
   T+800ms (T+20ms is the first sample AFTER firmware freezes):
   - `*0x9d000` — the 0x43b1 static (sanity check freeze detection works).
   - `*0x58f08` — D11 obj `field0x18` (was 0 at T+200ms).
   - `*0x62ea8` — wait-struct pointer (was garbage/uninit in test.97).
   - `*0x62a14` — global seen in fn 0x2208 analysis (used by
     `pciedngl_probe` path).
   - If all four are identical across all timepoints → firmware is hard-
     frozen after T+12ms and none of these globals got populated.
   - If any change at T+200/400/800 → firmware has SOME delayed execution
     path (e.g. interrupt-context code, DPC) we haven't accounted for.

3. **Sharedram + fw_init re-check** at the same timepoints (already in the
   existing T+200ms scan; extend to finer granularity).

Implementation notes:
- Reuse existing stage=0 dispatch in `brcmf_pcie_exit_download_state()`.
- `brcmf_pcie_read_ram32()` is the safe TCM read path — reuse, don't write.
- Keep the re-mask loop structure intact (defeats 3s periodic events).
- NO chip.c bus-ops, NO D11 BCMA wrapper reads yet — push that to test.100
  if console + pointer sampling don't narrow the hang.

After test.99 reading:
- If console shows a text past "pciedngl_probe called" → hang is later than
  currently thought; analyse the printed text for the failing subsystem.
- If console is frozen at "pciedngl_probe called" and pointers unchanged →
  hang is in pciedngl_probe BEFORE any subsystem logs → proceed to test.100
  with D11 BCMA wrapper reads (Path B step 1).
- If pointers change between T+20 and T+800 → delayed code path exists;
  characterise which pointer moves and when.

### Files modified / state snapshot
- `PLAN.md` — refactored to phase-level view; Current Status updated for test.98.
- `phase5/notes/phase5_progress.md` — Path B section added; current state block
  updated with test.98 result.
- `phase5/logs/test.98.journal` — full kernel log for test.98 run (NEW).
- `phase5/logs/test.98.stage0.partial` — partial stage0 log (header only before
  the 23:02 shutdown; kept for provenance, not for analysis).
- `phase5/logs/test.97.stage0` — restored to pre-test.98 clean state.
- `phase5/work/drivers/.../pcie.c` — still has test.98 probes (pointer-chain
  reads). Needs rewrite for test.99 D11 wrapper reads before next run.
- `phase5/work/test-staged-reset.sh` — still labelled test.97. Needs update to
  test.99 labels + LOG filename before next run.

## test.96 RESULT: CRASHED after 6 words — HANG CONFIRMED at fn 0x1624c via binary analysis

**test.96 ran in boot -1. CRASHED after only 6 code words (0x5200-0x5214). No RP restore.**
**PIVOT: Used firmware binary directly — 6 TCM words matched binary exactly → binary == TCM image.**

**fn 0x5250 disassembled from binary = nvram_get() — NOT the hang:**
```
5250: push {r4, r5, r6, lr}
5252: r4 = r0 (NVRAM buffer), r6 = r1 (key string)
5256: cmp r1, #0; beq 0x529c     ; if key==NULL, return NULL
525c: bl 0x82e                   ; strlen(key) → r5
5292: r0 = r6; b.w 0x87d4        ; tail call → another nvram lookup
```
Simple NVRAM key string lookup. NOT a hardware polling loop. NOT the hang.

**Vtable data found in firmware binary:**
```
PCIe2 vtable (at 0x58c9c):
  [0x58c9c] = 0x1e91 → fn 0x1E90 (vtable[0])
  [0x58ca0] = 0x1c75 → fn 0x1C74 (vtable[1]) ← CALL 2

D11 vtable (at 0x58f1c):
  [0x58f1c] = 0x67615 → fn 0x67614 (vtable[0])
  [0x58f20] = 0x11649 → fn 0x11648 (vtable[1]) ← CALL 3
```

**fn 0x1C74 (Call 2 = PCIe2_obj->vtable[1]) — NOT the hang:**
```
1c74: push {r4, lr}
1c76: r4 = [r0, #24]     ; load sub-object
1c7c: bl 0xa30            ; printf
1c80: r3 = [r4, #24]     ; nested struct
1c86: r2 = [r3, #36]; r2 |= 0x100; [r3, #36] = r2  ; set bit 8
1c8c: pop {r4, pc}        ; return
```
Trivial: sets bit 8 in BSS struct field, returns 0. NOT the hang.

**fn 0x11648 (Call 3 = D11_obj->vtable[1]) → leads to hang:**
```
1166e: r0 = [r4, #8]
11670: bl 0x18ffc        ← D11 init → eventually hangs
1167e: bl 0x1429c        ; stub returning 0
11682: pop {r2, r3, r4, pc}
```

**fn 0x18ffc (D11 init, called from Call 3) → hang chain:**
```
19024: ldrb r5, [r4, #0xac]  ; init flag
19028: cbz r5, 0x1904e        ; if flag==0: full init path
1904e: bl 0x16f60             ← FIRST D11 SETUP CALL (if first-time init)
19054: bl 0x14bf8
...
1908e: bl 0x17ed4             ; (this fn sets field0xac=1 — marks init done)
```
Flag at [r4+0xac] is 0 on first call → takes full init path starting at 0x16f60.
fn 0x17ed4 (sets init flag) is NEVER REACHED because hang happens before it.

**fn 0x16f60 (first D11 setup) → calls PHY read/write loop:**
- Copies 5 PHY register offsets from 0x4aff8: {0x005e, 0x0060, 0x0062, 0x0078, 0x00d4}
- Runs 5-iteration loop calling fn 0x16476 (PHY read) then fn 0x16d00 (PHY write)
- fn 0x16476: `mov.w r2, #0x10000; b.w 0x1624c` → enters wait loop

**fn 0x1624c = CONFIRMED HANG LOCATION (hardware PHY completion wait loop):**
```
1624c: push {r3, r4, r5, lr}
1624e: r5 = *(0x16298) = 0x62ea8  ; global wait-struct pointer

[SETUP:]
16252: r3 = *0x62ea8               ; wait struct ptr
16258: r3->field24 = 1             ; set "in progress"
1625c: r3->field28 = 0             ; clear completion flag
1625e: b.n 0x16286

[WAIT CHECK LOOP:]
16286: r3 = *0x62ea8
16288: r2 = r3->field20            ; status flag
1628a: cmp r2, #1
1628c: bne → EXIT                  ; if field20 != 1: exit (cancelled)
1628e: r3 = r3->field28            ; completion flag
16290: cmp r3, #0
16292: beq → LOOP (0x16286)        ; if field28==0: keep waiting ← INFINITE LOOP HERE
16294: pop {r3, r4, r5, pc}        ; return when field28 != 0
```
**HANGS WHILE: field20==1 AND field28==0**
**EXIT WHEN: field20!=1 (cancelled) OR field28!=0 (D11 PHY operation complete)**
This is a semaphore/event wait. field28 must be set by D11 PHY completion ISR.
**If D11 ISR never fires → field28 stays 0 → infinite loop.**

Root cause: D11 core not powered/clocked, or its interrupt not routed, so ISR never fires.
Global 0x62ea8 is a wait-struct used by 40+ locations in firmware.

Log: phase5/logs/test.96.journal (only 6 code words captured before crash)

## test.94 RESULT: SURVIVED (vtable read), CRASHED in STACK-LOW at word 154

**test.94 ran in boot -1. Module survived vtable dump, crashed at word 154/192 of STACK-LOW.**
**VTABLE: VT[0x58cf4] = 0x1FC3 → hang function is at 0x1FC2 (Thumb). CONFIRMED.**

**Key findings from VTABLE dump (0x58CD0-0x58D40):**
- VT[0x58cd4] = 0x00058c9c (nested vtable/struct ptr)
- VT[0x58cd8] = 0x00004999 (function at 0x4998)
- VT[0x58cdc] = 0x0009664c (BSS data ptr)
- **VT[0x58cf4] = 0x00001FC3** → Call 1 function (blx r3 at 0x644dc) = 0x1FC2 (Thumb) ← HANG CANDIDATE
- VT[0x58cf8] = 0x00001FB5 → vtable[+8] fn at 0x1FB4
- VT[0x58cfc] = 0x00001F79 → vtable[+12] fn at 0x1F78
- VT[0x58d24] = 0x00000001, VT[0x58d28..0x58d3c] = small fn pointers (0x4167C-0x416E3)

**Disassembly of 0x1FC2 (from arm-none-eabi-objdump on test.87 bytes):**
```
1fc2:  mov  r2, r1
1fc4:  ldr  r1, [r0, #24]  ; r1 = obj->si_ptr (field+0x18)
1fc6:  mov  r3, r0          ; r3 = obj
1fc8:  ldr  r0, [r1, #20]  ; r0 = si_ptr->dev (field+0x14)
1fca:  mov  r1, r3          ; r1 = obj (restore)
1fcc:  b.w  0x2208          ; TAIL CALL → 0x2208
```
→ 0x1FC2 is a TRAMPOLINE, not the actual hang. Rearranges args and tail calls to 0x2208.

**0x1FB4 (vtable[+8]):** identical trampoline → b.w 0x235C
**0x1F78 (vtable[+12]):** real function, calls 0x2E70 and 0x7DC4

**Analysis of 0x2208 (the REAL init function):**
```
push.w {r0,r1,r4,r5,r6,r7,r8,lr}   ; 8 regs = 32 bytes stack frame
r7 = *0x232C = 0x00062A14           ; global state ptr
r4=arg0(obj), r6=arg1, r5=arg2
r3 = *0x62A14 = 0x58CF0             ; vtable/state ptr (from test.93)
if (r3 & 2): optional debug print
if r6==0 || r5==0: error path
...
r8 = 0
bl 0x1FD0           ; allocate 76-byte struct (malloc via 0x7D60)
obj->field12 = result
if (alloc failed): error path
r0 = *0x62A14 & 0x10                ; 0x58CF0 & 0x10 = 0x10 (SET!)
if bit4 NOT set: return early (0x231C)
r1 = *0x2350 (timer priority value)
r0 = 0
bl 0x5250           ; register timer/callback
if (r0 == 0): success path:
    r0 = *0x237c = 0x00000000 (NULL!)
    r6 = 0
    b.w 0x848       ; TAIL CALL → 0x848 = strcmp (C library, NOT hang — CONFIRMED test.95)
```

**0x1FD0 (struct constructor called by 0x2208):**
- mallocs 76 bytes via 0x7D60
- memsets to 0 via 0x91C
- field52 = 0x740 = 1856, field60 = 0x3E8 = 1000, field64 = 28, field68 = 12, field72 = 4
- These look like timer/retry parameters (period_ms, timeout_ms, max_retry)

**STACK-LOW findings (0x9C400-0x9CDFC, crashed at 0x9CDFC):**
- 0x9C400-0x9CC54: ALL STAK fill (0x5354414b) — 0x1454 bytes = 5.2KB unused
- 0x9CC58-0x9CDFC: console ring buffer + BSS data (NOT stack frames)
  - 0x9CC5C = console write ptr (0x8009CCBE)
  - 0x9CCC0-0x9CDD8 = decoded console strings
  - 0x9CC88 = 0x000475B5 (ODD → Thumb fn ptr at 0x475B4 in struct)
- Stack frames NOT yet read (need 0x9CE00-0x9D000 or higher)
- Crash at ~3.25s total (exceeding ~3s PCIe crash window)

## test.95 RESULT: CLEAN EXIT — 0x840-0xB40 ALL C RUNTIME LIBRARY

**test.95 ran in boot -2 (and boot -1). Both SURVIVED with "TIMEOUT — FW silent for 2s — clean exit".**
**CODE DUMP COMPLETE: 192 words at 0x840-0xB40 disassembled (test95_disasm.txt).**

**CRITICAL CORRECTION: 0x848 is NOT a hang site — it is the loop body of strcmp.**
The annotation "b.w 0x848 = likely actual hang location" was WRONG.

**Functions found in 0x840-0xB40:**
- 0x840-0x87a: `strcmp` — entry at 0x840 (b.n 0x848), loop at 0x842-0x856, exit at 0x858-0x87a
- 0x87c-0x916: `strtol`/`strtoul` — whitespace skip, sign handling, 0x prefix, base conversion
- 0x91c-0x968: `memset` — 4-byte aligned stores + byte tail
- 0x96a-0xa2e: `memcpy` — LDMIA/STMIA 32-byte blocks, `tbb` jump table
- 0xa30-0xaaa: console printf — 520-byte stack buffer, calls 0xfd8/0x7c8/0x5ac/0x1848
- 0xabc-0xafa: callback dispatcher — 5-entry loop, `blx r3` dispatch with flag masking
- 0xb04-0xb16: wrapper loading globals for 0xabc
- 0xb18-0xb3f: heap free — adjusts accounting, walks linked list

**0xa4c was wrongly annotated** — it is in the MIDDLE of console printf at 0xa30, not a cleanup fn.

**Call chain from 0x2208:**
  bl 0x5250 (timer/callback reg) → succeeds → b.w 0x848 (tail call into strcmp)
  strcmp completes in microseconds. HANG IS ELSEWHERE.

**si_attach disasm (test91_disasm.txt, 0x64400-0x64ab8):**
- Function at 0x644??-0x64536: contains 3 vtable dispatches
  - Call 1 (0x644dc): *(*(0x62a14)+4) — obj vtable ptr at offset 0 → vtable[1]
  - Call 2 (0x644fc): r6=0x58cc4, ldr r3,[r6,#16] → vtable ptr at obj+16 → vtable[1]  
  - Call 3 (0x6451a): r7=0x58ef0, ldr r3,[r7,#16] → vtable ptr at obj+16 → vtable[1]
- si_attach at 0x64590: EROM-parsing loop, calls 0x2704 (EROM parser) for each core

## test.97 RESULT: fn 0x1624c never ran — hang is earlier
(See full analysis in "Current state" section above. Journal: phase5/logs/test.97.journal)

## test.98 PLAN: Pointer-chain reads to confirm D11 bus hang at fn 0x16f7a

**Goal:** Walk pointer chain at T+200ms to find hw_base_ptr and determine if it's a hardware addr.
Chain: TCM[0x58f08] → +8 → +0x10 → +0x88 → check if ≥ 0x18000000.
Also: stack probe 0x9FE00-0x9FF00 for LR=0x19054 (fn0x18ffc→fn0x16f60) and LR=0x11674.

**Expected results:**
- If step4 >= 0x18000000 → D11 bus hang confirmed. Next: pre-enable D11 core.
- If step4 == 0 → hang even earlier; need to trace si_attach D11 core init.
- If step1 == 0 → D11_obj->field0x18 not set; si_attach didn't initialize D11 obj.

## Run test.98 (to be built):
  cd /home/kimptoc/bcm4360-re/phase5/work && make && sudo ./test-staged-reset.sh 0

## test.93 RESULT: SURVIVED (both runs) — vtable pointer decoded, stack top is NVRAM

**test.93 ran twice (boot -2 at 12:02, boot -1 at 12:10), BOTH SURVIVED.**
Both showed "TIMEOUT — FW silent for 2s — clean exit" and "RP settings restored".

**Key findings from D2 (DATA-62A14) dump:**
- D2[0x62a14] = 0x00058cf0 → vtable pointer for Call 1 (blx r3 at 0x644dc)
- Vtable is at TCM[0x58cf0]; entry [+4] = TCM[0x58cf4] = function pointer for Call 1
- D2[0x62994] = 0x18000000 (ChipCommon base — confirms si_t struct location)
- D2[0x62ab0] = 0x58680001 (chipcaps — matches si_t from console output)
- D2[0x62ad4] = 0x00004360 (chip_id = BCM4360 ✓)
- D2[0x62ad8] = 0x00000003 (chip_rev = 3 ✓)
- D2[0x62ae0] = 0x00009a4d (chipst ✓)

**Key findings from SK (STACK-TOP) dump [0x9F800-0xA000]:**
- 0x9FF1C–0xA0000: NVRAM data ("sromrev=11\0boardtype=0x0552\0boardrev=0x1101\0...")
- 0x9F800–0x9FF1B: random/uninitialized data — NO Thumb LR values in TCM code range
- CONCLUSION: 0x9F800–0xA000 is NOT active stack. Active frames are near STAK fill at 0x9C400.

**What remains unknown:**
- TCM[0x58cf4] = ??? (the actual function being called — not yet read)
- Stack LR values (to confirm call depth and which vtable call hangs)

Log: phase5/logs/test.93.journal

## test.92 RESULT: SURVIVED — STAK fill confirmed above 0x9BC00; EROM parser analyzed

**test.92 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**Stack dump 0x9BC00-0x9C400: ENTIRELY STAK (0x5354414b)**
- Active stack frames are ABOVE 0x9C400
- Stack grows down from 0xA0000; estimated SP ~0x9F800
  (860-byte zeroed struct in 0x670d8 frame + si_attach 60-byte frame + others)

**EROM parser function at 0x2704 (0x2600-0x2900 dumped):**
- Simple loop: loads EROM entries sequentially from TCM, returns when match found
- r1 = &ptr, r2 = mask (or 0), r3 = match value
- NO infinite loops, NO hardware register reads
- CANNOT be the hang location

**Function structure at 0x27ec (core registration, vtable call):**
- `blx r3` at 0x2816 calls a vtable function (potential hang candidate)
- But this is called by si_attach (0x64590) during core enumeration

**Key insight: Vtable calls are in a function BEFORE si_attach in TCM:**
- From test.91 dump (0x64400-0x6458c area):
  - `bl 0x63b38` with r1=0x83c → looks up PCIe2 core object → r6
  - `bl 0x63b38` with r1=0x812 → looks up D11/MAC core object → r7
  - If both found: three vtable calls follow:
    - Call 1 (0x644dc): via [0x62a14][4], args=(PCIe2_obj, D11_obj)
    - Call 2 (0x644fc): PCIe2_obj->vtable[1](), if Call 1 succeeds
    - Call 3 (0x6451a): D11_obj->vtable[1](), if Call 2 succeeds

**test.92 hypothesis: hang is in one of the three vtable calls (PCIe2 or D11 core init)**

Log: phase5/logs/test.92.journal
EROM disasm: phase5/analysis/test92_erom_disasm.txt

## test.90 RESULT: SURVIVED — 0x670d8 disassembled; 0x64590 is next hang candidate

**test.90 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**function 0x670d8 fully disassembled (1344 bytes, 0x66e00-0x67340):**
- Entry: `stmdb sp!, {r0-r9, sl, lr}` (pushes 12 registers)
- Loads 7 args (3 from regs r0/r1/r2/r3, 4 from stack [sp+48..+56])
- memset: zeroes 860 bytes (0x35c) from r4 (the init struct)
- Stores initial values into struct offsets
- Calls 0x66ef4 (tiny function: returns 1 always) — never hangs
- At 0x67156: `mov.w r9, #0x18000000` (ChipCommon base!)
- At 0x6715c: `ldr.w r1, [r9]` = reads ChipCommon chip_id register
- Extracts chip_id, numcores, etc. from register
- **At 0x67190: `bl 0x64590` — FIRST DEEP CALL, likely hang point**
  - Args: r0=struct_ptr, r1=0x18000000 (ChipCommon), r2=r7
  - This is likely `si_attach` or `si_create` (silicon backplane init)
- After return: checks [struct+0xd0] — if NULL, error exit
- If non-NULL: calls 0x66fc4 (function in our dump, enumerates cores)
  - 0x66fc4 loops through [struct+0xd0] cores calling 0x99ac, 0x9964
  - Returns 1 (success) after loop

**call chain established:**
- pciedngl_probe → 0x67358 → 0x672e4 (wrapper) → 0x670d8 → 0x64590

**0x64590 not in dump (below 0x66e00) — MUST DUMP NEXT**
**0x66fc4 analyzed: core-enumeration loop, returns 1 on success**

Disassembly: phase5/analysis/test90_disassembly.txt
Log: phase5/logs/test.90.journal

## test.89 RESULT: SURVIVED — 0x43b1 is STATIC constant (stored once, not incremented)

**test.89 ran in boot -1. Key findings from fast-sampling:**
1. T+0ms: ctr=0x00000000 (ARM just released)
2. T+2ms: ctr=0x00058c8c (CHANGED — firmware running, some intermediate value)
3. T+10ms: ctr=0x00058c8c (held for 8ms)
4. T+12ms: ctr=0x000043b1 AND cons=0x8009ccbe (BOTH changed simultaneously)
5. T+20ms+: ctr=0x000043b1 FROZEN, cons frozen, sharedram=0xffc70038 NEVER changes

**RESOLVED: 0x43b1 IS a static constant, NOT a counter**
- Function at 0x673cc returns MOVW R0, #0x43b1 → firmware stores it to 0x9d000
- Previous "WFI-disproof" based on frozen counter was INVALID for values at T+200ms
- BUT firmware IS genuinely hung: sharedram NEVER changes (even at 2s+)
  - PCI-CDC firmware WOULD write sharedram on successful init
  - Never changing = TRUE HANG, not WFI idle

**TIMELINE reconstructed:**
- T+0ms: ARM released, TCM[0x9d000]=0
- T+2ms: firmware stored 0x58c8c to 0x9d000 (some intermediate init value)
- T+10ms: still 0x58c8c (firmware executing init code)
- T+12ms: firmware stored 0x43b1 to 0x9d000 (function 0x673cc result) AND initialized console
- T+12ms+: EVERYTHING FROZEN — firmware hung at this exact point
  - Console write ptr = 0x8009ccbe = TCM[0x9ccbe] (same as all previous tests)
  - Last message = "pciedngl_probe called" (same as test.78-80 decode)
  - Hang occurs inside pciedngl_probe → 0x67358 (TARGET 1) → 0x670d8 (deep init)

**NEXT: disassemble 0x670d8** — the only unexamined function in the call chain
Log: phase5/logs/test.89.journal

## test.91 RESULT: CRASHED at word 431 — partial si_attach disassembly obtained

**Crash cause:** Unmasked 1280-word code dump loop; at ~7ms/word, 431 × 7ms ≈ 3s hit PCIe crash window.

**Partial disassembly (431 words, 0x64400-0x64ab8) — key findings:**
- **0x64590 (si_attach):** reads ChipCommon+0xfc = EROM pointer register
- Immediately branches to EROM parse loop, calls fn at **0x2704** (EROM entry reader)
- **Vtable dispatch calls at 0x644dc and 0x644fc** (`blx r3`) — these init individual backplane cores
  → Most likely hang points: one core's init fn reads backplane registers for a powered-off core

**Stack location corrected:** STAK marker at 0x9BF00 (from test.88) → active frames near 0x9BC00.

Log: phase5/logs/test.91.journal
Dump: phase5/analysis/test91_dump.txt (431 words: 0x64400-0x64ab8)

## test.88 RESULT: CRASHED cleanup — but all data obtained

**test.88 ran in boot -1 (also partial in boot -2). Key findings:**
1. All three call targets disassembled — NO infinite loops, CPSID, or WFI in any
2. TARGET 1 (0x67358): alloc + calls 0x670d8 (deep init) — most likely hang location
3. TARGET 2 (0x64248): struct allocator (0x4c bytes), returns — clean
4. TARGET 3 (0x63C24): registration function, returns 0 — clean
5. **CRITICAL: Function at 0x673cc returns constant 0x43b1** — same value as "frozen counter"
6. Stack scan 0x9F000-0x9FFF8: mostly zeros, no dense return address cluster
7. "STAK" marker at 0x9bf00 — stack region may be near 0x9c000
8. Counter: T+200ms=0x43b1 (RUNNING), T+400ms=FROZEN
9. CRASHED during cleanup (no RP restore messages)

Full disassembly: phase5/analysis/test88_disassembly.txt

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL → writing during init CRASHES ✗ (test.71/74)
- Firmware prints: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75-80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- select_core after firmware starts → CRASH ✗ (test.66/76 PCIe2, test.86 ARM CR4)
- Core switching after FW start CONFIRMED LETHAL across ALL core types ✗ (test.66/76/86)
- WFI theory DEAD: frozen counter = TRUE HANG, not WFI idle (WFI keeps timers running) ✗
  UPDATE: counter at 0x9d000 is STATIC value (not a counter) — set once to 0x43b1
  BUT: sharedram NEVER changes = firmware NEVER completes init = GENUINE HANG ✓
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- Counter freezes at 0x43b1 between T+200ms and T+400ms — hang is VERY early ✓ (test.87)
- TCM top = 0xA0000 (640KB), stack grows down from there ✓ (test.87 TCB)
- pciedngl_probe calls into 0x67358, 0x64248, 0x63C24 — hang is inside one of these ✓ (test.87 disasm)
- All 3 call targets have NO infinite loops, CPSID, or WFI ✓ (test.88 disasm)
- TARGET 1 (0x67358) calls 0x670d8 (deep init) — most likely hang location ✓ (test.88)
- 0x670d8 calls si_attach (0x64590) which dispatches vtable calls ✓ (test.90)
- si_attach vtable fn at 0x1FC2 = TRAMPOLINE → tail calls 0x2208 ✓ (test.94 disasm)
- 0x2208 allocates struct, calls 0x5250, then tail calls 0x848 ✓ (test.94 disasm)
- 0x848 = strcmp (C runtime), NOT the hang ✓ (test.95 disasm)
- fn 0x5250 = nvram_get() (NVRAM key lookup), NOT the hang ✓ (test.96 binary disasm)
- Call 2 (fn 0x1C74) = trivial bit-set, returns 0, NOT the hang ✓ (test.96 binary disasm)
- Call 3 (fn 0x11648) → fn 0x18ffc → fn 0x16f60 → fn 0x1624c = CONFIRMED HANG ✓ (test.96 binary analysis)
- fn 0x1624c = hardware PHY completion wait loop at global 0x62ea8 ✓
- Loop spins while (*0x62ea8)->field20==1 AND field28==0 ✓
- field28 set by D11 PHY ISR — ISR never fires → infinite loop ✓ (hypothesis)
- D11 PHY register offsets in loop: 0x005e, 0x0060, 0x0062, 0x0078, 0x00d4 (from 0x4aff8) ✓
- Firmware binary matches TCM image exactly (6 words verified) — safe for offline disassembly ✓
- fn 0x1624c NEVER RAN at T+200ms — wait struct fields all garbage (uninitialized) ✓ (test.97)
- fn 0x16476 tail-calls fn 0x162fc (NOT fn 0x1624c) ✓ (corrected from binary)
- fn 0x16f60 @ 0x16f7a does hardware read BEFORE calling fn 0x16476 — AHB hang candidate ✓
- Stack frames are near 0x9FE40 (not 0x9CE00 which is console ring buffer) ✓ (test.97)

## Console text decoded (test.78/79/80/82/83/84 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (static value, set once at T+12ms then firmware freezes)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.95.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.85: CRASHED T+18-20s — STATUS/DevSta cleared, firmware STILL hung; STATUS theory DEAD
- test.86: CRASHED T+2s — ARM core switch (select_core) crashed immediately; core switch LETHAL
- test.87: SURVIVED — counter froze T+200-400ms at 0x43b1; pciedngl_probe disassembled; code dumps obtained
- test.88: CRASHED cleanup — all 3 targets disassembled; NO loops/CPSID/WFI; 0x673cc returns 0x43b1 constant; 0x670d8 is next suspect
- test.89: SURVIVED — 0x43b1 is STATIC (stored once at T+12ms); WFI-disproof RESOLVED; sharedram confirms TRUE HANG
- test.90: SURVIVED — 0x670d8 fully disassembled; calls si_attach (0x64590) at 0x67190; NO loops
- test.91: CRASHED at word 431 — partial si_attach (0x64590) dump; vtable dispatch at 0x644dc
- test.92: SURVIVED — STAK extends 0x9BC00-0x9C400; EROM parser at 0x2704 is benign
- test.93: SURVIVED (×2) — D2[0x62a14]=0x58CF0 (vtable ptr); sk[0x9F800]=NVRAM (not stack)
- test.94: SURVIVED vtable, CRASHED STACK-LOW at ~3.25s — VT[0x58cf4]=0x1FC3; 0x1FC2→0x2208→0x848
- test.95: SURVIVED — 0x840-0xB40 = C runtime (strcmp, strtol, memset, memcpy, printf); 0x848 = strcmp NOT hang
- test.96: CRASHED after 6 words — pivoted to firmware binary analysis; fn 0x1624c confirmed as hang location
- test.97: CRASHED (machine crash) — wait struct fields = garbage → fn 0x1624c never ran; hang is earlier; corrected: fn 0x16476 → fn 0x162fc (not fn 0x1624c directly)

## POST-test.109 (2026-04-17) — probe wedges BEFORE enum block executes

### Result: skip_arm=1, reached "rambase=0x0 ramsize=0xa0000 ... fw_size=442233" then STOP
Log `phase5/logs/test.109.stage0` shows driver path through `brcmf_pcie_reset_device`
(EFI state, PMU, pllcontrol[0..5], test.40 watchdog msg all present — lines 72-80
of log) and `brcmf_fw_alloc_request` + firmware file resolution (line 81-85),
but NOTHING after the `rambase=` debug line. System crashed after "Capture
complete" — no test.101 pre-ARM baseline, no test.109 enum lines, no skip_arm
message, no "Cleaning up brcmfmac".

### Root cause (advisor-confirmed)
Probe thread wedges in `brcmf_pcie_copy_mem_todev` at pcie.c line ~1803, which
writes the 442KB firmware via ~110K iowrite32 calls. ONE posted write that never
completes wedges the probe thread indefinitely.

All downstream code in `brcmf_pcie_download_fw_nvram` is unreachable, including:
- "NVRAM loaded" log (test.108 reached this; test.109 did not)
- test.101 pre-ARM baseline (dev_emerg at line 1883)
- test.109 enum block (lines 1890-1929)
- bcm4360_skip_arm branch (line 1932)

Verified NOT a dmesg-timing artifact by comparison with `journalctl -b -1` which
also stops at same point.

### test.110 plan — move enum to brcmf_pcie_reset_device (pre-FW-download site)
Reset_device already ran successfully in test.109 (EFI/PMU/pllcontrol lines
captured in log). Inserting the 11-slot enum there after the "test.40: allowing
watchdog reset" log line runs the enum BEFORE copy_mem_todev, so the wedge
cannot block it.

Code change (pcie.c):
- ADD: 11-slot enum block inside reset_device's BCM4360 branch, after
  "test.40: allowing watchdog reset" dev_info, before fall-through
- REMOVE: old enum block in download_fw_nvram (unreachable)
- bcm4360_skip_arm=1 retained as safety (unrelated path, avoids ARM release)

Build verified (pcie.c compiles, brcmfmac.ko linked). Ready to run.

### Test run
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected output (stage 0 log):
- EFI state / PMU / pllcontrol lines (same as test.109)
- NEW: "BCM4360 test.110: backplane core enumeration (slot+0 only, 11 slots)"
- NEW: 11 lines "BCM4360 test.110: slot[0xNNNNNNNN] off0=0x........"
- NEW: "BCM4360 test.110: enum complete, BAR0 restored"
- Then probe continues into FW download → wedges at copy_mem_todev (expected)
- System should NOT crash; dmesg capture should include all enum lines

Success criteria: ≥11 enum lines present in dmesg ring buffer.
Failure mode: if system crashes at enum, BAR0 writes are dangerous pre-probe.

## POST-test.110 (2026-04-17) — HARD CRASH, pivot from raw BAR0 sweep

### Result: kernel panic / full host crash, zero log lines persisted
Log `phase5/logs/test.110.stage0` captured only pre-test lspci state; nothing
from the driver's probe path reached disk. Enum block in `brcmf_pcie_reset_device`
that performed an 11-slot raw BAR0 window sweep (`pci_write_config_dword` on
BRCMF_PCIE_BAR0_WINDOW for each slot base, then ioread32 at window+0) was the
trigger — one of those writes wedged the bus so hard the whole machine died
instantly, no journald flush, no kmsg tail.

### Root cause
Raw BAR0 window writes in a tight loop, before any of the driver's usual
serialization (spinlocks, msleep barriers) hit unmapped / uninitialized /
powered-down backplane ranges. Even touching unassigned wrappers on BCMA
SOCI_SB can trigger a bus hang that SERR's the root port. We already saw
related fragility in tests 66/76/86 (post-ARM select_core = lethal); a
pre-ARM raw sweep of slot bases is the same class of hazard with more reads.

### Pivot (test.111)
By the time `brcmf_pcie_reset_device` runs, `brcmf_chip_recognition` has
already populated `ci->cores` (chip.c:1043-1049). We can walk that list
instead of touching MMIO — `brcmf_chip_get_core(ci, coreid)` returns the
registered core struct with id/base/rev. Zero new MMIO, zero hang risk.

## POST-test.111 (2026-04-17) — FW HANG TARGET IDENTIFIED

### Result: clean enum, FW hang target = d11 MAC @ 0x18001000
Log `phase5/logs/test.111.stage0` shows:
```
BCM4360 test.111: id=0x800 CHIPCOMMON   base=0x18000000 rev=43
BCM4360 test.111: id=0x812 80211        base=0x18001000 rev=42  <<< FW HANG TARGET
BCM4360 test.111: id=0x83C PCIE2        base=0x18003000 rev=1
BCM4360 test.111: id=0x83E ARM_CR4      base=0x18002000 rev=2
(INTERNAL_MEM, PMU, ARM_CM3, GCI, DEFAULT all NOT PRESENT)
```
Combined with test.106 evidence (fn 0x1415c spin-polls `*0x180011e0` in FW),
the hang is FW polling d11 MAC core's **clk_ctl_st register** (d11+0x1e0) for
CCS_BP_ON_HT (bit 19) which never sets because HT clock / BBPLL is off.

### Register semantics (from include/chipcommon.h and brcmsmac/aiutils.h)
- offset 0x1e0 = `clk_ctl_st`
- bit 1  = CCS_FORCEHT (driver/FW requests HT clock)
- bit 17 = CCS_HAVEHT (HT clock available)
- bit 18 = CCS_BP_ON_ALP (backplane running on ALP)
- bit 19 = CCS_BP_ON_HT (backplane running on HT) ← FW polls this

Same register layout exists on every core's wrapper; ChipCommon and d11 both
expose clk_ctl_st at +0x1e0. FW's choice to poll d11's copy (not CC's) means
the FW sees its core's clock view, not the chip-global view. But PMU grants
affect the whole backplane.

## Phase 5 CLOSED (2026-04-17)

Chain of evidence now complete:
1. test.87-96:  FW hangs inside pciedngl_probe → si_attach → ... → fn 0x1624c
2. test.106:    offline disasm — fn 0x1415c spin-polls `*0x180011e0`
3. test.111:    0x18001000 = d11 MAC core (BCMA_CORE_80211 id=0x812, rev=42)
4. d11+0x1e0 = d11.clk_ctl_st; FW waits for CCS_BP_ON_HT
5. test.40 EFI dump: clk_ctl_st=0x00010040 → HAVEALP=1, HAVEHT=0, BP_ON_HT=0

EFI left BCM4360 on ALP clock (32MHz). FW needs HT clock (PLL lock) for d11
PHY. Phase 6 goal: make HT clock come up before FW starts. This is a PMU /
BBPLL bring-up problem, not a driver reset or FW-loader problem.

## POST-test.112 (2026-04-17) — CC FORCEHT set BP_ON_ALP, not HT

### Result: FORCEHT persisted on CC, but PMU did not grant HT
Log `phase5/logs/test.112.stage0` (line 92-94):
```
pre-force CC.clk_ctl_st=0x00010040 (HAVEALP=1 HAVEHT=0 BP_ON_HT=0)
wrote CCS_FORCEHT (bit 1) to CC.clk_ctl_st, polling for CCS_BP_ON_HT...
after 100×100us: clk_ctl_st=0x00050042 pmustatus=0x0000002a res_state=0x0000013b -- HT TIMEOUT
```
Delta: 0x00010040 → 0x00050042.
- bit 1 (CCS_FORCEHT) now set (written by us): good
- bit 18 (CCS_BP_ON_ALP) appeared: ALP still granted
- bit 17 (CCS_HAVEHT), bit 19 (CCS_BP_ON_HT): still 0
- pmustatus=0x2a, res_state=0x13b: UNCHANGED from EFI baseline

Reading: PMU accepted that CC wants ALP and left it there. PMU did not
interpret CC FORCEHT as a request for HT/BBPLL.

### Three candidate blockers (advisor-identified)
1. **Wrong core** — FW polls d11.clk_ctl_st, so CC FORCEHT may not
   propagate to d11. Test next: write FORCEHT to d11.clk_ctl_st directly.
2. **Resource mask ceiling** — max_res_mask=0x13f, min_res=0x13b,
   res_state=0x13b. Max-res only adds bit 2 (0x4), and nobody requests
   it. Likely not the blocker (min_res is), but max_res shotgun rules
   it in/out cheaply.
3. **pllcontrol unset** — pllcontrol[0]=0, pllcontrol[1]=0. EFI left
   BBPLL frequency config blank. No amount of FORCEHT will lock a PLL
   with no divider config.

Advisor reviewed pre-commit: test (c) (max_res shotgun) is almost certainly
going to fail — res_state=0x13b = min_res, and widening max_res doesn't
force a request. If steps (b) and (c) both fail, test.114 should widen
**min_res_mask** (e.g. set bit 2 or discover HT-related bits), not jump
straight to pllcontrol programming.

## PRE-test.113 (2026-04-17) — d11 FORCEHT + max_res discriminator

### Code change (pcie.c, brcmf_pcie_reset_device BCM4360 branch)
ADD new test.113 block AFTER the existing test.112 CC FORCEHT block:

Step (a): `brcmf_pcie_select_core(BCMA_CORE_80211)`, read `regs+0x1e0`
          → baseline d11.clk_ctl_st

Step (b): `brcmf_pcie_write_reg32(regs+0x1e0, baseline | 0x2)` — FORCEHT
          poll d11.clk_ctl_st for bit 19 (BP_ON_HT), 100×100us = 10ms
          switch to CC, read pmustatus/res_state/pllcontrol[0..5]
          → if HT up: theory 1 wins (d11 is right core)

Step (c): (if step b failed) save max_res, write max_res=0xFFFFFFFF
          poll CC.clk_ctl_st for bit 19, 100×100us = 10ms
          re-read pmustatus/res_state/pllcontrol[0..5]
          → if HT up: theory 2 wins (max_res was blocking)

Step (d): restore max_res_mask to saved value (do not leave wide open)

Safety:
- brcmf_pcie_select_core() is the same path driver uses elsewhere; NOT
  the raw BAR0 sweep that crashed test.110
- skip_arm=1 retained — FW not running, no write/read race at 0x180011e0
- Existing test.112 block LEFT IN PLACE — CC FORCEHT already showed no
  effect on PMU, so leaving it set doesn't interfere with d11 writes

### Expected outcomes
- Most likely: step (b) fails (d11 is just another wrapper, PMU indifferent)
  → step (c) runs → also fails (min_res not max_res is the ceiling)
  → test.114 = widen min_res_mask or program pllcontrol[0]/[1]
- Small chance: step (b) succeeds → "PMU needed FORCEHT from the core
  that will consume HT (d11)" → driver fix = add d11 FORCEHT to reset path
- Small chance: step (c) succeeds → max_res really was the ceiling →
  driver fix = widen max_res_mask before ARM release

pllcontrol re-reads (added per advisor): after each poll loop, re-read
pllcontrol[0..5]. If any transition from 0 to non-zero between baseline and
step (b)/(c), PMU did touch PLL config. If all stay at [0, 0, 0xc31,
0x133333, 0x06060c03, 0x000606] throughout, theory 3 (PLL programming
genuinely missing) is strongly confirmed.

### Run
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

### Success criteria
- No crash
- Log contains test.113 step-a baseline line
- Log contains test.113 step-b result (HT UP or rejected)
- If step (c) ran, log contains step-c result + step-d restore line
- Clean "test.113: complete" line
- Module cleanly removed (`rmmod brcmfmac` succeeds)

### Failure signatures
- Host crash during step (a) read at d11+0x1e0  → d11 wrapper is already
  hung or powered down; cannot force HT from that core. Implies max_res
  or pllcontrol as only remaining path.
- Host crash during step (c) max_res write        → writing 0xFFFFFFFF to
  max_res_mask while FORCEHT is active destabilizes PMU. Back off to
  specific bit probes instead of shotgun.
- Log stops mid-probe                              → a specific read/write
  hangs the bus; narrow down which step; retry with fewer probes.

---

## TEST.127 EXECUTION — 2026-04-19 (session restart, after crash recovery)

### Pre-test state
- Module rebuilt: Apr 19 00:07 (test.127 pcie.c markers in place)
- Build status: clean, no rebuild markers needed
- PCIe state: clean (MAbort-, CommClk+)
- test.126 crashed during insmod before any markers printed

### Hypothesis (test.127 stage0)
test.126 crashed during insmod before ANY test markers printed. Crash is likely:
- Before brcmf_pcie_probe is called (module load error)
- Or in probe entry before first pr_emerg marker (line ~3871)

test.127 adds pr_emerg markers at:
1. Start of brcmf_pcie_probe (after device ID check)
2. After devinfo kzalloc
3. After devinfo->pdev assignment

**Expected outcome:** markers will show exactly where the crash occurs.

### Running test.127 stage0
Command: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`


---

## TEST.127 EXECUTION PLAN (2026-04-19 session restart)

### State
- Module rebuilt Apr 19 00:07
- PCIe state clean
- test.126 crashed during insmod before any markers

### Hypothesis
Crash occurs before brcmf_pcie_probe starts or very early in probe entry,
before the first test marker at line ~3871.

### Markers added (pcie.c)
1. pr_emerg: Start of brcmf_pcie_probe (device ID check)
2. pr_emerg: After devinfo kzalloc
3. pr_emerg: After devinfo->pdev assignment

Expected: markers will show exactly where crash occurs.

### Test command
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

### Git status
M phase5/logs/test.126.stage0 (from prior test, now clean)

---

## SYSTEMATIC DEBUGGING — Session 2026-04-19 (after crash recovery)

### Evidence Summary
**Pattern:**
- test.109-114: Various diagnostic tests, test.114 completed stage0/stage1
- test.115+: ALL crash during insmod, before any probe markers  
- test.126/127: Still crashing at identical boundary (insmod → crash, no output)

**File sizes (bytes):** 
- Working tests (109, 111, 112, 114): >5000 bytes
- Crashing tests (115-127): ~3650 bytes (just preamble, nothing after "=== Loading brcmfmac...")

### Root Cause Investigation (Phase 1)

**Fact 1: Crash is in module load, not probe**
- insmod call in test script crashes system
- Probe markers at line 3836+ never execute
- No dmesg output captured (script didn't reach capture point)
- System appears to hard panic during insmod

**Fact 2: crash is not from unsafe d11.clk_ctl_st reads**
- unguarded ioread32(devinfo->regs + 0x1e0) at line 2752 is AFTER ARM release
- stage 0 has bcm4360_skip_arm=1, returns at line 1946 before ARM release
- Therefore test.67-107 code never executes in stage 0
- The crash is happening MUCH earlier than that code

**Fact 3: Stage 0 should be minimal and safe**
- SBR at probe entry (line 3879-3896)
- chip_attach via brcmf_chip_attach (line 3898)
- module param setup (line 3933-3949)
- SKIP_ARM=1 return at 1946

**Fact 4: Test.109 baseline was safe**
- test.109 committed "enum moved before skip_arm; skip_arm=1 to avoid crash"
- Commit e590e51 shows test.109 was the baseline for stage 0 safety
- test.115 onward ALL crash

### Search for Regression Between test.114 and test.115

Looking at commit history:
- test.114d (e731310): "skip watchdog write, add 3a discriminator marker"
- Post-test.114d crash message: "chip_attach MMIO dead, power cycle required"
- test.115 (2f3c12a): "remove resetcore from test.114b"
- But test.114b was stage1 (ARM released), test.115 stage0

### HYPOTHESIS: Module Binary Corruption or Build Issue

Since test.109 was safe and test.115+ ALL crash at identical point (before probe), possibility:
1. **Kernel module ABI mismatch** — kbuild/kernel changed, module can't load
2. **Linking failure** — module binary is corrupted or circular dependency
3. **Hardware state** — PCIe/IOMMU permanently corrupted from test.114d crash

### Next Steps (Phase 1 → Phase 2)
1. **Verify module binary is valid**
   - Check module dependencies: `modinfo ./brcmfmac.ko | grep depends`
   - Try loading on clean kernel boot
   - Compare binary size/symbols with test.109 baseline build

2. **Check for kernel/module ABI changes**
   - `uname -r` kernel version
   - Compare module compilation flags
   - Try rebuild with test.109 exact code: `git show e590e51:drivers/.../pcie.c > /tmp/pcie109.c`

3. **Establish Hardware Clean State**
   - Full power cycle (battery drain) if MMIO is corrupted
   - Current MMIO test: UR/I/O error in 6ms (fast, expected) ✓

### Immediate Action: Revert to test.109 Build

Safest fast path to understand crash:
```bash
git stash
git checkout e590e51
make -C phase5/work
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

If test.109 commit works → regression introduced test.110-114
If test.109 also crashes → hardware corruption from earlier crash

---

## DIAGNOSTIC: Fresh rebuild of current code (2026-04-19 post-crash)

### Hypothesis
Tests 116+ all crash during insmod before probe markers.
Fresh rebuild of current code to isolate:
1. Is it a stale module binary issue?
2. Is it a code regression since test.109?

### Current State
- Branch: main (e4a5097)
- Fresh rebuild completed successfully
- About to run: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`
- Expected: either the crash reproduces OR system recovers (no crash)

### test.127 RESULT: CRASHED during insmod (kernel panic) — system recovered via watchdog

**test.127 ran at 2026-04-19 00:54. Module crashed the kernel during insmod, before any probe output. System recovered cleanly.**

**Crash signature (same as test.116-126):**
- Log ends with: `=== Loading brcmfmac (bcm4360_reset_stage=0, bcm4360_skip_arm=1) ---`
- No `insmod returned rc=` output (script halted)
- No probe markers (test.114b code never ran)
- Kernel panic → automatic watchdog recovery

**Evidence the crash is in module load, not probe:**
- insmod call at line 121 of test-staged-reset.sh never returns
- Proof: script sets `set +e` at line 120 to capture RC, but never logs it
- If probe had run, dev_info lines from pcie.c would appear before the crash
- None appear → crash happens in module initialization, before probe entry

**Regression timeline (test.109 working → test.115+ crashing):**
- test.109 (commit e590e51): "enum moved before skip_arm; skip_arm=1 to avoid crash"
  + Baseline safe state, module loads cleanly
- test.110-114: Various diagnostic code added (core enum, d11 wrapper reads, d11 forceht)
- test.115 (commit 2f3c12a): "remove resetcore from test.114b — pure diagnostic control"
  + First crash observed
  + ALL subsequent tests (116-127) crash identically

**Key observation:**
- The code between test.109 and test.115 looks safe (mostly diagnostic reads)
- But the crash is happening BEFORE the probe function entry
- This means either:
  1. **Module initialization** (module_init or static initializers) has unsafe code
  2. **Kernel module ABI** changed (kbuild/kernel incompatibility)
  3. **Symbol resolution failure** causes a late kernel crash during insmod

**Symbol check needed:**
- Verify module dependencies haven't broken
- Confirm brcmutil, cfg80211 are present and compatible
- Check for unresolved symbols that could cause late-stage panic

### NEXT: Isolate the insmod crash

Phase 2a (Hypothesis: kernel module ABI corruption):
1. Check module symbol resolution: `modinfo ./brcmfmac.ko | grep depends`
2. Compare with test.109 baseline: git show e590e51:drivers/.../pcie.c | wc -l
3. If symbols OK → rebuild with test.109 exact code to confirm that works

If test.109 code runs cleanly → regression is in test.110-114 diffs.
If test.109 also crashes → module infrastructure broken (compile flags? kernel version?)

### Files to check
- phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c (line 1-100 for static init)
- Kbuild flags (CFLAGS, module dependencies)
- Compare test.109 binary size vs current binary (if binary bloat suggests symbol table corruption)

### Investigation Update — Crash Hidden from dmesg

**Observations:**
1. BCM4360 device present (lspci confirms 03:00.0)
2. probe() has pr_emerg markers at line 3838 (very early) — NOT LOGGED
3. Module dependencies resolve (cfg80211, brcmutil)
4. dmesg buffer contains no kernel panic / BUG / Oops messages
5. System recovers cleanly (watchdog resets)
6. **Crash signature:** insmod syscall never returns (blocked or hard panic)

**Key insight:** 
- If probe reached, line 3838 pr_emerg would appear (even in a panic)
- It doesn't appear → kernel panic is in pci_register_driver() BEFORE probe
- OR kernel crashes so hard (e.g., NULL deref in insmod itself) that dmesg is lost

**Binary state:** Module size 14MB (Apr 19 00:54), same as test.127 build
- modinfo shows correct dependencies
- Symbol table appears intact

### test.128 PLAN: Surgical diagnostics to isolate crash point

**Hypothesis:** Crash is in pci_register_driver, BEFORE probe is called. Goal: add early pr_emerg messages that survive panics to narrow the crash point.

**Changes made (pcie.c):**
- Line 4261: Added `pr_emerg("BCM4360 test.128: brcmf_pcie_register() entry\n");` at function entry
- Line 4263: Added `pr_emerg("BCM4360 test.128: calling pci_register_driver\n");` before pci_register_driver()
- Line ~3836: Added `pr_emerg("BCM4360 test.128: PROBE ENTRY\n");` at very start of probe function

**Expected results:**
- If "brcmf_pcie_register entry" appears → module init is running
- If "calling pci_register_driver" appears → about to register
- If "PROBE ENTRY" appears → probe was called before crash
- If nothing appears → crash in module init phase before pcie_register runs

**Build:** Use existing module binary if rebuild fails (source changes alone won't cause module load issue anyway)

**After test.128:**
- Match logged messages to crash point
- If "calling pci_register_driver" is last message → crash is in pci_register_driver internals
- If nothing → crash is earlier (module_init → brcmf_core_init → ...)
- If "PROBE ENTRY" appears → we have a new crash location to investigate

### MODULE BUILD STATUS

The module binary (14MB, compiled 2026-04-19 00:54) is a pre-compiled binary NOT rebuilt with the test.128 diagnostic additions. To test with the new pr_emerg markers, the module must be rebuilt.

**Build system:** NixOS/kbuild required. Attempted `make -C phase5/work` failed (no kernel Makefile in that directory). Full build likely requires:
- Kernel headers for 6.12.80
- kbuild environment (via nix-shell or similar NixOS tooling)
- KDIR or KERNELDIR pointing to kernel source

**Options:**
1. **Manual rebuild:** User should run `make -C phase5/work` or equivalent with proper kernel build environment (if previous session established one)
2. **Alternative approach:** Analyze crash WITHOUT rebuild by examining:
   - Binary diffs between test.109 and current (14MB vs prior size)
   - Kernel log from previous tests to find pattern
   - Code audit of test.109→current diffs for module-init-phase issues

**Code audit findings (from diff analysis):**
- test.114b: d11 wrapper reads are GUARDED (check IN_RESET before reading core register) — safe
- test.125/126: PCIE2 mailbox clear now returns early for BCM4360 — avoids known crash
- test.127/128: pr_emerg markers added to probe entry (needs rebuild to take effect)
- No suspicious static initializers or module_init changes found

**Hypothesis update:**
Since the crash happens BEFORE probe even prints its first message, and all code from test.109→current appears safe (diagnostic/read-only), the issue might be:
1. **Stale module cache** — kernel caching old version of .ko file
2. **Binary corruption** — 14MB module might have a corrupted section
3. **Hidden code path** — static initialization or symbol resolution in a code path we haven't examined

---

## CORRECTED ANALYSIS: test.127 Crash Location Found (2026-04-19 session)

### Key Finding: Previous-Boot Log Confirms Probe DID Run

The previous hypothesis "crash before probe entry" was WRONG. The test script does `dmesg -C` BEFORE insmod, so if the machine crashes during insmod, the shell never reaches the dmesg capture. This made it look like probe never ran.

Reading `journalctl -k -b -1` (previous boot log from test.127) shows:
```
brcmfmac: BCM4360 test.127: probe entry (vendor=14e4 device=43a0)
... (all probe steps run including chip_attach, buscore_reset bypass, chip_recognition)
brcmfmac 0000:03:00.0: BCM4360 test.120: before brcmf_fw_get_firmwares
```

The LAST line in the kernel log is "before brcmf_fw_get_firmwares". Machine hard-crashed (MCE/CTO — no BUG/Oops/panic message) immediately after calling `brcmf_fw_get_firmwares`.

### Crash Location: brcmf_pcie_setup async callback

`brcmf_fw_get_firmwares` calls `request_firmware_nowait` which fires the callback `brcmf_pcie_setup` asynchronously (but quickly, since firmware is cached). The callback's first MMIO-unsafe action is `brcmf_pcie_attach` which writes to PCIe2 core config registers.

**Likely cause:** PCIe2 core is in BCMA reset state. Writing to its config registers via the backplane window triggers a PCIe Completion Timeout (CTO) → Machine Check Exception → hard reboot.

### Next Step: Add markers to pinpoint exact crash line

PLAN: Add pr_emerg markers inside `brcmf_pcie_setup` and `brcmf_pcie_attach` to find exact line.

Markers needed:
1. `brcmf_pcie_setup` entry (line 3548)
2. Before `brcmf_pcie_attach(devinfo)` (line 3565)
3. Inside `brcmf_pcie_attach` (line 779), before each MMIO write

After markers → build → test stage 0 → read journalctl -k -b -1 → last marker = crash location.

### Test.128 HYPOTHESIS

Crash is in `brcmf_pcie_attach` → PCIe2 CONFIGADDR write (line 785 of pcie.c). If confirmed, fix is to skip that function for BCM4360 (BAR1 fix not needed; we use BAR2 for firmware download).

This is test.128.

---

## TEST.128 RESULTS — 2026-04-19 (session restart after crash)

Two test.128 runs captured from journal:

### Run A — Boot -2 (00:54, module WITHOUT test.128 pcie_attach markers)
Last BCM4360 marker: `BCM4360 test.120: before brcmf_fw_get_firmwares`
→ Crash is in async callback fired by `brcmf_fw_get_firmwares` (i.e., `brcmf_pcie_setup`)

### Run B — Boot -1 (07:40, module WITH test.128 pcie_attach markers)
Last BCM4360 marker: `BCM4360 test.120: bus wired and drvdata set`
→ Crash earlier than Run A; hardware state variance (worse PCIe state after Run A crash)
→ `brcmf_pcie_setup/brcmf_pcie_attach` markers never reached

### Analysis
- Run A (more informative) confirms crash is in the async `brcmf_pcie_setup` callback
- `brcmf_pcie_setup` immediately calls `brcmf_pcie_attach`
- `brcmf_pcie_attach` writes to PCIe2 CONFIGADDR via backplane window (BAR0)
- PCIe2 core is in BCMA reset at that point → CTO → MCE → hard reboot
- Run B crashed earlier due to cumulative hardware state degradation after Run A

### PCIe State (current)
- MAbort- on endpoint (03:00.0): clean
- MAbort+ in root port (00:1c.2) secondary status: dirty (from prior crash)
- CommClk- in LnkCtl (dirty per CLAUDE.md pre-test checklist)

### Test.128 Second Run Plan (test.128-run2)
Run existing test.128 module binary again (already has pcie_attach markers).
If hardware state permits, Run A behavior should repeat and we'll see:
```
BCM4360 test.128: brcmf_pcie_setup ENTRY
BCM4360 test.128: before brcmf_pcie_attach
BCM4360 test.128: brcmf_pcie_attach ENTRY
BCM4360 test.128: before select_core PCIE2
BCM4360 test.128: before write CONFIGADDR   ← likely last marker before crash
```

Command: `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`
Log: phase5/logs/test.128.stage0 (will overwrite)

### Test.129 Plan (implement fix)
Based on evidence from Run A + BCMA reset theory:
- Add BCM4360 early return in `brcmf_pcie_attach` before any MMIO
- The function sets PCIe Command register (bus master enable) via backplane — already set by kernel PCI subsystem via pci_enable_device()
- BCM4360 uses BAR2 for firmware download, so BAR1 config (purpose of pcie_attach) is unnecessary

Fix: In `brcmf_pcie_attach`, before `select_core`, add:
```c
if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
    pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
    return;
}
```

---

## POST-test.128 second run — 2026-04-19 (session restart after crash)

### Result: CRASHED EARLY (hardware state degradation)

Boot -1 (07:41-07:49) ran test.128 second run. Last markers in journal:
- `BCM4360 test.128: brcmf_pcie_register() entry`
- `BCM4360 test.128: calling pci_register_driver`
- `BCM4360 test.128: PROBE ENTRY`
- `BCM4360 test.127: probe entry`
- `BCM4360 test.127: devinfo allocated, before pdev assign`
- **NO** `BCM4360 test.127: devinfo->pdev assigned, before SBR`

Crash is after devinfo kzalloc but before devinfo->pdev = pdev. This is trivially safe code —
crash is almost certainly an asynchronous MCE/NMI from a pending PCIe completion timeout
queued from the previous crash firing during module load.

**Conclusion:** Hardware too degraded after two consecutive crashes for meaningful data.
Per failure signature plan: skip second run, proceed directly to test.129 fix.

**PCIe state (current boot 0):**
- Endpoint (03:00.0): MAbort- (clean), CommClk- (dirty)
- Root port (00:1c.2) secondary: MAbort+ (dirty)

---

## TEST.129 RESULT — 2026-04-19 (session restart after crash)

### PARTIAL SUCCESS: brcmf_pcie_attach bypass WORKED, crash moved forward

**Boot -1 journal (test.129 run) last markers:**
```
BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360
BCM4360 test.128: after brcmf_pcie_attach
```
(journal ends here — hard crash immediately after)

**Analysis:**
- The `brcmf_pcie_attach` bypass is confirmed working
- Next call in `brcmf_pcie_setup` after `brcmf_pcie_attach` is `brcmf_chip_get_raminfo`
- `brcmf_chip_get_raminfo` BCM4360 bypass would print markers — they didn't appear
- Crash occurred between "after brcmf_pcie_attach" and `brcmf_chip_get_raminfo` print
- OR crash is in `brcmf_pcie_enter_download_state` (called inside `brcmf_pcie_download_fw_nvram`)

**Root cause identified:**
`brcmf_pcie_enter_download_state` for BCM4360/43602:
1. Calls `brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4)` — changes BAR0 window
2. Calls `brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_ARMCR4REG_BANKIDX, 5)` — **CRASH**
   ARM_CR4 core is in BCMA reset → BAR0 MMIO write → PCIe CTO → MCE → hard crash

**PCIe state (current boot 0):**
- Endpoint (03:00.0): MAbort- (clean), CommClk+
- Root port (00:1c.2) secondary: MAbort- (clean)

---

## Current state (2026-04-19, PRE test.129 — bypass brcmf_pcie_attach for BCM4360)

### CODE STATE: brcmf_pcie_attach BYPASSED FOR BCM4360

**Evidence supporting bypass:**
- Run A (boot during session at 00:54): last marker `BCM4360 test.120: before brcmf_fw_get_firmwares`
  → crash is in async callback `brcmf_pcie_setup`, which immediately calls `brcmf_pcie_attach`
- `brcmf_pcie_attach` selects PCIe2 core and writes to CONFIGADDR via BAR0
- PCIe2 core is in BCMA reset at that point → CTO → MCE → hard crash

**Code change (pcie.c line ~783):**
Added at start of `brcmf_pcie_attach`, before any MMIO:
```c
if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
    pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
    return;
}
```

**Why safe to skip:**
- BCM4360 uses BAR2 for firmware download, not BAR1
- BAR1 window sizing (the purpose of brcmf_pcie_attach) is unnecessary for BCM4360
- BusMaster already enabled by kernel PCI subsystem via pci_enable_device()
- device_wakeup_enable can be skipped at this stage

**Hypothesis (test.129 stage0):**
- Probe continues through SBR, chip_attach, reset path, firmware download without crashing
- Should see `BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360` in journal
- Then probe continues further into firmware setup
- Possible next crash: in firmware download or OTP access (but more likely clean run)

**Build status:** BUILT — brcmfmac.ko compiled 2026-04-19 (test.129 bypass in place)

**Pre-test requirements:**
1. Build the module
2. Check PCIe state (MAbort+ root port secondary — may need clearing or power cycle)
3. Force runtime PM on if needed

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Success criteria:**
- Journal shows `BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360`
- Probe continues past brcmf_pcie_attach without crash
- Next crash point identified (or no crash — very unlikely but possible)

**Failure signatures:**
- Crash before bypass marker: hardware state too degraded, need power cycle
- Crash after bypass but before firmware download: different code path is the issue

---

## TEST.130 RESULT — 2026-04-19 (session restart after crash)

### EARLY CRASH: hardware state variance, not a code regression

**Boot -1 journal (test.130 run) last markers:**
```
BCM4360 test.125: buscore_reset entry, ci assigned
BCM4360 test.122: reset_device bypassed; probe-start SBR already completed
```
(journal ends here — hard crash immediately after, before "after reset_device return")

**Analysis:**
- The crash occurred between "reset_device bypassed" (printed at end of `brcmf_pcie_reset_device` before its return) and the next marker "after reset_device return" in `brcmf_pcie_buscore_reset`
- This is earlier than test.129 which reached "brcmf_pcie_attach bypassed" in the async callback
- The test.130 code changes (enter_download_state bypass, brcmf_pcie_setup markers) are all AFTER chip_attach — they cannot cause an earlier crash
- **Conclusion: hardware state variance** — sometimes the BCM4360 comes back from SBR in a worse state, causing chip_attach MMIO to crash before any more markers appear
- The "reset_device bypassed" message was the last message that got flushed to the persistent journal before the crash — later messages (including "skipping PCIE2 mailbox clear; returning 0") were likely lost

**PCIe state (current boot 0):**
- Endpoint (03:00.0): MAbort- (clean), CommClk+
- Root port (00:1c.2): MAbort- (clean), secondary=03, subordinate=03

**Action:** Re-run test.130 — code is correct, hardware is in clean state.

---

## PRE-TEST.130 RE-RUN (2026-04-19 session restart)

**STATE:** test.130 crashed on first run due to hardware variance. PCIe state is now clean.
- Endpoint MAbort-, CommClk+; root port MAbort-, secondary=03, subordinate=03
- Module built 2026-04-19 08:06 — test.130 bypasses in place (no rebuild needed)

**HYPOTHESIS (re-run):**
The first test.130 run was a hardware variance crash (chip_attach MMIO timing).
On this run, chip_attach should complete cleanly (same path as test.129 which succeeded).
Then the async callback brcmf_pcie_setup should fire and we should see:
1. "brcmf_pcie_setup ENTRY" (test.128 marker)
2. "before brcmf_pcie_attach" → "brcmf_pcie_attach bypassed for BCM4360" → "after brcmf_pcie_attach"
3. "before brcmf_chip_get_raminfo" → "after brcmf_chip_get_raminfo" (fixed BCM4360 values)
4. "after brcmf_pcie_adjust_ramsize"
5. "before brcmf_pcie_download_fw_nvram" → firmware written to BAR2 TCM → "after..."
6. Progress markers until next crash OR "after brcmf_pcie_request_irq"
Expected crash point: `brcmf_pcie_init_ringbuffers` (reads from firmware shared memory — requires firmware running)

**Run:** `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## Current state (2026-04-19, PRE test.130 — bypass brcmf_pcie_enter_download_state ARM_CR4 write)

### CODE STATE: brcmf_pcie_enter_download_state BYPASSED FOR BCM4360

**Evidence:**
- test.129 confirmed brcmf_pcie_attach bypass works
- Crash after "after brcmf_pcie_attach" — next dangerous BAR0 write is in `brcmf_pcie_enter_download_state`
- That function writes to ARM_CR4 core via BAR0 MMIO while ARM is in BCMA reset → CTO → MCE

**Code changes (pcie.c):**
1. In `brcmf_pcie_enter_download_state`: added BCM4360 early return before ARM_CR4 writes
2. Added markers throughout `brcmf_pcie_setup`:
   - before/after `brcmf_chip_get_raminfo`
   - after `brcmf_pcie_adjust_ramsize`
   - before/after `brcmf_pcie_download_fw_nvram`
   - before/after `brcmf_pcie_init_ringbuffers`
   - after `brcmf_pcie_init_scratchbuffers`
   - before `select_core PCIE2`
   - before/after `brcmf_pcie_request_irq`

**Why safe to skip:**
- bcm4360_skip_arm=1: ARM is never released in this stage, so bank protection setup is irrelevant
- The BANKIDX/BANKPDA writes only matter before ARM execution

**Hypothesis (test.130 stage0):**
- Should see `brcmf_pcie_enter_download_state bypassed for BCM4360` marker
- Firmware download proceeds (BAR2 MMIO writes to TCM) — should work since BAR2 is accessible
- Progress markers reveal how far we get before next crash (likely in ringbuffer init or PCIE2 select_core MMIO)

**Build status:** BUILT — brcmfmac.ko compiled 2026-04-19 (test.130 bypass in place)

**PCIe state (pre-test):**
- Endpoint (03:00.0): MAbort- (clean), CommClk+
- Root port (00:1c.2) secondary: MAbort- (clean)

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Success criteria:**
- Journal shows `brcmf_pcie_enter_download_state bypassed for BCM4360`
- Journal shows `before/after brcmf_pcie_download_fw_nvram`
- If no crash: journal shows `after brcmf_pcie_request_irq`

**Failure signatures:**
- Crash before download marker: different code path (unlikely)
- Crash in init_ringbuffers: need to check if firmware initialized shared memory
- Crash in select_core PCIE2: PCIE2 core still in BCMA reset and needs explicit reset sequence


---

## TEST SERIES 131–143 RESULTS — 2026-04-19 (retrospective documentation)

### Summary: ARM CR4 discovered running; halt attempts led to hardware degeneration

These tests progressively added diagnostic markers and attempted to solve the ARM CR4 async crash discovered in tests 127-130.

---

### TEST.131 — BAR0 stability probe added
**Code:** Added `BCM4360 test.131: BAR0 2nd probe = ... — stable` marker 50ms after first probe.
**Result:** Consistent `0x15034360` — chip ID stable post-SBR.

### TESTS 132-134 — Structural markers
- **test.132**: struct wiring / pci_pme_capable logging (wowl=1 confirmed)
- **test.133**: BusMaster cleared + ASPM disabled after chip_attach (LnkCtl before=0x0143 after=0x0140)
- **test.134**: post-attach fw-ptr-extract + kfree markers

All ran clean (probe reached async callback).

---

### TESTS 135-136 — Firmware path exploration
Tested various bypass/logging combinations. No new crashes; logs show full probe→async callback path completing up to `before brcmf_pcie_download_fw_nvram`.

---

### TEST.137 — KEY FINDING: ARM CR4 state logged after SBR

**Purpose:** Added ARM CR4 BCMA register read inside `enter_download_state` (before touching it), logging RESET_CTL and IOCTL state.

**Result (stream):**
```
BCM4360 test.137: ARM_CR4: RESET_CTL=0x0000 IN_RESET=NO IOCTL=0x0001 CPUHALT=NO CLK=YES
```

**Significance:** SBR does NOT leave ARM CR4 in reset. ARM is RUNNING immediately after SBR. IOCTL=0x0001 = CLK only (no CPUHALT). This confirms the root cause of all prior crashes: the ARM CR4 executes firmware during chip_attach and MMIO operations.

Stream was truncated here — crash during/after the RESET_CTL read, before the full log message could be printed.

---

### TEST.138 — ARM running confirmed; crash in enter_download_state

**Purpose:** Same code as test.137 (re-run on fresh boot).

**Result:** Crash during the ARM CR4 state read inside `enter_download_state`. Stream ended after `after RESET_CTL read = 0x0000`. ARM was running and crashed the host when BAR0 window was pointed at ARM CR4 core (0x18002000) and RESET_CTL was read.

**Conclusion:** ARM executing firmware = CTO when driver touches BCMA wrapper MMIO.

---

### TEST.139 — First ARM halt attempt (probe-time, RESET_CTL only)

**Purpose:** Added probe-time ARM halt in probe() after chip_attach: write RESET_CTL=1 to assert ARM in reset.

**Problem:** Code wrote RESET_CTL=1 WITHOUT first writing IOCTL=FGC|CLK. The correct BCMA halt sequence requires:
1. IOCTL |= CPUHALT|FGC|CLK (0x0023) first
2. Then RESET_CTL = 1

**Result:** Log shows crash before probe-time ARM halt code ran. Stream truncated before reaching that point.

---

### TEST.140 — ARM halt attempt with wrong BCMA sequence → WEDGED WRAPPER

**Purpose:** Re-run of test.139-style halt, this time with probe reaching the ARM halt block.

**Result (stream):**
```
BCM4360 test.140: probe-time ARM CR4 reset asserted RESET_CTL=0xffffffff IN_RESET=YES
```

**CRITICAL:** `RESET_CTL=0xffffffff` = all-ones = PCIe CTO response. Writing RESET_CTL=1 to the ARM CR4 wrapper WITHOUT first setting IOCTL=FGC|CLK caused a completion timeout. The BCMA wrapper is now **wedged** — subsequent reads return 0xffffffff.

**Root cause:** ARM was still running (CLK enabled) when RESET_CTL=1 was written. The proper BCMA sequence is IOCTL=CPUHALT|FGC|CLK first, which gates the clock to allow safe reset assertion.

---

### TEST.141 — Correct BCMA sequence, but wedged state from test.140

**Purpose:** Fixed BCMA sequence: write IOCTL=0x0023 first, then RESET_CTL=1. Code change is correct.

**Pre-test state:** MAbort+ on secondary bus, CommClk- — bad state inherited from test.140 wedge.

**Result (stream):** BLANK. Only stream header. Crash during PCIe enumeration (`pci_register_driver`), before probe() fired.

**Reason:** test.140 left the ARM CR4 BCMA wrapper in a wedged state. When pci_register_driver triggered PCIe enumeration and the system tried to access the device's config space, it generated CTO → MPC IRBNCE → hard crash.

---

### TEST.142 — Re-run with ARM CR4 base logging, same wedged state

**Purpose:** Added `ARM CR4 core->base=0x%08x` logging. Same fundamental code.

**Pre-test state:** MAbort+ confirmed in header — still degraded from test.140.

**Result (stream):**
```
BCM4360 test.128: brcmf_pcie_register() entry
BCM4360 test.128: calling pci_register_driver
pcieport 0000:00:1c.2: Enabling MPC IRBNCE
```

Crash during pci_register_driver PCIe enumeration — identical to test.141. ARM halt code in probe() never ran.

---

### TEST.143 — Re-run (same code as test.142)

**Purpose:** Attempt to confirm or break the test.142 pattern.

**Pre-test state:** MAbort+, CommClk- (persistent degraded state).

**Result:** Identical to test.142:
```
BCM4360 test.128: brcmf_pcie_register() entry
BCM4360 test.128: calling pci_register_driver
pcieport 0000:00:1c.2: Enabling MPC IRBNCE
```
Crash before probe. PCIe hierarchy lost: root port secondary=ff, subordinate=fe.

---

### ROOT CAUSE ANALYSIS — Hardware degeneration chain

```
test.139: ARM halt code didn't reach (crash before probe-time block)
test.140: ARM halt code ran, but used RESET_CTL=1 WITHOUT IOCTL=FGC|CLK first
          → BCMA wrapper wedged (RESET_CTL=0xffffffff = CTO response)
          → Hardware state: MAbort+, CommClk-
tests 141-143: Ran on wedged hardware
              → pci_register_driver triggers PCIe enumeration CTO
              → pcieport MPC IRBNCE, hard crash before probe() fires
```

The test.141/142/143 crashes are NOT caused by a code bug — the fixed BCMA sequence is correct. They are caused by the persistent wedged state from test.140 running on degraded hardware.

**On clean hardware (test.137/138)**: ARM running was problematic but didn't immediately crash during `pci_register_driver`. The crash came later (inside enter_download_state MMIO access with ARM running).

---

### CURRENT STATE — 2026-04-19 end of session

**PCIe state:** BROKEN. Root port secondary=ff, subordinate=fe. Module MUST NOT be loaded.

**Code state (test.142/143):**
- Correct BCMA halt sequence in probe(): IOCTL=0x0023 then RESET_CTL=1
- ARM CR4 base address logging present
- `brcmf_chip_get_core(BCMA_CORE_ARM_CR4)` used for base address

**Known ARM CR4 hardcoded base:** `0x18002000` (confirmed from test.111 log)

**Required action:** COLD REBOOT (full power cycle — warm reboot does NOT power-cycle BCM4360).

**Post-reboot plan:**
1. Check `lspci -s 00:1c.2` → verify secondary=03, subordinate=03 (hierarchy restored)
2. Check `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk'` → verify MAbort-, CommClk+
3. Run discriminator test (current code, unchanged): `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`
4. HYPOTHESIS: On clean hardware, probe() will reach ARM halt block; IOCTL=0x0023 + RESET_CTL=1 will halt ARM properly; downstream tests can proceed

**If discriminator passes (ARM halted cleanly):** Firmware download should proceed past enter_download_state without crash → next barrier is init_ringbuffers.

**If discriminator fails:** Implement pre-register ARM halt in `brcmf_pcie_register()` using pci_get_device() + hardcoded ARM CR4 base 0x18002000, BEFORE pci_register_driver call.

---

## PRE-TEST.144 — Post-cold-reboot discriminator test

**PURPOSE:** Confirm clean-boot behavior on test.142/143 code (correct BCMA ARM halt sequence).

**HYPOTHESIS:** On clean hardware with no inherited wedged state:
- probe() fires successfully
- ARM CR4 halt block executes: IOCTL=0x0023 then RESET_CTL=1
- RESET_CTL reads back 0x0001 (not 0xffffffff)
- ARM is halted; downstream MMIO proceeds without crash

**Pre-test checklist:**
- [ ] Cold reboot performed (full power cycle)
- [ ] `lspci -s 00:1c.2` shows secondary=03, subordinate=03
- [ ] `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk'` shows MAbort-, CommClk+
- [ ] No rebuild needed — test.142/143 code is the current module

**Test command:** `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`


---

## PRE-TEST.144 HARDWARE STATE — 2026-04-19 (post SMC reset)

**Context:** Cold reboot (power off/on) did NOT reset BCM4360 — secondary=ff survived because BCM4360 is on Apple standby rail. SMC reset (Shift+Ctrl+Option+Power 10s) was required to fully power-cycle the chip.

**Root port (00:1c.2):** secondary=03, subordinate=03, MAbort-, secondary-MAbort- ✓
**Endpoint (03:00.0):** MAbort- ✓, Mem+, BusMaster+, Region0=b0600000, Region2=b0400000 ✓
**IRBNCE:** Normal boot-time init messages only (all ports simultaneously at 20:54:09) ✓

**Hypothesis:** On clean hardware (ARM CR4 BCMA wrapper freshly reset by SMC), probe() will:
1. Execute SBR cleanly
2. chip_attach succeeds
3. ARM halt block runs: IOCTL=0x0023 then RESET_CTL=1
4. RESET_CTL reads back 0x0001 (not 0xffffffff)
5. ARM halted; downstream MMIO proceeds past enter_download_state without crash

**Note:** A normal cold reboot is insufficient for this hardware — need SMC reset if BCM4360 wrapper gets wedged.

---

## test.143 SECOND RUN RESULT (2026-04-19 20:56:07) — crash EVEN EARLIER (only 1 line captured)

**Context:** This run was done immediately after the PRE-test.144 SMC reset (clean hardware state).

**Stream log (test.143.stage0.stream — second run):**
- [120.778412] brcmfmac: loading out-of-tree module taints kernel.
- **CRASH** — "BCM4360 test.128: brcmf_pcie_register() entry" NEVER appeared

**Crash window:** Between kernel taint printk and first line of brcmf_pcie_register() — i.e.,
inside brcmfmac_module_init → brcmf_core_init → ... before brcmf_pcie_register() is called.

**CONCLUSION:** Even brcmf_pcie_register() is too late to place the ARM halt.
The ARM CR4 executed garbage during the module_init window, BEFORE pci_register_driver.
Must halt ARM at the very top of brcmfmac_module_init().

---

## Current state — 2026-04-19, PRE test.144 — early ARM halt in module_init

### CODE STATE: test.144 binary — NEEDS REBUILD ✓ (rebuilt at 21:xx BST)

**Hardware state (post-crash SMC reset by user):**
- PCIe endpoint 03:00.0: MAbort- (CLEAN) ✓
- Root port: secondary=03/03, MAbort- ✓

**test.144 change: brcmf_pcie_early_arm_halt() called as FIRST action in brcmfmac_module_init()**
- New function in pcie.c: uses pci_get_device(0x14e4, 0x43a0) + ioremap(BAR0, 0x2000)
- Sets BAR0_WINDOW (config[0x80]) = 0x18002000 (ARM CR4 base, from test.111)
- Writes IOCTL=0x0023 (FGC|CLK|CPUHALT) then RESET_CTL=0x0001
- Reads back both registers for diagnostic logging
- Called from brcmfmac_module_init() before platform_driver_probe, before brcmf_core_init
- ARM halted BEFORE pci_register_driver is ever called

**Hypothesis (test.144):**
- ARM halted in module_init → probe() survives → chip_attach succeeds
- "BCM4360 test.144: early ARM halt done: IOCTL=0x00000023 RESET_CTL=0x00000001 IN_RESET=YES" appears
- "BCM4360 test.128: PROBE ENTRY" appears
- Probe-time ARM reset block also fires (re-asserts IOCTL=0x0023, RESET_CTL=1) — harmless
- enter_download_state runs without crash

**Interpretation matrix (test.144):**
- "early ARM halt done: IN_RESET=YES" + "PROBE ENTRY" appears → SUCCESS; proceed to next test
- "early ARM halt done: IN_RESET=NO/WEDGED" → IOCTL sequencing wrong; investigate
- "BCM4360 test.144: BCM4360 not found" → pci_get_device failed (unexpected)
- "early ARM halt" never appears → crash even before module_init first line (very unlikely)
- Early halt succeeds but probe() still crashes → different crash cause; analyze

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

---

## TESTS 145–165 — retrospective summary (2026-04-19 → 2026-04-20)

Git log is the primary record from test.144 onward. Key inflection points:

- **test.145–152** — probe-time ARM halt integrated into buscore_reset (after 2nd SBR);
  discriminator series to prove probe entry is safe.
- **test.152–154** — early-return discriminators at probe entry / after SBR / after
  chip_attach: all SUCCESS.
- **test.155–158** — fw_get_firmwares / duplicate-halt crash isolation. test.158
  SUCCESS: removing the *duplicate* ARM halt was the sole crash trigger; single
  buscore_reset halt is correct.
- **test.159–162** — progressive slicing of setup callback up to adjust_ramsize;
  all SUCCESS (no HW touch past raminfo).
- **test.163** — first `brcmf_pcie_download_fw_nvram` attempt via stock
  `copy_mem_todev` (442KB BAR2 TCM write). **Hard crash → machine reboot.**
- **test.164** — replaced with inline iowrite32 loop, breadcrumb every 16KB,
  mdelay(50) between. Reached 425984 / 442233 bytes; crashed in final 16KB
  window. No MCE/CTO logged → silent machine freeze.
- **test.165** — tightened breadcrumb to 1KB, mdelay(20) between. Reached
  340992 / 442233 bytes (333 KB of 432 KB); crashed in next 1KB window.

### Key observation (test.164 vs test.165)

Crashes occur at DIFFERENT byte offsets under different timing:
- test.164 (16KB/50ms): 425984 bytes written before freeze
- test.165 (1KB/20ms):  340992 bytes written before freeze

Same iowrite32 loop, same BAR2 target, same firmware data — just different
printk/mdelay cadence. The crash is NOT tied to a specific byte offset.

Elapsed fw-write wall-clock (test.165): 10:42:44 → 10:42:53 = 9 s for 341 KB.
Cumulative mdelay alone was ~333 × 20 ms = 6.66 s. So more breadcrumbs →
slower write → earlier crash by byte count.

### Working hypothesis

Something ASYNCHRONOUS (wall-clock-based) tears down the link during the
BAR2 fw download. Candidates:

1. **ARM CR4 auto-resume** — test.145 halt may not be sticky; ARM could be
   re-armed by a clock/reset re-assertion in later probe flow and start
   executing stale TCM as host overwrites it.
2. **PCIe link power management** — ASPM / L1 entry mid-download causing
   malformed TLPs and CTO. Test.133 cleared BusMaster and disabled ASPM on
   the endpoint, but the root port may still be negotiating L1 state.
3. **Firmware/hardware watchdog** — some hidden counter in the BCMA wrapper
   fires after N ms and pulls the link down.
4. **Printk storm consequences** — unlikely: we'd see a kernel panic in
   the journal, not a silent freeze.

### HW state (post-crash, 2026-04-20 11:00)

- lspci 03:00.0: MAbort- **CLEAN** (no SMC reset needed) ✓
- Root port 00:1c.2: hierarchy visible
- Kernel journal from previous boot captured → `phase5/logs/test.165.journalctl.txt`

### PRE-TEST.166 PLAN — confirm ARM is halted during fw write

Goal: discriminate async-watchdog vs ARM-resume.

**Proposed code changes:**
1. Immediately before the BAR2 fw-write loop in
   `brcmf_pcie_download_fw_nvram`, re-assert ARM CR4 halt
   (IOCTL=0x23, RESET_CTL=1) via BAR0 window switch to ARM_CR4 base
   (0x18002000). Read back RESET_CTL — log `test.166: pre-write RESET_CTL=...`.
2. Use test.164-style 16KB breadcrumbs (less async time between writes).
3. After the write loop (and before the "fw write complete" marker), read
   RESET_CTL again — log `test.166: post-write RESET_CTL=...`.
4. Restore BAR0 window to ChipCommon afterwards.

**Interpretation matrix (test.166):**
- pre-write RESET_CTL=0x0001 (halted) + fw write completes → SUCCESS;
  hypothesis: need to keep ARM halted; next test attempts full probe-up path.
- pre-write RESET_CTL=0x0000 (running) → ARM auto-resumed before fw write
  even though test.145 halted it in buscore_reset. Fix: re-halt here.
- pre-write=halted + crash mid-write, post-write never appears → either
  ARM resumed silently during write, OR async watchdog (ASPM/firmware timer).
- pre-write=halted + crash near same offset as test.164 → watchdog more likely.

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Module rebuild required** — `make -C /home/kimptoc/bcm4360-re/phase5/work`
before running.

---

## TEST.170 RESULT — 2026-04-20 13:54 (BREAKTHROUGH on fw-write, crash moves downstream)

### Captured evidence
- Log: `phase5/logs/test.170.journalctl.txt` (1186 lines, previous boot)
- Stage0: `phase5/logs/test.170.stage0`
- Stream: `phase5/logs/test.170.stage0.stream` (post-crash boot only — machine hard-froze)

### Result: fw-write SUCCEEDS, crash in post-write mdelay(100)

Full chunked 442 233 B BAR2 fw write completed cleanly:
- `starting chunked fw write, total_words=110558 (442233 bytes) tail=1`
- 26 × 16 KB breadcrumbs all fired (wrote 4096 → 106496 words)
- `all 110558 words written, before tail (tail=1)` ✓
- `tail 1 bytes written at offset 442232` ✓
- `post-write ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES` ✓
- `fw write complete (442233 bytes)` — 13:54:25

### Crash location: after `fw write complete`, before `post-mdelay100`

Only code between those two `pr_emerg` calls is a single `mdelay(100)` at
pcie.c:1955. No MCE, no CTO, no panic captured — machine hard-froze (silent
freeze), required SMC reset to recover.

ARM CR4 probe in "post-write" still showed IOCTL=0x21 (CPUHALT|CLK),
RESET_CTL=0. So ARM is still nominally halted at the moment the write ended.
Whatever tears the link down fires during the subsequent 100 ms idle window.

### Interpretation

This is a bigger breakthrough than it looks. All prior "crash mid-write at
variable byte offset" results (test.164 @ 425984 B, test.165 @ 340992 B)
can now be reinterpreted:

- Those crashes were NOT a byte-offset watchdog. They correlate with *elapsed
  wall-clock time* spent inside the fw-write loop (which includes each
  iteration's `mdelay(50)` breadcrumb pause).
- test.170's cadence (16 KB / 50 ms) completed the write fast enough to beat
  the async-event deadline.
- The async event still fires — it just now fires during the post-write
  100 ms settle delay instead of mid-write.

Working hypothesis candidates (ranked):
1. **Root-port ASPM re-entering L1** — endpoint had ASPM disabled (LnkCtl
   after=0x0140) but the root port may still be negotiating; L1 entry on
   idle + un-booted fw = malformed TLP → link drop.
2. **Hidden chip watchdog** — some PMU/resource watchdog fires ~1–2 s after
   the driver stops polling. test.170 total fw-write elapsed was ~9 s
   (13:54:23 → 13:54:25) including 26 × mdelay(50) ≈ 1.3 s of idle.
3. **MCE escalated by iommu=strict** — any bad TLP during the idle gap
   becomes a hard fault.

### PRE-TEST.171 PLAN — probe inside the post-write idle window

**Goal:** localize the async crash to a specific sub-interval of the 100 ms
mdelay, and discover whether MMIO activity during idle prevents the crash.

**Code changes (pcie.c, in `brcmf_pcie_download_fw_nvram` right after
`fw write complete`):**

Replace `mdelay(100)` with a 10-iteration loop:
```c
for (i = 0; i < 10; i++) {
    mdelay(10);
    brcmf_pcie_probe_armcr4_state(devinfo, "idle-N");
}
```
Each iteration:
- 10 ms busy wait
- Read-only ARM CR4 probe (IOCTL/RESET_CTL via BAR0 hi-window)
- Prints one line with iteration index and ARM state

**Hypothesis:** if the probes keep the PCIe link "busy" (MMIO activity),
the crash won't fire — confirming that idle ASPM/L1 is the trigger.
If the crash does fire, we learn which 10 ms sub-window triggers it.

**Interpretation matrix:**
- Crash at iteration N (0 < N < 10) → async event fires at ~N×10 ms after
  fw write completes. Narrow further by N.
- No crash, all 10 iterations log → MMIO activity blocks the async event.
  Next test: strip ASPM from root port explicitly (pci_disable_link_state
  on root port, not just endpoint).
- Crash at iteration 0 → the probe itself (MMIO after write) trips the
  fault; next test: use a different probe target (e.g. BAR2 ioread32).
- ARM state flips during the probes (CPUHALT→NO, RESET_CTL→0xffffffff)
  → ARM auto-resuming; different root cause (chip internal watchdog
  un-halting ARM after fw write).

**Test command:**
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

**Module rebuild required** before the test.

**Pre-test HW state (verified 2026-04-20 14:xx post-SMC-reset):**
- Endpoint 03:00.0: MAbort- ✓, BusMaster+, Mem+, Region0=b0600000, Region2=b0400000
- Root port 00:1c.2: secondary=03, subordinate=03, MAbort-, secondary-MAbort-

---

## TEST.171 RESULT — 2026-04-20 14:50 (crash narrowed to ~20-30 ms after fw write)

### Captured evidence
- Stage0 wrapper log: `phase5/logs/test.171.stage0`
- Crash-time dmesg stream: `phase5/logs/test.171.stage0.stream`
- Previous-boot journal captured after SMC reset: `phase5/logs/test.171.journalctl.txt`

The wrapper stream was mostly lost to the hard freeze: it contains only early
boot lines and no `brcmfmac` breadcrumbs. The previous boot journal was
recoverable and is the authoritative artifact for this test.

### Result

test.171 again completed the full 442233 byte BAR2 firmware write:
- `all 110558 words written, before tail (tail=1)`
- `tail 1 bytes written at offset 442232`
- `post-write ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`
- `fw write complete (442233 bytes)`

The split idle loop then logged:
- `idle-0 ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`
- `idle-1 ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`

No `idle-2`, no `post-idle-loop`, no MCE, no panic, and no PCIe/AER error
were captured before the host froze. SMC reset was required.

### Interpretation

The fatal window is now approximately **20-30 ms after `fw write complete`**:
the first two 10 ms delays plus BAR0 ARM CR4 probes completed, then the host
froze before the third probe printed.

Important constraints:
- ARM CR4 is still reported halted at `post-write`, `idle-0`, and `idle-1`.
  This weakens the "ARM auto-resumed and executed partial firmware" theory for
  this specific post-write crash.
- Periodic BAR0 MMIO probes did **not** keep the system alive through the
  whole 100 ms idle window. That weakens the simple "any MMIO activity prevents
  idle ASPM/L1" version of the ASPM hypothesis.
- The crash still happens after the firmware payload is fully in TCM and before
  NVRAM/resetintr handling, so the current failure is downstream of the raw
  442 KB BAR2 write.

### Current HW state after SMC reset (2026-04-20 ~15:00)

`/run/current-system/sw/bin/lspci` is available; the old pinned
`/nix/store/...pciutils-3.14.0/bin/lspci` path used by the wrapper no longer
exists in this boot, so the wrapper's pre-test lspci section is blank.

Post-reset enumeration is clean:
- Endpoint 03:00.0: BCM4360 visible, Mem+, BusMaster+, BAR0=b0600000,
  BAR2=b0400000, Status has `<MAbort-`.
- Root port 00:1c.2: secondary=03/subordinate=03, memory window
  b0400000-b06fffff, bridge control `MAbort-`, secondary status `<MAbort-`.

### PRE-TEST.172 recommendation

Do **not** run another test until this note and the test.171 artifacts are
committed and pushed.

Next best test: disable ASPM on the **upstream root port** before the firmware
download, not only on the endpoint.

Rationale: test.158 disabled endpoint ASPM (`LnkCtl after=0x0140`), but the
root port may still be entering L1 or otherwise transitioning the link during
the post-write idle gap. Since test.171 freezes after ~20-30 ms of post-write
settle time with ARM still halted, root-port link-state/power-management is
now the highest-value variable to remove.

Suggested code change for test.172:
1. In the BCM4360 probe/setup path, find `pci_upstream_bridge(devinfo->pdev)`.
2. Log root-port `LnkCtl` before/after.
3. Call `pci_disable_link_state(root_port, PCIE_LINK_STATE_L0S |
   PCIE_LINK_STATE_L1 | PCIE_LINK_STATE_CLKPM)` before `brcmf_pcie_download_fw_nvram`.
4. Keep the test.171 idle-loop probes unchanged so the result is comparable.
5. Update `test-staged-reset.sh` to use `/run/current-system/sw/bin/lspci`
   when the pinned Nix-store path is absent.

Interpretation:
- If test.172 survives all 10 idle probes and reaches `post-idle-loop`, root
  port ASPM/CLKPM was implicated.
- If it still freezes after `idle-1`, focus next on chip-internal PMU/watchdog
  or the BAR0 ARM probe side effects rather than generic link idle.
- If root-port LnkCtl already has ASPM bits clear, test.172 still records that
  fact and avoids assuming endpoint-only ASPM was sufficient.

---

## PRE-TEST.172 STATE — 2026-04-20 16:50

Implemented the recommended test.172 code checkpoint:
- `pcie.c`: relabeled current breadcrumbs to test.172; after endpoint ASPM
  disable, finds `pci_upstream_bridge(pdev)`, logs root-port `LnkCtl`, calls
  `pci_disable_link_state(bridge, PCIE_LINK_STATE_L0S | PCIE_LINK_STATE_L1 |
  PCIE_LINK_STATE_CLKPM)`, then logs root-port `LnkCtl` again.
- `test-staged-reset.sh`: writes `test.172.stageN` logs, describes the
  root-port ASPM/CLKPM hypothesis, and falls back from the stale pinned
  Nix-store `lspci` path to `/run/current-system/sw/bin/lspci` or `command -v
  lspci`.

Build status:
- `make -C /home/kimptoc/bcm4360-re/phase5/work` still fails because that
  directory has no Makefile. Use the kernel kbuild path instead.
- Build command used:
  `make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
- Build result: OK. Existing warning only:
  `brcmf_pcie_write_ram32` defined but not used. BTF skipped because `vmlinux`
  is unavailable.
- `strings brcmfmac.ko | rg "test\\.172|root port|post-idle-loop"` confirms
  the new markers are in the module.

Before running:
1. Commit and push this test.172 code/build-state checkpoint.
2. Run only stage 0:
   `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

---

## TEST.172 RESULT — 2026-04-20 17:41 (root-port ASPM already off; freeze moved to ~80-90 ms)

### Captured evidence
- Stage0 wrapper log: `phase5/logs/test.172.stage0`
- Crash-time dmesg stream: `phase5/logs/test.172.stage0.stream`
- Previous-boot journal captured after SMC reset:
  `phase5/logs/test.172.journalctl.txt`

### Result

The post-SMC-reset PCIe hierarchy is clean:
- Endpoint 03:00.0: BCM4360 visible, Mem+, BusMaster+, BAR0=b0600000,
  BAR2=b0400000, Status has `<MAbort-`.
- Root port 00:1c.2: secondary=03/subordinate=03, memory window
  b0400000-b06fffff, bridge control `MAbort-`, secondary status `<MAbort-`.

The root-port link-control test produced an important negative result:
- Endpoint LnkCtl changed from `0x0143` to `0x0140`; endpoint ASPM bits clear.
- Root port LnkCtl was already `0x0040` before the new disable call:
  ASPM bits clear and CLKREQ/ClockPM off.
- Root port LnkCtl remained `0x0040` after `pci_disable_link_state()`.

test.172 again completed the full 442233 byte BAR2 firmware write:
- `all 110558 words written, before tail (tail=1)`
- `tail 1 bytes written at offset 442232`
- `post-write ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES`
- `fw write complete (442233 bytes)`

The post-write idle loop logged through:
- `idle-0` ... `idle-7`, all with `CPUHALT=YES`

No `idle-8`, no `idle-9`, no `post-idle-loop`, no MCE, no panic, and no
PCIe/AER error were captured before the host froze. SMC reset was required.

### Interpretation

Root-port ASPM/CLKPM is not the current primary explanation: the root port was
already in the target state before the test. The crash still happens after the
firmware payload is fully written while ARM CR4 remains halted.

test.172 lasted longer than test.171 (through idle-7 instead of idle-1), so the
exact freeze timing has jitter or depends on the preceding config-space/MMIO
sequence. The best current bound is: fatal window occurs during the post-write
idle/probe phase, after about 80 ms in this run, before any resetintr read or
NVRAM write.

### PRE-TEST.173 recommendation

Do **not** run another test until this note and the test.172 artifacts are
committed and pushed.

Next best test: remove BAR0 ARM CR4 MMIO from the post-write idle loop.

Suggested code change for test.173:
1. Keep endpoint/root-port link-state logging unchanged for comparability.
2. After `fw write complete`, replace the 10 x `mdelay(10) + ARM CR4 probe`
   loop with a no-device-MMIO loop: log before/after each 10 ms delay, but do
   not call `brcmf_pcie_probe_armcr4_state()` inside that idle window.
3. Keep the `post-idle-loop` breadcrumb immediately before the existing
   resetintr read so the next boundary remains clear.
4. Keep stage0 only and keep `bcm4360_skip_arm=1`.

Interpretation:
- If the no-MMIO loop survives to `post-idle-loop`, the BAR0 ARM CR4 probes
  themselves are implicated in the post-write crash path.
- If it still freezes during the no-MMIO idle window, focus on an asynchronous
  chip/host event after a complete BAR2 firmware write, not on the probe reads.
- If it reaches `post-idle-loop` but freezes on resetintr, the next boundary is
  the PCIE2 resetintr read rather than the idle delay.

---

## PRE-TEST.173 STATE — 2026-04-20 17:58

Implemented the recommended test.173 code checkpoint:
- `pcie.c`: relabeled current breadcrumbs to `test.173`; retained the
  endpoint/root-port LnkCtl logging from test.172 for comparability; replaced
  the post-`fw write complete` 10 x `mdelay(10) + ARM CR4 BAR0 probe` loop
  with a no-device-MMIO loop that logs before and after each 10 ms delay.
- `test-staged-reset.sh`: writes `test.173.stageN` logs and documents the
  no-MMIO post-fw idle-loop discriminator. Stage0 remains the only intended
  next run (`bcm4360_skip_arm=1`, `WAIT_SECS=90`).

Build status:
- Build command used:
  `make -C /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
- Build result: OK. Existing warning only:
  `brcmf_pcie_write_ram32` defined but not used. BTF skipped because `vmlinux`
  is unavailable.
- `strings brcmfmac.ko | rg "test\\.173|no-MMIO|post-idle-loop"` confirms
  the new markers are in the module.

Before running:
1. Commit and push this test.173 code/build-state checkpoint.
2. Run only stage 0:
   `sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected interpretation:
- Reaches `post-idle-loop`: BAR0 ARM CR4 probes are implicated in the
  post-write crash path.
- Freezes during the no-MMIO idle loop: asynchronous chip/host event after a
  completed BAR2 firmware write remains the leading hypothesis.
- Reaches `post-idle-loop` then freezes on resetintr: PCIE2 resetintr read is
  the next boundary.
