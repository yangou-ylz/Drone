#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

printf 'USB devices:\n'
lsusb

printf '\nDAP/debug-probe keyword scan:\n'
if lsusb | grep -Ei 'cmsis|dap|debug|hid|arm|st-link|stlink|wch|j-link|jlink'; then
  printf '\nA debug-probe-like USB device is visible above.\n'
else
  printf '\nNo obvious DAP/CMSIS-DAP/debug probe is currently visible.\n'
fi
