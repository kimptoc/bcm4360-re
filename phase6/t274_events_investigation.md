# T274-FW — Pending-events writers + pcidongle_probe tail + HOSTRDY_DB1 protocol check

**Date:** 2026-04-24 (post-T273-FW)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Read-only capstone disassembly + literal-pool + ARM vector-table analysis.
**Scripts:** `phase6/t274_events_writers.py`, `phase6/t274_broad_scan.py`, plus ad-hoc helpers in `/tmp`.
**Clean-room note:** plain-language description with short illustrative snippets.

## TL;DR

Four significant findings that reframe the hang picture:

1. **T255/T256 data shows `pciedngl_isr` IS registered.** Scheduler callback list at 0x9627C has node[0]={next=0x96F48, fn=0x1C99 (pciedngl_isr), arg=0x58CC4, flag=0x8}. So `pcidongle_probe` DID run far enough to call `hndrte_add_isr`. This contradicts my earlier "pcidongle_probe never reached" reading (which was based on T247's sharedram-addr-unchanged). The correct reading is: pcidongle_probe ran PAST hndrte_add_isr but failed/stopped BEFORE sharedram publish.

2. **pcidongle_probe (0x1E90) is short (232 bytes) and has a clear structure**: alloc devinfo, init fields via 5 helpers, call `hndrte_add_isr` at 0x1F28, check success, call post-reg finalizer `fn@0x1E44` at 0x1F38, then return. No sharedram publish inside pcidongle_probe itself.

3. **fn@0x1E44 and its sub-calls are SHORT and CLEAN** — no polling loops. fn@0x1E44 is 68 bytes, writes computed values to devinfo+0x38 and [devinfo_substruct+0x100], calls 0x2F18 (struct init, ~116B, clean) and 0x2DF0 (1-insn `bx lr`), tail-calls 0x1DD4 (114B, single-pass msg-queue setup).

4. **Fw does NOT reference HOSTRDY_DB1 (0x10000000) in code.** 5 literal-pool-aligned byte matches exist but all are false positives (no LDR pc-rel or MOVW/MOVT encoded reference). This fw version (RTE 6.30.223 TOB, older) **does not use the HOSTRDY_DB1 advertisement protocol**. The upstream brcmfmac `brcmf_pcie_hostready` (gated on `shared.flags & HOSTRDY_DB1`) would therefore NEVER fire on this chip — upstream normal operation doesn't write H2D_MAILBOX_1 during probe.

## 1. Scheduler callback list shows pciedngl_isr IS registered

Reinterpreted T256 data:

```
TCM[0x9627c..0x962bc] = 00096f48 00001c99 00058cc4 00000008 ...
```

Decoded as the RTE scheduler's callback linked-list head node:
- `[+0x00] next = 0x96F48`
- `[+0x04] fn   = 0x1C99` (thumb) → pciedngl_isr at 0x1C98
- `[+0x08] arg  = 0x58CC4` (pointer into pciedngldev struct region)
- `[+0x0C] flag = 0x00000008` (bit 3)

This is identical to the "pciedngl_isr scheduler node" as hndrte_add_isr would create it (per T269 §4). Therefore **pcidongle_probe's call to hndrte_add_isr at 0x1F28 completed successfully**, and the node was prepended to the list.

The NEXT pointer (0x96F48) points to another node that T256 didn't probe. That's likely the wlc ISR (fn@0x1146C from T273). So the full list is probably `pciedngl_isr → wlc_fn@0x1146C → [terminator]`.

## 2. pcidongle_probe body structure (0x1E90..0x1F78, 232 bytes)

```
0x1e90  push prologue + arg capture (r6, r8, sb, fp, sl)
0x1ea2  bl #0xa30          ; printf("pciedngl_probe")
0x1eac  bl #0x66e64        ; helper (unknown role)
0x1eb6  bl #0x7d60         ; alloc(0x3c) = 60 bytes
0x1ece  bl #0x91c          ; memset to 0
        several stores populating the alloc'd struct
0x1ee8  bl #0x67358        ; helper (unknown role)
0x1ef2  bl #0x9948         ; class-dispatch helper
0x1efa  bl #0x9964         ; class-dispatch helper
0x1f08  bl #0x64248        ; helper (returns fn-ptr or handle)
        checks r0 != 0
0x1f28  bl #0x63c24        ; hndrte_add_isr (REGISTERS pciedngl_isr)
0x1f2c  cbz r0, #0x1f36    ; on success (r0 == 0) → proceed
0x1f38  bl #0x1e44         ; POST-REGISTRATION FINALIZE
0x1f3c  mov r0, r4         ; return devinfo
0x1f3e  b #0x1f4a          ; → return
0x1f4a  pop epilogue
```

Error paths (0x1EC6, 0x1F18, 0x1F34, 0x1F50) all converge at 0x1F40 which:
- Logs `pciedev_msg.c` line 0xAD via `bl #0x11e8` (error trace).
- Returns 0.

## 3. fn@0x1E44 post-registration finalizer (68 bytes)

```
0x1e44  ldr r3, [pc, #0x44]   ; r3 = &lit (pts to 0x62ea8, a global struct)
0x1e46  push {r0-r2, r4, r5, lr}
0x1e48  ldr r3, [r3]           ; r3 = *0x62ea8 = some config/struct pointer
0x1e4a  mov r4, r0             ; r4 = devinfo
0x1e4c  ldr r2, [r0, #0x18]    ; r2 = *(devinfo+0x18) = ISR_STATUS sub-struct ptr
0x1e4e  add.w r5, r4, #0x24
0x1e52  ldr r1, [r3, #4]
0x1e54  bic r1, r1, #0xfc000000
0x1e58  orr r1, r1, #0x8000000
0x1e5c  str r1, [r0, #0x38]    ; devinfo->[0x38] = (r1_low_26 | 0x8000000)
0x1e5e  ldr r0, [r3, #4]
0x1e60  and r0, r0, #0xfc000000
0x1e64  orr r0, r0, #0xc
0x1e68  str.w r0, [r2, #0x100] ; *(ISR_STATUS_sub+0x100) = (r0_high_6 | 0xc)
0x1e6c  mov r0, r5             ; r0 = &devinfo[0x24]
0x1e6e  ldr r2, [r3, #0xc]
0x1e70  movs r3, #1
0x1e72  str r3, [sp]
0x1e74  subs r3, #1
0x1e76  bl #0x2f18             ; helper (struct init) — clean
0x1e7a  mov r0, r5
0x1e7c  bl #0x2df0             ; no-op (`bx lr`)
0x1e80  mov r0, r4
0x1e82  add sp, #0xc
0x1e84  pop.w {r4, r5, lr}     ; restore caller's lr
0x1e88  b.w #0x1dd4            ; TAIL-CALL to fn@0x1DD4 with caller's lr
```

### 3.1 Significant: [ISR_STATUS_sub + 0x100] initialization

The write at 0x1E68 initializes the word at offset 0x100 of the ISR_STATUS sub-struct (the same offset that `pciedngl_isr` reads at `*(pciedev+0x18)+0x18)+0x20` — wait, that's a different offset chain). Let me reconcile: pciedngl_isr reads the **ISR_STATUS register** at `*(arg+0x18)+0x18)+0x20` (three levels deep). fn@0x1E44 writes `*(devinfo+0x18)+0x100` (two levels deep). Different offsets; different fields.

The value written at 0x1E68 is `(config_word & 0xfc000000) | 0xc` — high 6 bits of a config word OR'd with constant 0xc (12 = four low bits). This looks like an **initialization of a hardware mailbox enable/mode register** via a TCM mirror.

### 3.2 Tail-call to fn@0x1DD4

After `pop.w {r4, r5, lr}` at 0x1E84 (restoring caller's lr), `b.w #0x1dd4` at 0x1E88 jumps to 0x1DD4 with caller's lr intact. So 0x1DD4 is effectively a tail-call continuation. When 0x1DD4 returns (via its own `bx lr`), control goes directly back to pcidongle_probe's caller.

## 4. fn@0x1DD4 — message-queue setup (114 bytes)

```
0x1dd4  push {r4, r5, lr}
0x1dd6  movs r4, #0xa           ; counter = 10
0x1dda  mov r5, r0               ; r5 = devinfo
0x1ddc  movs r1, #0xc4           ; size = 196
0x1de0  str r4, [sp, #0xc]       ; sp[0xc] = 10 (output parameter)
0x1de2  bl #0x7d60               ; alloc(196)
0x1de6  str r0, [r5, #0x20]      ; devinfo->[0x20] = buffer
0x1de8  cbnz r0, #0x1df8         ; if alloc ok → 0x1df8
... (alloc-fail: error trace 0xc8, returns -1)
0x1df8  ldr r2, [pc, #0x40]      ; r2 = &global
0x1dfc  str r0, [r2]             ; global = buffer
0x1e00  bl #0x91c                ; memset(buffer, 0, 196)
0x1e06  add r2, sp, #0xc         ; r2 = &sp[0xc] (output)
0x1e08  str r3, [sp]
0x1e0a  mov.w r3, #0x400         ; arg3 = 1024
0x1e0e  ldr r0, [r5, #0x10]      ; r0 = devinfo->[0x10]
0x1e10  ldr r1, [r5, #0x20]      ; r1 = devinfo->[0x20] = buffer
0x1e12  bl #0x66a60              ; MSG-QUEUE READ helper
0x1e16  mov r5, r0               ; r5 = return value
0x1e18  cbnz r0, #0x1e2a         ; if non-zero → error exit
0x1e1a  ldr r1, [sp, #0xc]       ; r1 = updated sp[0xc]
0x1e1c  cmp r1, #9
0x1e1e  bgt #0x1e32              ; if r1 > 9 → exit
0x1e20  mov r2, r4
0x1e22  ldr r0, [pc, #0x1c]      ; format string
0x1e24  bl #0xa30                ; printf (short-read trace)
0x1e28  b #0x1e32                ; exit
0x1e2a  ...error exit (trace line 0xd5)
0x1e32  mov r0, r5               ; return
0x1e34  add sp, #0x14
0x1e36  pop {r4, r5, pc}         ; RETURN to pcidongle_probe's caller
```

No polling loop. Single-pass: alloc → bl #0x66a60 (msg read) → check → return.

### 4.1 bl #0x66a60 is a shared message-queue helper

The call signature here (r0 = devinfo[0x10] = HW descriptor, r1 = buffer, r3 = 0x400 = 1024 bytes max, r2 = output length ptr) matches the pattern T269 identified for pciedngl_isr's bl #0x2E10 (reads HW message into buffer).

Both pciedngl_isr AND fn@0x1DD4 call into the same message-read infrastructure. If bl #0x66a60 polls waiting for a message that never arrives, fn@0x1DD4 hangs. But pcidongle_probe calls fn@0x1DD4 as part of init — if the message queue is empty at init time (which it would be, since no interrupt has fired yet), bl #0x66a60 should return immediately with "no messages" (not poll).

Verifying bl #0x66a60 for hidden polling would be the next cheap step.

## 5. The HOSTRDY_DB1 non-reference finding

Searched for 32-bit literal `0x10000000` in the blob:

| Location | Type | Interpretation |
|---|---|---|
| 0x400 | in data region at ARM reset path | false positive (data bytes) |
| 0x45CAC | in string/data region | false positive |
| 0x504C4 | in string/data region | false positive |
| 0x57C18 | in string/data region | false positive |
| 0x57C20 | in string/data region | false positive |

**None of these locations has an ldr pc-rel or MOVW/MOVT pair that references them.** Expanded search to 8KB backward from each literal — zero matches.

Separately scanned the entire blob for `movt r?, #0x1000` instructions (the upper half of a MOVW/MOVT pair producing 0x10000000) — zero matches.

**Conclusion: fw never references 0x10000000 as a code constant.** This fw version doesn't use the HOSTRDY_DB1 advertisement bit. Upstream brcmfmac's `brcmf_pcie_hostready` (which gates on `shared.flags & HOSTRDY_DB1`) would NEVER fire on this chip even under normal operation.

### 5.1 Implication for the protocol story

Previous sessions' reframe ("fw never reaches sharedram publish, so HOSTRDY_DB1 never set, so host must wait for the gate to clear") is partially incorrect. The fuller statement:

- Fw **never advertises HOSTRDY_DB1 at all**, because fw doesn't know about that bit.
- Upstream brcmfmac's normal operation on BCM4360 **does not call `brcmf_pcie_hostready`**.
- Fw expects wake via a **different mechanism** — unknown from blob static analysis.

The upstream driver for older firmware is probably structured to proceed past `hostready` if the flag isn't set (or skip `hostready` entirely). Worth verifying against upstream.

### 5.2 What this means for scaffold investigation

- Our scaffold (T258–T269) writing H2D_MAILBOX_1 was inappropriate for this fw — there's no reason fw would have FN0_0 unmasked/handled at any well-defined point, since the whole "host signals ready via doorbell" protocol isn't what this fw uses.
- The "scaffold wedges host on MSI subscription" issue (T262/T263/T264/T265/T266) is separate and independent of any fw protocol question.
- If we want to understand what event wakes fw, we need to look at **message-queue / CDC / iovar** pathways — not mailbox-doorbell.

## 6. Writers of the pending-events word: none found directly

Searched the blob for writers at the expected offset patterns:
- `str [r?, #0x100]` → 0 hits
- `str [r?, #0x458]` (= #0x358 + #0x100 flat) → 0 hits
- `str [r?, #0x358]` (setting the intermediate ptr) → 0 hits
- `orr` following `ldr [r?, #0x100]` (bit-set pattern) → 0 hits
- `add r?, r?, #0x100` followed by `str` (compute-address pattern) → 2 hits, both unrelated (stack frame adjustments)

**This strongly suggests the pending-events word at `*(ctx+0x358)+0x100` is not software-maintained.** More likely:

- **Hardware-mapped**: `*(ctx+0x358)` points to a backplane-mapped interrupt-status register. Reads return HW-latched bits; writes are W1C to ack.
- OR **updated via memory-mapped DMA** from another CPU core (coprocessor / PHY-CPU).

This changes the "pending-events" model: it's not a software bitmap the RTE fills — it's a HW status register the RTE reads. Bits get set by HW events, cleared by fw writes.

### 6.1 Correcting T269 §2 interpretation

T269 described `*(ctx+0x358)+0x100` as "a software-maintained 32-bit 'pending events' word". Evidence now says it's HW-maintained. The scheduler reads it like any HW status register, and dispatches callbacks when bits are set by HW.

### 6.2 Implication for fn@0x1146C and pciedngl_isr triggers

Both fn@0x1146C (wlc) and pciedngl_isr (pciedngl) are registered via hndrte_add_isr, which allocates a bit index in this HW-maintained word. The bit allocation is from a shared pool. When the HW sets that bit (via its own logic — e.g., because a mailbox interrupt fired), the scheduler dispatches the matching callback.

For pciedngl_isr the HW event is: `H2D_MAILBOX_1` write (bit 3 in the pending-events word via the FN0 interrupt path).
For fn@0x1146C, the HW event is... unknown. Could be:
- A different mailbox bit (fn0 bits 4-7?).
- A timer expiry (but scheduler state frozen across 23 dwells rules out periodic timers).
- A WLC-specific HW event (e.g., MAC TBTT, PHY calibration complete).

## 7. ARM IRQ vector finding (context)

ARM vector table at blob offset 0x00: Thumb-2 `b.w` branches to handlers. IRQ handler at 0x18 → 0xF8. Handler:

1. Saves state via `srsdb sp!` + `cps #0x1f` + `push` chain.
2. At 0x162: `ldr r4, [pc, #0x24]` loads pointer at lit@0x188 = 0x224.
3. `ldr r4, [r4]` → r4 = *0x224 = ISR dispatcher fn-ptr.
4. `cmp r4, #0` → if NULL, `beq #0x168` (infinite self-loop).
5. Else `blx r4` to dispatch.

**[0x224] is NULL in the blob image.** No code was found that writes to address 0x224. Either:

- [0x224] is SUPPOSED to be NULL in this fw (the dispatcher runs via a different path — maybe VBAR-remapped ARM vectors).
- Or a writer exists via an indirect addressing mode I didn't spot.
- Or fw runs in a state where the ARM IRQ vector is never taken (CPU IRQs always disabled).

If [0x224] stays NULL at runtime AND any IRQ fires, fw would spin in 0x168. But T257/T255 say fw is in WFI (cooperative sleep), not stuck in 0x168. So either no IRQ is firing (consistent with observed: host doesn't generate any IRQ), OR the dispatcher is installed differently.

## 8. Open questions (for future work)

1. **What writes to [0x224]?** If no writer exists, ARM IRQs would infinite-loop. Either (a) the blob uses ARM's VBAR-relocated vectors with a different IRQ handler, OR (b) IRQs are never enabled, OR (c) the writer uses an obscure addressing mode. Worth a deeper scan.
2. **What fires fn@0x1146C's flag bit?** Given the pending-events word is HW-maintained, this reduces to "which HW event sets wlc's allocated bit". Requires reading the wlc-class slot in the 9-thunk vector (0x99AC..0x99C8 — only one of the 9 targets corresponds to wlc's class, per `*(ctx+0xCC)`).
3. **What's the true wake protocol?** If HOSTRDY_DB1 isn't advertised, the normal host→fw wake pathway is different. Upstream brcmfmac protocol for older fw needs auditing.

## 9. Recommended next steps

### 9.1 If continuing static analysis

Most productive question: **what writes to the pending-events word at the HW level?** This has two paths:

a. Trace writers of `[r?+0x254]` (the HW-regs pointer seen in 4 of the 9-thunk vector targets at 0x28AE / 0x28E2 / 0x29AC / 0x2A4C) and see what offsets they write.
b. Identify WLC's class index via the literal value that `*(ctx+0xCC)` evaluates to at runtime (a known value should be derivable from fw boot init).

### 9.2 If pivoting to upstream audit

Audit upstream brcmfmac for older-fw compatibility:
- Check if `brcmf_pcie_hostready` has any "advertise fallback" when HOSTRDY_DB1 isn't set in shared.flags.
- Check if there's a different probe path for "no shared.flags published" (maybe fw without shared-struct is a legacy mode).
- If upstream has a "direct attach" mode for older fw, adopt it.

### 9.3 If pivoting to hardware

Design T274-OBS hardware probe that samples:
- TCM[ramsize-4] at each dwell (re-confirms T247 result).
- The pending-events word at runtime (compute its location via `[ctx+0x358]` where ctx = `*[0x6296C]` = 0x62A98 per T255). Address would be `*0x62A98+0x358+0x100`. Dereference the chain live.
- The ISR dispatch pointer at [0x224].

These are cheap reads; substrate budget-permitting. Would narrow "is fw really stuck" vs "is something changing slowly that we missed."

## 10. Clean-room posture

All findings are disassembled mnemonics + literal-pool analysis + ASCII-string cross-reference + Thumb-2 branch-decode. No reconstructed function bodies; illustrative snippets only. Scripts are in `phase6/t274_*.py` and `/tmp/t274_*.py` (the latter should be moved to phase6 if retained).
