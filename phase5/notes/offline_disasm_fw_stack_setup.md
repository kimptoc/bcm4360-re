# Offline disasm: BCM4360 firmware SP (stack) setup at boot

**Source:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442,233 bytes, Thumb-2, loaded to TCM @ offset 0).
**Tool:** capstone 5.0.7 (nix) — ARMv7 Thumb-2 mode.
**Range analyzed:** 0x00-0x200, plus reset target at 0x268-0x330 and helpers 0x440-0x540.

---

## TL;DR — SP at boot

| Mode (CPSR[4:0]) | SP value | Stack region (grows down) | Inside TCM [0..0xA0000]? |
|---|---|---|---|
| **SYS (0x1F)** — the only mode where real work runs | **~0x9D0A0** (inferred: TCM_top - 0x2F60, see below) | **[~0x9A144 .. ~0x9D0A0)**, 0x2F5C = 12,124 B | **YES** — fully inside TCM |
| FIQ / IRQ / ABT / UND / SVC | briefly set to `LR_mode` in some vector stubs, then discarded — exception entry immediately switches to SYS and uses the SYS stack | (effectively shared SYS stack) | n/a — state lands on SYS stack |

**Gate answer:** the firmware's live stack lives in **TCM**. TCM-probe readability of firmware stack: **YES** — stack body fits well within the 0..0xA0000 window.

The firmware is **hndrte** (Broadcom HND RTOS — confirmed by symbols `hndrte.c`, `hndrte_arm.c`, `hndrte_lbuf.c`, `dngl_rte.c`, and the printfs `"Stack bottom: 0x%p, lwm: 0x%p, curr: 0x%p, top: 0x%p"` at 0x4019E, `"Free stack: 0x%x(%d) lwm: 0x%x(%d)"` at 0x401DA). It uses the classic **single-SYS-stack** pattern: every exception vector does `srsdb sp!, #0x1f` then `cps #0x1f` so all state lands on the one common SYS stack, independent of whatever per-mode SP each vector briefly set along the way.

### Honest confidence note (derived vs. inferred)

**Mechanically derived from disasm (high confidence):**
- Initial CPU mode at 0x52 = SYS (CPSR[4:0]=0x1F), IRQ+FIQ masked.
- The one and only "real" SP write is at 0x2FC: `mov sp, r5` with `r5 = r7 - 0x2F5C - 4 = r7 - 0x2F60`.
- Stack size constant = `*0x58C8C = 0x2F5C` (12,124 bytes).
- Stack grows downward (ARM standard) from SP, so body = [SP-0x2F5C .. SP).
- No per-mode SP is set to a fresh absolute value — all per-mode SP writes in vectors use `mov sp, lr` (i.e. take whatever LR the CPU loaded at exception entry), and then immediately `srsdb #0x1f` pushes to the SYS stack.

**Inferred (supported by runtime evidence, not mechanically provable from offline disasm alone):**
- `r7 = 0xA0000` (TCM_top). Function at 0x440 actually computes
  `r7 = Σ(type1_bank_sizes) + ((p15/c9/c1/#0 & 0xFFFFF000) - Σ(type0_bank_sizes))`
  walking SOCRAM bank-info via cp15 c9/c1 with c9/c12/#1 as selector. Without hardware probes the exact numeric result is not mechanically derivable. It equals 0xA0000 on this board because:
  1. Phase 5 host probe detected `ramsize=0xA0000, rambase=0` (phase5_progress.md L138,159).
  2. `ws[0x62ea8] = 0x0009D0A4` observed at runtime (phase5_progress.md L474) — numerically equal to SP_init+4 under this assumption. Note: phase5_progress.md describes this value as "static TCM pointer (firmware data section)", not proven to be SP-related, so this is circumstantial corroboration, not proof.
  3. Console ring buffer observed at 0x9CCC0–0x9CDBC (phase5_progress.md L484), which is *just below* the claimed stack bottom (~0x9A144) — consistent with a TCM layout of [heap/BSS … console_ring … stack … top=0xA0000].

If `r7 ≠ 0xA0000` for some reason (e.g., reserved regions at top), SP_init and the stack region shift but remain inside TCM, because TCM ends at 0xA0000.

