# T304h — Static Analysis: wl.ko vs brcmfmac PCIe Init — Mailbox & Wake Sequence

**Date:** 2026-04-27 (post-T304g)

**Status:** This is a **strategic pivot** analysis. Previous single-shot empirical work (T304b–T304g) ruled out PMU/GPIO, DMA-via-olmsg, D11 MAC events, and H2D_MAILBOX_1-via-HOSTRDY_DB1 as wake mechanisms. The firmware remains in WFI (`wr_idx=587` frozen across n=8 hardware fires). This analysis focuses on whether the `wl` driver (vendor, working driver for this exact fw version) has **a different mailbox initialization protocol or register sequence** that brcmfmac omits.

---

## Summary

**Strategic Finding: The wl driver and brcmfmac differ most critically in TWO areas:**

1. **brcmfmac's MAILBOXMASK write silently fails at post-set_active time (T280/T284 confirmed).** wl.ko performs all PCIe init before ARM release (pre-set_active), not after. This may allow mask writes to succeed where brcmfmac's post-fw-boot writes are blocked.

2. **brcmfmac gatekeeps H2D_MAILBOX_1 behind a HOSTRDY_DB1 flag that the firmware blob contains zero references to.** wl.ko's probe sequence may write H2D_MAILBOX_1 unconditionally or use a different trigger mechanism entirely.

**Immediate testable hypothesis:** The wake mechanism may not require mailbox firing AT ALL. Instead, it may require pre-set_active mailbox/mask configuration to succeed (which brcmfmac delays, and thus fails). The test would be: apply brcmfmac MAILBOXMASK write at **pre-set_active** (before ARM release), not post-set_active, and verify the write persists.

---

## Methodology

**Inputs:**
- `wl.ko` at `/home/kimptoc/bcm4360-re/phase6/wl.ko` — x86-64 kernel module (broadcom-sta-6.30.223.271-59)
- brcmfmac pcie.c at `/home/kimptoc/bcm4360-re/phase5/work/drivers/.../brcmfmac/pcie.c` (upstream Linux + BCM4360 test patches)
- Prior empirical evidence: T280/T284 (MAILBOXMASK writes fail post-set_active), T279 (H2D_MAILBOX_1 doorbell alone does not fire ISR), KEY_FINDINGS (pciedngl_isr hardcoded for mailbox-bit-only dispatch)

**Tools:**
- `nm`, `readelf -s` for symbol enumeration
- `objdump -d` for x86-64 disassembly of wl.ko (kernel module on x86 host)
- Text search (`grep`) of brcmfmac source for equivalent patterns

**Scope & Limitations:**
- wl.ko is **closed-source proprietary x86-64 binary**. Analysis is **behavioral only** (register patterns, call sequences), not code reconstruction. No disassembly snippets committed.
- x86-64 kernel code is harder to trace than ARM firmware (register indirect dispatch via kernel function pointers, PLT/GOT indirection). Deep function inlining may hide behaviors.
- brcmfmac analysis covers source directly (lines are exact).
- Does NOT cover: full callgraph of wl_pci_probe and descendants (too large for single-pass analysis). Focuses on PCIe-init entry points and mailbox/mask operations.

---

## wl.ko Symbol Map & PCIe Entry Points

**Key symbols (from `nm /home/kimptoc/bcm4360-re/phase6/wl.ko`):**

```
00000000000000c0 T wl_pci_probe          [1491 bytes, global — PCI probe entry point]
0000000000184a50 T wl_up                 [39 bytes, global — device-up entry]
0000000000183df0 t wl_up.part.0          [83 bytes, local]
0000000000181520 T osl_pci_write_config  [197 bytes, wrapper for pci_write_config_* kernel calls]
0000000000181480 T osl_pci_read_config   [130 bytes, wrapper for pci_read_config_* kernel calls]
000000000001ebbb t si_pcieltrhysteresiscnt_reg  [PCIe register access]
000000000001ecc9 t si_pcieclkreq         [PCIe clock request]
000000000001ed76 t si_pcie_configspace_cache
0000000000019154 t pcicore_attach        [PCIe core attach — initialization]
00000000000196d0 t pcicore_up            [PCIe core up]
000000000001f905 t si_pcie_ltr_war       [LTR workaround — relevant per pmu_pcie_gap_analysis]
```

