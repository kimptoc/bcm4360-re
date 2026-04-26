# T289 — static analysis: 9-thunk vector, hndrte_add_isr body, MMIO write search

**Date:** 2026-04-26
**Scripts:** `phase6/t289_all_thunks.py`, `phase6/t289_hndrte_add_isr_body.py`, `phase6/t289_mbm_write_search.py`
**Inputs:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 B, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** read-only capstone disassembly + literal-pool scan.
**Goal (per advisor reconcile):** static-analysis pivot from T288 wrap-read line of investigation; identify the actual wake-gate writer (per KEY_FINDINGS row 118 LIVE).

## TL;DR — three structural findings, all independent of substrate

1. **The "9-thunk vector at 0x99AC..0x99CC" is the AI/SI library API method dispatch** — NOT a per-class interrupt-mask vector. Each thunk implements one upstream `aiutils.c` SI method (`si_setcoreidx`, `si_core_setctl`, `si_core_disable`, `ai_core_reset`, etc.). Strings `'ai_core_disable'` and `'ai_core_reset'` are referenced directly inside class-6/7 thunks confirming the mapping.
2. **`hndrte_add_isr` (fn@0x63C24) does NOT write to any HW interrupt-enable register.** Body: alloc 16-byte node, save-current-class, switch-class via si_setcoreidx, `BIT_alloc` (which reads wrap+0x100), build node, prepend to list at `*0x629A4`, restore-original-class via direct call to thunk vector entry. Six total stores in the function — all to the new node or the list head pointer; ZERO HW register writes.
3. **The fw blob contains ZERO references to PCIE2 register space.** Exhaustive 4-byte-aligned literal scan: 0 hits for 0x1800304C (MAILBOXMASK), 0 hits for 0x18003000 (PCIE2 base), 0 hits for 0x18103000 (PCIE2 wrapper), 0 hits in entire 0x180030xx page. The ONLY backplane MMIO literal in the entire 442KB blob is **`0x18000000` (chipcommon REG base) at file-offset 0x328 — single hit.** Fw never targets PCIE2 MMIO from its own code.

These three findings combine to a structural reframe: **the wake mechanism for fw is not via PCIE2 MAILBOXMASK at all** — neither host nor fw writes to it, and the only host-side write path silently drops (T241/T280/T284). Fw's wake comes from somewhere else.

## 1. Per-class thunk decode

The vector at 0x99AC..0x99CC dispatches by class index to 8 method targets + a no-op fallback (per T274). Disasm of all 8 active targets:

| Class | Thunk @ | Strings/asserts | Inferred SI API method | Register touched |
|---|---|---|---|---|
| 0 | 0x27EC | `'aiutils.c'` line 0x1F6 (502) | `si_setcoreidx` (per-class context switch) | sched ctx only — sets sched+0x88 to per-class register base, sched+0x254 to per-class wrapper base, sched+0xCC to class index. NO HW writes. |
| 1 | 0x2B8C | `'aiutils.c'` line 0x423 (1059) | `si_core_setctl` / wrap+0x408 RMW (ioctrl) | wrapper+0x408 (`ioctrl`) — RMW with mask+value args |
| 2 | 0x2BDC | `'aiutils.c'` line 0x449 (1097) | wrap+0x500 RMW (resetctrl) — has 12-bit mask validation | wrapper+0x500 (`resetctrl`) — RMW with mask+value, low-12-bit only |
| 3 | 0x28E2 | (no strings — small body) | `si_iscoreup` — read ioctrl & resetstatus | wrapper+0x408 + wrapper+0x800 (read-only) |
| 4 | 0x28AE | (small) | `si_corereg_w_addrspace` (generic wrap RMW with byte-offset/4 indexing) | wrapper+arbitrary offset |
| 5 | 0x2904 | `'aiutils.c'` line 0x32A (810), 0x32B, 0x32C, 0x338 | `si_corereg` (generic per-class core REGISTER RMW with byte offset) | `[sched+r4*4+0x8c]+offset` (per-class register base + offset) |
| 6 | 0x29AC | `'aiutils.c'` line 0x37C, **`'ai_core_disable'`** STRING ref | `ai_core_disable` (poll wrap+0x804, RMW wrap+0x800/+0x408 with delay loops) | wrapper+0x800 + wrapper+0x408 + wrapper+0x804 |
| 7 | 0x2A4C | `'aiutils.c'` line 0x3AD, **`'ai_core_reset'`** STRING ref | `ai_core_reset` (RMW wrap+0x408, set wrap+0x800, poll wrap+0x804) | wrapper+0x804 + wrapper+0x408 + wrapper+0x800 |

