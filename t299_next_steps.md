# T299 Next Steps

Date: 2026-04-27

## Decision

After T299, take the **A2 / BAR2-only sched_ctx mapping** branch first.

Do not fire another broad BAR0 chipcommon/wrapper probe. Do not run another
test that reaches the known t+90s wedge unless the wedge itself is the target.
The next hardware fire should either avoid BAR0 entirely, or touch exactly one
predicted OOB-router register with a clear stopping rule.

## Current Frontier

T299 falsified the ASPM hypothesis for the late wedge:

- T299 ran with `pcie_aspm.policy=performance` plus runtime sysfs
  `policy=performance`.
- 03:00.0, 02:00.0, and the root port were all verified `ASPM Disabled`.
- The probe still wedged at the end of the t+90s readout, matching T270,
  T276, T287c, and T298.
- This was not an `rmmod` wedge. The boot ended before the script could reach
  the post-sleep `rmmod`.

T298/T299 now give the stable primary-source runtime picture:

- Firmware boots, reaches a stable idle/WFI state, and is not dead.
- The live runtime is HNDRTE/offload, not the FullMAC `wl_probe -> wlc_*`
  chain.
- The live ISR list has exactly two nodes:
  - bit 3 / mask `0x8`: `pciedngl_isr`
  - bit 0 / mask `0x1`: RTE chipcommon-class ISR
- `events_p = sched_ctx + 0x358 = 0x18109000`.
- `0x18109000` is the ARM OOB Router core, not chipcommon wrapper space.

The remaining blocker is now narrow:

> What hardware event sets OOB bit 0 or bit 3 in the OOB Router pending-events
> bitmap and wakes the firmware from WFI?

## Why Not BAR0 First

KEY_FINDINGS row 85 is still load-bearing. The T294/T295/T296/T297 cluster
showed that BAR0 chipcommon/wrapper probes can null-fire before the actual
discriminator runs. T298 succeeded specifically because it stayed BAR2-only.

T299 did not de-risk BAR0. ASPM was the candidate explanation for part of the
wedge surface; full ASPM disable made no difference. Therefore A3 remains
useful but risky, and should wait until the remaining BAR2/static signal is
exhausted.

Do not retry `test.288a` or any equivalent broad chipcommon/PCIE2 wrapper
read. T298 already extracted the OOB allocation result from TCM without
touching BAR0.

## Recommended Sequence

### 0. Documentation updates

Before drafting or firing the next PRE-TEST, bring the high-level docs into
line with the corrected post-T299 state.

Required updates:

- `PLAN.md`: update from its post-T298 framing to post-T299. It should say
  ASPM is falsified for the t+90s wedge, A2 is the recommended next step, and
  A3/B are gated behind the BAR2/static pass.
- `phase6/NOTES.md`: remove or qualify stale wording that still points at
  `test.288a` as the cheap next probe. The current rule is that `test.288a`
  is retired because it touches BAR0 wrapper space and T297 already hit the
  row-85 noise belt.
- `phase6/t299_t306_offload_runtime.md`: add a short correction note that the
  older "already-compiled test.288a" recommendation was superseded by T297,
  T298, and T299. The live-runtime conclusion still stands.
- `phase5/notes/phase5_progress.md`: if it is used as a session arc, add a
  concise post-T299 entry: T299 reproduced T298's two-node ISR list under full
  ASPM disable and still wedged at t+90s, so ASPM is not the cause.
- `KEY_FINDINGS.md`: only update if a doc audit finds stale wording that
  conflicts with rows 85, 104, 152, 161, 162, or 163. Those rows are already
  the canonical state.
- `RESUME_NOTES.md`: keep its current-state block as the live source of truth.
  If another PRE-TEST is added, preserve the T299 correction that the wedge was
  not during `rmmod`.

Documentation rule for this cleanup: do not rewrite history or delete useful
old analysis. Add correction notes where old recommendations aged out, and
point readers to T299/T300 direction instead.

### 1. T300 static prep — no hardware fire

Run a targeted static pass over the live offload-side runtime only. The goal is
not more broad callgraph expansion; it is to answer whether the OOB-router
pending-event mapping has any TCM-resident metadata.

Inspect:

- writer/source of `sched_ctx + 0x358`
- `sched_ctx + 0x2c0..0x35c`
- especially `+0xd0`, `+0xd4`, `+0x300..+0x35c`
- ISR list handling around `TCM[0x629A4]`
- any class/core/slot table that ties OOB bit positions to ISR nodes

Stop when the pass either finds a BAR2-readable mapping candidate or clearly
fails to find one.

### 2. T300 BAR2-only sched map

If the static prep identifies useful TCM state, implement a new BAR2-only
runtime probe.

Allowed reads:

- `TCM[0x6296C]` scheduler context pointer
- `TCM[0x629A4]` ISR list head
- ISR nodes and masks
- `sched_ctx + 0x2c0..0x35c`
- existing console struct pointer / write index

Forbidden in this probe:

- no `BAR0_WINDOW` writes
- no `select_core`
- no chipcommon reads
- no PCIE2 reads
- no wrapper reads
- no OOB-router BAR0 reads

The fire should exit before the known t+90s bracket. Prefer an early-exit path
similar to `bcm4360_test269_early_exit`, or a shorter T300-specific exit after
the final useful BAR2 sample.

### 3. If T300 yields no mapping, run A3 as a surgical one-shot

If BAR2/static work cannot expose the pending bitmap, the next discriminator is
the OOB Router pending-events register itself:

- raw `BAR0_WINDOW = 0x18109000`
- read `BAR0 + 0x100` (`0x18109100`)
- optionally read `BAR0 + 0x000` only if the plan has a concrete expected
  value or identity check

This should be a single-purpose probe, not a scan. It must cite KEY_FINDINGS
row 85, explain why OOB Router is distinct from the failed chipcommon/PCIE2
wrapper probes, and exit before t+90s.

### 4. Defer wake injection until pending state is observable

Host-side wake-event injection remains the highest-yield direction once the
pending path is observable. But it should not be the immediate next fire.

Likely productive candidates:

- trigger a real DMA/message transfer over the shared_info DMA buffer
- exercise the PCI-CDC / message-queue path suggested by the firmware banner
- use OOB-router pending observations to choose a specific event source

Avoid more blind mailbox or MAILBOXMASK pokes. Prior T258-T280 work already
made that line weak, and the firmware does not advertise the upstream
HOSTRDY_DB1 protocol.

## Hardware Fire Gate

Before the next hardware fire, the PRE-TEST block must state:

- whether the test touches BAR0
- if BAR0 is touched, the exact address and exact expected value/bit pattern
- if BAR2-only, that it performs no `BAR0_WINDOW`, `select_core`,
  chipcommon, PCIE2, wrapper, or OOB-router reads
- how the test exits before the t+90s wedge bracket
- what single bit of information the fire is expected to decide

## Current Recommendation

Build **T300: BAR2-only sched_ctx/OOB metadata map** after a short static prep.
If that does not produce a concrete mapping, move to **A3: one-shot OOB Router
pending read at 0x18109100**. Only after one of those exposes pending-event
state should the project move to host-side wake injection.
