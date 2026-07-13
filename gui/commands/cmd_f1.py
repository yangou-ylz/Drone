# -*- coding: utf-8 -*-
"""0xF1 链路验证命令。

固件端约定（见 [FcSrc/Uplink_Cmd.c](../../FcSrc/Uplink_Cmd.c)）：
- 0xF1 帧数据：S16 X, S16 Y（小端，前 4 字节）；多余数据忽略；
- 飞控收到后限频 10Hz 通过 0xA0 绿字回显 ``F1: X=.. Y=..``；
- 无 CLP / UNK 等异常分支，纯链路打通验证。

回执解析：前缀 ``F1:`` 即视为本命令的 ACK；进一步用正则解析数值用于日志展示。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..io.protocol import ADDR_BROADCAST, build_f1_xy
from ..services.command_registry import (
    REGISTRY,
    AckResult,
    Command,
    CommandPanelBase,
)
from ..services.log_service import LogLevel


_ACK_PATTERN = re.compile(r"^F1\s*:\s*X\s*=\s*(-?\d+)\s+Y\s*=\s*(-?\d+)", re.I)


class CmdF1(Command):
    cmd_id = 0xF1
    name = "链路验证 F1"
    category = "调试"
    description = "发送两个 S16 (X, Y)，飞控以 0xA0 绿字回显，用于验证 PC→飞控链路通畅。"
    requires_confirm = False
    ack_timeout_ms = 1500

    def build_frame(self, params: dict) -> bytes:
        x = int(params["x"])
        y = int(params["y"])
        # build_f1_xy 内部约束 [-32768, 32767]；前端 QSpinBox 已限幅，这里再防一道
        if not (-32768 <= x <= 32767) or not (-32768 <= y <= 32767):
            raise ValueError(f"F1 参数越界：x={x}, y={y}")
        return build_f1_xy(ADDR_BROADCAST, x, y)

    def parse_ack(self, text: str) -> AckResult | None:
        m = _ACK_PATTERN.search(text.strip())
        if not m:
            return None
        return AckResult(
            ok=True,
            level=LogLevel.INFO,
            message=f"F1 OK：X={m.group(1)}, Y={m.group(2)}",
        )

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return F1Panel(self, parent)

    def describe_params(self, params: dict) -> str:
        return f"X={params.get('x')}, Y={params.get('y')}"


class F1Panel(CommandPanelBase):
    """F1 输入面板：两个 QSpinBox + 发送 + 重发 + 状态。"""

    send_requested = Signal(dict)

    def __init__(self, cmd: CmdF1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._last_params: dict | None = None
        self._linked = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(f"<b>{self._cmd.name}</b>  &nbsp;<span style='color:#888;'>"
                       f"CMD=0x{self._cmd.cmd_id:02X}</span>")
        root.addWidget(title)

        desc = QLabel(self._cmd.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666;")
        root.addWidget(desc)

        # 输入行
        row = QHBoxLayout()
        row.addWidget(QLabel("X:"))
        self._sb_x = QSpinBox()
        self._sb_x.setRange(-32768, 32767)
        self._sb_x.setValue(1234)
        self._sb_x.setMinimumWidth(110)
        row.addWidget(self._sb_x)

        row.addSpacing(12)
        row.addWidget(QLabel("Y:"))
        self._sb_y = QSpinBox()
        self._sb_y.setRange(-32768, 32767)
        self._sb_y.setValue(-4562)
        self._sb_y.setMinimumWidth(110)
        row.addWidget(self._sb_y)
        row.addStretch(1)
        root.addLayout(row)

        # 按钮行
        btn_row = QHBoxLayout()
        self._btn_send = QPushButton("发送")
        self._btn_send.setMinimumWidth(100)
        self._btn_send.clicked.connect(self._on_send)
        btn_row.addWidget(self._btn_send)

        self._btn_resend = QPushButton("重发上次")
        self._btn_resend.setEnabled(False)
        self._btn_resend.clicked.connect(self._on_resend)
        btn_row.addWidget(self._btn_resend)

        btn_row.addStretch(1)
        root.addLayout(btn_row)

        # 状态行：状态灯 ● + 文本
        status_row = QHBoxLayout()
        self._lamp = QLabel("●")
        self._lamp.setStyleSheet("color: #888; font-size: 16pt;")
        status_row.addWidget(self._lamp)
        self._status = QLabel("（未连接串口时发送按钮不可用）")
        self._status.setStyleSheet("color: #888;")
        status_row.addWidget(self._status, 1)
        root.addLayout(status_row)

        root.addStretch(1)
        self._refresh_buttons()

    # ---- 公共 ----
    def set_enabled_for_link(self, linked: bool) -> None:
        self._linked = bool(linked)
        self._refresh_buttons()
        if linked:
            self.set_ack_state(self.STATE_IDLE, "就绪。点击发送或重发上次。")
        else:
            self.set_ack_state(self.STATE_IDLE, "（未连接串口时发送按钮不可用）")

    def set_ack_state(self, state: str, message: str = "") -> None:
        # 状态灯颜色 + 文字色
        if state == self.STATE_WAITING:
            self._lamp.setStyleSheet("color: #FBC02D; font-size: 16pt;")  # 黄
            self._status.setStyleSheet("color: #B58900;")
            text = message or "等待回执…"
        elif state == self.STATE_OK:
            self._lamp.setStyleSheet("color: #2E7D32; font-size: 16pt;")  # 绿
            self._status.setStyleSheet("color: #2E7D32;")
            text = message or "发送成功"
        elif state == self.STATE_WARN:
            self._lamp.setStyleSheet("color: #EF6C00; font-size: 16pt;")  # 橙
            self._status.setStyleSheet("color: #EF6C00;")
            text = message or "发送完成（限幅/警告）"
        elif state in (self.STATE_FAIL, self.STATE_TIMEOUT):
            self._lamp.setStyleSheet("color: #C62828; font-size: 16pt;")  # 红
            self._status.setStyleSheet("color: #C62828;")
            text = message or ("超时未收到回执" if state == self.STATE_TIMEOUT else "发送失败")
        else:  # IDLE
            self._lamp.setStyleSheet("color: #888; font-size: 16pt;")
            self._status.setStyleSheet("color: #888;")
            text = message or "就绪"
        self._status.setText(text)

    # ---- 槽 ----
    def _on_send(self) -> None:
        params = {"x": self._sb_x.value(), "y": self._sb_y.value()}
        self._last_params = dict(params)
        self.send_requested.emit(params)
        self._btn_resend.setEnabled(self._linked)

    def _on_resend(self) -> None:
        if not self._last_params:
            return
        self.send_requested.emit(dict(self._last_params))

    def _refresh_buttons(self) -> None:
        self._btn_send.setEnabled(self._linked)
        self._btn_resend.setEnabled(self._linked and self._last_params is not None)


# 模块导入即注册（commands/__init__.py 引用本模块即触发）
REGISTRY.register(CmdF1())
