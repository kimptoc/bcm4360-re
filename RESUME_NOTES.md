# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-22, after test.232)

**Latest outcome (test.232):** BM=OFF did NOT prevent the wedge.
Host wedged mid-probe, required reboot. Boot -1 journal tail-
truncated at `wide-TCM[0x2c000]` pre-release snapshot (21:52:52) —
every breadcrumb beyond that (rest of pre-release snapshots,
INTERNAL_MEM probe, pre-set-active probes, the `test.232: SKIPPING
pci_set_master` marker, FORCEHT, `brcmf_chip_set_active`, dwells)
was swallowed by the tail-truncation budget. No test.232 breadcrumb
landed at all. The binary discriminator still carries though: given
test.230 proved this identical flow (minus set_active) runs cleanly
end-to-end, the only runtime-different actor between the last
landed log and the wedge is `brcmf_chip_set_active`. So the wedge
trigger is still set_active; BM=OFF failed to neutralize it.

**Inference (advisor-refined):** "DMA-completion-waiting" theory is
falsified — with BM=OFF, fw's DMA TLPs get UR responses from the
root complex instead of stalling waiting for a completion, yet host
still wedges. Wedge is NOT pure completion-starvation. It MAY still
be DMA-rooted (fw could react to UR by doing something bus-hostile
— AXI-side faults, retry storms, internal pcie2 bring-down). Phrase
carefully: "not waiting-for-completion-of-missing-target", not "not
DMA-related".

**Blockers on next hardware test (advisor-flagged):**
1. Host rebooted without SMC reset. Current lspci resembles
   post-SMC-reset clean state, but fw may have left CR4 in a partially-
   activated state. User should do SMC reset before next hardware
   test — the "SMC reset NOT done" flag is a request, not a skip.
2. Open question to user: does SMC reset wipe TCM? The TCM ring-buffer
   logger's viability depends on the answer. If SMC reset wipes TCM,
   the logger only helps on runs where reboot-without-SMC-reset
   suffices — but history says SMC reset is usually required. Answer
   before designing, may kill the approach.
3. Cheap rule-out done: `/dev/ttyS0..3` exist but MacBook Pro 11,1
   exposes no physical serial — `earlyprintk=serial` likely to
   bit-bucket unless user has a USB-serial adapter mapped. Check
   before committing to that option.

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

**Test.233 plan candidates (blocked on user answer about SMC↔TCM):**
- **If TCM survives SMC reset** → build minimal TCM ring-buffer logger.
  Use BAR2 window: reserve the last ~16 KB of TCM (fw ramsize=0x9c000..0xa0000),
  driver writes breadcrumb records via `brcmf_pcie_copy_mem_todev`; post-wedge
  reader uses `dd resource2` to pull the ring. Cost: ~1 day of driver code +
  a reader script.
- **If TCM is wiped by SMC reset** → either (a) add a stub shared-memory
  struct in TCM pre-set_active so fw can make progress, turning the
  diagnostic into a forward-step, or (b) try netconsole/USB-serial via
  second host (user previously declined, may be worth revisiting).
- **Forward-path option (independent of logging):** study upstream
  `brcmf_pcie_init_share` and build a minimal shared-memory struct in
  TCM BEFORE set_active. Even if the wedge still happens, the stumble
  point should shift; if it stops wedging, we've found the missing
  piece. This is the natural next step the DMA-target-missing theory
  already implied — advisor now says it may double as a discriminator
  cheaper than a full logger.

**Logging transport status:**
- journald: drops ~15–20 s of tail when host loses userspace (confirmed tests 226/227/231/232).
- pstore: doesn't fire — bus-wide stall freezes watchdog CPU (tests 227/228/229).
- netconsole: user declined second-host setup.
- TCM ring buffer: not yet tested. Strongest remaining transport. Post-wedge BAR0 fast-UR proven alive. **Blocking unknown: whether SMC reset wipes TCM.**
- `earlyprintk=serial`: `/dev/ttyS0..3` exist but MacBook has no exposed port — likely bit-bucket without USB-serial adapter.

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

## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
