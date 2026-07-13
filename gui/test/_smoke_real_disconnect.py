# -*- coding: utf-8 -*-
"""真实 SerialWorker 的断开链路烟测：mock Win32Serial 避免硬件依赖。"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 关键：在 import gui.io.serial_worker 之前替换 Win32Serial
import groundTest.win_serial as ws_mod  # noqa: E402


class FakeWin32Serial:
    def __init__(self, name):
        self.name = name
        self._open = False
    def open(self):
        self._open = True
    def close(self):
        self._open = False
    def write(self, data):
        return len(data)
    def read_nonblocking(self, max_bytes=4096, wait_s=0.05):
        import time as _t
        _t.sleep(min(wait_s, 0.02))
        return b""


ws_mod.Win32Serial = FakeWin32Serial

from PySide6.QtCore import (  # noqa: E402
    QEventLoop, QMetaObject, Qt, QThread, QTimer, Q_ARG,
)
from PySide6.QtWidgets import QApplication  # noqa: E402
from gui.io.serial_worker import SerialWorker  # noqa: E402
# 也要把 SerialWorker 模块里的 Win32Serial 引用替换掉
import gui.io.serial_worker as sw_mod  # noqa: E402
sw_mod.Win32Serial = FakeWin32Serial


def _wait(ms):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def main():
    app = QApplication(sys.argv)

    events = []
    thread = QThread()
    worker = SerialWorker()
    worker.moveToThread(thread)
    thread.started.connect(worker.start_loop)
    worker.connected.connect(lambda n: events.append(("conn", n)))
    worker.disconnected.connect(lambda r: events.append(("disc", r)))
    worker.error.connect(lambda e: events.append(("err", e)))
    thread.start()
    _wait(100)

    # 模拟 UI 线程发起 open
    QMetaObject.invokeMethod(worker, "open_port", Qt.ConnectionType.QueuedConnection,
                              Q_ARG(str, "COM_MOCK"))
    _wait(200)
    print(f"[after open] events={events}")
    assert any(e[0] == "conn" for e in events), "open_port 未触发 connected"

    # 模拟 UI 线程发起 close（模拟用户点击断开）
    events.clear()
    QMetaObject.invokeMethod(worker, "close_port", Qt.ConnectionType.QueuedConnection)
    _wait(500)
    print(f"[after close] events={events}")
    assert any(e[0] == "disc" for e in events), "close_port 未触发 disconnected"

    # 收尾
    QMetaObject.invokeMethod(worker, "stop", Qt.ConnectionType.QueuedConnection)
    _wait(100)
    thread.quit()
    thread.wait(2000)
    print("[smoke] real SerialWorker close path OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
