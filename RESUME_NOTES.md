# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-22, after test.231)

**Latest outcome (test.231):** Timing bisect ran — 10 breadcrumbs at
10/50/100/200/300/500/700/900/1000 ms post-set_active. Host wedged,
SMC reset required. **Journal tail-truncated to probe-time
`pci_clear_master` (21:34:40)** — all 10 dwell breadcrumbs were lost
along with the normal `returned true` marker. Compare test.230: the
same `pci_clear_master` breadcrumb landed at line 1118 and the run
continued cleanly through set_active-skip to -ENODEV. So this is the
established tail-truncation pattern (tests 226/227), not a new wedge
location. The bisect produced **no new information**: the wedge
window we want to bisect (≤1 s) is smaller than journald's tail-drop
budget (~15–20 s here).

**Pivot required before another wedge test.** Journald is structurally
too lossy for sub-second measurements. pstore is dead (bus-wide stall
freezes watchdog CPU — tests 227/228/229). netconsole declined. The
strongest remaining option is a **TCM-resident breadcrumb ring buffer**:
we've proven 16/16 TCM writes survive and fast-UR BAR0 is alive
post-wedge, so a marker written to TCM just before each msleep can be
read back after recovery via setpci/mmap (or a diagnostic-mode .ko
that maps BAR2, dumps the ring, and exits without probing).
*Caveat to verify:* does a Mac SMC reset wipe chip TCM? If yes, the
ring is only readable after a soft recovery that doesn't hit SMC.

**Prior fact (test.230):** `brcmf_chip_set_active` is the **SOLE
trigger** for the bus-wide wedge. With that call skipped, the host
survived the entire probe path cleanly — both breadcrumbs landed,
driver returned -ENODEV, rmmod worked, host alive ≥30 s after, BAR0
still fast-UR. First-ever clean full run.

**Prior fact (test.229):** Post-set_active probe MMIO is innocent —
probes `#if 0`'d, host still wedged. Narrowed the trigger to
"set_active itself"; test.230 confirmed.

**Hardware invariants:**
- Chip: BCM4360, chiprev=3, ccrev=43, pmurev=17
- Cores: pcie2 rev=1, ARM CR4 @ 0x18002000
- Firmware: 442,233 bytes; rambase=0x0, ramsize=0xA0000 (640 KB TCM)
- BAR0=0xb0600000, BAR2=0xb0400000 (TCM window)
- Firmware download: full 442 KB writes successfully; TCM verify 16/16 MATCH
- set_active: reaches CR4, returns true; CPUHALT clears; fw starts executing

**Ruled-out hypotheses (cumulative):**

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/7/0xe/0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |
| Wedge at test.158 ARM CR4 probe line | 226, 227 | ruled out — tail-truncation illusion; journal kept going after that line once NMI watchdog enabled |
| Chunked-write regression (wedge at chunk 27) | 228 | ruled out — was also tail-truncation; full 107 chunks in journal once we survive long enough |
| Wedge caused by probe_armcr4_state MMIO 0x408 (H1) | 229 | ruled out — probes disabled, wedge still occurred |
| Wedge caused by any tier-1/2 fine-grain probe | 229 | ruled out — gated `#if 0`, wedge still occurred |
| Wedge caused by 3000 ms dwell polling | 229 | ruled out — replaced with msleep(1000), still wedged |
| Wedge caused by pre-set_active path (FORCEHT / pci_set_master / fw write) | 230 | ruled out — skipped set_active, host survived cleanly end-to-end |
| Wedge caused by anything OTHER than `brcmf_chip_set_active` | 230 | ruled out — that call is the single-point trigger |
| Sub-second wedge window measurable via journald tail | 231 | ruled out — tail-truncation budget (~15–20 s) >> wedge window |

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — DMA target not set up:**
Upstream brcmfmac sets up extensive shared-memory / ring-descriptor
infrastructure (`brcmf_pcie_init_share`, ring alloc, mailbox setup)
BEFORE set_active. Our BCM4360 path bypasses all of that. Newly-alive
firmware likely tries to DMA-read ring descriptor addresses from the
shared-memory struct in TCM; those fields are all-zero or garbage;
firmware dereferences a NULL/garbage host address; PCIe TLPs issued
to that host address never get a completion; bus stalls.

