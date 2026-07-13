# -*- coding: utf-8 -*-
"""敏感命令二次确认对话框。

为 `Command.requires_confirm = True` 的命令统一提供"参数预览 + 强制勾选"
确认界面：用户必须勾选「我已确认参数无误」复选框后，「发送」按钮才会启用，
避免随手回车把错误参数打到飞控上。

用法：
    if confirm_send(parent, cmd_name, desc_text):
        # 用户确认
        ...
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)


class _ConfirmDialog(QDialog):
    """命令二次确认弹窗：勾选复选框后「发送」才可点。"""

    def __init__(self, parent: QWidget | None, cmd_name: str, desc: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"二次确认：{cmd_name}")
        self.setModal(True)
        self.setMinimumWidth(420)
        # 阻止用 ESC 之外的关闭方式默认通过
        self.setWindowFlag(Qt.WindowType.WindowContextHelpButtonHint, False)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 12)
        root.setSpacing(10)

        title = QLabel(f"<b>即将发送：{cmd_name}</b>")
        title.setStyleSheet("font-size: 13pt;")
        root.addWidget(title)

        warn = QLabel(
            "<span style='color:#C62828;'>"
            "此命令会改变飞控状态，请确认所有参数无误后再发送。"
            "</span>"
        )
        warn.setWordWrap(True)
        root.addWidget(warn)

        desc_label = QLabel(f"<b>参数：</b><br>{desc}")
        # 强制锁死深色文字 + 浅灰底，避免主题切换（特别是暗色主题）下出现"白底白字"
        desc_label.setStyleSheet(
            "QLabel {"
            " background: #f5f5f5; border: 1px solid #c0c0c0;"
            " padding: 8px; font-family: Consolas, monospace;"
            " color: #212121;"
            "}"
        )
        desc_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        desc_label.setWordWrap(True)
        root.addWidget(desc_label)

        self._chk = QCheckBox("我已确认参数无误")
        self._chk.toggled.connect(self._on_check_toggled)
        root.addWidget(self._chk)

        self._buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setText("发送")
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        # 默认聚焦到取消，回车不会误触发送
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setDefault(True)
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(False)
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        root.addWidget(self._buttons)

    def _on_check_toggled(self, checked: bool) -> None:
        self._buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(bool(checked))


def confirm_send(parent: QWidget | None, cmd_name: str, desc: str) -> bool:
    """弹出二次确认对话框；返回 True 表示用户确认发送。"""
    dlg = _ConfirmDialog(parent, cmd_name, desc)
    return dlg.exec() == QDialog.DialogCode.Accepted
