# T300 step 1 — static prep for BAR2-only sched_ctx / OOB-mapping probe

Date: 2026-04-27 evening (post-T299)

Per `t299_next_steps.md` §1: targeted static pass over the live offload
runtime to answer whether the OOB-router pending-event state has any
TCM-resident shadow we could read via BAR2 only.

## Conclusion (3 lines)

- **No TCM-resident shadow of the OOB Router pending-events bitmap exists.**
  Firmware reads `0x18109100` live from hardware via `fn@0x9936` (3-insn
  leaf: load `[sched_ctx+0x358]`, load `[+0x100]`, return). Static analysis
  found zero writers of this register into TCM.
- **The ISR-list at `TCM[0x629A4]` is the only OOB-bit → callback mapping
  cached in TCM** — and T298/T299 already enumerated it (2 nodes, masks
  0x8 and 0x1). No alternate dispatch table found.
- **Per directive doc §3, next step is A3** (one-shot OOB Router pending
  read at `0x18109100` via BAR0_WINDOW = 0x18109000), since BAR2 cannot
  expose pending-events state. Optional add-on: a BAR2 sweep of the
  per-slot core-ID table at `sched_ctx + 0xd0..` for cross-validation
  against host-side enumeration — but that does NOT advance the wake
  question, only adds redundancy.

## Per-question findings

### Q1: Writer of `sched_ctx + 0x358` (the events_p)

Firmware appears to write `0x18109000` (ARM OOB Router MMIO base) into
`sched_ctx+0x358` at offset `0x64644` within `fn@0x64590` (the EROM core
enumerator), per `phase6/t288_pcie2_reg_map.md` line 85:

```
0x64644: str.w r3, [r4, #0x358]   ; one-time, not slot-indexed
```

This is a single MMIO-address store of the OOB Router agent's hardware
backplane address — NOT a cached pending-bitmap shadow. The value is
read-only at runtime by the scheduler poll leaf:

```
fn@0x9936:  ldr r3, [sched_ctx, #0x358]
            ldr r0, [r3, #0x100]
            bx  lr
```

`fn@0x9936` returns the **live hardware value** of the OOB Router pending-
events register. There is no software cache between hardware and dispatch.

Cross-cited: `phase6/t274_events_investigation.md` confirmed zero writers
of the pending-events register itself.

### Q2: `sched_ctx + 0x2c0..0x35c` sweep

Catalogue of what is statically known:

| Offset | Content | Source | Status |
|---|---|---|---|
| `+0xcc` | 0x1 stable (semantics unknown — NOT class-ID 0x800/0x812 as predicted) | T298 t+90s primary-source | unknown — open |
| `+0xd0` | core count (slot counter) | t288_pcie2_reg_map.md §fn@0x67194 reader | NEW — not yet runtime-probed |
| `+0xd4 + slot*4` | per-slot core-ID table (e.g. slot 0 → 0x800 chipcommon, slot 1 → 0x812 D11, ...) | t288 §fn@0x9968 lookup; fn@0x64590 at 0x6467c writer | NEW — not yet runtime-probed |
| `+0x114, +0x194, +0x1d4, +0x214, +0x2d8, +0x318` (each + slot*4) | per-slot capability fields written by enumerator | t288_pcie2_reg_map.md §Per-slot stores | NEW — not runtime-probed |
| `+0x254, +0x258` | chipcommon-wrap base 0x18100000; class-indexed wrapper-base table starts here | T287c post-set_active | observed |
| `+0x25c..+0x270` (stride 4) | per-class wrapper bases (core[2]=0x18101000, core[3]=0x18102000, core[4]=0x18103000, core[5]=0x18104000, core[6]=0) | T287c post-set_active | observed |
| `+0x300..+0x35c` (12 dwords) | uncharacterized — no static writers found in enumerator loop | gap analysis | likely padding/reserved |
| `+0x358` | 0x18109000 (OOB Router MMIO base) | T298 + t288 §0x64644 writer | observed |

The `+0x300..+0x35c` gap is most consistent with structure padding in
the `si_t` definition. No reads or writes from any function reached by
the live BFS were found targeting that range.

### Q3: ISR-list handling around `TCM[0x629A4]`

`TCM[0x629A4]` is the head pointer for the singly-linked ISR list.

- **Allocator:** `hndrte_add_isr` (fn@0x63C24, per T289 §2) malloc's
  16-byte nodes, stores `next/fn/arg/mask` at `+0x0/+0x4/+0x8/+0xC`,
  prepends to head.
