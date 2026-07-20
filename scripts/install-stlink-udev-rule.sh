#!/usr/bin/env bash
set -euo pipefail

RULE_PATH="/etc/udev/rules.d/60-stlink-local.rules"
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage:
  scripts/install-stlink-udev-rule.sh [--dry-run]

Options:
  --dry-run   Print the udev rules without writing /etc/udev/rules.d.
EOF
}

emit_rules() {
  cat <<'EOF'
# Local ST-Link rules for OpenOCD.
# ST-LINK/V1, ST-LINK/V2, ST-LINK/V2-1, and STLINK-V3 common VID:PID pairs.
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3744", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3748", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374b", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374d", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374e", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="374f", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3752", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3753", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3754", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3755", MODE="0666", GROUP="plugdev", TAG+="uaccess"
SUBSYSTEM=="usb", ATTR{idVendor}=="0483", ATTR{idProduct}=="3757", MODE="0666", GROUP="plugdev", TAG+="uaccess"
EOF
}

while (( $# > 0 )); do
  case "${1}" in
    -h|--help)
      usage
      exit 0
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      printf 'ERROR: unsupported option: %s\n\n' "${1}" >&2
      usage >&2
      exit 2
      ;;
  esac
done

cat <<EOF
This installs local udev rules for ST-Link USB access:
  ${RULE_PATH}

It will use sudo and may ask for your Ubuntu password.
EOF

if (( DRY_RUN )); then
  printf '\nDry run only; not writing %s.\n\n' "${RULE_PATH}"
  emit_rules
  exit 0
fi

emit_rules | sudo tee "${RULE_PATH}" >/dev/null

sudo udevadm control --reload-rules
sudo udevadm trigger

cat <<EOF

ST-Link udev rules installed.
Unplug and replug the ST-Link, then run:
  ./scripts/check-stlink.sh
EOF