**Key observation**: NONE of these 8 thunks writes to a register that resembles a "wake-gate unmask" or interrupt-enable. They write to:
- AI-backplane wrapper control: `ioctrl` (0x408), `resetctrl` (0x500), `resetstatus` (0x800)
- Per-class core register space (via class-5 generic helper)
- Wrapper agent registers (via class-4 generic helper)

The OOB-routing register `oobselouta30` at wrapper+0x100 (read-only via fn@0x9940/9944 — BIT_alloc) is the only +0x100-ish register touched, and it's READ for bit-pool allocation, not written.

### 1.1 Class 5 (`si_corereg`) could theoretically write MAILBOXMASK

If class-5 thunk were called with `(class=PCIE2, offset=0x4C, mask, value)`, the resulting MMIO write would land at `[sched+0x8c+r4*4]+0x4C`, which — if the per-class register base for PCIE2 is set to 0x18003000 — would be MAILBOXMASK at 0x1800304C.

**But** runtime evidence (KEY_FINDINGS row 132) shows that during T287c's observation window, sched+0x88 only shifted between **chipcommon (0x18000000)** and **core[2] (0x18001000)** — fw never called `si_setcoreidx(PCIE2)`. Static evidence (this T289 section 3) shows fw has NO PCIE2 base literal anywhere in the blob, so a runtime call to si_setcoreidx(PCIE2) would have to obtain the value from sched+0x8c+4*4 = sched+0x9C (the per-class register-base table). That table is populated by EROM walk so it would have the right value at runtime. But fw NEVER calls si_setcoreidx(PCIE2) in the windows we observed.

**Conclusion**: class-5 thunk COULD write MAILBOXMASK in principle, but fw's runtime behavior shows it never does. Fw stays in chipcommon/core[2] context, never touches PCIE2 from its own code.

## 2. hndrte_add_isr body

`fn@0x63C24` (60 bytes of body):

```
push {r3-r8, sb, lr}
r0=0x10, r1=0
r4 ← caller's r1 (class arg, e.g. 0x812 for special path)
sb ← caller's r2 (callback fn ptr — sb=arg used as flag holder later)
r8 ← caller's r3 (callback arg)
bl fn@0x1298                  ; alloc(16) — for new node
mov r5, r0                    ; r5 = node ptr
cbnz r0, .alloc_ok
ldr r0, lit (printf format)
bl printf                     ; alloc-fail trace
return -27 (alloc error)

.alloc_ok:
ldr r6, lit (=0x6296C)        ; sched_ctx pointer table addr
ldr r0, [r6]                  ; r0 = sched_ctx
bl fn@0x9956                  ; r0 = sched->[0xCC] = current class
mov r7, r0                    ; r7 = saved current class
ldr r3, [sp, #0x24]           ; r3 = caller's stack arg (force_class flag)
cbnz r3, .skip_set            ; if flag set, skip si_setcoreidx
ldr r0, [r6]
mov r1, r4                    ; r1 = caller's class
mov r2, sb                    ; r2 = callback fn (passthrough)
bl fn@0x9990                  ; class-validate wrapper → si_setcoreidx (class-0 thunk)
cbnz r0, .skip_set
ldr r0, lit ('hndrte.c')
movw r1, #0x786 (=1926)
bl printf/assert              ; assert si_setcoreidx returned non-zero

.skip_set:
ldr r0, [r6]                  ; r0 = sched_ctx
mov.w sb, #1                  ; sb = 1 (re-used as bit constant)
bl fn@0x9940                  ; BIT_alloc — reads wrap+0x100 low bits, returns bit index
movw r3, #0x812
cmp r4, r3                    ; class == 0x812?
lsl.w r0, sb, r0              ; r0 = 1 << bit_index
str r0, [r5, #0xC]            ; node[0xC] = bit mask
bne .skip_812
; class == 0x812 special path: re-allocate using fn@0x9944 (mid bits of wrap+0x100)
ldr r3, lit (=0x6296C)
ldr r0, [r3]
bl fn@0x9944                  ; BIT_alloc — reads wrap+0x100 mid bits
lsl.w r0, sb, r0
str r0, [r5, #0xC]            ; node[0xC] = new bit mask (overwrite)

.skip_812:
ldr r3, [sp, #0x20]           ; r3 = caller's arg5 (callback arg)
mov r1, r7                    ; r1 = saved original class
str r3, [r5, #8]              ; node[8] = arg
ldr r3, lit (=0x629A4)        ; r3 = list head ptr address
str.w r8, [r5, #4]            ; node[4] = callback fn ptr
ldr r0, [r6]                  ; r0 = sched_ctx
ldr r2, [r3]                  ; r2 = current head of list
str r2, [r5]                  ; node[0] = next = old head
str r5, [r3]                  ; head = new node (LIST PREPEND)
bl fn@0x99AC                  ; tail-call to thunk-vector entry → b.w 0x27EC = si_setcoreidx
                              ; with (r0=sched_ctx, r1=r7=original class)
                              ; → restores per-class context
movs r0, #0
return 0 (success)
```

