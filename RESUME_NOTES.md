# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 08:5x, after test.241 — write-verify at MAILBOXMASK pre-FORCEHT FAILED; read path works, sentinel writes did not latch; test confounded with stage, not conclusive about (c))

**Latest outcome (test.241):** With `force_seed=1`,
`ultra_dwells=1`, `poll_sharedram=1`, `wide_poll=1`,
`writeverify=1`, the probe logged the MAILBOXMASK round-trip right
after `pci_set_master` (post-BM-on, pre-FORCEHT, pre-set_active).
Result:

```
test.241: write-verify target MAILBOXMASK offset=0x4c (BAR0)
test.241: MAILBOXMASK baseline=0x00000318 (expect 0x00000000)
test.241: after write=0xDEADBEEF readback=0x00000318 (expect 0xDEADBEEF)
test.241: after write=0x00000000 readback=0x00000318 (expect 0x00000000)
test.241: RESULT FAIL (sentinel-match=0 baseline-zero=0 clear-zero=0)
```

The probe then continued through FORCEHT, set_active (returned
TRUE at 08:30:09 BST), and landed **the same 22 dwells as
test.239/240** (t+100ms..t+90000ms). All 22 sharedram_ptr polls
held `0xffc70038`; all 22 wide-TCM[-64..-8] samples held the same
NVRAM text. Wedge bracket unchanged [t+90s, t+120s]. Host wedged;
SMC reset; current boot 0 started 08:33:44 BST, PCIe clean
(`Mem+ BusMaster+`, MAbort-, CommClk+).

**What test.241 proves and does not prove:**

- **Proves:** at our probe stage immediately after `pci_set_master`
  and before FORCEHT/set_active, writing 0xDEADBEEF (and later 0)
  to `devinfo->reginfo->mailboxmask` (BAR0+0x4c) does NOT change
  the readback value. The readback (0x00000318) is deterministic
  and non-trivial — reads reach a real register, writes don't
  latch there at this stage.
- **Does not prove** that BAR0 writes are broken generally, because:
  - **Stage mismatch with test.240's DB1 write.** Test.240 rang DB1
    at **t+2000ms post-set_active**, i.e. AFTER FORCEHT clocks
    forced and CR4 rstvec set. Test.241 wrote MAILBOXMASK **before**
    any of that. Upstream's own MAILBOXMASK writes
    (`brcmf_pcie_intr_enable`, pcie.c:1339) happen post-shared-init,
    much later than our probe point — so MAILBOXMASK may be in a
    clock/reset domain that's only writable post-set_active.
  - **Our PRE-TEST.241 assumption was wrong.** The plan said
    "MAILBOXMASK defaults to 0 and accepts arbitrary writes." The
    baseline is 0x318 (bits 3,4,8,9), not 0. Unexplained — not
    from any of our current code paths; possible hardware power-
    on default or residual from an earlier boot, but we haven't
    identified the origin.
  - **Dead-code note.** pcie.c:3524+ contains a "test.96" block
    that is supposed to write MAILBOXMASK=0x00FF0300 pre-ARM-release
    and log a readback. That block is inside `brcmf_pcie_download_fw_nvram`
    but downstream of an early-return / different path — zero
    test.96 MBMASK lines appear in this or any recent run's
    journal, so we have no prior evidence either way for whether
    BAR0 writes to MAILBOXMASK ever land.

**Disposition of the three test.240 readings:**

1. **(a) doorbell self-clears / fw saw it and ignored** — still
   plausible.
2. **(b) offset not RAM-backed pre-shared-init** — still plausible.
3. **(c) our BAR0 write did not reach the chip** — *not* cleanly
   confirmed by test.241 because of stage mismatch. Strength of
   (c) is NOT settled; test.241's FAIL is consistent with "MAILBOXMASK
   is gated against writes at our pre-FORCEHT stage" which says
   nothing about H2D_MAILBOX_1 writes at post-set_active stage.

**Next step (test.242 — direct discriminator):** repeat write-verify
at the **same stage DB1 was rung in test.240**, post-set_active,
during the ultra-dwell ladder (e.g. at t+100ms and again at
t+2000ms). Same register (MAILBOXMASK) to keep one axis fixed. If
the writes latch post-set_active, stage-gating is confirmed and
the DB1 null in test.240 is best explained by (a)/(b). If the
writes still fail post-set_active, (c) is a real problem in our
BAR0-write path and we must investigate core-select / aperture /
window state before any more doorbell attempts. Full plan in
PRE-TEST.242 (next).

**Hardware state (current, 08:5x BST boot 0):** `lspci -s 03:00.0`
shows `Mem+ BusMaster+`, MAbort-, CommClk+, DEVSEL=fast. No brcm
modules loaded. SMC reset performed between test.241 wedge and
current boot.

