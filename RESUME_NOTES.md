# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 07:42, after test.239 — sharedram_ptr stayed `0xffc70038` for ALL 22 landed dwells; fw never advanced to shared-struct allocation)

**Latest outcome (test.239):** With `force_seed=1`,
`ultra_dwells=1`, `poll_sharedram=1`, the probe ran cleanly to
`brcmf_chip_set_active` (returned TRUE at 01:10:43 BST), then the
ladder landed **the same 22 dwell breadcrumbs as test.238**
(t+100ms..t+90000ms) plus 22 paired `test.239: t+Xms
sharedram_ptr=0x%08x` polls. **Every poll returned `0xffc70038`** —
identical to the NVRAM-length marker our host writes pre-set_active.
Fw never overwrote TCM[ramsize-4] with a shared-struct address
during the ≥90 s window. Host wedged again in the same [t+90s,
t+120s] window; user performed SMC reset; current boot 0 started
07:41:38 BST, lspci `Mem- BusMaster-` (uninitialised — driver not
yet loaded; will become Mem+ BM+ when probe runs), MAbort-, no
modules loaded.

**Polling pattern (boot -1, set_active at 01:10:43):** The 22
landed pairs always read `sharedram_ptr=0xffc70038` (NVRAM marker,
unchanged from pre-set_active). The expected `t+120000ms` poll
never landed (wedge cut journal at 01:12:24 — ~22 s before that
line was due, same wedge bracket as test.238).

**Why this matters — branches the post-set_active model:**
1. **Fw IS executing for ≥90 s** (poll-readback never went
   `0xffffffff`, no MAborts; wedge model "bus crash at t+1s" was
   already refuted in test.237/238 and is freshly reconfirmed).
2. **Fw is NOT advancing through upstream's normal init path.**
   Upstream brcmfmac waits up to `BRCMF_PCIE_FW_UP_TIMEOUT=5000ms`
   for fw to overwrite TCM[ramsize-4] with `sharedram_addr`. In
   test.239 we waited 18× that and fw still hadn't done it.
3. **Fw is stuck in a pre-shared-alloc loop** — likely waiting on
   either (a) a host-side handshake / doorbell signal, or
   (b) chip-internal initialization that legitimately takes
   longer than upstream's 5 s but eventually fires its own
   panic/watchdog around t+100-120 s.

**Decision-tree branch hit:** PRE-TEST.239 pre-committed:
*"sharedram_ptr stays 0xffc70038 through last landed dwell → Test.240:
add a host 'HostRDY' doorbell ring (H2D_MAILBOX_0 or equivalent)
during an early dwell to see if fw is blocked on host handshake."*
That is the directly-pre-committed next step.

**Caveats / alternative readings to consider for test.240 design:**
- Polling itself was a single `brcmf_pcie_read_ram32` per dwell —
  zero-side-effect MMIO reads should not have masked any fw state
  change, but this is also the first run where we touched BAR2 inside
  the dwell loop; if it somehow disturbed fw, the right control is
  test.238 baseline (no polling) — already on file.
- It is also possible fw allocates `sharedram_addr` somewhere
  *other* than upstream's documented slot — but we've never seen
  any upstream variant or BCM-driver code use a different slot.

**Hardware state (current, 07:42 BST boot 0):** `lspci -s 03:00.0`
shows `Mem- BusMaster-` (device disabled because no driver loaded;
this is normal post-SMC-reset before insmod). MAbort-, DEVSEL=fast.
No modules loaded. SMC reset performed between test.239 wedge and
current boot.

---

## Prior outcome (test.238 — wedge bracketed to [t+90s, t+120s] post-set_active)

Test.238 ran the same ultra-extended dwell ladder out to t+120s
without polling sharedram. Result was 22 of 23 dwell breadcrumbs
landed (t+100ms..t+90000ms), missing only `t+120000ms dwell`. That
established the wedge bracket [t+98s, t+118s] (lower bound from
host-CPU activity 7+ s past last brcmfmac line; upper bound from
~15-20 s journald tail-truncation budget). See **POST-TEST.238**
block below for full evidence and ladder timestamps. Test.239 ran
on the same ladder + the new sharedram_ptr poll; the wedge bracket
is unchanged (last landed line at the same t+90 s position with the
same wedge window).

