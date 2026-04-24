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

## Host-firmware protocol — **olmsg over shared-info DMA ring** (the right answer)

| Claim | Status | Evidence | Date |
|---|---|---|---|
| **Primary host-fw protocol is olmsg (offload messaging) over a DMA ring buffer whose address is published via a `shared_info` struct in TCM.** Not msgbuf, not BCDC. | CONFIRMED | phase4/notes/transport_discovery.md (wl.ko symbolic evidence) + phase4/notes/test_crash_analysis.md §Test.28 (runtime handshake) | 2026-04-13 |
| `shared_info` struct lives at **TCM[0x9D0A4]** (BCM4360 — ramsize - 0x2F5C). Layout: | CONFIRMED | phase4/notes/level4_shared_info_plan.md + test.28 | 2026-04-13 |
| &nbsp;&nbsp;`+0x000` = `magic_start` (0xA5A5A5A5) | | | |
| &nbsp;&nbsp;`+0x004`..`+0x00B` = olmsg DMA physical addr (lo+hi 32-bit) | | | |
| &nbsp;&nbsp;`+0x00C` = buffer size (0x10000 = 64 KB) | | | |
| &nbsp;&nbsp;`+0x010` = fw-writable status field (observed `0x0009af88`) | | | |
| &nbsp;&nbsp;`+0x2028` = `fw_init_done` (fw sets non-zero when ready) | | | |
| &nbsp;&nbsp;`+0x2F38` = `magic_end` (0x5A5A5A5A) | | | |
| Writing a valid `shared_info` BEFORE ARM release is sufficient to prevent the 100 ms panic. Fw runs stably for ≥2 s, reads DMA addr, writes status to +0x010, sends 2 PCIe mailbox signals. | CONFIRMED | phase4/notes/test_crash_analysis.md §Test.28 (Level 4 PASS) | 2026-04-13 |
| olmsg ring structure: two rings (host→fw = ring 0, fw→host = ring 1). Each `{data_offset, size, read_ptr, write_ptr}` = 16 bytes header; ring data 0x7800 (30 KB) each; total 0xF020 within a 64 KB DMA buffer. | CONFIRMED | phase4/notes/option_c_feasibility.md (wl.ko disasm) | 2026-04-12 |
| Upstream brcmfmac PCIe path is **msgbuf-only**. BCM4360 fw does NOT speak msgbuf. No msgbuf fw variant for BCM4360 exists in linux-firmware. | CONFIRMED | commit `fc73a12` + T274 (zero HOSTRDY_DB1 refs in blob) | 2026-04-12, 2026-04-24 |
| BCDC proto code exists in brcmfmac (bcdc.c/h), wired to SDIO + USB. PCIe's `tx_ctlpkt`/`rx_ctlpkt` (pcie.c:2597/2604) are stubs returning 0. **BCDC-over-PCIe was an incorrect direction** — BCM4360 speaks olmsg, not BCDC. | SUPERSEDED-CORRECT | phase6/t275_upstream_audit.md (discovered stubs); phase4B olmsg evidence (the actual protocol) | 2026-04-24 |

## Current fw init state (what Phase 5's patches achieve, what's left)

| Claim | Status | Evidence | Date |
|---|---|---|---|
| With Phase 5 patches (NVRAM + Apple random_seed + FORCEHT), fw passes the Phase 4B `wlc_bmac_attach` TRAP point. | CONFIRMED | Phase 5 T236 onwards; no SROM-boardtype TRAP observed in current testing | 2026-04-23 |
| fw reaches `pcidongle_probe` and registers `pciedngl_isr` as scheduler callback node[0] (flag bit 3 = 0x8). | CONFIRMED | T255/T256 (node at TCM[0x9627C]) + T269 blob analysis + T274 reinterpretation | 2026-04-23, 2026-04-24 |
| `pcidongle_probe` body completes (alloc devinfo → helpers → hndrte_add_isr → fn@0x1E44 post-reg → return). No hangs in its direct body/sub-tree. | CONFIRMED | T274 disasm of 0x1E90..0x1F78 | 2026-04-24 |
| After pcidongle_probe returns, fw enters WFI via scheduler idle path. Scheduler state at TCM[0x6296C..0x629B4] frozen across 23 dwells (t+100 ms through t+90 s). | CONFIRMED | T255 frozen-state probe + T257 WFI-reachability static analysis | 2026-04-23 |
| fw never writes sharedram_addr to TCM[ramsize-4] — stays at NVRAM trailer `0xffc70038`. | CONFIRMED | T247 probe (22 reads across all dwells) | 2026-04-23 |
| **Phase 5 never carried forward Phase 4B's shared_info write.** The olmsg handshake is missing from the Phase 5 driver path. | LIVE (the next fix) | phase5/work/.../pcie.c does not write to TCM[0x9D0A4]; Phase 5 T234 tried zeroing TCM[0x9FE00..] but NOT writing shared_info | 2026-04-24 |

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
| Tight HW-polling loop is the current hang mechanism. | RULED-OUT | T273 / T274 — every identified tight loop in wlc_bmac_attach sub-tree is bounded (MAC-copy 6, txavail 6, macol_attach 30, SB-reset 20 ms). fn@0x1146C body has no HW reads. | 2026-04-24 |
| `pci=noaer` can be blamed for host wedges. Removing it didn't stop them. | RULED-OUT | phase4/notes/test_crash_analysis.md §Revised diagnosis | 2026-04-14 |
| `pci_reset_function()` works on this chip. | RULED-OUT | phase4/notes/test_crash_analysis.md §What doesn't work | 2026-04-13 |
| Fw writes `sharedram_addr` or any last-60-bytes of TCM within 90 s of `set_active` (under current patches). | RULED-OUT | T239/T240/T247 wide-poll across 23 dwells | 2026-04-23 |

## Unresolved / working hypotheses

| Claim | Status | Evidence | Date |
|---|---|---|---|
| Adding a shared_info + olmsg DMA write to Phase 5's `brcmf_pcie_setup` early path will break the WFI-stall and let fw publish sharedram_addr. | LIVE (next to try) | phase4/notes/test_crash_analysis.md §Test.28 shows this pattern works pre-ARM-release; Phase 5 just needs to port it | 2026-04-24 |
| BCDC-over-PCIe via brcmfmac's bcdc.c is a viable driver path. | LIKELY-WRONG | Correct protocol per primary sources is olmsg, not BCDC. BCDC symbols in blob are shared-codebase artifact. T275 writeup should be read with this caveat. | 2026-04-24 |
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
