# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 16:5x BST, POST-TEST.251 — **forward-write ring + last-line-before-hang + saved-state region all captured**. T251 t+60s probe landed at 15:55:04, last journal entry at 15:55:33 (t+90s probe burst → wedge ≤1s after, n=5 streak T247..T251). Three findings: (1) **last text line printed by fw before hang**: `"...(r) on BCM4360 r3 @ 40.0/160.0/160.0MHz\n"` at 0x9CE30..0x9CE58 — likely wlc_attach init banner showing chip rev + radio config. After "\n\0" at 0x9CE58, ring ends at STAK canary fill — **ring upper bound ≈ 0x9CE5A**. (2) **Backward-from-buf_ptr region 0x9CC94..0x9CCAC** contains a binary log record continuation (header `0x40010 / fmt=0x629C0 / 0x9af80 / 0xa / 0x185d`) — same record format as T250's wl_probe/dngl_probe records → **forward-write ring confirmed**. (3) **Saved-state region 0x9CE98..0x9CF34** (after STAK canary): 30+ u32s with repeated TCM offsets (0x93610 ×5, 0x92440 ×3, 0x91cc4 ×3) and odd-LSB fw addresses (0x12c69, 0x68321, 0x68d2f, 0x5271 — all **Thumb-mode PCs**). 0x9CEA0=0x000934C0 matches T248's 0x9CFE0 trap-region value. **0x9CF2C=0x000043B1 matches frozen "counter" at 0x9d000** → 0x43B1 may not be a counter but a saved register/token. Boot 0 started 16:50:08 BST, PCIe clean.)

### What test.250 landed (facts)

Full journal at `phase5/logs/test.250.journalctl.txt` (466 lines). Three T250 lines at t+60000ms decode as follows (all LE byte-swap-to-ASCII for text dwords):

**TCM[0x9ccb0..0x9cd2c] — 32 u32 (pre-buffer context + log head):**
```
0x9ccb0: 00040010 00000057 00062910 00000a87        [4-field binary record header]
0x9ccc0..0x9cd18: ASCII → "125888.001 Chipc: rev 43, caps 0x58680001,
                          chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11\n\n"
0x9cd1c: 0000185d                                    [= 6237 dec]
0x9cd20: 00040010 00000057 00062910 00000a87        [next record header — same 4 fields]
```
Values match host-observed: ccrev=43, pmurev=17, pmucaps=0x10a22b11 (test.193 PMU dump). Fresh fw-side observations: **chipst=0x9a4d**, **caps=0x58680001**.

**TCM[0x9cd30..0x9cdac] — 32 u32 (log mid / binary-heavy records):**
```
0x9cd30..0x9cd40: ASCII "125888.000 Chipc000\0"  [timestamp + truncated msg]
0x9cd44..0x9cd60: 8009cda6 00000000 0000000a 0009cdaf 8009cda6 0003fffc
                  0009cda8 00000000                [fw VAs (0x800..) + TCM offsets]
0x9cd64..0x9cda4: 00000713 00000003 0003ffff 0780e600 00062910 18001000
                  00058ef0 0009cdb3 000001f6 000629c0 0009af80 0000000a
                  0000185d 000001f6 0000001b 00062910 00000a87
                                                     [multi-arg printf record]
0x9cda8..0x9cdac: ASCII "1258" "88.0"             [start of next timestamp]
```
Key embedded values: **0x18001000** = chipcommon core base register (matches host-enumerated core[2] base). **0x62910, 0x629C0** = fw code offsets (likely fmt strings — both < TCM 0x6BF78 code region).

**TCM[0x9cdb0..0x9ce2c] — 32 u32 (T249 assert region + 32-byte extension):**
```
0x9cdb0..0x9cdc0: ASCII "00 wl_probe called\n\0"
0x9cdc4..0x9cdd8: ASCII "ciedngl_probe called\n\0"    [record tail "cied" + dngl_probe]
0x9cddc..0x9ce04: 00000713 00000000 0003ffff 000629c0 0009af80 0000000a
                  0000185d 0003ffff 00000051 00062910 00000a87
                                                     [multi-arg printf record]
0x9ce08..0x9ce10: ASCII "125888.0000 \n"           [timestamp + leading space]
0x9ce14..0x9ce2c: ASCII "RTE (PCIE-CDC) 6.30.223 (TOB)"  ← FIRMWARE VERSION BANNER
```

