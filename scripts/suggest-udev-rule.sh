#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

printf 'This script only prints suggested udev rules. It does not write /etc/udev/rules.d and does not use sudo.\n\n'

mapfile -t DEVICES < <(lsusb | rg -i 'cmsis|dap|debug|hid|arm|st-link|stlink|wch|j-link|jlink' || true)

if [[ "${#DEVICES[@]}" -eq 0 ]]; then
  printf 'No obvious DAP/CMSIS-DAP/debug probe found in lsusb.\n'
  printf 'Run ./scripts/check-dap.sh after plugging in the DAP.\n'
  exit 0
fi

printf 'Candidate debug probe USB devices:\n'
printf '%s\n' "${DEVICES[@]}"
printf '\nSuggested udev rule candidates:\n'

for line in "${DEVICES[@]}"; do
  if [[ "${line}" =~ ID[[:space:]]+([0-9a-fA-F]{4}):([0-9a-fA-F]{4}) ]]; then
    vendor="${BASH_REMATCH[1],,}"
    product="${BASH_REMATCH[2],,}"
    printf '\n# From: %s\n' "${line}"
    printf 'SUBSYSTEM=="usb", ATTR{idVendor}=="%s", ATTR{idProduct}=="%s", MODE="0666", GROUP="plugdev", TAG+="uaccess"\n' "${vendor}" "${product}"
  fi
done

cat <<'EOF'

If OpenOCD reports USB permission errors, confirm before applying a rule like:

  sudo tee /etc/udev/rules.d/60-cmsis-dap-local.rules
  sudo udevadm control --reload-rules
  sudo udevadm trigger

Do not apply rules blindly. Use the exact VID:PID from your DAP.
EOF

