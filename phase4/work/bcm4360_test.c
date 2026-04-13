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
MODULE_PARM_DESC(max_level, "Max test level: 0=bind, 1=config, 2=BAR0, 3=full");

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
#define FW_INIT_TIMEOUT_MS	2000

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

	dev_info(&dev->pdev->dev, "Halting ARM CR4...\n");
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, BCMA_RESET_CTL_RESET);
	usleep_range(10, 20);
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   ARMCR4_CPUHALT | BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	usleep_range(10, 20);

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

/* ---- ISR ---- */

static irqreturn_t bcm4360_isr(int irq, void *data)
{
	struct bcm4360_dev *dev = data;

	dev->irq_count++;
	if (dev->irq_count <= 10)
		dev_info(&dev->pdev->dev, "IRQ #%d\n", dev->irq_count);
	else if (dev->irq_count == 11)
		dev_info(&dev->pdev->dev, "IRQ log suppressed\n");
	return IRQ_HANDLED;
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

	/* Test BAR0 window switching: point to ARM wrapper and read IOCTL */
	pci_write_config_dword(pdev, PCI_BAR0_WIN, ARM_WRAP_BASE & ~(BAR0_WIN_SIZE - 1));
	val = ioread32(dev->regs + (ARM_WRAP_BASE & (BAR0_WIN_SIZE - 1)));
	dev_info(&pdev->dev, "[level 2] ARM wrapper IOCTL = 0x%08x (via BAR0 window)\n", val);

	/* Restore BAR0 window to default (ChipCommon) */
	pci_write_config_dword(pdev, PCI_BAR0_WIN, 0x18000000);

	dev_info(&pdev->dev, "[level 2] PASS\n");
	return 0;
}

/* ==== LEVEL 3: Full init (BAR2 + ARM + FW + olmsg) ==== */

