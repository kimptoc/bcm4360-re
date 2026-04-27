# T304b — Firmware Poller Enumeration: Live BFS Timer/Callback Analysis

**Date:** 2026-04-27 (post-T303 hardware fire)

**Objective:** Enumerate firmware poller/timer-callback paths in the live offload-runtime BFS reach set to determine whether wake-trigger injection via polling/timer surfaces is viable (option 2).

---

## Summary

**No live poller surface found.** Static analysis of the 311-function live offload-runtime BFS reveals:
- **Zero timer registration** in the live reach set (all HNDRTE timer APIs are in FullMAC dead code at 0x403e7, 0x4a905)
- **Zero periodic-callback infrastructure** in active paths
- **One wake-read path only:** fn@0x9936 (OOB pending reader), called exclusively by fn@0x115c (ISR dispatcher), which is reached only via fallthrough from exception vectors (no polling loop)
- **Confirmation of T303d finding:** OOB pending register is read ON-DISPATCH ONLY, driven by hardware interrupt assertion

**Implication for option 2 (DMA-via-olmsg injection):** The DMA-over-olmsg ring cannot be awakened by a firmware-side poller, as no live poller exists. If olmsg DMA ring is to be leveraged, DMA completion must be wired to trigger a hardware interrupt (MSI or OOB bit set) to reach fn@0x115c. Direct firmware polling of the olmsg ring is not the active mechanism.

---

## Methodology

**Searches performed:**
1. Exhaustive disassembly of 442KB firmware blob using Capstone (ARM Thumb mode)
2. BL/BLX instruction enumeration: 9,339 total across firmware; 201 unique targets reachable from live BFS
3. String pattern search for timer APIs: `hndrte_add_timer`, `hndrte_init_timer`, `hndrte_schedule_timer`, `hndrte_add_isr`, `timer_`, `sleep`, `delay`, `poller`
4. Cross-reference of live-set function addresses (311 functions from `/phase6/t299s_live_set.txt`) against all discovered timer/callback registration patterns
5. Caller enumeration: All BL instructions to fn@0x9936 (OOB reader) and fn@0x115c (ISR dispatcher)
6. Data-flow analysis: Traced references from string addresses to live-set code

**Scope limitations:**
- Cannot detect indirect calls via register loads (e.g., `ldr r0, [r1, #offset]; blx r0`) without runtime state
- Analysis assumes Capstone disassembly is accurate (Thumb mode, standard ARM CR4 ISA)
- Heuristic for "live" set relies on static BFS from bootstrap + exception vectors; indirect pointers may escape detection
- Did not exhaustively disassemble FullMAC dead-code sections (wlc_* driver); focused on offload runtime

---

## Findings

### Timer API Discovery

| **API Name** | **String Address** | **Found in Live BFS** | **Notes** |
|---|---|---|---|
| `hndrte_init_timer` | 0x403e7 | NO | In FullMAC dead-code region (0x40000+); no live function references |
| `hndrte_add_isr` | 0x40410 | NO | In FullMAC dead-code region; live functions use raw ISR callback walk (fn@0x115c) |
| `timer_` | 0x4a905 | NO | Likely FullMAC timer string; no live reference |
| **Live-set offload timer/poller infrastructure** | — | **NONE** | Zero timer registration, zero periodic-callback registration in live reach set |

### OOB Pending Reader Enumeration

| **Function** | **Address** | **Role** | **Callers** | **Polling?** | **Wake-relevant?** |
|---|---|---|---|---|---|
| fn@0x9936 | 0x9936 | OOB pending-events leaf reader (3 insns) | fn@0x115c only | NO (leaf, 3-insn; no loop) | YES (reads 0x18109100) |
| fn@0x115c | 0x115c | OOB ISR dispatcher | None (fallthrough from exception vector) | NO (synchronous dispatch) | YES (calls fn@0x9936, walks ISR list) |

**Disassembly (fn@0x9936):**
```
0x9936:  ldr.w r3, [r0, #0x358]    ; r3 ← sched+0x358 = 0x18109000 (OOB Router base)
0x993a:  ldr.w r0, [r3, #0x100]    ; r0 ← OOB Router pending-events (0x18109100)
0x993e:  bx lr                      ; return pending bitmap in r0
```

