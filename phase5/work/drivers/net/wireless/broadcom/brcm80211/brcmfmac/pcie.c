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

/* BCM4360 test.235: skip the brcmf_chip_set_active call AFTER the test.234
 * zero+verify block has run. Lets us observe the zero loop's full output in
 * journald (no wedge => no tail truncation), characterize the pre-zero TCM
 * fingerprint, and confirm the verify lands at 0/71 non-zero. test.230
 * baseline for safety. Default 0 (test.234 path: call set_active). */
static int bcm4360_test235_skip_set_active;
module_param(bcm4360_test235_skip_set_active, int, 0644);
MODULE_PARM_DESC(bcm4360_test235_skip_set_active, "BCM4360 test.235: skip brcmf_chip_set_active after zero+verify (1=skip, 0=normal test.234 path)");

/* BCM4360 test.236: force the upstream Apple-style random_seed write right
 * after the live NVRAM write. Upstream gates this block on otp.valid (which
 * is FALSE on the BCM4360 path because OTP read is bypassed at probe), AND
 * places it in dead code after an early -ENODEV return — so we never write
 * the seed today. Apple BCM4360/firmware comment in upstream notes "Some
 * Apple chips/firmwares expect a buffer of random data to be present before
 * NVRAM" (sizeof(footer)+256 B with magic 0xfeedc0de). When this param is
 * set, also disable the test.234 zero block (which would clobber the seed).
 * Default 0 (no seed write — test.234/235 behaviour). */
static int bcm4360_test236_force_seed;
module_param(bcm4360_test236_force_seed, int, 0644);
MODULE_PARM_DESC(bcm4360_test236_force_seed, "BCM4360 test.236: force Apple random_seed write before set_active (1=force, 0=do not write)");

/* BCM4360 test.237: extended dwell ladder after brcmf_chip_set_active.
 * Replaces the short t+100..t+1000 chain with a ladder reaching t+30s so
 * we can bracket the actual wedge moment. Test.236 Run B landed t+700ms
 * as the last journald breadcrumb — lower bound only. Journald tail-
 * truncation budget is not calibrated, so we can't back out the wedge
 * from "last flushed" alone. Use switch msleep for >1s waits to avoid
 * pinning the CPU + triggering softlockup from our own thread. Pair
 * with bcm4360_test236_force_seed=1 for the seed-present comparison run.
 * Default 0 (short t+100..t+1000 chain). */
static int bcm4360_test237_extended_dwells;
module_param(bcm4360_test237_extended_dwells, int, 0644);
MODULE_PARM_DESC(bcm4360_test237_extended_dwells, "BCM4360 test.237: extend post-set_active dwell ladder to t+30s (1=extended, 0=short t+100..t+1000)");

/* BCM4360 test.238: ultra-extended dwell ladder to bracket wedge beyond
 * t+30s. Test.237 landed t+25000ms as the last journald breadcrumb —
 * either the wedge is inside [t+25s, t+30s) with live-flush tail cutoff,
 * or the wedge is further out (≥t+40s) with full tail-truncation. Fine-
 * grain through the suspect window (t+26..t+30s, 1s steps) and extend
 * out to t+120s to tell these apart. Sub-second and coarser dwells
 * preserved for sanity. Pair with bcm4360_test236_force_seed=1.
 * Default 0 (off; use test237 or short ladder). */
static int bcm4360_test238_ultra_dwells;
module_param(bcm4360_test238_ultra_dwells, int, 0644);
MODULE_PARM_DESC(bcm4360_test238_ultra_dwells, "BCM4360 test.238: ultra-extended dwell ladder to t+120s with 1s fine-grain through [t+25..t+30] window (1=ultra, 0=off)");

/* BCM4360 test.239: while the test.238 ladder runs, poll TCM[ramsize-4]
 * at each dwell point. Upstream brcmfmac convention: fw overwrites that
 * slot with sharedram_addr (pcie_shared struct pointer) once its init
 * completes. Before set_active, we leave the NVRAM length marker
 * 0xffc70038 there. So polling diagnoses when (if ever) fw writes its
 * shared-struct pointer during the 90s window test.238 proved fw is
 * alive. Pair with force_seed=1 + ultra_dwells=1. Zero-side-effect
 * (read-only MMIO). Default 0. */
static int bcm4360_test239_poll_sharedram;
module_param(bcm4360_test239_poll_sharedram, int, 0644);
MODULE_PARM_DESC(bcm4360_test239_poll_sharedram, "BCM4360 test.239: poll TCM[ramsize-4] sharedram pointer at every test.238 dwell breadcrumb (1=poll, 0=off)");

/* BCM4360 test.240: ring upstream's "HostRDY" doorbell (write 1 to PCIE2
 * H2D_MAILBOX_1, BAR0 + 0x144) at the t+2000ms dwell breadcrumb to test
 * whether fw is blocked on a host-side handshake. Test.239 proved fw
 * never overwrites TCM[ramsize-4] with sharedram_addr in ≥90s — far
 * past upstream's BRCMF_PCIE_FW_UP_TIMEOUT (5s). One reading is fw is
 * waiting on host doorbell ring before it advances to shared-struct
 * setup. Single-write side effect: pure register store; if fw asserts
 * a D2H IRQ in response, host has no MSI installed yet so it bit-buckets.
 * Pair with poll_sharedram=1 + wide_poll=1 to observe any tail-TCM
 * change post-ring. Default 0. */
static int bcm4360_test240_ring_h2d_db1;
module_param(bcm4360_test240_ring_h2d_db1, int, 0644);
MODULE_PARM_DESC(bcm4360_test240_ring_h2d_db1, "BCM4360 test.240: ring H2D_MAILBOX_1 (BAR0+0x144=1) at t+2000ms dwell (1=ring, 0=off)");

/* BCM4360 test.240: scan a wider tail-TCM window (16 dwords,
 * ramsize-64..ramsize-4) at every test.239 poll point instead of just
 * the single sharedram slot. Fw might write a status/heartbeat or even
 * its shared-struct address at a non-standard offset; one extra
 * MMIO read per dwell costs negligible vs the test.239 baseline that
 * already proved fw doesn't watchdog on bus activity. Read-only MMIO,
 * zero-side-effect. Pair with poll_sharedram=1. Default 0. */
static int bcm4360_test240_wide_poll;
module_param(bcm4360_test240_wide_poll, int, 0644);
MODULE_PARM_DESC(bcm4360_test240_wide_poll, "BCM4360 test.240: scan tail-TCM [ramsize-64..ramsize-4] (15 dwords) at every dwell instead of single slot (1=wide, 0=narrow)");

/* BCM4360 test.241: write-verify that driver BAR0 writes actually
 * land on the chip. Test.240 rang H2D_MAILBOX_1 (BAR0+0x144) with
 * value=1 and read back 0x00000000 — uninterpretable without
 * proving the BAR0-write path itself. When set, just after
 * pci_set_master and before set_active: read MAILBOXMASK baseline
 * (expect 0), write sentinel 0xDEADBEEF, read back (expect
 * 0xDEADBEEF), write 0 to restore (expect 0). MAILBOXMASK is a
 * RAM-backed mask register upstream already uses — round-trip of
 * sentinel + zero leaves the chip in the same state as a run
 * without test.241. Default 0. */
static int bcm4360_test241_writeverify;
module_param(bcm4360_test241_writeverify, int, 0644);
MODULE_PARM_DESC(bcm4360_test241_writeverify, "BCM4360 test.241: BAR0 write-path verification (sentinel round-trip on MAILBOXMASK) post-pci_set_master, pre-set_active (1=verify, 0=off)");

/* BCM4360 test.242: repeat the test.241 MAILBOXMASK round-trip at
 * dwell points INSIDE the ultra ladder — t+100ms and t+2000ms —
 * i.e. POST-set_active. test.241 failed at the pre-FORCEHT stage
 * but that's confounded with "MAILBOXMASK is in a clock/reset
 * domain that's only writable later". This test measures the
 * write path at the same stage test.240 rang DB1, so we can
 * cleanly discriminate "BAR0 writes broken" from "stage-gated
 * register". Safe: MAILBOXMASK is the same register
 * brcmf_pcie_intr_disable writes 0 to in production cleanup.
 * Default 0. */
static int bcm4360_test242_writeverify_postactive;
module_param(bcm4360_test242_writeverify_postactive, int, 0644);
MODULE_PARM_DESC(bcm4360_test242_writeverify_postactive, "BCM4360 test.242: MAILBOXMASK sentinel round-trip at t+100ms and t+2000ms dwells (post-set_active) to discriminate stage-gating from broken write path (1=verify, 0=off)");

/* BCM4360 test.243: re-run the MBM round-trip at t+100ms and t+2000ms
 * with an EXPLICIT brcmf_pcie_select_core(PCIE2) before the write, to
 * fix the silent BAR0_WINDOW defect in tests 240/241/242 (probes wrote
 * to CR4_wrap or CC instead of PCIE2 because no core was selected).
 * Also:
 *   - log BRCMF_PCIE_BAR0_WINDOW config-space value before AND after
 *     the select, to make window state evidence not assumption;
 *   - use invert-and-restore (~baseline) sentinel so the result is
 *     informative regardless of baseline value and robust to
 *     reserved-bit clipping;
 *   - restore the prior BAR0_WINDOW after the round-trip so
 *     downstream ladder state is unperturbed;
 *   - add a BAR2 TCM[0x90000] round-trip at the same dwell points
 *     as an independent "is MMIO write landing post-set_active"
 *     axis (BAR2 does not use BAR0_WINDOW, so it's decoupled).
 * Default 0. */
static int bcm4360_test243_writeverify_v2;
module_param(bcm4360_test243_writeverify_v2, int, 0644);
MODULE_PARM_DESC(bcm4360_test243_writeverify_v2, "BCM4360 test.243: MBM round-trip under explicit select_core(PCIE2) + BAR2 TCM[0x90000] round-trip at t+100ms and t+2000ms dwells (1=verify, 0=off)");

/* BCM4360 test.245: move T243's MBM + BAR2 round-trip probe from the
 * dwell ladder (post-set_active) to the PRE-FORCEHT stage (after
 * pci_set_master, before the FORCEHT write, before brcmf_chip_set_active).
 * Test.244 proved the post-set_active T243 probe wedges the host before
 * any pr_emerg line flushes. At pre-FORCEHT ARM is not running and
 * upstream brcmfmac itself does select_core(PCIE2) at this stage
 * (pcie.c:3580 in upstream). Same invert-and-restore sentinel and BAR2
 * TCM[0x90000] independent axis. Default 0. */
static int bcm4360_test245_writeverify_preforcehttp;
module_param(bcm4360_test245_writeverify_preforcehttp, int, 0644);
MODULE_PARM_DESC(bcm4360_test245_writeverify_preforcehttp, "BCM4360 test.245: MBM + BAR2 TCM[0x90000] round-trip under explicit select_core(PCIE2) at pre-FORCEHT stage (after pci_set_master, before FORCEHT+set_active) (1=verify, 0=off)");

/* BCM4360 test.246: disambiguate test.245's MBM partial-latch. Test.245
 * wrote 0xFFFFFFFF and got readback 0x00000300 — bits 8,9 latched (FN0_0,
 * FN0_1) but documented-legal D2H_DB bits (16..23, 0x00FF0000) did not.
 * Write upstream's exact production MBM value
 *     int_d2h_db | int_fn0 = 0x00FF0000 | 0x00000300 = 0x00FF0300
 * at the same pre-FORCEHT stage. Possible outcomes:
 *   - readback = 0x00FF0300 → all documented legal bits writable at
 *     pre-FORCEHT; test.245's 0x300 was simply reserved-bits clipping.
 *   - readback = 0x00000300 → D2H_DB bits (16..23) are pre-FORCEHT-gated
 *     (clock/reset domain, or write-gated until post-shared-init). FN0
 *     bits writable but D2H_DB not.
 *   - readback = 0 → our write didn't reach the chip at all, contradicting
 *     test.245; would indicate probe-order-sensitive behavior we need
 *     to investigate.
 * Default 0. */
static int bcm4360_test246_writeverify_legal;
module_param(bcm4360_test246_writeverify_legal, int, 0644);
MODULE_PARM_DESC(bcm4360_test246_writeverify_legal, "BCM4360 test.246: write upstream's production MBM value (int_d2h_db|int_fn0=0x00FF0300) at pre-FORCEHT to disambiguate test.245's partial-latch (1=verify, 0=off)");

/* BCM4360 test.247: first shared-struct probe. Pre-place a 72-byte
 * brcmf_pcie_shared_info-shaped struct at TCM[0x80000] via BAR2 at the
 * pre-FORCEHT stage. Struct contents: version byte (=5,
 * BRCMF_PCIE_MIN_SHARED_VERSION) at offset 0; all other 17 u32s zero.
 * ramsize-4 (NVRAM trailer 0xffc70038) is NOT overwritten. Per-dwell
 * poll of the same 18 u32s observes whether fw reads/writes any struct
 * field across ≥90s. Discriminator between (S1) BCM4360 fw reads host-
 * pre-placed struct and (S2) fw follows upstream protocol and is stalled
 * upstream of allocate-and-publish step. See PRE-TEST.247 in
 * RESUME_NOTES.md for full rationale. Default 0. */
static int bcm4360_test247_preplace_shared;
module_param(bcm4360_test247_preplace_shared, int, 0644);
MODULE_PARM_DESC(bcm4360_test247_preplace_shared, "BCM4360 test.247: pre-place a 72-byte pcie_shared-shaped struct at TCM[0x80000] at pre-FORCEHT and poll it at every dwell (1=enable, 0=off)");

/* BCM4360 test.248: wide-TCM scan across 16 u32 offsets, split 8
 * known-hot (prior tests 66/81/89/94/96/213/216/217 saw fw write
 * here) + 8 upper-TCM gap points. Two snapshots: at pre-FORCEHT
 * (baseline) and at the t+90000ms dwell (pre-wedge). Diff per
 * offset between snapshots = fw touched that region during the
 * ≥90s post-set_active window. Default 0. See PRE-TEST.248 in
 * RESUME_NOTES.md and phase6/test248_bcm_work.md. */
static int bcm4360_test248_wide_tcm_scan;
module_param(bcm4360_test248_wide_tcm_scan, int, 0644);
MODULE_PARM_DESC(bcm4360_test248_wide_tcm_scan, "BCM4360 test.248: wide-TCM 16-offset scan at pre-FORCEHT and t+90000ms dwell (upper-TCM priority, known-hot addresses) (1=enable, 0=off)");

/* Fixed offset list for T248 wide-TCM scan. Order preserved in the
 * logged line so snapshots are column-aligned for diff. */
static const u32 bcm4360_t248_offsets[16] = {
	/* Known-hot (previously observed fw writes) */
	0x9c000,  /* "STAK" marker (pcie.c:2292 comment) */
	0x9cc5c,  /* console ring write pointer (virtual addr field) */
	0x9cdb0,  /* prior trap ASCII address (test.213/216/217) */
	0x9cfe0,  /* prior trap struct address */
	0x9d000,  /* evolving counter pre-T230 (0→0x58c8c→0x43b1→frozen) */
	0x9d0a4,  /* olmsg shared_info magic_start */
	0x9f0cc,  /* olmsg fw_init_done */
	0x9fffc,  /* ramsize-4 — redundant with T239 but unifies record */
	/* Upper-TCM gap coverage */
	0x90000,  /* BAR2 round-trip anchor (T245/T246) */
	0x94000,
	0x98000,  /* user-specified upper-TCM priority */
	0x9a000,
	0x9b000,
	0x9e000,  /* between olmsg magic and fw_init_done */
	0x9f000,
	0x9fe00,  /* just below random_seed region start 0x9fe14 */
};

/* BCM4360 test.248: wide-TCM scan helper. Reads 16 u32s from
 * bcm4360_t248_offsets[] and emits one machine-diffable pr_emerg
 * line. stage_tag should be a compile-time string literal. Zero
 * cost when param off. Defined at file scope so both the pre-
 * FORCEHT and t+90000ms invocations (in brcmf_pcie_download_fw_nvram)
 * see the same macro. */
#define BCM4360_T248_WIDESCAN(stage_tag) do { \
	if (bcm4360_test248_wide_tcm_scan) { \
		u32 _w248[16]; \
		int _k248; \
		for (_k248 = 0; _k248 < 16; _k248++) \
			_w248[_k248] = brcmf_pcie_read_ram32(devinfo, \
				bcm4360_t248_offsets[_k248]); \
		pr_emerg("BCM4360 test.248: " stage_tag " TCM[16 off] = " \
			 "0x9c000=%08x 0x9cc5c=%08x 0x9cdb0=%08x 0x9cfe0=%08x " \
			 "0x9d000=%08x 0x9d0a4=%08x 0x9f0cc=%08x 0x9fffc=%08x " \
			 "0x90000=%08x 0x94000=%08x 0x98000=%08x 0x9a000=%08x " \
			 "0x9b000=%08x 0x9e000=%08x 0x9f000=%08x 0x9fe00=%08x\n", \
			 _w248[0], _w248[1], _w248[2], _w248[3], \
			 _w248[4], _w248[5], _w248[6], _w248[7], \
			 _w248[8], _w248[9], _w248[10], _w248[11], \
			 _w248[12], _w248[13], _w248[14], _w248[15]); \
	} \
} while (0)

/* BCM4360 test.249: console-buffer + assert-text window dump.
 * Fw freezes at T+12ms (per test.89) with counter 0x9d000=0x43b1;
 * console write-idx at 0x9cc5c evolved in T248 (→0x8009ccbe), so
 * any fw log output from the 0-12ms pre-freeze window is frozen
 * in place. This probe dumps:
 *  - A 640B window TCM[0x9CA00..0x9CCA0] (160 u32s) covering the
 *    console_info struct at 0x9cc5c and the preceding buffer area,
 *    fired at t+60000ms to keep ~30s headroom before the wedge
 *    (T248 landed its snapshot ≤1s before wedge at t+90000ms).
 *  - A 96B window TCM[0x9CDB0..0x9CE10] (24 u32s) covering the
 *    historic assert-text region (tests 213/216/217), fired at
 *    t+90000ms (low cost alongside T248's existing snapshot).
 *  - Per-dwell read of TCM[0x9d000] via the T239 poll extension,
 *    to directly reproduce test.89's "counter single-write at
 *    T+12ms, frozen thereafter" reading across all 23 dwells.
 * All BAR2 reads; no register side effects. Default 0. See
 * PRE-TEST.249 in RESUME_NOTES.md. */
static int bcm4360_test249_console_dump;
module_param(bcm4360_test249_console_dump, int, 0644);
MODULE_PARM_DESC(bcm4360_test249_console_dump, "BCM4360 test.249: console window 0x9CA00..0x9CCA0 at t+60s + assert window 0x9CDB0..0x9CE10 at t+90s + per-dwell 0x9d000 read (1=enable, 0=off)");

/* BCM4360 test.249: console-window dump helper. Reads 160 u32s
 * starting at 0x9CA00 and emits 5 pr_emerg lines of 32 u32s each
 * (288 chars + prefix < kernel LOG_LINE_MAX 1024). stage_tag is a
 * compile-time string literal. Zero cost when param off. */
#define BCM4360_T249_CONSOLE_WINDOW(stage_tag) do { \
	if (bcm4360_test249_console_dump) { \
		u32 _c249[160]; \
		int _k249; \
		for (_k249 = 0; _k249 < 160; _k249++) \
			_c249[_k249] = brcmf_pcie_read_ram32(devinfo, \
				0x9CA00 + _k249 * 4); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9ca00..0x9ca7c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _c249[0], _c249[1], _c249[2], _c249[3], _c249[4], _c249[5], _c249[6], _c249[7], \
			 _c249[8], _c249[9], _c249[10], _c249[11], _c249[12], _c249[13], _c249[14], _c249[15], \
			 _c249[16], _c249[17], _c249[18], _c249[19], _c249[20], _c249[21], _c249[22], _c249[23], \
			 _c249[24], _c249[25], _c249[26], _c249[27], _c249[28], _c249[29], _c249[30], _c249[31]); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9ca80..0x9cafc] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _c249[32], _c249[33], _c249[34], _c249[35], _c249[36], _c249[37], _c249[38], _c249[39], \
			 _c249[40], _c249[41], _c249[42], _c249[43], _c249[44], _c249[45], _c249[46], _c249[47], \
			 _c249[48], _c249[49], _c249[50], _c249[51], _c249[52], _c249[53], _c249[54], _c249[55], \
			 _c249[56], _c249[57], _c249[58], _c249[59], _c249[60], _c249[61], _c249[62], _c249[63]); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9cb00..0x9cb7c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _c249[64], _c249[65], _c249[66], _c249[67], _c249[68], _c249[69], _c249[70], _c249[71], \
			 _c249[72], _c249[73], _c249[74], _c249[75], _c249[76], _c249[77], _c249[78], _c249[79], \
			 _c249[80], _c249[81], _c249[82], _c249[83], _c249[84], _c249[85], _c249[86], _c249[87], \
			 _c249[88], _c249[89], _c249[90], _c249[91], _c249[92], _c249[93], _c249[94], _c249[95]); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9cb80..0x9cbfc] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _c249[96], _c249[97], _c249[98], _c249[99], _c249[100], _c249[101], _c249[102], _c249[103], \
			 _c249[104], _c249[105], _c249[106], _c249[107], _c249[108], _c249[109], _c249[110], _c249[111], \
			 _c249[112], _c249[113], _c249[114], _c249[115], _c249[116], _c249[117], _c249[118], _c249[119], \
			 _c249[120], _c249[121], _c249[122], _c249[123], _c249[124], _c249[125], _c249[126], _c249[127]); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9cc00..0x9cc7c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _c249[128], _c249[129], _c249[130], _c249[131], _c249[132], _c249[133], _c249[134], _c249[135], \
			 _c249[136], _c249[137], _c249[138], _c249[139], _c249[140], _c249[141], _c249[142], _c249[143], \
			 _c249[144], _c249[145], _c249[146], _c249[147], _c249[148], _c249[149], _c249[150], _c249[151], \
			 _c249[152], _c249[153], _c249[154], _c249[155], _c249[156], _c249[157], _c249[158], _c249[159]); \
	} \
} while (0)

