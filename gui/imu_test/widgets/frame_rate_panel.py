# -*- coding: utf-8 -*-
"""帧率监控面板（Phase 1.2）。

订阅 ImuDataHub.frame_seen(cmd, ts)，用滑动时间窗口统计每类帧的实时频率，
以紧凑表格展示：帧类型 / 帧ID / 频率(Hz) / 累计 / 状态。

设计：
- 统计与刷新解耦：frame_seen 只往各 cmd 的 deque 里塞时间戳（O(1)）；
  QTimer 定时（默认 4Hz）重算 Hz 并刷新表格，避免高频帧触发 UI 抖动。
- 频率 = 窗口内帧数 / 窗口时间跨度（滑动窗口 _WINDOW_S 秒）。
- 已知关键帧预置期望频率，状态用颜色标注达标/偏低/掉线。
"""
from __future__ import annotations

import time
from collections import deque
from typing import Deque, Dict

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

# 滑动窗口长度（秒）：越长越平滑，越短越灵敏
_WINDOW_S = 2.0
# UI 刷新周期（毫秒）
_REFRESH_MS = 250
# 超过该时间没收到帧则视为掉线（秒）
_STALE_S = 1.5

# 已知帧：cmd -> (显示名, 期望频率Hz 或 None)
_FRAME_INFO: Dict[int, tuple] = {
    0x01: ("IMU 原始 (acc/gyr)", 100.0),
    0x02: ("气压/磁力", 20.0),
    0x03: ("欧拉角", None),
    0x04: ("四元数姿态", 67.0),
    0x05: ("融合高度", 50.0),
    0x06: ("飞控状态", 20.0),
    0x07: ("飞行速度", 50.0),
    0x08: ("XY 位移", 20.0),
    0x0D: ("电池", None),
    0xA0: ("日志字符串", None),
}

# 状态颜色
_COL_OK = QColor("#4CAF50")      # 达标（≥ 期望×0.8）
_COL_LOW = QColor("#FFB300")     # 偏低
_COL_STALE = QColor("#9E9E9E")   # 掉线/无期望时的普通灰
_COL_TEXT = QColor("#DCDCDC")


class FrameRatePanel(QWidget):
    """实时帧率监控表格面板。"""

    _HEADERS = ("帧类型", "帧ID", "频率(Hz)", "累计", "状态")

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        # 每个 cmd 的时间戳滑动窗口 + 累计计数 + 最近一次到达时刻
        self._windows: Dict[int, Deque[float]] = {}
        self._totals: Dict[int, int] = {}
        self._last_ts: Dict[int, float] = {}
        self._row_of: Dict[int, int] = {}  # cmd -> 表格行号

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)

        self._table = QTableWidget(0, len(self._HEADERS), self)
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self._table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table.setShowGrid(True)
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
        lay.addWidget(self._table)

        # 刷新定时器
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---- 数据入口（连接 ImuDataHub.frame_seen）----
    @Slot(int, float)
    def on_frame_seen(self, cmd: int, ts: float) -> None:
        dq = self._windows.get(cmd)
        if dq is None:
            dq = deque()
            self._windows[cmd] = dq
            self._totals[cmd] = 0
        dq.append(ts)
        self._totals[cmd] += 1
        self._last_ts[cmd] = ts

    def clear(self) -> None:
        """清空统计（切换测试时用）。"""
        self._windows.clear()
        self._totals.clear()
        self._last_ts.clear()
        self._row_of.clear()
        self._table.setRowCount(0)

    # ---- 定时刷新 ----
    def _refresh(self) -> None:
        now = time.monotonic()
        cutoff = now - _WINDOW_S
        for cmd in sorted(self._windows.keys()):
            dq = self._windows[cmd]
            while dq and dq[0] < cutoff:
                dq.popleft()
            # 频率：窗口内帧数 / 实际跨度（不足一窗按已有跨度）
            if len(dq) >= 2:
                span = dq[-1] - dq[0]
                hz = (len(dq) - 1) / span if span > 1e-6 else 0.0
            else:
                hz = 0.0
            last = self._last_ts.get(cmd, 0.0)
            stale = (now - last) > _STALE_S
            self._update_row(cmd, hz, self._totals.get(cmd, 0), stale)

    def _update_row(self, cmd: int, hz: float, total: int, stale: bool) -> None:
        name, expect = _FRAME_INFO.get(cmd, (f"未知帧", None))
        row = self._row_of.get(cmd)
        if row is None:
            row = self._table.rowCount()
            self._table.insertRow(row)
            self._row_of[cmd] = row
            for c in range(len(self._HEADERS)):
                it = QTableWidgetItem()
                if c >= 1:
                    it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                self._table.setItem(row, c, it)
            self._table.item(row, 0).setText(name)
            self._table.item(row, 1).setText(f"0x{cmd:02X}")

        # 频率 / 累计
        self._table.item(row, 2).setText("--" if stale else f"{hz:5.1f}")
        self._table.item(row, 3).setText(str(total))

        # 状态判定
        status_item = self._table.item(row, 4)
        hz_item = self._table.item(row, 2)
        if stale:
            status_item.setText("掉线")
            status_item.setForeground(_COL_STALE)
            hz_item.setForeground(_COL_STALE)
        elif expect is None:
            status_item.setText("正常")
            status_item.setForeground(_COL_OK)
            hz_item.setForeground(_COL_TEXT)
        elif hz >= expect * 0.8:
            status_item.setText("达标")
            status_item.setForeground(_COL_OK)
            hz_item.setForeground(_COL_OK)
        else:
            status_item.setText(f"偏低(期望{expect:.0f})")
            status_item.setForeground(_COL_LOW)
            hz_item.setForeground(_COL_LOW)