---

## Prior outcome (test.240 — DB1 ring at t+2000ms had zero observable effect; readback=0x00000000; BAR0-write-path itself unverified)

Test.240 ran with `force_seed=1 ultra_dwells=1 poll_sharedram=1
ring_h2d_db1=1 wide_poll=1`. Probe was clean through fw download,
NVRAM, seed, FORCEHT, `pci_set_master`, `brcmf_chip_set_active`
(returned TRUE at 08:02:46 BST). At the t+2000ms dwell, the
driver wrote `1` to `devinfo->reginfo->h2d_mailbox_1` (BAR0+0x144)
via `brcmf_pcie_write_reg32`; readback immediately after was
`0x00000000`. The ladder then landed 22 of 23 dwells
(t+100ms..t+90000ms) matching test.238/239 exactly; sharedram_ptr
and wide-TCM[-64..-8] unchanged throughout. Wedge same bracket
[t+90s, t+120s]. See **POST-TEST.240** block below for full
evidence.

---

**Prior outcome (test.234):** Test wedged. Same tail-truncation
pattern as test.231/232. Last journald line at 23:12:50 BST was
`BCM4360 test.158: BusMaster cleared after chip_attach` — that's
inside `brcmf_pcie_attach` BEFORE `brcmf_pcie_download_fw_nvram`
even starts. **Zero test.234 breadcrumbs landed in journald** (no
PRE-ZERO scan, no zeroing log, no verify, no set_active call/return,
no dwells). The retained test.233 PRE-READ continuity log also
didn't land. So we cannot tell from this run alone whether:
- the zero loop ran or completed
- set_active was called
- the wedge point shifted relative to test.231/232

This is the **expected** journald blackout behavior (tail loss
~15-20s) and matches every prior set_active-enabled run. Host had
to be SMC-reset + rebooted (~28 min downtime). PCIe state on this
boot (boot 0, started 23:41:20 BST) is clean — Mem+ BusMaster+,
MAbort-, CommClk+. No pstore (watchdog frozen by bus stall, as before).

**Conclusion forced by this run:** test.234 cannot be interpreted
on its own. We need a logging transport that survives the wedge
window. Per test.233, TCM survives within-boot SBR+rmmod+insmod
(Run 2) but is wiped by SMC reset (Run 3). And we *always* need
SMC reset to recover from the wedge. So the next test must
**decompose** the experiment into observable pieces — at minimum,
a test.235 that runs the zero+verify path **without** set_active
(test.230 baseline) so we can confirm the zero loop works at all,
then a separate run that adds set_active back. Detailed plan in
PRE-TEST.235 (next).

---

**Prior outcome (test.233):** TCM persistence probe answered the
advisor-blocking question. 3 runs on test.230 baseline (set_active
SKIPPED, no wedge). Wrote 0xDEADBEEF/0xCAFEBABE magic to
TCM[0x90000/4] in each run, pre-read the same offsets at probe
entry:

| Run | Context | Pre-read | Interpretation |
|---|---|---|---|
| 1 | fresh post-SMC-reset boot | 0x842709e1 / 0x90dd4512 | **non-zero** residue — fingerprint-like |
| 2 | same boot, after rmmod | 0xDEADBEEF / 0xCAFEBABE | **MATCH** — TCM survives SBR + rmmod/insmod within boot |
| 3 | post-SMC-reset + reboot | 0x842709e1 / 0xb0dd4512 | magic GONE; near-identical to Run 1 baseline |

**Binary conclusion:** SMC reset + reboot wipes our magic.
**TCM ring-buffer logger is NOT viable for cross-SMC-reset data
retention** — and every wedge in this investigation has required an
SMC reset to recover. So TCM logger can't carry wedge-timing data
through the recovery path we actually use.

**Side observations worth keeping:**
- Run 2 confirmed TCM persists across rmmod/insmod + probe-start
  SBR. If a wedge ever leaves host recoverable without SMC reset,
  the logger *would* help — but that hasn't happened in any test.
- Run 1 and Run 3 pre-reads are near-identical (one word byte-
  identical, one word off by one bit). These are NOT zeros or
  all-0xFF — they look like a deterministic SRAM/fingerprint
  pattern or residue of an early init routine that runs fresh on
  each SMC-reset boot. Offset 0x90000 is past fw image (0..0x6bf78)
  and before NVRAM (0x9ff1c), so our code never writes there in
  normal flow. Could be a BCM4360 SRAM power-on signature.

