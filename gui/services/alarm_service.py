# -*- coding: utf-8 -*-
"""AlarmService —— 三级报警中心。

策略：
- :meth:`info` / :meth:`warn` / :meth:`error` 三种入口，自动转写一条日志；
- ERROR 级别在主线程额外弹出模态对话框，提示用户介入；
- 信号 :attr:`alarm_raised` 暴露给状态栏/指示灯订阅（如最近一次警报闪烁）。

线程：
- 入口方法在任意线程安全调用；
- 弹窗依赖主线程，通过 QueuedConnection 信号触发，绝不在 worker 线程直接构造 QMessageBox。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QMessageBox, QWidget

from .log_service import LogLevel, LogService


class AlarmService(QObject):
    """报警分发器。"""

    alarm_raised = Signal(int, str, str)        # level(int), category, message
    _request_error_dialog = Signal(str, str)    # 私有：跨线程到主线程的弹窗触发器

    def __init__(self, log_service: LogService, parent_widget: QWidget | None = None) -> None:
        super().__init__()
        self._log = log_service
        self._parent_widget = parent_widget
        # 跨线程弹窗：用 QueuedConnection 让 _show_error_dialog 在主线程执行
        self._request_error_dialog.connect(
            self._show_error_dialog, Qt.ConnectionType.QueuedConnection
        )

    def set_parent_widget(self, w: QWidget) -> None:
        """主窗口构造完成后再回填，避免循环依赖。"""
        self._parent_widget = w

    # ---- 三级入口 ----
    def info(self, category: str, message: str) -> None:
        self._log.info(category, message)
        self.alarm_raised.emit(int(LogLevel.INFO), category, message)

    def warn(self, category: str, message: str) -> None:
        self._log.warn(category, message)
        self.alarm_raised.emit(int(LogLevel.WARN), category, message)

    def error(self, category: str, message: str, *, popup: bool = True) -> None:
        """ERROR 默认弹窗；批量错误可设 popup=False 仅记录。"""
        self._log.error(category, message)
        self.alarm_raised.emit(int(LogLevel.ERROR), category, message)
        if popup:
            # 异步到主线程
            self._request_error_dialog.emit(category, message)

    # ---- 槽 ----
    @Slot(str, str)
    def _show_error_dialog(self, category: str, message: str) -> None:
        try:
            box = QMessageBox(self._parent_widget)
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(f"错误：{category}")
            box.setText(message)
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()
        except Exception:
            # 弹窗失败兜底，不再递归报错
            pass
