# -*- coding: utf-8 -*-
"""防误触的 DoubleSpinBox（共用控件）。

原生 QDoubleSpinBox 点上下箭头时，Qt 会通过事件循环 selectAll() 整行文本，
导致下一次点击直接覆盖。本子类在 stepBy / 鼠标聚焦后延迟 deselect，
同时拦截在抑制期内的 selectionChanged，保证用户主动拖蓝不受影响。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QAbstractSpinBox, QDoubleSpinBox, QWidget


class StableDoubleSpinBox(QDoubleSpinBox):
    """箭头不再触发"全选当前值"误覆盖。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.UpDownArrows)
        # 不在每次按键就 emit valueChanged，避免输入 -1 时先被 -（取负空值）触发越界恢复
        self.setKeyboardTracking(False)
        # 关键：Qt 内部 stepBy 完成后会通过事件循环再次 selectAll，
        # 因此 deselect 必须排到事件队列末尾才能生效。
        self.valueChanged.connect(self._schedule_deselect)
        le = self.lineEdit()
        if le is not None:
            le.selectionChanged.connect(self._on_selection_changed)
        self._suppress_select = False

    def stepBy(self, steps: int) -> None:  # noqa: N802 - Qt 命名
        self._suppress_select = True
        super().stepBy(steps)
        self._schedule_deselect()
        QTimer.singleShot(0, self._clear_suppress)

    def focusInEvent(self, event) -> None:  # noqa: N802
        super().focusInEvent(event)
        if event.reason() in (
            Qt.FocusReason.MouseFocusReason,
            Qt.FocusReason.OtherFocusReason,
        ):
            self._suppress_select = True
            QTimer.singleShot(0, self._safe_deselect)
            QTimer.singleShot(0, self._clear_suppress)

    def _on_selection_changed(self) -> None:
        if not self._suppress_select:
            return
        le = self.lineEdit()
        if le is not None and le.hasSelectedText():
            le.deselect()
            le.setCursorPosition(len(le.text()))

    def _schedule_deselect(self, *_args) -> None:
        QTimer.singleShot(0, self._safe_deselect)

    def _safe_deselect(self) -> None:
        le = self.lineEdit()
        if le is not None:
            le.deselect()
            le.setCursorPosition(len(le.text()))

    def _clear_suppress(self) -> None:
        self._suppress_select = False
