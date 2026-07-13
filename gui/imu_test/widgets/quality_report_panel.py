# -*- coding: utf-8 -*-
"""质量报告面板（Phase 5）。

一键采集一段数据后，对照 gui/imu测试要求.md 逐项检查，输出清单表：
[检查项 / 实测值 / 判据 / 结果]，并给出整体 通过/不通过 结论。

检查项覆盖：
- 数据完整性：无 NaN/Inf（acc/gyr/euler）
- 采样频率：IMU(0x01) / 姿态(0x04) ≥ 50Hz
- 量程合理：|acc| ≤ 156.8 m/s²，|gyr| ≤ 34.9 rad/s
- 静态噪声：acc 三轴 std < 0.05；gyr 三轴 std < 0.01
- 四元数模长：0.999 ~ 1.001
- 姿态静态漂移：roll/pitch std < 2°，yaw std < 3°
- 姿态无跳变：相邻帧 |Δ| < 5°

数据来源：ImuDataHub.imu_raw / attitude / quat_norm。
说明：静态类判据须在设备静止时采集才有意义（运动时会“不通过”属正常）。
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.logger import get_logger

# 判据阈值
_ACC_RANGE = 156.8
_GYR_RANGE = 34.9
_ACC_NOISE = 0.05
_GYR_NOISE = 0.01
_QNORM_LO, _QNORM_HI = 0.999, 1.001
_RP_DRIFT = 2.0
_YAW_DRIFT = 3.0
_JUMP = 5.0
_FREQ_MIN = 50.0

_ITEMS = [
    "数据完整性（无 NaN/Inf）",
    "IMU 采样频率 ≥ 50Hz",
    "姿态采样频率 ≥ 50Hz",
    "加速度量程 ≤ 156.8 m/s²",
    "角速度量程 ≤ 34.9 rad/s",
    "加速度静态噪声 std < 0.05",
    "角速度静态噪声 std < 0.01",
    "四元数模长 0.999~1.001",
    "姿态静态漂移 R/P<2° Y<3°",
    "姿态无跳变（相邻 <5°）",
]

_GREEN = "#4CAF50"
_RED = "#EF5350"
_GRAY = "#9E9E9E"


def _std(xs: list[float]) -> float:
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / n)


def _finite(xs: list[float]) -> bool:
    return all(math.isfinite(x) for x in xs)


class QualityReportPanel(QWidget):
    """一键质检 + 清单表。"""

    def __init__(self, data_hub=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._hub = data_hub
        self._collecting = False
        self._reset_buffers()

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        bar = QHBoxLayout()
        self._btn = QPushButton("开始检测", self)
        self._btn.clicked.connect(self._toggle)
        bar.addWidget(self._btn)
        self._hint = QLabel("采集一段数据后自动评估（静态项须设备静止）", self)
        self._hint.setStyleSheet("color:#999;")
        bar.addWidget(self._hint)
        bar.addStretch(1)
        self._verdict = QLabel("—", self)
        self._verdict.setStyleSheet("font-size:15px; font-weight:bold; color:#9E9E9E;")
        bar.addWidget(self._verdict)
        root.addLayout(bar)

        self._table = QTableWidget(len(_ITEMS), 4, self)
        self._table.setHorizontalHeaderLabels(["检查项", "实测值", "判据", "结果"])
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        self._table.setStyleSheet(
            "QTableWidget { background:#232323; color:#DCDCDC; gridline-color:#3a3a3a; }"
            "QHeaderView::section { background:#333; color:#DCDCDC; padding:4px; border:0; }"
        )
        for r, name in enumerate(_ITEMS):
            self._table.setItem(r, 0, QTableWidgetItem(name))
            for c in (1, 2, 3):
                self._table.setItem(r, c, QTableWidgetItem("—"))
        root.addWidget(self._table, 1)

    def _reset_buffers(self) -> None:
        self._ax: list[float] = []; self._ay: list[float] = []; self._az: list[float] = []
        self._gx: list[float] = []; self._gy: list[float] = []; self._gz: list[float] = []
        self._imu_ts: list[float] = []
        self._roll: list[float] = []; self._pitch: list[float] = []; self._yaw: list[float] = []
        self._att_ts: list[float] = []
        self._qnorm: list[float] = []

    # ---- 数据入口 ----
    @Slot(object)
    def on_imu_raw(self, s: object) -> None:
        if not self._collecting:
            return
        self._ax.append(s.acc_x); self._ay.append(s.acc_y); self._az.append(s.acc_z)
        self._gx.append(s.gyr_x); self._gy.append(s.gyr_y); self._gz.append(s.gyr_z)
        self._imu_ts.append(s.ts)

    @Slot(object)
    def on_attitude(self, s: object) -> None:
        if not self._collecting:
            return
        self._roll.append(s.roll_deg); self._pitch.append(s.pitch_deg); self._yaw.append(s.yaw_deg)
        self._att_ts.append(s.ts)

    @Slot(float)
    def on_quat_norm(self, norm: float) -> None:
        if self._collecting:
            self._qnorm.append(norm)

    def clear(self) -> None:
        self._reset_buffers()

    # ---- 检测流程 ----
    def _toggle(self) -> None:
        self._collecting = not self._collecting
        if self._collecting:
            self._reset_buffers()
            self._btn.setText("停止并评估")
            self._verdict.setText("采集中…")
            self._verdict.setStyleSheet("font-size:15px; font-weight:bold; color:#4FC3F7;")
        else:
            self._btn.setText("开始检测")
            self._evaluate()

    @staticmethod
    def _freq(ts: list[float]) -> float:
        if len(ts) < 2:
            return 0.0
        span = ts[-1] - ts[0]
        return (len(ts) - 1) / span if span > 0 else 0.0

    def _evaluate(self) -> None:
        rows = []  # (值str, 判据str, pass/None)
        acc_all = self._ax + self._ay + self._az
        gyr_all = self._gx + self._gy + self._gz
        euler_all = self._roll + self._pitch + self._yaw

        # 1 完整性
        if not (acc_all or gyr_all or euler_all):
            rows.append(("无数据", "有数据", None))
        else:
            ok = _finite(acc_all) and _finite(gyr_all) and _finite(euler_all)
            rows.append(("有 NaN/Inf" if not ok else "全部有限", "无 NaN/Inf", ok))

        # 2 IMU 频率
        f = self._freq(self._imu_ts)
        rows.append((f"{f:.1f} Hz", "≥ 50Hz", f >= _FREQ_MIN if self._imu_ts else None))
        # 3 姿态频率
        fa = self._freq(self._att_ts)
        rows.append((f"{fa:.1f} Hz", "≥ 50Hz", fa >= _FREQ_MIN if self._att_ts else None))

        # 4 acc 量程
        if acc_all:
            amax = max(abs(v) for v in acc_all)
            rows.append((f"max|acc|={amax:.1f}", "≤ 156.8", amax <= _ACC_RANGE))
        else:
            rows.append(("—", "≤ 156.8", None))
        # 5 gyr 量程
        if gyr_all:
            gmax = max(abs(v) for v in gyr_all)
            rows.append((f"max|gyr|={gmax:.2f}", "≤ 34.9", gmax <= _GYR_RANGE))
        else:
            rows.append(("—", "≤ 34.9", None))

        # 6 acc 噪声
        if len(self._az) >= 2:
            an = max(_std(self._ax), _std(self._ay), _std(self._az))
            rows.append((f"std={an:.4f}", "< 0.05", an < _ACC_NOISE))
        else:
            rows.append(("—", "< 0.05", None))
        # 7 gyr 噪声
        if len(self._gz) >= 2:
            gn = max(_std(self._gx), _std(self._gy), _std(self._gz))
            rows.append((f"std={gn:.4f}", "< 0.01", gn < _GYR_NOISE))
        else:
            rows.append(("—", "< 0.01", None))

        # 8 四元数模长
        if self._qnorm:
            lo, hi = min(self._qnorm), max(self._qnorm)
            ok = lo >= _QNORM_LO and hi <= _QNORM_HI
            rows.append((f"[{lo:.4f}, {hi:.4f}]", "0.999~1.001", ok))
        else:
            rows.append(("—", "0.999~1.001", None))

        # 9 姿态漂移
        if len(self._roll) >= 2:
            sr, sp, sy = _std(self._roll), _std(self._pitch), _std(self._yaw)
            ok = sr < _RP_DRIFT and sp < _RP_DRIFT and sy < _YAW_DRIFT
            rows.append((f"R{sr:.2f} P{sp:.2f} Y{sy:.2f}", "R/P<2 Y<3", ok))
        else:
            rows.append(("—", "R/P<2 Y<3", None))

        # 10 姿态跳变
        if len(self._roll) >= 2:
            jmp = 0.0
            for seq in (self._roll, self._pitch, self._yaw):
                for i in range(1, len(seq)):
                    d = abs(seq[i] - seq[i - 1])
                    if d > 180:
                        d = 360 - d  # 处理 yaw 环绕
                    jmp = max(jmp, d)
            rows.append((f"max Δ={jmp:.2f}°", "< 5°", jmp < _JUMP))
        else:
            rows.append(("—", "< 5°", None))

        # 写表 + 统计
        passed = failed = 0
        for r, (val, crit, ok) in enumerate(rows):
            self._table.item(r, 1).setText(val)
            self._table.item(r, 2).setText(crit)
            res = self._table.item(r, 3)
            if ok is None:
                res.setText("跳过"); res.setForeground(QColor(_GRAY))
            elif ok:
                res.setText("✓ 通过"); res.setForeground(QColor(_GREEN)); passed += 1
            else:
                res.setText("✗ 不通过"); res.setForeground(QColor(_RED)); failed += 1

        if failed == 0 and passed > 0:
            self._verdict.setText(f"✓ 全部通过（{passed}）")
            self._verdict.setStyleSheet(f"font-size:15px; font-weight:bold; color:{_GREEN};")
        else:
            self._verdict.setText(f"✗ {failed} 项不通过 / {passed} 通过")
            self._verdict.setStyleSheet(f"font-size:15px; font-weight:bold; color:{_RED};")
        self._log.info("质检完成：通过 %d，不通过 %d", passed, failed)