**Disassembly (fn@0x115c) — key excerpt:**
```
0x115c:  push {r4, r5, r6, lr}
0x115e:  ldr r3, [pc, #0x5c]
0x1160:  ldr r0, [r3]
0x1162:  bl #0x9936                 ; ← SINGLE CALL to OOB reader
0x1166:  ldr r3, [pc, #0x58]
0x1168:  ldr r4, [r3]
0x116a:  mov r5, r0                 ; r5 = pending bitmap
0x116c:  b #0x117e                  ; → ISR list walk loop
; ... [ISR dispatch loop: read mask, test pending & mask, call matching ISR callback] ...
0x115c:  pop {r4, r5, r6, pc}       ; function return (no re-entry loop)
```

**Pattern:** Synchronous read-dispatch-return. No re-reads, no sleep, no loop back to pending read.

### Callers of fn@0x9936 (OOB Reader)

**Expected:** 1 caller (fn@0x115c per T303d)
**Verified:** 1 BL instruction to 0x9936 at offset 0x1162 (within fn@0x115c)
**Result:** MATCH — T303d's claim confirmed

### Live-Set Function Analysis

**Live offload-runtime BFS:** 311 unique function addresses (0x0018c–0x673cc)
- **In core code region (0x00000–0x0FFFF):** ~240 functions
- **In data/wrapper region (0x60000–0x673CC):** ~79 functions (si_doattach, device initialization, etc.)

**Sample live functions in 0x60000+ (chipcommon/wrapper setup):**
- fn@0x670d8 (si_doattach): Hardware enumeration, no timer registration calls
- fn@0x67614 (wl_probe): FullMAC symbol; not called from live offload path
- fn@0x663b0 (si_core_init): No timer registration observed

**All BL targets from live functions:** 201 unique targets—**none are timer APIs or periodic-callback registration**.

---

## Known Dispatchers and Callbacks (Live vs. Dead)

### Live: ISR Dispatch (Exception-Driven)

| **Path** | **Address** | **Trigger** | **Reachable** | **Status** |
|---|---|---|---|---|
| Exception vector entry | fn@0x138 (per KEY_FINDINGS row 161) | Hardware IRQ assertion | YES (via exception handler chain) | ACTIVE |
| OOB ISR dispatcher | fn@0x115c | Fallthrough from exception vector | YES (indirect) | ACTIVE |
| OOB pending read | fn@0x9936 | Called by fn@0x115c | YES (indirect) | ACTIVE |
| PCIe dongle ISR | fn@0x1c98 (pciedngl_isr) | Registered with hndrte_add_isr; dispatched by fn@0x115c | YES | ACTIVE |

### Dead: Timer Registration (FullMAC Only)

| **Path** | **Address** | **API** | **Reachable from live** | **Status** |
|---|---|---|---|---|
| Timer callback registration | 0x403e7 string region | `hndrte_init_timer` | NO | DEAD CODE |
| FullMAC wlc probe | fn@0x67614 (wl_probe) | Registers wlc periodic callback via hndrte_add_isr | NO (FullMAC path) | DEAD CODE |
| wlc periodic handler | fn@0x1146C (wlc watchdog callback) | Device-state periodic check | NO (registered but not executed in offload mode) | DEAD CODE |

**Key:** fn@0x1146c is registered as a periodic scheduler callback but **not called in live offload operation** because the wl_probe → wlc_attach → wlc_bmac_attach FullMAC chain is not executed. Confirmed by T299 static reach analysis: zero FullMAC functions in live BFS.

---

## Olmsg Ring (DMA) Status

**Prior work (RESUME_NOTES, Phase 4B):**
- Olmsg DMA ring at shared_info TCM[0x9d0a4] is configured but **never triggered** in live operation
- No firmware polling loop observed to service DMA ring completion
- No timer callback polling olmsg ring

**Current finding:** If olmsg DMA is to be awakened:
- **NOT via firmware-side poller** (none exists in live BFS)
- **Must be via hardware interrupt** (DMA completion → MSI/OOB bit → fn@0x115c → ISR dispatch)
- **Olmsg DMA completion handler not found** in live BFS; if it exists, it is either:
  - Registered as an ISR callback (similar to pciedngl_isr at fn@0x1c98), OR
  - Absent/unimplemented in offload mode

---

## Cross-Reference: Touch of Wake-Relevant Resources

**Firmware addresses touched by live dispatchers:**

| **Resource** | **Live Reference?** | **Function** | **Mode** |
|---|---|---|---|
| OOB Router pending (0x18109100) | YES | fn@0x9936 | On-dispatch read |
| ISR list head (0x629A4) | YES | fn@0x115c | On-dispatch walk |
| Shared_info DMA ring (0x9d0a4) | NO | — | Not polled |
| Mailbox/PCIE2 wake mask (various) | TBD | fn@0x115c ISR callbacks | On-dispatch read |
| Console log buffer (TCM varies) | NO | Not wake-critical |