**Counter 0x9d000 = 0x000043b1 for ALL 23 dwells (t+100ms..t+90000ms).** Test.89 single-write reading replicated at n=2.

### What test.250 settled (facts)

- **Firmware identified: Broadcom BCM4360 RTE (PCIE-CDC) 6.30.223 (TOB)** — Runtime Environment, PCIe/CDC protocol, build 6.30.223 Tip-of-Branch. Matches brcmfmac4360-pcie.bin (442233 bytes). This is a well-known public Broadcom fw version (published widely as brcmfmac4360-pcie across many distributions).
- **Chipc init ran normally pre-hang.** Captured log "Chipc: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11" matches host-observed ccrev/pmurev/pmucaps exactly. Firmware saw the same chip state we did — no init-time disagreement.
- **wl_probe and dngl_probe both executed pre-hang.** Both log lines present in the ring. Fw progressed into driver-probe stage before hanging at fn 0x1FC2 (test.94).
- **Console is a log-RECORD ring, not a flat text ring.** Each record carries: binary header (~4 u32 fields likely length/type/fmt-ptr/seq), ASCII timestamp in "125888.XXX" format (unclear unit — microseconds since fw boot plausible), formatted text inline, trailing binary args. Fmt-string pointers resolve into fw code region (< 0x6BF78). This explains why T249 text started "mid-phrase" — we landed inside a record body.
- **Buf_ptr at 0x9CC5C = 0x8009ccbe → TCM 0x9CCBE** confirmed as newest-write-location. T250 gap dump 0x9CCB0..0x9CE30 connected cleanly with T249's 0x9CDB0..0x9CE0C extension — same values observed in the overlap region.
- **Counter-freeze / log-write ordering paradox.** Counter 0x9d000 froze at 0x43b1 before T+100ms (per test.89 n=2 now). Yet wl_probe/dngl_probe log lines imply fw ran further into init than a ~12ms freeze would allow. Either (a) log writes predate counter freeze entirely (all records written in the 0..12ms window), or (b) counter writes are unrelated to forward execution (some other thread stopped ticking). Timestamps "125888.XXX" in records suggest fw internal time ≫ 12ms — favors (b).
- **No ASSERT text found** in 0x9CDB0 region. Previous hypothesis (assert caused halt) falsified. Fw hangs silently, consistent with test.94's "wait-loop at fn 0x1FC2."
- **SMC reset required** (n=4 streak T247..T250).

### Next-test direction (T251 — post-advisor)

