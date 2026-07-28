# -*- coding: utf-8 -*-
"""位置测试独立功能页。"""
from __future__ import annotations

import csv
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from math import atan2, degrees, sqrt
from typing import Callable, Deque, Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QScrollArea,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from gui.io.protocol import (
    AUTO_CMD_ABORT_LAND,
    AUTO_CMD_EMERGENCY_LOCK,
    AUTO_CMD_LAND_ONLY,
    AUTO_CMD_LOCK_RC,
    AUTO_CMD_PRECHECK,
    AUTO_CMD_QUERY_STATUS,
    AUTO_CMD_REQUEST_MODE2,
    AUTO_CMD_TAKEOFF_HOLD,
    AUTO_FLAG_NO_XY_MOTION,
    AUTO_MOVE_AXIS_AUTO,
    AUTO_MOVE_AXIS_XY,
    AUTO_MOVE_CMD_START,
    AUTO_MOVE_CMD_STOP,
    CMD_AUTO_MISSION,
    CMD_AUTO_MOVE,
    CMD_AUTO_STATUS,
    CMD_AUTO_VELOCITY,
    CMD_RPI_POSITION_MIRROR,
)
from gui.services.auto_mission_labels import cmd_label, error_label, state_label
from gui.services.telemetry_decoder import decode_auto_mission_status, decode_rpi_position_mirror
from gui.services.telemetry_models import AutoMissionStatusSample, RpiPositionMirrorSample

try:
    import pyqtgraph as pg
    _PG_OK = True
except Exception as _pg_exc:  # pragma: no cover - depends on runtime env
    pg = None
    _PG_OK = False
    _PG_IMPORT_ERR = repr(_pg_exc)


_INVALID_S32 = -2147483648
_AUTO_STATE_MOVE_HOLD = 24
_F6_SEGMENT_FRESH_S = 1.0
_EXPORT_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, "logs", "position_test_exports")
)


