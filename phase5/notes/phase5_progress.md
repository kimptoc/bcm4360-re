# Phase 5: brcmfmac BCM4360 Support

## Goal

Use `brcmfmac` as the host-side bring-up harness for BCM4360:

- add missing chip support
- prove firmware download and ARM release
- characterize the live firmware runtime after release
- identify the missing host-side conditions needed to reach useful operation

This file is the **Phase 5 story arc**, not the live handoff. For the current
frontier, read [RESUME_NOTES.md](../../RESUME_NOTES.md). For pinned facts, read
[KEY_FINDINGS.md](../../KEY_FINDINGS.md).

## Inputs

- `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/*`
- `phase5/logs/test.*`
- Phase 4 shared-info results
- Phase 6 clean-room `wl` analysis

## Current Phase-5 Summary

Phase 5 succeeded at the original bring-up problem:

- `brcmfmac` now recognizes BCM4360
- firmware download works
- ARM release works
- Apple-specific host writes materially affect firmware progression
- the firmware reaches a live idle/WFI runtime rather than immediately dying

Phase 5 did **not** yet solve the operational problem:

- the firmware never reaches normal host/firmware runtime under the current
  host setup
- the exact wake/handshake/event path after ARM release remains unresolved
- substrate instability makes high-risk MMIO experiments expensive and noisy

## Major Results

### 1. BCM4360 support landed in the harness

Early Phase 5 established the minimum host support required to talk to the
chip through `brcmfmac`:

- added missing chip and PCI IDs
- mapped BCM4360 firmware selection
- fixed TCM rambase assumptions (`rambase = 0`)
- replaced unsafe `memcpy_toio` behavior with 32-bit writes in the critical
  firmware/NVRAM path
- guarded the `INTERNAL_MEM` reset path that does not exist on BCM4360

Net result: the project moved from “unsupported chip” to “firmware download and
ARM release are under host control.”

### 2. Msgbuf is not the answer

Once ARM release worked cleanly, the expected upstream PCIe `msgbuf` handshake
did not appear. That confirmed the earlier cross-phase finding that BCM4360 is
not an ordinary `brcmfmac` PCIe/msgbuf target.

This is the strategic pivot of Phase 5:

- `brcmfmac` is useful as a bring-up and observation harness
- it is not, unmodified, the final transport model for BCM4360

### 3. Apple-specific host writes matter

The project found that Apple-flavored setup details are not cosmetic:

- NVRAM/footer/seed handling changes boot progression materially
- the host-written `shared_info` structure at `TCM[0x9D0A4]` is real
- firmware writes back the console pointer at `shared_info[+0x010]`

That is one of Phase 5’s most important positive results: the firmware listens
to host-prepared state beyond the bare firmware blob itself.

### 4. The firmware is alive after release

The current model is no longer “firmware crashes immediately.”

Observed Phase-5 behavior now supports a more precise claim:

- ARM release succeeds
- the firmware executes
- scheduler / silicon-info state becomes populated
- the runtime settles into WFI/idle waiting for an event or condition

That reframed the work from generic crash forensics into a narrower wake-path
and runtime-protocol problem.

## What Phase 5 Ruled Out

At a high level, Phase 5 has already ruled out several broad explanations:

- basic chip-ID / firmware-mapping absence
- wrong TCM base assumption
- firmware-download mechanics as the primary blocker
- “ARM release itself crashes the host” as a sufficient explanation
- ordinary upstream PCIe/msgbuf shared-ram flow as the active runtime
- simple PCIe mailbox doorbell pokes as an early wake solution

For the authoritative versions of those claims, use `KEY_FINDINGS.md`.

## What Aged Out

Several older Phase-5 ideas are now stale or incomplete:

- “BCM4360 firmware speaks exactly what upstream PCIe wants”
- “if we just reach `pcie_shared`, the rest will fall into place”
- “the D11 `0x48080` wake-mask path explains the live runtime”
- “more one-off BAR0 pokes will probably settle the question”

Those were useful intermediate models, but they no longer describe the best
current understanding.

## Current Risks / Constraints

### Substrate instability

Recent test campaigns showed that repeated hardware fires can wedge at
different points along the same otherwise-known path. That means:

- single-fire interpretations are weak
- a good discriminator is worth more than a clever but noisy probe
- read-only or low-surface-area tests are preferred when possible

### Documentation drift

Phase 5 generated the most logs and ad hoc test planning in the repo. The new
documentation split should keep this file as synthesis, not as a rolling
session diary.

## Post-T299 update (2026-04-27)

T298 (BAR2-only ISR-list walk, 2026-04-27 14:19 BST) cleared the BAR0
noise belt and identified the OOB-routing slots at primary-source
level: RTE chipcommon-class ISR allocated bit 0 of `oobselouta30`;
`pciedngl_isr` allocated bit 3.

T299 (2026-04-27 15:29 BST) reproduced the 2-node ISR result
**bit-for-bit** under full upstream ASPM disable (cmdline
`pcie_aspm.policy=performance` + runtime sysfs flip → 03:00.0 +
02:00.0 + root port 00:1c.2 all `ASPM Disabled`). Wedged at
end-of-t+90s probe — same point as T270-BASELINE / T276 / T287c /
T298. **ASPM falsified** as the cause of the [t+90s, t+120s] wedge
bracket (KEY_FINDINGS row 152). Also corrected: the wedge has always
been at end-of-t+90s, not at rmmod — boot-end timestamps prove rmmod
(after `sleep 150`) never executed in any of these fires
(KEY_FINDINGS row 163).

## Best Next Work For Phase 5

1. **T300 = BAR2-only sched_ctx / OOB-mapping pass.** Per
   `../../t299_next_steps.md`: static prep for writer of
   `sched_ctx + 0x358`, sweep `+0x2c0..+0x35c`, and ISR-list
   handling around `TCM[0x629A4]`. If a BAR2-readable mapping
   candidate exists, fire a single-purpose probe (no `BAR0_WINDOW`
   write, no `select_core`, no chipcommon/PCIE2/wrapper/OOB-router
   reads) that exits before the [t+90s, t+120s] wedge bracket.
   `test.288a` is RETIRED (T297 wedged on it; T298 obsoleted it).

2. If T300 step 1 finds no BAR2 mapping, A3 (one-shot OOB Router
   pending read at `0x18109100`) is the surgical fallback — must
   cite KEY_FINDINGS row 85, justify why OOB Router is a distinct
   backplane agent from the chipcommon/PCIE2-wrap surfaces, and
   exit before t+90s.

3. Wake-event injection (B) is DEFERRED until pending state is
   observable. Per advisor constraint walk 2026-04-27, the
   enumerated B sub-options (MSI assert, olmsg-ring write, DMA
   "over olmsg ring", `pci=noaspm`) lack a mechanism that fires
   `oobselouta30` bit 0 or bit 3.

4. Prefer runtime discriminators over more broad static
   interpretation. Reason: the active blocker is "what HW event
   sets OOB bit 0 or bit 3?" — answered by step 1 or step 2, not
   by more callgraph work.

5. Use Phase 6 only where it sharpens a specific host-side
   experiment (e.g., the T300 static prep step is exactly that).

## Evidence Pointers

- Live frontier: [RESUME_NOTES.md](../../RESUME_NOTES.md)
- Cross-phase facts: [KEY_FINDINGS.md](../../KEY_FINDINGS.md)
- Raw test evidence: `phase5/logs/test.*`
- Historical chronology: [RESUME_NOTES_HISTORY.md](../../RESUME_NOTES_HISTORY.md)
