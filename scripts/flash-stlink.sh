#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/flash-stlink.sh [--dry-run] [--hla] <target> <firmware.elf|hex|bin> [bin_flash_address]

Targets:
  f103c8t6   STM32F103C8T6 / Blue Pill class boards
  f407       STM32F407 family boards

Examples:
  scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.elf
  scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.hex
  scripts/flash-stlink.sh f103c8t6 /path/to/f103_app.bin
  scripts/flash-stlink.sh f407 build-gcc/ANO_LX.hex
  scripts/flash-stlink.sh --dry-run f103c8t6 /path/to/f103_app.elf
  scripts/flash-stlink.sh --hla f103c8t6 /path/to/f103_app.elf

Notes:
  - This is the ST-Link route only. Existing DAP/J-Link scripts are separate.
  - This script never builds firmware automatically; pass the exact file to flash.
  - For .bin files, the flash address defaults to 0x08000000.
  - Use --hla only if the default ST-Link backend fails with very old firmware.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
DEFAULT_BIN_FLASH_ADDRESS="0x08000000"
DRY_RUN=0
STLINK_BACKEND="direct"

require_file() {
  local path="$1"
  local label="$2"

  if [[ ! -e "${path}" ]]; then
    printf 'ERROR: missing %s: %s\n' "${label}" "${path}" >&2
    return 1
  fi
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
    --hla)
      STLINK_BACKEND="hla"
      shift
      ;;
    --)
      shift
      break
      ;;
    -*)
      printf 'ERROR: unsupported option: %s\n\n' "${1}" >&2
      usage >&2
      exit 2
      ;;
    *)
      break
      ;;
  esac
done

if (( $# < 2 || $# > 3 )); then
  usage >&2
  exit 2
fi

TARGET="$1"
FIRMWARE="$2"
BIN_FLASH_ADDRESS="${3:-${DEFAULT_BIN_FLASH_ADDRESS}}"

case "${TARGET}" in
  f103|f103c8t6|stm32f103c8t6)
    TARGET_LABEL="STM32F103C8T6"
    if [[ "${STLINK_BACKEND}" == "hla" ]]; then
      OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f103c8t6-stlink-hla-low-speed-no-srst.cfg"
    else
      OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f103c8t6-stlink-low-speed-no-srst.cfg"
    fi
    ;;
  f407|stm32f407)
    TARGET_LABEL="STM32F407"
    if [[ "${STLINK_BACKEND}" == "hla" ]]; then
      OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f407-stlink-hla-low-speed-no-srst.cfg"
    else
      OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f407-stlink-low-speed-no-srst.cfg"
    fi
    ;;
  *)
    printf 'ERROR: unsupported target: %s\n\n' "${TARGET}" >&2
    usage >&2
    exit 2
    ;;
esac

require_file "${OPENOCD_BIN}" "OpenOCD"
require_file "${OPENOCD_SCRIPTS}/interface/stlink.cfg" "OpenOCD ST-Link config"
require_file "${OPENOCD_SCRIPTS}/interface/stlink-hla.cfg" "OpenOCD ST-Link HLA config"
require_file "${OPENOCD_CFG}" "${TARGET_LABEL} ST-Link OpenOCD config"
require_file "${FIRMWARE}" "${TARGET_LABEL} firmware"

FIRMWARE_ABS="$(realpath "${FIRMWARE}")"
F407_DEFAULT_PREFIX="${PROJECT_ROOT}/build-gcc/ANO_LX."
if [[ "${TARGET_LABEL}" == "STM32F103C8T6" && "${FIRMWARE_ABS}" == "${F407_DEFAULT_PREFIX}"* ]]; then
  printf 'ERROR: refusing to flash the F407 ANO_LX build output into STM32F103C8T6: %s\n' "${FIRMWARE_ABS}" >&2
  exit 2
fi

if [[ "${FIRMWARE_ABS}" == *"}"* ]]; then
  printf 'ERROR: firmware path cannot contain "}" because OpenOCD uses Tcl braces: %s\n' "${FIRMWARE_ABS}" >&2
  exit 2
fi

FIRMWARE_LOWER="$(printf '%s' "${FIRMWARE_ABS}" | tr '[:upper:]' '[:lower:]')"

case "${FIRMWARE_LOWER}" in
  *.elf|*.hex)
    if (( $# == 3 )); then
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

printf 'Flashing %s through ST-Link/OpenOCD (%s backend) at 1000 kHz without SRST.\n' "${TARGET_LABEL}" "${STLINK_BACKEND}"
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
