# -*- coding: utf-8 -*-
"""IMU 测试台主窗口（Phase 6 接线整合）。

布局（用户 2026-07-12 已确认 5 Tab）：
- 顶部横向页签 QTabWidget：实时总览 / 曲线监控 / Yaw跟随 / 静态校准 / 质量报告
- 底部状态栏：数据流帧率 / 已采集帧数 / 时间

各 Tab 内容：
- 实时总览：左=帧率面板+数值面板(上下)，右=3D姿态（此内部排布为默认，可调）
- 曲线监控：加速度/角速度实时曲线
- Yaw跟随：Yaw 跟随/回弹测试
- 静态校准 / 质量报告：占位（Phase 4/5 填充）

各面板通过 ImuDataHub 的 Qt 信号解耦订阅；无 hub 时仍可显示空布局。
"""
from __future__ import annotations

import time
from datetime import datetime

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QLabel,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.logger import get_logger
from gui.imu_test.widgets.attitude_3d_panel import Attitude3DPanel
from gui.imu_test.widgets.calibration_panel import CalibrationPanel
from gui.imu_test.widgets.device_calibration_panel import DeviceCalibrationPanel
from gui.imu_test.widgets.frame_rate_panel import FrameRatePanel
from gui.imu_test.widgets.imu_chart_panel import ImuChartPanel
from gui.imu_test.widgets.imu_value_panel import ImuValuePanel
from gui.imu_test.widgets.quality_report_panel import QualityReportPanel
from gui.imu_test.widgets.yaw_test_panel import YawTestPanel

# Tab 定义：(内部键, 显示标题)。顺序即页签顺序。
_TABS = (
    ("overview", "实时总览"),
    ("charts", "曲线监控"),
    ("yaw", "Yaw跟随"),
    ("roll", "Roll跟随"),
    ("pitch", "Pitch跟随"),
    ("calibration", "静态校准"),
    ("device_cal", "设备校准"),
    ("quality", "质量报告"),
)


class _PlaceholderTab(QWidget):
    """占位 Tab 页：居中提示「开发中」，Phase 推进时替换为真实面板。"""

    def __init__(self, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip = QLabel(f"「{title}」面板 · 开发中", self)
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tip.setStyleSheet("color: #888; font-size: 14px;")
        lay.addWidget(tip)


class ImuTestWindow(QWidget):
    """IMU 数据质量测试台（顶层容器，嵌入主窗口 QStackedWidget）。"""

    def __init__(self, data_hub=None, parent: QWidget | None = None, send_frame_fn=None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._hub = data_hub
        self._send_frame_fn = send_frame_fn
        self._frame_count = 0
        self._recent_ts: list[float] = []  # 最近帧时间戳，用于估算总帧率

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部横向页签 ----
        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._tab_pages: dict[str, QWidget] = {}

        # 各面板实例
        self._frame_rate_panel = FrameRatePanel(self)
        self._value_panel = ImuValuePanel(self)
        self._attitude_panel = Attitude3DPanel(self)
        self._chart_panel = ImuChartPanel(self)
        self._yaw_panel = YawTestPanel(self, axis="yaw")
        self._roll_panel = YawTestPanel(self, axis="roll")
        self._pitch_panel = YawTestPanel(self, axis="pitch")
        self._calibration_panel = CalibrationPanel(data_hub, self)
        self._device_cal_panel = DeviceCalibrationPanel(send_frame_fn, self)
        self._quality_panel = QualityReportPanel(data_hub, self)

        for key, title in _TABS:
            page = self._build_tab(key, title)
            self._tabs.addTab(page, title)
            self._tab_pages[key] = page
        root.addWidget(self._tabs, 1)

        # ---- 底部状态栏 ----
        self._status = QLabel(self)
        self._status.setContentsMargins(8, 2, 8, 2)
        self._status.setStyleSheet(
            "QLabel { border-top: 1px solid rgba(128,128,128,0.35); color: #999; }"
        )
        root.addWidget(self._status)
        self._update_status(fps=0.0, frames=0)

        # ---- 订阅 DataHub 信号 ----
        if self._hub is not None:
            self._hub.frame_seen.connect(self._on_frame_seen)
            self._hub.imu_raw.connect(self._value_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._chart_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._yaw_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._roll_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._pitch_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._calibration_panel.on_imu_raw)
            self._hub.imu_raw.connect(self._quality_panel.on_imu_raw)
            self._hub.attitude.connect(self._value_panel.on_attitude)
            self._hub.attitude.connect(self._attitude_panel.on_attitude)
            self._hub.attitude.connect(self._yaw_panel.on_attitude)
            self._hub.attitude.connect(self._roll_panel.on_attitude)
            self._hub.attitude.connect(self._pitch_panel.on_attitude)
            self._hub.attitude.connect(self._quality_panel.on_attitude)
            self._hub.quat_norm.connect(self._quality_panel.on_quat_norm)
            self._hub.log_text.connect(self._device_cal_panel.on_log_text)
            self._log.info("IMU 测试台已接入 DataHub")

        # 状态栏定时刷新
        self._status_timer = QTimer(self)
        self._status_timer.setInterval(500)
        self._status_timer.timeout.connect(self._refresh_status)
        self._status_timer.start()

        self._log.info("IMU 测试台窗口已创建（%d 个 Tab）", len(_TABS))

    # ---- Tab 构建 ----
    def _build_tab(self, key: str, title: str) -> QWidget:
        if key == "overview":
            outer = QSplitter(Qt.Orientation.Horizontal, self)
            left = QSplitter(Qt.Orientation.Vertical, self)
            left.addWidget(self._frame_rate_panel)
            left.addWidget(self._value_panel)
            left.setSizes([220, 420])
            outer.addWidget(left)
            outer.addWidget(self._attitude_panel)
            outer.setSizes([420, 520])
            return outer
        if key == "charts":
            return self._chart_panel
        if key == "yaw":
            return self._yaw_panel
        if key == "roll":
            return self._roll_panel
        if key == "pitch":
            return self._pitch_panel
        if key == "calibration":
            return self._calibration_panel
        if key == "device_cal":
            return self._device_cal_panel
        if key == "quality":
            return self._quality_panel
        return _PlaceholderTab(title, self)

    # ---- 信号槽 ----
    @Slot(int, float)
    def _on_frame_seen(self, cmd: int, ts: float) -> None:
        self._frame_count += 1
        self._recent_ts.append(ts)
        # 帧率信息同时喂给帧率面板
        self._frame_rate_panel.on_frame_seen(cmd, ts)

    def _refresh_status(self) -> None:
        now = time.monotonic()
        self._recent_ts = [t for t in self._recent_ts if now - t <= 2.0]
        fps = 0.0
        if len(self._recent_ts) >= 2:
            span = self._recent_ts[-1] - self._recent_ts[0]
            if span > 0:
                fps = (len(self._recent_ts) - 1) / span
        self._update_status(fps=fps, frames=self._frame_count)

    def _update_status(self, fps: float, frames: int) -> None:
        now = datetime.now().strftime("%H:%M:%S")
        self._status.setText(
            f"● 数据流 {fps:5.1f} Hz    |    已采集 {frames} 帧    |    {now}"
        )

    def tab_page(self, key: str) -> QWidget | None:
        """按键获取 Tab 页控件。"""
        return self._tab_pages.get(key)