---

**Prior outcome (test.234):** Test wedged. Same tail-truncation
pattern as test.231/232. Last journald line at 23:12:50 BST was
`BCM4360 test.158: BusMaster cleared after chip_attach` — that's
inside `brcmf_pcie_attach` BEFORE `brcmf_pcie_download_fw_nvram`
even starts. **Zero test.234 breadcrumbs landed in journald** (no
PRE-ZERO scan, no zeroing log, no verify, no set_active call/return,
no dwells). The retained test.233 PRE-READ continuity log also
didn't land. So we cannot tell from this run alone whether:
- the zero loop ran or completed
- set_active was called
- the wedge point shifted relative to test.231/232

This is the **expected** journald blackout behavior (tail loss
~15-20s) and matches every prior set_active-enabled run. Host had
to be SMC-reset + rebooted (~28 min downtime). PCIe state on this
boot (boot 0, started 23:41:20 BST) is clean — Mem+ BusMaster+,
MAbort-, CommClk+. No pstore (watchdog frozen by bus stall, as before).

**Conclusion forced by this run:** test.234 cannot be interpreted
on its own. We need a logging transport that survives the wedge
window. Per test.233, TCM survives within-boot SBR+rmmod+insmod
(Run 2) but is wiped by SMC reset (Run 3). And we *always* need
SMC reset to recover from the wedge. So the next test must
**decompose** the experiment into observable pieces — at minimum,
a test.235 that runs the zero+verify path **without** set_active
(test.230 baseline) so we can confirm the zero loop works at all,
then a separate run that adds set_active back. Detailed plan in
PRE-TEST.235 (next).

---

**Prior outcome (test.233):** TCM persistence probe answered the
advisor-blocking question. 3 runs on test.230 baseline (set_active
SKIPPED, no wedge). Wrote 0xDEADBEEF/0xCAFEBABE magic to
TCM[0x90000/4] in each run, pre-read the same offsets at probe
entry:

| Run | Context | Pre-read | Interpretation |
|---|---|---|---|
| 1 | fresh post-SMC-reset boot | 0x842709e1 / 0x90dd4512 | **non-zero** residue — fingerprint-like |
| 2 | same boot, after rmmod | 0xDEADBEEF / 0xCAFEBABE | **MATCH** — TCM survives SBR + rmmod/insmod within boot |
| 3 | post-SMC-reset + reboot | 0x842709e1 / 0xb0dd4512 | magic GONE; near-identical to Run 1 baseline |

**Binary conclusion:** SMC reset + reboot wipes our magic.
**TCM ring-buffer logger is NOT viable for cross-SMC-reset data
retention** — and every wedge in this investigation has required an
SMC reset to recover. So TCM logger can't carry wedge-timing data
through the recovery path we actually use.

**Side observations worth keeping:**
- Run 2 confirmed TCM persists across rmmod/insmod + probe-start
  SBR. If a wedge ever leaves host recoverable without SMC reset,
  the logger *would* help — but that hasn't happened in any test.
- Run 1 and Run 3 pre-reads are near-identical (one word byte-
  identical, one word off by one bit). These are NOT zeros or
  all-0xFF — they look like a deterministic SRAM/fingerprint
  pattern or residue of an early init routine that runs fresh on
  each SMC-reset boot. Offset 0x90000 is past fw image (0..0x6bf78)
  and before NVRAM (0x9ff1c), so our code never writes there in
  normal flow. Could be a BCM4360 SRAM power-on signature.

**Pivot: shared-memory struct forward step.** With TCM logger ruled
out as the timing transport, the path advisor already identified
as the natural next step becomes primary: study upstream brcmfmac's
`brcmf_pcie_init_share` + PCIE2 ring infrastructure, then build a
minimal shared-memory struct in TCM BEFORE `brcmf_chip_set_active`
so that when fw activates, it has valid DMA targets to dereference.
This is both a discriminator (if wedge stops or shifts, we've found
the missing piece) and a forward step regardless of logging.

