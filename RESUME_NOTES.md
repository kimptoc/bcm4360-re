# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-27 22:30 BST — POST-TEST.304 + 7 STATIC RECCES (T304b/c/d/e/f/g/h). **wl comparison stage 1 ATTEMPTED but FAILED to deliver core deliverable.** Two paths forward; awaiting user steer.

**Three closed surfaces (from earlier in session):**

- **PMU + GPIO** (T304c): host-reachable but no registered fw ISR.
- **DMA-via-olmsg via pciedngl_isr** (T304d): pciedngl_isr is a single-bit mailbox-doorbell handler that NEVER touches the olmsg ring at TCM[0x9d0a4]; reads from a bus_info-local ring at `bus_info+0x24`.
- **H2D_MAILBOX_1 doorbell** (T304e): two independent strands close this. (1) **Empirical:** pciedngl_isr has NEVER fired across n=8 hardware fires — `wr_idx=587` frozen at every probe stage; its first action is `printf("pciedngl_isr called\n")` which would advance wr_idx. (2) **Protocol:** fw blob has ZERO references to HOSTRDY_DB1 (0x10000000); upstream brcmfmac's `brcmf_pcie_hostready()` gates H2D_MAILBOX_1 writes on this flag.

**Option 2 (HW-internal events) static passes — T304f + T304g, just completed:**

- **T304f** (`phase6/t304f_d11_init_offload.md`): **Offload runtime does NOT initialize D11 MAC.** Zero D11 register writes in live code (T300 enumeration of all 8 D11+0x16C INTMASK writers confirmed every one is in dead FullMAC code: fn@0x142b8/0x181ec/0x2309e/0x233e8/0x2340c). Zero D11-base literals in 442 KB blob (T297j). Zero `si_setcoreidx(0x812)` calls in live BFS. fw obtains D11 base via si_doattach EROM walk (stored at sched_ctx[+0x88] per T287c) but never writes any D11 register. **Implication:** offload runtime never enables D11 RX/TX/TSF wake events; D11 surface is closed by design. Likely intentional — data-plane ops would happen over olmsg DMA, not D11 MAC events.

- **T304g** (`phase6/t304g_isr_registration_audit.md`): **T298's 2-node ISR enumeration (bits 0+3) is the empirically-confirmed wake surface — but the static audit found a real BFS gap that does NOT change the strategic verdict.** Static enumeration of all 3 direct-BL `hndrte_add_isr` (0x63C24) call sites: fn@0x63CF0 (RTE init, in live BFS, accounts for bit 0); fn@0x1F28 (pcidongle_probe, accounts for bit 3 registration); fn@0x67774 (FullMAC wl_attach, dead). **Crucial caveat advisor catch:** T304g claimed pcidongle_probe is "dead code" and the pciedngl_isr registration is "stale TCM persists across boots". This is empirically dead — TCM is volatile across cold boot, and T298/T303 observed the ISR list count CHANGE 1→2 during the T276 poll window (count=1 at post-set_active = only chipcommon-class; count=2 from post-T276-poll onwards = pciedngl_isr added). **pcidongle_probe IS being reached at runtime via a path the BFS missed** — the indirect-dispatch coverage gap row 161 flagged is REAL and unresolved. This does NOT contradict the strategic verdict (still 2 ISRs, bits 0+3) because T298 directly observed the linked list — the empirical observation is primary-source. But the BFS-based "no other ISRs could exist" inference cannot be made strongly.

**DO-NOT-PROPAGATE multiple agent overreaches in T304f/T304g** (advisor-flagged):
- T304g's "stale TCM" hypothesis (TCM is volatile + count changes during run)
- T304g's "Coverage Complete; BFS gap closed" verdict in its strong form
- T304f's §"OOB Router Architecture" again lists wlc_isr in registered ISRs (T298 found 2 nodes, no wlc_isr — same error T304c made)
- T304f's "pciedngl_isr ... Yes (T256: fires every second at t+90s..t+120s)" is fabricated — T256 was static disasm correlation, not runtime observation; empirical record is wr_idx=587 frozen across n=8

**PATTERN CAVEAT (n=3+ now: T304c, T304e, T304f):** subagents have repeatedly invented runtime ISR-firing claims from static identification cites. When a static report says "fires" or "executes", cross-check against the wr_idx=587 frozen record before propagating. **Static reach ≠ runtime execution.** Logged in KEY_FINDINGS as a cross-cutting note.

**Strategic state — UNCHANGED by T304f/T304g:**

- Option 1 (`wl` driver comparison): **HIGHEST-VALUE REMAINING DIRECTION**. The vendor `wl` driver successfully drives this chip — capturing its register-write sequence and diffing against brcmfmac is the cleanest path forward.
- Option 2 (HW-internal events): T304f confirms D11 dormant; T304g confirms 2-ISR wake surface. The "synthetic injection via D11/PHY config" angle is closed by D11 dormancy. Other HW-internal events (chipcommon, PMU, GCI) have no registered handler. Option 2 is effectively closed without firmware modification.
- **No fire warranted.** No hypothesis sharp enough.

**Stage 1 of `wl` comparison (T304h) ATTEMPTED 2026-04-27 22:25 BST — FAILED to deliver core deliverable.**

Subagent task: disasm wl.ko's PCIe init and identify what wl does that brcmfmac doesn't. Agent CAPTURED wl.ko symbol map (real, useful: `wl_pci_probe`, `pcicore_attach`, `pcicore_up`, `osl_pci_write_config`, `si_pcie_*`) and provided brcmfmac walkthrough — but **DID NOT actually disasm wl.ko functions**. Agent's own Open Questions §1+§2 admit: "Does wl.ko write MAILBOXMASK before fw download? Currently unknown." and "Does wl.ko write H2D_MAILBOX_1 unconditionally? Current hypothesis: yes." The "Modification 1: Pre-set_active MAILBOXMASK Write — Highest Confidence" recommendation is justified by "wl.ko likely does this (all major init before ARM release)" — that's INFERENCE, not OBSERVATION.

**PATTERN CAVEAT NOW n=4** (T304c, T304e, T304f, T304h): subagents hit a complexity wall (here: x86-64 disasm of proprietary closed-source kernel module is harder than ARM Thumb fw blob disasm — more inlining, PLT/GOT indirection, kernel-API wrappers) and INVENT findings rather than report incomplete work. Pattern is stable enough to plan around: tighter prompts demanding "show disasm offsets + instructions for the specific claim, or report 'could not locate'", OR do high-stakes disasm directly.

**Reframing (advisor catch):** T304h conflated TWO SEPARATE hypotheses that should be evaluated independently:
- **(a) "Move brcmfmac MAILBOXMASK write to pre-set_active"** — a brcmfmac-internal hypothesis worth testing on its own merits. T241/T280/T284 established post-set_active MAILBOXMASK writes silently fail; pre-set_active writes might succeed. **Stands regardless of what wl does** — low-confidence but cheap to test (single brcmfmac code-only modification + single-shot fire).
- **(b) "wl.ko writes H2D_MAILBOX_1 unconditionally"** — an unverified wl claim. Needs wl.ko verification before it's actionable.

Don't let them ride together.

**Three paths forward — needs user steer:**

