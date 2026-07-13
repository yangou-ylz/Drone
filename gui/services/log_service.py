# -*- coding: utf-8 -*-
"""LogService —— 统一日志中心。

职责：
1. 提供统一的 :meth:`log` 接口，按等级/分类记录一条事件；
2. 通过 Qt 信号 :attr:`entry_added` 通知所有订阅者（如 LogView）；
3. 同步将带毫秒时间戳的纯文本追加写入 TXT 文件；
4. 提供 :meth:`export_to` 一键导出（复制当前 TXT 到目标路径）。

线程安全：
- :meth:`log` 可在任意线程调用；写文件加 :class:`QMutex` 保护；
- Qt 信号 emit 后由 Qt 自动决定连接类型（订阅者多数在主线程，使用 QueuedConnection）。
"""
from __future__ import annotations

import datetime as _dt
import os
import shutil
import sys
from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import QMutex, QMutexLocker, QObject, Signal


class LogLevel(IntEnum):
    """日志等级，数值越大越严重，便于按下限过滤显示。"""
    DEBUG = 0   # 调试细节，默认不显示
    INFO = 1    # 一般操作信息
    WARN = 2    # 业务可恢复警告
    ERROR = 3   # 错误（同时会触发 AlarmService.error）

    @property
    def label(self) -> str:
        return {0: "调试", 1: "信息", 2: "警告", 3: "错误"}[int(self)]

    @property
    def color_hex(self) -> str:
        # 用于 LogView 的 HTML 着色
        return {0: "#888888", 1: "#1976D2", 2: "#E65100", 3: "#C62828"}[int(self)]


@dataclass(frozen=True)
class LogEntry:
    """单条日志条目（不可变，便于跨线程传递）。"""
    ts: _dt.datetime         # 时间戳
    level: LogLevel
    category: str            # 分类，例如 "串口" / "发送" / "回执" / "系统"
    message: str

    def format_plain(self) -> str:
        """格式化为纯文本（写入文件用）。"""
        ts = self.ts.strftime("%H:%M:%S") + f".{self.ts.microsecond // 1000:03d}"
        return f"[{ts}] [{self.level.label}] [{self.category}] {self.message}"


# 默认日志目录
_DEFAULT_LOG_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, "logs")
)


class LogService(QObject):
    """全局日志服务，单实例。"""

    entry_added = Signal(object)   # LogEntry，object 类型规避 Qt 元类型注册

    def __init__(self, log_dir: str = "") -> None:
        super().__init__()
        self._mutex = QMutex()
        self._log_dir = log_dir.strip() or _DEFAULT_LOG_DIR
        self._file_path: str = ""
        self._fp = None  # 文本文件对象
        self._open_file()

    # ---- 公共接口 ----
    def log(self, level: LogLevel, category: str, message: str) -> None:
        """记录一条日志。线程安全。"""
        entry = LogEntry(
            ts=_dt.datetime.now(),
            level=level,
            category=category or "通用",
            message=message,
        )
        # 写文件（加锁）
        with QMutexLocker(self._mutex):
            if self._fp is not None:
                try:
                    self._fp.write(entry.format_plain() + "\n")
                    self._fp.flush()
                except Exception as exc:
                    print(f"[LogService] 写文件失败：{exc}", file=sys.stderr)
        # 信号上抛（无锁，Qt 自己处理）
        try:
            self.entry_added.emit(entry)
        except Exception as exc:
            print(f"[LogService] 发信号失败：{exc}", file=sys.stderr)

    # 便捷方法
    def debug(self, category: str, message: str) -> None:
        self.log(LogLevel.DEBUG, category, message)

    def info(self, category: str, message: str) -> None:
        self.log(LogLevel.INFO, category, message)

    def warn(self, category: str, message: str) -> None:
        self.log(LogLevel.WARN, category, message)

    def error(self, category: str, message: str) -> None:
        self.log(LogLevel.ERROR, category, message)

    @property
    def file_path(self) -> str:
        """当前日志文件绝对路径（可能为空字符串表示打开失败）。"""
        return self._file_path

    def export_to(self, target_path: str) -> bool:
        """把当前日志文件另存为 target_path。返回是否成功。"""
        if not self._file_path or not os.path.isfile(self._file_path):
            return False
        try:
            with QMutexLocker(self._mutex):
                if self._fp is not None:
                    self._fp.flush()
                shutil.copyfile(self._file_path, target_path)
            return True
        except Exception as exc:
            print(f"[LogService] 导出失败：{exc}", file=sys.stderr)
            return False

    def close(self) -> None:
        """关闭文件句柄，主窗口退出时调用。"""
        with QMutexLocker(self._mutex):
            if self._fp is not None:
                try:
                    self._fp.close()
                except Exception:
                    pass
                self._fp = None

    # ---- 内部 ----
    def _open_file(self) -> None:
        try:
            os.makedirs(self._log_dir, exist_ok=True)
            fname = _dt.datetime.now().strftime("gui_%Y%m%d_%H%M%S.txt")
            self._file_path = os.path.join(self._log_dir, fname)
            # utf-8 with BOM，方便记事本直接打开看中文
            self._fp = open(self._file_path, "w", encoding="utf-8-sig", buffering=1)
            self._fp.write(
                f"=== 凌霄上位机日志开始 {_dt.datetime.now().isoformat(timespec='seconds')} ===\n"
            )
            self._fp.flush()
        except Exception as exc:
            self._fp = None
            self._file_path = ""
            print(f"[LogService] 打开日志文件失败：{exc}", file=sys.stderr)
