# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-17, POST test.101 — Case 0: breadcrumb ZERO, hang UPSTREAM of 0x68bbc)

Git branch: main. Last pushed commit fcb9558 (Pre-test.101 rev — baseline probe).
Untracked: `phase5/logs/test.101.stage0` (needs commit).

### TEST.101 RESULT — Case 0 (matrix row 1): breadcrumb ZERO

Test.101 ran cleanly in boot -1 (07:42:59 → 07:43:01 clean exit). Machine
then crashed/rebooted ~30 min later (08:13:05 boot 0) — unrelated to the
test run itself; the test completed with "RP settings restored".

Key readings:
```
Pre-ARM baseline: *0x62e20 = 0x00000000  ZERO (expected — no stale TCM) ✓
T+200ms:          *0x62e20 = 0x00000000  ZERO
```

Control pointers (as test.100):
```
ctr[0x9d000]  = 0x000043b1
d11[0x58f08]  = 0x00000000
ws [0x62ea8]  = 0x0009d0a4
pd [0x62a14]  = 0x00058cf0
```
Counter frozen at 0x43b1 from T+200ms onward, confirming hard freeze by
T+12ms (per test.89 timeline) still holds.

**Interpretation per test.101 matrix row 1:** baseline=0 means no stale
TCM (interpretation is clean); T+200ms=0 means fn 0x68a68 NEVER wrote
*0x62e20 at 0x68bbc. Therefore fn 0x68a68 did NOT reach 0x68bbc.

Combined with test.100 (Case C′: fn 0x1624c never ran), the freeze is:
- Inside fn 0x68a68 prefix/body BEFORE bl 0x1ab50 at 0x68bcc
  (specifically the unexamined body region 0x68aca–0x68bbc), OR
- Upstream in wl_probe (fn 0x67614), in one of the earlier sub-BLs
  BEFORE bl 0x68a68 at 0x67700.

Per the earlier subagent offline disasm (`offline_disasm_wl_subbls.md`),
the five wl_probe sub-BLs (fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c,
plus fn 0x68a68 prefix through 0x68aca) contain NO spin loops, HW-register
polling, or fixed-TCM stores in their direct bodies. The hang must
therefore be in one of their DESCENDANTS, or in fn 0x68a68's UNEXAMINED
body 0x68aca–0x68bbc.

### Next step — offline disasm BEFORE test.102

Cheap-progress ordering (no hardware test):

1. **Disasm fn 0x68a68 body region 0x68aca–0x68bbc** (~242 bytes, Thumb-2).
   This is the region between prefix end (already clean) and the
   breadcrumb store. If a spin loop or HW poll exists here, hang is
   inside fn 0x68a68 itself. Identify any globals/pointers written so
   we have candidate breadcrumbs for test.102.

2. **Disasm descendants of fn 0x66e64, fn 0x649a4, fn 0x6491c** (wl_probe's
   earlier sub-BLs). These haven't been traced one level deeper. Find
   any globals/fixed-TCM stores we could breadcrumb.

3. Only AFTER offline disasm: design test.102 probes from concrete
   breadcrumb sites (likely ONE new probe at a specific TCM address that
   would only be non-zero if fn 0x68a68 body reached a particular
   checkpoint).

### Pre-test.101 state (retained for context below)

---

### Advisor refinement #1 (added 2026-04-17, pre-run)

Per advisor, the pre-ARM baseline read was the missing piece from the
earlier test-plan review — without it, a non-zero post-FW breadcrumb
could reflect residual TCM state from a prior in-same-boot modprobe,
not a fresh FW write. Code change: 3-line probe in pcie.c inside the
existing pre-ARM logging block (before ARM release, zero masking-loop
impact). Emits `dev_emerg "BCM4360 test.101 pre-ARM baseline: *0x62e20=...
ZERO (expected) / NON-ZERO (stale TCM, breadcrumb reading is unreliable)"`.

Matrix interpretation rule: if baseline != 0, the T+200ms breadcrumb
reading is UNRELIABLE and the run should be re-done after fresh power
cycle. If baseline == 0 and T+200 == 0 → Case U1 (hang before 0x68bbc).
If baseline == 0 and T+200 != 0 → Case D (hang at/past bl 0x1ab50).

### Offline disasm result (subagent, 2026-04-17)

`phase5/notes/offline_disasm_wl_subbls.md` — full report.

Disassembled wl_probe's 5 untraced sub-BLs (fn 0x66e64, fn 0x649a4,
fn 0x4718, fn 0x6491c) and fn 0x68a68's prefix. **None contain spin loops,
HW-register polling, or fixed-TCM stores** — every memory write is
r4-relative into the freshly-malloc'd wl_ctx. fn 0x4718 is a 3-instruction
leaf. Therefore the hang is NOT internally in any of those five.

**Most-likely hang site:** fn 0x68a68 (wlc_attach) BODY between its prefix
end at 0x68aca and `bl 0x1ab50` at 0x68bcc — an unexamined region (test.100
only excluded fn 0x1624c, a deeper descendant).

**Hot breadcrumb identified: `*0x62e20`.** Spot-verified:
```
0x68bb6: ldr  r3, [pc, #200]   ; literal at 0x68c80 = 0x00062e20 ✓
0x68bb8: ldr  r2, [r3]
0x68bba: cbnz r2, 0x68bbe       ; skip if already set
0x68bbc: str  r4, [r3]           ; *0x62e20 = wl_ctx ptr
0x68bcc: bl   0x1ab50            ; PHY descent (8 bytes later)
```
`*0x62e20` is zero in the firmware image. After firmware reset:
- **non-zero** → fn 0x68a68 advanced to within 8 bytes of bl 0x1ab50;
  hang is inside bl 0x1ab50 (or the 2-insn gap before it). test.100
  already excluded fn 0x1624c, so the hang would be in fn 0x1ab50 BEFORE
  it reaches fn 0x16476.
- **zero** → fn 0x68a68 did not reach 0x68bbc. Hang is in one of its
  earlier BLs (0x68a68 prefix/body), or in wl_probe BEFORE bl 0x68a68 at
  0x67700 — i.e. in fn 0x66e64 / fn 0x649a4 / fn 0x4718 / fn 0x6491c's
  DESCENDANTS (since their direct bodies are bounded).

### test.101 PLAN — minimal single breadcrumb probe

**Goal:** narrow hang to "past 0x68bbc" vs "before 0x68bbc" with MINIMUM
loop-overhead impact. Test.100 added 9 extra `read_ram32` calls and
regressed (boot ended between T+1800ms and T+2000ms).

**Probe changes from test.99 baseline:**
- REMOVE test.100's triple-timepoint 3-field wait-struct reads (already
  answered — Case C′ confirmed, struct never touched).
- REMOVE test.100's T+400ms+T+800ms duplicate pointer probes (test.99
  already proved pointers are byte-identical across those windows).
- ADD one new read: `TCM[0x62e20]` at T+200ms only.

Net: test.101 probe count = test.99 - 2 + 1 = **fewer reads than
test.99**. Should not regress on the masking-loop budget.

