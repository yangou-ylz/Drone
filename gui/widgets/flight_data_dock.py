# -*- coding: utf-8 -*-
"""飞行数据面板 Dock（阶段C）：主界面常用数据集中显示。

参考匿名上位机"图二"通用数据区，分三组：
1. 飞行状态：飞行模式(0x06) / 锁定状态(0x06) / 电池电压电流(0x0D)
2. 飞控融合估计：融合高度(0x05) / 附加测高(0x05) / 速度XYZ(0x07)
3. 通用外部传感器：通用位置(0x32) / 通用速度·光流(0x33) / 通用测距·激光(0x34)
   —— 状态文字来自 0x0E 官方状态帧，数值来自对应数据帧；无数据显示 NO。

设计约束：
- 纯显示 Dock，订阅 TelemetryBus 的 typed 样本信号，自身不解码
- 每类数据带"最近更新时刻"，超时(默认2.5s)自动置为 NO / 灰显
- 配色沿用暗色主题，与数字面板风格一致
"""
from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

# 飞行模式映射（与固件 User_Task.c fc_mode_sta 一致）
_MODE_NAMES = {0: "自稳", 1: "定高", 2: "定点", 3: "程控"}

# 0x0E 传感器状态映射（官方手册）: 0无数据/1不可用/2正常/3良好
_STA_NAMES = {0: "无数据", 1: "不可用", 2: "正常", 3: "良好"}
_STA_COLORS = {0: "#888888", 1: "#FF9800", 2: "#4CAF50", 3: "#00E5FF"}

# 数据超时阈值（秒）：超过则显示 NO / 灰显
_STALE_S = 2.5


