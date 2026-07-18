# -*- coding: utf-8 -*-
"""位置测试面板（Position Test）。

用户需求（2026-07-17 已拍板 + 迭代）：
- 底层策略模式 + 注册表（gui/imu_test/position）：多算法**并行对比**
- X / Y / Z 三轴各一张图，但**一次只显示一个轴**（顶部"显示轴"下拉切换），减少绘图开销
- 每图下方对齐显示该轴各算法实时位移；曲线可用复选框逐个显隐（默认全开）
- 检测的是**位移(相对量)**，不是绝对位置
- 统一「装填」按钮：点击后开始计算相对位移（可设保持时长自动结算）
- 「清除/重置」、界面可调判据参数（各算法自带 + 全局保持时长/稳定窗口）
- CSV 导出：t_rel_s / dx dy dz / 原始观测量 / 当前算法名 / 相位标记
- **惰性门控**：切到别的 Tab（面板隐藏）即停止一切计算与刷新，不占后台开销

轴向：机体系 前X-左Y-上Z，逐轴直连（vx→X, vy→Y, vz→Z），面板不做坐标变换。

数据源（ImuDataHub 信号）：
- velocity(0x07, cm/s)  → InputKind.VELOCITY 类算法
- imu_raw(0x01, m/s²)   → InputKind.ACCEL 类算法
- position(0x32, cm)    → InputKind.POSITION 类算法
"""
from __future__ import annotations

import csv
import os
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.logger import get_logger
from gui.imu_test.position import InputKind, create_all

_REFRESH_MS = 33        # 绘图刷新 ~30Hz
_MAX_PTS    = 12000     # 每算法每轴最多保留点数

_AXES = ("x", "y", "z")
_AXIS_TITLE = {"x": "X 轴位移（前+）", "y": "Y 轴位移（左+）", "z": "Z 轴位移（上+）"}
_COL_ZERO = "#888888"

# 相位
PH_IDLE = "未装填"
PH_REC  = "记录中"
PH_DONE = "完成"

pg.setConfigOptions(antialias=True, background="#232323", foreground="#B0B0B0")


