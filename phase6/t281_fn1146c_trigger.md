# T281 — static analysis of fn@0x1146C trigger chain

**Date:** 2026-04-24 (post-T278, pre-T279)
**Goal:** Before firing a mailbox-poke test (T279), figure out which register / bit / event fn@0x1146C responds to. Advisor-directed deliverables: (1) class-to-bit mapping, (2) hndrte_add_isr flag allocation for fn@0x1146C, (3) whether fn@0x23374 / fn@0x113b4 log anything (→ T279 observability).

Scripts: `phase6/t281_fn1146c_dispatch.py`, `phase6/t281_fn23374_extent.py`, `phase6/t281_fn2309c.py`, `phase6/t281_thunks.py`.

## Results by deliverable

### Deliverable (3) — logging from fn@0x23374 / fn@0x113b4 — **STRONGLY POSITIVE**

Both functions contain `printf` (BL 0xA30) and `printf/assert` (BL 0x11E8) calls. If either fires, fw will log new content to the console T277/T278 demonstrated. Highlights:

- **fn@0x23374** (flag-byte test helper):
  - `bl #0x14948` (trace), `bl #0xa30` (printf) x2 at 0x233a8..0x233b2
  - `bl #0x11e8` (printf/assert) with line 0x300 (768) at 0x233cc
- **fn@0x113b4** (action dispatcher, 184 bytes):
  - `bl #0x14948` trace + `bl #0xa30` printf at 0x1141a..0x1141e
  - `bl #0xa30` printf at 0x11424
  - `bl #0x11e8` printf/assert with string `'wl_rte.c'` + line 0x5c5 (1477) at 0x1144e
  - Plus BL calls to fn@0x4750, fn@0x2312c, fn@0x1138, fn@0x233e8 — all may log

**Observation for T279: blind mailbox-poke will produce CONSOLE output if the right bit is hit.** Even without knowing the exact bit, we can sweep and watch. Console produces an ASCII trail per fire.

### Deliverable (1) — trigger-check mechanism — **PATTERN RESOLVED; specific register TBD**

Call chain: `fn@0x1146C → fn@0x23374 → fn@0x2309c` (the actual bit-check).

**fn@0x1146C** (10 insns, 32 bytes):
```
push {r0, r1, r4, lr}
ldr r4, [r0, #0x18]     ; r4 = scheduler_node.[0x18]
add.w r1, sp, #7         ; r1 = &local_byte
ldr r0, [r4, #8]         ; r0 = dispatch_ctx
bl #0x23374              ; test flag
cbz r0, .end             ; if fn returns 0, skip
ldrb.w r3, [sp, #7]      ; load local_byte
cbz r3, .end             ; if byte == 0, skip
mov r0, r4               ; r0 = scheduler_node.[0x18]
bl #0x113b4              ; ACTION
.end: pop {r2, r3, r4, pc}
```

**fn@0x23374** (flag-byte test helper):
- Loads `r4 = *(ctx+0x10)` — the flag struct
- Clears *byte_out
- Checks `[flag+0xac]` byte (enabled?) → skip if 0
- Checks `[flag+0x60]` dword (queue state?) → skip if 0
- Calls `fn@0x2309c(ctx, 1)` — the trigger check
- If return != -1 AND return != 0: sets *byte_out = 1 (fire action)

**fn@0x2309c** (trigger check — the key function):
```
ldr r4, [r0, #0x10]       ; r4 = flag struct
ldr r5, [r4, #0x88]       ; r5 = flag.[0x88] (sub-struct)
ldr r6, [r5, #0x168]      ; r6 = PENDING-EVENTS WORD at sub_struct.[0x168]
...
(if debug flag set: printf trace lines)
bl #0x23076               ; additional pre-check (possibly busy/lock)
cbnz r0, ret_minus_1      ; if busy, return -1 (retry later)
cmp r6, #-1
beq ret_0                 ; no events
ldr r3, [r4, #0x60] or [r4, #0x64]  ; flag mask (based on flag_select)
ldr r0, [r4, #0x180]      ; additional mask
orr r0, r3, r0
ands r0, r6                ; match: pending & our_mask
beq ret_0                 ; no match
; MATCH! consume events via W1C:
str r3, [r5, #0x16c]      ; (clear some)
str r0, [r5, #0x168]      ; W1C write-back = clear matched bits
str r3, [r4, #0x60]       ; clear local tally
tst r0, #0x8000           ; special bit
bne store_0x10000_at_[r5, #0x28]
pop; return r0 (matched bits)
```

**Key structural findings:**

