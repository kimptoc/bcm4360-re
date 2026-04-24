# T275 — Upstream / Project audit: does any version of brcmfmac drive PCIe-CDC firmware?

**Date:** 2026-04-24 (post-T274-FW)
**Method:** Local grep + git log archaeology on our own project tree.

## TL;DR

- **Answer to the core question**: the upstream mainline brcmfmac driver does NOT drive PCIe-CDC firmware. Its PCIe path is msgbuf-only (pcie.c hardcodes `proto_type = BRCMF_PROTO_MSGBUF`; Kconfig `BRCMFMAC_PCIE selects BRCMFMAC_PROTO_MSGBUF`).
- **However, BCDC protocol code EXISTS** in brcmfmac (`bcdc.c` + `bcdc.h`) and is currently wired to **SDIO (`bcmsdh.c:1081`) and USB (`usb.c:1263`)**, not PCIe. The BCDC proto layer talks to the bus via standard `txctl`/`rxctl`/`txdata` callbacks that every bus provides.
- **Critical observation**: PCIe's `brcmf_pcie_tx_ctlpkt` and `brcmf_pcie_rx_ctlpkt` (pcie.c:2597/2604) are **STUBS that return 0** — they exist because the function-pointer table requires them, but msgbuf's proto attach never calls them (msgbuf has its own ring-based ctl path).
- **This is rediscovery**: the project already knew (from Phase 4B, commit `fc73a12` dated 2026-04-12) that "BCM4360 wl firmware uses BCDC protocol… while brcmfmac PCIe requires msgbuf protocol. No msgbuf firmware exists for BCM4360 in any known source. **Driver patches are proven working — firmware compatibility is the sole blocker.**"
- **New engineering path (synthesized from rediscovery + T274 findings)**: route BCDC over PCIe via a minimal implementation of `tx_ctlpkt`/`rx_ctlpkt` that uses the existing H2D/D2H mailbox registers + the PCIE-CDC firmware's own `pciedngl_isr` as the counter-party. The fw side is already implemented (T269 analysis) — it consumes commands via `pciedngl_isr` → `dngl_dev_ioctl` and returns responses via TCM ring writes.

## 1. The audit question, answered

### 1.1 Is BCDC currently wired to PCIe in upstream brcmfmac?

**No.** Evidence:

- `pcie.c:6877`: `bus->proto_type = BRCMF_PROTO_MSGBUF;` — PCIe probe hardcodes msgbuf.
- `Kconfig`: `config BRCMFMAC_PCIE { select BRCMFMAC_PROTO_MSGBUF; }` — PCIe implies msgbuf at config time.
- `bus.h:51-52`: only two proto types exist (`BRCMF_PROTO_BCDC` and `BRCMF_PROTO_MSGBUF`). No third "PCIe-CDC" type.
- `proto.c:32-41`: the proto dispatch is a pure if/else between BCDC and MSGBUF.

### 1.2 Was there ever a version of brcmfmac that drove PCIe-CDC firmware?

Local git log on our project tree (searched for `CDC|PCIE-CDC|bcdc` in commit messages):

- All CDC-related project commits are FROM OUR OWN work (Phase 4A, 4B, 5.x). None reference an upstream origin for PCIe-CDC support.
- Kernel-tree upstream archaeology isn't available locally, but the Kconfig/proto layout says: no native path.

**Negative with moderate confidence.** Possibility not fully ruled out: there may exist an out-of-tree Broadcom driver (`wl.ko` proprietary; `brcm-sta-dkms`; Apple/macOS drivers) that drives PCIe-CDC firmware via a private non-brcmfmac path. Phase 4A's analysis of wl.ko (phase4/notes/transport_discovery.md) suggested wl.ko treats BCM4360 as a **SoftMAC NIC with offload engine**, not a FullMAC dongle — so wl.ko's code path may not be directly applicable.

### 1.3 Does any bus transport in brcmfmac drive BCDC?

**Yes, SDIO and USB.** Evidence:

- `bcmsdh.c:1081`: `bus_if->proto_type = BRCMF_PROTO_BCDC;`
- `usb.c:1263`: `bus->proto_type = BRCMF_PROTO_BCDC;`
- Both provide full `brcmf_bus_ops` structs with working `txctl`/`rxctl` implementations that shuttle BCDC command bytes over their respective transports.

## 2. The BCDC protocol layer (how it expects to talk to the bus)

From `bcdc.c`:

| BCDC operation | Bus API called | Purpose |
|---|---|---|
| Send command (e.g., `query_dcmd`, `set_dcmd`) | `brcmf_bus_txctl(bus_if, msg, len)` → `bus->ops->txctl(dev, msg, len)` | Write CDC header + payload as raw bytes to dongle |
| Receive response | `brcmf_bus_rxctl(bus_if, msg, len)` → `bus->ops->rxctl(dev, msg, len)` | Read CDC header + payload as raw bytes from dongle |
| Send data packet | `brcmf_bus_txdata(bus_if, skb)` → `bus->ops->txdata(dev, skb)` | Write TX data frame |

