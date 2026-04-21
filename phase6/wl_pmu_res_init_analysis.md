# BCM4360 PMU Resource Initialization Analysis

## 1. HT Clock Handshake Mechanism

Contrary to initial hypotheses, bit 9 of the PMU Control register (`pmucontrol`, ChipCommon offset `0x600`) is NOT the HT request handshake bit on BCM4360.

### 1.1 PMU Control Bit 9: NOILPONW
Analysis of `si_pmu_init` (wl.ko + `0x11993`) confirms that bit 9 (`0x200`) corresponds to `BCMA_CC_PMU_CTL_NOILPONW`.
- At wl.ko + `0x119ba`, the driver checks `pmurev != 1`.
- If true (BCM4360 is rev 17), it proceeds to +`0x119d0`.
- At wl.ko + `0x119e1`, it performs `OR $0x2, %ah` (setting bit 9) and writes it back to `pmucontrol` (+`0x600`).
- This matches the `bcma` driver behavior, where `NOILPONW` is set during early initialization.

### 1.2 The Real HT Handshake
The firmware requests HT clock by asserting a resource request.
- **Request Signal:** The firmware/driver asserts bits in `min_res_mask` (offset `0x618`) or via the `res_req_timer` (offset `0x644`).
- **Availability Signal:** The host/firmware polls `pmustatus` (offset `0x608`) bit 2 (`0x4`), which is `PST_HTAVAIL` (`HAVEHT`).
- **Confirmation:** `si_pmu_waitforclk_on_backplane` (wl.ko + `0x12543`) specifically polls offset `0x608` and masks with `0x4` to wait for HT clock stability.

## 2. BCM4360 PMU Resource Table

The BCM4360 (PMU Rev 17) uses a 10-entry resource table located at `.rodata + 0x27e790` (file offset `0x40c9a0`).

| Resource Index | Timer/Dependency Value | Description (Likely) |
|----------------|------------------------|----------------------|
| 0              | `0x00000001`           | ALP Clock            |
| 1              | `0x00000001`           | HT Clock             |
| 2              | `0x00000001`           | Resource 2           |
| 3              | `0x00000001`           | Resource 3           |
| 4              | `0x00860002`           | Resource 4           |
| 5              | `0x00000000`           | Resource 5           |
| 6              | `0x00200001`           | Resource 6 (Rev < 4) |
| 7              | `0x00080001`           | Resource 7           |
| 8              | `0x00000000`           | Resource 8           |
| 9              | `0x00000080`           | Resource 9           |

*Note: Table was extracted from `wl.ko` binary at `.rodata + 0x27e790`.*

## 3. Mask Values for BCM4360 Rev 3

The BCM4360 revision 3 initialization in `si_pmu_res_init` (0x14cab) and its helper `si_pmu_chipcontrol` (0x111b0) establishes the resource masks.

### 3.1 Initial Helper Masks (in `si_pmu_chipcontrol`)
For `BCMA_CHIP_ID_BCM4360` with `corerev > 2`, `si_pmu_chipcontrol` sets:
- `min_msk` = `0x00000000` (or `0x103` if `corerev <= 3`)
- `max_msk` = `0x000001ff`

### 3.2 Dynamic Update (`si_pmu_res_init`)
The `min_msk` is dynamically updated by `si_pmu_res_init` after the initial values are set. It calls a resource request helper (wl.ko + `0x118f2`) that iterates through the initial mask and adds any dependencies defined in the resource table.

The previous analysis incorrectly claimed that a package ID check for BCM4360 would force the masks to `0x3fffffff`. This is not the case. The `0x3fffffff` mask is set by `si_pmu_chipcontrol`, but for other chip families (e.g., BCM4314, BCMa886), not BCM4360.

## 4. Conclusion for test.189
The firmware stall in `test.188` was likely caused by `brcmfmac` failing to set the PMU resource masks correctly. Even if the firmware requests HT clock (via internal PMU logic), the hardware will not grant it unless the host has enabled the resource in the `max_res_mask`. The previous recommendation to use a wide-open `0x3fffffff` mask was based on an incorrect reading of the disassembly. A more precise mask should be used.

