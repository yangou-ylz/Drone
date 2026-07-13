# -*- coding: utf-8 -*-
"""CommandPanel —— 命令选择 + 面板切换容器。

布局：
    ┌──────────────────────────────────────────────────────┐
    │ 分类: [调试 ▼]   命令: [链路验证 F1 ▼]               │
    ├──────────────────────────────────────────────────────┤
    │                                                      │
    │     （当前命令的输入面板，QStackedWidget）           │
    │                                                      │
    └──────────────────────────────────────────────────────┘

从 :data:`REGISTRY` 遍历命令构建分组下拉，**不需要为新命令改本文件**。

输出统一信号 :attr:`command_send_requested(cmd_id, params)`，
由 MainWindow 负责（必要时弹确认）→ 组帧 → 入队发送 → 登记 AckMatcher。
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..services.command_registry import REGISTRY, Command, CommandPanelBase


class CommandPanel(QWidget):
    """命令面板容器。"""

    command_send_requested = Signal(int, dict)   # cmd_id, params

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # cmd_id -> 已创建的面板（懒构造）
        self._panels: dict[int, CommandPanelBase] = {}
        # 在 QStackedWidget 中 cmd_id -> index
        self._panel_index: dict[int, int] = {}
        self._linked = False
        self._build_ui()
        self._populate()

    # ---- 公共 ----
    def set_enabled_for_link(self, linked: bool) -> None:
        """串口连接状态变化时由主窗口调用，向所有已构造的面板广播。"""
        self._linked = bool(linked)
        for panel in self._panels.values():
            try:
                panel.set_enabled_for_link(self._linked)
            except Exception:
                pass

    def set_ack_state(self, cmd_id: int, state: str, message: str = "") -> None:
        """按 cmd_id 路由三态反馈到对应面板（面板未构造则忽略）。"""
        panel = self._panels.get(cmd_id)
        if panel is None:
            return
        try:
            panel.set_ack_state(state, message)
        except Exception:
            pass

    def current_command(self) -> Command | None:
        cid = self._cmd_combo.currentData()
        return REGISTRY.get(cid) if isinstance(cid, int) else None

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(QLabel("分类："))
        self._cat_combo = QComboBox()
        self._cat_combo.setMinimumWidth(120)
        self._cat_combo.currentTextChanged.connect(self._on_category_changed)
        top.addWidget(self._cat_combo)

        top.addSpacing(12)
        top.addWidget(QLabel("命令："))
        self._cmd_combo = QComboBox()
        self._cmd_combo.setMinimumWidth(220)
        self._cmd_combo.currentIndexChanged.connect(self._on_command_changed)
        top.addWidget(self._cmd_combo)

        top.addStretch(1)
        root.addLayout(top)

        self._stack = QStackedWidget()
        root.addWidget(self._stack, 1)

    def _populate(self) -> None:
        self._cat_combo.blockSignals(True)
        for cat in REGISTRY.categories():
            self._cat_combo.addItem(cat)
        self._cat_combo.blockSignals(False)
        # 触发首个分类填充命令下拉
        if self._cat_combo.count() > 0:
            self._on_category_changed(self._cat_combo.currentText())

    # ---- 槽 ----
    def _on_category_changed(self, category: str) -> None:
        self._cmd_combo.blockSignals(True)
        self._cmd_combo.clear()
        for cmd in REGISTRY.in_category(category):
            self._cmd_combo.addItem(cmd.name, cmd.cmd_id)
        self._cmd_combo.blockSignals(False)
        if self._cmd_combo.count() > 0:
            self._on_command_changed(0)

    def _on_command_changed(self, _idx: int) -> None:
        cmd = self.current_command()
        if cmd is None:
            return
        # 懒构造面板并加入栈
        if cmd.cmd_id not in self._panels:
            panel = cmd.create_panel(self)
            # 桥接面板的 send_requested → 本控件 command_send_requested
            try:
                panel.send_requested.connect(lambda p, cid=cmd.cmd_id: self.command_send_requested.emit(cid, dict(p)))
            except AttributeError:
                # 面板未定义 send_requested 信号，给出友好错误
                print(f"[CommandPanel] 命令 0x{cmd.cmd_id:02X} 的面板缺少 send_requested 信号")
            self._panels[cmd.cmd_id] = panel
            self._panel_index[cmd.cmd_id] = self._stack.addWidget(panel)
            panel.set_enabled_for_link(self._linked)
        self._stack.setCurrentIndex(self._panel_index[cmd.cmd_id])
