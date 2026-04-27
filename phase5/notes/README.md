# Phase 5 Notes Guide

Phase 5 is where the documentation volume is highest, so the note types need to
stay separate.

## Put content here

- experiment design for upcoming tests
- medium-term analysis of Phase 5 behavior
- synthesis of several related tests
- explanations of why a hypothesis was ruled in or out

## Do not put content here

- raw logs
- the current one-session handoff state
- cross-phase pinned facts

Those belong in:

- raw logs: `phase5/logs/`
- session handoff: `RESUME_NOTES.md`
- pinned facts: `KEY_FINDINGS.md`

## Preferred structure for a Phase 5 note

At the top of each note, include:

1. Goal
2. Inputs
3. Conclusion
4. Impact on next work

If a note mostly replays a sequence of tests, it should usually be split into:

- one short synthesis note here
- references to the exact `phase5/logs/test.*` files
