# Offline disasm: r0 setup for `bl #0x1415c` at 0x6831c (inside fn 0x6820c)

Scope: backward trace of r0 at the BL row-14 call site (0x6831c) in fn 0x6820c.
Firmware: `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, SHA unchanged
from prior notes). Tool: capstone 5.0.7 Thumb-2.

Date: 2026-04-17. Follow-up to `offline_disasm_6820c.md` and
`offline_disasm_1415c.md`.

---

## 1. Answer summary

- **r0 at BL 0x6831c = r4 (callee-saved register of fn 0x6820c).**
- **r4 was set at 0x6825c from the return value of `bl #0x68cd2`** (first body
  call at 0x68258). Semantically this is the pointer to the freshly
  allocated/initialised "PHY/MAC-core" struct.
- **No stack spill of r0 or r4 inside fn 0x6820c's own frame.** Between
  0x6825c and 0x6831c, r4 is held live; it is never written to `[sp, #imm]`.
- **But the struct pointer IS mirrored to two locations the kernel can read:**
  - **`[r5 + 0x10]`** via `str r0, [r5, #0x10]` at **0x68266**, where `r5` =
    fn 0x6820c's captured arg0 = caller's `r4` (result of `bl #0x67cbc` in
    wlc_attach at 0x68b42).
  - **`[r5 + 0xc]`** via `str.w sl, [r5, #0xc]` at **0x68304** — mirror of
    `[struct + 0x88]` (the MMIO pointer itself). Populated AFTER 0x682d8
    loaded `[r4 + 0x7c]`, called 0x9990, and wrote the result into
    `[r4 + 0x88]`.
- **Fn 0x1415c's own frame carries the struct pointer on its stack** as the
  saved caller-r4 slot at **`body_SP(0x1415c) = 0x9CEC8`** (verified from
  test.104 via `offline_disasm_1415c.md`). Reading `[0x9CEC8]` while the
  CPU is parked anywhere inside fn 0x1415c yields the struct pointer with
  no kernel-side knowledge of caller_arg0 required.

---

## 2. Backward trace of r0 from 0x6831c

Disassembled 0x6820c..0x68330 (prologue + body through the BL at 0x6831c):

```
0x6820c: push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}
0x6821c: mov    r5, r0          ; *** CAPTURE caller_arg0 into r5 ***
0x68258: bl     #0x68cd2        ; alloc/init
0x6825c: mov    r4, r0          ; *** r4 = alloc'd struct ptr ***
0x6825e: cmp    r0, #0
0x68260: beq.w  #0x689ee        ; bail if alloc failed
0x68266: str    r0, [r5, #0x10] ; mirror struct ptr into [caller_arg0+0x10]
0x682d2: ldr    r0, [r4, #0x7c] ; setup for bl #0x9990
0x682d4: bl     #0x9990         ; returns MMIO sub-block base
0x682d8: str.w  r0, [r4, #0x88] ; struct->mmio = r0
0x682fe: ldr.w  sl, [r4, #0x88]
0x68302: mov    r0, r4
0x68304: str.w  sl, [r5, #0xc]  ; [caller_arg0+0xc] = MMIO ptr
0x68308: bl     #0x67f44
0x68312: ldr    r0, [r4, #0x7c]
0x68314: bl     #0x9a9c
0x68318: mov    r0, r4          ; *** r0 = r4 = struct ptr ***
0x6831a: movs   r1, #0
0x6831c: bl     #0x1415c        ; ← target call
0x68320: mov    r0, r4
```

Between 0x6825c (`mov r4, r0`) and 0x6831c (call site):
- r4 is READ (as `[r4, #X]`, or moved back into r0) at many sites, but is
  **never written**. r4 is live-held throughout.
- r5 is READ (`ldr r3, [r5]`, `str r0, [r5, #0x10]`, `str.w sl, [r5, #0xc]`)
  but also **never written**. r5 is live-held throughout.

Grep of every r4/r5 mention inside this range (capstone output):

```
0x6820c: push.w   {r4, r5, r6, r7, r8, sb, sl, fp, lr}
0x6821c: mov      r5, r0
0x68250: mov      r0, r5
0x6825c: mov      r4, r0
0x68266: str      r0, [r5, #0x10]
0x68268: str.w    sb, [r5, #0x18]
0x68280: ldr      r3, [r5]
0x68288..0x682ca: various str [r4, #off], ldr [r4, #off]  (all READ/FIELD-WRITE)
0x682d0: str      r3, [r5, #0x24]
0x682d2..0x68312: ldr/str [r4, #off]  (field accesses)
0x68304: str.w    sl, [r5, #0xc]
0x68318: mov      r0, r4          ← ARG for 0x1415c
0x68320: mov      r0, r4
0x6832a: mov      r0, r4
```

