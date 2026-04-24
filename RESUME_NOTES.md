# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-24 19:10 BST, POST-T286-STATIC + T287-CODE — **T286 static wall reached: scheduler ctx at 0x62A98 is zero-init BSS, pending-events chain is runtime-populated. Pivoted to T287 runtime probe.** T287 reads 7 scheduler ctx fields (`+0x10/+0x18/+0x88/+0x8c/+0x168/+0x254/+0x258`) at every T284/T285 stage. If `+0x258 = 0x18000000` → T283's chipcommon hypothesis verified. If `+0x88` reveals an MMIO base, we know which core owns the pending-events word. Build clean. Fire pending clean substrate — last fire (T285) was null-fire at test.125 T268 pattern; need solid cold cycle before T287.)

---

## PRE-TEST.287 (2026-04-24 19:10 BST — **Runtime scheduler-ctx probe. Read TCM[0x62A98 + {0x10,0x18,0x88,0x8c,0x168,0x254,0x258}] at every T284/T285 stage. Resolves T286's static-trace wall.**)

### Hypothesis

T283 static analysis resolved:
- `scheduler_ctx+0x258 = [something]`, copied to `+0x254`.
- `[scheduler_ctx+0x254]+0x100` = BIT_alloc's register read = strongly inferred to be CHIPCOMMON INTSTATUS (0x18000100).
- `scheduler_ctx+0x88 = [scheduler_ctx+0x8c]`, copied by class-0 thunk.

T286 confirmed the scheduler ctx is zero-init BSS at 0x62A98 statically, so we can only resolve the pointer values at RUNTIME.

T287 reads the actual runtime values. Expected discrimination:

| `+0x258` value | `+0x88` value | `+0x168` value | Reading |
|---|---|---|---|
| `0x18000000` (CHIPCOMMON) | `0x18000xxx` or similar | Any | T283 hypothesis fully verified. Pending-events word is at `[+0x88]+0x168` = a chipcommon offset. |
| `0x18000000` | `0x18100000` (PCIE2) or other | Any | Bit-pool is chipcommon but pending-events is a different core. Tells us which. |
| Not MMIO (TCM or 0) | Any | `0x` pattern non-zero | pending-events may be TCM-backed. Host can directly write it. |
| All zeros | All zeros | All zeros | Scheduler ctx hasn't been initialized (class-0 thunk didn't run or crashed silently). Would be unexpected given T255 shows callbacks registered. |
| `+0x18` non-zero | — | — | dispatch_ctx_ptr populated at runtime — T286's chain can be walked further via TCM reads at the dumped pointer values. |

### Design

Code landed. New param `bcm4360_test287_sched_ctx_read`. Helper macro `BCM4360_T287_READ_SCHED(tag)` reads 7 specific offsets in one pr_emerg line. Piggybacks on 5 T284/T285 sites + 4 T278 stage hooks (total 9 readback points).

All reads are `brcmf_pcie_read_ram32` (BAR2 direct TCM access) — independent of BAR0_WINDOW state. No core-switching needed.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test285_chipcommon_read=1 \
    bcm4360_test287_sched_ctx_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.287.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.287.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.287.journalctl.txt
```

All previous readback infrastructure enabled (T284 MBM + T285 CC registers + T287 sched ctx fields) for aligned time-series across the full fw init.

### Substrate note

**Previous fire (T285) was null at T268 pattern.** Before T287 fire, user should do a full cold cycle (shutdown, unplug, wait ≥5 min, SMC reset, plug, boot). T268 pattern suggests substrate drift even despite SMC reset when power-off is short.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test287_sched_ctx_read`; T287 pr_emerg string present.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Substrate**: **longer cold cycle required** (≥5 min power-off per T268/T285 pattern).
6. **Fire log**: all previous readback + new T287 per-stage row.

### Outcome interpretation notes

- If T287 reveals `+0x258 = 0x18000000`, advisor's T283 hypothesis is fully confirmed and T289 (write chipcommon to wake fw) becomes the direct next step.
- If `+0x258` is something else, T283's chipcommon-INTSTATUS claim needs revision — we'd expand T287 to dump more offsets or trace the allocator path.

### Fire expectations

Same envelope as T284/T285 fires (~115-145 s to late-ladder wedge). T287 data lands in first ~3 s after set_active. 9 readback stages × 7 values = 63 data points per fire; all in journal regardless of late-ladder wedge.

---

## POST-TEST.285 (2026-04-24 18:23 BST fire, boot -1 — **NULL FIRE. Host wedged at `test.125: after reset_device return`, ~20 s into insmod — BEFORE any T285/T284 code executes. T268-pattern host-side wedge recurrence. No chipcommon data captured. Retry after longer cold-cycle.**)

### Timeline (from `phase5/logs/test.285.journalctl.txt`, boot -1)

- `18:23:34` insmod starts, `test.188: module_init entry`
- `18:23:36` `brcmf_pcie_register() entry` + `before pci_register_driver`
- `18:23:54` `test.125: buscore_reset entry, ci assigned` (~20 s into insmod, normal probe path)
- `18:23:55` **`test.125: after reset_device return`** — LAST MARKER
- [silent lockup; expected next marker `test.125: after reset, before get_raminfo` never fires]
- `18:23:55` boot ended (watchdog reboot)
- `18:39:10` boot 0 (user cold-cycled)

### What T285 DID NOT settle

- **Zero T285 data captured.** The probe block lives in `brcmf_pcie_download_fw_nvram`, which sits FAR after `buscore_reset`. We never got past buscore_reset → get_raminfo. No chipcommon INTSTATUS/INTMASK/0x168 values collected.
- **T284 MBM readbacks also not collected** for the same reason.

### What T285 DID observe (indirectly)

- **T268's pre-firmware wedge is REPRODUCIBLE**. The `test.125: after reset_device return → get_raminfo` window is a known host-side failure point. Previously observed 2026-04-24 01:33 (T268's fire). Today 2026-04-24 18:23 same marker pattern, same wedge.
- **Substrate was NOT fully clean despite cold cycle with SMC reset**. Boot -2 ran 16:26 → 18:20 (2 hours, likely system idle), then boot -1 started 18:22 (only ~2 min gap). Short power-off window may not have given chip sufficient cool-down. Prior reliable cold cycles in this project (T270-BASELINE, baseline-postcycle) may have had longer power-off durations.

### Code status

- **No T285 code changes required.** T285 code is correct; it just never ran.
- Build at commit `543eaa2` is still valid.
- Fire command unchanged.

### Next-test direction

**Option A (fastest, advisor-unneeded): immediate retry after longer cold cycle.**
- User performs ≥5 min full power-off (unplug preferred, per CLAUDE.md "full cold power cycle (shutdown + ≥60 s + SMC reset)") before retry.
- Re-verify substrate via lspci + lsmod before insmod.
- Fire the exact same T285+T284+T278+T277+T276 combo.
- If host wedges at same `test.125` point again, substrate is genuinely degraded and we escalate to the user.

**Option B: stop for the day; resume later with cooler chip.**
- Session has accumulated ~8 fires since 07:54 BST. Today's n-of-wedges reaches into double digits.
- Tomorrow's fresh chip likely reaches the T285 probe code.

**Option C: static work instead (no substrate cost).**
- Deep-trace wlc-probe r7 setup (the T286 candidate from T283). Would resolve fn@0x2309c's pending-events word absolute address without firing anything.
- Would produce additional info for T287 design even if T285 fires cleanly later.

### Post-fire checklist

- Journal captured: ✓ `phase5/logs/test.285.journalctl.txt` (1077 lines — truncated by early wedge).
- Run output captured: ✓ `phase5/logs/test.285.run.txt` (insmod start only — no "returned" timestamp).
- Null-fire recorded: ✓ this block.
- No KEY_FINDINGS updates needed (no new primary-source data).

---

## PRE-TEST.285 (2026-04-24 17:25 BST — **Chipcommon register read-only probe across T278 stages. Confirm/falsify T283's inference that fw's wake path is chipcommon-side. 3 targeted registers: INTSTATUS (0x100), INTMASK (0x104), 0x168.**)

### Hypothesis

T283 static disasm resolved:
- BIT_alloc reads chipcommon INTSTATUS at `0x18000100`.
- Scheduler ctx links to CHIPCOMMON MMIO base.
- Strong inference: fn@0x2309c's pending-events word is another chipcommon-side register, plausibly at `0x18000168`.