Branches to consider:
1. **Widen ring read past 0x9CE30** — the LAST line fw printed should be the next record after dngl_probe + banner. Dump 0x9CE30..0x9D000 (208 bytes / 52 u32s). That line is the strongest direct hint at the hang location.
2. **Decode 0x9cfe0 trap-struct region** — T248 showed 0x000934c0 there. If it's a populated trap struct (r5, TCM-top, PC), gives direct hang PC.
3. **Public-fw-version leverage** — 6.30.223 is public; init sequence post-dngl_probe is knowable from upstream brcmfmac's expected protocol (shared_info handshake at fn exit). This is lateral, but can suggest *what fw expects from host next* — and whether we're failing to provide it (e.g., host doesn't ACK something fw waits for).

Advisor call before design.

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

## PRE-TEST.251 (2026-04-23 15:5x BST, boot 0 after test.250 crash + SMC reset) — **console ring-end + backward-read from buf_ptr.** T250 captured log content 0x9CCB0..0x9CE30 but two questions remain: (1) where does the ring end past 0x9CE30? and (2) is buf_ptr a forward-write index (if so, content just-before 0x9CCBE is newest). T251 answers both in a single t+60s probe.

### Hypothesis

Advisor-sharpened reading of T250: timestamps "125888.XXX" × 100ns = 12.5888 ms — matches test.89 freeze at T+12ms exactly. All four timestamps cluster tight (125888.000..001..0000), consistent with a burst of log writes ending at freeze. This favors: fw ran ~12ms, flushed a batch of log records, froze. If buf_ptr at 0x9CCBE is the forward-write index, then content at 0x9CCBC and earlier is the most-recently-written text — newer than what we saw at 0x9CDB0..0x9CE30.

**Observables at 0x9CC80..0x9CCAC (backward-read, 12 u32 / 48 B):**
- If forward-write ring: this region holds the NEWEST log records — last lines fw printed before hang.
- If backward-write ring: this region is older content or canary/zeros.
- The gap between T249's struct-area end (0x9CC7C) and T250's gap-dump start (0x9CCB0) is exactly 48 bytes.

**Observables at 0x9CE30..0x9CF30 (forward-past-T250, 64 u32 / 256 B):**
- If forward-write ring: this region holds OLDER log records, possibly ring-start or a boundary/zeros.
- If backward-write ring: this region holds newer content past dngl_probe.
- 0x9CFE0 is the trap-struct region (T248 0x000934c0) — bounded above.

**Ring-layout decision**: whichever region holds "dense structured records continuing the Chipc/wl_probe/dngl_probe/banner sequence" is the NEWER end. The other is OLDER end or off-ring.

### Design

**Single probe at t+60000ms** (drops T249 console window + T250 gap window — both already captured):

| Dwell | Added probe | u32 reads | Rationale |
|---|---|---|---|
| t+60000ms | `TCM[0x9CC80..0x9CCAC]` (12 u32s = 48 B) | 12 | Backward-read from buf_ptr at 0x9CCBE — closes forward/backward ring-layout question. |
| t+60000ms | `TCM[0x9CE30..0x9CF30]` (64 u32s = 256 B) | 64 | Forward-past-T250 continuation — finds ring-end boundary (expect zeros/canary past some address ≤ 0x9CFE0). |
| every dwell (23 points) | `TCM[0x9d000]` (1 u32) | 23 total | Same per-dwell poll, now gated on T249 \|\| T250 \|\| T251. n=3 replication of test.89. |

**Log format (3 pr_emerg lines at t+60s):**

```
test.251: t+60000ms TCM[0x9cc80..0x9ccac] = 12 hex values (backward-read from buf_ptr)
test.251: t+60000ms TCM[0x9ce30..0x9ceac] = 32 hex values (forward continuation head)
test.251: t+60000ms TCM[0x9ceb0..0x9cf2c] = 32 hex values (forward continuation tail)
```

Line-length budget: 32 × 9 + prefix ~60 = ~350 chars. Backward line is ~180 chars. Well under LOG_LINE_MAX 1024.

**Runtime config**: `bcm4360_test249_console_dump=0 bcm4360_test250_console_gap=0 bcm4360_test251_console_ext=1`. Drops already-captured windows; keeps struct/widescan baselines.

### Next-step matrix

| Observation | Implication | T252 direction |
|---|---|---|
| 0x9CC80..0x9CCAC contains ASCII log records continuing Chipc/wl_probe/dngl_probe sequence | **Forward-write ring confirmed.** Backward-content is newest; LAST line fw printed sits here. | Decode last line → correlate with public fw 6.30.223 init sequence → identify hang point. |
| 0x9CC80..0x9CCAC is zeros or canary; 0x9CE30..0x9CF30 has dense records | **Backward-write (or wrapped) ring.** Content at 0x9CE30+ is newer. Look for last-line there. | Decode 0x9CE30+ tail; correlate with fw init sequence. |
| Both regions have dense records | Ring doesn't align to our hypothesized boundaries; probably a larger window. | Widen further: dump 0x9CC00..0x9D000 in a future probe. |
| 0x9CE30..0x9CF30 has zeros/canary boundary | **Ring-end found** somewhere in this window. Exact boundary narrows ring size → total log capacity → how much we've captured. | Document ring boundary; reassess remaining questions. |
| Counter 0x9d000 = 0x43b1 across all 23 dwells (n=3 replication) | Test.89 single-write confirmed at n=3. | No further action on this axis. |

### Safety

- All BAR2 reads, no register side effects.
- Total added reads: 12 + 64 at t+60s + 23 per-dwell = 99 reads. Comparable to T250.
- SMC reset expected to be required after wedge (n=5 streak T247..T251).

### Code change outline

1. New module param `bcm4360_test251_console_ext` near T250's.
2. New macro `BCM4360_T251_RING_EXT(stage_tag)` reading:
   - 12 u32s at 0x9CC80..0x9CCAC (1 pr_emerg line)
   - 64 u32s at 0x9CE30..0x9CF30 (2 pr_emerg lines × 32 u32 each)
3. Extend T239 ctr gate: `if (bcm4360_test249_console_dump || bcm4360_test250_console_gap || bcm4360_test251_console_ext)`.
4. Invocation: right after `BCM4360_T250_GAP_WINDOW("t+60000ms")` (pcie.c:3394).

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
    bcm4360_test251_console_ext=1
sleep 240
sudo rmmod brcmfmac_wcc brcmfmac brcmutil || true
```

Note: `bcm4360_test249_console_dump` and `bcm4360_test250_console_gap` are NOT set.

### Expected artifacts

- `phase5/logs/test.251.run.txt`
- `phase5/logs/test.251.journalctl.txt`

### Pre-test checklist (complete — READY TO FIRE)

1. **Build status**: **REBUILT + VERIFIED.** md5sum `2c8a4a36130b1f10a10e0314c16d2270` on `brcmfmac.ko`. `modinfo` shows new param `bcm4360_test251_console_ext`. `strings` confirms all 3 T251 format lines (12-u32 backward + 2 × 32-u32 forward). Only pre-existing unused-variable warnings (no new regressions).
2. **PCIe state**: **clean.** `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1, UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky). Re-verified 15:49 BST.
3. **Hypothesis**: stated — backward-read closes ring-layout question; forward-past-T250 finds ring boundary.
4. **Plan**: this block + code change to be committed and pushed before insmod.
5. **Host state**: boot 0 started 15:37:02 BST, uptime ~12 min at plan time, stable. No brcm modules loaded.

