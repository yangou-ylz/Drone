# -*- coding: utf-8 -*-
"""占位命令 —— 阶段 E 给"飞行控制""模式切换"两类预留 UI 槽位。

目的：演示 :class:`Command` 的扩展点；让操作员**在 UI 里看见**这些功能
"已规划但固件尚未实现"，避免误以为软件不支持。

设计要点：
- 占位 cmd_id 故意用 ``0xE1`` / ``0xE2``（凌霄上行帧未占用区间，**仅 UI 自用**，
  绝对不会真正下发到飞控；面板里发送按钮永久禁用）；
- :meth:`build_frame` 抛 :class:`NotImplementedError`，做最后一道防线；
- :meth:`parse_ack` 始终返回 ``None``（占位命令不期望任何回执）；
- 面板提供清晰中文文案 + 灰色禁用按钮，便于将来直接替换。

扩展指南（真要实现某个占位命令时）：
1. 新建 ``gui/commands/cmd_xxx.py``，写一个真实的 :class:`Command` 子类（参考
   :mod:`gui.commands.cmd_f1` / :mod:`gui.commands.cmd_f2`）；
2. 在 ``gui/commands/__init__.py`` 里 ``from . import cmd_xxx``；
3. **删除**本文件里对应那条占位的 ``REGISTRY.register(...)``；
4. UI 自动出现新命令。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ..services.command_registry import (
    AckResult,
    Command,
    CommandPanelBase,
    REGISTRY,
)


# ---------------- 占位面板（共享） ----------------

class _PlaceholderPanel(CommandPanelBase):
    """通用占位面板：信息文本 + 永久禁用的发送按钮。"""

    send_requested = Signal(dict)

    def __init__(self, command_name: str, planned_feature: str,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        title = QLabel(f"{command_name}（开发中）")
        title.setStyleSheet("font-size: 14pt; font-weight: bold; color: #555;")
        root.addWidget(title)

        info = QLabel(
            f"该功能已在产品路线图中预留：{planned_feature}\n\n"
            f"当前固件尚未实现对应的上行帧；UI 槽位保留以确保后续扩展时"
            f"无需调整主界面框架。"
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #666;")
        root.addWidget(info)

        # 状态行（套用基类约定的三态接口；占位场景永远 IDLE）
        st_row = QHBoxLayout()
        self._lamp = QLabel("●")
        self._lamp.setStyleSheet("color: #888; font-size: 16pt;")
        st_row.addWidget(self._lamp)
        self._status = QLabel("固件未实现")
        self._status.setStyleSheet("color: #888;")
        st_row.addWidget(self._status)
        st_row.addStretch(1)
        root.addLayout(st_row)

        # 永久禁用的发送按钮：让用户看到入口，但点不下去
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn = QPushButton("发送（不可用）")
        self._btn.setEnabled(False)
        self._btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self._btn.setToolTip("固件尚未实现该命令")
        btn_row.addWidget(self._btn)
        root.addLayout(btn_row)
        root.addStretch(1)

    def set_enabled_for_link(self, linked: bool) -> None:
        # 占位面板不随串口状态切换，永远禁用
        self._btn.setEnabled(False)

    def set_ack_state(self, state: str, message: str = "") -> None:
        # 占位面板不期望接到任何回执，故忽略；保持 idle 文案
        return


# ---------------- 占位命令本体 ----------------

class _PlaceholderCommand(Command):
    """所有占位命令的共同行为。"""

    # 子类必须覆盖
    cmd_id: int = 0
    name: str = ""
    category: str = ""
    description: str = ""
    requires_confirm: bool = False
    ack_timeout_ms: int = 0  # 占位 → 不等回执

    # 子类填充
    planned_feature: str = ""

    def build_frame(self, params: dict) -> bytes:
        raise NotImplementedError(
            f"{self.name} 是占位命令，固件尚未实现，禁止发送"
        )

    def parse_ack(self, text: str):  # -> AckResult | None
        # 占位命令绝不认领任何回执
        return None

    def create_panel(self, parent: QWidget | None = None) -> CommandPanelBase:
        return _PlaceholderPanel(self.name, self.planned_feature, parent)


class _FlightCtrlPlaceholder(_PlaceholderCommand):
    cmd_id = 0xE1
    name = "飞行控制（占位）"
    category = "飞行控制（占位）"
    description = "未来用于程控模式下的位置/速度直发指令"
    planned_feature = (
        "·  程控模式 (mode=3) 下直发目标 XYZ 速度 / 位置；\n"
        "·  实时频率 50 Hz；\n"
        "·  超时降级到悬停（飞控侧保护）。"
    )


class _ModeSwitchPlaceholder(_PlaceholderCommand):
    cmd_id = 0xE2
    name = "模式切换（占位）"
    category = "模式切换（占位）"
    description = "未来用于上位机请求飞控切换工作模式（0/1/2/3）"
    planned_feature = (
        "·  上位机请求切换到指定模式；\n"
        "·  仅作建议；最终模式由 AUX1 通道 + 飞控安全策略仲裁。"
    )


# ---------------- 注册 ----------------

REGISTRY.register(_FlightCtrlPlaceholder())
REGISTRY.register(_ModeSwitchPlaceholder())
