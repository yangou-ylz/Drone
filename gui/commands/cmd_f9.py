# -*- coding: utf-8 -*-
"""0xF9 GUI相对位移命令。

第一版用途：飞行器已经在 Mode2 且已解锁悬停时，GUI 发送 X/Y/Z 相对位移，
STM32 复用现有 PID3D 位置环执行移动。F9 不负责起飞/降落；降落仍使用 F7。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..io.protocol import (
    ADDR_BROADCAST,
    AUTO_MOVE_AXIS_AUTO,
    AUTO_MOVE_AXIS_X,
    AUTO_MOVE_AXIS_XY,
    AUTO_MOVE_AXIS_XYZ,
    AUTO_MOVE_AXIS_Y,
    AUTO_MOVE_AXIS_Z,
    AUTO_MOVE_CMD_QUERY,
    AUTO_MOVE_CMD_START,
    AUTO_MOVE_CMD_STOP,
    AUTO_MOVE_LIMIT_CM,
    AUTO_SAFETY_KEY,
    build_f9_move_cmd,
)
from ..services.auto_mission_labels import error_label, format_auto_a0_text
from ..services.command_registry import (
    REGISTRY,
    AckResult,
    Command,
    CommandPanelBase,
)
from ..services.log_service import LogLevel
from ..widgets.stable_spinbox import StableDoubleSpinBox


_MOVE_ACK = re.compile(r"^AUTO\s+(MOVE_[A-Z0-9_]+)(.*)$", re.I)


_CMD_LABELS = {
    AUTO_MOVE_CMD_QUERY: "查询位移状态",
    AUTO_MOVE_CMD_START: "启动相对位移",
    AUTO_MOVE_CMD_STOP: "停止位移",
}


class CmdF9(Command):
    cmd_id = 0xF9
    name = "相对位移 F9"
    category = "自主"
    description = "GUI发送相对位移，STM32复用现有PID3D位置环执行；不负责起飞/降落。"
    requires_confirm = False
    ack_timeout_ms = 1800

    def build_frame(self, params: dict) -> bytes:
        cmd = int(params["cmd"]) & 0xFF
        safety_key = AUTO_SAFETY_KEY if cmd == AUTO_MOVE_CMD_START else 0
        return build_f9_move_cmd(
            ADDR_BROADCAST,
            int(params["seq"]) & 0xFFFF,
            cmd,
            safety_key=safety_key,
            x_cm=float(params.get("x_cm", 0.0)),
            y_cm=float(params.get("y_cm", 0.0)),
            z_cm=float(params.get("z_cm", 0.0)),
            axis_mode=int(params.get("axis_mode", AUTO_MOVE_AXIS_AUTO)),
            flags=int(params.get("flags", 0)),
        )

    def parse_ack(self, text: str) -> AckResult | None:
        s = text.strip()
        m = _MOVE_ACK.match(s)
        if not m:
            return None
        event = m.group(1).upper()
        translated = format_auto_a0_text(s)
        if "ERR" in event or "DENY" in event or "TIMEOUT" in event:
            return AckResult(False, LogLevel.ERROR, f"F9 失败：{translated}")
        if "BUSY" in event or "CLP" in event or "DUP" in event:
            return AckResult(True, LogLevel.WARN, f"F9 警告：{translated}")
        return AckResult(True, LogLevel.INFO, f"F9 OK：{translated}")

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return F9Panel(self, parent)

    def describe_params(self, params: dict) -> str:
        cmd = int(params.get("cmd", -1))
        return (
            f"{_CMD_LABELS.get(cmd, f'cmd=0x{cmd:02X}')}, "
            f"seq={params.get('seq')}, "
            f"X={float(params.get('x_cm', 0.0)):.1f}cm, "
            f"Y={float(params.get('y_cm', 0.0)):.1f}cm, "
            f"Z={float(params.get('z_cm', 0.0)):.1f}cm"
        )


class F9Panel(CommandPanelBase):
    send_requested = Signal(dict)

    def __init__(self, cmd: CmdF9, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._linked = False
        self._seq = 1
        self._last_params: dict | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(
            f"<b>{self._cmd.name}</b>  &nbsp;<span style='color:#888;'>CMD=0xF9</span>"
            "  &nbsp;<span style='color:#C62828;'>[飞行中敏感]</span>"
        )
        root.addWidget(title)

        desc = QLabel(
            "要求：飞机已在定点Mode2、已解锁且稳定悬停；F9只移动，不起飞不降落。"
            "停止位移只清零速度，正常降落请用F7一键降落。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#666;")
        root.addWidget(desc)

        pos_box = QGroupBox("相对位移")
        grid = QGridLayout(pos_box)
        grid.addWidget(QLabel("X"), 0, 0)
        self._x = self._axis_spin(30.0)
        grid.addWidget(self._x, 0, 1)
        grid.addWidget(QLabel("Y"), 0, 2)
        self._y = self._axis_spin(0.0)
        grid.addWidget(self._y, 0, 3)
        grid.addWidget(QLabel("Z"), 0, 4)
        self._z = self._axis_spin(0.0)
        grid.addWidget(self._z, 0, 5)

        grid.addWidget(QLabel("轴模式"), 1, 0)
        self._axis_mode = QComboBox()
        self._axis_mode.addItem("自动", AUTO_MOVE_AXIS_AUTO)
        self._axis_mode.addItem("仅 X", AUTO_MOVE_AXIS_X)
        self._axis_mode.addItem("仅 Y", AUTO_MOVE_AXIS_Y)
        self._axis_mode.addItem("仅 Z", AUTO_MOVE_AXIS_Z)
        self._axis_mode.addItem("XY 联动", AUTO_MOVE_AXIS_XY)
        self._axis_mode.addItem("XYZ 联动", AUTO_MOVE_AXIS_XYZ)
        grid.addWidget(self._axis_mode, 1, 1, 1, 2)

        hint = QLabel(
            f"第一版每轴限幅 ±{AUTO_MOVE_LIMIT_CM}cm；建议首飞只测 X=20~30cm，Y/Z先为0。"
        )
        hint.setStyleSheet("color:#777;")
        grid.addWidget(hint, 1, 3, 1, 3)
        root.addWidget(pos_box)

        self._confirm = QCheckBox("我已确认：飞机已稳定悬停，周围安全，允许执行位移")
        self._confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        root.addWidget(self._confirm)

        row = QHBoxLayout()
        self._btn_query = QPushButton("查询位移状态")
        self._btn_query.clicked.connect(lambda: self._send(AUTO_MOVE_CMD_QUERY))
        row.addWidget(self._btn_query)

        self._btn_start = QPushButton("启动相对位移")
        self._btn_start.setStyleSheet("font-weight:bold;color:#C62828;")
        self._btn_start.clicked.connect(lambda: self._send(AUTO_MOVE_CMD_START))
        row.addWidget(self._btn_start)

        self._btn_stop = QPushButton("停止位移")
        self._btn_stop.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_stop.clicked.connect(lambda: self._send(AUTO_MOVE_CMD_STOP))
        row.addWidget(self._btn_stop)
        row.addStretch(1)
        root.addLayout(row)

        status_row = QHBoxLayout()
        self._lamp = QLabel("●")
        self._lamp.setStyleSheet("color:#888;font-size:16pt;")
        status_row.addWidget(self._lamp)
        self._status = QLabel("（未连接串口时发送按钮不可用）")
        self._status.setStyleSheet("color:#888;")
        status_row.addWidget(self._status, 1)
        root.addLayout(status_row)

        root.addStretch(1)
        self._refresh_buttons()

    def _axis_spin(self, default: float) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(-float(AUTO_MOVE_LIMIT_CM), float(AUTO_MOVE_LIMIT_CM))
        sb.setDecimals(1)
        sb.setSingleStep(10.0)
        sb.setValue(default)
        sb.setSuffix(" cm")
        sb.setMinimumWidth(105)
        return sb

    def set_enabled_for_link(self, linked: bool) -> None:
        self._linked = bool(linked)
        self._refresh_buttons()
        if linked:
            self.set_ack_state(self.STATE_IDLE, "就绪。先查询；首测建议 X=20~30cm。")
        else:
            self.set_ack_state(self.STATE_IDLE, "（未连接串口时发送按钮不可用）")

    def set_ack_state(self, state: str, message: str = "") -> None:
        if state == self.STATE_WAITING:
            self._lamp.setStyleSheet("color:#FBC02D;font-size:16pt;")
            self._status.setStyleSheet("color:#B58900;")
            text = message or "等待回执…"
        elif state == self.STATE_OK:
            self._lamp.setStyleSheet("color:#2E7D32;font-size:16pt;")
            self._status.setStyleSheet("color:#2E7D32;")
            text = message or "命令已确认"
        elif state == self.STATE_WARN:
            self._lamp.setStyleSheet("color:#EF6C00;font-size:16pt;")
            self._status.setStyleSheet("color:#EF6C00;")
            text = message or "命令有警告"
        elif state in (self.STATE_FAIL, self.STATE_TIMEOUT):
            self._lamp.setStyleSheet("color:#C62828;font-size:16pt;")
            self._status.setStyleSheet("color:#C62828;")
            text = message or ("超时未收到回执" if state == self.STATE_TIMEOUT else "命令失败")
        else:
            self._lamp.setStyleSheet("color:#888;font-size:16pt;")
            self._status.setStyleSheet("color:#888;")
            text = message or "就绪"
        self._status.setText(text)

    def _send(self, cmd: int) -> None:
        if cmd == AUTO_MOVE_CMD_START and not self._confirm.isChecked():
            self.set_ack_state(self.STATE_FAIL, "启动位移已拦截：未勾选安全确认")
            return
        params = {
            "seq": self._seq,
            "cmd": cmd,
            "x_cm": float(self._x.value()),
            "y_cm": float(self._y.value()),
            "z_cm": float(self._z.value()),
            "axis_mode": int(self._axis_mode.currentData()),
            "flags": 0,
        }
        self._seq = (self._seq + 1) & 0xFFFF
        if self._seq == 0:
            self._seq = 1
        self._last_params = dict(params)
        self.send_requested.emit(params)

    def _refresh_buttons(self) -> None:
        self._btn_query.setEnabled(self._linked)
        self._btn_start.setEnabled(self._linked)
        self._btn_stop.setEnabled(self._linked)


REGISTRY.register(CmdF9())
