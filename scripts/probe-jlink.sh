#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

printf 'Probing STM32F407 through SEGGER J-Link/OpenOCD. This does not erase or program flash.\n'

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f openocd/stm32f407-jlink-low-speed-no-srst.cfg \
  -c "init; halt; flash probe 0; targets; shutdown"