**Recommended Action:**
1. Initialize the PMU resource table with the values in Section 2.
2. Set `max_res_mask` to the value determined by `si_pmu_chipcontrol` for BCM4360, which is `0x1ff`. A wider mask may be safe but is not what the `wl` driver does.
3. Set `min_res_mask` to include at least ALP (bit 0) and HT (bit 1) to satisfy the early firmware boot requirements.

## 5. Re-anchored Verification

This section provides audit-ready verification for the claims made above, based on re-anchored disassembly of `wl.ko`.

### 5.1 Q1: The 0x3fffffff value at 0x1538c

**Conclusion: Refuted.** The original analysis was incorrect. The value `0x3fffffff` is not written at or around `0x1538c`. The instruction at that address is a `call`.

**Analysis:**
The disassembly of `si_pmu_res_init` from `0x14cab` shows that `0x1538c` is part of a series of function calls related to chip-specific workarounds, not a literal write of a mask value.
```
   15384:       mov    rsi,r13
   15387:       mov    edi,0xe
   1538c:       call   15391 <si_pmu_res_init+0x6e6>
```
The value `0x3fffffff` does appear in the `si_pmu_chipcontrol` function (called by `si_pmu_res_init`), but it is associated with other chipsets, not the BCM4360. For example:
```
0000000000011553 <si_pmu_chipcontrol+0x3e8>:
   11553:       mov    edx,0x3fffffff
   11558:       mov    r14d,0x23f6ff
   1155e:       jmp    11590 <si_pmu_chipcontrol+0x425>
```
This path is taken for chip IDs that fall through the main switch statement, such as BCM4314, not BCM4360.

### 5.2 Q2: The package-ID gate (bit 0x20)

**Conclusion: Confirmed, but with different consequences.** The package-ID gate is real, but it does not lead to the `0x3fffffff` mask write.

**Analysis:**
Within `si_pmu_res_init`, for chip `0x4360`, the code checks the package ID. The check happens at `0x15296` for `corerev <= 3` and `0x152e4` for `corerev > 3`.
```
0000000000015291 <si_pmu_res_init+0x5e6>:
   15291:       mov    eax,DWORD PTR [rbx+0x48] ; rbx is sih, eax = sih->chip_pkg
   ...
   15296:       test   al,0x20
   15298:       jne    15399 <si_pmu_res_init+0x6ee> ; if (chip_pkg & 0x20) != 0, skip
```
If the bit is *not* set, the code proceeds with a series of register writes via function calls, but none of these writes involve the `0x3fffffff` mask. The original analysis incorrectly conflated this conditional path with the mask value used for other chips.

### 5.3 Q3: The HT-availability polling claim at wl.ko+0x12543

**Conclusion: Confirmed.**

**Analysis:**
The function `si_pmu_waitforclk_on_backplane` at `0x12543` is a polling routine.
```
0000000000012543 <si_pmu_waitforclk_on_backplane>:
   12552:       mov    r12d,edx          ; r12d = mask (caller-supplied)
   1254b:       mov    r14d,ecx          ; r14d = timeout in us
   ...
   12577:       lea    rax,[rax+0x608]   ; Set poll address to ChipCommon base + 0x608
   ...
   12596:       mov    rdi, ...          ; rdi = address of register (pmustatus)
   1259a:       call   ...               ; read register value into eax
   1259f:       and    eax,r12d          ; apply mask
   125a2:       cmp    eax,r12d          ; check if all masked bits are set
   125a5:       je     125ad             ; exit loop if condition met
   125a7:       cmp    r14d,0x9
   125ab:       ja     12588             ; loop if timeout has not expired
```
The code confirms the following:
- **Register Offset:** It polls the register at offset `0x608` relative to the ChipCommon core's base address, which corresponds to `pmustatus`.
- **Mask Value:** The mask is passed as an argument (`edx`) by the caller. For waiting on HT clock, the caller would use `0x4`.
- **Polling Loop:** The function implements a standard polling loop with a timeout, repeatedly reading the register and checking the bits against the mask until the condition is met or the timeout expires.

## 6. Package-ID Gate (bit 0x20) WAR Analysis

This section details the static analysis of the package ID gate found in `si_pmu_res_init`, which triggers different hardware workarounds (WARs) based on bit 0x20 of the `sih->chip_pkg` field.

