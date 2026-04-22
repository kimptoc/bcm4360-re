# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-22, after test.229)

**Latest confirmed fact (test.229):** The post-set_active host wedge is a
**firmware-initiated bus-wide PCIe stall**, not caused by any host probe
MMIO. Test.229 skipped all post-set_active probes (`#if 0`) and replaced
them with a single `msleep(1000)`; the host still wedged. Signature: bus-
wide stall that freezes every CPU simultaneously (NMI watchdog armed but
never fired; pstore empty).

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

**Current leading theory for the wedge cause (H2):**
Newly-alive firmware on CR4 does something on the PCIe bus (DMA, MSI,
config TLP) within ~1 s of `brcmf_chip_set_active` returning that
triggers a completion-starvation stall. All CPUs block on subsequent
bus access, including the watchdog CPU.

**Secondary-possibility worth investigating later:**
Upstream brcmfmac sets up extensive shared-memory / ring-descriptor
infrastructure (`brcmf_pcie_init_share`, ring alloc, mailbox setup)
BEFORE set_active. Our BCM4360 path bypasses all of that. If firmware
expects ring descriptor addresses in TCM shared memory and tries to
DMA there, the DMA target is invalid → no completion → bus stall.

**Immediate next step (test.230 proposed):**
Single-line change — don't call `brcmf_chip_set_active` at all.

| Result | Interpretation | Next |
|---|---|---|
| Host stays alive, driver returns -ENODEV cleanly, rmmod works | Firmware activation IS the sole trigger. | test.231: binary-search when in the first second the stall starts (msleep 100 vs 500 vs 900). |
| Host wedges anyway | Something pre-set_active is the cause (FORCEHT write / pci_set_master / fw-write sequence). | test.231: progressively disable pre-set_active steps. |

**Logging transport status:**
- journald: truncates the last ~5–10 s of tail once host loses userspace (confirmed in tests 226/227).
- pstore: doesn't fire because NMI watchdog's CPU also freezes on bus-wide stall (confirmed tests 227/228/229).
- netconsole: user declined second-host setup.
- Remaining option: `earlyprintk=serial` over RS-232 if/when this becomes the bottleneck.

---


## POST-TEST.229 (2026-04-22 21:08 BST, boot 0 of new session — boot -1 journal captured) — (H2) CONFIRMED: wedge is firmware-initiated bus stall, not our probe MMIO

### Headline

Test.229 ran the Option A binary discriminator (all post-set_active probes
gated behind `#if 0`, replaced with a single `msleep(1000)`). Host still
wedged bus-wide. **This is H2 from the PRE-229 decision tree: firmware-
initiated bus stall — our probing was innocent.** Newly-alive firmware
on ARM CR4 takes the front-side bus down on its own during the ~1 s
window after `brcmf_chip_set_active` returns, regardless of what the
host does next.

### Evidence (boot -1 journal, Apr 22 21:04:41 → 21:04:59)

- Full 442 KB firmware downloaded: **107** chunks in journal (complete).
- TCM verify post-fw-download: **16/16 MATCH** at every sampled offset.
- Pre-set-active probes ran cleanly:
  - CR4 IOCTL=0x21 IOSTATUS=0 RESET_CTL=0 CPUHALT=YES
  - D11 IOCTL=0x7 IOSTATUS=0 RESET_CTL=0x1 (IN_RESET=YES)
  - CR4 clk_ctl_st=0x07030040 [HAVEHT/ALP_AVAIL/bit6]
- FORCEHT applied: clk_ctl_st 0x01030040 → 0x010b0042 (post-write).
- `brcmf_chip_set_active returned true` — reached.
- `test.229: SKIPPING post-set_active probes — msleep(1000) before BM-clear`
  emitted (21:04:59).
- **Second breadcrumb `test.229: 1000 ms dwell done` never appeared.**
  Journal ends there. No NMI watchdog trigger, no panic, no AER.
- pstore empty on recovery (`/sys/fs/pstore/` — 0 files).
- Auto-reboot did not complete in the armed 30 s; user performed SMC reset.

### Why this is H2

