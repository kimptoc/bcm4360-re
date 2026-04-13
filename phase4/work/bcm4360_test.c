// SPDX-License-Identifier: GPL-2.0
/*
 * BCM4360 Offload Firmware Communication Test Module
 *
 * Phase 4B: Step-gated hardware bring-up with crash isolation.
 *
 * Levels (controlled by max_level parameter):
 *   0 = PCI bind only — no hardware access at all
 *   1 = PCI config space reads + D3→D0 power wake
 *   2 = BAR0 mapping + register reads
 *   3 = BAR2 (TCM) mapping + ARM halt + firmware download + full init
 *
 * Each level logs extensively. If any level returns 0xFFFFFFFF or hangs,
 * the test script aborts and captures dmesg.
 */

#include <linux/module.h>
#include <linux/pci.h>
#include <linux/firmware.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>

#define DRV_NAME "bcm4360_test"

static int max_level = 0;
module_param(max_level, int, 0444);
MODULE_PARM_DESC(max_level, "Max test level: 0=bind, 1=config, 2=BAR0, 3=TCM+FW, 4=ARM release (no DMA), 5=ARM+DMA+olmsg");

/* PCI IDs */
#define BCM4360_VENDOR_ID	0x14e4
#define BCM4360_DEVICE_ID	0x43a0

/* BAR sizes */
#define BAR0_SIZE		0x8000		/* 32KB register window */
#define BAR2_SIZE		0xA0000		/* 640KB TCM (populated only) */

/* BCMA backplane registers (offsets within wrapper space) */
#define BCMA_IOCTL		0x0408
#define BCMA_IOCTL_CLK		0x0001
#define BCMA_IOCTL_FGC		0x0002
#define BCMA_RESET_CTL		0x0800
#define BCMA_RESET_CTL_RESET	0x0001

/* ARM CR4 specific */
#define ARMCR4_CPUHALT		0x0020

/* BCM4360 backplane addresses (from Phase 1 core enumeration) */
#define ARM_WRAP_BASE		0x18102000
#define ARM_CORE_BASE		0x18002000

/* PCI config space BAR0 window register */
#define PCI_BAR0_WIN		0x80
#define BAR0_WIN_SIZE		0x1000

/* BCM4360 TCM parameters */
#define TCM_RAMSIZE		0xA0000		/* 640KB */

/* Shared info structure */
#define SHARED_INFO_OFFSET	(TCM_RAMSIZE - 0x2F5C)	/* = 0x9D0A4 */
#define SHARED_INFO_SIZE	0x2F3C
#define SI_MAGIC_START		0x000
#define SI_OLMSG_PHYS_LO	0x004
#define SI_OLMSG_PHYS_HI	0x008
#define SI_OLMSG_SIZE		0x00C
#define SI_CONFIG_FLAGS		0x020
#define SI_MAC_ADDR		0x024	/* 6 bytes: MAC address */
#define SI_FW_INIT_DONE		0x2028
#define SI_MAGIC_END		0x2F38
#define SHARED_MAGIC_START	0xA5A5A5A5
#define SHARED_MAGIC_END	0x5A5A5A5A

/* olmsg buffer */
#define OLMSG_BUF_SIZE		0x10000
#define OLMSG_RING_SIZE		0x7800
#define OLMSG_HEADER_SIZE	0x20

/* Firmware */
#define FW_NAME			"brcm/brcmfmac4360-pcie.bin"
#define NVRAM_NAME		"brcm/brcmfmac4360-pcie.txt"
#define FW_INIT_TIMEOUT_MS	2000

/* NVRAM/SPROM */
#define CHIPCOMMON_BASE		0x18000000
#define CC_SROM_CTRL		0x0190
#define CC_SROM_ADDR		0x019C
#define CC_SROM_DATA		0x01A0
#define SROM_BUSTYPE_WORD	0x0002	/* word offset for boardtype in SROM */
#define SROM_BOARDREV_WORD	0x0003
#define NVRAM_END_MAGIC		0x0FEED

struct bcm4360_dev {
	struct pci_dev *pdev;
	void __iomem *regs;		/* BAR0 */
	void __iomem *tcm;		/* BAR2 */
	void *olmsg_buf;
	dma_addr_t olmsg_dma;
	int irq_count;
	int result;			/* 0=pass, 1=dead_device, <0=error */
};

/* ---- Backplane access via BAR0 window ---- */

static u32 bp_read32(struct bcm4360_dev *dev, u32 addr)
{
	u32 offset = addr & (BAR0_WIN_SIZE - 1);
	u32 win = addr & ~(BAR0_WIN_SIZE - 1);

	pci_write_config_dword(dev->pdev, PCI_BAR0_WIN, win);
	return ioread32(dev->regs + offset);
}

static void bp_write32(struct bcm4360_dev *dev, u32 addr, u32 val)
{
	u32 offset = addr & (BAR0_WIN_SIZE - 1);
	u32 win = addr & ~(BAR0_WIN_SIZE - 1);

	pci_write_config_dword(dev->pdev, PCI_BAR0_WIN, win);
	iowrite32(val, dev->regs + offset);
	ioread32(dev->regs + offset); /* flush */
}

/* ---- TCM access via BAR2 (32-bit only!) ---- */

static u32 tcm_read32(struct bcm4360_dev *dev, u32 offset)
{
	if (offset + 4 > BAR2_SIZE)
		return 0xDEADDEAD;
	return ioread32(dev->tcm + offset);
}

static void tcm_write32(struct bcm4360_dev *dev, u32 offset, u32 val)
{
	if (offset + 4 > BAR2_SIZE)
		return;
	iowrite32(val, dev->tcm + offset);
}

/* ---- ARM CR4 core control ---- */

static void arm_halt(struct bcm4360_dev *dev)
{
	u32 val;
	int count = 0;

	dev_info(&dev->pdev->dev, "Halting ARM CR4...\n");

	/* Step 1: Force clocks, put ARM in reset */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, BCMA_RESET_CTL_RESET);
	usleep_range(10, 20);

	/* Step 2: Set CPUHALT while still in reset */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   ARMCR4_CPUHALT | BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	usleep_range(10, 20);

	/* Step 3: Take ARM out of reset — ARM stays halted via CPUHALT,
	 * but SOCRAM/TCM becomes accessible for firmware download.
	 * Without this step, TCM reads return 0xFFFFFFFF. */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, 0);
	do {
		val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
		if (!(val & BCMA_RESET_CTL_RESET))
			break;
		usleep_range(40, 60);
	} while (++count < 50);

	/* Step 4: Drop FGC, keep CPUHALT + CLK */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   ARMCR4_CPUHALT | BCMA_IOCTL_CLK);

	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&dev->pdev->dev, "ARM IOCTL after halt: 0x%08x\n", val);
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
	dev_info(&dev->pdev->dev, "ARM RESET_CTL: 0x%08x\n", val);
}

static void arm_release(struct bcm4360_dev *dev)
{
	u32 val;
	int count = 0;

	dev_info(&dev->pdev->dev, "Releasing ARM CR4...\n");
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, 0);
	do {
		val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
		if (!(val & BCMA_RESET_CTL_RESET))
			break;
		usleep_range(40, 60);
	} while (++count < 50);

	if (val & BCMA_RESET_CTL_RESET) {
		dev_err(&dev->pdev->dev, "ARM RESET_CTL failed to clear\n");
		return;
	}

	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL, BCMA_IOCTL_CLK);
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&dev->pdev->dev, "ARM IOCTL after release: 0x%08x\n", val);
}

/* ---- Interrupt handling ---- */

/* PCIe core registers (within BAR0 when window set to PCIe core 0x18003000) */
#define PCIE_CORE_BASE		0x18003000
#define PCIE_INTSTATUS		0x020	/* offset within PCIe core */
#define PCIE_INTMASK		0x024
#define PCIE_MAILBOXINT		0x048
#define PCIE_MAILBOXMASK	0x04C

