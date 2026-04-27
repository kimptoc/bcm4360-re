# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 — live offload runtime distinguished from FullMAC dead code)

**Model.** The blob carries two runtimes; the live one is HNDRTE/offload, not
the `wl_probe → wlc_*` FullMAC chain. Firmware boots, populates `sched_ctx`,
and idles at WFI as normal. The earlier "wake gate STRUCTURALLY CLOSED"
framing applies to the FullMAC code path, not the live offload runtime.

**What just changed.** T299–T306 (this session) traced the live BFS, ruled
out FullMAC reachability via static heuristics, and reconciled with empirical
test.290a chain-walks (n=2, never populated) and test.287c sched_ctx readings
(stable across t+5/30/90 s). Full synthesis lives in
[phase6/t299_t306_offload_runtime.md](phase6/t299_t306_offload_runtime.md).
Load-bearing facts promoted to KEY_FINDINGS (new row plus SUPERSEDED-SCOPE
markers on rows 159 / 160).

**Next discriminator.** `test.288a` (chipcommon-wrap + PCIe2-wrap OOB-selector
read, already compiled into the driver, never fired). Targets KEY_FINDINGS
row 148's untested chipcommon-wrapper wake hypothesis. Read-only, single
module-param flag, no rebuild required.

**What not to retry blindly.**

- More static-disasm probes against the FullMAC chain — treat it as dead in
  offload mode. The session already hit the convergence-without-progress
  failure mode there.
- More PCIe2 mailbox / D11 INTMASK wake probes — both empirically and
  structurally exhausted (rows 125 / 159-superseded).
- Insmod cycles on stale substrate without budgeting for the ~3/4 null-fire
  rate per row 85.

**Substrate state.** No hardware fires this session. Substrate-null cluster
T294/T295/T296 from prior sessions is unresolved but no longer strategically
blocking the new direction.

## Archived detail

Older PRE/POST test blocks have been migrated to
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).

Current policy for this file:

- keep the current-state block above
- keep only the latest 2-3 active PRE/POST test pairs when a hardware campaign
  is in flight
- move older chronology to history
- move broader synthesis into phase notes or `KEY_FINDINGS.md`

For the recent T290/T294/T296-era chronology, see:
- [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md)
- [phase5/notes/phase5_progress.md](phase5/notes/phase5_progress.md)
- [KEY_FINDINGS.md](KEY_FINDINGS.md)

The next action remains the read-only `test.288a` runtime discriminator already
summarized in the current-state block above.