**Also:** shorten FW-wait from 2000ms to 1200ms to widen safety margin
against whatever periodic event killed test.100 at ~1.9s.

**Matrix (after reading *0x62e20):**

| *0x62e20 | Conclusion | Next action |
|----------|------------|-------------|
| 0          | fn 0x68a68 did NOT reach 0x68bbc. Hang is in 0x68a68 prefix/body before the breadcrumb, or upstream in wl_probe sub-BL descendants. | test.102: probe wl_ctx fields (needs wl_ctx ptr discovery first) OR disasm fn 0x68a68 prefix + descendants of fn 0x6491c. |
| non-zero, value plausible as heap ptr (TCM range 0x0..0xA0000, typically 0x9xxxx) | fn 0x68a68 reached 0x68bbc. Hang is inside the window `bl 0x1ab50 → bl 0x16476 → b.w 0x162fc → bl 0x1624c` but NOT inside fn 0x1624c itself (test.100 excluded that). So hang is in the body of fn 0x1ab50, fn 0x16476, or fn 0x162fc pre-spin. | test.102: disasm those three fn bodies pre-bl; probe their breadcrumbs. |
| non-zero, value implausible (random)    | Either TCM read failed or breadcrumb theory is wrong. | Re-check read path; verify literal pool claim with second tool. |

**Pre-flight reminders:**
- Probe is read-only via `brcmf_pcie_read_ram32` (same safe path as test.99/100).
- FW-wait shortened to 1200ms. No other change to cleanup order.
- If machine crashes anyway, that's still informative — different cadence
  than test.100 would pinpoint what the ~1.9s event is.

### Hardening checks completed before build

**Firmware image at offset 0x62e20**: 0x00000000 (surrounding .bss-like
region also zero). So post-FW non-zero at 0x62e20 unambiguously means
FW wrote it.

**All writers of 0x62e20 in the firmware** (grepped literal 0x00062e20,
3 aligned hits in pools at 0x149b0 / 0x68208 / 0x68c80):
1. `fn 0x68a68 @ 0x68bbc` — `str r4, [r3]` sets wl_ctx ptr (attach path,
   on wl_probe lineage). **This is the breadcrumb.**
2. `fn 0x681bc @ 0x681cc` — `str r2, [r3]` where r2=0, conditional clear.
   Prologue at 0x681bc; only runs on detach/cleanup (guarded by `arg ==
   *0x62e20`). **Does NOT run during wl_probe.**
3. `fn at 0x14948 uses literal at 0x149b0` — READ-ONLY
   (`ldr r3,[pc,#88]; ldr r3,[r3,#0]; cbz r3,err; ldr r3,[r3,#12]`).
   Diagnostic/logging helper. **Not a writer.**

→ During wl_probe attach, only writer of 0x62e20 is fn 0x68a68 @ 0x68bbc.
Breadcrumb semantics are preserved: non-zero at T+200ms ⇒ that single
instruction ran.

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.100 probe block with
  test.101: single read of TCM[0x62e20] at T+200ms. Drop duplicate
  pointer reads at T+400/800ms. Change FW-wait cap from 2000ms to 1200ms.
- `phase5/work/test-staged-reset.sh` — relabel test.100 → test.101,
  LOG filename accordingly.

### After running test.101
- Apply matrix, choose test.102.
- Most-likely outcome (per subagent analysis) is *0x62e20 non-zero →
  hang is in fn 0x1ab50 pre-bl body.

### TEST.100 RESULT — Case C′ (matrix row 5): wait-struct = pre-init garbage, stable

test.100 ran in boot -1 (23:31:37 → 00:46:48). Probes at T+200/400/800ms
captured identical values (stability check PASSED). Firmware hard-frozen
at T+12ms per test.89 timeline; nothing on-chip changed across 600ms.

Control pointers (identical across T+200/400/800ms):
```
ctr[0x9d000]  = 0x000043b1    (static constant from fn 0x673cc)
d11[0x58f08]  = 0x00000000    (D11 obj never linked)
ws [0x62ea8]  = 0x0009d0a4    (wait-struct pointer — static, from BSS)
pd [0x62a14]  = 0x00058cf0    (pciedngl vtable, matches test.93/99)
```

Wait-struct field reads at ws=0x9d0a4 (identical across T+200/400/800ms):
```
f20 [ws+0x14] = 0x66918f11
f24 [ws+0x18] = 0x5bebcbeb
f28 [ws+0x1c] = 0x84f54b2a
```

**None of these are {0,1}** — they are arbitrary 32-bit values. Per the
test.100 matrix (row 5): `f24 ∉ {0,1}` → **Case C′: struct never touched,
pre-init garbage**. fn 0x1624c's setup code (`r3->field24=1;
r3->field28=0`) never ran, therefore fn 0x1624c itself never ran.

**Conclusion:** the freeze is strictly upstream of fn 0x1624c — inside
wl_probe (fn 0x67614), before it reaches the D11 PHY wait chain. The
bl-graph says exactly one path from wl_probe reaches fn 0x1624c; that path
is fn 0x67700→0x68a68→…→0x1624c. The hang must be in either the body of
fn 0x68a68 before its call to fn 0x1ab50, or in one of the 6 other sub-BLs
wl_probe invokes BEFORE bl 0x68a68 (at offsets 0x67700 and earlier).

This corroborates test.97's hint (same "garbage" reading) and definitively
rules out the PHY-completion-wait hypothesis as the LIVE freeze site.

### Test.100 ALSO produced a new regression

The run died between T+1800ms and T+2000ms (journal ends at T+1800ms
FROZEN, no TIMEOUT / RP-restore lines, machine powercycled). test.99 used
the same FW-wait loop and exited cleanly at T+2000ms. The delta is 3 extra
`read_ram32` calls at each of T+200/400/800ms (≈30–90ms total extra time
in the masking loop). That evidently nudged past a re-mask window and a
periodic PCIe event slipped through.

**Implication for test.101:** the masking loop must be re-audited or the
FW-wait shortened (e.g. 1000ms) before adding any more probes. Do NOT
stack further reads on top of the current loop without budget work.

### Next step — offline-only progress before test.101

Per advisor review, the cheap-progress ordering is:

1. **Firmware-binary sanity check** (30 seconds, offline): dump firmware
   image bytes at offset 0x9d0b8, 0x9d0bc, 0x9d0c0. If they match the read
   values 0x66918f11 / 0x5bebcbeb / 0x84f54b2a → "Case C′ = firmware image
   static data" confirmed. If they don't match → new puzzle (uninit RAM?
   wrong address translation?).

2. **Offline disasm of wl_probe's 6 untraced sub-BLs**. wl_probe has 7
   sub-BLs; only bl 0x68a68 at 0x67700 (→ PHY chain) is currently mapped.
   The other 6 are unknown. Find each, note its reads/writes (globals or
   fields of wl_struct). The hang is in one of them (or in fn 0x68a68's
   body before bl 0x1ab50). This narrows test.101 to concrete breadcrumbs
   instead of the hypothetical wl_struct[+0x90] placeholder.

3. **Masking-loop audit**: ensure re-mask fires every iteration when probe
   block inflates the body; consider dropping FW-wait from 2000ms to
   1000ms for test.101 to widen margin.

4. Only THEN design test.101 probes from concrete breadcrumb sites.

---

## Pre-test.100 state (retained for context below)

### Offline disasm — wl_probe and freeze chain (no hardware test)

`phase5/notes/offline_disasm_c_init.md` Round 3 + Round 4 (full detail).

Anchored "wl_probe called\n" print site to fn 0x67614 (LDR-literal scan
matched "wl_probe" string at 0x4a1ea via *0x67890). **fn 0x67614 IS
wl_probe()**. It is called as `wl_struct.ops[0]` from inside fn 0x63b38 in
c_init's wl-device registration step.

Brute-force callgraph BFS (depth ≤ 6) from each of wl_probe's 7 sub-BLs
shows EXACTLY ONE reaches the test.96 D11 PHY wait chain:

```
wl_probe @ 0x67614
 → bl 0x68a68 @ 0x67700           (5 stack args + 4 reg args)
   → bl 0x1ab50 @ 0x68bcc
     → bl 0x16476 @ 0x1ad2e        (PHY register access wrapper)
       → b.w 0x162fc                (PHY-completion wrapper)
         → bl 0x1624c @ 0x1632e     (SPIN: while ws->f20==1 && ws->f28==0)
