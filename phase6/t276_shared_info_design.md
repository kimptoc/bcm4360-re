# T276 — Shared-info handshake port design (Phase 5 pcie.c)

**Date:** 2026-04-24 (post-T275-CORRECTION, post-KEY_FINDINGS audit)
**Goal:** Port Phase 4B's proven `shared_info` pre-ARM-release write into Phase 5's `brcmf_pcie_setup`. This is a **diagnostic test**, not a claimed fix — we want to observe what fw does when the handshake direction is correct.
**Status:** Design only. No code yet. Advisor check required before implementation.

## Context — the one-line problem

Phase 5 pcie.c has **zero writes** of the shared_info magic (`0xA5A5A5A5`/`0x5A5A5A5A`). It only reads TCM[0x9D0A4] expecting fw to write the magic. Phase 4B Test.28 proved the opposite: **host writes magic first**, then fw responds.

## What Phase 4B proved (Test.28 / Test.29)

- Writing `shared_info` at TCM[0x9D0A4] **before ARM release** prevents the 100 ms panic.
- Fw runs stably for ≥2 s without corrupting anything.
- Fw **writes** `shared_info[+0x010]` with a non-zero value (observed: `0x0009af88`) — this is a pointer to a console struct.
- Fw sends **2 PCIe mailbox signals** (`PCIE_MAILBOXINT` = 0x00000003 post-run).
- Fw did NOT set `fw_init_done` (stayed 0).
- Fw did NOT write to the olmsg ring (write_ptr stayed 0).

## What Phase 5 gets WITHOUT shared_info (current baseline)

- Fw passes the panic point (NVRAM + Apple random_seed + FORCEHT are sufficient for that alone).
- Fw runs init, enters WFI by ~t+12 ms (T257).
- Scheduler state at TCM[0x6296C..0x629B4] frozen across 90 s (T255).
- pciedngl_isr registered as scheduler node[0] at TCM[0x9627C] (T255/T256/T274).
- sharedram_addr at TCM[ramsize-4] never changes from NVRAM trailer 0xffc70038 (T247).

## Hypothesis being tested

Adding a Phase 4B-style shared_info write in Phase 5's pre-ARM-release path will change fw's post-release behavior. Specifically:

- Fw will write a non-zero value to `shared_info[+0x010]` (a pointer into TCM).
- Fw will send ≥1 PCIe mailbox signal (non-zero `PCIE_MAILBOXINT`).
- Scheduler state at TCM[0x6296C..0x629B4] will NOT be frozen — it will advance through at least one more state.
- `fw_init_done` at `shared_info[+0x2028]` may or may not be set.
- sharedram_addr at TCM[ramsize-4] may or may not change.

Whether fw fully initializes depends on whether there's a FURTHER handshake step we haven't identified. Phase 4B Test.29 suggests there is (fw_init_done never fired even with DMA). But **we don't need to know that yet** — the first observable advance is itself diagnostic.

## Proposed code change (design only)

### Location

In `brcmf_pcie_download_fw_nvram` (phase5/work/.../pcie.c), **after the FORCEHT write and immediately before `brcmf_chip_set_active`** (around line 3513).

Placement rationale (advisor): writing *after* FORCEHT means no intermediate Phase 5 code can touch the shared_info region between our write and ARM release. This minimises any ordering interference.

Gated behind a new module param `bcm4360_test276_shared_info` so the change is opt-in and doesn't break the T270-BASELINE reproducibility test.

### Overlap check (pcie.c writes into [0x9D0A4..0x9FFE0))

- T234 (line 3523) zeros `[0x9FE00..0x9FF1C)` — within our shared_info region — BUT it is **already gated OFF when `bcm4360_test236_force_seed=1`** (line 3520: `if (!bcm4360_test236_force_seed) { … }`). T276 will run with `force_seed=1` (the T270-BASELINE config), so T234 cannot execute concurrently. No overlap.
- No other writes into `[0x9D0A4..0x9FFE0)` exist in pcie.c (grep confirmed). All references to `0x9D0A4` / `0x9F0CC` elsewhere are READS.

### Sketch

