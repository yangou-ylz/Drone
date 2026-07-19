# -*- coding: utf-8 -*-
"""0xF5 树莓派位置帧离线测试。

运行：
    python3 groundTest/test_f5_frame.py
"""
from __future__ import annotations

from ano_protocol import (
    ADDR_FC_STM32,
    FLAG_SLAM_VALID,
    FLAG_TARGET_VALID,
    INVALID_S32,
    build_f5_position,
    calc_checksum,
    hex_dump,
)


GOLDEN_CUR_0_TAR_X100 = (
    "AA 61 F5 19 "
    "00 00 00 00 00 00 00 00 50 00 00 00 "
    "64 00 00 00 00 00 00 00 50 00 00 00 "
    "03 20 36"
)


def test_golden_frame() -> None:
    frame = build_f5_position(
        ADDR_FC_STM32,
        0,
        0,
        80,
        100,
        0,
        80,
        FLAG_SLAM_VALID | FLAG_TARGET_VALID,
    )
    assert len(frame) == 31
    assert hex_dump(frame) == GOLDEN_CUR_0_TAR_X100
    assert frame[:4] == bytes([0xAA, 0x61, 0xF5, 0x19])
    sc, ac = calc_checksum(frame[:-2])
    assert frame[-2:] == bytes([sc, ac])


def test_invalid_s32_is_signed_minimum() -> None:
    frame = build_f5_position(ADDR_FC_STM32, None, None, None, None, None, None, 0)
    invalid_bytes = INVALID_S32.to_bytes(4, "little", signed=True)
    assert frame[4:8] == invalid_bytes == bytes([0x00, 0x00, 0x00, 0x80])
    assert frame[28] == 0


def test_range_check() -> None:
    try:
        build_f5_position(ADDR_FC_STM32, 2147483648, 0, 0, 0, 0, 0, 0)
    except ValueError:
        return
    raise AssertionError("expected out-of-range s32 ValueError")


def main() -> int:
    test_golden_frame()
    test_invalid_s32_is_signed_minimum()
    test_range_check()
    print("test_f5_frame.py: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
