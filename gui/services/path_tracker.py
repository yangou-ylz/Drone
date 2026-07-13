# -*- coding: utf-8 -*-
"""P2 PathTracker：后台积分路径，激活瞬间快照 yaw0，0x07 机体系速度旋转到激活时刻局部系。

设计要点（与 master_plan D3 / D4 / D5 / D7 对齐）：
- 后台积分常驻：是否 enabled 仅影响"是否真正积分 + 是否更新轨迹"，
  关闭时仍接收姿态以便随时能用最新 yaw 作 yaw0
- 激活瞬间：把当前姿态的 yaw 作为 yaw0，清空轨迹，把当前位置置原点
- 0x07 是机体系速度（FLU），激活后每帧以 delta_yaw = yaw_now - yaw0 旋转到局部系：
    vx_local = vx_body * cos(delta_yaw) - vy_body * sin(delta_yaw)
    vy_local = vx_body * sin(delta_yaw) + vy_body * cos(delta_yaw)
  delta_yaw 归一化到 [-180, 180] 避免 ±180° 边界跳变
- 速度死区 _DEADBAND_CMPS：消除 IMU 静止偏置漂移（实测 ~0.5 cm/s → 30cm/min 漂移）
- Z 位置 = alt_fu_cm（绝对值，不积分；D5）
- 时间衰减：deque + 按 trail_seconds 修剪头部 + 兜底 max_points
- 纯逻辑，无 Qt 依赖；线程安全交给上层（TelemetryBus 在主线程串行调用）
"""
from __future__ import annotations

import math
import time
from collections import deque
from typing import Deque, Optional

# ---- 极简策略（2026-05-28 冻结、等光流接入）----
# 背景：IMU 0x07 本身是加速度积分来的速度，再用 v 积分出 xy 是双重漂移，仅靠 GUI 补丁
#   （运动检测、冷却锁定、yaw 门控、|v|EMA……）都只能掏东增西。两轮股折验证：越补丁越不可预测。
# 决策：等光流传感器接入后取融合 v，在那之前路径漂移不再迫调。
# 现状：仅保留 |v_body| < 2 cm/s 死区（防长期静止 IMU 偏置漂移增长轨迹）。
#   位置=0x07 直接 body→local 反旋转后积分；yaw=IMU 实时值。所见即所得。
_V_DEADBAND_CMPS: float = 2.0        # cm/s，body 系速度死区（仅静止偏置过滤）
_V_DEADBAND_SQ: float = _V_DEADBAND_CMPS * _V_DEADBAND_CMPS

from gui.services.telemetry_models import (
    AttitudeSample,
    HeightSample,
    PathPoint,
    PathSnapshot,
    PathTrackerConfig,
    VelocitySample,
)