```c
static int bcm4360_test276_shared_info;
module_param(bcm4360_test276_shared_info, int, 0644);
MODULE_PARM_DESC(bcm4360_test276_shared_info,
    "BCM4360 test.276: write shared_info handshake at TCM[0x9D0A4] "
    "before ARM release (ports Phase 4B test.28 pattern). 1=enable, 0=off.");

/* BCM4360 test.276 constants (from phase4/work/bcm4360_test.c) */
#define BCM4360_T276_SHARED_INFO_OFFSET  0x9D0A4   /* ramsize - 0x2F5C */
#define BCM4360_T276_SHARED_INFO_SIZE    0x2F3C
#define BCM4360_T276_SI_MAGIC_START      0x000
#define BCM4360_T276_SI_DMA_LO           0x004
#define BCM4360_T276_SI_DMA_HI           0x008
#define BCM4360_T276_SI_BUF_SIZE         0x00C
#define BCM4360_T276_SI_FW_INIT_DONE     0x2028
#define BCM4360_T276_SI_MAGIC_END        0x2F38
#define BCM4360_T276_MAGIC_START_VAL     0xA5A5A5A5
#define BCM4360_T276_MAGIC_END_VAL       0x5A5A5A5A
#define BCM4360_T276_OLMSG_BUF_SIZE      0x10000    /* 64 KB */
#define BCM4360_T276_OLMSG_RING_SIZE     0x7800     /* 30 KB each ring */
#define BCM4360_T276_OLMSG_HDR_SIZE      0x20       /* 2 rings * 16 bytes */

/* Inside brcmf_pcie_download_fw_nvram, gated on test276: */
if (bcm4360_test276_shared_info &&
    devinfo->ci->chip == BRCM_CC_4360_CHIP_ID) {
    void *olmsg_buf = NULL;
    dma_addr_t olmsg_dma = 0;
    u32 base = BCM4360_T276_SHARED_INFO_OFFSET;
    u32 i;

    /* 1. Allocate DMA coherent buffer for olmsg. */
    olmsg_buf = dma_alloc_coherent(&devinfo->pdev->dev,
                                   BCM4360_T276_OLMSG_BUF_SIZE,
                                   &olmsg_dma, GFP_KERNEL);
    if (!olmsg_buf) {
        pr_emerg("BCM4360 test.276: dma_alloc_coherent FAILED; skipping\n");
        goto t276_skip;
    }
    memset(olmsg_buf, 0, BCM4360_T276_OLMSG_BUF_SIZE);

    /* 2. Initialize olmsg ring header (2 rings of 30 KB each). */
    {
        __le32 *p = (__le32 *)olmsg_buf;
        p[0] = cpu_to_le32(BCM4360_T276_OLMSG_HDR_SIZE);   /* ring0 data_off */
        p[1] = cpu_to_le32(BCM4360_T276_OLMSG_RING_SIZE);  /* ring0 size */
        p[2] = 0;  p[3] = 0;                               /* ring0 rd/wr */
        p[4] = cpu_to_le32(BCM4360_T276_OLMSG_HDR_SIZE
                         + BCM4360_T276_OLMSG_RING_SIZE);  /* ring1 data_off */
        p[5] = cpu_to_le32(BCM4360_T276_OLMSG_RING_SIZE);  /* ring1 size */
        p[6] = 0;  p[7] = 0;                               /* ring1 rd/wr */
    }

    /* 3. Zero the shared_info region in TCM. */
    for (i = 0; i < BCM4360_T276_SHARED_INFO_SIZE / 4; i++)
        brcmf_pcie_write_ram32(devinfo, base + i * 4, 0);

    /* 4. Write the handshake fields. */
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_MAGIC_START,
                           BCM4360_T276_MAGIC_START_VAL);
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_DMA_LO,
                           lower_32_bits(olmsg_dma));
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_DMA_HI,
                           upper_32_bits(olmsg_dma));
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_BUF_SIZE,
                           BCM4360_T276_OLMSG_BUF_SIZE);
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_FW_INIT_DONE, 0);
    brcmf_pcie_write_ram32(devinfo, base + BCM4360_T276_SI_MAGIC_END,
                           BCM4360_T276_MAGIC_END_VAL);

    pr_emerg("BCM4360 test.276: shared_info written at TCM[0x%x], "
             "olmsg_dma=0x%llx size=%d\n",
             base, (u64)olmsg_dma, BCM4360_T276_OLMSG_BUF_SIZE);

    /* 5. Verify ALL 6 written fields landed (not just magic). DMA_LO/HI
     *    and BUF_SIZE are what fw actually uses; silent bit-flip there
     *    would make fw do nothing while magic still looks correct. */
    pr_emerg("BCM4360 test.276: readback "
             "magic_start=0x%08x (exp 0x%08x) dma_lo=0x%08x (exp 0x%08x) "
             "dma_hi=0x%08x (exp 0x%08x) buf_size=0x%08x (exp 0x%08x) "
             "fw_init_done=0x%08x (exp 0) magic_end=0x%08x (exp 0x%08x)\n",
             brcmf_pcie_read_ram32(devinfo, base),
             BCM4360_T276_MAGIC_START_VAL,
             brcmf_pcie_read_ram32(devinfo, base + BCM4360_T276_SI_DMA_LO),
             lower_32_bits(olmsg_dma),
             brcmf_pcie_read_ram32(devinfo, base + BCM4360_T276_SI_DMA_HI),
             upper_32_bits(olmsg_dma),
             brcmf_pcie_read_ram32(devinfo, base + BCM4360_T276_SI_BUF_SIZE),
             BCM4360_T276_OLMSG_BUF_SIZE,
             brcmf_pcie_read_ram32(devinfo,
                                   base + BCM4360_T276_SI_FW_INIT_DONE),
             brcmf_pcie_read_ram32(devinfo,
                                   base + BCM4360_T276_SI_MAGIC_END),
             BCM4360_T276_MAGIC_END_VAL);

    /* 6. Stash olmsg buf in brcmf_pciedev_info for cleanup. Must be
     *    freed on BOTH successful remove AND probe-failure paths; the
     *    canonical cleanup site is brcmf_pcie_release_resource. */
    devinfo->t276_olmsg_buf = olmsg_buf;
    devinfo->t276_olmsg_dma = olmsg_dma;

t276_skip:
    ;
}
```

