# T297 — flag_struct allocator trace (advisor (δ) pivot from POST-TEST.296 stopping rule)

**Date:** 2026-04-27 (post-T296 substrate-null cluster)
**Scripts:** `phase6/t297_flag_struct_writers.py`, `phase6/t297b_init_block_0x6a070.py`, `phase6/t297c_scan_around.py`, `phase6/t297d_resolve_lits.py`, `phase6/t297e_flag_struct_shape.py`
**Goal (per advisor reconcile after POST-TEST.296):** Resolve KEY_FINDINGS row 158's open question — identify flag_struct's allocator and the writer of its `[+0x88]` field, so the wake-gate base address `flag_struct[+0x88]+0x168` becomes statically determinable.

**Approach:** zero-substrate-cost static analysis. T289b §3 listed 8 candidate `[..., #0x88]` writers; characterize the unknowns and search for shape-matched candidates.

## TL;DR — flag_struct's `[+0x88]` is NOT initialized by any direct `str rN, [reg, #0x88]` instruction in the entire blob

**Negative result, but informative:** all 8 stores of any width to `[reg, +0x88]` (excluding sp-relative) are now characterized. NONE of them initializes a struct that matches flag_struct's shape. The flag_struct[+0x88] write must use an indirect addressing pattern.

| Site | Mnemonic | Function (T289b + T297) | Struct context | Value stored at [+0x88] |
|---|---|---|---|---|
| 0x2850 | str.w | fn@0x27EC (class-0 SI thunk = `si_setcoreidx`) | sched_ctx | per-class register base |
| 0x2874 | str.w | fn@0x27EC (same fn, second store) | sched_ctx | re-store of per-class base after assertions |
| 0x67112 | str.w | fn@0x670D8 (`si_doattach`) | sched_ctx | r6 = chipcommon REG base 0x18000000 |
| 0x64A14 | str.w | fn@0x649A4 | STRUCT_A (0xAC-byte alloc) | r5 = arg2 = wlc_callback_ctx (back-pointer) |
| 0x682D8 | str.w | fn@0x6820C | (per-class table) | r0 = `sched[class*4+0x114]` field |
| **0x6A070** | **str.w** | **fn@???? (callbacks-table init, fn-start not yet found via push-lr scan)** | **callbacks/handlers table** | **r3 = 0x00030935 = Thumb fn ptr to `fn@0x30934`** |
| 0x7346 | strh.w (16-bit) | fn@0x7210 | (different — has +0x80, +0x84, +0x88 dwords used as windowing math) | (uxth-trimmed bit-shifted value, not a base) |
| 0x1BB28 | strh.w to sp+0x88 | fn@0x1BA9C | stack frame | irrelevant (local var) |
| **0x6A8CC** | **strb.w (BYTE)** | **fn@???? (T289b missed — strb-only scan)** | **(some struct with [+0x60] dword + [+0x88] byte 40 B apart)** | **byte value (not a base address)** |

T289b §3 listed 8 sites; T297's exhaustive resumable scan finds 8 too — but with one different: T289b missed `0x6A8CC` (a strb.w byte store), and T297 confirms `0x6A070` is a callbacks-table init (the literal at the [+0x88] store is a Thumb fn pointer, not a base address).

### Resolution of the 0x6A070 "TBD" entry

Site 0x6A070 sits inside a struct-init block (0x6A040..0x6A090) that writes 8 fn pointers to `[r4, +0x20/0x24/0x28/0x2c/0x6c/0x70/0x74/0x88/0x8c]`:

| Offset | Value (resolved literal) | Decoded |
|---|---|---|
| +0x20 | 0x00025c89 | Thumb fn @0x25C88 |
| +0x24 | 0x00033f71 | Thumb fn @0x33F70 (`push.w {r4..fp, lr}` — heavyweight) |
| +0x28 | 0x00030871 | Thumb fn @0x30870 |
| +0x2c | 0x000292c5 | Thumb fn @0x292C4 |
| +0x6c | 0x000296ad | Thumb fn @0x296AC |
| +0x70 | 0x000273b5 | Thumb fn @0x273B4 |
| +0x74 | 0x00030895 | Thumb fn @0x30894 |
| **+0x88** | **0x00030935** | **Thumb fn @0x30934 (`ldr r3, [r0, #0x1c]`)** |
| +0x8c | 0x000292c5 | Thumb fn @0x292C4 (also at +0x2c) |

