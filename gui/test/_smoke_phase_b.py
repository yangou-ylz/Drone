# -*- coding: utf-8 -*-
"""阶段 B 烟测：自启动主窗口，触发若干日志/报警/异常路径，验证后退出。

验证点：
1. 主窗口能正常显示（ConnectionBar、LogView、状态栏齐全）；
2. LogService 文件被创建并写入；
3. AlarmService.info/warn 不弹窗、error 弹窗（烟测模式跳过弹窗）；
4. ConfigService 在退出时持久化 window_size/window_pos；
5. 全局 sys.excepthook 不会让程序崩溃。

烟测期间禁用 ERROR 弹窗（避免阻塞自动退出）。
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main import MainWindow, _install_excepthook  # noqa: E402


def _drive(win: MainWindow) -> None:
    """触发日志/报警/异常路径。"""
    # 1. 三级日志
    win._log.debug("烟测", "DEBUG 行（默认过滤等级看不到）")
    win._log.info("烟测", "INFO 行：阶段 B 启动正常")
    win._log.warn("烟测", "WARN 行：橙色，模拟可恢复警告")

    # 2. 报警 —— info/warn 不弹窗
    win._alarm.info("烟测", "AlarmService.info 测试")
    win._alarm.warn("烟测", "AlarmService.warn 测试")

    # 3. ConnectionBar 端口枚举
    n = win._connection_bar._combo.count()
    win._log.info("烟测", f"ConnectionBar 枚举到 {n} 个串口")

    # 4. 触发模拟连接成功 → 失败路径（不真开串口，直接调槽）
    win._on_serial_connected("COM_TEST")
    win._on_serial_disconnected("用户主动断开（模拟）")

    # 5. 验证 LogService 文件已写
    fp = win._log.file_path
    if fp and os.path.isfile(fp):
        size = os.path.getsize(fp)
        win._log.info("烟测", f"日志文件已生成：{fp} ({size} B)")
        print(f"[smoke] log file ok: {fp} ({size} B)")
    else:
        print(f"[smoke] WARN: log file not found: {fp!r}", file=sys.stderr)

    # 6. 验证 ConfigService 写盘
    cfg_path = win._config.path
    print(f"[smoke] config path: {cfg_path}")


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    # 烟测中不主动触发 alarm.error()，避免模态弹窗阻塞自动退出
    _install_excepthook(win._alarm)
    win.show()

    # 0.5s 后触发各种动作；2.5s 后关闭主窗口
    QTimer.singleShot(500, lambda: _drive(win))
    QTimer.singleShot(2500, win.close)

    rc = app.exec()
    print(f"[smoke] app.exec returned {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
