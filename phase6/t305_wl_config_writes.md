# T305-followup: wl.ko config-space writes — call graph from wl_pci_probe

**Date:** 2026-04-28
**Method:** Direct disasm + reloc table walk (no subagent — n=4 fabrication caveat applies to closed x86-64 binaries). Source data: `/run/booted-system/kernel-modules/lib/modules/6.12.80/kernel/net/wireless/wl.ko` (broadcom-sta 6.30.223.271-59).

## Premise

GLM/Kilo document `t305_glm51_options.md` claimed bcmdhd uses PCI config space (not BAR0 MMIO) for interrupt masking on older PCIe core revisions, and recommended writing `PCIIntmask = 0x3` from brcmfmac. This task verifies (a) what config-space writes wl.ko actually makes, (b) which are reachable from `wl_pci_probe` during BCM4360 init.

## Findings

### Total config-space write surface in wl.ko

31 sites of `osl_pci_write_config(osh, offset, size, value)` calls (Broadcom OSL wrapper around `pci_write_config_dword`). Identified via reloc table grep: `osl_pci_write_config` symbol at `.text+0x181520`.

For comparison: brcmfmac's `phase5/work/.../pcie.c` has zero config-space writes outside `BRCMF_PCIE_BAR0_WINDOW` (offset 0x80) backplane core switching.

### Write sites by containing function (offsets identified from preceding `mov esi, X` instructions)

| Site (file offset of e8 opcode) | Containing function | esi (offset) | Notes |
|---|---|---|---|
| 0x1cc6, 0x1d05 | `ai_setcoreidx` | rdi (variable, BAR0 base) | Backplane window switch |
| 0x1f89 | `ai_scan` | (chip enumeration) | Scan path |
| 0x17e2d | `pcie_configspace_restore` | rbx 0..0xfc loop | Restore-after-suspend |
| 0x17ee5 | `pcie_lcreg` | r12b | PCIe LCR cap chain access |
| 0x17fc2 | `pcie_set_maxpayload_size` | r12d | PCIe device control RMW |
| 0x18039 | `pcie_obffenable` | r12d | OBFF cap RMW |
| 0x180b6 | `pcie_ltrenable` | r12d | LTR cap RMW |
| 0x18131 | `pcie_clkreq` | r12d | ClkReq cap RMW |
| 0x18457 | `pcicore_pmeclr` | esi+4 | PME area RMW |
| 0x184aa | `pcicore_pmestatclr` | esi+4 | PME area RMW |
| 0x184fa | `pcicore_pmeen` | esi+4 | PME area RMW |
| 0x185b0 | `pcicore_pmeen` (continuation) | esi+4 | PME area RMW |
| 0x18a5a | `pcie_set_L1substate` | r12d | L1 substate cap RMW |
| 0x19082 | `pcicore_sleep` | r12d | Sleep config |
| **0x1941a** | **`pcicore_hwup`** | **0xc** | **Cache-line-size set OR 0x40** |
| 0x196b2 | `pcicore_hwup`+0x372 | r12d | Second hwup write |
| 0x1c61e | `sb_core_reset` | 0x80 | BAR0 window switch |
| **0x1e614** | **`si_clkctl_xtal`** | **0xb4** | **PMU/clock crystal RMW** |
| **0x1e62b** | **`si_clkctl_xtal`** | **0xb8** | **PMU/clock crystal RMW** |
| **0x1e653** | **`si_clkctl_xtal`** | **0xb4** | **2nd 0xB4 write (RMW + AND 0x7f)** |
| 0x1e689 | `si_clkctl_xtal` | (continuation) | RMW |
| **0x1e6a0** | **`si_clkctl_xtal`** | **0xb8** | **2nd 0xB8 write** |
| 0x1e74a | `si_ldo_war` | 0x80 (val=0x18000000) | BAR0→chipcommon |
| 0x1e7cd | `si_ldo_war` | 0x80 (restore) | BAR0 restore |
| 0x1fa6f | `si_survive_perst_war` | 0x80 | BAR0 window |
| **0x2165d** | **`si_pci_setup`** | **0x94** | **Vendor PCI setup RMW (eax \| r14d)** |
| 0x22bc1 | `si_muxenab` | 0x80 (val=0x18000000) | BAR0→chipcommon |

### Reachability from `wl_pci_probe`

Static call graph trace via reloc table reverse lookup:

#### Chain 1: `wl_pci_probe → wlc_attach`
Confirmed via `.rela.init.text` reloc at `.init.text+0x3e2` → `wlc_attach`. 

```
wl_pci_probe (.init.text + 0xC0, size 1491)
└── wlc_attach (at .text + 0x37D10, size 6639) at .init.text+0x3E2
```

#### Chain 2: `wlc_attach → wlc_bmac_attach → config writes`
Reverse-grep of relocs targeting `wlc_bmac_attach`:
- caller `wlc_attach @ +0x27f` (single call site)

`wlc_bmac_attach` callees (relevant config-write paths):
- `wlc_bmac_xtal @ +0x10f7` → `si_clkctl_xtal` → **config 0xB4 + 0xB8**
- `si_pcieobffenable @ +0x2b9` → `pcie_obffenable` → cap chain
- `si_pcieltrenable @ +0x291` → `pcie_ltrenable` → cap chain

**Implication:** during `wl_pci_probe → wlc_attach`, wl writes config 0xB4 + 0xB8 (PMU/clock crystal) BEFORE firmware download/boot. This happens in our wlc_attach failure path too — so the writes are attempted even when wl fails downstream. (Cannot directly observe in our cycle1+1b runs since wl failed at module init before reaching probe.)

