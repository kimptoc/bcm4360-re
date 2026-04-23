# T254 Local Blob Analysis — PHY dispatcher subtree scan + key caller anchors

**Date:** 2026-04-23 (post-T253 hardware capture)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Read-only blob disassembly with capstone (`capstone.CS_MODE_THUMB`).
**Scripts:** `phase5/analysis/t254_6a2d8_worker.py`, `t254_dispatch_scan.py`, `t254_poll_detail.py`

## Goal

After T253 settled the saved-state region as a call-context snapshot (branch α), narrow further: which specific function inside the wlc_phy_attach → callee subtree contains the firmware hang? Scan the PHY dispatcher tree and follow advisor-requested cross-checks (WFI, self-loops, chiprev call site, PMCCNTR enable).

## What T254 settled

### 1. 0x6A2D8 is NOT the hang site

Disassembly of 0x6A2D8 (103 instructions, 256 bytes, tail-calls 0x52B8):

- Structured as setup/configure-and-tail-call helper. No backward branches, i.e., **no internal loops of any kind**.
- BL targets: 0x82E (strlen-style), 0xA30 (printf), 0x52B8/0x52E8 (string-parse loops — not HW), 0x7D60 (alloc thunk), 0x14948 (trace), 0x79C, 0x34D88 (predicate tail-calling 0x6A214), 0x7D68 (alloc).
- Tail target 0x52B8 is a comma-separated string iterator (comma-check loop, `cmp r3, #0x2c`), not a hardware poll.

Removed from hang candidates.

### 2. wlc_phy_attach's direct dispatch-table calls are benign

wlc_phy_attach (0x6A954..0x6AED2, 213 insns) invokes the 0x38A50 dispatch table **twice**, both at index 0 (`bl #0x38A50` at 0x6A9E0 and 0x6AAB0). Table-idx-0 thunk forwards to 0x15940.

0x15940 has **zero backward branches → no polling loop**.

Scanned all 17 dispatch-table targets reachable through 0x38A50 / 0x38A24 thunks. Loop-classification results:

| Target | Loops | HW-poll | Weak | Other |
|---|---|---|---|---|
| 0x15940 | 0 | — | — | — |
| 0x1722C | 1 | **YES** | — | — |
| 0x14CAC | 1 | HW-poll | — | — (actually full fn body, see §3) |
| 0x14384 | 1 | — | weak | — (bit-update helper, false positive) |
| all others | 0 | — | — | — |

### 3. 0x1722C is `wlc_bmac_suspend_mac_and_wait` — BOUNDED, not the hang

Trace and error prints in 0x1722C reference the function-name string at blob[0x4B189] = `"wlc_bmac_suspend_mac_and_wait"`. This is a known Broadcom WLC function that tells MAC to suspend then waits for the suspended-state bit.

Polling loop at **0x173D8..0x173EC** (8 insns):

```
0x173D8: movs     r0, #0xA          ; delay 10 units
0x173DA: bl       #0x1ADC           ; delay helper
0x173DE: subs     r7, #0xA          ; countdown
0x173E0: ldr.w    r3, [r4, #0x128]  ; read MAC control/status register shadow
0x173E4: tst.w    r3, #1            ; bit 0 = MAC-suspended-ack
0x173E8: bne      #0x173EE          ; success path exit
0x173EA: cmp      r7, #9
0x173EC: bne      #0x173D8          ; loop back while r7 > 9
```

Initial r7 = literal `0x14441` (82497) at lit@0x173D4 → **~8249 iterations × 10 units = 82497 units of delay** via 0x1ADC helper. On timeout, falls through to 0x173EE (trace + error-path bookkeeping — function continues, does not halt).

### 4. Delay helper 0x1ADC is bounded via CPU cycle counter

