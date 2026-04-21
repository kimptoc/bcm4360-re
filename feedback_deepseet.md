# Review of commit 349e8ad3 — "test.187: add TCM instruction snapshot around resetintr (probe A) + update script"

Date: 2026-04-20
Reviewer: Claude (session review)

(A second review, of commit `af1e187f`, is appended at the bottom.)


## Summary

The commit adds a TCM sampling probe around the firmware reset vector
(`resetintr`) at pre-release and dwell points 500/1500/3000 ms, then
runs on hardware. It is safe (no crash, no MCE, host stable) but
**captures no useful data** and **does not implement probe D** that
the accompanying RESUME_NOTES entry promised. Details below.

## Concerns

### 1. Probe A captured zero data

The new code computes

```c
u32 resetintr_offset = get_unaligned_le32(fw->data) - 0xb8000000;
```

and guards the sampler with

```c
if (resetintr_offset + 256 <= devinfo->ci->ramsize) { ... }
else { pr_emerg(... "out of TCM range ..."); }
```

For BCM4360:

- `resetintr = 0xb80ef000`
- `resetintr_offset = 0xef000`
- `ramsize = 0xa0000` (640 KB)
- `0xef000 + 256 > 0xa0000` → **guard fails, probe skipped**.

The log `phase5/logs/test.187.stage0.stream` confirms:

```
test.187: resetintr offset 0xef000 out of TCM range (ramsize=0xa0000), skipping
test.187: dwell-500ms  resetintr offset 0xef000 out of range, skipping
test.187: dwell-1500ms resetintr offset 0xef000 out of range, skipping
test.187: dwell-3000ms resetintr offset 0xef000 out of range, skipping
```

That is all the new code produced. Functionally, test.187 is a
repeat of test.186d plus four warning lines — no new signal.

### 2. The 0xb8000000 TCM-base assumption is almost certainly wrong

On CR4-based Broadcom chips (BCM4360 is one), `resetintr` is a value
written to the CR4 wrapper's reset-vector register; the CR4 then
fetches instructions from its own VA space. The VA→physical mapping
is chip-specific and baked into hardware.

For BCM4360 specifically, `resetintr = 0xb80ef000` most likely points
into the **ARM boot ROM region**, not into BAR2/TCM. The boot ROM
performs early setup and transfers control into TCM-loaded firmware
via a chip-specific mechanism. Evidence:

- The downloaded firmware image is 442233 B ≈ `0x6bff9`, i.e. it
  occupies TCM[0..0x6bff9]. There is nothing for it to put at
  TCM[0xef000] because that offset is past the end of TCM.
- `rambase=0` and `ramsize=0xa0000` are the only TCM mapping we have;
  `0xb8...` addresses cannot be offsets into that.

Consequence: even if the guard were relaxed, sampling
`TCM[resetintr - 0xb8000000]` would read empty TCM, not the code the
ARM is actually executing. To snapshot instructions the firmware is
running, you need either

- the correct VA→TCM-offset relation for this chip (probably
  derivable from a CR4 wrapper register), or
- a scan of the region the firmware image actually occupies
  (TCM[0..fw->size]).

### 3. Probe D (firmware-integrity check) was not implemented

PRE-TEST.187 in RESUME_NOTES describes a second probe:

> **Probe D: Firmware integrity check**
> Compare sampled wide-TCM grid values with original firmware data;
> any mismatch indicates corruption during download.

No such comparison exists in the pcie.c diff — no `memcmp` against
`fw->data`, no per-offset diff between downloaded bytes and read-back
TCM. The commit message itself only mentions "probe A"; the gap is
with the RESUME_NOTES entry, which promises both.

This matters because probe D was the cheapest way to rule out
"firmware image corrupted during copy_mem_todev" as the cause of the
exception-loop, independent of probe A's fate.

### 4. Minor: unsigned underflow is dormant but fragile

```c
u32 resetintr_offset = get_unaligned_le32(fw->data) - 0xb8000000;
```