- **Path A — Tighter static retry on wl.ko.** Re-prompt a subagent with a NARROW target (single function: `pcicore_attach`'s MAILBOXMASK write site only) with explicit "show disasm bytes for the specific claim, or report 'could not locate'" requirement. Lower budget, sharper deliverable. ~15-20 min. Risk: subagent could hit the same wall; this would tell us static is genuinely too hard for x86-64 wl.ko and we should switch to Path B.
- **Path B — Skip to live wl trace.** Edit `/etc/nixos/configuration.nix` to un-blacklist wl, `nixos-rebuild boot`, reboot, let wl bind to the chip + bring it up. Capture register/MMIO writes via bpftrace/kprobes on `pci_*_config_*` + `iowrite32`. Then revert + reboot to return to brcmfmac dev mode. Real system-state change but bounded; ~30 min round-trip including reboot cycles. **Empirical observation, no static inference needed.**
- **Path (a) — Independent test of "MAILBOXMASK timing" hypothesis.** Cheap brcmfmac-only modification: move the MAILBOXMASK write to pre-set_active timing, fire and observe whether mask persists + whether wr_idx advances. **Doesn't depend on what wl does.** Tests the timing-failure-mode hypothesis directly. Single-shot probe; substrate cost only. Could run in parallel with A or B.

**Recommendation:** Path B is probably the cleanest — empirical capture of what wl actually does is more valuable than another static gamble. Path (a) is a parallel-able cheap experiment if user wants to maximize information per session. Path A is the most conservative but risks burning more time on the same failure mode.

**Three host-driveable wake-injection candidates closed (T304b–T304e):** PMU/GPIO, DMA-via-olmsg, H2D_MAILBOX_1. Option 2 (HW-internal events) effectively closed without fw mod (T304f D11 dormant; T304g 2-ISR confirmation with BFS gap caveat). Strategic state UNCHANGED — wl comparison still highest-value remaining direction; just harder than expected to extract via static analysis alone.

**User chose Path B (live wl trace) 2026-04-27 23:20 BST. Cycle 1 in progress.**

## PRE-CYCLE.1 (live wl trace — does wl wake the fw?)

**Hypothesis:** vendor `wl` driver (broadcom-sta-6.30.223.271-59, version-matched to fw RTE 6.30.223 banner) successfully wakes this fw under normal driver init. Empirical observation under wl will tell us:
- whether the fw is in fact wakeable at all in this hardware/SROM/NVRAM configuration
- if yes, the chip-side state under wl (TCM[0x9af88] console wr_idx, TCM[0x629A4] ISR list count, sched_ctx, lspci config) — comparable to the n=8 brcmfmac wedge baselines
- the gap between wl-driven and brcmfmac-driven chip state

**Decisive question (cycle 1):** does TCM[0x9af88] console wr_idx advance past 587 under wl?

If YES → wl knows the right protocol; cycle 2 captures the PCI config sequence wl uses.
If NO → either wl can't drive this fw build either (different problem entirely — SROM/NVRAM/fw-version mismatch we missed) OR wl uses a different mechanism that doesn't write to console. Either is informative.

**State change executed:**
- `/etc/nixos/configuration.nix.preWlCycle1` — backup of pre-edit state (copied via sudo)
- `/etc/nixos/configuration.nix` line 21 — `wl` removed from blacklist (kept `b43 bcma ssb` blacklisted; comment added cross-referencing this cycle)
- `sudo nixos-rebuild boot` — IN PROGRESS at writeup time (background bash bzg217kcs, log at /tmp/nixos-rebuild-boot-cycle1.log)

**Required AFTER nixos-rebuild boot completes:**
1. Verify rebuild succeeded: `tail /tmp/nixos-rebuild-boot-cycle1.log` — look for "activated" not error
2. **Commit + push + sync** (this RESUME_NOTES + the .preWlCycle1 reference; nixos config itself is in /etc/nixos not in this repo — note that)
3. **User reboot:** `sudo reboot`

**POST-REBOOT capture sequence (run in cycle 1 by post-reboot Claude):**

1. **PCIe state check:** `sudo lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta|LnkCtl'` → expect MAbort-, CommClk+
2. **Verify wl bound:** `lspci -k -s 03:00.0` should show "Kernel driver in use: wl"
3. **Check wl probe in dmesg:** `sudo dmesg | grep -iE 'wl|broadcom|bcma|brcm' | head -50` (look for wl_pci_probe success, fw load, interface up)
4. **Check WiFi interface:** `ip link show` — should show new wlanX or eth0 interface
5. **DECISIVE READ — TCM[0x9af88] (console wr_idx) via /dev/mem mmap of BAR2:**
   - BAR2 base = 0xb0400000 (per lspci pre-cycle reconnaissance — verify post-cycle)
   - wr_idx field is at TCM[0x9af88] + offset within console_ctx struct (per T276/T278 — wr_idx is a u32 within the struct that si[+0x010] points to). Need to read the struct ptr first.
   - Alternative: read BAR2[0x9af88+offset] directly. Per T277/T278 instrumentation: si[+0x010] = console_struct_ptr; struct@console_struct_ptr has buf_addr at +0, buf_size at +4, write_idx at +8 (or near).
   - Pragmatic approach: write a small Python script using mmap + struct to read BAR2 directly. Code sketch:
     ```python
     import mmap, struct
     with open('/sys/bus/pci/devices/0000:03:00.0/resource2', 'rb') as f:
         mm = mmap.mmap(f.fileno(), 0x100000, prot=mmap.PROT_READ)
         # Read si[+0x010] = console_struct_ptr (relative to TCM start)
         console_ptr = struct.unpack('<I', mm[0x9af88+0x10:0x9af88+0x14])[0] & 0xfffff
         # Read wr_idx within console struct
         buf_addr = struct.unpack('<I', mm[console_ptr:console_ptr+4])[0]
         buf_size = struct.unpack('<I', mm[console_ptr+4:console_ptr+8])[0]
         wr_idx = struct.unpack('<I', mm[console_ptr+8:console_ptr+12])[0]
         print(f'console_ptr=0x{console_ptr:08x} buf_addr=0x{buf_addr:08x} buf_size=0x{buf_size:08x} wr_idx={wr_idx}')
     ```
   - **Decisive comparison:** if wr_idx > 587 → wl is advancing the console; **wl HAS WOKEN THE FW**. If wr_idx == 587 (or whatever wl init writes — could be different baseline if wl uses a different shared_info) → no advancement during wl init.
6. **Read TCM[0x629A4] ISR list head + count:** walk linked list (each node = 16 bytes: next, fn, arg, mask) — count nodes. Compare against T298's 2 nodes. If >2, wl has registered additional ISRs.
7. **Snapshot lspci** for config-space deltas: `sudo lspci -vvv -s 03:00.0 > /home/kimptoc/bcm4360-re/phase6/cycle1_lspci.txt`
8. **Snapshot dmesg** (full wl-side messages): `sudo dmesg > /home/kimptoc/bcm4360-re/phase6/cycle1_dmesg.txt`
9. **Document POST-CYCLE.1 in RESUME_NOTES** with all readings.

**Privacy note:** wl will probably broadcast probe requests to scan for networks. May try to auto-associate if any saved network config exists (unlikely in clean nixos but possible). User confirmed OK with this.

**Cleanup cycle (after capture):**
1. `sudo cp /etc/nixos/configuration.nix.preWlCycle1 /etc/nixos/configuration.nix` — restore blacklist
2. `sudo nixos-rebuild boot`
3. Commit + push + sync
4. User reboots
5. Verify back to dev mode (brcmfmac usable, wl blacklisted)

**Substrate note:** the chip is going through 2 reboot cycles + actual wl init. The "fresh substrate" baselines from earlier in this session no longer apply post-cleanup — would need new baselines if any further brcmfmac fires happen. For wl-discriminator purposes this is fine.

**Awaiting nixos-rebuild boot completion to commit + push + reboot.**

**Substrate is fresh** (boot 0 @ 21:16:01). PCIe lspci clean. No code changes outstanding. T304 macro is empirically validated. Docs cleaned up per DOCS.md §3 (T299/T300/T301 pairs migrated). PLAN.md, RESUME_NOTES, KEY_FINDINGS all current as of this writeup.

**Earlier in session (2026-04-27):** T304 fire result + POST-TEST.304 + KEY_FINDINGS gate-1 row + row 104 extension. T304b (no-pollers) + T304c (PMU/GPIO dormant) static recces. T304d (pciedngl_isr disasm — mailbox-only). T304e (bus_info+0x18 trace — HOSTRDY_DB1 absence). T304f + T304g (D11 dormant + ISR coverage audit; this commit). **KEY_FINDINGS gained 7 new rows total this session.**

**Earlier session work (kept for context):**

- POST-TEST.303 written up + committed (commit 3c85608); KEY_FINDINGS rows 104/162/163 updated

**Gate-stack result (commit 4adaa81, phase6/t303e_oob_gate_stack.md).** 6 gates between host writing OOB Router pending and fn@0x115c executing on ARM:

| Gate | Status | Evidence |
|---|---|---|
| 1: Write semantics (RW1S/W1C/RO) of 0x18109100 | UNKNOWN — empirical only | Agent acknowledges "cannot be done statically". Note: agent's "Linux bcma drivers don't write OOBSELOUTA30" argument was wrong-target — OOBSELOUTA30 is at chipcommon-wrap +0x100, NOT OOB Router (0x367) +0x100. Different agents, doesn't transfer. |
| 2: oobselouta30/74 routing enable bits | UNKNOWN | T298 confirms slots allocated but not whether they're enabled for output |
| 3: ARM CR4 IRQ controller mask | UNKNOWN (plausibly open) | T303d's "fallthrough from exception vectors" is *thin inference* — could be missed indirect dispatch. **No empirical evidence any ISR has fired in live offload runtime** (n=8 fires across T276/T287c/T298/T299/T300/T301/T302b/T303 all show console wr_idx=587 frozen post-init; T279 H2D_MBX_0 positive control returned MAILBOXINT=0). |
| 4: SiliconBackplane upstream path | UNKNOWN | No public docs for ARM 0x367 routing |
| 5: fn@0x115c reachability | KNOWN-OPEN | Per T303d unconditional fallthrough |
| 6: BAR0 accessibility to 0x18109000 | PARTIALLY-OPEN | Clean at post-set_active n=2 (T300/T301); T301 t+60s wedge open question |

**Gate-1 fire decision rationale.** Cycle of static surfaces yielded all bookkeeping (gap writers + sched+0xCC) plus one decisive structural finding (on-dispatch only). No further static surface can resolve Gate 1 — the agent that found the gap admits it's empirical-only. Continuing the defer cycle is sunk cost. Proposed move:

**PRE-TEST.304 — Gate-1 empirical probe.** Single BAR0 transaction sequence at post-set_active timing:
1. Save BAR0_WINDOW
2. `pci_write_config_dword(BAR0_WINDOW, 0x18109000)` (point at OOB Router agent — proven safe in T300/T301 sample 1 n=2)
3. Read BAR0+0x100 (baseline pending) — expect 0x0
4. Write BAR0+0x100 = 0xFFFFFFFF (the test write)
5. Read BAR0+0x100 (post-write) — discriminator
6. Restore BAR0_WINDOW

Outcomes:
- post-write read = 0xFFFFFFFF → **RW1S** → Gate 1 is RW1S; host CAN set bits → potentially fire-able B
- post-write read = 0x0 → **W1C** OR **RO**; the bit semantics is "write-1-clears" or "ignored". Either way host cannot set bits via this register → option B via OOB Router pending is dead; need to find another wake-trigger surface
- post-write read = 0xFF... AND console wr_idx advances OR follow-up scan shows fw state change → BONUS: partial Gate 3 evidence (downstream dispatch must have happened)

Risk: identical to T300 sample 1 — single BAR0 transaction at post-set_active, OOB Router agent, no wedge in T300/T301 sample 1 (n=2 clean). Code edit needed: new test304 macro modeled after test300 with the write+readback step added. One extra BAR0 write vs T300; risk delta negligible.

**Awaiting user steer.** Three options:
1. **Approve PRE-TEST.304 as proposed** — code edit, rebuild, fire when substrate in clean window.
2. **Modify the probe** — e.g. write specifically `0x9` (just bits 0+3) instead of `0xFFFFFFFF` to test bit-set-with-routed-bits-only, or run two separate writes.
3. **Defer further** — request additional static work (e.g. one more pass on Gate 3 looking for explicit ARM IRQ enable code, or PMU GPIO investigation).

**A2-extension result (commit 49c3c35, phase6/t303b_gap_writers.md).** Subagent identified `fn@0x64590` (core enumerator, called from si_doattach at fn@0x670d8) as the writer of all 6 populated dwords at sched+0x318..+0x32c via indexed store at address 0x6466e (`str.w r0, [r4, r3, lsl #2]` where r3 = slot+0xc6). Values come from `fn@0x2728` (EROM core-descriptor parser) — per-core revision + wrapper capability fields cached at init from EROM. One entry per host-enumerated core, slot order matches T218 exactly. **Why static scan missed it:** writer location WAS documented in phase6/t288_pcie2_reg_map.md:90 — the gap was a documentation/cross-reference miss, not an analysis miss. **Wake-question impact: zero** — these are initialization-time metadata, no runtime readers identified in BFS scan. Gap resolved.

**sched+0xCC writer result (commit 5465446, phase6/t303c_cc_writer.md).** Subagent identified `fn@0x27EC` (si_setcoreidx class-0 thunk) as the writer at address 0x02878 via `str.w r5, [r4, #0xcc]`. The value written is the active class index. The 0x0 → 0x1 transition during T276 poll = class switch from chipcommon (class 0) to core[2] (class 1) — **independently corroborates** the sched+0x88 shift from 0x18000000 → 0x18001000 already documented in row 132/137 (caught by T287/T298 at later stages). sched+0xCC is per-class context bookkeeping, not a wake gate. **Wake-question impact: minimal** — confirms fw is alive and progressing through class switches as expected, doesn't identify what fw waits for.

**EMPIRICAL REFRAME (advisor catch, primary-source).** T303 console wr_idx=587 frozen from t+500ms through t+90s (no new console output across 4 sample stages). fw IS quiescent at console-logging resolution — "fw waiting for wake event" is no longer assumption, it's primary-source evidence. Worth checking T287c/T298/T299 for cross-fire confirmation but the n=1 in T303 is unambiguous.

**Option 4 result (commit 0cf433b, phase6/t303d_oob_reader_schedule.md).** **OOB pending-events is read ON-DISPATCH ONLY** (90% confidence). The 3-insn leaf reader fn@0x9936 has exactly ONE caller: fn@0x115c (synchronous ISR dispatcher at fw addr 0x001162). fn@0x115c is **not registered as a timer callback** and has **no direct BL/BLX callers** — reached only via fallthrough from the exception-vector chain (fn@0x138 + continuation per row 161). Read-dispatch-return pattern, single read per invocation, no loop/sleep/poll. fw IS in WFI; only an ARM exception (HW IRQ assert) can wake it.

**Advisor reframe 2026-04-27 20:48 BST after option-4 result.** Original "draft B (DMA-via-olmsg)" framing was wrong — DMA-via-ring depends on a poller that doesn't exist. **The actual decision is downstream of two unverified facts:**

1. **OOB Router +0x100 register write semantics.** The option-4 agent recommended "host writes 0x18109100 to set bits 0/3" assuming RW1S (write-1-to-set). Could be W1C (write-1-to-clear, common HW pattern — `0x9` would CLEAR bits, not set them) or read-only-by-host (status of upstream OOB lines, host writes ignored). RW1S is one of three plausible behaviors picked without evidence.

2. **Full gate stack between OOB pending bit being set and fn@0x115c executing.** T279 found MAILBOXMASK=0 — gates the **PCIE2 mailbox path** (H2D_MAILBOX_0/1 → mailbox interrupt → ARM). The OOB Router is a **different upstream-line aggregator** — bits 0/3 of OOB pending route to ARM via different selector registers (`oobselouta30` per row 144). MAILBOXMASK=0 does NOT necessarily gate OOB-Router-driven IRQs. But there may be other masks: a second OOB-side enable register (e.g. `oobselouta74` at agent +0x104), or an ARM-side interrupt controller mask. **Unmapped.** Whether B is even possible rides on this stack.

**Next move:** kick off third static subagent to MAP THE GATE STACK between OOB pending bit set and fn@0x115c execution. Identify each gate as known-open / known-closed / unknown. Cheap (no fire). Then advisor consult on whether B is fire-able or whether more work needed. ~~Draft B PRE-TEST~~ deferred — premature until gate stack mapped. T303 FIRED at 20:10:56 BST (boot -1 uptime ~21 min — late but within row 83 clean window per row 83). All probe stages CLEAN through `t+90s SUMMARY count=2 sched_cc=0x1 events_p=0x18109000 pending=0x0` plus T303 readouts at every stage. **Boot -1 ended at 20:13:11** — silent kernel death right after t+90s SUMMARY, exact same [t+90s, t+120s] T270-BASELINE pattern (now n=7 without test300). Auto-recovery, NO SMC reset (boot 0 started 20:14:43). Current uptime ~2 min, lspci clean (MAbort-, CommClk+).

**Headline T303 results (all BAR2-only sched_ctx field reads, modeled after T287c):**

1. **`sched+0xD0` (count) = 0x5 stable** across all 6 stages.
2. **`slots[+0xD4..+0xF0]` = `0x800 0x812 0x83e 0x83c 0x81a 0x135 0x0 0x0`** stable across all stages — first 6 entries match host-side `brcmf_pcie_select_core` enumeration (T218) EXACTLY in order; slots 6-7 zero. **OOB Router (0x367) is NOT in the slot table** → confirms KEY_FINDINGS row 162 framing: OOB Router is accessed via the separate `sched+0x358 = 0x18109000` pointer, outside the indexed slot model.
3. **`sched+0xCC` is NOT stable across stages** — `0x0` at post-set_active, `0x1` from post-T276-poll onwards. T287/T298 framed this as "0x1 stable" but never sampled at post-set_active — prior framing was **stage-incomplete, not wrong**. Transition window = the ~2s T276 poll. NEW signal worth a row 163 update.
4. **`gap +0x300..+0x354`** (22 dwords) is **NOT all zero** as t300_static_prep §65 expected. 6 populated dwords at `+0x318..+0x32c`: `2b084411 2a004211 02084411 01084411 11004211 00080201`, stable across all stages. Rest zero. **Note: populated entries are at gap indices 6..11 (offsets +0x18..+0x2c into the gap), NOT 0..5** — so these are NOT trivially 1:1 with the 6 populated slots at +0xD4..+0xE8. Structure unclear; record-bytes-defer-interpretation. Static analysis (t288_pcie2_reg_map enumerator) found no writers — fw populates this region at runtime via a path the static scan missed.

**count semantics — open between two readings:**
- (a) `count` = last allocated *index* (0-indexed): count=5 means slots 0..5 valid → matches host enum exactly.
- (b) `count` excludes the I/O hub core (0x135 has base=0): fw counts 5 "real" backplane cores.

(a) is the boring/likely answer. Don't pick (b) just because it's tidier. Either way the load-bearing claim is the same: **slot table = host enum exactly; OOB Router 0x367 NOT in slot table** — primary-source confirmation that fw uses the separate `sched+0x358` pointer for OOB Router access.

**Wedge timing caveat.** All probe printks are bunched at 20:13:10/11 in journalctl, but insmod was 20:10:56 and `test.158: ASPM disabled` printed at 20:11:00 normally. The 2-minute gap = fw boot/wait. The 20:13:10/11 bunching is journald draining the printk buffer as the kernel dies — i.e., **journalctl timestamps cannot extract precise stage timing for this run.** Wedge bracket [t+90s, t+120s] is inferred from script-level fact (insmod returned, `sleep 150` was wedged inside), not from printk timestamps.

**Hypothesis matrix outcome.** Closest match to row 2 of PRE-TEST.303 matrix ("sched+0xD0 = 6 AND slot table = host enum") with the count=5/6-IDs split as a footnote. OOB Router accessed via separate fw-internal pointer outside slot model — **CONFIRMED**.

**Wake-trigger source: NO ADVANCE.** T303 was BAR2-only by design; it does not read OOB Router pending. Sample 2 question (does pending ever transition to non-zero) is still unanswered across T300/T301/T302b/T303.

**Headline result.** Dropping `test300_oob_pending` MOVED wedge BACK to [t+90s, t+120s] — outcome row 1 of PRE-TEST.302b matrix. **Strong causal inference:** test300 BAR0 OOB Router read at post-set_active IS shifting the wedge bracket forward (n=6 without test300: T270-BASELINE/T276/T287c/T298/T299/T302b → wedge at [t+90s, t+120s]; n=2 with test300: T300 (~t+45s) / T301 (t+60s)). Also: T302b also dropped `test284_premask_enable` (the only other module-param diff vs T298/T299) but wedge bracket UNCHANGED — **eliminates the test284 confound from row 104.** test284 is NOT the wedge-shifting factor.

**Secondary confirmation (n=3).** `count=1` at post-set_active (only RTE-CC ISR registered) → `count=2` at post-T276-poll (pciedngl_isr added) reproduces in T302b — same as T300/T301. Likely correlated with `test284_premask` being DROPPED (n=3 for both). T298/T299 with `test284_premask=1` saw count=2 at post-set_active. Not load-bearing for the wake question; possibly indicates test284 reorders pciedngl_isr registration earlier.

**Wake-trigger source: NO ADVANCE.** test300 dropped means no OOB Router pending sample at all in T302b. The "is `pending` ever non-zero" question is unanswered — sample 2 has now never been read across T300/T301/T302b. Strong inference says test300 must be redesigned (single-shot at post-set_active only, or much earlier sample 2) to ever read pending at a different timing without destabilizing the bracket.

Prior fire (T301, 19:24:49 BST): sample 1 BAR0 OOB Router read at post-set_active SUCCEEDED (n=2 with T300, `pending=0x00000000`). **Wedge at t+60s, AT sample 2's BAR0 OOB Router window-write** — anchor-2 ("saved=0x18102000; about to set OOB Router window") flushed, anchor-3 never logged. Auto-recovery, no SMC reset. T302b discriminator now answers the test300-causal question (CAUSAL).

T299 FIRED 15:29:00 BST on boot -1 with full ASPM-disabled chain (cmdline `pcie_aspm.policy=performance` parsed, runtime sysfs flip applied at 15:27:57 before insmod; 03:00.0+02:00.0+root all `ASPM Disabled`). Probe ran clean through all 9 stages — IDENTICAL 2-node ISR readout to T298. Wedged at end-of-t+90s probe (boot -1 ended 15:31:05, ~7s after t+90s SUMMARY). User cold-boot/SMC reset; current uptime now ~30+ min, ASPM back to default. **H1 (ASPM = wedge cause) FALSIFIED.** **Wedge is the known [t+90s, t+120s] bracket** (KEY_FINDINGS row 104, T270-BASELINE pattern, reproduced T276/T287c/T298/T299) — NOT a "rmmod wedge" as POST-TEST.298 mistakenly claimed.

**T300 step 1 — static prep result.** Explore agent pass found: fw reads OOB Router pending-events at `0x18109100` LIVE via `fn@0x9936` (3-insn leaf: `ldr [sched+0x358]; ldr [+0x100]; bx lr`). Zero writers of this register into TCM exist anywhere reached from the live BFS. The ISR-list at `TCM[0x629A4]` (already enumerated by T298/T299) is the only OOB-bit→callback cache in TCM. Per-slot core-ID table at `sched+0xd0..` IS BAR2-readable and would cross-validate against host-side enumeration but does not advance the wake question. Per `t299_next_steps.md` §3, next move is A3 — single-purpose BAR0 OOB Router read with strict scope and exit before t+90s. Full report: `phase6/t300_static_prep.md`.

**Advisor catches that corrected the framing.** Two errors caught in T298/T299 post-test interpretation:
1. **"rmmod wedge" was always wrong.** `journalctl --list-boots` shows boot -5 ended `14:21:34` (T298) and boot -1 ended `15:31:05` (T299). Script `sleep 150` puts rmmod ~150s after insmod return — both boot-ends are well before that. Wedge is at end-of-t+90s probe (~7s after t+90s SUMMARY in T299; same in T298). rmmod never executed. **POST-TEST.298 incorrectly attributed the wedge to rmmod; it was actually the [t+90s, t+120s] bracket per row 104.** Update KEY_FINDINGS row 163 accordingly.
2. **T299 t+90s readout latency rose mid-stage.** T298 t+90s: all 4 readout lines at `14:21:34` (single second). T299 t+90s: `15:30:55→15:30:58` (3-second spread, 1s+ between consecutive prints). Each `printk` taking ~1s is anomalous — TCM read latency was rising for several seconds before silent kernel death. NEW signal vs T298 (which printed instantly then died). Could be the ASPM-disabled chain causing different bus-state behaviour, or could be substrate variation. n=1 fire with this latency pattern; not yet load-bearing.

**Result of T299.** ASPM-disabled chain (full: 03:00.0 + 02:00.0 + root port 00:1c.2) made ZERO difference to either the noise belt (T299 was the second clean fire in a row, BAR2-only path holding) OR to the [t+90s, t+120s] wedge bracket (T299 wedged at the same point T298/T287c/T276/T270-BASELINE did). Per row 104 + row 163 update: this wedge has been observed under 5 different module-param + cmdline combinations now and is fw-side, not host-side ASPM management.

**Cmdline correction history.** Four attempts at the same intent (force ASPM Disabled on the link):
1. v1: `pci=noaspm` — passive, cannot disable BIOS-enabled ASPM. Post-reboot LnkCtl showed L0s L1 still Enabled.
2. v2: `pcie_aspm=off` — *also* passive. Disables the kernel ASPM management subsystem ("PCIe ASPM is disabled" in dmesg) but BIOS-written LnkCtl bits remain. Post-reboot 2026-04-27 evening: 03:00.0 still `ASPM L0s L1 Enabled`, 02:00.0 still `ASPM L1 Enabled`. Per-device `link/` sysfs not created (subsystem disabled), policy knob locked at runtime.
3. v3: `pcie_aspm.policy=performance` — added to cmdline, `nixos-rebuild boot` ran cleanly, /proc/cmdline confirms it post-reboot — but kernel ignored the param. Sysfs `policy` still showed `[default]`, LnkCtl on 03:00.0 still `ASPM L0s L1 Enabled`, 02:00.0 still `ASPM L1 Enabled`. Subsystem WAS live this time (sysfs writable, `link/` dir present), so the param was at least parsed enough to keep the subsystem alive — just not applied. Likely cause: kernel-internal early default committed before `pcie_aspm` saw its module param.
4. **v4: runtime sysfs flip.** `echo performance | sudo tee /sys/module/pcie_aspm/parameters/policy` — actively disables. Verified 2026-04-27 post-third-reboot: policy sysfs now `default [performance] powersave powersupersave`. LnkCtl post-flip: 03:00.0 `ASPM Disabled`, 02:00.0 `ASPM Disabled`, 00:1c.0 root port `ASPM Disabled`. MAbort- everywhere. CommClk+ on 03:00.0 and 02:00.0, CommClk- on root (structural, not a fault).

T299 fire premise (PRE-TEST verification step 5) now satisfied via runtime path instead of boot path. The single-bit hypothesis is unchanged.

**Model.** The blob carries two runtimes; the live one is HNDRTE/offload, not
the `wl_probe → wlc_*` FullMAC chain. T298 just provided primary-source
confirmation: only 2 ISRs are registered at runtime (pciedngl_isr + RTE
chipcommon-class ISR). No `wlc_isr` (fn=0x1146D) — the FullMAC chain stays
dead in offload mode as predicted by KEY_FINDINGS row 161.

**What just happened.** PRE-TEST.298 fired ~14:19:30 BST after user cold
cycle. Probe ran cleanly through all 7 stages (pre-write, post-write,
post-set_active, post-T276-poll, post-T278-initial-dump, t+500ms, t+5s,
t+30s, t+90s) — **substrate-noise belt was passed**, first such fire
since T293. Watchdog late-ladder wedge during rmmod attempt (~t+150s)
required user SMC reset; orthogonal to the probe success. Cold-booted
14:31 BST; uptime ~2 min at writeup time.

**Primary-source result.** ISR-list at TCM[0x629A4] = 2 nodes, frozen
across all 5 post-set_active stages (no churn between t+0 and t+90s):

| Node | TCM addr | fn | arg | mask (OOB-slot bit) | Identification |
|---|---|---|---|---|---|
| 0 | 0x0009627c | 0x1c99 | 0x58cc4 | 0x8 (bit 3) | pciedngl_isr (T256 reproduces) |
| 1 | 0x00096f48 | 0x0b05 | 0x0 | 0x1 (bit 0) | RTE chipcommon-class ISR (fn@0xB04+thumb) |

`mask` = `1 << bit_index` where `bit_index` was returned by BIT_alloc
reading chipcommon-wrap+0x100 (`oobselouta30`) at `hndrte_add_isr` time.
**The RTE chipcommon-class ISR was allocated bit 0** — primary-source
identification of the OOB slot. The wake-trigger that SETS bit 0 is
still LIVE; what's confirmed is the routing slot, not the trigger
source.

Auxiliary fields (with caveats):

- `sched+0xCC = 0x1` stable across all stages. **Semantics unclear** —
  not the live class-ID (predicted 0x800/0x812 in PRE-TEST). Could be
  a status/flag word; per row 137, slot counter is at +0xD0 so +0xCC
  is something else.
- `events_p = sched+0x358 = 0x18109000` — chipcommon-wrap MMIO REGION
  address (0x18100000 + 0x9000), NOT a TCM-internal pointer. Outside
  T298_RAMSIZE_BOUND (0xA0000), so the bounds check in the macro
  rejected it and `pending=0` is a CODE-PATH PLACEHOLDER, not a
  measurement. The events_p VALUE is real and meaningful (fw stores
  a backplane MMIO addr at sched+0x358); the pending VALUE is not.
- `+0x88 = 0x18001000` (D11 base) at post-set_active onwards — class
  shift to core[2]/D11 happens earlier than T287c previously sampled
  (already there at post-set_active, not after the 2s poll).

**What the result confirms / weakens / leaves open.**

- **CONFIRMED:** row 161 (live runtime ≠ FullMAC) — only 2 nodes, no
  wlc_isr. wl_attach's hndrte_add_isr call site never executed.
- **CONFIRMED-PARTIAL:** row 148 (chipcommon-wrap is the wake-routing
  surface) — bit 0 of `oobselouta30` is what the chipcommon-class ISR
  was allocated at registration. The mechanism (BIT_alloc reads OOB
  selector to claim a slot) is live and produced a value.
- **STILL LIVE:** what HW event sets `oobselouta30` bit 0 (or any bit)
  to wake fw from WFI. Pending=0 is uninformative (placeholder), so we
  haven't observed any event firing or not firing.
- **STOPPING-RULE VINDICATED:** row 85's "pivot to TCM-only, off BAR0"
  rule worked. T298 is the first probe-bearing fire to clear the
  substrate-noise belt since T293. The 4-null T294→T297 streak was
  caused by BAR0 chipcommon/wrapper touches, not by something in the
  shared scaffold.

**Next discriminator (post-A1 resolution).** A1 was resolved via static
docs/EROM cross-check: `events_p = sched+0x358 = 0x18109000` is the
**ARM OOB Router core (BCMA core ID 0x367)**, per phase1 EROM walk +
Linux `bcma.h:76`. Distinct backplane agent (NOT chipcommon-wrap
interior). Host-side bcma enumeration (test.218) misses this core; fw
uses it via direct backplane access. Its `+0x100` register is the
pending-events bitmap fw reads to decide which OOB-routed ISR to wake.

What this resolution changes for direction-picking:

- "Candidate A — TCM-side `oobselouta30` shadow" was largely answered
  by T298 already: node[+0xC] mask values ARE the OOB allocation
  result. There is no separate "live oobselouta30 value" to chase
  (the register is routing config, not pending flags).
- The newly-identified target is the OOB Router pending register at
  0x18109100. Reading it is what would tell us which OOB lines are
  asserted at runtime. But that's a BAR0 read — and we don't yet know
  whether the BAR0 row 85 noise belt is chipcommon-wrap-specific or
  generalises to all backplane reads (T297 wedge was specifically on
  chipcommon-wrap+PCIE2-wrap; OOB Router is a different agent).

Three remaining candidates, awaiting user steer:

1. **A2 — More BAR2 sched_ctx mapping.** Cheap, speculative. Read
   sched+0xD0 (slot counter per row 137), +0xD4-table (per-slot core-id
   per row 138), the +0x300–0x350 gap, +0x35C onwards. Might find a
   TCM-resident dispatch table tying OOB bits → ISR nodes. Risk: low;
   yield: speculative.
2. **A3 — Read OOB Router pending-events at 0x18109100 via BAR0.**
   The actual wake-state register. Risk: row 85 noise belt may bite at
   any BAR0 chipcommon-wrap-region read — though OOB Router is a
   different agent than the chipcommon/PCIE2 wraps that wedged in T297.
   Single read, 1-shot scaffold; cold-cycle budget needed.
3. **B — Host-side wake-event injection.** DMA transfer over Phase 4B
   olmsg ring (already plumbed at shared_info), MSI assert, or
   `pci=noaspm` upstream lead from row 152. Most ambitious; biggest
   information yield if it works.

The user's earlier "1 pls" picked A as written in PLAN.md. With A1
resolved and the framing collapsed, the choice has changed shape. New
question to user: A2, A3, or B?

**What not to retry blindly.**

- Same as before: BAR0 chipcommon/PCIE2/wrapper reads at any timing
  (row 85), PCIe2 mailbox / D11 INTMASK wake probes (rows 125/159).
- **Don't claim "wake gate identified at chipcommon-wrap+0x100 bit 0".**
  That conflates the OOB allocation slot (now known) with the trigger
  source (still unknown).
- Don't burn another fire just to re-read T298 — the 2-node result is
  primary-source and stable. Need a NEW probe, not a re-fire.

**Substrate state.** Cold-booted 14:31 BST, lspci clean as of 14:32.
Uptime 2 min — fresh window. Next plan should be drafted while still
fresh; don't fire again without one.

---

## PRE-TEST.302b (drafted 2026-04-27 19:43 BST on user GO. Drops `bcm4360_test300_oob_pending=1` AND `bcm4360_test269_early_exit=1` from the T301 fire; otherwise unchanged. Restores `sleep 150` per T298/T299 baseline so the t+90s/t+120s probes actually run. NO rebuild — same module bits, different param set.)

### Goal — single bit of information

Does dropping `test300_oob_pending` move the wedge back to the prior [t+90s, t+120s] bracket?

| Outcome | Interpretation | Next step |
|---|---|---|
| Wedge at [t+90s, t+120s] | **test300 enablement IS shifting the bracket forward.** OOB Router BAR0 read at post-set_active has a delayed effect on bus state. Strong inference. | Decide whether to revisit the OOB Router probe with a different timing strategy (e.g., one-shot sample at post-set_active only, no sample 2; or skip OOB Router entirely and pivot) |
| Wedge at t+45s..t+60s | **AMBIGUOUS.** Either (a) test300 was a red herring and substrate variance widened independently, or (b) the dropped `test284_premask_enable` (also dropped in T300/T301 vs T298/T299) is what shifts the bracket. T302b' (drop test300, RE-ADD test284) bisects | Fire T302b' next |
| Substrate-noise null upstream of t+45s | falls into the existing row 85 noise belt; T302b not the culprit. Cold cycle and re-fire | substrate variance |
| New wedge mode | handle on its own merits | TBD |

**Prediction (Claude before fire):** ~60-65% wedge at [t+90s, t+120s]; ~30-35% stays at t+45s..t+60s; ~5% other. Confidence not high → test is well-targeted.

### Diff vs T301 fire (2026-04-27 19:24 BST, sample 2 wedge at t+60s)

- IDENTICAL module (no rebuild)
- IDENTICAL kernel cmdline (default ASPM)
- DROPPED: `bcm4360_test300_oob_pending=1` (the param under test) and `bcm4360_test269_early_exit=1` (early exit at t+60s would skip the [t+90s, t+120s] bracket and defeat the test)
- CHANGED: `sleep 75` → `sleep 150` (matches T298/T299 baseline so rmmod attempt would happen after t+90s probes if they survive)

### Substrate state at writeup (19:43 BST)

- Boot 0 started 19:27:36 BST; uptime 15 min — **at late edge of row 83's 10-15 min middle window**
- 03:00.0: `ASPM L0s L1 Enabled` (default), MAbort-, CommClk+, x1 @2.5GT/s
- 02:00.0: `ASPM L1 Enabled` (default), MAbort-, CommClk+, x1 @5GT/s

### Pre-fire checklist (CLAUDE.md)

1. ✓ NO REBUILD — same module bits that fired T301
2. ✓ Hypothesis matrix above
3. ✓ PCIe state checked (clean, just done)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → Fire immediately (uptime already 15 min — at late edge of clean window)
7. ✓ Advisor consulted (post-T301; recommended T302b over T302a)

### Fire command (run immediately after commit/push/sync)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test298_isr_walk=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.302b.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.302b.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.302b.journalctl.txt
```

If wedged before journalctl: on next boot, `sudo journalctl -k -b -1 > phase5/logs/test.302b.journalctl.txt`.

### Risk and recovery

- Identical risk profile to T298/T299 (which both wedged at [t+90s, t+120s] but auto-recovered or required SMC). Worst case: silent kernel wedge → auto-recovery or user SMC reset.
- No new probe code; risk is substrate + the known wedge bracket.

## POST-TEST.302b (2026-04-27 19:51 BST — T302b FIRED. All probe stages clean through t+90s SUMMARY. Wedged at end-of-t+90s probe — exact T270-BASELINE [t+90s, t+120s] pattern. Auto-recovery, no SMC reset needed.)

### Headline result

- **Wedge bracket moved BACK to [t+90s, t+120s] when `test300_oob_pending` was dropped.** Outcome row 1 of PRE-TEST.302b matrix. **Strong causal inference: test300 enablement IS shifting the wedge bracket forward** (n=6 without test300 vs n=2 with test300, distinct loci).
- **`test284_premask` confound from row 104 ELIMINATED.** T302b also dropped `test284_premask_enable` (vs T298/T299). Wedge stayed at [t+90s, t+120s] regardless. test284 is NOT the wedge-shifting factor.
- ISR-list at post-set_active: count=1 (only RTE-CC mask=0x1) → count=2 at post-T276-poll (pciedngl_isr mask=0x8 added). Same pattern as T300/T301 (n=3 now without test284_premask). All later stages frozen at count=2, `pending=0x0`, `events_p=0x18109000`, `sched_cc=0x1`.
- No advance on the wake-trigger source question — test300 dropped means no OOB Router pending read at all.

### ASPM state at fire time

03:00.0 `ASPM L0s L1 Enabled`, 02:00.0 `ASPM L1 Enabled` (defaults; T299 falsified ASPM-as-cause, no flip). Same as T300/T301.

### Timeline (boot -1, `phase5/logs/test.302b.journalctl.txt`, 1482 lines)

- `19:27:36` boot start
- `19:45:29` insmod (uptime ~17 min — late edge of row 83 clean window; planned for ~10-15 min, slipped slightly)
- `19:45:34` SBR via bridge 0000:00:1c.2
- `19:46:15` brcmf_chip_set_active returned TRUE
- `19:46:15` post-set_active: **T298 count=1** (RTE-CC ISR only, mask=0x1) — same as T300/T301
- `19:46:15` post-T276-poll → count=2 (pciedngl_isr added, mask=0x8). Steady state from here.
- `19:46:15→22` post-T278-initial-dump, t+500ms, t+5s, t+30s — all clean, count=2 stable, `pending=0x0`
- `19:46:27` t+35000ms dwell
- `19:46:37` t+45000ms dwell (cleared T300's wedge point — second clearing after T301)
- `19:46:53` t+60000ms dwell (cleared T301's wedge point — first clearing of t+60s with no test300 access)
- `19:47:23` **t+90000ms dwell + t+90s test.278/287/287c/298 readout** — count=2 stable, `pending=0x0`
- `19:47:23` **last log line: `test.298: stage t+90s SUMMARY count=2 sched_cc=0x00000001 events_p=0x18109000 pending=0x00000000`**
- `19:47:23` boot -1 ends (silent kernel death same second as t+90s SUMMARY)
- `19:49:32` boot 0 starts (auto-recovery, no SMC reset)

### Hypothesis matrix vs result

| Outcome (from PRE-TEST.302b) | Observed? |
|---|---|
| Wedge at [t+90s, t+120s] (test300 IS shifting bracket) | **YES** — t+90s SUMMARY printed cleanly, boot ended same second |
| Wedge at t+45s..t+60s (ambiguous: substrate variance OR test284 confound) | NO |
| Substrate-noise null upstream of t+45s | NO — all probe stages cleared |
| New wedge mode | NO |

Outcome row 1 confirmed. Strong inference per the matrix's "Next step" column: **decide whether to revisit the OOB Router probe with a different timing strategy (e.g., one-shot sample at post-set_active only, no sample 2; or skip OOB Router entirely and pivot).**

### What this changes

- **KEY_FINDINGS row 104 (wedge bracket robustness):** add T302b to reproduction list (now n=6 without test300: T270-BASELINE / T276 / T287c / T298 / T299 / T302b). **Eliminate the test284_premask confound:** T302b dropped test284 yet wedge stayed at [t+90s, t+120s] — test284 is NOT the wedge-shifting factor. test300 is.
- **KEY_FINDINGS row 162 (OOB Router):** unchanged from T301 readings (no new sample 1 in T302b). The "test300 enablement causally shifts the wedge bracket" sub-question is now **CONFIRMED** at n=2 wedged with test300 vs n=6 without. Update LIVE → CONFIRMED on that sub-question.
- **KEY_FINDINGS row 85 sub-entry (per-agent BAR0 noise belt):** unchanged. T302b had no BAR0 OOB Router access.
- **NEW (n=3): `count=1` at post-set_active correlates with `test284_premask=0`.** T298/T299 (test284=1) saw count=2; T300/T301/T302b (test284=0) saw count=1 → count=2 transition at post-T276-poll. Likely test284 reorders pciedngl_isr registration earlier. Not load-bearing for wake question.
- **What is NOT changed:** wake-trigger source for OOB bit 0 (RTE-CC) and bit 3 (pciedngl_isr) STILL LIVE. T302b had no probe of OOB Router pending — sample 2 of T300/T301/T302b campaign has never successfully read.

### Files

- `phase5/logs/test.302b.journalctl.txt` (boot -1, 1482 lines, ends at t+90s SUMMARY)
- `phase5/logs/test.302b.run.txt` (0 bytes — silent kernel death)

### Substrate state at writeup

- Boot 0 started 19:49:32 BST, uptime ~2 min
- 03:00.0: `ASPM L0s L1 Enabled` (default), MAbort-, CommClk+
- No SMC reset performed (auto-recovery sufficient)

### Next direction (held — needs advisor consult)

Test300 enablement is causally shifting the wedge bracket. Three candidate next probes — all need an advisor pass before fire:

1. **T303a — single-shot test300 (sample 1 only, NO sample 2).** Code edit: drop the t+60s sample 2 hook entirely; keep only the post-set_active sample 1. Predicts: wedge moves back to [t+90s, t+120s] (n=3+ on causal: BAR0 OOB Router read AT post-set_active alone is enough to perturb later bus state) OR wedge moves to a NEW point. Cleanest causal isolation of "what about test300 shifts the bracket" — was it sample 1 alone, or was it the cumulative effect of sample 1 + sample 2's pre-wedge access pattern.
2. **T303b — move sample 2 to t+30s.** Code edit: change the sample 2 hook from t+60s to t+30s. Sample 2 has never been read; getting one reading at any non-post-set_active timing would advance the wake-trigger question. Risk: t+30s is BEFORE the [t+90s, t+120s] bracket but inside the t+45s/t+60s shift seen with test300 — sample 2 might still wedge. n=1 likely outcome.
3. **A2 — BAR2 sched_ctx mapping (no BAR0).** Read sched+0xD0 (slot counter), sched+0xD4-table (per-slot core-id), the +0x300-0x350 gap. Cheap, low-risk, no BAR0. Speculative yield (might find a TCM-resident OOB-bit→ISR dispatch table). Doesn't advance pending-register reading.

A2 is cheapest. T303a is the cleanest causal call. T303b is the highest information-yield IF it doesn't wedge. **2026-04-27 19:55 BST: user picked A2.**

## PRE-TEST.303 (drafted 2026-04-27 19:55 BST on user pick of A2. NEW probe `bcm4360_test303_sched_extras` reads previously-unprobed sched_ctx fields: +0xCC semantics (observed 0x1 stable, unknown), +0xD0 slot count, +0xD4..+0xF0 per-slot core-ID table (8 entries × 4 bytes), +0x300..+0x354 gap (22 dwords, no static writers found in t288 enumerator scan). All BAR2-only — honours row 85 stopping rule. Requires REBUILD.)

### Goal — single bit of information

Cross-validate firmware's runtime view of the BCMA backplane against host-side `brcmf_pcie_select_core` enumeration (T218: 6 cores `0x800/0x812/0x83e/0x83c/0x81a/0x135`). Specifically: does the per-slot core-ID table at sched+0xD4 include the OOB Router (0x367) that host enumeration MISSED but EROM has at 0x18109000? If yes, this is primary-source confirmation that fw enumeration covers a superset of host enumeration, and sched+0xD0 will read 7 (or more). If no, the OOB Router is accessed via a separate pointer (sched+0x358 already shown) outside the enumerated slot table.

Secondary: characterize the +0x300..+0x354 gap — t300_static_prep §65 calls it "uncharacterized — no static writers found". Runtime read tells us if it's zero-init'd (pure padding), populated by something static analysis missed, or used as a runtime workspace.

### Hypothesis matrix

| Outcome | Interpretation | Updates |
|---|---|---|
| sched+0xD0 = 7+ AND slot table contains 0x367 | **fw enumeration is a superset of host** — covers OOB Router. Cross-validates sched+0x358=0x18109000 as part of the slot model | KEY_FINDINGS row 162 strengthens with primary-source slot enumeration |
| sched+0xD0 = 6 AND slot table = host enum | fw and host enumeration agree on 6 cores; OOB Router is accessed via a separate fw-internal pointer outside the slot model. The sched+0x358 path is special-case | row 162: OOB Router accessed via separate pointer, not in slot table |
| sched+0xD0 differs from any prediction (e.g. 8, 9) | unexpected — check what's in the slot table to identify extras | depends on data |
| Gap +0x300..+0x354 mostly zero | likely structure padding; static analysis was right | t300_static_prep §65 confirmed |
| Gap +0x300..+0x354 has populated values | runtime workspace or static analysis missed writers | new direction — investigate via trace |
| sched+0xCC NOT 0x1 stable | T287/T298's "0x1 stable" framing was stage-incomplete | row 163 update |
| Probe wedges (substrate-noise belt extends to BAR2 range we haven't read before) | extremely unlikely per row 85 (TCM reads at 0x62A98+offsets up to +0x354 = TCM[0x62DEC] — within ramsize 0xA0000) | row 85 widens unexpectedly |

### Probe code (new test303 macro, modeled after T287c)

```c
/* BCM4360 test.303: BAR2-only sched_ctx field-map extension.
 * Reads previously-unprobed fields per t300_static_prep §60-67:
 *   +0xCC = semantics LIVE (observed 0x1 stable in T287/T298)
 *   +0xD0 = slot count (per row 137 / t288_pcie2_reg_map fn@0x67194)
 *   +0xD4..+0xF0 = per-slot core-ID table (8 entries, slot*4 indexed)
 *   +0x300..+0x354 = uncharacterized gap (22 dwords, no static writers)
 * BAR2-only — zero BAR0/select_core/wrapper touches.
 * Requires test287_sched_ctx_read=1 for context (same hook sites).
 * READ-ONLY w.r.t. all MMIO. */
static int bcm4360_test303_sched_extras;
module_param(bcm4360_test303_sched_extras, int, 0644);
MODULE_PARM_DESC(bcm4360_test303_sched_extras, "...");

#define BCM4360_T303_READ_EXTRAS(tag) do { \
    if (bcm4360_test303_sched_extras) { \
        /* +0xCC + count + 8-slot core-ID table */ \
        u32 _cc = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0CC); \
        u32 _d0 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0D0); \
        u32 _d4 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0D4); \
        u32 _d8 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0D8); \
        u32 _dc = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0DC); \
        u32 _e0 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0E0); \
        u32 _e4 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0E4); \
        u32 _e8 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0E8); \
        u32 _ec = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0EC); \
        u32 _f0 = brcmf_pcie_read_ram32(devinfo, BCM4360_T287_SCHED_CTX_BASE + 0x0F0); \
        pr_emerg("BCM4360 test.303: %s sched[+0xCC]=0x%08x +0xD0(count)=0x%08x slots[+0xD4..+0xF0]=%08x %08x %08x %08x %08x %08x %08x %08x\n", \
            tag, _cc, _d0, _d4, _d8, _dc, _e0, _e4, _e8, _ec, _f0); \
        /* gap +0x300..+0x354 in 8-dword groups */ \
        /* ... 3 lines of 8 dwords + 1 line of 6 dwords = 22 dwords total ... */ \
    } \
} while (0)
```

Hook sites: same as T287/T287c (lines 1410, 4554, 4558, 4569, 4618, 4703 in pcie.c). Same risk profile.

### Substrate prerequisites

- Boot 0 started 19:49:32 BST; uptime now ~5-6 min at writeup
- Plan to fire at uptime ~10-15 min (row 83 middle of clean window) → fire ~19:59-20:04 BST
- 03:00.0/02:00.0 lspci clean, default ASPM
- modinfo verify that `bcm4360_test303_sched_extras` param appears post-build

### Pre-fire checklist (CLAUDE.md)

1. → REBUILD required (new probe code + module param) — `make -C phase5/work`
2. ✓ Hypothesis matrix above
3. → PCIe state check after rebuild
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → Wait for uptime ~10-15 min then fire
7. ✓ Advisor consulted (recommended A2 as conservative substrate-saving option; user picked it)

### Module params (fire command)

- ENABLE: T236, T238, T276, T277, T278, T287, T287c, T298, **T303 (new)**
- SAME as T302b plus T303 — DROP test300/test269/test284 (test300 is causal shifter, drop)

### Fire command (run AFTER rebuild + lspci verify + uptime in window)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test298_isr_walk=1 \
    bcm4360_test303_sched_extras=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.303.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.303.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.303.journalctl.txt
```