**Prior fact (test.232):** BM=OFF did NOT prevent the wedge, so
pure DMA-completion-waiting theory is falsified. Wedge may still
be DMA-rooted via fw's reaction to UR responses (AXI fault, retry
storms, pcie2 bring-down internally), but it's not plain
completion-starvation.

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
| Wedge is pure DMA-completion-starvation (fw stalls waiting for response to TLP with bad host address) | 232 | ruled out — BM=OFF forces UR responses instead of completion-waiting, host still wedged |
| TCM ring-buffer logger viable across wedge recovery | 233 | ruled out — TCM magic survives within-boot SBR+insmod (Run 2) but wiped by SMC reset + reboot (Run 3) — every wedge-recovery in this investigation used SMC reset |
| Wedge caused by fingerprint values in [0x9FE00..0x9FF1C) (cheap tier) | 234, 235 | ruled out — zeroing the region did not prevent test.234's wedge |
| Fw-wedge independent of Apple random_seed footer presence | 236 | ruled out — writing `magic=0xfeedc0de` + 256-byte buffer at [0x9FE14..0x9FF1C) shifts the wedge noticeably later: fw reaches ≥t+700ms post-set_active, vs. test.234's pre-fw-download cutoff |
| Wedge is instantaneous at/near set_active return (sub-second) | 237 | ruled out — with seed present and an extended msleep ladder, fw runs ≥25 s post-set_active; dwells at t+100..t+25000ms all landed live, driver thread schedulable throughout. |
| Wedge is a fw-timeout at ~t+30 s (Model A from PRE-TEST.238) | 238 | ruled out — fine-grain 1 s ladder through [t+25..t+30 s] all landed; dwells at t+35, 45, 60, 90 s all landed. Wedge is not near t+30 s. |
| Wedge happens within ~t+40-45 s of set_active (Model B from PRE-TEST.238) | 238 | ruled out — `t+60 s dwell` and `t+90 s dwell` both landed live. True wedge window is [t+90 s, t+120 s]. |
| Fw completes shared-struct init before wedge (i.e. writes `sharedram_addr` to TCM[ramsize-4]) | 239 | ruled out — 22 consecutive polls at t+100ms..t+90s all returned the pre-set_active NVRAM marker `0xffc70038`. Fw is executing for ≥90s but has not reached / not exited the step that normally overwrites this slot. |

**Refined wedge model (post test.230):**
The moment ARM CR4 starts executing firmware (rstvec written via
`brcmf_chip_set_active`), something happens on the PCIe bus within
~1 s that freezes every CPU that touches the chip or the shared
PCIe domain — including the watchdog CPU. All pre-set_active work
(FORCEHT, pci_set_master, 442 KB fw download, NVRAM write, TCM verify)
is now proven safe.

**Strong candidate — fw blocked on host handshake:**
Test.239 direct evidence is that fw never advances to the normal
shared-struct-allocation step within ≥90 s post-set_active (upstream
timeout for this is 5 s). Either fw is waiting on a host-side action
we've never issued, or fw is in a chip-internal stall that eventually
self-panics at ~t+100-120 s. The cheapest-first probe is to ring the
upstream "HostRDY" doorbell (H2D_MAILBOX_1, value 1), or more
generally write to PCIE2 H2D_MAILBOX_0/1 during an early dwell and
observe whether fw reacts (sharedram_ptr changes, wedge shifts,
wedge disappears). Pre-committed as test.240 in PRE-TEST.239's
decision tree.

**Next test direction (test.240):**
Small code change on top of test.239: write to one of H2D_MAILBOX_0
(0x140) or H2D_MAILBOX_1 (0x144) at an early dwell breadcrumb
(e.g. t+1500ms) while continuing to poll `sharedram_ptr` at every
dwell. If fw was blocked on host doorbell, sharedram_ptr will
change to a non-marker value within some dwell after the doorbell.
If nothing changes and the wedge is identical to test.239, the
"host handshake missing" branch is weakened and we pivot to the
shared-struct pre-allocation (upstream `brcmf_pcie_init_share`-
style) path. Implementation must be sanity-checked before insmod:
advisor call required to settle whether to ring DB1 (upstream's
hostready slot) or DB0 (general mailbox) and whether additional
seed-time preconditions are needed.

**Logging transport status (updated after test.233):**
- journald: drops ~15–20 s of tail when host loses userspace (confirmed tests 226/227/231/232).
- pstore: doesn't fire — bus-wide stall freezes watchdog CPU (tests 227/228/229).
- netconsole: user declined second-host setup.
- **TCM ring buffer: ruled out** — TCM magic wiped by SMC reset +
  reboot (test.233 Run 3). Survives within-boot rmmod/insmod (Run 2),
  but every wedge in this investigation has required an SMC reset.