No `str r4, [sp, #imm]` and no `str r5, [sp, #imm]` in the entire body up
to 0x6831c — confirmed.

---

## 3. Ultimate origin of r0

```
wlc_attach @ 0x68a68
  ├─ 0x68b42: bl #0x67cbc   ; (struct alloc / "outer wlc_info")
  ├─ 0x68b46: mov r4, r0    ; caller's r4 = outer struct
  ├─ ... field init on [r4, ...]
  ├─ 0x68b90: bl #0x6820c   ; r0 = caller.r4 = outer struct ptr
  │                           (r0 is NOT explicitly moved before the call;
  │                            the last writer of r0 was the return of
  │                            bl #0x67cbc)
  ╎
  └─ fn 0x6820c:
       ├─ 0x6821c: mov r5, r0     ; r5 = outer struct (caller_arg0)
       ├─ 0x68258: bl #0x68cd2    ; returns ptr to INNER struct
       ├─ 0x6825c: mov r4, r0     ; r4 = inner struct
       ├─ 0x68266: str r0, [r5, #0x10]   ; outer[0x10] = inner
       ├─ 0x682d4: bl #0x9990     ; returns MMIO status page
       ├─ 0x682d8: str r0, [r4, #0x88]   ; inner[0x88] = MMIO page
       ├─ 0x68304: str sl, [r5, #0xc]    ; outer[0x0c] = MMIO page
       │
       └─ 0x6831c: bl #0x1415c    ; r0 = r4 = INNER struct
```

So the struct pointer delivered to fn 0x1415c is:

- the **return value of fn 0x68cd2**, NOT a constant literal, NOT loaded
  from MMIO, NOT read off the stack. It originates from a heap/pool
  allocation performed by fn 0x68cd2.
- held stably in **r4** (callee-saved, one of the registers pushed in the
  prologue — so caller's r4 is preserved in the push slot, and the new
  value is live in the register).

---

## 4. Frame layout of fn 0x6820c (confirmation)

```
0x6820c: push.w {r4, r5, r6, r7, r8, sb, sl, fp, lr}   ; 9 regs × 4 = 36 bytes
0x68212: sub    sp, #0x74                              ; 116 bytes locals
```

Total frame: 36 + 116 = **152 bytes**.

Relative to body_SP (= caller_SP − 152):
```
body_SP + 0x00 .. 0x73 : locals (0x74 bytes)
body_SP + 0x74 : pushed r4  (caller's r4)
body_SP + 0x78 : pushed r5  (caller's r5)
body_SP + 0x7c : pushed r6  (caller's r6)
body_SP + 0x80 : pushed r7  (caller's r7)
body_SP + 0x84 : pushed r8  (caller's r8)
body_SP + 0x88 : pushed sb
body_SP + 0x8c : pushed sl
body_SP + 0x90 : pushed fp
body_SP + 0x94 : pushed lr  (= 0x68b95 when called from wlc_attach)
                              (= caller_SP − 4)
```

The **live r4** (inner-struct pointer) is NOT written to any of these slots.
The slot at body_SP+0x74 holds the CALLER's r4 (which happens to equal the
OUTER struct pointer, NOT the inner one).

The **live r5** (outer-struct pointer / caller_arg0) is likewise not written
to the stack. Slot body_SP+0x78 holds caller's r5 (unrelated value).

---

## 5. Probe-accessible addresses (kernel-side)

### While parked INSIDE fn 0x1415c (current hypothesis)

Per `offline_disasm_1415c.md`, fn 0x1415c's own frame places the caller's
r4 at **[0x9CEC8]**. Since fn 0x6820c's live r4 == inner-struct pointer at
the BL site (0x6831c), that pushed slot IS the inner-struct pointer.

**Primary probe: read 4 bytes at 0x9CEC8 → inner struct pointer.**
- Then read `[p + 0x88]` → MMIO status page base.
- Then read `[mmio + 0x1e0]` → the register the CPU is polling.

This is the cleanest path and has no dependency on `*0x62e20`.