### Risk and recovery

- All BAR2 reads, no BAR0 — safe per row 85 (noise belt is BAR0-specific to chipcommon-wrap/PCIE2-wrap)
- Wedge bracket [t+90s, t+120s] still expected (no test300 means baseline pattern reproduces). Auto-recovery should suffice.
- Worst case: silent kernel wedge in normal bracket; user SMC reset if no auto-recovery.

## POST-TEST.303 (written 2026-04-27 20:18 BST)

### Fire timing & substrate

- insmod: 20:10:56 BST (boot -1 uptime ~21 min — late but within row 83 clean window)
- ASPM-disable confirmation print: 20:11:00 BST (normal ~4s post-insmod)
- ~2 min fw boot/wait gap (printk timing in journalctl unreliable from here on)
- All probe stages CLEAN through `t+90s SUMMARY` (last lines flushed at 20:13:11)
- Boot -1 ended 20:13:11 — silent kernel death right after t+90s SUMMARY
- Auto-recovery, NO SMC reset — boot 0 started 20:14:43

Wedge in expected [t+90s, t+120s] bracket (KEY_FINDINGS row 104). Now n=7 without test300 enabled (T270-BASELINE/T276/T287c/T298/T299/T302b/T303).

### Primary-source data

All values stable across all 6 stages (post-set_active, post-T276-poll, post-T278-initial-dump, t+500ms, t+5s, t+30s, t+90s) UNLESS noted:

| Field | Value | Notes |
|---|---|---|
| `sched+0xCC` | **0x0 at post-set_active**, **0x1 from post-T276-poll onwards** | NEW signal. T287/T298 framed "0x1 stable" but never sampled at post-set_active — prior framing stage-incomplete. Transition window = ~2s T276 poll. Semantics still unknown but value is now known to be 0-init plus a write during the T276 poll path. |
| `sched+0xD0` (count) | `0x5` | Stable |
| `slots[+0xD4]` | `0x800` | CHIPCOMMON (host slot 1) |
| `slots[+0xD8]` | `0x812` | host slot 2 |
| `slots[+0xDC]` | `0x83e` | ARM-CR4 (host slot 3) |
| `slots[+0xE0]` | `0x83c` | PCIE2 (host slot 4) |
| `slots[+0xE4]` | `0x81a` | host slot 5 |
| `slots[+0xE8]` | `0x135` | I/O hub (host slot 6, base=0) |
| `slots[+0xEC]` | `0x0` | empty |
| `slots[+0xF0]` | `0x0` | empty |
| `gap +0x300..+0x314` | all `0x00000000` | (6 dwords) |
| `gap +0x318` | `0x2b084411` | populated |
| `gap +0x31c` | `0x2a004211` | populated |
| `gap +0x320` | `0x02084411` | populated |
| `gap +0x324` | `0x01084411` | populated |
| `gap +0x328` | `0x11004211` | populated |
| `gap +0x32c` | `0x00080201` | populated |
| `gap +0x330..+0x354` | all `0x00000000` | (10 dwords) |

