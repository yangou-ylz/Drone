#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

LOG_DIR="${PROJECT_ROOT}/logs"
mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/local-env-verify-$(date +%Y%m%d-%H%M%S).log"

run_step() {
  local title="$1"
  shift

  printf '\n== %s ==\n' "${title}"
  "$@"
}

{
  printf 'STM32F407 local environment verification\n'
  printf 'Generated at: %s\n' "$(date -Is)"
  printf 'Project: %s\n' "${PROJECT_ROOT}"
  printf 'OpenOCD: %s\n\n' "${OPENOCD_BIN}"

  run_step "Tool versions" bash -c '
    cmake --version | head -1
    ninja --version
    arm-none-eabi-gcc --version | head -1
    "'"${OPENOCD_BIN}"'" --version 2>&1 | head -4
  '

  run_step "Shell script syntax" bash -c '
    for s in scripts/*.sh; do
      bash -n "$s"
      printf "ok: %s\n" "$s"
    done
  '

  run_step "VS Code JSON validation" bash -c '
    if command -v node >/dev/null 2>&1; then
      node -e "for (const f of [\".vscode/settings.json\", \".vscode/tasks.json\", \".vscode/launch.json\", \".vscode/extensions.json\"]) { JSON.parse(require(\"fs\").readFileSync(f, \"utf8\")); console.log(\"ok: \" + f); }"
    else
      printf "node not found; skipping JSON validation\n"
    fi
  '

  run_step "CMake configure and build" "${SCRIPT_DIR}/build.sh"

  run_step "OpenOCD default config parse" "${OPENOCD_BIN}" \
    -s "${OPENOCD_SCRIPTS}" \
    -f openocd/stm32f407-cmsis-dap.cfg \
    -c "exit"

  run_step "OpenOCD low-speed config parse" "${OPENOCD_BIN}" \
    -s "${OPENOCD_SCRIPTS}" \
    -f openocd/stm32f407-cmsis-dap-low-speed-no-srst.cfg \
    -c "exit"

  run_step "Build outputs" ls -lh \
    build-gcc/ANO_LX.elf \
    build-gcc/ANO_LX.hex \
    build-gcc/ANO_LX.bin \
    build-gcc/ANO_LX.map

  run_step "DAP visibility, non-fatal" bash -c '
    lsusb
    if lsusb | rg -i "cmsis|dap|debug|hid|arm|st-link|stlink|wch|j-link|jlink"; then
      printf "\nDAP/debug-probe candidate visible.\n"
    else
      printf "\nNo obvious DAP/CMSIS-DAP/debug probe currently visible. Hardware validation remains pending.\n"
    fi
  '

  printf '\nLocal environment verification complete.\n'
  printf 'Hardware flashing is still a separate user acceptance step.\n'
} 2>&1 | tee "${LOG_FILE}"

printf '\nSaved local environment verification log: %s\n' "${LOG_FILE}"