This is a **wlc-internal callbacks/handlers table** — looks like a method dispatch struct with ~8 method pointers. The struct r4 here is NOT flag_struct (whose [+0x88] is a memory base, not a fn ptr).

### What this means for the chain

The chain `wlc_callback_ctx[+0x18][+8][+0x10][+0x88]` (fn@0x1146C → fn@0x23374 → fn@0x2309C) is correct and verified. But flag_struct's [+0x88] is initialized by something OTHER than a direct `str rN, [reg, #0x88]` instruction.

Candidate indirect mechanisms to investigate:

1. **memcpy from a template struct**: a static template in .data has the wake-gate base baked in at offset +0x88; an alloc-and-copy operation produces flag_struct from it.
2. **Register-offset addressing**: `mov r3, #0x88; str rN, [r4, r3]` — this would not show in a direct-offset scan.
3. **Pointer arithmetic**: `add r3, r4, #0x88; str rN, [r3]` — store via intermediate add. Scan would have to recognize `add rX, r4, #0x88` patterns.
4. **Post-indexed addressing**: `str rN, [r4], #0x88` — increments r4 after the store. Would still produce a `str rN, [r4]` not `str rN, [r4, #0x88]`.
5. **`strd` to `[reg, +0x80]`** — strd writes 8 bytes starting at imm; +0x80 store dual would write +0x80 and +0x84, NOT +0x88. Already in scan.
6. **`stm`/multi-store** with a base offset: less common in init code, but possible.

Of these: (1) and (3) are the most likely, given normal ARM compiler output.

### KEY_FINDINGS impact

**Row 158** — STAYS LIVE; refined: "flag_struct[+0x88] is NOT initialized by any direct `[reg, +0x88]` store anywhere in the blob. Initialization mechanism is indirect — most likely template-memcpy or pointer-arithmetic via `add rX, baseReg, #0x88; str ...`. Identifying the actual writer requires either a memcpy-template scan or a pointer-arithmetic-then-store scan."

**Row 156** — UNCHANGED.

## What's next (advisor reconcile required)

Three paths:

- **(δ-1) Pointer-arithmetic scan**: enumerate all `add rN, rM, #0x88` instructions, then look for `str rX, [rN]` immediately following. Cheap, narrow, 100% static.
- **(δ-2) Template-memcpy scan**: find all `bl memcpy` (or inline `ldm`/`stm` copy loops) whose source is in .data and whose copy length spans offset 0x88 of the destination. Would identify a static template if used.
- **(δ-3) Top-down wl_probe trace**: from wl_probe(arg=wlc_callback_ctx), trace the call tree until something ALLOCS a struct and stores it into wlc_pub[+8] = dispatch_ctx, or stores something into dispatch_ctx[+0x10] = flag_struct base. This is the most direct path but the deepest call tree.

Recommended order: (δ-1) first (cheapest), then (δ-2), then (δ-3) only if the others dead-end. If all three dead-end statically, the only remaining option is a TCM read-only sampling probe at runtime — which advisor explicitly noted as the safe fallback over (γ-c) write-probe.

## Update — T297-6/7/8: T274 re-scan with resumable iterator (post-advisor)

### T274's old scan was incomplete (but T281's HW-MMIO inference still holds)

Advisor flagged that T274's negative writer scan likely hit the same capstone-stops-at-undecodable-bytes bug T297e exposed. T297f re-ran the scan with the resumable iterator (which T297e proved finds 6× more hits).

**Result — 22 writer candidate sites found, vs T274's near-zero:**

| Offset | 32-bit hits | Sub-32 hits | `add rN, rM, #imm` | `mov rN, #imm` |
|---|---|---|---|---|
| +0x168 | 3 (`str.w`) | 2 (strh, strb) | 2 (one is `add r0, r4, #0x168`) | 1 (`mov.w r1, #0x168`) |
| +0x16C | 4 (`str.w`) | 3 (strb) | 4 (`add rN, rM, #0x16c`) | 0 |

### Classification of each [+0x168] / [+0x16C] writer (T297g)

