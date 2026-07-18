# -*- coding: utf-8 -*-
"""线速度（Vx / Vy / Vz）观测测试面板。

功能目标（2026-07-13）：
- 实时显示 vx/vy/vz 三轴曲线（0x07 帧，cm/s）
- 记录统计指标：最大值、最小值、均值、标准差、峰峰值
- "装填"后才开始记录，按需随时"停止记录"并查看结果
- 导出全部已记录样本为 CSV（含 t_rel_s, vx, vy, vz）

数据来源：ImuDataHub.velocity 信号（VelocitySample.vx_cmps / vy_cmps / vz_cmps）

说明（对应用户观察到的现象）：
- vz 静止时始终在 ±2 cm/s 左右徘徊：IMU 融合高度方向噪声正常现象
- vx/vy 停止后出现反向脉冲（如 vy 从 +26 → −5 → 0）：IMU 内部 ZUPT 残差，
  不是 GUI 问题，后续接光流后会改善，本面板用于量化观察该现象
"""
from __future__ import annotations

import csv
import math
import os
import time
from collections import deque
from typing import Deque, Optional

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.logger import get_logger

_REFRESH_MS = 33        # 绘图刷新 ~30Hz
_MAX_PTS    = 9000      # 最多保留 ~90s @ 100Hz

# 三轴颜色
_COL_VX = "#EF5350"    # 红
_COL_VY = "#66BB6A"    # 绿
_COL_VZ = "#42A5F5"    # 蓝
_COL_ZERO = "#888888"  # 零基准线

# 相位
PH_IDLE  = "未装填"
PH_REC   = "记录中"
PH_DONE  = "完成"

pg.setConfigOptions(antialias=True, background="#232323", foreground="#B0B0B0")