static irqreturn_t bcm4360_isr(int irq, void *data)
{
	struct bcm4360_dev *dev = data;
	u32 intstatus;

	if (!dev->regs)
		return IRQ_NONE;

	/* Read and clear PCIe core interrupt status via backplane */
	intstatus = bp_read32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS);
	if (intstatus == 0 || intstatus == 0xFFFFFFFF)
		return IRQ_NONE;

	/* Clear by writing back (W1C) */
	bp_write32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS, intstatus);

	dev->irq_count++;
	if (dev->irq_count <= 10)
		dev_info(&dev->pdev->dev, "IRQ #%d intstatus=0x%08x\n",
			 dev->irq_count, intstatus);
	else if (dev->irq_count == 11)
		dev_info(&dev->pdev->dev, "IRQ log suppressed (further IRQs silenced)\n");

	return IRQ_HANDLED;
}

/* Mask all PCIe core interrupts */
static void pcie_mask_irqs(struct bcm4360_dev *dev)
{
	bp_write32(dev, PCIE_CORE_BASE + PCIE_INTMASK, 0);
	bp_write32(dev, PCIE_CORE_BASE + PCIE_MAILBOXMASK, 0);
	/* Clear any pending */
	bp_write32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS, 0xFFFFFFFF);
	bp_write32(dev, PCIE_CORE_BASE + PCIE_MAILBOXINT, 0xFFFFFFFF);
}

/* ---- SPROM reading (host side, via ChipCommon) ---- */

static u16 sprom_read16(struct bcm4360_dev *dev, u16 word_offset)
{
	/* Set the SPROM address and read via ChipCommon */
	bp_write32(dev, CHIPCOMMON_BASE + CC_SROM_ADDR, (u32)word_offset);
	/* Trigger read: some chips need a specific control value */
	udelay(10);
	return (u16)bp_read32(dev, CHIPCOMMON_BASE + CC_SROM_DATA);
}

static void dump_sprom(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	u16 i;
	u32 ctrl;

	/* Read SROM control register to check capability */
	ctrl = bp_read32(dev, CHIPCOMMON_BASE + CC_SROM_CTRL);
	dev_info(&pdev->dev, "[sprom] CC SROM_CTRL=0x%08x\n", ctrl);

	/* Dump first 16 SPROM words — these contain board ID info */
	dev_info(&pdev->dev, "[sprom] First 16 words:\n");
	for (i = 0; i < 16; i++) {
		u16 val = sprom_read16(dev, i);
		dev_info(&pdev->dev, "[sprom]   [%02u] = 0x%04x\n", i, val);
	}

	/* Also try PCI config space SPROM shadow (offset 0x100+) */
	dev_info(&pdev->dev, "[sprom] PCI config space 0x100-0x11F:\n");
	for (i = 0; i < 8; i++) {
		u32 val;
		pci_read_config_dword(pdev, 0x100 + i * 4, &val);
		dev_info(&pdev->dev, "[sprom]   cfg[0x%03x] = 0x%08x\n",
			 0x100 + i * 4, val);
	}
}

/* ---- NVRAM loading to TCM ---- */

/*
 * brcmfmac NVRAM format in TCM:
 * - NVRAM text placed at (ramsize - nvram_padded_len - 4)
 * - Null-terminated key=value pairs, each separated by \0
 * - Padded with \0 to 4-byte boundary
 * - At (ramsize - 4): write the total padded length as a u32
 *   with bit pattern: (~nvram_padded_len << 16) | nvram_padded_len
 */
static int load_nvram_to_tcm(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	const struct firmware *nvram_fw;
	const char *data;
	size_t len, padded_len;
	u32 nvram_tcm_offset, token;
	u32 i, word;
	int ret;

	ret = request_firmware(&nvram_fw, NVRAM_NAME, &pdev->dev);
	if (ret) {
		dev_info(&pdev->dev, "[nvram] No NVRAM file (%s): %d\n",
			 NVRAM_NAME, ret);
		return ret;
	}

	data = nvram_fw->data;
	len = nvram_fw->size;
	dev_info(&pdev->dev, "[nvram] Loaded %s (%zu bytes)\n", NVRAM_NAME, len);

	/* Pad to 4-byte boundary */
	padded_len = (len + 3) & ~3;

	/* NVRAM goes at end of TCM: ramsize - padded_len - 4 */
	nvram_tcm_offset = TCM_RAMSIZE - 4 - padded_len;
	dev_info(&pdev->dev, "[nvram] Writing %zu bytes to TCM 0x%x\n",
		 padded_len, nvram_tcm_offset);

	/* Write NVRAM data to TCM, word by word */
	for (i = 0; i < padded_len; i += 4) {
		word = 0;
		if (i < len)
			word |= (u8)data[i];
		if (i + 1 < len)
			word |= (u32)(u8)data[i + 1] << 8;
		if (i + 2 < len)
			word |= (u32)(u8)data[i + 2] << 16;
		if (i + 3 < len)
			word |= (u32)(u8)data[i + 3] << 24;
		tcm_write32(dev, nvram_tcm_offset + i, word);
	}

	/* Write the length token at ramsize - 4 */
	token = (~padded_len << 16) | (padded_len & 0xFFFF);
	tcm_write32(dev, TCM_RAMSIZE - 4, token);
	dev_info(&pdev->dev, "[nvram] Length token at TCM 0x%x = 0x%08x\n",
		 TCM_RAMSIZE - 4, token);

	release_firmware(nvram_fw);
	return 0;
}

/* ==== LEVEL 0: PCI bind only ==== */

static int level0_bind_only(struct bcm4360_dev *dev)
{
	dev_info(&dev->pdev->dev, "[level 0] PCI bind only — no hardware access\n");
	dev_info(&dev->pdev->dev, "[level 0] PASS\n");
	return 0;
}

/* ==== LEVEL 1: PCI config space + power management ==== */

