# T272-FW — Firmware init-chain trace between wlc_bmac_attach and pcidongle_probe

**Date:** 2026-04-24 (post-T269 fw-blob diss + T271 pre-code blocker)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Read-only capstone (Thumb) disassembly; brute-force BL/BLX scan; literal-pool xref; string xref.
**Scripts:** `phase6/t272_callers.py`, `t272_xref.py`, `t272_string_search.py`, `t272_windows.py` (and `/tmp/t272_*.py` ad-hoc helpers — key findings reproduced here).
**Clean-room note:** structures and identities described in plain language from mnemonics + literal-pool / ASCII-string cross-references. No reconstructed function bodies committed beyond short illustrative snippets.

## TL;DR

- Found the **device-registration struct layout** fw uses: both `wlc` (struct base `0x58EFC`) and `pciedngldev` (struct base `~0x58C88`) are registered with function-pointer tables. `wlc`'s probe is `fn@0x67614`; `pciedngldev`'s probe is `pcidongle_probe` (`0x1E90`).
- Direct call chain (innermost first): `wlc_phy_attach (0x6A954) ← wlc_bmac_attach (0x6820C) ← fn@0x68A68 ← fn@0x67614 ← (indirect dispatch through the wlc fn-table)`.
- **fn@0x67614 has zero direct BL callers** — reached only through indirect dispatch via the wlc function table at `0x58F1C`. Same pattern as `pcidongle_probe`. Both are invoked by an RTE device-probe-iterator walking a list of registered devices.
- The saved-LR snapshot from T251 resolves to: last completed BL at `0x6831C → bl #0x1415C` (SB-core-reset-waiter, bounded 20ms per T253). So wlc_bmac_attach HAD progressed at least to that call site and fn_1415C had returned (per T254 bounded-loop reading).
- **After the saved-LR return point (`0x68320`)**, wlc_bmac_attach continues with two un-traced sub-calls: **`bl #0x15940`** (already cleared by T254) and **`bl #0x179c8`** (NEW — not yet traced for polling loops).
- **Second un-traced path**: `fn@0x68A68` calls **`bl #0x67F2C`** BEFORE calling wlc_bmac_attach. This call is not in prior T253/T254 analyses.
- Dispatch-table entries in the pciedngl function table at `0x58C88..0x58CFC`: probe (`pcidongle_probe`), plus five other fn-ptrs at `0x58CA0/0x58CA4/0x58CA8/0x58CB0` (attach helpers) and ISR (`pciedngl_isr` at `0x58CB8`). Tick-scale word at `0x58C98 = 0x50` matches T254 finding.

## 1. Anchor addresses and how they were confirmed

| Name | Address | Evidence |
|---|---|---|
| `pciedngl_isr` | `0x1C98` | T269 analysis — 5 internal string xrefs |
| `pcidongle_probe` | `0x1E90` | T269 analysis — BL target from `hndrte_add_isr` registration site at `0x1F28` |
| `hndrte_add_isr` | `0x63C24` | T269 analysis — registration call site in `pcidongle_probe` |
| `wlc_bmac_attach` | `0x6820C` | fn-start found by `find_function_start(0x6865E)`; prologue `push.w {r4..fp, lr}`; body contains 9 references to "wlc_bmac_attach" trace string at `0x4B121` |
| `wlc_phy_attach` | `0x6A954` | T253 analysis — called from `0x6865E` inside `wlc_bmac_attach` |
| `fn@0x67614` | `0x67614` | Direct BL caller of `fn@0x68A68` |
| `fn@0x68A68` | `0x68A68` | Direct BL caller of `wlc_bmac_attach` at `0x68B90` |

### What about wlc_attach?

