# -*- coding: utf-8 -*-
"""ImuDataHub —— IMU 测试台数据中枢（Phase 1.1）。

职责（单一）：
- 订阅现有 ``SerialWorker.frame_received`` 信号（不改 SerialWorker）
- 复用既有解码逻辑，把原始 Frame → 结构化样本
- 通过 Qt 信号向各测试面板广播；面板之间彼此解耦

设计约束：
- 只做解码 + 广播，不持有任何 Widget、不做统计/节流（那是各面板的事）
- 纯 QObject，运行在主线程（frame_received 为跨线程队列连接，槽在主线程执行）
- 加速度/陀螺标定值可运行时更新（校准面板 Phase 4 会用）

数据来源帧（匿名协议 V7）：
- 0x01 IMU 原始值（~100Hz）: acc/gyr 各三轴 s16(LSB) + shock
- 0x04 四元数姿态（~67Hz）: 复用 telemetry_decoder.decode_attitude_quat
"""
from __future__ import annotations

import math
import struct
import time
from dataclasses import dataclass
from typing import Optional

from PySide6.QtCore import QObject, Signal, Slot

from gui.imu_test.logger import get_logger
from gui.services.telemetry_decoder import (
    decode_attitude_quat,
    decode_gen_position,
    decode_gen_velocity,
    decode_velocity,
)

# ---- 标定默认值（实测校准；校准面板可覆盖）----
# 加速度标定：frame_monitor 真机静止实测 Az=1363.4 LSB ≈ 1g（2026-07-17）
# 说明：协议手册标称 ±16g（1g=2048 LSB）不准，固件实配约 ±24g 量程
DEFAULT_ACC_SCALE = 9.80665 / 1363.4   # LSB → m/s²（实测 1g=1363.4 LSB）
DEFAULT_GYR_SCALE = 0.001065           # LSB → rad/s（±2000dps 量程，暂未实测校准）

# 0x01 帧解包：acc_x/y/z, gyr_x/y/z (s16) + shock(u8)，小端
_FMT_0x01 = "<hhhhhhB"
_LEN_0x01 = struct.calcsize(_FMT_0x01)  # 13

# 帧 ID 常量
CMD_IMU_RAW = 0x01
CMD_ATT_QUAT = 0x04
CMD_VEL     = 0x07   # 0x07 飞控融合速度（机体系，cm/s）
CMD_GEN_POS = 0x32   # 0x32 通用位置型传感器帧（光流/激光等外部观测位置，cm）
CMD_GEN_VEL = 0x33   # 0x33 光流原始速度（机体系，cm/s，S16×3）
CMD_LOG_STR = 0xA0


@dataclass(frozen=True)
class ImuRawSample:
    """0x01 IMU 原始值解码结果（物理量 + 原始 LSB）。"""

    ts: float                 # 接收时刻（time.monotonic 秒）
    acc_x: float              # m/s²
    acc_y: float
    acc_z: float
    gyr_x: float              # rad/s
    gyr_y: float
    gyr_z: float
    shock: int                # 震动标志（原样透传）
    raw_acc: tuple            # (acc_x, acc_y, acc_z) 原始 LSB
    raw_gyr: tuple            # (gyr_x, gyr_y, gyr_z) 原始 LSB