```
0x1ADC: push {r3,r4,r5,lr}
0x1ADE: mov   r4, r0              ; r4 = units
0x1AE0: bl    #0x1EC              ; get current cycle count (t_start)
0x1AE4: ldr   r3, [pc, #0x10]     ; r3 = ticks_per_unit scale (0x58C98 in TCM)
0x1AE6: ldr   r3, [r3]
0x1AE8: muls  r4, r3, r4          ; target elapsed = units * scale
0x1AEA: mov   r5, r0              ; r5 = t_start
0x1AEC: bl    #0x1EC              ; read cycle count again
0x1AF0: subs  r0, r0, r5          ; elapsed = now - t_start
0x1AF2: cmp   r0, r4
0x1AF4: blo   #0x1AEC             ; loop while elapsed < target
0x1AF6: pop {...,pc}
```

0x1EC is a trivial CP15 read: `mrc p15, #0, r0, c9, c13, #0; bx lr` — that's **PMCCNTR** (Performance Monitor Cycle Counter).

**Cross-check: is PMCCNTR enabled?** Two PMCR writes found at blob[0x1D6] and blob[0x1DC]:
- `mcr p15, #0, r1, c9, c12, #0` — writes PMCR (control reg, bit 0 = E enable)
- `mcr p15, #0, r1, c9, c12, #1` — writes PMCNTENSET (per-counter enable)

Additionally, fw **demonstrably ran long enough** to print the RTE boot banner and reach wlc_bmac_attach. Any broken-delay scenario would have hung inside very early init. PMCCNTR delay works → all polling loops built on it have finite timeout.

Initial scale factor at blob[0x58C98] = **0x50 (80 cycles/unit)** → `delay(10)` ≈ 800 cycles ≈ 10 µs at ~80 MHz.

So every polling loop in the PHY-dispatch subtree has a bounded walk-clock timeout. **Bounded loops cannot be the silent hang.**

### 5. "40/160/160MHz" last-printed banner is the RTE boot banner, NOT wlc_attach

Blob[0x6BAE5] = `"RTE (%s-%s%s%s) %s on BCM%s r%d @ %d.%d/%d.%d/%d.%dMHz"` — this is the **Runtime Environment startup banner** printed very early during fw boot, not by wlc_attach or wlc_bmac_attach.

This revises the T251 reading ("last printed line was a wlc_attach init banner"). Fw actually hangs after RTE banner prints, anywhere within the remaining init sequence — the last-line evidence is weaker than previously stated.

### 6. Chiprev banner call site is blob[0x06876E..0x06877A]

Format string at blob[0x4C534]: `"wl%d: %s: chiprev %d corerev %d cccap 0x%x maccap 0x%x band %sG, phy_type %d phy_rev %d\n"`

**Exactly one** LDR-pool reference to this literal: `0x06876E: ldr r0, [pc, #0x60]` (literal @ 0x687D0). Followed by a `bl #0xA30` (printf) at 0x06877A. Same function also references the literal `"wlc_bmac_attach"` (blob[0x4B121]) from 0x68778 → confirms this is **inside wlc_bmac_attach**.

The chiprev banner was never observed in the captured ring → fw never reached `0x06877A`.

### 7. WFI / WFE and self-loop cross-check

- **WFI** (Thumb `0xBF30`): **1 occurrence** at blob[0x001C1E] — a 4-byte leaf function (`wfi; bx lr`).
  - **WFI IS reachable via a scheduler tail-call chain**:
    - 0x1C1E (WFI leaf) ← b.w from 0x1C0C (thunk) ← b.w from 0x11CC (inside scheduler-main function)
    - Scheduler main at 0x115C walks a linked list of callbacks at `[0x629A4]` (each node: flag at +0xC, fn-ptr at +4, arg at +8, next at +0), then checks a "current task" pointer at `[0x6299C]`. If no runnable work, falls through to sleep-flag write at `[0x629B4]`, calls `0x1038` (barrier/critical-section), rechecks flag, and either loops back or exits.
    - 0x115C has ONE direct caller: 0x1962 (`b.w #0x115C` tail-call).
  - **The WFI path is reachable** whenever the scheduler runs out of runnable callbacks AND the sleep-flag remains unset through 0x1038. This is the classic RTOS idle hook.
  - **Implication for hang**: if fw enters WFI (no runnable tasks, no pending event) and no interrupt fires to wake the CPU, fw stalls in WFI indefinitely with NO code executing, NO counter updates, NO ring writes — fully consistent with observed evidence.
