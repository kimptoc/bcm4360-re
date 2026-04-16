# BCM4360 RE — Resume Notes (auto-updated before each test)

## Current state (2026-04-16, ABOUT TO RUN test.96 — module built, not yet run)

Git branch: main (pushed to origin)
Module built successfully. About to run test.96.
Test.96 dumps (at T+200ms, outer==1):
  CODE: TCM[0x5200-0x5400] = 128 words — covers fn 0x5250 (called by 0x2208 before b.w 0x848)
  Per-100-word re-masking. Total 128 words — well within safe limit (1.9s total).
Key question: does 0x5250 contain a hardware register polling loop that causes the hang?

## test.94 RESULT: SURVIVED (vtable read), CRASHED in STACK-LOW at word 154

**test.94 ran in boot -1. Module survived vtable dump, crashed at word 154/192 of STACK-LOW.**
**VTABLE: VT[0x58cf4] = 0x1FC3 → hang function is at 0x1FC2 (Thumb). CONFIRMED.**

**Key findings from VTABLE dump (0x58CD0-0x58D40):**
- VT[0x58cd4] = 0x00058c9c (nested vtable/struct ptr)
- VT[0x58cd8] = 0x00004999 (function at 0x4998)
- VT[0x58cdc] = 0x0009664c (BSS data ptr)
- **VT[0x58cf4] = 0x00001FC3** → Call 1 function (blx r3 at 0x644dc) = 0x1FC2 (Thumb) ← HANG CANDIDATE
- VT[0x58cf8] = 0x00001FB5 → vtable[+8] fn at 0x1FB4
- VT[0x58cfc] = 0x00001F79 → vtable[+12] fn at 0x1F78
- VT[0x58d24] = 0x00000001, VT[0x58d28..0x58d3c] = small fn pointers (0x4167C-0x416E3)

**Disassembly of 0x1FC2 (from arm-none-eabi-objdump on test.87 bytes):**
```
1fc2:  mov  r2, r1
1fc4:  ldr  r1, [r0, #24]  ; r1 = obj->si_ptr (field+0x18)
1fc6:  mov  r3, r0          ; r3 = obj
1fc8:  ldr  r0, [r1, #20]  ; r0 = si_ptr->dev (field+0x14)
1fca:  mov  r1, r3          ; r1 = obj (restore)
1fcc:  b.w  0x2208          ; TAIL CALL → 0x2208
```
→ 0x1FC2 is a TRAMPOLINE, not the actual hang. Rearranges args and tail calls to 0x2208.

**0x1FB4 (vtable[+8]):** identical trampoline → b.w 0x235C
**0x1F78 (vtable[+12]):** real function, calls 0x2E70 and 0x7DC4

**Analysis of 0x2208 (the REAL init function):**
```
push.w {r0,r1,r4,r5,r6,r7,r8,lr}   ; 8 regs = 32 bytes stack frame
r7 = *0x232C = 0x00062A14           ; global state ptr
r4=arg0(obj), r6=arg1, r5=arg2
r3 = *0x62A14 = 0x58CF0             ; vtable/state ptr (from test.93)
if (r3 & 2): optional debug print
if r6==0 || r5==0: error path
...
r8 = 0
bl 0x1FD0           ; allocate 76-byte struct (malloc via 0x7D60)
obj->field12 = result
if (alloc failed): error path
r0 = *0x62A14 & 0x10                ; 0x58CF0 & 0x10 = 0x10 (SET!)
if bit4 NOT set: return early (0x231C)
r1 = *0x2350 (timer priority value)
r0 = 0
bl 0x5250           ; register timer/callback
if (r0 == 0): success path:
    r0 = *0x237c = 0x00000000 (NULL!)
    r6 = 0
    b.w 0x848       ; TAIL CALL → 0x848 = strcmp (C library, NOT hang — CONFIRMED test.95)
```

**0x1FD0 (struct constructor called by 0x2208):**
- mallocs 76 bytes via 0x7D60
- memsets to 0 via 0x91C
- field52 = 0x740 = 1856, field60 = 0x3E8 = 1000, field64 = 28, field68 = 12, field72 = 4
- These look like timer/retry parameters (period_ms, timeout_ms, max_retry)

