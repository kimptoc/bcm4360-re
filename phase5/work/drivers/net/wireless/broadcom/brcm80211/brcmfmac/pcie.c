// SPDX-License-Identifier: ISC
/*
 * Copyright (c) 2014 Broadcom Corporation
 */

#include <linux/kernel.h>
#include <linux/module.h>
#include <linux/firmware.h>
#include <linux/pci.h>
#include <linux/vmalloc.h>
#include <linux/delay.h>
#include <linux/interrupt.h>
#include <linux/bcma/bcma.h>
#include <linux/sched.h>
#include <linux/sched/signal.h>
#include <linux/kthread.h>
#include <linux/io.h>
#include <linux/random.h>
#include <linux/unaligned.h>

#include <soc.h>
#include <chipcommon.h>
#include <brcmu_utils.h>
#include <brcmu_wifi.h>
#include <brcm_hw_ids.h>

/* Custom brcmf_err() that takes bus arg and passes it further */
#define brcmf_err(bus, fmt, ...)					\
	do {								\
		if (IS_ENABLED(CONFIG_BRCMDBG) ||			\
		    IS_ENABLED(CONFIG_BRCM_TRACING) ||			\
		    net_ratelimit())					\
			__brcmf_err(bus, __func__, fmt, ##__VA_ARGS__);	\
	} while (0)

#include "debug.h"
#include "bus.h"
#include "commonring.h"
#include "msgbuf.h"
#include "pcie.h"
#include "firmware.h"
#include "chip.h"
#include "core.h"
#include "common.h"


enum brcmf_pcie_state {
	BRCMFMAC_PCIE_STATE_DOWN,
	BRCMFMAC_PCIE_STATE_UP
};

BRCMF_FW_DEF(4360, "brcmfmac4360-pcie");
BRCMF_FW_DEF(43602, "brcmfmac43602-pcie");
BRCMF_FW_DEF(4350, "brcmfmac4350-pcie");
BRCMF_FW_DEF(4350C, "brcmfmac4350c2-pcie");
BRCMF_FW_CLM_DEF(4355, "brcmfmac4355-pcie");
BRCMF_FW_CLM_DEF(4355C1, "brcmfmac4355c1-pcie");
BRCMF_FW_CLM_DEF(4356, "brcmfmac4356-pcie");
BRCMF_FW_CLM_DEF(43570, "brcmfmac43570-pcie");
BRCMF_FW_DEF(4358, "brcmfmac4358-pcie");
BRCMF_FW_DEF(4359, "brcmfmac4359-pcie");
BRCMF_FW_DEF(4359C, "brcmfmac4359c-pcie");
BRCMF_FW_CLM_DEF(4364B2, "brcmfmac4364b2-pcie");
BRCMF_FW_CLM_DEF(4364B3, "brcmfmac4364b3-pcie");
BRCMF_FW_DEF(4365B, "brcmfmac4365b-pcie");
BRCMF_FW_DEF(4365C, "brcmfmac4365c-pcie");
BRCMF_FW_DEF(4366B, "brcmfmac4366b-pcie");
BRCMF_FW_DEF(4366C, "brcmfmac4366c-pcie");
BRCMF_FW_DEF(4371, "brcmfmac4371-pcie");
BRCMF_FW_CLM_DEF(4377B3, "brcmfmac4377b3-pcie");
BRCMF_FW_CLM_DEF(4378B1, "brcmfmac4378b1-pcie");
BRCMF_FW_CLM_DEF(4378B3, "brcmfmac4378b3-pcie");
BRCMF_FW_CLM_DEF(4387C2, "brcmfmac4387c2-pcie");

/* firmware config files */
MODULE_FIRMWARE(BRCMF_FW_DEFAULT_PATH "brcmfmac*-pcie.txt");
MODULE_FIRMWARE(BRCMF_FW_DEFAULT_PATH "brcmfmac*-pcie.*.txt");

/* BCM4360 debug: skip ARM release to safely test firmware download without crash */
static int bcm4360_skip_arm;
module_param(bcm4360_skip_arm, int, 0644);
MODULE_PARM_DESC(bcm4360_skip_arm, "BCM4360: skip ARM release (1=skip, 0=normal)");

/* BCM4360 debug: test.20 — staged reset to isolate crashing register write.
 * stage=0: read-only (dump ARM CR4 wrapper registers)
 * stage=1: write IOCTL = FGC|CLK (coredisable in_reset_configure step)
 * stage=2: stage 1 + write RESET_CTL = 0 (clear reset)
 * stage=3: stage 2 + write IOCTL = CPUHALT|CLK (final config) */
static int bcm4360_reset_stage = -1;
module_param(bcm4360_reset_stage, int, 0644);
MODULE_PARM_DESC(bcm4360_reset_stage, "BCM4360: staged reset (0=read-only, 1=IOCTL, 2=+RESET_CTL, 3=+final IOCTL)");

/* per-board firmware binaries */
MODULE_FIRMWARE(BRCMF_FW_DEFAULT_PATH "brcmfmac*-pcie.*.bin");
MODULE_FIRMWARE(BRCMF_FW_DEFAULT_PATH "brcmfmac*-pcie.*.clm_blob");
MODULE_FIRMWARE(BRCMF_FW_DEFAULT_PATH "brcmfmac*-pcie.*.txcap_blob");

static const struct brcmf_firmware_mapping brcmf_pcie_fwnames[] = {
	BRCMF_FW_ENTRY(BRCM_CC_4360_CHIP_ID, 0xFFFFFFFF, 4360),
	BRCMF_FW_ENTRY(BRCM_CC_43602_CHIP_ID, 0xFFFFFFFF, 43602),
	BRCMF_FW_ENTRY(BRCM_CC_43465_CHIP_ID, 0xFFFFFFF0, 4366C),
	BRCMF_FW_ENTRY(BRCM_CC_4350_CHIP_ID, 0x000000FF, 4350C),
	BRCMF_FW_ENTRY(BRCM_CC_4350_CHIP_ID, 0xFFFFFF00, 4350),
	BRCMF_FW_ENTRY(BRCM_CC_43525_CHIP_ID, 0xFFFFFFF0, 4365C),
	BRCMF_FW_ENTRY(BRCM_CC_4355_CHIP_ID, 0x000007FF, 4355),
	BRCMF_FW_ENTRY(BRCM_CC_4355_CHIP_ID, 0xFFFFF800, 4355C1), /* rev ID 12/C2 seen */
	BRCMF_FW_ENTRY(BRCM_CC_4356_CHIP_ID, 0xFFFFFFFF, 4356),
	BRCMF_FW_ENTRY(BRCM_CC_43567_CHIP_ID, 0xFFFFFFFF, 43570),
	BRCMF_FW_ENTRY(BRCM_CC_43569_CHIP_ID, 0xFFFFFFFF, 43570),
	BRCMF_FW_ENTRY(BRCM_CC_43570_CHIP_ID, 0xFFFFFFFF, 43570),
	BRCMF_FW_ENTRY(BRCM_CC_4358_CHIP_ID, 0xFFFFFFFF, 4358),
	BRCMF_FW_ENTRY(BRCM_CC_4359_CHIP_ID, 0x000001FF, 4359),
	BRCMF_FW_ENTRY(BRCM_CC_4359_CHIP_ID, 0xFFFFFE00, 4359C),
	BRCMF_FW_ENTRY(BRCM_CC_4364_CHIP_ID, 0x0000000F, 4364B2), /* 3 */
	BRCMF_FW_ENTRY(BRCM_CC_4364_CHIP_ID, 0xFFFFFFF0, 4364B3), /* 4 */
	BRCMF_FW_ENTRY(BRCM_CC_4365_CHIP_ID, 0x0000000F, 4365B),
	BRCMF_FW_ENTRY(BRCM_CC_4365_CHIP_ID, 0xFFFFFFF0, 4365C),
	BRCMF_FW_ENTRY(BRCM_CC_4366_CHIP_ID, 0x0000000F, 4366B),
	BRCMF_FW_ENTRY(BRCM_CC_4366_CHIP_ID, 0xFFFFFFF0, 4366C),
	BRCMF_FW_ENTRY(BRCM_CC_43664_CHIP_ID, 0xFFFFFFF0, 4366C),
	BRCMF_FW_ENTRY(BRCM_CC_43666_CHIP_ID, 0xFFFFFFF0, 4366C),
	BRCMF_FW_ENTRY(BRCM_CC_4371_CHIP_ID, 0xFFFFFFFF, 4371),
	BRCMF_FW_ENTRY(BRCM_CC_4377_CHIP_ID, 0xFFFFFFFF, 4377B3), /* revision ID 4 */
	BRCMF_FW_ENTRY(BRCM_CC_4378_CHIP_ID, 0x0000000F, 4378B1), /* revision ID 3 */
	BRCMF_FW_ENTRY(BRCM_CC_4378_CHIP_ID, 0xFFFFFFE0, 4378B3), /* revision ID 5 */
	BRCMF_FW_ENTRY(BRCM_CC_4387_CHIP_ID, 0xFFFFFFFF, 4387C2), /* revision ID 7 */
};

#define BRCMF_PCIE_FW_UP_TIMEOUT		5000 /* msec */

#define BRCMF_PCIE_REG_MAP_SIZE			(32 * 1024)

/* backplane addres space accessed by BAR0 */
#define	BRCMF_PCIE_BAR0_WINDOW			0x80
#define BRCMF_PCIE_BAR0_REG_SIZE		0x1000
#define	BRCMF_PCIE_BAR0_WRAPPERBASE		0x70

#define BRCMF_PCIE_BAR0_WRAPBASE_DMP_OFFSET	0x1000
#define BRCMF_PCIE_BARO_PCIE_ENUM_OFFSET	0x2000

#define BRCMF_PCIE_ARMCR4REG_BANKIDX		0x40
#define BRCMF_PCIE_ARMCR4REG_BANKPDA		0x4C

/* ARM CR4 IOCTL flags (from chip.c, needed for test.19 halt_only) */
#define ARMCR4_BCMA_IOCTL_CPUHALT		0x0020

#define BRCMF_PCIE_REG_INTSTATUS		0x90
#define BRCMF_PCIE_REG_INTMASK			0x94
#define BRCMF_PCIE_REG_SBMBX			0x98

#define BRCMF_PCIE_REG_LINK_STATUS_CTRL		0xBC

#define BRCMF_PCIE_PCIE2REG_INTMASK		0x24
#define BRCMF_PCIE_PCIE2REG_MAILBOXINT		0x48
#define BRCMF_PCIE_PCIE2REG_MAILBOXMASK		0x4C
#define BRCMF_PCIE_PCIE2REG_CONFIGADDR		0x120
#define BRCMF_PCIE_PCIE2REG_CONFIGDATA		0x124
#define BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0	0x140
#define BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1	0x144

#define BRCMF_PCIE_64_PCIE2REG_INTMASK		0xC14
#define BRCMF_PCIE_64_PCIE2REG_MAILBOXINT	0xC30
#define BRCMF_PCIE_64_PCIE2REG_MAILBOXMASK	0xC34
#define BRCMF_PCIE_64_PCIE2REG_H2D_MAILBOX_0	0xA20
#define BRCMF_PCIE_64_PCIE2REG_H2D_MAILBOX_1	0xA24

#define BRCMF_PCIE2_INTA			0x01
#define BRCMF_PCIE2_INTB			0x02

#define BRCMF_PCIE_INT_0			0x01
#define BRCMF_PCIE_INT_1			0x02
#define BRCMF_PCIE_INT_DEF			(BRCMF_PCIE_INT_0 | \
						 BRCMF_PCIE_INT_1)

#define BRCMF_PCIE_MB_INT_FN0_0			0x0100
#define BRCMF_PCIE_MB_INT_FN0_1			0x0200
#define	BRCMF_PCIE_MB_INT_D2H0_DB0		0x10000
#define	BRCMF_PCIE_MB_INT_D2H0_DB1		0x20000
#define	BRCMF_PCIE_MB_INT_D2H1_DB0		0x40000
#define	BRCMF_PCIE_MB_INT_D2H1_DB1		0x80000
#define	BRCMF_PCIE_MB_INT_D2H2_DB0		0x100000
#define	BRCMF_PCIE_MB_INT_D2H2_DB1		0x200000
#define	BRCMF_PCIE_MB_INT_D2H3_DB0		0x400000
#define	BRCMF_PCIE_MB_INT_D2H3_DB1		0x800000

#define BRCMF_PCIE_MB_INT_FN0			(BRCMF_PCIE_MB_INT_FN0_0 | \
						 BRCMF_PCIE_MB_INT_FN0_1)
#define BRCMF_PCIE_MB_INT_D2H_DB		(BRCMF_PCIE_MB_INT_D2H0_DB0 | \
						 BRCMF_PCIE_MB_INT_D2H0_DB1 | \
						 BRCMF_PCIE_MB_INT_D2H1_DB0 | \
						 BRCMF_PCIE_MB_INT_D2H1_DB1 | \
						 BRCMF_PCIE_MB_INT_D2H2_DB0 | \
						 BRCMF_PCIE_MB_INT_D2H2_DB1 | \
						 BRCMF_PCIE_MB_INT_D2H3_DB0 | \
						 BRCMF_PCIE_MB_INT_D2H3_DB1)

#define	BRCMF_PCIE_64_MB_INT_D2H0_DB0		0x1
#define	BRCMF_PCIE_64_MB_INT_D2H0_DB1		0x2
#define	BRCMF_PCIE_64_MB_INT_D2H1_DB0		0x4
#define	BRCMF_PCIE_64_MB_INT_D2H1_DB1		0x8
#define	BRCMF_PCIE_64_MB_INT_D2H2_DB0		0x10
#define	BRCMF_PCIE_64_MB_INT_D2H2_DB1		0x20
#define	BRCMF_PCIE_64_MB_INT_D2H3_DB0		0x40
#define	BRCMF_PCIE_64_MB_INT_D2H3_DB1		0x80
#define	BRCMF_PCIE_64_MB_INT_D2H4_DB0		0x100
#define	BRCMF_PCIE_64_MB_INT_D2H4_DB1		0x200
#define	BRCMF_PCIE_64_MB_INT_D2H5_DB0		0x400
#define	BRCMF_PCIE_64_MB_INT_D2H5_DB1		0x800
#define	BRCMF_PCIE_64_MB_INT_D2H6_DB0		0x1000
#define	BRCMF_PCIE_64_MB_INT_D2H6_DB1		0x2000
#define	BRCMF_PCIE_64_MB_INT_D2H7_DB0		0x4000
#define	BRCMF_PCIE_64_MB_INT_D2H7_DB1		0x8000

#define BRCMF_PCIE_64_MB_INT_D2H_DB		(BRCMF_PCIE_64_MB_INT_D2H0_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H0_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H1_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H1_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H2_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H2_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H3_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H3_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H4_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H4_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H5_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H5_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H6_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H6_DB1 | \
						 BRCMF_PCIE_64_MB_INT_D2H7_DB0 | \
						 BRCMF_PCIE_64_MB_INT_D2H7_DB1)

#define BRCMF_PCIE_SHARED_VERSION_7		7
#define BRCMF_PCIE_MIN_SHARED_VERSION		5
#define BRCMF_PCIE_MAX_SHARED_VERSION		BRCMF_PCIE_SHARED_VERSION_7
#define BRCMF_PCIE_SHARED_VERSION_MASK		0x00FF
#define BRCMF_PCIE_SHARED_DMA_INDEX		0x10000
#define BRCMF_PCIE_SHARED_DMA_2B_IDX		0x100000
#define BRCMF_PCIE_SHARED_HOSTRDY_DB1		0x10000000

#define BRCMF_PCIE_FLAGS_HTOD_SPLIT		0x4000
#define BRCMF_PCIE_FLAGS_DTOH_SPLIT		0x8000

#define BRCMF_SHARED_MAX_RXBUFPOST_OFFSET	34
#define BRCMF_SHARED_RING_BASE_OFFSET		52
#define BRCMF_SHARED_RX_DATAOFFSET_OFFSET	36
#define BRCMF_SHARED_CONSOLE_ADDR_OFFSET	20
#define BRCMF_SHARED_HTOD_MB_DATA_ADDR_OFFSET	40
#define BRCMF_SHARED_DTOH_MB_DATA_ADDR_OFFSET	44
#define BRCMF_SHARED_RING_INFO_ADDR_OFFSET	48
#define BRCMF_SHARED_DMA_SCRATCH_LEN_OFFSET	52
#define BRCMF_SHARED_DMA_SCRATCH_ADDR_OFFSET	56
#define BRCMF_SHARED_DMA_RINGUPD_LEN_OFFSET	64
#define BRCMF_SHARED_DMA_RINGUPD_ADDR_OFFSET	68

#define BRCMF_RING_H2D_RING_COUNT_OFFSET	0
#define BRCMF_RING_D2H_RING_COUNT_OFFSET	1
#define BRCMF_RING_H2D_RING_MEM_OFFSET		4
#define BRCMF_RING_H2D_RING_STATE_OFFSET	8

#define BRCMF_RING_MEM_BASE_ADDR_OFFSET		8
#define BRCMF_RING_MAX_ITEM_OFFSET		4
#define BRCMF_RING_LEN_ITEMS_OFFSET		6
#define BRCMF_RING_MEM_SZ			16
#define BRCMF_RING_STATE_SZ			8

#define BRCMF_DEF_MAX_RXBUFPOST			255

#define BRCMF_CONSOLE_BUFADDR_OFFSET		8
#define BRCMF_CONSOLE_BUFSIZE_OFFSET		12
#define BRCMF_CONSOLE_WRITEIDX_OFFSET		16

#define BRCMF_DMA_D2H_SCRATCH_BUF_LEN		8
#define BRCMF_DMA_D2H_RINGUPD_BUF_LEN		1024

#define BRCMF_D2H_DEV_D3_ACK			0x00000001
#define BRCMF_D2H_DEV_DS_ENTER_REQ		0x00000002
#define BRCMF_D2H_DEV_DS_EXIT_NOTE		0x00000004
#define BRCMF_D2H_DEV_FWHALT			0x10000000

#define BRCMF_H2D_HOST_D3_INFORM		0x00000001
#define BRCMF_H2D_HOST_DS_ACK			0x00000002
#define BRCMF_H2D_HOST_D0_INFORM_IN_USE		0x00000008
#define BRCMF_H2D_HOST_D0_INFORM		0x00000010

#define BRCMF_PCIE_MBDATA_TIMEOUT		msecs_to_jiffies(2000)

#define BRCMF_PCIE_CFGREG_STATUS_CMD		0x4
#define BRCMF_PCIE_CFGREG_PM_CSR		0x4C
#define BRCMF_PCIE_CFGREG_MSI_CAP		0x58
#define BRCMF_PCIE_CFGREG_MSI_MSGCTL		0x5A
#define BRCMF_PCIE_CFGREG_MSI_ADDR_L		0x5C
#define BRCMF_PCIE_CFGREG_MSI_ADDR_H		0x60
#define BRCMF_PCIE_CFGREG_MSI_DATA		0x64
#define BRCMF_PCIE_CFGREG_LINK_STATUS_CTRL	0xBC
#define BRCMF_PCIE_CFGREG_LINK_STATUS_CTRL2	0xDC
#define BRCMF_PCIE_CFGREG_RBAR_CTRL		0x228
#define BRCMF_PCIE_CFGREG_PML1_SUB_CTRL1	0x248
#define BRCMF_PCIE_CFGREG_REG_BAR2_CONFIG	0x4E0
#define BRCMF_PCIE_CFGREG_REG_BAR3_CONFIG	0x4F4
#define BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB	3

/* Magic number at a magic location to find RAM size */
#define BRCMF_RAMSIZE_MAGIC			0x534d4152	/* SMAR */
#define BRCMF_RAMSIZE_OFFSET			0x6c


struct brcmf_pcie_console {
	u32 base_addr;
	u32 buf_addr;
	u32 bufsize;
	u32 read_idx;
	u8 log_str[256];
	u8 log_idx;
};

struct brcmf_pcie_shared_info {
	u32 tcm_base_address;
	u32 flags;
	struct brcmf_pcie_ringbuf *commonrings[BRCMF_NROF_COMMON_MSGRINGS];
	struct brcmf_pcie_ringbuf *flowrings;
	u16 max_rxbufpost;
	u16 max_flowrings;
	u16 max_submissionrings;
	u16 max_completionrings;
	u32 rx_dataoffset;
	u32 htod_mb_data_addr;
	u32 dtoh_mb_data_addr;
	u32 ring_info_addr;
	struct brcmf_pcie_console console;
	void *scratch;
	dma_addr_t scratch_dmahandle;
	void *ringupd;
	dma_addr_t ringupd_dmahandle;
	u8 version;
};

#define BRCMF_OTP_MAX_PARAM_LEN 16

struct brcmf_otp_params {
	char module[BRCMF_OTP_MAX_PARAM_LEN];
	char vendor[BRCMF_OTP_MAX_PARAM_LEN];
	char version[BRCMF_OTP_MAX_PARAM_LEN];
	bool valid;
};

struct brcmf_pciedev_info {
	enum brcmf_pcie_state state;
	bool in_irq;
	struct pci_dev *pdev;
	char fw_name[BRCMF_FW_NAME_LEN];
	char nvram_name[BRCMF_FW_NAME_LEN];
	char clm_name[BRCMF_FW_NAME_LEN];
	char txcap_name[BRCMF_FW_NAME_LEN];
	const struct firmware *clm_fw;
	const struct firmware *txcap_fw;
	const struct brcmf_pcie_reginfo *reginfo;
	void __iomem *regs;
	void __iomem *tcm;
	u32 ram_base;
	u32 ram_size;
	struct brcmf_chip *ci;
	u32 coreid;
	struct brcmf_pcie_shared_info shared;
	wait_queue_head_t mbdata_resp_wait;
	bool mbdata_completed;
	bool irq_allocated;
	bool wowl_enabled;
	u8 dma_idx_sz;
	void *idxbuf;
	u32 idxbuf_sz;
	dma_addr_t idxbuf_dmahandle;
	u16 (*read_ptr)(struct brcmf_pciedev_info *devinfo, u32 mem_offset);
	void (*write_ptr)(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
			  u16 value);
	struct brcmf_mp_device *settings;
	struct brcmf_otp_params otp;
#ifdef DEBUG
	u32 console_interval;
	bool console_active;
	struct timer_list timer;
#endif
};

struct brcmf_pcie_ringbuf {
	struct brcmf_commonring commonring;
	dma_addr_t dma_handle;
	u32 w_idx_addr;
	u32 r_idx_addr;
	struct brcmf_pciedev_info *devinfo;
	u8 id;
};

/**
 * struct brcmf_pcie_dhi_ringinfo - dongle/host interface shared ring info
 *
 * @ringmem: dongle memory pointer to ring memory location
 * @h2d_w_idx_ptr: h2d ring write indices dongle memory pointers
 * @h2d_r_idx_ptr: h2d ring read indices dongle memory pointers
 * @d2h_w_idx_ptr: d2h ring write indices dongle memory pointers
 * @d2h_r_idx_ptr: d2h ring read indices dongle memory pointers
 * @h2d_w_idx_hostaddr: h2d ring write indices host memory pointers
 * @h2d_r_idx_hostaddr: h2d ring read indices host memory pointers
 * @d2h_w_idx_hostaddr: d2h ring write indices host memory pointers
 * @d2h_r_idx_hostaddr: d2h ring reaD indices host memory pointers
 * @max_flowrings: maximum number of tx flow rings supported.
 * @max_submissionrings: maximum number of submission rings(h2d) supported.
 * @max_completionrings: maximum number of completion rings(d2h) supported.
 */
struct brcmf_pcie_dhi_ringinfo {
	__le32			ringmem;
	__le32			h2d_w_idx_ptr;
	__le32			h2d_r_idx_ptr;
	__le32			d2h_w_idx_ptr;
	__le32			d2h_r_idx_ptr;
	struct msgbuf_buf_addr	h2d_w_idx_hostaddr;
	struct msgbuf_buf_addr	h2d_r_idx_hostaddr;
	struct msgbuf_buf_addr	d2h_w_idx_hostaddr;
	struct msgbuf_buf_addr	d2h_r_idx_hostaddr;
	__le16			max_flowrings;
	__le16			max_submissionrings;
	__le16			max_completionrings;
};

static const u32 brcmf_ring_max_item[BRCMF_NROF_COMMON_MSGRINGS] = {
	BRCMF_H2D_MSGRING_CONTROL_SUBMIT_MAX_ITEM,
	BRCMF_H2D_MSGRING_RXPOST_SUBMIT_MAX_ITEM,
	BRCMF_D2H_MSGRING_CONTROL_COMPLETE_MAX_ITEM,
	BRCMF_D2H_MSGRING_TX_COMPLETE_MAX_ITEM,
	BRCMF_D2H_MSGRING_RX_COMPLETE_MAX_ITEM
};

