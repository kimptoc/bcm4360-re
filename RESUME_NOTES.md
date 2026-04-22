# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23, after test.234 wedge → deciding next direction)

**Latest outcome (test.234):** Test wedged. Same tail-truncation
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

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — DMA target not set up:**
Upstream brcmfmac sets up extensive shared-memory / ring-descriptor
infrastructure (`brcmf_pcie_init_share`, ring alloc, mailbox setup)
BEFORE set_active. Our BCM4360 path bypasses all of that. Newly-alive
firmware likely tries to DMA-read ring descriptor addresses from the
shared-memory struct in TCM; those fields are all-zero or garbage;
firmware dereferences a NULL/garbage host address; PCIe TLPs issued
to that host address never get a completion; bus stalls.

**Test.234 plan (primary direction after test.233):**
Implement a **minimal shared-memory struct in TCM BEFORE set_active**,
per upstream brcmfmac `brcmf_pcie_init_share` pattern. Two bonuses:
- Discriminator: if the wedge stops, we've found the piece fw was
  reaching for. If timing/signature shifts, we have a new observable.
- Forward step: it's part of the eventual correct driver path anyway.

Cost: 1-2 days to read brcmf_pcie_init_share + related ring setup,
decide minimum viable struct, wire the allocations.

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


## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
