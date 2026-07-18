# -*- coding: utf-8 -*-
"""具体位置估计算法（方案A 注册表实现）。

当前内置三种（覆盖用户列出的三类位置来源）：
1. DirectPositionEstimator   —— 直接转发外部观测位置（0x32），位移 = 当前位置 − 原点
2. VelocityIntegrator        —— 速度积分（0x07 → 位移，梯形积分 + 死区）
3. AccelDoubleIntegrator     —— 加速度二次积分（0x01 → 速度 → 位移，含零偏估计 + 泄漏抑漂）

新增算法（滤波/融合等）只需在此继承 PositionEstimator + @register，
GUI 启动后即自动出现在对比曲线中。
"""
from __future__ import annotations

from typing import List, Optional

from gui.imu_test.position.estimator_base import (
    InputKind,
    ParamSpec,
    PositionEstimator,
    Vec3,
    register,
)


@register
class DirectPositionEstimator(PositionEstimator):
    """直接转发外部观测位置（0x32，cm）。位移 = 当前位置 − 装填原点。"""

    key = "direct_pos"
    label = "直接位置转发(0x32)"
    input_kind = InputKind.POSITION
    color = "#FFCA28"   # 琥珀

    def reset(self) -> None:
        self._origin: Optional[Vec3] = None   # 首帧作原点

    def update(self, t: float, x: float, y: float, z: float) -> Vec3:
        if self._origin is None:
            self._origin = (x, y, z)
        ox, oy, oz = self._origin
        return (x - ox, y - oy, z - oz)


@register
class VelocityIntegrator(PositionEstimator):
    """速度积分：对 0x07 飞控融合速度(cm/s)做梯形积分得位移(cm)。

    参数：
    - deadband：速度死区(cm/s)，|v|<死区 视为 0，抑制静止噪声累积
    - max_dt：相邻帧最大积分间隔(s)，防丢帧导致积分跳变
    - stop_suppress_en：停止抑制开关（单次位移测试用，检测停止后不再积分负尾巴）
    - stop_thr_cmps：停止判定速度阈值（各轴绝对值均小于此值认为已停）
    - stop_hold_s：停止持续时长（稳定低于阈值此时长后触发抑制）
    """

    key = "vel_integral"
    label = "飞控速度积分(0x07)"
    input_kind = InputKind.VELOCITY
    color = "#66BB6A"   # 绿

    @classmethod
    def params_spec(cls) -> List[ParamSpec]:
        return [
            ParamSpec("deadband", "速度死区", 0.5, 0.0, 50.0, 0.5, "cm/s", 1),
            ParamSpec("max_dt", "最大积分步长", 0.1, 0.01, 1.0, 0.01, "s", 2),
            ParamSpec("stop_suppress_en", "停止抑制(0=关/1=开)", 0.0, 0.0, 1.0, 1.0, "", 0),
            ParamSpec("stop_thr_cmps", "停止速度阈值", 1.5, 0.1, 10.0, 0.5, "cm/s", 1),
            ParamSpec("stop_hold_s", "停止持续时长", 0.3, 0.05, 2.0, 0.05, "s", 2),
        ]

    def reset(self) -> None:
        self._t_prev: Optional[float] = None
        self._prev_v = (0.0, 0.0, 0.0)
        self._pos = [0.0, 0.0, 0.0]
        self._stopped = False          # 停止抑制标志
        self._below_thr_since: Optional[float] = None  # 进入低速区的时刻

    def _apply_deadband(self, v: float) -> float:
        return 0.0 if abs(v) < self.param("deadband") else v

    def update(self, t: float, x: float, y: float, z: float) -> Vec3:
        vx = self._apply_deadband(x)
        vy = self._apply_deadband(y)
        vz = self._apply_deadband(z)
        
        # 停止抑制逻辑：检测到稳定低速后，后续速度不再积分（防反向尾巴）
        if self.param("stop_suppress_en", 0.0) > 0.5:
            thr = self.param("stop_thr_cmps", 1.5)
            hold = self.param("stop_hold_s", 0.3)
            if abs(vx) < thr and abs(vy) < thr and abs(vz) < thr:
                if self._below_thr_since is None:
                    self._below_thr_since = t
                elif t - self._below_thr_since >= hold:
                    self._stopped = True  # 连续低速足够久，触发停止
            else:
                self._below_thr_since = None  # 速度重新起来，复位
                self._stopped = False

        if self._t_prev is not None:
            dt = t - self._t_prev
            if 0.0 < dt <= self.param("max_dt", 0.1) and not self._stopped:
                pvx, pvy, pvz = self._prev_v
                # 梯形积分：位移 += (v_prev + v_now)/2 * dt
                self._pos[0] += (pvx + vx) * 0.5 * dt
                self._pos[1] += (pvy + vy) * 0.5 * dt
                self._pos[2] += (pvz + vz) * 0.5 * dt
        self._t_prev = t
        self._prev_v = (vx, vy, vz)
        return (self._pos[0], self._pos[1], self._pos[2])