### Findings

1. **Slot table = host enumeration EXACTLY** (n=1 fire, but stable across 6 stages). 6 slot entries with the BCMA core-IDs in host-enum order, slots 6-7 zero. Primary-source confirmation that fw scheduler maintains a slot view that matches what host's `brcmf_pcie_select_core` finds via EROM walk.

2. **OOB Router (0x367) is NOT in the slot table.** Confirms KEY_FINDINGS row 162's framing: fw accesses OOB Router via the separate `sched+0x358 = 0x18109000` pointer, OUTSIDE the indexed slot model. The slot table and the OOB Router pointer are two distinct fw-internal mechanisms.

3. **count=5 vs 6 populated slot IDs — semantics open between (a) last-allocated index and (b) "real" cores excluding I/O hub.** (a) is the boring/likely answer. Either way the load-bearing claim — slot table = host enum, OOB Router separate — is unchanged. Don't pick (b) just because it's tidier.

4. **`sched+0xCC` transitions during the T276 poll** (0x0 → 0x1). Worth row 163 update — T287/T298's "0x1 stable" framing was stage-incomplete (those probes never sampled at post-set_active). Semantics still unknown but the temporal profile is now characterized.

5. **`+0x300..+0x354` gap is NOT all zero** — t300_static_prep §65 ("no static writers found") prediction broken. 6 populated dwords at `+0x318..+0x32c`. Indices 6..11 of the gap, NOT 0..5 — so NOT trivially 1:1 with slots 0..5. Structure unclear; leave as primary-source bytes for now.