class PositionTestPanel(QWidget):
    """位置测试面板：三轴独立图 + 多算法并行对比 + 位移检测。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._phase = PH_IDLE
        self._t_arm = 0.0

        # 全部已注册估计器（并行对比）
        self._estimators = create_all()

        # 每个算法一份缓冲：t + 三轴位移；键=algo.key
        # buf[key] = (deque_t, {axis: deque_disp})
        self._buf: Dict[str, Tuple[Deque[float], Dict[str, Deque[float]]]] = {}
        # 原始观测量缓冲（导出用）：raw[key] = (deque_t, {axis: deque_raw})
        self._raw: Dict[str, Tuple[Deque[float], Dict[str, Deque[float]]]] = {}
        for est in self._estimators:
            self._buf[est.key] = (
                deque(maxlen=_MAX_PTS),
                {a: deque(maxlen=_MAX_PTS) for a in _AXES},
            )
            self._raw[est.key] = (
                deque(maxlen=_MAX_PTS),
                {a: deque(maxlen=_MAX_PTS) for a in _AXES},
            )

        # 每算法每轴一条曲线：curves[key][axis]
        self._curves: Dict[str, Dict[str, pg.PlotDataItem]] = {}
        # 每轴下方对齐的实时位移数值标签（每算法一行）：disp_labels[axis][key]
        self._disp_labels: Dict[str, Dict[str, QLabel]] = {a: {} for a in _AXES}
        # 每轴每算法的标签容器（用于随曲线显隐）：disp_cells[axis][key]
        self._disp_cells: Dict[str, Dict[str, QWidget]] = {a: {} for a in _AXES}
        # 每算法最新三轴位移（实时刷标签用）
        self._last_disp: Dict[str, List[float]] = {
            est.key: [0.0, 0.0, 0.0] for est in self._estimators
        }

        # 当前显示的轴（一次只显示一个）
        self._cur_axis = "x"
        # 面板是否可见（惰性门控：切走 Tab 就不计算、不刷新）
        self._active = False
        # 每算法显隐复选框：algo_vis[key]
        self._algo_vis: Dict[str, QCheckBox] = {}

        # 全局判据参数
        self._hold_dur = 0.0      # 保持时长(s)：>0 时装填后到时自动结算；=0 手动停止（默认手动，避免图冻结）
        self._settle_win = 1.0    # 稳定窗口(s)：末尾窗口内极差<容差视为稳定
        self._settle_tol = 1.0    # 稳定容差(cm)

        self._build_ui()

        # 定时器按需启动：仅当面板可见时（showEvent）才跑，切走即停（hideEvent）
        self._timer = QTimer(self)
        self._timer.setInterval(_REFRESH_MS)
        self._timer.timeout.connect(self._refresh_plots)

    # ------------------------------------------------------------------ #
    # UI
    # ------------------------------------------------------------------ #
    def _build_ui(self) -> None:
        # 外层滚动（界面可滚动）
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll)

        content = QWidget()
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        # ---- 顶部：控制条 + 参数 ----
        root.addLayout(self._build_control_row())
        root.addWidget(self._build_param_box())
        # ---- 视图控制：轴选择 + 各算法曲线显隐 ----
        root.addWidget(self._build_view_row())

        # ---- 单轴显示：QStackedWidget，一次只显示一个轴（X/Y/Z 切换）----
        self._axis_stack = QStackedWidget()
        self._axis_index: Dict[str, int] = {}
        for i, axis in enumerate(_AXES):
            self._axis_stack.addWidget(self._build_axis_block(axis))
            self._axis_index[axis] = i
        root.addWidget(self._axis_stack)

        root.addStretch(1)

    def _build_control_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(8)

        self._btn_arm = QPushButton("装填（开始检测位移）")
        self._btn_arm.clicked.connect(self._on_arm)
        self._btn_stop = QPushButton("停止")
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_stop.setEnabled(False)
        self._btn_reset = QPushButton("清除/重置")
        self._btn_reset.clicked.connect(self._on_reset)
        self._btn_export = QPushButton("导出 CSV")
        self._btn_export.clicked.connect(self._on_export)
        self._btn_export.setEnabled(False)

        self._lbl_phase = QLabel(PH_IDLE)
        self._lbl_phase.setStyleSheet("color:#FFCA28; font-size:14px; font-weight:bold;")
        self._lbl_count = QLabel("已记录：0 帧")
        self._lbl_count.setStyleSheet("color:#B0B0B0; font-size:12px;")

        for b in (self._btn_arm, self._btn_stop, self._btn_reset, self._btn_export):
            b.setMinimumWidth(140)
            row.addWidget(b)
        row.addSpacing(12)
        row.addWidget(self._lbl_phase)
        row.addWidget(self._lbl_count)
        row.addStretch(1)
        return row

    def _build_view_row(self) -> QGroupBox:
        """视图控制：选择显示哪个轴 + 各算法曲线显隐开关。"""
        box = QGroupBox("显示控制")
        box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        row = QHBoxLayout(box)
        row.setSpacing(10)

        # 轴选择器：一次只看一个轴，减少绘图开销
        row.addWidget(QLabel("显示轴："))
        self._axis_combo = QComboBox()
        for axis in _AXES:
            self._axis_combo.addItem(_AXIS_TITLE[axis], axis)
        self._axis_combo.currentIndexChanged.connect(self._on_axis_changed)
        self._axis_combo.setMinimumWidth(150)
        row.addWidget(self._axis_combo)

        row.addSpacing(20)
        row.addWidget(QLabel("曲线："))
        # 各算法一个复选框，默认全开；取消勾选即隐藏该算法曲线，方便单看某一种
        for est in self._estimators:
            cb = QCheckBox(est.label)
            cb.setChecked(True)
            cb.setStyleSheet(f"QCheckBox{{color:{est.color}; font-size:12px;}}")
            cb.toggled.connect(self._apply_visibility)
            self._algo_vis[est.key] = cb
            row.addWidget(cb)
        row.addStretch(1)
        return box

    def _build_param_box(self) -> QGroupBox:
        box = QGroupBox("判据参数（可现场调节）")
        box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        grid = QGridLayout(box)
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)

        # 全局参数
        self._sp_hold = self._mk_spin(0.0, 120.0, 0.5, self._hold_dur, 1, " s")
        self._sp_hold.valueChanged.connect(lambda v: setattr(self, "_hold_dur", float(v)))
        self._sp_win = self._mk_spin(0.1, 10.0, 0.1, self._settle_win, 1, " s")
        self._sp_win.valueChanged.connect(lambda v: setattr(self, "_settle_win", float(v)))
        self._sp_tol = self._mk_spin(0.0, 100.0, 0.5, self._settle_tol, 1, " cm")
        self._sp_tol.valueChanged.connect(lambda v: setattr(self, "_settle_tol", float(v)))

        c = 0
        for label, sp, tip in (
            ("保持时长(0=手动)", self._sp_hold, "装填后经过该时长自动结算；0 表示只能手动停止"),
            ("稳定窗口", self._sp_win, "末尾该时长窗口内位移极差小于容差判为稳定"),
            ("稳定容差", self._sp_tol, "稳定判据的位移极差阈值"),
        ):
            lbl = QLabel(label + "：")
            lbl.setStyleSheet("color:#B0B0B0; font-size:12px;")
            lbl.setToolTip(tip)
            grid.addWidget(lbl, 0, c); grid.addWidget(sp, 0, c + 1)
            c += 2

        # 各算法自带参数（每算法一行）
        r = 1
        self._algo_spins: Dict[Tuple[str, str], QDoubleSpinBox] = {}
        for est in self._estimators:
            specs = est.params_spec()
            if not specs:
                continue
            name = QLabel(f"【{est.label}】")
            name.setStyleSheet(f"color:{est.color}; font-size:12px; font-weight:bold;")
            grid.addWidget(name, r, 0, 1, 2)
            cc = 2
            for spec in specs:
                lbl = QLabel(spec.label + "：")
                lbl.setStyleSheet("color:#B0B0B0; font-size:12px;")
                grid.addWidget(lbl, r, cc)
                sp = self._mk_spin(spec.minimum, spec.maximum, spec.step,
                                   spec.default, spec.decimals,
                                   (" " + spec.unit) if spec.unit else "")
                # 绑定：变化即更新该算法参数
                sp.valueChanged.connect(
                    lambda v, e=est, k=spec.key: e.set_param(k, float(v))
                )
                self._algo_spins[(est.key, spec.key)] = sp
                grid.addWidget(sp, r, cc + 1)
                cc += 2
            r += 1
        return box

    @staticmethod
    def _mk_spin(mn: float, mx: float, step: float, val: float,
                 decimals: int, suffix: str) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(mn, mx)
        sp.setSingleStep(step)
        sp.setDecimals(decimals)
        sp.setValue(val)
        if suffix:
            sp.setSuffix(suffix)
        sp.setMinimumWidth(90)
        sp.setStyleSheet("QDoubleSpinBox{color:#DCDCDC;}")
        return sp

    def _build_axis_block(self, axis: str) -> QGroupBox:
        """单轴块：曲线图 + 下方对齐的多算法实时位移标签。"""
        box = QGroupBox(_AXIS_TITLE[axis])
        box.setStyleSheet("QGroupBox{color:#DCDCDC; font-size:12px; font-weight:bold;}")
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        plot = pg.PlotWidget()
        plot.setMinimumHeight(200)
        plot.showGrid(x=True, y=True, alpha=0.25)
        plot.setLabel("bottom", "时间", units="s")
        plot.setLabel("left", "位移", units="cm")
        # 关闭自动 SI 前缀，避免小位移时纵轴出现 "mcm"（毫厘米）这种误导单位
        plot.getAxis("left").enableAutoSIPrefix(False)
        plot.getAxis("bottom").enableAutoSIPrefix(False)
        plot.addLegend(offset=(10, 10))
        zero = pg.InfiniteLine(pos=0, angle=0,
                               pen=pg.mkPen(_COL_ZERO, width=1,
                                            style=Qt.PenStyle.DashLine))
        plot.addItem(zero)
        for est in self._estimators:
            curve = plot.plot(pen=pg.mkPen(est.color, width=2), name=est.label)
            self._curves.setdefault(est.key, {})[axis] = curve
        v.addWidget(plot)

        # 下方对齐：每算法一行"算法名：位移值 cm"（放进独立 cell，便于随曲线显隐）
        disp_row = QGridLayout()
        disp_row.setHorizontalSpacing(14)
        disp_row.setVerticalSpacing(2)
        for i, est in enumerate(self._estimators):
            cell = QWidget()
            hb = QHBoxLayout(cell)
            hb.setContentsMargins(0, 0, 0, 0)
            hb.setSpacing(4)
            tag = QLabel(f"{est.label}：")
            tag.setStyleSheet(f"color:{est.color}; font-size:12px;")
            val = QLabel("0.00 cm")
            val.setStyleSheet(f"color:{est.color}; font-size:13px; font-weight:bold;")
            hb.addWidget(tag)
            hb.addWidget(val)
            hb.addStretch(1)
            disp_row.addWidget(cell, i // 2, i % 2)
            self._disp_labels[axis][est.key] = val
            self._disp_cells[axis][est.key] = cell
        v.addLayout(disp_row)
        return box

    # ------------------------------------------------------------------ #
    # 视图控制（轴切换 / 曲线显隐 / 惰性刷新）
    # ------------------------------------------------------------------ #
    def _on_axis_changed(self, idx: int) -> None:
        """切换当前显示轴：切 Stacked 页 + 立即刷新一次该轴曲线。"""
        axis = self._axis_combo.itemData(idx)
        if axis not in self._axis_index:
            return
        self._cur_axis = axis
        self._axis_stack.setCurrentIndex(self._axis_index[axis])
        self._refresh_plots()   # 立即把当前轴画出来，不等下一拍

    def _apply_visibility(self) -> None:
        """按复选框状态显隐各算法的曲线与位移标签。"""
        for est in self._estimators:
            vis = self._algo_vis[est.key].isChecked()
            for axis in _AXES:
                self._curves[est.key][axis].setVisible(vis)
                cell = self._disp_cells[axis].get(est.key)
                if cell is not None:
                    cell.setVisible(vis)
        self._refresh_plots()

    # ---- 惰性门控：只有面板可见时才计算/刷新，切走即停，省 CPU ----
    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._active = True
        if not self._timer.isActive():
            self._timer.start()

    def hideEvent(self, event) -> None:  # noqa: N802
        super().hideEvent(event)
        self._active = False
        self._timer.stop()

    # ------------------------------------------------------------------ #
    # 数据入口（按 input_kind 路由）
    # ------------------------------------------------------------------ #
    @Slot(object)
    def on_velocity(self, s: object) -> None:
        self._feed(InputKind.VELOCITY,
                   getattr(s, "ts", None),
                   float(getattr(s, "vx_cmps", 0)),
                   float(getattr(s, "vy_cmps", 0)),
                   float(getattr(s, "vz_cmps", 0)))

    @Slot(object)
    def on_imu_raw(self, s: object) -> None:
        self._feed(InputKind.ACCEL,
                   getattr(s, "ts", None),
                   float(getattr(s, "acc_x", 0)),
                   float(getattr(s, "acc_y", 0)),
                   float(getattr(s, "acc_z", 0)))

    @Slot(object)
    def on_position(self, s: object) -> None:
        # 无效轴（0x80000000）保留上次，简单起见此处直接透传 cm 值
        self._feed(InputKind.POSITION,
                   getattr(s, "ts", None),
                   float(getattr(s, "x_cm", 0)),
                   float(getattr(s, "y_cm", 0)),
                   float(getattr(s, "z_cm", 0)))

    @Slot(object)
    def on_gen_velocity(self, s: object) -> None:
        """0x33 光流原始速度（有效性前端已判断，此处直接透传）。"""
        self._feed(InputKind.GEN_VELOCITY,
                   getattr(s, "ts", None),
                   float(getattr(s, "vx_cmps", 0)),
                   float(getattr(s, "vy_cmps", 0)),
                   float(getattr(s, "vz_cmps", 0)))

    def _feed(self, kind: InputKind, ts: Optional[float],
              rx: float, ry: float, rz: float) -> None:
        """把一帧观测量喂给所有匹配 input_kind 的估计器。"""
        # 惰性门控：面板不可见（切到别的 Tab）时直接返回，不做任何计算
        if not self._active:
            return
        t = ts if ts is not None else time.monotonic()
        cur = self._cur_axis
        for est in self._estimators:
            if est.input_kind != kind:
                continue
            dx, dy, dz = est.update(t, rx, ry, rz)
            self._last_disp[est.key] = [dx, dy, dz]
            # 只刷新"当前显示轴"的位移标签（其它轴不可见，省开销）
            d_cur = {"x": dx, "y": dy, "z": dz}[cur]
            lbl = self._disp_labels[cur].get(est.key)
            if lbl is not None:
                lbl.setText(f"{d_cur:+.2f} cm")

            if self._phase != PH_REC:
                continue
            t_rel = t - self._t_arm
            tb, axb = self._buf[est.key]
            tb.append(t_rel)
            axb["x"].append(dx); axb["y"].append(dy); axb["z"].append(dz)
            rt, rab = self._raw[est.key]
            rt.append(t_rel)
            rab["x"].append(rx); rab["y"].append(ry); rab["z"].append(rz)

        # 记录中：更新帧数 + 稳定检测 + 时间阈值自动结算
        if self._phase == PH_REC:
            n = max((len(self._buf[e.key][0]) for e in self._estimators), default=0)
            stable = self._is_stable()
            tag = "已稳定" if stable else "运动中"
            self._lbl_count.setText(f"已记录：{n} 帧 · {tag}")
            # 保持时长>0：到时自动结算（时间阈值内的相对位移）
            if self._hold_dur > 0 and (t - self._t_arm) >= self._hold_dur:
                self._on_stop()

    def _is_stable(self) -> bool:
        """稳定检测：所有有数据的算法，在末尾 settle_win 秒窗口内，
        三轴位移极差均 < settle_tol，则判为已稳定。供实时状态显示用。"""
        win = self._settle_win
        tol = self._settle_tol
        any_data = False
        for est in self._estimators:
            tb, axb = self._buf[est.key]
            if len(tb) < 2:
                continue
            any_data = True
            t_end = tb[-1]
            # 取末尾窗口内的样本索引
            idx0 = 0
            for i in range(len(tb) - 1, -1, -1):
                if t_end - tb[i] > win:
                    idx0 = i + 1
                    break
            if len(tb) - idx0 < 2:
                return False   # 窗口内样本太少，尚不能判稳
            for a in _AXES:
                seg = list(axb[a])[idx0:]
                if seg and (max(seg) - min(seg)) >= tol:
                    return False
        return any_data

    # ------------------------------------------------------------------ #
    # 绘图刷新
    # ------------------------------------------------------------------ #
    def _refresh_plots(self) -> None:
        # 只绘制"当前显示轴"且"可见算法"的曲线，最大限度降低绘图开销
        axis = self._cur_axis
        for est in self._estimators:
            if not self._algo_vis[est.key].isChecked():
                continue
            tb, axb = self._buf[est.key]
            if not tb:
                continue
            t_arr = np.fromiter(tb, float)
            self._curves[est.key][axis].setData(
                t_arr, np.fromiter(axb[axis], float)
            )

    # ------------------------------------------------------------------ #
    # 按钮
    # ------------------------------------------------------------------ #
    def _clear_buffers(self) -> None:
        for est in self._estimators:
            self._buf[est.key][0].clear()
            self._raw[est.key][0].clear()
            for a in _AXES:
                self._buf[est.key][1][a].clear()
                self._raw[est.key][1][a].clear()
                self._curves[est.key][a].setData([], [])

    def _on_arm(self) -> None:
        self._clear_buffers()
        for est in self._estimators:
            est.reset()               # 各算法置原点
            self._last_disp[est.key] = [0.0, 0.0, 0.0]
        for axis in _AXES:
            for lbl in self._disp_labels[axis].values():
                lbl.setText("0.00 cm")
        self._t_arm = time.monotonic()
        self._phase = PH_REC
        self._lbl_phase.setText(PH_REC)
        self._lbl_count.setText("已记录：0 帧")
        self._btn_arm.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._log.info("位置测试：装填，开始检测位移（保持时长=%.1fs）", self._hold_dur)

    def _on_stop(self) -> None:
        if self._phase != PH_REC:
            return
        self._phase = PH_DONE
        self._lbl_phase.setText(PH_DONE)
        self._btn_arm.setEnabled(True)
        self._btn_stop.setEnabled(False)
        has_data = any(self._buf[e.key][0] for e in self._estimators)
        self._btn_export.setEnabled(has_data)
        self._log.info("位置测试：停止/结算")

    def _on_reset(self) -> None:
        self._phase = PH_IDLE
        self._clear_buffers()
        for est in self._estimators:
            est.reset()
            self._last_disp[est.key] = [0.0, 0.0, 0.0]
        for axis in _AXES:
            for lbl in self._disp_labels[axis].values():
                lbl.setText("0.00 cm")
        self._lbl_phase.setText(PH_IDLE)
        self._lbl_count.setText("已记录：0 帧")
        self._btn_arm.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._log.info("位置测试：已清除/重置")

    def _on_export(self) -> None:
        if not any(self._buf[e.key][0] for e in self._estimators):
            return
        default = os.path.join(os.path.expanduser("~"), "position_test.csv")
        path, _ = QFileDialog.getSaveFileName(self, "导出位置测试", default, "CSV (*.csv)")
        if not path:
            return
        phase_tag = self._phase
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow([
                    "algo", "t_rel_s",
                    "dx_cm", "dy_cm", "dz_cm",
                    "raw_x", "raw_y", "raw_z",
                    "phase",
                ])
                for est in self._estimators:
                    tb, axb = self._buf[est.key]
                    rt, rab = self._raw[est.key]
                    for i in range(len(tb)):
                        w.writerow([
                            est.key, f"{tb[i]:.4f}",
                            f"{axb['x'][i]:.3f}", f"{axb['y'][i]:.3f}", f"{axb['z'][i]:.3f}",
                            f"{rab['x'][i]:.3f}", f"{rab['y'][i]:.3f}", f"{rab['z'][i]:.3f}",
                            phase_tag,
                        ])
            self._log.info("位置测试已导出：%s", path)
        except OSError as exc:
            QMessageBox.warning(self, "导出失败", f"写文件失败：{exc}")