class _ValueLabel(QLabel):
    """一个数值显示 Label，带"有效/超时"着色。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("NO", parent)
        self.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
        )
        self._ts: float = 0.0
        self.set_no()

    def set_no(self) -> None:
        self.setText("NO")
        self.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
            " color: #777777;"
        )
        self._ts = 0.0

    def set_value(self, text: str, color: str = "#E0E0E0") -> None:
        self.setText(text)
        self.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; font-size: 13px;"
            f" color: {color};"
        )
        self._ts = time.monotonic()

    def check_stale(self, now: float) -> None:
        if self._ts > 0.0 and (now - self._ts) > _STALE_S:
            self.set_no()


class FlightDataDock(QDockWidget):
    """主界面飞行数据面板（飞行状态 / 融合估计 / 外部传感器）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("飞行数据", parent)
        self.setObjectName("FlightDataDock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)

        # 最近一次 0x0E 状态帧（用于给通用传感器行标注状态文字）
        self._mod_g_vel = 0
        self._mod_g_pos = 0
        self._mod_alt_add = 0
        self._mod_ts = 0.0

        body = QWidget()
        vbox = QVBoxLayout(body)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # ---- 组1：飞行状态 ----
        g1 = QGroupBox("飞行状态", body)
        f1 = QFormLayout(g1)
        f1.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_mode = _ValueLabel(g1)
        self._lbl_lock = _ValueLabel(g1)
        self._lbl_volt = _ValueLabel(g1)
        self._lbl_curr = _ValueLabel(g1)
        f1.addRow("飞行模式", self._lbl_mode)
        f1.addRow("锁定状态", self._lbl_lock)
        f1.addRow("电池电压", self._lbl_volt)
        f1.addRow("电池电流", self._lbl_curr)
        vbox.addWidget(g1)

        # ---- 组2：飞控融合估计（IMU 估计，非外部传感器）----
        g2 = QGroupBox("飞控融合估计", body)
        f2 = QFormLayout(g2)
        f2.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_alt_fu = _ValueLabel(g2)
        self._lbl_alt_add = _ValueLabel(g2)
        self._lbl_vx = _ValueLabel(g2)
        self._lbl_vy = _ValueLabel(g2)
        self._lbl_vz = _ValueLabel(g2)
        f2.addRow("融合高度", self._lbl_alt_fu)
        f2.addRow("附加测高", self._lbl_alt_add)
        f2.addRow("速度 X", self._lbl_vx)
        f2.addRow("速度 Y", self._lbl_vy)
        f2.addRow("速度 Z", self._lbl_vz)
        vbox.addWidget(g2)

        # ---- 组3：通用外部传感器（光流/激光等专用传感器）----
        g3 = QGroupBox("通用外部传感器", body)
        f3 = QFormLayout(g3)
        f3.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        self._lbl_gpos = _ValueLabel(g3)      # 0x32 通用位置
        self._lbl_gpos_sta = _ValueLabel(g3)  # 0x0E STA_G_POS
        self._lbl_gvel = _ValueLabel(g3)      # 0x33 通用速度(光流)
        self._lbl_gvel_sta = _ValueLabel(g3)  # 0x0E STA_G_VEL
        self._lbl_gdis = _ValueLabel(g3)      # 0x34 通用测距(激光)
        self._lbl_gdis_sta = _ValueLabel(g3)  # 0x0E STA_ALT_ADD
        f3.addRow("通用位置", self._lbl_gpos)
        f3.addRow("  └ 状态", self._lbl_gpos_sta)
        f3.addRow("通用速度(光流)", self._lbl_gvel)
        f3.addRow("  └ 状态", self._lbl_gvel_sta)
        f3.addRow("通用测距(激光)", self._lbl_gdis)
        f3.addRow("  └ 状态", self._lbl_gdis_sta)
        vbox.addWidget(g3)

        vbox.addStretch(1)
        self.setWidget(body)

        # 超时检查定时器（500ms）
        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._check_stale)
        self._timer.start()

    # =====================================================
    #                   订阅槽（连 TelemetryBus）
    # =====================================================
    @Slot(object)
    def on_flight_mode(self, s) -> None:
        """0x06 飞控运行模式。"""
        name = _MODE_NAMES.get(s.mode, f"模式{s.mode}")
        self._lbl_mode.set_value(f"{name} ({s.mode})")
        if s.locked:
            self._lbl_lock.set_value("已解锁", "#FF5252")   # 解锁=有动力，红色警示
        else:
            self._lbl_lock.set_value("锁定", "#4CAF50")

    @Slot(object)
    def on_battery(self, s) -> None:
        """0x0D 电压电流。"""
        # 低压警示：<10.5V 变红（3S锂电，仅提示，非硬阈值）
        vcolor = "#FF9800" if s.voltage_v < 10.5 else "#E0E0E0"
        self._lbl_volt.set_value(f"{s.voltage_v:.2f} V", vcolor)
        self._lbl_curr.set_value(f"{s.current_a:.2f} A")

    @Slot(object)
    def on_height(self, s) -> None:
        """0x05 高度。"""
        self._lbl_alt_fu.set_value(f"{s.alt_fu_cm} cm")
        self._lbl_alt_add.set_value(f"{s.alt_add_cm} cm")

    @Slot(object)
    def on_velocity(self, s) -> None:
        """0x07 速度（cm/s）。"""
        self._lbl_vx.set_value(f"{s.vx_cmps} cm/s")
        self._lbl_vy.set_value(f"{s.vy_cmps} cm/s")
        self._lbl_vz.set_value(f"{s.vz_cmps} cm/s")

    @Slot(object)
    def on_module_status(self, s) -> None:
        """0x0E 外接模块工作状态：记录并刷新通用传感器状态文字。"""
        self._mod_g_vel = s.sta_g_vel
        self._mod_g_pos = s.sta_g_pos
        self._mod_alt_add = s.sta_alt_add
        self._mod_ts = time.monotonic()
        self._apply_status(self._lbl_gpos_sta, s.sta_g_pos)
        self._apply_status(self._lbl_gvel_sta, s.sta_g_vel)
        self._apply_status(self._lbl_gdis_sta, s.sta_alt_add)

    @Slot(object)
    def on_gen_position(self, s) -> None:
        """0x32 通用位置传感器数据。"""
        parts = []
        parts.append(f"{s.x_cm}" if s.valid_x else "—")
        parts.append(f"{s.y_cm}" if s.valid_y else "—")
        parts.append(f"{s.z_cm}" if s.valid_z else "—")
        if s.valid_x or s.valid_y or s.valid_z:
            self._lbl_gpos.set_value(f"({parts[0]},{parts[1]},{parts[2]}) cm")
        else:
            self._lbl_gpos.set_value("数据无效", "#FF9800")

    @Slot(object)
    def on_gen_velocity(self, s) -> None:
        """0x33 通用速度传感器数据（光流）。"""
        parts = []
        parts.append(f"{s.vx_cmps}" if s.valid_x else "—")
        parts.append(f"{s.vy_cmps}" if s.valid_y else "—")
        parts.append(f"{s.vz_cmps}" if s.valid_z else "—")
        if s.valid_x or s.valid_y or s.valid_z:
            self._lbl_gvel.set_value(f"({parts[0]},{parts[1]},{parts[2]}) cm/s")
        else:
            self._lbl_gvel.set_value("数据无效", "#FF9800")

    @Slot(object)
    def on_gen_distance(self, s) -> None:
        """0x34 通用测距传感器数据（激光/超声）。"""
        if s.valid:
            dir_txt = "水平" if s.direction == 0 else "垂直"
            self._lbl_gdis.set_value(f"{s.distance_cm} cm [{dir_txt}{s.angle}°]")
        else:
            self._lbl_gdis.set_value("数据无效", "#FF9800")

    # =====================================================
    #                    内部
    # =====================================================
    def _apply_status(self, lbl: _ValueLabel, sta: int) -> None:
        name = _STA_NAMES.get(sta, f"?{sta}")
        color = _STA_COLORS.get(sta, "#E0E0E0")
        lbl.set_value(name, color)

    def _check_stale(self) -> None:
        now = time.monotonic()
        for lbl in (
            self._lbl_mode, self._lbl_lock, self._lbl_volt, self._lbl_curr,
            self._lbl_alt_fu, self._lbl_alt_add,
            self._lbl_vx, self._lbl_vy, self._lbl_vz,
            self._lbl_gpos, self._lbl_gpos_sta,
            self._lbl_gvel, self._lbl_gvel_sta,
            self._lbl_gdis, self._lbl_gdis_sta,
        ):
            lbl.check_stale(now)
