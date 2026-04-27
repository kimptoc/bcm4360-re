# T297 Next Steps

Date: 2026-04-27

## Decision

After T297, take the **BAR2-only relocation** branch, preceded by one narrow
static pass. Do not run another BAR0/chipcommon/wrapper probe until the next
plan explicitly explains why KEY_FINDINGS row 85 does or does not apply.

T297 produced no new runtime signal: the host wedged before any T297-specific
instrumentation fired. It also became the fourth consecutive null fire in the
T294/T295/T296/T297 cluster, with the wedge again upstream of the actual
discriminator. That makes another "fresh substrate, retry once more" BAR0
fire the wrong next move.

## Why BAR2-first

The useful distinction is no longer "runtime probe vs static analysis". It is:

> Can the next artifact avoid BAR0 completely?

Broad static archaeology on the old FullMAC path is spent. T299-T306 already
reframed the live runtime as HNDRTE/offload, not the `wl_probe -> wlc_*`
FullMAC chain. More analysis of that dead path is unlikely to improve the
next hardware decision.

But a small static pass is still worthwhile if it directly supports a BAR2-only
probe. The goal is to find TCM-resident consumers, shadows, or bookkeeping for
the wrapper/OOB routing state, not to expand the call graph generally.

## Near-Term Plan

1. Run a targeted static pass over the live offload-side paths only:
   - `hndrte_add_isr`
   - `BIT_alloc`
   - `sched_ctx` / `si_t`
   - ISR node/list storage around `*0x629A4`
   - pciedngl ISR registration and event bookkeeping structs

2. For that static pass, answer one concrete question:
   - Is the wrapper/OOB selector result, allocated bit index, ISR node, or
     pending-event mapping copied into TCM anywhere the host can read through
     BAR2?

3. If yes, implement a BAR2-only runtime probe that reads only TCM state:
   - existing `sched_ctx` fields
   - core/reg/wrap tables
   - ISR node list and allocated bit indices, if located
   - pending-event or ISR metadata structs, if reachable
   - no `BAR0_WINDOW` writes
   - no `select_core`
   - no chipcommon, PCIE2, or wrapper BAR0 reads

4. If no TCM shadow or consumer can be found quickly, switch to static-only
   until there is a concrete predicted wrapper/OOB bit pattern. The next BAR0
   fire should be one-shot-for-one-prediction, not a general probe.

## Hardware Fire Gate

Before any next hardware fire, the PRE-TEST block must include:

- A citation to KEY_FINDINGS row 85.
- A statement of whether the test touches BAR0.
- If it touches BAR0, the exact predicted register value or bit pattern being
  tested.
- If it is BAR2-only, an explicit statement that it does not write
  `BAR0_WINDOW`, call `select_core`, or read chipcommon/PCIE2/wrapper MMIO.

## Current Recommendation

Build the next experiment as **BAR2-only relocation after targeted static
prep**. Do not retry T288a/T297 as-is.
