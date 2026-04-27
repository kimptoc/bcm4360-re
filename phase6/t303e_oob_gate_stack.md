# T303e — OOB Router gate stack analysis: host → fn@0x115c execution path

**Date:** 2026-04-27 (post-T303 hardware fire, static analysis only)

**Goal:** Map the gate stack between (a) host writing to OOB Router pending register at 0x18109100 and (b) firmware executing fn@0x115c (the OOB ISR dispatcher). Identify each gate as known-open, known-closed, or unknown, with evidence for option B (host-side wake-event injection) feasibility assessment.

---

## Headline Matrix: Gate Status Summary

| Gate # | Name | Status | Evidence | Impact on Option B |
|--------|------|--------|----------|-------------------|
| 1 | OOB Router +0x100 write semantics (RW1S vs W1C vs RO) | UNKNOWN | No published ARM 0x367 datasheet; Linux bcma drivers read-only; T300/T301 sample 1 succeeded but never wrote to this register | CRITICAL — if RO or W1C, host write has no effect |
| 2 | oobselouta30/74 routing enable (bits that unmask OOB→ARM path) | UNKNOWN | T298 confirms bits 0/3 allocated; no evidence whether these bits gate output or just select output line | MODERATE — if routing is disabled by default, host must enable it first |
| 3 | ARM CR4 IRQ controller mask (CPSR I-bit + interrupt controller mask) | UNKNOWN | No static discovery of ARM GIC/interrupt-controller initialization; fw blob uses on-dispatch ISR reading with exception-vector entry but no explicit IRQ-enable code found | CRITICAL — if global IRQ disabled or vector masked, no exception fires regardless of pending bit |
| 4 | MSI/interrupt-delivery path from OOB Router to ARM exception interface | UNKNOWN | OOB Router (0x367) is a distinct backplane agent; exact upstream aggregation path (SiliconBackplane IRQ, MSI interface, GCI, etc.) not documented in publicly available ARM/BCM sources | CRITICAL — if path broken or blocked, no exception fires on pending bit set |
| 5 | fn@0x115c reachability from exception vector (gate within fn@0x138 chain) | KNOWN-OPEN | Per T303d: fn@0x115c reached by fallthrough from exception-vector chain (fn@0x138 + continuation), single synchronous read-dispatch pattern, no conditional gates blocking dispatch | LOW — once exception fires, dispatcher will execute; no additional checks between exception entry and fn@0x115c |
| 6 | BAR0 write accessibility to 0x18109000 (OOB Router window) | PARTIALLY-OPEN | T300/T301 sample 1 (post-set_active) succeeded n=2; T301 sample 2 (t+60s) wedged at window-write call. Noise belt ruled out per row 85, but time-dependent accessibility remains open. | MODERATE — accessibility is timing-dependent; post-set_active window is clean but narrow |

---

## Per-Gate Detail

### Gate 1: OOB Router +0x100 (pending register) write semantics

**Status:** UNKNOWN

**Question:** Can the host SET pending bits by writing to 0x18109100? Three plausible behaviors:
- **RW1S** (read-write-1-to-set): host write 0x9 sets bits 0+3, asserts upstream
- **W1C** (write-1-to-clear): host write 0x9 CLEARS bits 0+3, blocks dispatch
- **RO** (read-only-by-host): host writes ignored, register is a read-only status of upstream OOB lines

**Evidence:**

1. **Linux bcma driver pattern:** Lines 57–62 of bcma/driver_mips.c show `bcma_aread32(dev, BCMA_MIPS_OOBSELOUTA30)` for reading the OOBSELOUTA30 register (the routing selector at wrap+0x100). Search for corresponding `bcma_awrite32(dev, BCMA_MIPS_OOBSELOUTA30, ...)` — ZERO writes to OOBSELOUTA30 in the bcma driver. Writes DO exist for OOBSELINA74 (the input selector) and for other agent registers, but not for OOBSELOUTA30 itself. **Pattern suggests OOBSELOUTA30 is read-only from host perspective.**

2. **T300/T301 hardware fires:** Sample 1 executed clean BAR0 reads of OOB Router pending (0x18109100) at post-set_active, returning `pending=0x0` (n=2). These were READ operations, not writes. No hardware fire has attempted a WRITE to 0x18109100 to test set semantics.

3. **Broadcom AI-backplane spec pattern:** OOB-related registers in the backplane typically follow "upstream OOB lines assert → agent samples lines and places pending bitmap in a read-only status register → host/fw reads to see pending events." The register is usually read-only, with upstream line control in the actual device/event source.

