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

## Current Status (2026-04-27, post-T299)

**Active phases:** Phase 5.2 and Phase 6 remain active. T298 (BAR2-only
ISR-walk) shifted the frontier to "what HW event fires the OOB slots".
T299 then falsified the ASPM hypothesis for the [t+90s, t+120s] wedge
(KEY_FINDINGS row 152): full ASPM disable on 03:00.0 + 02:00.0 + root
port 00:1c.2 reproduced T298's 2-node ISR result bit-for-bit, and still
wedged at end-of-t+90s probe — same bracket as T270-BASELINE / T276 /
T287c / T298. Also corrected: the wedge is at end-of-t+90s, NOT during
rmmod (boot-end timestamps prove rmmod after `sleep 150` never executed
in any of these fires; KEY_FINDINGS row 163 updated).

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

Sequence per `t299_next_steps.md`: **T300 (A2 — BAR2-only sched_ctx /
OOB-mapping probe) first, then A3 (one-shot OOB Router pending read at
0x18109100) only if A2 yields no mapping. Wake-injection (B) deferred
until pending-event state is observable.**

1. **T300 — BAR2-only sched_ctx + ISR-list metadata pass.** Two-step:
   (1a) static prep — find writer of `sched_ctx + 0x358`, sweep
   `sched_ctx + 0x2c0..0x35c` (esp. +0xd0/+0xd4/+0x300..+0x35c), and
   ISR list handling around `TCM[0x629A4]`, looking for any class /
   core / slot table that ties OOB bit positions to ISR nodes; (1b)
   if a BAR2-readable mapping candidate is found, implement a
   single-purpose probe that reads ONLY: `TCM[0x6296C]`, `TCM[0x629A4]`,
   ISR nodes/masks, `sched_ctx + 0x2c0..0x35c`, console struct ptr/wr_idx.
   **Forbidden in T300:** any `BAR0_WINDOW` write, `select_core`,
   chipcommon read, PCIE2 read, wrapper read, or OOB-router BAR0 read.
   The fire MUST exit before the [t+90s, t+120s] bracket (use
   `bcm4360_test269_early_exit=1` or a similar early-exit path).

2. **A3 — OOB Router pending-events read at `0x18109100`** (only if T300
   step 1a finds no usable BAR2 mapping). Single-purpose surgical probe:
   raw `BAR0_WINDOW = 0x18109000`, read `BAR0 + 0x100`, exit. Must cite
   KEY_FINDINGS row 85 in the PRE-TEST and explain why OOB Router is a
   distinct backplane agent from the chipcommon/PCIE2-wrap surfaces that
   wedged in T297.

3. **Wake-event injection (B)** — DEFERRED. Per advisor constraint walk
   2026-04-27 evening: each enumerated B sub-option (MSI assert, olmsg
   ring write, DMA transfer, `pci=noaspm`) lacks a mechanism that
   actually fires `oobselouta30` bit 0 or bit 3. MAILBOXMASK=0 +
   write-locked (KEY_FINDINGS rows 117/118/126) blocks the MSI/MBM
   path; Phase 4B row 39 shows fw doesn't poll the olmsg ring; ASPM
   was already falsified by T299. B becomes viable once OOB pending
   state is observable (one of the candidates from `t299_next_steps.md`
   §4: real DMA over shared_info buffer, PCI-CDC message-queue path
   per fw banner, or OOB-router pending-driven event-source choice).

   The previously-recommended `test.288a` BAR0 probe is RETIRED —
   T297 wedged on it (row 85), and T298 already extracted the OOB
   result from TCM without touching BAR0.

### Hardware Fire Gate (per `t299_next_steps.md`)

Before any next hardware fire, the PRE-TEST block MUST state:

- whether the test touches BAR0
- if BAR0 is touched, the exact address and exact expected
  value/bit pattern
- if BAR2-only, that it performs no `BAR0_WINDOW`, `select_core`,
  chipcommon, PCIE2, wrapper, or OOB-router reads
- how the test exits before the [t+90s, t+120s] wedge bracket
- what single bit of information the fire is expected to decide

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
