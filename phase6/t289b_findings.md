# T289b — wlc_callback_ctx trace + chipcommon-wake hypothesis verification

**Date:** 2026-04-26 (post-T289)
**Scripts:** `phase6/t289b_*.py`
**Goal (per advisor reconcile after T289):** verify whether the inferred wake source `chipcommon+0x168` actually holds, by tracing `wlc_callback_ctx` from its allocation in `wl_probe` and resolving what `[wlc_callback_ctx+0x10][+0x88]` actually points to.

## TL;DR — the chipcommon-wake hypothesis WEAKENED

The inference rested on assuming that `[flag_struct+0x88]` = chipcommon REG base, by analogy to `sched_ctx+0x88` = chipcommon (T287b runtime). T289b shows that **the +0x88 offset has different semantics in different structs**:

- `sched_ctx+0x88` = chipcommon REG base (T287b runtime; written by `si_doattach` at fn@0x67112)
- `STRUCT_A+0x88` = wlc_callback_ctx (back-pointer; written by fn@0x649a4 at 0x64a14, where STRUCT_A is alloc'd from a 0xAC-byte buffer with arg2 stored to [+0x88])
- `(unknown struct)+0x88` ← per-class register-base table value (written by fn@0x6820c at 0x682d8, where the value is `sched[class*4+0x114]` returned by si_setcoreidx wrapper)

Three different conventions for the same offset, in three different structs. The "+0x88 = chipcommon" pattern doesn't transfer across struct types.

**Net**: KEY_FINDINGS row for "wake source candidate chipcommon-internal" stays LIVE but should NOT be relied upon for design decisions. The actual struct that fn@0x2309c reads via `[dispatch_ctx+0x10][+0x88]` may have a totally different +0x88 semantics — possibly PCIE2 base, possibly TCM, possibly something else.

## 1. The wlc_callback_ctx chain (verified)

Forward direction (from the registration site):

- `wl_probe` (fn@0x67614) is called via the function-pointer table at blob offset `0x58F1C` (the only literal of `0x67615` in the entire blob is at this address).
- Table layout (32 bytes from 0x58F1C):
  ```
  +0x00 (0x58F1C): wl_probe        (0x67615)
  +0x04 (0x58F20): fn@0x11649       (likely .start or .open)
  +0x08 (0x58F24): fn@0x1132D       (likely .stop or .close)
  +0x0C (0x58F28): fn@0x11605       (likely .ioctl)
  +0x10 (0x58F2C): 0
  +0x14 (0x58F30): fn@0x1158D
  +0x18 (0x58F34): fn@0x11525
  +0x1C (0x58F38): fn@0x1146D       (the WLC ISR itself)
  ```
  Pattern matches a typical Broadcom "wlc handlers" struct. The table is referenced once in the blob (from `0x58F00` which contains the value `0x58F1C` — likely the table-base pointer in some larger driver struct).
- `wl_probe` calls `hndrte_add_isr` at 0x67774 with:
  - `r0 = 0` (sb at this point)
  - `r1 = wl_probe's stack[0x48]` (caller-passed arg via stack)
  - `r2 = wl_probe's r5 = wl_probe's stack[0x4C]` (another caller-passed arg)
  - `r3 = fn@0x1146D` (the WLC ISR — passed directly via lit@0x678C4)
  - `sp[0] = r7` (where r7 = first arg of wl_probe)
  - `sp[4] = r8` (where r8 = third arg of wl_probe)
- Per `hndrte_add_isr` body (fn@0x63C24):
  - `node[4] = caller's r3` = fn@0x1146C (callback fn)
  - `node[8] = caller's sp+0` = `r7` of wl_probe (callback arg = wlc_callback_ctx)

Therefore: **wlc_callback_ctx = wl_probe's first argument**.

## 2. Forward dereference chain verified

Per disasm of fn@0x1146C, fn@0x23374, fn@0x2309C:

```
fn@0x1146C (the wlc ISR, called by scheduler with r0 = wlc_callback_ctx):
  ldr r4, [r0, #0x18]   ; r4 = wlc_callback_ctx[+0x18] = "wlc_pub"
  ldr r0, [r4, #8]      ; r0 = wlc_pub[+8] = "dispatch_ctx"
  bl fn@0x23374         ; flag-check(dispatch_ctx)
  cbz r0, .end
  ldrb [sp, #7]
  cbz, .end
  mov r0, r4            ; r0 = wlc_pub
  bl fn@0x113B4         ; ACTION(wlc_pub)
  pop ...

fn@0x23374 (called with r0 = dispatch_ctx):
  ldr r4, [r0, #0x10]   ; r4 = dispatch_ctx[+0x10] = "flag_struct"
  strb #0, [r1]
  ldrb [r4, #0xAC]      ; check flag_struct[+0xAC] (enabled?)
  cbz, .skip
  ldr [r4, #0x60]       ; check flag_struct[+0x60] (queue state?)
  cbz, .skip
  movs r1, #1
  bl fn@0x2309C         ; pending-events check (r0 = dispatch_ctx unchanged)
  ...

fn@0x2309C (pending-events check, r0 = dispatch_ctx):
  ldr r4, [r0, #0x10]    ; r4 = dispatch_ctx[+0x10] = "flag_struct" (same as above)
  ldr.w r5, [r4, #0x88]  ; r5 = flag_struct[+0x88] = ???  ← QUESTION
  ldr.w r6, [r5, #0x168] ; r6 = [r5+0x168] = pending events word
  ...
  W1C clears at [r5, #0x168] and [r5, #0x16C]
```

Four-level chain: `wlc_callback_ctx[+0x18][+8][+0x10][+0x88]` is the absolute base address of the pending-events register.

## 3. What flag_struct[+0x88] actually is — UNRESOLVED

Static evidence found by scanning all stores to [..., #0x88] in the blob (8 hits total, of which 3 are not previously identified):

| Site | Function | What gets stored to [+0x88] |
|---|---|---|
| 0x2850 | fn@0x27EC (class-0 thunk = si_setcoreidx) | per-class register base from `sched[class*4 + 0x8C]` |
| 0x2874 | fn@0x27EC (same fn, second store) | re-store of same per-class base (after assertions) |
| **0x67112** | **fn@0x670D8 (si_doattach)** | **r6 = chipcommon REG base 0x18000000** (passed in by caller fn@0x672E4) — this is the sched_ctx initialization |
| 0x64A14 | fn@0x649A4 | r5 = arg2 of fn = wlc_callback_ctx (back-pointer into 0xAC-byte alloc'd STRUCT_A) |
| 0x682D8 | fn@0x6820C | r0 = return of fn@0x9990 (class-validate wrapper → si_setcoreidx) = `sched[class*4 + 0x114]` |
| 0x6A070 | (fn TBD) | r3 = TBD |
| 0x7346 | (fn TBD) | strh.w (16-bit; different size — probably not the 32-bit base) |
| 0x1BB28 | (fn TBD) | strh.w to sp+0x88 (stack frame; irrelevant) |

**Three different semantics for the same offset across the blob**: per-class register base (sched_ctx convention), wlc_callback_ctx back-pointer (STRUCT_A in fn@0x649A4), per-class +0x114 field (fn@0x6820C). None of these is a "universal" rule; each is convention-dependent on the specific struct type.

The inference "flag_struct+0x88 = chipcommon by analogy to sched_ctx+0x88" was wrong: the analogy doesn't hold across struct types.

## 4. What this means

### 4.1 The "wake = chipcommon+0x168" hypothesis must be downgraded further

Previously LIVE (per T289 finding §3.1). Now structurally weaker:

- The address `flag_struct[+0x88]+0x168` is real and read at runtime; it IS the wake-gate address.
- But that address is **not statically determinable** from the disasm without identifying which specific struct flag_struct is, AND finding the writer that initializes its [+0x88].
- The "+0x88 = chipcommon" pattern from sched_ctx is sched-specific. flag_struct is a different struct (it has a +0xAC byte, +0x60 dword, +0x180 dword, etc. used as flag bytes — none of which match the sched_ctx layout per T288).

The wake-gate address could be any of:
- chipcommon+0x168 (still possible — fn@0x649A4's [+0x88] = wlc_callback_ctx, but not the relevant chain; need to find a different writer)
- PCIE2+0x168 (would map to some PCIE2 register — but fw blob has 0 PCIE2 literals per T289 §3, so unlikely)
- TCM+0x168 (a software-maintained word — would contradict T274's negative writer scan)
- Some other backplane core base + 0x168

### 4.2 The next zero-fire question

Identifying flag_struct's [+0x88] writer requires:
1. Finding the alloc site of flag_struct (look for stores to `[+0x10]` in fn@0x649A4-allocated STRUCT_A or in deeper-init code)
2. Finding the chain `STRUCT_A[+x] = ...` that eventually reaches flag_struct
3. Identifying flag_struct's allocation point (likely a si_attach-like helper that creates wlc internals)

This is deeper-trace work — pure static analysis but multiple levels deep. Each step is independent of the others, so it can be done incrementally.

### 4.3 What's known with high confidence (carried forward from T289)

These T289 CONFIRMED findings stand on their own; T289b doesn't affect them:

- The 9-thunk vector at 0x99AC is the AI/SI library API (CONFIRMED).
- hndrte_add_isr writes ZERO HW registers (CONFIRMED).
- Fw blob has only ONE chipcommon-base load instruction (well — actually TWO, see §5).

## 5. Correction to T289 §3 — chipcommon literal count

T289 §3 stated "the only backplane MMIO literal in the entire blob is `0x18000000` at file-offset 0x328 — single hit". That was a literal-pool scan. T289b found that fw also constructs `0x18000000` via Thumb-2 modified-immediate encoding — a `mov.w rN, #0x18000000` instruction not visible to literal-pool scanning. There are EXACTLY TWO such instructions in the entire blob:

- `0x67156`: `mov.w sb, #0x18000000` (in fn@0x670D8 = si_doattach — to read chipcommon[+0] = chipid for chip identification)
- `0x67306`: `mov.w r3, #0x18000000` (in fn@0x672E4 = scheduler ctx allocator — passed to si_doattach as the chipcommon base)

The literal at 0x328 may or may not be referenced by any code (initial scan found 0 PC-rel loaders within Thumb-2's ±4KB range; no MOVW/MOVT pair encoding either). Most likely it's an unused initialization-data word that happens to equal chipcommon base by coincidence (e.g. a reset-vector field or a struct initializer constant).

Net: fw constructs chipcommon base inline at exactly two code sites, both in si_doattach / its caller. Still only a chipcommon literal — no PCIE2 base anywhere — so T289 §3's structural conclusion (fw never targets PCIE2 MMIO) holds.

## 6. Status of the wake-source question

| Hypothesis | Status |
|---|---|
| Wake gate = PCIE2 MAILBOXMASK at BAR0+0x4C | RULED-OUT (T241/T280/T284/T289 §3) |
| Wake gate = some chipcommon register at +0x168 | LIVE but UNVERIFIED — depends on flag_struct[+0x88] resolving to chipcommon, which is unproven |
| Wake gate = some PCIE2 register at +0x168 | UNLIKELY — would require fw to know PCIE2 base, which it has no literal for |
| Wake gate = some other backplane core (ARM-CR4 / D11) at +0x168 | POSSIBLE — sched_ctx +0x88 was observed shifting to core[2]=0x18001000 at runtime (T287c); flag_struct[+0x88] could plausibly be set to a different core's base in a similar context-switch pattern |
| Wake gate = TCM (software-maintained word) | POSSIBLE if T274's negative writer scan missed an indirect-addressing pattern |

## 7. Clean-room posture

All findings are disassembled mnemonics + literal-pool analysis + offset-pattern matching. No reconstructed function bodies. Scripts in `phase6/t289b_*.py`. Zero hardware fires.
