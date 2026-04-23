# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 15:0x BST, POST-TEST.249 — **fw log output captured.** Counter 0x9d000 = 0x43b1 across ALL 23 dwells (t+100ms..t+90000ms) → test.89 single-write reading directly confirmed; fw hard-freezes before T+100ms. Console window dump revealed: 0x9CA00..0x9CC54 is all `5354414b` ("STAK") stack canary (no log); beginning at 0x9CC58 is a console-tracking struct area (buf_ptr VA `0x8009ccbe` at 0x9CC5C → TCM offset 0x9CCBE). The `0x9CDB0..0x9CE10` "assert window" **actually contained live fw console text** with decodable ASCII: "...01 wl_probe called\n[...]cied ngl_probe called\n" followed by binary header fields (0x3FFFF repeat, offsets in 0x62xxx/0x9Axxx range) and ASCII tail "1258 88.0" (ASCII-decodable — treat as tentative build tag, not verified version string). **Advisor called post-run identified 240-byte gap at 0x9CCB0..0x9CDB0 we never dumped — that's where the end-of-log (newest writes) sits. T249 text starts mid-phrase because we missed the buffer head.** T250 design: fill the 0x9CCB0..0x9D000 gap (~336 B, 84 u32s) in a single t+60s probe, drop the 0x9CA00..0x9CC50 STAK region. Boot 0 started 15:05:49 BST, uptime ~5 min at write time, host healthy. SMC reset required after T249 wedge.)

### What test.249 landed (facts)

Full journal preserved at `phase5/logs/test.249.journalctl.txt` (463 lines kept). Key extracts:

- **Counter freeze (23-for-23):**
  ```
  test.249: t+{100,300,500,700,1000,1500,2000,3000,5000,10000,
            15000,20000,25000,26000,27000,28000,29000,30000,
            35000,45000,60000,90000}ms ctr[0x9d000]=0x000043b1
  ```
  Also t+120000ms implicit — test.238 'dwell done' line at 15:04:10 before crash. Every dwell returns the same value. This directly confirms test.89's observation that 0x9d000 is a single-write static constant — fw wrote 0x43b1 once before our first T+100ms poll and never again.

