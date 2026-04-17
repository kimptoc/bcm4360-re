# Offline disassembly: fn 0x68a68 body (post test.101)

Scope: disassembly of fn 0x68a68 (wlc_attach) body 0x68a68..0x68bcc, and
each of its 6 body BL targets (first-level only). Done 2026-04-17 after
test.101 showed breadcrumb `*0x62e20 == 0` (Case 0, hang upstream of 0x68bbc).

Tool: capstone via nix-shell (`python3Packages.capstone`, script -qc wrapper
to work around nix-shell --run output swallowing).

## Executive summary

**Primary finding:** fn 0x68a68's first body BL — `bl 0x67f2c` at 0x68aca —
is a 4-instruction trampoline that TAIL-CALLS to `0x67358`:
```
0x67f2c: push {r4, lr}
0x67f2e: ldr  r4, [sp, #0x10]   ; load arg4
0x67f30: pop.w {r4, lr}           ; restores r4, lr
0x67f34: b.w  0x67358              ; tail call
```

`0x67358` is the SAME deep-init routine previously traced from pciedngl_probe
(via test.87/88/90/91): 0x67358 → 0x670d8 → 0x64590 (si_attach) → vtable
dispatches (Call 1 = 0x1FC2→0x2208 = dngl_binddev; Call 2 = 0x1C74 = trivial;
Call 3 = 0x11648 → 0x18ffc → 0x16f60 → 0x1ab50 → 0x1624c). test.100 proved
fn 0x1624c NEVER ran, so hang is somewhere in this descent.

**Therefore the Case 0 breadcrumb result (hang upstream of 0x68bbc) is
consistent with hang inside the 0x67f2c→0x67358 chain (si_attach descent)
rather than upstream in wl_probe's earlier sub-BLs.**

**No fixed-TCM breadcrumbs exist in fn 0x68a68 body.** All stores in the
body are sp/r0/r3/r4/sl-relative (stack and freshly-allocated object fields).
The only fixed-TCM store is at 0x68bbc (the one we already have).

## fn 0x68a68 body: 6 BL candidates (in execution order)

| Addr | BL target | First-pass analysis | Hang capacity |
|------|-----------|---------------------|---------------|
| 0x68aca | 0x67f2c | 4-insn trampoline → b.w 0x67358 (si_attach descent) | HIGH — deep descent, known to reach unreached region |
| 0x68b02 | 0x5250 | nvram_get() — known safe (test.96 binary analysis) | ZERO |
| 0x68b0c | 0x50e8 | strtoul()-like string parser (bounded, backward branches are BOUNDED loops — iterate over chars of input) | NEAR-ZERO |
| 0x68b42 | 0x67cbc | bounded: 3× bl 0x12c20 (malloc), field init, backward-b branches are error-path merges (not spin) | LOW |
| 0x68b90 | 0x6820c | calls 0x68cd2, 0x142e0, fn 0x191dc, 0x9990, 0x9964 — not yet fully traced | MEDIUM |
| 0x68ba0 | 0x191dc | chip-id dispatcher: `cmp r0, #0xXXX; beq default` pattern, 16+ IDs; returns without loops | ZERO |

## Control flow of body

```
0x68aca: bl 0x67f2c  (tail→0x67358)           ← if hangs here, never returns
0x68ace: mov r8, r0
0x68ad0: cbnz r0, 0x68afc   ; if nonzero (success), goto mid
0x68ad2-0x68af8: if zero: log + set err field, branch to end
0x68afc: ldr r0, [sp, #0x30]
0x68afe: cbz r0, 0x68b3a
0x68b00: ldr r1, [pc, ...] ; nvram key string
0x68b02: bl 0x5250          ; nvram_get
0x68b06: cbz r0, 0x68b3a
0x68b08-0x68b0a: zero r1, r2
0x68b0c: bl 0x50e8          ; strtoul parse
0x68b10+: stash result, log
0x68b38: mov r6, r4
0x68b3a: mov r0, sb; ... setup args
0x68b42: bl 0x67cbc         ; struct setup
0x68b46: mov r4, r0
0x68b48: cmp r0, #0; beq 0x68bfe  ; if alloc failed, bail
0x68b4c-0x68b8c: populate struct fields (via r4/r3/r0/sp offsets)
0x68b90: bl 0x6820c         ; further init
0x68b94: str r0, [sp, #0x34]
0x68b96: cmp r0, #0; bne 0x68bfe ; on nonzero return, bail
0x68b9a-0x68ba0: bl 0x191dc  ; chip-id dispatch
0x68ba4-0x68bb4: compute struct field, store [r4, #0x24]
0x68bb6-0x68bbc: BREADCRUMB store *0x62e20 = r4
0x68bbe-0x68bca: small cleanup (clear *sl if sl!=0)
0x68bcc: bl 0x1ab50          ; PHY descent
```

## Verified: 16-byte gap 0x68bbc→0x68bcc

Instructions between breadcrumb store and bl 0x1ab50:
```
0x68bbc: str  r4, [r3]           ; BREADCRUMB
0x68bbe: cmp.w sl, #0
0x68bc2: beq 0x68bca
0x68bc4: movs r3, #0
0x68bc6: str.w r3, [sl]          ; clear *sl if non-null
0x68bca: mov r0, r4
0x68bcc: bl 0x1ab50
```

**No other BL in this 16-byte gap.** So "*0x62e20 != 0" and "entered bl 0x1ab50"
are equivalent within this unconditional path (advisor verify: ✓).

## Implications for test.102

Most-likely hang: **inside the bl 0x67f2c → b.w 0x67358 descent** (first body
call). This is consistent with previous hypothesis that hang is in si_attach
descent, and with the test.100 finding that fn 0x1624c never ran.

**No cheap in-body breadcrumb exists** — all stores in fn 0x68a68 body are
register-relative. To discriminate "fn 0x67f2c returned normally vs never
returned" requires either:

1. A breadcrumb inside fn 0x67358 / 0x670d8 / 0x64590's body, at a fixed TCM
   address. Needs further disasm of those (partially done earlier).
2. Or: probe a TCM location written by one of the sub-init routines (e.g.
   si_attach's per-core object registration writes pointers to fixed TCM
   globals for some core types).

## Next: disasm targets to find a new breadcrumb

Candidates for deeper disasm (to find fixed-TCM writes that could serve
as progress breadcrumbs):

- **fn 0x670d8** already disassembled (test.90) — no fixed-TCM writes
  identified. Stores are r4-relative into its 860-byte init struct.
- **fn 0x64590 (si_attach)** — partially disassembled (test.91, 431 words).
  Look for ChipCommon register writes or fixed-TCM pointer saves.
- **fn 0x11648 (Call 3)** — trivial wrapper → bl 0x18ffc + bl 0x1429c.
- **fn 0x18ffc (D11 init)** — prefix analyzed (test.96). Check body for
  fixed-TCM stores before fn 0x16f60.
- **fn 0x16f60** — has `bl 0x16476` at known location; the hardware read at
  0x16f7a is the AHB-hang candidate. Check if anything fixed is written
  before 0x16f7a.

## Conclusion

No immediate breadcrumb inside fn 0x68a68 body. Test.102 should probe a
breadcrumb inside the si_attach descent (fn 0x670d8 / 0x64590 / 0x18ffc /
0x16f60 body). Requires another disasm pass to find fixed-TCM write sites.

Tools note: `script -qc` wrapper required to capture `nix-shell --run`
output when not attached to a PTY (nix-shell silently swallows stdout
otherwise). capstone 5.0.7 used.
