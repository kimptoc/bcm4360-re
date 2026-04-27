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

Post-T304e: **all three host-driveable wake-injection candidates
examined this session are now CLOSED.** Strategic pivot point reached.
Reports: `phase6/t304b_fw_poller_enumeration.md`,
`phase6/t304c_pmu_gpio_surface.md`,
`phase6/t304d_pciedngl_isr_disasm.md`,
`phase6/t304e_pciedev_info_pointer_trace.md`. KEY_FINDINGS gained 5
new rows this session capturing the load-bearing verdicts.

**Closed surfaces (will not be re-investigated without new evidence):**

1. **PMU / GPIO surface — CLOSED** (T304c). Both host-reachable via
   BAR0 windowing but neither has a registered fw ISR. T298
   enumerated exactly 2 live ISRs (pciedngl_isr OOB bit 3, RTE
   chipcommon-class fn@0xB04 OOB bit 0) — no PMU- or GPIO-class ISR.

2. **DMA-via-olmsg via pciedngl_isr — CLOSED** (T304d). pciedngl_isr
   end-to-end disasm: single-bit mailbox-doorbell handler; reads from
   `bus_info+0x24` transport-local ring; NEVER touches the olmsg DMA
   ring at TCM[0x9d0a4]. T304b confirmed no other live ISR handler.

3. **H2D_MAILBOX_1 doorbell — CLOSED** (T304e). Two independent
   strands: (a) **Empirical:** pciedngl_isr (the only bit 0x100
   handler) has NEVER fired across n=8 fires — `wr_idx=587` frozen at
   every probe stage, and pciedngl_isr's first action is
   `printf("pciedngl_isr called\n")` which would advance wr_idx if it
   had ever fired. (b) **Protocol:** fw blob contains ZERO references
   to HOSTRDY_DB1 (0x10000000), the flag upstream brcmfmac's
   `brcmf_pcie_hostready()` uses to gate H2D_MAILBOX_1 writes. fw
   never advertises hostready → upstream driver never writes
   H2D_MAILBOX_1 → ISR never fires. Both strands close this surface
   independently of the (still-open) MMIO-vs-TCM resolution for
   `bus_info[+0x18]`.

**Caveat carried forward:** T304e did not actually trace the writer
of `pciedev_info[+0x18]` (pcidongle_probe stores at 0x1EBE-0x1EE8
left undisassembled). The "TCM shadow proven" framing in T304e's
report is INFERRED, not established — the agent's two arguments are
weak (T289 "no PCIE2 base literals" doesn't preclude runtime-loaded
base addresses from EROM walk; "computed value at fn@0x1E44 means
TCM" is wrong — `str.w r0, [r2, #0x100]` with computed r0 is the
standard MMIO RMW idiom). The strategic verdict (H2D_MAILBOX_1
closed) holds independently. **If a future session pivots back to
wake-injection, the bus_info[+0x18] physical identity is a real gap.**

**Strategic pivot — wake question reframed:**

The "find a host-injection path" frame has been thoroughly exhausted
on the surfaces accessible to a static + single-shot empirical
campaign. Two parallel option-2 static passes (T304f + T304g)
further narrowed the picture:

- **T304f:** Offload runtime does NOT initialize D11 MAC. Zero D11
  register writes in live code, zero D11-base literals, zero
  `si_setcoreidx(0x812)` calls. fw stores D11 base at sched_ctx[+0x88]
  via EROM walk (T287c runtime confirmed) but never writes any D11
  register. **The "synthetic injection via D11/PHY config" angle
  under option 2 is closed by D11 dormancy.**
- **T304g:** Static ISR-registration audit confirms T298's empirical
  2-node enumeration (bits 0+3) is the wake surface — but
  inadvertently exposed a real BFS coverage gap (the path by which
  pciedngl_isr is registered at runtime is NOT reached by the BFS).
  Strategic verdict (2 ISRs, bits 0+3) is unchanged because T298
  directly observed the linked list — empirical primary-source. But
  the BFS-based "no other ISRs could exist" inference is weakened.

**Refined direction triage post-T304g:**

1. **`wl` driver comparison work — HIGHEST-VALUE REMAINING DIRECTION.**
   Previously sat in "deferred / lower-priority" since post-T299. The
   vendor `wl` driver presumably DOES make this fw fire pciedngl_isr
   (or some other ISR) successfully, since the chip works under the
   original driver. Capturing the register-write sequence `wl` issues
   during init/up — and diffing against what brcmfmac does — is the
   single highest-value remaining direction. Concrete first step:
   load `wl` on a parallel system or in a controlled environment and
   capture MMIO/config-write trace via instrumentation (ftrace,
   kprobes, or a strategic LD_PRELOAD wrapper).

2. **HW-internal events surface — EFFECTIVELY CLOSED** without fw
   modification. T304f closes D11; T304c closes PMU/GPIO; chipcommon
   events have no handler beyond bit 0 RTE class. The only remaining
   structural unknown is whether a third ISR could exist via the
   indirect-dispatch BFS gap T304g exposed — but T298's empirical
   2-node count is the load-bearing fact, not a static enumeration.

**No fire warranted.** Awaiting user steer on direction.

**Pattern caveat** (n=3 occurrences this session: T304c, T304e,
T304f): subagents have repeatedly invented runtime ISR-firing claims
from static identification cites. When a static report says "fires"
or "executes", cross-check against the wr_idx=587 frozen record
before propagating. **Static reach ≠ runtime execution.**

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
