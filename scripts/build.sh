#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env.sh
source "${SCRIPT_DIR}/env.sh"

cd "${PROJECT_ROOT}"

cmake -S . -B build-gcc -G Ninja \
  -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi-gcc.cmake \
  -DCMAKE_BUILD_TYPE=Debug

cmake --build build-gcc --parallel

printf '\nBuild outputs:\n'
ls -lh build-gcc/ANO_LX.elf build-gcc/ANO_LX.hex build-gcc/ANO_LX.bin

