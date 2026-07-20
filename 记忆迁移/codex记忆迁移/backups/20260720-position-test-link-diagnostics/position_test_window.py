# -*- coding: utf-8 -*-
"""位置测试独立功能页。"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.io.protocol import CMD_RPI_POSITION_MIRROR
from gui.services.telemetry_decoder import decode_rpi_position_mirror
from gui.services.telemetry_models import RpiPositionMirrorSample


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
        self._recent_ts: Deque[float] = deque(maxlen=200)
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._refresh)

    def set_active(self, active: bool) -> None:
        if active:
            if not self._timer.isActive():
                self._timer.start()
        else:
            self._timer.stop()

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
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
        ]
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
        if sample is None:
            self._lbl_alive.setText("等待 0xF6")
            self._lbl_alive.setStyleSheet("color:#FFCA28; font-size:18px; font-weight:bold;")
            return

        age = now - self._last_rx_wall
        alive = age < 1.0
        self._lbl_alive.setText("实时" if alive else f"超时 {age:.1f}s")
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


class PositionTestWindow(QWidget):
    """主菜单中的独立“位置测试”页面。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._tabs = QTabWidget(self)
        self._tabs.setDocumentMode(True)
        self._realtime = _RealtimePage(self)
        self._tabs.addTab(self._realtime, "实时数据")
        self._tabs.addTab(
            _Placeholder("坐标标定", "下一阶段：A/B/C三点向导，计算ROS map到飞控X前/Y左的变换。", self),
            "坐标标定",
        )
        self._tabs.addTab(
            _Placeholder("稳定性", "下一阶段：静止窗口均值、标准差、峰峰值、跳变和丢帧统计。", self),
            "稳定性",
        )
        self._tabs.addTab(
            _Placeholder("轨迹回放", "下一阶段：XY轨迹、X/Y/Z时间曲线、CSV/JSON导出。", self),
            "轨迹回放",
        )
        root.addWidget(self._tabs, 1)

        self._status = QLabel("位置测试：未激活", self)
        self._status.setContentsMargins(8, 2, 8, 2)
        self._status.setStyleSheet(
            "QLabel { border-top: 1px solid rgba(128,128,128,0.35); color:#999; }"
        )
        root.addWidget(self._status)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._realtime.set_active(active)
        self._status.setText("位置测试：接收 0xF6 镜像帧" if active else "位置测试：未激活")

    @Slot(object)
    def on_frame(self, frame: object) -> None:
        if not self._active:
            return
        if getattr(frame, "cmd", None) != CMD_RPI_POSITION_MIRROR:
            return
        data = getattr(frame, "data", None)
        if data is None:
            return
        sample = decode_rpi_position_mirror(bytes(data))
        if sample is not None:
            self._realtime.on_sample(sample)
