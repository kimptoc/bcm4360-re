#!/usr/bin/env bash
# Restore pre-wl-test NixOS config and rebuild boot entry.
set -e
sudo cp /etc/nixos/configuration.nix.preWlMitigationTest /etc/nixos/configuration.nix
sudo nixos-rebuild boot
echo "Done. Reboot to return to mitigated kernel."
