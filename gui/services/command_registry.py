# -*- coding: utf-8 -*-
"""CommandRegistry —— 命令注册中心。

设计目标：**新增一个上行命令 = 加一个 cmd_xxx.py + 在 commands/__init__.py 注册一行**。
框架代码（命令面板、AckMatcher、主窗口）零修改。

核心抽象：
- :class:`AckResult`：飞控对一条命令的回执结果（OK/限幅/拒绝），驱动日志着色和报警等级。
- :class:`Command`：命令描述符（ABC），子类提供 build_frame / parse_ack / 面板类。
- :class:`CommandRegistry`：进程内单例，按 cmd_id 索引；命令面板从中遍历构建分组下拉。

约束：
- `Command` 实例必须无状态（参数都从面板的 send_requested 字典里来）；
- `parse_ack` 必须只在确认是本命令的回执时返回 AckResult，否则返回 None，避免误抢匹配。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable

from PySide6.QtWidgets import QWidget

from .log_service import LogLevel


@dataclass(frozen=True)
class AckResult:
    """命令回执解析结果。"""
    ok: bool             # True=成功（或可恢复），False=被拒绝
    level: LogLevel      # 日志等级，决定颜色与是否报警
    message: str         # 日志展示用文案，例如 "F1: X=1234 Y=-4562"


class Command(ABC):
    """命令抽象基类。每个 cmd_xxx.py 实现一个具体 Command。"""

    # ---- 子类需覆盖的元信息 ----
    cmd_id: int = 0
    name: str = ""               # 中文展示名，如 "链路验证 F1"
    category: str = "调试"        # 命令面板的分组
    description: str = ""        # 鼠标悬停提示
    requires_confirm: bool = False
    ack_timeout_ms: int = 1500   # 回执超时；0 表示不等回执

    # ---- 子类必须实现 ----
    @abstractmethod
    def build_frame(self, params: dict) -> bytes:
        """根据面板参数构建完整数据帧（含帧头/校验）。"""

    @abstractmethod
    def parse_ack(self, text: str) -> AckResult | None:
        """从一条 0xA0 字符串识别本命令的回执；不是本命令的回执返回 None。"""

    @abstractmethod
    def create_panel(self, parent: QWidget | None = None) -> "CommandPanelBase":
        """构造该命令的输入面板。"""

    # ---- 辅助 ----
    def describe_params(self, params: dict) -> str:
        """日志中描述本次发送的参数，子类可覆盖以美化。"""
        return ", ".join(f"{k}={v}" for k, v in params.items())


class CommandPanelBase(QWidget):
    """所有命令面板的基类（占位类型 hint，实际继承在 cmd_xxx.py 内）。

    子类约定：
    - 提供 Qt 信号 ``send_requested(dict)``，参数为 build_frame 所需 kwargs；
    - 提供方法 :meth:`set_enabled_for_link(bool)`，串口未连接时禁用发送按钮；
    - 提供方法 :meth:`set_ack_state(state, message)`，接收三态反馈
      （state 取值：idle/waiting/ok/warn/fail/timeout）；
    - 可选：保留 ``last_params``，配合 "重发" 按钮。

    本基类不强行约束信号定义（Qt 信号必须在 QObject 类体中声明），
    具体子类自行 `from PySide6.QtCore import Signal` 并定义 `send_requested = Signal(dict)`。
    """

    # 三态反馈状态字符串常量（子类可复用，也可直接传字符串）
    STATE_IDLE = "idle"
    STATE_WAITING = "waiting"
    STATE_OK = "ok"
    STATE_WARN = "warn"     # 例如 CLP（限幅）
    STATE_FAIL = "fail"     # 例如 UNK（未知 ID）
    STATE_TIMEOUT = "timeout"

    def set_enabled_for_link(self, linked: bool) -> None:   # pragma: no cover - 子类覆盖
        """串口连接状态变化时由 MainWindow 调用。默认空实现。"""

    def set_ack_state(self, state: str, message: str = "") -> None:  # pragma: no cover
        """三态反馈入口；默认空实现，子类覆盖以更新状态灯。

        :param state: STATE_IDLE / STATE_WAITING / STATE_OK / STATE_WARN /
                      STATE_FAIL / STATE_TIMEOUT
        :param message: 补充文本，例如 "X=1234 Y=-4562" 或 "超时 1500ms"
        """


class _CommandRegistry:
    """进程内单例。模块底部用 :data:`REGISTRY` 暴露。"""

    def __init__(self) -> None:
        self._by_id: dict[int, Command] = {}
        self._order: list[int] = []   # 注册顺序，保持下拉栏稳定

    def register(self, command: Command) -> None:
        """注册命令。重复注册同 cmd_id 抛 ValueError。"""
        if not isinstance(command, Command):
            raise TypeError(f"register 需要 Command 实例，实际：{type(command)!r}")
        if command.cmd_id in self._by_id:
            raise ValueError(f"cmd_id 0x{command.cmd_id:02X} 已注册：{self._by_id[command.cmd_id].name}")
        self._by_id[command.cmd_id] = command
        self._order.append(command.cmd_id)

    def get(self, cmd_id: int) -> Command | None:
        return self._by_id.get(cmd_id)

    def all(self) -> Iterable[Command]:
        """按注册顺序返回所有命令。"""
        for cid in self._order:
            yield self._by_id[cid]

    def categories(self) -> list[str]:
        """所有出现过的分组（保持首次出现顺序）。"""
        seen: list[str] = []
        for c in self.all():
            if c.category not in seen:
                seen.append(c.category)
        return seen

    def in_category(self, category: str) -> list[Command]:
        return [c for c in self.all() if c.category == category]

    def clear(self) -> None:
        """仅供测试使用。"""
        self._by_id.clear()
        self._order.clear()


REGISTRY = _CommandRegistry()
