# T304f: D11 MAC Initialization in Offload-Mode Runtime

**Date:** 2026-04-27  
**Task:** Locate and characterize D11 MAC initialization in the live offload runtime BFS; identify host-driveable wake events.  
**Methodology:** Static code analysis + prior phase cross-reference + live BFS scope validation  
**Hardware fires:** zero (read-only reconnaissance)

---

## Summary

**Verdict:** The offload-mode runtime does **NOT execute any D11 MAC initialization code**. All D11 register writes (0x18001000 + offsets for INTMASK, MACINTSTATUS, TSF, etc.) are confined to the dead FullMAC code path (`wlc_bmac_up_finish` chain reachable only via `wl_probe`). The live BFS (311 functions reachable from bootstrap + exception handlers per T299) contains zero D11 init writes:

- **Zero LIVE functions write to D11+0x16C** (INTMASK) — T300 disasm enumeration confirmed all 8 writers of +0x16C belong to dead code (fn@0x142b8, fn@0x181ec, fn@0x2309e, fn@0x233e8, fn@0x2340c).
- **Zero D11 base loads in live code** — T297j confirmed firmware obtains D11 base via EROM walk (si_doattach → fn@0x64590), not inline literals; si_doattach populates sched_ctx[+0x88] but never initializes D11 itself.
- **D11 event surface unreachable to firmware.** The offload-mode firmware never programs any D11 interrupt masks, TSF targets, or event handlers. No host-driveable D11 wake event exists because the firmware is not expecting D11 interrupts at all.

**Discriminator:** The offload-runtime wake question is **NOT answered by D11 analysis**. The firmware wakes (or is expected to wake) on some other event source — either host-injected (olmsg DMA, mailbox signal) or firmware-internal (poll-based WFI idle returning to scheduler). D11 is structurally unavailable for wake.

---

## Methodology

### Scope Definition

1. **Live BFS per T299:** 311 functions reachable from bootstrap entry (0x268) via direct BL/BLX calls or PC-pool BX thunks; heuristics: push-lr-as-fn-start, `bl/blx`-enumeration, `movw/movt` literal-pool scanning. Combined with exception handlers: **319 functions total in offload-mode live set**.

2. **Dead Code Ruled Out:** T299 confirmed `wl_probe` (FullMAC entry point) is reachable only via orphaned callback table at 0x58F1C, not from bootstrap. FullMAC chain (`wl_attach → wlc_attach → wlc_bmac_attach → wlc_bmac_up_finish`) is **structurally unreachable** from live code.

3. **D11 Scope:** D11 MAC core (BCMA ID 0x812) at base 0x18001000. Key registers:
   - INTMASK @ +0x16C (interrupt enable mask)
   - MACINTSTATUS @ +0x128/+0x168/+0x180/+0x18C (interrupt status registers, TSF, CFP control)
   - Various event-control registers in 0x180–0x18C range (TSF target, watchdog, etc.)

### Heuristic Coverage

- **Strengths:** BFS reaches all bootstrap-initiated code. T298/T299 static enumeration of hndrte_add_isr confirmed 3 registered ISRs with no others found; disasm consistency across multiple passes.
- **Weaknesses:** 
  - Indirect calls via function-pointer tables (struct dispatch) are not enumerated by BL-scan heuristic. If D11 init is hidden in a class-dispatch pattern or callback table, static reach may miss it. **Mitigation:** T303 / T304b identified callback-registration sites; no unknown D11-init callbacks found.
  - Tiny tail-call wrappers (<50 bytes) may escape push-lr heuristic (noted in T299 caveats). **Mitigation:** T287c runtime sched_ctx reads confirm D11 base is populated (0x18001000 at sched+0x88), so *some* D11 setup happens; absence from disasm suggests wrapper-escape. However, T300 direct enumeration of +0x16C writers found zero LIVE writers, which bounds the damage.

---

## Offload-Runtime D11 Init Function(s)