```

`fn 0x68a68` has exactly ONE caller — wl_probe at 0x67700 — so the entry to
the spin-loop subtree is unique through wl_probe. The freeze fingerprint
matches test.96's analysis (D11 PHY ISR never fires → field28 stays 0). The
EARLIER claim that the hang was via c_init's "Call 3" (0x6451a) was wrong —
that dispatch chain only runs AFTER wl_probe RETURNS, and wl_probe never
returns (so wl_struct[+0x18] stays 0, as observed in test.99).

Open questions remaining (will be answered by test.100):
- Is the live freeze actually inside the fn 0x1624c spin-wait, or earlier
  in the wl_probe path (e.g. inside fn 0x66e64 / fn 0x649a4 / fn 0x68a68
  body before reaching the PHY chain)?
- Wait struct address: test.99 read `*0x62ea8 = 0x9d0a4` — the static BSS
  struct that fn 0x1624c spins on. We can probe its field20/24/28 directly.

### test.100 PLAN — wait-struct field probe (cheap PHY-wait fingerprint check)

**Goal:** decide between three concrete hypotheses with ONE more cheap
read-only hardware cycle:

1. PHY spin-loop is the live freeze location (advisor's "case A").
2. fn 0x1624c entered then exited via the cancel path (case B).
3. fn 0x1624c never entered — freeze is upstream in wl_probe (case C).

**Probes (stage0, all read-only TCM accesses via brcmf_pcie_read_ram32):**

Wait struct: addr = `*0x62ea8 = 0x9d0a4` (confirmed in test.99). Read fields
at offsets +0x14/+0x18/+0x1c (= field20 / field24 / field28 in test.96
analysis) at T+200/400/800ms to confirm stability:

```
ws_addr  = *0x62ea8                        ; should be 0x9d0a4
field20  = TCM[ws_addr + 0x14]             ; status flag (loop var)
field24  = TCM[ws_addr + 0x18]             ; "in progress" flag
field28  = TCM[ws_addr + 0x1c]             ; completion flag (set by ISR)
```

Also keep the test.99 pointer-sample probes (ctr/d11/ws/pd) as control — if
those CHANGE between test.99 and test.100 it would invalidate the read.

**Pre-flight stability check (READ FIRST before applying matrix):**

test.89 established firmware hard-freezes by T+12ms. test.99 confirmed
control pointers are byte-identical across T+200/400/800ms. Therefore
field20/field24/field28 MUST also be byte-identical across the three
timepoints. **If they vary, that itself is the bigger story** (delayed
code path, or the read isn't doing what we think — e.g. probe disturbing
state, addr translation wrong). Stop, characterise the variation, and DO
NOT apply the matrix to T+200ms values alone.

**Matrix interpretation (advisor, refined):**

| field24 | field20 | field28 | Conclusion |
|---------|---------|---------|------------|
| 1 | 1 | 0 | **Case A — spin-loop is live freeze.** Path B step 1 (D11 BCMA wrapper bring-up to enable D11 core / route ISR). |
| 1 | 0 | 0 | **Case B — entered then cancelled.** Hang is in fn 0x162fc body AFTER bl 0x1624c returned via cancel path. Re-examine fn 0x162fc continuation. |
| 1 | * | !=0 | Spin completed (field28 set), but firmware still hung downstream. Hang is past PHY wait — need to trace fn 0x1ab50 / fn 0x68a68 callees beyond the PHY register loop. |
| 0 | * | * | **Case C — fn 0x1624c never entered, struct zero-initialised.** Freeze is upstream in wl_probe. Probe candidates: fn 0x66e64, fn 0x649a4, fn 0x4718, fn 0x6491c, or fn 0x68a68 body before bl 0x1ab50. |
| ∉{0,1} | * | * | **Case C′ — struct never touched, pre-init garbage** (test.97 saw garbage values here). Same upstream-freeze conclusion as C, but distinguishable from "BSS-zero never-entered" — different next-test framing. |

**Risk profile:** identical to test.99. All probes are TCM reads via
existing `brcmf_pcie_read_ram32` path, gated by the same masking macro.
test.99 ran cleanly (clean exit, RP restored) so test.100 should too. If
the machine crashes anyway, that itself is a useful signal (different from
test.99's clean exit).

### Files to modify before run
- `phase5/work/drivers/.../pcie.c` — replace test.99 probe block (lines
  ~2516-2621) with test.100: 3-field wait-struct probes + control pointer
  re-reads at T+200/400/800ms. Drop the console ring dump (test.99 already
  read it; nothing changed).
- `phase5/work/test-staged-reset.sh` — labels test.99 → test.100, LOG
  filename test.99.stage${STAGE} → test.100.stage${STAGE}.

### After running test.100
- Map readings to the matrix above to choose next test.
- Common-case (A) follow-up = test.101 = D11 core wrapper bring-up via
  chip.c bus-ops (Path B step 1).
- (B) follow-up = offline-disasm fn 0x162fc continuation past 0x16332.
- (C) follow-up = test.101 = probe wl_probe sub-allocations (e.g. write a
  "breadcrumb" by reading r4 alloc result via TCM probe of wl_struct[+0x90]).

---

## Pre-test.99 state (2026-04-17, retained for context)

Git branch: main. Last pushed commit 75b52a1 (Post-test.99 doc).
Pending commit: offline disasm of c_init() + corrected freeze location.

**TEST.99 RESULT: firmware hard-frozen, no delayed code path, D11 obj still unlinked.**

Test.99 ran cleanly at 23:28:52–23:28:56 (boot -1, journal
`phase5/logs/test.99.journal`). "RP settings restored" — no host crash.

Pointer sample — **IDENTICAL across T+200/400/800ms**:
```
ctr[0x9d000]  = 0x000043b1    (static, matches test.89)
d11[0x58f08]  = 0x00000000    (D11 obj never linked — matches test.98)
ws [0x62ea8]  = 0x0009d0a4    (TCM ptr to static struct in BSS)
pd [0x62a14]  = 0x00058cf0    (vtable, matches test.93)
```
→ firmware is frozen by T+200ms with NO runtime change for the next 600ms.
Eliminates any "delayed DPC/ISR writes" hypothesis for these globals.

Console ring (256 bytes from 0x9ccc0): ChipCommon banner truncated. The
test.80 console captured the printed sequence:
ChipCommon → "wl_probe called" → "pciedngl_probe called" → **RTE banner**
(`RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz`)
then KATS fill — i.e. **freeze is AFTER the RTE banner print**, not at
"pciedngl_probe called" as earlier notes incorrectly stated.

### Offline disasm finding (2026-04-17, no hardware test)

`phase5/notes/offline_disasm_c_init.md` — full breakdown.

**`c_init()` lives at TCM 0x642fc.** Its literal pool (0x64540-0x6458c)
reveals the function's full call structure:

| Step | What c_init does | Observed? |
|------|------------------|-----------|
| 1 | Print RTE banner (format @ 0x6bae4, version @ 0x40c2f) | ✓ test.80 |
| 2 | Print `"c_init: add PCI device"` (@ 0x40c42) | ✗ |
| 3 | Store `*0x62a14 = 0x58cf0` (pciedngl_probe vtable) | ✓ test.99 |
| 4 | Print `"add WL device 0x%x"` (@ 0x40c61) | ✗ |
| 5 | Failure paths: `binddev failed` / `device open failed` / `netdev open failed` | ✗ none |

So execution definitely reaches step 3 (vtable populated). It does NOT
reach the failure paths. Freeze is between step 3 and the WL print, inside
either pciedngl_probe init or a subroutine called from c_init.

### Next decision (test.100) — three options

- (a) **Continue offline disasm** (free, no hardware test): trace c_init
  body 0x642fc–0x6453e (~322 bytes Thumb-2) to identify the exact BL after
  the vtable store. May pinpoint the failing subroutine without any
  hardware cycle.
- (b) **Wider/relocated console dump** to capture KATS region — earlier
  thought to surface post-RTE prints, but offline disasm shows step 4
  print only happens AFTER subroutine returns, so likely still empty.
- (c) **D11 BCMA wrapper reads** (Path B step 1) — requires chip.c bus-ops
  scaffolding; defer until offline disasm exhausts cheap progress.

**Recommend (a) first** — it is strictly free and may eliminate (b) and
narrow (c) to a specific D11 prereq.

**TEST.98 RESULT: step1 = TCM[0x58f08] = 0x00000000 → hang is in si_attach.**

Test.98 probe readings (from `phase5/logs/test.98.journal`, captured via
journalctl -b -1 after the module+script mismatch caused the stage0 log to be
labelled test.97 — raw partial preserved at `phase5/logs/test.98.stage0.partial`):

```
step1 = TCM[0x58f08] = 0x00000000 (D11_obj->field0x18)
step1 out of TCM range → D11_obj->field0x18 not set
(si_attach didn't run / didn't reach D11 obj init)
counter T+200ms = 0x000043b1 RUNNING
counter T+400ms = 0x000043b1 FROZEN (stays frozen through 2s timeout)
clean exit — no host crash
```

**Interpretation:**
- Firmware DOES start and runs some early code (counter reaches 0x43b1).
- Firmware freezes by T+400ms — a very early freeze, well before the D11 PHY
  wait loop at fn 0x1624c (which is several function levels deep inside
  si_attach's D11 bring-up).
- The D11 object pointer at `*0x58f08` is NEVER populated, which means the
  D11 section of si_attach hasn't reached the point where it links its
  object into that global.
- Previous hypothesis — "hang in fn 0x16f60 AHB read" — is INCORRECT; the
  pointer-chain cannot be walked because its root entry is still 0.

**Revised root cause hypothesis:** si_attach cannot bring the D11 core up at
all. A prerequisite (reset/enable/clock/power/interrupt-routing) is not in
the state si_attach expects. Per GitHub issue #11 recommendation #3.

**Pivot: Path B — D11 core prerequisite checks (phase5_progress.md).**

### Revised interpretation (advisor input + test.89 context)

test.89 proved firmware actually freezes at T+12ms — not at T+200–400ms.
The counter at 0x9d000 is a static constant (0x43b1) written exactly once
by fn 0x673cc, not a running tick. Sequence is:

```
T+0ms:  ctr = 0                        (ARM released)
T+2ms:  ctr = 0x58c8c                  (intermediate write)
T+12ms: ctr = 0x43b1 + console init    (fn 0x673cc stores static; firmware
                                        hangs at this exact point)
