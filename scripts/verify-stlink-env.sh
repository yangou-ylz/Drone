#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/stlink-env-verify-$(date +%Y%m%d-%H%M%S).log"
TMP_DIR="${LOG_DIR}/stlink-verify-tmp-$(date +%Y%m%d-%H%M%S)"

mkdir -p "${LOG_DIR}" "${TMP_DIR}"
cd "${PROJECT_ROOT}"

run_step() {
  local title="$1"
  shift

  printf '\n== %s ==\n' "${title}"
  "$@"
}

require_file() {
  local path="$1"
  local label="$2"

  if [[ ! -e "${path}" ]]; then
    printf 'ERROR: missing %s: %s\n' "${label}" "${path}" >&2
    return 1
  fi
}

{
  printf 'STM32 ST-Link local environment verification\n'
  printf 'Generated at: %s\n' "$(date -Is)"
  printf 'Project: %s\n' "${PROJECT_ROOT}"
  printf 'OpenOCD: %s\n' "${OPENOCD_BIN}"
  printf 'Temporary dry-run files: %s\n\n' "${TMP_DIR}"

  run_step "Required files" bash -c '
    require_file() {
      if [[ ! -e "$1" ]]; then
        printf "ERROR: missing %s: %s\n" "$2" "$1" >&2
        return 1
      fi
      printf "ok: %s\n" "$1"
    }

    require_file "'"${OPENOCD_BIN}"'" "OpenOCD"
    require_file "'"${OPENOCD_SCRIPTS}"'/interface/stlink.cfg" "OpenOCD ST-Link config"
    require_file "'"${OPENOCD_SCRIPTS}"'/interface/stlink-hla.cfg" "OpenOCD ST-Link HLA config"
    require_file "'"${OPENOCD_SCRIPTS}"'/target/stm32f1x.cfg" "OpenOCD STM32F1 target config"
    require_file "'"${OPENOCD_SCRIPTS}"'/target/stm32f4x.cfg" "OpenOCD STM32F4 target config"
    require_file openocd/stm32f103c8t6-stlink-low-speed-no-srst.cfg "F103 ST-Link direct config"
    require_file openocd/stm32f103c8t6-stlink-hla-low-speed-no-srst.cfg "F103 ST-Link HLA config"
    require_file openocd/stm32f407-stlink-low-speed-no-srst.cfg "F407 ST-Link direct config"
    require_file openocd/stm32f407-stlink-hla-low-speed-no-srst.cfg "F407 ST-Link HLA config"
  '

  run_step "Tool versions" bash -c '
    "'"${OPENOCD_BIN}"'" --version 2>&1 | head -4
  '

  run_step "ST-Link shell script syntax" bash -c '
    for s in scripts/check-stlink.sh scripts/install-stlink-udev-rule.sh scripts/probe-stlink.sh scripts/flash-stlink.sh scripts/diagnose-stlink.sh scripts/verify-stlink-env.sh; do
      bash -n "$s"
      printf "ok: %s\n" "$s"
    done
  '

  run_step "udev installer dry-run" ./scripts/install-stlink-udev-rule.sh --dry-run

  run_step "OpenOCD ST-Link config parse" bash -c '
    set -euo pipefail
    for cfg in \
      openocd/stm32f103c8t6-stlink-low-speed-no-srst.cfg \
      openocd/stm32f103c8t6-stlink-hla-low-speed-no-srst.cfg \
      openocd/stm32f407-stlink-low-speed-no-srst.cfg \
      openocd/stm32f407-stlink-hla-low-speed-no-srst.cfg
    do
      printf "parse: %s\n" "$cfg"
      "'"${OPENOCD_BIN}"'" -s "'"${OPENOCD_SCRIPTS}"'" -f "$cfg" -c shutdown
    done
  '

  run_step "Flash command dry-runs" bash -c '
    set -euo pipefail
    : > "'"${TMP_DIR}"'/f103_app.elf"
    : > "'"${TMP_DIR}"'/f103_app.hex"
    : > "'"${TMP_DIR}"'/f103_app.bin"
    : > "'"${TMP_DIR}"'/f407_app.hex"

    ./scripts/flash-stlink.sh --dry-run f103c8t6 "'"${TMP_DIR}"'/f103_app.elf"
    ./scripts/flash-stlink.sh --dry-run --hla f103c8t6 "'"${TMP_DIR}"'/f103_app.hex"
    ./scripts/flash-stlink.sh --dry-run f103c8t6 "'"${TMP_DIR}"'/f103_app.bin"
    ./scripts/flash-stlink.sh --dry-run f407 "'"${TMP_DIR}"'/f407_app.hex"
    ./scripts/flash-stlink.sh --dry-run --hla f407 "'"${TMP_DIR}"'/f407_app.hex"
  '

  run_step "F103/F407 mix-up guard" bash -c '
    set -euo pipefail
    if [[ -f build-gcc/ANO_LX.hex ]]; then
      if ./scripts/flash-stlink.sh --dry-run f103c8t6 build-gcc/ANO_LX.hex >/tmp/stlink-mixup-guard.out 2>/tmp/stlink-mixup-guard.err; then
        printf "ERROR: mix-up guard did not reject build-gcc/ANO_LX.hex for f103c8t6\n" >&2
        exit 1
      fi
      cat /tmp/stlink-mixup-guard.err
      printf "ok: F407 build output is rejected for f103c8t6 target\n"
    else
      printf "build-gcc/ANO_LX.hex not present; skipping F407 output rejection test\n"
    fi
  '

  run_step "udev rule status, non-fatal" bash -c '
    if [[ -f /etc/udev/rules.d/60-stlink-local.rules ]]; then
      printf "installed: /etc/udev/rules.d/60-stlink-local.rules\n"
      sed -n "1,80p" /etc/udev/rules.d/60-stlink-local.rules
    else
      printf "not installed: /etc/udev/rules.d/60-stlink-local.rules\n"
      printf "Install with: ./scripts/install-stlink-udev-rule.sh\n"
    fi
  '

  run_step "ST-Link USB visibility, non-fatal" bash -c '
    lsusb
    if lsusb | grep -Ei "st-link|stlink|stmicroelectronics|0483:3744|0483:3748|0483:374b|0483:374d|0483:374e|0483:374f|0483:3752|0483:3753|0483:3754|0483:3755|0483:3757"; then
      printf "\nST-Link candidate visible.\n"
    else
      printf "\nNo obvious ST-Link currently visible. Hardware probe/flash remains pending.\n"
    fi
  '

  printf '\nST-Link local verification complete.\n'
  printf 'This verification did not erase or program flash.\n'
} 2>&1 | tee "${LOG_FILE}"

printf '\nSaved ST-Link verification log: %s\n' "${LOG_FILE}"
printf 'Dry-run placeholder files remain at: %s\n' "${TMP_DIR}"