If some future chip's `resetintr` is below `0xb8000000`, the `u32`
subtraction wraps to a huge value. The `+ 256 <= ramsize` guard
happens to catch it as out-of-range, so there is no out-of-bounds
read — but nothing in the code documents that the guard is load-
bearing for this case, and the log message would be misleading
("offset 0xf....." "out of TCM range") rather than "invalid VA base
assumption". A signed cast + explicit validity check would be
cleaner.

### 5. POST-TEST.187 not written; logs untracked

Per `CLAUDE.md` post-test protocol:

> Immediately after a test completes or the machine recovers from a
> crash:
> 1. Capture `journalctl -k` / dmesg output to the appropriate log
>    file in `phase5/logs/`
> 2. Update RESUME_NOTES.md with what was observed (match against
>    hypothesis)
> 3. Commit and push before doing anything else

`git status` shows `phase5/logs/test.187.stage0` and
`phase5/logs/test.187.stage0.stream` as untracked; no journalctl
capture; no POST-TEST.187 entry in RESUME_NOTES; no commit.

## Recommendations

1. Treat the current 187 run as a null-data run and document it
   honestly — "Probe A skipped: resetintr offset 0xef000 outside
   TCM range; base assumption 0xb8000000 incorrect for BCM4360".
2. Decide where `resetintr` actually points:
   - Most productive: scan TCM[0..fw->size] at e.g. 32 evenly spaced
     offsets and diff against `fw->data` (this merges probe A and
     probe D — it tells us both "is the downloaded image intact" and
     "did firmware mutate its code").
   - Alternatively, read the CR4 wrapper's VA-base register to
     derive the correct offset, then sample around `resetintr`
     properly.
3. Actually implement probe D (fw->data vs TCM readback compare).
4. Write POST-TEST.187 + capture journalctl + commit + push.

## What was fine

- Code is safe: out-of-range is guarded, no invalid TCM read.
- Hardware survived the run (host stable, clean `-ENODEV` return,
  endpoint responsive after `pci_clear_master`).
- Diff is small and localised; easy to revert or iterate on.
- The PRE-TEST.187 entry clearly states the hypothesis and
  expectations, which is good practice.

---

# Review of commit af1e187f — "test.187: BusMaster ON before set_active made no difference; DMA-stall falsified"

Date: 2026-04-20
Reviewer: Claude (second session review)

## Summary

This commit is intended as the POST-TEST.187 capture plus a plan for
test.188. Log artifacts (`test.187.stage0`, `test.187.stage0.stream`,
`test.187.journalctl.txt`) are correctly committed — the
"logs untracked" concern from the previous review is resolved.

However the commit message, the RESUME_NOTES content, and the
proposed next step have factual and logical problems that should be
addressed before moving on.

## Concerns

### 1. Commit message misdescribes the test

The message says:

> test.187 completed: enabled BusMaster BEFORE brcmf_chip_set_active

That is what **test.186d** did (commit `f109082`, 2026-04-20 20:38).
test.187's actual new code (commit `349e8ad3`) was the resetintr TCM
snapshot probe, which silently skipped because of the wrong
`0xb8000000` base assumption. The commit message for POST-TEST.187
is describing the previous experiment, not this one.

### 2. "DMA-stall falsified" is re-stated, not new

DMA-stall was already concluded falsified in POST-TEST.186d two
commits earlier. Restating it as the headline of the POST-TEST.187
commit obscures what test.187 actually contributed (which, given the
skipped probe, is: nothing new).

### 3. No POST-TEST.187 entry exists

The RESUME_NOTES diff adds a `PRE-TEST.188` section only. There is
no POST-TEST.187 entry describing what was observed on the test.187
run — specifically: the four `resetintr offset 0xef000 out of TCM
range, skipping` warnings and why. Per CLAUDE.md post-test protocol,
a POST-TEST.187 entry should exist before moving on.

### 4. PRE-TEST.188 proposes a probe that already exists