If correct, T285 observations will show:
- INTSTATUS with some bits set at/after set_active (fw has outstanding interrupt bits).
- INTMASK either open (bits 3/4 set = unmasked) or closed (explaining why fw doesn't wake).
- `0x168` matching pattern with INTSTATUS (if it's indeed the pending-events reg for fn@0x2309c).

### Outcome matrix (advisor-framed)

| INTSTATUS @set_active | INTMASK @set_active | 0x168 @set_active | Reading |
|---|---|---|---|
| Non-zero w/ bits 3/4 set | Non-zero w/ bits 3/4 set | Any | Trigger bits ARE set AND unmasked — fw should be wakeable. Something else gating (maybe node linkage timing). Narrow via T286. |
| Non-zero w/ bits 3/4 set | 0 (masked) | Any | **Chipcommon INTMASK is the gate.** T287 writes unmask there; high-value fix. |
| 0 or unrelated bits | Any | Any | Trigger bits NOT in chipcommon. T283 hypothesis wrong; different register entirely. T286 deep wlc-trace becomes next. |
| 0x168 reads != INTSTATUS pattern | — | — | 0x168 isn't the pending-events word. Narrows where it actually is. |
| 0x168 == INTSTATUS | — | — | 0x168 is a mirror/alias. Reading it is free information; not a new target. |

### Design (advisor-approved)

Code landed. Gated behind `bcm4360_test285_chipcommon_read=1`; requires T276+T277+T278+T284.

1. Window-safe helper macro `BCM4360_T285_READ_CC(tag)`:
   ```c
   save BAR0_WINDOW → select_core(CHIPCOMMON) → read 0x100/0x104/0x168 → restore BAR0_WINDOW
   ```
   All 4 operations are in-macro so no caller can forget the restore.
2. Piggybacks on 5 T284 MBM readback sites:
   - pre-write (pre-set_active)
   - post-write (pre-set_active)
   - post-set_active (CRITICAL)
   - post-T276-poll
   - post-T278-initial-dump
3. Plus 4 T278 stage hooks (t+500ms, t+5s, t+30s, t+90s) — the `BCM4360_T278_HOOK` macro extended to call T285 after T284.

Total: 9 chipcommon readback points per fire, each emitting `INTSTATUS / INTMASK / 0x168` plus a `saved_win` sanity value.

READ-ONLY. No writes anywhere. No state mutation.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test285_chipcommon_read=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.285.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.285.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.285.journalctl.txt
```

T284 stays enabled so MBM time-series + chipcommon time-series line up one-to-one. T279 intentionally OFF (would add MMIO noise; not the question this fire).

### Safety

- Read-only probe. 9 × 3 reads = 27 values. Each operation is microseconds.
- Window save/restore discipline inside macro protects other BAR0 accesses.
- Late-ladder wedge expected same as prior fires — T285 data lands in first ~3 s.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test285_chipcommon_read`; 1 T285 pr_emerg string present (all 9 stages use same format string).
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: needs fresh cold cycle (previous was for T284).
6. **Log attribution**: `saved_win` field in each T285 line = sanity (if it changes unexpectedly, the window restoration isn't working).

### Fire expectations

- Insmod + path to set_active: ~20 s
- T284+T285 reads across 9 stages: ~1 s total
- T238 ladder to wedge: ~90-120 s
- Total ~115-145 s before wedge

T285's diagnostic value lands in the first ~3 s after set_active. If the late-ladder wedge fires, all data is already in the journal.

---

## POST-TEST.284 (2026-04-24 16:16 BST fire, boot -1 — **Multi-finding result: MBM has non-zero default 0x318, pre-set_active writes also silently drop, set_active clears MBM to 0, write-locked at all tested timings. Reconciles with T241 (which was FAIL, not PASS as I'd misremembered). MBM at BAR0+0x4C is not writable on BCM4360 via the upstream-canonical helper.**)

### Timeline (from `phase5/logs/test.284.journalctl.txt`, boot -1)

- `16:16:36` insmod
- `16:16:46` insmod returned
- `16:17:59` chip_attach + fw download + FORCEHT complete (identical path to T278-T280)
- `16:17:59` **T284 pre-write (pre-set_active): `MAILBOXMASK=0x00000318 MAILBOXINT=0x00000000`** ← NON-ZERO default!
- `16:17:59` T284: "calling brcmf_pcie_intr_enable" marker
- `16:17:59` T284: "brcmf_pcie_intr_enable returned" marker (no mid-call wedge)
- `16:17:59` **T284 post-write (pre-set_active): `MAILBOXMASK=0x00000318`** ← unchanged; write of 0xFF0300 silently dropped
- `16:17:59` `brcmf_chip_set_active returned TRUE`
- `16:17:59` **T284 post-set_active: `MAILBOXMASK=0x00000000`** ← set_active cleared it
- `16:17:59` T276 2s poll: identical (si[+0x010]=0x9af88)
- `16:17:59` T284 post-T276-poll: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:17:59` T278 POST-POLL (full): 587 B (identical to T278)
- `16:17:59` T284 post-T278-initial-dump: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:17:59` T279 H2D probes: identical null (no fw response, console unchanged)
- `16:17:59 → 16:18:30` T238 ladder to t+90s with T284 stage readbacks:
  - `t+500ms`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+5s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+30s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
  - `t+90s`: `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`
- `16:26:06` boot 0 (cold-cycled by user)

### Reconciliation with T241 (2026-04-23 fire)

Grep of `phase5/logs/test.241.journalctl.txt` shows T241 observed:
- MAILBOXMASK baseline = `0x00000318` (pre-set_active)
- After write 0xDEADBEEF: readback 0x318 (write dropped)
- After write 0 to restore: readback 0x318 (write dropped)
- **RESULT: FAIL** (sentinel-match=0, baseline-zero=0, clear-zero=0)

**My earlier writeups (T280, PRE-TEST.284) claimed "T241 proved MBM writes work pre-set_active". That's WRONG.** T241 was FAIL — writes have been silently dropping at BAR0+0x4C since 2026-04-23. Today's T284 rediscovers that finding plus adds the post-set_active time-series.

Correcting the framing: MBM at BAR0+0x4C is **write-locked on BCM4360 across all tested timings** (pre-set_active T241/T284 FAIL; post-set_active T280 FAIL). 0x318 is a chip default (or set by some pre-attach code we haven't identified). `brcmf_chip_set_active` clears it to 0.

### What T284 settled (factually)

1. **MAILBOXMASK has a non-zero default `0x00000318` at pre-set_active** on a fresh BCM4360 boot. Not 0 as I'd repeatedly claimed.
2. **0x318 decode**: `FN0_0 (0x100) | FN0_1 (0x200) | bits 3+4 (0x018)`. Bits 3/4 may correspond to T273/T274's scheduler-callback flags (pciedngl_isr got flag=0x8 = bit 3; fn@0x1146C candidate = bit 4 = 0x010).
3. **Pre-set_active MBM writes silently fail** (T241 + T284). Register is write-locked even before ARM release.
4. **`brcmf_chip_set_active` clears MBM to 0.** ARM-release side effect. Persistent across all subsequent readbacks (6 post-set_active reads through t+90s all show 0).
5. **Post-set_active MBM writes also silently fail** (T280 + T284 confirm).
6. **Write mechanism (`brcmf_pcie_write_reg32` → `iowrite32` at BAR0+0x4C) is not broken** — it wrote H2D registers fine in T279 (those saw the writes land even if fw didn't respond). MBM specifically is the locked register.
7. **No T85/T96 markers in the T284 journal.** The pre-ARM-release MBM-write code at pcie.c:5411 DID NOT EXECUTE — it's in a code path the T238 early-exit bypasses. So our code never wrote MBM in this run; the 0x318 came from somewhere else (chip default, buscore_reset, or chip_attach internals).

### Decoded bit-level significance

- `0x318 = 0x008 | 0x010 | 0x100 | 0x200`
- Bit 3 (0x008): T274 said pciedngl_isr's scheduler flag is 0x8. Suggestive match.
- Bit 4 (0x010): fn@0x1146C candidate (next sequential bit). Suggestive match.
- Bit 8 (0x100): `BRCMF_PCIE_MB_INT_FN0_0` — HW interrupt for pciedngl_isr.
- Bit 9 (0x200): `BRCMF_PCIE_MB_INT_FN0_1` — HW interrupt for hostready/WLC.

**If bits 3/4 in HW MAILBOXMASK mirror the software scheduler flags, the default 0x318 has EXACTLY the bits needed to wake BOTH pciedngl_isr and fn@0x1146C.** set_active clearing the mask to 0 is what blocks fw from waking. The 0x318 default looks like a chip-level "proper" wake configuration.

### Critical next question

**What does `brcmf_chip_set_active` do that clears MBM, and can we either prevent it or restore MBM after?**

Static analysis angles:
- Trace `brcmf_chip_set_active` → likely writes to ARM CR4 CPUHALT bit → possibly triggers a PCIe2 core reset side-effect that clears MAILBOXMASK.
- Fw's own init code might write MBM back to 0x318 as part of hndrte_add_isr's per-class unmask thunk (T274 hypothesis). Our T284 readings show it doesn't — but maybe the fw's write target isn't BAR0+0x4C (which is the upstream-defined offset). Could be a backplane-side register.

Hardware test angles (next after static, if needed):
- T285: write MBM immediately post-set_active (but BEFORE T276 poll) to see if there's a brief window where writes land.
- T286: write MBM via buscore-prep-addr path (different access mechanism).
- T287: write a different register that might mirror into MBM (BAR0+0x24 INTMASK, chipcommon-side mailbox).

### What T284 did NOT settle

- **What writes 0x318 at boot.** Chip default vs pre-attach code. Need to grep pcie.c + chip.c for any pre-attach MBM writes.
- **Whether there's a writable mirror of MBM** (different BAR0 offset, or backplane register).
- **What specifically in `brcmf_chip_set_active` clears MBM.** Source disasm needed.

### Next-test direction (advisor required before committing)

Three candidates:
- **T283 (static blob disasm)**: was deferred for T284. Now more valuable: find fw's MBM-writer (or evidence that fw uses a different register entirely). Goal: identify the REAL mask register, if different from BAR0+0x4C.
- **T285 (very-early post-set_active write)**: insmod→set_active→IMMEDIATE MBM write before any further code runs. Tests whether clear-by-set_active is immediate or has a settle window.
- **T286 (alternative write path)**: try writing MBM via buscore_prep_addr access or through a different PCIE2 core selection. If the register is backplane-gated, switching backplane window might enable the write.

T283 is highest-info-per-cost (static, no substrate) and has a clear decision tree based on findings.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.284.journalctl.txt` (1450 lines).
- Run output captured: ✓ `phase5/logs/test.284.run.txt`.
- Outcome matrix resolved: ✓ **row 3** ("Resets to 0 at some readback point" — specifically at post-set_active).
- T241 reconciliation complete (corrected my earlier-framing error).
- Ready to commit + push + sync.

---

## PRE-TEST.284 (2026-04-24 16:05 BST — **Move `brcmf_pcie_intr_enable` call to BEFORE `brcmf_chip_set_active`. 8-point MBM readback tracks whether pre-set mask persists through fw init. Potential home-run single-fire test.**)

### Hypothesis

- T241 (pre-set_active): MBM round-trip PASS — write lands.
- T280 (post-set_active): MBM write silently drops — register unresponsive.
- Hypothesis: chip state during `brcmf_chip_set_active` transitions the register from writable to unwritable. A pre-set_active write may either (a) persist into fw runtime (home run — fw wakes), (b) get reset by fw's init (tells us WHEN it resets), or (c) be preserved but produce no wake (mask was not the whole gate; H2D probes next).

### Outcome matrix

| MBM persistence | Console advance past wr_idx=587 | Reading |
|---|---|---|
| Stays `0xFF0300` all 8 reads | **New log at t+500ms or earlier** | **HOME RUN.** Pre-set mask survives; fw wakes. Driver fix: move `brcmf_pcie_intr_enable` before `brcmf_chip_set_active`. |
| Stays `0xFF0300` | No new log | Mask survived but no latched bits to wake. T279 H2D probes will fire productively now — can run in same fire if both enabled. |
| Resets to 0 at some readback point | Any | **Diagnostic gold.** Pinpoints WHEN the reset happens (pre- or post-set_active timestamp). T283 static analysis follows to find the reset writer. |
| Mid-fire wedge with pre-set_active MBM logged | — | Novel wedge: pre-set mask + ARM release trips fw's early ISR into NULL-deref or similar. Fall back to narrow `0x100` in T284b. |

### Design

Code landed. Gated behind `bcm4360_test284_premask_enable=1`; requires T276+T277+T278.

1. After T276 shared_info write (if enabled), BEFORE `brcmf_chip_set_active`:
   - Read MBM ("pre-write (pre-set_active)") — expect 0.
   - `pr_emerg "calling brcmf_pcie_intr_enable (pre-set_active)"` — safety marker.
   - Call `brcmf_pcie_intr_enable(devinfo)` (writes MBM = 0xFF0300).
   - `pr_emerg "brcmf_pcie_intr_enable returned"`.
   - Read MBM ("post-write (pre-set_active)") — expect 0xFF0300 (T241-consistent).
2. `brcmf_chip_set_active` runs.
3. Read MBM ("post-set_active") — CRITICAL persistence check.
4. T276 2 s poll runs (if enabled) — reads si[+0x010], fw_done, mbxint.
5. After T276 poll-end: Read MBM ("post-T276-poll").
6. T277 decode runs (if enabled).
7. T278 POST-POLL full dump runs (if enabled).
8. After T278 initial dump: Read MBM ("post-T278-initial-dump").
9. Ladder runs; at each T278 stage hook (t+500ms, t+5s, t+30s, t+90s): MBM read piggybacks the console delta dump ("stage t+Xs").

Total: 8 MBM readback points across the full init → ladder timeline. `pr_emerg` for each → in journal even on wedge.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test284_premask_enable=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.284.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.284.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.284.journalctl.txt
```

T279 also enabled: if mask persists and console doesn't advance on its own, H2D probes run with mask=0xFF0300 → expected to produce MAILBOXINT latch and (hopefully) new fw console content. T280 NOT enabled (redundant — T284 already opens mask earlier).

### Safety (advisor-flagged)

Pre-set mask + ARM release is a new state in this harness. Two specific wedge paths:
- Fw's ISR fires immediately on ARM release (if any bit was already latched before we wrote the mask); handler may not be fully initialized → NULL deref → fw TRAP.
- ISR handler writes to TCM region we also read → races.

Mitigation: readback markers at each stage give visibility up to wedge point. Pre-set_active MBM log line is already in the journal before ARM release, so any wedge-during-set_active is attributable.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test284_premask_enable`; strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: needs fresh cold cycle (previous was for T280 fire).
6. **Log attribution**: pre/post-call markers discriminate mid-call wedge from later wedges.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT: ~20 s
- T276 shared_info write: ~50 ms
- T284 pre-write / intr_enable / post-write: ~10 ms
- brcmf_chip_set_active + post-set_active read: ~100 ms
- T276 2s poll + T277 + T278 initial dump + post-T278 read: ~3 s
- T279 H2D probes: ~250 ms
- T238 ladder with 4 more MBM reads + potential wake: variable
- Total: ~25 s before ladder; T238 ladder for 120 s; wedge or clean completion

If HOME RUN (fw wakes), the late-ladder wedge may not happen — fw running normally consumes the ladder differently. Need to watch for that.

---

## POST-TEST.280 (2026-04-24 15:31 BST fire, boot -1 — **MAILBOXMASK write SILENTLY DROPS at post-set_active. `brcmf_pcie_intr_enable` runs cleanly but the register doesn't change. Matrix row 5. Blocks the "unblock mask → wake fw" approach via this register/path/timing.**)

### Timeline (from `phase5/logs/test.280.journalctl.txt`, boot -1)

- `15:31:39` insmod
- `15:31:49` insmod returned
- `15:32:12` chip_attach + fw download + FORCEHT + set_active (identical to T278/T279 path)
- `15:32:12` T276 si[+0x010]=0x0009af88 at t+0ms (identical fw response — consistent across all 4 fires today)
- `15:32:12` T278 POST-POLL (full): 587 B dumped (identical fw console content)
- `15:32:12` **T280: pre-enable `MAILBOXMASK=0x00000000 MAILBOXINT=0x00000000`** (matches T279)
- `15:32:12` T280: "calling brcmf_pcie_intr_enable" marker
- `15:32:12` T280: "brcmf_pcie_intr_enable returned" marker — **no mid-call wedge; helper completed**
- `15:32:12` **T280: post-enable `MAILBOXMASK=0x00000000` (expected 0xFF0300)** — **WRITE SILENTLY DROPPED**
- `15:32:12` T280: post-enable MAILBOXINT=0 (consistent with mask still closed)
- `15:32:12` T280 post-mask-enable delta: `no new log (wr_idx=587 unchanged)` — fw did NOT wake
- `15:32:12` T280: +100ms MAILBOXINT=0 (no late-arriving signals)
- `15:32:12` T279 ran with MAILBOXMASK still 0: both H2D writes produced `MAILBOXINT=0`, `no new log` — identical to T279 fire
- `15:32:12 → 15:33:33` T238 ladder to `t+90000ms dwell`, then wedge [t+90s, t+120s] (unchanged)
- `15:48:28` boot 0 (user cold-cycled)

### What T280 settled (factually)

1. **`brcmf_pcie_intr_enable` (the upstream-canonical helper) does NOT modify MAILBOXMASK on this chip in the post-set_active state.** Both pre/post markers fired, no wedge; MBM readback shows the register unchanged at 0x00000000.

2. **New class of silent-failure finding.** Unlike prior T258/T259 which WEDGED the host when writing MAILBOXMASK (with different timing — t+120s ladder, plus MSI subscription), T280's MBM write produced zero effect, zero wedge. Either:
   - (a) The write never reached the register (BAR0 access issue at this time / state).
   - (b) The write reached but the register is read-only / write-masked in this state.
   - (c) The write landed briefly, then something reset the register to 0 before readback.

3. **Clean call chain.** `brcmf_pcie_intr_enable` is a 2-line helper that calls `brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxmask, devinfo->reginfo->int_d2h_db | devinfo->reginfo->int_fn0)`. We have no indication `reginfo->mailboxmask` is wrong (it's `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = 0x4C`). The write path is the same one T241 verified passing at pre-set_active.

4. **Pre-latched bits confirmed zero.** `MAILBOXINT=0` both pre and post — fw has NOT pre-latched any H2D bits waiting for the mask to open. Even if we could open the mask, there's nothing currently waiting.

5. **T279 probes re-ran under mask=0 and reproduced T279's null response.** Consistent across fires. No drift in the diagnostic itself.

### What changes between pre-set_active (T241 PASS) and post-set_active (T280 FAIL)?

During `brcmf_chip_set_active`:
- ARM CR4 reset de-asserted (fw starts executing).
- Clock states change (FORCEHT already applied pre-call; other clocks may switch).
- Fw takes ownership of some HW state.

Candidate causes for MBM write silent failure:
- **PCIE2 core in a different reset/clock state after fw runs.** Fw could disable the PCIE2 register block's write enable after init.
- **Backplane window shift.** BAR0 window's mapping could change if fw writes to the BAR0_WINDOW register; pcie.c's `buscore_prep_addr` handles this but only for buscore reads/writes, not for the MBM path which uses a fixed offset into BAR0.
- **ARM-owned bit.** Some PCIe2 registers have ARM-only write access once fw is running — would be a HW design decision not documented.

### Implications

- The whole "host writes MAILBOXMASK to wake fw" approach is blocked at this register/timing/method.
- Prior T258/T259 wedges were probably a DIFFERENT failure mode (MSI-subscription related, which IS gated by time-in-MSI-bound-state per T264-T266). The MBM write itself may also have silently dropped in those runs; we just didn't read back.

### What T280 did NOT settle

- Whether MAILBOXMASK at a DIFFERENT offset works (e.g., BAR0+0xC34 = `BRCMF_PCIE_64_PCIE2REG_MAILBOXMASK` — but that's 64-bit-addressing variant, shouldn't apply to BCM4360).
- Whether the write works via a DIFFERENT access method (buscore prep addr, window-mapped access, direct TCM-shadow write).
- Whether the write works at DIFFERENT timing (pre-set_active via an earlier probe extension; mid-ladder; post-ladder).
- Whether fw's own init ever unmasks (it apparently doesn't, based on T279/T280 readings).

### Next-test direction (advisor required)

Candidates, small-to-large:

- **T282-MBM-WRITE-VARIANTS**: fire with multiple attempted MBM writes at post-set_active time — different values (narrow 0x100 vs full 0xFF0300), different helpers (raw iowrite32 bypassing reginfo, buscore-prepped write), different timings (immediately post-set_active, after a delay). Small, diagnostic-first.

- **T283-FW-MBM-TRACE**: blob disasm for the actual mask-register writes fw's init code performs. If fw writes the mask itself but at a different offset, we know where the "real" mask register is. Static analysis; no substrate cost.

- **T284-PRE-SET-ACTIVE-MBM**: Call `brcmf_pcie_intr_enable` BEFORE `brcmf_chip_set_active`. T241 verified MBM write works at this stage. Open question: does fw's ARM-release clear the mask we just set, or does our pre-set-active mask survive into fw runtime?

T283 is the highest-info-per-cost (pure static, likely reveals the right register). T284 is the highest-payoff-if-it-works (direct fix). T282 is detailed narrowing.

Advisor call before committing to shape.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.280.journalctl.txt` (1467 lines).
- Run output captured: ✓ `phase5/logs/test.280.run.txt`.
- Outcome matrix resolved: ✓ **row 5** ("MBM readback mismatch — write didn't land").
- Ready to commit + push + sync.

---

## PRE-TEST.280 (2026-04-24 15:05 BST — **Host-side MAILBOXMASK unblock. Call brcmf_pcie_intr_enable between T278 dump and T279 H2D probes; see if the mask alone wakes fw or pre-latched bits fire.**)

### Hypothesis

T279 observed MAILBOXMASK=0 — fw's own init did NOT unmask, so no H2D write can propagate. Two candidate explanations:
1. **Mask unmask is supposed to happen, didn't.** If fw set the *software* flag-mask when hndrte_add_isr registered pciedngl_isr and fn@0x1146C (T273/T274 evidence), but never propagated that to the HW MAILBOXMASK register, fw has a "latent ready" state: internal MAILBOXINT would latch an H2D bit, but the ARM never wakes because mask is 0.
2. **Mask unmask requires a host action we haven't made.** Upstream brcmfmac's `brcmf_pcie_intr_enable` writes MAILBOXMASK; fw expects the host to do this.

Both cases: writing MAILBOXMASK ourselves is the discriminator.

Per advisor: if bits were ALREADY pre-latched in MAILBOXINT (waiting for the mask to open), the mask-enable alone will wake fw without any H2D write. This is the highest-value outcome and we lose it if T280 is merged with T279's H2D probes.

### Outcome matrix

| Post-mask-enable delta | Post-mask MBXINT | Post H2D_MBX_1 delta | Post H2D_MBX_0 delta | Reading |
|---|---|---|---|---|
| **New fw log** | Non-zero pre-latched | — | — | **Home run: mask was the sole gate; fw had bits pre-latched; unblocking wakes it.** Driver fix: call `brcmf_pcie_intr_enable` during setup. |
| "no new log" | 0 | New wl/bmac/wl_rte.c log | (bonus) | fn@0x1146C's trigger = H2D_MBX_1 under open mask. Driver fix: mask enable + H2D_MBX_1. |
| "no new log" | 0 | "no new log" | `"pciedngl_isr called"` | Positive control OK; fn@0x1146C's bit is neither H2D_MBX_0 nor H2D_MBX_1. Narrow search (T281b — enumerate other wake mechanisms). |
| "no new log" | 0 | "no new log" | "no new log" | MBM readback will show whether write landed. If landed, mask not gating; deeper issue (INTMASK at 0x24? ARM vector at [0x224]?). Pivot to static analysis. |
| readback mismatch (post MBM ≠ 0xFF0300) | — | — | — | MBM write didn't land. BAR0 write-path issue; prior T241/T243 had MBM round-trip tests — re-check. |
| Mid-call wedge (only "calling brcmf_pcie_intr_enable" marker fires, "returned" does not) | — | — | — | Novel finding: `brcmf_pcie_intr_enable` itself wedges HW under shared_info-present conditions. Prior T258/T259 wedges had no shared_info. New class of wedge; fall back to raw write of narrower mask in T280b. |

### Design

Code landed. Gated on `bcm4360_test280_mask_enable=1`; requires T276+T277+T278.

1. Read MAILBOXMASK (expect 0 per T279). Log.
2. Read MAILBOXINT (expect 0). Log — shows any pre-latched bits.
3. `pr_emerg "calling brcmf_pcie_intr_enable"` — safety marker for mid-call wedge attribution.
4. Call `brcmf_pcie_intr_enable(devinfo)` (upstream helper — writes int_d2h_db | int_fn0 = 0xFF0300 to MAILBOXMASK).
5. `pr_emerg "returned"` — confirms call didn't wedge.
6. Read MAILBOXMASK (verify 0xFF0300). Log.
7. Read MAILBOXINT (check for pre-latched bits). Log.
8. msleep(100).
9. T278 delta console dump — **critical observation: did mask enable alone wake fw?**
10. Read MAILBOXINT again (log any late-arriving signals).
11. If `bcm4360_test279_mbx_probe=1` also set: T279's H2D probes run AFTER this block.

NO MSI, NO request_irq, NO hostready call. All orthogonal to the mask question.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test280_mask_enable=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.280.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.280.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.280.journalctl.txt
```

Both T279 and T280 enabled so one fire discriminates all matrix outcomes.

### Safety

- Prior T258/T259 wrote MAILBOXMASK via the same helper and wedged host. Those runs lacked shared_info; T280 has shared_info + console + pre-write log marker. That's a real conditions delta but not a guarantee.
- Pre-log marker `"calling brcmf_pcie_intr_enable"` + post-log `"returned"` discriminates "wedge during MMIO write" from "wedge during subsequent probe reads" from "wedge during H2D write" from "wedge much later in ladder".
- Expect wedge. Budget one cold cycle per fire.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test280_mask_enable`; 6 T280 strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since ~14:55 BST (~10 min, inside T270's 20-min clean window). **Recommended: fresh cold cycle before fire** for cleanest read.
6. **Log attribution markers**: pre/post-call `pr_emerg` lines make wedge-location diagnosable.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT + set_active: ~20 s
- T276 2s poll + T277 decode + T278 full dump: ~3 s
- T280 mask-enable + 100 ms dwell + delta dump: ~150 ms
- T279 H2D probes: ~250 ms
- T238 ladder to wedge: ~90-120 s
- Total: ~115-145 s before wedge

T280's diagnostic lands in the first ~3.2 seconds after set_active. Wedge after that still leaves all diagnostic data in the journal.

---

## POST-TEST.279 (2026-04-24 13:51 BST fire, boot -1 — **Decisive finding: `MAILBOXMASK = 0x00000000`. Both H2D mailbox writes landed with zero MAILBOXINT response and zero new console content. Advisor's sanity check identified the root cause: fw's mask blocks any wake interrupt. Major reframe.**)

### Timeline (from `phase5/logs/test.279.journalctl.txt`, boot -1)

- `13:51:22` insmod
- `13:51:32` insmod returned
- `13:51:55` chip_attach + fw download + FORCEHT + set_active complete
- `13:51:55` T276 si[+0x010]=0x0009af88 at t+0ms (identical to T276/T277/T278 — fw response is stable across runs)
- `13:51:55` T278 POST-POLL (full): wr_idx=587, 5 chunks dumped (identical 587 B fw console content as T278)
- `13:51:55` **T279: pre-probe `MAILBOXMASK = 0x00000000` (0 = all fw ints masked)**
- `13:51:55` T279: writing `H2D_MAILBOX_1 = 1` (hypothesis: fn@0x1146C trigger?)
- `13:51:55` **Post-H2D_MBX_1 (+100ms): `MAILBOXINT = 0x00000000`** (D2H mirror stayed 0)
- `13:51:55` **T278 POST-H2D_MBX_1 (+100ms): `no new log (wr_idx=587 unchanged)`**
- `13:51:55` T279: writing `H2D_MAILBOX_0 = 1` (positive control: pciedngl_isr)
- `13:51:55` **Post-H2D_MBX_0 (+100ms): `MAILBOXINT = 0x00000000`** (D2H mirror stayed 0)
- `13:51:55` **T278 POST-H2D_MBX_0 (+100ms): `no new log (wr_idx=587 unchanged)`**
- `13:51:55 → 13:53:15` T238 ladder runs t+100ms → t+90000ms (22 markers; standard wedge window at [t+90s, t+120s])
- `13:53:15` boot ended (late-ladder wedge → watchdog reboot)

### What T279 settled (factually)

1. **`MAILBOXMASK = 0x00000000` in Phase 5's fw state.** All fw-side mailbox interrupt bits are masked. First time this has been primary-source measured.

2. **Both H2D_MAILBOX writes landed but produced NO MAILBOXINT latch.** `H2D_MBX_1=1` and `H2D_MBX_0=1` are both valid writes (the register addresses are known to work per pcie.c constants + prior T240 attempts); fw saw them; fw's mask kept them from propagating to the ARM interrupt line.

3. **Fw console stayed at `wr_idx=587`.** No fw code ran in the 100 ms windows — not fn@0x113b4 (which would produce printf output per T281), not pciedngl_isr (which would produce `"pciedngl_isr called"` per T274 blob analysis). This confirms fw's ARM is in WFI and the mailbox writes did not wake it.

4. **Positive control failed as expected under MAILBOXMASK=0.** H2D_MBX_0 is the **known-good** path for pciedngl_isr per T274, but with MAILBOXMASK=0 even this known-good path is silent. The observation pipeline (console + delta cursor + pr_emerg) is NOT broken; the wake path is.

5. **Late-ladder wedge unchanged** (orthogonal).

### The reframe

Prior assumption: fn@0x1146C's trigger is an unknown specific bit; T279 would identify it. Result: ANY bit we might write is blocked by MAILBOXMASK=0 before it reaches fw. Therefore:

- The question "which bit triggers fn@0x1146C" is moot until the mask is opened.
- The question BECOMES: "why is MAILBOXMASK=0, and what happens if we open it ourselves?"

### What this tells us about fw init

- T274's analysis of hndrte_add_isr said it "dispatches a class-specific unmask via a 9-entry thunk vector". The thunks (0x27EC region) should unmask the relevant MAILBOXINT bit for each registered ISR.
- pciedngl_isr was registered (T255/T274 confirmed). But MAILBOXMASK=0 at our observation point means **either (a) the unmask didn't happen, (b) it happened to a different register, or (c) it was reset somehow.**
- Prior framing: "fn@0x1146C waits for a trigger that never fires." True but the reason it never fires is a STEP EARLIER — fw's own init didn't unmask the interrupt line that would carry the trigger.

This changes the investigation direction. Possible causes for the mask being 0:
1. **Something resets MAILBOXMASK** after fw's init (PCIe link state, ARM reset, clock gate reset). Unlikely but possible.
2. **hndrte_add_isr's unmask thunk writes to a different register** (not BAR0 PCIE2REG_MAILBOXMASK but perhaps a backplane-side register, or the INTMASK at BAR0+0x24).
3. **Fw DOES unmask, but only after some further init step we haven't passed.** The unmask might be gated on a condition we haven't satisfied (e.g., host must set a specific register first to indicate readiness).
4. **MAILBOXMASK gets reset on entry to WFI** (unlikely; masks are typically persistent).

### Next-test direction (T280 candidate)

**T280 — Set MAILBOXMASK ourselves and re-probe**: After T279's zero-response observation, write `MAILBOXMASK = 0x300` (enables FN0_0 + FN0_1 per upstream brcmfmac convention), then re-run the T279 sequence. Three outcomes:

| T280 outcome | Reading | Follow-up |
|---|---|---|
| H2D_MBX_0=1 → fw logs `"pciedngl_isr called"` AND MAILBOXINT shows 0x100 latched | **Host-side mask unblocking works.** Fw's init path didn't unmask but host CAN do it. Test H2D_MBX_1 next; follow wherever it leads. | Stage a "patch: enable mailboxes post-set_active" and test if fw completes init naturally. |
| H2D writes still produce 0 MAILBOXINT | Either MAILBOXMASK write didn't land (read back to verify) OR H2D writes don't latch regardless of mask. Deeper issue. | Read MAILBOXMASK after writing; investigate BAR0 write-path (prior T241/T243 had MBM round-trip tests). |
| Host wedges on MAILBOXMASK write | Same wedge mode T258-T269 hit. Observation: those lacked shared_info; T280 has it. If still wedges, MAILBOXMASK write itself is toxic on this HW. | Fall back to INTMASK (BAR0+0x24) instead of MAILBOXMASK, or a different approach. |

Safety: prior MAILBOXMASK-write scaffolds wedged host. T280 adds observability (T278 console + T279 MAILBOXINT reads) BEFORE the mailbox write, so even if the MAILBOXMASK write itself wedges, we have pre-wedge state captured. Also prior scaffolds wrote 0xFF0300; T280 should try a narrower 0x300 first.

Alternative T280b: **Pre-write mask-enable EARLIER, before set_active**, so fw observes it during init. Might influence fw's behavior differently than a post-init override.

Advisor call before committing to T280's exact shape.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.279.journalctl.txt` (1447 lines).
- Run output captured: ✓ `phase5/logs/test.279.run.txt` (3 lines — fire/insmod/return).
- Outcome matrix resolved: ✓ row 3 ("No new log on either probe") — with root cause identified: MAILBOXMASK=0.
- Ready to commit + push + sync.

---

## PRE-TEST.279 (2026-04-24 13:30 BST — **Directed mailbox probe. H2D_MBX_1 hypothesis + H2D_MBX_0 positive control, console observation between. Single fire.**)

### Hypothesis

T278 confirmed fw enters silent WFI after wl_probe registers `fn@0x1146C` as a scheduler callback. T281 static analysis showed the callback dispatcher reads a HW-mapped pending-events word and fires fn@0x113b4 (which contains `printf` + `printf/assert`) when a matching bit is set.

Two candidate writes:
1. **H2D_MAILBOX_1=1** (BAR0 + 0x144): upstream's "hostready" signal. If this is fn@0x1146C's trigger, fw will log (from fn@0x113b4's printf chain) within ~100 ms.
2. **H2D_MAILBOX_0=1** (BAR0 + 0x140): known-positive control — fw's MAILBOXINT.FN0_0 (bit 0x100) latches → fires pciedngl_isr per T274. Fw's pciedngl_isr logs `"pciedngl_isr called"` (string at blob 0x40685).

### Outcome matrix

| H2D_MBX_1 console delta | H2D_MBX_0 console delta | Reading |
|---|---|---|
| New log w/ `wl` / `bmac` / `intr` / `wl_rte.c` strings | any | **Home run.** fn@0x1146C's trigger = H2D_MBX_1. |
| `"no new log"` | `"pciedngl_isr called"` or similar | Positive control confirmed; fn@0x1146C needs something else. T280 narrows (MAILBOXMASK bit enable? different H2D register?). |
| `"no new log"` | `"no new log"` | Either observation path broken, MAILBOXMASK=0 keeps fw masked, OR fw doesn't latch on H2D at all. Decode from MAILBOXMASK pre-probe value + any post-MAILBOXINT change. |
| New log on BOTH probes | — | Multi-bit response; both triggers valid. |
| Host wedges on H2D_MBX_1 | — | MMIO-write wedge independent of MSI; new finding. Prior-probe console delta still captured if it fired before wedge. |
| Host wedges on H2D_MBX_0 | — | Wedge is specific to pciedngl_isr path (MSI-orthogonal). |

### Design

Code landed (see previous commit). Runs in `brcmf_pcie_download_fw_nvram`'s post-set_active block, AFTER T276 2s poll + T277 struct decode + T278 initial full dump:

1. Read `MAILBOXMASK` (sanity check — if 0, fw has everything masked).
2. Write `H2D_MAILBOX_1 = 1`.
3. `msleep(100)`.
4. Read `MAILBOXINT` (D2H mirror — non-zero means fw signalled back).
5. T278 delta console dump.
6. Write `H2D_MAILBOX_0 = 1`.
7. `msleep(100)`.
8. Read `MAILBOXINT`.
9. T278 delta console dump.

No MSI, no request_irq — per T264-T266, host-side MSI subscription is the wedge trigger, not the write itself.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 bcm4360_test279_mbx_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.279.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.279.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.279.journalctl.txt
```

### Safety

- Same envelope as T276/T277/T278 + 2 mailbox writes + 200 ms added dwell.
- No MSI subscription (orthogonal to T264-T266 wedge).
- Platform watchdog expected to recover late-ladder wedge.
- H2D writes without prior MSI setup HAVE NEVER been fired in Phase 5 — they could trigger a novel wedge mode, but the T258-T269 scaffolds wrote H2D without shared_info present; T279 has shared_info in place, matching Phase 4B's Test.28 conditions more closely.

### Pre-test checklist

1. **Build**: ✓ committed next push; modinfo shows `bcm4360_test279_mbx_probe`; 6 T279 strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (committing before fire).
5. **Host state**: boot 0 up since 13:04 BST (~30 min old; past T270's 20 min clean window).
6. **Recommendation**: **cold cycle before fire** for cleanest substrate; the two mailbox writes are a new stress pattern.

### Fire expectations

- Insmod + chip_attach + fw download + FORCEHT + set_active: ~20 s
- T276 2 s poll + T277 decode + T278 full dump + T279 probe sequence: ~3 s
- T238 ladder to crash: ~90-120 s
- Total: ~115-145 s before wedge

T279's diagnostic value lands in the first 3 seconds after set_active. Even if the host wedges during or after the probes, the console delta dumps will already be in the journal.

---

## POST-TEST.278 (2026-04-24 12:50 BST fire, boot -1 — **Full 587 B fw console captured; all 4 stage hooks report silence. Matrix row 1: fw logs only during first ~2s. Primary-source confirmation of T257's WFI reading. Hang bracket refined to inside wl_probe.**)

### Timeline (from `phase5/logs/test.278.journalctl.txt`, boot -1)

- `12:50:54` insmod fire (post cold-cycle)
- `12:51:04` insmod returned (10 s)
- `12:51:19` chip_attach + fw download + NVRAM + FORCEHT + set_active complete
- `12:51:19` T276 si[+0x010]=0x0009af88 at t+0ms (same response as T276/T277)
- `12:51:19` T278 **POST-POLL (full) wr_idx=587 prev=0 delta=587 dumping=587 bytes** across 5 chunks (128+128+128+128+75 B)
- `12:51:19` T278 t+500ms: `no new log (wr_idx=587 unchanged)`
- `12:51:21` T278 t+5s: `no new log (wr_idx=587 unchanged)`
- `12:51:47` T278 t+30s: `no new log (wr_idx=587 unchanged)`
- `12:52:48` T278 t+90s: `no new log (wr_idx=587 unchanged)`
- [wedge in [t+90s, t+120s]; boot ended 12:52:48]

### Reassembled fw console (full 587 B)

```
Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
125888.000 
RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz
125888.000 pciedngl_probe called
125888.000 Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
125888.000 wl_probe called
125888.000 Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11
```

### What T278 settled (factually)

1. **Fw reaches `wl_probe` (WLC device probe = T273's `fn@0x67614`).** Primary-source confirmation. Earlier indirect evidence (scheduler callback registered for `fn@0x1146C`) suggested this; T278's log text makes it direct.

2. **Fw reaches `pciedngl_probe`** and completes it (advances past into wl_probe). Confirms T274's finding that pcidongle_probe's body runs through without hangs.

3. **Fw completes `si_kattach`** before RTE banner is printed. Kernel-attach stage done; chipcommon register access is working.

4. **Watchdog tick = 32 ms** (`wd_msticks = 32` from `si_kattach` log). New primary-source timing fact. Relevant for future analysis of fw-side watchdog behaviour.

5. **RTE banner**: `"RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz"`. Clock rates 40 MHz XTAL / 160 MHz backplane / 160 MHz ARM CPU, consistent with chipst 0x9a4d decode.

6. **Fw goes silent after wl_probe's initial chipc dump.** No subsequent log output across the full dwell ladder — t+500ms through t+90s all show `wr_idx=587 unchanged`.

7. **T257's WFI reading is now primary-source confirmed.** The scheduler isn't busy-looping (would produce log entries over time); fw isn't asserting (no "ASSERT" / "TRAP" / "PC=" strings); fw isn't timing out (no watchdog print despite 32 ms tick). The silence is consistent only with "scheduler idle via WFI, waiting for an event".

8. **No fw-side self-diagnosis string.** Fw doesn't self-identify a missing input. Unlike many embedded systems that print "waiting for X" or "timeout on Y", this fw just returns to scheduler and idles. Means we can't learn the missing trigger from the log alone — we have to either disasm the wl_probe tail (T273 territory) or induce triggers on hardware (T279 territory).

### Hang bracket — tightened to wl_probe's tail

Prior reading (from T272-FW / T273-FW): "hang is somewhere in wl_probe's tail, inside sub-functions we haven't fully traced."

T278 refines: wl_probe PRINTS "wl_probe called" → "Found chip type AI" → "Chipc: rev 43..." then goes quiet. There are two orderings for the quiet region:

- **(A)** wl_probe's sub-calls (including `hndrte_add_isr(fn@0x1146C, ...)`) do NOT log. They just complete their work (registrations, init) and wl_probe returns. Scheduler sees no runnable events → WFI.
- **(B)** wl_probe enters an inner sub-call that is silent AND happens to never return (a HW-dependent stall that the T273/T274 disasm failed to identify).

T257's WFI-via-scheduler-state finding favours (A): the scheduler's frozen node state means RTE's scheduler is running idle, which only happens after all probes return. (B) would leave wl_probe mid-execution on the call stack — scheduler wouldn't be reached.

**Conclusion: wl_probe completes normally (no assert, no hang). Fw reaches the scheduler idle state and WFI-waits for `fn@0x1146C`'s callback trigger, which never fires in our test harness.**

### What T278 did NOT settle

- **What trigger fn@0x1146C is waiting on.** T273 identified the callback registration but the specific MAILBOXINT bit / HW event / host action that fires it is unknown.
- Why Test.28 saw MAILBOXINT=0x3 in Phase 4B harness but T276/T277/T278 see 0 under Phase 5 patches. The console log suggests fw does not self-initiate mailbox signals during init; Test.28's signals may have been host-driven by Phase 4B harness writing something we don't.
- Whether writing to a specific MAILBOXINT bit in the scheduler's pending-events word would wake fn@0x1146C. T274 looked for writers of this word and found none — suggesting the bit IS HW-mapped and requires a PCIe-side action, not a TCM write.

### Next-test direction (advisor required)

Candidates:

- **T279-MBXINT-PROBE**: With T278 periodic console running, fire a single MAILBOXINT write (e.g., bit 0x1 = FN0_0 = pciedngl_isr trigger; or bit 0x2; or H2D_MAILBOX_0) AFTER set_active + T276 poll, and watch the console for fw response. Observable: if fw logs `"pciedngl_isr called"` (string at blob 0x40685 per T274 analysis), we've confirmed the FN0_0 mapping AND woken up fw partially. Safety concern: prior scaffolds (T258-T269) that wrote MAILBOXINT without console access all wedged the host; now with console readable via T278, we can observe even a short fw activity before any wedge.

- **T280-MBXMASK-WIDE-POLL**: Still observation-only. Read not just `MAILBOXINT` but also `MAILBOXMASK`, `H2D_MAILBOX_0/1/2`, `D2H_MAILBOX_0/1/2` during the T278 stages. Discriminates whether any of these registers change passively across the ladder. Low-risk, low-reward — probably all zero.

- **T281-POKE-FN1146C**: Blob-disasm fn@0x1146C more carefully to identify the specific flag bit or event it responds to. Static analysis, no fire. Could make T279's write target specific rather than guessed.

Highest-value-per-fire: **T279** (console-observed mailbox poke). Safest: **T281** (static). Between them, probably T281 first (cheap, directed), then T279 (directed fire) after.

### Safety + substrate

- T278 ran the same ~150 s envelope as T270-BASELINE. Late-ladder wedge consumed one cold-cycle substrate budget.
- Current boot 0 is post-T278-wedge cold cycle (user performed SMC reset). Clean substrate available for next fire.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.278.journalctl.txt` (1449 lines).
- Run output captured: ✓ `phase5/logs/test.278.run.txt`.
- Outcome matrix resolved: ✓ **row 1** ("Fw logged ONLY during first ~2s; silence across all 4 stage hooks").
- Full fw console reassembled above; key facts extracted.
- Ready to commit + push + sync.

---

## PRE-TEST.278 (2026-04-24 12:10 BST — **Periodic console dump across the dwell ladder. Post-poll full dump + deltas at t+500ms, t+5s, t+30s, t+90s. Single fire, combined axes per advisor.**)

### Hypothesis

T277 captured the first 128 B of 587 B fw wrote at ~t+2s post-set_active. Three questions remain open:

1. **What's in bytes 128..587?** (near-certain: more chipc decode / init messages; potentially assertions)
2. **Does fw continue logging past t+2s?** If yes, we see what fw does during the dwell ladder (up to the late-ladder wedge).
3. **Is there a log entry around t+90s just before the wedge?** If yes, that's likely the decisive diagnostic.

T278 answers all three in one fire: post-poll seeds the delta cursor with prev=0 so the first call dumps the full current window; then 4 per-stage hooks dump deltas at t+500ms, t+5s, t+30s, t+90s.

### Outcome matrix

| Observation | Interpretation | Follow-up |
|---|---|---|
| Post-poll dumps full 587 B; stage hooks all "no new log (wr_idx=587 unchanged)" | Fw logged ONLY during the first ~2 s post-set_active. It went quiet for the rest of the ladder — consistent with WFI per T257. Log content from bytes 128..587 may still reveal the init end-state. | Decode bytes 128..587 for assert/trap strings; decide if further FW wake-up is needed. |
| Post-poll dumps 587 B; t+5s/t+30s deltas non-zero | Fw keeps logging during early ladder but stops before t+30s. | Content of each delta tells us what fw logged and when. |
| Post-poll dumps 587 B; t+90s delta non-zero | **Fw logs right before the late-ladder wedge.** Highest-value. The t+90s delta content is the most likely to explain the wedge mechanism (assert, timeout, state dump). | Decode carefully. Could redirect the investigation immediately. |
| Post-poll: struct becomes invalid between T277 capture and T278 read | Struct moved or got corrupted. Unlikely but the validator catches it. | Log shows reason; rethink. |
| Some t+Xs delta contains known Broadcom trap string (`"ASSERT"`, `"TRAP"`, `"PC=0x"`) | **Smoking gun.** Fw self-reported a trap/assert. | Decode trap location against blob disasm; likely points to the exact fw state when wedge fires. |

### Design

Code landed; gated behind `bcm4360_test278_console_periodic=1` (requires `test276 + test277`). Helper function `bcm4360_t278_dump_console_delta` does all work:

- Re-reads struct at `si[+0x010]` pointer (not hardcoded — robust to any offset change).
- Validates `buf_addr / buf_size / write_idx` against `devinfo->ci->ramsize`.
- Tracks delta via `devinfo->t278_prev_write_idx` (struct field, lifetime = devinfo).
- Dumps in 128 B chunks with `%*pE` ASCII escape; hard cap at 1024 B per call to avoid printk truncation.
- Prints `"no new log"` on empty delta (silence is data).

Per-stage hooks use a small macro `BCM4360_T278_HOOK(tag)` inlined next to the 4 dwell pr_emerg lines.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.278.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.278.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.278.journalctl.txt
```

### Substrate note

Current boot 0 is post-T277 recovery. Like PRE-TEST.277 noted, a fresh cold cycle before fire keeps results substrate-clean. **Recommended: cold cycle before T278 fire.**

### Expected artifacts

- `phase5/logs/test.278.run.txt`
- `phase5/logs/test.278.journalctl.txt`

### Safety

- Same envelope as T276/T277 (existing shared_info write + DMA alloc + reads only).
- 4 additional reads + ~4×(4+32)=144 read_ram32 calls during ladder (~2 ms added per stage — well under dwell granularity).
- Platform watchdog expected to recover late-ladder wedge.

### Pre-test checklist

1. **Build**: ✓ committed once we push (next); modinfo shows `bcm4360_test278_console_periodic`; 8 T278 pr_emerg strings visible.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since ~12:02 BST (~10 min — inside T270-BASELINE's 20 min clean window, but consumed by T277 fire and recovery).
6. **Recommendation**: cold cycle before fire (user-initiated).

### Fire expectations

~150 s total run time (same as T270-BASELINE / T276 / T277). Expected to wedge in [t+90s, t+120s] (orthogonal to T278). T278's diagnostic value lies in what the logs contain, not whether the ladder completes.

---

## POST-TEST.277 (2026-04-24 11:55 BST fire, boot -1 — **Fw's live console captured: 587 B of fw-written log at TCM[0x96f78]. `buf_addr/size/wr_idx/rd_addr` struct layout Phase 4B proposed is CONFIRMED. Console is a real ring with timestamps. First 128 B decoded — rest unread (extend in T278).**)

### Timeline (from `phase5/logs/test.277.journalctl.txt`, boot -1)

- `11:55:14` insmod fire (post cold-cycle)
- `11:55:34` fw download + NVRAM + FORCEHT complete (20 s into fire)
- `11:55:34` **T277 PRE-WRITE struct@0x9af88**: `buf_addr=0xad9afa8b buf_size=0x02d5bf1b write_idx=0x5370158c read_addr=0x23535c0b` — ALL GARBAGE (uninitialized memory, struct not yet populated)
- `11:55:34` T276 shared_info written at TCM[0x9d0a4] (olmsg_dma=0x89b10000, all 6 fields verified)
- `11:55:34` `brcmf_chip_set_active returned TRUE`
- `11:55:34` T276 t+0ms: `si[+0x010]=0x0009af88 fw_done=0 mbxint=0` (same response as T276)
- `11:55:37` T276 poll-end: unchanged
- `11:55:37` **T277 POST-POLL struct@0x0009af88**: `buf_addr=0x00096f78 buf_size=0x00004000 write_idx=0x0000024b read_addr=0x00096f78` — **ALL FIELDS VALID TCM ADDRESSES**
- `11:55:37` **T277 buffer@0x00096f78 (first 128 B) ASCII**: `"Found chip type AI (0x15034360)\r\n125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11\r\n125888."`
- `11:55:37 → 11:57:08` T238 ladder: t+100ms → ... → t+90000ms dwell (22 markers, same pattern as T276/T270-BASELINE)
- `11:57:08` **LAST MARKER: `t+90000ms dwell`** — wedge in [t+90s, t+120s]
- `12:02:28` boot 0 (user cold-cycled during recovery)

### What T277 settled (factually)

1. **Phase 4B's struct layout interpretation is CONFIRMED.** 4 dwords at fw-published pointer = `{buf_addr, buf_size, write_idx, read_addr}`. All four fields make internal sense: buf_addr and read_addr both point to 0x96f78 (ring's fresh-read state — nothing consumed yet); buf_size is a plausible 16 KB ring size; write_idx is plausible <buf_size.

2. **Fw DOES populate the struct during post-set_active init.** Pre-write struct at 0x9af88 was uninitialized garbage; post-poll it's fully populated with valid values. Row 1 of the pre/post matrix ("struct populated by fw during post-set_active init") — CONFIRMED.

3. **Fw writes real log content during init.** 587 bytes of genuine ASCII text including:
   - chip identification: `"Found chip type AI (0x15034360)"` (AI = AXI Interconnect — matches Phase 4's chip architecture observations)
   - timestamped register dump: `"125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"`
   - Second timestamp `125888.` starts at byte 128 (our dump cuts mid-line)

4. **The timestamp unit is an open question.** `125888.000` appears at the first log line — too large for microseconds-since-boot, too large for milliseconds. Possibilities: PMU free-running counter value (chipc has one); arbitrary tick counter; or the buffer isn't starting at position 0 of the boot sequence. Not load-bearing for the next-step decisions.

5. **Buffer has NOT wrapped.** write_idx = 0x24b = 587 bytes << buf_size = 16 KB. read_addr = buf_addr = no host has consumed any entries. A dump of `buf_addr..buf_addr+write_idx` captures the full fw log so far.

6. **Late-ladder wedge unchanged.** Same `t+90000ms` last marker as T270-BASELINE and T276. T277 is pure read-only; doesn't affect the wedge mechanism.

### What T277 did NOT settle

- **What's in bytes 128..587** of fw's console. Our 128 B dump cuts mid-line (second `125888.` timestamp truncates). The remaining 459 bytes likely contain more register dumps, init-phase messages, and may contain the decisive clue about where/why fw enters WFI. **This is the T278 target.**
- Whether fw writes MORE log content during the ladder (t+100ms → t+90s window). The 587-byte snapshot is from ~2 s post-set_active; if fw continues to log during the ladder, periodic reads would catch that.
- What `0x00096f78` as `buf_addr` means in the TCM layout. It's 0x9af88 - 0x96f78 = 0x4010 below the console struct; 16 KB ring stops at 0x96f78 + 0x4000 = 0x9af78, which is 0x10 below the struct at 0x9af88. So the buffer is contiguous: `[0x96f78 .. 0x9af78)` then a 16 B gap, then the struct at 0x9af88. Neat layout.

### Decoded chip-identity from fw's log (cross-check)

Fw reports: chip type AI, `0x15034360` (full chip ID with rev/pkg bits), Chipc rev 43, caps `0x58680001`, chipst `0x9a4d`, pmurev 17, pmucaps `0x10a22b11`.

Cross-ref with Phase 4 identity from Python probe scripts + T252: chip 4360 / rev 3 / pkg 0, so `0x15034360` decoded = `0x1500_4360 | (rev 3 << 16) | (pkg 0 << 28)`. Consistent. The `0x58680001 ` Chipc caps + `0x9a4d` chipst haven't been recorded in our prior probes — new primary-source facts from fw itself, worth saving.

### Next-test direction

T278-CONSOLE-EXTENDED — two-axis extension of T277:

1. **Dump size**: use `min(write_idx, 4096)` (or even the full `buf_size` for completeness) in post-poll. Captures the entire current log, not just the first 128 B. Multiple pr_emerg lines with 128 B chunks per line (kernel printk line length limits). Expected payoff: **full fw init log** in one fire.

2. **Periodic reads during dwell ladder**: at t+500ms, t+5s, t+30s, t+60s, t+90s — re-read struct + dump newly-written region (bytes `write_idx_prev..write_idx_current`). If write_idx advances, we see what fw logs during the ladder and — critically — may see what fw logs right before the wedge.

Two independent axes; combine into one test or separate into T278+T279. Advisor call on which to prefer.

### What opens up

If fw keeps writing to the console, we have a primary-source channel for fw internal state that didn't exist before. Examples of things we could now learn:

- What init phase fw reaches (specific function/subsystem names in log lines).
- Whether fw self-reports ASSERT/TRAP messages (these are usually verbose in Broadcom fw).
- When (and whether) fw tries to read something from shared_info that we haven't provided.
- When fw transitions from init to "ready" state (if ever).

This is potentially the biggest lever we've had in Phase 5. Progress it carefully.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.277.journalctl.txt` (1436 lines).
- Run output captured: ✓ `phase5/logs/test.277.run.txt`.
- Pre/post matrix resolved: ✓ row 1 ("struct populated by fw during post-set_active init").
- Buffer matrix resolved: ✓ row 1 ("readable log text").
- Ready to commit + push + sync.

---

## PRE-TEST.277 (2026-04-24 11:18 BST — **Console-struct decode at the pointer T276 captured. Two-point read (pre-write + post-poll) + 128 B ASCII-escaped buffer dump. Advisor-approved.**)

### Hypothesis

T276 showed fw responds at shared_info[+0x010] with `0x0009af88` — a TCM address Phase 4B called a "console struct pointer". Phase 4B's interpretation is 4 dwords: `{buf_addr, buf_size, write_idx, read_addr}`. T277 tests the interpretation AND extracts whatever log text the buffer contains.

Two-point read discriminates three possibilities for how the struct exists:

| Pre-write struct | Post-poll struct | Reading |
|---|---|---|
| all zeros | populated (non-zero fields) | **Struct populated by fw during post-set_active init** (expected interpretation). |
| populated | identical | **Struct pre-existed in fw image**; post-set_active fw just copied the pointer to si[+0x010]. |
| populated | `write_idx` advanced (others unchanged) | **Fw is actively logging in our 2 s poll window.** Highest-value: the buffer is a live ring and our dump has fresh content. |
| garbage both | — | Struct offset is not at 0x9af88 in this layout; interpretation needs revising. |

### Outcome matrix

| Buffer ASCII dump | Reading | Follow-up |
|---|---|---|
| Readable log text (trap strings, printf fragments, `bmac`, `phy`, timing) | **Fw internal log captured.** Content may reveal what fw's doing between set_active and the late-ladder wedge. | Decode trap line; cross-ref with T272-FW init chain. If late-ladder wedge has a fw-side cause, the log will show it in subsequent reads. |
| Readable but only one or two lines, then zeros | Log is young — fw wrote a few lines then went quiet. | Extend dump to larger window (256 B–4 KB); track `write_idx` across ladder dwells. Design T278 around periodic console reads during the dwell ladder. |
| Non-ASCII but structured (fixed-size records, pointers) | Not a text console — maybe a circular message struct (olmsg pre-ring?). | Re-decode as structured records; if records carry fw→host messages, this could be the actual response channel. |
| All zeros or garbage | Struct is not at 0x9af88, OR `buf_addr` points somewhere uninitialized. | Check the struct fields — if buf_addr is 0, fw hasn't assigned one; if buf_addr is non-zero but points to zero bytes, log is genuinely empty (unexpected since fw is supposedly running code). |
| `buf_addr` not in `[0, ramsize)` | Address out of TCM — pointer is a DMA address? A garbage/uninitialized value? Log to confirm. | Don't dereference; add separate check for PCIe BAR / DMA addr interpretation in T278. |

### Design

Code landed alongside T276 (same commit will wrap both). Gated behind `bcm4360_test277_console_decode=1`; requires `bcm4360_test276_shared_info=1` (reads si[+0x010] as the struct pointer).

1. **Pre-shared_info-write**: read 4 dwords at TCM[0x9af88] (Phase 4B's observed pointer — hardcoded only for the pre-write read since fw hasn't published si[+0x010] yet). Logs `buf_addr / buf_size / write_idx / read_addr`.
2. **Post-2s-poll**: read si[+0x010] dynamically; if in `[1, ramsize)` read 4 dwords at that address. Same labels.
3. **If `buf_addr` ∈ (0, ramsize)**: read 128 B (32 dwords) starting at `buf_addr`, print as `%*pE` (ASCII escape) AND `%*ph` (hex). Escape form makes trap/log strings readable; hex form catches control bytes that `%*pE` hides.
4. **If any pointer invalid**: skip the follow, log the value. Safe.

No writes anywhere beyond the existing T276 writes. Pure read-only observation.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.277.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.277.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.277.journalctl.txt
```

### Substrate note (advisor caveat)

Current boot 0 is a watchdog recovery from the T276 crash, NOT a fresh cold cycle. T269 pattern: drift within ~25 min of post-wedge boots. If T277 differs from T276 on the `si[+0x010] = 0x0009af88` anchor value (e.g., 0 post-poll, or a different pointer), drift is a possible confound. Recommended: request cold cycle before T277 fire for cleanest comparison. If firing on current boot, accept and note in POST-T277 that substrate was post-wedge-recovery, not cold-cycle.

### Expected artifacts

- `phase5/logs/test.277.run.txt`
- `phase5/logs/test.277.journalctl.txt`

### Safety

- Same envelope as T276 (existing shared_info write + DMA alloc) + new reads only.
- No new writes, no MSI, no request_irq.
- Host wedge in [t+90s, t+120s] still expected (orthogonal to T277); platform watchdog recovers.

### Pre-test checklist

1. **Build**: pending code commit + build verification (next action).
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: this block.
4. **Plan**: this block (commit before fire).
5. **Host state**: boot 0 up since 11:09:35 BST (watchdog-recovered, not cold-cycled).
6. **Recommendation**: cold cycle before fire so result is not substrate-noise-polluted.

---

## PRE-TEST.276 (2026-04-24 10:50 BST, boot 0, substrate stale — **Port Phase 4B test.28's shared_info write into Phase 5; diagnostic observation of fw response under current patches. Not a claimed fix.**)

### Hypothesis

Phase 4B Test.28 (2026-04-13) proved: writing a valid `shared_info` struct at TCM[ramsize-0x2F5C] before ARM release prevents the 100 ms panic AND causes fw to (a) write a non-zero pointer to `shared_info[+0x010]` (observed value `0x0009af88`), and (b) send 2 PCIe mailbox signals (`PCIE_MAILBOXINT` = `0x00000003`).

Phase 5 passes the panic point via NVRAM + random_seed + FORCEHT (different path), but currently makes **zero shared_info writes** (`grep 0xA5A5A5A5 pcie.c` → no matches). Fw enters WFI by ~t+12 ms; scheduler frozen across 23 dwells (T255); sharedram_addr never published (T247).

T276 adds the missing shared_info write. Under Phase 5's patches (fw already past Phase 4B's panic point), does the fw still exhibit Test.28's response pattern, or does the different fw init state (further-along) change what it does?

### Outcome matrix

| Observation | Interpretation | Follow-up |
|---|---|---|
| `si[+0x010]` becomes non-zero AND ≥1 `mbxint` bit set within 2 s | **Test.28 reproduces under Phase 5 patches.** Fw is listening to shared_info even past panic point. Protocol anchor confirmed. | Decode pointer at si[+0x010]; probe referenced TCM region; consider next handshake step (fw_init_done, or olmsg ring poke). |
| Only `mbxint` becomes non-zero (no si[+0x010] update) | Partial response — fw notices handshake but doesn't complete the status-write step Test.28 saw. Fw state is genuinely further than Phase 4B. | Check scheduler state [0x6296C..0x629B4] — does it differ from T255 frozen baseline? Probe WLC-side register writes. |
| Only `si[+0x010]` becomes non-zero (no `mbxint`) | Inverse partial — fw writes status but doesn't signal. Unusual. | Check if fw wrote anywhere else in shared_info region; scan for additional pointer updates. |
| Both stay zero across 2 s | **Test.28 does NOT reproduce under Phase 5 patches.** Protocol model for this fw state needs rethinking. | Verify readbacks (rule out failed writes); compare scheduler state vs T270-BASELINE; reframe based on evidence. |
| `fw_init_done` becomes non-zero | Full init — would be a significant surprise given Test.29. | Switch from diagnostic to communication — probe olmsg ring for fw→host messages, try sending a command. |
| Host wedges earlier than T270-BASELINE's t+90-120s window | Regression from T276's bus-master + DMA alloc interacting with drifted substrate | Disable T276; re-fire T270-BASELINE to confirm drift vs T276-caused. |
| Readback magic check fails | Write path issue (not a fw-response issue) | Debug write_ram32 semantics for our specific offset; re-derive rambase assumption. |

### Design

Code already landed in commit `e866f7c`. When `bcm4360_test276_shared_info=1`:
1. Before `brcmf_chip_set_active` (after FORCEHT): `dma_alloc_coherent(64 KB)` + memset zero + write olmsg ring header (2 rings × 16 B + 2×30 KB data areas).
2. Zero shared_info TCM region `[ramsize-0x2F5C..ramsize-0x20)` (0x2F3C bytes).
3. Write 6 fields: magic_start (0xA5A5A5A5), dma_lo, dma_hi, buf_size (0x10000), fw_init_done (0), magic_end (0x5A5A5A5A).
4. Readback-verify ALL 6 fields (not just magic — DMA_LO/HI are what fw uses).
5. Call `brcmf_chip_set_active` (standard T238 path).
6. Poll post-release at 10 ms intervals for 2 s: read si[+0x010], fw_init_done, MAILBOXINT. Log on any change (don't break — Phase 4B saw multiple signals). Print final snapshot always.
7. Proceed into T238 ultra-dwell ladder as normal.

Cleanup: `dma_free_coherent` in `brcmf_pcie_release_resource` (covers remove + probe-failure paths).

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.276.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.276.run.txt || true
sudo journalctl -k --since "5 minutes ago" > /home/kimptoc/bcm4360-re/phase5/logs/test.276.journalctl.txt
```

Same skeleton as T270-BASELINE + the T276 param. 150 s covers chip_attach + shared_info write (~1 s) + set_active + 2 s T276 poll + full T238 ladder to t+120s = ~140 s expected.

### Expected artifacts

- `phase5/logs/test.276.run.txt`
- `phase5/logs/test.276.journalctl.txt`

### Safety

- Same T270-BASELINE envelope + DMA alloc + TCM writes into a region no other Phase 5 code touches (T234 gated off when test236=1, verified).
- No MSI, no `request_irq` — deliberately orthogonal to the T264-T266 MSI-wedge issue.
- Worst case: host wedge in [t+90s, t+120s] matching T270-BASELINE; platform watchdog recovers.

### Pre-test checklist

1. **Build**: ✓ committed (e866f7c); modinfo shows `bcm4360_test276_shared_info`; 5 test.276 strings visible.
2. **PCIe state** (at 10:50 BST): `Mem+ BusMaster+`, no MAbort+. **Clean per registers.**
3. **Substrate**: ⚠ ~3 h post-cycle (boot 0 up since 07:59 BST). **Outside T270-BASELINE's 20-min clean window.** T269 drift pattern: at 23 min post-cycle, crash window halved. At 3 h, drift is expected dominant. Signal likely muddied.
4. **Hypothesis**: this block.
5. **Plan**: this block (committed before fire).
6. **Recommendation**: **cold power cycle before fire** for cleanest read. Without a cold cycle, a null result would be ambiguous (drift vs no-response); firing inside the clean window gives the diagnostic its full power.

### Fire conditions

Do NOT fire until: (a) fresh cold cycle completed (boot 0 of a power-off session), and (b) fire within ~20 min of that boot. If substrate budget is limited, this test gets priority over any scaffold variant — T276 is the next gating evidence for the whole Phase 5 protocol model.

---

## POST-TEST.276 (2026-04-24 11:06 BST fire, boot -1 — **Phase 4B Test.28 handshake REPRODUCES: si[+0x010]=0x0009af88 (exact match). Row 3 outcome: fw wrote status, NO mailbox signals. Protocol anchor confirmed under Phase 5 patches. Late-ladder wedge unchanged from T270-BASELINE.**)

### Timeline (from `phase5/logs/test.276.journalctl.txt`, boot -1)

- `11:06:03` module_init entry
- `11:06:05` pci_register_driver
- `11:06:13..21` SBR, chip_attach, 6 cores enumerated, fw download (test.225 chunked 110558 words ✓), NVRAM write (228 bytes), random_seed footer (magic 0xfeedc0de, len 0x100)
- `11:06:22` FORCEHT applied — clk_ctl_st `0x01030040 → 0x010b0042` (HAVEHT=YES, ALP_AVAIL=YES, FORCEHT=YES)
- `11:06:22` **T276 shared_info written at TCM[0x9d0a4], olmsg_dma=0x8a160000, size=65536**
- `11:06:22` **T276 readback verified ALL 6 fields**: magic_start=0xa5a5a5a5 ✓, dma_lo=0x8a160000 ✓, dma_hi=0x00000000 ✓, buf_size=0x00010000 ✓, fw_init_done=0 ✓, magic_end=0x5a5a5a5a ✓
- `11:06:22` test.238: `brcmf_chip_set_active returned TRUE`
- `11:06:22` **T276 poll t+0ms: `si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000`** ← fw responded immediately
- `11:06:25` **T276 poll-end (2s later): `si[+0x010]=0x0009af88 fw_done=0x00000000 mbxint=0x00000000`** — no further change
- `11:06:25 → 11:07:56` T238 ladder: t+100ms → t+300 → t+500 → t+700 → t+1s → t+1.5s → t+2s → t+3s → t+5s → t+10s → t+15s → t+20s → t+25s → t+26-30s → t+35s → t+45s → t+60s → **t+90000ms**
- `11:07:56` **LAST MARKER: `t+90000ms dwell`** — 22 dwells completed (matches T270-BASELINE)
- [silent wedge; expected t+120000ms never fired]
- `11:09:35` platform watchdog reboot

### Direct comparison vs T270-BASELINE (2026-04-24 07:54 fire)

| Metric | T270-BASELINE | T276 | Delta |
|---|---|---|---|
| last marker | t+90000ms dwell | t+90000ms dwell | **identical** |
| elapsed set_active → last marker | 91 s | 94 s | +3 s (jitter) |
| wedge window | (t+90s, t+120s] | (t+90s, t+120s] | **identical** |
| si[+0x010] pre-fire | (no write, field was pre-existing/0) | **0x0009af88 at t+0ms** | **fw responded** |
| MAILBOXINT | (not polled) | **0 for 2 s** | new negative data |
| recovery | watchdog + cold cycle | watchdog | clean so far |

### Direct comparison vs Phase 4B Test.28 (2026-04-13, different code path)

| Observation | Phase 4B Test.28 | T276 | Match? |
|---|---|---|---|
| si[+0x010] value | **0x0009af88** | **0x0009af88** | ✓ **EXACT MATCH** |
| Timing of si[+0x010] write | "within ≥2 s stable window" | **t+0ms (before first 10 ms poll tick)** | T276 tighter bound |
| MAILBOXINT post-run | `0x00000003` (2 bits set) | `0x00000000` | ✗ differs |
| fw_init_done | 0 (not set) | 0 | ✓ both unset |
| Fw stable for ≥2 s after ARM release | YES | YES | ✓ |

### What T276 settled (factually)

1. **The shared_info protocol anchor is REAL and consistent across fw states.** Whatever code in fw consumes shared_info and writes back `0x0009af88` at `+0x010` ran identically at 2026-04-13 (Phase 4B test module, minimal harness) and 2026-04-24 (Phase 5, with NVRAM/random_seed/FORCEHT patches layered on). The response is identical to the bit. Fw is genuinely listening at this interface.
2. **The response is very early post-ARM-release.** Inside our first 10 ms poll tick — well before most fw init steps. Consistent with shared_info being a startup gate, not a late-init feature.
3. **Phase 5's added patches do NOT reroute fw past this check-point.** The earlier belief ("Phase 5 fw is further along so Phase 4B observations may not apply") is weakened — at least for the shared_info field, Phase 5 fw behaves the same.
4. **T276 did NOT reproduce Test.28's mailbox signals.** Test.28 ended with `MAILBOXINT=0x00000003` (bits 0+1 set). T276 saw 0 bits set across the full 2 s poll. Plausible reasons:
   - Test.28 did additional steps after ARM release that T276 doesn't (the Phase 4B harness may have driven extra writes that triggered these signals).
   - Our 2 s poll missed a transient (fw set-and-cleared within <10 ms) — unlikely since fw is supposedly stable in this window.
   - Phase 5 fw state differs in a way that produces si[+0x010] response but not mailbox signals — possible but counter to point 3.
5. **T276 did NOT avoid or change the late-ladder crash.** Same wedge window `[t+90s, t+120s]` as T270-BASELINE. Whatever is wedging the host in that window is orthogonal to the shared_info handshake.
6. **The 64 KB olmsg DMA buffer was allocated, published to fw, and fw did NOT read or write it** (no pointer updates in si[+0x010] beyond the immediate 0x0009af88, which is a TCM address — 0x9af88 is below ramsize 0xa0000 — not our DMA address 0x8a160000). Same observation as Phase 4B Test.29 (ring unused).

### Pointer 0x0009af88 — what is it?

`0x9af88` is a TCM address (< ramsize 0xa0000). Note: this is **inside** the TCM but 0x211C bytes BEFORE shared_info base (0x9d0a4). Phase 4B called it a "console struct pointer." We can't probe it post-crash, but next run could read TCM[0x9af88..0x9aff0] to decode (likely `{buf_addr, buf_size, write_idx, read_addr}` struct per Phase 4B notes).

### What T276 did NOT settle

- Whether the late-ladder crash in [t+90s, t+120s] is fw-side or host-side (T270-BASELINE already raised this; T276 inherits the same gap).
- Why the mailbox signals differ from Test.28 (Phase 5 vs Phase 4 harness diverges somewhere between ARM release and t+2s).
- Whether sending a host action (e.g., writing H2D_MAILBOX_1, or writing into the TCM[0x9af88] console ring) would advance fw further.

### Next-test direction (advisor required)

Several candidates, each diagnostic:

- **T277-CONSOLE-DECODE**: Add a console-struct read at T276 poll time — dump 16 dwords starting at TCM[0x0009af88]. Cheap add to existing T276 code. Decodes the fw-provided pointer, should reveal buf_addr / buf_size / pointer fields matching Phase 4B's console-struct interpretation. Tells us where fw logs go (trap strings, printfs) → we can then READ fw's post-ARM-release internal log, which is far more informative than register polling.
- **T278-MBXINT-WIDEPOLL**: Re-run T276 with finer-granularity MAILBOXINT polling (every 1 ms × 100 iterations + every 10 ms × 200 iterations, plus H2D/D2H mailbox-mask registers). Tests whether Test.28's 2-bit mailbox signal is a transient we missed, or truly absent in the Phase 5 path.
- **T279-OLMSG-READ**: Add DMA-buffer readback to T276 — scan the 64 KB olmsg buffer for any fw writes. Confirms the Test.29 finding ("fw did not write olmsg") under Phase 5 conditions.
- **T280-STICK-WAIT**: Extend post-release wait to 10-30 s instead of 2 s, then probe shared_info + MAILBOXINT. Tests whether fw's signal was outside our 2 s window.

T277 is likely the highest-value (opens up the fw's internal console; may reveal assert/trap messages explaining the late-ladder wedge).

### Safety + substrate

- T276 consumed ~2 min of substrate; we're now ~5 min into boot 0. Substrate window is still fresh if we want another fire soon.
- T270-BASELINE finding holds: cold cycle → ~20 min clean window → drift reasserts. Current boot 0 is a post-crash watchdog recovery, not a cold cycle; substrate integrity for a second fire is uncertain (in T269 the 2nd post-cycle fire had drift; T270's 2nd cycle was user-cold-cycled for cleanness).

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.276.journalctl.txt` (1417 lines).
- Run output captured: ✓ `phase5/logs/test.276.run.txt` (2 lines — insmod entry/return).
- Outcome matrix resolved: ✓ **row 3** ("Only si[+0x010] nonzero; no mbxint") — with the added refinement that si[+0x010] value is the EXACT Phase 4B Test.28 value.
- Ready to commit + push + sync.

---

### Hypothesis

Four consecutive T265-T268 fires crashed progressively earlier, with T268 finally failing on a host-only pre-firmware path that worked 24 minutes earlier. A full cold power cycle (shutdown + unplug + 60s + SMC reset) resets chip/PCIe endpoint rails that platform watchdog reboots don't. Prediction: the baseline T218 ultra-dwell path that was reliable earlier in the session now works again.

### Design

Bare-minimum insmod — only the two params that establish the known-good path:
- `bcm4360_test236_force_seed=1` — standard seeding
- `bcm4360_test238_ultra_dwells=1` — ultra-dwell ladder (the verified-reliable path from session start)

No scaffold (T259/T265/T266/T267/T268 all off). No probe extensions. Module unchanged (ko built at 01:33 for T268; T268 code is gated behind its own param, so leaving `bcm4360_test268_early_scaffold=0` = identical control flow to pre-T268 code).

### Outcome matrix

| Outcome | Reading |
|---|---|
| Reaches end of ultra-dwells, rmmod succeeds | Substrate good. Re-fire T268 next. |
| Crashes at `after reset_device return` again | Hardware in bad state; escalate to user. |
| Crashes elsewhere in mid-ladder | Partial drift; discuss with advisor before next fire. |

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.baseline-postcycle.journalctl.txt`
- `phase5/logs/test.baseline-postcycle.run.txt`

### Pre-test checklist

1. **Build**: already built at 01:33 (T268 code present but gated off via unset param).
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort).
3. **Hypothesis**: cold power cycle restores substrate → baseline path traverses end-to-end again.
4. **Plan**: this block (committed before fire).
5. **Host state**: boot 0, up since 06:29 BST.

---

## POST-TEST.BASELINE-POSTCYCLE (2026-04-24 06:32 BST run — **Substrate good; crash migrates from scaffold region to late-ladder (t+90→t+120s) under pure ladder config.**)

### Timeline (from `phase5/logs/test.baseline-postcycle.journalctl.txt`)

- `06:32:44` insmod entry
- `06:32:49` full probe path traversed: SBR ✓, chip_attach ✓, **test.125 after reset_device return ✓** (where T268 wedged), get_raminfo ✓, chip_attach returned successfully, ASPM disabled
- `06:33:07` firmware download complete (test.188 fw-sample MATCH entries), `chip_set_active returned TRUE`
- `06:33:07–06:34:35` T238 ladder progression: t+100ms → t+500ms → t+2000ms → t+10s → t+30s → t+45s → t+60s → t+90000ms
- `06:34:35` **LAST MARKER: `t+90000ms dwell`**
- [silent lockup, no further kernel output; expected next marker t+120000ms never fires]
- `06:47` platform watchdog reboot

Crash window: [t+90000ms marker fired, t+120000ms marker never fired] — crashed somewhere in the ~30s gap between these two dwell points.

### What baseline did NOT have (significant)

- NO scaffold (T259/T265/T266/T267/T268 all OFF)
- NO MSI enable, NO request_irq, NO interrupt-handler registration
- NO T239 poll_sharedram, NO T240 wide_poll, NO T247 preplace_shared, NO T248 wide_tcm_scan

Pure T238 ultra-dwell ladder with T236 seed. Minimal config.

### Key reinterpretation

The late-ladder crash window (t+90s → t+120s) is reached under the bare T238 ladder. **Prior test crashes in this same window have been attributed to various scaffold/param combinations, but the ladder alone is sufficient.** This substantially weakens the "scaffold is the crasher" framing that guided T265-T268.

Previous interpretations that should now be questioned:
- T267's "mid t+120000ms probe burst" crashes may be intrinsic to the ladder, not caused by the scaffold.
- T265/T266 msleep-based framing only holds IF the scaffold actually reaches execution — in this pure-ladder run, no scaffold is present.
- T264's "duration-proportional" phrasing conflated scaffold duration with total-elapsed-time; the crash may be elapsed-time-based regardless of scaffold.

### What baseline settled (factually)

- **Cold power cycle cleared the T268-stage host-path drift.** The `after reset_device return` wedge is state-dependent and can be reset by full AC disconnect + 60s wait + SMC reset.
- **The t+90s→t+120s crash window is reproducible WITHOUT the scaffold.** This is a new data point not previously isolated.

### What baseline did NOT settle

- Whether the crash is at a fixed wall-clock time (~2min post-insmod / ~90-120s post-set_active) or depends on cumulative MMIO activity.
- Which operation inside the t+90→t+120 window triggers the crash (the ladder has minimal activity in this interval — mostly sleep).
- Whether simply extending the interval would still crash in the same window if more granular markers were inserted.

### Next-test direction (advisor required)

The framing shift is large enough that I shouldn't pick the next test alone. Options:
- **B-variant: bisect the t+90→t+120 window** with extra dwell markers at t+95s, t+100s, t+105s, t+110s, t+115s, t+120s. Single-param change to T238. Tells us whether the crash is at a specific sub-window.
- **B-variant: cut the ladder short at t+90s and rmmod cleanly.** Does the cleanup path work if we exit before the crash window? High-value — if rmmod succeeds, confirms the crash is elapsed-time/ladder-work related, and gives us a stable baseline to build on.
- **Reconcile with old "known-good" T218**: earlier in the project T218 was said to reach end-of-ladder reliably. Need to verify that claim vs today's crash.

Consulting advisor next.

### Reconciliation with history (added post-advisor)

Grep across `test.2*.journalctl.txt`:

| Logs reaching `t+120000ms dwell` | Logs with actual clean rmmod |
|---|---|
| 12/13 (244, 249, 256, 258, 259, 261, 262, 263, 264, 265, 266, 267; only 260 didn't) | **0/13** (cleanup_markers=1 matches were false-positives from unrelated `sd sdb: Media removed` lines) |

So the "T218 / baseline reliably reaches end of ladder" claim that anchored POST-TEST.268's drift framing holds HALFWAY: prior runs do reach t+120000ms dwell marker, but none of them unload cleanly afterward. Every test since 244 crashed somewhere past the t+120000ms marker. Today's baseline-postcycle crashing at t+90→t+120 is slightly earlier than historical (which crashed past t+120), but the crash window is in the same general neighborhood.

Implication: T265-T268 scaffold-attributed crashes were likely the **same late-window host-wedge mechanism** that affects the baseline. The scaffold was never the primary crasher. This validates the framing shift.

---

## PRE-TEST.269 (2026-04-24 06:55 BST, boot 0 — **Early-exit variant: stop the T238 ladder at t+60000ms and return, enabling clean rmmod.**)

### Hypothesis

Baseline reached `t+90000ms dwell` and crashed before `t+120000ms dwell` — a ~30s window that's never been safely traversed. Three mechanisms remain consistent with all evidence to date:

1. **Wall-clock timer**: something fires at ~111-143s after insmod regardless of what code is doing.
2. **Activity-accumulation**: cumulative PCIe/MMIO activity crosses some threshold at this time.
3. **Cleanup-path trigger**: the real crasher is in the BM-clear/release path that runs after the ladder, and the ladder is just "time before cleanup fires".

T269 discriminates cleanly:

| Outcome | Reading |
|---|---|
| Ladder stops at t+60s, BM-clear + chip release + rmmod succeed | **Activity/late-ladder crash avoidable by early exit.** Stable reproducer found. (a) and (b) both consistent; (c) refuted. |
| Ladder stops at t+60s but crash fires ~111-143s after insmod (during BM-clear or after) | **Wall-clock timer confirmed.** (a) confirmed. |
| Crash during rmmod or in BM-clear path itself | **Cleanup path is the real crasher.** (c) confirmed. Rewrites the T265-T268 framing entirely. |

### Design

New param `bcm4360_test269_early_exit`. When set, the T238 ultra-dwells branch:
1. Runs t+100ms through t+60000ms dwells as normal (with all probe helpers invoked at t+60000ms).
2. **`goto ultra_dwells_done`** right after the t+60000ms probes, skipping t+90000ms, t+120000ms, and all scaffold blocks.
3. Normal flow resumes at `ultra_dwells_done:` which runs BM-clear + chip release.

Single variable change from baseline-postcycle: the ladder returns early.

### Safety

- Smallest exposure yet: 60s of ladder vs 120s (baseline-postcycle ran 90s before crash).
- No scaffold, no MSI, no request_irq.
- Platform watchdog reliable on host lockup.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test269_early_exit=1
sleep 100
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

insmod probe thread runs: chip_attach (~25s) + T238 ladder to t+60s (~60s) = ~85s before probe returns. `sleep 100` gives margin, then rmmod.

### Expected artifacts

- `phase5/logs/test.269.journalctl.txt`
- `phase5/logs/test.269.run.txt`

### Pre-test checklist

1. **Build**: module rebuilt; `bcm4360_test269_early_exit` param visible via modinfo; `test.269: early-exit at t+60000ms` marker in .ko strings.
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort) at 06:48 BST.
3. **Hypothesis**: this block.
4. **Plan**: this block (committed before fire).
5. **Host state**: boot 0, up since 06:47 BST.

---

## PRE-TEST.265 (2026-04-24 00:0x BST, boot 0 — **Identical to T264 scaffold but with msleep(500) instead of msleep(2000).** Single-variable change that decouples "duration-proportional" from "fixed timer post-scaffold-entry".)

### Hypothesis

Across T260/T262/T263/T264, intended_duration = scaffold_duration = elapsed_time_at_crash. Three equally-consistent mechanisms remain:
- **(a)** Duration-proportional: crash fires at `intended_duration` after scaffold entry
- **(b)** Fixed timer at ~2s post-scaffold-entry (coincidentally ≥ all intended durations so far)
- **(c)** Crash tied to msleep-exit transition specifically

T265c changes msleep from 2000ms to 500ms. Three outcomes discriminate cleanly:

| Outcome | Reading |
|---|---|
| Crash within ~500ms (before "msleep done" marker) | **(a) confirmed**: duration-proportional. Timer scales with intended sleep. |
| Crash at ~2s (well after msleep returned, during cleanup) | **(b) confirmed**: fixed timer at ~2s post-scaffold-entry. **CLEANUP PATH BECOMES VISIBLE FOR THE FIRST TIME.** Highest-value outcome. |
| Crash at exactly 500ms (msleep-exit wall-clock) | **(c) confirmed**: msleep-exit transition itself. Different mechanism. |
| Clean completion past 2s | Scaffold-duration was load-bearing somehow. Unlikely but possible. |

### Design

Single new module param `bcm4360_test265_short_noloop`. EXACTLY identical to T264 scaffold (pci_enable_msi + request_irq + msleep + cleanup with markers) but msleep is 500ms instead of 2000ms.

Critically: **NO probes, timer reads, or log markers inside the msleep window**. T264 established "no MMIO during sleep" property — preserve it.

### Safety

- Smallest envelope yet. No loop, no MMIO, no writes. MSI + handler + short sleep + cleanup.
- Cleanup markers will fire if cleanup path runs (first-time visibility if outcome (b)).
- Host crash still expected (n=15+ streak at this point). Platform watchdog reliable.

### Code change outline

1. New module param `bcm4360_test265_short_noloop`.
2. Extend T239 ctr gate + T258 buf_ptr probe gate.
3. Add new invocation block mirroring T264 but with msleep(500). Separate from T264 block to keep both accessible.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test265_short_noloop=1
sleep 300
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

T258-T264 NOT set.

### Expected artifacts

- `phase5/logs/test.265.journalctl.txt`
- `phase5/logs/test.265.run.txt`

### Pre-test checklist (pending code+build)

1. **Build status**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: msleep(500) discriminates duration-proportional vs fixed-timer vs msleep-exit-transition.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 00:03 BST.

Advisor-confirmed. Code + build + fire pending. **Duration-anchor framing in POST-TEST.264 should be treated as hypothesis with circumstantial support — T265c is the test that will actually confirm or refute it.**

---

## POST-TEST.265 (2026-04-24 00:11 BST run — **Fixed-timer-at-2s FALSIFIED; duration-proportional NOT yet confirmed.**)

### Timeline (from `phase5/logs/test.265.journalctl.txt`)

- `00:11:31` scaffold entry — `pci_enable_msi=0 prev_irq=18 new_irq=79`, `request_irq ret=0`
- `00:11:31` `entering msleep(500) — no loop, no MMIO`
- [crash]
- `00:12` platform watchdog reboot (host up 00:12)

**No "msleep done" marker**, no `free_irq` or `pci_disable_msi` markers. Silent lockup (no panic/MCE/AER — same pattern as T264).

### What T265 settled (factually)

- **Host crashed inside the 500ms msleep window** (before "msleep done" could fire).
- **Fixed timer at ~2s after scaffold entry is FALSIFIED.** If the trigger were a fixed ~2s timer, T265's 500ms msleep would end at 500ms, cleanup would run, and "msleep done" / `free_irq` markers would print ~1.5s before the crash. They did not. So the trigger fired at some point in [0, 500ms].

### What T265 did NOT settle (advisor calibration)

- Whether the trigger is:
  - (a) Duration-proportional (crashes at ~msleep_duration regardless of what duration is set), OR
  - (a') Fixed timer somewhere in [0, 500ms] (any msleep long enough to contain the timer crashes in the same way)
- These two are indistinguishable with T264 (2000ms) + T265 (500ms) alone. T266 shrinks the bound.

### Surviving candidate mechanisms (after T265)

1. ~~Fixed timer at ~2s post-entry~~ — **FALSIFIED by T265**.
2. Duration-proportional trigger: fires at `~intended_msleep_duration` after scaffold entry.
3. Fixed timer at some time < 500ms after scaffold entry.
4. Msleep-exit-transition specific (crash fires precisely when msleep schedules back in).
5. Cleanup path is crasher (still invisible — no positive evidence either way).
6. PCIe/ASPM L1→L0 retrain during idle msleep (ASPM L1 enabled in LnkCtl).

### Next-test direction (T266 — advisor-confirmed)

Single-variable change from T265: msleep(500) → msleep(50). Shrinks upper bound 10×.

| T266 outcome | Reading |
|---|---|
| Crash within 50ms (no "msleep done") | Trigger fires in [0, 50ms]. Either fixed-timer-<50ms or proportional. At this point the distinction matters less — "soon after request_irq" is the mechanism. |
| Crash at ~500ms (msleep done fires, but before cleanup finishes) | **Fixed timer ∈ [50ms, 500ms]. Duration-proportional FALSIFIED.** Plus cleanup path becomes visible for first time — high-value. |
| Crash at ~2s (msleep done fires AND cleanup runs cleanly, then crashes much later) | Unlikely (contradicts T265 which would have seen same timing) — but would revive candidate (1) indirectly. |
| Clean completion past 2s | Very short scaffold survives. Opens new questions. |

### Safety

- Same safety envelope as T264/T265. Smaller msleep = less time in MSI-bound state.
- Host crash likely (n=16+ streak). Watch for hardware drift (advisor flagged): if T266 produces non-reproducible results, re-fire before building on them.

### Code change

Extension of existing T265 block OR new param. Simplest: add `bcm4360_test266_ultra_short_noloop` mirroring T265 but msleep(50).

---

## PRE-TEST.266 (2026-04-24 00:1x BST, boot 0 — **msleep(50) variant to shrink upper bound of trigger time 10×.**)

### Hypothesis

T264 (msleep 2000) + T265 (msleep 500): crash within the intended sleep window. Fixed-timer-at-2s falsified. Still coupled: duration-proportional vs fixed-<500ms. T266 = msleep(50) shrinks bound.

### Design

Mirror of T265 block with msleep(50). No other changes. Same markers. Same cleanup.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test266_ultra_short_noloop=1
sleep 200
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.266.journalctl.txt`
- `phase5/logs/test.266.run.txt`

### Pre-test checklist

1. **Build**: NOT yet rebuilt.
2. **PCIe**: verify clean before fire.
3. **Hypothesis**: msleep(50) outcome discriminates proportional vs fixed-<500ms.
4. **Plan**: this block (committed before code).
5. **Hardware drift awareness**: n=16+ crashes today — if T266 produces weird results, re-fire once before claiming anything.

Advisor-confirmed. Code + build + fire pending.

### PCIe state check before T266 fire (2026-04-24 00:1x BST)

**PCIe DIRTY after T265 auto-reboot**: `03:00.0 Control: Mem- BusMaster-`, BARs `[disabled]`, `LnkCtl: ASPM Disabled`, `CommClk-`. BCM4360 endpoint unresponsive. Platform watchdog reboot did not fully recover chip state.

**SMC reset needed** before firing T266. *SMC reset completed by user at 00:23 BST; boot 0 came up with device visible at config space. Firing T266.*

---

## POST-TEST.266 (2026-04-24 00:26 BST run — **msleep(50) also crashes inside its own sleep window. Upper bound now ≤50ms.**)

### Timeline (from `phase5/logs/test.266.journalctl.txt`)

- `00:26:14` dwell ladder reached t+120000ms normally (baseline buf_ptr=0x8009CCBE, same as prior runs)
- `00:26:14` scaffold entry — `pci_enable_msi=0 prev_irq=18 new_irq=79`, `request_irq ret=0`
- `00:26:14` `entering msleep(50) — no loop, no MMIO`
- [crash inside 50ms window]
- `00:27` platform watchdog reboot

**No "msleep done" marker.** No free_irq, no pci_disable_msi. Silent lockup — no panic/MCE/AER.

### What test.266 settled (factually)

- Trigger fires somewhere in [0, 50ms] after scaffold entry (after `request_irq` returned).
- Same pattern as T264 (2s) and T265 (500ms): crash always within the intended msleep window; "msleep done" never fires.
- **Upper bound compressed 40× across three tests** (T264 2000ms → T265 500ms → T266 50ms).

### What test.266 did NOT settle

- Still coupled: duration-proportional trigger vs fixed-timer-<50ms. At this bound the distinction starts mattering less — any fixed timer under 50ms looks "nearly immediate".
- Which of `pci_enable_msi`, `request_irq`, or "being MSI-bound" is the essential trigger component.
- Whether crash fires during the msleep, or precisely at msleep-exit (<50ms granularity is insufficient here).

### Surviving candidate mechanisms (after T266)

1. ~~Fixed timer at ~2s~~ — FALSIFIED by T265.
2. **Near-instant trigger within [0, 50ms] of request_irq returning.** Mechanism unknown — could be MSI routing, first IRQ arrival, ASPM state transition, or something else tied to the IRQ subscription.
3. **Duration-proportional trigger** (crash at ~intended_duration). Still plausible but narrowing — at msleep(50) the delta from request_irq is only 50ms.
4. **Msleep-exit-transition specific**: the moment the scheduler resumes the task after msleep completes, some state is fatal.
5. **Cleanup path still invisible**: we've never seen cleanup markers fire, which is consistent with either "crash happens first" (candidates 2/3/4) or "cleanup fires the crash".

### Next-test direction (T267 — advisor call before committing)

Candidate tests to isolate the trigger component:

- **T267a: no msleep at all.** Scaffold = pci_enable_msi + request_irq + IMMEDIATE free_irq + pci_disable_msi. If cleanup markers fire → trigger requires "being MSI-bound for some time". If crashes before any marker → trigger is immediate upon request_irq.
- **T267b: pci_enable_msi only** (no request_irq). Enables MSI, small sleep, disables MSI. Tests whether MSI enablement alone triggers.
- **T267c: request_irq on legacy INTx** (no pci_enable_msi). Tests whether request_irq alone (without MSI) triggers. Requires driver code restructuring.

Most discriminating single test: probably T267a (smallest envelope, fastest check, directly answers "is msleep necessary").

Advisor call before committing to T267 design.

---

## PRE-TEST.267 (2026-04-24 00:3x BST, boot 0 — **No-msleep variant: MSI + request_irq + IMMEDIATE free_irq + pci_disable_msi. Existing cleanup markers give 5-position crash discrimination. Clean completion = msleep-duration is necessary (highest-value outcome).**)

### Hypothesis

T264/T265/T266 all crash inside intended msleep window; upper bound ≤50ms. Remaining question: is msleep's duration essential, or is the trigger fired by request_irq / MSI setup itself?

T267a removes msleep entirely. The sequence becomes purely: request_irq → free_irq → pci_disable_msi. Each transition has an existing marker.

### Design (no code size change — reuse T264 block pattern)

```
pci_enable_msi                          [marker A: pci_enable_msi=...]
request_irq                             [marker B: request_irq ret=...]
pr_emerg "skipping msleep; calling free_irq immediately"   [NEW marker]
pr_emerg "calling free_irq"             [marker C]
free_irq                                 —
pr_emerg "free_irq returned"            [marker D]
pr_emerg "calling pci_disable_msi"      [marker E]
pci_disable_msi                          —
pr_emerg "pci_disable_msi returned"     [marker F]
```

### Next-step matrix (advisor-framed)

| Last marker seen | Reading |
|---|---|
| A, B only (no "skipping msleep" print) | Crash between request_irq and next pr_emerg. Very tight window — trigger is ~immediate upon request_irq return. |
| B + "skipping msleep" + C | Crash in free_irq. |
| C + D | Crash between free_irq and pci_disable_msi — unexpected. |
| D + E | Crash in pci_disable_msi. |
| D + E + F (all markers fire, module unloads) | **msleep duration is necessary for crash trigger.** Highest-value outcome. Time-in-MSI-bound-state matters. Re-fire once to confirm (n=2). |

### Safety

- Smallest scaffold yet — no sleep between request_irq and free_irq.
- Cleanup path runs under every conceivable timer-firing-time <50ms.
- Host crash still likely but uncertain. Re-fire required if all markers fire (first clean completion would be headline finding; n=1 insufficient).

### Code change outline

1. New param `bcm4360_test267_no_msleep`.
2. Extend T239 ctr gate + T258 buf_ptr probe gate.
3. Add scaffold block mirroring T264 but with msleep call REPLACED by a new "skipping msleep" pr_emerg marker.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test267_no_msleep=1
sleep 200
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Expected artifacts

- `phase5/logs/test.267.journalctl.txt`
- `phase5/logs/test.267.run.txt`

### Pre-test checklist

1. **Build**: NOT yet rebuilt.
2. **PCIe state**: verify clean before fire.
3. **Hypothesis**: stated — 5-position discrimination of crash location.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 00:27 BST.

Advisor-confirmed. Code + build + fire pending.

### T267 first fire (2026-04-24 00:36 BST) — **NULL TEST**

Reached t+120000ms probe burst, printed test.238/239/240/247, crashed before test.249. Normal pacing.

### T267 re-fire (2026-04-24 01:08 BST) — **ALSO NULL TEST, different crash position**

Reached t+120000ms probe burst, printed test.238/239/240, crashed before test.247 (earlier than first fire). Normal pacing. Scaffold never ran again.

### Consolidated observation: hardware drift

Two consecutive null-test fires of T267 crashed at DIFFERENT positions within the t+120000ms probe burst (after test.247 vs after test.240). Earlier today T264-rerun, T265, T266 all successfully ran their scaffolds at this same point.

Interpretation: **hardware drift is now actively polluting signal.** Advisor flagged this risk at n=16+ wedges. We're now at n=22+. The BCM4360 chip and/or PCIe bridge state is degraded.

Options:
1. Extended idle period + SMC reset + full power cycle (let chip cool, let BMC fully reset state).
2. Pivot test strategy: run tests that don't need the full 120s dwell ladder — move the scaffold much earlier to minimize accumulated stress per test.
3. Accept this investigation has reached its practical limit for today; preserve state and resume after longer cool-down.

**Not firing again without advisor consultation.** Pausing here to avoid further hardware stress while state is drifting.

### Advisor reframe + T268 pivot (2026-04-24 01:2x BST)

Advisor pushed back on "hardware drift" framing. Real read: t+120000ms probe burst region is **marginal** (6/9 pass today). Fix is the same either way: **pivot the scaffold out of the flaky region entirely.**

The scaffold is a pure host-side MSI/request_irq test. It doesn't need the 120s dwell ladder (which exists for fw-state probing, a different question). Move the scaffold to run **right after `brcmf_chip_set_active()` returns TRUE**, before the dwell ladder starts. ~10× less exposure per test, identical scaffold evidence, duration-scaling results from T264/T265/T266 still compose.

---

## PRE-TEST.268 (2026-04-24 01:2x BST, boot 0 — **Early-scaffold pivot: run T267-style MSI + request_irq + immediate cleanup RIGHT AFTER `brcmf_chip_set_active` returns, skip the dwell ladder entirely.** 10× less exposure; same scaffold test.)

### Hypothesis

T267's scaffold would have given 5-position crash discrimination, but two consecutive T267 fires both crashed in the t+120000ms probe burst (the shared dwell-ladder exit region). T268 moves the scaffold to a quieter time window: right after chip activation, before any dwell probes.

If T268 crashes inside scaffold: we get the same discrimination T267 was meant to provide. 
If T268 completes cleanly: the msleep-duration hypothesis from T264-T266 stands — crash requires being MSI-bound long enough for a timer to fire.

### Design

New param `bcm4360_test268_early_scaffold`. When set:

1. Dwell ladder entry prints `brcmf_chip_set_active` call + TRUE/FALSE marker (unchanged).
2. **Skip the entire dwell ladder.** `goto ultra_dwells_done`.
3. Run the exact same scaffold as T267: `pci_enable_msi` + `request_irq` + IMMEDIATE `free_irq` + `pci_disable_msi`, all markers bracketed.
4. Proceed to BM-clear + chip release (unchanged — this is what runs after `#undef BCM4360_T239_POLL`).

Conceptually this is `bcm4360_test267_no_msleep=1` but with the scaffold running 2 minutes earlier (right after chip activation, ~15s into insmod instead of ~2min).

### Next-step matrix

| Outcome | Reading |
|---|---|
| All 6 scaffold markers fire, module unloads | **msleep duration is necessary** for crash trigger. Headline finding. Re-fire once. |
| Crash between markers A-B, B-C, C-D, D-E, or E-F | 5-position discrimination fires — tells us exactly where in pci_enable_msi / request_irq / free_irq / pci_disable_msi the crash happens. |
| Crash before scaffold entry (in probe path earlier than scaffold) | Same flaky region hit again; investigate further. |

### Safety

- Scaffold envelope unchanged from T267; just moved earlier.
- Skips 120s of MMIO reads — less exposure to the marginal region that failed T267 twice.
- Same cleanup (free_irq + pci_disable_msi) before BM-clear/chip release.

### Code change outline

1. New module param `bcm4360_test268_early_scaffold`.
2. Insert `if (bcm4360_test268_early_scaffold) { scaffold; goto ultra_dwells_done; }` right after `brcmf_chip_set_active returned TRUE/FALSE` prints at line ~3713.
3. Add label `ultra_dwells_done: ;` right before `#undef BCM4360_T239_POLL` at line ~4048.
4. Build + verify modinfo + strings.

### Run sequence

```bash
sudo insmod .../brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test268_early_scaffold=1
sleep 30
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

No probe params needed — we're skipping the ladder. `sleep 30` gives init + chip_set_active + scaffold time to run (should be <20s).

### Expected artifacts

- `phase5/logs/test.268.journalctl.txt`
- `phase5/logs/test.268.run.txt`

### Pre-test checklist (pending code+build)

1. **Build**: NOT yet rebuilt.
2. **PCIe state**: verified clean (Mem+ BusMaster+, no MAbort).
3. **Hypothesis**: move scaffold out of marginal ladder region; 5-position discrimination retained.
4. **Plan**: this block (committed before code).
5. **Host state**: boot 0 up since 01:15 BST.

Advisor-confirmed. Code + build + fire pending.

---

## POST-TEST.268 (2026-04-24 01:33 BST run — **Null test: crashed before scaffold could run, before firmware download, before `chip_set_active`.**)

### Timeline (from `phase5/logs/test.268.journalctl.txt`)

- `01:33:32` insmod entry, test.188 module_init entry
- `01:33:33–01:33:43` normal path: SDIO register, PCI register, probe entry, SBR, chip_attach, BAR0 probes, 6 cores enumerated
- `01:33:43` `test.125: buscore_reset entry, ci assigned`
- `01:33:43` `test.122: reset_device bypassed; probe-start SBR already completed`
- `01:33:46` `test.125: after reset_device return` — **LAST MARKER**
- [silent lockup, no further kernel output]
- `01:34+` platform watchdog reboot

### Key observation

The next expected marker after `after reset_device return` is `test.125: after reset, before get_raminfo` (seen in T267 journal at 01:09:00 → 01:09:03, a ~3s gap). T268 never produced that marker.

Crash happened in the 3-second window between `buscore_reset` returning and `get_raminfo` being called — **host-side code path with zero involvement of firmware, scaffold, or dwell ladder**. The plainest failure path seen so far.

### What T268 did NOT settle

- **T268 scaffold never executed.** Any msleep-duration / cleanup-path / fixed-timer claim remains unresolved from T264-T266.

### Crash-stage trend (hardware marginality escalating)

| Fire | Last marker before crash | Stage |
|---|---|---|
| T265 | `entering msleep(500)` (scaffold running) | post-firmware-download, inside scaffold window |
| T266 | `entering msleep(50)` (scaffold running) | same |
| T267 #1 | mid t+120000ms probe burst | dwell ladder late |
| T267 #2 | mid t+120000ms probe burst (different position) | dwell ladder late |
| T268 | `test.125: after reset_device return` | pre-firmware-download host path |

Four consecutive fires crashed progressively earlier. T268's crash is in a host-only code path — no scaffold, no firmware, no probes.

### Surviving hypotheses (unchanged from POST-TEST.266)

1. Duration-proportional trigger in scaffold window
2. Fixed timer in [0, 50ms]
3. Msleep-exit transition
4. Cleanup path crasher
5. PCIe/ASPM L1 retrain

**None of these were tested by T268.**

### Next-test direction (advisor required)

Possible pivots:
- **Cold-baseline re-fire**: fire T218 baseline (no scaffold) to see if plain probe path is reliably failing.
- **Even-earlier scaffold (T269)**: scaffold right after SBR — but T268's crash is in buscore_reset→get_raminfo, so scaffold would need to move even earlier in the probe path.
- **Abandon scaffold line temporarily**: step back to passive T218 observation.
- **Full power cycle / longer cool-down** before next fire — hardware thermal/state drift.

Consulting advisor next.

---

## POST-TEST.269 (2026-04-24 06:56-06:57 BST run — **Ladder crashed at `t+45000ms dwell`; never reached the t+60000ms early-exit. Zero evidence for or against the early-exit hypothesis. Significantly EARLIER than baseline-postcycle 23 min prior on identical code — hardware drift signal reasserted.**)

### Timeline (from `phase5/logs/test.269.journalctl.txt`, boot -1)

- `06:56:24` insmod entry, SBR, chip_attach, FORCEHT, `brcmf_chip_set_active returned TRUE`
- `06:56:24 → 06:57:10` T238 ladder progressed t+100ms → t+300 → t+500 → t+700 → t+1000 → t+1500 → t+2000 → t+3000 → t+5000 → t+10000 → t+15000 → t+20000 → t+25000 → t+26s → t+27s → t+28s → t+29s → t+30000 → t+35000 → **t+45000ms** dwell
- `06:57:10` **LAST MARKER: `t+45000ms dwell`**
- [silent lockup; no further kernel output; expected next markers t+50000ms / t+60000ms never fired]
- `07:02:51` platform watchdog reboot (boot 0)

### What T269 settled (factually)

- **The crash time halved vs baseline-postcycle.** Comparison of runs on identical code (T269 diverges from baseline only at t+60000ms; crash happened at t+45000ms before the divergence):
  - `baseline-postcycle` (06:33:07 set_active) → crashed between `t+90000ms` (06:34:35) and `t+120000ms` → **survived ~88s of ladder**
  - `T269` (06:56:24 set_active) → crashed between `t+45000ms` (06:57:10) and `t+50000ms` → **survived ~46s of ladder**
  - Same host, same hardware, same code up to the crash point, runs 23 minutes apart → clear drift signal.

- **Early-exit hypothesis: UNTESTED.** T269 never reached the t+60000ms branch point. All three outcomes enumerated in PRE-TEST.269 are neither confirmed nor refuted.

- **PCIe state clean on next boot.** Post-crash boot 0 shows `Mem+ BusMaster+`, no MAbort — the lockup left PCI config space intact (watchdog reboot cleared it).

### What T269 did NOT settle

- Whether the crash is wall-clock-based (fires ~N seconds after insmod regardless of what code does), activity-accumulation-based (crosses a cumulative-MMIO threshold), or cleanup-path-based.
- Whether the early-exit would have completed cleanly had the ladder reached it — cannot test this path under current hardware state.

### Drift pattern (today's run history)

| Run | Time | set_active | Last marker | Elapsed-at-crash |
|---|---|---|---|---|
| T267 #1 | 00:36 BST | ✓ | mid t+120000ms probe burst | ~130s |
| T267 #2 | 01:08 BST | ✓ | mid t+120000ms probe burst (earlier position) | ~125s |
| T268 | 01:33 BST | ✗ (never reached) | `after reset_device return` (pre-fw) | ~3s |
| baseline-postcycle | 06:33 BST (post cold power cycle) | ✓ | t+90000ms dwell | ~88s |
| T269 | 06:56 BST | ✓ | t+45000ms dwell | ~46s |

Cold power cycle at 06:30 BST gave **one** clean late-ladder traversal (baseline-postcycle), then drift restored within 23 min. This is consistent with T267's "hardware drift actively polluting signal" finding — the cold cycle's effect is transient.

### Surviving candidate mechanisms (unchanged from POST-BASELINE-POSTCYCLE, still no evidence for any)

- Wall-clock timer (but now timing varies widely — 46s vs 88s — suggesting not fixed)
- Activity-accumulation (plausible but the two runs had very similar MMIO patterns up to t+45s)
- Cleanup-path crasher (still unreachable)

### Next-test direction (advisor required — drift dominates signal)

Options to consider:

1. **Another cold power cycle + immediate re-fire of T269** (n=2 reproducibility check of the early-exit hypothesis). If hardware behaves like baseline-postcycle did (one clean run after cold cycle), T269 may succeed. Risk: drift back by second fire.
2. **Re-fire baseline (no T269 variant) after cold cycle**, to check whether the drift reading holds (is the "clean run" reproducible at all, or did baseline-postcycle get lucky?).
3. **Pause hardware tests entirely**; pivot to firmware-blob analysis (the T253-T255 thread on wlc_phy_attach internals was deferred when hardware leads opened). This is the lowest-cost option and doesn't consume hardware state.
4. **Extended cool-down** (hours, not minutes) before any further hardware fire.

Today's n-of-wedges is now 23+. Hardware signal is noisy and getting noisier.

Consulting advisor next.

---

## PRE-TEST.270-BASELINE (2026-04-24 07:52 BST, boot 0 after second cold power cycle at ~07:47 BST — **Reproducibility check: fire bare baseline config (no T269, no scaffold, no probes) and see if baseline-postcycle's t+90s clean traversal reproduces post-cold-cycle.**)

### Hypothesis

The 06:33 BST baseline-postcycle run reached `t+90000ms dwell` cleanly after a cold power cycle at 06:30 BST. T269 fired 23 min later (still within same cold-cycle session) crashed at `t+45000ms` — drift returned within ~25 min.

If baseline-postcycle's clean run was substrate-driven (post-cold-cycle is reliably clean for ~20 min), this fire will reproduce: ladder runs t+100ms → t+90000ms cleanly, host wedges in [t+90s, t+120s], platform watchdog reboots.

If it was circumstantial (one lucky roll), this fire will wedge earlier — anywhere from mid-probe-path to mid-ladder — and the whole T265–T269 framing built on "cold cycle restores substrate" needs re-examination.

### Design

Single-variable — strict reproduction of 06:33 BST config:
- `bcm4360_test236_force_seed=1` — standard seeding.
- `bcm4360_test238_ultra_dwells=1` — ultra-dwell ladder to t+120s.
- No probe params, no scaffold params (T259/T265/T266/T267/T268/T269 all OFF).

Same module .ko (built 01:33, bit-for-bit identical to baseline-postcycle's and T269's). All new params gated off = identical control flow.

### Outcome matrix

| Outcome | Reading | Follow-up |
|---|---|---|
| Reaches `t+90000ms dwell`, wedges in [t+90s, t+120s] like 06:33 | Substrate-bounded. Clean post-cold-cycle run reproducible. Can build on this substrate (careful). | Advisor + consider T270 with scaffold variant on this now-validated substrate. |
| Crashes earlier in ladder (t+X000ms, X<90) | 06:33 was lucky; drift already active. Scaffold-driven framing of T265–T269 needs re-examination. | Stop firing today; pivot to fw-blob (task phase6/t269_fw_blob_diss.md). |
| Crashes in probe path before set_active | Different hardware state from 06:33; chip/bridge in a harder-to-recover state. | Escalate to user; longer cool-down; no more fires today. |

### Pre-test checklist

1. **Build status**: VERIFIED. modinfo shows `bcm4360_test236_force_seed` and `bcm4360_test238_ultra_dwells`. No rebuild.
2. **PCIe state**: VERIFIED clean at 07:52 BST — `Mem+ BusMaster+`, no `MAbort+` / `CommClk-` / `>SERR-` / `<PERR-`.
3. **Hypothesis**: this block.
4. **Plan**: this block (committing before fire).
5. **Host state**: boot 0, up since 07:50 BST. Fresh cold cycle completed at ~07:47 BST (boot -1 was a transient 17s boot, then cold cycle, then boot 0).
6. **Task brief**: `phase6/t269_baseline.md` (committed 6e9645d).

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.270-baseline.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.270-baseline.run.txt || true
```

### Expected artifacts

- `phase5/logs/test.270-baseline.journalctl.txt`
- `phase5/logs/test.270-baseline.run.txt`

### Safety

- Smallest envelope available. No scaffold. No MSI. No request_irq.
- Platform watchdog has been reliable (n=4+ of 4 for host-lockup recovery today).
- Expected worst case: host wedge → watchdog reboot. User not needed unless recovery fails.

---

## POST-TEST.270-BASELINE (2026-04-24 07:54-07:55 BST run — **Reaches `t+90000ms dwell` cleanly, wedges in [t+90s, t+120s] — reproduces 06:33 BST baseline-postcycle within measurement noise. Substrate-bounded reading CONFIRMED.**)

### Timeline (from `phase5/logs/test.270-baseline.journalctl.txt`, boot -1)

- `07:54:05` insmod (per run.txt), FORCEHT, chip_attach, T238 ladder entry
- `07:54:25` `brcmf_chip_set_active returned TRUE`
- `07:54:25 → 07:55:56` T238 ladder traversed t+100ms → t+300 → t+500 → t+700 → t+1000 → t+1500 → t+2000 → t+3000 → t+5000 → t+10000 → t+15000 → t+20000 → t+25000 → t+26000 → t+27000 → t+28000 → t+29000 → t+30000 → t+35000 → t+45000 → **t+60000ms** → **t+90000ms** dwell
- `07:55:56` **LAST MARKER: `t+90000ms dwell`** (22 dwells completed)
- [silent lockup; t+120000ms dwell never fires]
- `07:58:23` platform watchdog reboot (boot 0); user performed cold-cycle between boots based on boot gap

### Direct comparison vs 06:33 BST baseline-postcycle

| Metric | baseline-postcycle (06:33) | T270-BASELINE (07:54) | Delta |
|---|---|---|---|
| set_active TRUE at | 06:33:07 | 07:54:25 | (absolute time only) |
| last marker | `t+90000ms dwell` | `t+90000ms dwell` | **identical** |
| elapsed from set_active to last marker | 88s (06:33:07 → 06:34:35) | 91s (07:54:25 → 07:55:56) | +3s (within ladder-step jitter) |
| wedge window | (t+90s, t+120s] | (t+90s, t+120s] | **identical** |
| ladder markers landed | 22 | 22 | **identical** |
| kernel crash trace | none | none | **identical** |
| recovery | watchdog | watchdog + cold-cycle | (user cold-cycled between boots for cleanness) |

### What T270-BASELINE settled (factually)

- **Clean post-cold-cycle substrate IS reproducible.** Two independent cold-cycle firings, same .ko, same params, ~90 minutes apart, both reach t+90000ms dwell and crash in the same [t+90s, t+120s] window.
- **The 06:33 BST baseline-postcycle run was NOT circumstantial.** The "cold cycle buys ~20-25 min of clean substrate" reading is now substantiated.
- **The T269 result (46s of ladder, 44 min post-cold-cycle, after two watchdog reboots) IS consistent with drift accumulation, not with "baseline is inherently unreliable".**

### What T270-BASELINE did NOT settle

- The t+90→t+120 wedge mechanism itself — still unknown (activity accumulation? wall-clock watchdog? fw-side timer?).
- How many fires the clean substrate tolerates before drift resets (n=1 post-cycle confirmed clean for this cycle; n=2+ behavior unknown).
- Whether the substrate is "clean for time X" or "clean for Y operations" — 06:33 → 06:56 T269 crashed earlier after one intervening boot; was it the time (23 min) or the boot?

### Next-test direction

Code audit (phase6/t269_code_audit_results.md) recommends **Candidate A** as highest-probability scaffold fix: add `init_ringbuffers + init_scratchbuffers` before any T258-style scaffold. Rationale:

- Candidate A addresses the biggest load-bearing skip in our harness vs upstream brcmfmac.
- Without ring+scratch DMA buffers published to TCM, fw has no valid DMA target; any post-doorbell TLP hits unmapped address → with `pci=noaer` cmdline, result is silent wedge (matches observed pattern).
- Cleanly discriminative: if scaffold now completes (markers fire, rmmod succeeds), ring-init was the load-bearing skip. If still wedges, ring-init is ruled out and we focus on ASPM L1 or PMU watchdog.

Audit-recommended fire order now validated (step 1 complete):
1. ✓ Baseline re-fire → substrate confirmed (THIS TEST).
2. **T271**: T266 scaffold + Candidate A (init_ringbuffers + init_scratchbuffers before scaffold).
3. Depending on (2), remove `pci=noaer` (Candidate B) or add readback markers (Candidate E).

Constraint from substrate finding: each scaffold test consumes clean-substrate time; if we want T271 to be readable, fire it soon after a cold cycle (within ~20 min window based on the T269 vs baseline-postcycle gap). Sequence: cold cycle → T271 → if wedge, accept as-is and analyze; do NOT re-fire without another cold cycle.

Advisor + T271 code design before next fire.

### Post-test checklist

- Journal captured: ✓ `phase5/logs/test.270-baseline.journalctl.txt` (1411 lines).
- Run output captured: ✓ `phase5/logs/test.270-baseline.run.txt`.
- Matrix outcome resolved: ✓ row 1 — "Reaches t+90000ms, wedges [t+90s, t+120s] — substrate-bounded."
- Ready to commit + push + sync.

---

## T271 PRE-CODE-CHECK (2026-04-24 08:10 BST — **Advisor-flagged pre-code grep surfaces a blocker. No code written; no hardware fired.**)

### The check

Per advisor (prior to this session): before coding T271 (T266 scaffold + Candidate A ring-init), verify that `devinfo->shared.ring_info_addr` is populated on our code path before the scaffold point. If not, `brcmf_pcie_init_ringbuffers` would read garbage from TCM[0] and the experiment is unreadable.

### Primary-source findings

Grep of `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`:

1. **`shared.ring_info_addr` is populated ONLY inside `brcmf_pcie_init_share_ram_info`** (line 2784: `shared->ring_info_addr = brcmf_pcie_read_tcm32(devinfo, addr);`).
2. **`init_share_ram_info` is called from two sites inside `brcmf_pcie_download_fw_nvram`**: line 5700 (the T96/FullDongle-ready direct init) and line 5804 (the wrapper fallthrough at end of function).
3. **Our T238 ultra_dwells branch at line 3581 exits `brcmf_pcie_download_fw_nvram` BEFORE lines 5700..5804.** We never reach either init_share_ram_info call.
4. **T47/T96 markers** (which test.130 setup would log if either init_share_ram_info path executed) are **absent** from the T270-BASELINE journal — confirmed by grep.
5. **`init_share_ram_info` itself requires `sharedram_addr` (fw-published at TCM[ramsize-4])** via the loop at line 5723-5727.
6. **T247 primary-source observation (recorded in RESUME_NOTES_HISTORY line 830)**: TCM[ramsize-4] stayed at `0xffc70038` (NVRAM trailer marker) across all 23 dwells through t+120s. **Fw never publishes sharedram_addr.**

### Implication: Candidate A is blocked upstream

`init_ringbuffers → reads shared.ring_info_addr → populated only by init_share_ram_info → requires sharedram_addr → fw never publishes it.` The chain is broken at the source, not the sink. Candidate A as framed (add two function calls) is not a minimal-change test; the preconditions the audit presumed are absent.

### Tightening the hang reading (new evidence)

This evidence bounds the hang window tighter than before:

- si_attach completes (T252: 0x92440 struct populated).
- Fw enters WFI (T257: DEFINITIVE via scheduler path).
- Fw does NOT publish sharedram_addr at TCM[ramsize-4] before entering WFI (primary-source via T247 probe across 23 dwells).

Conclusion: **fw's WFI entry happens BEFORE the shared-info-publish step.** The init sequence reaches further than wlc_bmac_attach (per T251/T252) but stops before reaching shared-info publish. This narrows where in the init sequence the WFI-entry happens.

### Advisor directive (current session)

> "Don't code yet — fw-blob diss task is still running on another host; its results will almost certainly redirect T271 anyway — because 'what wakes pciedngl_isr' and 'what triggers shared-publish' are likely the same protocol question viewed from two sides."

Action: park T271 coding. Wait for fw-blob diss task to land. When results arrive, redesign T271 with the wake/publish protocol in mind.

### What this does NOT invalidate

- The code audit (phase6/t269_code_audit_results.md) is still useful — its wedge-timing analysis, `pci=noaer` observation, threaded-IRQ analysis, and Candidates B/C/D/E/F are independent of this blocker.
- The T270-BASELINE finding (substrate reproducibility) is unaffected.
- Candidates B (remove `pci=noaer`) and C (add `pci=noaspm`) become higher-priority because they don't require shared-info to be populated.

### Substrate budget status

No hardware fired. Cold-cycle window still ~open (boot 0 at 07:58 BST, ~15 min old). If we want to fire anything soon: Candidate B (remove `pci=noaer` from boot cmdline) or Candidate C (add `pci=noaspm`) are the viable single-variable next tests, but both require reboot config changes and possibly another cold cycle.

No immediate fire needed. Waiting for fw-blob diss + user direction.

---

## POST-FW-BLOB-DISS REFRAME (2026-04-24 08:40 BST — **fw-blob diss task landed and dovetails with T271 pre-code blocker into a coherent reframe. No new hardware fires; pure documentation update.**)

### What the fw-blob diss settled

Full analysis: `phase6/t269_pciedngl_isr.md`. Key factual outcomes:

1. **pciedngl_isr entry at blob 0x1C98** (Thumb). Confirmed via string cross-refs `"pciedngl_isr called\n"`, `"pciedngl_isr"`, `"pciedev_msg.c"`, `"pciedngl_isr exits"` at 0x40685/0x4069D/0x406B2/0x406E5/0x40733 — all referenced by this function's body.
2. **Wake bit**: `pciedngl_isr` tests bit 0x100 of a software ISR_STATUS at `*(pciedev+0x18)+0x18)+0x20`. Value 0x100 matches `BRCMF_PCIE_MB_INT_FN0_0` in upstream brcmfmac (pcie.c:954). ACK via W1C (write-one-to-clear) of the same bit.
3. **No fw-side host-facing register writes** on wake. All response via TCM ring writes that host polls. Doorbell W1C is the only MAILBOXINT mirror access.
4. **No panic/reboot/host-watchdog string in blob**. Fw can sit in WFI indefinitely without self-destructing. The host wedge is NOT fw-initiated. All `"watchdog"` strings refer to periodic soft-timers (`wlc_phy_watchdog`, `wlc_bmac_watchdog`, `wlc_dngl_ol_bcn_watchdog`, etc.), not "host must respond" timers.
5. **Bit allocation**: `hndrte_add_isr` at 0x63C24 allocates the scheduler callback node, dispatches a class-specific unmask via a 9-entry thunk vector at 0x99AC..0x99C8 (→ 0x27EC region). For pciedngl_isr the allocated bit is 3 (flag=0x8).
6. **Upstream handshake protocol** (from reading our own `pcie.c` — not the blob):
   - Fw publishes `shared.flags |= BRCMF_PCIE_SHARED_HOSTRDY_DB1` (0x10000000, pcie.c:1016) as part of its init.
   - Host reads `shared.flags` (after `brcmf_pcie_init_share_ram_info` populates `devinfo->shared`).
   - ONLY if HOSTRDY_DB1 observed, host calls `brcmf_pcie_hostready` (pcie.c:2044) which writes H2D_MAILBOX_1 = 1.
   - Fw's already-unmasked FN0_0 bit fires → scheduler dispatches `pciedngl_isr` → handshake proceeds.

### Why the scaffold investigation (T258–T269) was doomed

Every scaffold (T258, T259, T260, T261, T262, T263) that wrote H2D_MAILBOX_1 did so **without observing HOSTRDY_DB1 first** — none of them even read `shared.flags`. Three possibilities:
- Fw had unmasked FN0_0 but not populated `pciedev+0x18` sub-struct → ISR NULL-derefs on its first read → fw ARM crashes silently mid-ISR → bus stops responding → host MMIO wedges.
- Fw had not yet unmasked FN0_0 → early doorbell lost (edge-sensitive) or latched (level-sensitive) — either way, harmless, but…
- …The fact that T262/T263 (no doorbell at all) also wedged rules out "only the doorbell ring wedges" — the scaffold-line mere act of subscribing MSI + IRQ on BCM4360 is already producing a wedge.

Net: even with perfect handshake, the scaffold line was hitting a secondary wedge mode. Given (4), it is not fw-initiated. Most likely it's host-side: ASPM-L1 exit timing, MSI-vector routing, or a kernel spinlock path that depends on a device state that doesn't exist because fw hasn't initialized it. Candidates B/C/E from the code audit address some of these.

### Dovetail with T271 pre-code blocker

The pre-code check surfaced: **sharedram_addr at TCM[ramsize-4] is never populated by fw** (T247 observed 0xffc70038 NVRAM trailer unchanged across all 23 dwells through t+120s). Per the fw-blob analysis section 5.2, sharedram publish happens as part of pcidongle_probe — which happens AFTER `hndrte_add_isr(pciedngl_isr, ...)` and BEFORE fw advertises HOSTRDY_DB1. Logical chain:

```
si_attach (T252: 0x92440)
   → wlc attach (T251: saved-LR 0x68D2F)
   → wlc_bmac_attach (T251: saved-LR 0x68321)
   → ... gap we can't see ...
   → pcidongle_probe
     → hndrte_add_isr(pciedngl_isr) — allocates bit 3, unmasks FN0_0
     → publishes sharedram_addr at ramsize-4
     → publishes shared.flags |= HOSTRDY_DB1
     → (now host would see flags and safely ring doorbell)
```

T247 evidence: TCM[ramsize-4] never changes → sharedram never published → **pcidongle_probe did not complete its publish phase** (or ran but never got that far).

T257 evidence (WFI is DEFINITIVE): the scheduler reached a point where no callback's flag bit matched, so it went to idle loop → WFI.

Combined: **fw is stuck in WFI somewhere BEFORE pcidongle_probe's sharedram-publish point**. The scheduler is waiting on a pending-events bit that never fires — a bit that something else should have set during init.

### Updated hang bracket (tighter than session start — **REVISED by T274-FW**)

| Point | Evidence |
|---|---|
| RTE boot banner | T250 ring-dump (`"RTE (PCIE-CDC) 6.30.223 (TOB)"`) |
| si_attach completes | T252 decode of 0x92440 (si_info-class struct with CC base 0x18001000 cached) |
| wlc attach / bmac attach entered | T251 saved-LR 0x68D2F / 0x68321 near those function bodies (α branch, now supported but not proven) |
| **pcidongle_probe COMPLETED through hndrte_add_isr + fn@0x1E44 + fn@0x1DD4** | T274-FW: T255/T256 show pciedngl_isr IS registered as scheduler node[0] at 0x9627C; pcidongle_probe's body maps to alloc→register→init→return with no hangs |
| **fw enters WFI** | T257 DEFINITIVE (host harness bypasses MSI setup; no IRQ ever arrives) |
| **sharedram publish NOT reached** | T247: TCM[ramsize-4] unchanged 23/23 dwells. T274-FW finding: sharedram publish is NOT inside pcidongle_probe — it must be in a LATER phase of fw init gated on an event that never fires. |

Hang location: AFTER pcidongle_probe returns to its caller (the device-probe-iterator). Fw enters a scheduler state with registered callbacks (pciedngl_isr + wlc's fn@0x1146C) but no runnable flag bits → WFI. Sharedram publish is gated behind an event fw expects but never receives.

**Earlier reading "pcidongle_probe never reached" was WRONG and is superseded by T274-FW.**

### What this invalidates / moots / keeps

| Item | Status |
|---|---|
| T271 / Candidate A (add init_ringbuffers before scaffold) | **MOOT** — pcidongle_probe-gated shared-publish was assumed and doesn't happen. |
| Scaffold-line investigation (T258–T269 shape) | **BLOCKED** pending fw reaching pcidongle_probe. Not abandoned; paused. |
| T270-BASELINE substrate reproducibility | **UNAFFECTED** — still holds. |
| Code audit (phase6/t269_code_audit_results.md) | Mostly still useful; specific scaffold-fix candidates A–F are now: A moot; B/C/E still live for "why does the *scaffold act of MSI subscription* also wedge"; D/F deprioritized. |
| fw-blob diss (phase6/t269_pciedngl_isr.md) | **Done.** No further work on pciedngl_isr needed until fw reaches it. |
| Hardware substrate | Still clean-ish (~40 min into boot; drift may have started); no fires pending. |

### New productive thread: T272-FW

Trace the fw init chain between wlc_bmac_attach completion and pcidongle_probe entry. Goals:

- Find wlc_attach's return point in the caller, and what function is called next.
- Map the init sequence from there up to pcidongle_probe.
- Identify any step in that sequence that:
  - reads a HW register in a way that could block on unclocked-core access, or
  - schedules an RTE callback + returns to scheduler (legitimate — but then something must set that callback's flag bit), or
  - tail-calls into a dispatcher that's waiting on an event bit that requires a host action we haven't taken.

Output: `phase6/t272_init_chain.md` describing the gap + specific init-step candidates.

Advisor call if the gap is large or ambiguous. No new hardware fires until this analysis produces a concrete candidate.

---

## POST-T272-FW (2026-04-24 09:30 BST — **Init chain mapped. Hang bracket tightened to a 2–3-call sub-tree inside wlc_bmac_attach's tail. Next static-analysis step named. No hardware fires.**)

### What T272-FW settled

Full doc: `phase6/t272_init_chain.md`. Key facts:

- **Device-registration struct layout identified.** Both `wlc` (base `0x58EFC`) and `pciedngldev` (base `~0x58C88`) use Broadcom hndrte-style fn-pointer tables. Probe slots: `[0x58F1C] → fn@0x67614` (wlc) and `[0x58C9C] → pcidongle_probe (0x1E90)` (pciedngldev).
- **Both probes reached ONLY via indirect dispatch** through a (static-linked) device-list iterator. No direct BL callers for `fn@0x67614` or `pcidongle_probe`. RTE walks the device list and invokes each probe in registration order.
- **Direct call chain** (innermost first): `wlc_phy_attach (0x6A954) ← wlc_bmac_attach (0x6820C) ← fn@0x68A68 ← fn@0x67614 ← indirect`.
- **"wlc_attach" is a stage-name, not a function**. The `"wlc_attach"` ASCII string at `0x4B1FF` is referenced only from trace strings inside `wlc_bmac_attach`'s error paths. No dedicated `wlc_attach` function body in this blob.
- **Saved-LR 0x68321 from T251 resolves to**: return from `bl #0x1415C` at 0x6831C (SB-core-reset waiter; bounded 20ms per T253/T254). fw had reached at least that point inside `wlc_bmac_attach`, and fn_1415C had returned.

### Hang bracket — tightened

After the T251 saved-LR return point (0x68320), wlc_bmac_attach continues with these sub-calls:

```
0x68326:  bl #0x15940        ; T254 already cleared (no loops)
0x6832C:  bl #0x179C8        ; UNTRACED — HIGHEST PRIORITY candidate
0x68330:  cbnz r0, +0x28     ; error check
0x6835E:  bl #0x52A2         ; lookup helper
0x6836E:  bl #0x67E1C        ; UNTRACED — second priority
```

Also (but lower priority since fw already passed it to reach the saved-LR point):

```
0x68ACA:  (inside fn@0x68A68, before bl wlc_bmac_attach)
          bl #0x67F2C        ; UNTRACED — tertiary
```

### The 3 untraced sub-calls that could contain the hang

| Addr | Pattern heuristic | Priority |
|---|---|---|
| `0x179C8` | First BL after T251-observed saved-LR; position suggests HW/MAC bringup | HIGH |
| `0x67E1C` | Second BL in continuation chain | MEDIUM |
| `0x67F2C` | In fn@0x68A68 wrapper, before wlc_bmac_attach call | LOW (likely completed) |

If `0x179C8` contains an unbounded polling loop with a host-dependent condition (bit that only flips when host writes to a specific register), the hang location is identified and the fix is "set that bit before fw reaches 0x179C8."

### Observations on probe ordering

If device-probe-iterator invokes `wlc` before `pciedngldev` (order in static linked list), and `wlc`-probe hangs, `pciedngldev`-probe never runs → `pcidongle_probe` never runs → no `hndrte_add_isr(pciedngl_isr, bit=3)` → no sharedram publish → no HOSTRDY_DB1 advertising → host cannot safely ring doorbell. This is exactly what T247/T255/T257 observed.

### Why this is a reasonable stopping point for today

- T272-FW narrowed the hang window from "somewhere between si_attach and pcidongle_probe" to "inside one of three specific sub-functions, all in wlc_bmac_attach's tail."
- Continuing would be T273-FW: disassemble `0x179C8`, `0x67E1C`, `0x67F2C` bodies; classify each as bounded / unbounded-polling / dispatcher-tail-call. That's the natural next analytical step.
- No hardware fires today since 08:01 (T270-BASELINE). Substrate window has likely closed (boot uptime 1h40m+, drift expected). Next hardware fire needs another cold cycle.
- If T273-FW identifies an unbounded polling loop in any of these calls, a targeted T274 hardware probe becomes designable: peek at the specific register the loop reads, confirm the hang point on live hardware.

### What T272-FW did NOT settle

- Exact hang address within the bracket — need T273-FW to disassemble the 3 sub-calls.
- Which specific event / register / HW-state transition fw is waiting on — same answer.
- Whether our scaffold investigation could ever produce a valid wake — still blocked by the shared-publish gap. That gap closes only if fw reaches pcidongle_probe, which requires the hang in wlc_bmac_attach's tail to be resolved first.

---

## POST-T273-FW (2026-04-24 10:10 BST — **All 3 T272 candidates cleared; full wlc_bmac_attach first-level scan confirms no unbounded HW-polling. Scheduler-callback lead identified: fn@0x1146C registered via hndrte_add_isr at 0x67774 inside wlc-probe.**)

Full writeup: `phase6/t273_subcall_triage.md`. Scripts: `phase6/t273_*.py`.

### What T273-FW settled

1. **All 3 T272 candidates are non-polling**:
   - `0x179C8` = `wlc_bmac_validate_chip_access` (96 insns, no backward branches; string xref confirms identity).
   - `0x67E1C` = tiny field-reader (2 insns).
   - `0x67F2C` = 10-insn dispatcher (tail-calls one of two targets).

2. **Full wlc_bmac_attach body scan** (44 unique BL targets, 2140 bytes): every tight loop at first-level has a **fixed bounded iteration count**:
   - `0x1415C` — SB-core reset waiter, 20ms via delay helper (T253/T254).
   - `0x5198` — 6-iter MAC-address copy.
   - `0x67F8C` — 6-iter txavail setup (string `&txavail`, `wlc_bmac.c`).
   - `0x68D7C` — 30-iter init loop (string `wlc_macol_attach`).

3. **Negative-result signal**: hang is NOT a simple tight HW-polling loop. Combined with T255 (frozen scheduler state) and T257 (WFI DEFINITIVE), the mechanism is "fw enters scheduler with no runnable callback → WFI waiting for an interrupt that never fires."

4. **Advisor-flagged lead (followed)**: `fn@0x67614` (wlc-probe top) calls `hndrte_add_isr` at 0x67774, registering `fn@0x1146C` as a scheduler callback.
   - Args observed: r3 = 0x1146D (fn-ptr); r0 = sb = 0 (NULL ctx); r1/r2/r7/r8 carry name/arg/class metadata.
   - fn@0x1146C is 10 insns, NO HW register reads — purely dispatches to `bl #0x23374` (helper sets byte flag) → conditional `bl #0x113b4` (action).
   - Appears as the last slot in the wlc device fn-table (0x58F38 = 0x1146D).
   - Trigger flag bit allocated by hndrte_add_isr from the class-dispatch pool (per T269 analysis). Scheduler tests the pending-events word `*(ctx+0x358)+0x100` against each node's flag.

### Strong circumstantial case: fn@0x1146C's flag is host-driven

| Evidence | What it tells us |
|---|---|
| T255: scheduler state [0x6296C..0x629B4] identical across 23 dwells | Rules out periodic timer tick (would drift) |
| T257: WFI DEFINITIVE (host bypass of MSI/IRQ setup) | Matches "host should be signaling something but isn't" |
| Upstream brcmfmac protocol: hostready gate on HOSTRDY_DB1 | Confirms pattern where host triggers fw wake events |
| fn@0x1146C body: no HW regs, pure event-driven dispatch | Matches "await external event" — not HW-state polling |

These all point to: **fn@0x1146C waits for a specific host-driven trigger** that our test harness never generates. Unlike pciedngl_isr (bit 3 = FN0_0 mailbox), we don't yet know which trigger — it's allocated from the same pool but via a different class-dispatch path.

### What this means for next moves

**Scaffold line (T258–T269) was doubly blocked**:
1. The scaffold rang H2D_MAILBOX_1 without the HOSTRDY_DB1 gate — which wouldn't have mattered even with the gate, because fw never reaches pciedngldev-probe to advertise HOSTRDY_DB1.
2. The scaffold would have fired bit 3 (FN0_0 = pciedngl_isr) which isn't even registered yet at the time of our scaffold firing (since pcidongle_probe hasn't run).
3. The right wake-trigger for the CURRENT fw state is whatever fn@0x1146C's flag responds to — a DIFFERENT mailbox bit that we haven't been writing.

### Next cheap static-analysis steps

Each ~30 min:

1. **Trace writers of `*(ctx+0x358)+0x100`** — which function(s) in the blob STORE to this pending-events word? The arguments / bit-patterns reveal what triggers fire the word.
2. **Disasm the 9-thunk vector's WLC slot** (the one for WLC's `*(ctx+0xCC)` class index) — identifies which HW interrupt class WLC is attached to.
3. **Disasm helpers `0x23374` and `0x113b4`** (called from fn@0x1146C body) — verify they don't have hidden HW reads.

### Next hardware direction (only if static step 1 or 2 identifies a register)

Design T274 scaffold to write the specific mailbox/doorbell/status register that fires fn@0x1146C's bit. If fw advances past the WFI, pciedngldev-probe may run → sharedram publish → HOSTRDY_DB1 → then the original scaffold design might work.

BUT: the separate "MSI subscription itself wedges host" issue (code audit §4) remains. Even with a correct fw-wake trigger, the host-side wedge modes from T264/T265/T266 would still need to be addressed. Probably via `pci=noaer` removal or `pci=noaspm` (audit candidates B/C).

### Session status

- Zero hardware fires since 08:01 BST (T270-BASELINE).
- Substrate window is closed (boot 0 uptime ~2h+; drift reliable within 25 min of cold cycle).
- No hardware action planned until static analysis identifies a specific register to target.
- fw-blob side: T273 concluded. T274-FW would be the pending-events-word writer trace.

---

## POST-T274-FW (2026-04-24 11:00 BST — **Architectural mismatch discovered. Major reframe.**)

Full writeup: `phase6/t274_events_investigation.md`. Scripts: `phase6/t274_*.py` + `/tmp/t274_*.py`.

### What T274-FW settled

1. **T255/T256 data reinterpreted**: pciedngl_isr IS registered (node[0] at TCM[0x9627C]: next=0x96F48, fn=0x1C99, arg=0x58CC4, flag=0x8). Therefore **pcidongle_probe ran PAST hndrte_add_isr successfully**. My earlier reading "pcidongle_probe never reached" was WRONG.

2. **pcidongle_probe full body mapped** (0x1E90..0x1F78, 232 bytes):
   - alloc devinfo(0x3c) → memset → 5 sub-call helpers populating struct
   - `bl #0x63C24` (hndrte_add_isr) at 0x1F28 — registers pciedngl_isr
   - `bl #0x1E44` at 0x1F38 — post-registration finalize
   - return

3. **fn@0x1E44 (post-reg finalize, 68 bytes)**:
   - Initializes ISR_STATUS mirror at `[devinfo_substruct + 0x100]` with `(config & 0xfc000000) | 0xc`
   - Calls `bl #0x2F18` (struct-init helper, ~116B clean) and `bl #0x2DF0` (1-insn `bx lr` no-op)
   - Tail-calls `bl #0x1DD4`

4. **fn@0x1DD4 (114 bytes, tail-called from fn@0x1E44)**:
   - Allocates 196-byte msg buffer, stores at devinfo+0x20
   - Calls `bl #0x66a60` (shared msg-queue init — T273 also considered via different path; verified bounded below)
   - Returns

5. **bl #0x66a60 is NOT a polling loop** (verified per advisor's 20-min cheap check):
   - 208 bytes, 1 backward branch (a 30-iter bounded list-init loop)
   - Allocates up to 30 descriptors via `bl #0x7d74` and links them into a message-queue list
   - String reference `'bcmutils.c'` — a bcmutils init helper
   - No waits, no HW register polls

6. **pcidongle_probe completes fully with no hangs in its body or sub-tree**. Hang is AFTER it returns.

7. **HOSTRDY_DB1 (0x10000000) is NOT referenced in fw code** (critical finding):
   - 5 literal-pool-aligned byte matches exist in the blob.
   - ZERO of them have direct LDR pc-rel references or MOVW/MOVT pairs encoded elsewhere in code.
   - `movt r?, #0x1000` scan of entire blob: zero matches.
   - **Therefore: this fw does NOT advertise HOSTRDY_DB1 as part of its shared.flags protocol.**

8. **Implication — architectural mismatch**:
   - Upstream brcmfmac `brcmf_pcie_hostready` (pcie.c:2044) is gated on `shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1`. If fw never sets that bit, upstream's normal probe would NEVER write H2D_MAILBOX_1.
   - The fw banner literally says `"RTE (PCIE-CDC) 6.30.223 (TOB)"` — **CDC-PCIe**, not msgbuf.
   - Upstream brcmfmac's PCIe driver path is **msgbuf-only**. BCM4360's CDC-PCIe fw may be architecturally incompatible with upstream's probe path.

9. **Writers of pending-events word NOT found**:
   - Zero stores at offset #0x100 with preceding ctx+0x358 load.
   - Zero stores at offset #0x458 (flat).
   - Zero stores at offset #0x358 (ctx setup).
   - Strongly suggests the word at `*(ctx+0x358)+0x100` is **HW-mapped**, not software-maintained. T269's "software-maintained pending events" reading needs correction.

10. **IRQ handler finding**:
    - ARM vector at 0x18 → handler at 0xF8 → calls `[*0x224]` (ISR dispatcher).
    - `[0x224]` = 0 in static blob; no code writes to 0x224 via direct lit-ref.
    - Implies fw either runs with IRQs disabled, or uses a VBAR-remapped ARM vector path, or [0x224] is written via an addressing mode we missed. Non-blocking but notable.

### Major reframe

The scaffold investigation's whole premise (that fw would wake via a doorbell if the right host-side state is set) may be **architecturally mismatched** with this fw. The banner indicates CDC-PCIe. Upstream brcmfmac's PCIe path is msgbuf-only. We've been trying to drive CDC firmware with a msgbuf driver.

### New productive direction (advisor-confirmed)

**Upstream audit.** Specific question:

- Is there any version of brcmfmac (past or present) that drove PCIe-CDC fw?
- If YES: that path is our reference. We need to port/port-forward that driver path or re-enable it.
- If NO: upstream brcmfmac was never designed for BCM4360's legacy fw. The project reframes as "port or write a CDC-PCIe driver," not "patch the existing msgbuf driver."

Either answer unblocks. Continuing blob spelunking at this depth has diminishing returns.

### What remains valid

- T270-BASELINE substrate reproducibility (unaffected).
- T257 WFI-DEFINITIVE observation (unaffected — fw IS in WFI).
- The scaffold-line host-wedge modes (T258–T269) — those are host-side issues independent of fw protocol. Still need to be addressed if/when we have a wake sequence that matches the fw.
- T253/T254's polling-loop-classification of wlc_phy_attach's subtree (unaffected — that was thorough and correct).

### What is invalidated / needs updating

- The "pcidongle_probe never reached" claim (from POST-FW-BLOB-DISS REFRAME) — WRONG. Reconciled in the bracket table above.
- T269's "software-maintained pending events word" reading — probably HW-mapped based on the zero-writer finding. Noted in T274 §6.1.
- The "host needs to ring the right mailbox to wake fw" framing for T273's fn@0x1146C analysis — possibly true, possibly architectural mismatch. We don't yet know what CDC-PCIe's wake protocol expects.

### Session status

- No hardware fires planned.
- Static analysis at diminishing-return depth.
- Next action: upstream audit for CDC-PCIe driver support (possibly in git history of brcmfmac, or in broadcom/brcmsmac, or in the out-of-tree broadcom drivers).

---

## POST-T275-UPSTREAM-AUDIT (2026-04-24 11:45 BST — **Phase 4 rediscovery + engineering path identified. Full writeup at phase6/t275_upstream_audit.md.**)

### What T275 settled

1. **Upstream brcmfmac PCIe is msgbuf-only.** `pcie.c:6877` hardcodes `proto_type = BRCMF_PROTO_MSGBUF`. Kconfig's `BRCMFMAC_PCIE` selects `BRCMFMAC_PROTO_MSGBUF`. No upstream version ever drove PCIe-CDC.
2. **But BCDC code is in brcmfmac**, wired to SDIO (`bcmsdh.c:1081`) and USB (`usb.c:1263`). BCDC talks to bus via standard `txctl`/`rxctl`/`txdata` callbacks defined in `brcmf_bus_ops`.
3. **Critical observation**: PCIe's `brcmf_pcie_tx_ctlpkt` and `brcmf_pcie_rx_ctlpkt` (pcie.c:2597/2604) are **stubs returning 0**. Msgbuf doesn't call them; they exist only to satisfy the bus_ops struct.
4. **Phase 4B already reached this conclusion** (commit `fc73a12`, 2026-04-12): "BCM4360 wl firmware uses BCDC protocol… No msgbuf firmware exists for BCM4360 in any known source… Driver patches are proven working — firmware compatibility is the sole blocker." T258-T274 was ~2 weeks of rediscovery work.
5. **T274's misread corrected**: "fw never references HOSTRDY_DB1" is correct fact, but my interpretation "fw expects some other mystery wake trigger" was wrong. Simpler: **fw expects host to send the first CDC command, which starts the init state machine**. We don't send one because we use msgbuf proto, not BCDC.

### The engineering path (novel contribution of T275)

Minimal patchset:

1. New Kconfig option `BRCMFMAC_PCIE_BCDC` (or per-chip flag for BCM4360).
2. Modify pcie.c:6877 to set `proto_type = BRCMF_PROTO_BCDC` for BCM4360.
3. Implement `brcmf_pcie_tx_ctlpkt`:
   - Copy CDC command bytes into a TCM buffer (pcidongle_probe's allocated buffer per T274 §4).
   - Write H2D_MAILBOX_1 = 1 → fires fw's pciedngl_isr (bit 0x100 = FN0_0).
   - Wait for completion.
4. Implement `brcmf_pcie_rx_ctlpkt`:
   - Register D2H mailbox IRQ handler (needed before first command).
   - Handler copies CDC response bytes from TCM + wakes waitqueue.
   - `rx_ctlpkt` sleeps until handler signals, copies to caller's `msg` buffer.
5. First test: `WLC_GET_VERSION` dcmd round-trip. Success = response with valid version + sharedram_addr subsequently published (side-effect of fw advancing past CDC-wait).

### Why this should work when scaffolds didn't

Scaffolds (T258-T269) wrote H2D_MAILBOX_1 into a fw state with no valid command buffer. Fw's `pciedngl_isr` fired on the doorbell, read nonsense from the command buffer, and either ignored it or crashed silently.

With BCDC wiring, the command buffer contains a real CDC command BEFORE the doorbell. Fw reads a valid command, processes it, returns a response. Standard CDC operation that the fw was built for.

### What this re-frames

- **T274's "mystery wake trigger"** — resolved. It's just "host sends CDC command".
- **T273's fn@0x1146C** — the wlc-side scheduler callback. Probably fires when WLC init messages arrive via CDC (once the host sends them). Not a blocker to get initial CDC working.
- **The T258-T269 scaffold line** — fundamentally wrong approach. Writing mailbox doorbells without valid command bytes in the buffer can't wake fw productively.
- **The host-side MSI-wedge issue** (from code audit) — orthogonal, still live. Need to solve it as part of this work (MSI subscription is required to receive D2H responses).

### Open questions for advisor / next session

1. **Sanity-check the rediscovery**: Phase 4 ended with "fw compat is the blocker". T275 says "actually, the BCDC proto layer + the empty PCIe stubs give us a clean path without needing new fw". Why did Phase 4 not take this path? Either we missed something Phase 4 knew, or Phase 4 didn't realize the stubs existed.
2. **CDC bringup sequence**: what's the first few commands to send? (Possibly inferable from wl.ko or from Broadcom docs; brcmfmac's SDIO path must do the same dialog.)
3. **Where is pcidongle_probe's command-input buffer** in TCM? `devinfo->[0x10]` at runtime — needs live lookup or further blob analysis to find its TCM offset.
4. **MSI-wedge on BCM4360** (code audit §4): independent of proto choice; needs its own fix before D2H responses can be received.

### Session-level summary

Two full days of blob spelunking (T250-T274) converged on a conclusion that Phase 4B (2026-04-12) had already reached. The unique contribution of this session is:

- **Direct evidence** for the architectural mismatch (T274: zero HOSTRDY_DB1 refs, pciedngl_isr/hndrte_add_isr fully characterized, all scheduler state mapped).
- **The specific stub-implementation path** (T275: txctl/rxctl exist as empty stubs, BCDC proto attach already handles everything else).
- **Clean re-grounding** of the engineering plan: patch 2 stubs + 1 line to switch proto_type = concrete code change, not a vague "fw compat is the blocker."

### Session status

- No hardware fires today since 08:01 BST (T270-BASELINE).
- All commits pushed and filesystem synced.
- Ready to advisor-check the engineering plan. If approved, next session implements the 2-stubs + Kconfig change.

---

## POST-T275-CORRECTION (2026-04-24 12:30 BST — **Advisor blocked T275's BCDC plan. Primary sources in phase4/notes show olmsg/shared_info is the right protocol.**)

### What happened

Advisor flagged two unreconciled things before any code:

1. **Phase 4A (`phase4/notes/transport_discovery.md`) says BCM4360 is SoftMAC NIC + offload engine, NOT FullMAC dongle.** "There is no BCDC-over-PCIe transport protocol to reverse-engineer" — explicitly ruling out what T275 proposed.
2. **Phase 4B's conclusion doc (`phase4/notes/test_crash_analysis.md`, added by commit `a8007d2`) had specific runtime findings I hadn't read.**

Reading the Phase 4B conclusion doc revealed:

- **Test.28 (2026-04-13)**: writing a valid `shared_info` struct at **TCM[0x9D0A4]** before ARM release completely prevents the 100 ms panic. Fw runs stably for ≥2 s, finds magic markers, reads the olmsg DMA buffer address, writes status (`0x0009af88`) to `shared_info[0x10]`, sends 2 PCIe mailbox signals.
- Layout (`phase4/notes/level4_shared_info_plan.md`):
  - `+0x000` magic_start `0xA5A5A5A5`
  - `+0x004..+0x00B` olmsg DMA addr (lo + hi 32-bit)
  - `+0x00C` buffer size `0x10000` (64 KB)
  - `+0x010` fw-writable status
  - `+0x2028` fw_init_done (fw sets when ready)
  - `+0x2F38` magic_end `0x5A5A5A5A`

### The correct protocol

**olmsg** (offload messaging) over a DMA ring buffer, address published via `shared_info` in TCM. NOT BCDC.

`bcm_olmsg_*` symbols in the fw blob correspond to Phase 4A's wl.ko-side `bcm_olmsg_writemsg`/`bcm_olmsg_readmsg` helpers. This is the protocol wl.ko (Broadcom's proprietary driver) uses for BCM4360. The BCDC strings (`bcmcdc`, `pciedngl_*`) in the blob are shared-codebase artifacts — fw CAN parse CDC but the HOST-observable runtime protocol is olmsg.

### Phase 4A vs 4B reconciled

- **Phase 4A** analyzed `wl.ko` host-side. Saw offload usage. Correctly concluded the runtime protocol is olmsg.
- **Phase 4B** analyzed the fw blob. Saw wlc_*, pciedngl_*, bcmcdc. Concluded "FullMAC CDC" — but this described the *fw binary's compiled capabilities*, not the runtime protocol the host drives.
- **The two readings are compatible**: fw binary has both FullMAC and offload code; wl.ko chose offload path; we should too.

### Why T275 went off course

I reached for the familiar framework (brcmfmac + BCDC/msgbuf dispatch) without reconciling against Phase 4's specific runtime findings. T274's "fw expects some mystery wake" should have triggered a Phase 4 lookup — it didn't. Rediscovered the mismatch from first principles over T250-T274, then proposed a plan that contradicted Phase 4's own conclusion.

### New pinned file: `KEY_FINDINGS.md`

Created at repo root. Schema: Fact | Status (CONFIRMED / RULED-OUT / LIVE / SUPERSEDED) | Evidence | Date. Seeded with ~40 cross-phase facts including the shared_info offsets, olmsg ring layout, Phase 4B's test.28 evidence, Phase 5's current progression, and what's been ruled out (BCDC-over-PCIe, tight HW-poll, writing doorbells without shared_info).

**CLAUDE.md updated** to require reading KEY_FINDINGS.md first, and to instruct "grep prior phases before declaring a new finding". Final section of KEY_FINDINGS.md is a self-review reminder for end-of-session updates.

### Corrected engineering path

Not "wire BCDC via two stubs." Instead:

1. **In Phase 5's `brcmf_pcie_setup` (before the early return for BCM4360)**: write Phase 4B's `shared_info` struct to TCM[0x9D0A4] after allocating a 64 KB DMA coherent buffer for olmsg.
2. After ARM release: poll `shared_info[+0x2028]` (fw_init_done) for up to ~2 s. If fw sets it, handshake succeeded.
3. Parse olmsg ring structure (ring 0 = host→fw, ring 1 = fw→host, each 30 KB data area + 16-byte header).
4. Send a `BCM_OL_*` command via olmsg ring 0 (e.g., `BCM_OL_BEACON_ENABLE` or similar bringup command — requires further cross-ref to enumerate the early-init command set).
5. Wait for response on ring 1 via PCIe mailbox signal.

This is closer to what wl.ko does. Patch it into brcmfmac-PCIe as a "BCM4360-specific olmsg attach" path — parallel to (not replacing) the msgbuf attach.

### What T275 still contributes

The STUB observation (PCIe's `tx_ctlpkt`/`rx_ctlpkt` return 0) is factually correct but irrelevant. Msgbuf doesn't use them and BCDC wiring wouldn't work because BCDC is the wrong protocol. The T275 writeup should be read with a correction header saying "BCDC direction is wrong — olmsg is right; see POST-T275-CORRECTION and KEY_FINDINGS.md."

### Session status (updated)

- KEY_FINDINGS.md and CLAUDE.md pointer added.
- T275 is recorded but flagged as SUPERSEDED-CORRECT (the stub observation stands; the BCDC conclusion doesn't).
- olmsg handshake path identified as the next LIVE hypothesis.
- No hardware fires since 08:01 BST.
- Advisor-check on olmsg port before coding (the patch is bigger than "two stubs" — needs DMA buffer alloc, TCM write, fw_init_done poll, olmsg ring parsing, mailbox handler).