/* BCM4360 test.249: assert-text window helper. Reads 24 u32s from
 * 0x9CDB0 and emits one line. Historic assert-text region per
 * tests 213/216/217; T248 saw 0x9CDB0=0x77203030 hinting ASCII
 * content. Zero cost when param off. */
#define BCM4360_T249_ASSERT_WINDOW(stage_tag) do { \
	if (bcm4360_test249_console_dump) { \
		u32 _a249[24]; \
		int _m249; \
		for (_m249 = 0; _m249 < 24; _m249++) \
			_a249[_m249] = brcmf_pcie_read_ram32(devinfo, \
				0x9CDB0 + _m249 * 4); \
		pr_emerg("BCM4360 test.249: " stage_tag " TCM[0x9cdb0..0x9ce0c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _a249[0], _a249[1], _a249[2], _a249[3], _a249[4], _a249[5], _a249[6], _a249[7], \
			 _a249[8], _a249[9], _a249[10], _a249[11], _a249[12], _a249[13], _a249[14], _a249[15], \
			 _a249[16], _a249[17], _a249[18], _a249[19], _a249[20], _a249[21], _a249[22], _a249[23]); \
	} \
} while (0)

/* BCM4360 test.250: console buffer-gap dump.
 * T249 dumped 0x9CA00..0x9CCA0 (found all STAK canary) and
 * 0x9CDB0..0x9CE10 (found ASCII log text starting mid-phrase).
 * The 240-byte gap at 0x9CCB0..0x9CDB0 was never dumped — buf_ptr
 * VA 0x8009ccbe (seen at 0x9CC5C) → TCM offset 0x9CCBE, i.e. the
 * unread end-of-log sits exactly in that gap. T250 dumps 96 u32s
 * (384 B) at 0x9CCB0..0x9CE30 in 3 pr_emerg lines of 32 u32s each,
 * fired at t+60000ms (same envelope as T249's console window, with
 * ~30s headroom before the wedge). Also extends the T249 per-dwell
 * 0x9d000 counter poll so the frozen-counter streak evidence is
 * retained when T249's STAK window is disabled. All BAR2 reads. */
static int bcm4360_test250_console_gap;
module_param(bcm4360_test250_console_gap, int, 0644);
MODULE_PARM_DESC(bcm4360_test250_console_gap, "BCM4360 test.250: dump 96 u32s at 0x9CCB0..0x9CE30 at t+60s (buf_ptr gap; T249 found content mid-phrase at 0x9CDB0) + per-dwell 0x9d000 poll (1=enable, 0=off)");

/* BCM4360 test.250: gap-window helper. Reads 96 u32s starting at
 * 0x9CCB0 and emits 3 pr_emerg lines of 32 u32s each (line length
 * ~350 chars — within kernel LOG_LINE_MAX). Zero cost when off. */
#define BCM4360_T250_GAP_WINDOW(stage_tag) do { \
	if (bcm4360_test250_console_gap) { \
		u32 _g250[96]; \
		int _n250; \
		for (_n250 = 0; _n250 < 96; _n250++) \
			_g250[_n250] = brcmf_pcie_read_ram32(devinfo, \
				0x9CCB0 + _n250 * 4); \
		pr_emerg("BCM4360 test.250: " stage_tag " TCM[0x9ccb0..0x9cd2c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _g250[0], _g250[1], _g250[2], _g250[3], _g250[4], _g250[5], _g250[6], _g250[7], \
			 _g250[8], _g250[9], _g250[10], _g250[11], _g250[12], _g250[13], _g250[14], _g250[15], \
			 _g250[16], _g250[17], _g250[18], _g250[19], _g250[20], _g250[21], _g250[22], _g250[23], \
			 _g250[24], _g250[25], _g250[26], _g250[27], _g250[28], _g250[29], _g250[30], _g250[31]); \
		pr_emerg("BCM4360 test.250: " stage_tag " TCM[0x9cd30..0x9cdac] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _g250[32], _g250[33], _g250[34], _g250[35], _g250[36], _g250[37], _g250[38], _g250[39], \
			 _g250[40], _g250[41], _g250[42], _g250[43], _g250[44], _g250[45], _g250[46], _g250[47], \
			 _g250[48], _g250[49], _g250[50], _g250[51], _g250[52], _g250[53], _g250[54], _g250[55], \
			 _g250[56], _g250[57], _g250[58], _g250[59], _g250[60], _g250[61], _g250[62], _g250[63]); \
		pr_emerg("BCM4360 test.250: " stage_tag " TCM[0x9cdb0..0x9ce2c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _g250[64], _g250[65], _g250[66], _g250[67], _g250[68], _g250[69], _g250[70], _g250[71], \
			 _g250[72], _g250[73], _g250[74], _g250[75], _g250[76], _g250[77], _g250[78], _g250[79], \
			 _g250[80], _g250[81], _g250[82], _g250[83], _g250[84], _g250[85], _g250[86], _g250[87], \
			 _g250[88], _g250[89], _g250[90], _g250[91], _g250[92], _g250[93], _g250[94], _g250[95]); \
	} \
} while (0)



/* BCM4360 test.251: console ring-end + backward-read from buf_ptr.
 * T250 captured log content 0x9CCB0..0x9CE30 (Chipc init, wl_probe,
 * dngl_probe, RTE banner). Open questions: (1) where does the ring
 * end past 0x9CE30? (2) is buf_ptr (0x9CCBE) a forward-write index
 * (if so, bytes before 0x9CCBE are the newest writes)?
 *
 * Probe: 12 u32s at 0x9CC80..0x9CCAC (backward from buf_ptr, fills
 * gap between T249 struct-area end at 0x9CC7C and T250 start at
 * 0x9CCB0) + 64 u32s at 0x9CE30..0x9CF30 (forward continuation, may
 * contain ring boundary or older content depending on direction).
 * All BAR2 reads. */
static int bcm4360_test251_console_ext;
module_param(bcm4360_test251_console_ext, int, 0644);
MODULE_PARM_DESC(bcm4360_test251_console_ext, "BCM4360 test.251: dump 12 u32 at 0x9CC80..0x9CCAC (backward from buf_ptr) + 64 u32 at 0x9CE30..0x9CF30 (forward past T250) at t+60s, closes ring-layout question; also per-dwell 0x9d000 poll (1=enable, 0=off)");

/* BCM4360 test.251: ring-extension helper. 3 pr_emerg lines total.
 * Line 1: 12 u32 at 0x9CC80..0x9CCAC (~180 char).
 * Line 2: 32 u32 at 0x9CE30..0x9CEAC (~350 char).
 * Line 3: 32 u32 at 0x9CEB0..0x9CF2C (~350 char).
 * Zero cost when off. */
#define BCM4360_T251_RING_EXT(stage_tag) do { \
	if (bcm4360_test251_console_ext) { \
		u32 _b251[12]; \
		u32 _f251[64]; \
		int _n251; \
		for (_n251 = 0; _n251 < 12; _n251++) \
			_b251[_n251] = brcmf_pcie_read_ram32(devinfo, \
				0x9CC80 + _n251 * 4); \
		for (_n251 = 0; _n251 < 64; _n251++) \
			_f251[_n251] = brcmf_pcie_read_ram32(devinfo, \
				0x9CE30 + _n251 * 4); \
		pr_emerg("BCM4360 test.251: " stage_tag " TCM[0x9cc80..0x9ccac] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x\n", \
			 _b251[0], _b251[1], _b251[2], _b251[3], _b251[4], _b251[5], _b251[6], _b251[7], \
			 _b251[8], _b251[9], _b251[10], _b251[11]); \
		pr_emerg("BCM4360 test.251: " stage_tag " TCM[0x9ce30..0x9ceac] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _f251[0], _f251[1], _f251[2], _f251[3], _f251[4], _f251[5], _f251[6], _f251[7], \
			 _f251[8], _f251[9], _f251[10], _f251[11], _f251[12], _f251[13], _f251[14], _f251[15], \
			 _f251[16], _f251[17], _f251[18], _f251[19], _f251[20], _f251[21], _f251[22], _f251[23], \
			 _f251[24], _f251[25], _f251[26], _f251[27], _f251[28], _f251[29], _f251[30], _f251[31]); \
		pr_emerg("BCM4360 test.251: " stage_tag " TCM[0x9ceb0..0x9cf2c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _f251[32], _f251[33], _f251[34], _f251[35], _f251[36], _f251[37], _f251[38], _f251[39], \
			 _f251[40], _f251[41], _f251[42], _f251[43], _f251[44], _f251[45], _f251[46], _f251[47], \
			 _f251[48], _f251[49], _f251[50], _f251[51], _f251[52], _f251[53], _f251[54], _f251[55], \
			 _f251[56], _f251[57], _f251[58], _f251[59], _f251[60], _f251[61], _f251[62], _f251[63]); \
	} \
} while (0)


/* BCM4360 debug: test.252 — BSS-data probe at saved-state region's repeated
 * TCM offsets. T251 saved-state region (0x9CE98..0x9CF34) referenced three
 * data addresses repeatedly: 0x93610 (5x), 0x92440 (3x), 0x91CC4 (3x). All
 * lie above code segment (0x6BF78), so BSS/heap; not in fw blob. T252 reads
 * 16 u32s at each of three windows centered on those addresses to identify
 * what fw is tracking at hang time (task descriptor / PHY shadow / mutex).
 * All BAR2 reads. */
static int bcm4360_test252_phy_data;
module_param(bcm4360_test252_phy_data, int, 0644);
MODULE_PARM_DESC(bcm4360_test252_phy_data, "BCM4360 test.252: read 16 u32 each at TCM[0x93600..0x9363c], TCM[0x92430..0x9246c], TCM[0x91cb0..0x91cec] at t+60s; identifies the BSS data fw is tracking at hang time (1=enable, 0=off)");

/* BCM4360 test.252: BSS-data probe helper. 3 pr_emerg lines, 16 u32 each.
 * Each line ~190 char. Zero cost when off. */
#define BCM4360_T252_DATA_PROBE(stage_tag) do { \
	if (bcm4360_test252_phy_data) { \
		u32 _d252_a[16], _d252_b[16], _d252_c[16]; \
		int _n252; \
		for (_n252 = 0; _n252 < 16; _n252++) { \
			_d252_a[_n252] = brcmf_pcie_read_ram32(devinfo, 0x93600 + _n252 * 4); \
			_d252_b[_n252] = brcmf_pcie_read_ram32(devinfo, 0x92430 + _n252 * 4); \
			_d252_c[_n252] = brcmf_pcie_read_ram32(devinfo, 0x91cb0 + _n252 * 4); \
		} \
		pr_emerg("BCM4360 test.252: " stage_tag " TCM[0x93600..0x9363c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d252_a[0], _d252_a[1], _d252_a[2], _d252_a[3], _d252_a[4], _d252_a[5], _d252_a[6], _d252_a[7], \
			 _d252_a[8], _d252_a[9], _d252_a[10], _d252_a[11], _d252_a[12], _d252_a[13], _d252_a[14], _d252_a[15]); \
		pr_emerg("BCM4360 test.252: " stage_tag " TCM[0x92430..0x9246c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d252_b[0], _d252_b[1], _d252_b[2], _d252_b[3], _d252_b[4], _d252_b[5], _d252_b[6], _d252_b[7], \
			 _d252_b[8], _d252_b[9], _d252_b[10], _d252_b[11], _d252_b[12], _d252_b[13], _d252_b[14], _d252_b[15]); \
		pr_emerg("BCM4360 test.252: " stage_tag " TCM[0x91cb0..0x91cec] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d252_c[0], _d252_c[1], _d252_c[2], _d252_c[3], _d252_c[4], _d252_c[5], _d252_c[6], _d252_c[7], \
			 _d252_c[8], _d252_c[9], _d252_c[10], _d252_c[11], _d252_c[12], _d252_c[13], _d252_c[14], _d252_c[15]); \
	} \
} while (0)


/* BCM4360 debug: test.253 — central-shared-object + list_head peer probe.
 * T251/T252 found 0x934C0 referenced across three T252 structs AND in T248's
 * 0x9CFE0 AND in T251's saved-state 0x9CEA0. T252 decoded 0x92460..0x9246F as
 * two adjacent list_head pairs with peers at 0x91E54 and 0x91E84. T253
 * probes:
 *   (a) TCM[0x934B8..0x934F4] = 16 u32 (8 pre-bytes + central object) —
 *       catches allocator header if present, identifies object class
 *       (TCB/wl/si/etc).
 *   (b) TCM[0x91E50..0x91E8C] = 16 u32 — validates list_head pair (should
 *       self-ref or point back to 0x92460/0x92468 if empty; to other peers
 *       if list has members).
 * All BAR2 reads. */
static int bcm4360_test253_shared_obj;
module_param(bcm4360_test253_shared_obj, int, 0644);
MODULE_PARM_DESC(bcm4360_test253_shared_obj, "BCM4360 test.253: read TCM[0x934b8..0x934f4] + TCM[0x91e50..0x91e8c] at t+60s; decodes central shared object referenced across T251/T252 structs + validates list_head peer inference (1=enable, 0=off)");

/* BCM4360 test.253: central-shared-object probe helper. 2 pr_emerg lines,
 * 16 u32 each. Each line ~190 char. Zero cost when off. */
#define BCM4360_T253_SHARED_PROBE(stage_tag) do { \
	if (bcm4360_test253_shared_obj) { \
		u32 _d253_a[16], _d253_b[16]; \
		int _n253; \
		for (_n253 = 0; _n253 < 16; _n253++) { \
			_d253_a[_n253] = brcmf_pcie_read_ram32(devinfo, 0x934b8 + _n253 * 4); \
			_d253_b[_n253] = brcmf_pcie_read_ram32(devinfo, 0x91e50 + _n253 * 4); \
		} \
		pr_emerg("BCM4360 test.253: " stage_tag " TCM[0x934b8..0x934f4] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d253_a[0], _d253_a[1], _d253_a[2], _d253_a[3], _d253_a[4], _d253_a[5], _d253_a[6], _d253_a[7], \
			 _d253_a[8], _d253_a[9], _d253_a[10], _d253_a[11], _d253_a[12], _d253_a[13], _d253_a[14], _d253_a[15]); \
		pr_emerg("BCM4360 test.253: " stage_tag " TCM[0x91e50..0x91e8c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d253_b[0], _d253_b[1], _d253_b[2], _d253_b[3], _d253_b[4], _d253_b[5], _d253_b[6], _d253_b[7], \
			 _d253_b[8], _d253_b[9], _d253_b[10], _d253_b[11], _d253_b[12], _d253_b[13], _d253_b[14], _d253_b[15]); \
	} \
} while (0)

/* BCM4360 test.255: RTE scheduler state probe + tick-scale check.
 * Discriminates (A) backplane bus-stall vs (A') CPU-in-WFI vs
 * (C) tick-scale corruption. All 4 BSS addresses are blob-zero; any
 * non-zero value at probe time proves fw's scheduler reached that code
 * path. Tick-scale blob-default is 0x50; corrupted value would break
 * all PMCCNTR-backed delay loops. Run at BOTH t+100ms and t+90s for
 * drift test on scheduler's own state. */
static int bcm4360_test255_sched_probe;
module_param(bcm4360_test255_sched_probe, int, 0644);
MODULE_PARM_DESC(bcm4360_test255_sched_probe, "BCM4360 test.255: read TCM[0x6296C, 0x629A4, 0x6299C, 0x629B4, 0x58C98] at t+100ms; decodes RTE scheduler state + tick-scale (1=enable, 0=off)");

static int bcm4360_test255_sched_late;
module_param(bcm4360_test255_sched_late, int, 0644);
MODULE_PARM_DESC(bcm4360_test255_sched_late, "BCM4360 test.255: late RTE scheduler state probe at t+90000ms; drift-test partner to test255_sched_probe (1=enable, 0=off)");

static int bcm4360_test255_struct_decode;
module_param(bcm4360_test255_struct_decode, int, 0644);
MODULE_PARM_DESC(bcm4360_test255_struct_decode, "BCM4360 test.255: read TCM[0x93550..0x9358C] at t+60s; decodes 0x9355C struct family (T253 follow-up) (1=enable, 0=off)");

/* BCM4360 test.255 scheduler probe helper. 1 pr_emerg line, 5 u32 total.
 * Gate flag is macro argument so one body serves early and late probes. */
#define BCM4360_T255_SCHED_PROBE_COND(gate_flag, stage_tag) do { \
	if (gate_flag) { \
		u32 _d255s[5]; \
		_d255s[0] = brcmf_pcie_read_ram32(devinfo, 0x6296C); \
		_d255s[1] = brcmf_pcie_read_ram32(devinfo, 0x629A4); \
		_d255s[2] = brcmf_pcie_read_ram32(devinfo, 0x6299C); \
		_d255s[3] = brcmf_pcie_read_ram32(devinfo, 0x629B4); \
		_d255s[4] = brcmf_pcie_read_ram32(devinfo, 0x58C98); \
		pr_emerg("BCM4360 test.255: " stage_tag \
			 " sched[0x6296C,0x629A4,0x6299C,0x629B4]=%08x %08x %08x %08x tick[0x58C98]=%08x\n", \
			 _d255s[0], _d255s[1], _d255s[2], _d255s[3], _d255s[4]); \
	} \
} while (0)

/* BCM4360 test.255 struct-decode helper. 1 pr_emerg line, 16 u32. */
#define BCM4360_T255_STRUCT_DECODE(stage_tag) do { \
	if (bcm4360_test255_struct_decode) { \
		u32 _d255f[16]; \
		int _n255; \
		for (_n255 = 0; _n255 < 16; _n255++) \
			_d255f[_n255] = brcmf_pcie_read_ram32(devinfo, 0x93550 + _n255 * 4); \
		pr_emerg("BCM4360 test.255: " stage_tag " TCM[0x93550..0x9358c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d255f[0], _d255f[1], _d255f[2], _d255f[3], _d255f[4], _d255f[5], _d255f[6], _d255f[7], \
			 _d255f[8], _d255f[9], _d255f[10], _d255f[11], _d255f[12], _d255f[13], _d255f[14], _d255f[15]); \
	} \
} while (0)

/* BCM4360 test.256: scheduler callback-list walk + current-task struct deref.
 * Walks first 4 nodes at BSS[0x9627C] (T255-observed list head). Each node is
 * 16 bytes: {next=+0, fn-ptr=+4, arg=+8, flag=+0xC} per pcie fn 0x115C disasm.
 * If any fn-ptr falls in wlc_attach family (blob 0x68xxx-0x6Axxx), we have
 * hard evidence those are registered as scheduler callbacks -> reinforces (A)
 * bus-stall inside callback hypothesis. Also dereferences current-task ptr at
 * BSS[0x96F2C] to decode task struct. */
static int bcm4360_test256_sched_walk;
module_param(bcm4360_test256_sched_walk, int, 0644);
MODULE_PARM_DESC(bcm4360_test256_sched_walk, "BCM4360 test.256: walk scheduler callback list at TCM[0x9627C..0x962BC] + current-task struct at TCM[0x96F2C..0x96F6C] at t+60s (1=enable, 0=off)");

static int bcm4360_test256_sched_walk_early;
module_param(bcm4360_test256_sched_walk_early, int, 0644);
MODULE_PARM_DESC(bcm4360_test256_sched_walk_early, "BCM4360 test.256: also run sched_walk at t+100ms (redundancy if fw wedges before t+60s) (1=enable, 0=off)");

/* BCM4360 test.258: IRQ-enable drift test. After t+120s dwell, writes
 * MAILBOXMASK + H2D_MAILBOX_1 (via existing brcmf_pcie_intr_enable +
 * brcmf_pcie_hostready helpers), waits 5s, re-reads console buf_ptr
 * at TCM[0x9CC5C]. If buf_ptr advanced, fw woke from WFI and ran code
 * — (A') causation confirmed. Variant B (safe): does NOT call
 * request_irq to avoid handle_mb_data corrupting TCM[0]. */
static int bcm4360_test258_enable_irq;
module_param(bcm4360_test258_enable_irq, int, 0644);
MODULE_PARM_DESC(bcm4360_test258_enable_irq, "BCM4360 test.258: after t+120s dwell, write MAILBOXMASK + H2D_MAILBOX_1 and sample console buf_ptr before+after 5s wait; detects fw wake-from-WFI (1=enable, 0=off)");

/* BCM4360 test.259: like test.258 but registers a minimal safe IRQ handler
 * BEFORE enabling MAILBOXMASK so any fw-raised IRQ is consumed cleanly
 * (no kernel-level unhandled-IRQ storm). Handler reads MAILBOXINT, ACKs
 * by write-back, then masks further IRQs to prevent storm. Counter +
 * last-seen value are atomic so probe can read them. Does NOT touch
 * devinfo->shared.* — only reginfo registers + atomic counters. */
static int bcm4360_test259_safe_enable_irq;
module_param(bcm4360_test259_safe_enable_irq, int, 0644);
MODULE_PARM_DESC(bcm4360_test259_safe_enable_irq, "BCM4360 test.259: safe variant of test.258 — registers a minimal no-op IRQ handler BEFORE enabling MAILBOXMASK so fw-raised IRQs don't wedge the host. Logs IRQ-count + last MAILBOXINT value (1=enable, 0=off)");

static atomic_t bcm4360_t259_irq_count = ATOMIC_INIT(0);
static atomic_t bcm4360_t259_last_mailboxint = ATOMIC_INIT(0);

/* bcm4360_t259_safe_handler is defined later (needs struct brcmf_pciedev_info
 * + brcmf_pcie_read_reg32/write_reg32 to be forward-declared first). */

/* BCM4360 test.260: split-enable variants. mask_only writes MAILBOXMASK
 * but NOT the doorbell; doorbell_only does the inverse. Both use the
 * same safe IRQ handler + MSI setup as T259. Replaces T259's single
 * msleep(5000) with 50×{msleep(100); read MAILBOXINT + buf_ptr} timeline
 * so partial data is recovered even if the host wedges mid-loop. */
static int bcm4360_test260_mask_only;
module_param(bcm4360_test260_mask_only, int, 0644);
MODULE_PARM_DESC(bcm4360_test260_mask_only, "BCM4360 test.260: mask-only variant — write MAILBOXMASK=0xFF0300 but SKIP H2D_MAILBOX_1 doorbell, then 50×{msleep(100); log MAILBOXINT + buf_ptr} timeline. Isolates whether mask write alone wedges host. (1=enable, 0=off)");

static int bcm4360_test260_doorbell_only;
module_param(bcm4360_test260_doorbell_only, int, 0644);
MODULE_PARM_DESC(bcm4360_test260_doorbell_only, "BCM4360 test.260: doorbell-only variant — write H2D_MAILBOX_1=1 but SKIP MAILBOXMASK, then 50×{msleep(100); log MAILBOXINT + buf_ptr} timeline. Isolates whether doorbell alone wedges host. (1=enable, 0=off)");

static int bcm4360_test262_msi_poll_only;
module_param(bcm4360_test262_msi_poll_only, int, 0644);
MODULE_PARM_DESC(bcm4360_test262_msi_poll_only, "BCM4360 test.262: control variant — enable MSI + request_irq + run the same 50×{msleep(100); log MAILBOXINT + buf_ptr} timeline, but SKIP both MAILBOXMASK and H2D_MAILBOX_1 writes. Isolates whether the shared instrumentation scaffold alone wedges host. (1=enable, 0=off)");

/* BCM4360 test.263: short-scaffold variant. Same as T262 (MSI +
 * request_irq + poll loop, no register writes) but 10 iterations instead
 * of 50. Cleanup path (timeline-done print + free_irq + pci_disable_msi)
 * will execute under t+125s for the first time — lets us see whether
 * cleanup itself is the crasher, or whether crash is time-anchored
 * (fires at t+125s regardless of scaffold duration). */
static int bcm4360_test263_short;
module_param(bcm4360_test263_short, int, 0644);
MODULE_PARM_DESC(bcm4360_test263_short, "BCM4360 test.263: short-scaffold variant — same as T262 but only 10 iterations (1s loop instead of 5s). Discriminates absolute-time crash (t+125s) vs scaffold-duration crash vs cleanup-path crash. (1=enable, 0=off)");

/* BCM4360 test.264: loop-less scaffold. MSI + request_irq + single
 * msleep(2000) + cleanup, with pr_emerg markers bracketing each step.
 * No MMIO reads inside the sleep. No loop structure. Discriminates
 * duration-anchor (crash ~2s into msleep) vs cleanup-path-is-crasher
 * (crash between msleep-done and pci_disable_msi-returned) vs
 * loop-content-necessary (clean completion — loop MMIO reads mattered). */
static int bcm4360_test264_noloop;
module_param(bcm4360_test264_noloop, int, 0644);
MODULE_PARM_DESC(bcm4360_test264_noloop, "BCM4360 test.264: loop-less scaffold — MSI + request_irq + single msleep(2000) + cleanup with markers. No MMIO reads inside the sleep. Isolates whether the trigger is duration-of-MSI-bound, cleanup-path, or loop-content. (1=enable, 0=off)");

/* BCM4360 test.265: shorter-sleep variant of T264. Identical in every
 * way EXCEPT msleep(500) instead of msleep(2000). Single-variable change
 * to decouple duration-proportional (crash <500ms) vs fixed-timer post-
 * scaffold-entry (crash ~2s, well after msleep exits — FIRST EXECUTION
 * of the cleanup path) vs msleep-exit-transition (crash at 500ms exactly). */
static int bcm4360_test265_short_noloop;
module_param(bcm4360_test265_short_noloop, int, 0644);
MODULE_PARM_DESC(bcm4360_test265_short_noloop, "BCM4360 test.265: short-sleep variant of T264 — same scaffold but msleep(500) instead of msleep(2000). Decouples duration-proportional vs fixed-timer. (1=enable, 0=off)");

/* BCM4360 test.266: ultra-short-sleep variant. msleep(50) instead of 500.
 * Shrinks the upper bound on trigger-fire time 10× from T265. Crash
 * within 50ms = trigger very fast; crash at ~500ms (cleanup phase) =
 * fixed timer ∈ [50, 500ms] AND cleanup becomes visible first time. */
static int bcm4360_test266_ultra_short_noloop;
module_param(bcm4360_test266_ultra_short_noloop, int, 0644);
MODULE_PARM_DESC(bcm4360_test266_ultra_short_noloop, "BCM4360 test.266: ultra-short-sleep variant — T264/T265 scaffold but msleep(50) instead of 500. Shrinks trigger upper bound 10×. (1=enable, 0=off)");

/* BCM4360 test.267: no-msleep variant. Scaffold = pci_enable_msi +
 * request_irq + IMMEDIATE free_irq + pci_disable_msi. No sleep between
 * request_irq and free_irq. Existing cleanup markers (calling free_irq,
 * free_irq returned, calling pci_disable_msi, pci_disable_msi returned)
 * give 5-position discrimination of crash location. Clean completion
 * would mean msleep duration is necessary — headline finding. */
static int bcm4360_test267_no_msleep;
module_param(bcm4360_test267_no_msleep, int, 0644);
MODULE_PARM_DESC(bcm4360_test267_no_msleep, "BCM4360 test.267: no-msleep scaffold — MSI + request_irq + IMMEDIATE cleanup. No sleep between request_irq and free_irq. Tests whether msleep duration is necessary for the crash trigger. (1=enable, 0=off)");

/* BCM4360 test.268: early-scaffold pivot. Runs the T267 scaffold RIGHT
 * AFTER brcmf_chip_set_active() returns, skipping the entire 120s dwell
 * ladder. Moves the scaffold out of the marginal t+120000ms probe-burst
 * region that caused two consecutive T267 null-test fires. Same
 * discrimination as T267; ~10× less exposure to the flaky region. */
static int bcm4360_test268_early_scaffold;
module_param(bcm4360_test268_early_scaffold, int, 0644);
MODULE_PARM_DESC(bcm4360_test268_early_scaffold, "BCM4360 test.268: run T267 scaffold right after brcmf_chip_set_active returns; skip the 120s dwell ladder entirely. Same T267 discrimination with 10× less exposure to the marginal probe region. (1=enable, 0=off)");

/* BCM4360 test.269: early-exit at t+60000ms. Skip all ladder steps past
 * t+60000ms (no t+90/t+120 dwells, no scaffolds). Goal: does the probe
 * + ultra-dwells path return cleanly if we stop before the late-window
 * crash region? Three outcomes discriminate cleanly:
 *   - clean rmmod           -> late-ladder/wall-clock crash avoidable by
 *                              exiting before it; stable reproducer.
 *   - crash at ~111-143s    -> wall-clock timer confirmed regardless of
 *                              ladder activity (high-value).
 *   - crash during rmmod    -> cleanup path is the real crasher. */
static int bcm4360_test269_early_exit;
module_param(bcm4360_test269_early_exit, int, 0644);
MODULE_PARM_DESC(bcm4360_test269_early_exit, "BCM4360 test.269: early-exit at t+60000ms — skip t+90s/t+120s dwells and all scaffolds; goto ultra_dwells_done for clean BM-clear + release. Tests wall-clock vs ladder-activity crash mechanism. (1=enable, 0=off)");

/* BCM4360 test.276: port Phase 4B test.28's shared_info pre-ARM-release
 * write into Phase 5. Writes magic + olmsg DMA buffer address to TCM
 * shared_info struct at ramsize-0x2F5C (0x9D0A4 for 640 KB TCM). After
 * set_active, polls shared_info[+0x010], fw_init_done, and MAILBOXINT
 * for 2 s, logging every change. Pure diagnostic — no MSI, no doorbell.
 * Design: phase6/t276_shared_info_design.md. Protocol evidence:
 * KEY_FINDINGS.md §Host-firmware protocol. */
static int bcm4360_test276_shared_info;
module_param(bcm4360_test276_shared_info, int, 0644);
MODULE_PARM_DESC(bcm4360_test276_shared_info, "BCM4360 test.276: write shared_info handshake at TCM[ramsize-0x2F5C] and allocate 64 KB olmsg DMA buffer before ARM release; poll response for 2 s post-release. Ports Phase 4B test.28. (1=enable, 0=off)");

/* BCM4360 test.276 constants — see phase4/notes/level4_shared_info_plan.md */
#define BCM4360_T276_SHARED_INFO_OFFSET	0x2F5C	/* subtracted from ramsize */
#define BCM4360_T276_SHARED_INFO_SIZE	0x2F3C	/* ramsize-0x2F5C..ramsize-0x20 */
#define BCM4360_T276_SI_MAGIC_START	0x000
#define BCM4360_T276_SI_DMA_LO		0x004
#define BCM4360_T276_SI_DMA_HI		0x008
#define BCM4360_T276_SI_BUF_SIZE	0x00C
#define BCM4360_T276_SI_FW_STATUS	0x010	/* fw-writable */
#define BCM4360_T276_SI_FW_INIT_DONE	0x2028
#define BCM4360_T276_SI_MAGIC_END	0x2F38
#define BCM4360_T276_MAGIC_START_VAL	0xA5A5A5A5
#define BCM4360_T276_MAGIC_END_VAL	0x5A5A5A5A
#define BCM4360_T276_OLMSG_BUF_SIZE	0x10000	/* 64 KB */
#define BCM4360_T276_OLMSG_RING_SIZE	0x7800	/* 30 KB per ring */
#define BCM4360_T276_OLMSG_HDR_SIZE	0x20	/* 2 rings * 16 B header */

/* BCM4360 test.277: follow the pointer fw writes to shared_info[+0x010]
 * (observed value 0x0009af88 — T276). Phase 4B interprets this as a
 * {buf_addr, buf_size, write_idx, read_addr} console struct. T277 dumps
 * the struct at two points (pre-shared_info-write + post-2s-poll) to
 * discriminate fw-boot-populated vs post-set_active-populated vs
 * actively-advancing. If buf_addr is a valid TCM address, dumps the
 * first 128 B of the buffer with ASCII escape so trap/log text is
 * readable. See phase6/t276_shared_info_design.md + advisor trace. */
static int bcm4360_test277_console_decode;
module_param(bcm4360_test277_console_decode, int, 0644);
MODULE_PARM_DESC(bcm4360_test277_console_decode, "BCM4360 test.277: dump console struct at fw-published pointer (T276 response 0x9af88) before and after the 2s poll, plus 128 B of the buffer it points to if buf_addr is a valid TCM address. Requires bcm4360_test276_shared_info=1. (1=enable, 0=off)");

/* T277 uses the pointer value fw wrote to shared_info[+0x010] as
 * the struct base. Phase 4B observed 0x0009af88 — we confirm at runtime
 * by reading si[+0x010] after ARM release rather than hardcoding. */
#define BCM4360_T277_STRUCT_DWORDS	4	/* buf_addr, size, wr_idx, rd_addr */
#define BCM4360_T277_BUFFER_DUMP_BYTES	128	/* 32 dwords */

/* BCM4360 test.278: periodic console dump across the dwell ladder.
 * Extends T277 (single-point dump) to: (a) dump the full write_idx
 * window at post-poll time (seeded prev=0), and (b) re-dump deltas at
 * t+500ms, t+5s, t+30s, t+90s stages of the ladder. Catches fw log
 * entries written after the initial chipc decode — potentially the
 * decisive signal for the late-ladder wedge. Requires test276+test277.
 * Design: advisor trace 2026-04-24 post-T277. */
static int bcm4360_test278_console_periodic;
module_param(bcm4360_test278_console_periodic, int, 0644);
MODULE_PARM_DESC(bcm4360_test278_console_periodic, "BCM4360 test.278: periodic console delta dump during T238 dwell ladder. Post-poll seeds with prev=0 (full dump); then delta dumps at t+500ms, t+5s, t+30s, t+90s. Requires bcm4360_test276_shared_info=1 and bcm4360_test277_console_decode=1. (1=enable, 0=off)");

#define BCM4360_T278_CHUNK_BYTES	128	/* per pr_emerg line */
#define BCM4360_T278_MAX_BYTES_PER_CALL	1024	/* printk safety cap */

/* BCM4360 test.279: directed mailbox-probe with console observation.
 * Writes H2D_MAILBOX_1 (hypothesis: fn@0x1146C's trigger) then
 * H2D_MAILBOX_0 (known-positive control for pciedngl_isr per T274).
 * Between each write: msleep(100) + T278 console delta dump.
 * Also reads MAILBOXMASK first as sanity check (0 = all masked,
 * writes would be futile). No MSI, no request_irq — orthogonal to
 * the T264-T266 MSI-subscription wedge. Requires T276+T277+T278.
 * Design: phase6/t281_fn1146c_trigger.md + advisor trace 2026-04-24. */
static int bcm4360_test279_mbx_probe;
module_param(bcm4360_test279_mbx_probe, int, 0644);
MODULE_PARM_DESC(bcm4360_test279_mbx_probe, "BCM4360 test.279: post-T278-poll, read MAILBOXMASK, write H2D_MAILBOX_1=1 (hypothesis), msleep+console-dump, write H2D_MAILBOX_0=1 (positive control), msleep+console-dump. Requires T276+T277+T278. (1=enable, 0=off)");
/* T278 helper body is defined after brcmf_pcie_read_ram32 (needs it)
 * and after struct brcmf_pciedev_info. See bcm4360_t278_dump_console_delta
 * later in this file. */

/* BCM4360 test.278: per-stage hook — re-read si[+0x010] for the struct
 * pointer and dump delta since last call. Gated on both T277+T278 to
 * match the post-poll seeding precondition. */
#define BCM4360_T278_HOOK(tag) do { \
	if (bcm4360_test278_console_periodic && \
	    bcm4360_test277_console_decode) { \
		u32 _t278_ptr = brcmf_pcie_read_ram32(devinfo, \
			(devinfo->ci->ramsize - \
			 BCM4360_T276_SHARED_INFO_OFFSET) + \
			BCM4360_T276_SI_FW_STATUS); \
		bcm4360_t278_dump_console_delta(devinfo, tag, _t278_ptr, \
			&devinfo->t278_prev_write_idx); \
	} \
} while (0)

/* BCM4360 test.256 scheduler-walk helper. 2 pr_emerg lines, 16 u32 each.
 * gate_flag arg lets caller pick between sched_walk (t+60s) and
 * sched_walk_early (t+100ms). */
#define BCM4360_T256_SCHED_WALK_COND(gate_flag, stage_tag) do { \
	if (gate_flag) { \
		u32 _d256a[16], _d256b[16]; \
		int _n256; \
		for (_n256 = 0; _n256 < 16; _n256++) { \
			_d256a[_n256] = brcmf_pcie_read_ram32(devinfo, 0x9627C + _n256 * 4); \
			_d256b[_n256] = brcmf_pcie_read_ram32(devinfo, 0x96F2C + _n256 * 4); \
		} \
		pr_emerg("BCM4360 test.256: " stage_tag " TCM[0x9627c..0x962bc] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d256a[0], _d256a[1], _d256a[2], _d256a[3], _d256a[4], _d256a[5], _d256a[6], _d256a[7], \
			 _d256a[8], _d256a[9], _d256a[10], _d256a[11], _d256a[12], _d256a[13], _d256a[14], _d256a[15]); \
		pr_emerg("BCM4360 test.256: " stage_tag " TCM[0x96f2c..0x96f6c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d256b[0], _d256b[1], _d256b[2], _d256b[3], _d256b[4], _d256b[5], _d256b[6], _d256b[7], \
			 _d256b[8], _d256b[9], _d256b[10], _d256b[11], _d256b[12], _d256b[13], _d256b[14], _d256b[15]); \
	} \
} while (0)

/* BCM4360 test.258 IRQ-enable drift probe helper. Reads console buf_ptr
 * at TCM[0x9CC5C] + 16 u32 ring content at TCM[0x9CC20..0x9CC5C] (the
 * 0x40 bytes ending at buf_ptr storage word). 1 pr_emerg line. */
#define BCM4360_T258_BUFPTR_PROBE(stage_tag) do { \
	if (bcm4360_test258_enable_irq || bcm4360_test259_safe_enable_irq || \
	    bcm4360_test260_mask_only || bcm4360_test260_doorbell_only || \
	    bcm4360_test262_msi_poll_only || bcm4360_test263_short || \
	    bcm4360_test264_noloop || bcm4360_test265_short_noloop || \
	    bcm4360_test266_ultra_short_noloop || bcm4360_test267_no_msleep) { \
		u32 _d258bp = brcmf_pcie_read_ram32(devinfo, 0x9CC5C); \
		u32 _d258r[16]; \
		int _n258; \
		for (_n258 = 0; _n258 < 16; _n258++) \
			_d258r[_n258] = brcmf_pcie_read_ram32(devinfo, 0x9CC20 + _n258 * 4); \
		pr_emerg("BCM4360 test.258: " stage_tag " buf_ptr[0x9CC5C]=%08x ring_tail[0x9CC20..0x9CC5C] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d258bp, \
			 _d258r[0], _d258r[1], _d258r[2], _d258r[3], _d258r[4], _d258r[5], _d258r[6], _d258r[7], \
			 _d258r[8], _d258r[9], _d258r[10], _d258r[11], _d258r[12], _d258r[13], _d258r[14], _d258r[15]); \
	} \
} while (0)

/* Legacy T256_SCHED_WALK macro kept for backward compat — t+60s probe. */
#define BCM4360_T256_SCHED_WALK(stage_tag) do { \
	if (bcm4360_test256_sched_walk) { \
		u32 _d256a[16], _d256b[16]; \
		int _n256; \
		for (_n256 = 0; _n256 < 16; _n256++) { \
			_d256a[_n256] = brcmf_pcie_read_ram32(devinfo, 0x9627C + _n256 * 4); \
			_d256b[_n256] = brcmf_pcie_read_ram32(devinfo, 0x96F2C + _n256 * 4); \
		} \
		pr_emerg("BCM4360 test.256: " stage_tag " TCM[0x9627c..0x962bc] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d256a[0], _d256a[1], _d256a[2], _d256a[3], _d256a[4], _d256a[5], _d256a[6], _d256a[7], \
			 _d256a[8], _d256a[9], _d256a[10], _d256a[11], _d256a[12], _d256a[13], _d256a[14], _d256a[15]); \
		pr_emerg("BCM4360 test.256: " stage_tag " TCM[0x96f2c..0x96f6c] = " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x " \
			 "%08x %08x %08x %08x %08x %08x %08x %08x\n", \
			 _d256b[0], _d256b[1], _d256b[2], _d256b[3], _d256b[4], _d256b[5], _d256b[6], _d256b[7], \
			 _d256b[8], _d256b[9], _d256b[10], _d256b[11], _d256b[12], _d256b[13], _d256b[14], _d256b[15]); \
	} \
} while (0)


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
	/* BCM4360 test.276: olmsg DMA buffer handed to fw via shared_info. */
	void *t276_olmsg_buf;
	dma_addr_t t276_olmsg_dma;
	/* BCM4360 test.278: cursor for delta console dumps across the
	 * dwell ladder. Reset on each insmod (kzalloc zeroes it). */
	u32 t278_prev_write_idx;
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


/* BCM4360 test.259 safe IRQ handler — defined here because it needs
 * struct brcmf_pciedev_info + the reg32 helpers above. */
static irqreturn_t bcm4360_t259_safe_handler(int irq, void *arg)
{
	struct brcmf_pciedev_info *devinfo = arg;
	u32 status;

	status = brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->mailboxint);
	if (!status)
		return IRQ_NONE;

	atomic_set(&bcm4360_t259_last_mailboxint, status);
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxint, status);
	brcmf_pcie_write_reg32(devinfo, devinfo->reginfo->mailboxmask, 0);
	atomic_inc(&bcm4360_t259_irq_count);
	return IRQ_HANDLED;
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


/* BCM4360 test.278: re-read console struct at struct_ptr, validate,
 * dump [buf_addr + *prev_idx .. buf_addr + write_idx) as ASCII-escape
 * 128 B chunks (capped at 1024 B per call), advance *prev_idx. On any
 * validation failure or empty delta, log a one-line reason and return. */
static void
bcm4360_t278_dump_console_delta(struct brcmf_pciedev_info *devinfo,
				const char *stage_tag,
				u32 struct_ptr,
				u32 *prev_idx_p)
{
	u32 t278_struct[BCM4360_T277_STRUCT_DWORDS];
	u32 buf_addr, buf_size, write_idx;
	u32 prev = *prev_idx_p;
	u32 delta, to_dump, i, off;

	if (struct_ptr == 0 || struct_ptr >= devinfo->ci->ramsize) {
		pr_emerg("BCM4360 test.278: %s struct_ptr 0x%08x invalid; skipping\n",
			 stage_tag, struct_ptr);
		return;
	}
	for (i = 0; i < BCM4360_T277_STRUCT_DWORDS; i++)
		t278_struct[i] = brcmf_pcie_read_ram32(devinfo,
						       struct_ptr + i * 4);
	buf_addr  = t278_struct[0];
	buf_size  = t278_struct[1];
	write_idx = t278_struct[2];
	if (buf_addr == 0 || buf_addr >= devinfo->ci->ramsize ||
	    buf_size == 0 || buf_size > devinfo->ci->ramsize ||
	    write_idx > buf_size) {
		pr_emerg("BCM4360 test.278: %s struct invalid (buf_addr=0x%08x buf_size=0x%08x wr_idx=0x%08x); skipping\n",
			 stage_tag, buf_addr, buf_size, write_idx);
		return;
	}
	if (write_idx == prev) {
		pr_emerg("BCM4360 test.278: %s no new log (wr_idx=%u unchanged)\n",
			 stage_tag, write_idx);
		return;
	}
	if (write_idx < prev) {
		/* Ring wrapped or reset. Log and restart from 0. */
		pr_emerg("BCM4360 test.278: %s wr_idx=%u < prev=%u (wrap or reset); restarting cursor at 0\n",
			 stage_tag, write_idx, prev);
		prev = 0;
	}
	delta = write_idx - prev;
	to_dump = min_t(u32, delta, (u32)BCM4360_T278_MAX_BYTES_PER_CALL);
	pr_emerg("BCM4360 test.278: %s wr_idx=%u prev=%u delta=%u dumping=%u bytes\n",
		 stage_tag, write_idx, prev, delta, to_dump);

	for (off = 0; off < to_dump; off += BCM4360_T278_CHUNK_BYTES) {
		u8 chunk[BCM4360_T278_CHUNK_BYTES];
		u32 *u32p = (u32 *)chunk;
		u32 this_bytes = min_t(u32, (u32)BCM4360_T278_CHUNK_BYTES,
				       to_dump - off);
		u32 this_dwords = (this_bytes + 3) / 4;
		u32 j;

		for (j = 0; j < this_dwords; j++)
			u32p[j] = brcmf_pcie_read_ram32(
				devinfo,
				buf_addr + prev + off + j * 4);
		pr_emerg("BCM4360 test.278: %s chunk@+%u (%u B): %*pE\n",
			 stage_tag, prev + off, this_bytes,
			 this_bytes, chunk);
	}
	if (delta > BCM4360_T278_MAX_BYTES_PER_CALL)
		pr_emerg("BCM4360 test.278: %s ... truncated %u bytes (wr_idx=%u, dumped up to %u)\n",
			 stage_tag, delta - BCM4360_T278_MAX_BYTES_PER_CALL,
			 write_idx,
			 prev + BCM4360_T278_MAX_BYTES_PER_CALL);
	*prev_idx_p = write_idx;
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
	u32 ioctl = 0xdeadbeef, rstctl = 0xdeadbeef, iostat = 0xdeadbeef;

	/* test.169 confirmed: BCM4360 ARM CR4 wrapbase is core->base + 0x100000
	 * (canonical BCMA AI layout); the previous low-window probe at +0x1000
	 * read a different register (CLK only). Use the high window exclusively.
	 * test.186d adds IOSTATUS (0x40c) to expose firmware-visible wrapper bits. */
	arm_core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_ARM_CR4);
	if (arm_core) {
		pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				      &saved_bar0);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       arm_core->base + 0x100000);
		ioctl  = brcmf_pcie_read_reg32(devinfo, 0x408);
		iostat = brcmf_pcie_read_reg32(devinfo, 0x40c);
		rstctl = brcmf_pcie_read_reg32(devinfo, 0x800);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       saved_bar0);
	}

	brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
	pr_emerg("BCM4360 test.188: %s ARM CR4 IOCTL=0x%08x IOSTATUS=0x%08x RESET_CTL=0x%08x CPUHALT=%s\n",
		 tag, ioctl, iostat, rstctl, (ioctl & 0x20) ? "YES" : "NO");
}


/* test.188: read-only probe of D11 (BCMA_CORE_80211) wrapper.
 *
 * D11 is the 802.11 MAC/PHY core. Firmware bringing up wifi has to reset
 * and enable D11 via its wrapper registers. If firmware reaches the point
 * of D11 bring-up we expect IOCTL/IOSTATUS/RESET_CTL here to change
 * between pre-release and the dwell samples. Same BCMA AI high-window
 * convention as CR4 (wrapbase = core->base + 0x100000).
 */
static void brcmf_pcie_probe_d11_state(struct brcmf_pciedev_info *devinfo,
				       const char *tag)
{
	struct brcmf_core *d11_core;
	u32 saved_bar0;
	u32 ioctl = 0xdeadbeef, rstctl = 0xdeadbeef, iostat = 0xdeadbeef;

	d11_core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_80211);
	if (d11_core) {
		pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				      &saved_bar0);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       d11_core->base + 0x100000);
		ioctl  = brcmf_pcie_read_reg32(devinfo, 0x408);
		iostat = brcmf_pcie_read_reg32(devinfo, 0x40c);
		rstctl = brcmf_pcie_read_reg32(devinfo, 0x800);
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       saved_bar0);
	}

	brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
	pr_emerg("BCM4360 test.188: %s D11 IOCTL=0x%08x IOSTATUS=0x%08x RESET_CTL=0x%08x\n",
		 tag, ioctl, iostat, rstctl);
}