- `earlyprintk=serial`: `/dev/ttyS0..3` exist but MacBook has no
  exposed port — likely bit-bucket without USB-serial adapter.

Logging for test.234 falls back to journald tail-truncation as
before. Resolution ≥15-20 s is fine because the goal is shape-
comparison (does the wedge still happen? at the same place?),
not sub-second timing.

---


## POST-TEST.239 (2026-04-23 01:12 BST, boot -1 — same wedge bracket as test.238; sharedram_ptr held `0xffc70038` for all 22 polls) — fw never advanced to shared-struct allocation

### Summary

`bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1
bcm4360_test239_poll_sharedram=1`. Probe ran cleanly through fw
download, NVRAM write, seed write (footer at 0x9ff14, magic
0xfeedc0de, len 0x100), FORCEHT, `pci_set_master`, and
`brcmf_chip_set_active` (returned TRUE at 01:10:43.523 BST). Ladder
emitted **22 dwell+poll pairs** at t+100, 300, 500, 700, 1000, 1500,
2000, 3000, 5000, 10000, 15000, 20000, 25000, 26000, 27000, 28000,
29000, 30000, 35000, 45000, 60000, 90000 ms (last line 01:12:15
BST). The expected `t+120000ms` pair never landed; journal cut at
01:12:24 (~22 s before that breadcrumb was due). Host wedged; SMC
reset performed by user; current boot 0 started 07:41:38 BST.

### sharedram_ptr poll results

**All 22 polls returned `0xffc70038`** — identical to the NVRAM
length marker our host writes at TCM[ramsize-4] before set_active.
Fw never overwrote that slot during the ≥90 s window. No transient
to a valid RAM address, no `0xffffffff` (no bus-error read), no
garbage value.

```
Apr 23 01:10:43 test.238: t+100ms dwell
Apr 23 01:10:43 test.239: t+100ms sharedram_ptr=0xffc70038
Apr 23 01:10:44 test.238: t+300ms dwell
Apr 23 01:10:44 test.239: t+300ms sharedram_ptr=0xffc70038
... (every pair identical pattern; sharedram_ptr never changes) ...
Apr 23 01:12:15 test.238: t+90000ms dwell
Apr 23 01:12:15 test.239: t+90000ms sharedram_ptr=0xffc70038
<journal ends 01:12:24 — host wedged in [t+90s, t+120s] window>
```

### Key interpretations

1. **Wedge bracket unchanged from test.238** — same [t+98s, t+118s]
   window. So the addition of one MMIO read per dwell did NOT
   destabilise fw or shift the wedge (rules out the
   "polling-causes-wedge" branch from PRE-TEST.239 decision tree).
2. **Fw does not progress through normal init** — upstream brcmfmac's
   `BRCMF_PCIE_FW_UP_TIMEOUT` is 5 s. We waited 18× that. Fw never
   wrote `sharedram_addr` to TCM[ramsize-4]. So fw is either:
   - blocked on a host-side handshake (no doorbell, no IRQ, no
     write to a polling-watched slot by the host), or
   - executing an unrelated internal init that completes (or
     panics) at ~t+100-120s, which then wedges the bus.
3. **Wedge is not an early bus event** — every poll at t<90s read
   the BAR2 window cleanly (returned the marker, never `0xffffffff`).
   So PCIe is healthy throughout fw's ≥90 s execution.
4. **Decision-tree branch hit:** PRE-TEST.239 pre-committed
   *"sharedram_ptr stays 0xffc70038 → Test.240: HostRDY doorbell ring"*.
   That is the next action.

### Caveats

- We did not measure whether fw writes anywhere ELSE in TCM —
  only TCM[ramsize-4]. Fw could be advancing through some other
  state machine that doesn't touch this slot. Test.240 may want to
  spot-check a few other tail-TCM addresses too.
- `brcmf_pcie_read_ram32` uses BAR2 window MMIO. Same op already
  proven safe in tests 188/218/226. Not a new risk.

### Artifacts

