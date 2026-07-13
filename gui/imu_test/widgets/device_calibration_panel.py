# -*- coding: utf-8 -*-
"""设备校准面板 —— 触发凌霄 IMU 内置硬件校准。

与「静态校准」Tab 区别：
- 静态校准：软件侧采样计算 acc_scale / gyr 零偏（给 ROS yaml 用），不改 IMU。
- 设备校准（本面板）：向凌霄 IMU 发 0xE0 命令，触发 IMU **内置**校准
  （陀螺仪 / 快速水平 / 磁力计 / 6面加速度），IMU 执行并通过 0xA0 字符串帧
  回传过程提示，效果等同匿名上位机的校准流程。

数据路径：面板 → send_fn → 串口 → 数传 → 凌霄IMU（执行）→ 0xA0 回传 → on_log_text。
"""
from __future__ import annotations

import html as _html
from datetime import datetime
from typing import Callable, Optional

from PySide6.QtCore import Qt, Slot
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from gui.imu_test.calibration_cmd import CALIBRATIONS, CalibrationDef, build_cal_frame
from gui.imu_test.logger import get_logger

# 0xA0 颜色码 → 终端显示色
_COLOR_HEX = {0: "#E0E0E0", 1: "#FF6B6B", 2: "#6BCB77"}

# 终端（QTextEdit）暗色样式，沿用现有 log_view 面板配色
_TERM_QSS = (
    "QTextEdit { background-color: #1E1E1E; color: #E0E0E0; }"
    "QScrollBar:vertical { background: #2A2A2A; width: 14px; margin: 16px 0 16px 0; }"
    "QScrollBar::handle:vertical { background: #5A5A5A; min-height: 30px; border-radius: 5px; }"
    "QScrollBar::handle:vertical:hover { background: #7A7A7A; }"
    "QScrollBar::handle:vertical:pressed { background: #9A9A9A; }"
    "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
    " background: #3A3A3A; height: 14px; subcontrol-origin: margin; }"
    "QScrollBar::add-line:vertical { subcontrol-position: bottom; }"
    "QScrollBar::sub-line:vertical { subcontrol-position: top; }"
    "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
)


class DeviceCalibrationPanel(QWidget):
    """凌霄 IMU 硬件校准面板（4 个校准按钮 + 终端 log）。

    :param send_fn: 发送整帧的回调 ``send_fn(frame: bytes) -> bool``，
                    返回 True 表示已入队发送，False 表示未连接/被拒。
                    为 None 时按钮禁用（仅展示）。
    """

    def __init__(
        self,
        send_fn: Optional[Callable[[bytes], bool]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._send_fn = send_fn
        self._buttons: dict[str, QPushButton] = {}
        self._build_ui()

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        # 安全提示条
        warn = QLabel(
            "⚠ 校准前请拆掉螺旋桨或确保飞机安全放置；校准指令直接发送给凌霄 IMU 执行。"
        )
        warn.setWordWrap(True)
        warn.setStyleSheet(
            "QLabel { background:#3A2A00; color:#FFC107; border:1px solid #6A4A00;"
            " border-radius:4px; padding:6px 8px; }"
        )
        root.addWidget(warn)

        # 主体：左=校准按钮+说明，右=终端 log
        body = QHBoxLayout()
        body.setSpacing(10)

        # ---- 左列：4 个校准 ----
        left = QVBoxLayout()
        left.setSpacing(8)
        for cal in CALIBRATIONS:
            left.addWidget(self._make_cal_group(cal))
        left.addStretch(1)
        clear_btn = QPushButton("清屏")
        clear_btn.setToolTip("仅清除终端显示")
        clear_btn.clicked.connect(lambda: self._term.clear())
        left.addWidget(clear_btn)

        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(320)
        body.addWidget(left_w)

        # ---- 右列：终端 log ----
        right = QVBoxLayout()
        right.setSpacing(2)
        right.addWidget(QLabel("校准过程提示（凌霄 IMU 通过 0xA0 回传）："))
        self._term = QTextEdit()
        self._term.setReadOnly(True)
        self._term.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(10)
        self._term.setFont(f)
        self._term.setStyleSheet(_TERM_QSS)
        right.addWidget(self._term, 1)
        body.addLayout(right, 1)

        root.addLayout(body, 1)

        self._append(
            0,
            "— 设备校准终端就绪 —  点击左侧按钮触发对应校准，IMU 的实时提示会显示在这里。",
        )

    def _make_cal_group(self, cal: CalibrationDef) -> QGroupBox:
        box = QGroupBox(cal.name)
        box.setStyleSheet("QGroupBox { font-weight: bold; }")
        lay = QVBoxLayout(box)
        lay.setSpacing(4)
        lay.setContentsMargins(8, 6, 8, 8)

        tip = QLabel(cal.steps)
        tip.setWordWrap(True)
        tip.setStyleSheet("QLabel { color:#AAAAAA; font-weight:normal; font-size:12px; }")
        lay.addWidget(tip)

        btn = QPushButton(f"开始{cal.name}")
        btn.setEnabled(self._send_fn is not None)
        btn.clicked.connect(lambda _=False, c=cal: self._on_click(c))
        self._buttons[cal.key] = btn
        lay.addWidget(btn)
        return box

    # ---- 交互 ----
    def _on_click(self, cal: CalibrationDef) -> None:
        if self._send_fn is None:
            return
        # 二次确认（安全 + 展示原理）
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle(f"确认{cal.name}")
        msg.setText(f"即将向凌霄 IMU 发送「{cal.name}」命令。")
        msg.setInformativeText(
            f"原理：{cal.principle}\n\n操作：{cal.steps}\n\n确认继续？"
        )
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        msg.button(QMessageBox.StandardButton.Yes).setText("发送校准")
        msg.button(QMessageBox.StandardButton.No).setText("取消")
        if msg.exec() != QMessageBox.StandardButton.Yes:
            self._append(0, f"已取消：{cal.name}")
            return

        frame = build_cal_frame(cal)
        hex_str = " ".join(f"{b:02X}" for b in frame)
        ok = False
        try:
            ok = bool(self._send_fn(frame))
        except Exception as exc:  # noqa: BLE001
            self._log.warning("发送校准帧异常：%r", exc)
            self._append(1, f"{cal.name} 发送失败：{exc}")
            return
        if ok:
            self._append(2, f"已发送 {cal.name} 命令  [{hex_str}]")
            self._append(0, "等待凌霄 IMU 回传提示……")
            self._log.info("发送校准命令 %s：%s", cal.name, hex_str)
        else:
            self._append(1, f"{cal.name} 未发送：串口未连接")

    # ---- 接收：0xA0 字符串（凌霄 IMU 校准提示） ----
    @Slot(int, str)
    def on_log_text(self, color: int, text: str) -> None:
        """由 ImuDataHub.log_text 信号驱动，显示 IMU 的 0xA0 提示。"""
        self._append(color, text)

    # ---- 内部：终端追加一行 ----
    def _append(self, color: int, text: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        hexcolor = _COLOR_HEX.get(color, "#E0E0E0")
        line = (
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:{hexcolor};">{_html.escape(text)}</span>'
        )
        self._term.append(line)
        bar = self._term.verticalScrollBar()
        bar.setValue(bar.maximum())