**STACK-LOW findings (0x9C400-0x9CDFC, crashed at 0x9CDFC):**
- 0x9C400-0x9CC54: ALL STAK fill (0x5354414b) — 0x1454 bytes = 5.2KB unused
- 0x9CC58-0x9CDFC: console ring buffer + BSS data (NOT stack frames)
  - 0x9CC5C = console write ptr (0x8009CCBE)
  - 0x9CCC0-0x9CDD8 = decoded console strings
  - 0x9CC88 = 0x000475B5 (ODD → Thumb fn ptr at 0x475B4 in struct)
- Stack frames NOT yet read (need 0x9CE00-0x9D000 or higher)
- Crash at ~3.25s total (exceeding ~3s PCIe crash window)

## test.95 RESULT: CLEAN EXIT — 0x840-0xB40 ALL C RUNTIME LIBRARY

**test.95 ran in boot -2 (and boot -1). Both SURVIVED with "TIMEOUT — FW silent for 2s — clean exit".**
**CODE DUMP COMPLETE: 192 words at 0x840-0xB40 disassembled (test95_disasm.txt).**

**CRITICAL CORRECTION: 0x848 is NOT a hang site — it is the loop body of strcmp.**
The annotation "b.w 0x848 = likely actual hang location" was WRONG.

**Functions found in 0x840-0xB40:**
- 0x840-0x87a: `strcmp` — entry at 0x840 (b.n 0x848), loop at 0x842-0x856, exit at 0x858-0x87a
- 0x87c-0x916: `strtol`/`strtoul` — whitespace skip, sign handling, 0x prefix, base conversion
- 0x91c-0x968: `memset` — 4-byte aligned stores + byte tail
- 0x96a-0xa2e: `memcpy` — LDMIA/STMIA 32-byte blocks, `tbb` jump table
- 0xa30-0xaaa: console printf — 520-byte stack buffer, calls 0xfd8/0x7c8/0x5ac/0x1848
- 0xabc-0xafa: callback dispatcher — 5-entry loop, `blx r3` dispatch with flag masking
- 0xb04-0xb16: wrapper loading globals for 0xabc
- 0xb18-0xb3f: heap free — adjusts accounting, walks linked list

**0xa4c was wrongly annotated** — it is in the MIDDLE of console printf at 0xa30, not a cleanup fn.

**Call chain from 0x2208:**
  bl 0x5250 (timer/callback reg) → succeeds → b.w 0x848 (tail call into strcmp)
  strcmp completes in microseconds. HANG IS ELSEWHERE.