**Immediate next step (test.232 — TCM ring-buffer logging transport):**
Replace the post-set_active `pr_emerg` breadcrumbs with TCM writes to
a reserved scratch region (e.g. offset 0x9F000 — top of 640 KB TCM,
well past the 0x6F000 fw payload). Each breadcrumb writes a 32-bit
`sequence | timestamp` word at offset+4*N. Then after SMC recovery,
a diagnostic tool (setpci BAR2 + /dev/mem read, or a minimal .ko that
maps BAR2 and dumps 40 bytes without probing) reads the ring.
First: verify whether Mac SMC reset wipes chip TCM. If TCM is wiped,
fall back to the broader `earlyprintk=serial` option.

Per-test design (test.232 draft):
- code: write markers at `tcm_base + 0x9F000 + 4*idx` for idx=0..9
  immediately before each msleep(N); leave `pr_emerg` in place as a
  redundant second transport.
- post-wedge: power up host, avoid SMC reset if possible, read BAR2
  window at TCM offset 0x9F000, dump 10 u32s; if non-zero tail, last
  non-zero index = upper bound on wedge window.
- fallback probe: if TCM is wiped, test.232 becomes moot; move to
  netconsole (user re-ask) or serial.

**Logging transport status:**
- journald: drops ~15–20 s of tail when host loses userspace (confirmed tests 226/227/231).
- pstore: doesn't fire — bus-wide stall freezes watchdog CPU (tests 227/228/229).
- netconsole: user declined second-host setup.
- TCM ring buffer: not yet tested. Strongest remaining candidate. 16/16 write-verify proven in tests 225/228/229/230. Post-wedge BAR0 fast-UR proven alive. Unknown: whether SMC reset wipes TCM (user feedback needed).
- `earlyprintk=serial`: remaining option if TCM route fails.

---


## POST-TEST.231 (2026-04-22 21:34 BST, boot -1 → SMC reset → boot 0) — journal tail-truncation swamped the bisect; no timing info recovered

### Headline

Host wedged as expected once `brcmf_chip_set_active` was re-enabled. SMC
reset required. Boot -1 journal tail-truncated to `test.158: about to
pci_clear_master (config-space write)` at 21:34:40 — a full ~15–20 s
(and ~10 code-path blocks) BEFORE the set_active call that was
supposed to reveal timing. All 10 timing breadcrumbs
(t=10/50/100/200/300/500/700/900/1000 ms plus dwell-done) were lost.
No new information about wedge timing.

### Why this is tail-truncation, not a new regression

Test.230's journal captured the exact same `about to pci_clear_master`
breadcrumb at line 1118, then continued cleanly through ASPM disable,
full fw download, TCM verify, set_active-skip, 1000 ms dwell, BM
clear, release_firmware, and -ENODEV return (line 1413, 21:24:57).
So this breadcrumb is NOT a wedge point — it just happens to be where
journald's last-flushed entry landed for test.231. This matches the
tail-truncation pattern first confirmed in tests 226/227 (host loses
userspace → journald drops the tail that was in the kernel ring
buffer but not yet persisted).

### Truncation budget exceeded the bisect window

The wedge window under investigation was ≤1 s (10 ms – 1000 ms after
set_active). Based on test.231 compared to test.230, journald lost at
least ~15 seconds of tail (the gap between `pci_clear_master` and the
expected dwell breadcrumbs). That's one to two orders of magnitude
larger than the measurement interval. Journald is structurally unable
to resolve this wedge window.

### Artifacts captured