**Pivot: shared-memory struct forward step.** With TCM logger ruled
out as the timing transport, the path advisor already identified
as the natural next step becomes primary: study upstream brcmfmac's
`brcmf_pcie_init_share` + PCIE2 ring infrastructure, then build a
minimal shared-memory struct in TCM BEFORE `brcmf_chip_set_active`
so that when fw activates, it has valid DMA targets to dereference.
This is both a discriminator (if wedge stops or shifts, we've found
the missing piece) and a forward step regardless of logging.

**Prior fact (test.232):** BM=OFF did NOT prevent the wedge, so
pure DMA-completion-waiting theory is falsified. Wedge may still
be DMA-rooted via fw's reaction to UR responses (AXI fault, retry
storms, pcie2 bring-down internally), but it's not plain
completion-starvation.

**Prior fact (test.230):** `brcmf_chip_set_active` is the **SOLE
trigger** for the bus-wide wedge. With that call skipped, the host
survived the entire probe path cleanly — both breadcrumbs landed,
driver returned -ENODEV, rmmod worked, host alive ≥30 s after, BAR0
still fast-UR. First-ever clean full run.

**Prior fact (test.229):** Post-set_active probe MMIO is innocent —
probes `#if 0`'d, host still wedged. Narrowed the trigger to
"set_active itself"; test.230 confirmed.

**Hardware invariants:**
- Chip: BCM4360, chiprev=3, ccrev=43, pmurev=17
- Cores: pcie2 rev=1, ARM CR4 @ 0x18002000
- Firmware: 442,233 bytes; rambase=0x0, ramsize=0xA0000 (640 KB TCM)
- BAR0=0xb0600000, BAR2=0xb0400000 (TCM window)
- Firmware download: full 442 KB writes successfully; TCM verify 16/16 MATCH
- set_active: reaches CR4, returns true; CPUHALT clears; fw starts executing

**Ruled-out hypotheses (cumulative):**

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/7/0xe/0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |
| Wedge at test.158 ARM CR4 probe line | 226, 227 | ruled out — tail-truncation illusion; journal kept going after that line once NMI watchdog enabled |
| Chunked-write regression (wedge at chunk 27) | 228 | ruled out — was also tail-truncation; full 107 chunks in journal once we survive long enough |
| Wedge caused by probe_armcr4_state MMIO 0x408 (H1) | 229 | ruled out — probes disabled, wedge still occurred |
| Wedge caused by any tier-1/2 fine-grain probe | 229 | ruled out — gated `#if 0`, wedge still occurred |
| Wedge caused by 3000 ms dwell polling | 229 | ruled out — replaced with msleep(1000), still wedged |
| Wedge caused by pre-set_active path (FORCEHT / pci_set_master / fw write) | 230 | ruled out — skipped set_active, host survived cleanly end-to-end |
| Wedge caused by anything OTHER than `brcmf_chip_set_active` | 230 | ruled out — that call is the single-point trigger |
| Sub-second wedge window measurable via journald tail | 231 | ruled out — tail-truncation budget (~15–20 s) >> wedge window |
| Wedge is pure DMA-completion-starvation (fw stalls waiting for response to TLP with bad host address) | 232 | ruled out — BM=OFF forces UR responses instead of completion-waiting, host still wedged |
| TCM ring-buffer logger viable across wedge recovery | 233 | ruled out — TCM magic survives within-boot SBR+insmod (Run 2) but wiped by SMC reset + reboot (Run 3) — every wedge-recovery in this investigation used SMC reset |
| Wedge caused by fingerprint values in [0x9FE00..0x9FF1C) (cheap tier) | 234, 235 | ruled out — zeroing the region did not prevent test.234's wedge |
| Fw-wedge independent of Apple random_seed footer presence | 236 | ruled out — writing `magic=0xfeedc0de` + 256-byte buffer at [0x9FE14..0x9FF1C) shifts the wedge noticeably later: fw reaches ≥t+700ms post-set_active, vs. test.234's pre-fw-download cutoff |
| Wedge is instantaneous at/near set_active return (sub-second) | 237 | ruled out — with seed present and an extended msleep ladder, fw runs ≥25 s post-set_active; dwells at t+100..t+25000ms all landed live, driver thread schedulable throughout. |
| Wedge is a fw-timeout at ~t+30 s (Model A from PRE-TEST.238) | 238 | ruled out — fine-grain 1 s ladder through [t+25..t+30 s] all landed; dwells at t+35, 45, 60, 90 s all landed. Wedge is not near t+30 s. |
| Wedge happens within ~t+40-45 s of set_active (Model B from PRE-TEST.238) | 238 | ruled out — `t+60 s dwell` and `t+90 s dwell` both landed live. True wedge window is [t+90 s, t+120 s]. |
| Fw completes shared-struct init before wedge (i.e. writes `sharedram_addr` to TCM[ramsize-4]) | 239 | ruled out — 22 consecutive polls at t+100ms..t+90s all returned the pre-set_active NVRAM marker `0xffc70038`. Fw is executing for ≥90s but has not reached / not exited the step that normally overwrites this slot. |
| Fw writes ANY of the last 60 bytes of TCM (not just ramsize-4) during the ≥90 s pre-wedge window | 240 | ruled out — a 15-dword wide-poll at ramsize-64..ramsize-8, sampled at 22 ladder points, returned the unchanged NVRAM tail text every time. Fw's post-init work, if any, does not touch the tail region. |
| Ringing H2D_MAILBOX_1 (upstream "HostRDY" offset, BAR0+0x144) at t+2000ms releases fw's pre-shared-alloc stall | 240 | **inconclusive** — readback after write=1 was 0x00000000 AND no downstream observable change (sharedram_ptr, tail-TCM, wedge timing all identical to test.239). Three candidate readings: (a) doorbell self-clears / fw saw it and chose not to act; (b) offset not RAM-backed pre-shared-init; (c) our BAR0 write path landed on the wrong register. (c) blocks cleanly concluding anything about DB1 as a signal. |
| BAR0 write path via `brcmf_pcie_write_reg32` reaches chip at our **pre-FORCEHT** probe stage (using MAILBOXMASK round-trip) | 241 | **inconclusive** — baseline read 0x318 (not the expected 0); both writes (0xDEADBEEF and 0) did NOT change readback. Read path is live. Stage-mismatch with test.240's DB1 (post-set_active) means FAIL here may be register-stage-gating, not a general write-path defect. Test.242 repeats at post-set_active dwell points to resolve. |

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — fw blocked on host handshake (still standing,
but not freshly strengthened by test.240):**
Fw never advances to shared-struct allocation within ≥90 s
post-set_active (upstream timeout is 5 s). Test.240 attempted the
upstream HostRDY doorbell (DB1) as the cheapest handshake probe;
result was inconclusive for the reasons in *Three readings* above.

