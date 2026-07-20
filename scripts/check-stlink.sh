#!/usr/bin/env bash
set -euo pipefail

RULE_PATH="/etc/udev/rules.d/60-stlink-local.rules"
STLINK_PATTERN='st-link|stlink|stmicroelectronics|0483:3744|0483:3748|0483:374b|0483:374d|0483:374e|0483:374f|0483:3752|0483:3753|0483:3754|0483:3755|0483:3757'

printf 'USB devices:\n'
lsusb

printf '\nST-Link keyword scan:\n'
if lsusb | grep -Ei "${STLINK_PATTERN}"; then
  printf '\nAn ST-Link-like USB device is visible above.\n'
else
  printf '\nNo obvious ST-Link device is currently visible.\n'
fi

printf '\nudev rule status:\n'
if [[ -f "${RULE_PATH}" ]]; then
  printf 'installed: %s\n' "${RULE_PATH}"
else
  printf 'not installed: %s\n' "${RULE_PATH}"
  printf 'install with: ./scripts/install-stlink-udev-rule.sh\n'
fi

printf '\nCurrent user groups:\n'
id -nG
if id -nG | tr ' ' '\n' | grep -qx 'plugdev'; then
  printf 'ok: current user is in plugdev\n'
else
  printf 'warning: current user is not in plugdev\n'
fi

cat <<'EOF'

Next checks:
  1. If udev was just installed, unplug and replug ST-Link.
  2. Run: ./scripts/probe-stlink.sh f103c8t6
  3. If an old ST-Link/V2 fails, try: ./scripts/probe-stlink.sh --hla f103c8t6
EOF
