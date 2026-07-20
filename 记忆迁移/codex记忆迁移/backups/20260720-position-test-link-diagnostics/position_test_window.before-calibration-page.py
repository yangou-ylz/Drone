# -*- coding: utf-8 -*-
"""位置测试独立功能页。"""
from __future__ import annotations

import time
from collections import deque
from math import sqrt
from typing import Deque, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.io.protocol import CMD_RPI_POSITION_MIRROR
from gui.services.telemetry_decoder import decode_rpi_position_mirror
from gui.services.telemetry_models import RpiPositionMirrorSample


_INVALID_S32 = -2147483648


class _Placeholder(QWidget):
    def __init__(self, title: str, text: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = QLabel(f"{title}\n{text}", self)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet("color:#888; font-size:14px;")
        lay.addWidget(label)


class _RealtimePage(QWidget):
    """实时数据页：显示解析后的 0xF6 字段。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._sample: Optional[RpiPositionMirrorSample] = None
        self._last_rx_wall = 0.0
        self._active = False
        self._link_connected = False
        self._total_frames = 0
        self._f6_frames = 0
        self._last_any_cmd: Optional[int] = None
        self._last_any_wall = 0.0
        self._recent_ts: Deque[float] = deque(maxlen=200)
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self._refresh()

    def set_link_connected(self, connected: bool) -> None:
        self._link_connected = bool(connected)
        if not connected:
            self._sample = None
            self._last_rx_wall = 0.0
            self._total_frames = 0
            self._f6_frames = 0
            self._last_any_cmd = None
            self._last_any_wall = 0.0
            self._recent_ts.clear()
        self._refresh()

    def on_any_frame(self, cmd: int) -> None:
        self._total_frames += 1
        self._last_any_cmd = int(cmd) & 0xFF
        self._last_any_wall = time.monotonic()
        self._refresh()

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        self._f6_frames += 1
        self._sample = sample
        self._last_rx_wall = time.monotonic()
        self._recent_ts.append(sample.ts)
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        status_box = QGroupBox("链路状态", self)
        status_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        grid = QGridLayout(status_box)
        grid.setHorizontalSpacing(16)
        grid.setVerticalSpacing(8)

        self._lbl_alive = self._make_value_label("等待 0xF6")
        self._lbl_rate = self._make_value_label("-- Hz")
        self._lbl_rx = self._make_value_label("--")
        self._lbl_err = self._make_value_label("--")
        for col, (name, widget) in enumerate((
            ("状态", self._lbl_alive),
            ("镜像帧率", self._lbl_rate),
            ("0xF5计数", self._lbl_rx),
            ("错误计数", self._lbl_err),
        )):
            title = QLabel(name, self)
            title.setStyleSheet("color:#888; font-size:12px;")
            grid.addWidget(title, 0, col)
            grid.addWidget(widget, 1, col)
        root.addWidget(status_box)

        self._table = QTableWidget(10, 3, self)
        self._table.setHorizontalHeaderLabels(["字段", "数值", "说明"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget{background:#232323; color:#DCDCDC; gridline-color:#3A3A3A;}"
            "QTableWidget::item{background:#232323; color:#DCDCDC;}"
            "QTableWidget::item:alternate{background:#2B2B2B; color:#DCDCDC;}"
            "QHeaderView::section{background:#333; color:#DCDCDC; padding:4px;}"
        )
        rows = [
            ("cur_x", "--", "当前位置 X，飞控坐标：前+，cm"),
            ("cur_y", "--", "当前位置 Y，飞控坐标：左+，cm"),
            ("cur_z", "--", "当前位置 Z，飞控坐标：上+，cm"),
            ("tar_x", "--", "目标 X，cm"),
            ("tar_y", "--", "目标 Y，cm"),
            ("tar_z", "--", "目标 Z，cm"),
            ("flags", "--", "bit0=SLAM_VALID, bit1=TARGET_VALID, bit2=VISUAL_MODE"),
            ("SLAM_VALID", "--", "0=SLAM无效，不应进入控制"),
            ("TARGET_VALID", "--", "0=目标无效，tar应等于cur或被忽略"),
            ("VISUAL_MODE", "--", "视觉目标模式标记"),
            ("GUI_RX_FRAMES", "--", "GUI本次连接已解析的全部匿名协议帧"),
            ("GUI_F6_FRAMES", "--", "GUI本次连接已解析的0xF6镜像帧"),
            ("LAST_CMD", "--", "最近收到的匿名协议CMD；有普通帧但无0xF6时用于定位"),
        ]
        self._table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, text in enumerate(row):
                item = QTableWidgetItem(text)
                if c == 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(r, c, item)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 120)
        self._table.setColumnWidth(1, 160)
        root.addWidget(self._table, 1)

    def _make_value_label(self, text: str) -> QLabel:
        lbl = QLabel(text, self)
        lbl.setStyleSheet("color:#4FC3F7; font-size:18px; font-weight:bold;")
        return lbl

    def _refresh(self) -> None:
        sample = self._sample
        now = time.monotonic()
        if not self._active:
            self._lbl_alive.setText("未激活")
            self._lbl_alive.setStyleSheet("color:#9E9E9E; font-size:18px; font-weight:bold;")
            self._lbl_rate.setText("-- Hz")
            self._lbl_rx.setText("--")
            self._lbl_err.setText("--")
            return
        if not self._link_connected:
            self._lbl_alive.setText("未连接串口")
            self._lbl_alive.setStyleSheet("color:#EF5350; font-size:18px; font-weight:bold;")
            self._lbl_rate.setText("-- Hz")
            self._lbl_rx.setText("--")
            self._lbl_err.setText("--")
            self._update_diag_rows()
            return
        if sample is None:
            if self._total_frames > 0:
                self._lbl_alive.setText("有遥测，无0xF6；检查树莓派发送程序")
            else:
                self._lbl_alive.setText("已连接，等待0xF6；需运行树莓派发送程序")
            self._lbl_alive.setStyleSheet("color:#FFCA28; font-size:18px; font-weight:bold;")
            self._lbl_rate.setText("-- Hz")
            self._lbl_rx.setText("--")
            self._lbl_err.setText("--")
            self._update_diag_rows()
            return

        age = now - self._last_rx_wall
        alive = age < 1.0
        self._lbl_alive.setText("实时" if alive else f"0xF6超时 {age:.1f}s")
        self._lbl_alive.setStyleSheet(
            ("color:#66BB6A;" if alive else "color:#EF5350;") +
            " font-size:18px; font-weight:bold;"
        )

        if len(self._recent_ts) >= 2:
            span = self._recent_ts[-1] - self._recent_ts[0]
            rate = (len(self._recent_ts) - 1) / span if span > 1e-6 else 0.0
            self._lbl_rate.setText(f"{rate:.1f} Hz")
        else:
            self._lbl_rate.setText("-- Hz")

        self._lbl_rx.setText(str(sample.rx_cnt))
        self._lbl_err.setText(f"LEN {sample.len_err_cnt} / CK {sample.checksum_err_cnt}")

        values = [
            sample.cur_x_cm,
            sample.cur_y_cm,
            sample.cur_z_cm,
            sample.tar_x_cm,
            sample.tar_y_cm,
            sample.tar_z_cm,
            f"0x{sample.flags:02X}",
            "YES" if sample.slam_valid else "NO",
            "YES" if sample.target_valid else "NO",
            "YES" if sample.visual_mode else "NO",
        ]
        for row, value in enumerate(values):
            item = self._table.item(row, 1)
            if item is not None:
                item.setText(str(value))
        self._update_diag_rows()

    def _set_value(self, row: int, value: object) -> None:
        item = self._table.item(row, 1)
        if item is not None:
            item.setText(str(value))

    def _update_diag_rows(self) -> None:
        if self._table.rowCount() < 13:
            return
        self._set_value(10, self._total_frames)
        self._set_value(11, self._f6_frames)
        if self._last_any_cmd is None:
            self._set_value(12, "--")
        else:
            age = time.monotonic() - self._last_any_wall if self._last_any_wall else 0.0
            self._set_value(12, f"0x{self._last_any_cmd:02X} ({age:.1f}s前)")


class _StabilityPage(QWidget):
    """静止稳定性页：统计 0xF6 当前坐标窗口内的抖动和链路跳变。"""

    _ROWS = (
        ("X 前+", 0),
        ("Y 左+", 1),
        ("Z 上+", 2),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._samples: Deque[RpiPositionMirrorSample] = deque(maxlen=5000)
        self._last_refresh = 0.0
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()
        self._refresh()

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        if not self._active:
            return
        self._samples.append(sample)
        now = time.monotonic()
        if now - self._last_refresh >= 0.2:
            self._last_refresh = now
            self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        control_box = QGroupBox("采样窗口", self)
        control_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        controls = QHBoxLayout(control_box)
        controls.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._window_s = QDoubleSpinBox(control_box)
        self._window_s.setRange(1.0, 120.0)
        self._window_s.setSingleStep(1.0)
        self._window_s.setDecimals(1)
        self._window_s.setSuffix(" s")
        self._window_s.setValue(10.0)
        self._window_s.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("统计窗口", self._window_s)

        self._jump_cm = QDoubleSpinBox(control_box)
        self._jump_cm.setRange(0.5, 200.0)
        self._jump_cm.setSingleStep(0.5)
        self._jump_cm.setDecimals(1)
        self._jump_cm.setSuffix(" cm")
        self._jump_cm.setValue(5.0)
        self._jump_cm.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("跳变阈值", self._jump_cm)
        controls.addLayout(form)

        self._btn_clear = QPushButton("清空样本", control_box)
        self._btn_clear.clicked.connect(self._clear)
        controls.addWidget(self._btn_clear)
        controls.addStretch(1)

        self._summary = QLabel("未激活", control_box)
        self._summary.setStyleSheet("color:#222; font-size:13px;")
        controls.addWidget(self._summary)
        root.addWidget(control_box)

        self._table = QTableWidget(len(self._ROWS), 7, self)
        self._table.setHorizontalHeaderLabels([
            "轴",
            "有效样本",
            "均值 cm",
            "标准差 cm",
            "峰峰值 cm",
            "最小 / 最大 cm",
            "跳变",
        ])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet(
            "QTableWidget{background:#232323; color:#DCDCDC; gridline-color:#3A3A3A;}"
            "QTableWidget::item{background:#232323; color:#DCDCDC;}"
            "QTableWidget::item:alternate{background:#2B2B2B; color:#DCDCDC;}"
            "QHeaderView::section{background:#333; color:#DCDCDC; padding:4px;}"
        )
        for r, (label, _idx) in enumerate(self._ROWS):
            self._table.setItem(r, 0, QTableWidgetItem(label))
            for c in range(1, 7):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(r, c, item)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 90)
        self._table.setColumnWidth(1, 90)
        self._table.setColumnWidth(2, 110)
        self._table.setColumnWidth(3, 110)
        self._table.setColumnWidth(4, 110)
        self._table.setColumnWidth(5, 150)
        root.addWidget(self._table, 1)

        note = QLabel(
            "说明：这里只统计 SLAM_VALID=1 且 cur_x/y/z 都不是 INVALID_S32 的样本；"
            "当前阶段只做观测诊断，不进入 PID 或控制输出。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9E9E9E; font-size:12px;")
        root.addWidget(note)

    def _clear(self) -> None:
        self._samples.clear()
        self._refresh()

    def _window_samples(self) -> list[RpiPositionMirrorSample]:
        if not self._samples:
            return []
        cutoff = self._samples[-1].ts - float(self._window_s.value())
        return [s for s in self._samples if s.ts >= cutoff]

    @staticmethod
    def _has_valid_cur(sample: RpiPositionMirrorSample) -> bool:
        return (
            sample.slam_valid
            and sample.cur_x_cm != _INVALID_S32
            and sample.cur_y_cm != _INVALID_S32
            and sample.cur_z_cm != _INVALID_S32
        )

    def _refresh(self) -> None:
        if not self._active:
            self._summary.setText("未激活")
            return

        window = self._window_samples()
        valid = [s for s in window if self._has_valid_cur(s)]
        invalid_count = len(window) - len(valid)
        rate = self._sample_rate(window)
        rx_jump = self._rx_jump_count(window)
        self._summary.setText(
            f"窗口 {float(self._window_s.value()):.1f}s | "
            f"样本 {len(window)} | 有效 {len(valid)} | 无效 {invalid_count} | "
            f"镜像 {rate:.1f}Hz | rx_cnt跳号/节流 {rx_jump}"
        )

        axis_values = [
            [s.cur_x_cm for s in valid],
            [s.cur_y_cm for s in valid],
            [s.cur_z_cm for s in valid],
        ]
        for row, values in enumerate(axis_values):
            stats = self._axis_stats(values)
            for col, text in enumerate(stats, start=1):
                item = self._table.item(row, col)
                if item is not None:
                    item.setText(text)

    @staticmethod
    def _sample_rate(samples: list[RpiPositionMirrorSample]) -> float:
        if len(samples) < 2:
            return 0.0
        span = samples[-1].ts - samples[0].ts
        return (len(samples) - 1) / span if span > 1e-6 else 0.0

    @staticmethod
    def _rx_jump_count(samples: list[RpiPositionMirrorSample]) -> int:
        if len(samples) < 2:
            return 0
        jumps = 0
        prev = samples[0].rx_cnt
        for sample in samples[1:]:
            gap = int(sample.rx_cnt) - int(prev)
            if gap > 1:
                jumps += gap - 1
            prev = sample.rx_cnt
        return jumps

    def _axis_stats(self, values: list[int]) -> list[str]:
        if not values:
            return ["0", "--", "--", "--", "--", "--"]
        count = len(values)
        mean = sum(values) / count
        variance = sum((v - mean) * (v - mean) for v in values) / count
        std = sqrt(variance)
        mn = min(values)
        mx = max(values)
        p2p = mx - mn
        jump_threshold = float(self._jump_cm.value())
        jumps = sum(
            1 for prev, cur in zip(values, values[1:])
            if abs(cur - prev) > jump_threshold
        )
        return [
            str(count),
            f"{mean:.1f}",
            f"{std:.2f}",
            f"{p2p:.1f}",
            f"{mn} / {mx}",
            str(jumps),
        ]


class PositionTestWindow(QWidget):
    """主菜单中的独立“位置测试”页面。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._link_connected = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._realtime = _RealtimePage(self)
        self._stability = _StabilityPage(self)
        self._tabs.addTab(self._realtime, "实时数据")
        self._tabs.addTab(
            _Placeholder("坐标标定", "下一阶段：A/B/C三点向导，计算ROS map到飞控X前/Y左的变换。", self),
            "坐标标定",
        )
        self._tabs.addTab(self._stability, "稳定性")
        self._tabs.addTab(
            _Placeholder("轨迹回放", "下一阶段：XY轨迹、X/Y/Z时间曲线、CSV/JSON导出。", self),
            "轨迹回放",
        )
        self._tabs.currentChanged.connect(lambda _idx: self._sync_page_activity())
        root.addWidget(self._tabs, 1)

        self._status = QLabel("位置测试：未激活", self)
        self._status.setContentsMargins(8, 2, 8, 2)
        self._status.setStyleSheet(
            "QLabel { border-top: 1px solid rgba(128,128,128,0.35); color:#999; }"
        )
        root.addWidget(self._status)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._sync_page_activity()
        self._realtime.set_link_connected(self._link_connected)
        self._status.setText(
            "位置测试：串口已连接，接收 0xF6 镜像帧"
            if active and self._link_connected
            else ("位置测试：请先连接数传串口" if active else "位置测试：未激活")
        )

    def set_link_connected(self, connected: bool) -> None:
        self._link_connected = bool(connected)
        self._realtime.set_link_connected(connected)
        if self._active:
            self._status.setText(
                "位置测试：串口已连接，接收 0xF6 镜像帧"
                if connected else "位置测试：请先连接数传串口"
            )

    def _sync_page_activity(self) -> None:
        active = bool(self._active)
        self._realtime.set_active(active)
        self._stability.set_active(active and self._tabs.currentWidget() is self._stability)

    @Slot(object)
    def on_frame(self, frame: object) -> None:
        if not self._active:
            return
        cmd = getattr(frame, "cmd", None)
        if cmd is None:
            return
        self._realtime.on_any_frame(int(cmd))
        if cmd != CMD_RPI_POSITION_MIRROR:
            return
        data = getattr(frame, "data", None)
        if data is None:
            return
        sample = decode_rpi_position_mirror(bytes(data))
        if sample is not None:
            self._realtime.on_sample(sample)
            self._stability.on_sample(sample)