static const u32 brcmf_ring_itemsize_pre_v7[BRCMF_NROF_COMMON_MSGRINGS] = {
	BRCMF_H2D_MSGRING_CONTROL_SUBMIT_ITEMSIZE,
	BRCMF_H2D_MSGRING_RXPOST_SUBMIT_ITEMSIZE,
	BRCMF_D2H_MSGRING_CONTROL_COMPLETE_ITEMSIZE,
	BRCMF_D2H_MSGRING_TX_COMPLETE_ITEMSIZE_PRE_V7,
	BRCMF_D2H_MSGRING_RX_COMPLETE_ITEMSIZE_PRE_V7
};

static const u32 brcmf_ring_itemsize[BRCMF_NROF_COMMON_MSGRINGS] = {
	BRCMF_H2D_MSGRING_CONTROL_SUBMIT_ITEMSIZE,
	BRCMF_H2D_MSGRING_RXPOST_SUBMIT_ITEMSIZE,
	BRCMF_D2H_MSGRING_CONTROL_COMPLETE_ITEMSIZE,
	BRCMF_D2H_MSGRING_TX_COMPLETE_ITEMSIZE,
	BRCMF_D2H_MSGRING_RX_COMPLETE_ITEMSIZE
};

struct brcmf_pcie_reginfo {
	u32 intmask;
	u32 mailboxint;
	u32 mailboxmask;
	u32 h2d_mailbox_0;
	u32 h2d_mailbox_1;
	u32 int_d2h_db;
	u32 int_fn0;
};

static const struct brcmf_pcie_reginfo brcmf_reginfo_default = {
	.intmask = BRCMF_PCIE_PCIE2REG_INTMASK,
	.mailboxint = BRCMF_PCIE_PCIE2REG_MAILBOXINT,
	.mailboxmask = BRCMF_PCIE_PCIE2REG_MAILBOXMASK,
	.h2d_mailbox_0 = BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0,
	.h2d_mailbox_1 = BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1,
	.int_d2h_db = BRCMF_PCIE_MB_INT_D2H_DB,
	.int_fn0 = BRCMF_PCIE_MB_INT_FN0,
};

static const struct brcmf_pcie_reginfo brcmf_reginfo_64 = {
	.intmask = BRCMF_PCIE_64_PCIE2REG_INTMASK,
	.mailboxint = BRCMF_PCIE_64_PCIE2REG_MAILBOXINT,
	.mailboxmask = BRCMF_PCIE_64_PCIE2REG_MAILBOXMASK,
	.h2d_mailbox_0 = BRCMF_PCIE_64_PCIE2REG_H2D_MAILBOX_0,
	.h2d_mailbox_1 = BRCMF_PCIE_64_PCIE2REG_H2D_MAILBOX_1,
	.int_d2h_db = BRCMF_PCIE_64_MB_INT_D2H_DB,
	.int_fn0 = 0,
};

static void brcmf_pcie_setup(struct device *dev, int ret,
			     struct brcmf_fw_request *fwreq);
static struct brcmf_fw_request *
brcmf_pcie_prepare_fw_request(struct brcmf_pciedev_info *devinfo);
static void
brcmf_pcie_fwcon_timer(struct brcmf_pciedev_info *devinfo, bool active);
static void brcmf_pcie_debugfs_create(struct device *dev);

static u16
brcmf_pcie_read_reg16(struct brcmf_pciedev_info *devinfo, u32 reg_offset)
{
	void __iomem *address = devinfo->regs + reg_offset;

	return ioread16(address);
}

static u32
brcmf_pcie_read_reg32(struct brcmf_pciedev_info *devinfo, u32 reg_offset)
{
	void __iomem *address = devinfo->regs + reg_offset;

	return (ioread32(address));
}


static void
brcmf_pcie_write_reg32(struct brcmf_pciedev_info *devinfo, u32 reg_offset,
		       u32 value)
{
	void __iomem *address = devinfo->regs + reg_offset;

	iowrite32(value, address);
}


static u8
brcmf_pcie_read_tcm8(struct brcmf_pciedev_info *devinfo, u32 mem_offset)
{
	void __iomem *address = devinfo->tcm + mem_offset;

	return (ioread8(address));
}


static u16
brcmf_pcie_read_tcm16(struct brcmf_pciedev_info *devinfo, u32 mem_offset)
{
	void __iomem *address = devinfo->tcm + mem_offset;

	return (ioread16(address));
}


static void
brcmf_pcie_write_tcm16(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
		       u16 value)
{
	void __iomem *address = devinfo->tcm + mem_offset;

	iowrite16(value, address);
}


static u16
brcmf_pcie_read_idx(struct brcmf_pciedev_info *devinfo, u32 mem_offset)
{
	u16 *address = devinfo->idxbuf + mem_offset;

	return (*(address));
}


static void
brcmf_pcie_write_idx(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
		     u16 value)
{
	u16 *address = devinfo->idxbuf + mem_offset;

	*(address) = value;
}


static u32
brcmf_pcie_read_tcm32(struct brcmf_pciedev_info *devinfo, u32 mem_offset)
{
	void __iomem *address = devinfo->tcm + mem_offset;

	return (ioread32(address));
}


static void
brcmf_pcie_write_tcm32(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
		       u32 value)
{
	void __iomem *address = devinfo->tcm + mem_offset;

	iowrite32(value, address);
}


static u32
brcmf_pcie_read_ram32(struct brcmf_pciedev_info *devinfo, u32 mem_offset)
{
	void __iomem *addr = devinfo->tcm + devinfo->ci->rambase + mem_offset;

	return (ioread32(addr));
}


static void
brcmf_pcie_write_ram32(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
		       u32 value)
{
	void __iomem *addr = devinfo->tcm + devinfo->ci->rambase + mem_offset;

	iowrite32(value, addr);
}


static void
brcmf_pcie_copy_dev_tomem(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
			  void *dstaddr, u32 len)
{
	void __iomem *address = devinfo->tcm + mem_offset;
	__le32 *dst32;
	__le16 *dst16;
	u8 *dst8;

	if (((ulong)address & 4) || ((ulong)dstaddr & 4) || (len & 4)) {
		if (((ulong)address & 2) || ((ulong)dstaddr & 2) || (len & 2)) {
			dst8 = (u8 *)dstaddr;
			while (len) {
				*dst8 = ioread8(address);
				address++;
				dst8++;
				len--;
			}
		} else {
			len = len / 2;
			dst16 = (__le16 *)dstaddr;
			while (len) {
				*dst16 = cpu_to_le16(ioread16(address));
				address += 2;
				dst16++;
				len--;
			}
		}
	} else {
		len = len / 4;
		dst32 = (__le32 *)dstaddr;
		while (len) {
			*dst32 = cpu_to_le32(ioread32(address));
			address += 4;
			dst32++;
			len--;
		}
	}
}


static void
brcmf_pcie_copy_mem_todev(struct brcmf_pciedev_info *devinfo, u32 mem_offset,
			  const void *srcaddr, u32 len)
{
	void __iomem *address = devinfo->tcm + mem_offset;
	const __le32 *src32;
	u32 i;

	/* BCM4360 requires strict 32-bit MMIO writes — 64-bit memcpy_toio
	 * (rep movsq on x86) hangs the PCIe bus.  Use iowrite32 for all
	 * chips; it's correct everywhere and only marginally slower.
	 */
	src32 = (const __le32 *)srcaddr;
	for (i = 0; i < len / 4; i++)
		iowrite32(le32_to_cpu(src32[i]), address + i * 4);

	/* Handle trailing bytes (NVRAM may not be 4-byte aligned) */
	if (len & 3) {
		u32 tmp = 0;

		memcpy(&tmp, (const u8 *)srcaddr + (len & ~3u), len & 3);
		iowrite32(tmp, address + (len & ~3u));
	}
}


#define READCC32(devinfo, reg) brcmf_pcie_read_reg32(devinfo, \
		CHIPCREGOFFS(reg))
#define WRITECC32(devinfo, reg, value) brcmf_pcie_write_reg32(devinfo, \
		CHIPCREGOFFS(reg), value)


static void
brcmf_pcie_select_core(struct brcmf_pciedev_info *devinfo, u16 coreid)
{
	const struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);
	struct brcmf_core *core;
	u32 bar0_win;

	core = brcmf_chip_get_core(devinfo->ci, coreid);
	if (core) {
		bar0_win = core->base;
		pci_write_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, bar0_win);
		if (pci_read_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW,
					  &bar0_win) == 0) {
			if (bar0_win != core->base) {
				bar0_win = core->base;
				pci_write_config_dword(pdev,
						       BRCMF_PCIE_BAR0_WINDOW,
						       bar0_win);
			}
		}
	} else {
		brcmf_err(bus, "Unsupported core selected %x\n", coreid);
	}
}


/* test.169: read-only dual-wrapbase probe of ARM CR4 IOCTL/RESET_CTL.
 *
 * test.169 revealed that IOCTL/RESET_CTL at (core->base + 0x1408/0x1800) read
 * as 0x0001 / 0x0 across every probe point — including immediately after
 * brcmf_chip_set_passive. Two interpretations: (a) the halt genuinely isn't
 * taking effect, or (b) our probe address is wrong.
 *
 * chip.c writes IOCTL/RESET_CTL at cpu->wrapbase + BCMA_IOCTL/BCMA_RESET_CTL
 * (offsets 0x408 / 0x800). `wrapbase` is populated by the BCMA erom scan and
 * is not directly readable from here. The two common BCMA AI wrapper layouts
 * are (i) wrapbase = base + 0x1000 (matches our original probe — offsets
 * 0x1408/0x1800), and (ii) wrapbase = base + 0x100000 (separate high window,
 * canonical BCMA AI layout).
 *
 * test.169 logs both views side-by-side so any discrepancy is visible in the
 * same log line. Writes: none — still purely diagnostic.
 */
static void brcmf_pcie_probe_armcr4_state(struct brcmf_pciedev_info *devinfo,
					  const char *tag)
{
	struct brcmf_core *arm_core;
	u32 saved_bar0;
	u32 ioctl = 0xdeadbeef, rstctl = 0xdeadbeef;

	/* test.169 confirmed: BCM4360 ARM CR4 wrapbase is core->base + 0x100000
	 * (canonical BCMA AI layout); the previous low-window probe at +0x1000
	 * read a different register (CLK only). Use the high window exclusively. */
	arm_core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_ARM_CR4);
	if (arm_core) {
		pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				      &saved_bar0);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       arm_core->base + 0x100000);
		ioctl  = brcmf_pcie_read_reg32(devinfo, 0x408);
		rstctl = brcmf_pcie_read_reg32(devinfo, 0x800);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       saved_bar0);
	}

	brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
	pr_emerg("BCM4360 test.176: %s ARM CR4 IOCTL=0x%08x RESET_CTL=0x%08x CPUHALT=%s\n",
		 tag, ioctl, rstctl, (ioctl & 0x20) ? "YES" : "NO");
}


static void brcmf_pcie_reset_device(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_core *core;
	u16 cfg_offset[] = { BRCMF_PCIE_CFGREG_STATUS_CMD,
			     BRCMF_PCIE_CFGREG_PM_CSR,
			     BRCMF_PCIE_CFGREG_MSI_CAP,
			     BRCMF_PCIE_CFGREG_MSI_ADDR_L,
			     BRCMF_PCIE_CFGREG_MSI_ADDR_H,
			     BRCMF_PCIE_CFGREG_MSI_DATA,
			     BRCMF_PCIE_CFGREG_LINK_STATUS_CTRL2,
			     BRCMF_PCIE_CFGREG_RBAR_CTRL,
			     BRCMF_PCIE_CFGREG_PML1_SUB_CTRL1,
			     BRCMF_PCIE_CFGREG_REG_BAR2_CONFIG,
			     BRCMF_PCIE_CFGREG_REG_BAR3_CONFIG };
	u32 i;
	u32 val;
	u32 lsc;
	bool bcm4360;

	if (!devinfo->ci)
		return;

	bcm4360 = devinfo->ci->chip == BRCM_CC_4360_CHIP_ID;

	if (bcm4360) {
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.122: reset_device bypassed; probe-start SBR already completed\n");
		return;
	}

	/* Disable ASPM */
	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
	pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_REG_LINK_STATUS_CTRL,
			      &lsc);
	val = lsc & (~BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB);
	pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_REG_LINK_STATUS_CTRL,
			       val);
	if (bcm4360)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.118: PCIE2 selected, ASPM disabled (lsc=0x%08x)\n",
			  lsc);

	/* Watchdog reset — BCM4360 skips this: SBR at probe-start already reset the chip,
	 * and test.114c confirmed the watchdog write crashes the PCIe link on BCM4360. */
	if (!bcm4360) {
		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
		WRITECC32(devinfo, watchdog, 4);
		msleep(100);
	} else {
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.118: ChipCommon watchdog skipped\n");
	}

	/* Restore ASPM */
	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
	pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_REG_LINK_STATUS_CTRL,
			       lsc);
	if (bcm4360)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.118: ASPM restored, entering PCIE2 cfg replay\n");

	core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
	if (core && core->rev <= 13) {
		for (i = 0; i < ARRAY_SIZE(cfg_offset); i++) {
			brcmf_pcie_write_reg32(devinfo,
					       BRCMF_PCIE_PCIE2REG_CONFIGADDR,
					       cfg_offset[i]);
			val = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);
			brcmf_dbg(PCIE, "config offset 0x%04x, value 0x%04x\n",
				  cfg_offset[i], val);
			brcmf_pcie_write_reg32(devinfo,
					       BRCMF_PCIE_PCIE2REG_CONFIGDATA,
					       val);
		}
	}
	if (bcm4360)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.118: reset_device complete\n");
}


static void brcmf_pcie_attach(struct brcmf_pciedev_info *devinfo)
{
	u32 config;

	pr_emerg("BCM4360 test.128: brcmf_pcie_attach ENTRY\n");

	/* test.129: BCM4360 — skip BAR1 window sizing; PCIe2 core is in BCMA reset at this
	 * point, so any BAR0 MMIO to it causes CTO → MCE → hard crash. BAR2 is used for
	 * firmware download, not BAR1, so this config is unnecessary for BCM4360.
	 */
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.129: brcmf_pcie_attach bypassed for BCM4360\n");
		return;
	}

	/* BAR1 window may not be sized properly */
	pr_emerg("BCM4360 test.128: before select_core PCIE2\n");
	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
	pr_emerg("BCM4360 test.128: before write CONFIGADDR\n");
	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x4e0);
	pr_emerg("BCM4360 test.128: before read CONFIGDATA\n");
	config = brcmf_pcie_read_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA);
	pr_emerg("BCM4360 test.128: before write CONFIGDATA config=0x%08x\n", config);
	brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_CONFIGDATA, config);
	pr_emerg("BCM4360 test.128: after write CONFIGDATA\n");

	device_wakeup_enable(&devinfo->pdev->dev);
	pr_emerg("BCM4360 test.128: brcmf_pcie_attach EXIT\n");
}


static int brcmf_pcie_enter_download_state(struct brcmf_pciedev_info *devinfo)
{
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		u32 reset_ctl, ioctl;

		/* test.142: ARM CR4 reset asserted at probe-time with proper BCMA sequence.
		 * Confirm reset state still held when firmware callback fires. */
		pr_emerg("BCM4360 test.142: enter_download_state — confirming ARM CR4 reset state\n");
		brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4);
		reset_ctl = brcmf_pcie_read_reg32(devinfo, 0x1800);
		ioctl     = brcmf_pcie_read_reg32(devinfo, 0x1408);
		pr_emerg("BCM4360 test.142: ARM CR4 state RESET_CTL=0x%08x IN_RESET=%s IOCTL=0x%04x CPUHALT=%s FGC=%s CLK=%s\n",
			 reset_ctl, (reset_ctl == 1) ? "YES" : "NO/BAD",
			 ioctl, (ioctl & 0x0020) ? "YES" : "NO",
			 (ioctl & 0x0002) ? "YES" : "NO",
			 (ioctl & 0x0001) ? "YES" : "NO");
		mdelay(300);
		return 0;
	}
	if (devinfo->ci->chip == BRCM_CC_43602_CHIP_ID) {
		brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_ARMCR4REG_BANKIDX,
				       5);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_ARMCR4REG_BANKPDA,
				       0);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_ARMCR4REG_BANKIDX,
				       7);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_ARMCR4REG_BANKPDA,
				       0);
	}
	return 0;
}


static int brcmf_pcie_exit_download_state(struct brcmf_pciedev_info *devinfo,
					  u32 resetintr)
{
	struct brcmf_core *core;

	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID ||
	    devinfo->ci->chip == BRCM_CC_43602_CHIP_ID) {
		core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_INTERNAL_MEM);
		if (core)
			brcmf_chip_resetcore(core, 0, 0, 0);
	}

	if (!brcmf_chip_set_active(devinfo->ci, resetintr))
		return -EIO;
	return 0;
}


static int
brcmf_pcie_send_mb_data(struct brcmf_pciedev_info *devinfo, u32 htod_mb_data)
{
	struct brcmf_pcie_shared_info *shared;
	struct brcmf_core *core;
	u32 addr;
	u32 cur_htod_mb_data;
	u32 i;

	shared = &devinfo->shared;
	addr = shared->htod_mb_data_addr;
	cur_htod_mb_data = brcmf_pcie_read_tcm32(devinfo, addr);

	if (cur_htod_mb_data != 0)
		brcmf_dbg(PCIE, "MB transaction is already pending 0x%04x\n",
			  cur_htod_mb_data);

	i = 0;
	while (cur_htod_mb_data != 0) {
		msleep(10);
		i++;
		if (i > 100)
			return -EIO;
		cur_htod_mb_data = brcmf_pcie_read_tcm32(devinfo, addr);
	}

	brcmf_pcie_write_tcm32(devinfo, addr, htod_mb_data);
	pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_REG_SBMBX, 1);

	/* Send mailbox interrupt twice as a hardware workaround */
	core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
	if (core->rev <= 13)
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_REG_SBMBX, 1);

	return 0;
}


static void brcmf_pcie_handle_mb_data(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_pcie_shared_info *shared;
	u32 addr;
	u32 dtoh_mb_data;

	shared = &devinfo->shared;
	addr = shared->dtoh_mb_data_addr;
	dtoh_mb_data = brcmf_pcie_read_tcm32(devinfo, addr);

	if (!dtoh_mb_data)
		return;

	brcmf_pcie_write_tcm32(devinfo, addr, 0);

	brcmf_dbg(PCIE, "D2H_MB_DATA: 0x%04x\n", dtoh_mb_data);
	if (dtoh_mb_data & BRCMF_D2H_DEV_DS_ENTER_REQ)  {
		brcmf_dbg(PCIE, "D2H_MB_DATA: DEEP SLEEP REQ\n");
		brcmf_pcie_send_mb_data(devinfo, BRCMF_H2D_HOST_DS_ACK);
		brcmf_dbg(PCIE, "D2H_MB_DATA: sent DEEP SLEEP ACK\n");
	}
	if (dtoh_mb_data & BRCMF_D2H_DEV_DS_EXIT_NOTE)
		brcmf_dbg(PCIE, "D2H_MB_DATA: DEEP SLEEP EXIT\n");
	if (dtoh_mb_data & BRCMF_D2H_DEV_D3_ACK) {
		brcmf_dbg(PCIE, "D2H_MB_DATA: D3 ACK\n");
		devinfo->mbdata_completed = true;
		wake_up(&devinfo->mbdata_resp_wait);
	}
	if (dtoh_mb_data & BRCMF_D2H_DEV_FWHALT) {
		brcmf_dbg(PCIE, "D2H_MB_DATA: FW HALT\n");
		brcmf_fw_crashed(&devinfo->pdev->dev);
	}
}


static void brcmf_pcie_bus_console_init(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_pcie_shared_info *shared;
	struct brcmf_pcie_console *console;
	u32 addr;

	shared = &devinfo->shared;
	console = &shared->console;
	addr = shared->tcm_base_address + BRCMF_SHARED_CONSOLE_ADDR_OFFSET;
	console->base_addr = brcmf_pcie_read_tcm32(devinfo, addr);

	addr = console->base_addr + BRCMF_CONSOLE_BUFADDR_OFFSET;
	console->buf_addr = brcmf_pcie_read_tcm32(devinfo, addr);
	addr = console->base_addr + BRCMF_CONSOLE_BUFSIZE_OFFSET;
	console->bufsize = brcmf_pcie_read_tcm32(devinfo, addr);

	brcmf_dbg(FWCON, "Console: base %x, buf %x, size %d\n",
		  console->base_addr, console->buf_addr, console->bufsize);
}

/**
 * brcmf_pcie_bus_console_read - reads firmware messages
 *
 * @devinfo: pointer to the device data structure
 * @error: specifies if error has occurred (prints messages unconditionally)
 */
static void brcmf_pcie_bus_console_read(struct brcmf_pciedev_info *devinfo,
					bool error)
{
	struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);
	struct brcmf_pcie_console *console;
	u32 addr;
	u8 ch;
	u32 newidx;

	if (!error && !BRCMF_FWCON_ON())
		return;

	console = &devinfo->shared.console;
	if (!console->base_addr)
		return;
	addr = console->base_addr + BRCMF_CONSOLE_WRITEIDX_OFFSET;
	newidx = brcmf_pcie_read_tcm32(devinfo, addr);
	while (newidx != console->read_idx) {
		addr = console->buf_addr + console->read_idx;
		ch = brcmf_pcie_read_tcm8(devinfo, addr);
		console->read_idx++;
		if (console->read_idx == console->bufsize)
			console->read_idx = 0;
		if (ch == '\r')
			continue;
		console->log_str[console->log_idx] = ch;
		console->log_idx++;
		if ((ch != '\n') &&
		    (console->log_idx == (sizeof(console->log_str) - 2))) {
			ch = '\n';
			console->log_str[console->log_idx] = ch;
			console->log_idx++;
		}
		if (ch == '\n') {
			console->log_str[console->log_idx] = 0;
			if (error)
				__brcmf_err(bus, __func__, "CONSOLE: %s",
					    console->log_str);
			else
				pr_debug("CONSOLE: %s", console->log_str);
			console->log_idx = 0;
		}
	}
}


static void brcmf_pcie_intr_disable(struct brcmf_pciedev_info *devinfo)
{
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxmask, 0);
}


static void brcmf_pcie_intr_enable(struct brcmf_pciedev_info *devinfo)
{
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxmask,
			       devinfo->reginfo->int_d2h_db |
			       devinfo->reginfo->int_fn0);
}

static void brcmf_pcie_hostready(struct brcmf_pciedev_info *devinfo)
{
	if (devinfo->shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1)
		brcmf_pcie_write_reg32(devinfo,
				       devinfo->reginfo->h2d_mailbox_1, 1);
}

static irqreturn_t brcmf_pcie_quick_check_isr(int irq, void *arg)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)arg;

	if (brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->mailboxint)) {
		brcmf_pcie_intr_disable(devinfo);
		brcmf_dbg(PCIE, "Enter\n");
		return IRQ_WAKE_THREAD;
	}
	return IRQ_NONE;
}


static irqreturn_t brcmf_pcie_isr_thread(int irq, void *arg)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)arg;
	u32 status;

	devinfo->in_irq = true;
	status = brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->mailboxint);
	brcmf_dbg(PCIE, "Enter %x\n", status);
	if (status) {
		brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxint,
				       status);
		if (status & devinfo->reginfo->int_fn0)
			brcmf_pcie_handle_mb_data(devinfo);
		if (status & devinfo->reginfo->int_d2h_db) {
			if (devinfo->state == BRCMFMAC_PCIE_STATE_UP)
				brcmf_proto_msgbuf_rx_trigger(
							&devinfo->pdev->dev);
		}
	}
	brcmf_pcie_bus_console_read(devinfo, false);
	if (devinfo->state == BRCMFMAC_PCIE_STATE_UP)
		brcmf_pcie_intr_enable(devinfo);
	devinfo->in_irq = false;
	return IRQ_HANDLED;
}


static int brcmf_pcie_request_irq(struct brcmf_pciedev_info *devinfo)
{
	struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);

	brcmf_pcie_intr_disable(devinfo);

	brcmf_dbg(PCIE, "Enter\n");

	pci_enable_msi(pdev);
	if (request_threaded_irq(pdev->irq, brcmf_pcie_quick_check_isr,
				 brcmf_pcie_isr_thread, IRQF_SHARED,
				 "brcmf_pcie_intr", devinfo)) {
		pci_disable_msi(pdev);
		brcmf_err(bus, "Failed to request IRQ %d\n", pdev->irq);
		return -EIO;
	}
	devinfo->irq_allocated = true;
	return 0;
}