- **WFE** (Thumb `0xBF20`): searched blob — no valid WFE instructions found in code region (several 0x20 0xBF byte sequences exist but all disassemble as data / arithmetic when decoded as code at those offsets).
- **Self-loop `0xE7FE` (`b .`)**: 6 occurrences total. Four (0x25E, 0x290, 0x326, 0x53E) are in low-address reset/exception-handler code. **Two at blob[0x464F6] and blob[0x468F4] are false positives** — surrounding bytes disassemble as gibberish (repeated identical instructions at adjacent 2-byte offsets, asymmetric strh/ldrb with nonsensical offsets, junk strings `"kkkk::::"`, `"V22dN::t"` etc. nearby). No BL or B instruction in the code region targets either. These are **data bytes that happen to be 0xFE 0xE7**, not executable self-loops.

**Revised net**: WFI IS reachable from normal execution. The wlc code path itself has no tight unbounded loops — but the ARM core can enter WFI via the RTE scheduler at 0x115C when no tasks are runnable. This promotes the "CPU idle waiting for IRQ" hypothesis to a real candidate alongside "CPU bus-stalled on unclocked-core access."

## Where the hang is — reading after T254

### Caveat on α (advisor-flagged)

T253 falsified the narrower claim "0x934C0 is a TCB." It did NOT fully settle the broader claim "the saved-state region at 0x9CE98..0x9CF34 is a live call-context snapshot vs. a paused-task save frame." Those are logically distinct. The working model remains α (call-context snapshot), but this is a **working model, not a settled fact**. Conclusions downstream ("fw was executing inside X at hang time") carry that uncertainty.

### Converging evidence

1. Fw printed RTE boot banner (blob[0x6BAE5]) — before any wlc init starts.
2. Fw reached wlc_attach (LR 0x68D2F in saved-state — if α holds).
3. Fw reached wlc_bmac_attach (LR 0x68321 in saved-state — confirmed by wlc_bmac_attach function name literal @ blob[0x4B121] being referenced from 0x6834E, 0x68398, 0x6871A, 0x68778 — if α holds).
4. Fw did **not** reach the chiprev-banner printf at 0x06877A (this is ring-evidence, independent of α).
5. 0x68321 is the return address to `bl #0x1415C` at 0x6831E (T253 identified 0x1415C as a SB-core reset polling waiter — bounded 20ms).
6. The polling loops at 0x1415C (T253), 0x1722C (T254), and 0x14CAC (this analysis) are all built on PMCCNTR-backed delay → all bounded.
7. Self-loop `b .` search found no reachable unbounded spin in wlc code path.
8. **WFI is reachable** via the scheduler at 0x115C. Fw can legitimately enter CPU-idle if no tasks are runnable.

### Candidates remaining (revised priority)

