# Test.248+ Off-Chip Work

Purpose: tasks that can be done on another machine because they only
require source code, notes, local artifacts, or compile-time checking.

## Scope rule

This file is for any step that does not require the BCM4360 card to be
present. It includes reading, diffing, editing, building, documenting,
and preparing targeted experiments for later validation on the BCM host.

## Track 1: `pcie.c` audit against upstream

Goal: reduce the risk that accumulated BCM4360-only instrumentation has
changed core behavior and is contaminating negative results.

### 1.1 Establish the diff surface

1. Diff local `phase5/work/.../pcie.c` against the chosen upstream
   baseline.
2. Separate changes into:
   - pure logging
   - test-only gating via module params
   - behavior-changing edits in the normal attach/download path
   - BCM4360-specific permanent bring-up changes
3. Produce a short inventory of the behavior-changing edits first.

### 1.2 Audit the high-risk flow points

Check these in order:
1. `brcmf_pcie_attach`
2. firmware download path
3. NVRAM write path
4. pre-`pci_set_master` and post-`pci_set_master` sequencing
5. FORCEHT write placement
6. `brcmf_chip_set_active` call site and timing
7. dwell-ladder hooks and any code that still runs when test params are
   off
8. cleanup / module removal path

### 1.3 Look specifically for accidental regressions

1. Any code that runs for BCM4360 even when the intended test flag is
   off.
2. Any early `return` that now skips upstream logic.
3. Any `select_core` or register write that moved earlier/later than
   upstream.
4. Any NVRAM or random-seed write that overlaps with a probe region.
5. Any residual instrumentation that alters timing enough to affect the
   wedge window.

### 1.4 Produce an audit note

Write a short note under `phase6/` that lists:
1. changes that are clearly safe scaffolding
2. changes that are behavior-changing but intended
3. changes that are suspicious and should be reverted, gated, or tested
   in isolation on the BCM host

## Track 2: Upstream shared-struct and console-layout dig

Goal: stop guessing about the pcie shared struct and identify exactly
what firmware and host are expected to exchange.

### 2.1 Trace the upstream code path

1. Start from `brcmf_pcie_init_share`.
2. Follow into `brcmf_pcie_bus_console_init`.
3. Identify every field populated in the shared struct.
4. Record:
   - offset
   - width
   - host-writes vs firmware-writes expectation
   - when in the sequence the field becomes valid

### 2.2 Identify the minimal viable struct

1. Distinguish mandatory fields from fields that are only needed after
   firmware is already running normally.
2. Identify whether “version at offset 0, rest zero” is plausible or
   obviously insufficient.
3. Determine whether the console-buffer pointer publication convention
   gives a better observation target than the current T247 region.

### 2.3 Produce a field map note

Create a note in `phase6/` containing:
1. struct layout table
2. minimum fields required for first contact
3. candidate offsets worth probing in T249 or later

## Track 3: Signature/version research for Test.249

Goal: prepare a disciplined set of candidate shared-struct signatures so
the next hardware runs are not guesswork.

### 3.1 Check upstream constants and version guards

1. Find where `BRCMF_PCIE_MIN_SHARED_VERSION` and any max/current shared
   version are defined.
2. Determine whether version `5` is merely the minimum accepted by host
   code or specifically what firmware is expected to publish/consume.
3. Identify any chip-specific version handling.

### 3.2 Search local reverse-engineering notes

1. Review `phase6/NOTES.md`, `wl_pmu_res_init_analysis.md`, and related
   Phase 6 notes for:
   - shared-struct magic words
   - console signatures
   - HND RTE markers
   - any constants that look like version bounds
2. Record only clean-room-safe semantic findings.

### 3.3 Produce the Test.249 candidate set

1. Rank candidates as:
   - high-confidence: `5`, `6`, `7`
   - medium-confidence: any alternate magic supported by source
   - low-confidence: speculative signatures that should wait
2. For each candidate, state why it deserves a hardware run.

## Track 4: NVRAM audit

Goal: determine whether firmware could be blocked on malformed or
incomplete NVRAM rather than PMU/shared-struct issues.

### 4.1 Collect the current input

1. Locate the active `brcmfmac4360-pcie.txt` used by this project.
2. Normalize it into key/value form.
3. Record checksum / trailer conventions if applicable.

### 4.2 Compare against references

1. Compare against any locally available Apple-extracted or known
   BCM4360 NVRAM references.
2. Flag:
   - missing required keys
   - obviously wrong board or revision identifiers
   - malformed values
   - suspicious clock/power-related params

### 4.3 Produce an audit note

Write a note under `phase6/` containing:
1. keys that look correct
2. keys that are uncertain
3. concrete edits that would justify a later hardware-backed A/B test

## Track 5: Phase 6 PMU/PCIe notes cleanup

Goal: stop stale analysis from sending implementation effort in the
wrong direction.

### 5.1 Reconcile docs against current code

1. Update or annotate `phase6/pmu_pcie_gap_analysis_final.md`.
2. Explicitly note that current `pcie.c` already performs the
   `test.194` BCM4360 attach-time `SBMBX` and `PMCR_REFUP` writes.
3. Re-rank remaining untried PCIe2 and PMU items after removing already
   attempted work from the “missing” list.

### 5.2 Clarify the real open questions

Document separately:
1. what has been tried in code
2. what has been observed on hardware
3. what still lacks implementation
4. what still lacks validation

## Track 6: Candidate code work that can be authored elsewhere

These can be implemented on another machine, then shipped to the BCM
host for validation:

### 6.1 T248/T249 scaffolding

1. Add the new module params.
2. Add helpers/macros for structured logging.
3. Refactor duplicated probe code into small helpers if that reduces
   risk without changing runtime behavior.

### 6.2 `pcie.c` cleanup

1. Fence test-only code more tightly behind params.
2. Remove or isolate obviously stale one-off instrumentation.
3. Simplify the hot path so hardware results are easier to interpret.

### 6.3 PMU/PCIe candidate implementation

1. Prepare attach-time PCIe2 init patches not yet tried.
2. Prepare PMU control / resource-mask helper skeletons.
3. Keep these patches small and hypothesis-specific so the BCM host can
   validate one idea at a time.

## Output expectations for off-chip contributors

Any off-chip work should hand back:
- a short note under `phase6/` when the output is analysis
- a patch or branch when the output is code
- explicit assumptions
- exact follow-up hardware check needed on the BCM host
