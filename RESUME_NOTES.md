# BCM4360 RE — Resume Notes (auto-updated before each test)

## POST-TEST.202 (2026-04-22) — console buffer mapped + assert call site decoded

Logs: `phase5/logs/test.202.journalctl.full.txt`. Run text:
`phase5/logs/test.202.run.txt`. Test ran cleanly — no crash.

### Result 1: hndrte_cons buffer geometry

The dump at `0x96f40..0x96fc0` reveals that the actual log buffer
starts at `0x96f78`, **not** at `0x97000` as we assumed in test.200:

```
0x96f40: 00000010 00000000 00000000 00000b05
0x96f50: 00000000 00000001 00000010 00000000
0x96f60: 00000000 00000000 00000000 00000000   ← chip-info pointed here
0x96f70: 00004000 00000000 6e756f46 68632064   ← buf_size=0x4000, idx=0, then "Foun"
0x96f80: "ip type AI (0x15"
0x96f90: "034360)\r\n125888."
0x96fa0: "000 Chipc: rev 4"
0x96fb0: "3, caps 0x586800"
... (continuing into 0x97000)
```

So the descriptor near `0x96f60` carries (probable layout):

- `0x96f70 = log_buf_size = 0x4000` (16384 B)
- `0x96f74 = log_idx = 0`
- `0x96f78..0x9af78 = log_buf` (16 KB ring)

The log content visible across `0x96f78..0x97070` is only ~248 B —
the firmware emits boot messages + the assert and halts, leaving
the rest of the buffer as zeros. So the duplicate text we saw at
`0x9cdb0..0x9cdf0` in test.199/200 is from a **second sink** (the
firmware exception handler's trap console), not a different copy of
the main ring buffer.

The 32-byte block at `0x96f40..0x96f60` is some other descriptor
(value `0x00000b05` at `0x96f4c` is suggestive — possibly a
counter or reserved-bytes field). Not investigating further now.

### Result 2: assert call site decoded

The dump at `0x6418c..0x641e0` is dense Thumb-2 instructions. The
key sequence around the BL to the assert handler (LR=0x641cb in
the trap data, so BL ends at 0x641ca):

```
... (preceding compare/branch logic) ...
0x641b0:  2e09 d101              ← CMP r6,#9 ; BNE.N <skip>
... 
0x641c0:  481c                   ← LDR r0, [pc,#0x70]   (load format-string ptr)
0x641c2:  f240 118d              ← MOVW r1, #0x18d      (= 397, line number)
0x641c6:  f79d f80f              ← BL  <assert_handler> (LR = 0x641ca)
0x641ca:  ...                    ← (next instruction)
```

This means the *failing check immediately above the assert call* is
a `CMP r6, #9` followed by a `BNE`. r6 holds *some 4-bit-or-so
field of the chip-info struct* — most likely a sub-revision /
package-variant code that this firmware build expects to equal 9
for the BCM4360 it's looking for, but our chip reports a different
value. The LDR at 0x641c0 reads the format string from offset 0x70
past PC, so the literal pool starts around `0x64234`.

### What is r6 = 9 testing?

Speculation, ranked by likelihood:

1. **Chip-package-variant code**: BCM4360 has multiple package
   variants (4360A, 4360B, etc.). The chip-info struct at
   `0x62a98..` includes some bytes we haven't decoded yet (`0x14e4`
   = vendor ID, `0x4360` = chipid). One field around there might
   be a "package code" the firmware checks against an expected
   value.

2. **Chiprev sub-field**: ccrev=43 = 0x2b = 0b101011. Bits[3:0] = 9.
   So `r6 = ccrev & 0xf = 9` would actually pass this check —
   meaning the BNE branches around the assert and *something else*
   triggers the assert. Possible if the "v=43" in the printf uses
   a different value than r6.

3. **A device-tree / flash-region read** that returned a value the
   firmware deems wrong (e.g., a strap or OTP read).

Hypothesis (2) is intriguing because if `ccrev & 0xf == 9` is the
test and 43 & 0xf = 11 (= 0xb) — *that's* what we have, and 11 ≠ 9.
So the assert *does* fire because our ccrev's low nibble is 0xb,
not 0x9. This suggests the firmware was built for a chip whose
ccrev's low nibble is 9 (e.g., ccrev 25, 41, 57, ...) and our
ccrev=43 isn't in the supported set. **This is testable** by
reading the literal pool to see what format string we're emitting —
if the format is `"v = %d"` and the value in the printf is r6, then
we'd see "v = 11", not "v = 43". But we *see* "v = 43" → so the
printf variable is *not* r6 directly. The actual asserted condition
might be at a different register, with r6=9 being something else.

### Plan for test.203

1. **Read the literal pool at `0x64200..0x64280`** — this contains
   the format-string address + any other values LDR'd by the
   assert call. Decode literally what `r0`, `r2`, `r3` hold by
   the time the BL fires.

2. **Read the chip-info struct's neighbours at `0x62b00..0x62b80`** —
   we may find related per-chip configuration fields. Especially
   interesting: any byte that == 9 (or 0xb) so we can confirm
   what r6 was loaded from.

Both reads are <16 rows total (~3 ms). Easy add.

---

## PRE-TEST.202 (2026-04-22) — read hndrte_cons descriptor + decode assert call site

### Hypothesis

Two cheap additional dumps will give us:

1. **`hndrte_cons` descriptor at `0x96f60`** (4 rows): ring metadata
   — base pointer, size, current write index. Confirmed via test.201
   that `0x62af0` (chip-info field) holds `0x00096f60`, which sits
   immediately below the console text we found at `0x97000`. Standard
   Broadcom layout has a small descriptor struct preceding the
   ring buffer, with fields like `{vcons_in, vcons_out, log_base,
   log_idx, log_buf, log_buf_size, log_idx2, ...}`.

2. **Assert call-site context at `0x6418c..0x641b8`** (4 rows): the
   literal-pool / instructions immediately before the `MOVW r1,#0x18d`
   we already located at `0x641b8`. ARM Thumb-2 LDR-from-PC commonly
   appears just before such call sites to load `r0`, `r2`, `r3` with
   pointers to the format string + arguments. From the literals we
   can identify *which* value is being checked.

### Implementation

**chip.c** — bump marker `test.201` → `test.202`. PMU still 0x17f.

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                              | Rows |
|--------------------|------------------------------------------------------|-----:|
| `0x6418c..0x641e0` | Assert call-site (extends prior, +instructions)      |    6 |
| `0x62a80..0x62b00` | Chip-info struct (proven useful, keep)               |    8 |
| `0x96f40..0x96fc0` | hndrte_cons descriptor (8 rows centered on 0x96f60)  |    8 |
| `0x97000..0x97200` | Console ring                                         |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text                              |   64 |

Total = 118 rows ≈ 24 ms. Slight increase over test.201 (108 rows).

### Build + pre-test

- About to rebuild module.
- Last PCIe state clean post-test.201.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.202.journalctl.full.txt`.

### Expected outcomes

- **`hndrte_cons` descriptor decoded**: we'll see a small struct
  with pointers to `log_buf` (likely `0x97000`), a `log_buf_size`
  (likely `0x200` = 512 B = 32 rows we've been dumping), a
  `log_idx` write pointer that tells us *exactly* where the next
  message will land (and therefore where the *latest* message
  ended). This eliminates pattern-matching guesswork.

- **Literal-pool decode**: the LDR offsets in `0x6418c..0x641b8`
  point to an address pool (typically just past the function end,
  before the next function starts). With the literals + the values
  at those addresses, we can identify what global variable / what
  check is being performed. This may directly tell us *what* the
  assert is checking (e.g., a chip-rev allowlist, a feature flag,
  a function-pointer that should have been initialized).

---

## POST-TEST.201 (2026-04-22) — BREAKTHROUGH 4: 0x62a98 is the chip-info struct, not code

Logs: `phase5/logs/test.201.journalctl.full.txt` (use the `.full.txt`).
Run text: `phase5/logs/test.201.run.txt`. Test ran cleanly — no crash.

### Headline result

The mystery PC value `0x00062a98` from the trap data is **not a code
address**. The live TCM around it contains a populated chip-info data
structure that looks like Broadcom's `si_info_t`:

```
0x62a80: 00000000 00000000 00000000 00000000   ← header / unused
0x62a90: 00000001 00000020 00000001 00000000   ← (0x62a98 here = 0x00000001)
0x62aa0: 00000700 ffffffff 00000011 0000002b   ← 0x11=pmurev=17, 0x2b=ccrev=43
0x62ab0: 58680001 00000003 00000011 10a22b11   ← caps, chiprev=3, pmurev, pmucaps
0x62ac0: 0000ffff 00000000 000014e4 00000000   ← 0x14e4 = Broadcom vendor ID
0x62ad0: 00000000 00004360 00000003 00000000   ← 0x4360 = chip ID, rev=3
0x62ae0: 00008a4d 00000000 00000000 00000000   ← 0x8a4d = chipst (matches log)
0x62af0: 00096f60 00000000 00000000 00000000   ← pointer into upper TCM
```

Every value in this struct matches the chip we already know we have:
chiprev=3, ccrev=43, pmurev=17, pmucaps=0x10a22b11, chipst=0x8a4d.
That's the firmware's `si_info_t` (or equivalent) for the local chip.

**Hypothesis (b) confirmed**: the trap struct's "PC" slot is actually
a *function argument* (likely `r0`/`r1` saved at exception entry, which
the trap handler displays as PC because it dumps the full register
file). The real instruction-pointing value is `ra=0x000641cb` — the
LR — which we already located in code at `0x641b8`'s `BL <assert>`.

### Control region (assert site) — confirmed code

```
0x641a0: fc9cf79d 682b3e0a 21e0f8d3 3f00f412
0x641b0: 2e09d101 f8d3d1f3 f41331e0 d1043f00
0x641c0: f240481c f79d118d 6ca3f80f 7f80f413
0x641d0: 2100d00d 4620460b 6200f44f fef8f7ff
```

Live TCM bytes in this range have the typical Thumb-2 encoding density:
`f240` (MOVW), `f80f` (LDRB.W literal pool form), `4620 460b`
(MOV r0,r4 ; MOV r3,r1), `bl` calls (`f7ff fef8`). Matches exactly the
disassembly we did desktop-side — control passes, our offset model is
right for this code region.

### Important secondary finding

The chip-info struct's last populated field at `0x62af0` holds
`0x00096f60` — a pointer into upper TCM. **Our console-buffer dump
in test.200 found readable text starting at `0x97000`**, just past
`0x96f60`. So `0x96f60` is the address of the `hndrte_cons` descriptor
header (which is typically a small struct followed by the ring buffer
itself). Reading that descriptor will tell us:

- Ring base address
- Ring size
- Current write index (so we can know where the *latest* console
  message is, instead of guessing from text positions)
- Possibly a "buffer-full" or "wrap" flag

### Implications

1. **The assert is operating on this chip-info struct.** With "v = 43"
   in the assert message and `ccrev=43` in the struct, the failing
   check is almost certainly something *about* `ccrev` — either:
   - Validating ccrev is in a supported list and 43 isn't there (in
     this firmware build), OR
   - Looking up a per-ccrev table entry and finding it null/missing.

2. **The chip-info struct is built by the firmware's `si_attach` /
   `si_kattach`** (hence the console-log line "si_kattach done.
   ccrev = 43, wd_msticks = 32" appearing right before the assert).
   So `si_kattach` succeeds, but the *next* function — which uses the
   built struct — finds `ccrev=43` unacceptable.

3. **Trap-handler register layout demystified.** The slot we were
   calling "PC" was carrying the asserted function's argument, not
   the PC. The trap handler likely dumps `r0..r12`, `sp`, `lr`,
   `pc`, `cpsr` in some order. The 16-word region at 0x9cf60..0x9d000
   is consistent with that: 16 slots, the right ballpark.

### Next step (test.202)

Two lines of attack, in increasing order of investment:

1. **Read the hndrte_cons descriptor at `0x96f60`**: 64-byte dump
   should reveal the ring metadata and exact write index. From there
   we can find the most recent console line precisely (no more
   pattern-matching the duplicate text shadows).

2. **Read the chip-info struct's table-lookup field**: if there's
   a per-ccrev table with a null slot for 43, the address of that
   table will be derivable from instructions immediately before the
   assert (around `0x6418c..0x641b6` — between any earlier prologue
   and the `MOVW r1,#0x18d` line-number store). Read that range
   live and decode the literal pool addresses (`LDR Rx, [pc,#imm]`)
   to find what value the assert is comparing against.