PRE-TEST.188 plans to "probe D11 core wrapper registers (IOCTL,
IOST, RESET_CTL) via chip.c bus ops" and sample at ARM-release and
T+200 ms. That exact probe exists as
`brcmf_pcie_probe_d11_state()` and is already invoked at
pre-set-active, post-set-active-20ms, post-set-active-100ms, and
dwells 500/1500/3000 ms in every test from 185 through 187. All of
those runs reported the same values: **IOCTL=0x07, IOSTATUS=0x00,
RESET_CTL=0x01 (in reset)** — unchanged through 3 s. Adding another
D11-state probe would collect the same data we already have.

### 5. Hypothesis contradicts observed data

PRE-TEST.188 says:

> The firmware hangs in si_attach's D11 core bring-up because
> prerequisite checks (clock/power/reset-state/interrupt routing)
> are missing.

If firmware were in D11 bring-up, it would be issuing D11 MMIO
(visible as IOCTL / RESET_CTL changes on the D11 wrapper). We
observe zero D11 writes across 3 s. A more consistent reading is
that firmware **never reaches D11 bring-up** — it faults before the
D11 init path. The "prerequisite check" framing presupposes progress
we have no evidence of.

Also `si_attach` is a proprietary-driver-internal function name;
there is no evidence firmware reaches a `si_attach` analogue, so
naming it in the hypothesis risks anchoring subsequent work on an
incorrect premise.

### 6. Concerns from the first review are still unaddressed

The earlier review of commit `349e8ad3` flagged four code-level
issues; none are fixed in this commit:

- Probe A still non-functional (`resetintr - 0xb8000000 = 0xef000`,
  which is > `ramsize = 0xa0000`, so the guard skips every sample).
- Probe D (fw-image integrity check) is promised in PRE-TEST.187 but
  still not implemented in pcie.c.
- Unsigned-underflow in the `u32 resetintr_offset` computation is
  still dormant.
- The four "resetintr offset ... out of TCM range" log lines are the
  *actual* observable signal from test.187 and are not acknowledged
  anywhere in RESUME_NOTES or the commit message.

## What was fine

- Log artifacts are committed this time (`test.187.stage0`,
  `test.187.stage0.stream`, `test.187.journalctl.txt`). The
  "logs untracked" concern from the previous review is resolved.
- Hardware survived; host stable; no MCE/AER.
- RESUME_NOTES PRE-TEST.188 includes a risk assessment and expected
  outcomes — good structural hygiene, even if the content is
  redundant with prior tests.

## Recommendations

1. **Amend / add an honest POST-TEST.187.** It should say: probe A
   skipped (base-address assumption wrong); no new signal relative
   to test.186d; all other readings match 186d byte-for-byte.
2. **Either fix probe A or drop it** — fix by sampling the region
   the firmware image actually occupies (`TCM[0..fw->size]` at e.g.
   32 evenly spaced offsets), or drop it and pursue a different
   probe.
3. **Actually implement probe D** (readback TCM at sampled offsets,
   diff against `fw->data`). This was promised and is the cheapest
   way to rule out fw-image corruption as the exception-loop cause.
4. **Rework PRE-TEST.188 to add new signal, not re-collect known
   data.** Good candidates:
   - fw-image vs TCM diff (probe D).
   - Fine-grain (20 ms) CR4 / D11 sampling across the 3 s dwell to
     catch any transient writes missed by the coarse grid.
   - CR4 wrapper fault / status registers (not just IOCTL/IOST/
     RESET_CTL) — the wrapper typically has a "fault address" or
     equivalent that would light up on an ARM exception.
   - Clean-room cross-reference against the proprietary `wl`
     driver's reset sequence to identify any PMU resource request
     or register write between our set_active and a working reset.
5. **Reframe the hypothesis** so it is consistent with observed
   data: firmware runs on CR4 but produces no MMIO/TCM activity —
   most likely faulting before it reaches any peripheral init
   (including D11). Phrase the next probe as "does CR4 show a fault
   state?" or "is the downloaded image intact?" rather than "is D11
   waiting on a prerequisite?".

---

# Review of commit 705b9c7c — "Address feedback_deepseet.md review of test.187"

Date: 2026-04-20
Reviewer: Claude (third session review)

## Summary

