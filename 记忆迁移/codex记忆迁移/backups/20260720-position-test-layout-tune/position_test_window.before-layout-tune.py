# -*- coding: utf-8 -*-
"""位置测试独立功能页。"""
from __future__ import annotations

import csv
import os
import time
from collections import deque
from math import atan2, degrees, sqrt
from typing import Deque, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.io.protocol import CMD_RPI_POSITION_MIRROR
from gui.services.telemetry_decoder import decode_rpi_position_mirror
from gui.services.telemetry_models import RpiPositionMirrorSample

try:
    import pyqtgraph as pg
    _PG_OK = True
except Exception as _pg_exc:  # pragma: no cover - depends on runtime env
    pg = None
    _PG_OK = False
    _PG_IMPORT_ERR = repr(_pg_exc)


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
        self._recent_rx: Deque[tuple[float, int]] = deque(maxlen=200)
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
            self._recent_rx.clear()
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
        self._recent_rx.append((sample.ts, int(sample.rx_cnt)))
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
            ("F5输入 / F6镜像", self._lbl_rate),
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
            mirror_rate = (len(self._recent_ts) - 1) / span if span > 1e-6 else 0.0
            f5_rate = self._rx_rate()
            self._lbl_rate.setText(f"{f5_rate:.1f} / {mirror_rate:.1f} Hz")
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

    def _rx_rate(self) -> float:
        if len(self._recent_rx) < 2:
            return 0.0
        t0, c0 = self._recent_rx[0]
        t1, c1 = self._recent_rx[-1]
        span = t1 - t0
        delta = c1 - c0
        if span <= 1e-6 or delta < 0:
            return 0.0
        return float(delta) / span


