#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

ARM_GCC_DIR="/opt/gcc-arm-none-eabi-9-2020-q2-update/bin"
OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"

export PATH="${ARM_GCC_DIR}:${PATH}"

require_file() {
  local path="$1"
  local label="$2"

  if [[ ! -e "${path}" ]]; then
    printf 'ERROR: missing %s: %s\n' "${label}" "${path}" >&2
    return 1
  fi
}

require_file "${ARM_GCC_DIR}/arm-none-eabi-gcc" "Arm GCC"
require_file "${OPENOCD_BIN}" "OpenOCD"
require_file "${OPENOCD_SCRIPTS}/interface/cmsis-dap.cfg" "OpenOCD CMSIS-DAP config"
require_file "${OPENOCD_SCRIPTS}/target/stm32f4x.cfg" "OpenOCD STM32F4 target config"