### Auxiliary probes (if 0x9CEC8 is already in use or gives 0)

These only apply if we know the outer-struct address (caller_arg0):

| What | Address | Available after | Value |
|------|---------|-----------------|-------|
| outer → inner mirror | `[outer + 0x10]` | 0x68266 | inner struct ptr |
| outer → MMIO mirror  | `[outer + 0xc]`  | 0x68304 | MMIO status page |

Both offsets are populated well before the BL at 0x6831c (0x68266 is the
8th body instr; 0x68304 is ~20 instructions before the BL). Safe for THIS
hang. **NOT safe** for probing from a hang upstream of 0x68266 / 0x68304 —
values will be stale or 0.

### Finding the outer-struct address

wlc_attach at **0x68bbc** stores `r4` (= outer struct) to the fixed TCM
global at **0x62e20** (literal pool entry at 0x68c80 = 0x00062e20):

```
0x68bb6: ldr  r3, [pc, #0xc8]   ; r3 = 0x00062e20
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, #0x68bbe      ; skip if already set
0x68bbc: str  r4, [r3]          ; *0x62e20 = outer struct ptr
```

**CRITICAL CAVEAT:** 0x68bbc executes AFTER `bl #0x6820c` returns. If the
hang is inside fn 0x6820c (or deeper — e.g. inside fn 0x1415c's poll loop),
`*0x62e20 == 0` and the outer-struct address is **not yet published**. So
`*0x62e20` is the team's existing "did we finish fn 0x6820c" breadcrumb
(per `offline_disasm_wl_subbls.md`), and for the current hang site it will
read 0 — i.e. the outer-struct-relative probes (`[outer+0x10]`, `[outer+0xc]`)
are NOT usable via 0x62e20 for this scenario. Use the 0x9CEC8 stack-frame
probe instead.

---

## 6. Does fn 0x6820c save its own r0 anywhere readable?

**Short answer: no, not on its own stack frame.**

Long answer:
- In-register-only: r0 (incoming) is moved to r5 at 0x6821c and lives in r5
  through the BL. r5 is NEVER spilled inside fn 0x6820c's own frame.
- In-outer-struct: via 0x68266 it is effectively visible as `(outer_struct)`
  itself — trivially, because r5 == outer_struct and we can write offset
  fields of it. There's no "address-of-r5 in memory" anywhere in fn 0x6820c.
- In fn 0x6820c's push block: body_SP+0x78 holds CALLER's r5, which is
  unrelated to the struct pointer.

Similarly r4 (the inner struct pointer post-0x6825c):
- Held in register for the entire 0x6825c..0x68a0e range.
- Written to memory ONLY via field offsets of r4 itself (e.g. `[r4, #0x7c]`,
  `[r4, #0x88]`, `[r4, #0x94]`), which ARE memory locations inside the
  inner struct but they don't contain the struct's own address.
- Written to memory via `[r5, #0x10]` at 0x68266 (outer->inner mirror).
  This IS an address-of-inner-struct record, but to read it the kernel
  must already know where outer_struct lives (see section 5 caveat).

There is no "fn 0x6820c stashed r0 at a stack offset X we could read from
the kernel by computing body_SP+X." For stack-based recovery of the inner
struct pointer, the kernel must walk INTO fn 0x1415c's frame and read
[0x9CEC8].

---

## 7. Test plan implications

1. **Primary probe (no new kernel instrumentation required if body_SP walk
   is already set up):** read 4 bytes at 0x9CEC8 → inner struct pointer
   P.
2. Read 4 bytes at `P + 0x88` → MMIO page pointer M.
3. Read 4 bytes at `M + 0x1e0` → current value of the status register the
   CPU is polling (bit 17, mask 0x20000). Low bit 17 → CPU is legitimately
   waiting; HW hang.
4. Secondary/sanity: confirm `*0x62e20 == 0` (expected if hang is upstream
   of wlc_attach 0x68bbc, which fits the "hang inside fn 0x1415c" model).

All three reads are pure memory probes — no FW re-run, no kernel module
changes.

---

## 8. One-line take-away

r0 at `bl #0x1415c` (0x6831c) is the return value of the first body call
`bl #0x68cd2` (0x68258), held in callee-saved **r4**, never stack-spilled
inside fn 0x6820c, and recoverable from the kernel by reading the saved-r4
slot of fn 0x1415c's own push frame at **[0x9CEC8]**.
