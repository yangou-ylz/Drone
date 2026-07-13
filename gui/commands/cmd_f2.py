# -*- coding: utf-8 -*-
"""0xF2 参数写入命令（敏感）。

固件端约定（见 [FcSrc/Uplink_Cmd.c](../../FcSrc/Uplink_Cmd.c)）：
- 0xF2 帧 DATA = U8 ID + Float32(LE) Value（共 5 字节）；
- 白名单 ID：0x01/0x02/0x03 分别对应目标 X/Y/Z (cm)；其余返回 UNK；
- 限幅 |value| ≤ 500.0 cm，超出 clamp 并打 CLP 标记；
- 飞控通过 0xA0 回显：
    * 成功：``P01=50.0``         （绿，INFO）
    * 限幅：``P01=500.0 CLP``    （绿，WARN）
    * 未知 ID：``P?? UNK``       （红，ERROR）

二次确认：是。修改飞控运行时目标位置，必须强制用户勾选确认。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..io.protocol import ADDR_BROADCAST, build_f2_param
from ..services.command_registry import (
    REGISTRY,
    AckResult,
    Command,
    CommandPanelBase,
)
from ..services.log_service import LogLevel
from ..widgets.stable_spinbox import StableDoubleSpinBox


# 必须与 FcSrc/Uplink_Cmd.h 保持一致
_PARAM_OPTIONS = (
    (0x01, "目标 X 位置 (cm)"),
    (0x02, "目标 Y 位置 (cm)"),
    (0x03, "目标 Z 位置 (cm)"),
)
_PARAM_LIMIT_CM = 500.0   # 与 FC 端 PARAM_GOAL_LIMIT_CM 对齐（仅做参考显示，飞控仍会自行限幅）

# 回执正则：``P01=50.0`` / ``P01=500.0 CLP`` / ``P?? UNK``
_ACK_OK = re.compile(r"^P([0-9A-Fa-f]{2})\s*=\s*(-?\d+(?:\.\d+)?)(?:\s+(CLP))?\s*$")
_ACK_UNK = re.compile(r"^P([0-9A-Fa-f?]{2})\s+UNK\s*$")


class CmdF2(Command):
    cmd_id = 0xF2
    name = "参数写入 F2"
    category = "参数"
    description = (
        "向飞控写入运行时目标位置（cm）。ID=0x01/0x02/0x03 → 目标 X/Y/Z；"
        "|value| > 500 飞控自动限幅；ID 不在白名单返回 UNK。"
    )
    requires_confirm = True   # 改飞控状态，强制二次确认
    ack_timeout_ms = 1500

    def build_frame(self, params: dict) -> bytes:
        pid = int(params["param_id"]) & 0xFF
        value = float(params["value"])
        return build_f2_param(ADDR_BROADCAST, pid, value)

    def parse_ack(self, text: str) -> AckResult | None:
        s = text.strip()
        # UNK 优先匹配（更具特征）
        m = _ACK_UNK.match(s)
        if m:
            pid = m.group(1).upper()
            return AckResult(
                ok=False,
                level=LogLevel.ERROR,
                message=f"F2 失败：未知参数 ID P{pid}",
            )
        m = _ACK_OK.match(s)
        if m:
            pid = m.group(1).upper()
            value = m.group(2)
            clamped = m.group(3) is not None
            if clamped:
                return AckResult(
                    ok=True,
                    level=LogLevel.WARN,
                    message=f"F2 限幅：P{pid}={value} (CLP)",
                )
            return AckResult(
                ok=True,
                level=LogLevel.INFO,
                message=f"F2 OK：P{pid}={value}",
            )
        return None

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return F2Panel(self, parent)

    def describe_params(self, params: dict) -> str:
        pid = int(params.get("param_id", 0))
        label = next((n for i, n in _PARAM_OPTIONS if i == pid), f"未知 0x{pid:02X}")
        return f"ID=0x{pid:02X} ({label}), Value={params.get('value')}"


class F2Panel(CommandPanelBase):
    """F2 输入面板：参数 ID 下拉 + Value QDoubleSpinBox + 三态灯。"""

    send_requested = Signal(dict)

    def __init__(self, cmd: CmdF2, parent: QWidget | None = None) -> None:
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
                       f"CMD=0x{self._cmd.cmd_id:02X}</span>"
                       "  &nbsp;<span style='color:#C62828;'>[敏感命令]</span>")
        root.addWidget(title)

        desc = QLabel(self._cmd.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666;")
        root.addWidget(desc)

        # 输入行
        row = QHBoxLayout()
        row.addWidget(QLabel("参数 ID："))
        self._cb_id = QComboBox()
        for pid, name in _PARAM_OPTIONS:
            self._cb_id.addItem(f"0x{pid:02X}  {name}", pid)
        self._cb_id.setMinimumWidth(220)
        row.addWidget(self._cb_id)

        row.addSpacing(12)
        row.addWidget(QLabel("Value："))

        self._sb_value = StableDoubleSpinBox()
        self._sb_value.setRange(-600.0, 600.0)
        self._sb_value.setDecimals(1)
        self._sb_value.setSingleStep(10.0)
        self._sb_value.setValue(50.0)
        self._sb_value.setMinimumWidth(140)
        self._sb_value.setSuffix(" cm")
        row.addWidget(self._sb_value)
        row.addStretch(1)
        root.addLayout(row)

        hint = QLabel(
            f"<span style='color:#888;'>飞控限幅范围：±{_PARAM_LIMIT_CM:.0f} cm，"
            f"超出会自动 clamp 并标 CLP</span>"
        )
        root.addWidget(hint)

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

        # 状态行：● + 文本
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
            self.set_ack_state(self.STATE_IDLE, "就绪。点击发送（需二次确认）。")
        else:
            self.set_ack_state(self.STATE_IDLE, "（未连接串口时发送按钮不可用）")

    def set_ack_state(self, state: str, message: str = "") -> None:
        if state == self.STATE_WAITING:
            self._lamp.setStyleSheet("color: #FBC02D; font-size: 16pt;")
            self._status.setStyleSheet("color: #B58900;")
            text = message or "等待回执…"
        elif state == self.STATE_OK:
            self._lamp.setStyleSheet("color: #2E7D32; font-size: 16pt;")
            self._status.setStyleSheet("color: #2E7D32;")
            text = message or "写入成功"
        elif state == self.STATE_WARN:
            self._lamp.setStyleSheet("color: #EF6C00; font-size: 16pt;")
            self._status.setStyleSheet("color: #EF6C00;")
            text = message or "已写入但触发限幅 CLP"
        elif state in (self.STATE_FAIL, self.STATE_TIMEOUT):
            self._lamp.setStyleSheet("color: #C62828; font-size: 16pt;")
            self._status.setStyleSheet("color: #C62828;")
            text = message or ("超时未收到回执" if state == self.STATE_TIMEOUT else "写入失败")
        else:
            self._lamp.setStyleSheet("color: #888; font-size: 16pt;")
            self._status.setStyleSheet("color: #888;")
            text = message or "就绪"
        self._status.setText(text)

    # ---- 槽 ----
    def _on_send(self) -> None:
        params = {
            "param_id": int(self._cb_id.currentData()),
            "value": float(self._sb_value.value()),
        }
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


# 模块导入即注册
REGISTRY.register(CmdF2())
