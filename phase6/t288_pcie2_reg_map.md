# T288 — Scheduler core-enumeration trace + BIT_alloc register identity

**Date:** 2026-04-24 (post-T287b, all static — no hardware fires)
**Goal:** Locate the actual writer of `sched_ctx+0x258 = 0x18100000` after T287b runtime data. Identify register at that offset + 0x100 where BIT_alloc reads.
**Scripts:** `phase6/t288_fn670d8_trace.py`, `phase6/t288_find_258_writers.py`, `phase6/t288_fn64590.py`, `phase6/t288_verify_slot.py`.

---

## ⚠️ CORRECTION (2026-04-24 evening)

**An earlier draft of this document concluded `0x18100000` was PCIE2 core base.
That was wrong. It is CHIPCOMMON WRAPPER base.**

The host-side brcmfmac-patched enumerator (test.218 in chip.c) has been
logging the full core table for this chip all along. Primary-source table
from `phase5/logs/test.287b.journalctl.txt`:

| core | id | rev | base | wrap |
|---|---|---|---|---|
| 1 | 0x800 | 43 | 0x18000000 | **0x18100000** ← |
| 2 | 0x812 | 42 | 0x18001000 | 0x18101000 |
| 3 | 0x83e | 2 | 0x18002000 | 0x18102000 | ARM-CR4
| 4 | **0x83c** | 1 | **0x18003000** | 0x18103000 | PCIE2 (real)
| 5 | 0x81a | 17 | 0x18004000 | 0x18104000 |
| 6 | 0x135 | 0 | 0x00000000 | 0x18108000 |

- chipcommon (core[1]) has base=0x18000000 and wrap=**0x18100000**.
- PCIE2 (core[4]) has base=0x18003000, NOT 0x18100000.
- The 0x18100xxx range is the chipcommon WRAPPER, part of a contiguous
  0x181xxxxx wrap region (one page per core, stride 0x1000).
- Fw blob grep had zero hits for 0x18100000 as a literal because wraps
  are computed (base + 0x100000) or passed via register values, not
  stored in literal pools.

**What this means for BIT_alloc:**
- fn@0x9940/9944 (→ 0x2890/0x289e) reads `[sched+0x254]+0x100` = `chipcommon_wrapper+0x100` = **0x18100100**
- NOT PCIE2+0x100, NOT chipcommon register-base+0x100 (which is what T285 probed)
- The 5-bit `and #0x1f` result likely reflects OOB (out-of-band) interrupt-line routing bits in the AI/AXI backplane wrapper. This is speculative register-name inference; only the address and mask-width are primary-source.

**What still holds from the original T288 work:**
- fn@0x670d8 = si_doattach (confirmed)
- fn@0x64590 = core enumerator with slot-indexed stride-4 stores (confirmed mechanism)
- `[sched+slot*4+0xd4]` = per-slot core-id array (confirmed by fn@0x9968 lookup)
- Class-0 thunk at 0x27ec/0x287c does `[sched+(class+0x96)*4] → sched+0x254` (T283 arithmetic verified)
- The "0x11 not-found sentinel" from fn@0x9968 matches T287b's runtime `sched+0x10 = 0x11` reading

