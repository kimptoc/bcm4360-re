// SPDX-License-Identifier: GPL-2.0
/*
 * BCM4360 Offload Firmware Communication Test Module
 *
 * Phase 4B: Proves host ↔ firmware handshake over the olmsg protocol.
 *
 * What this does:
 * 1. Claims the BCM4360 PCI device, maps BARs
 * 2. Halts the ARM CR4 core
 * 3. Downloads the offload firmware (4352pci-bmac) to TCM via 32-bit writes
 * 4. Writes the shared_info structure at TCM end (ramsize - 0x2F5C)
 * 5. Allocates DMA-coherent 64KB olmsg ring buffer
 * 6. Registers an MSI interrupt handler BEFORE ARM release
 * 7. Releases the ARM CR4
 * 8. Polls shared_info[0x2028] for firmware init completion (2s timeout)
 *
 * Based on Phase 3 proven code (32-bit TCM writes, BAR mapping) and
 * Phase 4A reverse engineering of wlc_ol_up from wl.ko.
 */

#include <linux/module.h>
#include <linux/pci.h>
#include <linux/firmware.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/dma-mapping.h>
#include <linux/io.h>

#define DRV_NAME "bcm4360_test"

/*
 * Module parameter: max_step
 *
 * Controls how far the test proceeds. Use to isolate crash point.
 *   0 = PCI probe + BAR map only (read chip ID)
 *   1 = + ARM halt via backplane
 *   2 = + firmware download to TCM
 *   3 = + olmsg setup + shared_info write
 *   4 = + disable bus mastering + register IRQ
 *   5 = + release ARM (DANGEROUS — this is where Phase 3 crashed)
 *   6 = + re-enable bus mastering + poll fw_init_done
 */
static int max_step = 6;
module_param(max_step, int, 0444);

/* PCI IDs */
#define BCM4360_VENDOR_ID	0x14e4
#define BCM4360_DEVICE_ID	0x43a0

/* BAR sizes */
#define BAR0_SIZE		0x8000		/* 32KB register window */
#define BAR2_SIZE		0xA0000		/* 640KB TCM (populated region only!) */
/* NOTE: BAR2 physical region is 2MB but only 640KB is populated.
 * Mapping the full 2MB risks speculative reads of dead address space
 * which can hang the PCIe bus. Phase 3 confirmed 640KB = 4 A-banks. */

/* BCMA backplane registers (offsets within wrapper space) */
#define BCMA_IOCTL		0x0408
#define BCMA_IOCTL_CLK		0x0001
#define BCMA_IOCTL_FGC		0x0002
#define BCMA_RESET_CTL		0x0800
#define BCMA_RESET_CTL_RESET	0x0001

/* ARM CR4 specific */
#define ARMCR4_CPUHALT		0x0020

/* BCM4360 backplane addresses (from Phase 1 core enumeration) */
#define ARM_WRAP_BASE		0x18102000	/* ARM CR4 wrapper */
#define ARM_CORE_BASE		0x18002000	/* ARM CR4 core */

/* PCI config space BAR0 window register */
#define PCI_BAR0_WIN		0x80
#define BAR0_WIN_SIZE		0x1000		/* 4KB window */

/* BCM4360 TCM parameters (from Phase 3) */
#define TCM_RAMSIZE		0xA0000		/* 640KB */
#define TCM_RAMBASE		0x0

/* Shared info structure offset from end of TCM (from wlc_ol_up RE) */
#define SHARED_INFO_OFFSET	(TCM_RAMSIZE - 0x2F5C)	/* = 0x9D0A4 */
#define SHARED_INFO_SIZE	0x2F3C			/* start magic to end magic + 4 */

/* Shared info field offsets */
#define SI_MAGIC_START		0x000	/* 0xA5A5A5A5 */
#define SI_OLMSG_PHYS_LO	0x004	/* DMA phys addr low */
#define SI_OLMSG_PHYS_HI	0x008	/* DMA phys addr high */
#define SI_OLMSG_SIZE		0x00C	/* 0x10000 */
#define SI_FIELD_14		0x014	/* 0 */
#define SI_FIELD_18		0x018	/* 0 */
#define SI_FW_INIT_DONE		0x2028	/* FW sets non-zero when ready */
#define SI_MAGIC_END		0x2F38	/* 0x5A5A5A5A */

/* Magic values */
#define SHARED_MAGIC_START	0xA5A5A5A5
#define SHARED_MAGIC_END	0x5A5A5A5A

