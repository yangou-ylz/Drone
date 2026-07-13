# -*- coding: utf-8 -*-
"""IMU 实时曲线面板（Phase 2.2）。

用 pyqtgraph 绘制滚动曲线：上图加速度(m/s²) X/Y/Z，下图角速度(rad/s) X/Y/Z。
时间窗口默认最近 _WINDOW_S 秒。

设计：
- 高频数据不逐帧重绘：on_imu_raw 只把样本塞进 deque(环形，maxlen 限长)；
  QTimer（默认 30Hz）统一取数据重设曲线，避免卡顿。
- 时间轴用相对秒（相对首样本），只显示最近窗口。
- 深色背景，X/Y/Z 用红/绿/蓝区分，带图例。
"""
from __future__ import annotations

from collections import deque
from typing import Deque

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QTimer, Slot
from PySide6.QtWidgets import QVBoxLayout, QWidget

from gui.imu_test.logger import get_logger

_WINDOW_S = 10.0          # 显示时间窗口（秒）
_REFRESH_MS = 33          # ~30Hz 重绘
_MAX_PTS = 4000           # 环形缓冲容量（10s@最高~200Hz*2 余量）

# X/Y/Z 曲线颜色
_COL_X = "#EF5350"
_COL_Y = "#66BB6A"
_COL_Z = "#42A5F5"

pg.setConfigOptions(antialias=True, background="#232323", foreground="#B0B0B0")


class ImuChartPanel(QWidget):
    """加速度 / 角速度实时滚动曲线。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()

        # 环形缓冲：时间戳 + 六路数据
        self._t: Deque[float] = deque(maxlen=_MAX_PTS)
        self._ax: Deque[float] = deque(maxlen=_MAX_PTS)
        self._ay: Deque[float] = deque(maxlen=_MAX_PTS)
        self._az: Deque[float] = deque(maxlen=_MAX_PTS)
        self._gx: Deque[float] = deque(maxlen=_MAX_PTS)
        self._gy: Deque[float] = deque(maxlen=_MAX_PTS)
        self._gz: Deque[float] = deque(maxlen=_MAX_PTS)
        self._t0 = None  # 首样本时间戳

        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)

        # ---- 加速度图 ----
        self._plot_acc = pg.PlotWidget()
        self._plot_acc.setTitle("加速度 (m/s²)", color="#DCDCDC", size="11pt")
        self._plot_acc.showGrid(x=True, y=True, alpha=0.25)
        self._plot_acc.addLegend(offset=(10, 10))
        self._plot_acc.setLabel("bottom", "时间", units="s")
        self._c_ax = self._plot_acc.plot(pen=pg.mkPen(_COL_X, width=1.5), name="X")
        self._c_ay = self._plot_acc.plot(pen=pg.mkPen(_COL_Y, width=1.5), name="Y")
        self._c_az = self._plot_acc.plot(pen=pg.mkPen(_COL_Z, width=1.5), name="Z")
        lay.addWidget(self._plot_acc, 1)

        # ---- 角速度图 ----
        self._plot_gyr = pg.PlotWidget()
        self._plot_gyr.setTitle("角速度 (rad/s)", color="#DCDCDC", size="11pt")
        self._plot_gyr.showGrid(x=True, y=True, alpha=0.25)
        self._plot_gyr.addLegend(offset=(10, 10))
        self._plot_gyr.setLabel("bottom", "时间", units="s")
        self._plot_gyr.setXLink(self._plot_acc)  # X 轴联动
        self._c_gx = self._plot_gyr.plot(pen=pg.mkPen(_COL_X, width=1.5), name="X")
        self._c_gy = self._plot_gyr.plot(pen=pg.mkPen(_COL_Y, width=1.5), name="Y")
        self._c_gz = self._plot_gyr.plot(pen=pg.mkPen(_COL_Z, width=1.5), name="Z")
        lay.addWidget(self._plot_gyr, 1)

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---- 数据入口 ----
    @Slot(object)
    def on_imu_raw(self, s: object) -> None:
        if self._t0 is None:
            self._t0 = s.ts
        self._t.append(s.ts - self._t0)
        self._ax.append(s.acc_x)
        self._ay.append(s.acc_y)
        self._az.append(s.acc_z)
        self._gx.append(s.gyr_x)
        self._gy.append(s.gyr_y)
        self._gz.append(s.gyr_z)

    def clear(self) -> None:
        for dq in (self._t, self._ax, self._ay, self._az, self._gx, self._gy, self._gz):
            dq.clear()
        self._t0 = None
        for c in (self._c_ax, self._c_ay, self._c_az, self._c_gx, self._c_gy, self._c_gz):
            c.setData([], [])

    # ---- 刷新 ----
    def _refresh(self) -> None:
        if not self._t:
            return
        t = np.fromiter(self._t, dtype=float)
        tmax = t[-1]
        tmin = tmax - _WINDOW_S
        mask = t >= tmin
        t_win = t[mask]
        self._c_ax.setData(t_win, np.fromiter(self._ax, dtype=float)[mask])
        self._c_ay.setData(t_win, np.fromiter(self._ay, dtype=float)[mask])
        self._c_az.setData(t_win, np.fromiter(self._az, dtype=float)[mask])
        self._c_gx.setData(t_win, np.fromiter(self._gx, dtype=float)[mask])
        self._c_gy.setData(t_win, np.fromiter(self._gy, dtype=float)[mask])
        self._c_gz.setData(t_win, np.fromiter(self._gz, dtype=float)[mask])
        self._plot_acc.setXRange(tmin, tmax, padding=0.02)