The ASCII string `"wlc_attach"` at blob offset `0x4B1FF` is referenced via literal-pool only from inside `wlc_bmac_attach`'s body (`0x68AEE`, `0x68B2E`, `0x68BF4` all LDR lit@`0x68C74`). No separate `wlc_attach` function body uses its own name as a trace string in this blob. Interpretation: `"wlc_attach"` is used as a stage-name label in trace messages emitted from `wlc_bmac_attach`'s error paths, not as the trace-name of a dedicated function. The function-chain role played by "wlc_attach" is filled by `fn@0x67614` (the wlc-device probe entry) and `fn@0x68A68` (intermediate wrapper), neither of which print `"wlc_attach"` themselves.

## 2. Device-registration structs

### 2.1 pciedngldev struct (base ~0x58C88)

```
[0x58C88] = 0x00000001     ; class/version
[0x58C8C] = 0x00002F5C
[0x58C90] = 0x00000020
[0x58C94] = 0x0000001F
[0x58C98] = 0x00000050     ; tick scale (per T254 §4)
[0x58C9C] = 0x1E91         ; probe    → pcidongle_probe
[0x58CA0] = 0x1C75         ; fn @ 0x1C74
[0x58CA4] = 0x1C51         ; fn @ 0x1C50
[0x58CA8] = 0x1D9D         ; fn @ 0x1D9C
[0x58CAC] = 0
[0x58CB0] = 0x1C39         ; fn @ 0x1C38
[0x58CB4] = 0
[0x58CB8] = 0x1C99         ; isr     → pciedngl_isr
[0x58CBC] = 0
[0x58CC0] = 0
[0x58CC4] = "pciedngldev\0"
[0x58CD4] = 0x00058C9C     ; self-ref to probe slot
```

**Literal-pool refs into this struct:**
- `0x58C88` (class word) referenced from `0x1130` — likely a false-positive byte match (surrounding disasm is gibberish / data region).
- `0x58C98` (tick-scale) referenced from `0x1AF8`, `0x63FA8`, `0x63FCC` — these are the delay-scale fetch sites.
- `0x58C9C` (probe slot) referenced only by the struct's own self-ref at `0x58CD4`.
- `0x58CC4` (name string) referenced from `0x6455C` — but `0x6454C..0x6458C` disassembles as data, not code. This is likely a bigger **device-list table** in which this struct is an entry.
- `0x58CB8` (isr slot) has an additional code-ref at `0x58B7A` (from T269).

### 2.2 wlc struct (base 0x58EFC)

```
[0x58EFC] = 0
[0x58F00] = 0x00058F1C     ; self-ref to fn-table
[0x58F04..0x58F18] = 0
[0x58F1C] = 0x67615        ; probe → fn@0x67614
[0x58F20] = 0x11649        ; fn @ 0x11648 (detach?)
[0x58F24] = 0x1132D        ; fn @ 0x1132C (up?)
[0x58F28] = 0x11605        ; fn @ 0x11604 (down?)
[0x58F2C] = 0
[0x58F30] = 0x1158D        ; fn @ 0x1158C
[0x58F34] = 0x11525        ; fn @ 0x11524
[0x58F38] = 0x1146D        ; fn @ 0x1146C
```

Function-table layout matches `pciedngldev`'s: probe at offset 0, plus several tail-slot fn-ptrs. **No direct literal-pool refs to `0x58EFC`, `0x58F00`, or `0x58F1C` from elsewhere in code** — the struct is visible only via static linkage (fw link-time device list).

## 3. Direct call chain

