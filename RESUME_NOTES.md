# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-22, after test.233)

**Latest outcome (test.233):** TCM persistence probe answered the
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

## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
