#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

if [[ ! -f build-gcc/ANO_LX.elf ]]; then
  printf 'build-gcc/ANO_LX.elf is missing; building first.\n'
  "${SCRIPT_DIR}/build.sh"
fi

printf 'Flashing STM32F407 through CMSIS-DAP/OpenOCD using the verified no-SRST profile.\n'

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f openocd/stm32f407-cmsis-dap-low-speed-no-srst.cfg \
  -c "program build-gcc/ANO_LX.elf verify reset exit"
