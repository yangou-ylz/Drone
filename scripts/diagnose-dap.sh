#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/dap-diagnostics-$(date +%Y%m%d-%H%M%S).log"

{
  printf 'STM32F407 DAP diagnostics\n'
  printf 'Generated at: %s\n\n' "$(date -Is)"

  printf '== System ==\n'
  uname -a
  lsb_release -a 2>/dev/null || true
  id
  printf '\n'

  printf '== Tools ==\n'
  command -v cmake || true
  cmake --version 2>/dev/null | head -1 || true
  command -v ninja || true
  ninja --version 2>/dev/null || true
  command -v arm-none-eabi-gcc || true
  arm-none-eabi-gcc --version 2>/dev/null | head -1 || true
  printf 'OpenOCD: %s\n' "${OPENOCD_BIN}"
  "${OPENOCD_BIN}" --version 2>&1 | head -4 || true
  printf '\n'

  printf '== Project Outputs ==\n'
  ls -lh build-gcc/ANO_LX.elf build-gcc/ANO_LX.hex build-gcc/ANO_LX.bin 2>/dev/null || true
  printf '\n'

  printf '== USB Devices ==\n'
  lsusb || true
  printf '\n'

  printf '== DAP Keyword Scan ==\n'
  lsusb | grep -Ei 'cmsis|dap|debug|hid|arm|st-link|stlink|wch|j-link|jlink' || true
  printf '\n'

  printf '== Kernel Messages: recent USB lines ==\n'
  dmesg --ctime 2>/dev/null | grep -Ei 'usb|hid|cmsis|dap|stlink|jlink|debug' | tail -80 || true
  printf '\n'

  printf '== OpenOCD Config Parse ==\n'
  "${OPENOCD_BIN}" \
    -s "${OPENOCD_SCRIPTS}" \
    -f openocd/stm32f407-cmsis-dap.cfg \
    -c 'exit' 2>&1 || true
  printf '\n'

  printf '== Notes ==\n'
  printf 'This script is read-only except for writing this project-local log file.\n'
  printf 'It does not install packages, change udev rules, erase flash, or program the target.\n'
} | tee "${LOG_FILE}"

printf '\nSaved diagnostic log: %s\n' "${LOG_FILE}"
