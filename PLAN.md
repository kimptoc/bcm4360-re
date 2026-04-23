# BCM4360 Reverse Engineering — Execution Plan

## Overview

The goal is to add BCM4360 support to the Linux kernel's `brcmfmac` driver by
reverse-engineering the host-to-firmware protocol used by the proprietary `wl`
driver. This follows the precedent set by the Asahi Linux project for BCM4387.

We have a live BCM4360 device on this machine with the `wl` driver loaded,
giving us the ability to trace driver behaviour, read hardware registers, and
compare against the existing `brcmfmac` codebase.

> **Scope of this document:** high-level phase status only. Per-test detail
> (what was tried, what log was captured, what it proved) lives in
> `phase5/notes/phase5_progress.md`, commit messages, and `phase5/logs/`.

> **Legal constraint:** All reverse engineering follows clean-room methodology
> — observe behavior, document in plain language, implement from that
> documentation. Do not copy disassembly structure directly into driver code.
> See README.md and CLAUDE.md for full guidelines (ref: issue #12).

## Current Status (2026-04-23, POST-TEST.246)

**Active phase:** Phase 5.2 — firmware wedges within `[t+120s, t+150s]` of
`brcmf_chip_set_active` (clean-probe bracket, per T244). Pivoting from
"single-register write-verify probes" to **shared-memory-struct pre-allocation**
as the next forward step. Full per-test detail lives in `RESUME_NOTES.md` +
`RESUME_NOTES_HISTORY.md`; this block captures the arc.

### What is proven working (as of T246)

- Full probe path to `brcmf_chip_set_active` runs cleanly: fw download
  (442 KB, 16/16 BAR2 verify), NVRAM write (228 B), Apple random_seed
  footer, FORCEHT, `pci_set_master`, `brcmf_chip_set_active` returning
  TRUE. CR4 CPUHALT transitions YES→NO; fw executes for ≥90 s
  post-set_active.
- `brcmf_pcie_select_core(PCIE2)` moves BAR0_WINDOW correctly
  (0x18000000 → 0x18003000). BAR0 writes to PCIE2 core registers land
  at pre-FORCEHT under explicit `select_core(PCIE2)` (T245/T246: FN0
  bits of MBM latch cleanly; restore 0 → readback 0 round-trips).
- BAR2 TCM writes are alive post-set_active (T245/T246 invert-and-restore
  on TCM[0x90000] PASS).
- fw reacts to the Apple random_seed footer at `[ramsize-0x1ec..ramsize-4]`:
  writing a seed shifts the wedge significantly later (T236 — fw progresses
  from "no observable signal" to "executes ≥90 s under extended ladder").

### What is ruled out (T229–T246, cumulative)

| Claim | Status | Key test(s) |
|---|---|---|
| Probe-path MMIO caused the wedge | ruled out | T229, T230 |
| `brcmf_chip_set_active` is the SOLE wedge trigger | confirmed | T230 |
| Fine-grain MMIO probes post-set_active shift timing | ruled out | T229 |
| Plain DMA-completion-waiting | ruled out | T232 (BM=OFF still wedged) |
| TCM ring-buffer logger viable across SMC reset | ruled out | T233 |
| Wedge is near t+30 s / t+45 s / t+90 s | ruled out | T238 |
| Fw writes `sharedram_addr` to TCM[ramsize-4] within 90 s | ruled out | T239 (22 polls all at NVRAM marker 0xffc70038) |
| Fw writes any of last 60 TCM bytes within 90 s | ruled out | T240 (wide-poll unchanged) |
| Post-set_active BAR0-PCIE2 writes safe | ruled out | T243/T244 (wedge-on-probe; confirmed by null-run) |
| D2H_DB bits of MBM writable at pre-FORCEHT | ruled out | T246 (stage-gated; only FN0 bits latch) |

### Current leading hypothesis

Fw starts on ARM release and executes for ≥90 s, but never reaches (or
completes) the step that populates TCM[ramsize-4] with the shared-struct
pointer (T239 — 22 polls, all show NVRAM marker 0xffc70038 unchanged).
The host→fw doorbell / MBM channel is ruled out as an early nudge:
- D2H_DB MBM bits can only be driven post-shared-init (T246 stage-gated).
- Post-set_active PCIE2 writes are a wedge hazard (T243/T244).

**Upstream protocol (per `brcmf_pcie_init_share_ram_info` at pcie.c:2106):**
fw allocates its own `pcie_shared` struct in TCM and writes that address
to `ramsize-4` on its own timeline; host polls every 10 ms up to
`BRCMF_PCIE_FW_UP_TIMEOUT` (5 s) for the slot to change. Only then does
host *read* from the fw-allocated struct (signature/version at offset 0,
ring pointers at offsets 40/44/48, console at 20, etc.). **Host never
writes the struct itself in upstream.**

So "fw blocked on shared-struct" is a symptom, not a cause. The real
question is: what is fw doing during those ≥90 s before it reaches the
allocate-and-publish step? Two testable sub-hypotheses:

- **(S1) BCM4360 fw deviates from upstream** and expects the host to
  pre-place a shared struct (or part of one) at a known TCM location
  before ARM release. Apple's in-tree `wl` driver may perform such a
  write that upstream brcmfmac does not.
- **(S2) Fw follows upstream protocol** and is stalled upstream of the
  struct-allocate step — e.g. waiting on a missing NVRAM parameter,
  missing seed data, a PMU resource, or a specific register write.
  Under S2 the shared-struct level is the wrong place to intervene.

T236's random_seed footer was a concrete instance of "Apple-specific
host write that upstream brcmfmac doesn't do and that firmware depends
on." Same shape of question repeats at the shared-struct level.

### Next direction: shared-struct probe (PRE-TEST.247 onward)

The strongest discriminator between (S1) and (S2) is: **pre-place a
plausibly-formed shared struct in TCM via BAR2 before set_active and
write its address to ramsize-4; observe whether fw reads from it and/or
the wedge timeline changes.** Results:

| Observation | Interpretation |
|---|---|
| Fw overwrites ramsize-4 with its own address (normal upstream) | Our pre-placed struct was ignored; we're still following upstream protocol; (S2) intact. |
| Fw overwrites one or more fields in our struct (e.g. ring base pointers appear) | (S1) confirmed — fw reads from a host-pre-placed struct at least for *some* fields. Iterate field-by-field. |
| Fw's wedge bracket shifts (earlier or later) | Our struct influences fw execution timing; iterate to find which field matters. |
| No change at all (ramsize-4 unchanged, struct unchanged, same [t+120s, t+150s] bracket) | Pre-placed struct does nothing. (S1) weakened; pivot to (S2)-style investigation: Phase-6 `wl`-trace study, IMEM inspection at 0xef000, or NVRAM-parameter comparison against Apple's macOS config. |

**Design (PRE-TEST.247 — advisor-reviewed 2026-04-23):**

- **Struct layout.** Fill to offset ≥ 68 (ringupd_addr) — upstream reads
  offsets 0/20/34/36/40/44/48/52/56/64/68. A tiny flag-only struct
  leaves uninitialised neighbours fw might read; a ~72-byte block with
  zeros in unused fields gives fw "version ok + nothing configured yet"
  which is a valid pre-init state. Set offset 0 to
  `BRCMF_PCIE_MIN_SHARED_VERSION` = 5 (low byte); all other words zero.
  No DMA fields populated (no scratch, no ring info, no mb data addrs)
  — if fw dereferences any of them unconditionally, we'll see the
  resulting null deref (a new data point).
- **TCM placement.** Struct base at 0x80000 inside the "dead region"
  `[0x6C000..0x9FE00]` (above fw code end 0x6bf78, below random_seed
  region 0x9FE00). T233 proved this region is untouched by fw and host
  in normal flow; T245/T246 proved BAR2 writes land there under
  invert-and-restore.
- **ramsize-4 is NOT overwritten (NVRAM trailer load-bearing).** Our own
  pcie.c test.64 note (line 3527) documents that 0xffc70038 is the
  NVRAM length/magic token the firmware's NVRAM parser reads; T63
  zeroed it and broke NVRAM discovery. Fw then *overwrites* ramsize-4
  with its own sharedram_addr on upstream-compatible firmware paths.
  Overwriting ramsize-4 before fw runs would confound NVRAM breakage
  with struct-read behaviour — unusable as a discriminator.
- **Two observables on the same run (cheap instrumentation):**
  1. Did fw write ramsize-4 (i.e. `value != 0xffc70038`)? — existing
     `poll_sharedram=1` path continues to observe this at every dwell.
     If YES, we're on S2 (fw follows upstream; struct-allocate step
     eventually reached); go read the fw-written address and feed
     `init_share_ram_info`.
  2. Did fw read and/or write our pre-placed struct at 0x80000? —
     new struct-region poll (8 u32s at [0x80000..0x80020]) at every
     dwell, comparing against baseline we wrote. If any word changes,
     (S1) evidence: fw touched our struct. If nothing changes, (S1)
     weakened: pivot to Phase-6 `wl` trace and/or IMEM inspection.