static int level1_config_space(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	u16 vendor, device, subsys_vendor, subsys_device;
	u16 cmd, status;
	u32 pmcsr_raw;
	int pm_cap, ret;
	u16 pmcsr;

	dev_info(&pdev->dev, "[level 1] Reading PCI config space...\n");

	/* Read identity registers — these should work even in D3 */
	pci_read_config_word(pdev, PCI_VENDOR_ID, &vendor);
	pci_read_config_word(pdev, PCI_DEVICE_ID, &device);
	pci_read_config_word(pdev, PCI_SUBSYSTEM_VENDOR_ID, &subsys_vendor);
	pci_read_config_word(pdev, PCI_SUBSYSTEM_ID, &subsys_device);
	dev_info(&pdev->dev, "[level 1] Vendor:Device = %04x:%04x  Subsys = %04x:%04x\n",
		 vendor, device, subsys_vendor, subsys_device);

	if (vendor == 0xFFFF || device == 0xFFFF) {
		dev_err(&pdev->dev, "[level 1] FAIL — device not responding in config space\n");
		dev->result = 1;
		return -EIO;
	}

	/* Read command/status */
	pci_read_config_word(pdev, PCI_COMMAND, &cmd);
	pci_read_config_word(pdev, PCI_STATUS, &status);
	dev_info(&pdev->dev, "[level 1] CMD=0x%04x STATUS=0x%04x\n", cmd, status);
	dev_info(&pdev->dev, "[level 1]   IO=%d MEM=%d BusMaster=%d\n",
		 !!(cmd & PCI_COMMAND_IO),
		 !!(cmd & PCI_COMMAND_MEMORY),
		 !!(cmd & PCI_COMMAND_MASTER));

	/* Find Power Management capability and read current state */
	pm_cap = pci_find_capability(pdev, PCI_CAP_ID_PM);
	if (!pm_cap) {
		dev_warn(&pdev->dev, "[level 1] No PM capability found\n");
	} else {
		pci_read_config_dword(pdev, pm_cap + PCI_PM_CTRL, &pmcsr_raw);
		pmcsr = pmcsr_raw & 0xFFFF;
		dev_info(&pdev->dev, "[level 1] PM cap at 0x%02x, PMCSR=0x%04x, state=D%d\n",
			 pm_cap, pmcsr, pmcsr & PCI_PM_CTRL_STATE_MASK);

		if ((pmcsr & PCI_PM_CTRL_STATE_MASK) != 0) {
			/* Device is in D1/D2/D3 — wake it */
			dev_info(&pdev->dev, "[level 1] Device in D%d — waking to D0...\n",
				 pmcsr & PCI_PM_CTRL_STATE_MASK);

			pci_set_power_state(pdev, PCI_D0);
			msleep(100);  /* PCI spec: D3→D0 needs up to 50ms + extra margin */

			/* Re-enable device after power state change */
			ret = pci_enable_device(pdev);
			if (ret) {
				dev_err(&pdev->dev, "[level 1] FAIL — pci_enable_device after D0 wake: %d\n", ret);
				return ret;
			}
			pci_clear_master(pdev);

			/* Read PM state again */
			pci_read_config_dword(pdev, pm_cap + PCI_PM_CTRL, &pmcsr_raw);
			pmcsr = pmcsr_raw & 0xFFFF;
			dev_info(&pdev->dev, "[level 1] After D0 wake: PMCSR=0x%04x, state=D%d\n",
				 pmcsr, pmcsr & PCI_PM_CTRL_STATE_MASK);

			if ((pmcsr & PCI_PM_CTRL_STATE_MASK) != 0) {
				dev_err(&pdev->dev, "[level 1] FAIL — device stuck in D%d\n",
					pmcsr & PCI_PM_CTRL_STATE_MASK);
				dev->result = 1;
				return -EIO;
			}
		}

		/* Re-read command register — power state change may reset it */
		pci_read_config_word(pdev, PCI_COMMAND, &cmd);
		dev_info(&pdev->dev, "[level 1] Post-wake CMD=0x%04x (MEM=%d)\n",
			 cmd, !!(cmd & PCI_COMMAND_MEMORY));

		/* Ensure memory space access is enabled */
		if (!(cmd & PCI_COMMAND_MEMORY)) {
			dev_info(&pdev->dev, "[level 1] Enabling memory space access...\n");
			cmd |= PCI_COMMAND_MEMORY;
			pci_write_config_word(pdev, PCI_COMMAND, cmd);
		}
	}

	/* --- BAR0 window diagnostics (config space only, no MMIO) --- */
	{
		u32 bar0_win, bar0_raw;
		resource_size_t bar0_phys;
		u32 bar0_len;

		/* Read current BAR0 window value */
		pci_read_config_dword(pdev, PCI_BAR0_WIN, &bar0_win);
		dev_info(&pdev->dev, "[level 1] BAR0_WIN (config 0x80) = 0x%08x\n", bar0_win);

		/* Read BAR0 base address from config space */
		pci_read_config_dword(pdev, PCI_BASE_ADDRESS_0, &bar0_raw);
		bar0_phys = pci_resource_start(pdev, 0);
		bar0_len = pci_resource_len(pdev, 0);
		dev_info(&pdev->dev, "[level 1] BAR0 raw=0x%08x phys=0x%llx len=0x%x\n",
			 bar0_raw, (u64)bar0_phys, bar0_len);

		if (bar0_phys == 0 || bar0_len == 0) {
			dev_err(&pdev->dev, "[level 1] BAR0 not assigned by BIOS/firmware!\n");
		}

		/* Try writing BAR0_WIN to ChipCommon (0x18000000) */
		dev_info(&pdev->dev, "[level 1] Setting BAR0_WIN to 0x18000000 (ChipCommon)...\n");
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);
		pci_read_config_dword(pdev, PCI_BAR0_WIN, &bar0_win);
		dev_info(&pdev->dev, "[level 1] BAR0_WIN readback = 0x%08x\n", bar0_win);

		if (bar0_win != 0x18000000) {
			dev_warn(&pdev->dev, "[level 1] BAR0_WIN write did not stick!\n");
		}

		/* Try PCIe core window */
		dev_info(&pdev->dev, "[level 1] Setting BAR0_WIN to 0x18003000 (PCIe core)...\n");
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18003000);
		pci_read_config_dword(pdev, PCI_BAR0_WIN, &bar0_win);
		dev_info(&pdev->dev, "[level 1] BAR0_WIN readback = 0x%08x\n", bar0_win);

		/* Read BAR2 info too */
		pci_read_config_dword(pdev, PCI_BASE_ADDRESS_2, &bar0_raw);
		bar0_phys = pci_resource_start(pdev, 2);
		bar0_len = pci_resource_len(pdev, 2);
		dev_info(&pdev->dev, "[level 1] BAR2 raw=0x%08x phys=0x%llx len=0x%x\n",
			 bar0_raw, (u64)bar0_phys, bar0_len);

		/* Check PCIe link status via capability */
		{
			int pcie_cap = pci_find_capability(pdev, PCI_CAP_ID_EXP);
			if (pcie_cap) {
				u16 link_status, link_ctrl;
				pci_read_config_word(pdev, pcie_cap + PCI_EXP_LNKSTA, &link_status);
				pci_read_config_word(pdev, pcie_cap + PCI_EXP_LNKCTL, &link_ctrl);
				dev_info(&pdev->dev, "[level 1] PCIe link: speed=%d width=%d ctrl=0x%04x\n",
					 link_status & PCI_EXP_LNKSTA_CLS,
					 (link_status & PCI_EXP_LNKSTA_NLW) >> PCI_EXP_LNKSTA_NLW_SHIFT,
					 link_ctrl);
			} else {
				dev_warn(&pdev->dev, "[level 1] No PCIe capability found\n");
			}
		}

		/* Restore BAR0_WIN to ChipCommon for level 2 */
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);

		/* Check and clear AER (Advanced Error Reporting) status */
		{
			int aer_pos = pci_find_ext_capability(pdev, PCI_EXT_CAP_ID_ERR);
			if (aer_pos) {
				u32 uncorr, corr;
				pci_read_config_dword(pdev, aer_pos + 0x04, &uncorr);
				pci_read_config_dword(pdev, aer_pos + 0x10, &corr);
				dev_info(&pdev->dev, "[level 1] AER: uncorr=0x%08x corr=0x%08x\n",
					 uncorr, corr);

				/* Clear errors by writing 1 to each set bit (W1C registers) */
				if (uncorr) {
					pci_write_config_dword(pdev, aer_pos + 0x04, uncorr);
					dev_info(&pdev->dev, "[level 1] Cleared AER uncorrectable errors\n");
				}
				if (corr) {
					pci_write_config_dword(pdev, aer_pos + 0x10, corr);
					dev_info(&pdev->dev, "[level 1] Cleared AER correctable errors\n");
				}

				/* Verify they cleared */
				pci_read_config_dword(pdev, aer_pos + 0x04, &uncorr);
				pci_read_config_dword(pdev, aer_pos + 0x10, &corr);
				dev_info(&pdev->dev, "[level 1] AER after clear: uncorr=0x%08x corr=0x%08x\n",
					 uncorr, corr);
			}
		}

		/* Enable bus mastering — device may need it for internal operations */
		dev_info(&pdev->dev, "[level 1] Enabling bus mastering...\n");
		pci_set_master(pdev);
		pci_read_config_word(pdev, PCI_COMMAND, &cmd);
		dev_info(&pdev->dev, "[level 1] CMD after bus master: 0x%04x (MEM=%d MASTER=%d)\n",
			 cmd, !!(cmd & PCI_COMMAND_MEMORY), !!(cmd & PCI_COMMAND_MASTER));
	}

	dev_info(&pdev->dev, "[level 1] PASS\n");
	return 0;
}

/* ==== LEVEL 2: BAR0 mapping + register reads ==== */