**Next test direction (test.241):**
Per advisor — pivot to "write-verify first, then doorbell". Before
another boot-burn on DB0, instrument one or more known-RAM-backed
BAR0 MMIO locations with a write-then-immediate-readback pattern
inside the probe, after `pci_set_master` and before `set_active`,
to prove the driver's BAR0 write path lands correctly with the
current core-select window. If that passes, ring DB0 at t+2000ms
as the original decision tree had. If that fails, the whole
"doorbell" branch is suspect and we pivot to (a) investigate core-
select window handling, and/or (b) pre-allocate a shared-memory
struct in TCM `brcmf_pcie_init_share`-style and write its address
to TCM[ramsize-4] before set_active (the advisor's prior "jump"
suggestion). Details in PRE-TEST.241.

**Logging transport status (updated after test.233):**
- journald: drops ~15–20 s of tail when host loses userspace (confirmed tests 226/227/231/232).
- pstore: doesn't fire — bus-wide stall freezes watchdog CPU (tests 227/228/229).
- netconsole: user declined second-host setup.
- **TCM ring buffer: ruled out** — TCM magic wiped by SMC reset +
  reboot (test.233 Run 3). Survives within-boot rmmod/insmod (Run 2),
  but every wedge in this investigation has required an SMC reset.
- `earlyprintk=serial`: `/dev/ttyS0..3` exist but MacBook has no
  exposed port — likely bit-bucket without USB-serial adapter.

Logging for test.234 falls back to journald tail-truncation as
before. Resolution ≥15-20 s is fine because the goal is shape-
comparison (does the wedge still happen? at the same place?),
not sub-second timing.

---


