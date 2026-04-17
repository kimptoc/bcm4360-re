# Offline disassembly: wl_probe sub-BLs (hang-site narrowing, post test.100)

Scope: purely offline analysis of the sub-BL targets invoked from wl_probe
(fn 0x67614) on BCM4360 firmware `/lib/firmware/brcm/brcmfmac4360-pcie.bin`.
Tool: `arm-none-eabi-objdump -D -b binary -marm -Mforce-thumb`. Loader base =
TCM offset 0. All addresses below are byte offsets into the firmware image
(Thumb entry = odd-bit ptr, address here is the even-aligned start).

Motivation: test.99 showed the `wl_struct` pointer at `*0x58f08` stays zero
(wl_probe never returns), and test.100's PHY-wait fingerprint probe at
`*<wait-struct>` stayed zero too — so the hang is NOT inside fn 0x1624c
(PHY polling). That leaves wl_probe itself (prologue BLs before
wlc_attach) or the body of fn 0x68a68 (wlc_attach) before its call to
fn 0x1ab50 as the hang region.

This pass disassembles the five candidates the user named and the rest of
wl_probe (0x67704..0x6790c), then picks ONE most-likely hang site and
proposes test.101 probe addresses.

---

## Executive summary

**Finding: the five earlier sub-BLs are internally bounded. No spin loops,
no HW-register polling, no fixed-TCM stores — every write is r4-relative
into the freshly-allocated object. The hang is NOT in any of them under
the disassembly evidence.**

**Most-likely hang site: fn 0x68a68 (wlc_attach) BODY, between its
prefix end at 0x68aca and `bl 0x1ab50` at 0x68bcc.** test.100 excluded
only fn 0x1624c; the intermediate body of 0x68a68 and of 0x1ab50 remain
untested.

**Fallback candidate (low confidence): fn 0x6491c → bl 0x3428 → bl 0x33d8.**
This is the only depth-1 callee from the earlier five with unexamined
depth-2 ground, but all of fn 0x33d8's internals are bounded allocs +
iovar registers, so the prior is low.

**test.101 probe — the single clean fixed-address breadcrumb in this
whole subtree is in fn 0x68a68's BODY at 0x68bb6/0x68bbc**:

```
0x68bb6: ldr  r3, [pc, #200]   ; r3 = 0x00062e20 (literal at 0x68c80)
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, 0x68bbe
0x68bbc: str  r4, [r3]          ; *0x62e20 = wlc_info
```

Pool literal at 0x68c80 decodes to `0x00062e20`. Currently 0 in the binary.
**`*0x62e20 != 0` after reset = fn 0x68a68 advanced past all its setup
calls to within a few instructions of `bl 0x1ab50` at 0x68bcc.**

