# T251 Local Blob Analysis — Hang Narrowed to wlc_phy_attach

**Date:** 2026-04-23 (post-T251 capture, pre-T252)
**Blob:** `/lib/firmware/brcm/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Local read-only blob analysis. No hardware test.

## Blob → TCM mapping (verified)

- Blob size 0x6BF79 ≈ observed code upper bound 0x6BF78.
- TCM offset N (for N < 0x6BF78) corresponds to blob byte N directly. No header.
- Verified by: ASCII strings observed in T250 (Chipc fmt) located at exact blob offsets; literal-pool addresses in code resolve to expected fmt strings.

## Last-printed-line — fmt string and call site

Observed in T251 ring at TCM[0x9CE30..0x9CE58]:
> `"...(r) on BCM4360 r3 @ 40.0/160.0/160.0MHz\n"`

Fmt string: blob[0x6BAE4] = `"\nRTE (%s-%s%s%s) %s on BCM%s r%d @ %d.%d/%d.%d/%d.%dMHz"`

Call site: blob[0x6454C] = literal-pool entry holding 0x6BAE4. The printf code lives at ~0x64500..0x64530 (function epilogue at 0x64534 = `pop {r4-r11,pc}`). This printf fires once per attach inside the early `wl_probe`/`dngl_probe` flow.

## Next-fmt-string-fw-would-have-printed (never observed)

Right after the RTE banner fmt in the strings region: blob[0x6BB1D] = `" wl%d: Broadcom BCM%04x 802.11 Wireless Controller %s FWID 01-%x"`

Call site: blob[0x678BC]. This banner is printed AFTER wlc_attach completes successfully. We never saw it → fw is stuck before wlc_attach returns.

## Saved-state region PC decode

T251 captured these Thumb-mode (LSB=1) addresses in TCM[0x9CE98..0x9CF34]:

| Saved value | Code addr | Region | Notes |
|---|---|---|---|
| 0x000475B5 | 0x475B4 | inside Chipc fmt string | Likely fmt-string ref with tag bit, NOT a PC |
| 0x00012C69 | 0x12C68 | Early utility | Function epilogue at 0x12C66; saved LR for return |
| 0x00068D2F | 0x68D2E | **wlc_attach** | Literal pool 0x68C6C..0x68C88 has 'wlc_attach', 'si_attach failed', 'wlc_attach: failed with err %d' |
| 0x00068321 | 0x68320 | **wlc_bmac_attach** | Literal pool 0x687B8..0x687D0 has 'wlc_bmac_attach', 'wlc_phy_shim_attach failed', 'wlc_phy_attach failed', 'chiprev...phy_type %d phy_rev %d' |
| 0x00005271 | 0x5270 | Early utility | Pattern looks like string/byte processing (`ldrb [r3],#1`) |

## Saved PC verification (Thumb-2 BL preceding bytes)

Confirmed each saved PC lies right after a Thumb-2 BL instruction (signature: first halfword high byte 0xF0..0xF7, second halfword high nibble C/D/F):

| Saved PC | Bytes at PC-4 | Decoded | BL target |
|---|---|---|---|
| 0x12C68 | `ed f7 5a fe` | Thumb-2 BL | 0x00091C (function start ~0x87C) |
| 0x68D2E | `a9 f7 79 ff` | Thumb-2 BL | 0x012C20 (function entry) |
| 0x68320 | `ab f7 1e ff` | Thumb-2 BL | 0x01415C (function entry) |
| 0x5270  | `fb f7 b8 fa` | Thumb-2 BL | 0x0007E0 (function entry) |
| 0x475B4 | `73 20 30 78` (ASCII "s 0x") | NOT a BL | confirmed = fmt-string ref with tag bit |

All four code-region PCs are real return addresses from BL calls. 0x475B5 is confirmed as a fmt-string pointer (with Thumb tag), not a PC.

## Hypothesised call relationships (NOT confirmed as a stack)

The saved-state region is **not necessarily a clean stack snapshot**. Reasons to be cautious:
- 5× repeats of 0x93610 don't fit a typical stack pattern (stacks rarely have one ptr 5×).
- The PC ordering in memory (0x12C69, 0x68D2F, 0x68321, 0x5271 from low→high addr) doesn't match a clean caller→callee chain (0x68321/wlc_bmac_attach appearing OLDER than 0x68D2F/wlc_attach is backwards from expected nesting).
- More likely: a task-context-save area, RTOS task descriptor table, or a heterogeneous trap/state record.