- The pending-events word is at `[[ctx.inner[0x10]].inner[0x88]] + 0x168`. The dispatcher is a classic "AND pending with mask; clear matched bits via W1C" pattern.
- `str.w r0, [r5, #0x168]` AFTER match = W1C clear — matches MMIO semantics (write-one-to-clear doorbell registers).
- T274 previously searched for writers of the "software pending-events word" and found zero. This is strong evidence the word is **HW-mapped** (i.e., it's an MMIO register, not TCM-backed memory). That aligns with `pending-events-word = MMIO doorbell register`.

Without runtime visibility of ctx/flag struct addresses, the **specific MMIO offset** isn't statically resolvable from fn@0x2309c alone. But the pattern matches Broadcom MAILBOXINT register conventions.

### Deliverable (2) — fn@0x1146C's flag bit allocation — **INDIRECTLY KNOWN**

T274 established: pciedngl_isr got bit 3 (flag=0x8) via hndrte_add_isr. For wlc's fn@0x1146C, registered by the same helper at 0x67774, the bit is different — likely allocated sequentially (bit 4 = 0x10, or similar) from the same pool.

The **9-thunk vector at 0x99AC..0x99CC** is a per-class init table (8 active classes, 1 no-op fallback):

```
0x99ac  b.w #0x27ec    ; class 0
0x99b0  b.w #0x2b8c    ; class 1
0x99b4  b.w #0x2bdc    ; class 2
0x99b8  b.w #0x28e2    ; class 3
0x99bc  b.w #0x28ae    ; class 4
0x99c0  b.w #0x2904    ; class 5
0x99c4  b.w #0x29ac    ; class 6
0x99c8  b.w #0x2a4c    ; class 7
0x99cc  movs r0, #0    ; class ≥8 — return 0 (no-op)
0x99ce  bx lr
```

Reached via the class-validate wrapper at `0x9990` which tail-calls `0x27EC` (class 0 target — which then does per-class dispatch internally). T274 said pciedngl routes through this and allocates bit 3.

The class-value-to-bit mapping isn't a clean 1:1 table — it's done dynamically inside `hndrte_add_isr` by searching a pool for an unused bit. **Therefore: the only reliable way to know fn@0x1146C's bit is to observe hndrte_add_isr's allocation at runtime** — i.e., a peek at the scheduler callback list during the ladder (T278-style console read or a dedicated T279 probe).

## What this means for T279

**Register-direction correction (advisor):** MAILBOXINT is the D2H (fw→host) mirror with W1C semantics — writing it from the host CLEARS fw-set bits, it does NOT trigger fw. The host-to-device trigger registers are **H2D_MAILBOX_0** and **H2D_MAILBOX_1**; writing a non-zero value to either causes fw's internal MAILBOXINT to latch the corresponding FN0_n bit.

**Design directly follows**:
1. **Positive control: write `H2D_MAILBOX_0 = 1`** → causes fw's MAILBOXINT.FN0_0 (bit 0x100) to latch → fires fw's pciedngl_isr per T274. Known-positive path. If fw logs `"pciedngl_isr called"` (string at blob 0x40685), console-observation path is end-to-end verified.
2. **Hypothesis: write `H2D_MAILBOX_1 = 1`** → upstream convention is "hostready" doorbell. Upstream gates this on `HOSTRDY_DB1` (which fw doesn't advertise per T274), but the write itself is safe to attempt. If it fires fn@0x1146C's bit, new log content mentioning `wl` / `bmac` / `intr` / `wl_rte.c` will appear (fn@0x113b4 has `printf/assert` at line 1477).
3. **Advisor order: hypothesis first, positive control second.** Freshest chip state for the higher-value probe. Between probes: `msleep(100)` + T278 delta dump.
4. **Observability**: fn@0x23374 and fn@0x113b4 both contain printf/assert. A successful trigger WILL produce console output.
5. **Sanity check before first write**: read `MAILBOXMASK` register. If 0, fw has all mailbox ints masked — writes would be futile.
6. **Safety**: no MSI, no request_irq (T264-T266 host wedge was MSI-subscription-only; orthogonal to mailbox writes). Prior scaffolds wedged because they lacked shared_info context; T279 runs after shared_info is written and acknowledged.

## Open questions (not blocking T279)

1. **Precise MMIO address of the pending-events word at [sub+0x168].** Would let us verify our MAILBOXINT writes hit exactly the right register. Best resolved by: (a) inspecting hndrte_add_isr allocation tracker at runtime, OR (b) cross-refing against Broadcom brcmsmac PCIe register map (chipc's mailbox block).
2. **Timestamp unit in fw's console (`125888.000`).** Unlikely load-bearing for T279 but would help correlate log entries with our polling timestamps.
3. **fn@0x2309c's helper `fn@0x23076`** (pre-check busy/lock). Not traced; not blocking.

## Declaring T281 complete

- Deliverable 3 (logging): CONFIRMED strong — multiple printf/assert calls in both fn@0x23374 and fn@0x113b4.
- Deliverable 1 (trigger mechanism): pattern fully understood (pending-events-word AND flag-mask, W1C clear); specific register offset requires runtime probe.
- Deliverable 2 (flag bit for fn@0x1146C): indirectly known to be allocated from hndrte_add_isr's bit pool; specific bit = bit 4+ (pciedngl took bit 3).

Static phase complete. Ready to call advisor for T279 directed-fire design.