- **Gating.** New module param `bcm4360_test247_preplace_shared=1`.
- **Safety.** Struct is pure TCM memory write into a region proven
  unused. No register side-effect. NVRAM trailer at ramsize-4
  unchanged. BAR0 window state unperturbed (only BAR2 writes).
  Observables are read-only polls added to the existing
  `poll_sharedram`/`wide_poll` ladder.

**Phase 6 `wl`-trace status (pre-T247 check):** no pre-set_active
TCM-write evidence in `phase5/logs/wl-trace/` — directory contains
function_graph ftrace of `pci_enable_device()` scope only (112 lines)
plus config-space dumps, no register-level trace. So (S1) has no
concrete anchor; T247 is a discriminator test, not a forward step
blueprint yet. If (S1) yields evidence, T248+ iterates on struct
fields; if (S1) is falsified, Phase-6 trace work or IMEM probing
becomes higher priority.

**What counts as "fw activity":**
- Any fw-originated TCM write (ramsize-4, struct slot, wide-poll
  region) is the primary signal — present or absent is definitive
  on a single run.
- Wedge-bracket timing changes are secondary. n=1 variance between
  tests makes ±20 s uninformative; don't over-interpret.

### Previous "next-step ladder" (per T188) — status update
- **B. `wl` reset sequence study** — ongoing in Phase 6, parallel track;
  not blocking Phase 5.2.
