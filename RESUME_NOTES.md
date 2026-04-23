# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 19:0x BST, POST-TEST.254 — **hang is NOT a direct polling loop; all wlc PHY-subtree loops are PMCCNTR-bounded.** Host stable, boot 0 up since 18:11:33 BST, PCIe clean (Mem+ BusMaster+ MAbort-), no brcm loaded. T254 was a LOCAL analysis pass (no hardware test, no crash) — scripts + deliverable `phase5/analysis/T254_phy_subtree.md`. Key findings: (1) **All three PHY-subtree polling loops** (0x1415C, 0x1722C = `wlc_bmac_suspend_mac_and_wait`, 0x14CAC) use `bl #0x1ADC` delay helper which reads PMCCNTR (CP15 c9,c13,0) — **bounded, cannot hang**. PMCCNTR is enabled at boot via PMCR writes at 0x1D6/0x1DC. Each poll has ≤82ms wall-clock timeout. (2) **"40/160/160MHz" last-printed line is the RTE BOOT banner** (blob[0x6BAE5]), NOT wlc_attach — T251 reading revised. Fw hung AFTER RTE prints, anywhere in subsequent init. (3) **Chiprev banner call site = blob[0x06877A]** (inside wlc_bmac_attach, confirmed by wlc_bmac_attach literal ref from same function). Fw never reached this printf → hang is in wlc_bmac_attach pre-0x06877A. (4) **No WFI, no reachable `b .` self-loop** in wlc path. Two apparent hits at 0x464F6/0x468F4 are false positives (data region, no callers, junk strings nearby). (5) **Best-fit hang mechanism**: cross-core / backplane wait — fw issued a transaction to an unclocked/stuck SB core, CPU stalled at memory-subsystem level. Ruled out: direct polling-loop hang; RTOS task wait (no task-table primitives found); all known delay loops. Next-test T255: cheap hardware probe of TCM[0x58C98] (tick-scale) + TCM[0x93550..0x9358C] (decode 0x9355C, the forward-linked struct pointer from 0x934C0).)



## PRE-TEST.252 (2026-04-23 17:0x BST, boot 0 after test.251 crash + SMC reset) — **BSS data probe at the saved-state-region's repeated TCM offsets.** Single t+60s probe reads 16 u32s at each of 0x93610, 0x92440, 0x91CC4 — the three runtime-data addresses fw appears to be tracking at hang time (5×, 3×, 3× repetition in T251's saved-state region).

### Hypothesis

The saved-state region at TCM[0x9CE98..0x9CF34] holds repeated references to three TCM data addresses (above the code segment, so not in the blob — runtime BSS/heap):

| Addr | Repetition | Hypothesis class |
|---|---|---|
| 0x00093610 | 5× | Active task/object descriptor — most-likely "current pointer" or scheduler head |
| 0x00092440 | 3× | Secondary pointer in same structure family |
| 0x00091CC4 | 3× | Third pointer in same structure family |

