# T298 — Static pass per t297_next_steps.md: TCM shadow of OOB routing IS readable via BAR2

**Date:** 2026-04-27
**Goal:** answer the single question posed in `t297_next_steps.md` step 2:
*Is the wrapper/OOB selector result, allocated bit index, ISR node, or
pending-event mapping copied into TCM anywhere the host can read through
BAR2?*
**Inputs:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 B,
md5 `812705b3ff0f81f0ef067f6a42ba7b46`).
**Method:** read-only static disasm + literal-pool / string cross-reference,
plus replay of existing primary-source TCM data (T256, T287c, T290a).
**Scripts:**
[`t298_isr_callers.py`](t298_isr_callers.py),
[`t298_isr_b04_id.py`](t298_isr_b04_id.py).
**Hardware fires this pass:** zero. Honours KEY_FINDINGS row 85 stopping rule.

## Answer

**YES.** Each registered ISR's OOB-allocated bit index is shadowed at
`node[+0xC]` of its entry in the linked list whose head pointer lives at
**`TCM[0x629A4]`**. All addresses are BAR2-resident
(< `0xA0000` ramsize, well within BAR2's 2 MB direct TCM window).
A dynamic walk of that list — head ptr → follow `[+0]` next-ptr until null
— enumerates every registered ISR's allocated wake-routing bit, with
zero BAR0 / chipcommon / PCIE2 / wrapper MMIO touches.

## Why this works structurally

`hndrte_add_isr` (fn@0x63C24, T289 §2) runs **`BIT_alloc`** to obtain a
free bit-pool slot from the AI-backplane wrapper agent register
`oobselouta30` at `wrap+0x100`. The class context active at the time of
the call determines which class's wrapper is read — the class is set by
the caller's `r1` arg, propagated into sched_ctx via si_setcoreidx (the
class-0 thunk at 0x27EC), then BIT_alloc reads `[sched+0x254]+0x100`.

After allocation, hndrte_add_isr stores `1 << bit_index` at the new
node's `+0xC` offset. The node is then linked at the head of the list
whose pointer-to-head lives at `*0x629A4`. **The OOB read happens once
during registration; the resulting bit index is persistent in TCM as
long as the ISR remains registered.** Reading the TCM shadow gives us
the same information as reading the wrapper register at registration
time, without ever touching BAR0.

## The three ISRs the fw blob registers

Static enumeration of every direct `bl/blx` targeting `0x63C24` finds
exactly 3 call sites. Each loads its callback fn-ptr into r3 from the
literal pool just before the call:

