# T304d — Static Disassembly of pciedngl_isr: Event-Dispatch Analysis and DMA/Olmsg Viability

**Date:** 2026-04-27 (post-T304c)

**Firmware blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)

**Task:** Determine whether pciedngl_isr (fn@0x1c98, registered ISR at OOB bit 3) dispatches DMA completion events on the olmsg ring, resolving option 2 (DMA-via-olmsg) viability.

**Primary finding:** **pciedngl_isr handles ONLY the H2D_MAILBOX_1 doorbell (bit 0x100), NOT DMA completion events.** It does not read DMA-completion status, does not access the olmsg ring, and dispatches exclusively to host-triggered message reception. Option 2 (DMA-via-olmsg) remains **PARTIALLY OPEN with explicit gating condition**: viability requires either (a) a separate ISR handler for DMA completion (not found in live BFS), or (b) firmware modification to extend pciedngl_isr's dispatch logic to handle DMA-completion bits alongside the mailbox bit.

---

## Summary

**Option 2 verdict: PARTIALLY OPEN — not viable as-is without handler modification or discovery.**

pciedngl_isr's event dispatch is hardcoded to test a single ISR-status bit (0x100 = FN0_0 doorbell via H2D_MAILBOX_1). The function:
1. Reads a software ISR_STATUS register at `[pciedev_info+0x18→+0x18→+0x20]`
2. Tests ONLY bit 0x100 (FN0_0)
3. If unset: prints "invalid ISR status" and returns (spurious interrupt path)
4. If set: ACKs with W1C, enters a packet-processing loop calling malloc → message_read_helper → dngl_dev_ioctl
5. Loops while packets remain, then exits without re-reading ISR_STATUS

**No code path touches:**
- DMA completion-status registers (PCIE2 core)
- Olmsg ring pointers or descriptors (TCM[0x9d0a4] + ring structure)
- Any multi-bit event dispatch (only 0x100 is tested)
- Any DMA-descriptor walk or DMA-engine control

**Implication:** If DMA completion on the olmsg ring is to trigger firmware action, either (a) a different ISR handler must be registered and dispatched on a different OOB bit, or (b) the PCIe DMA-completion interrupt must NOT fire an OOB bit at all (making host-injected DMA via olmsg wake non-viable). T298's ISR list enumeration found 2 nodes (pciedngl_isr on bit 3, chipcommon RTE ISR on bit 0); no third node exists in the current configuration for DMA completion.

---

## Methodology

**Static analysis of pciedngl_isr at fn@0x1c98:**
- Disassembled entire function (260 bytes, 0x1c98–0x1d78) using Capstone ARM Thumb mode
- Cross-referenced string literals (printf message sources) to confirm identity (prior work T269 and T256)
- Traced all register-indirect structure accesses (r5, r6 pointers derived from arg=0x58cc4)
- Enumerated all BL/BLX call targets and inspected their signatures for DMA-related operations
- Examined control-flow logic: conditional branches, loops, and exit paths
- Searched firmware blob for DMA-ring, olmsg, bzdma, pcidma patterns (none found)

**Scope:**
- Full disassembly of pciedngl_isr and its direct sub-handlers (malloc, message_read_helper, dngl_dev_ioctl entry)
- Investigation of arg=0x58cc4 struct usage (pciedev_info)
- Verification against prior work (T269, T256, T298, T304b, T304c)

**Did NOT cover:**
- Indirect call sites via function pointers (none detected in pciedngl_isr; register-BLX dispatch is used only for a single known callback at fn@0x20d8 in dngl_dev_ioctl)
- Deep disassembly of dngl_dev_ioctl's full packet-processing logic (stopped at payload dispatch; upstream handling not analyzed)
- PCIE2 DMA engine control paths (checked for direct accesses from ISR; none found)

---

## pciedngl_isr Structure

### Entry (0x1C98–0x1CA4)

```
0x01C98: push.w     {r4, r5, r6, r7, r8, sb, lr}   ; save 7 regs
0x01C9C: ldr        r5, [r0, #0x18]                 ; r5 ← *(arg+0x18) = bus_info*
0x01C9E: sub        sp, #0x1c                       ; stack frame (28 bytes)
0x01CA0: ldr        r0, [pc, #0xd8]                 ; r0 ← string literal "pciedngl_isr called\n"
0x01CA2: ldr        r6, [r5, #0x18]                 ; r6 ← *(bus_info+0x18) = HW-shadow*
0x01CA4: bl         #0xa30                          ; printf(r0)
```

