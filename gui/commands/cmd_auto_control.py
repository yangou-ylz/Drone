# -*- coding: utf-8 -*-
"""GUI-only 自主飞行组合面板。

该面板不新增飞控协议，不直接下发 0xEA。它只是把常用的 F7 起飞/降落
和 F9 相对位移按钮放在同一页，减少飞行测试时来回切换面板。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..io.protocol import (
    AUTO_CMD_ABORT_LAND,
    AUTO_CMD_CLEAR_ERROR,
    AUTO_CMD_EMERGENCY_LOCK,
    AUTO_CMD_LAND_ONLY,
    AUTO_CMD_LOCK_RC,
    AUTO_CMD_PRECHECK,
    AUTO_CMD_QUERY_STATUS,
    AUTO_CMD_RELEASE_RC,
    AUTO_CMD_REQUEST_MODE2,
    AUTO_CMD_START_LOW_TAKEOFF_LAND,
    AUTO_CMD_TAKEOFF_HOLD,
    AUTO_FLAG_NO_XY_MOTION,
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
    CMD_AUTO_MISSION,
    CMD_AUTO_MOVE,
)
from ..services.auto_mission_labels import (
    error_label,
    flag_summary,
    rc_control_label,
    rc_input_color,
    rc_input_label,
    state_label,
)
from ..services.command_registry import AckResult, Command, CommandPanelBase, REGISTRY
from ..widgets.stable_spinbox import StableDoubleSpinBox


F7_LABELS = {
    AUTO_CMD_QUERY_STATUS: "查询状态",
    AUTO_CMD_PRECHECK: "预检",
    AUTO_CMD_REQUEST_MODE2: "请求定点",
    AUTO_CMD_CLEAR_ERROR: "清错误",
    AUTO_CMD_LOCK_RC: "锁定遥控权",
    AUTO_CMD_RELEASE_RC: "释放遥控权",
    AUTO_CMD_TAKEOFF_HOLD: "一键起飞保持",
    AUTO_CMD_START_LOW_TAKEOFF_LAND: "定时起降测试",
    AUTO_CMD_LAND_ONLY: "一键降落",
    AUTO_CMD_ABORT_LAND: "中止并降落",
    AUTO_CMD_EMERGENCY_LOCK: "强制上锁",
}

F9_LABELS = {
    AUTO_MOVE_CMD_QUERY: "查询位移",
    AUTO_MOVE_CMD_START: "启动位移",
    AUTO_MOVE_CMD_STOP: "停止位移",
}


class CmdAutoControl(Command):
    """UI-only 组合入口，真实发送由面板代理到 F7/F9。"""

    cmd_id = 0xEA
    name = "自主飞行控制"
    category = "自主"
    description = "同一页完成 F7 起飞/降落与 F9 相对位移；底层协议不变。"
    requires_confirm = False
    ack_timeout_ms = 0

    def build_frame(self, params: dict) -> bytes:
        raise NotImplementedError("自主飞行控制是GUI组合面板，不直接发送0xEA帧")

    def parse_ack(self, text: str) -> AckResult | None:
        return None

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return AutoControlPanel(parent)


class AutoControlPanel(CommandPanelBase):
    """常用自主飞行操作集中面板。"""

    command_send_requested = Signal(int, dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._linked = False
        self._f7_seq = 1
        self._f9_seq = 1
        self._buttons: list[QPushButton] = []
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(
            "<b>自主飞行控制</b>  "
            "<span style='color:#777;'>同页代理 F7 起飞/降落 + F9 相对位移</span>"
        )
        root.addWidget(title)

        status_box = QGroupBox("实时状态（0xF8）")
        status_grid = QGridLayout(status_box)
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(5)
        self._live_labels: dict[str, QLabel] = {}
        self._add_live_field(status_grid, "状态", "state", 0, 0)
        self._add_live_field(status_grid, "错误", "error", 0, 2)
        self._add_live_field(status_grid, "模式", "mode", 1, 0)
        self._add_live_field(status_grid, "解锁", "unlock", 1, 2)
        self._add_live_field(status_grid, "电压", "voltage", 2, 0)
        self._add_live_field(status_grid, "高度", "alt", 2, 2)
        self._add_live_field(status_grid, "传感", "sensor", 3, 0)
        self._add_live_field(status_grid, "遥控", "rc", 3, 2)
        self._add_live_field(status_grid, "标志", "flags", 4, 0)
        self._set_all_live_waiting()
        root.addWidget(status_box)

        prep_box = QGroupBox("飞前准备")
        prep = QGridLayout(prep_box)
        self._add_f7_button(prep, "查询状态", AUTO_CMD_QUERY_STATUS, 0, 0)
        self._add_f7_button(prep, "预检", AUTO_CMD_PRECHECK, 0, 1)
        self._add_f7_button(prep, "请求定点", AUTO_CMD_REQUEST_MODE2, 0, 2)
        self._btn_lock_rc = self._add_f7_button(prep, "锁定遥控权", AUTO_CMD_LOCK_RC, 1, 0)
        self._btn_lock_rc.setStyleSheet("font-weight:bold;color:#2E7D32;")
        self._add_f7_button(prep, "释放遥控权", AUTO_CMD_RELEASE_RC, 1, 1)
        self._add_f7_button(prep, "清错误", AUTO_CMD_CLEAR_ERROR, 1, 2)
        root.addWidget(prep_box)

        flight_box = QGroupBox("起飞 / 降落")
        flight = QGridLayout(flight_box)
        flight.addWidget(QLabel("起飞高度"), 0, 0)
        self._height = QSpinBox()
        self._height.setRange(30, 80)
        self._height.setValue(40)
        self._height.setSuffix(" cm")
        flight.addWidget(self._height, 0, 1)

        flight.addWidget(QLabel("总超时"), 0, 2)
        self._timeout = self._seconds_spin(30.0, 5.0, 60.0, 1.0)
        flight.addWidget(self._timeout, 0, 3)

        flight.addWidget(QLabel("定时悬停"), 1, 0)
        self._hold = self._seconds_spin(5.0, 1.0, 30.0, 0.5)
        self._hold.setToolTip("只用于“定时起降测试”；一键起飞保持不会自动倒计时降落。")
        flight.addWidget(self._hold, 1, 1)

        self._takeoff_confirm = QCheckBox("确认场地安全，允许自动起飞")
        self._takeoff_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        flight.addWidget(self._takeoff_confirm, 1, 2, 1, 2)

        self._btn_takeoff = self._add_f7_button(flight, "一键起飞保持", AUTO_CMD_TAKEOFF_HOLD, 2, 0)
        self._btn_takeoff.setStyleSheet("font-weight:bold;color:#C62828;")
        self._add_f7_button(flight, "定时起降测试", AUTO_CMD_START_LOW_TAKEOFF_LAND, 2, 1)
        self._btn_land = self._add_f7_button(flight, "一键降落", AUTO_CMD_LAND_ONLY, 2, 2)
        self._btn_land.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_abort = self._add_f7_button(flight, "中止并降落", AUTO_CMD_ABORT_LAND, 3, 0)
        self._btn_abort.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_emergency = self._add_f7_button(flight, "强制上锁", AUTO_CMD_EMERGENCY_LOCK, 3, 2)
        self._btn_emergency.setStyleSheet("font-weight:bold;background:#C62828;color:white;")
        root.addWidget(flight_box)

        move_box = QGroupBox("相对位移（F9）")
        move = QGridLayout(move_box)
        move.addWidget(QLabel("X"), 0, 0)
        self._x = self._axis_spin(30.0)
        move.addWidget(self._x, 0, 1)
        move.addWidget(QLabel("Y"), 0, 2)
        self._y = self._axis_spin(0.0)
        move.addWidget(self._y, 0, 3)
        move.addWidget(QLabel("Z"), 0, 4)
        self._z = self._axis_spin(0.0)
        move.addWidget(self._z, 0, 5)

        move.addWidget(QLabel("轴模式"), 1, 0)
        self._axis_mode = QComboBox()
        self._axis_mode.addItem("自动", AUTO_MOVE_AXIS_AUTO)
        self._axis_mode.addItem("仅 X", AUTO_MOVE_AXIS_X)
        self._axis_mode.addItem("仅 Y", AUTO_MOVE_AXIS_Y)
        self._axis_mode.addItem("仅 Z", AUTO_MOVE_AXIS_Z)
        self._axis_mode.addItem("XY 联动", AUTO_MOVE_AXIS_XY)
        self._axis_mode.addItem("XYZ 联动", AUTO_MOVE_AXIS_XYZ)
        move.addWidget(self._axis_mode, 1, 1, 1, 2)

        self._move_confirm = QCheckBox("确认飞机已稳定悬停，允许执行位移")
        self._move_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        move.addWidget(self._move_confirm, 1, 3, 1, 3)

        self._add_f9_button(move, "查询位移", AUTO_MOVE_CMD_QUERY, 2, 0)
        self._btn_move = self._add_f9_button(move, "启动位移", AUTO_MOVE_CMD_START, 2, 1)
        self._btn_move.setStyleSheet("font-weight:bold;color:#C62828;")
        self._btn_stop_move = self._add_f9_button(move, "停止位移", AUTO_MOVE_CMD_STOP, 2, 2)
        self._btn_stop_move.setStyleSheet("font-weight:bold;color:#EF6C00;")
        hint = QLabel(f"建议先测 20~50cm；每轴限幅 ±{AUTO_MOVE_LIMIT_CM}cm。")
        hint.setStyleSheet("color:#777;")
        move.addWidget(hint, 2, 3, 1, 3)
        root.addWidget(move_box)

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

    def _seconds_spin(self, default: float, low: float, high: float, step: float) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(low, high)
        sb.setDecimals(1)
        sb.setSingleStep(step)
        sb.setValue(default)
        sb.setSuffix(" s")
        sb.setMinimumWidth(95)
        return sb

    def _axis_spin(self, default: float) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(-float(AUTO_MOVE_LIMIT_CM), float(AUTO_MOVE_LIMIT_CM))
        sb.setDecimals(1)
        sb.setSingleStep(10.0)
        sb.setValue(default)
        sb.setSuffix(" cm")
        sb.setMinimumWidth(105)
        return sb

    def _add_live_field(self, grid: QGridLayout, label: str, key: str, row: int, col: int) -> None:
        name = QLabel(label)
        name.setStyleSheet("color:#666;")
        value = QLabel("--")
        value.setMinimumWidth(90)
        value.setStyleSheet("font-weight:bold;color:#555;")
        grid.addWidget(name, row, col)
        grid.addWidget(value, row, col + 1)
        self._live_labels[key] = value

    def _set_live(self, key: str, text: str, color: str = "#333", tooltip: str | None = None) -> None:
        label = self._live_labels.get(key)
        if label is None:
            return
        label.setText(text)
        label.setToolTip(tooltip or (text if len(text) > 14 else ""))
        label.setStyleSheet(f"font-weight:bold;color:{color};")

    def _set_all_live_waiting(self) -> None:
        for key in self._live_labels:
            self._set_live(key, "等待0xF8", "#777")

    def _add_f7_button(self, grid: QGridLayout, text: str, cmd: int, row: int, col: int) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.clicked.connect(lambda _checked=False, c=cmd: self._send_f7(c))
        grid.addWidget(button, row, col)
        self._buttons.append(button)
        return button

    def _add_f9_button(self, grid: QGridLayout, text: str, cmd: int, row: int, col: int) -> QPushButton:
        button = QPushButton(text)
        button.setMinimumHeight(32)
        button.clicked.connect(lambda _checked=False, c=cmd: self._send_f9(c))
        grid.addWidget(button, row, col)
        self._buttons.append(button)
        return button

    def set_enabled_for_link(self, linked: bool) -> None:
        self._linked = bool(linked)
        self._refresh_buttons()
        if linked:
            self.set_ack_state(self.STATE_IDLE, "就绪。建议流程：查询/预检 → 请求定点 → 锁定遥控权 → 起飞 → 位移 → 降落。")
        else:
            self.set_ack_state(self.STATE_IDLE, "（未连接串口时发送按钮不可用）")

    def set_ack_state(self, state: str, message: str = "") -> None:
        colors = {
            self.STATE_WAITING: ("#FBC02D", "#B58900", "等待回执..."),
            self.STATE_OK: ("#2E7D32", "#2E7D32", "命令已确认"),
            self.STATE_WARN: ("#EF6C00", "#EF6C00", "命令有警告"),
            self.STATE_FAIL: ("#C62828", "#C62828", "命令失败"),
            self.STATE_TIMEOUT: ("#C62828", "#C62828", "超时未收到回执"),
        }
        lamp_color, text_color, default = colors.get(state, ("#888", "#888", "就绪"))
        self._lamp.setStyleSheet(f"color:{lamp_color};font-size:16pt;")
        self._status.setStyleSheet(f"color:{text_color};")
        self._status.setText(message or default)

    def on_child_ack_state(self, cmd_id: int, state: str, message: str = "") -> None:
        if cmd_id in (CMD_AUTO_MISSION, CMD_AUTO_MOVE):
            self.set_ack_state(state, message)

    def on_auto_mission_status(self, sample) -> None:
        error_ok = sample.error == 0
        mode_ok = sample.mode == 2
        volt_ok = bool(sample.flags & 0x0001)
        sensor_ok = sample.ext_vel_ok and sample.ext_alt_ok
        flags = flag_summary(sample.flags, include_hex=True)
        self._set_live("state", state_label(sample.state), "#2E7D32" if error_ok else "#C62828")
        self._set_live("error", error_label(sample.error), "#2E7D32" if error_ok else "#C62828")
        self._set_live("mode", "定点Mode2" if mode_ok else f"Mode{sample.mode}", "#2E7D32" if mode_ok else "#EF6C00")
        self._set_live("unlock", "已解锁" if sample.unlock else "已上锁", "#EF6C00" if sample.unlock else "#2E7D32")
        self._set_live("voltage", f"{sample.voltage_v:.2f} V", "#2E7D32" if volt_ok else "#C62828")
        self._set_live("alt", f"{sample.alt_cm} cm", "#333")
        self._set_live("sensor", f"外速{'正常' if sample.ext_vel_ok else '无效'} / 测高{'正常' if sample.ext_alt_ok else '无效'}",
                       "#2E7D32" if sensor_ok else "#C62828")
        self._set_live("rc", f"{rc_control_label(sample)} / {rc_input_label(sample)}", rc_input_color(sample))
        self._set_live("flags", flags, "#2E7D32" if error_ok else "#C62828", tooltip=flags)

    def _send_f7(self, cmd: int) -> None:
        if cmd in (AUTO_CMD_TAKEOFF_HOLD, AUTO_CMD_START_LOW_TAKEOFF_LAND) and not self._takeoff_confirm.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "自动起飞前必须勾选安全确认。")
            self.set_ack_state(self.STATE_FAIL, "自动起飞已拦截：未勾选安全确认")
            return
        params = {
            "seq": self._f7_seq,
            "cmd": cmd,
            "height_cm": int(self._height.value()),
            "hold_ms": int(round(float(self._hold.value()) * 1000.0)),
            "flags": AUTO_FLAG_NO_XY_MOTION,
            "timeout_ms": int(round(float(self._timeout.value()) * 1000.0)),
        }
        self._f7_seq = self._next_seq(self._f7_seq)
        self.set_ack_state(self.STATE_WAITING, f"已发送 F7：{F7_LABELS.get(cmd, f'0x{cmd:02X}')}")
        self.command_send_requested.emit(CMD_AUTO_MISSION, params)

    def _send_f9(self, cmd: int) -> None:
        if cmd == AUTO_MOVE_CMD_START and not self._move_confirm.isChecked():
            self.set_ack_state(self.STATE_FAIL, "启动位移已拦截：未勾选安全确认")
            return
        params = {
            "seq": self._f9_seq,
            "cmd": cmd,
            "x_cm": float(self._x.value()),
            "y_cm": float(self._y.value()),
            "z_cm": float(self._z.value()),
            "axis_mode": int(self._axis_mode.currentData()),
            "flags": 0,
        }
        self._f9_seq = self._next_seq(self._f9_seq)
        self.set_ack_state(self.STATE_WAITING, f"已发送 F9：{F9_LABELS.get(cmd, f'0x{cmd:02X}')}")
        self.command_send_requested.emit(CMD_AUTO_MOVE, params)

    @staticmethod
    def _next_seq(seq: int) -> int:
        seq = (seq + 1) & 0xFFFF
        return 1 if seq == 0 else seq

    def _refresh_buttons(self) -> None:
        for button in self._buttons:
            button.setEnabled(self._linked)


REGISTRY.register(CmdAutoControl())