static int level2_bar0_access(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	u32 val, bar0_win;
	u32 chip_id, chip_rev, chip_pkg;

	dev_info(&pdev->dev, "[level 2] Mapping BAR0...\n");

	dev->regs = pci_iomap(pdev, 0, BAR0_SIZE);
	if (!dev->regs) {
		dev_err(&pdev->dev, "[level 2] FAIL — pci_iomap BAR0 returned NULL\n");
		return -ENOMEM;
	}
	dev_info(&pdev->dev, "[level 2] BAR0 mapped at %px (32KB)\n", dev->regs);

	/* Re-check AER status before MMIO — did level 1 clear succeed? */
	{
		int aer_pos = pci_find_ext_capability(pdev, PCI_EXT_CAP_ID_ERR);
		if (aer_pos) {
			u32 uncorr, corr;
			pci_read_config_dword(pdev, aer_pos + 0x04, &uncorr);
			pci_read_config_dword(pdev, aer_pos + 0x10, &corr);
			dev_info(&pdev->dev, "[level 2] AER pre-read: uncorr=0x%08x corr=0x%08x\n",
				 uncorr, corr);
		}
	}

	/* Check current BAR0 window register value */
	pci_read_config_dword(pdev, PCI_BAR0_WIN, &bar0_win);
	dev_info(&pdev->dev, "[level 2] BAR0_WIN register = 0x%08x\n", bar0_win);

	/* Ensure window points to ChipCommon before first MMIO read */
	if (bar0_win != 0x18000000) {
		dev_info(&pdev->dev, "[level 2] Setting BAR0_WIN to ChipCommon...\n");
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);
		msleep(1);
	}

	dev_info(&pdev->dev, "[level 2] About to do first MMIO read (BAR0+0x00)...\n");

	/* Single MMIO read — this is the dangerous operation */
	val = ioread32(dev->regs);
	dev_info(&pdev->dev, "[level 2] BAR0[0x00] (current window) = 0x%08x\n", val);

	if (val == 0xFFFFFFFF) {
		/* Backplane not responding. Try explicitly setting window to
		 * ChipCommon (0x18000000) — wl may have left it elsewhere */
		dev_info(&pdev->dev, "[level 2] Got 0xFFFFFFFF — setting BAR0_WIN to ChipCommon (0x18000000)...\n");
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);
		msleep(1);

		/* Read back the window register to verify the write took */
		pci_read_config_dword(pdev, PCI_BAR0_WIN, &bar0_win);
		dev_info(&pdev->dev, "[level 2] BAR0_WIN after write = 0x%08x\n", bar0_win);

		val = ioread32(dev->regs);
		dev_info(&pdev->dev, "[level 2] BAR0[0x00] (ChipCommon window) = 0x%08x\n", val);
	}

	if (val == 0xFFFFFFFF) {
		/* Still dead. Try reading different BAR0 offsets — maybe offset 0
		 * is special but other offsets work */
		dev_info(&pdev->dev, "[level 2] Still 0xFFFFFFFF — probing other offsets...\n");
		dev_info(&pdev->dev, "[level 2]   BAR0[0x04] = 0x%08x\n", ioread32(dev->regs + 0x04));
		dev_info(&pdev->dev, "[level 2]   BAR0[0x08] = 0x%08x\n", ioread32(dev->regs + 0x08));
		dev_info(&pdev->dev, "[level 2]   BAR0[0xFC] = 0x%08x\n", ioread32(dev->regs + 0xFC));

		/* Try setting window to PCIe core (0x18003000) — this core
		 * manages the PCIe link and should always be accessible */
		dev_info(&pdev->dev, "[level 2] Trying PCIe core window (0x18003000)...\n");
		pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18003000);
		msleep(1);
		val = ioread32(dev->regs);
		dev_info(&pdev->dev, "[level 2]   PCIe core[0x00] = 0x%08x\n", val);

		dev_err(&pdev->dev, "[level 2] FAIL — BAR0 reads 0xFFFFFFFF (backplane not responding)\n");
		dev->result = 1;
		pci_iounmap(pdev, dev->regs);
		dev->regs = NULL;
		return -EIO;
	}

	/* Parse chip ID register:
	 * [15:0]  = chip ID (expect 0x43a0 for BCM4360)
	 * [19:16] = chip revision
	 * [23:20] = package option */
	chip_id = val & 0xFFFF;
	chip_rev = (val >> 16) & 0xF;
	chip_pkg = (val >> 20) & 0xF;
	dev_info(&pdev->dev, "[level 2] Chip ID=0x%04x Rev=%d Pkg=%d\n",
		 chip_id, chip_rev, chip_pkg);

	if (chip_id != 0x4360) {
		dev_warn(&pdev->dev, "[level 2] Unexpected chip ID (expected 0x4360)\n");
	}

	/* Read a few more ChipCommon registers to verify BAR0 is working */
	val = ioread32(dev->regs + 0x04);  /* capabilities */
	dev_info(&pdev->dev, "[level 2] ChipCommon caps = 0x%08x\n", val);

	val = ioread32(dev->regs + 0xFC);  /* chip status */
	dev_info(&pdev->dev, "[level 2] ChipCommon status = 0x%08x\n", val);

	/* Test BAR0 window switching: point to ARM wrapper and read base */
	pci_write_config_dword(pdev, PCI_BAR0_WIN, ARM_WRAP_BASE & ~(BAR0_WIN_SIZE - 1));
	val = ioread32(dev->regs + (ARM_WRAP_BASE & (BAR0_WIN_SIZE - 1)));
	dev_info(&pdev->dev, "[level 2] ARM wrapper[0x000] = 0x%08x (via BAR0 window)\n", val);
	/* Also read actual IOCTL at offset 0x408 */
	{
		u32 ioctl_addr = ARM_WRAP_BASE + BCMA_IOCTL;
		pci_write_config_dword(pdev, PCI_BAR0_WIN, ioctl_addr & ~(BAR0_WIN_SIZE - 1));
		val = ioread32(dev->regs + (ioctl_addr & (BAR0_WIN_SIZE - 1)));
		dev_info(&pdev->dev, "[level 2] ARM wrapper IOCTL(0x408) = 0x%08x\n", val);
	}

	/* Restore BAR0 window to default (ChipCommon) */
	pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);

	dev_info(&pdev->dev, "[level 2] PASS\n");
	return 0;
}

/* ==== LEVEL 3: BAR2 (TCM) mapping + halt ARM + download FW ==== */

