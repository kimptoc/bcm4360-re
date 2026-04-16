# Offline disassembly: c_init() and the freeze region

**Date:** 2026-04-17
**Source:** `phase1/output/firmware_4352pci.bin` (md5 812705b3...) ≡ `/lib/firmware/brcm/brcmfmac4360-pcie.bin`
**Tool:** `cstool`/capstone via `command nix-shell -p python3Packages.capstone`
  (note: shell-snapshot wraps `nix-shell` with `--command zsh`, which silently
   drops `--run`; must invoke `command nix-shell` directly)

## Loader assumptions

- Firmware loaded at TCM base 0x00000000. File offset == TCM virtual address.
- Pool literals use the raw 0x000xxxxx form (no high-bit alias).

## c_init() — verified via disassembly

- Function starts at TCM **0x642fc** (`push.w {r4-r11, lr}` — full register save).
- Function body: 0x642fc … 0x6453e (**0x242 = 578 bytes** — corrected).
- Literal pool: 0x64540 … 0x6458c.
- Pool order matched execution order (verified by LDR-literal scan).
- Tail: `pop.w {r4-r11, pc}` at 0x64532 ✓.

### Annotated call sequence

```
0x642fc  push.w {r4-r11, lr}                       <-- function entry
...      [setup elided — sets up r4 (caller arg), r5 (flag word ptr)]
0x643ce  ldr.w lr, =0x40c2f                        ; lr = "6.30.223 (TOB) (r)"
...      [more setup; computes a divide for one of the MHz args]
0x6443a  ldr r0, =0x6bae4                          ; arg0 = banner format
0x64440  ldr r1, =0x40c27 ("PCI")                  ; arg1
0x64444  ldr r2, =0x40c2b ("CDC")                  ; arg2
0x64446  bl  0xa30                                  ; printf — RTE BANNER (test.80 ✓)

0x6444a  ldr r3, [r5]; tst r3, #2; beq             ; gated debug print
0x64452  ldr r0, =0x40c42 ("c_init: add PCI device")
0x64456  bl  0xa30                                  ; printf (gated)

0x6445a  ldr r0, =0x58cc4 ("pciedngldev")
0x6445c  movw r1, #0x83c                            ; size? = 0x83c
0x64460  movw r2, #0x4999                           ; magic? = 0x4999
0x64464  bl  0x63b38                                ; "register/lookup device"
0x64468  cbnz r0, 0x64474                           ; if r0!=0: skip vtable store
                                                    ; (in test.99: r0==0, fell through)
0x6446a  ldr r2, =0x58cf0                           ; vtable
0x6446c  ldr r3, =0x62a14                           ; storage slot
0x6446e  str r2, [r3]                               ; *0x62a14 = 0x58cf0  (test.99 ✓)
0x64470  ldr r6, =0x58cc4 ("pciedngldev")           ; r6 = name marker
0x64472  b   0x64476
0x64474  movs r6, #0                                ; (alt path: r6 = 0)

0x64476  mov r0, r4
0x64478  bl  0x673cc                                ; <-- returns CONST 0x43b1
                                                    ;   (fn 0x673cc body is just
                                                    ;    movw r0,#0x43b1; bx lr —
                                                    ;    NOT the counter writer)
0x6447c..8a  r7 = (r0==0xffff) ? 0x4318 : r0       ; r7 = 0x43b1

0x6448c  ldr r3, [r5]; tst r3, #2; beq             ; gated print
0x64494  ldr r0, =0x40c61 ("add WL device 0x%x")
0x6449a  bl  0xa30                                  ; gated; never observed

0x6449e  mov r2, r7                                 ; arg2 = 0x43b1 (WL dev id)
0x644a0  ldr r0, =0x58ef0 ("wl")
0x644a2  movw r1, #0x812
0x644a6  bl  0x63b38                                ; second device register/lookup
                                                    ; (for "wl" device)
0x644aa  ldr r7, =0x58ef0 ("wl"); cmp r0,#0; ite ne; movne r7,#0
                                                    ; r7 = 0 if r0!=0 else "wl"

0x644b2  cbnz r6, 0x644be                           ; r6!=0 in our path → skip
0x644b4  ldr r0, ="rtecdc.c"; bl 0x11e8 (assert)
0x644be  cbnz r7, 0x644ca
0x644c0  ldr r0, ="rtecdc.c"; bl 0x11e8 (assert)

0x644ca  cmp r6,#0; beq 0x6452e (exit)
0x644ce  cmp r7,#0; beq 0x6452e (exit)
                                                    ; need both r6 and r7 non-zero
                                                    ; to reach the dispatch chain

0x644d2  ldr r3, =0x62a14
0x644d4  mov r0, r6                                 ; arg0
0x644d6  mov r1, r7                                 ; arg1
0x644d8  ldr r3, [r3]                               ; r3 = *0x62a14 = 0x58cf0
0x644da  ldr r3, [r3, #4]                          ; r3 = *(0x58cf0+4) = 0x1fc3 (Thumb)
0x644dc  blx r3                                     ; <-- INDIRECT CALL to 0x1fc2

0x644de  cmp r0,#0; bge ...                         ; check return
0x644e2  ldr r3, [r5]; tst r3, #1; beq             ; gated print
0x644ea  ldr r0, =("device binddev failed")
0x644f2  bl  0xa30                                  ; gated; never observed

0x644f6  ldr r3, [r6, #0x10]; r0 = r6              ; r6's vtable at +0x10
0x644fa  ldr r3, [r3, #4]                          ; method at +4
0x644fc  blx r3                                     ; <-- INDIRECT CALL via r6
0x644fe  cbz r0, 0x64514                            ; if r0==0, skip
... (similar pattern: device open call, gated failure print)

0x64514  ldr r3, [r7, #0x10]                       ; r7's vtable at +0x10
0x6451a  blx r3                                     ; <-- INDIRECT CALL via r7
... (third device call, third gated failure print)

0x6452e  mov r0, r4
0x64530  add sp, #0x44
0x64532  pop.w {r4-r11, pc}                        <-- function return
```

