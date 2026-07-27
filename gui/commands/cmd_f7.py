# -*- coding: utf-8 -*-
"""0xF7 自主任务控制命令。

第一阶段只做 GUI → STM32 任务状态机触发：
- 查询、预检、请求定点、干运行；
- 正式低高度起降需要安全勾选，且强制 no_xy_motion；
- 中止降落/强制上锁用于现场兜底。
"""
from __future__ import annotations

import re

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    ADDR_BROADCAST,
    AUTO_CMD_ABORT_LAND,
    AUTO_CMD_CLEAR_ERROR,
    AUTO_CMD_DRYRUN_TAKEOFF_LAND,
    AUTO_CMD_EMERGENCY_LOCK,
    AUTO_CMD_PRECHECK,
    AUTO_CMD_QUERY_STATUS,
    AUTO_CMD_LOCK_RC,
    AUTO_CMD_RELEASE_RC,
    AUTO_CMD_REQUEST_MODE2,
    AUTO_CMD_START_LOW_TAKEOFF_LAND,
    AUTO_FLAG_NO_XY_MOTION,
    AUTO_SAFETY_KEY,
    build_f7_auto_cmd,
)
from ..services.command_registry import (
    REGISTRY,
    AckResult,
    Command,
    CommandPanelBase,
)
from ..services.auto_mission_labels import (
    error_label,
    flag_summary,
    format_auto_a0_text,
    rc_control_label,
    rc_input_color,
    rc_input_label,
    state_label,
)
from ..services.log_service import LogLevel


_AUTO_ACK = re.compile(r"^AUTO\s+(.+)$", re.I)

_CMD_LABELS = {
    AUTO_CMD_QUERY_STATUS: "查询状态",
    AUTO_CMD_PRECHECK: "预检",
    AUTO_CMD_REQUEST_MODE2: "请求定点",
    AUTO_CMD_DRYRUN_TAKEOFF_LAND: "起降干运行",
    AUTO_CMD_START_LOW_TAKEOFF_LAND: "正式低高度起降",
    AUTO_CMD_ABORT_LAND: "中止并降落",
    AUTO_CMD_EMERGENCY_LOCK: "强制上锁",
    AUTO_CMD_CLEAR_ERROR: "清错误",
    AUTO_CMD_LOCK_RC: "锁定遥控权",
    AUTO_CMD_RELEASE_RC: "释放遥控权",
}

_KEY_CMDS = {
    AUTO_CMD_REQUEST_MODE2,
    AUTO_CMD_DRYRUN_TAKEOFF_LAND,
    AUTO_CMD_START_LOW_TAKEOFF_LAND,
    AUTO_CMD_LOCK_RC,
    AUTO_CMD_RELEASE_RC,
}

class CmdF7(Command):
    cmd_id = 0xF7
    name = "自主任务 F7"
    category = "自主"
    description = "GUI触发STM32定点模式自主任务状态机；当前阶段不接XY速度控制。"
    requires_confirm = False
    ack_timeout_ms = 1800

    def build_frame(self, params: dict) -> bytes:
        cmd = int(params["cmd"]) & 0xFF
        seq = int(params["seq"]) & 0xFFFF
        safety_key = AUTO_SAFETY_KEY if cmd in _KEY_CMDS else int(params.get("safety_key", 0))
        return build_f7_auto_cmd(
            ADDR_BROADCAST,
            seq,
            cmd,
            safety_key=safety_key,
            height_cm=int(params.get("height_cm", 40)),
            hold_ms=int(params.get("hold_ms", 3000)),
            flags=int(params.get("flags", AUTO_FLAG_NO_XY_MOTION)),
            timeout_ms=int(params.get("timeout_ms", 30000)),
        )

    def parse_ack(self, text: str) -> AckResult | None:
        s = text.strip()
        m = _AUTO_ACK.match(s)
        if not m:
            return None
        body = m.group(1).strip()
        upper = body.upper()
        translated = format_auto_a0_text(f"AUTO {body}")
        if upper.startswith("ERR") or "FAIL" in upper or "DENY" in upper:
            return AckResult(False, LogLevel.ERROR, f"F7 失败：{translated}")
        if upper.startswith("DUP"):
            return AckResult(True, LogLevel.WARN, f"F7 重复序号：{translated}")
        if upper.startswith("EMERGENCY"):
            return AckResult(False, LogLevel.ERROR, f"F7 急停：{translated}")
        return AckResult(True, LogLevel.INFO, f"F7 OK：{translated}")

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return F7Panel(self, parent)

    def describe_params(self, params: dict) -> str:
        cmd = int(params.get("cmd", -1))
        return (
            f"{_CMD_LABELS.get(cmd, f'cmd=0x{cmd:02X}')}, "
            f"seq={params.get('seq')}, h={params.get('height_cm')}cm, "
            f"hold={params.get('hold_ms')}ms, timeout={params.get('timeout_ms')}ms"
        )


