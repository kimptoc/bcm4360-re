# BCM4360 RE — Resume Notes (auto-updated before each test)

## POST-TEST.225 RERUN (2026-04-22 19:29 BST, boot 0) — JACKPOT: full 442 KB firmware download + TCM verification, host wedged in post-snapshot / set_active block

### Headline

The test.225 rerun is the **jackpot branch** of the original decision tree.
The 442 KB firmware download completed end-to-end with per-chunk readback
verification, the full TCM snapshot was emitted, and every fw-sample
readback MATCHED. This is the first time firmware bytes have been
observed in place in TCM on this chip.

The host then wedged. The next boot (boot 0) is healthy — BAR0 fast-UR
19–25 ms across four reads, SMC reset was performed between crashes.

### What boot -1 (19:12–19:24:11) captured

Logs now archived:
- `phase5/logs/test.225.rerun.journalctl.full.txt` (1400 lines, whole boot)
- `phase5/logs/test.225.rerun.journalctl.txt` (310 lines, brcmfmac-filtered)

Download progress — full 107 × 1024-word chunks + final partial 990-word
chunk emitted, all readbacks OK:

```
19:24:05 test.225: wrote 1024 words (4096 bytes) last=0xb19c6018 readback=0xb19c6018 OK
... (107 chunks) ...
19:24:11 test.225: wrote 109568 words (438272 bytes) last=0x46200db9 readback=0x46200db9 OK
```

Total written = 110558 words / 442232 bytes (final 990-word tail
implicit — chunk-size guard, no marker line on partial chunk).

Post-download snapshot — all emitted at 19:24:11 in a tight burst:
- wide-TCM 40 × 4 KB stride readbacks (full 0–0x9c000 range)
- fine-TCM snapshot complete (16384 cells, base=0x90000)
- tail-TCM 16 × 4 B readbacks (NVRAM region 0x9ffc0–0x9fffc)
- fw-sample 17 × readback vs fw->data: **ALL MATCH**
- CC-regs: clk_ctl_st=0x01030040, pmucontrol=0x01770181,
  pmustatus=0x0000002e, res_state=0x000007ff

Post-download CC state vs pre-download:
- Pre-download: clk_ctl_st=0x07030040 [HAVEHT=YES ALP_AVAIL=YES]
- Post-download: clk_ctl_st=0x01030040 [HAVEHT still bit 17 SET;
  upper status nibble 0x07→0x01 — PMU request counters reset]

Log tail ends at `CC-res_state=0x000007ff (pre-release snapshot)`. No
oops, BUG, MCE, watchdog, rcu stall, or soft-lockup in the full-boot
journal.

### Where the wedge actually happened — open question

Two interpretations survive:

1. **Real wedge immediately after CC-res_state print.** In test.218
   and test.219 logs (same code path), the next expected lines are:
   - `INTERNAL_MEM core not found — resetcore skipped (expected on BCM4360)`
   - `pre-set-active ARM CR4 IOCTL=... CPUHALT=YES`
   - `pre-set-active D11 IOCTL=... RESET_CTL=0x1`
   - `pre-BM PCI_COMMAND=0x0002 BM=OFF MMIO guard mailboxint=...`
   - `pci_set_master done; PCI_COMMAND=0x...`
   - `post-BM-on MMIO guard mailboxint=...`
   - `test.219: FORCEHT write CC clk_ctl_st pre=... post=... [HAVEHT=? ...]`
   - `test.219: calling brcmf_chip_set_active resetintr=...`
   - `brcmf_chip_set_active returned true`
   - `tier1 ARM CR4 IOCTL=... CPUHALT=NO`  ← firmware starts running
   None of these appeared in test.225.

2. **Log tail was truncated.** test.225's chunk loop emitted 107 lines
   in ~6 s, followed by 78 snapshot lines all at 19:24:11. That's
   heavy ring-buffer pressure with no mdelay between lines. A wedge
   deeper in the flow (in set_active or tier1) could drop the last N
   lines before flush-to-disk. test.218 by contrast had much less log
   volume leading into this block (no chunked readback), so journald
   stayed caught up — its emissions cannot be used as a flush-budget
   comparison.

Without discriminator, the test.226 design has to cover **both**
possibilities (markers before AND after set_active). Per advisor,
msleep is better than mdelay between breadcrumbs because it yields
to the journald worker kthread.

### BCM4360 INTERNAL_MEM confirmed NOT a concern

test.218 log confirms `INTERNAL_MEM core not found` on BCM4360 — so
`brcmf_chip_resetcore(imem_core, 0, 0, 0)` is never reached and SOCRAM
(the TCM holding our freshly-written firmware) is never wiped. The
resetcore branch is safe to leave as-is.

### Chip state on current boot 0 (19:25 onward)

- `lspci -vvv -s 03:00.0`: `I/O- Mem+ BusMaster+` (BIOS residual).
  DEVSEL=fast, MAbort-, SERR-. Config space clean.
- `enable=0`, `power_state=unknown`
- BAR0 `dd resource0` timing: 21 / 19 / 19 / 25 ms (fast-UR,
  well under the test script's 40 ms threshold)
- `lsmod | grep brcm`: empty
- Uptime ~4 min post-SMC-reset boot

Safe to insmod after a test.226 build.

---

## PRE-TEST.226 (2026-04-22 19:35 BST) — pinpoint the post-snapshot wedge with msleep-spaced breadcrumbs

### Objective

test.225 rerun cleared the firmware-download debugging chapter. The
wedge has moved to the post-snapshot / set_active path. The next cheap,
non-invasive test is to drop msleep-spaced breadcrumbs between every
operation from `CC-res_state` through `brcmf_chip_set_active` and into
tier1, so we can pinpoint the wedge location regardless of whether it's
"real wedge in this block" or "log tail truncation on deeper wedge".

### What changes in pcie.c

Insert a `test.226` pr_emerg marker + `msleep(5)` between each of the
following operations in the block starting after the CC-reg print loop
(around pcie.c line 2353) through the end of `brcmf_chip_set_active`:

1. `past pre-release snapshot — entering INTERNAL_MEM lookup`
2. Before `brcmf_chip_get_core(BCMA_CORE_INTERNAL_MEM)`
3. After `brcmf_chip_get_core` (print `imem_core=%p`)
4. Before pre-set-active ARM CR4 probe
5. After pre-set-active ARM CR4 probe
6. Before pre-set-active D11 probe
7. After pre-set-active D11 probe
8. Before pre-set-active D11 clkctlst probe
9. After pre-set-active D11 clkctlst probe
10. Before `pci_read_config_word(PCI_COMMAND)` (pre-BM)
11. After pre-BM read
12. Before `pci_set_master`
13. After `pci_set_master`
14. Before `post-BM` MMIO guard
15. After post-BM MMIO guard
16. Before FORCEHT write (CC select + READCC32)
17. After FORCEHT write (post-write readback + log)
18. Before `brcmf_chip_set_active` call
19. After `brcmf_chip_set_active` return (before its existing print)
20. Before tier1 loop entry

No logic changes. No behavior changes beyond extra msleep(5) × ~20 =
100 ms added latency. No changes to PMU mask, chunk loop, firmware
payload, or anything else.

### Decision tree

| Last test.226 marker emitted | Interpretation | Next |
|---|---|---|
| "before `brcmf_chip_get_core`" but not "after" | impossibly early — must be log flush issue, not real wedge | rethink flush budget; add mdelay(100) instead of msleep(5) |
| "after brcmf_chip_get_core" / pre-set-active probes but not pci_set_master | wedge on ARM CR4 / D11 wrapper MMIO read | look at select_core left from prior readbacks |
| "before pci_set_master" but not "after" | config-space write wedged PCIe link | check AER / root-port state; may need separate probe |
| FORCEHT write visible, set_active marker not | wedge in FORCEHT path (unlikely; test.219 proved this works) | n/a |
| `brcmf_chip_set_active returned` visible, tier1 not | wedge in firmware execution — real behavior, not probe artefact | move to tier1 response debugging; compare against test.218 tier1 outcomes |
| All markers through tier1 visible, host wedges later | wedge is in dwell or D11 bring-up — reset plan to deeper window | design test.227 around the later probe set |

### Hardware risk

Low. Each breadcrumb is a pr_emerg + 5 ms sleep. Worst case this
adds ~100 ms latency and no new MMIO. Chip state is the same as
test.225 rerun, which got this far safely. Host wedge hypothesis
unchanged — retest will either reproduce the wedge (in which case
breadcrumbs pinpoint it) or — less likely — the extra msleep gives
the PMU enough slack to complete set_active cleanly.

### Build + run

1. Edit `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`
   (insert 20 breadcrumbs in the block between line ~2353 and line ~2470)
2. `make -C /home/kimptoc/bcm4360-re/phase5/work`
3. Verify `strings brcmfmac.ko | grep -c "test\\.226"` ≥ 20
4. `sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh`

Expected artifacts:
- `phase5/logs/test.226.run.txt`
- `phase5/logs/test.226.journalctl.txt` (grep-filtered, post-run)
- `phase5/logs/test.226.journalctl.full.txt` (whole boot, post-run)
- On crash: capture `sudo journalctl -k -b -1` from next boot.

### Pre-test checks (will re-verify right before insmod)

- Build succeeded, .ko mtime fresh, test.226 marker count ≥ 20
- `lspci -vvv -s 03:00.0` clean (no MAbort/SERR)
- BAR0 dd < 40 ms (fast-UR regime)
- `lsmod | grep brcm` empty

---

## PRE-TEST.225 RERUN (2026-04-22 19:25 BST, boot 0) — post-git-recovery refresh

### Session context

Previous session wedged the host at ~16:20 BST after committing+pushing
the PRE-TEST.225 RERUN plan. Wedge left three zero-byte git objects
locally (HEAD commit + tree + blob). Recovery on this boot:

1. `git fsck` found ref `refs/heads/main` pointing at empty object.
2. Main reflog's last good hash was `5ad176b`; origin had `7183e17`
   (the pre-rerun commit pushed just before wedge).
3. Removed empty objects, reset main to `5ad176b`, `git fetch origin`
   pulled the missing commit, `git reset --hard origin/main` restored
   tree cleanly. Working tree back at `7183e17`.

### Fresh boot state verification (boot 0, uptime ~13 min)

- `lspci -vvv -s 03:00.0`: Control `I/O- Mem+ BusMaster+` (BIOS
  residual — enable=0 in sysfs). MAbort-, SERR-, DEVSEL=fast.
  Region 0 assigned at 0xb0600000 (32K), Region 2 at 0xb0400000 (2M).
- `enable=0`, `power_state=D0`
- BAR0 `dd resource0` timing: 40ms (cold first read, transient link
  wake) → 19–22ms stable across 8 subsequent reads. Fast-UR regime,
  safe to insmod.
- `lsmod | grep brcm`: empty.
- `brcmfmac.ko`: 14.3 MB, mtime 15:25:45 (same test.225 build from
  pre-wedge session; `strings` confirms test.225 readback marker).

### Plan — unchanged

Rerun test.225 as-is (no code changes). Same decision tree as the
entry below: splits boot -1's silent tail into "real setup-entry
wedge" vs "journald flush loss on deeper wedge".

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts (next LOG_NUM):
- `phase5/logs/test.N.run.txt`
- `phase5/logs/test.N.journalctl.txt` (grep-filtered)
- `phase5/logs/test.N.journalctl.full.txt` (whole boot)

---

## PRE-TEST.225 RERUN (2026-04-22 16:10 BST) — deeper PCI state dive; safe to rerun

### Deeper dive: BAR0 timing depends on `enable`, not just chip health

Re-measuring BAR0 after enabling the device showed a surprise:
`enable=1` (D0) produced **65–85ms CTO-regime** reads, while `enable=0`
(also reported D0 after transition) produced clean **21–28ms fast-UR**.
Five consecutive reads in each state confirmed the pattern.

Interpretation: the test script's `dd ... resource0` pre-check is
sensitive to the `enable` bit, not purely to chip backplane health.
With `enable=0` the kernel has PCI memory decoding disabled for the
device and returns a fast rejection; with `enable=1` the transaction
actually reaches the PCIe link and, if the chip backplane is
unresponsive, times out at ~50ms + overhead → looks like CTO.

**This does not mean the chip needs an SMC reset.** Two datapoints
for that:

1. Boot -1's test.225 run proved the chip is reachable via the
   kernel-side probe path: SBR via root-port bridge → BAR0 CC
   probe returned `0x15034360` (twice, stable) → full chip_attach
   → PMU mask writes succeeded (pmustatus=0x2e res_state=0x7ff,
   identical to test.224).
2. In the `enable=0` regime — which is the state the test script's
   pre-check will actually see — BAR0 returns fast-UR cleanly at
   ~25ms. The pre-check passes safely.

### Rule-of-thumb for this platform

- After user-space has touched `enable` or done bare `dd` probes,
  always `echo 0 > enable` before running the test script.
  Otherwise the pre-check sees `enable=1` CTO-regime timing and
  refuses to insmod (same symptom as a genuinely dead chip).
- The **meaningful** safety signal is BAR0 timing in `enable=0`
  state (or on fresh boot where `enable=0` is the default). Fast-UR
  in that state = chip alive; SBR in probe will recover it.
- `enable=1` CTO timing on its own is NOT a chip-dead signal. Drop
  to `enable=0` and re-measure before concluding anything.

### Current hardware state

- `lspci -s 03:00.0`: Region 0/2 `[disabled]`, DEVSEL=fast, MAbort-,
  SERR-. Config space readable.
- `enable=0`, `power_state=D0`
- BAR0 `dd ... resource0`: 21–28ms fast-UR across 5 consecutive reads
- `lsmod | grep brcm`: empty
- DevSta 0x0010 (UnsupReq+ latched from bare `dd` probes; informational
  only, non-W1C bit 4 is AuxPowerDetected — writable error bits
  cleared to 0 via W1C write `CAP_EXP+0xa.w=0x000f`)

### Build state

- `brcmfmac.ko` 14.3 MB, mtime 15:25:45 (same build from 15:45 BST
  session — no code changes between wedge and now)
- `strings` confirms `BCM4360 test.225` readback marker present

### Plan — rerun test.225 as-is

Objective: split the two possible interpretations of boot -1's silent
tail.

- **If rerun reproduces "test.188 setup-entry, then silence"** — real
  signal: something specific wedges in `msleep(300)` or the pre-attach
  probe. Design test.226 with probe points inside that 300ms idle
  and between the attach probes.
- **If rerun emits chunk-loop lines (`test.225: wrote N words`)** —
  boot -1 just lost the ring-buffer tail on wedge. Continue test.224
  chunk-hang debugging plan.
- **If download completes** — jackpot; move to ARM release.

No code changes. Same module, same run command:

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts:
- `phase5/logs/test.225.rerun.run.txt` (depends on LOG_NUM; next free is test.226 slot, but overwrite guard handles it)
- `phase5/logs/test.225.rerun.journalctl.txt` (grep-filtered, post-run)
- `phase5/logs/test.225.rerun.journalctl.full.txt` (whole boot, post-run)

---

## POST-TEST.225 (2026-04-22 15:57 BST, revised 16:05) — hang site uncertain; chip still alive; rerun test.225 as-is

### Revision note

Initial take on this entry said "hang moved EARLIER" and "drain-to-0
required". Both were overstated. The boot -1 journal proves the chip
was alive through chip_attach + PMU mask writes + ASPM dance — same
identifiers as test.224 — so the "chip-state regression" framing is
not supported by the data. Equally, "hang at setup-entry/pre-attach"
is not proven: journald has a flush window between `pr_emerg` writes
and disk, and a silent crash deeper in the probe can drop the tail of
the ring buffer. Kept the facts; dropped the overreach.

### Binary sanity check

`strings brcmfmac.ko | grep 'test.225'` produces the `test.225: wrote
...readback=...` format string — confirms the loaded module is the
test.225 build (mtime 15:25:45). Zero `test.225:` emissions in the log
means "no chunk line made it to disk", which is **consistent with
either** (a) chunk loop never executed, or (b) it executed and the
tail of the ring buffer was dropped on wedge.

### Last lines visible in boot -1 journal

Logs captured: `phase5/logs/test.225.journalctl.txt` (74 lines,
grep-filtered), `phase5/logs/test.225.journalctl.full.txt` (1155 lines,
whole boot). No oops, BUG, MCE, watchdog, rcu_sched stall, or hung
task — pure silent wedge.

```
15:49:09 test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0
15:49:09 test.188: setup-entry ARM CR4 IOCTL=0x00000021 IOSTATUS=0x00000000 RESET_CTL=0x00000000 CPUHALT=YES
15:49:10 test.188: pci_register_driver returned ret=0   ← module_init stack, parallel to the async fw callback
[silence until host reset]
```

Possible interpretations (not yet distinguished):
1. Setup wedged during `msleep(300)` / `pre-attach` probe (pcie.c:4590
   / 4596). Everything after setup-entry was truly not emitted.
2. Setup ran much further — possibly into the chunk loop — but the
   tail of the ring buffer didn't flush before the crash. Test.224's
   chunk messages flushed cleanly because the `mdelay(50)` between
   chunks gave journald disk-write headroom; a tight crash inside a
   chunk burst could lose the last few.

### What boot -1 *does* establish

- Chip is reachable: `BAR0 CC@0x18000000 = 0x15034360` (twice, stable)
- SBR in probe worked, chip_attach succeeded, six cores enumerated
- `pmustatus=0x0000002e res_state=0x000007ff` — **identical** to test.224
- ARM CR4 state post-reset: IOCTL=0x21, CPUHALT=YES — same as test.224
- ASPM disabled cleanly, LnkCtl manipulated, firmware request served

No chip-side difference from test.224 is visible in the pre-hang
journal. The "deeper dive" logic from 15:45 BST (fast-UR → SBR in
probe recovers chip) was empirically confirmed — chip was recovered.

### Current hardware state (boot 0, now)

- Uptime ~15 min (boot 15:42, post-wedge reboot)
- `lspci -s 03:00.0`: device present, Control: `I/O- Mem- BusMaster-`,
  Region 0/2 show `[disabled]`. DEVSEL=fast, no MAbort/SERR.
- `enable=0` initially (now set to 1), `power_state=D3cold`
- `dd ... resource0`: **fast-UR (~19ms)** — same regime as pre-test.225's
  32ms; deeper-dive logic says chip alive, SBR will recover
- `lsmod | grep brcm`: empty

### Decision: rerun test.225 as-is

Cheapest way to split the two interpretations of boot -1:

- **If hang reproduces at setup-entry / pre-attach** (no chunk lines) —
  real signal that something between setup-entry and pre-attach is
  wedging this specific code path. Design test.226 around that probe.
- **If chunk lines appear this time** — boot -1 "no test.225 lines"
  was journald flush loss on wedge. test.224-style chunk debugging
  still on the table. Use the readback data to pick next step.
- **If download completes** — jackpot (very unlikely on same chip state).

No code changes. No drain-to-0 required on current evidence.

---

## PROCEEDING WITH TEST.225 (2026-04-22 15:45 BST) — fast-UR confirmed, chip safe

Re-checked the post-SMC-reset state with the **same timing logic** the
test script uses, not just a bare dd. Result: BAR0 dd returns
"Input/output error" but in **32 ms** elapsed (bash overhead included).
The test script's threshold is 40 ms — under that = fast Unsupported
Request, meaning the chip IS alive and the kernel-side SBR in probe
will recover it. Over 40 ms = slow Completion Timeout (dead chip,
hard-crash risk).

Earlier confusion: a bare `dd` returning I/O error looks alarming, but
that's the **expected** state for an unconfigured BCM4360 — the chip
responds "no" fast (UR), which is the safe state, distinct from the
56 ms slow-CTO state that aborted test.225 last time. The quick SMC
reset DID work this time.

### Build state (just verified)
- `brcmfmac.ko` 14.3 MB, mtime 15:25 — already rebuilt for test.225
- `strings` confirms `BCM4360 test.225` markers in the binary
- Kernel 6.12.80 vermagic match (per prior session)

### Pre-test hardware state
- Boot 0 of 1 (uptime ~3 min, this is the post-SMC-reset boot)
- `lspci -vvv -s 03:00.0`: 2.5GT/s x1, MAbort-, SERR-, CommClk+
- DevSta clean (cleared via setpci W1C earlier)
- BAR0 dd: 32 ms = fast UR = safe to insmod
- `lsmod | grep brcm` empty

### Plan
Run test.225 as designed in the original PRE-TEST.225 entry below: 4 KB
chunks (1024 words) with per-chunk readback verify, to pinpoint where
the test.224 firmware-download hang occurs (~131 KB into a 442 KB
download). Decision tree, hypotheses, and run command unchanged.

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

---

## POST-SMC-RESET CHECK (2026-04-22 15:43 BST) — chip backplane STILL dead

User reports an SMC reset was performed and the host has rebooted (uptime
~1 min, boot at 15:42). Pre-test hardware verification:

- `lspci -vvv -s 03:00.0`: Link up, 2.5GT/s x1, MAbort-, SERR-, CommClk+,
  config space readable (vendor 0x14e4 dev 0x43a0 chiprev 0x03)
- DevSta showed `CorrErr+ UnsupReq+` latched from earlier — cleared via
  `setpci CAP_EXP+0xa.w=0x000f` (W1C). Now reads clean.
- `/sys/bus/pci/devices/0000:03:00.0/enable` was 0; set to 1.
  power_state now reports D0.
- **`dd if=...resource0 bs=4 count=1` still returns "Input/output error"
  immediately.** Chip-internal backplane is not responding to MMIO even
  though PCIe link is up and the device is enabled.

This is the same symptom as the test.225 abort. The SMC reset that was
done did not restore chip backplane responsiveness.

Hypothesis: the SMC reset performed may have been the quick variant
(power+ctrl+shift+option for 10s) rather than the full drain-to-zero
required for this dead-chip mode. On Apple silicon laptops the drain-to-0
procedure is: shut down → unplug power → drain battery to 0% (leave it
overnight or several hours unplugged) → reconnect power → boot. Quick SMC
resets often don't clear chip-internal state from BCM4360 hangs.

**Action required from user**: confirm the type of SMC reset performed.
If it was a quick reset, the full drain-to-0 may still be required.
Alternatively, we can wait some hours with the host powered off to see
if chip-internal state decays naturally.

No code/plan changes — test.225 module build is still ready to run when
BAR0 comes back. Pre-check guard in test-brcmfmac.sh will continue to
refuse insmod while BAR0 is dead, which is the safe default.

---

## TEST.225 ABORTED (2026-04-22 15:40 BST) — BAR0 dead; SMC reset required before retry

The test-brcmfmac.sh pre-check (BAR0 MMIO read via
`/sys/bus/pci/devices/0000:03:00.0/resource0`) reported **"FATAL: BAR0
MMIO Completion Timeout (56 ms) — device dead"** and refused to
insmod — a safety feature to prevent a sure-thing host hard-crash.
Manual `dd` against the sysfs BAR0 resource returned "Input/output
error" immediately, confirming the chip backplane is gone even though
PCIe config-space reports link up (LnkSta 2.5GT/s x1, no MAbort/SERR,
DevSta clean).

This matches the PRE-TEST.225 risk note — no SMC reset between
test.223, test.224, and the current boot. Three consecutive crash
boots have left chip-internal state in a dead window despite a clean
host reboot. Standard MacBook SMC reset procedure (drain battery to 0%,
leave powered off a few minutes, recharge, boot) is required before
test.225 can run. No code or plan changes — when BAR0 is alive again
we can re-run the same module build.

**Action required from user**: SMC reset (drain-to-0 procedure), boot,
verify `dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 bs=4 count=1`
succeeds, then re-run `sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh`.

No journal captured this time — the test script aborted pre-insmod, so
there's nothing to grep.

---

## PRE-TEST.225 (2026-04-22 15:35 BST) — pinpoint download hang: 4 KB chunks + readback verify

### What changed vs test.224

**pcie.c (`brcmf_pcie_download_fw_nvram` chunk loop)**:
- `chunk_words` **4096 → 1024** (16 KB → 4 KB per breadcrumb). Total
  chunks 27 → ~108. Gives 4× finer hang resolution (we'll know to
  within 4 KB where it stops).
- Chunk-boundary marker **test.188 → test.225**. New log line adds a
  readback of the last word written to distinguish three failure modes:
  - `readback == src32[i]` → write OK, bus alive. Keep going.
  - `readback == 0xffffffff` → BAR2 window dead (PMU/TCM gone), but
    bus still responsive on the read side.
  - readback hangs → whole backplane dead.

No changes to PMU mask, probe order, firmware, or anything else.

### Build state (just verified)

- `brcmfmac.ko` rebuilt clean; `strings` shows the new `test.225`
  marker in pcie.o. One harmless unused-function warning on
  `brcmf_pcie_write_ram32` (same as before).
- Kernel 6.12.80 vermagic match.

### Pre-test hardware state (current boot 0)

- `lspci -vvv -s 03:00.0`: LnkCtl ASPM Disabled, LnkSta 2.5GT/s x1,
  MAbort-, SERR-, CommClk-. Clean config state.
- `lsmod | grep brcm` empty.
- **No SMC reset between test.223, test.224, and this boot.** Chip
  may retain PMU state from prior runs. Expect the first two PMU
  mask writes to show `0x13f -> 0x7ff` and `0x13b -> 0x7ff`; if
  baseline is already `0x7ff` the chip has dirty state and we'd want
  an SMC reset for a clean rerun.

### Hypothesis

Given test.224 hung after 8 × 16 KB chunks (131072 bytes = 32768
words), test.225 will emit chunks at 1024, 2048, 3072, ... word
boundaries. Expected outcomes:

1. **Time-correlated hang** — chunks 33..34 (131072..135168 B) hang
   with the same ~2 s post-start pattern. Confirms it's not the
   payload content, but either cumulative host backpressure or a
   chip state that drops mid-download.
2. **Address-correlated hang** — hang moves to exactly the same byte
   offset (131072 B, which is TCM +0x20000). Suggests a TCM block /
   window boundary; would look like a lot like rambase=0 + 128 KB =
   a natural 128 KB aperture limit.
3. **Readback "DEAD" (0xffffffff) just before hang** — BAR2 window
   went dark, most likely a PMU resource dropped. Look at
   `clk_ctl_st` on next test.
4. **Readback "MISMATCH"** — silent write corruption, would be
   surprising on BAR2.
5. **Readback "OK" through the hang boundary, then the next chunk
   never fires** — the NEXT chunk's first iowrite32 wedged the host.
   Test.226 would inject a liveness probe *between* chunks to narrow
   which specific word does it.

### Decision tree

| Observation | Interpretation | Next |
|---|---|---|
| All chunks readback OK, download completes | 4 KB cadence gives the chip enough breathing room; proceed to ARM release | Re-enable post-release TCM sampling (test.228+) |
| Hang at byte offset 131072 ± 4 KB | Address boundary, not a time effect. Probably TCM window / RAM size edge | Inspect `ramsize=0xa0000` and whether TCM really maps 0x00000..0xa0000 |
| Hang at a *later* byte offset (e.g. 256 KB, 384 KB) | Chunk size / cadence matters — smaller chunks helped | Confirm with test.226 chunk_words=512 (2 KB) |
| Readback=0xffffffff for N chunks before hang | BAR2 went dark silently while bus was alive | test.226 adds clk_ctl_st sample per chunk |
| Host hangs during test.225 (no oops, silent) | Same as test.224; didn't help | Consider pre-download warm-up (idle dwell after HAVEHT) or move to BAR0-windowed writes |
| Baseline mask read shows 0x7ff at first PMU write line | Chip retained state from test.224; SMC reset needed | Halt, request SMC reset, re-run |

### Risk note — same as test.224

Download hangs silently; host will likely wedge again if the same
failure mode repeats. No SMC reset since test.223; chip state could
be subtly off. This test is worth running in its current state
because the information cost of **not** narrowing the hang location
is high — test.226 will design differently if test.225 pinpoints a
specific byte offset or distinguishes bus-dead from BAR2-dead.

### Run command

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts:
- `phase5/logs/test.225.run.txt`
- `phase5/logs/test.225.journalctl.txt` (grep-filtered, post-run)
- `phase5/logs/test.225.journalctl.full.txt` (whole boot, post-run)
- On crash: capture from `journalctl -k -b -1` on next boot.

---

## POST-TEST.224 (2026-04-22 15:20 BST) — narrow mask works; download now hangs at 131 KB / 442 KB (new failure mode)

### Summary

Test.224 reached the furthest point of any test to date. Narrow PMU
mask `0x7ff` behaved identically to the `0xffffffff` wide mask
(`pmustatus=0x2e res_state=0x7ff`), HAVEHT=YES persisted through
pre-download and pre-halt probes, the download actually started and
ran for ~2 seconds before hanging at chunk 8 of 27 — 32768 words /
131072 bytes (~30% through the 442233-byte firmware).

Logs captured: `phase5/logs/test.224.journalctl.txt` (117 lines),
`phase5/logs/test.224.journalctl.full.txt` (1237 lines).

### Key log lines from test.224 (boot -1, 15:16:56 → 15:17:12)

```
15:16:59 test.224: max_res_mask 0x0000013f -> 0x000007ff (wrote 0x000007ff)
15:16:59 test.224: min_res_mask 0x0000013b -> 0x000007ff (wrote 0x000007ff)
15:16:59 test.224: post-settle pmustatus=0x0000002e res_state=0x000007ff (expect 0x2e / 0x7ff)
15:17:08 test.218: pre-download CR4 clk_ctl_st=0x07030040
          [HAVEHT(17)=YES ALP_AVAIL(16)=YES BP_ON_HT(19)=no ...]
15:17:08 test.218: pre-download D11 IN_RESET=YES (RST=0x00000001)
15:17:08 test.163: before brcmf_pcie_download_fw_nvram (442KB BAR2 write)
15:17:09 test.138: post-BAR2-ioread32 = 0x03cd4384 (real value — BAR2 accessible)
15:17:10 test.188: pre-halt CR4 clk_ctl_st=0x07030040 [HAVEHT=YES ALP_AVAIL=YES ...]
15:17:10 test.188: starting chunked fw write, total_words=110558 (442233 bytes)
15:17:10 test.188: wrote 4096 words (16384 bytes)
15:17:10 test.188: wrote 8192 words (32768 bytes)
15:17:10 test.188: wrote 12288 words (49152 bytes)
15:17:11 test.188: wrote 16384 words (65536 bytes)
15:17:12 test.188: wrote 20480 words (81920 bytes)
15:17:12 test.188: wrote 24576 words (98304 bytes)
15:17:12 test.188: wrote 28672 words (114688 bytes)
15:17:12 test.188: wrote 32768 words (131072 bytes)
[ SILENCE — machine hung ]
```

No oops / BUG / MCE / AER. Clean hang.

### Interpretation

1. **Narrow mask = wide mask on this silicon** (confirmed). The
   achievable resource set is bits 0..10 (`0x7ff`); anything wider is a
   no-op. Drop `0xffffffff` from future writes.
2. **HAVEHT is stable** across the full probe sequence (pre-download,
   pre-halt, consistently `0x07030040`). The breakthrough holds.
3. **Download now progresses** — test.223 never got this far; test.221
   hung on log volume, not the burst itself. This is the **first time**
   we have concrete evidence of firmware words reaching TCM.
4. **New failure mode**: host hangs between chunk 8 (wrote at 15:17:12)
   and chunk 9 (should have written at ~15:17:12 + 50 ms delay +
   16 KB of iowrite32s). Each chunk has a `mdelay(50)` after it, so
   the inner `iowrite32` burst is ~4 ms at PCIe write latency — the
   hang is almost certainly inside the 9th chunk's iowrite32 burst, at
   some address between 0x20000 and 0x24000 in BAR2 window
   (rambase=0x0 + 131072 = 0x20000).

### What test.224 does NOT tell us

- Whether it's the **address** of the write (TCM block boundary?) or
  the **cumulative count** of writes that triggers the hang.
- Whether the bus itself died or only BAR2 writes are being rejected
  (no readback probe after each chunk).
- Whether the PMU state has drifted during the download (no
  clk_ctl_st probe inside the loop).
- Whether HT clock is still present when the hang occurs.

### Next hypothesis — test.225 plan

Add three probes to the chunk loop to pinpoint the hang and
distinguish "bus dead" from "TCM writes silently dropped":

1. **BAR0 readback after each chunk** — read the ChipCommon ID register
   (`0x18000000` via BAR0). If this still returns `0x15034360` after
   chunk 8 but hangs on chunk 9, the BAR0 backplane is alive and only
   BAR2 writes are failing. If BAR0 read itself hangs → bus death.
2. **Read-back verify** the last word written in each chunk — detects
   silent drops.
3. **Halve `chunk_words` to 2048** (8 KB per chunk) — finer hang
   location, `mdelay(50)` per chunk gives the chip ~2× more recovery
   time per MB of transfer.
4. (Optional) Probe ARM CR4 `clk_ctl_st` at the start of each chunk,
   not just pre/post download — confirm HAVEHT stays up.

Minimal diagnostic change — if the hang is address-correlated we'll
see it at a specific byte offset; if time-correlated, at a specific
elapsed interval since download start.

### Decision tree for test.225

| Observation | Interpretation | Next |
|---|---|---|
| BAR0 readback survives past hang, only BAR2 hangs | TCM window gone — possibly a PMU resource or clock dropped mid-download | Sample clk_ctl_st / res_state every chunk; correlate |
| BAR0 readback also hangs | Whole backplane dead — PCIe link still up but chip-internal bus stopped | Try throttling further (chunk_words=1024) |
| Download completes | Chunk size or cadence was the issue — compare with test.224 to see what changed | Proceed to firmware release / post-download verification |
| Hang moves to same byte offset (e.g. 0x20000) | Address-correlated: TCM block boundary, specific memory cell | Map TCM; test a read before the problematic offset |
| Hang moves with different timing | Time-correlated: cumulative effect (backpressure, clock, thermal) | Try a longer mid-download delay |

### Risk — chip state not cleanly reset

No SMC reset between test.223, test.224, and current boot 0. The
first two PMU mask writes we'll do in test.225 will log
`0x13f -> 0x7ff` and `0x13b -> 0x7ff` — if baseline reads show
`0x7ff` already, the chip has retained prior mask state and SMC
reset is needed for a clean run.

### Pre-test.225 hardware state (current boot 0)

- `lspci -vvv -s 03:00.0`: LnkCtl ASPM Disabled, LnkSta 2.5GT/s x1,
  MAbort-, SERR-, CommClk-. Link up, no dirty state.
- `lsmod | grep brcm` empty.

---

## PRE-TEST.224 (2026-04-22 15:10 BST) — narrow mask to observed 0x7ff + pre-download HAVEHT capture

### What changed vs test.223

**chip.c (`brcmf_chip_setup` PMU block)**:
- `max_res_mask` write `0xffffffff` → **`0x000007ff`** (observed achievable set)
- `min_res_mask` write `0xffffffff` → **`0x000007ff`** (same)
- Markers `test.223` → `test.224` (both mask lines + the post-settle
  readback line)
- Readback message now includes `(expect 0x2e / 0x7ff)` so we can
  eyeball-confirm the identical hardware state

**pcie.c (`brcmf_pcie_setup` just before download)**:
- Added `brcmf_pcie_probe_d11_clkctlst(devinfo, "pre-download")` right
  after the existing `brcmf_pcie_probe_armcr4_state(devinfo, "pre-download")`
- This reads CR4 + 0x1e0 and D11 + 0x1e0 clk_ctl_st BEFORE the 442 KB
  BAR2 burst. Test.221 proved HAVEHT=YES from inside `download_fw_nvram`
  at the "pre-set-active" sampling; test.223 never reached that because
  the burst hung. The new probe captures the same bit pattern at the
  earliest safe point

No other code changes. `nr_fw_samples` still 16 (from test.222).

### Build state (just verified)

- `brcmfmac.ko` rebuilt clean; markers `test.224: max_res_mask`,
  `test.224: min_res_mask`, `test.224: post-settle pmustatus` all
  present in `strings brcmfmac.ko`
- One harmless `-Wunused-function` warning on `brcmf_pcie_write_ram32`
  (same as before)
- Kernel 6.12.80 vermagic match

### Pre-test hardware state

- Boot 0 `lspci -vvv -s 03:00.0`: `MAbort- SERR- LnkSta 2.5GT/s x1
  ASPM Disabled` — link up, no dirty state flags
- **No SMC reset between test.223 crash and current boot** (user
  confirmed in conversation). BCM4360 may retain internal state from
  the test.223 hang — relevance unclear, PCIe cfg looks clean but
  chip-internal PMU state could still be transient. See Risk note
  below
- `lsmod | grep brcm` → empty (no prior brcmfmac this boot)

### Hypothesis

1. Narrower `0x7ff` mask is hardware-equivalent to `0xffffffff` on
   this silicon (bits 11+ unimplemented). Expected readback
   `pmustatus=0x2e res_state=0x7ff` matches test.223.
2. The new `probe_d11_clkctlst("pre-download")` will emit
   `test.218: pre-download CR4 clk_ctl_st=0x0703xxxx [HAVEHT(17)=YES
   ALP_AVAIL(16)=YES ...]` — same pattern test.221 saw from the
   deeper "pre-set-active" probe.
3. Download burst behaviour is uncertain — may repeat the
   test.223 hang, may complete (test.221 sample) depending on
   chip-internal state.

### Decision tree

| Observation | Interpretation | Next |
|---|---|---|
| pmustatus=0x2e res_state=0x7ff + probe HAVEHT=YES + download completes | Jackpot: narrow mask works, no burst hang. Compare post-release TCM with test.188 nr_fw_samples=16 loop | follow firmware startup probes |
| HAVEHT=YES but download still hangs | Burst hang reproducible regardless of mask width; need to mitigate burst (e.g. throttle MMIO rate, split into smaller chunks, or investigate why test.221 succeeded here) | test.225: throttled MMIO download |
| HAVEHT=NO pre-download | Mask 0x7ff narrower than expected OR silicon needs additional bit | capture pmustatus/res_state actual; try 0xffffffff again for comparison |
| Chip PMU state different vs test.223 (res_state ≠ 0x7ff) | Chip-internal state was dirty post-test.223 crash; SMC reset needed to reset PMU memory | halt, request SMC reset |

### Risk note — chip state may be dirty

Cold reboot does not power-cycle the M.2 slot. Any PMU / ARM CR4 /
backplane state set during test.223 may persist into this boot even
though the host's view of the chip (lspci) looks clean. Two possible
outcomes:

- **Best case**: chip is effectively in POR (PMU internal latches
  cleared by link-down/link-up cycle). Test.224 behaves like running
  on fresh silicon, probably mirrors test.223 up to the "pre-download"
  probe.
- **Worst case**: BCM4360 retains PMU mask values and/or partial
  up-sequence state. The wide mask from test.223 might still be
  "requested" at POR, skewing our baseline readback (would expect to
  see pre_max already `0x7ff` or `0xffffffff`, not `0x13f`).
- **Crash case**: the chip is in a state where even early MMIO hangs.
  Would show as no progress past test.158 BAR0 probe.

The pre_max / pre_min values in the first two log lines of test.224
are the cheapest tell for this: if they read `0x7ff`/`0x7ff` instead
of the expected `0x13f`/`0x13b`, the chip has retained test.223's mask
and we should stop and request an SMC reset before going further.

### Run command (same script)

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts: `phase5/logs/test.224.run.txt`,
`phase5/logs/test.224.journalctl.txt`,
`phase5/logs/test.224.journalctl.full.txt`. On crash → capture from
`journalctl -k -b -1` next boot.

---

## POST-TEST.223 (2026-04-22 15:05 BST) — msleep fix worked past ASPM, captured first-ever PMU state, but fw-download hang

### Summary

Test.223 is a partial success. The `msleep(20)` + readback change
landed as planned and the host survived past the test.222 ASPM-time
hang. We captured the first-ever post-wide-mask PMU state and ran
all the way through chip_attach, ASPM disable, PCIe2 setup, fw
request, setup callback, raminfo, and the "pre-download" ARM CR4
probe. Then the host hung silently — the next `pr_emerg`
("test.163: before brcmf_pcie_download_fw_nvram (442KB BAR2 write)")
never appeared in the journal. Cold reboot only (no SMC reset).

Logs captured: `phase5/logs/test.223.journalctl.txt` (95 lines,
grep-filtered) and `phase5/logs/test.223.journalctl.full.txt`
(1203 lines, whole boot -1).

### Key log lines from test.223 (boot -1, 14:53:12 → 15:01:32)

```
15:01:21 test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11
15:01:21 test.193: PMU WARs applied — chipcontrol#1 0x00000210->0x00000a10
         pllcontrol#6=0x080004e2 #0xf=0x0000000e
15:01:21 test.223: max_res_mask 0x0000013f -> 0xffffffff (wrote 0xffffffff)
15:01:21 test.223: min_res_mask 0x0000013b -> 0xffffffff (wrote 0xffffffff — learning probe)
15:01:21 test.223: post-settle pmustatus=0x0000002e res_state=0x000007ff  ★ new data ★
15:01:21 test.119: brcmf_chip_attach returned successfully
15:01:22 test.158: BusMaster cleared after chip_attach
15:01:23 test.158: ASPM disabled; LnkCtl before=0x0143 after=0x0140           ← survived test.222 hang point
15:01:24 test.188: root port ... LnkCtl after=0x0040                          ← survived
15:01:29 test.162: brcmf_pcie_setup CALLBACK INVOKED ret=0
15:01:32 test.128: brcmf_pcie_attach ENTRY
15:01:32 test.194: PCIe2 CLK_CONTROL probe = 0x00000182
15:01:32 test.194: SBMBX write done
15:01:32 test.194: PMCR_REFUP 0x00051852 -> 0x0005185f
15:01:32 test.128: after brcmf_pcie_attach
15:01:32 test.130: after brcmf_chip_get_raminfo
15:01:32 test.188: post-raminfo ARM CR4 IOCTL=0x21 IOSTATUS=0 RESET_CTL=0 CPUHALT=YES
15:01:32 test.130: after brcmf_pcie_adjust_ramsize
15:01:32 test.188: pre-download ARM CR4 IOCTL=0x21 IOSTATUS=0 RESET_CTL=0 CPUHALT=YES
[ SILENCE — machine hung ]
```

No oops / BUG / MCE / AER in the log (kernel booted with `pci=noaer`,
so AER is suppressed anyway). Pure silent hang.

### First-ever wide-mask PMU state (★ key data ★)

| Reg | Default (test.191..220) | Post-wide-mask (test.223) | Delta (new bits set) |
|---|---|---|---|
| pmustatus | 0x2a | 0x2e | +bit 2 |
| res_state | 0x13b | 0x7ff | +bits 2, 6, 7, 9, 10 (i.e. +0x6c4) |

`res_state=0x7ff` = bits 0..10 all asserted. Writing `0xffffffff` vs
`0x7ff` would produce the same hardware outcome — bits 11+ aren't
implemented on this silicon. **The useful narrow mask is 0x7ff.**

Interpretation:
- Baseline 0x13b = bits 0,1,3,4,5,8. The five NEW resources PMU brought
  up are at bits 2, 6, 7, 9, 10.
- Test.221 proved that with this wider mask the ARM CR4 `clk_ctl_st`
  reads **HAVEHT=YES, ALP_AVAIL=YES**. So one of the five new bits
  (2/6/7/9/10) is the HT-clock-backing resource we've been missing.
- Narrowing from 0xffffffff to 0x7ff is safe (same resources). Further
  narrowing (e.g. to `0x13b | 0x40` = 0x17b) would bisect which bit
  actually enables HT. Not required yet — 0x7ff is the clean ask.

### Why the fw-download hang?

Rough sequence after `test.188: pre-download ARM CR4`:

1. `pr_emerg("BCM4360 test.163: before brcmf_pcie_download_fw_nvram")`
2. `mdelay(300)`
3. `brcmf_pcie_download_fw_nvram` — **442 KB BAR2 MMIO burst** into TCM
   (CPU→device posted writes, no DMA)

The "test.163" pr_emerg never reached the journal. Two candidates:

- **(a)** The pr_emerg itself printed but wasn't drained to console
  before the host wedged. Hang is inside `download_fw_nvram` when the
  long MMIO burst trips bus unresponsiveness caused by the wide PMU
  mask having promoted a resource (D11 / BP-on-HT / ALP) that is now
  contending for the backplane.
- **(b)** Something between the two `pr_emerg` calls is doing hidden
  work. Reading pcie.c:4637–4640, there is nothing but the pr_emerg
  and a `mdelay`. So (a) is by far the more plausible explanation.

No evidence of a chip-side fault — flow progressed much further than
any prior test. The blocker is now a **host-side MMIO backpressure**
issue during the 442 KB burst, not a chip init gap.

### What worked (record for future)

- `msleep(20)` after the pair of wide mask writes was sufficient to
  let PMU settle before the ASPM state transition on the root port
  (test.222 hung here; test.223 did not).
- Readback of `pmustatus`/`res_state` via `brcmf_pcie_read_reg32` after
  the delay landed cleanly and produced the key 0x2e/0x7ff data point.
- Wide mask writes themselves are benign at probe time. The hang is
  correlated with sustained MMIO traffic later.

### Next hypothesis — narrow mask + bisect HAVEHT bit

Plan for test.224 (PRE section being drafted now):

1. Change both mask writes from `0xffffffff` → `0x7ff` (exact
   observed-achievable resource set). No hardware behaviour change
   vs. test.223 expected, but it's the clean ask and sets up further
   bisection.
2. Keep msleep(20) + readback. Expect same `pmustatus=0x2e
   res_state=0x7ff` — if we see a different value, the write width
   actually matters.
3. Add a second probe_armcr4_state call AFTER mask settle to confirm
   HAVEHT latches the same as test.221 (this is the regression check).
4. Do NOT attempt fw-download yet — too risky until we've mitigated
   the burst-time hang. Harness can early-return before download
   (via `bcm4360_skip_arm=1` path already present) to keep the host
   alive while we iterate on the mask.

If test.224 is clean with 0x7ff and HAVEHT latches, test.225 can
bisect (0x13b | 0x40 first — bit 6 is the most likely HT backer
based on bcma conventions).

### Crash-boot hardware state

- Boot 0 `lspci -vvv -s 03:00.0`: `MAbort- SERR- CommClk- LnkSta
  2.5GT/s x1 ASPM Disabled` — link still up, clean. No SMC reset
  between boot -1 crash and boot 0.
- No brcmfmac loaded (`lsmod | grep brcm` empty). mt76/mt76x02_*
  present on unrelated USB card.

---

## POST-CRASH / PRE-TEST.223 (2026-04-22 15:00 BST) — add PMU settle delay + readback to stop ASPM-time bus hang

### test.222 forensics (boot -1, 14:41:07 → 14:51:22)

`phase5/logs/test.222.run.txt` is **empty** — the test-brcmfmac.sh
helper never got to write to its log file. journalctl from the crash
boot shows the brcmfmac load did make progress:

```
14:51:18 test.193: PMU WARs applied — chipcontrol#1 0x00000210->0x00000a10 ...
14:51:18 test.222: max_res_mask 0x0000013f -> 0xffffffff (wrote 0xffffffff)
14:51:19 test.222: min_res_mask 0x0000013b -> 0xffffffff (wrote 0xffffffff — learning probe)
14:51:20 test.119: brcmf_chip_attach returned successfully
14:51:21 test.158: BusMaster cleared after chip_attach
14:51:22 test.158: ASPM disabled; LnkCtl before=0x0143 after=0x0140 ...
14:51:22 test.188: root port 0000:00:1c.2 LnkCtl before=0x0040 ASPM=0x0 ...
14:51:22 test.188: root-port pci_disable_link_state returned — reading LnkCtl
[ SILENCE — machine hung ]
```

No oops / BUG / call-trace. The host froze between
`pci_disable_link_state returned` on the root port and the readback
of the root-port `LnkCtl` immediately after.

### Crash cause hypothesis (differs from test.221 cause)

test.221 survived this exact point and reached the fw-sample loop,
where pr_emerg flooding killed the host. test.222 hung **earlier**,
during root-port ASPM transition, so the root cause is not log
volume.

The wider PMU mask write `min_res_mask = 0xffffffff` forces the PMU
to bring up **every** implemented resource, running ramp/up
sequences for each. During this power-rail churn the endpoint is
likely unresponsive to config-space / bus traffic. We follow the
mask writes with:

- read-back of max and min masks (two MMIO reads)
- `brcmf_chip_setup` returns immediately
- `pci_clear_master` (config write)
- `pci_disable_link_state` on endpoint (config writes via root port)
- `pci_disable_link_state` on root port (config writes on parent)
- read-back of root-port `LnkCtl`

If the endpoint's link is in L1 during any of this and the PMU is
busy powering rails, the LTR/ASPM state transition can stall.
test.221 got lucky on timing; test.222 did not.

### Change for test.223 (minimal, diagnostic + soft settle)

1. After writing `max_res_mask = 0xffffffff` and `min_res_mask =
   0xffffffff`, **`msleep(20)`** to let the PMU finish promoting
   resources before any more bus traffic.
2. After the sleep, read `pmustatus` and `res_state` once each and
   emit a single `pr_emerg` with both values. This gives us the
   first-ever look at what the PMU actually brought up when asked
   unconditionally (key data for narrowing the mask in later tests).
3. Bump the two mask-write markers `test.222` → `test.223` so we
   can grep-confirm the new module loaded.
4. Keep `nr_fw_samples=16` in pcie.c — log-volume fix still needed.

No change to the mask values themselves. No change to flow order.
Just give the chip a moment to catch up before the ASPM state
transition.

### Decision tree

| Observation | Interpretation | Next |
|---|---|---|
| Host survives past ASPM, reaches firmware download | Settle delay was the fix; capture new pmustatus/res_state data | Use the captured bits to narrow the mask |
| Host survives, pmustatus/res_state = 0x13b/0x13f (no change) | Wider mask didn't promote anything after all — test.221 HAVEHT was a transient | Re-check test.221 HAVEHT capture; consider narrower mask |
| Host survives, pmustatus shows many new bits SET | Jackpot — capture and narrow in test.224 | Shrink mask to only-bits-set pattern |
| Host hangs at same point | Settle delay insufficient; PMU ramp longer than 20ms | Try msleep(50–100) or gate mask writes earlier |
| Host hangs later (e.g. fw-sample loop) | Progress — diagnose new hang separately | Follow the new failure |

### Build state

- chip.c: adding msleep(20) + pmustatus/res_state readback after
  the pair of mask writes; bumping test.222 → test.223 markers.
- pcie.c: unchanged from test.222 (nr_fw_samples=16).
- Expected rebuild: clean.

### Pre-test hardware state

- `lspci -vvv -s 03:00.0` (current boot 0): MAbort-, SERR-,
  DevSta clean, LnkSta 2.5GT/s x1, LnkCtl ASPM Disabled, CommClk-.
  Note: user confirmed **no SMC reset** between the test.222 crash
  and this boot — just a cold reboot. PCIe state nonetheless
  reports clean, matching prior boot pattern.
- brcmfmac not loaded (`lsmod` empty).

### Run plan

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts:
- `phase5/logs/test.223.run.txt`
- `phase5/logs/test.223.journalctl.txt` (post-run grep)
- `phase5/logs/test.223.journalctl.full.txt` (post-run full boot dump)
- On crash: capture from `journalctl -k -b -1` next boot.

---

## PRE-TEST.222 (2026-04-22 14:50 BST) — re-run wider-mask probe with reduced log volume

### What changed vs test.221

- `pcie.c` — `nr_fw_samples` reduced **256 → 16**. test.221 crashed
  the host while pumping 256 × pr_emerg fw-sample lines at the kernel
  syslog; at 16 samples the log volume is ≈16× lower and should stay
  well below the soft-lockup threshold.
- `chip.c` — PMU mask-write markers bumped `test.221 → test.222` so
  we can grep-confirm the new module loaded.
- Wider PMU mask write itself is **unchanged** — still
  `min_res_mask = max_res_mask = 0xffffffff` on the CC PMU.

### Build state (verified just now)

- `brcmfmac.ko` rebuilt 14:49 Apr 22; `strings` shows `test.222`
  markers in chip.o. No compile errors; one harmless unused-function
  warning on `brcmf_pcie_write_ram32`.
- Kernel 6.12.80, vermagic matches.

### Pre-test hardware state (just checked)

- `lspci -vvv -s 03:00.0`: `MAbort- SERR- DevSta clean, LnkSta 2.5GT/s
   x1, ASPM Disabled` → clean post-SMC-reset, safe to probe.
- No brcmfmac module loaded (`lsmod | grep brcm` empty).

### Hypothesis

With HAVEHT now available (proven in test.221) AND log volume tamed,
we should see firmware progress **past** the previous stall points:

1. Pre-release `clk_ctl_st` reproducibly = HAVEHT=YES (regression check).
2. ARM CR4 release proceeds (as before).
3. Post-release TCM probes: we expect some cells that were UNCHANGED
   in tests 184–197 to now change — firmware reaching NVRAM parser,
   mailbox setup, or even initial console output.
4. D11 wrapper might exit RESET (was held at 0x01 through test.185).

### Decision tree

| Post-dwell observation | Interpretation |
|---|---|
| TCM cells change, mailboxint bits set | Firmware running further — advance to next mailbox/state probe |
| Same TCM as test.184 (pmucontrol bit-9 flip only) | HAVEHT not sufficient; inspect other resource deps (D11 reset, GCI, otp) |
| Host crashes again during dwell | Tighten log further or comment out the entire fw-sample block |
| Chip reports AER / MCE | HT clock mask was too aggressive — back off to max-only |

### Run plan

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts:
- `phase5/logs/test.222.run.txt`
- `phase5/logs/test.222.journalctl.txt` (post-run grep)
- `phase5/logs/test.222.journalctl.full.txt` (post-run full boot dump)
- On crash: capture from `journalctl -k -b -1` next boot.

---

## POST-TEST.221 (2026-04-22 14:45 BST) — ★★ BREAKTHROUGH: HAVEHT=YES after wider PMU masks ★★

### Summary

Test.221 proves the wider PMU resource-mask hypothesis. After widening
both min_res_mask and max_res_mask to 0xffffffff on the BCM4360
ChipCommon PMU (before the firmware download / ARM release), the
ARM CR4 `clk_ctl_st` register reads **0x07030040 = HAVEHT(17)=YES,
ALP_AVAIL(16)=YES** at the pre-halt probe. This is the first time
HAVEHT has ever come up on this chip in this driver — resolves the
test.219 blocker where FORCEHT latched but HAVEHT never asserted.

Machine then hard-hung during `test.188` post-release TCM verification
(256 × pr_emerg fw-sample compare lines pumped into kernel syslog in a
tight loop). User did SMC reset; current boot is clean
(`MAbort- SERR- DevSta clean, LnkSta 2.5GT/s x1`).

### Key log lines (from boot -2, now captured in
`phase5/logs/test.221.journalctl.{txt,full.txt}`)

