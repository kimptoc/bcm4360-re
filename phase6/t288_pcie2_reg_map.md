# T288 — PCIE2+0x100 register map + scheduler-ctx core-enumeration

**Date:** 2026-04-24 (post-T287b, all static — no hardware fires)
**Goal:** After T287b falsified T283's chipcommon inference for `sched_ctx+0x258`, locate the actual writer of `+0x258 = 0x18100000` (PCIE2 base) and identify PCIE2+0x100 register semantics.
**Scripts:** `phase6/t288_fn670d8_trace.py`, `phase6/t288_find_258_writers.py`, `phase6/t288_fn64590.py`, `phase6/t288_verify_slot.py`.

## Summary (short version)

| Question | Answer |
|---|---|
| Does fn@0x672e4 write sched_ctx+0x258? | No. It calls fn@0x670d8 with chipcommon as r3; no direct stores to +0x258 in its body. |
| Does fn@0x670d8 write sched_ctx+0x258? | No. It stores +0x10=0x11 and +0x88=chipcommon (matches T287b), but no +0x258. It calls fn@0x64590 (core enumerator). |
| What is fn@0x670d8? | **`si_doattach`** — Broadcom SiliconInfo attach. Confirmed by string literals: `'siutils.c'` at 0x470ec, `'si_doattach'` at 0x474cf. |
| What is fn@0x64590? | **The core enumerator** (si_scan-equivalent). Iterates cores discovered via chipcommon EROM; for each slot stores multiple fields at stride-4 slot-indexed offsets. |
| Is 0x18100000 (PCIE2 base) a literal anywhere? | **No.** 0 literal-pool hits in fw blob. The value is runtime-discovered during EROM walk. |
| Is 0x83c (BCMA_CORE_PCIE2 core-id) a literal? | **No.** 0 hits anywhere. Either BCM4360 uses a different PCIE2 core-id, or the enumerator doesn't match by 0x83c symbolically. |
| Is slot=17 = PCIE2 proven? | **LIVE.** Offset arithmetic (`slot*4 + 0x214 = 0x258` → slot=17) is necessary but not sufficient; no independent core-id verification yet. |

## fn@0x670d8 = si_doattach (CONFIRMED)

Evidence (primary-source):
- 0x670f6: `ldr r0, [pc, #0x1bc] lit@0x672b4 = 'siutils.c'`
- 0x67124: `ldr r1, [pc, #0x194] lit@0x672bc = 'si_doattach'`
- 0x67108: `bl #0x91c` with args (r0=sched_ctx, r1=0, r2=0x35c) — zeroes 0x35c bytes of ctx (matches si_info_t size in Broadcom source)
- 0x67110: `str r3, [r4, #0x10]` where r3=0x11 — matches T287b `+0x10 = 0x00000011` EXACTLY
- 0x67112: `str.w r6, [r4, #0x88]` where r6=chipcommon — matches T287b `+0x88 = 0x18000000` EXACTLY
- 0x6715a..0x67182: reads chipc[0]=chipid and extracts type/rev/caps into sched+0x3c/+0x40/+0x44 — classic si_doattach pattern
- 0x67190: `bl #0x64590` with args (sched_ctx, chipcommon, arg2) — calls core enumerator
- 0x67194: `ldr r3, [r4, #0xd0]; cbnz r3, ...` — expects enumerator to set sched+0xd0 (core count)

## fn@0x64590 = core enumerator (CONFIRMED mechanism)

### Per-slot store pattern

For each core discovered in the EROM walk, the enumerator stores multiple fields at slot-indexed offsets. The slot index `r5` is loaded from `[sched+0xd0]` (the running core-count counter).

Fixed-offset-with-slot stores (from fn@0x64590 body):
```
0x64644  str.w r3, [r4, #0x358]                   ; one-time store (not slot-indexed)
0x6467c  str.w r0, [r3, #0xd4]   where r3=sched+slot*4  ; core-id at per-slot +0xd4
0x64720  str.w r2, [r3, #0x114]  where r3=sched+slot*4  ; per-slot +0x114
0x64726  str.w r2, [r3, #0x1d4]  where r3=sched+slot*4  ; per-slot +0x1d4
0x64764  str.w r1, [r2, #0x194]  where r2=sched+slot*4  ; per-slot +0x194
0x64768  str.w r3, [r2, #0x214]  where r2=sched+slot*4  ; per-slot +0x214 ← PCIE2 base for slot 17
```