static void brcmf_pcie_release_irq(struct brcmf_pciedev_info *devinfo)
{
	struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);
	u32 status;
	u32 count;

	if (!devinfo->irq_allocated)
		return;

	brcmf_pcie_intr_disable(devinfo);
	free_irq(pdev->irq, devinfo);
	pci_disable_msi(pdev);

	msleep(50);
	count = 0;
	while ((devinfo->in_irq) && (count < 20)) {
		msleep(50);
		count++;
	}
	if (devinfo->in_irq)
		brcmf_err(bus, "Still in IRQ (processing) !!!\n");

	status = brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->mailboxint);
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxint, status);

	devinfo->irq_allocated = false;
}


static int brcmf_pcie_ring_mb_write_rptr(void *ctx)
{
	struct brcmf_pcie_ringbuf *ring = (struct brcmf_pcie_ringbuf *)ctx;
	struct brcmf_pciedev_info *devinfo = ring->devinfo;
	struct brcmf_commonring *commonring = &ring->commonring;

	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP)
		return -EIO;

	brcmf_dbg(PCIE, "W r_ptr %d (%d), ring %d\n", commonring->r_ptr,
		  commonring->w_ptr, ring->id);

	devinfo->write_ptr(devinfo, ring->r_idx_addr, commonring->r_ptr);

	return 0;
}


static int brcmf_pcie_ring_mb_write_wptr(void *ctx)
{
	struct brcmf_pcie_ringbuf *ring = (struct brcmf_pcie_ringbuf *)ctx;
	struct brcmf_pciedev_info *devinfo = ring->devinfo;
	struct brcmf_commonring *commonring = &ring->commonring;

	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP)
		return -EIO;

	brcmf_dbg(PCIE, "W w_ptr %d (%d), ring %d\n", commonring->w_ptr,
		  commonring->r_ptr, ring->id);

	devinfo->write_ptr(devinfo, ring->w_idx_addr, commonring->w_ptr);

	return 0;
}


static int brcmf_pcie_ring_mb_ring_bell(void *ctx)
{
	struct brcmf_pcie_ringbuf *ring = (struct brcmf_pcie_ringbuf *)ctx;
	struct brcmf_pciedev_info *devinfo = ring->devinfo;

	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP)
		return -EIO;

	brcmf_dbg(PCIE, "RING !\n");
	/* Any arbitrary value will do, lets use 1 */
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->h2d_mailbox_0, 1);

	return 0;
}


static int brcmf_pcie_ring_mb_update_rptr(void *ctx)
{
	struct brcmf_pcie_ringbuf *ring = (struct brcmf_pcie_ringbuf *)ctx;
	struct brcmf_pciedev_info *devinfo = ring->devinfo;
	struct brcmf_commonring *commonring = &ring->commonring;

	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP)
		return -EIO;

	commonring->r_ptr = devinfo->read_ptr(devinfo, ring->r_idx_addr);

	brcmf_dbg(PCIE, "R r_ptr %d (%d), ring %d\n", commonring->r_ptr,
		  commonring->w_ptr, ring->id);

	return 0;
}


static int brcmf_pcie_ring_mb_update_wptr(void *ctx)
{
	struct brcmf_pcie_ringbuf *ring = (struct brcmf_pcie_ringbuf *)ctx;
	struct brcmf_pciedev_info *devinfo = ring->devinfo;
	struct brcmf_commonring *commonring = &ring->commonring;

	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP)
		return -EIO;

	commonring->w_ptr = devinfo->read_ptr(devinfo, ring->w_idx_addr);

	brcmf_dbg(PCIE, "R w_ptr %d (%d), ring %d\n", commonring->w_ptr,
		  commonring->r_ptr, ring->id);

	return 0;
}


static void *
brcmf_pcie_init_dmabuffer_for_device(struct brcmf_pciedev_info *devinfo,
				     u32 size, u32 tcm_dma_phys_addr,
				     dma_addr_t *dma_handle)
{
	void *ring;
	u64 address;

	ring = dma_alloc_coherent(&devinfo->pdev->dev, size, dma_handle,
				  GFP_KERNEL);
	if (!ring)
		return NULL;

	address = (u64)*dma_handle;
	brcmf_pcie_write_tcm32(devinfo, tcm_dma_phys_addr,
			       address & 0xffffffff);
	brcmf_pcie_write_tcm32(devinfo, tcm_dma_phys_addr + 4, address >> 32);

	return (ring);
}


static struct brcmf_pcie_ringbuf *
brcmf_pcie_alloc_dma_and_ring(struct brcmf_pciedev_info *devinfo, u32 ring_id,
			      u32 tcm_ring_phys_addr)
{
	void *dma_buf;
	dma_addr_t dma_handle;
	struct brcmf_pcie_ringbuf *ring;
	u32 size;
	u32 addr;
	const u32 *ring_itemsize_array;

	if (devinfo->shared.version < BRCMF_PCIE_SHARED_VERSION_7)
		ring_itemsize_array = brcmf_ring_itemsize_pre_v7;
	else
		ring_itemsize_array = brcmf_ring_itemsize;

	size = brcmf_ring_max_item[ring_id] * ring_itemsize_array[ring_id];
	dma_buf = brcmf_pcie_init_dmabuffer_for_device(devinfo, size,
			tcm_ring_phys_addr + BRCMF_RING_MEM_BASE_ADDR_OFFSET,
			&dma_handle);
	if (!dma_buf)
		return NULL;

	addr = tcm_ring_phys_addr + BRCMF_RING_MAX_ITEM_OFFSET;
	brcmf_pcie_write_tcm16(devinfo, addr, brcmf_ring_max_item[ring_id]);
	addr = tcm_ring_phys_addr + BRCMF_RING_LEN_ITEMS_OFFSET;
	brcmf_pcie_write_tcm16(devinfo, addr, ring_itemsize_array[ring_id]);

	ring = kzalloc(sizeof(*ring), GFP_KERNEL);
	if (!ring) {
		dma_free_coherent(&devinfo->pdev->dev, size, dma_buf,
				  dma_handle);
		return NULL;
	}
	brcmf_commonring_config(&ring->commonring, brcmf_ring_max_item[ring_id],
				ring_itemsize_array[ring_id], dma_buf);
	ring->dma_handle = dma_handle;
	ring->devinfo = devinfo;
	brcmf_commonring_register_cb(&ring->commonring,
				     brcmf_pcie_ring_mb_ring_bell,
				     brcmf_pcie_ring_mb_update_rptr,
				     brcmf_pcie_ring_mb_update_wptr,
				     brcmf_pcie_ring_mb_write_rptr,
				     brcmf_pcie_ring_mb_write_wptr, ring);

	return (ring);
}


static void brcmf_pcie_release_ringbuffer(struct device *dev,
					  struct brcmf_pcie_ringbuf *ring)
{
	void *dma_buf;
	u32 size;

	if (!ring)
		return;

	dma_buf = ring->commonring.buf_addr;
	if (dma_buf) {
		size = ring->commonring.depth * ring->commonring.item_len;
		dma_free_coherent(dev, size, dma_buf, ring->dma_handle);
	}
	kfree(ring);
}


static void brcmf_pcie_release_ringbuffers(struct brcmf_pciedev_info *devinfo)
{
	u32 i;

	for (i = 0; i < BRCMF_NROF_COMMON_MSGRINGS; i++) {
		brcmf_pcie_release_ringbuffer(&devinfo->pdev->dev,
					      devinfo->shared.commonrings[i]);
		devinfo->shared.commonrings[i] = NULL;
	}
	kfree(devinfo->shared.flowrings);
	devinfo->shared.flowrings = NULL;
	if (devinfo->idxbuf) {
		dma_free_coherent(&devinfo->pdev->dev,
				  devinfo->idxbuf_sz,
				  devinfo->idxbuf,
				  devinfo->idxbuf_dmahandle);
		devinfo->idxbuf = NULL;
	}
}


static int brcmf_pcie_init_ringbuffers(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_bus *bus = dev_get_drvdata(&devinfo->pdev->dev);
	struct brcmf_pcie_ringbuf *ring;
	struct brcmf_pcie_ringbuf *rings;
	u32 d2h_w_idx_ptr;
	u32 d2h_r_idx_ptr;
	u32 h2d_w_idx_ptr;
	u32 h2d_r_idx_ptr;
	u32 ring_mem_ptr;
	u32 i;
	u64 address;
	u32 bufsz;
	u8 idx_offset;
	struct brcmf_pcie_dhi_ringinfo ringinfo;
	u16 max_flowrings;
	u16 max_submissionrings;
	u16 max_completionrings;

	memcpy_fromio(&ringinfo, devinfo->tcm + devinfo->shared.ring_info_addr,
		      sizeof(ringinfo));
	if (devinfo->shared.version >= 6) {
		max_submissionrings = le16_to_cpu(ringinfo.max_submissionrings);
		max_flowrings = le16_to_cpu(ringinfo.max_flowrings);
		max_completionrings = le16_to_cpu(ringinfo.max_completionrings);
	} else {
		max_submissionrings = le16_to_cpu(ringinfo.max_flowrings);
		max_flowrings = max_submissionrings -
				BRCMF_NROF_H2D_COMMON_MSGRINGS;
		max_completionrings = BRCMF_NROF_D2H_COMMON_MSGRINGS;
	}
	if (max_flowrings > 512) {
		brcmf_err(bus, "invalid max_flowrings(%d)\n", max_flowrings);
		return -EIO;
	}

	if (devinfo->dma_idx_sz != 0) {
		bufsz = (max_submissionrings + max_completionrings) *
			devinfo->dma_idx_sz * 2;
		devinfo->idxbuf = dma_alloc_coherent(&devinfo->pdev->dev, bufsz,
						     &devinfo->idxbuf_dmahandle,
						     GFP_KERNEL);
		if (!devinfo->idxbuf)
			devinfo->dma_idx_sz = 0;
	}

	if (devinfo->dma_idx_sz == 0) {
		d2h_w_idx_ptr = le32_to_cpu(ringinfo.d2h_w_idx_ptr);
		d2h_r_idx_ptr = le32_to_cpu(ringinfo.d2h_r_idx_ptr);
		h2d_w_idx_ptr = le32_to_cpu(ringinfo.h2d_w_idx_ptr);
		h2d_r_idx_ptr = le32_to_cpu(ringinfo.h2d_r_idx_ptr);
		idx_offset = sizeof(u32);
		devinfo->write_ptr = brcmf_pcie_write_tcm16;
		devinfo->read_ptr = brcmf_pcie_read_tcm16;
		brcmf_dbg(PCIE, "Using TCM indices\n");
	} else {
		memset(devinfo->idxbuf, 0, bufsz);
		devinfo->idxbuf_sz = bufsz;
		idx_offset = devinfo->dma_idx_sz;
		devinfo->write_ptr = brcmf_pcie_write_idx;
		devinfo->read_ptr = brcmf_pcie_read_idx;

		h2d_w_idx_ptr = 0;
		address = (u64)devinfo->idxbuf_dmahandle;
		ringinfo.h2d_w_idx_hostaddr.low_addr =
			cpu_to_le32(address & 0xffffffff);
		ringinfo.h2d_w_idx_hostaddr.high_addr =
			cpu_to_le32(address >> 32);

		h2d_r_idx_ptr = h2d_w_idx_ptr +
				max_submissionrings * idx_offset;
		address += max_submissionrings * idx_offset;
		ringinfo.h2d_r_idx_hostaddr.low_addr =
			cpu_to_le32(address & 0xffffffff);
		ringinfo.h2d_r_idx_hostaddr.high_addr =
			cpu_to_le32(address >> 32);

		d2h_w_idx_ptr = h2d_r_idx_ptr +
				max_submissionrings * idx_offset;
		address += max_submissionrings * idx_offset;
		ringinfo.d2h_w_idx_hostaddr.low_addr =
			cpu_to_le32(address & 0xffffffff);
		ringinfo.d2h_w_idx_hostaddr.high_addr =
			cpu_to_le32(address >> 32);

		d2h_r_idx_ptr = d2h_w_idx_ptr +
				max_completionrings * idx_offset;
		address += max_completionrings * idx_offset;
		ringinfo.d2h_r_idx_hostaddr.low_addr =
			cpu_to_le32(address & 0xffffffff);
		ringinfo.d2h_r_idx_hostaddr.high_addr =
			cpu_to_le32(address >> 32);

		memcpy_toio(devinfo->tcm + devinfo->shared.ring_info_addr,
			    &ringinfo, sizeof(ringinfo));
		brcmf_dbg(PCIE, "Using host memory indices\n");
	}

	ring_mem_ptr = le32_to_cpu(ringinfo.ringmem);

	for (i = 0; i < BRCMF_NROF_H2D_COMMON_MSGRINGS; i++) {
		ring = brcmf_pcie_alloc_dma_and_ring(devinfo, i, ring_mem_ptr);
		if (!ring)
			goto fail;
		ring->w_idx_addr = h2d_w_idx_ptr;
		ring->r_idx_addr = h2d_r_idx_ptr;
		ring->id = i;
		devinfo->shared.commonrings[i] = ring;

		h2d_w_idx_ptr += idx_offset;
		h2d_r_idx_ptr += idx_offset;
		ring_mem_ptr += BRCMF_RING_MEM_SZ;
	}

	for (i = BRCMF_NROF_H2D_COMMON_MSGRINGS;
	     i < BRCMF_NROF_COMMON_MSGRINGS; i++) {
		ring = brcmf_pcie_alloc_dma_and_ring(devinfo, i, ring_mem_ptr);
		if (!ring)
			goto fail;
		ring->w_idx_addr = d2h_w_idx_ptr;
		ring->r_idx_addr = d2h_r_idx_ptr;
		ring->id = i;
		devinfo->shared.commonrings[i] = ring;

		d2h_w_idx_ptr += idx_offset;
		d2h_r_idx_ptr += idx_offset;
		ring_mem_ptr += BRCMF_RING_MEM_SZ;
	}

	devinfo->shared.max_flowrings = max_flowrings;
	devinfo->shared.max_submissionrings = max_submissionrings;
	devinfo->shared.max_completionrings = max_completionrings;
	rings = kcalloc(max_flowrings, sizeof(*ring), GFP_KERNEL);
	if (!rings)
		goto fail;

	brcmf_dbg(PCIE, "Nr of flowrings is %d\n", max_flowrings);

	for (i = 0; i < max_flowrings; i++) {
		ring = &rings[i];
		ring->devinfo = devinfo;
		ring->id = i + BRCMF_H2D_MSGRING_FLOWRING_IDSTART;
		brcmf_commonring_register_cb(&ring->commonring,
					     brcmf_pcie_ring_mb_ring_bell,
					     brcmf_pcie_ring_mb_update_rptr,
					     brcmf_pcie_ring_mb_update_wptr,
					     brcmf_pcie_ring_mb_write_rptr,
					     brcmf_pcie_ring_mb_write_wptr,
					     ring);
		ring->w_idx_addr = h2d_w_idx_ptr;
		ring->r_idx_addr = h2d_r_idx_ptr;
		h2d_w_idx_ptr += idx_offset;
		h2d_r_idx_ptr += idx_offset;
	}
	devinfo->shared.flowrings = rings;

	return 0;

fail:
	brcmf_err(bus, "Allocating ring buffers failed\n");
	brcmf_pcie_release_ringbuffers(devinfo);
	return -ENOMEM;
}


static void
brcmf_pcie_release_scratchbuffers(struct brcmf_pciedev_info *devinfo)
{
	if (devinfo->shared.scratch)
		dma_free_coherent(&devinfo->pdev->dev,
				  BRCMF_DMA_D2H_SCRATCH_BUF_LEN,
				  devinfo->shared.scratch,
				  devinfo->shared.scratch_dmahandle);
	if (devinfo->shared.ringupd)
		dma_free_coherent(&devinfo->pdev->dev,
				  BRCMF_DMA_D2H_RINGUPD_BUF_LEN,
				  devinfo->shared.ringupd,
				  devinfo->shared.ringupd_dmahandle);
}

static int brcmf_pcie_init_scratchbuffers(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_bus *bus = dev_get_drvdata(&devinfo->pdev->dev);
	u64 address;
	u32 addr;

	devinfo->shared.scratch =
		dma_alloc_coherent(&devinfo->pdev->dev,
				   BRCMF_DMA_D2H_SCRATCH_BUF_LEN,
				   &devinfo->shared.scratch_dmahandle,
				   GFP_KERNEL);
	if (!devinfo->shared.scratch)
		goto fail;

	addr = devinfo->shared.tcm_base_address +
	       BRCMF_SHARED_DMA_SCRATCH_ADDR_OFFSET;
	address = (u64)devinfo->shared.scratch_dmahandle;
	brcmf_pcie_write_tcm32(devinfo, addr, address & 0xffffffff);
	brcmf_pcie_write_tcm32(devinfo, addr + 4, address >> 32);
	addr = devinfo->shared.tcm_base_address +
	       BRCMF_SHARED_DMA_SCRATCH_LEN_OFFSET;
	brcmf_pcie_write_tcm32(devinfo, addr, BRCMF_DMA_D2H_SCRATCH_BUF_LEN);

	devinfo->shared.ringupd =
		dma_alloc_coherent(&devinfo->pdev->dev,
				   BRCMF_DMA_D2H_RINGUPD_BUF_LEN,
				   &devinfo->shared.ringupd_dmahandle,
				   GFP_KERNEL);
	if (!devinfo->shared.ringupd)
		goto fail;

	addr = devinfo->shared.tcm_base_address +
	       BRCMF_SHARED_DMA_RINGUPD_ADDR_OFFSET;
	address = (u64)devinfo->shared.ringupd_dmahandle;
	brcmf_pcie_write_tcm32(devinfo, addr, address & 0xffffffff);
	brcmf_pcie_write_tcm32(devinfo, addr + 4, address >> 32);
	addr = devinfo->shared.tcm_base_address +
	       BRCMF_SHARED_DMA_RINGUPD_LEN_OFFSET;
	brcmf_pcie_write_tcm32(devinfo, addr, BRCMF_DMA_D2H_RINGUPD_BUF_LEN);
	return 0;

fail:
	brcmf_err(bus, "Allocating scratch buffers failed\n");
	brcmf_pcie_release_scratchbuffers(devinfo);
	return -ENOMEM;
}


static void brcmf_pcie_down(struct device *dev)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *pcie_bus_dev = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = pcie_bus_dev->devinfo;

	brcmf_pcie_fwcon_timer(devinfo, false);
}

static int brcmf_pcie_preinit(struct device *dev)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;

	brcmf_dbg(PCIE, "Enter\n");

	brcmf_pcie_intr_enable(buspub->devinfo);
	brcmf_pcie_hostready(buspub->devinfo);

	return 0;
}

static int brcmf_pcie_tx(struct device *dev, struct sk_buff *skb)
{
	return 0;
}


static int brcmf_pcie_tx_ctlpkt(struct device *dev, unsigned char *msg,
				uint len)
{
	return 0;
}


static int brcmf_pcie_rx_ctlpkt(struct device *dev, unsigned char *msg,
				uint len)
{
	return 0;
}


static void brcmf_pcie_wowl_config(struct device *dev, bool enabled)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = buspub->devinfo;

	brcmf_dbg(PCIE, "Configuring WOWL, enabled=%d\n", enabled);
	devinfo->wowl_enabled = enabled;
}


static size_t brcmf_pcie_get_ramsize(struct device *dev)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = buspub->devinfo;

	return devinfo->ci->ramsize - devinfo->ci->srsize;
}


static int brcmf_pcie_get_memdump(struct device *dev, void *data, size_t len)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = buspub->devinfo;

	brcmf_dbg(PCIE, "dump at 0x%08X: len=%zu\n", devinfo->ci->rambase, len);
	brcmf_pcie_copy_dev_tomem(devinfo, devinfo->ci->rambase, data, len);
	return 0;
}

static int brcmf_pcie_get_blob(struct device *dev, const struct firmware **fw,
			       enum brcmf_blob_type type)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = buspub->devinfo;

	switch (type) {
	case BRCMF_BLOB_CLM:
		*fw = devinfo->clm_fw;
		devinfo->clm_fw = NULL;
		break;
	case BRCMF_BLOB_TXCAP:
		*fw = devinfo->txcap_fw;
		devinfo->txcap_fw = NULL;
		break;
	default:
		return -ENOENT;
	}

	if (!*fw)
		return -ENOENT;

	return 0;
}

static int brcmf_pcie_reset(struct device *dev)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pciedev *buspub = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = buspub->devinfo;
	struct brcmf_fw_request *fwreq;
	int err;

	brcmf_pcie_intr_disable(devinfo);

	brcmf_pcie_bus_console_read(devinfo, true);

	brcmf_detach(dev);

	brcmf_pcie_release_irq(devinfo);
	brcmf_pcie_release_scratchbuffers(devinfo);
	brcmf_pcie_release_ringbuffers(devinfo);
	brcmf_pcie_reset_device(devinfo);

	fwreq = brcmf_pcie_prepare_fw_request(devinfo);
	if (!fwreq) {
		dev_err(dev, "Failed to prepare FW request\n");
		return -ENOMEM;
	}

	err = brcmf_fw_get_firmwares(dev, fwreq, brcmf_pcie_setup);
	if (err) {
		dev_err(dev, "Failed to prepare FW request\n");
		kfree(fwreq);
	}

	return err;
}

static const struct brcmf_bus_ops brcmf_pcie_bus_ops = {
	.preinit = brcmf_pcie_preinit,
	.txdata = brcmf_pcie_tx,
	.stop = brcmf_pcie_down,
	.txctl = brcmf_pcie_tx_ctlpkt,
	.rxctl = brcmf_pcie_rx_ctlpkt,
	.wowl_config = brcmf_pcie_wowl_config,
	.get_ramsize = brcmf_pcie_get_ramsize,
	.get_memdump = brcmf_pcie_get_memdump,
	.get_blob = brcmf_pcie_get_blob,
	.reset = brcmf_pcie_reset,
	.debugfs_create = brcmf_pcie_debugfs_create,
};


static void
brcmf_pcie_adjust_ramsize(struct brcmf_pciedev_info *devinfo, u8 *data,
			  u32 data_len)
{
	__le32 *field;
	u32 newsize;

	if (data_len < BRCMF_RAMSIZE_OFFSET + 8)
		return;

	field = (__le32 *)&data[BRCMF_RAMSIZE_OFFSET];
	if (le32_to_cpup(field) != BRCMF_RAMSIZE_MAGIC)
		return;
	field++;
	newsize = le32_to_cpup(field);

	brcmf_dbg(PCIE, "Found ramsize info in FW, adjusting to 0x%x\n",
		  newsize);
	devinfo->ci->ramsize = newsize;
}


static int
brcmf_pcie_init_share_ram_info(struct brcmf_pciedev_info *devinfo,
			       u32 sharedram_addr)
{
	struct brcmf_bus *bus = dev_get_drvdata(&devinfo->pdev->dev);
	struct brcmf_pcie_shared_info *shared;
	u32 addr;

	shared = &devinfo->shared;
	shared->tcm_base_address = sharedram_addr;

	shared->flags = brcmf_pcie_read_tcm32(devinfo, sharedram_addr);
	shared->version = (u8)(shared->flags & BRCMF_PCIE_SHARED_VERSION_MASK);
	brcmf_dbg(PCIE, "PCIe protocol version %d\n", shared->version);
	if ((shared->version > BRCMF_PCIE_MAX_SHARED_VERSION) ||
	    (shared->version < BRCMF_PCIE_MIN_SHARED_VERSION)) {
		brcmf_err(bus, "Unsupported PCIE version %d\n",
			  shared->version);
		return -EINVAL;
	}

	/* check firmware support dma indicies */
	if (shared->flags & BRCMF_PCIE_SHARED_DMA_INDEX) {
		if (shared->flags & BRCMF_PCIE_SHARED_DMA_2B_IDX)
			devinfo->dma_idx_sz = sizeof(u16);
		else
			devinfo->dma_idx_sz = sizeof(u32);
	}

	addr = sharedram_addr + BRCMF_SHARED_MAX_RXBUFPOST_OFFSET;
	shared->max_rxbufpost = brcmf_pcie_read_tcm16(devinfo, addr);
	if (shared->max_rxbufpost == 0)
		shared->max_rxbufpost = BRCMF_DEF_MAX_RXBUFPOST;

	addr = sharedram_addr + BRCMF_SHARED_RX_DATAOFFSET_OFFSET;
	shared->rx_dataoffset = brcmf_pcie_read_tcm32(devinfo, addr);

	addr = sharedram_addr + BRCMF_SHARED_HTOD_MB_DATA_ADDR_OFFSET;
	shared->htod_mb_data_addr = brcmf_pcie_read_tcm32(devinfo, addr);

	addr = sharedram_addr + BRCMF_SHARED_DTOH_MB_DATA_ADDR_OFFSET;
	shared->dtoh_mb_data_addr = brcmf_pcie_read_tcm32(devinfo, addr);

	addr = sharedram_addr + BRCMF_SHARED_RING_INFO_ADDR_OFFSET;
	shared->ring_info_addr = brcmf_pcie_read_tcm32(devinfo, addr);

	brcmf_dbg(PCIE, "max rx buf post %d, rx dataoffset %d\n",
		  shared->max_rxbufpost, shared->rx_dataoffset);

	brcmf_pcie_bus_console_init(devinfo);
	brcmf_pcie_bus_console_read(devinfo, false);

	return 0;
}