static int level3_tcm_and_fw(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	const struct firmware *fw;
	const u32 *src;
	u32 word_count, i, val;
	int ret;

	dev_info(&pdev->dev, "[level 3] BAR2 + ARM halt + FW download...\n");

	/* === CANARY 1: before BAR2 map === */
	pr_emerg("bcm4360: CANARY 1 — about to pci_iomap BAR2\n");
	mdelay(100);

	/* Map BAR2 (TCM) */
	dev_info(&pdev->dev, "[level 3] Mapping BAR2 (TCM, %dKB)...\n", BAR2_SIZE / 1024);
	dev->tcm = pci_iomap(pdev, 2, BAR2_SIZE);
	if (!dev->tcm) {
		dev_err(&pdev->dev, "[level 3] FAIL — pci_iomap BAR2 returned NULL\n");
		return -ENOMEM;
	}
	dev_info(&pdev->dev, "[level 3] BAR2 mapped at %px\n", dev->tcm);

	/* === CANARY 2: BAR2 mapped, about to read TCM === */
	pr_emerg("bcm4360: CANARY 2 — BAR2 mapped, about to read TCM[0]\n");
	mdelay(100);

	/* Verify TCM access with multiple reads */
	val = tcm_read32(dev, 0);
	dev_info(&pdev->dev, "[level 3] TCM[0x00] = 0x%08x\n", val);
	if (val == 0xFFFFFFFF) {
		dev_err(&pdev->dev, "[level 3] FAIL — TCM reads 0xFFFFFFFF\n");
		dev->result = 1;
		return -EIO;
	}
	val = tcm_read32(dev, 4);
	dev_info(&pdev->dev, "[level 3] TCM[0x04] = 0x%08x (BAR2 sanity check)\n", val);

	/* Check and clear AER errors before bulk write — stale errors on
	 * Gen1 x1 link can cause fatal lockup during sustained MMIO traffic */
	{
		int aer_pos = pci_find_ext_capability(pdev, PCI_EXT_CAP_ID_ERR);
		if (aer_pos) {
			u32 uncorr, corr;

			pci_read_config_dword(pdev, aer_pos + 0x04, &uncorr);
			pci_read_config_dword(pdev, aer_pos + 0x10, &corr);
			dev_info(&pdev->dev,
				 "[level 3] AER pre-write: uncorr=0x%08x corr=0x%08x\n",
				 uncorr, corr);
			if (uncorr) {
				pci_write_config_dword(pdev, aer_pos + 0x04, uncorr);
				dev_info(&pdev->dev, "[level 3] Cleared AER uncorrectable errors\n");
			}
			if (corr) {
				pci_write_config_dword(pdev, aer_pos + 0x10, corr);
				dev_info(&pdev->dev, "[level 3] Cleared AER correctable errors\n");
			}
		}
	}

	/* === CANARY 3: about to halt ARM === */
	pr_emerg("bcm4360: CANARY 3 — AER cleared, about to arm_halt()\n");
	mdelay(100);

	/* Halt ARM before firmware download */
	dev_info(&pdev->dev, "[level 3] Halting ARM...\n");
	arm_halt(dev);

	/* === CANARY 4: ARM halt returned === */
	pr_emerg("bcm4360: CANARY 4 — arm_halt() returned\n");
	mdelay(100);

	/* Verify ARM halt: CPUHALT set, reset cleared (TCM accessible) */
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&pdev->dev, "[level 3] ARM IOCTL after halt = 0x%08x (expect CPUHALT|CLK=0x21)\n", val);
	if (!(val & ARMCR4_CPUHALT)) {
		dev_err(&pdev->dev, "[level 3] FAIL — ARM CPUHALT not set (IOCTL=0x%08x)\n", val);
		return -EIO;
	}
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
	dev_info(&pdev->dev, "[level 3] ARM RESET_CTL after halt = 0x%08x (expect 0x00)\n", val);
	if (val & BCMA_RESET_CTL_RESET) {
		dev_err(&pdev->dev, "[level 3] FAIL — ARM still in reset, TCM not writable\n");
		return -EIO;
	}

	/* Download firmware */
	dev_info(&pdev->dev, "[level 3] Downloading firmware...\n");
	ret = request_firmware(&fw, FW_NAME, &pdev->dev);
	if (ret) {
		dev_err(&pdev->dev, "[level 3] Firmware load failed: %d\n", ret);
		return ret;
	}
	dev_info(&pdev->dev, "[level 3] Firmware: %s (%zu bytes)\n", FW_NAME, fw->size);

	if (fw->size > TCM_RAMSIZE) {
		dev_err(&pdev->dev, "[level 3] Firmware too large\n");
		release_firmware(fw);
		return -EINVAL;
	}

	src = (const u32 *)fw->data;
	word_count = (fw->size + 3) / 4;
	dev_info(&pdev->dev, "[level 3] Writing %u DWORDs (%zu bytes) to TCM...\n",
		 word_count, fw->size);

	/* === CANARY 5: about to start bulk TCM write === */
	pr_emerg("bcm4360: CANARY 5 — starting bulk TCM write (%u DWORDs)\n",
		 word_count);
	mdelay(100);

	for (i = 0; i < word_count; i++) {
		/* Single-word pacing for Gen1 x1: barrier + write + readback
		 * every word to prevent PCIe write-post buffer overflow. */
		wmb();
		iowrite32(src[i], dev->tcm + (i * 4));
		val = ioread32(dev->tcm + (i * 4));  /* flush posted write */
		/* Verify write — but 0xFFFFFFFF is valid firmware data, so
		 * compare against expected value instead of magic sentinel */
		if (val != src[i]) {
			dev_err(&pdev->dev,
				"[level 3] FAIL — write mismatch at DWORD %u: "
				"wrote 0x%08x read 0x%08x\n", i, src[i], val);
			/* If readback is 0xFFFFFFFF and we didn't write that,
			 * device is dead. Otherwise it's a real mismatch. */
			if (val == 0xFFFFFFFF) {
				release_firmware(fw);
				return -EIO;
			}
		}
		/* Extra drain pause every 16 DWORDs */
		if ((i & 0x0F) == 0x0F)
			udelay(20);
		/* Progress canary every 1024 DWORDs so crash shows how far we got */
		if ((i & 0x3FF) == 0)
			pr_emerg("bcm4360: TCM write progress: DWORD %u/%u\n",
				 i, word_count);
	}
	/* Final flush — verify last word */
	val = ioread32(dev->tcm + ((word_count - 1) * 4));
	if (val != src[word_count - 1]) {
		dev_err(&pdev->dev, "[level 3] FAIL — final verify mismatch: "
			"wrote 0x%08x read 0x%08x\n", src[word_count - 1], val);
		if (val == 0xFFFFFFFF) {
			release_firmware(fw);
			return -EIO;
		}
	}
	/* === CANARY 6: bulk write survived === */
	pr_emerg("bcm4360: CANARY 6 — bulk TCM write complete\n");
	mdelay(100);

	dev_info(&pdev->dev, "[level 3] FW write complete\n");

	val = ioread32(dev->tcm);
	dev_info(&pdev->dev, "[level 3] FW verify: first=0x%08x (expect 0x%08x)\n",
		 val, src[0]);
	if (val != src[0]) {
		dev_err(&pdev->dev, "[level 3] FAIL — FW verify mismatch\n");
		release_firmware(fw);
		return -EIO;
	}
	release_firmware(fw);

	/* Read the TCM region where shared_info will go (diagnostic) */
	{
		u32 base = SHARED_INFO_OFFSET;
		dev_info(&pdev->dev, "[level 3] TCM at shared_info offset 0x%x:\n", base);
		for (i = 0; i < 8; i++)
			dev_info(&pdev->dev, "[level 3]   [0x%x] = 0x%08x\n",
				 base + i * 4, tcm_read32(dev, base + i * 4));
	}

	dev_info(&pdev->dev, "[level 3] PASS — ARM halted, FW downloaded, ready for level 4\n");
	return 0;
}

/* ==== LEVEL 4: ARM release (NO DMA, NO bus mastering) ==== */
/*
 * This is the dangerous step. We release the ARM with:
 * - Bus mastering OFF (firmware cannot DMA)
 * - IRQs masked at the PCIe core (firmware cannot generate interrupts)
 * - An ISR registered just in case (reads + clears intstatus)
 * - NO shared_info written (firmware will fail to find magic, but safely)
 *
 * Expected outcome: ARM runs, finds no valid shared_info, spins or halts.
 * We observe via TCM reads whether the firmware modified any memory.
 */
