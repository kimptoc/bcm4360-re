# test.103 LR → function interpretation table (SHALLOW frames)

Purpose: extend test102_lr_table.md UPWARD (shallower) — the caller
chain from firmware boot DOWN to wl_probe. Together with the deep-
descent table, this covers the full stack at hang time.

Format: `LR_value = return_address_after_bl` (the value the CPU pushes
on the stack when `bl` / `blx Rm` executes). Thumb → LSB is set (odd).

Sources:
- offline_disasm_fw_stack_setup.md (reset path 0..0x2FC)
- offline_disasm_c_init.md (c_init @ 0x642fc, fn 0x63b38 body)
- Fresh offline disasm of 0x2408 (main), 0x2fc..0x330 (boot tail)

**Most LR values are Thumb — from `bl`/`blx` instructions which OR-in
the LSB automatically. Actual register value = `addr | 1`.**

**EXCEPTION:** the outermost saved LR (from boot, frame A) is
**0x320 — EVEN**. That's because the reset code at 0x318-0x31a does
`ldr r0, [pc,#0x60]; mov lr, r0` (literal `0x320` verbatim — `mov`
doesn't set the Thumb bit) then `bx r4`. So main's `push {r4,lr}`
saves the raw 0x320.

Filter: use `word ∈ [0x300..0x70000]` AND `(word & 1)` for CALL-site LRs
(Frames B..G). For the main-frame anchor at 0x9D09C, check for **0x320
exact** — it won't pass the odd-bit filter, but it's the single static
"stack base" marker that confirms the sweep landed on the true stack.

---

## Boot → c_init chain

The reset path at 0x2FC sets SP = 0x9D0A0, then:
```
0x2fc  mov sp, r5                      ; SP = TCM_top - 0x2F60
0x2fe..0x310  zero BSS [0x62910..0x63ac4)
0x312  *0x21c = 0xa2c                  ; some state marker
0x318  lr = 0x320                      ; manual LR load — return target
0x31c  r4 = 0x2409                     ; Thumb → fn 0x2408
0x31e  bx r4                           ; JUMP (not bl!) into fn 0x2408
0x320  *0x21c = 0xbaad; b 0x326        ; infinite loop on return
```

Because 0x31e is `bx` not `bl`, it doesn't push LR — and because LR
was loaded manually via `mov lr, r0` from the literal `0x320` (no LSB
OR-in like `bl` would do), when fn 0x2408 does `push {r4, lr}` the
saved LR = **0x320 (raw literal, EVEN)**. Verified: `data[0x37c:0x380]
= 0x00000320`. main is never expected to return — 0x320 is a shutdown
marker loop (`*0x21c = 0xbaad; b 0x326`) — so the ARM/Thumb mismatch
(even = ARM-mode) never matters. 0x320 sits at 0x9D09C as a permanent
static "stack bottom" anchor.

### Frame A: main @ 0x2408 — the firmware entry function

Entry LR = **0x320 (EVEN)** — this is the literal value the boot code
stuffed into LR before the `bx r4` jump. Pushed by main's first
instruction.

```
0x2408: push {r4, lr}              ; 8-byte frame
0x240a: bl  0x642dc                ; pre-init (leaf, no BL; just 4-byte copy)
0x240e: bl  0x1cc                  ; leaf (sets CP15 c9/c12 selectors)
0x2412: bl  0x642fc                ; <-- c_init (THE MAIN INIT) — 104-byte frame
0x2416: mov r4, r0
0x2418: bl  0xc6c                  ; post-c_init (likely "run app")
0x241c: mov r0, r4
0x241e: pop.w {r4, lr}
0x2422: b.w 0x11d0                 ; tail jump
```

| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x240a  | 0x642dc (leaf copy) | 0x240b |
| 0x240e  | 0x1cc (CP15 setter, leaf) | 0x240f |
| **0x2412** | **0x642fc (c_init)** | **0x2417** |
| 0x2418  | 0xc6c (post-init) | 0x2419 |

**Most-likely-on-stack LR:** **0x2417** — c_init is still executing at
hang time, so the active BL inside main IS 0x2412.

---

## Frame B: c_init @ 0x642fc — 104-byte frame (0x24 push + 0x44 sub)

c_init prologue: `push {r4-r11, lr}` (9 regs = 36 B) + `sub sp, #0x44`
(68 B) → total 104 B per frame.

ALL BL sites inside c_init body (0x642fc..0x6453e):

| # | BL site | Target | LR | Role |
|---|---------|--------|-----|------|
| 1 | 0x64302 | 0x63d9c | 0x64303 | early hook (pre-banner) |
| 2 | 0x6430c | 0x9a46  | 0x6430d | heap/pool init |
| 3 | 0x64314 | 0x99ac  | 0x64315 | alloc helper |
| 4 | 0x6432e | 0xa30 (printf) | 0x6432f | debug print (gated) |
| 5 | 0x6433e | 0x5514  | 0x6433f | helper |
| 6-8 | 0x6434c,0x54,0x64 | 0x9a1e × 3 | 0x6434d..0x64365 | 3× helper |
| 9-11| 0x64374,0x84,0x94 | 0x99d0 × 3 | 0x64375..0x64395 | 3× helper |
| 12-14| 0x643a6,0xb2,0xba | 0x1c22 × 3 | 0x643a7..0x643bb | 3× helper |
| 15 | 0x64446 | 0xa30 | 0x64447 | **RTE BANNER** (visible) |
| 16 | 0x64456 | 0xa30 | 0x64457 | "c_init: add PCI device" (gated) |
| 17 | 0x64464 | **0x63b38** | 0x64465 | **pciedngl device register** (RETURNED per test.99) |
| 18 | 0x64478 | 0x673cc | 0x64479 | returns const 0x43b1 (WL dev id) |
| 19 | 0x6449a | 0xa30 | 0x6449b | "add WL device 0x%x" (gated) |
| 20 | **0x644a6** | **0x63b38** | **0x644ab** | **wl device register — CURRENTLY ACTIVE** |
| 21 | 0x644ba | 0x11e8 | 0x644bb | assert (not taken in success path) |
| 22 | 0x644c6 | 0x11e8 | 0x644c7 | assert (not taken) |
| 23 | 0x644dc | blx r3 (0x1fc2) | 0x644dd | dispatch — **not yet reached** |
| 24 | 0x644f2 | 0xa30 | 0x644f3 | failure print |
| 25 | 0x644fc | blx r3 | 0x644fd | vtable dispatch — not reached |
| 26 | 0x64510 | 0xa30 | 0x64511 | failure print |
| 27 | 0x6451a | blx r3 | 0x6451b | vtable dispatch — not reached |
| 28 | 0x6452a | 0xa30 | 0x6452b | (late) |

**Most-likely-on-stack LR:** **0x644ab** — the wl call to fn 0x63b38
is the one that descends into wl_probe → fn 0x68a68 → PHY wait.

Note: LR 0x64465 (from pciedngl call #17) is NOT on the stack — that
call returned before #20 ran. Same for all earlier BLs.

---

## Frame C: fn 0x63b38 — 24-byte frame (push 6 regs)

Prologue: `push {r0, r1, r4, r5, r6, lr}` (6 × 4 = 24 B). No sub sp.
Epilogue: `pop {r2, r3, r4, r5, r6, pc}` (r0/r1 scratch slots popped
as r2/r3 and discarded).

Body BLs (0x63b38..0x63b92):

| BL site | Target | LR | Role |
|---------|--------|-----|------|
| 0x63b54 | blx r6 (r1==0x700 path — **NOT taken** for wl: size=0x812) | 0x63b55 | not on stack |
| 0x63b62 | 0x9990 | 0x63b67 | alloc — RETURNS (reached 0x63b78) |
| **0x63b78** | **blx r6 (= wl_struct.ops[0] = 0x67615 = wl_probe)** | **0x63b7b** | **CURRENT — wl_probe is running** |

**Most-likely-on-stack LR:** **0x63b7b** — wl_probe hasn't returned.

The `blx r6` is an indirect call via function-pointer table (wl_struct
at 0x58ef0, +0x10 → 0x58f1c → ops[0] = 0x67615 = fn 0x67614 = wl_probe).
Return address = 0x63b78 + 2 = 0x63b7a → LR = 0x63b7b.

---

## Frame D: wl_probe @ 0x67614 — 72-byte frame (0x24 push + 0x24 sub)

Prologue: `push.w {r4-r11, lr}` (9 regs = 36 B) + `sub sp, #0x24` (36 B)
= 72 B.

Body BLs — this is the CRITICAL list (from offline disasm 0x67614..0x67890):

| BL site | Target | LR | Role |
|---------|--------|-----|------|
| 0x67628 | 0xa30 (printf) | 0x6762d | "wl_probe called" — VISIBLE |
| 0x67630 | 0x7d60 (malloc) | 0x67635 | alloc wl ctx 176B |
| 0x6764c..0x6765d | gated error path | — | not taken |
| 0x67662 | 0x91c (memset) | 0x67663 | zero ctx |
| 0x6766a | 0x66e64 | 0x6766f | early sub-init |
| 0x67672 | 0x649a4 | 0x67677 | sub-init → r4[+0x90] |
| 0x6769x..0x67699 | gated error path | — | not taken |
| 0x676a0 | 0x4718 | 0x676a5 | helper |
| 0x676ae | 0x6491c | 0x676b3 | sub-init → r4[+0x8c] |
| 0x676cc..0x676dd | gated error | — | not taken |
| **0x67700** | **0x68a68 (wlc_attach)** | **0x67705** | **CRITICAL — descends into PHY wait** |
| 0x6771c..rest | post-wlc_attach | — | not reached |

**Most-likely-on-stack LR:** **0x67705** — per test102 table, wlc_attach
is the unique path that reaches the D11 PHY wait where we believe the
hang lives.

---

## Frames E..G (from test102_lr_table.md — deep chain)

- Frame E: wlc_attach @ 0x68a68, 96 B (0x24 push + 0x3c sub)
  - Critical LR: **0x68acf** (calls 0x67f2c trampoline → 0x67358)
- Frame F: fn 0x67358, 48 B (12-reg push, no sub)
  - Critical LR: **0x6739d** (bl 0x670d8)
- Frame G: fn 0x670d8, 48 B (12-reg push, no sub)
  - Next LR candidates: 0x67195 / 0x671b5 / 0x671c1 / 0x671d5 / 0x671f7
    (depending on which sub-call is currently hung)

The 0x67f2c trampoline has push/pop — leaves NO persistent frame.

---

## Consolidated stack layout (SP_TOP = 0x9D0A0)

Offsets computed by simulating push/sub for each frame. `LR_at` is the
absolute TCM address where that frame's saved LR sits. Stack grows
DOWN; SP_after = SP after entire prologue (push + sub).

| Frame | Saved LR | Saved at | SP_after |
|-------|----------|----------|----------|
| A: main @ 0x2408       | **0x00000320** (boot shutdown marker — EVEN) | **0x9D09C** | 0x9D098 |
| B: c_init @ 0x642fc    | **0x00002417** (return to main)            | **0x9D094** | 0x9D030 |
| C: fn 0x63b38 (wl call)| **0x000644ab** (return to c_init)          | **0x9D02C** | 0x9D018 |
| D: wl_probe @ 0x67614  | **0x00063b7b** (return to fn 0x63b38)      | **0x9D014** | 0x9CFD0 |
| E: wlc_attach @ 0x68a68| **0x00067705** (return to wl_probe)        | **0x9CFCC** | 0x9CF70 |
| F: fn 0x67358          | **0x00068acf** (return to wlc_attach)      | **0x9CF6C** | 0x9CF40 |
| G: fn 0x670d8          | **0x0006739d** (return to 0x67358)         | **0x9CF3C** | 0x9CF10 |

Between saved-LR slots, intermediate addresses hold saved r4-r11 / sub
sp locals — those are generally NOT LR-shaped (heap ptrs, counters,
handles). The LR filter `(val & 1) && 0x300 < val < 0x70000` should
cleanly isolate the 7 LRs above.

### Critical LRs — 5 to 8 most important values to find

Priority-ordered (deepest first, strongest freeze evidence):

1. **0x63b7b** — wl_probe is running (if seen: confirms hang is inside wl_probe subtree)
2. **0x644ab** — c_init's wl bl 0x63b38 is active (if seen: confirms c_init didn't return)
3. **0x2417** — main called c_init (base of whole chain)
4. **0x67705** — wlc_attach (fn 0x68a68) is running (deep chain confirmed)
5. **0x68acf** — fn 0x67358 is running
6. **0x6739d** — fn 0x670d8 is running
7. **0x320** — outermost LR (boot tail marker — EVEN; always present as static anchor at 0x9D09C)
8. Then one of: **0x67195 / 0x671b5 / 0x671c1 / 0x671d5 / 0x671f7** — tells us WHICH 0x670d8 sub-call is hung

### Sweep interpretation guide

If the 16-word sweep near 0x9D090..0x9D0A0 shows both **0x320** (at
0x9D09C — note EVEN, use exact-match not odd-bit filter) and 0x2417
(at 0x9D094), that locks down the outer chain unambiguously. Then
follow deeper addresses:

- 0x9D02C: should be 0x644ab → confirms wl fn 0x63b38 frame
- 0x9D014: should be 0x63b7b → confirms wl_probe frame
- 0x9CFCC: should be 0x67705 → confirms wlc_attach frame
- 0x9CF6C: should be 0x68acf → confirms 0x67358 frame
- 0x9CF3C: should be 0x6739d → confirms 0x670d8 frame

Sweep window suggestion: 64 words × 4 B = 256 B covering
[0x9CF10..0x9D0A0) captures the full chain A..G plus one deeper
frame (the hung 0x670d8 sub-call's saved LR).

### Alternate hypothesis: hang earlier than wlc_attach

If the sweep shows 0x320 + 0x2417 but NOT 0x644ab at 0x9D02C:
- Maybe hang is inside one of c_init's earlier BLs (less likely — see
  "Remaining freeze candidates" in offline_disasm_c_init.md).
- Or hang is inside the pciedngl fn 0x63b38 call at 0x64464 (LR would
  be **0x64465** at 0x9D02C instead of 0x644ab) — test.99 vtable
  evidence argues AGAINST this.

If 0x320 appears at 0x9D09C but 0x2417 does NOT at 0x9D094: freeze
is BEFORE c_init — only inside 0x642dc (a leaf, no frame) or 0x1cc
(leaf) — extremely unlikely given RTE banner was observed.

If 0x320 does NOT appear at 0x9D09C: sweep missed the stack entirely
OR stack was trashed (very unlikely — 0x320 is written once at boot
and overwritten only if stack depth exceeds the full 0x2F5C allocation).
