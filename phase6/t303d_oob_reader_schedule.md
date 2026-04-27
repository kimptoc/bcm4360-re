# T303d — OOB Router pending-events reader: on-dispatch execution context

**Date:** 2026-04-27 (post-T303 hardware fire)

**Goal:** Determine whether firmware reads OOB Router pending-events register (0x18109100) on a periodic schedule (active polling via timer) or only on-dispatch from an upstream IRQ source (interrupt-driven). This question discriminates between two fundamentally different wake-mechanism categories and shapes the option B (active wake-event injection) design.

---

## Headline Answer

**OOB pending-events is read ON-DISPATCH ONLY, not on a periodic schedule.**

Firmware reads the register exactly once per exception/interrupt, within a synchronized ISR dispatcher chain that fires when an upstream hardware interrupt asserts. There is no timer-driven polling loop, no background poller thread, and no periodic re-reads of the pending bitmap. The read happens at exception-handler latency, driven by hardware IRQ assertion.

---

## Reader Function and Call Chain

### fn@0x9936: The OOB pending-events reader

Per phase6/t300_static_prep.md, firmware reads OOB Router pending-events at absolute address 0x18109100 via a 3-instruction leaf function:

```
fn@0x9936:
  ldr r3, [sched_ctx, #0x358]    ; r3 ← sched+0x358 = 0x18109000 (OOB Router base)
  ldr r0, [r3, #0x100]           ; r0 ← OOB Router pending-events (0x18109100)
  bx  lr                         ; return pending bitmap in r0
```

**Single caller:** fn@0x115c (the OOB ISR dispatcher), located at firmware address 0x001162.

### fn@0x115c: The OOB ISR dispatcher

The function containing the BL to fn@0x9936 is a **synchronous interrupt dispatcher**:

```
0x115c: push {r4, r5, r6, lr}           ; function prologue
0x115e: ldr r3, [pc, #0x5c]
0x160:  ldr r0, [r3]                    ; load constant
0x162:  bl #0x9936                      ; CALL fn@0x9936 — read OOB pending
0x166:  ldr r3, [pc, #0x58]
0x168:  ldr r4, [r3]                    ; r4 ← ISR-list head pointer
0x16a:  mov r5, r0                      ; r5 ← pending-events bitmap

        ; ISR dispatch loop (0x16e-0x180):
0x16e:  ldr r3, [r4, #0xc]              ; r3 ← ISR node mask
0x170:  tst r5, r3                      ; test pending & mask
0x172:  beq #0x17c                      ; if no match, skip this ISR
0x174:  ldr r3, [r4, #4]                ; r3 ← ISR callback fn pointer
0x176:  cbz r3, #0x17c                  ; if NULL, skip
0x178:  ldr r0, [r4, #8]                ; r0 ← ISR arg
0x17a:  blx r3                          ; CALL ISR callback (bx via register)
0x17c:  ldr r4, [r4]                    ; r4 ← next node in linked list
0x17e:  cmp r4, #0                      ; check if more nodes
0x180:  bne #0x16e                      ; loop if non-zero
```

**Pattern:** Read OOB pending once, walk ISR list once, dispatch any matching callbacks, return. No re-read, no sleep/delay, no loop back. Classic synchronous exception handler.

### Call context: exception vector entry

fn@0x115c has **no direct BL/BLX callers** and **no stored pointer references** in the entire blob. This indicates it is reached by **fallthrough from upstream exception handler code**, not by explicit branch. Per KEY_FINDINGS row 161, the unified dispatcher fn@0x138 is the entry point for exception/interrupt handling with ~319 functions in its reachable set. fn@0x115c appears to be a continuation of that exception-handling chain.

---

## Execution Context: ISR Dispatcher, Not Polling Loop

### Key discriminators (all satisfied for on-dispatch):

1. **No periodic loop or timer callback.** The function contains no LOOP structures that re-read pending events. No `sleep`, `delay`, or timer-registration calls precede the pending read. The pending read happens exactly once per function invocation.

2. **No background task or "poller" registration.** Firmware does not register fn@0x115c as a callback with any timer or scheduler. It is not entered from a periodic context; it is entered from exception context.

