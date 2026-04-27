# T304c: PMU and GPIO Subsystem Reconnaissance — Wake Surface Discovery

**Date:** 2026-04-27  
**Task:** Identify if PMU or GPIO subsystems offer host-driveable interrupt surfaces distinct from OOB Router (now W1C/RO-confirmed closed by T304).  
**Methodology:** Static code analysis + upstream register documentation + prior-work cross-reference.  
**Hardware fires:** zero (read-only reconnaissance).

---

## Summary

**Verdict:** The PMU subsystem IS reachable and has interrupt machinery; however, no direct evidence of host-driveable PMU interrupt triggers in the current firmware design. GPIO subsystem is hardware-present but software-dormant in the offload blob. The actual wake source for firmware is NOT via PCIE2 MAILBOXMASK (confirmed dead T289) and NOT via OOB Router pending register (confirmed W1C/RO by T304). The firmware reads pending events at **chipcommon+0x168**, which does NOT correspond to any upstream-documented chipcommon hardware register (0x168 lies in a reserved gap in the struct chipcregs definition). Most likely: 0x168 is an offset into a **D11 MAC core software structure** (wlc_hw or similar), not a hardware register at all. This reframes the wake question from "what hardware surface sets bits at chipcommon+0x168?" to "what firmware-internal event structure shadows at this offset, and what wakes that structure?"

**Implication for option 1 (host-driveable wake):** Neither PMU nor GPIO offer the needed trigger path in the current configuration. The chipcommon+0x168 wake source is firmware-internal and not directly host-accessible via BAR0 register writes. Alternative directions (option 2: DMA-via-olmsg, option 3: passive re-read) remain open per RESUME_NOTES.

---

## 1. PMU Subsystem: Register Layout and Host Reachability

### 1.1 PMU Base Address and Register Block

- **PMU base:** ChipCommon+0x600 (per upstream BCMA headers)
- **Host reach:** Full — BAR0 windowing to ChipCommon core (0x18000000) places all PMU registers at ChipCommon+0x6xx within host-accessible range
- **BCM4360 PMU revision:** 17 (recorded in RESUME_NOTES POST-TEST.300, RESUME_NOTES POST-TEST.304)

**PMU Register Map (confirmed upstream `bcma_driver_chipcommon.h:324-368`)**

| Offset | Name | Purpose | Host-writable? |
|---|---|---|---|
| 0x600 | PMU_CTL | Control register (NOILPONW, HTREQEN, ALPREQEN, etc.) | Yes (R/W) |
| 0x604 | PMU_CAP | PMU capabilities (read-only) | Read-only |
| 0x608 | PMU_STAT | PMU status (HT/ALP available, interrupt pending) | Read-only |
| 0x60C | PMU_RES_STAT | Resource status | Read-only |
| 0x610 | PMU_RES_PEND | Resource pending | Read-only |
| 0x618 | PMU_MINRES_MSK | Min resource mask | Yes (R/W) |
| 0x61C | PMU_MAXRES_MSK | Max resource mask | Yes (R/W) |
| 0x620-0x628 | PMU_RES_TABSEL/DEPMSK/UPDNTM | Resource table selectors | Yes (per firmware interaction) |
| 0x634 | PMU_WATCHDOG | Watchdog timer | Yes (R/W) |
| 0x640-0x648 | PMU_RES_REQTS/REQT/REQM | Resource request timers and masks | Yes (R/W) |
| 0x650/0x654 | CHIPCTL_ADDR/DATA | Indirect chipcontrol register access | Yes (RMW) |
| 0x660/0x664 | PLLCTL_ADDR/DATA | Indirect PLL/regcontrol register access | Yes (RMW) |

### 1.2 PMU Interrupt Path (NOT found in firmware)

**Expected interrupt architecture:** PMU has an IRQ line to ARM CR4; PMU_STAT bit 6 (BCMA_CC_PMU_STAT_INTPEND) signals pending PMU interrupts. Upstream drivers read `PMU_STAT & 0x40` to detect pending PMU events.

**Firmware evidence:** T298 static ISR enumeration (3 registered ISRs in live offload blob):
1. `pciedngl_isr` — allocated OOB bit 3 (confirmed runtime)
2. `fn@0xB04` thunk — chipcommon-class ISR, allocated OOB bit from `oobselouta30` (registered but never observed firing in T256-T306)
3. `wlc_isr` — FullMAC path, NOT registered in offload mode

**Missing:** No PMU-specific ISR found in static enumeration of `hndrte_add_isr` call sites (T289). The `fn@0xB04` thunk is labeled a "chipcommon-class RTE handler" but its actual callback function (`fn@0xABC`) is not yet disassembled for classification.

### 1.3 Host-driven PMU interrupt capability

**Direct host writes to PMU_WATCHDOG or PMU_RES_REQT?** Technically possible (registers are R/W), but:
- Firmware never touches PCIE2 MMIO from its own code (T289 exhaustive scan: zero PCIE2 register literals in 442KB blob)
- Firmware reads only chipcommon-base literal (0x18000000, single hit at file offset 0x328)
- No evidence of firmware monitoring PMU_STAT for watchdog or resource-request events