- **F. OpenWrt / Asahi / SDK-leak survey** — lower priority now that
  shared-struct hypothesis is testable directly.
- **C. IMEM inspection via BAR2 at 0xef000** — deferred; cheap side probe
  if the shared-struct direction stalls.
- **A** (ARM fault regs) and **D** (UART console) — deferred.

### What's NOT proven yet in this regression-recovery tree
- Firmware-originated TCM writes (fw has been silent in TCM-observable
  space through ≥90s despite executing).
- Shared-struct handshake / fw init completion.
- Firmware reaching the old Phase-5.2 D11 PHY wait loop (T98
  TCM[0x58f08]==0 finding); gated behind the shared-struct work.

See also GitHub issues #9 (architecture) and #11 (direction review).

---

## Prior Status (2026-04-21) — historical snapshot before T189–T246 arc

**Active phase:** Phase 5.2 — probe-path stability regression recovery after
hard-crash sessions (tests 149–157).

**Completed in this recovery (2026-04-20):**
- **test.157 CRASH PINPOINTED:** per-marker `msleep(300)` discipline identified
  the MCE trigger — duplicate probe-level ARM halt caused `RESET_CTL=1` to wedge
  the ARM core's BAR0 window, and the next MMIO write triggered the MCE
  (iommu=strict likely escalates bad MMIO to a hard fault).
- **test.158 SUCCESS:** removed the duplicate ARM halt; BusMaster clear and
  ASPM disable (both config-space ops) are safe.
- **test.159 SUCCESS:** reginfo selection + pcie_bus_dev/settings/bus/msgbuf
  kzalloc + struct wiring + pci_pme_capable + dev_set_drvdata all safe.
- **test.160 SUCCESS:** brcmf_alloc (wiphy_new + cfg80211 ops) + OTP bypass +
  brcmf_pcie_prepare_fw_request all safe. Firmware name resolved:
  `brcm/brcmfmac4360-pcie` for chip BCM4360/3.
- **test.161 SUCCESS:** `brcmf_fw_get_firmwares` async path + setup callback
  entry + BCM4360 early-return stub + `brcmf_pcie_remove` BCM4360 short-circuit
  guard (skips MMIO cleanup when `state != UP`). Firmware blobs loaded:
  CODE 442233 B, NVRAM 228 B (CLM/TXCAP absent — optional). Clean rmmod.
- **test.162 SUCCESS:** Setup callback ran `brcmf_pcie_attach` (BCM4360 no-op) +
  fw-ptr extract + `kfree(fwreq)` + `brcmf_chip_get_raminfo` (fixed info
  rambase=0 ramsize=0xa0000) + `brcmf_pcie_adjust_ramsize` (fw-header parse).
  Early-return before `brcmf_pcie_download_fw_nvram`. Clean rmmod via test.161
  short-circuit. DevSta clean post-test.

**Completed since (2026-04-20 PM):**
- **test.177 SUCCESS:** 228-byte NVRAM BAR2 write at `ramsize - nvram_len`.
- **test.178 SUCCESS:** NVRAM marker readback at `ramsize - 4` = 0xffc70038.
- **test.179 SUCCESS:** 8-word TCM verify dump at `TCM[0x0..0x1c]`.
- **test.180 NEGATIVE RESULT:** `BCMA_CORE_INTERNAL_MEM` is absent on
  BCM4360, so the upstream `brcmf_pcie_exit_download_state` INTERNAL_MEM
  resetcore branch is a no-op on our chip.
- **test.181 BREAKTHROUGH:** `brcmf_chip_set_active(ci, resetintr)` runs
  cleanly. ARM CR4 IOCTL went from 0x0021 (CPUHALT=YES) to 0x0001
  (CPUHALT=NO); both 20 ms and 100 ms post-release probes confirm ARM
  continuously executing firmware; host survived the full 30 s harness
  dwell; no MCE/AER/panic; clean rmmod. First clean ARM release on BCM4360
  in this tree.
- **test.182 NEGATIVE RESULT (clean run):** ARM stays running
  (CPUHALT=NO at 20/100/500/1500/3000 ms) but TCM[0x0..0x1c] and the
  NVRAM marker at `ramsize - 4` are UNCHANGED through 3 s post-release.
  Host survives. Interpretation: firmware is stalled in an early loop
  that does not touch the image-header TCM window or the NVRAM slot.
  Next step (test.183) widens the TCM scan to the last 64 bytes + a
  handful of mid-TCM probe points and adds a BAR0 backplane read.
