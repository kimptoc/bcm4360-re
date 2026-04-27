# CLAUDE.md Review

**Well-judged:**
- Legal section is standard clean-room practice, not overly cautious — necessary for RE work
- Push-after-commit and filesystem sync are pragmatic given crash history
- "Grep prior phases before declaring new findings" avoids expensive re-discovery
- Pre-test PCIe state check is load-bearing for this type of work

**Potential concerns:**

1. **Too rigid on hypothesis step** — "State your hypothesis" before *every* hardware test adds friction. Worth keeping for complex tests, but for quick register reads or minor tweaks, it's bureaucratic. Consider: "For non-trivial hardware tests, state your hypothesis..."

2. **No escape hatch for the checklists** — The pre/post-test checklists apply to *any* test touching hardware. But there's no guidance on what counts as a "test" vs. a quick probe. An `lspci` check isn't the same risk level as `insmod`. A tiered system (quick probe vs. module load vs. full test) would reduce friction.

3. **Passive phrasing in places** — "Consider updating KEY_FINDINGS.md" vs. the more decisive rules elsewhere. The closing-session instruction should be firmer: "Update KEY_FINDINGS.md if this session produced any load-bearing facts."

4. **Missing: failure mode branching** — The post-test checklist treats crash and success the same. Crashes need different recovery (check git integrity, verify filesystem). A short crash-specific sub-checklist would help.

5. **"Always push immediately after every commit"** — This is aggressive but defensible. One risk: pushing broken WIP commits. Could add: commit messages should flag WIP state explicitly (e.g., `WIP: mid-experiment`).

6. **No mention of automated testing** — For the non-hardware parts of the codebase, there's no lint/typecheck/test guidance. The project might benefit from that.

**Overall:** Appropriately cautious for a kernel-module RE project. The main improvement would be **tiering the checklist by risk** rather than applying full ceremony to every interaction.