/* olmsg buffer */
#define OLMSG_BUF_SIZE		0x10000		/* 64KB */
#define OLMSG_RING_SIZE		0x7800		/* 30KB per ring */
#define OLMSG_HEADER_SIZE	0x20		/* 32 bytes for two ring headers */

/* Firmware file */
#define FW_NAME			"brcm/brcmfmac4360-pcie.bin"
#define FW_EXPECTED_SIZE	442233		/* 4352pci-bmac variant */

/* Timeouts */
#define FW_INIT_TIMEOUT_MS	2000
#define FW_INIT_POLL_MS		1

struct bcm4360_dev {
	struct pci_dev *pdev;

	/* BAR mappings */
	void __iomem *regs;		/* BAR0: 32KB register window */
	void __iomem *tcm;		/* BAR2: 2MB TCM window */

	/* DMA buffer for olmsg */
	void *olmsg_buf;		/* virtual address */
	dma_addr_t olmsg_dma;		/* physical address */

	/* IRQ tracking */
	int irq_count;
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
	/* Readback to flush */
	ioread32(dev->regs + offset);
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

	/* Disable ARM core: set RESET */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, BCMA_RESET_CTL_RESET);
	usleep_range(10, 20);

	/* Set CPUHALT in IOCTL */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL,
		   ARMCR4_CPUHALT | BCMA_IOCTL_FGC | BCMA_IOCTL_CLK);
	usleep_range(10, 20);

	/* Verify halted */
	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&dev->pdev->dev, "ARM IOCTL after halt: 0x%08x (expect CPUHALT=0x20)\n", val);

	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
	dev_info(&dev->pdev->dev, "ARM RESET_CTL: 0x%08x (expect RESET=0x01)\n", val);
}

static void arm_release(struct bcm4360_dev *dev)
{
	u32 val;
	int count = 0;

	dev_info(&dev->pdev->dev, "Releasing ARM CR4...\n");

	/* Clear RESET while keeping CLK and CPUHALT */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL, 0);
	count = 0;
	do {
		val = bp_read32(dev, ARM_WRAP_BASE + BCMA_RESET_CTL);
		if (!(val & BCMA_RESET_CTL_RESET))
			break;
		usleep_range(40, 60);
	} while (++count < 50);

	if (val & BCMA_RESET_CTL_RESET) {
		dev_err(&dev->pdev->dev, "ARM RESET_CTL failed to clear (0x%08x)\n", val);
		return;
	}

	/* Set normal running state: CLK only (no FGC, no CPUHALT) */
	bp_write32(dev, ARM_WRAP_BASE + BCMA_IOCTL, BCMA_IOCTL_CLK);

	val = bp_read32(dev, ARM_WRAP_BASE + BCMA_IOCTL);
	dev_info(&dev->pdev->dev, "ARM IOCTL after release: 0x%08x (expect CLK=0x01)\n", val);
}

/* ---- Firmware download ---- */

static int download_firmware(struct bcm4360_dev *dev)
{
	const struct firmware *fw;
	const u32 *src;
	u32 word_count, i;
	int ret;

	ret = request_firmware(&fw, FW_NAME, &dev->pdev->dev);
	if (ret) {
		dev_err(&dev->pdev->dev, "Failed to load firmware %s: %d\n", FW_NAME, ret);
		return ret;
	}

	dev_info(&dev->pdev->dev, "Firmware loaded: %s (%zu bytes)\n", FW_NAME, fw->size);

	if (fw->size > TCM_RAMSIZE) {
		dev_err(&dev->pdev->dev, "Firmware too large: %zu > %d\n", fw->size, TCM_RAMSIZE);
		release_firmware(fw);
		return -EINVAL;
	}

	/* Download via 32-bit writes (memcpy_toio hangs BCM4360!) */
	src = (const u32 *)fw->data;
	word_count = (fw->size + 3) / 4;

	for (i = 0; i < word_count; i++)
		iowrite32(src[i], dev->tcm + (i * 4));

	/* Verify first and last words */
	{
		u32 first = ioread32(dev->tcm);
		u32 last = ioread32(dev->tcm + ((word_count - 1) * 4));

		dev_info(&dev->pdev->dev,
			 "FW download OK (%u words). First=0x%08x Last=0x%08x\n",
			 word_count, first, last);

		if (first != src[0] || last != src[word_count - 1]) {
			dev_err(&dev->pdev->dev, "FW verify FAILED!\n");
			release_firmware(fw);
			return -EIO;
		}
	}

	release_firmware(fw);
	return 0;
}

