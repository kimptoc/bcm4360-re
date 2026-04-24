# Task: T269-BASELINE — Baseline reproducibility hardware test (post cold power cycle)

## Release task

Fire the bare `baseline-postcycle` configuration (minimum params, no T269 variant, no scaffold, no extra probes) on the BCM4360 after a full cold power cycle, to answer:

1. **Is baseline-postcycle's clean t+90s ladder traversal reproducible, or was it a one-off?**
2. **If reproducible**, drift is bounded to a window post-cold-cycle — we have a stable substrate to build tests on.
3. **If not reproducible** (wedge earlier than t+90s), the "clean run after cold cycle" reading from 2026-04-24 06:33 BST was circumstantial, and the T265–T268 scaffold-driven framing needs a full reframe.

This is the **only hardware fire advisor endorsed for today** (2026-04-24), and only if hardware work is required. It is strictly single-variable — no new code, no new params beyond baseline — and exists to validate or invalidate a load-bearing data point.

## Pre-conditions

- Hardware state verification: BCM4360 endpoint visible on PCIe bus with clean config (`Mem+ BusMaster+`, no `MAbort+`). If not, escalate to user for SMC reset.
- Required: full cold power cycle (shutdown, unplug AC for ≥60s, boot fresh) completed at some point before this test. If the machine hasn't cold-cycled since the last baseline-postcycle, do not fire — the variable isn't controlled.
- Build state: module already built at 01:33 BST with T268/T269 code gated off by unset params. No rebuild needed.

## Sources

- **Module**: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko` (current build). Verify `modinfo` shows `bcm4360_test236_force_seed` and `bcm4360_test238_ultra_dwells` as params.
- **Reference run**: `phase5/logs/test.baseline-postcycle.journalctl.txt` — the t+90s-reaching run we're trying to reproduce.
- **Pre-test checklist**: `CLAUDE.md` top section.

## Environment

- Sudo required (run via Claude Code harness; user has granted sudo).
- Must execute from `/home/kimptoc/bcm4360-re/`.
- Script-assisted run recommended — errors compounded by manual steps add noise.

## Steps

1. **Pre-flight verification** (foreground, ~30s total):
   - `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'` — confirm clean state. If `MAbort+` or `CommClk-`, stop and escalate.
   - `uptime` — capture current boot duration; if host has been up for hours with no idle period, note that cold-cycle may have drifted.
   - `git status` — must be clean (no uncommitted work that a crash would lose).

2. **Pre-test commit** (required by CLAUDE.md):
   - Add a `PRE-TEST.270-BASELINE` block to `RESUME_NOTES.md` with:
     - Hypothesis: baseline-postcycle's t+90s traversal was substrate-good-at-the-time, not lucky. Expected: reach t+90000ms dwell cleanly, wedge in [t+90s, t+120s] (like 2026-04-24 06:33 run).
     - Outcome matrix: reproduce (substrate bounded), earlier wedge (drift not bounded), crash-in-probe-path (different hardware state).
     - Run sequence (from step 3).
   - Commit with message `PRE-TEST.270-BASELINE: reproducibility check after cold cycle`.
   - `git push` and `sync` (per CLAUDE.md mandatory policy).

3. **Fire** (foreground ≤ ~3 min wall-clock):
   ```bash
   sudo modprobe cfg80211
   sudo modprobe brcmutil
   sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
       bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
   sleep 150
   sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee /home/kimptoc/bcm4360-re/phase5/logs/test.270-baseline.run.txt || true
   ```
   - Expected outcomes at fire time: either the ladder progresses to t+90s and host wedges in the t+90→t+120 gap (auto-reboot expected; platform watchdog handles it), OR the ladder wedges earlier and host needs SMC reset. EITHER outcome is useful signal.
   - If the host wedges during the test, DO NOT attempt recovery — let the platform watchdog or user-triggered SMC reset handle it. Machine may be unavailable for several minutes.

4. **Post-test capture** (after reboot or machine recovery):
   - `sudo journalctl -k -b -1 --no-pager > phase5/logs/test.270-baseline.journalctl.txt`
   - Sanity: `wc -l phase5/logs/test.270-baseline.journalctl.txt` (expect ~500+ lines if full boot -1 captured).
   - Extract key markers:
     ```bash
     grep 'test\.238' phase5/logs/test.270-baseline.journalctl.txt | tail -10
     grep -c 'test\.238: t+.*dwell' phase5/logs/test.270-baseline.journalctl.txt
     ```
   - Record last-marker time and elapsed-from-set_active.

5. **Post-test write-up** (required by CLAUDE.md):
   - Add a `POST-TEST.270-BASELINE` block to `RESUME_NOTES.md` recording:
     - Timeline (insmod → set_active → last marker → wedge → recovery).
     - Outcome match against the pre-test matrix.
     - Direct comparison to 2026-04-24 06:33 baseline-postcycle run (same table format).
     - What this settles (reproducible substrate / not reproducible / different wedge mode).
     - Next-test direction (advisor call recommended before any follow-on hardware fire).
   - Commit and push immediately (`sync` after commit per CLAUDE.md).

## Expected deliverables

- `phase5/logs/test.270-baseline.run.txt` — stdout/stderr of the insmod/rmmod sequence.
- `phase5/logs/test.270-baseline.journalctl.txt` — kernel journal from boot -1.
- Updated `RESUME_NOTES.md` with `PRE-TEST.270-BASELINE` (before fire) and `POST-TEST.270-BASELINE` (after) blocks.
- Single git commit for PRE, single git commit for POST, both pushed immediately.

## Out of scope

- Any test variant that adds probe params, scaffolds, or module-param combinations beyond `force_seed=1` and `ultra_dwells=1`. This is strictly the baseline.
- Re-firing on wedge — one fire, one result. Multiple fires introduce drift variables.
- Building on results (designing T271) — that's a separate task post-completion.

## Success criteria

- Journal captured with ≥1 ladder marker after set_active.
- Last-marker time recorded and compared against 06:33 BST reference.
- One of the outcome-matrix rows resolved (reproduced vs not vs different).
- All commits pushed and filesystem synced.

## Failure / safety modes

- **Build verification fails** (`modinfo` missing params): escalate to user; do not fire.
- **PCIe state dirty pre-fire** (`MAbort+`, `CommClk-`): escalate for SMC reset; do not fire on bad state.
- **Multiple wedges in sequence** (this fire wedges + previous n-streak was already high): stop; notify user; further fires pollute signal.
- **Machine unavailable for recovery**: nothing to do but wait or have user intervene.