class _StabilityPage(QWidget):
    """稳定性测试页：按用户点击开始/停止采样，默认用于静止定位抖动测试。"""

    _ROWS = (
        ("X 前+", 0),
        ("Y 左+", 1),
        ("Z 上+", 2),
    )
    _TEST_MODES = (
        (
            "静止定位稳定性（推荐）",
            "用途：飞机/雷达静止不动时，测试 SLAM 当前位置 cur 的抖动、漂移和跳变。"
            "这是起飞前最重要的观测质量检查，不是飞行控制稳定性测试。",
            "操作：放稳机体，不要移动；点击开始测试；等待设定时长自动结算。重点看标准差和峰峰值。",
        ),
        (
            "定点悬停观测（仅记录）",
            "用途：后续安全悬停时，只观察 SLAM 坐标是否稳定。当前 GUI 仍然只记录，不参与控制。",
            "操作：确认安全后悬停，点击开始测试；重点看 Z 轴和 XY 是否慢慢漂移。",
        ),
        (
            "慢速平移连续性",
            "用途：沿黑线慢速移动时，检查坐标是否连续、有无跳变或短时间失效。"
            "这不是静止稳定性，均值/峰峰值只作为范围参考。",
            "操作：点击开始测试后匀速慢移；重点看跳变、无效样本和轨迹页曲线是否断裂。",
        ),
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._running = False
        self._done = False
        self._t_start: Optional[float] = None
        self._last_sample: Optional[RpiPositionMirrorSample] = None
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
        self._last_sample = sample
        if self._running:
            if self._t_start is None:
                self._t_start = sample.ts
            self._samples.append(sample)
            if sample.ts - self._t_start >= float(self._duration_s.value()):
                self._stop()
        now = time.monotonic()
        if now - self._last_refresh >= 0.2:
            self._last_refresh = now
            self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        guide_box = QGroupBox("测试说明", self)
        guide_box.setStyleSheet(
            "QGroupBox{background:#2B2B2B; color:#DCDCDC; font-size:12px;"
            " border:1px solid #555; margin-top:8px; padding-top:8px;}"
            "QGroupBox::title{subcontrol-origin: margin; left:8px; padding:0 4px;}"
        )
        guide_lay = QVBoxLayout(guide_box)
        self._mode_help = QLabel("", guide_box)
        self._mode_help.setWordWrap(True)
        self._mode_help.setStyleSheet("color:#F5F5F5; font-size:13px; line-height:125%;")
        guide_lay.addWidget(self._mode_help)
        root.addWidget(guide_box)

        control_box = QGroupBox("测试控制", self)
        control_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        controls = QHBoxLayout(control_box)
        controls.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._mode_combo = QComboBox(control_box)
        for label, _desc, _ops in self._TEST_MODES:
            self._mode_combo.addItem(label)
        self._mode_combo.currentIndexChanged.connect(lambda _idx: self._update_mode_help())
        form.addRow("测试类型", self._mode_combo)

        self._duration_s = QDoubleSpinBox(control_box)
        self._duration_s.setRange(3.0, 120.0)
        self._duration_s.setSingleStep(1.0)
        self._duration_s.setDecimals(1)
        self._duration_s.setSuffix(" s")
        self._duration_s.setValue(10.0)
        self._duration_s.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("测试时长", self._duration_s)

        self._jump_cm = QDoubleSpinBox(control_box)
        self._jump_cm.setRange(0.5, 200.0)
        self._jump_cm.setSingleStep(0.5)
        self._jump_cm.setDecimals(1)
        self._jump_cm.setSuffix(" cm")
        self._jump_cm.setValue(5.0)
        self._jump_cm.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("跳变阈值", self._jump_cm)
        controls.addLayout(form)

        self._btn_start = QPushButton("开始测试", control_box)
        self._btn_stop = QPushButton("停止并结算", control_box)
        self._btn_clear = QPushButton("重置结果", control_box)
        self._btn_start.clicked.connect(self._start)
        self._btn_stop.clicked.connect(self._stop)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_stop.setEnabled(False)
        controls.addWidget(self._btn_start)
        controls.addWidget(self._btn_stop)
        controls.addWidget(self._btn_clear)
        controls.addStretch(1)

        self._summary = QLabel("未开始", control_box)
        self._summary.setWordWrap(True)
        self._summary.setMaximumWidth(430)
        self._summary.setStyleSheet("color:#69F0AE; font-size:17px; font-weight:bold;")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._summary.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        controls.addWidget(self._summary)
        root.addWidget(control_box)

        self._table = QTableWidget(len(self._ROWS), 9, self)
        self._table.setHorizontalHeaderLabels([
            "轴",
            "有效样本",
            "均值 cm",
            "σ cm",
            "摆动 cm",
            "漂移 cm",
            "min/max cm",
            "跳变",
            "判读",
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
            for c in range(1, 9):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._table.setItem(r, c, item)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setColumnWidth(0, 72)
        self._table.setColumnWidth(1, 78)
        self._table.setColumnWidth(2, 78)
        self._table.setColumnWidth(3, 68)
        self._table.setColumnWidth(4, 76)
        self._table.setColumnWidth(5, 76)
        self._table.setColumnWidth(6, 96)
        self._table.setColumnWidth(7, 56)
        root.addWidget(self._table, 1)

        note = QLabel(
            "指标解释：抖动σ=坐标短时间噪声；最大摆动=测试期间最大值-最小值；"
            "漂移=结束坐标-开始坐标；跳变=相邻两帧变化超过阈值。当前阶段只观测，不进入 PID 或控制输出。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#CFCFCF; font-size:13px;")
        root.addWidget(note)
        self._update_mode_help()

    def _clear(self) -> None:
        self._running = False
        self._done = False
        self._t_start = None
        self._samples.clear()
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._refresh()

    def _start(self) -> None:
        self._samples.clear()
        self._running = True
        self._done = False
        self._t_start = None
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._refresh()

    def _stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._done = True
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._refresh()

    def _update_mode_help(self) -> None:
        idx = max(0, min(self._mode_combo.currentIndex(), len(self._TEST_MODES) - 1))
        label, desc, ops = self._TEST_MODES[idx]
        self._mode_help.setText(f"{label}\n{desc}\n{ops}")
        self._refresh()

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

        samples = list(self._samples)
        valid = [s for s in samples if self._has_valid_cur(s)]
        invalid_count = len(samples) - len(valid)
        mirror_rate = self._sample_rate(samples)
        f5_rate = self._f5_input_rate(samples)
        rx_jump = self._rx_jump_count(samples)
        elapsed = 0.0
        if self._t_start is not None and samples:
            elapsed = max(0.0, samples[-1].ts - self._t_start)
        if self._running:
            phase = f"测试中 {elapsed:.1f}/{float(self._duration_s.value()):.1f}s"
        elif self._done:
            phase = "测试完成"
        else:
            phase = "未开始：点击“开始测试”后才采样"
        self._summary.setText(
            f"{phase} | 样本 {len(samples)} | 有效 {len(valid)} | 无效 {invalid_count} | "
            f"F5 {f5_rate:.1f}Hz / F6 {mirror_rate:.1f}Hz | 节流/漏显 {rx_jump}"
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

    @staticmethod
    def _f5_input_rate(samples: list[RpiPositionMirrorSample]) -> float:
        if len(samples) < 2:
            return 0.0
        span = samples[-1].ts - samples[0].ts
        delta = int(samples[-1].rx_cnt) - int(samples[0].rx_cnt)
        if span <= 1e-6 or delta < 0:
            return 0.0
        return float(delta) / span

    def _axis_stats(self, values: list[int]) -> list[str]:
        if not values:
            return ["0", "--", "--", "--", "--", "--", "--"]
        count = len(values)
        mean = sum(values) / count
        variance = sum((v - mean) * (v - mean) for v in values) / count
        std = sqrt(variance)
        mn = min(values)
        mx = max(values)
        p2p = mx - mn
        drift = values[-1] - values[0]
        jump_threshold = float(self._jump_cm.value())
        jumps = sum(
            1 for prev, cur in zip(values, values[1:])
            if abs(cur - prev) > jump_threshold
        )
        verdict = "好"
        if jumps > 0:
            verdict = "有跳变"
        elif p2p > 20.0 or abs(drift) > 15.0:
            verdict = "漂移偏大"
        elif p2p > 10.0 or std > 3.0:
            verdict = "需观察"
        return [
            str(count),
            f"{mean:.1f}",
            f"{std:.2f}",
            f"{p2p:.1f}",
            f"{drift:+.1f}",
            f"{mn} / {mx}",
            str(jumps),
            verdict,
        ]


class _CalibrationPage(QWidget):
    """坐标标定页：用原点、实际前进、实际左移三点估算平面坐标变换。"""

    _CAPTURE_ROWS = (
        ("原点 O", "起点，机头方向保持为后续 +X 参考"),
        ("前进点 X", "沿现实机头前方黑线移动后采样"),
        ("左移点 Y", "沿现实机体左侧黑线移动后采样"),
    )
    _DIAG_ROWS = (
        "前进向量",
        "左移向量",
        "夹角",
        "方向性",
        "变换矩阵",
        "当前换算",
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._latest: Optional[RpiPositionMirrorSample] = None
        self._points: list[Optional[tuple[int, int, int]]] = [None, None, None]
        self._build_ui()

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        self._refresh()

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        if not self._active:
            return
        self._latest = sample
        self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        guide_box = QGroupBox("操作引导", self)
        guide_box.setStyleSheet(
            "QGroupBox{background:#2B2B2B; color:#DCDCDC; font-size:12px;"
            " border:1px solid #555; margin-top:8px; padding-top:8px;}"
            "QGroupBox::title{subcontrol-origin: margin; left:8px; padding:0 4px;}"
        )
        guide_lay = QVBoxLayout(guide_box)
        guide = QLabel(
            "目标：用三次地面平移，判断树莓派发来的坐标与飞控坐标 X前 / Y左 是否对齐。\n"
            "第 1 步：把机体放在黑线交点，机头对准现实“前方线”，点击“1 采样原点 O”。\n"
            "第 2 步：沿机头前方黑线平移设定距离，停稳后点击“2 采样 +X 前进点”。\n"
            "第 3 步：回到原点，沿机体左侧黑线平移设定距离，停稳后点击“3 采样 +Y 左移点”。\n"
            "判断：夹角越接近 90° 越好；比例越接近 1 越好；方向性会提示是否需要换轴或取反。",
            guide_box,
        )
        guide.setWordWrap(True)
        guide.setStyleSheet("color:#F5F5F5; font-size:13px; line-height:125%;")
        guide_lay.addWidget(guide)
        root.addWidget(guide_box)

        controls_box = QGroupBox("标定采样（按步骤点击）", self)
        controls_box.setStyleSheet("QGroupBox{color:#B0B0B0; font-size:12px;}")
        controls = QHBoxLayout(controls_box)
        controls.setSpacing(12)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._forward_cm = QDoubleSpinBox(controls_box)
        self._forward_cm.setRange(10.0, 500.0)
        self._forward_cm.setSingleStep(10.0)
        self._forward_cm.setDecimals(1)
        self._forward_cm.setSuffix(" cm")
        self._forward_cm.setValue(100.0)
        self._forward_cm.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("前进实测距离", self._forward_cm)

        self._left_cm = QDoubleSpinBox(controls_box)
        self._left_cm.setRange(10.0, 500.0)
        self._left_cm.setSingleStep(10.0)
        self._left_cm.setDecimals(1)
        self._left_cm.setSuffix(" cm")
        self._left_cm.setValue(100.0)
        self._left_cm.valueChanged.connect(lambda _v: self._refresh())
        form.addRow("左移实测距离", self._left_cm)
        controls.addLayout(form)

        btn_origin = QPushButton("1 原点 O", controls_box)
        btn_forward = QPushButton("2 +X 前进", controls_box)
        btn_left = QPushButton("3 +Y 左移", controls_box)
        btn_clear = QPushButton("清空", controls_box)
        btn_origin.clicked.connect(lambda: self._capture(0))
        btn_forward.clicked.connect(lambda: self._capture(1))
        btn_left.clicked.connect(lambda: self._capture(2))
        btn_clear.clicked.connect(self._clear)
        controls.addWidget(btn_origin)
        controls.addWidget(btn_forward)
        controls.addWidget(btn_left)
        controls.addWidget(btn_clear)
        controls.addStretch(1)

        self._live_label = QLabel("等待有效 0xF6", controls_box)
        self._live_label.setWordWrap(True)
        self._live_label.setMaximumWidth(360)
        self._live_label.setStyleSheet("color:#69F0AE; font-size:20px; font-weight:bold;")
        self._live_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._live_label.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        controls.addWidget(self._live_label)
        root.addWidget(controls_box)

        self._capture_table = QTableWidget(len(self._CAPTURE_ROWS), 5, self)
        self._capture_table.setHorizontalHeaderLabels(["点位", "X cm", "Y cm", "Z cm", "用途"])
        self._setup_table(self._capture_table)
        for row, (name, desc) in enumerate(self._CAPTURE_ROWS):
            self._capture_table.setItem(row, 0, QTableWidgetItem(name))
            self._capture_table.setItem(row, 4, QTableWidgetItem(desc))
            for col in (1, 2, 3):
                item = QTableWidgetItem("--")
                item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._capture_table.setItem(row, col, item)
        self._capture_table.horizontalHeader().setStretchLastSection(True)
        root.addWidget(self._capture_table)

        self._diag_table = QTableWidget(len(self._DIAG_ROWS), 2, self)
        self._diag_table.setHorizontalHeaderLabels(["项目", "结果"])
        self._setup_table(self._diag_table)
        for row, name in enumerate(self._DIAG_ROWS):
            self._diag_table.setItem(row, 0, QTableWidgetItem(name))
            self._diag_table.setItem(row, 1, QTableWidgetItem("--"))
        self._diag_table.horizontalHeader().setStretchLastSection(True)
        self._diag_table.setColumnWidth(0, 120)
        root.addWidget(self._diag_table, 1)

        note = QLabel(
            "流程：机体放在原点并对准现实前方黑线，采样 O；沿前方黑线平移固定距离采样 +X；"
            "回到原点后沿左侧黑线平移固定距离采样 +Y。结果用于判断树莓派发来的坐标是否需要旋转、换轴或取反。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9E9E9E; font-size:12px;")
        root.addWidget(note)

    @staticmethod
    def _setup_table(table: QTableWidget) -> None:
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        table.setAlternatingRowColors(True)
        table.setStyleSheet(
            "QTableWidget{background:#232323; color:#DCDCDC; gridline-color:#3A3A3A;}"
            "QTableWidget::item{background:#232323; color:#DCDCDC;}"
            "QTableWidget::item:alternate{background:#2B2B2B; color:#DCDCDC;}"
            "QHeaderView::section{background:#333; color:#DCDCDC; padding:4px;}"
        )

    def _clear(self) -> None:
        self._points = [None, None, None]
        self._refresh()

    def _capture(self, idx: int) -> None:
        sample = self._latest
        if sample is None or not self._valid_cur(sample):
            self._live_label.setText("没有有效 SLAM 当前坐标，不能采样")
            self._live_label.setStyleSheet("color:#C62828; font-size:13px;")
            return
        self._points[idx] = (sample.cur_x_cm, sample.cur_y_cm, sample.cur_z_cm)
        self._refresh()

    @staticmethod
    def _valid_cur(sample: RpiPositionMirrorSample) -> bool:
        return (
            sample.slam_valid
            and sample.cur_x_cm != _INVALID_S32
            and sample.cur_y_cm != _INVALID_S32
            and sample.cur_z_cm != _INVALID_S32
        )

    def _refresh(self) -> None:
        sample = self._latest
        if not self._active:
            self._live_label.setText("未激活")
            self._live_label.setStyleSheet("color:#9E9E9E; font-size:20px; font-weight:bold;")
        elif sample is None:
            self._live_label.setText("等待有效 0xF6")
            self._live_label.setStyleSheet("color:#FFCA28; font-size:20px; font-weight:bold;")
        elif not self._valid_cur(sample):
            self._live_label.setText(f"当前 SLAM 无效 flags=0x{sample.flags:02X}")
            self._live_label.setStyleSheet("color:#FF5252; font-size:20px; font-weight:bold;")
        else:
            self._live_label.setText(
                f"当前 cur=({sample.cur_x_cm}, {sample.cur_y_cm}, {sample.cur_z_cm}) cm"
            )
            self._live_label.setStyleSheet("color:#69F0AE; font-size:20px; font-weight:bold;")

        for row, point in enumerate(self._points):
            values = point if point is not None else ("--", "--", "--")
            for col, value in enumerate(values, start=1):
                item = self._capture_table.item(row, col)
                if item is not None:
                    item.setText(str(value))
        self._refresh_diagnostics()

    def _refresh_diagnostics(self) -> None:
        o, px, py = self._points
        for row in range(len(self._DIAG_ROWS)):
            self._set_diag(row, "--")
        if o is None:
            self._set_diag(0, "先采样原点 O")
            return

        if px is not None:
            vx = (px[0] - o[0], px[1] - o[1])
            len_x = self._length2(vx)
            scale_x = len_x / float(self._forward_cm.value()) if self._forward_cm.value() else 0.0
            angle_x = degrees(atan2(vx[1], vx[0])) if len_x > 1e-6 else 0.0
            self._set_diag(0, f"d=({vx[0]}, {vx[1]}) | 长度 {len_x:.1f}cm | 比例 {scale_x:.3f} | 角度 {angle_x:.1f}°")
        else:
            self._set_diag(0, "等待采样 +X 前进点")

        if py is not None:
            vy = (py[0] - o[0], py[1] - o[1])
            len_y = self._length2(vy)
            scale_y = len_y / float(self._left_cm.value()) if self._left_cm.value() else 0.0
            angle_y = degrees(atan2(vy[1], vy[0])) if len_y > 1e-6 else 0.0
            self._set_diag(1, f"d=({vy[0]}, {vy[1]}) | 长度 {len_y:.1f}cm | 比例 {scale_y:.3f} | 角度 {angle_y:.1f}°")
        else:
            self._set_diag(1, "等待采样 +Y 左移点")

        if px is None or py is None:
            return
        vx = (px[0] - o[0], px[1] - o[1])
        vy = (py[0] - o[0], py[1] - o[1])
        len_x = self._length2(vx)
        len_y = self._length2(vy)
        det = vx[0] * vy[1] - vx[1] * vy[0]
        dot = vx[0] * vy[0] + vx[1] * vy[1]
        if len_x > 1e-6 and len_y > 1e-6:
            cos_angle = max(-1.0, min(1.0, dot / (len_x * len_y)))
            angle = degrees(atan2(abs(det), dot))
            self._set_diag(2, f"{angle:.1f}°（越接近90°越好，cos={cos_angle:.3f}）")
        else:
            self._set_diag(2, "采样距离过小，无法判断夹角")

        direction = "左手/右手不确定"
        if det > 1e-6:
            direction = "收到坐标中 +Y 在 +X 的逆时针侧"
        elif det < -1e-6:
            direction = "收到坐标中 +Y 在 +X 的顺时针侧，可能需要取反/换轴"
        self._set_diag(3, f"det={det:.1f} | {direction}")

        transform = self._transform_text(o, vx, vy)
        self._set_diag(4, transform)
        self._set_diag(5, self._current_transform_text(o, vx, vy))

    @staticmethod
    def _length2(v: tuple[int, int]) -> float:
        return sqrt(float(v[0] * v[0] + v[1] * v[1]))

    def _transform_text(
        self,
        origin: tuple[int, int, int],
        vx: tuple[int, int],
        vy: tuple[int, int],
    ) -> str:
        forward_cm = float(self._forward_cm.value())
        left_cm = float(self._left_cm.value())
        b00 = vx[0] / forward_cm
        b10 = vx[1] / forward_cm
        b01 = vy[0] / left_cm
        b11 = vy[1] / left_cm
        det = b00 * b11 - b01 * b10
        if abs(det) < 1e-6:
            return "矩阵不可逆：两次移动方向太接近或距离太短"
        inv00 = b11 / det
        inv01 = -b01 / det
        inv10 = -b10 / det
        inv11 = b00 / det
        return (
            f"先减O=({origin[0]},{origin[1]})；"
            f"flight_x={inv00:.3f}*dx + {inv01:.3f}*dy；"
            f"flight_y={inv10:.3f}*dx + {inv11:.3f}*dy"
        )

    def _current_transform_text(
        self,
        origin: tuple[int, int, int],
        vx: tuple[int, int],
        vy: tuple[int, int],
    ) -> str:
        sample = self._latest
        if sample is None or not self._valid_cur(sample):
            return "--"
        forward_cm = float(self._forward_cm.value())
        left_cm = float(self._left_cm.value())
        b00 = vx[0] / forward_cm
        b10 = vx[1] / forward_cm
        b01 = vy[0] / left_cm
        b11 = vy[1] / left_cm
        det = b00 * b11 - b01 * b10
        if abs(det) < 1e-6:
            return "矩阵不可逆"
        dx = sample.cur_x_cm - origin[0]
        dy = sample.cur_y_cm - origin[1]
        flight_x = (b11 * dx - b01 * dy) / det
        flight_y = (-b10 * dx + b00 * dy) / det
        return f"当前点换算约 flight=({flight_x:.1f}, {flight_y:.1f}) cm"

    def _set_diag(self, row: int, text: str) -> None:
        item = self._diag_table.item(row, 1)
        if item is not None:
            item.setText(text)


class _TrajectoryPage(QWidget):
    """轨迹页：记录 0xF6 当前坐标，显示 XY 路径并导出 CSV。"""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._recording = False
        self._t0: Optional[float] = None
        self._samples: Deque[RpiPositionMirrorSample] = deque(maxlen=30000)
        self._last_sample: Optional[RpiPositionMirrorSample] = None
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

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        if not self._active:
            return
        self._last_sample = sample
        if self._recording:
            if self._t0 is None:
                self._t0 = sample.ts
            self._samples.append(sample)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        top = QHBoxLayout()
        top.setSpacing(10)
        self._btn_start = QPushButton("开始记录", self)
        self._btn_stop = QPushButton("停止记录", self)
        self._btn_clear = QPushButton("清空轨迹", self)
        self._btn_export = QPushButton("导出 CSV", self)
        self._btn_start.clicked.connect(self._start)
        self._btn_stop.clicked.connect(self._stop)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_export.clicked.connect(self._export_csv)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(False)
        top.addWidget(self._btn_start)
        top.addWidget(self._btn_stop)
        top.addWidget(self._btn_clear)
        top.addWidget(self._btn_export)

        self._window_s = QDoubleSpinBox(self)
        self._window_s.setRange(1.0, 600.0)
        self._window_s.setDecimals(1)
        self._window_s.setSingleStep(5.0)
        self._window_s.setSuffix(" s")
        self._window_s.setValue(60.0)
        self._window_s.valueChanged.connect(lambda _v: self._refresh())
        top.addWidget(QLabel("显示窗口", self))
        top.addWidget(self._window_s)

        top.addStretch(1)
        self._status = QLabel("未记录", self)
        self._status.setStyleSheet("color:#222; font-size:13px;")
        top.addWidget(self._status)
        root.addLayout(top)

        if _PG_OK:
            pg.setConfigOptions(antialias=True)
            self._plot = pg.PlotWidget(self)
            self._plot.setBackground("#232323")
            self._plot.showGrid(x=True, y=True, alpha=0.25)
            self._plot.setLabel("bottom", "X 前+", units="cm")
            self._plot.setLabel("left", "Y 左+", units="cm")
            self._plot.setAspectLocked(True, ratio=1)
            self._plot.addLegend(offset=(10, 10))
            self._path_curve = self._plot.plot(
                pen=pg.mkPen("#4FC3F7", width=2),
                symbol="o",
                symbolSize=5,
                symbolBrush="#4FC3F7",
                name="cur XY",
            )
            self._target_curve = self._plot.plot(
                [],
                [],
                pen=None,
                symbol="x",
                symbolSize=12,
                symbolBrush=None,
                symbolPen=pg.mkPen("#FFCA28", width=2),
                name="target",
            )
            root.addWidget(self._plot, 1)
        else:
            self._plot = None
            self._path_curve = None
            self._target_curve = None
            label = QLabel(f"pyqtgraph 不可用，无法绘制轨迹：{_PG_IMPORT_ERR}", self)
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color:#C62828; font-size:14px;")
            root.addWidget(label, 1)

        self._stats_table = QTableWidget(6, 2, self)
        self._stats_table.setHorizontalHeaderLabels(["项目", "数值"])
        _CalibrationPage._setup_table(self._stats_table)
        rows = [
            "记录样本",
            "有效样本",
            "无效样本",
            "当前位置",
            "XY范围",
            "rx_cnt跳号/节流",
        ]
        for row, name in enumerate(rows):
            self._stats_table.setItem(row, 0, QTableWidgetItem(name))
            self._stats_table.setItem(row, 1, QTableWidgetItem("--"))
        self._stats_table.horizontalHeader().setStretchLastSection(True)
        self._stats_table.setMaximumHeight(190)
        root.addWidget(self._stats_table)

        note = QLabel(
            "说明：轨迹页记录的是 STM32 镜像下来的 0xF6 cur 坐标，用于地面路线、黑线平移和坐标对齐复盘；"
            "当前阶段仍不向飞控输出任何控制。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9E9E9E; font-size:12px;")
        root.addWidget(note)

    def _start(self) -> None:
        self._recording = True
        self._t0 = None
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status.setText("记录中")
        self._status.setStyleSheet("color:#1B5E20; font-size:13px; font-weight:bold;")
        self._refresh()

    def _stop(self) -> None:
        self._recording = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export.setEnabled(bool(self._samples))
        self._status.setText("已停止")
        self._status.setStyleSheet("color:#222; font-size:13px;")
        self._refresh()

    def _clear(self) -> None:
        self._samples.clear()
        self._t0 = None
        self._btn_export.setEnabled(False)
        self._refresh()

    def _visible_samples(self) -> list[RpiPositionMirrorSample]:
        if not self._samples:
            return []
        cutoff = self._samples[-1].ts - float(self._window_s.value())
        return [s for s in self._samples if s.ts >= cutoff]

    @staticmethod
    def _valid_cur(sample: RpiPositionMirrorSample) -> bool:
        return (
            sample.slam_valid
            and sample.cur_x_cm != _INVALID_S32
            and sample.cur_y_cm != _INVALID_S32
            and sample.cur_z_cm != _INVALID_S32
        )

    def _refresh(self) -> None:
        visible = self._visible_samples()
        valid = [s for s in visible if self._valid_cur(s)]
        if _PG_OK and self._path_curve is not None:
            self._path_curve.setData(
                [s.cur_x_cm for s in valid],
                [s.cur_y_cm for s in valid],
            )
            target = self._last_sample
            if (
                target is not None
                and target.target_valid
                and target.tar_x_cm != _INVALID_S32
                and target.tar_y_cm != _INVALID_S32
            ):
                self._target_curve.setData([target.tar_x_cm], [target.tar_y_cm])
            elif self._target_curve is not None:
                self._target_curve.setData([], [])
        self._update_stats(visible, valid)

    def _update_stats(
        self,
        visible: list[RpiPositionMirrorSample],
        valid: list[RpiPositionMirrorSample],
    ) -> None:
        total = len(self._samples)
        invalid = len(visible) - len(valid)
        last = self._last_sample
        self._set_stat(0, str(total))
        self._set_stat(1, str(len(valid)))
        self._set_stat(2, str(invalid))
        if last is not None and self._valid_cur(last):
            self._set_stat(3, f"({last.cur_x_cm}, {last.cur_y_cm}, {last.cur_z_cm}) cm")
        elif last is not None:
            self._set_stat(3, f"SLAM无效 flags=0x{last.flags:02X}")
        else:
            self._set_stat(3, "--")
        if valid:
            xs = [s.cur_x_cm for s in valid]
            ys = [s.cur_y_cm for s in valid]
            self._set_stat(4, f"X {min(xs)}..{max(xs)} cm | Y {min(ys)}..{max(ys)} cm")
        else:
            self._set_stat(4, "--")
        self._set_stat(5, str(_StabilityPage._rx_jump_count(visible)))
        self._btn_export.setEnabled(bool(self._samples))

    def _set_stat(self, row: int, text: str) -> None:
        item = self._stats_table.item(row, 1)
        if item is not None:
            item.setText(text)

    def _export_csv(self) -> None:
        if not self._samples:
            return
        default = os.path.join(os.getcwd(), "position_test_trajectory.csv")
        path, _ = QFileDialog.getSaveFileName(self, "导出位置测试轨迹", default, "CSV (*.csv)")
        if not path:
            return
        self.export_csv(path)
        self._status.setText(f"已导出 {len(self._samples)} 行")

    def export_csv(self, path: str) -> int:
        rows = list(self._samples)
        t0 = rows[0].ts if rows else 0.0
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "t_rel_s",
                "cur_x_cm",
                "cur_y_cm",
                "cur_z_cm",
                "tar_x_cm",
                "tar_y_cm",
                "tar_z_cm",
                "flags",
                "slam_valid",
                "target_valid",
                "visual_mode",
                "rx_cnt",
                "len_err_cnt",
                "checksum_err_cnt",
            ])
            for sample in rows:
                writer.writerow([
                    f"{sample.ts - t0:.3f}",
                    sample.cur_x_cm,
                    sample.cur_y_cm,
                    sample.cur_z_cm,
                    sample.tar_x_cm,
                    sample.tar_y_cm,
                    sample.tar_z_cm,
                    f"0x{sample.flags:02X}",
                    int(sample.slam_valid),
                    int(sample.target_valid),
                    int(sample.visual_mode),
                    sample.rx_cnt,
                    sample.len_err_cnt,
                    sample.checksum_err_cnt,
                ])
        return len(rows)


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
        self._calibration = _CalibrationPage(self)
        self._stability = _StabilityPage(self)
        self._trajectory = _TrajectoryPage(self)
        self._tabs.addTab(self._realtime, "实时数据")
        self._tabs.addTab(self._calibration, "坐标标定")
        self._tabs.addTab(self._stability, "稳定性")
        self._tabs.addTab(self._trajectory, "轨迹回放")
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
        self._calibration.set_active(active and self._tabs.currentWidget() is self._calibration)
        self._stability.set_active(active and self._tabs.currentWidget() is self._stability)
        self._trajectory.set_active(active and self._tabs.currentWidget() is self._trajectory)

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
            self._calibration.on_sample(sample)
            self._stability.on_sample(sample)
            self._trajectory.on_sample(sample)