Then, ideally, **ensure bus mastering is ENABLED** before ARM release (it already is in Phase 5's setup path — verify, don't assume). Fw cannot DMA to the olmsg buffer without bus master.

After `brcmf_chip_set_active` returns TRUE (around line 3521), add a **post-release shared_info poll**:

Polling discipline (advisor): **do NOT break on first nonzero** — Phase 4B Test.28 showed `si[+0x010]` update AND 2 mailbox signals. Breaking on the first signal loses the other(s). Instead: log on any change, then continue polling for the full 2 s, logging every subsequent change. The timeline is the useful artifact.

```c
if (bcm4360_test276_shared_info) {
    u32 last_si_10 = 0xdeadbeef, last_fw_done = 0xdeadbeef,
        last_mbxint = 0xdeadbeef;
    for (i = 0; i < 200; i++) {      /* 2 seconds at 10 ms */
        u32 si_10      = brcmf_pcie_read_ram32(devinfo, base + 0x010);
        u32 si_fw_done = brcmf_pcie_read_ram32(devinfo,
                                 base + BCM4360_T276_SI_FW_INIT_DONE);
        u32 mbxint     = brcmf_pcie_read_reg32(devinfo,
                                 BRCMF_PCIE_PCIE2REG_MAILBOXINT);
        if (si_10 != last_si_10 || si_fw_done != last_fw_done ||
            mbxint != last_mbxint) {
            pr_emerg("BCM4360 test.276: t+%dms "
                     "si[+0x010]=0x%08x fw_done=0x%08x mbxint=0x%08x\n",
                     i * 10, si_10, si_fw_done, mbxint);
            last_si_10 = si_10;
            last_fw_done = si_fw_done;
            last_mbxint = mbxint;
        }
        msleep(10);
    }
    /* Final snapshot always printed, even if nothing changed. */
    pr_emerg("BCM4360 test.276: poll-end "
             "si[+0x010]=0x%08x fw_done=0x%08x mbxint=0x%08x\n",
             brcmf_pcie_read_ram32(devinfo, base + 0x010),
             brcmf_pcie_read_ram32(devinfo,
                                   base + BCM4360_T276_SI_FW_INIT_DONE),
             brcmf_pcie_read_reg32(devinfo,
                                   BRCMF_PCIE_PCIE2REG_MAILBOXINT));
}
```

### Cleanup (advisor polish 5)

Add to `brcmf_pcie_release_resource` (called from remove and probe-failure):

```c
if (devinfo->t276_olmsg_buf) {
    dma_free_coherent(&devinfo->pdev->dev,
                      BCM4360_T276_OLMSG_BUF_SIZE,
                      devinfo->t276_olmsg_buf,
                      devinfo->t276_olmsg_dma);
    devinfo->t276_olmsg_buf = NULL;
    devinfo->t276_olmsg_dma = 0;
}
```

## Outcome matrix