## POST-TEST.241 (2026-04-23 08:29 BST, boot -1 — write-verify at MAILBOXMASK pre-FORCEHT FAILED; read path live, writes did not latch; result confounded with stage)

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1
bcm4360_test241_writeverify=1`. `bcm4360_test240_ring_h2d_db1` was
intentionally OFF for this run (goal was to measure bare
write-verify, not re-mix a doorbell). Probe reached
`brcmf_chip_set_active` (returned TRUE at 08:30:09 BST). Write-verify
lines fired between the post-BM-on MMIO guard and the FORCEHT block:

```
test.241: write-verify target MAILBOXMASK offset=0x4c (BAR0)
test.241: MAILBOXMASK baseline=0x00000318 (expect 0x00000000)
test.241: after write=0xDEADBEEF readback=0x00000318 (expect 0xDEADBEEF)
test.241: after write=0x00000000 readback=0x00000318 (expect 0x00000000)
test.241: RESULT FAIL (sentinel-match=0 baseline-zero=0 clear-zero=0)
```

All three match bits zero. Ladder then ran 22 dwells
(t+100ms..t+90000ms); last line 08:31:41 BST. `t+120000ms` never
landed. Host wedged; SMC reset performed by user; current boot 0
started 08:33:44 BST.

### What the FAIL signals

The **read** path to BAR0+0x4c is live: returns a deterministic
non-trivial value (0x318, not 0 and not 0xffffffff). The **write**
path at this stage does not change that value. Two candidate
interpretations, neither ruled out by this run alone:

1. **Stage-gated register.** MAILBOXMASK sits in a clock or reset
   domain that's dormant until FORCEHT / set_active. Writes are
   silently dropped at this stage but would land later. Consistent
   with upstream brcmfmac: the only production writer is
   `brcmf_pcie_intr_enable` (pcie.c:1339), which runs post-fw-up
   / post-shared-init — far later than our probe insertion point.
2. **Generally broken BAR0 write path.** Our
   `brcmf_pcie_write_reg32(devinfo, offset, val)` =
   `iowrite32(val, devinfo->regs + offset)` is somehow not landing
   on-chip (wrong window, posted-write blocked, aperture issue).
   If true, the DB1 write in test.240 also didn't land, making the
   readback=0 there trivial and test.240 re-opens.

These are different claims with different implications — test.241
does not pick between them because it tested at a stage where
MAILBOXMASK writes may legitimately be non-functional. The
discriminator is to re-run write-verify **post-set_active** at
the same ladder points where test.240's DB1 fired. That is
PRE-TEST.242.

### Wedge / ladder behaviour

Identical to test.239 and test.240:

- Dwell breadcrumbs: 22 of 23 landed (t+100ms .. t+90000ms).
- sharedram_ptr: `0xffc70038` at every poll (no fw write).
- Wide-TCM[ramsize-64..ramsize-8]: NVRAM text unchanged at every
  poll (no fw write).
- Journal ends 08:31:41 BST; wedge in same [t+90s, t+120s] bracket.
- No Oops / Call Trace / softlockup / hardlockup in boot -1.

Adding the write-verify sequence did NOT shift the wedge timing —
three extra BAR0 MMIO ops pre-FORCEHT are invisible to the wedge
trigger (consistent with all prior evidence that the wedge is
set_active-gated, not pre-set_active path).

### Unexplained signal

The baseline value `0x00000318` = bits 3, 4, 8, 9. `grep 0x318` in
pcie.c finds no current writer of this specific value. Possible
origins: hardware power-on reset state of MAILBOXMASK for PCIE2
rev=1 on BCM4360; residual state left by a prior boot's driver
before the SMC reset (though SMC reset is supposed to wipe this);
or bits set by early chip init we don't instrument. Noted but
not blocking — what matters for test.242 is that the READ is
deterministic and stable, so a subsequent round-trip will produce
a clean pass/fail regardless of the baseline value.

### PRE-TEST.241 assumption that was wrong

The PRE block claimed "MAILBOXMASK defaults to 0 and accepts
arbitrary writes." Baseline ≠ 0 (it's 0x318), and writes don't
latch. Both halves of the assumption failed. The choice of
MAILBOXMASK as a discriminator register was also weak in
retrospect: upstream only writes it post-shared-init, so we had
no precedent showing writes to this register are even meant to
land at our probe stage.

### Dead-code clarification

pcie.c lines 3524+ ("test.96") write MAILBOXMASK=0x00FF0300 and
log a readback. Same function as our test.241 insertion
(`brcmf_pcie_download_fw_nvram`), but downstream of a branch/return
that is taken in our current flow — zero `test.96 MBMASK`
lines appear in this run's journal or any recent run's journal.
So no historical BAR0-write verification to lean on.

### Artifacts

- `phase5/logs/test.241.run.txt` — PRE harness + insmod output
  (truncated at "sleeping 240s" because host wedged during sleep).
- `phase5/logs/test.241.journalctl.full.txt` (1488 lines) — full
  boot -1 journal.
- `phase5/logs/test.241.journalctl.txt` (417 lines) — filtered
  BCM4360 / brcmfmac / watchdog subset.

---


## PRE-TEST.242 (2026-04-23 08:5x BST, boot 0 post-SMC-reset from test.241) — move write-verify POST set_active, ladder-timed, to directly discriminate (c) from stage-gating of MAILBOXMASK

### Hypothesis

Test.241 showed MAILBOXMASK writes don't latch at the pre-FORCEHT
stage, but that doesn't tell us whether BAR0 writes work
**post-set_active** (the stage where test.240 rang DB1). The two
candidate interpretations of test.241's FAIL differ *only* in
how they respond to a stage change:

| Claim | Expected post-set_active write-verify result |
|---|---|
| (1) MAILBOXMASK is stage-gated; BAR0 writes generally fine | PASS — sentinel round-trip works post-set_active |
| (2) BAR0 write path is broken for this register / generally | FAIL — sentinel round-trip still doesn't latch |

Test.242 resolves this by relocating the write-verify from the
pre-FORCEHT insertion point to **inside the dwell ladder**, at
early dwell points post-set_active. If PASS emerges, test.240's
DB1 readback=0 collapses to reading (a) or (b) and we can pivot
to the next doorbell-or-shared-struct branch with confidence. If
FAIL persists, we stop chasing doorbells and investigate the
BAR0-write path (core-select window, aperture, iowrite32 ordering,
etc.) before any further host→fw signalling.

### Plan

1. **New module param** `bcm4360_test242_writeverify_postactive`
   (default 0). When set, inject write-verify round-trips at
   TWO dwell points inside the ultra ladder:
   - **t+100ms** (first dwell after set_active returns)
   - **t+2000ms** (same point where test.240 rang DB1)
2. **Register choice.** Keep MAILBOXMASK (`devinfo->reginfo->mailboxmask`
   = BAR0+0x4c on our pcie2 non-64 variant) to keep ONE axis
   changed (stage) vs test.241. Same baseline / sentinel /
   clear sequence:
   ```c
   baseline    = read_reg32(MBM);
   write_reg32(MBM, 0xDEADBEEF);
   after_sent  = read_reg32(MBM);
   write_reg32(MBM, 0);
   after_clear = read_reg32(MBM);
   pr_emerg("... t+Xms RESULT %s (sent-match=%d clear-zero=%d)\n",
            ...);
   ```
3. **No DB1 ring in test.242.** Keep `ring_h2d_db1=0`. The goal
   is to isolate the write-path variable only.
4. **Preserve all other ladder instrumentation** — force_seed,
   ultra_dwells, poll_sharedram, wide_poll — so dwell / sharedram /
   tail-TCM comparisons to test.239/240/241 remain valid. Skipping
   test.241's pre-FORCEHT writeverify (=0 for this run).
5. If t+100ms PASSes but t+2000ms FAILs (or vice versa), that's a
   strong signal that post-set_active chip state evolves fast
   enough to close the write path mid-ladder — flag for test.243
   but still a clean discriminator for DB1-at-t+2000ms.

### Expected outcomes

| t+100ms | t+2000ms | Interpretation | Test.243 direction |
|---|---|---|---|
| PASS | PASS | BAR0 write path works post-set_active. test.241 FAIL was stage-gating of MAILBOXMASK. test.240's DB1 null = (a) or (b). | ring DB0 at t+2000ms; if also null, pivot to shared-struct pre-alloc in TCM. |
| PASS | FAIL | Write path starts working post-set_active but closes again later. Would explain why DB1 at t+2000ms was invisible. | Test.243 maps when write path is open — spread write-verify across dwell ladder (10 points). |
| FAIL | FAIL | BAR0 write path is broken post-set_active too. test.240 DB1 never reached chip; (c) confirmed. | Stop all doorbell attempts. Investigate core-select window / aperture; compare to upstream's pre-set_active MBMASK writer block. |
| FAIL | PASS | Write path opens later than t+100ms — unusual, but discrimiator for DB1-at-t+2000ms is still clean (writes work there). | Same as PASS/PASS branch for test.243. |

### Code change

1. Add module param `bcm4360_test242_writeverify_postactive` near
   existing test.241 param.
2. At the t+100ms dwell breadcrumb (inside the ultra ladder),
   gated on this param, emit the 5-line round-trip + RESULT line.
3. At the t+2000ms dwell breadcrumb, same treatment.
4. Keep the test.241 pre-FORCEHT block code in place but run
   with `bcm4360_test241_writeverify=0` so it doesn't fire —
   we keep the option to run it again later for cross-check.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test242_writeverify_postactive=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Safety

- Post-set_active MAILBOXMASK writes at t+100ms and t+2000ms are
  during the exact window upstream's `brcmf_pcie_intr_disable`
  (pcie.c:1333) writes 0 to the same register in production
  (called during cleanup). So write + immediate restore to 0 is
  a safe no-op IF writes land. If writes don't land, the register
  state is unchanged — same outcome as test.241 — still safe.
- Two extra 5-op round-trips during the dwell ladder add <100 µs
  total MMIO time; indistinguishable from the existing per-dwell
  read load. Does not affect wedge timing (test.239/240/241 all
  showed the same 22-of-23 pattern despite incremental MMIO
  additions).

### Hardware state (current, 08:5x BST boot 0 post-SMC-reset)

- `sudo lspci -vvv -s 03:00.0`: Control `Mem+ BusMaster+`, Status
  MAbort-, DEVSEL=fast, LnkCtl CommClk+, LnkSta 2.5GT/s x1.
- No brcm modules loaded.
- Boot 0 started 2026-04-23 08:33:44 BST.

### Build status — PENDING

Need to edit pcie.c + `make -C phase5/work` + strings/modinfo
verify before insmod.

### Expected artifacts

- `phase5/logs/test.242.run.txt`
- `phase5/logs/test.242.journalctl.full.txt`
- `phase5/logs/test.242.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + strings verify before insmod.
2. PCIe state: clean per above.
3. Hypothesis: stated above.
4. Plan: in this block; commit + push + sync before any code change.
5. Filesystem sync on commit.