- **test.183 NEGATIVE RESULT (clean run):** widened scan covers 32
  TCM sample points — 8 image-header + 8 mid-TCM (0x1000..0x80000) +
  16 tail-TCM (last 64 B). All UNCHANGED across 500/1500/3000 ms.
  Host survives. New observation: the last 228 B of TCM hold our
  own NVRAM text (`vendid=0x14e4 deviceid=0x43a0 xtalfreq=40000
  aa2g=7 aa5g=7 …`) and firmware has not modified the magic/length
  word at `ramsize - 4`. Conclusion: firmware is running on ARM
  CR4 but has not reached NVRAM consumption. Likely wedged in a
  pre-NVRAM-parser wait loop (PMU/clock/host-handshake).
- **test.184 SMALL-POSITIVE RESULT:** ChipCommon backplane sampling
  (8 regs) + pmutimer diff proves firmware is executing. `pmutimer`
  ticks at ~36 kHz (≈ILP) through all dwells → PMU clocked normally.
  `pmucontrol` flipped bit 9 (0x200) exactly once between pre-release
  and 500 ms, then stayed at `0x01770381` — firmware wrote at least
  one pmucontrol bit as part of early init. All other backplane
  regs + all 32 TCM sample points UNCHANGED through 3 s. Host
  survives. Firmware is alive and performed a small amount of
  early init, then idles. Most likely wedged at an early wait
  point (host handshake, resource availability).
- **test.185 BOUNDARY RESULT:** 40-point 16-KB TCM grid + CR4 IOSTATUS
  + D11 wrapper probe. All 40 wide-TCM + 16 tail-TCM + 8 image-header
  TCM points UNCHANGED through 3 s. CR4 IOSTATUS=0x0 uninformative.
  **D11 wrapper held in reset (RESET_CTL=0x01) from cold, and firmware
  never touches it in 3 s** — IOCTL=0x07, IOSTATUS=0x00, RESET_CTL=0x01
  identical from pre-halt through dwell-3000ms. pmucontrol bit-9 flip
  and pmutimer tick rate reproduce test.184 exactly. Firmware is alive
  but stalled BEFORE D11 bring-up and BEFORE any TCM writes.
- **test.186a NULL-RESULT:** rang all three H2D channels
  (H2D_MAILBOX_0 / H2D_MAILBOX_1 / SBMBX) after the 3000ms dwell.
  `mailboxint` flipped bit 0 (0x1), but bit 0 is not in either
  `int_fn0` (0x0300) or `int_d2h_db` (0x10000..0x800000) — most likely
  our own H2D_MAILBOX_0 write latched locally, not firmware responding.
  All other signals UNCHANGED: D11 still in reset, NVRAM marker
  unchanged, 64 TCM probes UNCHANGED, no FN0/D2H bits asserted. Host
  doorbells do not unstick firmware at this stage. Three candidates
  remain: (1) fw stalled in exception/panic loop after one PMU write;
  (2) fw waiting on DMA (disambiguate via BusMaster-window test);
  (3) fw waiting on D11 wrapper (less likely).
- **test.186c NULL-RESULT (mailboxint is not W1C on BCM4360):** cleared
  `mailboxint` via write-0xffffffff and sampled after each kick. The
  clear-write instead *set* bits 0-1 (pre-kick 0x0 → post-write 0x3),
  proving these bits are RW / "write-sets" rather than W1C. All three
  subsequent kicks (H2D_MAILBOX_0, H2D_MAILBOX_1, SBMBX) produced
  delta=0 on `mailboxint` and no change to D11, TCM, NVRAM marker, or
  pmucontrol beyond the test.184 baseline. Confirms test.186a's 0x1
  was our own write latch. Doorbell theory fully ruled out for this
  stage. Remaining candidates narrow to (1) exception/panic loop and
  (2) DMA stall.
- **test.186b NULL-RESULT (BusMaster enable does not unstick firmware):**
  After the 3-s passive dwell, pci_set_master for a ~100 ms window
  while sampling at +50/+100 ms, then pci_clear_master and post-BM
  dwells at 500/2000 ms. All three MMIO guards passed (endpoint
  responsive throughout). **Firmware produced zero change during or
  after the BM-on window**: D11 still in reset, TCM unchanged, NVRAM
  marker unchanged, mailboxint=0x0 throughout, pmucontrol/pmutimer
  match test.184 baseline. Clean run, no AER/MCE, clean rmmod. DMA
  stall hypothesis effectively falsified — if firmware were waiting
  on DMA it should have made progress once BusMaster was on. Leading
  hypothesis is now **candidate 1: firmware is in an exception /
  panic loop very early** (after the one pmucontrol bit-9 write); CPU
  is running but not touching anything observable over MMIO.

**test.186b interpretation CORRECTED:** on re-reading `pcie.c`
around lines 2725-2742 / 4033-4037, test.64/65-era comments
establish that firmware needs BusMaster ON *before* `brcmf_chip_set_active`
so its first PCIe DMA succeeds; otherwise firmware enters a
crash-restart loop every ~3 s. test.186b turned BusMaster on
3 s after set_active — by then firmware was already stuck and
no amount of late BusMaster enable could rescue it. DMA-stall
was NOT falsified by 186b alone — test.186d re-ran the probe with
BusMaster on *before* set_active to resolve the ambiguity.

