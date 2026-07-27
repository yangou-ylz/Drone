# -*- coding: utf-8 -*-
"""GUI-only 自主飞行组合面板。

该面板不新增飞控协议，不直接下发 0xEA。它只是把常用的 F7 起飞/降落
和 F9 相对位移按钮放在同一页，减少飞行测试时来回切换面板。
"""
from __future__ import annotations

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
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

AUTO_STATE_MOVE_HOLD = 24


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
        self._route_active = False
        self._route_legs: list[tuple[float, float, float]] = []
        self._route_index = 0
        self._route_waiting_seq: int | None = None
        self._route_timer_pending = False
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
        flight = QVBoxLayout(flight_box)
        self._takeoff_confirm = QCheckBox("确认场地安全，允许自动起飞")
        self._takeoff_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        flight.addWidget(self._takeoff_confirm)

        flight_body = QHBoxLayout()
        flight_buttons = QGridLayout()
        self._btn_takeoff = self._add_f7_button(
            flight_buttons, "一键起飞保持", AUTO_CMD_TAKEOFF_HOLD, 0, 0
        )
        self._btn_takeoff.setStyleSheet("font-weight:bold;color:#C62828;")
        self._add_f7_button(flight_buttons, "定时起降测试", AUTO_CMD_START_LOW_TAKEOFF_LAND, 0, 1)
        self._btn_land = self._add_f7_button(flight_buttons, "一键降落", AUTO_CMD_LAND_ONLY, 1, 0)
        self._btn_land.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_abort = self._add_f7_button(flight_buttons, "中止并降落", AUTO_CMD_ABORT_LAND, 1, 1)
        self._btn_abort.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_emergency = self._add_f7_button(flight_buttons, "强制上锁", AUTO_CMD_EMERGENCY_LOCK, 2, 0)
        self._btn_emergency.setStyleSheet("font-weight:bold;background:#C62828;color:white;")
        flight_body.addLayout(flight_buttons, 2)
        flight_body.addWidget(self._separator())

        flight_settings = QVBoxLayout()
        self._height = QSpinBox()
        self._height.setRange(30, 80)
        self._height.setValue(40)
        self._height.setSuffix(" cm")
        flight_settings.addWidget(self._setting_pair("起飞高度", self._height))
        self._timeout = self._seconds_spin(30.0, 5.0, 60.0, 1.0)
        flight_settings.addWidget(self._setting_pair("总超时", self._timeout))
        self._hold = self._seconds_spin(5.0, 1.0, 30.0, 0.5)
        self._hold.setToolTip("只用于“定时起降测试”；一键起飞保持不会自动倒计时降落。")
        flight_settings.addWidget(self._setting_pair("定时悬停", self._hold))
        flight_settings.addStretch(1)
        flight_body.addLayout(flight_settings, 1)
        flight.addLayout(flight_body)
        root.addWidget(flight_box)

        move_box = QGroupBox("相对位移（F9）")
        move = QVBoxLayout(move_box)
        self._move_confirm = QCheckBox("确认飞机已稳定悬停，允许执行位移")
        self._move_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        move.addWidget(self._move_confirm)

        move_body = QHBoxLayout()
        move_buttons = QGridLayout()
        self._add_f9_button(move_buttons, "查询位移", AUTO_MOVE_CMD_QUERY, 0, 0)
        self._btn_move = self._add_f9_button(move_buttons, "启动位移", AUTO_MOVE_CMD_START, 0, 1)
        self._btn_move.setStyleSheet("font-weight:bold;color:#C62828;")
        self._btn_stop_move = self._add_f9_button(move_buttons, "停止位移", AUTO_MOVE_CMD_STOP, 1, 0)
        self._btn_stop_move.setStyleSheet("font-weight:bold;color:#EF6C00;")
        move_body.addLayout(move_buttons, 2)
        move_body.addWidget(self._separator())

        move_settings = QVBoxLayout()
        self._x = self._axis_spin(30.0)
        move_settings.addWidget(self._setting_pair("X 位移", self._x))
        self._y = self._axis_spin(0.0)
        move_settings.addWidget(self._setting_pair("Y 位移", self._y))
        self._z = self._axis_spin(0.0)
        move_settings.addWidget(self._setting_pair("Z 位移", self._z))
        self._axis_mode = QComboBox()
        self._axis_mode.addItem("自动", AUTO_MOVE_AXIS_AUTO)
        self._axis_mode.addItem("仅 X", AUTO_MOVE_AXIS_X)
        self._axis_mode.addItem("仅 Y", AUTO_MOVE_AXIS_Y)
        self._axis_mode.addItem("仅 Z", AUTO_MOVE_AXIS_Z)
        self._axis_mode.addItem("XY 联动", AUTO_MOVE_AXIS_XY)
        self._axis_mode.addItem("XYZ 联动", AUTO_MOVE_AXIS_XYZ)
        move_settings.addWidget(self._setting_pair("轴模式", self._axis_mode))
        hint = QLabel(f"建议先测 20~50cm；每轴限幅 ±{AUTO_MOVE_LIMIT_CM}cm。")
        hint.setStyleSheet("color:#777;")
        move_settings.addWidget(hint)
        move_settings.addStretch(1)
        move_body.addLayout(move_settings, 1)
        move.addLayout(move_body)
        root.addWidget(move_box)

        route_box = QGroupBox("固定轨迹巡航")
        route = QVBoxLayout(route_box)
        self._route_confirm = QCheckBox("确认飞机已稳定悬停，允许连续执行多段位移")
        self._route_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        route.addWidget(self._route_confirm)

        route_body = QHBoxLayout()
        route_buttons = QGridLayout()
        self._btn_route_start = QPushButton("开始巡航")
        self._btn_route_start.setMinimumHeight(32)
        self._btn_route_start.setStyleSheet("font-weight:bold;color:#C62828;")
        self._btn_route_start.clicked.connect(self._start_route)
        route_buttons.addWidget(self._btn_route_start, 0, 0)
        self._buttons.append(self._btn_route_start)
        self._btn_route_stop = QPushButton("停止巡航")
        self._btn_route_stop.setMinimumHeight(32)
        self._btn_route_stop.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_route_stop.clicked.connect(self._stop_route)
        route_buttons.addWidget(self._btn_route_stop, 0, 1)
        self._buttons.append(self._btn_route_stop)
        self._route_status = QLabel("未开始")
        self._route_status.setStyleSheet("color:#777;")
        route_buttons.addWidget(self._route_status, 1, 0, 1, 2)
        route_body.addLayout(route_buttons, 2)
        route_body.addWidget(self._separator())

        route_settings = QVBoxLayout()
        self._route_pattern = QComboBox()
        self._route_pattern.addItem("矩形闭环：前→左→后→右", "rect")
        self._route_pattern.addItem("正方形闭环：四边等长", "square")
        self._route_pattern.addItem("直角：前→左", "front_left")
        self._route_pattern.addItem("直角：前→右", "front_right")
        self._route_pattern.addItem("前后往返", "out_back")
        route_settings.addWidget(self._setting_pair("轨迹", self._route_pattern))
        self._route_forward = self._route_spin(100.0)
        route_settings.addWidget(self._setting_pair("前后距离", self._route_forward))
        self._route_lateral = self._route_spin(100.0)
        route_settings.addWidget(self._setting_pair("左右距离", self._route_lateral))
        self._route_pause = self._seconds_spin(0.8, 0.2, 5.0, 0.1)
        route_settings.addWidget(self._setting_pair("段间等待", self._route_pause))
        route_hint = QLabel("按F8“位移到位保持”切下一段；X+为前，Y+为左。")
        route_hint.setStyleSheet("color:#777;")
        route_settings.addWidget(route_hint)
        route_settings.addStretch(1)
        route_body.addLayout(route_settings, 1)
        route.addLayout(route_body)
        root.addWidget(route_box)

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

    def _route_spin(self, default: float) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(20.0, float(AUTO_MOVE_LIMIT_CM))
        sb.setDecimals(1)
        sb.setSingleStep(10.0)
        sb.setValue(default)
        sb.setSuffix(" cm")
        sb.setMinimumWidth(105)
        return sb

    def _separator(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.Shape.VLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        line.setStyleSheet("color:#C8C8C8;")
        return line

    def _setting_pair(self, label: str, widget: QWidget) -> QWidget:
        wrap = QWidget()
        row = QHBoxLayout(wrap)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        lbl = QLabel(label)
        lbl.setMinimumWidth(70)
        lbl.setStyleSheet("color:#555;")
        row.addWidget(lbl)
        row.addWidget(widget)
        row.addStretch(1)
        return wrap

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
        if cmd_id == CMD_AUTO_MOVE and self._route_active and state in (
            self.STATE_WARN,
            self.STATE_FAIL,
            self.STATE_TIMEOUT,
        ):
            self._route_active = False
            self._route_timer_pending = False
            self._set_route_status(f"巡航中止：{message}", "#C62828")

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
        self._advance_route_on_status(sample)

    def _send_f7(self, cmd: int) -> None:
        if cmd in (AUTO_CMD_TAKEOFF_HOLD, AUTO_CMD_START_LOW_TAKEOFF_LAND) and not self._takeoff_confirm.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "自动起飞前必须勾选安全确认。")
            self.set_ack_state(self.STATE_FAIL, "自动起飞已拦截：未勾选安全确认")
            return
        if cmd in (AUTO_CMD_LAND_ONLY, AUTO_CMD_ABORT_LAND, AUTO_CMD_EMERGENCY_LOCK):
            self._cancel_route("巡航已取消：正在降落/中止/急停")
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
        if cmd == AUTO_MOVE_CMD_STOP:
            self._cancel_route("巡航已取消：手动停止位移")
        self._emit_f9(
            cmd,
            float(self._x.value()),
            float(self._y.value()),
            float(self._z.value()),
            int(self._axis_mode.currentData()),
            f"已发送 F9：{F9_LABELS.get(cmd, f'0x{cmd:02X}')}",
        )

    def _emit_f9(
        self,
        cmd: int,
        x_cm: float,
        y_cm: float,
        z_cm: float,
        axis_mode: int,
        status_text: str,
    ) -> int:
        seq = self._f9_seq
        params = {
            "seq": seq,
            "cmd": cmd,
            "x_cm": float(x_cm),
            "y_cm": float(y_cm),
            "z_cm": float(z_cm),
            "axis_mode": int(axis_mode),
            "flags": 0,
        }
        self._f9_seq = self._next_seq(self._f9_seq)
        self.set_ack_state(self.STATE_WAITING, status_text)
        self.command_send_requested.emit(CMD_AUTO_MOVE, params)
        return seq

    def _build_route_legs(self) -> list[tuple[float, float, float]]:
        forward = float(self._route_forward.value())
        lateral = float(self._route_lateral.value())
        pattern = self._route_pattern.currentData()
        if pattern == "square":
            return [(forward, 0.0, 0.0), (0.0, forward, 0.0), (-forward, 0.0, 0.0), (0.0, -forward, 0.0)]
        if pattern == "front_left":
            return [(forward, 0.0, 0.0), (0.0, lateral, 0.0)]
        if pattern == "front_right":
            return [(forward, 0.0, 0.0), (0.0, -lateral, 0.0)]
        if pattern == "out_back":
            return [(forward, 0.0, 0.0), (-forward, 0.0, 0.0)]
        return [(forward, 0.0, 0.0), (0.0, lateral, 0.0), (-forward, 0.0, 0.0), (0.0, -lateral, 0.0)]

    def _start_route(self) -> None:
        if not self._route_confirm.isChecked():
            self.set_ack_state(self.STATE_FAIL, "开始巡航已拦截：未勾选巡航安全确认")
            self._set_route_status("未勾选安全确认", "#C62828")
            return
        if self._route_active:
            self._set_route_status("巡航已在执行中", "#EF6C00")
            return
        self._route_legs = self._build_route_legs()
        if not self._route_legs:
            self._set_route_status("轨迹为空", "#C62828")
            return
        self._route_active = True
        self._route_index = 0
        self._route_waiting_seq = None
        self._route_timer_pending = False
        self._set_route_status(f"准备发送第1段 / 共{len(self._route_legs)}段", "#B58900")
        self._send_next_route_leg()

    def _stop_route(self) -> None:
        self._route_active = False
        self._route_timer_pending = False
        self._route_waiting_seq = None
        self._set_route_status("已停止巡航，并发送停止位移", "#EF6C00")
        self._emit_f9(
            AUTO_MOVE_CMD_STOP,
            0.0,
            0.0,
            0.0,
            AUTO_MOVE_AXIS_AUTO,
            "已发送 F9：停止巡航/停止位移",
        )

    def _send_next_route_leg(self) -> None:
        self._route_timer_pending = False
        if not self._route_active:
            return
        if self._route_index >= len(self._route_legs):
            self._route_active = False
            self._route_waiting_seq = None
            self._set_route_status("巡航完成：最后一段已到位保持", "#2E7D32")
            return
        x_cm, y_cm, z_cm = self._route_legs[self._route_index]
        leg_no = self._route_index + 1
        seq = self._emit_f9(
            AUTO_MOVE_CMD_START,
            x_cm,
            y_cm,
            z_cm,
            AUTO_MOVE_AXIS_AUTO,
            f"巡航第{leg_no}/{len(self._route_legs)}段：X={x_cm:.0f} Y={y_cm:.0f} Z={z_cm:.0f}",
        )
        self._route_waiting_seq = seq
        self._route_index += 1
        self._set_route_status(
            f"第{leg_no}/{len(self._route_legs)}段执行中，等待到位 seq={seq}",
            "#B58900",
        )

    def _advance_route_on_status(self, sample) -> None:
        if not self._route_active or self._route_waiting_seq is None:
            return
        if sample.error != 0:
            self._route_active = False
            self._route_timer_pending = False
            self._set_route_status(f"巡航中止：{error_label(sample.error)}", "#C62828")
            return
        if sample.last_cmd != CMD_AUTO_MOVE or sample.last_cmd_seq != self._route_waiting_seq:
            return
        if sample.state != AUTO_STATE_MOVE_HOLD or self._route_timer_pending:
            return

        if self._route_index >= len(self._route_legs):
            self._route_active = False
            self._route_waiting_seq = None
            self._set_route_status("巡航完成：闭环最后一段已到位", "#2E7D32")
            return

        self._route_timer_pending = True
        pause_ms = int(round(float(self._route_pause.value()) * 1000.0))
        self._set_route_status(
            f"第{self._route_index}/{len(self._route_legs)}段到位，{float(self._route_pause.value()):.1f}s后下一段",
            "#2E7D32",
        )
        QTimer.singleShot(pause_ms, self._send_next_route_leg)

    def _set_route_status(self, text: str, color: str = "#777") -> None:
        self._route_status.setText(text)
        self._route_status.setStyleSheet(f"color:{color};font-weight:bold;")

    def _cancel_route(self, text: str) -> None:
        if not self._route_active and self._route_waiting_seq is None:
            return
        self._route_active = False
        self._route_timer_pending = False
        self._route_waiting_seq = None
        self._set_route_status(text, "#EF6C00")

    @staticmethod
    def _next_seq(seq: int) -> int:
        seq = (seq + 1) & 0xFFFF
        return 1 if seq == 0 else seq

    def _refresh_buttons(self) -> None:
        for button in self._buttons:
            button.setEnabled(self._linked)


REGISTRY.register(CmdAutoControl())