---


## PRE-TEST.241 (2026-04-23 08:2x BST, boot 0 post-SMC-reset from test.240) — write-verify BAR0 path BEFORE ringing another doorbell; de-confound the "DB1 null" reading

### Hypothesis

Test.240's DB1 ring produced readback=0 and zero downstream effect.
Advisor flagged a three-way ambiguity: (a) doorbell self-clears / fw
saw it and ignored pre-shared-init; (b) offset not RAM-backed pre-
shared-init; (c) our `brcmf_pcie_write_reg32` call at BAR0+0x144
didn't reach the intended register (wrong core-select window, or
wrong aperture). Reading (c) would make a test.241-tries-DB0 run
null-and-uninterpretable for the same reason. We must de-confound
*before* another doorbell attempt.

### Write-verify plan

Inside `brcmf_pcie_attach` / equivalent, immediately after
`pci_set_master` and well BEFORE `brcmf_chip_set_active`, do the
following gated on new module param `bcm4360_test241_writeverify`:

1. **Probe a known-RAM-backed BAR0 scratch** — upstream brcmfmac
   accesses several BAR0-resident registers (e.g. PCIE2 scratch
   slots, intmask register) that are backed by on-chip RAM /
   flip-flops and ARE readable pre-fw-run. Select one from upstream
   where we have confidence about readback semantics (decide exact
   register during code write). Log a read-back BEFORE the test
   write (baseline).