---

## POST-TEST.251 (2026-04-23 16:5x BST — boot 0 after test.251 crash + SMC reset)

Boot -1 timeline: insmod 15:53:40 → t+60s probe 15:55:04 (success) → t+90s probe 15:55:33 (success, last journal entry) → wedge → boot ended 15:55:33. Wedge ≤1s after t+90s probe burst — consistent with n=5 streak T247..T251. Full journal at `phase5/logs/test.251.journalctl.txt` (1528 lines kept).

### What test.251 landed (facts)

**Backward-read TCM[0x9CC80..0x9CCAC] — 12 u32 (just above buf_ptr@0x9CCBE):**
```
0x9cc80: 0009cd0e 0009cec0 000475b5 0009cef0   [4-field struct: TCM/TCM/Thumb-PC/TCM]
0x9cc90: 00000000 00000713 00000000 00040010   [pad + record-tail args + record header]
0x9cca0: 000629c0 0009af80 0000000a 0000185d   [fmt-ptr, arg, arg, line# 6237]
```
- 0x9CC80..0x9CC8C looks like a **second console-state struct** (4 fields):
  - 0x0009CD0E (TCM offset, ring interior)
  - 0x0009CEC0 (TCM offset — points 9 bytes into "BCM4360 r3" text region!)
  - 0x000475B5 (Thumb-mode fw code addr — last printf caller PC?)
  - 0x0009CEF0 (TCM offset — points into the saved-state region we just discovered)
- 0x9CC9C..0x9CCAC: **binary log record header in same format as T250's wl_probe/dngl_probe records** (0x40010 type word, 0x629C0 fmt-ptr, 0x185D line#) → **forward-write ring layout confirmed** — backward content is freshest log records.

