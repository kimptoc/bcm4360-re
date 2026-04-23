# Upstream brcmfmac Shared Struct Field Map

**Source:** `/home/user/bcm4360-re/phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c` (GPL upstream brcmfmac driver, instrumented)

---

## Struct Layout: brcmf_pcie_shared_info

Host-side struct definition at **pcie.c:492-511**. Firmware expects a memory image at the TCM address published by firmware via **TCM[ramsize-4]**, read by host after firmware completes boot.

### Field-by-Field Breakdown

| Offset | Field | Width | Type | Direction | Validity Timing | Notes |
|--------|-------|-------|------|-----------|-----------------|-------|
| 0 | flags | u32 | LE | FW→Host | Immediately after FW writes sharedram addr | Encodes version (bits 0-7), DMA_INDEX (0x10000), DMA_2B_IDX (0x100000), HOSTRDY_DB1 (0x10000000) [pcie.c:411-414] |
| 4 | (unknown/reserved) | u32 | LE | ? | After FW publication | Test.247 observed no changes across 23 dwells |
| 8 | (unknown/reserved) | u32 | LE | ? | After FW publication | Test.247 observed no changes |
| 12 | (unknown/reserved) | u32 | LE | ? | After FW publication | Test.247 observed no changes |
| 16 | (unknown/reserved) | u32 | LE | ? | After FW publication | Test.247 observed no changes |
| 20 | console_addr | u32 | LE | FW→Host | After FW publishes sharedram | Firmware writes console struct base address (TCM offset); host reads at sharedram+20 [pcie.c:1345-1346] |
| 24-32 | (unknown/reserved) | u32[2] | LE | ? | After FW publication | Test.247 observed no changes |
| 34 | max_rxbufpost | u16 | LE | FW→Host | After FW publishes sharedram | Max RX buffers to pre-post [pcie.c:2149]; host defaults to BRCMF_DEF_MAX_RXBUFPOST if 0 [pcie.c:2150-2151] |
| 36 | rx_dataoffset | u32 | LE | FW→Host | After FW publishes sharedram | Offset from start of RX buffer to actual frame data [pcie.c:2154] |
| 40 | htod_mb_data_addr | u32 | LE | FW→Host | After FW publishes sharedram | Host→firmware mailbox data register address in TCM [pcie.c:2157] |
| 44 | dtoh_mb_data_addr | u32 | LE | FW→Host | After FW publishes sharedram | Firmware→host mailbox data register address in TCM [pcie.c:2160] |
| 48 | ring_info_addr | u32 | LE | FW→Host | After FW publishes sharedram | Address of brcmf_pcie_dhi_ringinfo struct in TCM [pcie.c:2163]; host memcpy_fromio reads ring metadata from this address [pcie.c:1739-1740] |
| 52-55 | (console_bufaddr in host) | - | (internal) | Host | After console_init called | Populated by host reading from firmware's console struct; not part of shared memory |
| 56-59 | (console_bufsize) | - | (internal) | Host | After console_init called | Populated by host reading from firmware's console struct |
| 60-63 | (console_read_idx) | - | (internal) | Host | Runtime | Maintained by host during console_read loop |
| 64-68 | (console_log_str) | - | (internal) | Host | Runtime | Temporary host buffer, not shared with FW |
| 69 | (console_log_idx) | - | (internal) | Host | Runtime | Temporary host counter |
| 70-71 | version (extracted) | u8 | - | Host | After init_share_ram_info reads flags | Version extracted from flags[0:7]; must be 5-7 [pcie.c:2131-2137] |
| 72+ | *commonrings[] | ptrs (kernel mem) | Host | Host | After init_ringbuffers called | Array of 5 pointers to DMA-allocated ring buffers; not in TCM shared memory |

**Key Observations:**
- Host struct **brcmf_pcie_shared_info** at pcie.c:492 is **not** directly written to TCM by host.
- **Firmware** writes a memory image at TCM[sharedram_addr] starting with flags (version in low byte) at offset 0.
- Host **reads** from that firmware-provided image, populates the host struct via **brcmf_pcie_init_share_ram_info** (pcie.c:2120-2172).
- Offsets 0, 20, 34, 36, 40, 44, 48 are read from TCM; the rest are host-side state.