3. **Single synchronous read-dispatch-return pattern.** The pending read is followed immediately by ISR dispatch and function return. The structure is:
   - Exception fires (hardware IRQ asserts)
   - Exception handler executes (fn@0x138 + continuation)
   - fn@0x115c executes (as part of exception handler chain)
   - fn@0x9936 called: single read of pending bitmap
   - ISR dispatch: walk list, call callbacks
   - Function return

4. **No visible timer/scheduler data structures.** The static reach analysis (phase6/t299_t306_offload_runtime.md) covering ~319 functions found no timer-registration or periodic-callback infrastructure in the live offload runtime. The FullMAC `wl_*` timer routines remain dead code.

5. **Consistent with hardware fire observations (T300/T301).** T300 and T301 observed `pending=0x00000000` at post-set_active timing (samples 1 and 2). If firmware were polling on a background timer/scheduler, we would expect either:
   - Multiple non-zero transitions in the pending bitmap between samples (if poller detected events)
   - Or a continuous background read pattern that would increase cumulative register access counts
   
   Instead, T300/T301 showed clean single-shot reads with frozen pending=0x0. This is consistent with "only read when interrupt fires" behavior, not "read every Nms on a timer."

---

## Temporal Profile

Per T303 hardware fire (row 162), the OOB Router pending-events register is readable via BAR0 at post-set_active timing (n=2 fires confirmed). The function fn@0x115c itself is not explicitly called during post-set_active (no exception fires at that moment). The ISR dispatcher chain fn@0x115c would execute only when a hardware interrupt asserts — which in the test environment appears to be either:

- Not occurring at all (pending=0x0 consistently)
- Or occurring very infrequently during the ~90-second observation window

If firmware were on a periodic polling schedule, we would expect to see evidence of scheduler initialization (timer registration, callback binding, etc.) in the static reach set. The absence of such evidence, combined with the synchronous structure of fn@0x115c itself, strongly indicates wake-trigger delivery happens via hardware interrupts to the ARM CR4 exception interface, not via firmware-side polling.

---

## Confidence and Residual Uncertainty

**Confidence: 90%** (high)

The evidence is consistent and mutually reinforcing:
- Static disassembly clearly shows synchronous dispatcher structure (no loops, no sleep)
- Call chain analysis shows fn@0x115c reachable only from exception context, not from timer callbacks
- Live reach analysis found zero timer/scheduler registration in ~319-function set
- Hardware fire observations (pending=0x0 consistency) fit on-dispatch model
- Code pattern matches classic ARM exception-handler dispatcher

**Residual uncertainty (10%):**

1. **Inline continuation ambiguity.** fn@0x115c has no explicit callers; it is reached by fallthrough. If the exception-handling chain is longer or has indirect dispatcher logic not discovered by static analysis, there could be hidden timer-driven paths. However, the 319-function reach set per row 161 is comprehensive (includes all functions reachable from exception vectors via BL, BX, and PC-pool patterns), so a major dispatcher is unlikely to be missed.

2. **Unobserved hardware events during test window.** All observed hardware fires (T300, T301, T303) show pending=0x0. It's possible that wake events DO fire during normal operation (when test probes are not running), but the test environment is so quiescent that fn@0x115c never executes. If a hidden periodic poller exists alongside the on-dispatch reader, it would not be exercised in these tests. However, per RESUME_NOTES §"EMPIRICAL REFRAME", T303 shows console wr_idx frozen from t+500ms through t+90s — strong evidence fw IS quiescent waiting for wake events, not in an active polling loop.

3. **Possibility of multiple readers.** The static analysis found only fn@0x9936 as a reader of 0x18109100. If other code paths read the same register via different instructions (e.g., direct `ldr r0, [r3, #0x100]` without calling fn@0x9936), they might not have been discovered. However, t300_static_prep.md explicitly scanned for writers and readers of 0x18109100; the conclusion was "zero writers of this register into TCM" and fn@0x9936 as the only reader in the reach set.

---

## Implication for Option B (Active Wake-Event Injection)