**Implication:** If OOBSELOUTA30 at wrap+0x100 is the same type of register as the OOB pending-events register at 0x18109100 (which is NOT confirmed), then the host cannot SET bits by writing. The host would need to trigger an upstream OOB-line assertion (via D11, PMU, or another core) and the pending register would reflect that state. **This is the weakest gate — no direct evidence either way.**

**Recommendation:** Test feasibility of option B requires one explicit hardware write to 0x18109100 with a known value (e.g., 0x9) and a subsequent read to confirm whether bits are set. This cannot be done statically.

---

### Gate 2: oobselouta30 / oobselouta74 routing enable bits

**Status:** UNKNOWN

**Question:** Are bits 0/3 of oobselouta30 (the allocated OOB routing slots per T298) enabled for output to ARM, or disabled by default? Is there a separate ENABLE field (e.g., in oobselouta74 at wrap+0x104) gating the output?

**Evidence:**

1. **T298 ISR-list enumeration:** Node[0] = RTE chipcommon-class ISR, mask=0x1 (bit 0 of oobselouta30). Node[1] = pciedngl_isr, mask=0x8 (bit 3). These bits were allocated by BIT_alloc at ISR registration time. No evidence of a parallel ENABLE-bit write.

2. **KEY_FINDINGS row 144:** "Purpose: interrupt-line routing between backplane cores; BIT_alloc scans packed fields of oobselouta30 for unused routing slots." The register is documented as a ROUTING SELECTOR (which line gets output), not as an ENABLE/DISABLE mask.

3. **hndrte_add_isr (T289, T289b):** Function body includes si_setcoreidx (class switch), BIT_alloc (bit-slot allocation), then ISR node construction. ZERO HW register writes besides the SI library calls. No enable-bit set.

4. **oobselouta74 documentation (Linux bcma):** Defined at wrap+0x104 (per BCMA_MIPS_OOBSELINA74 = 0x004 in the MIPS driver). The "INA" (input selector) vs "OUTA" (output selector) naming suggests different roles. INA is read/written by the MIPS driver for MIPS-side IRQ configuration. OUTA is for ARM OOB routing. **No explicit enable-disable pattern observed.**

5. **Static reach on si library (T289, T289b, T303c):** The 9-thunk vector at 0x99AC..0x99CC includes si_setcoreidx, si_core_setctl, si_core_disable, ai_core_reset, etc. None of these write a register resembling "OOB enable" or "OOB mask."

**Implication:** If oobselouta30 bits 0/3 are enabled by default (or enabled during some prior initialization in the non-offload FullMAC path), then a pending bit set on line 0 or 3 would fire. If there is a separate enable/mask in oobselouta74 or elsewhere that is disabled, the path is blocked.

**Residual uncertainty:** The FullMAC path (wl_probe → wlc_bmac_attach → hndrte_add_isr) may have enable logic that was never replicated in the offload-mode sched_ctx initialization. T287c / T303 confirmed that the live offload runtime uses sched_ctx (si_t), not flag_struct (wlc-allocated), and sched_ctx initialization does NOT include explicit OOB enable writes. **THEREFORE:** if the enable was done in FullMAC mode only, it was not re-executed in offload mode, and bits 0/3 are potentially disabled.

---

### Gate 3: ARM CR4 interrupt controller mask

**Status:** UNKNOWN

**Question:** Is the ARM CR4 interrupt controller initialized to accept exceptions on the OOB-routed vector, or is the vector masked / globally disabled?

**Evidence:**

1. **Exception-vector entry discovered (T303d):** The blob's reset vector (offset 0x00) and exception vectors are mapped at firmware address 0x00. Per T274 / T299 static analysis, fn@0x138 is the unified dispatcher reached from these vectors. ~319 functions in the reach set, including fn@0x115c (the OOB ISR dispatcher).

2. **No explicit IRQ-enable code found:** Static disassembly scan for `CPSR.I bit clear` operations (typically via CPSID/CPSIE instructions or exception-return with SPSR modification) found NO explicit enable in the live offload path (rows 161, 299_t306). The FullMAC path (wl.ko, wlc_* functions) has zero reach from the live bootstrap, so any FullMAC-side interrupt-enable is dead code.

3. **Firmware waits in WFI (row 161, RESUME_NOTES):** "fw is alive and idle as designed, waiting for a wake event the test framework hasn't yet generated." T303 console output frozen from t+500ms through t+90s — evidence of WFI idle. WFI (Wait For Interrupt) is a CPU mode that requires interrupts to be globally enabled for the WFI exit; a disabled interrupt would cause infinite WFI hang.

