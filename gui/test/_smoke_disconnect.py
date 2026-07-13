# -*- coding: utf-8 -*-
"""单点烟测：连接→断开链路是否完整工作（FakeWorker）。"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ["LINGXIAO_GUI_FAKE"] = "1"

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main import MainWindow  # noqa: E402


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication(sys.argv)
    win = MainWindow()
    cb = win._connection_bar
    # 模拟选择 COM_FAKE
    cb._combo.setEditText("COM_FAKE")
    # 模拟点连接按钮
    cb._btn.click()
    _wait(300)
    print(f"[step1] after connect: connected={cb._connected} btn_text={cb._btn.text()!r}")
    assert cb._connected, "连接未生效"

    # 模拟点断开按钮
    cb._btn.click()
    _wait(300)
    print(f"[step2] after disconnect: connected={cb._connected} btn_text={cb._btn.text()!r}")
    assert not cb._connected, "断开未生效"

    print("[smoke] OK")
    QTimer.singleShot(100, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