The on-dispatch determination **strongly favors interrupt-driven wake mechanisms** over timer-based ones:

### Favored: MSI Assert or DMA Event Trigger

Since firmware waits in WFI for a hardware interrupt and reads OOB pending only on exception dispatch, the most direct active-test design would be to **assert a hardware interrupt line on the ARM CR4 exception interface**, triggering the exception vector and thus fn@0x115c. This would cause the pending read and ISR dispatch to execute without requiring firmware to poll or call out to a scheduler.

**Mechanisms:**
- **MSI assert:** Host driver writes the MSI trigger register (chipcommon+0x5C8 or similar per BCM conventions) to inject an interrupt. The interrupt fires → exception vector → fn@0x115c → reads OOB pending. Direct and fast.
- **OOB Router direct bit set:** Host writes OOB Router pending-events register directly (via BAR0_WINDOW = 0x18109000, then write +0x100) to set one of the OOB bits that firmware's allocated ISRs are listening for (bits 0 or 3 per T298). The bit read by fn@0x9936 would be non-zero → ISR dispatch executes.

### Less favored: Polling-based injection

Periodically writing to a firmware mailbox or shared-memory flag and relying on fw to poll would be less aligned with the on-dispatch architecture. The firmware does not appear to have a background poller; it would need one to be added or enabled.

### DMA over olmsg ring (Phase 4B)

If the olmsg ring at shared_info is plumbed for DMA-based messaging (per RESUME_NOTES "phase 4B olmsg DMA, never triggered"), this could be leveraged to send wake-event payloads to firmware. However, this still assumes firmware has some path to process DMA-ring events. If DMA-ring processing also goes through the on-dispatch chain (i.e., DMA completion fires an interrupt → fn@0x115c executes), then this mechanism is compatible with the on-dispatch finding. If DMA-ring processing is polled, it would contradict the finding.

**Recommendation for option B:** Prioritize MSI assert or direct OOB bit set as the injection mechanism. Both are compatible with the on-dispatch architecture and do not require firmware changes. If DMA-ring approach is chosen, verify that DMA completion is interrupt-driven (not polled) to maintain consistency with the fw architecture.

---

## Files and References

- **phase6/t300_static_prep.md:** Initial identification of fn@0x9936 as the OOB pending reader (3-insn leaf)
- **phase6/t303b_gap_writers.md, t303c_cc_writer.md:** Methodology for static disassembly analysis (same approach used here)
- **KEY_FINDINGS row 161:** Unified dispatcher fn@0x138, ~319 functions in reach set, confirmation that live runtime is HNDRTE offload (not FullMAC)
- **KEY_FINDINGS row 162:** OOB Router identity (BCMA core 0x367) and BAR0 reachability at post-set_active
- **KEY_FINDINGS row 163:** ISR-list enumeration (T298/T299) showing 2 nodes with OOB bits 0 and 3 allocated
- **RESUME_NOTES "Current state":** T303 fire showing console wr_idx frozen from t+500ms through t+90s (fw quiescent, not polling)
- **Firmware: fn@0x9936** (offset 0x9936, 6 bytes)
- **Firmware: fn@0x115c** (offset 0x115c, ~148 bytes)
- **Hardware fire: T300, T301, T303** (pending=0x0 at post-set_active, no spontaneous non-zero transitions observed)

---

## Conclusion

Firmware reads OOB Router pending-events **on interrupt dispatch only**, not on a periodic schedule. The reader fn@0x9936 is called by a synchronous ISR dispatcher fn@0x115c that executes as part of the exception-handling chain. No polling loop, timer callback, or background scheduler task invokes the read. Wake events must be delivered via hardware interrupt assertion (MSI, direct bit set, or equivalent interrupt-delivery mechanism) to trigger firmware execution. This architecture strongly favors interrupt-driven active-test mechanisms (option B: MSI assert or OOB direct write) over timer-based or polling-based approaches.

---

**Co-authored by:** Static disassembly analysis (phase6/t303d workflow, Capstone-based disassembler) + cross-reference to T300/T301/T303 hardware fire observations.

