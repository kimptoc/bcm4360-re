KDIR ?= /lib/modules/$(shell uname -r)/build
BRCM_SRC := $(src)/brcm80211/brcmfmac

obj-m += brcmfmac.o

brcmfmac-y += $(BRCM_SRC)/core.o
brcmfmac-y += $(BRCM_SRC)/bus.o
brcmfmac-y += $(BRCM_SRC)/proto.o
brcmfmac-y += $(BRCM_SRC)/common.o
brcmfmac-y += $(BRCM_SRC)/firmware.o

all:
	$(MAKE) -C $(KDIR) M=$(PWD) modules

clean:
	$(MAKE) -C $(KDIR) M=$(PWD) clean
