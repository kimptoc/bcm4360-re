# Phase 5: brcmfmac BCM4360 Support

## Approach

Patch the upstream `brcmfmac` kernel driver to add BCM4360 (PCI ID 14e4:43a0)
support. The firmware is PCI-CDC FullMAC (identified in Phase 4), which is
exactly what brcmfmac expects.

## Discovery: brcmfmac never supported BCM4360

No `BRCM_CC_4360_CHIP_ID`, `BRCM_PCIE_4360_DEVICE_ID`, or firmware mapping
existed in the kernel. The BCM4360 fell in a gap — too new for b43/brcmsmac
(SoftMAC drivers), never added to brcmfmac's PCI table. Only `bcma` claimed
the PCI ID, acting as a bus driver without a wireless driver on top.

The kernel module alias table confirms: `pci:v000014E4d000043A0` → `bcma` only.

## Patches applied (3 files)

### brcm_hw_ids.h
- Added `BRCM_CC_4360_CHIP_ID` (0x4360)
- Added `BRCM_PCIE_4360_DEVICE_ID` (0x43a0)

### pcie.c
- Added `BRCMF_FW_DEF(4360, "brcmfmac4360-pcie")`
- Added `BRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360)`
- Added `BRCMF_PCIE_DEVICE(BRCM_PCIE_4360_DEVICE_ID, WCC)`
- Added BCM4360 to enter/exit download state handlers (same as 43602 — ARM CR4)

### chip.c
- Added `BRCM_CC_4360_CHIP_ID` to `brcmf_chip_tcm_rambase()` → 0 (fixed from initial 0x180000)

## Test 1: Module load and probe (2026-04-14)

### Result: PARTIAL SUCCESS — firmware loaded, crash in setup

```
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3
brcmfmac 0000:03:00.0: Direct firmware load for brcm/brcmfmac4360-pcie.Apple Inc.-MacBookPro11,1.bin failed with error -2
```

Key observations:
1. **brcmfmac recognized BCM4360** — chip ID 0x4360, rev 3
2. **Firmware loaded successfully** — used `brcmfmac4360-pcie.bin`
3. Platform-specific firmware (`Apple Inc.-MacBookPro11,1.bin`) not found (expected)
4. CLM blob and txcap blob not found (non-fatal)

### Crash in brcmf_pcie_setup

```
BUG: unable to handle page fault for address: ffffd3f8c141fffc
Oops: 0002 [#1] PREEMPT SMP PTI
RIP: 0010:iowrite32+0x10/0x40
Call Trace:
  brcmf_pcie_setup+0x1d2/0xda0 [brcmfmac]
  brcmf_fw_request_done+0x148/0x190 [brcmfmac]
```

The crash is a page fault during `iowrite32` in `brcmf_pcie_setup`. The driver
is writing to TCM (likely the NVRAM placement at end of RAM) but the target
address is outside the mapped region.

RAX=0x180000 (RAM base), faulting address is an ioremap'd address that's past
the end of the BAR2 mapping.

### Analysis

The `brcmf_pcie_setup` function writes NVRAM to `rambase + ramsize - nvram_len`.
If `brcmf_chip_tcm_ramsize()` returns an incorrect value (due to CR4 capability
register reads returning bad data on the flaky PCIe link), the write offset
could be past the end of the mapped BAR.

Alternatively, BCM4360's TCM layout may differ from 43602 — the RAM base is
correct (0x180000) but the BAR2 mapping size may not cover the full TCM range.

### Next steps

1. ~~Add debug prints to capture ramsize, rambase, and BAR2 mapping range~~ ✅ done
2. ~~Compare with Phase 4 findings~~ ✅ rambase fixed to 0
3. ~~May need to add BCM4360-specific ramsize override if auto-detection fails~~ — TBD

## Fix 1: rambase=0 (commit d872ae2)

Phase 4 proved BAR2 maps TCM directly at offset 0 (no 0x180000 offset).
Changed `brcmf_chip_tcm_rambase()` for `BRCM_CC_4360_CHIP_ID` to return 0.

## Fix 2: Replace memcpy_toio with 32-bit iowrite32 writes

Phase 3/4 proved BCM4360 hangs on 64-bit `rep movsq` (which x86 `memcpy_toio`
uses). Added `brcmf_pcie_copy_mem_todev()` helper in `pcie.c` — a 32-bit
`iowrite32` loop with trailing-byte handling.