**Forward-read TCM[0x9CE30..0x9CE58] — ASCII (continuation past T250's banner):**
```
0x9ce30: " (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz\n\0"
0x9ce58..0x9ce80: STAK STAK STAK STAK STAK STAK STAK STAK   [stack canary fill]
```
**Last printed line**: `"...(r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"` — likely full form: "wlc_attach: BCM4360 802.11n (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz" (a wlc_attach init banner showing chip rev a3 + bandwidth config). Ring upper bound ≈ 0x9CE5A.

**Forward-read TCM[0x9CE84..0x9CF34] — saved-state region (30+ u32 after STAK canary):**
```
0x9ce84: 00000004 5354414b 00000000 00000000        [tail of canary + zeros]
0x9ce94: 00093610 00000030 0009cf44 000934c0        [TCM, 48, TCM-self, T248-trap-val]
0x9cea4: 00091c04 00000000 00012c69 0009cf44 00000000   [TCM, 0, Thumb-PC, TCM-self, 0]
0x9ceb8: 00093610 00092440 00091cc4 00068d2f 00000000   [TCM ×3, Thumb-PC, 0]
0x9cecc: 00091cc4 00091cc4 00092440 00000000 00068321   [TCM ×3, 0, Thumb-PC]
0x9cee0: 0009cf1c 0009f08a 0000000a 00005271 00000000   [TCM, TCM-elsewhere, 10, Thumb-PC, 0]
0x9cef4: 000927bc 0000003c 00000004 00000000 0009238c   [TCM, 60, 4, 0, TCM]
0x9cf08: 00000000 00093610 000000c4 00000004 00093610   [0, TCM, 196, 4, TCM]
0x9cf1c: 00092440 00000000 00093610 00000028 000043b1   [TCM, 0, TCM, 40, FROZEN-CTR-MATCH]
0x9cf30: 00093610 00091e54                              [TCM, TCM]
```
**Repeated TCM offsets**: 0x00093610 (×5), 0x00092440 (×3), 0x00091CC4 (×3). All in TCM data region.
**Thumb-mode fw code PCs (LSB=1)**: 0x000475B5 (in console struct), 0x00012C69, 0x00068D2F, 0x00068321, 0x00005271. All within fw code region (< 0x6BF78).
**Cross-references found:**
- 0x9CEA0 = 0x000934C0 — exact match to T248's 0x9CFE0 trap-region value.
- 0x9CF2C = 0x000043B1 — exact match to frozen "counter" at 0x9D000.

### What test.251 settled (facts)

- **Forward-write ring layout confirmed.** Backward-from-buf_ptr region holds freshest log records (binary header in same format as T250). Ring boundary ≈ 0x9CE5A (where "\n\0" transitions to STAK canary fill).
- **Last text line fw printed before hang identified**: the wlc_attach init banner with BCM4360 r3 silicon + 40.0/160.0/160.0MHz radio config. This is normal wireless-driver init progress — fw has done substantial chip/radio bring-up before hanging.
- **Saved-state / trap-record region exists at 0x9CE98..0x9CF34+** (after stack canary, before T248's 0x9CFE0 marker). Multiple Thumb-mode fw PCs and repeated data-region TCM offsets suggest a structured record (call frame, task table, or trap dump). 0x934C0 also appears here, cross-referenced from T248.
- **0x000043B1 reframe**: appears at both 0x9D000 (the "frozen counter") and 0x9CF2C (the saved-state region). Strongly suggests 0x43B1 is **not a counter** — it's a register save value or token written multiple times by fw (perhaps a task ID, a register snapshot, or a fixed sentinel). Test.89 "single-write" reading was correct in mechanism (one write, then frozen) but wrong in interpretation (it's saved state, not a tick counter).
- **Ring size estimate**: from STAK-end (~0x9CC9F-ish — but we saw the ring runs from at least 0x9CC94 backwards — ring start unknown) to 0x9CE5A → minimum ring length ≈ 0x1C0 = 448 bytes. Could be larger (we haven't dumped before 0x9CC80).
- **SMC reset required** (n=5 streak T247..T251).
- **Counter 0x9d000 = 0x43b1 across all 23 dwells (n=3 replication)** — test.89 single-write confirmed at n=3.

### Next-test direction (T252 — pending advisor consultation)

Branches:
1. **Decode saved-state region as a possible trap/exception record.** The Thumb-mode PCs (0x12C69, 0x68D2F, 0x68321, 0x5271) are the strongest direct hint at hang location. If fw kept a call stack snapshot, disassembling these PCs in the public 6.30.223 fw blob (clean-room: observe → document) could identify the hung function.
2. **Read fw data at the repeated TCM offsets (0x93610, 0x92440, 0x91CC4)** — these may be active task descriptors or globals fw is waiting on.
3. **Look at fmt-string at fw 0x629C0 and 0x62910** to identify the printf templates that produced the record headers (would tell us *which printf* was last fired before hang).
4. **Walk the ring backwards further** (TCM[0x9C800..0x9CC80] = 256 u32) to find ring start + record sequence leading up to wlc_attach banner.

Advisor call before design.

---

### Hardware state (current, 2026-04-23 16:50+ BST, boot 0 after test.251 crash **with SMC reset**)

`sudo lspci -s 03:00.0`: `Mem+ BusMaster+`, MAbort-, DEVSEL=fast, LnkSta 2.5GT/s x1, UESta all zero, CESta AdvNonFatalErr+ (pre-existing sticky). No brcm modules loaded. Boot 0 started 16:50:08 BST. Host healthy.

---
