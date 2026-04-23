# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 00:55, after test.238 — ultra-extended ladder landed 22/23 breadcrumbs (t+100ms..t+90s); wedge window tightened to [t+90s, t+120s])

**Latest outcome (test.238):** With Apple random_seed present AND
the ultra-extended dwell ladder out to t+120s, **22 of 23 dwell
breadcrumbs landed** covering t+100ms..t+90000ms. Missing only
`t+120000ms dwell` and everything downstream (dwell-done,
BM-clear, release, -ENODEV). Host wedged, SMC reset performed
(user); current boot 0 started 00:54:07 BST, clean `Mem+
BusMaster+ MAbort-`, no modules loaded.

Landed ladder timestamps (boot -1, set_active at 00:50:46):

```
test.238: calling brcmf_chip_set_active resetintr=0xb80ef000 (ultra-extended ladder t+120s)
test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006
test.238: brcmf_chip_set_active returned TRUE
test.238: t+100ms / t+300ms / t+500ms / t+700ms / t+1000ms (batched @ 00:50:46)
test.238: t+1500ms / t+2000ms / t+3000ms / t+5000ms (batched @ 00:50:46)
test.238: t+10000ms (00:50:50) — live flush resumes
test.238: t+15000ms (00:50:55)
test.238: t+20000ms (00:51:00)
test.238: t+25000ms (00:51:05)
test.238: t+26000ms (00:51:06)       ← 1 s fine-grain window opens
test.238: t+27000ms (00:51:07)
test.238: t+28000ms (00:51:08)
test.238: t+29000ms (00:51:09)
test.238: t+30000ms (00:51:10)
test.238: t+35000ms (00:51:15)
test.238: t+45000ms (00:51:25)
test.238: t+60000ms (00:51:41)
test.238: t+90000ms (00:52:11 — last test.238 line of boot -1)
<then only wlp0s20u2 lines through 00:52:24 — journal ends>
```

Expected `t+120000ms dwell` would have logged at 00:52:46; journal
ended 00:52:24 — ~22 s before that line was due.

**Wedge-moment bounds (much tighter now):**
- **Lower bound — from host-CPU evidence:** `wlp0s20u2` kernel
  lines at 00:52:22–00:52:24 BST (t+96–98 s post-set_active)
  prove at least one host CPU was scheduling non-brcmfmac wlan
  work long after our last breadcrumb — i.e., **host was still
  alive at ≥ t+98 s**. Wedge must be at ≥ t+98 s.
- **Upper bound:** Applying the ~15–20 s journald tail-truncation
  budget to the 00:52:24 cut ⇒ wedge at real-time ≤ 00:52:44,
  i.e. ≤ t+118 s.
- **Window:** wedge ∈ **[t+98 s, t+118 s]** (~20 s wide).
- Fine-grain [t+25..t+30] window **all landed** (1 s steps) ⇒
  no fw-timeout near t+30 s. Model A from PRE-TEST.238 is
  **refuted**; Model B (late wedge) holds.
- **Abrupt-wedge signature:** since host CPUs were still
  scheduling wlan work 7+ s after our last dwell breadcrumb,
  the wedge is NOT a slow resource exhaustion — it's a
  bus-level event that kills journald's kmsg flush path fast
  enough that the final 15–20 s of activity never persists.

**Rewrites test.237 interpretation:** test.237's missing
`t+30000ms dwell` breadcrumb was NOT the wedge moment — every
intermediate breadcrumb (t+30 s, t+35 s, t+45 s, t+60 s, t+90 s)
lands cleanly in test.238. Test.237's journal cut at t+25 s
reflected a longer tail-truncation / rmmod-phase cut, not the
actual wedge. The true wedge moment in test.237 was likely
similar to test.238's (≥ t+90 s), with its shorter ladder just
not having breadcrumbs past t+30 s to land.

**What this tells us about the wedge cause:**
- Fw+bus are **demonstrably healthy for ≥90 s** post-set_active
  on every wedged run with seed present.
- Timeout / trigger is at **~100-120 s**, very suspicious for:
  - Fw internal watchdog at a multi-of-N periods (~30 s × 3–4 or
    ~60 s × 2, both hitting that window).
  - One-shot fw init timer that completes at ~100 s and then
    tries to DMA-read or dereference a host-provided structure
    that we haven't set up (pcie_shared / ringinfo / console /
    mailbox / dma_scratch_buf).
  - Fw periodic-heartbeat that expects host doorbell ring-back
    within N intervals; after ~3–4 intervals without response,
    bus-wide trap.

**Implications for next work:**
- Seed extends fw runtime by **≥2 orders of magnitude** relative
  to test.234 baseline (seed-less probe wedged pre-fw-download).
  But it does NOT prevent the late wedge.
- Further dwell-extension is diminishing-returns — we already
  have a tight window. The bottleneck is NOT knowing what fw
  expected during those 90 s.
- **Primary next target (test.239):** implement a minimal
  `pcie_shared` struct in TCM before `brcmf_chip_set_active`,
  following upstream brcmfmac's `brcmf_pcie_init_share` pattern
  (ringinfo pointer, console pointer, H2D/D2H mailbox addrs,
  dma_scratch_buf). If wedge shifts later or disappears, we've
  found the next missing piece.
- Alternate cheap discriminator (test.239a): add another ~5-10 s
  of fine-grain ladder in [t+90..t+120] (5 steps at 5 s each) to
  pin the wedge moment to ±5 s rather than the ±15 s tail-trunc
  window. Cost: one wedge cycle + SMC reset. Useful only if
  advisor thinks tight timing is decisive.