struct brcmf_random_seed_footer {
	__le32 length;
	__le32 magic;
};

#define BRCMF_RANDOM_SEED_MAGIC		0xfeedc0de
#define BRCMF_RANDOM_SEED_LENGTH	0x100

static noinline_for_stack void
brcmf_pcie_provide_random_bytes(struct brcmf_pciedev_info *devinfo, u32 address)
{
	u8 randbuf[BRCMF_RANDOM_SEED_LENGTH];

	get_random_bytes(randbuf, BRCMF_RANDOM_SEED_LENGTH);
	brcmf_pcie_copy_mem_todev(devinfo, address, randbuf,
				  BRCMF_RANDOM_SEED_LENGTH);
}

/* test.85: MSI dummy IRQ handler — counts firmware MSI interrupts */
/* MSI ISR removed — test.82 proved MSI_count=0 across 30s, theory dead */

static int brcmf_pcie_download_fw_nvram(struct brcmf_pciedev_info *devinfo,
					const struct firmware *fw, void *nvram,
					u32 nvram_len)
{
	struct brcmf_bus *bus = dev_get_drvdata(&devinfo->pdev->dev);
	u32 sharedram_addr;
	u32 sharedram_addr_written;
	u32 loop_counter;
	int err;
	u32 address;
	u32 resetintr;

	brcmf_dbg(PCIE, "Halt ARM.\n");
	err = brcmf_pcie_enter_download_state(devinfo);
	if (err)
		return err;

	dev_info(&devinfo->pdev->dev,
		 "BCM4360 debug: rambase=0x%x ramsize=0x%x srsize=0x%x fw_size=%zu tcm=%px\n",
		 devinfo->ci->rambase, devinfo->ci->ramsize,
		 devinfo->ci->srsize, fw->size, devinfo->tcm);
	brcmf_dbg(PCIE, "Download FW %s\n", devinfo->fw_name);

	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		u32 bar2_probe;

		/* test.138: confirm crash site — is it the ioread32 itself (sync)
		 * or async during the preceding mdelay in enter_download_state?
		 * If pre-BAR2 appears but post-BAR2 doesn't → ioread32 is sync crash.
		 * If neither appears → async crash during trailing mdelay(300) above.
		 * If both appear → crash is later (copy_mem_todev).
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.138: pre-BAR2-ioread32 (tcm=%px)\n",
			  devinfo->tcm);
		mdelay(300);

		bar2_probe = ioread32(devinfo->tcm);

		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.138: post-BAR2-ioread32 = 0x%08x %s\n",
			  bar2_probe,
			  bar2_probe == 0xffffffff ? "(0xffffffff — CTO/error)" :
						     "(real value — BAR2 accessible)");
		mdelay(300);
	}

	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		/* test.167: test.166 proved ARM CR4 is NOT halted at fw-write
		 * time (pre-write RESET_CTL=0x0, IN_RESET=NO). Crash offsets
		 * drift with byte count (test.164: 426K, test.165: 341K,
		 * test.166: 360K) — consistent with ARM running partially
		 * written firmware. Re-halt ARM CR4 immediately before the
		 * 442KB write, verify halted, do the write, verify still halted.
		 *
		 * Interpretation:
		 *   post-halt=0x1, post-write=0x1, write completes → SUCCESS;
		 *     ARM-resume was the root cause.
		 *   post-halt=0x1, crash mid-write → write itself un-halts ARM
		 *     or a separate watchdog fires. Need mid-write polls next.
		 *   post-halt=0x0 → brcmf_chip_set_passive did not halt;
		 *     fall back to direct RESET_CTL=1 write.
		 */
		const __le32 *src32 = (const __le32 *)fw->data;
		u32 chunk_words = 16384 / 4;	/* 16KB breadcrumbs (test.164 cadence) */
		u32 total_words = (u32)(fw->size / 4);
		u32 tail = fw->size & 3u;
		void __iomem *wbase = devinfo->tcm + devinfo->ci->rambase;
		u32 i;

		/* Pre-halt probe (hi-window only since test.169) */
		brcmf_pcie_probe_armcr4_state(devinfo, "pre-halt");
		mdelay(50);

		/* test.167: re-halt ARM CR4 via the public chip API. */
		pr_emerg("BCM4360 test.176: re-halting ARM CR4 via brcmf_chip_set_passive\n");
		mdelay(50);
		brcmf_chip_set_passive(devinfo->ci);
		mdelay(100);	/* settle */

		/* Post-halt probe */
		brcmf_pcie_probe_armcr4_state(devinfo, "post-halt");
		mdelay(50);

		pr_emerg("BCM4360 test.176: starting chunked fw write, total_words=%u (%zu bytes) tail=%u wbase=%px\n",
			 total_words, fw->size, tail, wbase);
		mdelay(50);

		for (i = 0; i < total_words; i++) {
			iowrite32(le32_to_cpu(src32[i]), wbase + i * 4);
			if ((i + 1) % chunk_words == 0) {
				pr_emerg("BCM4360 test.176: wrote %u words (%u bytes)\n",
					 i + 1, (i + 1) * 4);
				mdelay(50);
			}
		}

		pr_emerg("BCM4360 test.176: all %u words written, before tail (tail=%u)\n",
			 total_words, tail);
		mdelay(50);

		if (tail) {
			u32 tmp = 0;

			memcpy(&tmp, (const u8 *)fw->data + (fw->size & ~3u),
			       tail);
			iowrite32(tmp, wbase + (fw->size & ~3u));
			pr_emerg("BCM4360 test.176: tail %u bytes written at offset %zu\n",
				 tail, fw->size & ~3u);
			mdelay(50);
		}

		pr_emerg("BCM4360 test.176: fw write complete (%zu bytes)\n",
			 fw->size);
		/* test.176: test.175 proved msleep(100) survives. Add only
		 * host-memory resetintr extraction before the same early return;
		 * still no post-write device MMIO or NVRAM write.
		 */
		pr_emerg("BCM4360 test.176: before post-fw msleep(100)\n");
		msleep(100);
		pr_emerg("BCM4360 test.176: after post-fw msleep(100)\n");
		resetintr = get_unaligned_le32(fw->data);
		pr_emerg("BCM4360 test.176: host resetintr=0x%08x before release\n",
			 resetintr);
		release_firmware(fw);
		brcmf_fw_nvram_free(nvram);
		pr_emerg("BCM4360 test.176: released fw/nvram after host resetintr; returning -ENODEV\n");
		return -ENODEV;
	} else {
		brcmf_pcie_copy_mem_todev(devinfo, devinfo->ci->rambase,
					  fw->data, fw->size);
	}

	resetintr = get_unaligned_le32(fw->data);
	release_firmware(fw);
	pr_emerg("BCM4360 test.176: after release_firmware resetintr=0x%08x\n",
		 resetintr);
	mdelay(50);

	if (nvram) {
		address = devinfo->ci->rambase + devinfo->ci->ramsize -
			  nvram_len;
		pr_emerg("BCM4360 test.176: pre-NVRAM write address=0x%x len=%u tcm=%px\n",
			 address, nvram_len, devinfo->tcm);
		mdelay(50);

		/* test.170: chunked NVRAM iowrite32 with breadcrumbs (mirrors the
		 * 442 KB fw write cadence that test.169 proved safe) — replaces
		 * the unbounded copy_mem_todev call. NVRAM is small (a few KB)
		 * so this typically yields one or two breadcrumbs. */
		{
			void __iomem *naddr = devinfo->tcm + address;
			const __le32 *nsrc32 = (const __le32 *)nvram;
			u32 nwords = nvram_len / 4;
			u32 ntail = nvram_len & 3;
			u32 nchunk = 1024;	/* 4 KB breadcrumbs */
			u32 j;

			for (j = 0; j < nwords; j++) {
				iowrite32(le32_to_cpu(nsrc32[j]),
					  naddr + j * 4);
				if ((j + 1) % nchunk == 0) {
					pr_emerg("BCM4360 test.176: NVRAM wrote %u words (%u bytes)\n",
						 j + 1, (j + 1) * 4);
					mdelay(50);
				}
			}
			if (ntail) {
				u32 tmp = 0;

				memcpy(&tmp,
				       (const u8 *)nvram + (nvram_len & ~3u),
				       ntail);
				iowrite32(tmp, naddr + (nvram_len & ~3u));
			}
			pr_emerg("BCM4360 test.176: post-NVRAM write done (%u bytes)\n",
				 nvram_len);
			mdelay(50);
		}
		brcmf_fw_nvram_free(nvram);

		if (devinfo->otp.valid) {
			size_t rand_len = BRCMF_RANDOM_SEED_LENGTH;
			struct brcmf_random_seed_footer footer = {
				.length = cpu_to_le32(rand_len),
				.magic = cpu_to_le32(BRCMF_RANDOM_SEED_MAGIC),
			};

			/* Some Apple chips/firmwares expect a buffer of random
			 * data to be present before NVRAM
			 */
			brcmf_dbg(PCIE, "Download random seed\n");

			address -= sizeof(footer);
			brcmf_pcie_copy_mem_todev(devinfo, address, &footer,
						  sizeof(footer));

			address -= rand_len;
			brcmf_pcie_provide_random_bytes(devinfo, address);
		}
	} else {
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 debug: WARNING - no NVRAM loaded!\n");
	}

	/* test.64: Do NOT zero ramsize-4.  The last 4 bytes of the NVRAM blob
	 * (0xffc70038) are the NVRAM length/magic token the firmware reads to
	 * locate its configuration.  Zeroing it (test.63) broke NVRAM discovery.
	 * The standard brcmfmac protocol:
	 *   host writes NVRAM → 0xffc70038 sits at ramsize-4
	 *   firmware reads it, parses NVRAM, inits PCIe2
	 *   firmware *overwrites* ramsize-4 with sharedram_addr
	 *   host detects the change (value != 0xffc70038) → that's sharedram_addr
	 */
	sharedram_addr_written = brcmf_pcie_read_ram32(devinfo,
						       devinfo->ci->ramsize -
						       4);
	dev_info(&devinfo->pdev->dev,
		 "BCM4360 debug: NVRAM marker at ramsize-4 = 0x%08x (NVRAM length token, not zeroed)\n",
		 sharedram_addr_written);

	/* test.39: watchdog reset enabled for BCM4360.
	 * test.39 result: watchdog survived on IOMMU group 8. After watchdog,
	 * BBPLL still off (HAVEHT=0 in pmustatus, HAVEALP=1). PMU domain is
	 * always-on: min_res/max_res/res_state unchanged. Watchdog did NOT
	 * bring up BBPLL. BCM4360 needs explicit BBPLL initialization.
	 * test.40: added pllcontrol reads + ARM wrapper diagnostics.
	 */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		/* Read-only: log PMU/HT state just before ARM release */
		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 pre-ARM: clk_ctl_st=0x%08x res_state=0x%08x HT=%s\n",
			 READCC32(devinfo, clk_ctl_st),
			 READCC32(devinfo, res_state),
			 (READCC32(devinfo, clk_ctl_st) & 0x20000) ? "YES" : "NO");

		/* test.101 baseline: read *0x62e20 before ARM release.
		 * FW image at offset 0x62e20 is 0, so a pre-ARM non-zero
		 * here would indicate stale TCM state from a prior load
		 * in the same boot, not a fresh FW write. Must be ZERO
		 * for the post-FW breadcrumb probe to be unambiguous.
		 */
		{
			u32 baseline = brcmf_pcie_read_ram32(devinfo, 0x62e20);

			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.101 pre-ARM baseline: *0x62e20=0x%08x %s\n",
				  baseline,
				  baseline == 0 ? "ZERO (expected)" :
						  "NON-ZERO -- stale TCM, breadcrumb reading is unreliable");
		}

		/* test.110: backplane core enum moved to brcmf_pcie_reset_device.
		 * Rationale: probe wedges in copy_mem_todev (earlier in this
		 * function), so code here never ran even with skip_arm=1.
		 */

		/* test.114b: d11 clk_ctl_st diagnostic before ARM release.
		 *
		 * test.114 stage1 result: d11 NOT in BCMA reset (RESET_CTL=0 already).
		 * clk_ctl_st=0x070b0042 at T+200ms: BP_ON_HT=YES, HAVEHT=YES, FORCEHT=YES.
		 * FW successfully wrote FORCEHT and BP_ON_HT was granted — fn 0x1415c
		 * likely exited. Anchor F mismatch (0x68c49 vs exp 0x68b95) suggests
		 * hang has moved downstream to a new site near FW address 0x68c49.
		 *
		 * This is now a pure read-only diagnostic; no resetcore (control test).
		 * d11 clk_ctl_st readable because d11 is already out of reset here.
		 */
		{
			u32 d11_wrap_rst, d11_wrap_ioctl, d11_ccs;

			brcmf_pcie_select_core(devinfo, BCMA_CORE_80211);
			d11_wrap_rst   = brcmf_pcie_read_reg32(devinfo, 0x1800);
			d11_wrap_ioctl = brcmf_pcie_read_reg32(devinfo, 0x1408);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.114b: wrap_RESET_CTL=0x%08x IN_RESET=%s wrap_IOCTL=0x%08x CLK=%s\n",
				 d11_wrap_rst,
				 (d11_wrap_rst   & 1) ? "YES" : "NO",
				 d11_wrap_ioctl,
				 (d11_wrap_ioctl & 1) ? "YES" : "NO");

			/* Only read core register if d11 is out of BCMA reset.
			 * Reading 0x1e0 while IN_RESET=YES causes PCIe SLVERR → hard crash.
			 * (This killed test.115 stage0 after reboot left d11 in reset.) */
			if (!(d11_wrap_rst & 1)) {
				d11_ccs = brcmf_pcie_read_reg32(devinfo, 0x1e0);
				dev_info(&devinfo->pdev->dev,
					 "BCM4360 test.114b: d11 clk_ctl_st=0x%08x BP_ON_HT=%s HAVEHT=%s FORCEHT=%s\n",
					 d11_ccs,
					 (d11_ccs & BIT(19)) ? "YES" : "NO",
					 (d11_ccs & BIT(17)) ? "YES" : "NO",
					 (d11_ccs & BIT(1))  ? "YES" : "NO");
			} else {
				dev_info(&devinfo->pdev->dev,
					 "BCM4360 test.114b: d11 IN_RESET=YES — skipping clk_ctl_st read (unsafe)\n");
			}

			brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
		}

		if (bcm4360_skip_arm) {
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.12: skipping ARM release (bcm4360_skip_arm=1)\n");
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.12: FW downloaded OK, dumping TCM state\n");

			/* Dump first 64 bytes of TCM to verify FW was written */
			{
				u32 i, val;

				for (i = 0; i < 64; i += 4) {
					val = brcmf_pcie_read_ram32(devinfo, i);
					if (i % 16 == 0)
						dev_info(&devinfo->pdev->dev,
							 "BCM4360 TCM[0x%04x]: %08x %08x %08x %08x\n",
							 i,
							 val,
							 brcmf_pcie_read_ram32(devinfo, i + 4),
							 brcmf_pcie_read_ram32(devinfo, i + 8),
							 brcmf_pcie_read_ram32(devinfo, i + 12));
				}
			}

			/* Read back NVRAM area to verify it was written */
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.12: sharedram[0x%x] = 0x%08x\n",
				 devinfo->ci->ramsize - 4,
				 brcmf_pcie_read_ram32(devinfo,
						       devinfo->ci->ramsize - 4));
			return -ENODEV; /* clean abort, no crash */
		}

		/* test.46: isolate ARM CPU startup from firmware execution.
		 *
		 * test.44 ROOT CAUSE FOUND:
		 *   Our pre-activate TCM overwrite (0xEAFFFFFE at 0x00..0x1C) was
		 *   silently undone by brcmf_pcie_buscore_activate(), which writes
		 *   rstvec=0xb80ef000 (firmware reset vector) to TCM[0] AFTER our
		 *   overwrite but BEFORE ARM is released. Both test.43 and test.44
		 *   ran identical firmware — hence identical 19-iter crash timing.
		 *
		 * test.46 FIX: branch-to-self is now written inside
		 *   brcmf_pcie_buscore_activate() for BCM4360, replacing rstvec
		 *   with 0xEAFFFFFE at TCM[0..0x1C]. This is the LAST write before
		 *   ARM reset is deasserted — guaranteed to be what ARM sees.
		 *
		 * Expected outcomes:
		 *   Crash at ~19 iters: hardware timer fires ~950ms after ARM
		 *     release, independent of ARM code — next step: keep ARM in
		 *     reset but wait 5s to confirm BBPLL alone is safe.
		 *   Different iter count: B. loop changes crash mode — useful data.
		 *   PASS: firmware execution (via rstvec at TCM[0]) is crash source.
		 */
		{
			u32 clk, pmu_st;
			int retries;

			brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
			clk = READCC32(devinfo, clk_ctl_st);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47 pre-BBPLL: clk_ctl_st=0x%08x min_res=0x%08x max_res=0x%08x res_state=0x%08x pmustatus=0x%08x HT=%s\n",
				 clk,
				 READCC32(devinfo, min_res_mask),
				 READCC32(devinfo, max_res_mask),
				 READCC32(devinfo, res_state),
				 READCC32(devinfo, pmustatus),
				 (clk & 0x20000) ? "YES" : "NO");

			/* Raise PMU ceiling first, then floor. Order matters. */
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47: raising max_res_mask+min_res_mask to 0xFFFFF\n");
			WRITECC32(devinfo, max_res_mask, 0xFFFFF);
			WRITECC32(devinfo, min_res_mask, 0xFFFFF);

			/* Poll pmustatus HAVEHT (bit 2 = 0x04) — BBPLL up */
			retries = 0;
			do {
				msleep(10);
				pmu_st = READCC32(devinfo, pmustatus);
				retries++;
			} while (!(pmu_st & 0x04) && retries < 10);

			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47 BBPLL: pmustatus=0x%08x clk_ctl_st=0x%08x HAVEHT=%s (retries=%d)\n",
				 pmu_st, READCC32(devinfo, clk_ctl_st),
				 (pmu_st & 0x04) ? "YES" : "NO", retries);

			if (!(pmu_st & 0x04)) {
				dev_err(&devinfo->pdev->dev,
					"BCM4360 test.47: BBPLL failed — aborting\n");
				return -ENODEV;
			}

			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47: BBPLL up — proceeding to ARM release (B. injected via activate)\n");
		}
	}

	/* test.64: Enable BusMaster on BCM4360 endpoint BEFORE ARM release.
	 * The SBR (Secondary Bus Reset) at probe time clears PCI_COMMAND
	 * including BusMaster (bit 2).  pci_enable_device() re-enables Mem
	 * but NOT BusMaster.  Without BusMaster the firmware cannot DMA to
	 * host memory — its PCIe2 DMA init fails every ~3s causing the
	 * periodic crash events we observed in test.58-63.
	 * IOMMU (group 8 confirmed active) protects against rogue DMA.
	 */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		u16 cmd_before;

		pci_read_config_word(devinfo->pdev, PCI_COMMAND, &cmd_before);
		pci_set_master(devinfo->pdev);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.65: BusMaster enabled; CMD was=0x%04x now=0x%04x\n",
			 cmd_before,
			 ({u16 c; pci_read_config_word(devinfo->pdev, PCI_COMMAND, &c); c;}));
	}

	/* test.85: MSI enable + dummy IRQ handler before ARM release.
	 *
	 * test.81 RESULT: CRASHED ~31s after ARM release (exactly at 30s
	 * timeout + cleanup). MSI was enabled (pci_enable_msi returned 0,
	 * ADDR=0xfee00738) but no IRQ handler was registered. Firmware
	 * fired MSIs during pcidongle_probe with no handler → unhandled
	 * interrupts. Crash occurred when cleanup restored RP error
	 * reporting (re-enabling SERR/AER while MSI still active).
	 *
	 * test.85 fixes:
	 * 1. ADD: request_irq() with counting dummy handler after pci_enable_msi
	 * 2. FIX: cleanup order — free_irq → pci_disable_msi → restore RP
	 * 3. FIX: stale array indices in baseline log (was wrong since expansion)
	 * 4. ADD: read MSI message control at 0x5A to verify MSI Enable bit
	 * 5. ADD: log MSI interrupt count at each TCM scan and at timeout
	 * 6. KEEP: wider TCM scan, ASPM disable, reg clears, console/BSS dumps
	 *
	 * test.85 hypothesis: firmware fires MSIs during pcidongle_probe.
	 * With a proper handler, the system absorbs them safely. The MSI
	 * counter tells us whether MSI is relevant to the hang.
	 * If count > 0: firmware IS firing MSIs → MSI matters for probe
	 * If count == 0: firmware never fired MSI → MSI not the issue
	 */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		struct brcmf_core *pcie2_core_info;
		u32 lsc, pcie2_ioctl, pcie2_reset;
		u32 pcie2_intmask, pcie2_mbint, pcie2_mbmask, pcie2_h2d0, pcie2_h2d1;
		/* (BAC dump vars removed — not needed for test.80) */

		/* Print PCIe2 core revision */
		pcie2_core_info = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.96: PCIe2 core id=0x%x rev=%d\n",
			 pcie2_core_info ? pcie2_core_info->id : 0,
			 pcie2_core_info ? pcie2_core_info->rev : -1);

		/* Keep ASPM disabled (safe, harmless) */
		brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
		pci_read_config_dword(devinfo->pdev,
				      BRCMF_PCIE_REG_LINK_STATUS_CTRL, &lsc);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.96: EP LINK_STATUS_CTRL=0x%08x ASPM_bits=0x%x\n",
			 lsc, lsc & BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB);
		if (lsc & BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB) {
			pci_write_config_dword(devinfo->pdev,
					       BRCMF_PCIE_REG_LINK_STATUS_CTRL,
					       lsc & ~BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.96: ASPM disabled (was 0x%x) before ARM\n",
				 lsc & BRCMF_PCIE_LINK_STATUS_CTRL_ASPM_ENAB);
		}

		/* Named register summary (BAC dump removed — confirmed identical across tests) */
		pcie2_intmask = brcmf_pcie_read_reg32(devinfo,
						      BRCMF_PCIE_PCIE2REG_INTMASK);
		pcie2_mbint   = brcmf_pcie_read_reg32(devinfo,
						      BRCMF_PCIE_PCIE2REG_MAILBOXINT);
		pcie2_mbmask  = brcmf_pcie_read_reg32(devinfo,
						      BRCMF_PCIE_PCIE2REG_MAILBOXMASK);
		pcie2_h2d0    = brcmf_pcie_read_reg32(devinfo,
						      BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0);
		pcie2_h2d1    = brcmf_pcie_read_reg32(devinfo,
						      BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1);
		pcie2_ioctl   = brcmf_pcie_read_reg32(devinfo, 0x1408);
		pcie2_reset   = brcmf_pcie_read_reg32(devinfo, 0x1800);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.96: PCIe2 pre-ARM: INTMASK=0x%x MBINT=0x%x MBMASK=0x%x H2D0=0x%x H2D1=0x%x IOCTL=0x%x RESET=0x%x\n",
			 pcie2_intmask, pcie2_mbint, pcie2_mbmask,
			 pcie2_h2d0, pcie2_h2d1, pcie2_ioctl, pcie2_reset);

		/* test.85: SET INTMASK and MAILBOXMASK to driver-expected values
		 * BEFORE ARM release. PCI-CDC firmware may poll MBMASK waiting for
		 * host to signal interrupt readiness. Normal brcmfmac sets these
		 * AFTER sharedram, but old firmware may expect them BEFORE.
		 * Values: int_d2h_db (0xFF0000) | int_fn0 (0x0300) = 0x00FF0300
		 */
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_INTMASK,
				       0x00FF0300);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_MAILBOXMASK,
				       0x00FF0300);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0, 0);
		brcmf_pcie_write_reg32(devinfo, BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1, 0);

		/* NEW in test.79: clear unknown non-zero regs from test.78 dump.
		 * 0x100-0x108 all read 0x0000000c (unknown purpose).
		 * 0x1E0 read 0x00070040 (unknown purpose).
		 * NOT clearing 0x120/0x124 (CONFIGADDR/CONFIGDATA — used by driver).
		 */
		brcmf_pcie_write_reg32(devinfo, 0x100, 0);
		brcmf_pcie_write_reg32(devinfo, 0x104, 0);
		brcmf_pcie_write_reg32(devinfo, 0x108, 0);
		brcmf_pcie_write_reg32(devinfo, 0x1E0, 0);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.96: SET INTMASK=0x00FF0300 MBMASK=0x00FF0300 + cleared H2D0/H2D1 + unknown regs 0x100-0x108, 0x1E0\n");

		/* Readback to verify writes took effect */
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.96: post-write readback: INTMASK=0x%08x MBMASK=0x%08x 0x100=0x%08x 0x1E0=0x%08x\n",
			 brcmf_pcie_read_reg32(devinfo, BRCMF_PCIE_PCIE2REG_INTMASK),
			 brcmf_pcie_read_reg32(devinfo, BRCMF_PCIE_PCIE2REG_MAILBOXMASK),
			 brcmf_pcie_read_reg32(devinfo, 0x100),
			 brcmf_pcie_read_reg32(devinfo, 0x1E0));

		/* MSI removed — test.82 proved MSI_count=0 across 30s */

		/* test.85: Dump device-side config + clear STATUS errors + walk PCIe caps.
		 * test.85 found CMD_STA=0x08100006 — STATUS bit 11 (Signaled Target
		 * Abort) is SET. This residual error from SBR may cause firmware to
		 * spin in pcidongle_probe when it reads its own config STATUS.
		 * Fix: clear all STATUS RW1C bits before ARM release.
		 * Also: walk capability list to dump full PCIe Express cap registers
		 * (DEVSTA, LNKSTA, etc.) which may have additional error bits.
		 */
		{
			u32 cfg04, cfg10, cfg14, cfg18, cfg4e0, cfg4f4;
			u32 cfg04_after;
			u32 cap_ptr_reg, pcie_cap_off;
			u32 cfg_devctl_sta, cfg_pm_csr;

			/* Read current CMD+STATUS */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x04);
			cfg04 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			/* BARs */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x10);
			cfg10 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x14);
			cfg14 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x18);
			cfg18 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR,
				BRCMF_PCIE_CFGREG_REG_BAR2_CONFIG);
			cfg4e0 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR,
				BRCMF_PCIE_CFGREG_REG_BAR3_CONFIG);
			cfg4f4 = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);

			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.96: dev-side config: CMD_STA=0x%08x BAR0=0x%08x BAR1=0x%08x BAR2=0x%08x\n",
				 cfg04, cfg10, cfg14, cfg18);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.96: dev-side config: BAR2_CONFIG(0x4E0)=0x%08x BAR3_CONFIG(0x4F4)=0x%08x\n",
				 cfg4e0, cfg4f4);

			/* CLEAR STATUS error bits: write 0xFFFF to STATUS (RW1C)
			 * while preserving COMMAND. STATUS is upper 16 bits of offset 0x04.
			 */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x04);
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA,
				(cfg04 & 0x0000FFFF) | 0xFFFF0000);
			/* Readback to verify clearing */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x04);
			cfg04_after = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.96: STATUS clear: before=0x%08x after=0x%08x\n",
				 cfg04, cfg04_after);

			/* Walk capability list to find PCIe Express capability */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x34);
			cap_ptr_reg = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);
			pcie_cap_off = 0;
			{
				u32 ptr = cap_ptr_reg & 0xFF;
				int walk = 0;

				while (ptr >= 0x40 && ptr < 0x100 && walk < 20) {
					u32 cap_hdr;

					brcmf_pcie_write_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGADDR,
						ptr & ~3u);
					cap_hdr = brcmf_pcie_read_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGDATA);
					/* Shift to align if ptr is not dword-aligned */
					if (ptr & 3)
						cap_hdr >>= (ptr & 3) * 8;

					dev_info(&devinfo->pdev->dev,
						 "BCM4360 test.96: cap walk: ptr=0x%02x id=0x%02x next=0x%02x\n",
						 ptr, cap_hdr & 0xFF,
						 (cap_hdr >> 8) & 0xFF);

					if ((cap_hdr & 0xFF) == 0x10) {
						/* PCI Express Capability */
						pcie_cap_off = ptr;
					}
					ptr = (cap_hdr >> 8) & 0xFF;
					walk++;
				}
			}

			/* Dump PCIe Express capability registers if found */
			if (pcie_cap_off) {
				u32 devctl_sta, lnkctl_sta;

				/* DevCtl+DevSta at pcie_cap+0x08 */
				brcmf_pcie_write_reg32(devinfo,
					BRCMF_PCIE_PCIE2REG_CONFIGADDR,
					pcie_cap_off + 0x08);
				devctl_sta = brcmf_pcie_read_reg32(devinfo,
					BRCMF_PCIE_PCIE2REG_CONFIGDATA);

				/* LnkCtl+LnkSta at pcie_cap+0x10 */
				brcmf_pcie_write_reg32(devinfo,
					BRCMF_PCIE_PCIE2REG_CONFIGADDR,
					pcie_cap_off + 0x10);
				lnkctl_sta = brcmf_pcie_read_reg32(devinfo,
					BRCMF_PCIE_PCIE2REG_CONFIGDATA);

				dev_info(&devinfo->pdev->dev,
					 "BCM4360 test.96: PCIe cap@0x%02x: DevCtl+Sta=0x%08x LnkCtl+Sta=0x%08x\n",
					 pcie_cap_off, devctl_sta, lnkctl_sta);

				/* Clear DevSta RW1C error bits (upper 16 of DevCtl+Sta) */
				if (devctl_sta & 0xFFFF0000) {
					brcmf_pcie_write_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGADDR,
						pcie_cap_off + 0x08);
					brcmf_pcie_write_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGDATA,
						devctl_sta);
					/* Readback */
					brcmf_pcie_write_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGADDR,
						pcie_cap_off + 0x08);
					cfg_devctl_sta = brcmf_pcie_read_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_CONFIGDATA);
					dev_info(&devinfo->pdev->dev,
						 "BCM4360 test.96: DevSta clear: before=0x%08x after=0x%08x\n",
						 devctl_sta, cfg_devctl_sta);
				}
			} else {
				dev_info(&devinfo->pdev->dev,
					 "BCM4360 test.96: PCIe cap NOT found (cap_ptr=0x%08x)\n",
					 cap_ptr_reg);
			}

			/* PM_CSR at offset 0x4C */
			brcmf_pcie_write_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x4C);
			cfg_pm_csr = brcmf_pcie_read_reg32(devinfo,
				BRCMF_PCIE_PCIE2REG_CONFIGDATA);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.96: PM_CSR(0x4C)=0x%08x\n",
				 cfg_pm_csr);
		}

		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);

		/* test.109: enum block moved earlier in the function (see just after
		 * test.101 pre-ARM baseline). This post-test.96 site is no longer
		 * used — enum runs before the skip_arm branch so it's reachable
		 * in both skip_arm=1 and skip_arm=0 paths.
		 */
	}

	brcmf_dbg(PCIE, "Bring ARM in running state\n");
	err = brcmf_pcie_exit_download_state(devinfo, resetintr);
	if (err)
		return err;

	/* test.46: immediately after ARM release, read ARM wrapper registers.
	 * ARM wrapper IOCTL at wrapper_base+0x408 = core_base+0x1408.
	 * ARM wrapper RESET_CTL at wrapper_base+0x800 = core_base+0x1800.
	 * ARM core clk_ctl_st at core_base+0x1E0 (if implemented by ARM).
	 * These confirm ARM is truly "up" and show its clock state at release.
	 */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		u32 arm_ioctl, arm_rst, arm_clkst;

		brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4);
		arm_ioctl  = brcmf_pcie_read_reg32(devinfo, 0x1408); /* wrapper IOCTL */
		arm_rst    = brcmf_pcie_read_reg32(devinfo, 0x1800); /* wrapper RESET_CTL */
		arm_clkst  = brcmf_pcie_read_reg32(devinfo, 0x01E0); /* core clk_ctl_st */
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.47 ARM-release: IOCTL=0x%08x RESET_CTL=0x%08x ARM_CLKST=0x%08x\n",
			 arm_ioctl, arm_rst, arm_clkst);
		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
	}

	/* test.67: Extended diagnostic — 60s wait + full TCM memory activity scan.
	 *
	 * test.66 RESULT: CRASHED before T+0000ms — PCIe2 select_core writes at outer=0
	 *   (before first msleep) caused EP config crash. Root cause: brcmf_pcie_select_core()
	 *   does pci_write_config_dword to BAR0_WINDOW — same crash mechanism as test.51.
	 *   Baseline PCIe2 reads worked at T+0ms; outer=0 PCIe2 reads failed at T+~5ms.
	 *
	 * test.67 fixes:
	 *   1. Remove PCIe2 mailbox reads entirely (both baseline and loop) — unsafe
	 *   2. Skip TCM scan at outer==0: first 200ms is pure masking (matches test.65)
	 *   3. Initialize fw_init_done_last from baseline read (not 0) so we detect
	 *      RUNTIME changes, not the constant firmware binary value at that address
	 *   4. Keep fw_init_done poll in inner loop (one safe BAR2 read per 10ms)
	 *   5. Keep 20-location TCM scan but only from outer>=1 (T+200ms+)
	 *
	 * Key scan addresses:
	 *   0x9D0A4: shared_info magic_start (olmsg protocol)
	 *   0x9F0CC: fw_init_done (olmsg) = SHARED_INFO_OFFSET + SI_FW_INIT_DONE
	 *   0x9FFFC: ramsize-4 (FullDongle sharedram pointer)
	 *   0x6C000..0x9C000: free TCM area (firmware heap/stack activity)
	 */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		/* test.81: expanded TCM scan — original 21 + wider 0x9A000-0x9FC00 range.
		 * PCI-CDC might write handshake at non-MSGBUF locations.
		 * Total: ~45 locations (still fast, ~1 read each).
		 */
		static const u32 t66_scan[] = {
			0x6C000, 0x70000, 0x74000, 0x78000,
			0x7C000, 0x80000, 0x84000, 0x88000,
			0x8C000, 0x90000, 0x94000, 0x98000,
			/* Wider coverage of upper TCM (every 0x100 from 0x9A000) */
			0x9A000, 0x9A100, 0x9A200, 0x9A300,
			0x9A400, 0x9A500, 0x9A600, 0x9A700,
			0x9A800, 0x9A900, 0x9AA00, 0x9AB00,
			0x9AC00, 0x9AD00, 0x9AE00, 0x9AF00,
			0x9B000, 0x9B100, 0x9B200, 0x9B300,
			0x9B400, 0x9B500, 0x9B600, 0x9B700,
			0x9B800, 0x9B900, 0x9BA00, 0x9BB00,
			0x9BC00, 0x9BD00, 0x9BE00, 0x9BF00,
			0x9C000, 0x9D000,
			0x9D0A4,  /* olmsg shared_info magic_start */
			0x9E000,
			0x9F0CC,  /* olmsg fw_init_done */
			0x9FF00,
			0x9FF1C,  /* NVRAM start */
			0x9cc5c,  /* console ring write pointer (virtual addr field) */
			0x9FFFC,  /* ramsize-4 (FullDongle/PCI-CDC sharedram ptr) */
		};
		u32 t66_prev[ARRAY_SIZE(t66_scan)];
		struct pci_dev *rp = devinfo->pdev->bus ? devinfo->pdev->bus->self : NULL;
		u16 rp_cmd_orig = 0, rp_bc_orig = 0, rp_devctl_orig = 0;
		u32 rp_aer_orig = 0;
		int pcie_cap = 0, aer_cap = 0;
		int outer, inner;
		u32 fw_sharedram = sharedram_addr_written; /* NVRAM token (0xffc70038) */
		u32 fw_init_done_last = 0;
		int i;

		/* Step 1: initial masking — disable RP error escalation */
		if (rp) {
			u16 rtctl = 0;
			u32 ext_cap0 = 0xdeadbeef;

			pcie_cap = pci_find_capability(rp, PCI_CAP_ID_EXP);
			aer_cap  = pci_find_ext_capability(rp, PCI_EXT_CAP_ID_ERR);

			pci_read_config_word(rp, PCI_COMMAND, &rp_cmd_orig);
			pci_write_config_word(rp, PCI_COMMAND,
					      rp_cmd_orig & ~PCI_COMMAND_SERR);

			pci_read_config_word(rp, PCI_BRIDGE_CONTROL, &rp_bc_orig);
			pci_write_config_word(rp, PCI_BRIDGE_CONTROL,
					      rp_bc_orig & ~PCI_BRIDGE_CTL_SERR);

			if (pcie_cap) {
				pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
						     &rp_devctl_orig);
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
						      rp_devctl_orig & ~0x000f);
				pci_read_config_word(rp, pcie_cap + PCI_EXP_RTCTL, &rtctl);
			}

			if (aer_cap) {
				pci_read_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND,
						      &rp_aer_orig);
				pci_write_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND, 0);
			}

			pci_read_config_dword(rp, 0x100, &ext_cap0);

			/* RW1C-clear status regs unconditionally at init */
			if (pcie_cap) {
				u16 devsta; u32 rtsta;
				pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, &devsta);
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, devsta);
				pci_read_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, &rtsta);
				pci_write_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, rtsta);
			}
			{
				u16 secsta;
				pci_read_config_word(rp, PCI_SEC_STATUS, &secsta);
				pci_write_config_word(rp, PCI_SEC_STATUS, secsta);
			}

			{
				u16 ep_cmd;

				pci_read_config_word(devinfo->pdev, PCI_COMMAND, &ep_cmd);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.96: RP=%s masked CMD BC DevCtl AER; "
					  "RootCtl=0x%04x ext_cap0=0x%08x nvram_token=0x%08x EP_CMD=0x%04x\n",
					  pci_name(rp), rtctl, ext_cap0,
					  sharedram_addr_written, ep_cmd);
			}
		} else {
			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.96: no root port — skipping masking\n");
		}

		/* Baseline TCM scan — read all 20 locations before FW has had time to run */
		for (i = 0; i < (int)ARRAY_SIZE(t66_scan); i++)
			t66_prev[i] = brcmf_pcie_read_ram32(devinfo, t66_scan[i]);

		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: TCM baseline: sharedram[0x9FFFC]=0x%08x "
			  "magic[0x9D0A4]=0x%08x fw_init[0x9F0CC]=0x%08x console_ptr[0x9cc5c]=0x%08x\n",
			  t66_prev[ARRAY_SIZE(t66_scan) - 1],  /* 0x9FFFC sharedram */
			  t66_prev[46],  /* 0x9D0A4 magic */
			  t66_prev[48],  /* 0x9F0CC fw_init */
			  t66_prev[51]); /* 0x9cc5c console */

		/* Initialize fw_init_done_last from baseline so we detect RUNTIME changes,
		 * not the constant firmware binary value pre-loaded at that address.
		 */
		fw_init_done_last = t66_prev[48]; /* 0x9F0CC */

		/* test.94: Confirm baseline — 1 read to verify ARM is running.
		 * test.89 proved: 0x9d000 goes 0→0x58c8c(T+2ms)→0x43b1(T+12ms)→frozen.
		 * 0x43b1 is a STATIC constant stored by function 0x673cc, NOT a counter.
		 * Firmware hangs at ~T+12ms. No need to repeat 100ms fast-sampling.
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: ARM released. t+0 baseline: ctr=0x%08x shared=0x%08x cons=0x%08x\n",
			  brcmf_pcie_read_ram32(devinfo, 0x9d000),
			  brcmf_pcie_read_ram32(devinfo, devinfo->ci->ramsize - 4),
			  brcmf_pcie_read_ram32(devinfo, 0x9cc5c));

		/* Step 2: FW wait + per-inner-tick re-masking
		 * test.101: shortened FW-wait cap 2000ms→1200ms (outer<10→outer<6)
		 * to widen safety margin against the ~1.9s regression seen in
		 * test.100. Probe count also reduced — see test.101 probe block.
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.101: starting FW wait + masking loop (1.2s max, re-mask every 10ms)\n");

		for (outer = 0; outer < 6; outer++) {
			/* Every 2s (10 outer iters, but NOT outer==0): TCM memory activity scan.
			 * Skip outer==0 — first 200ms is pure masking to match proven test.65
			 * behavior. Diagnostic reads start at T+200ms after firmware has settled.
			 */
			if (outer > 0 && outer % 10 == 0) {
				u16 ep_cmd;
				int changed = 0;

				pci_read_config_word(devinfo->pdev, PCI_COMMAND, &ep_cmd);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.96 T+%04dms: sharedram=0x%08x fw_init=0x%08x EP_CMD=0x%04x\n",
					  outer * 200, fw_sharedram, fw_init_done_last, ep_cmd);

				/* Scan all TCM locations; log any that changed */
				for (i = 0; i < (int)ARRAY_SIZE(t66_scan); i++) {
					u32 cur = brcmf_pcie_read_ram32(devinfo, t66_scan[i]);

					if (cur != t66_prev[i]) {
						dev_emerg(&devinfo->pdev->dev,
							  "BCM4360 test.96 T+%04dms: TCM[0x%05x] CHANGED 0x%08x → 0x%08x\n",
							  outer * 200, t66_scan[i],
							  t66_prev[i], cur);
						t66_prev[i] = cur;
						changed++;
					}
				}
				if (!changed)
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.96 T+%04dms: TCM scan — no changes\n",
						  outer * 200);
			}

			/* test.94: Counter tracking every 200ms (from test.87).
			 * 0x9d000 = 0x43b1 constant after T+12ms (static, not a counter).
			 * NO core switching (lethal: tests 66/76/86 all crashed).
			 * All reads via BAR2 (safe TCM reads only).
			 */
			if (outer > 0) {
				u32 counter = brcmf_pcie_read_ram32(devinfo, 0x9d000);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.96 T+%04dms: counter=0x%08x %s\n",
					  outer * 200, counter,
					  counter == t66_prev[43] ? "FROZEN" : "RUNNING");
				/* t66_scan[43] = 0x9D000 — update tracked value */
				t66_prev[43] = counter;
			}

			/* test.96: Code dump at 0x5200-0x5400 (128 words) to analyze fn 0x5250.
			 *
			 * test.95 RESULTS (CLEAN EXIT — code dumped successfully):
			 *   0x840-0xB40 disassembled → ALL C runtime library:
			 *     0x840: strcmp (entry at 0x840, loop body at 0x848 — NOT a hang site)
			 *     0x87c: strtol/strtoul
			 *     0x91c: memset
			 *     0x96a: memcpy (LDMIA/STMIA 32-byte blocks)
			 *     0xa30: console printf (calls 0xfd8/0x7c8/0x5ac/0x1848)
			 *     0xabc: callback dispatcher (5-entry, blx r3 dispatch)
			 *     0xb04: wrapper for 0xabc
			 *     0xb18: heap free
			 *   b.w 0x848 from 0x2208 is a tail call INTO strcmp — benign.
			 *   0xa4c annotation was wrong (mid-printf, not cleanup).
			 *   HANG LOCATION STILL UNKNOWN after test.95.
			 *
			 * Call chain established from si_attach disasm (test.91 + test.91_disasm):
			 *   si_attach (0x64590) → vtable Call 1 via *(*(0x62a14)+4)
			 *   object at 0x58cc4 (Call 2, vtable at obj+16, entry[1])
			 *   object at 0x58ef0 (Call 3, vtable at obj+16, entry[1])
			 *   Call 1 path: 0x644dc blx→0x1FC2→b.w 0x2208→bl 0x5250→b.w 0x848
			 *
			 * test.96 GOAL: dump 0x5200-0x5400 to disassemble fn 0x5250.
			 *   0x5250 is called by 0x2208 (via bl 0x5250) before b.w 0x848.
			 *   If 0x5250 contains LDR+CMP+BNE hardware-polling loop → IT IS THE HANG.
			 *   128 words × ~13ms = 1.7s; total with T+200ms = 1.9s (SAFE < 3s window)
			 */