---

## Console Struct: brcmf_pcie_console

**Definition:** pcie.c:483-490

Firmware maintains a separate console struct **at an address published in the shared struct** (offset 20). Host retrieves it via multi-step read:

1. Read console_base_addr from TCM[sharedram+20] [pcie.c:1346]
2. Read console_buf_addr from TCM[console_base_addr+8] [pcie.c:1349]
3. Read console_bufsize from TCM[console_base_addr+12] [pcie.c:1351]
4. At runtime, read console write index from TCM[console_base_addr+16] [pcie.c:1380]

**Console offsets within the console struct** (maintained by firmware):
- Offset 0: base_addr of console struct itself (pointer firmware stores, host reads)
- Offset 8: buf_addr (ring buffer start in TCM) [BRCMF_CONSOLE_BUFADDR_OFFSET=8]
- Offset 12: bufsize (ring buffer size) [BRCMF_CONSOLE_BUFSIZE_OFFSET=12]
- Offset 16: write_idx (FW's write position) [BRCMF_CONSOLE_WRITEIDX_OFFSET=16]

---

## Ring Info Struct: brcmf_pcie_dhi_ringinfo

**Definition:** pcie.c:585-598

Host reads this struct from TCM[ring_info_addr] as a single **memcpy_fromio** [pcie.c:1739-1740]. This struct contains:

| Offset | Field | Width | Dir | Notes |
|--------|-------|-------|-----|-------|
| 0 | ringmem | u32 LE | FW→Host | TCM address of ring memory blocks |
| 4 | h2d_w_idx_ptr | u32 LE | FW→Host | Write-index pointer for H2D ring 0 (or TCM offset if DMA_INDEX flag not set) |
| 8 | h2d_r_idx_ptr | u32 LE | FW→Host | Read-index pointer for H2D ring 0 |
| 12 | d2h_w_idx_ptr | u32 LE | FW→Host | Write-index pointer for D2H ring 0 |
| 16 | d2h_r_idx_ptr | u32 LE | FW→Host | Read-index pointer for D2H ring 0 |
| 20-27 | h2d_w_idx_hostaddr | msgbuf_buf_addr | Host→FW | Host DMA address (low 32b + high 32b) for H2D write indices (DMA mode only) |
| 28-35 | h2d_r_idx_hostaddr | msgbuf_buf_addr | Host→FW | Host DMA address for H2D read indices |
| 36-43 | d2h_w_idx_hostaddr | msgbuf_buf_addr | Host→FW | Host DMA address for D2H write indices |
| 44-51 | d2h_r_idx_hostaddr | msgbuf_buf_addr | Host→FW | Host DMA address for D2H read indices |
| 52 | max_flowrings | u16 LE | FW→Host | Max flow rings FW supports [pcie.c:1742-1744] |
| 54 | max_submissionrings | u16 LE | FW→Host | Max H2D common rings (includes H2D common rings) |
| 56 | max_completionrings | u16 LE | FW→Host | Max D2H common rings |

---

## Minimum Fields Required Before set_active

### For Firmware to Progress Past set_active

Based on code analysis, **firmware must have**:

1. **Flags with version byte** at TCM[sharedram+0]:
   - Bits 0-7 must be 5-7 (MIN=5 [pcie.c:409], MAX=7 [pcie.c:410])
   - Flags checked at pcie.c:2130-2137; fails if outside range
   - **Test.247 finding:** Version=5 at offset 0, rest zero passed the initial read-accept gate

2. **Console address** at TCM[sharedram+20]:
   - Not strictly required to progress; brcmf_pcie_bus_console_init [pcie.c:1337-1355] reads it unconditionally
   - If zero or invalid, console_read returns immediately [pcie.c:1377-1378]
   - Does NOT block firmware progression

3. **Ring info address** at TCM[sharedram+48]:
   - **CRITICAL:** Used immediately after init_share_ram_info in init_ringbuffers [pcie.c:1739]
   - If zero or garbage, memcpy_fromio will read garbage → ring setup fails → probe fails
   - Must point to valid brcmf_pcie_dhi_ringinfo struct with sensible max_flowrings, max_submissionrings, max_completionrings

4. **Mailbox data addresses** (offsets 40, 44):
   - **Not** read during init_ringbuffers or init_share_ram_info
   - Used later during first message exchange [implies after set_active succeeds]
   - Can remain zero for pre-set_active phase

5. **max_rxbufpost, rx_dataoffset, htod/dtoh_mb_data_addr** (offsets 34, 36, 40, 44):
   - **Not** checked for validity during initialization
   - If zero, host uses defaults or defers to ringbuf init

### Verdict on Test.247 Probe (72 bytes, version=5, rest zero)

**Important framing:** T247 observed firmware *never* publish a
`sharedram_addr` at TCM[ramsize-4] (unchanged across 23 dwells). The
host code that reads and validates the shared struct
(`brcmf_pcie_init_share_ram_info`, `pcie.c:2120`) is only reached
*after* the host detects an FW-published sharedram pointer. In T247
the host never got there. So the analysis below is conditional — it
describes what *would* happen *if* firmware had published the struct
and host had reached the validation path, not what did happen.

**Hypothetical: if host had reached `init_share_ram_info`, what would
it do with our 72-byte, version=5, rest-zero struct?**
- Version=5: *would* pass the host's range check at
  `pcie.c:2131-2137` (5 ∈ [MIN=5, MAX=7]).
- Console addr=0: host-side `console_init` handles zero gracefully.
- Ring info addr=0: host-side `memcpy_fromio` from TCM[0] would read
  invalid ringinfo; `max_flowrings` would be garbage, likely failing
  the bounds check at `pcie.c:1751-1753`. This failure would occur
  during `brcmf_pcie_init_ringbuffers` (`pcie.c:5445`), which is
  itself only called after `brcmf_chip_set_active` succeeds.

**What T247 actually observed:**
Firmware never wrote the sharedram pointer. The host-side validation
path above was never invoked. The null result therefore does not
falsify either the version choice or the ring_info layout — it is
upstream of both checks. The distinguishing question T247 leaves open
is why firmware never publishes a sharedram_addr, not whether our
placeholder struct would have passed validation.

**Implication for T249 / follow-on runs:**
Signature/version sweeps at the same pre-placement offset test the
same off-path hypothesis T247 tested. If firmware does not publish
sharedram_addr regardless of signature, varying version=5/6/7 at
TCM[0x80000] will continue to produce null results for the same
reason. A sweep would still be informative as a falsifier — it bounds
the class of "pre-placement content that might get firmware to
engage" — but the matrix should enumerate the more likely outcome
(all-null) and plan for the PMU/PLL pivot accordingly.

---

## Sequence: When Each Field Becomes Valid

```
1. Host downloads FW, releases ARM reset
2. Firmware boots, allocates internal structures, writes sharedram address to TCM[ramsize-4]
   └─ TCM[ramsize-4] now contains sharedram_addr (a RAM offset, typically < 0x80000)

3. Host polls TCM[ramsize-4] for change from NVRAM marker (0xffc70038) [pcie.c:4788-4789]
   └─ Detects FW-written sharedram_addr

4. Host calls brcmf_pcie_init_share_ram_info(devinfo, sharedram_addr) [pcie.c:2120]
   └─ Reads flags [FW must have flags.version ∈ [5,7]]
   └─ Reads console_addr at offset 20
   └─ Reads mailbox addrs at offsets 40, 44
   └─ Reads ring_info_addr at offset 48
   └─ Calls brcmf_pcie_bus_console_init (reads console metadata from FW's console struct)
   └─ Returns success/failure

5. Host calls brcmf_pcie_init_ringbuffers(devinfo) [pcie.c:5445]
   └─ Memcpy_fromio from TCM[ring_info_addr] to read brcmf_pcie_dhi_ringinfo
   └─ Reads max_submissionrings, max_flowrings, max_completionrings
   └─ Sets up H2D and D2H common ring indices
   └─ If DMA_INDEX flag set: writes host DMA addresses back to ringinfo struct [pcie.c:1813-1814]

6. Host calls brcmf_pcie_init_scratchbuffers(devinfo) [pcie.c:5453]
   └─ Allocates scratch DMA buffer
   └─ Writes scratch buffer address to TCM[sharedram+56] (BRCMF_SHARED_DMA_SCRATCH_ADDR_OFFSET)
   └─ Writes scratch buffer size to TCM[sharedram+52]
   └─ Allocates ringupd DMA buffer
   └─ Writes ringupd buffer address to TCM[sharedram+68]
   └─ Writes ringupd buffer size to TCM[sharedram+64]

7. Host request IRQ [pcie.c:5464]

8. Firmware now running with full ring buffers, DMA indices, console, and scratch buffers
```

---

## Console Buffer Publication Convention

**Firmware publishes console differently than shared struct:**

1. **No TCM[ramsize-4] marker** for console address
2. Firmware stores console base address **inside** the shared struct at offset 20 (console_addr field)
3. Host reads: TCM[sharedram+20] → console_base_addr
4. From console_base_addr, host reads:
   - TCM[console_base_addr+8]: buffer start address
   - TCM[console_base_addr+12]: buffer size
   - TCM[console_base_addr+16]: current write index (polled at runtime)

**Better discriminator for next run (T249)?**
- **Current method:** Poll TCM[ramsize-4] for sharedram address (coarse, time-expensive)
- **Proposed:** Poll TCM[sharedram+20] directly (if sharedram_addr is known)
  - Advantage: Doesn't rely on NVRAM marker
  - Risk: Requires knowing sharedram_addr beforehand
  
- **Even better:** Poll TCM[ramsize-4], and once it changes, poll TCM[sharedram_addr+20]
  - Combines detection (ramsize-4) with validation (console presence)
  - If console_addr ≠ 0, firmware has advanced past minimum init

---

## Candidate TCM Offsets for T249+ Probing

**Ranked by expected FW activity:**

### Tier 1: High-Value Offsets (strong signals if modified)

| Offset | Reason | Field |
|--------|--------|-------|
| ramsize-4 | Initial FW publication point | sharedram_addr pointer |
| sharedram+0 | FW writes version flag | flags with version byte |
| sharedram+20 | FW publishes console struct | console_addr |
| sharedram+48 | FW publishes ring metadata | ring_info_addr |
| ring_info_addr+0 | FW publishes ring memory start | ringmem pointer |
| ring_info_addr+52 | FW publishes ring limits | max_flowrings |

### Tier 2: Medium-Value Offsets (would indicate full progression)

| Offset | Reason | Field |
|--------|--------|-------|
| sharedram+34 | RX buffer limits | max_rxbufpost |
| sharedram+36 | RX frame offset | rx_dataoffset |
| sharedram+40 | H→F mailbox address | htod_mb_data_addr |
| sharedram+44 | F→H mailbox address | dtoh_mb_data_addr |
| console_base_addr+16 | Console write pointer active | write_idx |

### Tier 3: Lower-Value Offsets (only changed after host writes back)

| Offset | Reason | Notes |
|--------|--------|-------|
| ring_info_addr+20-51 | Host writes DMA addresses | Only if DMA_INDEX mode; FW does not write |
| sharedram+52 | Scratch buffer length | Host writes only |
| sharedram+56 | Scratch buffer address | Host writes only |
| sharedram+64 | Ringupd length | Host writes only |
| sharedram+68 | Ringupd address | Host writes only |

---

## Summary

**Firmware expectations (code-driven):**
- Firmware **publishes** sharedram address to TCM[ramsize-4] early in boot
- Firmware **populates** a memory image at sharedram with at minimum: version (offset 0), console_addr (offset 20), ring_info_addr (offset 48)
- Ring info struct must contain valid max_*rings counts, or host probe fails
- Scratch/ringupd buffers are written by **host** after firmware publishes console, not prerequisites for set_active

**Test.247 outcome (version=5, rest zero):**
- Would be accepted by version check
- Would likely fail at ringbuf init because ring_info_addr=0 leads to garbage reads
- Firmware would not reach the point of dwelling; probe would fail synchronously in host code

**Next steps (T249):**
- Monitor Tier 1 offsets immediately after set_active call
- Expect activity at ramsize-4 (sharedram pointer) first; then cascade through sharedram+0, +20, +48
- If activity seen at console_addr or ring_info_addr, firmware has progressed to table-lookup phase (promising)
- If activity stops at console_addr, firmware may be stuck waiting for console struct validation

