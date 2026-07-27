# -*- coding: utf-8 -*-
"""0xFA GUI键盘低速速度控制命令。"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from ..io.protocol import (
    ADDR_BROADCAST,
    AUTO_SAFETY_KEY,
    AUTO_VEL_CMD_QUERY,
    AUTO_VEL_CMD_SET,
    AUTO_VEL_CMD_STOP,
    build_fa_velocity_cmd,
)
from ..services.auto_mission_labels import format_auto_a0_text
from ..services.command_registry import AckResult, Command, CommandPanelBase, REGISTRY
from ..services.log_service import LogLevel


_VEL_ACK = re.compile(r"^AUTO\s+(VEL_[A-Z0-9_]+)(.*)$", re.I)

_CMD_LABELS = {
    AUTO_VEL_CMD_QUERY: "查询速度控制",
    AUTO_VEL_CMD_SET: "设置速度",
    AUTO_VEL_CMD_STOP: "停止速度控制",
}


class CmdFA(Command):
    cmd_id = 0xFA
    name = "低速速度 FA"
    category = "自主"
    description = "GUI键盘低速水平速度/yaw控制；只写vel_x/vel_y/yaw_dps。"
    requires_confirm = False
    ack_timeout_ms = 900

    def build_frame(self, params: dict) -> bytes:
        cmd = int(params["cmd"]) & 0xFF
        safety_key = AUTO_SAFETY_KEY if cmd == AUTO_VEL_CMD_SET else 0
        return build_fa_velocity_cmd(
            ADDR_BROADCAST,
            int(params["seq"]) & 0xFFFF,
            cmd,
            safety_key=safety_key,
            vx_cmps=float(params.get("vx_cmps", 0.0)),
            vy_cmps=float(params.get("vy_cmps", 0.0)),
            yaw_dps=float(params.get("yaw_dps", 0.0)),
            flags=int(params.get("flags", 0)),
        )

    def parse_ack(self, text: str) -> AckResult | None:
        m = _VEL_ACK.match(text.strip())
        if not m:
            return None
        event = m.group(1).upper()
        translated = format_auto_a0_text(text)
        if "ERR" in event or "DENY" in event or "TIMEOUT" in event:
            return AckResult(False, LogLevel.ERROR, f"FA 失败：{translated}")
        if "CLP" in event or "DUP" in event:
            return AckResult(True, LogLevel.WARN, f"FA 警告：{translated}")
        return AckResult(True, LogLevel.INFO, f"FA OK：{translated}")

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return FAPanel(parent)

    def describe_params(self, params: dict) -> str:
        cmd = int(params.get("cmd", -1))
        return (
            f"{_CMD_LABELS.get(cmd, f'cmd=0x{cmd:02X}')}, "
            f"seq={params.get('seq')}, "
            f"vx={float(params.get('vx_cmps', 0.0)):.1f}cm/s, "
            f"vy={float(params.get('vy_cmps', 0.0)):.1f}cm/s, "
            f"yaw={float(params.get('yaw_dps', 0.0)):.1f}deg/s"
        )


class FAPanel(CommandPanelBase):
    send_requested = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._linked = False
        self._seq = 1
        root = QVBoxLayout(self)
        title = QLabel("<b>低速速度 FA</b>  建议日常使用“自主飞行控制”组合面板。")
        root.addWidget(title)
        self._btn_query = QPushButton("查询速度控制")
        self._btn_query.clicked.connect(self._send_query)
        root.addWidget(self._btn_query)
        root.addStretch(1)
        self.set_enabled_for_link(False)

    def set_enabled_for_link(self, linked: bool) -> None:
        self._linked = bool(linked)
        self._btn_query.setEnabled(self._linked)

    def _send_query(self) -> None:
        self.send_requested.emit({
            "seq": self._seq,
            "cmd": AUTO_VEL_CMD_QUERY,
            "vx_cmps": 0.0,
            "vy_cmps": 0.0,
            "yaw_dps": 0.0,
            "flags": 0,
        })
        self._seq = (self._seq + 1) & 0xFFFF or 1


REGISTRY.register(CmdFA())
