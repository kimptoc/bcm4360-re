Review the current bcm4360-re project state, and continue development.

Rules:
- Always push immediately after every commit
- You have sudo permissions; run tests yourself (insmod, rmmod, journalctl, scripts)
- Read RESUME_NOTES.md first to pick up where the last session left off

## Pre-test checklist (hardware/kernel module tests)

Before any test that touches hardware or loads kernel modules:

1. **Check build status** — look for "NOT yet rebuilt" in RESUME_NOTES.md; if present,
   run `make -C /home/kimptoc/bcm4360-re/phase5/work` before proceeding
2. **Check PCIe state** — run `lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'`
   and verify no dirty state (MAbort+, CommClk- indicate bad state from prior crash)
3. **State your hypothesis** — write one sentence in RESUME_NOTES.md: what you expect
   to see and why. Makes results unambiguous.
4. **Write plan to RESUME_NOTES.md, commit, and push** — assume the machine may crash

## Post-test (after every test, crash or success)

Immediately after a test completes or the machine recovers from a crash:

1. Capture `journalctl -k` / dmesg output to the appropriate log file in `phase5/logs/`
2. Update RESUME_NOTES.md with what was observed (match against hypothesis)
3. Commit and push before doing anything else

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