static int level4_arm_release_safe(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	u32 i, val, base;
	bool irq_registered = false;
	int ret;

	dev_info(&pdev->dev, "[level 4] ARM release with shared_info (NO DMA)...\n");

	if (!dev->tcm || !dev->regs) {
		dev_err(&pdev->dev, "[level 4] FAIL — BAR0/BAR2 not mapped (run level 2+3 first)\n");
		return -EINVAL;
	}

	/* Ensure bus mastering is OFF — firmware cannot DMA */
	pci_clear_master(pdev);

	/* Mask all PCIe core interrupts before ARM release */
	pcie_mask_irqs(dev);

	/* Allocate DMA buffer for olmsg (firmware needs a valid address
	 * in shared_info even if bus mastering is off) */
	if (!dev->olmsg_buf) {
		dev->olmsg_buf = dma_alloc_coherent(&pdev->dev, OLMSG_BUF_SIZE,
						    &dev->olmsg_dma, GFP_KERNEL);
		if (!dev->olmsg_buf) {
			dev_err(&pdev->dev, "[level 4] FAIL — DMA alloc failed\n");
			return -ENOMEM;
		}
	}

	/* Initialize olmsg ring buffer structure */
	{
		u32 *buf = dev->olmsg_buf;

		memset(buf, 0, OLMSG_BUF_SIZE);
		/* Ring 0 (host→fw): data at offset 0x20, size 0x7800 */
		buf[0] = OLMSG_HEADER_SIZE;	/* data_offset */
		buf[1] = OLMSG_RING_SIZE;	/* size */
		buf[2] = 0;			/* read_ptr */
		buf[3] = 0;			/* write_ptr */
		/* Ring 1 (fw→host): data at offset 0x20+0x7800, size 0x7800 */
		buf[4] = OLMSG_HEADER_SIZE + OLMSG_RING_SIZE;	/* data_offset */
		buf[5] = OLMSG_RING_SIZE;	/* size */
		buf[6] = 0;			/* read_ptr */
		buf[7] = 0;			/* write_ptr */
	}
	dev_info(&pdev->dev, "[level 4] olmsg buffer: dma=0x%llx\n",
		 (u64)dev->olmsg_dma);

	/* Write shared_info to TCM — this is what the firmware looks for
	 * on boot. Without it, firmware panics ~100ms after ARM release. */
	base = SHARED_INFO_OFFSET;
	dev_info(&pdev->dev, "[level 4] Writing shared_info at TCM 0x%x...\n", base);
	/* Zero the entire shared_info structure first */
	for (i = 0; i < SHARED_INFO_SIZE / 4; i++)
		tcm_write32(dev, base + i * 4, 0);
	/* Write required fields */
	tcm_write32(dev, base + SI_MAGIC_START, SHARED_MAGIC_START);
	tcm_write32(dev, base + SI_OLMSG_PHYS_LO, lower_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_PHYS_HI, upper_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_SIZE, OLMSG_BUF_SIZE);
	tcm_write32(dev, base + SI_FW_INIT_DONE, 0);
	tcm_write32(dev, base + SI_MAGIC_END, SHARED_MAGIC_END);

	/* Verify shared_info writes */
	val = tcm_read32(dev, base + SI_MAGIC_START);
	dev_info(&pdev->dev, "[level 4] shared_info magic_start=0x%08x (expect 0x%08x)\n",
		 val, SHARED_MAGIC_START);
	val = tcm_read32(dev, base + SI_MAGIC_END);
	dev_info(&pdev->dev, "[level 4] shared_info magic_end=0x%08x (expect 0x%08x)\n",
		 val, SHARED_MAGIC_END);
	val = tcm_read32(dev, base + SI_FW_INIT_DONE);
	dev_info(&pdev->dev, "[level 4] fw_init_done=0x%08x (expect 0)\n", val);

	/* Register ISR as safety net */
	ret = request_irq(pdev->irq, bcm4360_isr, IRQF_SHARED, DRV_NAME, dev);
	if (ret) {
		dev_err(&pdev->dev, "[level 4] IRQ registration failed: %d\n", ret);
		return ret;
	}
	irq_registered = true;
	dev_info(&pdev->dev, "[level 4] IRQ %d registered, PCIe interrupts masked\n", pdev->irq);

	/* === RELEASE ARM === */
	pr_emerg("bcm4360: LEVEL4 — about to release ARM (shared_info written, no DMA)\n");
	mdelay(100);
	dev_info(&pdev->dev, "[level 4] *** RELEASING ARM (shared_info written, no bus master) ***\n");
	arm_release(dev);
	pr_emerg("bcm4360: LEVEL4 — arm_release() returned, still alive\n");
	dev_info(&pdev->dev, "[level 4] ARM released — still alive\n");

	/* Poll fw_init_done — firmware should write non-zero if it initializes */
	for (i = 0; i < FW_INIT_TIMEOUT_MS; i++) {
		val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_FW_INIT_DONE);
		if (val != 0) {
			dev_info(&pdev->dev,
				 "[level 4] *** FW INIT DONE *** val=0x%08x at %dms\n",
				 val, i);
			break;
		}
		/* Canary at key intervals */
		if (i == 50 || i == 100 || i == 500 || i == 1000)
			pr_emerg("bcm4360: LEVEL4 — %dms post-release, alive, fw_init_done=0\n", i);
		msleep(1);
	}
	if (val == 0)
		dev_info(&pdev->dev, "[level 4] fw_init_done timeout (%dms) — firmware did not signal\n",
			 FW_INIT_TIMEOUT_MS);

	dev_info(&pdev->dev, "[level 4] IRQs received: %d\n", dev->irq_count);

	/* Post-poll TCM snapshot — see what firmware wrote */
	dev_info(&pdev->dev, "[level 4] Post-release shared_info snapshot:\n");
	for (i = 0; i < 8; i++)
		dev_info(&pdev->dev, "[level 4]   [0x%x] = 0x%08x\n",
			 base + i * 4, tcm_read32(dev, base + i * 4));
	val = tcm_read32(dev, base + SI_FW_INIT_DONE);
	dev_info(&pdev->dev, "[level 4] Post-release fw_init_done=0x%08x\n", val);

	/* Check first few words of TCM (firmware entry point area) */
	dev_info(&pdev->dev, "[level 4] TCM[0x00]=0x%08x [0x04]=0x%08x [0x08]=0x%08x\n",
		 tcm_read32(dev, 0), tcm_read32(dev, 4), tcm_read32(dev, 8));

	/* Read PCIe core intstatus to see if FW tried to signal */
	val = bp_read32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS);
	dev_info(&pdev->dev, "[level 4] PCIe intstatus=0x%08x\n", val);
	val = bp_read32(dev, PCIE_CORE_BASE + PCIE_MAILBOXINT);
	dev_info(&pdev->dev, "[level 4] PCIe mailboxint=0x%08x\n", val);

	/* Halt ARM again for safety */
	dev_info(&pdev->dev, "[level 4] Re-halting ARM...\n");
	arm_halt(dev);

	if (irq_registered)
		free_irq(pdev->irq, dev);

	dev_info(&pdev->dev, "[level 4] PASS — ARM released and re-halted safely\n");
	return 0;
}

/* ==== LEVEL 5: ARM release with shared_info + DMA (full init) ==== */