| Observed | Interpretation | Next step |
|---|---|---|
| `si[+0x010]` becomes non-zero AND `mbxint` becomes non-zero | fw is responding to handshake (matches Test.28). This is the **success** outcome — we have a working protocol anchor. | Follow `si[+0x010]` pointer → read console struct → decode. Then probe further to identify next handshake step. |
| Only `mbxint` becomes non-zero | Fw sees the handshake but hasn't written +0x010. Unexpected per Test.28 but still progress. | Wait longer; check scheduler state differs from baseline. |
| No change across 2 s | Either the write path failed (readback check will catch this), OR fw doesn't reach the check. | Verify readbacks; if readbacks OK, the handshake has changed meaning between Phase 4B's fw and our current state — need to rethink. |
| `fw_init_done` becomes non-zero | Full init. Would be a big surprise given Test.29. | Switch from diagnostic to communication — probe olmsg ring, try sending a command. |
| Host wedges earlier than T270-BASELINE | Regression — bus-mastering + DMA + Phase 5 patches interacting badly. | Disable with `bcm4360_test276_shared_info=0`; investigate. |

## Safety

- Module param gated → default OFF → Phase 5's T270-BASELINE behavior unchanged when disabled.
- Write path is TCM writes + one DMA coherent alloc — standard operations, no novel PCIe risk.
- No new MSI subscription (deliberately avoiding the T264-T266 MSI-wedge issue; keeps this test orthogonal).
- Worst case: same wedge as T270-BASELINE.

## What this does NOT do (explicit scope limits)

- Does NOT attempt to send a command via olmsg.
- Does NOT subscribe MSI or register a threaded IRQ handler.
- Does NOT attempt to be a working driver — this is purely observation.

Even the success outcome just gives us a pointer into TCM. Full driver bringup is multi-step beyond that.

## Pre-test checklist (when ready to fire)

1. Build with `bcm4360_test276_shared_info` param visible via `modinfo`.
2. PCIe state clean (`Mem+ BusMaster+`, no `MAbort+`).
3. Fresh cold cycle (substrate window matters — T270-BASELINE proved ~25 min post-cycle).
4. `PRE-TEST.276` block in RESUME_NOTES with outcome matrix.
5. Commit + push + sync before fire.
6. Fire: `insmod ... bcm4360_test236_force_seed=1 bcm4360_test238_ultra_dwells=1 bcm4360_test276_shared_info=1` with `sleep 30` then `rmmod`.
7. Capture journal; compare si+mbxint deltas vs T270-BASELINE.

## Advisor review (2026-04-24 post-design) — RESOLVED

1. **Direction** — T276 first, MSI-wedge (Candidates B/C) second. Axes are orthogonal; T276 doesn't touch MSI. If fw responds, MSI-wedge becomes the next gate. If fw stays silent, protocol model needs reconsidering before MSI work is worth anything.
2. **DMA addressing** — No `dma_set_mask` anywhere in brcmfmac PCIe path; kernel default 32-bit is fine for BCM4360 (PCIe Gen1 x1, no 64-bit addressing required). Noted, not a blocker.
3. **`write_ram32` semantics** — Resolved via pcie.c:1385. Calls `iowrite32(value, devinfo->tcm + devinfo->ci->rambase + mem_offset)`. For BCM4360 rambase = 0, so equivalent to Phase 4B's direct BAR2 `iowrite32`. ✓
4. **bus master state** — Resolved via pcie.c:3303. `pci_set_master(devinfo->pdev)` is called before FORCEHT, before `brcmf_chip_set_active`. ✓
5. **Reproducibility of Test.28 result** — Open; this is what T276 measures. Expected ambiguity, not a blocker.

### Polish items addressed in this revision

- **Polling discipline**: continuous 2 s polling, log on any change, plus a final snapshot — gives a timeline instead of a first-signal truncation.
- **Readback all 6 fields**: magic + DMA_LO/HI + BUF_SIZE + fw_init_done + magic_end. Silent bit-flip on DMA would otherwise pass the magic check.
- **Placement**: immediately before `brcmf_chip_set_active`, after FORCEHT — no Phase 5 code between write and ARM release.
- **Overlap check**: T234 is the only other writer into the region, and it's gated OFF when `test236_force_seed=1`. No concurrent overlap.
- **Cleanup**: `dma_free_coherent` in `brcmf_pcie_release_resource` (covers both remove + probe-failure paths).

Advisor green-lit implementation.

## Clean-room note

This is a port of Phase 4B's observed behavior. The shared_info struct layout was deduced by Phase 4B from wl.ko reverse engineering (behavior → offsets), not from firmware disassembly. Test.28's positive result confirms the offsets empirically. This is clean-room implementation of an observed host-protocol.