/* test.218: read-only probe of clk_ctl_st (offset 0x1e0) on the cores
 * implicated in ramstbydis polling.
 *
 * BCM4360 firmware traps inside `ramstbydis` at PC 0x000641cb with assert
 * text "v = 43, wd_msticks = 32". Static analysis of ramstbydis (see
 * test.215 RESUME_NOTES) shows it polls bit 17 of [r5+0x1e0] up to 2000
 * times × 10µs (~20ms). Trap data slot[0]=0x18002000.
 *
 * EROM scan (test.217 logs at chip_init) confirms 0x18002000 is **ARM CR4
 * base**, not D11 (D11 base = 0x18001000). So the polled register is
 * **ARM CR4 + 0x1e0 = ARM CR4's clk_ctl_st**. Bit 17 of clk_ctl_st is
 * HAVEHT (HT clock available to this core). The assert means firmware
 * never sees HT clock at ARM CR4 within the ~20ms timeout.
 *
 * This probe samples ARM CR4 + 0x1e0 (the actually-polled register) plus
 * D11 + 0x1e0 (kept for context, expected to skip on IN_RESET=YES). Reads
 * gated on each core's wrapper RESET_CTL — reading 0x1e0 while IN_RESET=YES
 * caused PCIe SLVERR in test.115.
 */