static int level5_full_init(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	u32 i, val, base;
	u32 *buf;
	bool irq_registered = false;
	int ret;

	dev_info(&pdev->dev, "[level 5] Full init with shared_info + DMA...\n");

	if (!dev->tcm || !dev->regs) {
		dev_err(&pdev->dev, "[level 5] FAIL — BAR0/BAR2 not mapped\n");
		return -EINVAL;
	}

	/* Halt ARM (may still be running from level 4) */
	arm_halt(dev);

	/* Ensure bus mastering OFF */
	pci_clear_master(pdev);

	/* Mask PCIe interrupts */
	pcie_mask_irqs(dev);

	/* Re-download firmware (ARM may have modified TCM) */
	{
		const struct firmware *fw;
		const u32 *src;
		u32 word_count;

		ret = request_firmware(&fw, FW_NAME, &pdev->dev);
		if (ret) {
			dev_err(&pdev->dev, "[level 5] Firmware load failed: %d\n", ret);
			return ret;
		}
		src = (const u32 *)fw->data;
		word_count = (fw->size + 3) / 4;
		for (i = 0; i < word_count; i++)
			iowrite32(src[i], dev->tcm + (i * 4));
		dev_info(&pdev->dev, "[level 5] FW re-downloaded (%zu bytes)\n", fw->size);
		release_firmware(fw);
	}

	/* Dump SPROM from host side (before firmware can interfere) */
	dump_sprom(dev);

	/* Load NVRAM to TCM (at end of RAM, brcmfmac format) */
	ret = load_nvram_to_tcm(dev);
	if (ret)
		dev_info(&pdev->dev, "[level 5] Continuing without NVRAM file\n");

	/* Allocate DMA buffer if not already allocated */
	if (!dev->olmsg_buf) {
		dev->olmsg_buf = dma_alloc_coherent(&pdev->dev, OLMSG_BUF_SIZE,
						    &dev->olmsg_dma, GFP_KERNEL);
		if (!dev->olmsg_buf) {
			dev_err(&pdev->dev, "[level 5] FAIL — DMA alloc failed\n");
			return -ENOMEM;
		}
	}

	/* Setup olmsg ring buffer */
	buf = dev->olmsg_buf;
	memset(buf, 0, OLMSG_BUF_SIZE);
	/* Ring 0 (host→fw): data at offset 0x20, size 0x7800 */
	buf[0] = OLMSG_HEADER_SIZE;	/* data_offset */
	buf[1] = OLMSG_RING_SIZE;	/* size */
	buf[2] = 0;			/* read_ptr */
	buf[3] = 0;			/* write_ptr */
	/* Ring 1 (fw→host): data at offset 0x20+0x7800, size 0x7800 */
	buf[4] = OLMSG_HEADER_SIZE + OLMSG_RING_SIZE;	/* data_offset */
	buf[5] = OLMSG_RING_SIZE;	/* size */
	buf[6] = 0;			/* read_ptr */
	buf[7] = 0;			/* write_ptr */
	dev_info(&pdev->dev, "[level 5] olmsg buffer: dma=0x%llx virt=%px\n",
		 (u64)dev->olmsg_dma, dev->olmsg_buf);

	/* Write shared_info to TCM */
	base = SHARED_INFO_OFFSET;
	dev_info(&pdev->dev, "[level 5] Writing shared_info at TCM 0x%x...\n", base);
	/* Zero the entire shared_info structure first */
	for (i = 0; i < SHARED_INFO_SIZE / 4; i++)
		tcm_write32(dev, base + i * 4, 0);
	/* Write required fields */
	tcm_write32(dev, base + SI_MAGIC_START, SHARED_MAGIC_START);
	tcm_write32(dev, base + SI_OLMSG_PHYS_LO, lower_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_PHYS_HI, upper_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_SIZE, OLMSG_BUF_SIZE);
	/* Config flags — wl driver writes a value here from wlc state.
	 * Use 0 for now; firmware may check but shouldn't block init. */
	tcm_write32(dev, base + SI_CONFIG_FLAGS, 0);
	/* MAC address — firmware expects this; read from PCI subsystem ID
	 * or use the Apple OUI with device-derived bytes for testing */
	{
		u8 mac[8] = {0}; /* 8 bytes for aligned 2x u32 writes */
		u16 subsys;
		pci_read_config_word(pdev, PCI_SUBSYSTEM_ID, &subsys);
		/* Apple OUI 00:xx:xx + subsystem-derived bytes */
		mac[0] = 0x00;
		mac[1] = 0x1C;
		mac[2] = 0xB3;  /* Apple OUI prefix */
		mac[3] = (u8)(subsys >> 8);
		mac[4] = (u8)(subsys & 0xFF);
		mac[5] = 0x01;
		tcm_write32(dev, base + SI_MAC_ADDR,
			    mac[0] | (mac[1] << 8) | (mac[2] << 16) | (mac[3] << 24));
		tcm_write32(dev, base + SI_MAC_ADDR + 4,
			    mac[4] | (mac[5] << 8));
		dev_info(&pdev->dev,
			 "[level 5] MAC in shared_info: %02x:%02x:%02x:%02x:%02x:%02x\n",
			 mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
	}
	tcm_write32(dev, base + SI_FW_INIT_DONE, 0);
	tcm_write32(dev, base + SI_MAGIC_END, SHARED_MAGIC_END);

	/* Verify shared_info writes */
	val = tcm_read32(dev, base + SI_MAGIC_START);
	dev_info(&pdev->dev, "[level 5] shared_info magic_start=0x%08x (expect 0x%08x)\n",
		 val, SHARED_MAGIC_START);
	val = tcm_read32(dev, base + SI_MAGIC_END);
	dev_info(&pdev->dev, "[level 5] shared_info magic_end=0x%08x (expect 0x%08x)\n",
		 val, SHARED_MAGIC_END);

	/* Register ISR */
	ret = request_irq(pdev->irq, bcm4360_isr, IRQF_SHARED, DRV_NAME, dev);
	if (ret) {
		dev_err(&pdev->dev, "[level 5] IRQ registration failed: %d\n", ret);
		return ret;
	}
	irq_registered = true;
	dev_info(&pdev->dev, "[level 5] IRQ %d registered\n", pdev->irq);

	/* Enable bus mastering BEFORE ARM release — firmware needs DMA
	 * access to read olmsg buffer immediately on startup */
	pci_set_master(pdev);
	dev_info(&pdev->dev, "[level 5] Bus mastering ON (before ARM release)\n");

	/* Clear pending interrupts and unmask */
	bp_write32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS, 0xFFFFFFFF);
	bp_write32(dev, PCIE_CORE_BASE + PCIE_MAILBOXINT, 0xFFFFFFFF);
	bp_write32(dev, PCIE_CORE_BASE + PCIE_INTMASK, 0xFFFFFFFF);
	bp_write32(dev, PCIE_CORE_BASE + PCIE_MAILBOXMASK, 0xFFFFFFFF);
	dev_info(&pdev->dev, "[level 5] PCIe interrupts cleared and unmasked\n");

	/* Boot handshake step 6: write CPUHALT to ARM IOCTL before release
	 * (matches wl driver's sequence between shared_info and ARM release) */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL, ARMCR4_CPUHALT);
	dev_info(&pdev->dev, "[level 5] ARM IOCTL = 0x20 (step 6 pre-release)\n");

	/* Release ARM — firmware starts executing immediately */
	dev_info(&pdev->dev, "[level 5] *** RELEASING ARM ***\n");
	arm_release(dev);
	dev_info(&pdev->dev, "[level 5] ARM released\n");

	/* Poll for firmware init */
	dev_info(&pdev->dev, "[level 5] Polling fw_init_done...\n");
	for (i = 0; i < FW_INIT_TIMEOUT_MS; i++) {
		val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_FW_INIT_DONE);
		if (val != 0) {
			dev_info(&pdev->dev,
				 "[level 5] *** FW INIT SUCCESS *** val=0x%08x at %dms\n",
				 val, i);
			goto fw_ok;
		}
		/* Periodic progress at 100ms, 500ms, 1000ms, 1500ms */
		if (i == 100 || i == 500 || i == 1000 || i == 1500) {
			u32 ist = bp_read32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS);
			u32 mbi = bp_read32(dev, PCIE_CORE_BASE + PCIE_MAILBOXINT);
			dev_info(&pdev->dev,
				 "[level 5] %dms: fw_init_done=0, intstatus=0x%x, mailbox=0x%x, irqs=%d\n",
				 i, ist, mbi, dev->irq_count);
		}
		usleep_range(1000, 1500);
	}

	/* Timeout — mask interrupts and disable bus mastering */
	pcie_mask_irqs(dev);
	pci_clear_master(pdev);
	dev_err(&pdev->dev, "[level 5] FW init TIMEOUT (%dms) — bus master disabled\n",
		FW_INIT_TIMEOUT_MS);

	/* === Comprehensive diagnostic dump === */
	dev_info(&pdev->dev, "[level 5] === POST-TIMEOUT DIAGNOSTICS ===\n");

	/* ARM state — still running or crashed? */
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&pdev->dev, "[level 5] ARM IOCTL=0x%08x RESET_CTL=0x%08x\n",
		 val, bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL));

	/* PCIe interrupt state */
	dev_info(&pdev->dev, "[level 5] PCIe intstatus=0x%08x mailboxint=0x%08x\n",
		 bp_read32(dev, PCIE_CORE_BASE + PCIE_INTSTATUS),
		 bp_read32(dev, PCIE_CORE_BASE + PCIE_MAILBOXINT));
	dev_info(&pdev->dev, "[level 5] PCIe intmask=0x%08x mailboxmask=0x%08x\n",
		 bp_read32(dev, PCIE_CORE_BASE + PCIE_INTMASK),
		 bp_read32(dev, PCIE_CORE_BASE + PCIE_MAILBOXMASK));
	dev_info(&pdev->dev, "[level 5] IRQs received: %d\n", dev->irq_count);

	/* Scan entire shared_info for non-zero words firmware wrote
	 * (we zeroed it all before writing our fields) */
	base = SHARED_INFO_OFFSET;
	{
		int nz_count = 0;
		for (i = 0; i < SHARED_INFO_SIZE / 4; i++) {
			val = tcm_read32(dev, base + i * 4);
			if (val != 0) {
				if (nz_count < 40) /* cap output */
					dev_info(&pdev->dev,
						 "[level 5] shared_info[0x%04x]=0x%08x\n",
						 i * 4, val);
				nz_count++;
			}
		}
		dev_info(&pdev->dev,
			 "[level 5] shared_info: %d non-zero words out of %u\n",
			 nz_count, SHARED_INFO_SIZE / 4);
	}

	/* Read firmware console buffer.
	 * shared_info[0x010] points to a console structure:
	 *   +0x00: buf_addr (TCM address of text buffer)
	 *   +0x04: buf_size
	 *   +0x08: write_idx (bytes written)
	 *   +0x0C: read_addr
	 */
	{
		u32 cons_struct = tcm_read32(dev, base + 0x010);
		if (cons_struct > 0 && cons_struct < TCM_RAMSIZE - 16) {
			u32 buf_addr = tcm_read32(dev, cons_struct);
			u32 buf_size = tcm_read32(dev, cons_struct + 4);
			u32 write_idx = tcm_read32(dev, cons_struct + 8);
			dev_info(&pdev->dev,
				 "[level 5] FW console: struct=0x%x buf=0x%x size=%u written=%u\n",
				 cons_struct, buf_addr, buf_size, write_idx);
			if (buf_addr > 0 && buf_addr < TCM_RAMSIZE &&
			    write_idx > 0 && write_idx <= buf_size &&
			    buf_size <= 0x10000) {
				/* Read console text as ASCII from TCM */
				u32 to_read = write_idx;
				u32 offset;
				char line[128];
				int lpos = 0;
				if (to_read > 2048) {
					/* Show last 2KB if buffer is large */
					offset = buf_addr + write_idx - 2048;
					to_read = 2048;
					dev_info(&pdev->dev,
						 "[level 5] FW console (last 2KB of %u):\n",
						 write_idx);
				} else {
					offset = buf_addr;
					dev_info(&pdev->dev,
						 "[level 5] FW console (%u bytes):\n",
						 write_idx);
				}
				for (i = 0; i < to_read; i++) {
					u32 word = tcm_read32(dev,
							      (offset + i) & ~3);
					u8 ch = (word >> (8 * ((offset + i) & 3))) & 0xFF;
					if (ch == '\n' || lpos >= 120) {
						line[lpos] = '\0';
						if (lpos > 0)
							dev_info(&pdev->dev,
								 "[level 5] CON: %s\n",
								 line);
						lpos = 0;
					} else if (ch >= 0x20 && ch < 0x7F) {
						line[lpos++] = ch;
					} else if (ch == '\t') {
						line[lpos++] = ' ';
					}
				}
				if (lpos > 0) {
					line[lpos] = '\0';
					dev_info(&pdev->dev,
						 "[level 5] CON: %s\n", line);
				}
			}
		}
	}

	/* Check olmsg DMA buffer */
	buf = dev->olmsg_buf;
	dev_info(&pdev->dev, "[level 5] olmsg host->fw: wr=%u rd=%u\n", buf[3], buf[2]);
	dev_info(&pdev->dev, "[level 5] olmsg fw->host: wr=%u rd=%u\n", buf[7], buf[6]);
	/* Scan first 64 words of olmsg for any non-zero data */
	{
		int nz = 0;
		for (i = 0; i < 64; i++)
			if (buf[i]) nz++;
		dev_info(&pdev->dev,
			 "[level 5] olmsg first 256 bytes: %d non-zero words\n", nz);
	}

	/* Halt ARM */
	arm_halt(dev);
	if (irq_registered)
		free_irq(pdev->irq, dev);
	return -ETIMEDOUT;

