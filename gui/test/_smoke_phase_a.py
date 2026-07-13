# -*- coding: utf-8 -*-
"""阶段 A 自测：启动 GUI，2 秒后自动关闭，验证窗口与线程生命周期。

不依赖任何实体串口。预期：进程返回 0；stderr 无 Python Traceback。
"""
from __future__ import annotations
import sys
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from gui.main import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    # 2 秒后自动触发关闭 (等同用户点 X)
    QTimer.singleShot(2000, win.close)
    rc = app.exec()
    print(f"[smoke] app.exec returned {rc}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