T+12ms onward: nothing changes         (sharedram never writes)
```

Therefore:
- test.98 reading `*0x58f08 = 0` at T+200ms was taken ~188ms AFTER the real
  freeze. It is consistent with "hang is before D11 obj linkage" but DOES
  NOT pinpoint the hang to D11 init specifically.
- The proven hang location from earlier tests is
  `pciedngl_probe → 0x67358 → 0x670d8 → deep init`; the fn 0x16f60 / fn
  0x1624c chain was called-graph analysis, not execution evidence.
- Jumping straight to D11 BCMA wrapper reads is premature — we need better
  hang localisation first.

### test.99 plan — console ring + multi-timepoint pointer sampling

Goal: narrow the hang location using CHEAP, READ-ONLY probes before
committing to D11 BCMA wrapper reads (which add bus-ops scaffolding and
have a bigger blast radius if anything goes wrong).

Probes (stage0, all read-only BAR2 accesses):

1. **Console ring dump at T+400ms** (highest-signal probe).
   - Read 256 bytes of TCM starting at the console-text base. Decode as ASCII
     to text on the host side (skip unprintable bytes). If firmware printed
     an ASSERT, a function-entry trace, or any identifiable string past
     "pciedngl_probe called", hang location narrows to that call.
   - Base address: locate via `console_ptr[0x9cc5c]` — when firmware is
     running this holds a TCM pointer (e.g. 0x8009ccbe → text at 0x9ccbe).
     Walk back from there to the ring start if needed. (Test.94 already
     identified 0x9CCC0–0x9CDD8 as decoded console strings.)

2. **Multi-timepoint TCM-pointer sampling** at T+20ms, T+200ms, T+400ms,
   T+800ms (T+20ms is the first sample AFTER firmware freezes):
   - `*0x9d000` — the 0x43b1 static (sanity check freeze detection works).
   - `*0x58f08` — D11 obj `field0x18` (was 0 at T+200ms).
   - `*0x62ea8` — wait-struct pointer (was garbage/uninit in test.97).
   - `*0x62a14` — global seen in fn 0x2208 analysis (used by
     `pciedngl_probe` path).
   - If all four are identical across all timepoints → firmware is hard-
     frozen after T+12ms and none of these globals got populated.
   - If any change at T+200/400/800 → firmware has SOME delayed execution
     path (e.g. interrupt-context code, DPC) we haven't accounted for.

3. **Sharedram + fw_init re-check** at the same timepoints (already in the
   existing T+200ms scan; extend to finer granularity).

Implementation notes:
- Reuse existing stage=0 dispatch in `brcmf_pcie_exit_download_state()`.
- `brcmf_pcie_read_ram32()` is the safe TCM read path — reuse, don't write.
- Keep the re-mask loop structure intact (defeats 3s periodic events).
- NO chip.c bus-ops, NO D11 BCMA wrapper reads yet — push that to test.100
  if console + pointer sampling don't narrow the hang.

After test.99 reading:
- If console shows a text past "pciedngl_probe called" → hang is later than
  currently thought; analyse the printed text for the failing subsystem.
- If console is frozen at "pciedngl_probe called" and pointers unchanged →
  hang is in pciedngl_probe BEFORE any subsystem logs → proceed to test.100
  with D11 BCMA wrapper reads (Path B step 1).
- If pointers change between T+20 and T+800 → delayed code path exists;
  characterise which pointer moves and when.

### Files modified / state snapshot
- `PLAN.md` — refactored to phase-level view; Current Status updated for test.98.
- `phase5/notes/phase5_progress.md` — Path B section added; current state block
  updated with test.98 result.
- `phase5/logs/test.98.journal` — full kernel log for test.98 run (NEW).
- `phase5/logs/test.98.stage0.partial` — partial stage0 log (header only before
  the 23:02 shutdown; kept for provenance, not for analysis).
- `phase5/logs/test.97.stage0` — restored to pre-test.98 clean state.
- `phase5/work/drivers/.../pcie.c` — still has test.98 probes (pointer-chain
  reads). Needs rewrite for test.99 D11 wrapper reads before next run.
- `phase5/work/test-staged-reset.sh` — still labelled test.97. Needs update to
  test.99 labels + LOG filename before next run.

## test.96 RESULT: CRASHED after 6 words — HANG CONFIRMED at fn 0x1624c via binary analysis

**test.96 ran in boot -1. CRASHED after only 6 code words (0x5200-0x5214). No RP restore.**
**PIVOT: Used firmware binary directly — 6 TCM words matched binary exactly → binary == TCM image.**

**fn 0x5250 disassembled from binary = nvram_get() — NOT the hang:**
```
5250: push {r4, r5, r6, lr}
5252: r4 = r0 (NVRAM buffer), r6 = r1 (key string)
5256: cmp r1, #0; beq 0x529c     ; if key==NULL, return NULL
525c: bl 0x82e                   ; strlen(key) → r5
5292: r0 = r6; b.w 0x87d4        ; tail call → another nvram lookup
```
Simple NVRAM key string lookup. NOT a hardware polling loop. NOT the hang.

**Vtable data found in firmware binary:**
```
PCIe2 vtable (at 0x58c9c):
  [0x58c9c] = 0x1e91 → fn 0x1E90 (vtable[0])
  [0x58ca0] = 0x1c75 → fn 0x1C74 (vtable[1]) ← CALL 2

