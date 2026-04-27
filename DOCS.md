# BCM4360 RE Documentation Map

This project already has the right raw material. What it lacks is a strict
"what goes where" contract.

Use this file as the top-level map for documentation, notes, and results.

## The Canonical Layers

### 1. Public overview

Files:
- `README.md`
- `PLAN.md`

Purpose:
- Explain the project goal, hardware target, high-level approach, and current
  phase.
- Help a new reader understand the project without reading test-by-test notes.

Rules:
- Keep these files stable and high-signal.
- Do not put per-test crash details here.
- Do update them when the project direction or phase status changes.

### 2. Pinned truth

Files:
- `KEY_FINDINGS.md`

Purpose:
- Record load-bearing facts that changed the direction of the project.
- Preserve cross-phase conclusions that should not be rediscovered.

Rules:
- Only add findings that would matter to a future session.
- Each row should be a fact, status, evidence link, and date.
- If a prior conclusion changes, mark the old one `SUPERSEDED` or update it
  explicitly.
- Do not use this file as a running diary.

### 3. Live session handoff

Files:
- `RESUME_NOTES.md`
- `RESUME_NOTES_HISTORY.md`

Purpose:
- Capture the current working state, latest tests, immediate next probe, and
  recovery state after crashes.

Rules:
- `RESUME_NOTES.md` is for the current session horizon only.
- Keep only the current state block plus the latest 2-3 PRE/POST test pairs.
- Move older PRE/POST detail into `RESUME_NOTES_HISTORY.md`.
- The first screen of `RESUME_NOTES.md` should answer:
  - What is the current model?
  - What just changed?
  - What is the next discriminator?
  - What should not be retried blindly?

### 4. Phase narratives

Files:
- `phaseN/notes/*.md`
- `phaseN/results/*.md`
- `phase6/*.md`

Purpose:
- Preserve medium-term analysis inside the phase where it was produced.
- Keep detailed reasoning, experiment design, and per-topic synthesis close to
  the artifacts they explain.

Rules:
- Use `notes/` for working analysis and experiment design.
- Use `results/` for concluded analysis that is worth citing later.
- Prefer one topic per file.
- At the top of each file, state:
  - goal
  - inputs/evidence
  - conclusion
  - impact on next work

### 5. Raw evidence

Files:
- `phase*/logs/*`
- disassembly outputs
- helper script outputs

Purpose:
- Preserve primary-source evidence.

Rules:
- Do not summarize inline in the log file itself.
- Summarize the meaning in a nearby note and link back to the exact log.
- Treat logs as evidence, not as documentation for humans.

## Recommended Workflow

When a test or analysis finishes:

1. Put raw output in `phase*/logs/` or the relevant phase artifact path.
2. Summarize the immediate outcome in `RESUME_NOTES.md` if it affects the next
   session.
3. If the outcome is load-bearing, add or update a row in `KEY_FINDINGS.md`.
4. If the outcome closes a broader question, write a phase note or results file
   and cite the raw evidence.
5. If the project direction changed, update `PLAN.md` and, if needed,
   `README.md`.

## What Should Move Out Of Live Notes

The following content does not belong in `RESUME_NOTES.md` long-term:

- old PRE/POST test plans once they are no longer near the frontier
- repeated restatements of already-pinned facts
- broad phase summaries that belong in `PLAN.md`
- multi-test syntheses that deserve their own note

When one of those starts growing, create a phase note and replace the long text
in `RESUME_NOTES.md` with:

- a 2-5 line summary
- a pointer to the durable note

## Suggested File Roles Going Forward

- `README.md`: what this project is and why it matters
- `PLAN.md`: what phase the project is in and what the next strategic goals are
- `KEY_FINDINGS.md`: facts that should survive every session
- `RESUME_NOTES.md`: what the next person needs right now
- `RESUME_NOTES_HISTORY.md`: archived session/test chronology
- `phase5/notes/phase5_progress.md`: phase-5 story arc, not the latest crash
- `phase6/NOTES.md`: phase-6 map and active analysis threads

## Writing Heuristics

- Prefer conclusions over chronology.
- Prefer one claim per section.
- Prefer links to evidence over repeated pasted evidence.
- Prefer updating an existing synthesis file over creating another loosely
  overlapping note.
- If a note does not change the next decision or preserve a hard-won result, it
  probably belongs in a log, not a markdown file.