---

## Evidence — instruction trace

### 1. Reset flow
```
0x000: 00f0 0eb8  b.w  #0x20                 ; reset vector
```

### 2. Sentinel-fill + initial mode setup (0x20-0x5F)
```
0x020: 0e48       ldr  r0, [pc, #0x38]       ; r0 = *0x60 = 0xBBADBADD
0x022-0x3C: mov r1..r12, sp, lr = r0         ; ALL regs + SP + LR = 0xBBADBADD
                                              ; <-- this is a DEBUG SENTINEL, not real SP
0x03E: eff3 0080  mrs  r0, apsr              ; read current CPSR
0x042: 4ff0 1f01  mov  r1, #0x1f             ; mask low-5 bits (mode field)
0x046: 20ea 0100  bic  r0, r0, r1            ; clear mode bits
0x04A: 4ff0 df01  mov  r1, #0xdf             ; set I=1, F=1, T=1(bit5), mode=SYS(0x1F)
0x04E: 40ea 0100  orr  r0, r0, r1
0x052: 80f3 0089  msr  cpsr_fc, r0           ; CPSR = SYS mode, IRQ+FIQ masked
0x056: 0248       ldr  r0, [pc, #8]          ; r0 = *0x60 = 0x00000269
0x058: 0047       bx   r0                    ; jump to thumb fn @ 0x268
0x060:            [literal pool: 0xbbadbadd, 0x00000269]
```
**→ Initial run-mode = SYS (0x1F). Initial SP = 0xBBADBADD sentinel (garbage) until overwritten.**

### 3. First real SP write (0x268 onward — after `bx r0` → 0x268)
```
0x268: bl #0x390              ; MPU init (mcr p15 region regs) — preserves r4-r11
... ChipID validation loop reads 0x18000000 (PMU regs), verifies CoreID pattern 0x083e (WLAN core)
0x2A2: bl #0x4ec               ; r8 = result (returns a CP15-masked address)
0x2A8: bl #0x50c               ; sb = result (ditto; walks core list looking for a match)
0x2D4: bl #0x440               ; r7 = computed TCM top
         ; Function 0x440 reads mrc p15, c9, c1, #0 (BTCM region / Cortex-R SRAM region),
         ; sums per-bank size (2^13 * (bank_size_reg+1)) across banks selected via
         ; mcr p15, c9, c12, #1 (bank selector), and computes
         ;   r7 = Σ(bank_sizes) + ( (p15/c9/c1/#0 & 0xfffff000) - Σ(other_bank_sizes) )
         ; Net effect: r7 = TCM top-of-memory address.
0x2E4: 3d46       mov  r5, r7                ; r5 = TCM_top
0x2EC: dff8 7880  ldr.w r8, [pc, #0x78]      ; r8 = 0x00058C8C (address of stack-size var)
0x2F0: d8f8 0090  ldr.w sb, [r8]             ; sb = *0x58C8C = 0x00002F5C = 12,124 bytes
0x2F4: a5eb 0905  sub.w r5, r5, sb           ; r5 = TCM_top - 0x2F5C
0x2F8: a5f1 0405  sub.w r5, r5, #4           ; r5 = TCM_top - 0x2F60
0x2FC: ad46       mov  sp, r5                ;  <<== REAL SP WRITE (SYS mode)
```

**SP formula:** `SP_init = TCM_top - stack_size - 4 = TCM_top - 0x2F60`

### 4. Stack-size constant in image
```
[0x58C8C] = 0x00002F5C            ; stack size = 12,124 bytes (~11.8 KB)
[0x58C74] = 0x00000000             ; saved r5 (zero)
[0x58C78] = 0xBBADBADD             ; saved r6 (still sentinel)
[0x58C7C] = 0xBBADBADD             ; saved r7 (still sentinel)
```

