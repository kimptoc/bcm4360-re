# Offline disasm: fn 0x1415c (called from 0x6831c in fn 0x6820c)

Primary data: raw bytes of `/lib/firmware/brcm/brcmfmac4360-pcie.bin` starting at offset 0x1415c.
Disassembler: capstone (Thumb-2), run via `PYTHONPATH=/nix/store/.../python3-capstone/.../site-packages python3`.

---

## 1. Prologue & frame verification

```
0x1415c: 70b5         push   {r4, r5, r6, lr}
0x1415e: 90f80a31     ldrb.w r3, [r0, #0x10a]
0x14162: 0446         mov    r4, r0
0x14164: 0d46         mov    r5, r1
0x14166: 002b         cmp    r3, #0
0x14168: 48d0         beq    #0x141fc
0x1416a: 29bb         cbnz   r1, #0x141b8      ; r1=0 from caller → FALL THROUGH
0x1416c: d0f88830     ldr.w  r3, [r0, #0x88]
0x14170: 4020         movs   r0, #0x40
0x14172: 44f62966     movw   r6, #0x4e29       ; timeout counter ≈ 20009
0x14176: d3f8e021     ldr.w  r2, [r3, #0x1e0]
0x1417a: 42f00202     orr    r2, r2, #2        ; set bit1 of reg
0x1417e: c3f8e021     str.w  r2, [r3, #0x1e0]  ; write back
0x14182: edf7abfc     bl     #0x1adc           ; delay(0x40)
```

### Frame math (explicit)

- Push set: `{r4, r5, r6, lr}` → N = 4 registers
- push_size = 4·N = 16 bytes
- No `sub sp, #imm` in the prologue
- total_frame = push_size + sub_imm = 16 + 0 = **16 bytes**  (≤ 24 ✓)
- body_SP = caller_SP − total_frame = 0x9CED8 − 16 = **0x9CEC8**
- Predicted LR-slot = body_SP + 4·(N−1) = 0x9CEC8 + 12 = **0x9CED4** ✓ (matches test.104 reading of 0x68321)

Frame & LR-slot checks **PASS**. Proceed.

Stack layout of fn 0x1415c body frame:
```
0x9CED4: saved LR = 0x68321   (verified by test.104)
0x9CED0: saved r6
0x9CECC: saved r5
0x9CEC8: saved r4             ← body_SP
```

---

## 2. Function classification

**Classification: HW (PMU/PHY) register poll helper, NOT a compiler runtime.**

Evidence:
- **Struct-field access pattern**: `ldrb [r0, #0x10a]` (enable flag), `ldr [r0, #0x88]` (pointer), then `ldr [r3, #0x1e0]` (HW MMIO register). Not a memcpy/memset signature.
- **RMW on a memory-mapped register**: `orr #2; str`; later `bic #2; str`. Classic "set HW bit → wait → clear HW bit" idiom.
- **Tight status-poll loops** at 0x14188–0x141a0 and 0x141d2–0x141ea, both testing bit 0x20000 of `[r3+0x1e0]`.
- **Timeout counter** `movw r6, #0x4e29` (= 20009 decimal) decremented by 10 each iteration → ~2000 polls before giving up. Canonical HW-timeout pattern.
- **Calls into 0x1adc** — this is a **delay helper** (it does `muls`+poll on a free-running timer, has 70+ callers across firmware; see disasm of 0x1adc: `bl 0x1ec; muls; bl 0x1ec; sub; cmp; blo` loop). Confirms timing-sensitive HW sequencing.
- On poll timeout, falls through to `bl 0x11e8` with a movw literal (0x1273 = 4723 decimal, likely a file/line or error-code constant passed to a printf/assert — 0x11e8 ends with `svc #0` after `bl 0xa30`).

Low address (0x1415c ≈ 80 KB into image) does **not** indicate compiler helper: this module packs HW drivers and helpers together, and the delay utility itself is at 0x1adc. Compiler runtimes (memcpy etc.) are typically much smaller and leafy — this is 174 bytes with multiple polling loops.

Likely purpose: **"enable/disable some PHY or PMU block" with busy-wait on ready/done status bit**. r1 selects direction (0 = enable path taken at 0x68321).

---

## 3. BL / BLX calls (body only, r1=0 branch and shared tail)

Caller uses r1=0, so the `cbnz r1, 0x141b8` at 0x1416a falls through. The r1≠0 branch (0x141b8…0x141ea) is listed for completeness but NOT on the live path from 0x68321.

| # | addr     | insn          | target  | return PC (saved-LR) | one-liner |
|---|----------|---------------|---------|----------------------|-----------|
| 1 | 0x14182  | bl #0x1adc    | 0x1adc  | **0x14187**          | delay(0x40) before first poll |
| 2 | 0x1418a  | bl #0x1adc    | 0x1adc  | **0x1418f**          | delay(0xa) inside poll loop (repeats up to ~2000×) |
| 3 | 0x141b2  | bl #0x11e8    | 0x11e8  | **0x141b7**          | printf/assert on poll timeout ("giving up" log) |
| 4 | 0x141d4  | bl #0x1adc    | 0x1adc  | **0x141d9**          | delay(0xa) inside r1≠0 loop (NOT on live path) |

