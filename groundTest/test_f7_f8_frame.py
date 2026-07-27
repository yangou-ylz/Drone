# -*- coding: utf-8 -*-
"""0xF7/0xF8 自主任务协议离线测试。"""
from __future__ import annotations

import struct

from ano_protocol import (
    ADDR_BROADCAST,
    AUTO_CMD_LOCK_RC,
    AUTO_CMD_PRECHECK,
    AUTO_CMD_RELEASE_RC,
    AUTO_CMD_TAKEOFF_HOLD,
    AUTO_FLAG_NO_XY_MOTION,
    AUTO_MOVE_AXIS_AUTO,
    AUTO_MOVE_CMD_START,
    AUTO_SAFETY_KEY,
    AUTO_STATUS_FLAG_RC_FAILSAFE,
    AUTO_STATUS_FLAG_RC_HOLD_FRAME,
    AUTO_STATUS_FLAG_RC_LOCKOUT,
    AUTO_STATUS_FLAG_RC_NO_SIGNAL,
    AUTO_VEL_CMD_SET,
    CMD_AUTO_STATUS,
    build_f7_auto_cmd,
    build_f9_move_cmd,
    build_fa_velocity_cmd,
    build_frame,
    calc_checksum,
    hex_dump,
    parse_f8_auto_status,
)


GOLDEN_F7_PRECHECK = (
    "AA FF F7 10 "
    "01 01 00 01 00 00 28 00 B8 0B 08 00 30 75 00 00 "
    "4B BB"
)

GOLDEN_F7_TAKEOFF_HOLD = (
    "AA FF F7 10 "
    "01 0B 00 0A 5A A5 28 00 B8 0B 08 00 30 75 00 00 "
    "5D 15"
)

GOLDEN_F9_MOVE_X30 = (
    "AA FF F9 0F "
    "01 01 00 01 5A A5 1E 00 00 00 00 00 FF 00 00 "
    "D0 89"
)

GOLDEN_FA_VEL = (
    "AA FF FA 0E "
    "01 01 00 01 5A A5 0F 00 F1 FF 14 00 00 00 "
    "C6 35"
)


def test_f7_precheck_golden() -> None:
    frame = build_f7_auto_cmd(
        ADDR_BROADCAST,
        seq=1,
        cmd=AUTO_CMD_PRECHECK,
        height_cm=40,
        hold_ms=3000,
        flags=AUTO_FLAG_NO_XY_MOTION,
        timeout_ms=30000,
    )
    assert len(frame) == 22
    assert hex_dump(frame) == GOLDEN_F7_PRECHECK
    assert frame[:4] == bytes([0xAA, 0xFF, 0xF7, 0x10])
    sc, ac = calc_checksum(frame[:-2])
    assert frame[-2:] == bytes([sc, ac])


def test_f7_release_rc_requires_safety_key() -> None:
    frame = build_f7_auto_cmd(
        ADDR_BROADCAST,
        seq=9,
        cmd=AUTO_CMD_RELEASE_RC,
        safety_key=AUTO_SAFETY_KEY,
    )
    ver, seq, cmd, key, *_ = struct.unpack("<BHBHHHHHH", frame[4:-2])
    assert ver == 1
    assert seq == 9
    assert cmd == AUTO_CMD_RELEASE_RC
    assert key == AUTO_SAFETY_KEY


def test_f7_lock_rc_requires_safety_key() -> None:
    frame = build_f7_auto_cmd(
        ADDR_BROADCAST,
        seq=10,
        cmd=AUTO_CMD_LOCK_RC,
        safety_key=AUTO_SAFETY_KEY,
    )
    ver, seq, cmd, key, *_ = struct.unpack("<BHBHHHHHH", frame[4:-2])
    assert ver == 1
    assert seq == 10
    assert cmd == AUTO_CMD_LOCK_RC
    assert key == AUTO_SAFETY_KEY