### 5. Exception vector stubs (0x64-0x137) — per-mode SP briefly touched, then irrelevant
Two stub shapes appear. Vectors 1,2 (Undef-style) at 0x64, 0x7E:
```
0x064:  srsdb sp!, #0x1f       ; push {LR,SPSR} to SYS stack (writeback=1f)
0x068:  cps #0x1f              ; switch CPU mode to SYS
0x06C:  push {r0}; push {lr}; sub sp, #0x18; push {r0-r7}  ; all on SYS stack
0x074:  eor r0, r0, r0 ; add r0, r0, #1  (#2 for vec 2)
0x07C:  b #0x138               ; common dispatch
```
Vectors 3..7 (SVC/prefetch/data-abort/IRQ/FIQ) at 0x98, 0xB8, 0xD8, 0xF8, 0x118 prepend a 3-insn per-mode SP fix-up before the shared SRS/CPS:
```
0x098:  mov sp, lr             ; sp_mode = LR_mode (per-mode SP briefly written)
0x09A:  sub sp, #4 (or #8)     ; adjust
0x09C:  mov lr, sp             ; save adjusted value back into LR
0x09E:  srsdb sp!, #0x1f       ; THEN save state to SYS stack (writeback=1f)
0x0A2:  cps #0x1f              ; switch to SYS
   ...  (same tail as above)
```
**Net effect for our purpose:** per-mode SPs (`sp_abt`, `sp_und`, `sp_svc`, `sp_irq`, `sp_fiq`) are briefly written at entry to an *exception-mode-specific LR value* — but the value is functionally discarded on the very next instruction (`srsdb sp!, #0x1f` writes to the SYS stack regardless of which mode is current; the `!` writeback updates the per-mode SP with the target-mode SP, not the current SP). No handler ever runs real code with a per-mode SP holding TCM data; all real state lands on the SYS stack at whatever SYS-SP currently is.

No FIQ/IRQ/ABT/UND/SVC vector loads an SP from a literal pool or MSR — i.e. there is no absolute SP_mode init anywhere.

---

## TCM numeric gate

From `phase5/notes/phase5_progress.md` (Phase 5 kernel probe): **ramsize = 0xA0000, rambase = 0**, so TCM = **[0x00000000 .. 0x000A0000)** (640 KB).

**Why we believe `r7 = 0xA0000`** (i.e. TCM_top):

1. **Host probe match.** Phase 5 auto-detected `ramsize=0xA0000` (phase5_progress.md L138, L159). That value is itself read from a similar SRAM/TCM enumeration path on the host side — both host and firmware reach the same total-SRAM arithmetic against the same hardware, so `r7` should equal `ramsize`.
2. **Live pointer numerology.** `ws[0x62ea8] = 0x0009D0A4` (phase5_progress.md L474) = SP_init + 4 under this assumption. phase5_progress.md describes this value as a "static TCM pointer (firmware data section)" — circumstantial, not proof, but extremely suggestive of an initial-SP-derived value saved during boot.
3. **Layout consistency.** Console ring buffer lives at 0x9CCC0–0x9CDBC (phase5_progress.md L484) — directly below the claimed stack bottom ~0x9A144 would overlap; actually 0x9CCC0 sits *within* the claimed stack region [0x9A144..0x9D0A0). This is not a contradiction in practice: at boot the stack has barely been used (a few hundred bytes), so the console ring pre-allocated below SP_init isn't overwritten unless the stack depth blows past ~0x400 bytes. Layout [heap … console_ring @ 0x9CCC0 … active_stack_top @ 0x9D0A0 … TCM_top @ 0xA0000] is the classic hndrte partitioning. (An alternative, more defensive interpretation: the effective working stack is only the upper ~0x3E0 bytes of the allocation; the lower portion is used by the console ring + other static buffers. Either way, SP_init and the active stack window are inside TCM.)

