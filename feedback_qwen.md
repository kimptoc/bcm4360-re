# Review of PRE-TEST.188 (RESUME_NOTES.md)

## Substantive concerns

### 1. CR4 fault-register prediction overclaims (prediction #4)

> "If CR4 fault registers are non-zero: direct confirmation of exception
> handler. Fault address + type will identify the failing instruction."

`brcmf_pcie_probe_armcr4_state` (pcie.c:714) reads only three registers
via the BCMA CR4 wrapper high window:

- `0x408` IOCTL
- `0x40c` IOSTATUS
- `0x800` RESET_CTL

These are BCMA wrapper registers — they are **not** ARM architectural
fault state (DFSR / IFSR / DFAR / IFAR). IOSTATUS may expose *some*
wrapper-level fault/status bits but cannot yield "fault address + type"
at a granularity that identifies the failing instruction. The prediction
sets an expectation the probe cannot meet.

**Fix options:**

- Narrow the prediction: "If IOSTATUS shows non-zero fault/error bits,
  wrapper-level fault state is visible; follow up with dedicated
  ARM-architectural fault-register probe."
- Or add a dedicated fault-register probe (access to DFSR/IFSR/DFAR/IFAR
  via CR4 co-processor/system register path — requires additional
  wrapper-window work and research into how Broadcom exposes these on
  the BCM4360 CR4 tile).

## 2. Fine-grain window labels misleading (biggest issue)

Code ordering in `brcmf_pcie_download_fw_nvram`:

```
set_active
  20 ms, 100 ms probes
  dwell 500 / 1500 / 3000 ms                 ← coarse grid (pcie.c:2269..2360)
  tier-1 "0-50 ms"    (10 × 5 ms = 50 ms)    ← actually 3000–3050 ms
  tier-2 "50-1550 ms" (30 × 50 ms = 1500 ms) ← actually 3050–4550 ms
```

The PRE-TEST.188 hypothesis states fine-grain sampling *"catches
transient firmware activity missed by the coarse 500/1500/3000 ms grid"*.

But the fine-grain loops run **after** the 3 s dwell, not between its
samples. The actual windows are therefore ~3000–3050 ms and ~3050–4550 ms
relative to `brcmf_chip_set_active`. To catch a 0–50 ms exception
(the stated motivation — capturing the first-fault window), tier-1 must
fire **before** the 500 ms dwell sample.

As written, the probe answers **"is the ARM still stuck at T+4.5 s?"**
rather than **"when did it get stuck?"**.

This is both a code-design issue and a hypothesis-wording issue. They
are coupled — pick one interpretation and make them agree.

**Fix options:**

- **(a) Reorder:** move tier-1 to *before* the dwell grid; keep only
  the 3000 ms dwell sample. Simpler; loses 500/1500 ms data, but those
  samples have been UNCHANGED across tests 184–187 so the information
  cost is near zero.
- **(b) Relabel:** keep the order, rename tiers to "post-dwell-0–50 ms"
  / "post-dwell-50–1550 ms", and narrow the hypothesis claim to
  "persistence check" rather than "transient detection". Still
  diagnostic for the persistent-loop case.

## Minor

- **Stale date stamp**: header says `2026-04-20`; if the test is run
  today, bump it.
- **Build-status note missing** per CLAUDE.md pre-test checklist — the
  PRE entry does not explicitly state "rebuilt clean". We did rebuild
  clean (frame-size warning resolved, only pre-existing unused-function
  warning remains), but it should be documented in the entry.
- **Probe D scope**: samples TCM[0..fw->size], not IMEM. Fine as
  stated — the PRE entry correctly scopes probe D to "download-path
  corruption". Just worth noting the reset-vector region at IMEM
  0xef000 remains untouched by probe D (pre-existing limitation
  carried over from test.187).

## Verified accurate

- `pre_resetintr` / `resetintr_offset` residue genuinely removed —
  `grep -n "pre_resetintr\|resetintr_offset" pcie.c` returns no matches.
- 256 samples × ~1734 B step across 442 KB firmware matches the
  "~1.7 KB" claim in the PRE entry.
- Risk assessment (read-only BAR2 + `-ENODEV` return +
  `pci_clear_master` always executed) matches the code.

## Recommendation (author's preference)

Fix **#2 option (a)** first — move tier-1 before the dwell grid. It's
the highest-signal change. Then:

1. Soften prediction #4 to match what IOSTATUS can actually show (or
   add a real fault-register probe if that's the intent).
2. Bump the date stamp.
3. Add a one-line "module rebuilt clean (only pre-existing
   brcmf_pcie_write_ram32 unused warning remains)" to the PRE entry.
4. Run the test.

## TODO — decided: option 2a

User selected **option 2(a)**: reorder so tier-1 runs before the dwell
grid, and drop the 500/1500 ms dwell samples (keep 3000 ms only).
Information cost is near zero because those samples have been
UNCHANGED across tests 184–187.

Checklist:

1. **pcie.c**: move tier-1 (10 × 5 ms) before the dwell grid; remove
   500 ms and 1500 ms entries from `dwell_labels_ms` /
   `dwell_increments_ms`, leaving only 3000 ms.
2. **pcie.c**: decide whether tier-2 stays in the post-dwell position
   or also moves earlier. Current recommendation: keep tier-2
   immediately after tier-1 (so fine-grain = tier-1 [0–50 ms] +
   tier-2 [50–1550 ms]), and push the 3000 ms dwell sample to after
   tier-2 for a late-persistence check.
3. **RESUME_NOTES.md PRE-TEST.188**: update the ordering description
   to match the new code flow.
4. **RESUME_NOTES.md PRE-TEST.188**: soften prediction #4 to
   "IOSTATUS shows non-zero fault/error bits" or equivalent — do not
   claim fault-address/type granularity.
5. **RESUME_NOTES.md PRE-TEST.188**: bump date stamp to the actual
   run date.
6. **RESUME_NOTES.md PRE-TEST.188**: add build-status line (module
   rebuilt clean; only pre-existing
   `brcmf_pcie_write_ram32 defined but not used` warning remains).
7. **test-staged-reset.sh**: update `WAIT_SECS` comment if the new
   total in-module time changes meaningfully (tier-1 50 ms + tier-2
   1500 ms + dwell 3000 ms ≈ 4.55 s, basically unchanged).
8. Rebuild module with
   `make -C $KDIR M=phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules`
   and confirm clean build (frame-size warning should stay resolved).
9. Commit + push + sync per CLAUDE.md.
10. PCIe pre-test check (`lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`)
    and verify no dirty state.
11. Run `sudo ./phase5/work/test-staged-reset.sh 0`.
12. Capture `journalctl -k` / dmesg output to `phase5/logs/test.188.journalctl.txt`.
13. Write POST-TEST.188 entry in RESUME_NOTES.md with observations
    matched against hypothesis.
14. Commit + push + sync.