Plus 0x000934C0 appears once (also in T248's 0x9CFE0). Together these form a ~0x18C0-byte cluster of related runtime structures.

**Disambiguator probes** answer one of:
- (a) Task control blocks → expect to see a small fixed-layout struct with magic numbers, a state field, a stack pointer, and a function pointer.
- (b) PHY hardware struct shadows → expect register-like values (channel, frequency, gain settings, calibration data).
- (c) Mutex / semaphore / event flag → expect a small struct with a counter, an owner-id, a queue head.
- (d) Sandbox/garbage → expect zeros or random.

If (a) fits, the function-pointer fields will be Thumb-mode addresses pointing into fw code — disassembly target. If (b) fits, we have hard evidence fw is stuck talking to the radio. If (c) fits, the queue-head can be walked.

### Design

**Single probe at t+60000ms** (T251 console_ext is OFF — already captured):

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x93600..0x9363c]` (16 u32 = 64 B) | 16 | 5×-repeat target — primary, most likely active descriptor |
| t+60000ms | `TCM[0x92430..0x9246c]` (16 u32 = 64 B) | 16 | 3×-repeat target — secondary |
| t+60000ms | `TCM[0x91cb0..0x91cec]` (16 u32 = 64 B) | 16 | 3×-repeat target — tertiary |
| every dwell (23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Continued frozen-counter poll. n=4 replication of test.89. |

Total: 71 reads (vs T251's 99). Saves ~28 reads.

**Log format (3 pr_emerg lines at t+60s):**
```
test.252: t+60000ms TCM[0x93600..0x9363c] = 16 hex values (5x-repeat target)
test.252: t+60000ms TCM[0x92430..0x9246c] = 16 hex values (3x-repeat target)
test.252: t+60000ms TCM[0x91cb0..0x91cec] = 16 hex values (3x-repeat target)
```
Each line ~190 chars. Well under LOG_LINE_MAX 1024.

**Runtime config**: `bcm4360_test252_phy_data=1`. Drops T249/T250/T251 console probes (already captured).

### Next-step matrix

| Observation | Implication | T253 direction |
|---|---|---|
| 0x93610 area has Thumb-mode function pointers (LSB=1) and small int fields | Looks like a TCB / object with virtual dispatch. Disassemble the fn-ptrs in blob to identify what fw is waiting on. | Decode the fn-ptrs locally, no T253 needed if conclusive. |
| 0x93610 area has register-like values (channel/freq/gain) | PHY hardware shadow. Fw stuck mid-radio-init. | Probe PHY core registers via PCIe BAR2 alias; correlate with channel-init timing. |
| 0x93610 area has mutex/semaphore pattern (counter, owner, queue-head) | Fw stuck waiting for a mutex / event. | Walk the queue; identify waiting tasks. |
| 0x93610..0x91CB0 areas all zeros | BSS not initialized / fw never reached this code path | Pivot: re-decode the saved-state region under a different model (call stack vs context table). |
| 0x93610 areas all distinct, no overlap | Three independent objects (not same struct family) | Each becomes its own decode target. |
| Counter 0x9d000 = 0x43b1 across all 23 dwells (n=4 replication) | Test.89 single-write confirmed at n=4. Reframe to "saved-state field" stands. | No further action on this axis. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 48 at t+60s + 23 per-dwell = 71 reads. Comfortable margin under T251.
- SMC reset expected after wedge (n=6 streak T247..T252 expected).

### Code change outline

1. New module param `bcm4360_test252_phy_data` near T251's.
2. New macro `BCM4360_T252_DATA_PROBE(stage_tag)` reading 3 × 16 u32 → 3 pr_emerg lines.
3. Extend T239 ctr gate: `if (bcm4360_test249_console_dump || bcm4360_test250_console_gap || bcm4360_test251_console_ext || bcm4360_test252_phy_data)`.
4. Invocation: right after `BCM4360_T251_RING_EXT("t+60000ms")` (pcie.c).

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test252_phy_data=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T249/T250/T251 params NOT set (already captured those windows).

### Expected artifacts

- `phase5/logs/test.252.run.txt`
- `phase5/logs/test.252.journalctl.txt`

### Pre-test checklist (complete — READY TO FIRE)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `0014a0f872848f4e3621d629d9a08b2a` on `brcmfmac.ko`. `modinfo` shows new param `bcm4360_test252_phy_data`. `strings` confirms all 3 T252 format lines (16 u32 each at 0x93600/0x92430/0x91cb0). Only pre-existing unused-variable warnings.
2. **PCIe state**: `Mem+ BusMaster+`, MAbort-, CommClk+, UESta clean, CESta AdvNonFatalErr+ (sticky). Re-verified 16:51 BST.
3. **Hypothesis**: stated above (BSS data at saved-state region's repeated TCM offsets identifies what fw is tracking at hang).
4. **Plan**: this block + code change to be committed and pushed before insmod.
5. **Host state**: boot 0 started 16:50 BST, stable. No brcm modules loaded.

---

## POST-TEST.252 (2026-04-23 17:1x BST — boot -1 after test.252 crash + SMC reset)

Boot -1 timeline: boot start 16:50:08 → insmod 17:16:16 → t+60s probe 17:17:37 (T252 + T247/238/239/240/248/249) → t+90s probe 17:18:08 (T248 + T249 ctr final) → wedge ≤1s after → last journal entry 17:18:08. Full journal at `phase5/logs/test.252.journalctl.txt` (1509 lines). All 3 T252 probe regions captured successfully.

### What test.252 landed (facts)

**TCM[0x93600..0x9363C] — 16 u32 (5×-repeat target, 0x93610-centered):**
```
0x93600: 00000000 00000000 00000010 00000000   [+0..+12 zeros]
0x93610: 00000000 00058ef0 00000000 00000000   [+16: 0x58EF0 at offset +4]
0x93620: 000000b0 00000000 00000000 00000000   [+32: 0xB0 at offset +0]
0x93630: 00000000 00000000 00000000 00000000   [+48..+60: zeros]
```

**TCM[0x92430..0x9246C] — 16 u32 (3×-repeat secondary, 0x92440-centered) — RICHEST:**
```
0x92430: 00000000 00000000 00000374 00000000   [+8: 0x374 = 884]
0x92440: 0009238c 00093610 00093628 18001000   [4 pointers: TCM,TCM,TCM,CC-core-base]
0x92450: 00091cc4 00091c04 000934c0 00000000   [3 TCM ptrs + 0; 0x934C0 = T248 match]
0x92460: 00091e54 00091e84 00091e54 00091e84   [TWO adjacent list_head pairs]
```

**TCM[0x91CB0..0x91CEC] — 16 u32 (3×-repeat tertiary, 0x91CC4-centered):**
```
0x91CB0: 00000000 00000000 00000000 00000188   [+12: 0x188 = 392]
0x91CC0: 00000000 00092440 00091c04 00093610   [back-refs: secondary, TCM, primary]
0x91CD0: 00000000 000934c0 00000000 00000000   [0x934C0 match again]
0x91CE0: 00000000 00000000 00000000 00000000   [zeros]
```

**Counter 0x9D000 = 0x000043B1 for all 22 dwells** this run (n=4 replication of test.89).

### What test.252 settled (facts)

- **0x58EF0 is NOT a function pointer — it's the ASCII string `"wl\0\0"`** (blob[0x58EF0] = 0x77 0x6C 0x00 0x00). This is the interface-name prefix used in `"wl%d:"` fmt strings. Reframes 0x93610: this slot holds a **pointer to the interface name string**. 0x93610 is likely a **wl_info / WL driver context structure** — the top-level 802.11 driver state. 0xB0 (176) at 0x93620 is a small field (flags/size/index).
- **0x92440 is a runtime-populated silicon-backplane descriptor (si_info-class).** Contains `0x18001000` = ChipCommon core base register — and critically, the blob has **ZERO verbatim `18 00 10 00` literals** anywhere. That means fw constructs this value at runtime (MOVW/MOVT pair) and caches it here. Consistent with `si_attach()` semantics (enumerate SB cores, cache base addresses). Field inventory:
  - `0x92438 = 0x374` (908 dec) — likely a size/count field
  - `0x92440..0x9244F`: 4 pointers (TCM data ptrs + CC core base) — likely `ccores[0]`/`pub`/similar
  - `0x92450..0x9245F`: 3 pointers + 0 — likely pointers to neighboring descriptor structs
  - `0x92460..0x9246F`: `{0x91E54, 0x91E84}` pattern × 2 — **two adjacent embedded `list_head` nodes** (prev/next to same peer pair). These are empty or sparsely populated lists.
- **0x91CC4 region is a subordinate struct with back-references to both primary (0x93610) and secondary (0x92440).** Same 0x934C0 value appears again. Three structs form an inter-linked family.
- **0x934C0 is referenced in all three structs** (0x92458, 0x91CD4) **AND** in T248's 0x9CFE0 **AND** in T251's saved-state 0x9CEA0. Strong signal that 0x934C0 is a **central shared object** (chipcommon public struct pointer, or a scheduler/event root). Not yet probed.
- **No Thumb-mode function pointers** (all LSBs are 0 or point to string/data). Reading (a) "TCB with fn-ptrs" from the PRE-TEST.252 matrix is NOT supported. Reading (b) "PHY register shadow" is NOT supported either (no register-like values such as channel/gain). Reading (c) "mutex/semaphore" is partially supported by the two `list_head`-style pairs but there's no counter or owner-id pattern.
- **Best fit: these are silicon-backplane/driver-descriptor structs — not PHY state.** 0x18001000 = ChipCommon core base. The structs are linked into a wl/si core descriptor graph. Hang is likely in a *waiter* that references these structs (via LR 0x68320 → wlc_bmac_attach → wlc_phy_attach), not in the structs themselves being "wrong."
- **Ring-end bound tightened (test.89 counter reframe holds).** Counter value 0x43B1 at 0x9D000 and 0x9CF2C confirmed stable across n=4 replications — not a tick counter; a saved-register/token.
- **Wedge ≤1s after t+90s probe burst** (n=6 streak T247..T252). Probe costs are flat, not cumulative.
- **SMC reset required.**

### Where the hang is — careful reading post-T252

Combined with T251 blob analysis (the "saved-state region" contains PCs 0x68320 and 0x68D2E, located in/near wlc_bmac_attach and wlc_attach respectively; the chiprev banner — printed after wlc_phy_attach returns — was never observed):

1. **wlc_attach entered** (PC 0x68D2E in its literal-pool region).
2. **wlc_bmac_attach entered** (PC 0x68320 in its literal-pool region).
3. si_info struct at 0x92440 populated with CC core base 0x18001000 → `si_attach()` completed before hang.
4. Chiprev banner never fires → fw has NOT progressed past wlc_bmac_attach's post-wlc_phy_attach printf.
5. **Unverified, not a conclusion**: "inside wlc_phy_attach" is the tightest reading, but T251 saved PCs don't form a clean caller→callee chain and the saved-state region may be a context save / TCB rather than a stack. Conservative claim: hang is **somewhere in the wlc_attach → wlc_bmac_attach call tree, before the chiprev banner fires**.

### Next-test direction (T253 — candidates for advisor review)

Pure local blob analysis can probably still reach:
1. **Disassemble wlc_phy_attach (call site at ~blob[0x6831C..], BL target ~blob[0x1415C])** to identify PHY register polling loops. Find tight `ldr/tst/beq` patterns and which register/mask they target.
2. **Chase 0x934C0** — probe TCM[0x934C0..0x93500] to identify the central shared struct.
3. **Examine code around 0x58EF0 / 0x93610 init** — strings region context might reveal what driver-object 0x93610 holds (wl_info field offsets).
4. **Pivot to hardware**: read AC_PHY core registers via BAR0 window (dangerous — PHY access can wedge if core not out of reset).

Advisor call before committing to T253 design.

---

### Hardware state (current, 2026-04-23 17:28+ BST, boot 0 after test.252 crash **with SMC reset**)

`sudo lspci -s 03:00.0`: `Mem+ BusMaster+`, MAbort-, CommClk+, LnkSta 2.5GT/s x1, UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky). No brcm modules loaded. Boot 0 started 17:28:11 BST. Host healthy.

---

## PRE-TEST.253 (2026-04-23 17:5x BST, boot 0 after test.252 crash + SMC reset) — **central-shared-object probe + list_head validation**. Single t+60s probe reads 16 u32 at 0x934B8 (covers 0x934C0 and 8 pre-bytes for allocator-header check) + 16 u32 at 0x91E50 (list_head peers + context). Advisor-confirmed post-T253 local analysis.

### Hypothesis

Two branches of the saved-state reading need discrimination:

- **Branch (α) — stack-or-call-context reading**: the saved-state region at TCM[0x9CE98..0x9CF34] is an active task's call context, so the LR values there (0x68321 in wlc_bmac_attach area, 0x68D2F in wlc_attach area) reflect the current hung call chain. T252 local analysis narrows the hang to a callee of wlc_phy_attach (likely via 0x34DE0 → 0x6A2D8 dispatcher chain).
- **Branch (β) — task context save / TCB reading**: the saved-state region is a paused task's TCB. The hang is in a DIFFERENT task entirely; the saved LRs just show what this paused task was doing. This makes T253's local analysis of 0x6A2D8 irrelevant (wrong task).

**The 0x934C0 probe discriminates**. If 0x934C0 looks like a TCB — magic/type tag + state field + stack pointer + entry function pointer — then (β) is strongly supported and "which task hung" becomes the question. If it looks like a regular struct (no magic, no state, no sp/entry-fn pattern), (α) remains tenable.

**The 0x91E54/0x91E84 probe validates the list_head pair reading**. An empty doubly-linked list embedded in a struct has prev=self+offset, next=self+offset (pointing back to the slot). If `[0x91E54]={next=0x92460, prev=0x92460}` (or similar, pointing back to the si_info struct's list-head slot at 0x92460/0x92468), the list is empty and our "embedded list_head" inference is correct. If they point elsewhere, the list has members and we can walk them (new info). If they're garbage, list-head reading needs revision.

### Design

**Single probe at t+60000ms** (T252 phy_data is OFF — already captured):

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x934B8..0x934F8]` (16 u32 = 64 B) | 16 | Central-shared-object decode. 8 pre-bytes (0x934B8..0x934BF) catch allocator header if present; main region 0x934C0..0x934F8 holds the object. |
| t+60000ms | `TCM[0x91E50..0x91E90]` (16 u32 = 64 B) | 16 | list_head peer probe. Reads 0x91E54 (peer A) + 0x91E84 (peer B) + surrounding context. |
| every dwell (23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Per-dwell ctr poll. n=5 replication of test.89. |

Total: 32 + 23 = 55 reads. Cheaper than T252 (71) and T251 (99).

**Log format (2 pr_emerg lines at t+60s):**
```
test.253: t+60000ms TCM[0x934b8..0x934f4] = 16 hex values (central shared object + header)
test.253: t+60000ms TCM[0x91e50..0x91e8c] = 16 hex values (list_head peer pair + context)
```
Each line ~190 chars. Under LOG_LINE_MAX 1024.

**Runtime config**: `bcm4360_test253_shared_obj=1`. Drops T249/T250/T251/T252 probes (all already captured).

### Next-step matrix

| Observation at 0x934C0 | Implication | T254 direction |
|---|---|---|
| Magic/type tag + state + sp + entry-fn pattern | Branch (β) confirmed: saved-state is a **paused task TCB**. Hang is in a different task. | Enumerate RTOS task list; probe the other TCBs. |
| Regular struct (no magic, no sp/entry-fn) — e.g., config or routing table | Branch (α) still tenable. | Resume local disassembly: 0x6A2D8 (real PHY worker) for polling loops. |
| Sparse zeros / garbage | 0x934C0 ref across structs was coincidental or a stale pointer. | Revisit: reread T251/T252 decodes. |

| Observation at 0x91E54 / 0x91E84 | Implication | T254 direction |
|---|---|---|
| prev/next point back to 0x92460/0x92468 | Empty list_head embedded in si_info. Confirms reading. | No further action on this axis. |
| prev/next point to other TCM addresses (e.g., 0x91E54/0x91E84 themselves, or other peers) | List has members — can walk to enumerate. | Walk list from 0x91E54 to enumerate members. |
| Garbage values | list_head reading wrong. | Revisit si_info-class inference. |

| Counter 0x9d000 = 0x43b1 across all 23 dwells (n=5 replication) | test.89 single-write confirmed at n=5. Reframe holds. | No further action. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 32 at t+60s + 23 per-dwell = 55 reads (cheapest probe since T248).
- SMC reset expected after wedge (n=7 streak T247..T253 expected).

### Code change outline

1. New module param `bcm4360_test253_shared_obj` near T252's.
2. New macro `BCM4360_T253_SHARED_PROBE(stage_tag)` reading 2 × 16 u32 → 2 pr_emerg lines.
3. Extend T239 ctr gate: `if (...T252 || bcm4360_test253_shared_obj)`.
4. Invocation: right after `BCM4360_T252_DATA_PROBE("t+60000ms")` in pcie.c.

### Run sequence

```bash
sudo modprobe cfg80211 && sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1 \
    bcm4360_test253_shared_obj=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: T249/T250/T251/T252 params NOT set (already captured those windows).

### Expected artifacts

- `phase5/logs/test.253.run.txt`
- `phase5/logs/test.253.journalctl.txt`

### Pre-test checklist (complete — READY TO FIRE)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `bce1d0f08e661f1b0df50c0fdc3a04f4` on `brcmfmac.ko`. `modinfo` shows new param `bcm4360_test253_shared_obj`. `strings` confirms both T253 format lines (16 u32 each at 0x934b8 / 0x91e50). Only pre-existing unused-variable warnings.
2. **PCIe state**: `Mem+ BusMaster+`, MAbort-, CommClk+, UESta clean, CESta AdvNonFatalErr+ (sticky). Re-verified 17:5x BST.
3. **Hypothesis**: stated above — if 0x934C0 looks like a TCB, the saved-state is a paused task (reframes hang as "which task") → (β); if regular struct, stack-like-reading (α) tenable. list_head peer self-ref confirms empty-list inference.
4. **Plan**: this block + code change to be committed and pushed before insmod.
5. **Host state**: boot 0 started 17:28 BST, stable. No brcm modules loaded.

---

## POST-TEST.253 (2026-04-23 18:0x BST — boot -1 after test.253 crash + SMC reset)

Boot -1 timeline: boot start 17:28:11 → insmod 18:00:54 → t+60s probe 18:02:17 (T253 + T247/238/239/240/248/249 success) → t+90s probe 18:02:46 (T248 + T249 ctr final) → wedge ≤1s after → boot ended 18:03:03. Wedge n=7 streak T247..T253. PCIe cleanly recovered after SMC reset (Mem+ BusMaster+ MAbort- UESta clean, CESta AdvNonFatalErr+ sticky). Full journal at `phase5/logs/test.253.journalctl.txt` (458 lines). Both T253 probe regions captured successfully.

### What test.253 landed (facts)

**TCM[0x934B8..0x934F4] — 16 u32 (central shared object + pre-header):**
```
0x934B8: 00000078 00000000 00000000 0009355c   [+0: 0x78=120, +8: zero, +12: TCM ptr 0x9355C]
0x934C8: 00000000 00000000 00000000 00000000   [+0x10..+0x1C zeros]
0x934D8: 00000000 00000000 00000000 00006908   [+0x20..+0x28 zeros, +0x2C: 0x6908 (26888)]
0x934E8: 00000000 00000000 00000000 00000003   [+0x30..+0x38 zeros, +0x3C: 0x3]
```

Mapping with 0x934B8 as base:
- 0x934B8 = 0x00000078 (= 120 dec) — looks like an allocator size header (next struct = 120 bytes).
- 0x934C0 (the "central shared object") is 8 bytes later. Contents 0x40-byte tail shown:
  - 0x934C0 = 0 (object base)
  - +0x04 = 0x0009355C (TCM ptr — new, forward into the struct family)
  - +0x08 = 0
  - +0x0C = 0
  - +0x10..+0x20 = 0 (all zero across 5 u32)
  - +0x24 = 0x00006908 (= 26888)
  - +0x28 = 0
  - +0x2C = 0
  - +0x30 = 0
  - +0x34 = 0x00000003

**TCM[0x91E50..0x91E8C] — 16 u32 (list_head peer pair region, probing targets 0x91E54 + 0x91E84):**
```
0x91E50: 00000000 00000000 00000000 00000000   [all zeros]
0x91E60: 00000000 00000000 00000000 00000000   [all zeros]
0x91E70: 00000000 00000000 00000000 00000030   [+0x28: 0x30 (48)]
0x91E80: 00000000 00000000 00000000 00000000   [all zeros]
```
- 0x91E54 = 0 (expected "peer A" — was referenced from 0x92460 in T252 as list_head next).
- 0x91E84 = 0 (expected "peer B" — was referenced from 0x92464 in T252 as list_head prev).
- Only non-zero in the 64-byte window: 0x91E7C = 0x30.

**Counter 0x9D000 = 0x000043B1 for all 22 dwells** this run (n=5 replication of test.89 single-write reading).

### What test.253 settled (facts)

- **Branch (α) — saved-state region is a call-context snapshot — CONFIRMED.** 0x934C0 TCB-pattern test was the pre-test discriminator. All three TCB signals absent (no magic, no LSB=1 fn-pointer in the 16-u32 dump, no sp-like value). Reading "the saved-state region at 0x9CE98..0x9CF34 is a task's call context, and the LR values 0x68321/0x68D2F there reflect the hung call chain" **stands unrevised**. The T251-era β alternative ("paused TCB reading, hang in different task") is **falsified** — T253 closes this fork.
- **0x934C0 is a partially-initialized 120-byte struct** (size 0x78 in the pre-header at 0x934B8 is consistent with an ARM-style allocator prefix). Only three fields populated out of ~30 u32 slots. Consistent with fw being stuck mid-init — the allocator ran and a few fields were written, but fw hung before completing this struct's initialization. Fields that ARE populated:
  - +0x04 = 0x9355C — another TCM ptr into the struct family (cheap probe target).
  - +0x24 = 0x6908 — unexplained constant (not a blob offset, not in 0x18xxxxxx range, fits "count / index / token").
  - +0x34 = 0x3 — small integer (state, index, or flag set).
- **list_head peer-pair reading DOWNGRADED.** T253 probe at 0x91E50..0x91E8C shows both 0x91E54 and 0x91E84 are zero. Linux empty-list convention requires self-reference; non-empty requires populated peers; both-zero is neither. The T252 "two adjacent embedded list_head pairs at 0x92460" claim is **not confirmed** by T253. Plausible alternatives: (a) non-Linux list convention with NULL terminators; (b) uninitialized BSS read via stale pointers in 0x92440; (c) those 0x92460 fields are not list_head pointers at all — possibly integer values or different-sized record offsets. This does NOT change the si_info-class reading of 0x92440 (CC core base 0x18001000 evidence still holds) — only the list_head sub-inference.
- **0x9355C is now the cheapest next-probe target** — same family as 0x934C0, forward linkage, same risk profile as T253.
- **n=5 replication of test.89 frozen-ctr.** 0x43B1 at 0x9D000 stable across 22 dwells × 5 boots.
- **n=7 wedge streak T247..T253.** Probe costs remain flat (not cumulative).
- **SMC reset required.**

### Where the hang is — reading after T253

Consolidated picture (no contradictions in observed data):

1. wlc_attach entered (LR 0x68D2F in saved-state).
2. wlc_bmac_attach entered (LR 0x68321 in saved-state).
3. si_info (0x92440) populated with CC core base 0x18001000 → si_attach() completed before hang.
4. wlc_attach printed the RTE banner + BCM4360 r3 40/160/160MHz line (T251). Next line (chiprev banner, printed after wlc_phy_attach returns) never fires.
5. 0x934C0 partially initialized — allocator ran, first few fields written, struct body unfinished.
6. Hang is inside a callee reached from wlc_bmac_attach → wlc_phy_attach → [callee]. Per T253 local analysis (phase5/analysis/T253_wlc_phy_attach.md), the most likely sub-tree is the 0x34DE0 dispatcher chain → 0x6A2D8 (real PHY worker) → 0x38A50/0x38A24 dispatch tables (PHY-op vtable entries).

### Next-test direction (T254 — candidates for advisor review)

Two tracks, both cheap:

1. **T254 LOCAL (preferred, no hardware)**: disassemble 0x6A2D8 (the real PHY worker that 0x34DE0 tail-calls 8× from inside wlc_phy_attach). Look for tight polling loops (`ldr/tst/bne-back`) targeting PHY-core registers. This is the next narrowing step after T253's local analysis. Output: identify specific register/mask fw is polling. Deliverable: `phase5/analysis/T254_6a2d8_worker.md`.

2. **T254 HARDWARE (if local work leaves gaps)**: probe TCM[0x93550..0x9358C] (16 u32) to decode 0x9355C — the only unfollowed pointer in 0x934C0's populated fields. Same cost as T253 (~32 reads), same wedge expectation. Deferred until local analysis of 0x6A2D8 is done, since local work may change what we want to know about 0x9355C.

Advisor call before committing to T254 design.

---

## POST-TEST.254 (2026-04-23 19:0x BST — local disassembly only, no hardware test)

T254 was a local-analysis pass (no kernel module load, no crash). Deliverable: `phase5/analysis/T254_phy_subtree.md`. Scripts: `t254_6a2d8_worker.py`, `t254_dispatch_scan.py`, `t254_poll_detail.py`.

### What test.254 landed (facts)

- **0x6A2D8 has no backward branches** — no loops, cannot be the hang. Structured as setup + tail-call to 0x52B8 (a comma-separated-string iterator — not hardware).
- **wlc_phy_attach's dispatch-table exposure is narrow**: only TWO direct calls into 0x38A50 table, both at index 0 → target 0x15940 (also loop-free).
- **Scanned all 17 dispatch-table targets reachable via 0x38A50/0x38A24**: only one tight hardware-poll candidate, at target **0x1722C**.
- **0x1722C is `wlc_bmac_suspend_mac_and_wait`** (function name string at blob[0x4B189]). Polling loop at 0x173D8..0x173EC (8 insns) reads `[r4 + 0x128]` bit 0 with r7 countdown from 0x14441. On timeout **falls through without assert** — and uses the bounded `bl #0x1ADC` delay.
- **Delay helper 0x1ADC is bounded via PMCCNTR** (CP15 `mrc p15,0,r0,c9,c13,0` at 0x1EC). PMCCNTR is enabled early in boot (PMCR writes at 0x1D6 and 0x1DC: `mcr p15,0,r1,c9,c12,0/1`). Blob init tick-scale at TCM[0x58C98] = 0x50 → `delay(10)` ≈ 10 µs → 82ms total wall-clock for the 0x1722C poll.
- **"40/160/160MHz" line IS the RTE boot banner** at blob[0x6BAE5]: `"RTE (%s-%s%s%s) %s on BCM%s r%d @ %d.%d/%d.%d/%d.%dMHz"` — printed very early in fw boot, NOT by wlc_attach. T251 reading "last printed line is wlc_attach banner" is **revised**. Fw hung AFTER RTE banner, anywhere in the remaining init.
- **Chiprev banner call site pinpointed**: blob[0x06876E] LDR + blob[0x06877A] BL to printf 0xA30. Uses format at blob[0x4C534]. Same function references `"wlc_bmac_attach"` string at blob[0x4B121] from 0x68778 → **confirmed inside wlc_bmac_attach**. Fw never reached this printf → hang is in wlc_bmac_attach's execution BEFORE byte 0x06877A.
- **WFI check**: exactly 1 WFI (0xBF30) in blob at offset 0x001C1E — in early boot code, not reachable from wlc path. None inside wlc_bmac_attach / wlc_phy_attach range.
- **Self-loop (`b .` = 0xE7FE) check**: 6 occurrences total. Four at 0x25E/0x290/0x326/0x53E are real early-boot fault handlers. Two apparent hits at blob[0x464F6] and blob[0x468F4] are **false positives** — surrounding bytes disassemble as garbage (junk strings `"kkkk::::"`, `"V22dN::t"` nearby, repeated identical instructions at adjacent offsets, no reachable BL/B targeting them). Data, not code. **No reachable unbounded-wait primitive in wlc path.**

### What test.254 settled (facts)

- **The hang is NOT a direct polling loop in the fw code region**. All three candidate polling loops (0x1415C, 0x1722C, 0x14CAC) are built on PMCCNTR-backed `bl #0x1ADC` and have finite wall-clock timeouts ≤ 82ms. Bounded loops do not silently hang for 60+ seconds.
- **Saved LR 0x68321 is the return address of `bl #0x1415C` at 0x6831E** inside wlc_bmac_attach (T253 identified 0x1415C as SB-core reset waiter; T254 confirms caller context). So fw was inside 0x1415C or one of its transitive callees at capture time — but those are also all bounded.
- **Remaining hang candidates** (in priority order, post-T254):
  - **(A) Cross-core / backplane wait** — fw issued a transaction targeting an unclocked or stuck SB core; the bus read backpressures the ARM core indefinitely. CPU is stalled at memory-subsystem level, not at instruction level. Saved LR reflects the last completed call return before the stall. This best matches all observed evidence (silent hang, no advancement in any counter, ring/canary intact, probes from host-side work fine).
  - **(B) Inter-thread wait** — an RTOS task waiting on a semaphore/queue; the hung task may be different from the one captured in the saved-state. T253 didn't find TCB/task-table primitives in any captured struct — reducing likelihood.
  - **(C) Tick-scale corruption** — TCM[0x58C98] (blob default 0x50) overwritten mid-run to 0xFFFFFFFF, making `target = units * scale` overflow and the delay loop effectively unbounded.
- **wlc_phy_attach's own body NOT under suspicion**: 213 insns, only 2 direct dispatch calls both to idx-0 (benign), no tight loops, all BL targets have bounded loops or no loops. Moves emphasis AWAY from the "inside wlc_phy_attach" reading.

### Next-test direction (T255 — candidates for advisor review)

Back to hardware probes, informed by T254 narrowing:

1. **Cheapest: TCM[0x58C98..+4]** — verify tick-scale at hang time (1 u32 read). Settles (C) — if value == 0x50, (C) falsified; if corrupted, strong new lead.
2. **TCM[0x93550..0x9358C]** (16 u32) — decode 0x9355C, the forward-linked pointer from 0x934C0. Same risk profile as T253.
3. **Higher-risk: sample PHY/MAC `[core_base + 0x128]` via BAR0** — the register the 0x1722C polling loop reads. Needs careful gate-on-core-reset-state check; accessing an unclocked core can wedge the bus. Design caution warranted.
4. **Enumerate RTOS task-table** — requires finding the task-control-block magic layout. Defer until cheaper paths exhausted.

Advisor call before committing to T255 design.

---
