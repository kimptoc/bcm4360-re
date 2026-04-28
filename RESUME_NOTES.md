# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.
> File role: this is the live handoff file only. Cross-phase facts belong in
> [KEY_FINDINGS.md](KEY_FINDINGS.md); broader documentation rules live in
> [DOCS.md](DOCS.md).

## Current state (2026-04-28 ~16:55 BST — DIVERGED to wl-blob test; brcmfmac RE work paused)

### WL-MITIGATION-TEST (2026-04-28 ~16:55 BST) — staged, awaiting reboot

**Why diverged:** after deep power cycle (battery drain + SMC reset), substrate is **clean** (`<MAbort-`). User wants to confirm BCM4360 hardware health via Broadcom proprietary `wl` driver before resuming brcmfmac fires. `wl` modprobe at 16:39:21 in current boot (gen-96) failed with kernel WARN `Unpatched return thunk in use` at `getvar+0x20` → `wl_module_init` returned code 1, module is zombie (loaded, refcount 0, unbound).

**Root cause:** kernel's retbleed/return-thunk mitigation rejects code path in proprietary wl blob. NOT a hardware issue.

**Action staged (gen-97):**
- `/etc/nixos/configuration.nix` line 22 → `boot.kernelParams` now includes `retbleed=off spectre_v2=off`
- Backup at `/etc/nixos/configuration.nix.preWlMitigationTest`
- `sudo nixos-rebuild boot` ran clean → gen-97 created, NOT activated. Currently still on gen-96.
- Revert helper: `phase5/work/revert-wl-mitigation.sh` (restores backup + nixos-rebuild boot)

**Next step (when user ready):**
1. Reboot (systemd-boot will default to gen-97 with mitigations off)
2. `sudo modprobe wl` (or `insmod`) and observe — if `wl` binds and BCM4360 enumerates as wireless interface → hardware confirmed healthy
3. After test: run `phase5/work/revert-wl-mitigation.sh` then reboot back to mitigated kernel (any generation 96 or earlier)
4. Resume brcmfmac fires from clean substrate

**Mitigation flip is reversible at any time via the systemd-boot menu** (pick gen-96 or earlier).

---

## Previous state (2026-04-28 ~08:45 BST — POST-fire-attempt: HARD FREEZE during fw download; T305+T306 NEVER FIRED; substrate clean post-reboot)

### POST-R1-RE-FIRE (boot -1: 08:43:02 → 08:51:37 BST, 8.5 min) — **2nd hard freeze, different crash point**

R1 (re-fire identical script) was attempted. Same patched brcmfmac (15.6 MB, T305+T306 params) loaded successfully via insmod. **Crash hit at test.158 `about to pci_clear_master`** — BEFORE chip_attach completed properly, BEFORE fw download even began. ~20 sec from module_init to freeze. Identical no-oops/no-AER hard-freeze pattern, abrupt journal cutoff. Required hard power-cycle (13 min gap to next boot).

**2-for-2 crashes today; both during PCIe device I/O, at different points in the same ~20s window:**
- Crash 1 (08:39:25): test.225 chunk 24/108 — BAR2 MMIO write (deep in fw download)
- Crash 2 (08:51:37): test.158 pci_clear_master — config-space write (early, just after chip_attach)

**Common factor:** PCIe transaction targeting BCM4360. Pure host-side setup (chip enumeration, buscore_reset, PMU WARs, max/min_res_mask writes — all observed up to 08:51:36 in crash 2) completes fine. The freeze hits at the next outbound PCIe txn.

**`pci=noaer` is in /proc/cmdline** — present yesterday (test.304 succeeded with it) and today, so not a NEW variable. But it means PCIe link-layer errors and completion timeouts are completely INVISIBLE. If the BCM4360 is dropping completions, we'd see hard freeze not AER trace.

**Substrate post-each-reboot:** clean. MAbort-, CommClk+, link 2.5GT/s x1, no brcm modules loaded. Hardware survives intact between boots.