| Site | Fn | Pattern | Interpretation |
|---|---|---|---|
| 0x15640 | fn@0x15638 | `mov.w r1, #-1; str.w r1, [r4, #0x168]` (where r4 = `[r0, +0x88]`) | **Clear-all wake-gate bits** — W1C-style write of 0xFFFFFFFF |
| 0x15ede | fn@0x15E92 | `mov.w r3, #0x4000; str.w r3, [r5, #0x168]` (r5 = `[r4, +0x88]`) | **Clear specific bit** (0x4000 = bit 14) — W1C-style |
| 0x23108 | fn@0x2309C | T281's W1C clear (matched bits) | Documented in T281 |
| 0x230fe / 0x23402 / 0x23420 / 0x23448 | fn@0x2309C / 0x233E8 / 0x2340C | All W1C clears on [+0x16C] | Multiple consumers exist |
| 0x230fe→0x23102 | fn@0x2309C | `str r3, [r5, #0x16c]; ldr r2, [r5, #0x16c]` — write then immediate readback | **HW MMIO write barrier** — strong evidence the address is HW |
| 0x142ce / 0x14310 / 0x187fc | misc fns | strb.w (byte) writes — different struct shape | Likely different chain (not flag_struct) |
| 0x2bdc0 | fn@0x2b92c | strh.w with `movw r1, #0x932`; in series with [+0x158/0x180/0x188/0x200] writes | Different struct (16-bit-aligned reg layout) |
| 0x3cb18 | fn@0x3cab0 | bitmap clear-bit operation (`add r2, r4, r3, lsr #3 ; ldrb [r2, #0x168] ; bic ; strb`) | Byte-array indexing; unrelated chain |

**Net conclusion**: ALL writes through the flag_struct→[+0x88] chain at [+0x168]/[+0x16C] are **W1C-clear semantics** (consumer-side). NO producer-set pattern (`ldr; orr #bit; str`) found. The read-then-write-back-with-verify at fn@0x2309C is a classic HW MMIO write barrier.

### Register-block layout via [+0x88]-loaded base (T297h)

In functions following the wake-gate chain (ldr-sites: 0x1563a, 0x15e9e, 0x230aa, 0x233fc, 0x23416, 0x23444), the register-block accesses are:

| Offset | Loads | Stores | Notable constants written |
|---|---|---|---|
| +0x128 | 4 | 2 | (R/W; tested with `tst.w #1`) |
| +0x168 | 1 | 3 | -1 (clear-all), 0x4000 |
| +0x16C | 2 | 5 | 0 (zero out, then readback) |
| +0x180 | 6 | 0 | (read-only mask register?) |
| +0x184 | 2 | 0 | (read-only) |
| +0x188 | 0 | 1 | 0x80000000 (bit 31) |
| +0x18C | 0 | 2 | 0x2000000 (bit 25) |

This **looks like a HW interrupt-control block** — pairs of status (W1C) + mask (R/W) registers at consecutive 4-byte offsets. The +0x180 read-only mask + +0x184 register pair, +0x188/+0x18C paired writes of bit-31 and bit-25, and +0x168/+0x16C paired clears all match the standard Broadcom interrupt-block convention.

### KEY_FINDINGS impact (revised)

- **Row 158** — STAYS LIVE. The wake-gate IS HW MMIO (T281 inference HOLDS, even after the better scan). What's NOT yet identified: which HW core's MMIO base it points at.
- **Row 156** — REINFORCED. hndrte_add_isr writes no HW registers; the wake-gate is initialized somewhere else.
- **NEW finding**: Multiple sibling consumer functions (fn@0x15638, fn@0x15E92, fn@0x233E8, fn@0x2340C) follow the SAME flag_struct→[+0x88] chain — this is a real wlc-internal register block, with bit-31 and bit-25 as named events.

### Identification candidates for the wake-gate HW base

The block has the layout: [+0x128]=R/W status, [+0x168]/[+0x16C]=W1C status pair, [+0x180]/[+0x184]=read-only masks, [+0x188]/[+0x18C]=mask R/W. This shape suggests:

- **NOT chipcommon REG base** — chipcommon has Watchdog/PMU/Clock/UART/SPROM/JTAG/PWMs etc. at known offsets; the wake-gate cluster doesn't match.
- **NOT PCIE2** — fw blob has 0 PCIE2 literals (T289 §3); fw could only reach PCIE2 via EROM-walked sched_ctx[per-class][reg], which T287c shows fw never does at runtime.
- **Plausible: D11 (core[2] = 0x18001000) MAC interrupt block** — D11 has interrupt-status registers in its main MMIO page; offsets 0x128/0x168/0x16C/0x180+ are within the D11 MAC reg range.
- **Plausible: ARM-CR4 core registers (0x18002000)** — ARM has its own peripheral interrupts; Cortex-R4 has VIC at predictable offsets within its register space, but the absolute offsets typically start higher than 0x100.
- **Plausible: an internal hndrte-block at chipcommon WRAPPER (0x18100000) that's not the standard agent regs** — wrap pages have agent regs only at 0x000-0xFFF; offsets 0x128/0x168/0x180+ would be beyond the agent range.