4. **Absence of ARM GIC / NVIC initialization code:** The blob makes ZERO references to ARM Generic Interrupt Controller (GIC) base addresses or NVIC (NVIC is Cortex-M specific; CR4 uses GIC or SiliconBackplane interrupt controller). No initialization of IRQ masks, enable registers, or priority levels in the static reach set.

5. **Implicit assumption in on-dispatch design (T303d):** The reader fn@0x9936 and dispatcher fn@0x115c are reached only from exception context, with NO loop/sleep/poll. **This architecture implicitly assumes interrupts are enabled.** If they were disabled, the code would hang at WFI forever. The empirical WFI-and-idle behavior suggests interrupts ARE enabled globally (otherwise fw would hang, not idle).

**Implication:** The broad structure is consistent with a working interrupt setup (fw enters WFI expecting interrupts to wake it). However, **the specific vector assigned to OOB Router bits 0/3 may be masked at the interrupt controller level.** The static analysis does not discover which ARM IRQ vector number OOB bits are mapped to, nor whether that vector's mask bit is set.

**Residual uncertainty:** Three sub-gates within this gate:
- **CPSR.I bit:** Likely cleared (enabled) — WFI behavior suggests this
- **ARM IRQ-vector to OOB-bit mapping:** UNKNOWN — no static discovery of which ARM IRQ line (0–31 on typical GIC/SB) carries OOB Router events
- **IRQ-controller vector mask:** UNKNOWN — whether that vector's mask bit is set (enabled) or clear (disabled)

---

### Gate 4: Upstream aggregation from OOB Router to ARM exception interface

**Status:** UNKNOWN

**Question:** How does a pending bit in the OOB Router (0x18109000) propagate to the ARM CR4 exception interface? The backplane defines OOB-Router as "interrupt-routing fabric" (per phase1 EROM walk), but the exact upstream path is not documented in public sources.

**Evidence:**

1. **OOB Router BCMA core identity (row 162, phase1/core_enumeration_analysis.md):** Core index 6, mfr ARM, slave port at 0x18109000, size 0x1000, NO master ports, NO wrappers. Classification: "interrupt-routing fabric."

2. **Distinct from other backplane agents:** Unlike chipcommon (which has master/wrapper and can directly assert interrupt lines), OOB Router has only a slave port — it is a **passive aggregator**, not an active source. It routes upstream OOB line assertions from other cores to the ARM CR4.

3. **No ARMv7-R GIC documentation in kernel sources:** The kernel bcma drivers (brcmsmac, brcmfmac) configure OOB routing via OOBSELOUTA30/OOBSELINA74 for MIPS (MIPS32 74K core). There is NO parallel code for ARM CR4 OOB-to-exception mapping. **This suggests the ARM path is either:**
   - (a) Hardwired in SiliconBackplane RTL (bits 0–3 always route to ARM IRQ 0–3, or similar static mapping), or
   - (b) Configured via a separate ARM-side interrupt controller interface not exposed in open-source drivers.

4. **MSI and other interrupt-delivery paths:** Broadcom SiliconBackplane typically offers multiple interrupt mechanisms: MIPS-targeted OOB lines, ARM MSI (Message Signaled Interrupt), D11 MAC interrupts, PMU GPIO-based IRQs, etc. The OOB Router is **one path** but not necessarily the only one, and not necessarily the primary one for offload-mode wake.

5. **T303d (on-dispatch analysis):** Concludes fn@0x115c executes when "a hardware interrupt asserts — which in the test environment appears to be either not occurring at all (pending=0x0 consistently) or occurring very infrequently during the ~90-second observation window." **No evidence that OOB-routed interrupts are actually waking the ARM.**

**Implication:** The OOB Router path from pending bit set to ARM exception may be:**
- **Gated by a SiliconBackplane-side aggregator mask** (e.g., an "ARM IRQ enable" register in the backplane control layer)
- **Not wired at all** (OOB bits 0/3 might route to MIPS or GPIO, not ARM)
- **Conditionally enabled** only during FullMAC mode and disabled in offload mode
- **Correctly wired but the wrong wake mechanism** — the actual fw wake source is D11 MAC events, PMU GPIO, or another path

**Residual uncertainty:** This is the deepest gate. Without access to proprietary Broadcom SiliconBackplane RTL or a detailed ARM CR4 wrapper datasheet, the connectivity is unconfirmed.

---

### Gate 5: fn@0x115c reachability (conditional checks within exception-vector chain)

**Status:** KNOWN-OPEN

**Question:** Once an ARM exception fires and fn@0x138 executes, is there any conditional check that could prevent fn@0x115c from executing?

**Evidence:**