**si_attach disasm (test91_disasm.txt, 0x64400-0x64ab8):**
- Function at 0x644??-0x64536: contains 3 vtable dispatches
  - Call 1 (0x644dc): *(*(0x62a14)+4) — obj vtable ptr at offset 0 → vtable[1]
  - Call 2 (0x644fc): r6=0x58cc4, ldr r3,[r6,#16] → vtable ptr at obj+16 → vtable[1]  
  - Call 3 (0x6451a): r7=0x58ef0, ldr r3,[r7,#16] → vtable ptr at obj+16 → vtable[1]
- si_attach at 0x64590: EROM-parsing loop, calls 0x2704 (EROM parser) for each core

## test.96 PLAN: Disassemble fn 0x5250 (timer/callback registration)

**Goal:** Determine if fn 0x5250 (called by 0x2208) contains hardware polling that causes the hang.

**Approach:**
1. Keep all proven init (BBPLL, BusMaster, ASPM, masking)
2. Release ARM
3. At outer==1 (T+200ms): dump TCM[0x5200-0x5400] = 128 words
   - Covers fn 0x5250 (called by 0x2208 before the benign b.w 0x848/strcmp)
   - Per-100-word re-masking
4. 2s outer timeout, re-mask every 10ms (inner loop unchanged)

**Expected outcomes:**
- If 0x5250 contains LDR+CMP+BNE polling loops → IT IS THE HANG
- If 0x5250 is a simple RTOS timer registration → hang is in vtable Call 2 or Call 3
- Look for: reads from hardware-mapped addresses, wait-for-bit loops, CPSID/WFI

**Total timing:** T+200ms + 128 words × ~13ms = T+200ms + 1.7s = T+1.9s (SAFE, < 3s window)

## Run test.96 (module already built):
  cd /home/kimptoc/bcm4360-re/phase5/work && sudo ./test-staged-reset.sh 0

## After test — what to do:
1. Check which boot: `for b in -5 -4 -3 -2 -1 0; do echo "=== $b ==="; sudo journalctl -b $b -k 2>/dev/null | grep "BCM4360 test.96" | wc -l; done`
2. Save journal: `sudo bash -c 'journalctl -b -1 -k > /home/kimptoc/bcm4360-re/phase5/logs/test.96.journal && chown kimptoc:users /home/kimptoc/bcm4360-re/phase5/logs/test.96.*'`
3. Key things to check:
   a. SURVIVED? (RP settings restored = yes)
   b. Extract code dump: `grep "BCM4360 test.96 code:" test.96.journal`
   c. Disassemble: python3 extract hex → arm-none-eabi-objdump --adjust-vma=0x5200 -M force-thumb
   d. Look for: LDR+CMP+BNE loops, reads from BAR0-mapped addresses, hardware spin-waits

## test.93 RESULT: SURVIVED (both runs) — vtable pointer decoded, stack top is NVRAM

**test.93 ran twice (boot -2 at 12:02, boot -1 at 12:10), BOTH SURVIVED.**
Both showed "TIMEOUT — FW silent for 2s — clean exit" and "RP settings restored".

**Key findings from D2 (DATA-62A14) dump:**
- D2[0x62a14] = 0x00058cf0 → vtable pointer for Call 1 (blx r3 at 0x644dc)
- Vtable is at TCM[0x58cf0]; entry [+4] = TCM[0x58cf4] = function pointer for Call 1
- D2[0x62994] = 0x18000000 (ChipCommon base — confirms si_t struct location)
- D2[0x62ab0] = 0x58680001 (chipcaps — matches si_t from console output)
- D2[0x62ad4] = 0x00004360 (chip_id = BCM4360 ✓)
- D2[0x62ad8] = 0x00000003 (chip_rev = 3 ✓)
- D2[0x62ae0] = 0x00009a4d (chipst ✓)

**Key findings from SK (STACK-TOP) dump [0x9F800-0xA000]:**
- 0x9FF1C–0xA0000: NVRAM data ("sromrev=11\0boardtype=0x0552\0boardrev=0x1101\0...")
- 0x9F800–0x9FF1B: random/uninitialized data — NO Thumb LR values in TCM code range
- CONCLUSION: 0x9F800–0xA000 is NOT active stack. Active frames are near STAK fill at 0x9C400.

**What remains unknown:**
- TCM[0x58cf4] = ??? (the actual function being called — not yet read)
- Stack LR values (to confirm call depth and which vtable call hangs)

Log: phase5/logs/test.93.journal

## test.92 RESULT: SURVIVED — STAK fill confirmed above 0x9BC00; EROM parser analyzed

**test.92 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**Stack dump 0x9BC00-0x9C400: ENTIRELY STAK (0x5354414b)**
- Active stack frames are ABOVE 0x9C400
- Stack grows down from 0xA0000; estimated SP ~0x9F800
  (860-byte zeroed struct in 0x670d8 frame + si_attach 60-byte frame + others)

**EROM parser function at 0x2704 (0x2600-0x2900 dumped):**
- Simple loop: loads EROM entries sequentially from TCM, returns when match found
- r1 = &ptr, r2 = mask (or 0), r3 = match value
- NO infinite loops, NO hardware register reads
- CANNOT be the hang location

**Function structure at 0x27ec (core registration, vtable call):**
- `blx r3` at 0x2816 calls a vtable function (potential hang candidate)
- But this is called by si_attach (0x64590) during core enumeration

**Key insight: Vtable calls are in a function BEFORE si_attach in TCM:**
- From test.91 dump (0x64400-0x6458c area):
  - `bl 0x63b38` with r1=0x83c → looks up PCIe2 core object → r6
  - `bl 0x63b38` with r1=0x812 → looks up D11/MAC core object → r7
  - If both found: three vtable calls follow:
    - Call 1 (0x644dc): via [0x62a14][4], args=(PCIe2_obj, D11_obj)
    - Call 2 (0x644fc): PCIe2_obj->vtable[1](), if Call 1 succeeds
    - Call 3 (0x6451a): D11_obj->vtable[1](), if Call 2 succeeds

**test.92 hypothesis: hang is in one of the three vtable calls (PCIe2 or D11 core init)**

Log: phase5/logs/test.92.journal
EROM disasm: phase5/analysis/test92_erom_disasm.txt

## test.90 RESULT: SURVIVED — 0x670d8 disassembled; 0x64590 is next hang candidate

**test.90 ran in boot -1 (survived, TIMEOUT clean exit). Key findings:**

**function 0x670d8 fully disassembled (1344 bytes, 0x66e00-0x67340):**
- Entry: `stmdb sp!, {r0-r9, sl, lr}` (pushes 12 registers)
- Loads 7 args (3 from regs r0/r1/r2/r3, 4 from stack [sp+48..+56])
- memset: zeroes 860 bytes (0x35c) from r4 (the init struct)
- Stores initial values into struct offsets
- Calls 0x66ef4 (tiny function: returns 1 always) — never hangs
- At 0x67156: `mov.w r9, #0x18000000` (ChipCommon base!)
- At 0x6715c: `ldr.w r1, [r9]` = reads ChipCommon chip_id register
- Extracts chip_id, numcores, etc. from register
- **At 0x67190: `bl 0x64590` — FIRST DEEP CALL, likely hang point**
  - Args: r0=struct_ptr, r1=0x18000000 (ChipCommon), r2=r7
  - This is likely `si_attach` or `si_create` (silicon backplane init)
- After return: checks [struct+0xd0] — if NULL, error exit
- If non-NULL: calls 0x66fc4 (function in our dump, enumerates cores)
  - 0x66fc4 loops through [struct+0xd0] cores calling 0x99ac, 0x9964
  - Returns 1 (success) after loop

**call chain established:**
- pciedngl_probe → 0x67358 → 0x672e4 (wrapper) → 0x670d8 → 0x64590

**0x64590 not in dump (below 0x66e00) — MUST DUMP NEXT**
**0x66fc4 analyzed: core-enumeration loop, returns 1 on success**

Disassembly: phase5/analysis/test90_disassembly.txt
Log: phase5/logs/test.90.journal

## test.89 RESULT: SURVIVED — 0x43b1 is STATIC constant (stored once, not incremented)

**test.89 ran in boot -1. Key findings from fast-sampling:**
1. T+0ms: ctr=0x00000000 (ARM just released)
2. T+2ms: ctr=0x00058c8c (CHANGED — firmware running, some intermediate value)
3. T+10ms: ctr=0x00058c8c (held for 8ms)
4. T+12ms: ctr=0x000043b1 AND cons=0x8009ccbe (BOTH changed simultaneously)
5. T+20ms+: ctr=0x000043b1 FROZEN, cons frozen, sharedram=0xffc70038 NEVER changes

**RESOLVED: 0x43b1 IS a static constant, NOT a counter**
- Function at 0x673cc returns MOVW R0, #0x43b1 → firmware stores it to 0x9d000
- Previous "WFI-disproof" based on frozen counter was INVALID for values at T+200ms
- BUT firmware IS genuinely hung: sharedram NEVER changes (even at 2s+)
  - PCI-CDC firmware WOULD write sharedram on successful init
  - Never changing = TRUE HANG, not WFI idle

**TIMELINE reconstructed:**
- T+0ms: ARM released, TCM[0x9d000]=0
- T+2ms: firmware stored 0x58c8c to 0x9d000 (some intermediate init value)
- T+10ms: still 0x58c8c (firmware executing init code)
- T+12ms: firmware stored 0x43b1 to 0x9d000 (function 0x673cc result) AND initialized console
- T+12ms+: EVERYTHING FROZEN — firmware hung at this exact point
  - Console write ptr = 0x8009ccbe = TCM[0x9ccbe] (same as all previous tests)
  - Last message = "pciedngl_probe called" (same as test.78-80 decode)
  - Hang occurs inside pciedngl_probe → 0x67358 (TARGET 1) → 0x670d8 (deep init)

**NEXT: disassemble 0x670d8** — the only unexamined function in the call chain
Log: phase5/logs/test.89.journal

## test.91 RESULT: CRASHED at word 431 — partial si_attach disassembly obtained

**Crash cause:** Unmasked 1280-word code dump loop; at ~7ms/word, 431 × 7ms ≈ 3s hit PCIe crash window.

**Partial disassembly (431 words, 0x64400-0x64ab8) — key findings:**
- **0x64590 (si_attach):** reads ChipCommon+0xfc = EROM pointer register
- Immediately branches to EROM parse loop, calls fn at **0x2704** (EROM entry reader)
- **Vtable dispatch calls at 0x644dc and 0x644fc** (`blx r3`) — these init individual backplane cores
  → Most likely hang points: one core's init fn reads backplane registers for a powered-off core

**Stack location corrected:** STAK marker at 0x9BF00 (from test.88) → active frames near 0x9BC00.

Log: phase5/logs/test.91.journal
Dump: phase5/analysis/test91_dump.txt (431 words: 0x64400-0x64ab8)

## test.88 RESULT: CRASHED cleanup — but all data obtained

**test.88 ran in boot -1 (also partial in boot -2). Key findings:**
1. All three call targets disassembled — NO infinite loops, CPSID, or WFI in any
2. TARGET 1 (0x67358): alloc + calls 0x670d8 (deep init) — most likely hang location
3. TARGET 2 (0x64248): struct allocator (0x4c bytes), returns — clean
4. TARGET 3 (0x63C24): registration function, returns 0 — clean
5. **CRITICAL: Function at 0x673cc returns constant 0x43b1** — same value as "frozen counter"
6. Stack scan 0x9F000-0x9FFF8: mostly zeros, no dense return address cluster
7. "STAK" marker at 0x9bf00 — stack region may be near 0x9c000
8. Counter: T+200ms=0x43b1 (RUNNING), T+400ms=FROZEN
9. CRASHED during cleanup (no RP restore messages)

Full disassembly: phase5/analysis/test88_disassembly.txt

## Key confirmed findings
- BCM4360 ARM requires BBPLL (max_res_mask raised to 0xFFFFF) ✓
- BAR2 reads (brcmf_pcie_read_ram32) are SAFE with masking ✓
- Masking (RP CMD+BC+DevCtl+AER + 10ms RW1C-clear) defeats all 3s periodic events ✓
- BusMaster must be enabled BEFORE ARM release ✓
- Per-read re-mask+msleep(10) in TIMEOUT path is safe ✓
- No IOMMU/DMA faults during firmware operation ✓
- SBMBX alone does NOT trigger pcie_shared write ✓ (test.73)
- H2D_MAILBOX_0 via BAR0 = RING DOORBELL → writing during init CRASHES ✗ (test.71/74)
- Firmware prints: RTE banner + wl_probe + pcie_dngl_probe ✓
- Firmware FREEZES in pcidongle_probe (no exception, no trap) ✓ (test.75-80)
- Firmware protocol = PCI-CDC (NOT MSGBUF) ✓ — even after solving hang, MSGBUF won't work
- ASPM disable on EP does NOT fix pcidongle_probe hang ✗ (test.76)
- Stale H2D0/H2D1=0xffffffff cleared to 0 does NOT fix hang ✗ (test.77)
- PCIe2 BAC dump: 0x120/0x124 = CONFIGADDR/CONFIGDATA, NOT DMA ✓ (test.78 corrected)
- PCIe2 core rev=1 ✓ (test.79)
- Clearing 0x100-0x108, 0x1E0 does NOT fix hang ✗ (test.79)
- select_core after firmware starts → CRASH ✗ (test.66/76 PCIe2, test.86 ARM CR4)
- Core switching after FW start CONFIRMED LETHAL across ALL core types ✗ (test.66/76/86)
- WFI theory DEAD: frozen counter = TRUE HANG, not WFI idle (WFI keeps timers running) ✗
  UPDATE: counter at 0x9d000 is STATIC value (not a counter) — set once to 0x43b1
  BUT: sharedram NEVER changes = firmware NEVER completes init = GENUINE HANG ✓
- PCIe2 wrapper pre-ARM: IOCTL=0x1 RESET_CTL=0x0 (safe to read/write pre-ARM) ✓
- Counter freezes at 0x43b1 between T+200ms and T+400ms — hang is VERY early ✓ (test.87)
- TCM top = 0xA0000 (640KB), stack grows down from there ✓ (test.87 TCB)
- pciedngl_probe calls into 0x67358, 0x64248, 0x63C24 — hang is inside one of these ✓ (test.87 disasm)
- All 3 call targets have NO infinite loops, CPSID, or WFI ✓ (test.88 disasm)
- TARGET 1 (0x67358) calls 0x670d8 (deep init) — most likely hang location ✓ (test.88)
- 0x670d8 calls si_attach (0x64590) which dispatches vtable calls ✓ (test.90)
- si_attach vtable fn at 0x1FC2 = TRAMPOLINE → tail calls 0x2208 ✓ (test.94 disasm)
- 0x2208 allocates struct, calls 0x5250, then tail calls 0x848 ✓ (test.94 disasm)
- 0x848 = NEXT UNKNOWN — likely the actual hang location ← PENDING test.95

## Console text decoded (test.78/79/80/82/83/84 T+3s)
Ring buffer at 0x9ccc7, write ptr 0x9ccbe (wrapped):
- "125888.000 Chipcommon: rev 43, caps 0x58680001, chipst 0x9a4d pmurev 17, pmucaps 0x10a22b11"
- "125888.000 wl_probe called"
- "pciedngl_probe called"
- "125888.000 RTE (PCI-CDC) 6.30.223 (TOB) (r) on BCM4360 r3 @ 40.0/160.0/160.0MHz"
Firmware prints CDC protocol banner (not FullDongle MSGBUF).

## BSS data decoded (from test.75-80 T+3s/T+5s dump)
- 0x9d000 = 0x000043b1 (static value, set once at T+12ms then firmware freezes)
- 0x9d060..0x9d080: si_t structure with "4360" chip ID
- 0x9d084/0x9d088 = 0xbbadbadd (RTE heap uninitialized = heap never allocated there)
- 0x9d0a4+ = static firmware binary data (NOT olmsg magic)

## Key files
- Source: phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c
- Test script: phase5/work/test-staged-reset.sh
- Logs: phase5/logs/test.95.journal (after test)
- Build: KDIR=/nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build && make -C "$KDIR" M=/home/kimptoc/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac modules

## Test history summary (recent)
- test.85: CRASHED T+18-20s — STATUS/DevSta cleared, firmware STILL hung; STATUS theory DEAD
- test.86: CRASHED T+2s — ARM core switch (select_core) crashed immediately; core switch LETHAL
- test.87: SURVIVED — counter froze T+200-400ms at 0x43b1; pciedngl_probe disassembled; code dumps obtained
- test.88: CRASHED cleanup — all 3 targets disassembled; NO loops/CPSID/WFI; 0x673cc returns 0x43b1 constant; 0x670d8 is next suspect
- test.89: SURVIVED — 0x43b1 is STATIC (stored once at T+12ms); WFI-disproof RESOLVED; sharedram confirms TRUE HANG
- test.90: SURVIVED — 0x670d8 fully disassembled; calls si_attach (0x64590) at 0x67190; NO loops
- test.91: CRASHED at word 431 — partial si_attach (0x64590) dump; vtable dispatch at 0x644dc
- test.92: SURVIVED — STAK extends 0x9BC00-0x9C400; EROM parser at 0x2704 is benign
- test.93: SURVIVED (×2) — D2[0x62a14]=0x58CF0 (vtable ptr); sk[0x9F800]=NVRAM (not stack)
- test.94: SURVIVED vtable, CRASHED STACK-LOW at ~3.25s — VT[0x58cf4]=0x1FC3; 0x1FC2→0x2208→0x848
- test.95: PENDING — code dump 0x840-0xB40 to find hang in 0x848 or 0xa4c