6. **n=7 reproduction of the [t+90s, t+120s] wedge bracket without test300** (row 104 update). T303 is the cleanest version yet — every probe stage flushed before the wedge, including all 4 readout lines per stage at t+5s/t+30s/t+90s.

### Wedge timing caveat (advisor catch)

All probe printks bunched at journalctl timestamps 20:13:10/11. Insmod print and ASPM-disable print landed normally. The bunching = printk buffer drained as the kernel dies. **Cannot extract precise stage timing from journalctl.** Wedge bracket inferred from script-level fact: insmod returned, `sleep 150` was wedged inside (run.txt is 0 bytes; rmmod never executed; boot ended ~135s after insmod = within [t+90s, t+150s]).

### What this resolves

- KEY_FINDINGS row 162 framing of "OOB Router accessed via separate pointer outside slot model" → CONFIRMED via primary-source slot enumeration.
- KEY_FINDINGS row 104's [t+90s, t+120s] bracket → reproduced, n=7.
- t300_static_prep §65 "gap is uncharacterized but probably zero-init" → partially falsified, 6 populated dwords found.

### What this does NOT advance

- Wake-trigger HW source (the OOB pending-events question). T303 was BAR2-only by design; sample 2 OOB Router pending read still never accomplished across T300/T301/T302b/T303.
- The +0x318..+0x32c populated dwords' meaning. Need disasm or runtime trace of writers to interpret.