**Classification:** PMU is **host-reachable but NOT driveable as a wake source** under current firmware design. Writing PMU_WATCHDOG or PMU_RES_REQT from host would set bits, but firmware ISR registration and event dispatch don't appear to monitor those registers.

---

## 2. GPIO Subsystem: Hardware Presence and Host Reach

### 2.1 GPIO Hardware Present

- **GPIO base:** ChipCommon+0x60 (per upstream headers)
- **GPIO register set:** (upstream bcma_driver_chipcommon.h:192-206)
  - 0x60: GPIOIN (input state, read-only)
  - 0x64: GPIOOUT (output value, R/W)
  - 0x68: GPIOOUTEN (output enable, R/W)
  - 0x70: GPIOPOL (polarity, R/W)
  - 0x74: GPIOIRQ (interrupt mask, R/W)
  - 0x58: GPIOPULLUP, 0x5C: GPIOPULLDOWN (corerev >= 20)

### 2.2 GPIO Interrupt Routing

**Expected model:** GPIO interrupts route to ChipCommon, which can assert OOB bits to ARM via ChipCommon backplane wrapper (`oobselouta30` at wrap+0x100). This is the SAME OOB routing path used by `pciedngl_isr` and the mysterious `fn@0xB04`.

**Firmware evidence:** GPIO is never mentioned in the firmware blob (phase6 grep search: zero references to GPIO register names or GPIO-related strings). No GPIO-related ISR found in static enumeration.

**Host reach:** GPIO registers are fully accessible via BAR0 windowing to ChipCommon. Host can read GPIOIN, write GPIOOUT/GPIOOUTEN/GPIOIRQ.

### 2.3 Host-driven GPIO as wake surface

**Problem:** For a GPIO to trigger an interrupt to ARM, firmware must have registered a GPIO ISR. No evidence of this in offload blob.

**Classification:** GPIO is **hardware-present but software-dormant**. Host can toggle GPIO output pins, but no registered firmware handler will receive an interrupt from GPIO events under current firmware.

---

## 3. The Actual Wake Source: chipcommon+0x168 (NOT a hardware register)

### 3.1 What firmware reads

Per T289 findings (§4.5, confirmed T281/T287b):
- Firmware ISR entry path reads pending events at `[[sched_ctx_ptr+0x358]+0x100]`
- Runtime observation (T287b): sched_ctx+0x88 points to ChipCommon base (0x18000000)
- **Inferred address:** ChipCommon+0x168

### 3.2 Is 0x168 a hardware register?

**Answer: NO.** Offset 0x168 does NOT appear in upstream struct chipcregs (defined in phase3/work chipcommon.h). The structure layout shows:
- ECI registers end at 0x180 (line 142: `u32 eci_eventmaskmi;`)
- PAD[3] at 0x17C-0x188
- SROM registers begin at 0x190 (line 146: `u32 sromcontrol;`)

**0x168 falls in the PAD/reserved region**, suggesting it is NOT a documented hardware register in upstream BCMA. This strongly suggests **0x168 is an offset into a D11 MAC software structure** (wlc_hw, wlc_info, or similar), not a chipcommon hardware register.

### 3.3 Evidence from firmware structure writes

T297g classification of `[reg, +0x168]` write sites (5 str.w/strh.w locations in firmware):
- Site 0x15640: writes -1 (0xFFFFFFFF) to `[r4, 0x168]` — likely "clear all pending events"
- Site 0x15EDE: writes 0x4000 to `[r5, 0x168]` — bit 14 set
- Site 0x23108: writes `r0` (computed mask from GPIO/MAC state) to `[r5, 0x168]` — event dispatch
- Sites 0x2BDC0, 0x23402, 0x23420: various strh.w/str.w patterns

**Observation:** Multiple firmware functions access +0x168 with different base pointers (`r4`, `r5`, etc.) in different contexts, suggesting +0x168 is an **offset within a frequently-allocated structure** (likely D11 MAC hardware block context, allocated per-interface or globally).

### 3.4 PMU/GPIO/GCI as candidates

T289 speculated three candidates for what sets bits at chipcommon+0x168:
1. **PMU interrupt status** — but 0x168 is not PMU_STAT (0x608)
2. **GCI (Generic Core Interface)** — present in BCM4360 (CAP_EXT bit 0x4), but no GCI register layout found in upstream headers for rev 43
3. **D11 MAC internal event structure** — most likely, given multiple sw-context accesses

---

## 4. Cross-Reference with Firmware ISR Registration

### 4.1 The three registered ISRs (T298)

| ISR | Class | OOB bit allocated | Status | Callback |
|---|---|---|---|---|
| pciedngl_isr | PCIE2 (implicit) | 3 (confirmed runtime T256) | **LIVE** | hndrte-level event dispatch |
| fn@0xB04 | ChipCommon (0x800) | allocated from oobselouta30 (TCM shadow readable) | Registered but behavior unknown | fn@0xABC (thunk) |
| wlc_isr | D11 (0x812) | Would be allocated | **DEAD** in offload mode | FullMAC chain unreachable |

### 4.2 PMU as wake source: structural gap