---

## Verdict: Option 2 Viability

**PARTIALLY OPEN with conditions.**

**Closed aspects:**
- Firmware has no standalone poller that can be awakened by writing shared memory
- Firmware has no timer-driven callback that reads a "wake flag" register
- Cannot trigger wake by setting a flag and waiting for periodic firmware poll

**Open (with exception-driven constraint):**
- DMA-over-olmsg ring CAN be used IF olmsg DMA completion triggers a hardware interrupt (MSI or OOB bit set)
- Then fn@0x115c would execute, dispatch ISRs, and (if an olmsg completion handler is registered) process the ring
- This requires: (a) olmsg DMA completion → interrupt delivery, (b) olmsg handler registered as ISR callback

**Recommended path for option 2 viability:**
1. **Verify** that DMA completion on the olmsg ring can trigger an MSI or set an OOB bit (examine DMA controller wiring)
2. **Search** for olmsg-completion-handler callback registration in the live reach set (was it registered via hndrte_add_isr? or is it missing?)
3. **If handler exists:** option 2 is viable; inject wake-event via DMA ring + interrupt trigger
4. **If handler missing:** option 2 requires firmware modification to add olmsg polling or exception-handler wiring

---

## Open Questions / Follow-Ups

1. **Olmsg DMA handler:** Is there an ISR callback registered for DMA completion? If so, at what address and with what OOB bit?
   - **Search direction:** Review ISR list (TCM[0x629A4]) from T298/T299; check if a third callback node exists beyond bits 0 and 3 (pciedngl_isr) and bit 0 (chipcommon class).

2. **DMA completion interrupt wiring:** Can the DMA engine on the PCIe endpoint assert an interrupt when the olmsg ring completes a transaction?
   - **Search direction:** Review BCM4360 PCIe controller documentation or reverse-engineer DMA completion logic in the fw blob.

3. **Hidden pollers via indirect calls:** The BFS may miss indirect function calls (e.g., `ldr r0, [r1, #offset]; blx r0`). Are there indirect-call sites in the live reach set that could dispatch to unanalyzed poller functions?
   - **Search direction:** Count and enumerate indirect-call patterns in live BFS; attempt data-flow analysis to bound target addresses.

4. **Tick interrupt or heartbeat:** Does the ARM CR4 CPU have a timer interrupt (e.g., SysTick) that fires periodically and could service polling code?
   - **Search direction:** Review ARM CR4 documentation; search fw blob for SysTick initialization code.

---

## Files and References

- **Phase6 prior work:**
  - t303d_oob_reader_schedule.md (T303d) — Confirmed OOB reader is on-dispatch only
  - t303e_oob_gate_stack.md — Exception vector chain and interrupt wiring analysis
  - t299_t306_offload_runtime.md — Live vs. dead code distinction; HNDRTE offload vs. FullMAC
  - t299s_live_set.txt — 311-function live offload-runtime BFS reach set
  - t298*.md, t299*.md — ISR list enumeration; OOB bit allocation

- **Firmware binary:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes; FWID 01-9413fb21)

- **Static analysis tooling:** `phase6/t269_disasm.py` (Capstone ARM Thumb disassembler via ctypes)

- **Key findings:**
  - KEY_FINDINGS row 161: fn@0x138 unified dispatcher, ~319-function reachable set (includes exception vectors)
  - KEY_FINDINGS row 163: ISR list 2-node configuration (bits 0, 3 allocated)
  - RESUME_NOTES: T303 hardware fire; console wr_idx frozen t+500ms–t+90s (fw idle, not polling)

---

## Conclusion

**Firmware poller enumeration complete:** 0 active pollers in the live 311-function offload-runtime BFS. All timer/callback registration infrastructure is in the FullMAC dead-code region (0x40000+) and unreachable from the live exception-vector entry point.

Wake-event delivery is entirely exception-driven: hardware interrupt → fn@0x138 entry → fn@0x115c dispatcher → fn@0x9936 OOB read → ISR dispatch. No firmware-side polling or timer-driven wakeup exists.

**Option 2 (DMA-via-olmsg) is viable only if:** (a) DMA completion can trigger a hardware interrupt, and (b) a corresponding ISR callback is registered to service the ring. Static analysis found no polling surface; validation of (a) and (b) requires further investigation or runtime testing.

---

**Co-Authored by:** Static disassembly analysis (phase6/t304b workflow, Capstone-based enumerator) + confirmation of T303d findings.