def test_f7_takeoff_hold_golden() -> None:
    frame = build_f7_auto_cmd(
        ADDR_BROADCAST,
        seq=11,
        cmd=AUTO_CMD_TAKEOFF_HOLD,
        safety_key=AUTO_SAFETY_KEY,
        height_cm=40,
        hold_ms=3000,
        flags=AUTO_FLAG_NO_XY_MOTION,
        timeout_ms=30000,
    )
    assert len(frame) == 22
    assert hex_dump(frame) == GOLDEN_F7_TAKEOFF_HOLD
    assert frame[:4] == bytes([0xAA, 0xFF, 0xF7, 0x10])
    sc, ac = calc_checksum(frame[:-2])
    assert frame[-2:] == bytes([sc, ac])


def test_f9_move_x30_golden() -> None:
    frame = build_f9_move_cmd(
        ADDR_BROADCAST,
        seq=1,
        cmd=AUTO_MOVE_CMD_START,
        safety_key=AUTO_SAFETY_KEY,
        x_cm=30,
        y_cm=0,
        z_cm=0,
        axis_mode=AUTO_MOVE_AXIS_AUTO,
    )
    assert len(frame) == 21
    assert hex_dump(frame) == GOLDEN_F9_MOVE_X30
    assert frame[:4] == bytes([0xAA, 0xFF, 0xF9, 0x0F])
    sc, ac = calc_checksum(frame[:-2])
    assert frame[-2:] == bytes([sc, ac])


def test_fa_velocity_golden() -> None:
    frame = build_fa_velocity_cmd(
        ADDR_BROADCAST,
        seq=1,
        cmd=AUTO_VEL_CMD_SET,
        safety_key=AUTO_SAFETY_KEY,
        vx_cmps=15,
        vy_cmps=-15,
        yaw_dps=20,
    )
    assert len(frame) == 20
    assert hex_dump(frame) == GOLDEN_FA_VEL
    assert frame[:4] == bytes([0xAA, 0xFF, 0xFA, 0x0E])
    sc, ac = calc_checksum(frame[:-2])
    assert frame[-2:] == bytes([sc, ac])


def test_f8_status_parse() -> None:
    data = struct.pack(
        "<BHHBBHHBBHhHHHH",
        1,      # ver
        7,      # status_seq
        3,      # last_cmd_seq
        10,     # state
        4,      # last_cmd
        0,      # error
        0x002B
        | AUTO_STATUS_FLAG_RC_LOCKOUT
        | AUTO_STATUS_FLAG_RC_FAILSAFE
        | AUTO_STATUS_FLAG_RC_NO_SIGNAL
        | AUTO_STATUS_FLAG_RC_HOLD_FRAME, # flags
        2,      # mode
        1,      # unlock
        1630,   # voltage_100
        40,     # alt_cm
        1200,   # state_ms
        80,     # f5_age_ms
        5,      # rx_f7_cnt
        0,      # err_cnt
    )
    frame = build_frame(ADDR_BROADCAST, CMD_AUTO_STATUS, data)
    assert len(frame) == 31
    st = parse_f8_auto_status(frame[4:-2])
    assert st.ver == 1
    assert st.status_seq == 7
    assert st.last_cmd_seq == 3
    assert st.state == 10
    assert st.last_cmd == 4
    assert st.flags & AUTO_STATUS_FLAG_RC_LOCKOUT
    assert st.flags & AUTO_STATUS_FLAG_RC_FAILSAFE
    assert st.flags & AUTO_STATUS_FLAG_RC_NO_SIGNAL
    assert st.flags & AUTO_STATUS_FLAG_RC_HOLD_FRAME
    assert st.voltage_100 == 1630
    assert st.alt_cm == 40


def main() -> int:
    test_f7_precheck_golden()
    test_f7_release_rc_requires_safety_key()
    test_f7_lock_rc_requires_safety_key()
    test_f7_takeoff_hold_golden()
    test_f9_move_x30_golden()
    test_fa_velocity_golden()
    test_f8_status_parse()
    print("test_f7_f8_frame.py: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