- **Console window at 0x9CA00..0x9CCA0 (t+60000ms, 160 u32s = 640 B):**
  - 0x9CA00..0x9CC54 (0xD8 bytes / ~54 dwords): all `5354414b` ("STAK") repeated — stack canary fill, not console log.
  - 0x9CC58: `0x00303031` = LE-bytes `31 30 30 00` = ASCII "100\0" (possibly a version/tag field header)
  - 0x9CC5C: `0x8009ccbe` = fw VA → TCM offset `0x9CCBE` (matches T248's `0x9cc5c=8009ccbe`)
  - 0x9CC60: `0x00000001`
  - 0x9CC64: `0x0000000a`
  - 0x9CC68: `0x0009ccc7` — looks like a TCM offset (0x9CCC7 = 0x9CCBE + 9)
  - 0x9CC6C: `0x8009ccbe` (duplicate VA)
  - 0x9CC70: `0x32623131` = LE-bytes "11b2"
  - 0x9CC74: `0x31306132` = LE-bytes "2a01"
  - 0x9CC78: `0x10a22b11` / 0x9CC7C: `0x00000010`

- **"Assert" window at 0x9CDB0..0x9CE0C (t+90000ms, 24 u32s = 96 B) — actually console log content:**
  ```
  77203130 72705f6c 2065626f 6c6c6163 000a6465 64656963 5f6c676e 626f7270 61632065 64656c6c 0000000a
  ```
  Decoded LE-ASCII: `"01 wl_probe called\n[?]cied ngl_probe called\n"` (the stem before "ngl_probe" — probably "d" making "dngl_probe" — and the stem before "01" are outside the window).
  
  Then binary fields: `0x713, 0, 0x3FFFF, 0x629C0, 0x9AF80, 0xA, 0x185D, 0x3FFFF, 0x51, 0x62910, 0xA87` — look like address/size init-log values (0x629C0 = 404928, 0x9AF80 = 634240 — both under TCM size 0xA0000 = 655360).
  
  Then ASCII tail `38353231 302e3838` = bytes `"1258" + "88.0"` → "125888.0" — tentative fw build ID or version string.

### What test.249 settled (facts)

- **Test.89 single-write reading confirmed.** 0x43b1 at 0x9d000 is a constant, not a counter. Fw stops writing to 0x9d000 before T+100ms.
- **Fw did print console output before freezing.** Text "wl_probe called", "ngl_probe called", and ASCII "1258/88.0" all visible in the 0x9CDB0 region. The fw's console buffer is live and contains fragments of boot banner / init log / possibly build tag.
- **Console_info struct location tentatively at 0x9CC54..0x9CC7C** (hypothesis; upstream `brcmf_pcie_console` offsets are {base+8 buf_addr, base+12 bufsize, base+16 write_idx}. If base = 0x9CC54, then buf_addr=0x8009ccbe at 0x9CC5C matches, but bufsize=1 at 0x9CC60 is nonsensical. Either base ≠ 0x9CC54, or BCM4360's fw uses a different struct layout. Verify in T250 by dumping more context.)
- **"Assert window" misframing from PRE-TEST.249 corrected.** The 0x9CDB0 region is console log content, not separate assert text. `wl_probe called` is normal fw init, not a trap message. No assert/trap was hit — fw just hangs without fault-reporting (consistent with test.94 hang at fn 0x1FC2 being a wait-loop, not an exception).
- **240-byte gap at 0x9CCB0..0x9CDB0 never dumped.** Buf_ptr VA 0x8009ccbe → TCM 0x9CCBE. T249 console window ended at 0x9CCA0, T249 assert window started at 0x9CDB0. The buffer between them is where newest log writes land before wrapping — that's why visible text starts mid-phrase.
- **SMC reset required** after wedge (consistent with T246..T248 streak).

### Next test direction (T250 — advisor-confirmed)

Single-focus probe to fill the 240-byte gap and close out the buf_ptr-first-decode:

1. **Primary read at t+60000ms: `TCM[0x9CCB0..0x9D000]`** — 84 u32s = 336 bytes. Covers the unread gap AND extends past 0x9CDB0 to capture the rest of the log region in one pass. Also starts 8 bytes before 0x9CCB8 (0x9CCBE = buf_ptr low 20 bits) to show pre-buffer context.
2. **Drop the 0x9CA00..0x9CC50 window** — T249 proved it's all STAK canary, zero info content. Saves ~88 u32 reads.
3. **Keep the per-dwell 0x9d000 poll** — 0 new cost, maintains frozen-counter streak evidence.
4. **Optional secondary at t+90000ms: `TCM[0x9CFE0..0x9D020]`** — 16 u32s. Trap struct region (T248 showed 0x9CFE0=`0x000934C0`). Only fires if ≥30s headroom remains.

POST decode strategy: hex-dump with byte-swap-to-char column; verify console_info struct layout by triangulating buf_ptr/bufsize/write_idx against what's in the dumped bytes.

**Fallback if gap dump is blank**: the log buffer is small or wrapped. Widen the net one more time, or pivot to decoding 0x9CFE0 trap region and/or fn 0x1FC2 disassembly path (test.94).

Proceed to PRE-TEST.250 design.

### What test.248 landed (facts)

Two journal lines captured pre-crash (full journal at `phase5/logs/test.248.journalctl.txt`):

```
Apr 23 13:45:56.923 test.248: pre-FORCEHT TCM[16 off] =
  0x9c000=f79d6dd9 0x9cc5c=d5f2d856 0x9cdb0=b77ddbaa 0x9cfe0=4a426302 0x9d000=4d917b4a
  0x9d0a4=555c2631 0x9f0cc=870ca015 0x9fffc=ffc70038
  0x90000=84270be1 0x94000=464c65ec 0x98000=15f3b94d 0x9a000=bc3125a9
  0x9b000=85177bed 0x9e000=5790b619 0x9f000=7bf1b8b4 0x9fe00=14086122

Apr 23 13:47:26.936 test.248: t+90000ms TCM[16 off] =
  0x9c000=5354414b 0x9cc5c=8009ccbe 0x9cdb0=77203030 0x9cfe0=000934c0 0x9d000=000043b1
  0x9d0a4=555c2631 0x9f0cc=870ca015 0x9fffc=ffc70038
  0x90000=84270be1 0x94000=464c65ec 0x98000=00000000 0x9a000=00000000
  0x9b000=85177bed 0x9e000=5790b619 0x9f000=7bf1b8b4 0x9fe00=14086122
```

(Note: 0x9b000 **did** change in journal but not in diff summary above — re-read: pre=0x85177bed, post=0x00000000 → CHANGED. Correcting: 8 offsets changed, zeroed set is 0x98000/0x9a000/0x9b000. Original log: line has `0x9b000=00000000` at t+90000ms, `0x9b000=85177bed` at pre-FORCEHT. The two-line diff is authoritative.)

### Diff table

| Offset | pre-FORCEHT | t+90000ms | Δ | Notes |
|---|---|---|---|---|
| 0x9c000 | f79d6dd9 | **5354414b** | ✓ | fw wrote ASCII "STAK" — stack-top marker |
| 0x9cc5c | d5f2d856 | **8009ccbe** | ✓ | console ring write-ptr — fw VA (0x80000000 region = ARM CR4 dcache/TCM alias) |
| 0x9cdb0 | b77ddbaa | **77203030** | ✓ | bytes "30 30 20 77" = `"00 w"` — start of ASCII text (assert/trap header?) |
| 0x9cfe0 | 4a426302 | **000934c0** | ✓ | looks like a small counter or pointer (0x934c0 = fw offset?) |
| 0x9d000 | 4d917b4a | **000043b1** | ✓ | **Exact match to pre-T230's frozen-counter endpoint.** Same stall state. |
| 0x9d0a4 | 555c2631 | 555c2631 | — | unchanged — likely fw-image bytes (data segment in 0x9D0A4) |
| 0x9f0cc | 870ca015 | 870ca015 | — | unchanged — likely fw-image bytes |
| 0x9fffc | ffc70038 | ffc70038 | — | NVRAM marker, redundant with T239 |
| 0x90000 | 84270be1 | 84270be1 | — | unchanged — matches T245 baseline exactly (fingerprint or fw-image) |
| 0x94000 | 464c65ec | 464c65ec | — | unchanged — fw image |
| 0x98000 | 15f3b94d | **00000000** | ✓ | fw **zeroed** — BSS/heap init pattern |
| 0x9a000 | bc3125a9 | **00000000** | ✓ | fw **zeroed** |
| 0x9b000 | 85177bed | **00000000** | ✓ | fw **zeroed** |
| 0x9e000 | 5790b619 | 5790b619 | — | unchanged — fw image |
| 0x9f000 | 7bf1b8b4 | 7bf1b8b4 | — | unchanged — fw image |
| 0x9fe00 | 14086122 | 14086122 | — | unchanged — random_seed region start (T236 seed) |

### What test.248 settled (facts)

- **(S2) refined, not universal.** T247's "fw touches none of our 80 observed bytes" is true *for those bytes* but fw **does** touch other TCM regions. Fw stall reading needs to be qualified: "fw stalls at a specific state, after doing substantial work."
- **Fw reaches the same pre-T230 stall state.** `0x9d000=0x000043b1` is byte-identical to the pre-T230 observation of "counter evolved 0→0x58c8c(T+2ms)→0x43b1(T+12ms)→frozen." This is strong continuity: the fw crash/stall pattern is the same as pre-T230; our intervening investigation has not been changing *what* fw does, just what *we* see.
- **Console subsystem is alive.** Write-pointer at 0x9cc5c is a valid fw-VA (0x8009ccbe — ARM Cortex-R dcache/TCM-alias window). The log content should live at that VA, which in our BAR2 TCM window maps to an offset we can probe.
- **Stack, BSS, olmsg are all initialized.** "STAK" marker at 0x9c000, three zeroed BSS regions, olmsg addresses 0x9D0A4 and 0x9F0CC populated (even if those specific bytes are fw-image, the *surrounding* structure is presumably live).
- **W2 fw-alive branch of the matrix is hit.** Per PRE-TEST.248 matrix: "Known-hot offsets changed (0x9cc5c / 0x9d000 / 0x9D0A4 / 0x9F0CC or trap addresses) → Phase 6 pivot becomes 'read the console' — capture console buffer, decode fw output."
- **Wedge within ≤1s of the t+90s T248 probe burst.** T248 t+90000ms line at 13:47:26.936; boot's last journal entry at 13:47:26 (same second). Earlier phrasing "[90s, 120s] wedge bracket" was too generous — actual unchangedness is "within log resolution, wedge occurred ≤1s after the t+90s probe fired." Anticipated T249 probe-cost uplift (+160 reads at t+90s) may push into the wedge; split across two dwells if needed. **Note**: this ~90s host-side wedge is not fw execution progress — fw froze at T+12ms per test.89. The 90s is kernel driver load/timeout dynamics.
- **SMC reset required** (n=2 post-T247 streak — consistent with T246/T247 pattern).

### Next test direction (T249 — advisor-confirmed)

**Pre-freeze log output lives in the console buffer, frozen-in-place since T+12ms.** T249 reads the region around 0x9CC5C and the 0x9CDB0 assert-text area to capture anything fw printed during its 0–12ms init window before the hang at fn 0x1FC2.

1. **Single snapshot at t+90000ms** (no second snapshot — fw is frozen, read would be identical; probe cost better spent widening the window).
2. **Primary read: `TCM[0x9CA00..0x9CCA0]` — 160 u32s = 640 bytes.** Covers console log buffer + struct area around write-idx at 0x9CC5C. Decode dwords at 0x9CC5C-8 and 0x9CC5C+4..8 first — standard Broadcom console_info layout is `{buf_ptr, bufsize, in_idx, out_idx}` contiguous. Translate (buf_ptr & 0xFFFFF) → TCM offset for T250 buffer-content read.
3. **Secondary read: `TCM[0x9CDB0..0x9CE10]` — 24 u32s = 96 bytes.** Historic assert-text region per pcie.c annotations ("ASSERT in file hndarm.c line 397..."); T248's 0x9CDB0=0x77203030 = bytes "00 w" in LE already hints ASCII text.
4. **Add 0x9d000 to per-dwell poll** — one u32/dwell, effectively free. Closes out "is the counter really frozen from first dwell?" directly in this run's data.
5. POST decode: hex-dump with byte-swap-to-char column for the console/assert regions.

**Fallback if both windows are null/garbage**: pivot to fn 0x1FC2 disassembly path from test.94 — that thread was active pre-T230 and has the most direct reach to the hang. Don't accept null twice in this direction before revisiting.

Proceed to PRE-TEST.250 design.

---

## PRE-TEST.250 (2026-04-23 15:3x BST, boot 0 after test.249 crash + SMC reset) — **console buf_ptr gap dump.** T249 captured log content fragments starting mid-phrase at 0x9CDB0; the 240-byte gap at 0x9CCB0..0x9CDB0 (exactly where buf_ptr VA 0x8009ccbe → TCM[0x9CCBE] lives) was never dumped. Single-focus probe fills it; STAK-canary window dropped.

### Hypothesis

Fw wrote log content into its ring buffer before freezing at T+12ms. T249 showed: `0x9CDB0..0x9CE0C` has ASCII "01 wl_probe called\n[?]cied ngl_probe called\n" + binary init values + ASCII "1258 88.0". Both text fragments start mid-word — the stems live in the 0x9CCB0..0x9CDB0 gap. T250 dumps that gap (plus ~80 bytes past T249's window end for continuity verification).

**Observables:**
- 0x9CCB0..0x9CCBC: pre-buffer context (8 bytes before buf_ptr TCM[0x9CCBE]). Possibly end of the struct area at 0x9CC7C + padding.
- 0x9CCBE onwards: start of console ring buffer content. If fw printed a boot banner, version line, NVRAM parse output — it's here.
- 0x9CD30..0x9CDAC: middle-of-log content (unclear whether wrapped or linear).
- 0x9CDB0..0x9CE2C: re-dump of T249's assert-window region + 32 bytes extension. Consistency check between runs AND extends view to cover 32 bytes past 0x9CE0C.
- Counter 0x9d000 per dwell: kept via the T239 extension — should be 0x43b1 for all 23 dwells (replicates T249 n=1).

**Decode goal**: produce a contiguous text-readable dump of whatever the fw wrote to its console between T+0 and T+12ms. Expect to see: fw version / build tag / date, NVRAM parse summary, driver-interface probe lines ("wl_probe", "dngl_probe"), possibly an error line immediately before the hang.

### Design

**Single probe at t+60000ms** (no t+90s probe for T250):

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x9CCB0..0x9CE30]` (96 u32s = 384 B) | 96 | Fills the unread gap and extends past T249's assert window by 32 bytes. 30s headroom before wedge per T249 timing. |
| every dwell (23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Same per-dwell poll as T249, now gated on T249 \|\| T250. Replicates frozen-counter streak. |

**Log format (3 pr_emerg lines at t+60s):**

```
test.250: t+60000ms TCM[0x9ccb0..0x9cd2c] = 32 hex values (pre-buf + log head)
test.250: t+60000ms TCM[0x9cd30..0x9cdac] = 32 hex values (log mid)
test.250: t+60000ms TCM[0x9cdb0..0x9ce2c] = 32 hex values (T249 assert-window region + extension)
```

Each line ~350 chars (32 × 9 + prefix ~60) — comfortably under kernel LOG_LINE_MAX 1024.

**Runtime config**: `bcm4360_test249_console_dump=0 bcm4360_test250_console_gap=1`. Drops T249's 160-u32 STAK window (zero info content) while keeping the per-dwell ctr poll.

### Next-step matrix

| Observation | Implication | T251 direction |
|---|---|---|
| Gap contains readable fw boot banner / version / NVRAM lines | Log buffer captured; decode and document the full startup log. Identify the LAST line fw printed — points at the hang location. | Decode fully; correlate last log line with fw code to find the hang point. |
| Gap is mostly zeros | Buffer hasn't been written this deeply; either fw log buffer is elsewhere or very short. | Widen the search region (0x9D000+ or 0x9C000-) or fall back to fn 0x1FC2 disassembly. |
| Gap contains more "STAK" canary or ASCII-but-garbled | Buf_ptr VA decoding is wrong; the 0x8009ccbe value points elsewhere. | Re-derive console base via upstream `brcmf_pcie_bus_console_init` semantics (shared_info ptr + 20). But shared_info ptr = 0xffc70038 was garbage pre-T230, so this may dead-end. |
| Gap contains structured binary (addresses, dma handles) | Region isn't the log ring but something else — perhaps heap/stack layout tables. | Decode as struct fields rather than ASCII; compare with brcmf_pcie_shared_info layout. |
| Counter 0x9d000 = 0x43b1 across all 23 dwells (replicated from T249) | Test.89 single-write reading confirmed at n=2. | No further action on this axis. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 96 at t+60s + 23 per-dwell = 119 reads. Less than T249 (160+24+23=207). Well within probe envelope.
- SMC reset expected to be required after wedge (consistent with T246–T249 streak).

### Pre-test checklist

1. **Build status**: **REBUILT + VERIFIED.** md5sum `7cb5d53c9f8785e86522996f63f4a6a7` on `brcmfmac.ko`. `modinfo` shows new param `bcm4360_test250_console_gap`. `strings` confirms all 3 format lines. Only pre-existing unused-variable warnings (no new regressions). Commit: `aac27a2`.
2. **PCIe state**: **clean.** `Mem+ BusMaster+`, MAbort-, CommClk+, LnkSta 2.5GT/s x1. UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky, same as T248/T249). Re-verified 15:30 BST.
3. **Hypothesis**: stated — 240-byte gap contains fw log content that starts T249's mid-phrase fragments ("wl_probe called", "ngl_probe called").
4. **Plan**: this block + code change committed and pushed before insmod.
5. **Host state**: boot 0 started 15:05:49 BST, uptime ~24 min at write time, stable. No brcm modules loaded.

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
    bcm4360_test250_console_gap=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: `bcm4360_test249_console_dump` is NOT set (dropping STAK window).

### Expected artifacts

- `phase5/logs/test.250.run.txt`
- `phase5/logs/test.250.journalctl.txt`

---

## Prior outcome (test.247 — first shared-struct probe null across all 23 dwells pre-FORCEHT. Struct at TCM[0x80000..0x80047] unchanged; ramsize-4 unchanged at `0xffc70038`; tail-TCM unchanged. Wedge [90s, 120s], SMC reset required. Matrix row 3: (S1) minimal-signature falsified. **Re-interpreted by T248: the struct-untouched reading was true only for those 80 bytes; fw IS active in upper TCM at 0x9cxxx range.**)

### What test.247 landed (facts)

```
test.247: pre-FORCEHT pre-placed shared-struct at TCM[0x80000] (72 bytes, version=5 @offset 0, rest=0)
test.247: pre-FORCEHT readback = 00000005 00000000 ...00000000   [18 u32s, write landed as intended]

All 23 per-dwell polls (t+100ms..t+90000ms):
  test.247: struct[0x80000..0x80047] = 00000005 00000000 ... 00000000   [UNCHANGED across all dwells]
  test.239: sharedram_ptr=0xffc70038                                     [UNCHANGED across all dwells]
  test.240: tail-TCM[-64..-8] = <NVRAM trailer text>                     [UNCHANGED across all dwells]

Last journal line: Apr 23 11:48:18 t+90000ms dwell ladder entries.
```

### What test.247 settled (facts only — interpretation deferred to advisor)

- **Fw runs ≥90s post-set_active but touches NONE of the observed TCM regions.** Three independent observation windows — struct region `[0x80000..0x80047]`, ramsize-4, ramsize-tail `[-64..-8]` — all report unchanged across 23 polls. This is a stronger statement than "(S1) falsified" alone.
- **BAR2 write of a 72-byte struct into dead TCM lands cleanly at pre-FORCEHT.** Readback matches written bytes; consistent with T245/T246 BAR2 PASS.
- **Probe cost stays constant.** T245 alone, T246 (T245+T246), T247 (T247 only, larger footprint) all reach t+90000ms. Pre-FORCEHT probe insertion costs ~30s of fw runtime regardless of probe size (within the range measured). n=3 now.
- **SMC reset required this time.** T245 no-SMC-reset (n=1), T246 SMC required (n=1), T247 SMC required (n=1). Streak is no clearer.

### Open question to resolve before PRE-TEST.248

**Does "fw touches none of our observed regions" falsify (S1) as a class, or only "(S1) with minimal host-pre-placed signature"?** Observation windows cover ~80 bytes out of 640KB TCM. A wide-scan probe across ~8–16 offsets would cheaply distinguish "fw is stalled doing nothing" from "fw is writing somewhere we're not looking." That vs a Phase-6 pivot is the next decision.

### Advisor response (2026-04-23 12:2x BST, post-T247 reconcile call)

Two cheap intermediate probes to run before any Phase-6 pivot:
1. **Wide-TCM scan** — snapshot ~16 u32 offsets spread across TCM[0..0xA0000) at pre-FORCEHT and at t+90000ms (pre-wedge); diff = "fw wrote here." Distinguishes "fw stalled doing nothing" from "fw writing somewhere we're not looking."
2. **Multi-signature sweep** — our version=5 may be wrong for BCM4360's Apple-variant fw. Try version=5,6,7 (MIN/MAX bounds upstream accepts) or an alternate magic word. Only if T248 wide-scan returns null.

Order: wide-scan first (T248); signature sweep deferred to T249 if T248 null. Rationale: if wide-scan finds fw writing *anywhere*, signature sweep is probably moot — we'd know fw is working, not stalled.

---

## PRE-TEST.249 (2026-04-23 14:5x BST — **EXECUTED 2026-04-23 15:01:48; POST-TEST.249 summarized at top.** Outcome: counter 0x43b1 frozen across all 23 dwells (test.89 single-write reading confirmed); console-window dump found STAK canary at 0x9CA00..0x9CC54 and tentative console_info struct at 0x9CC58+; "assert window" actually contained live console log text (wl_probe called, ngl_probe called, ASCII "1258/88.0"). 240-byte gap at 0x9CCB0..0x9CDB0 never dumped — advisor-identified, becomes T250 primary target.) — **console-buffer + assert-text window dump.** Fw is frozen at T+12ms (test.89) but its console write-idx evolved (T248: 0x9cc5c d5f2d856 → 8009ccbe); if the console was flushed before the hang, its buffer contents hold fw log output from the 0–12ms pre-freeze window. Split probe load across two dwells to stay inside the wedge envelope.

### Hypothesis

T248 proved fw runs briefly, sets up stack + BSS + console, then freezes at the same state as pre-T230 (0x9d000=0x43b1). Fw printed *something* during init — firmware images of this class typically emit a boot banner, NVRAM parse summary, or assert message before halting. That text sits frozen in the console log buffer at a VA pointed to by a pointer near 0x9CC5C. Observables:

- Dwords near 0x9CC5C likely follow Broadcom `console_info` layout: `{buf_ptr, bufsize, in_idx, out_idx}` contiguous. Need 8 dwords around the write-idx location to see this.
- Prior assert-text region `0x9CDB0..0x9CE10` holds ASCII trap/panic messages in tests 213/216/217. T248 saw 0x9CDB0=0x77203030 = bytes "30 30 20 77" = `"00 w"` — strong hint an ASCII string starts there.
- Counter at 0x9d000: advisor-requested added to per-dwell poll. If frozen from first dwell (t+100ms) at 0x43b1, test.89's single-write reading is directly reproduced in this run's data.

### Design

**Dwell split (avoids piling probe cost at t+90s, where T248 landed ≤1s before wedge):**

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x9CA00..0x9CCA0]` (160 u32s = 640B) | 160 | Heavy read, window around console write-idx. Fw is frozen so content is identical at t+60s and t+90s; reading earlier keeps ≥30s headroom before the wedge. |
| t+90000ms | `TCM[0x9CDB0..0x9CE10]` (24 u32s = 96B) | 24 | Light read, prior assert-text region. Keeps T248's existing t+90s probe cost roughly constant. |
| every dwell (t+100ms..t+120000ms, 23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Advisor-requested; closes out "is counter frozen from first dwell?" directly. Matches test.89's single-write reading if all 23 dwells return 0x43b1. |

**Log format (machine-diffable, split into readable lines):**

Per-dwell (extension of `BCM4360_T239_POLL` — no new tag):
```
test.249: t+XXXms ctr[0x9d000]=%08x
```

At t+60s (new macro `BCM4360_T249_CONSOLE_WINDOW`, 5 lines × 32 u32s = 160 dwords):
```
test.249: t+60000ms TCM[0x9ca00..0x9ca7c] = 32 hex values
test.249: t+60000ms TCM[0x9ca80..0x9cafc] = 32 hex values
test.249: t+60000ms TCM[0x9cb00..0x9cb7c] = 32 hex values
test.249: t+60000ms TCM[0x9cb80..0x9cbfc] = 32 hex values
test.249: t+60000ms TCM[0x9cc00..0x9cc7c] = 32 hex values  (contains 0x9cc5c write-idx)
```

At t+90s (new macro `BCM4360_T249_ASSERT_WINDOW`, 1 line × 24 u32s):
```
test.249: t+90000ms TCM[0x9cdb0..0x9ce0c] = 24 hex values
```

Line-length budget: 32 u32s × 9 chars = 288 chars + prefix ~60 chars = ~350 chars. Comfortably under kernel `LOG_LINE_MAX` (1024).

### Next-step matrix

| Observation | Implication | T250 direction |
|---|---|---|
| Console window 0x9CA00..0x9CCA0 contains ASCII text (readable words visible after byte-swap) | Console has fw boot/log output. Dwords preceding 0x9CC5C are the console_info struct. Extract `buf_ptr`, translate VA→TCM offset, read buffer content in T250. | Dump full console buffer at the derived TCM offset; decode. |
| Window contains mostly zeros/fingerprint-like values, no ASCII | Console exists (write-idx is a valid VA) but buffer content is elsewhere. Search wider (0x9C000..0x9D000) for ASCII clusters. | Widen search or fall back to fn 0x1FC2 disassembly path. |
| Assert window 0x9CDB0..0x9CE10 contains "ASSERT in file..." text | Fw hit an assert; the hang at fn 0x1FC2 is probably an assert-induced halt, not a hardware lockup. | Decode assert text → file/line → locate in fw disassembly → root cause. |
| Counter 0x9d000 is 0x43b1 from t+100ms onward (all 23 dwells) | Test.89's single-write reading confirmed directly. Fw hard-freezes before T+100ms. | Closes out the frozen-counter hypothesis; directional signal already used. |
| Counter 0x9d000 evolves through dwells | Fw is not frozen as assumed; need new interpretation. | Density around counter; probably bigger rewrite of current model. |

### Safety

- All BAR2 reads, no register side effects. Same class as T247/T248/T239 probes.
- Total additional reads: 160 (t+60s) + 24 (t+90s) + 23 × 1 (per-dwell) = 207 reads on top of T247/T248 baseline.
- t+60s currently has no T247/T248 probe other than the standard T239/T240/T247 polls. Adding 160 reads at t+60s is the largest uplift; t+60s has ~30s headroom before the wedge.
- Continuity: T247 struct at 0x80000 + T248 wide-scan both kept on. Same binary gains T249 param additively.

### Code change outline

1. New module param `bcm4360_test249_console_dump` near T248's (pcie.c:268–270).
2. New offset arrays (optional; can use explicit loops) — 160 u32s at `0x9CA00 + i*4` and 24 u32s at `0x9CDB0 + j*4`.
3. New macros:
   - `BCM4360_T249_CONSOLE_WINDOW(stage_tag)` — reads 160 u32s, emits 5 `pr_emerg` lines of 32 u32s each.
   - `BCM4360_T249_ASSERT_WINDOW(stage_tag)` — reads 24 u32s, emits 1 `pr_emerg` line.
4. Extend `BCM4360_T239_POLL` with a fourth conditional `if (bcm4360_test249_console_dump)` reading 0x9d000 as one line.
5. Invocation: `BCM4360_T249_CONSOLE_WINDOW("t+60000ms")` right after `BCM4360_T239_POLL("60000ms")` (pcie.c:3229), gated on the param. `BCM4360_T249_ASSERT_WINDOW("t+90000ms")` right after `BCM4360_T248_WIDESCAN("t+90000ms")` (pcie.c:3233).

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
    bcm4360_test249_console_dump=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Pre-test checklist (complete — READY TO FIRE)

1. Build status: **REBUILT + VERIFIED.** md5sum `22fbd23dbcf68479c3689f0d8e7db2a1` on `brcmfmac.ko`. `modinfo` shows `parm: bcm4360_test249_console_dump`. `strings` confirms all 6 format lines (5 × 32-u32 console window at t+60s + 1 × 24-u32 assert window at t+90s) and 23 per-dwell 0x9d000 ctr format lines. Only pre-existing unused-variable warnings (no new regressions).
2. PCIe state: **clean.** `Mem+ BusMaster+`, MAbort-, CommClk+, LnkSta 2.5GT/s x1, UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky, same as T248). Re-verified 15:00 BST.
3. Hypothesis: stated — pre-freeze fw log output in 0x9CA00..0x9CCA0 console window or 0x9CDB0..0x9CE10 assert region; counter 0x43b1 frozen across all 23 dwells.
4. Plan: this block + code change committed; push + sync before insmod.
5. Host state: boot 0 started 14:41, uptime ~19 min, stable. No brcm modules loaded (mt76 Wi-Fi adapter unrelated).

### Expected artifacts

- `phase5/logs/test.249.run.txt`
- `phase5/logs/test.249.journalctl.txt`

---

## PRE-TEST.248 (2026-04-23 12:2x BST, boot 0 after test.247 crash + SMC reset) — **wide-TCM scan. EXECUTED 2026-04-23 13:45; POST-TEST.248 summarized at top. Outcome: W2 fw-alive variant. Both snapshots landed pre-crash; diff shows 8 of 16 offsets changed including all known-hot fw-runtime markers.**

### Hypothesis

T247 null result covers only ~80 bytes (struct region + ramsize-4 + tail-TCM) out of 640KB TCM. Fw may be executing and modifying TCM outside those windows. A wide-scan diff (baseline vs pre-wedge) exposes any such activity. Three outcomes:

- **(W1) Wide-scan null** (all 16 offsets unchanged between baseline and pre-wedge). Strengthens (S2) fw-stalled reading to "fw touches no TCM region we sampled." Next: T249 signature sweep (version=5/6/7 + alternate magic) to falsify (S1) as a class.
- **(W2) Wide-scan shows changes at offset(s) ∉ {0x80000, ramsize-4, tail}**. Falsifies "fw stalled doing nothing." Fw is working; we've just been looking in the wrong place. Next: densify around the changing offset(s); decode what fw is writing.
- **(W3) Wide-scan shows changes inside fw code region [0..0x6bf78]**. Would mean fw is self-modifying or writing to its own code segment — very unlikely. Flag and decompose.

### Design (refined per `phase6/test248_bcm_work.md` A1 + pcie.c / HISTORY review)

User guidance: prioritize upper TCM [0x90000..0xa0000), include 0x98000 and 0x9c000 at minimum, compact two-snapshot scan across that region, keep T247 struct continuity.

Pcie.c (line 4128 `t66_scan`) and HISTORY (lines 4607, 5073) reveal a map of *previously observed* fw-written upper-TCM offsets from earlier tests (test.66/81/89/94/96 and test.213/216/217 trap-text decode). Using these directly is far more informative than uniform stride:

**Known-hot offsets (fw writes here pre-T230):**
- `0x9cc5c` — console ring write pointer (virtual addr field)
- `0x9d000` — counter that evolved `0 → 0x58c8c (T+2ms) → 0x43b1 (T+12ms) → frozen`
- `0x9D0A4` — "olmsg shared_info magic_start"
- `0x9F0CC` — "olmsg fw_init_done"
- `0x9c000` — "STAK" marker (pcie.c:2292 comment)

**Known-hot offsets on fw assert/trap (test.213/216/217 evidence):**
- `0x9cdb0..0x9ce10` — assert text ("ASSERT in file hndarm.c line 397 ... v=43, wd_msticks=32")
- `0x9cfe0` — trap struct (r5 base, chip_info ptr, TCM top, trap PC)

**Decision**: sample 16 u32 offsets — 8 known-hot + 8 upper-TCM gap coverage — at two snapshots (pre-FORCEHT baseline + t+90000ms pre-wedge). If ANY known-hot offset shows baseline != pre-wedge, fw is alive and writing. If all null, fw is genuinely quiescent in observed regions.

**Final T248 offset list (16 u32):**

Known-hot (8):
- `0x9c000` (STAK marker — user-specified)
- `0x9cc5c` (console ring write pointer)
- `0x9cdb0` (prior trap ASCII address)
- `0x9cfe0` (prior trap struct address)
- `0x9d000` (prior evolving counter)
- `0x9D0A4` (olmsg magic)
- `0x9F0CC` (olmsg fw_init_done)
- `0x9FFFC` (ramsize-4 — redundant with T239 but unifies the record)

Upper-TCM gap coverage (8):
- `0x90000` (BAR2 round-trip anchor, adjacent to T245/T246 observations)
- `0x94000`
- `0x98000` (user-specified)
- `0x9A000`
- `0x9B000`
- `0x9E000` (between olmsg magic and fw_init_done)
- `0x9F000`
- `0x9FE00` (just below random_seed region start)

**Continuity**: keep `bcm4360_test247_preplace_shared=1` and struct at 0x80000 version=5. No change to T247's block.
**Cost**: 2 snapshots × 16 reads = 32 BAR2 reads total. ≪ T247's per-dwell polls.
**Log format (machine-diffable)**: one `pr_emerg` line per snapshot, fixed-order hex values:
```
test.248: <stage> TCM[16 off] = 0x9c000=%08x 0x9cc5c=%08x 0x9cdb0=%08x 0x9cfe0=%08x 0x9d000=%08x 0x9d0a4=%08x 0x9f0cc=%08x 0x9fffc=%08x 0x90000=%08x 0x94000=%08x 0x98000=%08x 0x9a000=%08x 0x9b000=%08x 0x9e000=%08x 0x9f000=%08x 0x9fe00=%08x
```
Two `pr_emerg` lines total (stage="pre-FORCEHT" and stage="t+90000ms"), plus an existing T247 per-dwell poll already covers struct region and ramsize-4.

### Next-step matrix (W1/W2/W3 per phase6/test248_bcm_work.md A6)

| Wide-scan diff | Implication | Test.249 direction |
|---|---|---|
| All 16 offsets unchanged between pre-FORCEHT and t+90000ms (including known-hot 0x9cc5c, 0x9d000, 0x9D0A4, 0x9F0CC) | **(W1)** — "fw stalled doing nothing" strengthened to near-certainty. Fw never writes any of the previously-observed hot addresses. | T249: signature sweep (version=5/6/7 + alt magic at struct [0]) to falsify (S1) as a class. If that also nulls, Phase 6 PMU/PLL work is justified. |
| One or more dead-region offsets (0x90000..0x9B000 or 0x9E000..0x9FE00) changed but known-hot offsets did not | **(W2, dead-region variant)** — fw IS working, just not at the post-T230 addresses we'd expect. | Densify around the changing offset(s) with a focused stride; decode what's being written. |
| Known-hot offsets changed (0x9cc5c / 0x9d000 / 0x9D0A4 / 0x9F0CC or trap addresses) | **(W2, fw-alive variant)** — fw has progressed past the quiescence we inferred from T239/T247. Console pointer or olmsg state evolving = strong forward signal. | Phase 6 pivot becomes "read the console" — capture console buffer, decode fw output. |
| NVRAM ramsize-4 or tail-TCM changed (contradicts T239/T240 with per-dwell polls) | **(W3, contradicts prior obs)** | Verify, then treat as if W2 fw-alive. |

### Safety

- BAR2 reads only (no writes beyond T247's existing struct placement); no register touch beyond T247 baseline.
- +32 BAR2 reads total vs T247 (16 pre-FORCEHT, 16 at t+90000ms). Well within T247's probe-cost envelope.
- Reads from fw image offsets do not perturb fw execution (read-only).
- SMC reset expected to be required after wedge (consistent with T247).

### Code change outline (A2 from phase6/test248_bcm_work.md)

1. **New module param** `bcm4360_test248_wide_tcm_scan` (default 0) near T247's param.
2. **Static offset array** `bcm4360_t248_offsets[16]` with the 16 addresses above.
3. **New macro** `BCM4360_T248_WIDESCAN(stage_tag)` — loops over the array, reads 16 u32s via `brcmf_pcie_read_ram32()`, emits one machine-diffable `pr_emerg` line.
4. **Two invocation sites**:
   - Pre-FORCEHT: right after T247's pre-place block, before FORCEHT write.
   - Pre-wedge: inside the existing `BCM4360_T239_POLL` macro or adjacent, gated to fire only when `strcmp(stage,"t+90000ms")==0` — or simpler, add a third arm after the existing T239/T240/T247 arms that runs only at that dwell.

### Run sequence (after build+verify)

```bash
sudo modprobe cfg80211
sudo modprobe brcmutil
sudo insmod phase5/work/drivers/.../brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

### Pre-test checklist status (updated 13:45 BST)

1. Build status: **REBUILT + VERIFIED.** md5sum `6f87f1ff91f0cc300e5fa7e13f03e80b` on `brcmfmac.ko`. `modinfo` shows new param. `strings` shows both format lines (pre-FORCEHT + t+90000ms). Only pre-existing unused-variable warnings (no new regressions). Commit: 549bc0e.
2. PCIe state: **clean.** `Mem+ BusMaster+`, MAbort-, CommClk+, LnkSta 2.5GT/s x1. UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky, consistent with prior tests).
3. Hypothesis: (W1)/(W2)/(W3) matrix stated above.
4. Plan: committed and pushed. Filesystem synced.
5. Host state: boot 0 started 12:13:29 BST, uptime ~90 min, stable. No brcm modules loaded.

### Run command (exact)

```bash
sudo modprobe cfg80211 && \
sudo modprobe brcmutil && \
sudo insmod /home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/brcmfmac.ko \
    bcm4360_test236_force_seed=1 \
    bcm4360_test238_ultra_dwells=1 \
    bcm4360_test239_poll_sharedram=1 \
    bcm4360_test240_wide_poll=1 \
    bcm4360_test247_preplace_shared=1 \
    bcm4360_test248_wide_tcm_scan=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

---

### Hardware state (current, 2026-04-23 12:1x BST, boot 0 after test.247 crash **with SMC reset**)

`lspci -s 03:00.0` (sudo): `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1. No brcm modules loaded. Boot 0 started 12:13:29 BST, uptime ~1 min at write time. Host healthy.

---