static void brcmf_pcie_probe_one_clkctlst(struct brcmf_pciedev_info *devinfo,
					  struct brcmf_core *core,
					  const char *core_name,
					  const char *tag)
{
	u32 saved_bar0;
	u32 rstctl;
	u32 ccs = 0xdeadbeef;
	bool in_reset;

	pci_read_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
			      &saved_bar0);

	/* Wrapper RESET_CTL via canonical AI high window at base + 0x100000
	 * (confirmed by EROM: every core uses wrap = base + 0x100000). */
	pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
			       core->base + 0x100000);
	rstctl = brcmf_pcie_read_reg32(devinfo, 0x800);
	in_reset = (rstctl & 1) != 0;

	if (!in_reset) {
		pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
				       core->base);
		ccs = brcmf_pcie_read_reg32(devinfo, 0x1e0);
	}

	pci_write_config_dword(devinfo->pdev, BRCMF_PCIE_BAR0_WINDOW,
			       saved_bar0);
	brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);

	if (in_reset) {
		pr_emerg("BCM4360 test.218: %s %s IN_RESET=YES (RST=0x%08x) — clk_ctl_st SKIPPED\n",
			 tag, core_name, rstctl);
		return;
	}

	pr_emerg("BCM4360 test.218: %s %s clk_ctl_st=0x%08x [HAVEHT(17)=%s ALP_AVAIL(16)=%s BP_ON_HT(19)=%s bit6=%s FORCEHT(1)=%s FORCEALP(0)=%s]\n",
		 tag, core_name, ccs,
		 (ccs & BIT(17)) ? "YES" : "no ",
		 (ccs & BIT(16)) ? "YES" : "no ",
		 (ccs & BIT(19)) ? "YES" : "no ",
		 (ccs & BIT(6))  ? "SET" : "clr",
		 (ccs & BIT(1))  ? "YES" : "no ",
		 (ccs & BIT(0))  ? "YES" : "no ");
}

static void brcmf_pcie_probe_d11_clkctlst(struct brcmf_pciedev_info *devinfo,
					  const char *tag)
{
	struct brcmf_core *core;

	core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_ARM_CR4);
	if (core)
		brcmf_pcie_probe_one_clkctlst(devinfo, core, "CR4", tag);
	else
		pr_emerg("BCM4360 test.218: %s ARM CR4 core not found\n", tag);

	core = brcmf_chip_get_core(devinfo->ci, BCMA_CORE_80211);
	if (core)
		brcmf_pcie_probe_one_clkctlst(devinfo, core, "D11", tag);
	else
		pr_emerg("BCM4360 test.218: %s D11 core not found\n", tag);
}


/* test.188: snapshot ChipCommon backplane registers that firmware would
 * typically manipulate during early init, plus pmutimer as a monotonic
 * "is the PMU clocked?" signal. Purely diagnostic; no writes.
 */
#define BRCMF_BP_REG_COUNT 8
static void brcmf_pcie_sample_backplane(struct brcmf_pciedev_info *devinfo,
					u32 vals[BRCMF_BP_REG_COUNT])
{
	brcmf_pcie_select_core(devinfo, BCMA_CORE_CHIPCOMMON);
	vals[0] = READCC32(devinfo, clk_ctl_st);
	vals[1] = READCC32(devinfo, pmucontrol);
	vals[2] = READCC32(devinfo, pmustatus);
	vals[3] = READCC32(devinfo, res_state);
	vals[4] = READCC32(devinfo, pmutimer);
	vals[5] = READCC32(devinfo, min_res_mask);
	vals[6] = READCC32(devinfo, max_res_mask);
	vals[7] = READCC32(devinfo, pmuwatchdog);
}