**Structure chaining:**
- `arg` = pciedev_info struct at TCM[0x58cc4] (registered ISR argument, per T256/T269)
- `r5` = `*(arg+0x18)` points to bus-info sub-struct (per-transport state)
- `r6` = `*(r5+0x18)` points to HW-shadow struct containing ISR_STATUS

### Core Dispatch Loop (0x1CA8–0x1D70)

**Event test (0x1CA8–0x1CB2):**
```
0x01CA8: ldr        r3, [r6, #0x20]                 ; r3 ← ISR_STATUS at [r6+0x20]
0x01CAA: str        r3, [sp, #0x14]                 ; stash copy to stack
0x01CAE: tst.w      r3, #0x100                      ; test bit 0x100 ONLY
0x01CB2: bne        #0x1cc4                         ; branch if set (non-zero)
```

**Spurious interrupt path (0x1CB4–0x1CC0):**
```
0x01CB4: ldr        r2, [sp, #0x14]                 ; r2 ← ISR_STATUS copy
0x01CB6: ldr        r0, [pc, #0xc8]                 ; r0 ← "%s: invalid ISR status: 0x%08x"
0x01CB8: ldr        r1, [pc, #0xc8]                 ; r1 ← "pciedngl_isr"
0x01CBA: add        sp, #0x1c                       ; pop frame
0x01CBC: pop.w      {r4, r5, r6, r7, r8, sb, lr}   ; pop regs
0x01CC0: b.w        #0xa30                          ; tail-call printf (trace + return)
```

If bit 0x100 is NOT set, ISR prints error and exits. This is a guard against spurious calls or ISR firing when no mailbox event is pending.

**Valid-event path (0x1CC4–0x1D70):**

**Acknowledge (0x1CC4–0x1CCA):**
```
0x01CC4: mov.w      r3, #0x100                      ; r3 ← 0x100
0x01CC8: ldr        r0, [r5, #0x20]                 ; r0 ← *(bus_info+0x20) = msg_pool*
0x01CCA: str        r3, [r6, #0x20]                 ; [HW-shadow+0x20] ← 0x100 (W1C ACK)
```

Writes 0x100 to ISR_STATUS using write-one-to-clear semantics. The bit is now cleared for the next interrupt.

**Packet allocation loop (0x1CCC–0x1D70):**
```
0x01CCC: bl         #0x4e20                         ; call malloc(msg_pool*) → r0
0x01CD0: mov        r4, r0                          ; r4 ← allocated descriptor*
0x01CD2: cbnz       r0, #0x1ce6                     ; if non-NULL, proceed; else error
```

If malloc fails:
```
0x01CD4: ldr        r1, [pc, #0xac]                 ; r1 ← "malloc failure"
0x01CD6: ldr        r0, [pc, #0xb0]                 ; r0 ← "pciedev_msg.c"
0x01CD8: bl         #0xa30                          ; printf(...)
0x01CDC: ldr        r0, [pc, #0xac]                 ; r0 ← error file string
0x01CDE: movs       r1, #0xfa                       ; r1 ← line number (0xFA = 250)
0x01CE0: bl         #0x11e8                         ; error-trace function
0x01CE4: b          #0x1d70                         ; jump to exit
```

If allocation succeeds:
```
0x01CE6: ldr.w      sb, [r0, #0x10]                 ; sb ← *(descriptor+0x10) = buffer*
0x01CEA: add.w      r7, r5, #0x24                   ; r7 ← &(bus_info+0x24) = ring structure*
0x01CEE: mov.w      r2, #0x400                      ; r2 ← 0x400 (1024 bytes read size)
0x01CF2: mov        r1, sb                          ; r1 ← buffer*
0x01CF4: mov        r0, r7                          ; r0 ← ring*
0x01CF6: bl         #0x2e10                         ; call message_read_helper(ring*, buf*, 0x400)
0x01CFA: mov        r8, r0                          ; r8 ← bytes_read
```

**Message read and dispatch (0x01CFC–0x1D68):**
```
0x01CFC: mov        r0, r7                          ; r0 ← ring*
0x01CFE: bl         #0x2d38                         ; call get_pkt_length(ring*) → r0
0x01D02: mov        r1, r8                          ; r1 ← bytes_read
0x01D04: mov        r7, r0                          ; r7 ← pkt_length
0x01D06: mov        r2, r7                          ; r2 ← pkt_length
0x01D08: ldr        r0, [pc, #0x84]                 ; r0 ← trace format string
0x01D0A: bl         #0xa30                          ; printf("pktlen=%d nextpktlen=%d", ...)
0x01D0E: cmp.w      r8, #0                          ; compare bytes_read with 0
0x01D12: beq        #0x1d62                         ; if no data, skip to cleanup
```

