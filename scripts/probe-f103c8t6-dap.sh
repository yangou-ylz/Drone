#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
OPENOCD_CFG="${PROJECT_ROOT}/openocd/stm32f103c8t6-cmsis-dap-low-speed-no-srst.cfg"

require_file() {
  local path="$1"
  local label="$2"

  if [[ ! -e "${path}" ]]; then
    printf 'ERROR: missing %s: %s\n' "${label}" "${path}" >&2
    return 1
  fi
}

require_file "${OPENOCD_BIN}" "OpenOCD"
require_file "${OPENOCD_SCRIPTS}/interface/cmsis-dap.cfg" "OpenOCD CMSIS-DAP config"
require_file "${OPENOCD_SCRIPTS}/target/stm32f1x.cfg" "OpenOCD STM32F1 target config"
require_file "${OPENOCD_CFG}" "STM32F103C8T6 OpenOCD config"

printf 'Probing STM32F103C8T6 through CMSIS-DAP/OpenOCD at 1000 kHz without SRST. This does not erase or program flash.\n'

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f "${OPENOCD_CFG}" \
  -c "init; targets; shutdown"
