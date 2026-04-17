# test.102 LR → function interpretation table

Purpose: pre-computed BEFORE running test.102, so sweep results can be
interpreted without ambiguity.

Format: each entry is `LR_value = return_address_after_bl` (the value the
CPU pushes on the stack when a `bl` executes). Thumb code → LSB is set
(odd). Derived from:
- test88_disassembly.txt (pciedngl_probe, fn 0x67358, fn 0x670d8 prefix)
- test90_disassembly.txt (fn 0x66e00..0x673a0 — includes 0x670d8 body)
- test91_disasm.txt (fn 0x64400..0x64a5a — includes si_attach 0x64590)
- offline_disasm_68a68_body.md (fn 0x68a68 body — /tmp/disasm.log)

**All addresses are Thumb mode: actual LR value = `addr | 1`.**
Filter for candidacy: `word ∈ [0x800..0x70000]` AND `word & 1`.

## Expected live chain (hang is inside 0x67358 descent per offline disasm)

Top of stack (deepest nested call) → bottom (root):

### Frame 0: wl_probe's caller → wl_probe
(c_init → dngl_binddev → wl_probe — LRs not useful here since we know
wl_probe is running)

### Frame 1: wl_probe (fn 0x67614) — called bl 0x68a68
| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x67700 | 0x68a68 (wlc_attach) | **0x67705** |

### Frame 2: wlc_attach (fn 0x68a68) — called bl 0x67f2c
(only the first body BL matters — if hang is past it, subsequent BLs'
LRs would appear instead)

| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x68aca | 0x67f2c (trampoline) | **0x68acf** |
| 0x68b02 | 0x5250 (nvram_get) | 0x68b07 |
| 0x68b0c | 0x50e8 (strtoul) | 0x68b11 |
| 0x68b42 | 0x67cbc (struct setup) | 0x68b47 |
| 0x68b90 | 0x6820c | 0x68b95 |
| 0x68ba0 | 0x191dc (chip-id) | 0x68ba5 |
| 0x68bcc | 0x1ab50 (PHY — test.100 excluded) | 0x68bd1 |

### 0x67f2c trampoline — NO FRAME
```
0x67f2c: push {r4, lr}
0x67f2e: ldr r4, [sp, #0x10]
0x67f30: pop.w {r4, lr}        ; restores r4, lr
0x67f34: b.w 0x67358            ; tail call — no frame persists
```
So 0x67358 is entered with LR = wlc_attach's 0x68acf (unchanged by
trampoline).

### Frame 3: fn 0x67358 — called bl 0x670d8
Per test88_disassembly.txt:
| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x6736e | 0x7d60 (malloc) | 0x67373 |
| 0x67378 | 0x7d6e (size) | 0x6737d |
| 0x67380 | 0xa30 (printf) | 0x67385 |
| 0x67398 | 0x670d8 (deep init) | **0x6739d** |
| 0x673a8 | 0x7d68 (free) | 0x673ad |

### Frame 4: fn 0x670d8 — called bl 0x64590 (si_attach) and more
Per test90_disassembly.txt (extracted BLs):
| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x670fc | 0x11e8 (ASSERT) | 0x67101 |
| 0x67108 | 0x91c (memset) | 0x6710d |
| 0x67128 | 0xa30 (printf) | 0x6712d |
| 0x67136 | 0xa30 | 0x6713b |
| 0x67146 | 0x66ef4 | 0x6714b |
| 0x67150 | 0xa30 | 0x67155 |
| 0x67186 | 0xa30 | 0x6718b |
| 0x67190 | 0x64590 (si_attach) | **0x67195** |
| 0x671b0 | 0x66fc4 (core enum) | **0x671b5** |
| 0x671bc | 0x66ec0 (list register) | **0x671c1** |
| 0x671d0 | 0x66a18 | **0x671d5** |
| 0x671d8 | 0xa30 | 0x671dd |
| 0x671f2 | 0x66ef8 | **0x671f7** |
| 0x6720a | 0x9990 | 0x6720f |
| 0x67218 | 0x11e8 | 0x6721d |
| 0x67226 | 0x99ac | 0x6722b |
| 0x6722e | 0x66d04 | 0x67233 |
| 0x67236 | 0x66d68 | 0x6723b |
| 0x6723e | 0x52a2 | 0x67243 |
| 0x67248 | 0x66dd0 | 0x6724d |
| 0x67250 | 0x66da8 | 0x67255 |
| 0x6725c | 0x5250 | 0x67261 |
| 0x67266 | 0x52a2 | 0x6726b |
| 0x6726e | 0x6708c | 0x67273 |