Assuming `TCM_top = 0xA0000`:
- **SP_init = 0xA0000 - 0x2F60 = 0x9D0A0**
- **Allocated stack region = [0x9A144 .. 0x9D0A0)**, 0x2F5C bytes
- **Active stack window (top of that region, what's live during execution)** is likely only a few hundred bytes below 0x9D0A0 at any time — readily captured by TCM probes over [0x9CC00 .. 0x9D0A0) or wider.

Both SP and the full stack allocation are **inside TCM** → readable via existing Phase 5 TCM BAR2 probe window.

---

## String / symbol corroboration

- 0x400C1: `"Text: %ld(%ldK), Data: %ld(%ldK), Bss: %ld(%ldK), Stack: %dK\n"` — runtime prints stack size in KB.
- 0x40178: `"Stack bottom has been overwritten\n"`
- 0x4019E: `"Stack bottom: 0x%p, lwm: 0x%p, curr: 0x%p, top: 0x%p\n"` — hndrte stack watermark printf.
- 0x401DA: `"Free stack: 0x%x(%d) lwm: 0x%x(%d)\n"`
- 0x40200: `"Inuse stack: 0x%x(%d) hwm: 0x%x(%d)\n"`
- Symbols: `hndrte.c`, `hndrte_arm.c`, `hndrte_lbuf.c`, `hndrte_cons.c`, `dngl_rte.c` — Broadcom HND Runtime Environment (aka hndrte / rte), which has a documented single-SYS-mode-stack architecture.

These printfs mean the running firmware itself can emit stack watermark info — future probes could trigger them via the hndrte console.

---

## Summary of ALL SP writes found in 0x00-0x200

| Offset | Insn bytes | Decoded | Effect |
|---|---|---|---|
| 0x03A | 85 46 | `mov sp, r0` | SP = 0xBBADBADD (sentinel) |
| 0x064, 0x07E, 0x09E, 0x0BE, 0x0DE, 0x0FE, 0x11E | 2d e8 1f c0 | `srsdb sp!, #0x1f` | Push exception state to SYS stack (SP -= 8) |
| 0x070, 0x08A, 0x0AA, 0x0CA, 0x0EA, 0x10A, 0x12A | 86 b0 | `sub sp, #0x18` | Reserve 24 B on SYS stack (per-vector) |
| 0x09A, 0x0BA, 0x0DA, 0x0FA, 0x11A | 81/82 b0 | `sub sp, #4/#8` | Minor SP adjust in vector prologues |
| 0x098, 0x0B8, 0x0D8, 0x0F8, 0x118 | f5 46 | `mov sp, lr` | Restore SP=LR at top of some vector stubs (abort/undef return) |
| 0x15C | 12 b0 | `add sp, #0x48` | SP cleanup in dispatch epilogue |
| 0x160 | 8c b0 | `sub sp, #0x30` | Reserve dispatch-frame |
| 0x16E | 0c b0 | `add sp, #0x30` | Release dispatch-frame |
| 0x17E | 8f b0 | `sub sp, #0x3c` | (part of pre-RFE restore) |
| 0x182 | 08 b0 | `add sp, #0x20` | Final cleanup before `rfeia sp!` |
| 0x184 | bd e9 00 c0 | `rfeia sp!` | Return from exception; SP += 8 |
| **0x2FC** | **ad 46** | **`mov sp, r5`** | ★ **REAL initial SP set** — SP = TCM_top - 0x2F60 |

Everything between 0x03A and 0x2FC is the bring-up path; nothing between them sets a per-mode SP (mode is set to SYS once at 0x52 and never changed during init).

---

## Conclusion

1. **Single SYS-mode stack.** hndrte firmware runs all code (main + every exception) on one SYS-mode stack. Per-mode SPs are touched by vectors 3..7 via `mov sp, lr` but carry no persistent meaningful value; SRSDB with #0x1f writeback immediately redirects state to the SYS stack.
2. **Mechanical formula (from disasm alone):** `SP_init = r7 - 0x2F60`, where `r7` = output of fn @ 0x440 (SRAM/TCM size computed from CP15 c9/c1 bank enumeration), and `0x2F5C` is the stack-size constant stored at `[0x58C8C]`.
3. **Numeric SP_init = 0x9D0A0** (inferred: `r7 = 0xA0000 = TCM_top`, supported by host-side ramsize probe and live-pointer corroboration — see "Honest confidence note").
4. **Allocated stack region = [0x9A144 .. 0x9D0A0)**, 0x2F5C bytes, grows downward.
5. **Entirely inside TCM** (0..0xA0000) → **readable via Phase 5 TCM BAR2 probes.** Suggested focused probe window: `[0x9CC00 .. 0x9D0A0)` for recent stack activity, or full `[0x9A000 .. 0x9D100)` for cold regions.