- **test.186d NULL RESULT (DMA-stall falsified):** `pci_set_master`
  ran immediately before `brcmf_chip_set_active`, so firmware held
  BusMaster through its full startup window. `brcmf_chip_set_active`
  returned true; ARM CR4 transitioned CPUHALT=YES → NO. **All other
  signals are byte-for-byte identical to test.186b's passive baseline:**
  D11 still in reset, 56 TCM sample points UNCHANGED through 3 s,
  NVRAM marker still `0xffc70038`, mailboxint stayed at 0 (no D2H
  or FN0 bits), CC backplane regs matched 186b (one pmucontrol
  bit-9 flip, monotonic pmutimer). Host stable, final
  `pci_clear_master` left endpoint responsive (post-BM-clear MMIO
  guard OK). **BusMaster ON vs OFF during set_active makes no
  behavioural difference — DMA-stall hypothesis is refuted.**

**Leading hypothesis now:** firmware ARM is running but in an
**exception / spin loop** that produces no observable MMIO or TCM
effect. Either it faults immediately after the jump to `resetintr`
and loops silently in an exception vector, or it polls for a
prerequisite (register write, PMU resource, specific shared-RAM word)
that `brcmf_chip_set_active` does not satisfy on this chip.

- **test.187 CLEAN RUN, probe A skipped:** `resetintr_offset = 0xb80ef000
  - 0xb8000000 = 0xef000` exceeds `ramsize = 0xa0000`, so the reset
  vector is outside TCM (likely in IMEM / CR4-internal region). Probe A
  skipped; test became essentially a re-run of 186d. All other signals
  match prior baseline. Download-path integrity not yet checked.
- **test.188 NULL RESULT (all hypotheses at this probe granularity
  exhausted):** Replaced probe A with probe D (256-point firmware-image
  integrity check) and added two-tier fine-grain CR4/D11 sampling
  (10 × 5 ms, then 30 × 50 ms, ordered *before* the dwell per
  feedback_qwen.md option 2a).
  - **Probe D:** all 256 TCM samples MATCH `fw->data`. Download path
    is clean — corruption falsified.
  - **Tier-1 (~100-150 ms, 5 ms grain):** ARM IOCTL=0x01, IOSTATUS=0,
    every sample identical. No transient firmware activity.
  - **Tier-2 (~150-1650 ms, 50 ms grain):** same — silent.
  - **Dwell-3000 ms:** same — silent.
  - **IOSTATUS=0x00000000 at every probe:** no wrapper-level fault
    bits. If firmware has faulted, the wrapper doesn't see it.
  - **fw[0] = 0xb80ef000:** the reset vector IS the first word of
    the firmware image. ARM boots from VA 0xb80ef000, which is in
    IMEM or a CR4-internally-mapped region (outside TCM).
  - Net: whatever happens to the ARM happens within <20 ms of
    `brcmf_chip_set_active` returning, without writing anything
    observable through TCM, D11, mailboxint, or the CR4 wrapper.

### Next-step ladder (all prior-granularity probes exhausted)

Further progress requires a different observation modality. Options in
rough order of effort-vs-yield, documented in POST-TEST.188:

- **B. Clean-room study of proprietary `wl` reset sequence** — identify
  register writes `wl` performs that brcmfmac does not (PMU, PLL, D11
  prep, shared-RAM handshake). Static disassembly / string analysis only
  on this host (`wl` won't load on kernel 6.12.80 per §Tools). Legally
  safest and likely highest yield.
- **F. OpenWrt / Asahi / SDK-leak patch survey** for BCM4360-specific
  init register writes missing from upstream. Cheap; concrete diffs.
- **C. IMEM / reset-vector inspection via BAR2 beyond TCM** — BAR2 is
  2 MB; TCM fills low 640 KB. Try a read-only sample at offset 0xef000
  (above ramsize) before and after `set_active`. Determines whether
  IMEM is BAR2-mapped and potentially exposes the reset-vector
  instructions.
- **A. ARM architectural fault registers (DFSR/IFSR/DFAR/IFAR)** —
  biggest project; defer.
- **D. Firmware UART console** — undocumented on Mac hardware; lowest
  priority.

**Recommendation:** pursue B and F in parallel (both offline / no host
risk); fall back to C as a quick hardware probe if B/F come up empty.

**Re-entering the old 5.2 investigation:** once the probe-path restore is
complete (i.e. firmware download and ARM release can run without host crash),
the TCM[0x58f08] D11-object-not-linked finding from test.98 still applies —
the path-B D11 core bring-up probe plan remains valid, just currently gated
behind getting firmware boot to run again.

**What is proven working (as of test.181):**
- Chip recognition, BAR0/BAR2 mapping, 442 KB firmware download, 228 B NVRAM
  placement, NVRAM marker readback at ramsize-4.
- ARM CR4 release via `brcmf_chip_set_active` (test.181 — reproducibly
  clean on current tree; CPUHALT transitions YES→NO, host survives ≥30 s).
- Clean module rmmod while ARM continues running firmware.

**What is not yet re-verified in this regression-recovery tree:**
- Firmware-originated TCM writes (next: test.182 post-release dwell +
  TCM re-read).
- Sharedram handshake / firmware init completion.
- Firmware reaching the old Phase-5.2 D11 PHY wait loop; test.98 finding
  `TCM[0x58f08] == 0` remains the standing downstream hypothesis.

See also GitHub issues #9 (architecture assessment) and #11 (direction review).

---

## Phase 1: Reconnaissance ✅ COMPLETE

**Goal:** Understand the chip and extract the firmware.

**Outcome:**
- 9 BCMA cores identified (ARM CR4, D11 rev 42, PCIe Gen2, ChipCommon rev 43,
  USB 2.0 Device, plus infrastructure cores).
- Firmware extracted from macOS `wl.ko`: `brcmfmac4360-pcie.bin` (442KB,
  v6.30.223.0, Dec 2013). Thumb-2 ARM, hndrte RTOS.
- brcmfmac delta scoped to ~10 lines for basic support.

Details: `phase1/notes/`.

---

## Phase 2: MMIO Tracing (fallback, not executed)

**Goal:** Capture the `wl` driver's MMIO sequence if Phase 3 fails in ways
that can't be diagnosed from dmesg alone.

**Status:** Not needed during Phase 3 (which succeeded at driver-side bring-up).
Was re-considered during Phase 5 crash investigation; `phase5/logs/wl-trace`
holds a partial capture for reference when/if the D11 reset sequence needs to
be compared against `wl`.

---

## Phase 3: Patched brcmfmac Bring-up ✅ COMPLETE

**Goal:** Prove the driver-side PCIe/TCM/ARM-control path works on BCM4360.

**Outcome:**
- Patches to `brcm_hw_ids.h`, `pcie.c`, `chip.c` add chip ID, firmware mapping,
  TCM rambase (corrected to `0x0`), and CR4 download handlers.
- Hardware characterized: BAR2 maps TCM at offset 0 (640KB populated);
  BCM4360 requires 32-bit `iowrite32` only (64-bit `memcpy_toio` hangs PCIe);
  B-bank must not be accessed via BANKIDX.
- Firmware download end-to-end verified.

**Key finding:** brcmfmac assumes msgbuf protocol but BCM4360 firmware speaks
BCDC. No msgbuf-compatible firmware exists for this chip.

Details: `phase3/results/diagnostic_findings.md`, `phase3/logs/`.

---

## Phase 4: BCDC-over-PCIe Host Transport ✅ PARTIALLY COMPLETE

**Goal:** Decide whether to build a BCDC-over-PCIe host transport (since
brcmfmac speaks msgbuf and BCM4360 firmware speaks BCDC).

**Outcome:**
- 4A (transport discovery): confirmed BCDC encapsulation + PCIe messaging
  mechanics from `wl.ko` and firmware strings.
- 4B (standalone harness): firmware download + ARM release work standalone
  but firmware crashed the host ~100–200ms after release.
- **Decision:** pivot to Phase 5 — patch brcmfmac directly rather than build
  a standalone driver, because brcmfmac already handles PCIe lifecycle,
  interrupts, and DMA setup.

4C (BCDC command implementation) and 4D (integration decision) deferred until
firmware boots cleanly in Phase 5.

Details: GitHub issue #4.

---

## Phase 5: BCM4360 Bring-up via brcmfmac ← **CURRENT PHASE**

**Goal:** Boot the BCM4360 firmware to a steady state where shared-memory
communication is possible, then establish a BCDC control path.

brcmfmac is being used as a **debug/bring-up harness**. Final driver
architecture (SoftMAC vs. offload) remains open — see GitHub issue #9.

### 5.1 — Basic chip support patches ✅ COMPLETE

Minimum viable patches applied (chip ID, firmware mapping, rambase=0,
32-bit iowrite32, INTERNAL_MEM NULL guard). Firmware downloads; ARM used to
crash the host on release.

### 5.2 — Firmware boot stability & forensics ← **IN PROGRESS**

Iterative debug-harness work driven by hypothesis → probe → log → commit.

**Resolved:**
- Host-crash-on-ARM-release root cause isolated (BAR2 wait-loop PCIe
  completion timeout + BCMA resetcore register sequencing). Phase-5.2
  probe path now runs cleanly through `brcmf_chip_set_active`.
- Apple random_seed footer was the first observable forward step (T236);
  fw reads the seed and progresses ≥90 s where without-seed runs stalled
  earlier.
- Single-register write-verify probes (T241–T246) settled: BAR0 writes
  to PCIE2 core regs land under `select_core(PCIE2)` at pre-FORCEHT;
  MBM D2H_DB bits are stage-gated and only become writable post-shared-init.

**Open:**
- Fw executes for ≥90 s post-set_active without writing anything observable
  in TCM, MBM, mailboxint, or any other MMIO slot we poll (T238–T246).
- **Leading hypothesis:** fw is blocked on a shared-memory-struct
  handshake. Upstream's `brcmf_pcie_init_share` pre-allocates a
  `pcie_shared` struct and writes its TCM address to `ramsize-4` before
  ARM release; our driver currently leaves `ramsize-4` at the NVRAM
  marker 0xffc70038, which is not a valid shared-struct address. T239
  polled that slot 22 times across ≥90 s — it never changed.
- **Next:** PRE-TEST.247 — pre-allocate a minimum-viable shared struct
  in TCM via BAR2, write its address to `ramsize-4` before
  `brcmf_chip_set_active`. See Current Status above for the full design
  framing.

**Exit criterion for 5.2:** firmware reaches a state where it writes a valid
shared-memory handshake structure (pcie_shared / BCDC control ring), or we
have a clear characterization of why it cannot.

### 5.3 — Firmware protocol bridge

**Goal:** Replace the msgbuf handshake with BCDC-over-PCIe so brcmfmac can
talk to BCM4360 firmware.

Gated on 5.2 completion.

### 5.4 — Functional validation

Scan, associate, transfer data. Gated on 5.3.

### 5.5 — Upstream submission

Patches to `linux-wireless@vger.kernel.org` and `brcm80211@lists.linux.dev`.

---

## Phase 6: Clean-room `wl` analysis ← **IN PROGRESS (parallel to 5.2)**

**Goal:** Identify the register writes the proprietary `wl` driver performs
during BCM4360 bringup that `brcmfmac` does not — specifically between
firmware download and the point firmware reaches normal operation.
Executes option B from the POST-TEST.188 next-step ladder.

### 6.1 — Symbol-level survey ✅ FIRST PASS

Commit `d6d1b98`, `phase6/NOTES.md`.

- `wl.ko` extracted (broadcom-sta-6.30.223.271-59, 7.3 MB, merged
  PCI/PCIe driver, supports 4350/4352/4360).
- Call chain mapped: `wl_pci_probe → wlc_attach → wlc_bmac_attach →
  wlc_hw_attach → wlc_bmac_corereset`.
- Gaps identified (present in `wl`, absent from `brcmfmac`):
  - `si_pmu_*` family (`si_pmu_chip_init`, `si_pmu_pll_init`,
    `si_pmu_res_init`, `si_pmu_waitforclk`, `si_pmu_spuravoid`, …).
  - `do_4360_pcie2_war` — BCM4360-specific WAR, called from
    `si_pci_sleep` and `wlc_bmac_4360_pcie2_war`.
  - OTP/NVRAM path via `otp_init` + `otp_nvread`; brcmfmac bypasses
    this with hardcoded 228 B NVRAM text.
- Concrete hypothesis link: test.188's observed pmucontrol bit-9 flip
  (firmware *requesting* a PMU resource) + `wl`'s PMU init path
  absent from brcmfmac ⇒ firmware's request never gets host-side
  acknowledgement.

### 6.2 — Review concerns (to address)

Priority-ordered from the code review of `d6d1b98`:

1. **Extract register-level detail** — current findings are symbol-level
   only. Without "wl writes 0xV to ChipCommon+0xOFF at these call sites"
   we can't reimplement or compare. **Start here**: disassemble
   `do_4360_pcie2_war` (small, BCM4360-specific, two call-sites) and
   document its register writes as offsets + values in plain language.
   Then `si_pmu_chip_init`. Commit a per-function markdown for each.
2. **Reproducibility of `find_callers.py`** — depends on
   `/tmp/wl_funcs.txt` which is not committed. Either commit the symbol
   list to `phase6/symbols/` or teach the script to regenerate it from
   `wl.ko` via `nm` / `objdump` at runtime.
3. **Side-by-side `wl` vs `brcmfmac` comparison table missing.**
   Listing wl's bringup sequence next to brcmfmac's `brcmf_chip_set_active`
   in a single table makes the gap concrete and auditable.
4. **`do_4360_pcie2_war` detail is the hottest lead**, not yet
   disassembled — promote to next action per concern 1.
5. **Kernel 6.12.80 constraint on `wl`** — see §6.3; can likely be
   lifted via NixOS boot params, unblocking dynamic tracing.
6. **Clean-room framing not restated in NOTES.md** — add a one-line
   reminder at the top: *extract register writes as offsets+values,
   not instruction sequences; never transcribe disassembly blocks*.
7. **Option F (OpenWrt / Asahi / SDK-leak patch survey) completed** — report generated in `phase6/pmu_pcie_gap_analysis_final.md`. Identified missing PMU/PCIe2 register writes.
   independent** — pure reading, zero host risk, can run in parallel
   with phase 6. Pick up opportunistically.
8. **No prioritisation inside NOTES.md "what to look for next".** My
   suggested order: `do_4360_pcie2_war` → `si_pmu_chip_init` →
   `si_pmu_pll_init` → `si_pmu_res_init` → `si_gci_init` →
   `pcicore_up/hwup` → `si_pcieclkreq`.

### 6.3 — Getting `wl` to load on this host (investigation)

**Current blocker:** on kernel 6.12.80 the module load fails with
*"Unpatched return thunk"*. Origin: since ~v5.19 the kernel's
`apply_returns()` validates that every `ret` in a loaded module is
annotated so retbleed / Spectre-v2 mitigations can patch it. `wl.ko`
(vintage ~2014, compiled without `-mfunction-return=thunk-extern`) has
bare returns and is refused.

**Why we want `wl` loaded:** once running we can `mmiotrace` a full
chip-attach run and diff the MMIO write stream against `brcmfmac`'s —
that is a direct list of missing writes, obtained in minutes instead
of weeks of static disassembly.

**Paths to enable (NixOS-specific):**

- **Boot param `retbleed=off` (simplest).** Add to NixOS config:
  ```nix
  boot.kernelParams = [ "retbleed=off" ];
  ```
  This disables the runtime return-thunk check. Likely sufficient.
  More aggressive alternatives: `"spectre_v2=off"` or
  `"mitigations=off"`. Security cost: the machine becomes vulnerable
  to Spectre-v2 / retbleed side-channel attacks — acceptable on a
  dedicated RE lab host with no sensitive workload, **unacceptable**
  on a machine that also handles personal/credentialed work.
- **Pin an older kernel that predates the check.** e.g.
  ```nix
  boot.kernelPackages = pkgs.linuxPackages_5_15;
  ```
  `wl` loaded cleanly on 5.x historically. Downside: loses newer
  kernel features; our brcmfmac patches must be re-tested on 5.15.
  Heavier change than a boot-param flip.
- **Rebuild `wl` with return-thunk compiler flag.** nixpkgs
  `broadcom_sta` is already a source build — a patch adding
  `EXTRA_CFLAGS += -mfunction-return=thunk-extern` to its kbuild
  invocation *may* produce a module that passes the check. Needs
  experimental confirmation; the proprietary assembly blobs inside
  `wl` may not tolerate the flag.
- **Binary-patch `wl.ko`.** Rewrite `ret` → `jmp __x86_return_thunk`
  throughout the module. Technically possible, high effort, fragile.

**Recommended approach:** try **boot param `retbleed=off`** first.
Cost: one line of NixOS config, one reboot. If `modprobe wl` then
succeeds, we have dynamic tracing available. If not, fall back to
pinning 5.15.

**Safety envelope for dynamic tracing once `wl` loads:**
- Confirm BCM4360 at 03:00.0 is unbound from `brcmfmac` before
  loading `wl`.
- Enable `mmiotrace` on BAR0/BAR2 ranges first, then `modprobe wl`.
- Capture one clean attach cycle to log, unload, rebind `brcmfmac`.
- Treat the trace log as reference data only — re-implement clean,
  do not transcribe MMIO sequences 1:1 without understanding the
  *why* of each write.

### 6.4 — Recommended next actions (ordered)

1. **Disassemble `do_4360_pcie2_war`** (concern 1 + concern 4).
   Document register writes in plain language in
   `phase6/do_4360_pcie2_war.md`. Smallest scope, BCM4360-specific,
   most-likely directly-testable driver patch.
2. **Commit symbol list + fix `find_callers.py`** (concern 2).
3. **Try `boot.kernelParams = [ "retbleed=off" ]` in NixOS config**
   (concern 5). If `wl` loads, dynamic tracing probably makes 4-8
   above much easier; if it doesn't, revert and continue static.
4. **Build side-by-side `wl` vs `brcmfmac` bringup table** (concern 3).
5. **Disassemble `si_pmu_chip_init`, then `si_pmu_pll_init`,
   `si_pmu_res_init`** (concern 8 priority order).
6. **Add clean-room reminder header to `phase6/NOTES.md`** (concern 6).
7. **Option F survey completed** — report generated in `phase6/pmu_pcie_gap_analysis_final.md`. Identified missing PMU/PCIe2 register writes.

---

## Tools and Environment

- **OS:** NixOS, kernel 6.12.x
- **Target device:** BCM4360 at PCI 03:00.0
- **Backup connectivity:** USB WiFi adapter (MT76x2u) at wlp0s20u2
- **Languages:** Python (probing/analysis), C (kernel module)
- **Key tools:** `ftrace`, `mmiotrace`, `trace-cmd`, `binwalk`, `objdump`,
  `readelf`, Ghidra (firmware analysis)
- **`wl` proprietary driver:** fails to load on kernel 6.12.80
  with *"Unpatched return thunk"* (post-v5.19 `apply_returns()`
  retbleed check; `wl.ko` compiled without `-mfunction-return=thunk-extern`
  has bare returns). Workaround is plausible — boot NixOS with
  `kernelParams = [ "retbleed=off" ]`, or pin `linuxPackages_5_15`.
  See §6.3 for the full path and safety envelope. Once loaded, `wl`
  enables live `mmiotrace` + `ftrace` capture of chip bringup —
  potentially orders of magnitude faster than static disassembly.

## Success Criteria

- BCM4360 works with an open-source Linux driver (scan, connect, data transfer).
- No proprietary code in the driver (firmware loaded as a separate binary).
- Patch accepted upstream or viable for out-of-tree use.
- BCDC-over-PCIe transport documented for community reference.

Even a partial result (e.g., control path works but data path proves
infeasible) is valuable — it documents the protocol and informs future efforts.
