# T253 Local Blob Analysis — wlc_phy_attach mapped; hang not in its body

**Date:** 2026-04-23 (post-T252 capture, pre-T253 hardware)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Local read-only blob disassembly with capstone (`capstone.CS_MODE_THUMB`).

## Function boundaries identified

| Function (observed) | Start | End (next prologue) | Size | Notes |
|---|---|---|---|---|
| wlc_phy_attach | 0x6A954 | 0x6AED2 | ~1.4 KB | Push.w `{r0,r1,r2,r4-r12,lr}` (big stack frame); 'wlc_phy_attach' string at blob[0x54EF2] referenced 2× inside for trace |
| fn_1415C (called from wlc_bmac_attach @ 0x6831C) | 0x1415C | (separate) | helper | SB-core reset polling: reads core+0x1E0, tests bit 0x20000, ~20ms timeout at each of two call-sites |

wlc_phy_attach confirmed by:
- Direct `bl #0x6a954` at blob[0x6865E] inside wlc_bmac_attach.
- Return-value branch at blob[0x68666]: `cbnz r0, #0x68690` — non-zero = success path.
- If zero (NULL): falls through to error branch at 0x68672+ which loads literal 0x687C8 → `"wl%d: %s: wlc_phy_attach failed\n"` (blob[0x4C4E7]) and printfs.

## What wlc_phy_attach does internally

Body 0x6A954..0x6AED2 disassembles cleanly (~1435 instructions in first 0x4000 bytes, but function itself is ~1.4KB). Observed structure:

- Large entry prologue saving 12 registers + LR (common for attach-style ctor with many local vars).
- Two dbg-trace blocks at the top (conditional on `r3 & 1` flag + trace-level mask 0x8000), formatting `"wlc_phy_attach"` name + args.
- Heavy pointer-chasing (`ldr r3, [r5]; ldr r5, [r0, #8]; ...`) — walks the passed-in `pub` / `wlcore` struct.
- Allocation call at blob[0x6A85A]: `bl #0x91c` (likely `kmalloc`-style); sets up a 0xE8-byte object, populates from caller struct.
- **Two fixed-count init loops** near function tail (NOT polling loops):
  - 0x6ADF0..0x6AE0A: iterates r6=0..0x17 (24 times), calling `bl #0x34E18` each iteration. Stores byte result at `[r4 + 0x1040 + 4]`.
  - 0x6AE0C..0x6AE24: iterates r6=0..0xD (14 times), same helper, stores at `[r4 + 0x1040 + 0x1C]`.
  Both loops terminate on count — **not poll-wait**.

**No tight `ldr/tst/bcond-back` hardware-polling loops inside wlc_phy_attach's own body.** The function is initialization code, not a hardware waiter.

## BL call inventory inside wlc_phy_attach (48 calls; by target frequency)

| Target | Calls | Likely role |
|---|---|---|
| 0x00A30 | 10× | printf (fmt-string dispatch) |
| 0x34DE0 | 8× | Generic dispatcher — wraps 0x34D88 predicate + tail-call to 0x6A2D8 |
| 0x14948 | 5× | Trace-timestamp helper (called from many places in fw) |
| 0x34DB8 | 4× | Similar dispatcher pattern — wraps 0x34D88 + b.w 0x50E8 |
| 0x38A50 | 2× | **Dispatch jump table** — 8-byte thunks `ldr r0,[r0]; b.w #XXXX`, each forwarding to a different function (PHY op vtable entry) |
| 0x34DD8, 0x34E18 | 2× each | Inline wrappers around 0x34DB8 / 0x34DE0 |
| 0x38A24 | 1× | Another dispatch jump table (`ldr r0, [r0, #8]; b.w ...`) |
| 0x07D60, 0x07D6E, 0x07D68 | 1× each | Memory/alloc helpers |
| 0x0091C | 1× | bzero / memset |
| 0x6A3D8 | 1× | Local helper inside wlc_phy_attach's own region |
| 0x673D2 | 1× | Another helper (in wlc_bmac region) |

The 0x34DE0 dispatch pattern (called 8×) is the most likely pathway into a polling loop. It:
1. Calls 0x34D88 (checks some predicate — possibly "is this core active?"),
2. If predicate true, tail-calls 0x6A2D8 with original args (the real worker),
3. If false, returns saved r7 directly (a default/NULL case).

The real PHY work happens in 0x6A2D8 (and further sub-dispatches 0x38A50 + 0x38A24 table entries).

## What fn_1415C is (called from wlc_bmac_attach @ 0x6831C)

This is the BL target from the T251 saved-PC 0x68321. Disassembly confirms it's a **silicon-backplane core reset waiter**:

- Prologue 0x1415C: `push {r4,r5,r6,lr}` — small frame.
- Reads flag byte at `[r0+0x10A]` (0xB sits at 0x6a8f0 etc — appears to be a "core active" flag).
- Two distinct code paths based on r1 (called with r1=0 vs r1!=0).
- **Polling loop at 0x14188..0x141A0** (r1=0 path):
  - `movs r0, #0xA` (arg = 10)
  - `bl #0x1ADC` (delay helper, ~10 units)
  - `subs r6, #0xA` (countdown)
  - `ldr r3, [r4, #0x88]` → `ldr r2, [r3, #0x1E0]` (read core+0x1E0)
  - `tst r2, #0x20000` (test bit 17)
  - `bne` branch-out-success
  - else `cmp r6, #9; bne` — loop back while r6 > 9
  - r6 starts at `movw r6, #0x4E29` (20041 decimal). Count down by 10 per iteration → ~2000 iterations.
- **Second polling loop at 0x141D4..0x141EA** — identical structure, r1!=0 path.

Reading: this function polls an SB-core SBTMSTATELOW-like register waiting for a "reset-complete" or "clock-ready" bit (0x20000 = bit 17). Timeout falls through to an error path that calls `bl #0x11E8` (printf/assert) with arg `r1=0x1273`.

If bit 17 of SB-core+0x1E0 never clears (or never sets — depending on which polarity the `bne`-out reads), this loop runs to ~20ms and then exits with an error log. That error log (or the printf at 0x11E8) is NOT observed in the captured ring. This rules out the **timed-out-and-logged** scenario only — it does NOT rule out either:

- **currently-in-progress**: loop still iterating, r6 hasn't reached 9 yet. Unlikely at wall-clock scale (the ~20ms budget is far smaller than the host-side wedge window), but a broken `bl #0x1ADC` delay helper (e.g., waits on a clock tick that stopped) could stall each iteration indefinitely.
- **never-reached**: control flow in wlc_bmac_attach never reached the `bl #0x1415C` at 0x6831C. The saved LR 0x68321 would then be stale/leftover, consistent with T251's "saved-state region may not be a clean stack" caveat.

Consequently, fn_1415C is **lower-priority but not ruled out** as the hang location.

## 0x18001000 literal-ref check (advisor-requested verify of si_info reading)

- `0x18001000` (CC core base): **0 blob refs** — fw constructs via MOVW/MOVT at runtime.
- `0x18000000` (base without offset): **2 blob refs** (at blob[0x328] and blob[0x510B1]).
- `0x18005000` (MAC core base variant): **12 blob refs** — this one IS literal-encoded.

The split is consistent with: fw has a base-address + enum-code loop that walks SB cores via `si_attach()`, caches the resolved per-core bases to runtime BSS/heap. MAC core base (0x18005000) is used enough to justify a direct literal in the code; CC core base (0x18001000) is cached in the si_info struct we saw at TCM[0x92440..0x9244F]. **Reading of 0x92440 as si_info-class struct is strengthened, not weakened, by this check.**

## What this means for the hang

**The hang is NOT inside wlc_phy_attach's own body** (no tight polling loops + function is short ~1.4KB of init code). The hang is inside one of its callees:

- **Most likely**: 0x34DE0 dispatcher chain → 0x6A2D8 → 0x38A50/0x38A24 table entries. These are the generic PHY-op dispatchers wlc_phy_attach uses to call device-specific PHY init methods.
- **Less likely** (but present): 0x14948 trace helper (called 5×); 0xA30 printf (called 10×). If any of these hang on a console-write handshake, fw could freeze mid-print. T250/T251 show last-line output WAS written, so 0xA30 is not totally broken — but a handshake after write could hang.
- **fn_1415C (SB-core reset poll)**: ruled out as primary hang — would have timed out and logged.

Post-POST-TEST.252 struct reading still holds:
- 0x93610 = wl_info-class struct (points to 'wl' name string).
- 0x92440 = si_info-class struct (CC base cached, list_heads embedded).
- 0x91CC4 = subordinate struct with back-pointers.
- 0x934C0 = **central shared object** — referenced in all three structs AND in T251's saved-state — highest-info-per-byte next probe target.
- 0x91E54 / 0x91E84 = list_head peer pair — cheap to probe, confirms/falsifies list-head inference.

## Recommended T253 direction

Advisor called for local-first. That is now done. Findings support a hybrid next step:

- **T253 hardware probe (cheap)**: read TCM[0x934C0..0x93500] (16 u32) + TCM[0x91E50..0x91E8C] (16 u32). Identifies the central shared object and confirms/falsifies list_head pair reading. One dwell at t+60s. Total 32 new reads — far cheaper than T252.
- **T253 local (parallel)**: disassemble 0x6A2D8 (the real worker that 0x34DE0 tail-calls) to look for hardware-polling loops there. This targets the actual PHY-op implementations.

Advisor call before committing to T253 design.

## Clean-room note

All observations are: (1) disassembled-instruction mnemonic + operand reading via capstone, (2) literal-pool address resolution, (3) function boundary identification by push/pop prologue+epilogue matching, (4) string-table cross-reference. Functions are described by role and structure, not by reproducing their instruction sequences beyond short illustrative snippets.