2. **Write a sentinel (0xDEADBEEF)** to that scratch register via
   `brcmf_pcie_write_reg32(devinfo, OFFSET, 0xDEADBEEF)`. Log the
   write.
3. **Immediately read-back** via `brcmf_pcie_read_reg32`. Log the
   result. Expected: `0xDEADBEEF` (confirms BAR0 write path lands).
4. **Write 0** and read-back to confirm the write path is not
   stuck (idempotency check).
5. Only after that, preserve all the test.240 flags (force_seed,
   ultra_dwells, poll_sharedram, wide_poll) but DISABLE
   `ring_h2d_db1` for this run. The purpose of test.241 is to
   establish the write-path works — not yet to re-try a doorbell.

### Expected outcomes

| Write-verify result | Interpretation | Next step |
|---|---|---|
| Step 3 reads `0xDEADBEEF` | BAR0 write path is live for that scratch register. Strengthens (a)/(b) over (c) for test.240. | test.242: ring DB0 at t+2000ms with otherwise identical run. If DB0 also null-and-quiet → "doorbell handshake pre-shared-init" is not the key; pivot to shared-struct pre-alloc. |
| Step 3 reads something other than `0xDEADBEEF` (0, scratch baseline, scrambled) | BAR0-write path is confounded at some offsets. DB1 null (c) supported. Must diagnose core-select window / aperture / indirection. | test.242: add core-select window read+log around write points; also try different scratch offsets to map what's writable. |
| Step 3 read itself returns `0xffffffff` (bus error) | Chip in a bad PCIe state even pre-set_active — would explain a lot of prior noise. | SMC reset + reboot, retest; if reproducible, PCIe link-up / config inspection. |

### Discriminator budget for this boot

- Entire write-verify sequence is ≤5 MMIO ops and a few log lines;
  adds <1 ms to probe execution.
- Keeping ultra-dwells ON costs ≤120 s run-time (wedge expected in
  same [t+90s, t+120s] window), which matters only for prolonging
  the wedge-window wait; write-verify result is logged at probe
  entry and lands in journald long before any wedge.

### Code change (IMPLEMENTED)

1. Module param `bcm4360_test241_writeverify` (default 0) added in
   pcie.c near the test.240 params.
