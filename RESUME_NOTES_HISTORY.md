## POST-TEST.238 (2026-04-23 00:55 BST, boot -1 — wedged in [t+90 s, t+120 s] post-set_active; SMC reset required) — 22 of 23 breadcrumbs landed, fw runs ≥90 s under seed

### Summary

Test.238's ultra-extended ladder ran with `bcm4360_test236_force_seed=1`
and `bcm4360_test238_ultra_dwells=1`. Probe executed fw download, NVRAM
write, seed write, FORCEHT, `pci_set_master`, and `brcmf_chip_set_active`
cleanly. `set_active` returned TRUE. The 23-step post-set_active ladder
then landed **22 breadcrumbs** (t+100, 300, 500, 700, 1000, 1500,
2000, 3000, 5000, 10000, 15000, 20000, 25000, 26000, 27000, 28000,
29000, 30000, 35000, 45000, 60000, 90000 ms) before the journal cut
at 00:52:24 BST. Missing only `t+120000ms dwell` (expected at
00:52:46, ~22 s after the cut) and all post-dwell lines.

Host wedged. User performed SMC reset; current boot 0 started
00:54:07 BST clean.

### Evidence (boot -1 tail, from `journalctl -b -1 -k`)

```
Apr 23 00:50:46 test.238: calling brcmf_chip_set_active resetintr=0xb80ef000 (ultra-extended ladder t+120s)
Apr 23 00:50:46 test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006
Apr 23 00:50:46 test.238: brcmf_chip_set_active returned TRUE
Apr 23 00:50:46 test.238: t+100 / 300 / 500 / 700 / 1000 / 1500 / 2000 / 3000 / 5000 ms  (batched)
Apr 23 00:50:50 test.238: t+10000ms dwell
Apr 23 00:50:55 test.238: t+15000ms dwell
Apr 23 00:51:00 test.238: t+20000ms dwell
Apr 23 00:51:05 test.238: t+25000ms dwell
Apr 23 00:51:06 test.238: t+26000ms dwell
Apr 23 00:51:07 test.238: t+27000ms dwell
Apr 23 00:51:08 test.238: t+28000ms dwell
Apr 23 00:51:09 test.238: t+29000ms dwell
Apr 23 00:51:10 test.238: t+30000ms dwell
Apr 23 00:51:15 test.238: t+35000ms dwell
Apr 23 00:51:25 test.238: t+45000ms dwell
Apr 23 00:51:41 test.238: t+60000ms dwell
Apr 23 00:52:11 test.238: t+90000ms dwell         ← last test.238 line of boot -1
<then only non-BCM4360 traffic (wlp0s20u2 wlan) through 00:52:24 — journal ends>
```

Live timestamps through t+90s prove the driver thread was
schedulable and the kmsg flush path healthy for ≥90 s
post-set_active. No Oops, no Call Trace, no watchdog fire, no
softlockup backtrace in boot -1.

### Key interpretations

1. **Rewrites test.237:** the `t+25000ms dwell` line we had treated
   as the wedge-adjacent breadcrumb was not the wedge moment at
   all. Test.238 shows t+25 through t+90 s all land cleanly, so
   test.237's shorter ladder simply didn't have breadcrumbs past
   t+30 s to print. Test.237's journal cut was tail-truncation or
   rmmod-phase artefact, not wedge timing.
2. **Wedge window [t+90 s, t+120 s]:** directly bounded — t+90 s
   landed live, t+120 s did not and would have logged at 00:52:46,
   ~22 s past the 00:52:24 journal cut.
3. **Fw has a late trigger** — the deadline is ~100–120 s, ~4–5×
   longer than anything test.237 saw. Compatible with:
   - Internal fw watchdog expiring after 3–4 periods of a 30 s tick.
   - One-shot fw timer (~100 s) firing DMA-read of an
     uninitialised shared-memory pointer (pcie_shared /
     ringinfo / console / mailbox).
   - Fw heartbeat expecting host ring-back after N intervals.

### Observations worth keeping

- **No softlockup panic** despite 3 long msleeps (30 s, 30 s, 30 s)
  in the ladder; `softlockup_panic=1` + `softlockup_all_cpu_backtrace=1`
  didn't fire, which confirms the driver thread was yielding and
  the *host* CPUs weren't stalled during the 90 s run. Wedge must
  hit somewhere between 00:52:11 and 00:52:24, and kills the bus
  fast enough that host journald can't flush any wedge-witness
  lines.
- `BAR0 timing PRE` showed `dd: Input/output error` — but `lspci`
  PRE showed `Mem+ BusMaster+ MAbort-`. Likely the BAR0 raw dd was
  tripping on an earlier boot-0 condition that didn't prevent the
  probe from running (insmod proceeded to completion).
- The batched-at-00:50:46 cluster (t+100 … t+5000 ms) vs the live
  per-second flush from t+10 s onwards matches prior journald
  flush dynamics; not wedge-relevant.

### Artifacts

- `phase5/logs/test.238.run.txt` — PRE capture + insmod + "sleeping 240s"
  (truncated because host wedged during sleep)
- `phase5/logs/test.238.journalctl.full.txt` (1438 lines) — full
  boot -1 journal
- `phase5/logs/test.238.journalctl.txt` (378 lines) — filtered
  BCM4360/brcmfmac/watchdog subset

---


## PRE-TEST.238 (2026-04-23 00:4x BST, boot 0 post-SMC-reset from test.237) — ultra-extended dwell ladder to t+120s with 1s fine-grain through [t+25..t+30s] window

### Hypothesis

Test.237 bounded the wedge moment to [t+25s, t+40-45s]. Two
very-different mechanisms fit the evidence:

**A. "Fw fixed timeout at ~t+30s"** — journal was flushing live by
t+10s (per-second timestamps for t+10/15/20/25), so tail-truncation
was likely seconds at most. Wedge would be at t+30s ±1-2s. Mechanism:
fw waits N seconds for some host-side response (IRQ / doorbell /
shared-struct read) then fires an internal trap/watchdog.

**B. "Wedge is later (≥t+40s), full tail-truncation"** — if the
kernel buffer pressure came back at wedge time, the ~15-20s budget
applies and the actual wedge could be at t+40-45s. Mechanism:
similar to A but different deadline.

Both models predict fw wedges the PCIe bus eventually; but the exact
deadline matters for whether we're racing a fw watchdog vs. a fw
heartbeat timer vs. something else.

**Discriminator:** run a ladder that is fine-grain through
[t+25..t+30s] (1s steps) AND extends to t+120s. Expected patterns:

| Last landed breadcrumb | Interpretation |
|---|---|
| t+26/27/28/29/30s cuts (e.g., t+28 lands, t+29 doesn't) | **Model A confirmed** — fw timeout bracket. Pivots plan to "build shared-struct fast enough to race the timeout" |
| t+30s lands, cuts in [t+35..t+45s] | **Model B (timeout slightly later)** — still within the set_active-tripped bus-crash model, ~5s slack |
| Lands past t+45s (e.g., t+60 lands, t+90 cuts) | Wedge is NOT fixed-timeout; possibly conditional on a future host action (e.g., `rmmod`) or intermittent |
| All 23 breadcrumbs land + clean BM-clear + -ENODEV | **Extraordinary** — long wait somehow avoids the wedge (maybe fw self-heals if untouched long enough?) |

### Code change

1. New module param `bcm4360_test238_ultra_dwells` (default 0).
2. New `else if` branch before test.237 in the set_active chain.
   Ladder: t+100, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000,
   15000, 20000, 25000, 26000, 27000, 28000, 29000, 30000, 35000, 45000,
   60000, 90000, 120000 ms (23 post-set_active breadcrumbs).
3. Existing test.235, test.237, test.234 paths preserved.

### Run sequence

```bash
# single run this boot
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1
# ladder runs ~121 s post-set_active; probe return adds ~1 s
sleep 240
# host may be wedged; if so, SMC reset
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Budget is 2× max dwell (advisor). Sysctls: nmi_watchdog=1,
hardlockup_panic=1, softlockup_panic=1, softlockup_all_cpu_backtrace=1.

### Hardware state (boot 0, post-SMC-reset)

- Boot 0 started 2026-04-23 00:35:43 BST.
- `lspci -vvv -s 03:00.0`: Control Mem+ BusMaster+, MAbort-, fast-UR.
- No modules loaded. Clean post-SMC-reset idiom.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~00:4x BST. `strings` confirms
`bcm4360_test238_ultra_dwells` module param + all 23 new test.238
breadcrumbs. Pre-existing unused-variable warnings unchanged.

### Expected artifacts

- `phase5/logs/test.238.run.txt` — PRE + harness output
- `phase5/logs/test.238.journalctl.full.txt` — full boot journal
- `phase5/logs/test.238.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: REBUILT CLEAN above.
2. PCIe state: clean per above.
3. Hypothesis: bracket fw-timeout vs. late-wedge (A vs. B), above.
4. Plan: in this block; commit+push+sync before insmod.
5. Filesystem sync on commit.

---


## POST-TEST.237 (2026-04-23 00:32 BST, boot -1 — wedged at ~t+25-45 s post-set_active, SMC reset required) — extended dwell ladder landed 13 breadcrumbs; fw runs for tens of seconds under seed

### Summary

With `bcm4360_test236_force_seed=1` and
`bcm4360_test237_extended_dwells=1` together, the probe executed
the full fw-download, NVRAM write, seed write, FORCEHT dance,
pci_set_master, and `brcmf_chip_set_active` cleanly. `set_active`
returned TRUE. The extended ladder then flushed 13 dwell
breadcrumbs — t+100 / 300 / 500 / 700 / 1000 / 1500 / 2000 /
3000 / 5000 / 10000 / 15000 / 20000 / 25000 ms — before the
journal cut. Missing: `t+30000ms dwell`, dwell-done, BM-clear,
release-core, -ENODEV, and everything downstream.

Host wedged. User performed SMC reset; current boot 0 started
00:35:43 BST clean.

### Evidence (boot -1 tail, from `journalctl -b -1 -k`)

```
Apr 23 00:32:27 test.237: calling brcmf_chip_set_active resetintr=0xb80ef000 (extended-dwell ladder)
Apr 23 00:32:27 test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006
Apr 23 00:32:27 test.237: brcmf_chip_set_active returned TRUE
Apr 23 00:32:27 test.237: t+100ms dwell     (batched flush; set_active ~t=00:32:22)
Apr 23 00:32:27 test.237: t+300ms dwell
Apr 23 00:32:27 test.237: t+500ms dwell
Apr 23 00:32:27 test.237: t+700ms dwell
Apr 23 00:32:27 test.237: t+1000ms dwell
Apr 23 00:32:27 test.237: t+1500ms dwell
Apr 23 00:32:27 test.237: t+2000ms dwell
Apr 23 00:32:27 test.237: t+3000ms dwell
Apr 23 00:32:27 test.237: t+5000ms dwell
Apr 23 00:32:31 test.237: t+10000ms dwell   (live flush)
Apr 23 00:32:36 test.237: t+15000ms dwell   (live flush)
Apr 23 00:32:42 test.237: t+20000ms dwell   (live flush)
Apr 23 00:32:47 test.237: t+25000ms dwell   (last line of boot -1)
<journal ends — host wedged>
```

The transition from batched-at-00:32:27 to individually flushed
after ~t+5s is journald behavior — once the kernel buffer
pressure passes, kmsg writes flush immediately. So the
timestamps after t+10s are *real* driver-thread scheduling times.

### Key interpretation

**Falsified:** wedge is instantaneous or sub-second post-set_active.
Previously-best lower bound was t+700ms (test.236 Run B).
Test.237 extends that by a factor of ~36× — fw+driver both run
for ≥25 seconds.

**Bounded:** actual wedge moment ∈ [t+25 s, t+40-45 s]. The
upper bound is the ~15-20 s journald tail-truncation window
established in tests 231/232/234. Cannot tighten further from
this run alone.

**Implication for fw-wedge model:** whatever fw is waiting
for / running in / periodically checking, the timeout is tens
of seconds, not milliseconds. This is compatible with:
- a periodic watchdog / heartbeat on fw's side that fires
  after ~20-30 s of no valid host-side interaction
- fw eventually dereferencing an uninitialised pointer in
  an yet-unwritten shared-memory struct (ringinfo / console /
  mailbox / scratch_buf)
- fw attempting to DMA-read a host address we haven't supplied

### Observations worth keeping

- Pre-set-active snapshot (at 00:32:27) shows `TCM[0x90000] =
  0x04270be1` — same SRAM-PUF pattern family as test.233 Runs 1/3
  and test.236 Run B. Consistent post-reboot fingerprint.
- BAR0 timing was fast-UR (22 ms) at PRE; no signs of bus
  health issues before insmod.
- 13 dwell breadcrumbs is more than any prior wedged run across
  the entire investigation. Confirms the seed is doing something
  material.

### Artifacts

- `phase5/logs/test.237.run.txt` — truncated at `=== sleeping
  45s ===` (captured PRE sysctls, lspci, BAR0, modules, insmod
  exit)
- `phase5/logs/test.237.journalctl.full.txt` — 1419 lines, full
  boot -1 journal
- `phase5/logs/test.237.journalctl.txt` — 356 lines, filtered
  `BCM4360|brcmfmac` subset

---


## PRE-TEST.237 (2026-04-23 00:2x BST, boot 0 post-SMC-reset from test.236 Run B) — extended dwell ladder to t+30s with Apple random_seed present; bracket the actual wedge moment

### Hypothesis

Test.236 Run B demonstrated that writing the Apple-style random_seed
at TCM[0x9fe14..0x9ff1c) (magic 0xfeedc0de, length 0x100, 256-byte
random buffer) lets fw execute for ≥700 ms past set_active return —
a categorical shift from test.234, where zero post-set_active
breadcrumbs landed. But the **actual wedge moment is unknown**: we
only have a lower bound (t+700ms) and an untrusted upper bound from
the ~15-20 s journald tail-truncation folk figure.

**This test: extend the dwell ladder past t+10s to bracket the
wedge moment directly.** The new ladder adds breadcrumbs at
t=1.5s, 2s, 3s, 5s, 10s, 15s, 20s, 25s, 30s. Under ideal (no-wedge)
conditions, all 13 breadcrumbs land and the probe proceeds to
BM-clear + release + -ENODEV. Under a wedge at some t*, breadcrumbs
land up to the one emitted just before t* (minus any tail-truncation
window).

### Discriminator outcomes

| Last landed breadcrumb | Interpretation | Next |
|---|---|---|
| Full chain lands (t+30s done) + clean rmmod | Seed + extended wait BOTH stop the wedge — something in the 30 s window satisfies fw's expectation, or fw reaches a natural idle. Major positive. | Re-enable set_active + short dwells, confirm clean; then investigate what changed |
| t+30s done lands, but BM-clear/rmmod hang | Fw still wedges, but only after our 30 s dwell returns → wedge triggered by BM-clear or a post-return action, not by fw spinning | Shift wedge isolation to BM-clear / release path |
| Breadcrumb at t=[T1..T2] lands, next missing (e.g. t+15s lands, t+20s doesn't) | Wedge moment pinned to [T1, T2] window. Tail-truncation may hide ~T2 → T2+15s of additional breadcrumbs, but if T2 is >20s we can also hope for softlockup to fire on the driver thread mid-msleep. | Binary-search the window; decide whether to pivot to pcie_shared struct build |
| Cuts at t+700ms (same as Run B) regardless of extended dwells | "journald-flush-variance" counter-hypothesis NOT falsified. Seed may not genuinely have bought fw time — the 4 extra breadcrumbs from Run B may have landed due to flush dynamics. | Re-test with force_seed=0 + extended dwells. If cuts at same place, seed bought no time. If cuts at `BusMaster cleared`, journald-variance is weak. |
| Wedge earlier than t+700ms (e.g. cuts at `set_active returned TRUE`) | Run B was lucky; wedge timing is variable run-to-run | Need multiple runs; timing-based discrimination unreliable |

### Code change

1. New module param `bcm4360_test237_extended_dwells` (default 0).
2. In `brcmf_pcie_download_fw_nvram`'s set_active block, new
   `else if (bcm4360_test237_extended_dwells)` branch that replaces
   the short mdelay chain with:
   - mdelay chain for t+100..t+1000 (preserved for sub-second
     accuracy + per-dwell resolution)
   - msleep chain for t+1.5, 2, 3, 5, 10, 15, 20, 25, 30 s
     (msleep yields — avoids our thread pinning CPU + accidentally
     triggering softlockup without a fw wedge)
3. Existing test.234/235/236 paths preserved via the if/else-if chain:
   - skip_set_active=1 → test.235 path (no set_active)
   - test237_extended_dwells=1 → extended ladder
   - neither → test.234 short chain

### Run sequence (one run, this boot)

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test237_extended_dwells=1
# Wait >35s for the 30s dwell ladder + BM-clear/rmmod
sleep 45
# (host may already be wedged; if so, SMC reset required)
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

The harness script supports module args. Armed sysctls as usual
(nmi_watchdog=1, hardlockup_panic=1, softlockup_panic=1).

### Softlockup interaction

Kernel softlockup threshold is typically 20-22 s. With msleep
dwells (driver thread yields), softlockup from our *own* thread
is unlikely. But if the wedge stalls another CPU handling
interrupts or journald-flushing for >22 s, softlockup may fire
on THAT CPU → panic → pstore may capture a backtrace. This would
be a bonus observable beyond the breadcrumbs themselves.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~00:15 BST. `strings` confirms
the new `bcm4360_test237_extended_dwells` module param + 13 new
test.237 breadcrumbs (t+100..t+30000 ms + set_active call/TRUE/FALSE
lines). Pre-existing unused-variable warnings unchanged — no
regressions.

### Hardware state (boot 0, post-SMC-reset)

- Boot 0 started 2026-04-23 00:12:32 BST (post-SMC-reset reboot
  after test.236 Run B wedge).
- `lspci -vvv -s 03:00.0`: Control Mem+ BusMaster+, MAbort-, fast.
  Clean post-boot idiom.
- No modules loaded. Uptime ~few min.

### Expected artifacts

- `phase5/logs/test.237.run.txt` — PRE sysctls/lspci/BAR0 +
  harness output + POST lspci
- `phase5/logs/test.237.journalctl.full.txt` — boot 0 (or boot -1
  if host wedged) full journal
- `phase5/logs/test.237.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: **REBUILT CLEAN** above.
2. PCIe state: clean post-SMC-reset boot.
3. Hypothesis stated above.
4. Plan in this PRE block; will commit + push + sync before insmod.
5. Filesystem sync on commit.

---

## PRE-TEST.236 (2026-04-23 00:0x BST, boot 0 same as test.235) — force the upstream Apple-style random_seed write before `brcmf_chip_set_active`

### Hypothesis (NEW lead, found by code-reading after test.235)

Code review of `brcmf_pcie_download_fw_nvram` revealed two facts that
together make the random_seed write a strong candidate for the wedge
trigger:

1. **The live BCM4360 path returns `-ENODEV` at line 2887** (after fw
   download + dwell + tier probes + BM-clear). The post-return code at
   lines 2899-2959 — which contains the only `if (devinfo->otp.valid)`
   block that does the random_seed write — is **dead code on our
   path**. NVRAM is actually written earlier at lines ~2256-2287, and
   no random_seed write exists in the live path.

2. **Upstream gates the seed write on `devinfo->otp.valid`**, which
   is FALSE on our path because OTP read is bypassed (test.124, line
   ~5347-5355: `OTP read bypassed — OTP not needed`). Even if the
   dead code WERE reached, the seed write would still be skipped.

3. **The upstream comment is Apple-specific:** *"Some Apple chips/
   firmwares expect a buffer of random data to be present before
   NVRAM"*. BCM4360 in MacBookPro11,1 is an Apple board.

   Layout (computed for our 228-byte NVRAM, ramsize=0xa0000):
   - NVRAM: [0x9FF1C..0xA0000)  (228 B, ends at ramsize-0)
   - Seed footer (8 B, magic 0xfeedc0de + length 0x100): [0x9FF14..0x9FF1C)
   - Random bytes (256 B): [0x9FE14..0x9FF14)

   This means our test.234 zero range [0x9FE00..0x9FF1C) overlaps
   the *entire* seed area — fw, on every prior wedge run, has read
   either uninitialised SRAM-PUF garbage there (test.234) or zeros
   (would-be test.234-with-zeros via test.235 baseline). It has
   never seen the magic 0xfeedc0de footer that signals "random
   buffer present".

If fw conditionally:
- requires the seed (e.g. for crypto / WPA-key derivation),
- panics or stalls when the magic is absent,
- waits indefinitely on a DMA / mailbox handshake driven by seed,

…then providing it should change the post-set_active behaviour (no
wedge / wedge shifts later / different journald cutoff).

### Code change

1. New module param `bcm4360_test236_force_seed` (default 0).
2. In `brcmf_pcie_download_fw_nvram`, immediately after the existing
   live NVRAM write (post `post-NVRAM write done` log, before NVRAM
   marker readback): **if `force_seed`**:
   - Compute `footer_addr = address - sizeof(footer)` where `address
     = ramsize - nvram_len = 0x9FF1C`.
   - Write footer (length=0x100, magic=0xfeedc0de) via
     `brcmf_pcie_copy_mem_todev` (BCM4360-safe iowrite32 helper).
   - Write 256 random bytes at `footer_addr - 256` via the existing
     `brcmf_pcie_provide_random_bytes` (also routes through the safe
     copy helper).
   - Verify the footer landed by reading length and magic words back.
   - Log addresses, magic, lengths.
3. Wrap the existing test.234 zero block in
   `if (!bcm4360_test236_force_seed) { ... }` so it doesn't
   overwrite the seed when force_seed=1.

### Two-run protocol (per advisor; uses test.235's existing param)

**Run A — verify seed write is BCM4360-safe (no wedge expected):**
```bash
sudo insmod brcmfmac.ko \
     bcm4360_test235_skip_set_active=1 \
     bcm4360_test236_force_seed=1
sleep 5; sudo rmmod brcmfmac
```
Expected breadcrumbs:
- `test.236: writing random_seed footer at TCM[0x9ff14] magic=0xfeedc0de len=0x100`
- `test.236: writing random_seed buffer at TCM[0x9fe14] (256 bytes)`
- `test.236: seed footer readback length=0x00000100 magic=0xfeedc0de`
- existing test.235 SKIPPING + dwell-done lines

**Run B — same boot, test if seed prevents wedge:**
```bash
sudo rmmod brcmfmac_wcc; sudo rmmod brcmfmac
sudo insmod brcmfmac.ko \
     bcm4360_test235_skip_set_active=0 \
     bcm4360_test236_force_seed=1
sleep 15  # wedge-window
```
Per test.233 Run 2, TCM persists across the within-boot rmmod/insmod +
probe-start SBR, so the seed Run A wrote should still be in TCM when
Run B's set_active fires. (Run B re-writes it anyway via the same
code path, so this is belt-and-braces.)

### Decision tree

| Run A outcome | Run B outcome | Interpretation | Next |
|---|---|---|---|
| All breadcrumbs land, footer readback magic=0xfeedc0de | Wedge stops or breadcrumbs land further than test.231/234 | **Random_seed was the missing piece.** Major finding. | Restore conditional seed write properly (don't depend on otp.valid for BCM4360); progress to next blocker |
| All breadcrumbs land, footer readback magic=0xfeedc0de | Wedge identical to test.234 (cuts at "BusMaster cleared after chip_attach" or similar) | Seed not the missing piece (or not enough on its own). | Look at OTHER pieces in upstream pre-set_active path: shared-memory struct, ringinfo_addr, mailbox; or revisit OTP bypass |
| All breadcrumbs land, but readback wrong magic (e.g. 0x00000000) | n/a | TCM write to that range failed / wrong addr math. | Fix address calc or write helper |
| Wedge in Run A | n/a | Seed write itself wedges — surprising; copy_mem_todev should be safe | Investigate copy_mem_todev path or addr |

### Expected artifacts

- `phase5/logs/test.236.runA.run.txt` + journals (no wedge expected)
- `phase5/logs/test.236.runB.run.txt` + journals (wedge possible)

### Hardware state

- Boot 0 (started 2026-04-22 23:41:20 BST), still alive after test.235.
- `lspci -vvv -s 03:00.0`: Mem+ BusMaster-, MAbort-, fast-UR (post test.235 rmmod).
- No modules loaded.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~00:0x BST. `strings` confirms 3
test.236 breadcrumbs + `bcm4360_test236_force_seed` module param.
Existing test.235 param retained. Pre-existing unused-variable
warnings unchanged.

### Pre-test checklist (CLAUDE.md)

1. Build status: REBUILT CLEAN above.
2. PCIe state: clean post test.235.
3. Hypothesis stated above.
4. Plan in this PRE block; will commit + push before insmod.
5. Filesystem sync on commit.

---


## POST-TEST.236 (2026-04-23 00:06 BST, boot -1 after SMC reset) — random_seed write SHIFTS the wedge later; fw reaches ≥t+700ms post-set_active

### Summary moved into "Current state" header above. This block holds
### the full evidence table, reasoning, and Run-B journald tail.

### Run A (skip_set_active=1, force_seed=1) — seed-write mechanism verified clean

Clean run, no wedge. Seed breadcrumbs in journal (00:05:52 BST):

```
test.236: writing random_seed footer at TCM[0x9ff14] magic=0xfeedc0de len=0x100
test.236: writing random_seed buffer at TCM[0x9fe14] (256 bytes)
test.236: seed footer readback length=0x00000100 magic=0xfeedc0de (expect 0x00000100 / 0xfeedc0de)
```

Readback matched expected values → TCM writes to [0x9fe14..0x9ff1c)
via `brcmf_pcie_copy_mem_todev` are byte-accurate. Probe then hit the
test.235 SKIPPING path, 1000 ms dwell, BM-clear, -ENODEV, clean rmmod
(run.txt truncated at fw-download chunk 36/108 due to 5 s sleep
expiring mid-download; journal has full flow through
`post-NVRAM write done`). **Seed write is BCM4360-safe.**

### Run B (skip_set_active=0, force_seed=1) — WEDGE, but ~15 s later than test.234

Host wedged, SMC reset required to recover (user did this between
Run B and this session). Run B journal (boot -1) did flush
significantly further than test.234's boot:

| Boot | Last breadcrumb landed | Position in probe |
|---|---|---|
| test.234 (boot -2 of this history) | `test.158: BusMaster cleared after chip_attach` | **before** fw download |
| test.236 Run B (boot -1) | `test.234: t+700ms dwell` | **after** set_active returned TRUE, 700 ms in |

That's a categorically different cutoff — test.234 didn't survive to
print fw-download, NVRAM write, pre-release snapshot, set_active,
or any dwell. Run B printed **all** of them plus four post-set_active
dwell breadcrumbs.

### Run B — full post-set_active tail (from `journalctl -b -1`)

```
Apr 23 00:07:18 test.236: writing random_seed footer at TCM[0x9ff14] magic=0xfeedc0de len=0x100
Apr 23 00:07:18 test.236: writing random_seed buffer at TCM[0x9fe14] (256 bytes)
Apr 23 00:07:18 test.236: seed footer readback length=0x00000100 magic=0xfeedc0de
Apr 23 00:07:18 test.234: calling brcmf_chip_set_active resetintr=0xb80ef000 (after zero-upper-TCM)
Apr 23 00:07:18 test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006 (BusMaster preserved)
Apr 23 00:07:18 test.234: brcmf_chip_set_active returned TRUE
Apr 23 00:07:18 test.234: t+100ms dwell
Apr 23 00:07:18 test.234: t+300ms dwell
Apr 23 00:07:19 test.234: t+500ms dwell
Apr 23 00:07:19 test.234: t+700ms dwell
<journal ends — host wedged>
```

Missing from this tail: `t+1000ms dwell`, `dwell done`, any BM-clear,
any -ENODEV. So fw ran ≥700 ms under the seed, and the wedge hit
between t+700ms and t+1000ms — OR later, with tail-truncation (15-20 s)
wiping only the final window. Either way, the wedge is **not** in
the pre-set_active path that killed test.234's journal flush.

### Interpretation — "seed was a missing piece, but not the only one"

1. **Falsified:** "fw wedges because seed area contains SRAM garbage at
   set_active time." With valid seed present, fw demonstrably runs
   further (≥700 ms, breadcrumbs prove CPU+bus still healthy).
2. **Not (yet) falsified:** "fw wedges because it subsequently reaches
   another uninitialised shared-memory address (ringinfo / console /
   shared struct)." Consistent with both the timing and the upstream
   brcmfmac flow which sets up additional structures around the time
   seed lands.
3. **Known confound:** "wedge-moment unchanged, but more of the log
   got flushed this time because the CPU froze slower." Weakened by
   the fact that dwell breadcrumbs require the code path actually to
   execute — if fw wedged at the same moment as test.234, the CPU
   wouldn't have called the 300/500/700-ms msleep() chain at all.
   Still worth discriminating cheaply before major work.

### Pre-zero TCM snapshot under seed write (belt-and-braces check)

Run B's pre-set-active TCM[0x90000] read was `0xa42709e1` — same
SRAM-PUF pattern observed in test.233 Runs 1 & 3. So the chip's
non-seed TCM area still contains its fingerprint pattern going
into set_active, unchanged by our test.234/235 zero range.

### Hardware state (now)

Current boot: boot 0, started 2026-04-23 00:12:32 BST (post-SMC-reset
reboot). `lspci -vvv -s 03:00.0` on 03:00.0: Mem+ BusMaster+, MAbort-,
fast. No modules loaded, uptime ~2 min. Ready for test.237.

### Artifacts

- `phase5/logs/test.236.runA.run.txt` (153 lines — truncated by
  script-sleep, fine; journal has full flow)
- `phase5/logs/test.236.runA.journalctl.txt` (filtered)
- `phase5/logs/test.236.runA.journalctl.full.txt` (1852 lines)
- `phase5/logs/test.236.runB.run.txt` (20 lines — insmod + sleep, then
  wedged before any post-test capture)

Run B journal is **in `journalctl -b -1`** (boot -1 of current live
session). Tail visible above.

---

## POST-TEST.235 (2026-04-22 23:53 BST, boot 0) — cheap-tier zero of [0x9FE00..0x9FF1C) does NOT prevent wedge

Summary: 71/71 dwords non-zero pre-zero (SRAM-PUF-style random data);
0/71 non-zero post-zero (zero loop works); SKIPPING set_active per
`bcm4360_test235_skip_set_active=1`; Clean BM-clear / -ENODEV / rmmod,
host alive. Combined with test.234 wedge → cheap-tier failed for this
region. Code-reading then identified the random_seed write as the
next candidate (see test.236).

---


## PRE-TEST.235 (2026-04-23 00:xx BST, post-SMC-reset boot from test.234 wedge) — observable run of test.234's zero+verify, set_active SKIPPED (test.230 baseline + module param)

### Hypothesis

Test.234 wedged in the journald-blackout window — none of its
breadcrumbs landed. The minimum next step is to run the exact same
zero+verify code without calling set_active (test.230 baseline).
Then all journald logs will land: pre-zero scan reveals what 71
dwords in [0x9FE00..0x9FF1C) actually contain on a fresh boot;
verify pass count confirms zero writes landed; combined with
test.234's wedge, by elimination the wedge was in the set_active
path even with the region zeroed.

### Code change

Added `bcm4360_test235_skip_set_active` module param and an if/else
in the test.234 block — when set, emit `SKIPPING` line + 1000 ms
dwell + dwell-done line, else run original test.234 path.

### Expected artifacts

- `phase5/logs/test.235.run.txt`
- `phase5/logs/test.235.journalctl.full.txt`
- `phase5/logs/test.235.journalctl.txt`

### Hardware state (post-SMC-reset boot 0, started 2026-04-22 23:41:20 BST)

Mem+ BusMaster+, MAbort-, CommClk+, LnkSta 2.5GT/s x1, clean.
No modules loaded; BAR0 timing fast-UR (22 ms) at boot start.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-22 ~23:50 BST. `strings` confirmed
new module param + 2 test.235 breadcrumbs.

---


## PRE-TEST.234 (2026-04-23 00:xx BST, post-SMC-reset boot from test.233 Run 3) — zero TCM[0x9FE00..0x9FF1C] before `brcmf_chip_set_active`; cheapest-tier shared-memory-struct probe

### Hypothesis

The wedge triggered by `brcmf_chip_set_active` is caused, at least
in part, by firmware reading *something* in the upper TCM region
(between the end of the firmware image at 0x6BF78 and the NVRAM
slot at 0x9FF1C) during its boot phase and using that value as a
DMA target / pointer. On a post-SMC-reset boot, that region contains
a deterministic SRAM fingerprint (test.233 Runs 1 & 3 showed non-
zero, nearly-identical bytes at 0x90000 despite our code never
writing there). Fw dereferences the fingerprint as if it were a
host address, PCIe TLP to that bogus address never completes (or
the root complex UR-responds), fw enters a state that freezes the
bus host-wide within ~1 s.

This is the **cheapest-tier** experiment of the staged plan the
advisor laid out before test.234:
- **Cheap (this test):** zero the suspect region, re-enable
  set_active. If fw now DMAs to a NULL address instead of a
  fingerprint-derived one, behavior may change (NULL is often
  DMA-rejected cleanly at root complex; garbage is not).
- **Medium (test.235 if cheap fails):** write sentinel pointers
  into TCM itself (no host DMA alloc) at suspect offsets.
- **Expensive (test.236 if medium fails):** real DMA-coherent
  allocations + TCM pointer fixups.

### Region chosen — 0x9FE00..0x9FF1C (284 bytes, 71 dwords)

- Above the firmware image (ends at 0x6BF78) — not part of fw code.
- Below the NVRAM slot (starts at 0x9FF1C) — not touched by NVRAM write.
- Below the ramsize-4 marker (0x9FFFC) — not touched by NVRAM marker write.
- Matches the traditional upper-TCM position where brcmfmac-style
  shared-memory structs often live on other chips.

Our code never writes to this region during the probe path, so on
a post-SMC-reset boot it contains whatever the SRAM powers up as
(the fingerprint). Zeroing it is the cheapest way to test whether
its contents are load-bearing for fw boot.

### Code change

In `brcmf_pcie_download_fw_nvram`, replace the test.233 block
(write magic + SKIPPING set_active) with test.234:

1. **Pre-zero scan**: read all 71 dwords in [0x9FE00..0x9FF1C),
   log any non-zero cells as `pre-zero TCM[0x%05x]=0x%08x`, and
   emit a summary count.
2. **Zero loop**: write 0 to each of the 71 dwords.
3. **Verify pass**: re-read, count non-zero cells, log summary
   `zero verify N/71 non-zero` (expect 0/71).
4. **Restore `brcmf_chip_set_active`**: call it with the resetintr
   derived from the first 4 fw bytes (as test.231/232 did). Log
   before the call; log the boolean return.
5. **Post-set_active dwells**: five breadcrumbs at t=100, 300, 500,
   700, 1000 ms after set_active returns, then "dwell done".
6. **BM-clear + release + -ENODEV** (unchanged).

Keep the test.231 pci_set_master restore from test.233 (BM=ON
going into set_active — test.230 baseline).

### Decision tree

| Outcome signature | Interpretation | Next (test.235) |
|---|---|---|
| Full clean run: set_active returns, all 5 dwells + dwell-done land, BM-clear, -ENODEV, rmmod clean, host alive ≥30 s | **Zeroing the region stopped the wedge.** Fw was dereferencing fingerprint as a DMA target. Major finding. | Narrow down which specific dword inside the region matters — binary-search with smaller zero ranges, then design real shared-memory struct. |
| Wedge occurs but tail-truncation lands **more** breadcrumbs than test.231/232 (e.g. "set_active returned" visible, or t=100ms dwell lands) | **Wedge shifted later** — zeroing bought time. Fw still hitting another bad region or reaches further before hanging. | Widen the zero range (0x70000..0x9FF1C, ~195 KB) in test.235 to cover all possible shared-memory locations. |
| Wedge occurs, tail-truncation at same point as test.231/232 (before any post-set_active breadcrumb) | **Region didn't matter** — theory wrong or fw reads elsewhere. | Try different regions: fw image upper bits (0x6C000..0x9FE00), or fw-written regions (maybe fw re-reads a spot in its own image as a pointer seed). |
| Wedge at earlier point (before set_active) — e.g. zeroing itself wedges the host | Unexpected — TCM-write should be safe (test.225 wrote 442 KB cleanly). Indicates either a wild hazard in the region or a bug in the zero loop. | Re-read journal for latest breadcrumb; consider 4-byte-at-a-time vs loop bug. |

### Expected artifacts

- `phase5/logs/test.234.run.txt` — PRE sysctls + lspci + BAR0 + pstore + strings + harness output.
- `phase5/logs/test.234.journalctl.full.txt` — boot -1 or boot 0 journal.
- `phase5/logs/test.234.journalctl.txt` — filtered subset (test.234 breadcrumbs only).
- PRE/POST lspci captures.

### Hardware state (post-SMC-reset boot, carries over from test.233 Run 3)

- Boot 0 started at 2026-04-22 ~22:3x BST (after user did SMC reset +
  reboot between Runs 2 and 3 of test.233).
- `lspci -vvv -s 03:00.0` at 23:xx: Control `Mem+ BusMaster-` (clean
  rmmod idiom after Run 3), Status MAbort- (clean), DevSta AuxPwr+
  TransPend-, LnkCtl ASPM L0s L1 Enabled CommClk+, LnkSta 2.5GT/s
  x1. No dirty signature.
- pstore empty. No modules loaded.

### Build status — REBUILT CLEAN (2026-04-22 23:09 BST)

`brcmfmac.ko` 14259504 bytes, mtime 23:09. `strings` confirms 14
test.234 breadcrumbs present (PRE-ZERO scan header, per-cell pre-
zero non-zero reporter, pre-zero summary, zeroing header, VERIFY-
FAIL reporter, zero verify summary, set_active call header, set_
active TRUE/FALSE return lines, five dwell breadcrumbs t+100..
t+1000ms). The pre-existing `test.233: PRE-READ TCM[0x90000]=…`
at function entry is retained as a continuity diagnostic (same
fingerprint check as test.233 Runs 1 & 3).

Build warnings are all pre-existing unused-variable warnings for
stale helpers (`dwell_increments_ms`, `dwell_labels_ms`, `dump_
ranges`, `brcmf_pcie_write_ram32`) from earlier test iterations —
not regressions.

### Logging / watchdog arming

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

### Pre-test checklist (CLAUDE.md)

1. Build status: **PENDING** (code change in progress; will rebuild before test).
2. PCIe state: will capture + verify no dirty state (MAbort+, CommClk-) before insmod.
3. Hypothesis stated: above.
4. Plan written to RESUME_NOTES.md: this block.
5. Filesystem synced on commit.

---


## POST-TEST.233 (2026-04-22 22:41 BST, 3 runs across 2 boots) — SMC reset wipes our TCM magic; TCM ring-buffer logger RULED OUT

### Headline

All 3 runs completed cleanly (test.230 baseline, no wedge). Writes
verified each time (post-write readback = 0xDEADBEEF/0xCAFEBABE).
The critical evidence is the **pre-read** values at probe entry:

| Run | Boot | Timestamp | Pre-read TCM[0x90000] | Pre-read TCM[0x90004] |
|---|---|---|---|---|
| 1 | boot -1 first insmod (fresh post-SMC-reset) | 22:25:50 | 0x842709e1 | 0x90dd4512 |
| 2 | boot -1 second insmod (same boot) | 22:26:52 | **0xDEADBEEF** | **0xCAFEBABE** |
| 3 | boot 0 first insmod (post-SMC-reset + reboot) | 22:40:xx | 0x842709e1 | 0xb0dd4512 |

### Interpretation

**Run 2 = MATCH (magic preserved within a boot):** TCM retains
writes across a full driver-module cycle including the probe-start
Secondary Bus Reset via bridge. Useful bank: within a single boot,
if a wedge leaves the host recoverable without SMC reset, the TCM
can carry data across the reload.

**Run 3 ≠ magic (magic wiped across SMC reset):** Our 0xDEADBEEF/
0xCAFEBABE is gone; the pre-read reverted to a value very close to
Run 1's fresh-boot baseline (first word byte-identical, second word
off by one bit in the high byte). SMC reset + reboot either cut
power to the SRAM, or the brcmfmac re-init on a fresh boot traverses
more initialization than the within-boot cycle does.

**The Run 1 / Run 3 non-zero pre-reads are themselves interesting.**
Offset 0x90000 is past the 442 KB fw image (ends at 0x6bf78) and
before the 228 B NVRAM slot (0x9ff1c). Our code never writes there
in the normal flow, yet we see specific non-zero bytes consistent
across SMC resets with only a single-bit difference. Likely
candidates:
- BCM4360 SRAM power-on fingerprint (SRAM cells settling to
  deterministic-but-instance-specific values; known PUF-adjacent
  property).
- Some early-probe routine (CR4 halt / buscore_reset / bridge
  SBR) writes a pattern here as a side effect.
Not worth chasing now; the binary answer (SMC reset wipes our
magic) is what matters.

### Binary conclusion: TCM ring-buffer logger NOT viable

Every wedge in this investigation (tests 226, 227, 228, 229, 231,
232) has required an SMC reset to recover the host. Since SMC reset
wipes our TCM magic, a TCM-resident ring-buffer logger cannot
survive the recovery path we actually use. Ruled out.

Caveat: if a future wedge were ever host-recoverable without SMC
reset (e.g. driver hang that doesn't freeze the watchdog), the
logger could still help for that narrow case. Not worth building
speculatively.

### Pivot — test.234 plan (per PRE decision tree, "all pre-reads → 0/garbage" branch landed)

Primary direction: **build a minimal shared-memory struct in TCM
before `brcmf_chip_set_active`**, per upstream brcmfmac
`brcmf_pcie_init_share` pattern. Two payoffs:

1. **Diagnostic:** If the wedge stops, we've located the missing
   piece fw was dereferencing. If timing/signature shifts, we have
   a new observable.
2. **Forward step:** Valid shared-memory infrastructure is part of
   the eventual correct driver path anyway — progress on the
   reverse-engineering goal regardless of the wedge outcome.

Advisor previously flagged this as potentially simpler/cheaper than
building a full logger — and we have no logger alternative left.

### Evidence summary / artifacts

- `phase5/logs/test.233.runs12.journal.txt` — 697 lines covering
  runs 1-2 (already committed in f203c0b).
- `phase5/logs/test.233.run3.journal.txt` — 349 lines, boot 0
  post-SMC-reset journal with Run 3.
- `phase5/logs/test.9, test.10, test.12` — harness dmesg captures.
- All 3 runs: clean writes (post-write readback matched magic every
  time), clean -ENODEV, clean rmmod. test.230 baseline held.
- No wedges. No SMC reset required for any test.233 run — only the
  one between run 2 and run 3 that the test design asked for.

### Hardware state (post-Run-3 rmmod, 22:41 BST)

- `lspci -vvv -s 03:00.0` — Control `Mem+ BusMaster-` (kernel
  reverted after rmmod), MAbort-, DevSta would still show sticky
  UR+ but no new dirty signature.
- No modules loaded, no pstore dumps.
- Host is ready for test.234 (code development, no hardware test
  needed for initial implementation read-through).

---


## PRE-TEST.233 (2026-04-22 22:25 BST, fresh SMC-reset boot) — TCM persistence probe: does SMC reset wipe TCM?

### Hypothesis

We don't know whether TCM (chip's internal SRAM, mapped via BAR2)
survives an SMC reset. The answer determines whether the TCM ring-
buffer logger (our strongest remaining wedge-timing transport) is
viable at all. Design: write a magic pattern to a known-safe TCM
offset on one run, read it back on a later run, and log survival.

### Design — 3 runs across 1 SMC reset

Each run uses the test.230 baseline probe path (FORCEHT ✓,
pci_set_master ✓, **`brcmf_chip_set_active` SKIPPED**). No wedge
risk in any run — this exact path ran cleanly end-to-end in
test.230. Probe writes a magic pattern to TCM[0x90000] /
TCM[0x90004] as late as possible in the probe, then dwells
1000 ms, then does clean BM-clear + release → -ENODEV. Driver
rmmods cleanly.

Offset 0x90000 is past the 442 KB firmware image (last fw byte at
0x6bf78) and before the NVRAM slot (0x9ff1c), so it's untouched
by the normal fw/NVRAM writes.

| Run | Context | Pre-read expected (if TCM preserved) | Pre-read expected (if wiped) |
|---|---|---|---|
| 1 | fresh SMC-reset boot, first insmod | 0 / garbage (baseline — no prior write) | 0 / garbage (same) |
| 2 | same boot, second insmod after rmmod | 0xDEADBEEF / 0xCAFEBABE | 0 / garbage → probe-start SBR wipes TCM |
| 3 | after SMC reset + reboot, first insmod | 0xDEADBEEF / 0xCAFEBABE | 0 / garbage → SMC reset wipes TCM |

Run 2 is a bonus: tells us whether the driver's own probe-start
SBR (via bridge) wipes TCM. If SBR itself wipes, cross-boot
persistence via the driver path is impossible.

### Code change

`drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` in
`brcmf_pcie_download_fw_nvram`:

1. **Restored** test.232's SKIP of `pci_set_master` → `pci_set_master`
   called as in test.230 baseline. No functional difference with
   set_active skipped, but matches a proven-clean path.
2. **Added pre-read** (near function entry, after the BAR2 probe):
   reads TCM[0x90000] and [0x90004], logs as
   `test.233: PRE-READ TCM[0x90000]=... TCM[0x90004]=...`.
3. **Added write + verify + skip-set_active** (where the
   brcmf_chip_set_active call used to be, replacing test.231's 10
   timing dwells): writes 0xDEADBEEF to TCM[0x90000] and
   0xCAFEBABE to TCM[0x90004], logs, reads back, logs. Then a
   `test.233: SKIPPING brcmf_chip_set_active` marker, 1000 ms
   dwell, `dwell done` marker.

All other test.230 breadcrumbs (fw download, TCM verify, NVRAM
write, pre-release snapshots, FORCEHT, pci_set_master, BM-clear,
-ENODEV return) retained.

### Build status — REBUILT CLEAN (2026-04-22 22:23 BST)

`brcmfmac.ko` 14249552 bytes. `strings` confirms 5 test.233
breadcrumbs present and 0 test.232 leftovers:
- `test.233: PRE-READ TCM[0x90000]=0x%08x TCM[0x90004]=0x%08x ...`
- `test.233: writing magic TCM[0x90000]=0xDEADBEEF TCM[0x90004]=0xCAFEBABE`
- `test.233: POST-WRITE readback TCM[0x90000]=0x%08x ... (expect DEADBEEF/CAFEBABE)`
- `test.233: SKIPPING brcmf_chip_set_active ...`
- `test.233: 1000 ms dwell done ...`

### Hardware state (post-SMC-reset boot at ~21:54 BST, user did SMC reset)

- Boot 0 started 2026-04-22 21:54:48 BST (following test.232 wedge
  reboot + user SMC reset).
- `lspci -vvv -s 03:00.0`: Control `Mem+ BusMaster+`, Status
  MAbort- (clean), DevSta CorrErr+ UnsupReq+ (sticky) AuxPwr+
  TransPend-, LnkCtl ASPM L0s L1 Enabled CommClk+, LnkSta 2.5GT/s
  x1. Matches post-SMC-reset idiom from prior tests.
- No modules loaded. pstore empty.

### Run sequence (this PRE entry covers all 3 runs; POST will
summarize outcomes)

```bash
# Run 1: fresh SMC-reset boot — captures baseline TCM state
sudo phase5/work/test-brcmfmac.sh   # (or insmod equivalent)
sudo rmmod brcmfmac_wcc brcmfmac brcmutil

# Run 2: same boot, tests probe-SBR persistence
sudo phase5/work/test-brcmfmac.sh
sudo rmmod brcmfmac_wcc brcmfmac brcmutil

# >>> Intermission: user SMC-resets host. Reboot. <<<

# Run 3: post-SMC-reset boot — tests SMC-reset persistence
sudo phase5/work/test-brcmfmac.sh
sudo rmmod brcmfmac_wcc brcmfmac brcmutil
```

The harness test-brcmfmac.sh already arms NMI watchdog / panic
sysctls + captures run artifacts. Each run's journal is read
live (no wedge expected).

### Decision tree

| Run 2 pre-read | Run 3 pre-read | Interpretation | Next |
|---|---|---|---|
| magic | magic | **TCM survives everything** (SBR + SMC reset). Logger fully viable. | Build TCM ring-buffer logger |
| magic | 0/garbage | TCM survives SBR within boot, wiped by SMC reset. Logger only helps if host survives without SMC reset (rare). | Investigate alt transports or proceed to shared-memory struct implementation |
| 0/garbage | (any) | Probe-start SBR wipes TCM. Logger cannot use driver-probe path to seed state cross-boot. | Shared-memory-struct forward step, or alternative reset path |
| 0/garbage | magic | Contradictory — SBR wipes but SMC reset preserves? Unlikely; re-investigate. | Rerun runs 1-2 to confirm baseline |

### Logging / watchdog arming

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

No wedge expected — test.230 baseline. If a wedge somehow occurs,
the test design catches it the same way test.230 would (BM-clear
+ -ENODEV or visible hang).

### Expected artifacts

- `phase5/logs/test.233.run1.journal.txt` — current-boot journal after run 1
- `phase5/logs/test.233.run2.journal.txt` — current-boot journal after run 2 (both runs visible)
- `phase5/logs/test.233.run3.journal.txt` — boot -1 or boot 0 journal after run 3 (depending on whether host survived; expected survive)
- PRE/POST lspci captures for each run
---


## POST-TEST.232 (2026-04-22 21:52 BST, boot -1 journal captured) — BM=OFF did NOT prevent wedge; DMA-completion-waiting theory falsified

### Headline

Host wedged as in test.231, required reboot. Boot -1 journal tail-
truncated at `wide-TCM[0x2c000] pre-release snapshot` (21:52:52).
None of the test.232-specific breadcrumbs (`SKIPPING pci_set_master`,
`post-skip PCI_COMMAND`, `post-skip MMIO guard`) landed, nor did
anything from `past pre-release snapshot` onward — INTERNAL_MEM
probe, pre-set-active probes, BusMaster dance, FORCEHT, set_active,
dwells, BM-clear, release were all lost to tail-truncation. But the
binary discriminator still resolves: the same flow ran cleanly end-
to-end in test.230 (set_active skipped), so the only runtime-
different actor between the last landed log and the wedge is
`brcmf_chip_set_active`, which is back on in test.232. BM=OFF did
not neutralize it.

### Inference

**Plain DMA-completion-waiting theory is falsified.** With BM=OFF,
any DMA TLP the device tries to issue gets UR-responded by the root
complex (device is not bus master), so fw does not stall waiting
for a completion that never lands. The host wedged anyway. Therefore
the bus-stall mechanism is not pure completion-starvation.

**Still potentially DMA-rooted:** fw's response to receiving a UR
for its DMA TLP could itself be bus-hostile — AXI-side faults,
retry storms against a dead rc path, internal pcie2 core being
brought down, etc. We cannot yet distinguish those from a fully
non-DMA mechanism (e.g. fw wedges an internal register or induces
a link downtrain on its own initiative).

**Phrase carefully going forward:** "not waiting-for-completion-of-
missing-target", not "not DMA-related".

### Evidence (boot -1 journal, 1297 lines)

- Full probe path landed through test.225 chunk writes (107 chunks,
  all 110558 words, tail byte written).
- fw write complete + post-fw msleep(100) + NVRAM write (228 bytes).
- Pre-release TCM snapshots started landing: `TCM[0x0000..0x001c]`
  (resetintr + 7 x 4B neighbors), `wide-TCM[0x00000..0x2c000]`
  (12 x 16-KB-spaced samples). Last landed line:
  `wide-TCM[0x2c000]=0xf0084643 (pre-release snapshot)` at 21:52:52.
- Expected-but-not-landed: `wide-TCM[0x30000..]`, `tail-TCM`, fw
  samples, `CC-*` backplane snapshot, `test.226: past pre-release
  snapshot — entering INTERNAL_MEM lookup`, and everything after.
- No NMI watchdog / softlockup / hardlockup messages in boot -1
  (bus-wide stall froze watchdog CPU too, same signature as 227/228/229/231).
- Boot -1 ended at 21:52:52; host rebooted at 21:54:48 (user-initiated
  or auto-panic unclear; panic=30 was armed).

### Hardware state after reboot (NO SMC reset done per user)

- `lspci -vvv -s 03:00.0` — Control `Mem+ BusMaster+` (kernel default),
  Status MAbort- (clean), DevSta CorrErr+ UnsupReq+ (sticky, same as
  post-SMC-reset state in tests 230/231/232 PRE), AuxPwr+ TransPend-,
  LnkCtl ASPM L0s L1 Enabled CommClk+, LnkSta 2.5GT/s x1. No dirty
  signature visible from the host side.
- pstore empty.
- No brcmfmac modules loaded.
- Caveat: chip's internal state (CR4, fw) may still be partially
  active from the test.232 set_active — only an SMC reset clears
  that definitively.

### Artifacts captured

- `phase5/logs/test.232.run.txt` — PRE sysctls + lspci + BAR0 + pstore
  + strings + truncated harness ("Modules loaded. Waiting 15s…").
- `phase5/logs/test.232.journalctl.full.txt` — 1297 lines boot -1.
- `phase5/logs/test.232.journalctl.txt` — 275 lines filtered.
- No pstore dump.

### Blockers before test.233 (per advisor)

1. **Ask user: does SMC reset wipe TCM?** Determines TCM-ring-buffer
   logger viability. Answer this before designing the logger.
2. **Request SMC reset before next hardware test.** User flagged "SMC
   reset NOT done" — treat as a prompt to do one, not permission to
   skip. Chip may still have fw partially active in CR4.
3. Cheap rule-out done: `/dev/ttyS0..3` exist but no physical serial
   on this MacBook (cmdline has no earlyprintk=). Serial likely dead
   end unless user has USB-serial adapter.

### Direction (pending user answers)

Leading candidate regardless of logging decision: **implement a
minimal shared-memory struct in TCM before set_active** (per upstream
brcmfmac `brcmf_pcie_init_share`). Two bonuses:
- It's the natural forward step the DMA-target-missing theory implied.
- If the wedge stops, we've found the piece. If the wedge shifts in
  timing or signature, we have a new observable.
- Advisor suggests this may double as a cheaper discriminator than a
  full TCM ring-buffer logger.

---

## PRE-TEST.232 (2026-04-22 21:49 BST, boot 0 post-SMC-reset) — skip `pci_set_master` before set_active; binary discriminator for DMA-target-missing hypothesis

### Hypothesis

Wedge is caused by firmware issuing DMA to unpopulated shared-memory
rings in TCM. Those ring structs are zero/garbage; fw dereferences a
NULL/garbage host address; PCIe TLPs stall waiting for completions
that never land; bus-wide freeze within ~1 s.

If this is correct, setting BM=OFF before set_active should make
device-side DMA fail-fast at the root complex (which refuses TLPs
from a bus-master-off device). Firmware may stall internally but the
host bus should stay healthy.

### Why this, not more logging

Advisor pivot (bisect was uninformative — see POST-TEST.231). Testing
"why" with a candidate theory gives a binary result either way;
refining "when" requires durable logging we haven't built. If BM=OFF
fails to survive, *then* the TCM-logger investment is justified.

### Code change

In `brcmf_pcie_download_fw_nvram` (pcie.c:2416-2449 block), replaced
the `pci_set_master` call + surrounding breadcrumbs with a `test.232:
SKIPPING pci_set_master — BM stays OFF into set_active` marker. The
PCI_COMMAND read-back and MMIO guard remain so we can verify BM=OFF
is still in effect going into set_active. Everything else — FORCEHT,
fw download, TCM verify, set_active, 10 dwell breadcrumbs, BM-clear,
release — is identical to test.231.

### Build status — REBUILT CLEAN (2026-04-22 21:49 BST)

`brcmfmac.ko` 14250696 bytes, mtime 21:49. `strings` confirms:
- `BCM4360 test.232: SKIPPING pci_set_master`
- `BCM4360 test.232: post-skip PCI_COMMAND=0x%04x BM=%s (expect OFF)`
- `BCM4360 test.232: post-skip MMIO guard mailboxint=0x%08x (endpoint still responsive)`

### Decision tree

| Outcome signature | Interpretation | Next (test.233) |
|---|---|---|
| All 10 dwell breadcrumbs (t=10..1000ms) + set_active returned true + -ENODEV + rmmod works + host stays alive | **DMA-target-missing confirmed.** Wedge-trigger neutralized with BM=OFF. | Investigate upstream `brcmf_pcie_init_share` and build a minimal shared-memory struct in TCM so fw can progress with BM=ON. |
| Set_active returns true in journal but dwell breadcrumbs truncate, host wedges | Wedge happens even without BM. Theory wrong or partial — fw is doing something other than plain DMA that hangs the bus. | Pivot to TCM ring-buffer logger to recover timing, or try earlyprintk=serial. |
| Set_active returns false, or earlier breadcrumb missing, or new regression | Unexpected interaction between BM=OFF and set_active path itself (e.g. fw init requires BM to even initialize). | Re-read journal for latest breadcrumb; consider whether BM-off breaks something earlier. |

### Hardware state (post-SMC-reset boot at 21:36 BST)

- `lspci -vvv -s 03:00.0` at 21:49 BST: Control `Mem+ BusMaster+`
  (kernel default, brcmfmac will reset), Status MAbort- (clean), DevSta
  CorrErr+ UnsupReq+ (sticky from earlier) TransPend-, LnkCtl ASPM
  Enabled CommClk+ (post-SMC-reset idiom matches test.230 PRE), LnkSta
  2.5GT/s x1. No dirty-state signature — safe to proceed.

### Logging / watchdog arming (same as test.231)

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

### Expected artifacts

- `phase5/logs/test.232.run.txt` — PRE sysctls + lspci + BAR0 timing + pstore + strings + harness output.
- `phase5/logs/test.232.journalctl.full.txt` — boot 0 or boot -1 journal.
- `phase5/logs/test.232.journalctl.txt` — filtered subset.

### Pre-test checklist (CLAUDE.md)

1. Build status: **REBUILT CLEAN** (21:49 BST)
2. PCIe state: will capture + verify no dirty state (MAbort+, CommClk-) before insmod
3. Hypothesis stated: above
4. Plan written to RESUME_NOTES.md: this block
5. Filesystem synced on commit

---

## POST-TEST.231 (2026-04-22 21:34 BST, boot -1 → SMC reset → boot 0) — journal tail-truncation swamped the bisect; no timing info recovered

### Headline

Host wedged as expected once `brcmf_chip_set_active` was re-enabled. SMC
reset required. Boot -1 journal tail-truncated to `test.158: about to
pci_clear_master (config-space write)` at 21:34:40 — a full ~15–20 s
(and ~10 code-path blocks) BEFORE the set_active call that was
supposed to reveal timing. All 10 timing breadcrumbs
(t=10/50/100/200/300/500/700/900/1000 ms plus dwell-done) were lost.
No new information about wedge timing.

### Why this is tail-truncation, not a new regression

Test.230's journal captured the exact same `about to pci_clear_master`
breadcrumb at line 1118, then continued cleanly through ASPM disable,
full fw download, TCM verify, set_active-skip, 1000 ms dwell, BM
clear, release_firmware, and -ENODEV return (line 1413, 21:24:57).
So this breadcrumb is NOT a wedge point — it just happens to be where
journald's last-flushed entry landed for test.231. This matches the
tail-truncation pattern first confirmed in tests 226/227 (host loses
userspace → journald drops the tail that was in the kernel ring
buffer but not yet persisted).

### Truncation budget exceeded the bisect window

The wedge window under investigation was ≤1 s (10 ms – 1000 ms after
set_active). Based on test.231 compared to test.230, journald lost at
least ~15 seconds of tail (the gap between `pci_clear_master` and the
expected dwell breadcrumbs). That's one to two orders of magnitude
larger than the measurement interval. Journald is structurally unable
to resolve this wedge window.

### Artifacts captured

- `phase5/logs/test.231.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore (empty) + strings. Harness output ends at "Modules
  loaded. Waiting 15s…" (script killed by wedge).
- `phase5/logs/test.231.journalctl.full.txt` — 1472 lines boot -1.
- `phase5/logs/test.231.journalctl.txt` — 442 lines filtered.
- `phase5/logs/test.8` — test-brcmfmac.sh dmesg from test.230 run
  (captured by script mid-session, not test.231). Kept as a reference
  for what a full successful run looks like.
- No pstore artifacts (bus-wide stall → watchdog frozen, as expected).

### Hardware state after SMC reset

Host alive, booted into boot 0 (21:36:38 BST). Chip reset via SMC.
Ready for next test after logging pivot.

### Implication: pivot before next wedge test

Further wedge experiments that depend on journald for sub-second
resolution are guaranteed to lose data. Need a transport that
survives the bus-wide stall. Top candidate: TCM-resident ring buffer
(see "Current state" → test.232 draft).

---

## PRE-TEST.231 (2026-04-22 21:33 BST, boot 0, no reset needed) — single-run timing bisect to locate the wedge window post-set_active

### Hypothesis

With `brcmf_chip_set_active` re-enabled (baseline + wedge returns),
emit 10 breadcrumbs at 10/50/100/200/300/500/700/900/1000 ms after
the `returned true` marker. The last breadcrumb to appear in the
journal gives an upper bound on the wedge window. Interpretation:

- Last breadcrumb at 10–100 ms → fw hits the bus within ~100 ms of
  starting. Suggests DMA-target-missing or instant config-TLP failure.
- Last breadcrumb at 200–500 ms → fw runs some init routine then
  stumbles. Could be init-poll on a missing resource.
- Last breadcrumb at 700–1000 ms → fw polls for a host-ready marker
  or does extensive internal init first.
- All breadcrumbs including `t=1000ms dwell done` land, host wedges
  later → stall is past 1 s; broader window to hunt in.
- `t=0ms dwell start` itself does not land → stall is instant-on-
  set_active.

### Why single-run (not 4 runs as advisor initially suggested)

Advisor suggested N=50/250/500/900 as 4 separate runs. Single-run with
10 sequential breadcrumbs gives the same information (last-landing
breadcrumb = wedge upper bound) plus finer granularity, at 1/4 the
SMC-reset cost. Wedge is reliably reproducible (tests 227/228/229 all
wedged in the same window), so independent-runs aren't needed for
variance observation. If the single-run result is ambiguous (e.g.
breadcrumbs interleave with kernel watchdog messages in confusing
ways), individual-N runs remain available as a fallback.

### Code change (pcie.c, in `brcmf_pcie_download_fw_nvram`)

Restored the original `brcmf_chip_set_active` call + surrounding
`test.226 immediately before / after` + `test.188: returned %s`
breadcrumbs that test.230 removed. Then replaced test.230's single
`msleep(1000)` with a chain of `msleep(N) + pr_emerg` pairs at the
offsets above. Total dwell is still 1000 ms.

Post-set_active probe block (`probe_armcr4_state` etc.) remains at
`#if 0` — keep one variable at a time.

### Build status — REBUILT CLEAN (2026-04-22 21:32 BST)

`brcmfmac.ko` 14251536 bytes, mtime 21:32. `strings` confirms all 10
`test.231: t=…` breadcrumbs present.

### Hardware state (still boot 0 of 21:06 BST SMC-reset session)

- `lspci -vvv -s 03:00.0`: Control Mem+ BM-, Status MAbort-, DevSta
  UnsupReq- (cleared by test.230), TransPend-, LnkSta 2.5GT/s x1.
- BAR0 timing 17/18/18/18 ms — fast-UR intact.
- pstore empty, no modules loaded.
- No SMC reset needed (test.230 left chip clean because fw never activated).

### Decision tree

| Journal signature | Interpretation | Test.232 direction |
|---|---|---|
| Last breadcrumb is `t=0ms dwell start` or `returned true` | Stall is effectively instant-on-set_active. | Try to populate shared-memory struct in TCM before set_active so fw has valid DMA targets. |
| Last breadcrumb in [10, 200] ms | Fast fw-stumble. Likely DMA-target-missing. | Same as above (populate shared-memory). |
| Last breadcrumb in [300, 700] ms | Medium — fw runs an init routine then stumbles. | Look for fw init polling shapes (ring-descriptor read, doorbell write, MSI request). |
| Last breadcrumb in [900, 1000] ms | Slow — fw polls host-ready marker or does extensive init. | May be recoverable by responding to a fw doorbell within the window. |
| All breadcrumbs land including `t=1000ms dwell done` | Stall is past 1 s. | Extend dwell (test.232: 1/2/3/5 s breadcrumbs) and re-bisect. |

### Logging / watchdog arming (same as test.229/230)

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

If host wedges: expect no auto-reboot, user power-cycle + SMC reset
needed (consistent with tests 227/228/229).

### Expected artifacts

- `phase5/logs/test.231.run.txt` — PRE + harness.
- `phase5/logs/test.231.journalctl.full.txt` — full journal (boot 0
  if host survives; boot -1 if wedged).
- `phase5/logs/test.231.journalctl.txt` — brcmfmac/PCIe/NMI filtered.

---

## POST-TEST.230 (2026-04-22 21:25 BST, boot 0 — NO CRASH, host survived cleanly) — `brcmf_chip_set_active` is the SOLE wedge trigger

### Headline

First-ever clean full run of the probe path. Skipping the
`brcmf_chip_set_active` call (single code change from test.229 baseline)
produced a clean -ENODEV return, clean rmmod, host alive ≥30 s after
rmmod, and a healthy PCIe bus throughout. All strict success criteria
met. H2 is confirmed at the strongest possible level: firmware
activation is the sole bus-stall trigger.

### Evidence (current-boot journal, 21:24:49 → 21:24:58, no reboot needed)

- Pre-set-active path: all breadcrumbs landed in order
  (pci_set_master, FORCEHT, pre-set-active probes, etc. — identical to
  test.229).
- Firmware download: 107 chunks, full 442 KB.
- TCM verify: 16/16 MATCH.
- `test.219: calling brcmf_chip_set_active resetintr=0xb80ef000
  (FORCEHT pre-applied)` — breadcrumb landed but the call itself skipped.
- `test.230: SKIPPING brcmf_chip_set_active — resetintr=0xb80ef000
  NOT written to CR4` — 1136.529876 s boot-time.
- `test.230: 1000 ms dwell done (no fw activation); proceeding to
  BM-clear + release` — 1137.566367 s boot-time (≈1.04 s later — the
  msleep(1000) actually completed).
- `test.188: pci_clear_master done; PCI_COMMAND=0x0002 BM=OFF` — clean BM-clear.
- `test.188: post-BM-clear MMIO guard mailboxint=0x00000001 (endpoint
  alive after BM-off)` — endpoint responsive through end of probe.
- `test.163: download_fw_nvram returned ret=-19 (expected -ENODEV
  for skip_arm=1)` — probe path completed as designed.
- `test.163: fw released; returning from setup (state still DOWN)` —
  full return, no stall.

### Post-run host / bus health (rmmod at 21:25:32 BST, +30 s dwell at 21:26:03)

- `rmmod brcmfmac_wcc && rmmod brcmfmac && rmmod brcmutil` — all clean.
- `lsmod | grep -E 'brcm|wl'` after rmmod — empty.
- lspci after rmmod: Control `Mem+ BusMaster-`; DevSta **UnsupReq-**
  (sticky bit cleared — nothing in this test generated an UR after
  the pre-test UR probe), TransPend-; LnkCtl ASPM Disabled (kernel
  reverted after rmmod), LnkSta 2.5GT/s x1.
- BAR0 timing 18/18/18/18 ms — fast-UR regime intact.
- pstore still empty.
- 30 s dwell passed uneventfully.

### What this proves

| Hypothesis | Status |
|---|---|
| Pre-set_active bus-hostile write (FORCEHT / pci_set_master / fw download) | **RULED OUT** — entire sequence ran, host fine |
| `brcmf_chip_set_active` itself or its immediate aftermath is the trigger | **CONFIRMED** |
| Firmware activation → DMA to missing shared-memory rings → completion starvation | still the leading theory; test.231 will probe it |

### Next: test.231 (timing bisect, per advisor)

Re-enable `brcmf_chip_set_active` and place an `msleep(N)` between the
`returned %s` breadcrumb and the BM-clear tail, running the test at
N=50 / 250 / 500 / 900 ms. The *last* N for which the msleep-done
breadcrumb lands tells us the window in which firmware first does
something bus-hostile. Rationale:
- Fast (<100 ms) → fw stumbles immediately on missing DMA target.
- Slow (>500 ms) → fw runs some init first, then stumbles — different
  signature, maybe it's polling for a host-readiness marker.

### Artifacts captured

- `phase5/logs/test.230.run.txt` — PRE sysctls + lspci + BAR0 + pstore
  + strings + harness output (405 lines).
- `phase5/logs/test.230.journalctl.full.txt` — current-boot full
  journal (1419 lines).
- `phase5/logs/test.230.journalctl.txt` — brcmfmac/PCIe/NMI filtered
  (401 lines).
- No pstore dump (none expected — no crash).

---

## PRE-TEST.230 (2026-04-22 21:22 BST, boot 0 post-SMC-reset) — skip `brcmf_chip_set_active` entirely; binary test of H2-sub-hypothesis

### Hypothesis

Firmware activation (= CR4 coming out of reset with rstvec written) is
the SOLE trigger for the bus-wide wedge confirmed in test.229 (H2).
If we never call `brcmf_chip_set_active`, the host should survive the
entire probe path cleanly (return -ENODEV → rmmod succeeds → host stays
alive afterwards).

### Code change

`drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` —
`brcmf_pcie_download_fw_nvram`, right after the `test.219: calling`
and `mdelay(30)`. Replaced the `brcmf_chip_set_active(...)` call and
its surrounding probe/dwell block with:

```c
pr_emerg("BCM4360 test.230: SKIPPING brcmf_chip_set_active — resetintr=0x%08x NOT written to CR4\n",
         resetintr);
msleep(1000);
pr_emerg("BCM4360 test.230: 1000 ms dwell done (no fw activation); proceeding to BM-clear + release\n");
```

Also initialised `sa_rc = false` at declaration to silence uninitialised
use (it is referenced nowhere else in this arm but still declared in
the enclosing scope).

**Post-set_active probe block remains `#if 0`** — not re-enabled. This
preserves the H1/H2 ambiguity fix from test.229 (one variable at a
time).

### Build status — REBUILT CLEAN (2026-04-22 21:22 BST)

`brcmfmac.ko` 14243024 bytes, mtime 21:22. `strings` confirms both
new breadcrumbs present:
- `BCM4360 test.230: SKIPPING brcmf_chip_set_active`
- `BCM4360 test.230: 1000 ms dwell done (no fw activation); …`

### Hardware state (post-SMC-reset boot at 21:06 BST)

- `lspci -vvv -s 03:00.0` — Control `Mem+ BusMaster+`, Status
  MAbort-, TAbort-, DEVSEL=fast; DevSta CorrErr+ UnsupReq+ (sticky,
  from earlier UR), AuxPwr+ TransPend-; LnkCtl ASPM Enabled, CommClk+;
  LnkSta 2.5GT/s x1 — clean (post-SMC-reset idiom, matches test.229
  PRE state exactly).
- BAR0 `dd resource0` wall-clock: 18/18/18/18 ms — fast-UR regime.
- `lsmod | grep -E 'brcm|wl'`: empty.
- pstore: empty (no lingering dumps).

### Decision tree

| Outcome signature | Interpretation | Next (test.231) |
|---|---|---|
| Both breadcrumbs in journal + -ENODEV return + rmmod works + host ≥30 s alive after rmmod | **Firmware activation IS the sole bus-stall trigger.** Pre-set_active path is safe. | Timing bisect: re-enable set_active, insert `msleep(N)` between set_active return and the BM-clear tail. Try N=50/250/500/900 (new test.231 binary discriminator). |
| Any breadcrumb missing, or driver stall, or host wedges | **Something pre-set_active is bus-hostile.** Candidates: FORCEHT write, pci_set_master, fw-write sequence itself. | Progressively disable pre-set_active steps — start by skipping pci_set_master (keep BM=OFF throughout). |
| Second breadcrumb in journal but rmmod hangs or host dies later | More subtle — bus health is already degraded even without fw activation; mdelay timing or prior register writes left a dirty state. | Capture all post-second-breadcrumb state (pstore, /proc/interrupts, lspci re-read) before interpreting. |

### Logging / watchdog arming (same as test.229)

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

Note: if the host wedges, `panic=30` may not trigger auto-reboot
(bus-wide stalls freeze the watchdog CPU too, as confirmed in tests
227/228/229). Plan for user power-cycle + SMC reset on that path.

### Expected artifacts

- `phase5/logs/test.230.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore + strings + harness output.
- `phase5/logs/test.230.journalctl.full.txt` — full current-boot kernel
  journal (or boot -1 if host wedges).
- `phase5/logs/test.230.journalctl.txt` — brcmfmac/PCIe/NMI-filtered subset.
- `phase5/logs/test.230.pstore.txt` — IF pstore fires (unlikely on
  bus-wide stall; possible if this is a different failure mode).

---

## POST-TEST.229 (2026-04-22 21:08 BST, boot 0 of new session — boot -1 journal captured) — (H2) CONFIRMED: wedge is firmware-initiated bus stall, not our probe MMIO

### Headline

Test.229 ran the Option A binary discriminator (all post-set_active probes
gated behind `#if 0`, replaced with a single `msleep(1000)`). Host still
wedged bus-wide. **This is H2 from the PRE-229 decision tree: firmware-
initiated bus stall — our probing was innocent.** Newly-alive firmware
on ARM CR4 takes the front-side bus down on its own during the ~1 s
window after `brcmf_chip_set_active` returns, regardless of what the
host does next.

### Evidence (boot -1 journal, Apr 22 21:04:41 → 21:04:59)

- Full 442 KB firmware downloaded: **107** chunks in journal (complete).
- TCM verify post-fw-download: **16/16 MATCH** at every sampled offset.
- Pre-set-active probes ran cleanly:
  - CR4 IOCTL=0x21 IOSTATUS=0 RESET_CTL=0 CPUHALT=YES
  - D11 IOCTL=0x7 IOSTATUS=0 RESET_CTL=0x1 (IN_RESET=YES)
  - CR4 clk_ctl_st=0x07030040 [HAVEHT/ALP_AVAIL/bit6]
- FORCEHT applied: clk_ctl_st 0x01030040 → 0x010b0042 (post-write).
- `brcmf_chip_set_active returned true` — reached.
- `test.229: SKIPPING post-set_active probes — msleep(1000) before BM-clear`
  emitted (21:04:59).
- **Second breadcrumb `test.229: 1000 ms dwell done` never appeared.**
  Journal ends there. No NMI watchdog trigger, no panic, no AER.
- pstore empty on recovery (`/sys/fs/pstore/` — 0 files).
- Auto-reboot did not complete in the armed 30 s; user performed SMC reset.

### Why this is H2

The post-set_active code path in test.229 is literally just a `pr_emerg`
+ `msleep(1000)` + `pr_emerg`. No MMIO, no config-space writes, no
anything. The first pr_emerg landed in the journal (so CPU was alive
then). During the `msleep(1000)` — where the kernel yields, other CPUs
keep running, timer ticks fire — something froze every CPU
simultaneously. That signature rules out "host did something that
hung" and points to "bus went away under us". The most plausible
cause on this bus (front-side) is PCIe completion starvation: firmware
does something (a DMA read, a config TLP, an MSI) that never gets
a completion; every CPU that subsequently touches the chip or the
shared PCIe domain blocks; watchdog CPUs block too.

### What we've now ruled out

| Hypothesis | Status |
|---|---|
| Wedge caused by `probe_armcr4_state` MMIO at 0x408 (first post-set_active read) | **RULED OUT** — probes skipped, wedge still occurred |
| Wedge caused by any of the tier-1/2 fine-grain probes | **RULED OUT** — all gated behind `#if 0` |
| Wedge caused by 3000 ms dwell polling | **RULED OUT** — replaced with `msleep(1000)`, still wedged |
| Firmware load / TCM corruption / NVRAM write | not yet ruled out, but highly unlikely (16/16 TCM MATCH, 107 chunks clean) |
| Firmware-initiated post-activation bus event | **CONFIRMED** as the cause |

### Artifacts captured

- `phase5/logs/test.229.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore (empty) + the SKIPPING / dwell-done strings from .ko.
  `test-brcmfmac.sh output` ends at `Loading patched brcmfmac modules...`
  (script killed mid-run by wedge).
- `phase5/logs/test.229.journalctl.full.txt` — 1390 lines whole boot -1.
- `phase5/logs/test.229.journalctl.txt` — 397 lines brcmfmac/PCIe/NMI filtered.
- No `test.229.pstore.txt` — pstore empty after recovery reboot.

### Implication for test.230

PRE-229 decision tree prescribes (H2 branch):

> test.230 goes a different direction: either don't call set_active at
> all (read all the state before firmware comes alive), or sample CR4
> state via config-space-only path (no BAR0 MMIO after set_active).

Cheapest next step: **don't call set_active**. Single-line change
(gate the `brcmf_chip_set_active` call behind `#if 0`, or replace the
call with a no-op breadcrumb + msleep). Decision tree:

| Result | Interpretation | Next |
|---|---|---|
| Host stays alive, driver returns -ENODEV cleanly, rmmod works | Firmware activation IS the sole trigger. Bus stall happens after CR4 is released from reset. | test.231 narrows the timing: e.g. call set_active then msleep(100) vs msleep(500) to see when the stall starts. |
| Host wedges anyway | Something pre-set_active is causing the stall (FORCEHT write, pci_set_master, fw/NVRAM write sequence). Much more work to isolate. | test.231 = progressively disable pre-set_active steps to isolate the culprit. |

This keeps the experimentation binary and cheap.

### Secondary possibility to consider (not test.230 but future)

Upstream brcmfmac sets up extensive shared memory / ring descriptor
infrastructure BEFORE `brcmf_chip_set_active` on other Broadcom PCIe
parts: `brcmf_pcie_init_share`, ring allocation, mailbox setup. Our
bypass path likely skips all of that for BCM4360. If newly-alive
firmware tries to DMA ring descriptors from host memory that was
never allocated, it could trigger exactly the kind of completion
starvation we observe. Worth investigating once test.230 narrows the
cause further — but test.230 is the cheaper next swing.

---

## POST-TEST.228 (2026-04-22 20:42 BST, boot 0 of new session — boot -1 journal captured) — set_active reached AND returned true for the first time; pstore empty, bus-wide stall confirmed

### Headline

Full 442 KB firmware downloaded (**107** chunks in journal, up from 26 in
test.227), TCM verify passed (16/16 MATCH), `brcmf_chip_set_active`
called AND returned `true` — furthest progress ever. Host wedged
immediately after, between the `brcmf_chip_set_active returned true`
pr_emerg and the first `post-set-active-20ms` MMIO probe. NMI watchdog
never fired, `/sys/fs/pstore/` is empty, host auto-rebooted ~2 min
later (not the 30 s armed) — consistent with bus-wide stall that
froze every CPU including the watchdog CPU.

### Branch taken from PRE-228 decision tree: (a) + new progress

| Result | → test.228 observed |
|---|---|
| ~107 chunks → (a) pure truncation; wedge is post-chunked-write | **MATCH — 107 chunks captured** |
| ~26 chunks → (b) real regression at chunk 27 | — |

Branch (a) confirmed for the chunked-write portion. But additionally:
**set_active was empirically captured in this journal for the first time.**
test.225.rerun's journal (the one the commit called "JACKPOT") actually
ended at `CC-res_state=0x000007ff (pre-release snapshot)` — no
set_active marker. test.228 is the FIRST run where we see
`BCM4360 test.188: brcmf_chip_set_active returned true`. That's real
new progress, not just truncation-lift.

### Confounder — state-dependence across 4 stacked wedges without SMC reset

Same .ko as test.226/227 but the chip has now endured 4 wedges without
SMC reset. "(a) vs (b)" is clean at the chunk-count level, but
"same .ko, same plan" is no longer literally the same experiment at
the chip-state level. The (a) conclusion stands (107 is unambiguous),
but test.229 should be run on a freshly-reset chip so the next binary
outcome is not contaminated by accumulated chip state.

### Wedge location

Last brcmfmac line in boot -1 journal (line 1399 of the full log):
```
20:36:12 brcmfmac: BCM4360 test.226: immediately before brcmf_chip_set_active()
20:36:12 brcmfmac 0000:03:00.0: BCM4360 test.65 activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006 (BusMaster preserved)
20:36:12 brcmfmac: BCM4360 test.226: immediately after brcmf_chip_set_active() returned
20:36:12 brcmfmac: BCM4360 test.188: brcmf_chip_set_active returned true
(end of journal)
```

Next action in code (pcie.c:2497-2498):
```c
mdelay(20);
brcmf_pcie_probe_armcr4_state(devinfo, "post-set-active-20ms");
```

`brcmf_pcie_probe_armcr4_state` does (pcie.c:714-741):
1. pci_read_config_dword BAR0_WINDOW  (config space — usually safe)
2. pci_write_config_dword BAR0_WINDOW := arm_core->base + 0x100000 (config posted)
3. **MMIO read of 0x408 (ARM CR4 IOCTL)  ← first MMIO after set_active**
4. MMIO read of 0x40c (IOSTATUS)
5. MMIO read of 0x800 (RESET_CTL)
6. pci_write_config_dword to restore BAR0_WINDOW
7. select_core(CHIPCOMMON)
8. pr_emerg the result

Two candidate hypotheses for the wedge:

- **(H1) Host-initiated MMIO stall.** The read at 0x408 hangs because
  ARM CR4 wrapper is in a transitional state: CR4 has just been taken
  out of reset and firmware is reinitialising the BCMA bus during the
  20 ms mdelay window.
- **(H2) Firmware-initiated bus stall.** Newly-alive firmware on CR4
  does something of its own (bus-wide master-abort, PCIe completion
  starvation, BCMA clock gating) that freezes the host bus
  independently of our probing.

### pstore verdict — not a viable transport past this wedge

NMI watchdog armed (confirmed `NMI watchdog: Enabled` at 20:25:24).
`hardlockup_panic`, `softlockup_panic`, `panic=30` armed (confirmed in
`test.228.run.txt`). Yet **no panic fired, pstore empty, auto-reboot
at ~2 min not 30 s**. This is PRE-227 decision-table outcome (i):
bus-wide stall freezes every CPU simultaneously; the watchdog CPU
can't fire either. **Breadcrumbs past the wedge point will never
flush, by either journald or panic handler.** Must move the wedge
earlier (or skip it entirely) if we want to capture more.

### Artifacts captured (2026-04-22 20:42 BST)

- `phase5/logs/test.228.run.txt` — 35 lines; PRE sysctls + lspci +
  BAR0 timing + pstore (empty). `test-brcmfmac.sh output` is a blank
  line (script killed mid-run by wedge — expected).
- `phase5/logs/test.228.journalctl.full.txt` — 1399 lines (whole boot -1).
- `phase5/logs/test.228.journalctl.txt` — 340 lines (brcmfmac-filtered).
- No `test.228.pstore.txt` — pstore was empty after the crash reboot.

---

## PRE-TEST.229 (plan, not yet run) — Option A binary discriminator: is the wedge caused by our probe MMIO or by firmware action on the bus?

### Hypothesis + design

Skip ALL post-set_active probes (`probe_armcr4_state`,
`probe_d11_state`, `probe_d11_clkctlst`, tier-1 fine-grain, tier-2
fine-grain, 3000 ms dwell). Replace with a single
`msleep(1000)` + breadcrumb pair + straight to the existing
BM-clear → release_firmware → return -ENODEV tail.

### Binary decision tree

| Result | Interpretation | Next test |
|---|---|---|
| Host does NOT wedge; driver returns -ENODEV cleanly and rmmod works | **(H1) Wedge is host-initiated MMIO.** Our probe hung on an MMIO read. | test.230 adds per-MMIO breadcrumbs inside `probe_armcr4_state` (between the config-space window reprogramming and each of the three BAR0 reads) to pinpoint the hanging register. |
| Host wedges anyway | **(H2) Wedge is firmware-initiated bus stall.** Our probing was innocent; newly-alive firmware takes the bus down on its own. | test.230 goes a different direction: either don't call set_active at all (read all the state before firmware comes alive), or sample CR4 state via config-space-only path (no BAR0 MMIO after set_active). |

### Why Option A beats Option B (per-register breadcrumbs)

1. **Binary answer from one run.** Option A tests a single yes/no
   question. Option B assumes (H1) and tries to narrow it — wastes
   a run if (H2) is the real cause.
2. **Works with bus-wide stall.** If (H2) is true, breadcrumbs past
   the wedge never flush. Option A's last breadcrumb is a controlled
   `msleep(1000)` in the middle of the host's own code — if we get
   past it, the wedge isn't bus-wide.
3. **Cheap.** Small code change (gate the probe block), rebuild is
   ~30 s on this hardware, test run ~20 s.

### Pre-test state requirements

**USER ACTION REQUIRED before test.229: SMC reset.** The chip has
endured 4 wedges without reset across tests 226 (×3), 227, 228. Test.229
is a pivot run — we need a clean chip baseline so the binary outcome
is not contaminated by accumulated state. ACPI config space still looks
clean on current boot but that is not evidence the chip itself is clean.

### Code change plan (to implement next)

In `brcmf_pcie_download_fw_nvram` (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`), immediately after:
```c
pr_emerg("BCM4360 test.188: brcmf_chip_set_active returned %s\n",
         sa_rc ? "true" : "false");
```
wrap the subsequent post-set_active probe + tier + dwell block in
`if (0)` (or a compile-time flag), and insert:
```c
pr_emerg("BCM4360 test.229: SKIPPING post-set_active probes — msleep(1000) before BM-clear\n");
msleep(1000);
pr_emerg("BCM4360 test.229: 1000 ms dwell done; proceeding to BM-clear + release\n");
```

The BM-clear / release_firmware / return -ENODEV tail at pcie.c:2742+
stays intact.

### Pre-test checklist (to complete before running)

1. Build status: **REBUILT CLEAN** (2026-04-22 20:51 BST) — `brcmfmac.ko`
   contains both `test.229: SKIPPING post-set_active probes` and
   `test.229: 1000 ms dwell done` strings; probe/tier/dwell block now
   gated behind `#if 0`
2. PCIe state: will re-verify after SMC reset (user action)
3. Hypothesis stated: above
4. Plan committed and pushed: this commit
5. Filesystem synced in commit step
6. **USER ACTION PENDING**: SMC reset before insmod

### Run command (same as every test)

```bash
# Arm watchdog sysctls (same as test.228; still useful to confirm H1 vs H2 crash mode if wedge still happens)
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync

sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```


---

## POST-TEST.227 / PRE-TEST.228 (2026-04-22 20:35 BST, boot 0 of new session) — tail-truncation theory partly confirmed; designing the (a)/(b) discriminator

### Headline

Test.227 ran, host wedged, auto-reboot never completed (user pressed power
button). Journal of boot -1 shows the driver got **much further** than the
3× test.226 runs: all the way through `test.158` post-chip_attach probes
(BusMaster clear, ASPM disable, LnkCtl read — all succeeded), then into
`brcmf_pcie_download_fw_nvram`, and into the 442 KB chunked firmware
write loop. Last captured breadcrumb:
```
20:23:18 brcmfmac: BCM4360 test.225: wrote 26624 words (106496 bytes) last=0x220682ab readback=0x220682ab OK
```
That's chunk 26 of 108. Journal stops there — no further breadcrumbs.

### What we learned

1. **Tail-truncation theory is confirmed in part.** The "wedge at test.158"
   pattern from test.226/rerun/rerun2 was an artifact of journald not
   flushing after the host lost userspace. With NMI watchdog enabled
   (`Enabled. Permanently consumes one hw-PMU counter.` at 20:21:47, before
   the 20:23:03 insmod), the kernel kept forcing flushes longer. So the
   real wedge point is NOT test.158 — that line is reached and passed
   cleanly.

2. **pstore is still empty** after the wedge — `/sys/fs/pstore/` has no
   `dmesg-efi_pstore-*` files. Interpretation per the PRE-227 decision
   table: either (i) the wedge is a bus-wide stall (all CPUs frozen
   simultaneously, watchdog CPU can't fire), or (ii) the wedge is soft
   (CPU still responds to NMI so `hardlockup_panic` never triggers), or
   (iii) the panic handler started but couldn't complete the efi_pstore
   write (less likely — `panic=30` would have rebooted but the user
   power-cycled before 30 s elapsed so we can't tell).

3. **NMI watchdog was armed** (confirmed in boot -1 journal). No direct
   confirmation of `hardlockup_panic`/`softlockup_panic` sysctls in logs
   (kernel doesn't log sysctl writes), so we don't know if the panic
   path was actually enabled. `test.227.run.txt` is 0 bytes — the
   harness did not capture the sysctl state before insmod. Fix this in
   test.228 (print sysctls to run.txt).

### The unresolved question — two hypotheses, opposite test.228 designs

The chunked-write loop in `brcmf_pcie_download_fw_nvram` is
**byte-identical** between commit `5735a29` (test.225 POST rerun) and
commit `0a19a6e` (test.226 code) — only post-chunked-write breadcrumbs
differ. Yet:

- **test.225.rerun** (boot of 19:24:11 BST): journal contains **107**
  `test.225: wrote … OK` lines, i.e. the full 442 KB was written and
  TCM verify ran afterwards (`fw-sample[…] MATCH` × 16). Success.
- **test.227** (boot of 20:23:18 BST): journal contains **26**
  `test.225: wrote … OK` lines, i.e. only 24 % of firmware captured.

Possible explanations:

- **(a) Pure tail-truncation, no real regression.** All 107 chunks
  actually wrote successfully in test.227 too, but journald only
  flushed the first 26 before the host wedged. The real wedge in
  test.227 is post-chunked-write (possibly in the new test.226
  breadcrumb block). "Wedge at chunk 27" would then be an illusion,
  same as "wedge at test.158" was.
- **(b) Real regression in chunked-write.** Chunk 27 genuinely hangs
  now but didn't before test.225.rerun. Possible causes: chip state
  corruption from 3 consecutive wedges without SMC reset; ambient
  temperature; a previously-cached PCIe window state.

Designing test.228 breadcrumbs around chunk 27 commits to (b) before
(b) has been tested.

### Cheapest discriminator — re-run SAME .ko with explicit sysctl logging

1. No code change. Same `brcmfmac.ko` as test.226/227.
2. Re-arm watchdog sysctls and log their values to `test.228.run.txt`
   BEFORE insmod so we have a durable record.
3. `sync` before insmod.
4. Run the test; capture boot journal after reboot.

Decision tree:

| Result | Interpretation | Next test |
|---|---|---|
| ~107 chunks in journal (same as test.225.rerun) | (a) Pure truncation; the "wedge" in test.227 was post-chunked-write. | test.229 = add breadcrumbs to the test.226 post-chunked-write block + long mdelay between each so journald has time to flush. |
| ~26 chunks again (same chunk-27 cutoff) | (b) Real regression, possibly state-driven. | Ask user for SMC reset, re-run same .ko. If ~107 chunks return → state-driven; test.229 isolates the trigger. If ~26 still → chunk-27 is a real data-dependent wedge; test.229 adds per-word breadcrumbs in chunk 27. |
| Chunks count wildly different from 26 or 107 (e.g. 50, 80) | Non-deterministic / race; the wedge is timing-related, not address-related. | Switch to earlyprintk or accept we need a second host for netconsole. |

### Hardware state before test.228 (boot 0 of this session)

- User note: SMC reset was NOT done after the test.227 crash.
- `lspci -vvv -s 03:00.0`: Control I/O- Mem- BusMaster-, Status MAbort-
  SERR- TAbort- DEVSEL=fast, DevSta AuxPwr+ TransPend-, LnkCtl ASPM
  Disabled CommClk-, LnkSta 2.5GT/s x1 — clean.
- BAR0 `dd resource0` wall-clock: 40/18/18/18 ms (1st is cold-cache
  warmup; steady state is fast-UR regime well under 40 ms).
- `lsmod | grep brcm` — empty.
- pstore empty (no previous panic dumps).
- `nmi_watchdog`, `hardlockup_panic`, `softlockup_panic`, `panic` all
  back to defaults (0 / 0 / 0 / 0) — reboot cleared the earlier sysctls.

### Commands in order (test.228)

```bash
# Arm watchdog path and record the fact durably
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic

# Durable record of pre-test state
RUN=/home/kimptoc/bcm4360-re/phase5/logs/test.228.run.txt
{
  echo "=== test.228 PRE sysctls ==="
  for k in nmi_watchdog hardlockup_panic softlockup_panic panic; do
    printf '  %s=%s\n' "$k" "$(cat /proc/sys/kernel/$k)"
  done
  echo "=== test.228 PRE lspci ==="
  sudo lspci -vvv -s 03:00.0 | grep -E 'Control|Status|MAbort|LnkSta|CommClk|TransPend|DevSta' | sed 's/^/  /'
  echo "=== test.228 PRE BAR0 timing (4 reads) ==="
  for i in 1 2 3 4; do
    { TIMEFORMAT=%R; time sudo dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 of=/dev/null bs=4 count=1 >/dev/null 2>&1; } 2>&1 | sed 's/^/  /'
  done
  echo "=== test.228 PRE pstore ==="
  sudo ls -la /sys/fs/pstore/ 2>&1 | sed 's/^/  /'
} | sudo tee "$RUN" >/dev/null
sync

# Run the test
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh 2>&1 | sudo tee -a "$RUN" >/dev/null
```

### Expected artifacts after reboot/recovery

- `phase5/logs/test.228.run.txt` — sysctl values + lspci/BAR0 pre-test
  state (durable even if host wedges mid-test).
- `phase5/logs/test.228.journalctl.full.txt` — boot -1 full journal.
- `phase5/logs/test.228.journalctl.txt` — brcmfmac-filtered subset.
- `phase5/logs/test.228.pstore.txt` — if pstore fires this time.

### State written to RESUME_NOTES and committed BEFORE running

This entry is committed and pushed before the test starts, per the
CLAUDE.md rule. If the host wedges, the next session can pick up from
here with the decision tree already written down.

---

## PRE-TEST.227 (2026-04-22 20:15 BST, boot 0) — durable logging via pstore + NMI watchdog; SAME .ko as test.226

### Hypothesis

The wedge at `test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)` has
been observed 3/3 times. Runs up to that line are normal; the journal ends
there on each run. The leading theory is **tail-truncation**: pr_emerg is
emitted after test.158 but journald never flushes the last bytes to disk
because the host loses the ability to run userspace. The 12 test.226
breadcrumbs inside `brcmf_pcie_download_fw_nvram` all lie past the wedge
so they've never been observed — consistent with either "host wedges
between test.158 and first breadcrumb" or "host wedges later and all
that time journald never flushes".

### Why this test is cheap

- **No new code.** Using the existing test.226 .ko unchanged. First round
  of test.227 is purely a logging-transport change.
- **No new hardware.** efi_pstore backend is already registered
  (`Registered efi_pstore as persistent store backend` in dmesg of this
  boot). `/sys/fs/pstore/` is empty and ready.
- **Zero-cost kernel reconfig.** Three sysctl writes:
  - `kernel.nmi_watchdog=1` — enables hard/soft lockup detectors
  - `kernel.hardlockup_panic=1` — escalates "CPU stuck, doesn't respond to
    NMI" to a kernel panic (which triggers pstore dump + auto-reboot)
  - `kernel.softlockup_panic=1` — same for slower "thread held CPU >20s"
    case (belt-and-braces)
  - `kernel.panic=30` — auto-reboot 30 s after panic, so we recover
    without needing an SMC reset

### Why pstore (not netconsole) is the right first swing

- No second host needed. The user confirmed they do not want to set up a
  netconsole capture host.
- pstore writes synchronously to the panic handler — no buffering in a
  userspace daemon, so it does not share journald's "never flushed" failure
  mode.
- ~10240 bytes of the tail of the kernel log get saved
  (`CONFIG_PSTORE_DEFAULT_KMSG_BYTES=10240`). That's roughly 80–120 lines,
  comfortably covering the last ~30 s of brcmfmac activity.
- If the wedge is a single-CPU MMIO stall (canonical Broadcom pattern —
  CPU stuck waiting for a TLP completion), NMI watchdog detects that
  CPU's silence and panics. pstore dumps the tail of dmesg including any
  test.226 breadcrumbs that fired before the stall.

### Known failure mode — if this test yields nothing useful

If the wedge freezes every CPU simultaneously (bus-wide PCIe fault that
halts the whole front-side bus), no CPU runs the watchdog and no panic
fires. In that case pstore stays empty and we pivot to netconsole (which
needs a second host). Fallback is still cheap — same .ko, same test
harness, just a different transport.

### Expected outcomes

| pstore contents after reboot | Interpretation | Next |
|---|---|---|
| `dmesg-efi_pstore-*` contains `test.226` breadcrumbs past test.158 | Journal was truncating. We now have the real wedge point. | Move test.228 design to the new, deeper wedge point. |
| pstore contains lines up to `test.158: ARM CR4 core->base` and nothing after | No post-test.158 breadcrumb was ever emitted — wedge is literally on the next instruction (ARM CR4 probe or the msleep right after). | Redesign test.228 to probe that narrow gap — replace `pr_emerg("about to pci_clear_master")` + `msleep(300)` with either (a) skip the clear-master path entirely to see if wedge moves, or (b) split the next step into register reads with breadcrumbs between each. |
| pstore empty, journal truncated as before | Wedge is a bus-wide stall; watchdog never fired. | Pivot to netconsole (needs second host) or earlyprintk=serial (needs serial cable). |
| Machine does not reboot in 30 s | hardlockup_panic path didn't engage (or panic didn't auto-reboot). | Check if `kernel.panic` was actually 30; user may need to power-cycle once. |

### Hardware state before test (same boot 0 as previous entry)

- `lspci -vvv -s 03:00.0`: Control `I/O- Mem- BusMaster-`; MAbort-, SERR-,
  TAbort-, DEVSEL=fast, DevSta TransPend-, LnkSta 2.5GT/s x1.
- BAR0 `dd resource0` 19/17/17/18 ms — fast-UR regime.
- `lsmod | grep -E 'brcm|wl'` empty.
- No SMC reset since the rerun2 crash; state still looks clean per every
  check (wedge-at-test.158 is early enough that no PCIe config-space state
  got dirtied).

### Commands in order

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync

# Re-verify hardware is still fast-UR before insmod
sudo lspci -vvv -s 03:00.0 | grep -E 'MAbort|LnkSta'
for i in 1 2 3 4; do time sudo dd if=/sys/bus/pci/devices/0000:03:00.0/resource0 of=/dev/null bs=4 count=1 2>&1 | tail -1; done

# Run test (same as every other test)
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts (after reboot/recovery):
- `/sys/fs/pstore/dmesg-efi_pstore-*` — durable tail with pre-wedge lines
- `phase5/logs/test.227.pstore.txt` — copied from pstore
- `phase5/logs/test.227.journalctl.full.txt` — boot -1 journal (what
  journald did manage to save)
- `phase5/logs/test.227.journalctl.txt` — brcmfmac-filtered subset

### State written to RESUME_NOTES and committed BEFORE running

This entry is committed and pushed before the test starts, per the
CLAUDE.md rule. If the host wedges, the next session can pick up from
here.

---

## POST-TEST.226.rerun2 (2026-04-22 20:05 BST, boot 0 → crash, now on boot 0 of new session) — 3/3 WEDGE AT TEST.158, discriminator complete

### Headline

Third run of identical test.226 .ko wedged at the **exact same line** as runs 1 and 2:
`test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)` — emitted
20:05:00 BST, journal ends one line later. This is outcome 1 from the
binomial discriminator decision tree: **wedge is reproducible at this
flow point (3/3)**. The plan pivots to **test.227 — durable logging**
(netconsole or earlyprintk=serial), as more pr_emerg breadcrumbs are
dead weight if the real story is tail truncation from a deeper wedge.

### Boot -1 journal (the crashed rerun2)

Captured to `phase5/logs/test.226.rerun2.journalctl.full.txt` (1101 lines,
whole boot) and `phase5/logs/test.226.rerun2.journalctl.txt` (53 lines,
brcmfmac-filtered). Last six lines of the filtered log:

```
20:04:59 brcmfmac: BCM4360 test.224: post-settle pmustatus=0x0000002e res_state=0x000007ff (expect 0x2e / 0x7ff)
20:05:00 brcmfmac 0000:03:00.0: BCM4360 test.119: brcmf_chip_attach returned successfully
20:05:00 brcmfmac 0000:03:00.0: BCM4360 test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)
(journal ends here — host wedged)
```

Identical shape to runs 1 (19:41:42) and 2 (19:51:13): everything through
chip_attach succeeds, the "ARM CR4 core->base" probe prints, and then the
host stops logging. The 12 test.226 breadcrumbs inside
`brcmf_pcie_download_fw_nvram` never fire (they are past the wedge).

### Current boot 0 state (this session, crash-recovery only — SMC reset NOT done)

User notified that no SMC reset was performed after the rerun2 crash.
Checked hardware anyway:

- `lspci -vvv -s 03:00.0`: Control `I/O- Mem- BusMaster-`; Status
  MAbort-, SERR-, TAbort-, DEVSEL=fast — clean.
- DevSta AuxPwr+ TransPend- — no hung transactions.
- LnkCtl: ASPM Disabled; CommClk- (pre-ASPM-config state, normal on
  fresh boot). LnkSta: Speed 2.5GT/s, Width x1 — link up.
- BAR0 `dd resource0` wall-clock: 19 / 17 / 17 / 18 ms — fast-UR regime
  (well under 40 ms stuck threshold).
- `lsmod | grep -E 'brcm|wl'`: empty.

Despite no SMC reset, the chip looks clean by every normal check. The
wedge at test.158 was early (before PCIe config-space writes, before
bus-master, before FW download), so it apparently did not latch
persistent dirty state in the chip. This is consistent with the pattern
seen on boot 0 after the earlier rerun1 wedge.

### Git corruption recovered

Session restart found three zero-byte object files from the crashed
rerun2 write (this is the corruption pattern CLAUDE.md warns about):
`c32be563…` (HEAD commit), `2fb2e407…` (blob), `8f8f5d6f…` (tree). The
remote `origin/main` already had the same SHA, confirming the commit
was pushed before the crash. Recovery: `sync` → delete the three exact
zero-byte files → `git fetch origin` → `git fsck` clean (only harmless
dangling orphans from prior recoveries). Working tree intact at
`c32be56`. Commit tool-chain fully functional again.

### Decision for next step — test.227 (durable logging)

Pivot per the binomial decision tree in the earlier PRE entry. Two
candidate transports:

1. **netconsole** (kernel → UDP → capture host on same network)
   - Pros: no extra hardware, works on NixOS out of the box, each
     `pr_emerg` is flushed to the wire before the next line executes,
     so even a hard lockup leaves a complete trace on the capture host.
   - Cons: need a second host on the LAN to run `nc -lu` or a simple
     UDP capture script. User has not yet indicated such a host is
     available.
2. **earlyprintk=serial** (kernel → `/dev/ttyS0` → serial cable → capture host)
   - Pros: bypasses all kernel-log machinery; works even in very early
     boot / NMI context.
   - Cons: needs physical serial cable + a second host with a serial
     port. NixOS may not have a UART exposed depending on the platform.

Recommended: **netconsole**, because no new hardware is needed if the
user has a second machine on the network (even a laptop). test.227
would add a NETCONSOLE_TARGET setup step, convert the breadcrumbs around
the test.158 wedge to pr_emerg, and keep journald capture as a backup.

### Pending user input before test.227 implementation

- Confirm whether to proceed with netconsole (second host available?)
  or pivot to earlyprintk=serial (hardware available?).
- Whether to do an SMC reset before the next test (recommended — we have
  a 2-row pattern of "wedge at test.158 → boot looks clean → still
  wedges", so state isn't the cause, but SMC reset removes one variable).

---

## POST-TEST.226 RERUN (2026-04-22 19:55 BST, boot 0) — wedged at same test.158 line as first run; 2/2 reproducibility

### Headline

The test.226 rerun on boot -1 (19:50:54 → 19:51:13 — 19 s from insmod to
wedge) stopped at the exact same line as the first test.226 run:
`test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)`. Two runs of
the same .ko, same wedge point. SMC reset between boot -1 and boot 0
done; boot 0 clean (BAR0 20-23 ms fast-UR, lsmod clean, no MAbort/SERR).

### What this does — and does not — prove

The 2/2 reproducibility rules out "one-off flake". But it does NOT prove
the wedge is between the ARM CR4 print and the next pr_emerg in source
— source has only `pr_emerg("about to pci_clear_master")` + `msleep(300)`
between them, and the pr_emerg precedes the msleep. A missing pr_emerg
from the log is more likely **journald tail truncation from a deeper
wedge** than a wedge on a trivial pr_emerg line.

Also consider: test.225.rerun (boot -3) got past this exact probe and
reached the full FW download. Nothing in the test.226 diff (26 lines
of pr_emerg+msleep inserted INSIDE `brcmf_pcie_download_fw_nvram`) is
upstream of this probe. Either the regression is stochastic (not 2/2
but flip-a-coin leaning bad) or layout-perturbation of the .ko hit a
PCIe timing window — unlikely but not eliminable from code alone.

### Decision: try ONE more test.226 rerun as binomial discriminator

Three outcomes possible on this next rerun (boot 0 → boot -1 of next
session):

1. **Wedges at test.158 again (3/3)** — the wedge is reproducible at
   this flow point. Build test.227 that pivots to **durable logging**
   (netconsole or `earlyprintk=serial`) rather than more pr_emergs —
   if tail truncation is the real story, more breadcrumbs are wasted.

2. **Passes test.158 and reaches FW download** — 2/3 failure rate → it's
   stochastic with high incidence. test.226's 12 downstream breadcrumbs
   become useful again; interpret per the original decision tree
   (copy from the entry further down).

3. **Wedges somewhere different** — new information. Redesign from there.

Hypothesis to record for match-against: **I expect a wedge at test.158
again** (outcome 1). Reason: two identical runs hitting the same line
is stronger than one — Bayesian lean toward reproducible. If it passes,
I'll treat that as evidence of stochasticity and pivot test.227
accordingly.

### Hardware state on current boot 0 (19:55 onward, uptime ~1 min)

- `lspci -vvv -s 03:00.0`: Control `I/O- Mem- BusMaster-` (fresh post-boot,
  nothing enabled). MAbort-, SERR-, DEVSEL=fast. Clean.
- `enable=0`, `power_state=unknown`
- BAR0 `dd` wall-clock: 23 / 21 / 21 / 20 ms — fast-UR, well under 40 ms
- `lsmod | grep brcm`: empty
- `brcmfmac.ko` unchanged since 19:40 (same test.226 build; 12 markers
  present per `strings`)

### Run

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected artifacts:
- `phase5/logs/test.N.run.txt` (wrapper output)
- `phase5/logs/test.N.journalctl.txt` (grep-filtered)
- `phase5/logs/test.N.journalctl.full.txt` (whole boot, post-recovery)

If host wedges: capture via `sudo journalctl -k -b -1` from next boot.

---

## POST-TEST.226 (2026-04-22 19:45 BST, boot 0) — EARLIER wedge than test.225.rerun, NONE of the 12 breadcrumbs fired

### Headline

test.226 wedged at **`test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)`** —
about 19 s after insmod on boot -1 (19:41:23 → 19:41:42). Compare to boot -2's
test.225.rerun, which at the *same* flow point printed another ~10 lines of
test.158/test.188 setup markers before starting the chunked FW download
~10 s later. **None of the 12 test.226 breadcrumbs fired** — all are past
the wedge, deeper in `brcmf_pcie_download_fw_nvram`.

SMC reset **was** performed between boot -2 and boot -1 (confirmed earlier),
and again between boot -1 and boot 0. So boot -1 started from a clean post-SMC
state, identical to boot 0's current state. This is a regression from a clean
state, not a dirty-hardware artifact.

### Observed boot -1 journal (test.226)

Last good marker before wedge:
```
19:41:42 brcmfmac 0000:03:00.0: BCM4360 test.158: ARM CR4 core->base=0x18002000 (no MMIO issued)
(boot ends here — host wedged)
```

Full sequence from probe to wedge (14 kernel lines) is intact:
test.188 module_init → test.155 sdio → test.128 probe → test.127 devinfo →
test.53 SBR → chip_attach → test.218 core enum (6 cores) → test.125 buscore_reset →
test.122 reset bypass → test.145 ARM CR4 halt → test.188 post-halt CPUHALT=YES →
test.121 raminfo → test.193 chip info + PMU WARs → test.224 max/min/post-settle
(pmustatus=0x2e res_state=0x7ff — clean) → test.119 chip_attach returned →
**test.158: ARM CR4 core->base** → wedge.

Compare boot -2 (test.225.rerun) from the same point:
```
test.158: ARM CR4 core->base  (same line)
test.158: about to pci_clear_master
test.158: BusMaster cleared after chip_attach
test.158: about to read LnkCtl before ASPM disable
test.158: LnkCtl read before=0x0143 — disabling ASPM
test.158: pci_disable_link_state returned — reading LnkCtl
test.158: ASPM disabled; LnkCtl before=0x0143 after=0x0140
test.188: root port 0000:00:1c.2 LnkCtl before=0x0040 — disabling L0s/L1/CLKPM
test.188: root-port pci_disable_link_state returned
test.188: root port 0000:00:1c.2 LnkCtl after=0x0040
(10 s gap — test.188 setup-entry / pre-attach / post-attach / post-raminfo / pre-download)
test.188: starting chunked fw write, total_words=110558
test.225: wrote 1024 words — full download through to post-snapshot
```

### What this rules out and what it means

- **Not caused by test.226 code changes.** The 12 breadcrumbs are all inside
  `brcmf_pcie_download_fw_nvram`, which is reached only AFTER the chunked FW
  download. The wedge on boot -1 was before any of that, right after
  `brcmf_chip_attach` returned.
- **Not dirty hardware.** SMC reset between -2 and -1 was performed; boot -1's
  pre-insmod state was clean (per the 19:25 PRE entry below).
- **Candidates for the regression**:
  1. Flaky one-off — PCIe link renegotiation / ASPM state / PMU settle hit a
     bad window this run that cleared on retry.
  2. Something nondeterministic in the probe path that lands on this wedge
     some-fraction-of-the-time.
- **Rerun is the right discriminator.** test.226's 12 breadcrumbs are dead
  weight against *this* failure mode — they only help if the wedge recurs in
  the post-CC-res_state block. If the rerun wedges at test.158 again, pivot
  to test.227: drop breadcrumbs between `test.158: ARM CR4 core->base` and
  `test.158: about to pci_clear_master` (small gap on boot -2 — narrow
  window to instrument).

### Hardware state on current boot 0 (19:45 onward)

- `lspci -vvv -s 03:00.0`: `I/O- Mem+ BusMaster+` (BIOS residual).
  MAbort-, SERR-, DEVSEL=fast — clean.
- `enable=0`, `power_state=unknown`.
- BAR0 `dd resource0` timing: **21 / 20 / 20 / 19 ms** (fast-UR regime,
  well under 40 ms threshold).
- `lsmod | grep brcm`: empty.

Ready to rerun test.226 .ko as-is.

---

## PRE-TEST.226 RERUN (2026-04-22 19:45 BST, boot 0) — same .ko, cheapest next step

### Objective

Rerun the existing test.226 .ko with no code changes. Two possible outcomes:
- **Reaches FW download + breadcrumbs fire** → the boot -1 regression was a
  flake; proceed as originally planned, interpreting the 12 breadcrumbs per
  the decision tree below.
- **Wedges at test.158 again** → regression is reproducible; pivot to test.227
  with breadcrumbs in the post-chip_attach / pre-pci_clear_master gap.

### Build state

- `brcmfmac.ko` dated 19:40, 14.27 MB — unchanged since test.226 built.
- No rebuild needed.

### Run

```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

### Hardware risk

Identical to the original test.226 pre-plan. Chip is in a verified-clean
state. Worst case is another wedge, host recovery via next SMC reset (done
twice already this session, confirmed reliable).

### Breadcrumb decision tree (if download is reached this time — unchanged from original)

| Last test.226 marker emitted | Interpretation | Next |
|---|---|---|
| "before `brcmf_chip_get_core`" but not "after" | impossibly early — log flush issue, not real wedge | rethink flush budget; add mdelay(100) instead of msleep(5) |
| "after brcmf_chip_get_core" / pre-set-active probes but not pci_set_master | wedge on ARM CR4 / D11 wrapper MMIO read | look at select_core left from prior readbacks |
| "before pci_set_master" but not "after" | config-space write wedged PCIe link | check AER / root-port state; may need separate probe |
| FORCEHT write visible, set_active marker not | wedge in FORCEHT path (unlikely; test.219 proved this works) | n/a |
| `brcmf_chip_set_active returned` visible, tier1 not | wedge in firmware execution — real behavior, not probe artefact | move to tier1 response debugging; compare against test.218 tier1 outcomes |
| All markers through tier1 visible, host wedges later | wedge is in dwell or D11 bring-up — reset plan to deeper window | design test.227 around the later probe set |

### Pre-test checks — DONE

- Build is fresh (test.226 .ko, unchanged from pre-test.226-original).
- `lspci -vvv -s 03:00.0` clean (no MAbort/SERR).
- BAR0 dd 19-21 ms — fast-UR regime.
- `lsmod | grep brcm` empty.

---

## POST-TEST.225 RERUN (2026-04-22 19:29 BST, boot -2) — JACKPOT: full 442 KB firmware download + TCM verification, host wedged in post-snapshot / set_active block

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

## PRE-TEST.226 READY (2026-04-22 19:42 BST) — build + state verified, insmod next

### Build state
- `brcmfmac.ko` rebuilt at 19:40, 14.27 MB
- `strings` counts 12 × `BCM4360 test.226:` markers in the binary
- No new warnings from the kbuild run

### Hardware state immediately before insmod
- `lspci -vvv -s 03:00.0`: MAbort-, SERR-, DEVSEL=fast
- `enable=0`, `power_state=unknown`
- BAR0 `dd resource0` timing: 21 / 19 / 19 ms — fast-UR, well under 40 ms
- `lsmod | grep brcm`: empty

Hypothesis: one of the 12 test.226 markers will print and the next one
won't — pinpointing the wedge location within the ~100-line block
between CC-res_state and the first tier1 probe. If all 12 print, the
wedge is downstream of set_active (in tier1 dwell or firmware-resume
handling) and test.227 will walk breadcrumbs into that region.

### Run
```bash
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

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

## PRE-TEST.192 (2026-04-22) — apply chip_pkg=0 PMU WARs (chipcontrol #1 + pllcontrol #6/7/0xe/0xf)

**Status:** chip.c edited, module built clean, NOT YET TESTED on hardware.

### Hypothesis

test.188 baseline (uncommitted in test.191 logs) gets past probe to
firmware download but the firmware stalls with all TCM/D11 scratch
regions marked UNCHANGED. Our current best guess for why: Apple
BCM4360 has `chip_pkg = 0`, so it takes the bit-0x20-CLEAR branch of
`si_pmu_res_init`, which executes a sequence of PMU WAR writes that
brcmfmac has never performed. Without those writes some PMU/PLL
resource never asserts HT-avail, so the firmware never starts.

### What test.192 adds to test.188 baseline

In `brcmf_chip_setup` (chip.c:1134+), **after** `pmucaps`/`pmurev` have
been read but **before** bus-core setup, for `BCM_CC_4360_CHIP_ID &&
cc->pub.rev > 3`:

1. `chipcontrol #1 |= 0x800` (RMW via 0x650/0x654 addr/data pair)
2. `pllcontrol_data = 0x080004e2` at index 6     (0x660/0x664)
3. `pllcontrol_data = 0x0000000e` at index 7
4. `pllcontrol_data = 0x080004e2` at index 0xe
5. `pllcontrol_data = 0x0000000e` at index 0xf

**Offset-naming note:** wl.ko's symbol names call the 0x660/0x664 pair
"regcontrol" in some places, but Linux `struct chipcregs` reserves
that name for 0x658/0x65c and uses `pllcontrol_addr/_data` for
0x660/0x664. The writes in test.192 use the Linux field names
`pllcontrol_addr/_data` to target the hardware offsets 0x660/0x664
that wl.ko actually writes. See `phase6/wl_pmu_res_init_analysis.md`
§0.1 for the naming-collision table.

### Expected outcomes

| Outcome | Interpretation | Next step |
|---|---|---|
| TCM or D11 scratch region shows CHANGED bytes in dump | WARs were blocking firmware; PMU WAR set is necessary | Follow firmware progress; may need further PMU/PLL work |
| All scratch regions still UNCHANGED, clean -ENODEV exit | WARs didn't unblock firmware; something else missing | Revisit PCIe2 init (DLYPERST/DISSPROMLD) or min/max_res_mask 0x1ff widening |
| Hard crash during probe | PMU write triggered a fault before firmware download | Bisect the 5 WAR writes one at a time |
| New error in dmesg (e.g. PMU timeout) | WAR changed PMU state enough to unblock but something else hits a ceiling | Inspect error location |

### Build status

- `chip.c` updated with `pllcontrol_addr`/`_data` field names (was
  incorrectly using `regcontrol_*` in earlier draft — that would have
  targeted 0x658/0x65c which is the wrong register pair).
- `make -C $KDIR M=...brcmfmac modules` → clean build, no warnings.
- `brcmfmac.ko` rebuilt at
  `/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko`.

### Pre-test checklist (from CLAUDE.md)

1. Build status: REBUILT CLEAN (just now)
2. PCIe state check: not run yet — user should verify before test:
   `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
3. Hypothesis stated: see above.
4. Plan committed and pushed: (this commit)
5. Filesystem sync: included in commit step.

### Run command

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected log: `phase5/logs/test.192` (or `test.192.journalctl.txt`
with full journal).

---

## POST-TEST.191 (2026-04-22) — CHIP IS HEALTHY; live PMU state invalidates test.189 mask values

Captured: `phase5/logs/test.191.journalctl.txt` (current-boot dump, 972
lines). **No crash.** Module loaded, traversed the full test.188 path,
reached `dwell-3000ms` fine-grain tier, returned -ENODEV (skip_arm=1).
PCIe clean post-test, module unloaded cleanly.

### Decision-tree outcome: "chip healthy" branch

All milestone probes fired in order:
- `halt ARM CR4` → `halt done` (1 s later — slow but successful)
- `chip_attach returned successfully`
- `setup-entry`, `pre-attach`, `post-attach` probes all fired
- `download_fw_nvram` returned `-19` (ENODEV, expected skip_arm=1 exit)
- Module unloaded cleanly, lspci clean

Conclusion: the test.190 early crash at `halt ARM CR4` was NOT a
persistent chip-state problem. Either post-SMC-reset state was
genuinely bad at that moment and has since cleared, OR the
test.189/190 build somehow influenced behavior before the PMU writes
ran (unlikely — but not fully ruled out). Either way, we now have a
working baseline to continue from.

### CRITICAL finding: chip sets its own PMU res_masks

Pre-release snapshot (host did NO PMU writes) on BCM4360:
```
CC-pmucontrol = 0x01770181
CC-pmustatus  = 0x0000002a
CC-res_state  = 0x0000013b   ← resources 0,1,3,4,5,8 enabled
CC-min_res_mask = 0x0000013b ← firmware-set default (NOT 0x103!)
CC-max_res_mask = 0x0000013f ← firmware-set default (NOT 0x1ff!)
```

After 3 s dwell:
```
CC-pmucontrol = 0x01770381 (bit 0x200 set = NOILPONW toggled ON)
CC-min_res_mask = 0x0000013b (unchanged — firmware isn't overwriting)
CC-max_res_mask = 0x0000013f (unchanged)
```

**Implications**:
1. test.189's `min_res_mask=0x103` was *removing* resources 3, 4, 5
   (which the chip's own firmware relies on). That write was actively
   harmful, not helpful. This likely explains why test.189 hung.
2. test.189's `max_res_mask=0x1ff` was a superset of 0x13f — should
   have been benign in isolation.
3. test.189's NOILPONW write was trying to force a bit the firmware
   sets on its own ~3 s after attach. Likely redundant at best.
4. Gemini re-anchor cc5d525 of the wl disassembly — the 0x103 and
   0x1ff masks attributed to the BCM4360 path — is WRONG for this
   chip. Either they belong to a different code path, or the
   anchoring was off-by-one. Needs re-investigation before any more
   PMU writes are added.

### What this means for the PMU-bisect plan
Abandon the test.189/190 bisect direction entirely. The Option-A/B/C
plan in POST-TEST.189 is based on wrong target values. We now have
ground truth from the live chip:
- min_res_mask target = **0x13b** (not 0x103, not 0x101)
- max_res_mask target = **0x13f** (not 0x1ff)
- NOILPONW = managed by firmware; host write is not required

### Next step — test.192 direction
Two candidates:

**A.** Write the *correct* masks (0x13b / 0x13f) from chip.c and
observe whether firmware progresses past its idle loop. This is the
one-variable-at-a-time change. If firmware still idles, host-side
PMU writes are not the missing piece. If firmware advances, we've
found part of the fix.

**B.** Revisit the actual test.188 blocker — firmware sits in a
spin loop / exception handler. The 3-second dwell showed NO TCM
changes (all `UNCHANGED` in the sampled range) and no D11
progression. The missing piece is probably NOT PMU at all — it's
whatever mailbox/doorbell the firmware expects before advancing.
Revisit `phase6/wl_pmu_res_init_analysis.md` to audit whether we
mis-anchored other parts of the wl disassembly too.

Recommend **B first** (a re-anchoring audit) to avoid another round
of wrong-target writes before the next hardware test.

### Files
- Log: `phase5/logs/test.191.journalctl.txt`
- Baseline anchor: search for "CC-min_res_mask" — first pre-release
  snapshot line (around line 452)

---

## PRE-TEST.191 (2026-04-21) — revert to test.188 baseline for chip-state sanity check

### Rationale
Test.190 hung at `halt ARM CR4` — a point test.188 traversed in ~3 ms
and where the test.190 code change (min_res_mask removal) cannot have
executed yet. Timestamps in test.190 also showed ~500 ms between every
printk, pointing to systemic slowness (dirty PCIe or kernel throttle).
Before resuming the PMU bisect we need a **clean baseline sanity check**
to decide whether the chip/PCIe is still healthy after two hard-crash
+ SMC-reset cycles.

### Change
`git checkout 2c23fc9^ -- phase5/work/.../chip.c phase5/work/.../pcie.c`
— reverts *only* the two source files that test.189/test.190 modified,
back to the test.188 state. RESUME_NOTES and everything else untouched.

### Build status
Rebuilt 2026-04-21, clean (only the pre-existing
`brcmf_pcie_write_ram32 defined but not used` warning remains).

### PCIe state pre-test
`lspci -vvv -s 03:00.0` is clean: `<MAbort-`, no `>TAbort`, no SERR.

### Hypothesis for test.191
Test.191 runs the exact code test.188 ran. Outcomes:

| Outcome | Interpretation | Next move |
|---|---|---|
| Reaches `pre-attach`/`post-attach`, exits -ENODEV (like test.188 did) | Chip is healthy. test.190 early crash was driven by the remaining PMU writes (NOILPONW / max_res_mask=0x1ff) or subtle timing. | Retry Option-A with fresh bisect. |
| Hangs at `halt ARM CR4` again | Chip is in persistent post-SMC-reset bad state. SMC reset is insufficient. | Full power cycle (battery drain) before any further testing. Code bisect cannot conclude on current chip. |
| Hangs at some *other* new point | Further diagnostic needed — capture and analyze. | Document and reconsider. |

### Expected observations if healthy (matches test.188)
- brcmfmac loads, chip_attach returns (halt ARM CR4 completes in ms)
- `setup-entry` probe fires: IOCTL=0x21, CPUHALT=YES
- firmware request succeeds (async via udev)
- `pre-attach` probe fires
- `post-attach` probe fires
- download_fw_nvram returns -ENODEV (skip_arm=1 path)
- Module unloads cleanly, lspci still clean

### Next step
User runs test.191 (`phase5/work/test-brcmfmac.sh`). Capture
journalctl to `phase5/logs/test.191.journalctl.txt`, update this file.

---

## POST-TEST.190 (2026-04-21) — hard crash EARLIER than test.189, at halt ARM CR4; min_res_mask bisect inconclusive

Captured: `phase5/logs/test.190.journalctl.txt` (prior-boot dump, 1077
lines). Host hard-froze at 23:46:17 BST (during `buscore_reset`);
required SMC reset. PCIe state clean post-reset (`<MAbort-`).

### Crash sequence
Last brcmfmac kernel line (both boots hung immediately after):
```
23:46:17.207 brcmfmac 0000:03:00.0: BCM4360 test.145: halting ARM CR4 after second SBR (buscore_reset)
```

No "ARM CR4 halt done" followup, no Oops, no MCE logged before the
hang. Hard freeze requiring SMC reset.

### Why this is surprising
The only code diff between test.189 and test.190 is dropping the
`min_res_mask = 0x103` write in `brcmf_chip_setup`. That write runs
*later* in the flow than the hang point — `brcmf_chip_setup` is
called from `brcmf_chip_recognition` after `brcmf_chip_attach`, while
the halt ARM CR4 is inside `buscore_reset` which runs *before*
chip_attach returns. So the bisect change cannot logically account
for the earlier crash location.

Test.188 (no PMU writes at all) traversed the same halt ARM CR4 step
in ~3 ms (dmesg `[57629.418085]` → `[57629.421031]`).
Test.189 traversed it sub-second in journalctl too.
Test.190 got stuck *at* that step.

### Additional signal: printk deltas
Every brcmfmac log line in test.190 is spaced **~500-585 ms** from
the previous one — uniformly, even for in-kernel-only code that
should execute in microseconds (e.g. 528 ms between
`brcmf_core_init entry` and `before brcmf_sdio_register`). In
test.188 these same transitions are sub-millisecond. Something is
systemically slowing every printk or every in-kernel step by ~500 ms.

### Gemini's top 3 hypotheses (in likelihood order)
1. **Dirty PCIe/root-port state post-SMC-reset.** MMIO to the chip
   or PCIe link is hitting silent retries, stalling everything. The
   chip hangs at halt ARM CR4 independent of our code change.
2. **Kernel RCU/softlockup throttling** triggered by slow MMIO —
   kernel applies ~500 ms scheduling penalties.
3. **Hardware watchdog inside the chip** fires while driver is slow,
   terminating the session before chip_attach completes.

(1) is most consistent with the symptoms — the slowness is uniform
across ALL init lines (not just MMIO-adjacent ones), suggesting
kernel-level delay, but the host was also running on just-post-
SMC-reset state where PCIe Root Port may have been in a degraded
link (not an MAbort-visible fault but a slower-retry mode).

### Interpretation
- Option-A bisect is **inconclusive**. We cannot tell whether
  `min_res_mask=0x103` was the test.189 trigger because test.190
  hit a *different* failure before the diff mattered.
- The crash is happening in a code path that test.188 passed
  cleanly. That means either (a) environmental slowness (bad PCIe
  state, warm chip, prior-test residue) is the real story, or (b)
  the NOILPONW / max_res_mask writes have a latent side-effect that
  manifests at the next MMIO even after chip_attach returns — but
  that's a stretch given chip.c layout.

### Recommended next step — back out to known-good baseline first

Before touching more PMU writes we need a **clean test.188 re-run**
(no chip.c PMU writes, no pcie.c PCIe2 port code) to confirm the
baseline is *still* stable after the two hard crashes + SMC resets.

- If test.188 re-run succeeds (reaches post-attach, -ENODEV exit):
  the chip/PCIe is healthy; test.190's early crash was driven by
  the PMU writes (NOILPONW or max_res_mask) or by chip state that
  test.188's code path tolerates but test.190's doesn't. Then retry
  Option-A (min_res_mask removed) again — if it crashes the same
  way twice, we have a reproducible signal.
- If test.188 re-run also crashes: the chip is in a persistent bad
  state (possibly a firmware-side latch) and we need a full power
  cycle / battery drain rather than SMC reset. That rules out any
  code-level bisect conclusion for now.

Call this **test.191 = revert to test.188 code, rebuild, re-run as
baseline sanity**.

### Files
- Log: `phase5/logs/test.190.journalctl.txt`
- Crash analysis anchor: search for "halting ARM CR4" — last brcmfmac line

---

## PRE-TEST.190 (2026-04-21) — Option-A bisect: drop min_res_mask only, rebuilt clean

Module rebuilt 2026-04-21 after test.189 crash, clean (only pre-existing
`brcmf_pcie_write_ram32 defined but not used` warning remains).

### Change vs. test.189 (one file, one hunk)
`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c`
`brcmf_chip_setup` ~line 1131: removed `min_res_mask = 0x103` write.
NOILPONW (pmucontrol bit 9) and `max_res_mask = 0x1ff` both kept —
neither asserts a live resource request. PCIe2 port code in pcie.c
is unchanged (never reached in test.189, so not the suspect).

### PCIe state pre-test
`lspci -vvv -s 03:00.0` shows clean: `<MAbort-`, no `>TAbort`, no SERR.

### Hypothesis for test.190
If test.189 crash was caused by `min_res_mask=0x103` (active request
for resources 0/1/8) wedging the PMU state machine, test.190 should
behave like test.188 — firmware idle but host stable, and reach
`pre-attach` / `post-attach` probes successfully, then EXIT with
-ENODEV (BCM4360 skip_arm=1 path). If test.190 also crashes, the
NOILPONW or max_res_mask write is the trigger instead (unlikely
since neither drives resources on).

### Expected observations
- brcmfmac loads, chip_attach returns
- `setup-entry` probe: IOCTL=0x21, CPUHALT=YES (same as test.188/189)
- `pre-attach` probe fires — the new success signal vs test.189
- `post-attach` probe fires
- download_fw_nvram runs, returns -ENODEV (skip_arm path)
- Module unloads cleanly, host stable, lspci still clean

### Next step
User runs test.190 (`phase5/work/test-brcmfmac.sh`). Capture journalctl
to `phase5/logs/test.190.journalctl.txt`, update this file.

---

## POST-TEST.189 (2026-04-21) — hard crash at 23:36:16 during brcmf_pcie_setup; PMU writes implicated (PCIe2 port not reached)

Captured: `phase5/logs/test.189.journalctl.txt` (prior-boot dump, 1593
lines). Host hard-froze after "setup-entry" probe at 23:36:16 BST;
required SMC reset. PCIe state clean post-reset (`<MAbort-`).

### Crash sequence
- 23:36:07 module load
- 23:36:11 `brcmf_chip_attach` returned successfully — this is where
  the test.189 PMU writes execute inside `brcmf_chip_setup`:
  NOILPONW (pmucontrol bit 9), `max_res_mask=0x1ff`, `min_res_mask=0x103`
- 23:36:11–23:36:15 async fw request, alloc, etc. (no MMIO activity)
- 23:36:16 `brcmf_pcie_setup` CALLBACK INVOKED ret=0
- 23:36:16 `setup-entry` probe: **ARM CR4 IOCTL=0x00000021 IOSTATUS=0
  RESET_CTL=0 CPUHALT=YES** (MMIO still works here — same as test.188)
- (next expected print: `pre-attach` probe after `msleep(300)`,
  never appears in journal — hard hang, no further kernel output)

### Interpretation
- The crash occurred **before** `brcmf_pcie_attach` was called. The
  only log line is the existing `setup-entry` probe; the subsequent
  `msleep(300)` and `pre-attach` probe never complete.
- Therefore the new PCIe2 port code in `pcie.c` (resetcore, DLYPERST
  WAR, LTR WAR, PM clock, PMCR_REFUP, SBMBX) **cannot be the trigger**
  — it is never executed.
- The trigger must be the `chip.c` PMU writes done at 23:36:11. They
  appear stable for ~5 seconds (chip_attach returns, fw request runs,
  setup callback's first probe still works), then something internal
  to the chip reaches a state that wedges the PCIe link during the
  300 ms msleep or the next MMIO.
- Plausible root cause: setting `min_res_mask = 0x103` asserts a live
  request for resources 0 (ALP), 1 (HT), 8 (unknown). Resource 8's
  timer/dependency value is `0x00000000` in the wl resource table
  (`phase6/wl_pmu_res_init_analysis.md` §2) — i.e. we asked the PMU
  to power up a resource that needs no dependencies, which may be a
  resource the chip doesn't want enabled this early. HT clock request
  requires the package-ID WARs (bit 0x20 branch, see §6) that test.189
  did not port — if those WARs gate the regulator programming, the
  request hangs the PMU state machine.

### Next-step options (bisect before next hardware test)
A. **Narrow to min_res_mask only.** Keep NOILPONW and `max_res_mask=0x1ff`
   (neither drives resources on), drop the `min_res_mask=0x103` write.
   If the crash disappears, confirms active resource request is the
   trigger. Cheapest experiment.
B. **Change min_res_mask to 0x101** (ALP + HT only, no bit 8). If A
   passes and we still want to drive HT, try the 2-bit mask next.
C. **Port the bit-0x20 package-gate WARs** (regcontrol #6/#0xe writes,
   per §6.2 corerev<=3 branch) before setting min_res_mask, if they
   turn out to be prerequisites for the HT request to complete.
D. **Disable all chip.c PMU writes**, re-enable just the pcie.c PCIe2
   port to test whether that code alone is safe. This is test.188 + pcie.c
   port only — useful as a clean baseline for PCIe2 port verification.

### Recommendation
Option A is the minimal, cheapest bisect. If it runs to the same
firmware-idle result as test.188, we have proof the PMU writes (not
the PCIe2 port) are what crashes. Then try B, then C. Defer D unless
A–C all fail.

### Files
- Log: `phase5/logs/test.189.journalctl.txt`
- Crash analysis anchor: search for "setup-entry" — last brcmfmac line

---

## SESSION RESUME (2026-04-21, post-crash + SMC reset)

Host was crashed by test.189; user performed SMC reset before this
session. `lspci -vvv -s 03:00.0` shows clean state: `<MAbort-`,
no `>TAbort`, no SERR. Module in `phase5/work/.../brcmfmac/` is the
test.189 build (commit 950599d). See POST-TEST.189 above for analysis.

## PRE-TEST.189 (2026-04-21) — conservative PMU + PCIe2 port, built clean

Module rebuilt 2026-04-21, clean (only pre-existing
`brcmf_pcie_write_ram32 defined but not used` warning remains).

**Rebuilt again 2026-04-21 after PCIe2-reset fix** — see "Crash-risk
mitigation" below.

### Crash-risk mitigation (added 2026-04-21 before first run)

Initial port did BAR0 MMIO to the PCIe2 core in `brcmf_pcie_attach`
without first bringing it out of BCMA reset. That is exactly the
test.129 crash pattern ("*PCIe2 core is in BCMA reset at this point,
so any BAR0 MMIO to it causes CTO → MCE → hard crash*").

Fix (one line, `pcie.c` inside the BCM4360 branch of
`brcmf_pcie_attach`, immediately after `brcmf_chip_get_core` null
check):

```c
brcmf_chip_resetcore(core, 0, 0, 0);
```

`bcma`'s own `pcie2` init runs after `bcma_core_setup` which
releases the core from reset implicitly. `brcmfmac` does not reset
PCIe2 elsewhere, so we do it explicitly here before the first MMIO.
Matches the standard pattern used at chip.c:608 (SR), :666 (sysmem),
:1312 (D11). Module rebuilt clean after this addition.

**Build command** (correction — CLAUDE.md's `make -C phase5/work` is wrong;
there's no top-level Makefile there):
```
make -C /lib/modules/$(uname -r)/build \
     M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac \
     modules
```

**PCIe state** (`lspci -vvv -s 03:00.0`): clean — `<MAbort-`, no dirty
state from prior crash.

### Files changed (vs. test.188)
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c`
  `brcmf_chip_setup` ~line 1102: BCM4360 branch adds NOILPONW write
  (rev-dependent per bcma_pmu_init), max_res_mask=0x1ff,
  min_res_mask=0x103 (matches wl per Gemini re-anchor cc5d525).
- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`
  `brcmf_pcie_attach` ~line 885: replaces BCM4360 early-return with
  bcma_core_pcie2_init port — DLYPERST WAR (dead code for chiprev=3
  but kept for parity), LTR WAR, PM clock period, PMCR_REFUP, SBMBX.
  `brcmf_pcie_exit_download_state` ~line 1024: adds pmustatus bit-2
  (PST_HTAVAIL) poll for BCM4360 before brcmf_chip_set_active.

Full diff + rationale: `phase5/notes/test_189_implementation_plan.md`
(commit cd169ac). All magic numbers verified against bcma source.

### Hypothesis for test.189

Firmware stalls in test.188 because brcmfmac never performs the PMU
and PCIe2 prerequisites bcma does. Four layers are introduced at
once; the observation pattern decides which was the blocker:

| Layer becomes active | Expected observable if this was the blocker |
|---|---|
| PMU_CTL (NOILPONW) | test.188's firmware-idle signature disappears (any TCM/D11/mailbox change) |
| PCIe2 core init | D11 leaves reset (RESET_CTL=0) or mailbox fires |
| res_masks (min=0x103 / max=0x1ff) | `pmustatus` bit 2 (HAVEHT) reaches 1; firmware advances |
| HT poll pre-set_active | Previous intermittent progress becomes repeatable |

`0x3fffffff` mask override explicitly excluded — Gemini re-anchor
cc5d525 refuted it for BCM4360 (belongs to BCM4314 path in
si_pmu_chipcontrol, not us).

### Next step
User runs test.189 (`phase5/work/test-brcmfmac.sh`) per CLAUDE.md
post-test procedure. Capture journalctl, update this file with
observations against the hypothesis table above.

---

## POST-TEST.188 (2026-04-21) — firmware truly idle; fine-grain tiers + integrity check both NULL; exception/spin-loop confirmed

Captured artifacts:
- `phase5/logs/test.188.stage0`
- `phase5/logs/test.188.stage0.stream`
- `phase5/logs/test.188.stage0.raw.log`
- `phase5/logs/test.188.journalctl.txt` (1046 lines)

Result: **clean run, host stable, returned -ENODEV as designed.**
Module build re-verified clean (frame-size warning resolved; only
pre-existing `brcmf_pcie_write_ram32 defined but not used` warning
remains). Test ran with tier-1/tier-2 ordered BEFORE the coarse dwell
per option 2(a).

### Observations

Firmware image was released (CPUHALT YES→NO at 20 ms post-set_active).
After that point, **zero changes** were observed across the entire
monitoring window up to 3000 ms:

| Probe | Time Window | Result |
|---|---|---|
| ARM CR4 (IOCTL/IOSTATUS/RESET_CTL) | 20ms → 3000ms | **IDENTICAL every sample**: IOCTL=0x01, IOSTATUS=0x00000000, RESET_CTL=0x00 |
| D11 wrapper | 20ms → 3000ms | **UNCHANGED**: IOCTL=0x07, RESET_CTL=0x01 (never released) |
| TCM[0x0000..0x001C] (8 dwords) | dwell-3000ms | **ALL UNCHANGED** |
| Wide-TCM (15 points: 0x00000..0x60000) | dwell-3000ms | **ALL UNCHANGED** |
| Tail-TCM (14 dwords: ramsize-64..ramsize-4) | dwell-3000ms | **ALL UNCHANGED** |
| NVRAM marker (ramsize-4) | dwell-3000ms | **UNCHANGED** 0xffc70038 |
| 256-point firmware integrity | dwell-3000ms | **ALL MATCH** (TCM readback == fw->data) |
| Tier-1 CR4/D11 fine-grain | ~100-150ms | **ALL IDENTICAL** (no transient) |
| Tier-2 CR4/D11 fine-grain | ~150-1650ms | **ALL IDENTICAL** (no transient) |
| Tier-1 fw-integrity subset | ~100-150ms | **ALL MATCH** |
| Tier-2 fw-integrity subset | ~150-1650ms | **ALL MATCH** |
| CC backplane (8 regs) | dwell-3000ms | clk_ctl_st UNCHANGED; pmucontrol bit-9 flipped (0x01770181→0x01770381, expected); pmustatus UNCHANGED; pmuwatchdog=0; all others UNCHANGED |
| mailboxint (final) | end | 0x00000000 — no doorbells |
| pci_clear_master | end | PCI_COMMAND=0x0002 (BM OFF); MMIO guard responsive |

**Critical:** `IOSTATUS=0x00000000` at every tier sample. The ARM CR4
wrapper reports **no fault/error bits**. This rules out an exception
handler that writes a wrapper-level status register — the spin-loop
must be a *clean infinite loop*, not an active fault state visible
through the BCMA AI wrapper.

**Additional finding — fw[0] is the reset vector:**
`fw-sample[0x00000] = 0xb80ef000 vs 0xb80ef000 MATCH`. The first 32-bit
word of the firmware image IS `resetintr` (0xb80ef000). This is the
ARM's boot-time jump target. `brcmf_chip_set_active` writes this value
into a CR4 register so the ARM boots from 0xb80ef000. That VA is at
TCM offset 0xef000, but ramsize = 0xa0000 so this VA lies **outside
TCM** — most likely in IMEM (2 MB BAR2 region beyond TCM) or a CR4
internally-mapped region. This explains why test.187's probe A (reading
TCM at offset 0xef000) read garbage / out-of-range.

### Hypothesis Assessment
- **Firmware-integrity 256 MATCH:** download-path corruption **FALSIFIED**
- **Tier-1/tier-2 ALL UNCHANGED:** firmware makes **zero observable
  progress** in the ~100–1650 ms window. Previously could have been
  missed by 500/1500/3000 grid — that possibility now eliminated.
- **IOSTATUS=0x00000000:** wrapper-level exception **not visible**.
  Firmware either (a) stuck in clean infinite loop (no MMIO, no TCM
  writes, no exception status bits); or (b) faulting at a hardware
  level that doesn't update wrapper registers.
- **All TCM/D11/NVRAM/mailboxint UNCHANGED:** firmware has written
  nothing, sent no doorbells, released no cores.

### Conclusion
ARM is released, clock is ticking (PMU clock advances), but firmware
makes zero forward progress. The fine-grain window (~100–1650 ms)
eliminates the possibility that firmware makes a brief advance and
stalls between the old 500/1500/3000 ms sampling grid points.

### Next steps — ranked

Every currently-testable hypothesis at this probe granularity has been
falsified. Further progress requires moving to a different observation
modality. Options in rough order of effort-vs-yield:

**B. Clean-room cross-reference of proprietary `wl` driver reset sequence**
vs `brcmf_chip_set_active`. The ARM faults within <20 ms of release —
almost always means a missing prerequisite register write. BCM4360 has
a complex PMU/PLL bring-up. Document the register writes `wl` performs
between firmware download and ARM release that brcmfmac does not,
then re-implement clean. Legally safest and likely highest yield.
Constraint: `wl` fails to load on this host kernel 6.12.80 per
PLAN.md §Tools, so dynamic tracing may need an older kernel / sibling
machine; static disassembly + string analysis remains viable here.

**F. OpenWrt / kernel-fork survey for BCM4360 quirks.** Cheap search
through known downstream patches (OpenWrt, Asahi Linux, Broadcom SDK
leaks) for BCM4360-specific init register writes missing from upstream
brcmfmac. Concrete, testable diffs.

**C. IMEM / reset-vector inspection via BAR2 beyond TCM.** BAR2 is 2 MB;
TCM fills the low 640 KB (ramsize). The remaining 1.4 MB of BAR2 may
map IMEM or CR4-internal memory that includes VA 0xb80ef000. Attempt a
short read-only BAR2 sample at offset 0xef000 (above ramsize) pre- and
post-set_active. If it reads valid instruction bytes, we gain direct
visibility into firmware's reset-vector region. If it reads 0xffffffff
/ CTO, we learn that IMEM is not BAR2-mapped on this chip.

**A. ARM architectural fault registers (DFSR / IFSR / DFAR / IFAR).**
Would give direct fault type + address, definitively identifying the
failing instruction. Requires reaching CR4 coprocessor regs through
either a CoreSight/DAP window or a wrapper route. Biggest research
project of the five; defer until B/F/C are exhausted.

**D. Firmware UART / serial console.** Broadcom firmwares can emit
diagnostic text over UART. GPIO mapping and voltage levels undocumented
for BCM4360 on Mac hardware; physical-layer risk. Low priority.

**Recommendation:** B and F in parallel (both are offline / research-
only; no host risk). C as a quick hardware probe once its safety is
confirmed (read-only, small window). A and D remain backlog.

---

## POST-TEST.186d (2026-04-20) — BusMaster ON before set_active made no difference; DMA-stall falsified; exception/spin-loop is the leading hypothesis

Captured artifacts:
- `phase5/logs/test.186d.stage0`
- `phase5/logs/test.186d.stage0.stream`
- `phase5/logs/test.186d.journalctl.txt` (449 lines)

Result: **clean run, host stable, returned -ENODEV as designed.**
`pci_set_master` executed BEFORE `brcmf_chip_set_active`
(PCI_COMMAND 0x0002 → 0x0006, BM bit set). MMIO guards before and
after both BM-on and BM-clear all succeeded. `brcmf_chip_set_active`
returned true in ~30 ms; `pci_clear_master` at the end left the
device responsive (post-BM-clear MMIO guard read succeeded).

### Observed behaviour (BusMaster-ON window from set_active through 3 s dwell)

| Signal                  | Pre-set-active         | Post-set-active 20 ms / 100 ms / 500 ms / 1500 ms / 3000 ms |
|-------------------------|------------------------|--------------------------------------------------------------|
| ARM CR4 IOCTL           | 0x21 (CPUHALT=YES)     | 0x01 (CPUHALT=NO) at every sample                           |
| ARM CR4 IOSTATUS        | 0                      | 0                                                            |
| ARM CR4 RESET_CTL       | 0                      | 0                                                            |
| D11 IOCTL               | 0x07                   | 0x07                                                         |
| D11 RESET_CTL           | 0x01 (IN RESET)        | 0x01                                                         |
| NVRAM marker @ rs-4     | 0xffc70038             | 0xffc70038 (UNCHANGED)                                       |
| TCM[0..0x1c]            | snapshot               | UNCHANGED at every offset, every sample                       |
| wide-TCM (0..0x9c000)   | snapshot               | UNCHANGED                                                    |
| tail-TCM (last 64 B)    | snapshot               | UNCHANGED                                                    |
| PCIE2 mailboxint        | 0x0                    | 0x0 (no D2H, no FN0 bits)                                    |
| CC clk_ctl_st           | 0x00050040             | 0x00050040                                                   |
| CC pmucontrol           | 0x01770181             | 0x01770381 (bit 9 flipped once → the test.184 one-shot)      |
| CC pmustatus            | 0x0000002a             | 0x0000002a                                                   |
| CC pmutimer             | monotonic              | monotonic (advances each sample, PMU alive)                  |
| CC res_state / res_mask | stable                 | stable                                                       |

### Interpretation — DMA-stall hypothesis falsified

This result is **byte-for-byte identical** to test.186b's passive
baseline. The *only* relevant difference between 186b and 186d is
that 186d held BusMaster ON through `brcmf_chip_set_active` and the
whole 3 s dwell, exactly as the test.64/65-era comments prescribed.

If firmware's first action were a PCIe DMA that failed without
BusMaster (the DMA-stall hypothesis), we would expect 186d to produce
at least *one* forward-progress signal: a TCM write, a D11 release,
an mbox bit, or at minimum an overwrite of the 0xffc70038 sharedram
marker slot. None of these occurred. BusMaster ON/OFF during the
critical window is behaviourally equivalent from firmware's point of
view. DMA-stall is no longer a credible explanation for the `brcmfmac`
failure on BCM4360. The periodic ~3 s crash cycle the test.64/65
comments blamed on missing BusMaster was almost certainly a *different*
failure mode specific to the Phase-4 full-attach path (msgbuf rings,
live DMA) and not relevant here.

### What the ARM is doing

The ARM came out of halt (CR4 IOCTL bit 0x20 cleared by set_active)
and ran for ≥ 3 s with zero visible effect. Possible explanations,
in rough order of likelihood:

1. **Exception / spin-loop** — ARM hits a fault immediately after the
   first jump to `resetintr` (0xb80ef000) and enters an exception
   handler that either loops silently or spins on a fault condition
   that never clears. The firmware image may be validly loaded but
   dependent on a setup step `brcmf_chip_set_active` does not perform.
2. **Prerequisite poll** — firmware polls a specific register or
   memory word waiting for a host-driven "go" signal we haven't
   asserted. Candidates: host-driven mailbox beyond MAILBOX_0/1,
   a specific shared-RAM word the upstream-driver writes that we
   don't, a PMU resource not requested.
3. **Clock / PLL mismatch** — test.185+ keep the stock BBPLL
   configuration, but the proprietary Broadcom reset sequence may
   touch specific PMU resources before releasing the ARM. Our
   pmucontrol bit-9 flip happens; the rest of the PMU is quiet.

### Next probe candidates (in priority order)

A. **TCM instruction snapshot around `resetintr`** — read TCM at
   0xb80ef000 (rebased to TCM offset 0xef000) for ~256 bytes before
   and after set_active, and at dwell times. If the bytes are
   identical, either the ARM isn't fetching from there or it's not
   writing anywhere observable. Cheap, read-only, safe.

B. **Sample D11 mac_ctl + a few PMU resource bits repeatedly during
   the 3 s dwell** at finer granularity (every 20 ms) to catch any
   transient firmware action.

C. **Compare the `brcmf_chip_set_active` path with the original
   Broadcom `wl` reset sequence** (via code archaeology of the
   upstream brcmfmac vs proprietary wl driver cross-compiled for
   a testable kernel) to find any register write we're missing.
   This is the clean-room-safe approach: observe the proprietary
   driver's register writes, document the behaviour, re-implement.

D. **Check whether firmware image integrity survives the download
   path** — snapshot TCM[resetintr..resetintr+64] pre- and
   post-`brcmf_chip_set_active` to catch firmware self-modifying the
   reset vector region or any corruption introduced by the proprietary
   download helper.

Recommended first step: **A + D together** (cheap, additive, both
inform the exception-loop vs missing-prerequisite question).

---

## POST-TEST.187 (2026-04-20) — resetintr offset out of TCM range; no TCM writes; exception-loop hypothesis strengthened

Captured artifacts:
- `phase5/logs/test.187.stage0`
- `phase5/logs/test.187.stage0.stream`
- `phase5/logs/test.187.journalctl.txt` (to be captured)

Result: **clean run, host stable, returned -ENODEV as designed.**

### Observations
1. **resetintr offset calculation**: `resetintr_offset = 0xb80ef000 - 0xb8000000 = 0xef000`. This exceeds TCM size (`ramsize = 0xa0000`), so the resetintr vector lies outside TCM (likely in IMEM region). The probe skipped sampling due to range check.
2. **No TCM writes**: All sampled TCM regions (header, wide grid, tail) unchanged across dwell periods, identical to test.186d.
3. **ARM CR4 IOCTL**: CPUHALT cleared after `brcmf_chip_set_active`, ARM running but no visible activity.
4. **D11 still in reset**: RESET_CTL unchanged.
5. **PMU activity**: pmutimer monotonic, pmucontrol bit-9 flipped once (as before).
6. **No mailboxint activity**: No D2H or FN0 bits asserted.
7. **BusMaster ON before set_active** (as test.186d) still no DMA-stall evidence.

### Interpretation
- **Exception-loop hypothesis strengthened**: Firmware is not writing to TCM, not releasing D11, not asserting mailboxint, despite ARM being out of halt for ≥3 s. The resetintr vector is outside TCM, so we cannot yet inspect the instruction stream. Need to sample IMEM region.
- **Firmware image integrity**: Not yet probed (probe D pending). No corruption observed in sampled wide‑TCM grid (but only TCM region).
- **Next step**: Probe IMEM region around resetintr offset (0xef000) using BAR2 mapping (size 2 MB). Also implement firmware integrity check.

### Recommended next step
**test.188**: 
A. Sample IMEM region at offset 0xef000 (256 bytes) before and after set_active, ignoring TCM size limit (but ensure offset < 2 MB). 
B. Add firmware integrity check: compare wide‑TCM grid with original firmware data (probe D).
C. Keep BusMaster ON before set_active, skip_arm=1, -ENODEV return.

---
## PRE-TEST.187 (2026-04-20) — TCM instruction snapshot around resetintr + firmware integrity check

### Hypothesis
If firmware is stuck in an exception loop after `brcmf_chip_set_active`, the instructions at the resetintr vector (0xb80ef000) will remain unchanged across the dwell period. If firmware modifies its own code (self-modifying), we will see changes in the sampled region. Additionally, firmware image integrity will be verified by comparing sampled TCM regions with the original firmware data to detect corruption during download.

### Probe A: TCM instruction snapshot
- Sample 256 bytes at offset resetintr - 0xb8000000 (0xef000) before and after set_active, and at dwell times (500/1500/3000 ms).
- If offset out of TCM range, log warning and skip.

### Probe D: Firmware integrity check
- Compare sampled wide-TCM grid values with original firmware data; any mismatch indicates corruption during download.

### Expected outcomes
- No changes in resetintr region → supports exception-loop hypothesis.
- Changes in resetintr region → firmware is writing to its own code (unlikely).
- Corruption in firmware image → download path issue.
- No corruption → firmware image intact.

### Risk
Read-only probes; no additional risk beyond existing test.186d (BusMaster ON before set_active, skip_arm=1, -ENODEV return).

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```

## PRE-TEST.186d (2026-04-20, staged) — BusMaster on BEFORE set_active

### Hypothesis
test.64/65-era comments in pcie.c (lines 2725-2742 and 4033-4037)
establish that firmware's first action at startup is a PCIe DMA that
fails silently if BusMaster is off, causing a crash-restart loop
every ~3s. test.186b enabled BusMaster 3 s too late. This test
enables it *before* `brcmf_chip_set_active`, so firmware's first
DMA has a chance of succeeding.

### Prediction
- **If DMA-stall:** within the 3 s post-set_active window we expect
  at least one of — (a) any TCM write (any of 56 probed offsets
  CHANGED), (b) D11 RESET_CTL transitioning to 0x00, (c) sharedram
  pointer replacing our 0xffc70038 NVRAM marker, (d) mailboxint
  asserting a D2H bit (0x10000..0x800000), (e) more than one
  pmucontrol bit flipping over time.
- **If exception-loop:** the same test.186b post-BM baseline
  (D11 in reset, TCM unchanged, one pmucontrol bit-9 flip,
  pmutimer monotonic, otherwise silent). This would then fully
  rule out the DMA-stall hypothesis and make exception-loop the
  leading candidate.

### Risk
Phase-4B crashed the host with BusMaster on + full attach (msgbuf
rings set up, so firmware DMA targeted real structures). This test
does NOT set up rings — it stays in the skip_arm=1 / -ENODEV early
return path. Shared RAM contains only our firmware image and NVRAM;
any DMA pointer firmware reads from it is effectively garbage, which
the IOMMU (device is in group 8) will block. That should translate
the failure mode from "host MCE" to "firmware DMA-error retry".

Mitigations: (a) MMIO guard reads before and after set_active,
(b) total post-set_active observation ≤ 3 s, (c) `pci_clear_master`
before module return regardless of outcome.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```
PCIe pre-test: verify no MAbort+ on `lspci -vvv -s 03:00.0`.

---

## AMENDMENT to POST-TEST.186b (2026-04-20) — interpretation corrected; DMA-stall NOT falsified

On re-reading `pcie.c` around line 4020 the test.64/65-era comment
(from an earlier phase of this investigation) states:

> Enable BusMaster on BCM4360 endpoint BEFORE ARM release. …
> Without BusMaster the firmware cannot DMA to host memory — its
> PCIe2 DMA init fails every ~3s causing the periodic crash events
> we observed in test.58-63.

test.186b enabled BusMaster **3 seconds after `brcmf_chip_set_active`**,
by which time firmware's first DMA attempt had already failed.
Turning BusMaster on later cannot un-stick firmware that is already
in its DMA-failure / retry / panic loop. So 186b's "no response"
result is consistent with DMA-stall, not evidence against it.

The correct test is **test.186d**: `pci_set_master` *before* the
existing `brcmf_chip_set_active` call, keep skip_arm=1 + -ENODEV
early return, observe the same sample grid. If firmware now
progresses (TCM writes / D11 wrapper releasing / sharedram marker
replacing 0xffc70038 / D2H mailboxint bits asserting) → DMA-stall
confirmed. If still no change → exception-loop hypothesis
strengthens. `pci_clear_master` before module return, IOMMU group 8
gives secondary protection against any stray DMA.

The body of POST-TEST.186b below still describes the actual measured
signals (which remain valid as data); only the interpretation
—"DMA-stall effectively falsified"— is retracted.

---

## POST-TEST.186b (2026-04-20) — BusMaster enable does not unstick firmware; exception-loop is the leading hypothesis

Captured artifacts:
- `phase5/logs/test.186b.stage0`
- `phase5/logs/test.186b.stage0.stream`
- `phase5/logs/test.186b.journalctl.txt` (607 lines)

Result: **clean run, host stable, no crash. Firmware did not respond
to BusMaster being enabled for 100 ms.** All post-BM samples match the
test.186c/186a/185 passive baseline — D11 still in reset, TCM
unchanged, NVRAM marker unchanged, mailboxint=0x0 throughout. The only
signals remain test.184's one-shot pmucontrol bit-9 flip and the
monotonic pmutimer tick.

### BM transition

```
pre-BM       PCI_COMMAND=0x0002 BM=OFF  mailboxint=0x00000000
BM-on        PCI_COMMAND=0x0006 BM=ON
BM-on+50ms   mailboxint=0x00000000 UNCHANGED  D11 RESET_CTL=0x01  CR4 IOCTL=0x01
BM-on+100ms  mailboxint=0x00000000 UNCHANGED  D11 RESET_CTL=0x01  CR4 IOCTL=0x01
BM-cleared   PCI_COMMAND=0x0002 BM=OFF
post-BM-500ms  (all same as pre)  pmucontrol=0x01770381 (test.184 baseline)
post-BM-2000ms (all same as pre)  pmutimer keeps ticking
```

All three MMIO guards passed — endpoint remained responsive
throughout. No AER, no MCE, clean rmmod.

### Interpretation

With BusMaster on firmware had unimpeded access to host memory via
PCIe DMA. If the early stall were a "DMA attempt silently fails because
BusMaster is cleared" wait, enabling BusMaster for 100 ms should have
let the attempted DMA complete and produced a visible side effect
(TCM write, D11 release, sharedram marker replacing 0xffc70038, or a
D2H doorbell). Nothing happened.

Combined with 186a/186c (doorbells ruled out), this strongly points
to **candidate 1: firmware is in an exception/panic loop very early
in its startup**, after the single pmucontrol bit-9 write. The CPU is
running (CPUHALT=NO, pmutimer still advances) but not touching
anything we can observe via MMIO.

### What still fits and what doesn't

- **Fits an exception loop:** no memory writes, no DMA attempts, no
  doorbells, CPU running, one pre-exception register write completed.
- **Does not fit a DMA stall:** BusMaster-on window should have
  yielded *some* DMA progress or caused an AER — it did neither.
- **Does not fit D11-wait:** firmware would still be reading TCM
  header or polling CC registers, which we'd see on MMIO. No reads
  are observable of course, but the *lack of any writes* for 5 s is
  hard to reconcile with a sensible wait loop.

### Next boundary

Shift the search from "what might firmware be waiting on" to
"what is firmware's actual state right now?". Two useful probes:
1. **Re-halt + inspect.** Clear CPUHALT → set CPUHALT to re-halt the
   ARM core, then read TCM + CR4 wrapper registers. If the CPU was in
   an exception vector, the panic handler may have left breadcrumbs
   in a known TCM location (trap vector table, scratch area, or the
   image header's panic-log field).
2. **Compare to the `wl` driver trace.** Phase 2 captured a partial
   MMIO trace of the macOS `wl` driver. The sequence between the
   equivalent `set_active` point and firmware reaching usable state
   must differ from our path somewhere — if we can diff those MMIO
   sequences we can find the missing step that lets firmware progress.
   Artifact: `phase5/logs/wl-trace`.

The second probe is lower-risk (read-only comparison, no hardware
interaction) and may reveal the required host step quickly; it should
come first.

---

## PRE-TEST.186b (2026-04-20, staged) — brief BusMaster-on window

### Hypothesis
After 186a/186c ruled out the doorbell path, the two remaining
candidates for firmware's early stall are (1) exception/panic loop and
(2) DMA stall (firmware needs to fetch something over PCIe DMA but
BusMaster is cleared, so the attempt silently fails). This test briefly
enables BusMaster for ~100 ms after the existing 3-s passive dwell,
then immediately clears it again and dwells for 500 ms and 2 s, with
MMIO-guard reads before the enable, after the enable, and after the
clear to detect any host/endpoint wedge early.

### Prediction
- **If firmware is DMA-stalled:** during or after the BM-on window we
  expect to see at least one of — (a) TCM write activity (any of the
  56 probed offsets CHANGED), (b) D11 RESET_CTL clearing from 0x01,
  (c) sharedram-info address replacing our 0xffc70038 NVRAM marker
  at ramsize-4, or (d) mailboxint asserting a D2H bit (0x10000+).
- **If firmware is in an exception/panic loop:** no change anywhere.
  Same post-BM snapshot as test.186a/186c: D11 still in reset, TCM
  unchanged, pmucontrol bit 9 still the only set bit in the CC diff.

### Risk
Phase-4B hard-crashed the host when BusMaster was left on through
full attach. Mitigations: (a) very short window (~100 ms total),
(b) MMIO guard reads before/after to bail early if the endpoint
stops responding, (c) always `pci_clear_master` before continuing.
If the machine crashes, post-recovery notes and the `stream` log
capture whatever made it to disk.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```
PCIe pre-test: verify no MAbort+ on `lspci -vvv -s 03:00.0`.

---

## POST-TEST.186c (2026-04-20) — mailboxint is RW-set-on-write; no H2D channel elicits firmware response

Captured artifacts:
- `phase5/logs/test.186c.stage0`
- `phase5/logs/test.186c.stage0.stream`
- `phase5/logs/test.186c.journalctl.txt` (594 lines)

Result: **clean run, host stable. Hypothesis partially correct and
partially wrong.** The W1C theory of `mailboxint` is disproved: writing
0xffffffff to clear the register instead left bits 0-1 asserted
(pre-kick 0x0 → after-write 0x3), meaning that for this chip bits 0-1
of mailboxint are read/write (or "write-sets") rather than write-one-
to-clear. None of the three kick channels then changed the value
further — delta=0 after H2D_MAILBOX_0, H2D_MAILBOX_1, and SBMBX.

### Per-kick attribution

```
pre-kick           mailboxint = 0x00000000
after W1C-clear    mailboxint = 0x00000003   <- write of 0xffffffff SET bits 0-1
after H2D_MBX_0=1  mailboxint = 0x00000003  (delta=0x0)
after H2D_MBX_1=1  mailboxint = 0x00000003  (delta=0x0)
after SBMBX=1      mailboxint = 0x00000003  (delta=0x0)
post-kick +500ms   mailboxint = 0x00000003  UNCHANGED
post-kick +2000ms  mailboxint = 0x00000003  UNCHANGED
```

### Key conclusions

1. **Bits 0-1 of `mailboxint` are not W1C — our clear-write SET them.**
   Most likely these bits are "host-side latch of H2D activity" and
   the 0xffffffff write is interpreted as "raise both mailbox-0 and
   mailbox-1 doorbell" on the endpoint side. This matches the test.186a
   observation (0x1 appeared after a single mailbox-0 kick = bit 0);
   test.186c just wrote-all-ones and got both bits.
2. **Test.186a's 0x1 was our own write, confirmed.** Not firmware.
3. **Not one of the three H2D channels elicited any firmware
   response** (no D2H bits 0x10000+, no FN0 bits 0x0100/0x0200, no
   D11 wrapper change, no TCM change, no NVRAM marker change).
4. **D11 wrapper unchanged throughout** — RESET_CTL=0x01, IOCTL=0x07
   at pre-halt, pre-set-active, every dwell, post-kick +500/+2000ms.
   Firmware never releases D11 on its own at this stage.
5. **Only signs of life remain test.184 baseline**: pmucontrol bit 9
   flipped once (0x01770181 → 0x01770381 by dwell+500ms), pmutimer
   ticks monotonically (+~36 kHz). No new activity after the kicks.

### What this rules in / out

- **Ruled out (strongly):** "firmware is waiting on H2D doorbell to
  start." Three different doorbell paths, zero response. The doorbell
  mechanism doesn't become active at this stage of bring-up.
- **Still in play (of test.186a's three candidates):**
  (1) exception/panic loop after single PMU write, and
  (2) DMA stall (BusMaster cleared → any DMA attempt fails silently).
  (3) D11 wrapper wait is less likely now — firmware normally brings
  D11 up itself after PMU init, so the fact that D11 hasn't moved
  suggests firmware never reached the D11-init code path, not that
  it's stuck polling D11.

### Next boundary

test.186b: briefly enable BusMaster for ~100 ms after ARM release,
then clear it again and sample. If firmware is DMA-stalled (candidate
2), the brief BusMaster window should let its startup DMA complete
and we should see either (a) TCM write activity, (b) D11 wrapper
release, or (c) sharedram-info address replacing our 0xffc70038 marker
at ramsize-4. If no change, the exception-loop theory (candidate 1)
becomes the leading hypothesis and we'd need a different probe
strategy (e.g. reading CR4 wrapper IFP/PC registers if exposed, or
re-asserting reset and inspecting TCM for a panic stub).

Risk note: BusMaster-on after ARM release crashed the host in Phase-4B.
The mitigation is (a) very brief window, (b) root-port MMIO guard
before/after, (c) immediate re-clear if any MMIO slows down.

---

## PRE-TEST.186c (2026-04-20, staged) — per-kick mailboxint attribution

### Hypothesis
test.186a saw `mailboxint` flip bit 0 (0x1) after kicking all three
H2D channels, but bit 0 is outside `int_fn0` (0x0300) and
`int_d2h_db` (0x10000+). Most likely explanation: our H2D_MAILBOX_0
write latched locally into bit 0 of the doorbell-reflect side of the
register. test.186c disambiguates by (a) W1C-clearing `mailboxint` to
a known 0x0 before kicking, and (b) reading `mailboxint` after each
individual kick so we can attribute any asserted bit to the specific
channel that set it.

### Prediction
- After W1C clear: `mailboxint` reads 0x00000000.
- After H2D_MAILBOX_0 kick: bit 0 appears (0x00000001). Confirms
  the echo theory.
- After H2D_MAILBOX_1 kick: probably no new bits (mailbox-1 is
  typically a separate latch or no-op from host side).
- After SBMBX kick: probably no new bits (SBMBX is config-space
  sideband, separate signal path).
- Post-kick dwells: everything else matches test.186a (D11 still in
  reset, NVRAM marker unchanged, 64 TCM probes UNCHANGED).

Any deviation — e.g. bit 0 not appearing after mailbox_0, or D2H
bits (0x10000+) asserting, or FN0 bits (0x0300) asserting — would
be significant new information about firmware state.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```
PCIe pre-test: MAbort-, LnkSta x1 2.5GT/s — clean.

---

## POST-TEST.186a (2026-04-20) — firmware ignores all three host doorbells

Captured artifacts:
- `phase5/logs/test.186.stage0`
- `phase5/logs/test.186.stage0.stream`
- `phase5/logs/test.186.journalctl.txt`

Result: **clean run, host stable. `mailboxint` changed 0x0 → 0x1 after
the kick, but bit 0 is not any of the D2H/FN0 signals brcmfmac cares
about (D2H bits start at 0x10000, FN0 at 0x100) — most likely our own
H2D_MAILBOX_0 write latched into the local side of the doorbell
register, not firmware responding. All other probes UNCHANGED: D11
RESET_CTL still 0x01, D11 IOCTL/IOSTATUS stable at 0x07/0x00, NVRAM
marker untouched, all 56 TCM sample points UNCHANGED, no FN0/D2H
bits asserted.** Firmware is not gated on any host doorbell at this
point in its startup.

### The one CHANGED signal — and why it's ambiguous

```
pre-kick  PCIE2 mailboxint = 0x00000000
post-500ms PCIE2 mailboxint = 0x00000001  (CHANGED)
post-2000ms PCIE2 mailboxint = 0x00000001  (unchanged from +500ms)
```

In `brcmf_reginfo_default` the bits brcmfmac's ISR acts on are:
- `int_fn0  = BRCMF_PCIE_MB_INT_FN0  = 0x0100 | 0x0200 = 0x0300`
- `int_d2h_db = (D2H0_DB0|D2H0_DB1|...|D2H3_DB1) = 0x10000..0x800000`

Bit 0 (0x1) is **not in either mask**. Bit 0 most likely latches the
fact that the host issued an H2D to mailbox 0 (chip-internal side of
the doorbell register). That would explain why it latched immediately
(within the 500 ms poll) and never cleared — we never explicitly clear
it. It is **not evidence of firmware response**.

To distinguish conclusively we would need to either (a) clear
mailboxint before the kick and observe it assert post-kick, or
(b) kick only *one* of the three channels and see whether mailboxint
bit 0 still appears when we don't write to mailbox 0.

### What firmware did NOT do

- D11 wrapper: IOCTL=0x07 / IOSTATUS=0x00 / RESET_CTL=0x01 —
  identical to test.185, identical pre-halt to post-kick-2000ms.
  Firmware never starts D11 bring-up.
- Mailboxint D2H/FN0 bits (the bits that would indicate firmware
  is deliberately signalling host): all zero throughout.
- NVRAM marker at ramsize-4: still 0xffc70038 (our magic/len). If
  firmware had reached the sharedram handoff it would have replaced
  this with the shared-info address. It did not.
- TCM: 8 image-header + 40 wide-grid + 16 tail = 64 probe points,
  all UNCHANGED at post-kick +500 ms and +2000 ms.
- pmucontrol bit 9: still 0x01770381 (the single flip from test.184
  — no additional flip triggered by our kick).

### What firmware DID do

- Same as test.184/185: flipped pmucontrol bit 9 exactly once within
  the first 500 ms after ARM release. pmutimer ticks monotonically.

### Interpretation

The doorbell theory is essentially disproved for *this stage* of
firmware startup. Three complementary channels (generic H2D, HostReady
H2D, SBMBX config) all produced zero effect on D11, TCM, or the D2H
signals that firmware would use to acknowledge us. Firmware is *alive*
but either:
1. **Stalled in an exception/panic loop very early.** After the one
   PMU write, the CPU may have hit an undefined instruction or data
   abort handler and now loops in it without touching memory. This is
   consistent with: CPU running (pmutimer ticks are hardware-level
   and unrelated to CPU state, but CPUHALT=NO means the core is
   definitely not parked), no memory writes, no mailbox traffic.
2. **Stalled waiting on DMA.** Firmware may need to fetch something
   from host memory via DMA (e.g., the resetintr vector table, or a
   shared-memory descriptor). With BusMaster cleared the DMA attempt
   silently fails; firmware has no way to report that failure over
   MMIO because its error reporting path is in shared-memory too.
3. **Stalled waiting on D11.** Firmware may be polling a D11 wrapper
   bit that requires a clock or reset sequence we haven't performed.
   Not likely as the dominant theory (firmware normally brings up D11
   itself after its own PMU/clock init), but possible if D11 init
   depends on something upstream.

### Next boundary

Two complementary experiments, roughly in increasing risk order:

- **test.186b — brief BusMaster window.** Re-enable BusMaster for a
  2-3 s observation window with the same passive/kick flow; then
  disable before return. Watch for D11 bring-up, TCM writes, any
  change in the D2H mailboxint bits. If firmware was DMA-stalled we
  should see at least a partial shared-info setup. Phase-4B crashed
  with BusMaster enabled + full attach path; this experiment keeps
  the attach path absent (still -ENODEV) so we isolate DMA from
  interrupt handling. Restores BusMaster-cleared state before the
  module returns.
- **test.186c — clear mailboxint pre-kick to disambiguate.** Cheap,
  no-risk variant of test.186a: write mailboxint = 0xffffffff to clear
  any latched bits before the kick, then observe post-kick bits. If
  bit 0 still reappears after a clear + kick, it's our own H2D
  echo. If it doesn't reappear, firmware may be lazily asserting it.

Plan: run test.186c first (cheap, informative) to nail down the
mailboxint bit 0 interpretation; then commit to test.186b if 186c
confirms no firmware response.

---

## PRE-TEST.186a (2026-04-20, staged) — H2D mailbox kick after passive dwell

### Hypothesis
test.185 showed firmware is alive (pmucontrol bit 9 flipped, pmutimer
ticks) but idles without touching D11 or TCM. The simplest candidate
for "stuck waiting" is a host doorbell that we never sent. test.186a
reuses the test.185 passive flow verbatim, then — after the 3000ms
dwell completes — rings all three available H2D channels in quick
succession:

1. `H2D_MAILBOX_0` — BAR0 PCIE2-core offset 0x140, generic doorbell
2. `H2D_MAILBOX_1` — BAR0 PCIE2-core offset 0x144, HostReady doorbell
3. `SBMBX`         — PCI config-space offset 0x98, sideband mailbox

All three are single-word MMIO/config writes. No BusMaster needed,
no shared-info parse needed, no DMA. After the kick, dwell +500 ms
and +2000 ms (total ~2.5 s post-kick) and re-probe D11+CR4 wrappers,
CC backplane regs, mailboxint, NVRAM marker, image-header TCM,
wide-TCM grid (40 points), and tail-TCM (16 points). BusMaster
remains cleared; still -ENODEV early return.

### Prediction
- **Most likely (continuation of test.185 null)**: all post-kick
  probes match pre-kick values, no D11 bring-up, no TCM writes,
  mailboxint stays 0. Confirms firmware isn't gated on a doorbell
  at this early stage.
- **Positive evidence (best case)**: mailboxint asserts, OR D11
  RESET_CTL clears bit 0, OR at least one TCM word changes. Any of
  these would pinpoint a specific channel firmware is listening on.
- **Unexpected (must investigate)**: host MMIO freeze, completion
  timeout on the SBMBX config write, or firmware halt indicated by
  D11/CR4 wedge.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```
WAIT_SECS=45 covers the extra ~2 s post-kick dwell (total in-module
~5 s). PCIe pre-test: MAbort-, LnkSta x1 2.5GT/s — clean.

---

## POST-TEST.185 (2026-04-20) — D11 held in reset; firmware stalled in earliest init

Captured artifacts:
- `phase5/logs/test.185.stage0`
- `phase5/logs/test.185.stage0.stream`
- `phase5/logs/test.185.journalctl.txt`

Result: **clean run, host stable, -ENODEV returned. Firmware baseline
(pmutimer ticks, pmucontrol bit 9 set once) reproduces from test.184.
D11 wrapper probe shows the D11 core is held in reset (RESET_CTL=0x01)
and firmware NEVER takes it out of reset in 3 s. All 40 wide-TCM probe
points + all 16 tail points UNCHANGED.** Hypothesis (c) from PRE-TEST
confirmed: firmware is stalled in earliest init, before any D11 bring-up
and before any TCM writes.

### D11 wrapper — held in reset across every probe

```
pre-halt              D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
pre-set-active        D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
post-set-active-20ms  D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
post-set-active-100ms D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
post-set-active-500ms D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
post-set-active-1500ms D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
post-set-active-3000ms D11 IOCTL=0x07 IOSTATUS=0x00 RESET_CTL=0x01
```

Three things to note:
1. D11 RESET_CTL bit 0 is asserted — D11 core in reset from cold
   (chip-default). Firmware has not deasserted reset.
2. D11 IOCTL=0x07 (fclk_en | fclk_force_on | ioctl_bit2) — also the
   chip-default wrapper state before firmware touches it.
3. Values are identical pre-halt and at 3000 ms → firmware did not
   even touch the D11 wrapper in 3 s.

**Conclusion**: firmware never reached the phase where it brings D11
out of reset. This is very early in the init sequence.

### ARM CR4 — IOSTATUS stays zero

CR4 IOCTL drops 0x21 → 0x01 (CPUHALT released) as expected.
CR4 IOSTATUS=0x00 at every probe (pre-halt / pre-set-active / 20 ms /
100 ms / 500 ms / 1500 ms / 3000 ms). New visibility but no useful
signal from IOSTATUS on this core.

### TCM — 40 wide points + 16 tail points + 8 image-header points all UNCHANGED

Every sampled word from 0x00000 to 0x9c000 (every 16 KB) plus the last
64 bytes (NVRAM region) reads the same value pre-release and at 3000 ms.
Firmware has not written any of 56 sampled TCM words in 3 s.

### Backplane — same deltas as test.184

```
pre-release:   CC-pmucontrol=0x01770181  CC-pmutimer=0x0d7f584d
dwell-500ms:   CC-pmucontrol=0x01770381  CC-pmutimer=0x0d7fb28b  Δ=0x5a3e / 500 ms → ~46 kHz
dwell-1500ms:  CC-pmucontrol=0x01770381  CC-pmutimer=0x0d803b93
dwell-3000ms:  CC-pmucontrol=0x01770381  CC-pmutimer=0x0d810b0c  Δ=0x1b2bf / 3000 ms → ~37 kHz
```

pmucontrol bit 9 flips exactly once within 500 ms (same single write
as test.184). pmutimer ticks monotonically — confirms we're not in a
wedge where MMIO is dead; we really are observing firmware that is
alive but stuck.

### What this narrows down

We now have three facts:
1. ARM CR4 is released and the core is executing instructions
   (pmucontrol bit 9 was written by *something* after release).
2. Firmware completes at least one CC register write in < 500 ms,
   then idles for the remaining 2.5 s (pmucontrol steady, no further
   CC writes, no TCM writes, no D11 wrapper touch).
3. Firmware is stalled at a point that is **before** D11 bring-up
   and **before** any TCM initialisation.

The most likely explanation: firmware's very early startup writes a
single PMU bit (bit 9 of pmucontrol — commonly part of xtal-freq
select) and then waits. Two candidate wait points:
- waiting for host-side PCIe2 mailbox handshake, which we never send
  because we return -ENODEV (Phase-4B path);
- waiting for BusMaster to be enabled so it can fetch a resource
  from host DMA (we cleared BusMaster to survive past test.134's
  crash).

### Next boundary (test.186)

Two complementary probes, in order of least-risky first:

1. **test.186a — lightweight host doorbell without BusMaster.**
   Write to the PCIe2 H2D mailbox address from the host (MMIO write
   only, no host-side DMA required). If firmware was waiting on a
   mailbox it should respond with a TCM / D11 / pmucontrol change
   within a few hundred ms. BusMaster still cleared; still early
   return.

2. **test.186b — BusMaster ON for a brief window, observe, then OFF.**
   If mailbox alone doesn't unstick firmware, re-enable BusMaster
   for a 1-2 s observation window. Phase-4B crashed with BusMaster
   enabled + full attach path; this narrow experiment keeps the
   attach path absent (still -ENODEV) so firmware would only have
   the chance to initiate DMA, not to complete a full sharedram
   handshake. If the host survives and TCM/D11 start moving, we've
   identified DMA as the stall point.

(Current task list ends at #30 — these two become tasks #31/#32.)

---

## PRE-TEST.185 (2026-04-20, staged) — widen TCM scan + D11 wrapper probe

### Hypothesis
Firmware is running (test.184 proved it via pmutimer ticks and one
pmucontrol bit flip) but we cannot see it touching TCM in the 32
points we sample. Either (a) firmware writes somewhere outside those
probes, (b) firmware never reaches the point of writing to TCM, or
(c) firmware is stalled waiting on an external event (host doorbell,
D11 bring-up, etc.).

test.185 widens the TCM sampling to a 16-KB grid across the full
640-KB TCM (40 probe points) and adds a D11 (BCMA_CORE_80211) wrapper
probe alongside the ARM CR4 probe at every sample point (pre-halt,
pre-set-active, +20 ms, +100 ms, +500 ms, +1500 ms, +3000 ms). CR4
probe also gains IOSTATUS (0x40c) for wrapper visibility. BusMaster
stays cleared; still returns -ENODEV.

### Prediction
- pmutimer continues to tick; pmucontrol stays at 0x01770381 (the
  test.184 value) — baseline firmware side-effect reproduces.
- ARM CR4 IOSTATUS reveals a non-zero value that changes across
  dwells, giving a second observable besides CPUHALT.
- D11 IOCTL/RESET_CTL: either (a) all-zero and unchanged → firmware
  hasn't reached D11 bring-up, or (b) changes → firmware has started
  taking D11 out of reset (major milestone).
- Wide-TCM grid: at least one of the 40 points changes if firmware
  is actually rewriting any 16-KB block of the image. If all 40 stay
  UNCHANGED (our expectation given test.184's 32-point null result)
  we can definitively say firmware is not touching TCM at all in 3 s.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```

Expected HW: PCIe link stays up, host survives, -ENODEV returned from
insmod. LnkSta stays at x1 2.5GT/s; no MAbort+.

---

## Current state (2026-04-20, POST test.184 — pmutimer ticking, firmware flipped pmucontrol bit 9 once)

### TEST.184 RESULT — firmware IS doing early init; one backplane bit moved

Captured artifacts:
- `phase5/logs/test.184.stage0`
- `phase5/logs/test.184.stage0.stream`
- `phase5/logs/test.184.journalctl.txt`

Result: **Two pieces of evidence that firmware is executing, both on
the backplane side only. All TCM (32 sample points) remains UNCHANGED.
Host survives cleanly.**

### Decisive observations

#### pmutimer ticks at ~36 kHz — PMU is fully alive

```
pre-release:   CC-pmutimer=0x0bd41400
dwell-500ms:   CC-pmutimer=0x0bd465bb   Δ=0x51bb  = 20923 ticks / 500 ms
dwell-1500ms:  CC-pmutimer=0x0bd4ed96   Δ=0xd996  = 55702 ticks / 1500 ms
dwell-3000ms:  CC-pmutimer=0x0bd5ba7f   Δ=0x1a67f = 108159 ticks / 3000 ms
```

Rate: ~36000 Hz (108159 / 3.0). This is close to ILP (32768 Hz) with
our MMIO-read latency widening the apparent interval — the counter
itself is monotonic, positive, and linear across the three dwells.
The PMU clock domain is running normally.

#### pmucontrol bit 0x200 set exactly once in the first 500 ms

```
pre-release:   CC-pmucontrol=0x01770181
dwell-500ms:   CC-pmucontrol=0x01770381   CHANGED (bit 9 set)
dwell-1500ms:  CC-pmucontrol=0x01770381   UNCHANGED
dwell-3000ms:  CC-pmucontrol=0x01770381   UNCHANGED
```

**This is the first observed firmware side-effect on this chip
under brcmfmac.** Someone — firmware is the only thing executing
between pre-release and dwell-500ms — flipped bit 9 (0x200) of
pmucontrol. Meaning of that bit: in the Broadcom PMU layout this
field is typically part of `PCTL_XTALFREQ` (xtal-frequency-select,
bits 9–12) or `PCTL_NOILP_ON_WAKE`. Without disassembly, we can
only say: *firmware executed at least the code path that writes
pmucontrol, and did so within 500 ms of ARM release*.

After that single write, pmucontrol holds steady through 3 s.
Firmware either:
- finished its early PMU init and moved on, or
- stalled right after that write.

#### All other backplane registers UNCHANGED

```
CC-clk_ctl_st   = 0x00050040   (BP_ON_HT bit set in upper byte
                                — HT clock available)
CC-pmustatus    = 0x0000002a   (HAVEHT bit 0x04 *not* actually set,
                                but firmware has HT via BP route;
                                bits 0x02 + 0x08 + 0x20 asserted)
CC-res_state    = 0x0000013b   (HAVEHT/HAVEALP/PLL up pattern —
                                PMU resources in steady state)
CC-min_res_mask = 0x0000013b
CC-max_res_mask = 0x0000013f
CC-pmuwatchdog  = 0x00000000
```

`res_state == min_res_mask` means all requested resources are
asserted. `max_res_mask` is one bit higher (0x04 — commonly
`RES_HT_AVAIL`) — that bit is available but not requested.
pmuwatchdog = 0: no watchdog active.

### All TCM regions still UNCHANGED

Image-header, mid-TCM, tail-TCM: same exact values at pre-release,
500/1500/3000 ms. Firmware has not written to TCM in any of the
32 sample points. Consistent with test.183.

### ARM CR4 state

CPUHALT=NO at 20/100/500/1500/3000 ms. RESET_CTL=0 throughout. ARM
continues running for the full 3 s, no regression.

### Interpretation

This refines hypothesis (A) from PRE-184:

- Firmware *is* executing (pmucontrol bit flip is proof).
- Firmware progressed far enough past reset to reach at least one
  PMU manipulation in the first 500 ms, then stopped touching
  anything observable on the backplane or TCM.
- Most likely: firmware reached an early "wait for host" or
  "wait for a specific resource" point and has been idle there
  since ~500 ms.

Ruled out:
- "ARM totally idle" — we now have a side-effect that requires
  ARM execution.
- "PMU frozen / chip-wide stall" — pmutimer is ticking.
- "MSVC compiler weirdness / probe reads were bogus" — the pre-release
  `pmucontrol=0x01770181` vs post-release `0x01770381` differ only
  in bit 9, so this is a real firmware write, not a race with our
  probe.

Not yet ruled out:
- Firmware writes TCM in regions we aren't sampling (can't be
  excluded without wider scan).
- Firmware writes D11 SHM or other core-local SRAM (not visible
  via TCM read).

### Current HW state after test.184

- `brcmfmac` unloaded; `brcmutil` still loaded.
- Endpoint 03:00.0: `Mem- BusMaster-`, BAR regions `[disabled]`,
  `<MAbort-`. Clean post-rmmod. Re-initialises on next insmod.
- Root port 00:1c.2: clean. No AER/MCE.

### Recommended next step — PRE test.185

Two orthogonal probes worth doing before any host-side progression:

1. **Widen the TCM scan further.** With the test.184 finding that
   firmware wrote pmucontrol once, it's likely it also touched TCM
   somewhere outside the 32 sample points we watch today. Sample
   every 16 KB across the full 640 KB TCM (that's 40 probe points)
   at pre-release and at 3000 ms — keeps the same dwell cadence
   but gives ~8× the spatial coverage. Also record which word in
   each 16 KB block we're reading (so if one changes, we know where).

2. **Sample more backplane reg windows.** Read the ARM CR4 core
   wrapper's IOSTATUS/RESET_ST alongside IOCTL/RESET_CTL. Also
   probe the D11 core's ioctl/reset at `core->base + 0x100000 +
   0x408/0x800` — if firmware is bringing the D11 PHY/MAC up,
   that would show there.

Start with (1) — it's the safest and most likely to find more
activity given we already know firmware is running.

Do *not* start enabling BusMaster or MSI until (1) + (2) both come
back clean. That territory caused Phase-4B host crashes and we
should exhaust passive observation first.

Commit + push + sync PRE-test.185 before running.

### Pre-test HW state expected

Same as test.184 post-run: endpoint `03:00.0` shows `Mem- BusMaster-`,
BAR regions `[disabled]`. Clean post-rmmod.

---

## Previous state (2026-04-20, PRE test.184 — ChipCommon backplane observation)

### PRE-TEST.184 checkpoint

Test.183 proved 32 TCM sample points across three regions are UNCHANGED
through 3 s post-release. ARM CR4 stays CPUHALT=NO the whole time. The
working hypothesis is that firmware is running but wedged in a
pre-NVRAM-parser wait loop. To discriminate "ARM idle" from "ARM
working in backplane state we haven't observed", test.184 adds
ChipCommon backplane-register sampling.

Implementation:

1. New helper `brcmf_pcie_sample_backplane(devinfo, u32 vals[8])` reads
   eight ChipCommon registers via `READCC32`:
   - `clk_ctl_st`  — BP clock request / HAVEHT status bits
   - `pmucontrol`  — PMU control word (written by firmware resource
                     setup)
   - `pmustatus`   — PMU state (HAVEHT bit 0x04 etc.)
   - `res_state`   — which PMU resources are currently asserted
   - `pmutimer`    — monotonic ILP-clock tick counter (~32 kHz).
                     Ticks every dwell if the PMU is clocked,
                     regardless of firmware. CHANGED→UNCHANGED flip
                     here would mean the PMU itself has stopped.
   - `min_res_mask`, `max_res_mask` — resource-request masks
   - `pmuwatchdog` — PMU watchdog; firmware normally tickles this
                     to keep itself running.
2. New const array `brcmf_bp_reg_names[8]` for symbolic logging.
3. In the BCM4360 early-return block:
   - After the tail-TCM pre-release snapshot, call
     `brcmf_pcie_sample_backplane(devinfo, pre_bp)` and log each
     register as `CC-<name>=0x<val> (pre-release snapshot)`.
   - At each dwell (500/1500/3000 ms) re-sample and log
     `dwell-<ms>ms CC-<name>=0x<now> (was 0x<pre>) CHANGED|UNCHANGED`.
4. TCM snapshots (image-header + mid + tail) stay identical to
   test.183. ARM CR4 release path, BusMaster-cleared policy, and
   `-ENODEV` return all unchanged.

Build: OK via kernel kbuild. Module has 40 `test.184` markers and
0 `test.183` strings. Format strings `CC-%s=...` present in binary.
Only existing warning is `brcmf_pcie_write_ram32 defined but not used`.
BTF skipped (vmlinux unavailable).

Harness `WAIT_SECS` stays 45 — the 8 extra register reads per snapshot
add negligible time.

### Hypothesis

Given test.183's finding that TCM stays static for 3 s:

- (A) **PMU is alive (pmutimer ticks) but firmware is not touching
  backplane resource regs either.** pmutimer CHANGED (monotonically
  increasing by ≥ floor(500/32)·16 = ~16 ticks per 500 ms of ILP
  clock at 32 kHz) — all *other* CC regs UNCHANGED. Means the chip
  is clocked but firmware genuinely isn't doing work on the
  backplane we can see. Likely waiting on an MMIO from the host
  (BusMaster / MailBox / scratchpad).
- (B) **PMU is alive AND firmware is manipulating backplane state.**
  pmutimer + one or more of `clk_ctl_st`/`pmustatus`/`res_state`/
  `min_res_mask`/`max_res_mask`/`pmuwatchdog` CHANGED. Means firmware
  is running its resource/clock setup — significant activity we
  haven't seen yet. Unexpected but very informative.
- (C) **PMU is frozen.** pmutimer UNCHANGED. Would mean the whole PMU
  has stalled, which would be a regression from test.181/.182/.183
  (ARM CR4 is running, so the ARM clock domain is on — which usually
  requires HAVEHT/HT clocks, which are PMU-sourced). Investigate
  deeply.

Expected at minimum: `pmutimer` monotonically increasing across
dwells. That alone will confirm the chip's PMU is clocking normally.

### Interpretation matrix

- `pmutimer` increases per dwell, other CC regs UNCHANGED: firmware
  is running on ARM but doing no backplane work — case (A). Next
  test probably needs to enable BusMaster to get firmware past its
  host-handshake wait.
- `pmutimer` increases, and `pmustatus`/`res_state`/masks CHANGED:
  firmware is driving backplane — case (B). Next test interprets
  the changed bit fields.
- `pmutimer` does NOT increase: PMU stalled — case (C). Investigate
  before any host-facing progression.
- `pmuwatchdog` CHANGED (decreasing): firmware is not tickling PMU
  watchdog — it will eventually fire. Need to understand whether the
  watchdog is active in our configuration.
- ARM CR4 probe returns CPUHALT=YES at any dwell: regression.
- TCM regions start CHANGED: unexpected — firmware finally wrote
  somewhere; record exactly which region / offset.

### Run command

Only stage 0:
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Post-run: capture journalctl to `phase5/logs/test.184.journalctl.txt`,
update RESUME_NOTES.md with POST-TEST.184, commit and push.

### Pre-test HW state expected

Same as test.183 post-run: endpoint `03:00.0` shows `Mem- BusMaster-`,
BAR regions `[disabled]`. Clean post-rmmod state. Re-initialises on
next insmod.

---

## Previous state (2026-04-20, POST test.183 — wider scan: ALL regions UNCHANGED for 3 s; firmware not parsing NVRAM)

### TEST.183 RESULT — clean run; hypothesis (B1) reinforced

Captured artifacts:
- `phase5/logs/test.183.stage0`
- `phase5/logs/test.183.stage0.stream`
- `phase5/logs/test.183.journalctl.txt`

Result: **No TCM writes anywhere in the observed regions for 3 s
post-release.** ARM CR4 stays running (CPUHALT=NO, RESET_CTL=0 at
20/100/500/1500/3000 ms). Host survives cleanly, clean rmmod,
no MCE/AER. This is the widest scan we've done (32 words total) and
zero of them change — firmware is *not* making any TCM writes in the
image-header, mid-image, or tail regions for the first 3 s.

### Decisive observations

1. **Image-header TCM[0x0..0x1c]:** 8 words, all UNCHANGED across
   500/1500/3000 ms. Values match the reset-vector / exception table
   we wrote with the firmware blob (0xb80ef000, 0xb82ef000, …).
2. **Mid-TCM probe points** (0x1000, 0x2000, 0x4000, 0x8000, 0x10000,
   0x20000, 0x40000, 0x80000): all UNCHANGED. Each reads as
   firmware-image content (looks like Thumb-2 code — e.g.
   `0x1a806863`, `0xfc8cf7fe`). None touched by firmware.
3. **Tail-TCM last 64 B** (16 words at 0x9ffc0..0x9fffc): all
   UNCHANGED. **New finding**: these 64 bytes hold our *own* NVRAM
   text. Decoding the bytes little-endian:
   `...=0\0vendid=0xdevice=0x14e4...` etc. — the last 228 B of TCM
   is exactly the NVRAM we placed at `ramsize - 228 = 0x9ff1c`.
4. **NVRAM marker at ramsize-4 = 0xffc70038**: this is our *own*
   write (upstream convention: magic `0xffc70000 | (nvram_len / 4)`;
   `228 / 4 = 57 = 0x39`... but observed `0x38 = 56` → actually
   length-in-words is computed somewhere else; regardless, this is
   the marker brcmfmac writes for the firmware to consume).

### Implication — the upstream "sharedram-address slot" is NVRAM text here

Upstream brcmfmac for msgbuf chips typically reads the shared-memory
structure pointer from `TCM[ramsize - 4]` after firmware boot
(firmware clears the magic and writes the sharedram address). For
BCM4360 with our 228-B NVRAM + 4-B marker layout, `ramsize - 8` and
the entire last 64 bytes are *occupied by NVRAM variable text*. The
only word firmware is expected to clear is `ramsize - 4` itself
(the magic). And that word has not been cleared after 3 s.

**Conclusion**: firmware has not yet parsed and consumed NVRAM. It is
running ARM code but has not reached the point of clearing the
magic/length word at `ramsize - 4`.

### What this narrows down

Combined with test.182 (only image-header + marker) and test.181
(CPUHALT=NO for 30 s), the picture is:

- ARM CR4 is executing firmware code continuously.
- For at least 3 s of that execution, firmware does not modify any
  32 sample points across TCM that we observe, including the single
  word the host uses as a handshake (`ramsize - 4`).
- Either:
  (a) firmware is stuck in a very early loop — pre-NVRAM-consumption
      — waiting on a register, clock, PMU resource, or host handshake
      that never occurs; OR
  (b) firmware is executing but only modifies TCM words that our
      32-sample grid doesn't happen to cover (unlikely — we have
      good coverage of the main image body and the entire handshake
      tail); OR
  (c) firmware is modifying RAM regions outside TCM (e.g. backplane
      SRAM, D11 SHM, PHY reg tables) — possible if its early init
      happens entirely in backplane-local memory before touching
      the host-visible TCM handshake.

Most likely: (a) with a PMU/clock or host-handshake wait, because
(c) would still eventually require firmware to clear the magic word
to tell the host it's ready.

### Decoded NVRAM fragment from tail-TCM dump (for reference)

Taking the 16-word tail-TCM dump and expanding little-endian bytes:

```
0x9ffc0 0x7600303d : "=0\0v"
0x9ffc4 0x69646e65 : "endi"     \ "vendi"
0x9ffc8 0x78303d64 : "d=0x"     | "vendid=0x"
0x9ffcc 0x34653431 : "14e4"     / "vendid=0x14e4"
0x9ffd0 0x76656400 : "\0dev"
0x9ffd4 0x303d6469 : "id=0"
0x9ffd8 0x61333478 : "x43a"
0x9ffdc 0x74780030 : "0\0xt"    → "deviceid=0x43a" + "0\0"
0x9ffe0 0x72666c61 : "alfr"
0x9ffe4 0x343d7165 : "eq=4"
0x9ffe8 0x30303030 : "0000"     → "xtalfreq=40000"
0x9ffec 0x32616100 : "\0aa2"
0x9fff0 0x00373d67 : "g=7\0"    → "aa2g=7"
0x9fff4 0x67356161 : "aa5g"
0x9fff8 0x0000373d : "=7\0\0"  → "aa5g=7"
0x9fffc 0xffc70038 : (magic + length word; NOT text)
```

This is straight brcmfmac NVRAM ("vendid=0x14e4", "deviceid=0x43a0",
"xtalfreq=40000", "aa2g=7", "aa5g=7"). Firmware will consume this
by stepping backward from the magic word. **None of it has been
touched after 3 s** — so firmware's NVRAM parser has not run.

### Current HW state after test.183

- `brcmfmac` unloaded; `brcmutil` still loaded.
- Endpoint 03:00.0: `Mem- BusMaster-`, BAR regions `[disabled]`,
  `<MAbort-`. Clean post-rmmod.
- Root port 00:1c.2: clean. No AER/MCE.

### Recommended next step — PRE test.184

Firmware is running but has not reached NVRAM consumption. Two
promising paths:

1. **Backplane observation (non-destructive).** Read live backplane
   state via BAR0 pre-release and at each dwell. Targets:
   - ARM CR4 wrapper status / bankidx — to see if firmware is
     touching its own core-control registers.
   - ChipCommon PMU status / ChipControl / watchdog timer — these
     tick or change as firmware runs the backplane.
   - ARM CR4 core's CPU cycle counter, if exposed — gives proof of
     "instructions executed" even if ARM is in a tight loop.
   This stays safely on the BAR0 side, does not touch BusMaster or
   MSI, and discriminates (a) vs (c).

2. **Minimal host setup, then re-observe TCM.** If backplane shows
   firmware is running but idle, it may be waiting on a host
   handshake. A conservative test would:
   - Enable BusMaster on the endpoint.
   - Program the PCIe host-to-device window (MailBox / scratchpad
     regs) to expected boot-ready values *if* we know them; if not,
     just enable BusMaster and re-run the 3 s TCM scan to see
     whether magic-word clearance happens simply because firmware
     can now DMA.
   Higher risk — this is exactly the territory where Phase-4B used
   to crash the host. Keep it for after (1).

Start with (1) in test.184: add BAR0 backplane reads at pre-release
and at the 3000 ms dwell.

Do not run test.184 until PRE-test.184 checkpoint is committed and
pushed.

---

## Previous state (2026-04-20, PRE test.183 — widened TCM scan: image-header + mid + tail)

### PRE-TEST.183 checkpoint

Test.182 proved ARM CR4 runs continuously for ≥3 s after release, but
TCM[0x0..0x1c] and the NVRAM marker at `ramsize - 4` stay UNCHANGED
across 500/1500/3000 ms dwells. Two open questions:

- Is firmware doing *any* TCM writes (we only sampled 32 bytes near the
  image header)?
- Has firmware written its shared-memory address anywhere near
  `ramsize - 8`, where upstream brcmfmac looks for it?

Test.183 widens the TCM observation window by adding two more regions
to the pre-release snapshot and each dwell re-read. No BusMaster change,
no MSI, same `-ENODEV` return path.

Implementation:
1. Keep the test.182 image-header snapshot (TCM[0x0..0x1c], 8 words).
2. Add mid-TCM probe points at offsets `0x1000, 0x2000, 0x4000, 0x8000,
   0x10000, 0x20000, 0x40000, 0x80000`. These sample the body of the
   firmware image (0x40000 = 256 KB, 0x80000 = 512 KB both land inside
   the 442 KB fw — should read as firmware code/data pre-release).
   Storage: `pre_mid[8]`. Pre-release log tag: `mid-TCM[0x%05x]`.
3. Add last-64-B-of-TCM window: 16 words at
   `ramsize - 64 .. ramsize - 4` (0x9ffc0 .. 0x9fffc). Covers the
   NVRAM marker at `ramsize - 4`, the upstream sharedram-address slot
   at `ramsize - 8`, and any adjacent handshake fields.
   Storage: `pre_tail[16]`. Pre-release log tag: `tail-TCM[0x%05x]`.
4. At each dwell (500/1500/3000 ms) re-read *all three* regions (same
   8 + 8 + 16 words) and log CHANGED/UNCHANGED per word.
5. Keep `brcmf_chip_set_active` release path. Release fw/nvram and
   return `-ENODEV`.

Build: OK via kernel kbuild. Module has 38 `test.183` markers and 0
`test.182` strings. Pre-release tags `mid-TCM` and `tail-TCM` present in
binary. Only existing warning is `brcmf_pcie_write_ram32 defined but not
used`. BTF skipped (vmlinux unavailable).

Harness `WAIT_SECS` stays 45 — the three extra snapshot regions add
~50 ms total of MMIO reads, not enough to affect the 3 s in-module
dwell budget.

### Hypothesis

One of the following:
- (A1) Firmware is alive and has written into mid-TCM — probably to
  initialise its own data segment. One or more mid-TCM words CHANGED
  at 500 ms or later. Strong evidence that firmware is executing past
  early init and starting to lay down runtime state.
- (A2) Firmware has written the sharedram address at `ramsize - 8` or
  another word in the last 64 B. One of the `tail-TCM` words CHANGED.
  This is the signature brcmfmac normally looks for. If CHANGED at
  3000 ms, we know exactly where to read the handshake and test.184
  can start interpreting its contents.
- (B1) All three regions stay UNCHANGED across 3000 ms. Firmware is
  running but wedged in a loop that doesn't touch TCM at all. Next
  test would need to observe the backplane (chipcommon / CR4
  wrapper) and/or sample the PMU clock counter to confirm firmware
  is doing *any* work. May also indicate we need to enable BusMaster
  and MSI for firmware to progress past host-handshake wait.
- (B2) Changes appear but in an unexpected pattern (e.g. only the
  last two words of tail, or scattered mid-TCM words). Interpretation
  case-by-case; likely narrows the search window.

Expected ARM state across all three dwells: `IOCTL=0x00000001
RESET_CTL=0x00000000 CPUHALT=NO` (same as test.182). Any divergence
means ARM re-halted itself — new finding to investigate.

### Interpretation matrix

- tail-TCM word at `ramsize - 8` CHANGED: firmware wrote sharedram
  address. Huge. Record the value — test.184 dereferences it.
- Any tail-TCM word CHANGED (excluding marker at ramsize-4):
  firmware is touching the end-of-TCM handshake region.
- Any mid-TCM word CHANGED: firmware is executing past the
  image-header window and modifying its own memory.
- All regions UNCHANGED, CPUHALT=NO holds: ARM running but no TCM
  writes — next test samples backplane state / considers enabling
  BusMaster.
- ARM probe returns CPUHALT=YES at any dwell: ARM re-halted. Treat
  as regression from test.181/.182; investigate.
- Host freezes during dwell: narrow the dwell window.

### Run command

Only stage 0:
```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Post-run: capture journalctl to `phase5/logs/test.183.journalctl.txt`,
update RESUME_NOTES with POST-TEST.183, commit and push.

### Pre-test HW state expected

Same as test.182 post-run: endpoint `03:00.0` shows `Mem- BusMaster-`,
BAR regions `[disabled]`, `<MAbort-`. Normal post-rmmod state, clean.

---

## Previous state (2026-04-20, POST test.182 — ARM running but TCM[0..0x1c] + NVRAM marker UNCHANGED for 3 s)

### TEST.182 RESULT — clean run; hypothesis (B) confirmed

Captured artifacts:
- `phase5/logs/test.182.stage0`
- `phase5/logs/test.182.stage0.stream`
- `phase5/logs/test.182.journalctl.txt`

Result: **ARM continues running firmware for ≥3 s post-release, but does
not touch TCM[0x0..0x1c] or the NVRAM marker at `ramsize - 4` in that
window.** Host survived cleanly. Clean `-ENODEV` + rmmod. No MCE/AER/panic.

### Decisive sequence (condensed)

```
pre-release snapshot:
  NVRAM marker at ramsize-4 = 0xffc70038
  TCM[0x00]=0xb80ef000  TCM[0x04]=0xb82ef000  TCM[0x08]=0xb839f000
  TCM[0x0c]=0xb844f000  TCM[0x10]=0xb852f000  TCM[0x14]=0xb860f000
  TCM[0x18]=0xb86ef000  TCM[0x1c]=0xb87cf000
  pre-set-active:         IOCTL=0x00000021 RESET_CTL=0x0 CPUHALT=YES
calling brcmf_chip_set_active resetintr=0xb80ef000 (BusMaster stays cleared)
brcmf_chip_set_active returned true
post-set-active-20ms:     IOCTL=0x00000001 RESET_CTL=0x0 CPUHALT=NO
post-set-active-100ms:    IOCTL=0x00000001 RESET_CTL=0x0 CPUHALT=NO
post-set-active-500ms:    IOCTL=0x00000001 RESET_CTL=0x0 CPUHALT=NO
  dwell-500ms  NVRAM marker UNCHANGED (0xffc70038)
  dwell-500ms  TCM[0x00..0x1c] all UNCHANGED (matches pre-release)
post-set-active-1500ms:   IOCTL=0x00000001 RESET_CTL=0x0 CPUHALT=NO
  dwell-1500ms NVRAM marker UNCHANGED
  dwell-1500ms TCM[0x00..0x1c] all UNCHANGED
post-set-active-3000ms:   IOCTL=0x00000001 RESET_CTL=0x0 CPUHALT=NO
  dwell-3000ms NVRAM marker UNCHANGED
  dwell-3000ms TCM[0x00..0x1c] all UNCHANGED
released fw/nvram after extended post-release TCM sampling; returning -ENODEV
```

### Interpretation

- ARM CR4 is genuinely running: `CPUHALT=NO` holds steady at 20 ms,
  100 ms, 500 ms, 1.5 s, and 3 s post-release. No re-halt, no reset.
- The initial 8-word TCM window (firmware image header — the vector
  table / initial jump targets written as part of the 442 KB fw download)
  is read-only or at least untouched by firmware for the first 3 s.
  Those words map to reset-vector / exception-vector entries
  (`0xb80ef000`, `0xb82ef000`, …) and wouldn't be modified by normal
  firmware init.
- The NVRAM marker at `ramsize - 4 = 0xffc70038` is ALSO unchanged.
  Upstream firmware writes `BRCMF_FWNVRAM_MAGIC` / size at this slot
  as part of NVRAM consumption. After 3 s with ARM running, our
  firmware has *not* performed that write.
- Combined with the fact that test.181 already showed the host
  surviving 30 s post-release, this is hypothesis (B) from PRE-182:
  **ARM is running but firmware is stalled in a very early loop that
  does not touch TCM[0..0x1c] or the NVRAM marker**.
- No evidence yet that firmware is doing *any* TCM writes — but we
  only sampled a 32-byte window. The working hypothesis for test.183
  is that firmware either:
  (a) stalls before reaching NVRAM consumption (waiting on a backplane
      register, PMU resource, clock, or PCIe host-handshake that
      brcmfmac never provides because BusMaster/MSI stay disabled);
  (b) writes its shared-memory structure to a different TCM region
      (e.g. `sharedram_addr` at `ramsize - 8` or a firmware-resolved
      address), leaving the first 32 bytes untouched.

### Why this is still good news

- No crash, no MCE/AER, clean rmmod — repeatability confirmed.
- ARM CR4 running stably for ≥3 s under brcmfmac with BusMaster
  cleared gives us a reliable *observation platform*: we can now
  extend probes to any TCM window and any MMIO read without
  destabilising the host.
- The shape of the problem is now concrete: *what is firmware doing
  (or waiting for) between ARM release and its first TCM write?*

### Current HW state after test.182

- `brcmfmac` unloaded; `brcmutil` still loaded.
- Endpoint 03:00.0: `Mem- BusMaster-`, BAR regions `[disabled]`,
  `<MAbort-`, link 2.5GT/s x1. Clean post-rmmod state. Re-initialises
  on next insmod.
- Root port 00:1c.2: clean.
- No MCE/AER. No SMC reset needed.

### Recommended next step — PRE test.183

Widen the observation window. Two parallel probes:

1. **Widen TCM scan.** The firmware image header occupies the first
   TCM region; shared structures are typically placed near the end
   of RAM. Test.183 should sample:
   - Last 64 bytes of TCM: `TCM[ramsize - 64 .. ramsize - 4]` in
     4-byte words — this covers NVRAM marker (ramsize-4), sharedram
     address slot (upstream convention: `ramsize - 8`), and any
     trailing firmware handshake fields.
   - A small mid-TCM sample: `TCM[0x1000]`, `TCM[0x2000]`,
     `TCM[0x10000]`, `TCM[0x40000]`, `TCM[0x80000]` — just a few
     probe points to see if firmware has touched *any* memory.
   - Same 500 ms / 1500 ms / 3000 ms dwell cadence; log CHANGED/
     UNCHANGED per word.
2. **Sample backplane via BAR0.** Read chipcommon rev/revID and
   ARM CR4 wrapper bank index once pre-release and once at 3 s
   post-release to see whether firmware is performing any
   backplane ops. If those registers change, firmware is alive
   on the backplane even if it hasn't touched TCM in the windows
   we're watching.

Keep BusMaster cleared. Still return `-ENODEV`. Keep `WAIT_SECS=45`.

Commit + push + sync the PRE-test.183 checkpoint before running.

---

## Previous state (2026-04-20, PRE test.182 — extended post-release TCM sampling)

### PRE-TEST.182 checkpoint

Test.181 proved `brcmf_chip_set_active(ci, 0xb80ef000)` releases ARM CR4
cleanly (IOCTL 0x0021→0x0001, CPUHALT YES→NO, no RESET_CTL change, host
survives ≥30 s). The next boundary is to determine whether firmware is
actually *executing* — writing to its own TCM — or simply spinning in an
early stall loop.

Implementation (same probe tree as test.181 through `post-set-active-100ms`,
then extended):
1. Immediately after the 8-word TCM verify dump, snapshot the 8 words into
   local array `pre_tcm[8]` and the NVRAM marker at `ramsize - 4` into
   `pre_marker` (new locals in the BCM4360 early-return block).
2. Keep the test.181 sequence through `post-set-active-100ms`.
3. Loop three extra dwell stages with labels 500 ms / 1500 ms / 3000 ms.
   Incremental sleeps: +400 ms, +1000 ms, +1500 ms. Each stage:
   - `brcmf_pcie_probe_armcr4_state(devinfo, "post-set-active-<label>ms")`
   - Read NVRAM marker; compare against `pre_marker`; log CHANGED/UNCHANGED.
   - Read TCM[0x0..0x1c] word-by-word; compare against `pre_tcm[j]`; log
     CHANGED/UNCHANGED per word.
4. Release `fw`/`nvram` and return `-ENODEV`. Still no BusMaster, no MSI,
   no sharedram polling, no advance into normal attach.

Harness change: `WAIT_SECS` bumped from 30 to 45 to cover the additional
~3 s in-module dwell plus existing 100 ms + 20/100 ms post-probes.

Build: OK via kernel kbuild. Module carries 34 `test.182` markers and 0
`test.181` strings. Only existing warning is `brcmf_pcie_write_ram32
defined but not used`. BTF skipped (vmlinux unavailable).

### Hypothesis

Firmware will either:
- (A) ARM has started executing firmware and is initialising its early
  state — at least one TCM word in 0x0..0x1c will change between the
  pre-release snapshot and one of the 500/1500/3000 ms reads, and/or
  the NVRAM marker at `ramsize - 4` will change (firmware parsed NVRAM
  and overwrote the marker), OR
- (B) ARM is running but firmware is stalled in a very early loop that
  does not touch TCM[0..0x1c] or the NVRAM marker — all reads
  UNCHANGED. In that case the next test expands the TCM scan window
  and/or starts sampling backplane state via BAR0.

Expected ARM state across all three dwells: `IOCTL=0x00000001
RESET_CTL=0x00000000 CPUHALT=NO` (same as test.181 post-probes). Any
divergence (e.g. CPUHALT returning to YES) means the ARM has re-halted
itself, which would be a new finding.

### Interpretation matrix

- Any TCM word in 0x0..0x1c CHANGED at 500 ms / 1500 ms / 3000 ms:
  firmware is executing and touching its own TCM. Strong green light for
  test.183 to expand the TCM scan and hunt for sharedram structure.
- NVRAM marker at `ramsize - 4` CHANGED: firmware has consumed NVRAM
  (normal on successful boot) and likely moved into sharedram setup.
- All UNCHANGED but ARM CR4 probes remain CPUHALT=NO across dwells:
  ARM is running but stuck in an early loop that never touches
  TCM[0..0x1c] or NVRAM marker. Next test widens the scan window and
  adds backplane-register sampling via BAR0 to see if firmware is
  doing any MMIO at all.
- ARM CR4 probe at any dwell returns CPUHALT=YES or an unexpected
  RESET_CTL: ARM has re-halted itself (fault, watchdog, or deliberate
  halt). Investigate before doing anything else.
- Host freezes during the extended dwell (no stream lines past a given
  dwell, harness appears to hang): prolonged ARM execution without
  BusMaster/MSI is unstable. Narrow the dwell window and consider
  enabling BusMaster before the last stage.

### Run command

Only stage 0. Full battery-drain recovery policy still applies if the
harness aborts before insmod on BAR0 CTO:

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0
```

Post-run: capture `journalctl -k -b 0 --since "10 minutes ago" > phase5/logs/test.182.journalctl.txt`,
update RESUME_NOTES with the POST-TEST.182 observation, commit, push.

### Pre-test HW state expected

Same as test.181 post-run: endpoint `03:00.0` shows `Mem- BusMaster-` with
BAR regions `[disabled]`. This is the normal post-rmmod state and will
re-initialise on next insmod.

---

## Previous state (2026-04-20, POST test.181 — BREAKTHROUGH: ARM release works, firmware running)

### TEST.181 RESULT — brcmf_chip_set_active SUCCESS; ARM CR4 running; host stable

Captured artifacts:
- `phase5/logs/test.181.stage0`
- `phase5/logs/test.181.stage0.stream`
- `phase5/logs/test.181.journalctl.txt`

Result: **SUCCESS — ARM is running firmware and the host survived 30 s.**

Decisive sequence:
```
BCM4360 test.181: pre-set-active ARM CR4 IOCTL=0x00000021 RESET_CTL=0x00000000 CPUHALT=YES
BCM4360 test.181: calling brcmf_chip_set_active resetintr=0xb80ef000 (BusMaster stays cleared)
BCM4360 test.65 activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0002 (BusMaster preserved)
BCM4360 test.181: brcmf_chip_set_active returned true
BCM4360 test.181: post-set-active-20ms  ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 CPUHALT=NO
BCM4360 test.181: post-set-active-100ms ARM CR4 IOCTL=0x00000001 RESET_CTL=0x00000000 CPUHALT=NO
BCM4360 test.181: released fw/nvram after brcmf_chip_set_active probes; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
=== Capture complete ===
Cleaning up brcmfmac...
```

### Interpretation — what the numbers say

- `pre-set-active` IOCTL=0x0021: CPUHALT bit (0x20) + CLK-something bit (0x01)
  set — ARM is halted.
- After `brcmf_chip_set_active` the IOCTL reads 0x0001: the 0x20 CPUHALT bit
  has been cleared while 0x01 stays on. `RESET_CTL` stays 0 (ARM not in
  reset). This is exactly the signature of a successful CR4 release.
- Both post probes (20 ms and 100 ms) show the same stable IOCTL=0x0001 /
  CPUHALT=NO. ARM CR4 is running firmware continuously.
- The activate op logged "rstvec=0xb80ef000 to TCM[0]; CMD=0x0002
  (BusMaster preserved)". `CMD=0x0002` means Memory Space is enabled but
  BusMaster and I/O are disabled — firmware cannot DMA to host memory,
  as intended.
- No MCE, no PCIe AER, no panic. Clean `-ENODEV` return, clean rmmod, no
  SMC reset needed. The 30 s harness dwell completed normally with ARM
  running in the background.
- Post-run lspci shows endpoint `Mem- BusMaster- CommClk-` with regions
  `[disabled]` — that is the normal post-rmmod state when brcmfmac disables
  the device on unload. Not a fault indicator.

### Why this matters

This is the first clean `brcmf_chip_set_active` on BCM4360 via brcmfmac in
this tree. Phase 4B used to crash the host within 100-200 ms of ARM release;
now ARM runs for >30 s without wedging anything. The accumulated safety
changes — SBR on probe, endpoint + root-port ASPM off, CommClk+, BusMaster
cleared before ARM release, full 442 KB fw + 228 B NVRAM + marker in TCM,
explicit ARM re-halt via `brcmf_chip_set_passive` before fw write — are
collectively sufficient to make the CR4 release safe.

The historic Phase-4B "host crashes ~100-200 ms after ARM release" is no
longer reproducible in this configuration. The stability prerequisite for
Phase 5.2's exit criterion (firmware reaches a state where it writes a
shared-memory handshake) is now in place.

### Current HW state after test.181

- `brcmfmac` is unloaded. `brcmutil` remains loaded.
- Endpoint 03:00.0 visible: `Mem- BusMaster-`, BAR regions `[disabled]`,
  `<MAbort-`, link 2.5GT/s x1, ASPM disabled, CommClk-. This is the
  expected post-rmmod state and re-initialises cleanly on next insmod.
- Root port 00:1c.2 visible, clean. No MAbort.
- No kernel panic, MCE, AER, or SMC reset required.

### Recommended next step — PRE test.182

Do **not** run another hardware test until this note and the test.181
artifacts are committed, pushed, and synced.

Best next discriminator: let ARM run, then sample TCM to see whether
firmware has started initialising memory.

Suggested test.182:
1. Keep the test.181 sequence through `post-set-active-100ms`.
2. Add a longer dwell after `post-set-active-100ms`: `msleep(500)` and
   `msleep(1000)` in stages with breadcrumbs `dwell-500ms`, `dwell-1500ms`.
3. After each dwell, re-probe ARM CR4 state and re-read a small TCM window
   — specifically `TCM[0x0..0x1c]` (same 8 words as test.181) plus the
   NVRAM marker at `ramsize - 4`. Compare against the pre-release values
   to detect firmware-originated writes.
4. Release `fw`/`nvram` and return `-ENODEV`. Still do NOT enable
   BusMaster, do NOT enable MSI, do NOT advance to sharedram polling.

Interpretation matrix:
- Any TCM word in 0x0..0x1c changes between the pre-release dump and a
  post-release re-read: firmware is executing and writing to its own TCM.
  Next test expands the TCM scan and starts hunting for the sharedram
  structure address.
- The NVRAM marker changes: firmware has consumed the NVRAM placement
  (normal on successful boot) and likely moved into shared-memory setup.
- No TCM changes after 1.5 s: ARM is running but firmware is wedged in an
  early loop (e.g. waiting for a register that never asserts). Next test
  adds BAR0 reads of chipcommon registers to see whether firmware is
  actively doing backplane I/O.
- Host freezes during the extended dwell: something about prolonged ARM
  execution without BusMaster/MSI is unstable. Narrow the window and
  consider enabling BusMaster before the last dwell stage.

### Pre-test HW state remains the test.181 post-run state

- Endpoint disabled post-rmmod (expected). Next insmod will re-initialise.
- No dirty state. Safe to proceed to test.182 once PRE-test.182 is
  committed.

---

## Previous state (2026-04-20, PRE test.181 — brcmf_chip_set_active isolation)

### PRE-TEST.181 checkpoint

Implemented test.181 as the next boundary after test.180's negative finding:
1. Keep the full chunked BAR2 firmware write.
2. Keep `msleep(100)` after `fw write complete`.
3. Keep host-side resetintr extraction.
4. Keep the 228-byte NVRAM BAR2 write at `0x9ff1c`.
5. Keep the `ramsize - 4` NVRAM marker readback.
6. Keep the 8-word TCM verify dump at offsets `0x0..0x1c`.
7. Keep the INTERNAL_MEM core lookup (expected NULL on BCM4360).
8. Add the ARM release:
   - Read-only probe: `brcmf_pcie_probe_armcr4_state(devinfo, "pre-set-active")`.
   - `mdelay(50)`.
   - Emit breadcrumb "calling brcmf_chip_set_active resetintr=0x%08x
     (BusMaster stays cleared)".
   - `mdelay(50)`.
   - Call `brcmf_chip_set_active(devinfo->ci, resetintr)`; log the bool.
   - `mdelay(20)` then probe with tag `post-set-active-20ms`.
   - `mdelay(80)` then probe with tag `post-set-active-100ms`.
9. Release `fw`/`nvram` and return `-ENODEV` (no sharedram polling, no
   advance into normal attach).

Build status: OK via kernel kbuild. Existing warning only:
`brcmf_pcie_write_ram32` is defined but unused. BTF generation is skipped
because `vmlinux` is unavailable.

`strings brcmfmac.ko | grep test.181` confirms the new markers are present:
- `BCM4360 test.181: calling brcmf_chip_set_active resetintr=0x%08x (BusMaster stays cleared)`
- `BCM4360 test.181: brcmf_chip_set_active returned %s`
- `BCM4360 test.181: released fw/nvram after brcmf_chip_set_active probes; returning -ENODEV`

No `test.180` strings remain in the module binary.

Before running: commit, push, and `sync` this PRE-test.181 checkpoint. Then
run only stage 0:
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

### Hypothesis

Firmware is fully in TCM, NVRAM is placed at `ramsize - 4`, and the NVRAM
marker is 0xffc70038 (non-zero, structurally plausible). The only remaining
unexecuted step in `brcmf_pcie_exit_download_state` for BCM4360 is
`brcmf_chip_set_active(ci, resetintr)`, which:
1. Writes `resetintr` (0xb80ef000) to TCM[0] via the PCIE2 core activate op.
2. Calls `brcmf_chip_resetcore(arm_cr4, ARMCR4_BCMA_IOCTL_CPUHALT, 0, 0)`,
   which de-asserts ARM reset with the CPUHALT IOCTL bit cleared — ARM CR4
   starts executing firmware at the reset vector in TCM[0].

The Phase 4B history shows early attempts to release ARM on BCM4360 crashed
the host within 100-200 ms. Since then we have added substantial safety:
endpoint ASPM off, root-port ASPM off, CommClk+, BusMaster cleared, SBR on
probe, full 442 KB fw + NVRAM + marker all verified. Firmware cannot DMA to
host because BusMaster is cleared. If the host still freezes on set_active,
the ARM CR4 takeover itself — not stray DMA or link state — is the cause.

### Interpretation matrix

- Reaches `post-set-active-20ms` with ARM CR4 IOCTL CPUHALT bit clear
  (CPUHALT=NO, RESET_CTL=0): ARM release is clean and firmware is executing.
  Next test can extend the dwell and sample TCM sharedram region for the
  firmware init handshake.
- Reaches `post-set-active-20ms` with CPUHALT=YES: set_active did not
  actually un-halt ARM (set_active returned true but CR4 is still halted).
  Next test probes the ARM CR4 IOCTL register state around the call in more
  detail, and may add a manual `resetcore` call with explicit bitmasks.
- Freezes between `calling brcmf_chip_set_active` and `brcmf_chip_set_active
  returned`: the activate op or the CR4 resetcore itself is the trigger.
  Next test splits the two: call `chip->ops->activate(...)` directly, probe,
  then call `brcmf_chip_resetcore(arm_cr4, ARMCR4_BCMA_IOCTL_CPUHALT, 0, 0)`.
- Freezes between set_active return and `post-set-active-20ms`: ARM runs
  firmware which almost immediately wedges the host — consistent with Phase
  4B behavior. Next test either re-halts ARM within the 20 ms window or
  instruments firmware-side activity via TCM sharedram reads before release.
- Freezes between `post-set-active-20ms` and `post-set-active-100ms`:
  firmware survives the first 20 ms and wedges between 20 and 100 ms. Narrow
  the window further.
- `brcmf_chip_set_active` returned false (we'd log the false return, then
  still probe): chip.c treated the CR4 set_active as a no-op. Rare path, but
  flag it and decide next step from the probe output.

### Pre-test HW state (test.180 post-run, verified 2026-04-20 18:44)

- `brcmfmac` is unloaded. `brcmutil` remains loaded.
- Endpoint 03:00.0 visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled, CommClk+.
- Root port 00:1c.2 visible, clean. No dirty state.

Re-run `lspci -vvv -s 03:00.0` in the harness before insmod to confirm.

---

## Previous state (2026-04-20, POST test.180 — INTERNAL_MEM core absent on BCM4360)

### TEST.180 RESULT — negative result: INTERNAL_MEM core not found

Captured artifacts:
- `phase5/logs/test.180.stage0`
- `phase5/logs/test.180.stage0.stream`
- `phase5/logs/test.180.journalctl.txt`

Result: **SUCCESS / no crash.** test.180 completed the full 442233-byte BAR2
firmware write, slept for 100 ms, read host resetintr, wrote the 228-byte NVRAM
blob to BAR2 at `0x9ff1c`, read back the `ramsize - 4` NVRAM marker, read
eight 32-bit words from TCM offsets `0x0..0x1c`, attempted the INTERNAL_MEM
core lookup, logged `INTERNAL_MEM core not found — resetcore skipped`,
released `fw`/`nvram`, returned `-ENODEV`, waited the harness's 30 seconds,
and cleaned up without freezing.

Key persisted markers:
```
BCM4360 test.180: fw write complete (442233 bytes)
BCM4360 test.180: after post-fw msleep(100)
BCM4360 test.180: host resetintr=0xb80ef000 before NVRAM
BCM4360 test.180: pre-NVRAM write address=0x9ff1c len=228 naddr=ffffcf598249ff1c
BCM4360 test.180: post-NVRAM write done (228 bytes)
BCM4360 test.180: NVRAM marker at ramsize-4 = 0xffc70038
BCM4360 test.180: TCM[0x0000]=0xb80ef000
BCM4360 test.180: TCM[0x0004]=0xb82ef000
BCM4360 test.180: TCM[0x0008]=0xb839f000
BCM4360 test.180: TCM[0x000c]=0xb844f000
BCM4360 test.180: TCM[0x0010]=0xb852f000
BCM4360 test.180: TCM[0x0014]=0xb860f000
BCM4360 test.180: TCM[0x0018]=0xb86ef000
BCM4360 test.180: TCM[0x001c]=0xb87cf000
BCM4360 test.180: INTERNAL_MEM core not found — resetcore skipped
BCM4360 test.180: released fw/nvram after INTERNAL_MEM resetcore; returning -ENODEV
```

### Interpretation

Important negative result. The upstream `brcmf_pcie_exit_download_state`
guards the INTERNAL_MEM resetcore behind `chip == 4360 || chip == 43602`, but
on this BCM4360 device `brcmf_chip_get_core(ci, BCMA_CORE_INTERNAL_MEM)`
returns NULL — there is no separate INTERNAL_MEM BCMA core in the BCM4360
core list we built during chip_attach. The upstream branch is effectively a
no-op on our chip.

Consequence: for BCM4360, the remaining work in `brcmf_pcie_exit_download_state`
is just the `brcmf_chip_set_active(ci, resetintr)` call, which writes
`resetintr` to the ARM reset vector, takes ARM out of reset, and lets firmware
run. This is the single highest-risk operation still unexecuted in the clean
path.

The NULL result also means we do **not** need to worry about an INTERNAL_MEM
resetcore side effect; we can proceed directly from the known-safe test.180
state to isolating `brcmf_chip_set_active(..., resetintr)`.

### Current HW state after test.180

- `brcmfmac` is unloaded. `brcmutil` remains loaded.
- Endpoint 03:00.0 visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled, CommClk+.
- Root port still enumerated; no dirty state.

### Recommended next step — PRE test.181

Do **not** run another hardware test until this note and the test.180 artifacts
are committed, pushed, and synced.

Best next discriminator: probe the internals of `brcmf_chip_set_active`
before calling it, then call it.

`brcmf_chip_set_active` in chip.c does two things for a CR4 chip:
1. Call `brcmf_chip_cr4_set_active(ci, rstvec)` which writes `rstvec` to the
   ARM reset-vector register and un-halts the CR4 via `brcmf_chip_resetcore`
   on the ARM core with `ARMCR4_BCMA_IOCTL_CPUHALT` cleared.
2. Which triggers firmware execution.

Recommended test.181 approach — instrument, then call:
1. Keep the test.180 sequence through the INTERNAL_MEM core lookup
   (which will log `not found — skipped` again).
2. Add a read-only probe of the CR4 ARM core reset/control registers
   immediately before the set_active call (reuse the existing
   `brcmf_pcie_probe_armcr4_state` helper with tag `pre-set-active`).
3. Call `brcmf_chip_set_active(devinfo->ci, resetintr)` and check its return.
4. Add a post-set_active ARM probe (`post-set-active`) with a short
   `mdelay(20)` first, to catch whether the host freezes the moment ARM runs.
5. Release `fw`/`nvram` and return `-ENODEV` (do not advance into the normal
   attach / sharedram polling path yet).

Interpretation matrix:
- Freezes between `pre-set-active` and `post-set-active`: ARM CR4 release
  itself is the crash trigger — firmware starts executing and immediately
  wedges the link/host, consistent with Phase 4B behavior.
- Reaches `post-set-active` and ARM state shows CPUHALT=NO / RESET_CTL=0:
  ARM is running safely for at least 20 ms. Next test adds a longer dwell
  and checks sharedram for the firmware init signature.
- `brcmf_chip_set_active` returns false (we return -EIO): chip.c treated the
  CR4 set_active as failed; capture which sub-step failed in chip.c logs.

### Pre-test HW state remains the test.180 post-run state (verified 18:44)

- `MAbort-`, `CommClk+`, link 2.5GT/s x1, endpoint ASPM disabled.
- Safe to proceed directly to test.181 once PRE-test.181 is committed.

---

## Previous state (2026-04-20, PRE test.180 — INTERNAL_MEM resetcore discriminator)

### PRE-TEST.180 checkpoint

Implemented test.180 as the next boundary after test.179's success:
1. Keep the full chunked BAR2 firmware write.
2. Keep `msleep(100)` after `fw write complete`.
3. Keep host-side resetintr extraction.
4. Keep the 228-byte NVRAM BAR2 write at `0x9ff1c`.
5. Keep the `ramsize - 4` NVRAM marker readback.
6. Keep the 8-word TCM verify dump at offsets `0x0..0x1c`.
7. Add only the first half of `brcmf_pcie_exit_download_state`:
   - `brcmf_chip_get_core(ci, BCMA_CORE_INTERNAL_MEM)`.
   - If present, `mdelay(50)` → `brcmf_chip_resetcore(core, 0, 0, 0)`
     → `mdelay(50)`, with `pre-resetcore INTERNAL_MEM core->base=... rev=...`
     and `post-resetcore INTERNAL_MEM complete` log lines.
   - If absent, log `INTERNAL_MEM core not found — resetcore skipped`.
8. Release `fw`/`nvram` and return `-ENODEV`.
9. Still skip `brcmf_chip_set_active(ci, resetintr)`, device-side resetintr
   use, broad TCM dumps, and ARM release.

Build status: OK via kernel kbuild. Existing warning only:
`brcmf_pcie_write_ram32` is defined but unused. BTF generation is skipped
because `vmlinux` is unavailable.

`strings brcmfmac.ko | grep test.180` confirms these new markers are present:
- `BCM4360 test.180: pre-resetcore INTERNAL_MEM core->base=0x%08x rev=%u`
- `BCM4360 test.180: post-resetcore INTERNAL_MEM complete`
- `BCM4360 test.180: INTERNAL_MEM core not found — resetcore skipped`
- `BCM4360 test.180: released fw/nvram after INTERNAL_MEM resetcore; returning -ENODEV`

No `test.179` strings remain in the module binary.

Before running: commit, push, and `sync` this PRE-test.180 checkpoint. Then run
only stage 0:
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

### Hypothesis

`brcmf_pcie_exit_download_state()` performs two chip-touching operations:
internal-memory core reset, then `brcmf_chip_set_active(..., resetintr)` which
releases ARM. On BCM4360 we've never run this function cleanly — the old
host-crash path was everywhere downstream. test.180 asks whether the first
half alone (INTERNAL_MEM resetcore, no set_active, no ARM release) is safe.

If it is, the next test can focus narrowly on `brcmf_chip_set_active` and ARM
release as the remaining half, with firmware + NVRAM + internal-mem core
reset all known-safe beneath it.

### Interpretation matrix

- Survives with `INTERNAL_MEM core not found`: chip topology lacks that
  core on BCM4360 (or `brcmf_chip_get_core` returns NULL for it). Record the
  fact and plan test.181 against `brcmf_chip_set_active(..., resetintr)` only.
- Survives with `pre-resetcore` + `post-resetcore` both logged and clean rmmod:
  INTERNAL_MEM core reset is safe; next test isolates
  `brcmf_chip_set_active(..., resetintr)` / ARM release.
- Freezes between `pre-resetcore` and `post-resetcore`: `brcmf_chip_resetcore`
  on INTERNAL_MEM is itself the next unsafe operation. Next test adds
  register-level probing of INTERNAL_MEM reset state rather than calling the
  library helper.
- Freezes after `post-resetcore` but before the harness `-ENODEV` return: the
  post-resetcore settle is itself a boundary; extend the mdelay and add further
  breadcrumbs.

### Pre-test HW state (still the test.179 post-run state, 2026-04-20 18:34)

- `brcmfmac` is unloaded. `brcmutil` remains loaded.
- Endpoint 03:00.0 visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled.
- Endpoint AER UESta clear; correctable `Timeout+ AdvNonFatalErr+` remains.
- Root port 00:1c.2 visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

Re-run `lspci -vvv -s 03:00.0` in the harness before insmod to confirm no
fresh dirty state.

---

## Previous state (2026-04-20, POST test.179 — tiny TCM verify SUCCESS)

### TEST.179 RESULT — tiny BAR2 TCM verify survives

Captured artifacts:
- `phase5/logs/test.179.stage0`
- `phase5/logs/test.179.stage0.stream`

Result: **SUCCESS / no crash.** test.179 completed the full 442233-byte BAR2
firmware write, slept for 100 ms, read host resetintr, wrote the 228-byte NVRAM
blob to BAR2 at `0x9ff1c`, read back the `ramsize - 4` NVRAM marker, read eight
32-bit words from TCM offsets `0x0..0x1c`, released `fw`/`nvram`, returned
`-ENODEV`, waited the harness's 30 seconds, and cleaned up without freezing.

Key persisted markers:
```
BCM4360 test.179: fw write complete (442233 bytes)
BCM4360 test.179: after post-fw msleep(100)
BCM4360 test.179: host resetintr=0xb80ef000 before NVRAM
BCM4360 test.179: pre-NVRAM write address=0x9ff1c len=228 naddr=ffffcf5982c9ff1c
BCM4360 test.179: post-NVRAM write done (228 bytes)
BCM4360 test.179: NVRAM marker at ramsize-4 = 0xffc70038
BCM4360 test.179: TCM[0x0000]=0xb80ef000
BCM4360 test.179: TCM[0x0004]=0xb82ef000
BCM4360 test.179: TCM[0x0008]=0xb839f000
BCM4360 test.179: TCM[0x000c]=0xb844f000
BCM4360 test.179: TCM[0x0010]=0xb852f000
BCM4360 test.179: TCM[0x0014]=0xb860f000
BCM4360 test.179: TCM[0x0018]=0xb86ef000
BCM4360 test.179: TCM[0x001c]=0xb87cf000
BCM4360 test.179: released fw/nvram after tiny TCM verify; returning -ENODEV
```

### Interpretation

Small post-NVRAM BAR2 reads are safe. The current safe boundary now includes
full firmware write, sleeping dwell, host resetintr extraction, NVRAM write,
NVRAM marker readback, and a tiny TCM verify dump. The next meaningful risk is
the downstream `brcmf_pcie_exit_download_state()` path, but that function does
two things: resets the internal-memory core, then calls `brcmf_chip_set_active`
with `resetintr` and releases ARM. Split those apart.

### Current HW state after test.179

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled.
- Endpoint AER UESta is clear; correctable `Timeout+ AdvNonFatalErr+` remains.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### Recommended next step — PRE test.180

Do **not** run another hardware test until this note and the test.179 artifacts
are committed, pushed, and synced.

Best next discriminator: add only the first half of
`brcmf_pcie_exit_download_state()` after the successful test.179 tiny TCM dump:
1. Keep the test.179 sequence through the tiny TCM reads.
2. Get the `BCMA_CORE_INTERNAL_MEM` core and call
   `brcmf_chip_resetcore(core, 0, 0, 0)` if present.
3. Log before/after the internal-memory resetcore.
4. Release `fw`/`nvram` and return `-ENODEV`.
5. Still skip `brcmf_chip_set_active(devinfo->ci, resetintr)`, ARM release,
   shared-RAM polling, and the rest of normal attach.

Expected interpretation:
- Survives: internal-memory resetcore is safe; next test can isolate
  `brcmf_chip_set_active(..., resetintr)` / ARM release.
- Freezes: the internal-memory core reset is the next unsafe operation.

---

## Previous state (2026-04-20, PRE test.179 — tiny TCM verify discriminator)

### PRE-TEST.179 checkpoint

Implemented test.179 as the next boundary after test.178's success:
1. Keep the full chunked BAR2 firmware write.
2. Keep `msleep(100)` after `fw write complete`.
3. Keep host-side resetintr extraction.
4. Keep the 228-byte NVRAM BAR2 write at `0x9ff1c`.
5. Keep the `ramsize - 4` NVRAM marker readback.
6. Add only a tiny BAR2 TCM verify dump: eight 32-bit reads at offsets
   `0x0..0x1c`, logged as `TCM[0x%04x]`.
7. Release `fw`/`nvram` and return `-ENODEV`.
8. Still skip post-write ARM probing, device-side resetintr use,
   exit-download-state, broad TCM dumps, and ARM release.

Build status: OK via kernel kbuild. Existing warning only:
`brcmf_pcie_write_ram32` is defined but unused. BTF generation is skipped
because `vmlinux` is unavailable.

`strings brcmfmac.ko` confirms these markers are present:
- `BCM4360 test.179: NVRAM marker at ramsize-4 = 0x%08x`
- `BCM4360 test.179: TCM[0x%04x]=0x%08x`
- `BCM4360 test.179: released fw/nvram after tiny TCM verify; returning -ENODEV`

Before running: commit, push, and `sync` this PRE-test.179 checkpoint. Then run
only stage0:
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected interpretation:
- Survives: tiny BAR2 TCM readback is safe; next boundary can isolate
  device-side resetintr / exit-download-state work.
- Freezes during the tiny dump: post-NVRAM BAR2 reads beyond the marker are the
  next unsafe operation.

---

## Previous state (2026-04-20, POST test.178 — NVRAM marker readback SUCCESS)

### TEST.178 RESULT — NVRAM marker readback survives

Captured artifacts:
- `phase5/logs/test.178.stage0`
- `phase5/logs/test.178.stage0.stream`

Result: **SUCCESS / no crash.** test.178 completed the full 442233-byte BAR2
firmware write, slept for 100 ms, read host resetintr, wrote the 228-byte NVRAM
blob to BAR2 at `0x9ff1c`, read back the `ramsize - 4` NVRAM marker, released
`fw`/`nvram`, returned `-ENODEV`, waited the harness's 30 seconds, and cleaned
up without freezing.

Key persisted markers:
```
BCM4360 test.178: fw write complete (442233 bytes)
BCM4360 test.178: before post-fw msleep(100)
BCM4360 test.178: after post-fw msleep(100)
BCM4360 test.178: host resetintr=0xb80ef000 before NVRAM
BCM4360 test.178: pre-NVRAM write address=0x9ff1c len=228 naddr=ffffcf598229ff1c
BCM4360 test.178: post-NVRAM write done (228 bytes)
BCM4360 test.178: NVRAM marker at ramsize-4 = 0xffc70038
BCM4360 test.178: released fw/nvram after NVRAM marker readback; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
```

### Interpretation

The NVRAM marker BAR2 readback is safe after the NVRAM write. The old crash
boundary is now downstream of full firmware write, sleeping dwell, host
resetintr extraction, NVRAM write, and marker readback. The next conservative
boundary is a small BAR2 TCM verify dump, still returning before any
device-side resetintr use, exit-download-state transition, or ARM release.

### Current HW state after test.178

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled.
- Endpoint AER UESta is clear; correctable `Timeout+ AdvNonFatalErr+` remains.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### Recommended next step — PRE test.179

Do **not** run another hardware test until this note and the test.178 artifacts
are committed, pushed, and synced.

Best next discriminator: add only a small BAR2 TCM verify dump after the
successful test.178 marker readback, then release and return:
1. Keep the test.178 sequence through `NVRAM marker at ramsize-4`.
2. Read/log a small fixed TCM window, preferably 8 words at offsets
   `0x0..0x1c`, enough to confirm BAR2 readback without a broad scan.
3. Release `fw`/`nvram` and return `-ENODEV`.
4. Still skip post-write ARM probing, device-side resetintr use,
   exit-download-state, broad TCM dumps, and ARM release.

Expected interpretation:
- Survives: small BAR2 readback is safe; next boundary can isolate
  device-side resetintr / exit-download-state work.
- Freezes during the small dump: post-NVRAM BAR2 reads beyond the marker are
  the next unsafe operation.

---

## Previous state (2026-04-20, PRE test.178 — NVRAM marker readback discriminator)

### PRE-TEST.178 checkpoint

Implemented test.178 as the next boundary after test.177's success:
1. Keep the full chunked BAR2 firmware write.
2. Keep `msleep(100)` after `fw write complete`.
3. Keep host-side resetintr extraction.
4. Keep the 228-byte NVRAM BAR2 write at `0x9ff1c`.
5. Add only the NVRAM marker readback:
   `brcmf_pcie_read_ram32(devinfo, devinfo->ci->ramsize - 4)`.
6. Release `fw`/`nvram` and return `-ENODEV`.
7. Still skip post-write ARM probing, device-side resetintr use, TCM dump, and
   ARM release.

Build status: OK via kernel kbuild. Existing warning only:
`brcmf_pcie_write_ram32` is defined but unused. BTF generation is skipped
because `vmlinux` is unavailable.

`strings brcmfmac.ko` confirms these markers are present:
- `BCM4360 test.178: post-NVRAM write done (%u bytes)`
- `BCM4360 test.178: NVRAM marker at ramsize-4 = 0x%08x`
- `BCM4360 test.178: released fw/nvram after NVRAM marker readback; returning -ENODEV`

Before running: commit, push, and `sync` this PRE-test.178 checkpoint. Then run
only stage0:
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected interpretation:
- Survives: NVRAM marker/readback is safe; next boundary can add the small TCM
  verify dump or device-side resetintr/exit-download-state work.
- Freezes before marker value is logged: BAR2 readback from `ramsize - 4` is
  the isolated unsafe operation.
- Freezes after marker value is logged: marker readback completed and the
  return/unwind path needs the next discriminator.

---

## Previous state (2026-04-20, POST test.177 — NVRAM BAR2 write SUCCESS)

### TEST.177 RESULT — NVRAM BAR2 write after safe sleep/resetintr survives

Captured artifacts:
- `phase5/logs/test.177.stage0`
- `phase5/logs/test.177.stage0.stream`

Result: **SUCCESS / no crash.** test.177 completed the full 442233-byte BAR2
firmware write, slept for 100 ms after `fw write complete`, read resetintr from
host firmware memory, wrote the 228-byte NVRAM blob to BAR2 at `0x9ff1c`,
released `fw`/`nvram`, returned `-ENODEV`, waited the harness's 30 seconds, and
cleaned up without freezing.

Key persisted markers:
```
BCM4360 test.177: fw write complete (442233 bytes)
BCM4360 test.177: before post-fw msleep(100)
BCM4360 test.177: after post-fw msleep(100)
BCM4360 test.177: host resetintr=0xb80ef000 before NVRAM
BCM4360 test.177: pre-NVRAM write address=0x9ff1c len=228 naddr=ffffcf5982c9ff1c
BCM4360 test.177: post-NVRAM write done (228 bytes)
BCM4360 test.177: released fw/nvram after NVRAM write; returning -ENODEV
BCM4360 test.163: download_fw_nvram returned ret=-19 (expected -ENODEV for skip_arm=1)
BCM4360 test.163: fw released; returning from setup (state still DOWN)
```

### Interpretation

The NVRAM BAR2 write is safe after the sleeping dwell and host resetintr
extraction. The old crash boundary is now further downstream than the raw NVRAM
write. The next untested boundary is reading back the NVRAM marker at
`ramsize - 4` after the NVRAM write.

### Current HW state after test.177

- `brcmfmac` is unloaded. `brcmutil` remains loaded from the harness; USB Wi-Fi
  stack modules remain unrelated.
- Endpoint 03:00.0 is visible: `Mem+ BusMaster-`, BAR0=b0600000, BAR2=b0400000,
  `<MAbort-`, link 2.5GT/s x1, endpoint ASPM disabled.
- Endpoint AER UESta is clear; correctable `Timeout+ AdvNonFatalErr+` remains.
- Root port 00:1c.2 is visible: bus 03/03, memory window b0400000-b06fffff,
  bridge `MAbort-`, secondary `<MAbort-`, link 2.5GT/s x1, ASPM disabled.

### Recommended next step — PRE test.178

Do **not** run another hardware test until this note and the test.177 artifacts
are committed, pushed, and synced.

Best next discriminator: add only the NVRAM marker/readback after the successful
test.177 NVRAM write, then release and return:
1. Keep the test.177 sequence through `post-NVRAM write done`.
2. Read/log `brcmf_pcie_read_ram32(devinfo, devinfo->ci->ramsize - 4)`.
3. Release `fw`/`nvram` and return `-ENODEV`.
4. Still skip post-write ARM probe, device-side resetintr use, TCM dump, and
   ARM release.

Expected interpretation:
- Survives: marker/readback is safe; next boundary can add the small TCM verify
  dump or device-side resetintr/exit-download-state work.
- Freezes on/after the marker read: BAR2 readback from the NVRAM/shared-RAM
  marker address is the next unsafe operation.

---

## Previous state (2026-04-20, PRE test.177 — NVRAM BAR2 write discriminator)

### PRE-TEST.177 checkpoint

Implemented test.177 as the next boundary after test.176's success:
1. Keep the full 442233-byte chunked BAR2 firmware write.
2. Keep the proven-safe `msleep(100)` after `fw write complete`.
3. Keep host-side `resetintr = get_unaligned_le32(fw->data)` and log it.
4. Add only the NVRAM BAR2 write using a bounded iowrite32 loop at
   `rambase + ramsize - nvram_len`.
5. Release `fw`/`nvram` and return `-ENODEV`.
6. Still skip post-write ARM probing, device-side resetintr use, NVRAM
   marker/readback, TCM dump, and ARM release.

Build status: OK via kernel kbuild. Existing warning only:
`brcmf_pcie_write_ram32` is defined but unused. BTF generation is skipped
because `vmlinux` is unavailable.

`strings brcmfmac.ko` confirms these markers are present:
- `BCM4360 test.177: host resetintr=0x%08x before NVRAM`
- `BCM4360 test.177: pre-NVRAM write address=0x%x len=%u naddr=%px`
- `BCM4360 test.177: post-NVRAM write done (%u bytes)`
- `BCM4360 test.177: released fw/nvram after NVRAM write; returning -ENODEV`

Before running: commit, push, and `sync` this PRE-test.177 checkpoint. Then run
only stage0:
`sudo /home/kimptoc/bcm4360-re/phase5/work/test-staged-reset.sh 0`

Expected interpretation:
- Survives: NVRAM BAR2 write is safe after sleeping dwell; next test should add
  the NVRAM marker/readback boundary.
- Freezes before `pre-NVRAM write`: the host resetintr-to-NVRAM gap or logging
  is unexpectedly unsafe.
- Freezes after `pre-NVRAM write` but before `post-NVRAM write done`: the NVRAM
  BAR2 iowrite loop is the isolated unsafe operation.
- Freezes after `post-NVRAM write done`: NVRAM write completed but post-write
  return/unwind timing needs isolation.

---

## Previous state (2026-04-20, POST test.176 — host resetintr SUCCESS)

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


## POST-TEST.187 (2026-04-20) — Probe A skipped due to wrong TCM-base assumption; no new signal

Captured artifacts:
- `phase5/logs/test.187.stage0`
- `phase5/logs/test.187.stage0.stream`
- `phase5/logs/test.187.journalctl.txt` (449 lines)

Result: **clean run, host stable, returned -ENODEV as designed.**
Probe A (TCM instruction snapshot around resetintr) was skipped because
`resetintr_offset = 0xef000` exceeds `ramsize = 0xa0000`. The assumption
that `resetintr - 0xb8000000` maps to TCM offset is incorrect for BCM4360.

### Observed behaviour

All readings identical to test.186d:
- ARM CR4: IOCTL 0x21→0x01 (CPUHALT cleared), IOSTATUS=0, RESET_CTL=0
- D11 core: IOCTL=0x07, IOSTATUS=0x00, RESET_CTL=0x01 (in reset)
- TCM regions: header, wide grid, tail all unchanged across dwells
- Backplane registers: pmutimer advances, pmucontrol bit 9 flipped once
- PCIE2 mailboxint: 0x0 (no D2H, no FN0 bits)

Probe A log output:
```
test.187: resetintr offset 0xef000 out of TCM range (ramsize=0xa0000), skipping
test.187: dwell-500ms  resetintr offset 0xef000 out of range, skipping
test.187: dwell-1500ms resetintr offset 0xef000 out of range, skipping
test.187: dwell-3000ms resetintr offset 0xef000 out of range, skipping
```

### Interpretation

1. **Probe A non-functional**: The `0xb8000000` TCM-base assumption is wrong
   for BCM4360. `resetintr = 0xb80ef000` likely points to ARM boot ROM, not
   TCM. Even if sampled, it would read empty TCM, not executing code.

2. **No new signal**: Test.187 adds no new data beyond test.186d. The
   "resetintr out of range" warnings are the only observable difference.

3. **Probe D not implemented**: The promised firmware-integrity check
   (compare fw->data with TCM readback) was not implemented.

4. **DMA-stall already falsified**: As established in POST-TEST.186d,
   BusMaster ON/OFF makes no difference; DMA-stall hypothesis remains
   falsified.

### Lessons for next test

- **Fix or drop probe A**: Either sample TCM[0..fw->size] at evenly spaced
  offsets (actual firmware region), or drop the resetintr probe entirely.
- **Implement probe D**: Cheapest way to rule out firmware corruption.
- **Avoid redundant probes**: D11 state is already sampled in all tests;
  need new signal, not re-collection of known data.
- **Reframe hypothesis**: Firmware shows no MMIO/TCM activity → likely
  faulting before reaching peripheral init, not stuck in D11 bring-up.

---

## PRE-TEST.188 (2026-04-21) — firmware-integrity check + fine-grain CR4/D11 sampling (reordered)

### Hypothesis
ARM is released (CPUHALT YES→NO) but produces zero observable MMIO/TCM
activity across ≥ 3 s of dwell time (tests 184–187). Likely causes:
(1) firmware early exception/spin-loop; (2) missing register writes
specific to BCM4360 that proprietary `wl` performs.

Leading hypothesis: early exception/spin-loop.

### Predictions
- **All 256 integrity samples MATCH + all tier-1/tier-2 UNCHANGED:**
  firmware image intact, but firmware truly idle. Next: inspect
  CR4 wrapper fault/exception registers, or cross-reference against
  proprietary `wl` driver reset sequence.
- **ANY firmware-image vs TCM mismatch:** download-path corruption
  confirmed. Investigation shifts to write-path integrity (timing,
  alignment, byte order of the `iowrite32` loop).
- **Fine-grain sampling catches transient activity** (any TCM write,
  D11 release, pmucontrol change beyond bit-9, mailboxint assertion):
  firmware makes partial forward progress before stalling. Focus
  subsequent probes around the time-of-first-activity window.
- **CR4 wrapper IOSTATUS shows non-zero fault/error bits:** wrapper-
  level fault state visible; follow up with dedicated ARM-
  architectural fault-register probe.

### Timing (relative to `brcmf_chip_set_active`)

```
  set_active (≈ 70 ms)
  → 20 ms post-probe
  → 80 ms post-probe
  → tier-1: 10 × 5 ms  ≈ ~100–150 ms      (catch early fault)
  → tier-2: 30 × 50 ms ≈ ~150–1650 ms      (catch mid-range)
  → dwell-3000 ms      ≈ ~1650–3000 ms      (late persistence)
  → cleanup + -ENODEV
```

### What changed in pcie.c
1. Removed test.187 residue (`pre_resetintr[64]`, `resetintr_offset`).
2. Added fw-integrity probe D (256 samples).
3. **Reordered fine-grain tiers to run BEFORE the dwell grid**
   (feedback_qwen.md option 2a). Dropped 500/1500 ms dwell samples;
   kept 3000 ms only. Total in-module time ≈ 4.6 s.
4. Relabelled breadcrumbs: test.186d → test.188.

### Risk
Read-only BAR2 reads + minimal state-machine probes. No writes
beyond existing firmware-download path. Module early-returns
-ENODEV; `pci_clear_master` always executed.

### Build status
Module rebuilt clean. Frame-size warning resolved; only pre-existing
`brcmf_pcie_write_ram32 defined but not used` warning remains.

### Run command
```
sudo ./phase5/work/test-staged-reset.sh 0
```

PCIe pre-test: verify no MAbort+ on `lspci -vvv -s 03:00.0`.

---

## Downstream Survey (Phase6) — 2026-04-22

Completed survey of downstream Linux kernel forks and community patches for
BCM4360 bringup code missing from upstream brcmfmac.

**Sources examined:**
- Local `wl` driver analysis (`phase6/NOTES.md`) — identified ~50 PMU/PLL/PCIe
  initialisation functions that `wl` calls before ARM release and `brcmfmac`
  does not.
- Local kernel source (`phase3/work/linux-6.12.80`) — no BCM4360-specific
  bring‑up code present; BCM4387 support is upstream.
- Local patch (`phase3/patches/0001-brcmfmac-add-BCM4360-support.patch`) —
  only adds device IDs, no register‑level init.

**Key finding:** The highest‑priority missing prerequisite is PMU resource‑mask
and PLL initialisation. Firmware flips PMU control bit‑9 (HT availability
request) and spins waiting for HT clock; without host‑side PMU resource mask
and PLL configuration, the firmware can never proceed.

Full survey written to `phase6/downstream_survey.md`, committed as ea61dc9.

## ANALYSIS.001 (2026-04-21) — BCM4360 PMU/PCIe init gap analysis

**Hypothesis:** brcmfmac skips PCIe2 core bring‑up and PMU resource‑mask writes that bcma driver performs for BCM4360, causing firmware to stall after ARM release.

**Sources surveyed:**
- Asahi Linux bcma driver (`driver_chipcommon_pmu.c`, `driver_pcie2.c`)
- Upstream brcmfmac (`chip.c`, `pcie.c`)
- OpenWrt broadcom‑wl package (presence of BCM4360 firmware, no driver patches found)
- Broadcom‑sta variants (broadcom‑wl, debian, aur) — not examined in detail (deferred)

**Findings:**

1. **Missing PCIe2 core initialization:** brcmfmac's `brcmf_pcie_attach` returns early for BCM4360 (pcie.c:895), skipping all PCIe2 register writes:
   - `PCIE2_CLK_CONTROL` DLYPERST/DISSPROMLD workaround (BCM4360 rev>3)
   - LTR (Latency Tolerance Reporting) configuration
   - Power‑management clock‑period, PMCR_REFUP, SBMBX writes

2. **Missing PMU initialization:** brcmfmac performs no PMU register writes:
   - `BCMA_CC_PMU_CTL` NOILPONW bit (depends on pmurev)
   - `BCMA_CC_PMU_MINRES_MSK` / `MAXRES_MSK` (unknown for BCM4360 — bcma has no case; must be extracted from wl.ko)
   - No PLL programming (bcma also has none for BCM4360)

3. **BCMA sequence for BCM4360:**
   - `bcma_pmu_early_init` → `bcma_pmu_init` → `bcma_pmu_pll_init` → `bcma_pmu_resources_init` (sets resource masks) → `bcma_pmu_workarounds` (none for BCM4360)
   - `bcma_core_pcie2_init` → sets reqsize=1024, applies clock‑delay workaround (rev>3), configures LTR, PM‑clock period, PMCR_REFUP, SBMBX.

**Ranked missing writes (most likely to unblock firmware):**
1. PCIE2_CLK_CONTROL DLYPERST/DISSPROMLD (BCM4360‑specific workaround)
2. BCMA_CC_PMU_CTL NOILPONW (PMU control bit)
3. BCMA_CC_PMU_MINRES_MSK / MAXRES_MSK (resource grants)
4. PCIE2_LTR_STATE (ACTIVE→SLEEP handshake)
5. PCIE2_PVT_REG_PM_CLK_PERIOD (timer period)

**Next step:** Implement PCIe2 core bring‑up in brcmfmac, starting with the clock‑control workaround.

**Deliverable:** `phase6/pmu_pcie_gap_analysis_final.md`

## POST-TEST.239 (2026-04-23 01:12 BST, boot -1 — same wedge bracket as test.238; sharedram_ptr held `0xffc70038` for all 22 polls) — fw never advanced to shared-struct allocation

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1`. Probe ran cleanly through fw
download, NVRAM write, seed write (footer at 0x9ff14, magic
0xfeedc0de, len 0x100), FORCEHT, `pci_set_master`, and
`brcmf_chip_set_active` (returned TRUE at 01:10:43.523 BST). Ladder
emitted **22 dwell+poll pairs** at t+100, 300, 500, 700, 1000, 1500,
2000, 3000, 5000, 10000, 15000, 20000, 25000, 26000, 27000, 28000,
29000, 30000, 35000, 45000, 60000, 90000 ms (last line 01:12:15
BST). The expected `t+120000ms` pair never landed; journal cut at
01:12:24 (~22 s before that breadcrumb was due). Host wedged; SMC
reset performed by user; current boot 0 started 07:41:38 BST.

### sharedram_ptr poll results

**All 22 polls returned `0xffc70038`** — identical to the NVRAM
length marker our host writes at TCM[ramsize-4] before set_active.
Fw never overwrote that slot during the ≥90 s window. No transient
to a valid RAM address, no `0xffffffff` (no bus-error read), no
garbage value.

```
Apr 23 01:10:43 test.238: t+100ms dwell
Apr 23 01:10:43 test.239: t+100ms sharedram_ptr=0xffc70038
Apr 23 01:10:44 test.238: t+300ms dwell
Apr 23 01:10:44 test.239: t+300ms sharedram_ptr=0xffc70038
... (every pair identical pattern; sharedram_ptr never changes) ...
Apr 23 01:12:15 test.238: t+90000ms dwell
Apr 23 01:12:15 test.239: t+90000ms sharedram_ptr=0xffc70038
<journal ends 01:12:24 — host wedged in [t+90s, t+120s] window>
```

### Key interpretations

1. **Wedge bracket unchanged from test.238** — same [t+98s, t+118s]
   window. So the addition of one MMIO read per dwell did NOT
   destabilise fw or shift the wedge (rules out the
   "polling-causes-wedge" branch from PRE-TEST.239 decision tree).
2. **Fw does not progress through normal init** — upstream brcmfmac's
   `BRCMF_PCIE_FW_UP_TIMEOUT` is 5 s. We waited 18× that. Fw never
   wrote `sharedram_addr` to TCM[ramsize-4]. So fw is either:
   - blocked on a host-side handshake (no doorbell, no IRQ, no
     write to a polling-watched slot by the host), or
   - executing an unrelated internal init that completes (or
     panics) at ~t+100-120s, which then wedges the bus.
3. **Wedge is not an early bus event** — every poll at t<90s read
   the BAR2 window cleanly (returned the marker, never `0xffffffff`).
   So PCIe is healthy throughout fw's ≥90 s execution.
4. **Decision-tree branch hit:** PRE-TEST.239 pre-committed
   *"sharedram_ptr stays 0xffc70038 → Test.240: HostRDY doorbell ring"*.
   That is the next action.

### Caveats

- We did not measure whether fw writes anywhere ELSE in TCM —
  only TCM[ramsize-4]. Fw could be advancing through some other
  state machine that doesn't touch this slot. Test.240 may want to
  spot-check a few other tail-TCM addresses too.
- `brcmf_pcie_read_ram32` uses BAR2 window MMIO. Same op already
  proven safe in tests 188/218/226. Not a new risk.

### Artifacts

- `phase5/logs/test.239.run.txt` — PRE harness output (truncated at
  "sleeping 240s" because host wedged during sleep)
- `phase5/logs/test.239.journalctl.full.txt` (1458 lines) — full
  boot -1 journal
- `phase5/logs/test.239.journalctl.txt` (387 lines) — filtered
  BCM4360 / brcmfmac subset

---


## PRE-TEST.239 (2026-04-23 00:5x BST, boot 0 post-SMC-reset from test.238) — poll TCM[ramsize-4] at every ladder breadcrumb to observe whether fw writes `sharedram_addr` before the wedge

### Hypothesis

Test.238 proved fw+driver run for ≥90 s post-set_active with the
Apple random_seed present. The wedge window is [t+98 s, t+118 s].
During those ~100 seconds, fw is executing *something* — but we
have no visibility into what.

**Upstream brcmfmac convention** (confirmed in pcie.c@3144-3158):
- Host writes NVRAM → TCM[ramsize-4] = 0xffc70038 (NVRAM length
  marker token).
- Fw boots, parses NVRAM, inits PCIe2 internals, allocates its
  `pcie_shared` struct in its own TCM/scratch, then
  **overwrites TCM[ramsize-4] with the address of that struct**
  (`sharedram_addr`).
- Host detects the change (value ≠ 0xffc70038) and reads the
  struct at that address to bootstrap ringinfo / console /
  mailboxes.

We have never observed this value *during* the dwell ladder. If
fw is functional post-set_active, the sharedram_addr write should
happen at some t* ∈ (0, wedge] — and knowing its timing plus
the address fw hands us is highly diagnostic:

| Observation at ramsize-4 during the ladder | Interpretation |
|---|---|
| Stays at 0xffc70038 through t+90 s | Fw is running (dwells landed) but **has not completed its shared-struct init** — possibly stuck at a pre-alloc step, or waiting on host signal. |
| Changes to a valid RAM address at some t* | Fw completed shared-struct init at t*; we now know (a) fw boots correctly up to that step, (b) WHERE its pcie_shared struct lives → we can read ringinfo/console from that address on subsequent tests. |
| Changes to 0xffffffff (all-ones) | Bus error on the readback, not a fw write — indicates device disappeared from PCIe bus at that point. |
| Changes to a bogus value (e.g. 0x0, or address outside RAM) | Fw wrote something, but its internal state is inconsistent; likely this path diverges before sharedram alloc completes. |

This is a **zero-intervention observation test** — we only READ
TCM during dwells, no writes. No new hypothesis about fw expected
behaviour; just instrumentation of an already-documented protocol.

### Why polling, not sentinel-write (per prior advisor)

Advisor proposed writing a sentinel (e.g. 0xdeadbeef) at ramsize-4
before set_active to test whether fw reads from that slot. But the
upstream flow is **fw WRITES there, not reads** — the NVRAM marker
0xffc70038 already sits there (host writes it via NVRAM). Fw is
documented to overwrite, not dereference, that slot on init. So
polling is strictly more informative and costs nothing extra (just
a single MMIO read per dwell line vs. a full pre-set_active write
that fw will clobber anyway). Sentinel-write is strictly inferior
here.

### Code change

1. New module param `bcm4360_test239_poll_sharedram` (default 0).
2. In the test.238 ladder, after each `pr_emerg("... dwell\n")`,
   if `test239_poll_sharedram` is set, perform:
   ```c
   u32 v = brcmf_pcie_read_ram32(devinfo, devinfo->ci->ramsize - 4);
   pr_emerg("BCM4360 test.239: t+Xms sharedram_ptr=0x%08x\n", v);
   ```
   Emit one breadcrumb per ladder step (23 lines total alongside
   the 23 dwell lines).
3. Keep everything else identical — same ultra ladder, same seed,
   same pre-set_active path.

### Run sequence

```bash
# Build first
make -C phase5/work

# Then, this boot (after SMC-reset post-test.238):
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Budget 240 s per test.238 precedent. Sysctls nmi_watchdog=1,
hardlockup_panic=1, softlockup_panic=1 armed as before.

### Pre-committed test.240 decision tree (per advisor)

Before running test.239, here's what each outcome branches to —
pre-committed to avoid post-hoc "consistent with plan" bias:

| Test.239 observation | Test.240 direction |
|---|---|
| sharedram_ptr stays 0xffc70038 through last landed dwell | Fw boots but never reaches shared-struct allocation. Test.240: add a host "HostRDY" doorbell ring (H2D_MAILBOX_0 or equivalent) during an early dwell to see if fw is blocked on host handshake. |
| sharedram_ptr changes to a valid RAM address at t=T* | Fw completed shared-struct init at T*. Test.240: read the pcie_shared struct from that address, log its fields (ring_info_addr, console_addr, mailbox addrs) and share-magic. No fw change needed — pure observation, should be clean. |
| sharedram_ptr changes to 0xffffffff | Bus error reading the slot (device disappeared from BAR2 window). Test.240: narrow when the bus-error condition starts by cross-referencing with last landed dwell; investigate PCIe config space post-test. |
| sharedram_ptr changes to a non-RAM non-marker non-all-ones value | Fw wrote garbage. Test.240: inspect what it wrote — could be a bug in our test, a chip quirk, or a firmware internal that overwrites the slot for different reasons. Read nearby TCM to see if a struct was written. |
| Wedge moves EARLIER than test.238 (< t+90s) | Polling destabilises the bus during fw run (advisor's H2). Test.240: reduce poll frequency (only at t+10, 30, 60, 90 s) to confirm the dose-response; if wedge moves with poll count, polling itself is the cause. |
| Wedge moves LATER (> t+118 s) | Polling somehow buys fw time — the read MMIO may act as a heartbeat to fw. Test.240: deliberately add extra reads spaced through the ladder to see if wedge recedes further. |

### Safety — MMIO read during dwells

`brcmf_pcie_read_ram32` uses BAR2 window access — pure read, no
side effects. Test.188/test.226/test.218 already demonstrate
repeated TCM reads inside the probe are safe. One extra read per
dwell point is within the noise of existing activity.

### Hardware state (current, 00:55 BST boot 0 post-SMC-reset)

- `lspci -vvv -s 03:00.0`: Control Mem+ BusMaster+, MAbort-, fast.
- **BAR0 timing PRE**: reads cleanly (dword `0x203a6464` via dd
  against resource0). The I/O error recorded in test.238's PRE
  was a one-off, not a persistent issue — current boot is clean.
- No modules loaded.

### Build status — REBUILT CLEAN

Built 2026-04-23 ~00:57 BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
`strings brcmfmac.ko | grep test.239` shows all 23 breadcrumbs
(t+100ms..t+120000ms sharedram_ptr=%08x) plus the new module
param `bcm4360_test239_poll_sharedram`. Pre-existing
unused-variable warnings only — no regressions.

### Expected artifacts

- `phase5/logs/test.239.run.txt` — PRE harness + insmod output
- `phase5/logs/test.239.journalctl.full.txt` — full boot -1 journal
- `phase5/logs/test.239.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + strings verify before insmod.
2. PCIe state: clean post-SMC-reset above.
3. Hypothesis: stated above.
4. Plan: in this block; commit+push+sync before insmod.
5. Filesystem sync on commit.

---
## POST-TEST.240 (2026-04-23 08:03 BST, boot -1 — DB1 ring at t+2000ms landed with readback=0x00000000; wide-TCM scan held NVRAM text across all 22 dwells; wedge bracket unchanged from test.238/239)

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1 bcm4360_test240_ring_h2d_db1=1
bcm4360_test240_wide_poll=1`. Probe ran fw download → NVRAM write
→ seed write → FORCEHT → `pci_set_master` → `brcmf_chip_set_active`
cleanly; set_active returned TRUE at 08:02:46 BST. At the t+2000ms
breadcrumb, the driver wrote `1` to BAR0+0x144 via
`brcmf_pcie_write_reg32`; readback immediately after was
`0x00000000`, not `1`.

The ultra-extended ladder then emitted **22 dwell+sharedram_poll+
wide-poll triples** at t+100, 300, 500, 700, 1000, 1500, 2000, 3000,
5000, 10000, 15000, 20000, 25000, 26000, 27000, 28000, 29000, 30000,
35000, 45000, 60000, 90000 ms (last line 08:03:53 BST). The
`t+120000ms` triple never landed; host wedged. User performed SMC
reset; current boot 0 started 08:09:57 BST.

### DB1 ring evidence

```
Apr 23 08:02:46 test.238: t+2000ms dwell
Apr 23 08:02:46 test.240: ringing H2D_MAILBOX_1 (BAR0+0x144)=1 at t+2000ms
Apr 23 08:02:46 test.240: H2D_MAILBOX_1 ring done; readback=0x00000000
Apr 23 08:02:46 test.239: t+2000ms sharedram_ptr=0xffc70038
```

The sharedram_ptr poll immediately after the ring returned the
NVRAM marker unchanged — DB1 had no effect on that slot at t+2000ms
or any later dwell.

### sharedram_ptr polls

All 22 returned `0xffc70038` — identical to test.239.

### Wide-TCM scan (ramsize-64..ramsize-8, 15 dwords per dwell)

All 22 dwells returned the same 15 little-endian dwords, which
decode byte-wise to NVRAM text:

```
7600303d 69646e65 78303d64 34653431 76656400 303d6469 61333478 74780030
72666c61 343d7165 30303030 32616100 00373d67 67356161 0000373d
→ "=0.vendian=0x14e4.devid=0x43a0.xtalfreq=40000000.aa2g=7.aa5g=7.."
```

This is the tail of the NVRAM text we write to TCM before
set_active, followed by the 0xffc70038 length marker at ramsize-4
(not included in the 15-dword window). Conclusion: fw has not
written any of these 15 slots during the ≥90 s window.

### Wedge bracket

Unchanged from test.238 ([t+90s, t+120s]). Journal cut at 08:03:53
BST, ~25 s after the last landed dwell (t+90000ms at 08:03:52).
No Oops / Call Trace / softlockup / hardlockup in boot -1.

### Key interpretations

1. **Fw's post-init work, if any, is not in the last 60 bytes of
   TCM.** Upstream brcmfmac's shared-struct slot is TCM[ramsize-4],
   which is within but not the whole of this window; we've now
   proven fw does not touch ANY of ramsize-64..ramsize-4 during the
   pre-wedge window. So if fw IS advancing, it's writing somewhere
   else entirely (e.g., scratch aperture on the chip, a shared
   ring not in tail-TCM, or fw internal RAM outside the BAR2
   window).
2. **DB1 ring is pre-shared-init null.** The readback=0 is
   uninterpretable in isolation because of reading (c) — see
   Current State at top of file for the (a)/(b)/(c) breakdown.
3. **PRE `dd` harness error** at `/sys/bus/pci/.../resource0`
   recurred (third test in a row: test.238/239/240 — misread as
   "clean" in the test.239 block, dword `0x203a6464` ≡ ASCII "dd: ").
   Pre-insmod userspace sysfs read failures are distinct from
   in-driver BAR0 MMIO writes but justify verifying the latter
   explicitly (PRE-TEST.241 plan).

### Artifacts

- `phase5/logs/test.240.run.txt` — PRE harness + insmod output
  (truncated at "sleeping 240s" because host wedged during sleep)
- `phase5/logs/test.240.journalctl.full.txt` (1527 lines) — full
  boot -1 journal
- `phase5/logs/test.240.journalctl.txt` (422 lines) — filtered
  BCM4360 / brcmfmac / watchdog subset

---


## PRE-TEST.240 (2026-04-23 07:4x BST, boot 0 post-SMC-reset from test.239) — ring upstream's HostRDY doorbell (H2D_MAILBOX_1) at t+2000ms + scan a wider tail-TCM window at every dwell

### Hypothesis

Test.239 proved fw is alive ≥90s post-set_active but never overwrites
TCM[ramsize-4] with `sharedram_addr` (upstream brcmfmac's
`BRCMF_PCIE_FW_UP_TIMEOUT` is 5s — we waited 18× that). Branch
hit in PRE-TEST.239's pre-committed decision tree: *"Test.240: add a
host 'HostRDY' doorbell ring (H2D_MAILBOX_0 or equivalent) during
an early dwell"*.

Two choices folded into one cycle:
1. **Doorbell ring on H2D_MAILBOX_1 (BAR0+0x144=1) at t+2000ms.**
   Upstream's `brcmf_pcie_hostready` writes to that exact register
   when the `BRCMF_PCIE_SHARED_HOSTRDY_DB1` flag is set in the
   pcie_shared struct. fw provides that flag, so upstream's gate is
   only satisfied AFTER fw allocates the shared struct — but the
   underlying mailbox register is a hardware register that fw can
   poll any time post-reset. If fw is blocked on host doorbell
   pre-shared-struct, ringing DB1 unconditionally should release it.
   We use DB1 (not DB0) because DB1 is the upstream "host ready"
   slot; DB0 is the general H2D-message-queue slot which expects a
   shared HTOD_MB_DATA struct fw can't have without sharedram.

2. **Wider tail-TCM scan (15 dwords, ramsize-64..ramsize-4) at every
   dwell.** Test.239 only watched a single slot. Fw could be writing
   status / heartbeat / a non-standard sharedram_addr at another
   tail-TCM offset. One MMIO read per dwell already proven safe in
   test.239 (wedge timing unchanged); 15 reads adds negligible bus
   load.

### Expected discriminator outcomes

| Observation | Interpretation |
|---|---|
| sharedram_ptr changes to a valid RAM address within a few dwells of the t+2000ms ring | DB1 was the missing handshake — major progress; document it and start building the full host-side init sequence (next test reads pcie_shared from the new addr). |
| Wide-poll lights up with new values somewhere in tail-TCM (status / heartbeat counter / unknown struct), regardless of where sharedram_ptr stays | Fw IS doing post-init work but at non-standard offsets — read those next test to identify the structure(s). |
| Wedge moves dramatically EARLIER (e.g. wedges within a few s of the t+2000ms ring) | DB1 ring caused destabilisation — possibly fw saw an out-of-sequence doorbell and aborted. Tells us fw IS reading DB1 at this stage, just doesn't expect a write yet — refine timing for next test. |
| Wedge moves dramatically LATER or disappears | Best case: ring was the missing piece; rest of test gets clean BM-clear / -ENODEV / rmmod. |
| All identical to test.239 (wedge same window, sharedram_ptr unchanged, wide-poll all 0xffc70038/garbage) | DB1 ring is a null op pre-shared-init. Pivots to test.241: try DB0 (H2D_MAILBOX_0 = BAR0+0x140), then if also null, pivot to pre-allocating a shared struct in TCM before set_active (build `brcmf_pcie_init_share`-style block ourselves and write its address to TCM[ramsize-4] before set_active so fw has it from the start). |

### Code change

1. Two new module params:
   - `bcm4360_test240_ring_h2d_db1` (default 0) — ring DB1 at t+2000ms
   - `bcm4360_test240_wide_poll` (default 0) — wide tail-TCM scan
2. `BCM4360_T239_POLL` macro extended: when wide_poll is set, scan
   15 extra dwords starting at ramsize-64 in addition to the
   single-slot read at ramsize-4. Only wide-poll lines are new
   (existing test.239 single-slot lines preserved).
3. At the t+2000ms dwell breadcrumb in the ultra ladder, if
   ring_h2d_db1 is set, write 1 to BAR0+0x144 via
   `brcmf_pcie_write_reg32` then read back and log.

All other paths (test.234, test.235, test.237, test.238 baseline,
test.239 baseline) preserved unchanged.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_ring_h2d_db1=1 \
    bcm4360_test240_wide_poll=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Budget 240 s per test.238/239 precedent. Sysctls nmi_watchdog=1,
hardlockup_panic=1, softlockup_panic=1, softlockup_all_cpu_backtrace=1
armed.

### Pre-committed test.241 decision tree

Per advisor — pre-commit branches before running:

| Test.240 outcome | Test.241 direction |
|---|---|
| sharedram_ptr changes / wedge shifts after DB1 ring | Read pcie_shared struct from new addr; log fields (flags, ringinfo_addr, console_addr, htod/dtoh mailbox addrs). No new fw write — pure observation. |
| Wide-poll shows fw writing somewhere in tail-TCM (not ramsize-4) | Dump that region next test; widen scan further if needed. |
| All identical to test.239 (DB1 is null) | Test.241: ring DB0 instead (H2D_MAILBOX_0=0x140) at t+2000ms, otherwise identical. Cheap discriminator. |
| Wedge moves earlier | Investigate timing: try ringing DB1 at later dwell (t+5000ms, t+10000ms) — locate fw's expected window. |

### Safety notes

- H2D_MAILBOX_1 write is a single iowrite32 to BAR0+0x144. Same op
  upstream uses in production. If fw raises a D2H IRQ in response,
  no IRQ handler is registered yet — the line stays at default and
  the host doesn't take an interrupt. Worst case is fw sees a
  doorbell, panics on out-of-sequence handshake, and wedges earlier
  → still informative.
- Wide-poll is read-only MMIO (15 dwords per dwell). Test.239
  already proved single-dword tail-TCM reads don't shift the wedge.

### Hardware state (current, 07:4x BST boot 0 post-SMC-reset)

- `sudo lspci -vvv -s 03:00.0`: Control `Mem- BusMaster-` (driver
  not loaded yet — normal pre-insmod state); Status MAbort-, fast.
  CommClk- (normal for this Apple board pre-driver, NOT the dirty
  pattern; CLAUDE.md dirty-state marker is `MAbort+ AND CommClk-`
  together). LnkSta Speed 2.5GT/s Width x1.
- No modules loaded.
- Boot 0 started 2026-04-23 07:41:38 BST.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~07:55 BST via `make -C
/lib/modules/$(uname -r)/build M=...brcmfmac modules`. `strings`
and `modinfo` confirm both new params + new test.240 breadcrumbs
(ring + readback + wide-poll lines for all 23 dwell tags). Only
pre-existing unused-variable warnings — no regressions.

### Expected artifacts

- `phase5/logs/test.240.run.txt` — PRE harness + insmod output
- `phase5/logs/test.240.journalctl.full.txt` — full boot -1 journal
- `phase5/logs/test.240.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: REBUILT CLEAN above.
2. PCIe state: clean per `sudo lspci` above.
3. Hypothesis: stated above.
4. Plan: in this block; commit + push + sync before insmod.
5. Filesystem sync on commit.

---