- **Dispatcher (live runtime):** RTE scheduler at `fn@0x115C` calls
  `fn@0x9936` to obtain pending-events word, then walks the list
  matching `pending & node[+0xC]` to identify which callback to run,
  dispatches via `bx r3`.
- **TCM-resident reads possible without BAR0:** confirmed by T298 and
  T299 — full 2-node walk via `brcmf_pcie_read_ram32` from BAR2 only.

No alternate dispatch table found. The list IS the dispatcher's
data structure.

### Q4: Class/core/slot table

Three indexed tables exist in `sched_ctx`:

1. **Per-slot core-ID table** at `+0xd4 + slot*4` (count at `+0xd0`).
   Maps slot index → BCMA core ID. **Not yet observed at runtime;**
   cross-validates against host-side `lspci` and `test.218` enumeration.
2. **Per-class wrapper-base table** at `+0x254 + (class+0x96)*4`.
   Maps class → wrapper MMIO base. Observed stable from T287c onwards.
3. **Per-slot capability tables** at the offsets enumerated in Q2.
   Populated by enumerator, not yet runtime-probed.

**No OOB-bit → callback cache.** OOB bit allocations are **per-class**
(each class owns its 5-bit `oobselouta30` selector + bit pool) and the
allocation result is stored ONLY at the ISR-node `+0xC` mask. There
is no top-level summary table ("class K was allocated bits B0, B1, ...").
The ISR-list walk IS the only lookup path.

### Q5: Stopping rule

The static pass terminates with: **mapping for OOB pending-events
state was NOT found in TCM.** Per `t299_next_steps.md` §3 → next step is
A3.

The pass also identified one **secondary** TCM-readable target with
non-pending-events value: the per-slot core-ID table at `sched_ctx +
0xd0..0x114` (count + 16 entries × 4 bytes ≤ 0x44 bytes). This would
**not** advance the wake question, but it would **cross-validate**
firmware's view of the backplane against host-side enumeration. Decide
whether to combine that with the A3 PRE-TEST or skip it.

## Concrete recommendation

**Primary: proceed to A3** — single-purpose BAR0 OOB Router pending
read at `0x18109100` via `BAR0_WINDOW = 0x18109000`. Must satisfy the
Hardware Fire Gate from `t299_next_steps.md`:

- explicitly cite KEY_FINDINGS row 85
- justify why OOB Router (BCMA core 0x367) is a distinct backplane
  agent from the chipcommon (0x18100000) / PCIE2 (0x18103000)
  wrapper surfaces that wedged in T297
- exit before the [t+90s, t+120s] wedge bracket (early-exit at
  t+60s recommended)
- state the single bit of information: is `OOB Router + 0x100`
  non-zero at any sample point post-set_active? Non-zero would
  identify which OOB bits have been asserted by hardware events;
  zero across all sample points would tighten the "fw genuinely
  in WFI with no event delivery" reading.

**Optional add-on: per-slot core-ID table BAR2 read** at
`sched_ctx + 0xd0..0x114`. Adds cross-validation but no new
information toward the wake question. Decision should be made
explicitly when drafting the A3 PRE-TEST — likely defer to keep
the fire single-variable.

## Open static questions (low priority)

1. What populates `sched_ctx + 0x300..+0x35c`? (12 dwords currently
   unaccounted for — likely padding)
2. What writes `sched_ctx + 0xcc`? (Observed 0x1 stable across all
   T298 stages but semantics unknown; not live class-ID per
   KEY_FINDINGS row 137)
3. Verify per-slot core-ID table at runtime against host-side
   `test.218` enumeration (relegated to optional add-on above)

These do not block A3 and do not require further work before the
next hardware fire.

## Files cited

- `t299_next_steps.md` §1 (task statement)
- `KEY_FINDINGS.md` rows 85, 104, 137, 138, 148, 152, 161, 163
- `RESUME_NOTES.md` current-state block (post-T299)
- `phase6/t298_static_pass_findings.md` (ISR-list mechanism)
- `phase6/t299_t306_offload_runtime.md` (live vs dead-code)
- `phase6/t288_pcie2_reg_map.md` (enumerator + sched_ctx layout, the
  primary source for offset ownership)
- `phase6/t274_events_investigation.md` (zero writers of pending-
  events register found)
- `phase5/logs/test.298.journalctl.txt` (primary-source ISR-list)
- `phase5/logs/test.299.journalctl.txt` (T298 reproduction under
  ASPM-disabled state)