```
test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11
test.193: PMU WARs applied — chipcontrol#1 0x00000210->0x00000a10
          pllcontrol#6=0x080004e2 #0xf=0x0000000e
test.221: max_res_mask 0x0000013f -> 0xffffffff (wrote 0xffffffff)
test.221: min_res_mask 0x0000013b -> 0xffffffff (wrote 0xffffffff)
test.218: pre-halt CR4 clk_ctl_st=0x07030040
          [HAVEHT(17)=YES ALP_AVAIL(16)=YES BP_ON_HT(19)=no
           bit6=SET FORCEHT(1)=no FORCEALP(0)=no]
```

(FORCEHT=no yet HAVEHT=yes — HT is genuinely available at the PMU,
not a forced latch like test.219.)

### What this means

- The BCM4360 PMU resource registers are not read-only: writing the
  full 32-bit mask is accepted and read-back 0xffffffff (no clobber).
- The chip's default `0x13f / 0x13b` is a conservative mask that does
  not include the HT-clock-backing resource(s). Upstream `brcmfmac`
  never touches these registers, which is why HT never came up.
- With the wider mask the PMU brings up HT — satisfying the clock
  dependency the test.219 ramstbydis wait was blocked on.
- `wl` driver traces (when we get `wl` loading) should show the
  specific bits `wl` sets; our next refinement is to narrow the mask
  from `0xffffffff` to only the bits required. But for *now* the
  broad mask is our unblock.

### Crash cause (our own instrumentation, not the chip)

The hang occurred during `brcmf_pcie_download_fw_nvram` → pre-release
TCM verification, roughly half-way through the 256-entry fw-sample
compare loop (111 `fw-sample` lines logged before freeze). Pumping
256 × pr_emerg at ~3 MB of printk load overwhelms the kernel. Chip
survived; host OS did not.

### Decision: tame diagnostics, re-run as test.222

Minimal diagnostic-only change for next test (PRE-TEST.222):

- `pcie.c` — reduce `nr_fw_samples` **256 → 16** (coverage is
  already known-good from prior tests; 16 × 28 KB across fw is
  plenty to detect a bad write).
- Bump the PMU mask markers `test.221` → `test.222` so we can
  grep-confirm which module loaded (matches workflow from 220→221).
- Everything else unchanged — wider PMU masks stay in; we **want**
  to see whether firmware now makes progress past the previous
  stall points with HAVEHT=YES.

### Risk assessment

- **Chip side:** unchanged from test.221. Wider masks worked once,
  no hardware faults observed.
- **Host side:** reducing log volume ≈16× should drop pre-release
  dwell printk below the danger threshold.
- **If firmware now runs further**, expect to see:
  - TCM writes at previously-unchanged offsets (pmucontrol,
    mailbox, OLMSG area).
  - Possible D11 wrapper exit from RESET (test.185 blocker) once
    firmware reaches BPHY/MAC bring-up.
  - Still possible to hang if firmware issues DMA to an address we
    haven't set up — harness has the BAR0-probe safety gate.

### Run plan

1. Edit `phase5/work/drivers/.../pcie.c` — `nr_fw_samples = 256 → 16`.
2. Edit `phase5/work/drivers/.../chip.c` — bump 2× `test.221` → `test.222`.
3. `make -C phase5/work`
4. `sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh`
5. Capture `phase5/logs/test.222.{run,journalctl,journalctl.full}.txt`

---

## PRE-TEST.221 (2026-04-22 12:30 BST) — rerun wider-mask probe with pr_emerg markers

### What changed vs test.220

**Code change is purely diagnostic visibility**:

- `chip.c` — converted every `brcmf_err("BCM4360 test.XXX: ...")` to
  `pr_emerg(...)`. 11 call sites (test.121, 125, 193, 218, 220 → 221).
  Motivation: `brcmf_err` is gated by `net_ratelimit()` on this NixOS
  6.12.80 kernel (CONFIG_BRCMDBG and CONFIG_BRCM_TRACING are off), so
  most of our diagnostic emissions in test.220 were silently dropped.
- The two PMU mask-write markers (previously test.220) bumped to
  **test.221** so we can trivially confirm the recompiled module
  loaded by grepping for "test.221" in the journal.
- **The experiment itself is unchanged** — still writes
  `min_res_mask = max_res_mask = 0xffffffff` to CC PMU.

### Build state (verified just now)

- `brcmfmac.ko` rebuilt 12:28 Apr 22; vermagic `6.12.80 SMP preempt
  mod_unload` matches running kernel.
- `strings brcmfmac.ko` confirms both `test.221: max_res_mask ...`
  and `test.221: min_res_mask ...`.
- No compile warnings.

### Pre-test hardware state (just checked)

- `lspci -vvv -s 03:00.0`: `MAbort- SERR- CommClk+ LnkSta 2.5GT/s x1
  ASPM L0s L1 Enabled` → clean post-SMC-reset, safe to probe.
- No prior brcmfmac module loaded this boot (lsmod | grep brcm → empty).

### Hypothesis

Now that PMU markers aren't rate-limited, we expect to see — in the
same run, regardless of whether it ultimately crashes:

1. `test.193: chip=0x43a0 ccrev=... pmurev=... pmucaps=...` (re-prints
   the previously-dropped chip/PMU info banner).
2. `test.193: PMU WARs applied — ...` (the pre-existing chipcontrol/PLL
   tweak — was there all along, just not visible in logs).
3. `test.221: max_res_mask 0x0000017f -> 0xXXXXXXXX` — the read-back
   `XXXXXXXX` is *what the chip actually implements* in max_res_mask.
4. `test.221: min_res_mask 0x0000017f -> 0xYYYYYYYY` — the read-back
   YYYYYYYY tells us which bits the PMU will accept as `min` resources.

Then the dwell-probe samples of pmustatus (every 250 ms) tell us which
bits actually came UP under the wider request. Decision tree same as
PRE-TEST.220:

| pmustatus after wider mask | Interpretation |
|---|---|
| more bits UP incl. HT_AVAIL → HAVEHT=1 | mask was the blocker — proceed past ramstbydis |
| more bits UP but HAVEHT still 0 | dependency table unprogrammed — enumerate wl.ko res_dep (Phase 6) |
| pmustatus still 0x2a | wider mask rejected/clobbered — check register semantics |
| crash / SLVERR | mask write itself perturbs device — back off to max-only |

### Known risk

The test.220 run crashed during ASPM disable (after the mask write
completed, given the code ordering). We don't yet know whether the mask
write destabilised the device into the ASPM-time hang. If test.221
crashes the same way, that becomes strong evidence (not yet conclusive)
that the aggressive `0xffffffff` min write triggers it. In that case
next iteration narrows scope to max-only.

### Run plan

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected logs:
- `phase5/logs/test.221.run.txt` — test script stdout
- `journalctl -k -b 0 > phase5/logs/test.221.journalctl.txt` — after run
- If crash, capture from `journalctl -k -b -1` next boot.

---

## POST-CRASH REVIEW (2026-04-22 12:18 BST) — test.220 first-run forensics + new blind-spot finding

Machine just came back from the crash that killed the first test.220 run.
User ran an SMC reset before powering back on. Current state:

- **PCIe clean**: `MAbort- SERR- CommClk+ LnkSta 2.5GT/s x1, ASPM L0s L1 Enabled`
- **Boot -1** (12:14:32–12:14:49, 17 s): the test.220 run. Last line logged:
  `test.158: pci_disable_link_state returned — reading LnkCtl` → boot ends.
  No panic, no oops captured — hard crash/freeze.
- **Boot 0** (12:16:37–now): clean reboot, no brcmfmac activity.

### ★ NEW FINDING — `brcmf_err()` is rate-limited, our test markers are being silently dropped

`debug.h` line 45 defines `brcmf_err` as:

```c
if (IS_ENABLED(CONFIG_BRCMDBG) || IS_ENABLED(CONFIG_BRCM_TRACING) || net_ratelimit())
    __brcmf_err(NULL, __func__, fmt, ...);
```

NixOS kernel 6.12.80 has neither CONFIG_BRCMDBG nor CONFIG_BRCM_TRACING
enabled, so `brcmf_err` only emits when `net_ratelimit()` admits the line.
Under load, most lines are silently dropped.

Evidence from boot -1: `test.119: brcmf_chip_attach returned successfully`
(pr_emerg, always shown) appears at 12:14:46, proving `brcmf_chip_setup` ran
— yet neither `test.193: chip=...` nor `test.220: max_res_mask ...` nor
`test.220: min_res_mask ...` appear anywhere in the 43 brcmfmac log lines
of that boot. These are all `brcmf_err` calls and got eaten by ratelimit.

**Consequence:** the PMU mask write in test.220 almost certainly *did*
execute, but we have zero visibility on read-back values → we cannot
distinguish the test.220 decision-tree branches (A), (B), (mask locked),
(crash-on-mask-write). The crash during ASPM disable may or may not be
related to the mask write — can't tell yet.

### ★ Proposed fix before next test — switch marker macros

Convert all our `brcmf_err("BCM4360 test.XXX: ...")` diagnostic markers
(chip.c — test.121, test.125, test.188, test.193, test.218, test.220)
to `pr_emerg(...)` which is not rate-limited. Restores visibility for
every future test.

**Note to self:** this blind-spot explains several earlier test reports
that said "no messages from X" where we *expected* them. Before trusting
an absence-of-evidence in any log, confirm the marker uses pr_emerg and
not brcmf_err.

### Decision pending user input

Options for next test:

1. **test.221 (recommended)**: switch chip.c markers to pr_emerg, rebuild,
   rerun. Same experimental code (widen both masks), but we'll SEE what
   happens this time. Pure diagnostic change.
2. **test.220 re-run unchanged**: re-run with the same code hoping the
   mask write makes it into the log this time — low-reward, risks another
   crash with no diagnostic gain.
3. **test.221 (narrower)**: keep markers as pr_emerg, but first widen
   ONLY max_res_mask (reading the chip's implemented-bits mirror is
   non-perturbative). Defer the aggressive min_res_mask=0xffffffff until
   we know which bits are implemented. Least aggressive.

Going with option 1 unless user objects — it's the smallest change that
unblocks diagnosis.

---

## PRE-TEST.220 RERUN (2026-04-22 post-crash) — rerun the wider-mask learning probe

System crashed between commit `ae29e57` (test.220 PRE code) and the first
run of test.220. Boot -2 journal ended 10:44:18 with the module still
at test.218/219 markers — test.220 code was compiled (brcmfmac.ko
vermagic matches current kernel 6.12.80, `strings` shows test.220
markers) but never insmodded. Boot -1 was a short clean boot with no
brcmfmac activity. Current boot 0 shows PCIe clean: `<MAbort- >SERR-
CommClk- LnkSta Speed 2.5GT/s x1`.

Per user instruction (no SMC reset done): proceeding with test.220.
BCM4360 may carry whatever state the last test.219 run left it in —
but that state is `HAVEHT(17)=0, ALP_AVAIL=YES, FORCEHT latched in CC
only`, not a crash state. The test-brcmfmac.sh pre-MMIO check will
distinguish CTO (device dead) from UR (device alive but rejecting) via
timing, aborting safely if needed.

### Hypothesis (unchanged from original PRE-TEST.220 below)

Writing `0xffffffff` to both CC.min_res_mask and CC.max_res_mask:
- (A) brings up more bits in pmustatus, including HAVEHT → proceed past
  ramstbydis; make the wider mask permanent; or
- (B) leaves pmustatus = 0x2a unchanged → PMU resource dependency
  tables must be programmed (Phase 6 from wl.ko).

Expected log signatures:
- `BCM4360 test.220: max_res_mask 0x0000017f -> 0xffffffff`
- `BCM4360 test.220: min_res_mask 0x0000017f -> 0xXXXXXXXX`
  — the read-back XXXXXXXX tells us which bits the hardware actually
  implements in this register