- `phase5/logs/test.231.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore (empty) + strings. Harness output ends at "Modules
  loaded. Waiting 15s…" (script killed by wedge).
- `phase5/logs/test.231.journalctl.full.txt` — 1472 lines boot -1.
- `phase5/logs/test.231.journalctl.txt` — 442 lines filtered.
- `phase5/logs/test.8` — test-brcmfmac.sh dmesg from test.230 run
  (captured by script mid-session, not test.231). Kept as a reference
  for what a full successful run looks like.
- No pstore artifacts (bus-wide stall → watchdog frozen, as expected).

### Hardware state after SMC reset

Host alive, booted into boot 0 (21:36:38 BST). Chip reset via SMC.
Ready for next test after logging pivot.

### Implication: pivot before next wedge test

Further wedge experiments that depend on journald for sub-second
resolution are guaranteed to lose data. Need a transport that
survives the bus-wide stall. Top candidate: TCM-resident ring buffer
(see "Current state" → test.232 draft).

---

## PRE-TEST.231 (2026-04-22 21:33 BST, boot 0, no reset needed) — single-run timing bisect to locate the wedge window post-set_active

### Hypothesis

With `brcmf_chip_set_active` re-enabled (baseline + wedge returns),
emit 10 breadcrumbs at 10/50/100/200/300/500/700/900/1000 ms after
the `returned true` marker. The last breadcrumb to appear in the
journal gives an upper bound on the wedge window. Interpretation:

- Last breadcrumb at 10–100 ms → fw hits the bus within ~100 ms of
  starting. Suggests DMA-target-missing or instant config-TLP failure.
- Last breadcrumb at 200–500 ms → fw runs some init routine then
  stumbles. Could be init-poll on a missing resource.
- Last breadcrumb at 700–1000 ms → fw polls for a host-ready marker
  or does extensive internal init first.
- All breadcrumbs including `t=1000ms dwell done` land, host wedges
  later → stall is past 1 s; broader window to hunt in.
- `t=0ms dwell start` itself does not land → stall is instant-on-
  set_active.

### Why single-run (not 4 runs as advisor initially suggested)

Advisor suggested N=50/250/500/900 as 4 separate runs. Single-run with
10 sequential breadcrumbs gives the same information (last-landing
breadcrumb = wedge upper bound) plus finer granularity, at 1/4 the
SMC-reset cost. Wedge is reliably reproducible (tests 227/228/229 all
wedged in the same window), so independent-runs aren't needed for
variance observation. If the single-run result is ambiguous (e.g.
breadcrumbs interleave with kernel watchdog messages in confusing
ways), individual-N runs remain available as a fallback.

### Code change (pcie.c, in `brcmf_pcie_download_fw_nvram`)

Restored the original `brcmf_chip_set_active` call + surrounding
`test.226 immediately before / after` + `test.188: returned %s`
breadcrumbs that test.230 removed. Then replaced test.230's single
`msleep(1000)` with a chain of `msleep(N) + pr_emerg` pairs at the
offsets above. Total dwell is still 1000 ms.

Post-set_active probe block (`probe_armcr4_state` etc.) remains at
`#if 0` — keep one variable at a time.

### Build status — REBUILT CLEAN (2026-04-22 21:32 BST)

`brcmfmac.ko` 14251536 bytes, mtime 21:32. `strings` confirms all 10
`test.231: t=…` breadcrumbs present.

### Hardware state (still boot 0 of 21:06 BST SMC-reset session)

- `lspci -vvv -s 03:00.0`: Control Mem+ BM-, Status MAbort-, DevSta
  UnsupReq- (cleared by test.230), TransPend-, LnkSta 2.5GT/s x1.
- BAR0 timing 17/18/18/18 ms — fast-UR intact.
- pstore empty, no modules loaded.
- No SMC reset needed (test.230 left chip clean because fw never activated).

### Decision tree

| Journal signature | Interpretation | Test.232 direction |
|---|---|---|
| Last breadcrumb is `t=0ms dwell start` or `returned true` | Stall is effectively instant-on-set_active. | Try to populate shared-memory struct in TCM before set_active so fw has valid DMA targets. |
| Last breadcrumb in [10, 200] ms | Fast fw-stumble. Likely DMA-target-missing. | Same as above (populate shared-memory). |
| Last breadcrumb in [300, 700] ms | Medium — fw runs an init routine then stumbles. | Look for fw init polling shapes (ring-descriptor read, doorbell write, MSI request). |
| Last breadcrumb in [900, 1000] ms | Slow — fw polls host-ready marker or does extensive init. | May be recoverable by responding to a fw doorbell within the window. |
| All breadcrumbs land including `t=1000ms dwell done` | Stall is past 1 s. | Extend dwell (test.232: 1/2/3/5 s breadcrumbs) and re-bisect. |

### Logging / watchdog arming (same as test.229/230)

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

If host wedges: expect no auto-reboot, user power-cycle + SMC reset
needed (consistent with tests 227/228/229).

### Expected artifacts

- `phase5/logs/test.231.run.txt` — PRE + harness.
- `phase5/logs/test.231.journalctl.full.txt` — full journal (boot 0
  if host survives; boot -1 if wedged).
