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

### 7. WFI and self-loop cross-check

- **WFI** (Thumb `0xBF30`): **1 occurrence** at blob[0x001C1E] — in very early boot code, far below any wlc path. Likely an exception-wait in a reset handler. Not reachable from wlc_bmac_attach.
- **Self-loop `0xE7FE` (`b .`)**: 6 occurrences total. Four (0x25E, 0x290, 0x326, 0x53E) are in low-address reset/exception-handler code. **Two at blob[0x464F6] and blob[0x468F4] are false positives** — surrounding bytes disassemble as gibberish (repeated identical instructions at adjacent 2-byte offsets, asymmetric strh/ldrb with nonsensical offsets, junk strings `"kkkk::::"`, `"V22dN::t"` etc. nearby). No BL or B instruction in the code region targets either. These are **data bytes that happen to be 0xFE 0xE7**, not executable self-loops.

**Net: no reachable unbounded-wait primitive (WFI / b .) exists in the wlc code path.**

## Where the hang is — reading after T254

Converging evidence:

1. Fw printed RTE boot banner (blob[0x6BAE5]) — before any wlc init starts.
2. Fw reached wlc_attach (LR 0x68D2F in saved-state).
3. Fw reached wlc_bmac_attach (LR 0x68321 in saved-state — confirmed by wlc_bmac_attach function name literal @ blob[0x4B121] being referenced from 0x6834E, 0x68398, 0x6871A, 0x68778).
4. Fw did **not** reach the chiprev-banner printf at 0x06877A.
5. 0x68321 is the return address to `bl #0x1415C` at 0x6831E (T253 identified 0x1415C as a SB-core reset polling waiter — bounded 20ms).
6. The polling loops at 0x1415C (T253) and 0x1722C (T254) and 0x14CAC (this analysis) are all built on PMCCNTR-backed delay → all bounded.
7. No WFI, no reachable `b .` self-loop, no unbounded tight loop found in the wlc_bmac_attach / wlc_phy_attach call tree.

**The hang mechanism is therefore NOT a direct polling loop inside the fw code region**. Candidates remaining:

- **(A) Cross-core / PCIe wait**: fw issues a transaction targeting a core that's unclocked/held-in-reset, and the bus returns indefinitely (backplane timeout, if any, hasn't been characterized for this chip). The ARM core itself would be stalled on a pending LDR/STR — the hang is at memory-subsystem level, not instruction level. Saved LR captured last completed call-return before the stall.
- **(B) Inter-thread wait**: fw uses an RTOS (RTE = Real-Time Environment) with multiple tasks. One task might be waiting on a semaphore/queue/event that another task (never-scheduled, or stuck elsewhere) needs to signal. The saved-state region shows ONE task's frame; the hung task might be a different one. But T253 falsified the TCB reading of 0x934C0, and the si_info / wl_info structs don't show obvious RTOS primitives.
- **(C) Delay helper reentrancy or scale corruption**: if the tick-scale at TCM[0x58C98] gets overwritten to 0xFFFFFFFF (or extreme value) mid-run, `target = units * scale` overflows and `blo` becomes always-true. Worth a hardware probe.

Of these, **(A)** is the most consistent with the evidence: silent hang, no assertion, CPU-core stalled, ring not advanced. SB-core reset polling (0x1415C or 0x1722C callees) reads `[core_base + offset]` — if the core_base is wrong or the core is unclocked, the read returns stale/indeterminate data but the CPU itself still runs (bus read returns eventually). However, some cores respond via a PSL-style handshake that can back-pressure the CPU indefinitely on access. That matches a silent, non-terminating hang.

## Recommended T255 direction

Move back to hardware probe, informed by T254's narrowing:

1. **Cheapest probe: TCM[0x58C98..+4]** — verify the tick-scale has not been corrupted (expected 0x50 blob-default, or possibly an updated value). One u32 read. Settles (C).
2. **Read PHY / ChipCommon register [core_base + 0x128]** — the register the 0x1722C polling loop reads. If we can sample its value via BAR0 at hang time, we see whether bit 0 is ever set. Bit 0 = 1 means the poll would succeed; bit 0 always 0 means fw is genuinely waiting on a MAC suspend that never happens. Caveat: accessing PHY/MAC cores while they may be unclocked can itself wedge the bus — must gate on whether the core is out of reset first. This probe is **riskier** than T247..T253 and needs careful design.
3. **Probe 0x9355C** — the cheapest unfollowed pointer from 0x934C0. Same risk as T253. Decodes the forward-linked struct in the 0x934C0 family.
4. **Enumerate RTOS task list if one exists** — search fw BSS for task-table magic. Settles (B). Requires finding the task-control-block layout; not trivial. Defer.

Advisor call before committing to T255 design.

## Clean-room note

All observations are: (1) disassembled instruction mnemonics + operands via capstone, (2) literal-pool address resolution, (3) ASCII format-string pattern matching, (4) Thumb self-loop opcode pattern (`0xE7FE`), (5) CP15 coprocessor operand matching (PMCCNTR / PMCR). Function roles identified by format-string + literal-pool cross-reference, not by sequence-of-instructions reconstruction.