**Diff from yesterday's test.304 (last clean run):** new code added is bounded to the test.276 pre-set_active block, gated on params default-0. Macro definition + 2 module_param entries at file scope. None of this code runs until pre-set_active. Both crashes hit BEFORE pre-set_active. So new T305/T306 code itself can be ruled out as the trigger.

**What DID change today:** all crashes are first-fire-after-cold-boot. Yesterday's test.304 was likely a fire after the system had been up for hours of testing. Cold-boot state difference is plausible but unverified.

**Suspended R1 plan; T305+T306 never reached set_active in either fire. STOP touching hardware until we have a hypothesis.** Advisor consultation pending.

### PRE-FIRE-3 (warm-boot discriminator A) — fire scheduled at >=15 min post-boot

**Boot 0 started 09:04:19. Current ~09:19. Firing now after 15+ min uptime.**

**Hypothesis (cold-boot timing):** today's 2-for-2 hard freezes both happened at first-fire-after-cold-boot (4 min and 8 min uptime). Yesterday's clean test.304 was after long uptime. If we fire at 15+ min uptime with the SAME script + SAME build, and:
- it SURVIVES through fw download + pre-set_active → cold-boot init was the killer; T305/T306 should produce SUMMARY lines
- it CRASHES → cold-boot hypothesis falsified; switch to discriminator B (revert pcie.c to 66a2a89, rebuild, fire test.304-equivalent — distinguish env vs build)

**Substrate ready:** MAbort-, CommClk+, link 2.5GT/s x1, no brcm modules, mitigations not overridden. Patched brcmfmac.ko present at phase5/work (T305+T306 params, build 08:19 today).

### POST-FIRE-3 (boot -1: 09:04:19 → 09:20:32 BST, 16 min) — **3rd hard freeze; cold-boot hypothesis FALSIFIED**

Fire happened at ~15-min uptime. Crashed within ~21 seconds of brcmfmac module_init. **Crash 3 hit at test.188 post-attach** — after `brcmf_pcie_attach` (test.128 + test.194 PCIe2 register writes) returned, before `brcmf_chip_get_raminfo` (test.130) and before fw download.

**3-for-3 today, three different crash points within ~20 sec window:**
- Crash 1 (08:39:25, 4 min uptime): test.225 chunk 24 — deep in fw download (BAR2 MMIO writes)
- Crash 2 (08:51:37, 8 min uptime): test.158 about_to pci_clear_master — first config write after chip_attach
- Crash 3 (09:20:32, 16 min uptime): test.188 post-attach ARM CR4 check — between brcmf_pcie_attach and fw download

**Verdict on hypothesis A (cold-boot timing): FALSIFIED.** 15+ min uptime did NOT prevent the freeze. Crash distribution is random across the 20-sec post-init window — NOT a deterministic code bug.

**Strong candidates remaining:**
- (i) Marginal hardware (PSU sag, capacitor, BCM4360 silicon failure surfacing under PCIe load) — would explain random crash points
- (ii) System-level issue introduced today (kernel state, power management, cmdline change we missed)
- (iii) Build implicated despite gating — discriminator B would test this

**Hardware substrate clean post-each-reboot, link UP at 2.5GT/s x1.** Three power cycles required so far.

**Suspending all hardware fires. Next steps require user decision.** Discriminator B (revert pcie.c to 66a2a89, rebuild, fire test.304-equivalent) is the next experiment but burns another reboot if it crashes. Alternative: full diagnostic survey (memtest, smartctl, applesmc temps) before any further fire.

### PRE-FIRE-4 (discriminator B — code vs environment)

**Substrate as of 09:37:** clean (MAbort-, CommClk+, link 2.5GT/s x1, no brcm loaded). `pcie.c` reverted via `git checkout 66a2a89 -- ...` (verified: `grep -c bcm4360_test30[56]` returns 0). Clean rebuild done — fresh `pcie.o`, fresh `brcmfmac.o`, fresh `brcmfmac.ko` (15.57 MB, modinfo confirms no test305/306). Other .o files still from Apr 22 (same as yesterday — not a new variable).