1. **T303d static disassembly:** fn@0x115c is reached by **fallthrough** from fn@0x138 + continuation, not by explicit branch. Fallthrough means the function executes unless an earlier branch instruction jumps away.

2. **fn@0x115c structure (T303d):**
   ```
   0x115c: push {r4, r5, r6, lr}           ; function prologue
   0x115e: ldr r3, [pc, #0x5c]
   0x160:  ldr r0, [r3]                    ; load constant
   0x162:  bl #0x9936                      ; CALL fn@0x9936 — read OOB pending
   0x166:  ldr r3, [pc, #0x58]
   0x168:  ldr r4, [r3]                    ; r4 ← ISR-list head pointer
   0x16a:  mov r5, r0                      ; r5 ← pending-events bitmap
   [...dispatch loop...]
   ```
   No conditional branch before the pending read. The read is unconditional.

3. **Static reach analysis (row 161, T299 series):** The reach set from exception vectors includes fn@0x115c with no conditional entry gates discovered. The dispatcher is part of the standard ARM exception-handling chain.

4. **Cross-check against FullMAC (T297, T299):** The FullMAC `wlc_isr` (fn=0x1146D) has NO reach from the exception vector. Only the offload-mode ISR dispatcher (fn@0x115c) is reachable. This confirms the live path does not have dead-code conditional gates (where a gate would be a branch that is never taken in offload mode).

**Conclusion:** Once an exception fires, fn@0x115c will execute. There are no additional gates at the dispatcher entry level. **This gate is OPEN.**

---

### Gate 6: BAR0 write accessibility to OOB Router window (host-side injection feasibility)

**Status:** PARTIALLY-OPEN

**Question:** Can the host write to BAR0_WINDOW = 0x18109000 and then write/read BAR0+0x100 to manipulate the pending register, or is the OOB Router address space inaccessible at certain timings?

**Evidence:**

1. **T300/T301 sample 1 (post-set_active, n=2):** Both fires executed `pci_write_config_dword(BAR0_WINDOW, 0x18109000)` followed by `BAR0+0x100` read, successfully returning pending=0x0. KEY_FINDINGS row 85 stopping rule previously blocked BAR0 access due to chipcommon-wrap noise; **T300/T301 confirmed the noise belt does NOT extend to OOB Router at post-set_active.**

2. **T301 sample 2 (t+60s):** The same `pci_write_config_dword(BAR0_WINDOW, 0x18109000)` call wedged at the window-write operation. Boot ended same second. T302b (same test without test300) moved the wedge back to [t+90s, t+120s], confirming test300 enablement shifts the bracket forward (row 104). **This suggests time-dependent OOB Router accessibility — at post-set_active it's reachable, but by t+60s the access path may have entered a bad state.**

3. **Noise belt interpretation (row 85):** Substrate-noise belt is per-backplane-agent, not region-wide. OOB Router (0x367) is exempt at post-set_active, but T301 sample 2 suggests the exemption does not extend to all timings.

**Implication:** The host CAN write to 0x18109000 region at post-set_active (clean window, n=2). However, **BAR0 access to OOB Router may become unreliable at later timings** (t+60s or post-T276-poll when fw starts servicing other cores). For option B fire design, a strictly early post-set_active write window is required — no later than T301's t+0 marker (~1 second after set_active release).

**Residual uncertainty:** Whether the t+60s wedge is caused by:
- (a) The OOB Router agent itself entering a bad state (fw has accessed it, disabled something, etc.)
- (b) BAR0 window-write becoming unreliable due to fw activity
- (c) Substrate coincidence (low base-rate wedge happening to fire at sample 2 timing)

T302a (re-fire T301 unchanged) would discriminate; the result is not yet available.

---

## Synthesis: Option B Feasibility Assessment

**Option B** = host-side wake-event injection via setting OOB Router pending bits.

### IF all gates were open (hypothetical):
- Host write `0x18109100 = 0x9` (set bits 0+3) at post-set_active
- Bits 0/3 are enabled in oobselouta30 and upstream aggregator
- Bits route to ARM CR4 via SiliconBackplane
- ARM CR4 exception fires
- fn@0x138 → fallthrough → fn@0x115c executes
- fn@0x9936 reads 0x18109100 and returns pending=0x9
- ISR dispatch loop finds matching callbacks (RTE-CC ISR for bit 0, pciedngl_isr for bit 3)
- **WAKE FIRES**

### Reality: Open gates, closed gates, unknown gates

**BLOCKED (known-closed):** None explicitly proven closed; however, lack of evidence is different from openness.

**KNOWN-OPEN:**
- Gate 5: fn@0x115c reachability (unconditional fallthrough entry)