**Hardware state (current, 00:55 BST boot 0):** `lspci -s 03:00.0`
shows Mem+ BusMaster+ MAbort-, DEVSEL=fast. No modules loaded.
SMC reset performed between test.238 wedge and current boot.

---

## Prior outcome (test.236 Run B — random_seed DELAYS the wedge, shifts fw past set_active by ≥700 ms)

**Latest outcome (test.236, two runs):**

**Run A (skip_set_active=1, force_seed=1):** Clean. Seed footer
written at TCM[0x9ff14] magic=0xfeedc0de len=0x100; 256-byte random
buffer at TCM[0x9fe14..0x9ff14]; footer readback MATCH. Confirms the
Apple-style seed mechanism is BCM4360-safe and byte-accurate via
`brcmf_pcie_copy_mem_todev`.

**Run B (skip_set_active=0, force_seed=1):** Wedge — SMC reset
required — but the wedge **shifted demonstrably later**. Boot -1
journal shows Run B reached:

```
test.234: calling brcmf_chip_set_active resetintr=0xb80ef000
test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006
test.234: brcmf_chip_set_active returned TRUE
test.234: t+100ms dwell
test.234: t+300ms dwell
test.234: t+500ms dwell
test.234: t+700ms dwell
<journal cut — host wedged>
```

For comparison, test.234 (no seed) wedged so early that its journal
cut at `test.158: BusMaster cleared after chip_attach` — **before
fw download even started**. Every post-chip_attach breadcrumb was
lost to tail-truncation. Now with the seed written, fw demonstrably
runs ≥700 ms past set_active before wedging.

**Conclusion:** The Apple-style random_seed footer/buffer
([0x9fe14..0x9ff1c), magic `0xfeedc0de`, length `0x100`) was a
missing piece. Direct evidence: fw ran **≥700 ms post-set_active**
under the seed (four dwell breadcrumbs landed); test.234 without
seed had zero post-set_active breadcrumbs flush before the wedge
cut the journal mid-fw-download-sequence.

**Wedge moment — directly observed lower bound, not an upper bound.**
All we can say from journal evidence:
- Run B flushed `t+700ms dwell` — so fw actually executed for at
  least 700 ms after set_active return (the msleep chain required
  the driver thread to schedule for that long).
- test.234 flushed nothing beyond `BusMaster cleared after
  chip_attach` — structurally *before* fw download even started.

The "~15-20 s tail-truncation budget" is a folk figure from earlier
tests, NOT a calibrated constant. Log rate, IO rate, and freeze
dynamics all vary. Inferring an exact wedge moment from it is
weak. The safe read is: "Run B's wedge was definitely ≥700 ms
post-set_active-return; further precision requires test.237."

Test.237 should extend the dwell ladder out to t+30 s and use the
landed-vs-missing pattern to bracket the actual wedge moment.
Softlockup_panic is armed at the default kernel threshold (~20-22 s)
so if the driver thread is ever frozen inside an extended msleep,
we may get a panic backtrace to pstore — a secondary observable
beyond the breadcrumbs themselves.

Most likely next-target: the shared-memory / ringinfo structure.
Upstream brcmfmac's `brcmf_pcie_init_share` + `pcie_shared` struct
sets up ring descriptor addresses, console pointers, msgbuf ring
metadata — any of which fw may try to DMA-read after the seed lands.

**Implications for next work:**
- The cheap-tier "zero the region" hypothesis from test.234 is
  wholly superseded. Test.236 shows the issue wasn't random
  fingerprint values — it was the *absence* of the specific Apple
  random_seed magic (0xfeedc0de + length + buffer) that fw's
  activation path expects.
- Seed alone does not fully unstick fw. Next candidate: the
  pcie_shared / ringinfo / console pointer block that fw typically
  finds at `ramsize - 4`'s tail area in upstream flows. Building
  a minimal shared-memory struct in TCM (or an initialised region
  fw DMA-reads into) is the natural test.237 target.
- The ~15-20 s journald tail-truncation budget is still the main
  observability constraint. Run B's tail shows we can now get up
  to `t+700ms dwell` flushed — four new breadcrumbs that never
  landed in any prior wedged run.

**Hardware state (current, 00:13 BST boot 0):** lspci Mem+
BusMaster+, MAbort-, fast. No modules loaded. SMC reset was
performed between Run B wedge and current boot.

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

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — second missing piece (shared-memory struct):**
Test.236 validated that Apple's random_seed is one piece fw expects.
After seed lands, fw still wedges within ~1 s of set_active. Upstream
brcmfmac builds a full pcie_shared struct (ringinfo, console, H2D/D2H
mailbox addresses, dma_scratch_buf pointer) and writes its TCM
address to a known slot at boot — this is the natural next target
for the discriminator ladder.

**Planned test.237 direction:**
Before committing to the full `brcmf_pcie_init_share` implementation,
run a cheap timing-discriminator: same code path as test.236 Run B
but extend the dwell ladder past t+10s (t=1.5s, 2s, 3s, 5s, 10s,
15s, 20s, 25s, 30s) to bracket the inferred ~15-20 s wedge moment.

Two purposes:
1. Direct measurement of the wedge moment — if t+15s and t+20s land
   but t+25s doesn't, we've pinned the wedge to a ~5 s window and
   can further bisect.
2. Discriminator against "journald-flush-variance" counter-hypothesis
   (unlikely per the breadcrumb-required-to-execute argument but
   worth ruling out): if the wedge is actually still ~1 s post-
   set_active, the extended dwells all simply never execute, and
   the breadcrumbs cut at t+700ms regardless.

Optional: pair with a `force_seed=0` control run at matching dwell
points for the cleanest A/B comparison. Cost: one extra wedge
cycle + SMC reset. Defer if Run B already shows late breadcrumbs.

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


## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