@register
class OpticalFlowVelocityIntegrator(PositionEstimator):
    """光流原始速度积分：对 0x33 光流速度(cm/s)做梯形积分得位移(cm)。

    对比 0x07：0x33 是光流模块直接输出的速度，未经飞控内部融合/滤波；
    0x07 是飞控融合后的速度估计，可能含观测器动态。

    参数：
    - deadband：速度死区(cm/s)，|v|<死区 视为 0，抑制静止噪声累积
    - max_dt：相邻帧最大积分间隔(s)，防丢帧导致积分跳变
    - stop_suppress_en：停止抑制开关（单次位移测试用，检测停止后不再积分负尾巴）
    - stop_thr_cmps：停止判定速度阈值（各轴绝对值均小于此值认为已停）
    - stop_hold_s：停止持续时长（稳定低于阈值此时长后触发抑制）
    """

    key = "optflow_vel_integral"
    label = "光流速度积分(0x33)"
    input_kind = InputKind.GEN_VELOCITY
    color = "#42A5F5"   # 蓝

    @classmethod
    def params_spec(cls) -> List[ParamSpec]:
        return [
            ParamSpec("deadband", "速度死区", 0.5, 0.0, 50.0, 0.5, "cm/s", 1),
            ParamSpec("max_dt", "最大积分步长", 0.1, 0.01, 1.0, 0.01, "s", 2),
            ParamSpec("stop_suppress_en", "停止抑制(0=关/1=开)", 0.0, 0.0, 1.0, 1.0, "", 0),
            ParamSpec("stop_thr_cmps", "停止速度阈值", 1.5, 0.1, 10.0, 0.5, "cm/s", 1),
            ParamSpec("stop_hold_s", "停止持续时长", 0.3, 0.05, 2.0, 0.05, "s", 2),
        ]

    def reset(self) -> None:
        self._t_prev: Optional[float] = None
        self._prev_v = (0.0, 0.0, 0.0)
        self._pos = [0.0, 0.0, 0.0]
        self._stopped = False
        self._below_thr_since: Optional[float] = None

    def _apply_deadband(self, v: float) -> float:
        return 0.0 if abs(v) < self.param("deadband") else v

    def update(self, t: float, x: float, y: float, z: float) -> Vec3:
        # 0x33 的 vx/vy/vz 为 S16，0x8000=-32768 表示无效；透传前端已过滤
        vx = self._apply_deadband(x)
        vy = self._apply_deadband(y)
        vz = self._apply_deadband(z)
        
        # 停止抑制逻辑（同 0x07 版本）
        if self.param("stop_suppress_en", 0.0) > 0.5:
            thr = self.param("stop_thr_cmps", 1.5)
            hold = self.param("stop_hold_s", 0.3)
            if abs(vx) < thr and abs(vy) < thr and abs(vz) < thr:
                if self._below_thr_since is None:
                    self._below_thr_since = t
                elif t - self._below_thr_since >= hold:
                    self._stopped = True
            else:
                self._below_thr_since = None
                self._stopped = False

        if self._t_prev is not None:
            dt = t - self._t_prev
            if 0.0 < dt <= self.param("max_dt", 0.1) and not self._stopped:
                pvx, pvy, pvz = self._prev_v
                # 梯形积分：位移 += (v_prev + v_now)/2 * dt
                self._pos[0] += (pvx + vx) * 0.5 * dt
                self._pos[1] += (pvy + vy) * 0.5 * dt
                self._pos[2] += (pvz + vz) * 0.5 * dt
        self._t_prev = t
        self._prev_v = (vx, vy, vz)
        return (self._pos[0], self._pos[1], self._pos[2])