/* ---- olmsg ring buffer setup ---- */

static void setup_olmsg(struct bcm4360_dev *dev)
{
	u32 *buf = dev->olmsg_buf;

	memset(buf, 0, OLMSG_BUF_SIZE);

	/* Ring 0 header (host → firmware): offsets 0x00-0x0F */
	buf[0] = OLMSG_HEADER_SIZE;	/* data_offset: data starts after both headers */
	buf[1] = OLMSG_RING_SIZE;	/* size: 30KB */
	buf[2] = 0;			/* read_ptr */
	buf[3] = 0;			/* write_ptr */

	/* Ring 1 header (firmware → host): offsets 0x10-0x1F */
	buf[4] = OLMSG_HEADER_SIZE + OLMSG_RING_SIZE;	/* data_offset: 0x7820 */
	buf[5] = OLMSG_RING_SIZE;	/* size: 30KB */
	buf[6] = 0;			/* read_ptr */
	buf[7] = 0;			/* write_ptr */

	dev_info(&dev->pdev->dev,
		 "olmsg buffer: virt=%px dma=0x%llx size=0x%x\n",
		 dev->olmsg_buf, (u64)dev->olmsg_dma, OLMSG_BUF_SIZE);
}

/* ---- Shared info structure in TCM ---- */

static void write_shared_info(struct bcm4360_dev *dev)
{
	u32 base = SHARED_INFO_OFFSET;

	dev_info(&dev->pdev->dev,
		 "Writing shared_info at TCM offset 0x%x (ramsize 0x%x - 0x2F5C)\n",
		 base, TCM_RAMSIZE);

	/* Clear the shared info region first */
	{
		u32 i;
		for (i = 0; i < SHARED_INFO_SIZE / 4; i++)
			tcm_write32(dev, base + i * 4, 0);
	}

	/* Magic start */
	tcm_write32(dev, base + SI_MAGIC_START, SHARED_MAGIC_START);

	/* olmsg DMA physical address */
	tcm_write32(dev, base + SI_OLMSG_PHYS_LO, lower_32_bits(dev->olmsg_dma));
	tcm_write32(dev, base + SI_OLMSG_PHYS_HI, upper_32_bits(dev->olmsg_dma));

	/* olmsg buffer size */
	tcm_write32(dev, base + SI_OLMSG_SIZE, OLMSG_BUF_SIZE);

	/* Clear init fields */
	tcm_write32(dev, base + SI_FIELD_14, 0);
	tcm_write32(dev, base + SI_FIELD_18, 0);

	/* Clear fw_init_done flag */
	tcm_write32(dev, base + SI_FW_INIT_DONE, 0);

	/* Magic end */
	tcm_write32(dev, base + SI_MAGIC_END, SHARED_MAGIC_END);

	/* Verify magics */
	{
		u32 m_start = tcm_read32(dev, base + SI_MAGIC_START);
		u32 m_end = tcm_read32(dev, base + SI_MAGIC_END);

		dev_info(&dev->pdev->dev,
			 "shared_info: magic_start=0x%08x magic_end=0x%08x\n",
			 m_start, m_end);
	}
}

/* ---- Interrupt handler ---- */

static irqreturn_t bcm4360_isr(int irq, void *data)
{
	struct bcm4360_dev *dev = data;

	dev->irq_count++;

	/* Just log — don't do anything complex in ISR for this test */
	if (dev->irq_count <= 10)
		dev_info(&dev->pdev->dev, "IRQ #%d received\n", dev->irq_count);
	else if (dev->irq_count == 11)
		dev_info(&dev->pdev->dev, "IRQ suppressing further logs...\n");

	return IRQ_HANDLED;
}

/* ---- Main test sequence ---- */