static const char * const brcmf_bp_reg_names[BRCMF_BP_REG_COUNT] = {
	"clk_ctl_st", "pmucontrol", "pmustatus", "res_state",
	"pmutimer", "min_res_mask", "max_res_mask", "pmuwatchdog"
};


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

	/* test.194: BCM4360 — apply the minimal bcma pcie2 init writes that are
	 * NOT already gated out by our chiprev=3, pcie2_rev=1 silicon:
	 *   - PCIe2 SBMBX (0x098) = 0x1   (unconditional in bcma)
	 *   - PCIe2 PMCR_REFUP (0x1814) |= 0x1f (unconditional in bcma)
	 * Probe PCIe2 MMIO liveness first to avoid the CTO/MCE crash that the
	 * original bypass was added to prevent. If the CLK_CONTROL read returns
	 * 0xffffffff or 0 we abort without doing any writes.
	 */
	if (devinfo->pdev->device == BRCM_PCIE_4360_DEVICE_ID) {
		u32 clk_ctrl, pmcr;

		brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
		clk_ctrl = brcmf_pcie_read_reg32(devinfo, 0x0);
		pr_emerg("BCM4360 test.194: PCIe2 CLK_CONTROL probe = 0x%08x\n",
			  clk_ctrl);

		if (clk_ctrl == 0xffffffff || clk_ctrl == 0) {
			pr_emerg("BCM4360 test.194: PCIe2 looks dead, skipping writes\n");
			return;
		}

		/* SBMBX (indirect config @ 0x098) = 0x1 */
		brcmf_pcie_write_reg32(devinfo,
				       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x098);
		brcmf_pcie_write_reg32(devinfo,
				       BRCMF_PCIE_PCIE2REG_CONFIGDATA, 0x1);
		pr_emerg("BCM4360 test.194: SBMBX write done\n");

		/* PMCR_REFUP (indirect config @ 0x1814) |= 0x1f */
		brcmf_pcie_write_reg32(devinfo,
				       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x1814);
		pmcr = brcmf_pcie_read_reg32(devinfo,
					     BRCMF_PCIE_PCIE2REG_CONFIGDATA);
		brcmf_pcie_write_reg32(devinfo,
				       BRCMF_PCIE_PCIE2REG_CONFIGADDR, 0x1814);
		brcmf_pcie_write_reg32(devinfo,
				       BRCMF_PCIE_PCIE2REG_CONFIGDATA,
				       pmcr | 0x1f);
		pr_emerg("BCM4360 test.194: PMCR_REFUP 0x%08x -> 0x%08x\n",
			  pmcr, pmcr | 0x1f);

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

		/* test.233: TCM persistence probe — read two cells at
		 * 0x90000 / 0x90004 (past 442 KB fw image, before NVRAM
		 * slot at 0x9ff1c). Read happens after chip_attach + its
		 * probe-start SBR. Interpretation:
		 *   Run 1 (fresh SMC-reset boot): expect 0 / garbage
		 *   Run 2 (same boot, no reset): expect magic from Run 1
		 *     → if seen, TCM survives rmmod/insmod + probe-start SBR
		 *   Run 3 (after SMC reset + reboot): expect magic from Run 2
		 *     → if seen, TCM survives SMC reset; logger is viable
		 *     → if 0, SMC reset wipes TCM; pick a different transport
		 */
		{
			u32 persist_pre_a = brcmf_pcie_read_tcm32(devinfo, 0x90000);
			u32 persist_pre_b = brcmf_pcie_read_tcm32(devinfo, 0x90004);
			pr_emerg("BCM4360 test.233: PRE-READ TCM[0x90000]=0x%08x TCM[0x90004]=0x%08x (expect 0 fresh, 0xDEADBEEF/0xCAFEBABE if preserved)\n",
				 persist_pre_a, persist_pre_b);
		}
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
		u32 chunk_words = 4096 / 4;	/* test.225: 4KB breadcrumbs (was 16KB); finer hang resolution */
		u32 total_words = (u32)(fw->size / 4);
		u32 tail = fw->size & 3u;
		void __iomem *wbase = devinfo->tcm + devinfo->ci->rambase;
		u32 i;
		u32 pre_tcm[8] = {0};	/* image-header window TCM[0x0..0x1c] */
		u32 pre_marker = 0;	/* NVRAM marker at ramsize-4 */
		u32 pre_wide[40] = {0};	/* test.188: 16-KB grid across 640-KB TCM */
		u32 pre_tail[16] = {0};	/* test.188: last 64 B of TCM */
		u32 pre_bp[BRCMF_BP_REG_COUNT] = {0};	/* test.188: backplane regs */
		const u32 nr_fw_samples = 16;	/* test.222: reduced 256->16 (log storm crashed host in test.221) */
		u32 *pre_fw_sample = NULL;	/* test.188: heap-alloc'd — see below */
		u32 *fw_sample_offsets = NULL;	/* heap-alloc'd offsets for each sample */
		/* test.197: fine-grain scan over 0x90000..0xa0000 (upper TCM
		 * where test.196 saw the only firmware-originated writes:
		 * 0x98000 zeroed, 0x9c000 = "STAK" marker). 4-byte stride
		 * over 64 KB = 16384 cells = 64 KB heap. Post-dwell scan
		 * logs CHANGED entries only plus a summary count.
		 */
		const u32 fine_base = 0x90000;
		const u32 fine_stride = 4;
		const u32 nr_fine = 0x10000 / 4;	/* 16384 cells */
		u32 *pre_fine = NULL;
		/* test.199: end-of-dwell hex+ASCII dump regions. Two ranges
		 * around the firmware-init data structure caught in
		 * tests 196/197/198. Each range is dumped as 16-byte rows
		 * (4 × u32 + ASCII rendering) so we can read adjacent text
		 * fields and any format-string templates.
		 */
		static const u32 dump_ranges[][2] = {
			{0x40660, 0x406c0},	/* strings */
			{0x40700, 0x41000},	/* test.214: PCIe-dongle string slab (no fmt match) */
			{0x41000, 0x42000},	/* test.215: AI core / olmsg / rpc strings (no fmt match) */
			{0x00000, 0x01000},	/* test.218: ARM vectors + SVC handler (kept from test.217) */
			{0x40000, 0x40400},	/* early boot/init code */
			{0x40400, 0x40660},	/* code immediately before strings */
			{0x64280, 0x64500},	/* code immediately after asserting function */
			{0x63e00, 0x64280},	/* asserting function 0x64028..0x6422a */
			{0x62a00, 0x62c00},	/* chip-info struct */
			{0x9cc00, 0x9d000},	/* trap data + assert text */
			{0x9ff00, 0xa0000},	/* TCM top — NVRAM delivery check */
		};
		static const u32 wide_offsets[40] = {
			0x00000, 0x04000, 0x08000, 0x0c000,
			0x10000, 0x14000, 0x18000, 0x1c000,
			0x20000, 0x24000, 0x28000, 0x2c000,
			0x30000, 0x34000, 0x38000, 0x3c000,
			0x40000, 0x44000, 0x48000, 0x4c000,
			0x50000, 0x54000, 0x58000, 0x5c000,
			0x60000, 0x64000, 0x68000, 0x6c000,
			0x70000, 0x74000, 0x78000, 0x7c000,
			0x80000, 0x84000, 0x88000, 0x8c000,
			0x90000, 0x94000, 0x98000, 0x9c000
		};

		/* test.188: heap-allocate fw-sample buffers (2 KB total) to keep
		 * kernel stack under the 2 KB warn threshold. Allocation failure
		 * is non-fatal — the fw-integrity probe is simply skipped.
		 */
		pre_fw_sample = kcalloc(nr_fw_samples, sizeof(u32), GFP_KERNEL);
		fw_sample_offsets = kcalloc(nr_fw_samples, sizeof(u32), GFP_KERNEL);
		if (!pre_fw_sample || !fw_sample_offsets) {
			pr_emerg("BCM4360 test.188: fw-sample kcalloc failed — probe D disabled\n");
			kfree(pre_fw_sample);
			kfree(fw_sample_offsets);
			pre_fw_sample = NULL;
			fw_sample_offsets = NULL;
		}

		/* test.197: heap-alloc fine-grain scan buffer (64 KB) */
		pre_fine = kcalloc(nr_fine, sizeof(u32), GFP_KERNEL);
		if (!pre_fine)
			pr_emerg("BCM4360 test.197: pre_fine kcalloc(64K) failed — fine scan disabled\n");

		/* Pre-halt probe (hi-window only since test.169) */
		brcmf_pcie_probe_armcr4_state(devinfo, "pre-halt");
		brcmf_pcie_probe_d11_state(devinfo, "pre-halt");
		brcmf_pcie_probe_d11_clkctlst(devinfo, "pre-halt");
		mdelay(50);

		/* test.167: re-halt ARM CR4 via the public chip API. */
		pr_emerg("BCM4360 test.188: re-halting ARM CR4 via brcmf_chip_set_passive\n");
		mdelay(50);
		brcmf_chip_set_passive(devinfo->ci);
		mdelay(100);	/* settle */

		/* Post-halt probe */
		brcmf_pcie_probe_armcr4_state(devinfo, "post-halt");
		mdelay(50);

		pr_emerg("BCM4360 test.188: starting chunked fw write, total_words=%u (%zu bytes) tail=%u wbase=%px\n",
			 total_words, fw->size, tail, wbase);
		mdelay(50);

		for (i = 0; i < total_words; i++) {
			iowrite32(le32_to_cpu(src32[i]), wbase + i * 4);
			if ((i + 1) % chunk_words == 0) {
				/* test.225: read back the last word we wrote.
				 * - matches src32[i] → BAR2 write OK, bus alive
				 * - 0xffffffff → BAR2 window dead (PMU/TCM gone)
				 * - hang → whole backplane dead
				 * This lets us distinguish silent drops from bus death.
				 */
				u32 want = le32_to_cpu(src32[i]);
				u32 got = ioread32(wbase + i * 4);
				pr_emerg("BCM4360 test.225: wrote %u words (%u bytes) last=0x%08x readback=0x%08x %s\n",
					 i + 1, (i + 1) * 4, want, got,
					 got == want ? "OK" :
					 got == 0xffffffff ? "DEAD" : "MISMATCH");
				mdelay(50);
			}
		}

		pr_emerg("BCM4360 test.188: all %u words written, before tail (tail=%u)\n",
			 total_words, tail);
		mdelay(50);

		if (tail) {
			u32 tmp = 0;

			memcpy(&tmp, (const u8 *)fw->data + (fw->size & ~3u),
			       tail);
			iowrite32(tmp, wbase + (fw->size & ~3u));
			pr_emerg("BCM4360 test.188: tail %u bytes written at offset %zu\n",
				 tail, fw->size & ~3u);
			mdelay(50);
		}

		pr_emerg("BCM4360 test.188: fw write complete (%zu bytes)\n",
			 fw->size);
		/* test.188: test.181 proved brcmf_chip_set_active(ci, resetintr)
		 * succeeds on BCM4360 — ARM CR4 IOCTL 0x21 → 0x01 (CPUHALT YES→NO),
		 * host stable for 30 s. Now extend the post-release observation to
		 * detect firmware-originated TCM writes: snapshot TCM[0x0..0x1c]
		 * + NVRAM marker before release, then fine-grain tier-1 (~100-150 ms)
		 * and tier-2 (~150-1650 ms) for transient activity, then re-read
		 * with a diff at dwell-3000 ms for late-persistence state.
		 * BusMaster still cleared. Still no sharedram polling and no
		 * advance into normal attach; we release fw/nvram and return -ENODEV.
		 */
		pr_emerg("BCM4360 test.188: before post-fw msleep(100)\n");
		msleep(100);
		pr_emerg("BCM4360 test.188: after post-fw msleep(100)\n");
		resetintr = get_unaligned_le32(fw->data);
		pr_emerg("BCM4360 test.188: host resetintr=0x%08x before NVRAM\n",
			 resetintr);

		if (nvram) {
			void __iomem *naddr;
			const __le32 *nsrc32 = (const __le32 *)nvram;
			u32 nwords = nvram_len / 4;
			u32 ntail = nvram_len & 3;
			u32 nchunk = 1024;	/* 4 KB breadcrumbs */
			u32 j;

			address = devinfo->ci->rambase + devinfo->ci->ramsize -
				  nvram_len;
			naddr = devinfo->tcm + address;
			pr_emerg("BCM4360 test.188: pre-NVRAM write address=0x%x len=%u naddr=%px\n",
				 address, nvram_len, naddr);

			for (j = 0; j < nwords; j++) {
				iowrite32(le32_to_cpu(nsrc32[j]),
					  naddr + j * 4);
				if ((j + 1) % nchunk == 0) {
					pr_emerg("BCM4360 test.188: NVRAM wrote %u words (%u bytes)\n",
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
			pr_emerg("BCM4360 test.188: post-NVRAM write done (%u bytes)\n",
				 nvram_len);

			/* test.236: write the upstream Apple-style random_seed
			 * buffer that lives just below the NVRAM in TCM. Footer
			 * (8 B: magic 0xfeedc0de + length 0x100) sits at
			 * NVRAM_start - 8; 256 B of random bytes sit at
			 * NVRAM_start - 8 - 256. Upstream wraps this in
			 * `if (devinfo->otp.valid)` and places the block in the
			 * post-return-ENODEV dead path (line ~2941), so the BCM4360
			 * probe never writes the seed. With this module param set
			 * we force the write and verify the footer magic landed.
			 */
			if (bcm4360_test236_force_seed) {
				size_t rand_len = BRCMF_RANDOM_SEED_LENGTH;
				struct brcmf_random_seed_footer footer = {
					.length = cpu_to_le32(rand_len),
					.magic = cpu_to_le32(BRCMF_RANDOM_SEED_MAGIC),
				};
				u32 footer_addr = address - sizeof(footer);
				u32 rand_addr = footer_addr - rand_len;
				u32 rb_magic, rb_length;

				pr_emerg("BCM4360 test.236: writing random_seed footer at TCM[0x%05x] magic=0x%08x len=0x%x\n",
					 footer_addr, BRCMF_RANDOM_SEED_MAGIC,
					 (u32)rand_len);
				brcmf_pcie_copy_mem_todev(devinfo, footer_addr,
							  &footer,
							  sizeof(footer));
				pr_emerg("BCM4360 test.236: writing random_seed buffer at TCM[0x%05x] (%u bytes)\n",
					 rand_addr, (u32)rand_len);
				brcmf_pcie_provide_random_bytes(devinfo,
								rand_addr);

				/* verify footer magic + length readback */
				rb_length = brcmf_pcie_read_tcm32(devinfo,
								  footer_addr);
				rb_magic = brcmf_pcie_read_tcm32(devinfo,
								 footer_addr + 4);
				pr_emerg("BCM4360 test.236: seed footer readback length=0x%08x magic=0x%08x (expect 0x%08x / 0x%08x)\n",
					 rb_length, rb_magic,
					 (u32)rand_len,
					 BRCMF_RANDOM_SEED_MAGIC);
			}

			sharedram_addr_written =
				brcmf_pcie_read_ram32(devinfo,
						       devinfo->ci->ramsize - 4);
			pre_marker = sharedram_addr_written;
			pr_emerg("BCM4360 test.188: NVRAM marker at ramsize-4 = 0x%08x (pre-release snapshot)\n",
				 sharedram_addr_written);
			for (j = 0; j < 8; j++) {
				u32 offset = j * 4;
				u32 val = brcmf_pcie_read_ram32(devinfo, offset);

				pre_tcm[j] = val;
				pr_emerg("BCM4360 test.188: TCM[0x%04x]=0x%08x (pre-release snapshot)\n",
					 offset, val);
			}
			/* test.188: 16-KB wide grid across the full 640-KB TCM.
			 * test.184 saw all 32 sample points unchanged at 3 s —
			 * if firmware is rewriting *any* 16-KB block of the image
			 * we'll now see it. Every probe point is inside ramsize
			 * (0xa0000 = 640 KB); points at/above 0x4000 overlap the
			 * firmware image and should read as code, so any change
			 * is either firmware rewriting its own image or an
			 * external agent stomping TCM.
			 */
			for (j = 0; j < ARRAY_SIZE(wide_offsets); j++) {
				u32 offset = wide_offsets[j];
				u32 val = brcmf_pcie_read_ram32(devinfo, offset);

				pre_wide[j] = val;
				pr_emerg("BCM4360 test.188: wide-TCM[0x%05x]=0x%08x (pre-release snapshot)\n",
					 offset, val);
			}
			/* test.197: fine-grain pre-release snapshot of upper TCM
			 * (0x90000..0xa0000) at 4-byte stride. Silent — only
			 * post-dwell CHANGED entries get printed, plus a summary.
			 */
			if (pre_fine) {
				for (j = 0; j < nr_fine; j++) {
					u32 offset = fine_base + j * fine_stride;
					pre_fine[j] = brcmf_pcie_read_ram32(devinfo,
									    offset);
				}
				pr_emerg("BCM4360 test.197: fine-TCM pre-release snapshot complete (%u cells, base=0x%05x stride=%u)\n",
					 nr_fine, fine_base, fine_stride);
			}
			/* test.188: last 64 bytes of TCM cover the sharedram
			 * address slot (upstream convention: ramsize - 8) and
			 * other potential firmware handshake fields adjacent
			 * to the NVRAM marker at ramsize - 4.
			 */
			for (j = 0; j < ARRAY_SIZE(pre_tail); j++) {
				u32 offset = devinfo->ci->ramsize - 64 + j * 4;
				u32 val = brcmf_pcie_read_ram32(devinfo, offset);

				pre_tail[j] = val;
				pr_emerg("BCM4360 test.188: tail-TCM[0x%05x]=0x%08x (pre-release snapshot)\n",
					 offset, val);
			}
			/* test.188: sample firmware region at 256 evenly spaced offsets */
			/* High-density sampling (every ~1.7 KB across 442 KB fw) */
			if (fw->size >= 1024 && fw_sample_offsets) {  /* Need reasonable size and alloc success */
				u32 step = fw->size / (nr_fw_samples - 1);
				if (step < 4) step = 4;  /* Minimum 4-byte alignment */

				for (j = 0; j < nr_fw_samples; j++) {
					u32 offset = j * step;
					/* Ensure offset is 4-byte aligned and within fw size */
					offset = (offset + 3) & ~3u;
					if (offset >= fw->size) offset = fw->size - 4;
					
					fw_sample_offsets[j] = offset;
					u32 val = brcmf_pcie_read_ram32(devinfo, offset);
					pre_fw_sample[j] = val;
					u32 fw_val = get_unaligned_le32(fw->data + offset);
					pr_emerg("BCM4360 test.188: fw-sample[0x%05x]=0x%08x (TCM) vs 0x%08x (fw->data) %s\n",
						offset, val, fw_val,
						val == fw_val ? "MATCH" : "MISMATCH");
				}
			} else {
				pr_emerg("BCM4360 test.188: firmware too small (%zu bytes) for sampling, skipping\n",
					fw->size);
			}
			/* test.188: backplane-register snapshot via ChipCommon.
			 * pmutimer ticks at ILP clock (~32 kHz) so a positive
			 * delta between pre-release and dwell reads directly
			 * confirms the PMU is alive independent of any firmware
			 * behaviour. clk_ctl_st/pmustatus/res_state/min/max_res
			 * all change when firmware runs its clock/resource setup.
			 */
			brcmf_pcie_sample_backplane(devinfo, pre_bp);
			for (j = 0; j < BRCMF_BP_REG_COUNT; j++)
				pr_emerg("BCM4360 test.188: CC-%s=0x%08x (pre-release snapshot)\n",
					 brcmf_bp_reg_names[j], pre_bp[j]);
		} else {
			pr_emerg("BCM4360 test.188: no NVRAM loaded before early return\n");
		}

		pr_emerg("BCM4360 test.226: past pre-release snapshot — entering INTERNAL_MEM lookup\n");
		msleep(5);

		{
			struct brcmf_core *imem_core;

			imem_core = brcmf_chip_get_core(devinfo->ci,
							BCMA_CORE_INTERNAL_MEM);
			pr_emerg("BCM4360 test.226: after brcmf_chip_get_core(INTERNAL_MEM) = %p\n",
				 imem_core);
			msleep(5);
			if (imem_core) {
				pr_emerg("BCM4360 test.188: pre-resetcore INTERNAL_MEM core->base=0x%08x rev=%u\n",
					 imem_core->base, imem_core->rev);
				mdelay(50);
				brcmf_chip_resetcore(imem_core, 0, 0, 0);
				mdelay(50);
				pr_emerg("BCM4360 test.188: post-resetcore INTERNAL_MEM complete\n");
			} else {
				pr_emerg("BCM4360 test.188: INTERNAL_MEM core not found — resetcore skipped (expected on BCM4360)\n");
			}
		}
		pr_emerg("BCM4360 test.226: past INTERNAL_MEM block — entering pre-set-active probes\n");
		msleep(5);
		{
			bool sa_rc __maybe_unused = false;
			/* test.196: 12 × 250 ms = 3000 ms dwell, low-poll
			 * harness (replaces the single 1250 ms + heavy MMIO
			 * storm that crashed test.195 once HT resources came
			 * up). Each tick samples ChipCommon backplane only
			 * (safe even with HT clock active).
			 */
			static const u32 dwell_labels_ms[] = {
				250, 500, 750, 1000, 1250, 1500,
				1750, 2000, 2250, 2500, 2750, 3000
			};
			static const u32 dwell_increments_ms[] = {
				250, 250, 250, 250, 250, 250,
				250, 250, 250, 250, 250, 250
			};
			u32 d;
			u32 j;

			brcmf_pcie_probe_armcr4_state(devinfo,
						      "pre-set-active");
			brcmf_pcie_probe_d11_state(devinfo,
						   "pre-set-active");
			brcmf_pcie_probe_d11_clkctlst(devinfo,
						      "pre-set-active");
			pr_emerg("BCM4360 test.226: past pre-set-active probes — before 50ms pre-BM delay\n");
			msleep(5);
			mdelay(50);

			/* test.188: enable BusMaster BEFORE set_active so
			 * firmware's first DMA can complete. test.64/65-era
			 * comments (lines ~2725-2742, ~4033-4037) established
			 * that without BusMaster the firmware DMA init fails
			 * every ~3 s. MMIO guard before and after. */
			{
				u16 cmd_pre_bm, cmd_post_bm;
				u32 mmio_guard;

				pr_emerg("BCM4360 test.226: before pre-BM mailboxint MMIO read\n");
				msleep(5);
				mmio_guard = brcmf_pcie_read_reg32(devinfo,
						devinfo->reginfo->mailboxint);
				pci_read_config_word(devinfo->pdev,
						     PCI_COMMAND,
						     &cmd_pre_bm);
				pr_emerg("BCM4360 test.188: pre-BM PCI_COMMAND=0x%04x BM=%s MMIO guard mailboxint=0x%08x\n",
					 cmd_pre_bm,
					 (cmd_pre_bm & PCI_COMMAND_MASTER) ?
						"ON" : "OFF",
					 mmio_guard);

				/* test.233: restore pci_set_master (test.230
				 * baseline) — test.232 proved BM=OFF did not
				 * prevent the wedge, so pure DMA-completion-waiting
				 * is falsified. For test.233 (TCM persistence
				 * probe) we want the cleanest proven-safe probe
				 * path, which is test.230 (set_active SKIPPED,
				 * pci_set_master enabled). No functional change
				 * here vs test.230/231.
				 */
				pr_emerg("BCM4360 test.226: before pci_set_master\n");
				msleep(5);
				pci_set_master(devinfo->pdev);
				pr_emerg("BCM4360 test.226: after pci_set_master\n");
				msleep(5);
				pci_read_config_word(devinfo->pdev,
						     PCI_COMMAND,
						     &cmd_post_bm);
				pr_emerg("BCM4360 test.188: pci_set_master done; PCI_COMMAND=0x%04x BM=%s (before set_active)\n",
					 cmd_post_bm,
					 (cmd_post_bm & PCI_COMMAND_MASTER) ?
						"ON" : "OFF");

				mmio_guard = brcmf_pcie_read_reg32(devinfo,
						devinfo->reginfo->mailboxint);
				pr_emerg("BCM4360 test.188: post-BM-on MMIO guard mailboxint=0x%08x (endpoint still responsive)\n",
					 mmio_guard);
			}

			/* BCM4360 test.241: BAR0 write-path sentinel round-trip
			 * on MAILBOXMASK (0x4C). De-confounds test.240's
			 * readback=0 on DB1 ring. Expected PASS outcome:
			 * baseline=0, after-sentinel=0xDEADBEEF, after-clear=0. */
			if (bcm4360_test241_writeverify) {
				u32 baseline, after_sent, after_clear;
				const u32 MBM = devinfo->reginfo->mailboxmask;

				pr_emerg("BCM4360 test.241: write-verify target MAILBOXMASK offset=0x%x (BAR0)\n",
					 MBM);
				baseline = brcmf_pcie_read_reg32(devinfo, MBM);
				pr_emerg("BCM4360 test.241: MAILBOXMASK baseline=0x%08x (expect 0x00000000)\n",
					 baseline);
				brcmf_pcie_write_reg32(devinfo, MBM, 0xDEADBEEF);
				after_sent = brcmf_pcie_read_reg32(devinfo, MBM);
				pr_emerg("BCM4360 test.241: after write=0xDEADBEEF readback=0x%08x (expect 0xDEADBEEF)\n",
					 after_sent);
				brcmf_pcie_write_reg32(devinfo, MBM, 0);
				after_clear = brcmf_pcie_read_reg32(devinfo, MBM);
				pr_emerg("BCM4360 test.241: after write=0x00000000 readback=0x%08x (expect 0x00000000)\n",
					 after_clear);
				pr_emerg("BCM4360 test.241: RESULT %s (sentinel-match=%d baseline-zero=%d clear-zero=%d)\n",
					 (after_sent == 0xDEADBEEF &&
					  baseline == 0 && after_clear == 0) ?
						"PASS" : "FAIL",
					 after_sent == 0xDEADBEEF,
					 baseline == 0, after_clear == 0);
			}

			/* BCM4360 test.245: pre-FORCEHT BAR0 write-verify under explicit
			 * select_core(PCIE2). Same round-trip shape as T243 but at the
			 * known-safe pre-FORCEHT stage. Answers "do BAR0 writes to PCIE2
			 * registers latch when the window is correctly selected?" */
			if (bcm4360_test245_writeverify_preforcehttp) {
				const u32 _mbm = devinfo->reginfo->mailboxmask;
				u32 _win_before = 0, _win_after = 0;
				u32 _base, _after_sent, _after_restore;
				int _sent_match, _restore_match;
				u32 _t = 0x90000;
				u32 _b2_base, _b2_sent, _b2_restore;
				int _b2_sent_match, _b2_restore_match;

				pci_read_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, &_win_before);
				brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
				pci_read_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, &_win_after);
				pr_emerg("BCM4360 test.245: pre-FORCEHT BAR0_WINDOW before=0x%08x after=0x%08x (expect PCIE2 core base)\n",
					 _win_before, _win_after);

				_base = brcmf_pcie_read_reg32(devinfo, _mbm);
				brcmf_pcie_write_reg32(devinfo, _mbm, ~_base);
				_after_sent = brcmf_pcie_read_reg32(devinfo, _mbm);
				brcmf_pcie_write_reg32(devinfo, _mbm, _base);
				_after_restore = brcmf_pcie_read_reg32(devinfo, _mbm);
				_sent_match = (_after_sent == ~_base);
				_restore_match = (_after_restore == _base);
				pr_emerg("BCM4360 test.245: pre-FORCEHT MBM (BAR0+0x%x @window=0x%08x) baseline=0x%08x sent=0x%08x (match=%d) restored=0x%08x (match=%d) RESULT %s\n",
					 _mbm, _win_after, _base, _after_sent, _sent_match,
					 _after_restore, _restore_match,
					 (_sent_match && _restore_match) ? "PASS" : "FAIL");

				/* Restore prior BAR0_WINDOW so FORCEHT block downstream is
				 * unperturbed (FORCEHT does its own select_core(CHIPCOMMON)
				 * immediately after this, so strictly not required, but
				 * principle: don't leave global state changed). */
				pci_write_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, _win_before);

				/* BAR2 TCM[0x90000] round-trip — independent axis.
				 * BAR2 does not use BAR0_WINDOW, so this is a clean
				 * "is ANY MMIO write landing at pre-FORCEHT" sanity. */
				_b2_base = brcmf_pcie_read_ram32(devinfo, _t);
				brcmf_pcie_write_ram32(devinfo, _t, ~_b2_base);
				_b2_sent = brcmf_pcie_read_ram32(devinfo, _t);
				brcmf_pcie_write_ram32(devinfo, _t, _b2_base);
				_b2_restore = brcmf_pcie_read_ram32(devinfo, _t);
				_b2_sent_match = (_b2_sent == ~_b2_base);
				_b2_restore_match = (_b2_restore == _b2_base);
				pr_emerg("BCM4360 test.245: pre-FORCEHT BAR2 TCM[0x%05x] baseline=0x%08x sent=0x%08x (match=%d) restored=0x%08x (match=%d) RESULT %s\n",
					 _t, _b2_base, _b2_sent, _b2_sent_match,
					 _b2_restore, _b2_restore_match,
					 (_b2_sent_match && _b2_restore_match) ? "PASS" : "FAIL");
			}

			/* BCM4360 test.246: upstream-production MBM write-verify.
			 * Writes int_d2h_db|int_fn0 (= 0x00FF0300 for 4360) and
			 * logs readback — tells us whether the documented legal
			 * bits all latch at pre-FORCEHT, vs. only FN0 bits. */
			if (bcm4360_test246_writeverify_legal) {
				const u32 _mbm2 = devinfo->reginfo->mailboxmask;
				const u32 _legal = devinfo->reginfo->int_d2h_db |
						   devinfo->reginfo->int_fn0;
				u32 _t246_win_before = 0, _t246_win_after = 0;
				u32 _t246_b, _t246_s, _t246_r;

				pci_read_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, &_t246_win_before);
				brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
				pci_read_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, &_t246_win_after);
				pr_emerg("BCM4360 test.246: pre-FORCEHT BAR0_WINDOW before=0x%08x after=0x%08x (expect PCIE2 base)\n",
					 _t246_win_before, _t246_win_after);

				_t246_b = brcmf_pcie_read_reg32(devinfo, _mbm2);
				brcmf_pcie_write_reg32(devinfo, _mbm2, _legal);
				_t246_s = brcmf_pcie_read_reg32(devinfo, _mbm2);
				brcmf_pcie_write_reg32(devinfo, _mbm2, _t246_b);
				_t246_r = brcmf_pcie_read_reg32(devinfo, _mbm2);
				pr_emerg("BCM4360 test.246: pre-FORCEHT MBM legal-pattern baseline=0x%08x wrote=0x%08x readback=0x%08x (exact=%d d2h_db_latched=%d fn0_latched=%d) restored=0x%08x (restore_match=%d) RESULT %s\n",
					 _t246_b, _legal, _t246_s,
					 _t246_s == _legal,
					 (_t246_s & 0x00FF0000) == (_legal & 0x00FF0000),
					 (_t246_s & 0x00000300) == (_legal & 0x00000300),
					 _t246_r, _t246_r == _t246_b,
					 (_t246_s == _legal && _t246_r == _t246_b)
						? "PASS" : "FAIL");

				pci_write_config_dword(devinfo->pdev,
					BRCMF_PCIE_BAR0_WINDOW, _t246_win_before);
			}

			/* BCM4360 test.247: pre-place a 72-byte pcie_shared-shaped
			 * struct at TCM[0x80000]. Version byte at offset 0; all
			 * other u32s zero. Readback all 18 u32s (72 bytes) so we
			 * confirm BAR2 write landed on-chip before set_active.
			 * Dwell-poll reads these same 18 u32s at every ladder
			 * breadcrumb (see BCM4360_T239_POLL extension below). */
			if (bcm4360_test247_preplace_shared) {
				const u32 _t247_base = 0x80000;
				u32 _t247_rb[18];
				int _t247_i;

				for (_t247_i = 0; _t247_i < 18; _t247_i++)
					brcmf_pcie_write_ram32(devinfo,
						_t247_base + _t247_i * 4, 0);
				brcmf_pcie_write_ram32(devinfo, _t247_base,
					BRCMF_PCIE_MIN_SHARED_VERSION);
				for (_t247_i = 0; _t247_i < 18; _t247_i++)
					_t247_rb[_t247_i] = brcmf_pcie_read_ram32(devinfo,
						_t247_base + _t247_i * 4);
				pr_emerg("BCM4360 test.247: pre-FORCEHT pre-placed shared-struct at TCM[0x%05x] (72 bytes, version=%u @offset 0, rest=0); readback = %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x %08x\n",
					 _t247_base,
					 BRCMF_PCIE_MIN_SHARED_VERSION,
					 _t247_rb[0], _t247_rb[1], _t247_rb[2],
					 _t247_rb[3], _t247_rb[4], _t247_rb[5],
					 _t247_rb[6], _t247_rb[7], _t247_rb[8],
					 _t247_rb[9], _t247_rb[10], _t247_rb[11],
					 _t247_rb[12], _t247_rb[13], _t247_rb[14],
					 _t247_rb[15], _t247_rb[16], _t247_rb[17]);
			}

			/* BCM4360 test.248: baseline snapshot at pre-FORCEHT —
			 * 16 u32 offsets across upper TCM. Paired with a pre-
			 * wedge snapshot at the t+90000ms dwell; diff per
			 * offset = fw touched that region. */
			BCM4360_T248_WIDESCAN("pre-FORCEHT");

			pr_emerg("BCM4360 test.226: past BusMaster dance — entering FORCEHT block\n");
			msleep(5);

			/* test.219: force HT clock by setting FORCEHT (bit 1)
			 * of ChipCommon clk_ctl_st before set_active.
			 * Test.218 proved HAVEHT (bit 17) stuck CLEAR
			 * chip-wide throughout dwell — firmware ramstbydis
			 * times out polling for it. Hypothesis: HT request
			 * was never made; FORCEHT tells PMU to bring HT up.
			 */
			{
				u32 ccs_pre, ccs_post;

				pr_emerg("BCM4360 test.226: before FORCEHT select_core+READCC32\n");
				msleep(5);
				brcmf_pcie_select_core(devinfo,
						       BCMA_CORE_CHIPCOMMON);
				ccs_pre = READCC32(devinfo, clk_ctl_st);
				WRITECC32(devinfo, clk_ctl_st,
					  ccs_pre | BIT(1));
				udelay(50);
				ccs_post = READCC32(devinfo, clk_ctl_st);
				pr_emerg("BCM4360 test.219: FORCEHT write CC clk_ctl_st pre=0x%08x post=0x%08x [HAVEHT(17)=%s ALP_AVAIL(16)=%s FORCEHT(1)=%s]\n",
					 ccs_pre, ccs_post,
					 (ccs_post & BIT(17)) ? "YES" : "no ",
					 (ccs_post & BIT(16)) ? "YES" : "no ",
					 (ccs_post & BIT(1))  ? "YES" : "no ");
			}
			pr_emerg("BCM4360 test.226: past FORCEHT write — before 2ms+probe+20ms+set_active\n");
			msleep(5);
			mdelay(2);
			brcmf_pcie_probe_d11_clkctlst(devinfo,
						      "post-FORCEHT-write");

			mdelay(20);
			pr_emerg("BCM4360 test.219: calling brcmf_chip_set_active resetintr=0x%08x (FORCEHT pre-applied)\n",
				 resetintr);
			mdelay(30);

			/* test.236: skip the test.234 zero block when forcing a
			 * seed write, since the zero range overlaps the random_seed
			 * area (footer at NVRAM_start - 8, random bytes 256 B
			 * below) and would clobber it. */
			if (!bcm4360_test236_force_seed) {
			/* test.234: cheapest-tier shared-memory-struct probe.
			 * Zero the upper TCM region [0x9FE00..0x9FF1C) — 284
			 * bytes / 71 dwords — that is above the fw image and
			 * below the NVRAM slot, where our code never writes.
			 * test.233 showed this region has a deterministic non-
			 * zero SRAM fingerprint on a fresh SMC-reset boot.
			 * Hypothesis: fw reads a value there and uses it as a
			 * DMA target during boot; zeroing it changes behavior
			 * (NULL-DMA more likely to be cleanly rejected than a
			 * fingerprint-derived bogus address). Then re-enable
			 * brcmf_chip_set_active (test.231 path) and dwell with
			 * breadcrumbs to compare tail-truncation point vs
			 * test.231/232.
			 */
			{
				u32 j, nz_pre = 0, nz_post = 0;
				const u32 start = 0x9FE00;
				const u32 end   = 0x9FF1C;
				const u32 count = (end - start) / 4; /* 71 */

				pr_emerg("BCM4360 test.234: PRE-ZERO scan [0x%05x..0x%05x) %u dwords\n",
					 start, end, count);
				for (j = 0; j < count; j++) {
					u32 addr = start + j * 4;
					u32 val = brcmf_pcie_read_tcm32(devinfo, addr);
					if (val != 0) {
						pr_emerg("BCM4360 test.234: pre-zero TCM[0x%05x]=0x%08x\n",
							 addr, val);
						nz_pre++;
					}
				}
				pr_emerg("BCM4360 test.234: pre-zero scan %u/%u non-zero\n",
					 nz_pre, count);

				pr_emerg("BCM4360 test.234: zeroing TCM[0x%05x..0x%05x)\n",
					 start, end);
				for (j = 0; j < count; j++) {
					u32 addr = start + j * 4;
					brcmf_pcie_write_tcm32(devinfo, addr, 0);
				}

				for (j = 0; j < count; j++) {
					u32 addr = start + j * 4;
					u32 val = brcmf_pcie_read_tcm32(devinfo, addr);
					if (val != 0) {
						pr_emerg("BCM4360 test.234: VERIFY-FAIL TCM[0x%05x]=0x%08x (expected 0)\n",
							 addr, val);
						nz_post++;
					}
				}
				pr_emerg("BCM4360 test.234: zero verify %u/%u non-zero (expect 0)\n",
					 nz_post, count);
			}
			} /* end if (!bcm4360_test236_force_seed) for test.234 zero block */

			if (bcm4360_test235_skip_set_active) {
				pr_emerg("BCM4360 test.235: SKIPPING brcmf_chip_set_active (zero+verify-only run; test.230 baseline)\n");
				msleep(1000);
				pr_emerg("BCM4360 test.235: 1000 ms dwell done (no fw activation); proceeding to BM-clear + release\n");
			} else if (bcm4360_test238_ultra_dwells) {
				/* test.239 + test.240: poll helper. test.239 reads
				 * TCM[ramsize-4]; test.240 wide_poll additionally
				 * reads 15 dwords starting at ramsize-64 (so the
				 * full tail-TCM window ramsize-64..ramsize-4 is
				 * covered). Zero cost when both flags off. */
#define BCM4360_T239_POLL(ms_tag) do { \
					if (bcm4360_test239_poll_sharedram) { \
						u32 _v = brcmf_pcie_read_ram32(devinfo, \
							devinfo->ci->ramsize - 4); \
						pr_emerg("BCM4360 test.239: t+" ms_tag " sharedram_ptr=0x%08x\n", \
							 _v); \
						if (bcm4360_test240_wide_poll) { \
							u32 _w[15]; \
							int _i; \
							for (_i = 0; _i < 15; _i++) \
								_w[_i] = brcmf_pcie_read_ram32(devinfo, \
									devinfo->ci->ramsize - 64 + _i * 4); \
							pr_emerg("BCM4360 test.240: t+" ms_tag \
								 " tail-TCM[-64..-8] = " \
								 "%08x %08x %08x %08x %08x %08x %08x %08x " \
								 "%08x %08x %08x %08x %08x %08x %08x\n", \
								 _w[0], _w[1], _w[2], _w[3], \
								 _w[4], _w[5], _w[6], _w[7], \
								 _w[8], _w[9], _w[10], _w[11], \
								 _w[12], _w[13], _w[14]); \
						} \
					} \
					if (bcm4360_test247_preplace_shared) { \
						u32 _s247[18]; \
						int _j247; \
						for (_j247 = 0; _j247 < 18; _j247++) \
							_s247[_j247] = brcmf_pcie_read_ram32(devinfo, \
								0x80000 + _j247 * 4); \
						pr_emerg("BCM4360 test.247: t+" ms_tag \
							 " struct[0x80000..0x80047] = " \
							 "%08x %08x %08x %08x %08x %08x %08x %08x %08x " \
							 "%08x %08x %08x %08x %08x %08x %08x %08x %08x\n", \
							 _s247[0], _s247[1], _s247[2], _s247[3], \
							 _s247[4], _s247[5], _s247[6], _s247[7], \
							 _s247[8], _s247[9], _s247[10], _s247[11], \
							 _s247[12], _s247[13], _s247[14], _s247[15], \
							 _s247[16], _s247[17]); \
					} \
					if (bcm4360_test249_console_dump || \
					    bcm4360_test250_console_gap || \
					    bcm4360_test251_console_ext || \
					    bcm4360_test252_phy_data || \
					    bcm4360_test253_shared_obj || \
					    bcm4360_test255_sched_probe || \
					    bcm4360_test255_sched_late || \
					    bcm4360_test255_struct_decode || \
					    bcm4360_test256_sched_walk || \
					    bcm4360_test256_sched_walk_early || \
					    bcm4360_test258_enable_irq || \
					    bcm4360_test259_safe_enable_irq || \
					    bcm4360_test260_mask_only || \
					    bcm4360_test260_doorbell_only || \
					    bcm4360_test262_msi_poll_only || \
					    bcm4360_test263_short || \
					    bcm4360_test264_noloop || \
					    bcm4360_test265_short_noloop || \
					    bcm4360_test266_ultra_short_noloop || \
					    bcm4360_test267_no_msleep) { \
						u32 _ctr249 = brcmf_pcie_read_ram32(devinfo, \
							0x9d000); \
						pr_emerg("BCM4360 test.249: t+" ms_tag \
							 " ctr[0x9d000]=0x%08x\n", _ctr249); \
					} \
				} while (0)

				/* BCM4360 test.242: MAILBOXMASK sentinel round-trip
				 * at a dwell point. Gated on
				 * bcm4360_test242_writeverify_postactive so test.239/
				 * test.240 runs aren't perturbed. Writes 0xDEADBEEF,
				 * reads back, writes 0 to restore, reads back. All
				 * three readbacks logged. Safe: MAILBOXMASK=0 is the
				 * state brcmf_pcie_intr_disable leaves the register
				 * in during cleanup (pcie.c:1333). */
