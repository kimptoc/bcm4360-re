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

## Current Status (2026-04-27, post-T304)

**Active phases:** Phase 5.2 and Phase 6 remain active. The frontier is
"what HW event fires the OOB slots that wake the offload runtime from
WFI". This question has narrowed substantially since the previous PLAN
revision — see "What changed since post-T299" below.

### What changed since post-T299

T298 → T304 fire chain (2026-04-27) closed several major sub-questions:

- **T299** falsified the ASPM hypothesis for the [t+90s, t+120s] wedge
  bracket (KEY_FINDINGS row 152). Full ASPM disable on 03:00.0 +
  02:00.0 + root port 00:1c.2 reproduced T298's 2-node ISR result and
  still wedged at end-of-t+90s probe. Also corrected: the wedge is at
  end-of-t+90s, NOT during rmmod (boot-end timestamps prove rmmod after
  `sleep 150` never executed in any wedge fire; row 163 updated).
- **T300/T301** identified the ARM OOB Router agent (BCMA core 0x367
  at 0x18109000) as BAR0-reachable from host at post-set_active timing
  (n=2 sample-1 read clean, `pending=0x0`). T301 sample-2 wedged AT the
  re-access at t+60s.
- **T302b** confirmed the wedge bracket is robust without test300 (n=6,
  later n=8); test284_premask confound eliminated.
- **T303** read the fw scheduler's slot table (`sched+0xD0..+0xF0`):
  6 populated entries match host-side `brcmf_pcie_select_core` exactly,
  OOB Router (0x367) is NOT in the slot table — confirming fw uses the
  separate `sched+0x358 = 0x18109000` pointer for OOB Router access.
- **T303d** (static, no fire) showed the OOB pending-events register at
  0x18109100 is read ON-DISPATCH ONLY by `fn@0x9936`, called only from
  `fn@0x115c` reached only via fallthrough from the exception-vector
  chain. fw IS in WFI; only an ARM exception (HW IRQ assert) wakes it.
- **T303e** mapped a 6-gate stack between "host writes OOB Router
  pending bit" and "fn@0x115c executes on ARM"; gate 1 (write
  semantics) was the cheapest empirical question.
- **T304** fired the gate-1 probe: wrote 0xFFFFFFFF to 0x18109100 from
  host BAR0 at post-set_active, read back 0x00000000. Per advisor
  ruling-out (only bit 0 had a registered ISR at this stage; bits
  1/2/4-31 would have remained SET under RW1S), the verdict is **W1C
  or RO** — host cannot set OOB pending bits via this register.
  **Option B (host-injected wake via OOB Router pending) is DEAD.**

KEY_FINDINGS new row above row 162 pins the gate-1 verdict.

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

Post-T304 the OOB Router host-injection path is closed. Two parallel
static reconnaissance passes (T304b + T304c, completed 2026-04-27
21:25 BST, no fire) further narrowed the option space. Reports are at
`phase6/t304b_fw_poller_enumeration.md` and
`phase6/t304c_pmu_gpio_surface.md`. KEY_FINDINGS gained two new rows
(no-live-pollers + PMU/GPIO dormant) capturing the load-bearing
verdicts.

**Refined option triage:**

1. **PMU / GPIO surface — CLOSED** (T304c). Both subsystems are
   host-reachable via BAR0 windowing but neither has a registered fw
   ISR in the offload runtime. T298 enumerated exactly 2 live ISRs
   (pciedngl_isr OOB bit 3, RTE chipcommon-class fn@0xB04 OOB bit 0)
   — no PMU- or GPIO-class ISR present. Even if host writes
   PMU_WATCHDOG / PMU_RES_REQT or toggles GPIO, no fw handler will
   receive a resulting IRQ. **Closed without fw modification.**

2. **DMA-via-olmsg trip path — PARTIALLY OPEN** (T304b). Zero live fw
   pollers found in the 311-fn BFS reach set; the olmsg ring cannot
   be serviced by a fw poller. Viability hinges on (a) DMA-completion
   → IRQ wiring (MSI or OOB bit assertion), and (b) a registered ISR
   callback for that IRQ. The most likely candidate handler is
   pciedngl_isr (fn@0x1c98/0x1c99) — the cheapest next static move
   is to disassemble pciedngl_isr's event-dispatch logic and
   determine what events it processes. If it handles PCIe-side DMA
   completion events, option 2 has a known target; if not, option 2
   needs different machinery.

3. **Passive sample-2 re-read of OOB Router pending — LOWER
   PRIORITY.** With gate 1 closed, even if pending transitions
   naturally, host can't act on it. Useful only as observational
   evidence about idle-state fw/agent behaviour.

**Next concrete move (no fire required):** static disassembly of
pciedngl_isr to gate option 2's viability. Both T304b §"Open
Questions" #1 and T304c §6.1.3 flag this as the unresolved
question. Pending user approval to launch.

**Heuristic caveat (per KEY_FINDINGS row 161):** the 311-fn live BFS
rests on push-lr-as-fn-start + direct-BL coverage; indirect-call sites
may escape detection. T304b's "no pollers" is bounded by these
heuristics. If a future probe surfaces evidence of a missed indirect
dispatcher, revisit option 2's premise.

### Hardware Fire Gate (per `t299_next_steps.md`, retained)

Before any next hardware fire, the PRE-TEST block MUST state:

- whether the test touches BAR0
- if BAR0 is touched, the exact address and exact expected
  value/bit pattern
- if BAR2-only, that it performs no `BAR0_WINDOW`, `select_core`,
  chipcommon, PCIE2, wrapper, or OOB-router reads
- how the test exits before the [t+90s, t+120s] wedge bracket
  (n=8 reproduction count as of T304)
- what single bit of information the fire is expected to decide

T304 demonstrated that BAR0 OOB Router *write*-then-readback at
post-set_active is also tolerated (n=1, alongside n=3 read-only
sample-1 fires). The "OOB Router agent at post-set_active is safe for
single-shot transactions" datum extends to writes, not just reads.

### Methodology disciplines (retained)

Reduce dependence on single-fire interpretations. Substrate
instability is a first-order constraint (KEY_FINDINGS row 85). Future
hardware tests should be chosen for high discrimination per fire and
judged over repeated attempts where possible.

The previously-recommended `test.288a` chipcommon BAR0 probe is
RETIRED — T297 wedged on it, and BAR2-only walks have extracted the
relevant OOB allocation without touching it.

### Hardware Fire Gate (per `t299_next_steps.md`)

Before any next hardware fire, the PRE-TEST block MUST state:

- whether the test touches BAR0
- if BAR0 is touched, the exact address and exact expected
  value/bit pattern
- if BAR2-only, that it performs no `BAR0_WINDOW`, `select_core`,
  chipcommon, PCIE2, wrapper, or OOB-router reads
- how the test exits before the [t+90s, t+120s] wedge bracket
- what single bit of information the fire is expected to decide

**Resume `wl` comparison work only where it produces runtime deltas.**
The Phase 6 thread still matters, but the best remaining value is
likely live `wl` MMIO/config comparison or explicit register-sequence
comparison, not more broad dead-code archaeology.

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
