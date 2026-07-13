# -*- coding: utf-8 -*-
"""姿态轴（Yaw / Roll / Pitch）跟随/回弹测试面板（Phase 3.1）。

测的现象：手动把设备快速转过约 30° 后物理停住，但融合上报的角度会先冲到
峰值、停手后又慢慢往回漂约 10° 才稳定。本面板量化这个"回弹"。

设计（2026-07-12 用户确认 + 2026-07-13 泛化到三轴 + 判据可调）：
- 数据源：0x04 四元数解算的 roll/pitch/yaw（较平滑）
- 触发：点"装填"后自动检测旋转开始/停手（对应轴的物理角速度阈值）
  · yaw → gyr_z   · roll → gyr_x   · pitch → gyr_y
- 回弹量 = 停手瞬间峰值角度 − 最终稳定角度
- 判据参数（旋转阈值/停手保持/稳定容差/稳定窗口/稳定超时）全部 UI 可调，
  另有「手动结算」按钮可随时强制结束当前测试。

状态机：
  未装填 → 等待旋转 → 旋转中 → 停手稳定中 → 完成
关键点：用物理角速度(0x01)判"停手"（回弹时角速度≈0），
        用角度自身稳定性判"最终稳定"（回弹是滤波器输出漂移，非物理运动）。

同一个类 :class:`YawTestPanel` 通过构造参数 ``axis`` 复用于三个轴。
"""
from __future__ import annotations

import csv
import math
import os
import time
from collections import deque
from typing import Deque, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
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

# ---- 判据参数默认值（现已改为 UI 可调，这里仅作初值）----
DEF_ROTATE_THRESH_DPS = 2.0   # |角速度| 超过 → 旋转中；低于 → 候选停手
DEF_STOP_HOLD_S = 0.5         # 角速度持续低于阈值多久确认停手
DEF_SETTLE_WIN_S = 1.0        # 角度稳定判定滑动窗口
DEF_SETTLE_TOL_DEG = 0.3      # 窗口内角度极差小于此值 → 稳定
DEF_SETTLE_TIMEOUT_S = 8.0    # 停手后最长等待稳定时间（超时强制结算）
_REFRESH_MS = 33              # 绘图刷新 ~30Hz
_MAX_PTS = 6000

# ---- 三轴配置：显示名 / 角度属性 / 角速度属性 / 曲线颜色 ----
_AXIS_CFG: dict[str, dict] = {
    "yaw":   {"name": "Yaw",   "ang": "yaw_deg",   "gyr": "gyr_z", "color": "#4FC3F7"},
    "roll":  {"name": "Roll",  "ang": "roll_deg",  "gyr": "gyr_x", "color": "#FFB74D"},
    "pitch": {"name": "Pitch", "ang": "pitch_deg", "gyr": "gyr_y", "color": "#BA68C8"},
}

# ---- 相位 ----
PH_IDLE = "未装填"
PH_WAIT = "等待旋转"
PH_ROT = "旋转中"
PH_SETTLE = "停手稳定中"
PH_DONE = "完成"

_COL_YAW = "#4FC3F7"
_COL_PEAK = "#EF5350"
_COL_SETTLED = "#66BB6A"
_COL_ROT_REGION = (33, 120, 200, 45)
_COL_SETTLE_REGION = (255, 179, 0, 45)

pg.setConfigOptions(antialias=True, background="#232323", foreground="#B0B0B0")