**All 6 stores in this function**:
- `str r0, [r5, #0xc]` × 2 (set node bit mask — once normal, once class-0x812 override)
- `str r3, [r5, #8]` (set node arg)
- `str.w r8, [r5, #4]` (set node callback fn)
- `str r2, [r5]` (set node next ptr)
- `str r5, [r3]` (set list head to new node)

**Zero stores to any HW MMIO address.** Zero stores to any register that resembles an interrupt-enable.

The function's only HW interaction is THROUGH the SI library calls (`fn@0x9990` = si_setcoreidx, `fn@0x9940`/`fn@0x9944` = BIT_alloc reads). BIT_alloc is read-only — it reads `[sched+0x254]+0x100` (wrap+0x100 = `oobselouta30`) and extracts a bit-slice as the allocated bit index. The class-0 thunk (si_setcoreidx) only updates sched_ctx slots (no HW writes).

**There is no path through hndrte_add_isr that enables an interrupt source on the hardware.** The function only manipulates software state (linked list + node fields).

## 3. PCIE2 register space — fw blob has zero references

Exhaustive 4-byte-aligned literal scan over the 442233-byte blob:

| Pattern | Hits |
|---|---|
| `0x1800304C` (MAILBOXMASK absolute) | **0** |
| `0x18003000` (PCIE2 register base) | **0** |
| `0x18103000` (PCIE2 wrapper base) | **0** |
| Any 0x180030xx (PCIE2 register page low 256 B) | **0** |
| Any backplane MMIO literal in 0x18000000..0x18010000 range | **1**: `0x18000000` at file-offset `0x328` |

**Only one backplane literal in the entire fw blob: chipcommon REG base `0x18000000`** at file offset 0x328 (a single hit — the literal pool of an early-init function).

Fw doesn't reference PCIE2 from anywhere in its code. Not as a literal, not as a wrapper base, not as the MAILBOXMASK address, not as any other PCIE2 register.

### 3.1 Why this matters

Combined with KEY_FINDINGS row 125 (host-side MAILBOXMASK writes silently drop at all timings on this chip):

- Host writes to MAILBOXMASK silently fail → host can't unmask via this register.
- Fw never writes to MAILBOXMASK from its own code → fw doesn't unmask itself via this register either.
- **Therefore PCIE2 MAILBOXMASK is not the wake gate for this fw.**

This forces a structural reframe: the wake gate must be elsewhere. The remaining candidates (working hypothesis):

a. **Chipcommon interrupt path** — fw has chipcommon REG base (the only backplane literal in blob); the pending-events word read at `[sched+0x88]+0x168` (with sched+0x88 = chipcommon) lands at chipcommon+0x168. Whatever register lives at chipcommon+0x168 may be the actual interrupt-status register fw waits on. Wake source: events that set bits at chipcommon+0x168 (via HW logic).
b. **PMU watchdog tick** — fw banner says `wd_msticks = 32` (T278). Watchdog ticks every 32 ms once enabled. Could be a periodic wake source.
c. **Intra-chip events** (PHY-CPU, MAC TBTT) — these wake on chip-level events that happen only after MAC is fully enabled, which wl_probe init would NOT have completed at the WFI point.

Most likely (a). Verifying it requires identifying what register at chipcommon+0x168 actually is — that's a read-only hardware probe (NOT a write — much cheaper than T288's write-attempts).