## Vtable at TCM 0x58cf0

```
+0x00: 0x00000000  (null)
+0x04: 0x00001fc3  (Thumb code → 0x1fc2)  ← called by blx r3 at 0x644dc
+0x08: 0x00001fb5  (Thumb code → 0x1fb4)
+0x0c: 0x00001f79  (Thumb code → 0x1f78)
+0x10..+0x1c: 0
```

## Corrections to prior understanding

| Prior claim | Actual finding |
|-------------|----------------|
| "fn 0x673cc writes counter 0x43b1 to *0x9d000" | **WRONG.** fn 0x673cc is `movw r0,#0x43b1; bx lr` — it just RETURNS the constant 0x43b1 (the WL device ID). The counter 0x43b1 at *0x9d000 must be written elsewhere — likely in 0x63b38 or a sub-call. |
| "Freeze is between vtable store and WL print" | The WL print is gated by `tst r3,#2`. Its absence may be debug-flag, not freeze. |
| "Pool order tells the story" | Confirmed by disassembly, but advisor was correct that this is post-hoc justification. |
| Body size 322 bytes | Actually **578 bytes** (0x242). |
| "fn 0x63b38 returned NULL → fall-through" | **WRONG.** fn 0x63b38 returns 0 = SUCCESS (writes struct[+0x18]), -1 = FAILURE. The cbnz at 0x64468 SKIPS the vtable store on FAILURE. Test.99 saw vtable stored → pciedngldev call SUCCEEDED. |
| "In binary, pciedngldev[+0x18] = 0" | **WRONG context.** That field is a RUNTIME slot (set by fn 0x63b38 success path). At runtime in test.99 it should be NON-ZERO since vtable was stored. |

## Remaining freeze candidates

In execution order, BLs that ALWAYS execute past the vtable store:

1. `0x64478 bl 0x673cc`              — eliminated (2-insn const return)
2. `0x644a6 bl 0x63b38` ("wl" device) — possible
3. `0x644dc blx 0x1fc2` (vtable +4) — possible — needs disasm of 0x1fc2
4. `0x644fc blx via r6.[0x10]+4`     — possible (only if r6/r7 path taken)
5. `0x6451a blx via r7.[0x10]+4`     — possible (same gate)

## Further tracing (round 2)

### Struct schemas reverse-engineered

The "strings" at 0x58cc4 ("pciedngldev") and 0x58ef0 ("wl") are actually
struct headers whose first field is the name. Layout:

```
pciedngldev_struct @ 0x58cc4:        wl_struct @ 0x58ef0:
  +0x00  name "pciedngldev\0"          +0x00  name "wl\0"
  +0x10  ptr 0x58c9c                   +0x10  ptr 0x58f1c (-> ops table)
  +0x14..0x2c  zero                    +0x14  0
                                       +0x18  0   <-- *0x58f08 (test.99 read; 0)
  +0x2c  vtable=0 (in binary)          +0x1c..  zero
  +0x30  fn 0x1fc3                     +0x10  ptr to ops:
  +0x34  fn 0x1fb5                       0x58f1c: 0x67615 (fn ptr)
  +0x38  fn 0x1f79                       0x58f20..28: more fn ptrs
```

So `*0x58f08 = 0` (D11 obj never linked) is actually a field of the wl
device descriptor at offset +0x18. This field is meant to be set by some
later step; observing it as 0 means that step never ran.

### fn 0x1fc2 (vtable +4 method on pciedngldev) — TAIL CALL

```
0x1fc2:  mov r2, r1                  ; arg2 = wl_struct
0x1fc4:  ldr r1, [r0, #0x18]         ; r1 = pciedngldev[+0x18]
0x1fc6:  mov r3, r0                  ; r3 = pciedngldev (save)
0x1fc8:  ldr r0, [r1, #0x14]         ; r0 = pciedngldev[+0x18][+0x14]
0x1fca:  mov r1, r3                  ; r1 = pciedngldev
0x1fcc:  b.w 0x2208                  ; <-- TAIL JUMP to fn 0x2208
```

At runtime, pciedngldev[+0x18] should be set by fn 0x63b38's success path
(see fn 0x63b38 disasm below). If so, fn 0x1fc2 dereferences a valid ptr.

### fn 0x2208 = dngl_binddev

Confirmed by debug print pool entry: `*0x2334 = 0x408d5 = "dngl_binddev"`.

Function does:
- print "dngl_binddev:" debug (if flag set)
- if `r4[+0x38]==0 && r4[+0x3c]==0`: bind: `r4[+0x38]=r6; r4[+0x3c]=r5;
  r6[+0x24]=r5; r5[+0x24]=r6` — two-way link
- else: scan an array `r4[+0x40]` for matching entries

NOTE: dispatch chain reachability is INFERRED, not observed. Test.99
execution evidence stops at the vtable store at 0x6446e. Anything past
that — including whether the wl bl 0x63b38 call even ran — is unverified.

### fn 0x63b38 — register/lookup device (FULLY DECODED)

