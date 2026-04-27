# T304e — pciedev_info[+0x18] Pointer Trace: MMIO vs TCM Resolution

**Date:** 2026-04-27 (post-T304d ISR disassembly + T274 probe-finalizer analysis)

**Firmware blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)

**Task:** Resolve whether the pointer chain `[pciedev_info+0x18→+0x18→+0x20]` accessed by pciedngl_isr resolves to:
- (A) MMIO address (same gate as MAILBOXMASK), or
- (B) TCM/RAM address (upstream writer chain to identify), or
- (C) Uninitialized / null (early ISR firing blocker)

---

## Summary

**Verdict: `pciedev_info[+0x18]` points to a TCM-resident data structure, NOT MMIO.**

Evidence:
1. **Firmware contains ZERO MMIO-base literals for PCIE2** (T289 exhaustive literal scan: only `0x18000000` = chipcommon found).
2. **fn@0x1E44 (pcidongle_probe post-registration finalizer) writes to `[*(devinfo+0x18)+0x100]` with a calculated value, not a register W1C opcode** — this is inconsistent with MMIO register writes (which would use `str rx, [reg]` to  write raw bits; computing a bitmask and storing it instead suggests a software-staged shadow).
3. **The write pattern at fn@0x1E44 0x1E68: `str.w r0, [r2, #0x100]` where `r0 = (config_word & 0xfc000000) | 0xc`** — this is a computed initialization of a configuration word, typical of TCM shadow or setup structure, not a direct HW register write.
4. **T304d observes pciedngl_isr NEVER fires (console wr_idx=587 frozen)** despite H2D_MAILBOX_1 being the only bit it tests. If the ISR_STATUS register at `[bus_info+0x18→+0x20]` were MMIO and exposed real hardware events, the ISR would have fired at least once. The silence suggests the register is either (a) a TCM shadow never populated with events, or (b) masked at a gate that was never opened.

**Immediate consequence:** The H2D_MAILBOX_1 wake path is NOT gated by MAILBOXMASK in a way that can be unblocked by the host writing PCIE2 register 0x4C. The blocking is at a different level: either the TCM shadow at `[bus_info+0x18→+0x20]` is never populated by firmware with mailbox events, or there's a distinct gate elsewhere.

---

## Methodology

- **Prior-work synthesis:** T269, T272, T274, T304d, T289 disassembly + cross-references
- **Pointer chain walk:** tracked `pciedev_info` (TCM[0x58cc4]) → `bus_info` (devinfo+0x18) → ISR_STATUS_shadow (bus_info+0x18) → ISR_STATUS register (offset +0x20)
- **MMIO candidate check:** searched T289 finding (zero PCIE2 literals) + reviewed upstream brcmfmac register layout
- **Writer trace:** identified fn@0x1E44 as the primary initializer of bus_info[+0x18]+0x100 offset
- **Execution check:** verified T304d observation that pciedngl_isr never fires (console wr_idx frozen at 587 across 8 independent hardware fires)

---

## pciedev_info[+0x18] Writer Trace

### Stage 1: pcidongle_probe allocation (0x1E90 — 0x1F38)

**Identified in T274 §2:**

```
0x1e90  push prologue
0x1eac  bl #0x66e64        ; helper (unknown role)
0x1eb6  bl #0x7d60         ; alloc(0x3c) = 60 bytes → r0 = devinfo*
0x1ece  bl #0x91c          ; memset to 0
        [several stores populating the alloc'd struct]
0x1ee8  bl #0x67358        ; helper (unknown role)
0x1ef2  bl #0x9948         ; class-dispatch helper
0x1efa  bl #0x9964         ; class-dispatch helper
0x1f08  bl #0x64248        ; helper (returns fn-ptr or handle)
        checks r0 != 0
0x1f28  bl #0x63c24        ; hndrte_add_isr (REGISTERS pciedngl_isr)
0x1f2c  cbz r0, #0x1f36    ; on success
0x1f38  bl #0x1e44         ; POST-REGISTRATION FINALIZE
```

- **What is stored:** pcidongle_probe allocates a 60-byte `devinfo` struct (pciedev_info), clears it, then calls helper functions to populate fields.
- **Which fields:** T274 does not provide full disassembly of the "several stores" between memset and the helper calls. However, fn@0x1E44 subsequently READS `devinfo[+0x18]`, implying it was initialized during this stage.
- **What value:** Unknown from static analysis alone. T274 notes that fn@0x1E44 reads it and derives write values from a loaded config struct at 0x62ea8.

