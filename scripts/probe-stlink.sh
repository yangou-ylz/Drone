#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/probe-stlink.sh [--hla] <target>

Targets:
  f103c8t6   STM32F103C8T6 / Blue Pill class boards
  f407       STM32F407 family boards

This only connects to the target. It does not erase or program flash.

Options:
  --hla      Use deprecated HLA ST-Link backend for very old ST-Link/V2 firmware.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
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

if (( $# != 1 )); then
  usage >&2
  exit 2
fi

TARGET="$1"
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

printf 'Probing %s through ST-Link/OpenOCD (%s backend) at 1000 kHz without SRST. This does not erase or program flash.\n' "${TARGET_LABEL}" "${STLINK_BACKEND}"

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f "${OPENOCD_CFG}" \
  -c "init; halt; targets; shutdown"