BCDC cares only about the bus abstraction; it doesn't know whether the bus is SDIO, USB, or PCIe. If a PCIe-CDC transport implementation was added to `brcmf_pcie_bus_ops`, BCDC would work unchanged over PCIe.

### 2.1 CDC wire format (from bcdc.c)

```c
struct brcmf_proto_bcdc_dcmd {
    __le32 cmd;      // dongle command value
    __le32 len;      // lower 16: output buflen; upper 16: input buflen
    __le32 flags;    // flag defs given below
    __le32 status;   // status code returned from device
    // payload follows
};
```

16-byte header + variable payload. Standard CDC-class encoding.

## 3. What the PCIe bus ops ALREADY have

`pcie.c:2703`:
```c
static const struct brcmf_bus_ops brcmf_pcie_bus_ops = {
    .preinit = brcmf_pcie_preinit,
    .txdata = brcmf_pcie_tx,
    .stop = brcmf_pcie_down,
    .txctl = brcmf_pcie_tx_ctlpkt,     // line 2707
    .rxctl = brcmf_pcie_rx_ctlpkt,     // line 2708
    ...
};
```

`pcie.c:2597`:
```c
static int brcmf_pcie_tx_ctlpkt(struct device *dev, unsigned char *msg, uint len)
{
    return 0;                           // ← stub
}

static int brcmf_pcie_rx_ctlpkt(struct device *dev, unsigned char *msg, uint len)
{
    return 0;                           // ← stub
}
```

These are intentionally unused by msgbuf. Msgbuf's proto attach installs its own `query_dcmd`/`set_dcmd`/`tx_queue_data` that go directly to msgbuf's commonrings. The function-pointer slots in bus_ops are still required by the interface, hence the stub.

**To enable BCDC over PCIe, these two stubs need real implementations.**

## 4. Rediscovery context — what Phase 4 already knew

Phase 4A (`phase4/notes/transport_discovery.md`, 2026-04-12):

- Analyzed `wl.ko` proprietary driver statically. Concluded BCM4360 is SoftMAC + offload engine (not FullMAC).
- Phase 4A's finding: "There is no BCDC-over-PCIe transport protocol to reverse-engineer." But this was based on wl.ko's OFFLOAD firmware analysis (the "4352pci-bmac" offload fw), which is a different fw image than the PCIE-CDC FullMAC fw we have.

Phase 4B (commit `fc73a12`, 2026-04-12):

- Direct firmware-blob analysis identified PCIE-CDC / BCDC strings.
- Conclusion: "BCM4360 wl firmware uses BCDC protocol (bcmcdc.c, rtecdc.c, pciedngl_*) while brcmfmac PCIe requires msgbuf protocol. No msgbuf firmware exists for BCM4360 in linux-firmware or any known source. The chip predates msgbuf protocol introduction. **Driver patches are proven working — firmware compatibility is the sole blocker.**"

Phase 4B committed `a8007d2` — "final attempt crashed, document Phase 4 conclusion". Phase 4 ended there.

Phase 5 then began attempting to work around the protocol mismatch by patching brcmfmac PCIe to probe/advance further. 300+ commits later, T258–T269 scaffold investigation, T250–T274 blob deep-dives — all ultimately re-proving what Phase 4B already concluded.

**T274-FW independently reached the same conclusion via different evidence** (HOSTRDY_DB1 not referenced in code + PCIE-CDC banner + stub txctl/rxctl). The blob evidence closes the loop on Phase 4B's assertion with primary sources.

## 5. The new engineering path (the novel contribution of T275)

With the rediscovery grounded in current evidence, the concrete way forward is crisper than what Phase 4 ended on:

### 5.1 Minimal-change patchset outline

