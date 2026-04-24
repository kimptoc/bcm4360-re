# T269 — Firmware-blob disassembly of `pciedngl_isr` and the wake path

**Date:** 2026-04-24
**Blob:** `/home/kimptoc/brcmfmac4360-pcie.bin` (442233 bytes, md5 `812705b3ff0f81f0ef067f6a42ba7b46`)
**Method:** Read-only static disassembly with capstone via ctypes (Thumb mode). Scripts alongside this doc.
**Task brief:** `phase6/t269_fw_blob_diss.md`
**Clean-room note:** all observations are described in plain language from disassembled mnemonics, literal-pool reads, and ASCII-string cross-references. No large reconstructed function bodies committed — only short illustrative snippets where essential.

## TL;DR

- `pciedngl_isr` entry confirmed at blob **0x1C98** (Thumb). Body is 260 bytes.
- Scheduler dispatches it whenever bit **3 (0x8)** of the RTE "pending events" word is set. That word lives at `*(*(ctx+0x358)+0x100)` where `ctx = [0x6296C]`; the bit-index is allocated at registration time by `hndrte_add_isr` (not hard-coded).
- The ISR reads a software ISR_STATUS at `*(pciedev+0x18)+0x18)+0x20` and tests **bit 0x100** (which matches upstream's `BRCMF_PCIE_MB_INT_FN0_0` bit — the FN0 doorbell triggered by a host write to `H2D_MAILBOX_1`). On valid, it ACKs by writing 0x100 back (W1C).
- Fw performs **no host-facing register write** as part of its wake handshake. All response is via TCM ring writes that the host polls.
- `hndrte_add_isr` tail-calls a **HW-unmask commit** (0x99AC → 0x27EC) that enables the bit for the CPU only *after* the scheduler list is populated.
- **No "panic" / "reboot" string** in the blob. The fault-dump handler (0x63EE4) installs a software "deadman_to" RTE timer, but it is an internal PM / ramstbydis timer, not a "host didn't respond" kill-switch.
- **Upstream brcmfmac's normal order** is: fw publishes `shared.flags |= BRCMF_PCIE_SHARED_HOSTRDY_DB1` (0x10000000), and only *then* does the host call `brcmf_pcie_hostready` (write H2D_MAILBOX_1 = 1). Our scaffold rings the doorbell without waiting for that flag — so when fw wakes, it runs `pciedngl_isr` against un-initialized ring state, which is consistent with the silent late-ladder wedge.

## 1. pciedngl_isr entry point confirmation

T256 captured the scheduler callback list from live TCM via BAR2 probes:

```
node[0] @ 0x9627C:
  next = 0x96F48     fn = 0x1C99 (Thumb → 0x1C98)
  arg  = 0x58CC4     flag = 0x00000008
```

Disassembly at 0x1C98 has a 7-register save prologue (`push.w {r4-r8, sb, lr}`) and immediately references three blob strings that confirm the identity:

| Blob offset | String |
|---|---|
| 0x4069D | `"pciedngl_isr called\n"` |
| 0x406B2 | `"%s: invalid ISR status: 0x%08x"` |
| 0x40685 | `"pciedngl_isr"` |
| 0x406E5 | `"pciedev_msg.c"` |
| 0x40733 | `"pciedngl_isr exits"` |

These are referenced from 0x1CA0, 0x1CB6, 0x1CB8, 0x1CDC, 0x1D70 — i.e. they are used by this function, not just colocated. **Identity settled.**

Script: `phase6/t269_locate_isr.py` (walks [0x629A4] if populated, verifies prologue at 0x1C98). Note: the list head is zero in the blob image — the list is built at runtime by pcidongle_probe, so static list-walking produces no nodes; the captured TCM values from T256 are what we trust.

## 2. How the scheduler picks node[0]

The RTE scheduler at 0x115C walks the callback list:

- `r0 = *[0x6296C]` (the interrupt-class context pointer).
- `r5 = bl 0x9936` — event-mask getter. This is a 3-insn leaf: `r3 = [r0+0x358]; r0 = [r3+0x100]; bx lr`. So `r5 = *(*(ctx+0x358)+0x100)` — a software-maintained 32-bit "pending events" word.
- Iterate nodes starting at `*[0x629A4]`. For each node:
  - `r3 = node.flag (+0xC)`
  - `tst r5, r3` — check if any of the node's bits are pending
  - if set, `r3 = node.fn (+4)`, `r0 = node.arg (+8)`, `blx r3`

Node[0].flag = 0x8, so bit 3 of the pending word dispatches `pciedngl_isr`.

`0x9936` is a **reader** only (no side effects, no BSS writes — confirmed also by T256 prechecks). The pending word is populated by the HW-interrupt dispatcher, which we did not chase further (its writer lives inside the RTE IRQ entry path that branches through the 0x28xx table — cf. `0x99AC b.w 0x27EC` below).

## 3. pciedngl_isr body — behavior sketch

Prologue loads two struct pointers out of `arg = pciedev_info*`:

```
r5 = *(arg + 0x18)     ; per-ISR sub-struct ("bus info")
r6 = *(r5 + 0x18)      ; per-ISR HW-shadow struct (ISR_STATUS container)
```

Then:

1. Print `"pciedngl_isr called\n"` (via `printf` at 0xA30).
2. Read status: `r3 = *(r6 + 0x20)` — the ISR_STATUS word.
3. `tst r3, #0x100` — test bit 8.
4. If **not set**: print `"%s: invalid ISR status: 0x%08x"` and return (no ACK). This is the "spurious call" path.
5. If **set**:
   - `*(r6 + 0x20) = 0x100` — **W1C ACK** (write-one-to-clear of the same bit).
   - `r0 = *(r5 + 0x20)` (message-pool ptr), `bl 0x4E20` to get a packet descriptor.
   - If alloc fails → trace `"malloc failure"` + source file `"pciedev_msg.c"` line 250, and bail out.
   - Else: read the packet buffer length, call a message-read helper at 0x2E10 (reads 0x400 bytes from the HW queue into the newly allocated descriptor), pass it up via `dngl_dev_ioctl` at 0x20D8.
   - On dngl_dev_ioctl error: print `"%s: error calling dngl_dev_ioctl: %d"`.
6. Loop back to step 2 while more packets remain (r7 != 0), otherwise print `"pciedngl_isr exits\n"` and return.

### Bit 0x100 cross-reference to upstream

The value 0x100 corresponds to `BRCMF_PCIE_MB_INT_FN0_0` in the host driver
(`phase5/work/.../brcmfmac/pcie.c:954`), i.e. the FN0 doorbell bit that gets set
when the host writes `H2D_MAILBOX_1`. The ISR does not read BAR-backed MMIO
directly — it reads a software shadow at `[r6+0x20]` — but the bit value and
W1C semantics match the hardware register's behavior exactly, so the shadow
is populated from (or aliased to) the fw-side MAILBOXINT mirror by the RTE
IRQ entry path.

## 4. How the flag bit is allocated — `hndrte_add_isr` (0x63C24)

`pcidongle_probe` is at 0x1E90. Near the end it assembles a call to 0x63C24 with the pciedngl_isr fn-ptr literal (0x1C99) in `r3`. Behavior of 0x63C24:

1. `bl 0x1298` allocates a 16-byte node from the RTE heap.
2. Reads `[0x6296C]` (the HW-class context).
3. `bl 0x9956` reads `*(ctx + 0xCC)` — appears to be a per-class field.
4. `bl 0x9990` (name/ID validator — tolerant 0..0xF range check tail-calling 0x27EC).
5. `bl 0x9940` (dispatch-thunk → 0x2890) returns a **bit index**; `sb = 1`; `[node+0xC] = sb << bit_index`.
   - For pciedngl_isr this produced bit index 3 → flag = 0x00000008.
6. `[node+8] = caller-supplied arg`; `[node+4] = r8 = pciedngl_isr fn-ptr`.
7. Link at the head of `[0x629A4]` list: `next = old head; *[0x629A4] = node`.
8. **Tail-call 0x99AC → 0x27EC**. 0x99AC is a 1-insn forwarder (`b.w 0x27EC`). 0x99AC and its neighbors (0x99B0/0x99B4/…/0x99C8) form a **9-entry vector** of per-HW-class thunks — each targets a function in the 0x27xx..0x2Axx region. The presence of this vector and its invocation at *exit* of `hndrte_add_isr` is consistent with an "unmask the newly-registered bit at the hardware interrupt-mask register" step.

So: registration does three things at once — allocates a free bit, links the callback node, and tells the HW dispatcher to unmask that bit for this class. **Bit 3 unmasking happens here, not via a host-visible register write.**

### Implication

The fw's "I am ready to receive FN0_0" state is reached only at the return of `hndrte_add_isr(..., pciedngl_isr, ...)` inside `pcidongle_probe`, which itself runs deep inside the RTE post-boot init. Before that point, the FN0_0 doorbell bit is masked at the fw's class-dispatch level even if the HW bit is set. The host writing H2D_MAILBOX_1 before this point either latches (if the fw-side FN0_0 register is level-sensitive and sticky) or is lost (if edge-sensitive).

## 5. Pre-wake handshake expectations

### 5.1 What the blob contains

| Searched literal | Hits in blob | Interpretation |
|---|---|---|
| `0x00FF0300` (our MAILBOXMASK value) | **0** | Fw does not compare, read back, or store our scaffold mask literal. |
| `0x00000300` (int_fn0 combo) | 5 (all false positives in random integer data) | Not used as a distinct mask literal. |
| `0x00000048` (MAILBOXINT BAR0 offset) | 2 (both false positives — WLRPC ID enum entries 0x47, 0x48, 0x49, …) | Fw does not refer to the host-side BAR0 offset by that number. |
| `0x00000144` (H2D_MAILBOX_1 BAR0 offset) | **0** | As expected: fw does not write host-doorbell addresses. |
| `0x10000000` (`BRCMF_PCIE_SHARED_HOSTRDY_DB1`) | 0 in direct-literal search (wider search to do if needed) | Fw's announcement path likely builds this by shifting, not by literal load. |

No host-facing register literal surfaces — consistent with the picture that the fw side accesses its own mirror of MAILBOXINT through the backplane window, not via the PCIe2Reg BAR0 offsets the host uses.

### 5.2 What the upstream host flow requires

From `phase5/work/.../brcmfmac/pcie.c`:

- `#define BRCMF_PCIE_SHARED_HOSTRDY_DB1 0x10000000` (pcie.c:1016)
- `brcmf_pcie_hostready` (pcie.c:2044) is gated on `devinfo->shared.flags & BRCMF_PCIE_SHARED_HOSTRDY_DB1` — it only writes the H2D_MAILBOX_1 doorbell if fw has advertised the `HOSTRDY_DB1` bit in the shared-RAM `flags` word.
- `devinfo->shared.flags` is populated from TCM by `brcmf_pcie_init_share_ram_info` (pcie.c:2751) — which runs after firmware download completes AND after fw writes the sharedram_addr into the TCM slot at `ramsize-4`.

So the upstream ordering is:
1. Host downloads fw and jumps fw execution (chip_set_active).
2. Fw boots, runs RTE init, runs `pcidongle_probe` → `hndrte_add_isr(..., pciedngl_isr, bit=3)` → FN0_0 unmasked on the fw side.
3. Fw publishes the shared-RAM pointer + `flags` field, including `HOSTRDY_DB1`.
4. Host reads shared-RAM, sees `HOSTRDY_DB1` set, calls `brcmf_pcie_hostready` → writes H2D_MAILBOX_1 = 1.
5. Fw's FN0_0 fires (already unmasked) → scheduler dispatches pciedngl_isr → handshake proceeds.

Our test scaffold does **steps 1 → 2-ish → (skip 3) → 4** — we write H2D_MAILBOX_1 without waiting for `HOSTRDY_DB1`, and we never read the shared-RAM flags field.

## 6. Watchdog / panic search

| Search | Result |
|---|---|
| `"panic"` | 0 hits |
| `"reboot"` | 0 hits |
| `"watchdog"` | 8 hits — all are *soft* wlc / dngl internal watchdogs (`wlc_phy_watchdog`, `wlc_bmac_watchdog`, `wlc_dngl_ol_bcn_watchdog`, `wlc_dngl_ol_tkip_watchdog`). These are periodic-tick style, not "host must respond or die" timers. |
| `"reset"` | 29 hits, mostly ai_core / resetctrl debug strings; the one of interest is `"%s: Watchdog reset bit set, clearing"` (blob 0x40C0E) — a *boot-time* check that clears a latched watchdog-reset status, not a runtime timer. |
| `"deadman_to"` | 1 hit; referenced by the fault-dump handler at 0x63EE4 which *installs* a `deadman_to` RTE timer (2-second armed inside 0x63EE4). Callback at 0x1A8C is 4 instructions and tail-calls the RTE enqueue path — it's a PM/ramstbydis helper, not a host-response killer. |

**Net**: the blob does not contain a "host stopped talking → panic/reboot" watchdog. The fw can be left in WFI indefinitely without self-destructing. Whatever the host sees as the post-scaffold wedge is **not** a fw-initiated reset.

## 7. Implications for the host-side scaffold

### 7.1 What is load-bearing

- **Reading `shared.flags` before writing hostready** is the upstream contract. Our scaffold skips it. This is the single biggest source of "fw wakes in the wrong state."
- **`brcmf_pcie_intr_enable` (writing MAILBOXMASK=0xFF0300 on the host side) is independent of fw-side unmasking.** It controls whether device-to-host IRQs are delivered. It does not enable anything on the fw side. Writing it early is benign.
- **`brcmf_pcie_hostready` (writing H2D_MAILBOX_1 = 1) is the thing that can wake fw.** Writing it while fw has not yet run `pcidongle_probe` → `hndrte_add_isr` is the hazardous case.

### 7.2 What the ISR needs from shared memory

pciedngl_isr assumes:

- `pciedev_info*` (the arg) is fully populated, including `+0x18 → sub-struct → +0x18 → HW-shadow struct` with ISR_STATUS at `+0x20`. (Blob-initialized value at +0x18 is 0 — it *must* be populated at runtime by pciedngl_probe.)
- A message pool is reachable via `*(sub-struct+0x20)` for the malloc at 0x4E20.
- A dngl_dev_ioctl entry point is set up at `*(sub-struct+0x14)` — this is the call at 0x20D8.

If fw hasn't completed `pcidongle_probe`, these are zero / uninitialized, and the ISR will crash on the first deref. A crash in the fw ARM inside the ISR path is consistent with the silent late-ladder wedge we see: no kernel panic, no AER, no console advance — fw's bus activity stops and the host eventually falls off the bus.

### 7.3 Concrete scaffold-design recommendations

1. **Gate hostready on `shared.flags & 0x10000000`**. Either:
   - Poll the sharedram_addr slot at `ramsize-4` until it becomes non-zero, read `flags` at `sharedram_addr + 0`, and only call `brcmf_pcie_hostready` after `HOSTRDY_DB1` is observed; OR
   - Read a debug-ring sentinel that indicates `pcidongle_probe` has completed, and only then ring the doorbell.
2. **Probe-order invariant**: `brcmf_pcie_intr_enable` is safe to call at any time after `pci_enable_msi` + `request_irq`. **Do not** call `brcmf_pcie_hostready` without the above gate.
3. **Add a T270-class observation probe** (not a new scaffold) that samples `sharedram_addr` and `shared.flags` at each dwell tick. If `HOSTRDY_DB1` is never observed across a full 120 s ladder, fw is blocked somewhere before `pcidongle_probe`'s ring setup — and the real "why the scaffold wedges host" question is not ISR-side but probe-side (fw never gets to the point where the doorbell would be safe to ring).
4. **Defer the T270 scaffold rewrite** until the sharedram observation above either confirms or refutes "fw reached ring-init." T258–T269 all rang the doorbell blind; changing that blind-ring to gated-ring is the smallest next change with the highest information value.

### 7.4 What this analysis does NOT settle

- Whether the fw actually reaches pcidongle_probe within the 120 s ladder — static analysis cannot tell us this; requires sharedram polling (see 7.3.3).
- Which specific sub-field inside `pciedev_info` the ISR NULL-derefs when rung prematurely — the blob's blob-image values at 0x58CC4+{0x18,0x14} are zero, but runtime state may differ based on how far fw got through init.
- Whether the fw-side MAILBOXINT FN0_0 bit is edge- or level-sensitive (i.e. does an early host doorbell latch or vanish). This is a HW property not derivable from the blob.
- Which of the 9 thunks in the 0x99AC..0x99C8 vector maps to the PCIe FN0 class specifically — it's class-specific, dispatched via `*(ctx+0xCC)` (the class index). Determining which index the pciedngl class uses would require reading `*(0x6296C)+0xCC` from live hardware, or tracing backward from the 0x28xx handler bodies.

## 8. Artifacts produced by this analysis

- `phase6/t269_disasm.py` — ctypes wrapper around libcapstone.so (the nix capstone Python binding referenced in prior scripts is no longer present in /nix/store, this restores disasm for future T269+ work).
- `phase6/t269_locate_isr.py` — list walk + prologue check for node[0].
- `phase6/t269_isr_prologue.py` — full pciedngl_isr + 0x9936 disasm, arg-struct decode.
- `phase6/t269_mailbox_search.py` — literal / string search for register offsets, MAILBOXMASK values, and watchdog/panic strings.
- `phase6/t269_regtable_decode.py` — ruled out "MAILBOXINT=0x48 / MAILBOXMASK=0x4C literal" as false positive (WLRPC ID enum); showed pciedev struct vtable at 0x58CF4..0x58CFC.
- `phase6/t269_hndrte_add_isr.py` — refs to pciedngl_isr fn-ptr 0x1C99, deadman_to string, ramstbydis, 'hndrte_add_isr failed'; and disasm of pcidongle_probe (0x1E90) + scheduler (0x115C).
- `phase6/t269_add_isr_body.py` — disasm of `hndrte_add_isr` (0x63C24) and the deadman fault-dump handler (0x63EE4).
- `phase6/t269_hw_enable.py` — disasm of 0x99AC/0x9940/0x9944/0x9956/0x9990/0x1A8C/0x1BA4/0x1298 + vector table region 0x00..0x80.

## 9. Clean-room posture

All code listings in this document are short and illustrative; no complete reconstructed function bodies are checked in. Behavior is described in plain language. Exact instruction sequences used for identification (prologue + ASCII string cross-reference + literal-pool resolution) remain in the helper scripts, which disassemble the vendor blob locally and print to stdout — they are analysis tools, not derived-work source.
