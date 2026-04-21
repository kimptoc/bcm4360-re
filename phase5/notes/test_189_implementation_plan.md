# test.189 Implementation Plan — REVIEWED (values verified, one update applied)

> **Status:** Codex draft 2026-04-21, value-level reviewed against
> bcma and brcmfmac sources 2026-04-21 post-Gemini re-anchor.
>
> **Verification results — all green:**
> - LTR threshold values `0x883c883c`/`0x88648864`/`0x90039003` at
>   `0x844`/`0x848`/`0x84c` match `bcma/driver_pcie2.c:60-67` exactly
>   (`bcma_core_pcie2_set_ltr_vals`).
> - PCIE2 offset constants (DEVSTSCTRL2=0xD4, LTRENAB=0x400,
>   LTR_STATE=0x01A0, DLYPERST=0x0100, DISSPROMLD=0x0200,
>   PMCR_REFUP=0x1814, SBMBX=0x098, PM_CLK_PERIOD=0x184c) match
>   `include/linux/bcma/bcma_driver_pcie2.h`.
> - `BCMA_CC_CHIPST_4360_XTAL_40MZ = 0x1` confirmed in
>   `bcma_driver_chipcommon.h:109`.
> - `READCC32` macro exists at `brcmfmac/pcie.c:664` and is already
>   used for `pmustatus`/`min_res_mask`/`max_res_mask` reads.
> - `struct brcmf_chip.chiprev` and `struct brcmf_core.rev` exist in
>   `brcmfmac/chip.h:30,46`.
>
> **Update applied from Gemini re-anchor (commit cc5d525):**
> `min_res_mask` changed from `0x3` → **`0x103`** to match wl's actual
> behavior for BCM4360 with corerev ≤ 3 (our chip is chiprev 3). Bits
> 0+1+8 → ALP + HT + resource 8. See Change 2 below.
>
> **`0x3fffffff` explicitly excluded** — Gemini's re-anchor refuted
> this value for BCM4360; it belongs to `si_pmu_chipcontrol`'s path
> for *other chips* (BCM4314, etc.), not BCM4360
> (phase6/wl_pmu_res_init_analysis.md §5.1).
>
> **Note — the DLYPERST/DISSPROMLD WAR in Change 3 is dead code on
> our hardware** because bcma's guard `ci->rev > 3` evaluates FALSE
> for chiprev 3. Code path kept for parity with bcma; harmless no-op
> on this board.
>
> **Outstanding (not blocking test.189, but worth a follow-up):**
> - Package-ID bit 0x20 gate in `si_pmu_res_init` — confirmed real
>   per Gemini §5.2 but its WAR writes are not yet extracted. If
>   test.189 doesn't advance firmware, revisit.
> - "corerev" terminology in Gemini's §3.1 assumed to mean chip rev
>   (matches 3 for our hardware on both ">2" and "≤3" predicates).
>   If 0x103 turns out to be wrong, first suspect a different core's
>   rev being meant.

---

# test.189 Implementation Plan — conservative PMU + PCIe2 port

## 1. Summary
`test.189` should add only the verified PMU and PCIe2 prerequisites that current `brcmfmac` is still missing on BCM4360: set `NOILPONW`, apply the matches-wl initial PMU resource masks (`min_res_mask = 0x103`, `max_res_mask = 0x1ff`), port the verified `bcma_core_pcie2_init()` writes for the BCM4360 PCIe2 core, and gate final ARM release on `pmustatus & 0x4` before calling `brcmf_chip_set_active()`. The reason is unchanged from `test.188`: firmware leaves halt, but then does absolutely nothing observable, which is the signature expected when a required clock/resource/PCIe bring-up step is missing rather than when the firmware image itself is corrupt (`RESUME_NOTES.md:19-38`, `RESUME_NOTES.md:56-72`).