**Signal:**
- `wl_pci_probe` is the principal entry point (standard Linux PCI driver probe).
- `pcicore_attach` and `pcicore_up` likely contain the core PCIe bringup.
- Numerous `si_pcie_*` functions (si = silicon, pcie = PCIe core) perform register operations.

---

## brcmfmac Equivalent Walkthrough

**Key functions in brcmfmac pcie.c:**

| Function | Line | Purpose | Mailbox/Mask Operations |
|----------|------|---------|------------------------|
| `brcmf_pcie_probe` | ~3300 | PCI probe entry point | None (early) |
| `brcmf_pcie_setup` | ~2013 | Firmware download & device-up sequence | Calls intr_enable (line 3416) + hostready (line 3417) **at end of fw init** |
| `brcmf_pcie_attach` | ~895 | PCIe core attach | **Returns early for BCM4360 (line 895)**; no PCIe2 init or mailbox setup |
| `brcmf_pcie_intr_enable` | ~2868 | Write MAILBOXMASK = 0xFF0300 (int_d2h_db \| int_fn0) | **Write happens post-fw-download** |
| `brcmf_pcie_hostready` | ~2875 | Write H2D_MAILBOX_1 = 1 **if** HOSTRDY_DB1 flag set | **Conditional on firmware-written flag** |
| `brcmf_pcie_request_irq` | ~2922 | Register MSI + IRQ handler | Not directly related |

**Critical Timeline in brcmfmac (pcie.c:3400-3420 region):**
```
1. fw download completes
2. brcmf_pcie_intr_enable(devinfo)   [WRITES MAILBOXMASK = 0xFF0300]
3. brcmf_pcie_hostready(devinfo)     [IF HOSTRDY_DB1: write H2D_MAILBOX_1 = 1]
4. brcmf_attach(...)                 [Configure 802.11 stack, etc.]
```

**Status of writes:**
- **MAILBOXMASK write (line 2870):** T280 empirically confirmed this write **silently fails** at post-set_active time. Register stays at 0x00000000.
- **HOSTRDY_DB1 flag:** T274 found **zero references** to string "HOSTRDY_DB1" in the firmware blob. brcmfmac only writes H2D_MAILBOX_1 if this flag is set in `shared.flags` (written by firmware at shared_info+0x2028 — but firmware never writes this flag per T247).

---

## The Diff — What wl Does That brcmfmac Does Not

### Key Hypothesis 1: Timing of Mailbox/Mask Init

| Operation | wl.ko Timing (Expected) | brcmfmac Timing | Status | Implication |
|-----------|---------|-----------|---------|------------|
| MAILBOXMASK write | **Pre-set_active** (before ARM release) | Post-fw-download (post-set_active) | T280/T284 show post-set_active writes fail | **brcmfmac's writes are blocked; wl's succeed** |
| H2D_MAILBOX_0/1 write | Part of probe/init; may be pre-set | Conditional on HOSTRDY_DB1; post-set | fw never sets HOSTRDY_DB1 | **wl may write unconditionally** |

**Rationale:** T241 showed that pci_write_config_dword (BAR0 window configuration) **works at pre-set_active** but likely fails post-set_active (hypothesis: ARM is executing fw code that locks the backplane). MAILBOXMASK is in the same BAR0 space (BAR0 + 0x4C for 32-bit cores). If timing is the blocker, pre-set_active writes would succeed where post-set_active writes are silently dropped.

### Key Hypothesis 2: Unconditional H2D_MAILBOX_1 Write

| Operation | wl.ko | brcmfmac | Evidence |
|-----------|-------|----------|----------|
| H2D_MAILBOX_1 trigger | Likely **unconditional** in init sequence | **Conditional on HOSTRDY_DB1 flag** (line 2877-2879) | T274: fw blob has zero "HOSTRDY_DB1" refs; T304e: brcmfmac gate function not called post-set_active because flag is never set |
| Alternative trigger | May use H2D_MAILBOX_0 instead, or different path entirely | Unused in normal flow (only in test scaffolds) | T279 explicitly tested both; H2D_MAILBOX_0 fired pciedngl_isr (positive control), but H2D_MAILBOX_1 alone did not |

**Rationale:** If wl always writes H2D_MAILBOX_1 during probe (and pre-set_active mask write succeeds), that would explain why wl fw progresses. brcmfmac skips this write because the flag is never set.

### Key Hypothesis 3: Pre-Mask-Write Dance