| Caller | Caller fn boundary | Class arg (r1) | Callback fn ptr | Identity | Live in offload? |
|---|---|---|---|---|---|
| `0x1F28` | inside `pciedngl_probe` (str refs `'pciedngl_probe'`, `'%s: dngl_attach failed'`) | caller-supplied | `0x1C99` (Thumb fn @ `0x1C98`) | **`pciedngl_isr`** (str@0x40685 + body confirmed at 0x1C98 per T269 §1) | **YES** — T256 confirmed at runtime, node[0] @ TCM[0x9627C], bit-3 (`flag = 0x00000008`) |
| `0x63CF0` | fn @ `0x63CC0`; pre-call str refs `'hndrte.c'`, `'hndrte_add_isr: hndrte_malloc failed'` (i.e. RTE core init helper, neighbour of `hndrte_init_timer`) | **`0x800` = CHIPCOMMON core-id**, hard-coded `mov.w r1, #0x800` at 0x63CDE | `0xB05` (Thumb fn @ `0xB04`) | **fn@0xB04** — 12-byte thunk: loads sched_ctx from `*0x6296C` and state ptr from `*0x62994`, tail-calls `fn@0xABC`. Likely an RTE timer/watchdog/PMU handler bound to chipcommon class. | **LIKELY YES** — runs as part of core RTE init, well before any wlc/dngl path; not yet observed at runtime |
| `0x67774` | inside FullMAC `wl_attach` (str refs include the banner `'6.30.223 (TOB) (r)'`, `'wl%d: Broadcom BCM%04x 802.11 ...'`, `'wl%d: wlc_attach failed'`, `'wl%d: bcm_rpc_attach failed'`) | caller-supplied (per row 161 / T289 §1.1, presumably `0x812 = core[2] = D11`) | `0x1146D` (Thumb fn @ `0x1146C`) | **`wlc_isr`** (per T290a's hard-coded expected fn-ptr; FullMAC chain) | **NO** — T299–T306 ruled the FullMAC `wl_attach` chain dead under offload mode. Empirically T290a found garbage at the expected node address. |

## What this lets us discriminate (the bit of information)

A dynamic BAR2 walk of `TCM[0x629A4]` → ... should produce one of three
outcomes, each with a distinct interpretation:

| Walk result | Interpretation | Confidence in row 161 |
|---|---|---|
| 1 node (pciedngl_isr only) | RTE core-init `hndrte_add_isr(class=0x800, fn@0xB04)` did NOT execute, OR registered but immediately unregistered. RTE init didn't reach the timer/PMU helper. **Implications for the wake hypothesis weaken** — the "chipcommon-class ISR exists" basis erodes. | row 161 strengthened in spirit; row 148 chipcommon-wrap candidate weakens |
| 2 nodes (pciedngl_isr + fn@0xB04, with class=0x800) | The live offload runtime DOES register a chipcommon-class ISR. Its `node[+0xC]` value reveals which OOB bit BIT_alloc allocated from chipcommon-wrap+0x100 — exactly the `test.288a` data, obtained via TCM. **Best outcome.** Tells us (a) the wrapper register IS being read by fw at init, (b) what slot it produced, (c) that the ISR is in the dispatch list waiting for events. | row 161 confirmed; row 148 chipcommon-wrap candidate IDENTIFIED with primary-source bit allocation |
| 3 nodes (incl. fn @ 0x1146C `wlc_isr`) | FullMAC `wl_attach` DID execute and registered wlc_isr. **Major reframe needed** — row 161's "FullMAC dead in offload" finding is wrong, or it's reachable via a path the static reach analysis missed. | row 161 falsified; revisit T299/T306 BFS |
| 0 nodes (`TCM[0x629A4] = 0`) | List head is empty; either fw never reached `pcidongle_probe` or list was wiped. Deepest concern — would falsify T256's snapshot too. Probably substrate-noise-related. | inconclusive |
| 4+ nodes | Unknown additional ISRs registered beyond what static analysis found via direct `bl` (could be indirect-call or fn-ptr-from-table registration). Worth investigating. | row 161 mixed; need to identify the additional fns |

## The pending-events word — additional BAR2-readable signal

Per T269 §2, the RTE scheduler at fn@0x115C reads pending events via the
3-instruction leaf `fn@0x9936`:
`r3 = [sched+0x358]; r0 = [r3+0x100]; bx lr`. So the pending bitmap is at
`*(sched_ctx+0x358)+0x100`. Reading it is a 3-deref TCM walk:

1. `sched_ctx_ptr = TCM_read(0x6296C)` — known at runtime to be `0x62A98`
2. `events_struct_ptr = TCM_read(sched_ctx_ptr + 0x358)`
3. `pending = TCM_read(events_struct_ptr + 0x100)`

This is the software shadow of HW IRQ activity (set by the IRQ entry
path, cleared by the scheduler after dispatch). If fw is in WFI with no
HW events, expected value = 0. **If non-zero** at any stage, that tells
us which OOB bit fired but never got serviced — direct evidence of a
wake delivered to fw.

`AND`ing the pending-events word with each ISR node's `+0xC` mask tells
us which ISR each pending bit dispatches to. That's the
`bit-index → callback` map the wake hypothesis needs.

## Concrete probe spec (test.298)

**Read-only, BAR2-only.** Uses only `brcmf_pcie_read_ram32` which is
`ioread32(devinfo->tcm + ci->rambase + offset)` — direct ioread on BAR2,
no `BAR0_WINDOW` write, no `select_core`, no chipcommon/PCIE2/wrapper
register touch (verified at pcie.c:1875).

```
For stage in {post-set_active, post-T276-poll, t+5s, t+30s, t+90s}:
    sched_ctx_ptr = read32(0x6296C)
    head = read32(0x629A4)
    For i in 0..15 while head != 0:
        if not (0 <= head < 0xA0000): break  (defensive)
        next, fn, arg, mask = read32(head), read32(head+4),
                              read32(head+8), read32(head+0xC)
        emit pr_emerg with i, head, next, fn, arg, mask
        head = next
    sched_cc = read32(sched_ctx_ptr + 0xCC)  (current class, defensive bounds)
    events_p = read32(sched_ctx_ptr + 0x358)
    pending  = read32(events_p + 0x100) if 0 <= events_p < 0xA0000 else 0
    emit summary: stage, i, sched_cc, pending
```

Total reads per stage: ≤ 4 + (16 × 4) = 68 BAR2 ioread32s. Total memory
footprint per dump: small, fits in a few `pr_emerg` lines per stage.

## Decoder table (for log interpretation)

When the dump arrives, the `node[+4] = fn` value decodes to:

| node[+4] | ISR | Notes |
|---|---|---|
| `0x00001C99` | `pciedngl_isr` (Thumb @ 0x1C98) | always present per T256 |
| `0x00000B05` | `fn@0xB04` thunk | RTE chipcommon-class handler; thin wrapper around fn@0xABC |
| `0x0001146D` | `wlc_isr` (Thumb @ 0x1146C) | FullMAC; if present, T299–T306 reframe needed |
| anything else | unknown | follow-up: blob disasm at `(value & ~1)` |

`node[+0xC]` is `1 << bit_index`. Decode by `__builtin_ctz` or `log2`.
For the chipcommon-class ISR (fn@0xB04 with class=0x800), the bit index
is the slot BIT_alloc found in `oobselouta30` (chipcommon-wrap+0x100).

## What this enables / blocks

**Enables:**
- Direct primary-source confirmation/falsification of row 161 (live
  offload runtime ≠ FullMAC chain) at the ISR-registration level, not
  just via the static reach heuristic.
- Direct primary-source measurement of which OOB bit was allocated
  out of `oobselouta30` for the chipcommon-class ISR — equivalent to
  `test.288a`'s targeted read but obtained via TCM.
- Pending-events-word observation gives a primary signal for any
  HW interrupt that fires while fw is in WFI.

**Does NOT bypass:**
- The substrate noise belt (KEY_FINDINGS row 85). Test.298 still has to
  insmod through the Phase 5 init path; the 4-null streak's wedge points
  (test.158/188/193/225) are upstream of every probe regardless of
  BAR0 / BAR2 distinction. Budget multiple cold cycles per attempt.
- The need for fresh substrate within ≤2 min of cold-cycle boot per
  prior cluster observations.

## Hardware-fire gate (per t297_next_steps.md §"Hardware Fire Gate")

When test.298 is built and PRE-TEST.298 is written, the plan must
explicitly include:

- Citation to KEY_FINDINGS row 85 (this remains in force after T297).
- Statement that test.298 does NOT touch BAR0:
  - does not write `BAR0_WINDOW`
  - does not call `brcmf_pcie_select_core`
  - does not read chipcommon, PCIE2, or wrapper MMIO
  - uses only `brcmf_pcie_read_ram32` (verified BAR2-direct at pcie.c:1875)
- Acknowledgement that BAR2-only does NOT bypass the upstream noise belt.

## Clean-room posture

All disasm fragments above are short, illustrative, and presented in
plain language. No reconstructed function bodies committed. Behaviour
described from disassembled mnemonics + literal-pool reads + ASCII
string cross-references. Probe code reads only TCM via the existing
`brcmf_pcie_read_ram32` helper.
