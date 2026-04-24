# Task: T269-FW — Firmware-blob disassembly of `pciedngl_isr` and wake handshake

## Release task

Disassemble the firmware's PCIe ISR callback node (`pciedngl_isr`, identified in T256 as scheduler callback node[0]) and the surrounding wake-from-WFI code path, to answer:

1. **Which bits in which mailbox register does the fw read to decide a callback should fire?** (i.e., what the scheduler's `tst r5, flag` check needs)
2. **What handshake or ACK does the fw perform with the host after being woken** (writes to which mailbox? reads which host-ready flag? clears which bits?)
3. **Does the fw expect a specific initialization order** (e.g., does it poll for a host-ready flag before accepting IRQ-driven wakes)?
4. **Are there side effects of writing MAILBOXMASK or H2D_MAILBOX_1 too early** (e.g., does the fw clear a latched bit that makes subsequent wakes fail)?

Goal: produce an informed design for a safer host-side wake scaffold that does not wedge the host (T258–T269 have all wedged in different ways).

This is **pure static analysis**. No hardware, no kernel module loads, no test fires. Fully parallelizable with other work.

## Sources

- **Blob**: `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
  - Clean-room rule applies — describe behavior in plain language; no verbatim instruction sequences in committed docs beyond short illustrative snippets.
- **Prior analysis**:
  - `phase5/analysis/T251_blob_analysis.md` — saved-state region, ring buffer, buf_ptr structure
  - `phase5/analysis/T253_wlc_phy_attach.md` — wlc_phy_attach function boundaries, si_info struct inference
  - `phase5/analysis/T254_phy_subtree.md` — scheduler at 0x115C, WFI at 0x1C1E, dispatcher subtree
  - `phase5/analysis/t256_decode.py` — located `pciedngl_isr` as scheduler callback node[0] via the `[0x629A4]` list head
- **Existing helper scripts** in `phase5/analysis/t254_*.py`, `t255_*.py`, `t256_*.py` (capstone-based, THUMB mode)
- **T257 context**: `RESUME_NOTES_HISTORY.md` ~line 21386 — our harness bypasses `brcmf_pcie_request_irq`, `brcmf_pcie_intr_enable`, `brcmf_pcie_hostready`; fw waits in WFI forever for an IRQ the host never generates.
- **Upstream brcmfmac reference** for mailbox register semantics:
  - `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` (our patched copy; look for `BRCMF_PCIE_MB_INT_*`, `brcmf_pcie_handle_mb_data`, `H2D_MAILBOX_1`, `MAILBOXMASK`)

## Environment

- Python 3 + capstone: use `PYTHONPATH=/nix/store/3piq71wzj6ilmxsls0hiv9crvk86jb28-python3.13-capstone-5.0.7/lib/python3.13/site-packages python3 <script>` (avoid `nix-shell` — it hangs on startup).
- Capstone mode: `capstone.CS_MODE_THUMB`.
- Blob is loaded at base 0 for disassembly; runtime fw maps this at physical address ~0 (ARM reset vector region) and TCM mirror at BAR2+tail.

## Steps

1. **Locate `pciedngl_isr` entry point.**
   - Scheduler callback node[0] was identified via list head `[0x629A4]` → node at `0x9627c` → node's function-pointer field (fn-ptr at +4, arg at +8 per T254 §7).
   - Use `t256_decode.py` as template: read the node fields, cross-reference the fn-ptr value with a function prologue scan to confirm entry address.
   - Deliverable sub-artifact: confirmed entry address + disassembly of the first ~60 instructions.

2. **Identify the flag value the scheduler tests for node[0].**
   - Scheduler loop at 0x115C walks callback list with `tst r5, flag` where `r5 = bl 0x9936` (return value). The node's flag field is at a known offset.
   - Read node[0]'s flag value from the blob (static initializer in BSS region / data segment), decode the bitmask.

3. **Disassemble `0x9936` (the event-mask source).**
   - This function returns the value that scheduler `tst`s against each callback's flag. Typically this reads PCIE_INTSTATUS or MAILBOXINT via the backplane.
   - Identify which hardware register it reads and what bits are populated from where.

4. **Trace `pciedngl_isr` body.**
   - Identify calls to mailbox-register access helpers (look for known register-access patterns: MOVW/MOVT of 0x18005xxx addresses, or helper function calls with mailbox-offset arguments).
   - Identify any `str` writes to host-shared TCM regions (console ring at 0x9CCxx, shared-info structs, etc.) — these are observable from host.
   - Identify any ACK writes: clearing interrupt status bits, writing to H2D_MAILBOX registers.

5. **Check for pre-wake handshake expectations.**
   - Look for references to a host-ready flag (0x629Bx area from T254, or shared-info fields). If the fw scheduler polls/reads a flag before it will service IRQs, the ordering matters.
   - Search the blob for the literal 0x00FF0300 (our MAILBOXMASK value) and 0x1 (hostready value) to see where fw writes/reads these.

6. **Check for timeout or watchdog behavior.**
   - Does fw have a `watch-dog` timer that crashes / panics if host doesn't respond within N units? Search for `bl` targets that look like `panic` / `reboot` handlers.

7. **Write up findings.**
   - Function-boundary table, key register reads/writes, bit semantics, handshake sequence, implications for host-side scaffold design.
   - Clean-room style (behavior described; no large reconstructed code).

## Expected deliverables

- `phase5/analysis/T269_pciedngl_isr.md` — main analysis doc, covering all seven steps above. Similar structure to `T254_phy_subtree.md`.
- `phase5/analysis/t269_*.py` — capstone helper scripts used (keep small and focused, one script per question).
- Updated `RESUME_NOTES.md` entry when the analysis produces a concrete scaffold-design implication.
- Optional: if the analysis surfaces a specific `brcmfmac` register write that looks load-bearing, add a one-liner in pcie.c marked `BCM4360 T269-scaffold-design-note` — do NOT code the scaffold in this task.

## Out of scope

- Any hardware test fire, module build, or code change to pcie.c probe path.
- Coding a new T270 scaffold based on findings — that is a separate task after this analysis lands and is reviewed.
- Deep disassembly of unrelated scheduler callbacks (nodes[1..N]); only node[0] (`pciedngl_isr`) unless direct evidence implicates others.

## Success criteria

- Mailbox register + bit(s) that wake `pciedngl_isr` identified by name (matched to upstream `BRCMF_PCIE_MB_INT_*` symbols).
- Handshake sequence documented in plain language.
- At least one concrete recommendation for the host-side scaffold ordering or a specific register-write to add/remove.
