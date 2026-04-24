# T273-FW — Triage of un-traced sub-calls in wlc_bmac_attach's tail + wlc-probe scheduler callback

**Date:** 2026-04-24 (post-T272-FW)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Read-only capstone (Thumb) disassembly + tight-loop pattern matching + caller-site reconstruction.
**Scripts:** `phase6/t273_subcalls.py`, `t273_deeper.py`, `t273_bmac_tail.py`, `t273_loops.py`, `t273_wlc_isr.py`, `t273_wlc_callback.py`.
**Clean-room note:** plain-language description of behavior + short illustrative snippets; no reconstructed function bodies.

## TL;DR

- All 3 sub-calls named as candidates by T272 (`0x179C8`, `0x67E1C`, `0x67F2C`) are **NOT unbounded polling loops**.
- `0x179C8` is **`wlc_bmac_validate_chip_access`** (96 insns, straight-line, no loops — identity confirmed by string xref).
- `0x67E1C` is a tiny field-reader helper (2 insns).
- `0x67F2C` is a 10-insn dispatcher that tail-calls one of two targets depending on r1.
- Broader scan of the whole wlc_bmac_attach body (2140 bytes, 44 unique BL targets): **all tight loops at first-level sub-calls are BOUNDED** (MAC-address copy 6 iters, txavail setup 6 iters, wlc_macol_attach 30-iter init, SB-core reset 20ms bound per T253/T254).
- **Advisor-flagged lead**: `fn@0x67614` (wlc-probe top) itself calls `hndrte_add_isr` at `0x67774`, registering a scheduler callback `fn@0x1146C` with r0=NULL context.
- `fn@0x1146C` is a small scheduled callback (10 insns), NOT a HW-polling ISR. It awaits a flag bit via the RTE scheduler pending-events word. Whether the trigger is host-driven or fw-internal requires tracing `[ctx+0x358]+0x100` writers — deferred.

## 1. The 3 T272-framed candidates — all clean

### 1.1 `0x179C8` = `wlc_bmac_validate_chip_access`

- String literal `"wlc_bmac_validate_chip_access"` is referenced via LDR-pc-rel from this function's body (explicit identity).
- 96 insns / 232 bytes. **No backward branches** (no loops of any kind).
- Calls: `printf` (0xA30 ×4), `trace` (0x14948 ×2), two tiny helpers `0x16358` (1 insn `tst.w r1, #1`) ×3 and `0x16790` (1 insn `tst.w r1, #1`) ×3.
- Role: validates chip backplane access works by reading back expected values and comparing. Not a polling wait — a validate-once-and-return pattern.
- Classification: **not a hang site**. Returns cleanly.

### 1.2 `0x67E1C` — tiny field-reader

- 2 actual insns (the function body is extremely short; disambiguation between prologue and body was ambiguous but effective body is `ldr r1, [r0, #0x7c]; ldrh.w r3, [r0, #0x52]` → used as a field-extract helper with implicit return).
- Classification: **not a hang site**.

### 1.3 `0x67F2C` — dispatcher

- 10 insns, dispatches to `0x67358` (tail-call via `b.w`) or `0x66F6C` (tail-call via `b.w`) based on r1 value (non-zero or zero).
- Neither target contains tight loops reachable from wlc_bmac_attach's path to wlc_phy_attach.
- Classification: **not a hang site** on its own; downstream targets are dispatchers or bounded helpers.

## 2. Broader catalog of wlc_bmac_attach's first-level sub-calls

Scan of wlc_bmac_attach body (0x6820C..0x68A68, 2140 bytes, 839 instructions) found 44 unique BL targets. Classification:

| Target | Size | Class | Notes |
|---|---|---|---|
| `0x1415C` | 216B, 75 insns, 2 tight | **BOUNDED** | SB-core reset waiter, T253/T254, 20ms delay-helper-based timeout |
| `0x5198` | 46B, 19 insns, 1 tight | **BOUNDED** | MAC-address copy loop, 6 iters (counter cmp #6) |
| `0x67F8C` | 388B, 138 insns, 1 tight | **BOUNDED** | `&txavail` / `wlc_bmac.c` trace strings; 6-iter blx-indirect loop (counter cmp #6) |
| `0x68D7C` | 144B, 54 insns, 1 tight | **BOUNDED** | `wlc_macol_attach` trace string; 30-iter strh.w init loop (counter cmp #0x1e) |
| `0x179C8` | 232B, 96 insns, 0 tight | straight-line | `wlc_bmac_validate_chip_access` |
| `0x191DC` | 124B, 58 insns | straight-line | dispatcher/straight-line |
| `0x68CD2` | 170B, 62 insns | straight-line | dispatcher |
| `0x6A954` | 1406B, 213 insns | straight-line | `wlc_phy_attach` (T254 — clean) |
| `0x6A814` | 216B, 91 insns | straight-line | dispatcher |
| (many tiny helpers < 24 bytes) | | TINY | not hang candidates |
| (8 others with loose-only backward branches) | | error-path returns | not tight loops |

**Every tight loop identified has a fixed bounded count.** No first-level sub-call is an unbounded HW-polling loop.

## 3. The negative result is the signal

Combined with T257 (WFI-DEFINITIVE) and T255 (frozen scheduler state):

- fw is in WFI (confirmed).
- No tight HW-polling loop exists in the wlc_bmac_attach sub-tree (confirmed now).
- Therefore the hang is NOT "fw spinning in a HW register read waiting for a bit that never flips."
- The remaining mechanism is: **fw enters RTE scheduler with no runnable callbacks → goes to WFI → waits for an interrupt that never fires**.

## 4. The scheduler-callback lead (advisor-flagged)

`fn@0x67614` (wlc-probe top) calls `hndrte_add_isr` at offset `0x67774`:

```
0x67766: mov    r0, sb            ; ctx = 0 (sb was set to 0 at 0x676E0)
0x67768: ldr    r1, [sp, #0x48]   ; arg = stack-passed struct ptr
0x6776A: mov    r2, r5            ; name/class-id
0x6776C: ldr    r3, [pc, #0x154]  ; fn = 0x1146D (fn@0x1146C thumb)
0x6776E: str    r7, [sp]          ; 5th arg
0x67770: str.w  r8, [sp, #4]      ; 6th arg
0x67774: bl     #0x63c24          ; hndrte_add_isr
```

### 4.1 What fn@0x1146C looks like

```
0x1146C: push {r0, r1, r4, lr}
0x1146E: ldr r4, [r0, #0x18]      ; r4 = *(arg + 0x18)
0x11470: add.w r1, sp, #7         ; r1 = &sp[7] (byte out-param)
0x11474: ldr r0, [r4, #8]         ; r0 = *(r4 + 8)
0x11476: bl #0x23374              ; helper — sets byte at [sp+7]
0x1147A: cbz r0, #0x11488         ; if helper returned 0 → exit
0x1147C: ldrb.w r3, [sp, #7]      ; r3 = byte-flag from helper
0x11480: cbz r3, #0x11488         ; if flag == 0 → exit
0x11482: mov r0, r4
0x11484: bl #0x113b4              ; action fn
0x11488: pop {r2, r3, r4, pc}     ; return
```

No HW register reads. No BAR-backed MMIO. The trigger is purely the RTE scheduler pending-events bit allocated by `hndrte_add_isr`.

### 4.2 This fn is in the wlc device fn-table

```
[0x58F38] = 0x1146D  ; fn @ 0x1146C
```

So fn@0x1146C is the LAST-slot fn-ptr in the wlc device struct (at struct base 0x58EFC). Per the T272-identified fn-table layout, this corresponds to what upstream-Broadcom conventions would call the "watchdog/periodic" slot of a device struct.

### 4.3 What would fire fn@0x1146C's flag?

Per T269 hndrte_add_isr behavior:
1. Allocates a bit index from a class-specific pool (via `bl 0x9940` → 0x2890 dispatch-thunk).
2. `flag = 1 << bit_index`, stored at `node[+0xC]`.
3. Unmasks via class-specific thunk in the 9-entry vector at `0x99AC..0x99C8` (→ 0x27EC region).

The **pending-events word** that the scheduler tests (`*(ctx+0x358)+0x100` per T269) is populated by the RTE IRQ entry path. For pciedngl_isr (bit 3) the populate happened when MAILBOXINT FN0_0 bit 0x100 was set by a host-written H2D_MAILBOX_1 doorbell.

For fn@0x1146C, whether the populate source is:

- **(a) Host-driven** (like FN0_0): the bit only flips when the host writes a specific PCIe mailbox — fw waits forever absent host action. **Matches our observed freeze exactly.**
- **(b) Fw-internal** (e.g., periodic RTE timer tick): the bit would flip on each timer period (probably every ~1ms or ~1s). Then fn@0x1146C would run periodically, and TCM state would drift over time.
- **(c) WLC-side event** (e.g., PHY calibration completion): would fire on an internal HW state transition; timing may or may not match the freeze observation.

T255 observed scheduler state is FROZEN across 23 dwells (t+100ms through t+90s). This is **inconsistent with (b)** (a periodic tick would update scheduler state between dwells). It's most consistent with (a) or (c) — something needs to happen externally that never does.

If (a), the mechanism is: host needs to write some specific register to fire the bit that fn@0x1146C depends on. The scaffold investigation (T258–T269) wrote H2D_MAILBOX_1 which fires the FN0_0 bit (for pciedngl_isr, bit 3) — not fn@0x1146C's bit.

### 4.4 What this doesn't settle

- **Which specific HW register/event fires fn@0x1146C's bit**. Requires tracing writers of `[ctx+0x358]+0x100` in the blob and reading the 9-thunk vector's WLC-class dispatcher body at 0x27EC+.
- **Whether pciedngldev-probe is ever queued**. The device-probe iterator may schedule PCIEDNGL-probe as a callback that runs after WLC-probe's fn@0x1146C first fires. If fn@0x1146C never fires, the chain stalls there.
- **Why the scheduler enters WFI specifically** (vs spinning in a runnable callback list). Per T257 analysis this is confirmed — just noting the causal chain that leads there.

## 5. Where this leaves the investigation

### 5.1 Settled by T273

- The hang is NOT a simple tight HW-polling loop in wlc_bmac_attach's sub-tree.
- wlc-probe registers a scheduler callback `fn@0x1146C` whose trigger flag bit is allocated by hndrte_add_isr. The callback body has no HW register reads.
- After WLC-probe registers this callback and returns, the RTE scheduler awaits the callback's flag. If the flag is host-dependent and host isn't signaling it, fw enters WFI → observed freeze.

### 5.2 Remaining uncertainty

Whether fn@0x1146C's flag is host-driven (option a) or fw-internal (option b/c). Strong circumstantial evidence favors (a) given:
- Scheduler state frozen across 23 dwells (rules out periodic tick).
- Host bypass of MSI/IRQ setup per T257 (matches "host should be firing something but isn't").
- Upstream brcmfmac protocol DOES have a "host initiates handshake" step (`brcmf_pcie_hostready`) — but gated on HOSTRDY_DB1 from shared.flags, which pciedngldev-probe would set. Circular blocker.

### 5.3 Next cheap static-analysis steps (if continuing)

Each is ~30 min of work:

1. **Trace writers of `*(ctx+0x358)+0x100`** — find the function that sets the pending-events word in the WLC class dispatch. The source of its bits tells us whether WLC's callback is host-driven.
2. **Disasm the 9-thunk vector's WLC slot** (the one for the class `*(ctx+0xCC)` that WLC uses) — find which HW interrupt this class responds to.
3. **Disasm 0x23374 and 0x113b4** (helpers called from fn@0x1146C) — confirm they don't have HW register reads either.

### 5.4 Next hardware direction (if designable)

IF fn@0x1146C's flag is host-driven AND we can identify the specific register/event fw expects:

- Design T274 scaffold to write that specific register early (possibly at t+1s after set_active, well before typical wedge timing).
- If fw advances past fn@0x1146C, pciedngldev-probe may then run → sharedram publish → HOSTRDY_DB1 → normal handshake proceeds.

But this requires identifying the specific event first (steps in §5.3).

### 5.5 Out-of-scope dependency

The scaffold investigation (T258–T269) also revealed a separate host-side wedge mode: merely subscribing MSI + request_irq on BCM4360 wedges the host regardless of any mailbox/doorbell writes. That's independent of the fw-wake question and would need its own fix (candidates B/C from the code audit: remove `pci=noaer` or add `pci=noaspm`).

Even if we identify fn@0x1146C's trigger perfectly, we need both problems solved for a successful wake sequence.

## 6. Clean-room posture

All findings are: (1) capstone Thumb disassembly mnemonics + operands; (2) literal-pool resolution; (3) ASCII-string cross-reference; (4) backward-branch distance pattern matching; (5) tight-loop classification by iteration bound. No reconstructed function bodies; short illustrative snippets only.

## 7. Artifacts

- `phase6/t273_subcalls.py` — top-level classifier for the 3 T272 candidates.
- `phase6/t273_deeper.py` — sub-helper drill-down.
- `phase6/t273_bmac_tail.py` — full wlc_bmac_attach catalog (44 targets classified).
- `phase6/t273_loops.py` — bounded-loop analysis of the 3 polling candidates.
- `phase6/t273_wlc_isr.py` — hndrte_add_isr call-site decode inside fn@0x67614.
- `phase6/t273_wlc_callback.py` — fn@0x1146C body analysis + sb=NULL ctx finding.
- This document.
