# BCM4360 RE — Key Findings (cross-phase, pinned)

> **Read this FIRST each session, before RESUME_NOTES.md.**
>
> This file captures **load-bearing facts** across all phases. Things
> ruled in, ruled out, or known-unresolved. Evidence is linked to the
> authoritative phase note or commit.
>
> **Status vocabulary**:
> - **CONFIRMED** — proven by primary source, holds.
> - **RULED-OUT** — falsified by primary source, do not re-try without new evidence.
> - **LIVE** — current working hypothesis, not yet proven.
> - **SUPERSEDED** — once claimed, later corrected; keep for context.

---

## Firmware — identity & structure

| Claim | Status | Evidence | Date |
|---|---|---|---|
| fw blob at `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 B, md5 `812705b3ff0f81f0ef067f6a42ba7b46`) is the BCM4360 FullMAC fw. Banner `"RTE (PCIE-CDC) 6.30.223 (TOB)"`. FWID `01-9413fb21`. | CONFIRMED | `phase4/notes/test_crash_analysis.md §Phase 4 Conclusion`; T250 ring-dump | 2026-04-14, 2026-04-23 |
| fw blob contains BOTH a full wlc_* 802.11 stack AND `bcm_olmsg_*` offload helpers. Broadcom shared-codebase artifact; host picks which mode to drive. | CONFIRMED | wl.ko symbol analysis (phase4/notes/transport_discovery.md) + blob disasm T253/T254 | 2026-04-12, 2026-04-23 |
| fw expects valid NVRAM board data. Without it, `wlc_bmac_attach` reads SROM → 0xFFFF → TRAPs at PC 0xB80EF234 ~100 ms after ARM release. | CONFIRMED | phase4/notes/test_crash_analysis.md §Phase 4 Conclusion item 2 | 2026-04-14 |
| fw ignores NVRAM-in-TCM; reads HW SPROM instead. Writing NVRAM to ramsize-0x1ec..ramsize-4 DOES reach fw (observed side-effects on boot progression). | CONFIRMED | commit `79d2d9e` + Phase 5 T236 `random_seed` progression | 2026-04-13, 2026-04-23 |

## Host-firmware protocol — **shared_info handshake CONFIRMED; runtime protocol UNCERTAIN**

| Claim | Status | Evidence | Date |
|---|---|---|---|
| `shared_info` struct lives at **TCM[0x9D0A4]** (BCM4360 — ramsize - 0x2F5C). Writing it with magic markers before ARM release prevents the 100 ms panic. | CONFIRMED | phase4/notes/level4_shared_info_plan.md + test.28 (Level 4 PASS) | 2026-04-13 |
| `shared_info` layout: | CONFIRMED | phase4/work/bcm4360_test.c:60-72 + test.28 observations | 2026-04-13 |
| &nbsp;&nbsp;`+0x000` = `magic_start` (0xA5A5A5A5) | | | |
| &nbsp;&nbsp;`+0x004`..`+0x00B` = DMA phys addr (lo+hi 32-bit) | | | |
| &nbsp;&nbsp;`+0x00C` = buffer size (0x10000 = 64 KB) | | | |
| &nbsp;&nbsp;`+0x010` = fw-writable — points to a **console struct** (buf_addr, buf_size, write_idx, read_addr). Observed value `0x0009af88`. | | | |
| &nbsp;&nbsp;`+0x2028` = `fw_init_done` (fw sets non-zero on full init — **NEVER OBSERVED** set in Phase 4B testing) | | | |
| &nbsp;&nbsp;`+0x2F38` = `magic_end` (0x5A5A5A5A) | | | |
| With shared_info written, fw runs stably for ≥2 s, writes console struct pointer to `+0x010`, sends 2 PCIe mailbox signals via `PCIE_MAILBOXINT` bits. | CONFIRMED (Phase 4B); PARTIAL reproduction under Phase 5 (no mailbox signals) | test.28 / test.29 (Phase 4B harness); phase5/logs/test.276.journalctl.txt (Phase 5 patches) | 2026-04-13, 2026-04-24 |
| With shared_info + DMA bus master enabled: fw **did NOT write to the olmsg ring** (ring's write_ptr stayed 0). `fw_init_done` timed out. | CONFIRMED | test.29 + T276 post-release (olmsg ring pre-zeroed, read-ptrs stayed 0, fw_done stayed 0 across 2 s) | 2026-04-13, 2026-04-24 |
| **Phase 4B's `si[+0x010] = 0x0009af88` response reproduces EXACTLY under Phase 5 patches (T276).** Response happens at t+0ms post-set_active (before first 10 ms poll tick). Fw is genuinely listening at shared_info across fw init states. | CONFIRMED | phase5/logs/test.276.journalctl.txt:1394 vs phase4/notes/test_crash_analysis.md §Test.28 | 2026-04-24 |
| T276 did NOT reproduce Phase 4B's `MAILBOXINT=0x00000003` post-run. `MAILBOXINT` stayed 0 across full 2 s poll. Cause unclear — Phase 5 patches add ARM state differences; or Test.28's signals required a host action T276 doesn't make. | LIVE | test.276 poll-end line | 2026-04-24 |
| **The runtime protocol fw uses to talk to host is NOT proven.** Phase 4A inferred olmsg from wl.ko symbols; Phase 4B's runtime test showed olmsg ring unused. Phase 4B's level-5 code comment reads: `"This firmware is PCI-CDC (FullMAC), NOT olmsg offload"`. Current best reading: unknown; olmsg-only hypothesis is weak, CDC-only is contradicted by T274 (zero HOSTRDY_DB1 refs). | LIVE / UNRESOLVED | Contradictory sources; primary direct-observable evidence is mailbox signals + `shared_info[+0x010]` update | 2026-04-24 |
| olmsg ring structure (if used): two rings (host→fw = ring 0, fw→host = ring 1). Each `{data_offset, size, read_ptr, write_ptr}` = 16 bytes header; ring data 0x7800 (30 KB) each; total 0xF020 within 64 KB DMA buffer. | CONFIRMED-layout-UNCONFIRMED-usage | phase4/notes/option_c_feasibility.md (wl.ko disasm) | 2026-04-12 |
| Upstream brcmfmac PCIe path is **msgbuf-only**. BCM4360 fw does NOT speak msgbuf. No msgbuf fw variant for BCM4360 exists in linux-firmware. | CONFIRMED | commit `fc73a12` + T274 (zero HOSTRDY_DB1 refs in blob) | 2026-04-12, 2026-04-24 |
| BCDC proto code exists in brcmfmac (bcdc.c/h), wired to SDIO + USB. PCIe's `tx_ctlpkt`/`rx_ctlpkt` (pcie.c:2597/2604) are stubs returning 0. | CONFIRMED | phase6/t275_upstream_audit.md | 2026-04-24 |
| **T275's claim "BCDC-over-PCIe via 2 stubs is the path"** — SUPERSEDED. The stub observation stands, but "fw speaks BCDC" is unproven (T274 showed no HOSTRDY_DB1 refs; Phase 4B's PCI-CDC label applies to fw binary capability, not runtime behavior). | SUPERSEDED | phase6/t275 vs phase4/test.29 | 2026-04-24 |
| **Fw banner says `RTE (PCI-CDC)` in fw's own log.** Phase 4A's "olmsg-only" and T275's "CDC-only" are both partial; fw identifies itself as PCI-CDC, not olmsg. Runtime protocol remains LIVE but this is a data point for "CDC is relevant" (matches T274's label, contradicts earlier olmsg-only readings). | LIVE — banner evidence slightly favours CDC interpretation | T278 fw console line 4 | 2026-04-24 |

## Current fw init state (what Phase 5's patches achieve, what's left)

| Claim | Status | Evidence | Date |
|---|---|---|---|
| With Phase 5 patches (NVRAM + Apple random_seed + FORCEHT), fw passes the Phase 4B `wlc_bmac_attach` TRAP point. | CONFIRMED | Phase 5 T236 onwards; no SROM-boardtype TRAP observed in current testing | 2026-04-23 |
| fw reaches `pcidongle_probe` and registers `pciedngl_isr` as scheduler callback node[0] (flag bit 3 = 0x8). | CONFIRMED | T255/T256 (node at TCM[0x9627C]) + T269 blob analysis + T274 reinterpretation | 2026-04-23, 2026-04-24 |
| `pcidongle_probe` body completes (alloc devinfo → helpers → hndrte_add_isr → fn@0x1E44 post-reg → return). No hangs in its direct body/sub-tree. | CONFIRMED | T274 disasm of 0x1E90..0x1F78 | 2026-04-24 |
| After pcidongle_probe returns, fw enters WFI via scheduler idle path. Scheduler state at TCM[0x6296C..0x629B4] frozen across 23 dwells (t+100 ms through t+90 s). | CONFIRMED | T255 frozen-state probe + T257 WFI-reachability static analysis | 2026-04-23 |
| fw never writes sharedram_addr to TCM[ramsize-4] — stays at NVRAM trailer `0xffc70038`. | CONFIRMED | T247 probe (22 reads across all dwells) | 2026-04-23 |
| **Phase 5 never carried forward Phase 4B's shared_info write.** Phase 5 pcie.c has ZERO writes of `0xA5A5A5A5`/`0x5A5A5A5A` (verified by grep). It only READS 0x9D0A4 expecting fw to write the magic — but Test.28 proved the HOST writes it FIRST, then fw responds. Handshake direction has been backwards throughout Phase 5. | LIVE (the next fix) | grep shows zero writes; Test.28 proved direction | 2026-04-24 |

## Host-side — hardware characteristics

| Claim | Status | Evidence | Date |
|---|---|---|---|
| Chip ID 0x4360, revision 3, package 0. PCIe Gen1 x1 link. | CONFIRMED | phase4/notes/test_crash_analysis.md §Chip identity | 2026-04-13 |
| BAR0 = 32 KB (`0x8000`) backplane window. BAR2 = 2 MB (`0x200000`) TCM direct. | CONFIRMED | phase4/notes/test_crash_analysis.md §Device state | 2026-04-13 |
| BCM4360 lacks FLR support: `pci_reset_function()` hangs indefinitely. | CONFIRMED | phase4/notes/test_crash_analysis.md §What doesn't work | 2026-04-13 |
| `pci_disable_device()` in remove path → delayed PCIe bus lockup (~1–2 min). | CONFIRMED | same | 2026-04-13 |
| Stale AER errors after wl unload (UE 0x8000 = UR; CE 0x2000 = advisory) block BAR0 reads until W1C'd. | CONFIRMED | phase4/notes/test_crash_analysis.md §AER errors were the blocker | 2026-04-13 |

## Host-side — driver code

| Claim | Status | Evidence | Date |
|---|---|---|---|
| Kernel cmdline includes `pci=noaer` (NixOS config). Blinds us to all PCIe UE/CE/TLP-UR errors in kernel logs. | CONFIRMED | every journalctl capture | ongoing |
| Upstream `brcmf_pcie_setup` returns early for BCM4360 at line ~6368; never reaches `init_ringbuffers`/`init_scratchbuffers`/`request_irq`/`brcmf_attach`. Relies on Phase 5 patches. | CONFIRMED | phase6/t269_code_audit_results.md §2 | 2026-04-24 |
| `brcmf_pcie_tx_ctlpkt` and `brcmf_pcie_rx_ctlpkt` (pcie.c:2597/2604) are stubs returning 0. Msgbuf doesn't call them; they exist only to satisfy `brcmf_bus_ops` interface. | CONFIRMED | pcie.c inspection | 2026-04-24 |
| Merely subscribing MSI + `request_irq` on BCM4360 wedges the host — silent, no AER/NMI/MCE trace. Triggered within [0, 50 ms] of `request_irq`. Cause orthogonal to fw protocol question. | CONFIRMED | phase6/t269_code_audit_results.md §4 + T264/T265/T266 | 2026-04-24 |

## Testing / substrate

| Claim | Status | Evidence | Date |
|---|---|---|---|
| Full cold power cycle (shutdown + ≥60 s + SMC reset) buys a clean substrate window of ~20–25 minutes. Drift reliably returns after. | CONFIRMED | baseline-postcycle (06:33 BST) → T269 (06:56 BST) → T270-BASELINE (07:54 BST) replication | 2026-04-24 |
| Platform watchdog reliably recovers host lockups from fw-side or PCIe wedges. | CONFIRMED | n > 30 recoveries today without manual intervention | 2026-04-24 |

## Ruled out — keep the lessons

| Claim | Status | Evidence | Date |
|---|---|---|---|
| Writing H2D_MAILBOX_1 without prior shared_info + DMA buffer does anything productive. | RULED-OUT | T258–T269 scaffold series — all variants wedged without fw progress | 2026-04-23/24 |
| **Writing H2D_MAILBOX_0 or H2D_MAILBOX_1 without first enabling MAILBOXMASK does anything productive**, even under Phase 5 shared_info conditions. Fw's mask gates the bit from reaching the ARM interrupt line. | RULED-OUT | T279 primary-source | 2026-04-24 |
| **Writing MAILBOXMASK via `brcmf_pcie_intr_enable` at post-set_active time does anything productive** on BCM4360. Write silently drops; register stays 0. The "host unblocks mask → fw wakes" approach at this timing/register is blocked. | RULED-OUT | T280 primary-source: helper runs cleanly but readback shows register unchanged | 2026-04-24 |
| Tight HW-polling loop is the current hang mechanism. | RULED-OUT | T273 / T274 — every identified tight loop in wlc_bmac_attach sub-tree is bounded (MAC-copy 6, txavail 6, macol_attach 30, SB-reset 20 ms). fn@0x1146C body has no HW reads. | 2026-04-24 |
| `pci=noaer` can be blamed for host wedges. Removing it didn't stop them. | RULED-OUT | phase4/notes/test_crash_analysis.md §Revised diagnosis | 2026-04-14 |
| `pci_reset_function()` works on this chip. | RULED-OUT | phase4/notes/test_crash_analysis.md §What doesn't work | 2026-04-13 |
| Fw writes `sharedram_addr` or any last-60-bytes of TCM within 90 s of `set_active` (under current patches). | RULED-OUT | T239/T240/T247 wide-poll across 23 dwells | 2026-04-23 |

## Unresolved / working hypotheses

| Claim | Status | Evidence | Date |
|---|---|---|---|
| ~~Adding Phase 4B's shared_info write to Phase 5's `brcmf_pcie_setup` pre-ARM-release path will change fw behavior in a reproducible way.~~ | CONFIRMED — PARTIAL: si[+0x010] reproduces exactly (0x0009af88), mailbox signals do NOT reproduce. | T276 fire at 2026-04-24 11:06 BST | 2026-04-24 |
| **T276 did not alter the late-ladder crash window.** Fw still wedged host in [t+90s, t+120s] — same window as T270-BASELINE. The host wedge is orthogonal to whether shared_info is written. | CONFIRMED | phase5/logs/test.276.journalctl.txt t+90000ms LAST MARKER | 2026-04-24 |
| Pointer `0x0009af88` in si[+0x010] points to a 4-dword console struct: `{buf_addr, buf_size, write_idx, read_addr}` — Phase 4B layout interpretation CONFIRMED under Phase 5. | CONFIRMED | T277: post-poll struct decoded cleanly with all valid fields | 2026-04-24 |
| Fw-internal console buffer: **16 KB ring at TCM[0x96f78..0x9af78), struct header at TCM[0x9af88]** (16 B gap between buffer end and struct). | CONFIRMED | T277 struct dump: buf_addr=0x96f78 size=0x4000 | 2026-04-24 |
| Fw writes **real ASCII log content** to the console during post-set_active init. First 128 B captured by T277: `"Found chip type AI (0x15034360)\r\n125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11\r\n125888."`. | CONFIRMED | phase5/logs/test.277.journalctl.txt T277 buffer ASCII dump | 2026-04-24 |
| write_idx=0x24b=587 bytes at ~2 s post-set_active — fw's init log content at the time T277 polled. Ring has NOT wrapped (587 << 16 KB). `read_addr = buf_addr` — host has consumed nothing yet. | CONFIRMED | T277 post-poll struct | 2026-04-24 |
| Chip primary-source facts (from fw's own log): Chipc rev 43, caps `0x58680001`, chipst `0x9a4d`, pmurev 17, pmucaps `0x10a22b11`, chip type AI (AXI). Full chip-id dword `0x15034360`. | CONFIRMED | T277 buffer content | 2026-04-24 |
| Console struct at TCM[0x9af88] is NOT pre-populated in the fw image; fw writes it during post-set_active init. Pre-shared_info-write T277 read showed uninitialized garbage at that offset. | CONFIRMED | T277 PRE-WRITE dump: `buf_addr=0xad9afa8b size=0x02d5bf1b wr_idx=0x5370158c rd_addr=0x23535c0b` — uninitialized memory values | 2026-04-24 |
| **Fw reaches `wl_probe` and `pciedngl_probe`** (both logged by name by fw). Primary-source confirmation of Phase 5's fw advancing at least that far. | CONFIRMED | T278 fw console capture: `"pciedngl_probe called"` + `"wl_probe called"` | 2026-04-24 |
| **`si_kattach done. ccrev = 43, wd_msticks = 32`** — fw completes kernel/backbone attach; watchdog tick interval is 32 ms. | CONFIRMED | T278 fw console | 2026-04-24 |
| Fw clock rates: 40 MHz XTAL / 160 MHz backplane / 160 MHz ARM CPU. From fw's own RTE banner. | CONFIRMED | T278 fw console: `"RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0 MHz"` | 2026-04-24 |
| **Fw goes silent after wl_probe's initial chipc dump.** No further log entries across t+500ms / t+5s / t+30s / t+90s stages. Primary-source confirmation of T257's WFI reading (not busy-looping, not asserting, quietly waiting). | CONFIRMED | T278 all 4 stage hooks: `wr_idx=587 unchanged` | 2026-04-24 |
| No fw-side self-diagnosis string (no ASSERT / TRAP / PC= / "waiting for ..." / "timeout" text). Fw doesn't identify what it's waiting for — we must find the trigger via disasm + hardware probing. | CONFIRMED | T278 full 587 B console reassembled | 2026-04-24 |
| **wl_probe's scheduler callback registration (`fn@0x1146C` via hndrte_add_isr) appears to complete without fw logging the event.** wl_probe prints 3 lines then returns to RTE scheduler; T257 confirms WFI → RTE scheduler is running idle. wl_probe is NOT hanging inside a sub-call. | CONFIRMED (primary-source refinement of T273/T274) | T278 log end-point + T257 WFI-DEFINITIVE | 2026-04-24 |
| **`MAILBOXMASK = 0x00000000` in Phase 5 fw state at t~3 s post-set_active.** All fw-side MAILBOXINT bits masked at the ARM interrupt line. Explains why fw stays in WFI indefinitely — no mailbox write (H2D_MBX_0 or H2D_MBX_1) can propagate through the mask to wake the ARM. Decisive root-cause finding. | CONFIRMED | T279 pre-probe read: `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = 0x00000000` | 2026-04-24 |
| **Writing H2D_MAILBOX_0=1 and H2D_MAILBOX_1=1 produced ZERO MAILBOXINT latch and ZERO fw console response** under MAILBOXMASK=0. Confirms the mask is the gating factor (not absence of H2D writes). | CONFIRMED | T279 post-write reads: MAILBOXINT=0x0 after each; console wr_idx=587 unchanged | 2026-04-24 |
| **hndrte_add_isr's per-class unmask thunk (T274 description) does NOT produce a non-zero MAILBOXMASK under Phase 5 conditions.** Either the thunk writes to a different register, was not invoked, or its effect is gated on a condition we haven't satisfied. | LIVE | T279 MAILBOXMASK=0 primary-source + T274 thunk-vector analysis | 2026-04-24 |
| **Host-side MAILBOXMASK write via `brcmf_pcie_intr_enable` (writes `BRCMF_PCIE_PCIE2REG_MAILBOXMASK = BAR0+0x4C` with `0xFF0300`) SILENTLY FAILS at post-set_active time on BCM4360.** Helper returns cleanly (no wedge); readback shows register unchanged at `0x00000000`. Prior T241 verified the SAME BAR0 write-path PASSING at pre-set_active time → something in the chip's state post-ARM-release makes this register silently drop writes. | CONFIRMED | T280 pre/post MBM reads; T241 pre-set_active PASS comparison | 2026-04-24 |
| Pre-latched MAILBOXINT bits at post-set_active = 0 (no fw-side bits waiting for the mask to open). Even if MBM write worked, no immediate wake would fire. | CONFIRMED | T280 pre/post MAILBOXINT=0 | 2026-04-24 |
| **MAILBOXMASK default value at pre-set_active on BCM4360 = `0x00000318`** (not 0). Decode: `FN0_0 (0x100) | FN0_1 (0x200) | bits 3+4 (0x018)`. Bits 3 and 4 are suggestive matches for T273/T274's scheduler callback flags (pciedngl_isr flag=0x8=bit 3; fn@0x1146C candidate = bit 4). The default looks like a chip-level "proper wake configuration". | CONFIRMED | T284 pre-write pre-set_active read = 0x318 | 2026-04-24 |
| **`brcmf_chip_set_active` clears MAILBOXMASK from 0x318 → 0.** Single transition at ARM release; persists through entire post-set_active lifetime. | CONFIRMED | T284 post-set_active readback=0 (same MBM register); confirmed across 6 subsequent readbacks | 2026-04-24 |
| **MAILBOXMASK writes silently drop AT PRE-set_active too** (not just post-set_active). Write of 0xFF0300 leaves 0x318 unchanged. | CONFIRMED | T284 pre/post-write pre-set_active reads both 0x318; T241 same pattern 2026-04-23 | 2026-04-24 |
| **T241 was FAIL, not PASS** — earlier writeups (T280, PRE-TEST.284 plans) incorrectly cited T241 as proving MBM writes work pre-set_active. Primary source (`phase5/logs/test.241.journalctl.txt`) shows RESULT FAIL with identical 0x318-baseline + write-drop pattern that T284 reproduced. Framing correction recorded here. | CONFIRMED (correction) | phase5/logs/test.241.journalctl.txt | 2026-04-24 (correcting 2026-04-23 misread) |
| **MAILBOXMASK at BAR0+0x4C is write-locked on BCM4360 across all tested timings.** T241+T284 pre-set_active FAIL; T280+T284 post-set_active FAIL. The `brcmf_pcie_write_reg32(devinfo, ..., mailboxmask, ...)` path does not alter this register regardless of value, timing, or call path. | CONFIRMED | T241 + T280 + T284 cumulative | 2026-04-24 |
| **Scheduler ctx (used by hndrte_add_isr + class thunks) is TCM-backed at `*0x6296c`, populated by fn@0x672e4 at init.** fn@0x672e4 pushes `0x18000000` (CHIPCOMMON MMIO base) as an init arg into scheduler state. | CONFIRMED | T283 disasm of fn@0x672e4 at 0x67306 (`mov.w r3, #0x18000000`) | 2026-04-24 |
| **BIT_alloc (fn@0x9940 / fn@0x9944) reads chipcommon INTSTATUS at absolute `0x18000100`.** Access chain: `[scheduler_ctx+0x254]+0x100` where `[scheduler_ctx+0x254]` was set by class-0 thunk to point at CHIPCOMMON MMIO base. fn@0x9940 returns bits 0-4; fn@0x9944 (class 0x812) returns bits 8-12. Scheduler's free-interrupt-bit pool IS chipcommon intstatus. | CONFIRMED | T283 disasm of 0x2890/0x289e + 0x27ec class-0 thunk + 0x672e4 allocator | 2026-04-24 |
| **fn@0x2309c's pending-events chain (`[[r0+0x10][+0x88]]+0x168`) operates on a wlc-owned struct reached via `[wlc_callback_ctx+0x18]+8`, NOT on the scheduler ctx directly.** The `+0x88` offset is a different struct member than the scheduler's `+0x88`. Absolute address of the final `+0x168` word is NOT statically resolved without deeper wlc-probe trace — strong inference it's chipcommon MMIO near `0x18000168`. | PARTIAL — LIVE | T283 partial chain trace + chipcommon-side BIT_alloc pattern match | 2026-04-24 |
| **"The mask" in fn@0x1146C's dispatch is scheduler-side software flag mask (`[node+0xc] & pending_events`), NOT the PCIE2 MAILBOXMASK at BAR0+0x4C.** Therefore writing MAILBOXMASK was never going to wake fn@0x1146C — the entire T280/T284 mask-investigation axis was diagnosing the wrong register. fw's WFI likely wakes on chipcommon interrupt. | LIVE (strong inference) | T283 structural analysis; not yet tested on hardware | 2026-04-24 |
| BCDC-over-PCIe via brcmfmac's bcdc.c is a viable driver path. | LIKELY-WRONG | T274 + Phase 4B test.29 don't support CDC wiring as sufficient. Don't build on this. | 2026-04-24 |
| olmsg ring is the runtime communication path after shared_info. | UNCERTAIN | Phase 4A inferred; Phase 4B test.29 showed ring unused. Could depend on a further host action we didn't make. | 2026-04-24 |
| MSI-subscription wedge (T264–T266) has a known fix via `pci=noaspm` or different MSI setup. | LIVE | phase6/t269_code_audit_results.md §Candidates B/C — not tested | 2026-04-24 |

## Session discipline — READ THIS LAST AND UPDATE WHAT'S NEEDED

**Every session, at the end, ask yourself:**

1. Did this session produce a **load-bearing fact** (something that would change the next session's direction)? If yes → add a row here. Assign CONFIRMED / RULED-OUT / LIVE. Link evidence (phaseN/notes/file#section, or commit hash).
2. Did a prior CONFIRMED fact get **refined or superseded**? If yes → mark it SUPERSEDED with a short correction, add the new row as CONFIRMED.
3. Did a LIVE hypothesis get **tested**? Update status to CONFIRMED or RULED-OUT.
4. Is RESUME_NOTES's "Current state" block still consistent with this file? If not, fix one or both.

**Before starting the next session's substantive work**:

1. Read this file (the whole thing — it is deliberately short).
2. For any "aha" moment during research: run `git log --all --grep '<keyword>'` and `grep -rn '<keyword>' phase*/notes/ *.md` before writing it up as a new finding. If a prior phase has it, cite them rather than rediscovering.
3. If a "new finding" contradicts a CONFIRMED row here, pause and reconcile before committing.

This file rots if not maintained. Maintaining it is mutual — Claude prompts the user at session close to review; the user prompts Claude at session start to read.
