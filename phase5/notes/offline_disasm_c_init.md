# Offline disassembly: c_init() and the RTE banner site

**Date:** 2026-04-16 (post test.99)
**Source binary:** `phase1/output/firmware_4352pci.bin` (442233 bytes, md5 812705b3...) — confirmed identical to the loaded `/lib/firmware/brcm/brcmfmac4360-pcie.bin`.

## Loader assumptions

- Firmware loaded at TCM base 0x00000000. File offset == TCM virtual address for code/.data.
- Pointer values in code may carry the high `0x80000000` bit (mirror/uncached alias) — but literal pools we inspected use the raw 0x000xxxxx form.

## Banner format string

| TCM addr | Content |
|----------|---------|
| 0x6bae4  | `\nRTE (%s-%s%s%s) %s on BCM%s r%d @ %d.%d/%d.%d/%d.%dMHz\n\0` |
| 0x40c2f  | `6.30.223 (TOB) (r)` (banner version arg) |

## c_init() — function start at TCM 0x642fc

- Prologue at 0x642fc: `2d e9 f0 4f` (`push.w {r4-r11, lr}`) — large-frame Thumb-2 function.
- Code body: 0x642fc … 0x6453e (~322 bytes).
- Literal pool: 0x64540 … 0x6458c.
- Next function (`si_attach`) starts at 0x64590 — matches RESUME_NOTES.

### Literal pool decoded (0x64540–0x6458c)

| Pool offset | Value      | Resolves to |
|-------------|------------|-------------|
| 0x64540     | 0x40bfa    | `"c_init"` (function name string) |
| 0x64544     | 0x000f4240 | 1000000 (decimal — likely a delay/timeout const) |
| 0x64548     | 0x4227e    | (data, not string) |
| 0x6454c     | **0x6bae4** | **RTE banner format string** |
| 0x64550     | 0x40c27    | `"PCI"` (banner arg) |
| 0x64554     | 0x40c2b    | `"CDC"` (banner arg) |
| 0x64558     | 0x40c42    | `"%s:   c_init: add PCI device\n\n"` |
| 0x6455c     | 0x58cc4    | `"pciedngldev"` |
| 0x64560     | **0x58cf0** | pciedngl_probe vtable (test.99 saw this written to *0x62a14) |
| 0x64564     | **0x62a14** | TCM addr where vtable ptr is stored |
| 0x64568     | 0x40c61    | `"%s: add WL device 0x%x\n"` |
| 0x6456c     | 0x58ef0    | `"wl"` |
| 0x64570     | 0x40c79    | `"rtecdc.c"` |
| 0x64574     | 0x40c82    | `"%s: %s%s device binddev failed\n"` ← **failure path 1** |
| 0x64578     | 0x40ca2    | `"PCIDEV"` |
| 0x6457c     | 0x40ca9    | `"%s: %s%s device open failed\n"` ← **failure path 2** |
| 0x64580     | 0x40cc6    | `"%s: netdev:  device open failed\n"` ← **failure path 3** |
| 0x64584     | 0x40c2f    | `"6.30.223 (TOB) (r)"` (banner version arg) |
| 0x64588     | 0x186a0    | 100000 (decimal — another timeout/const) |
| 0x6458c     | 0x47704608 | `mov r0,r1; bx lr` — tiny inline trampoline (4 bytes) |

## What c_init() actually does

Sequence reconstructable from string args + test.80 console:

1. **Prints RTE banner** (`RTE (PCI-CDC) ... 6.30.223 (TOB) (r) on BCM4360 r3 @ 40/160/160 MHz`) → **OBSERVED in test.80**.
2. Prints `"c_init: add PCI device"` → **NOT observed** in any test → freeze is between (1) and (2), or this string never gets consumed because the print path itself stalls.
3. Sets `*0x62a14 = 0x58cf0` (pciedngl_probe vtable) → **OBSERVED populated in test.99**.
4. Adds WL device (`add WL device 0x%x`).
5. Three failure exit prints — **none observed** → freeze occurred mid-function, did not reach failure handlers.

### Reconciling with test.99 / test.80 evidence

- test.99: `pd[0x62a14] = 0x00058cf0` → step (3) executed ✓
- test.99: `d11[0x58f08] = 0` → step (4) (WL device add) did NOT complete (or D11 link is downstream of WL probe)
- test.80 console: only the RTE banner appears → either step (2) print was never flushed before freeze, OR the pcidev_open subroutine called between steps spins indefinitely

**Refined hypothesis:** c_init reaches step 3 (vtable assignment) and then enters either `pcidev_open` or `wl_probe` setup, where it stalls. The freeze is INSIDE c_init, somewhere after the vtable write but before the WL device print or failure paths.

## Correction to RESUME_NOTES

Earlier notes said "freeze at pciedngl_probe called". That's inaccurate:
- The string `"pciedngl_probe called"` does not appear in the firmware binary — what we saw was inferred from `pciedngldev` + a probe-style call pattern.
- The actual observed firmware-printed sequence (test.80) ends after the **RTE banner**.
- The vtable IS populated (test.99) → execution continues at least to step 3.

## Next moves

Concrete progressions from here (do NOT need a hardware test for any of these):

1. **Identify where vtable 0x58cf0 points** — disassemble pciedngl_probe to see what it does.
2. **Disassemble c_init body 0x642fc–0x6453e** — only ~322 bytes; should reveal exact subroutine call sequence.
3. **Search for next subroutine called after the vtable store** — that subroutine is the freeze candidate.
4. **`add WL device` printf site** — find which BL targets the wl_probe init path.
