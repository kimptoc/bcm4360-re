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

## Round 3 — wl_probe is fn 0x67614 (print site anchored)

The console line "wl_probe called\n" is emitted by **`printf("%s called\n",
"wl_probe")`** with format string at `0x40692` and name at `0x4a1ea`.
Pool-table search found exactly ONE pool entry referencing `0x4a1ea`
("wl_probe"): `*0x67890 = 0x4a1ea`. The LDR-literal that reads it is at
`0x67622`, inside fn `0x67614`.

→ **fn 0x67614 IS wl_probe()**. Sample disasm of its prologue:

```
0x67614: push.w {r4-r11, lr}; sub sp,#0x24
0x6761a: r7=r0; r6=r1; r0=*0x6788c=0x40692 ("%s called\n")
         r1=*0x67890=0x4a1ea ("wl_probe"); r8=r2; fp=r3; r5=[sp,#0x4c]
0x67628: bl 0xa30                  ; printf "wl_probe called"  <-- VISIBLE
0x6762e: r0=0; r1=0xb0
0x67630: bl 0x7d60                 ; alloc(0xb0=176B) -> r4 (wl ctx)
0x67636: cbnz r0, 0x6765e          ; if alloc OK -> continue
         ; else: print "wl_attach failed" + return
0x6765e..0x67666: memset(r4, 0, 0xb0); [r4]=r5 (parent ptr)
0x67668: bl 0x66e64                ; first sub-init
0x67672: bl 0x649a4                ; second sub-init -> r4[+0x90]
0x67676: cbnz r0,0x6769c           ; if non-zero: continue
         ; else: print "wl%d: %s wl_attach failed" + return
0x676a0: bl 0x4718                 ; helper (uses 0x1148d)
0x676ae: bl 0x6491c                ; -> r4[+0x8c]
         ... continues with multi-arg call pushing 5 stack args
```

Vtable at `0x58f1c` (wl_struct[+0x10]):
```
[0x58f1c] = 0x67615   ; ops[0] = fn 0x67614 = wl_probe   <-- THE PRINTER
[0x58f20] = 0x11649   ; ops[1] = fn 0x11648 ("D11 vtable[1]" in test.96)
```

So the call chain that emits the "wl_probe called" line is:

```
c_init                                  (0x644a6)
  → fn 0x63b38(wl_struct, 0x812, 0x43b1)
    → bl 0x9990 (alloc)                 (returns OK assumed)
    → ldr r3,[r0,#0x10] → ldr r6,[r3]   ; r6 = wl_struct.ops[0] = 0x67615
    → blx r6                            ; blx fn 0x67614 = wl_probe
      → bl 0xa30 ("wl_probe called")    ; <-- LAST OBSERVED CONSOLE LINE
      → bl 0x7d60 (alloc 176B)
      → bl 0x66e64
      → bl 0x649a4
      → bl 0x4718
      → bl 0x6491c
      → ...                             ; FREEZE somewhere here
```

### What this means for the test.96 chain
Earlier test.96 traced "Call 3 = D11_obj->vtable[1] = fn 0x11648 → fn 0x18ffc
→ fn 0x16f60 → fn 0x16476 → fn 0x162fc". That chain is reachable ONLY if
wl_probe (fn 0x67614 = ops[0]) RETURNS first, then c_init runs the dispatch
calls at 0x644dc/0x644fc/0x6451a. We have NO evidence wl_probe returns. The
freeze is more parsimoniously explained by hanging INSIDE wl_probe, not in
the post-wl_probe dispatch chain. The fn 0x162fc PHY wait-loop chain must
NOT be assumed to be the actual hang location.

### What the wl_struct[+0x18] = 0 reading actually means
In test.99, `*0x58f08 = wl_struct[+0x18] = 0`. fn 0x63b38's success path
writes struct[+0x18] AT THE END (post-blx ops[0]). So wl_struct[+0x18] = 0
is consistent with ops[0]=wl_probe never returning — i.e., wl_probe hung
mid-body. It does NOT mean ops[0] was never called: the console proves it
was, since we got "wl_probe called".