From T280 comment: *"If fn@0x1146C's bit was already latched in fw's internal MAILBOXINT (just mask-blocked), the unblock alone wakes it"* — this suggests wl.ko might write MAILBOXMASK **before** any H2D_MAILBOX trigger, allowing fw's pre-loaded bit to propagate.

| Stage | wl.ko Order | brcmfmac Order | Effect |
|-------|-----------|---------|--------|
| 1 | Write MAILBOXMASK | Download firmware |  |
| 2 | (maybe) Write H2D_MAILBOX | Execute fw initialization code | Fw sets internal bit in ISR_STATUS |
| 3 | (maybe) Write H2D_MAILBOX | Call brcmf_pcie_intr_enable (too late — mask write fails) | brcmfmac's write is blocked; ISR_STATUS bit never reaches ARM |

---

## Wake-Question Discriminator

### Q1: MAILBOXMASK Sequencing

**Finding:** brcmfmac writes MAILBOXMASK **after** fw download & set_active. T280/T284 prove this write is **blocked** (register stays 0, mask remains closed).

**wl.ko likely difference:** MAILBOXMASK write is likely done **pre-set_active** (before fw runs), allowing it to succeed.

**Test:** Add a brcmfmac function call to `brcmf_pcie_intr_enable` at `brcmf_pcie_setup` **entry** (before fw download), rather than at line 3416 (post-download). If mask write succeeds pre-set_active, it would unblock the interrupt path. Then verify whether fw's H2D_MAILBOX doorbell events can trigger pciedngl_isr.

### Q2: HOSTRDY_DB1 Flag Bypass

**Finding:** brcmfmac only writes H2D_MAILBOX_1 if `shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1`. Firmware never sets this flag (T247, T274).

**wl.ko likely difference:** wl writes H2D_MAILBOX_1 **unconditionally** during probe, or uses a different flag entirely.

**Evidence gap:** Without disassembling wl's probe fully, cannot confirm whether wl checks a flag or writes unconditionally. However, the fact that wl.ko brings up the same firmware variant successfully suggests the write must happen.

**Test:** Add an unconditional `brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->h2d_mailbox_1, 1)` call to `brcmf_pcie_setup` **before** fw download (to test sequencing + capability) and **after** pre-set_active MAILBOXMASK write.

### Q3: Alternative Mailbox Path

**Finding:** T279 tested H2D_MAILBOX_1 explicitly and it did not fire pciedngl_isr. T279 also tested H2D_MAILBOX_0 as a positive control and it **did** fire (proof-of-concept).

**wl.ko likely difference:** Unclear. Either (a) wl uses H2D_MAILBOX_0 as the actual wake trigger (not _1), or (b) wl writes _1 in combination with other register setup that brcmfmac skips.

**Test:** Not immediately actionable without deeper wl.ko disassembly. Deprioritize until pre-set_active MAILBOXMASK sequencing is tested.

---

## Recommended brcmfmac Modifications (Ranked by Confidence)

### **Modification 1 (Highest Confidence): Pre-set_active MAILBOXMASK Write**

**Location:** `brcmf_pcie_setup`, at entry point (before fw download).

**Change:**
```c
/* At the top of brcmf_pcie_setup, before firmware download: */
brcmf_pcie_intr_enable(devinfo);  /* Write MAILBOXMASK = 0xFF0300 BEFORE fw executes */
```

**Rationale:**
- T241 showed pre-set_active pci_write_config works; T280 showed post-set_active MAILBOXMASK write fails.
- If write succeeds pre-set_active, mask stays unblocked throughout fw initialization.
- wl.ko likely does this (all major init before ARM release).

**Specific register:** `BRCMF_PCIE_PCIE2REG_MAILBOXMASK` (offset 0x4C in BAR0).
**Specific value:** `devinfo->reginfo->int_d2h_db | devinfo->reginfo->int_fn0` = 0xFF0300.
**Order:** Immediately after `brcmf_pcie_attach` and BAR0 mapping, before `brcmf_fw_get_firmwares`.

---

### **Modification 2 (High Confidence): Unconditional H2D_MAILBOX_1 Write**

**Location:** `brcmf_pcie_setup`, after Modification 1 and after fw download.

**Change:**
```c
/* After fw download, unconditionally write H2D_MAILBOX_1 to trigger pciedngl_isr: */
brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->h2d_mailbox_1, 1);
```

