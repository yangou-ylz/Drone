#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

if [[ ! -f build-gcc/ANO_LX.hex ]]; then
  printf 'build-gcc/ANO_LX.hex is missing; building first.\n'
  "${SCRIPT_DIR}/build.sh"
fi

printf 'Flashing STM32F407 through SEGGER J-Link/OpenOCD using low-speed SWD no-SRST profile.\n'

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f openocd/stm32f407-jlink-low-speed-no-srst.cfg \
  -c "init; reset halt; sleep 100; halt; flash probe 0; flash write_image erase build-gcc/ANO_LX.hex; verify_image build-gcc/ANO_LX.hex; reset run; shutdown"