1. **Add a Kconfig option** `BRCMFMAC_PCIE_BCDC` (or a per-chip flag) to opt into BCDC on PCIe.
2. **Modify `brcmf_pcie_setup`** (pcie.c:6877) to set `proto_type = BRCMF_PROTO_BCDC` when the chip is BCM4360 (or when the Kconfig flag is set).
3. **Implement `brcmf_pcie_tx_ctlpkt`** to:
   - Write CDC command bytes into a known TCM buffer (the PCIE-CDC firmware's command-input region, identified during probe).
   - Write H2D_MAILBOX_1 = 1 to signal the fw (this is the `pciedngl_isr` FN0_0 trigger bit = 0x100, identified in T269).
   - Wait for completion (either poll or sleep on a waitqueue).
4. **Implement `brcmf_pcie_rx_ctlpkt`** to:
   - Register a D2H mailbox IRQ handler (before any command goes out).
   - The handler copies CDC response bytes from a TCM buffer + wakes the waitqueue.
   - `rx_ctlpkt` sleeps on the waitqueue until the handler signals, then copies bytes into the caller's `msg` buffer.
5. **Wire up data path** via `tx_queue_data` and the existing `brcmf_pcie_tx` function, adapted if needed.

### 5.2 The specific offsets / registers we know from T250–T274

- `pciedngl_isr` entry: blob 0x1C98 (invoked when FN0_0 bit 0x100 of `ISR_STATUS` fires → i.e., after host writes H2D_MAILBOX_1 = 1). Ring's the fw-side CDC ISR.
- `pciedngl_isr`'s message-read path: calls `bl #0x2E10` to read a packet (up to 0x400 bytes = 1024) from a HW queue into an alloc'd buffer, then dispatches to `dngl_dev_ioctl` at 0x20D8.
- Shared struct address: fw publishes sharedram_addr at TCM[ramsize-4] once it's ready; T247 confirmed fw never does this under our current harness because **the host doesn't issue the first CDC command to trigger the init handshake**. CDC protocol is host-initiated.

### 5.3 Testable-to-completion design (suggested advisor-check)

- The first milestone would be: send a BCDC ioctl command (e.g., `WLC_GET_VERSION`) and read the response.
- Success indicator: response contains a valid version number; sharedram_addr is subsequently published (side-effect of fw's boot advancing past the CDC-wait state).
- Failure modes to design for: host wedge on MSI subscription (the persistent side issue from the T258–T269 scaffold work, orthogonal to the proto question).

### 5.4 Why this works when scaffold investigations didn't

The scaffold investigation (T258–T269) was writing H2D_MAILBOX_1 into a fw state where the msgbuf proto attach had populated no shared.flags with HOSTRDY_DB1 (since fw doesn't advertise it) AND with uninitialized msgbuf rings (because msgbuf rings are never set up on this fw). Fw would either ignore the doorbell (nothing to do), or its `pciedngl_isr` would fire, read a nonsense command buffer, and barf.

With BCDC wiring, the command buffer is populated with a real CDC command BEFORE the doorbell. Fw's `pciedngl_isr` reads a valid command, processes it, responds. Normal CDC operation.

## 6. What Phase 4B didn't have that T275 does

- **Exact pciedngl_isr + hndrte_add_isr behavior** (T269 clean-room analysis): we now know exactly what fw-side ISR does on doorbell.
- **Exact device-probe structure** (T272): we know pcidongle_probe registers pciedngl_isr with bit 3 = FN0_0; wlc-probe registers fn@0x1146C on a separate class.
- **Exact post-probe state** (T274 x T255/T256): we know pcidongle_probe completes and the scheduler enters idle before sharedram publish — because fw is waiting for the first host CDC command to advance its init state machine.
- **Confirmation via negative evidence** (T274 §5): fw genuinely has no HOSTRDY_DB1 code path — the gating that upstream brcmfmac uses is irrelevant to this fw.

Phase 4B concluded "driver patches proven working, fw compat is the sole blocker" — at the time that was partly wrong (msgbuf proto is fundamentally incompatible regardless of driver patches; the issue isn't just "fw didn't advertise HOSTRDY_DB1", it's "fw doesn't speak msgbuf at all"). T274/T275 refine the understanding: **the correct action is not "patch brcmfmac-PCIe to work around msgbuf gating" but "route BCDC over PCIe via the stubs that already exist."**

## 7. Open questions

1. **Where exactly is the CDC command input buffer in TCM?** `pciedngl_isr`'s message-read target is at `devinfo->[0x10]` (the "HW descriptor" pointer). Need to identify what that is at runtime — likely a queue pointer allocated during pcidongle_probe.
2. **Which exact H2D mailbox register does fw read?** H2D_MAILBOX_1 (= 0x144 in PCIe2 core) is the FN0_0 trigger per our assumption but needs confirmation that writing to it sets bit 0x100 in the fw-side mirror.
3. **The host-side MSI subscription wedge** (T258–T269): still unresolved. BCDC-over-PCIe will need to subscribe MSI to get D2H responses. Candidates B (remove `pci=noaer`) and C (`pci=noaspm`) from the code audit remain live and orthogonal to this work.
4. **CDC command sequence from cold boot**: upstream drivers (for other chips) send a specific bringup dialog. Need to discover (or extract from wl.ko / Broadcom docs) what the first-few-commands sequence is for BCM4360.

## 8. Recommended next actions

1. **Before any code**: advisor-check this synthesis. The rediscovery angle means we're effectively proposing to restart a direction Phase 4 already closed; that deserves scrutiny.
2. **If approved**: write `tx_ctlpkt`/`rx_ctlpkt` skeletons that use the existing `brcmf_pcie_send_mb_data` + a new TCM command buffer. Gate behind a module param for BCM4360.
3. **First test**: attempt a `WLC_GET_VERSION` dcmd with just command-send + response-read; confirm round-trip.
4. **If round-trip works**: sharedram_addr should become populated (side-effect of fw's state advancing). That would be the definitive break from the session-long hang.
5. **Do NOT fire hardware speculatively**; design with expected observables listed first.

## 9. Clean-room posture

All findings here are from: (1) reading our own patched pcie.c + proto.c + bus.h (textual grep, no disassembly); (2) reading our own phase4/notes documents; (3) reading our own git log; (4) synthesis with T269/T272/T273/T274 blob findings (already clean-room per their own methodology). No new firmware analysis in this audit; no code changes.
