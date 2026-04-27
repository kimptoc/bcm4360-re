# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by
reverse-engineering the host-to-firmware protocol used by the proprietary `wl`
driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded,
giving us the ability to trace driver behaviour, read hardware registers, and
compare against the existing `brcmfmac` codebase.

> **Scope of this document:** high-level phase status only. Per-test detail
> (what was tried, what log was captured, what it proved) lives in
> `phase5/notes/phase5_progress.md`, commit messages, and `phase5/logs/`.
> Documentation roles across the repo are defined in `DOCS.md`.

> **Legal constraint:** All reverse engineering follows clean-room methodology
> — observe behavior, document in plain language, implement from that
> documentation. Do not copy disassembly structure directly into driver code.
> See README.md and CLAUDE.md for full guidelines (ref: issue #12).

## Current Status (2026-04-27)

**Active phases:** Phase 5.2 and Phase 6 remain active, but the frontier has
changed.

Phase 5 proved the host can reliably get BCM4360 through download, NVRAM
placement, Apple-specific seed/footer setup, and ARM release. Phase 6 then
clarified that recent static work had drifted into the wrong runtime model:
the live firmware path is the hndrte/offload runtime, while the `wl_probe →
wlc_* → wlc_bmac_*` FullMAC path exists in the blob but appears dead for the
currently-running mode.

### What is firmly established

- BCM4360 support patches in `brcmfmac` are sufficient to download the 442 KB
  firmware, release ARM, and keep host control long enough for meaningful
  observation.
- The host-written `shared_info` handshake at `TCM[0x9D0A4]` is real and
  reproducible: firmware writes back the console pointer field at `+0x010`,
  proving the firmware listens at that structure.
- The firmware then reaches a stable idle/WFI state rather than immediately
  crashing. This is a live runtime waiting for an event, not a dead CPU.
- The popular candidate wake paths have both weakened:
  - PCIe2 mailbox/doorbell probing has been tried extensively and did not wake
    the firmware.
  - The D11 `+0x16C` / `0x48080` wake-mask path belongs to dead FullMAC code,
    not the observed live path.

### What this means strategically

The project is no longer blocked on "does the firmware run?" It does.
The blocker is now narrower and more concrete:

- What wake or host-side event does the live offload/hndrte runtime expect
  after entering WFI?
- Is that event an interrupt path, a wrapper-side OOB/agent signal, MSI
  plumbing, or direct memory polling by the firmware main loop?

That is a better problem than the project had a week earlier, but it also means
further static callgraph deep-dives have sharply reduced value until a new
runtime discriminator lands.

### Current highest-value next work

1. **Gather a new runtime discriminator.**
   The leading pending probe is the already-compiled read-only `test.288a`
   wrapper-register read of chipcommon-wrap and PCIe2-wrap OOB-selector
   registers. This directly tests the still-live "wrapper/OOB wake path"
   hypothesis without adding new code.

2. **Reduce dependence on single-fire interpretations.**
   Substrate instability is now a first-order constraint. Future hardware tests
   should be chosen for high discrimination per fire and judged over repeated
   attempts where possible.

3. **Resume `wl` comparison work only where it produces runtime deltas.**
   The Phase 6 thread still matters, but the best remaining value is likely
   live `wl` MMIO/config comparison or explicit register-sequence comparison,
   not more broad dead-code archaeology.

### Deferred / lower-priority lines

- Broad OpenWrt/Asahi/SDK patch surveys remain lower priority than primary
  runtime discrimination on this exact hardware.
- More deep static tracing of orphaned FullMAC code should wait until runtime
  evidence suggests that code path is relevant again.

### Canonical sources for detail

- Cross-phase facts: `KEY_FINDINGS.md`
- Live frontier and next probe: `RESUME_NOTES.md`
- Detailed phase-5 arc: `phase5/notes/phase5_progress.md`
- Phase-6 analysis threads: `phase6/NOTES.md`

---

## Historical Detail

Older Phase-5 recovery chronology is intentionally not duplicated here.

Use:

- `phase5/notes/phase5_progress.md` for the detailed Phase-5 story arc
- `RESUME_NOTES_HISTORY.md` for archived session/test chronology
- `KEY_FINDINGS.md` for the load-bearing conclusions that survived that work
