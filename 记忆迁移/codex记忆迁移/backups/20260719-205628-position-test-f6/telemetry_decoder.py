# -*- coding: utf-8 -*-
"""P2 遥测解码器：仅依据 P0 字段冻结表，把 Frame.data → typed sample。

权威依据：用户手册/匿名通信协议V7.pdf 第 7-9 页 + gui/path_viz_master_plan.md P0 小节。

设计：
- 纯函数，无 Qt 依赖
- 解包失败返回 None（不抛异常，便于上层批量喂帧）
- 不做任何节流/状态保存（那是 PathTracker / TelemetryBus 的事）
"""
from __future__ import annotations

import math
import struct
import time
from typing import Optional

from gui.services.telemetry_models import (
    AttitudeSample,
    BatterySample,
    FlightModeSample,
    GenDistanceSample,
    GenPositionSample,
    GenVelocitySample,
    HeightSample,
    ModuleStatusSample,
    VelocitySample,
)
# ---- 各帧 LEN 与解包格式（与官方手册对齐）----
_FMT_0x03 = "<hhhB"   # ROL*100, PIT*100, YAW*100, FUSION_STA   → LEN=7
_FMT_0x04 = "<hhhhB"  # V0..V3 (*10000), FUSION_STA             → LEN=9
_FMT_0x05 = "<iiB"    # ALT_FU(cm), ALT_ADD(cm), ALT_STA        → LEN=9
_FMT_0x07 = "<hhh"    # SPEED_X/Y/Z (cm/s, 大地 NWU)            → LEN=6
_FMT_0x06 = "<BBBBB"  # MODE, LOCKED, CID, CMD0, CMD1           → LEN=5
_FMT_0x0D = "<HH"     # VOLTAGE*100, CURRENT*100                → LEN=4
_FMT_0x0E = "<BBBB"   # STA_G_VEL, STA_G_POS, STA_GPS, STA_ALT_ADD → LEN=4
_FMT_0x32 = "<iii"    # POS_X/Y/Z (cm)，0x80000000 无效         → LEN=12
_FMT_0x33 = "<hhh"    # SPEED_X/Y/Z (cm/s)，0x8000 无效         → LEN=6
_FMT_0x34 = "<BHI"    # DIRECTION, ANGLE, DIST(cm)，0xFFFFFFFF 无效 → LEN=7

# 通用传感器"数据无效"标志（官方手册）
_INVALID_S32 = -2147483648    # 0x80000000（struct 按 s32 解出的值）
_INVALID_S16 = -32768         # 0x8000（struct 按 s16 解出的值）
_INVALID_U32 = 0xFFFFFFFF     # 0x34 DIST 无效


# 四元数分量顺序：手册写 V0/V1/V2/V3，业界绝大多数实现 V0=w（标量）；
# 若后续实测发现是 V0=x，把 _QUAT_W_INDEX 改成 3，并由上层一次性翻转。
_QUAT_W_INDEX = 0
_QUAT_SCALE = 1.0 / 10000.0


def decode_attitude_euler(data: bytes, ts: Optional[float] = None) -> Optional[AttitudeSample]:
    """解码 0x03 欧拉姿态帧。"""
    if len(data) != struct.calcsize(_FMT_0x03):
        return None
    rol, pit, yaw, sta = struct.unpack(_FMT_0x03, data)
    return AttitudeSample(
        ts=ts if ts is not None else time.monotonic(),
        roll_deg=rol / 100.0,
        pitch_deg=pit / 100.0,
        yaw_deg=yaw / 100.0,
        source="euler",
        fusion_sta=sta,
    )


def decode_attitude_quat(data: bytes, ts: Optional[float] = None) -> Optional[AttitudeSample]:
    """解码 0x04 四元数姿态帧，内部转换为欧拉角输出（统一上层接口）。

    采用 ZYX (yaw-pitch-roll) 顺序，与匿名手册 4.1 节"载体->地理"姿态约定常用顺序一致。
    若 |quat| 偏离 1 太多则视为无效，返回 None。
    """
    if len(data) != struct.calcsize(_FMT_0x04):
        return None
    raw = struct.unpack(_FMT_0x04, data)
    q = [raw[i] * _QUAT_SCALE for i in range(4)]
    # 取 w 标量分量 + 三个矢量分量
    if _QUAT_W_INDEX == 0:
        w, x, y, z = q[0], q[1], q[2], q[3]
    else:
        x, y, z, w = q[0], q[1], q[2], q[3]
    norm_sq = w * w + x * x + y * y + z * z
    if norm_sq < 0.5 or norm_sq > 1.5:
        # 数据明显异常（手册扩 10000 倍传输有小量化误差，模长应非常接近 1）
        return None
    # 四元数 -> 欧拉（ZYX）。
    # 原始四元数按常规右手系公式转出后，pitch/yaw 与凌霄 0x03 欧拉角符号相反；
    # 以 0x03 官方直出欧拉角为显示/上层语义基准，因此这里统一翻转 pitch/yaw。
    # roll  = atan2(2(wx+yz), 1 - 2(x^2+y^2))
    # pitch = asin (2(wy - zx))，限幅防越界
    # yaw   = atan2(2(wz+xy), 1 - 2(y^2+z^2))
    sinr = 2.0 * (w * x + y * z)
    cosr = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr, cosr)
    sinp = max(-1.0, min(1.0, 2.0 * (w * y - z * x)))
    pitch = math.asin(sinp)
    siny = 2.0 * (w * z + x * y)
    cosy = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny, cosy)
    return AttitudeSample(
        ts=ts if ts is not None else time.monotonic(),
        roll_deg=math.degrees(roll),
        pitch_deg=-math.degrees(pitch),
        yaw_deg=-math.degrees(yaw),
        source="quat",
        fusion_sta=raw[4],
    )