**What's withdrawn:**
- "slot=17 = PCIE2" arithmetic — coincidental match, not real. PCIE2 is core[4], not slot 17. The mapping `slot*4 + 0x214 = 0x258` does NOT correspond to how `sched+0x258` actually gets populated.
- "writer of sched+0x258 is enumerator's slot-indexed store" — needs revisit. `sched+0x258` likely gets chipcommon wrapper base via a different path (possibly `si_doattach` itself, possibly a per-agent thunk setup we haven't found yet).
- "PCIE2+0x100 register identity" analysis (bcma RC_AXI_CONFIG discussion) — irrelevant; target isn't PCIE2 at all.

Open task: find the actual writer of sched+0x258 = chipcommon_wrapper_base. Candidates:
- Stored by fn@0x64590 when it enumerates the chipcommon core (core[1])
- Stored by si_doattach via a call chain after chipcommon discovery
- Computed on-the-fly from chipcommon-base (+0x100000)

---

## Remainder of this doc (still valid structural analysis)

### fn@0x670d8 = si_doattach (CONFIRMED)

Evidence (primary-source):
- 0x670f6: `ldr r0, [pc, #0x1bc] lit@0x672b4 = 'siutils.c'`
- 0x67124: `ldr r1, [pc, #0x194] lit@0x672bc = 'si_doattach'`
- 0x67108: `bl #0x91c` with args (r0=sched_ctx, r1=0, r2=0x35c) — zeroes 0x35c bytes of ctx (matches si_info_t size in Broadcom source)
- 0x67110: `str r3, [r4, #0x10]` where r3=0x11 — matches T287b `+0x10 = 0x00000011` EXACTLY
- 0x67112: `str.w r6, [r4, #0x88]` where r6=chipcommon — matches T287b `+0x88 = 0x18000000` EXACTLY
- 0x6715a..0x67182: reads chipc[0]=chipid and extracts type/rev/caps into sched+0x3c/+0x40/+0x44 — classic si_doattach pattern
- 0x67190: `bl #0x64590` with args (sched_ctx, chipcommon, arg2) — calls core enumerator
- 0x67194: `ldr r3, [r4, #0xd0]; cbnz r3, ...` — expects enumerator to set sched+0xd0 (core count)

### fn@0x64590 = core enumerator (CONFIRMED mechanism)

Per-slot stores:
```
0x6467c  str.w r0, [r3, #0xd4]   where r3=sched+slot*4   ; core-id at per-slot +0xd4
0x64720  str.w r2, [r3, #0x114]  where r3=sched+slot*4   ; per-slot +0x114
0x64726  str.w r2, [r3, #0x1d4]  where r3=sched+slot*4   ; per-slot +0x1d4
0x64764  str.w r1, [r2, #0x194]  where r2=sched+slot*4   ; per-slot +0x194
0x64768  str.w r3, [r2, #0x214]  where r2=sched+slot*4   ; per-slot +0x214
```
Fixed-offset stores:
```
0x64644  str.w r3, [r4, #0x358]    ; one-time (not slot-indexed)
```
Indexed addressing (separate region):
```
0x64664  str.w r7, [r4, r3, lsl #2] where r3 = slot + 0xb6   ; writes at byte offset 0x2d8 + slot*4
0x6466e  str.w r0, [r4, r3, lsl #2] where r3 = slot + 0xc6   ; writes at byte offset 0x318 + slot*4
```

### Per-slot core-id array confirmed by fn@0x9968

```
0x996a  ldr.w r5, [r0, #0xd0]    ; r5 = core count
0x9976  ldr.w r6, [r4, #0xd4]    ; r6 = [sched + idx*4 + 0xd4]
0x997a  cmp r6, r1                ; match core-id arg?
0x998c  movs r0, #0x11            ; not found → return 0x11 (same as sched+0x10)
```

### Class-0 thunk arithmetic (T283 verified)

At 0x284c: `add.w r3, r5, #0x96` where r5=class arg.
At 0x287c: `ldr.w r3, [r4, r3, lsl #2]` = `[sched + (class+0x96)*4]`.
At 0x2880: `str.w r3, [r4, #0x254]`.

For class=0: reads `[sched+0x258]`, stores at `sched+0x254`.
BIT_alloc (fn@0x9940 → 0x2890) then: `ldr.w r3, [r0, #0x254]; ldr.w r0, [r3, #0x100]; and r0, #0x1f`.
Reading at `[sched+0x258]+0x100` = `chipcommon_wrapper+0x100` = `0x18100100`, returning bits 0-4.

### Next steps (post-correction)

1. **Find writer of sched+0x258 = chipcommon wrapper base.** Not the enumerator's slot-indexed stores; likely a separate setup path. Candidates: deeper body of fn@0x64590 not yet disasmed; `fn@0x66fc4` (called with (sched, chipcommon, slot, slot, ...) at 0x671b0 — per-core setup?); `fn@0x6458c` (called at 0x64674).
2. **T288a redesign** — read-only probe of **chipcommon WRAPPER** at offsets {0x100, 0x104, 0x108, 0x168} at each T278 stage. Requires a core-select path that lands in the wrap region, not the register base. brcmfmac's `brcmf_pcie_select_core(BCMA_CORE_CHIPCOMMON)` selects the register base; the wrapper needs a different BAR0_WINDOW value (likely `0x18100000`).
3. **T288b — per-slot dump** extending T287 to read `[sched+0xd0]` (core count), `[sched+0xd4+i*4]` for i=0..15 (core-ids), `[sched+0x114+i*4]` and `[sched+0x214+i*4]`. Cross-validates host-side test.218 enumeration from the fw's own sched_ctx data structure.
4. **Identify chipcommon-wrapper+0x100 register.** Candidates: AI backplane wrapper OOB input status (5-bit mask matches); alternative names in Broadcom AI backplane wrapper spec if accessible.