class YawTestPanel(QWidget):
    """姿态轴跟随/回弹测试面板（Yaw / Roll / Pitch 三轴通用）。

    :param axis: ``"yaw"`` / ``"roll"`` / ``"pitch"``，决定取哪个角度与角速度分量。
    """

    def __init__(self, parent: QWidget | None = None, axis: str = "yaw") -> None:
        super().__init__(parent)
        self._log = get_logger()

        # ---- 轴配置 ----
        cfg = _AXIS_CFG.get(axis, _AXIS_CFG["yaw"])
        self._axis = axis
        self._axis_name = cfg["name"]
        self._ang_attr = cfg["ang"]     # "yaw_deg" / "roll_deg" / "pitch_deg"
        self._gyr_attr = cfg["gyr"]     # "gyr_z"   / "gyr_x"    / "gyr_y"
        self._col_curve = cfg["color"]

        # ---- 可调判据参数（初值取默认，UI 控件实时改写）----
        self._rotate_thresh = DEF_ROTATE_THRESH_DPS
        self._stop_hold = DEF_STOP_HOLD_S
        self._settle_win_s = DEF_SETTLE_WIN_S
        self._settle_tol = DEF_SETTLE_TOL_DEG
        self._settle_timeout = DEF_SETTLE_TIMEOUT_S

        # ---- 状态 ----
        self._phase = PH_IDLE
        self._gyr_dps = 0.0
        self._prev_yaw: Optional[float] = None   # 上一帧角度（用于去环绕）
        self._cont_yaw = 0.0                     # 连续化角度
        self._baseline = 0.0                     # 装填时角度，作为显示 0 点
        self._t_arm = 0.0
        self._rot_start_yaw = 0.0
        self._rot_start_t = 0.0
        self._peak_yaw = 0.0                     # 停手瞬间峰值（连续角度）
        self._stop_cand_t: Optional[float] = None
        self._stop_cand_yaw = 0.0
        self._stop_t = 0.0
        self._settled_yaw = 0.0
        self._settle_time = 0.0
        # 时间序列（相对装填时刻）：用于绘图与导出
        self._ts: Deque[float] = deque(maxlen=_MAX_PTS)
        self._ys: Deque[float] = deque(maxlen=_MAX_PTS)   # 相对 baseline
        self._settle_win: Deque[Tuple[float, float]] = deque()  # (t, cont_yaw)

        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_plot)
        self._timer.start()

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # 顶部：角度-时间曲线
        self._plot = pg.PlotWidget()
        self._plot.setTitle(
            f"{self._axis_name} 跟随曲线（相对起点）", color="#DCDCDC", size="11pt"
        )
        self._plot.showGrid(x=True, y=True, alpha=0.25)
        self._plot.setLabel("bottom", "时间", units="s")
        self._plot.setLabel("left", self._axis_name, units="°")
        self._curve = self._plot.plot(pen=pg.mkPen(self._col_curve, width=2), name=self._axis_name)
        # 区域/标线（延迟加入）
        self._rot_region: Optional[pg.LinearRegionItem] = None
        self._settle_region: Optional[pg.LinearRegionItem] = None
        self._peak_line: Optional[pg.InfiniteLine] = None
        self._settled_line: Optional[pg.InfiniteLine] = None
        root.addWidget(self._plot, 1)

        # 底部：指标 + 按钮
        bottom = QHBoxLayout()
        bottom.setSpacing(12)

        # 指标网格
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(3)
        self._metric_labels: dict[str, QLabel] = {}
        metrics = [
            ("phase", "状态"),
            ("cur", f"当前 {self._axis_name} (°)"),
            ("start", f"起始 {self._axis_name} (°)"),
            ("peak", f"峰值 {self._axis_name} (°)"),
            ("settled", f"稳定 {self._axis_name} (°)"),
            ("rebound", "回弹量 (°)"),
            ("rebound_pct", "回弹百分比 (%)"),
            ("settle_time", "稳定耗时 (s)"),
        ]
        for i, (key, name) in enumerate(metrics):
            r, c = divmod(i, 2)
            name_lbl = QLabel(name + "：")
            name_lbl.setStyleSheet("color:#B0B0B0; font-size:13px;")
            val_lbl = QLabel("--")
            val_lbl.setStyleSheet(f"color:{self._col_curve}; font-size:13px; font-weight:bold;")
            grid.addWidget(name_lbl, r, c * 2, alignment=Qt.AlignmentFlag.AlignRight)
            grid.addWidget(val_lbl, r, c * 2 + 1, alignment=Qt.AlignmentFlag.AlignLeft)
            self._metric_labels[key] = val_lbl
        self._metric_labels["phase"].setText(PH_IDLE)
        bottom.addLayout(grid, 1)

        # 判据参数（UI 可调）
        param_box = QGroupBox("判据参数（可调）")
        param_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        form = QFormLayout(param_box)
        form.setContentsMargins(8, 6, 8, 6)
        form.setVerticalSpacing(3)
        self._sp_rotate = self._make_spin(0.1, 30.0, 0.1, self._rotate_thresh, "°/s")
        self._sp_stop = self._make_spin(0.1, 5.0, 0.1, self._stop_hold, "s")
        self._sp_tol = self._make_spin(0.01, 10.0, 0.05, self._settle_tol, "°")
        self._sp_win = self._make_spin(0.2, 10.0, 0.1, self._settle_win_s, "s")
        self._sp_timeout = self._make_spin(1.0, 60.0, 0.5, self._settle_timeout, "s")
        self._sp_rotate.valueChanged.connect(lambda v: setattr(self, "_rotate_thresh", v))
        self._sp_stop.valueChanged.connect(lambda v: setattr(self, "_stop_hold", v))
        self._sp_tol.valueChanged.connect(lambda v: setattr(self, "_settle_tol", v))
        self._sp_win.valueChanged.connect(lambda v: setattr(self, "_settle_win_s", v))
        self._sp_timeout.valueChanged.connect(lambda v: setattr(self, "_settle_timeout", v))
        form.addRow("旋转判定阈值", self._sp_rotate)
        form.addRow("停手保持时长", self._sp_stop)
        form.addRow("稳定容差", self._sp_tol)
        form.addRow("稳定窗口", self._sp_win)
        form.addRow("稳定超时", self._sp_timeout)
        bottom.addWidget(param_box)

        # 按钮列
        btn_col = QVBoxLayout()
        btn_col.setSpacing(6)
        self._btn_arm = QPushButton("装填测试")
        self._btn_arm.clicked.connect(self._on_arm)
        self._btn_settle = QPushButton("手动结算")
        self._btn_settle.clicked.connect(self._on_manual_settle)
        self._btn_settle.setEnabled(False)
        self._btn_reset = QPushButton("重置")
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_export = QPushButton("导出曲线 CSV")
        self._btn_export.clicked.connect(self._on_export)
        self._btn_export.setEnabled(False)
        for b in (self._btn_arm, self._btn_settle, self._btn_reset, self._btn_export):
            b.setMinimumWidth(120)
            btn_col.addWidget(b)
        btn_col.addStretch(1)
        bottom.addLayout(btn_col)

        root.addLayout(bottom)

    @staticmethod
    def _make_spin(lo: float, hi: float, step: float, val: float, suffix: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setValue(val)
        sp.setDecimals(2)
        sp.setSuffix(" " + suffix)
        sp.setMaximumWidth(120)
        return sp

    # ---- 数据入口 ----
    @Slot(object)
    def on_imu_raw(self, s: object) -> None:
        """更新最新物理角速度（本轴分量，°/s），供旋转/停手判定。"""
        self._gyr_dps = math.degrees(getattr(s, self._gyr_attr))

    @Slot(object)
    def on_attitude(self, s: object) -> None:
        """每个姿态样本推进状态机。"""
        self._update_continuous_yaw(getattr(s, self._ang_attr))
        self._metric_labels["cur"].setText(f"{self._cont_yaw - self._baseline:+.2f}")
        if self._phase in (PH_IDLE, PH_DONE):
            return
        t = s.ts
        self._ts.append(t - self._t_arm)
        self._ys.append(self._cont_yaw - self._baseline)
        self._step(t)

    def _update_continuous_yaw(self, yaw_deg: float) -> None:
        if self._prev_yaw is None:
            self._prev_yaw = yaw_deg
            self._cont_yaw = yaw_deg
            return
        d = yaw_deg - self._prev_yaw
        if d > 180.0:
            d -= 360.0
        elif d < -180.0:
            d += 360.0
        self._cont_yaw += d
        self._prev_yaw = yaw_deg

    # ---- 状态机 ----
    def _step(self, t: float) -> None:
        g = abs(self._gyr_dps)
        if self._phase == PH_WAIT:
            if g > self._rotate_thresh:
                self._phase = PH_ROT
                self._rot_start_yaw = self._cont_yaw
                self._rot_start_t = t
                self._metric_labels["phase"].setText(PH_ROT)
                self._metric_labels["start"].setText(f"{self._cont_yaw - self._baseline:+.2f}")
                self._log.info("%s测试：检测到旋转开始", self._axis_name)

        elif self._phase == PH_ROT:
            if g <= self._rotate_thresh:
                if self._stop_cand_t is None:
                    self._stop_cand_t = t
                    self._stop_cand_yaw = self._cont_yaw   # 候选停手瞬间的角度
                elif t - self._stop_cand_t >= self._stop_hold:
                    # 确认停手
                    self._phase = PH_SETTLE
                    self._peak_yaw = self._stop_cand_yaw
                    self._stop_t = self._stop_cand_t
                    self._settle_win.clear()
                    self._metric_labels["phase"].setText(PH_SETTLE)
                    self._metric_labels["peak"].setText(f"{self._peak_yaw - self._baseline:+.2f}")
                    self._add_regions_after_stop()
                    self._log.info("%s测试：确认停手，峰值=%.2f°", self._axis_name, self._peak_yaw - self._baseline)
            else:
                self._stop_cand_t = None  # 只是瞬时抖动，继续旋转

        elif self._phase == PH_SETTLE:
            self._settle_win.append((t, self._cont_yaw))
            cutoff = t - self._settle_win_s
            while self._settle_win and self._settle_win[0][0] < cutoff:
                self._settle_win.popleft()
            vals = [y for _, y in self._settle_win]
            settled = False
            if (t - self._stop_t) >= self._settle_win_s and vals and (max(vals) - min(vals)) < self._settle_tol:
                settled = True
            elif (t - self._stop_t) >= self._settle_timeout:
                settled = True  # 超时强制结算
                self._log.warning("%s测试：稳定判定超时，强制结算", self._axis_name)
            if settled:
                self._settled_yaw = float(np.mean(vals)) if vals else self._cont_yaw
                self._settle_time = t - self._stop_t
                self._finish()

    def _on_manual_settle(self) -> None:
        """手动结算：在旋转中/停手稳定中随时强制结束当前测试。"""
        if self._phase not in (PH_ROT, PH_SETTLE):
            return
        t = time.monotonic()
        if self._phase == PH_ROT:
            # 尚未确认停手：把当前当作峰值 + 停手时刻，立即结算
            self._peak_yaw = self._cont_yaw
            self._stop_t = t
            self._metric_labels["peak"].setText(f"{self._peak_yaw - self._baseline:+.2f}")
            self._add_regions_after_stop()
        vals = [y for _, y in self._settle_win] or [self._cont_yaw]
        self._settled_yaw = float(np.mean(vals))
        self._settle_time = max(0.0, t - self._stop_t)
        self._log.info("%s测试：手动结算", self._axis_name)
        self._finish()

    def _finish(self) -> None:
        self._phase = PH_DONE
        self._btn_settle.setEnabled(False)
        rebound = self._peak_yaw - self._settled_yaw
        rot_span = self._peak_yaw - self._rot_start_yaw
        pct = (rebound / rot_span * 100.0) if abs(rot_span) > 1e-6 else 0.0
        self._metric_labels["phase"].setText(PH_DONE)
        self._metric_labels["settled"].setText(f"{self._settled_yaw - self._baseline:+.2f}")
        self._metric_labels["rebound"].setText(f"{rebound:+.2f}")
        self._metric_labels["rebound_pct"].setText(f"{pct:+.1f}")
        self._metric_labels["settle_time"].setText(f"{self._settle_time:.2f}")
        self._btn_export.setEnabled(True)
        self._draw_final_markers()
        self._log.info(
            "%s测试完成：峰值=%.2f° 稳定=%.2f° 回弹=%.2f°(%.1f%%) 耗时=%.2fs",
            self._axis_name,
            self._peak_yaw - self._baseline,
            self._settled_yaw - self._baseline,
            rebound, pct, self._settle_time,
        )

    # ---- 绘图辅助 ----
    def _add_regions_after_stop(self) -> None:
        # 旋转区间：rot_start_t → stop_t
        x0 = self._rot_start_t - self._t_arm
        x1 = self._stop_t - self._t_arm
        self._rot_region = pg.LinearRegionItem(
            values=(x0, x1), brush=_COL_ROT_REGION, movable=False
        )
        self._rot_region.setZValue(-10)
        self._plot.addItem(self._rot_region)

    def _draw_final_markers(self) -> None:
        x_stop = self._stop_t - self._t_arm
        x_end = self._ts[-1] if self._ts else x_stop
        # 停手→稳定 区间
        self._settle_region = pg.LinearRegionItem(
            values=(x_stop, x_end), brush=_COL_SETTLE_REGION, movable=False
        )
        self._settle_region.setZValue(-10)
        self._plot.addItem(self._settle_region)
        # 峰值/稳定 水平线
        self._peak_line = pg.InfiniteLine(
            pos=self._peak_yaw - self._baseline, angle=0,
            pen=pg.mkPen(_COL_PEAK, width=1, style=Qt.PenStyle.DashLine),
            label="峰值", labelOpts={"color": _COL_PEAK, "position": 0.05},
        )
        self._settled_line = pg.InfiniteLine(
            pos=self._settled_yaw - self._baseline, angle=0,
            pen=pg.mkPen(_COL_SETTLED, width=1, style=Qt.PenStyle.DashLine),
            label="稳定", labelOpts={"color": _COL_SETTLED, "position": 0.05},
        )
        self._plot.addItem(self._peak_line)
        self._plot.addItem(self._settled_line)

    def _refresh_plot(self) -> None:
        if not self._ts:
            return
        self._curve.setData(np.fromiter(self._ts, float), np.fromiter(self._ys, float))

    # ---- 按钮 ----
    def _on_arm(self) -> None:
        self._clear_state(keep_curve=False)
        self._phase = PH_WAIT
        self._t_arm = time.monotonic()
        self._baseline = self._cont_yaw
        self._metric_labels["phase"].setText(PH_WAIT)
        self._btn_export.setEnabled(False)
        self._btn_settle.setEnabled(True)
        self._log.info("%s测试：已装填，等待旋转", self._axis_name)

    def _on_reset(self) -> None:
        self._clear_state(keep_curve=False)
        self._metric_labels["phase"].setText(PH_IDLE)
        self._btn_settle.setEnabled(False)
        self._log.info("%s测试：已重置", self._axis_name)

    def clear(self) -> None:
        self._on_reset()

    def _clear_state(self, keep_curve: bool) -> None:
        self._phase = PH_IDLE
        self._stop_cand_t = None
        self._settle_win.clear()
        self._peak_yaw = self._settled_yaw = self._settle_time = 0.0
        if not keep_curve:
            self._ts.clear()
            self._ys.clear()
            self._curve.setData([], [])
            for item in (self._rot_region, self._settle_region, self._peak_line, self._settled_line):
                if item is not None:
                    self._plot.removeItem(item)
            self._rot_region = self._settle_region = self._peak_line = self._settled_line = None
        for k in ("start", "peak", "settled", "rebound", "rebound_pct", "settle_time"):
            self._metric_labels[k].setText("--")

    def _on_export(self) -> None:
        if not self._ts:
            return
        default = os.path.join(os.path.expanduser("~"), f"{self._axis}_test.csv")
        path, _ = QFileDialog.getSaveFileName(
            self, f"导出 {self._axis_name} 曲线", default, "CSV (*.csv)"
        )
        if not path:
            return
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["t_rel_s", f"{self._axis}_rel_deg"])
                for t, y in zip(self._ts, self._ys):
                    w.writerow([f"{t:.4f}", f"{y:.4f}"])
                w.writerow([])
                w.writerow([f"峰值{self._axis_name}", f"{self._peak_yaw - self._baseline:.4f}"])
                w.writerow([f"稳定{self._axis_name}", f"{self._settled_yaw - self._baseline:.4f}"])
                w.writerow(["回弹量", f"{self._peak_yaw - self._settled_yaw:.4f}"])
                w.writerow(["稳定耗时s", f"{self._settle_time:.4f}"])
            self._log.info("%s曲线已导出：%s", self._axis_name, path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"写文件失败：{exc}")