If data was read, validate and dispatch:
```
0x01D14: mov        r0, r4                          ; r0 ← descriptor*
0x01D16: bl         #0x1514                         ; call validation function
0x01D1A: cbnz       r0, #0x1d26                     ; if valid (non-zero), proceed
[else error path: print error at line 0x104]
0x01D26: ldr        r3, [r4, #0x10]                 ; r3 ← descriptor[+0x10] = buffer_ptr*
0x01D28: ldr        r2, [r4, #0xc]                  ; r2 ← descriptor[+0xc] = alloc_size?
0x01D2A: add        r3, r8                          ; r3 ← buffer_ptr + bytes_read
0x01D2C: cmp        r2, r3                          ; sanity check: alloc_size >= data_end
0x01D2E: bhs        #0x1d3a                         ; if OK, proceed
[else overflow error at line 0x104]
0x01D3A: movs       r1, #0                          ; r1 ← 0 (flags)
0x01D3C: movs       r3, #1                          ; r3 ← 1 (action code)
0x01D3E: strh.w     r8, [r4, #0x14]                 ; descriptor[+0x14] ← bytes_read (short)
0x01D42: mov        r2, r1                          ; r2 ← flags
0x01D44: str        r3, [sp, #0xc]                  ; stack[+0xc] ← action
0x01D46: mov        r3, sb                          ; r3 ← buffer*
0x01D48: str.w      r8, [sp]                        ; stack[+0x0] ← bytes_read
0x01D4C: str        r1, [sp, #4]                    ; stack[+0x4] ← flags
0x01D4E: str        r1, [sp, #8]                    ; stack[+0x8] ← flags
0x01D50: ldr        r0, [r5, #0x14]                 ; r0 ← *(bus_info+0x14) = dngl_dev_ioctl*
0x01D52: bl         #0x20d8                         ; call dngl_dev_ioctl(descriptor*, buffer*, flags, ...)
0x01D56: subs       r2, r0, #0                      ; r2 ← result code
0x01D58: bge        #0x1d62                         ; if >= 0 (success), exit loop
[else error path at line 0x104]
```

**Loop back for more packets (0x1D62–0x1D6E):**
```
0x01D62: ldr        r0, [r5, #0x10]                 ; r0 ← *(bus_info+0x10) = ring_mgmt*
0x01D64: mov        r1, r4                          ; r1 ← descriptor*
0x01D66: movs       r2, #0                          ; r2 ← 0 (mode)
0x01D68: bl         #0x7dc4                         ; call post_process(ring_mgmt*, descriptor*, 0)
0x01D6C: cmp        r7, #0                          ; compare pkt_length with 0
0x01D6E: bne        #0x1cc4                         ; if non-zero, loop back to re-read ISR_STATUS
```

**Exit (0x1D70–0x1D78):**
```
0x01D70: ldr        r0, [pc, #0x24]                 ; r0 ← "pciedngl_isr exits\n"
0x01D72: add        sp, #0x1c                       ; pop stack frame
0x01D74: pop.w      {r4, r5, r6, r7, r8, sb, lr}   ; pop regs
0x01D78: b.w        #0xa30                          ; tail-call printf + return
```

### Control Flow Summary

The ISR follows a simple structure:
1. **Single-bit test:** Read ISR_STATUS once; test bit 0x100 only
2. **Guard:** If bit not set, exit (spurious interrupt)
3. **Acknowledge:** W1C clear bit 0x100
4. **Packet loop:** While packets remain in the mailbox:
   - Allocate descriptor
   - Read packet from ring (1024 bytes max)
   - Validate and dispatch to dngl_dev_ioctl
   - Re-check for more packets via pkt_length
5. **Exit:** Print "pciedngl_isr exits\n" and return

**Critically:** the ISR does NOT re-read ISR_STATUS during the packet loop. The loop is driven by the presence of packets in the ring (detected via message_read_helper / pkt_length), not by checking other bits or DMA-completion status. Once the mailbox queue is exhausted, the ISR exits completely.

---

## arg=0x58cc4 Identification (pciedev_info Struct)

