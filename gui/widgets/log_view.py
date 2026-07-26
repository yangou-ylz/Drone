# -*- coding: utf-8 -*-
"""LogView —— 日志显示面板。

订阅 :class:`LogService` 的 ``entry_added`` 信号，按等级着色实时渲染。
顶部工具栏提供：等级过滤、暂停滚动、清屏、导出。

性能取舍：
- 使用 QTextEdit + appendHtml（支持颜色），日志量大时通过 _MAX_BLOCKS 自动剪裁；
- 阶段 B 命令吞吐 <=10 Hz，远低于性能瓶颈；后续若需要 10kHz 级日志再换 QPlainTextEdit。
"""
from __future__ import annotations

import html as _html

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QFont, QTextCursor
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ..services.log_service import LogEntry, LogLevel, LogService

_MAX_BLOCKS = 5000   # 最多保留行数，溢出后从顶部裁剪
_LEVEL_NAMES = ["全部(含调试)", "信息及以上", "警告及以上", "仅错误"]
_LEVEL_THRESHOLDS = [LogLevel.DEBUG, LogLevel.INFO, LogLevel.WARN, LogLevel.ERROR]


class LogView(QWidget):
    """日志面板控件。"""

    export_requested = Signal(str)   # 用户点击导出后，请求目标路径（由 MainWindow 实际调 LogService）

    def __init__(self, log_service: LogService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = log_service
        self._auto_scroll = True
        self._min_level = LogLevel.INFO
        self._build_ui()
        # 订阅
        self._log.entry_added.connect(self._on_entry)
        # 启动提示
        self._append_html(
            '<span style="color:#888;">— 日志开始 —</span><br>'
            f'<span style="color:#888;">日志文件：{_html.escape(self._log.file_path or "(打开失败)")}</span>'
        )

    # ---- UI ----
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(2)

        bar = QHBoxLayout()
        bar.setContentsMargins(6, 4, 6, 0)
        bar.setSpacing(8)

        bar.addWidget(QLabel("日志等级："))
        self._level_combo = QComboBox()
        for n in _LEVEL_NAMES:
            self._level_combo.addItem(n)
        self._level_combo.setCurrentIndex(1)  # 信息及以上
        self._level_combo.currentIndexChanged.connect(self._on_level_changed)
        bar.addWidget(self._level_combo)

        self._scroll_btn = QPushButton("暂停滚动")
        self._scroll_btn.setCheckable(True)
        self._scroll_btn.toggled.connect(self._on_scroll_toggled)
        bar.addWidget(self._scroll_btn)

        self._clear_btn = QPushButton("清屏")
        self._clear_btn.setToolTip("仅清除显示，不影响磁盘日志文件")
        self._clear_btn.clicked.connect(self._on_clear)
        bar.addWidget(self._clear_btn)

        self._export_btn = QPushButton("导出日志…")
        self._export_btn.clicked.connect(self._on_export)
        bar.addWidget(self._export_btn)

        bar.addStretch(1)
        root.addLayout(bar)

        self._edit = QTextEdit()
        self._edit.setReadOnly(True)
        self._edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        f = QFont("Consolas")
        f.setStyleHint(QFont.StyleHint.Monospace)
        f.setPointSize(10)
        self._edit.setFont(f)
        # 暗色背景 + 可拖拽的滚动条（默认 QSS 在某些主题下滑块隐形，这里显式加大）
        self._edit.setStyleSheet(
            "QTextEdit { background-color: #1E1E1E; color: #E0E0E0; }"
            # ---- 横向 ----
            "QScrollBar:horizontal { background: #2A2A2A; height: 14px; margin: 0 16px 0 16px; }"
            "QScrollBar::handle:horizontal { background: #5A5A5A; min-width: 30px; border-radius: 5px; }"
            "QScrollBar::handle:horizontal:hover { background: #7A7A7A; }"
            "QScrollBar::handle:horizontal:pressed { background: #9A9A9A; }"
            "QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {"
            " background: #3A3A3A; width: 14px; subcontrol-origin: margin; }"
            "QScrollBar::add-line:horizontal { subcontrol-position: right; }"
            "QScrollBar::sub-line:horizontal { subcontrol-position: left; }"
            "QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; }"
            # ---- 纵向 ----
            "QScrollBar:vertical { background: #2A2A2A; width: 14px; margin: 16px 0 16px 0; }"
            "QScrollBar::handle:vertical { background: #5A5A5A; min-height: 30px; border-radius: 5px; }"
            "QScrollBar::handle:vertical:hover { background: #7A7A7A; }"
            "QScrollBar::handle:vertical:pressed { background: #9A9A9A; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {"
            " background: #3A3A3A; height: 14px; subcontrol-origin: margin; }"
            "QScrollBar::add-line:vertical { subcontrol-position: bottom; }"
            "QScrollBar::sub-line:vertical { subcontrol-position: top; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }"
        )
        root.addWidget(self._edit, 1)

    # ---- 槽 ----
    def _on_entry(self, entry: LogEntry) -> None:
        if int(entry.level) < int(self._min_level):
            return
        ts = entry.ts.strftime("%H:%M:%S") + f".{entry.ts.microsecond // 1000:03d}"
        color = entry.level.color_hex
        # 转义防注入
        cat = _html.escape(entry.category)
        msg = _html.escape(entry.message)
        cat_color = "#CE93D8" if entry.category.lower() == "rviz" else "#80CBC4"
        line = (
            f'<span style="color:#888;">[{ts}]</span> '
            f'<span style="color:{color}; font-weight:bold;">[{entry.level.label}]</span> '
            f'<span style="color:{cat_color}; font-weight:bold;">[{cat}]</span> '
            f'<span style="color:#E0E0E0;">{msg}</span>'
        )
        self._append_html(line)

    def _on_level_changed(self, idx: int) -> None:
        if 0 <= idx < len(_LEVEL_THRESHOLDS):
            self._min_level = _LEVEL_THRESHOLDS[idx]

    def _on_scroll_toggled(self, paused: bool) -> None:
        self._auto_scroll = not paused
        self._scroll_btn.setText("继续滚动" if paused else "暂停滚动")

    def _on_clear(self) -> None:
        self._edit.clear()

    # ---- 公共 API（供菜单等外部调用） ----
    def clear_display(self) -> None:
        """清空显示，不影响磁盘日志。"""
        self._on_clear()

    def set_paused(self, paused: bool) -> None:
        """外部（如菜单）切换"暂停滚动"，会同步勾选工具栏按钮。"""
        if self._scroll_btn.isChecked() != paused:
            self._scroll_btn.setChecked(paused)
        else:
            # 按钮状态未变也要刷新内部 flag（避免不同步）
            self._on_scroll_toggled(paused)

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", "lingxiao_gui_log.txt", "文本文件 (*.txt)"
        )
        if path:
            self.export_requested.emit(path)

    # ---- 内部 ----
    def _append_html(self, html: str) -> None:
        cursor = self._edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertHtml(html + "<br>")
        # 行数裁剪
        doc = self._edit.document()
        if doc.blockCount() > _MAX_BLOCKS:
            cur = QTextCursor(doc)
            cur.movePosition(QTextCursor.MoveOperation.Start)
            for _ in range(doc.blockCount() - _MAX_BLOCKS):
                cur.select(QTextCursor.SelectionType.BlockUnderCursor)
                cur.removeSelectedText()
                cur.deleteChar()  # 删块尾换行
        if self._auto_scroll:
            sb = self._edit.verticalScrollBar()
            sb.setValue(sb.maximum())
