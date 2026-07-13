# -*- coding: utf-8 -*-
"""AckMatcher —— 发送→回执匹配器，含超时报警。

工作流程：
1. UI 通过 :meth:`track` 登记一次发送（携带 Command 实例和描述文本）；
2. 拿到 ``token`` 后调用 SerialWorker 发送实际字节；
3. 每条入站 0xA0 文本由 MainWindow 转交 :meth:`handle_text`，本类按 FIFO 顺序
   对挂起请求依次 ``parse_ack``，**首次命中即结清**；
4. 超时由 QTimer 触发，发 :attr:`request_timeout` 信号；用户可手动点"重发"按钮。

设计原则：
- **不自动重发**（用户规则）；
- **不跨命令匹配**：每次只让本命令的 parse_ack 看；这样多个命令同时挂起也不会互相抢；
- 命中 / 超时 / 取消均会从挂起表移除；UI 重发就生成新 token；
- 全部 QTimer 创建在主线程（本对象必须 moveToThread 到主线程）。
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from .command_registry import AckResult, Command


@dataclass
class _Pending:
    token: int
    command: Command
    description: str               # 例如 "F1 X=1234 Y=-4562"
    timer: QTimer = field(repr=False)


class AckMatcher(QObject):
    """发送-回执配对器。

    信号：
    - :attr:`request_tracked(token, cmd_id, description)`：登记成功（UI 可记日志）
    - :attr:`ack_matched(token, cmd_id, ok, level, message, description)`：命中回执
    - :attr:`request_timeout(token, cmd_id, description)`：等待超时
    """

    request_tracked = Signal(int, int, str)
    ack_matched = Signal(int, int, bool, int, str, str)
    request_timeout = Signal(int, int, str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pending: dict[int, _Pending] = {}
        self._token_seq = itertools.count(1)

    # ---- 公共 API ----
    def track(self, command: Command, description: str) -> int:
        """登记一次发送，返回 token。timeout_ms<=0 视为不等回执（立即返回，但仍发 tracked 信号）。"""
        token = next(self._token_seq)
        timer = QTimer(self)
        timer.setSingleShot(True)
        if command.ack_timeout_ms > 0:
            # lambda 闭包捕获 token
            timer.timeout.connect(lambda t=token: self._on_timeout(t))
            timer.start(command.ack_timeout_ms)
        self._pending[token] = _Pending(
            token=token, command=command, description=description, timer=timer
        )
        self.request_tracked.emit(token, command.cmd_id, description)
        return token

    @Slot(str)
    def handle_text(self, text: str) -> None:
        """对所有挂起请求按登记顺序尝试 parse_ack；首次命中即结清。"""
        if not self._pending:
            return
        # 按 token 升序遍历（FIFO）
        for token in sorted(self._pending.keys()):
            pending = self._pending.get(token)
            if pending is None:
                continue
            try:
                result = pending.command.parse_ack(text)
            except Exception as exc:
                # 单命令解析异常不应拖垮全局，记一条但继续
                print(f"[AckMatcher] parse_ack 异常 cmd=0x{pending.command.cmd_id:02X}: {exc}")
                continue
            if result is not None:
                self._finish(token, ok=True, result=result)
                return  # 一条文本只匹配一个挂起

    def cancel(self, token: int) -> None:
        """取消挂起请求（断开串口、用户主动取消时用）。"""
        p = self._pending.pop(token, None)
        if p is None:
            return
        p.timer.stop()
        p.timer.deleteLater()

    def cancel_all(self) -> None:
        for token in list(self._pending.keys()):
            self.cancel(token)

    @property
    def pending_count(self) -> int:
        return len(self._pending)

    # ---- 内部 ----
    def _on_timeout(self, token: int) -> None:
        p = self._pending.pop(token, None)
        if p is None:
            return
        p.timer.deleteLater()
        self.request_timeout.emit(token, p.command.cmd_id, p.description)

    def _finish(self, token: int, ok: bool, result: AckResult) -> None:
        p = self._pending.pop(token, None)
        if p is None:
            return
        p.timer.stop()
        p.timer.deleteLater()
        self.ack_matched.emit(
            token, p.command.cmd_id,
            bool(result.ok), int(result.level), result.message, p.description,
        )