#### Chain 3: `wl_up → wlc_up → wlc_bmac_hw_up → config writes`
Reverse-grep:
- `wl_up.part.0` → `wlc_up @ +0x14`
- `wlc_up @ +0x42` → `wlc_bmac_hw_up`
- `wlc_bmac_hw_up` callees:
  - `wlc_bmac_xtal @ +0xb4` → `si_clkctl_xtal` → **config 0xB4 + 0xB8 again**
  - `si_pci_fixcfg @ +0x121` → `pcicore_hwup` → **config 0xC** (cache line) + others
  - `si_ldo_war @ +0x50` → **config 0x80 (BAR0 → chipcommon)**
  - `si_survive_perst_war @ +0x3b` → **config 0x80**
  - `wlc_bmac_4360_pcie2_war @ +0x115` → BCM4360-SPECIFIC workaround (calls `si_pcie_configspace_restore`)

#### Chain 4: `wl_up → wlc_up → wlc_bmac_up_prep → config writes`
- `wlc_up @ +0x107` → `wlc_bmac_up_prep`
- `wlc_bmac_up_prep` callees:
  - `si_pci_setup @ +0x85` → **config 0x94 RMW (sets bit pattern in r14d)**
  - `si_pci_up @ +0xec` → `pcicore_up` → ...

### Notable absences

**No `PCIIntmask = 0x3` write anywhere in wl.ko.** Searched for `mov ecx, 0x3` followed by `osl_pci_write_config` — zero matches. The GLM/Kilo document's specific recommendation does not match what wl actually does.

**No write at offset 0x48 (would correspond to bcmdhd's `PCIMailBoxInt`)** in any wl.ko function. Pending bcmdhd cross-reference (subagent B).

### Cross-reference to brcmfmac

`grep -nE 'pci_write_config' phase5/work/.../pcie.c` confirms brcmfmac's only config writes are at `BRCMF_PCIE_BAR0_WINDOW` (offset 0x80) — backplane core switching. **No writes at 0x94, 0xb4, 0xb8.**

### `wlc_bmac_4360_pcie2_war` — BCM4360-specific carve-out

Direct hit on our chip ID. Function at `wlc_bmac_4360_pcie2_war` (798 bytes per nm), calls `si_pcie_configspace_restore` at +0x18e. Worth disassembling further to see what BCM4360-specific config-space behavior wl encodes — likely a known erratum workaround.

## Verdict on GLM/Kilo document

Document's HEADLINE ("PCIIntmask = 0x3 in PCI config space") is **wrong** for our chip — no such write exists in wl.ko.

Document's UNDERLYING DIRECTION ("vendor config space writes during init are unexplored and brcmfmac doesn't make them") is **correct**. Three concrete gaps:

1. **0xB4 + 0xB8 (`si_clkctl_xtal`)** — clock crystal control. Written during BOTH `wlc_attach` (probe time, before fw boot) AND `wlc_bmac_hw_up` (interface up time). Multiple sites suggests careful state machine.
2. **0x94 (`si_pci_setup`)** — vendor PCI setup RMW. Written during `wlc_bmac_up_prep` (interface up).
3. **PCIe cap chain** (LTR, OBFF, ClkReq, PME, L1substate) — wl programs these via cap chain config writes during `wlc_bmac_attach`. brcmfmac relies on kernel defaults. Less likely to be wake-related but possible.

`wlc_bmac_4360_pcie2_war` is a known BCM4360-specific function that should be inspected separately for any chip-specific config writes we'd otherwise miss.

## Next steps

- **C — T306 read-only probe** (already coded + built): reads config 0x40..0xFF at pre-write / post-set_active / post-T276-poll stages. Tells us what brcmfmac LEAVES at these offsets without writing — baseline for whether the wl-target offsets need touching, and whether they change naturally during fw boot.
- **B — bcmdhd cross-reference** (in progress, parallel subagent): corroborate against open-source bcmdhd; see if bcmdhd's BCM4360 init writes match wl's pattern or differs.
- **Future — disassemble `wlc_bmac_4360_pcie2_war`** to extract BCM4360-specific config-space WAR sequence verbatim. Clean-room implementation in brcmfmac would follow.

## Caveats

- All call-graph claims are based on direct-BL relocs only. Indirect dispatch (via function pointers / ops vtables) is NOT covered. Same heuristic limitation as ARM Thumb BFS analysis (KEY_FINDINGS row 161).
- Reachability from `wl_pci_probe` is established for `wlc_attach` → `wlc_bmac_attach`. The deeper chains (to `si_clkctl_xtal` etc.) are inferred from direct-BL caller chains; verified only that the chain exists, not that it executes UNCONDITIONALLY for BCM4360.
- We have NO runtime evidence of these writes happening (wl fails to load on our kernel — see KEY_FINDINGS wl-closure row).

## Source/method log

- Reloc enumeration: `readelf -Wr wl.ko` → `/tmp/wl_relocs_all.txt` (46310 lines)
- Function table: `readelf -sW wl.ko` filtered to FUNC + section 1 → `/tmp/wl_funcs2.txt` (2907 functions)
- Disasm: `objdump -d -M intel wl.ko` → `/tmp/wl_full_disasm.s` (429252 lines)
- Caller mapping: shell awk over relocs targeting suspect symbols, then awk-mapped to containing function via address ranges.
