# -*- coding: utf-8 -*-
"""静态校准面板（Phase 4）。

对照 gui/imu测试要求.md：
- 加速度尺度校准：Z 轴朝上静置采样 → 实测 |a|/acc_z 应为 9.8；据此修正 acc_scale
- 陀螺零偏校准：静置采样三轴角速度均值 = 零偏（目标 ±0.005 rad/s）
- 90° 积分自检：手动转 90°，积分 ∫gyr_z 应 = 90°±2°（验证 gyr_scale）

产出：一键复制可粘贴的 yaml 片段（不自动写远端配置）。
数据来源：ImuDataHub.imu_raw（ImuRawSample）。
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.data_hub import DEFAULT_ACC_SCALE, DEFAULT_GYR_SCALE
from gui.imu_test.logger import get_logger

_G = 9.80665            # 标准重力 m/s²
_GYR_BIAS_TOL = 0.005   # 零偏达标阈值 rad/s
_INTEG_TARGET = 90.0    # 90° 积分目标
_INTEG_TOL = 2.0        # 积分允差 °

_VAL = "color:#4FC3F7; font-weight:bold;"
_OK = "color:#4CAF50; font-weight:bold;"
_BAD = "color:#FFB300; font-weight:bold;"


class CalibrationPanel(QWidget):
    """加速度尺度 / 陀螺零偏 / 90°积分自检。"""

    def __init__(self, data_hub=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._hub = data_hub
        self._acc_scale = data_hub.acc_scale if data_hub else DEFAULT_ACC_SCALE
        self._gyr_scale = data_hub.gyr_scale if data_hub else DEFAULT_GYR_SCALE

        # 采样状态
        self._acc_on = False
        self._acc_ax: list[float] = []
        self._acc_ay: list[float] = []
        self._acc_az: list[float] = []
        self._gyr_on = False
        self._gyr_gx: list[float] = []
        self._gyr_gy: list[float] = []
        self._gyr_gz: list[float] = []
        # 积分自检
        self._integ_on = False
        self._integ_deg = 0.0
        self._integ_last_ts: float | None = None
        self._last: object | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(10)
        root.addWidget(self._build_acc_group())
        root.addWidget(self._build_gyr_group())
        root.addStretch(1)

        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---- 加速度尺度校准 ----
    def _build_acc_group(self) -> QGroupBox:
        box = QGroupBox("加速度尺度校准（设备水平静置，Z 轴朝上）", self)
        g = QGridLayout(box)
        self._acc_btn = QPushButton("开始采样", box)
        self._acc_btn.clicked.connect(self._toggle_acc)
        g.addWidget(self._acc_btn, 0, 0)
        self._acc_n = QLabel("采样 0", box)
        g.addWidget(self._acc_n, 0, 1)

        g.addWidget(QLabel("实测 |a|：", box), 1, 0)
        self._acc_norm = QLabel("--", box); self._acc_norm.setStyleSheet(_VAL)
        g.addWidget(self._acc_norm, 1, 1)
        g.addWidget(QLabel("实测 acc_z：", box), 1, 2)
        self._acc_z = QLabel("--", box); self._acc_z.setStyleSheet(_VAL)
        g.addWidget(self._acc_z, 1, 3)

        g.addWidget(QLabel("当前 acc_scale：", box), 2, 0)
        self._acc_cur = QLabel(f"{self._acc_scale:.6f}", box); self._acc_cur.setStyleSheet(_VAL)
        g.addWidget(self._acc_cur, 2, 1)
        g.addWidget(QLabel("建议 acc_scale：", box), 2, 2)
        self._acc_new = QLabel("--", box); self._acc_new.setStyleSheet(_OK)
        g.addWidget(self._acc_new, 2, 3)

        self._acc_yaml = QPlainTextEdit(box)
        self._acc_yaml.setReadOnly(True)
        self._acc_yaml.setFixedHeight(72)
        self._acc_yaml.setPlaceholderText("采样结束后生成 yaml 片段…")
        g.addWidget(self._acc_yaml, 3, 0, 1, 4)
        row = QHBoxLayout()
        self._acc_copy = QPushButton("复制 yaml 片段", box)
        self._acc_copy.clicked.connect(lambda: self._copy(self._acc_yaml))
        row.addStretch(1); row.addWidget(self._acc_copy)
        g.addLayout(row, 4, 0, 1, 4)
        return box

    def _toggle_acc(self) -> None:
        self._acc_on = not self._acc_on
        if self._acc_on:
            self._acc_ax.clear(); self._acc_ay.clear(); self._acc_az.clear()
            self._acc_btn.setText("停止采样")
            self._acc_yaml.setPlainText("")
        else:
            self._acc_btn.setText("开始采样")
            self._finish_acc()

    def _finish_acc(self) -> None:
        if not self._acc_az:
            return
        mz = sum(self._acc_az) / len(self._acc_az)
        if abs(mz) < 1e-6:
            return
        new_scale = self._acc_scale * _G / mz
        self._acc_new.setText(f"{new_scale:.6f}")
        self._acc_yaml.setPlainText(
            "# 加速度尺度校准（Z轴朝上静置）\n"
            f"# 实测 acc_z = {mz:.3f} m/s²（目标 {_G:.3f}）\n"
            "imu:\n"
            f"  acc_scale: {new_scale:.6f}"
        )
        self._log.info("acc 校准完成：mz=%.3f new_scale=%.6f", mz, new_scale)

    # ---- 陀螺零偏 + 90°积分 ----
    def _build_gyr_group(self) -> QGroupBox:
        box = QGroupBox("陀螺零偏校准 + 90° 积分自检", self)
        g = QGridLayout(box)

        # 零偏
        self._gyr_btn = QPushButton("开始静置采样", box)
        self._gyr_btn.clicked.connect(self._toggle_gyr)
        g.addWidget(self._gyr_btn, 0, 0)
        self._gyr_n = QLabel("采样 0", box)
        g.addWidget(self._gyr_n, 0, 1)
        g.addWidget(QLabel("零偏 X/Y/Z (rad/s)：", box), 1, 0)
        self._gyr_bias = QLabel("--", box); self._gyr_bias.setStyleSheet(_VAL)
        g.addWidget(self._gyr_bias, 1, 1, 1, 2)
        self._gyr_ok = QLabel("", box)
        g.addWidget(self._gyr_ok, 1, 3)

        # 90° 积分自检
        self._integ_btn = QPushButton("开始积分（手动转 90°）", box)
        self._integ_btn.clicked.connect(self._toggle_integ)
        g.addWidget(self._integ_btn, 2, 0)
        g.addWidget(QLabel("积分角度：", box), 2, 1)
        self._integ_lbl = QLabel("0.0°", box); self._integ_lbl.setStyleSheet(_VAL)
        g.addWidget(self._integ_lbl, 2, 2)
        self._integ_res = QLabel("", box)
        g.addWidget(self._integ_res, 2, 3)

        self._gyr_yaml = QPlainTextEdit(box)
        self._gyr_yaml.setReadOnly(True)
        self._gyr_yaml.setFixedHeight(72)
        self._gyr_yaml.setPlaceholderText("零偏采样结束后生成 yaml 片段…")
        g.addWidget(self._gyr_yaml, 3, 0, 1, 4)
        row = QHBoxLayout()
        self._gyr_copy = QPushButton("复制 yaml 片段", box)
        self._gyr_copy.clicked.connect(lambda: self._copy(self._gyr_yaml))
        row.addStretch(1); row.addWidget(self._gyr_copy)
        g.addLayout(row, 4, 0, 1, 4)
        return box

    def _toggle_gyr(self) -> None:
        self._gyr_on = not self._gyr_on
        if self._gyr_on:
            self._gyr_gx.clear(); self._gyr_gy.clear(); self._gyr_gz.clear()
            self._gyr_btn.setText("停止静置采样")
            self._gyr_yaml.setPlainText("")
        else:
            self._gyr_btn.setText("开始静置采样")
            self._finish_gyr()

    def _finish_gyr(self) -> None:
        if not self._gyr_gx:
            return
        bx = sum(self._gyr_gx) / len(self._gyr_gx)
        by = sum(self._gyr_gy) / len(self._gyr_gy)
        bz = sum(self._gyr_gz) / len(self._gyr_gz)
        self._gyr_yaml.setPlainText(
            "# 陀螺零偏校准（静置）\n"
            "imu:\n"
            f"  gyr_offset: [{bx:.6f}, {by:.6f}, {bz:.6f}]  # rad/s"
        )
        self._log.info("gyr 零偏完成：[%.6f, %.6f, %.6f]", bx, by, bz)

    def _toggle_integ(self) -> None:
        self._integ_on = not self._integ_on
        if self._integ_on:
            self._integ_deg = 0.0
            self._integ_last_ts = None
            self._integ_btn.setText("停止积分")
            self._integ_res.setText("")
        else:
            self._integ_btn.setText("开始积分（手动转 90°）")
            a = abs(self._integ_deg)
            if abs(a - _INTEG_TARGET) <= _INTEG_TOL:
                self._integ_res.setText(f"✓ {a:.1f}° 达标"); self._integ_res.setStyleSheet(_OK)
            else:
                self._integ_res.setText(f"✗ {a:.1f}° 偏差{a-_INTEG_TARGET:+.1f}°"); self._integ_res.setStyleSheet(_BAD)

    # ---- 数据入口 ----
    @Slot(object)
    def on_imu_raw(self, s: object) -> None:
        self._last = s
        if self._acc_on:
            self._acc_ax.append(s.acc_x); self._acc_ay.append(s.acc_y); self._acc_az.append(s.acc_z)
        if self._gyr_on:
            self._gyr_gx.append(s.gyr_x); self._gyr_gy.append(s.gyr_y); self._gyr_gz.append(s.gyr_z)
        if self._integ_on:
            if self._integ_last_ts is not None:
                dt = s.ts - self._integ_last_ts
                if 0 < dt < 0.5:
                    self._integ_deg += math.degrees(s.gyr_z) * dt
            self._integ_last_ts = s.ts

    def clear(self) -> None:
        self._last = None

    # ---- 刷新 ----
    def _refresh(self) -> None:
        if self._acc_on and self._acc_az:
            n = len(self._acc_az)
            mx = sum(self._acc_ax) / n; my = sum(self._acc_ay) / n; mz = sum(self._acc_az) / n
            self._acc_n.setText(f"采样 {n}")
            self._acc_norm.setText(f"{math.sqrt(mx*mx+my*my+mz*mz):.3f} m/s²")
            self._acc_z.setText(f"{mz:.3f} m/s²")
        if self._gyr_on and self._gyr_gx:
            n = len(self._gyr_gx)
            bx = sum(self._gyr_gx) / n; by = sum(self._gyr_gy) / n; bz = sum(self._gyr_gz) / n
            self._gyr_n.setText(f"采样 {n}")
            self._gyr_bias.setText(f"{bx:+.5f} / {by:+.5f} / {bz:+.5f}")
            ok = max(abs(bx), abs(by), abs(bz)) <= _GYR_BIAS_TOL
            self._gyr_ok.setText("✓ 达标" if ok else "✗ 超阈")
            self._gyr_ok.setStyleSheet(_OK if ok else _BAD)
        if self._integ_on:
            self._integ_lbl.setText(f"{self._integ_deg:.1f}°")

    def _copy(self, edit: QPlainTextEdit) -> None:
        txt = edit.toPlainText().strip()
        if txt:
            QGuiApplication.clipboard().setText(txt)
            self._log.info("yaml 片段已复制到剪贴板")
