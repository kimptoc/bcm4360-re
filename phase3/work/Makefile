KDIR ?= /nix/store/7nnvjff5glbhh2mygq08l2h6dw7f0cjz-linux-6.12.80-dev/lib/modules/6.12.80/build
BRCM_SRC := linux-6.12.80/drivers/net/wireless/broadcom/brcm80211/brcmfmac

ccflags-y += \
	-I $(src)/linux-6.12.80/drivers/net/wireless/broadcom/brcm80211/brcmfmac \
	-I $(src)/linux-6.12.80/drivers/net/wireless/broadcom/brcm80211/include

# Override kernel config: only build PCIe backend (no SDIO/USB)
# Force-include after autoconf.h to undef SDIO/USB, activating the stubs in bus.h
ccflags-y += -include $(src)/pcie_only.h

# Main brcmfmac module
obj-m += brcmfmac.o

brcmfmac-objs := \
	$(BRCM_SRC)/cfg80211.o \
	$(BRCM_SRC)/chip.o \
	$(BRCM_SRC)/fwil.o \
	$(BRCM_SRC)/fweh.o \
	$(BRCM_SRC)/p2p.o \
	$(BRCM_SRC)/proto.o \
	$(BRCM_SRC)/common.o \
	$(BRCM_SRC)/core.o \
	$(BRCM_SRC)/firmware.o \
	$(BRCM_SRC)/fwvid.o \
	$(BRCM_SRC)/feature.o \
	$(BRCM_SRC)/btcoex.o \
	$(BRCM_SRC)/vendor.o \
	$(BRCM_SRC)/pno.o \
	$(BRCM_SRC)/xtlv.o \
	$(BRCM_SRC)/bcdc.o \
	$(BRCM_SRC)/fwsignal.o \
	$(BRCM_SRC)/commonring.o \
	$(BRCM_SRC)/flowring.o \
	$(BRCM_SRC)/msgbuf.o \
	$(BRCM_SRC)/pcie.o \
	$(BRCM_SRC)/of.o \
	$(BRCM_SRC)/dmi.o \
	$(BRCM_SRC)/acpi.o

# WCC vendor module
obj-m += brcmfmac-wcc.o

brcmfmac-wcc-objs := \
	$(BRCM_SRC)/wcc/core.o \
	$(BRCM_SRC)/wcc/module.o

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
