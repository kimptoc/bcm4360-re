# T283 — Resolving fn@0x2309c's pending-events word + bit-alloc register

**Date:** 2026-04-24 (post-T284)
**Goal:** Find absolute address of fn@0x2309c's `[[ctx+0x10].[0x88]]+0x168` (pending-events word) and fn@0x9940/0x9944's `[ctx+0x254]+0x100` (bit-pool). Determine whether these are BAR0+0x4C (MAILBOXMASK, proved write-locked) or a different register.

Scripts: `phase6/t283_trace_pending_word.py`, `phase6/t283_class0_thunk.py`, `phase6/t283_scheduler_ctx_init.py`, `phase6/t283_ctx_allocator.py`, `phase6/t283_wlc_register_call.py`.

## Structural findings (high-confidence, primary-source)

### 1. Scheduler ctx is TCM-backed

- Scheduler ctx pointer at `*0x6296c` (TCM). Written by fw init at 0x63e00: `str r0, [r4]` where r4=0x6296c and r0=return of fn@0x672e4.
- fn@0x672e4 is the scheduler ctx allocator. It initializes a static struct anchored at `0x62a98` (TCM).
- **Crucial literal load at 0x67306**: `mov.w r3, #0x18000000` — CHIPCOMMON MMIO backplane base is pushed as an init arg (sp[8]) to the scheduler-init helper fn@0x670d8.

### 2. BIT_alloc reads CHIPCOMMON INTSTATUS

- fn@0x9940 → 0x2890: `ldr r3, [r0, #0x254]; ldr r0, [r3, #0x100]; and r0, r0, #0x1f`
- fn@0x9944 → 0x289e: same pattern, shifted right 8 (bits 8-12 instead of 0-4)
- r0 here is `scheduler_ctx`. `[scheduler_ctx+0x254]` is set by class-0 thunk at 0x2880 to `[scheduler_ctx+0x258]`.
- Given the 0x18000000 literal pushed through scheduler init, `[scheduler_ctx+0x258]` is the CHIPCOMMON MMIO base pointer. **Therefore `[scheduler_ctx+0x254]+0x100 = CHIPCOMMON_BASE + 0x100 = 0x18000100`.**
- Chipcommon register at offset 0x100 is `intstatus` per Broadcom convention — this is fw reading "which interrupt bits are claimed" for bit-allocation.

### 3. Class-0 thunk at 0x27ec — scheduler-side struct setup (NOT fn@0x2309c's chain)

Key lines:
```
0x2848  ldr.w r6, [r3, #0x8c]   ; r3 = scheduler_ctx + class*4 (class=0 → r3=scheduler_ctx)
0x2850  str.w r6, [r4, #0x88]   ; scheduler_ctx+0x88 = [scheduler_ctx+0x8c]
0x2878  str.w r5, [r4, #0xcc]   ; scheduler_ctx+0xcc = class index (=0 for pciedngl)
0x287c  ldr.w r3, [r4, r3, lsl #2]  ; r3 = [scheduler_ctx + (class+0x96)*4] for class=0: [scheduler_ctx+0x258]
0x2880  str.w r3, [r4, #0x254]  ; scheduler_ctx+0x254 = [scheduler_ctx+0x258]
```

The thunk's `scheduler_ctx+0x88` and `+0x254` are NOT directly the pending-events word. They're scheduler-owned per-class state that the bit-pool code uses.

### 4. fn@0x2309c's pending-events chain is on a DIFFERENT ctx

fn@0x2309c receives its `r0` through:
- fn@0x1146C's r0 = `new_struct[8]` (the callback ctx stored at hndrte_add_isr registration)
- fn@0x1146C: `r4 = [r0+0x18]; r0_new = [r4+8]`
- fn@0x23374: `r4 = [r0_new+0x10]` (flag_struct)
- fn@0x2309c: `r4 = [r0+0x10]; r5 = [r4+0x88]; r6 = [r5+0x168]` (pending-events)

**r0 in fn@0x2309c = a wlc-owned struct reached via `[wlc_callback_ctx+0x18]+8`.** This is NOT the scheduler_ctx. The `+0x10`, `+0x88` offsets in this chain are wlc's struct layout, not scheduler's.

### 5. wlc's callback-ctx = r7 from wlc-probe context

At 0x67774 (wlc-probe calls hndrte_add_isr):
```
0x6776e  str r7, [sp]        ; stack[0] in caller = sp[0x20] in callee = new_struct[8]
0x67770  str.w r8, [sp, #4]
0x67774  bl #0x63c24          ; hndrte_add_isr
```

- Caller's `sp[0]` becomes `sp[0x20]` of hndrte_add_isr (after its 8-reg push = 0x20 bytes), which hndrte_add_isr reads at `ldr r3, [sp, #0x20]` (0x63c92) and stores as `new_struct[8]` (0x63c96).
- Therefore **fn@0x1146C's callback_ctx = r7 in wlc-probe context**.
- r7's value is set earlier in wlc-probe (likely heap-allocated wlc_device struct). Without tracing wlc-probe's full setup, the absolute address isn't statically resolvable.