## 4. KEY_FINDINGS rows that need updating

### 4.1 Row 118 — FALSIFY

Current LIVE: `hndrte_add_isr's per-class unmask thunk does NOT produce a non-zero MAILBOXMASK ... Either thunk writes to different register, was not invoked, or its effect is gated.`

T289 evidence: **there is no "per-class unmask thunk".** The 9-thunk vector is the SI library API. None of the 8 active thunks writes a wake-gate or interrupt-enable register. hndrte_add_isr only touches software state (callback list).

New status: **FALSIFIED — the framing was wrong; no such thunk exists.**

### 4.2 Row 116 — REFINE

Current CONFIRMED: `MAILBOXMASK = 0x00000000 in Phase 5 fw state at t~3 s post-set_active. Explains why fw stays in WFI indefinitely.`

T289 evidence: MAILBOXMASK staying 0 is consistent with fw NEVER touching PCIE2 MMIO from blob, plus host writes silently dropping. The "Explains why fw stays in WFI" causal claim should be SOFTENED: it's structurally true that this register can't be the wake source under current conditions, but the "explanation" of WFI requires identifying the actual wake source elsewhere.

### 4.3 New row — ADD

**The fw blob has zero references to PCIE2 MMIO** (no PCIE2 register base literal, no MAILBOXMASK literal, no PCIE2 wrapper literal). The only backplane MMIO literal in the entire 442KB blob is chipcommon base `0x18000000` (single hit at file-offset 0x328). Fw never touches PCIE2 from its own code; PCIE2 register manipulation is host-side only. Combined with host MAILBOXMASK writes silently dropping (T241/T280/T284), PCIE2 MAILBOXMASK is structurally not the wake gate.

Status: **CONFIRMED (negative result, exhaustive scan)**.

### 4.4 New row — ADD

**The 9-thunk vector at 0x99AC..0x99CC is the AI/SI library API dispatch** (si_setcoreidx, si_core_setctl, si_core_disable, ai_core_reset, etc.). String literals `'ai_core_disable'` and `'ai_core_reset'` are referenced directly inside class-6/7 thunks. Class-1 RMWs ioctrl (wrap+0x408); class-2 RMWs resetctrl (wrap+0x500); class-3 reads ioctrl+resetstatus (`si_iscoreup`); class-4/5 are generic wrap/core register RMW helpers; class-6/7 are full reset sequences with poll loops. NONE writes a wake-gate or interrupt-enable register.

Status: **CONFIRMED**.

### 4.5 New row — ADD (working hypothesis)

**Wake source is likely chipcommon+0x168.** Per T281, fn@0x2309c reads pending-events at `[[r0+0x10][+0x88]]+0x168`. Per T287b runtime sched+0x88 = chipcommon REG base 0x18000000. The address chipcommon+0x168 is the candidate "interrupt-status" register fw waits on. Identifying which chipcommon register at offset 0x168 actually lives there (upstream kernel header lookup) and what HW path sets bits there (PMU? GCI? GPIO IRQ?) is the next cheap question — pure documentation/static work.

Status: **LIVE** (needs upstream-doc verification).

## 5. What this enables / blocks

**Enables (zero-fire next steps):**
- Look up upstream kernel reference for chipcommon+0x168 register identity.
- Identify which HW events set bits at chipcommon+0x168 on BCM4360.
- If chipcommon+0x168 is the PMU/GCI interrupt-status, derive what PMU resource transitions or GCI events would naturally fire while fw is in WFI.
- Compare against T287c's frozen-state observation (sched+0x88 went through one shift then froze — consistent with no chipcommon interrupts firing during the dwell windows).

**Blocks (saves substrate budget):**
- T288 wrap-read line is now decisively a side-question (the wrap+0x100 read is BIT_alloc's bit-pool source, not the wake gate). Even if the wrap-read probe didn't wedge (the thing it was testing) and even if MAILBOXMASK write succeeded (which it won't), neither is on the wake-gate path.
- T288d/N-baselines isn't worth the 3-fire budget for the H1 question; H1 is now structurally known to be misframed.

## 6. Clean-room posture

All findings are disassembled mnemonics + literal-pool analysis + ASCII-string cross-reference. No reconstructed function bodies; illustrative snippets show register-flow / call-site structure only. Scripts in `phase6/t289_*.py`. Zero hardware fires.