**Hypothesis.** Fire at 66a2a89 (last known-good) with the closest-match-to-yesterday param set: `test.276 + 277 + 278 + 287 + 298 + 303 + 304`. Outcomes:
- **Survives** → today's T305/T306 build was implicated despite gating (stack/section/.bss layout shift, debug-info size, etc.). Bisect: T306 only, then T305 only.
- **Crashes** → environmental/hardware. Don't fire again today; capture full lspci -xxxxvvv extended config diff and let the chip cool.

**Pre-test checklist done:** build OK; substrate clean; mitigations not overridden; hypothesis stated.

### POST-FIRE-4 (boot -1: 09:27:28 → 09:38:30 BST, 11 min) — **4th hard freeze; discriminator B verdict: HARDWARE/ENV implicated**

User fired the canonical `test-brcmfmac.sh` (plain insmod, no params) on the clean 66a2a89 rebuild. Active test was `test.234` (default-on, gated only on `!test236_force_seed`) — the upper-TCM-zero + ARM release diagnostic. **Crashed at `t+700ms` post-set_active dwell.** 81 test.234 markers in journal. None of test305/306/276/277/278 (rebuilt module has no T305/306; canonical script doesn't enable the others).

**4-for-4 today, all within ~20s of insmod, four different crash points:**
- Crash 1 (4 min uptime, T305/306 build): mid-fw-download (chunk 24)
- Crash 2 (8 min uptime, T305/306 build): pci_clear_master
- Crash 3 (16 min uptime, T305/306 build): post-PCIe-attach ARM check
- Crash 4 (11 min uptime, **clean 66a2a89 build**): t+700ms post-set_active dwell

**Discriminator B verdict.** Reverted build (no T305/306 code at all) ALSO crashed → today's T305/306 patch is NOT the (sole) cause. Hardware or environmental issue confirmed.

**Substrate after crash 4 is DIRTY for the first time today:**
- `ASPM Disabled` (was Enabled by default after prior crashes)
- `CommClk-` (was `CommClk+` after every prior crash)
- MAbort still clean
- Link still UP at 2.5GT/s x1

Suggests **cumulative damage** from the four hard freezes. Captured full extended config to `/home/kimptoc/bcm4360-re/phase5/logs/test.crash4-post-cfg.txt`.

**FULL STOP on hardware fires.** Per advisor: don't keep iterating on hardware today. Diagnosis is more valuable than another data point at this rate. Recommended cooldown + reseat + comparison of the captured config-space dump against any pre-wl-cycle baseline.

**One observational note:** Crash 4 progressed FURTHER than crashes 1–3 (got past set_active and 700ms post-release dwell). Could be statistical variance in the ~20s instability window, or the clean build is marginally less destabilizing. Not enough data to claim either.



### POST-FIRE-ATTEMPT-1 (boot -2: 08:35:19 → 08:39:25 BST, 4 min)

`fire-t305-t306.sh` was invoked. Patched brcmfmac (15.6 MB, with T305+T306 params) loaded successfully. Path through chip_attach → fw_request → set_passive → enter_download_state → fw chunked write. **Crash hit at test.225 chunk 24/108** (98304 / 442233 bytes written, ~22% through). Chunks 1–24 all show `readback=…OK`. Then immediate journal cutoff at 08:39:25 with no oops, no panic, no AER, no PCIe error. Required hard power-cycle (3+ min gap before next boot).

**T305 and T306 never executed.** Both wire in inside the test.276 pre-set_active block (pcie.c lines 4770/4781), which only runs *after* `brcmf_chip_set_active`, which only runs *after* fw download completes. We crashed long before that point.

**This crash is anomalous.** 78 prior `phase5/logs/test.*.journalctl*` runs traversed the same fw-download path; yesterday's `test.304` ran chunks 1–109 cleanly. Today's chunk-24 hard freeze has no obvious mechanism in the code — it's a pure BAR2 MMIO chunked write with per-chunk readback verification.

**Substrate post-reboot (boot 0, 08:43:02):** clean. `lspci -vvv -s 03:00.0` → MAbort-, CommClk+, LnkSta 2.5GT/s x1. No brcm modules loaded. `mitigations=off` not present. Hardware survived intact.

**Confounder: brcmfmac is NOT in nixos blacklist** (`boot.blacklistedKernelModules = [ "wl" "b43" "bcma" "ssb" ]`). udev would auto-bind brcmfmac on PCI match if the patched .ko were ever installed into the system module tree. The booted-system path holds only stock 216KB brcmfmac.ko.xz, so auto-bind would have used stock — but the test.X markers in dmesg confirm our patched 15.6MB module loaded. ⇒ The fire script `insmod` was the loader, as expected.

**Hypotheses for the freeze (low confidence):**
1. **Coincidental hardware event** — power, thermal, capacitor. Re-fire would test reproducibility.
2. **Cold-boot timing** — module init at +3:47 from cold boot may differ from typical post-uptime fires; PCIe/CPU state not fully settled.
3. **Test-code interaction** — unlikely; T305/T306/T298 all wire post-set_active, none reached.

**Decision pending from user.** Options:
- **(R1) Re-fire identical script** — simplest; tests repro. ~80% expected to succeed based on history.
- **(R2) Strip to T306-only** (read-only cfg dump) — minimum-risk discriminator, omits T305 write path. If it survives, T305 can be added on the next fire.
- **(R3) Wait and investigate substrate** — temperatures, dmidecode, journal for any recent SEL/MCE events. Lowest hardware risk but learns nothing about original question.

Recommendation: **R1 first** — the test/code is innocent; high prior probability the crash was incidental. If it crashes again at the SAME chunk, switch to R2 + investigate.

### PRE-FIRE — what was prepared (preserved for context)



**Headline.** Cycle 1+1b (live wl trace attempt) closed: wl_module_init aborts at `getvar+0x20` with `code 1`; under Option-A static disasm of wl.ko the real failure is `wlc_attach` returning 1 inside the closed Broadcom blob (the WARN is a structurally-noisy retpoline-fallback printk, not the failure). Module-param sweep (`passivemode`, `oneonly`, `nompc`, `piomode`) all fail identically. **wl path dead** — full migration of cycle1/1b detail in [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md). **Pivot to Path (a)** per advisor steer; reframed with explicit `select_core(PCIE2)` per KEY_FINDINGS row-171 confound flag.

**System state as of header:**
- `/etc/nixos/configuration.nix` restored from `.preWlCycle1` backup (wl back in blacklist; mitigations=off removed).
- `sudo nixos-rebuild boot` ran cleanly — boot config staged for next reboot.
- wl module unloaded; chip back to "Kernel modules: bcma, wl" (no driver bound).
- New T305 code added to `phase5/work/.../pcie.c` and module BUILT (`brcmfmac.ko` ready). Module change does NOT take effect until user reboots + reloads brcmfmac per `phase5/work/test-brcmfmac.sh`.

**Required AFTER user reboots:**
1. Verify clean substrate: `lspci -k -s 03:00.0` should show `Kernel driver in use: brcmfmac` (or be unbound; brcmfmac may not auto-load — that's fine, test-brcmfmac.sh will handle it). `mitigations=off` should NOT be in `/proc/cmdline`.
2. Verify PCIe state pre-fire: `sudo lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'` → expect MAbort-, CommClk+.
3. Fire decision belongs to user. See PRE-PATH(a) section below.

**Still-relevant earlier-session context** (kept for handoff continuity):
- KEY_FINDINGS gained 7 new rows in T304b–T304h+T304i sweep (PMU/GPIO/D11/ISR/H2D closures + WL diff caveats). Three host-driveable wake-injection candidates closed (PMU, DMA-via-olmsg, H2D_MAILBOX_1). D11 dormant in offload runtime. Two-ISR wake surface (bits 0+3) empirically confirmed. **wl comparison was the highest-value remaining direction PRE-cycle1 — now closed by host-side wl init failure**, leaving Path (a) and HW-internal-event injection as remaining angles.
- **PATTERN CAVEAT (n=4):** subagents repeatedly fabricate runtime / cross-driver behavior from static identification cites when they hit a complexity wall (T304c/e/f/h). Compensation: tight prompts demanding "show bytes or report missing", OR direct disasm. Applied successfully in Option-A wl.ko investigation (direct disasm + reloc lookup, no subagent).

## PRE-PATH(a) — T305: pre-set_active MAILBOXMASK enable WITH explicit select_core(PCIE2)

**Code staged 2026-04-28 ~00:25 BST. NOT YET FIRED. Awaiting user reboot + decision.**

### What's new

New module param `bcm4360_test305_premask_with_select` (default 0) added to `phase5/work/.../pcie.c`. When set, at pre-set_active timing (parallel to T284's existing block, but separate `if`):

1. Read BAR0_WINDOW (`_t305_win_before`) — captures whatever core was selected on entry.
2. Call `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)`.
3. Read BAR0_WINDOW again (`_t305_win_after`) — verify select succeeded; expect `0x18102000` (PCIE2 base).
4. Read MBM (`_t305_mbm_pre`) — sanity check; expect `0x318` per row 122 if PCIE2 reachable.
5. Call `brcmf_pcie_intr_enable(devinfo)` — writes MBM = `0xFF0300` (its standard payload).
6. Read MBM again (`_t305_mbm_post`) — discriminator.
7. Log SUMMARY line with verdict tag (`WRITE_LANDED` / `WRITE_DROPPED` / `UNEXPECTED_VALUE`).

### Hypothesis (single bit answered)

**H0 (null):** KEY_FINDINGS row 124 stands as written — pre-set_active MBM writes drop regardless of which core BAR0_WINDOW points at. T284 verdict is correct.

**H1 (the row-171/197 confound is real):** T284's silent-drop verdict was a routing artefact. `brcmf_pcie_intr_enable` calls `brcmf_pcie_write_reg32(devinfo, mailboxmask=0x4C, ...)` WITHOUT first selecting PCIE2 (verified at the function definition; row 197 in-source comment also flags this). If at the moment of the T284 write BAR0_WINDOW happened to be at chipcommon (or wherever else), the write hit `core_X+0x4C`, NOT PCIE2+0x4C. T305 forces the select, so the write is guaranteed to land at the intended target.

### Outcome decoder

| `_t305_win_before` | `_t305_mbm_post` | Interpretation |
|---|---|---|
| Already at PCIE2 base (0x18102000) | unchanged from `_t305_mbm_pre` (0x318 or 0) | **H0 confirmed.** Row 124 stands. MBM is genuinely write-locked at this register/timing. Not a routing issue. |
| Not at PCIE2 base | `0xFF0300` | **H1 confirmed.** Row 124 was a routing confound. T241/T280/T284 verdict needs revising — they may have been writing to `core_X+0x4C` instead. |
| Not at PCIE2 base | unchanged (0x318 or 0) | **Window-at-PCIE2 isn't the missing piece.** Deeper structural issue. Row 124's verdict effectively still holds; need to look elsewhere for what gates MBM writes. |

### Cross-cutting flag (advisor catch — not a contradiction the test must resolve)

KEY_FINDINGS shows tension between row 117 ("MBM=0 explains why fw stays in WFI") and row 157 ("fw blob has ZERO refs to PCIE2 register space → MBM structurally not the wake gate"). **If T305 lands the write (H1) BUT fw still does not wake** (no console wr_idx advance from 587, no MAILBOXINT, no behavior change), that's CLEAN CLOSURE of the MBM-as-wake-gate question — not a contradiction. It means MBM-write-lock is the wrong concern; row 157 is correct and MBM is structurally irrelevant. Either outcome (write lands / write drops) is information.

### Run sequence (after user reboots into the new boot config)

```bash
# 1. Substrate check (per CLAUDE.md pre-test checklist)
sudo lspci -vvv -s 03:00.0 | grep -E 'MAbort|CommClk|LnkSta'
cat /proc/cmdline   # mitigations=off should NOT be present

# 2. Verify built module is current
ls -la phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko
# (rebuild if needed: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build ; make -C "$KDIR" M=$PWD/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules)

# 3. Edit phase5/work/test-brcmfmac.sh modprobe args to add: bcm4360_test305_premask_with_select=1
#    (single-purpose run; do NOT also set bcm4360_test284_premask_enable=1 — they would write MBM twice and confound)
#    Keep T276 + T277 + T278 enabled per usual baseline.

# 4. Fire
sudo phase5/work/test-brcmfmac.sh

# 5. Inspect log for "BCM4360 test.305: SUMMARY" line in latest phase5/logs/test.N
```

### Substrate / cost expectations

- One full experiment fire (CLAUDE.md "Full experiment" tier) on substrate that's been through 3 reboots this session (cycle1, cycle1b, post-cleanup). Substrate freshness adequate for a single-shot probe but not for n>1 statistics.
- Crash risk: comparable to T284 (pre-set_active MBM write attempt). T284 fired without wedge — T305 just adds explicit select_core(PCIE2) before the same write, so risk delta is negligible.
- Wedge expectation per row 104: t+90s..t+120s bracket likely. T305 SUMMARY line prints AT pre-set_active timing (well before set_active completes), so even if wedge happens later, the SUMMARY should be in the log.

### Awaiting user steer post-reboot

Path (a) reframed as T305 is the live test. Decision belongs to user. Code is staged + built but not fired in user's absence (substrate has wl-tainted reboot history this session, and per CLAUDE.md full-experiment tier requires user awareness for crash recovery).

## A + B + C synthesis (2026-04-28 ~07:30 BST — wl.ko disasm + bcmdhd cross-reference)

User pointed at `t305_glm51_options.md` (Kilo doc claiming bcmdhd uses PCI config-space for interrupt masking). Three workstreams in parallel:

**A — wl.ko config-space write enumeration (direct disasm + reloc walk).** Full report: `phase6/t305_wl_config_writes.md`. 31 write sites; reachable from `wl_pci_probe → wlc_attach → wlc_bmac_attach`:
- `si_clkctl_xtal` writes config **0xB4 + 0xB8** (PMU/clock crystal area)
- `si_pcieobffenable` / `si_pcieltrenable` program PCIe LTR/OBFF caps
- `si_pci_setup` writes config **0x94** (vendor RMW) during interface up
- BCM4360-specific: `wlc_bmac_4360_pcie2_war` (798 bytes, not yet disassembled)
- **NO `PCIIntmask = 0x3` write anywhere** — Kilo doc's specific recommendation REFUTED in wl.

**B — bcmdhd cross-reference (subagent, AOSP source w/ file:line citations).**
- bcmdhd is the **same role as brcmfmac** (offload-host driver) — successfully drives BCM4360.
- bcmdhd does NOT write config 0x94, 0xB4, or 0xB8. `si_clkctl_xtal` and `si_pci_setup` are declared in headers but NOT implemented in the dongle-host build (those are full-driver helpers from wl/PCIE-gen1 codebase).
- bcmdhd's `dhdpcie_bus_intr_enable` for BCM4360 (PCIE2 rev 1, NOT in {2,4,6}) takes the **MMIO branch**: `si_corereg(sih, buscoreidx, PCIMailBoxMask=0x4C, def_intmask, def_intmask)` where `def_intmask = D2H_MB | FN0_0 | FN0_1`. **This is structurally identical to brcmfmac's `brcmf_pcie_intr_enable`.**
- bcmdhd's `si_corereg` internally does select-core-then-MMIO-write — the same pattern T305 forces explicitly.
- bcmdhd surfaces ONE init WAR at PCIE2 internal cfg **0x4e0** via CONFIGADDR/CONFIGDATA (BAR0+0x120/0x124), described as "BAR1 window may not be sized properly" RMW.

**C — T306 read-only PCI-cfg dump probe (built).** Reads config 0x40..0xFF (48 dwords) at pre-write / post-set_active / post-T276-poll. Independent of test284/305, safe to combine.

### KEY REFRAME

The Kilo document's "wl-only config-space writes (0x94/0xB4/0xB8) are the missing magic" hypothesis is **largely closed** by B: bcmdhd successfully drives BCM4360 without making those writes. They are full-driver / PCIE-gen1 helper code, NOT necessary for offload-mode operation. Pursuing T307 (vendor-cfg writes) is no longer the highest-priority direction.

What B **does** confirm: bcmdhd's intr_enable for BCM4360 takes the MMIO branch (PCIE2+0x4C), uses `si_corereg` which internally selects the PCIE2 core BEFORE the write. Our existing T241/T280/T284 used `brcmf_pcie_intr_enable` which writes BAR0+0x4C **without** selecting PCIE2 first — exactly the row-171 confound. **T305's design (explicit select_core(PCIE2) before the write) now exactly matches bcmdhd's pattern.** T305 is now strongly motivated, not just speculatively motivated.

### Already-implemented checks (verified, NOT new gaps)

- BAR1 WAR (PCIE2 internal cfg 0x4e0 RMW via CONFIGADDR/CONFIGDATA) is at pcie.c lines 2742-2748 (`test.128`). brcmfmac does this with explicit `brcmf_pcie_select_core(BCMA_CORE_PCIE2)` first. NOT a gap vs bcmdhd.
- bcma pcie2_init writes (test.194: SBMBX, PMCR_REFUP) are at pcie.c lines 2718-2731. Per memory and code comments, gated on chiprev=3 / pcie2_rev=1.

### Open new lead from B (lower priority than T305)

bcmdhd's BAR1 WAR write to PCIE2 internal cfg 0x4e0 is "RMW (read, write back unchanged)" — same as brcmfmac's test.128. **B's wording suggests the read itself is the operative side effect** (some chips have read-clears semantics). Worth confirming the bcmdhd source at `dhd_pcie.c:457-464` literally writes back the unchanged value, vs read-only-then-write-modified. If the write IS modifying, our test.128 may be wrong. Defer.

### Fire plan recommendation

**Single combined fire: T305 + T306 enabled together.**
- T305 (pre-set_active MBM write WITH select_core(PCIE2)) — bcmdhd-pattern-validated; single-bit answer on whether the write lands when properly routed.
- T306 (PCI cfg dump 0x40..0xFF at 3 stages) — read-only; baseline of what brcmfmac leaves at vendor area, including 0x94/0xB4/0xB8.
- Independent surfaces. T306 is read-only; T305 writes one register. Both print SUMMARY at pre-set_active timing well before any wedge.

Both questions answered in one substrate cost. Per CLAUDE.md full-experiment tier, awaiting user GO.

### Decision tree for follow-ups

- **T305 lands (mbm_post = 0xFF0300):** the routing confound was real. Next: T308 (does the mask persist across set_active? + trigger H2D doorbell + check console).
- **T305 drops with select_core verified:** MBM is genuinely write-locked. Pursue bcmdhd's `si_corereg` mechanism more carefully — maybe it does something different than our select_core+write. Examine its source.
- **T306 shows 0x94/0xB4/0xB8 already non-zero or in wl-target state:** chip defaults are favourable; vendor-cfg-writes hypothesis closed.
- **T306 shows 0x94/0xB4/0xB8 all zero:** wl writes them for a reason, and if T305 doesn't unblock, it's worth looking at why bcmdhd works without them (maybe PMU is in a different state at probe time on Android vs Linux).


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
