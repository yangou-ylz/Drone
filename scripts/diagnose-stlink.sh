#!/usr/bin/env bash
set -u -o pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/diagnose-stlink.sh <target>

Targets:
  f103c8t6   STM32F103C8T6 / Blue Pill class boards
  f407       STM32F407 family boards

This script diagnoses ST-Link connectivity. It does not erase or program flash.
It tries both the default ST-Link backend and the deprecated HLA fallback.
EOF
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
STM32_ROOT="$(cd "${PROJECT_ROOT}/.." && pwd)"

OPENOCD_DIR="${STM32_ROOT}/tools/xpack-openocd-0.12.0-7"
OPENOCD_BIN="${OPENOCD_DIR}/bin/openocd"
OPENOCD_SCRIPTS="${OPENOCD_DIR}/openocd/scripts"
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/stlink-diagnostics-$(date +%Y%m%d-%H%M%S).log"

run_step() {
  local title="$1"
  shift

  printf '\n== %s ==\n' "${title}"
  "$@"
  local status=$?
  printf '\n[exit %s] %s\n' "${status}" "${title}"
  return "${status}"
}

run_step_nonfatal() {
  run_step "$@" || true
}

check_required_files() {
  local missing=0

  for path in "$@"; do
    if [[ -e "${path}" ]]; then
      printf 'ok: %s\n' "${path}"
    else
      printf 'missing: %s\n' "${path}"
      missing=1
    fi
  done

  return "${missing}"
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (( $# != 1 )); then
  usage >&2
  exit 2
fi

TARGET="$1"
case "${TARGET}" in
  f103|f103c8t6|stm32f103c8t6)
    TARGET="f103c8t6"
    DIRECT_CFG="openocd/stm32f103c8t6-stlink-low-speed-no-srst.cfg"
    HLA_CFG="openocd/stm32f103c8t6-stlink-hla-low-speed-no-srst.cfg"
    ;;
  f407|stm32f407)
    TARGET="f407"
    DIRECT_CFG="openocd/stm32f407-stlink-low-speed-no-srst.cfg"
    HLA_CFG="openocd/stm32f407-stlink-hla-low-speed-no-srst.cfg"
    ;;
  *)
    printf 'ERROR: unsupported target: %s\n\n' "${TARGET}" >&2
    usage >&2
    exit 2
    ;;
esac

mkdir -p "${LOG_DIR}"
cd "${PROJECT_ROOT}" || exit 1

set +e
{
  printf 'STM32 ST-Link diagnostics\n'
  printf 'Generated at: %s\n' "$(date -Is)"
  printf 'Project: %s\n' "${PROJECT_ROOT}"
  printf 'Target: %s\n' "${TARGET}"
  printf 'OpenOCD: %s\n' "${OPENOCD_BIN}"
  printf 'Log: %s\n\n' "${LOG_FILE}"

  run_step_nonfatal "System" bash -c '
    uname -a
    lsb_release -a 2>/dev/null || true
    id
  '

  run_step_nonfatal "ST-Link USB and udev status" ./scripts/check-stlink.sh

  run_step_nonfatal "Tools" bash -c '
    command -v lsusb || true
    command -v grep || true
    "'"${OPENOCD_BIN}"'" --version 2>&1 | head -4 || true
  '

  run_step_nonfatal "Required OpenOCD files" check_required_files \
    "${OPENOCD_BIN}" \
    "${OPENOCD_SCRIPTS}/interface/stlink.cfg" \
    "${OPENOCD_SCRIPTS}/interface/stlink-hla.cfg" \
    "${OPENOCD_SCRIPTS}/target/stm32f1x.cfg" \
    "${OPENOCD_SCRIPTS}/target/stm32f4x.cfg" \
    "${DIRECT_CFG}" \
    "${HLA_CFG}"

  run_step_nonfatal "OpenOCD direct config parse" \
    "${OPENOCD_BIN}" -s "${OPENOCD_SCRIPTS}" -f "${DIRECT_CFG}" -c shutdown

  run_step_nonfatal "OpenOCD HLA config parse" \
    "${OPENOCD_BIN}" -s "${OPENOCD_SCRIPTS}" -f "${HLA_CFG}" -c shutdown

  run_step_nonfatal "Recent USB kernel messages" bash -c '
    dmesg --ctime 2>/dev/null | grep -Ei "usb|st-link|stlink|stmicroelectronics|0483|openocd" | tail -80 || true
  '

  run_step "Probe direct backend" timeout 20s ./scripts/probe-stlink.sh "${TARGET}"
  DIRECT_STATUS=$?

  run_step "Probe HLA backend" timeout 20s ./scripts/probe-stlink.sh --hla "${TARGET}"
  HLA_STATUS=$?

  printf '\n== Summary ==\n'
  printf 'direct probe exit: %s\n' "${DIRECT_STATUS}"
  printf 'HLA probe exit: %s\n' "${HLA_STATUS}"

  if (( DIRECT_STATUS == 0 || HLA_STATUS == 0 )); then
    printf 'Result: ST-Link can connect to target %s.\n' "${TARGET}"
    exit 0
  fi

  cat <<'EOF'
Result: ST-Link target probe failed.

Recommended next checks:
  1. Run ./scripts/install-stlink-udev-rule.sh, then unplug and replug ST-Link.
  2. Confirm ./scripts/check-stlink.sh shows an ST-Link USB device.
  3. Check SWDIO, SWCLK, GND, and VTref/3V3 wiring.
  4. Check target board power.
  5. If direct backend fails but HLA gets further, use --hla for probe/flash.
EOF
  exit 1
} 2>&1 | tee "${LOG_FILE}"
STATUS=${PIPESTATUS[0]}
set -e

printf '\nSaved ST-Link diagnostic log: %s\n' "${LOG_FILE}"
exit "${STATUS}"