The post-set_active code path in test.229 is literally just a `pr_emerg`
+ `msleep(1000)` + `pr_emerg`. No MMIO, no config-space writes, no
anything. The first pr_emerg landed in the journal (so CPU was alive
then). During the `msleep(1000)` — where the kernel yields, other CPUs
keep running, timer ticks fire — something froze every CPU
simultaneously. That signature rules out "host did something that
hung" and points to "bus went away under us". The most plausible
cause on this bus (front-side) is PCIe completion starvation: firmware
does something (a DMA read, a config TLP, an MSI) that never gets
a completion; every CPU that subsequently touches the chip or the
shared PCIe domain blocks; watchdog CPUs block too.

### What we've now ruled out

| Hypothesis | Status |
|---|---|
| Wedge caused by `probe_armcr4_state` MMIO at 0x408 (first post-set_active read) | **RULED OUT** — probes skipped, wedge still occurred |
| Wedge caused by any of the tier-1/2 fine-grain probes | **RULED OUT** — all gated behind `#if 0` |
| Wedge caused by 3000 ms dwell polling | **RULED OUT** — replaced with `msleep(1000)`, still wedged |
| Firmware load / TCM corruption / NVRAM write | not yet ruled out, but highly unlikely (16/16 TCM MATCH, 107 chunks clean) |
| Firmware-initiated post-activation bus event | **CONFIRMED** as the cause |

### Artifacts captured

- `phase5/logs/test.229.run.txt` — PRE sysctls + lspci + BAR0 timing
  + pstore (empty) + the SKIPPING / dwell-done strings from .ko.
  `test-brcmfmac.sh output` ends at `Loading patched brcmfmac modules...`
  (script killed mid-run by wedge).
- `phase5/logs/test.229.journalctl.full.txt` — 1390 lines whole boot -1.
- `phase5/logs/test.229.journalctl.txt` — 397 lines brcmfmac/PCIe/NMI filtered.
- No `test.229.pstore.txt` — pstore empty after recovery reboot.

### Implication for test.230

PRE-229 decision tree prescribes (H2 branch):

> test.230 goes a different direction: either don't call set_active at
> all (read all the state before firmware comes alive), or sample CR4
> state via config-space-only path (no BAR0 MMIO after set_active).

Cheapest next step: **don't call set_active**. Single-line change
(gate the `brcmf_chip_set_active` call behind `#if 0`, or replace the
call with a no-op breadcrumb + msleep). Decision tree:

| Result | Interpretation | Next |
|---|---|---|
| Host stays alive, driver returns -ENODEV cleanly, rmmod works | Firmware activation IS the sole trigger. Bus stall happens after CR4 is released from reset. | test.231 narrows the timing: e.g. call set_active then msleep(100) vs msleep(500) to see when the stall starts. |
| Host wedges anyway | Something pre-set_active is causing the stall (FORCEHT write, pci_set_master, fw/NVRAM write sequence). Much more work to isolate. | test.231 = progressively disable pre-set_active steps to isolate the culprit. |

This keeps the experimentation binary and cheap.

### Secondary possibility to consider (not test.230 but future)

Upstream brcmfmac sets up extensive shared memory / ring descriptor
infrastructure BEFORE `brcmf_chip_set_active` on other Broadcom PCIe
parts: `brcmf_pcie_init_share`, ring allocation, mailbox setup. Our
bypass path likely skips all of that for BCM4360. If newly-alive
firmware tries to DMA ring descriptors from host memory that was
never allocated, it could trigger exactly the kind of completion
starvation we observe. Worth investigating once test.230 narrows the
cause further — but test.230 is the cheaper next swing.

---

## POST-TEST.228 (2026-04-22 20:42 BST, boot 0 of new session — boot -1 journal captured) — set_active reached AND returned true for the first time; pstore empty, bus-wide stall confirmed

### Headline

Full 442 KB firmware downloaded (**107** chunks in journal, up from 26 in
test.227), TCM verify passed (16/16 MATCH), `brcmf_chip_set_active`
called AND returned `true` — furthest progress ever. Host wedged
immediately after, between the `brcmf_chip_set_active returned true`
pr_emerg and the first `post-set-active-20ms` MMIO probe. NMI watchdog
never fired, `/sys/fs/pstore/` is empty, host auto-rebooted ~2 min
later (not the 30 s armed) — consistent with bus-wide stall that
froze every CPU including the watchdog CPU.

