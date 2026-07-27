# -*- coding: utf-8 -*-
"""P2 TelemetryBus：把 SerialWorker 的 frame 转成 typed sample → 喂 PathTracker → 节流广播。

设计要点（与 master_plan D2 / D3 / D9 对齐）：
- 永远做：解码 + 缓存 + 积分（功能关闭时也照样后台运行，避免开关时跳变）
- 仅节流：path_updated 信号在功能启用 + 渲染帧率窗口内才发
- 单 Qt 线程：本对象生存于主线程，被 SerialWorker.frame_received 主线程槽调用
- 失败容忍：任何解码异常被捕获并通过 status 信号汇报，不打断飞控数据流
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QObject, Signal

from gui.io.protocol import Frame
from gui.services.path_tracker import PathTracker
from gui.services.telemetry_decoder import (
    decode_auto_mission_status,
    decode_attitude_euler,
    decode_attitude_quat,
    decode_battery,
    decode_flight_mode,
    decode_gen_distance,
    decode_gen_position,
    decode_gen_velocity,
    decode_height,
    decode_module_status,
    decode_velocity,
)
from gui.services.telemetry_models import PathTrackerConfig

# 状态级别：与 ConfigService / 日志窗保持一致
STATUS_INFO = 0
STATUS_WARN = 1
STATUS_ERROR = 2


class TelemetryBus(QObject):
    # 原始 typed 样本（其他 Dock 可订阅，例如姿态指针）
    attitude_updated = Signal(object)   # AttitudeSample
    velocity_updated = Signal(object)   # VelocitySample
    height_updated = Signal(object)     # HeightSample
    # 主界面通用数据面板订阅（飞行状态/电池/外接传感器）
    flight_mode_updated = Signal(object)   # FlightModeSample (0x06)
    battery_updated = Signal(object)       # BatterySample (0x0D)
    module_status_updated = Signal(object) # ModuleStatusSample (0x0E)
    gen_position_updated = Signal(object)  # GenPositionSample (0x32)
    gen_velocity_updated = Signal(object)  # GenVelocitySample (0x33)
    gen_distance_updated = Signal(object)  # GenDistanceSample (0x34)
    auto_mission_status_updated = Signal(object)  # AutoMissionStatusSample (0xF8)
    # 路径快照（PathSnapshot），仅在 render_enabled=True 且超过节流窗时发
    path_updated = Signal(object)
    # 状态/告警（level, text）
    status = Signal(int, str)

    def __init__(self, config: Optional[PathTrackerConfig] = None, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._tracker = PathTracker(config)
        self._render_enabled = False
        self._render_fps = 30
        self._min_emit_interval = 1.0 / float(self._render_fps)
        self._last_emit_ts: float = 0.0
        # P6 节流统计（需要时调 reset_throttle_stats() 清零；smoke / 压测会读）
        self._emit_count: int = 0
        self._drop_count: int = 0
        # 0x04 优先策略：若最近 0.5s 内收过 0x04（quat），就忽略 0x03 防抖
        self._last_quat_ts: float = 0.0
        self._quat_ttl: float = 0.5

    # ---- 配置 / 控制 ----
    @property
    def tracker(self) -> PathTracker:
        return self._tracker

    def set_render_enabled(self, enabled: bool) -> None:
        """切换"路径可视化"渲染开关。只影响 path_updated 是否对外广播 + 是否积分。"""
        if enabled == self._render_enabled:
            return
        self._render_enabled = enabled
        if enabled:
            self._tracker.enable()
            self.status.emit(STATUS_INFO, "路径可视化：启动（已快照 yaw0）")
        else:
            self._tracker.disable()
            self.status.emit(STATUS_INFO, "路径可视化：暂停")
        # 主动发一次快照让前端立即反应（关时也发一次"final"快照）
        self.path_updated.emit(self._tracker.snapshot())
        self._last_emit_ts = time.monotonic()

    def set_render_fps(self, fps: int) -> None:
        fps = max(1, min(120, int(fps)))
        self._render_fps = fps
        self._min_emit_interval = 1.0 / float(fps)

    def reset_throttle_stats(self) -> None:
        """清零 emit/drop 计数。压测/smoke 在开始采集前调一次。"""
        self._emit_count = 0
        self._drop_count = 0

    def get_throttle_stats(self) -> dict:
        """返回当前节流统计：emit/drop 次数 + 当前 render_fps。"""
        return {
            "emit": self._emit_count,
            "drop": self._drop_count,
            "fps": self._render_fps,
            "interval_s": self._min_emit_interval,
        }

    def reset_path(self) -> None:
        self._tracker.reset()
        self.status.emit(STATUS_INFO, "路径可视化：已重置轨迹")
        self.path_updated.emit(self._tracker.snapshot())
        self._last_emit_ts = time.monotonic()

    def update_config(self, cfg: PathTrackerConfig) -> None:
        self._tracker.update_config(cfg)

    # ---- 数据入口 ----
    def feed_frame(self, fr: Frame) -> None:
        """主入口：从 SerialWorker.frame_received 槽调用。任何异常都不抛。"""
        try:
            cmd = fr.cmd
            data = fr.data
            now = time.monotonic()
            if cmd == 0x04:
                sample = decode_attitude_quat(data, now)
                if sample is None:
                    return
                self._last_quat_ts = now
                # 积分只在路径可视化开启时进行，避免 100Hz 后台空算
                if self._render_enabled:
                    self._tracker.on_attitude(sample)
                    self._maybe_emit_path()
                self.attitude_updated.emit(sample)
            elif cmd == 0x03:
                # 若近 0.5s 内已有 0x04，跳过 0x03（quat 优先）
                if now - self._last_quat_ts < self._quat_ttl:
                    return
                sample = decode_attitude_euler(data, now)
                if sample is None:
                    return
                if self._render_enabled:
                    self._tracker.on_attitude(sample)
                    self._maybe_emit_path()
                self.attitude_updated.emit(sample)
            elif cmd == 0x05:
                sample = decode_height(data, now)
                if sample is None:
                    return
                if self._render_enabled:
                    self._tracker.on_height(sample)
                    self._maybe_emit_path()
                self.height_updated.emit(sample)
            elif cmd == 0x07:
                sample = decode_velocity(data, now)
                if sample is None:
                    return
                if self._render_enabled:
                    self._tracker.on_velocity(sample)
                    self._maybe_emit_path()
                self.velocity_updated.emit(sample)
            elif cmd == 0x06:
                sample = decode_flight_mode(data, now)
                if sample is not None:
                    self.flight_mode_updated.emit(sample)
            elif cmd == 0x0D:
                sample = decode_battery(data, now)
                if sample is not None:
                    self.battery_updated.emit(sample)
            elif cmd == 0x0E:
                sample = decode_module_status(data, now)
                if sample is not None:
                    self.module_status_updated.emit(sample)
            elif cmd == 0x32:
                sample = decode_gen_position(data, now)
                if sample is not None:
                    self.gen_position_updated.emit(sample)
            elif cmd == 0x33:
                sample = decode_gen_velocity(data, now)
                if sample is not None:
                    self.gen_velocity_updated.emit(sample)
            elif cmd == 0x34:
                sample = decode_gen_distance(data, now)
                if sample is not None:
                    self.gen_distance_updated.emit(sample)
            elif cmd == 0xF8:
                sample = decode_auto_mission_status(data, now)
                if sample is not None:
                    self.auto_mission_status_updated.emit(sample)
            else:
                return  # 其余 cmd 不在关注范围
        except Exception as exc:  # 永不向上抛
            self.status.emit(STATUS_WARN, f"TelemetryBus 解码异常: {exc!r}")

    # ---- 节流广播 ----
    def _maybe_emit_path(self) -> None:
        if not self._render_enabled:
            return
        now = time.monotonic()
        if now - self._last_emit_ts < self._min_emit_interval:
            self._drop_count += 1
            return
        # P6#2 异常隔离：snapshot / emit 任一失败都不影响后续帧的节流计数推进
        try:
            snap = self._tracker.snapshot()
            self._last_emit_ts = now
            self._emit_count += 1
            self.path_updated.emit(snap)
        except Exception as exc:
            # 失败仍要推进 last_emit_ts，避免下一帧立刻重试又失败
            self._last_emit_ts = now
            self.status.emit(STATUS_WARN, f"路径快照/广播异常: {exc!r}")