### 6.1. Disassembly Anchor and Verification

The analysis is anchored at `si_pmu_res_init` (wl.ko + `0x14cab`). Within this function, after chip-specific branches, code paths for BCM4352 and BCM4360 converge. A check on `sih->corerev` determines which gate to use:
- For `corerev <= 3`, the check is at `wl.ko+0x15296`.
- For `corerev > 3`, the check is at `wl.ko+0x152e4`.

Both gates test bit 0x20 of the `%al` register, which holds the value of `sih->chip_pkg` loaded at `wl.ko+0x15291`.

### 6.2. Branch: Bit 0x20 is CLEAR

This branch executes a series of chip-specific WAR writes. The behavior differs by `corerev`.

#### For `corerev <= 3` (path at `wl.ko+0x1529e`)

The code performs two writes to the PMU `regcontrol` registers. This involves writing a register number to `pmu_regcontrol_addr` (offset `0x660`) and then writing a value to `pmu_regcontrol_data` (offset `0x664`).

| Offset (wl.ko) | Action                                    | Register        | Value          |
|----------------|-------------------------------------------|-----------------|----------------|
| `+0x152b3`     | Set `regcontrol` address                  | `regcontrol` #6 | -              |
| `+0x152be`     | Write value                               | `regcontrol` #6 | `0x09048562`   |
| `+0x152cb`     | Set `regcontrol` address                  | `regcontrol` #0xe | -              |
| `+0x152d8`     | Write value (via jmp to `+0x1538c`)       | `regcontrol` #0xe | `0x09048562`   |

#### For `corerev > 3` (path at `wl.ko+0x152ea`)

This path is more complex, involving writes to both `chipcontrol` and `regcontrol` registers.

| Offset (wl.ko) | Action                                    | Register          | Value / Mask         |
|----------------|-------------------------------------------|-------------------|----------------------|
| `+0x1530c`     | Read-modify-write `chipcontrol` register 1  | `chipcontrol` #1  | `val | 0x800`        |
| `+0x15339`     | Write `regcontrol` register 6             | `regcontrol` #6   | `0x080004e2`         |
| `+0x15353`     | Write `regcontrol` register 7             | `regcontrol` #7   | `0x0000000e`         |
| `+0x1536d`     | Write `regcontrol` register 14 (0xe)      | `regcontrol` #0xe | `0x080004e2`         |
| `+0x15387`     | Write `regcontrol` register 15 (0xf)      | `regcontrol` #0xf | `0x0000000e`         |

### 6.3. Branch: Bit 0x20 is SET

In both `corerev` cases, if bit 0x20 of `sih->chip_pkg` is set, the code jumps to `wl.ko+0x15399`. This is the default fall-through path for this block, effectively skipping the WAR writes. This suggests that hardware with this bit set does not require these specific workarounds.

### 6.4. Portability Assessment

- **Bit 0x20 CLEAR branch:** The register writes are directly portable. The logic involves indirect writes via `addr`/`data` register pairs (`chipcontrol` at `0x650`/`0x654`, `regcontrol` at `0x660`/`0x664`), which can be implemented in `brcmfmac` using existing chip access functions. No complex logic is required, only a sequence of writes.
- **Bit 0x20 SET branch:** This path involves no new writes, so it is the default behavior and requires no changes to port.

The primary unknown is which package type is used in the target Mac hardware.

### 6.5. Recommendation for Stage-2 Port

1.  **Investigation:** The immediate priority is to determine the `sih->chip_pkg` value on the target hardware. This could be done by logging the value from a running `wl` driver or by dumping the `sii` state. Without this information, any implementation is speculative.
2.  **Default Implementation:** Given that the "bit is set" path is the non-WAR path, `brcmfmac` should initially assume this state, as it represents the "do nothing" case and is safer.
3.  **Conditional Implementation:** For stage-2, a module parameter should be added to `brcmfmac` to allow forcing the "bit is clear" WARs. This will enable testing both paths to see if the workarounds are necessary for stability or performance on the target hardware. The WARs should be implemented in a dedicated function, guarded by this parameter and the BCM4360 chip ID.