- `phase5/logs/test.239.run.txt` — PRE harness output (truncated at
  "sleeping 240s" because host wedged during sleep)
- `phase5/logs/test.239.journalctl.full.txt` (1458 lines) — full
  boot -1 journal
- `phase5/logs/test.239.journalctl.txt` (387 lines) — filtered
  BCM4360 / brcmfmac subset

---


## PRE-TEST.239 (2026-04-23 00:5x BST, boot 0 post-SMC-reset from test.238) — poll TCM[ramsize-4] at every ladder breadcrumb to observe whether fw writes `sharedram_addr` before the wedge

### Hypothesis

Test.238 proved fw+driver run for ≥90 s post-set_active with the
Apple random_seed present. The wedge window is [t+98 s, t+118 s].
During those ~100 seconds, fw is executing *something* — but we
have no visibility into what.

**Upstream brcmfmac convention** (confirmed in pcie.c@3144-3158):
- Host writes NVRAM → TCM[ramsize-4] = 0xffc70038 (NVRAM length
  marker token).
- Fw boots, parses NVRAM, inits PCIe2 internals, allocates its
  `pcie_shared` struct in its own TCM/scratch, then
  **overwrites TCM[ramsize-4] with the address of that struct**
  (`sharedram_addr`).
- Host detects the change (value ≠ 0xffc70038) and reads the
  struct at that address to bootstrap ringinfo / console /
  mailboxes.

We have never observed this value *during* the dwell ladder. If
fw is functional post-set_active, the sharedram_addr write should
happen at some t* ∈ (0, wedge] — and knowing its timing plus
the address fw hands us is highly diagnostic:

| Observation at ramsize-4 during the ladder | Interpretation |
|---|---|
| Stays at 0xffc70038 through t+90 s | Fw is running (dwells landed) but **has not completed its shared-struct init** — possibly stuck at a pre-alloc step, or waiting on host signal. |
| Changes to a valid RAM address at some t* | Fw completed shared-struct init at t*; we now know (a) fw boots correctly up to that step, (b) WHERE its pcie_shared struct lives → we can read ringinfo/console from that address on subsequent tests. |
| Changes to 0xffffffff (all-ones) | Bus error on the readback, not a fw write — indicates device disappeared from PCIe bus at that point. |
| Changes to a bogus value (e.g. 0x0, or address outside RAM) | Fw wrote something, but its internal state is inconsistent; likely this path diverges before sharedram alloc completes. |

This is a **zero-intervention observation test** — we only READ
TCM during dwells, no writes. No new hypothesis about fw expected
behaviour; just instrumentation of an already-documented protocol.

### Why polling, not sentinel-write (per prior advisor)

Advisor proposed writing a sentinel (e.g. 0xdeadbeef) at ramsize-4
before set_active to test whether fw reads from that slot. But the
upstream flow is **fw WRITES there, not reads** — the NVRAM marker
0xffc70038 already sits there (host writes it via NVRAM). Fw is
documented to overwrite, not dereference, that slot on init. So
polling is strictly more informative and costs nothing extra (just
a single MMIO read per dwell line vs. a full pre-set_active write
that fw will clobber anyway). Sentinel-write is strictly inferior
here.

### Code change

1. New module param `bcm4360_test239_poll_sharedram` (default 0).
2. In the test.238 ladder, after each `pr_emerg("... dwell\n")`,
   if `test239_poll_sharedram` is set, perform:
   ```c
   u32 v = brcmf_pcie_read_ram32(devinfo, devinfo->ci->ramsize - 4);
   pr_emerg("BCM4360 test.239: t+Xms sharedram_ptr=0x%08x\n", v);
   ```
   Emit one breadcrumb per ladder step (23 lines total alongside
   the 23 dwell lines).
3. Keep everything else identical — same ultra ladder, same seed,
   same pre-set_active path.

### Run sequence

