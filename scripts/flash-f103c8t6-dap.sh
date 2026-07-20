#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/flash-f103c8t6-dap.sh [--dry-run] <f103-firmware.elf|hex|bin> [bin_flash_address]

Examples:
  scripts/flash-f103c8t6-dap.sh /path/to/f103_app.elf
  scripts/flash-f103c8t6-dap.sh /path/to/f103_app.hex
  scripts/flash-f103c8t6-dap.sh /path/to/f103_app.bin
  scripts/flash-f103c8t6-dap.sh /path/to/f103_app.bin 0x08000000
  scripts/flash-f103c8t6-dap.sh --dry-run /path/to/f103_app.elf

Notes:
  - This script is only for STM32F103C8T6 via CMSIS-DAP/SWD.
  - It never builds or flashes the STM32F407 ANO_LX firmware.
  - For .bin files, the flash address defaults to 0x08000000.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f103c8t6-cmsis-dap-low-speed-no-srst.cfg"
DEFAULT_BIN_FLASH_ADDRESS="0x08000000"
DRY_RUN=0

require_file() {
  local path="$1"
  local label="$2"

  if [[ ! -e "${path}" ]]; then
    printf 'ERROR: missing %s: %s\n' "${label}" "${path}" >&2
    return 1
  fi
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--dry-run" ]]; then
  DRY_RUN=1
  shift
fi

if (( $# < 1 || $# > 2 )); then
  usage >&2
  exit 2
fi

FIRMWARE="$1"
BIN_FLASH_ADDRESS="${2:-${DEFAULT_BIN_FLASH_ADDRESS}}"

require_file "${OPENOCD_BIN}" "OpenOCD"
require_file "${OPENOCD_SCRIPTS}/interface/cmsis-dap.cfg" "OpenOCD CMSIS-DAP config"
require_file "${OPENOCD_SCRIPTS}/target/stm32f1x.cfg" "OpenOCD STM32F1 target config"
require_file "${OPENOCD_CFG}" "STM32F103C8T6 OpenOCD config"
require_file "${FIRMWARE}" "STM32F103C8T6 firmware"

FIRMWARE_ABS="$(realpath "${FIRMWARE}")"
if [[ "${FIRMWARE_ABS}" == *"}"* ]]; then
  printf 'ERROR: firmware path cannot contain "}" because OpenOCD uses Tcl braces: %s\n' "${FIRMWARE_ABS}" >&2
  exit 2
fi

FIRMWARE_LOWER="$(printf '%s' "${FIRMWARE_ABS}" | tr '[:upper:]' '[:lower:]')"

case "${FIRMWARE_LOWER}" in
  *.elf|*.hex)
    if (( $# == 2 )); then
      printf 'ERROR: flash address is only accepted for .bin firmware files.\n' >&2
      exit 2
    fi
    PROGRAM_CMD="program {${FIRMWARE_ABS}} verify reset exit"
    ;;
  *.bin)
    PROGRAM_CMD="program {${FIRMWARE_ABS}} ${BIN_FLASH_ADDRESS} verify reset exit"
    ;;
  *)
    printf 'ERROR: unsupported firmware type. Use .elf, .hex, or .bin: %s\n' "${FIRMWARE_ABS}" >&2
    exit 2
    ;;
esac

printf 'Flashing STM32F103C8T6 through CMSIS-DAP/OpenOCD at 1000 kHz without SRST.\n'
printf 'Firmware: %s\n' "${FIRMWARE_ABS}"

OPENOCD_CMD=(
  "${OPENOCD_BIN}"
  -s "${OPENOCD_SCRIPTS}"
  -f "${OPENOCD_CFG}"
  -c "${PROGRAM_CMD}"
)

if (( DRY_RUN )); then
  printf 'Dry run only; OpenOCD was not started.\n'
  printf 'Command:'
  printf ' %q' "${OPENOCD_CMD[@]}"
  printf '\n'
  exit 0
fi

"${OPENOCD_CMD[@]}"