If firmware were to wake on PMU events, it would need:
1. A PMU ISR handler registered at hndrte_add_isr — **not found**
2. Or, PMU events routed to chipcommon wrapper → OOB Router to an existing ISR slot — **no evidence**

The `fn@0xB04` chipcommon-class ISR is tantalizing (it's registered early in RTE init, before wl_probe), but:
- Its callback `fn@0xABC` has not been analyzed for what it does with pending events
- No chipcommon interrupt-status register is cleared/read in any observed log trace (T287c, T290a, T298-T304)

---

## 5. Host-Reach Assessment: Discriminator Summary

| Wake Surface | Type | Host-reachable | Host-driveable | Status |
|---|---|---|---|---|
| OOB Router pending (0x18109100) | HW register (W1C/RO) | Yes (BAR0 direct) | **NO (W1C-confirmed T304)** | GATE-1 CLOSED |
| PCIE2 MAILBOXMASK (0x1800304C) | HW register (R/W nominally) | Yes (BAR0 direct) | **NO (writes silently drop T241/T284)** | GATE-0 CLOSED |
| PMU control/status (0x18000600+) | HW register (R/W) | Yes (BAR0 direct) | **NO direct ISR evidence** | DORMANT |
| GPIO registers (0x18000060+) | HW register (R/W) | Yes (BAR0 direct) | **NO direct ISR evidence** | DORMANT |
| Chipcommon+0x168 | **UNKNOWN (not HW register)** | Unknown | **N/A** | LIKELY SW STRUCT |

---

## 6. Follow-Up Work and Unanswered Questions

### 6.1 Highest-priority questions (static, zero-fire)

1. **What is the D11 structure at +0x168?** Static code analysis: find wlc_hw definition in wl.ko; identify field at +0x168. This may reveal what event structure firmware polls.

2. **What sets bits in the D11+0x168 structure?** Follow firmware paths that write to +0x168 to determine what conditions trigger wake. Examples: D11 TBTT interrupt? PHY state change? Watchdog timer?

3. **Is the `fn@0xB04` chipcommon ISR actually active?** T298 detected it in static ISR list, but T256-T304 never observed its OOB bit firing. Either:
   - It's registered but never triggered (PMU/GCI events don't fire during WFI)
   - Its callback (`fn@0xABC`) is a no-op or error handler
   - The static registration analysis missed a conditional gate

### 6.2 Lowest-cost experimental question

**If PMU wake were possible:** Host writes a value to PMU_WATCHDOG or PMU_RES_REQT (e.g., 0x00010000), then firmware remains in WFI. Does chipcommon+0x168 or the OOB Router bits change? **This would confirm whether PMU events propagate to firmware-visible interrupt sources.**

Estimated cost: single cold-cycle fire (similar to T300/T304 footprint: post-set_active timing, BAR0 write + readback).

### 6.3 Longer-term static work (phase 7)

- Reverse D11 MAC interrupt masking + event delivery path
- Trace which D11 MAC events fire before wl_probe returns
- Reconcile firmware's actual wake moment (T256 observed at t+90s) with expected D11 event timeline

---

## 7. Conclusion: PMU/GPIO as Wake Surfaces — UNABLE TO OPEN

**PMU:** Hardware-present, host-accessible, but no firmware ISR handler found. PMU interrupt path (if it works) is not connected to the offload firmware.

**GPIO:** Hardware-present, host-accessible, but no firmware ISR handler found. Would require GPIO pin configuration (polarity, enable) AND registered ISR callback, both absent.

**Chipcommon+0x168 (actual wake site):** NOT a hardware register. Firmware polls an internal software event structure at this offset. Host cannot directly set bits in this structure via BAR0 register writes. The actual wake sources are firmware-internal (likely D11 MAC events), not host-driveable via PMU/GPIO registers.

**Implication:** Option 1 (host-driveable wake via PMU/GPIO) remains CLOSED. Prior discovery that MAILBOXMASK and OOB Router are not the wake gates is confirmed. Next direction: either unlock firmware ISR registration paths (option 1 variant: convince firmware to register a PMU/GPIO ISR), or pursue option 2 (DMA-via-olmsg) or option 3 (fw-internal passive events).

---

## References

- **Phase 1:** Core enumeration, ChipCommon at 0x18000000 (core 0), rev 43, PMU present
- **Phase 5/6 PMU Analysis:** `wl_pmu_res_init_analysis.md` (PMU registers, resource masks), `pmu_pcie_gap_analysis_final.md` (PMU initialization path)
- **T289:** ISR enumeration, PCIE2 MMIO zero-references, wake source = chipcommon+0x168 hypothesis
- **T298:** 3 ISRs registered (pciedngl_isr, fn@0xB04, wlc_isr), TCM-readable allocation bits
- **T304:** OOB Router 0x18109100 gate-1 verdict — W1C/RO, host CANNOT set bits
- **Upstream BCMA:** bcma_driver_chipcommon.h (register offsets), chipcommon.h struct chipcregs (register layout, 0x168 absent)
- **Firmware blob:** 442233 B, md5 812705b3ff0f81f0ef067f6a42ba7b46 (consistent across phase 5/6 work)

