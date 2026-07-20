#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

printf 'Probing STM32F407 through Horco CMSIS-DAPv2/OpenOCD. This does not erase or program flash.\n'

"${OPENOCD_BIN}" \
  -s "${OPENOCD_SCRIPTS}" \
  -f openocd/stm32f407-horco-cmsis-dap-v2-no-srst.cfg \
  -c "init; targets; shutdown"