#define T106_REMASK() do {						\
	if (rp) {							\
		u16 _bc, _dc, _devsta, _secsta;				\
		u32 _rtsta;						\
		pci_read_config_word(rp, PCI_BRIDGE_CONTROL, &_bc);	\
		pci_write_config_word(rp, PCI_BRIDGE_CONTROL,		\
				      _bc & ~PCI_BRIDGE_CTL_SERR);	\
		if (pcie_cap) {						\
			pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVCTL, &_dc);	\
			pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,		\
					      _dc & ~0x000f);		\
		}							\
		pci_write_config_word(rp, PCI_COMMAND,			\
				      rp_cmd_orig & ~PCI_COMMAND_SERR);	\
		if (pcie_cap) {						\
			pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, &_devsta);	\
			pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, _devsta);	\
			pci_read_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, &_rtsta);	\
			pci_write_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, _rtsta);	\
		}							\
		pci_read_config_word(rp, PCI_SEC_STATUS, &_secsta);	\
		pci_write_config_word(rp, PCI_SEC_STATUS, _secsta);	\
	}								\
} while (0)

			if (outer == 1) {
				/* test.106: discriminate prologue-hang vs poll-hang
				 * in fn 0x1415c.
				 *
				 * test.105 pinned T1=0x68321 (fn 0x1415c's own saved
				 * LR at [0x9CED4]) but T3[0x9CEC4]=0x91cc4 — NOT
				 * LR-shaped. Initial reading was "fn 0x1adc returned",
				 * but the simpler reading is: fn 0x1415c has NOT YET
				 * called any sub-BL. Stack below body_SP=0x9CEC8 is
				 * pre-call garbage.
				 *
				 * Hypothesis: hang is in fn 0x1415c's PROLOGUE, BEFORE
				 * the first BL to 0x1adc at 0x14182. Prime candidate is
				 * `ldr.w r2, [r3, #0x1e0]` at 0x14176 — the first MMIO
				 * touch of the status register. If the bus access
				 * stalls, CPU freezes on this load.
				 *
				 * DISCRIMINATOR: sample T3 at 3 time points. If fn
				 * 0x1415c were in the poll loop, we'd stochastically
				 * catch fn 0x1adc active and see 0x1418f. If T3 stays
				 * non-LR-shaped across all 3 samples, prologue-hang
				 * is confirmed.
				 *
				 * Per subagent disasm (2026-04-17):
				 *   - fn 0x6820c never spills r0 — struct pointer is
				 *     held live in its callee-saved r4. fn 0x1415c's
				 *     prologue `push {r4,r5,r6,lr}` saves caller-r4
				 *     at its body_SP = [0x9CEC8]. So [0x9CEC8] IS the
				 *     struct pointer. [struct+0x88] is the MMIO base.
				 *   - fn 0x15940 pushes {r4..r8,lr} (N=6), body_SP =
				 *     0x9CEC0, saved LR slot = 0x9CED4. If it were
				 *     active, [0x9CED4] would be 0x6832b, not 0x68321.
				 *     So T1=0x68321 still proves fn 0x1415c is active.
				 *
				 * Probe plan (14 reads total):
				 *   T+200ms (outer==1): ctr, pd, anc_E, anc_F, T1,
				 *                       T3@200, struct_ptr, mmio_base,
				 *                       sweep 0x9CEC0/0xCEBC/0xCEB8,
				 *                       sanity *0x62e20 — 12 reads
				 *   T+600ms (outer==3): T3@600 — 1 read
				 *   T+1000ms (outer==5): T3@1000 — 1 read
				 */
				u32 p_ctr, p_pd, bc_val;
				u32 anc_e, anc_f, t1, t3, struct_ptr, mmio_base, sw[3];
				int i, tms = outer * 200;
				bool t3_is_poll_delay, t3_is_pre_delay, t3_is_timeout;

				T106_REMASK();
				p_ctr = brcmf_pcie_read_ram32(devinfo, 0x9d000);
				T106_REMASK();
				p_pd  = brcmf_pcie_read_ram32(devinfo, 0x62a14);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 T+%04dms: ctr[0x9d000]=0x%08x "
					  "pd[0x62a14]=0x%08x\n",
					  tms, p_ctr, p_pd);

				T106_REMASK();
				anc_e = brcmf_pcie_read_ram32(devinfo, 0x9CFCC);
				T106_REMASK();
				anc_f = brcmf_pcie_read_ram32(devinfo, 0x9CF6C);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 ANCH E[0x9CFCC]=0x%08x F[0x9CF6C]=0x%08x "
					  "(exp 0x67705 0x68b95) MATCH E=%d F=%d\n",
					  anc_e, anc_f,
					  anc_e == 0x67705, anc_f == 0x68b95);

				T106_REMASK();
				t1 = brcmf_pcie_read_ram32(devinfo, 0x9CED4);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 T1[0x9CED4]=0x%08x %s (exp 0x68321 = fn 0x1415c saved LR)\n",
					  t1,
					  t1 == 0x68321 ? "MATCH — fn 0x1415c still active" :
					  t1 == 0x6832b ? "CHANGED to 0x6832b — fn 0x15940 is now active" :
					  "CHANGED — frame shifted elsewhere");

				T106_REMASK();
				t3 = brcmf_pcie_read_ram32(devinfo, 0x9CEC4);
				t3_is_poll_delay = (t3 == 0x1418f);
				t3_is_pre_delay  = (t3 == 0x14187);
				t3_is_timeout    = (t3 == 0x141b7);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 T3@%04dms[0x9CEC4]=0x%08x %s\n",
					  tms, t3,
					  t3_is_poll_delay ? "==0x1418f → INSIDE fn 0x1adc from POLL LOOP" :
					  t3_is_pre_delay  ? "==0x14187 → INSIDE fn 0x1adc from pre-loop delay" :
					  t3_is_timeout    ? "==0x141b7 → INSIDE fn 0x11e8 (poll TIMED OUT)" :
					  ((t3 & 1) && t3 >= 0x800 && t3 < 0x70000) ?
					  "LR-shaped but unexpected" :
					  "NOT LR-shaped → fn 0x1415c hasn't called any sub-BL yet (prologue-hang)");

				/* Struct pointer: fn 0x1415c saved caller-r4 here. */
				T106_REMASK();
				struct_ptr = brcmf_pcie_read_ram32(devinfo, 0x9CEC8);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 STRUCT_PTR[0x9CEC8]=0x%08x %s\n",
					  struct_ptr,
					  struct_ptr < 0xa0000 ? "TCM-shaped (valid struct ptr)" :
					  "NOT TCM-shaped (probably garbage)");

				/* Follow struct+0x88 if struct_ptr looks valid.
				 * [struct+0x88] is the MMIO base pointer used in the
				 * `ldr r3, [r0, #0x88]; ldr r2, [r3, #0x1e0]` sequence
				 * at 0x1416c-0x14176. MMIO value itself isn't TCM-
				 * readable but the base (stored in TCM) IS. */
				if (struct_ptr < 0xa0000 - 0x88) {
					T106_REMASK();
					mmio_base = brcmf_pcie_read_ram32(devinfo,
									  struct_ptr + 0x88);
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.106 MMIO_BASE[struct+0x88]=0x%08x "
						  "(target reg = 0x%08x)\n",
						  mmio_base, mmio_base + 0x1e0);
				} else {
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.106 MMIO_BASE: skipped (struct_ptr not TCM)\n");
				}

				/* Sweep 3 words below body_SP of fn 0x1415c — should
				 * all be pre-call stack garbage if prologue-hang. */
				for (i = 0; i < 3; i++) {
					T106_REMASK();
					sw[i] = brcmf_pcie_read_ram32(devinfo,
								      0x9CEC0 - (i * 4));
				}
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 SWEEP 0x9CEC0↓: %08x %08x %08x\n",
					  sw[0], sw[1], sw[2]);

				T106_REMASK();
				bc_val = brcmf_pcie_read_ram32(devinfo, 0x62e20);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 T+%04dms: SANITY *0x62e20=0x%08x\n",
					  tms, bc_val);

				/* test.107: read the exact register FW is hung reading
				 * (0x180011e0) via BAR0-window redirect. Compare host-side
				 * result to FW-side state:
				 *  - If we get a sensible value: core IS responding, FW
				 *    is stalling for some other reason (maybe it was a
				 *    transient hang on ARM's first access, or FW's poll
				 *    mask never matches, or we hit it pre-clock-enable
				 *    from ARM's side but host's BAR0 path has its own
				 *    clock).
				 *  - If we get 0xffffffff: core is genuinely dead. FW and
				 *    host both see the same thing.
				 *  - If the read HANGS the host (watchdog, or this probe
				 *    never prints): core is completely non-responsive at
				 *    the AXI/backplane level — both sides hang.
				 *
				 * NOTE: this writes BAR0 window — would disturb existing
				 * BAR0 code. Save+restore to CC (default post-ARM). The
				 * inner re-mask loop only touches root-port config space,
				 * not BAR0, so changing window here is safe between probes.
				 */
				{
					u32 hang_reg;

					T106_REMASK();
					pci_write_config_dword(devinfo->pdev,
							       BRCMF_PCIE_BAR0_WINDOW,
							       0x18001000);
					hang_reg = ioread32(devinfo->regs + 0x1e0);
					pci_write_config_dword(devinfo->pdev,
							       BRCMF_PCIE_BAR0_WINDOW,
							       0x18000000);
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.107 T+%04dms: FW-hang-target [0x180011e0]=0x%08x %s\n",
						  tms, hang_reg,
						  hang_reg == 0xffffffff ?
						    "DEAD from host side too" :
						    "alive from host side — FW-side hang is core-local");
				}
			}

			/* Time-evolved T3 samples at T+600ms and T+1000ms.
			 * Discriminator: if ANY sample catches LR=0x1418f/0x14187,
			 * fn 0x1415c is in the poll loop. If all samples stay
			 * non-LR-shaped, prologue-hang at 0x14176 is confirmed. */
			if (outer == 3 || outer == 5) {
				u32 t3;
				int tms = outer * 200;
				bool t3_is_poll_delay, t3_is_pre_delay, t3_is_timeout;

				T106_REMASK();
				t3 = brcmf_pcie_read_ram32(devinfo, 0x9CEC4);
				t3_is_poll_delay = (t3 == 0x1418f);
				t3_is_pre_delay  = (t3 == 0x14187);
				t3_is_timeout    = (t3 == 0x141b7);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.106 T3@%04dms[0x9CEC4]=0x%08x %s\n",
					  tms, t3,
					  t3_is_poll_delay ? "==0x1418f → INSIDE fn 0x1adc from POLL LOOP" :
					  t3_is_pre_delay  ? "==0x14187 → INSIDE fn 0x1adc from pre-loop delay" :
					  t3_is_timeout    ? "==0x141b7 → INSIDE fn 0x11e8 (poll TIMED OUT)" :
					  ((t3 & 1) && t3 >= 0x800 && t3 < 0x70000) ?
					  "LR-shaped but unexpected" :
					  "NOT LR-shaped → fn 0x1415c still pre-BL (prologue-hang)");
			}