class ImuDataHub(QObject):
    """IMU 数据解码中枢。订阅 frame_received，广播结构化信号。"""

    # ---- 对外信号 ----
    imu_raw = Signal(object)          # ImuRawSample（0x01）
    attitude = Signal(object)         # AttitudeSample（0x04→欧拉）
    velocity = Signal(object)         # VelocitySample（0x07 飞控融合速度）
    position = Signal(object)         # GenPositionSample（0x32 通用外部位置，供位置测试"直接转发"算法）
    gen_velocity = Signal(object)     # GenVelocitySample（0x33 光流原始速度）
    quat_norm = Signal(float)         # 0x04 原始四元数模长（质量检查用，理想≈1）
    frame_seen = Signal(int, float)   # (cmd, ts) 每收到一帧有效数据都发，供帧率统计
    log_text = Signal(int, str)       # 0xA0 字符串帧 (color, text)，供设备校准终端显示

    def __init__(
        self,
        parent: Optional[QObject] = None,
        acc_scale: float = DEFAULT_ACC_SCALE,
        gyr_scale: float = DEFAULT_GYR_SCALE,
    ) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._acc_scale = float(acc_scale)
        self._gyr_scale = float(gyr_scale)
        self._log.info(
            "ImuDataHub 初始化（acc_scale=%.6f, gyr_scale=%.6f）",
            self._acc_scale,
            self._gyr_scale,
        )

    # ---- 标定值（校准面板运行时更新）----
    @property
    def acc_scale(self) -> float:
        return self._acc_scale

    @property
    def gyr_scale(self) -> float:
        return self._gyr_scale

    def set_scales(
        self, acc_scale: Optional[float] = None, gyr_scale: Optional[float] = None
    ) -> None:
        """更新标定系数（None 表示保持不变）。"""
        if acc_scale is not None:
            self._acc_scale = float(acc_scale)
        if gyr_scale is not None:
            self._gyr_scale = float(gyr_scale)
        self._log.info(
            "标定系数已更新（acc_scale=%.6f, gyr_scale=%.6f）",
            self._acc_scale,
            self._gyr_scale,
        )

    # ---- 帧入口（连接 SerialWorker.frame_received）----
    @Slot(object)
    def on_frame(self, frame: object) -> None:
        """解码单帧并广播。异常不外抛，避免拖垮串口线程回调。"""
        cmd = getattr(frame, "cmd", None)
        data = getattr(frame, "data", None)
        if cmd is None or data is None:
            return
        ts = time.monotonic()
        try:
            if cmd == CMD_IMU_RAW:
                sample = self._decode_imu_raw(data, ts)
                if sample is not None:
                    self.frame_seen.emit(cmd, ts)
                    self.imu_raw.emit(sample)
            elif cmd == CMD_ATT_QUAT:
                att = decode_attitude_quat(data, ts)
                if att is not None:
                    self.frame_seen.emit(cmd, ts)
                    self.attitude.emit(att)
                    self._emit_quat_norm(data)
            elif cmd == CMD_VEL:
                vel = decode_velocity(data, ts)
                if vel is not None:
                    self.frame_seen.emit(cmd, ts)
                    self.velocity.emit(vel)
            elif cmd == CMD_GEN_POS:
                pos = decode_gen_position(data, ts)
                if pos is not None:
                    self.frame_seen.emit(cmd, ts)
                    self.position.emit(pos)
            elif cmd == CMD_GEN_VEL:
                gvel = decode_gen_velocity(data, ts)
                if gvel is not None:
                    self.frame_seen.emit(cmd, ts)
                    self.gen_velocity.emit(gvel)
            elif cmd == CMD_LOG_STR:
                self.frame_seen.emit(cmd, ts)
                self._emit_log_text(frame, data)
            else:
                # 其他帧也计入帧率统计（供总览观察全链路流量），但不解码
                self.frame_seen.emit(cmd, ts)
        except Exception as exc:  # noqa: BLE001 —— 解码鲁棒性优先
            self._log.warning("解码帧 cmd=0x%02X 失败：%r", cmd if isinstance(cmd, int) else -1, exc)

    # ---- 内部解码 ----
    def _emit_quat_norm(self, data: bytes) -> None:
        """从 0x04 原始帧算四元数模长并广播（质量检查用）。"""
        try:
            raw = struct.unpack("<hhhhB", data[:9])
            q = [raw[i] / 10000.0 for i in range(4)]
            self.quat_norm.emit(math.sqrt(q[0] * q[0] + q[1] * q[1] + q[2] * q[2] + q[3] * q[3]))
        except Exception:  # noqa: BLE001
            pass

    def _emit_log_text(self, frame: object, data: bytes) -> None:
        """从 0xA0 字符串帧解出 (color, text) 并广播（设备校准终端用）。"""
        try:
            cs = getattr(frame, "color_str", None)
            if callable(cs):
                res = cs()
                if res is not None:
                    color, text = res
                    self.log_text.emit(int(color), str(text))
                    return
            # 兜底：手动解码（data[0]=颜色，data[1:]=GBK 文本）
            if data:
                color = data[0]
                text = data[1:].decode("gbk", errors="replace")
                self.log_text.emit(int(color), text)
        except Exception as exc:  # noqa: BLE001
            self._log.warning("解码 0xA0 字符串帧失败：%r", exc)

    def _decode_imu_raw(self, data: bytes, ts: float) -> Optional[ImuRawSample]:
        """解码 0x01 IMU 原始帧（长度不足返回 None）。"""
        if len(data) < _LEN_0x01:
            return None
        ax, ay, az, gx, gy, gz, shock = struct.unpack(_FMT_0x01, data[:_LEN_0x01])
        return ImuRawSample(
            ts=ts,
            acc_x=ax * self._acc_scale,
            acc_y=ay * self._acc_scale,
            acc_z=az * self._acc_scale,
            gyr_x=gx * self._gyr_scale,
            gyr_y=gy * self._gyr_scale,
            gyr_z=gz * self._gyr_scale,
            shock=shock,
            raw_acc=(ax, ay, az),
            raw_gyr=(gx, gy, gz),
        )
