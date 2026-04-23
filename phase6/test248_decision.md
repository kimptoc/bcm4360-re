# Test.248 — parallel/offload decision

Written 2026-04-23 12:2x BST after POST-TEST.247 null result.
Captures the options presented to the user on whether any of the
T248 / T249 / Phase-6 work can be parallelized or moved to a
different host.

## Must be this host, serially

Anything that touches the BCM4360 chip over PCIe. One crash +
SMC-reset cycle per test, one host, no way around it without a
second machine carrying the same chip.

- T248 wide-TCM scan
- T249 signature sweep (if T248 nulls)
- Phase-6 IMEM read at BAR2[0xef000]
- Any other register-probe or write-verify test

## Can run in parallel, offline, no hardware

Static analysis that *prepares* whichever Phase-6 branch wins
(W1/W2/W3 per PRE-TEST.248 matrix). These are pure-reading tasks:
no chip access, no risk of wedging the host, no serialization
against the test ladder. Can be dispatched as parallel agents while
coding / waiting on test.248.

1. **Upstream source dig.** Trace `brcmf_pcie_init_share` →
   `brcmf_pcie_bus_console_init` → shared-struct field population
   in upstream brcmfmac. Extract the complete struct layout: every
   offset, which fw writes (host reads) vs which host writes
   (fw reads), plus the console-buffer publication convention. Gives
   T249 / Phase 6 a concrete target list to sample instead of
   guessing offsets.
2. **NVRAM audit.** Compare our `brcmfmac4360-pcie.txt` against
   Apple-extracted NVRAM content (if available) or against the
   published BCM4360 NVRAM reference. Flag any params fw might be
   stalled on — bad checksum, missing required entries, values
   outside valid range.
3. **HND RTE console / BCM shared-struct magic research.** Find
   documentation or source evidence for what signature/version
   BCM4360 fw actually expects at its shared struct. Is upstream's
   `BRCMF_PCIE_MIN_SHARED_VERSION = 5` load-bearing for BCM4360 or
   was it an arbitrary starting point? Any alternate magic words
   known (e.g. `HNDR`, `BRCM`, version-bounded magics)?
4. **pcie.c hack audit.** Compare our modified `pcie.c` against
   upstream. Hundreds of lines of test-instrumentation have been
   added; any inadvertent regression in the core flow (download
   ordering, NVRAM write, FORCEHT timing, select_core sequencing)
   could itself be the cause of the stall — separate from the
   hypotheses we've been testing.

## Parallel on a different host

Only helpful if a second BCM4360-equipped machine is available.
Otherwise no — the chip is the serialization bottleneck. The
parallel work in the section above happens on *this* host too
(just in a different agent / process), not a second box.

## Recommended next move

Before (or alongside) writing T248 code, dispatch 1–4 as parallel
Claude agents. Output goes into `phase6/` as separate notes files
so:

- Whichever T248 matrix row fires (W1/W2/W3), the follow-up already
  has a target list prepared.
- If T248 shows a changing offset outside our observation window
  (W2), the upstream source dig tells us what that offset *means*
  semantically (vs just "an address that changed").
- If T248 nulls (W1), the NVRAM + signature research tells us
  whether T249 signature sweep is the right next move or whether a
  different fw prerequisite (NVRAM-driven) is what's actually
  gating.

Risk of parallel dispatch: low. Each agent reads sources locally
(upstream brcmfmac, our repo, wl.ko disassembly already in phase6/).
No shared writes, no hardware access, no wedge risk.