#undef T106_REMASK

			/* Inner: re-mask + poll sharedram AND fw_init_done every 10ms for 200ms */
			for (inner = 0; inner < 20; inner++) {
				u32 fid;

				msleep(10);

				/* Re-mask + unconditional RW1C-clear every 10ms */
				if (rp) {
					u16 bc, dc, devsta, secsta;
					u32 rtsta;

					pci_read_config_word(rp, PCI_BRIDGE_CONTROL, &bc);
					pci_write_config_word(rp, PCI_BRIDGE_CONTROL,
							      bc & ~PCI_BRIDGE_CTL_SERR);

					if (pcie_cap) {
						pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVCTL, &dc);
						pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
								      dc & ~0x000f);
					}

					pci_write_config_word(rp, PCI_COMMAND,
							      rp_cmd_orig & ~PCI_COMMAND_SERR);

					/* Unconditional RW1C: writes reset PCH state */
					if (pcie_cap) {
						pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, &devsta);
						pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, devsta);
						pci_read_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, &rtsta);
						pci_write_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, rtsta);
					}
					pci_read_config_word(rp, PCI_SEC_STATUS, &secsta);
					pci_write_config_word(rp, PCI_SEC_STATUS, secsta);
				}

				/* Poll A: ramsize-4 for FullDongle sharedram pointer */
				fw_sharedram = brcmf_pcie_read_ram32(devinfo,
								      devinfo->ci->ramsize - 4);
				if (fw_sharedram != sharedram_addr_written) {
					/* Validate: distinguish real firmware write from PCIe
					 * bus error (all-ones). Read 3 known-stable locations.
					 * If ALL return 0xffffffff, the BAR0 write disrupted
					 * the device — it's a bus error, not firmware data.
					 */
					u32 chk_9d000 = brcmf_pcie_read_ram32(devinfo, 0x9d000);
					u32 chk_magic = brcmf_pcie_read_ram32(devinfo, 0x9D0A4);
					u32 chk_cons  = brcmf_pcie_read_ram32(devinfo, 0x9cc5c);
					bool all_ff = (fw_sharedram == 0xffffffff &&
						       chk_9d000 == 0xffffffff &&
						       chk_magic == 0xffffffff &&
						       chk_cons  == 0xffffffff);
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.96 T+%04dms: sharedram→0x%08x "
						  "9d000=0x%08x magic=0x%08x cons=0x%08x %s\n",
						  outer * 200 + (inner + 1) * 10, fw_sharedram,
						  chk_9d000, chk_magic, chk_cons,
						  all_ff ? "PCIe-ERR" : "dev-ok");
					if (!all_ff) {
						if (fw_sharedram < devinfo->ci->rambase +
						    devinfo->ci->ramsize) {
							/* Valid RAM address — FW is ready */
							goto t66_fw_ready;
						}
						/* Non-RAM address (e.g. 0xffffffff): firmware ACK.
						 * Update baseline so we detect next change, and
						 * send H2D_MAILBOX_1 (HOSTRDY_DB1 protocol).
						 */
						dev_emerg(&devinfo->pdev->dev,
							  "BCM4360 test.96: FW-ACK (sharedram=0x%08x "
							  "not valid RAM); sending H2D_MAILBOX_1, "
							  "updating baseline, continuing poll\n",
							  fw_sharedram);
						sharedram_addr_written = fw_sharedram;
						brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
						brcmf_pcie_write_reg32(devinfo,
								       BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1,
								       1);
					}
					/* else: PCIe bus error — device disrupted by BAR0 write.
					 * Keep polling with masking; device may recover.
					 */
				}

				/* Poll B: fw_init_done for olmsg protocol */
				fid = brcmf_pcie_read_ram32(devinfo, 0x9F0CC);
				if (fid != fw_init_done_last) {
					fw_init_done_last = fid;
					dev_emerg(&devinfo->pdev->dev,
						  "BCM4360 test.96 T+%04dms: fw_init_done CHANGED to 0x%08x\n",
						  outer * 200 + inner * 10, fid);
					if (fid != 0)
						goto t66_fw_init_done;
				}
			}
		}

		/* Timeout — FW did not signal in 30s.
		 * Re-mask + RW1C-clear + settle before final TCM scan, to avoid the
		 * crash seen in test.68 where the final BAR2 reads had no settle time
		 * after the last re-mask iteration.
		 */
		if (rp) {
			u16 bc, dc, devsta, secsta;
			u32 rtsta;

			pci_write_config_word(rp, PCI_COMMAND,
					      rp_cmd_orig & ~PCI_COMMAND_SERR);
			pci_read_config_word(rp, PCI_BRIDGE_CONTROL, &bc);
			pci_write_config_word(rp, PCI_BRIDGE_CONTROL,
					      bc & ~PCI_BRIDGE_CTL_SERR);
			if (pcie_cap) {
				pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVCTL, &dc);
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
						      dc & ~0x000f);
				pci_read_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, &devsta);
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVSTA, devsta);
				pci_read_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, &rtsta);
				pci_write_config_dword(rp, pcie_cap + PCI_EXP_RTSTA, rtsta);
			}
			pci_read_config_word(rp, PCI_SEC_STATUS, &secsta);
			pci_write_config_word(rp, PCI_SEC_STATUS, secsta);
		}
		msleep(1);

		/* test.87: NO BAR2 reads in timeout path.
		 * Crash scales with loop length — 3s loop should survive.
		 * Just print TIMEOUT, restore RP, and return cleanly.
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: TIMEOUT — FW silent for 2s — clean exit\n");

		/* Restore RP — no MSI to tear down (removed in test.85) */
		if (rp) {
			pci_write_config_word(rp, PCI_COMMAND, rp_cmd_orig);
			pci_write_config_word(rp, PCI_BRIDGE_CONTROL, rp_bc_orig);
			if (pcie_cap)
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
						      rp_devctl_orig);
			if (aer_cap)
				pci_write_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND,
						       rp_aer_orig);
			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.96: RP settings restored\n");
		}
		return -ENODEV;

t66_fw_init_done:
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: olmsg FW_INIT_DONE at T+%dms val=0x%08x "
			  "— olmsg protocol confirmed! sharedram=0x%08x\n",
			  outer * 200 + (inner + 1) * 10, fw_init_done_last, fw_sharedram);
		/* olmsg firmware initialized — restore RP, return */
		if (rp) {
			pci_write_config_word(rp, PCI_COMMAND, rp_cmd_orig);
			pci_write_config_word(rp, PCI_BRIDGE_CONTROL, rp_bc_orig);
			if (pcie_cap)
				pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
						      rp_devctl_orig);
			if (aer_cap)
				pci_write_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND,
						       rp_aer_orig);
			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.96: RP settings restored\n");
		}
		return -ENODEV;

t66_fw_ready:
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: FW READY (FullDongle) at T+%dms sharedram=0x%08x "
			  "— proceeding with probe init\n",
			  outer * 200 + (inner + 1) * 10, fw_sharedram);
		/* DO NOT restore RP here — firmware has just written sharedram and may
		 * immediately attempt DMA (D2H doorbell to uninitialised host rings).
		 * Keep masking active through init_share_ram_info (all BAR2/TCM reads —
		 * they work fine masked). RP is restored AFTER init returns.
		 */

		/* Validate sharedram is a real RAM address */
		if (fw_sharedram < devinfo->ci->rambase ||
		    fw_sharedram >= devinfo->ci->rambase + devinfo->ci->ramsize) {
			brcmf_err(bus,
				  "BCM4360 test.96: Invalid shared RAM address 0x%08x\n",
				  fw_sharedram);
			/* Restore RP before returning on invalid address */
			if (rp) {
				pci_write_config_word(rp, PCI_COMMAND, rp_cmd_orig);
				pci_write_config_word(rp, PCI_BRIDGE_CONTROL, rp_bc_orig);
				if (pcie_cap)
					pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
							      rp_devctl_orig);
				if (aer_cap)
					pci_write_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND,
							       rp_aer_orig);
			}
			return -ENODEV;
		}
		/* Directly init shared RAM — bypasses the unmasked second wait loop
		 * at the bottom of this function which would crash on BAR2 reads.
		 * Masking remains active during init to absorb any DMA errors from
		 * firmware D2H doorbell writes to uninitialised host rings.
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.96: calling init_share_ram_info(0x%08x) "
			  "(RP masking still active)\n",
			  fw_sharedram);
		{
			int t74_init_ret = brcmf_pcie_init_share_ram_info(devinfo,
								          fw_sharedram);
			/* Restore RP after init completes */
			if (rp) {
				pci_write_config_word(rp, PCI_COMMAND, rp_cmd_orig);
				pci_write_config_word(rp, PCI_BRIDGE_CONTROL, rp_bc_orig);
				if (pcie_cap)
					pci_write_config_word(rp, pcie_cap + PCI_EXP_DEVCTL,
							      rp_devctl_orig);
				if (aer_cap)
					pci_write_config_dword(rp, aer_cap + PCI_ERR_ROOT_COMMAND,
							       rp_aer_orig);
				dev_emerg(&devinfo->pdev->dev,
					  "BCM4360 test.96: RP settings restored (post-init)\n");
			}
			return t74_init_ret;
		}
	}

	brcmf_dbg(PCIE, "Wait for FW init\n");

	sharedram_addr = sharedram_addr_written;
	loop_counter = BRCMF_PCIE_FW_UP_TIMEOUT / 10;
	while ((sharedram_addr == sharedram_addr_written) && (loop_counter)) {
		msleep(10);
		sharedram_addr = brcmf_pcie_read_ram32(devinfo,
						       devinfo->ci->ramsize - 4);
		loop_counter--;
	}

	/* test.36: On timeout, log diagnostics BEFORE returning -ENODEV.
	 * These reads tell us if ARM executed even when FW didn't write pcie_shared.
	 */
	if (sharedram_addr == sharedram_addr_written) {
		struct brcmf_core *arm_core, *pcie2_core;
		u32 i, tcm_val;

		brcmf_err(bus, "BCM4360 test.47: FW timeout — did not write sharedram ptr in 5s\n");

		/* Diagnostic 1: ChipCommon clk_ctl_st + pmustatus after 5s.
		 * HAVEHT (bit 17 of clk_ctl_st, 0x20000) = BBPLL available to CC.
		 * HAVEALP (bit 16, 0x10000) = ALP available.
		 * pmustatus bit 2 (0x04) = HAVEHT at PMU level.
		 */
		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.47 post-timeout: CC clk_ctl_st=0x%08x res_state=0x%08x pmustatus=0x%08x HT=%s\n",
			 READCC32(devinfo, clk_ctl_st),
			 READCC32(devinfo, res_state),
			 READCC32(devinfo, pmustatus),
			 (READCC32(devinfo, clk_ctl_st) & 0x20000) ? "YES" : "NO");

		/* Diagnostic 2: ARM wrapper registers after 5s — did ARM reset itself? */
		brcmf_pcie_select_core(devinfo, BCMA_CORE_ARM_CR4);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.47 post-timeout: ARM IOCTL=0x%08x RESET_CTL=0x%08x ARM_CLKST=0x%08x\n",
			 brcmf_pcie_read_reg32(devinfo, 0x1408),
			 brcmf_pcie_read_reg32(devinfo, 0x1800),
			 brcmf_pcie_read_reg32(devinfo, 0x01E0));
		brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);

		/* Diagnostic 3: ARM CR4 and PCIE2 core states after timeout */
		arm_core   = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_ARM_CR4);
		pcie2_core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.47 post-timeout: ARM_CR4=%s PCIE2=%s\n",
			 arm_core   ? (brcmf_chip_iscoreup(arm_core)   ? "UP" : "DOWN") : "NULL",
			 pcie2_core ? (brcmf_chip_iscoreup(pcie2_core) ? "UP" : "DOWN") : "NULL");

		/* Diagnostic 3: read TCM[0..15] — if ARM ran, it may have modified
		 * these early init bytes vs what the driver wrote during FW download.
		 */
		for (i = 0; i < 16; i += 4) {
			tcm_val = brcmf_pcie_read_ram32(devinfo, i);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47 post-timeout: TCM[0x%04x]=0x%08x\n",
				 i, tcm_val);
		}
		/* Also read TCM[ramsize-8..ramsize-1] to check NVRAM area */
		for (i = devinfo->ci->ramsize - 8; i < devinfo->ci->ramsize; i += 4) {
			tcm_val = brcmf_pcie_read_ram32(devinfo, i);
			dev_info(&devinfo->pdev->dev,
				 "BCM4360 test.47 post-timeout: TCM[0x%05x]=0x%08x\n",
				 i, tcm_val);
		}

		return -ENODEV;
	}

	/* Firmware initialized: log the detected shared pointer */
	if (devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.47: FW init detected! sharedram_addr=0x%08x\n",
			 sharedram_addr);
	}

	if (sharedram_addr < devinfo->ci->rambase ||
	    sharedram_addr >= devinfo->ci->rambase + devinfo->ci->ramsize) {
		brcmf_err(bus, "Invalid shared RAM address 0x%08x\n",
			  sharedram_addr);
		return -ENODEV;
	}
	brcmf_dbg(PCIE, "Shared RAM addr: 0x%08x\n", sharedram_addr);

	return (brcmf_pcie_init_share_ram_info(devinfo, sharedram_addr));
}


static int brcmf_pcie_get_resource(struct brcmf_pciedev_info *devinfo)
{
	struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);
	int err;
	phys_addr_t  bar0_addr, bar1_addr;
	ulong bar1_size;

	err = pci_enable_device(pdev);
	if (err) {
		brcmf_err(bus, "pci_enable_device failed err=%d\n", err);
		return err;
	}

	pci_set_master(pdev);

	/* Bar-0 mapped address */
	bar0_addr = pci_resource_start(pdev, 0);
	/* Bar-1 mapped address */
	bar1_addr = pci_resource_start(pdev, 2);
	/* read Bar-1 mapped memory range */
	bar1_size = pci_resource_len(pdev, 2);
	if ((bar1_size == 0) || (bar1_addr == 0)) {
		brcmf_err(bus, "BAR1 Not enabled, device size=%ld, addr=%#016llx\n",
			  bar1_size, (unsigned long long)bar1_addr);
		return -EINVAL;
	}

	devinfo->regs = ioremap(bar0_addr, BRCMF_PCIE_REG_MAP_SIZE);
	devinfo->tcm = ioremap(bar1_addr, bar1_size);

	if (!devinfo->regs || !devinfo->tcm) {
		brcmf_err(bus, "ioremap() failed (%p,%p)\n", devinfo->regs,
			  devinfo->tcm);
		return -EINVAL;
	}
	brcmf_dbg(PCIE, "Phys addr : reg space = %p base addr %#016llx\n",
		  devinfo->regs, (unsigned long long)bar0_addr);
	brcmf_dbg(PCIE, "Phys addr : mem space = %p base addr %#016llx size 0x%x\n",
		  devinfo->tcm, (unsigned long long)bar1_addr,
		  (unsigned int)bar1_size);
	dev_info(&pdev->dev, "BCM4360 debug: BAR0=%#llx BAR2=%#llx BAR2_size=0x%lx tcm=%px\n",
		 (unsigned long long)bar0_addr, (unsigned long long)bar1_addr,
		 bar1_size, devinfo->tcm);

	/* test.53: BAR0 MMIO probe read — confirms device is responding after SBR.
	 * Set BAR0_WINDOW to ChipCommon (0x18000000) and read offset 0 (chip ID word).
	 * Expected: 0x43a04e13 or similar (chipid | corerev fields). 0xffffffff = dead.
	 * This read happens before chip_attach's enumeration; if it crashes → BAR0 MMIO broken.
	 * If it prints 0xffffffff → device not responding even after SBR → need power cycle.
	 */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		u32 probe_val, probe_val2;

		pci_write_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, 0x18000000);
		probe_val = ioread32(devinfo->regs);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.53: BAR0 probe (CC@0x18000000 off=0) = 0x%08x%s\n",
			  probe_val,
			  probe_val == 0xffffffff ? " — DEAD (no MMIO response)" : " — alive");
		if (probe_val == 0xffffffff) {
			dev_emerg(&pdev->dev,
				  "BCM4360 test.53: ABORT — BAR0 dead after SBR, skipping chip_attach\n");
			return -ENODEV;
		}
		/* test.131: second probe read after brief settle — confirms MMIO stable */
		msleep(50);
		probe_val2 = ioread32(devinfo->regs);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.131: BAR0 2nd probe = 0x%08x%s\n",
			  probe_val2,
			  probe_val2 == 0xffffffff ? " — DEAD" : " — stable");
		if (probe_val2 == 0xffffffff) {
			dev_emerg(&pdev->dev,
				  "BCM4360 test.131: ABORT — BAR0 unstable after SBR\n");
			return -ENODEV;
		}
	}

	return 0;
}


static void brcmf_pcie_release_resource(struct brcmf_pciedev_info *devinfo)
{
	if (devinfo->tcm)
		iounmap(devinfo->tcm);
	if (devinfo->regs)
		iounmap(devinfo->regs);

	pci_disable_device(devinfo->pdev);
}


static u32 brcmf_pcie_buscore_prep_addr(const struct pci_dev *pdev, u32 addr)
{
	u32 ret_addr;

	ret_addr = addr & (BRCMF_PCIE_BAR0_REG_SIZE - 1);
	addr &= ~(BRCMF_PCIE_BAR0_REG_SIZE - 1);
	pci_write_config_dword(pdev, BRCMF_PCIE_BAR0_WINDOW, addr);

	return ret_addr;
}


static u32 brcmf_pcie_buscore_read32(void *ctx, u32 addr)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)ctx;

	addr = brcmf_pcie_buscore_prep_addr(devinfo->pdev, addr);
	return brcmf_pcie_read_reg32(devinfo, addr);
}


static void brcmf_pcie_buscore_write32(void *ctx, u32 addr, u32 value)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)ctx;

	addr = brcmf_pcie_buscore_prep_addr(devinfo->pdev, addr);
	brcmf_pcie_write_reg32(devinfo, addr, value);
}


static int brcmf_pcie_buscoreprep(void *ctx)
{
	return brcmf_pcie_get_resource(ctx);
}