**UNKNOWN (must assume closed until proven open):**
- Gate 1: Write semantics of 0x18109100 (RW1S vs W1C vs RO?)
- Gate 2: oobselouta30 / oobselouta74 enable bits (enabled or disabled by default?)
- Gate 3: ARM CR4 interrupt controller mask (IRQ vector enabled?)
- Gate 4: Upstream SiliconBackplane aggregation path (wired or broken?)

**PARTIALLY-OPEN:**
- Gate 6: BAR0 accessibility (open at post-set_active, time-sensitive)

### Conclusion for Option B

**Option B is NOT FIRE-ABLE without resolving gates 1, 3, 4.**

Specifically:
1. **Gate 1 (write semantics)** must be resolved to know whether host write even affects the register
2. **Gate 3 (ARM IRQ enable)** must be verified; if globally disabled, exception never fires
3. **Gate 4 (upstream path)** must be confirmed wired; if OOB-to-ARM path doesn't exist, pending bit has no effect

**Gate 2 and 6 are lower priority:**
- Gate 2: If oobselouta30 bits are disabled, a prior initialization-step would be needed (may be resolvable with static analysis)
- Gate 6: Post-set_active window is narrow but available (n=2 confirmed clean); not a blocker for a one-shot fire at correct timing

### Recommended Next Steps (Static Analysis)

1. **Gate 1 (write semantics):** Search Linux kernel source for any write operations to BCMA_OOB_SEL_OUT_A30 or equivalent registers in ARM-targeted drivers (brcmfmac). If zero writes, register is read-only. **STATIC ONLY.**

2. **Gate 3 (ARM IRQ enable):** Disassemble the blob's exception-vector setup code and search for CPSIE (enable interrupts), GIC initialization, or MSI enable patterns. Look for any per-vector mask configuration in the reset-vector chain. **STATIC ONLY.**

3. **Gate 4 (upstream path):** Cross-reference Linux kernel bcma / brcmsmac source for ARM-CR4 OOB-to-exception mapping comments or code. If documentation exists, cite it. If not, a hardware fire probing the actual exception vector would be needed. **STATIC POSSIBLE; full proof requires hardware.**

4. **Gate 2 (oobselouta30 enable):** If gate 3 & 4 are open, revisit whether hndrte_add_isr in offload mode writes an additional enable-mask that was missed. Specifically, search for writes to any register at class-0-wrapper (chipcommon-wrap) offsets 0x100–0x110 or 0x500–0x510 during ISR registration. **STATIC ONLY.**

---

## Files and References

- **KEY_FINDINGS rows 125, 144, 161, 162, 163:** Summaries of prior work on OOB Router, ISR allocation, live runtime
- **phase6/t303d_oob_reader_schedule.md:** fn@0x115c as on-dispatch-only ISR dispatcher (gate 5)
- **phase6/t298_static_pass_findings.md, phase5/logs/test.298.journalctl.txt:** T298 ISR-list enumeration (bits 0/3 allocation, gate 2)
- **phase5/logs/test.300.journalctl.txt, test.301.journalctl.txt:** T300/T301 BAR0 OOB Router accessibility (gate 6)
- **phase6/t299_t306_offload_runtime.md:** Static reach analysis confirming no interrupt-enable code in live path (gate 3)
- **Linux kernel: scratch/asahi-linux/drivers/bcma/driver_mips.c:57–87:** OOBSELOUTA30 read-only pattern (gate 1, 2)
- **Linux kernel: scratch/asahi-linux/include/linux/bcma/bcma_regs.h:28:** `BCMA_OOB_SEL_OUT_A30 = 0x0100` definition

---

## Conclusion

The gate stack between OOB Router pending-bit write and fn@0x115c execution contains **at least 3 unknown gates** (write semantics, ARM IRQ enable, upstream SiliconBackplane path) that must be proven open before option B is fire-able. The known-open gate (fn@0x115c reachability) is necessary but not sufficient. **Option B should be labeled NEEDS-MORE-WORK / BLOCKED until gates 1, 3, 4 are statically resolved or a hardware fire specifically targets them.**

**If forced to choose today without further work:**
- **Option B is NOT recommended** — too many unknowns (gates 1, 3, 4)
- **Recommended alternative:** Continue static analysis on the live offload runtime to identify the actual wake trigger — it may be D11 MAC events, PMU GPIO, or a different OOB line, not OOB bits 0/3. See RESUME_NOTES and PLAN.md for next phase suggestions.

---

**Co-authored by:** Static gate-stack analysis framework + evidence synthesis from prior phase 6 work (T298–T303, rows 125/144/161–163).