D11 vtable (at 0x58f1c):
  [0x58f1c] = 0x67615 → fn 0x67614 (vtable[0])
  [0x58f20] = 0x11649 → fn 0x11648 (vtable[1]) ← CALL 3
```

**fn 0x1C74 (Call 2 = PCIe2_obj->vtable[1]) — NOT the hang:**
```
1c74: push {r4, lr}
1c76: r4 = [r0, #24]     ; load sub-object
1c7c: bl 0xa30            ; printf
1c80: r3 = [r4, #24]     ; nested struct
1c86: r2 = [r3, #36]; r2 |= 0x100; [r3, #36] = r2  ; set bit 8
1c8c: pop {r4, pc}        ; return
```
Trivial: sets bit 8 in BSS struct field, returns 0. NOT the hang.

**fn 0x11648 (Call 3 = D11_obj->vtable[1]) → leads to hang:**
```
1166e: r0 = [r4, #8]
11670: bl 0x18ffc        ← D11 init → eventually hangs
1167e: bl 0x1429c        ; stub returning 0
11682: pop {r2, r3, r4, pc}
```

**fn 0x18ffc (D11 init, called from Call 3) → hang chain:**
```
19024: ldrb r5, [r4, #0xac]  ; init flag
19028: cbz r5, 0x1904e        ; if flag==0: full init path
1904e: bl 0x16f60             ← FIRST D11 SETUP CALL (if first-time init)
19054: bl 0x14bf8
...
1908e: bl 0x17ed4             ; (this fn sets field0xac=1 — marks init done)
```
Flag at [r4+0xac] is 0 on first call → takes full init path starting at 0x16f60.
fn 0x17ed4 (sets init flag) is NEVER REACHED because hang happens before it.

**fn 0x16f60 (first D11 setup) → calls PHY read/write loop:**
- Copies 5 PHY register offsets from 0x4aff8: {0x005e, 0x0060, 0x0062, 0x0078, 0x00d4}
- Runs 5-iteration loop calling fn 0x16476 (PHY read) then fn 0x16d00 (PHY write)
- fn 0x16476: `mov.w r2, #0x10000; b.w 0x1624c` → enters wait loop

**fn 0x1624c = CONFIRMED HANG LOCATION (hardware PHY completion wait loop):**
```
1624c: push {r3, r4, r5, lr}
1624e: r5 = *(0x16298) = 0x62ea8  ; global wait-struct pointer

[SETUP:]
16252: r3 = *0x62ea8               ; wait struct ptr
16258: r3->field24 = 1             ; set "in progress"
1625c: r3->field28 = 0             ; clear completion flag
1625e: b.n 0x16286

[WAIT CHECK LOOP:]
16286: r3 = *0x62ea8
16288: r2 = r3->field20            ; status flag
1628a: cmp r2, #1
1628c: bne → EXIT                  ; if field20 != 1: exit (cancelled)
1628e: r3 = r3->field28            ; completion flag
16290: cmp r3, #0
16292: beq → LOOP (0x16286)        ; if field28==0: keep waiting ← INFINITE LOOP HERE
16294: pop {r3, r4, r5, pc}        ; return when field28 != 0
```
**HANGS WHILE: field20==1 AND field28==0**
**EXIT WHEN: field20!=1 (cancelled) OR field28!=0 (D11 PHY operation complete)**
This is a semaphore/event wait. field28 must be set by D11 PHY completion ISR.
**If D11 ISR never fires → field28 stays 0 → infinite loop.**

Root cause: D11 core not powered/clocked, or its interrupt not routed, so ISR never fires.
Global 0x62ea8 is a wait-struct used by 40+ locations in firmware.

Log: phase5/logs/test.96.journal (only 6 code words captured before crash)

## test.94 RESULT: SURVIVED (vtable read), CRASHED in STACK-LOW at word 154

**test.94 ran in boot -1. Module survived vtable dump, crashed at word 154/192 of STACK-LOW.**
**VTABLE: VT[0x58cf4] = 0x1FC3 → hang function is at 0x1FC2 (Thumb). CONFIRMED.**

**Key findings from VTABLE dump (0x58CD0-0x58D40):**
- VT[0x58cd4] = 0x00058c9c (nested vtable/struct ptr)
- VT[0x58cd8] = 0x00004999 (function at 0x4998)
- VT[0x58cdc] = 0x0009664c (BSS data ptr)
- **VT[0x58cf4] = 0x00001FC3** → Call 1 function (blx r3 at 0x644dc) = 0x1FC2 (Thumb) ← HANG CANDIDATE
- VT[0x58cf8] = 0x00001FB5 → vtable[+8] fn at 0x1FB4
- VT[0x58cfc] = 0x00001F79 → vtable[+12] fn at 0x1F78
- VT[0x58d24] = 0x00000001, VT[0x58d28..0x58d3c] = small fn pointers (0x4167C-0x416E3)

**Disassembly of 0x1FC2 (from arm-none-eabi-objdump on test.87 bytes):**
```
1fc2:  mov  r2, r1
1fc4:  ldr  r1, [r0, #24]  ; r1 = obj->si_ptr (field+0x18)
1fc6:  mov  r3, r0          ; r3 = obj
1fc8:  ldr  r0, [r1, #20]  ; r0 = si_ptr->dev (field+0x14)
1fca:  mov  r1, r3          ; r1 = obj (restore)
1fcc:  b.w  0x2208          ; TAIL CALL → 0x2208
```
→ 0x1FC2 is a TRAMPOLINE, not the actual hang. Rearranges args and tail calls to 0x2208.

**0x1FB4 (vtable[+8]):** identical trampoline → b.w 0x235C
**0x1F78 (vtable[+12]):** real function, calls 0x2E70 and 0x7DC4

**Analysis of 0x2208 (the REAL init function):**
```
push.w {r0,r1,r4,r5,r6,r7,r8,lr}   ; 8 regs = 32 bytes stack frame
r7 = *0x232C = 0x00062A14           ; global state ptr
r4=arg0(obj), r6=arg1, r5=arg2
r3 = *0x62A14 = 0x58CF0             ; vtable/state ptr (from test.93)
if (r3 & 2): optional debug print
if r6==0 || r5==0: error path
...
r8 = 0
bl 0x1FD0           ; allocate 76-byte struct (malloc via 0x7D60)
obj->field12 = result
if (alloc failed): error path
r0 = *0x62A14 & 0x10                ; 0x58CF0 & 0x10 = 0x10 (SET!)
if bit4 NOT set: return early (0x231C)
r1 = *0x2350 (timer priority value)
r0 = 0
bl 0x5250           ; register timer/callback
if (r0 == 0): success path:
    r0 = *0x237c = 0x00000000 (NULL!)
    r6 = 0
    b.w 0x848       ; TAIL CALL → 0x848 = strcmp (C library, NOT hang — CONFIRMED test.95)
```

**0x1FD0 (struct constructor called by 0x2208):**
- mallocs 76 bytes via 0x7D60
- memsets to 0 via 0x91C
- field52 = 0x740 = 1856, field60 = 0x3E8 = 1000, field64 = 28, field68 = 12, field72 = 4
- These look like timer/retry parameters (period_ms, timeout_ms, max_retry)

**STACK-LOW findings (0x9C400-0x9CDFC, crashed at 0x9CDFC):**
- 0x9C400-0x9CC54: ALL STAK fill (0x5354414b) — 0x1454 bytes = 5.2KB unused
- 0x9CC58-0x9CDFC: console ring buffer + BSS data (NOT stack frames)
  - 0x9CC5C = console write ptr (0x8009CCBE)
  - 0x9CCC0-0x9CDD8 = decoded console strings
  - 0x9CC88 = 0x000475B5 (ODD → Thumb fn ptr at 0x475B4 in struct)
- Stack frames NOT yet read (need 0x9CE00-0x9D000 or higher)
- Crash at ~3.25s total (exceeding ~3s PCIe crash window)

## test.95 RESULT: CLEAN EXIT — 0x840-0xB40 ALL C RUNTIME LIBRARY

**test.95 ran in boot -2 (and boot -1). Both SURVIVED with "TIMEOUT — FW silent for 2s — clean exit".**
**CODE DUMP COMPLETE: 192 words at 0x840-0xB40 disassembled (test95_disasm.txt).**

**CRITICAL CORRECTION: 0x848 is NOT a hang site — it is the loop body of strcmp.**
The annotation "b.w 0x848 = likely actual hang location" was WRONG.

**Functions found in 0x840-0xB40:**
- 0x840-0x87a: `strcmp` — entry at 0x840 (b.n 0x848), loop at 0x842-0x856, exit at 0x858-0x87a
- 0x87c-0x916: `strtol`/`strtoul` — whitespace skip, sign handling, 0x prefix, base conversion
- 0x91c-0x968: `memset` — 4-byte aligned stores + byte tail
- 0x96a-0xa2e: `memcpy` — LDMIA/STMIA 32-byte blocks, `tbb` jump table
- 0xa30-0xaaa: console printf — 520-byte stack buffer, calls 0xfd8/0x7c8/0x5ac/0x1848
- 0xabc-0xafa: callback dispatcher — 5-entry loop, `blx r3` dispatch with flag masking
- 0xb04-0xb16: wrapper loading globals for 0xabc
- 0xb18-0xb3f: heap free — adjusts accounting, walks linked list

**0xa4c was wrongly annotated** — it is in the MIDDLE of console printf at 0xa30, not a cleanup fn.

**Call chain from 0x2208:**
  bl 0x5250 (timer/callback reg) → succeeds → b.w 0x848 (tail call into strcmp)
  strcmp completes in microseconds. HANG IS ELSEWHERE.

**si_attach disasm (test91_disasm.txt, 0x64400-0x64ab8):**
- Function at 0x644??-0x64536: contains 3 vtable dispatches
  - Call 1 (0x644dc): *(*(0x62a14)+4) — obj vtable ptr at offset 0 → vtable[1]
  - Call 2 (0x644fc): r6=0x58cc4, ldr r3,[r6,#16] → vtable ptr at obj+16 → vtable[1]  
  - Call 3 (0x6451a): r7=0x58ef0, ldr r3,[r7,#16] → vtable ptr at obj+16 → vtable[1]
- si_attach at 0x64590: EROM-parsing loop, calls 0x2704 (EROM parser) for each core

## test.97 RESULT: fn 0x1624c never ran — hang is earlier
(See full analysis in "Current state" section above. Journal: phase5/logs/test.97.journal)

## test.98 PLAN: Pointer-chain reads to confirm D11 bus hang at fn 0x16f7a

**Goal:** Walk pointer chain at T+200ms to find hw_base_ptr and determine if it's a hardware addr.
Chain: TCM[0x58f08] → +8 → +0x10 → +0x88 → check if ≥ 0x18000000.
Also: stack probe 0x9FE00-0x9FF00 for LR=0x19054 (fn0x18ffc→fn0x16f60) and LR=0x11674.

**Expected results:**
- If step4 >= 0x18000000 → D11 bus hang confirmed. Next: pre-enable D11 core.
- If step4 == 0 → hang even earlier; need to trace si_attach D11 core init.
- If step1 == 0 → D11_obj->field0x18 not set; si_attach didn't initialize D11 obj.

## Run test.98 (to be built):
  cd /home/kimptoc/bcm4360-re/phase5/work && make && sudo ./test-staged-reset.sh 0

## test.93 RESULT: SURVIVED (both runs) — vtable pointer decoded, stack top is NVRAM

**test.93 ran twice (boot -2 at 12:02, boot -1 at 12:10), BOTH SURVIVED.**
Both showed "TIMEOUT — FW silent for 2s — clean exit" and "RP settings restored".

**Key findings from D2 (DATA-62A14) dump:**
- D2[0x62a14] = 0x00058cf0 → vtable pointer for Call 1 (blx r3 at 0x644dc)
- Vtable is at TCM[0x58cf0]; entry [+4] = TCM[0x58cf4] = function pointer for Call 1
- D2[0x62994] = 0x18000000 (ChipCommon base — confirms si_t struct location)
- D2[0x62ab0] = 0x58680001 (chipcaps — matches si_t from console output)
- D2[0x62ad4] = 0x00004360 (chip_id = BCM4360 ✓)
- D2[0x62ad8] = 0x00000003 (chip_rev = 3 ✓)
- D2[0x62ae0] = 0x00009a4d (chipst ✓)

**Key findings from SK (STACK-TOP) dump [0x9F800-0xA000]:**
- 0x9FF1C–0xA0000: NVRAM data ("sromrev=11\0boardtype=0x0552\0boardrev=0x1101\0...")
- 0x9F800–0x9FF1B: random/uninitialized data — NO Thumb LR values in TCM code range
- CONCLUSION: 0x9F800–0xA000 is NOT active stack. Active frames are near STAK fill at 0x9C400.

**What remains unknown:**
- TCM[0x58cf4] = ??? (the actual function being called — not yet read)
- Stack LR values (to confirm call depth and which vtable call hangs)

Log: phase5/logs/test.93.journal

## test.92 RESULT: SURVIVED — STAK fill confirmed above 0x9BC00; EROM parser analyzed

**test.92 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**Stack dump 0x9BC00-0x9C400: ENTIRELY STAK (0x5354414b)**
- Active stack frames are ABOVE 0x9C400
- Stack grows down from 0xA0000; estimated SP ~0x9F800
  (860-byte zeroed struct in 0x670d8 frame + si_attach 60-byte frame + others)

**EROM parser function at 0x2704 (0x2600-0x2900 dumped):**
- Simple loop: loads EROM entries sequentially from TCM, returns when match found
- r1 = &ptr, r2 = mask (or 0), r3 = match value
- NO infinite loops, NO hardware register reads
- CANNOT be the hang location

**Function structure at 0x27ec (core registration, vtable call):**
- `blx r3` at 0x2816 calls a vtable function (potential hang candidate)
- But this is called by si_attach (0x64590) during core enumeration

**Key insight: Vtable calls are in a function BEFORE si_attach in TCM:**
- From test.91 dump (0x64400-0x6458c area):
  - `bl 0x63b38` with r1=0x83c → looks up PCIe2 core object → r6
  - `bl 0x63b38` with r1=0x812 → looks up D11/MAC core object → r7
  - If both found: three vtable calls follow:
    - Call 1 (0x644dc): via [0x62a14][4], args=(PCIe2_obj, D11_obj)
    - Call 2 (0x644fc): PCIe2_obj->vtable[1](), if Call 1 succeeds
    - Call 3 (0x6451a): D11_obj->vtable[1](), if Call 2 succeeds

**test.92 hypothesis: hang is in one of the three vtable calls (PCIe2 or D11 core init)**

Log: phase5/logs/test.92.journal
EROM disasm: phase5/analysis/test92_erom_disasm.txt

## test.90 RESULT: SURVIVED — 0x670d8 disassembled; 0x64590 is next hang candidate

**test.90 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**function 0x670d8 fully disassembled (1344 bytes, 0x66e00-0x67340):**
- Entry: `stmdb sp!, {r0-r9, sl, lr}` (pushes 12 registers)
- Loads 7 args (3 from regs r0/r1/r2/r3, 4 from stack [sp+48..+56])
- memset: zeroes 860 bytes (0x35c) from r4 (the init struct)
- Stores initial values into struct offsets
- Calls 0x66ef4 (tiny function: returns 1 always) — never hangs
- At 0x67156: `mov.w r9, #0x18000000` (ChipCommon base!)
- At 0x6715c: `ldr.w r1, [r9]` = reads ChipCommon chip_id register
- Extracts chip_id, numcores, etc. from register
- **At 0x67190: `bl 0x64590` — FIRST DEEP CALL, likely hang point**
  - Args: r0=struct_ptr, r1=0x18000000 (ChipCommon), r2=r7
  - This is likely `si_attach` or `si_create` (silicon backplane init)
- After return: checks [struct+0xd0] — if NULL, error exit
- If non-NULL: calls 0x66fc4 (function in our dump, enumerates cores)
  - 0x66fc4 loops through [struct+0xd0] cores calling 0x99ac, 0x9964
  - Returns 1 (success) after loop

**call chain established:**
- pciedngl_probe → 0x67358 → 0x672e4 (wrapper) → 0x670d8 → 0x64590

**0x64590 not in dump (below 0x66e00) — MUST DUMP NEXT**
**0x66fc4 analyzed: core-enumeration loop, returns 1 on success**

Disassembly: phase5/analysis/test90_disassembly.txt
Log: phase5/logs/test.90.journal

## test.89 RESULT: SURVIVED — 0x43b1 is STATIC constant (stored once, not incremented)

**test.89 ran in boot -1. Key findings from fast-sampling:**
1. T+0ms: ctr=0x00000000 (ARM just released)
2. T+2ms: ctr=0x00058c8c (CHANGED — firmware running, some intermediate value)
3. T+10ms: ctr=0x00058c8c (held for 8ms)
4. T+12ms: ctr=0x000043b1 AND cons=0x8009ccbe (BOTH changed simultaneously)
5. T+20ms+: ctr=0x000043b1 FROZEN, cons frozen, sharedram=0xffc70038 NEVER changes

**RESOLVED: 0x43b1 IS a static constant, NOT a counter**
- Function at 0x673cc returns MOVW R0, #0x43b1 → firmware stores it to 0x9d000
- Previous "WFI-disproof" based on frozen counter was INVALID for values at T+200ms
- BUT firmware IS genuinely hung: sharedram NEVER changes (even at 2s+)
  - PCI-CDC firmware WOULD write sharedram on successful init
  - Never changing = TRUE HANG, not WFI idle

**TIMELINE reconstructed:**
- T+0ms: ARM released, TCM[0x9d000]=0
- T+2ms: firmware stored 0x58c8c to 0x9d000 (some intermediate init value)
- T+10ms: still 0x58c8c (firmware executing init code)
- T+12ms: firmware stored 0x43b1 to 0x9d000 (function 0x673cc result) AND initialized console
- T+12ms+: EVERYTHING FROZEN — firmware hung at this exact point
  - Console write ptr = 0x8009ccbe = TCM[0x9ccbe] (same as all previous tests)
  - Last message = "pciedngl_probe called" (same as test.78-80 decode)
  - Hang occurs inside pciedngl_probe → 0x67358 (TARGET 1) → 0x670d8 (deep init)

**NEXT: disassemble 0x670d8** — the only unexamined function in the call chain
Log: phase5/logs/test.89.journal

## test.91 RESULT: CRASHED at word 431 — partial si_attach disassembly obtained

**Crash cause:** Unmasked 1280-word code dump loop; at ~7ms/word, 431 × 7ms ≈ 3s hit PCIe crash window.

**Partial disassembly (431 words, 0x64400-0x64ab8) — key findings:**
- **0x64590 (si_attach):** reads ChipCommon+0xfc = EROM pointer register
- Immediately branches to EROM parse loop, calls fn at **0x2704** (EROM entry reader)
- **Vtable dispatch calls at 0x644dc and 0x644fc** (`blx r3`) — these init individual backplane cores
  → Most likely hang points: one core's init fn reads backplane registers for a powered-off core

**Stack location corrected:** STAK marker at 0x9BF00 (from test.88) → active frames near 0x9BC00.

Log: phase5/logs/test.91.journal
Dump: phase5/analysis/test91_dump.txt (431 words: 0x64400-0x64ab8)

## test.88 RESULT: CRASHED cleanup — but all data obtained

**test.88 ran in boot -1 (also partial in boot -2). Key findings:**
1. All three call targets disassembled — NO infinite loops, CPSID, or WFI in any
2. TARGET 1 (0x67358): alloc + calls 0x670d8 (deep init) — most likely hang location
3. TARGET 2 (0x64248): struct allocator (0x4c bytes), returns — clean
4. TARGET 3 (0x63C24): registration function, returns 0 — clean
5. **CRITICAL: Function at 0x673cc returns constant 0x43b1** — same value as "frozen counter"
6. Stack scan 0x9F000-0x9FFF8: mostly zeros, no dense return address cluster
7. "STAK" marker at 0x9bf00 — stack region may be near 0x9c000
8. Counter: T+200ms=0x43b1 (RUNNING), T+400ms=FROZEN
9. CRASHED during cleanup (no RP restore messages)

Full disassembly: phase5/analysis/test88_disassembly.txt

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL → writing during init CRASHES ✗ (test.71/74)
- Firmware prints: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75-80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- select_core after firmware starts → CRASH ✗ (test.66/76 PCIe2, test.86 ARM CR4)
- Core switching after FW start CONFIRMED LETHAL across ALL core types ✗ (test.66/76/86)
- WFI theory DEAD: frozen counter = TRUE HANG, not WFI idle (WFI keeps timers running) ✗
  UPDATE: counter at 0x9d000 is STATIC value (not a counter) — set once to 0x43b1
  BUT: sharedram NEVER changes = firmware NEVER completes init = GENUINE HANG ✓
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- Counter freezes at 0x43b1 between T+200ms and T+400ms — hang is VERY early ✓ (test.87)
- TCM top = 0xA0000 (640KB), stack grows down from there ✓ (test.87 TCB)
- pciedngl_probe calls into 0x67358, 0x64248, 0x63C24 — hang is inside one of these ✓ (test.87 disasm)
- All 3 call targets have NO infinite loops, CPSID, or WFI ✓ (test.88 disasm)
- TARGET 1 (0x67358) calls 0x670d8 (deep init) — most likely hang location ✓ (test.88)
- 0x670d8 calls si_attach (0x64590) which dispatches vtable calls ✓ (test.90)
- si_attach vtable fn at 0x1FC2 = TRAMPOLINE → tail calls 0x2208 ✓ (test.94 disasm)
- 0x2208 allocates struct, calls 0x5250, then tail calls 0x848 ✓ (test.94 disasm)
- 0x848 = strcmp (C runtime), NOT the hang ✓ (test.95 disasm)
- fn 0x5250 = nvram_get() (NVRAM key lookup), NOT the hang ✓ (test.96 binary disasm)
- Call 2 (fn 0x1C74) = trivial bit-set, returns 0, NOT the hang ✓ (test.96 binary disasm)
- Call 3 (fn 0x11648) → fn 0x18ffc → fn 0x16f60 → fn 0x1624c = CONFIRMED HANG ✓ (test.96 binary analysis)
- fn 0x1624c = hardware PHY completion wait loop at global 0x62ea8 ✓
- Loop spins while (*0x62ea8)->field20==1 AND field28==0 ✓
- field28 set by D11 PHY ISR — ISR never fires → infinite loop ✓ (hypothesis)
- D11 PHY register offsets in loop: 0x005e, 0x0060, 0x0062, 0x0078, 0x00d4 (from 0x4aff8) ✓
- Firmware binary matches TCM image exactly (6 words verified) — safe for offline disassembly ✓
- fn 0x1624c NEVER RAN at T+200ms — wait struct fields all garbage (uninitialized) ✓ (test.97)
- fn 0x16476 tail-calls fn 0x162fc (NOT fn 0x1624c) ✓ (corrected from binary)
- fn 0x16f60 @ 0x16f7a does hardware read BEFORE calling fn 0x16476 — AHB hang candidate ✓
- Stack frames are near 0x9FE40 (not 0x9CE00 which is console ring buffer) ✓ (test.97)

## Console text decoded (test.78/79/80/82/83/84 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (static value, set once at T+12ms then firmware freezes)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.95.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.85: CRASHED T+18-20s — STATUS/DevSta cleared, firmware STILL hung; STATUS theory DEAD
- test.86: CRASHED T+2s — ARM core switch (select_core) crashed immediately; core switch LETHAL
- test.87: SURVIVED — counter froze T+200-400ms at 0x43b1; pciedngl_probe disassembled; code dumps obtained
- test.88: CRASHED cleanup — all 3 targets disassembled; NO loops/CPSID/WFI; 0x673cc returns 0x43b1 constant; 0x670d8 is next suspect
- test.89: SURVIVED — 0x43b1 is STATIC (stored once at T+12ms); WFI-disproof RESOLVED; sharedram confirms TRUE HANG
- test.90: SURVIVED — 0x670d8 fully disassembled; calls si_attach (0x64590) at 0x67190; NO loops
- test.91: CRASHED at word 431 — partial si_attach (0x64590) dump; vtable dispatch at 0x644dc
- test.92: SURVIVED — STAK extends 0x9BC00-0x9C400; EROM parser at 0x2704 is benign
- test.93: SURVIVED (×2) — D2[0x62a14]=0x58CF0 (vtable ptr); sk[0x9F800]=NVRAM (not stack)
- test.94: SURVIVED vtable, CRASHED STACK-LOW at ~3.25s — VT[0x58cf4]=0x1FC3; 0x1FC2→0x2208→0x848
- test.95: SURVIVED — 0x840-0xB40 = C runtime (strcmp, strtol, memset, memcpy, printf); 0x848 = strcmp NOT hang
- test.96: CRASHED after 6 words — pivoted to firmware binary analysis; fn 0x1624c confirmed as hang location
- test.97: CRASHED (machine crash) — wait struct fields = garbage → fn 0x1624c never ran; hang is earlier; corrected: fn 0x16476 → fn 0x162fc (not fn 0x1624c directly)
