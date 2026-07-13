# -*- coding: utf-8 -*-
"""ConnectionBar —— 串口连接控制条。

布局（从左到右）：
    [串口  ▼] [刷新] [波特率 500000 (只读)] [连接/断开] [●状态] [提示文字]

设计：
- QComboBox 可编辑：既能从枚举列表选，也能手动输入未列出的 COM 口；
- 波特率显式只读显示 500000，提醒用户该值由数传驱动固化，不可改；
- 连接按钮单按钮二态（连接<->断开），降低误操作；
- 上次成功连接的串口名通过 ConfigService 记忆并默认填回；
- 仅发信号 :attr:`connect_requested` / :attr:`disconnect_requested`，
  实际打开/关闭由 MainWindow 路由到 SerialWorker，本控件不持有串口对象。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from ..io.serial_ports import list_serial_ports
from ..services.config_service import ConfigService


# 连接状态指示灯样式
_LED_STYLE = {
    "off": "color: #888; font-size: 18px;",
    "on": "color: #2E7D32; font-size: 18px;",   # 绿
    "err": "color: #C62828; font-size: 18px;",  # 红
}


class ConnectionBar(QWidget):
    """串口连接条控件。"""

    connect_requested = Signal(str)   # 要打开的串口名
    disconnect_requested = Signal()

    def __init__(self, config: ConfigService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._config = config
        self._connected = False
        self._build_ui()
        self.refresh_ports()
        # 回填上次串口
        last = self._config.get("last_port", "")
        if last:
            idx = self._combo.findText(last)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            else:
                self._combo.setEditText(last)

    # ---- 公共接口 ----
    def refresh_ports(self) -> None:
        """重新枚举本机 COM 口并更新下拉。"""
        current_text = self._combo.currentText().strip()
        self._combo.blockSignals(True)
        self._combo.clear()
        ports = list_serial_ports()
        for port, _friendly in ports:
            self._combo.addItem(port)
        # 还原文字（即便不在新列表里，editable 也能保留）
        if current_text:
            idx = self._combo.findText(current_text)
            if idx >= 0:
                self._combo.setCurrentIndex(idx)
            else:
                self._combo.setEditText(current_text)
        self._combo.blockSignals(False)
        self._hint.setText(f"已发现 {len(ports)} 个串口")

    def set_connected(self, port_name: str) -> None:
        """SerialWorker.connected 信号回调。"""
        self._connected = True
        self._led.setStyleSheet(_LED_STYLE["on"])
        self._led.setText("●")
        self._btn.setText("断开")
        self._combo.setEnabled(False)
        self._refresh_btn.setEnabled(False)
        self._hint.setText(f"已连接：{port_name}")
        # 记忆到 config
        self._config.set("last_port", port_name)

    def set_disconnected(self, reason: str = "") -> None:
        """SerialWorker.disconnected 信号回调。"""
        self._connected = False
        self._led.setStyleSheet(_LED_STYLE["off"])
        self._led.setText("●")
        self._btn.setText("连接")
        self._combo.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._hint.setText(f"已断开：{reason}" if reason else "未连接")

    def set_error(self, msg: str = "") -> None:
        """显示红色错误指示灯（断开但表明是异常断开）。"""
        self._led.setStyleSheet(_LED_STYLE["err"])
        if msg:
            self._hint.setText(msg)

    @property
    def is_connected(self) -> bool:
        return self._connected

    @property
    def current_port_text(self) -> str:
        return self._combo.currentText().strip()

    # ---- UI ----
    def _build_ui(self) -> None:
        lay = QHBoxLayout(self)
        lay.setContentsMargins(8, 6, 8, 6)
        lay.setSpacing(8)

        lay.addWidget(QLabel("串口："))
        self._combo = QComboBox()
        self._combo.setEditable(True)
        self._combo.setMinimumWidth(140)
        self._combo.setToolTip("从下拉选择，或手动输入 COM 口名（如 COM12）；\nCOM10+ 系统会自动加 \\\\.\\ 前缀")
        lay.addWidget(self._combo)

        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setToolTip("重新枚举本机串口")
        self._refresh_btn.clicked.connect(self.refresh_ports)
        lay.addWidget(self._refresh_btn)

        baud_lbl = QLabel("波特率：500000")
        baud_lbl.setStyleSheet("color: #555;")
        baud_lbl.setToolTip("匿名数传波特率由驱动固化，不可修改")
        lay.addWidget(baud_lbl)

        self._btn = QPushButton("连接")
        self._btn.setMinimumWidth(80)
        self._btn.clicked.connect(self._on_btn)
        lay.addWidget(self._btn)

        self._led = QLabel("●")
        self._led.setStyleSheet(_LED_STYLE["off"])
        f = QFont()
        f.setPointSize(14)
        self._led.setFont(f)
        self._led.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._led)

        self._hint = QLabel("未连接")
        self._hint.setStyleSheet("color: #555;")
        lay.addWidget(self._hint, 1)  # stretch

    def _on_btn(self) -> None:
        if self._connected:
            self.disconnect_requested.emit()
        else:
            port = self._combo.currentText().strip()
            if not port:
                self._hint.setText("请输入或选择串口")
                return
            self.connect_requested.emit(port)
