# T286 — wlc-probe r7 trace (static)

**Date:** 2026-04-24 (post-T285 null-fire)
**Goal:** Static resolution of fn@0x2309c's pending-events word absolute address via deeper wlc-probe trace.
**Status:** INCONCLUSIVE statically. Hit the "indirect too many layers" wall that advisor flagged as a possible stopping condition.

Scripts: `phase6/t286_wlc_probe_trace.py`, `phase6/t286_wlc_device_struct.py`, `phase6/t286_wlc_refs.py`, `phase6/t286_scheduler_ctx_dump.py`.

## Findings

### 1. wl_probe's `r7` = first argument (r0)

At fn@0x67614 entry:
```
0x67614  push.w {r4,...,fp,lr}
0x67618  sub sp, #0x24
0x6761a  mov r7, r0         ; *** r7 = wl_probe's r0 ***
0x6761c  mov r6, r1
```

r7 is preserved unchanged through wl_probe's body, then stored at `sp[0]` for hndrte_add_isr's 8th arg at 0x6776e. hndrte_add_isr writes it to `new_struct[8]`, and scheduler-dispatch invokes `(*new_struct[4])(new_struct[8])` = `fn@0x1146C(r7)`.

**So fn@0x1146C's r0 = wl_probe's r0 = whatever the device-probe iterator passed.**

### 2. wlc device struct at 0x58EFC — static layout

```
+0x000 = 0x00000000
+0x004 = 0x00058f1c         (ptr to +0x20 — fn-table base within same struct)
+0x008 .. +0x01c = 0
+0x018 = 0x00000000         ← if r7 = 0x58EFC, [r7+0x18] would be NULL
+0x020 = 0x00067615         (wl_probe with Thumb bit)
+0x024 = 0x00011649
+0x028 = 0x0001132d
+0x02c = 0x00011605
+0x030 = 0
+0x034 = 0x0001158d
+0x038 = 0x00011525
+0x03c = 0x0001146d         (fn@0x1146C with Thumb bit — our target)
```

**But `[0x58F14] = 0`**, so if the iterator passes `0x58EFC` as r0, fn@0x1146C's first instruction `ldr r4, [r0, #0x18]` would read NULL. Fw is known to be running after scheduler dispatches (T255/T274), so **r7 ≠ 0x58EFC**.

### 3. Zero literal-pool hits for 0x58EFC / 0x58F14

Exhaustive scan of the blob's 32-bit literals found NO loader of 0x58EFC or 0x58F14 in code. The wlc struct base is not loaded as a literal anywhere — confirming the iterator's dispatch passes something other than `0x58EFC` directly.

### 4. Scheduler ctx at 0x62A98 is zero-initialized BSS

```
+0x010 = 0  (flag_struct in fn@0x2309c)
+0x018 = 0  (dispatch_ctx_ptr in fn@0x1146C)
+0x088 = 0  (sub_struct in fn@0x2309c)
+0x08c = 0  (copied to +0x88 in class-0 thunk)
+0x168 = 0  (pending-events candidate)
+0x254 = 0  (BIT_alloc base per T283)
+0x258 = 0  (copied to +0x254)
```

All zeros statically. Populated at runtime by fn@0x672e4 + class thunks + per-device init calls. **No static resolution possible.**

### 5. Functions in wl_probe's pre-hndrte chain NOT YET TRACED

Still unexamined (each potentially adding another indirection layer):
- `fn@0x66e64` — called with r0 = r7 (wl_probe's arg). Result → sl.
- `fn@0x649a4` — called with r1 = r7, result stored at wlc_runtime[0x90].
- `fn@0x6491c` — called after, result at wlc_runtime[0x8c].
- `fn@0x68a68` — called at 0x67700 (this is the wlc_attach top, containing wlc_bmac_attach per T272).
- `fn@0x67f2c`, `fn@0x67e1c` — sub-calls in wlc_attach per T272.

Tracing each adds time and more indirection. Collective depth exceeds the 90-min budget advisor set for T283. T286 extends that budget but the "indirect too many layers" pattern is real — each function tends to allocate more heap structs and store pointers we'd then need to walk further.

## The wall

r7's value at runtime depends on:
1. Who calls wl_probe (the device-probe iterator — static, but iterator is itself indirect via the device list).
2. What's in the iterator's device-list entry for wlc.
3. Whether that entry is populated at runtime (likely, since device list entries have runtime data).

Without runtime data or a MUCH deeper static trace (tracing the device-list iterator init, probably several more function layers), **the absolute address of fn@0x2309c's pending-events word is not recoverable from static analysis alone.**

## Recommendation: pivot to runtime TCM-dump probe (T287)

Instead of more static tracing, **read the scheduler ctx struct's live values at post-set_active**. The struct is at TCM[0x62A98] (per T283). Adding a TCM-dump probe extends T285's infrastructure: at each stage (pre-write, post-set_active, each T278 hook), dump:

- TCM[0x62A98+0x10] — flag_struct pointer if scheduler_ctx is indeed the dispatch ctx
- TCM[0x62A98+0x18] — dispatch_ctx_ptr candidate
- TCM[0x62A98+0x88] — sub_struct pointer (after class-0 thunk runs)
- TCM[0x62A98+0x168] — pending-events candidate (if TCM-backed)
- TCM[0x62A98+0x254] — BIT_alloc base pointer (T283 inferred MMIO)
- TCM[0x62A98+0x258] — source of +0x254

Expected signals:
- If `scheduler_ctx[0x258]` = `0x18000000` (CHIPCOMMON MMIO base), T283's inference chain fully verified; `[0x254]+0x100` = `0x18000100` = chipcommon INTSTATUS.
- If `scheduler_ctx[0x88]` holds a pointer to a different MMIO address (e.g., `0x18100000` = PCIE2 base, or `0x18000000` = chipcommon), that tells us which core owns the pending-events word.
- If `scheduler_ctx[0x18]` is populated (non-zero), we can follow [0x18]+8+0x10+0x88 chain at runtime.

**T287 design**: add a helper `BCM4360_T287_READ_SCHED_CTX(tag)` that reads ~8 fields at TCM[0x62A98]. Zero-cost MMIO reads via `brcmf_pcie_read_ram32`. Piggyback onto T284/T285 call sites. READ-ONLY.

### Why T287 is better than more static work

- Bounded work (1 fire, 8 readbacks × ~10 stages = 80 values).
- Direct primary-source — no more chain inference.
- Deciding factor: reading the ACTUAL runtime values tells us everything the static trace couldn't.

### Risk for T287

Same substrate risk as T285 (T268-pattern pre-fw wedge). Need proper cold-cycle (≥5 min power-off ideally) before fire. If T287 also wedges at `test.125`, the substrate is persistently degraded and we're blocked on hardware.

## What T286 DID contribute

1. Confirmed wl_probe's r0 is passed through intact as fn@0x1146C's callback_ctx (not modified).
2. Confirmed wlc device struct at 0x58EFC has fn@0x1146C's ptr at [+0x38] (matches T273).
3. Confirmed no direct BL to wl_probe in the blob — indirect-dispatch-only.
4. Confirmed no literal-pool loader of 0x58EFC — iterator uses dynamic addressing.
5. Confirmed scheduler ctx at 0x62A98 is zero-init BSS (not pre-populated in blob image).

## Next step

Implement T287 (runtime scheduler-ctx dump) per the design above. Same gating pattern as T285 (`bcm4360_test287_sched_ctx_read`, requires T276+T277+T278+T284). Build + PRE-TEST block + user cold-cycle + fire.
