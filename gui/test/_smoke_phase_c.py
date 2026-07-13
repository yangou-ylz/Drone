# -*- coding: utf-8 -*-
"""阶段 C 烟测：CommandRegistry + AckMatcher + F1Panel 自动化验证。

验证点：
1. F1 命令自动注册到 REGISTRY，cmd_id=0xF1；
2. F1.build_frame({x:1234, y:-4562}) 输出与已知好串 `aafff104d2042eee90a1` 一致；
3. AckMatcher.track + handle_text("F1: X=1234 Y=-4562") → 命中并发 ack_matched；
4. AckMatcher 超时路径：用极短超时（200ms）确认 request_timeout 触发；
5. 主窗口能创建并集成 CommandPanel；F1Panel 在断开状态下发送按钮禁用。
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main import MainWindow, _install_excepthook  # noqa: E402
from gui.services.ack_matcher import AckMatcher  # noqa: E402
from gui.services.command_registry import REGISTRY  # noqa: E402


_EXPECTED_HEX = "aafff104d2042eee90a1"


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _test_registry() -> bool:
    f1 = REGISTRY.get(0xF1)
    if f1 is None:
        print("[smoke C] FAIL: REGISTRY 中找不到 0xF1", file=sys.stderr)
        return False
    print(f"[smoke C] REGISTRY ok: cmd_id=0x{f1.cmd_id:02X} name={f1.name}")
    return True


def _test_build_frame() -> bool:
    f1 = REGISTRY.get(0xF1)
    frame = f1.build_frame({"x": 1234, "y": -4562})
    got = frame.hex()
    if got != _EXPECTED_HEX:
        print(f"[smoke C] FAIL: build_frame={got!r} != expected {_EXPECTED_HEX!r}", file=sys.stderr)
        return False
    print(f"[smoke C] build_frame ok: {got}")
    return True


def _test_parse_ack() -> bool:
    f1 = REGISTRY.get(0xF1)
    r = f1.parse_ack("F1: X=1234 Y=-4562")
    if r is None or not r.ok:
        print(f"[smoke C] FAIL: parse_ack 未命中：{r!r}", file=sys.stderr)
        return False
    if f1.parse_ack("P01=30.0") is not None:
        print("[smoke C] FAIL: parse_ack 误匹配 F2 文本", file=sys.stderr)
        return False
    print(f"[smoke C] parse_ack ok: {r.message}")
    return True


def _test_ack_match(win: MainWindow) -> bool:
    f1 = REGISTRY.get(0xF1)
    matcher = win._ack
    matcher.cancel_all()
    got = {"matched": False, "msg": None}

    def on_match(token, cmd_id, ok, level, message, desc):
        got["matched"] = True
        got["msg"] = message

    matcher.ack_matched.connect(on_match)
    try:
        token = matcher.track(f1, "X=1234 Y=-4562")
        assert matcher.pending_count == 1
        matcher.handle_text("F1: X=1234 Y=-4562")
        if not got["matched"] or matcher.pending_count != 0:
            print(f"[smoke C] FAIL: ack_match 未触发 got={got} pending={matcher.pending_count}",
                  file=sys.stderr)
            return False
        print(f"[smoke C] ack_match ok: token={token} msg={got['msg']!r}")
        return True
    finally:
        matcher.ack_matched.disconnect(on_match)


def _test_ack_timeout(win: MainWindow) -> bool:
    f1 = REGISTRY.get(0xF1)
    matcher = win._ack
    matcher.cancel_all()
    got = {"timeout": False}

    def on_to(*_):
        got["timeout"] = True

    matcher.request_timeout.connect(on_to)
    original = f1.ack_timeout_ms
    try:
        type(f1).ack_timeout_ms = 200  # type: ignore[misc]
        matcher.track(f1, "超时测试")
        _wait(400)
        if not got["timeout"] or matcher.pending_count != 0:
            print(f"[smoke C] FAIL: timeout 未触发 got={got} pending={matcher.pending_count}",
                  file=sys.stderr)
            return False
        print("[smoke C] ack_timeout ok")
        return True
    finally:
        type(f1).ack_timeout_ms = original  # type: ignore[misc]
        matcher.request_timeout.disconnect(on_to)


def _test_panel_disabled_when_offline(win: MainWindow) -> bool:
    panel = win._command_panel
    panel.set_enabled_for_link(False)
    f1_panel = panel._panels.get(0xF1)
    if f1_panel is None:
        print("[smoke C] FAIL: F1Panel 未懒构造", file=sys.stderr)
        return False
    if f1_panel._btn_send.isEnabled():
        print("[smoke C] FAIL: 断开状态下发送按钮仍可点", file=sys.stderr)
        return False
    panel.set_enabled_for_link(True)
    if not f1_panel._btn_send.isEnabled():
        print("[smoke C] FAIL: 连接后发送按钮仍禁用", file=sys.stderr)
        return False
    print("[smoke C] panel enable-by-link ok")
    return True


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    _install_excepthook(win._alarm)
    win.show()

    ok = True
    # 立即测试（无需事件循环）
    ok &= _test_registry()
    ok &= _test_build_frame()
    ok &= _test_parse_ack()
    ok &= _test_ack_match(win)
    ok &= _test_panel_disabled_when_offline(win)

    # 异步测试：超时
    ok &= _test_ack_timeout(win)

    # 2s 后关闭窗口
    QTimer.singleShot(1000, win.close)
    rc = app.exec()
    print(f"[smoke C] app.exec returned {rc}; overall ok={ok}")
    return 0 if (rc == 0 and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