2. Insertion point: inside the BusMaster dance block, immediately
   after the "post-BM-on MMIO guard mailboxint" read at the
   `pr_emerg("BCM4360 test.188: post-BM-on ...")` line, and BEFORE
   the "past BusMaster dance — entering FORCEHT block" line. This
   is after `pci_set_master` succeeds and well before
   `brcmf_chip_set_active`, so write-verify lines hit journald at
   fresh probe entry (pre-wedge) and will land even if the wedge
   bracket is unchanged.
3. Target register: `devinfo->reginfo->mailboxmask` which on BCM4360
   resolves to `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = 0x4C` (non-64
   variant). Upstream already reads/writes this at brcmf_pcie_*
   attach+setup paths (lines 3514/3536 in our tree), so it's a
   proven R/W, RAM-backed mask register that defaults to 0 and
   accepts arbitrary 32-bit writes.
4. Round-trip sequence:
   ```c
   const u32 MBM = devinfo->reginfo->mailboxmask;
   baseline    = read_reg32(MBM);                        /* expect 0 */
   write_reg32(MBM, 0xDEADBEEF);
   after_sent  = read_reg32(MBM);                        /* expect 0xDEADBEEF */
   write_reg32(MBM, 0);
   after_clear = read_reg32(MBM);                        /* expect 0 */
   ```
   Each step emitted via `pr_emerg()`; final line emits a PASS/FAIL
   RESULT with three individual match bits, so the result is
   unambiguous regardless of journald formatting.
5. `ring_h2d_db1` is NOT set at insmod for this run — the goal is
   to measure the bare write-verify, not re-mix DB1 disturbance
   into the result.
6. All other test.236/238/239 paths preserved unchanged.

### Run sequence

```bash
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test241_writeverify=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Write-verify lines land in journald at probe entry (well before any
set_active-triggered wedge), so the RESULT will be retrievable
even if the host wedges again. The ultra-dwell ladder continues
to run after write-verify so we also capture whether the 22-of-23
dwell pattern is steady (same wedge bracket) or has shifted.

### Safety notes

- Write-verify happens BEFORE set_active, so it's inside the
  already-safe pre-set_active path (test.230 confirmed full
  clean run without set_active). Any sentinel we leave on a
  scratch register will be overwritten by fw once fw runs (and
  set_active still runs unchanged after write-verify).
- If we pick a scratch register that is ACTUALLY a control
  register, we could disrupt fw startup. Mitigation: pick a slot
  upstream's brcmfmac treats as benign scratch, or restrict to an
  intmask register where a round-trip of 0xdeadbeef→0 is a no-op
  once we clear it.

### Open items — resolved during code implementation

- **Exact BAR0 offset**: MAILBOXMASK (0x4C on BCM4360, accessed via
  `devinfo->reginfo->mailboxmask`). Picked because upstream
  actively uses this register (proven R/W) and it defaults to 0
  at our pre-init stage, so sentinel round-trip + restore to 0 is
  a true no-op on chip state.
- **Core-select window concern**: `brcmf_pcie_write_reg32` is
  `iowrite32(value, devinfo->regs + offset)` — a plain linear BAR0
  write with NO core-select indirection. So interpretation (c)
  sub-case "wrong core window" does not apply at the MMIO layer.
  (c) can still fire if the specific offset returns 0 by design
  or isn't RAM-backed — which is exactly what MAILBOXMASK
  round-trip rules out (or in, cleanly).

### Hardware state (current, 08:15 BST boot 0 post-SMC-reset)

- `lspci -s 03:00.0`: `Mem+ BusMaster+`, MAbort-, DEVSEL=fast.
- No brcm modules loaded.
- Boot 0 started 2026-04-23 08:09:57 BST.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~08:45 BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
Confirmed in built module:
- `strings` shows all 5 test.241 format lines + param name.
- `modinfo` reports `parm: bcm4360_test241_writeverify: ...`.
Only pre-existing unused-variable and `brcmf_pcie_write_ram32`
warnings — no new regressions.

### Expected artifacts

- `phase5/logs/test.241.run.txt`
- `phase5/logs/test.241.journalctl.full.txt`
- `phase5/logs/test.241.journalctl.txt`

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING.
2. PCIe state: clean per above.
3. Hypothesis: stated above.
4. Plan: in this block; commit+push+sync before any code change.
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


## Older test history (test.239 and earlier)

Full detail for POST-TEST.239 and PRE-TEST.239 →
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md)

---

<!-- REMOVED: POST-TEST.239 and PRE-TEST.239 — now in HISTORY
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
-->

---


## Older test history (earlier tests)

Full detail for tests prior to test.239 →
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