```
RTE init
  │
  └─ device-probe-iterator (iterates a static list of device structs)
      │
      ├─ WLC device:
      │   probe slot [0x58F1C] → fn@0x67614
      │         │
      │         └─ (direct BL at 0x67700) → fn@0x68A68
      │               │
      │               ├─ bl #0x67F2C              ← NEW un-traced
      │               └─ (direct BL at 0x68B90) → wlc_bmac_attach (0x6820C)
      │                     │
      │                     ├─ ...various init helpers...
      │                     ├─ bl #0x1415C  (SB-core-reset waiter; T253/T254 bounded 20ms)
      │                     │      └─ returns to 0x68320 (saved-LR 0x68321 observed in T251)
      │                     ├─ bl #0x15940  (T254 clean — no loops)
      │                     ├─ bl #0x179C8                  ← NEW un-traced
      │                     ├─ bl #0x6A954  (wlc_phy_attach — T254 subtree clean)
      │                     └─ (more tail calls, not fully traced)
      │
      └─ PCIEDNGLDEV device:
          probe slot [0x58C9C] → pcidongle_probe (0x1E90)
                │
                ├─ bl #0xA30  (printf "pciedngl_probe...")
                ├─ bl #0x66E64
                ├─ bl #0x7D60 (alloc)
                ├─ bl #0x91C  (memset)
                ├─ bl #0x67358
                ├─ bl #0x9948
                ├─ bl #0x9964
                ├─ bl #0x64248
                ├─ bl #0x1298 (node heap-alloc)
                ├─ bl #0x63C24 (hndrte_add_isr → pciedngl_isr registered with bit 3)
                └─ ... publishes sharedram_addr at TCM[ramsize-4]
                    ... sets shared.flags |= HOSTRDY_DB1 (0x10000000)
```

### 3.1 Direct-caller count per node

| Fn | Direct BL callers in blob | Notes |
|---|---|---|
| `pcidongle_probe` (0x1E90) | 0 | reached only via indirect dispatch through pciedngldev fn-table |
| `fn@0x67614` (wlc probe top) | 0 | reached only via indirect dispatch through wlc fn-table |
| `fn@0x68A68` | 1 (from `0x67700` = inside fn@0x67614) | |
| `wlc_bmac_attach` (0x6820C) | 1 (from `0x68B90` = inside fn@0x68A68) | |
| `wlc_phy_attach` (0x6A954) | 1 (from `0x6865E` = inside wlc_bmac_attach) | matches T253 |
| `hndrte_add_isr` (0x63C24) | 3 (0x1F28, 0x63CF0, 0x67774) | 0x1F28 is inside pcidongle_probe per T269 |

## 4. Where the hang is now bracketed

Combining prior analyses:

- **Entry**: RTE boot completes (banner fires, T250).
- **si_attach completes**: T252 (0x92440 populated with CC base 0x18001000).
- **wlc-probe starts**: fw enters the wlc-device probe, i.e. fn@0x67614.
- **wlc_bmac_attach reached**: T251 saved-LR 0x68321 places fw inside wlc_bmac_attach at (or past) the BL to fn_1415C. fn_1415C is bounded (T253/T254), so it returned.
- **wlc_bmac_attach still running**: the saved-LR represents a return point, so PC at the moment of the snapshot was ≥ 0x68320. But T255 scheduler-state probe showed fw is in WFI (no callback runnable). Either:
  - fw returned from wlc_bmac_attach and the scheduler ran out of immediately-runnable tasks (waiting on an event that never fires), OR
  - fw is inside a later part of wlc_bmac_attach that blocks waiting on an event.

- **pciedngldev-probe NOT reached**: T247 observed TCM[ramsize-4] = 0xFFC70038 (NVRAM trailer) unchanged across 23 dwells → `pcidongle_probe` never ran its sharedram-publish step.

### 4.1 Two untraced sub-trees in wlc_bmac_attach's tail

The saved-LR at 0x68320 is in the tail region of wlc_bmac_attach. Continuation from that point:

```
0x68320:  mov    r0, r4
0x68326:  bl     #0x15940      ; T254: clean, no loops
0x6832A:  mov    r0, r4
0x6832C:  bl     #0x179C8      ; UNTRACED
0x68330:  cbnz   r0, +0x28     ; if r0 != 0, jump past error path
0x68332:  ... (error/trace on r0 == 0) ...
0x6835A:  mov    r0, sb
0x6835E:  bl     #0x52A2       ; lookup/parse helper
0x6836C:  mov    r0, r4
0x6836E:  bl     #0x67E1C      ; UNTRACED
0x683A4:  (more work if r0 != 0)
```