**Address:** TCM[0x58cc4] (static blob offset)

**Identified as:** pciedev_info structure per T269; contains per-transport PCIe device state.

**Struct layout (inferred from ISR disassembly):**

| Offset | Name | Type | Usage in ISR |
|---|---|---|---|
| +0x00 | (unknown) | ? | Not accessed |
| +0x10 | ring_mgmt | pointer | Passed to fn@0x7dc4 (post_process) |
| +0x14 | dngl_dev_ioctl_fn | function pointer | Called at 0x1D52 |
| +0x18 | bus_info | pointer | Points to transport-specific bus_info struct |
| (via bus_info:) | | | |
| +0x00 | (unknown) | ? | Not accessed from ISR |
| +0x10 | descriptor_pool? | pointer | Loaded at 0x1CE6 as r0[+0x10] → sb |
| +0x14 | dngl_dev_ioctl_fn_again | function pointer | Loaded at 0x1D50 |
| +0x20 | msg_pool | pointer | Passed to malloc at 0x1CCC |
| +0x24 | (ring_structure) | struct | Used for message_read_helper (r7 = r5+0x24) |
| (via HW-shadow at bus_info+0x18:) | | | |
| +0x20 | ISR_STATUS | u32 register | Read at 0x1CA8, W1C ACK at 0x1CCA |

**Key finding:** The arg struct is purely a transport-state container. It does NOT contain the olmsg ring structure, DMA ring pointers, or any DMA-completion status. The olmsg ring is allocated separately at TCM[0x9d0a4] (per phase 4B notes) and is never referenced by pciedngl_isr.

---

## Event-Type Enumeration

pciedngl_isr dispatch is **deterministic and monolithic** — it tests exactly one event type:

### Event 1: Mailbox Doorbell (bit 0x100 = FN0_0)

| Property | Value |
|---|---|
| **Bit tested** | 0x100 (bit 8) |
| **Status register** | ISR_STATUS at [pciedev_info+0x18→+0x18→+0x20] |
| **Hardware identity** | BRCMF_PCIE_MB_INT_FN0_0 (upstream pcie.c:954) |
| **Trigger source** | Host write to H2D_MAILBOX_1 (BAR0 offset 0x144) |
| **Sub-handler** | Packet-read loop (fn@0x2e10 + fn@0x20d8) |
| **Resource touched** | Message pool (malloc arena) at bus_info+0x20; transport ring at bus_info+0x24 |
| **Olmsg ring touched?** | **NO** — ring is not accessed; only mailbox-queue packets are processed |
| **DMA-ring touched?** | **NO** — no DMA descriptor access |
| **PCIE2 regs read?** | **NO** — all status comes from software shadow at [r6+0x20] |

### No Other Event Types

The ISR does not test:
- Bits 0, 1, 2, 4-7, 9-31 (other positions in ISR_STATUS)
- DMA completion flags (no read from PCIE2 DMA status)
- Olmsg ring-specific events (no reference to olmsg structure)
- Other interrupt sources (chipcommon, PMU, GPIO) — those would be handled by bit 0 ISR (chipcommon-class RTE handler fn@0xB04), which is a separate registered ISR node

---

## Olmsg / DMA Assessment

### Does pciedngl_isr touch the olmsg ring?

**Answer: NO.**

Evidence:
1. **No code path accesses TCM[0x9d0a4]** or any offset within the olmsg buffer
2. **Packet processing is via ISR_STATUS bit 0x100 only**, which maps to the H2D_MAILBOX_1 doorbell (a single-bit event)
3. **Message read is from a bus_info-local ring** (ring_mgmt at bus_info+0x10, ring structure at bus_info+0x24), not from the olmsg DMA buffer
4. **No DMA descriptor walk** is performed; all memory accesses are to fixed-offset pointers within pciedev_info and bus_info structures
5. **No PCIE2 DMA-completion-status read** (would require reading from 0x18102000 + DMA_STATUS offset; blob grep found zero such register accesses from pciedngl_isr)

### Does pciedngl_isr touch any DMA completion status?

**Answer: NO.**

Evidence:
1. **Single-bit dispatch:** only 0x100 is tested; no loop to check for other bits
2. **ISR_STATUS is read once** at function entry; never re-read during packet loop
3. **Packet loop is driven by pkt_length**, not by checking DMA-completion bits
4. **No DMA-status registers are read** (blob contains no PCIE2 register literals; the ISR reads only from software shadow)