- pmustatus samples from the existing dwell probe reveal which bits
  come UP under the wider mask

### Build state (verified)

- `phase5/work/drivers/.../chip.c` lines ~1183–1211 contain the
  `0xffffffff` writes (BCM4360 branch)
- `brcmfmac.ko` built 10:43 Apr 22, vermagic 6.12.80 matches running
  kernel; `strings` confirms `BCM4360 test.220` markers

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.220.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.219 (2026-04-22) — FORCEHT latches but HAVEHT never comes up

Decision tree branch **(B)** confirmed.

Single line that decides the test:

```
test.219: FORCEHT write CC clk_ctl_st pre=0x00050040 post=0x00050042
          [HAVEHT(17)=no  ALP_AVAIL(16)=YES FORCEHT(1)=YES]
```

- FORCEHT bit latched correctly (post=0x...42)
- 50 µs after the write: HAVEHT still 0 on CC
- 2 ms + 20 ms + 30 ms later (post-FORCEHT-write probe on ARM CR4):
  HAVEHT still 0
- Throughout the **3 second dwell** ARM CR4 clk_ctl_st = 0x04050040
  (HAVEHT(17)=no, FORCEHT(1)=no — firmware never managed to set
  FORCEHT itself either)
- ASSERT in hndarm.c (ramstbydis) still fires (TCM strings present
  at 0x40300/0x40550/0x40670/0x9cdc0)

**Interpretation:** the HT request *was* made (FORCEHT bit visible
in CC clk_ctl_st), but the PMU did not grant it. This is exactly
decision-tree branch (B): HT clock is gated by a PMU resource
dependency we have not satisfied.

### Smoking-gun PMU dump (already in test.218/219 logs)

```
CC-pmustatus    = 0x0000002a    # bits 1, 3, 5 UP only
CC-min_res_mask = 0x0000017f    # bits 0,1,2,3,4,5,6,8 REQUESTED
CC-max_res_mask = 0x0000017f
CC-pmucontrol   = 0x01770181 → 0x01770381 (bit 9 toggles)
```

Bits 0, 2, 4, 6, 8 are requested by min_res_mask but NEVER come up
in pmustatus. Bit 6 is the typical HT_AVAIL slot for BCM43xx
families. The lower bits (0,2,4) are the regulator → xtal → ALP
chain HT depends on. PMU is refusing to advance because something
upstream (regulator? xtal_ldo? pll?) isn't satisfied.

The current `min_res_mask = 0x17f` patch in chip.c is therefore
under-spec'd for BCM4360. The proprietary `wl` driver almost
certainly writes a much wider mask (and possibly programs the PMU
resource-up/down/dependency tables before doing so).

---

## PRE-TEST.220 (2026-04-22) — proposed: widen min_res_mask + observe pmustatus

Two-explanation distinguisher (per issue #14 rule):

- (A) Wider min_res_mask makes more pmustatus bits come up and
  HAVEHT eventually appears → driver just needs the right mask
  (and maybe a `wl`-style PMU resource table).
- (B) Wider min_res_mask makes no new pmustatus bits come up →
  PMU dependency tables themselves are unprogrammed; just writing
  the mask is not enough; we need to program PMU `res_dep_mask`,
  `res_updn_timer`, etc. (the full `si_pmu_res_init` sequence).

### Implementation plan for test.220

1. In chip.c BCM4360-specific block, change the existing
   `min_res_mask = 0x17f` write to `min_res_mask = 0xffffffff`
   (or a calculated wider value — start with 0xffffffff to learn
   which bits *can* come up at all).
2. Read `pmustatus` after a settle delay and log which bits became
   UP vs which stayed DOWN. The kernel-side probe already samples
   these every 250 ms during dwell, so adding a wider mask is the
   only patch needed.
3. Bump test markers .219 → .220.

### Decision criteria

| pmustatus after wider mask | Interpretation | Next |
|---|---|---|
| All min_res_mask bits 0..7 UP, HAVEHT(17) on CC clk_ctl_st = 1, ramstbydis ASSERT gone | mask was the only blocker — make wider mask permanent | proceed past ramstbydis to next firmware blocker |
| More bits UP than before but HAVEHT still 0 | dependency table unprogrammed; we got the wrong subset up | enumerate PMU resource table from `wl.ko` (Phase 6 deliverable) |
| pmustatus unchanged from 0x2a | PMU not even accepting wider mask write | check whether min_res_mask register is locked, or wrong CC offset, or write is being clobbered by firmware |
| Crash/SLVERR | timing problem with mask write — defer or stage | revert to 0x17f and look elsewhere |

This is the next intervention test. Awaiting user go-ahead before
implementing — deliberately checking in because the previous
intervention (test.219) showed PMU is not in a freely-acceptable
state and a wider mask write could have side-effects we haven't
modeled.

---

## PRE-TEST.219 (2026-04-22) — force FORCEHT to bring up HT clock

### What POST-TEST.218 just delivered (ROOT CAUSE LOCATED)

Test.218 ran cleanly, no crash. **HAVEHT (bit 17) is stuck CLEAR
chip-wide, throughout the dwell, even pre-halt** — that is the missing
condition firmware is waiting on in ramstbydis.

ARM CR4 clk_ctl_st = **0x04050040** for every probe (52 samples,
3-second window):

```
bit 0  FORCEALP   = no
bit 1  FORCEHT    = no
bit 6  ?          = SET   (pre-existing, chip-wide; also set on CC)
bit 16 ALP_AVAIL  = YES   (always-on low-power clock available)
bit 17 HAVEHT     = no    ← THE MISSING ACK
bit 18 ?          = set   (chip-specific)
bit 19 BP_ON_HT   = no
bit 26 ?          = set   (CR4-specific)
```

ChipCommon clk_ctl_st = **0x00050040** (same minus the CR4-specific
bit 26) UNCHANGED across all 12 dwell ticks. So:
- HT clock is **never enabled chip-wide** during the firmware-active
  window
- ALP works (the always-on clock — what ARM CR4 boots from)
- Firmware boots on ALP, runs ramstbydis, sets bit 6, polls HAVEHT (HT
  acknowledge), times out because HT was never requested/granted

Why HT is missing: `min_res_mask = 0x17f` (bits 0-7) forces a set of
PMU resources, but **none of them request HT_AVAIL** for BCM4360. HT
needs the PLL up; the PLL needs power gated by a higher PMU resource
(roughly bit 8-12 on BCM4360 — exact bit needs confirmation).

D11 expectedly IN_RESET throughout (same as test.217 — firmware never
gets far enough to bring D11 out of reset).

### Implementation plan for test.219

Two-explanation distinguisher: does writing FORCEHT (bit 1) of
ChipCommon clk_ctl_st before `chip_set_active` bring HAVEHT up?

- (A) After write, ChipCommon HAVEHT = YES → HT clock is just unrequested.
  Driver's job is to request it (FORCEHT or proper PMU min_res_mask). If
  ARM CR4 HAVEHT also comes up, ramstbydis should succeed and firmware
  should advance past the assert.
- (B) After write, ChipCommon HAVEHT stays CLEAR → HT request is gated
  by a PMU resource we haven't forced. Need to enumerate PMU resources
  for BCM4360 and find HT_AVAIL bit, then OR it into min_res_mask.

Implementation in chip.c next to the existing `min_res_mask=0x17f`
patch (BCM4360-specific block):

```c
/* test.219: force HT clock by setting FORCEHT (bit 1) of ChipCommon
 * clk_ctl_st. Test.218 proved HAVEHT stuck CLEAR throughout, which is
 * what firmware (ramstbydis) is timing out on.
 */
{
    u32 ccs_addr = CORE_CC_REG(pmu->base, clk_ctl_st);
    /* But pmu->base is for PMU regs. CC clk_ctl_st is in CC core
     * regs, not PMU. Need ChipCommon base, not pmu->base. */
    ...
}
```

Actually safer to do this from pcie.c via `brcmf_pcie_select_core
(BCMA_CORE_CHIPCOMMON) + WRITECC32(clk_ctl_st, ...)`. Add it
immediately before `brcmf_chip_set_active` so the FORCEHT write happens
right before firmware release.

Sequence:
1. Sample CC + CR4 clk_ctl_st pre-write (already done as
   `pre-set-active` probe)
2. WRITECC32(clk_ctl_st, ccs_now | BIT(1))     ← test.219 intervention
3. Sample CC + CR4 clk_ctl_st post-write to confirm HAVEHT comes up
4. Call brcmf_chip_set_active as normal
5. Existing dwell probes record the rest

`min_res_mask = 0x17f` patch retained. Test marker .218 → .219.

### Decision tree

| After FORCEHT write | Interpretation | Next |
|---|---|---|
| CC HAVEHT(17) → 1, CR4 HAVEHT → 1, **firmware ASSERT gone** (different PC or no ASSERT) | root cause confirmed; HT clock was the missing condition | clean up — make FORCEHT a permanent driver-side step; explore proper PMU resource setting; advance to next firmware blocker |
| CC HAVEHT → 1, CR4 HAVEHT → 1, but ramstbydis still asserts at 0x000641cb | HAVEHT alone isn't the polled bit; firmware checks something else | re-decode the SET-bit operation in ramstbydis; check bit 6 vs bit 17 vs others |
| CC HAVEHT stays 0 after FORCEHT | HT request gated by missing PMU resource | enumerate BCM4360 PMU resources; find HT_AVAIL bit; OR into min_res_mask |
| Crash / SLVERR after write | timing-sensitive — defer FORCEHT write to a later point | write after set_active instead |

### Build/run

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.219.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.218 (2026-04-22) — see PRE-TEST.219 above

ROOT CAUSE LOCATED. ARM CR4 clk_ctl_st HAVEHT (bit 17) stuck CLEAR
throughout dwell. ChipCommon clk_ctl_st identical (HAVEHT=0). HT clock
is never enabled chip-wide; firmware (ramstbydis) times out polling for
HT acknowledge. Test.219 intervenes by writing FORCEHT before
set_active.

Bonus: EROM dump in chip_init showed slot[0]=0x18002000 = ARM CR4 base
(NOT D11 base 0x18001000), correctly identifying which core firmware
was polling — see PRE-TEST.218 discussion of the EROM data.

---

## PRE-TEST.218 (2026-04-22) — sample ARM CR4 clk_ctl_st (the actually-polled register)

### What POST-TEST.217 + EROM dump together delivered (BIG pivot)

Test.217 ran cleanly, no crash. Two signals captured:

**1. EROM core enumeration (logged at chip init by chip.c) gives the truth
about wrapper layout AND identifies the polled register's host core:**

```
core[1] id=0x800:rev43  base=0x18000000 wrap=0x18100000  ChipCommon
core[2] id=0x812:rev42  base=0x18001000 wrap=0x18101000  D11 (80211)
core[3] id=0x83e:rev2   base=0x18002000 wrap=0x18102000  ARM CR4
core[4] id=0x83c:rev1   base=0x18003000 wrap=0x18103000  PCIe2
core[5] id=0x81a:rev17  base=0x18004000 wrap=0x18104000  PMU/USB20_DEV
core[6] id=0x135:rev0   base=0x00000000 wrap=0x18108000  unknown
```

Confirms canonical AI layout: **wrap = base + 0x100000** for every core.
Test.114b's old low-window read at base+0x1800 was reading into unmapped
memory; the test.217 high-window read is correct.

**2. The polled register in ramstbydis is NOT D11 — it's ARM CR4.**

Trap data slot[0] = 0x18002000 = **ARM CR4 core base** (not D11 base —
D11 base is 0x18001000). The static-analysis hypothesis "[r5 = chip_info
ptr; *r5 = 0x18002000]" places the polled register at:

```
[*r5 + 0x1e0] = 0x18002000 + 0x1e0 = 0x180021e0 = ARM CR4 + 0x1e0
```

Per BCMA convention, **base + 0x1e0** is the **per-core clk_ctl_st**
register (test.114b decoded the same offset for D11 with bits HAVEHT(17),
ALP_AVAIL(16), BP_ON_HT(19), FORCEHT(1), FORCEALP(0)).

**Revised understanding:** firmware running ON ARM CR4 calls `ramstbydis`
("RAM standby disable" — for ARM CR4's own TCM/data memory), which:
- Sets bit 6 of ARM CR4's clk_ctl_st (chip-specific standby-disable
  request, or related clock-domain request)
- Polls bit 17 (HAVEHT — HT clock available to ARM CR4) for ~20 ms
- If HAVEHT never asserts → ASSERT "v=43, wd_msticks=32"

This re-frames the issue: **the failure is HT-clock distribution to ARM
CR4, not anything about D11.** ARM CR4 wrapper RESET_CTL=0 throughout
(test.188 already shows this); ARM CR4 IOCTL=0x01 (CLK enable only),
IOSTATUS=0. Yet ARM CR4 doesn't see HT clock when it requests one.

**3. ARM exception vectors located at TCM 0x00000:**

8 standard ARM vectors at 0x00..0x1c (Reset, Undef, SVC, PrefetchAbort,
DataAbort, Reserved, IRQ, FIQ). Reset-vector body at 0x20; SVC handler
body around 0x80. `v = %d, wd_msticks = %d` format string still TBD —
deferred (the polled-register identity is now the priority).

**4. ramstbydis trap recurred** — same assert text. Independent of probe
overhead.

### Implementation plan for test.218