```
fn 0x63b38(r0=struct, r1=size, r2=magic) -> int (0=ok, -1=fail)
  cmp r1, #0x700
  push {r0,r1,r4,r5,r6,lr}
  mov r4=r0; r6=r1; r5=r2
  bne 0x63b5c                      ; r1 != 0x700 → alt path

  ; r1 == 0x700 path (NEITHER call uses this — pcied=0x83c, wl=0x812):
  ldr r3, [r0,#0x10]                ; r3 = struct[+0x10] (ops table ptr)
  movs r1=0; r2=0
  ldr r6, [r3]                      ; r6 = first fn in ops table
  blx r6                            ; call ops[0](r0=struct, ..., r3=magic)
  cbnz r0, 0x63b7c                  ; r0!=0 → SUCCESS path
  subs r0,#1; b 0x63b90             ; return -1

0x63b5c:                            ; r1 != 0x700 path (BOTH calls use this)
  ldr r3, =0x6296c                  ; pool literal: global ptr
  ldr r0, [r3]                      ; r0 = *0x6296c (some context obj)
  bl  0x9990                        ; <-- alloc-ish; returns ptr or 0
  mov r1, r0
  cbz r0, 0x63b8c                   ; if alloc==0 → return -1
  ldr r3, [r4,#0x10]                ; r3 = struct[+0x10] (ops table)
  movs r2=0
  ldr r6, [r3]; mov r3=r5
  blx r6                            ; call ops[0](r0=struct, r1=alloc, r2=0, r3=magic)
  cbz r0, 0x63b8c                   ; if r0==0 → return -1

0x63b7c:                            ; SUCCESS (both branches converge)
  ldr r3, =0x62970                  ; list-head ptr
  str r0, [r4,#0x18]                ; struct[+0x18] = device handle (NON-ZERO)
  movs r0, #0                       ; return value = 0
  str r5, [r4,#0x14]                ; struct[+0x14] = magic
  ldr r2, [r3]; str r2, [r4,#0x20]  ; struct[+0x20] = old list head
  str r4, [r3]                      ; *0x62970 = struct (push to list)
  b 0x63b90

0x63b8c: mov.w r0, #-1
0x63b90: pop {r2,r3,r4,r5,r6,pc}
```

Implications:
- BOTH c_init calls (pcied size=0x83c, wl size=0x812) take the **alt path
  → bl 0x9990** (which calls bl 0x27ec — likely malloc/alloc).
- SUCCESS (r0=0) iff: bl 0x9990 returns non-zero AND ops[0](...) returns
  non-zero. On success, struct[+0x18] gets the alloc result.
- pciedngldev call returned 0 (we observed vtable store).
- wl_struct[+0x18] @ TCM 0x58f08 = 0 in test.99. Consistent with: wl
  call NEVER ran, OR wl call entered fn 0x63b38 but froze before the
  str at 0x63b7e (e.g. inside bl 0x9990 / bl 0x27ec / inside ops[0]).
- The c_init code at 0x644be `cbnz r7, 0x644ca` would assert if wl
  failed (r7=0). No assert string seen → either (a) wl call hung before
  returning, or (b) we never got that far. Pure failure return is unlikely.

## Open questions

1. Where is *0x9d000 = 0x43b1 written? Not by fn 0x673cc (just returns
   constant). Not by literal-pool LDR (no aligned ref to 0x9d000).
   Likely written via base-register addressing in some init helper that
   ran BEFORE T+200ms. Identity of the value (WL device ID 0x43b1) is
   suggestive but not proof of writer.
2. fn 0x9990 → fn 0x27ec — likely a memory pool allocator. Worth disasm
   to see if it can hang (e.g., on a counted-loop scan).
3. Is the freeze inside fn 0x9990/0x27ec for the wl call (size=0x812
   alloc), or further down the chain?

## Working hypothesis (low-confidence past step 2)

c_init sequence on this hardware:
1. RTE banner printed ✓ (test.80 console capture)
2. pciedngldev fn 0x63b38 returned 0 (success) → vtable stored at
   *0x62a14 = 0x58cf0 ✓ (test.99 probe)
3. (INFERRED past here)
4. WL device ID 0x43b1 returned by fn 0x673cc (constant return)
5. wl fn 0x63b38 — STATUS UNKNOWN. Either (a) freeze before reaching
   it, (b) freeze inside it (most likely candidate: bl 0x9990 alloc), or
   (c) successful but somehow didn't write +0x18 (unlikely per disasm).
6. If wl path completed, dispatch chain c_init→fn 0x1fc2→fn 0x2208
   (dngl_binddev) would run, but no evidence either way.