fw_ok:
	buf = dev->olmsg_buf;
	dev_info(&pdev->dev, "[level 5] olmsg host->fw: wr=%u rd=%u\n", buf[3], buf[2]);
	dev_info(&pdev->dev, "[level 5] olmsg fw->host: wr=%u rd=%u\n", buf[7], buf[6]);
	dev_info(&pdev->dev, "[level 5] IRQs received: %d\n", dev->irq_count);
	dev_info(&pdev->dev, "[level 5] PASS\n");

	/* Disable bus mastering, mask interrupts, halt ARM */
	pcie_mask_irqs(dev);
	pci_clear_master(pdev);
	arm_halt(dev);
	if (irq_registered)
		free_irq(pdev->irq, dev);
	return 0;
}

/* ---- PCI driver callbacks ---- */

static int bcm4360_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct bcm4360_dev *dev;
	int ret;

	dev_info(&pdev->dev, "=== BCM4360 test: max_level=%d ===\n", max_level);

	dev = kzalloc(sizeof(*dev), GFP_KERNEL);
	if (!dev)
		return -ENOMEM;

	dev->pdev = pdev;
	pci_set_drvdata(pdev, dev);

	ret = pci_enable_device(pdev);
	if (ret) {
		dev_err(&pdev->dev, "pci_enable_device failed: %d\n", ret);
		goto err_free;
	}

	/* Disable bus mastering immediately */
	pci_clear_master(pdev);

	/* Level 0 */
	ret = level0_bind_only(dev);
	if (ret || max_level < 1)
		goto done;

	/* Level 1 */
	ret = level1_config_space(dev);
	if (ret || max_level < 2)
		goto done;

	/* Level 2 */
	ret = level2_bar0_access(dev);
	if (ret || max_level < 3)
		goto done;

	/* Level 3: TCM + halt ARM + FW download */
	ret = level3_tcm_and_fw(dev);
	if (ret || max_level < 4)
		goto done;

	/* Level 4: ARM release (NO DMA, NO bus mastering) */
	ret = level4_arm_release_safe(dev);
	if (ret || max_level < 5)
		goto done;

	/* Level 5: Full init with shared_info + DMA */
	ret = level5_full_init(dev);

done:
	dev_info(&pdev->dev, "=== Test complete: level=%d result=%d ===\n",
		 max_level, ret);
	return 0;  /* Always succeed probe so module stays loaded for dmesg */

err_free:
	kfree(dev);
	return ret;
}

static void bcm4360_remove(struct pci_dev *pdev)
{
	struct bcm4360_dev *dev = pci_get_drvdata(pdev);

	dev_info(&pdev->dev, "BCM4360 test module remove\n");

	if (dev->tcm)
		arm_halt(dev);
	if (dev->olmsg_buf)
		dma_free_coherent(&pdev->dev, OLMSG_BUF_SIZE,
				  dev->olmsg_buf, dev->olmsg_dma);
	if (dev->tcm)
		pci_iounmap(pdev, dev->tcm);
	if (dev->regs)
		pci_iounmap(pdev, dev->regs);

	/* NOTE: We intentionally do NOT call pci_disable_device() here.
	 * Disabling the device after wl left it in a partially-initialized
	 * state causes a delayed PCIe bus lockup (~1-2 min after unload).
	 * Leaving the device enabled is safe — the PCI core handles cleanup. */
	dev_info(&pdev->dev, "BCM4360 test module remove done (device left enabled)\n");
	kfree(dev);
}

static const struct pci_device_id bcm4360_ids[] = {
	{ PCI_DEVICE(BCM4360_VENDOR_ID, BCM4360_DEVICE_ID) },
	{ }
};
MODULE_DEVICE_TABLE(pci, bcm4360_ids);

static struct pci_driver bcm4360_driver = {
	.name = DRV_NAME,
	.id_table = bcm4360_ids,
	.probe = bcm4360_probe,
	.remove = bcm4360_remove,
};

module_pci_driver(bcm4360_driver);

MODULE_LICENSE("GPL");
MODULE_DESCRIPTION("BCM4360 offload firmware communication test");
MODULE_FIRMWARE(FW_NAME);