All BLs are 4-byte Thumb-2. Return address = instr_addr + 4 with Thumb bit (= odd, matches normal firmware saved-LR encoding).

No BLX instructions in the body. No sub-frame that pushes to an address lower than 0x9CEC8 (only call target 0x1adc itself pushes further — that call frame is DEEPER than fn 0x1415c).

---

## 4. Polling / loop analysis

### Loop A (0x14188 – 0x141a0) — LIVE on current hang path (r1=0)

```
0x14188: 0a20       movs r0, #0xa
0x1418a: edf7a7fc   bl   #0x1adc        ; delay(10)
0x1418e: 0a3e       subs r6, #0xa       ; decrement counter (was 0x4e29)
0x14190: d4f88830   ldr.w r3, [r4, #0x88]
0x14194: d3f8e021   ldr.w r2, [r3, #0x1e0]
0x14198: 12f4003f   tst.w r2, #0x20000  ; test bit 17
0x1419c: 01d1       bne  #0x141a2       ; break out if set
0x1419e: 092e       cmp  r6, #9
0x141a0: f2d1       bne  #0x14188       ; loop until counter ≤ 9
```

- Reads `[[r4+0x88]+0x1e0]` (a 32-bit HW status register).
- Waits for bit 17 (0x20000) to become 1.
- If status never sets, loop runs ~2000 times (~tens of ms of delay) then falls through.
- **Prime hang candidate** if the HW block never asserts this ready bit. Delays into 0x1adc are bounded; hang would manifest as "fn takes a long time then continues" — not an infinite hang by itself. BUT if something panics inside 0x1adc (uncommon given 70 callers) or if the status read itself stalls the bus, we'd see it.

### Loop B (0x141d2 – 0x141ea) — NOT on live path (r1≠0 branch)

Mirror of Loop A with the same polling idiom. r1=0 on current call, so this code is unreached from 0x68321.

---

## 5. Fixed-TCM writes

No writes to fixed immediate addresses (no `str r?, [#imm]` or `movw/movt; str` pattern).
All stores are register-indirect via the struct pointer:

- `str [r3, #0x1e0]` at 0x1417e (RMW set bit 1)
- `str [r3, #0x1e0]` at 0x141f8 (RMW clear bit 1 at fn exit)
- `strb [r4, #0x109]` at 0x14204 (write a flag byte to struct)

No useful breadcrumbs can be planted from a kernel probe by watching fixed TCM addresses for this function. A probe would need the struct pointer (r0 = 0x??? value held in r4 from the caller).

---

## 6. Recommendations for test.105

**Target priority**: confirm whether we're parked inside the delay helper 0x1adc called from fn 0x1415c.

### Candidate LR slots to read

When fn 0x1415c calls 0x1adc, `0x1adc` pushes `{r3, r4, r5, lr}` (N=4) into its own new frame → body_SP of 0x1adc = 0x9CEC8 − 16 = 0x9CEB8, and 0x1adc's saved-LR-slot = 0x9CEB8 + 12 = **0x9CEC4**.

Test.105 should read (in order of likelihood given r1=0 on caller):

| Read @ | Expected value (if parked here) | Meaning |
|--------|---------------------------------|---------|
| **0x9CEC4** | **0x1418f** (Thumb bit) | parked inside 0x1adc called from Loop A body (BL #2) — HIGHEST LIKELIHOOD |
| 0x9CEC4 | 0x14187 | parked inside 0x1adc called from BL #1 (pre-loop) |
| 0x9CEC4 | 0x141b7 | parked inside 0x11e8 (timeout printf) — unlikely unless hung in log sink |
| 0x9CEB8..0x9CEC0 | anything | saved r3/r4/r5 of 0x1adc — useful to identify which sub-sub-frame if parked deeper |

Also keep test.104's read of 0x9CED4 as a stability anchor (should still be 0x68321).

If 0x9CEC4 is **not** 0x1418f/0x14187/0x141b7, then 0x1adc has already returned and we're still inside fn 0x1415c's body — next step would be to inspect r6 counter (stack-saved at 0x9CED0) to see if the poll loop is mid-run or we've fallen through to 0x141ac/0x141b2.

Because fn 0x1415c has only **3 distinct BL callsites on the live r1=0 path** (all to 0x1adc except the timeout printf), three specific values cover the entire call space — no dense sweep needed.

---

## 7. Function end address

Epilogue `pop {r4, r5, r6, pc}` at 0x14208 (bytes `70bd`).
Next instruction (`nop` at 0x1420a) is padding; 0x1420c begins a new, unrelated function (`cbz r4, ...` / `bx lr` at 0x14220).

**Function end (last byte of matching pop): 0x14209.**
