# -*- coding: utf-8 -*-
"""GUI-only 自主飞行组合面板。

该面板不新增飞控协议，不直接下发 0xEA。它只是把常用的 F7 起飞/降落
和 F9 相对位移按钮放在同一页，减少飞行测试时来回切换面板。
"""
from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen
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
    AUTO_VEL_CMD_QUERY,
    AUTO_VEL_CMD_SET,
    AUTO_VEL_CMD_STOP,
    AUTO_VEL_LIMIT_CMPS,
    AUTO_YAW_LIMIT_DPS,
    CMD_AUTO_MISSION,
    CMD_AUTO_MOVE,
    CMD_AUTO_VELOCITY,
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
_KEYMAP_FILE = Path(__file__).resolve().parents[1] / "keymaps" / "velocity_keys.json"


class _StickIndicator(QWidget):
    """低速水平速度按键状态显示。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._x = 0.0
        self._y = 0.0
        self.setMinimumSize(150, 150)

    def set_vector(self, x: float, y: float) -> None:
        self._x = max(-1.0, min(1.0, float(x)))
        self._y = max(-1.0, min(1.0, float(y)))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(10, 10, -10, -10)
        side = min(rect.width(), rect.height())
        cx = rect.center().x()
        cy = rect.center().y()
        radius = side * 0.42
        painter.setPen(QPen(QColor("#9E9E9E"), 2))
        painter.setBrush(QColor("#F7F7F7"))
        painter.drawEllipse(int(cx - radius), int(cy - radius), int(radius * 2), int(radius * 2))
        painter.setPen(QPen(QColor("#C0C0C0"), 1))
        painter.drawLine(int(cx - radius), cy, int(cx + radius), cy)
        painter.drawLine(cx, int(cy - radius), cx, int(cy + radius))
        knob_r = max(10, int(side * 0.07))
        kx = cx + self._x * radius
        ky = cy - self._y * radius
        painter.setPen(QPen(QColor("#2E7D32"), 2))
        painter.setBrush(QColor("#66BB6A"))
        painter.drawEllipse(int(kx - knob_r), int(ky - knob_r), knob_r * 2, knob_r * 2)


class _YawIndicator(QWidget):
    """低速 yaw 按键状态显示。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._yaw = 0.0
        self.setMinimumSize(150, 70)

    def set_yaw(self, yaw: float) -> None:
        self._yaw = max(-1.0, min(1.0, float(yaw)))
        self.update()

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self.rect().adjusted(14, 18, -14, -18)
        cy = rect.center().y()
        left = rect.left()
        right = rect.right()
        painter.setPen(QPen(QColor("#9E9E9E"), 4))
        painter.drawLine(left, cy, right, cy)
        painter.setPen(QPen(QColor("#D0D0D0"), 1))
        painter.drawLine((left + right) // 2, cy - 14, (left + right) // 2, cy + 14)
        knob_r = 11
        x = (left + right) / 2.0 + self._yaw * ((right - left) / 2.0)
        painter.setPen(QPen(QColor("#1565C0"), 2))
        painter.setBrush(QColor("#42A5F5"))
        painter.drawEllipse(int(x - knob_r), int(cy - knob_r), knob_r * 2, knob_r * 2)


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
        self._vel_seq = 1
        self._vel_enabled = False
        self._vel_pressed: set[int] = set()
        self._vel_last_sent = (0.0, 0.0, 0.0)
        self._vel_key_map = {
            "forward": int(Qt.Key.Key_Up),
            "back": int(Qt.Key.Key_Down),
            "left": int(Qt.Key.Key_Left),
            "right": int(Qt.Key.Key_Right),
            "yaw_left": int(Qt.Key.Key_A),
            "yaw_right": int(Qt.Key.Key_D),
        }
        self._load_velocity_keymap()
        self._capture_steps: list[tuple[str, str]] = []
        self._capture_index = -1
        self._vel_timer = QTimer(self)
        self._vel_timer.setInterval(100)
        self._vel_timer.timeout.connect(self._send_velocity_from_keys)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
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
        self._add_f7_button(move_buttons, "一键起飞保持", AUTO_CMD_TAKEOFF_HOLD, 2, 0)
        self._add_f7_button(move_buttons, "一键降落", AUTO_CMD_LAND_ONLY, 2, 1)
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
        self._add_f7_button(route_buttons, "一键起飞保持", AUTO_CMD_TAKEOFF_HOLD, 2, 0)
        self._add_f7_button(route_buttons, "一键降落", AUTO_CMD_LAND_ONLY, 2, 1)
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

        vel_box = QGroupBox("键盘低速速度控制")
        vel = QVBoxLayout(vel_box)
        self._vel_confirm = QCheckBox("确认飞机已稳定悬停，允许键盘实时速度控制")
        self._vel_confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        vel.addWidget(self._vel_confirm)

        vel_body = QHBoxLayout()
        vel_vis = QVBoxLayout()
        self._stick = _StickIndicator()
        self._yaw_indicator = _YawIndicator()
        vel_vis.addWidget(self._stick)
        vel_vis.addWidget(self._yaw_indicator)
        vel_body.addLayout(vel_vis, 1)
        vel_body.addWidget(self._separator())

        vel_settings = QVBoxLayout()
        vel_quick = QGridLayout()
        self._add_f7_button(vel_quick, "一键起飞保持", AUTO_CMD_TAKEOFF_HOLD, 0, 0)
        self._add_f7_button(vel_quick, "一键降落", AUTO_CMD_LAND_ONLY, 0, 1)
        vel_settings.addLayout(vel_quick)

        self._btn_vel_enable = QPushButton("启用键盘控制")
        self._btn_vel_enable.setMinimumHeight(32)
        self._btn_vel_enable.setStyleSheet("font-weight:bold;color:#C62828;")
        self._btn_vel_enable.clicked.connect(lambda _checked=False: self._enable_velocity_control())
        vel_settings.addWidget(self._btn_vel_enable)
        self._buttons.append(self._btn_vel_enable)

        self._btn_vel_disable = QPushButton("关闭键盘控制")
        self._btn_vel_disable.setMinimumHeight(32)
        self._btn_vel_disable.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._btn_vel_disable.clicked.connect(lambda _checked=False: self._disable_velocity_control())
        vel_settings.addWidget(self._btn_vel_disable)
        self._buttons.append(self._btn_vel_disable)

        self._btn_vel_capture = QPushButton("按键校准")
        self._btn_vel_capture.setMinimumHeight(32)
        self._btn_vel_capture.clicked.connect(lambda _checked=False: self._start_key_capture())
        vel_settings.addWidget(self._btn_vel_capture)
        self._buttons.append(self._btn_vel_capture)

        self._btn_vel_query = QPushButton("查询速度控制")
        self._btn_vel_query.setMinimumHeight(32)
        self._btn_vel_query.clicked.connect(lambda _checked=False: self._send_velocity_query())
        vel_settings.addWidget(self._btn_vel_query)
        self._buttons.append(self._btn_vel_query)

        self._linear_speed = self._speed_spin(15.0, 1.0, float(AUTO_VEL_LIMIT_CMPS), 1.0, " cm/s")
        vel_settings.addWidget(self._setting_pair("线速度", self._linear_speed))
        self._yaw_speed = self._speed_spin(10.0, 1.0, float(AUTO_YAW_LIMIT_DPS), 1.0, " deg/s")
        vel_settings.addWidget(self._setting_pair("角速度", self._yaw_speed))
        self._vel_values = QLabel("vx=0.0 cm/s  vy=0.0 cm/s  yaw=0.0 deg/s")
        self._vel_values.setStyleSheet("font-weight:bold;color:#555;")
        vel_settings.addWidget(self._vel_values)
        self._key_hint = QLabel("默认：方向键控制前后左右，A/D 控制偏航。点击启用后面板会获取键盘焦点。")
        self._key_hint.setWordWrap(True)
        self._key_hint.setStyleSheet("color:#777;")
        vel_settings.addWidget(self._key_hint)
        vel_settings.addStretch(1)
        vel_body.addLayout(vel_settings, 1)
        vel.addLayout(vel_body)
        root.addWidget(vel_box)

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

    def _speed_spin(
        self,
        default: float,
        low: float,
        high: float,
        step: float,
        suffix: str,
    ) -> StableDoubleSpinBox:
        sb = StableDoubleSpinBox()
        sb.setRange(low, high)
        sb.setDecimals(1)
        sb.setSingleStep(step)
        sb.setValue(default)
        sb.setSuffix(suffix)
        sb.setMinimumWidth(115)
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
        if cmd_id in (CMD_AUTO_MISSION, CMD_AUTO_MOVE, CMD_AUTO_VELOCITY):
            self.set_ack_state(state, message)
        if cmd_id == CMD_AUTO_MOVE and self._route_active and state in (
            self.STATE_WARN,
            self.STATE_FAIL,
            self.STATE_TIMEOUT,
        ):
            self._route_active = False
            self._route_timer_pending = False
            self._set_route_status(f"巡航中止：{message}", "#C62828")
        if cmd_id == CMD_AUTO_VELOCITY and state in (self.STATE_FAIL, self.STATE_TIMEOUT):
            self._disable_velocity_control(send_stop=False, reason=f"速度控制异常：{message}")

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

    def on_panel_deactivated(self, reason: str = "页面切换") -> None:
        """页面切走时只释放键盘速度；位移/巡航必须继续执行，除非用户点停止。"""
        if self._capture_index >= 0:
            self._capture_index = -1
            self._key_hint.setText("按键校准已中断：页面切换。")
            self._key_hint.setStyleSheet("color:#777;")

        if self._vel_enabled or self._vel_timer.isActive() or self._vel_pressed:
            self._disable_velocity_control(
                send_stop=self._linked,
                reason=f"键盘控制已暂停：{reason}",
            )

    def _send_velocity_query(self) -> None:
        self._emit_velocity(AUTO_VEL_CMD_QUERY, 0.0, 0.0, 0.0, "已发送 FA：查询速度控制")

    def _enable_velocity_control(self) -> None:
        if not self._linked:
            self.set_ack_state(self.STATE_FAIL, "串口未连接，不能启用键盘控制")
            return
        if not self._vel_confirm.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "启用键盘速度控制前必须勾选安全确认。")
            self.set_ack_state(self.STATE_FAIL, "键盘控制已拦截：未勾选安全确认")
            return
        self._vel_enabled = True
        self._vel_pressed.clear()
        self._vel_last_sent = (0.0, 0.0, 0.0)
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._key_hint.setText("键盘控制已启用：按住方向键/A/D才发送速度，松开立即归零。")
        self._key_hint.setStyleSheet("color:#2E7D32;font-weight:bold;")
        self._update_velocity_view(0.0, 0.0, 0.0)

    def _disable_velocity_control(self, *, send_stop: bool = True, reason: str = "键盘控制已关闭") -> None:
        self._vel_enabled = False
        self._vel_pressed.clear()
        self._vel_timer.stop()
        self._update_velocity_view(0.0, 0.0, 0.0)
        self._key_hint.setText(reason)
        self._key_hint.setStyleSheet("color:#777;")
        if send_stop and self._linked:
            self._emit_velocity(AUTO_VEL_CMD_STOP, 0.0, 0.0, 0.0, "已发送 FA：停止速度控制")

    def _start_key_capture(self) -> None:
        self._capture_steps = [
            ("forward", "请按：向上箭头"),
            ("back", "请按：向下箭头"),
            ("left", "请按：向左箭头"),
            ("right", "请按：向右箭头"),
            ("yaw_left", "请按：A（左旋）"),
            ("yaw_right", "请按：D（右旋）"),
        ]
        self._capture_index = 0
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        self._key_hint.setText(self._capture_steps[0][1])
        self._key_hint.setStyleSheet("color:#B58900;font-weight:bold;")

    def keyPressEvent(self, event) -> None:  # noqa: N802
        key = int(event.key())
        if event.isAutoRepeat():
            event.accept()
            return
        if self._capture_index >= 0:
            self._capture_key(key)
            event.accept()
            return
        if not self._vel_enabled:
            super().keyPressEvent(event)
            return
        if key in self._vel_key_map.values():
            self._vel_pressed.add(key)
            self._send_velocity_from_keys()
            self._vel_timer.start()
            event.accept()
            return
        super().keyPressEvent(event)

    def keyReleaseEvent(self, event) -> None:  # noqa: N802
        key = int(event.key())
        if event.isAutoRepeat():
            event.accept()
            return
        if key in self._vel_pressed:
            self._vel_pressed.discard(key)
            self._send_velocity_from_keys()
            if not self._vel_pressed:
                self._vel_timer.stop()
            event.accept()
            return
        super().keyReleaseEvent(event)

    def _capture_key(self, key: int) -> None:
        if self._capture_index < 0 or self._capture_index >= len(self._capture_steps):
            return
        action, _prompt = self._capture_steps[self._capture_index]
        self._vel_key_map[action] = int(key)
        self._capture_index += 1
        if self._capture_index >= len(self._capture_steps):
            self._capture_index = -1
            self._key_hint.setText(
                "按键校准完成：启用后按住映射键才输出速度，松开立即归零。"
            )
            self._key_hint.setStyleSheet("color:#2E7D32;font-weight:bold;")
            self._save_velocity_keymap()
            return
        self._key_hint.setText(self._capture_steps[self._capture_index][1])

    def _load_velocity_keymap(self) -> None:
        try:
            data = json.loads(_KEYMAP_FILE.read_text(encoding="utf-8"))
        except Exception:
            return
        for key in self._vel_key_map:
            try:
                value = int(data[key])
            except Exception:
                continue
            if value > 0:
                self._vel_key_map[key] = value

    def _save_velocity_keymap(self) -> None:
        try:
            _KEYMAP_FILE.parent.mkdir(parents=True, exist_ok=True)
            _KEYMAP_FILE.write_text(
                json.dumps(self._vel_key_map, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            self._key_hint.setText("按键已捕获，但保存失败；本次运行仍然生效。")
            self._key_hint.setStyleSheet("color:#EF6C00;font-weight:bold;")

    def _velocity_from_keys(self) -> tuple[float, float, float]:
        vx_axis = 0
        vy_axis = 0
        yaw_axis = 0
        if self._vel_key_map["forward"] in self._vel_pressed:
            vx_axis += 1
        if self._vel_key_map["back"] in self._vel_pressed:
            vx_axis -= 1
        if self._vel_key_map["left"] in self._vel_pressed:
            vy_axis += 1
        if self._vel_key_map["right"] in self._vel_pressed:
            vy_axis -= 1
        if self._vel_key_map["yaw_left"] in self._vel_pressed:
            yaw_axis += 1
        if self._vel_key_map["yaw_right"] in self._vel_pressed:
            yaw_axis -= 1

        linear = float(self._linear_speed.value())
        if vx_axis != 0 and vy_axis != 0:
            linear *= 0.7071
        vx = float(vx_axis) * linear
        vy = float(vy_axis) * linear
        yaw = float(yaw_axis) * float(self._yaw_speed.value())
        return vx, vy, yaw

    def _send_velocity_from_keys(self) -> None:
        if not self._vel_enabled:
            return
        vx, vy, yaw = self._velocity_from_keys()
        self._update_velocity_view(vx, vy, yaw)
        if vx != 0.0 or vy != 0.0 or yaw != 0.0:
            self._cancel_route("巡航已取消：键盘速度控制接管")
        if (vx, vy, yaw) == self._vel_last_sent and (vx, vy, yaw) == (0.0, 0.0, 0.0):
            return
        self._vel_last_sent = (vx, vy, yaw)
        self._emit_velocity(AUTO_VEL_CMD_SET, vx, vy, yaw, "已发送 FA：键盘速度")

    def _update_velocity_view(self, vx: float, vy: float, yaw: float) -> None:
        linear = max(1.0, float(self._linear_speed.value()))
        yaw_scale = max(1.0, float(self._yaw_speed.value()))
        # GUI 视觉按机体系 FLU 显示：X+ 向前、Y+ 向机头左、yaw+ 左旋。
        # 屏幕坐标 X+ 在右侧，所以水平和偏航指示需要取反；协议下发值不变。
        self._stick.set_vector(-vy / linear, vx / linear)
        self._yaw_indicator.set_yaw(-yaw / yaw_scale)
        self._vel_values.setText(f"vx={vx:.1f} cm/s  vy={vy:.1f} cm/s  yaw={yaw:.1f} deg/s")

    def _emit_velocity(self, cmd: int, vx: float, vy: float, yaw: float, status_text: str) -> int:
        seq = self._vel_seq
        params = {
            "seq": seq,
            "cmd": cmd,
            "vx_cmps": float(vx),
            "vy_cmps": float(vy),
            "yaw_dps": float(yaw),
            "flags": 0,
            "_silent": cmd == AUTO_VEL_CMD_SET,
        }
        self._vel_seq = self._next_seq(self._vel_seq)
        self.set_ack_state(self.STATE_WAITING, status_text)
        self.command_send_requested.emit(CMD_AUTO_VELOCITY, params)
        return seq

    @staticmethod
    def _next_seq(seq: int) -> int:
        seq = (seq + 1) & 0xFFFF
        return 1 if seq == 0 else seq

    def _refresh_buttons(self) -> None:
        for button in self._buttons:
            button.setEnabled(self._linked)


REGISTRY.register(CmdAutoControl())