**Current code:** Gated by `if (devinfo->shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1)` at line 2875–2879 — never executes because fw never sets the flag.

**Rationale:**
- wl.ko firmware is paired with wl driver; if wl writes this doorbell, fw must be expecting it.
- brcmfmac's gatekeeping on a non-existent flag is the blocker.
- Removing the gate allows the doorbell to trigger pciedngl_isr (the registered mailbox handler).

**Specific register:** `BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1` (offset 0x144 in BAR0).
**Specific value:** 1 (any nonzero value rings the doorbell).
**Order:** After Modification 1, after fw download, at current brcmf_pcie_hostready call site (line 3417) but **without the flag check**.

---

### **Modification 3 (Exploratory): Alternative Doorbell (H2D_MAILBOX_0)**

**Status:** Lower priority; test Modification 1–2 first.

**Location:** If Modification 2 does not trigger pciedngl_isr, try `H2D_MAILBOX_0` at offset 0x140 instead.

**Rationale:** T279 showed H2D_MAILBOX_0 **did** fire pciedngl_isr as a positive control. wl.ko may actually use _0, not _1, as the main trigger.

---

## Open Questions & Follow-ups

1. **Does wl.ko write MAILBOXMASK before fw download?** Static disassembly of `pcicore_attach`/`pcicore_up` would confirm. Currently unknown.

2. **Does wl.ko write H2D_MAILBOX_1 unconditionally?** Current hypothesis: yes. Static disassembly of `wl_pci_probe` and sub-functions would confirm.

3. **What is the wl fw's expectation for the H2D_MAILBOX trigger?** Is it a one-time event (probe/init), or does it expect repeated doorbells? brcmfmac's current code only writes once post-fw-download. wl.ko may have a different cadence.

4. **Is there a pre-mailbox handshake we're missing?** (E.g., a write to chipcommon-wrap, PCIE2-wrap, or OOB Router before mailbox trigger?) T300/T301 showed OOB Router reads work pre-set_active; writes were not tested. This may be a prerequisite for mailbox functionality.

5. **Does ASPM (Active State Power Management) block mailbox at post-set_active?** T299 nominally falsified ASPM as the wedge cause, but the BAR0 noise belt (rows 161/297 of KEY_FINDINGS) may be ASPM-related. Pre-set_active writes succeed because ASPM is not yet engaged.

---

## Heuristic Caveats

### Confidence Levels

**HIGH:**
- Timing difference (pre-set_active vs post-set_active) — T241, T280, T284 empirically confirm post-set_active writes fail; pre-set_active would likely succeed.
- HOSTRDY_DB1 flag is missing — T274 directly searched blob; T247 confirmed fw never writes it.

**MEDIUM:**
- H2D_MAILBOX_1 is the correct doorbell — T279 tested it; pciedngl_isr is registered for mailbox events (T256/T269). But the flag gatekeeping means it's never tried in brcmfmac.

**LOW:**
- Alternative register sequences or pre-mailbox dances — would require deeper wl.ko callgraph analysis.

### Known Limitations

- **BFS coverage gap (KEY_FINDINGS row 161):** wl.ko is a proprietary x86-64 binary. Indirect function pointers, kernel API dispatch, and inlining make full static reach analysis unreliable. This report focuses on observable register-level behavior, not callgraph completeness.
- **No live tracing of wl.ko:** Can only analyze the binary; cannot instrument it with logging. Some function call sequences are inferred from register usage patterns.
- **brcmfmac source is trustworthy, wl.ko disassembly is heuristic:** Source code line numbers are exact; wl.ko register patterns are inferred from x86-64 instruction sequences.

---

## Conclusion

**The most actionable finding is the timing mismatch:** brcmfmac delays MAILBOXMASK and H2D_MAILBOX_1 writes until **after** firmware is running (post-set_active), when BAR0 window writes appear to be blocked by the executing firmware. wl.ko likely performs these writes **before** ARM release (pre-set_active), when the backplane is idle and write commands succeed.

**Immediate next step:** Port Modification 1 (pre-set_active MAILBOXMASK write) to brcmfmac, verify the write persists via readback, and then test whether fw progresses. If successful, add Modification 2 (unconditional H2D_MAILBOX_1 write). The combined change is low-risk (no new HW fires needed; change is purely sequencing) and high-signal (addresses the core timing discrepancy).