class F7Panel(CommandPanelBase):
    send_requested = Signal(dict)

    def __init__(self, cmd: CmdF7, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cmd = cmd
        self._linked = False
        self._last_params: dict | None = None
        self._seq = 1
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        title = QLabel(
            f"<b>{self._cmd.name}</b>  &nbsp;<span style='color:#888;'>CMD=0xF7</span>"
            "  &nbsp;<span style='color:#C62828;'>[安全敏感]</span>"
        )
        root.addWidget(title)

        desc = QLabel(
            "当前阶段：GUI只触发状态机；STM32使用官方一键定点起降命令；"
            "不写XY速度、不依赖树莓派SLAM。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("color:#666;")
        root.addWidget(desc)

        param_box = QGroupBox("参数")
        grid = QGridLayout(param_box)
        lbl_height = QLabel("一键起飞高度")
        lbl_height.setToolTip("正式低高度起降时传给凌霄 IMU 官方 OneKey_Takeoff(height_cm) 的高度参数。")
        grid.addWidget(lbl_height, 0, 0)
        self._height = QSpinBox()
        self._height.setRange(30, 80)
        self._height.setValue(40)
        self._height.setSuffix(" cm")
        self._height.setToolTip("安全限幅 30~80cm；当前阶段建议先用默认 40cm，无桨测试通过前不要有桨起飞。")
        grid.addWidget(self._height, 0, 1)

        grid.addWidget(QLabel("悬停时间"), 0, 2)
        self._hold = QSpinBox()
        self._hold.setRange(1000, 5000)
        self._hold.setSingleStep(500)
        self._hold.setValue(3000)
        self._hold.setSuffix(" ms")
        grid.addWidget(self._hold, 0, 3)

        grid.addWidget(QLabel("总超时"), 1, 0)
        self._timeout = QSpinBox()
        self._timeout.setRange(5000, 60000)
        self._timeout.setSingleStep(1000)
        self._timeout.setValue(30000)
        self._timeout.setSuffix(" ms")
        grid.addWidget(self._timeout, 1, 1)

        self._no_xy = QCheckBox("强制 no_xy_motion")
        self._no_xy.setChecked(True)
        self._no_xy.setEnabled(False)
        grid.addWidget(self._no_xy, 1, 2, 1, 2)
        root.addWidget(param_box)

        cmd_box = QGroupBox("阶段命令")
        cmd_grid = QGridLayout(cmd_box)
        self._buttons: list[QPushButton] = []
        self._add_button(cmd_grid, "查询状态", AUTO_CMD_QUERY_STATUS, 0, 0)
        self._add_button(cmd_grid, "预检", AUTO_CMD_PRECHECK, 0, 1)
        self._add_button(cmd_grid, "请求定点", AUTO_CMD_REQUEST_MODE2, 0, 2)
        self._add_button(cmd_grid, "起降干运行", AUTO_CMD_DRYRUN_TAKEOFF_LAND, 1, 0)
        self._btn_start = self._add_button(
            cmd_grid, "正式低高度起降", AUTO_CMD_START_LOW_TAKEOFF_LAND, 1, 1
        )
        self._btn_start.setStyleSheet("font-weight:bold;color:#C62828;")
        self._add_button(cmd_grid, "中止并降落", AUTO_CMD_ABORT_LAND, 1, 2)
        self._btn_emergency = self._add_button(
            cmd_grid, "强制上锁", AUTO_CMD_EMERGENCY_LOCK, 2, 0
        )
        self._btn_emergency.setStyleSheet("font-weight:bold;background:#C62828;color:white;")
        self._btn_lock_rc = self._add_button(cmd_grid, "锁定遥控权", AUTO_CMD_LOCK_RC, 2, 1)
        self._btn_lock_rc.setStyleSheet("font-weight:bold;color:#2E7D32;")
        self._btn_release_rc = self._add_button(cmd_grid, "释放遥控权", AUTO_CMD_RELEASE_RC, 2, 2)
        self._btn_release_rc.setStyleSheet("font-weight:bold;color:#EF6C00;")
        self._add_button(cmd_grid, "清错误回空闲", AUTO_CMD_CLEAR_ERROR, 3, 2)
        root.addWidget(cmd_box)

        self._confirm = QCheckBox("我已确认：桨叶/场地/人员安全，允许正式低高度起降")
        self._confirm.setStyleSheet("color:#C62828;font-weight:bold;")
        root.addWidget(self._confirm)

        live_box = QGroupBox("实时状态（0xF8）")
        live_grid = QGridLayout(live_box)
        live_grid.setHorizontalSpacing(12)
        live_grid.setVerticalSpacing(6)
        self._live_labels: dict[str, QLabel] = {}
        self._add_live_field(live_grid, "状态", "state", 0, 0)
        self._add_live_field(live_grid, "错误", "error", 0, 2)
        self._add_live_field(live_grid, "模式", "mode", 1, 0)
        self._add_live_field(live_grid, "解锁", "unlock", 1, 2)
        self._add_live_field(live_grid, "电压", "voltage", 2, 0)
        self._add_live_field(live_grid, "高度", "alt", 2, 2)
        self._add_live_field(live_grid, "外部速度", "ext_vel", 3, 0)
        self._add_live_field(live_grid, "外部测高", "ext_alt", 3, 2)
        self._add_live_field(live_grid, "F5年龄", "f5_age", 4, 0)
        self._add_live_field(live_grid, "计数", "counts", 4, 2)
        self._add_live_field(live_grid, "RC控制权", "rc_lockout", 5, 0)
        self._add_live_field(live_grid, "遥控有效性", "rc_input", 5, 2)
        self._add_live_field(live_grid, "状态标志", "flags", 6, 0)
        self._set_all_live_waiting()
        root.addWidget(live_box)

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

    def _add_live_field(
        self, grid: QGridLayout, label: str, key: str, row: int, col: int
    ) -> None:
        name = QLabel(label)
        name.setStyleSheet("color:#666;")
        value = QLabel("--")
        value.setMinimumWidth(86)
        value.setStyleSheet("font-weight:bold;color:#555;")
        grid.addWidget(name, row, col)
        grid.addWidget(value, row, col + 1)
        self._live_labels[key] = value

    def _set_live(self, key: str, text: str, color: str = "#333", tooltip: str | None = None) -> None:
        lbl = self._live_labels.get(key)
        if lbl is None:
            return
        lbl.setText(text)
        lbl.setToolTip(tooltip or (text if len(text) > 14 else ""))
        lbl.setStyleSheet(f"font-weight:bold;color:{color};")

    def _set_all_live_waiting(self) -> None:
        for key in self._live_labels:
            self._set_live(key, "等待0xF8", "#777")

    def _add_button(self, grid: QGridLayout, text: str, cmd: int, row: int, col: int) -> QPushButton:
        btn = QPushButton(text)
        btn.setMinimumHeight(34)
        btn.clicked.connect(lambda _checked=False, c=cmd: self._send_cmd(c))
        grid.addWidget(btn, row, col)
        self._buttons.append(btn)
        return btn

    def set_enabled_for_link(self, linked: bool) -> None:
        self._linked = bool(linked)
        self._refresh_buttons()
        if linked:
            self.set_ack_state(self.STATE_IDLE, "就绪。先查询/预检/干运行，再正式起降。")
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

    def on_auto_mission_status(self, sample) -> None:
        error_ok = sample.error == 0
        mode_ok = sample.mode == 2
        volt_ok = bool(sample.flags & 0x0001)
        f5_age = "--" if sample.f5_age_ms >= 65535 else f"{sample.f5_age_ms} ms"
        flags = flag_summary(sample.flags, include_hex=True)

        self._set_live("state", state_label(sample.state), "#2E7D32" if error_ok else "#C62828")
        self._set_live("error", error_label(sample.error), "#2E7D32" if error_ok else "#C62828")
        self._set_live("mode", "定点Mode2" if mode_ok else f"Mode{sample.mode}",
                       "#2E7D32" if mode_ok else "#EF6C00")
        self._set_live("unlock", "已解锁" if sample.unlock else "已上锁",
                       "#EF6C00" if sample.unlock else "#2E7D32")
        self._set_live("voltage", f"{sample.voltage_v:.2f} V",
                       "#2E7D32" if volt_ok else "#C62828")
        self._set_live("alt", f"{sample.alt_cm} cm", "#333")
        self._set_live("ext_vel", "正常" if sample.ext_vel_ok else "无效",
                       "#2E7D32" if sample.ext_vel_ok else "#C62828")
        self._set_live("ext_alt", "正常" if sample.ext_alt_ok else "无效",
                       "#2E7D32" if sample.ext_alt_ok else "#C62828")
        self._set_live("f5_age", f5_age, "#555" if sample.f5_age_ms >= 65535 else "#2E7D32")
        self._set_live("counts", f"F7={sample.rx_f7_cnt} 错={sample.err_cnt}",
                       "#2E7D32" if sample.err_cnt == 0 else "#EF6C00")
        self._set_live("rc_lockout", rc_control_label(sample),
                       "#2E7D32" if sample.rc_lockout else "#EF6C00")
        self._set_live("rc_input", rc_input_label(sample), rc_input_color(sample))
        self._set_live("flags", flags, "#2E7D32" if error_ok else "#C62828", tooltip=flags)

    def _send_cmd(self, cmd: int) -> None:
        if cmd == AUTO_CMD_START_LOW_TAKEOFF_LAND and not self._confirm.isChecked():
            QMessageBox.warning(self, "安全确认缺失", "正式低高度起降前必须勾选安全确认。")
            self.set_ack_state(self.STATE_FAIL, "正式起降已拦截：未勾选安全确认")
            return
        params = {
            "seq": self._seq,
            "cmd": cmd,
            "height_cm": int(self._height.value()),
            "hold_ms": int(self._hold.value()),
            "flags": AUTO_FLAG_NO_XY_MOTION,
            "timeout_ms": int(self._timeout.value()),
        }
        self._seq = (self._seq + 1) & 0xFFFF
        if self._seq == 0:
            self._seq = 1
        self._last_params = dict(params)
        self.send_requested.emit(params)

    def _refresh_buttons(self) -> None:
        for btn in self._buttons:
            btn.setEnabled(self._linked)


REGISTRY.register(CmdF7())