**Highest-priority untraced callee**: `bl #0x179C8` at 0x6832C. This is the very next unchecked call after the observed saved-LR return point. If it polls or blocks, the hang is there.

**Second priority**: `bl #0x67E1C` at 0x6836E. Next BL in the continuation chain.

**Third priority**: `bl #0x67F2C` at 0x68ACA (inside fn@0x68A68, BEFORE the call to wlc_bmac_attach). But evidence from T251 suggests wlc_bmac_attach DID run at least partway, which means fn@0x68A68 reached the bl wlc_bmac_attach call. So fn@0x67F2C completed successfully or was skipped-via-branch — less likely to be the hang site.

### 4.2 What `0x179C8` might be

Not yet disassembled. Heuristic predictions based on its position in wlc_bmac_attach's init flow (right after fn_1415C SB-core-reset-wait and a clean dispatcher call 0x15940):

- Most likely: **another hardware-register-waiter** (PHY/MAC subsystem bringup waiting on a state bit). If its polling loop has a stuck condition (bit never transitions), this would match the observed freeze exactly — timing (tens of milliseconds after insmod), no trace output after set_active, scheduler eventually goes idle because no other runnable task exists.
- Less likely: a dispatcher (like 0x15940) with no loop.
- Unlikely: an alloc/free helper (those are much shorter and don't usually fail silently).

## 5. What would nail it down

### 5.1 Continue fw-blob analysis (cheapest)

Disassemble the two untraced calls:

- `0x179C8` (highest priority — first BL after saved-LR return point)
- `0x67E1C` (second priority)
- `0x67F2C` (tertiary, in fn@0x68A68 pre-wlc_bmac_attach path)

Look for:
- Backward branches (polling loops) — especially those reading a HW register via BAR/SB-core window that tests a bit and loops with a `bne` condition.
- Calls to delay helpers (`0x1ADC`, `0x11C8`, or similar).
- Tail-calls into dispatchers (which T254 traced) — these are likely clean.

Decision matrix for next step:
- If `0x179C8` has an unbounded polling pattern with a host-dependent condition (a bit that only flips when host writes something), **hang location identified** — the fix is to set that bit before fw reaches 0x179C8.
- If `0x179C8` is a bounded helper (like 0x1415C or 0x15940), move priority to `0x67E1C`.
- If none of the three have polling loops, the hang is in tail-called sub-dispatchers and we need a wider-tree scan.

### 5.2 Alternative: hardware probe (more expensive)

Add a probe that reads a stack-walk of the saved-state region at multiple dwell points (not just one, like T251). If the top-of-stack LR drifts between t+100ms and t+90s, fw is still active (hang is later). If it stays frozen at ~0x68320, hang is exactly at the observed point.

Requires substrate budget + scaffold code change; static analysis is cheaper and can answer the same question in most scenarios.

## 6. Clean-room posture

All observations are: (1) capstone Thumb disassembly mnemonics + operands; (2) literal-pool dword-aligned searches; (3) ASCII-string cross-references. Function roles are described in plain language. No reconstructed function bodies are included beyond short illustrative snippets needed for explanation. Disassembly tools are in `phase6/t272_*.py` and disassemble the vendor blob locally, printing to stdout.

## 7. Deliverables summary

- This document (`phase6/t272_init_chain.md`).
- Scripts `phase6/t272_callers.py`, `t272_xref.py`, `t272_string_search.py`, `t272_windows.py` — reusable xref helpers.
- Clear next step: disassemble `0x179C8`, `0x67E1C`, `0x67F2C` bodies and classify them as bounded / polling-with-HW-dep / tail-call. That work is the natural continuation (T273-FW).