def _default_export_path(prefix: str, suffix: str) -> str:
    os.makedirs(_EXPORT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return os.path.join(_EXPORT_DIR, f"{prefix}_{stamp}.{suffix.lstrip('.')}")


def _short_path(path: str, *, max_len: int = 64) -> str:
    try:
        text = os.path.relpath(path, os.getcwd())
    except Exception:
        text = str(path)
    if len(text) <= max_len:
        return text
    return "..." + text[-max(12, max_len - 3):]


def _choose_save_file(
    parent: QWidget,
    title: str,
    default_path: str,
    name_filter: str,
    suffix: str,
) -> str:
    """Use Qt's non-native dialog; native dialogs can hang on some Ubuntu setups."""
    dialog = QFileDialog(parent, title)
    dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
    dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
    dialog.setFileMode(QFileDialog.FileMode.AnyFile)
    dialog.setNameFilter(name_filter)
    dialog.setDefaultSuffix(suffix.lstrip("."))
    dialog.setDirectory(os.path.dirname(default_path))
    dialog.selectFile(os.path.basename(default_path))
    if not dialog.exec():
        return ""
    files = dialog.selectedFiles()
    return files[0] if files else ""


@dataclass
class _CommandEvent:
    ts: float
    iso: str
    cmd_id: int
    name: str
    desc: str
    params: dict


@dataclass
class _MoveSegment:
    seq: int
    ts_start: float
    x_cm: float
    y_cm: float
    z_cm: float
    start_xy: Optional[tuple[int, int]]
    expected_xy: Optional[tuple[float, float]]
    done_ts: Optional[float] = None
    actual_xy: Optional[tuple[int, int]] = None
    error_cm: Optional[float] = None


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
        controls.addSpacing(18)

        self._summary = QLabel("未开始", control_box)
        self._summary.setWordWrap(False)
        self._summary.setStyleSheet("color:#69F0AE; font-size:17px; font-weight:bold;")
        self._summary.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._summary.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        controls.addWidget(self._summary, 1)
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
            phase = f"测试 {elapsed:.1f}/{float(self._duration_s.value()):.1f}s"
        elif self._done:
            phase = "完成"
        else:
            phase = ""
        prefix = f"{phase} | " if phase else ""
        self._summary.setText(
            f"{prefix}样本 {len(samples)} | 有效 {len(valid)} | 无效 {invalid_count} | "
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
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        outer.addWidget(scroll, 1)

        content = QWidget(scroll)
        scroll.setWidget(content)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

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
        self._fit_table_to_rows(self._capture_table, len(self._CAPTURE_ROWS), 35)
        root.addWidget(self._capture_table, 0)

        self._diag_table = QTableWidget(len(self._DIAG_ROWS), 2, self)
        self._diag_table.setHorizontalHeaderLabels(["项目", "结果"])
        self._setup_table(self._diag_table)
        for row, name in enumerate(self._DIAG_ROWS):
            self._diag_table.setItem(row, 0, QTableWidgetItem(name))
            self._diag_table.setItem(row, 1, QTableWidgetItem("--"))
        self._diag_table.horizontalHeader().setStretchLastSection(True)
        self._diag_table.setColumnWidth(0, 120)
        self._fit_table_to_rows(self._diag_table, len(self._DIAG_ROWS), 35)
        root.addWidget(self._diag_table, 0)

        note = QLabel(
            "流程：机体放在原点并对准现实前方黑线，采样 O；沿前方黑线平移固定距离采样 +X；"
            "回到原点后沿左侧黑线平移固定距离采样 +Y。结果用于判断树莓派发来的坐标是否需要旋转、换轴或取反。",
            self,
        )
        note.setWordWrap(True)
        note.setStyleSheet("color:#9E9E9E; font-size:12px;")
        root.addWidget(note)
        root.addStretch(1)

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

    @staticmethod
    def _fit_table_to_rows(table: QTableWidget, rows: int, row_height: int) -> None:
        for row in range(rows):
            table.setRowHeight(row, row_height)
        header_h = max(table.horizontalHeader().sizeHint().height(), 30)
        height = header_h + rows * row_height + 8
        table.setMinimumHeight(height)
        table.setMaximumHeight(height)
        table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

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
        default = _default_export_path("position_test_trajectory", "csv")
        path = _choose_save_file(self, "导出位置测试轨迹", default, "CSV (*.csv)", "csv")
        if not path:
            return
        try:
            rows = self.export_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"位置测试轨迹 CSV 导出失败：\n{exc}")
            self._status.setText("导出失败")
            return
        self._status.setText(f"已导出 {rows} 行：{path}")

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


class _SessionRecorderPage(QWidget):
    """雷达/SLAM质量会话记录页：持续记录F6/F8/GUI命令事件。"""

    _METRIC_ROWS = (
        "记录状态",
        "记录时长",
        "0xF6样本",
        "SLAM有效率",
        "F5输入/F6镜像",
        "错误计数增量",
        "XY抖动σ",
        "Z抖动σ",
        "XY漂移",
        "跳变",
        "F8状态/错误",
        "F9闭环误差",
    )

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._active = False
        self._recording = False
        self._t0: Optional[float] = None
        self._start_iso = ""
        self._f6_samples: list[RpiPositionMirrorSample] = []
        self._f8_samples: list[AutoMissionStatusSample] = []
        self._commands: list[_CommandEvent] = []
        self._segments: list[_MoveSegment] = []
        self._last_f6: Optional[RpiPositionMirrorSample] = None
        self._last_f8: Optional[AutoMissionStatusSample] = None
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._refresh)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        elif not self._recording:
            self._timer.stop()
        self._refresh()

    def is_recording(self) -> bool:
        return self._recording

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        self._last_f6 = sample
        if self._recording:
            self._f6_samples.append(sample)
        if self._active:
            self._refresh()

    def on_auto_status(self, sample: AutoMissionStatusSample) -> None:
        self._last_f8 = sample
        if self._recording:
            self._f8_samples.append(sample)
            self._mark_move_done(sample)
        if self._active:
            self._refresh()

    def on_command_sent(self, cmd_id: int, params: dict, desc: str, *, silent: bool = False) -> None:
        if not self._recording:
            return
        if silent and int(cmd_id) == CMD_AUTO_VELOCITY:
            return
        event = _CommandEvent(
            ts=time.monotonic(),
            iso=datetime.now().isoformat(timespec="milliseconds"),
            cmd_id=int(cmd_id) & 0xFF,
            name=self._command_name(cmd_id, params),
            desc=str(desc),
            params=dict(params),
        )
        self._commands.append(event)
        self._maybe_start_move_segment(event)
        if self._active:
            self._refresh()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)
        self._btn_start = QPushButton("开始会话记录", self)
        self._btn_stop = QPushButton("停止记录", self)
        self._btn_clear = QPushButton("清空", self)
        self._btn_export_csv = QPushButton("导出 CSV", self)
        self._btn_export_report = QPushButton("导出报告", self)
        self._btn_start.clicked.connect(self._start)
        self._btn_stop.clicked.connect(self._stop)
        self._btn_clear.clicked.connect(self._clear)
        self._btn_export_csv.clicked.connect(self._export_csv_dialog)
        self._btn_export_report.clicked.connect(self._export_report_dialog)
        self._btn_stop.setEnabled(False)
        self._btn_export_csv.setEnabled(False)
        self._btn_export_report.setEnabled(False)
        for btn in (
            self._btn_start,
            self._btn_stop,
            self._btn_clear,
            self._btn_export_csv,
            self._btn_export_report,
        ):
            controls.addWidget(btn)
        controls.addStretch(1)
        self._status = QLabel("未记录", self)
        self._status.setStyleSheet("color:#777; font-weight:bold;")
        self._status.setWordWrap(True)
        self._status.setMaximumHeight(46)
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        controls.addWidget(self._status)
        root.addLayout(controls)

        hint = QLabel(
            "用途：从这里开始记录后，可以切到自主飞行控制页执行一键起飞、F9位移、固定巡航；"
            "本页会继续后台记录 0xF6 雷达位置、0xF8 状态和 GUI 命令事件。当前仍只读观测，不参与控制。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#CFCFCF; font-size:13px;")
        root.addWidget(hint)

        if _PG_OK:
            pg.setConfigOptions(antialias=True)
            self._plot = pg.PlotWidget(self)
            self._plot.setBackground("#232323")
            self._plot.showGrid(x=True, y=True, alpha=0.25)
            self._plot.setLabel("bottom", "X 前+", units="cm")
            self._plot.setLabel("left", "Y 左+", units="cm")
            self._plot.setAspectLocked(True, ratio=1)
            self._plot.addLegend(offset=(10, 10))
            self._cur_curve = self._plot.plot(
                pen=pg.mkPen("#4FC3F7", width=2),
                symbol="o",
                symbolSize=4,
                symbolBrush="#4FC3F7",
                name="雷达cur",
            )
            self._expected_curve = self._plot.plot(
                pen=pg.mkPen("#FFCA28", width=2, style=Qt.PenStyle.DashLine),
                symbol="x",
                symbolSize=8,
                symbolPen=pg.mkPen("#FFCA28", width=2),
                name="F9期望段",
            )
            root.addWidget(self._plot, 2)
        else:
            self._plot = None
            self._cur_curve = None
            self._expected_curve = None
            label = QLabel(f"pyqtgraph 不可用，无法绘制对比轨迹：{_PG_IMPORT_ERR}", self)
            label.setStyleSheet("color:#C62828; font-size:14px;")
            root.addWidget(label, 1)

        lower = QHBoxLayout()
        self._metrics = QTableWidget(len(self._METRIC_ROWS), 2, self)
        self._metrics.setHorizontalHeaderLabels(["指标", "结果"])
        _CalibrationPage._setup_table(self._metrics)
        for row, name in enumerate(self._METRIC_ROWS):
            self._metrics.setItem(row, 0, QTableWidgetItem(name))
            self._metrics.setItem(row, 1, QTableWidgetItem("--"))
        self._metrics.horizontalHeader().setStretchLastSection(True)
        self._metrics.setMinimumWidth(420)
        lower.addWidget(self._metrics, 1)

        self._segments_table = QTableWidget(0, 6, self)
        self._segments_table.setHorizontalHeaderLabels(["seq", "指令cm", "起点XY", "期望终点", "到位点", "误差cm"])
        _CalibrationPage._setup_table(self._segments_table)
        self._segments_table.horizontalHeader().setStretchLastSection(True)
        self._segments_table.setMinimumWidth(520)
        lower.addWidget(self._segments_table, 1)
        root.addLayout(lower, 1)

    def _start(self) -> None:
        self._clear_data()
        self._recording = True
        self._t0 = time.monotonic()
        self._start_iso = datetime.now().isoformat(timespec="seconds")
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._btn_export_csv.setEnabled(False)
        self._btn_export_report.setEnabled(False)
        if not self._timer.isActive():
            self._timer.start()
        self._refresh()

    def _stop(self) -> None:
        self._recording = False
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._btn_export_csv.setEnabled(bool(self._f6_samples or self._f8_samples or self._commands))
        self._btn_export_report.setEnabled(bool(self._f6_samples or self._f8_samples or self._commands))
        if not self._active:
            self._timer.stop()
        self._refresh()

    def _clear(self) -> None:
        if self._recording:
            return
        self._clear_data()
        self._btn_export_csv.setEnabled(False)
        self._btn_export_report.setEnabled(False)
        self._refresh()

    def _clear_data(self) -> None:
        self._t0 = None
        self._start_iso = ""
        self._f6_samples.clear()
        self._f8_samples.clear()
        self._commands.clear()
        self._segments.clear()

    def start_recording(self) -> None:
        if not self._recording:
            self._start()

    def stop_recording(self) -> None:
        if self._recording:
            self._stop()

    def has_data(self) -> bool:
        return bool(self._f6_samples or self._f8_samples or self._commands)

    def counts_text(self) -> str:
        state = "记录中" if self._recording else ("已停止" if self.has_data() else "未记录")
        return f"{state} | F6 {len(self._f6_samples)} | F8 {len(self._f8_samples)} | 命令 {len(self._commands)}"

    def export_default_bundle(self, *, stop_first: bool = True) -> tuple[str, str, int]:
        if stop_first and self._recording:
            self._stop()
        if not self.has_data():
            raise ValueError("当前没有可导出的雷达会话数据")
        csv_path = _default_export_path("position_test_session", "csv")
        report_path = _default_export_path("position_test_quality_report", "txt")
        rows = self.export_csv(csv_path)
        self.export_report(report_path)
        self._btn_export_csv.setEnabled(True)
        self._btn_export_report.setEnabled(True)
        self._status.setToolTip(f"CSV: {csv_path}\n报告: {report_path}")
        self._status.setText(f"已一键导出：CSV {rows} 行；报告 {_short_path(report_path)}")
        self._refresh()
        return csv_path, report_path, rows

    def _refresh(self) -> None:
        self._refresh_plot()
        self._refresh_metrics()
        self._refresh_segments_table()

    def _refresh_plot(self) -> None:
        if not _PG_OK or self._cur_curve is None:
            return
        valid = [s for s in self._f6_samples if self._valid_cur(s)]
        self._cur_curve.setData([s.cur_x_cm for s in valid], [s.cur_y_cm for s in valid])
        xs: list[float] = []
        ys: list[float] = []
        for seg in self._segments:
            if seg.start_xy is None or seg.expected_xy is None:
                continue
            xs.extend([seg.start_xy[0], seg.expected_xy[0], float("nan")])
            ys.extend([seg.start_xy[1], seg.expected_xy[1], float("nan")])
        if self._expected_curve is not None:
            self._expected_curve.setData(xs, ys)

    def _refresh_metrics(self) -> None:
        valid = [s for s in self._f6_samples if self._valid_cur(s)]
        total = len(self._f6_samples)
        duration = self._duration_s()
        f5_rate = self._f5_rate(self._f6_samples)
        f6_rate = self._sample_rate(self._f6_samples)
        err_delta = self._err_delta()
        xy_std = self._xy_std(valid)
        z_std = self._std([s.cur_z_cm for s in valid])
        xy_drift = self._xy_drift(valid)
        jumps = self._jump_count(valid, threshold_cm=20.0)
        f8_text = "--"
        if self._last_f8 is not None:
            f8_text = (
                f"{state_label(self._last_f8.state)} / "
                f"{error_label(self._last_f8.error)} / "
                f"{cmd_label(self._last_f8.last_cmd)} seq={self._last_f8.last_cmd_seq}"
            )
        closed = [seg.error_cm for seg in self._segments if seg.error_cm is not None]
        closed_text = "--" if not closed else (
            f"最近 {closed[-1]:.1f}cm / 平均 {sum(closed) / len(closed):.1f}cm / {len(closed)}段"
        )

        rows = [
            "记录中" if self._recording else ("已停止" if total or self._commands else "未记录"),
            f"{duration:.1f}s",
            f"{total}（有效 {len(valid)}）",
            "--" if total == 0 else f"{(len(valid) / total * 100.0):.1f}%",
            f"{f5_rate:.1f} / {f6_rate:.1f} Hz",
            err_delta,
            "--" if xy_std is None else f"{xy_std:.2f} cm",
            "--" if z_std is None else f"{z_std:.2f} cm",
            "--" if xy_drift is None else f"{xy_drift:.1f} cm",
            str(jumps),
            f8_text,
            closed_text,
        ]
        for row, text in enumerate(rows):
            self._set_metric(row, text)

        self._status.setText(
            f"{'记录中' if self._recording else '未记录/已停止'} | "
            f"F6 {total} | F8 {len(self._f8_samples)} | 命令 {len(self._commands)}"
        )
        self._status.setStyleSheet(
            "color:#2E7D32; font-weight:bold;" if self._recording else "color:#777; font-weight:bold;"
        )

    def _refresh_segments_table(self) -> None:
        self._segments_table.setRowCount(len(self._segments))
        for row, seg in enumerate(self._segments):
            values = [
                str(seg.seq),
                f"X={seg.x_cm:.0f} Y={seg.y_cm:.0f} Z={seg.z_cm:.0f}",
                self._xy_text(seg.start_xy),
                self._xy_text(seg.expected_xy),
                self._xy_text(seg.actual_xy),
                "--" if seg.error_cm is None else f"{seg.error_cm:.1f}",
            ]
            for col, text in enumerate(values):
                item = QTableWidgetItem(text)
                if col != 1:
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self._segments_table.setItem(row, col, item)

    def _export_csv_dialog(self) -> None:
        if not (self._f6_samples or self._f8_samples or self._commands):
            return
        default = _default_export_path("position_test_session", "csv")
        path = _choose_save_file(self, "导出位置测试会话CSV", default, "CSV (*.csv)", "csv")
        if not path:
            return
        try:
            rows = self.export_csv(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"位置测试会话 CSV 导出失败：\n{exc}")
            self._status.setText("CSV 导出失败")
            return
        self._status.setToolTip(path)
        self._status.setText(f"已导出 CSV {rows} 行：{_short_path(path)}")

    def _export_report_dialog(self) -> None:
        if not (self._f6_samples or self._f8_samples or self._commands):
            return
        default = _default_export_path("position_test_quality_report", "txt")
        path = _choose_save_file(self, "导出雷达质量报告", default, "Text (*.txt)", "txt")
        if not path:
            return
        try:
            self.export_report(path)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", f"雷达质量报告导出失败：\n{exc}")
            self._status.setText("报告导出失败")
            return
        self._status.setToolTip(path)
        self._status.setText(f"已导出质量报告：{_short_path(path)}")

    def export_csv(self, path: str) -> int:
        t0 = self._first_ts()
        rows: list[tuple[float, list[object]]] = []
        for sample in self._f6_samples:
            rows.append((sample.ts, [
                sample.ts - t0,
                "F6",
                sample.cur_x_cm,
                sample.cur_y_cm,
                sample.cur_z_cm,
                sample.tar_x_cm,
                sample.tar_y_cm,
                sample.tar_z_cm,
                f"0x{sample.flags:02X}",
                int(sample.slam_valid),
                int(sample.target_valid),
                sample.rx_cnt,
                sample.len_err_cnt,
                sample.checksum_err_cnt,
                "", "", "", "", "",
            ]))
        for sample in self._f8_samples:
            rows.append((sample.ts, [
                sample.ts - t0,
                "F8",
                "", "", "", "", "", "",
                f"0x{sample.flags:04X}",
                "", "",
                "", "", "",
                state_label(sample.state),
                error_label(sample.error),
                cmd_label(sample.last_cmd),
                sample.last_cmd_seq,
                f"{sample.voltage_v:.2f}V alt={sample.alt_cm}cm",
            ]))
        for event in self._commands:
            rows.append((event.ts, [
                event.ts - t0,
                "CMD",
                "", "", "", "", "", "",
                "", "", "",
                "", "", "",
                event.name,
                "",
                f"0x{event.cmd_id:02X}",
                event.params.get("seq", ""),
                event.desc,
            ]))
        rows.sort(key=lambda item: item[0])
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow([
                "t_rel_s",
                "type",
                "cur_x_cm",
                "cur_y_cm",
                "cur_z_cm",
                "tar_x_cm",
                "tar_y_cm",
                "tar_z_cm",
                "flags",
                "slam_valid",
                "target_valid",
                "rx_cnt",
                "len_err_cnt",
                "checksum_err_cnt",
                "state_or_name",
                "error",
                "cmd",
                "seq",
                "note",
            ])
            for _ts, row in rows:
                row[0] = f"{float(row[0]):.3f}"
                writer.writerow(row)
        return len(rows)

    def export_report(self, path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            f.write(self._report_text())

    def _report_text(self) -> str:
        valid = [s for s in self._f6_samples if self._valid_cur(s)]
        total = len(self._f6_samples)
        closed = [seg for seg in self._segments if seg.error_cm is not None]
        lines = [
            "位置测试 / 雷达SLAM质量报告",
            f"开始时间: {self._start_iso or '--'}",
            f"记录时长: {self._duration_s():.1f}s",
            f"F6样本: {total}, 有效: {len(valid)}, 有效率: {0.0 if total == 0 else len(valid) / total * 100.0:.1f}%",
            f"频率: F5输入 {self._f5_rate(self._f6_samples):.1f}Hz / F6镜像 {self._sample_rate(self._f6_samples):.1f}Hz",
            f"错误计数增量: {self._err_delta()}",
            f"XY抖动σ: {self._fmt_optional(self._xy_std(valid), 'cm')}",
            f"Z抖动σ: {self._fmt_optional(self._std([s.cur_z_cm for s in valid]), 'cm')}",
            f"XY漂移: {self._fmt_optional(self._xy_drift(valid), 'cm')}",
            f"跳变(>20cm): {self._jump_count(valid, threshold_cm=20.0)}",
            f"F8样本: {len(self._f8_samples)}, 命令事件: {len(self._commands)}",
            "",
            "F9段误差:",
        ]
        if not self._segments:
            lines.append("- 无F9相对位移段")
        for seg in self._segments:
            err = "--" if seg.error_cm is None else f"{seg.error_cm:.1f}cm"
            lines.append(
                f"- seq={seg.seq} cmd=({seg.x_cm:.0f},{seg.y_cm:.0f},{seg.z_cm:.0f}) "
                f"start={self._xy_text(seg.start_xy)} expected={self._xy_text(seg.expected_xy)} "
                f"actual={self._xy_text(seg.actual_xy)} err={err}"
            )
        if closed:
            mean_err = sum(float(seg.error_cm or 0.0) for seg in closed) / len(closed)
            lines.append(f"闭环/到位平均误差: {mean_err:.1f}cm")
        lines.extend([
            "",
            "判读纪律:",
            "- 当前只读观测，不接位置环，不写rt_tar，不触发0x41。",
            "- 若静止有效率低、跳变多、漂移大，先在树莓派侧修SLAM/坐标转换。",
            "- F9期望段只用于对比雷达观测，不代表飞控已使用树莓派位置控制。",
        ])
        return "\n".join(lines) + "\n"

    def _maybe_start_move_segment(self, event: _CommandEvent) -> None:
        if event.cmd_id != CMD_AUTO_MOVE:
            return
        try:
            cmd = int(event.params.get("cmd", -1))
            seq = int(event.params.get("seq", 0))
        except Exception:
            return
        if cmd != AUTO_MOVE_CMD_START:
            return
        start_xy = self._last_valid_xy(ref_ts=event.ts)
        x_cm = float(event.params.get("x_cm", 0.0))
        y_cm = float(event.params.get("y_cm", 0.0))
        z_cm = float(event.params.get("z_cm", 0.0))
        expected = None
        if start_xy is not None:
            expected = (start_xy[0] + x_cm, start_xy[1] + y_cm)
        self._segments.append(_MoveSegment(seq, event.ts, x_cm, y_cm, z_cm, start_xy, expected))

    def _mark_move_done(self, sample: AutoMissionStatusSample) -> None:
        if sample.last_cmd != CMD_AUTO_MOVE or sample.state != _AUTO_STATE_MOVE_HOLD or sample.error != 0:
            return
        for seg in reversed(self._segments):
            if seg.seq != sample.last_cmd_seq or seg.done_ts is not None:
                continue
            actual = self._last_valid_xy(ref_ts=sample.ts)
            seg.done_ts = sample.ts
            seg.actual_xy = actual
            if actual is not None and seg.expected_xy is not None:
                dx = actual[0] - seg.expected_xy[0]
                dy = actual[1] - seg.expected_xy[1]
                seg.error_cm = sqrt(dx * dx + dy * dy)
            break

    def _last_valid_xy(self, *, ref_ts: Optional[float] = None) -> Optional[tuple[int, int]]:
        ref = time.monotonic() if ref_ts is None else float(ref_ts)

        def fresh(sample: Optional[RpiPositionMirrorSample]) -> bool:
            if sample is None or not self._valid_cur(sample):
                return False
            age = ref - float(sample.ts)
            return -0.05 <= age <= _F6_SEGMENT_FRESH_S

        sample = self._last_f6
        if fresh(sample):
            return (sample.cur_x_cm, sample.cur_y_cm)  # type: ignore[union-attr]
        for sample in reversed(self._f6_samples):
            if fresh(sample):
                return (sample.cur_x_cm, sample.cur_y_cm)
        return None

    @staticmethod
    def _valid_cur(sample: RpiPositionMirrorSample) -> bool:
        return (
            sample.slam_valid
            and sample.cur_x_cm != _INVALID_S32
            and sample.cur_y_cm != _INVALID_S32
            and sample.cur_z_cm != _INVALID_S32
        )

    def _duration_s(self) -> float:
        if self._t0 is None:
            return 0.0
        if self._recording:
            return max(0.0, time.monotonic() - self._t0)
        last_ts = self._first_ts()
        for seq in (self._f6_samples, self._f8_samples, self._commands):
            if seq:
                last_ts = max(last_ts, seq[-1].ts)
        return max(0.0, last_ts - self._t0)

    def _first_ts(self) -> float:
        candidates: list[float] = []
        if self._t0 is not None:
            candidates.append(self._t0)
        if self._f6_samples:
            candidates.append(self._f6_samples[0].ts)
        if self._f8_samples:
            candidates.append(self._f8_samples[0].ts)
        if self._commands:
            candidates.append(self._commands[0].ts)
        return min(candidates) if candidates else time.monotonic()

    @staticmethod
    def _sample_rate(samples: list[RpiPositionMirrorSample]) -> float:
        if len(samples) < 2:
            return 0.0
        span = samples[-1].ts - samples[0].ts
        return (len(samples) - 1) / span if span > 1e-6 else 0.0

    @staticmethod
    def _f5_rate(samples: list[RpiPositionMirrorSample]) -> float:
        if len(samples) < 2:
            return 0.0
        span = samples[-1].ts - samples[0].ts
        delta = int(samples[-1].rx_cnt) - int(samples[0].rx_cnt)
        if span <= 1e-6 or delta < 0:
            return 0.0
        return float(delta) / span

    def _err_delta(self) -> str:
        if len(self._f6_samples) < 2:
            return "--"
        first = self._f6_samples[0]
        last = self._f6_samples[-1]
        return (
            f"LEN +{int(last.len_err_cnt) - int(first.len_err_cnt)} / "
            f"CK +{int(last.checksum_err_cnt) - int(first.checksum_err_cnt)}"
        )

    @staticmethod
    def _std(values: list[int]) -> Optional[float]:
        if not values:
            return None
        mean = sum(values) / len(values)
        return sqrt(sum((v - mean) * (v - mean) for v in values) / len(values))

    def _xy_std(self, samples: list[RpiPositionMirrorSample]) -> Optional[float]:
        if not samples:
            return None
        sx = self._std([s.cur_x_cm for s in samples]) or 0.0
        sy = self._std([s.cur_y_cm for s in samples]) or 0.0
        return sqrt(sx * sx + sy * sy)

    @staticmethod
    def _xy_drift(samples: list[RpiPositionMirrorSample]) -> Optional[float]:
        if len(samples) < 2:
            return None
        dx = samples[-1].cur_x_cm - samples[0].cur_x_cm
        dy = samples[-1].cur_y_cm - samples[0].cur_y_cm
        return sqrt(float(dx * dx + dy * dy))

    @staticmethod
    def _jump_count(samples: list[RpiPositionMirrorSample], threshold_cm: float) -> int:
        jumps = 0
        for prev, cur in zip(samples, samples[1:]):
            dx = cur.cur_x_cm - prev.cur_x_cm
            dy = cur.cur_y_cm - prev.cur_y_cm
            dz = cur.cur_z_cm - prev.cur_z_cm
            if sqrt(float(dx * dx + dy * dy + dz * dz)) > threshold_cm:
                jumps += 1
        return jumps

    @staticmethod
    def _xy_text(value: object) -> str:
        if value is None:
            return "--"
        try:
            x, y = value  # type: ignore[misc]
            return f"({float(x):.0f}, {float(y):.0f})"
        except Exception:
            return str(value)

    @staticmethod
    def _fmt_optional(value: Optional[float], unit: str) -> str:
        return "--" if value is None else f"{value:.2f}{unit}"

    @staticmethod
    def _command_name(cmd_id: int, params: dict) -> str:
        cmd_id = int(cmd_id) & 0xFF
        raw_cmd = int(params.get("cmd", -1)) if "cmd" in params else -1
        if cmd_id == CMD_AUTO_MISSION:
            return f"F7 {cmd_label(raw_cmd)}"
        if cmd_id == CMD_AUTO_MOVE:
            if raw_cmd == AUTO_MOVE_CMD_START:
                return "F9 启动位移"
            return f"F9 cmd={raw_cmd}"
        if cmd_id == CMD_AUTO_VELOCITY:
            return f"FA cmd={raw_cmd}"
        return f"0x{cmd_id:02X}"

    def _set_metric(self, row: int, text: str) -> None:
        item = self._metrics.item(row, 1)
        if item is not None:
            item.setText(text)


class _RadarWorkflowPage(QWidget):
    """临时雷达联调页：把记录、起飞、正方形巡航、降落、导出集中到一页。"""

    def __init__(
        self,
        session: _SessionRecorderPage,
        send_command_fn: Optional[Callable[[int, dict], None]],
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._session = session
        self._send_command_fn = send_command_fn
        self._active = False
        self._link_connected = False
        seed = int(time.monotonic() * 1000.0) & 0xFFFF
        self._f7_seq = self._next_seq(seed)
        self._f9_seq = self._next_seq(seed + 97)
        self._last_f8: Optional[AutoMissionStatusSample] = None
        self._last_f6: Optional[RpiPositionMirrorSample] = None
        self._f6_recent: Deque[RpiPositionMirrorSample] = deque(maxlen=200)
        self._route_active = False
        self._route_legs: list[tuple[float, float, float]] = []
        self._route_index = 0
        self._route_waiting_seq: Optional[int] = None
        self._route_timer_pending = False
        self._route_name = ""
        self._route_axis_mode = AUTO_MOVE_AXIS_AUTO
        self._buttons: list[QPushButton] = []
        self._build_ui()
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._refresh_status)

    def set_active(self, active: bool) -> None:
        self._active = bool(active)
        if active:
            if not self._timer.isActive():
                self._timer.start()
        elif not self._route_active:
            self._timer.stop()
        self._refresh_status()

    def set_link_connected(self, connected: bool) -> None:
        self._link_connected = bool(connected)
        self._refresh_buttons()
        self._refresh_status()

    def is_route_active(self) -> bool:
        return self._route_active or self._route_waiting_seq is not None

    def on_sample(self, sample: RpiPositionMirrorSample) -> None:
        self._last_f6 = sample
        self._f6_recent.append(sample)
        self._refresh_status()

    def on_auto_status(self, sample: AutoMissionStatusSample) -> None:
        self._last_f8 = sample
        self._update_f8_labels(sample)
        self._advance_route_on_status(sample)
        self._refresh_status()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        content = QWidget(scroll)
        content.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        root = QVBoxLayout(content)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        title = QLabel(
            "<b>雷达联调临时页</b>  "
            "<span style='color:#777;'>记录0xF6 + 一键起飞 + 多轨迹巡航 + 降落 + 一键导出</span>",
            self,
        )
        title.setWordWrap(True)
        title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(title)

        status_box = QGroupBox("关键状态", self)
        grid = QGridLayout(status_box)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(5)
        self._labels: dict[str, QLabel] = {}
        fields = [
            ("记录", "record"),
            ("F5/F6", "rate"),
            ("SLAM", "slam"),
            ("cur", "cur"),
            ("电压", "voltage"),
            ("模式/解锁", "mode"),
            ("状态", "state"),
            ("错误", "error"),
            ("外部传感", "sensor"),
            ("巡航", "route"),
        ]
        for i, (name, key) in enumerate(fields):
            row = i // 2
            col = (i % 2) * 2
            name_lbl = QLabel(name, status_box)
            name_lbl.setStyleSheet("color:#777;")
            value_lbl = QLabel("--", status_box)
            value_lbl.setStyleSheet("font-weight:bold;color:#333;")
            value_lbl.setWordWrap(True)
            value_lbl.setMaximumHeight(42)
            value_lbl.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            grid.addWidget(name_lbl, row, col)
            grid.addWidget(value_lbl, row, col + 1)
            self._labels[key] = value_lbl
        root.addWidget(status_box)

        body = QHBoxLayout()
        left = QVBoxLayout()
        left.setSpacing(8)

        record_box = QGroupBox("记录与导出", self)
        record_grid = QGridLayout(record_box)
        self._add_button(record_grid, "开始记录", self._start_recording, 0, 0)
        self._add_button(record_grid, "停止记录", self._stop_recording, 0, 1)
        btn_export = self._add_button(record_grid, "停止并导出CSV+报告", self._export_bundle, 1, 0, colspan=2)
        btn_export.setStyleSheet("font-weight:bold;color:#1565C0;")
        left.addWidget(record_box)

        prep_box = QGroupBox("飞前准备", self)
        prep_grid = QGridLayout(prep_box)
        self._add_button(prep_grid, "查询状态", lambda: self._send_f7(AUTO_CMD_QUERY_STATUS), 0, 0)
        self._add_button(prep_grid, "预检", lambda: self._send_f7(AUTO_CMD_PRECHECK), 0, 1)
        self._add_button(prep_grid, "请求定点", lambda: self._send_f7(AUTO_CMD_REQUEST_MODE2), 1, 0)
        self._add_button(prep_grid, "锁定遥控权", lambda: self._send_f7(AUTO_CMD_LOCK_RC), 1, 1)
        left.addWidget(prep_box)

        flight_box = QGroupBox("测试循环", self)
        flight = QVBoxLayout(flight_box)
        self._safety = QCheckBox("确认场地安全，允许自动起飞/巡航", flight_box)
        self._safety.setStyleSheet("color:#C62828;font-weight:bold;")
        flight.addWidget(self._safety)
        flight_grid = QGridLayout()
        btn_takeoff = self._add_button(
            flight_grid, "一键起飞保持", lambda: self._send_f7(AUTO_CMD_TAKEOFF_HOLD), 0, 0
        )
        btn_takeoff.setStyleSheet("font-weight:bold;color:#C62828;")
        btn_square = self._add_button(flight_grid, "正方形巡航", self._start_square_route, 0, 1)
        btn_square.setStyleSheet("font-weight:bold;color:#C62828;")
        btn_l = self._add_button(flight_grid, "L型巡航", self._start_l_route, 1, 0)
        btn_l.setStyleSheet("font-weight:bold;color:#C62828;")
        btn_t = self._add_button(flight_grid, "T型巡航", self._start_t_route, 1, 1)
        btn_t.setStyleSheet("font-weight:bold;color:#C62828;")
        btn_diag = self._add_button(flight_grid, "斜线巡航", self._start_diagonal_route, 2, 0)
        btn_diag.setStyleSheet("font-weight:bold;color:#C62828;")
        btn_stop = self._add_button(flight_grid, "停止巡航", self._stop_route, 2, 1)
        btn_stop.setStyleSheet("font-weight:bold;color:#EF6C00;")
        btn_land = self._add_button(flight_grid, "一键降落", lambda: self._send_f7(AUTO_CMD_LAND_ONLY), 3, 0)
        btn_land.setStyleSheet("font-weight:bold;color:#EF6C00;")
        btn_abort = self._add_button(flight_grid, "中止降落", lambda: self._send_f7(AUTO_CMD_ABORT_LAND), 3, 1)
        btn_abort.setStyleSheet("font-weight:bold;color:#EF6C00;")
        btn_lock = self._add_button(flight_grid, "强制上锁", lambda: self._send_f7(AUTO_CMD_EMERGENCY_LOCK), 4, 0, colspan=2)
        btn_lock.setStyleSheet("font-weight:bold;background:#C62828;color:white;")
        flight.addLayout(flight_grid)
        left.addWidget(flight_box)
        body.addLayout(left, 2)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        body.addWidget(sep)

        right = QVBoxLayout()
        params_box = QGroupBox("参数", self)
        form = QFormLayout(params_box)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._height = QSpinBox(params_box)
        self._height.setRange(30, 80)
        self._height.setValue(40)
        self._height.setSuffix(" cm")
        form.addRow("起飞高度", self._height)

        self._side = QDoubleSpinBox(params_box)
        self._side.setRange(20.0, 200.0)
        self._side.setDecimals(0)
        self._side.setSingleStep(10.0)
        self._side.setValue(50.0)
        self._side.setSuffix(" cm")
        form.addRow("轨迹距离", self._side)

        self._pause = QDoubleSpinBox(params_box)
        self._pause.setRange(0.2, 5.0)
        self._pause.setDecimals(1)
        self._pause.setSingleStep(0.1)
        self._pause.setValue(0.8)
        self._pause.setSuffix(" s")
        form.addRow("段间等待", self._pause)

        self._timeout = QDoubleSpinBox(params_box)
        self._timeout.setRange(5.0, 60.0)
        self._timeout.setDecimals(1)
        self._timeout.setSingleStep(1.0)
        self._timeout.setValue(30.0)
        self._timeout.setSuffix(" s")
        form.addRow("总超时", self._timeout)
        right.addWidget(params_box)

        hint = QLabel(
            "推荐循环：先运行树莓派导航和F5测试发送 → 开始记录 → 查询/预检/请求定点/锁定遥控权 → "
            "一键起飞保持 → 选择轨迹巡航 → 一键降落 → 停止并导出。"
            "轨迹定义：L型=X后Y；T型=X后Y左再Y右穿过中心；斜线=XY同时一段。"
            "本页仍只记录树莓派0xF5/STM32 0xF6，不接位置闭环。",
            self,
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#666;")
        hint.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        right.addWidget(hint)
        right.addStretch(1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        self._status = QLabel("等待连接串口", self)
        self._status.setStyleSheet("color:#777;font-weight:bold;")
        self._status.setWordWrap(True)
        self._status.setMaximumHeight(54)
        self._status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        root.addWidget(self._status)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        self._refresh_buttons()
        self._refresh_status()

    def _add_button(
        self,
        layout: QGridLayout,
        text: str,
        callback: Callable[[], None],
        row: int,
        col: int,
        *,
        colspan: int = 1,
    ) -> QPushButton:
        btn = QPushButton(text, self)
        btn.setMinimumHeight(32)
        btn.clicked.connect(lambda _checked=False: callback())
        layout.addWidget(btn, row, col, 1, colspan)
        self._buttons.append(btn)
        return btn

    def _refresh_buttons(self) -> None:
        enabled = bool(self._link_connected and self._send_command_fn is not None)
        for btn in self._buttons:
            if btn.text() in ("开始记录", "停止记录", "停止并导出CSV+报告"):
                btn.setEnabled(True)
            else:
                btn.setEnabled(enabled)

    def _start_recording(self) -> None:
        self._session.start_recording()
        self._set_status("已开始雷达会话记录", "#2E7D32")
        self._refresh_status()

    def _stop_recording(self) -> None:
        self._session.stop_recording()
        self._set_status("已停止雷达会话记录", "#1565C0")
        self._refresh_status()

    def _export_bundle(self) -> None:
        try:
            csv_path, report_path, rows = self._session.export_default_bundle(stop_first=True)
        except Exception as exc:
            QMessageBox.warning(self, "导出失败", str(exc))
            self._set_status("导出失败", "#C62828")
            return
        self._status.setToolTip(f"CSV: {csv_path}\n报告: {report_path}")
        self._set_status(
            f"已导出：CSV {rows}行；报告 {_short_path(report_path)}",
            "#1565C0",
        )
        self._refresh_status()

    def _send_f7(self, cmd: int) -> None:
        if self._send_command_fn is None or not self._link_connected:
            self._set_status("串口未连接，命令未发送", "#C62828")
            return
        if cmd == AUTO_CMD_TAKEOFF_HOLD and not self._safety.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "自动起飞前必须勾选场地安全确认。")
            self._set_status("起飞已拦截：未勾选安全确认", "#C62828")
            return
        if cmd in (AUTO_CMD_LAND_ONLY, AUTO_CMD_ABORT_LAND, AUTO_CMD_EMERGENCY_LOCK):
            self._cancel_route("巡航已取消：正在降落/中止/急停")
        if cmd == AUTO_CMD_TAKEOFF_HOLD and not self._session.is_recording():
            self._session.start_recording()
        params = {
            "seq": self._f7_seq,
            "cmd": int(cmd),
            "height_cm": int(self._height.value()),
            "hold_ms": 5000,
            "flags": AUTO_FLAG_NO_XY_MOTION,
            "timeout_ms": int(round(float(self._timeout.value()) * 1000.0)),
        }
        self._f7_seq = self._next_seq(self._f7_seq)
        self._send_command_fn(CMD_AUTO_MISSION, params)
        self._set_status(f"已发送 F7：{cmd_label(cmd)} seq={params['seq']}", "#B58900")

    def _emit_f9(
        self,
        cmd: int,
        x_cm: float,
        y_cm: float,
        z_cm: float,
        text: str,
        *,
        axis_mode: int = AUTO_MOVE_AXIS_AUTO,
    ) -> int:
        if self._send_command_fn is None or not self._link_connected:
            self._set_status("串口未连接，位移命令未发送", "#C62828")
            return 0
        seq = self._f9_seq
        params = {
            "seq": seq,
            "cmd": int(cmd),
            "x_cm": float(x_cm),
            "y_cm": float(y_cm),
            "z_cm": float(z_cm),
            "axis_mode": int(axis_mode),
            "flags": 0,
        }
        self._f9_seq = self._next_seq(self._f9_seq)
        self._send_command_fn(CMD_AUTO_MOVE, params)
        self._set_status(f"{text} seq={seq}", "#B58900")
        return seq

    def _start_square_route(self) -> None:
        side = float(self._side.value())
        self._start_route(
            "正方形",
            [(side, 0.0, 0.0), (0.0, side, 0.0), (-side, 0.0, 0.0), (0.0, -side, 0.0)],
        )

    def _start_l_route(self) -> None:
        side = float(self._side.value())
        self._start_route("L型", [(side, 0.0, 0.0), (0.0, side, 0.0)])

    def _start_t_route(self) -> None:
        side = float(self._side.value())
        self._start_route("T型", [(side, 0.0, 0.0), (0.0, side, 0.0), (0.0, -2.0 * side, 0.0)])

    def _start_diagonal_route(self) -> None:
        side = float(self._side.value())
        self._start_route("斜线", [(side, side, 0.0)], axis_mode=AUTO_MOVE_AXIS_XY)

    def _start_route(
        self,
        name: str,
        legs: list[tuple[float, float, float]],
        *,
        axis_mode: int = AUTO_MOVE_AXIS_AUTO,
    ) -> None:
        if not self._safety.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "开始巡航前必须勾选场地安全确认。")
            self._set_status("巡航已拦截：未勾选安全确认", "#C62828")
            return
        if self._route_active:
            self._set_status("巡航已经在执行中", "#EF6C00")
            return
        if not self._session.is_recording():
            self._session.start_recording()
        self._route_name = str(name)
        self._route_legs = list(legs)
        self._route_axis_mode = int(axis_mode)
        self._route_index = 0
        self._route_waiting_seq = None
        self._route_timer_pending = False
        self._route_active = True
        if not self._timer.isActive():
            self._timer.start()
        self._send_next_route_leg()

    def _stop_route(self) -> None:
        self._cancel_route("已停止巡航，并发送停止位移")
        self._emit_f9(AUTO_MOVE_CMD_STOP, 0.0, 0.0, 0.0, "已发送 F9：停止位移")

    def _send_next_route_leg(self) -> None:
        self._route_timer_pending = False
        if not self._route_active:
            return
        if self._route_index >= len(self._route_legs):
            self._route_active = False
            self._route_waiting_seq = None
            self._set_status(f"{self._route_name or '巡航'}完成：最后一段已到位保持", "#2E7D32")
            self._refresh_status()
            return
        x_cm, y_cm, z_cm = self._route_legs[self._route_index]
        leg_no = self._route_index + 1
        total = len(self._route_legs)
        seq = self._emit_f9(
            AUTO_MOVE_CMD_START,
            x_cm,
            y_cm,
            z_cm,
            f"{self._route_name or '巡航'}第{leg_no}/{total}段 X={x_cm:.0f} Y={y_cm:.0f}",
            axis_mode=self._route_axis_mode,
        )
        if seq == 0:
            self._route_active = False
            return
        self._route_waiting_seq = seq
        self._route_index += 1
        self._refresh_status()

    def _advance_route_on_status(self, sample: AutoMissionStatusSample) -> None:
        if not self._route_active or self._route_waiting_seq is None:
            return
        if sample.error != 0:
            self._cancel_route(f"巡航中止：{error_label(sample.error)}")
            return
        if sample.last_cmd != CMD_AUTO_MOVE or sample.last_cmd_seq != self._route_waiting_seq:
            return
        if sample.state != _AUTO_STATE_MOVE_HOLD or self._route_timer_pending:
            return
        if self._route_index >= len(self._route_legs):
            self._route_active = False
            self._route_waiting_seq = None
            self._set_status(f"{self._route_name or '巡航'}完成：最后一段已到位", "#2E7D32")
            self._refresh_status()
            return
        self._route_timer_pending = True
        pause_ms = int(round(float(self._pause.value()) * 1000.0))
        self._set_status(
            f"{self._route_name or '巡航'}第{self._route_index}/{len(self._route_legs)}段到位，"
            f"{float(self._pause.value()):.1f}s后下一段",
            "#2E7D32",
        )
        QTimer.singleShot(pause_ms, self._send_next_route_leg)

    def _cancel_route(self, text: str) -> None:
        if not self._route_active and self._route_waiting_seq is None:
            return
        self._route_active = False
        self._route_timer_pending = False
        self._route_waiting_seq = None
        self._set_status(text, "#EF6C00")
        self._refresh_status()

    def _update_f8_labels(self, sample: AutoMissionStatusSample) -> None:
        self._set_label("voltage", f"{sample.voltage_v:.2f} V", "#2E7D32" if sample.voltage_v >= 14.0 else "#C62828")
        self._set_label("mode", f"Mode{sample.mode} / {'已解锁' if sample.unlock else '已上锁'}", "#2E7D32" if sample.mode == 2 else "#EF6C00")
        self._set_label("state", state_label(sample.state), "#2E7D32" if sample.error == 0 else "#C62828")
        self._set_label("error", error_label(sample.error), "#2E7D32" if sample.error == 0 else "#C62828")
        sensor_ok = sample.ext_vel_ok and sample.ext_alt_ok
        self._set_label("sensor", f"外速{'OK' if sample.ext_vel_ok else '无效'} / 测高{'OK' if sample.ext_alt_ok else '无效'} / F5 {sample.f5_age_ms}ms",
                        "#2E7D32" if sensor_ok else "#C62828")

    def _refresh_status(self) -> None:
        self._set_label("record", self._session.counts_text(), "#2E7D32" if self._session.is_recording() else "#555")
        self._set_label("route", self._route_text(), "#B58900" if self._route_active else "#555")
        samples = list(self._f6_recent)
        if len(samples) >= 2:
            f6_rate = _StabilityPage._sample_rate(samples)
            f5_rate = _StabilityPage._f5_input_rate(samples)
            self._set_label("rate", f"F5 {f5_rate:.1f}Hz / F6 {f6_rate:.1f}Hz", "#2E7D32")
        else:
            self._set_label("rate", "--", "#555")
        sample = self._last_f6
        if sample is None:
            self._set_label("slam", "等待0xF6", "#EF6C00")
            self._set_label("cur", "--", "#555")
        elif self._valid_cur(sample):
            self._set_label("slam", "有效", "#2E7D32")
            self._set_label("cur", f"X={sample.cur_x_cm} Y={sample.cur_y_cm} Z={sample.cur_z_cm} cm", "#2E7D32")
        else:
            self._set_label("slam", f"无效 flags=0x{sample.flags:02X}", "#C62828")
            self._set_label("cur", "--", "#C62828")
        if self._last_f8 is None:
            self._set_label("voltage", "--", "#555")
            self._set_label("mode", "--", "#555")
            self._set_label("state", "--", "#555")
            self._set_label("error", "--", "#555")
            self._set_label("sensor", "--", "#555")

    def _route_text(self) -> str:
        if self._route_active:
            current = min(self._route_index + (0 if self._route_waiting_seq is None else 0), len(self._route_legs))
            prefix = f"{self._route_name} " if self._route_name else ""
            return f"{prefix}执行中 {current}/{len(self._route_legs)} 等待seq={self._route_waiting_seq}"
        return "未巡航"

    def _set_label(self, key: str, text: str, color: str) -> None:
        label = self._labels.get(key)
        if label is None:
            return
        label.setText(text)
        label.setStyleSheet(f"font-weight:bold;color:{color};")

    def _set_status(self, text: str, color: str) -> None:
        if not text.startswith("已导出"):
            self._status.setToolTip(text)
        self._status.setText(text)
        self._status.setStyleSheet(f"color:{color};font-weight:bold;")

    @staticmethod
    def _valid_cur(sample: RpiPositionMirrorSample) -> bool:
        return (
            sample.slam_valid
            and sample.cur_x_cm != _INVALID_S32
            and sample.cur_y_cm != _INVALID_S32
            and sample.cur_z_cm != _INVALID_S32
        )

    @staticmethod
    def _next_seq(seq: int) -> int:
        seq = (int(seq) + 1) & 0xFFFF
        return 1 if seq == 0 else seq


class PositionTestWindow(QWidget):
    """主菜单中的独立“位置测试”页面。"""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        send_command_fn: Optional[Callable[[int, dict], None]] = None,
    ) -> None:
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
        self._session = _SessionRecorderPage(self)
        self._workflow = _RadarWorkflowPage(self._session, send_command_fn, self)
        self._tabs.addTab(self._workflow, "雷达联调")
        self._tabs.addTab(self._realtime, "实时数据")
        self._tabs.addTab(self._calibration, "坐标标定")
        self._tabs.addTab(self._stability, "稳定性")
        self._tabs.addTab(self._trajectory, "轨迹回放")
        self._tabs.addTab(self._session, "雷达报告")
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
        self._workflow.set_link_connected(connected)
        if self._active:
            self._status.setText(
                "位置测试：串口已连接，接收 0xF6 镜像帧"
                if connected else "位置测试：请先连接数传串口"
            )

    def show_workflow(self) -> None:
        self._tabs.setCurrentWidget(self._workflow)
        self._sync_page_activity()

    def _sync_page_activity(self) -> None:
        active = bool(self._active)
        self._workflow.set_active(active and self._tabs.currentWidget() is self._workflow)
        self._realtime.set_active(active)
        self._calibration.set_active(active and self._tabs.currentWidget() is self._calibration)
        self._stability.set_active(active and self._tabs.currentWidget() is self._stability)
        self._trajectory.set_active(active and self._tabs.currentWidget() is self._trajectory)
        self._session.set_active(active and self._tabs.currentWidget() is self._session)

    def on_command_sent(self, cmd_id: int, params: dict, desc: str, *, silent: bool = False) -> None:
        """记录 GUI 已实际发出的自主命令事件，供雷达质量会话对齐使用。"""
        self._session.on_command_sent(cmd_id, params, desc, silent=silent)

    @Slot(object)
    def on_frame(self, frame: object) -> None:
        if not self._active and not self._session.is_recording() and not self._workflow.is_route_active():
            return
        cmd = getattr(frame, "cmd", None)
        if cmd is None:
            return
        cmd = int(cmd) & 0xFF
        if self._active:
            self._realtime.on_any_frame(cmd)

        data = getattr(frame, "data", None)
        if data is None:
            return

        if cmd == CMD_AUTO_STATUS:
            status = decode_auto_mission_status(bytes(data))
            if status is not None:
                self._session.on_auto_status(status)
                self._workflow.on_auto_status(status)
            return

        if cmd != CMD_RPI_POSITION_MIRROR:
            return

        sample = decode_rpi_position_mirror(bytes(data))
        if sample is not None:
            self._session.on_sample(sample)
            self._workflow.on_sample(sample)
            if self._active:
                self._realtime.on_sample(sample)
                self._calibration.on_sample(sample)
                self._stability.on_sample(sample)
                self._trajectory.on_sample(sample)