### Per-slot core-id table confirmed

fn@0x9968 does a linear search:
```
0x996a  ldr.w r5, [r0, #0xd0]    ; r5 = core count
0x9976  ldr.w r6, [r4, #0xd4]    ; r6 = [sched + idx*4 + 0xd4]
0x997a  cmp r6, r1                ; match arg1 (core-id to find)
0x998c  movs r0, #0x11            ; not found → return 0x11
```

**Two things proven:**
1. `[sched + slot*4 + 0xd4]` is the per-slot core-id array.
2. The "not found" sentinel `0x11` matches sched_ctx's `+0x10 = 0x11` reading — same constant used throughout.

## Class-0 thunk arithmetic (T283 verified in full)

At 0x284c: `add.w r3, r5, #0x96` where r5=class arg.
At 0x287c: `ldr.w r3, [r4, r3, lsl #2]` = `[sched + (class+0x96)*4]`.
At 0x2880: `str.w r3, [r4, #0x254]`.

**For class=0:** reads `[sched + 0x258]`, stores at `sched+0x254`. T283 fully confirmed.

BIT_alloc (fn@0x9940 → 0x2890) then: `ldr.w r3, [r0, #0x254]; ldr.w r0, [r3, #0x100]; and r0, r0, #0x1f`. Reading at `[sched+0x258]+0x100` = `PCIE2_base+0x100`, returning bits 0-4.

## Remaining uncertainty — slot=17 claim

The arithmetic is: `slot*4 + 0x214 = 0x258` → slot = 17.

**Not yet verified independently:**
- No literal `0x83c` (BCMA_CORE_PCIE2 core-id) anywhere in the blob. Either BCM4360 uses a different PCIE2 core-id OR the enumerator's EROM walk doesn't compare by symbolic constant (uses a table/registry instead).
- No two-point verification yet. T287b only read +0x258; it didn't read per-slot fields for slot 0 (chipcommon, whose `+0xd4` would be at `sched+0*4+0xd4 = sched+0xd4` = 0x800).

**How to verify next:**
- Option A — next fire reads `[sched+0xd4]`, `[sched+0xd4+17*4]`, `[sched+0xd4+slot*4]` for all slots. Would prove slot 17's core-id and identify neighbour cores.
- Option B — static trace of fn@0x64590's EROM walk (fn@0x2704 and fn@0x2728 look like EROM read primitives) to see how core-ids are compared.
- Option C — cross-check against upstream brcmfmac's chip.c which has the BCM4360 core table.

## PCIE2+0x100 register semantics (still LIVE)

We now know:
- The register IS on the PCIE2 core (not chipcommon) at byte offset 0x100.
- Upstream bcma_driver_pcie2.h names `0x100` as `BCMA_CORE_PCIE2_RC_AXI_CONFIG` — **but that is the ROOT-COMPLEX-side view.** BCM4360 fw is on the ENDPOINT side; EP-side 0x100 is a separate, undocumented register.
- BIT_alloc reads 5 bits (`and r0, #0x1f`) or 5 bits shifted-right-by-8 (fn@0x9944). This matches an "interrupt pending bits" semantic.
- Calling convention: BIT_alloc scans these bits to find a free interrupt/event slot to allocate to a new callback.

**Inference (not proof):** PCIE2 EP-side + 0x100 is likely a scheduler/interrupt status register used by fw's RTE scheduler to track which interrupt bits are free for allocation. Without a datasheet or dsdt/driver source on the EP-side PCIE2 core, we can't name it.

## Next steps (deferred — no more fires today)

1. **Verify slot=17 = PCIE2** (one of Options A/B/C above).
2. **Design T288a — read-only probe of PCIE2 core offsets {0x100, 0x104, 0x108, 0x168}** at each T278 stage. Macro pattern = T285 but with `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)` before reads.
3. **Design T288b — extend T287 to dump the full per-slot table** (`[sched+0xd4+i*4]` for i=0..15) to identify what each slot holds. Gives us the complete core layout in one fire.