- `phase5/logs/test.231.journalctl.txt` — brcmfmac/PCIe/NMI filtered.

---

## POST-TEST.230 (2026-04-22 21:25 BST, boot 0 — NO CRASH, host survived cleanly) — `brcmf_chip_set_active` is the SOLE wedge trigger

### Headline

First-ever clean full run of the probe path. Skipping the
`brcmf_chip_set_active` call (single code change from test.229 baseline)
produced a clean -ENODEV return, clean rmmod, host alive ≥30 s after
rmmod, and a healthy PCIe bus throughout. All strict success criteria
met. H2 is confirmed at the strongest possible level: firmware
activation is the sole bus-stall trigger.

### Evidence (current-boot journal, 21:24:49 → 21:24:58, no reboot needed)

- Pre-set-active path: all breadcrumbs landed in order
  (pci_set_master, FORCEHT, pre-set-active probes, etc. — identical to
  test.229).
- Firmware download: 107 chunks, full 442 KB.
- TCM verify: 16/16 MATCH.
- `test.219: calling brcmf_chip_set_active resetintr=0xb80ef000
  (FORCEHT pre-applied)` — breadcrumb landed but the call itself skipped.
- `test.230: SKIPPING brcmf_chip_set_active — resetintr=0xb80ef000
  NOT written to CR4` — 1136.529876 s boot-time.
- `test.230: 1000 ms dwell done (no fw activation); proceeding to
  BM-clear + release` — 1137.566367 s boot-time (≈1.04 s later — the
  msleep(1000) actually completed).
- `test.188: pci_clear_master done; PCI_COMMAND=0x0002 BM=OFF` — clean BM-clear.
- `test.188: post-BM-clear MMIO guard mailboxint=0x00000001 (endpoint
  alive after BM-off)` — endpoint responsive through end of probe.
- `test.163: download_fw_nvram returned ret=-19 (expected -ENODEV
  for skip_arm=1)` — probe path completed as designed.
- `test.163: fw released; returning from setup (state still DOWN)` —
  full return, no stall.

### Post-run host / bus health (rmmod at 21:25:32 BST, +30 s dwell at 21:26:03)

- `rmmod brcmfmac_wcc && rmmod brcmfmac && rmmod brcmutil` — all clean.
- `lsmod | grep -E 'brcm|wl'` after rmmod — empty.
- lspci after rmmod: Control `Mem+ BusMaster-`; DevSta **UnsupReq-**
  (sticky bit cleared — nothing in this test generated an UR after
  the pre-test UR probe), TransPend-; LnkCtl ASPM Disabled (kernel
  reverted after rmmod), LnkSta 2.5GT/s x1.
- BAR0 timing 18/18/18/18 ms — fast-UR regime intact.
- pstore still empty.
- 30 s dwell passed uneventfully.

### What this proves

| Hypothesis | Status |
|---|---|
| Pre-set_active bus-hostile write (FORCEHT / pci_set_master / fw download) | **RULED OUT** — entire sequence ran, host fine |
| `brcmf_chip_set_active` itself or its immediate aftermath is the trigger | **CONFIRMED** |
| Firmware activation → DMA to missing shared-memory rings → completion starvation | still the leading theory; test.231 will probe it |

### Next: test.231 (timing bisect, per advisor)

Re-enable `brcmf_chip_set_active` and place an `msleep(N)` between the
`returned %s` breadcrumb and the BM-clear tail, running the test at
N=50 / 250 / 500 / 900 ms. The *last* N for which the msleep-done
breadcrumb lands tells us the window in which firmware first does
something bus-hostile. Rationale:
- Fast (<100 ms) → fw stumbles immediately on missing DMA target.
- Slow (>500 ms) → fw runs some init first, then stumbles — different
  signature, maybe it's polling for a host-readiness marker.

### Artifacts captured

- `phase5/logs/test.230.run.txt` — PRE sysctls + lspci + BAR0 + pstore
  + strings + harness output (405 lines).
- `phase5/logs/test.230.journalctl.full.txt` — current-boot full
  journal (1419 lines).
- `phase5/logs/test.230.journalctl.txt` — brcmfmac/PCIe/NMI filtered
  (401 lines).