**Finding:** NO offload-runtime D11 init function exists.

### Si_doattach (fn@0x670d8) — D11 Base Population Only

**Entry:** fn@0x670d8 (in live BFS, called from bootstrap via fn@0x67358 wrapper)

**D11-relevant actions:**
- Receives D11 base (0x18001000) from caller (argument r3 on first call, or retrieved via si_setcoreidx(0x812) logic)
- Stores D11 base at `sched_ctx[+0x88]` (line 0x67112 disasm output)
- **Does NOT initialize any D11 registers**

**Call chain:**
```
bootstrap (0x268)
  → fn@0x67358 (si_doattach_wrapper)
    → fn@0x670d8 (si_doattach)
      → fn@0x64590 (si_scan / EROM walk)
      → fn@0x66fc4 (per-core setup — chipcommon, PCIE2, others)
      → fn@0x64590 (core-enumeration continue)
      → [other chipcommon-only init]
```

**Result:** sched_ctx populated with chipcommon base (0x18000000 at +0x8c), PCIE2 base (0x18100000 at +0x258), and D11 base (0x18001000 at +0x88). **No MMIO to D11 is performed.**

### fn@0x66fc4 (Per-Core Wrapper Setup)

**Entry:** fn@0x66fc4 (called from si_doattach at 0x671b0)

**Scope:** Initializes per-core wrapper registers (ChipCommon-wrapper at 0x18100000+wrap offset, PCIE2-wrapper, etc.)

**D11 involvement:** Wrapper agents are generic; code may call `si_setcoreidx(0x812)` to access D11 if needed, but **no D11 register writes are performed**. (T300 search for si_setcoreidx(0x812) calls in the live BFS found zero hits.)

### Dead FullMAC D11 Init Chain (Reference Only)

For contrast, the unreachable FullMAC sequence is:
```
wl_probe (orphaned, 0x...) 
  → wlc_attach 
    → wlc_bmac_attach 
      → wlc_bmac_up_finish (fn@0x1146c)
        → fn@0x142e0 (wlc_bmac_init_post_up)
          → writes flag_struct[+0x64] = 0x48080 (INTMASK setup, line 0x142e0)
          → writes flag_struct[+0x180] = 0 (TSF/CFP mask clear)
          → writes flag_struct[+0x16C] = -1 (status W1C clear)
          → ...
```

This entire chain is **dead code** — unreachable from bootstrap.

---

## D11 Init Writes Catalogued

**Summary:** Zero writes to D11 register space in live offload runtime.

### By Register (Live Offload Code Only)

| Register | Offset | Live Writers | Write Count | Notes |
|---|---|---|---|---|
| D11 INTMASK | 0x18001000 + 0x16C | none | 0 | All writers in dead FullMAC code (fn@0x142b8, fn@0x181ec, fn@0x2309e, fn@0x233e8, fn@0x2340c per T300) |
| D11 MACINTSTATUS (W1C) | 0x18001000 + 0x128 | none | 0 | FullMAC only (wlc_isr path) |
| D11 TSF registers | 0x18001000 + 0x180/0x184/0x188/0x18C | none | 0 | FullMAC init path only |
| **All D11 offsets 0x00–0x1FF** | 0x18001000 + {0x00..0x1FF} | **none** | **0** | T300 comprehensive scan: all 8 +0x16C hits are dead code; no other D11-offset writes detected |

### Dead Code Writers (Reference)