## Partial resolution — what we can conclude

### What we KNOW

- **Bit-pool register: `0x18000100` (CHIPCOMMON INTSTATUS)** — via `[scheduler_ctx+0x254]+0x100`. Absolute address confirmed statically.
- **`[scheduler_ctx+0x258]` = `0x18000000`** (CHIPCOMMON base, passed through fn@0x672e4's init).
- **The scheduler's "available interrupt bits" pool IS chipcommon INTSTATUS**, not BAR0+0x4C (MAILBOXMASK).

### What we CANNOT statically resolve (without deeper wlc tracing)

- The absolute address of `[sub+0x168]` (pending-events word for fn@0x1146C). Sub_struct is reached through wlc-owned struct fields, and the origin of these is in wlc-probe's setup code we haven't fully traced.
- Whether `[sub+0x168]` is also a chipcommon register (plausible: if `sub` points at `0x18000000 + something`, then `+0x168` would be chipcommon register at 0x18000168) OR a PCIE2 core register (if `sub` points at 0x18001000 or similar).

### Strong inference (not statically proven, but supported)

**Hypothesis: the pending-events word is ALSO a chipcommon register at `0x18000168`** (or similar near-chipcommon offset). Reasoning:
1. BIT_alloc uses chipcommon `0x18000100`. The same scheduler's dispatch would logically use a nearby chipcommon register for pending/clear.
2. T274 searched for writers of the pending-events word in fw code and found none — consistent with MMIO (HW-maintained).
3. T284 showed 0x318 at pre-set_active — bits 3+4 could match chipcommon intstatus bits 3+4 (backplane mailbox, clock, etc.) rather than PCIE2 MAILBOXINT bits 3+4 (which aren't defined in upstream).

### What this means for MBM / mask-open investigation

The "mask" in fn@0x1146C's dispatch is **scheduler-side software flag mask** (`[node+0xc] & pending_events`), not the HW MAILBOXMASK at BAR0+0x4C. Therefore:

- **Writing BAR0+0x4C (MAILBOXMASK) was never going to wake fn@0x1146C** — that's the PCIE2 MAILBOXINT mask, which only gates whether fw's ARM gets an IRQ from PCIE2. If fw's scheduler polls chipcommon INTSTATUS directly in its idle loop (WFI-wake on any ARM interrupt → scheduler iterates nodes → check bit), MAILBOXMASK is irrelevant to fn@0x1146C specifically.
- **fw's WFI likely wakes on chipcommon interrupt, not PCIE2.** That's why MBM=0 at post-set_active isn't blocking — it was already irrelevant.
- **The trigger for fn@0x1146C is a bit in chipcommon INTSTATUS.** Host would need to either set that bit (if it's HW-signalable) or cause an event that sets it.

## Next-step candidates

Given the partial static resolution, T283 produces these follow-ups:

### T285 — Chipcommon register dump across fw init stages

Hardware test. With T276+T277+T278+T284 all enabled, add a new probe that at each T284 stage reads:
- Chipcommon INTSTATUS (at BAR0 after select_core(CHIPCOMMON) + offset 0x100)
- Chipcommon INTMASK (offset 0x104)
- Chipcommon INTCONTROL (offset 0x108 or similar)
- Maybe chipcommon MAILBOXINT (offset 0x168 if the hypothesis is right)

Goal: observe which bits are set/cleared at each stage and whether any change under our poking correlates with a console advance.

### T286 — Deep wlc-probe trace (static, larger scope)

Disasm wlc-probe from entry (0x67614) tracing r7's origin and the struct allocations that feed into the fn@0x1146C callback chain. This would resolve the pending-events absolute address without further hardware fires.

Budget: 2-3h static work. Worth it only if T285 is ambiguous.

### T287 — Write chipcommon INTSTATUS to trigger fn@0x1146C

If T285 identifies the right bit, write chipcommon INTSTATUS directly (via select_core + offset 0x100) to simulate the trigger. Probe console for `wl_rte.c` printf/assert response per T281's observability analysis.

## What T283 did not settle

- Absolute address of the pending-events word (partial; strong inference only).
- Whether fw's WFI wake is on PCIE2 or chipcommon.
- Whether the chipcommon interrupt bit for fn@0x1146C is host-writable or HW-only.
- Why MBM defaults to 0x318 at pre-set_active (chip default vs something setting it — may be the chip's power-on / after-reset state).

## Recommendation

**Run T285 (hardware, cheap instrumentation) next.** It's the fastest way to get chipcommon-register data that either confirms the chipcommon hypothesis or redirects. If chipcommon INTSTATUS is also masked/zero, the wake path is completely different; if bits are set and the mask is open, we have a direct trigger to probe.

If T285 is ambiguous, T286 static-disasm of wlc-probe is the fallback.