#define BCM4360_T242_WRITEVERIFY(ms_tag) do { \
					if (bcm4360_test242_writeverify_postactive) { \
						const u32 _mbm = devinfo->reginfo->mailboxmask; \
						u32 _base, _after_sent, _after_clear; \
						int _sent_match, _clear_match; \
						_base = brcmf_pcie_read_reg32(devinfo, _mbm); \
						brcmf_pcie_write_reg32(devinfo, _mbm, 0xDEADBEEF); \
						_after_sent = brcmf_pcie_read_reg32(devinfo, _mbm); \
						brcmf_pcie_write_reg32(devinfo, _mbm, 0); \
						_after_clear = brcmf_pcie_read_reg32(devinfo, _mbm); \
						_sent_match = (_after_sent == 0xDEADBEEF); \
						_clear_match = (_after_clear == 0); \
						pr_emerg("BCM4360 test.242: t+" ms_tag " MAILBOXMASK (BAR0+0x%x) baseline=0x%08x sent=0x%08x (match=%d) cleared=0x%08x (match=%d) RESULT %s\n", \
							 _mbm, _base, _after_sent, _sent_match, _after_clear, _clear_match, \
							 (_sent_match && _clear_match) ? "PASS" : "FAIL"); \
					} \
				} while (0)

/* BCM4360 test.243: MBM round-trip under explicit select_core(PCIE2)
 * + BAR2 TCM[0x90000] round-trip. See param description above for
 * full rationale. Uses invert-and-restore sentinel so PASS/FAIL is
 * informative regardless of baseline value, and logs BAR0_WINDOW
 * config-space value before and after the select so the window is
 * evidence, not assumption. Restores the prior BAR0_WINDOW after
 * the round-trip so downstream ladder state is unperturbed. */