Plan to implement (1) first — it's a 4-row dump (~1 ms). If that
gives us a clean "latest console message" pointer, we can drop a lot
of the dumb text-window scanning that's currently giving us false
duplicates.

---

## PRE-TEST.201 (2026-04-22) — image translation: read TCM around trap PC and assert site

### Hypothesis

`PC=0x00062a98` from the trap data (decoded in test.200) reads as
all-zero bytes in the firmware *image file* at offset `0x62a98`. Two
possible explanations:

(a) Firmware loads with a non-zero base offset, so trap-PC values are
   virtual addresses that need translation before they map into the
   image.

(b) `0x62a98` is in the firmware's BSS/data area, and the trap PC is
   actually a function-pointer variable — the crash happened when the
   CPU branched through a function pointer that was uninitialized
   (pointing into BSS where the byte pattern is naturally zero).

If (b) is correct, then dumping live TCM at `0x62a98` should also show
zeros (BSS at runtime) — and the asymmetry between `0x62a98` (zeros)
and `0x641b8` (definitely instructions, we proved this desktop-side
already) confirms that one is data and the other is code.

If (a) is correct, the live TCM read at `0x62a98` will show
*instructions* — proving that the firmware is loaded with rambase=0
and we need a different image-offset translation to find the bytes
desktop-side.

### Implementation

**chip.c** — bump marker `test.200` → `test.201`. PMU still `0x17f`
bit-6-only (proven safe).

**pcie.c** — replace `dump_ranges[]`:

| Range              | Purpose                                        | Rows |
|--------------------|------------------------------------------------|-----:|
| `0x62a80..0x62b00` | Live bytes around trap PC (decide a vs b)      |    8 |
| `0x641a0..0x641e0` | Live bytes around assert call site (control)   |    4 |
| `0x97000..0x97200` | Console ring (trimmed — 0x96000 was entropy)   |   32 |
| `0x9cc00..0x9d000` | Trap data + assert text (proven useful)        |   64 |

Total = 108 rows = ~432 indirect MMIO reads ≈ 22 ms. Much cheaper
than test.200's 352-row dump.

The two new ranges are pure observation (live-TCM reads via the
existing indirect-MMIO helper). No firmware modification, no driver
behavior change — just adds 12 dump rows at the same dwell point.

### Build + pre-test

- About to rebuild module after edits.
- Last known PCIe state: clean post-test.200 (no MAbort).
- brcmfmac will be rmmod'd by the test script before insmod.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Logs → `phase5/logs/test.201.journalctl.full.txt` (use the `.full.txt`,
the test script's truncated `.journalctl.txt` cuts off the dump rows).

### Expected outcomes (advance scoring)

- **PC 0x62a80 region all-zero in live TCM** → hypothesis (b)
  confirmed. Trap PC is a stale/null function pointer. Next step:
  search firmware for symbols/strings near offset 0x62a98 to identify
  which fp variable lives there, and trace where it should be set.

- **PC 0x62a80 region looks like instructions in live TCM** →
  hypothesis (a) confirmed. Firmware must load at non-zero rambase.
  Next step: compute the load offset (compare live `0x62a98` bytes
  against image bytes at known offsets to find the delta) and re-look
  at the trapping code from a corrected image position.

- **Assert site `0x641b8` matches the image bytes we found
  desktop-side** → control check passes; our offset model is right
  for at least the code we've already located.

---

## POST-TEST.200 (2026-04-22) — decoded ARM trap-data structure at fa=0x9cfe0