Replaced all `memcpy_toio` calls in the firmware download path:
- Firmware data write (fw->data, ~442KB)
- NVRAM write
- Random seed footer write
- Random bytes write

One `memcpy_toio` remains in the msgbuf ring setup path (line ~1334) — this
won't be reached until after ARM release, and will likely fail anyway since
BCM4360 firmware speaks BCDC not msgbuf.

### Expected test result

Firmware download should complete without page fault or PCIe hang. After ARM
release, the msgbuf handshake will timeout (BCM4360 FW speaks BCDC). That
timeout is expected and non-fatal — it proves the firmware loaded correctly.

## Test 2: After rambase=0 + iowrite32 fix (2026-04-14)

### Result: CRASH — NULL pointer in brcmf_chip_resetcore

```
BUG: kernel NULL pointer dereference, address: 0x0000000000000020
RIP: 0010:brcmf_chip_resetcore+0xa/0x20 [brcmfmac]
Call Trace:
  brcmf_pcie_setup.cold+0x61e/0xb9c [brcmfmac]
```

Firmware download completed successfully (no page fault or PCIe hang).
Crash in `brcmf_pcie_exit_download_state()`: calls
`brcmf_chip_get_core(BCMA_CORE_INTERNAL_MEM)` which returns NULL for BCM4360
(no INTERNAL_MEM core — that's a BCM43602 thing), then passes NULL to
`brcmf_chip_resetcore`.

## Fix 3: NULL-check INTERNAL_MEM core before resetcore

BCM4360 has ARM CR4 with TCM banks, not a separate SOCRAM/INTERNAL_MEM core.
Added NULL check: `if (core) brcmf_chip_resetcore(core, 0, 0, 0);`

## Test 3: After NULL check fix (2026-04-14)

### Result: SUCCESS — firmware downloaded, ARM released, no crash

```
brcmfmac 0000:03:00.0: BCM4360 debug: BAR0=0xb0600000 BAR2=0xb0400000 BAR2_size=0x200000 tcm=ffffd4a042800000
brcmfmac: brcmf_fw_alloc_request: using brcm/brcmfmac4360-pcie for chip BCM4360/3
brcmfmac 0000:03:00.0: BCM4360 debug: rambase=0x0 ramsize=0xa0000 srsize=0x0 fw_size=442233
brcmfmac 0000:03:00.0: brcmf_pcie_download_fw_nvram: FW failed to initialize
brcmfmac 0000:03:00.0: brcmf_pcie_setup: Dongle setup failed
ieee80211 phy2: brcmf_fw_crashed: Firmware has halted or crashed
```

Key results:
1. **No crash** — no page fault, no PCIe hang, no kernel oops
2. **Firmware downloaded** — 442KB written to TCM at offset 0 via iowrite32
3. **ARM released** — firmware started running
4. **Expected failure: "FW failed to initialize"** — msgbuf handshake timeout

The "FW failed to initialize" is the BCDC-vs-msgbuf protocol mismatch. The
firmware doesn't write back to the shared RAM address because it doesn't
speak the msgbuf protocol. This confirms the Phase 4 finding that BCM4360
firmware uses BCDC.

### What works now

- brcmfmac recognizes BCM4360 (14e4:43a0)
- BAR0/BAR2 mapping correct
- rambase=0, ramsize=0xa0000 (640KB) auto-detected correctly
- Firmware download via 32-bit iowrite32 (no PCIe hang)
- ARM release without host crash
- Module loads/unloads cleanly

## Phase 5.2: Firmware console debugging (tests 3-7)

### Tests 3-6: Incomplete captures

Tests 3-6 captured only the initial firmware load (rambase, ramsize, fw_size)
but no post-ARM-release output. These were intermediate iterations while adding
debug dumps and NVRAM logging to pcie.c.

### Test 7: Firmware ASSERT at hndarm.c:397

The most informative test. Added TCM debug dumps and firmware console extraction.

**Console output decoded:**
```
Found chip type AI (0x15034360)
125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x824d pmurev 17, pmucaps 0x10a22b11
125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
140386.225 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
```

**Analysis:**
1. Firmware boots successfully — identifies BCM4360 chip, initializes ChipCommon
2. `si_kattach` (Silicon Interface kernel attach) completes — BCMA backplane init done
3. Firmware ASSERTs in `hndarm.c:397` ~14.5 seconds after first log (possibly a
   firmware watchdog or timeout)
4. The ASSERT happens during ARM initialization, likely related to:
   - Missing/incorrect NVRAM parameters
   - PCIe DMA/mailbox configuration the firmware expects but we haven't set up
   - A hardware configuration mismatch

**TCM scan results:**
- Shared memory marker at TCM end (0x9fffc) = 0xffc70038 — contains NVRAM footer data,
  not a pcie_shared address → firmware never wrote the msgbuf shared struct
- Console struct found at 0x96f70: buf_addr=0x4000, size=0 (unusual — size should be >0)
- Console text found at 0x96f78 by following `next` pointer at 0x9af94
- pcie_shared candidate at 0x9af90: flags=0xfa — this may be a pre-existing structure
  from firmware's data section, not a runtime-initialized shared memory area

### PC crash note

The last test (test 7 or a subsequent attempt) crashed the PC. This is likely due to
the firmware's ASSERT handler triggering a trap or the ARM entering an undefined state
that corrupts PCIe transactions. The 5-second timeout in `brcmf_pcie_download_fw_nvram`
may not be sufficient to safely handle the crash — the firmware may still be
writing to PCIe-visible memory during the timeout window.

### Uncommitted pcie.c changes

Added debug logging for:
- NVRAM load confirmation (len and TCM write address)
- Warning when no NVRAM is loaded
- Sharedram marker value before ARM release (to verify it's cleared to 0)

### Fix: disable bus mastering before ARM release (uncommitted until now)

Added `pci_clear_master()` before ARM release and `pci_set_master()` after FW
wait completes. This prevents the firmware's ASSERT handler from DMA-ing to host
memory and crashing the PC. Also removed the H2D doorbell hack (was speculative,
didn't help).

## Phase 5.2: Crash investigation (tests 8-11)

### Tests 8-10: All crashed PC
- test.8: PMU logging + ForceHT → **crashed PC** (no log)
- test.9: same as test.8 (commit 3d96dbc) → **crashed PC** (no log)
- test.10: skip watchdog entirely (commit 72235c4) → **crashed PC** (no log)

**Key conclusion:** Crash is NOT caused by watchdog reset — happens regardless.
The PMU/ForceHT register writes added in test.8 are the likely crash trigger.

### Test 11: Safe baseline revert (commit a3dbbb3)
Reverted to test.7 code: read-only PMU, bus mastering disabled, no PMU writes,
no ASPM disable. **Crashed PC.** Journal (recovered from `journalctl -b -1`)
shows all output up to ARM release, then system died abruptly. Log saved to
`phase5/logs/test.11`.

**Critical finding:** Test.7 previously ran without crashing, but the identical
code (test.11) now crashes. This rules out host-side code as the crash cause.
Something environmental changed — possibly PCIe link state, thermal, or
accumulated hardware state from repeated ARM releases across reboots.

### Tests 12a-12b: PCIe safety measures (commits 81afaf3, ba216a1)
- test.12a: skip_arm=1, FW download only → **PASS** (no crash, confirms download is safe)
- test.12b: AER/SERR masking before ARM release → **crashed PC**

### Test 13: Early IRQ handler + INTx disable (commit d1181a8)
- Registered IRQ handler BEFORE ARM release, disabled INTx at PCI config level
- **Crashed PC** — IRQ handler never fired, crash is pre-interrupt

### Test 14: Strip all PCIe safety, bus mastering ON (commit 60574c6)
- Hypothesis: bus mastering disable was the crash cause (added after test.7)
- Stripped ALL PCIe modifications, released ARM with bus_master=ON (EFI default)
- PCI_COMMAND=0x0006 (memory space + bus master enabled)
- **Crashed PC** — log saved to `phase5/logs/test.14`
- Last message: "releasing ARM as-is" then instant death

**Critical conclusion:** Bus mastering hypothesis is WRONG. Tests 11-14 all crash
regardless of PCIe safety measures, bus mastering state, IRQ handlers, or AER masking.
The crash is immediate upon ARM release. Something changed between test.7 (which
worked) and all subsequent tests.

### Crash pattern summary (tests 8-14)

| Test | Bus Master | PCIe Safety | IRQ Handler | Result |
|------|-----------|-------------|-------------|--------|
| 7    | disabled  | none        | none        | **PASS** |
| 8-10 | disabled  | various     | none        | CRASH |
| 11   | disabled  | none (=test.7) | none     | CRASH |
| 12a  | N/A       | skip_arm=1  | none        | PASS  |
| 12b  | disabled  | AER/SERR    | none        | CRASH |
| 13   | disabled  | INTx disable| early IRQ   | CRASH |
| 14   | **ON**    | **none**    | none        | CRASH |

**Every ARM release since test.7 crashes the PC.** The only safe operation is
firmware download without ARM release (test.12a).

### Working hypotheses for crash

1. **Hardware state accumulation:** Repeated ARM releases across reboots may have
   left the BCM4360 in a state that EFI doesn't fully reset. Test.7 worked because
   it was the first ARM release after a cold boot / extended power-off.

2. **Firmware DMA on boot:** The firmware immediately initiates DMA upon ARM release,
   targeting host memory addresses that aren't mapped. With bus mastering ON (test.14),
   this corrupts host memory. With bus mastering OFF (tests 8-13), the PCIe root
   complex rejects the DMA and generates a fatal error.

3. **Missing interrupt/DMA infrastructure:** The firmware expects MSI/MSI-X vectors
   and DMA ring buffers to be configured BEFORE ARM release. Without them, the
   firmware's first PCIe transaction causes a fatal bus error.

## Phase 5.2: Narrowing the crash (tests 15-20)

### Tests 15-18: Hypotheses disproved

| Test | Hypothesis | Mitigation | Result |
|------|-----------|------------|--------|
| 15   | ForceHT needed before ARM | ForceHT set | CRASH |
| 16   | Warm-up needed | Read-only warm-up first | CRASH |
| 16   | PCIe cold/warm state | Cold boot comparison | CRASH |
| 17   | MSI needed before ARM | MSI + IRQ handler | CRASH |
| 18   | Rogue DMA | IOMMU protection | CRASH |

### Test 19: CPUHALT isolation (commit 1ccf441)

**Key finding:** Used CPUHALT bit (0x20) in ARM CR4 IOCTL to keep ARM halted
even after reset-clear. ARM never executed firmware, yet **PC still crashed**.

**Critical conclusion:** The crash is caused by the `brcmf_chip_resetcore()`
register write sequence itself, NOT by ARM firmware execution. The act of
clearing the ARM's reset state (writing to RESET_CTL and IOCTL registers)
triggers a PCIe bus error that kills the host.

### Test 20: Staged reset (commits c6bfdc4, a92a15c)

Broke `brcmf_chip_resetcore()` into individual register writes to find exactly
which one crashes:

- **Stage 0** (read-only ARM CR4 register dump): **PASS** -- reads are safe
  - IOCTL, IOST, RESET_CTL values captured (pre-reset state)
- **Stage 1** (write IOCTL = FGC|CLK = 0x0003): **CRASH**
  - Log shows module loaded, then instant PC death
  - The very first register WRITE to the ARM CR4 core wrapper crashes the host

### Root cause identified

**Writing to the ARM CR4 core wrapper's IOCTL register (offset 0x408) crashes
the PCIe bus.** This is the first step of `brcmf_chip_resetcore()` -- it writes
FGC|CLK to configure the core before clearing reset. Reading the same register
is perfectly safe (stage 0).

This means the BCM4360's ARM CR4 core wrapper registers are NOT writable via
the standard BCMA core wrapper mechanism that works for 43602 and other chips.
The BCM4360 may require:
1. A different core selection/access method
2. Indirect register access via ChipCommon or PMU
3. A specific backplane configuration before core wrapper writes are allowed
4. The reset sequence from the macOS `wl` driver may use a completely different
   register access path

### Updated crash pattern summary (tests 7-20)

| Test | What happened | Result |
|------|---------------|--------|
| 7    | Full ARM release (first time) | **PASS** |
| 8-14 | Various ARM release approaches | CRASH |
| 12a  | FW download only, no ARM | PASS |
| 15-18| Various pre-ARM mitigations | CRASH |
| 19   | CPUHALT (ARM never runs) | CRASH |
| 20.0 | Read ARM CR4 registers | PASS |
| 20.1 | Write IOCTL = FGC\|CLK | **CRASH** |

### Next steps (after test.20)

1. **Examine how `brcmf_pcie_select_core()` works** -- verify the core selection
   is correct for BCM4360 and that the register window is properly mapped
2. **Check what test.7 did differently** -- was it using `brcmf_chip_set_active()`
   which goes through the chip.c abstraction layer? The staged test bypasses
   that and does direct register writes
3. **Trace the macOS wl driver's reset sequence** -- use Phase 3/4 MMIO traces
   to see exactly how the proprietary driver resets the ARM core
4. **Try indirect core access** -- use ChipCommon backplane access registers
   instead of direct core wrapper writes
5. **Power-cycle test** -- full AC power removal to ensure clean hardware state

## Phase 5.2: Isolating the crash trigger (tests 21-25)

### Test 21: chip.c bus ops read path (commit bf4167a)

Rewrote staged reset to use chip.c bus ops path (`buscore_prep_addr`) for correct
wrapbase addressing. Stage=0 was **read-only**: called `brcmf_chip_iscoreup()` which
reads wrapper IOCTL and RESET_CTL via the bus abstraction layer. **Crashed PC.**

**Finding:** Even READ access through the chip.c bus ops path crashes. This rules out
the "test.20 crash was write-specific" interpretation for that code path.

### Test 22: Pure canary (commit bd07eaa) — KEY FINDING

Stage=0 was a pure canary: just `dev_emerg()` and `return 0` from
`exit_download_state`. **No register reads, no chip ops, no core selection.**
**PC still crashed.**

**Critical conclusion:** The crash is NOT in `exit_download_state` code at all.
It is in code that runs AFTER exit_download_state returns 0 — specifically the
FW wait loop in `brcmf_pcie_download_fw_nvram` (line ~1993), which calls
`brcmf_pcie_read_ram32()` every 50ms reading BAR2 offset `ramsize-4`.

The ARM was never released (stage=0 returns 0 before any ARM IOCTL write). The
chip is in download mode (enter_download_state ran), and BAR2 reads to frozen
TCM cause PCIe completion timeouts → host crash.

### Test 23: return -ENODEV (commit c8d9bef)

Stage=0 returned `-ENODEV` from `exit_download_state`. Probe aborts before the
FW wait loop runs. **PC survived.**

**Confirms:** The FW wait loop's BAR2 reads are the crash trigger. Skipping them
entirely is safe.

### Test 24: ASPM hypothesis (commit ec3d358)

Stage=0 disabled PCIe ASPM L0s/L1 before returning 0. Hypothesis: ASPM link
power transitions while reading unresponsive device cause hang. **Crashed PC.**

**ASPM hypothesis disproved.** The crash is not link-state related.

### Test 25: INTERNAL_MEM reset hypothesis (uncommitted)

Stage=0 skipped `brcmf_chip_resetcore(BCMA_CORE_INTERNAL_MEM)` entirely before
returning 0. Hypothesis: INTERNAL_MEM reset makes TCM inaccessible. **Crashed PC.**

**INTERNAL_MEM reset hypothesis disproved.** Log truncated after "Loading brcmfmac"
— crash occurred before any dmesg output, consistent with crash happening in the
wait loop ~50ms after module probe starts (before log flush).

### Consolidated crash pattern (tests 7-25)

| Test | exit_download_state action | Returns | Wait loop runs | Result |
|------|---------------------------|---------|----------------|--------|
| 7    | full ARM release           | 0       | yes            | **PASS** |
| 8-20 | various ARM release attempts | 0    | yes            | CRASH |
| 21   | chip.c read via bus ops    | 0       | yes            | CRASH |
| 22   | canary only (no ops)       | 0       | yes            | CRASH |
| **23** | canary only (no ops)   | **-ENODEV** | **NO**     | **PASS** |
| 24   | ASPM disable + return 0    | 0       | yes            | CRASH |
| 25   | skip INTERNAL_MEM reset    | 0       | yes            | CRASH |

**The decisive variable is whether the FW wait loop runs.** Every test where the
wait loop's BAR2 reads execute crashes the host (except test.7, the first-ever
ARM release where firmware actually ran and responded promptly).

### Root cause (revised)

The FW wait loop reads `tcm + rambase + (ramsize-4)` every 50ms. When firmware
is not running (ARM in reset, or ARM released but firmware ASSERTs quickly),
this BAR2 read causes a PCIe completion timeout, crashing the host. In test.7,
the firmware ran long enough to write the shared memory marker before ASSERT,
so the first wait loop iteration succeeded and the loop exited before firmware
died.

The ARM CR4 IOCTL write finding from test.20 may be a secondary issue: it
crashes during the ARM release attempt. When we skip ARM release (tests 22-25),
we avoid that crash but fall into the wait loop crash instead.

### Next steps (after test.25)

1. **Skip the FW wait loop for BCM4360** — instead of returning 0 from
   `exit_download_state`, return 0 but also bypass the wait loop entirely in
   `brcmf_pcie_download_fw_nvram`. This confirms whether the wait loop is the
   sole remaining crash source.

2. **Fix the ARM release crash** — the IOCTL write crash (test.20) needs to be
   addressed separately. Options:
   - Consult Phase 3/4 MMIO traces for the correct macOS reset sequence
   - Try ChipCommon indirect backplane access instead of direct core wrapper writes
   - Check if `enter_download_state` is the problem (it also writes ARM IOCTL)

3. **Once ARM can be released without crashing**, re-enable the FW wait loop
   with a short timeout and appropriate error handling, then investigate the
   firmware ASSERT at `hndarm.c:397` and NVRAM configuration.

## Phase 5.2: test.99 result (2026-04-16 23:28) — pointers frozen across T+200/400/800ms

Multi-timepoint pointer sampling + console ring dump (256 bytes from 0x9ccc0).
Clean exit, "RP settings restored". Log: `phase5/logs/test.99.journal`.

**Pointer sample (T+200, T+400, T+800ms — all three identical):**
```
ctr[0x9d000]  = 0x000043b1   (static, set once at T+12ms — consistent with test.89)
d11[0x58f08]  = 0x00000000   (D11 obj never linked — confirms test.98)
ws [0x62ea8]  = 0x0009d0a4   (TCM ptr to static struct in BSS; non-zero)
pd [0x62a14]  = 0x00058cf0   (vtable ptr — populated, consistent with test.93)
```

**Interpretation:**
- Firmware is **hard-frozen** between T+12ms and T+800ms — no delayed code path,
  no DPC/ISR execution writing any of these globals after the freeze.
- `d11[0x58f08] = 0` confirms si_attach D11 obj linkage never occurred.
- `pd[0x62a14] = 0x58cf0` is non-zero → some early init reached the vtable
  lookup (consistent with code reaching vtable dispatch in si_attach prologue).
- `ws[0x62ea8] = 0x9d0a4` is a static TCM pointer (firmware data section) —
  the wait-struct ptr is set at firmware data init, not at runtime.

**Console ring (256 bytes from 0x9ccc0, console_wp=0x8009ccbe):**
- 0x9ccc0–0x9cd14: `"125888.001 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmu rev 17, pmucaps 0x10a22b11"` — same ChipCommon banner seen in tests 78–80.
- 0x9cd18–0x9cda4: BSS metadata (counters, pointers — not text).
- 0x9cda8–0x9cdbc: `"125888.001 wl_probe call"` — truncated mid-message at the
  end of the 256-byte window.
- **Notably absent:** `"pciedngl_probe called"`. Since `console_wp = 0x9ccbe`
  is the next-write position (most recent text ends at 0x9ccbe-1), the
  "pciedngl_probe called" string from prior tests must live in the wrap-around
  region — older text in the ring at offsets we did NOT dump (between 0x9cdc0
  and 0x9ccbe via wrap). Wider/relocated dump needed if we want to see it.

**Net conclusion:**
Test.99 narrows nothing structurally beyond what test.98 already established
— D11 obj is never linked, firmware is hard-frozen — but it eliminates the
"delayed code path" hypothesis and re-confirms the freeze is at the same
position. Path B (D11 prerequisite checks via BCMA wrapper reads) remains
the next planned probe.

## Phase 5.2: Current state (as of 2026-04-16, POST test.98 — Path B triggered)

Tests 26–97 are logged in `phase5/logs/test.*.journal` and not re-summarized here
— individual-test detail lives in commit messages and logs, not this file.

**Where we are:**
- ARM release crash resolved; firmware now executes through early init.
- test.97: wait-struct at `*0x62ea8` read garbage heap (field20=0x66918f11,
  field24=0x5febdbeb, field28=0x84f54b2a). Wait-loop-setup code (which writes
  field24=1, field28=0) never ran → **fn 0x1624c is NOT the hang site**. The
  hang is upstream of fn 0x1624c.
- test.98 (ran 2026-04-16 23:02, log `phase5/logs/test.98.journal`, partial
  stage0 capture `phase5/logs/test.98.stage0.partial`):
  **step1 = TCM[0x58f08] = 0x00000000** → D11 object `field0x18` never set →
  si_attach's D11 core initialization is the hang region, not the PHY wait.
  Firmware counter progressed to 0x43b1 then froze (T+200ms RUNNING, T+400ms
  FROZEN; clean 2s timeout exit, no host crash).

**Revised working hypothesis:** si_attach cannot complete D11 core bring-up —
the D11 core object is never linked into the global at `*0x58f08`. A
prerequisite (clock/power/reset-state/interrupt routing) is missing.

**Decision: Path B** (below). The original Path A (wait-struct downstream
investigation) is shelved until/unless D11 prerequisites are satisfied and the
hang moves downstream into fn 0x16f60 / fn 0x1624c territory.

## Phase 5.2: Next steps — Path B (D11 prerequisite checks)

Upstream prerequisite checks (GitHub issue #11 recommendation #3 —
"earliest unmet prerequisite: clock/power/interrupt-mask/core-state"). Probe
order, cheapest first:

1. **D11 core BCMA state** (test.99) — read D11 core wrapper IOCTL/IOST/RESET_CTL
   via chip.c bus ops. Is the D11 core out of reset and enabled at ARM-release
   time, and does si_kattach leave it in the expected state? Also sample at
   T+200ms to see whether firmware changed the D11 core state before freezing.
2. **D11 core clock** — check ChipCommon clock-request registers and PMU
   resource-up status for the D11 clock domain. A missing HT/ALP request is a
   classic completion-never-fires cause.
3. **D11 power** — check PMU `min_res_mask` / `res_state` for D11-related
   resources. If the PHY rail isn't up, the PHY never signals done.
4. **Interrupt mask / routing** — the firmware may poll a flag that an ISR is
   supposed to set. Dump D11 `IntMask`/`IntStatus` (MMIO) and the PCIe MSI
   mask. If the ISR path never fires, a polled-from-ISR flag stays stuck.
5. **Compare to wl driver reset trace** — if any of the above is wrong, check
   `phase5/logs/wl-trace` for the sequence the proprietary driver uses to
   bring the D11 core up before firmware start.

Each probe follows the established pattern: stage0 code dump → targeted
TCM/MMIO read at T+200ms → commit pre-test + post-test notes.

## Phase 5.3: Current state (2026-04-19, POST test.147)

After the later crash-recovery series, the immediate failure is now before the
old firmware/D11 path. Tests 145-147 narrowed the host crash to module load /
PCI registration setup:

- test.145 reached `module_init entry` and `brcmf_pcie_register() entry`, but
  not the old `calling pci_register_driver` marker.
- test.146 reached `before brcmf_dbg in brcmf_pcie_register`, implicating either
  `brcmf_dbg()`/tracepoint work or an asynchronous hardware crash in that tiny
  window.
- test.147 skipped that early `brcmf_dbg()` and still crashed; the persisted
  stream only contains `module_init entry`, not `brcmf_pcie_register() entry`.

Post-SMC recovery after test.147 restored the PCIe hierarchy: root port
`00:1c.2` is back at secondary/subordinate `03/03`, the BCM4360 endpoint is
present at `03:00.0`, MAbort is clear, BAR0/BAR2 are visible, and endpoint AER
UESta is clear.

Next discriminator should be test.148: add call-site markers in `common.c`
immediately before and after `brcmf_pcie_register()`. A no-call/early-return
variant is also useful if we want to prove that merely loading the module is
safe when PCI registration is not attempted. As usual, no stage1, and save
notes plus commit/push before any run.