### Open subroutines (in wl_probe, after the visible printf)
| BL | Target | Returns into | Likely role |
|----|--------|--------------|-------------|
| 0x67630 | 0x7d60   | r4 (=wl ctx malloc) | malloc(0xb0) — well-tested earlier |
| 0x67668 | 0x66e64  | (no save observed) | early sub-init |
| 0x67672 | 0x649a4  | r4[+0x90] | sub-init returning a handle |
| 0x676a0 | 0x4718   | — (uses r2=0x1148d ptr) | list/registry helper |
| 0x676ae | 0x6491c  | r4[+0x8c] | another sub-init |
| 0x67700 | 0x68a68  | r6 (-> 0x67730) | **5-stack-arg + 4-reg-arg call — REACHES PHY WAIT** |

### Round 4 — call-graph BFS pinpoints freeze chain (D11 PHY wait, via wl_probe)

Brute-force callgraph BFS (depth ≤ 4) from each wl_probe sub-fn:

| Sub-fn | Reaches D11 PHY chain? |
|--------|------------------------|
| fn 0x66e64 | NO (visited 17 fns) |
| fn 0x649a4 | NO (visited 19 fns) |
| fn 0x4718  | NO (visited 1 fn) |
| fn 0x6491c | NO (visited 44 fns) |
| fn 0x14288 | NO (visited 1 fn) |
| fn 0x79c   | NO (visited 1 fn) |
| **fn 0x68a68** | **YES** (3 hits) |

The exact path:

```
wl_probe @ 0x67614
 → bl 0x68a68 @ 0x67700                  (BIG: 5 stack args + 4 reg args)
   → bl 0x1ab50 @ 0x68bcc
     → bl 0x16476 @ 0x1ad2e               (PHY register access wrapper)
       → b.w 0x162fc                       (PHY-completion wrapper)
         → bl 0x1624c @ 0x1632e            (SPIN WAIT — same as test.96)
                                            ; while ws->field20==1 && ws->field28==0
```

`fn 0x68a68` is called from EXACTLY ONE site — wl_probe at 0x67700 — so this
is the unique entry to that subtree. The freeze fingerprint is identical to
the test.96 chain (D11 PHY ISR never fires → field28 stays 0). Now we have
the correct call path leading there: NOT via c_init's Call 3 (0x6451a), but
via wl_probe → fn 0x68a68 → fn 0x1ab50.

### fn 0x162fc verified as PHY wait wrapper

```
0x162fc: push {r3..r7,lr}
0x162fe: r3 = r0[+0x10a] (init flag); r4=r0; r5=r1; r7=r2
0x16308: r6 = r0[+0x88]               ; HARDWARE BASE? sub-struct (D11 wrapper)
0x1630c: cbnz r3, 0x16318             ; if not init, assert "wlc_bmac.c"
0x1632c: r0 = *r4                     ; load wait struct
0x1632e: bl 0x1624c                   ; SPIN WAIT for completion (same as test.96)
0x16332: r6[+0x160] = r7              ; trigger reg
0x16336: tst r5,#2 ...
0x16340: r5 = r6[+0x166]  or  r6[+0x164]   ; result reg
0x1634c: bl 0x1428c                   ; ?
0x16352: pop, return r5
```

fn 0x162fc's purpose is "trigger D11 PHY operation via r6=r0[+0x88], wait for
completion, read result". The hang is inside its bl 0x1624c.

### Implication for test.100

The freeze is the D11 PHY wait loop. Two test paths possible:

(a) **Cheap confirmation probe** — sample wait-struct fields at T+200ms:
    - addr = *0x62ea8 = 0x9d0a4 (already confirmed in test.99)
    - field20 = TCM[0x9d0a4 + 0x14]
    - field24 = TCM[0x9d0a4 + 0x18]
    - field28 = TCM[0x9d0a4 + 0x1c]
    - If field20==1 AND field28==0 → CONFIRMS PHY-wait hang fingerprint.
    - If field20!=1 → freeze elsewhere (some other use of *0x62ea8).
    - This is read-only TCM probes only — same risk profile as test.99.

(b) **D11 BCMA wrapper bring-up** (Path B step 1) — heavier scaffolding
    in chip.c bus-ops; requires writing to D11 IOCTL/RESET_CTL pre-ARM to
    enable the D11 core BEFORE wl_probe runs.

Recommend (a) first — single hardware cycle, trivial to implement, decides
between two distinct hypotheses. (b) is the next step IF (a) confirms PHY
wait.