```bash
# Build first
make -C phase5/work

# Then, this boot (after SMC-reset post-test.238):
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Budget 240 s per test.238 precedent. Sysctls nmi_watchdog=1,
hardlockup_panic=1, softlockup_panic=1 armed as before.

### Pre-committed test.240 decision tree (per advisor)

Before running test.239, here's what each outcome branches to —
pre-committed to avoid post-hoc "consistent with plan" bias:

| Test.239 observation | Test.240 direction |
|---|---|
| sharedram_ptr stays 0xffc70038 through last landed dwell | Fw boots but never reaches shared-struct allocation. Test.240: add a host "HostRDY" doorbell ring (H2D_MAILBOX_0 or equivalent) during an early dwell to see if fw is blocked on host handshake. |
| sharedram_ptr changes to a valid RAM address at t=T* | Fw completed shared-struct init at T*. Test.240: read the pcie_shared struct from that address, log its fields (ring_info_addr, console_addr, mailbox addrs) and share-magic. No fw change needed — pure observation, should be clean. |
| sharedram_ptr changes to 0xffffffff | Bus error reading the slot (device disappeared from BAR2 window). Test.240: narrow when the bus-error condition starts by cross-referencing with last landed dwell; investigate PCIe config space post-test. |
| sharedram_ptr changes to a non-RAM non-marker non-all-ones value | Fw wrote garbage. Test.240: inspect what it wrote — could be a bug in our test, a chip quirk, or a firmware internal that overwrites the slot for different reasons. Read nearby TCM to see if a struct was written. |
| Wedge moves EARLIER than test.238 (< t+90s) | Polling destabilises the bus during fw run (advisor's H2). Test.240: reduce poll frequency (only at t+10, 30, 60, 90 s) to confirm the dose-response; if wedge moves with poll count, polling itself is the cause. |
| Wedge moves LATER (> t+118 s) | Polling somehow buys fw time — the read MMIO may act as a heartbeat to fw. Test.240: deliberately add extra reads spaced through the ladder to see if wedge recedes further. |

### Safety — MMIO read during dwells

`brcmf_pcie_read_ram32` uses BAR2 window access — pure read, no
side effects. Test.188/test.226/test.218 already demonstrate
repeated TCM reads inside the probe are safe. One extra read per
dwell point is within the noise of existing activity.

### Hardware state (current, 00:55 BST boot 0 post-SMC-reset)

- `lspci -vvv -s 03:00.0`: Control Mem+ BusMaster+, MAbort-, fast.
- **BAR0 timing PRE**: reads cleanly (dword `0x203a6464` via dd
  against resource0). The I/O error recorded in test.238's PRE
  was a one-off, not a persistent issue — current boot is clean.
- No modules loaded.

### Build status — REBUILT CLEAN

Built 2026-04-23 ~00:57 BST via
`make -C $KDIR M=phase5/work/drivers/.../brcmfmac modules`.
`strings brcmfmac.ko | grep test.239` shows all 23 breadcrumbs
(t+100ms..t+120000ms sharedram_ptr=%08x) plus the new module
param `bcm4360_test239_poll_sharedram`. Pre-existing
unused-variable warnings only — no regressions.

### Expected artifacts

- `phase5/logs/test.239.run.txt` — PRE harness + insmod output
- `phase5/logs/test.239.journalctl.full.txt` — full boot -1 journal
- `phase5/logs/test.239.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: PENDING — make + strings verify before insmod.
2. PCIe state: clean post-SMC-reset above.
3. Hypothesis: stated above.
4. Plan: in this block; commit+push+sync before insmod.
5. Filesystem sync on commit.

---


## POST-TEST.238 (2026-04-23 00:55 BST, boot -1 — wedged in [t+90 s, t+120 s] post-set_active; SMC reset required) — 22 of 23 breadcrumbs landed, fw runs ≥90 s under seed

### Summary

Test.238's ultra-extended ladder ran with `bcm4360_test236_force_seed=1`
and `bcm4360_test238_ultra_dwells=1`. Probe executed fw download, NVRAM
write, seed write, FORCEHT, `pci_set_master`, and `brcmf_chip_set_active`
cleanly. `set_active` returned TRUE. The 23-step post-set_active ladder
then landed **22 breadcrumbs** (t+100, 300, 500, 700, 1000, 1500,
2000, 3000, 5000, 10000, 15000, 20000, 25000, 26000, 27000, 28000,
29000, 30000, 35000, 45000, 60000, 90000 ms) before the journal cut
at 00:52:24 BST. Missing only `t+120000ms dwell` (expected at
00:52:46, ~22 s after the cut) and all post-dwell lines.

Host wedged. User performed SMC reset; current boot 0 started
00:54:07 BST clean.