static int brcmf_pcie_buscore_reset(void *ctx, struct brcmf_chip *chip)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)ctx;
	struct brcmf_core *core;
	u32 val, reg;

	devinfo->ci = chip;
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.125: buscore_reset entry, ci assigned\n");
	brcmf_pcie_reset_device(devinfo);
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.125: after reset_device return\n");

	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		/* test.145: halt ARM CR4 immediately after the second SBR.
		 * brcmf_chip_attach() calls brcmf_chip_set_passive() once (pre-reset),
		 * then calls buscore_reset() which does a second SBR via reset_device().
		 * After that SBR the ARM is running garbage code again.  chip_attach()
		 * skips the second set_passive for BCM4360 (legacy test.121 decision),
		 * so we do it here instead before returning to chip_attach.
		 */
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.145: halting ARM CR4 after second SBR (buscore_reset)\n");
		brcmf_chip_set_passive(chip);
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.145: ARM CR4 halt done — skipping PCIE2 mailbox clear; returning 0\n");
		/* test.169: probe ARM CR4 state IMMEDIATELY after set_passive — narrowest
		 * possible window. If CPUHALT ever reads as 1, it is here. */
		brcmf_pcie_probe_armcr4_state(devinfo, "post-145");
		return 0;
	}

	/* reginfo is not ready yet */
	core = brcmf_chip_get_core(chip, BCMA_CORE_PCIE2);
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.125: PCIE2 core %s rev=%u\n",
			  core ? "found" : "NULL", core ? core->rev : 0);
	if (!core) {
		/* Should not happen; but avoid crash */
		return -ENODEV;
	}
	if (core->rev >= 64)
		reg = BRCMF_PCIE_64_PCIE2REG_MAILBOXINT;
	else
		reg = BRCMF_PCIE_PCIE2REG_MAILBOXINT;

	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.125: before PCIE2 reg read (reg=0x%x)\n", reg);
	val = brcmf_pcie_read_reg32(devinfo, reg);
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
		dev_emerg(&devinfo->pdev->dev,
			  "BCM4360 test.125: after PCIE2 reg read val=0x%08x\n", val);
	if (val != 0xffffffff) {
		if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.125: before PCIE2 reg write\n");
		brcmf_pcie_write_reg32(devinfo, reg, val);
		if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID)
			dev_emerg(&devinfo->pdev->dev,
				  "BCM4360 test.125: after PCIE2 reg write\n");
	}

	return 0;
}


static void brcmf_pcie_buscore_activate(void *ctx, struct brcmf_chip *chip,
					u32 rstvec)
{
	struct brcmf_pciedev_info *devinfo = (struct brcmf_pciedev_info *)ctx;

	/* test.46: restore normal firmware — write rstvec to TCM[0] for all chips.
	 * test.49: set DisINTx=1 AND BusMaster=0 immediately before ARM release.
	 *   INTx RULED OUT (test.49): CMD=0x0402 throughout all 49 iters, still crashed.
	 *   MSI RULED OUT (test.49): MSI_CTRL=0x0080 (only 64-bit cap bit), never enabled.
	 *   DMA already ruled out (test.48): BusMaster=0 throughout.
	 * test.51: INSTANT CRASH — select_core(CHIPCOMMON) in activate() corrupts BAR0
	 *   window during ARM init. Machine reset before any test.51 message was logged.
	 * test.52: activate() is IDENTICAL to test.49 — no watchdog reads here.
	 *   Watchdog is serviced in the poll loop where BAR0 is already ChipCommon.
	 */
	if (chip->chip == BRCM_CC_4360_CHIP_ID) {
		u16 cmd;

		/* test.65: DO NOT modify CMD here — pci_set_master() was called before
		 * brcmf_pcie_exit_download_state(), and BusMaster must stay set so
		 * firmware PCIe2 DMA init succeeds. Previous tests (test.49 era) cleared
		 * BusMaster here; that caused firmware crash-restart loop every ~3s.
		 */
		pci_read_config_word(devinfo->pdev, PCI_COMMAND, &cmd);
		dev_info(&devinfo->pdev->dev,
			 "BCM4360 test.65 activate: rstvec=0x%08x to TCM[0]; CMD=0x%04x (BusMaster preserved)\n",
			 rstvec, cmd);
	}
	brcmf_pcie_write_tcm32(devinfo, 0, rstvec);
}


static const struct brcmf_buscore_ops brcmf_pcie_buscore_ops = {
	.prepare = brcmf_pcie_buscoreprep,
	.reset = brcmf_pcie_buscore_reset,
	.activate = brcmf_pcie_buscore_activate,
	.read32 = brcmf_pcie_buscore_read32,
	.write32 = brcmf_pcie_buscore_write32,
};

#define BRCMF_OTP_SYS_VENDOR	0x15
#define BRCMF_OTP_BRCM_CIS	0x80

#define BRCMF_OTP_VENDOR_HDR	0x00000008

static int
brcmf_pcie_parse_otp_sys_vendor(struct brcmf_pciedev_info *devinfo,
				u8 *data, size_t size)
{
	int idx = 4;
	const char *chip_params;
	const char *board_params;
	const char *p;

	/* 4-byte header and two empty strings */
	if (size < 6)
		return -EINVAL;

	if (get_unaligned_le32(data) != BRCMF_OTP_VENDOR_HDR)
		return -EINVAL;

	chip_params = &data[idx];

	/* Skip first string, including terminator */
	idx += strnlen(chip_params, size - idx) + 1;
	if (idx >= size)
		return -EINVAL;

	board_params = &data[idx];

	/* Skip to terminator of second string */
	idx += strnlen(board_params, size - idx);
	if (idx >= size)
		return -EINVAL;

	/* At this point both strings are guaranteed NUL-terminated */
	brcmf_dbg(PCIE, "OTP: chip_params='%s' board_params='%s'\n",
		  chip_params, board_params);

	p = skip_spaces(board_params);
	while (*p) {
		char tag = *p++;
		const char *end;
		size_t len;

		if (*p++ != '=') /* implicit NUL check */
			return -EINVAL;

		/* *p might be NUL here, if so end == p and len == 0 */
		end = strchrnul(p, ' ');
		len = end - p;

		/* leave 1 byte for NUL in destination string */
		if (len > (BRCMF_OTP_MAX_PARAM_LEN - 1))
			return -EINVAL;

		/* Copy len characters plus a NUL terminator */
		switch (tag) {
		case 'M':
			strscpy(devinfo->otp.module, p, len + 1);
			break;
		case 'V':
			strscpy(devinfo->otp.vendor, p, len + 1);
			break;
		case 'm':
			strscpy(devinfo->otp.version, p, len + 1);
			break;
		}

		/* Skip to next arg, if any */
		p = skip_spaces(end);
	}

	brcmf_dbg(PCIE, "OTP: module=%s vendor=%s version=%s\n",
		  devinfo->otp.module, devinfo->otp.vendor,
		  devinfo->otp.version);

	if (!devinfo->otp.module[0] ||
	    !devinfo->otp.vendor[0] ||
	    !devinfo->otp.version[0])
		return -EINVAL;

	devinfo->otp.valid = true;
	return 0;
}

static int
brcmf_pcie_parse_otp(struct brcmf_pciedev_info *devinfo, u8 *otp, size_t size)
{
	int p = 0;
	int ret = -EINVAL;

	brcmf_dbg(PCIE, "parse_otp size=%zd\n", size);

	while (p < (size - 1)) {
		u8 type = otp[p];
		u8 length = otp[p + 1];

		if (type == 0)
			break;

		if ((p + 2 + length) > size)
			break;

		switch (type) {
		case BRCMF_OTP_SYS_VENDOR:
			brcmf_dbg(PCIE, "OTP @ 0x%x (%d): SYS_VENDOR\n",
				  p, length);
			ret = brcmf_pcie_parse_otp_sys_vendor(devinfo,
							      &otp[p + 2],
							      length);
			break;
		case BRCMF_OTP_BRCM_CIS:
			brcmf_dbg(PCIE, "OTP @ 0x%x (%d): BRCM_CIS\n",
				  p, length);
			break;
		default:
			brcmf_dbg(PCIE, "OTP @ 0x%x (%d): Unknown type 0x%x\n",
				  p, length, type);
			break;
		}

		p += 2 + length;
	}

	return ret;
}

static int brcmf_pcie_read_otp(struct brcmf_pciedev_info *devinfo)
{
	const struct pci_dev *pdev = devinfo->pdev;
	struct brcmf_bus *bus = dev_get_drvdata(&pdev->dev);
	u32 coreid, base, words, idx, sromctl;
	u16 *otp;
	struct brcmf_core *core;
	int ret;

	switch (devinfo->ci->chip) {
	case BRCM_CC_4355_CHIP_ID:
		coreid = BCMA_CORE_CHIPCOMMON;
		base = 0x8c0;
		words = 0xb2;
		break;
	case BRCM_CC_4364_CHIP_ID:
		coreid = BCMA_CORE_CHIPCOMMON;
		base = 0x8c0;
		words = 0x1a0;
		break;
	case BRCM_CC_4377_CHIP_ID:
	case BRCM_CC_4378_CHIP_ID:
		coreid = BCMA_CORE_GCI;
		base = 0x1120;
		words = 0x170;
		break;
	case BRCM_CC_4387_CHIP_ID:
		coreid = BCMA_CORE_GCI;
		base = 0x113c;
		words = 0x170;
		break;
	default:
		/* OTP not supported on this chip */
		return 0;
	}

	core = brcmf_chip_get_core(devinfo->ci, coreid);
	if (!core) {
		brcmf_err(bus, "No OTP core\n");
		return -ENODEV;
	}

	if (coreid == BCMA_CORE_CHIPCOMMON) {
		/* Chips with OTP accessed via ChipCommon need additional
		 * handling to access the OTP
		 */
		brcmf_pcie_select_core(devinfo, coreid);
		sromctl = READCC32(devinfo, sromcontrol);

		if (!(sromctl & BCMA_CC_SROM_CONTROL_OTP_PRESENT)) {
			/* Chip lacks OTP, try without it... */
			brcmf_err(bus,
				  "OTP unavailable, using default firmware\n");
			return 0;
		}

		/* Map OTP to shadow area */
		WRITECC32(devinfo, sromcontrol,
			  sromctl | BCMA_CC_SROM_CONTROL_OTPSEL);
	}

	otp = kcalloc(words, sizeof(u16), GFP_KERNEL);
	if (!otp)
		return -ENOMEM;

	/* Map bus window to SROM/OTP shadow area in core */
	base = brcmf_pcie_buscore_prep_addr(devinfo->pdev, base + core->base);

	brcmf_dbg(PCIE, "OTP data:\n");
	for (idx = 0; idx < words; idx++) {
		otp[idx] = brcmf_pcie_read_reg16(devinfo, base + 2 * idx);
		brcmf_dbg(PCIE, "[%8x] 0x%04x\n", base + 2 * idx, otp[idx]);
	}

	if (coreid == BCMA_CORE_CHIPCOMMON) {
		brcmf_pcie_select_core(devinfo, coreid);
		WRITECC32(devinfo, sromcontrol, sromctl);
	}

	ret = brcmf_pcie_parse_otp(devinfo, (u8 *)otp, 2 * words);
	kfree(otp);

	return ret;
}

#define BRCMF_PCIE_FW_CODE	0
#define BRCMF_PCIE_FW_NVRAM	1
#define BRCMF_PCIE_FW_CLM	2
#define BRCMF_PCIE_FW_TXCAP	3

static void brcmf_pcie_setup(struct device *dev, int ret,
			     struct brcmf_fw_request *fwreq)
{
	const struct firmware *fw;
	void *nvram;
	struct brcmf_bus *bus;
	struct brcmf_pciedev *pcie_bus_dev;
	struct brcmf_pciedev_info *devinfo;
	struct brcmf_commonring **flowrings;
	u32 i, nvram_len;

	bus = dev_get_drvdata(dev);
	pcie_bus_dev = bus->bus_priv.pcie;
	devinfo = pcie_bus_dev->devinfo;

	pr_emerg("BCM4360 test.162: brcmf_pcie_setup CALLBACK INVOKED ret=%d\n", ret);
	brcmf_pcie_probe_armcr4_state(devinfo, "setup-entry");
	msleep(300);

	/* check firmware loading result */
	if (ret)
		goto fail;

	brcmf_pcie_probe_armcr4_state(devinfo, "pre-attach");
	pr_emerg("BCM4360 test.128: before brcmf_pcie_attach\n");
	brcmf_pcie_attach(devinfo);
	pr_emerg("BCM4360 test.128: after brcmf_pcie_attach\n");
	brcmf_pcie_probe_armcr4_state(devinfo, "post-attach");
	mdelay(300); /* test.134: force journal flush before next risky op */

	/* test.134: bisect crash site — pure memory ops, no MMIO */
	pr_emerg("BCM4360 test.134: post-attach before fw-ptr-extract\n");
	mdelay(300);

	fw = fwreq->items[BRCMF_PCIE_FW_CODE].binary;
	nvram = fwreq->items[BRCMF_PCIE_FW_NVRAM].nv_data.data;
	nvram_len = fwreq->items[BRCMF_PCIE_FW_NVRAM].nv_data.len;
	devinfo->clm_fw = fwreq->items[BRCMF_PCIE_FW_CLM].binary;
	devinfo->txcap_fw = fwreq->items[BRCMF_PCIE_FW_TXCAP].binary;
	kfree(fwreq);

	pr_emerg("BCM4360 test.134: after kfree(fwreq)\n");
	mdelay(300);

	pr_emerg("BCM4360 test.130: before brcmf_chip_get_raminfo\n");
	mdelay(300);
	ret = brcmf_chip_get_raminfo(devinfo->ci);
	if (ret) {
		brcmf_err(bus, "Failed to get RAM info\n");
		release_firmware(fw);
		brcmf_fw_nvram_free(nvram);
		goto fail;
	}
	pr_emerg("BCM4360 test.130: after brcmf_chip_get_raminfo\n");
	brcmf_pcie_probe_armcr4_state(devinfo, "post-raminfo");
	mdelay(300);

	/* Some of the firmwares have the size of the memory of the device
	 * defined inside the firmware. This is because part of the memory in
	 * the device is shared and the devision is determined by FW. Parse
	 * the firmware and adjust the chip memory size now.
	 */
	brcmf_pcie_adjust_ramsize(devinfo, (u8 *)fw->data, fw->size);
	pr_emerg("BCM4360 test.130: after brcmf_pcie_adjust_ramsize\n");
	mdelay(300);

	/* test.135: BusMaster re-enable removed. BAR2/TCM writes are CPU→device MMIO
	 * (posted writes) and do NOT need BusMaster. BusMaster allows device-initiated
	 * DMA; re-enabling it before ring buffers are set up may trigger stray DMA
	 * from the chip → crash. Will re-enable later (before IRQ request).
	 * test.134 result: crash happened right after BusMaster re-enable, suggesting
	 * this was the crash trigger. Testing without it for test.135.
	 */

	brcmf_pcie_probe_armcr4_state(devinfo, "pre-download");
	pr_emerg("BCM4360 test.163: before brcmf_pcie_download_fw_nvram (442KB BAR2 write)\n");
	mdelay(300);
	ret = brcmf_pcie_download_fw_nvram(devinfo, fw, nvram, nvram_len);

	/* test.163: BCM4360 early-return after download_fw_nvram. When
	 * bcm4360_skip_arm=1, the function intentionally returns -ENODEV after
	 * downloading fw + NVRAM + verifying TCM contents. fw/nvram are already
	 * released inside the function (release_firmware(fw), brcmf_fw_nvram_free(nvram)).
	 * Clean return avoids the fail: path which would call brcmf_fw_crashed +
	 * device_release_driver (extra complexity we don't need at this stage). */
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.163: download_fw_nvram returned ret=%d (expected -ENODEV for skip_arm=1)\n", ret);
		msleep(300);
		/* clm_fw/txcap_fw are NULL (optional, not present) but release them anyway */
		release_firmware(devinfo->clm_fw);
		devinfo->clm_fw = NULL;
		release_firmware(devinfo->txcap_fw);
		devinfo->txcap_fw = NULL;
		pr_emerg("BCM4360 test.163: fw released; returning from setup (state still DOWN)\n");
		msleep(300);
		return;
	}

	if (ret) {
		pr_emerg("BCM4360 test.130: brcmf_pcie_download_fw_nvram FAILED ret=%d\n", ret);
		goto fail;
	}
	pr_emerg("BCM4360 test.130: after brcmf_pcie_download_fw_nvram\n");
	mdelay(300);

	devinfo->state = BRCMFMAC_PCIE_STATE_UP;

	pr_emerg("BCM4360 test.130: before brcmf_pcie_init_ringbuffers\n");
	mdelay(300);
	ret = brcmf_pcie_init_ringbuffers(devinfo);
	if (ret) {
		pr_emerg("BCM4360 test.130: brcmf_pcie_init_ringbuffers FAILED ret=%d\n", ret);
		goto fail;
	}
	pr_emerg("BCM4360 test.130: after brcmf_pcie_init_ringbuffers\n");
	mdelay(300);

	ret = brcmf_pcie_init_scratchbuffers(devinfo);
	if (ret)
		goto fail;
	pr_emerg("BCM4360 test.130: after brcmf_pcie_init_scratchbuffers\n");
	mdelay(300);

	pr_emerg("BCM4360 test.130: before select_core PCIE2\n");
	mdelay(300);
	brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
	pr_emerg("BCM4360 test.130: before brcmf_pcie_request_irq\n");
	mdelay(300);
	ret = brcmf_pcie_request_irq(devinfo);
	if (ret) {
		pr_emerg("BCM4360 test.130: brcmf_pcie_request_irq FAILED ret=%d\n", ret);
		goto fail;
	}
	pr_emerg("BCM4360 test.130: after brcmf_pcie_request_irq\n");
	mdelay(300);

	/* hook the commonrings in the bus structure. */
	for (i = 0; i < BRCMF_NROF_COMMON_MSGRINGS; i++)
		bus->msgbuf->commonrings[i] =
				&devinfo->shared.commonrings[i]->commonring;

	flowrings = kcalloc(devinfo->shared.max_flowrings, sizeof(*flowrings),
			    GFP_KERNEL);
	if (!flowrings)
		goto fail;

	for (i = 0; i < devinfo->shared.max_flowrings; i++)
		flowrings[i] = &devinfo->shared.flowrings[i].commonring;
	bus->msgbuf->flowrings = flowrings;

	bus->msgbuf->rx_dataoffset = devinfo->shared.rx_dataoffset;
	bus->msgbuf->max_rxbufpost = devinfo->shared.max_rxbufpost;
	bus->msgbuf->max_flowrings = devinfo->shared.max_flowrings;

	init_waitqueue_head(&devinfo->mbdata_resp_wait);

	ret = brcmf_attach(&devinfo->pdev->dev);
	if (ret)
		goto fail;

	brcmf_pcie_bus_console_read(devinfo, false);

	brcmf_pcie_fwcon_timer(devinfo, true);

	return;

fail:
	brcmf_err(bus, "Dongle setup failed\n");
	brcmf_pcie_bus_console_read(devinfo, true);
	brcmf_fw_crashed(dev);
	device_release_driver(dev);
}

static struct brcmf_fw_request *
brcmf_pcie_prepare_fw_request(struct brcmf_pciedev_info *devinfo)
{
	struct brcmf_fw_request *fwreq;
	struct brcmf_fw_name fwnames[] = {
		{ ".bin", devinfo->fw_name },
		{ ".txt", devinfo->nvram_name },
		{ ".clm_blob", devinfo->clm_name },
		{ ".txcap_blob", devinfo->txcap_name },
	};

	fwreq = brcmf_fw_alloc_request(devinfo->ci->chip, devinfo->ci->chiprev,
				       brcmf_pcie_fwnames,
				       ARRAY_SIZE(brcmf_pcie_fwnames),
				       fwnames, ARRAY_SIZE(fwnames));
	if (!fwreq)
		return NULL;

	fwreq->items[BRCMF_PCIE_FW_CODE].type = BRCMF_FW_TYPE_BINARY;
	fwreq->items[BRCMF_PCIE_FW_NVRAM].type = BRCMF_FW_TYPE_NVRAM;
	fwreq->items[BRCMF_PCIE_FW_NVRAM].flags = BRCMF_FW_REQF_OPTIONAL;
	fwreq->items[BRCMF_PCIE_FW_CLM].type = BRCMF_FW_TYPE_BINARY;
	fwreq->items[BRCMF_PCIE_FW_CLM].flags = BRCMF_FW_REQF_OPTIONAL;
	fwreq->items[BRCMF_PCIE_FW_TXCAP].type = BRCMF_FW_TYPE_BINARY;
	fwreq->items[BRCMF_PCIE_FW_TXCAP].flags = BRCMF_FW_REQF_OPTIONAL;
	/* NVRAM reserves PCI domain 0 for Broadcom's SDK faked bus */
	fwreq->domain_nr = pci_domain_nr(devinfo->pdev->bus) + 1;
	fwreq->bus_nr = devinfo->pdev->bus->number;

	/* Apple platforms with fancy firmware/NVRAM selection */
	if (devinfo->settings->board_type &&
	    devinfo->settings->antenna_sku &&
	    devinfo->otp.valid) {
		const struct brcmf_otp_params *otp = &devinfo->otp;
		struct device *dev = &devinfo->pdev->dev;
		const char **bt = fwreq->board_types;

		brcmf_dbg(PCIE, "Apple board: %s\n",
			  devinfo->settings->board_type);

		/* Example: apple,shikoku-RASP-m-6.11-X3 */
		bt[0] = devm_kasprintf(dev, GFP_KERNEL, "%s-%s-%s-%s-%s",
				       devinfo->settings->board_type,
				       otp->module, otp->vendor, otp->version,
				       devinfo->settings->antenna_sku);
		bt[1] = devm_kasprintf(dev, GFP_KERNEL, "%s-%s-%s-%s",
				       devinfo->settings->board_type,
				       otp->module, otp->vendor, otp->version);
		bt[2] = devm_kasprintf(dev, GFP_KERNEL, "%s-%s-%s",
				       devinfo->settings->board_type,
				       otp->module, otp->vendor);
		bt[3] = devm_kasprintf(dev, GFP_KERNEL, "%s-%s",
				       devinfo->settings->board_type,
				       otp->module);
		bt[4] = devm_kasprintf(dev, GFP_KERNEL, "%s-%s",
				       devinfo->settings->board_type,
				       devinfo->settings->antenna_sku);
		bt[5] = devinfo->settings->board_type;

		if (!bt[0] || !bt[1] || !bt[2] || !bt[3] || !bt[4]) {
			kfree(fwreq);
			return NULL;
		}
	} else {
		brcmf_dbg(PCIE, "Board: %s\n", devinfo->settings->board_type);
		fwreq->board_types[0] = devinfo->settings->board_type;
	}

	return fwreq;
}

#ifdef DEBUG
static void
brcmf_pcie_fwcon_timer(struct brcmf_pciedev_info *devinfo, bool active)
{
	if (!active) {
		if (devinfo->console_active) {
			del_timer_sync(&devinfo->timer);
			devinfo->console_active = false;
		}
		return;
	}

	/* don't start the timer */
	if (devinfo->state != BRCMFMAC_PCIE_STATE_UP ||
	    !devinfo->console_interval || !BRCMF_FWCON_ON())
		return;

	if (!devinfo->console_active) {
		devinfo->timer.expires = jiffies + devinfo->console_interval;
		add_timer(&devinfo->timer);
		devinfo->console_active = true;
	} else {
		/* Reschedule the timer */
		mod_timer(&devinfo->timer, jiffies + devinfo->console_interval);
	}
}

static void
brcmf_pcie_fwcon(struct timer_list *t)
{
	struct brcmf_pciedev_info *devinfo = from_timer(devinfo, t, timer);

	if (!devinfo->console_active)
		return;

	brcmf_pcie_bus_console_read(devinfo, false);

	/* Reschedule the timer if console interval is not zero */
	mod_timer(&devinfo->timer, jiffies + devinfo->console_interval);
}

static int brcmf_pcie_console_interval_get(void *data, u64 *val)
{
	struct brcmf_pciedev_info *devinfo = data;

	*val = devinfo->console_interval;

	return 0;
}

static int brcmf_pcie_console_interval_set(void *data, u64 val)
{
	struct brcmf_pciedev_info *devinfo = data;

	if (val > MAX_CONSOLE_INTERVAL)
		return -EINVAL;

	devinfo->console_interval = val;

	if (!val && devinfo->console_active)
		brcmf_pcie_fwcon_timer(devinfo, false);
	else if (val)
		brcmf_pcie_fwcon_timer(devinfo, true);

	return 0;
}

DEFINE_SIMPLE_ATTRIBUTE(brcmf_pcie_console_interval_fops,
			brcmf_pcie_console_interval_get,
			brcmf_pcie_console_interval_set,
			"%llu\n");