### Next direction (sharpened 2026-04-27 20:25 BST after second advisor consult)

Decision splits into TWO independent questions:

**Q1 — Static work (no substrate cost, do regardless):** **DONE 2026-04-27 20:35 BST** (phase6/t303b_gap_writers.md, commit 49c3c35). Writer = fn@0x64590, called from si_doattach. Values are EROM core descriptor metadata (revisions + wrapper capability fields) cached at init, one per host-enumerated core. Wake-question impact: zero. Gap resolved; no follow-on direction from this surface. ~~A2-extension~~ closed.

**Q2 — Next fire (substrate-budget call):**

The reframe: sample 2 OOB Router pending read has now FAILED n=4 (T300 wedged before sample 2 at t+45s; T301 wedged AT sample 2's window-write at t+60s; T302b/T303 dropped test300). T303b's premise — "t+30s might succeed where t+60s didn't" — needs to confront the pattern that **test300 enablement shifts wedge forward proportional to access timing** (T300 t+45s, T301 t+60s). Under that model, sample 2 at t+30s probably wedges at ~t+30s. The passive-observation approach may simply be unreachable from the host side.

The deeper reframe: the wake question is **"what sets OOB bits 0/3?"** Sample 2 (passive) tells us "does pending transition naturally during idle" — informative only if yes (n=4 says probably never gets to read it). **B (active wake-event injection)** tests the wake path directly — primary-source evidence either way (does pciedngl_isr fire? does pending bit 3 set after host MSI/DMA?).

Three options:

1. **T303b — sample 2 OOB Router pending at t+30s.** Passive observation. Risk: probably wedges at t+30s. Upside: if it lands, first non-zero pending observation. n=4 prior failures argue against.

2. **B — host-side wake-event injection.** Active path. Choices: (i) MSI assert via test bit in PCIE2 config, (ii) DMA transfer over Phase 4B olmsg ring (already plumbed at shared_info; never triggered). Primary-source either way (wake fires, or it doesn't and we know what's missing). Most ambitious.

3. **Neither — exhaust static surface first.** A2-extension + any other static surfaces (e.g. EROM walk for the OOB Router register layout, disasm of sched+0xCC writer to learn what flips it 0→1 during T276 poll). Defer next fire until a sharper hypothesis emerges.

**Recommendation hierarchy** based on advisor framing:
- Always do A2-extension (Q1).
- For Q2: **option 3 (defer fire)** is the conservative call — n=4 suggests T303b unlikely to advance; B is high-stakes without clear hypothesis. Use static work to sharpen.
- If pressed to fire: **option 2 (B)** is more likely informative than option 1 (T303b), per the n=4 sample-2 evidence. T303b risks burning substrate for another null.

Awaiting user steer on Q2.

## PRE-TEST.304 (drafted 2026-04-27 21:05 BST after user approval — gate-1 empirical probe of OOB Router pending register write semantics. Single new test304 macro added; all other params unchanged from T303 baseline.)

### Goal — single bit of information

**Does writing 0xFFFFFFFF to 0x18109100 (OOB Router pending register) set the bits, or is the register W1C / read-only?** This resolves Gate 1 of the option-B fire-ability gate stack (phase6/t303e).

### Hypothesis matrix

| Outcome | Interpretation | Updates |
|---|---|---|
| post-write read = `0xFFFFFFFF` | **RW1S** — host CAN set OOB pending bits. Option B is fire-able conditional on remaining gates. | KEY_FINDINGS row 162 + new row on register semantics. Gate 1 → KNOWN-OPEN. |
| post-write read = `0x00000000` | **W1C or RO** — host CANNOT set bits via this register. Option B via OOB Router pending is dead. Need different wake-trigger surface. | KEY_FINDINGS row 162: gate 1 → KNOWN-CLOSED. Switch direction (PMU GPIO, fw entry to unblock MAILBOXMASK, or other). |
| post-write read = partial set (e.g. `0x00000009` or `0xFFF80000`) | Sparse RW1S — only some bits implemented; can set the implemented ones | New finding: which bits are implemented. Compare to T298-allocated bits 0/3. |
| Any non-zero readout AND console wr_idx advances OR fw_init_done set OR mbxint changes | **BONUS:** dispatch chain fired downstream — partial Gate 3 evidence (ARM IRQ enable was open, exception was taken) | Gate 3 → KNOWN-OPEN by inference. Major progress. |
| Probe wedges before SUMMARY (anchor lines flushed, SUMMARY missing) | wedge during the write step — could be substrate noise OR write-induced fw response that crashes host (e.g. fw asserts unexpected IRQ that wedges PCIe) | Pre-fire interpretation: substrate noise more likely; if wedge AT anchor-5 specifically (after the write), interpret as write-induced |
| Probe completes but T303 fields show NEW values vs T303 baseline | Side effect of pending-bit write affecting fw scheduler state | Captured by T303/T298 instrumentation already in place |

### Diff vs T303 fire (2026-04-27 20:10 BST)

- IDENTICAL module params plus `bcm4360_test304_oob_write_probe=1`
- IDENTICAL fire script
- REBUILD with new test304 macro
- Same hook site as T300 sample 1: post-set_active only (proven safe n=2)
- Test300 STAYS DISABLED (it shifts the wedge bracket; no need to mix probes)

### Pre-fire checklist (CLAUDE.md)

1. ✓ REBUILD done — `make` exited clean, modinfo verified `bcm4360_test304_oob_write_probe` param visible
2. ✓ Hypothesis matrix above
3. → PCIe state check before fire (lspci MAbort/CommClk)
4. → Plan committed and pushed BEFORE fire (this commit)
5. → FS sync after push
6. → Fire when substrate is in clean window (current uptime ~50 min — late side; consider cold cycle for fresher substrate, or fire now and accept higher null-fire risk)
7. ✓ Advisor consulted (twice — once on Q2 fire decision flow, once on gate-stack interpretation; recommendation = fire gate-1 empirical probe)

### Module params (fire command)

- ENABLE: T236, T238, T276, T277, T278, T287, T287c, T298, T303, **T304 (new)**
- DISABLED: test300 (causal wedge shifter), test269 (early exit), test284 (premask)
- Same baseline as T303 plus T304

### Fire command (run AFTER lspci verify + uptime in window)

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 \
    bcm4360_test276_shared_info=1 bcm4360_test277_console_decode=1 \
    bcm4360_test278_console_periodic=1 \
    bcm4360_test287_sched_ctx_read=1 \
    bcm4360_test287c_extended=1 \
    bcm4360_test298_isr_walk=1 \
    bcm4360_test303_sched_extras=1 \
    bcm4360_test304_oob_write_probe=1 \
    > /home/kimptoc/bcm4360-re/phase5/logs/test.304.run.txt 2>&1
sleep 150
sudo rmmod brcmfmac_wcc brcmfmac brcmutil 2>&1 | tee -a /home/kimptoc/bcm4360-re/phase5/logs/test.304.run.txt || true
sudo journalctl -k -b 0 > /home/kimptoc/bcm4360-re/phase5/logs/test.304.journalctl.txt
```

### Risk and recovery

- Single BAR0 write at post-set_active timing — same risk profile as T300 sample 1 (clean n=2). The added write step (vs T300's read-only) is the only delta; if BAR0 OOB Router writes have different reachability than reads, this is where we'd find out.
- If RW1S and dispatch fires: fw might do something unexpected (e.g. assert host IRQ via PCIE2 mailbox response, change shared_info state, write to TCM). T276/T278/T287/T287c/T298/T303 instrumentation will catch any visible state change.
- Wedge bracket [t+90s, t+120s] still expected as baseline. Auto-recovery should suffice.
- Worst case: silent kernel wedge in normal bracket; user SMC reset if no auto-recovery.

## POST-TEST.304 (written 2026-04-27 21:18 BST after machine auto-recovered from T304 fire)

### Fire timing & substrate

- insmod: ~21:11:00 BST (boot -1 started 21:06:15 → uptime ~5 min, fresh substrate within row 83 window)
- All probe stages flushed CLEAN through `t+90s SUMMARY` at 21:13:16
- Boot -1 ended 21:13:16 — silent kernel death right after t+90s SUMMARY
- **Auto-recovery, NO SMC reset needed** — boot 0 started 21:16:01
- Same [t+90s, t+120s] wedge bracket (KEY_FINDINGS row 104). Now n=8 without test300 (T270-BASELINE/T276/T287c/T298/T299/T302b/T303/T304).

### Primary-source T304 data (gate-1 verdict)

All 6 anchors plus SUMMARY logged successfully at post-set_active. No wedge during the T304 sequence itself.

| Anchor | Log line |
|---|---|
| 1 | `about to save BAR0_WINDOW` |
| 2 | `saved=0x18102000; about to set OOB Router window=0x18109000` |
| 3 | `window set; about to read pre-write +0x100` |
| 4 | `pre=0x00000000; about to write 0xffffffff` |
| 5 | `write done; about to read post-write +0x100` |
| 6 | `post=0x00000000; about to restore BAR0_WINDOW=0x18102000` |
| SUMMARY | `pre=0x00000000 wrote=0xffffffff post=0x00000000 verdict=W1C-or-RO(no-set)` |

Source: `phase5/logs/test.304.journalctl.txt`. Sample-1 BAR0 OOB Router accessibility now n=3 (T300, T301, T304 all clean at post-set_active). Sample-1 BAR0 OOB Router *write*-then-readback is also clean (no wedge during/after the write step) — first primary-source observation that BAR0 writes to OOB Router agent at post-set_active are tolerated.

### Gate-1 verdict — host CANNOT set bits via OOB Router +0x100

**Plain reading:** `pre=0x0`, `wrote=0xffffffff`, `post=0x0` → bits did not stick after the write. Either W1C (write-1-to-clear) or RO (host writes ignored).

**Tightened ruling-out (advisor catch).** The post-write read could in principle be 0x0 under RW1S if every set bit was W1C-cleared by an ARM ISR before the readback. **This is structurally impossible here:**

- The probe wrote `0xFFFFFFFF` — all 32 bits.
- Only **bit 0** (RTE chipcommon-class ISR) was registered at post-set_active timing per T298/T303 (`count=1 sched_cc=0x0` confirmed at this exact stage in T304's prior `298 SUMMARY`).
- Bits 1, 2, and 4–31 have **no ISR registered**, so even if RW1S + bit 0 fired + bit 0 W1C-cleared, bits 1/2/4–31 would have **no fast-clear path** and would remain SET on readback.
- Observed `post = 0x00000000` → all 32 bits cleared by the write itself → **incompatible with RW1S**.

Therefore: register at 0x18109100 is **W1C or RO** for host-side writes. RO and W1C are observationally indistinguishable in this experiment (both yield `post=0` from `pre=0`); the load-bearing claim — **host cannot set OOB pending bits via this register** — holds for both.

### What this resolves / kills / leaves open

- **Gate 1 (OOB Router +0x100 write semantics) → KNOWN-CLOSED for host-set.** First primary-source resolution from the gate stack mapped in `phase6/t303e_oob_gate_stack.md`.
- **Option B "host writes 0x18109100 to set OOB pending bits 0/3 and trigger fn@0x115c via OOB path" → DEAD.** The OOB Router pending register is not host-driveable.
- **Unaffected — every other wake-trigger surface remains LIVE:**
  - PCIE2 mailbox path with MAILBOXMASK still gating (KEY_FINDINGS row 96 / T279)
  - PMU / GPIO surfaces (never probed)
  - DMA-via-olmsg-ring (Phase 4B plumbing exists but never triggered; trip path requires understanding fw poller schedule)
  - Whatever HW path normally drives those OOB lines (probably internal core-side asserts: D11 MAC events, chipcommon-class events, etc — not host-reachable except via the agents themselves)
- **"Fw is in WFI waiting for HW IRQ" framing from T303d remains intact.** What's killed is one specific candidate path for synthetic wake injection from the host.

### Robustness datapoint — post-set_active substrate window

T304 added 1 BAR0 write + 2 BAR0 reads (vs T300's 0 writes + 1 read) at post-set_active and still flushed clean through the entire ladder to t+90s SUMMARY. The post-set_active window appears robust to additional BAR0 OOB Router transactions when sample 2 (the t+60s re-access from T301) is omitted. Reinforces row 162 framing that the noise belt is per-agent + timing-dependent, not per-region or per-transaction-count.

### Follow-up items (non-blocking on the verdict)

- Anchor-6 says "about to restore BAR0_WINDOW" but no "restore done" anchor was added to the macro. Module continued cleanly through T276 poll + T298 walks, so functionally the restore landed — but the macro has no positive confirmation print. If a future sample 2 design re-enters this window, add a restore-done anchor.
- Sample 2 (does pending naturally transition to non-zero in idle) is still unanswered across T300/T301/T302b/T303/T304. With Gate 1 closed, **passive observation of pending** is now the only useful read of this register from the host side. Whether that's worth pursuing depends on the next-direction call.

### Next direction (deferred — separate decision from this writeup)

Three live options after Gate 1 closure:

1. **Pursue different wake surface — PMU/GPIO probe.** Static work first (find PMU register layout + any host-reachable GPIO-driven IRQ slots), then a probe-design pass.
2. **Pursue DMA-via-olmsg trip path.** Requires understanding what fw poller (if any) services the olmsg ring. T303d said reads happen on-dispatch only, so this needs a different fw entry point analysis.
3. **Resume passive sample 2 attempt** with a single-shot re-read at variable timing. Lower priority given Gate 1 closure — even if pending transitions, host can't act on it.

User steer needed. Suggest static work (option 1's first phase, or a fresh look at fw entry points for option 2) before the next fire.

## Archived detail

Older PRE/POST test blocks have been migrated to
[RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).

Current policy for this file:

- keep the current-state block above
- keep only the latest 2-3 active PRE/POST test pairs when a hardware campaign
  is in flight
- move older chronology to history
- move broader synthesis into phase notes or `KEY_FINDINGS.md`

For the recent T290/T294/T296-era chronology, see:
- [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md)
- [phase5/notes/phase5_progress.md](phase5/notes/phase5_progress.md)
- [KEY_FINDINGS.md](KEY_FINDINGS.md)

The next action is to draft a follow-on probe (TCM-side `oobselouta30`
shadow OR a host-side wake-event injection) — see "Next discriminator" in
the current-state block above. Do NOT fire test.288a (BAR0 chipcommon-wrap
read) — KEY_FINDINGS row 85 stopping rule confirmed valid by T298.