- **(A) Cross-core / PCIe wait (bus-stall)**: fw issues a transaction targeting a core that's unclocked/held-in-reset, and the bus returns indefinitely. The ARM core itself would be stalled on a pending LDR/STR. Saved LR captured last completed call-return before the stall. Consistent with: silent hang, no counter advances, ring unchanged.
- **(A') RTE scheduler WFI-stall**: fw's scheduler at 0x115C walks its callback list, finds no runnable work, falls through to `wfi` at 0x1C1E. If no interrupt wakes the CPU, fw sleeps indefinitely. Indistinguishable from (A) in terms of host-side observables (no code runs = no TCM updates = saved state remains frozen). The saved LR in the "call-context" region might then reflect the LR at the MOMENT THE SCHEDULER entered idle — which could be any prior completed call.
- **(B) Inter-thread wait**: an RTOS task waiting on a semaphore/queue/event. If scheduler is in WFI because all tasks are blocked, this IS (A'). Otherwise, if one task is looping and another is blocked, we'd expect SOME code to run (and TCM would drift). The observed stasis argues against a mixed case.
- **(C) Delay helper reentrancy or scale corruption**: if the tick-scale at TCM[0x58C98] is corrupted to 0xFFFFFFFF, `target = units * scale` overflows → `blo` always-taken → permanent inner-delay hang. Easy to falsify or confirm with a 1-u32 TCM probe.

### Discriminator that does NOT need new hardware probes

**Re-check ALREADY-CAPTURED T247/T239/T240 data**: these probes fire at EVERY dwell (t+100ms through t+90s). If their values drift between early and late dwells, fw IS executing code that writes TCM. If they are IDENTICAL at every dwell, fw is NOT executing fw code (consistent with WFI or bus-stall — both (A) and (A')).

From the T252 journal (test.247, test.240): values are **IDENTICAL across all 22 dwells within a single boot**. So fw stopped executing *before* the first poll at t+100ms, and remained stopped. This is consistent with both (A) and (A'), and with the prior reading "freeze happens within ~12ms of insmod" (test.89).

### Sharpened hang reading

Fw executes init code for a short window (≤ 12ms after insmod) during which it prints the RTE banner and performs early hardware setup (si_attach completes → 0x92440 populated with CC base 0x18001000). The next thing fw does is either:
- (a) stall on an SB-core access (bus-level hang — (A)), OR
- (b) exhaust its init-task work and enter scheduler idle → WFI (A'), waiting for an IRQ that never fires (perhaps because PCIe MSI setup depends on host-side protocol handshake that's incomplete).

The distinction matters: (A) is a fw bug; (A') is potentially a host-fw protocol issue we could fix on the driver side.

## Recommended T255 direction

Move back to hardware probe, informed by T254's narrowing:

1. **Cheapest: TCM[0x58C98..+4]** — verify the tick-scale has not been corrupted. Blob-default 0x50; if value changed to extreme → (C) confirmed. 1 u32. Low-risk.
2. **TCM[0x93550..0x9358C]** — decode 0x9355C, the forward-linked struct pointer from 0x934C0. Same risk as T253. 16 u32.
3. **Peek at the RTE scheduler state**: probe the callback-list head at TCM[0x629A4] and current-task at TCM[0x6299C] and sleep-flag at TCM[0x629B4]. If list is empty AND sleep-flag is set, fw went to WFI → (A') confirmed. These are BSS addresses in the blob's data-segment range. Cheap, low-risk, high-info. 3 u32 reads.
4. **Higher-risk: sample PHY/MAC `[core_base + 0x128]` via BAR0**. Tells us whether the MAC-suspend bit would have set. Requires careful gate-on-core-reset-state check; can wedge the bus. Design caution warranted.
5. **Enumerate RTOS task-table** — requires finding TCB layout. Defer.

Recommendation: combine (1) + (3) in a single t+60s probe (4 u32 total). This is cheaper than any prior probe and directly discriminates (A) vs (A') vs (C). If it points at (A'), next probe is (4) to look at hardware. If it points at (A), skip (4) and go to backplane-state probes.

Advisor call before committing to T255 design.

## Clean-room note

All observations are: (1) disassembled instruction mnemonics + operands via capstone, (2) literal-pool address resolution, (3) ASCII format-string pattern matching, (4) Thumb self-loop opcode pattern (`0xE7FE`), (5) CP15 coprocessor operand matching (PMCCNTR / PMCR). Function roles identified by format-string + literal-pool cross-reference, not by sequence-of-instructions reconstruction.