### Evidence (boot -1 tail, from `journalctl -b -1 -k`)

```
Apr 23 00:50:46 test.238: calling brcmf_chip_set_active resetintr=0xb80ef000 (ultra-extended ladder t+120s)
Apr 23 00:50:46 test.65  activate: rstvec=0xb80ef000 to TCM[0]; CMD=0x0006
Apr 23 00:50:46 test.238: brcmf_chip_set_active returned TRUE
Apr 23 00:50:46 test.238: t+100 / 300 / 500 / 700 / 1000 / 1500 / 2000 / 3000 / 5000 ms  (batched)
Apr 23 00:50:50 test.238: t+10000ms dwell
Apr 23 00:50:55 test.238: t+15000ms dwell
Apr 23 00:51:00 test.238: t+20000ms dwell
Apr 23 00:51:05 test.238: t+25000ms dwell
Apr 23 00:51:06 test.238: t+26000ms dwell
Apr 23 00:51:07 test.238: t+27000ms dwell
Apr 23 00:51:08 test.238: t+28000ms dwell
Apr 23 00:51:09 test.238: t+29000ms dwell
Apr 23 00:51:10 test.238: t+30000ms dwell
Apr 23 00:51:15 test.238: t+35000ms dwell
Apr 23 00:51:25 test.238: t+45000ms dwell
Apr 23 00:51:41 test.238: t+60000ms dwell
Apr 23 00:52:11 test.238: t+90000ms dwell         ← last test.238 line of boot -1
<then only non-BCM4360 traffic (wlp0s20u2 wlan) through 00:52:24 — journal ends>
```

Live timestamps through t+90s prove the driver thread was
schedulable and the kmsg flush path healthy for ≥90 s
post-set_active. No Oops, no Call Trace, no watchdog fire, no
softlockup backtrace in boot -1.

### Key interpretations

1. **Rewrites test.237:** the `t+25000ms dwell` line we had treated
   as the wedge-adjacent breadcrumb was not the wedge moment at
   all. Test.238 shows t+25 through t+90 s all land cleanly, so
   test.237's shorter ladder simply didn't have breadcrumbs past
   t+30 s to print. Test.237's journal cut was tail-truncation or
   rmmod-phase artefact, not wedge timing.
2. **Wedge window [t+90 s, t+120 s]:** directly bounded — t+90 s
   landed live, t+120 s did not and would have logged at 00:52:46,
   ~22 s past the 00:52:24 journal cut.
3. **Fw has a late trigger** — the deadline is ~100–120 s, ~4–5×
   longer than anything test.237 saw. Compatible with:
   - Internal fw watchdog expiring after 3–4 periods of a 30 s tick.
   - One-shot fw timer (~100 s) firing DMA-read of an
     uninitialised shared-memory pointer (pcie_shared /
     ringinfo / console / mailbox).
   - Fw heartbeat expecting host ring-back after N intervals.

### Observations worth keeping

- **No softlockup panic** despite 3 long msleeps (30 s, 30 s, 30 s)
  in the ladder; `softlockup_panic=1` + `softlockup_all_cpu_backtrace=1`
  didn't fire, which confirms the driver thread was yielding and
  the *host* CPUs weren't stalled during the 90 s run. Wedge must
  hit somewhere between 00:52:11 and 00:52:24, and kills the bus
  fast enough that host journald can't flush any wedge-witness
  lines.
- `BAR0 timing PRE` showed `dd: Input/output error` — but `lspci`
  PRE showed `Mem+ BusMaster+ MAbort-`. Likely the BAR0 raw dd was
  tripping on an earlier boot-0 condition that didn't prevent the
  probe from running (insmod proceeded to completion).
- The batched-at-00:50:46 cluster (t+100 … t+5000 ms) vs the live
  per-second flush from t+10 s onwards matches prior journald
  flush dynamics; not wedge-relevant.

### Artifacts

- `phase5/logs/test.238.run.txt` — PRE capture + insmod + "sleeping 240s"
  (truncated because host wedged during sleep)
- `phase5/logs/test.238.journalctl.full.txt` (1438 lines) — full
  boot -1 journal
- `phase5/logs/test.238.journalctl.txt` (378 lines) — filtered
  BCM4360/brcmfmac/watchdog subset