Replace `brcmf_pcie_probe_d11_clkctlst()` with `brcmf_pcie_probe_clkctlst()`
that samples **ARM CR4 + 0x1e0** (the actually-polled register) and also
samples D11 + 0x1e0 (kept for context, but expected to skip on
IN_RESET=YES since D11 hasn't been brought out of reset by firmware yet).

For each core:
- Read wrapper RESET_CTL via base + 0x100000 + 0x800 (now confirmed
  layout)
- If IN_RESET=NO, read core register 0x1e0 (low window @ base + 0x1e0)
- Decode clk_ctl_st bits 0,1,6,16,17,19

Call sites unchanged from test.217 (~52 reads per dwell). The dump
range 0x00000..0x01000 stays.

`min_res_mask=0x17f` patch retained. Test marker .217 → .218.

### Decision tree

| ARM CR4 clk_ctl_st observation | Interpretation | Next |
|---|---|---|
| HAVEHT(17) = 0 throughout dwell, FORCEHT(1) = 0 | firmware never set FORCEHT (or its set-bit-6 request didn't translate into HT clock); HT not granted | test.219: write FORCEHT=1 to ARM CR4 clk_ctl_st BEFORE set_active and observe whether assert disappears |
| HAVEHT(17) = 0 throughout, bit 6 = SET | firmware set bit 6, but PMU never granted HT — likely a PMU resource missing | force the relevant PMU resource (research which bit corresponds to HT for CR4); add to min_res_mask |
| HAVEHT(17) = 1 at any sample | HT clock IS available at probe time; firmware's poll missed it OR firmware reads via a different path; re-examine the SET-bit semantics | examine the bit-6 set vs poll timing; consider firmware-side race |
| ARM CR4 clk_ctl_st reads 0xffffffff or seems garbled | wrapper window guess wrong for CR4 (already disproved by test.169 / EROM) | unlikely — re-check |
| ChipCommon clk_ctl_st (existing sample) shows HAVEHT but ARM CR4 doesn't | HT enabled at chip level but not at CR4 — clock-domain partition issue | inspect PMU resources gating CR4-specific clock |

### Build/run

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.218.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.217 (2026-04-22) — see PRE-TEST.218 above

D11 wrapper readings (high window) report IN_RESET=YES throughout the
3-second dwell — internally inconsistent with test.114b's older
low-window reading. Test.218 distinguishes which window is real before
re-attempting the bit-17 hypothesis. ARM exception vectors located.

---

## PRE-TEST.217 (2026-04-22) — REVISED per issue #14: high-yield D11 clk_ctl_st probe

### Plan revision rationale (issue #14 alignment)

Issue #14's decision rule — **"no new test unless it distinguishes between
two concrete explanations"** — flags the originally staged test.217 plan
(dump 0x00000..0x01000 to find the `"v = %d, wd_msticks = %d"` format
string) as **low yield**:

- We already know `v=43`=ccrev (loaded by LDR at 0x64186 from chip_info[0x14])
- We already know `wd_msticks=32`=20ms timeout (matches the polling loop
  decoded from ramstbydis: max 2000 iterations × 10µs)
- Locating the literal merely confirms what we already understand; it does
  not move us toward identifying the missing condition

**Higher-yield test:** identify which register `[r5+0x1e0]` actually points
to during firmware's polling loop. Test.216 trap data at offset 0x9cfe0:

```
slot[0] = 0x18002000   ← D11 core base (chip_info[0x78])
slot[1] = 0x00062a98   ← chip_info struct ptr
slot[2] = 0x000a0000   ← TCM top
slot[3] = 0x000641cb   ← trap PC inside ramstbydis
```

Slot[0]=0x18002000 strongly implies `r5 = &chip_info[0x78]` and the polled
register is **D11 base + 0x1e0**.

**Critical existing context (line 2778):** `0x1e0` from any BCMA core base
is the per-core `clk_ctl_st` register. Bit 17 = HAVEHT (have HT clock).
Test.114b at line 2781 already reads this safely (with IN_RESET guard).

So the firmware's poll is most likely:
- Set bit 6 of D11.clk_ctl_st (request RAM standby — bit 6 is chip-specific
  but appears in the same register)
- Wait up to 20ms for HAVEHT (bit 17) to go HIGH (or for an ack bit)
- If it never asserts → ASSERT "v=43, wd_msticks=32"

### What POST-TEST.216 delivered (still valid)

Test.216 ran cleanly with `min_res_mask=0x17f`. Same trap (PC 0x000641cb,
`v = 43, wd_msticks = 32`). Dumped 0x01000..0x02000.

**helper_C @ 0x011E8 fully decoded** as a printf("ASSERT in file %s line %d
(ra %p, fa %p)") wrapper followed by `SVC #0` to the trap handler. So
helper_C ONLY emits the "ASSERT in file..." line; the `v = %d, wd_msticks
= %d` text comes from the SVC trap handler in 0x00000..0x01000 (still
unmapped, but now lower priority).

**0x01ADC entry** is a non-leaf wrapper calling 0x001EC in low TCM.

### Implementation plan for test.217 (REVISED — high yield)

Two probes, ordered by yield:

1. **PRIMARY: D11 clk_ctl_st (0x1e0) sampling during dwell.** New helper
   `brcmf_pcie_probe_d11_clkctlst()` that mirrors the test.114b pattern:
   - Select BCMA_CORE_80211, read wrapper RESET_CTL first to confirm
     IN_RESET=NO (avoid PCIe SLVERR if D11 is in reset — killed test.115).
   - If safe, read core register at offset 0x1e0 and decode bits 0..2,
     6, 16, 17, 19 (FORCEALP, FORCEHT, FORCEILP, ?, ALP_AVAIL, HAVEHT,
     BP_ON_HT).
   - Restore CHIPCOMMON window when done.

   Call sites:
   - `pre-set-active` (baseline)
   - `post-set-active-20ms`, `post-set-active-100ms`
   - Once per `tier1` iteration (10 × 5 ms — covers ~100-150 ms)
   - Once per `tier2` iteration (30 × 50 ms — covers ~150-1650 ms)
   - Once per dwell tick (12 × 250 ms — covers ~1750-3000 ms)

   Total: ~52 reads — safe (CC sample already runs at every tick without
   issue per test.196).

2. **SECONDARY (cheap, kept): low TCM dump 0x00000..0x01000** for SVC
   handler context (free with the existing dump_ranges loop).

`min_res_mask=0x17f` patch retained. Test marker .216 → .217.

### Decision tree

| D11 clk_ctl_st observation | Interpretation | Next test |
|---|---|---|
| Bit 17 (HAVEHT) STAYS CLEAR throughout dwell | D11 never receives HT clock — PMU isn't gating HT to D11, or D11's CCR clock-request bit isn't set | inspect/force PMU resource bits gating D11 HT, or pre-set D11 FORCEHT before set_active |
| Bit 17 oscillates / drops to 0 just before assert | Standby-request handshake doesn't ack | locate which bit firmware sets at +0x1e0 (likely bit 6) and inspect ack semantics |
| Bit 17 stays SET continuously | Polled register is NOT D11.clk_ctl_st — slot[0]=D11 base is a back-ref | re-decode chip_info[+0x78..0xa0] and find the real polled core |
| Read of D11+0x1e0 returns 0xffffffff | D11 went IN_RESET after set_active | check D11 wrapper RESET_CTL transitions over dwell |

### Build/run

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.217.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.216 (2026-04-22) — see PRE-TEST.217 above

helper_C @ 0x011E8 is a printf+SVC wrapper. Format string `v = %d,
wd_msticks = %d` not in 0x01000..0x02000 — emitted by SVC trap handler in
0x00000..0x01000. Plan revised per issue #14 to focus on identifying the
polled register directly via D11 clk_ctl_st sampling.

---

## PRE-TEST.216 (2026-04-22) — dump early TCM (0x01000..0x02000) to find helper_C + format string

### What POST-TEST.215 just delivered (HUGE — full ramstbydis decode)

Test.215 with `min_res_mask=0x17f` patch and dump range `0x41000..0x42000`.
Same trap as before (PC 0x000641cb, "v = 43, wd_msticks = 32"). Behavior
unchanged. But the code/data analysis broke open the function.

**Format string `"v = %d, wd_msticks = %d"` STILL not found.** 0x41000..0x42000
contained:
- AI core wrapper register format strings (0x41000-0x4147f) — extension of test.214 area
- `ai_core_disable` function name string at 0x41488
- `bcm_olmsg` (offload message) subsystem strings (0x41490-0x41b2f)
- `bcm_rpc_*` (inter-CPU RPC) subsystem strings (0x41b30-0x41ff0)

So the format string is NOT in the firmware's "main rodata" string slab
(0x40000-0x42000). Two remaining places to hunt:
- **Early TCM 0x01000-0x02000**: where helper_C (0x011E8) and the delay
  function (0x01ADC) live. printk-style helpers often have their format
  strings inline near the function.
- **Later string region 0x42000+**: bcm_rpc strings continue past 0x42000

### MAJOR BREAKTHROUGH: ramstbydis function fully decoded

By cross-referencing the literal pool entries at 0x64234..0x6423c and
disassembling 0x64180..0x641cf:

| Address | Literal | Meaning |
|---|---|---|
| 0x64234 | 0x00040671 | → "hndarm.c\0" (file name) |
| 0x64238 | 0x0004067a | → "ramstbydis\0" (function name — confirmed!) |
| 0x6423c | 0x00017fff | (mask or threshold value, TBD) |

**Disassembled flow of asserting function `ramstbydis(arg0=r4, arg1=r5)`:**

```
0x64180  MOVS  r2, #0
0x64182  STR.W r2, [r3, #0x1e0]          ; clear something at off 0x1e0
0x64186  LDR   r2, [r4, #0x14]           ; r2 = chip_info[0x14] = ccrev (43)
0x64188  CMP   r2, #39                   ; ccrev <= 39?
0x6418a  BLE   0x64198                   ; if so, skip set-bit step
0x6418c  LDR.W r2, [r3, #0x1e0]          ; (ccrev > 39 path) read register
0x64190  ORR.W r2, r2, #0x40             ; SET bit 6
0x64194  STR.W r2, [r3, #0x1e0]          ; write back — initiates the action
0x64198  MOVW  r6, #0x4E29               ; loop counter = 20009
0x6419c  B     0x641a6                   ; skip first delay
0x6419e  MOVS  r0, #10                   ; delay arg = 10 (µs)
0x641a0  BL    0x01ADC                   ; delay 10 µs (helper at 0x01ADC)
0x641a4  SUBS  r6, r6, #10               ; counter -= 10
0x641a6  LDR   r3, [r5, #0]              ; reload base addr
0x641a8  LDR.W r2, [r3, #0x1e0]          ; read polled register
0x641ac  TST   r2, #0x20000              ; check bit 17
0x641b0  BNE   0x641b6                   ; if SET, exit loop
0x641b2  CMP   r6, #9                    ; counter check
0x641b4  BNE   0x6419e                   ; if r6 != 9, loop
0x641b6  LDR.W r3, [r3, #0x1e0]          ; re-read register
0x641ba  TST   r3, #0x20000              ; re-test bit 17
0x641be  BNE   0x641ca                   ; if STILL SET, branch out (no assert)
0x641c0  LDR   r0, [PC, #0x70]           ; r0 = "hndarm.c"
0x641c2  MOVW  r1, #397                  ; r1 = 397 (line)
0x641c6  BL    0x011E8                   ; call helper_C — ASSERT path
0x641ca  LDR   r3, [r4, #0x48]           ; (post-assert; trap ra ends here)
0x641cc  TST   r3, #0x100
```

### What this tells us

1. **The function is called twice with two pointers** — `arg0=r4` (chip_info
   struct ptr 0x62a98) and `arg1=r5` (some other base — `*r5` = base address
   of a core whose register at offset 0x1e0 we poll).

2. **For BCM4360 (ccrev=43 > 39): the function FIRST sets bit 6** of
   `[*r5 + 0x1e0]`, **then waits up to 20 ms** for bit 17 of the same
   register to become SET (poll every 10 µs, max 2000 iterations).

3. **The assert fires when bit 17 stays CLEAR** for the full 20 ms timeout —
   i.e., the action initiated by setting bit 6 never produces the bit-17 ack.

4. **`v = 43` is `chip_info[0x14] = ccrev`** — loaded into r2 by the LDR at
   0x64186. This value gates the ccrev>39 path. v in the assert message is
   diagnostic context: "I'm in the ccrev>39 branch, ccrev was 43".

5. **`wd_msticks = 32`** — likely a global watchdog tick count (2000 polls
   × 10 µs = 20000 µs = 20 ms ≈ 32 ticks at 1.6 ms/tick — the firmware
   watchdog interval).

6. **Function name is literally `ramstbydis`** (confirmed via literal pool).
   Searches in `wl.ko` disassembly for this symbol should locate the source.

### What we still need

- **What register at offset 0x1e0 of `*r5`?** Knowing `r5` (arg1 of
   ramstbydis) tells us which subsystem hangs. Candidates:
   - D11 base 0x18002000 — register `D11_*_0x1e0` (TBD)
   - PMU PLL ctrl block (within ChipCommon)
   - Some other backplane core
- Need to find the CALLER of ramstbydis (where it gets r4, r5 args from).
   The function is at 0x64028..0x6422a; callers will load both pointers
   then `BL 0x64028`. Need to dump callers (in 0x40000-0x60000 code area).

### Implementation plan for test.216

**One probe + one chip_info[0x48] interpretation:**

1. **Dump early TCM 0x01000..0x02000** (4 KB, ~256 dump lines). Goals:
   - Locate helper_C function body (at 0x011E8)
   - Locate delay function body (at 0x01ADC)
   - Find any rodata literals near these helpers — esp. "v = %d, wd_msticks
     = %d" or similar format templates
   - Identify symbol that matches "wd_msticks" global

2. **Decode chip_info[0x48] = 0x00008a4d**: 35405 Hz ≈ ILP clock measured
   frequency (nominal 32768, +8% drift). If true, this is the firmware's
   measured ILP rate used for delay loops. Document it as a candidate
   interpretation; can verify later by comparing to PMU IlpCycleCount reg.

`min_res_mask=0x17f` patch retained. Test marker .215 → .216. One new
dump_ranges entry.

### Decision tree

| Find | Interpretation | Next |
|---|---|---|
| `"v = %d, wd_msticks = %d"` literal in 0x01000..0x02000 | format string located | trace its caller (likely helper_C); decode helper_C wraps printf |
| Helper code visible but no v/wd_msticks string | format is elsewhere (BSS data init? or 0x42000+) | dump those next |
| Different format like "%s assert: v=%d wdms=%d" | partial match — same vars, different wording | shift hunt to broader rodata |

### Build/run

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.216.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.215 (2026-04-22) — see PRE-TEST.216 above for full decode

Same trap behavior as .211/.212/.213/.214 (PC 0x641cb, "v = 43, wd_msticks =
32"). All findings fold into PRE-TEST.216. Two highlights worth pulling out:

- **`ramstbydis` (function name) confirmed via literal pool entry at 0x64238**
  pointing to TCM[0x4067a] = "ramstbydis\0". This is the canonical Broadcom
  name for the function.
- **`v = ccrev = 43`** definitively identified via LDR at 0x64186 from
  chip_info[0x14].

---

## PRE-TEST.215 (2026-04-22) — widen format-string hunt + dump chip-info struct in detail

### What POST-TEST.214 just delivered

Test.214 added one new dump range `0x40700..0x41000`. Outcomes:

1. **Format string `"v = %d, wd_msticks = %d"` NOT in 0x40700..0x41000.** Hunt
   continues — likely lives in the larger string area between 0x41000 and ~0x42000+.

2. **Firmware version string FOUND: `PCI.CDC.6.30.223 (TOB) (r)`** at 0x40b8x.
   Matches the last broadcom-sta release (September 2015, v6.30.223.271).
   Confirms our firmware blob and proprietary `wl` driver share the same
   ARM-side codebase. **Major reference data point** — anything we learn from
   wl driver-side disassembly applies directly to this firmware's code.

3. **AI core wrapper register layout discovered.** A long format-string block
   at 0x40e?? enumerates wrapper register names that firmware can dump for
   diagnostics: `Core ID, addr, config, resetctrl, resetstatus, ioctrl,
   iostatus, errlogctrl, errlogdone, errlogstatus, intstatus, errlogid,
   errloguser, errlogflags, errlogaddr, oobselin{a,b,c,d}{30,74},
   oobselout{a,b,c,d}{30,74}, oobsync{a,b,c,d}, oobseloutaen, oobaext...`
   This is the ChipCommon AI (AXI Interconnect) wrapper register set —
   useful reference if we later need to decode core-wrapper traps.

4. **Strings between 0x40700-0x41000 are entirely PCIe-dongle subsystem**:
   `pciedngl_isr/open/close/probe/send`, `bcmcdc.c`, `dngl_rte.c`,
   `proto_attach`, `dngl_devioctl`, `dngl_attach`, etc. This is the FullMAC
   protocol layer — not where ramstbydis lives.

5. **Behavior unchanged**: same trap PC `0x000641cb`, same assert message
   `v = 43, wd_msticks = 32` (only the leading firmware timestamp differs:
   141678.495 in test.214 vs 141331.301 in test.213). Confirms test.214's
   dump-only change had zero firmware impact, and that v=43 is **invariant
   across runs** — strong indicator v is a constant (chiprev or expected
   value), not a polling counter.

### Refinements to working theory

- Polling loop reads `[r3, #0x1e0]` where r3 = `*arg1` of asserting function
  (set at 0x6402e: `MOV r5, r1; ... LDR r3, [r5, #0]`). arg0 (saved as r4)
  appears in trap PC neighborhood: `LDR r3, [r4, #0x48]` at 0x641ca.
- BL at 0x641c6 → 0x011E8 (helper_C, the printf logger from test.211)
- The literal pool entry loaded into r0 right before the BL points to
  `"hndarm.c"` at 0x40671 (file name for the assert)
- The `"v = %d, wd_msticks = %d"` format string is not loaded by any literal
  pool entry in the asserting function — meaning it's emitted by a separate
  trap handler (probably automatic for any `ASSERT()` call) that reads global
  variables `v` and `wd_msticks`. Finding the string would still narrow the
  context.

### Implementation plan for test.215

**Two complementary probes in one test:**

1. **Continue format-string hunt**: dump `0x41000..0x42000` (next 4 KB; the
   PCIe-dongle string slab in 0x40700..0x41000 strongly suggests larger
   string clusters live ahead — and "v = %d, wd_msticks = %d" plus other
   trap-handler text likely cluster together).

2. **Dump arg0 (chip-info struct) in detail**: trap data slot[1] = 0x00062a98.
   We have `0x62a00..0x62c00` already in dump_ranges, but the post-trap dump
   shows it. Now we know arg0 = chip_info struct base — re-examining its
   contents at offsets 0x48 (used by `LDR r3, [r4, #0x48]` at trap PC) and
   the polling pointer field will tell us what hardware register is polled.

   Actually: we already dump 0x62a00..0x62c00 — we just need to **decode**
   the field at offset 0x48 from 0x62a98 = `0x62ae0` from existing data, no
   new MMIO needed.

So test.215 = ONE new dump range `{0x41000, 0x42000}`. Plus, in the post-test
analysis, decode the chip-info struct contents we already have.

### Decision tree

| Find | Interpretation | Next |
|---|---|---|
| `"v = %d"` or `"wd_msticks"` literally in 0x41000..0x42000 | format string located | trace what code references it; that's the trap handler — read globals being printed |
| Strings in 0x41000..0x42000 are still PCIe/CDC | format is even further | dump 0x42000..0x43000 in test.216 |
| chip_info[0x48] (= TCM[0x62ae0]) decodes to a register pointer | identifies the polled register subsystem | targeted register-space dump |

### Chip-info struct decoded from existing test.214 dump (no new MMIO needed)

Slot[1] in trap data = `0x00062a98` = chip_info_t base. Decoded layout (offsets
relative to 0x62a98):

| Offset | Value | Likely meaning |
|---|---|---|
| 0x00 | 0x00000001 | flag |
| 0x10 | 0x00000011 | rev (17 — pmurev?) |
| **0x14** | **0x0000002b** | **= 43 = ccrev — likely `v` printed in assert** |
| 0x18 | 0x58680001 | packed |
| 0x1c | 0x00000003 | chiprev |
| 0x20 | 0x00000011 | rev (17) |
| 0x30 | 0x000014e4 | PCI vendor ID (Broadcom) |
| 0x3c | 0x00004360 | chip ID |
| 0x40 | 0x00000003 | chiprev |
| **0x48** | **0x00008a4d** | **loaded by trap PC `LDR r3, [r4, #0x48]`** |
| 0x58 | 0x00096f60 | TCM ptr (near console buffer at 0x96f78) |
| 0x6c | 0x0009d0c8 | TCM ptr |
| 0x78 | 0x18002000 | core base table starts here |
| 0x7c | 0x18000000 | ChipCommon base |
| 0x80..0x8c | 0x18001000..0x18004000 | core base list |

**Two big findings from this decode:**

1. **`v=43` is BCM4360's `ccrev` (ChipCommon revision)** — confirmed from the
   field at offset 0x14 holding 0x2b = 43. This matches Broadcom's documented
   ccrev=43 for chiprev=3 of BCM4360. So the assert prints ccrev for
   diagnostic context — it's NOT the failed condition. The actual failure is
   the polling loop on `[r3, #0x1e0]`.

2. **chip_info[0x48] = 0x00008a4d** — too low to be a register pointer (would
   need 0x18xxxxxx for backplane). Could be a measured ILP frequency
   (35405 Hz ≈ 32768 nominal +8% drift), or a calibration value. Not
   immediately actionable but recorded for future cross-reference.

3. **Core base table at offset 0x78+** confirms standard Broadcom backplane
   layout: D11 at 0x18002000, ChipCommon at 0x18000000, etc. This means the
   polled register `[r3, #0x1e0]` likely lives in one of these cores —
   reading them at trap time would show stuck status bits.

### Build/run

`min_res_mask=0x17f` patch stays in place. Add one dump_ranges entry, bump
markers .214 → .215.

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.215.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.214 (2026-04-22) — fw version 6.30.223 located; format string still hiding

Logs: `phase5/logs/test.214.{run,journalctl,journalctl.full}.txt`. Test ran
cleanly; same trap behavior as test.213 (bit-for-bit identical trap PC and
assert text apart from firmware-internal timestamp prefix).

### Sanity check

- All 12 dwell ticks completed
- res_state stable at 0x17f (bit 2 still pinned by min_res_mask=0x17f)
- KATSKATS canary intact
- Trap PC: `0x000641cb` (same as .211/.212/.213)
- Assert text: `"... v = 43, wd_msticks = 32"` (same v, same wd_msticks)

### New strings cataloged from 0x40700..0x41000

Five distinct string clusters identified (decoded from hex+ASCII dump):

**0x40700-0x408xx — extension of PCIe-dongle subsystem strings**
- `extpktlen %d`, `dngl_dev_ioctl:`, `pciedngl_isr exits`, `partial pkt pool allocated`
- `dngl_attach failed`, `pcidongle_probe:hndrte_add_isr failed`
- `pciedngl_close/ioctl/send/probe/open`, `proto_attach`
- `bcmcdc.c`, `bad return buffer`, `out of txbufs`, `bad packet length`, `bad message length`
- `bus:`, `dngl_finddev`, `dngl_devioctl`, `dngl_binddev`, `dngl_sendpkt`
- `vslave %d not found`, `pkt 0x%p; len %d`, `QUERY`, `dngl_rte.c`, `ioctl %s cmd 0x%x, len %d`,
  `status = %d/0x%x`, `MALLOC failed`, `flowctl %s`, `dropped pkt`, `unknown`

**0x40b80-0x40bxx — firmware version + admin strings**
- `Broadcom`, `Watchdog reset bit set, clearing`, `PCI.CDC.6.30.223 (TOB) (r)`,
  `c_init: add PCI device`, `add WL device 0x%x`, `rtecdc.c`,
  `device binddev failed`, `PCIDEV`, `device open failed`, `netdev`

**0x40d??-0x40e?? — manufacturer + device-name format**
- `manf`, `%s: %s Network Adapter (%s)`, `RTEGPERMADDR failed`,
  `dngl_setifindex`, `dngl_unbinddev`

**0x40e??-end — ai_core_reset diagnostic dump format**
A massive printf format-string for dumping AI (AXI) core-wrapper registers.
Fields enumerated: `Core ID`, `addr`, `config`, `resetctrl`, `resetstatus`,
`resetread/writeid`, `ioctrl`, `iostatus`, `errlogctrl/done/status`,
`intstatus`, `errlog{id,user,flags,addr}`, `oobselin/out{a,b,c,d}{30,74}`,
`oobsync{a,b,c,d}`, `oobselout{a,b,c,d}en`, `oobaext...`. This is the
ChipCommon AI wrapper register set — useful reference for backplane decoding.

### Critical confirmation: firmware = wl driver firmware

The `PCI.CDC.6.30.223` string matches broadcom-sta v6.30.223.271 exactly
(September 2015 final release). Two implications:

1. Anything reverse-engineered from the proprietary `wl` ARM-side code IS
   directly applicable to this firmware (same codebase, same symbols)
2. The "ramstbydis" function we're hitting is part of the unified
   wl/firmware codebase, so symbol-name searches in `wl.ko` disassembly
   should find it

### Behavioral invariants confirmed across .211/.212/.213/.214

| Quantity | Value | Implication |
|---|---|---|
| Trap PC | `0x000641cb` | Same instruction asserts every time |
| `v` in assert | `43` | Constant; not a varying counter or register read |
| `wd_msticks` | `32` | Constant (fixed timeout) |
| Trap data slot[0] | `0x18002000` | D11 base addr (chip layout) |
| Trap data slot[1] | `0x00062a98` | chip-info struct ptr (constant alloc) |
| Trap data slot[2] | `0x000a0000` | TCM top |

`v=43` being constant strongly suggests it's `ccrev` or a similar
chip-identification value — possibly being printed for diagnostic context,
not as the failed condition itself.

---

## PRE-TEST.214 (2026-04-22) — locate "v = %d, wd_msticks = %d" format string + decode polled register

### What POST-TEST.213 just delivered

Three concrete results from forcing `min_res_mask = 0x17f`:

1. **PMU bit 2 IS controllable.** Pre-release snapshot shows res_state went from
   the long-standing `0x17b` to `0x17f` — bit 2 asserted as soon as the host
   wrote min_res_mask. Stayed at 0x17f across all 12 dwell ticks. So the chip
   *can* hold bit 2; nothing was missing in OTP/PLL config.

2. **Bit 2 was a coincidence — not the polling target.** Despite res_state now
   matching max_res_mask perfectly, firmware **still asserts at the same exact
   instruction** (trap PC `0x000641cb` = 0x641ca | thumb-bit) — bit-identical
   to test.211 and test.212.

3. **Full assert message decoded** from trap-text dump (0x9cdb0..0x9ce10):
   ```
   141331.301 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)

   v = 43, wd_msticks = 32
   ```
   - `v = 43` is the value firmware read from the polled register (or a count of
     retries) — meaning is unknown until we find the format string
   - `wd_msticks = 32` is a **software** watchdog timeout in milliseconds
     (note: `pmuwatchdog` is 0, so this is firmware-managed)
   - "ramstbydis" from earlier dump turns out to be the **function name**, not
     the assert text. Firmware string area at 0x40670 has it as
     `.hndarm.c\0ramstbydis\0pciedngl_isr...` — NUL-separated, so "ramstbydis"
     is just the symbol containing the assert.

### The new question

What does `v = 43` actually represent? Three candidates:
- **(a)** Value read from the polled hardware register `[r3, #0x1e0]`
  — an unexpected value where firmware expected 0 (or a specific other value)
- **(b)** Count of polling-loop iterations before timeout (the polling loop
  actually ran 43 times in 32 ms = ~745µs/iteration, plausible for an MMIO
  read + condition check)
- **(c)** Some chip identifier (note: `ccrev = 43`, suspicious coincidence)

The format string `"v = %d, wd_msticks = %d\n"` was NOT in our 0x40000..0x406c0
strings dump. It lives in firmware text we haven't scanned. Finding it would
tell us:
- The exact context (which subsystem's wait timed out)
- Whether v is a register read or a counter
- Possibly the polled register's name in source

### Implementation plan for test.214

**Single new dump range** added: `0x40700..0x41000` (768 bytes / 48 rows). This
is the firmware string area immediately after our existing 0x40000..0x406c0 dump,
where additional debug strings most likely live (printf templates are typically
co-located with their .c-file groupings).

If "wd_msticks" string isn't in that range, expand to `0x41000..0x42000` in
test.215.

Also: leave `min_res_mask = 0x17f` patch in place. It's been proven safe (no
crash) and proven a useful diagnostic baseline. Future tests inherit it.

### Decision tree

| Find | Interpretation | Next |
|---|---|---|
| Format string contains "wait", "timeout", "poll" | confirms (b) — v is iteration count | derive polling-loop period; trace what hardware bit firmware was waiting for |
| Format string near "regulator", "pll", "xtal" keywords | confirms (a) — v is a register value; tells subsystem | targeted register dump for that subsystem |
| Format string not in 0x40700..0x41000 | strings live further out | dump 0x41000..0x42000 in test.215 |

### Build/run

`min_res_mask=0x17f` patch already committed (chip.c). Adding only one
dump_ranges entry plus marker bumps .213→.214.

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.214.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.213 (2026-04-22) — bit 2 was a coincidence; full assert message decoded

Logs: `phase5/logs/test.213.{run,journalctl,journalctl.full}.txt`. Test ran
cleanly; all 12 dwell ticks completed; KATSKATS canary intact; no machine crash.

### Hypothesis check (forcing PMU bit 2 always-on)

`min_res_mask` write succeeded:
```
test.188: CC-min_res_mask=0x0000017f (pre-release snapshot)   [was 0x13b]
test.188: CC-res_state=0x0000017f (pre-release snapshot)      [was 0x17b]
```

All 12 dwell ticks: `res_state UNCHANGED at 0x17f`, `min_res_mask UNCHANGED at 0x17f`.
Bit 2 stayed asserted the entire run. **PMU side is now pristine: every bit
in max_res_mask is present in res_state.**

### What still failed

Trap data at 0x9cfe0 is **bit-for-bit identical** to test.211 and test.212:
```
0x9cfe0: 18002000 00062a98 000a0000 000641cb
```
- D11 base 0x18002000
- Chip-info pointer 0x00062a98
- TCM top 0x000a0000
- Trap PC 0x000641cb (= 0x641ca | Thumb bit) — same place as before

So firmware is hitting the same assert at hndarm.c:397, regardless of bit 2 state.
**Conclusion: bit 2's stuck-low correlation in test.212 was a coincidence; the
polling target is somewhere else.**

### Bonus — full assert text decoded from 0x9cdb0..0x9ce10

```
141331.301 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)

v = 43, wd_msticks = 32
```

(15 chars at start are likely a firmware-internal timestamp or version.)

This is the most informative fragment we've ever recovered from the trap.
Two new variables surfaced:
- `v = 43` — the value-of-interest at assert time. Could be a register read,
  iteration count, or a chip-related constant. Crucially, **43 == ccrev**.
- `wd_msticks = 32` — software watchdog timeout in ms. Notably, the *PMU*
  watchdog (pmuwatchdog) reads 0; this 32ms timeout is firmware-managed.

The format string `"v = %d, wd_msticks = %d\n"` lives somewhere in firmware
text we have not dumped (not in 0x40000..0x406c0). Finding it would tell us
exactly what `v` represents and bound the polling target's domain.

### Side-finding — earlier "ramstbydis" interpretation refined

The 0x40670 dump showed `.hndarm.c\0ramstbydis\0pciedngl_isr...` (NUL-separated).
"ramstbydis" is **the function name** containing the assert at line 397, not
part of the assert message. So "ramstbydis" = "RAM standby disable" function,
in which line 397's assert checks `v` against a wd-timeout condition.

### Why this is good news

We're closer than ever to the root cause:
- PMU is fully healthy (no stuck resource bits)
- Firmware boots, enters init code, executes `ramstbydis()`, polls something,
  times out at 32ms with `v = 43`, asserts cleanly at hndarm.c:397
- The assert handler runs (trap data + text written), which means firmware
  ARM is alive and console-ring works
- PCIe bus stays healthy after the assert (we read all dumps without MAbort)

The next probe (test.214) just needs to find the format string to learn what
`v = 43` represents.

---

## PRE-TEST.213 (2026-04-22) — force min_res_mask=0x17f to pin PMU bit 2 permanently on

### Breakthrough from POST-TEST.212 dwell snapshots

While planning test.213, I re-examined the existing dwell-PMU snapshots already
captured in test.212 (and identical across .210, .211). At every dwell tick from
250ms to 3000ms, immediately before assert:

```
clk_ctl_st    = 0x00050040
pmucontrol    = 0x01770381   (CHANGED from 0x01770181 — fw set bit 9 = ResReqAlways)
pmustatus     = 0x0000002a
res_state     = 0x0000017b   ← bits 0,1,3,4,5,6,8 set; **bit 2 missing**
pmutimer      = monotonic    (PMU is clocked)
min_res_mask  = 0x0000013b   (we don't write this — PMU default for chip)
max_res_mask  = 0x0000017f   (we write this — bit 6 added)
pmuwatchdog   = 0x00000000
```

`max_res_mask - res_state = 0x17f - 0x17b = 0x4 = bit 2`.

**Bit 2 is requested in max_res_mask but NEVER asserts in res_state, across all
dwell windows in every test since .196.** This is the only stuck-low resource
bit in the entire PMU register set.

The "ramstbydis" assert string (RAM standby DISable) maps semantically: an SRAM
PMU resource that controls standby mode for one of the on-chip RAMs. If firmware
issues "wait for RAM-standby-disable to take effect" → polling loop → res_state
never gets bit 2 set → r7 retry counter exhausts → assert "ramstbydis".

(The exact polling-loop opcode decode for which mask bit is checked is still in
progress — but the *PMU-side observation* of stuck bit 2 is independent of that
decode and stands on its own.)

### Hypothesis for test.213

**Pin bit 2 permanently on via min_res_mask.** Currently we only set
max_res_mask=0x17f (allowing bit 2 to be requested on-demand). If we ALSO
write min_res_mask=0x17f, we tell PMU "bit 2 must always be asserted, drive it
always-on, never let it drop." If bit 2 is enable-able with appropriate
PMU-side wiring/OTP/PLL config that's already present, this forces the issue.

Three possible outcomes:
1. **res_state goes to 0x17f** (bit 2 asserts) AND assert disappears →
   SOLVED — bit 2 was the polling target, firmware now sees its required state
2. **res_state goes to 0x17f** AND assert persists →
   PMU side is fine; polling target was in a *different* register (probably
   D11/PHY); bit 2 was a coincidence
3. **res_state stays 0x17b** (bit 2 still won't assert despite min_res mandate) →
   bit 2 has an unmet hardware dependency (likely a missing PMU chipcontrol or
   pllcontrol entry, OR an OTP fuse that's not populated). Firmware can't
   force what hardware refuses.

### Implementation

Single-line patch to `chip.c` after the existing max_res_mask write:

```c
if (pub->chip == BRCM_CC_4360_CHIP_ID) {
    /* existing: write max_res_mask = 0x17f */
    ...
    /* new for test.213: also pin min_res_mask = 0x17f to force bit 2 on */
    u32 min_addr = CORE_CC_REG(pmu->base, min_res_mask);
    u32 before_min = chip->ops->read32(chip->ctx, min_addr);
    chip->ops->write32(chip->ctx, min_addr, 0x17f);
    u32 after_min = chip->ops->read32(chip->ctx, min_addr);
    brcmf_err("BCM4360 test.213: min_res_mask 0x%08x -> 0x%08x (force bit 2 on)\n",
              before_min, after_min);
}
```

Bump test marker .212 → .213 in chip.c (3 sites) and pcie.c (2 sites). No
dump_ranges change needed — existing PMU snapshot at every dwell tick is
already exactly the diagnostic we need to verify the outcome.

### Risk

Low. Pinning bit 2 in min_res_mask might cause:
- More current draw (bit 2 = always-on RAM standby disable means RAM stays
  active even when firmware goes to sleep) — irrelevant for bring-up
- PMU sequencing issue if bit 2 has prerequisites — but if so, the symptom
  would be `before_min/after_min` mismatch in our trace, easy to diagnose

If outcome 3 (bit 2 won't assert), test.214 will need to find what enables bit 2
(PMU chipcontrol register / pllcontrol / OTP).

### Decision tree

| Outcome | Next test |
|---|---|
| res_state→0x17f + assert gone | **MAJOR WIN** — boot continues, focus on next failure point (BCDC handshake?) |
| res_state→0x17f + assert remains | dump D11/PHY register space to find true polling target |
| res_state→0x17b (bit 2 refuses) | study PMU chipcontrol/pllcontrol enables for bit 2 in BCM4360 wl driver |

### Run command

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild — see reference memory
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.213.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.212 (2026-04-22) — caller of 0x64028 NOT in dumped regions; need different angle

Logs: `phase5/logs/test.212.{run,journalctl,journalctl.full}.txt`. Test ran cleanly,
firmware asserted at hndarm.c:397 ("ramstbydis") as in all prior runs. PCIe bus stayed
healthy (no MAbort, dump phase completed in full).

### Region-by-region findings

**0x40000..0x40660 — firmware string table (not code)**

Contents are exclusively NUL-terminated debug/log strings:
- `0x40000`: "123456789ABCDEF.0123456789abcdef" (hex char tables)
- `0x40020`: "hndchipc.c.reclaim section 1: Returned %d bytes to the heap" (+ section 0 variant)
- `0x40090`: "Memory usage:..Text/Data/Bss/Stack" formatters
- `0x400e0`: "Arena total: %d(%dK), Free: %d(%dK), In use:..." block
- `0x40270`: "No timers..timer %p, fun %p, arg %p, %d ms"
- `0x40300`: "ASSERT in file %s line %d (ra %p, fa %p)" — the ASSERT formatter itself
- `0x40360`: "hndrte.c.No memory to satisfy request..."
- `0x403e0`: "hndrte_init_timer: hndrte_malloc failed"
- `0x40410`: "hndrte_add_isr: hndrte_malloc failed"
- `0x40430`: "mu.lb_alloc: size too big" / "lb_alloc: size (%u); alloc failed"
- `0x40480`: "hndrte_lbuf.c.lb_sane:.."
- `0x40540`: "FWID 01-%x" / "TRAP %x(%x): pc %x, lr %x, sp %x, cpsr %x..."
- `0x4065c`: "deadman"
- `0x40660`: "_to.hndrte_arm.c\0hndarm.c.ramstbydis.pciedngl_isr called.%s called..pciedngl_isr called..%s: invalid IS..."

These are referenced by code via PC-relative literal pools (the printf-style
helpers like helper_C@0x11E8 take string-pointer args). **Not** code.

**0x64280..0x64500 — sibling functions**

- `0x64280..0x642c4`: tail of function whose entry is *before* 0x64280 (continues from
  pre-asserting-fn region 0x6422c-0x64280's `0x64248` PUSH {r3-r9, lr}). Ends with
  `e8bd…83f8` POP.W {r4-r10, pc} idiom at 0x642c0.
- `0x642c4..0x642ec`: literal pool — 0x00058d24, 0x00040980, 0x000408e2, 0x00062a10,
  0x0004098c, 0x000409a0 — pointers to other strings, NOT to 0x64028
- `0x642ec`: tiny inline function: `4a064b05 70197dd1 70597e11 70997e51 70da7e92` —
  load r3,[pc,#0x14]; load r2,[pc,#0x18]; LDRB/STRB chain copying 4 bytes between
  two struct fields; then `bf004770` = NOP + BX LR
- `0x642f0` literal pool: 0x00062eb0, 0x0006beda
- `0x642fc..onward`: new function `4ff0e92d` PUSH.W {r4-r11, lr}; significant body
  with many BL calls (decoded two: BL at 0x64302 → 0x63D9C, BL at 0x644aa → 0x63B3C
  — both backward to **other unscanned addresses**, neither targets 0x64028)

**Post-asserting-function literal pool 0x6422c..0x64248**

`00040671 0004067a 00017fff 00062a08 00062a0c` — string pointers and a 0x17fff
mask. **No 0x00064028 / 0x00064029.** This rules out vtable/jump-table entries
in the asserting function's own pool.

### Cross-region search

Global grep across all test.212 dump rows:
- `00064028` — **zero matches**
- `00064029` — **zero matches**
- BL upper-halfword `f7ff` followed by `fdXX`/`feXX` (small backward branches) —
  two found, both in the new function 0x642fc-, both target other addresses.

### Conclusion

The caller of 0x64028 is in firmware text **outside the regions dumped so far**.
Two unscanned candidate areas remain:
1. **Low text 0x12000..0x40000** (~184KB) — where helper_C at 0x11E8 lives;
   likely contains hndrte_main / pmu_init / boot-init code
2. **Mid text 0x40670..0x63e00** (~145KB) — between strings and asserting fn;
   could contain PMU/PCIe init helpers

Brute-force widening dumps to cover 184KB+ of unscanned text is expensive and
not guaranteed to localize the caller. **Pivoting to a different angle for test.213**:
identify the polled register/bit directly, since the host can manipulate PMU state
even without knowing who scheduled the wait. See PRE-TEST.213 above.

---

## PRE-TEST.212 (2026-04-22) — find the CALLER of asserting function 0x64028

### What POST-TEST.211 just resolved

The three BL targets inside the asserting function (0x64028) are now identified:

| Target | Behavior | Implication |
|---|---|---|
| `0x9956` (helper_A) | `LDR.W r0, [r0, #0xcc]; BX LR` | Tiny getter — fetches a 32-bit field at offset +0xcc from a struct pointer |
| `0x9968` (helper_B) | Table-search loop returning **0x11 as the "not-found" sentinel** | The CMP r0, #0x11 in the asserting fn is "not-found check", **NOT pmurev=17 detection** |
| `0x11E8` (helper_C) | Function with stack frame, calls printf-style logger | Debug log helper — invoked with ("hndarm.c", #0xdf=223) to log a warning |

Critical reframe: the assert path is **not gated on chip-rev** — it's gated on
whether a *table lookup* succeeded. The polling loop at 0x6419e..0x641b8
runs regardless and times out independently.

### Why finding the caller matters

We now know the function body but not what kicks it off. Three possibilities,
each implies a different driver-side fix:

1. **Called once during PMU init** — caller passes (chip_struct, bit_id, mask)
   for some PMU resource the firmware should bring up. If caller's args are
   wrong (driver-side state), we can intercept upstream.
2. **Called from a workqueue / timer** — caller is firmware self-managed,
   nothing the driver can change. Then the only fix is unblocking the polling
   loop's hardware dependency (e.g., the bit at `r3 & 0x80000` not coming on
   may be linked to a clock/PMU resource the host hasn't enabled).
3. **Called from interrupt handler** — caller stack is a snapshot of an IRQ
   path. Less likely given function signature complexity.

### Hypothesis for test.212

Given the assert string "ramstbydis" + the polling loop pattern + the fact
that this fires near the start of firmware boot (no console output is
written before assertion), I expect: **caller is in early boot init,
likely a "ramstandby disable" config function called from `_main`/`hndrte_main`
or `pmu_init`**. The call should be statically resolvable as a single
direct BL/B.W targeting 0x64029 (Thumb bit set).

### Implementation plan

Pure dump expansion — no driver behavior change. Statically scan firmware
text for instruction encodings whose computed target = 0x64029.

For Thumb-2 BL targeting 0x64028 (as Thumb pointer 0x64029), the byte
encoding depends on the instruction's address (signed PC-relative offset).
We have to either (a) dump a wide region and scan for the *value* 0x00064029
(matches function-pointer table entries), or (b) write an offline tool
to compute encoded BL bytes for each potential caller address.

**Approach (a) — dump wide and grep for 0x00064029:**
Add three modest dump regions covering the most likely caller locations
(early boot text):

| Range | Purpose | Size |
|---|---|---|
| `{0x40400, 0x40660}` | Code immediately before the `_to.hndrte_arm.c` strings (hndrte main/init?) | 608 B / 38 rows |
| `{0x64280, 0x64500}` | Code immediately after asserting function (likely sibling functions in same compilation unit) | 608 B / 38 rows |
| `{0x40000, 0x40400}` | First page of code area (boot entry?) | 1024 B / 64 rows |

Cost: +140 dump rows ≈ 35ms additional MMIO. Acceptable.

After this dump, we can grep the captured words for `00064029` (function-pointer
table) AND statically decode visible BL/B.W instructions to compute targets.

### Decision tree

| Find | Interpretation | Next |
|---|---|---|
| Direct BL/B.W to 0x64028 in dumped range | caller located | trace caller's setup; identify what it passes as r0/r1/r2 |
| Function-pointer entry `0x00064029` in dumped range | indirect call via vtable | dump pointer table; trace its construction |
| Neither found | caller is elsewhere in firmware | widen dump or pivot to **Approach (b)**: compile offline tool to brute-force scan all dumps for BL targets matching 0x64028 |

### Run command

```
make -C /home/kimptoc/bcm4360-re/phase5/work    # via kbuild — see reference memory
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.212.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.211 (2026-04-22) — three BL helpers decoded; helper_B is a table-search returning 0x11 sentinel

Logs: `phase5/logs/test.211.{run,journalctl,journalctl.full}.txt`. Test ran
cleanly — no crash. Same firmware (4352pci).

### Static BL decode confirmed by live dump

| BL | Predicted target | Found function entry at target |
|---|---|---|
| 0x64032 | 0x9956 | `LDR.W r0, [r0, #0xcc]; BX LR` (4 bytes) |
| 0x6403e | 0x9968 | `PUSH {r4-r6, lr}; ...` (search loop) |
| 0x6404c | 0x11E8 | `PUSH {r4, r7, lr}; SUB SP, #0x0c; ADD r7, SP, #8; ...` |

All three targets land exactly on real Thumb function entry points — confirms
the BL decode methodology is correct.

### Helper_A at 0x9956 — trivial getter

```
0x9956: f8d0 00cc    LDR.W r0, [r0, #0xcc]    ; load value at offset 204 from struct
0x995a: 4770         BX LR                    ; return
```

Used by the asserting function with `r0 = r4 = arg0` (struct pointer).
Reads field at +0xcc into r0 — the result is then saved in r8 and passed
as arg2 to helper_B at 0x6403e.

### Helper_B at 0x9968 — table search returning 0x11 on not-found

```
0x9968: b570              PUSH {r4-r6, lr}
0x996a: f8d0 50d0         LDR.W r5, [r0, #0xd0]    ; r5 = max iteration count from struct +0xd0
0x9970: 2000              MOVS r0, #0              ; loop index = 0
0x9972: 4603              MOV r3, r0
0x9974: e008              B.N  0x9988               ; jump to loop test
0x9976: f8d4 ????         LDR.W r? , [r4, #?]      ; load table entry
0x997a: 60d4              STR r4, [r2, #0x0c]       ; store
0x997c: 428e              CMP r6, r1                ; compare entry to search key (r1=arg1)
0x997e: d102              BNE.N skip
0x9980: 4293              CMP r3, r2
0x9982: d005              BEQ.N return-found
0x9984: 3301              ADDS r3, #1
0x9986: 3001              ADDS r0, #1               ; ++index
0x9988: 3404              ADDS r4, #4               ; ++table_ptr
0x998a: 42a8              CMP r0, r5                ; index < limit?
0x998c: d3f4              BCC.N -24                 ; loop back
0x998e: 2011              MOVS r0, #0x11           ; set return = 0x11 (NOT-FOUND sentinel)
0x9990: bd70              POP {r4-r6, pc}
```

**Major reframe:** the `CMP r0, #0x11` at 0x64040 in the asserting function is
checking for helper_B's "not-found" sentinel — **NOT** checking pmurev==17.
Earlier hypothesis (test.210) that this gates on chip rev was wrong.

### Helper_C at 0x11E8 — printf-style logger

```
0x11e8: b590              PUSH {r4, r7, lr}
0x11ea: b083              SUB SP, SP, #0x0c
0x11ec: af02              ADD r7, SP, #8           ; r7 = frame pointer
0x11ee: 4603              MOV r3, r0               ; r3 = orig arg0
0x11f0: 460c              MOV r4, r1
0x11f2: 4622              MOV r2, r4               ; r2 = orig arg1
0x11f4: 4619              MOV r1, r3               ; r1 = orig arg0 (file ptr)
0x11f6: 4807              LDR r0, [PC, #0x1c]      ; r0 = format string ptr
0x11f8: 4673              MOV r3, lr               ; r3 = lr (return-addr arg?)
0x11fa: 9700              STR r7, [SP, #0]          ; stack arg
0x11fc: f7ff fc18         BL  <printer>            ; tail call into printer
... continues with restore + return ...
```

The signature is: `helper_C(file_str, line_num)` → calls inner printer with
format string. At call site (0x6404c) it gets `("hndarm.c", 0xdf=223)` —
**a debug log call** at line 223 of hndarm.c. Not the assert; just an info-level
log emitted when helper_B returned not-found.

### Updated picture of asserting function flow

```
PUSH {r4-r10, lr}
r4=arg0(struct*), r5=arg1, r6=arg2
r0 = helper_A(r4)              ; r0 = *(r4 + 0xcc)
r8 = r0
r0 = helper_B(r4, r5, 0)       ; table search; returns 0x11 if not found
r9 = r0
if (r0 == 0x11) {              ; not found case
   helper_C("hndarm.c", 223);  ; log warning
}
... (continues regardless) ...
... (eventually: polling loop with r7 as retry counter) ...
if (r7 exhausted) ASSERT("ramstbydis", line 397);
POP {r4-r10, pc}
```

### So the assert root cause is NOT the table-search miss

It's the polling loop timing out — exact bit polled: `r3 & 0x80000` after
loading r3 from `[r4, #0x4c]` (or possibly from a chip register through
indirect path). Need test.212 to find the *caller* of this whole function
to know what register/bit is being polled and what the firmware expected
to come up.

### Other state

- All other dump regions (chip-info, trap data, NVRAM) unchanged from test.210
- fine-TCM scan: 7 cells CHANGED — same as test.210 (firmware ran briefly,
  ticked timestamps in console area, asserted)
- Trap data at 0x9cfe0 unchanged: `18002000 00062a98 000a0000 000641cb`

---

## PRE-TEST.211 (2026-04-22) — decode BL targets in asserting function; identify what it polls

### Context

POST-TEST.210 (below) located the asserting function:

- **Entry:** `0x64028` — `PUSH.W {r4-r10, lr}`
- **Exit:** `0x6422a` — `POP.W  {r4-r10, pc}`
- **Spans:** ~514 bytes (~257 Thumb-2 halfwords)
- **First 3 args** saved into `r4` (struct ptr), `r5`, `r6` at function entry
- **Asserts** at 0x641c6 with `r0 = "ramstbydis"`, `r1 = #0x18d` (line 397)

We have 0x64028..0x64280 already in the dump from test.210. The next missing
puzzle pieces are:

1. **What does `r4` (the struct pointer arg) point at?** It is used in the
   polling loop (`LDR r3,[r4,#0x4c]; TST r3,#0x100`) and elsewhere via small
   field offsets. The chip-info struct at `0x62a98` is one candidate, but the
   function's own literal pool (0x64238..0x64244) holds pointers to `0x62a08`
   and `0x62a0c` — different addresses inside the same struct page.
2. **Where do the BL calls in 0x64030..0x64080 go?** The first BL (at 0x64030)
   is followed by a `CMP r0, #0x11; BNE` → if the call returns ≠ 0x11, the
   alternate path (which contains the assert) gets reached. Decoding the BL
   target reveals which firmware helper is being called.
3. **Where is the function called from?** Once we know its entry (0x64028)
   we can scan the rest of the firmware for `BL`/`B.W` instructions whose
   computed target = 0x64029 (Thumb bit set). That tells us which init phase
   triggers this code path.

### Hypothesis

The assert path is reached when:

- A polling loop (around 0x6419e..0x641b8) waits for hardware bit `r3 & 0x100`
  to clear (or a timer to expire), and falls through with `r7 == 0`
- `r7 == 0` triggers the assert — i.e. the loop ran out of iterations without
  the expected condition occurring

The expression label "ramstbydis" (RAM Standby Disable) suggests the firmware
is waiting on a PMU/RAM-state bit related to standby/wake transitions.
The bit `0x100` checked in `r3` is likely a status flag in the same memory-
mapped register family. From the chip-info struct (test.201/203 dumps) the
field at `+0x4c` is loaded — that's an offset into a per-core or per-block
state record.

### Statically decoded BL targets (no new dump needed)

Decoded the first few Thumb-2 BL instructions in the asserting function from
the test.210 byte dump (PC of BL = inst_addr + 4; signed 25-bit offset):

| BL location | Encoding (hw1, hw2) | Decoded offset | Target |
|---|---|---|---|
| 0x64032 | `f7a5 fc90` | -0x5A6E0 | **0x9956** (helper_A, called with r0=r4=arg0) |
| 0x6403e | `f7a5 fc93` | -0x5A6DA | **0x9968** (helper_B, called with r0=r4, r1=r5, r2=#0; returns code compared to 0x11) |
| 0x6404c | `f79d f8cc` | -0x62E68 | **0x11E8** (helper_C, called with r0=const, r1=#0xdf) |
| 0x64020 | `f7a5 bcc4` | -0x5A6DA | **0x9968** (B.W tail-call from PRIOR function — same target as helper_B!) |

Two strong observations:

1. **Helper_B at 0x9968 returns a code compared against 0x11 (=17).**
   `17 == pmurev` for BCM4360. This BL may be `get_pmurev()` or a chip-config
   probe. If pmurev != 17 (success), the function takes the alternate path
   that contains the polling loop and assert.
2. **Helper_B is also tail-called by a different prior function** (the B.W
   at 0x64020) — so it's a widely-used util, likely a hndrte runtime helper.

The two helpers at 0x9956 and 0x9968 sit only 18 bytes apart — strongly
suggesting they're two adjacent small helpers in a runtime utility region.
helper_C at 0x11E8 is far away (early boot/text region).

### Implementation plan for test.211 (dump-only, no logic change)

Add three small dump regions covering the helper bodies:

| Range | Purpose | Size |
|---|---|---|
| `{0x09900, 0x09a00}` | helper_A (0x9956) + helper_B (0x9968) | 256 bytes / 16 rows |
| `{0x011c0, 0x01240}` | helper_C (0x11E8) | 128 bytes / 8 rows |
| `{0x09c000, 0x09c100}` *(deferred — possibly noise)* | — | — |

Cost: +24 dump rows ≈ 6ms additional MMIO. Negligible.

We can DROP the existing `{0x97000, 0x97200}` console-buffer dump (we already
know it's static "old text" — saves 32 rows) — net savings actually.

### What we'll learn

- **helper_A body** → its role (probably a getter for a struct field, given
  it's called first and saves r0 result into r8)
- **helper_B body** → likely "get pmurev" or similar; if it has a clear
  literal-pool entry pointing to `pmurev` field offset, confirms the theory
- **helper_C body** → why r1=#0xdf is passed; 0xdf may be an init-flag bitmask

### Decision tree

| Find | Interpretation | Next |
|---|---|---|
| BL targets land inside 0x60000..0x70000 (firmware text region) | normal helpers — name them by their entry-point literal pool content | trace what each one does |
| BL targets land outside TCM (e.g. >0xa0000 or <0x40000) | indirect calls via function pointer table — globals-driven | dump pointer table |
| Caller scan finds `BL 0x64028` in init code path | pinpoints the boot phase that triggers this assert | document call-stack and target the *caller's* failure path |
| Caller scan finds no callers in the dumped range | function is reached via function-pointer table | dump pointer tables in known PMU init region |

### Run command (no module rebuild needed if only dump_ranges change)

```
make -C /home/kimptoc/bcm4360-re/phase5/work
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.211.{run,journalctl,journalctl.full}.txt`.

---

## POST-TEST.210 (2026-04-22) — asserting function entry located at 0x64028

Logs: `phase5/logs/test.210.{run,journalctl,journalctl.full}.txt`. Test ran
cleanly — no crash. Same firmware (4352pci) as tests 200-208.

### Result 1 — host-side core enumeration: 6 cores total

Confirmed 6 cores (matches the chip-info struct count):

```
core[1] id=0x800 rev43  base=0x18000000 wrap=0x18100000   ChipCommon
core[2] id=0x812 rev42  base=0x18001000 wrap=0x18101000   PCIe2
core[3] id=0x83e rev2   base=0x18002000 wrap=0x18102000   D11 (radio)
core[4] id=0x83c rev1   base=0x18003000 wrap=0x18103000   ARM CR4
core[5] id=0x81a rev17  base=0x18004000 wrap=0x18104000   PMU/SR
core[6] id=0x135 rev0   base=0x00000000 wrap=0x18108000   GCI/special
```

Reaffirms that the firmware "9-core mismatch" hypothesis from test.207 was
wrong (the "9" lives in the assert format buffer at 0x9cfa8, not a core
count field). Both sides see 6 cores.

### Result 2 — code dump 0x63e00..0x64280 reveals function structure

Multiple Thumb-2 function prologues identified by their PUSH instruction:

| Address | Prologue | Function size | Notes |
|---|---|---|---|
| 0x63e00 | (mid-function from prior dump) | ends at 0x63e36 with `BD1C` (POP {r2-r4, pc}) followed by `bf00 deaddead` | trailing sentinel |
| 0x63e6c | `b570` PUSH {r4-r6, lr} → `4d1a` LDR r5, [PC,#imm] | ~92 bytes (ends ~0x63ed8) | small handler — multiple BL into firmware helpers |
| 0x63fc4 | `2278 4b01 601a 4770` MOVS/LDR/STR/BX LR | 8 bytes | tiny "store r2=#0x78 into ptr" stub — likely a setter |
| 0x63fd0 | `e92d 41f0` PUSH.W {r4-r8, lr} | ~80 bytes (ends 0x6401e with `e8bd 41f0` POP + tail-call B.W at 0x64020) | medium helper |
| **0x64028** | **`e92d 47f0` PUSH.W {r4-r10, lr}** | **~514 bytes (ends 0x6422a with `e8bd 81f0` POP+pc)** | **THE ASSERTING FUNCTION** |
| 0x64248 | `e92d 43f8` PUSH.W {r3-r9, lr} | next function (out of dump scope) | unrelated helper below |

### Result 3 — anatomy of the asserting function

Function prologue (decoded from dump bytes):

```
0x64028: e92d 47f0    PUSH.W {r4-r10, lr}      ; 8-deep frame, lots of saved regs
0x6402c: 4604         MOV r4, r0               ; save arg0 → r4 (struct base)
0x6402e: 460d         MOV r5, r1               ; save arg1 → r5
0x64030: 4616         MOV r6, r2               ; save arg2 → r6
0x64030: f7a5 fc90    BL  <helper_A>           ; first call — uses r0 (arg0)
0x64034: 2200         MOVS r2, #0
0x64036: 4629         MOV r1, r5
0x64038: 4680         MOV r8, r0               ; r8 = result of helper_A (saved)
0x6403a: 4620         MOV r0, r4
0x6403c: f7a5 fc93    BL  <helper_B>
0x64040: 2811         CMP r0, #0x11            ; KEY GATE — expects 17
0x64042: 4681         MOV r9, r0
0x64044: d103         BNE  + (skip-success-path)
0x64046: 481d         LDR r0, [PC, #imm]       ; load constant
0x64048: 21df         MOVS r1, #0xdf
0x6404a: f79d f8cc    BL  <helper_C>           ; conditional helper if r0==0x11
0x6404e: 4649         MOV r1, r9
0x64050: 4620         MOV r0, r4
0x64052: f7a5 fcaa    BL  <helper_D>
... (more BLs, branches to alternate paths) ...
```

The assert call site (already known from earlier tests, confirmed in this dump):

```
0x641c0: 481c         LDR r0, [PC, #0x70]      ; r0 = ptr to "ramstbydis" (0x4067a)
0x641c2: f240 118d    MOVW r1, #0x18d          ; r1 = 397 (line number)
0x641c6: f79d ff80    BL  <_assert>            ; calls assert helper
```

The assert-call target `_assert(expr_str, line)` likely loads `__FILE__`
internally (the `0x40671 → "hndarm.c"` pointer is in the function's literal
pool at `0x64230`, so the function loads it once and passes/uses it
elsewhere — possibly via a global).

Function literal pool (immediately after function body):

```
0x64230: 00040671   ptr to "hndarm.c"
0x64234: 0004067a   ptr to "ramstbydis"   ← the failing-expression string
0x64238: 00017fff   constant (max_res_mask candidate? 0x17fff = 98303)
0x6423c: 00062a08   ptr to chip-info struct field
0x64240: 00062a0c   ptr to chip-info struct field
```

### Result 4 — the assert is preceded by a polling loop with timeout

Code at 0x6419e..0x641c6 (loop body and tail):

```
0x6419e: ...                         ; (loop top — exact body needs deeper trace)
0x641b0: 2e09         CMP r6, #9     ; loop guard
0x641b2: d101         BNE  +2        ; bypass exit-check
0x641b4: f8d3 31e0    LDR.W r3, [r3, #0x1e0]   ; refresh status word
0x641b8: f413 3f00    TST.W r3, #0x80000       ; bit-19 check
0x641bc: d1f3         BNE  -22       ; back to loop top — keep polling
0x641be: 3f00         SUBS r7, r7, #0          ; (set flags from r7)
       wait — at 0x641be the encoding is 0x3f00 = SUBS r7, r7, #0
0x641be: d104         BNE  +8        ; branch past assert if r7 != 0
0x641c0: <ASSERT call sequence — r0/r1 setup>
```

The assert is reached when the **polling loop exits with r7 == 0** —
i.e. retry counter exhausted without the expected `r3 & 0x80000` bit
appearing. (The exact bit being polled is encoded in the `f413 3f00` TST.W
mask — needs full Thumb-2 decode to confirm bit position.)

### Conclusion — moving from "the firmware ASSERTs" to "we know what the assert checks"

| Before test.210 | After test.210 |
|---|---|
| "Firmware halts at hndarm.c:397 with expression unknown" | "Firmware halts in a function at 0x64028, polling a status bit through r4 (struct base, arg0) at offset and timing out after r7 retries — RAM-standby-related" |
| Function entry unknown | Entry confirmed at 0x64028, exits 0x6422a |
| Caller unknown | Still unknown — need to scan code for callers of 0x64028 |
| Helper functions called along the way: unknown | First two helpers called at 0x64030 and 0x6403c with their args saved into r4/r5/r6/r8 |

This unblocks two further investigation paths in test.211 (see PRE-TEST.211
above): (1) what calls the function, (2) what the helpers do.

### Other state in test.210 (no change vs test.208)

- Trap data at 0x9cfe0: `18002000 00062a98 000a0000 000641cb` — same as test.208
- Format buffer at 0x9cf30..0x9cfb0: same structure (line=0x18d, ptr=0x62a08, val=9)
- Console buffer at 0x96f78..0x97200: timestamps `125888.000` and `137635.697`
- fine-TCM scan: 7 cells CHANGED (matches test.208 — firmware ran briefly)
- NVRAM blob at 0x9ff00..0xa0000: present and intact, ends with `ffc70038` marker

---

## PRE-TEST.210 (2026-04-22) — widen code dump to find assert function entry

### Hypothesis

The function containing the BL-to-assert at `0x641c6` starts somewhere
between `0x63e00` and `0x64100`. From earlier dumps:

- `0x64100..0x641df` shows mid-function code (loop with `SUBS r6,#1`,
  `STR r6,[r5,#0x10]`, `CMP r6,#0`, struct accesses through r5).
- `0x641c0..0x641d0` is the assert call site (`MOVW r1,#0x18d`, BL,
  post-BL `LDR r3,[r4,#0x4c]; TST r3,#0x100; BEQ`).
- `0x64238..0x64244` is a literal pool with pointers to "ramstbydis",
  `0x17fff`, `0x62a08`, `0x62a0c`.
- `0x64248` shows `2d e9 f8 43` = `STMDB SP!,{r3-r9,lr}` — clearly the
  **start of a *different* function** below the asserting one.

So the asserting function lives entirely **above 0x64248** and below
its own function entry (which we haven't located yet). Standard ARM Thumb-2
function prologues use `B5xx` (small PUSH) or `E92D xxxx` (PUSH.W) — both
are easy to spot byte-wise.

If we can find this function's entry, we get:

- The **prologue's PUSH list** → tells us the function's max-saved-register
  set, hinting at function complexity.
- **r5 setup** at the top → tells us where the chip-info struct pointer
  actually comes from (passed in or loaded from a global).
- Any **branch table or initial CMP** that determines which code path
  reaches the assert site.

### Implementation

Replace dump_ranges entries `{0x64100,0x641e0}` + `{0x64200,0x64280}` with
a single contiguous `{0x63e00,0x64280}`. New code dump = 1152 bytes / 16 =
**72 rows** (~18 ms additional MMIO time during dump phase). Bumps test
markers `209 → 210` for log clarity.

No NVRAM or firmware changes. No other code changes.

### Build + pre-test

- Module rebuild required (test marker bump triggers recompile)
- PCIe state: clean (`Status: Cap+ ... <MAbort-`)
- Firmware reverted to 4352pci-original (md5 `812705b3...`) post-test.209
- Filesystem will be synced before commit

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.210.{run,journalctl,journalctl.full}.txt`.

### Pre-arranged decision tree (read after test runs)

| Find at offset X | Interpretation | Next |
|---|---|---|
| `B5xx` or `E92D xxxx` between 0x63e00 and 0x64100 | function entry found | trace what's at function entry; identify args (r0..r3) and globals; map r5's source |
| Multiple `B5xx`/`E92D` patterns | several short functions in this range | bisect to find the one whose body extends to 0x641c6 (look for matching POP/`E8BD`) |
| No clear prologue, just data | range is data table or literal pool | widen further to `0x63800..0x63e00` in test.211 |
| Function entry below 0x63e00 | very large function (>900 bytes) | re-allocate dump budget; widen code window |

---

## POST-TEST.209 (2026-04-22) — 4350pci binary downloads but never executes (different entry-vector format)

Logs: `phase5/logs/test.209.{run,journalctl,journalctl.full}.txt`. Test ran
cleanly — no crash. Firmware reverted to 4352pci-original after test.

### Result 1: 4350pci firmware downloads correctly to TCM

The chip-info dump region `0x62a00..0x62c00` shows content **byte-identical
to the 4350pci binary file at the same offset**:

```
Test.209 TCM 0x62a00:  1886 6100 1886 6100 d200 ba13 a854 6100  ..a...a......Ta.
4350pci.bin offset 0x62a00:  1886 6100 1886 6100 d200 ba13 a854 6100  ..a...a......Ta.
```

This proves the 442233-byte (4352pci) blob got replaced by the 445717-byte
(4350pci) blob during firmware load.

### Result 2: 4350pci firmware never starts executing

- **Console buffer at `0x96f70..0x97070` is byte-identical to test.208**, including
  the exact same firmware-internal timestamps `125888.000` and `137635.697`.
  These are from old text in chip RAM that the new firmware never overwrote.
- **`fine-TCM summary: 0 of 16384 cells CHANGED`** during the 3000ms dwell.
  In test.208 we saw 7 cells change (timestamps in console buffer ticking).
  Zero changes here means firmware made no writes at all — it never ran.
- The `0x9cfe0` trap-data area still shows `18002000 00062a98 ... 000641cb` —
  but `0x62a98` in the **4350pci** image holds different content (`5212 5f00`),
  so this trap data is stale from test.208, not produced by the new firmware.

### Result 3: why 4350pci doesn't execute — entry-vector format differs

```
4352pci.bin first 64 bytes (working): 00f0 0eb8 00f0 2eb8 00f0 39b8 ...
4350pci.bin first 64 bytes (broken):  80f1 3ebc 80f1 68bc 80f1 73bc ...
```

The 4352pci vectors decode as `B.W +0x1c` style forward branches into the
firmware body (standard ARM Thumb-2 vector table). The 4350pci vectors look
like **wide BL/B branches with sign-extended large offsets** — they would
jump to wildly out-of-range addresses if executed at TCM[0].

This strongly suggests the 4350pci firmware was built to load at a **different
base address** than 4352pci. Possibly:
- It expects to be loaded above the bootrom region (e.g. starts at 0x40000)
- Or it has a separate header/loader sequence we'd need to honor
- Or it's intended for a chip variant where TCM is at a different physical address

Either way, **simply replacing the file isn't enough** to use 4350pci. Would
require driver-level support for the alternate load address (which brcmfmac
doesn't currently implement for BCM4360).

### Conclusion: wrong-firmware-variant hypothesis stays open

We didn't disprove the hypothesis (the 4350pci variant might fix the assert if
we could actually run it). But we did show that swapping the file alone won't
work. Two paths remain:

1. **Driver-level support for 4350pci-style firmware** — non-trivial. Would
   need to figure out the correct load address and any pre-init steps.
2. **Stay with 4352pci and find another angle on the assert** — patch the
   firmware in TCM after download, find the asserting function's entry point,
   or focus on what happens *after* the (non-fatal) assert returns.

### Plan for test.210

Pivot back to investigating the 4352pci assert path with a wider code dump.
Key open questions from test.207-208:

- Where does the **function containing the assert** start? (Currently unknown
  — we only have the assert call site at `0x641c0..0x641d0`.)
- The post-assert code at `0x641ca` does `LDR r3,[r4,#0x4c]; TST r3,#0x100;
  BEQ.N <skip>; ... BL <something>`. What does the post-BL call do?

Test.210 will widen the code dump to **`0x63a00..0x64400`** (~2300 bytes ≈ 1150
Thumb-2 instructions) — enough to find the function entry above the assert
call site (functions in this firmware appear ~512–1024 bytes long based on
spacing of literal pools we've seen).

Cost: +220 dump rows ≈ 55ms additional MMIO time. Negligible.

---

## PRE-TEST.209 (2026-04-22) — swap firmware to dlarray_4350pci variant (wrong-firmware test)

### Hypothesis

The Linux distro `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (md5
`812705b3ff0f81f0ef067f6a42ba7b46`, size 442233) is **byte-identical** to
`dlarray_4352pci` extracted from Apple/Broadcom's `wl.ko` in phase1.

Phase1's extraction script comments suggest:
- `dlarray_4352pci` → BCM4352/BCM4360 rev **≤ 3**
- `dlarray_4350pci` → BCM4350/BCM4360 rev **3+**

Our chip is BCM4360 rev 3 (chiprev=3) — exactly on the boundary where both
variants could apply. The currently-loaded 4352pci blob asserts at line 397
of `hndarm.c` (test.204..208). The 4350pci blob is a different binary
(md5 `550bf8d4e7efed60e1f36f9d8311c14b`, size 445717 — slightly larger).
**If the assert is firmware-build dependent (wrong-variant hypothesis),
swapping in the 4350pci variant should produce a different outcome.**

### Implementation

Pure firmware swap — no driver code changes. Bump test marker `208 → 209`
on the dump labels for traceability.

```
sudo cp /lib/firmware/brcm/brcmfmac4360-pcie.bin /lib/firmware/brcm/brcmfmac4360-pcie.bin.4352pci-original
sudo cp /home/kimptoc/bcm4360-re/phase1/output/firmware_4350pci.bin /lib/firmware/brcm/brcmfmac4360-pcie.bin
```

Keep `.bak` as the existing backup; add a new explicit `.4352pci-original`
for clarity. Same NVRAM as test.207-208 (reverted/original).

### Build + pre-test

- No code rebuild required (pure firmware swap), but bump test marker on
  pcie.c/chip.c label strings for log clarity → triggers a rebuild
- PCIe state: clean post-test.208
- Filesystem will be synced before commit

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.209.{run,journalctl,journalctl.full}.txt`.

### Pre-arranged decision tree (read after test runs)

| Outcome | Interpretation | Next |
|---|---|---|
| Same `line 397` assert with same `v=43` | wrong-variant hypothesis WRONG; firmware-content-independent assert | abandon firmware-swap path; pivot to bypass/patch route |
| Same line 397 with different `v` (e.g. `v=3`) | both variants assert at same site but with different state context | suggests a real config issue, dig into the v=value mapping |
| Different line/file in assert | new code path → great news; document new assert and repeat investigative cycle |
| **No assert, console buffer extends past 0x97070** | best case — 4350pci variant supports our chip; firmware booted further | read new console messages to see how far it got |
| Hard crash / no console output | 4350pci is too different — maybe it tries to use cores we don't have | revert to .bak immediately and pivot |

### Recovery plan (if 4350pci breaks the host)

If the test crashes the machine, on next boot:
```
sudo cp /lib/firmware/brcm/brcmfmac4360-pcie.bin.4352pci-original /lib/firmware/brcm/brcmfmac4360-pcie.bin
```
to restore the known baseline.

---

## POST-TEST.208 (2026-04-22) — both sides see 6 cores; "9-core mismatch" hypothesis killed

Logs: `phase5/logs/test.208.journalctl.full.txt`,
`phase5/logs/test.208.run.txt`. Test ran cleanly — no crash.

### Result 1: host-side enumerated 6 cores (matches firmware-side count exactly)

```
test.208: core[1] id=0x800:rev43 base=0x18000000 wrap=0x18100000  (ChipCommon)
test.208: core[2] id=0x812:rev42 base=0x18001000 wrap=0x18101000  (PCIe2)
test.208: core[3] id=0x83e:rev2  base=0x18002000 wrap=0x18102000  (D11/PHY)
test.208: core[4] id=0x83c:rev1  base=0x18003000 wrap=0x18103000
test.208: core[5] id=0x81a:rev17 base=0x18004000 wrap=0x18104000  (PMU)
test.208: core[6] id=0x135:rev0  base=0x00000000 wrap=0x18108000  (special — wrap-only)
test.208: host-side enumerated 6 cores total
```

### Result 2: firmware chip-info struct decoded further

Extended dump `0x62a00..0x62c00` reveals additional structure:

```
0x62a00..0x62a08  = (00, 00, 0x18002000)            [trap-PC slot]
0x62a90..0x62aa4  = (1, 0x20, 1, 0, 0x700, -1)       [unknown header]
0x62aa8..0x62ab8  = (17, 43, 0x58680001, 3, 17, 0x10a22b11)
                    pmurev=17, ccrev=43, ?, chiprev=3, pmurev=17, pmucaps
0x62ac0..0x62af0  = (0xffff, 0, 0x14e4, 0,           [vendid]
                     0, 0x4360, 3, 0,                 [chipid, chiprev]
                     0x8a4d, 0, 0, 0,                 [chipst]
                     0x96f60, 0, 0, 0)                [console-descriptor ptr]
0x62b18..0x62b1c  = (0x9d0c8, 0x157d1f36)            [?, magic?]
0x62b20..0x62b3c  = (0x18002000, 0x18000000, 0x18001000,
                     0x18002000, 0x18003000, 0x18004000) [AXI base list 1]
0x62b60..0x62b6c  = (0, 2, 5, 0x800)                  [?, ?, COUNT=5, first ID]
0x62b70..0x62b80  = (0x812, 0x83e, 0x83c, 0x81a)      [next 4 IDs]
0x62b80           = 0x135                             [6th ID — special]
0x62ba0..0x62bb8  = (0x18000000, 0x18001000, 0x18002000,
                     0x18003000, 0x18004000)          [AXI base list 2]
0x62bbc           = 0x18000000                        [extra/wrap?]
```

The struct contains a `count = 5` at `0x62b68` — followed by exactly the same
5 "real" core IDs the host enumerates. Plus the 6th special ID `0x135`
(the wrap-only one).

**Conclusion: host=6, firmware=6. Both agree. The earlier "firmware expects
9 cores" reading from test.207 was wrong.**

### Result 3: where does the `9` come from?

Re-examination of the trap-data area `0x9cfa0..0x9cfb0`:

```
0x9cfa0  0000018d 00062a08 00000009 0009cfe0   (line, ptr, value=9, fa)
0x9cfb0  00058c8c 00002f5c bbadbadd bbadbadd   (?, ?, BAD-BAD magic, magic)
```

- `0x18d = 397` (line number — known)
- `0x62a08` = pointer **into the chip-info struct**, offset 8 — which holds the
  trap-PC value `0x18002000` (D11 core base address)
- `0x00000009` = the literal value `9`
- `0x9cfe0` = `fa` (fault-data pointer — matches trap data location)

This 4-tuple looks like the **assert-formatting buffer**: `(line, file_ptr_or_ra,
expr_value, fault_addr)`. The assert macro likely captures 4-5 args for the
report.

So the `9` is NOT a core count — it's some *value being asserted*, probably the
return code of an internal function. The printed `v = 43` in the message text
is `ccrev` (passed as a separate arg for context).

### Result 4: assert call-chain re-interpretation

Combining test.207 code dump with the new chip-info findings, my updated
working model of the asserting routine:

1. Receive a request to operate on a core (the trap-PC `0x18002000` =
   core 0x83e at AXI base 0x18002000 = D11 core).
2. Look up that core in the chip-info table, walking the count=5 list.
3. The lookup returns a status code in r6.
4. If `r6 == 9` (probably "lookup failed" or "core type unsupported by this
   firmware build"), trigger ASSERT with `v = ccrev` for context — meaning
   "we don't know how to handle ccrev=43 for this core".

So **both interpretations point back to the same root cause**: this firmware
build doesn't fully support our chip's specific (chip × ccrev × core-rev)
combination — most likely because it was built for a different sub-revision.

### Implications and decision tree forward

The "wrong firmware variant" hypothesis is now **strongly supported**, just for
a different reason than I thought yesterday. Three concrete next directions:

1. **Source an alternate firmware blob.** Apple's wl.kext for this Mac contains
   `firmware_4360pci.bin` (we already extracted similar binaries for 4350/4352
   in phase1). If we can extract & convert the 4360 variant from macOS, it
   should be the *exact* match for this hardware. This is the cleanest test
   of the hypothesis.

2. **Decode the assert callsite at `0x641cb` (return address) onwards** — see
   what code path is hit if assert returns. May reveal whether assert is fatal
   here or is followed by error recovery.

3. **Bypass / patch the assert** — since it just calls a check that returns 9,
   patch the firmware blob in TCM after download to neuter the BNE/CMP and
   continue. High risk but informative.

### Plan for test.209

Direction 1 has the best signal-to-noise ratio. Action plan:

- Check `phase1/output/` and `phase1/extraction.json` for whether we already
  pulled the matching 4360 blob from Apple's wl.kext during phase1
- If not, document in PLAN.md that we need to revisit phase1 to extract it,
  and add a small test variant (`brcmfmac4360-pcie.bin.alt`) we can swap in

For test.209 itself (no firmware swap yet — that's a longer side-quest), do a
**focused dump of `0x9cf80..0x9cfd0`** (the assert-args region) plus
`0x641c8..0x64280` (post-BL code) to capture (a) all saved assert state and
(b) what the firmware does immediately after the BL to assert. If the assert
handler returns and we see a recovery path, we may have a way to keep going.

---

## PRE-TEST.208 (2026-04-22) — extended chip-info dump + host-side core count

### Hypothesis

Test.207 ended with the working theory that the firmware ASSERT at hndarm.c:397
fires because the firmware's ARM-side enumeration expected 9 distinct AI cores
(r6==9 check) but the chip-info struct it walked only contains 6 populated AXI
slots. If true, this is a "wrong firmware variant" failure — not a configuration
problem we can fix from the host side.

To confirm or refute, two complementary probes:

1. **Widen the chip-info struct dump** from `0x62a00..0x62b80` →
   `0x62a00..0x62c00`. The current dump shows the struct's chip-ID block and
   the start of an AXI-core table (5 populated slots starting at
   `0x18000000..0x18004000`). If the table continues past `0x62b80` with more
   slots — or contains a "core count" field at a known offset — we want to
   see it. Cost: +8 dump rows (~2 ms additional indirect MMIO time).

2. **Log the host-side enumerated core count** from
   `brcmf_chip_cores_check()`. brcmfmac walks the AXI core list itself during
   `brcmf_chip_attach()` via `brcmf_chip_dmp_erom_scan` — the `idx` counter
   in `brcmf_chip_cores_check` already tracks it. Promote the per-core
   `brcmf_dbg(INFO,...)` line to `brcmf_err(...)` so we see each one, and
   add a single summary line after the loop with the total count. Cost: zero
   runtime change beyond a few extra log lines.

### What the comparison will tell us

| Host count | Firmware-table count | Interpretation |
|---|---|---|
| 6 | 6 | Both agree; r6==9 expectation is firmware-internal — we need a different firmware binary or a way to fool the check |
| 9 | 6 | Host enumerated 9 but firmware's table missing 3 — firmware enumeration logic is broken (config or build mismatch we may influence) |
| 6 | 9 | Host missed 3 cores firmware can see — would mean the firmware build *is* right, host enumeration is incomplete |
| 9 | 9 | r6 isn't a core count after all; rethink |

### Implementation

**chip.c:**
- `brcmf_chip_cores_check`: change per-core log from `brcmf_dbg(INFO,...)` to
  `brcmf_err("BCM4360 test.208: core[%d] id=0x%x:rev%d base=0x%08x wrap=0x%08x", ...)`
- After the loop, add a summary `brcmf_err("BCM4360 test.208: host-side enumerated %d cores total ...", idx-1)`
- Bump test.207 → test.208 marker on the max_res_mask line

**pcie.c:**
- Extend chip-info dump_range upper bound from `0x62b80` → `0x62c00`
- Bump test.207 → test.208 in dump label format strings

**No NVRAM changes** (still on reverted/original NVRAM file).

### Build + pre-test

- Module rebuilt clean (just verified `make` completes; will rebuild after these edits)
- PCIe state: clean (`Status: Cap+ ... <MAbort-`); no dirty state from prior crash
- Filesystem will be synced before commit

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.208.journalctl{,.full}.txt` and `test.208.run.txt`.

### Pre-arranged decision tree (read after test runs)

- **Host=6, fw-table=6, no new field found** → strong evidence for "wrong firmware
  variant" hypothesis. Action: locate alternate firmware (macOS, different vendor)
  for this exact BCM4360 sub-revision.
- **Host=9, fw-table=6** → firmware downloader/init is dropping cores. Investigate
  what's in the EROM scan that brcmfmac sees vs. what firmware's enumeration gives.
- **Host=6, fw-table=9 (continued)** → re-examine host enumeration; possibly the
  EROM table walk is short-circuiting.
- **Either count ≠ {6,9}** → my model of what r6 represents is wrong; reconsider
  with the new core counts as data.

---

## POST-TEST.207 (2026-04-22) — NVRAM delivery confirmed; r6 source partly identified

Logs: `phase5/logs/test.207.journalctl.full.txt`. Run text:
`phase5/logs/test.207.run.txt`. Test ran cleanly — no crash.

### Result 1: NVRAM IS reaching firmware

Dump at `0x9ff00..0xa0000` shows our entire NVRAM content
present in TCM:

```
0x9ff10: "rev=11.boardsromrev=11.boardtype=0x0552.boardrev=0x1101"
0x9ff50: "boardflags=0x10401001.boardflags2=0x00000002..."
0x9ff80: "boardflags3=0x00000000.boardnum=0.macaddr=00:1C:B3:01:12:01"
0x9ffb0: "ccode=X0.regrev=0.vendid=0x14e4.devid=0x43a0.xtalfreq=40000"
0x9ffe0: "aa2g=7.aa5g=7..."
0x9fffc: ffc70038            ← NVRAM CRC/length trailer (matches the
                                value our log-marker reports)
```

So the firmware *is* receiving our NVRAM at the canonical TCM-top
location (the host driver downloaded it correctly). The
`ramstbydis` tests (test.205/206) were valid — the assert path
just doesn't depend on it.

This also confirms our NVRAM file is being preserved as ASCII
text, not transformed into a binary table (which is what some
older Broadcom NVRAM formats use). Good baseline.

### Result 2: code at 0x64100-0x64160 (wider context)

Observed-behavior summary (clean-room, no instruction excerpts):

- The function entry begins around `0x64100` and uses r5 as a
  **struct base register** (numerous `STR/LDR Rn, [r5, #imm]`
  with offsets like 0x10, 0x14, 0x40, 0x74, 0xe0, 0xe8).
- r6 is **decremented** (subtract-with-flags by 1 at `0x6411e`)
  and **stored** to `[r5, #0x10]` immediately after at `0x64120`.
- r7 is computed by **subtracting 0x40** from the function's
  first argument (at `0x6410c`).
- Multiple compares against constants 7, 12, 0xe0 (on r7) and 9
  (on r6, the one we already knew about) suggest a small
  state-machine or table-driven dispatch.
- A `CMP r6, #0` at `0x64140` followed by `BNE.N` (backward)
  forms a loop — r6 is a loop counter that decrements.

### Synthesis

The asserting routine appears to:
1. Receive the chip-info struct via r5 (or load it).
2. Initialize r6 with some small value (probably from a struct
   field — load not visible in current dump window) and r7 from
   an arg.
3. Walk a small table or per-core loop, decrementing r6 and
   updating struct fields at `[r5, #0x10]`, `[r5, #0x14]`, etc.
4. After the loop, check `r6 == 9` — if not equal, fire the
   assert (line 397).

Combined with the chip-info struct showing **6 populated AXI
core slots** (test.203: cores at 0x18000000, 0x18001000,
0x18002000, 0x18003000, 0x18004000 — 5 slots used + 1 starting
slot), and the assert wanting r6=9 — **the firmware is checking
that 9 cores were enumerated** but our chip only enumerated 6.

This isn't a value we can change via NVRAM. It's a chip
**enumeration-table mismatch**: the firmware build expects to
find 9 distinct AI cores, but the BCM4360 silicon only exposes
6 (or whatever count we measure). So this firmware was built
for a chip variant with more peripherals/cores than we have.

### Implications

- This is the "wrong firmware for this chip" failure mode. Our
  brcmfmac4360-pcie.bin is from a Linux distro firmware
  package; it might be built for a different BCM4360 sub-variant
  (e.g., the dual-band MIMO variant vs. the single-band variant).
- Possible solutions:
  - Try a different firmware binary (e.g., from macOS, or from
    a different vendor's brcmfmac release that targets this
    Apple-specific variant).
  - Confirm the core count is what we think — by reading the
    PCIe core enumeration ourselves and comparing.

### Plan for test.208

Two complementary probes:

1. **Read the chip-info core table more thoroughly**: dump
   `0x62b80..0x62c00` (8 rows, 32 bytes) — the table extends
   past where we currently dump. Want to see if there's a
   "core count" field at a struct offset we can directly
   inspect. Also re-dump `0x62b00..0x62b80` to verify the
   core-ID values (we may have mis-identified some).

2. **Confirm core count by host-side enumeration**: in
   chip.c, also log the count of cores brcmf's own enumeration
   logic finds. We already have `chip->cores` populated — print
   the number. Compare against what the firmware expects (9?).

Cost: small dump (+8 rows) + 1 log line in chip.c.

If host-side enumeration also finds 6, we're confident the chip
has 6 cores and the firmware expects 9 — so we need a different
firmware binary. If host-side finds 9 but the firmware's table
shows 6, the firmware enumeration is wrong (a firmware bug or
config mismatch we may be able to influence).

---

## PRE-TEST.207 (2026-04-22) — verify NVRAM-blob in TCM + widen code dump

### Hypothesis (3 things being tested)

1. **NVRAM reverted** to pre-205 state (no `ramstbydis` line). This
   isolates the question of "is firmware reading NVRAM at all?" —
   if YES, we'd want to see a clean baseline; if NO, none of the
   ramstbydis probes were valid tests.

2. **NVRAM blob delivery check** — Broadcom firmwares typically
   look for the NVRAM blob at the *top of TCM* (last few KB before
   ramsize). Reading `0x9ff00..0xa0000` (4 KB at TCM top) will
   show whether our NVRAM key=value text is present. If we see
   `sromrev=11\nboardtype=0x0552\n...` etc, NVRAM IS being
   delivered. If we see zeros / random / different content,
   NVRAM isn't reaching this address.

3. **r6 source** — `0x64100..0x64160` (6 rows, 24 instructions max)
   to capture instructions that may load r6 with a value before
   the CMP at `0x641b2`.

### Implementation

NVRAM reverted (already done). Marker bumps test.206 → test.207.

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                              | Rows |
|--------------------|------------------------------------------------------|-----:|
| `0x40660..0x406c0` | Strings (kept)                                       |    6 |
| `0x64100..0x641e0` | Code (extended down to find r6 source)               |   14 |
| `0x64200..0x64280` | Literal pool                                         |    8 |
| `0x62a00..0x62b80` | Chip-info struct                                     |   24 |
| `0x96f40..0x96fc0` | hndrte_cons descriptor                               |    8 |
| `0x97000..0x97200` | Console ring                                         |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text                              |   64 |
| `0x9ff00..0xa0000` | TCM top — NVRAM delivery check                       |   16 |

Total = 172 rows ≈ 34 ms. Acceptable.

### Build + pre-test

- Module rebuild needed (only marker changes).
- PCIe state: clean post-test.206.
- NVRAM file restored from backup (verified).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.207.journalctl.full.txt`.

### Decision tree for test.207

- **NVRAM text visible at 0x9ff00+** → firmware *is* receiving
  NVRAM. The ramstbydis tests were valid; the assert path simply
  doesn't depend on it. Proceed with r6 source analysis.
- **NVRAM area is zeros / random** → firmware isn't getting NVRAM
  at the expected location. Need to check the host driver's NVRAM
  download path; might be a fixable bug.
- **r6 source visible**: an LDR with a struct base register
  identifies what's being checked. May enable a focused next test.

---

## POST-TEST.206 (2026-04-22) — ramstbydis=1 also no effect; revert and pivot

Logs: `phase5/logs/test.206.journalctl.full.txt`. Run text:
`phase5/logs/test.206.run.txt`. Test ran cleanly — no crash.

### Result: identical assert (third time)

Same `hndarm.c:397`, same `v = 43`, same trap data
`18002000 00062a98 000a0000 000641cb` at `0x9cfe0`. Adding
`ramstbydis=1` (test.206) and `ramstbydis=0` (test.205) both
produced byte-identical results — and identical to the
no-ramstbydis baseline (test.204).

### Conclusion (NVRAM angle)

The firmware **either does not consume the `ramstbydis` NVRAM
variable in this code path, or our NVRAM isn't reaching the
firmware at all**. The latter is concerning enough to verify
directly in test.207.

### Plan for test.207 — three concurrent probes

1. **Revert NVRAM**: remove the `ramstbydis=1` line — restore the
   pre-205 NVRAM. (Backup is already at
   `phase5/work/nvram-backup-pre-205.txt`.)

2. **Verify NVRAM actually reached firmware**: add a dump range at
   the top of TCM (`0x9ff00..0xa0000`) where Broadcom firmwares
   typically place the NVRAM blob. If we see our key=value pairs
   there, NVRAM is being delivered. If zeros / random, NVRAM isn't
   loading at the address the firmware reads from.

3. **Find r6's source**: add wider code dump
   `0x64100..0x64160` (6 rows) — instructions before the
   pre-CMP region we already dumped. Look for an `LDR r6, [Rs,
   #imm]` that initializes r6.

Cost: small NVRAM dump (~16 rows) + small code dump (6 rows) =
+22 rows. Same dump pipeline.

---

## PRE-TEST.206 (2026-04-22) — try ramstbydis=1; second NVRAM probe

### Hypothesis

If `ramstbydis=0` (test.205) was already the firmware's default
behaviour, switching to `ramstbydis=1` should change the assert
outcome (or at least the chip-info struct visible in TCM after
the assert) IF the firmware actually reads this NVRAM key. If
`=1` also leaves the assert byte-identical, then either the
firmware doesn't read this key at all, or it consumes it after
the line-397 assert path runs.

### Implementation

NVRAM only — change `ramstbydis=0` → `ramstbydis=1`. No code change
beyond the test.205→206 marker bumps.

### Build + pre-test

- About to rebuild module (only marker change).
- PCIe state: clean post-test.205.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.206.journalctl.full.txt`.

### Decision after test.206

- **Same line 397, same v=43**: NVRAM key has no effect on this
  path. Plan test.207: revert NVRAM (remove ramstbydis line),
  add wider code dump `0x64100..0x64160` to find r6's source.

- **Different result**: ramstbydis IS active; document the new
  state and iterate on values.

---

## POST-TEST.205 (2026-04-22) — ramstbydis=0 had no effect; assert identical to test.204

Logs: `phase5/logs/test.205.journalctl.full.txt`. Run text:
`phase5/logs/test.205.run.txt`. Test ran cleanly — no crash.

### Result: identical assert to test.204

```
136825.784 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
v = 43, wd_msticks = 32
```

Trap-data structure at `0x9cfe0` is byte-identical to test.204:
`18002000 00062a98 000a0000 000641cb`. Line number at `0x9cfa0` is
still `0x18d` (=397). The only varying field across runs is the
boot-relative timestamp prefix in the console message.

**`ramstbydis=0` did not affect the line-397 path.**

### Interpretation

Three possibilities, listed by what they imply for next steps:

1. **The firmware ignored our NVRAM key**. Could be: (a) firmware
   doesn't read NVRAM until after this assert, or (b) firmware
   doesn't recognize `ramstbydis` for this build/chip, or (c) the
   firmware downloader/NVRAM stage isn't actually working. (c) is
   most concerning — would explain why no NVRAM-driven setting
   ever works.

2. **`ramstbydis=0` is the default** the firmware would have used
   anyway, so adding it changes nothing. Worth one more test with
   `ramstbydis=1` before discarding this avenue.

3. **The assert path doesn't depend on ramstbydis**. The string is
   nearby in the const-pool but used by an unrelated code path.
   In which case we need to find what r6 actually loads from.

### Per the pre-arranged decision tree

Outcome was "same line / same v" → my plan said: revert NVRAM,
then dump `0x64100..0x64160` in test.206 to find r6's source.

But before fully reverting, **one quick second probe**:
**test.206 will try `ramstbydis=1`** to disambiguate (1) vs (2)
above. If `=1` also produces an identical assert, the NVRAM key is
either being ignored or doesn't gate this path; revert it and
shift focus to dumping wider code context in test.207.

If `=1` produces a *different* result (different line, different
v, no assert), then we've confirmed the firmware does read
ramstbydis and we have a new lead.

---

## PRE-TEST.205 (2026-04-22) — add ramstbydis=0 to NVRAM, compare assert against test.204

### Hypothesis

Test.204 found the string "ramstbydis" (RAM Standby Disable) in the
firmware's literal pool nearby the assert call site. Our current NVRAM
file is missing this key. If the firmware reads ramstbydis from NVRAM
during init and the line-397 assert path branches on its value, then
adding `ramstbydis=0` (or `=1`) will change the assert outcome.

### Implementation

**No code changes** — pure NVRAM modification. Keep the same dump
configuration as test.204 so we can compare the trap region byte-for-
byte. Bump the test marker to test.205 so log lines are tagged.

**chip.c** — bump marker `test.204` → `test.205`.
**pcie.c** — only the test.204 → test.205 label rename. Same
`dump_ranges[]` as test.204.
**NVRAM** — append `ramstbydis=0` to
`/lib/firmware/brcm/brcmfmac4360-pcie.txt` (preserve existing keys).

### Build + pre-test

- Module rebuilt clean.
- PCIe state: clean post-test.204.
- NVRAM backed up to `phase5/work/nvram-backup-pre-205.txt` first.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.205.journalctl.full.txt`.

### Pre-arranged decision tree (read after test runs)

- **Same `line 397` assert AND same `v = 43`** → ramstbydis didn't
  affect this code path. Revert NVRAM, then dump `0x64100..0x64160`
  in test.206 to find r6's source.

- **Same `line 397` assert AND DIFFERENT `v = N`** → the asserted
  value depends on ramstbydis (or downstream code that consumed
  ramstbydis). Keep ramstbydis in NVRAM and try other values
  (`=1`) in test.206.

- **Different line / file** → great news, we passed line 397.
  Document the new assert and start the same investigative cycle
  on it.

- **No assert at all, console buffer extends past 0x97070** →
  best case. Read the new console messages to see how far init got.

---

## POST-TEST.204 (2026-04-22) — BREAKTHROUGH 5: "ramstbydis" identified — likely NVRAM key

Logs: `phase5/logs/test.204.journalctl.full.txt`. Run text:
`phase5/logs/test.204.run.txt`. Test ran cleanly — no crash.

### Result 1: string region decoded literally

Bytes at `0x40660..0x406c0`:

```
0x40660: "..._to\0hndrte_arm.c\0hndarm.c\0ramstbydis\0pciedngl_isr"
                                      ^0x40671          ^0x4067a
0x406a0: "pciedngl_isr called\n%s: invalid IS..."
```

Confirmed:
- `0x40671` = `"hndarm.c\0"` (9 bytes including terminator) — matches
  the assert literal-pool ptr ✓
- `0x4067a` = **`"ramstbydis\0"`** (11 bytes) — this is the second
  literal-pool pointer

`"ramstbydis"` is a known Broadcom **NVRAM variable name**: "RAM
Standby Disable". It controls whether the ARM core can enter
RAM-standby low-power state. **Our NVRAM file
(`/lib/firmware/brcm/brcmfmac4360-pcie.txt`) does NOT contain
this key.** When the firmware looks it up and finds it absent,
behaviour depends on the firmware build — some default value
might be used, or a fault path triggered.

Other nearby strings: `hndrte_arm.c` (sister file), `pciedngl_isr`
(PCIe dongle interrupt handler), `%s: invalid IS...` (truncated —
"invalid Interrupt Status"?) — all unrelated to the assert path,
just adjacent in the const-string section.

### Result 2: chip-info struct lower half

Bytes at `0x62a00..0x62a80`:

```
0x62a00:  00000000 00000000 18002000 00000002
0x62a10..0x62a78:  all zeros
```

So the literal-pool pointers `0x62a08` and `0x62a0c` target:
- `*0x62a08 = 0x18002000`  ← AXI/AI core base (matches the core
  table we already saw at 0x62b20)
- `*0x62a0c = 0x00000002`  ← small integer (index? count? state?)

If r6 is loaded from `0x62a0c`, then `r6 = 2`, and `CMP r6, #9`
→ unequal, BNE fires. Whether the assert is on the BNE-taken or
fall-through path needs us to confirm the conditional sense; but
either way `r6 = 2` ≠ `9`, so the conditional doesn't match the
"all good" expected case.

### Result 3: pre-CMP code

Bytes at `0x64160..0x6418c`:

```
0x64160:  4834 b920  f240 1165  f79d f83e  4620 f7a5
0x64170:  4b34 fbf9  682b 6018  f042 681a  601a 0202
0x64180:  f8c3 2200  696b 21e0  dd05 2a27  21e0 f8d3
```

Visible patterns (clean-room: high-level only):
- `0x64160`: `LDR r0, [pc, #0xd0]` then `CBNZ` form (b920) — early
  null/zero check.
- `f240 1165`: MOVW r1, #0x1165 — another constant load
- Multiple `f79d` patterns — repeated BL calls into nearby
  functions (one per `f79d` halfword at the start of an
  instruction pair)
- `682b`, `681a`, `696b` — `LDR r3, [r5]`, `LDR r2, [r3]`,
  `LDR r3, [r5, #0x14]` — chained struct-field reads
- `f8c3 2200`: `STR r2, [r3, #0x200]` — writing to a far offset
- `21e0`: `MOV r1, #0xe0` — preparing a register
- `dd05`: `BLE.N` — backward conditional branch

So r6 isn't loaded by a single visible LDR in this range; it
appears earlier (or is computed). I'll widen one more time to
`0x64100..0x64160` in the next test if needed. But the more
productive next step is to **test the ramstbydis hypothesis
directly** by modifying the NVRAM file.

### What "v = 43, wd_msticks = 32" actually tells us

Re-reading the assert text in light of "ramstbydis" being a key:

```
ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
v = 43, wd_msticks = 32
```

`v = 43` matches our `ccrev = 43`. `wd_msticks = 32` is the
watchdog tick value. So this assert is in a routine that has both
`ccrev` and `wd_msticks` in scope and prints them — likely an
**HW init / watchdog setup** routine. The presence of `ramstbydis`
in the literal pool nearby strongly suggests this routine is
configuring power management based on the `ramstbydis` NVRAM
variable, and asserting because something it expected to find
(maybe a particular core state, or `ramstbydis` set explicitly)
is missing.

### Plan for test.205 — direct test of the NVRAM hypothesis

Cheapest informative change: **add `ramstbydis=0` to NVRAM**, run.
Outcomes:

1. **Same assert at line 397** → ramstbydis isn't directly
   triggering the assert; it's in scope as a side effect. Move on
   to identifying r6's source via a wider code dump.

2. **Different assert (different line, different `v = N`)** →
   we've moved past the line-397 check. Whatever new assert
   appears tells us the next missing thing.

3. **No assert, firmware progresses** → ramstbydis was the gate.
   We'd see different console buffer contents (more init lines).

Will also try `ramstbydis=1` if 0 doesn't change anything.

NVRAM is host-supplied so this is fully under our control — no
firmware modification, no large excerpts committed.

---

## PRE-TEST.204 (2026-04-22) — extend chip-info down + read strings + pre-CMP code

### Hypothesis

Three small additions to the dump close several open puzzles from test.203.

1. **`0x62a00..0x62a80` (8 rows)** — chip-info struct lower half.
   The assert literal pool holds pointers to `0x62a08` and `0x62a0c`,
   both below our current dump start. Whatever values are there,
   the assert routine is reading them.

2. **`0x40660..0x406c0` (6 rows)** — string region. Reads the
   filename "hndarm.c" at `0x40671` and the format string at
   `0x4067a` literally. Confirms our reading of the assert message
   format and may show preceding/following strings that hint at
   the calling-function context.

3. **`0x64160..0x6418c` (4 rows)** — instructions immediately before
   the `CMP r6, #9` at `0x641b2`. Want to find the `LDR r6, [...]`
   that loads r6, which tells us *which struct* and *which field*
   r6 holds the value of. That's the actual smoking gun for "what
   does the firmware expect?".

### Implementation

**chip.c** — bump marker `test.203` → `test.204`.

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                              | Rows |
|--------------------|------------------------------------------------------|-----:|
| `0x40660..0x406c0` | Filename + format-string text                        |    6 |
| `0x64160..0x641e0` | Pre-CMP code + assert call-site (extended down)      |   10 |
| `0x64200..0x64280` | Literal pool                                         |    8 |
| `0x62a00..0x62b80` | Chip-info struct (extended down + neighbours)        |   24 |
| `0x96f40..0x96fc0` | hndrte_cons descriptor                               |    8 |
| `0x97000..0x97200` | Console ring                                         |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text                              |   64 |

Total = 152 rows ≈ 30 ms. Acceptable.

### Build + pre-test

- About to rebuild module.
- PCIe state: clean post-test.203.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.204.journalctl.full.txt`.

### Expected outcomes

- **String confirmation**: bytes at 0x40671 and 0x4067a should
  spell "hndarm.c\0" and the assert format. Definitive.
- **Chip-info lower half**: shows what's stored at `0x62a08`/`0x62a0c`
  that the assert routine consults.
- **r6 source**: a `LDR r6, [Rs, #imm]` will give us the struct
  base register and offset; chained back through earlier code to
  identify the structure type. Perhaps directly identifiable from
  Broadcom's open driver source (`brcmfmac` or upstream Linux).

---

## POST-TEST.203 (2026-04-22) — literal pool decoded + chip-info core table found

Logs: `phase5/logs/test.203.journalctl.full.txt`. Run text:
`phase5/logs/test.203.run.txt`. Test ran cleanly — no crash.

### Result 1: assert literal pool

Dump at `0x64200..0x64280` shows end-of-function code (0x64200-0x64232)
then the literal pool starts at `0x64234`:

```
0x64230:  bf00 81f0          ← (ends previous function)
0x64234:  00040671           ← ptr to "hndarm.c" (9-char filename)
0x64238:  0004067a           ← ptr to format string
0x6423c:  00017fff           ← 0x17fff  (17-bit mask — max_res_mask-like!)
0x64240:  00062a08           ← ptr into chip-info struct (r2 arg?)
0x64244:  00062a0c           ← ptr into chip-info struct (r3 arg?)
0x64248:  43f8 e92d 4b1d     ← (next function prologue: PUSH+LDR)
```

- `0x00040671 + 9 bytes = 0x0004067a` → "hndarm.c\0" (9 bytes
  including terminator) followed immediately by the format string.
- **`0x00017fff` is striking** — we know `max_res_mask` on this chip
  reads back as `0x17f` after our write. `0x17fff` is almost exactly
  `0x17f << 4` (= `0x17f0`, not quite) and looks like it could be a
  **mask check** — e.g., "does the chip's resource-mask cover all
  bits in 0x17fff?"  Or could be a totally unrelated bitmask used by
  a different check. Need to read the bytes at `0x40671..0x4067a` to
  confirm the filename, and walk back from the CMP to see which
  register this literal was loaded into.
- **`0x62a08` and `0x62a0c` pointers** — both are in the chip-info
  struct area, but *below* our currently-dumped range (we started at
  `0x62a80`). The struct extends at least to `0x62a08`.

### Result 2: chip-info struct upper half has AI/AXI core table

Dump at `0x62b00..0x62b80` reveals what appears to be a table of
peripheral-core base addresses (AXI bus slots) and core IDs:

```
0x62b00-0x62b18: zeros (padding)
0x62b1c:  0009d0c8                ← pointer into upper TCM (past trap data)
0x62b20:  18002000 18000000 18001000 18002000
0x62b30:  18003000 18004000 0 0                ← 6 core base addresses at 0x18000000+
0x62b40-0x62b5c: zeros
0x62b60:  00000000 00000002 00000005 00000800
0x62b70:  00000812 0000083e 0000083c 0000081a  ← 6 core-ID words
```

The sequence `0x18000000, 0x18001000, 0x18002000, 0x18003000, 0x18004000`
is classic Broadcom SoC AXI-bus core addressing (each core gets a
4KB window). The 6 corresponding core IDs at `0x62b70..0x62b7c` are
`0x800, 0x812, 0x83e, 0x83c, 0x81a` — these match Broadcom's
CC_CORE_ID=0x800, PCIE2_CORE_ID=0x83c, ARMCR4_CORE_ID=0x83e, etc.
**This is the firmware's core-enumeration table**.

### Speculation refined

The `r6 = 9` in the assert-preceding CMP is now less likely to be
a chip-rev test — with the literal `0x17fff` in the pool *and* the
PMU resource-mask angle, it might be testing whether a specific bit
in the PMU `max_res_mask` is set. Our max_res_mask = `0x17f` (the
driver-supplied value), but `0x17fff` has 13 bits set (0-9, 10, 11, 12).

Another plausible scenario: **r6 holds a count of AI cores found**,
and the firmware expected 9 cores but we have some different number
enumerated. The core table here shows 6 populated AXI slots — if the
firmware expects 9 and sees 6, that's the mismatch. But before
pursuing this, we need to read the instructions between a load of
r6 and the CMP to see where r6 actually comes from.

### Plan for test.204

1. **Extend chip-info dump down**: `0x62a00..0x62a80` (8 rows) to
   reach the `0x62a08`/`0x62a0c` pointers and see what values they
   target.

2. **Read the string region**: `0x40660..0x406c0` (6 rows) to
   extract the "hndarm.c" filename and format string literally —
   validates our reading of the assert format.

3. **Expand code context before the CMP**: pull `0x64160..0x6418c`
   (4 rows) to see what instruction loaded r6 (likely `LDR r6,
   [something, #offset]` — want to know what structure and field).

Total +18 rows over test.203. Still fast.

---

## PRE-TEST.203 (2026-04-22) — read literal pool + chip-info struct neighbours

### Hypothesis

Two more cheap dumps will close the loop on what the assert is checking:

1. **Literal pool at `0x64200..0x64280`** (8 rows). Test.202 showed the
   assert call uses `LDR r0, [pc, #0x70]` at `0x641c0`, which loads
   from `(0x641c0+4)+0x70 = 0x64234`. This region holds the
   format-string pointer (and possibly other pointers used by the
   variadic args). Dumping it lets us:
   - Confirm the format string is `"ASSERT in file %s line %d (ra %p, fa %p)\n"`
   - See if there are *more* arguments being formatted that we haven't
     decoded yet (e.g., the `v = 43, wd_msticks = 32` text we see in
     the log might be from a *follow-on* printf, not a single one)

2. **Chip-info struct neighbours `0x62b00..0x62b80`** (8 rows).
   Test.201 dumped `0x62a80..0x62b00` and showed the chip-info struct.
   We already see fields like ccrev=0x2b, chiprev=3, pmurev=0x11,
   pmucaps=0x10a22b11, vendor=0x14e4, chipid=0x4360. The 8 rows
   immediately after may hold the byte that r6 was loaded from
   (a value 9 would mean the chip variant matches, anything else
   triggers the assert).

Both reads are pure observation. Total +16 rows vs test.202.

### Implementation

**chip.c** — bump marker `test.202` → `test.203`.

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                              | Rows |
|--------------------|------------------------------------------------------|-----:|
| `0x6418c..0x641e0` | Assert call-site                                     |    6 |
| `0x64200..0x64280` | Literal pool used by the assert call                 |    8 |
| `0x62a80..0x62b80` | Chip-info struct + neighbours (extended)             |   16 |
| `0x96f40..0x96fc0` | hndrte_cons descriptor                               |    8 |
| `0x97000..0x97200` | Console ring                                         |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text                              |   64 |

Total = 134 rows ≈ 27 ms. +16 rows over test.202 (118 rows).

### Build + pre-test

- About to rebuild module.
- Last PCIe state: clean post-test.202.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.203.journalctl.full.txt`.

### Expected outcomes

- **Format string identified literally**: confirms our reading of
  the assert message and reveals any additional `%`-substitutions.
- **The compared value found**: if a byte at `0x62b00..0x62b80`
  equals 9, we know what the firmware was looking for. If it
  doesn't equal 9, the value is loaded via a more indirect path
  (struct chain), and we'll need to decode the load chain in a
  later test (read instructions before the CMP at `0x641b0`).

---

## POST-TEST.202 (2026-04-22) — console buffer mapped + assert call site decoded

Logs: `phase5/logs/test.202.journalctl.full.txt`. Run text:
`phase5/logs/test.202.run.txt`. Test ran cleanly — no crash.

### Result 1: hndrte_cons buffer geometry

The dump at `0x96f40..0x96fc0` reveals that the actual log buffer
starts at `0x96f78`, **not** at `0x97000` as we assumed in test.200:

```
0x96f40: 00000010 00000000 00000000 00000b05
0x96f50: 00000000 00000001 00000010 00000000
0x96f60: 00000000 00000000 00000000 00000000   ← chip-info pointed here
0x96f70: 00004000 00000000 6e756f46 68632064   ← buf_size=0x4000, idx=0, then "Foun"
0x96f80: "ip type AI (0x15"
0x96f90: "034360)\r\n125888."
0x96fa0: "000 Chipc: rev 4"
0x96fb0: "3, caps 0x586800"
... (continuing into 0x97000)
```

So the descriptor near `0x96f60` carries (probable layout):

- `0x96f70 = log_buf_size = 0x4000` (16384 B)
- `0x96f74 = log_idx = 0`
- `0x96f78..0x9af78 = log_buf` (16 KB ring)

The log content visible across `0x96f78..0x97070` is only ~248 B —
the firmware emits boot messages + the assert and halts, leaving
the rest of the buffer as zeros. So the duplicate text we saw at
`0x9cdb0..0x9cdf0` in test.199/200 is from a **second sink** (the
firmware exception handler's trap console), not a different copy of
the main ring buffer.

The 32-byte block at `0x96f40..0x96f60` is some other descriptor
(value `0x00000b05` at `0x96f4c` is suggestive — possibly a
counter or reserved-bytes field). Not investigating further now.

### Result 2: assert call site decoded

The dump at `0x6418c..0x641e0` is dense Thumb-2 instructions. The
key sequence around the BL to the assert handler (LR=0x641cb in
the trap data, so BL ends at 0x641ca):

```
... (preceding compare/branch logic) ...
0x641b0:  2e09 d101              ← CMP r6,#9 ; BNE.N <skip>
... 
0x641c0:  481c                   ← LDR r0, [pc,#0x70]   (load format-string ptr)
0x641c2:  f240 118d              ← MOVW r1, #0x18d      (= 397, line number)
0x641c6:  f79d f80f              ← BL  <assert_handler> (LR = 0x641ca)
0x641ca:  ...                    ← (next instruction)
```

This means the *failing check immediately above the assert call* is
a `CMP r6, #9` followed by a `BNE`. r6 holds *some 4-bit-or-so
field of the chip-info struct* — most likely a sub-revision /
package-variant code that this firmware build expects to equal 9
for the BCM4360 it's looking for, but our chip reports a different
value. The LDR at 0x641c0 reads the format string from offset 0x70
past PC, so the literal pool starts around `0x64234`.

### What is r6 = 9 testing?

Speculation, ranked by likelihood:

1. **Chip-package-variant code**: BCM4360 has multiple package
   variants (4360A, 4360B, etc.). The chip-info struct at
   `0x62a98..` includes some bytes we haven't decoded yet (`0x14e4`
   = vendor ID, `0x4360` = chipid). One field around there might
   be a "package code" the firmware checks against an expected
   value.

2. **Chiprev sub-field**: ccrev=43 = 0x2b = 0b101011. Bits[3:0] = 9.
   So `r6 = ccrev & 0xf = 9` would actually pass this check —
   meaning the BNE branches around the assert and *something else*
   triggers the assert. Possible if the "v=43" in the printf uses
   a different value than r6.

3. **A device-tree / flash-region read** that returned a value the
   firmware deems wrong (e.g., a strap or OTP read).

Hypothesis (2) is intriguing because if `ccrev & 0xf == 9` is the
test and 43 & 0xf = 11 (= 0xb) — *that's* what we have, and 11 ≠ 9.
So the assert *does* fire because our ccrev's low nibble is 0xb,
not 0x9. This suggests the firmware was built for a chip whose
ccrev's low nibble is 9 (e.g., ccrev 25, 41, 57, ...) and our
ccrev=43 isn't in the supported set. **This is testable** by
reading the literal pool to see what format string we're emitting —
if the format is `"v = %d"` and the value in the printf is r6, then
we'd see "v = 11", not "v = 43". But we *see* "v = 43" → so the
printf variable is *not* r6 directly. The actual asserted condition
might be at a different register, with r6=9 being something else.

### Plan for test.203

1. **Read the literal pool at `0x64200..0x64280`** — this contains
   the format-string address + any other values LDR'd by the
   assert call. Decode literally what `r0`, `r2`, `r3` hold by
   the time the BL fires.

2. **Read the chip-info struct's neighbours at `0x62b00..0x62b80`** —
   we may find related per-chip configuration fields. Especially
   interesting: any byte that == 9 (or 0xb) so we can confirm
   what r6 was loaded from.

Both reads are <16 rows total (~3 ms). Easy add.

---

## PRE-TEST.202 (2026-04-22) — read hndrte_cons descriptor + decode assert call site

### Hypothesis

Two cheap additional dumps will give us:

1. **`hndrte_cons` descriptor at `0x96f60`** (4 rows): ring metadata
   — base pointer, size, current write index. Confirmed via test.201
   that `0x62af0` (chip-info field) holds `0x00096f60`, which sits
   immediately below the console text we found at `0x97000`. Standard
   Broadcom layout has a small descriptor struct preceding the
   ring buffer, with fields like `{vcons_in, vcons_out, log_base,
   log_idx, log_buf, log_buf_size, log_idx2, ...}`.

2. **Assert call-site context at `0x6418c..0x641b8`** (4 rows): the
   literal-pool / instructions immediately before the `MOVW r1,#0x18d`
   we already located at `0x641b8`. ARM Thumb-2 LDR-from-PC commonly
   appears just before such call sites to load `r0`, `r2`, `r3` with
   pointers to the format string + arguments. From the literals we
   can identify *which* value is being checked.

### Implementation

**chip.c** — bump marker `test.201` → `test.202`. PMU still 0x17f.

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                              | Rows |
|--------------------|------------------------------------------------------|-----:|
| `0x6418c..0x641e0` | Assert call-site (extends prior, +instructions)      |    6 |
| `0x62a80..0x62b00` | Chip-info struct (proven useful, keep)               |    8 |
| `0x96f40..0x96fc0` | hndrte_cons descriptor (8 rows centered on 0x96f60)  |    8 |
| `0x97000..0x97200` | Console ring                                         |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text                              |   64 |

Total = 118 rows ≈ 24 ms. Slight increase over test.201 (108 rows).

### Build + pre-test

- About to rebuild module.
- Last PCIe state clean post-test.201.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.202.journalctl.full.txt`.

### Expected outcomes

- **`hndrte_cons` descriptor decoded**: we'll see a small struct
  with pointers to `log_buf` (likely `0x97000`), a `log_buf_size`
  (likely `0x200` = 512 B = 32 rows we've been dumping), a
  `log_idx` write pointer that tells us *exactly* where the next
  message will land (and therefore where the *latest* message
  ended). This eliminates pattern-matching guesswork.

- **Literal-pool decode**: the LDR offsets in `0x6418c..0x641b8`
  point to an address pool (typically just past the function end,
  before the next function starts). With the literals + the values
  at those addresses, we can identify what global variable / what
  check is being performed. This may directly tell us *what* the
  assert is checking (e.g., a chip-rev allowlist, a feature flag,
  a function-pointer that should have been initialized).

---

## POST-TEST.201 (2026-04-22) — BREAKTHROUGH 4: 0x62a98 is the chip-info struct, not code

Logs: `phase5/logs/test.201.journalctl.full.txt` (use the `.full.txt`).
Run text: `phase5/logs/test.201.run.txt`. Test ran cleanly — no crash.

### Headline result

The mystery PC value `0x00062a98` from the trap data is **not a code
address**. The live TCM around it contains a populated chip-info data
structure that looks like Broadcom's `si_info_t`:

```
0x62a80: 00000000 00000000 00000000 00000000   ← header / unused
0x62a90: 00000001 00000020 00000001 00000000   ← (0x62a98 here = 0x00000001)
0x62aa0: 00000700 ffffffff 00000011 0000002b   ← 0x11=pmurev=17, 0x2b=ccrev=43
0x62ab0: 58680001 00000003 00000011 10a22b11   ← caps, chiprev=3, pmurev, pmucaps
0x62ac0: 0000ffff 00000000 000014e4 00000000   ← 0x14e4 = Broadcom vendor ID
0x62ad0: 00000000 00004360 00000003 00000000   ← 0x4360 = chip ID, rev=3
0x62ae0: 00008a4d 00000000 00000000 00000000   ← 0x8a4d = chipst (matches log)
0x62af0: 00096f60 00000000 00000000 00000000   ← pointer into upper TCM
```

Every value in this struct matches the chip we already know we have:
chiprev=3, ccrev=43, pmurev=17, pmucaps=0x10a22b11, chipst=0x8a4d.
That's the firmware's `si_info_t` (or equivalent) for the local chip.

**Hypothesis (b) confirmed**: the trap struct's "PC" slot is actually
a *function argument* (likely `r0`/`r1` saved at exception entry, which
the trap handler displays as PC because it dumps the full register
file). The real instruction-pointing value is `ra=0x000641cb` — the
LR — which we already located in code at `0x641b8`'s `BL <assert>`.

### Control region (assert site) — confirmed code

```
0x641a0: fc9cf79d 682b3e0a 21e0f8d3 3f00f412
0x641b0: 2e09d101 f8d3d1f3 f41331e0 d1043f00
0x641c0: f240481c f79d118d 6ca3f80f 7f80f413
0x641d0: 2100d00d 4620460b 6200f44f fef8f7ff
```

Live TCM bytes in this range have the typical Thumb-2 encoding density:
`f240` (MOVW), `f80f` (LDRB.W literal pool form), `4620 460b`
(MOV r0,r4 ; MOV r3,r1), `bl` calls (`f7ff fef8`). Matches exactly the
disassembly we did desktop-side — control passes, our offset model is
right for this code region.

### Important secondary finding

The chip-info struct's last populated field at `0x62af0` holds
`0x00096f60` — a pointer into upper TCM. **Our console-buffer dump
in test.200 found readable text starting at `0x97000`**, just past
`0x96f60`. So `0x96f60` is the address of the `hndrte_cons` descriptor
header (which is typically a small struct followed by the ring buffer
itself). Reading that descriptor will tell us:

- Ring base address
- Ring size
- Current write index (so we can know where the *latest* console
  message is, instead of guessing from text positions)
- Possibly a "buffer-full" or "wrap" flag

### Implications

1. **The assert is operating on this chip-info struct.** With "v = 43"
   in the assert message and `ccrev=43` in the struct, the failing
   check is almost certainly something *about* `ccrev` — either:
   - Validating ccrev is in a supported list and 43 isn't there (in
     this firmware build), OR
   - Looking up a per-ccrev table entry and finding it null/missing.

2. **The chip-info struct is built by the firmware's `si_attach` /
   `si_kattach`** (hence the console-log line "si_kattach done.
   ccrev = 43, wd_msticks = 32" appearing right before the assert).
   So `si_kattach` succeeds, but the *next* function — which uses the
   built struct — finds `ccrev=43` unacceptable.

3. **Trap-handler register layout demystified.** The slot we were
   calling "PC" was carrying the asserted function's argument, not
   the PC. The trap handler likely dumps `r0..r12`, `sp`, `lr`,
   `pc`, `cpsr` in some order. The 16-word region at 0x9cf60..0x9d000
   is consistent with that: 16 slots, the right ballpark.

### Next step (test.202)

Two lines of attack, in increasing order of investment:

1. **Read the hndrte_cons descriptor at `0x96f60`**: 64-byte dump
   should reveal the ring metadata and exact write index. From there
   we can find the most recent console line precisely (no more
   pattern-matching the duplicate text shadows).

2. **Read the chip-info struct's table-lookup field**: if there's
   a per-ccrev table with a null slot for 43, the address of that
   table will be derivable from instructions immediately before the
   assert (around `0x6418c..0x641b6` — between any earlier prologue
   and the `MOVW r1,#0x18d` line-number store). Read that range
   live and decode the literal pool addresses (`LDR Rx, [pc,#imm]`)
   to find what value the assert is comparing against.

Plan to implement (1) first — it's a 4-row dump (~1 ms). If that
gives us a clean "latest console message" pointer, we can drop a lot
of the dumb text-window scanning that's currently giving us false
duplicates.

---

## PRE-TEST.201 (2026-04-22) — image translation: read TCM around trap PC and assert site

### Hypothesis

`PC=0x00062a98` from the trap data (decoded in test.200) reads as
all-zero bytes in the firmware *image file* at offset `0x62a98`. Two
possible explanations:

(a) Firmware loads with a non-zero base offset, so trap-PC values are
   virtual addresses that need translation before they map into the
   image.

(b) `0x62a98` is in the firmware's BSS/data area, and the trap PC is
   actually a function-pointer variable — the crash happened when the
   CPU branched through a function pointer that was uninitialized
   (pointing into BSS where the byte pattern is naturally zero).

If (b) is correct, then dumping live TCM at `0x62a98` should also show
zeros (BSS at runtime) — and the asymmetry between `0x62a98` (zeros)
and `0x641b8` (definitely instructions, we proved this desktop-side
already) confirms that one is data and the other is code.

If (a) is correct, the live TCM read at `0x62a98` will show
*instructions* — proving that the firmware is loaded with rambase=0
and we need a different image-offset translation to find the bytes
desktop-side.

### Implementation

**chip.c** — bump marker `test.200` → `test.201`. PMU still `0x17f`
bit-6-only (proven safe).

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                        | Rows |
|--------------------|------------------------------------------------|-----:|
| `0x62a80..0x62b00` | Live bytes around trap PC (decide a vs b)      |    8 |
| `0x641a0..0x641e0` | Live bytes around assert call site (control)   |    4 |
| `0x97000..0x97200` | Console ring (trimmed — 0x96000 was entropy)   |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text (proven useful)        |   64 |

Total = 108 rows = ~432 indirect MMIO reads ≈ 22 ms. Much cheaper
than test.200's 352-row dump.

The two new ranges are pure observation (live-TCM reads via the
existing indirect-MMIO helper). No firmware modification, no driver
behavior change — just adds 12 dump rows at the same dwell point.

### Build + pre-test

- About to rebuild module after edits.
- Last known PCIe state: clean post-test.200 (no MAbort).
- brcmfmac will be rmmod'd by the test script before insmod.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.201.journalctl.full.txt` (use the `.full.txt`,
the test script's truncated `.journalctl.txt` cuts off the dump rows).

### Expected outcomes (advance scoring)

- **PC 0x62a80 region all-zero in live TCM** → hypothesis (b)
  confirmed. Trap PC is a stale/null function pointer. Next step:
  search firmware for symbols/strings near offset 0x62a98 to identify
  which fp variable lives there, and trace where it should be set.

- **PC 0x62a80 region looks like instructions in live TCM** →
  hypothesis (a) confirmed. Firmware must load at non-zero rambase.
  Next step: compute the load offset (compare live `0x62a98` bytes
  against image bytes at known offsets to find the delta) and re-look
  at the trapping code from a corrected image position.

- **Assert site `0x641b8` matches the image bytes we found
  desktop-side** → control check passes; our offset model is right
  for at least the code we've already located.

---

## POST-TEST.200 (2026-04-22) — decoded ARM trap-data structure at fa=0x9cfe0

Logs: `phase5/logs/test.200.journalctl.full.txt` (always use `.full.txt`,
the test script's `.journalctl.txt` truncates the dump rows). Run text:
`phase5/logs/test.200.run.txt`.

### Headline result

The fault address `fa=0x0009cfe0` named in the assert message points to
a populated **ARM trap-data structure** in TCM. The 16 words around it
look exactly like a saved CPU context written by an exception handler:

```
0x9cf60: 00000000 00000713 00000000 0003ffff
0x9cf70: 00062a98 00000001 18000000 00000002
0x9cf80: 00000002 00001202 200001df 200001ff   ← CPSR-style words (mode bits)
0x9cf90: 00000047 00000000 000000fa 00000001
0x9cfa0: 0000018d 00062a08 00000009 0009cfe0   ← line=0x18d=397 stored explicitly!
0x9cfb0: 00058c8c 00002f5c bbadbadd bbadbadd   ← Broadcom 0xbbadbadd magic ×2
0x9cfc0: 00000000 0009cfd8 00001201 00001202
0x9cfd0: 00001202 200001ff 0009cfe0 00062a98
0x9cfe0: 18002000 00062a98 000a0000 000641cb   ← fault address — fa value
0x9cff0: 00062a98 0009d0a0 00000000 000a0000
```

Key observations:

- **Line number self-evident**: `0x9cfa0 = 0x18d = 397` matches the
  `hndarm.c line 397` in the assert text. The trap struct stores
  `line` as a u32.
- **Magic sentinel**: `bbadbadd bbadbadd` at `0x9cfb8/0x9cfbc` — the
  classic Broadcom "BAD BAD" trap-data marker, also referenced by
  upstream brcmfmac as `BRCMF_TRAP_DATA_MAGIC`.
- **CPSR words**: `0x200001df` and `0x200001ff` — these decode as ARM
  CPSR with V (overflow) flag set, A/I/F masked, mode `0x1f` (System)
  — i.e. saved as part of the exception entry.
- **ra/fa correspondence**: `ra=0x000641cb` (assert text) appears at
  `0x9cfec`. `fa=0x0009cfe0` is the address of the struct itself —
  recursively the trap struct's first 16 bytes are a small header.
- **Repeated PC value `0x00062a98`** appears at `0x9cf70`, `0x9cfd4`,
  `0x9cfe4`, `0x9cff0`. Likely the trapping PC and its propagated
  copies (saved across multiple slots: epc/cpc/lr).

### Console-buffer geometry now clearer

The wide 0x96000 region was overwhelmingly **entropy** (looks like a
random table or hash pool — all 4096 B nonzero, no ASCII patterns).
**The actual console text starts at `0x97000`** (not earlier as I had
guessed):

```
0x97000: "attach done. ccrev = 43, wd_msti"
0x97020: "cks = 32\r\n135178"
0x97030: ".345 ASSERT in f"
0x97040: "ile hndarm.c lin"
0x97050: "e 397 (ra 000641"
0x97060: "cb, fa 0009cfe0)"
0x97070: "\r\n" then 00 00 00 ... (ring tail)
```

So the console ring extends `0x97000..~0x97070` (continuous) and then
zeros to the end of region 0. The duplicate text we saw in test.199
`0x9cdb0..0x9cdf0` is the *same* assert text written via a second
sink (likely `hndrte_cons`'s shadow buffer in upper TCM near the trap
struct). Everything at `0x96000..0x96fff` is unrelated bulk data —
not console history. So next test should drop that range.

### Fact summary

- Fault is a *handled* assert: firmware vector caught it, populated
  `0xbbadbadd` trap data, wrote two copies of the message into the
  hndrte_cons sink, then halted.
- Trap PC = `0x00062a98` (Thumb). Trap LR = `0x000641ca` (=0x641cb&~1).
- Asserted line = 397 (`hndarm.c`), v=43, wd_msticks=32 (from text).
- The "v = 43" detail in the message is consistent with `ccrev`
  (chip common rev = 43) — the assert may be checking `ccrev` against
  an expected list and bailing because some host-side handshake
  hasn't told the firmware that we support its expected protocol.

### Open puzzles

- **PC=0x62a98 at firmware-image offset reads as zeros** (checked
  desktop-side). Two possibilities: (a) firmware loads with rambase
  offset, so PC is virtual not file-relative — needs translation by
  whatever load offset the bootloader uses; (b) `0x62a98` is in BSS
  (data section), and the trap PC is actually a function pointer
  variable holding the *target* of a call that crashed before it ran.
  Plan to investigate this with a tighter image read around the
  `MOVW r1, #0x18d` site we already located at `0x641b8`, and also
  to check the firmware ELF/PT_LOAD-equivalent metadata for any
  load-address adjustment.

- **What is the assert checking?** The assert call site is in a
  routine that runs *after* `si_kattach done` succeeds (because we
  see that line in the console buffer first). `wd_msticks=32` is
  printed alongside, which suggests this is in the watchdog/PMU
  setup path. Likely candidates for `hndarm.c:397`:
    - PMU resource-mask sanity check (firmware expects bits we
      didn't grant) — but our `max_res_mask=0x17f` matches what
      Broadcom's open driver uses for chiprev=43 already.
    - SHARED-RAM handshake check (firmware reads a magic value
      from a host-supplied location and asserts if missing).
    - Watchdog/clock-domain setup verification (since `wd_msticks`
      is printed in the same message, this code path is wd-related).

### Suggested next step (test.201 — to be planned in PRE-TEST.201)

Two tracks worth pursuing in parallel:

1. **Shared-RAM handshake**: re-examine where `brcmf_pcie_setup`
   writes the bootloader/shared structures and whether anything is
   missing for chiprev=43. Trace the writes the host *does* perform
   to TCM and compare against the populated firmware data
   (especially the area near `0x9d000..0x9d100`, just past the
   trap struct).

2. **Image translation puzzle**: read 4-byte stride around the
   firmware image at offsets `0x62a80..0x62b00` and `0x641a0..0x641e0`
   to confirm we *do* get instruction-shaped data at the assert
   call site (which we already proved at `0x641b8`) but not at
   the trap PC `0x62a98` — that asymmetry confirms hypothesis (b)
   above (BSS pointer) over (a) (virtual offset).

No firmware is being modified, no large excerpts will be committed.

---

## PRE-TEST.200 (2026-04-22) — extended TCM dump including fault address area

### Hypothesis

Test.199 caught the firmware assertion at `hndarm.c:397`. The assert
includes `fa=0x0009cfe0` (fault address) which sits just above our
test.199 dump end (`0x9cdc0`). Test.200 widens both dump ranges:

- `0x96000..0x97200` (was `0x96e00..0x97200`): catches earlier console
  ring-buffer history that may show what firmware was doing right
  before the assert.
- `0x9cc00..0x9d000` (was `0x9cc00..0x9cdc0`): covers the rest of
  the console message text AND the fault address `0x0009cfe0`. May
  reveal what the assert is actually checking for at that address.

### Firmware-image analysis (already done — desktop-only)

Found the assert call site in firmware: at offset `0x641b8` we see
`MOVW r1, #0x18d` (= **397** decimal — the line number) followed by
`LDR r0, =&"hndarm.c"` and a `BL` to the assert handler. Confirmed
identity of the line.

The return address from the captured ASSERT (`ra=0x000641cb`) is just
past this `BL` instruction, with the standard Thumb LSB set. This
gives us the function-level location of the assert: it's a routine
that runs after `si_kattach`, performs some hardware/state check, and
calls the assert handler with `r1=397`.

We don't decompile the function (clean-room rule), but we now know
*where* the failing check lives and can correlate test outcomes
against changes to host-side state that might satisfy that check.

### Implementation

**chip.c** — marker rename `test.199` → `test.200`. PMU unchanged.

**pcie.c** — widen `dump_ranges[]`:
- Region 0: `0x96000..0x97200` (4608 B = 288 rows)
- Region 1: `0x9cc00..0x9d000` (1024 B = 64 rows)

Total 352 dump rows, ~1408 indirect-MMIO reads (~70 ms). Still cheap
enough for a single end-of-dwell pass.

### Build + pre-test

- Module rebuilt clean.
- PCIe state still clean (verified post-test.199 reboot).
- Note: machine rebooted 07:24 (boot index 0) — test.199 ran cleanly,
  reboot was after test, possibly unrelated. brcmfmac currently
  loaded (test.199 left it loaded).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → `test.200.journalctl.full.txt` (use `.full.txt` — the test
script's truncated capture cuts off the dump rows).

---

## POST-TEST.199 (2026-04-22) — BREAKTHROUGH 3: firmware is ASSERTING — not waiting

Logs: `phase5/logs/test.199.journalctl.full.txt` (use `.full.txt`,
the test script's truncated `.journalctl.txt` cuts off the dump rows;
they appear earlier in the journal than the post-dwell fine scan that
fills the tail). Run text: `phase5/logs/test.199.run.txt`.

### Headline result

The firmware writes a `hndrte_cons`-style **debug console ring
buffer** into upper TCM. Decoding the dump:

```
Found chip type AI (0x15034360)
.125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x8a4d
                   pmurev 17, pmucaps 0x10a22b11
.125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
.134592.747 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
```

The firmware image (`/lib/firmware/brcm/brcmfmac4360-pcie.bin`)
contains the matching format strings — confirmed:
- `"Found chip type AI (0x%08x)"`
- `"ASSERT in file %s line %d (ra %p, fa %p)"`
- Source files referenced include `hndarm.c`, `hndrte_cons.c`,
  `hndrte.c`, `hndpmu.c`, `siutils.c`, `wlc_bmac.c` and many others.

### Updated mental model — firmware is *crashed*, not idle

| Earlier theory | Reality |
|---|---|
| Firmware in tight loop updating buffers | NO — buffers are written once during init, then frozen |
| Firmware in passive "wait for host handshake" idle | NO — firmware is **halted on assertion failure** |
| The 7 cells we kept catching across runs | These are the bytes of the ASSERT text (timestamp, line counter) and metadata struct that vary per boot |

What firmware actually does on each run:
1. Detects the chip (correct: 4360 AI)
2. Logs Chipc + PMU caps to console buffer
3. Calls `si_kattach` (~125888 us into firmware boot)
4. ~8704 us later (presumably some init step in `hndarm.c`), hits
   ASSERT at line 397 and halts.
5. Console buffer keeps the assertion message; ARM CR4 stays running
   (`CPUHALT=NO`, `RESET_CTL=0`) but doing nothing useful (no further
   register writes, no D2H mailbox, no IPC ring brought up).

### What we now know about TCM layout

| TCM region | Contents (decoded) |
|---|---|
| `0x96f70..0x97070` (~256 B) | Snapshot of the console log text (Found chip → si_kattach → ASSERT) |
| `0x97070..0x97200` | Zero-padded |
| `0x9cc00..0x9cd17` (~280 B) | Stack canary fill `"KATS"` repeating (= 0x5354414b LE — `'KATS'` reversed = `'STAK'`/start of "stack") |
| `0x9cd18..0x9cd2c` | Pointer-like values (high-bit-set 0x80000000 or'd over TCM addresses 0x9cd7e, 0x9cd87) |
| `0x9cd30..0x9cdaf` | hndrte_cons metadata struct: pointers to log buffer, line lengths, indices, plus mirrored values |
| `0x9cdb0..0x9cdc0` | Latest log message starting `"134592.747 ASSER..."` (continues past dump end) |
| `0x9cfe0` (fa) | The fault address from the ASSERT — just above our dump range |

### Cross-referencing the dump bytes

`0x9cd38 = 0x10a22b11` — this is `pmucaps` (16-bit chip register
literal value), so this struct stores firmware's snapshot of chip
state. Adjacent `0x9cd30 = ASCII "11b22a01"` is the same value
formatted as a hex string (matches `"pmucaps 0x10a22b11"` in the
console line) — so this struct holds both string and binary copies
of fields, classic log-record layout.

### Why the same 7 cells changed across runs

Re-explained simply: the per-run varying-text positions in the
hndrte_cons buffer landed on these 4-byte aligned cells. The text
contents of each ASSERT line vary slightly per boot (timestamp µs,
line counter `0x9cd50` — which is the µs value, e.g. 0x2eb=747 in
test.199), so those cells "differ from previous run" in the snapshot
diff. The cells with stable text (e.g. format-string constants) don't
diff and so don't show up in CHANGED lists.

### Next move (test.200)

Extend the dump to cover the **fault address area**
(`0x9cfc0..0x9d000`) and the area **before** the visible log start
(`0x96000..0x96e00`) to find:
- Whatever firmware code/data is at `fa=0x0009cfe0`
- Earlier console history (older log messages in the ring buffer)
- The hndrte_cons struct base pointer (so we can index it correctly)
- Any additional active write regions we missed

Also worth doing this run: search the firmware image for the
return-address `0x000641cb` to identify the function that calls the
ASSERT — gives us a function-level location for line 397 of hndarm.c.

Beyond test.200 — once we know what condition is failing in
hndarm.c:397, we can either change PMU/host setup to satisfy the
condition, or find a code path that avoids it. Likely candidate:
firmware expects the host to populate sharedram (D2H mailbox base
address) before bringing up the ARM CR4 — we currently never do
that handshake.

---

## PRE-TEST.199 (2026-04-22) — hex+ASCII dump of upper-TCM regions to decode firmware data structure

### What we know going into test.199

Test.198 changed the picture from "firmware runs continuous loops" to
"firmware runs init then halts":

- The 7 cells test.197 caught are written in the first <250 ms after
  `set_active` and **never updated again** during the 3 s dwell.
- Same 7 offsets are written across runs but values differ per run:
  test.197 wrote `0x335 = 821`, test.198 wrote `0xeb = 235`.
- Old "was" values come from the previous firmware run (TCM persists
  across rmmod/insmod since it's on-chip; rebooting the host would
  give us pristine ROM-poison values).

Reproducibility of the offset set + per-run variation of the values
implies these cells are a fixed firmware data structure storing
runtime values (calibration result, sensor reading, random init seed,
or boot-counter snapshot).

### Hypothesis

If we hex+ASCII dump the surrounding TCM region we should see:
- Adjacent printable bytes that extend the strings beyond the 4-byte
  cells we caught (e.g. "1366 84.235 A" might be part of a longer
  format string with field labels)
- Possibly format-string templates nearby (e.g. `"%4u %2u.%03u A"`)
- Other firmware-written fields that happened to land on already-zero
  bytes (so the wide-stride scan missed them)

### Implementation

**chip.c** — marker rename `test.198` → `test.199`. PMU unchanged.

**pcie.c** — replace the per-tick TS sample with a single end-of-dwell
hex+ASCII dump of two regions:
- `0x96e00..0x97200` (1 KB centred on 0x9702c)
- `0x9cc00..0x9cdc0` (448 B centred on 0x9cd48..0x9cdb8 active block)

Format per 16-byte row:
```
test.199: 0xNNNNN: ww0 ww1 ww2 ww3 | aaaaaaaaaaaaaaaa
```
where `wwN` is the 32-bit word read at +0/+4/+8/+12 and `a` is the
ASCII rendering (printables → char, others → '.').

Total log lines: (1024 + 448) / 16 = **92 dump rows** + the existing
fine-grain post-dwell scan. Cheap and easy to read.

### Build + pre-test

To do after edits — same checklist (build, PCIe state, push, sync).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.199.journalctl.txt`.

---

## POST-TEST.198 (2026-04-22) — firmware writes once at init then HALTS (revised model)

Logs: `phase5/logs/test.198.journalctl.txt` + `.full.txt`.

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ |
| `res_state` 0x13b → 0x17b | ✓ same as test.196/197 |
| Per-tick TS sample of 7 cells (12 ticks × 7 cells = 84 reads) | ✓ all SAME |
| ts-seed at dwell-250 ms shows final values already in place | ✓ |
| Post-dwell fine scan still finds same 7 cells "CHANGED" vs pre-set_active baseline | ✓ |

### Decoded — the model is "init + halt", not "running loops"

ts-seed at dwell-250 ms read:

```
[0x9702c]=0x34383636  "6684"
[0x97030]=0x3533322e  ".235"
[0x9cd48]=0x00323335  "532\0"
[0x9cd50]=0x000000eb  binary 235  ← matches ".235" in 0x97030
[0x9cdb0]=0x36363331  "1366"
[0x9cdb4]=0x322e3438  "84.2"
[0x9cdb8]=0x41203533  "35 A"
```

All 12 subsequent ticks (500 ms..3000 ms): every cell `delta=0 SAME`.

### Compared across runs

| Cell | test.197 final | test.198 final | Note |
|---|---|---|---|
| 0x9702c..0x97033 | "6172.821" | "6684.235" | varying |
| 0x9cd48..0x9cd4b | "128\0" | "532\0" | varying |
| 0x9cd50 (binary) | 0x335 = **821** | 0xeb = **235** | matches ASCII in 0x97030 each run |
| 0x9cdb0..0x9cdbb | "1352 98.036 A" | "1366 84.235 A" | varying |

**The binary at 0x9cd50 == the trailing ".NNN" digits in 0x97030 AND
in 0x9cdb4-0x9cdb8 each run** — same value formatted into both ASCII
buffers. Strong: the 7-cell change set is one logical record written
by a single sprintf-style routine during firmware init.

### Updated mental model

Firmware on this chip, with PMU `max_res_mask=0x17f` (HT clock only),
runs the following observable sequence after `set_active`:

1. (within first 250 ms) Sets `pmucontrol.NOILPONW`, leaves
   `clk_ctl_st = 0x00050040`.
2. (within first 250 ms) Writes a 1-record data structure spanning
   `0x97028..0x9cdbb` containing several stringified fields and one
   binary counter at `0x9cd50`. Looks like a calibration / sensor /
   boot-stat record — same offsets each run, fresh values each run.
3. After that — no further visible activity through the 3 s dwell
   (per-tick reads of the same cells stay constant; per-tick CC
   backplane regs stay constant except `pmutimer` which is the free
   counter).

What we still don't see:
- Any host↔firmware mailbox / doorbell handshake completing.
- Any IPC ring, sharedram pointer write, or D2H mailboxint event.
- D11 RESET still asserted (CPU never gets to bring up the radio MAC).

This is consistent with the firmware reaching the "wait for host
handshake" point in init and then idling because we never complete the
PCIe handshake (no sharedram base advertised, no doorbell, no MSI
configured).

### Next move (test.199)

Decode the firmware data structure: hex+ASCII dump of the active
region, look for adjacent printable text and format-string templates.
That tells us what firmware is reporting, and may give us a foothold
for matching offsets to known brcmfmac shared-memory layouts.

After test.199 — likely the right move is to rebuild the host-side
PCIe handshake from the trunk driver and retry the full bring-up; the
chip is ready, we just aren't talking to it.

---

## PRE-TEST.198 (2026-04-22) — per-tick time-series of 7 firmware-active TCM cells

### Hypothesis

Test.197 caught firmware updating 7 cells in the post-dwell scan window
(~400 ms after the 3000 ms dwell ended), including a binary counter
at `0x9cd50` whose value (0x335 = 821) matches an ASCII suffix at
`0x97030` (".821") — strong evidence of an active sprintf-style
loop. Test.198 reads the same 7 cells once per dwell tick (every
250 ms × 12 ticks) so we can measure the actual update cadence.

Expected outcomes (each is a useful datapoint):

| Pattern | Interpretation | Next move |
|---|---|---|
| Counter at 0x9cd50 increments by ~constant N every tick | firmware loop is periodic, N/250 ms = tick rate | use this rate to time other probes; investigate what gates the loop |
| Counter increments by varying N | firmware doing variable-cost work per loop | look at neighbouring cells for state |
| Counter does not change between ticks | activity we caught in test.197 was a one-shot, or update cadence > 250 ms | widen sample window, or use post-set_active baseline |
| Counter increments rapidly then stops | firmware hit an error / wait-for-host condition | examine what register state changed at the stop point |
| Hard crash (no precedent — these reads are very cheap) | something pathological with these specific addresses | retreat to test.197 baseline |

### Implementation

**chip.c** — marker rename `test.197` → `test.198`. PMU state unchanged
(`max_res_mask = 0x17f`, bit 6 only).

**pcie.c** — adds:
- `static const u32 ts_offsets[7]` containing the 7 active offsets
- `u32 ts_prev[7]` (stack) + `bool ts_seeded` flag
- Inside the existing dwell loop (after the CC backplane sample), a new
  block reads each of the 7 cells. First tick seeds `ts_prev` and logs
  the seed value. Subsequent ticks log value + delta vs prev tick.

Existing fine-grain post-dwell scan retained — we still want a chance
to spot any *new* active region we missed.

Per-tick cost: 7 indirect-MMIO reads ≈ ~50 µs each ≈ <0.5 ms per tick.
Negligible vs the 250 ms dwell increment. Should be crash-safe.

### Build + pre-test

- Module rebuilt clean (only pre-existing brcmf_pcie_write_ram32 warning).
- PCIe state from prior check (post-test.197): `MAbort-`, `FatalErr-`,
  `LnkSta` x1/2.5GT/s, `ASPM Disabled` — clean.
- brcmfmac module loaded from test.197 (test script will rmmod).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.198.journalctl.txt`.

---

## POST-TEST.197 (2026-04-22) — BREAKTHROUGH 2: firmware is *running loops* (ASCII counter strings updating in real time)

Logs: `phase5/logs/test.197.journalctl.txt` (892 brcmfmac lines) +
`test.197.journalctl.full.txt` (893 lines).

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ — slim dwell + 16 K post-dwell reads survived |
| `res_state` 0x13b → 0x17b (bit 6 only) | ✓ same as test.196 |
| Pre-release populate ran cleanly (16384 cells, 64 KB heap, ~6 s mark) | ✓ |
| Post-dwell scan found CHANGED cells | **7 of 16384** |
| Span of changes | `0x9702c..0x9cdb8` (23 952 bytes — wide, scattered) |
| 0x98000 / 0x9c000 (test.196 hits) — CHANGED again? | **No**, both UNCHANGED in test.197 |

### Decoded changes — firmware is updating ASCII counter strings

All seven changed cells decode as printable ASCII (little-endian):

| Addr | Old (hex / ASCII) | New (hex / ASCII) | Note |
|---|---|---|---|
| 0x9702c | 0x38393235 `"5298"` | 0x32373136 `"6172"` | adjacent → 8-byte string |
| 0x97030 | 0x3633302e `".063"` | 0x3132382e `".821"` | "5298.063" → "6172.821" |
| 0x9cd48 | 0x00303336 `"630\0"` | 0x00383231 `"128\0"` | null-terminated short string |
| 0x9cd50 | 0x00000024 (binary 36) | 0x00000335 (binary 821) | binary counter — **note 821 == suffix in 0x97030** |
| 0x9cdb0 | 0x32353331 `"1352"` | 0x31363331 `"1361"` | adjacent triple → 12-byte string |
| 0x9cdb4 | 0x302e3839 `"98.0"` | 0x382e3237 `"72.8"` | (cont) |
| 0x9cdb8 | 0x41203633 `"63 A"` | 0x41203132 `"12 A"` | (cont) → "1352 98.063 A" → "1361 72.812 A" |

**Significant detail**: the binary counter at `0x9cd50` reads `0x335 = 821`,
exactly matching the ASCII suffix in `0x97030` (`".821"`). This is firmware
*formatting* a binary counter into a printable string — strong evidence of
an active sprintf/print routine running, not just one-shot init writes.

### What this means

Test.196 showed firmware wrote two cells. Test.197 shows those exact cells
did NOT change again, but seven *other* cells did, **and the changes look
like a sprintf-style string buffer being updated**. The window between
pre-populate (~end-of-dwell) and post-dwell scan is only ~400 ms, so these
are events firing on a sub-second cadence. Firmware is alive and looping.

This is qualitatively different from test.196 (which could be read as
"firmware ran once and stopped"). Test.197 demonstrates **continuous
firmware execution** at sub-second granularity. The chip is functional;
what we still lack is the host↔firmware protocol bring-up that lets the
driver hand off control packets.

### Firmware progress timeline (unchanged from test.196)

- t=0 (pre-release): `pmucontrol=0x01770181`, `clk_ctl_st=0x00010040`
- t=250 ms: `pmucontrol=0x01770381` (NOILPONW set by firmware)
- t=500 ms–t=3000 ms: CC regs stable (firmware in steady-state loop)
- end-of-dwell: pre-populate snapshot of 0x90000-0xa0000 taken
- ~400 ms later: post-dwell scan → 7 cells CHANGED

### Hypothesis confirmed/refuted from PRE-TEST.197

| Hypothesis | Result |
|---|---|
| (a) Wide-stride aliasing — firmware only wrote two cells | **Refuted**. Test.197 shows multiple write hotspots not on the 16 KB grid. |
| (b) Contiguous structure | **Partially**. Two short adjacent runs (8 B at 0x9702c, 12 B at 0x9cdb0) but not one big block. |
| (c) Scattered singletons | **Confirmed for the binary counter** at 0x9cd50, possibly 0x9cd48 too. |

The picture is **multiple short string fields** scattered across 0x97000-0x9d000.
Looks like a status / log structure with several text fields and at least one
binary counter, all updated by the same firmware loop.

### Open puzzle

Test.196's writes (0x98000, 0x9c000) **did not repeat** in test.197.
Possibilities:
1. Those were one-shot init writes (zero-fill / stack-canary plant); test.197
   captured later steady-state activity instead.
2. The wide-TCM probe READ at those addresses during test.196 perturbed
   them (read-modify-clear on a register-aliased TCM region?). Unlikely —
   they are deep in TCM, not register-mapped.
3. Firmware behavior is non-deterministic across runs.

(1) is most plausible: test.196 caught early init, test.197 caught steady-state.

### Next options to consider

A. **Wider scan** (0x80000–0xa0000 or whole 0x00000–0xa0000) at 4-byte
   stride to find any other active write regions and any code/data near
   the strings that might decode as format-string templates.
B. **Time-series sample** of just the 7 known-active cells — read each
   cell every 250 ms during dwell, log values. Will tell us how fast
   the counter increments and whether the string fields update on a
   periodic schedule (heartbeat? watchdog?).
C. **Pre-set_active scan** — populate the snapshot BEFORE set_active so we
   see the *initial* writes too (test.196's 0x98000/0x9c000 hits) plus
   ongoing activity. Combine with end-of-dwell scan to see the full
   write history during the 3 s dwell.
D. **Decode the structure** — dump 0x97000-0x9d000 contents fresh (no
   compare) and look for printable strings with `strings` tool; might
   recognise format strings like `"%s %d.%03d A"` etc.

Recommendation: **B (time-series)** — cheapest, most informative.
Watching the counter at 0x9cd50 increment will tell us the firmware
loop frequency, which is a hard datapoint we don't have. If it
increments by N per 250 ms, we know the firmware tick rate.

---

## PRE-TEST.197 (2026-04-22) — fine-grain TCM scan over 0x90000–0xa0000 to map full extent of firmware writes

### Hypothesis

Test.196 caught two firmware-originated writes (`[0x98000]=0x00000000`,
`[0x9c000]=0x5354414b` "STAK") at exactly the 16 KB stride boundaries of
the existing `wide_offsets` scan. Either:

(a) Firmware wrote ONLY those two cells and they happened to land on the
    sample stride. Unlikely on a chip running real init code; suggests
    wide-stride aliasing.
(b) Firmware wrote a contiguous structure (e.g. an init descriptor /
    state block / shared-memory header) and our 16 KB stride only hit
    two cells of it. A finer scan will reveal the full extent.
(c) Firmware wrote multiple unrelated singletons at scattered offsets
    that happen to align with 16 KB boundaries by coincidence.

A 4-byte stride scan over the 64 KB upper-TCM region (0x90000–0xa0000)
will distinguish (a) from (b)/(c) and, if (b) holds, map the structure
boundaries — its size and content shape will tell us what state firmware
reached and what it might be waiting for next.

### Implementation

**chip.c** — marker rename only: `test.196` → `test.197`. PMU state
unchanged: `max_res_mask = 0x17f` (bit 6 only, proven safe).

**pcie.c** — add a heap-allocated 16384-cell pre-release snapshot covering
0x90000..0xa0000 at 4-byte stride (64 KB heap). The pre-release populate
runs silently (just logs a single completion line — printing 16384 cells
would spam the journal). The post-dwell scan reads all 16384 cells, prints
only the CHANGED entries, and emits a summary line:
- `fine-TCM summary: N of 16384 cells CHANGED`
- `fine-TCM CHANGED span 0x..... ..0x..... (NN bytes)` if any changed

The post-dwell single-shot scan adds ~16384 indirect-MMIO reads
(~400 ms in steady state with HT clock active). Test.196's slim dwell
harness already proved the chip survives extended post-dwell reads in
this PMU configuration; the new scan extends that window by ~400 ms but
does not poll mid-dwell.

### Expected outcomes

| Pattern of CHANGED cells | Interpretation | Next move |
|---|---|---|
| Only 0x98000 + 0x9c000 changed (same as test.196) | scattered singletons; firmware wrote two flags | grep firmware text image for these constants |
| Contiguous block of changed cells around 0x9c000 ("STAK..." string + neighbours) | firmware wrote a structure or string buffer | dump full block to decode purpose |
| Many scattered changes across 0x90000–0xa0000 | firmware writing init memory aggressively | classify into hot regions |
| Firmware wrote outside 0x90000-0xa0000 too | scan range too narrow | extend in test.198 |
| Hard crash | post-dwell read pressure with HT active is unsafe at 16 K reads | shrink range / increase stride |

### Build + pre-test

- chip.c, pcie.c edited; module built clean (only pre-existing
  brcmf_pcie_write_ram32 unused-function warning).
- PCIe state (verified before this run, still on boot 0):
  - `MAbort-`, `CommClk+`, `LnkSta` x1/2.5GT/s — clean
  - `UESta` all clear; `CESta` Timeout+ AdvNonFatalErr+ — accumulated
    correctable errors from the test.196 unbind cycle, benign.
  - `LnkCtl: ASPM Disabled` (we disabled it in chip_attach).
- brcmfmac module currently loaded (from test.196 success, test will rmmod).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.197.journalctl.txt`.

---

## POST-TEST.196 (2026-04-22) — BREAKTHROUGH: bit 6 alone is safe AND firmware finally writes TCM (first ever observation)

Logs: `phase5/logs/test.196.journalctl.txt` (885 brcmfmac lines) +
`test.196.journalctl.full.txt` (920 lines).

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ — system survived test cleanly, module rmmod'd normally |
| `res_state` 0x13b → 0x17b (bit 6 asserted, bit 7 NOT asserted) | ✓ |
| **First ever firmware-originated TCM writes detected** | ✓ |
| `fw-sample` 256-region scan post-dwell | 256 UNCHANGED — firmware code intact, no overwrite |
| `wide-TCM` post-dwell | **2 of 40 regions CHANGED** — firmware wrote scratch |

Specific writes found by post-dwell wide-TCM scan:

```
post-dwell wide-TCM[0x98000]=0x00000000 (was 0x15f3b94d) CHANGED
post-dwell wide-TCM[0x9c000]=0x5354414b (was 0xf39d6dd9) CHANGED
```

`0x9c000` is in the upper TCM (~624 KB from base, near the end of the
640 KB TCM). `0x5354414b` decodes as ASCII "KATS" little-endian / "STAK"
big-endian — looks like part of a firmware initialisation marker
(possibly "STACK" or a stack canary fill pattern). `0x98000` zeroed out.
**This is the first objective evidence in this project that firmware is
executing and writing data on this chip.**

### Bit 6 vs bit 7 decoded

| Signal | test.194 (max=0x13f) | test.195 (max=0x1ff, both 6+7) | test.196 (max=0x17f, bit 6 only) |
|---|---|---|---|
| `res_state` | 0x13b | 0x1fb | **0x17b** |
| `clk_ctl_st` pre-release | 0x00050040 | 0x01070040 | **0x00010040** |
| `clk_ctl_st` post-dwell | 0x00050040 | (crashed) | **0x00050040** (bit 0x40000 set during dwell) |
| `pmustatus` | 0x2a | 0x2e | 0x2a |
| `pmucontrol` post-dwell | 0x01770381 | 0x01770381 | 0x01770381 (NOILPONW set by fw within 250 ms) |
| Crash? | no | YES (mid-dwell freeze) | **no** |
| Firmware TCM writes? | 0 | unknown (crashed before scan) | **2** |

Bit 6 alone is the HT clock the firmware needs to execute. Bit 7 enables
something else (sets `clk_ctl_st` bits 0x10000+0x1000000 even before
`set_active` runs — confirmed by pre-release snapshot delta) and is the
destabiliser. Adding bit 7 to bit 6 simultaneously is what crashed
test.195.

### Firmware progress timeline (from per-tick CC backplane sample)

- t=0 (pre-release): `pmucontrol=0x01770181`, `clk_ctl_st=0x00010040`
- t=250 ms: `pmucontrol=0x01770381` (NOILPONW set), `clk_ctl_st=0x00050040`
  → firmware completed early `si_pmu_init` within first 250 ms
- t=500 ms through t=3000 ms: all CC regs stable (no further changes)
  → firmware then sits idle (or in a polling loop with no register-visible side effects)
- post-dwell: 2 wide-TCM cells found CHANGED
- D11 `RESET_CTL` stayed 0x1 throughout — firmware did NOT advance to D11 bring-up

### What this tells us

1. **Direction is fully validated.** Bit 6 of max_res_mask is THE gate.
   Firmware was waiting for HT clock; once we permit it, firmware runs
   and starts initializing.
2. **Bit 7 is dangerous and unnecessary** for the basic firmware unblock.
   We can leave it gated off for now.
3. **Firmware progress stops short of D11 bring-up.** It runs, completes
   PMU init, writes a small amount of scratch, then stalls. Likely waiting
   on something else: probably NVRAM (we currently don't fully program
   NVRAM), a host doorbell signal, or a second clock-domain enable.
4. **The slim dwell harness is a good baseline** for further bring-up
   work — it's safe even with HT clock active and gives clean per-tick
   PMU evolution data.

### Suggested next moves (priority order)

1. **Probe deeper into wide-TCM** — current scan only samples every 16 KB.
   Add a finer scan around `0x98000`–`0x9c000` to find the full extent
   of the firmware-written region. Possibly contains a fw-init structure
   we can decode to learn what state firmware reached.
2. **Test bit 7 alone** (`max_res_mask=0x1bf`) — formally confirm bit 7
   is the destabiliser independent of bit 6 (control test). Even with
   the slim harness, expect a crash; but we'll know.
3. **NVRAM revisit** — firmware in early init typically reads NVRAM for
   board-specific config (PHY calibration tables etc). If our NVRAM
   write is incomplete, fw could be sitting in a "wait for NVRAM ready"
   loop. Worth re-checking what we actually upload vs what wl.ko does.
4. **Forcing bit 6 via min_res_mask** — currently bit 6 is asserted only
   because we permitted it; the chip might cycle it. Setting
   `min_res_mask=0x17b` would FORCE bit 6 to stay on and could help fw
   make further progress.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| Bit 6 + bit 7 simultaneous activation is safe | 195 | falsified — chip freezes |
| Bit 6 alone destabilises the chip | **196** | **falsified** — bit 6 alone is safe |
| Heavy MMIO during dwell is universally safe | 195 | falsified |
| Slim dwell harness can't detect fw writes | **196** | **falsified** — caught both |

---

## PRE-TEST.196 (2026-04-22) — bisect res 6 vs 7 (try bit 6 only, max_res_mask=0x17f) + drastically reduce dwell-time MMIO

### Hypothesis

Test.195 proved widening `max_res_mask` activates resources 6 and 7 (first
ever res_state movement on this chip), but the simultaneous activation
combined with the heavy TCM-poll harness caused an unrecoverable freeze
~half-way through the 3000 ms dwell. Two unknowns to separate:

1. Which resource (6 or 7) destabilised the chip when its clock domain came
   live? Bit 6 only (`max_res_mask=0x17f`) lets us test bit 6 in isolation.
2. Is the freeze caused by the resources themselves, or by the MMIO storm
   the dwell-poll harness produces under a live HT clock? A drastically
   slimmer harness (no fw-sample / wide-TCM / tail-TCM scans during dwell)
   eliminates the harness as a confound — if the chip still freezes with
   bit 6 only and a slim harness, the resource is the gun.

### Implementation

**chip.c** — single-line change:
- `max_res_mask` write changes from `0x1ff` → `0x17f` (drop bit 7)
- Marker line updated: `BCM4360 test.196: max_res_mask 0x... -> 0x... (write 0x17f — bisect: bit 6 only)`

**pcie.c** — slim the dwell harness:
- Dwell stays 3000 ms total but is now split into 12 × 250 ms ticks.
- Each tick does ONLY: ARM/D11 wrapper probes (single MMIO each),
  TCM[0..0x1c] head scan (8 cheap reads), and the existing CC backplane
  sample (8 CC-only reads incl res_state, min_res_mask, max_res_mask,
  pmustatus, clk_ctl_st, pmucontrol, pmutimer, pmuwatchdog).
- The crashy heavy-MMIO loops (wide-TCM 40-read scan, tail-TCM 16-read
  scan, full fw-sample 256-read scan) are REMOVED from per-tick dwell.
- A SINGLE end-of-dwell summary scan runs after all ticks: full
  fw-sample (256 reads) reduced to a 3-bucket count (UNCHANGED /
  REVERTED / CHANGED) plus wide-TCM scan that only logs CHANGED entries.

### Expected outcomes

| Observation | Interpretation | Next |
|---|---|---|
| `max_res_mask 0x13f -> 0x17f` AND `res_state` advances to 0x17b (bit 6 only) | bit 6 alone activates cleanly; chip survives the dwell | follow up with bit 7 alone (`max_res_mask=0x1bf`) and confirm which destabilises |
| `res_state 0x17b` AND fw-sample summary shows CHANGED count > 0 | firmware finally writing TCM with HT clock alone | analyse what changed; pivot to per-region tracking |
| `res_state 0x17b` AND fw-sample all UNCHANGED, no crash | bit 6 unblocks resources but firmware still stalls; need more (min_res_mask widen, NVRAM, OTP) | widen min_res_mask to 0x17b in test.197 |
| Hard crash again with bit 6 alone and slim harness | bit 6 itself destabilises the chip independent of MMIO load | bit 7 alone next (`0x1bf`); if both crash, problem is the resources colliding with our PCIe state |
| `res_state` does NOT change to 0x17b | something else changed; investigate (or harness regression) | re-read code path |

### Build + pre-test

- chip.c, pcie.c edited; module built clean (one pre-existing unused-function
  warning unrelated to this change).
- PCIe state (verified post crash + SMC reset, current boot 0):
  - `MAbort-`, `CommClk+`, `LnkSta` Speed 2.5GT/s Width x1 — clean
  - `UESta` all clear; `CESta` AdvNonFatalErr+ (benign accumulator)
  - `DevSta` `CorrErr+ UnsupReq+` — benign post-boot noise
- No brcmfmac currently loaded.
- Hypothesis stated above.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.196.journalctl.txt`.

---

## POST-TEST.195 (2026-04-22) — max_res_mask widening WORKED (resources 6+7 asserted) but chip became unstable mid-dwell → hard crash (SMC reset required)

Logs: `phase5/logs/test.195.journalctl.txt` (792 brcmfmac lines) + `test.195.journalctl.full.txt` (2123 lines, full boot). Captured from journalctl boot -1 history after recovery — boot ended mid-dwell with no panic/MCE in dmesg (silent freeze).

### Key result — first ever observation of res_state advancing past 0x13b

| Register | test.194 (max=0x13f) | test.195 (max=0x1ff) | Delta |
|---|---|---|---|
| `max_res_mask` | 0x13f | **0x1ff** | widened by our write ✓ |
| `res_state` | 0x13b | **0x1fb** | **bits 6 + 7 newly asserted** (HT clock + backplane HT) |
| `clk_ctl_st` | 0x00050040 | **0x01070040** | new bits 0x01020000 set |
| `pmustatus` | 0x2a | **0x2e** | bit 0x4 set |
| `min_res_mask` | 0x13b | 0x13b | unchanged (we did not touch min) |

Diagnostic line in dmesg confirms write landed:
```
brcmf_chip_setup: BCM4360 test.195: max_res_mask 0x0000013f -> 0x000001ff (write 0x1ff)
```

**The hypothesis was correct in mechanism:** widening max_res_mask DID cause the chip to grant resources 6 and 7. This is the first time ever in this project that res_state has changed past the POR value of 0x13b.

### But — TCM never advanced AND chip became unstable

| Signal | Observation |
|---|---|
| TCM dwell-pre samples | UNCHANGED from baseline |
| TCM dwell-3000ms samples (got ~56 of 271 before crash) | ALL UNCHANGED — fw still not writing scratch |
| D11 RESET_CTL | 0x1 (still in reset) |
| ARM CR4 CPUHALT | NO (still running) |

**Box hard-crashed mid-dwell** (boot -1 ended at 00:53:12 BST, exactly when the TCM-sample stream stops at fw-sample[0x238f8]). No MCE, no panic, no oops in dmesg — the kernel just stopped logging. Required SMC reset to recover. Boot 0 (current, 00:54:26) is fresh, no module loaded; PCIe state clean (`MAbort-`, no FatalErr, link x1/2.5GT/s).

### Interpretation

Resources 6 and 7 control HT-clock domains. Enabling them simultaneously (the only delta vs test.194) caused the chip to switch into a state where the heavy TCM-poll loop (running every ~10ms during the 3s dwell) eventually triggered a fatal MMIO fault that the host couldn't recover from. Likely root cause: chip changed PCIe ref-clock or backplane clock once HT became available; the host's continued indirect-MMIO reads then collided with that transition and produced an unrecoverable CTO.

### Implications

1. **The unblock direction is right.** First res_state movement in 30+ tests means we're touching the actual gate.
2. **The diagnostic harness is now the liability.** The same TCM-poll loop that was safe in test.194 (resources gated off) is unsafe once resources are live.
3. **Firmware still hasn't started writing TCM** even with HT resources asserted. Either it needs more time than 3s, more resources (min_res_mask widening to *force* 6/7 to stay asserted), or a different trigger (NVRAM/OTP).

### Next test (test.196) — staged, low-poll diagnostic

Plan:
1. Keep `max_res_mask = 0x1ff` (proven to work).
2. Bisect bits 6 vs 7: try `max_res_mask = 0x17f` first (bit 6 only) — if safe, follow with bit 7. Identifies which resource destabilises the chip.
3. **Drastically reduce TCM-poll volume** during dwell — sample once at start, once at end. Replace with PMU/clk-state samples every 200ms (no-op MMIO of CC regs is cheap and stays in CC core which we know is safe).
4. Add `min_res_mask` and `max_res_mask` to the periodic PMU sample so we can see if firmware writes them.
5. If bit-6-only is also unstable, try widening *min_res_mask* to 0x17b (force bit 6 always asserted) — that may give firmware a stable HT clock long enough to write something.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| `max_res_mask = 0x1ff` widening doesn't matter | 195 | **falsified** — measurably activates resources 6+7 |
| 3s dwell with heavy TCM poll is universally safe | 195 | **falsified** — safe at res_state=0x13b but unsafe at 0x1fb |

---

## PRE-TEST.195 (2026-04-22) — widen max_res_mask from 0x13f (POR) to 0x1ff (wl.ko value)

### Hypothesis

Firmware is running (confirmed in test.194 post-mortem: ARM CR4 CPUHALT=NO
for 3s after set_active) but stalls on HT-clock polling. `res_state=0x13b`
and `max_res_mask=0x13f` throughout the dwell — the chip cannot grant
resources beyond bits 0..5 + bit 8 because max_res_mask forbids them.

Wl.ko's final PMU write programs `max_res_mask = 0x1ff` (bits 0..8). If
HT clock is driven by one of the bits the POR value of 0x13f masks out
(namely bits 6 and 7 — 0x40 and 0x80), widening to 0x1ff should allow
HT to assert and unblock the firmware poll.

### Implementation

One new write in `brcmf_chip_setup` (chip.c) after the PMU WAR block,
gated on `chip == BCM4360`:

```c
write(CORE_CC_REG(pmu->base, max_res_mask), 0x1ff);
```

Logged via `brcmf_err` with read-back before/after for proof.

### Expected outcomes

| Observation | Interpretation |
|---|---|
| `max_res_mask 0x0000013f -> 0x000001ff` AND TCM scratch shows CHANGED bytes | HT clock gate was the blocker; firmware advancing |
| `max_res_mask 0x0000013f -> 0x000001ff` AND res_state grows past 0x13b | resources 6/7 activated; firmware may still stall later |
| `max_res_mask 0x0000013f -> 0x000001ff` AND everything else identical to test.194 | max widening wasn't the gate; try min widening or OTP |
| Hard crash | unexpected — widening max_res_mask is documented behavior |

### Build + pre-test

- chip.c edited, built clean (brcmfmac.ko + chip.c timestamps match @ 2026-04-22 00:46)
- PCIe state (verified pre-run after crash + SMC reset):
  - `MAbort-`, `CommClk+`, LnkSta Speed 2.5GT/s Width x1 — clean
  - DevSta has `CorrErr+ UnsupReq+` — benign post-boot noise, no FatalErr
- Session context: prior session ended with a crash; user performed SMC reset
  before this run. Boot 0 (2026-04-22 00:49) is fresh, no prior module load.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.195.journalctl.txt`.

---

## POST-TEST.194 (2026-04-22) — PCIe2 writes landed cleanly, firmware executes but stalls on HT-clock polling

Log: `phase5/logs/test.194.journalctl.txt` (727 lines visible in dmesg) +
`test.194.journalctl.full.txt` (977 lines journalctl capture).

### Diagnostic output

```
test.194: PCIe2 CLK_CONTROL probe = 0x00000182   ← PCIe2 core alive, probe passed
test.194: SBMBX write done                        ← CONFIGIND 0x098 = 0x1 ✓
test.194: PMCR_REFUP 0x00051852 -> 0x0005185f    ← read back confirms +0x1f bits set
```

### Key finding — ARM CR4 IS RUNNING, firmware stalls on HT clock

Mis-read the earlier logs; ARM CR4 *is* released via `brcmf_chip_set_active`:

```
calling brcmf_chip_set_active resetintr=0xb80ef000 (BusMaster ENABLED)
brcmf_chip_set_active returned true
post-set-active-20ms   ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← ARM released
post-set-active-3000ms ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← still running
```

**Firmware executes but makes no observable progress.** Consistent with the
stall described in `phase6/wl_pmu_res_init_analysis.md §1`: firmware writes
`NOILPONW` (pmucontrol bit 0x200) early in `si_pmu_init` — we see
pmucontrol change from 0x01770181 → 0x01770381 over the dwell — then
polls for HT clock availability and never sees it.

### Evidence that ARM is running but stalled

| Signal | Value | Interpretation |
|---|---|---|
| ARM CR4 IOCTL | 0x0021 → 0x0001 | CPUHALT cleared ✓ |
| pmucontrol | 0x01770181 → 0x01770381 | NOILPONW bit 0x200 was set by firmware `si_pmu_init` |
| pmustatus | 0x2a (stable) | no progress (expect HT_AVAIL bits to appear) |
| res_state | 0x13b (stable) | HT resource never asserted |
| min_res_mask | 0x13b | unchanged |
| max_res_mask | 0x13f | unchanged — **HT resources likely gated OUT** |
| D11 RESET_CTL | 0x0001 (stable) | D11 still in reset — firmware never gets far enough to initialise D11 |
| TCM | all stable | firmware isn't writing scratch/heap → stuck in polling loop |

### Next hypothesis — widen max_res_mask to 0x1ff

Wl.ko's final writes at +0x153ed/+0x15401 program `min_res_mask` and
`max_res_mask`. POR leaves max_res_mask=0x13f (bits 0..5, 8). Wl.ko
widens max to **0x1ff** (bits 0..8 all permitted). If the HT clock
resource sits at bit 6 or bit 7, the chip can never grant it without
the wider mask, so the firmware's HT-avail poll will never succeed.

Planned test.195:

1. In `brcmf_chip_setup` (before the PMU WAR block), write
   `max_res_mask = 0x1ff` (offset 0x61c). Leave min_res_mask alone
   (POR=0x13b matches wl.ko's resolved value).
2. Use `brcmf_err`/`pr_emerg` for the write log so it's visible.
3. Expected signature of success: either (a) res_state grows beyond
   0x13b over the dwell, or (b) D11 RESET_CTL changes from 0x1 to 0x0
   (fw advances to core init), or (c) TCM scratch regions show writes.

### Ruled out so far

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/#7/#0xe/#0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |

### Remaining untested candidates (priority order)

1. **max_res_mask = 0x1ff** (test.195 — planned above, cheap bit widen)
2. **OTP init / radio calibration** — brcmfmac skips OTP entirely; firmware
   might need OTP-derived values before HT can assert
3. **min_res_mask = 0x1ff** also (go nuclear after max)
4. **D11 core passive init** — brcmfmac doesn't explicitly do anything to D11
   core before set_active; maybe firmware expects clock-enable

---

## PRE-TEST.194 (2026-04-22) — minimal PCIe2 init (SBMBX + PMCR_REFUP) re-enabled with liveness probe

**Status:** pcie.c edited, module built clean, ready to run.

### Hypothesis

After ruling out PMU WARs in test.193, next candidate is the PCIe2 core
bring-up that `brcmf_pcie_attach` currently bypasses entirely for BCM4360.
Auditing bcma's `bcma_core_pcie2_init` against our actual silicon
(chiprev=3, pcie2 core rev=1) eliminates 4 of 6 workarounds (DLYPERST, LTR,
crwlpciegen2, crwlpciegen2-gated) because their revision gates aren't met.

The only UNCONDITIONAL writes bcma does are:
- `PCIE2_SBMBX (0x098) = 0x1` — PCIe2 soft-mbox kick
- `PCIE2_PMCR_REFUP (0x1814) |= 0x1f` — power-management refup timing

If either of these is what gets PCIe2 to assert the signal the ARM CR4
firmware is polling, we may see first-ever TCM/D11 state change.

### Implementation (pcie.c brcmf_pcie_attach)

Replaced the full `if (BCM4360) return;` bypass with:
1. `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)`
2. Read `BCMA_CORE_PCIE2_CLK_CONTROL` (offset 0x0 of PCIe2 core) as a
   liveness probe. If it reads back `0xFFFFFFFF` or `0x00000000`, abort
   without doing any writes (PCIe2 core is dead/in reset).
3. Otherwise, perform the two writes via the indirect-config addr/data
   register pair (`CONFIGADDR = 0x120`, `CONFIGDATA = 0x124`):
   - `CONFIGADDR = 0x098; CONFIGDATA = 0x1`   (SBMBX)
   - `CONFIGADDR = 0x1814; DATA = read | 0x1f`  (PMCR_REFUP RMW)

All steps emit `pr_emerg` so output is visible without INFO debug enabled.

### Safety notes

- The original bypass was added to avoid a CTO→MCE crash caused by accessing
  PCIe2 MMIO while the PCIe2 core is in BCMA reset. The bypass condition was
  discovered empirically. Current flow (test.188 baseline + test.193 PMU WARs)
  has already successfully accessed BAR0 MMIO many times in buscore_reset /
  chip_attach / reset_device-bypass paths. The liveness probe catches the
  legacy failure mode if it returns.
- If the CLK_CONTROL probe returns an anomalous value (e.g. 0xDEADBEEF or a
  very bit-stuck pattern), that still indicates some form of "alive" and we
  will proceed with writes. The 0x0 / 0xFFFFFFFF guard is specifically for
  "device response missing" (CTO hardware default).
- The writes are to indirect config space via the on-chip CONFIGADDR/DATA
  pair; they do not touch PCIe link parameters and cannot break the bus.

### Decision tree

| Observation | Meaning | Next |
|---|---|---|
| Probe returns 0xffffffff or 0 | PCIe2 core in reset — writes skipped | Need to release PCIe2 BCMA reset first (test.195) |
| Probe returns real value, writes succeed, firmware boots (TCM CHANGED) | PMCR_REFUP/SBMBX was the gate | Follow firmware startup, enable remaining probe steps |
| Probe returns real value, writes succeed, firmware still silent | PCIe2 unconditional writes not the blocker either | Pivot to OTP init (option B) or D11 core (option C) |
| Hard crash | Something in the write path trips the CTO regression | Restore bypass, investigate core reset state |

### Pre-test checklist

1. Build status: REBUILT CLEAN
2. PCIe state: MAbort-, CommClk+, link up x1/2.5GT/s (verified before test.193)
3. Hypothesis stated: see above
4. Plan committed and pushed: this commit
5. Filesystem synced in commit step

### Run command

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.194.journalctl.txt`.

---

## POST-TEST.193 (2026-04-22) — WARs confirmed landing but produce no firmware progress → PMU WARs ruled out as blocker

Log: `phase5/logs/test.193.journalctl.txt` (974 lines) + `.full.txt`.

### Diagnostic output confirmed

```
test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11
test.193: PMU WARs applied — chipcontrol#1 0x00000a10->0x00000a10
          pllcontrol#6=0x080004e2 #0xf=0x0000000e
```

| Fact | Evidence |
|---|---|
| Gate condition met (`chip==4360 && ccrev>3`) | ccrev=43, prints "applied" not "SKIPPED" |
| pmurev=17, pmucaps=0x10a22b11 | matches wl.ko expectations for BCM4360 |
| chipcontrol #1 already has bit 0x800 SET at probe time | read-back 0x00000a10 both before AND after OR-0x800 |
| pllcontrol #6 write landed | read-back 0x080004e2 matches value we wrote |
| pllcontrol #0xf write landed | read-back 0x0000000e matches value we wrote |
| Firmware still blocked | all TCM/D11 scratch UNCHANGED, res_state=0x13b UNCHANGED |

**Bottom line:** chip_pkg=0 PMU WARs are NOT the firmware-stall blocker.
Bit 0x800 of chipcontrol #1 is already set by POR/bootrom; the pllcontrol
#6/#7/#0xe/#0xf writes land cleanly but have no visible downstream effect
on pmustatus / res_state / clk_ctl_st / TCM.

### Comparison vs test.192 (WARs off) and test.191 (baseline)

All PMU/TCM samples IDENTICAL to test.191 baseline. The WARs changed **nothing
visible** in any register we currently sample. Likely explanations:

1. The pllcontrol writes are regulator voltage targets — effect is only
   observable on an oscilloscope / by downstream resources drawing that rail.
   No register snapshot would show it.
2. The WARs enable capabilities the firmware needs **later**, once it's
   running; but firmware never starts because a **different** prerequisite
   is still missing.

Either way, we've exhausted the PMU-WAR hypothesis.

### Next gap to investigate — PCIe2 core bring-up

Log line at test.193 t=2219ms: `BCM4360 test.129: brcmf_pcie_attach bypassed
for BCM4360` — brcmfmac's `brcmf_pcie_attach` returns early for BCM4360 at
pcie.c:895, skipping:

- **PCIE2_CLK_CONTROL DLYPERST/DISSPROMLD** workaround for rev>3
  (this is THE BCM4360-specific PCIe workaround from bcma; phase6 gap analysis
  ranked it #1 of missing writes)
- LTR (Latency Tolerance Reporting) config
- Power-management clock-period, PMCR_REFUP, SBMBX writes

Our earlier decision to bypass brcmf_pcie_attach was to avoid a crash during
development; now that the chip is stable through fw-download, we can re-enable
selective parts. Recommend test.194: implement just the **PCIE2_CLK_CONTROL
DLYPERST/DISSPROMLD** write (bcma `bcma_core_pcie2_workarounds` for BCM4360
corerev>3) as the next candidate unblock.

### Preserved evidence

- `phase5/logs/test.192.journalctl.txt` — WARs silent (INFO filtered)
- `phase5/logs/test.193.journalctl.txt` — WARs confirmed via brcmf_err
- `phase6/wl_pmu_res_init_analysis.md` — PMU WAR analysis with §0/§0.1 corrections

### Action items (next session)

1. Re-read `phase6/downstream_survey.md` and the bcma `driver_pcie2.c`
   DLYPERST/DISSPROMLD workaround.
2. Find the PCIE2 core in chip->cores (PCIE2 coreid / pci_dev base address).
3. Implement the workaround in a new callsite (before set_active / fw download),
   gated on BCM4360 && corerev>3.
4. Test as test.194.

---

## PRE-TEST.193 (2026-04-22) — diagnostic build to confirm WARs land

(Now superseded by POST-TEST.193 above. Original plan retained for context.)

### Test.192 result — no crash, no visible state delta

Log: `phase5/logs/test.192.journalctl.txt` (also `test.192.journalctl.full.txt`,
972 + 971 lines respectively).

**Good news:** the probe path ran end-to-end, reached firmware download (442233
bytes to TCM), completed the 3000ms dwell, cleared bus-master, returned clean
-ENODEV. **No hard crash.**

**Observed state at dwell-3000ms (BASELINE vs WAR-enabled, side-by-side):**

| Register | test.191 (no WARs) | test.192 (WARs) | Delta |
|---|---|---|---|
| `CC-clk_ctl_st` | 0x00050040 | 0x00050040 | UNCHANGED |
| `CC-pmucontrol` pre-release | 0x01770181 | 0x01770181 | same |
| `CC-pmucontrol` post-dwell | 0x01770381 | 0x01770381 | **same CHANGED bit-0x200** |
| `CC-pmustatus` | 0x0000002a | 0x0000002a | UNCHANGED |
| `CC-res_state` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-min_res_mask` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-max_res_mask` | 0x0000013f | 0x0000013f | UNCHANGED |
| `CC-pmutimer` | 0x0457e14b → ... | 0x0457e14b → ... | (free-running) |
| All ~30 TCM/D11 scratch regions | all UNCHANGED | all UNCHANGED | UNCHANGED |

Conclusion: **the WAR writes had zero observable effect on any sampled
register.** Either (a) the writes never executed (gate condition false), or
(b) they executed but don't produce any side effect we're currently sampling.

### Diagnostic gap

`brcmf_dbg(INFO, "BCM4360 test.192: applied chip_pkg=0 PMU WARs")` was
silent — INFO-level debug is filtered out of dmesg by default. Every
previous test's `brcmf_dbg(INFO, ...)` output (e.g. `ccrev=%d pmurev=%d`
at chip.c:1131) is also missing from test.188/191/192 logs. So I cannot
distinguish "WARs skipped because `cc->pub.rev ≤ 3`" from "WARs ran but
had no effect".

### Test.193 — diagnostic upgrade (rebuilt clean, ready to run)

Changed `brcmf_dbg(INFO, ...)` → `brcmf_err(...)` for the test.192 marker,
added a chip/rev dump before the gate, and added read-back of
`chipcontrol #1`, `pllcontrol #6`, `pllcontrol #0xf` after the writes to
prove the indirect address/data pair is actually landing values.

Expected new log lines (all via `brcmf_err` so always print):

```
BCM4360 test.193: chip=0x4360 ccrev=<N> pmurev=<M> pmucaps=0x<caps>
BCM4360 test.193: PMU WARs applied — chipcontrol#1 0x<pre>->0x<post> pllcontrol#6=0x080004e2 #0xf=0x0000000e
```
(or `PMU WARs SKIPPED` with the reason.)

### Decision tree after test.193

| Log line | Interpretation | Next |
|---|---|---|
| `WARs SKIPPED (chip=0x4360 ccrev=<N>)` with N ≤ 3 | gate too strict; wl.ko path does not actually require corerev > 3 for chip_pkg=0 | drop the `ccrev>3` constraint, rebuild |
| `WARs SKIPPED` with chip ≠ 0x4360 | unexpected chip id match failure — investigate BRCM_CC_4360_CHIP_ID constant | grep the header |
| `WARs applied` but pllcontrol readbacks show 0x00000000 | write-ignore — wrong offsets or wrong corerev gating in hardware | re-audit, try raw 0x660/0x664 via ops->write32 with absolute offset |
| `WARs applied` with correct readbacks, state still all UNCHANGED | WARs did land but firmware still blocked by something else | pivot to next gap: PCIe2 init (DLYPERST/DISSPROMLD) or min/max_res_mask widen |
| `WARs applied` with correct readbacks, res_state or pmustatus CHANGED | first sign of progress; follow the signal | sample additional resources, keep going |

### Run command (same as test.192)

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected log: `phase5/logs/test.<N>` (script auto-increments; rename to `test.193.journalctl.txt`).

---

## Older test history

Tests prior to test.193 have been moved to [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md) to keep this file small for fresh-session pickup. When a new POST-TEST is recorded here, the oldest PRE/POST pair gets pushed to the top of the history file so this file always holds the latest 3 tests.