class PathTracker:
    def __init__(self, config: Optional[PathTrackerConfig] = None) -> None:
        self._cfg = config or PathTrackerConfig()
        self._points: Deque[PathPoint] = deque()
        self._enabled = False
        # 激活瞬间快照
        self._yaw0_deg: float = 0.0
        # 当前姿态 / 速度 / 高度（即使未激活也维护，用于"激活瞬间立即可用"）
        self._latest_attitude: Optional[AttitudeSample] = None
        self._latest_velocity: Optional[VelocitySample] = None
        self._latest_height: Optional[HeightSample] = None
        # 积分态
        self._x_cm: float = 0.0
        self._y_cm: float = 0.0
        self._z_cm: float = 0.0
        # P3 微调：Z 以启用瞬间的高度为零点，与 D4 yaw0 快照同调
        # （原 D5 “0x05 绝对高度”改为“0x05 - 启用瞬间偏置”，避免启用后方块凭空跳到绝对高度）
        self._z_offset_cm: float = 0.0
        # 上一次积分用到的速度样本时间戳
        self._last_vel_ts: Optional[float] = None
        # 最近一次反旋转得到的局部速度（仅用于 snapshot 渲染速度箭头）
        self._vx_local: float = 0.0
        self._vy_local: float = 0.0
        self._vz_local: float = 0.0

    # ---- 配置 ----
    def update_config(self, config: PathTrackerConfig) -> None:
        self._cfg = config
        self._trim()

    @property
    def config(self) -> PathTrackerConfig:
        return self._cfg

    # ---- 启用/重置 ----
    @property
    def enabled(self) -> bool:
        return self._enabled

    def enable(self) -> None:
        """启动一次新的可视化会话：以当前 yaw 为 yaw0，位置清零，轨迹清空。"""
        yaw_deg = self._latest_attitude.yaw_deg if self._latest_attitude else 0.0
        self._yaw0_deg = yaw_deg   # 激活瞬间机头方向定义为局部系 +X 轴
        self._x_cm = 0.0
        self._y_cm = 0.0
        # Z 偏置：以启用瞬间的高度为零点（没收到 0x05 时偏置记为 0）
        self._z_offset_cm = float(self._latest_height.alt_fu_cm) if self._latest_height else 0.0
        self._z_cm = 0.0
        self._points.clear()
        self._points.append(
            PathPoint(ts=time.monotonic(), x_cm=0.0, y_cm=0.0, z_cm=self._z_cm)
        )
        self._last_vel_ts = None  # 激活瞬间起重新计时
        self._vx_local = 0.0
        self._vy_local = 0.0
        self._vz_local = 0.0
        self._enabled = True

    def disable(self) -> None:
        """仅停止积分推进；保留轨迹和 yaw0，方便用户随时再次启用看历史。

        重新 enable 才会清空 / 重新快照 yaw0。
        """
        self._enabled = False
        self._last_vel_ts = None

    def reset(self) -> None:
        """彻底重置：清空轨迹、清积分态、保持 enabled 当前值。"""
        self._x_cm = 0.0
        self._y_cm = 0.0
        self._z_offset_cm = float(self._latest_height.alt_fu_cm) if self._latest_height else 0.0
        self._z_cm = 0.0
        self._points.clear()
        if self._enabled:
            # 重置时若仍处于激活态，重新快照 yaw0
            self.enable()

    # ---- 喂数据 ----
    def on_attitude(self, sample: AttitudeSample) -> None:
        """姿态帧：只保留最新值（极简策略，不做任何估计或过滤）。"""
        self._latest_attitude = sample

    def on_height(self, sample: HeightSample) -> None:
        """高度帧：保留最新值；若已激活则同步更新 z（相对启用瞬间偏置，不积分）。"""
        self._latest_height = sample
        if self._enabled:
            self._z_cm = float(sample.alt_fu_cm) - self._z_offset_cm

    def on_velocity(self, sample: VelocitySample) -> None:
        """速度帧：极简流程（等光流接入前不再加任何门控）。

        步骤：
        1. body 系死区：|v_body| < 2 cm/s 则 vx_b=vy_b=0（仅静止偏置过滤）。
        2. body → local 反旋转（delta_yaw = yaw_now - yaw0）。
        3. 直接积分：什么都不补，等光流。
        """
        self._latest_velocity = sample
        if not self._enabled:
            self._last_vel_ts = None
            return

        # ---- 1) body 系死区（仅静止偏置过滤）----
        vx_b = float(sample.vx_cmps)
        vy_b = float(sample.vy_cmps)
        vz_l = float(sample.vz_cmps)
        if vx_b * vx_b + vy_b * vy_b < _V_DEADBAND_SQ:
            vx_b = 0.0
            vy_b = 0.0

        # ---- 2) body → local 反旋转 ----
        if self._latest_attitude is not None:
            delta_raw = self._latest_attitude.yaw_deg - self._yaw0_deg
            delta_rad = math.radians(((delta_raw + 180.0) % 360.0) - 180.0)
            c = math.cos(delta_rad)
            s = math.sin(delta_rad)
            vx_l = vx_b * c - vy_b * s
            vy_l = vx_b * s + vy_b * c
        else:
            vx_l, vy_l = vx_b, vy_b

        # 渲染端速度箭头同步曝露（与积分一致，死区后则为 0）
        self._vx_local = vx_l
        self._vy_local = vy_l
        self._vz_local = vz_l

        # ---- 3) 积分 ----
        if self._last_vel_ts is None:
            self._last_vel_ts = sample.ts
            return  # 第一帧只设基准不积分
        dt = sample.ts - self._last_vel_ts
        self._last_vel_ts = sample.ts
        if dt <= self._cfg.min_dt_s:
            return
        if dt > self._cfg.max_dt_s:
            dt = self._cfg.max_dt_s
        self._x_cm += vx_l * dt
        self._y_cm += vy_l * dt
        self._points.append(
            PathPoint(ts=sample.ts, x_cm=self._x_cm, y_cm=self._y_cm, z_cm=self._z_cm)
        )
        self._trim()

    # ---- 修剪 ----
    def _trim(self) -> None:
        if not self._points:
            return
        # 兜底点数上限
        while len(self._points) > self._cfg.max_points:
            self._points.popleft()
        # 时间衰减：以队尾时间为参考，丢掉超出 trail_seconds 的头部
        tail_ts = self._points[-1].ts
        cutoff = tail_ts - self._cfg.trail_seconds
        while self._points and self._points[0].ts < cutoff:
            self._points.popleft()

    # ---- 快照 ----
    def snapshot(self) -> PathSnapshot:
        """渲染快照：姿态实时跟 IMU（不锁定，极简策略）。"""
        att = self._latest_attitude
        if att is None:
            roll = pitch = yaw = 0.0
        else:
            roll = att.roll_deg
            pitch = att.pitch_deg
            yaw = att.yaw_deg
        return PathSnapshot(
            ts=time.monotonic(),
            enabled=self._enabled,
            yaw0_deg=self._yaw0_deg,
            pos_cm=(self._x_cm, self._y_cm, self._z_cm),
            attitude_deg=(roll, pitch, yaw),
            vel_local_cmps=(self._vx_local, self._vy_local, self._vz_local),
            points=tuple(self._points),
        )