static int bcm4360_run_test(struct bcm4360_dev *dev)
{
	u32 val;
	int i, ret;
	bool irq_registered = false;

	dev_info(&dev->pdev->dev, "=== BCM4360 test: max_step=%d ===\n", max_step);

	/* Step 0: Read chip ID via BAR0 only — no BAR2 access */
	dev_info(&dev->pdev->dev, "[step 0] Reading chip ID via BAR0...\n");
	val = ioread32(dev->regs);
	dev_info(&dev->pdev->dev, "[step 0] BAR0[0x00] = 0x%08x (expect 0x43a0 in low 16 bits)\n", val);
	dev_info(&dev->pdev->dev, "[step 0] DONE — BAR0 MMIO OK\n");

	if (max_step < 1)
		return 0;

	/* Step 1: Map BAR2 (TCM) + halt ARM via backplane */
	dev_info(&dev->pdev->dev, "[step 1] Mapping BAR2 (TCM, %dKB)...\n", BAR2_SIZE / 1024);
	dev->tcm = pci_iomap(dev->pdev, 2, BAR2_SIZE);
	if (!dev->tcm) {
		dev_err(&dev->pdev->dev, "Failed to map BAR2\n");
		return -ENOMEM;
	}
	dev_info(&dev->pdev->dev, "[step 1] BAR2 mapped at %px\n", dev->tcm);

	/* Read a TCM word to verify */
	val = tcm_read32(dev, 0);
	dev_info(&dev->pdev->dev, "[step 1] TCM[0x00] = 0x%08x\n", val);

	/* Allocate DMA buffer for olmsg */
	dev->olmsg_buf = dma_alloc_coherent(&dev->pdev->dev, OLMSG_BUF_SIZE,
					    &dev->olmsg_dma, GFP_KERNEL);
	if (!dev->olmsg_buf) {
		dev_err(&dev->pdev->dev, "Failed to allocate olmsg DMA buffer\n");
		return -ENOMEM;
	}

	dev_info(&dev->pdev->dev, "[step 1] Halting ARM CR4...\n");
	arm_halt(dev);
	dev_info(&dev->pdev->dev, "[step 1] DONE\n");

	if (max_step < 2)
		return 0;

	/* Step 2: Download firmware to TCM */
	dev_info(&dev->pdev->dev, "[step 2] Downloading firmware...\n");
	ret = download_firmware(dev);
	if (ret)
		return ret;
	dev_info(&dev->pdev->dev, "[step 2] DONE\n");

	if (max_step < 3)
		return 0;

	/* Step 3: Set up olmsg + shared_info */
	dev_info(&dev->pdev->dev, "[step 3] Setting up olmsg + shared_info...\n");
	setup_olmsg(dev);
	write_shared_info(dev);
	dev_info(&dev->pdev->dev, "[step 3] DONE\n");

	if (max_step < 4)
		return 0;

	/* Step 4: Disable bus mastering + register IRQ */
	dev_info(&dev->pdev->dev, "[step 4] Disabling bus mastering...\n");
	pci_clear_master(dev->pdev);

	dev_info(&dev->pdev->dev, "[step 4] Registering IRQ handler...\n");
	ret = request_irq(dev->pdev->irq, bcm4360_isr, IRQF_SHARED,
			  DRV_NAME, dev);
	if (ret) {
		dev_err(&dev->pdev->dev, "Failed to register IRQ %d: %d\n",
			dev->pdev->irq, ret);
		return ret;
	}
	irq_registered = true;
	dev_info(&dev->pdev->dev, "[step 4] DONE — IRQ %d registered\n", dev->pdev->irq);

	if (max_step < 5)
		goto cleanup_irq;

	/* Step 5: Release ARM (DANGEROUS — Phase 3 crashed here) */
	dev_info(&dev->pdev->dev, "[step 5] *** RELEASING ARM CR4 — bus mastering OFF ***\n");
	arm_release(dev);
	dev_info(&dev->pdev->dev, "[step 5] ARM released — if you see this, no immediate crash\n");
	/* Small delay to let ARM start executing */
	msleep(100);
	dev_info(&dev->pdev->dev, "[step 5] 100ms after ARM release — still alive\n");
	dev_info(&dev->pdev->dev, "[step 5] DONE\n");

	if (max_step < 6)
		goto cleanup_irq;

	/* Step 6: Re-enable bus mastering + poll fw_init_done */
	dev_info(&dev->pdev->dev, "[step 6] Re-enabling bus mastering...\n");
	pci_set_master(dev->pdev);
	dev_info(&dev->pdev->dev, "[step 6] Bus mastering ON — if you see this, no DMA crash\n");

	/* Poll for firmware init completion */
	dev_info(&dev->pdev->dev, "[step 6] Polling fw_init_done...\n");

	for (i = 0; i < FW_INIT_TIMEOUT_MS / FW_INIT_POLL_MS; i++) {
		val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_FW_INIT_DONE);
		if (val != 0) {
			dev_info(&dev->pdev->dev,
				 "*** FW INIT SUCCESS *** fw_init_done=0x%08x after %d ms\n",
				 val, i);
			goto init_done;
		}
		usleep_range(1000, 1500);
	}

	/* Timeout — dump diagnostics */
	val = tcm_read32(dev, SHARED_INFO_OFFSET + SI_FW_INIT_DONE);
	dev_err(&dev->pdev->dev,
		"FW init TIMEOUT after %d ms (fw_init_done=0x%08x)\n",
		FW_INIT_TIMEOUT_MS, val);

	{
		u32 m_start = tcm_read32(dev, SHARED_INFO_OFFSET + SI_MAGIC_START);
		u32 m_end = tcm_read32(dev, SHARED_INFO_OFFSET + SI_MAGIC_END);

		dev_info(&dev->pdev->dev,
			 "shared_info post-check: magic_start=0x%08x magic_end=0x%08x\n",
			 m_start, m_end);
	}

	dev_info(&dev->pdev->dev, "TCM[0x00]=0x%08x TCM[0x04]=0x%08x TCM[0x08]=0x%08x\n",
		 tcm_read32(dev, 0), tcm_read32(dev, 4), tcm_read32(dev, 8));

	{
		u32 *buf = dev->olmsg_buf;
		dev_info(&dev->pdev->dev,
			 "olmsg ring1 (fw->host): write_ptr=%u read_ptr=%u\n",
			 buf[7], buf[6]);
	}

	dev_info(&dev->pdev->dev, "Total IRQs received: %d\n", dev->irq_count);
	goto cleanup_irq;