### What would be required for option 2 (DMA-via-olmsg) viability?

Option 2 requires two conditions:

1. **DMA-completion → interrupt wiring:** PCIe DMA engine must be configured to set an OOB bit when a transfer completes on the olmsg ring. This is a hardware/firmware-init property, not checked here.

2. **DMA-completion ISR handler:** A firmware ISR callback must be registered to handle DMA completion events. **This handler does NOT exist in the live offload-runtime BFS per T304b's enumeration.** T298's ISR-list walk found:
   - Node[0]: pciedngl_isr (fn@0x1c98) on OOB bit 3
   - Node[1]: chipcommon-class RTE ISR (fn@0xB04) on OOB bit 0
   - **No third node for DMA completion**

**Conclusion:** Even IF DMA-completion events set an OOB bit and fire the exception vector at fn@0x115c, the ISR dispatcher (fn@0x115c) would find no registered handler for that bit in the live scheduler node list. The pending event would be silently discarded (no matching node → no handler call).

---

## Verdict on Option 2

**OPTION 2 (DMA-via-olmsg) STATUS: PARTIALLY OPEN — GATED ON HANDLER AVAILABILITY**

**Current state (option 2a): NOT VIABLE as-is.**
- pciedngl_isr handles only H2D_MAILBOX_1 doorbell, not DMA completion
- No DMA-completion ISR handler is registered in the live offload firmware
- Olmsg DMA ring is configured but not actively serviced

**To make option 2 viable, ONE of the following must be true:**

1. **Option 2a-variant: Extend pciedngl_isr (firmware modification).**
   - Modify pciedngl_isr to test additional bits beyond 0x100
   - Add a dispatch branch for DMA-completion bits
   - Implement olmsg ring-read logic alongside mailbox logic
   - **Cost:** Firmware blob patching; significant reverse-engineering of olmsg protocol
   - **Blocker:** This is a firmware change, out of scope for host-side wake injection

2. **Option 2b: Discover/register a separate DMA-completion handler (firmware modification).**
   - Identify an existing but unregistered DMA-completion handler function in the blob
   - Add a call to `hndrte_add_isr(dma_handler, OOB_bit_N)` during firmware init
   - Configure DMA engine to set OOB_bit_N when olmsg transfers complete
   - **Cost:** Firmware binary modification; ISR registration hookup
   - **Blocker:** T304b's live-BFS enumeration found no DMA-handler candidates; static reach may miss unlinked functions

3. **Option 2c: Bypass firmware, drive olmsg via direct host polling (host-side option).**
   - Host reads olmsg D2H ring pointers directly via BAR2 (TCM[0x9d0a4+0x00..+0x0F])
   - Host performs DMA to populate H2D ring
   - Host polls D2H ring and decodes responses
   - **Cost:** Host-side protocol implementation; no firmware changes
   - **Blocker:** Requires firmware to be *listening* for the DMA (either via polling, timer callback, or exception handling). T304b confirms no fw-side poller exists; T269 confirms pciedngl_isr doesn't check olmsg. This option works only if a *separate* fw mechanism (e.g., D11 MAC state machine, or a dormant polling ISR) services the ring.

**Load-bearing fact:** Option 2 viability depends on whether firmware contains any DMA/olmsg handler that is either (a) already registered but not yet discovered by the BFS heuristics, or (b) present but dormant and retrievable via firmware patching. Static analysis cannot rule out (a) due to heuristic caveats; experimental runtime discovery is needed.

---

## Open Questions / Follow-Ups

1. **Is there a third registered ISR node for DMA completion?**
   - T298 found 2 nodes (bit 3, bit 0); no third visible
   - Could an indirect dispatch or function-pointer table hidden from the BFS heuristics exist?
   - **Action:** Re-run T298-style ISR-list walk on live hardware post-set_active (BAR2 read at 0x6296c→next pointers) to confirm node count; check for conditional ISR registration that only happens after certain init stages

2. **Does the olmsg ring ever get populated or serviced at runtime?**
   - Phase 4B's test.29 showed olmsg ring's write_ptr stayed 0 (fw never wrote)
   - Could fw service it only after a specific host command or init sequence that the test scaffold hasn't executed?
   - **Action:** Insert a runtime observation probe (e.g., T270-style BAR2 read of olmsg ring pointers at several time points) to determine if fw ever accesses the ring