Logs: `phase5/logs/test.200.journalctl.full.txt` (always use `.full.txt`,
the test script's `.journalctl.txt` truncates the dump rows). Run text:
`phase5/logs/test.200.run.txt`.

### Headline result

The fault address `fa=0x0009cfe0` named in the assert message points to
a populated **ARM trap-data structure** in TCM. The 16 words around it
look exactly like a saved CPU context written by an exception handler:

```
0x9cf60: 00000000 00000713 00000000 0003ffff
0x9cf70: 00062a98 00000001 18000000 00000002
0x9cf80: 00000002 00001202 200001df 200001ff   ← CPSR-style words (mode bits)
0x9cf90: 00000047 00000000 000000fa 00000001
0x9cfa0: 0000018d 00062a08 00000009 0009cfe0   ← line=0x18d=397 stored explicitly!
0x9cfb0: 00058c8c 00002f5c bbadbadd bbadbadd   ← Broadcom 0xbbadbadd magic ×2
0x9cfc0: 00000000 0009cfd8 00001201 00001202
0x9cfd0: 00001202 200001ff 0009cfe0 00062a98
0x9cfe0: 18002000 00062a98 000a0000 000641cb   ← fault address — fa value
0x9cff0: 00062a98 0009d0a0 00000000 000a0000
```

Key observations:

- **Line number self-evident**: `0x9cfa0 = 0x18d = 397` matches the
  `hndarm.c line 397` in the assert text. The trap struct stores
  `line` as a u32.
- **Magic sentinel**: `bbadbadd bbadbadd` at `0x9cfb8/0x9cfbc` — the
  classic Broadcom "BAD BAD" trap-data marker, also referenced by
  upstream brcmfmac as `BRCMF_TRAP_DATA_MAGIC`.
- **CPSR words**: `0x200001df` and `0x200001ff` — these decode as ARM
  CPSR with V (overflow) flag set, A/I/F masked, mode `0x1f` (System)
  — i.e. saved as part of the exception entry.
- **ra/fa correspondence**: `ra=0x000641cb` (assert text) appears at
  `0x9cfec`. `fa=0x0009cfe0` is the address of the struct itself —
  recursively the trap struct's first 16 bytes are a small header.
- **Repeated PC value `0x00062a98`** appears at `0x9cf70`, `0x9cfd4`,
  `0x9cfe4`, `0x9cff0`. Likely the trapping PC and its propagated
  copies (saved across multiple slots: epc/cpc/lr).

### Console-buffer geometry now clearer

The wide 0x96000 region was overwhelmingly **entropy** (looks like a
random table or hash pool — all 4096 B nonzero, no ASCII patterns).
**The actual console text starts at `0x97000`** (not earlier as I had
guessed):

```
0x97000: "attach done. ccrev = 43, wd_msti"
0x97020: "cks = 32\r\n135178"
0x97030: ".345 ASSERT in f"
0x97040: "ile hndarm.c lin"
0x97050: "e 397 (ra 000641"
0x97060: "cb, fa 0009cfe0)"
0x97070: "\r\n" then 00 00 00 ... (ring tail)
```

So the console ring extends `0x97000..~0x97070` (continuous) and then
zeros to the end of region 0. The duplicate text we saw in test.199
`0x9cdb0..0x9cdf0` is the *same* assert text written via a second
sink (likely `hndrte_cons`'s shadow buffer in upper TCM near the trap
struct). Everything at `0x96000..0x96fff` is unrelated bulk data —
not console history. So next test should drop that range.

### Fact summary

- Fault is a *handled* assert: firmware vector caught it, populated
  `0xbbadbadd` trap data, wrote two copies of the message into the
  hndrte_cons sink, then halted.
- Trap PC = `0x00062a98` (Thumb). Trap LR = `0x000641ca` (=0x641cb&~1).
- Asserted line = 397 (`hndarm.c`), v=43, wd_msticks=32 (from text).
- The "v = 43" detail in the message is consistent with `ccrev`
  (chip common rev = 43) — the assert may be checking `ccrev` against
  an expected list and bailing because some host-side handshake
  hasn't told the firmware that we support its expected protocol.

### Open puzzles

- **PC=0x62a98 at firmware-image offset reads as zeros** (checked
  desktop-side). Two possibilities: (a) firmware loads with rambase
  offset, so PC is virtual not file-relative — needs translation by
  whatever load offset the bootloader uses; (b) `0x62a98` is in BSS
  (data section), and the trap PC is actually a function pointer
  variable holding the *target* of a call that crashed before it ran.
  Plan to investigate this with a tighter image read around the
  `MOVW r1, #0x18d` site we already located at `0x641b8`, and also
  to check the firmware ELF/PT_LOAD-equivalent metadata for any
  load-address adjustment.

- **What is the assert checking?** The assert call site is in a
  routine that runs *after* `si_kattach done` succeeds (because we
  see that line in the console buffer first). `wd_msticks=32` is
  printed alongside, which suggests this is in the watchdog/PMU
  setup path. Likely candidates for `hndarm.c:397`:
    - PMU resource-mask sanity check (firmware expects bits we
      didn't grant) — but our `max_res_mask=0x17f` matches what
      Broadcom's open driver uses for chiprev=43 already.
    - SHARED-RAM handshake check (firmware reads a magic value
      from a host-supplied location and asserts if missing).
    - Watchdog/clock-domain setup verification (since `wd_msticks`
      is printed in the same message, this code path is wd-related).

### Suggested next step (test.201 — to be planned in PRE-TEST.201)

Two tracks worth pursuing in parallel:

1. **Shared-RAM handshake**: re-examine where `brcmf_pcie_setup`
   writes the bootloader/shared structures and whether anything is
   missing for chiprev=43. Trace the writes the host *does* perform
   to TCM and compare against the populated firmware data
   (especially the area near `0x9d000..0x9d100`, just past the
   trap struct).

2. **Image translation puzzle**: read 4-byte stride around the
   firmware image at offsets `0x62a80..0x62b00` and `0x641a0..0x641e0`
   to confirm we *do* get instruction-shaped data at the assert
   call site (which we already proved at `0x641b8`) but not at
   the trap PC `0x62a98` — that asymmetry confirms hypothesis (b)
   above (BSS pointer) over (a) (virtual offset).

No firmware is being modified, no large excerpts will be committed.

---

## PRE-TEST.200 (2026-04-22) — extended TCM dump including fault address area

### Hypothesis

Test.199 caught the firmware assertion at `hndarm.c:397`. The assert
includes `fa=0x0009cfe0` (fault address) which sits just above our
test.199 dump end (`0x9cdc0`). Test.200 widens both dump ranges:

- `0x96000..0x97200` (was `0x96e00..0x97200`): catches earlier console
  ring-buffer history that may show what firmware was doing right
  before the assert.
- `0x9cc00..0x9d000` (was `0x9cc00..0x9cdc0`): covers the rest of
  the console message text AND the fault address `0x0009cfe0`. May
  reveal what the assert is actually checking for at that address.

### Firmware-image analysis (already done — desktop-only)

Found the assert call site in firmware: at offset `0x641b8` we see
`MOVW r1, #0x18d` (= **397** decimal — the line number) followed by
`LDR r0, =&"hndarm.c"` and a `BL` to the assert handler. Confirmed
identity of the line.

The return address from the captured ASSERT (`ra=0x000641cb`) is just
past this `BL` instruction, with the standard Thumb LSB set. This
gives us the function-level location of the assert: it's a routine
that runs after `si_kattach`, performs some hardware/state check, and
calls the assert handler with `r1=397`.

We don't decompile the function (clean-room rule), but we now know
*where* the failing check lives and can correlate test outcomes
against changes to host-side state that might satisfy that check.

### Implementation

**chip.c** — marker rename `test.199` → `test.200`. PMU unchanged.

**pcie.c** — widen `dump_ranges[]`:
- Region 0: `0x96000..0x97200` (4608 B = 288 rows)
- Region 1: `0x9cc00..0x9d000` (1024 B = 64 rows)

Total 352 dump rows, ~1408 indirect-MMIO reads (~70 ms). Still cheap
enough for a single end-of-dwell pass.

### Build + pre-test

- Module rebuilt clean.
- PCIe state still clean (verified post-test.199 reboot).
- Note: machine rebooted 07:24 (boot index 0) — test.199 ran cleanly,
  reboot was after test, possibly unrelated. brcmfmac currently
  loaded (test.199 left it loaded).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → `test.200.journalctl.full.txt` (use `.full.txt` — the test
script's truncated capture cuts off the dump rows).

---

## POST-TEST.199 (2026-04-22) — BREAKTHROUGH 3: firmware is ASSERTING — not waiting

Logs: `phase5/logs/test.199.journalctl.full.txt` (use `.full.txt`,
the test script's truncated `.journalctl.txt` cuts off the dump rows;
they appear earlier in the journal than the post-dwell fine scan that
fills the tail). Run text: `phase5/logs/test.199.run.txt`.

### Headline result

The firmware writes a `hndrte_cons`-style **debug console ring
buffer** into upper TCM. Decoding the dump:

```
Found chip type AI (0x15034360)
.125888.000 Chipc: rev 43, caps 0x58680001, chipst 0x8a4d
                   pmurev 17, pmucaps 0x10a22b11
.125888.000 si_kattach done. ccrev = 43, wd_msticks = 32
.134592.747 ASSERT in file hndarm.c line 397 (ra 000641cb, fa 0009cfe0)
```

The firmware image (`/lib/firmware/brcm/brcmfmac4360-pcie.bin`)
contains the matching format strings — confirmed:
- `"Found chip type AI (0x%08x)"`
- `"ASSERT in file %s line %d (ra %p, fa %p)"`
- Source files referenced include `hndarm.c`, `hndrte_cons.c`,
  `hndrte.c`, `hndpmu.c`, `siutils.c`, `wlc_bmac.c` and many others.

### Updated mental model — firmware is *crashed*, not idle

| Earlier theory | Reality |
|---|---|
| Firmware in tight loop updating buffers | NO — buffers are written once during init, then frozen |
| Firmware in passive "wait for host handshake" idle | NO — firmware is **halted on assertion failure** |
| The 7 cells we kept catching across runs | These are the bytes of the ASSERT text (timestamp, line counter) and metadata struct that vary per boot |

What firmware actually does on each run:
1. Detects the chip (correct: 4360 AI)
2. Logs Chipc + PMU caps to console buffer
3. Calls `si_kattach` (~125888 us into firmware boot)
4. ~8704 us later (presumably some init step in `hndarm.c`), hits
   ASSERT at line 397 and halts.
5. Console buffer keeps the assertion message; ARM CR4 stays running
   (`CPUHALT=NO`, `RESET_CTL=0`) but doing nothing useful (no further
   register writes, no D2H mailbox, no IPC ring brought up).

### What we now know about TCM layout

| TCM region | Contents (decoded) |
|---|---|
| `0x96f70..0x97070` (~256 B) | Snapshot of the console log text (Found chip → si_kattach → ASSERT) |
| `0x97070..0x97200` | Zero-padded |
| `0x9cc00..0x9cd17` (~280 B) | Stack canary fill `"KATS"` repeating (= 0x5354414b LE — `'KATS'` reversed = `'STAK'`/start of "stack") |
| `0x9cd18..0x9cd2c` | Pointer-like values (high-bit-set 0x80000000 or'd over TCM addresses 0x9cd7e, 0x9cd87) |
| `0x9cd30..0x9cdaf` | hndrte_cons metadata struct: pointers to log buffer, line lengths, indices, plus mirrored values |
| `0x9cdb0..0x9cdc0` | Latest log message starting `"134592.747 ASSER..."` (continues past dump end) |
| `0x9cfe0` (fa) | The fault address from the ASSERT — just above our dump range |

### Cross-referencing the dump bytes

`0x9cd38 = 0x10a22b11` — this is `pmucaps` (16-bit chip register
literal value), so this struct stores firmware's snapshot of chip
state. Adjacent `0x9cd30 = ASCII "11b22a01"` is the same value
formatted as a hex string (matches `"pmucaps 0x10a22b11"` in the
console line) — so this struct holds both string and binary copies
of fields, classic log-record layout.

### Why the same 7 cells changed across runs

Re-explained simply: the per-run varying-text positions in the
hndrte_cons buffer landed on these 4-byte aligned cells. The text
contents of each ASSERT line vary slightly per boot (timestamp µs,
line counter `0x9cd50` — which is the µs value, e.g. 0x2eb=747 in
test.199), so those cells "differ from previous run" in the snapshot
diff. The cells with stable text (e.g. format-string constants) don't
diff and so don't show up in CHANGED lists.

### Next move (test.200)

Extend the dump to cover the **fault address area**
(`0x9cfc0..0x9d000`) and the area **before** the visible log start
(`0x96000..0x96e00`) to find:
- Whatever firmware code/data is at `fa=0x0009cfe0`
- Earlier console history (older log messages in the ring buffer)
- The hndrte_cons struct base pointer (so we can index it correctly)
- Any additional active write regions we missed

Also worth doing this run: search the firmware image for the
return-address `0x000641cb` to identify the function that calls the
ASSERT — gives us a function-level location for line 397 of hndarm.c.

Beyond test.200 — once we know what condition is failing in
hndarm.c:397, we can either change PMU/host setup to satisfy the
condition, or find a code path that avoids it. Likely candidate:
firmware expects the host to populate sharedram (D2H mailbox base
address) before bringing up the ARM CR4 — we currently never do
that handshake.

---

## PRE-TEST.199 (2026-04-22) — hex+ASCII dump of upper-TCM regions to decode firmware data structure

### What we know going into test.199

Test.198 changed the picture from "firmware runs continuous loops" to
"firmware runs init then halts":

- The 7 cells test.197 caught are written in the first <250 ms after
  `set_active` and **never updated again** during the 3 s dwell.
- Same 7 offsets are written across runs but values differ per run:
  test.197 wrote `0x335 = 821`, test.198 wrote `0xeb = 235`.
- Old "was" values come from the previous firmware run (TCM persists
  across rmmod/insmod since it's on-chip; rebooting the host would
  give us pristine ROM-poison values).

Reproducibility of the offset set + per-run variation of the values
implies these cells are a fixed firmware data structure storing
runtime values (calibration result, sensor reading, random init seed,
or boot-counter snapshot).

### Hypothesis

If we hex+ASCII dump the surrounding TCM region we should see:
- Adjacent printable bytes that extend the strings beyond the 4-byte
  cells we caught (e.g. "1366 84.235 A" might be part of a longer
  format string with field labels)
- Possibly format-string templates nearby (e.g. `"%4u %2u.%03u A"`)
- Other firmware-written fields that happened to land on already-zero
  bytes (so the wide-stride scan missed them)

### Implementation

**chip.c** — marker rename `test.198` → `test.199`. PMU unchanged.

**pcie.c** — replace the per-tick TS sample with a single end-of-dwell
hex+ASCII dump of two regions:
- `0x96e00..0x97200` (1 KB centred on 0x9702c)
- `0x9cc00..0x9cdc0` (448 B centred on 0x9cd48..0x9cdb8 active block)

Format per 16-byte row:
```
test.199: 0xNNNNN: ww0 ww1 ww2 ww3 | aaaaaaaaaaaaaaaa
```
where `wwN` is the 32-bit word read at +0/+4/+8/+12 and `a` is the
ASCII rendering (printables → char, others → '.').

Total log lines: (1024 + 448) / 16 = **92 dump rows** + the existing
fine-grain post-dwell scan. Cheap and easy to read.

### Build + pre-test

To do after edits — same checklist (build, PCIe state, push, sync).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.199.journalctl.txt`.

---

## POST-TEST.198 (2026-04-22) — firmware writes once at init then HALTS (revised model)

Logs: `phase5/logs/test.198.journalctl.txt` + `.full.txt`.

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ |
| `res_state` 0x13b → 0x17b | ✓ same as test.196/197 |
| Per-tick TS sample of 7 cells (12 ticks × 7 cells = 84 reads) | ✓ all SAME |
| ts-seed at dwell-250 ms shows final values already in place | ✓ |
| Post-dwell fine scan still finds same 7 cells "CHANGED" vs pre-set_active baseline | ✓ |

### Decoded — the model is "init + halt", not "running loops"

ts-seed at dwell-250 ms read:

```
[0x9702c]=0x34383636  "6684"
[0x97030]=0x3533322e  ".235"
[0x9cd48]=0x00323335  "532\0"
[0x9cd50]=0x000000eb  binary 235  ← matches ".235" in 0x97030
[0x9cdb0]=0x36363331  "1366"
[0x9cdb4]=0x322e3438  "84.2"
[0x9cdb8]=0x41203533  "35 A"
```

All 12 subsequent ticks (500 ms..3000 ms): every cell `delta=0 SAME`.

### Compared across runs

| Cell | test.197 final | test.198 final | Note |
|---|---|---|---|
| 0x9702c..0x97033 | "6172.821" | "6684.235" | varying |
| 0x9cd48..0x9cd4b | "128\0" | "532\0" | varying |
| 0x9cd50 (binary) | 0x335 = **821** | 0xeb = **235** | matches ASCII in 0x97030 each run |
| 0x9cdb0..0x9cdbb | "1352 98.036 A" | "1366 84.235 A" | varying |

**The binary at 0x9cd50 == the trailing ".NNN" digits in 0x97030 AND
in 0x9cdb4-0x9cdb8 each run** — same value formatted into both ASCII
buffers. Strong: the 7-cell change set is one logical record written
by a single sprintf-style routine during firmware init.

### Updated mental model

Firmware on this chip, with PMU `max_res_mask=0x17f` (HT clock only),
runs the following observable sequence after `set_active`:

1. (within first 250 ms) Sets `pmucontrol.NOILPONW`, leaves
   `clk_ctl_st = 0x00050040`.
2. (within first 250 ms) Writes a 1-record data structure spanning
   `0x97028..0x9cdbb` containing several stringified fields and one
   binary counter at `0x9cd50`. Looks like a calibration / sensor /
   boot-stat record — same offsets each run, fresh values each run.
3. After that — no further visible activity through the 3 s dwell
   (per-tick reads of the same cells stay constant; per-tick CC
   backplane regs stay constant except `pmutimer` which is the free
   counter).

What we still don't see:
- Any host↔firmware mailbox / doorbell handshake completing.
- Any IPC ring, sharedram pointer write, or D2H mailboxint event.
- D11 RESET still asserted (CPU never gets to bring up the radio MAC).

This is consistent with the firmware reaching the "wait for host
handshake" point in init and then idling because we never complete the
PCIe handshake (no sharedram base advertised, no doorbell, no MSI
configured).

### Next move (test.199)

Decode the firmware data structure: hex+ASCII dump of the active
region, look for adjacent printable text and format-string templates.
That tells us what firmware is reporting, and may give us a foothold
for matching offsets to known brcmfmac shared-memory layouts.

After test.199 — likely the right move is to rebuild the host-side
PCIe handshake from the trunk driver and retry the full bring-up; the
chip is ready, we just aren't talking to it.

---

## PRE-TEST.198 (2026-04-22) — per-tick time-series of 7 firmware-active TCM cells

### Hypothesis

Test.197 caught firmware updating 7 cells in the post-dwell scan window
(~400 ms after the 3000 ms dwell ended), including a binary counter
at `0x9cd50` whose value (0x335 = 821) matches an ASCII suffix at
`0x97030` (".821") — strong evidence of an active sprintf-style
loop. Test.198 reads the same 7 cells once per dwell tick (every
250 ms × 12 ticks) so we can measure the actual update cadence.

Expected outcomes (each is a useful datapoint):

| Pattern | Interpretation | Next move |
|---|---|---|
| Counter at 0x9cd50 increments by ~constant N every tick | firmware loop is periodic, N/250 ms = tick rate | use this rate to time other probes; investigate what gates the loop |
| Counter increments by varying N | firmware doing variable-cost work per loop | look at neighbouring cells for state |
| Counter does not change between ticks | activity we caught in test.197 was a one-shot, or update cadence > 250 ms | widen sample window, or use post-set_active baseline |
| Counter increments rapidly then stops | firmware hit an error / wait-for-host condition | examine what register state changed at the stop point |
| Hard crash (no precedent — these reads are very cheap) | something pathological with these specific addresses | retreat to test.197 baseline |

### Implementation

**chip.c** — marker rename `test.197` → `test.198`. PMU state unchanged
(`max_res_mask = 0x17f`, bit 6 only).

**pcie.c** — adds:
- `static const u32 ts_offsets[7]` containing the 7 active offsets
- `u32 ts_prev[7]` (stack) + `bool ts_seeded` flag
- Inside the existing dwell loop (after the CC backplane sample), a new
  block reads each of the 7 cells. First tick seeds `ts_prev` and logs
  the seed value. Subsequent ticks log value + delta vs prev tick.

Existing fine-grain post-dwell scan retained — we still want a chance
to spot any *new* active region we missed.

Per-tick cost: 7 indirect-MMIO reads ≈ ~50 µs each ≈ <0.5 ms per tick.
Negligible vs the 250 ms dwell increment. Should be crash-safe.

### Build + pre-test

- Module rebuilt clean (only pre-existing brcmf_pcie_write_ram32 warning).
- PCIe state from prior check (post-test.197): `MAbort-`, `FatalErr-`,
  `LnkSta` x1/2.5GT/s, `ASPM Disabled` — clean.
- brcmfmac module loaded from test.197 (test script will rmmod).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.198.journalctl.txt`.

---

## POST-TEST.197 (2026-04-22) — BREAKTHROUGH 2: firmware is *running loops* (ASCII counter strings updating in real time)

Logs: `phase5/logs/test.197.journalctl.txt` (892 brcmfmac lines) +
`test.197.journalctl.full.txt` (893 lines).

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ — slim dwell + 16 K post-dwell reads survived |
| `res_state` 0x13b → 0x17b (bit 6 only) | ✓ same as test.196 |
| Pre-release populate ran cleanly (16384 cells, 64 KB heap, ~6 s mark) | ✓ |
| Post-dwell scan found CHANGED cells | **7 of 16384** |
| Span of changes | `0x9702c..0x9cdb8` (23 952 bytes — wide, scattered) |
| 0x98000 / 0x9c000 (test.196 hits) — CHANGED again? | **No**, both UNCHANGED in test.197 |

### Decoded changes — firmware is updating ASCII counter strings

All seven changed cells decode as printable ASCII (little-endian):

| Addr | Old (hex / ASCII) | New (hex / ASCII) | Note |
|---|---|---|---|
| 0x9702c | 0x38393235 `"5298"` | 0x32373136 `"6172"` | adjacent → 8-byte string |
| 0x97030 | 0x3633302e `".063"` | 0x3132382e `".821"` | "5298.063" → "6172.821" |
| 0x9cd48 | 0x00303336 `"630\0"` | 0x00383231 `"128\0"` | null-terminated short string |
| 0x9cd50 | 0x00000024 (binary 36) | 0x00000335 (binary 821) | binary counter — **note 821 == suffix in 0x97030** |
| 0x9cdb0 | 0x32353331 `"1352"` | 0x31363331 `"1361"` | adjacent triple → 12-byte string |
| 0x9cdb4 | 0x302e3839 `"98.0"` | 0x382e3237 `"72.8"` | (cont) |
| 0x9cdb8 | 0x41203633 `"63 A"` | 0x41203132 `"12 A"` | (cont) → "1352 98.063 A" → "1361 72.812 A" |

**Significant detail**: the binary counter at `0x9cd50` reads `0x335 = 821`,
exactly matching the ASCII suffix in `0x97030` (`".821"`). This is firmware
*formatting* a binary counter into a printable string — strong evidence of
an active sprintf/print routine running, not just one-shot init writes.

### What this means

Test.196 showed firmware wrote two cells. Test.197 shows those exact cells
did NOT change again, but seven *other* cells did, **and the changes look
like a sprintf-style string buffer being updated**. The window between
pre-populate (~end-of-dwell) and post-dwell scan is only ~400 ms, so these
are events firing on a sub-second cadence. Firmware is alive and looping.

This is qualitatively different from test.196 (which could be read as
"firmware ran once and stopped"). Test.197 demonstrates **continuous
firmware execution** at sub-second granularity. The chip is functional;
what we still lack is the host↔firmware protocol bring-up that lets the
driver hand off control packets.

### Firmware progress timeline (unchanged from test.196)

- t=0 (pre-release): `pmucontrol=0x01770181`, `clk_ctl_st=0x00010040`
- t=250 ms: `pmucontrol=0x01770381` (NOILPONW set by firmware)
- t=500 ms–t=3000 ms: CC regs stable (firmware in steady-state loop)
- end-of-dwell: pre-populate snapshot of 0x90000-0xa0000 taken
- ~400 ms later: post-dwell scan → 7 cells CHANGED

### Hypothesis confirmed/refuted from PRE-TEST.197

| Hypothesis | Result |
|---|---|
| (a) Wide-stride aliasing — firmware only wrote two cells | **Refuted**. Test.197 shows multiple write hotspots not on the 16 KB grid. |
| (b) Contiguous structure | **Partially**. Two short adjacent runs (8 B at 0x9702c, 12 B at 0x9cdb0) but not one big block. |
| (c) Scattered singletons | **Confirmed for the binary counter** at 0x9cd50, possibly 0x9cd48 too. |

The picture is **multiple short string fields** scattered across 0x97000-0x9d000.
Looks like a status / log structure with several text fields and at least one
binary counter, all updated by the same firmware loop.

### Open puzzle

Test.196's writes (0x98000, 0x9c000) **did not repeat** in test.197.
Possibilities:
1. Those were one-shot init writes (zero-fill / stack-canary plant); test.197
   captured later steady-state activity instead.
2. The wide-TCM probe READ at those addresses during test.196 perturbed
   them (read-modify-clear on a register-aliased TCM region?). Unlikely —
   they are deep in TCM, not register-mapped.
3. Firmware behavior is non-deterministic across runs.

(1) is most plausible: test.196 caught early init, test.197 caught steady-state.

### Next options to consider

A. **Wider scan** (0x80000–0xa0000 or whole 0x00000–0xa0000) at 4-byte
   stride to find any other active write regions and any code/data near
   the strings that might decode as format-string templates.
B. **Time-series sample** of just the 7 known-active cells — read each
   cell every 250 ms during dwell, log values. Will tell us how fast
   the counter increments and whether the string fields update on a
   periodic schedule (heartbeat? watchdog?).
C. **Pre-set_active scan** — populate the snapshot BEFORE set_active so we
   see the *initial* writes too (test.196's 0x98000/0x9c000 hits) plus
   ongoing activity. Combine with end-of-dwell scan to see the full
   write history during the 3 s dwell.
D. **Decode the structure** — dump 0x97000-0x9d000 contents fresh (no
   compare) and look for printable strings with `strings` tool; might
   recognise format strings like `"%s %d.%03d A"` etc.

Recommendation: **B (time-series)** — cheapest, most informative.
Watching the counter at 0x9cd50 increment will tell us the firmware
loop frequency, which is a hard datapoint we don't have. If it
increments by N per 250 ms, we know the firmware tick rate.

---

## PRE-TEST.197 (2026-04-22) — fine-grain TCM scan over 0x90000–0xa0000 to map full extent of firmware writes

### Hypothesis

Test.196 caught two firmware-originated writes (`[0x98000]=0x00000000`,
`[0x9c000]=0x5354414b` "STAK") at exactly the 16 KB stride boundaries of
the existing `wide_offsets` scan. Either:

(a) Firmware wrote ONLY those two cells and they happened to land on the
    sample stride. Unlikely on a chip running real init code; suggests
    wide-stride aliasing.
(b) Firmware wrote a contiguous structure (e.g. an init descriptor /
    state block / shared-memory header) and our 16 KB stride only hit
    two cells of it. A finer scan will reveal the full extent.
(c) Firmware wrote multiple unrelated singletons at scattered offsets
    that happen to align with 16 KB boundaries by coincidence.

A 4-byte stride scan over the 64 KB upper-TCM region (0x90000–0xa0000)
will distinguish (a) from (b)/(c) and, if (b) holds, map the structure
boundaries — its size and content shape will tell us what state firmware
reached and what it might be waiting for next.

### Implementation

**chip.c** — marker rename only: `test.196` → `test.197`. PMU state
unchanged: `max_res_mask = 0x17f` (bit 6 only, proven safe).

**pcie.c** — add a heap-allocated 16384-cell pre-release snapshot covering
0x90000..0xa0000 at 4-byte stride (64 KB heap). The pre-release populate
runs silently (just logs a single completion line — printing 16384 cells
would spam the journal). The post-dwell scan reads all 16384 cells, prints
only the CHANGED entries, and emits a summary line:
- `fine-TCM summary: N of 16384 cells CHANGED`
- `fine-TCM CHANGED span 0x..... ..0x..... (NN bytes)` if any changed

The post-dwell single-shot scan adds ~16384 indirect-MMIO reads
(~400 ms in steady state with HT clock active). Test.196's slim dwell
harness already proved the chip survives extended post-dwell reads in
this PMU configuration; the new scan extends that window by ~400 ms but
does not poll mid-dwell.

### Expected outcomes

| Pattern of CHANGED cells | Interpretation | Next move |
|---|---|---|
| Only 0x98000 + 0x9c000 changed (same as test.196) | scattered singletons; firmware wrote two flags | grep firmware text image for these constants |
| Contiguous block of changed cells around 0x9c000 ("STAK..." string + neighbours) | firmware wrote a structure or string buffer | dump full block to decode purpose |
| Many scattered changes across 0x90000–0xa0000 | firmware writing init memory aggressively | classify into hot regions |
| Firmware wrote outside 0x90000-0xa0000 too | scan range too narrow | extend in test.198 |
| Hard crash | post-dwell read pressure with HT active is unsafe at 16 K reads | shrink range / increase stride |

### Build + pre-test

- chip.c, pcie.c edited; module built clean (only pre-existing
  brcmf_pcie_write_ram32 unused-function warning).
- PCIe state (verified before this run, still on boot 0):
  - `MAbort-`, `CommClk+`, `LnkSta` x1/2.5GT/s — clean
  - `UESta` all clear; `CESta` Timeout+ AdvNonFatalErr+ — accumulated
    correctable errors from the test.196 unbind cycle, benign.
  - `LnkCtl: ASPM Disabled` (we disabled it in chip_attach).
- brcmfmac module currently loaded (from test.196 success, test will rmmod).

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.197.journalctl.txt`.

---

## POST-TEST.196 (2026-04-22) — BREAKTHROUGH: bit 6 alone is safe AND firmware finally writes TCM (first ever observation)

Logs: `phase5/logs/test.196.journalctl.txt` (885 brcmfmac lines) +
`test.196.journalctl.full.txt` (920 lines).

### Headline result

| Outcome | Status |
|---|---|
| No crash | ✓ — system survived test cleanly, module rmmod'd normally |
| `res_state` 0x13b → 0x17b (bit 6 asserted, bit 7 NOT asserted) | ✓ |
| **First ever firmware-originated TCM writes detected** | ✓ |
| `fw-sample` 256-region scan post-dwell | 256 UNCHANGED — firmware code intact, no overwrite |
| `wide-TCM` post-dwell | **2 of 40 regions CHANGED** — firmware wrote scratch |

Specific writes found by post-dwell wide-TCM scan:

```
post-dwell wide-TCM[0x98000]=0x00000000 (was 0x15f3b94d) CHANGED
post-dwell wide-TCM[0x9c000]=0x5354414b (was 0xf39d6dd9) CHANGED
```

`0x9c000` is in the upper TCM (~624 KB from base, near the end of the
640 KB TCM). `0x5354414b` decodes as ASCII "KATS" little-endian / "STAK"
big-endian — looks like part of a firmware initialisation marker
(possibly "STACK" or a stack canary fill pattern). `0x98000` zeroed out.
**This is the first objective evidence in this project that firmware is
executing and writing data on this chip.**

### Bit 6 vs bit 7 decoded

| Signal | test.194 (max=0x13f) | test.195 (max=0x1ff, both 6+7) | test.196 (max=0x17f, bit 6 only) |
|---|---|---|---|
| `res_state` | 0x13b | 0x1fb | **0x17b** |
| `clk_ctl_st` pre-release | 0x00050040 | 0x01070040 | **0x00010040** |
| `clk_ctl_st` post-dwell | 0x00050040 | (crashed) | **0x00050040** (bit 0x40000 set during dwell) |
| `pmustatus` | 0x2a | 0x2e | 0x2a |
| `pmucontrol` post-dwell | 0x01770381 | 0x01770381 | 0x01770381 (NOILPONW set by fw within 250 ms) |
| Crash? | no | YES (mid-dwell freeze) | **no** |
| Firmware TCM writes? | 0 | unknown (crashed before scan) | **2** |

Bit 6 alone is the HT clock the firmware needs to execute. Bit 7 enables
something else (sets `clk_ctl_st` bits 0x10000+0x1000000 even before
`set_active` runs — confirmed by pre-release snapshot delta) and is the
destabiliser. Adding bit 7 to bit 6 simultaneously is what crashed
test.195.

### Firmware progress timeline (from per-tick CC backplane sample)

- t=0 (pre-release): `pmucontrol=0x01770181`, `clk_ctl_st=0x00010040`
- t=250 ms: `pmucontrol=0x01770381` (NOILPONW set), `clk_ctl_st=0x00050040`
  → firmware completed early `si_pmu_init` within first 250 ms
- t=500 ms through t=3000 ms: all CC regs stable (no further changes)
  → firmware then sits idle (or in a polling loop with no register-visible side effects)
- post-dwell: 2 wide-TCM cells found CHANGED
- D11 `RESET_CTL` stayed 0x1 throughout — firmware did NOT advance to D11 bring-up

### What this tells us

1. **Direction is fully validated.** Bit 6 of max_res_mask is THE gate.
   Firmware was waiting for HT clock; once we permit it, firmware runs
   and starts initializing.
2. **Bit 7 is dangerous and unnecessary** for the basic firmware unblock.
   We can leave it gated off for now.
3. **Firmware progress stops short of D11 bring-up.** It runs, completes
   PMU init, writes a small amount of scratch, then stalls. Likely waiting
   on something else: probably NVRAM (we currently don't fully program
   NVRAM), a host doorbell signal, or a second clock-domain enable.
4. **The slim dwell harness is a good baseline** for further bring-up
   work — it's safe even with HT clock active and gives clean per-tick
   PMU evolution data.

### Suggested next moves (priority order)

1. **Probe deeper into wide-TCM** — current scan only samples every 16 KB.
   Add a finer scan around `0x98000`–`0x9c000` to find the full extent
   of the firmware-written region. Possibly contains a fw-init structure
   we can decode to learn what state firmware reached.
2. **Test bit 7 alone** (`max_res_mask=0x1bf`) — formally confirm bit 7
   is the destabiliser independent of bit 6 (control test). Even with
   the slim harness, expect a crash; but we'll know.
3. **NVRAM revisit** — firmware in early init typically reads NVRAM for
   board-specific config (PHY calibration tables etc). If our NVRAM
   write is incomplete, fw could be sitting in a "wait for NVRAM ready"
   loop. Worth re-checking what we actually upload vs what wl.ko does.
4. **Forcing bit 6 via min_res_mask** — currently bit 6 is asserted only
   because we permitted it; the chip might cycle it. Setting
   `min_res_mask=0x17b` would FORCE bit 6 to stay on and could help fw
   make further progress.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| Bit 6 + bit 7 simultaneous activation is safe | 195 | falsified — chip freezes |
| Bit 6 alone destabilises the chip | **196** | **falsified** — bit 6 alone is safe |
| Heavy MMIO during dwell is universally safe | 195 | falsified |
| Slim dwell harness can't detect fw writes | **196** | **falsified** — caught both |

---

## PRE-TEST.196 (2026-04-22) — bisect res 6 vs 7 (try bit 6 only, max_res_mask=0x17f) + drastically reduce dwell-time MMIO

### Hypothesis

Test.195 proved widening `max_res_mask` activates resources 6 and 7 (first
ever res_state movement on this chip), but the simultaneous activation
combined with the heavy TCM-poll harness caused an unrecoverable freeze
~half-way through the 3000 ms dwell. Two unknowns to separate:

1. Which resource (6 or 7) destabilised the chip when its clock domain came
   live? Bit 6 only (`max_res_mask=0x17f`) lets us test bit 6 in isolation.
2. Is the freeze caused by the resources themselves, or by the MMIO storm
   the dwell-poll harness produces under a live HT clock? A drastically
   slimmer harness (no fw-sample / wide-TCM / tail-TCM scans during dwell)
   eliminates the harness as a confound — if the chip still freezes with
   bit 6 only and a slim harness, the resource is the gun.

### Implementation

**chip.c** — single-line change:
- `max_res_mask` write changes from `0x1ff` → `0x17f` (drop bit 7)
- Marker line updated: `BCM4360 test.196: max_res_mask 0x... -> 0x... (write 0x17f — bisect: bit 6 only)`

**pcie.c** — slim the dwell harness:
- Dwell stays 3000 ms total but is now split into 12 × 250 ms ticks.
- Each tick does ONLY: ARM/D11 wrapper probes (single MMIO each),
  TCM[0..0x1c] head scan (8 cheap reads), and the existing CC backplane
  sample (8 CC-only reads incl res_state, min_res_mask, max_res_mask,
  pmustatus, clk_ctl_st, pmucontrol, pmutimer, pmuwatchdog).
- The crashy heavy-MMIO loops (wide-TCM 40-read scan, tail-TCM 16-read
  scan, full fw-sample 256-read scan) are REMOVED from per-tick dwell.
- A SINGLE end-of-dwell summary scan runs after all ticks: full
  fw-sample (256 reads) reduced to a 3-bucket count (UNCHANGED /
  REVERTED / CHANGED) plus wide-TCM scan that only logs CHANGED entries.

### Expected outcomes

| Observation | Interpretation | Next |
|---|---|---|
| `max_res_mask 0x13f -> 0x17f` AND `res_state` advances to 0x17b (bit 6 only) | bit 6 alone activates cleanly; chip survives the dwell | follow up with bit 7 alone (`max_res_mask=0x1bf`) and confirm which destabilises |
| `res_state 0x17b` AND fw-sample summary shows CHANGED count > 0 | firmware finally writing TCM with HT clock alone | analyse what changed; pivot to per-region tracking |
| `res_state 0x17b` AND fw-sample all UNCHANGED, no crash | bit 6 unblocks resources but firmware still stalls; need more (min_res_mask widen, NVRAM, OTP) | widen min_res_mask to 0x17b in test.197 |
| Hard crash again with bit 6 alone and slim harness | bit 6 itself destabilises the chip independent of MMIO load | bit 7 alone next (`0x1bf`); if both crash, problem is the resources colliding with our PCIe state |
| `res_state` does NOT change to 0x17b | something else changed; investigate (or harness regression) | re-read code path |

### Build + pre-test

- chip.c, pcie.c edited; module built clean (one pre-existing unused-function
  warning unrelated to this change).
- PCIe state (verified post crash + SMC reset, current boot 0):
  - `MAbort-`, `CommClk+`, `LnkSta` Speed 2.5GT/s Width x1 — clean
  - `UESta` all clear; `CESta` AdvNonFatalErr+ (benign accumulator)
  - `DevSta` `CorrErr+ UnsupReq+` — benign post-boot noise
- No brcmfmac currently loaded.
- Hypothesis stated above.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.196.journalctl.txt`.

---

## POST-TEST.195 (2026-04-22) — max_res_mask widening WORKED (resources 6+7 asserted) but chip became unstable mid-dwell → hard crash (SMC reset required)

Logs: `phase5/logs/test.195.journalctl.txt` (792 brcmfmac lines) + `test.195.journalctl.full.txt` (2123 lines, full boot). Captured from journalctl boot -1 history after recovery — boot ended mid-dwell with no panic/MCE in dmesg (silent freeze).

### Key result — first ever observation of res_state advancing past 0x13b

| Register | test.194 (max=0x13f) | test.195 (max=0x1ff) | Delta |
|---|---|---|---|
| `max_res_mask` | 0x13f | **0x1ff** | widened by our write ✓ |
| `res_state` | 0x13b | **0x1fb** | **bits 6 + 7 newly asserted** (HT clock + backplane HT) |
| `clk_ctl_st` | 0x00050040 | **0x01070040** | new bits 0x01020000 set |
| `pmustatus` | 0x2a | **0x2e** | bit 0x4 set |
| `min_res_mask` | 0x13b | 0x13b | unchanged (we did not touch min) |

Diagnostic line in dmesg confirms write landed:
```
brcmf_chip_setup: BCM4360 test.195: max_res_mask 0x0000013f -> 0x000001ff (write 0x1ff)
```

**The hypothesis was correct in mechanism:** widening max_res_mask DID cause the chip to grant resources 6 and 7. This is the first time ever in this project that res_state has changed past the POR value of 0x13b.

### But — TCM never advanced AND chip became unstable

| Signal | Observation |
|---|---|
| TCM dwell-pre samples | UNCHANGED from baseline |
| TCM dwell-3000ms samples (got ~56 of 271 before crash) | ALL UNCHANGED — fw still not writing scratch |
| D11 RESET_CTL | 0x1 (still in reset) |
| ARM CR4 CPUHALT | NO (still running) |

**Box hard-crashed mid-dwell** (boot -1 ended at 00:53:12 BST, exactly when the TCM-sample stream stops at fw-sample[0x238f8]). No MCE, no panic, no oops in dmesg — the kernel just stopped logging. Required SMC reset to recover. Boot 0 (current, 00:54:26) is fresh, no module loaded; PCIe state clean (`MAbort-`, no FatalErr, link x1/2.5GT/s).

### Interpretation

Resources 6 and 7 control HT-clock domains. Enabling them simultaneously (the only delta vs test.194) caused the chip to switch into a state where the heavy TCM-poll loop (running every ~10ms during the 3s dwell) eventually triggered a fatal MMIO fault that the host couldn't recover from. Likely root cause: chip changed PCIe ref-clock or backplane clock once HT became available; the host's continued indirect-MMIO reads then collided with that transition and produced an unrecoverable CTO.

### Implications

1. **The unblock direction is right.** First res_state movement in 30+ tests means we're touching the actual gate.
2. **The diagnostic harness is now the liability.** The same TCM-poll loop that was safe in test.194 (resources gated off) is unsafe once resources are live.
3. **Firmware still hasn't started writing TCM** even with HT resources asserted. Either it needs more time than 3s, more resources (min_res_mask widening to *force* 6/7 to stay asserted), or a different trigger (NVRAM/OTP).

### Next test (test.196) — staged, low-poll diagnostic

Plan:
1. Keep `max_res_mask = 0x1ff` (proven to work).
2. Bisect bits 6 vs 7: try `max_res_mask = 0x17f` first (bit 6 only) — if safe, follow with bit 7. Identifies which resource destabilises the chip.
3. **Drastically reduce TCM-poll volume** during dwell — sample once at start, once at end. Replace with PMU/clk-state samples every 200ms (no-op MMIO of CC regs is cheap and stays in CC core which we know is safe).
4. Add `min_res_mask` and `max_res_mask` to the periodic PMU sample so we can see if firmware writes them.
5. If bit-6-only is also unstable, try widening *min_res_mask* to 0x17b (force bit 6 always asserted) — that may give firmware a stable HT clock long enough to write something.

### Ruled out

| Hypothesis | Test | Outcome |
|---|---|---|
| `max_res_mask = 0x1ff` widening doesn't matter | 195 | **falsified** — measurably activates resources 6+7 |
| 3s dwell with heavy TCM poll is universally safe | 195 | **falsified** — safe at res_state=0x13b but unsafe at 0x1fb |

---

## PRE-TEST.195 (2026-04-22) — widen max_res_mask from 0x13f (POR) to 0x1ff (wl.ko value)

### Hypothesis

Firmware is running (confirmed in test.194 post-mortem: ARM CR4 CPUHALT=NO
for 3s after set_active) but stalls on HT-clock polling. `res_state=0x13b`
and `max_res_mask=0x13f` throughout the dwell — the chip cannot grant
resources beyond bits 0..5 + bit 8 because max_res_mask forbids them.

Wl.ko's final PMU write programs `max_res_mask = 0x1ff` (bits 0..8). If
HT clock is driven by one of the bits the POR value of 0x13f masks out
(namely bits 6 and 7 — 0x40 and 0x80), widening to 0x1ff should allow
HT to assert and unblock the firmware poll.

### Implementation

One new write in `brcmf_chip_setup` (chip.c) after the PMU WAR block,
gated on `chip == BCM4360`:

```c
write(CORE_CC_REG(pmu->base, max_res_mask), 0x1ff);
```

Logged via `brcmf_err` with read-back before/after for proof.

### Expected outcomes

| Observation | Interpretation |
|---|---|
| `max_res_mask 0x0000013f -> 0x000001ff` AND TCM scratch shows CHANGED bytes | HT clock gate was the blocker; firmware advancing |
| `max_res_mask 0x0000013f -> 0x000001ff` AND res_state grows past 0x13b | resources 6/7 activated; firmware may still stall later |
| `max_res_mask 0x0000013f -> 0x000001ff` AND everything else identical to test.194 | max widening wasn't the gate; try min widening or OTP |
| Hard crash | unexpected — widening max_res_mask is documented behavior |

### Build + pre-test

- chip.c edited, built clean (brcmfmac.ko + chip.c timestamps match @ 2026-04-22 00:46)
- PCIe state (verified pre-run after crash + SMC reset):
  - `MAbort-`, `CommClk+`, LnkSta Speed 2.5GT/s Width x1 — clean
  - DevSta has `CorrErr+ UnsupReq+` — benign post-boot noise, no FatalErr
- Session context: prior session ended with a crash; user performed SMC reset
  before this run. Boot 0 (2026-04-22 00:49) is fresh, no prior module load.

### Run

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.195.journalctl.txt`.

---

## POST-TEST.194 (2026-04-22) — PCIe2 writes landed cleanly, firmware executes but stalls on HT-clock polling

Log: `phase5/logs/test.194.journalctl.txt` (727 lines visible in dmesg) +
`test.194.journalctl.full.txt` (977 lines journalctl capture).

### Diagnostic output

```
test.194: PCIe2 CLK_CONTROL probe = 0x00000182   ← PCIe2 core alive, probe passed
test.194: SBMBX write done                        ← CONFIGIND 0x098 = 0x1 ✓
test.194: PMCR_REFUP 0x00051852 -> 0x0005185f    ← read back confirms +0x1f bits set
```

### Key finding — ARM CR4 IS RUNNING, firmware stalls on HT clock

Mis-read the earlier logs; ARM CR4 *is* released via `brcmf_chip_set_active`:

```
calling brcmf_chip_set_active resetintr=0xb80ef000 (BusMaster ENABLED)
brcmf_chip_set_active returned true
post-set-active-20ms   ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← ARM released
post-set-active-3000ms ARM CR4 IOCTL=0x00000001 CPUHALT=NO    ← still running
```

**Firmware executes but makes no observable progress.** Consistent with the
stall described in `phase6/wl_pmu_res_init_analysis.md §1`: firmware writes
`NOILPONW` (pmucontrol bit 0x200) early in `si_pmu_init` — we see
pmucontrol change from 0x01770181 → 0x01770381 over the dwell — then
polls for HT clock availability and never sees it.

### Evidence that ARM is running but stalled

| Signal | Value | Interpretation |
|---|---|---|
| ARM CR4 IOCTL | 0x0021 → 0x0001 | CPUHALT cleared ✓ |
| pmucontrol | 0x01770181 → 0x01770381 | NOILPONW bit 0x200 was set by firmware `si_pmu_init` |
| pmustatus | 0x2a (stable) | no progress (expect HT_AVAIL bits to appear) |
| res_state | 0x13b (stable) | HT resource never asserted |
| min_res_mask | 0x13b | unchanged |
| max_res_mask | 0x13f | unchanged — **HT resources likely gated OUT** |
| D11 RESET_CTL | 0x0001 (stable) | D11 still in reset — firmware never gets far enough to initialise D11 |
| TCM | all stable | firmware isn't writing scratch/heap → stuck in polling loop |

### Next hypothesis — widen max_res_mask to 0x1ff

Wl.ko's final writes at +0x153ed/+0x15401 program `min_res_mask` and
`max_res_mask`. POR leaves max_res_mask=0x13f (bits 0..5, 8). Wl.ko
widens max to **0x1ff** (bits 0..8 all permitted). If the HT clock
resource sits at bit 6 or bit 7, the chip can never grant it without
the wider mask, so the firmware's HT-avail poll will never succeed.

Planned test.195:

1. In `brcmf_chip_setup` (before the PMU WAR block), write
   `max_res_mask = 0x1ff` (offset 0x61c). Leave min_res_mask alone
   (POR=0x13b matches wl.ko's resolved value).
2. Use `brcmf_err`/`pr_emerg` for the write log so it's visible.
3. Expected signature of success: either (a) res_state grows beyond
   0x13b over the dwell, or (b) D11 RESET_CTL changes from 0x1 to 0x0
   (fw advances to core init), or (c) TCM scratch regions show writes.

### Ruled out so far

| Hypothesis | Test | Outcome |
|---|---|---|
| chip_pkg=0 PMU WARs (chipcontrol#1, pllcontrol #6/#7/#0xe/#0xf) | 193 | ruled out — writes landed, no effect |
| PCIe2 SBMBX + PMCR_REFUP | 194 | ruled out — writes landed, no effect |
| ARM CR4 not released | 194 | ruled out — set_active confirmed, CPUHALT cleared |
| DLYPERST workaround | (skipped) | doesn't apply — chiprev=3 vs gate `>3` |
| LTR workaround | (skipped) | doesn't apply — pcie2 core rev=1 vs gate ≥2 |

### Remaining untested candidates (priority order)

1. **max_res_mask = 0x1ff** (test.195 — planned above, cheap bit widen)
2. **OTP init / radio calibration** — brcmfmac skips OTP entirely; firmware
   might need OTP-derived values before HT can assert
3. **min_res_mask = 0x1ff** also (go nuclear after max)
4. **D11 core passive init** — brcmfmac doesn't explicitly do anything to D11
   core before set_active; maybe firmware expects clock-enable

---

## PRE-TEST.194 (2026-04-22) — minimal PCIe2 init (SBMBX + PMCR_REFUP) re-enabled with liveness probe

**Status:** pcie.c edited, module built clean, ready to run.

### Hypothesis

After ruling out PMU WARs in test.193, next candidate is the PCIe2 core
bring-up that `brcmf_pcie_attach` currently bypasses entirely for BCM4360.
Auditing bcma's `bcma_core_pcie2_init` against our actual silicon
(chiprev=3, pcie2 core rev=1) eliminates 4 of 6 workarounds (DLYPERST, LTR,
crwlpciegen2, crwlpciegen2-gated) because their revision gates aren't met.

The only UNCONDITIONAL writes bcma does are:
- `PCIE2_SBMBX (0x098) = 0x1` — PCIe2 soft-mbox kick
- `PCIE2_PMCR_REFUP (0x1814) |= 0x1f` — power-management refup timing

If either of these is what gets PCIe2 to assert the signal the ARM CR4
firmware is polling, we may see first-ever TCM/D11 state change.

### Implementation (pcie.c brcmf_pcie_attach)

Replaced the full `if (BCM4360) return;` bypass with:
1. `brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2)`
2. Read `BCMA_CORE_PCIE2_CLK_CONTROL` (offset 0x0 of PCIe2 core) as a
   liveness probe. If it reads back `0xFFFFFFFF` or `0x00000000`, abort
   without doing any writes (PCIe2 core is dead/in reset).
3. Otherwise, perform the two writes via the indirect-config addr/data
   register pair (`CONFIGADDR = 0x120`, `CONFIGDATA = 0x124`):
   - `CONFIGADDR = 0x098; CONFIGDATA = 0x1`   (SBMBX)
   - `CONFIGADDR = 0x1814; DATA = read | 0x1f`  (PMCR_REFUP RMW)

All steps emit `pr_emerg` so output is visible without INFO debug enabled.

### Safety notes

- The original bypass was added to avoid a CTO→MCE crash caused by accessing
  PCIe2 MMIO while the PCIe2 core is in BCMA reset. The bypass condition was
  discovered empirically. Current flow (test.188 baseline + test.193 PMU WARs)
  has already successfully accessed BAR0 MMIO many times in buscore_reset /
  chip_attach / reset_device-bypass paths. The liveness probe catches the
  legacy failure mode if it returns.
- If the CLK_CONTROL probe returns an anomalous value (e.g. 0xDEADBEEF or a
  very bit-stuck pattern), that still indicates some form of "alive" and we
  will proceed with writes. The 0x0 / 0xFFFFFFFF guard is specifically for
  "device response missing" (CTO hardware default).
- The writes are to indirect config space via the on-chip CONFIGADDR/DATA
  pair; they do not touch PCIe link parameters and cannot break the bus.

### Decision tree

| Observation | Meaning | Next |
|---|---|---|
| Probe returns 0xffffffff or 0 | PCIe2 core in reset — writes skipped | Need to release PCIe2 BCMA reset first (test.195) |
| Probe returns real value, writes succeed, firmware boots (TCM CHANGED) | PMCR_REFUP/SBMBX was the gate | Follow firmware startup, enable remaining probe steps |
| Probe returns real value, writes succeed, firmware still silent | PCIe2 unconditional writes not the blocker either | Pivot to OTP init (option B) or D11 core (option C) |
| Hard crash | Something in the write path trips the CTO regression | Restore bypass, investigate core reset state |

### Pre-test checklist

1. Build status: REBUILT CLEAN
2. PCIe state: MAbort-, CommClk+, link up x1/2.5GT/s (verified before test.193)
3. Hypothesis stated: see above
4. Plan committed and pushed: this commit
5. Filesystem synced in commit step

### Run command

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Log → rename to `test.194.journalctl.txt`.

---

## POST-TEST.193 (2026-04-22) — WARs confirmed landing but produce no firmware progress → PMU WARs ruled out as blocker

Log: `phase5/logs/test.193.journalctl.txt` (974 lines) + `.full.txt`.

### Diagnostic output confirmed

```
test.193: chip=0x4360 ccrev=43 pmurev=17 pmucaps=0x10a22b11
test.193: PMU WARs applied — chipcontrol#1 0x00000a10->0x00000a10
          pllcontrol#6=0x080004e2 #0xf=0x0000000e
```

| Fact | Evidence |
|---|---|
| Gate condition met (`chip==4360 && ccrev>3`) | ccrev=43, prints "applied" not "SKIPPED" |
| pmurev=17, pmucaps=0x10a22b11 | matches wl.ko expectations for BCM4360 |
| chipcontrol #1 already has bit 0x800 SET at probe time | read-back 0x00000a10 both before AND after OR-0x800 |
| pllcontrol #6 write landed | read-back 0x080004e2 matches value we wrote |
| pllcontrol #0xf write landed | read-back 0x0000000e matches value we wrote |
| Firmware still blocked | all TCM/D11 scratch UNCHANGED, res_state=0x13b UNCHANGED |

**Bottom line:** chip_pkg=0 PMU WARs are NOT the firmware-stall blocker.
Bit 0x800 of chipcontrol #1 is already set by POR/bootrom; the pllcontrol
#6/#7/#0xe/#0xf writes land cleanly but have no visible downstream effect
on pmustatus / res_state / clk_ctl_st / TCM.

### Comparison vs test.192 (WARs off) and test.191 (baseline)

All PMU/TCM samples IDENTICAL to test.191 baseline. The WARs changed **nothing
visible** in any register we currently sample. Likely explanations:

1. The pllcontrol writes are regulator voltage targets — effect is only
   observable on an oscilloscope / by downstream resources drawing that rail.
   No register snapshot would show it.
2. The WARs enable capabilities the firmware needs **later**, once it's
   running; but firmware never starts because a **different** prerequisite
   is still missing.

Either way, we've exhausted the PMU-WAR hypothesis.

### Next gap to investigate — PCIe2 core bring-up

Log line at test.193 t=2219ms: `BCM4360 test.129: brcmf_pcie_attach bypassed
for BCM4360` — brcmfmac's `brcmf_pcie_attach` returns early for BCM4360 at
pcie.c:895, skipping:

- **PCIE2_CLK_CONTROL DLYPERST/DISSPROMLD** workaround for rev>3
  (this is THE BCM4360-specific PCIe workaround from bcma; phase6 gap analysis
  ranked it #1 of missing writes)
- LTR (Latency Tolerance Reporting) config
- Power-management clock-period, PMCR_REFUP, SBMBX writes

Our earlier decision to bypass brcmf_pcie_attach was to avoid a crash during
development; now that the chip is stable through fw-download, we can re-enable
selective parts. Recommend test.194: implement just the **PCIE2_CLK_CONTROL
DLYPERST/DISSPROMLD** write (bcma `bcma_core_pcie2_workarounds` for BCM4360
corerev>3) as the next candidate unblock.

### Preserved evidence

- `phase5/logs/test.192.journalctl.txt` — WARs silent (INFO filtered)
- `phase5/logs/test.193.journalctl.txt` — WARs confirmed via brcmf_err
- `phase6/wl_pmu_res_init_analysis.md` — PMU WAR analysis with §0/§0.1 corrections

### Action items (next session)

1. Re-read `phase6/downstream_survey.md` and the bcma `driver_pcie2.c`
   DLYPERST/DISSPROMLD workaround.
2. Find the PCIE2 core in chip->cores (PCIE2 coreid / pci_dev base address).
3. Implement the workaround in a new callsite (before set_active / fw download),
   gated on BCM4360 && corerev>3.
4. Test as test.194.

---

## PRE-TEST.193 (2026-04-22) — diagnostic build to confirm WARs land

(Now superseded by POST-TEST.193 above. Original plan retained for context.)

### Test.192 result — no crash, no visible state delta

Log: `phase5/logs/test.192.journalctl.txt` (also `test.192.journalctl.full.txt`,
972 + 971 lines respectively).

**Good news:** the probe path ran end-to-end, reached firmware download (442233
bytes to TCM), completed the 3000ms dwell, cleared bus-master, returned clean
-ENODEV. **No hard crash.**

**Observed state at dwell-3000ms (BASELINE vs WAR-enabled, side-by-side):**

| Register | test.191 (no WARs) | test.192 (WARs) | Delta |
|---|---|---|---|
| `CC-clk_ctl_st` | 0x00050040 | 0x00050040 | UNCHANGED |
| `CC-pmucontrol` pre-release | 0x01770181 | 0x01770181 | same |
| `CC-pmucontrol` post-dwell | 0x01770381 | 0x01770381 | **same CHANGED bit-0x200** |
| `CC-pmustatus` | 0x0000002a | 0x0000002a | UNCHANGED |
| `CC-res_state` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-min_res_mask` | 0x0000013b | 0x0000013b | UNCHANGED |
| `CC-max_res_mask` | 0x0000013f | 0x0000013f | UNCHANGED |
| `CC-pmutimer` | 0x0457e14b → ... | 0x0457e14b → ... | (free-running) |
| All ~30 TCM/D11 scratch regions | all UNCHANGED | all UNCHANGED | UNCHANGED |

Conclusion: **the WAR writes had zero observable effect on any sampled
register.** Either (a) the writes never executed (gate condition false), or
(b) they executed but don't produce any side effect we're currently sampling.

### Diagnostic gap

`brcmf_dbg(INFO, "BCM4360 test.192: applied chip_pkg=0 PMU WARs")` was
silent — INFO-level debug is filtered out of dmesg by default. Every
previous test's `brcmf_dbg(INFO, ...)` output (e.g. `ccrev=%d pmurev=%d`
at chip.c:1131) is also missing from test.188/191/192 logs. So I cannot
distinguish "WARs skipped because `cc->pub.rev ≤ 3`" from "WARs ran but
had no effect".

### Test.193 — diagnostic upgrade (rebuilt clean, ready to run)

Changed `brcmf_dbg(INFO, ...)` → `brcmf_err(...)` for the test.192 marker,
added a chip/rev dump before the gate, and added read-back of
`chipcontrol #1`, `pllcontrol #6`, `pllcontrol #0xf` after the writes to
prove the indirect address/data pair is actually landing values.

Expected new log lines (all via `brcmf_err` so always print):

```
BCM4360 test.193: chip=0x4360 ccrev=<N> pmurev=<M> pmucaps=0x<caps>
BCM4360 test.193: PMU WARs applied — chipcontrol#1 0x<pre>->0x<post> pllcontrol#6=0x080004e2 #0xf=0x0000000e
```
(or `PMU WARs SKIPPED` with the reason.)

### Decision tree after test.193

| Log line | Interpretation | Next |
|---|---|---|
| `WARs SKIPPED (chip=0x4360 ccrev=<N>)` with N ≤ 3 | gate too strict; wl.ko path does not actually require corerev > 3 for chip_pkg=0 | drop the `ccrev>3` constraint, rebuild |
| `WARs SKIPPED` with chip ≠ 0x4360 | unexpected chip id match failure — investigate BRCM_CC_4360_CHIP_ID constant | grep the header |
| `WARs applied` but pllcontrol readbacks show 0x00000000 | write-ignore — wrong offsets or wrong corerev gating in hardware | re-audit, try raw 0x660/0x664 via ops->write32 with absolute offset |
| `WARs applied` with correct readbacks, state still all UNCHANGED | WARs did land but firmware still blocked by something else | pivot to next gap: PCIe2 init (DLYPERST/DISSPROMLD) or min/max_res_mask widen |
| `WARs applied` with correct readbacks, res_state or pmustatus CHANGED | first sign of progress; follow the signal | sample additional resources, keep going |

### Run command (same as test.192)

```
sudo /home/kimptoc/bcm4360-re/phase5/work/test-brcmfmac.sh
```

Expected log: `phase5/logs/test.<N>` (script auto-increments; rename to `test.193.journalctl.txt`).

---

## Older test history

Tests prior to test.193 have been moved to [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md) to keep this file small for fresh-session pickup. When a new POST-TEST is recorded here, the oldest PRE/POST pair gets pushed to the top of the history file so this file always holds the latest 3 tests.
