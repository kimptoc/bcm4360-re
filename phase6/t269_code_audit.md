# Task: T269-CODE — Host-side scaffold failure audit (T258–T269)

## Release task

Audit the host-side kernel-driver code path in our patched `brcmfmac/pcie.c` against upstream, correlated with observed wedge timing in T258–T269 journal logs, to answer:

1. **What host-side ordering or dependency is our scaffold violating that causes the host to wedge when we try to enable IRQ delivery?**
2. **Is there a specific register write / function call upstream performs BEFORE `brcmf_pcie_request_irq` that we've been skipping?** (e.g., ring-buffer init, scratch buffer init, shared-struct publish)
3. **Does the timing of our scaffold relative to firmware boot / `brcmf_chip_set_active` return matter?** (T268 crashed BEFORE set_active; T267 crashed at t+120s probe burst — suggests scaffold-placement sensitivity)
4. **Is the host wedge actually an AER escalation from a bad PCIe transaction, a kernel-deadlock, or a CPU-side hang?** Evidence differs per test.

Goal: identify the specific host-side fix (ordering change, missing call, or bug in our scaffold) that would let us enable IRQ delivery without wedging the host. This informs the design of a T270 scaffold that reliably wakes fw from WFI.

This is **pure static analysis + log re-reading**. No hardware, no kernel module loads, no test fires. Fully parallelizable with other work.

## Sources