@register
class AccelDoubleIntegrator(PositionEstimator):
    """加速度二次积分：0x01 加速度(m/s²) → 速度 → 位移(cm)。

    静止时二次积分极易发散，故内置两项抑漂手段：
    - 零偏估计：reset 后前 bias_n 帧的加速度均值作为零偏，之后每帧扣除
    - 速度泄漏：每步 v *= (1 − leak)，模拟零速修正，抑制积分漂移

    参数：
    - bias_n：零偏估计帧数
    - acc_deadband：去偏后加速度死区(m/s²)
    - vel_leak：速度泄漏系数(0~1，越大越抑漂但越迟钝)
    - max_dt：最大积分步长(s)
    """

    key = "acc_double_integral"
    label = "加速度二次积分(0x01)"
    input_kind = InputKind.ACCEL
    color = "#EF5350"   # 红

    _M_TO_CM = 100.0

    @classmethod
    def params_spec(cls) -> List[ParamSpec]:
        return [
            ParamSpec("bias_n", "零偏估计帧数", 100, 0, 500, 10, "帧", 0),
            ParamSpec("acc_deadband", "加速度死区", 0.075, 0.0, 2.0, 0.01, "m/s²", 2),
            ParamSpec("vel_leak", "速度泄漏系数", 0.04, 0.0, 0.5, 0.01, "", 2),
            ParamSpec("max_dt", "最大积分步长", 0.05, 0.01, 1.0, 0.01, "s", 2),
        ]

    def reset(self) -> None:
        self._t_prev: Optional[float] = None
        self._bias = [0.0, 0.0, 0.0]
        self._bias_sum = [0.0, 0.0, 0.0]
        self._bias_cnt = 0
        self._vel = [0.0, 0.0, 0.0]
        self._pos = [0.0, 0.0, 0.0]   # 单位 m，输出时 ×100 转 cm

    def _deadband(self, a: float) -> float:
        return 0.0 if abs(a) < self.param("acc_deadband") else a

    def update(self, t: float, x: float, y: float, z: float) -> Vec3:
        bias_n = int(self.param("bias_n", 50))
        # 阶段1：零偏估计（前 bias_n 帧只累计，不积分）
        if self._bias_cnt < bias_n:
            self._bias_sum[0] += x
            self._bias_sum[1] += y
            self._bias_sum[2] += z
            self._bias_cnt += 1
            if self._bias_cnt == bias_n and bias_n > 0:
                self._bias = [s / bias_n for s in self._bias_sum]
            self._t_prev = t
            return (0.0, 0.0, 0.0)

        # 阶段2：去偏 + 死区
        ax = self._deadband(x - self._bias[0])
        ay = self._deadband(y - self._bias[1])
        az = self._deadband(z - self._bias[2])

        if self._t_prev is not None:
            dt = t - self._t_prev
            if 0.0 < dt <= self.param("max_dt", 0.05):
                leak = 1.0 - self.param("vel_leak", 0.02)
                acc = (ax, ay, az)
                for i in range(3):
                    # 速度积分 + 泄漏抑漂
                    self._vel[i] = (self._vel[i] + acc[i] * dt) * leak
                    # 位移积分（m）
                    self._pos[i] += self._vel[i] * dt
        self._t_prev = t
        return (
            self._pos[0] * self._M_TO_CM,
            self._pos[1] * self._M_TO_CM,
            self._pos[2] * self._M_TO_CM,
        )