---


## PRE-TEST.238 (2026-04-23 00:4x BST, boot 0 post-SMC-reset from test.237) — ultra-extended dwell ladder to t+120s with 1s fine-grain through [t+25..t+30s] window

### Hypothesis

Test.237 bounded the wedge moment to [t+25s, t+40-45s]. Two
very-different mechanisms fit the evidence:

**A. "Fw fixed timeout at ~t+30s"** — journal was flushing live by
t+10s (per-second timestamps for t+10/15/20/25), so tail-truncation
was likely seconds at most. Wedge would be at t+30s ±1-2s. Mechanism:
fw waits N seconds for some host-side response (IRQ / doorbell /
shared-struct read) then fires an internal trap/watchdog.

**B. "Wedge is later (≥t+40s), full tail-truncation"** — if the
kernel buffer pressure came back at wedge time, the ~15-20s budget
applies and the actual wedge could be at t+40-45s. Mechanism:
similar to A but different deadline.

Both models predict fw wedges the PCIe bus eventually; but the exact
deadline matters for whether we're racing a fw watchdog vs. a fw
heartbeat timer vs. something else.

**Discriminator:** run a ladder that is fine-grain through
[t+25..t+30s] (1s steps) AND extends to t+120s. Expected patterns:

| Last landed breadcrumb | Interpretation |
|---|---|
| t+26/27/28/29/30s cuts (e.g., t+28 lands, t+29 doesn't) | **Model A confirmed** — fw timeout bracket. Pivots plan to "build shared-struct fast enough to race the timeout" |
| t+30s lands, cuts in [t+35..t+45s] | **Model B (timeout slightly later)** — still within the set_active-tripped bus-crash model, ~5s slack |
| Lands past t+45s (e.g., t+60 lands, t+90 cuts) | Wedge is NOT fixed-timeout; possibly conditional on a future host action (e.g., `rmmod`) or intermittent |
| All 23 breadcrumbs land + clean BM-clear + -ENODEV | **Extraordinary** — long wait somehow avoids the wedge (maybe fw self-heals if untouched long enough?) |

### Code change

1. New module param `bcm4360_test238_ultra_dwells` (default 0).
2. New `else if` branch before test.237 in the set_active chain.
   Ladder: t+100, 300, 500, 700, 1000, 1500, 2000, 3000, 5000, 10000,
   15000, 20000, 25000, 26000, 27000, 28000, 29000, 30000, 35000, 45000,
   60000, 90000, 120000 ms (23 post-set_active breadcrumbs).
3. Existing test.235, test.237, test.234 paths preserved.

### Run sequence

```bash
# single run this boot
sudo insmod phase5/work/.../brcmutil.ko
sudo insmod phase5/work/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1
# ladder runs ~121 s post-set_active; probe return adds ~1 s
sleep 240
# host may be wedged; if so, SMC reset
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Budget is 2× max dwell (advisor). Sysctls: nmi_watchdog=1,
hardlockup_panic=1, softlockup_panic=1, softlockup_all_cpu_backtrace=1.

### Hardware state (boot 0, post-SMC-reset)

- Boot 0 started 2026-04-23 00:35:43 BST.
- `lspci -vvv -s 03:00.0`: Control Mem+ BusMaster+, MAbort-, fast-UR.
- No modules loaded. Clean post-SMC-reset idiom.

### Build status — REBUILT CLEAN

`brcmfmac.ko` rebuilt 2026-04-23 ~00:4x BST. `strings` confirms
`bcm4360_test238_ultra_dwells` module param + all 23 new test.238
breadcrumbs. Pre-existing unused-variable warnings unchanged.

### Expected artifacts

- `phase5/logs/test.238.run.txt` — PRE + harness output
- `phase5/logs/test.238.journalctl.full.txt` — full boot journal
- `phase5/logs/test.238.journalctl.txt` — filtered subset

### Pre-test checklist (CLAUDE.md)

1. Build status: REBUILT CLEAN above.
2. PCIe state: clean per above.
3. Hypothesis: bracket fw-timeout vs. late-wedge (A vs. B), above.
4. Plan: in this block; commit+push+sync before insmod.
5. Filesystem sync on commit.

---




## Older test history

Full detail for tests prior to test.228 → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