### Frame 5: fn 0x64590 (si_attach) — partial, per test91_disasm.txt
| BL site | Target | LR pushed |
|---------|--------|-----------|
| 0x645ae | 0x2704 (EROM parse) | 0x645b3 |
| 0x645c2 | 0x2704 | 0x645c7 |
| 0x64638 | 0x2728 (EROM parse) | 0x6463d |
| 0x64674 | 0x6458c | 0x64679 |
| 0x6468a | 0x2704 | 0x6468f |
| 0x646bc | 0x2728 | 0x646c1 |
| 0x646e6 | 0x2728 | 0x646eb |
| 0x64708 | 0xa30 | 0x6470d |
| 0x64712 | 0xa30 | 0x64717 |
| 0x64744 | 0x2728 | 0x64749 |
| 0x6478a | 0x2728 | 0x6478f |
| 0x647cc | 0x2728 | 0x647d1 |
| 0x64820 | 0x2728 | 0x64825 |
| 0x64860 | 0xa30 | 0x64865 |
| 0x64896 | 0xa30 | 0x6489b |

### Frame 6+: deeper children (0x66fc4 core enum, 0x66ec0 list register,
0x66a18, 0x66ef8 — not yet disassembled in detail)

## High-signal LRs to watch for

**Most likely to appear** (chain top, one per frame):
- **0x67705** — wl_probe after bl 0x68a68 (if wlc_attach still running)
- **0x68acf** — wlc_attach after bl 0x67f2c (if 0x67358 descent running)
- **0x6739d** — fn 0x67358 after bl 0x670d8 (if 0x670d8 running)
- **0x67195** — fn 0x670d8 after bl 0x64590 (si_attach) OR
- **0x671b5** — fn 0x670d8 after bl 0x66fc4 (core enum) OR
- **0x671c1** — fn 0x670d8 after bl 0x66ec0 (list register) OR
- **0x671d5** / **0x671f7** — fn 0x670d8 after later sub-BLs

**Interpretation by deepest seen:**
- Deepest = 0x67195 or 0x645xx → hang in si_attach (0x64590) or one of
  its unexplored branches (EROM iteration, core registration)
- Deepest = 0x671b5 → hang in core enum (0x66fc4) → needs offline disasm
- Deepest = 0x671c1 → hang in list register (0x66ec0) or its child 0x66e90
  — noteworthy because 0x66ec0 takes error-printf path on re-entry
- Deepest = 0x671d5 or 0x671f7 → hang in later 0x670d8 children (0x66a18,
  0x66ef8)

## False-positive handling

A single odd-bit word in [0x800..0x70000] is weak evidence — could be:
- Data that happens to match the filter
- A saved LR from a DIFFERENT, already-returned call (stale)
- A function pointer stored as data in a struct

**Confirmed = ≥2 LRs from this table present in the 16-word sweep,
forming a known caller→callee chain** (e.g. 0x68acf + 0x6739d — wlc_attach
called 0x67358 which called 0x670d8). That pattern can't arise by
coincidence.

If only 1 LR matches, or the matches don't chain: test.103 should do a
dense follow-up (32 reads × 4B stride) around the region where the hit
landed to capture the full frame chain.