def decode_height(data: bytes, ts: Optional[float] = None) -> Optional[HeightSample]:
    """解码 0x05 高度数据帧（按 P0 冻结：<iiB 三字段）。"""
    if len(data) != struct.calcsize(_FMT_0x05):
        return None
    alt_fu, alt_add, sta = struct.unpack(_FMT_0x05, data)
    return HeightSample(
        ts=ts if ts is not None else time.monotonic(),
        alt_fu_cm=alt_fu,
        alt_add_cm=alt_add,
        alt_sta=sta,
    )


def decode_velocity(data: bytes, ts: Optional[float] = None) -> Optional[VelocitySample]:
    """解码 0x07 速度帧（大地 NWU 系，cm/s）。"""
    if len(data) != struct.calcsize(_FMT_0x07):
        return None
    vx, vy, vz = struct.unpack(_FMT_0x07, data)
    return VelocitySample(
        ts=ts if ts is not None else time.monotonic(),
        vx_cmps=vx,
        vy_cmps=vy,
        vz_cmps=vz,
    )


def decode_flight_mode(data: bytes, ts: Optional[float] = None) -> Optional[FlightModeSample]:
    """解码 0x06 飞控运行模式帧（U8 ×5）。"""
    if len(data) != struct.calcsize(_FMT_0x06):
        return None
    mode, locked, cid, cmd0, cmd1 = struct.unpack(_FMT_0x06, data)
    return FlightModeSample(
        ts=ts if ts is not None else time.monotonic(),
        mode=mode,
        locked=bool(locked),
        cid=cid,
        cmd0=cmd0,
        cmd1=cmd1,
    )


def decode_battery(data: bytes, ts: Optional[float] = None) -> Optional[BatterySample]:
    """解码 0x0D 电压电流帧（传输时扩大 100 倍）。"""
    if len(data) != struct.calcsize(_FMT_0x0D):
        return None
    volt, curr = struct.unpack(_FMT_0x0D, data)
    return BatterySample(
        ts=ts if ts is not None else time.monotonic(),
        voltage_v=volt / 100.0,
        current_a=curr / 100.0,
    )


def decode_module_status(data: bytes, ts: Optional[float] = None) -> Optional[ModuleStatusSample]:
    """解码 0x0E 外接模块工作状态帧（U8 ×4）。"""
    if len(data) != struct.calcsize(_FMT_0x0E):
        return None
    g_vel, g_pos, gps, alt_add = struct.unpack(_FMT_0x0E, data)
    return ModuleStatusSample(
        ts=ts if ts is not None else time.monotonic(),
        sta_g_vel=g_vel,
        sta_g_pos=g_pos,
        sta_gps=gps,
        sta_alt_add=alt_add,
    )


def decode_gen_position(data: bytes, ts: Optional[float] = None) -> Optional[GenPositionSample]:
    """解码 0x32 通用位置型传感器帧（S32 ×3，cm；0x80000000 无效）。"""
    if len(data) != struct.calcsize(_FMT_0x32):
        return None
    x, y, z = struct.unpack(_FMT_0x32, data)
    return GenPositionSample(
        ts=ts if ts is not None else time.monotonic(),
        x_cm=x, y_cm=y, z_cm=z,
        valid_x=(x != _INVALID_S32),
        valid_y=(y != _INVALID_S32),
        valid_z=(z != _INVALID_S32),
    )


def decode_gen_velocity(data: bytes, ts: Optional[float] = None) -> Optional[GenVelocitySample]:
    """解码 0x33 通用速度型传感器帧（光流等，S16 ×3，cm/s；0x8000 无效）。"""
    if len(data) != struct.calcsize(_FMT_0x33):
        return None
    vx, vy, vz = struct.unpack(_FMT_0x33, data)
    return GenVelocitySample(
        ts=ts if ts is not None else time.monotonic(),
        vx_cmps=vx, vy_cmps=vy, vz_cmps=vz,
        valid_x=(vx != _INVALID_S16),
        valid_y=(vy != _INVALID_S16),
        valid_z=(vz != _INVALID_S16),
    )


def decode_gen_distance(data: bytes, ts: Optional[float] = None) -> Optional[GenDistanceSample]:
    """解码 0x34 通用测距传感器帧（U8 + U16 + U32；0xFFFFFFFF 无效）。"""
    if len(data) != struct.calcsize(_FMT_0x34):
        return None
    direction, angle, dist = struct.unpack(_FMT_0x34, data)
    return GenDistanceSample(
        ts=ts if ts is not None else time.monotonic(),
        direction=direction,
        angle=angle,
        distance_cm=dist,
        valid=(dist != _INVALID_U32),
    )
