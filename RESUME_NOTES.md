# BCM4360 RE — Resume Notes (auto-updated before each test)

> **Session-pickup guide.** Read the summary below, then the latest 2–3 test
> entries. Older tests → [RESUME_NOTES_HISTORY.md](RESUME_NOTES_HISTORY.md).
> **Policy:** when a new POST-TEST is recorded here, migrate the oldest
> PRE/POST pair down to HISTORY so this file holds at most ~3 tests.

## Current state (2026-04-23 17:2x BST, POST-TEST.252 — **three saved-state-referenced structs captured and decoded**. T252 fired at 17:17:37 (t+60s, all 3 probes captured); wedge ≤1s after t+90s T248 probe at 17:18:08 (n=6 streak T247..T252). Boot 0 started 17:28:11 BST, PCIe clean, no brcm loaded. Key findings: (1) **0x58EF0 (in 0x93610 struct) is the ASCII string `"wl"`**, NOT a function pointer — 0x93610 is likely a wl_info / WL driver-context structure. (2) **0x92440 is a runtime-populated silicon-backplane descriptor (si_info)** containing ChipCommon core base 0x18001000 (zero blob refs → fw-cached at runtime). Two adjacent embedded list_head pairs at 0x92460. (3) **0x91CC4 is a subordinate struct with back-refs to 0x92440 AND 0x93610** — three structs form an inter-linked family. (4) **0x934C0 is a central shared object** — referenced in all three structs AND in T248's 0x9CFE0 AND in T251's saved-state 0x9CEA0. Combined with T251 blob analysis (LR 0x68320 in wlc_bmac_attach; LR 0x68D2E in wlc_attach; chiprev banner never fires): hang is **somewhere in the wlc_attach → wlc_bmac_attach call tree, before the chiprev banner fires**. Narrower "inside wlc_phy_attach" reading remains **unverified** — T251 saved PCs don't form a clean caller→callee chain. T252 didn't add stack evidence; it only decoded struct contents.)

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
- **Ring upper bound (HYPOTHESIS, not settled)**: ~0x9CE5A based on text→STAK transition. The "\n\0" at 0x9CE58 followed by STAK canary fill is suggestive but not definitive — a sparsely-populated ring could extend further before STAK fill. Treat as working hypothesis; advisor flagged this.
- **Ring size estimate**: from STAK-end (~0x9CC9F-ish — but we saw the ring runs from at least 0x9CC94 backwards — ring start unknown) to ~0x9CE5A → minimum ring length ≈ 0x1C0 = 448 bytes. Could be larger.
- **SMC reset required** (n=5 streak T247..T251).
- **Counter 0x9d000 = 0x43b1 across all 23 dwells (n=3 replication)** — test.89 single-write confirmed at n=3.

### Next-test direction (T252 — advisor-confirmed)

**Local blob analysis already completed** (see `phase5/analysis/T251_blob_analysis.md`). Key findings:

- Blob → TCM mapping verified (blob byte N = TCM offset N for N < 0x6BF78).
- Last-printed fmt = wlc_attach RTE banner at blob[0x6BAE4], call site blob[0x6454C].
- Next-fmt-fw-would-have-printed = WL controller banner at blob[0x6BB1D], call site blob[0x678BC] — **never seen** → fw stuck before wlc_attach returns.
- Saved PCs verified by Thumb-2 BL preceding-byte signature (4 of 5 are real return addresses; 0x475B5 is a fmt-string pointer with tag bit, not a PC).
- 0x68D2E falls in/near wlc_attach (literal pool nearby has 'wlc_attach', 'wlc_attach: failed with err %d').
- 0x68320 falls in/near wlc_bmac_attach (literal pool nearby has 'wlc_bmac_attach', 'wlc_phy_attach failed', chiprev banner with phy_type/phy_rev args).
- The chiprev banner is the LAST line wlc_bmac_attach prints (after wlc_phy_attach returns). Never seen → **hang is in wlc_attach → wlc_bmac_attach call tree, before chiprev banner fires**. Stack-frame ordering not confirmed (saved-state region may be a context save / TCB rather than a clean stack).

**T252 probes the BSS data referenced by the saved-state region.** This is the only remaining axis local blob analysis can't reach.

---

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