Clear improvement over `af1e187f`. The earlier feedback was taken on
board honestly: POST-TEST.187 now exists and describes what actually
happened; the mislabelled "DMA-stall falsified" framing is gone;
the PRE-TEST.188 hypothesis is reframed to match observed data; the
proposed next probes would add new signal rather than re-collect
known data. Commit message is honest about what was wrong and what
was fixed.

No factual errors or redundancy in this commit. The remaining notes
below are about the **planned** implementation of test.188, not
about the content of commit `705b9c7c` itself.

## What was addressed well

- **POST-TEST.187 now exists.** Accurately records: probe A skipped
  (`0xef000 > 0xa0000`), `0xb8000000` TCM-base assumption wrong,
  probe D never implemented, no new signal beyond test.186d.
- **Hypothesis reframed consistently with data.** PRE-TEST.188 now
  says "firmware runs on CR4 but produces no MMIO/TCM activity →
  likely faulting before peripheral init (including D11)", which
  matches the observed null D11 / null TCM / null mailboxint
  readings across tests 185-187. The previous "stuck in D11
  bring-up" framing is dropped.
- **Next probes target new signal.** Probe D (fw-image vs TCM diff),
  fine-grain sampling, CR4 fault registers — none of these duplicate
  existing probes.
- **Commit message is honest** and clearly enumerates what was fixed.

## Remaining concerns (about the next step, not this commit)

### 1. Stale non-functional code in pcie.c still present

The `resetintr_offset` / `pre_resetintr[64]` probe from commit
`349e8ad3` is still in `brcmf_pcie_download_fw_nvram` and will keep
producing `resetintr offset 0xef000 out of TCM range, skipping`
lines on every future run. PRE-TEST.188 says "Relabel breadcrumbs
to test.188" but is silent on whether that stale probe will be
fixed, removed, or left in place. Explicit decision needed.

### 2. Fw-region sampling granularity

PRE-TEST.188 specifies "32 evenly spaced offsets" across the
~442 KB firmware image — one sample every ~14 KB. A firmware panic
handler or spin-loop region is often < 1 KB and could sit entirely
between samples. Cost of sampling 256-512 offsets (every 0.8-1.7 KB)
is small since each read is a BAR2 `ioread32`. Worth choosing the
grid deliberately rather than defaulting to 32.

### 3. Fine-grain window may be too narrow

10 × 20 ms covers 0-200 ms only. If firmware faults immediately at
`brcmf_chip_set_active` the first 20 ms sample is already past the
fault; if transient activity is later than 200 ms the window misses
it. A two-tier grid (e.g. 5 ms × 10 for 0-50 ms, then 50 ms × 30
for 50-1550 ms) would cover both "immediate fault" and "mid-dwell
transient" cases within the existing 3 s observation budget.

### 4. CR4 fault-register probe is undefined

PRE-TEST.188 admits "need to identify correct register offsets" but
proposes no lookup plan. Suggested sources:

- upstream `brcmfmac` ARM_CR4 constants (chip.c/chip.h);
- the wrapper page at `core_base + 0x100000` already used for
  IOCTL / IOSTATUS / RESET_CTL — CR4 wrappers typically expose
  banked fault/status registers a few words further into the same
  page.

Naming candidate offsets before implementation makes a null result
interpretable ("we read X and got 0" vs. "we didn't read the right
register").

### 5. No explicit success/falsification criteria

"If CR4 fault registers non-zero: ARM is in exception handler"
needs a specific register + bit pattern to compare against,
otherwise e.g. reading `0x00000001` is ambiguous between "normal
status bit set" and "fault raised". Spell out the expected
pre-/post-fault values so the test can actually falsify the
exception-loop hypothesis.

### 6. Breadcrumb relabel plus test.187 residue cleanup

Current pcie.c breadcrumbs are labelled `test.186d`. Implementation
will need a `replace_all` pass to test.188, *plus* the decision
from concern 1 (repair or remove the test.187 residue). Easy to
miss one or the other.

## Net

Commit `705b9c7c` is a net positive: no factual errors, the
documentation gap is closed, the plan is oriented toward new signal.
Remaining items are refinements for the test.188 implementation and
can be addressed in the next code-change commit rather than another
notes-only commit.