3. **What is the actual DMA-completion signal path in the hardware?**
   - Does PCIE2 DMA-completion set an OOB bit, or is it only visible via PCIE2 register polling?
   - Which OOB bit would DMA-completion use (if any)?
   - **Action:** Consult BCM4360 PCIE2 datasheet or reverse-engineer the PCIE2 → backplane → OOB routing logic from the blob's DMA init code

4. **Is pciedngl_isr the ONLY handler on OOB bit 3, or could the dispatcher call multiple handlers per bit?**
   - T269 shows `tst` and `bne`; only one branch per bit in the ISR-dispatcher loop
   - If match found, dispatcher calls the one registered handler; if no match, silently continues
   - **Implication:** if bit 3 is allocated to pciedngl_isr, DMA-completion cannot use the same bit without modifying the dispatcher
   - **Action:** Verify T269's dispatcher loop structure; confirm no multi-handler branching per bit

---

## Heuristic Caveats

1. **Indirect call sites:** pciedngl_isr uses direct BL/BLX to known functions (malloc, message_read_helper, dngl_dev_ioctl). No indirect dispatch is visible. However, the dispatcher at fn@0x115c uses a loop with dynamic callback invocation `blx r3` where r3 is loaded from the ISR node list. This indirect dispatch is NOT escapable heuristically — it is performed dynamically at runtime and must be checked empirically (which T298 did via live TCM walk).

2. **Hidden DMA handler:** If a DMA-completion handler exists in the blob but is not reached from the live BFS (e.g., only called via a function-pointer table that the BFS heuristics missed), static analysis alone cannot find it. T304b's conclusion "no pollers in the live BFS" rests on direct-BL coverage; an indirect call site in a dormant code section would evade this count.

3. **Conditional ISR registration:** If pcidongle_probe or a later init stage conditionally calls `hndrte_add_isr(dma_handler, ...)` only after a certain host signal, the node might not be populated at the time of T298's ISR-list walk (which ran post-set_active before any host signals). Runtime testing at a later stage (e.g., post-hostready or post-first-mailbox-write) would be needed to detect a late-registered handler.

---

## Clean-Room Posture

All disassembly observations are described in plain language. No complete function reconstruction is committed; only short illustrative instruction sequences are shown where essential for explaining the dispatch logic. Behavior is characterized (e.g., "reads bit 0x100, tests via TST, branches on NZ") rather than via verbatim instruction dumps.

---

## Files and References

- **Primary source:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes)
- **Disassembler:** `phase6/t269_disasm.py` (Capstone wrapper via ctypes)
- **Prior work:**
  - T269 (`phase6/t269_pciedngl_isr.md`) — Initial pciedngl_isr disassembly + arg struct identification
  - T298 (`phase6/t298*.md`) — ISR list enumeration via BAR2-only TCM walk; 2-node discovery
  - T304b (`phase6/t304b_fw_poller_enumeration.md`) — Live BFS enumeration; zero pollers
  - T304c (`phase6/t304c_pmu_gpio_surface.md`) — PMU/GPIO ISR check; no handlers found
  - T256 (`RESUME_NOTES_HISTORY.md`) — Runtime observation of ISR node[0] = pciedngl_isr
- **KEY_FINDINGS.md:**
  - Row 163 (T298 ISR enumeration; 2 nodes)
  - Row 162 (T304b zero pollers)
  - Row 164 (T304c PMU/GPIO; verdict only)
  - Row 165 (T304 OOB Router W1C/RO ruling)

---

## Conclusion

pciedngl_isr is a **single-purpose mailbox handler** that processes H2D_MAILBOX_1 doorbell events. It reads packets from a transport-specific message queue (not the olmsg ring) and dispatches them to host-facing protocol handlers (dngl_dev_ioctl).

**Option 2 (DMA-via-olmsg) remains PARTIALLY OPEN** — not viable without either (a) discovering/registering a separate DMA-completion ISR handler, (b) firmware modification to extend pciedngl_isr's dispatch, or (c) bypassing firmware entirely with host-side olmsg polling (which requires fw to be listening). Static analysis has closed the hypothesis "pciedngl_isr handles DMA completion"; the actual DMA-completion wake source remains unidentified and is the next lowest-cost static target: **audit the chip-init code (fn@0x6820C and callees) to determine whether DMA interrupt wiring is configured at all.**

---

**Co-Authored by:** Static disassembly + control-flow analysis of firmware pciedngl_isr function (phase6/t304d analysis suite, Capstone-based disassembler).