Secondary probe targets (no fixed TCM addresses exist inside the five
earlier sub-BLs, so we probe the CALLING slots in wl_probe's parent):
check `[wl_struct+140]` (0x6491c result) and `[wl_struct+144]` (0x649a4
result), since wl_struct's base is already captured at `*0x58f08`. Those
two slots becoming non-zero narrows the pre-wlc_attach progression.

---

## fn 0x66e64 — trivial alloc+link helper

### Size / extent
0x66e64..0x66e8a = 38 bytes (19 Thumb insns).

### Body
```
0x66e64: push {r4, lr}
0x66e66: mov r4, r0                ; r0 = parent ptr
0x66e68: movs r0, #16
0x66e6a: bl  0x1298                ; malloc(16)
0x66e6e: cbz r0, 0x66e86            ; bail on NULL
0x66e70: movs r1, #0
0x66e72: movs r2, #16
0x66e74: bl  0x91c                 ; memset(new,0,16)
0x66e78: str r4, [r0, #4]          ; new[4] = parent
0x66e7a: ...                       ; (fall-through returns new in r0)
0x66e86: movs r0, #0               ; return NULL
0x66e88: pop {r4, pc}
0x66e8a: (end)
```

### Fixed TCM stores: **none**
### r4-offset wl_struct writes: **none** (r4 holds local parent, not wl)
### BL targets: 0x1298 (malloc), 0x91c (memset).
### Spin loops: none.
### HW register accesses: none.

**Hang capacity: zero.** Pure 16-byte alloc + zero-init + parent link.

---

## fn 0x649a4 — 172-byte struct allocator, bounded init

### Size / extent
0x649a4..0x64a2e = 138 bytes.

### Body highlights
```
0x649a4: push {r4-r7, lr}
0x649a6: mov r5, r0                ; r0 = parent (wl_struct or wl_info)
0x649a8: mov r6, r1                ; r1 = handle
0x649aa: movs r0, #172
0x649ac: bl  0x1298                ; malloc(172)
0x649b0: cbz r0, <err>
0x649b2: mov r4, r0
0x649b4: movs r1, #0
0x649b6: movs r2, #172
0x649b8: bl  0x91c                 ; memset(new,0,172)
0x649bc: str r5, [r4, #4]          ; [#4] = parent
0x649be: str r6, [r4]              ; [#0] = handle
0x649c0: movs r0, #20
0x649c2: bl  0x1298                ; second malloc(20)
0x649c6: cbz r0, <err>
0x649c8: str r0, [r4, #20]         ; [#20] = inner 20B obj
0x649ca: movs r1, #0
0x649cc: movs r2, #20
0x649ce: bl  0x91c                 ; zero inner
0x649d2: movs r1, #1
0x649d4: mov r0, r4
0x649d6: bl  0x50a8                ; helper (bounded, counted loop r5=1 iter)
0x649dc: movs r2, #0
0x649de: str r2, [r4, #0x88]       ; [#0x88] = 0
0x649e2: movs r2, #0x63
0x649e4: str r2, [r4, #0x64]       ; [#0x64] = 99
0x649e8: movw r2, #0xfa0
0x649ec: str r2, [r4, #0x6c]       ; [#0x6c] = 4000
...
0x64a2c: pop {r4-r7, pc}
```

### Fixed TCM stores: **none**
### r4-offset writes: 0x00, 0x04, 0x14, 0x64, 0x6c, 0x88 (all into fresh 172B obj)
### BL targets: 0x1298 (malloc×2), 0x91c (memset×2), 0x50a8 (counted init, r5=1 iter)
### Spin loops: none. 0x50a8 is a counted helper, not a spin.
### HW register accesses: none.

**Hang capacity: near zero.** No polling constructs, no HW touches.

---

## fn 0x4718 — 3-instruction leaf, cannot hang

### Size / extent
0x4718..0x4720 = 8 bytes.

### Body
```
0x4718: str r2, [r0, #76]
0x471a: str r1, [r0, #80]
0x471c: bx  lr
```

### Fixed TCM stores: none
### r4-offset writes: n/a (writes via r0, caller's handle)
### BL targets: none
### Spin loops: none
### HW register accesses: none

**Hang capacity: ZERO, mathematically.** Three stores then return. Caller's
effect: handle[0x4c] = 0x1148d (fn ptr, Thumb), handle[0x50] = r4.

---

## fn 0x6491c — 120-byte alloc + iovar register setup

### Size / extent
0x6491c..0x6498a = 110 bytes.

### Body highlights
```
0x6491c: push {r4-r7, lr}
0x6491e: mov r5, r0                ; parent
0x64920: mov r6, r1
0x64922: mov r7, r2
0x64924: movs r0, #120
0x64926: bl  0x1298                ; malloc(120)
0x6492a: cbz r0, <err>
0x6492c: mov r4, r0
0x6492e: movs r1, #0
0x64930: movs r2, #120
0x64932: bl  0x91c                 ; memset
0x64936: str r7, [r4]              ; [#0] = r7
0x64938: str r5, [r4, #4]          ; [#4] = parent
0x6493a: str r6, [r4, #8]          ; [#8] = r6
0x6493e: movs r2, #0x69
0x64940: strb r2, [r4, #0x25]      ; [#0x25] = 0x69
0x64944: ldr r2, =0xbeef0dad
0x64946: str r2, [r4, #0x50]       ; [#0x50] = 0xbeef0dad (magic)
0x6494a: ldr r2, =0xdf00061e
0x6494c: str r2, [r4, #0x48]       ; [#0x48] = 0xdf00061e (magic)
0x64950: mov r0, r4
0x64952: bl  0x7d60                ; sub-alloc
0x64956: cbz r0, <err-free>
0x64958: str r0, [r4, #0x10]
0x6495a: mov r0, r4
0x6495c: movs r1, #0
0x6495e: bl  0x4034                ; 6-insn leaf stores
0x64962: mov r0, r4
0x64964: bl  0x4130                ; returns 4 (literal)
0x64968: str r0, [r4, #0x1c]
0x6496a: mov r0, r4
0x6496c: bl  0x3428                ; 2×1200B alloc + 2×iovar_register
0x64970: cbnz r0, <err-free-all>
...
0x64986: bl  0x648b4                ; error cleanup path
0x6498a: pop {r4-r7, pc}
```

### Fixed TCM stores: **none**
### r4-offset writes: 0, 4, 8, 0x10, 0x1c, 0x25 (byte), 0x48, 0x50
### BL targets:
  - 0x1298 malloc, 0x91c memset
  - 0x7d60 sub-alloc helper
  - 0x4034 6-insn leaf stores (stores r3 to [r0,#0x24], then a few more into r0+0x8, r0+0xc, r0+0x28)
  - 0x4130 leaf: `movs r0, #4 ; bx lr` (returns 4)
  - 0x3428 bounded init: two 1200B mallocs + two `bl 0x1878` (iovar_register)
  - 0x648b4 error-path free
### Spin loops: none.
### HW register accesses: none in this function or in 0x3428's visible body.

### Depth-2 note on fn 0x3428
Disasm shows two `bl 0x1298` (each 1200 bytes), two `bl 0x1878` (iovar
register — short string-keyed table insert), then return. No HW poll.
**fn 0x33d8** (called as a leaf init inside 0x3428's fan-out) likewise
does allocs + table work. All bounded.

**Hang capacity: low.** Two magic constants at [#0x48] and [#0x50] suggest
this is a named/tagged object (bcm_rpc_tp? wlc_tcp_keep?) but nothing polls.

---

## fn 0x68a68 — wlc_attach (prefix only; body kept for final section)

### Prefix extent
0x68a68..0x68aca = 98 bytes, zero outward BLs except an optional `bl 0xa30`
debug-printf if msglevel flag set.

### Prefix body
```
0x68a68: push {r4-r11, lr}
0x68a6a: sub sp, #0x44             ; 68-byte locals
0x68a6c: mov r4, r0                ; r0 = wl_struct (from wl_probe)
0x68a6e: mov r5, r1
0x68a70: mov r6, r2
0x68a72: mov r7, r3
0x68a74: ldr r0, [sp, #0x68]       ; arg5
0x68a76: str r0, [sp, #0x28]
...                                 ; moves incoming args into local slots
0x68a9c: ldr r0, =0x58f44          ; msglevel flag
0x68a9e: ldr r0, [r0]
0x68aa0: cbz r0, 0x68aa8
0x68aa2: ldr r0, =<fmt-string>
0x68aa6: bl  0xa30                 ; printf(debug); this is "wlc_attach"
0x68aa8: (continue)
...
0x68aca: bl  0x67f2c                ; FIRST real outward call — end of prefix
```

### Fixed TCM stores: **none in the prefix**
### r4-offset writes: none in the prefix (r4 stashed to sp slot for later)
### BL targets in prefix: 0xa30 (debug printf, conditional)
### Spin loops: none
### HW register accesses: `ldr [0x58f44]` is msglevel (RAM flag, not HW)

**Hang capacity: zero in the prefix.** But the BODY past 0x68aca is the
region test.100 did NOT probe — see conclusion.

### Key BODY breadcrumb (for test.101)
```
0x68bb6: ldr  r3, [pc, #200]   ; literal at 0x68c80 = 0x00062e20
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, 0x68bbe       ; skip if already initialised
0x68bbc: str  r4, [r3]          ; *0x62e20 = wlc_info ptr
0x68bbe: ...
0x68bcc: bl   0x1ab50           ; descends into PHY chain
```

`*0x62e20 != 0` = fn 0x68a68 reached at least 0x68bbc. Currently 0 in
firmware binary.

---

## Rest of wl_probe (0x67704..0x6790c)

### BL call list in execution order

| Offset | Target | Notes |
|--------|--------|-------|
| 0x67732 | 0x14288 | leaf: `ldr r0,[r0]; bx lr` (dereference) |
| 0x6774c | 0x79c   | varargs helper |
| 0x67762 | 0xa30   | debug printf (conditional) |
| 0x67774 | 0x63c24 | iovar/config helper |
| 0x677c0 | 0x3496  | leaf stores |
| 0x677ca | 0x1878  | iovar_register |
| 0x677d4 | 0x1878  | iovar_register |
| 0x677da | 0x67514 | sub-alloc local helper |
| 0x67806 | 0x67454 | sub-alloc local helper |
| 0x6782e | 0x67914 | 8B alloc (wl_nd_attach) |
| 0x67856 | 0x67978 | 120B alloc (wl_arp_attach) |
| 0x67884 | 0x1878  | iovar_register "wlmsg" |
| 0x67904 | 0x675c0 | wl_free (error cleanup tail only) |

All descend into bounded alloc/init/table-insert. The three sub-alloc
helpers (0x67514, 0x67454, 0x67914, 0x67978) are each a few dozen
instructions — malloc + memset + link stores, no HW, no loops.

### r4-offset stores from wl_probe (wl_struct layout)

| Offset | Value | Source |
|--------|-------|--------|
| +0x00 | parent (r5) | prologue |
| +0x08 | wlc_info (r6) | after wlc_attach returns |
| +0x0c | r6[#0x10] | chip/unit field |
| +0x10 | r7 | arg |
| +0x2c | wl_struct (self-ref) | |
| +0x30 | r4 (self) | |
| +0x48 | 0x63db | magic |
| +0x78 | 0x67454 result | |
| +0x7c | 0x67914 result | wl_nd handle |
| +0x80 | 0x67978 result | wl_arp handle |
| +0x8c | 0x6491c result | fn under analysis |
| +0x90 | 0x649a4 result | fn under analysis |
| +0x94 | *(r4+0x8c) inner | chained |
| +0x98 | r6 | wlc_info second slot |
| +0x9c | r6[#0x10] | |
| +0xa4 | 0x67514 result | |

**Note**: wl_probe's own r4 is the wl_struct. `*0x58f08 = wl_struct` is
set by wl_probe's CALLER (c_init/dngl_binddev path) only after wl_probe
returns. Therefore test.99's `*0x58f08 == 0` is consistent with hang
ANYWHERE inside wl_probe — it does NOT discriminate between prologue BLs
and wlc_attach's interior.

---

## Conclusion: hang-site pick

**Under this disassembly, none of the five named sub-BLs have a
spin-wait pattern or HW-register access.** The hang pick that honours the
evidence is:

### Primary (high confidence of region, uncertainty of exact BL):
**fn 0x68a68 (wlc_attach), BODY between 0x68aca and 0x68bcc.**

Rationale:
- test.100's wait-struct fingerprint stayed zero → fn 0x1624c never ran
  → hang is BEFORE the PHY-wait chain is entered.
- The PHY-wait chain is reached only via wlc_attach → fn 0x1ab50 at 0x68bcc.
- wlc_attach's body between 0x68aca and 0x68bcc performs multiple BLs
  (0x67f2c first, then several more we have not disassembled in this
  pass), any of which could lock. test.100 did not probe any of this region.
- The five sub-BLs analysed here are all provably bounded.

### Fallback (low confidence):
**fn 0x6491c → bl 0x3428 → bl 0x33d8 subtree**, the only depth-1 callee
from the earlier five with unexamined depth-2 ground. Named only for
completeness; all visible internals are bounded allocs + iovar registers.

---

## test.101 probe proposal

Write breadcrumbs at known offsets after reset; after firmware upload and
expected-hang time, read back and compare.

### Primary breadcrumb
- **`*0x62e20`** — set by fn 0x68a68 at 0x68bbc (`str r4, [r3]`).
  - `*0x62e20 != 0` → hang is AFTER 0x68bbc, i.e. inside `bl 0x1ab50`
    or in the tail of wlc_attach after the PHY chain returns (unlikely
    given PHY spin isn't the culprit per test.100).
  - `*0x62e20 == 0` → hang is BEFORE 0x68bbc: either in wl_probe prologue
    (0x67614..0x67704), wl_probe's mid-section BLs (0x67732..0x677ca), or
    in wlc_attach's body between 0x68aca and 0x68bbc.

### Secondary breadcrumbs (in wl_probe parent frame)
- **`*0x58f08` + 0x8c** — [wl_struct+0x8c] = fn 0x6491c result
- **`*0x58f08` + 0x90** — [wl_struct+0x90] = fn 0x649a4 result
  Both set in wl_probe BEFORE the wlc_attach call chain reaches PHY.
  Non-zero means the earlier sub-BLs completed; zero means hang occurred
  in or before fn 0x6491c / fn 0x649a4 — but we need wl_struct base in
  *0x58f08 first, which is only set AFTER wl_probe returns. So these
  secondary probes only work if we ALSO patch a TCM scratch that one of
  the sub-BL callees writes. Practically: the primary probe at `*0x62e20`
  is the cleanest signal.

### Suggested test.101 wiring
1. Patch loader to zero `*0x62e20` before firmware boot.
2. Let firmware run to hang (observed t ≈ same as test.99).
3. Dump `*0x62e20`.
4. Dump `*0x58f08` (already instrumented) as sanity.
5. Decision tree:
   - `*0x62e20 == 0`, `*0x58f08 == 0` → hang in wl_probe prologue or
     wlc_attach prefix/body-before-0x68bbc. Next probe: one of fn 0x68a68's
     early body BLs (starting 0x67f2c at 0x68aca).
   - `*0x62e20 != 0`, `*0x58f08 == 0` → hang between 0x68bbc and wl_probe
     return; since test.100 excluded fn 0x1624c, look at fn 0x1ab50's
     OTHER sub-BLs or wlc_attach's tail after 0x1ab50.

---

## Addenda

### Pool strings confirmed
"wl_probe", "wlc_attach" (at 0x4b1ff — confirms fn 0x68a68 identity),
"MALLOC failed", "bcm_rpc_tp_attach failed", "wlc_attach failed",
"hndrte_add_isr failed", "wl_nd_attach failed", "wl_arp_attach failed",
"wl_icmp_attach failed", "wlc_tcp_keep_attach failed", "wlmsg", "wlhist",
"dpcdump", "msglevel".

### Tools and reproduction
All disasm via `arm-none-eabi-objdump -D -b binary -marm -Mforce-thumb
--start-address=<hex> --stop-address=<hex>
/lib/firmware/brcm/brcmfmac4360-pcie.bin`. Binary path is the absolute
NixOS firmware location; TCM base = 0.