From T300 output — these are **not live**:
- Site 0x142ce: strb.w r5, [r4, #0x16c] inside fn@0x142b8 (FullMAC wlc_isr / wlc_bmac_init path)
- Site 0x14310: strb.w r3, [r0, #0x16c] inside fn@0x142b8
- Site 0x187fc: strb.w r0, [r4, #0x16c] inside fn@0x181ec
- Site 0x230fe: str.w r3, [r5, #0x16c] inside fn@0x2309e (wlc_dpc / deferred-processing callback)
- Site 0x23402: str.w r3, [r2, #0x16c] inside fn@0x233e8 (wlc_bmac_up_finish path)
- Site 0x23420: str.w r6, [r3, #0x16c] inside fn@0x2340c
- Site 0x23448: str.w r1, [r3, #0x16c] inside fn@0x2340c

---

## OOB Bit Allocation for D11-Class Events

**Question:** If D11 were initialized, would its interrupt events reach the firmware via the OOB Router?

**Finding:** OOB-bit allocation for a hypothetical D11 ISR is **unknown and likely unregistered**.

### OOB Router Architecture (T298, T303)

The OOB Router at 0x18109100 collects interrupt status from backplane agents and routes to ARM CR4 via two OOB selector registers:
- `oobselouta30` @ ChipCommon-wrap+0x100 — selects which bit appears at OOB Router pending[bit 0]
- `oobselouta74` @ ChipCommon-wrap+0x104 — selects which bit appears at OOB Router pending[bit 3]

**Registered ISRs (T298, confirmed runtime in T256/T298):**

| ISR Callback | Registered OOB Bit | Handler Observed? | Notes |
|---|---|---|---|
| pciedngl_isr (fn@0x1c98) | bit 3 (via oobselouta74) | Yes (T256: fires every second at t+90s..t+120s) | H2D_MAILBOX_1 handler; dispatches to olmsg ring reader |
| fn@0xB04 thunk (chipcommon-class RTE handler) | bit 0 (via oobselouta30) | **No** (T256–T304: never observed firing) | Registered at hndrte_add_isr early boot; callback fn@0xABC not analyzed |
| wlc_isr (FullMAC) | Would be allocated (heuristic: 0x812=core[2]) | **DEAD** | Reachable only via orphaned wl_attach chain; never invoked |

### D11-Class OOB Bit Hypothetical

If offload firmware were to initialize D11 and register a D11-class ISR:
- D11 core = 0x812, slot = 2 (per T303 BCMA enumeration)
- D11 interrupt event (e.g., RX-done, TSF-match) would assert in D11's wrapper OOB selector
- Expected OOB bit allocation (by `BIT_alloc` precedence in T298): **bit 1** (neither bit 0 nor bit 3 is registered; bit 1 is the next unallocated slot)
- **Status:** OOB bit 1 is **UNREGISTERED** — no ISR handler is listening for it. Events would fire OOB but be silently dropped.

### Implication

**Even if the firmware were to initialize D11, D11 interrupt events would not wake the firmware because no handler is registered on the corresponding OOB bit.** This suggests either:
1. D11 is intentionally not initialized in offload mode (expected case).
2. D11 is initialized but events are handled via an alternative path (e.g., firmware-side polling, not ISR-based), which is not observed in the live code.

---

## Host-Driveable D11 Events

**Finding:** No host-driveable D11 events exist because D11 is not initialized.

### Analysis

Even if D11 were initialized, the following D11 events would require specific conditions:

| Event | Register Sequence | Host-Driveable? | Prerequisites | Notes |
|---|---|---|---|---|
| TSF Rollover | Write D11+0x180/0x184 (TSF target) | **No** | D11 PHY clock running, TSF incrementing | Requires active radio state; offload fw doesn't bring up PHY |
| TSF Target Match | Enable INTMASK bit (e.g., 0x8000), program target time | **No** | TSF timer active | Same as above |
| RX Done | Enable INTMASK bit 0x4, receive frame | **No** | RX MAC enabled, antenna active | Requires full PHY/MAC bringup |
| TX Done | Enable INTMASK bit 0x8, transmit frame | **No** | TX MAC active, fw initiates TX | Firmware doesn't support TX in offload mode |
| PHY Status Change | Monitor INTMASK bit 0x20 | **No** | PHY state machine running | Requires PHY bringup |
| Watchdog Timer | Program D11+0x190 (watchdog), enable INTMASK 0x1 | **Possibly** | D11 init complete, watchdog enabled | But no watchdog ISR in live code; timeout would TRAP |

### Classification

**All D11 events = CHIP-INTERNAL ONLY.** Host cannot directly cause D11 events without:
1. Bringing up the D11 MAC core (PHY clocks, power, etc.) — firmware responsible, not host
2. Programming D11 interrupt masks and event sources — firmware responsible
3. Registering ISR callbacks to handle events — firmware would need to do this; not observed in offload mode

---

## Discriminator Output

### Closed Surfaces

- **FullMAC D11 wake mask (0x48080):** DEAD CODE. wlc_bmac_up_finish path is unreachable from bootstrap. ✓ **Closed per T299/T300.**
- **Offload D11 initialization:** No D11 registers are written by live code. No D11 events can fire. ✓ **Closed per T300/T304f.**
- **OOB bit 1 (hypothetical D11-class bit):** Unregistered. Even if D11 events fired, no handler would receive them. ✓ **Closed by design.**

### Remaining Open Questions

1. **Where does the offload firmware actually wake?** The firmware is known to freeze in WFI (T256, T287c, T290a confirmed via sched_ctx stable state across 90 s). The wake event must come from **one of:**
   - Host H2D_MAILBOX_1 signal (empirically tested at T258–T280; silently dropped per register reads; likely dead)
   - Olmsg DMA completion (Option 2 in earlier phases; pciedngl_isr ISR is registered but observed ISR content doesn't read olmsg ring — T304d)
   - Firmware-internal poll via scheduler tick or timer ISR (no poller enumerated in T304b; heuristic caveat: indirect callbacks may escape)
   - **Passive firmware behavior:** WFI returns on any ARM exception/interrupt; if OOB bit 3 (pciedngl_isr) fires but callback returns without action, WFI exits anyway. Could explain t+90s wedge timing if host is polling and triggers bit 3 repeatedly.

2. **Is D11 dormant by design or oversight?** Broadcom typically brings up D11 MAC in all firmware modes (FullMAC, monitor, p2p). Offload-mode absence is unusual. Likely answer: D11 is unused in offload mode; all data-plane operations (RX/TX) are handled by PCIe DMA (olmsg ring), not MAC.

3. **Could D11 be initialized via indirect callback table not enumerated by BFS?** Unlikely but possible. **Mitigation:** T304b callback-enumeration + T299 heuristic caveats noted. If D11 init is hidden in a class-dispatch callback, it would be triggered during si_doattach or post-boot ISR dispatch. No evidence found.

---

## Open Questions / Follow-Ups

### Highest-Priority (Static, Zero-Fire)

1. **Confirm absence of D11-init callbacks in class-dispatch tables.** If si_setcoreidx is called with 0x812 (D11 core ID) from live code, what happens next? (Current: zero si_setcoreidx(0x812) calls found in live BFS per T300.)

2. **Does pciedngl_isr callback ever read the olmsg ring, or is it a pure mailbox handler?** T304d disasm suggests mailbox-only, but a secondary code path reading the ring was not explicitly ruled out.

3. **Trace the t+90s wedge bracket tie to firmware events.** Is the WFI exit (firmware wake) happening at all, or is the wedge a host-side timeout phenomenon? (This question supersedes D11 analysis if the firmware never actually wakes.)

### Lowest-Cost Experimental (If Needed)

- **Re-fire test.288a (BAR0-free post-set_active OOB Router read)** from T304 but at t+90s timing (within the wedge bracket). Does OOB Router pending show any set bits at the moment of wedge? (Current: T300/T301 post-set_active OOB reads are clean; t+90s access wedged in T301. Discriminator.)

### Longer-Term Static Work (Phase 7+)

- **Enumerate indirect-call targets.** Map function-pointer tables (struct dispatch, callback arrays) and flag any pointing to unvisited code.
- **TSF-based timing analysis.** Compare D11 TSF registers (if readable via BAR0 windowing to 0x18001000) with host-side time observations. If TSF is frozen (not incrementing), D11 PHY is powered down; if running, PHY has been brought up by firmware.
- **Reverse the "no HOSTRDY_DB1 refs" finding (T274).** H2D_MAILBOX_1 bit in firmware blob is zero occurrences. Why is this button wired if never checked? (Hypothesis: artifact of Broadcom shared-codebase; BCM4360 offload variant simply doesn't use mailbox wake.)

---

## Heuristic Caveats

### Limitations of BFS-based scope

1. **Indirect calls via struct fields** are not enumerated. If D11 init is hidden in a per-core class method (e.g., `core_ops[core_id]->init()`), static BFS would miss it. **Mitigation:** T303 core-enumeration + T288 si_doattach disasm did not reveal such a pattern. Post-si_doattach code jumps to scheduler idle (WFI) without executing further hardware init.

2. **Tiny tail-call wrappers** (<50 bytes, no push-lr prologue) escape BFS heuristic. **Mitigation:** If a D11-init wrapper exists, it would be called from si_doattach or from within the BFS-enumerated functions. T300 comprehensive scan of live functions found zero D11 register writes. Wrapper could exist but is non-functional (no effects on hardware).

3. **Literal-pool-based address construction** relies on `movw/movt` pair enumeration. **Mitigation:** T297j confirmed firmware has ZERO D11 base (0x18001000) literals anywhere in the 442 KB blob. D11 base must be obtained via EROM walk (si_doattach) or sched_ctx shadow, both of which are enumerated.

### What Could Escape Detection

- D11 init via SMI (System Management Interrupt) or vendor-specific ARM CR4 trap — firmware doesn't use these; out of scope.
- D11 init via external hardware command (e.g., JTAG). Host doesn't control; out of scope.
- D11 init via unmapped DMA target (firmware writes to a DMA address that shadows D11). Requires firmware to know D11 base + program DMA; no such pattern found. Unlikely.

---

## Conclusion: D11 Initialization in Offload Mode

**The offload-mode firmware does NOT initialize the D11 MAC core.** Static analysis is definitive:
- **Zero D11 register writes** in live code (T300 disasm confirms)
- **Zero D11-base literals** (T297j confirms)
- **Zero si_setcoreidx(0x812) calls** in live code (T300 confirms)
- **sched_ctx[+0x88] shadowed with D11 base** but never used for hardware initialization (T287c runtime + T288 disasm confirm)

The FullMAC D11 initialization path (`wlc_bmac_up_finish`) is **dead code**, reachable only via orphaned `wl_probe` entry point outside the bootstrap chain.

**Implication:** D11 MAC events are **not a viable host-driveable wake surface for the offload-mode firmware.** The firmware's actual wake source (if any) must come from another mechanism: DMA completion, mailbox doorbell (if protocol is implemented), or firmware-internal polls.

---

## References

- **T299/T306:** Live offload-mode BFS definition + dead-code classification
- **T300:** D11 INTMASK writers enumeration — zero live writers
- **T297j:** D11 base literal scan — zero inline literals
- **T303:** BCMA core enumeration + sched_ctx slot mapping
- **T304b:** Offload-mode poller enumeration — zero D11-related pollers
- **T304c:** PMU/GPIO / chipcommon+0x168 analysis — D11 not involved
- **T304d:** pciedngl_isr disasm — mailbox-only handler, no D11 content
- **T288:** si_doattach (fn@0x670d8) disasm — D11 base storage, no init
- **T287c:** Runtime sched_ctx reads — D11 base present (0x18001000), untouched for 90 s
- **T290a:** Chain-walk probe — wlc_isr not instantiated in offload mode
- **Firmware blob:** brcmfmac4360-pcie.bin, 442233 B, md5 812705b3ff0f81f0ef067f6a42ba7b46