init_done:
	{
		u32 *buf = dev->olmsg_buf;
		dev_info(&dev->pdev->dev,
			 "olmsg ring0 (host->fw): write_ptr=%u read_ptr=%u\n",
			 buf[3], buf[2]);
		dev_info(&dev->pdev->dev,
			 "olmsg ring1 (fw->host): write_ptr=%u read_ptr=%u\n",
			 buf[7], buf[6]);
	}
	dev_info(&dev->pdev->dev, "Total IRQs received: %d\n", dev->irq_count);
	arm_halt(dev);

cleanup_irq:
	if (irq_registered)
		free_irq(dev->pdev->irq, dev);
	return 0;
}

/* ---- PCI driver callbacks ---- */

static int bcm4360_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	struct bcm4360_dev *dev;
	int ret;

	dev_info(&pdev->dev, "BCM4360 test module probe\n");

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

	/* Disable bus mastering immediately — wl may have left it on */
	pci_clear_master(pdev);

	/* Try to reset the PCI function to clear any state from wl */
	ret = pci_reset_function(pdev);
	if (ret)
		dev_warn(&pdev->dev, "pci_reset_function failed: %d (non-fatal)\n", ret);
	else
		dev_info(&pdev->dev, "PCI function reset OK\n");

	/* Re-enable after reset */
	ret = pci_enable_device(pdev);
	if (ret) {
		dev_err(&pdev->dev, "pci_enable_device after reset failed: %d\n", ret);
		goto err_free;
	}

	ret = dma_set_mask_and_coherent(&pdev->dev, DMA_BIT_MASK(32));
	if (ret) {
		dev_err(&pdev->dev, "DMA mask failed: %d\n", ret);
		goto err_disable;
	}

	/* Map BAR0 only at probe — BAR2 (TCM) is deferred to avoid crash */
	dev->regs = pci_iomap(pdev, 0, BAR0_SIZE);
	if (!dev->regs) {
		dev_err(&pdev->dev, "Failed to map BAR0\n");
		ret = -ENOMEM;
		goto err_disable;
	}
	dev_info(&pdev->dev, "BAR0 mapped at %px (32KB)\n", dev->regs);

	/* Run the test — BAR2 and DMA are mapped inside if needed */
	ret = bcm4360_run_test(dev);

	/* Keep module loaded even on failure so dmesg can be inspected */
	dev_info(&pdev->dev, "Test complete, result: %d\n", ret);
	return 0;

err_disable:
	pci_disable_device(pdev);
err_free:
	kfree(dev);
	return ret;
}

static void bcm4360_remove(struct pci_dev *pdev)
{
	struct bcm4360_dev *dev = pci_get_drvdata(pdev);

	dev_info(&pdev->dev, "BCM4360 test module remove\n");

	/* Halt ARM for clean state (only if TCM was mapped) */
	if (dev->tcm)
		arm_halt(dev);

	if (dev->olmsg_buf)
		dma_free_coherent(&pdev->dev, OLMSG_BUF_SIZE,
				  dev->olmsg_buf, dev->olmsg_dma);
	if (dev->tcm)
		pci_iounmap(pdev, dev->tcm);
	pci_iounmap(pdev, dev->regs);
	pci_disable_device(pdev);
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