static void brcmf_pcie_debugfs_create(struct device *dev)
{
	struct brcmf_bus *bus_if = dev_get_drvdata(dev);
	struct brcmf_pub *drvr = bus_if->drvr;
	struct brcmf_pciedev *pcie_bus_dev = bus_if->bus_priv.pcie;
	struct brcmf_pciedev_info *devinfo = pcie_bus_dev->devinfo;
	struct dentry *dentry = brcmf_debugfs_get_devdir(drvr);

	if (IS_ERR_OR_NULL(dentry))
		return;

	devinfo->console_interval = BRCMF_CONSOLE;

	debugfs_create_file("console_interval", 0644, dentry, devinfo,
			    &brcmf_pcie_console_interval_fops);
}

#else
void brcmf_pcie_fwcon_timer(struct brcmf_pciedev_info *devinfo, bool active)
{
}

static void brcmf_pcie_debugfs_create(struct device *dev)
{
}
#endif

/* Forward declaration for pci_match_id() call */
static const struct pci_device_id brcmf_pcie_devid_table[];

static int
brcmf_pcie_probe(struct pci_dev *pdev, const struct pci_device_id *id)
{
	int ret;
	struct brcmf_fw_request *fwreq;
	struct brcmf_pciedev_info *devinfo;
	struct brcmf_pciedev *pcie_bus_dev;
	struct brcmf_core *core;
	struct brcmf_bus *bus;

	if (!id) {
		id = pci_match_id(brcmf_pcie_devid_table, pdev);
		if (!id) {
			pci_err(pdev, "Error could not find pci_device_id for %x:%x\n", pdev->vendor, pdev->device);
			return -ENODEV;
		}
	}

	/* test.127: add very early marker in probe entry to confirm probe is called */
	pr_emerg("BCM4360 test.128: PROBE ENTRY (device=%04x vendor=%04x id=%p)\n",
		 pdev->device, pdev->vendor, id);
	msleep(300); /* test.158: flush PROBE ENTRY before proceeding */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.158: probe entry flush done — proceeding\n");
		msleep(300); /* test.158: flush before kzalloc */
	}

	brcmf_dbg(PCIE, "Enter %x:%x\n", pdev->vendor, pdev->device);

	ret = -ENOMEM;
	devinfo = kzalloc(sizeof(*devinfo), GFP_KERNEL);
	if (devinfo == NULL)
		return ret;

	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.127: devinfo allocated, before pdev assign\n");
	}

	devinfo->pdev = pdev;
	pcie_bus_dev = NULL;

	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.127: devinfo->pdev assigned, before SBR\n");
	}

	/* test.53: secondary bus reset via upstream bridge, before chip_attach.
	 * test.52 RESULT: INSTANT CRASH during chip enumeration BAR0 MMIO reads.
	 *   test.52 logged "BCM4360 debug: BAR0=..." (from brcmf_pcie_get_resource in
	 *   chip_attach's prepare callback) but crashed before "BCM4360 EFI state:" in
	 *   brcmf_pcie_reset_device — meaning crash was during chip ID enumeration reads.
	 * Root cause hypothesis: tests 50/51 left BCM4360 in bad state (watchdog or
	 *   select_core during ARM init corrupted PCIe/AXI state), causing BAR0 MMIO
	 *   reads to fail (PCIe Completion Timeout → NMI → host crash).
	 * Fix: do host-side PCIe secondary bus reset (SBR) via upstream bridge before
	 *   chip_attach. SBR resets the BCM4360's AXI fabric WITHOUT needing BAR0 MMIO,
	 *   using only host PCI config cycles to the bridge.
	 * After SBR + pci_restore_state: BCM4360 should be in clean power-on-reset state.
	 *
	 * test.53 RESULT: INSTANT CRASH at poll loop iter 1 after WRITECC32(watchdog, 0x7FFFFFFF).
	 *   SBR CONFIRMED WORKING: BAR0 probe = 0x15034360 (alive), chip_attach succeeded,
	 *   BBPLL up, ARM released, iter 1 logged WDOG_PRE=0 PMUWDOG=0 then CRASH.
	 *   Write 0x7FFFFFFF to ChipCommon watchdog → "iter 1" logged → crash on next BAR2 read.
	 *   SBR retained for test.54 to keep clean device state.
	 */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID && pdev->bus && pdev->bus->self) {
		struct pci_dev *bridge = pdev->bus->self;
		u16 bc = 0;

		pci_save_state(pdev);
		pci_read_config_word(bridge, PCI_BRIDGE_CONTROL, &bc);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.53: SBR via bridge %s (bridge_ctrl=0x%04x) before chip_attach\n",
			  pci_name(bridge), bc);
		pci_write_config_word(bridge, PCI_BRIDGE_CONTROL,
				      bc | PCI_BRIDGE_CTL_BUS_RESET);
		msleep(10);  /* PCIe spec: hold reset ≥1ms */
		pci_write_config_word(bridge, PCI_BRIDGE_CONTROL, bc);
		msleep(500); /* test.131: increased from 200ms — chip_attach MMIO crashed at 200ms after
			      * multiple crash cycles; 500ms gives AXI fabric more stabilization time */
		pci_restore_state(pdev);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.53: SBR complete — bridge_ctrl restored\n");
	}

	pr_emerg("BCM4360 test.158: before brcmf_chip_attach\n");
	msleep(300); /* test.158: flush before chip_attach MMIO */
	devinfo->ci = brcmf_chip_attach(devinfo, pdev->device,
					&brcmf_pcie_buscore_ops);
	if (IS_ERR(devinfo->ci)) {
		ret = PTR_ERR(devinfo->ci);
		devinfo->ci = NULL;
		pr_emerg("BCM4360 test.158: chip_attach FAILED ret=%d\n", ret);
		goto fail;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.119: brcmf_chip_attach returned successfully\n");
		msleep(300); /* test.158: flush chip_attach success before BusMaster/ASPM */
	}

	/* test.158: REMOVED duplicate probe-level ARM halt.
	 * test.157 proved chip_attach/buscore_reset already halted ARM (test.145 path);
	 * the duplicate halt's RESET_CTL=1 wedged the ARM core's BAR0 window and the
	 * next write triggered an MCE. Skip the duplicate halt entirely.
	 *
	 * test.158 scope: BusMaster clear + ASPM disable (both config-space ops, no BAR0).
	 * Early return after BusMaster/ASPM — before reginfo/allocs.
	 */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		u16 lnkctl_before, lnkctl_after;
		struct pci_dev *bridge;
		u16 rp_lnkctl_before, rp_lnkctl_after;
		struct brcmf_core *arm_core;

		/* Log ARM CR4 base for reference (no MMIO to ARM core). */
		arm_core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_ARM_CR4);
		if (arm_core)
			dev_emerg(&pdev->dev,
				  "BCM4360 test.158: ARM CR4 core->base=0x%08x (no MMIO issued)\n",
				  arm_core->base);

		pr_emerg("BCM4360 test.158: about to pci_clear_master (config-space write)\n");
		msleep(300); /* test.158: flush before pci_clear_master */
		pci_clear_master(pdev);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.158: BusMaster cleared after chip_attach\n");
		msleep(300); /* test.158: flush after pci_clear_master */

		pr_emerg("BCM4360 test.158: about to read LnkCtl before ASPM disable\n");
		msleep(300); /* test.158: flush before lnkctl read */
		pcie_capability_read_word(pdev, PCI_EXP_LNKCTL, &lnkctl_before);
		pr_emerg("BCM4360 test.158: LnkCtl read before=0x%04x — disabling ASPM\n",
			 lnkctl_before);
		msleep(300); /* test.158: flush after lnkctl read */

		pci_disable_link_state(pdev, PCIE_LINK_STATE_ASPM_ALL);
		pr_emerg("BCM4360 test.158: pci_disable_link_state returned — reading LnkCtl\n");
		msleep(300); /* test.158: flush after disable_link_state */

		pcie_capability_read_word(pdev, PCI_EXP_LNKCTL, &lnkctl_after);
		dev_emerg(&pdev->dev,
			  "BCM4360 test.158: ASPM disabled; LnkCtl before=0x%04x after=0x%04x ASPM-bits-after=0x%x\n",
			  lnkctl_before, lnkctl_after, lnkctl_after & PCI_EXP_LNKCTL_ASPMC);
		msleep(300); /* test.176: flush before root-port ASPM/CLKPM work */

		/* test.176 keeps the root-port LnkCtl logging from test.172 for
		 * comparability. test.172 showed root-port ASPM/CLKPM was already
		 * off, so the main discriminator is now immediate return after
		 * fw write completion in brcmf_pcie_download_fw_nvram().
		 */
		bridge = pci_upstream_bridge(pdev);
		if (bridge) {
			pcie_capability_read_word(bridge, PCI_EXP_LNKCTL,
						  &rp_lnkctl_before);
			dev_emerg(&pdev->dev,
				  "BCM4360 test.176: root port %s LnkCtl before=0x%04x ASPM=0x%x CLKREQ=%s — disabling L0s/L1/CLKPM\n",
				  pci_name(bridge), rp_lnkctl_before,
				  rp_lnkctl_before & PCI_EXP_LNKCTL_ASPMC,
				  rp_lnkctl_before & PCI_EXP_LNKCTL_CLKREQ_EN ? "on" : "off");
			msleep(300);

			pci_disable_link_state(bridge, PCIE_LINK_STATE_L0S |
					       PCIE_LINK_STATE_L1 |
					       PCIE_LINK_STATE_CLKPM);
			pr_emerg("BCM4360 test.176: root-port pci_disable_link_state returned — reading LnkCtl\n");
			msleep(300);

			pcie_capability_read_word(bridge, PCI_EXP_LNKCTL,
						  &rp_lnkctl_after);
			dev_emerg(&pdev->dev,
				  "BCM4360 test.176: root port %s LnkCtl after=0x%04x ASPM=0x%x CLKREQ=%s\n",
				  pci_name(bridge), rp_lnkctl_after,
				  rp_lnkctl_after & PCI_EXP_LNKCTL_ASPMC,
				  rp_lnkctl_after & PCI_EXP_LNKCTL_CLKREQ_EN ? "on" : "off");
			msleep(300);
		} else {
			dev_emerg(&pdev->dev,
				  "BCM4360 test.176: no upstream bridge found; root-port ASPM/CLKPM disable skipped\n");
			msleep(300);
		}

		msleep(300); /* test.159: flush before reginfo section */
	}

	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.159: before PCIE2 core/reginfo setup\n");
		msleep(300); /* test.159: flush before PCIE2 core get */
	}
	core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_PCIE2);
	if (core->rev >= 64)
		devinfo->reginfo = &brcmf_reginfo_64;
	else
		devinfo->reginfo = &brcmf_reginfo_default;
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.159: reginfo selected (pcie2 rev=%u)\n",
			  core->rev);
		msleep(300); /* test.159: flush after reginfo select */
	}

	pcie_bus_dev = kzalloc(sizeof(*pcie_bus_dev), GFP_KERNEL);
	if (pcie_bus_dev == NULL) {
		ret = -ENOMEM;
		goto fail;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.159: pcie_bus_dev allocated\n");
		msleep(300); /* test.159: flush after pcie_bus_dev kzalloc */
	}

	/* For BCM4360, bypass full module param/ACPI/OF/DMI probe for now (test.123) */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		devinfo->settings = kzalloc(sizeof(*devinfo->settings), GFP_KERNEL);
	} else {
		devinfo->settings = brcmf_get_module_param(&devinfo->pdev->dev,
							   BRCMF_BUSTYPE_PCIE,
							   devinfo->ci->chip,
							   devinfo->ci->chiprev);
	}
	if (!devinfo->settings) {
		ret = -ENOMEM;
		goto fail;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.159: settings allocated (BCM4360 dummy path)\n");
		msleep(300); /* test.159: flush after settings alloc */
	}

	bus = kzalloc(sizeof(*bus), GFP_KERNEL);
	if (!bus) {
		ret = -ENOMEM;
		goto fail;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev, "BCM4360 test.159: bus allocated\n");
		msleep(300); /* test.159: flush after bus kzalloc */
	}
	bus->msgbuf = kzalloc(sizeof(*bus->msgbuf), GFP_KERNEL);
	if (!bus->msgbuf) {
		ret = -ENOMEM;
		kfree(bus);
		goto fail;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev, "BCM4360 test.159: msgbuf allocated\n");
		msleep(300); /* test.159: flush after msgbuf kzalloc */
	}

	/* hook it all together. */
	pcie_bus_dev->devinfo = devinfo;
	pcie_bus_dev->bus = bus;
	bus->dev = &pdev->dev;
	bus->bus_priv.pcie = pcie_bus_dev;
	bus->ops = &brcmf_pcie_bus_ops;
	bus->proto_type = BRCMF_PROTO_MSGBUF;
	bus->fwvid = id->driver_data;
	bus->chip = devinfo->coreid;
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev, "BCM4360 test.159: struct wiring done — before pci_pme_capable\n");
		msleep(300); /* test.159: flush before pci_pme_capable */
	}
	bus->wowl_supported = pci_pme_capable(pdev, PCI_D3hot);
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.159: after pci_pme_capable wowl=%d\n",
			  bus->wowl_supported);
		msleep(300); /* test.159: flush after pci_pme_capable */
	}
	dev_set_drvdata(&pdev->dev, bus);
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev, "BCM4360 test.160: drvdata set — before brcmf_alloc\n");
		msleep(300); /* test.160: flush before brcmf_alloc */
	}

	ret = brcmf_alloc(&devinfo->pdev->dev, devinfo->settings);
	if (ret)
		goto fail_bus;
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.160: brcmf_alloc complete — wiphy allocated\n");
		msleep(300); /* test.160: flush after brcmf_alloc */
	}

	/* test.124: bypass OTP read for BCM4360 — known to have OTP */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.160: OTP read bypassed — OTP not needed\n");
		ret = 0;
		msleep(300); /* test.160: flush after OTP bypass */
	} else {
		ret = brcmf_pcie_read_otp(devinfo);
	}
	if (ret) {
		brcmf_err(bus, "failed to parse OTP\n");
		goto fail_brcmf;
	}

#ifdef DEBUG
	/* Set up the fwcon timer */
	timer_setup(&devinfo->timer, brcmf_pcie_fwcon, 0);
#endif

	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.160: before prepare_fw_request\n");
		msleep(300); /* test.160: flush before prepare_fw_request */
	}
	fwreq = brcmf_pcie_prepare_fw_request(devinfo);
	if (!fwreq) {
		ret = -ENOMEM;
		goto fail_brcmf;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.160: firmware request prepared\n");
		msleep(300); /* test.160: flush after prepare_fw_request */
	}

	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		pr_emerg("BCM4360 test.161: calling brcmf_fw_get_firmwares — async callback expected\n");
		msleep(300); /* test.161: flush final marker before fw request */
	}
	ret = brcmf_fw_get_firmwares(bus->dev, fwreq, brcmf_pcie_setup);
	if (ret < 0) {
		kfree(fwreq);
		goto fail_brcmf;
	}
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		dev_emerg(&pdev->dev,
			  "BCM4360 test.161: brcmf_fw_get_firmwares returned %d (async/success; callback will fire)\n",
			  ret);
		msleep(300);
	}
	return 0;

fail_brcmf:
	brcmf_free(&devinfo->pdev->dev);
fail_bus:
	kfree(bus->msgbuf);
	kfree(bus);
fail:
	brcmf_err(NULL, "failed %x:%x\n", pdev->vendor, pdev->device);
	brcmf_pcie_release_resource(devinfo);
	if (devinfo->ci)
		brcmf_chip_detach(devinfo->ci);
	if (devinfo->settings)
		brcmf_release_module_param(devinfo->settings);
	kfree(pcie_bus_dev);
	kfree(devinfo);
	return ret;
}


static void
brcmf_pcie_remove(struct pci_dev *pdev)
{
	struct brcmf_pciedev_info *devinfo;
	struct brcmf_bus *bus;

	brcmf_dbg(PCIE, "Enter\n");

	bus = dev_get_drvdata(&pdev->dev);
	if (bus == NULL)
		return;

	devinfo = bus->bus_priv.pcie->devinfo;

	/* test.161: BCM4360 short-circuit — when firmware boot never completed
	 * (state != UP), skip the MMIO-touching cleanup (console_read,
	 * intr_disable, release_ringbuffers, release_irq) and skip msgbuf
	 * flowrings kfree (ringbuffers never allocated them). */
	if (pdev->device == BRCM_PCIE_4360_DEVICE_ID &&
	    devinfo->state != BRCMFMAC_PCIE_STATE_UP) {
		pr_emerg("BCM4360 test.161: remove() short-circuit — state=%d != UP; skipping MMIO cleanup\n",
			 devinfo->state);
		msleep(300);
		brcmf_detach(&pdev->dev);
		brcmf_free(&pdev->dev);
		kfree(bus->bus_priv.pcie);
		kfree(bus->msgbuf);
		kfree(bus);
		brcmf_pcie_release_resource(devinfo);
		release_firmware(devinfo->clm_fw);
		release_firmware(devinfo->txcap_fw);
		if (devinfo->ci)
			brcmf_chip_detach(devinfo->ci);
		if (devinfo->settings)
			brcmf_release_module_param(devinfo->settings);
		kfree(devinfo);
		dev_set_drvdata(&pdev->dev, NULL);
		pr_emerg("BCM4360 test.161: remove() short-circuit complete\n");
		return;
	}

	brcmf_pcie_bus_console_read(devinfo, false);
	brcmf_pcie_fwcon_timer(devinfo, false);

	devinfo->state = BRCMFMAC_PCIE_STATE_DOWN;
	if (devinfo->ci)
		brcmf_pcie_intr_disable(devinfo);

	brcmf_detach(&pdev->dev);
	brcmf_free(&pdev->dev);

	kfree(bus->bus_priv.pcie);
	kfree(bus->msgbuf->flowrings);
	kfree(bus->msgbuf);
	kfree(bus);

	brcmf_pcie_release_irq(devinfo);
	brcmf_pcie_release_scratchbuffers(devinfo);
	brcmf_pcie_release_ringbuffers(devinfo);
	brcmf_pcie_reset_device(devinfo);
	brcmf_pcie_release_resource(devinfo);
	release_firmware(devinfo->clm_fw);
	release_firmware(devinfo->txcap_fw);

	if (devinfo->ci)
		brcmf_chip_detach(devinfo->ci);
	if (devinfo->settings)
		brcmf_release_module_param(devinfo->settings);

	kfree(devinfo);
	dev_set_drvdata(&pdev->dev, NULL);
}


#ifdef CONFIG_PM


static int brcmf_pcie_pm_enter_D3(struct device *dev)
{
	struct brcmf_pciedev_info *devinfo;
	struct brcmf_bus *bus;

	brcmf_dbg(PCIE, "Enter\n");

	bus = dev_get_drvdata(dev);
	devinfo = bus->bus_priv.pcie->devinfo;

	brcmf_pcie_fwcon_timer(devinfo, false);
	brcmf_bus_change_state(bus, BRCMF_BUS_DOWN);

	devinfo->mbdata_completed = false;
	brcmf_pcie_send_mb_data(devinfo, BRCMF_H2D_HOST_D3_INFORM);

	wait_event_timeout(devinfo->mbdata_resp_wait, devinfo->mbdata_completed,
			   BRCMF_PCIE_MBDATA_TIMEOUT);
	if (!devinfo->mbdata_completed) {
		brcmf_err(bus, "Timeout on response for entering D3 substate\n");
		brcmf_bus_change_state(bus, BRCMF_BUS_UP);
		return -EIO;
	}

	devinfo->state = BRCMFMAC_PCIE_STATE_DOWN;

	return 0;
}


static int brcmf_pcie_pm_leave_D3(struct device *dev)
{
	struct brcmf_pciedev_info *devinfo;
	struct brcmf_bus *bus;
	struct pci_dev *pdev;
	int err;

	brcmf_dbg(PCIE, "Enter\n");

	bus = dev_get_drvdata(dev);
	devinfo = bus->bus_priv.pcie->devinfo;
	brcmf_dbg(PCIE, "Enter, dev=%p, bus=%p\n", dev, bus);

	/* Check if device is still up and running, if so we are ready */
	if (brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->intmask) != 0) {
		brcmf_dbg(PCIE, "Try to wakeup device....\n");
		if (brcmf_pcie_send_mb_data(devinfo, BRCMF_H2D_HOST_D0_INFORM))
			goto cleanup;
		brcmf_dbg(PCIE, "Hot resume, continue....\n");
		devinfo->state = BRCMFMAC_PCIE_STATE_UP;
		brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
		brcmf_bus_change_state(bus, BRCMF_BUS_UP);
		brcmf_pcie_intr_enable(devinfo);
		brcmf_pcie_hostready(devinfo);
		brcmf_pcie_fwcon_timer(devinfo, true);
		return 0;
	}

cleanup:
	brcmf_chip_detach(devinfo->ci);
	devinfo->ci = NULL;
	pdev = devinfo->pdev;
	brcmf_pcie_remove(pdev);

	err = brcmf_pcie_probe(pdev, NULL);
	if (err)
		__brcmf_err(NULL, __func__, "probe after resume failed, err=%d\n", err);

	return err;
}


static const struct dev_pm_ops brcmf_pciedrvr_pm = {
	.suspend = brcmf_pcie_pm_enter_D3,
	.resume = brcmf_pcie_pm_leave_D3,
	.freeze = brcmf_pcie_pm_enter_D3,
	.restore = brcmf_pcie_pm_leave_D3,
};


#endif /* CONFIG_PM */


#define BRCMF_PCIE_DEVICE(dev_id, fw_vend) \
	{ \
		BRCM_PCIE_VENDOR_ID_BROADCOM, (dev_id), \
		PCI_ANY_ID, PCI_ANY_ID, \
		PCI_CLASS_NETWORK_OTHER << 8, 0xffff00, \
		BRCMF_FWVENDOR_ ## fw_vend \
	}
#define BRCMF_PCIE_DEVICE_SUB(dev_id, subvend, subdev, fw_vend) \
	{ \
		BRCM_PCIE_VENDOR_ID_BROADCOM, (dev_id), \
		(subvend), (subdev), \
		PCI_CLASS_NETWORK_OTHER << 8, 0xffff00, \
		BRCMF_FWVENDOR_ ## fw_vend \
	}

static const struct pci_device_id brcmf_pcie_devid_table[] = {
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4350_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE_SUB(0x4355, BRCM_PCIE_VENDOR_ID_BROADCOM, 0x4355, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4354_RAW_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4355_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4356_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43567_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43570_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43570_RAW_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4358_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4359_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4360_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43602_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43602_2G_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43602_5G_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43602_RAW_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4364_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4365_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4365_2G_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4365_5G_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE_SUB(0x4365, BRCM_PCIE_VENDOR_ID_BROADCOM, 0x4365, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4366_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4366_2G_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4366_5G_DEVICE_ID, BCA),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4371_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_43596_DEVICE_ID, CYW),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4377_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4378_DEVICE_ID, WCC),
	BRCMF_PCIE_DEVICE(BRCM_PCIE_4387_DEVICE_ID, WCC),

	{ /* end: all zeroes */ }
};


MODULE_DEVICE_TABLE(pci, brcmf_pcie_devid_table);


static struct pci_driver brcmf_pciedrvr = {
	.name = KBUILD_MODNAME,
	.id_table = brcmf_pcie_devid_table,
	.probe = brcmf_pcie_probe,
	.remove = brcmf_pcie_remove,
#ifdef CONFIG_PM
	.driver.pm = &brcmf_pciedrvr_pm,
#endif
	.driver.coredump = brcmf_dev_coredump,
};


/* test.144/145/146/147/148: observability probe — log module_init entry.
 * BAR0 MMIO on a fresh uninitialized chip (no prior driver run) returns UR
 * which crashes the host.  ARM halt is now done in brcmf_pcie_buscore_reset()
 * after chip_attach() has initialized the PCIe-to-backplane bridge. */
void brcmf_pcie_early_arm_halt(void)
{
	pr_emerg("BCM4360 test.176: module_init entry — immediate return after complete BAR2 fw write\n");
}

int brcmf_pcie_register(void)
{
	int ret;

	pr_emerg("BCM4360 test.176: brcmf_pcie_register() entry\n");
	msleep(300); /* flush marker before pci_register_driver */
	pr_emerg("BCM4360 test.176: before pci_register_driver\n");
	msleep(300); /* flush — if crash here, it's in pci_register_driver kernel code */
	ret = pci_register_driver(&brcmf_pciedrvr);
	pr_emerg("BCM4360 test.176: pci_register_driver returned ret=%d\n", ret);
	return ret;
}


void brcmf_pcie_exit(void)
{
	brcmf_dbg(PCIE, "Enter\n");
	pci_unregister_driver(&brcmf_pciedrvr);
}
