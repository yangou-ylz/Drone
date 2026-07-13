# -*- coding: utf-8 -*-
"""0xF3 三轴目标坐标同帧写入命令（敏感）。

固件端约定（见 FcSrc/Uplink_Cmd.c）：
- 0xF3 帧 DATA = float32_LE × 3（共 12 字节，依次 x/y/z，单位 cm）；
- 飞控对每个轴各自做 ``|v| ≤ 500cm`` 限幅，任一轴被限幅 → 回显末尾带 ``CLP``；
- 与 0xF2 共享同一组 RAM 槽位与 Getter，断电丢值；
- 飞控通过 0xA0 回显：
    * 成功：``P*=30.0,44.0,55.0``        （绿，INFO）
    * 限幅：``P*=500.0,44.0,55.0 CLP``   （绿，WARN）
- 不会出现 UNK（0xF3 无 ID 字段）。

相对 0xF2 的优势：三轴原子写入，避免拆 3 帧串联时任一丢包导致状态撕裂。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..io.protocol import ADDR_BROADCAST, build_f3_xyz
from ..services.command_registry import (
    REGISTRY,
    AckResult,
    Command,
    CommandPanelBase,
)
from ..services.log_service import LogLevel
from ..widgets.stable_spinbox import StableDoubleSpinBox


_PARAM_LIMIT_CM = 500.0   # 与 FC 端对齐（仅做参考显示）

# 回执正则：``P*=30.0,44.0,55.0`` 或带 ``CLP`` 后缀
_ACK_OK = re.compile(
    r"^P\*\s*=\s*"
    r"(-?\d+(?:\.\d+)?)\s*,\s*"
    r"(-?\d+(?:\.\d+)?)\s*,\s*"
    r"(-?\d+(?:\.\d+)?)"
    r"(?:\s+(CLP))?\s*$"
)


class CmdF3(Command):
    cmd_id = 0xF3
    name = "三轴目标 F3"
    category = "参数"
    description = (
        "原子写入三轴目标位置（X/Y/Z, cm）。单帧 15B（含 12B 数据），"
        "飞控对每轴各自限幅 ±500，任一被限幅回执末尾标 CLP。"
    )
    requires_confirm = True   # 改飞控状态，强制二次确认
    ack_timeout_ms = 1500

    def build_frame(self, params: dict) -> bytes:
        x = float(params["x"])
        y = float(params["y"])
        z = float(params["z"])
        return build_f3_xyz(ADDR_BROADCAST, x, y, z)

    def parse_ack(self, text: str) -> AckResult | None:
        s = text.strip()
        m = _ACK_OK.match(s)
        if m:
            x, y, z = m.group(1), m.group(2), m.group(3)
            clamped = m.group(4) is not None
            if clamped:
                return AckResult(
                    ok=True,
                    level=LogLevel.WARN,
                    message=f"F3 限幅：X={x}, Y={y}, Z={z} (CLP)",
                )
            return AckResult(
                ok=True,
                level=LogLevel.INFO,
                message=f"F3 OK：X={x}, Y={y}, Z={z}",
            )
        return None

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return F3Panel(self, parent)

    def describe_params(self, params: dict) -> str:
        return (
            f"X={params.get('x')}, "
            f"Y={params.get('y')}, "
            f"Z={params.get('z')} (cm)"
        )


class F3Panel(CommandPanelBase):
    """F3 输入面板：X/Y/Z 三个 SpinBox + 发送 + 重发 + 三态灯。"""

    send_requested = Signal(dict)

    def __init__(self, cmd: CmdF3, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._last_params: dict | None = None
        self._linked = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(
            f"<b>{self._cmd.name}</b>  &nbsp;<span style='color:#888;'>"
            f"CMD=0x{self._cmd.cmd_id:02X}</span>"
            "  &nbsp;<span style='color:#C62828;'>[敏感命令]</span>"
        )
        root.addWidget(title)

        desc = QLabel(self._cmd.description)
        desc.setWordWrap(True)
        desc.setStyleSheet("color: #666;")
        root.addWidget(desc)

        # 输入行：X / Y / Z
        row = QHBoxLayout()
        row.addWidget(QLabel("X:"))
        self._sb_x = self._make_axis_sb(0.0)
        row.addWidget(self._sb_x)
        row.addSpacing(8)
        row.addWidget(QLabel("Y:"))
        self._sb_y = self._make_axis_sb(0.0)
        row.addWidget(self._sb_y)
        row.addSpacing(8)
        row.addWidget(QLabel("Z:"))
        self._sb_z = self._make_axis_sb(0.0)
        row.addWidget(self._sb_z)
        row.addStretch(1)
        root.addLayout(row)

        hint = QLabel(
            f"<span style='color:#888;'>飞控对每轴各自限幅 ±{_PARAM_LIMIT_CM:.0f} cm，"
            f"超出会自动 clamp 并在回执末尾标 CLP</span>"
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

    def _make_axis_sb(self, default: float) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(-600.0, 600.0)
        sb.setDecimals(1)
        sb.setSingleStep(10.0)
        sb.setValue(default)
        sb.setMinimumWidth(110)
        sb.setSuffix(" cm")
        return sb

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
            text = message or (
                "超时未收到回执" if state == self.STATE_TIMEOUT else "写入失败"
            )
        else:
            self._lamp.setStyleSheet("color: #888; font-size: 16pt;")
            self._status.setStyleSheet("color: #888;")
            text = message or "就绪"
        self._status.setText(text)

    # ---- 槽 ----
    def _on_send(self) -> None:
        params = {
            "x": float(self._sb_x.value()),
            "y": float(self._sb_y.value()),
            "z": float(self._sb_z.value()),
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
REGISTRY.register(CmdF3())