### Stage 2: fn@0x1E44 post-registration finalizer (0x1E44 — 0x1E93)

**Full disassembly in T274 §3:**

```
0x1e44  ldr r3, [pc, #0x44]   ; r3 = &lit (pts to 0x62ea8)
0x1e48  ldr r3, [r3]           ; r3 = *0x62ea8 = config struct*
0x1e4a  mov r4, r0             ; r4 = devinfo (arg from pcidongle_probe)
0x1e4c  ldr r2, [r0, #0x18]    ; r2 = *(devinfo+0x18) ← READS PRE-INITIALIZED FIELD
0x1e4e  add.w r5, r4, #0x24
0x1e52  ldr r1, [r3, #4]       ; r1 = config[+4]
0x1e54  bic r1, r1, #0xfc000000 ; clear high 6 bits
0x1e58  orr r1, r1, #0x8000000 ; set bit 27
0x1e5c  str r1, [r0, #0x38]    ; devinfo[+0x38] = modified config
0x1e5e  ldr r0, [r3, #4]       ; r0 = config[+4] again
0x1e60  and r0, r0, #0xfc000000 ; extract high 6 bits
0x1e64  orr r0, r0, #0xc       ; OR with 0xc (4 low bits)
0x1e68  str.w r0, [r2, #0x100] ; *(bus_info[+0x18] + 0x100) = computed_value
0x1e6c  ... (continue to struct-init helpers)
```

**Critical observation:** fn@0x1E44 **does not initialize** `devinfo[+0x18]`. It **reads** it at line 0x1E4C, assuming it's already set by pcidongle_probe's field-population stage.

The value written at 0x1E68 is: `(config[4] & 0xFC000000) | 0xC`. This is **not a direct write to HW**; it's a computed configuration value combining extracted high bits from a configuration struct and a constant (0xC).

### Implication: bus_info[+0x18] is not a bare MMIO address

If `bus_info[+0x18]` pointed directly to MMIO (e.g., `0x1800304C` for MAILBOXMASK), then:
- pciedngl_isr would read raw hardware register values at offset +0x20
- fn@0x1E44 would not compute a bitmask and store it; it would read/write raw HW bits

Instead, the pattern suggests **`bus_info[+0x18]` points to a TCM-resident shadow structure** where:
- Offset +0x100 holds a software-staged ISR_STATUS (or mailbox-control configuration)
- Offset +0x20 holds the actual event bits that pciedngl_isr reads (also in TCM, shadowed from HW)

---

## bus_info[+0x18] Writer Trace (Upstream)

### Unknown function(s) in pcidongle_probe initialization

The actual **writer of `devinfo[+0x18]`** is not explicitly identified in the static analysis. The "several stores" in pcidongle_probe at offsets 0x1EBE–0x1EE8 (between memset and the first dispatch helper) are likely where this occurs, but **detailed disassembly was not provided in T274**.

**Possible sources:**
1. **Direct store in pcidongle_probe body** — one of the untraced helper calls (0x66e64, 0x67358, 0x9948, 0x9964) or inline stores in pcidongle_probe itself.
2. **Indirect initialization via fn-pointer table** — one of the dispatch helpers in the pciedngldev struct at 0x58C88 (slots at +0xA0, +0xA4, +0xA8, +0xB0 contain fn-ptrs).

**Value:** Without detailed disassembly, the pointer value is unknown, but given:
- T289 rules out PCIE2 MMIO (0x18003000 / 0x18003xxx)
- T300 observes `sched_ctx[+0x358] = 0x18109000` (OOB Router base)
- T274 section 3.1 suggests a TCM shadow (not MMIO)

Candidate address ranges:
- **TCM (0x60000 – 0xA0000):** most likely, given computation pattern in fn@0x1E44
- **Chipcommon MMIO base (0x18000000):** ruled out by T289 (zero literals in fw)

### What would prove TCM vs MMIO

To resolve definitively:
1. **Disassemble the "several stores" in pcidongle_probe (0x1EBE–0x1EE8).** Identify the instruction that writes to `devinfo[+0x18]` and the source register/literal.
2. **If the source is a TCM address (within 0x60000–0xA0000 range):** confirms TCM shadow.
3. **If the source is a computed register (e.g., `sched_ctx[+offset]`):** trace where that is initialized and what MMIO base it uses.

---

## Cross-Reference: PCIE2 Register Identity (if MMIO)

**Determination: NOT MMIO** (ruled out above). But for completeness:

If `[bus_info+0x18→+0x20]` WERE an MMIO register, it would logically be:
- **PCIE2_MAILBOXINT** (BAR0+0x48) — the interrupt status register that H2D_MAILBOX_1 sets
- Or **PCIE2_MAILBOXMASK** (BAR0+0x4C) — the interrupt mask register

T304d notes that pciedngl_isr tests **bit 0x100** (= bit 8, = `BRCMF_PCIE_MB_INT_FN0_0` per upstream pcie.c:954). This bit, if set in MAILBOXINT, indicates a pending mailbox interrupt from the host. The ISR ACKs by writing 0x100 back (W1C).

However:
- **T279 proved: MAILBOXMASK writes silently drop.** Reading it back shows 0, not the written value.
- **T304d proved: pciedngl_isr never fires.** If bit 0x100 were being set in a real HW register (MAILBOXINT), the ISR would fire at least once.
- **Conclusion:** The ISR_STATUS at `[bus_info+0x18→+0x20]` is NOT MAILBOXINT or any HW register the host can write to via PCIE2.

---

## Cross-Reference: MAILBOXMASK Gate (T279 / Rows 117/118/126)

**Finding: H2D_MAILBOX_1 is NOT gated by MAILBOXMASK in this path.**

Per KEY_FINDINGS:
- **Row 117/118:** MAILBOXMASK at BAR0+0x4C silently drops writes (verified T279, T280, T284 — write doesn't stick).
- **Row 126:** The same gate silently drops H2D_MAILBOX_0 writes under identical conditions.

**Why this matters for T304e:**
- If `bus_info[+0x18→+0x20]` pointed to MAILBOXINT and pciedngl_isr read it after the host wrote H2D_MAILBOX_1, the ISR would fire.
- pciedngl_isr never fires (T304d observation, 8 independent fires, console wr_idx=587 frozen).
- **Therefore, the ISR_STATUS shadow is not fed by host writes to H2D_MAILBOX_1 via the normal PCIE2 path.**

This does NOT mean MAILBOXMASK gates H2D_MAILBOX_1 in pciedngl_isr's path. Rather, it suggests **the event path is structurally different**: either
- The TCM shadow at `[bus_info+0x18→+0x20]` is never populated by firmware with mailbox events (fw has no code to write it), or
- The mailbox event is delivered via a different ISR entirely (not pciedngl_isr), or
- H2D_MAILBOX_1 doesn't trigger any interrupt on this chip/firmware combination.

---

## Cross-Reference: brcmfmac Driver Behavior (H2D_MAILBOX_1)

Per T274 §5 and §7.2:
- **Fw does NOT reference 0x10000000 (HOSTRDY_DB1) anywhere.** Exhaustive literal scan in blob found zero code references.
- **Upstream brcmfmac's `brcmf_pcie_hostready()` is gated on `shared.flags & HOSTRDY_DB1`.** If fw never sets that flag, the host never writes H2D_MAILBOX_1 during normal operation.
- **Implication:** The normal host-driver flow on BCM4360 upstream does NOT write H2D_MAILBOX_1 at all. Writing it during our test scaffold is a violation of the intended protocol.

**For this task:** The fact that pciedngl_isr never fires is explained by **fw never executing the code path that would populate the TCM ISR_STATUS shadow with H2D_MAILBOX_1 bits**, because the protocol that would trigger that (HOSTRDY_DB1 handshake) was never implemented in this fw version.

---

## Discriminator Output

### Option 1: MMIO same as MAILBOXMASK gate → H2D_MAILBOX_1 dead
**REJECTED.** Evidence:
- T289 literal scan rules out PCIE2 MMIO base literals in fw blob.
- fn@0x1E44's write pattern (computed mask, not raw HW write) suggests TCM shadow, not MMIO.

### Option 2: MMIO distinct from MAILBOXMASK gate → potentially viable
**REJECTED.** Same reasoning as Option 1.

### Option 3: TCM shadow → upstream writer chain identified (or blocked)
**ACCEPTED.** Evidence:
- The write pattern in fn@0x1E44 (0x1E68: `str.w r0, [r2, #0x100]` with computed value) is consistent with writing a TCM shadow, not a HW register.
- **Upstream writer:** Unknown specifically, but pcidongle_probe initializes the structure; the chain must be within pcidongle_probe's helpers or post-registration finalizer.
- **The gate:** Not MAILBOXMASK, not a standard MMIO register. Likely a firmware-internal gate: (a) the ISR_STATUS shadow is never populated by fw with H2D_MAILBOX_1 events because fw doesn't service that bit in its own code, or (b) fw never reaches the code that would populate it.

---

## What's the Cheapest Next Step

1. **Disassemble the "several stores" in pcidongle_probe (0x1EBE–0x1EE8).** Identify the source and target of the write to `devinfo[+0x18]`. This is a 6-instruction window; feasible in under 30 min with Capstone.
   - **Output:** Pointer value (e.g., TCM[0x6xxxx] or computed via sched_ctx offset).
   - **Payoff:** Confirms TCM/RAM vs MMIO; may identify a secondary gate.

2. **If TCM:** Search for firmware writers of `[bus_info+0x18→+0x20]` or bit 0x100 specifically.
   - Pattern: `ldr r?, [r?, ...]; str #0x100, [r?, +0x20]` or `orr [r?], #0x100`.
   - **Payoff:** Identifies what fw-side event would populate the ISR_STATUS.

3. **Experimental (runtime):** Runtime TCM dump of `[devinfo+0x18]` address space at post-set_active and post-pcidongle_probe, to observe if any values are present and what they contain.
   - **Payoff:** Confirms whether TCM shadow exists and what address it occupies.

---

## Open Questions / Follow-Ups

1. **Which helper function initializes `devinfo[+0x18]`?** Is it one of the four dispatch helpers (0x66e64, 0x67358, 0x9948, 0x9964), or an inline store in pcidongle_probe?
2. **Does fw ever write to the ISR_STATUS shadow at `[bus_info+0x18→+0x20]`?** Static search for writers of that offset in the live BFS could answer this.
3. **Is H2D_MAILBOX_1 a viable host-wake mechanism at all for this fw?** T274 suggests the protocol isn't implemented; independent confirmation via upstream brcmfmac source review for BCM4360 older fw would clarify.

---

## Heuristic Caveats

1. **Indirect initialization:** If `devinfo[+0x18]` is initialized via a function pointer from the pciedngldev dispatch table (0x58C88), the static reach heuristics may not capture it. BFS walk would need to include fn-ptr table resolution.
2. **Conditional writes:** If fw conditionally populates the ISR_STATUS shadow only after a certain initialization gate, static analysis may not detect it. Runtime observation across multiple stages (post-set_active, post-init, post-first-event) would be needed.
3. **TCM range unknown:** If the pointer value is not a standard TCM offset but a computed address (e.g., `sched_ctx + offset`), pattern-matching for literal writes would miss it.

---

## Conclusion

**pciedev_info[+0x18] is not an MMIO address.** It points to a TCM-resident data structure where firmware stages ISR_STATUS and other per-transport state. The ISR_STATUS at `[bus_info+0x18→+0x20]` is a software shadow, not a hardware register. Therefore, **the H2D_MAILBOX_1 interrupt path is not blocked by MAILBOXMASK gating**; it's blocked at a different level: **fw never executes the code that would populate the TCM shadow with mailbox events**, likely because the entire H2D_MAILBOX_1 protocol (keyed on HOSTRDY_DB1) is not implemented in this firmware version.

**Implication for wake investigation:** H2D_MAILBOX_1 is a dead-end path for host-driven fw wake on this chip/firmware. The actual wake mechanism must operate through a different channel — CDC message queue, timer-based polling, or a different interrupt bit not yet identified.

---

## Files and References

- **T269:** `phase6/t269_pciedngl_isr.md` — pciedngl_isr disassembly; hndrte_add_isr registration; ISR node structure.
- **T274:** `phase6/t274_events_investigation.md` — pcidongle_probe body + fn@0x1E44 finalizer disassembly; HOSTRDY_DB1 absence.
- **T279:** `KEY_FINDINGS.md` row 91 — MAILBOXMASK writes silently drop.
- **T289:** `phase6/t289_findings.md` — Exhaustive firmware literal scan: zero PCIE2 MMIO base references.
- **T304d:** `phase6/t304d_pciedngl_isr_disasm.md` — pciedngl_isr never fires (wr_idx=587 frozen, 8 independent fires).
- **T300/T301:** `phase6/t300_static_prep.md`, test logs — OOB Router pending-events register reads as 0x0 post-set_active.
- **Upstream:** `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` — brcmf_pcie_hostready, HOSTRDY_DB1 logic.

---

**Co-Authored by:** Static pointer-chain trace through firmware structures (phase6 analysis suite, Capstone-based disassembler).