- No pstore dump (none expected — no crash).

---

## PRE-TEST.230 (2026-04-22 21:22 BST, boot 0 post-SMC-reset) — skip `brcmf_chip_set_active` entirely; binary test of H2-sub-hypothesis

### Hypothesis

Firmware activation (= CR4 coming out of reset with rstvec written) is
the SOLE trigger for the bus-wide wedge confirmed in test.229 (H2).
If we never call `brcmf_chip_set_active`, the host should survive the
entire probe path cleanly (return -ENODEV → rmmod succeeds → host stays
alive afterwards).

### Code change

`drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` —
`brcmf_pcie_download_fw_nvram`, right after the `test.219: calling`
and `mdelay(30)`. Replaced the `brcmf_chip_set_active(...)` call and
its surrounding probe/dwell block with:

```c
pr_emerg("BCM4360 test.230: SKIPPING brcmf_chip_set_active — resetintr=0x%08x NOT written to CR4\n",
         resetintr);
msleep(1000);
pr_emerg("BCM4360 test.230: 1000 ms dwell done (no fw activation); proceeding to BM-clear + release\n");
```

Also initialised `sa_rc = false` at declaration to silence uninitialised
use (it is referenced nowhere else in this arm but still declared in
the enclosing scope).

**Post-set_active probe block remains `#if 0`** — not re-enabled. This
preserves the H1/H2 ambiguity fix from test.229 (one variable at a
time).

### Build status — REBUILT CLEAN (2026-04-22 21:22 BST)

`brcmfmac.ko` 14243024 bytes, mtime 21:22. `strings` confirms both
new breadcrumbs present:
- `BCM4360 test.230: SKIPPING brcmf_chip_set_active`
- `BCM4360 test.230: 1000 ms dwell done (no fw activation); …`

### Hardware state (post-SMC-reset boot at 21:06 BST)

- `lspci -vvv -s 03:00.0` — Control `Mem+ BusMaster+`, Status
  MAbort-, TAbort-, DEVSEL=fast; DevSta CorrErr+ UnsupReq+ (sticky,
  from earlier UR), AuxPwr+ TransPend-; LnkCtl ASPM Enabled, CommClk+;
  LnkSta 2.5GT/s x1 — clean (post-SMC-reset idiom, matches test.229
  PRE state exactly).
- BAR0 `dd resource0` wall-clock: 18/18/18/18 ms — fast-UR regime.
- `lsmod | grep -E 'brcm|wl'`: empty.
- pstore: empty (no lingering dumps).

### Decision tree

| Outcome signature | Interpretation | Next (test.231) |
|---|---|---|
| Both breadcrumbs in journal + -ENODEV return + rmmod works + host ≥30 s alive after rmmod | **Firmware activation IS the sole bus-stall trigger.** Pre-set_active path is safe. | Timing bisect: re-enable set_active, insert `msleep(N)` between set_active return and the BM-clear tail. Try N=50/250/500/900 (new test.231 binary discriminator). |
| Any breadcrumb missing, or driver stall, or host wedges | **Something pre-set_active is bus-hostile.** Candidates: FORCEHT write, pci_set_master, fw-write sequence itself. | Progressively disable pre-set_active steps — start by skipping pci_set_master (keep BM=OFF throughout). |
| Second breadcrumb in journal but rmmod hangs or host dies later | More subtle — bus health is already degraded even without fw activation; mdelay timing or prior register writes left a dirty state. | Capture all post-second-breadcrumb state (pstore, /proc/interrupts, lspci re-read) before interpreting. |

### Logging / watchdog arming (same as test.229)

```bash
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync
```

Note: if the host wedges, `panic=30` may not trigger auto-reboot
(bus-wide stalls freeze the watchdog CPU too, as confirmed in tests
227/228/229). Plan for user power-cycle + SMC reset on that path.

### Expected artifacts

- `phase5/logs/test.230.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore + strings + harness output.
- `phase5/logs/test.230.journalctl.full.txt` — full current-boot kernel
  journal (or boot -1 if host wedges).
- `phase5/logs/test.230.journalctl.txt` — brcmfmac/PCIe/NMI-filtered subset.
- `phase5/logs/test.230.pstore.txt` — IF pstore fires (unlikely on
  bus-wide stall; possible if this is a different failure mode).

---

## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
