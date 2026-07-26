# -*- coding: utf-8 -*-
"""RViz 顶栏快捷入口烟雾测试。

不启动真实 rviz2；通过 LINGXIAO_RVIZ_COMMAND 注入一个可控的假进程，
验证菜单按钮、日志转发和 GUI 关闭时的进程清理。
"""
from __future__ import annotations

import os
import shlex
import sys
import time

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["LINGXIAO_GUI_FAKE"] = "1"

fake_code = (
    "import sys,time,signal\n"
    "print('rviz smoke start', flush=True)\n"
    "signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))\n"
    "while True:\n"
    "    time.sleep(0.1)\n"
)
os.environ["LINGXIAO_RVIZ_COMMAND"] = f"{shlex.quote(sys.executable)} -c {shlex.quote(fake_code)}"

from PySide6.QtWidgets import QApplication  # noqa: E402


def _pump_until(app: QApplication, predicate, timeout_s: float, label: str) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError(f"timeout waiting for {label}")


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)

    from gui.main import MainWindow

    logs: list[tuple[str, str]] = []
    win = MainWindow()
    win._log.entry_added.connect(lambda e: logs.append((e.category, e.message)))

    titles = [a.text() for a in win.menuBar().actions()]
    assert any(t == "rviz" for t in titles), f"顶栏缺少 rviz：{titles}"

    win._act_rviz.trigger()
    _pump_until(app, lambda: win._rviz.is_running, 2.0, "rviz fake process start")
    _pump_until(app, lambda: any(cat == "rviz" and "rviz smoke start" in msg for cat, msg in logs),
                2.0, "rviz log forwarding")
    assert win._act_rviz.text() == "rviz(运行中)", win._act_rviz.text()

    win.close()
    _pump_until(app, lambda: not win._rviz.is_running, 2.0, "rviz fake process stop")
    assert any(cat == "rviz" and "停止 rviz2：GUI 退出" in msg for cat, msg in logs)

    print("RViz smoke OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