- **Our patched driver**: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` — primary audit target.
- **Upstream kernel `brcmfmac/pcie.c`** for diff reference — in git history (earlier phase5 commits before any BCM4360 patches) or pull from upstream kernel tree. Key upstream functions to compare:
  - `brcmf_pcie_probe` — overall probe sequence
  - `brcmf_pcie_setup` — post-firmware-download setup (ring init, scratch init, request_irq, intr_enable, hostready)
  - `brcmf_pcie_request_irq` — MSI enable + threaded IRQ registration
  - `brcmf_pcie_intr_enable` — MAILBOXMASK write
  - `brcmf_pcie_hostready` — H2D_MAILBOX_1 write
  - `brcmf_pcie_handle_mb_data` — the mb-data ISR path
  - `brcmf_pcie_init_ringbuffers`, `brcmf_pcie_init_scratchbuffers` — data structures that must exist before IRQs fire.
- **Wedge journal logs**:
  - `phase5/logs/test.258.journalctl.txt` — safe variant (MAILBOXMASK + hostready, no request_irq); wedged during 5s idle sleep.
  - `phase5/logs/test.259.journalctl.txt` — MSI enable + safe handler + MAILBOXMASK + hostready; wedged just after post-wait probe (irq_count=0 at time of wedge).
  - `phase5/logs/test.26[0-7].journalctl.txt` — scaffold iterations (T260 mask-only, T261 doorbell-only, T262 scaffold-alone, T263 absolute-time watchdog, T264 bare msleep, T265/T266 msleep duration scan, T267 no-msleep variant).
  - `phase5/logs/test.268.journalctl.txt` — early-scaffold pivot; crashed before scaffold could run.
  - `phase5/logs/test.269.journalctl.txt` — early-exit ladder variant; crashed at t+45s dwell, scaffold never ran.
- **Historical RESUME notes**:
  - `RESUME_NOTES.md` (current) — PRE/POST pairs for T268, BASELINE-POSTCYCLE, T269 + older T265/T266/T267.
  - `RESUME_NOTES_HISTORY.md` — POST-TEST.258, .259 blocks ~line 21518 and 21317 have detailed wedge analysis.
- **Upstream reference** (useful, not required): pull a recent kernel's `drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` for side-by-side comparison. Do not commit it; only reference.

## Environment

- Local grep/diff on text files. No special tooling required.
- `grep`, `diff`, `git log -p` for history, `git blame` on specific lines if the modification history matters.

## Steps

1. **Build a test → symptom → last-marker table.**
   - For each of T258..T269: extract insmod time, scaffold-entry marker (if any), last marker before wedge, wedge time, elapsed, recovery path (watchdog / SMC reset). Produce a single table.
   - Look for patterns: is the wedge elapsed-time-based (fixed ~N sec after insmod), activity-based (cumulative MMIO), or state-based (specific marker always last)?

2. **Diff our scaffold setup vs upstream `brcmf_pcie_setup` init order.**
   - Extract upstream's post-`chip_set_active` call sequence:
     ```
     init_ringbuffers → init_scratchbuffers → publish_shared_info → request_irq → intr_enable → hostready
     ```
     (Verify this against actual upstream code; this is my recollection.)
   - Identify which of these our test harness skips (known: at least `request_irq`, `intr_enable`, `hostready` per T257).
   - For each skipped call, determine if it's load-bearing for the ones that come after. Specifically: does fw write to ringbuffer descriptors immediately after wake? If yes, skipping `init_ringbuffers` means fw writes to unmapped/garbage memory when it wakes.

3. **Verify the T258/T259/T260 scaffolds actually executed the writes they claim.**
   - T258 claimed "MAILBOXMASK + hostready written" — is there a readback after each write in the journal? If not, we only know the write was issued, not that it landed.
   - Check if the register offsets we wrote match upstream's exact symbols (e.g., is `PCIE_MAILBOX_INT_MASK` at the offset we assume?).

4. **Host wedge modality check (for each wedge):**
   - Was the journal `-k -b -1` capture clean (wedge was fw-side or a simple hang)?
   - Are there any AER, MCE, NMI, or panic traces in the journal? Grep each journal for `AER`, `MCE`, `NMI`, `Oops`, `BUG`, `panic`, `hung task`.
   - If no trace: likely a spinlock deadlock or CPU-held-in-ISR condition.

5. **Check for specific known-dangerous patterns:**
   - Writing `0xFFFFFFFF` or a pattern containing stale bits to MAILBOXMASK (upstream writes a bit-set specific to this chip).
   - Calling `request_threaded_irq` without a corresponding `devm_add_action` cleanup / matching `free_irq` on error path.
   - Writing to H2D_MAILBOX_1 before shared-info struct is published (fw handler might deref a NULL/garbage pointer).
   - `brcmf_pcie_bus_console_read` being called from a different context than upstream expects (consumer vs producer race).

6. **Correlate wedge times against "scaffold executed" vs "scaffold never ran".**
   - T268 / T269 crashed before scaffold — the wedge is NOT scaffold-caused in those tests. It's in the probe path ahead of scaffold. That's a separate host-side issue (possibly driver drift / hardware drift) that also needs isolation.
   - T258, T259 crashed AFTER scaffold — these are scaffold-caused. Focus host-fix audit here.

7. **Identify the minimal-change candidate.**
   - Produce ≥1 specific, testable hypothesis: "the host wedges in T259 because we skip init_ringbuffers, so when fw wakes and writes to a ring descriptor it TLPs a bad address, kernel panics".
   - Write the specific code change(s) needed to test the hypothesis — without implementing them in this task.

## Expected deliverables

- `phase5/analysis/T269_code_audit.md` — main analysis doc. Structure:
  - Summary table (test → symptom → last marker → elapsed → recovery).
  - Upstream init-order vs our-harness init-order diff.
  - Per-wedge modality check (AER / no-AER / deadlock / etc.).
  - Specific code-change candidates ranked by probability of being the fix.
  - Clean-room note (host-side audit so clean-room not directly load-bearing, but still describe behavior not paste).
- Optionally: a focused script `phase5/analysis/t269_wedge_table.py` that auto-builds the summary table from journals (if >5 logs and manual extraction feels fragile).
- Updated `RESUME_NOTES.md` entry when the analysis produces a concrete host-side fix design.

## Out of scope

- Any hardware test fire, module build, or code change to pcie.c.
- Designing a new T270 scaffold based on findings — that is a separate task after this audit + the fw-blob analysis both land.
- Deep dive into `brcmf_pcie_handle_mb_data` internals (defer to T269-FW if it becomes relevant).

## Success criteria

- Summary table covering T258–T269 wedges.
- Identified upstream init-order steps our harness skips, ranked by load-bearingness.
- At least one minimal-change candidate for host-side fix, with test plan.
- Wedge modality classified per test (AER / deadlock / ISR-storm / other).
