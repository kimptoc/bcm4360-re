# Offline disassembly: fn 0x6820c body (firmware initialization chain)

Scope: fn 0x6820c (called from wlc_attach @ 0x68b90) disassembled 0x6820c..0x68a16.
Called as `bl 0x6820c` with LR=0x68b95 pushed on stack.

Tool: capstone 5.0.7 (nix-shell).

Date: 2026-04-17 (test.103 follow-up).

## Executive summary

**Primary hang candidates:**

1. **HIGHEST: fn 0x68cd2 at 0x68258** — first body call, return value checked immediately. If this fn never returns or returns 0, execution branches to 0x689ee (final cleanup) without running any downstream logic. fn 0x68cd2 reportedly "does struct allocation and initialization"; no visibility yet into what it polls or waits for.

2. **HIGH: fn 0x67f44 at 0x68308** — mid-body call, return value gated to error path. Hits error path (movs r3, #0xd; b 0x68356) if nonzero. Not yet traced; could be a synchronization or module-load routine.

3. **MEDIUM-HIGH: fn 0x179c8 at 0x6832c** — late in execution chain. Return checked at 0x68330; if nonzero, branches to 0x6835a (alternate path involving 0x52a2 nvram_get calls and 0x68d7c, 0x3e0b0 secondary init). If this fn hangs, CPU never reaches the alternate init path.

4. **RECURRING POLLING:** Function contains 18 instances of `ldr r3, [r7]; cmp r3, #v; beq/bge pattern` (lines below). These poll a global flag loaded at 0x68210 (r7 = [pc, #0x1fc]). The flag controls console logging conditionally (via bl 0x14948, bl 0xa30 pairs). These are not blocking loops themselves but may mask underlying hangs if the polled flag never changes.

**Most likely overall hang site:** fn 0x68cd2 (first deep call), because:
- It's the first function called after prologue (0x68258)
- Return value is checked immediately (0x6825e)
- If it hangs or returns 0, no downstream code runs
- fn 0x68a68's description notes "0x68cd2, 0x142e0, fn 0x191dc, 0x9990, 0x9964 — not yet fully traced"

No fixed-TCM writes in fn 0x6820c body itself (all stores are sp-relative or object-field-relative).

---

## Prologue and frame layout

```
0x6820c: push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}  ; 36 bytes saved
0x68210: ldr r7, [pc, #0x1fc]                         ; r7 = global flag addr
0x68212: sub sp, #0x74                                ; reserve 116 bytes
0x68214: mov r6, r3                                   ; save arg3
0x68216: ldrb.w fp, [sp, #0x98]                       ; load arg4 from stack
0x6821a: movs r3, #0
0x6821c: mov r5, r0                                   ; save arg0
0x6821e: str r3, [sp, #0x6c]                          ; zero local var
0x68220: mov sl, r1                                   ; save arg1
0x68222: ldr r3, [r7]                                 ; load global flag
0x68224: mov r8, r2                                   ; save arg2
0x68226: ldr.w sb, [sp, #0xa8]                        ; load arg5 from stack
```

**Frame size:** 152 bytes (36 pushed regs + 116 sub + 4-byte alignment slack).

LR at entry (0x68b95) resides at [sp, #0xb0] relative to prologue SP (post-push, pre-sub).

---

## BL/BLX call list (101 total)

Key semantic hints:
- **0x14948, 0xa30** = logging pair (gated by r7 flag checks)
- **0x191dc** = chip-id dispatcher (called @0x682a8, @0x6860a)
- **0x9990, 0x9964, 0x9a9c, 0x9956, 0x9a98, 0x9914** = HW register read/init functions
- **0x52a2, 0x5198, 0x51c4, 0x51dc** = nvram_get with key lookup
- **0x68cd2, 0x68d5a, 0x68d7c** = struct allocation/init (same module as 0x6820c)
- **0x35e5a, 0x3e0b0, 0x3e0b0** = PHY/chip secondary init

| # | Addr | Target | LR saved | First-level semantic |
|----|------|--------|----------|---------------------|
| 1 | 0x68238 | 0x14948 | 0x6823d | logging (gated by r7 check @0x6823e) |
| 2 | 0x6823c | 0xa30 | 0x68241 | logging output |
| 3 | 0x6824c | 0xa30 | 0x68251 | logging output (in conditional block) |
| 4 | 0x68258 | 0x68cd2 | 0x6825d | ★ STRUCT ALLOC/INIT (return checked @0x6825e: if 0, goto 0x689ee) |
| 5 | 0x6827c | 0x142e0 | 0x68281 | HW register copy (per 68a68 notes) |
| 6 | 0x6829a | 0x11e8 | 0x6829f | logging (error path: "no PHY") |
| 7 | 0x682a8 | 0x191dc | 0x6829d | chip-id dispatcher |
| 8 | 0x682d4 | 0x9990 | 0x6829d | HW register read (per 68a68) |
| 9 | 0x6829e4 | 0x11e8 | 0x6829d | logging (error path: "read failed") |
| 10 | 0x682ea | 0x9964 | 0x682ef | HW register read (per 68a68) |
| 11 | 0x682fa | 0x11e8 | 0x682ff | logging (error path: "invalid config") |
| 12 | 0x68308 | 0x67f44 | 0x6830d | ★ UNKNOWN (return @0x6830c: if ≠0, error; goto 0x68356) |
| 13 | 0x68314 | 0x9a9c | 0x68319 | HW register read |
| 14 | 0x6831c | 0x1415c | 0x68321 | HW init (unknown target) |
| 15 | 0x68326 | 0x15940 | 0x6832b | HW init (unknown target) |
| 16 | 0x6832c | 0x179c8 | 0x68331 | ★ INIT CHAIN (return @0x68330: if ≠0, goto 0x6835a alt-path) |
| 17-19 | 0x68342/8/50 | 0x14948/a30/a30 | ... | logging (conditional on r7 @0x68334) |
| 20 | 0x6835e | 0x52a2 | 0x68363 | nvram_get (on alt-path @0x6835a) |
| 21 | 0x6836e | 0x67e1c | 0x68373 | struct field setup |
| 22-24 | ... | 0x14948/a30/a30 | ... | logging (conditional) |
| 25 | 0x6836a8 | 0x52a2 | 0x6829d | nvram_get (series of 5 calls) |
| ... | ... | 0x52a2 | ... | nvram_get (4 more) |
| 30 | 0x6846e | 0x14a84 | 0x68473 | struct field manipulation |
| 31-91 | ... | mixed | ... | long switch/dispatch on chip-ID (multiple targets like 0x6b59c, 0x6a814, 0xa954, 0x35e5a, 0x6af88/a8/ae, 0x6a814, 0x67f8c, 0x1482c, 0x176ea, 0x14bf8, etc.) |
| 92 | 0x6898c | 0x68d7c | 0x68991 | struct field setup (alt init) |
| 93 | 0x6889b6 | 0x3e0b0 | 0x6829d | PHY secondary init (alt init path) |
| 94-101 | ... | 0x14948/a30 pairs | ... | logging (final cleanup and error paths) |

---

## Polling patterns in fn 0x6820c

18 instances of conditional-flag polling via global r7 (loaded at 0x68210 from [pc, #0x1fc]):

```
ldr r3, [r7]        ; poll global flag (addresses vary: 0x68232, 0x6833c, 0x6837e, ...)
cmp/tst r3, #v      ; test against constant
beq/bge/bne target  ; branch on result
```

Affected instruction addresses:
- 0x68232 cmp, 0x68234 cmp, 0x68236 bge (gates logging at 0x68238)
- 0x6833c cmp, 0x6833e cmp, 0x68340 bge (gates logging at 0x68342)
- 0x6837e cmp, 0x68380 cmp, 0x68382 bge (gates logging at 0x68384)
- (13 more similar patterns)

**Implication:** Function polls a global configuration flag ~18 times. These are non-blocking checks (branch over logging, not spin loops). However, they reveal that large portions of fn 0x6820c's body are conditional on this flag — if the flag is corrupted or uninitialized, execution may skip critical init code.

---

## No fixed-TCM writes in fn 0x6820c body

All stores are **register-relative** (sp, r0, r3, r4, r5-relative) or **indirect** (field offsets into dynamically-allocated objects). No literal fixed-address writes like `str r0, [#0x62e20]` found.

Typical patterns:
```
str r0, [r4, #0x10]          ; field offset into dynamically-allocated struct
str.w r0, [r4, #0x88]        ; wide variant
strb.w r0, [r4, #0x50]       ; byte store
strh.w r0, [r4, #0x52]       ; halfword store
str r3, [sp, #0x6c]          ; sp-relative (stack local)
```

**Breadcrumb implication:** Cannot use fn 0x6820c body itself to set a TCM progress marker. Breadcrumbs must be placed in **target functions** (0x68cd2, 0x67f44, 0x179c8, etc.) if they write fixed TCM addresses, or by polling dynamic object pointers.

---

## Recursion / re-entry check

**No back-calls to 0x6xxxx or 0x68xxx range found.** All 101 BL targets are either:
- Lower addresses (0x9990, 0x9964, 0x52a2, 0x11e8 = support functions)
- Higher addresses in same module (0x68cd2, 0x68d7c, 0x68d5a = sister init routines)
- Far-off dispatch regions (0x35e5a, 0x3e0b0, 0x06af88, 0x06a814 = PHY/chip init)

No evidence of re-entry into fn 0x68a68 (wlc_attach) or fn 0x6820c itself.

---

## Function end

```
0x68a12: ldr r0, [sp, #0x6c]          ; load return value from stack local
0x68a14: add sp, #0x74                ; restore sp (undo prologue sub)
0x68a16: pop.w {r4, r5, r6, r7, r8, sb, sl, fp, pc}  ; restore regs + return
0x68a1a: nop
```

**Epilogue matches prologue:** sub sp / add sp; push.w ... pc / pop.w ... pc.

Return value = contents of [sp, #0x6c] (zeroed at 0x6821e, written by downstream logic). This value is returned to wlc_attach caller (0x68b94), which checks it at 0x68b96.

---

## Refined hypothesis for test.104+

1. **Immediate disasm priority: fn 0x68cd2 (0x68258)** — first sub-call, gating all downstream code. If it hangs or returns 0, none of the rest runs.

2. **Secondary: fn 0x67f44 (0x68308)** — midway, error-gating call. Hang here would stall one init path.

3. **Tertiary: fn 0x179c8 (0x6832c)** — late-init call that gates an alternate path (0x6835a..0x68a0e). If it hangs, CPU never reaches that logic.

4. **Flag polling:** All 18 `ldr r3, [r7]` checks are non-blocking (short branches to logging or next insn). Global flag is loaded at 0x68210 from a literal pool offset. If flag is garbage, behavior is unpredictable but not a spin-loop hang by itself.

---

## Summary statistics

| Metric | Count |
|--------|-------|
| Total BL/BLX instructions | 101 |
| Prologue instructions | 8 |
| Epilogue instructions | 4 |
| Function span (0x6820c to 0x68a16) | 2058 bytes |
| Frame size (saved regs + local stack) | 152 bytes |
| Unique call targets | ~50+ |
| Conditional polling patterns | 18 |
| Fixed TCM writes | 0 |

---

## Conclusion

fn 0x6820c is a **deep initialization cascade** (101 BL calls over 2 KB of code). The hang is most likely in **fn 0x68cd2** (first sub-call after prologue, gating everything), or in one of the 18 conditional branches that may skip critical init if the global r7 flag is corrupted. No progress breadcrumbs available in this function's body itself; next steps must disasm the target functions to find where the hang actually occurs.