What IS strongly supported:
- **0x68D2E is in (or very near) wlc_attach** — its literal pool has `'wlc_attach'`, `'si_attach failed'`, `'wlc_attach: failed with err %d'`.
- **0x68320 is in (or very near) wlc_bmac_attach** — its literal pool has `'wlc_bmac_attach'`, `'wlc_phy_shim_attach failed'`, `'wlc_phy_attach failed'`, `'chiprev...phy_type %d phy_rev %d'`.
- The fmt `'wl%d: %s: chiprev %d corerev %d cccap 0x%x maccap 0x%x band %sG, phy_type %d phy_rev %d'` (blob[0x4C534]) is the LAST line wlc_bmac_attach prints — fires only AFTER wlc_phy_attach returns. We never saw it in any ring dump. **wlc_phy_attach has not returned, OR fw hung at an earlier point in wlc_bmac_attach (before the chiprev banner).**

So the conservative claim: hang is somewhere inside the wlc_attach → wlc_bmac_attach call tree, BEFORE the wlc_bmac_attach chiprev banner fires. The literal narrowing to "inside wlc_phy_attach" requires assuming the saved PCs reflect the actual call stack, which is unverified.

## Confirmed fmt strings used in observed log

| Observed text | Fmt-string addr | Notes |
|---|---|---|
| `"Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"` | blob[0x47579] | Chipc init; called from blob[0x67088] |
| `"wl_probe called"` | blob[0x40692] = `'%s called\n'` | Generic; arg `wl_probe` from blob[0x4A1EA] |
| `"dngl_probe called"` | blob[0x40692] | Same fmt; arg `dngl_probe` from elsewhere |
| `"...RTE (PCIE-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"` | blob[0x6BAE4] | Called from blob[0x6454C] |

## Repeated TCM data offsets in saved-state region

These appeared with high repetition (5×, 3×, 3×) — they are TCM addresses ABOVE the code segment (> 0x6BF78), so NOT in the blob — runtime BSS/heap data.

| Offset | Repetition | Likely meaning |
|---|---|---|
| 0x00093610 | 5× | Active task/struct descriptor (frequent ref → "current pointer") |
| 0x00092440 | 3× | Possibly secondary/queue pointer |
| 0x00091CC4 | 3× | Possibly third related pointer |
| 0x000934C0 | 1× (also seen at TCM[0x9CFE0] T248) | Trap-region head candidate |

These could be:
- Active task control blocks for a scheduler
- A linked list head + queued items
- Saved register set with several `r5`/`r6`/etc holding the same struct ptr

## Re-interpretation: 0x000043B1 is not a counter

Found at:
- TCM[0x9D000] (the "frozen counter" — n=3 across T249/250/251)
- TCM[0x9CF2C] (the saved-state region, T251)

Same value at two different locations strongly suggests this is a **saved register** or **token** that fw wrote to multiple places, not a periodic-update counter. Test.89's "single-write reading" was correct in mechanism but wrong in interpretation — 0x9D000 isn't a tick counter; it's a saved-state field.

Decimal: 0x43B1 = 17329. Could be:
- A task ID
- An interrupt vector number
- A PHY register or PLL setting value
- A loop counter at the moment of hang

## Open questions / next probes

1. **What's at TCM[0x93610]?** Reading 0x9361X..0x93640 would reveal the active descriptor structure pointed to by the saved-state region. This is BSS data, populated at runtime.
2. **Walk the ring backwards** from 0x9CC80 → find log records leading up to the RTE banner. Might reveal e.g. "si_kattach done" or "Found chip type AI" messages confirming si_doattach succeeded.
3. **Look for PHY/radio polling loops** in code area 0x6900..0x6BFXX (above wlc_attach), or in early code (around fn 0x1FC2 area) — wait-loops typically have a tight pattern: `loop: ldr r0, [reg]; tst r0, mask; beq loop`.

## Clean-room note

All observations above are: (1) fmt-string text reads, (2) literal-pool address resolution, (3) function boundary identification by epilogue patterns. No instruction sequences are reproduced. Conclusions are derived from address↔string mapping + observed log content + behavioral inference.
