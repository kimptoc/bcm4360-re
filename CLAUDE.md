Review the current bcm4360-re project state, and continue development.

Rules:
- Always push immediately after every commit. If the commit is knowingly incomplete
  or experimental, make that explicit in the commit subject, e.g. `WIP: mid-experiment`.
- You have sudo permissions; run tests yourself (insmod, rmmod, journalctl, scripts)
- **Read KEY_FINDINGS.md FIRST** — cross-phase load-bearing facts, pinned. Cheap to read, expensive to skip.
- Then read RESUME_NOTES.md for recent tests and current state.
- Use `DOCS.md` as the file-role contract. Keep `RESUME_NOTES.md` as a live
  handoff only; put durable cross-phase facts in `KEY_FINDINGS.md`, broader
  strategy in `PLAN.md`, and medium-term synthesis in phase notes/results.
- **Before declaring a "new finding"**: grep prior phases. Run `git log --all --grep '<keyword>'` and `grep -rn '<keyword>' phase*/notes/ *.md`. Cite prior work rather than rediscovering.
- **When closing the session** (before the user ends it or compaction hits):
  update `KEY_FINDINGS.md` if this session produced any load-bearing fact,
  changed a previous finding, or invalidated an assumption. See the last
  section of that file for the schema.

## Hardware Interaction Tiers

**Quick probe:** read-only checks such as `lspci`, `journalctl`, `dmesg`,
`cat /sys/...`, or register/state inspection that does not load/unload modules
or reset hardware.

**Module test:** `insmod`, `rmmod`, driver reloads, firmware interaction,
PCIe reset, or any command likely to touch device state.

**Full experiment:** any planned module test with new code, new parameters,
reset sequencing, crash risk, or results intended to support a finding.

## Pre-test checklist (hardware/kernel module tests)

Before module tests or full experiments:

1. **Check build status** — look for "NOT yet rebuilt" in RESUME_NOTES.md; if present,
   run `make -C /home/kimptoc/bcm4360-re/phase5/work` before proceeding
2. **Check PCIe state** — run `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
   and verify no dirty state (MAbort+, CommClk- indicate bad state from prior crash)
3. **State your hypothesis for non-trivial tests** — for full experiments, write
   one sentence in RESUME_NOTES.md: what you expect to see and why. For quick
   probes, a short command note is enough.
4. **Write plan to RESUME_NOTES.md, commit, and push** — required before full
   experiments; optional for quick read-only probes.
5. **Run `sync` after committing/pushing** — git has been corrupted a few times.

## Post-test

After every module test or full experiment:

1. Capture `journalctl -k` / dmesg output to the appropriate log file in `phase5/logs/`
2. Update RESUME_NOTES.md with what was observed, matched against the hypothesis
3. If the result is load-bearing, update `KEY_FINDINGS.md`; if it closes a
   broader question, update the relevant phase note
4. Commit and push before doing anything else

After a crash or forced reboot, also:

1. Check PCIe state before further hardware interaction
2. Run `git status --short` and verify the worktree/index are sane
3. Confirm expected log files exist and are readable
4. Run `sync` after documenting and committing recovery notes

## Legal & Licensing Rules

This project reverse-engineers proprietary firmware for interoperability.
All work must stay on the right side of copyright law. Follow these rules
without exception:

**Allowed:**
- Describe firmware behavior: register access patterns, polling loops, state
  transitions, timing, call chains — in plain language
- Small minimal instruction excerpts only when essential for explanation
- Implement new driver logic from *observed behavior* and documented interfaces
- Log/trace/dump signals extracted from hardware (register values, state flags)

**Not allowed:**
- Commit large disassembly blocks or full reconstructed functions
- Commit firmware blobs or modified firmware images
- Write driver code that mirrors instruction sequence or control flow directly
  from disassembly (clean-room: observe → document behavior → implement)
- Publish large memory dumps containing firmware code

**Documentation style:**
- Prefer: "Firmware appears to…", "Observed behavior suggests…", "Likely waiting on…"
- Avoid: "Exact code is…", "This function is implemented as…" with full reconstruction

**Workflow:**
1. Observe behavior (logs, traces, register reads)
2. Identify patterns and document in plain language
3. Implement clean logic based on documented behavior — not directly from disassembly

Tasks:
1. Read RESUME_NOTES.md and review current project state
1a. regularly review PLAN.md against progress and adjust PLAN based on findings.
2. Ensure all work is documented, committed, and pushed
3. Continue with the next phase of development