class VelocityTestPanel(QWidget):
    """线速度观测测试面板（Vx / Vy / Vz 三轴）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._phase = PH_IDLE
        self._t_arm = 0.0

        # 滚动缓冲：(t_rel_s, vx, vy, vz)
        self._ts:  Deque[float] = deque(maxlen=_MAX_PTS)
        self._vxs: Deque[float] = deque(maxlen=_MAX_PTS)
        self._vys: Deque[float] = deque(maxlen=_MAX_PTS)
        self._vzs: Deque[float] = deque(maxlen=_MAX_PTS)

        # 最新一帧（用于指标实时刷新）
        self._cur_vx = 0.0
        self._cur_vy = 0.0
        self._cur_vz = 0.0

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_plot)
        self._timer.start()

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ---- 曲线区 ----
        self._plot = pg.PlotWidget()
        self._plot.setTitle("线速度曲线 Vx / Vy / Vz", color="#DCDCDC", size="11pt")
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("bottom", "时间", units="s")
        self._plot.setLabel("left", "速度", units="cm/s")
        self._plot.addLegend(offset=(10, 10))
        # 零基准线
        zero_line = pg.InfiniteLine(pos=0, angle=0,
                                    pen=pg.mkPen(_COL_ZERO, width=1,
                                                 style=Qt.PenStyle.DashLine))
        self._plot.addItem(zero_line)
        self._curve_vx = self._plot.plot(pen=pg.mkPen(_COL_VX, width=2), name="Vx")
        self._curve_vy = self._plot.plot(pen=pg.mkPen(_COL_VY, width=2), name="Vy")
        self._curve_vz = self._plot.plot(pen=pg.mkPen(_COL_VZ, width=2), name="Vz")
        root.addWidget(self._plot, 1)

        # ---- 底部 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        # 实时指标网格（三轴 × 6 项）
        stats_box = QGroupBox("统计指标（记录期间）")
        stats_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        grid = QGridLayout(stats_box)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(3)

        self._stat_labels: dict[str, QLabel] = {}
        # 列头
        for ci, (txt, col) in enumerate([("Vx", _COL_VX), ("Vy", _COL_VY), ("Vz", _COL_VZ)], 1):
            hdr = QLabel(txt)
            hdr.setStyleSheet(f"color:{col}; font-size:13px; font-weight:bold;")
            hdr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            grid.addWidget(hdr, 0, ci)

        rows = [
            ("cur",  "当前 (cm/s)"),
            ("max",  "最大 (cm/s)"),
            ("min",  "最小 (cm/s)"),
            ("mean", "均值 (cm/s)"),
            ("std",  "标准差"),
            ("pp",   "峰峰值"),
        ]
        for ri, (key, label) in enumerate(rows, 1):
            lbl = QLabel(label + "：")
            lbl.setStyleSheet("color:#B0B0B0; font-size:12px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(lbl, ri, 0)
            for ci, axis in enumerate(["vx", "vy", "vz"], 1):
                col = [_COL_VX, _COL_VY, _COL_VZ][ci - 1]
                v = QLabel("--")
                v.setStyleSheet(f"color:{col}; font-size:12px; font-weight:bold;")
                v.setAlignment(Qt.AlignmentFlag.AlignCenter)
                grid.addWidget(v, ri, ci)
                self._stat_labels[f"{key}_{axis}"] = v

        bottom.addWidget(stats_box, 1)

        # 按钮列
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)

        self._btn_arm = QPushButton("装填/开始记录")
        self._btn_arm.clicked.connect(self._on_arm)

        self._btn_stop = QPushButton("停止记录")
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)

        self._btn_reset = QPushButton("重置")
        self._btn_reset.clicked.connect(self._on_reset)

        self._btn_export = QPushButton("导出 CSV")
        self._btn_export.clicked.connect(self._on_export)
        self._btn_export.setEnabled(False)

        self._lbl_phase = QLabel(PH_IDLE)
        self._lbl_phase.setStyleSheet("color:#FFCA28; font-size:14px; font-weight:bold;")
        self._lbl_phase.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._lbl_count = QLabel("已记录：0 帧")
        self._lbl_count.setStyleSheet("color:#B0B0B0; font-size:12px;")
        self._lbl_count.setAlignment(Qt.AlignmentFlag.AlignCenter)

        for w in (self._btn_arm, self._btn_stop, self._btn_reset, self._btn_export,
                  self._lbl_phase, self._lbl_count):
            w.setMinimumWidth(130)
            btn_col.addWidget(w)
        btn_col.addStretch(1)
        bottom.addLayout(btn_col)

        root.addLayout(bottom)

    # ------------------------------------------------------------------ #
    # 数据入口
    # ------------------------------------------------------------------ #
    @Slot(object)
    def on_velocity(self, s: object) -> None:
        """接收 VelocitySample，更新实时指标，若在记录则存入缓冲。"""
        vx = float(getattr(s, "vx_cmps", 0))
        vy = float(getattr(s, "vy_cmps", 0))
        vz = float(getattr(s, "vz_cmps", 0))
        self._cur_vx, self._cur_vy, self._cur_vz = vx, vy, vz

        # 实时刷"当前"列
        for ax, val in (("vx", vx), ("vy", vy), ("vz", vz)):
            self._stat_labels[f"cur_{ax}"].setText(f"{val:+.1f}")

        if self._phase != PH_REC:
            return

        t_rel = getattr(s, "ts", time.monotonic()) - self._t_arm
        self._ts.append(t_rel)
        self._vxs.append(vx)
        self._vys.append(vy)
        self._vzs.append(vz)

        n = len(self._ts)
        self._lbl_count.setText(f"已记录：{n} 帧")

        # 每 10 帧刷新一次统计（避免每帧 np.std 开销）
        if n % 10 == 0:
            self._update_stats()

    # ------------------------------------------------------------------ #
    # 统计
    # ------------------------------------------------------------------ #
    def _update_stats(self) -> None:
        if not self._ts:
            return
        for ax, buf in (("vx", self._vxs), ("vy", self._vys), ("vz", self._vzs)):
            arr = np.fromiter(buf, dtype=float)
            self._stat_labels[f"max_{ax}"].setText(f"{arr.max():+.1f}")
            self._stat_labels[f"min_{ax}"].setText(f"{arr.min():+.1f}")
            self._stat_labels[f"mean_{ax}"].setText(f"{arr.mean():+.2f}")
            self._stat_labels[f"std_{ax}"].setText(f"{arr.std():.2f}")
            self._stat_labels[f"pp_{ax}"].setText(f"{arr.max() - arr.min():.2f}")

    # ------------------------------------------------------------------ #
    # 绘图刷新
    # ------------------------------------------------------------------ #
    def _refresh_plot(self) -> None:
        if not self._ts:
            return
        t_arr = np.fromiter(self._ts, float)
        self._curve_vx.setData(t_arr, np.fromiter(self._vxs, float))
        self._curve_vy.setData(t_arr, np.fromiter(self._vys, float))
        self._curve_vz.setData(t_arr, np.fromiter(self._vzs, float))

    # ------------------------------------------------------------------ #
    # 按钮
    # ------------------------------------------------------------------ #
    def _on_arm(self) -> None:
        self._ts.clear(); self._vxs.clear(); self._vys.clear(); self._vzs.clear()
        self._curve_vx.setData([], []); self._curve_vy.setData([], []); self._curve_vz.setData([], [])
        for k in self._stat_labels:
            if not k.startswith("cur_"):
                self._stat_labels[k].setText("--")
        self._t_arm = time.monotonic()
        self._phase = PH_REC
        self._lbl_phase.setText(PH_REC)
        self._lbl_count.setText("已记录：0 帧")
        self._btn_arm.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._log.info("速度测试：开始记录")

    def _on_stop(self) -> None:
        self._phase = PH_DONE
        self._lbl_phase.setText(PH_DONE)
        self._btn_arm.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(bool(self._ts))
        self._update_stats()   # 最终刷新一次
        self._log.info("速度测试：停止记录，共 %d 帧", len(self._ts))

    def _on_reset(self) -> None:
        self._phase = PH_IDLE
        self._ts.clear(); self._vxs.clear(); self._vys.clear(); self._vzs.clear()
        self._curve_vx.setData([], []); self._curve_vy.setData([], []); self._curve_vz.setData([], [])
        self._lbl_phase.setText(PH_IDLE)
        self._lbl_count.setText("已记录：0 帧")
        self._btn_arm.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(False)
        for k in self._stat_labels:
            if not k.startswith("cur_"):
                self._stat_labels[k].setText("--")
        self._log.info("速度测试：已重置")

    def _on_export(self) -> None:
        if not self._ts:
            return
        default = os.path.join(os.path.expanduser("~"), "velocity_test.csv")
        path, _ = QFileDialog.getSaveFileName(self, "导出速度曲线", default, "CSV (*.csv)")
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_rel_s", "vx_cmps", "vy_cmps", "vz_cmps"])
                for t, vx, vy, vz in zip(self._ts, self._vxs, self._vys, self._vzs):
                    w.writerow([f"{t:.4f}", f"{vx:.1f}", f"{vy:.1f}", f"{vz:.1f}"])
                # 统计摘要
                w.writerow([])
                w.writerow(["# 统计摘要"])
                w.writerow(["轴", "最大", "最小", "均值", "标准差", "峰峰值"])
                for ax, buf in (("Vx", self._vxs), ("Vy", self._vys), ("Vz", self._vzs)):
                    arr = np.fromiter(buf, dtype=float)
                    w.writerow([ax,
                                f"{arr.max():.2f}", f"{arr.min():.2f}",
                                f"{arr.mean():.2f}", f"{arr.std():.2f}",
                                f"{arr.max() - arr.min():.2f}"])
            self._log.info("速度曲线已导出：%s", path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"写文件失败：{exc}")