static int level3_full_init(struct bcm4360_dev *dev)
{
	struct pci_dev *pdev = dev->pdev;
	const struct firmware *fw;
	const u32 *src;
	u32 word_count, i, val, base;
	u32 *buf;
	bool irq_registered = false;
	int ret;

	dev_info(&pdev->dev, "[level 3] Full initialization...\n");

	/* Map BAR2 (TCM) */
	dev_info(&pdev->dev, "[level 3] Mapping BAR2 (TCM, %dKB)...\n", BAR2_SIZE / 1024);
	dev->tcm = pci_iomap(pdev, 2, BAR2_SIZE);
	if (!dev->tcm) {
		dev_err(&pdev->dev, "[level 3] FAIL — pci_iomap BAR2 returned NULL\n");
		return -ENOMEM;
	}
	dev_info(&pdev->dev, "[level 3] BAR2 mapped at %px\n", dev->tcm);

	/* Verify TCM access */
	val = tcm_read32(dev, 0);
	dev_info(&pdev->dev, "[level 3] TCM[0x00] = 0x%08x\n", val);
	if (val == 0xFFFFFFFF) {
		dev_err(&pdev->dev, "[level 3] FAIL — TCM reads 0xFFFFFFFF\n");
		dev->result = 1;
		return -EIO;
	}

	/* Allocate DMA buffer */
	dev->olmsg_buf = dma_alloc_coherent(&pdev->dev, OLMSG_BUF_SIZE,
					    &dev->olmsg_dma, GFP_KERNEL);
	if (!dev->olmsg_buf) {
		dev_err(&pdev->dev, "[level 3] FAIL — DMA alloc failed\n");
		return -ENOMEM;
	}

	/* Halt ARM */
	dev_info(&pdev->dev, "[level 3] Halting ARM...\n");
	arm_halt(dev);

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
	for (i = 0; i < word_count; i++)
		iowrite32(src[i], dev->tcm + (i * 4));

	val = ioread32(dev->tcm);
	dev_info(&pdev->dev, "[level 3] FW verify: first=0x%08x (expect 0x%08x)\n",
		 val, src[0]);
	if (val != src[0]) {
		dev_err(&pdev->dev, "[level 3] FAIL — FW verify mismatch\n");
		release_firmware(fw);
		return -EIO;
	}
	release_firmware(fw);

	/* Setup olmsg ring buffer */
	buf = dev->olmsg_buf;
	memset(buf, 0, OLMSG_BUF_SIZE);
	buf[0] = OLMSG_HEADER_SIZE;
	buf[1] = OLMSG_RING_SIZE;
	buf[4] = OLMSG_HEADER_SIZE + OLMSG_RING_SIZE;
	buf[5] = OLMSG_RING_SIZE;
	dev_info(&pdev->dev, "[level 3] olmsg: dma=0x%llx\n", (u64)dev->olmsg_dma);

	/* Write shared_info */
	base = SHARED_INFO_OFFSET;
	dev_info(&pdev->dev, "[level 3] Writing shared_info at TCM 0x%x...\n", base);
	for (i = 0; i < SHARED_INFO_SIZE / 4; i++)
		tcm_write32(dev, base + i * 4, 0);
	tcm_write32(dev, base + SI_MAGIC_START, SHARED_MAGIC_START);
	tcm_write32(dev, base + SI_OLMSG_PHYS_LO, lower_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_PHYS_HI, upper_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_SIZE, OLMSG_BUF_SIZE);
	tcm_write32(dev, base + SI_FW_INIT_DONE, 0);
	tcm_write32(dev, base + SI_MAGIC_END, SHARED_MAGIC_END);

	val = tcm_read32(dev, base + SI_MAGIC_START);
	dev_info(&pdev->dev, "[level 3] shared_info magic_start=0x%08x\n", val);

	/* Disable bus mastering, register IRQ, release ARM */
	pci_clear_master(pdev);

	ret = request_irq(pdev->irq, bcm4360_isr, IRQF_SHARED, DRV_NAME, dev);
	if (ret) {
		dev_err(&pdev->dev, "[level 3] IRQ registration failed: %d\n", ret);
		return ret;
	}
	irq_registered = true;
	dev_info(&pdev->dev, "[level 3] IRQ %d registered\n", pdev->irq);

	dev_info(&pdev->dev, "[level 3] *** RELEASING ARM ***\n");
	arm_release(dev);
	dev_info(&pdev->dev, "[level 3] ARM released — still alive\n");
	msleep(100);
	dev_info(&pdev->dev, "[level 3] 100ms post-release — still alive\n");

	/* Re-enable bus mastering for DMA */
	pci_set_master(pdev);
	dev_info(&pdev->dev, "[level 3] Bus mastering ON\n");

	/* Poll for firmware init */
	dev_info(&pdev->dev, "[level 3] Polling fw_init_done...\n");
	for (i = 0; i < FW_INIT_TIMEOUT_MS; i++) {
		val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_FW_INIT_DONE);
		if (val != 0) {
			dev_info(&pdev->dev,
				 "[level 3] *** FW INIT SUCCESS *** val=0x%08x at %d ms\n",
				 val, i);
			goto fw_ok;
		}
		usleep_range(1000, 1500);
	}

	dev_err(&pdev->dev, "[level 3] FW init TIMEOUT (2s)\n");
	val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_MAGIC_START);
	dev_info(&pdev->dev, "[level 3] Post-timeout magic_start=0x%08x\n", val);
	val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_MAGIC_END);
	dev_info(&pdev->dev, "[level 3] Post-timeout magic_end=0x%08x\n", val);
	dev_info(&pdev->dev, "[level 3] TCM[0]=0x%08x TCM[4]=0x%08x\n",
		 tcm_read32(dev, 0), tcm_read32(dev, 4));

	buf = dev->olmsg_buf;
	dev_info(&pdev->dev, "[level 3] olmsg fw->host: wr=%u rd=%u\n", buf[7], buf[6]);
	dev_info(&pdev->dev, "[level 3] IRQs received: %d\n", dev->irq_count);

	if (irq_registered)
		free_irq(pdev->irq, dev);
	return -ETIMEDOUT;

fw_ok:
	buf = dev->olmsg_buf;
	dev_info(&pdev->dev, "[level 3] olmsg host->fw: wr=%u rd=%u\n", buf[3], buf[2]);
	dev_info(&pdev->dev, "[level 3] olmsg fw->host: wr=%u rd=%u\n", buf[7], buf[6]);
	dev_info(&pdev->dev, "[level 3] IRQs received: %d\n", dev->irq_count);
	dev_info(&pdev->dev, "[level 3] PASS\n");

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

	/* Level 3 */
	ret = level3_full_init(dev);

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
