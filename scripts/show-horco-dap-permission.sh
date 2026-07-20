#!/usr/bin/env bash
set -euo pipefail

dev_path="$(
  for p in /dev/bus/usb/*/*; do
    props="$(udevadm info -q property -n "${p}" 2>/dev/null || true)"
    if printf '%s\n' "${props}" | grep -q '^ID_VENDOR_ID=faed$' &&
       printf '%s\n' "${props}" | grep -q '^ID_MODEL_ID=4873$'; then
      printf '%s\n' "${p}"
      break
    fi
  done
)"

if [[ -z "${dev_path}" ]]; then
  printf 'Horco CMSIS-DAP faed:4873 is not currently visible.\n'
  printf 'Plug it in, then run: lsusb | grep -i dap\n'
  exit 1
fi

printf 'Horco CMSIS-DAP raw USB device: %s\n' "${dev_path}"
ls -l "${dev_path}"
printf '\nTemporary permission fix for this plug-in instance:\n'
printf '  sudo chmod 666 %q\n' "${dev_path}"
printf '\nPermanent udev rule:\n'
printf '  SUBSYSTEM=="usb", ATTR{idVendor}=="faed", ATTR{idProduct}=="4873", MODE="0666", GROUP="plugdev", TAG+="uaccess"\n'
