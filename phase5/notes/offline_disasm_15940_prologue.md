# Offline disasm: fn 0x15940 prologue — T1 anchor validation

Purpose: confirm whether fn 0x15940 (target of BL row 15 at 0x68326 in caller fn 0x6820c) would, if currently active, leave the earlier BL row 14 return value 0x68321 untouched at [0x9CED4].

Disassembler: capstone Thumb-2 on `/lib/firmware/brcm/brcmfmac4360-pcie.bin`.

---

## 1. Prologue bytes

```
0x15940: f1 f1 ff 3f     cmp.w  r1, #-1
0x15944: 2d e9 f0 41     push.w {r4, r5, r6, r7, r8, lr}
0x15948: 04 46           mov    r4, r0
0x1594a: 0d 46           mov    r5, r1
0x1594c: 04 d1           bne    #0x15958
0x1594e: d0 f8 94 30     ldr.w  r3, [r0, #0x94]
0x15952: 5d 6a           ldr    r5, [r3, #0x24]
0x15954: 1d b1           cbz    r5, #0x15958
0x15956: 58 68           ldr    r5, [r3, #0x18]
```

No `sub sp, #imm` anywhere in the prologue before first body use. (Scanned through 0x159a0 for any sp-relative or sub-sp insn; none in this window — and SP is also used directly to read args only after the push.)

## 2. Frame math

- Push set: `{r4, r5, r6, r7, r8, lr}` → **N = 6 registers**
- push_size = 4·N = **24 bytes**
- sub_imm = **0**
- **total_frame = 24 bytes**

With caller_SP = 0x9CED8 at the BL at 0x68326:

- body_SP = 0x9CED8 − 24 = **0x9CEC0**
- Saved-reg layout (ARM push order, low → high address):
  ```
  0x9CEC0: saved r4      ← body_SP
  0x9CEC4: saved r5
  0x9CEC8: saved r6
  0x9CECC: saved r7
  0x9CED0: saved r8
  0x9CED4: saved LR = 0x6832b   (return to caller after BL row 15)
  ```
- Saved-LR slot = body_SP + 4·(N−1) = 0x9CEC0 + 20 = **0x9CED4**

## 3. Verdict: [0x9CED4] IS OVERWRITTEN

fn 0x15940's prologue writes its saved LR to exactly [0x9CED4]. The saved LR it would write is **0x6832b** (return PC of BL row 15 in fn 0x6820c, i.e. PC of next insn 0x68328 + Thumb-bit).

Since our observed T1 value at [0x9CED4] is **0x68321** (the BL row 14 return) and NOT 0x6832b, fn 0x15940 cannot be the currently active frame on top of caller 0x6820c — if it were active, its own push would have clobbered [0x9CED4] with 0x6832b.

### Concretely

| Scenario                        | Value at [0x9CED4] |
|---------------------------------|--------------------|
| fn 0x1415c active (N=4 push)    | 0x68321 (LR of BL row 14) ← matches test.104 |
| fn 0x15940 active (N=6 push)    | 0x6832b (LR of BL row 15) — NOT observed     |

T1 = 0x68321 at [0x9CED4] therefore **still proves fn 0x1415c is the active frame** (or at least rules out fn 0x15940 as active). The anchor is sound.

## 4. Additional guardrail

Even if fn 0x15940 later performed a `sub sp, #imm` deeper in its body (after the prologue), that does not resurrect the overwritten [0x9CED4] — the `push.w {…, lr}` at 0x15944 already committed the store. Any subsequent sub sp only makes the active body_SP lower, never higher; it cannot "re-expose" the pre-push value of that slot.

Hence: T1 anchor validated. fn 0x1415c remains the sole consistent active-frame hypothesis.