The most likely candidate is **D11 MAC interrupt block at +0x100 within the D11 core base**. T287c showed sched_ctx+0x88 shifting to 0x18001000 (core[2]) at runtime — that's D11's REG base. If `flag_struct[+0x88]` was set to the same value (0x18001000) during wlc init, the wake-gate would be at 0x18001000+0x168 = `0x18001168`.

This is verifiable cheaply with a TCM read-only probe at runtime (no chipcommon RMW needed) — read `flag_struct[+0x88]` directly via TCM and confirm.

## T297-9: cluster-shape candidate at 0x6A814 — NOT flag_struct

The 0x6A8A4/0x6A8CC/0x6AC70 cluster (str at +0x60, strb at +0x88, strb at +0xAC, all on r4) flagged in T297e is a 232-byte (0xE8) struct allocator/initializer at fn@0x6A814. Body shape:
- `bl alloc(?, 0xE8); memset(r4, 0, 0xE8)` — alloc-and-zero
- Many field copies from `arg0` (template) → new struct (r4)
- Explicit byte zeroing at +0x82..+0x89 + +0x94 (defensive zero)
- The [+0x88] write is `strb.w r3, [r4, #0x88]` with r3=0 — a BYTE clearing, not a 32-bit base store

Not flag_struct. Closes that line.

## T297-10: wake-gate identification via brcmsmac/d11.h cross-reference

Explore agent searched upstream Linux kernel for HW core matching the register-block signature (offsets 0x128, 0x168, 0x16C, 0x180-0x18C with bit constants 0xFFFFFFFF/0x4000/0x80000000/0x2000000):

> The register block belongs to **D11 (core[2], ID 0x812, base 0x18001000)** — Broadcom 802.11 MAC.
>
> | Offset | Register | Purpose |
> |---|---|---|
> | 0x128 | `macintstatus` | MAC interrupt status (R/W) |
> | 0x168 / 0x16C | (interrupt block — W1C-style) | (exact name varies between D11 revs; W1C-clear pattern matches) |
> | 0x180 / 0x184 | `tsf_timerlow` / `tsf_timerhigh` | TSF time |
> | 0x188 / 0x18C | `tsf_cfprep` / `tsf_cfpstart` | TSF CFP control |

Constant decode under D11 INTSTATUS interpretation:
- 0xFFFFFFFF write to +0x168 = "clear all pending MAC interrupts" (init/reset path)
- 0x4000 = bit 14 = likely **MI_GP1** (general-purpose interrupt 1)
- 0x80000000 = bit 31 = likely **MI_TO** (general-purpose timeout) or saturate flag
- 0x2000000 = bit 25 = some MAC-event mask

Note: BCM4360's D11 is rev 42 (per T287c), while upstream brcmsmac's d11.h covers older D11 revs (rev 24-26). Exact register names at +0x168/+0x16C may differ between revs, but the CORE identification (D11 = wireless MAC) is solid.

### Strategic implication — major shift

**fw is waiting for D11 (wireless MAC) interrupts to wake from WFI**, not for PCIE2 mailboxes (already ruled out per row 117) and not for chipcommon events (the analogy that misled T283/T287b).

To get fw past WFI, the host needs to either:
1. **Trigger a real D11 MAC event** — requires the MAC to be powered up + configured + receiving wireless activity. Pre-attach is too early; needs wlc_init complete first.
2. **Write a D11 INTSTATUS bit directly via BAR0** (using `select_core(D11)` then write to D11_BASE+0x168). This SETS a software-friendly bit (e.g., MI_GP1) which fw responds to during dispatch.
3. **Find an internal path** where chipcommon or another reachable core triggers a D11 INTSTATUS bit indirectly.

**Fundamental re-frame**: the wake mechanism for fw isn't "host doorbell to PCIe" — it's "MAC event to D11 INTSTATUS". This explains why T241/T280/T284 host MBM writes did nothing (different register block entirely) and why hndrte_add_isr writes no HW registers (it's wlc-side scheduler work, not interrupt enable).

## Clean-room posture

All findings are disassembled mnemonics + literal-pool resolution + offset-pattern matching, plus open-source cross-reference (brcmsmac/d11.h via Explore). No reconstructed function bodies. Scripts in `phase6/t297*.py`. Zero hardware fires.