#define BCM4360_T243_WRITEVERIFY(ms_tag) do { \
					if (bcm4360_test243_writeverify_v2) { \
						const u32 _mbm = devinfo->reginfo->mailboxmask; \
						u32 _win_before = 0, _win_after = 0; \
						u32 _base, _after_sent, _after_restore; \
						int _sent_match, _restore_match; \
						u32 _t = 0x90000; \
						u32 _b2_base, _b2_sent, _b2_restore; \
						int _b2_sent_match, _b2_restore_match; \
						pci_read_config_dword(devinfo->pdev, \
							BRCMF_PCIE_BAR0_WINDOW, &_win_before); \
						brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2); \
						pci_read_config_dword(devinfo->pdev, \
							BRCMF_PCIE_BAR0_WINDOW, &_win_after); \
						pr_emerg("BCM4360 test.243: t+" ms_tag " BAR0_WINDOW before=0x%08x after=0x%08x (expect PCIE2 core base)\n", \
							 _win_before, _win_after); \
						_base = brcmf_pcie_read_reg32(devinfo, _mbm); \
						brcmf_pcie_write_reg32(devinfo, _mbm, ~_base); \
						_after_sent = brcmf_pcie_read_reg32(devinfo, _mbm); \
						brcmf_pcie_write_reg32(devinfo, _mbm, _base); \
						_after_restore = brcmf_pcie_read_reg32(devinfo, _mbm); \
						_sent_match = (_after_sent == ~_base); \
						_restore_match = (_after_restore == _base); \
						pr_emerg("BCM4360 test.243: t+" ms_tag " MBM (BAR0+0x%x @window=0x%08x) baseline=0x%08x sent=0x%08x (match=%d) restored=0x%08x (match=%d) RESULT %s\n", \
							 _mbm, _win_after, _base, _after_sent, _sent_match, _after_restore, _restore_match, \
							 (_sent_match && _restore_match) ? "PASS" : "FAIL"); \
						/* Restore prior BAR0_WINDOW so ladder downstream is unperturbed. */ \
						pci_write_config_dword(devinfo->pdev, \
							BRCMF_PCIE_BAR0_WINDOW, _win_before); \
						/* BAR2 TCM[0x90000] round-trip — independent axis (BAR2 does not use BAR0_WINDOW). */ \
						_b2_base = brcmf_pcie_read_ram32(devinfo, _t); \
						brcmf_pcie_write_ram32(devinfo, _t, ~_b2_base); \
						_b2_sent = brcmf_pcie_read_ram32(devinfo, _t); \
						brcmf_pcie_write_ram32(devinfo, _t, _b2_base); \
						_b2_restore = brcmf_pcie_read_ram32(devinfo, _t); \
						_b2_sent_match = (_b2_sent == ~_b2_base); \
						_b2_restore_match = (_b2_restore == _b2_base); \
						pr_emerg("BCM4360 test.243: t+" ms_tag " BAR2 TCM[0x%05x] baseline=0x%08x sent=0x%08x (match=%d) restored=0x%08x (match=%d) RESULT %s\n", \
							 _t, _b2_base, _b2_sent, _b2_sent_match, _b2_restore, _b2_restore_match, \
							 (_b2_sent_match && _b2_restore_match) ? "PASS" : "FAIL"); \
					} \
				} while (0)

				/* BCM4360 test.276: pre-ARM-release shared_info write.
				 * Placement: AFTER FORCEHT, IMMEDIATELY BEFORE
				 * brcmf_chip_set_active, so nothing else in Phase 5's
				 * probe path can touch the region between our write
				 * and ARM release. See phase6/t276_shared_info_design.md. */
				if (bcm4360_test276_shared_info &&
				    devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
					u32 t276_base = devinfo->ci->ramsize -
							BCM4360_T276_SHARED_INFO_OFFSET;
					void *t276_buf = NULL;
					dma_addr_t t276_dma = 0;
					u32 t276_i;

					/* BCM4360 test.277: pre-shared_info-write dump of
					 * the Phase 4B observed pointer 0x9af88. Discriminates
					 * "struct pre-existed in fw image" vs "populated by
					 * fw during post-set_active init". */
					if (bcm4360_test277_console_decode) {
						u32 t277_struct[BCM4360_T277_STRUCT_DWORDS];
						u32 t277_j;

						for (t277_j = 0;
						     t277_j < BCM4360_T277_STRUCT_DWORDS;
						     t277_j++)
							t277_struct[t277_j] = brcmf_pcie_read_ram32(
								devinfo, 0x9af88 + t277_j * 4);
						pr_emerg("BCM4360 test.277: PRE-WRITE struct@0x9af88 buf_addr=0x%08x buf_size=0x%08x write_idx=0x%08x read_addr=0x%08x\n",
							 t277_struct[0], t277_struct[1],
							 t277_struct[2], t277_struct[3]);
					}

					t276_buf = dma_alloc_coherent(
						&devinfo->pdev->dev,
						BCM4360_T276_OLMSG_BUF_SIZE,
						&t276_dma, GFP_KERNEL);
					if (!t276_buf) {
						pr_emerg("BCM4360 test.276: dma_alloc_coherent FAILED; skipping shared_info write\n");
					} else {
						__le32 *p = (__le32 *)t276_buf;

						memset(t276_buf, 0,
						       BCM4360_T276_OLMSG_BUF_SIZE);
						/* olmsg ring header: ring0 (host->fw),
						 * ring1 (fw->host). Each {data_off,
						 * size, rd_ptr, wr_ptr}. */
						p[0] = cpu_to_le32(BCM4360_T276_OLMSG_HDR_SIZE);
						p[1] = cpu_to_le32(BCM4360_T276_OLMSG_RING_SIZE);
						p[2] = 0;
						p[3] = 0;
						p[4] = cpu_to_le32(BCM4360_T276_OLMSG_HDR_SIZE +
								   BCM4360_T276_OLMSG_RING_SIZE);
						p[5] = cpu_to_le32(BCM4360_T276_OLMSG_RING_SIZE);
						p[6] = 0;
						p[7] = 0;

						/* Zero shared_info TCM region before
						 * writing known fields — clears any
						 * prior content / fw trap state. */
						for (t276_i = 0;
						     t276_i < BCM4360_T276_SHARED_INFO_SIZE / 4;
						     t276_i++)
							brcmf_pcie_write_ram32(
								devinfo,
								t276_base + t276_i * 4,
								0);

						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_MAGIC_START,
							BCM4360_T276_MAGIC_START_VAL);
						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_DMA_LO,
							lower_32_bits(t276_dma));
						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_DMA_HI,
							upper_32_bits(t276_dma));
						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_BUF_SIZE,
							BCM4360_T276_OLMSG_BUF_SIZE);
						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_FW_INIT_DONE,
							0);
						brcmf_pcie_write_ram32(devinfo,
							t276_base + BCM4360_T276_SI_MAGIC_END,
							BCM4360_T276_MAGIC_END_VAL);

						pr_emerg("BCM4360 test.276: shared_info written at TCM[0x%05x] olmsg_dma=0x%llx size=%d\n",
							 t276_base,
							 (unsigned long long)t276_dma,
							 BCM4360_T276_OLMSG_BUF_SIZE);
						pr_emerg("BCM4360 test.276: readback magic_start=0x%08x (exp 0x%08x) dma_lo=0x%08x (exp 0x%08x) dma_hi=0x%08x (exp 0x%08x)\n",
							 brcmf_pcie_read_ram32(devinfo, t276_base),
							 BCM4360_T276_MAGIC_START_VAL,
							 brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_DMA_LO),
							 lower_32_bits(t276_dma),
							 brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_DMA_HI),
							 upper_32_bits(t276_dma));
						pr_emerg("BCM4360 test.276: readback buf_size=0x%08x (exp 0x%08x) fw_init_done=0x%08x (exp 0) magic_end=0x%08x (exp 0x%08x)\n",
							 brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_BUF_SIZE),
							 BCM4360_T276_OLMSG_BUF_SIZE,
							 brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_FW_INIT_DONE),
							 brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_MAGIC_END),
							 BCM4360_T276_MAGIC_END_VAL);

						devinfo->t276_olmsg_buf = t276_buf;
						devinfo->t276_olmsg_dma = t276_dma;
					}
				}

				pr_emerg("BCM4360 test.238: calling brcmf_chip_set_active resetintr=0x%08x (ultra-extended ladder t+120s)\n",
					 resetintr);
				mdelay(10);
				if (!brcmf_chip_set_active(devinfo->ci, resetintr))
					pr_emerg("BCM4360 test.238: brcmf_chip_set_active returned FALSE\n");
				else
					pr_emerg("BCM4360 test.238: brcmf_chip_set_active returned TRUE\n");

				/* BCM4360 test.276: 2 s post-ARM-release poll of
				 * shared_info response fields. Log on any change,
				 * continue for full 2 s (don't break on first
				 * signal — Phase 4B Test.28 showed BOTH a TCM
				 * update and mailbox signals). */
				if (bcm4360_test276_shared_info &&
				    devinfo->ci->chip == BRCM_CC_4360_CHIP_ID &&
				    devinfo->t276_olmsg_buf) {
					u32 t276_base = devinfo->ci->ramsize -
							BCM4360_T276_SHARED_INFO_OFFSET;
					u32 last_fw_status = 0xdeadbeef;
					u32 last_fw_init = 0xdeadbeef;
					u32 last_mbxint = 0xdeadbeef;
					u32 t276_i;

					pr_emerg("BCM4360 test.276: entering 2s poll post-set_active\n");
					for (t276_i = 0; t276_i < 200; t276_i++) {
						u32 fw_status = brcmf_pcie_read_ram32(
							devinfo,
							t276_base + BCM4360_T276_SI_FW_STATUS);
						u32 fw_init = brcmf_pcie_read_ram32(
							devinfo,
							t276_base + BCM4360_T276_SI_FW_INIT_DONE);
						u32 mbxint = brcmf_pcie_read_reg32(
							devinfo,
							BRCMF_PCIE_PCIE2REG_MAILBOXINT);

						if (fw_status != last_fw_status ||
						    fw_init != last_fw_init ||
						    mbxint != last_mbxint) {
							pr_emerg("BCM4360 test.276: t+%dms si[+0x010]=0x%08x fw_done=0x%08x mbxint=0x%08x\n",
								 t276_i * 10, fw_status,
								 fw_init, mbxint);
							last_fw_status = fw_status;
							last_fw_init = fw_init;
							last_mbxint = mbxint;
						}
						msleep(10);
					}
					pr_emerg("BCM4360 test.276: poll-end si[+0x010]=0x%08x fw_done=0x%08x mbxint=0x%08x\n",
						 brcmf_pcie_read_ram32(devinfo,
							t276_base + BCM4360_T276_SI_FW_STATUS),
						 brcmf_pcie_read_ram32(devinfo,
							t276_base + BCM4360_T276_SI_FW_INIT_DONE),
						 brcmf_pcie_read_reg32(devinfo,
							BRCMF_PCIE_PCIE2REG_MAILBOXINT));

					/* BCM4360 test.277: post-poll console decode.
					 * Re-read the pointer fw published at si[+0x010]
					 * (T276 observed 0x9af88 both at t+0 and t+2s),
					 * then dump the 4-dword struct there and — if
					 * buf_addr is a valid TCM address — dump 128 B of
					 * the buffer as ASCII-escaped text. */
					if (bcm4360_test277_console_decode) {
						u32 t277_ptr = brcmf_pcie_read_ram32(devinfo,
							t276_base + BCM4360_T276_SI_FW_STATUS);
						u32 t277_struct[BCM4360_T277_STRUCT_DWORDS];
						u32 t277_j;

						pr_emerg("BCM4360 test.277: POST-POLL struct-ptr from si[+0x010]=0x%08x\n",
							 t277_ptr);

						if (t277_ptr == 0 ||
						    t277_ptr >= devinfo->ci->ramsize) {
							pr_emerg("BCM4360 test.277: POST-POLL struct-ptr not a valid TCM address (ramsize=0x%x); skipping struct read\n",
								 devinfo->ci->ramsize);
						} else {
							for (t277_j = 0;
							     t277_j < BCM4360_T277_STRUCT_DWORDS;
							     t277_j++)
								t277_struct[t277_j] = brcmf_pcie_read_ram32(
									devinfo,
									t277_ptr + t277_j * 4);
							pr_emerg("BCM4360 test.277: POST-POLL struct@0x%08x buf_addr=0x%08x buf_size=0x%08x write_idx=0x%08x read_addr=0x%08x\n",
								 t277_ptr,
								 t277_struct[0],
								 t277_struct[1],
								 t277_struct[2],
								 t277_struct[3]);

							/* If buf_addr is a valid TCM address,
							 * dump 128 B of buffer content with
							 * ASCII-escape so trap/log text is
							 * readable without hex-decode. */
							if (t277_struct[0] > 0 &&
							    t277_struct[0] < devinfo->ci->ramsize) {
								u8 t277_buf[BCM4360_T277_BUFFER_DUMP_BYTES];
								u32 t277_dwords = BCM4360_T277_BUFFER_DUMP_BYTES / 4;
								u32 *t277_u32p = (u32 *)t277_buf;

								for (t277_j = 0;
								     t277_j < t277_dwords;
								     t277_j++)
									t277_u32p[t277_j] = brcmf_pcie_read_ram32(
										devinfo,
										t277_struct[0] + t277_j * 4);
								pr_emerg("BCM4360 test.277: buffer@0x%08x (first %u B) ASCII: %*pE\n",
									 t277_struct[0],
									 BCM4360_T277_BUFFER_DUMP_BYTES,
									 BCM4360_T277_BUFFER_DUMP_BYTES,
									 t277_buf);
								pr_emerg("BCM4360 test.277: buffer@0x%08x (first %u B) HEX:   %*ph\n",
									 t277_struct[0],
									 BCM4360_T277_BUFFER_DUMP_BYTES,
									 BCM4360_T277_BUFFER_DUMP_BYTES,
									 t277_buf);
							} else {
								pr_emerg("BCM4360 test.277: buf_addr 0x%08x not a valid TCM address; skipping buffer dump\n",
									 t277_struct[0]);
							}
						}
					}

					/* BCM4360 test.278: seed periodic delta dump
					 * with prev=0 so the FIRST call prints the full
					 * write_idx window captured at post-poll time.
					 * Subsequent per-stage calls in the dwell ladder
					 * print only deltas since this point. */
					if (bcm4360_test278_console_periodic &&
					    bcm4360_test277_console_decode) {
						u32 t278_ptr = brcmf_pcie_read_ram32(
							devinfo,
							t276_base + BCM4360_T276_SI_FW_STATUS);

						devinfo->t278_prev_write_idx = 0;
						bcm4360_t278_dump_console_delta(
							devinfo,
							"POST-POLL (full)",
							t278_ptr,
							&devinfo->t278_prev_write_idx);
					} else if (bcm4360_test278_console_periodic) {
						pr_emerg("BCM4360 test.278: requires bcm4360_test277_console_decode=1; skipping\n");
					}

					/* BCM4360 test.279: directed mailbox probe.
					 * Advisor-approved order: hypothesis (H2D_MBX_1)
					 * first, positive control (H2D_MBX_0) second.
					 * Between each write: 100 ms dwell + T278 delta
					 * dump (so new console content produced by fw's
					 * ISR→dispatch→printf chain is logged). Requires
					 * T276+T277+T278 for console observability. */
					if (bcm4360_test279_mbx_probe &&
					    bcm4360_test276_shared_info &&
					    bcm4360_test277_console_decode &&
					    bcm4360_test278_console_periodic) {
						u32 mask_pre;

						mask_pre = brcmf_pcie_read_reg32(devinfo,
							BRCMF_PCIE_PCIE2REG_MAILBOXMASK);
						pr_emerg("BCM4360 test.279: pre-probe MAILBOXMASK=0x%08x (0 = all fw ints masked)\n",
							 mask_pre);

						/* Probe 1: H2D_MAILBOX_1=1 (hypothesis: wakes fn@0x1146C) */
						pr_emerg("BCM4360 test.279: writing H2D_MAILBOX_1=1 (hypothesis — fn@0x1146C trigger?)\n");
						brcmf_pcie_write_reg32(devinfo,
							BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1,
							1);
						msleep(100);
						{
							u32 mbxint_post = brcmf_pcie_read_reg32(devinfo,
								BRCMF_PCIE_PCIE2REG_MAILBOXINT);
							u32 t279_ptr = brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_FW_STATUS);
							pr_emerg("BCM4360 test.279: post-H2D_MBX_1 MAILBOXINT=0x%08x (D2H mirror, non-zero = fw signalled)\n",
								 mbxint_post);
							bcm4360_t278_dump_console_delta(devinfo,
								"POST-H2D_MBX_1 (+100ms)",
								t279_ptr,
								&devinfo->t278_prev_write_idx);
						}

						/* Probe 2: H2D_MAILBOX_0=1 (positive control — pciedngl_isr) */
						pr_emerg("BCM4360 test.279: writing H2D_MAILBOX_0=1 (positive control — pciedngl_isr)\n");
						brcmf_pcie_write_reg32(devinfo,
							BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_0,
							1);
						msleep(100);
						{
							u32 mbxint_post = brcmf_pcie_read_reg32(devinfo,
								BRCMF_PCIE_PCIE2REG_MAILBOXINT);
							u32 t279_ptr = brcmf_pcie_read_ram32(devinfo,
								t276_base + BCM4360_T276_SI_FW_STATUS);
							pr_emerg("BCM4360 test.279: post-H2D_MBX_0 MAILBOXINT=0x%08x (D2H mirror, non-zero = fw signalled)\n",
								 mbxint_post);
							bcm4360_t278_dump_console_delta(devinfo,
								"POST-H2D_MBX_0 (+100ms)",
								t279_ptr,
								&devinfo->t278_prev_write_idx);
						}
					} else if (bcm4360_test279_mbx_probe) {
						pr_emerg("BCM4360 test.279: requires T276+T277+T278 all enabled; skipping\n");
					}
				}
				if (bcm4360_test268_early_scaffold) {
					struct pci_dev *_pdev268 = devinfo->pdev;
					int _prev_irq268 = _pdev268->irq;
					int _msi_ret268, _req_ret268;
					mdelay(100);
					pr_emerg("BCM4360 test.268 early: skipping dwell ladder; running scaffold NOW\n");
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret268 = pci_enable_msi(_pdev268);
					pr_emerg("BCM4360 test.268 early: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret268, _prev_irq268, _pdev268->irq);
					_req_ret268 = request_irq(_pdev268->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t268_early", devinfo);
					pr_emerg("BCM4360 test.268 early: request_irq ret=%d\n", _req_ret268);
					if (_req_ret268 == 0) {
						pr_emerg("BCM4360 test.268 early: SKIPPING msleep — immediate cleanup\n");
						pr_emerg("BCM4360 test.268 early: calling free_irq\n");
						free_irq(_pdev268->irq, devinfo);
						pr_emerg("BCM4360 test.268 early: free_irq returned\n");
					} else {
						pr_emerg("BCM4360 test.268 early: request_irq FAILED (%d)\n", _req_ret268);
					}
					if (_msi_ret268 == 0) {
						pr_emerg("BCM4360 test.268 early: calling pci_disable_msi\n");
						pci_disable_msi(_pdev268);
						pr_emerg("BCM4360 test.268 early: pci_disable_msi returned\n");
					}
					pr_emerg("BCM4360 test.268 early: scaffold complete; jumping to end of ultra-dwells branch\n");
					goto ultra_dwells_done;
				}
				mdelay(100);
				pr_emerg("BCM4360 test.238: t+100ms dwell\n");
				BCM4360_T242_WRITEVERIFY("100ms");
				BCM4360_T243_WRITEVERIFY("100ms");
				BCM4360_T239_POLL("100ms");
				BCM4360_T255_SCHED_PROBE_COND(bcm4360_test255_sched_probe, "t+100ms");
				BCM4360_T256_SCHED_WALK_COND(bcm4360_test256_sched_walk_early, "t+100ms");
				mdelay(200);
				pr_emerg("BCM4360 test.238: t+300ms dwell\n");
				BCM4360_T239_POLL("300ms");
				mdelay(200);
				pr_emerg("BCM4360 test.238: t+500ms dwell\n");
				BCM4360_T239_POLL("500ms");
				BCM4360_T278_HOOK("t+500ms");
				mdelay(200);
				pr_emerg("BCM4360 test.238: t+700ms dwell\n");
				BCM4360_T239_POLL("700ms");
				mdelay(300);
				pr_emerg("BCM4360 test.238: t+1000ms dwell\n");
				BCM4360_T239_POLL("1000ms");
				msleep(500);
				pr_emerg("BCM4360 test.238: t+1500ms dwell\n");
				BCM4360_T239_POLL("1500ms");
				msleep(500);
				pr_emerg("BCM4360 test.238: t+2000ms dwell\n");
				BCM4360_T242_WRITEVERIFY("2000ms");
				BCM4360_T243_WRITEVERIFY("2000ms");
				if (bcm4360_test240_ring_h2d_db1) {
					u32 _rb;
					pr_emerg("BCM4360 test.240: ringing H2D_MAILBOX_1 (BAR0+0x%x)=1 at t+2000ms\n",
						 BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1);
					brcmf_pcie_write_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1, 1);
					_rb = brcmf_pcie_read_reg32(devinfo,
						BRCMF_PCIE_PCIE2REG_H2D_MAILBOX_1);
					pr_emerg("BCM4360 test.240: H2D_MAILBOX_1 ring done; readback=0x%08x\n",
						 _rb);
				}
				BCM4360_T239_POLL("2000ms");
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+3000ms dwell\n");
				BCM4360_T239_POLL("3000ms");
				msleep(2000);
				pr_emerg("BCM4360 test.238: t+5000ms dwell\n");
				BCM4360_T278_HOOK("t+5s");
				BCM4360_T239_POLL("5000ms");
				msleep(5000);
				pr_emerg("BCM4360 test.238: t+10000ms dwell\n");
				BCM4360_T239_POLL("10000ms");
				msleep(5000);
				pr_emerg("BCM4360 test.238: t+15000ms dwell\n");
				BCM4360_T239_POLL("15000ms");
				msleep(5000);
				pr_emerg("BCM4360 test.238: t+20000ms dwell\n");
				BCM4360_T239_POLL("20000ms");
				msleep(5000);
				pr_emerg("BCM4360 test.238: t+25000ms dwell\n");
				BCM4360_T239_POLL("25000ms");
				/* Fine-grain through the suspect [t+25s, t+30s] window. */
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+26000ms dwell\n");
				BCM4360_T239_POLL("26000ms");
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+27000ms dwell\n");
				BCM4360_T239_POLL("27000ms");
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+28000ms dwell\n");
				BCM4360_T239_POLL("28000ms");
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+29000ms dwell\n");
				BCM4360_T239_POLL("29000ms");
				msleep(1000);
				pr_emerg("BCM4360 test.238: t+30000ms dwell\n");
				BCM4360_T278_HOOK("t+30s");
				BCM4360_T239_POLL("30000ms");
				/* Extend past t+30s to distinguish fw-timeout from late-wedge. */
				msleep(5000);
				pr_emerg("BCM4360 test.238: t+35000ms dwell\n");
				BCM4360_T239_POLL("35000ms");
				msleep(10000);
				pr_emerg("BCM4360 test.238: t+45000ms dwell\n");
				BCM4360_T239_POLL("45000ms");
				msleep(15000);
				pr_emerg("BCM4360 test.238: t+60000ms dwell\n");
				BCM4360_T239_POLL("60000ms");
				BCM4360_T249_CONSOLE_WINDOW("t+60000ms");
				BCM4360_T250_GAP_WINDOW("t+60000ms");
				BCM4360_T251_RING_EXT("t+60000ms");
				BCM4360_T252_DATA_PROBE("t+60000ms");
				BCM4360_T253_SHARED_PROBE("t+60000ms");
				BCM4360_T255_STRUCT_DECODE("t+60000ms");
				BCM4360_T256_SCHED_WALK("t+60000ms");
				if (bcm4360_test269_early_exit) {
					pr_emerg("BCM4360 test.269: early-exit at t+60000ms — skipping t+90s/t+120s/scaffolds, jumping to ultra_dwells_done\n");
					goto ultra_dwells_done;
				}
				msleep(30000);
				pr_emerg("BCM4360 test.238: t+90000ms dwell\n");
				BCM4360_T278_HOOK("t+90s");
				BCM4360_T239_POLL("90000ms");
				BCM4360_T248_WIDESCAN("t+90000ms");
				BCM4360_T249_ASSERT_WINDOW("t+90000ms");
				BCM4360_T255_SCHED_PROBE_COND(bcm4360_test255_sched_late, "t+90000ms");
				msleep(30000);
				pr_emerg("BCM4360 test.238: t+120000ms dwell done (proceeding to BM-clear + release)\n");
				BCM4360_T239_POLL("120000ms");
				BCM4360_T258_BUFPTR_PROBE("t+120000ms");
				if (bcm4360_test258_enable_irq) {
					pr_emerg("BCM4360 test.258: triggering intr_enable + hostready at t+120s\n");
					brcmf_pcie_intr_enable(devinfo);
					brcmf_pcie_hostready(devinfo);
					pr_emerg("BCM4360 test.258: intr_enable + hostready done; sleeping 5s\n");
					msleep(5000);
					pr_emerg("BCM4360 test.238: t+125000ms post-enable dwell\n");
					BCM4360_T239_POLL("125000ms");
					BCM4360_T258_BUFPTR_PROBE("t+125000ms");
				}
				if (bcm4360_test259_safe_enable_irq) {
					struct pci_dev *_pdev259 = devinfo->pdev;
					int _prev_irq = _pdev259->irq;
					int _msi_ret, _req_ret;
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret = pci_enable_msi(_pdev259);
					pr_emerg("BCM4360 test.259: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret, _prev_irq, _pdev259->irq);
					_req_ret = request_irq(_pdev259->irq,
							       bcm4360_t259_safe_handler,
							       IRQF_SHARED, "t259_safe", devinfo);
					pr_emerg("BCM4360 test.259: request_irq ret=%d\n", _req_ret);
					if (_req_ret == 0) {
						pr_emerg("BCM4360 test.259: triggering intr_enable + hostready at t+120s (handler registered)\n");
						brcmf_pcie_intr_enable(devinfo);
						brcmf_pcie_hostready(devinfo);
						pr_emerg("BCM4360 test.259: intr_enable + hostready done; sleeping 5s\n");
						msleep(5000);
						pr_emerg("BCM4360 test.259: post-wait irq_count=%d last_mailboxint=0x%08x\n",
							 atomic_read(&bcm4360_t259_irq_count),
							 atomic_read(&bcm4360_t259_last_mailboxint));
						pr_emerg("BCM4360 test.238: t+125000ms post-enable dwell\n");
						BCM4360_T239_POLL("125000ms");
						BCM4360_T258_BUFPTR_PROBE("t+125000ms");
						brcmf_pcie_intr_disable(devinfo);
						free_irq(_pdev259->irq, devinfo);
					} else {
						pr_emerg("BCM4360 test.259: request_irq FAILED (%d), skipping enable sequence\n",
							 _req_ret);
					}
					if (_msi_ret == 0)
						pci_disable_msi(_pdev259);
				}
				if (bcm4360_test260_mask_only ||
				    bcm4360_test260_doorbell_only ||
				    bcm4360_test262_msi_poll_only ||
				    bcm4360_test263_short) {
					struct pci_dev *_pdev260 = devinfo->pdev;
					int _prev_irq260 = _pdev260->irq;
					int _msi_ret260, _req_ret260;
					int _i260;
					int _max_iter = bcm4360_test263_short ? 10 : 50;
					const char *_tnum = bcm4360_test263_short ? "263" :
						(bcm4360_test262_msi_poll_only ? "262" : "260");
					const char *_variant = bcm4360_test263_short ? "short" :
						(bcm4360_test260_mask_only ? "mask_only" :
						 (bcm4360_test260_doorbell_only ?
						  "doorbell_only" : "msi_poll_only"));
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret260 = pci_enable_msi(_pdev260);
					pr_emerg("BCM4360 test.%s %s: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _tnum, _variant, _msi_ret260, _prev_irq260, _pdev260->irq);
					_req_ret260 = request_irq(_pdev260->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t260_safe", devinfo);
					pr_emerg("BCM4360 test.%s %s: request_irq ret=%d\n",
						 _tnum, _variant, _req_ret260);
					if (_req_ret260 == 0) {
						if (bcm4360_test260_mask_only) {
							pr_emerg("BCM4360 test.260 mask_only: calling intr_enable (MAILBOXMASK write) — NO doorbell\n");
							brcmf_pcie_intr_enable(devinfo);
							pr_emerg("BCM4360 test.260 mask_only: intr_enable done; starting 50×100ms timeline\n");
						} else if (bcm4360_test260_doorbell_only) {
							pr_emerg("BCM4360 test.260 doorbell_only: calling hostready (H2D_MAILBOX_1 write) — NO mask\n");
							brcmf_pcie_hostready(devinfo);
							pr_emerg("BCM4360 test.260 doorbell_only: hostready done; starting 50×100ms timeline\n");
						} else if (bcm4360_test263_short) {
							pr_emerg("BCM4360 test.263 short: skipping intr_enable + hostready; starting 10×100ms timeline (1s loop)\n");
						} else {
							pr_emerg("BCM4360 test.262 msi_poll_only: skipping intr_enable + hostready; starting 50×100ms timeline\n");
						}
						for (_i260 = 0; _i260 < _max_iter; _i260++) {
							u32 _mbi = brcmf_pcie_read_reg32(devinfo, devinfo->reginfo->mailboxint);
							u32 _bp = brcmf_pcie_read_ram32(devinfo, 0x9CC5C);
							msleep(100);
							pr_emerg("BCM4360 test.%s %s: t+%dms mailboxint=0x%08x buf_ptr=0x%08x irq_count=%d\n",
								 _tnum, _variant,
								 120100 + _i260 * 100,
								 _mbi, _bp,
								 atomic_read(&bcm4360_t259_irq_count));
						}
						pr_emerg("BCM4360 test.%s %s: timeline done; final irq_count=%d last_mailboxint=0x%08x\n",
							 _tnum, _variant,
							 atomic_read(&bcm4360_t259_irq_count),
							 atomic_read(&bcm4360_t259_last_mailboxint));
						if (bcm4360_test260_mask_only)
							brcmf_pcie_intr_disable(devinfo);
						pr_emerg("BCM4360 test.%s %s: calling free_irq\n", _tnum, _variant);
						free_irq(_pdev260->irq, devinfo);
						pr_emerg("BCM4360 test.%s %s: free_irq returned\n", _tnum, _variant);
					} else {
						pr_emerg("BCM4360 test.%s %s: request_irq FAILED (%d), skipping enable sequence\n",
							 _tnum, _variant, _req_ret260);
					}
					if (_msi_ret260 == 0) {
						pr_emerg("BCM4360 test.%s %s: calling pci_disable_msi\n", _tnum, _variant);
						pci_disable_msi(_pdev260);
						pr_emerg("BCM4360 test.%s %s: pci_disable_msi returned\n", _tnum, _variant);
					}
				}
				if (bcm4360_test264_noloop) {
					struct pci_dev *_pdev264 = devinfo->pdev;
					int _prev_irq264 = _pdev264->irq;
					int _msi_ret264, _req_ret264;
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret264 = pci_enable_msi(_pdev264);
					pr_emerg("BCM4360 test.264 noloop: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret264, _prev_irq264, _pdev264->irq);
					_req_ret264 = request_irq(_pdev264->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t264_noloop", devinfo);
					pr_emerg("BCM4360 test.264 noloop: request_irq ret=%d\n", _req_ret264);
					if (_req_ret264 == 0) {
						pr_emerg("BCM4360 test.264 noloop: entering msleep(2000) — no loop, no MMIO\n");
						msleep(2000);
						pr_emerg("BCM4360 test.264 noloop: msleep done; irq_count=%d last_mailboxint=0x%08x\n",
							 atomic_read(&bcm4360_t259_irq_count),
							 atomic_read(&bcm4360_t259_last_mailboxint));
						pr_emerg("BCM4360 test.264 noloop: calling free_irq\n");
						free_irq(_pdev264->irq, devinfo);
						pr_emerg("BCM4360 test.264 noloop: free_irq returned\n");
					} else {
						pr_emerg("BCM4360 test.264 noloop: request_irq FAILED (%d), skipping msleep\n",
							 _req_ret264);
					}
					if (_msi_ret264 == 0) {
						pr_emerg("BCM4360 test.264 noloop: calling pci_disable_msi\n");
						pci_disable_msi(_pdev264);
						pr_emerg("BCM4360 test.264 noloop: pci_disable_msi returned\n");
					}
				}
				if (bcm4360_test265_short_noloop) {
					struct pci_dev *_pdev265 = devinfo->pdev;
					int _prev_irq265 = _pdev265->irq;
					int _msi_ret265, _req_ret265;
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret265 = pci_enable_msi(_pdev265);
					pr_emerg("BCM4360 test.265 short_noloop: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret265, _prev_irq265, _pdev265->irq);
					_req_ret265 = request_irq(_pdev265->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t265_short", devinfo);
					pr_emerg("BCM4360 test.265 short_noloop: request_irq ret=%d\n", _req_ret265);
					if (_req_ret265 == 0) {
						pr_emerg("BCM4360 test.265 short_noloop: entering msleep(500) — no loop, no MMIO\n");
						msleep(500);
						pr_emerg("BCM4360 test.265 short_noloop: msleep done; irq_count=%d last_mailboxint=0x%08x\n",
							 atomic_read(&bcm4360_t259_irq_count),
							 atomic_read(&bcm4360_t259_last_mailboxint));
						pr_emerg("BCM4360 test.265 short_noloop: calling free_irq\n");
						free_irq(_pdev265->irq, devinfo);
						pr_emerg("BCM4360 test.265 short_noloop: free_irq returned\n");
					} else {
						pr_emerg("BCM4360 test.265 short_noloop: request_irq FAILED (%d), skipping msleep\n",
							 _req_ret265);
					}
					if (_msi_ret265 == 0) {
						pr_emerg("BCM4360 test.265 short_noloop: calling pci_disable_msi\n");
						pci_disable_msi(_pdev265);
						pr_emerg("BCM4360 test.265 short_noloop: pci_disable_msi returned\n");
					}
				}
				if (bcm4360_test266_ultra_short_noloop) {
					struct pci_dev *_pdev266 = devinfo->pdev;
					int _prev_irq266 = _pdev266->irq;
					int _msi_ret266, _req_ret266;
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret266 = pci_enable_msi(_pdev266);
					pr_emerg("BCM4360 test.266 ultra_short: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret266, _prev_irq266, _pdev266->irq);
					_req_ret266 = request_irq(_pdev266->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t266_ultra", devinfo);
					pr_emerg("BCM4360 test.266 ultra_short: request_irq ret=%d\n", _req_ret266);
					if (_req_ret266 == 0) {
						pr_emerg("BCM4360 test.266 ultra_short: entering msleep(50) — no loop, no MMIO\n");
						msleep(50);
						pr_emerg("BCM4360 test.266 ultra_short: msleep done; irq_count=%d last_mailboxint=0x%08x\n",
							 atomic_read(&bcm4360_t259_irq_count),
							 atomic_read(&bcm4360_t259_last_mailboxint));
						pr_emerg("BCM4360 test.266 ultra_short: calling free_irq\n");
						free_irq(_pdev266->irq, devinfo);
						pr_emerg("BCM4360 test.266 ultra_short: free_irq returned\n");
					} else {
						pr_emerg("BCM4360 test.266 ultra_short: request_irq FAILED (%d), skipping msleep\n",
							 _req_ret266);
					}
					if (_msi_ret266 == 0) {
						pr_emerg("BCM4360 test.266 ultra_short: calling pci_disable_msi\n");
						pci_disable_msi(_pdev266);
						pr_emerg("BCM4360 test.266 ultra_short: pci_disable_msi returned\n");
					}
				}
				if (bcm4360_test267_no_msleep) {
					struct pci_dev *_pdev267 = devinfo->pdev;
					int _prev_irq267 = _pdev267->irq;
					int _msi_ret267, _req_ret267;
					atomic_set(&bcm4360_t259_irq_count, 0);
					atomic_set(&bcm4360_t259_last_mailboxint, 0);
					_msi_ret267 = pci_enable_msi(_pdev267);
					pr_emerg("BCM4360 test.267 no_msleep: pci_enable_msi=%d prev_irq=%d new_irq=%d\n",
						 _msi_ret267, _prev_irq267, _pdev267->irq);
					_req_ret267 = request_irq(_pdev267->irq,
								  bcm4360_t259_safe_handler,
								  IRQF_SHARED, "t267_nosleep", devinfo);
					pr_emerg("BCM4360 test.267 no_msleep: request_irq ret=%d\n", _req_ret267);
					if (_req_ret267 == 0) {
						pr_emerg("BCM4360 test.267 no_msleep: SKIPPING msleep — immediate cleanup\n");
						pr_emerg("BCM4360 test.267 no_msleep: calling free_irq\n");
						free_irq(_pdev267->irq, devinfo);
						pr_emerg("BCM4360 test.267 no_msleep: free_irq returned\n");
					} else {
						pr_emerg("BCM4360 test.267 no_msleep: request_irq FAILED (%d)\n",
							 _req_ret267);
					}
					if (_msi_ret267 == 0) {
						pr_emerg("BCM4360 test.267 no_msleep: calling pci_disable_msi\n");
						pci_disable_msi(_pdev267);
						pr_emerg("BCM4360 test.267 no_msleep: pci_disable_msi returned\n");
					}
				}
				ultra_dwells_done: ;
#undef BCM4360_T239_POLL
			} else if (bcm4360_test237_extended_dwells) {
				pr_emerg("BCM4360 test.237: calling brcmf_chip_set_active resetintr=0x%08x (extended-dwell ladder)\n",
					 resetintr);
				mdelay(10);
				if (!brcmf_chip_set_active(devinfo->ci, resetintr))
					pr_emerg("BCM4360 test.237: brcmf_chip_set_active returned FALSE\n");
				else
					pr_emerg("BCM4360 test.237: brcmf_chip_set_active returned TRUE\n");
				mdelay(100);
				pr_emerg("BCM4360 test.237: t+100ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.237: t+300ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.237: t+500ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.237: t+700ms dwell\n");
				mdelay(300);
				pr_emerg("BCM4360 test.237: t+1000ms dwell\n");
				msleep(500);
				pr_emerg("BCM4360 test.237: t+1500ms dwell\n");
				msleep(500);
				pr_emerg("BCM4360 test.237: t+2000ms dwell\n");
				msleep(1000);
				pr_emerg("BCM4360 test.237: t+3000ms dwell\n");
				msleep(2000);
				pr_emerg("BCM4360 test.237: t+5000ms dwell\n");
				msleep(5000);
				pr_emerg("BCM4360 test.237: t+10000ms dwell\n");
				msleep(5000);
				pr_emerg("BCM4360 test.237: t+15000ms dwell\n");
				msleep(5000);
				pr_emerg("BCM4360 test.237: t+20000ms dwell\n");
				msleep(5000);
				pr_emerg("BCM4360 test.237: t+25000ms dwell\n");
				msleep(5000);
				pr_emerg("BCM4360 test.237: t+30000ms dwell done (proceeding to BM-clear + release)\n");
			} else {
				pr_emerg("BCM4360 test.234: calling brcmf_chip_set_active resetintr=0x%08x (after zero-upper-TCM)\n",
					 resetintr);
				mdelay(10);
				if (!brcmf_chip_set_active(devinfo->ci, resetintr))
					pr_emerg("BCM4360 test.234: brcmf_chip_set_active returned FALSE\n");
				else
					pr_emerg("BCM4360 test.234: brcmf_chip_set_active returned TRUE\n");
				mdelay(100);
				pr_emerg("BCM4360 test.234: t+100ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.234: t+300ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.234: t+500ms dwell\n");
				mdelay(200);
				pr_emerg("BCM4360 test.234: t+700ms dwell\n");
				mdelay(300);
				pr_emerg("BCM4360 test.234: t+1000ms dwell done (proceeding to BM-clear + release)\n");
			}
#if 0
			mdelay(20);
			brcmf_pcie_probe_armcr4_state(devinfo,
						      "post-set-active-20ms");
			brcmf_pcie_probe_d11_state(devinfo,
						   "post-set-active-20ms");
			brcmf_pcie_probe_d11_clkctlst(devinfo,
						      "post-set-active-20ms");
			mdelay(80);	/* total 100 ms dwell after release */
			brcmf_pcie_probe_armcr4_state(devinfo,
						      "post-set-active-100ms");
			brcmf_pcie_probe_d11_state(devinfo,
						   "post-set-active-100ms");
			brcmf_pcie_probe_d11_clkctlst(devinfo,
						      "post-set-active-100ms");

			/* test.188: Two-tier fine-grain sampling BEFORE the
			 * coarse dwell grid.  Previous layout (tests 184–187)
			 * had no activity at 500/1500/3000 ms, so those samples
			 * are dropped.  Tiers now run at their intended windows:
			 *   tier-1: ~100-150 ms (10 × 5 ms) -- catch early fault
			 *   tier-2: ~150-1650 ms (30 × 50 ms) -- catch mid-range
			 *   dwell 3000 ms: late persistence check
			 *
			 * Timing note: 100 ms comes from 20+30+20+80+20 ms of
			 * set_active machinery before tier-1 starts.
			 */

			/* Tier 1: 5 ms granularity (~100-150 ms post-set_active) */
			pr_emerg("BCM4360 test.188: tier-1 fine-grain ~100-150 ms (10 × 5 ms)\n");
			for (i = 0; i < 10; i++) {
				u32 k;
				mdelay(5);
				brcmf_pcie_probe_armcr4_state(devinfo, "tier1");
				brcmf_pcie_probe_d11_state(devinfo, "tier1");
				brcmf_pcie_probe_d11_clkctlst(devinfo, "tier1");

				/* Subset of fw-integrity region every other
				 * sample (16 of 256 points) */
				if (fw->size >= 1024 && fw_sample_offsets &&
				    (i % 2 == 0)) {
					for (k = 0; k < 16; k++) {
						u32 idx = k * 16;
						if (idx >= nr_fw_samples) break;
						u32 offset = fw_sample_offsets[idx];
						u32 val = brcmf_pcie_read_ram32(devinfo, offset);
						u32 fw_val = get_unaligned_le32(fw->data + offset);
						pr_emerg("BCM4360 test.188: tier1-t+%ums fw-sample[0x%05x]=0x%08x vs 0x%08x %s\n",
							100 + (i+1)*5, offset, val, fw_val,
							val == fw_val ? "MATCH" : "MISMATCH");
					}
				}
			}

			/* Tier 2: 50 ms granularity (~150-1650 ms post-set_active) */
			pr_emerg("BCM4360 test.188: tier-2 fine-grain ~150-1650 ms (30 × 50 ms)\n");
			for (i = 0; i < 30; i++) {
				mdelay(50);
				brcmf_pcie_probe_armcr4_state(devinfo, "tier2");
				brcmf_pcie_probe_d11_state(devinfo, "tier2");
				brcmf_pcie_probe_d11_clkctlst(devinfo, "tier2");

				/* Minimal fw sampling during tier 2
				 * (first sample only, every 5th) */
				if (fw->size >= 1024 && fw_sample_offsets &&
				    (i % 5 == 0)) {
					u32 offset = fw_sample_offsets[0];
					u32 val = brcmf_pcie_read_ram32(devinfo, offset);
					u32 fw_val = get_unaligned_le32(fw->data + offset);
					pr_emerg("BCM4360 test.188: tier2-t+%ums fw-sample[0x%05x]=0x%08x vs 0x%08x %s\n",
						150 + i*50, offset, val, fw_val,
						val == fw_val ? "MATCH" : "MISMATCH");
				}
			}

			/* test.188: extended post-release observation.
			 * Re-read TCM[0x0..0x1c] and the NVRAM marker at each
			 * dwell stage and diff against the pre-release snapshot
			 * to detect firmware-originated writes.
			 */
			for (d = 0; d < ARRAY_SIZE(dwell_labels_ms); d++) {
				u32 marker_now;
				char tag[32];

				msleep(dwell_increments_ms[d]);
				snprintf(tag, sizeof(tag),
					 "post-set-active-%ums",
					 dwell_labels_ms[d]);
				brcmf_pcie_probe_armcr4_state(devinfo, tag);
				brcmf_pcie_probe_d11_state(devinfo, tag);
				brcmf_pcie_probe_d11_clkctlst(devinfo, tag);

				marker_now = brcmf_pcie_read_ram32(devinfo,
						devinfo->ci->ramsize - 4);
				pr_emerg("BCM4360 test.188: dwell-%ums NVRAM marker=0x%08x (was 0x%08x) %s\n",
					 dwell_labels_ms[d], marker_now,
					 pre_marker,
					 marker_now == pre_marker ?
						"UNCHANGED" : "CHANGED");

				for (j = 0; j < 8; j++) {
					u32 offset = j * 4;
					u32 val = brcmf_pcie_read_ram32(devinfo,
									offset);

					pr_emerg("BCM4360 test.188: dwell-%ums TCM[0x%04x]=0x%08x (was 0x%08x) %s\n",
						 dwell_labels_ms[d], offset,
						 val, pre_tcm[j],
						 val == pre_tcm[j] ?
							"UNCHANGED" :
							"CHANGED");
				}

				/* test.196: wide-TCM, tail-TCM, and full
				 * fw-sample scans during dwell are DISABLED.
				 * test.195 crashed mid-dwell (sample ~56/271)
				 * once HT resources became active — the heavy
				 * indirect-MMIO storm collides with the chip's
				 * post-HT clock-domain transition. Only the
				 * cheap CC backplane sample below remains for
				 * mid-dwell visibility. A single end-of-dwell
				 * fw-sample scan runs after the full dwell
				 * (see post-dwell block below the loop).
				 */

				{
					u32 bp_now[BRCMF_BP_REG_COUNT];

					brcmf_pcie_sample_backplane(devinfo,
								    bp_now);
					for (j = 0; j < BRCMF_BP_REG_COUNT;
					     j++)
						pr_emerg("BCM4360 test.188: dwell-%ums CC-%s=0x%08x (was 0x%08x) %s\n",
							 dwell_labels_ms[d],
							 brcmf_bp_reg_names[j],
							 bp_now[j], pre_bp[j],
							 bp_now[j] ==
							 pre_bp[j] ?
								"UNCHANGED" :
								"CHANGED");
				}

				/* test.199: per-tick TS sample removed — test.198
				 * proved cells stay constant across the dwell.
				 * Dump moved to end-of-dwell, see below.
				 */
			}

			/* test.196: single end-of-dwell fw-sample + wide-TCM
			 * scan AFTER the dwell completes. test.195 lost this
			 * data because the per-tick scan crashed mid-dwell;
			 * doing it once at the end gives us definitive
			 * "did firmware ever write TCM?" evidence with
			 * minimal exposure to clock-transition windows.
			 */
			if (fw->size >= 1024 && fw_sample_offsets) {
				u32 changed = 0, reverted = 0, unchanged = 0;
				for (j = 0; j < nr_fw_samples; j++) {
					u32 offset = fw_sample_offsets[j];
					u32 val = brcmf_pcie_read_ram32(devinfo, offset);
					u32 fw_val = get_unaligned_le32(fw->data + offset);
					if (val == pre_fw_sample[j])
						unchanged++;
					else if (val == fw_val)
						reverted++;
					else
						changed++;
				}
				pr_emerg("BCM4360 test.196: post-dwell fw-sample summary: %u UNCHANGED, %u REVERTED, %u CHANGED (of %u)\n",
					 unchanged, reverted, changed, nr_fw_samples);
			}
			for (j = 0; j < ARRAY_SIZE(wide_offsets); j++) {
				u32 offset = wide_offsets[j];
				u32 val = brcmf_pcie_read_ram32(devinfo, offset);
				if (val != pre_wide[j])
					pr_emerg("BCM4360 test.196: post-dwell wide-TCM[0x%05x]=0x%08x (was 0x%08x) CHANGED\n",
						 offset, val, pre_wide[j]);
			}

			/* test.199: hex+ASCII dump of the firmware-init data
			 * structure regions found in tests 196/197/198.
			 * Each 16-byte row = 4 indirect-MMIO reads (~250 µs)
			 * + an ASCII rendering of the 16 bytes for human
			 * inspection. Two ranges, ~92 rows total. Goal: see
			 * adjacent printable text and any nearby format
			 * strings to decode what firmware is reporting.
			 */
			for (j = 0; j < ARRAY_SIZE(dump_ranges); j++) {
				u32 addr;
				u32 lo = dump_ranges[j][0];
				u32 hi = dump_ranges[j][1];

				pr_emerg("BCM4360 test.218: dump range 0x%05x..0x%05x\n",
					 lo, hi);
				for (addr = lo; addr < hi; addr += 16) {
					u32 w[4];
					char ascii[17];
					unsigned int b;

					w[0] = brcmf_pcie_read_ram32(devinfo, addr);
					w[1] = brcmf_pcie_read_ram32(devinfo, addr + 4);
					w[2] = brcmf_pcie_read_ram32(devinfo, addr + 8);
					w[3] = brcmf_pcie_read_ram32(devinfo, addr + 12);
					for (b = 0; b < 16; b++) {
						u8 c = (u8)(w[b >> 2] >> ((b & 3) * 8));
						ascii[b] = (c >= 0x20 && c < 0x7f) ?
							(char)c : '.';
					}
					ascii[16] = '\0';
					pr_emerg("BCM4360 test.218: 0x%05x: %08x %08x %08x %08x | %s\n",
						 addr, w[0], w[1], w[2], w[3],
						 ascii);
				}
			}

			/* test.197: post-dwell fine-grain scan over upper TCM.
			 * Logs CHANGED cells individually + summary count.
			 * Single-pass — runs after dwell completes so the chip
			 * is in steady state for the duration of the scan.
			 */
			if (pre_fine) {
				u32 fine_changed = 0;
				u32 fine_first = 0xffffffff;
				u32 fine_last = 0;
				for (j = 0; j < nr_fine; j++) {
					u32 offset = fine_base + j * fine_stride;
					u32 val = brcmf_pcie_read_ram32(devinfo,
									offset);
					if (val != pre_fine[j]) {
						pr_emerg("BCM4360 test.197: post-dwell fine-TCM[0x%05x]=0x%08x (was 0x%08x) CHANGED\n",
							 offset, val, pre_fine[j]);
						fine_changed++;
						if (offset < fine_first)
							fine_first = offset;
						if (offset > fine_last)
							fine_last = offset;
					}
				}
				pr_emerg("BCM4360 test.197: fine-TCM summary: %u of %u cells CHANGED",
					 fine_changed, nr_fine);
				if (fine_changed > 0)
					pr_emerg("BCM4360 test.197: fine-TCM CHANGED span 0x%05x..0x%05x (%u bytes)\n",
						 fine_first, fine_last,
						 fine_last - fine_first + 4);
			}
#endif /* test.229 Option A: post-set_active probe + tier + dwell block skipped */
		}
		/* test.188: set_active ran with BusMaster ENABLED (set
		 * above before the call). Tiers ran at ~100-1650 ms then
		 * 3000 ms dwell sampled late-persistence state. Sample
		 * mailboxint one final time, then pci_clear_master before
		 * returning -ENODEV so the chip is in a safe state.
		 */
		{
			u32 mbint_final;
			u16 cmd_post_clear;
			u32 mmio_guard_post;

			brcmf_pcie_select_core(devinfo, BCMA_CORE_PCIE2);
			mbint_final = brcmf_pcie_read_reg32(devinfo,
					devinfo->reginfo->mailboxint);
			pr_emerg("BCM4360 test.188: final PCIE2 mailboxint=0x%08x (D2H bits would be 0x10000+, FN0 bits 0x0100/0x0200)\n",
				 mbint_final);

			pci_clear_master(devinfo->pdev);
			pci_read_config_word(devinfo->pdev, PCI_COMMAND,
					     &cmd_post_clear);
			pr_emerg("BCM4360 test.188: pci_clear_master done; PCI_COMMAND=0x%04x BM=%s\n",
				 cmd_post_clear,
				 (cmd_post_clear & PCI_COMMAND_MASTER) ?
					"ON" : "OFF");

			mmio_guard_post = brcmf_pcie_read_reg32(devinfo,
					devinfo->reginfo->mailboxint);
			pr_emerg("BCM4360 test.188: post-BM-clear MMIO guard mailboxint=0x%08x (endpoint alive after BM-off)\n",
				 mmio_guard_post);
		}

		release_firmware(fw);
		brcmf_fw_nvram_free(nvram);
		kfree(pre_fw_sample);
		kfree(fw_sample_offsets);
		kfree(pre_fine);
		pr_emerg("BCM4360 test.188: released fw/nvram after BM-before-set_active + tiers + 3000ms dwell + BM-clear; returning -ENODEV\n");
		return -ENODEV;
	} else {
		brcmf_pcie_copy_mem_todev(devinfo, devinfo->ci->rambase,
					  fw->data, fw->size);
	}

	resetintr = get_unaligned_le32(fw->data);
	release_firmware(fw);
	pr_emerg("BCM4360 test.188: after release_firmware resetintr=0x%08x\n",
		 resetintr);
	mdelay(50);

	if (nvram) {
		address = devinfo->ci->rambase + devinfo->ci->ramsize -
			  nvram_len;
		pr_emerg("BCM4360 test.188: pre-NVRAM write address=0x%x len=%u tcm=%px\n",
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
					pr_emerg("BCM4360 test.188: NVRAM wrote %u words (%u bytes)\n",
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
			pr_emerg("BCM4360 test.188: post-NVRAM write done (%u bytes)\n",
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
	/* BCM4360 test.276: free olmsg DMA buffer if allocated. Covers both
	 * remove and probe-failure paths (this function is called from both). */
	if (devinfo->t276_olmsg_buf) {
		dma_free_coherent(&devinfo->pdev->dev,
				  BCM4360_T276_OLMSG_BUF_SIZE,
				  devinfo->t276_olmsg_buf,
				  devinfo->t276_olmsg_dma);
		devinfo->t276_olmsg_buf = NULL;
		devinfo->t276_olmsg_dma = 0;
	}

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
	/* test.224: capture CR4+D11 clk_ctl_st at the earliest point
	 * where all devinfo/core state is available. Test.221 only saw
	 * HAVEHT=YES from deep inside download_fw_nvram; test.223 never
	 * reached that point because the 442KB BAR2 burst hung. This
	 * probe runs before the burst — if HAVEHT=YES here, we have
	 * pre-download confirmation even if the burst later hangs. */
	brcmf_pcie_probe_d11_clkctlst(devinfo, "pre-download");
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
		msleep(300); /* test.188: flush before root-port ASPM/CLKPM work */

		/* test.186d keeps the root-port LnkCtl logging from test.172 for
		 * comparability. test.172 showed root-port ASPM/CLKPM was already
		 * off, so the main discriminator is now extended post-release TCM
		 * sampling (firmware-originated write detection) in
		 * brcmf_pcie_download_fw_nvram().
		 */
		bridge = pci_upstream_bridge(pdev);
		if (bridge) {
			pcie_capability_read_word(bridge, PCI_EXP_LNKCTL,
						  &rp_lnkctl_before);
			dev_emerg(&pdev->dev,
				  "BCM4360 test.188: root port %s LnkCtl before=0x%04x ASPM=0x%x CLKREQ=%s — disabling L0s/L1/CLKPM\n",
				  pci_name(bridge), rp_lnkctl_before,
				  rp_lnkctl_before & PCI_EXP_LNKCTL_ASPMC,
				  rp_lnkctl_before & PCI_EXP_LNKCTL_CLKREQ_EN ? "on" : "off");
			msleep(300);

			pci_disable_link_state(bridge, PCIE_LINK_STATE_L0S |
					       PCIE_LINK_STATE_L1 |
					       PCIE_LINK_STATE_CLKPM);
			pr_emerg("BCM4360 test.188: root-port pci_disable_link_state returned — reading LnkCtl\n");
			msleep(300);

			pcie_capability_read_word(bridge, PCI_EXP_LNKCTL,
						  &rp_lnkctl_after);
			dev_emerg(&pdev->dev,
				  "BCM4360 test.188: root port %s LnkCtl after=0x%04x ASPM=0x%x CLKREQ=%s\n",
				  pci_name(bridge), rp_lnkctl_after,
				  rp_lnkctl_after & PCI_EXP_LNKCTL_ASPMC,
				  rp_lnkctl_after & PCI_EXP_LNKCTL_CLKREQ_EN ? "on" : "off");
			msleep(300);
		} else {
			dev_emerg(&pdev->dev,
				  "BCM4360 test.188: no upstream bridge found; root-port ASPM/CLKPM disable skipped\n");
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
	pr_emerg("BCM4360 test.188: module_init entry — extended post-release TCM sampling\n");
}

int brcmf_pcie_register(void)
{
	int ret;

	pr_emerg("BCM4360 test.188: brcmf_pcie_register() entry\n");
	msleep(300); /* flush marker before pci_register_driver */
	pr_emerg("BCM4360 test.188: before pci_register_driver\n");
	msleep(300); /* flush — if crash here, it's in pci_register_driver kernel code */
	ret = pci_register_driver(&brcmf_pciedrvr);
	pr_emerg("BCM4360 test.188: pci_register_driver returned ret=%d\n", ret);
	return ret;
}


void brcmf_pcie_exit(void)
{
	brcmf_dbg(PCIE, "Enter\n");
	pci_unregister_driver(&brcmf_pciedrvr);
}
