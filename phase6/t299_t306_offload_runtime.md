# T299–T306: live offload-mode runtime distinguished from FullMAC dead code

**Goal.** Reconcile static-disassembly findings about the wake gate
(KEY_FINDINGS rows 158–160) with the observed runtime behaviour: firmware
boots, reaches a stable WFI idle, but no probed wake event ever fires.

**Inputs.**

- `phase6/t299*.py` and `phase6/t300_d11_intmask_writers.py` — static traces
  from FW reset vector forward
- `phase5/work/drivers/.../brcmfmac/pcie.c` — BCM4360_T290A_CHAIN macro,
  test.96 INTMASK setup, test.288a wrap-read scaffold
- `phase5/logs/test.287c.journalctl.txt` — sched_ctx readings at t+5 / t+30
  / t+90 s
- `phase5/logs/test.290.journalctl.txt` — test.290a chain-walk results

**Conclusion.**

1. The blob contains two parallel runtimes. The live path is the HNDRTE
   dongle-side ARM-CR4 PCIe-protocol runtime. The `wl_probe → wlc_attach →
   wlc_bmac_attach → wlc_bmac_up_finish` FullMAC path exists in the blob but
   the static call graph from the reset vector does not reach it under any
   of the heuristics tried (direct `bl/blx`, `bx`-via-PC-pool literal,
   `movw/movt` pair). 311 fns reach from bootstrap; combined reach across
   bootstrap + all 8 ARM exception entries = 319 fns; none of the wifi /
   FullMAC entries are inside that set.
2. The single firmware writer of `0x48080` to a `+0x16C` offset is the
   FullMAC `fn@0x142E0` path. Static cross-checks ruled out alternative
   mask-construction paths (single `0x48080` literal at file 0x14318;
   zero `movw/movt` pairs anywhere in the blob; `wl_probe` reachable only
   via the orphaned 0x58F1C handlers table). Dead-code in offload mode.
3. Empirical test.290a chain walks (n=2, pre-set_active) returned
   `wrong-node-fn-not-wlc-isr` with random data at TCM[0x96F48+4]. The
   wlc_isr scheduler node was never populated. Consistent with conclusion 1.
4. Empirical test.287c sched_ctx readings (t+5 / t+30 / t+90 s) show
   `sched[+0x88]=0x18001000`, `+0x8c=0x18000000`, wrapper bases at
   `+0x254..+0x268`, all stable. `sched_ctx` is the silicon-info struct
   (`si_t`) populated by `si_doattach` (`fn@0x670d8`, in the live BFS).
   `flag_struct` (with the wake mask at `+0x64`, allocated by the now-dead
   `wlc_bmac_attach`) is a different struct that never gets populated in
   offload mode. Prior session likely conflated the two because both have
   D11 base at `+0x88` (BCM convention), and the prior "host observed
   `flag_struct[+0x64]=0x48080`" framing was actually a static-intent
   reading, not a live host read — `pcie.c` has no host-side read of
   `flag_struct + 0x64`.
5. The "fw freezes at WFI" is normal idle behaviour in this runtime. fw is
   alive across at least 90 s of stable sched_ctx readings; the unanswered
   question is which event the offload runtime expects to wake on, not
   whether the CPU is hung.
6. Of the wake-mechanism candidates surveyed, the only one that has not
   been empirically tested with the right register is the chipcommon /
   PCIe2 wrapper agent OOB-selector path. The already-compiled,
   never-fired `test.288a` wrap-read probe is the cheapest read-only
   discriminator for that path.

**Impact on next work.**

- Stop expanding static-disasm probes against the FullMAC chain; treat it
  as dead code in offload mode for planning purposes.
- Promote the load-bearing distinction (live HNDRTE vs dead FullMAC,
  sched_ctx vs flag_struct) into KEY_FINDINGS so future sessions don't
  retread the wake-gate / `0x48080` thread on the dead path.
- The next runtime probe should be `test.288a` plus, if substrate allows,
  re-running `test.290a` at later stages (post-set_active, post-T276-poll,
  post-T278) to push the n=2 chain-walk result above the 3-sample
  stopping rule.

**Cross-references.**

- KEY_FINDINGS rows 158, 159, 160 — superseded scope (correct as static
  analysis of the FullMAC path, but the live offload runtime does not
  execute that path).
- KEY_FINDINGS row 125 — PCIe2 mailbox doorbell empirically tested and
  silently drops; consistent with this finding.
- KEY_FINDINGS row 148 — chipcommon-wrapper write target hypothesis,
  still untested, addressed by `test.288a`.
- `phase6/t297_flag_struct_trace.md` — the prior-session static
  identification of the wake-arm path; correct in its own scope.

**Heuristic caveats not yet resolved.**

The "live BFS" used in T299 series rests on three heuristics that have
each been bitten at least once during the work:
`push-lr` as fn-start (misses tiny tail-call wrappers); `bl/blx` plus
`bx`-via-PC-pool as the only call mechanisms (misses indirect calls
through struct fields); `movw/movt` and 4-byte aligned literal-pool as
the only address-construction mechanisms (probably complete on this
blob, but not proven). The empirical test.290a / test.287c data that
backs the conclusion is independent of those heuristics, which is why
the conclusion is being promoted; the static reach numbers themselves
should be treated as upper bounds on "what's dead", not certainties.
