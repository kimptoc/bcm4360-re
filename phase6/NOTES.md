# Phase 6: wl Clean-Room Analysis

## Goal

Use clean-room analysis of proprietary `wl` behavior to answer only the
questions that matter to the open BCM4360 bring-up:

- what host-side initialization does `wl` do that `brcmfmac` does not?
- which firmware paths are real at runtime versus merely present in the blob?
- what host-visible registers, structures, or event paths should Phase 5 test
  next?

This file is the **Phase 6 map**, not the full analysis archive. For current
session state, read [RESUME_NOTES.md](../RESUME_NOTES.md). For pinned facts,
read [KEY_FINDINGS.md](../KEY_FINDINGS.md).

## Inputs

- `wl.ko` extracted from the installed broadcom-sta package
- symbol tables and relocation scans
- targeted disassembly helpers in `phase6/*.py`
- Phase 5 runtime observations and logs

## Current Phase-6 Summary

Phase 6 produced two kinds of value:

1. **Positive structure findings**
   It mapped major bring-up families in `wl`, especially PMU/PLL/PCIe init
   clusters that are absent from upstream `brcmfmac`.

2. **Negative/runtime-correction findings**
   It showed that several attractive-looking FullMAC paths in the blob are not
   the paths exercised by the currently observed live runtime.

That second category is strategically more important right now. Phase 6 did not
prove the project impossible; it proved that some recent hypotheses were aimed
at the wrong runtime.

## Major Results

### 1. `wl` contains substantial PMU/PLL/PCIe bring-up logic absent from upstream `brcmfmac`

The earliest and still-valid Phase-6 conclusion is that `wl` performs a much
broader initialization sequence before or around ARM/D11 release than upstream
`brcmfmac` does. That includes:

- PMU resource setup
- PLL setup/reset
- chipcommon/clock control work
- PCIe-specific WARs and attach/up paths
- OTP-related power/control setup

This remains a strong long-term reason to keep Phase 6 alive.

### 2. Presence in the blob is not evidence of live execution

Later Phase-6 work corrected an important methodological mistake:

- the blob contains both FullMAC/wlc code and offload/hndrte helpers
- the live runtime being observed after ARM release is not automatically the
  most feature-rich or obvious code family present in the image

The repo’s late-April work showed that several previously emphasized `wl_probe`
and `wlc_*` paths appear structurally dead for the observed live runtime.

### 3. The D11 `0x48080` wake-mask path is not the active runtime answer

Phase 6 successfully identified the FullMAC-side D11 wake-mask mechanism, but
that became a cautionary result rather than the solution:

- it is a real mechanism in the blob
- it explains a FullMAC-side path
- it does not explain the observed offload/hndrte runtime that Phase 5 is
  actually exercising

That is still useful. It tells the project where **not** to focus next.

## What Phase 6 Still Supports

Despite the dead-code corrections, several Phase-6 directions remain valuable:

- extracting concrete PMU/PLL/resource-init deltas from `wl`
- identifying live register-level differences between `wl` bring-up and the
  current `brcmfmac` harness
- correlating wrapper/OOB, MSI, or event plumbing hypotheses with firmware-side
  structures

## What Aged Out

The following Phase-6 patterns should now be treated cautiously:

- broad callgraph expansion without a runtime discriminator
- assuming `wl_probe`/`wlc_attach`/`wlc_bmac_up` are relevant just because they
  are richly referenced in the blob
- promoting a static finding directly into a runtime explanation without a
  Phase-5 observable

The recent repo state calls this out explicitly as
“convergence-without-progress.”

## Best Next Work For Phase 6

1. Support a specific Phase-5 runtime probe.
   Current example: T300 BAR2-only sched_ctx / OOB-mapping pass — see
   `../t299_next_steps.md` and `../PLAN.md` post-T299 section. Phase 6
   help is welcome on the static prep step (writer of `sched_ctx+0x358`,
   class/core/slot table tying OOB bit positions to ISR nodes). The
   previously listed `test.288a` lead is RETIRED (wedged in T297 per
   KEY_FINDINGS row 85; superseded by T298's BAR2-only ISR-list
   extraction at primary-source level, then T299's bit-for-bit
   reproduction with ASPM disabled).

2. Prioritize `wl` comparison work that yields register or event deltas.
   Example: live MMIO/config-space comparison, or explicit initialization-table
   differences that can be mapped to host-visible behavior.

3. Deprioritize more broad dead-code archaeology unless new runtime evidence
   makes it relevant again.

## Canonical Evidence Pointers

- Live frontier: [RESUME_NOTES.md](../RESUME_NOTES.md)
- Cross-phase facts: [KEY_FINDINGS.md](../KEY_FINDINGS.md)
- Phase-5 runtime arc: [phase5/notes/phase5_progress.md](../phase5/notes/phase5_progress.md)
- Raw helper scripts and analysis outputs: `phase6/*.py`, `phase6/*.md`, `phase6/*.out`