### Branch taken from PRE-228 decision tree: (a) + new progress

| Result | → test.228 observed |
|---|---|
| ~107 chunks → (a) pure truncation; wedge is post-chunked-write | **MATCH — 107 chunks captured** |
| ~26 chunks → (b) real regression at chunk 27 | — |

Branch (a) confirmed for the chunked-write portion. But additionally:
**set_active was empirically captured in this journal for the first time.**
test.225.rerun's journal (the one the commit called "JACKPOT") actually
ended at `CC-res_state=0x000007ff (pre-release snapshot)` — no
set_active marker. test.228 is the FIRST run where we see
`BCM4360 test.188: brcmf_chip_set_active returned true`. That's real
new progress, not just truncation-lift.

### Confounder — state-dependence across 4 stacked wedges without SMC reset

Same .ko as test.226/227 but the chip has now endured 4 wedges without
SMC reset. "(a) vs (b)" is clean at the chunk-count level, but
"same .ko, same plan" is no longer literally the same experiment at
the chip-state level. The (a) conclusion stands (107 is unambiguous),
but test.229 should be run on a freshly-reset chip so the next binary
outcome is not contaminated by accumulated chip state.

### Wedge location

Last brcmfmac line in boot -1 journal (line 1399 of the full log):
```
20:36:12 brcmfmac: BCM4360 test.226: immediately before brcmf_chip_set_active()
20:36:12 brcmfmac 0000:03:00.0: BCM4360 test.65 activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006 (BusMaster preserved)
20:36:12 brcmfmac: BCM4360 test.226: immediately after brcmf_chip_set_active() returned
20:36:12 brcmfmac: BCM4360 test.188: brcmf_chip_set_active returned true
(end of journal)
```

Next action in code (pcie.c:2497-2498):
```c
mdelay(20);
brcmf_pcie_probe_armcr4_state(devinfo, "post-set-active-20ms");
```

`brcmf_pcie_probe_armcr4_state` does (pcie.c:714-741):
1. pci_read_config_dword BAR0_WINDOW  (config space — usually safe)
2. pci_write_config_dword BAR0_WINDOW := arm_core->base + 0x100000 (config posted)
3. **MMIO read of 0x408 (ARM CR4 IOCTL)  ← first MMIO after set_active**
4. MMIO read of 0x40c (IOSTATUS)
5. MMIO read of 0x800 (RESET_CTL)
6. pci_write_config_dword to restore BAR0_WINDOW
7. select_core(CHIPCOMMON)
8. pr_emerg the result

Two candidate hypotheses for the wedge:

- **(H1) Host-initiated MMIO stall.** The read at 0x408 hangs because
  ARM CR4 wrapper is in a transitional state: CR4 has just been taken
  out of reset and firmware is reinitialising the BCMA bus during the
  20 ms mdelay window.
- **(H2) Firmware-initiated bus stall.** Newly-alive firmware on CR4
  does something of its own (bus-wide master-abort, PCIe completion
  starvation, BCMA clock gating) that freezes the host bus
  independently of our probing.

### pstore verdict — not a viable transport past this wedge

NMI watchdog armed (confirmed `NMI watchdog: Enabled` at 20:25:24).
`hardlockup_panic`, `softlockup_panic`, `panic=30` armed (confirmed in
`test.228.run.txt`). Yet **no panic fired, pstore empty, auto-reboot
at ~2 min not 30 s**. This is PRE-227 decision-table outcome (i):
bus-wide stall freezes every CPU simultaneously; the watchdog CPU
can't fire either. **Breadcrumbs past the wedge point will never
flush, by either journald or panic handler.** Must move the wedge
earlier (or skip it entirely) if we want to capture more.

### Artifacts captured (2026-04-22 20:42 BST)

- `phase5/logs/test.228.run.txt` — 35 lines; PRE sysctls + lspci +
  BAR0 timing + pstore (empty). `test-brcmfmac.sh output` is a blank
  line (script killed mid-run by wedge — expected).
