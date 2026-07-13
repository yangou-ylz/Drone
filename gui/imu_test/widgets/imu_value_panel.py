# -*- coding: utf-8 -*-
"""IMU 实时数值面板（Phase 2.1）。

订阅 ImuDataHub.imu_raw / attitude，用紧凑表格实时显示：
加速度(m/s²)+原始LSB、角速度(rad/s & °/s)、加速度模长、姿态角、震动标志。

设计：
- 高频数据不直接刷 UI：on_imu_raw/on_attitude 只缓存最新样本；
  QTimer（默认 20Hz）统一把最新值写进表格，避免 UI 抖动/卡顿。
- 表格行固定、只改单元格文本，不重建行。
"""
from __future__ import annotations

import math
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.logger import get_logger

_REFRESH_MS = 50  # 20Hz UI 刷新

# 行定义：(键, 显示名, 单位)。键用于 _set 定位行。
_ROWS = (
    ("acc_x", "加速度 X", "m/s²"),
    ("acc_y", "加速度 Y", "m/s²"),
    ("acc_z", "加速度 Z", "m/s²"),
    ("acc_norm", "加速度模长 |a|", "m/s²"),
    ("gyr_x", "角速度 X", "rad/s"),
    ("gyr_y", "角速度 Y", "rad/s"),
    ("gyr_z", "角速度 Z", "rad/s"),
    ("roll", "横滚 Roll", "°"),
    ("pitch", "俯仰 Pitch", "°"),
    ("yaw", "偏航 Yaw", "°"),
    ("shock", "震动标志", ""),
)

_COL_TEXT = QColor("#DCDCDC")
_COL_DIM = QColor("#8a8a8a")
_COL_ACCENT = QColor("#4FC3F7")


class ImuValuePanel(QWidget):
    """IMU 实时数值表格面板。"""

    _HEADERS = ("物理量", "数值", "单位", "原始(LSB)")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._last_raw = None       # 最新 ImuRawSample
        self._last_att = None       # 最新 AttitudeSample
        self._row_index = {key: i for i, (key, _n, _u) in enumerate(_ROWS)}

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._table = QTableWidget(len(_ROWS), len(self._HEADERS), self)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setAlternatingRowColors(True)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for c in range(1, len(self._HEADERS)):
            hdr.setSectionResizeMode(c, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setStyleSheet(
            "QTableWidget { background-color: #232323; gridline-color: #3a3a3a;"
            " color: #DCDCDC; font-size: 13px; }"
            "QHeaderView::section { background-color: #333; color: #DCDCDC;"
            " padding: 4px 8px; border: none; border-right: 1px solid #3a3a3a; }"
            "QTableWidget::item { padding: 2px 8px; }"
        )
        # 建行
        for key, name, unit in _ROWS:
            r = self._row_index[key]
            it_name = QTableWidgetItem(name)
            it_val = QTableWidgetItem("--")
            it_unit = QTableWidgetItem(unit)
            it_raw = QTableWidgetItem("--")
            it_val.setForeground(_COL_ACCENT)
            it_unit.setForeground(_COL_DIM)
            it_raw.setForeground(_COL_DIM)
            for it in (it_val, it_unit, it_raw):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._table.setItem(r, 0, it_name)
            self._table.setItem(r, 1, it_val)
            self._table.setItem(r, 2, it_unit)
            self._table.setItem(r, 3, it_raw)
        lay.addWidget(self._table)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---- 数据入口 ----
    @Slot(object)
    def on_imu_raw(self, sample: object) -> None:
        self._last_raw = sample

    @Slot(object)
    def on_attitude(self, sample: object) -> None:
        self._last_att = sample

    def clear(self) -> None:
        self._last_raw = None
        self._last_att = None
        for key, _n, _u in _ROWS:
            r = self._row_index[key]
            self._table.item(r, 1).setText("--")
            self._table.item(r, 3).setText("--")

    # ---- 刷新 ----
    def _set(self, key: str, val_text: str, raw_text: Optional[str] = None) -> None:
        r = self._row_index[key]
        self._table.item(r, 1).setText(val_text)
        if raw_text is not None:
            self._table.item(r, 3).setText(raw_text)

    def _refresh(self) -> None:
        s = self._last_raw
        if s is not None:
            self._set("acc_x", f"{s.acc_x:+.3f}", str(s.raw_acc[0]))
            self._set("acc_y", f"{s.acc_y:+.3f}", str(s.raw_acc[1]))
            self._set("acc_z", f"{s.acc_z:+.3f}", str(s.raw_acc[2]))
            norm = math.sqrt(s.acc_x ** 2 + s.acc_y ** 2 + s.acc_z ** 2)
            self._set("acc_norm", f"{norm:.3f}", "")
            # 角速度：rad/s 主值 + 括号里 °/s 便于直观
            self._set("gyr_x", f"{s.gyr_x:+.4f}  ({math.degrees(s.gyr_x):+.1f}°/s)", str(s.raw_gyr[0]))
            self._set("gyr_y", f"{s.gyr_y:+.4f}  ({math.degrees(s.gyr_y):+.1f}°/s)", str(s.raw_gyr[1]))
            self._set("gyr_z", f"{s.gyr_z:+.4f}  ({math.degrees(s.gyr_z):+.1f}°/s)", str(s.raw_gyr[2]))
            self._set("shock", str(s.shock), "")
        a = self._last_att
        if a is not None:
            self._set("roll", f"{a.roll_deg:+.2f}", "")
            self._set("pitch", f"{a.pitch_deg:+.2f}", "")
            self._set("yaw", f"{a.yaw_deg:+.2f}", "")