## 2. Verified inputs
- `test.188` established the baseline failure signature: ARM leaves halt, D11 stays in reset, TCM stays byte-identical, `mailboxint` stays zero, and `pmustatus` never changes during the 3 s window. That means the next test should focus on missing bring-up prerequisites, not firmware download integrity (`RESUME_NOTES.md:19-38`, `RESUME_NOTES.md:56-72`).
- `brcmfmac` currently does not perform any BCM4360 PCIe2 attach-time initialization because `brcmf_pcie_attach()` returns immediately for device `0x43a0` (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c:885-898`).
- `brcmfmac` already reads PMU capabilities and records `pmurev` in `brcmf_chip_setup()`, so that function is the cleanest existing insertion point for PMU setup that must happen before firmware bring-up (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c:1122-1138`).
- The verified `bcma` PMU rule for `BCMA_CC_PMU_CTL` is: clear `NOILPONW` only for `pmurev == 1`, otherwise set it. BCM4360 is in the non-rev-1 path (`scratch/asahi-linux/drivers/bcma/driver_chipcommon_pmu.c:295-307`).
- The clean-room PMU analysis confirmed that BCM4360 PMU control bit 9 is `NOILPONW`, not the HT-request handshake bit, and that `pmustatus` bit 2 (`0x4`) is the verified HT-available indicator (`phase6/wl_pmu_res_init_analysis.md:5-18`).
- The verified BCM4360 helper mask is `max_res_mask = 0x1ff`, covering resources 0-8 (`phase6/wl_pmu_res_init_analysis.md:43-47`).
- Per Gemini's re-anchored disassembly (§3.1), wl's actual initial `min_res_mask` for BCM4360 with corerev ≤ 3 is `0x103` (bits 0+1+8: ALP, HT, and resource 8). Using `0x103` matches wl behavior exactly rather than picking a narrower conservative value (`phase6/wl_pmu_res_init_analysis.md:43-47`).
- The verified BCM4360 PCIe2 init sequence from `bcma_core_pcie2_init()` is: BCM4360 rev>3 `CLK_CONTROL` WAR (`DLYPERST` cleared, `DISSPROMLD` set), LTR WAR, PM clock period write, `PMCR_REFUP |= 0x1f`, and `SBMBX = 1` (`scratch/asahi-linux/drivers/bcma/driver_pcie2.c:39-55`, `scratch/asahi-linux/drivers/bcma/driver_pcie2.c:57-105`, `scratch/asahi-linux/drivers/bcma/driver_pcie2.c:132-186`; summarized in `phase6/pmu_pcie_gap_analysis_final.md:57-75`).
- `bcma` derives BCM4360 ALP from `chipstatus` bit 0: 40 MHz when set, 20 MHz when clear. That directly determines the PM clock period programmed into PCIe2 (`scratch/asahi-linux/drivers/bcma/driver_chipcommon_pmu.c:336-347`, `scratch/asahi-linux/include/linux/bcma/bcma_driver_chipcommon.h:109`).
- `brcmf_chip_set_active()` currently remains the only final ARM-release primitive in the path, and `brcmf_pcie_exit_download_state()` is where that call is made now (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c:1407-1425`, `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c:950-964`).

## 3. Code changes

### PMU_CTL

#### Change 1: set `NOILPONW` during PMU capability setup
- File path: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c`
- Function being modified: `brcmf_chip_setup`
- Exact line range being changed: `1107-1138`

Old code:
```diff
-	u32 base;
-	u32 val;
-	int ret = 0;
-
-	pub = &chip->pub;
-	cc = list_first_entry(&chip->cores, struct brcmf_core_priv, list);
-	base = cc->pub.base;
-
-	/* get chipcommon capabilites */
-	pub->cc_caps = chip->ops->read32(chip->ctx,
-					 CORE_CC_REG(base, capabilities));
-	pub->cc_caps_ext = chip->ops->read32(chip->ctx,
-					     CORE_CC_REG(base,
-							 capabilities_ext));
-
-	/* get pmu caps & rev */
-	pmu = brcmf_chip_get_pmu(pub); /* after reading cc_caps_ext */
-	if (pub->cc_caps & CC_CAP_PMU) {
-		val = chip->ops->read32(chip->ctx,
-					CORE_CC_REG(pmu->base, pmucapabilities));
-		pub->pmurev = val & PCAP_REV_MASK;
-		pub->pmucaps = val;
-	}
-
-	brcmf_dbg(INFO, "ccrev=%d, pmurev=%d, pmucaps=0x%x\n",
-		  cc->pub.rev, pub->pmurev, pub->pmucaps);
-
-	/* execute bus core specific setup */
-	if (chip->ops->setup)
-		ret = chip->ops->setup(chip->ctx, pub);
```

New code:
```diff
+	u32 base;
+	u32 val;
+	u32 pmu_ctl;
+	int ret = 0;
+
+	pub = &chip->pub;
+	cc = list_first_entry(&chip->cores, struct brcmf_core_priv, list);
+	base = cc->pub.base;
+
+	/* get chipcommon capabilites */
+	pub->cc_caps = chip->ops->read32(chip->ctx,
+					 CORE_CC_REG(base, capabilities));
+	pub->cc_caps_ext = chip->ops->read32(chip->ctx,
+					     CORE_CC_REG(base,
+							 capabilities_ext));
+
+	/* get pmu caps & rev */
+	pmu = brcmf_chip_get_pmu(pub); /* after reading cc_caps_ext */
+	if (pub->cc_caps & CC_CAP_PMU) {
+		val = chip->ops->read32(chip->ctx,
+					CORE_CC_REG(pmu->base, pmucapabilities));
+		pub->pmurev = val & PCAP_REV_MASK;
+		pub->pmucaps = val;
+
+		if (pub->chip == BRCM_CC_4360_CHIP_ID) {
+			pmu_ctl = chip->ops->read32(chip->ctx,
+					CORE_CC_REG(pmu->base, pmucontrol));
+			if (pub->pmurev == 1)
+				pmu_ctl &= ~0x200;
+			else
+				pmu_ctl |= 0x200;
+			chip->ops->write32(chip->ctx,
+					CORE_CC_REG(pmu->base, pmucontrol), pmu_ctl);
+		}
+	}
+
+	brcmf_dbg(INFO, "ccrev=%d, pmurev=%d, pmucaps=0x%x\n",
+		  cc->pub.rev, pub->pmurev, pub->pmucaps);
+
+	/* execute bus core specific setup */
+	if (chip->ops->setup)
+		ret = chip->ops->setup(chip->ctx, pub);
```

Rationale: this ports the single verified PMU control write that `bcma_pmu_init()` performs for every non-rev-1 PMU, and the BCM4360 clean-room notes confirm that bit 9 is `NOILPONW`, not an HT request bit (`scratch/asahi-linux/drivers/bcma/driver_chipcommon_pmu.c:295-307`, `phase6/wl_pmu_res_init_analysis.md:5-18`).

### Res-masks

#### Change 2: program only the conservative verified BCM4360 initial masks
- File path: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/chip.c`
- Function being modified: `brcmf_chip_setup`
- Exact line range being changed: `1107-1138`

Old code:
```diff
-	/* get pmu caps & rev */
-	pmu = brcmf_chip_get_pmu(pub); /* after reading cc_caps_ext */
-	if (pub->cc_caps & CC_CAP_PMU) {
-		val = chip->ops->read32(chip->ctx,
-					CORE_CC_REG(pmu->base, pmucapabilities));
-		pub->pmurev = val & PCAP_REV_MASK;
-		pub->pmucaps = val;
-	}
```

New code:
```diff
+	/* get pmu caps & rev */
+	pmu = brcmf_chip_get_pmu(pub); /* after reading cc_caps_ext */
+	if (pub->cc_caps & CC_CAP_PMU) {
+		val = chip->ops->read32(chip->ctx,
+					CORE_CC_REG(pmu->base, pmucapabilities));
+		pub->pmurev = val & PCAP_REV_MASK;
+		pub->pmucaps = val;
+
+		if (pub->chip == BRCM_CC_4360_CHIP_ID) {
+			chip->ops->write32(chip->ctx,
+					CORE_CC_REG(pmu->base, max_res_mask), 0x1ff);
+			chip->ops->write32(chip->ctx,
+					CORE_CC_REG(pmu->base, min_res_mask), 0x103);
+		}
+	}
```

Rationale: `0x1ff` is the verified BCM4360 helper `max_res_mask` (9-entry resource table). `0x103` matches wl's actual initial value for BCM4360 with corerev ≤ 3 per Gemini's re-anchored disassembly (`phase6/wl_pmu_res_init_analysis.md:43-47` §3.1). Bits set: 0 (ALP) + 1 (HT) + 8. Previous draft used `0x3` (ALP+HT only) as a minimal conservative value; `0x103` is the matches-wl value and is preferred because bit 8 is a resource wl actually asserts and we don't know what firmware requires (`phase6/wl_pmu_res_init_analysis.md §5.1` refuted the alternative `0x3fffffff` override).

### PCIe2 init

#### Change 3: replace the BCM4360 early return in `brcmf_pcie_attach()` with the verified PCIe2 init port
- File path: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`
- Function being modified: `brcmf_pcie_attach`
- Exact line range being changed: `885-913`

Old code:
```diff
-static void brcmf_pcie_attach(struct brcmf_pciedev_info *devinfo)
-{
-	u32 config;
-
-	pr_emerg("BCM4360 test.128: brcmf_pcie_attach ENTRY\n");
-
-	/* test.129: BCM4360 — skip BAR1 window sizing; PCIe2 core is in BCMA reset at this
-	 * point, so any BAR0 MMIO to it causes CTO → MCE → hard crash. BAR2 is used for
-	 * firmware download, not BAR1, so this config is unnecessary for BCM4360.
-	 */
-	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
-		pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
-		return;
-	}
-
-	/* BAR1 window may not be sized properly */
-	pr_emerg("BCM4360 test.128: before select_core PCIE2\n");
-	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
-	pr_emerg("BCM4360 test.128: before write CONFIGADDR\n");
-	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x4e0);
-	pr_emerg("BCM4360 test.128: before read CONFIGDATA\n");
-	config = brcmf_pcie_read_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA);
-	pr_emerg("BCM4360 test.128: before write CONFIGDATA config=0x%08x\n", config);
-	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA, config);
-	pr_emerg("BCM4360 test.128: after write CONFIGDATA\n");
-
-	device_wakeup_enable(&devinfo->pdev->dev);
-	pr_emerg("BCM4360 test.128: brcmf_pcie_attach EXIT\n");
-}
```

New code:
```diff
+static void brcmf_pcie_attach(struct brcmf_pciedev_info *devinfo)
+{
+	u32 config;
+	u32 chipstatus;
+	u32 devstsctr2;
+	u32 alp_khz;
+	u32 pm_value;
+	struct brcmf_core *core;
+
+	pr_emerg("BCM4360 test.128: brcmf_pcie_attach ENTRY\n");
+
+	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
+		core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
+		if (!core)
+			return;
+
+		brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
+
+		if (devinfo->ci->chiprev > 3) {
+			config = brcmf_pcie_read_reg32(devinfo, 0x0000);
+			config &= ~0x0100;
+			config |= 0x0200;
+			brcmf_pcie_write_reg32(devinfo, 0x0000, config);
+			brcmf_pcie_read_reg32(devinfo, 0x0000);
+		}
+
+		if (core->rev >= 2 && core->rev != 10 && core->rev <= 13) {
+			brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR,
+					       0x0d4);
+			devstsctr2 = brcmf_pcie_read_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGDATA);
+			if (devstsctr2 & 0x400) {
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x844);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGDATA, 0x883c883c);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x848);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGDATA, 0x88648864);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x84c);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGDATA, 0x90039003);
+
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x0d4);
+				brcmf_pcie_write_reg32(devinfo,
+					       BRCMF_PCIE_PCIE2REG_CONFIGDATA,
+					       devstsctr2 | 0x400);
+
+				brcmf_pcie_write_reg32(devinfo, 0x01a0, 0x2);
+				usleep_range(1000, 2000);
+				brcmf_pcie_write_reg32(devinfo, 0x01a0, 0x0);
+				usleep_range(1000, 2000);
+			}
+		}
+
+		if (core->rev <= 13) {
+			brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
+			chipstatus = READCC32(devinfo, chipstatus);
+			brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
+			alp_khz = (chipstatus & 0x1) ? 40000 : 20000;
+			pm_value = (1000000 * 2) / alp_khz;
+
+			brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR,
+					       0x184c);
+			brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA,
+					       pm_value);
+		}
+
+		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR,
+				       0x1814);
+		config = brcmf_pcie_read_reg32(devinfo,
+				       BRCMF_PCIE_PCIE2REG_CONFIGDATA);
+		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA,
+				       config | 0x1f);
+
+		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR,
+				       0x0098);
+		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA,
+				       0x1);
+
+		device_wakeup_enable(&devinfo->pdev->dev);
+		pr_emerg("BCM4360 test.189: brcmf_pcie_attach applied conservative PCIe2 init\n");
+		return;
+	}
+
+	/* BAR1 window may not be sized properly */
+	pr_emerg("BCM4360 test.128: before select_core PCIE2\n");
+	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
+	pr_emerg("BCM4360 test.128: before write CONFIGADDR\n");
+	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x4e0);
+	pr_emerg("BCM4360 test.128: before read CONFIGDATA\n");
+	config = brcmf_pcie_read_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA);
+	pr_emerg("BCM4360 test.128: before write CONFIGDATA config=0x%08x\n", config);
+	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA, config);
+	pr_emerg("BCM4360 test.128: after write CONFIGDATA\n");
+
+	device_wakeup_enable(&devinfo->pdev->dev);
+	pr_emerg("BCM4360 test.128: brcmf_pcie_attach EXIT\n");
+}
```

Rationale: this is the exact conservative port of the verified BCM4360 `bcma_core_pcie2_init()` sequence and nothing more. The current early return drops all of these writes on the floor, so `test.189` should reintroduce only the verified WARs and PM programming before firmware download (`phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c:885-898`, `scratch/asahi-linux/drivers/bcma/driver_pcie2.c:39-55`, `scratch/asahi-linux/drivers/bcma/driver_pcie2.c:57-105`, `scratch/asahi-linux/drivers/bcma/driver_pcie2.c:132-186`).

### HT poll

#### Change 4: wait for verified HT-available state before final ARM release
- File path: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`
- Function being modified: `brcmf_pcie_exit_download_state`
- Exact line range being changed: `955-964`

Old code:
```diff
-	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID ||
-	    devinfo->ci->chip == BRCM_CC_43602_CHIP_ID) {
-		core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_INTERNAL_MEM);
-		if (core)
-			brcmf_chip_resetcore(core, 0, 0, 0);
-	}
-
-	if (!brcmf_chip_set_active(devinfo->ci, resetintr))
-		return -EIO;
-	return 0;
```

New code:
```diff
+	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID ||
+	    devinfo->ci->chip == BRCM_CC_43602_CHIP_ID) {
+		core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_INTERNAL_MEM);
+		if (core)
+			brcmf_chip_resetcore(core, 0, 0, 0);
+	}
+
+	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
+		u32 pmu_st;
+		int retries;
+
+		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
+		retries = 0;
+		do {
+			msleep(10);
+			pmu_st = READCC32(devinfo, pmustatus);
+			retries++;
+		} while (!(pmu_st & 0x04) && retries < 10);
+
+		if (!(pmu_st & 0x04))
+			return -ETIMEDOUT;
+	}
+
+	if (!brcmf_chip_set_active(devinfo->ci, resetintr))
+		return -EIO;
+	return 0;
```

Rationale: the verified HT handshake is not `pmucontrol` bit 9; it is `pmustatus & 0x4`. Polling that bit before final ARM release is the conservative way to ensure the floor/ceiling mask change has actually granted HT before the firmware starts executing (`phase6/wl_pmu_res_init_analysis.md:14-18`).

### Sequencing

#### Change 5: keep `brcmf_chip_set_active()` as the last ARM-release action
- File path: `phase5/work/drivers/net/wireless/broadcom/brcm80211/brcmfmac/pcie.c`
- Function being modified: `brcmf_pcie_exit_download_state`
- Exact line range being changed: `955-964`

(This is the same hunk as Change 4; retained for plan completeness.)

## 4. Sequencing
1. `brcmf_chip_attach()` runs first, and its existing `brcmf_chip_setup()` PMU-capability block becomes the place where BCM4360 gets `NOILPONW`, `max_res_mask = 0x1ff`, and `min_res_mask = 0x103` before any firmware work starts (`chip.c:1122-1138`).
2. The firmware callback path later enters `brcmf_pcie_setup()`, which already calls `brcmf_pcie_attach()` before `brcmf_chip_get_raminfo()` (`pcie.c:4298-4303`, `pcie.c:4319-4328`).
3. `brcmf_pcie_attach()` stops returning early for BCM4360 and instead applies the verified PCIe2 sequence: `CLK_CONTROL` WAR, conditional LTR WAR, PM clock period programming, `PMCR_REFUP |= 0x1f`, and `SBMBX = 1` (`pcie.c:885-913` after the change).
4. `brcmf_chip_get_raminfo()` stays where it is today; no logic moves across it (`pcie.c:4319-4328`, `chip.c:757-823`).
5. `brcmf_pcie_download_fw_nvram()` still enters download state, copies firmware/NVRAM, and computes `resetintr` exactly where it does today (`pcie.c:1899-1914`, `pcie.c:3024-3027`).
6. `brcmf_pcie_exit_download_state()` still resets `BCMA_CORE_INTERNAL_MEM` first for BCM4360/43602, as it already does (`pcie.c:955-960`).
7. The new conservative gate is inserted next: for BCM4360 only, select ChipCommon and poll `READCC32(devinfo, pmustatus)` until bit 2 (`0x4`) is set, or fail with `-ETIMEDOUT`.
8. Only after that poll succeeds does `brcmf_pcie_exit_download_state()` call `brcmf_chip_set_active(devinfo->ci, resetintr)`.
9. `brcmf_chip_set_active()` itself stays unchanged and remains the final ARM-release step, which preserves the current clean separation between preconditions and CPU release (`chip.c:1407-1425`).
10. For the staged `test.189` run, no further widening should be introduced after ARM release; the existing probe points should be reused to decide whether any of these four layers was the blocker.

## 5. Expected test.189 outcomes

| Layer enabled | ARM IOCTL | D11 RESET_CTL | `pmustatus` bit 2 | TCM deltas | `mailboxint` | exit code | Observable that confirms that layer was the blocker |
|---|---|---|---|---|---|---|---|
| PMU_CTL only | `0x01` after `set_active` if ARM still releases cleanly | Likely still `0x01` unless firmware advances | May stay at prior baseline or become more stable earlier | Any first non-zero delta after the prior all-zero baseline | Any non-zero mailbox bit | staged `-ENODEV` unless path is widened later | If `test.188`'s fully idle signature disappears with only `NOILPONW` added, then the missing PMU_CTL write was the gating prerequisite. |
| +PCIe2 | `0x01` | First credible success case is `0x00` on at least one post-release sample | May still be `0` or `1`; PCIe2 writes are not the HT grant themselves | First post-release TCM movement, especially if mailbox/D11 also wake up | First non-zero D2H/FN0 bit | staged `-ENODEV` | If PMU_CTL alone stays idle but adding PCIe2 attach writes produces any D11 release, mailbox interrupt, or TCM write, the skipped BCM4360 PCIe2 core init was the blocker. |
| +res-masks | `0x01` | Stronger chance of `0x00` because firmware can now get HT synchronously | Should reach `1` (`0x4`) before or around release, instead of staying flat | First persistent TCM movement is expected here if HT gating was the real problem | Mailbox may start toggling after ARM gets past its first wait | staged `-ENODEV` unless the timeout path trips | If earlier rows stay idle but this row makes `pmustatus & 0x4` become true and firmware then starts moving, the missing resource floor/ceiling was the blocker. |
| +HT poll | `0x01` on success path; unchanged if the timeout fires before release | `0x00` only on the success path | Must be `1` before `brcmf_chip_set_active()` is called | If prior row showed intermittent/no movement, this row should make it repeatable | Mailbox should become repeatable if the only issue was release timing | `0` if bring-up proceeds, `-ETIMEDOUT` if HT never arrives, staged `-ENODEV` if the harness still exits early by design | If masks make HT available but firmware still sometimes launches too early, the explicit pre-release poll will be the layer that turns a race into repeatable progress. |

## 6. Things NOT in this plan (deferred)
- Broad resource-mask override beyond the verified 9-resource helper mask: excluded because that path is still package-gated and not re-anchored for this exact hardware.
- Package-ID gate conditions: excluded because the package test that selects broader PMU behavior is not yet verified on this host.
- Rev-3-specific PLL programming on `PMU_PLLCTL_ADDR`/`PMU_PLLCTL_DATA`: defer to stage 2 only; it is not part of the conservative baseline for `test.189`.
- Any OTP/SPROM/OTP-power sequencing changes: excluded because the current failure signature is "firmware released but completely idle," not "firmware cannot read calibration/NVRAM."
- Additional watchdog, SBR, or kernel-touching reset experiments: excluded because `test.188` was host-stable and the goal here is a minimal bring-up delta, not another reset-path branch.
- BusMaster sequencing changes: excluded because `test.186d` already falsified the "first DMA fails because BusMaster is off" hypothesis (`RESUME_NOTES.md:126-170`).

## 7. Rollback
If `test.189` crashes the host or wedges the link, revert in this order:

1. Remove the BCM4360 branch added to `brcmf_pcie_attach()` and restore the current early return first. That is the highest-risk change because it reintroduces BAR0 PCIe2 MMIO that current BCM4360 code intentionally bypasses.
2. Remove the new `pmustatus & 0x4` wait in `brcmf_pcie_exit_download_state()`. If the failure is a hang rather than a hard crash, this is the next most likely place to stall.
3. Remove the `max_res_mask`/`min_res_mask` writes in `brcmf_chip_setup()`, keeping the `pmurev` read intact.
4. Remove the `NOILPONW` write in `brcmf_chip_setup()` last. It is the narrowest PMU change and the one most directly mirrored by verified `bcma` behavior.
5. Do not touch `brcmf_chip_set_active()` itself during rollback unless all four earlier removals fail to restore the current stable `test.188` baseline; keeping the final ARM-release primitive unchanged is part of the safety boundary for this test.