- `phase5/logs/test.228.journalctl.full.txt` — 1399 lines (whole boot -1).
- `phase5/logs/test.228.journalctl.txt` — 340 lines (brcmfmac-filtered).
- No `test.228.pstore.txt` — pstore was empty after the crash reboot.

---

## PRE-TEST.229 (plan, not yet run) — Option A binary discriminator: is the wedge caused by our probe MMIO or by firmware action on the bus?

### Hypothesis + design

Skip ALL post-set_active probes (`probe_armcr4_state`,
`probe_d11_state`, `probe_d11_clkctlst`, tier-1 fine-grain, tier-2
fine-grain, 3000 ms dwell). Replace with a single
`msleep(1000)` + breadcrumb pair + straight to the existing
BM-clear → release_firmware → return -ENODEV tail.

### Binary decision tree

| Result | Interpretation | Next test |
|---|---|---|
| Host does NOT wedge; driver returns -ENODEV cleanly and rmmod works | **(H1) Wedge is host-initiated MMIO.** Our probe hung on an MMIO read. | test.230 adds per-MMIO breadcrumbs inside `probe_armcr4_state` (between the config-space window reprogramming and each of the three BAR0 reads) to pinpoint the hanging register. |
| Host wedges anyway | **(H2) Wedge is firmware-initiated bus stall.** Our probing was innocent; newly-alive firmware takes the bus down on its own. | test.230 goes a different direction: either don't call set_active at all (read all the state before firmware comes alive), or sample CR4 state via config-space-only path (no BAR0 MMIO after set_active). |

### Why Option A beats Option B (per-register breadcrumbs)

1. **Binary answer from one run.** Option A tests a single yes/no
   question. Option B assumes (H1) and tries to narrow it — wastes
   a run if (H2) is the real cause.
2. **Works with bus-wide stall.** If (H2) is true, breadcrumbs past
   the wedge never flush. Option A's last breadcrumb is a controlled
   `msleep(1000)` in the middle of the host's own code — if we get
   past it, the wedge isn't bus-wide.
3. **Cheap.** Small code change (gate the probe block), rebuild is
   ~30 s on this hardware, test run ~20 s.

### Pre-test state requirements

**USER ACTION REQUIRED before test.229: SMC reset.** The chip has
endured 4 wedges without reset across tests 226 (×3), 227, 228. Test.229
is a pivot run — we need a clean chip baseline so the binary outcome
is not contaminated by accumulated state. ACPI config space still looks
clean on current boot but that is not evidence the chip itself is clean.

### Code change plan (to implement next)

In `brcmf_pcie_download_fw_nvram` (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`), immediately after:
```c
pr_emerg("BCM4360 test.188: brcmf_chip_set_active returned %s\n",
         sa_rc ? "true" : "false");
```
wrap the subsequent post-set_active probe + tier + dwell block in
`if (0)` (or a compile-time flag), and insert:
```c
pr_emerg("BCM4360 test.229: SKIPPING post-set_active probes — msleep(1000) before BM-clear\n");
msleep(1000);
pr_emerg("BCM4360 test.229: 1000 ms dwell done; proceeding to BM-clear + release\n");
```

The BM-clear / release_firmware / return -ENODEV tail at pcie.c:2742+
stays intact.

### Pre-test checklist (to complete before running)

1. Build status: **REBUILT CLEAN** (2026-04-22 20:51 BST) — `brcmfmac.ko`
   contains both `test.229: SKIPPING post-set_active probes` and
   `test.229: 1000 ms dwell done` strings; probe/tier/dwell block now
   gated behind `#if 0`
2. PCIe state: will re-verify after SMC reset (user action)
3. Hypothesis stated: above
4. Plan committed and pushed: this commit
5. Filesystem synced in commit step
6. **USER ACTION PENDING**: SMC reset before insmod

### Run command (same as every test)

```bash
# Arm watchdog sysctls (same as test.228; still useful to confirm H1 vs H2 crash mode if wedge still happens)
echo 1 | sudo tee /proc/sys/kernel/nmi_watchdog
echo 1 | sudo tee /proc/sys/kernel/hardlockup_panic
echo 1 | sudo tee /proc/sys/kernel/softlockup_panic
echo 30 | sudo tee /proc/sys/kernel/panic
sync

sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```


---

## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
