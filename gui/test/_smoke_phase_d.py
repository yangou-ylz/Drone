# -*- coding: utf-8 -*-
"""阶段 D 烟测：F2 命令 + 三态联动 + 离线 FakeWorker 端到端。

验证点：
1. F2 命令自动注册到 REGISTRY，cmd_id=0xF2，requires_confirm=True；
2. F2.build_frame 已知好串：id=0x01, value=50.0 → 帧字节固定；
3. F2.parse_ack 三分支：成功 / CLP / UNK 各自的 level 正确；
4. F2.parse_ack 不误匹配 F1 文本；F1.parse_ack 不误匹配 F2 文本；
5. FakeWorker open/send F1 → 收到 0xA0 "F1: X=.. Y=.." 回执；
6. FakeWorker send F2 (UNK ID) → 收到红字 P?? UNK；
7. FakeWorker send F2 (越界) → 收到 CLP；
8. 端到端：MainWindow + AckMatcher + FakeWorker，F1 发送后状态机走完，
   面板状态切到 ok。
"""
from __future__ import annotations

import os
import struct
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import (  # noqa: E402
    QByteArray,
    QEventLoop,
    QMetaObject,
    Qt,
    QTimer,
    Q_ARG,
)
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.io.fake_worker import FakeWorker  # noqa: E402
from gui.io.protocol import build_f2_param, ADDR_BROADCAST  # noqa: E402
from gui.services.command_registry import REGISTRY  # noqa: E402
from gui.services.log_service import LogLevel  # noqa: E402


def _wait(ms: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


# ---------------- 纯逻辑测试（不需要 GUI 进入 exec）----------------

def _test_f2_registered() -> bool:
    f2 = REGISTRY.get(0xF2)
    if f2 is None:
        print("[smoke D] FAIL: REGISTRY 中找不到 0xF2", file=sys.stderr)
        return False
    if not f2.requires_confirm:
        print("[smoke D] FAIL: F2 应当要求二次确认", file=sys.stderr)
        return False
    print(f"[smoke D] F2 registered ok: name={f2.name} confirm={f2.requires_confirm}")
    return True


def _test_f2_build_frame() -> bool:
    f2 = REGISTRY.get(0xF2)
    # id=0x01, value=50.0 → DATA = 01 00 00 48 42 (float32 LE)
    frame = f2.build_frame({"param_id": 0x01, "value": 50.0})
    # 也用底层组帧再算一遍做交叉验证
    expected = build_f2_param(ADDR_BROADCAST, 0x01, 50.0)
    if frame != expected:
        print(f"[smoke D] FAIL: F2.build_frame 不一致 got={frame.hex()} exp={expected.hex()}",
              file=sys.stderr)
        return False
    # 校验帧头/CMD/LEN 结构
    if frame[0] != 0xAA or frame[1] != 0xFF or frame[2] != 0xF2 or frame[3] != 5:
        print(f"[smoke D] FAIL: F2 帧结构异常 {frame.hex()}", file=sys.stderr)
        return False
    # DATA 段 float32(50.0) = 0x42480000 → LE = 00 00 48 42
    data = frame[4:9]
    pid = data[0]
    val = struct.unpack("<f", data[1:5])[0]
    if pid != 0x01 or abs(val - 50.0) > 1e-6:
        print(f"[smoke D] FAIL: F2 DATA 解析错 pid={pid} val={val}", file=sys.stderr)
        return False
    print(f"[smoke D] F2.build_frame ok: {frame.hex()}")
    return True


def _test_f2_parse_ack() -> bool:
    f2 = REGISTRY.get(0xF2)
    # 成功
    r = f2.parse_ack("P01=50.0")
    if r is None or not r.ok or r.level != LogLevel.INFO:
        print(f"[smoke D] FAIL: P01=50.0 解析错 {r!r}", file=sys.stderr)
        return False
    # CLP
    r = f2.parse_ack("P02=500.0 CLP")
    if r is None or not r.ok or r.level != LogLevel.WARN:
        print(f"[smoke D] FAIL: CLP 解析错 {r!r}", file=sys.stderr)
        return False
    # UNK
    r = f2.parse_ack("P?? UNK")
    if r is None or r.ok or r.level != LogLevel.ERROR:
        print(f"[smoke D] FAIL: UNK 解析错 {r!r}", file=sys.stderr)
        return False
    r = f2.parse_ack("P05 UNK")
    if r is None or r.ok or r.level != LogLevel.ERROR:
        print(f"[smoke D] FAIL: P05 UNK 解析错 {r!r}", file=sys.stderr)
        return False
    print("[smoke D] F2.parse_ack ok (INFO/WARN/ERROR)")
    return True


def _test_cross_no_match() -> bool:
    f1 = REGISTRY.get(0xF1)
    f2 = REGISTRY.get(0xF2)
    if f1.parse_ack("P01=50.0") is not None:
        print("[smoke D] FAIL: F1 误匹配 F2 文本", file=sys.stderr)
        return False
    if f2.parse_ack("F1: X=1 Y=2") is not None:
        print("[smoke D] FAIL: F2 误匹配 F1 文本", file=sys.stderr)
        return False
    print("[smoke D] cross-parse 隔离 ok")
    return True


# ---------------- FakeWorker 回环测试 ----------------

def _test_fake_f1(worker: FakeWorker) -> bool:
    got = {"frame": None}

    def on_frame(fr):
        got["frame"] = fr

    worker.frame_received.connect(on_frame)
    try:
        # 构造 F1 帧字节
        f1 = REGISTRY.get(0xF1)
        frame = f1.build_frame({"x": 1234, "y": -4562})
        worker.send_bytes(QByteArray(frame))
        _wait(200)  # 等仿真定时器
        if got["frame"] is None:
            print("[smoke D] FAIL: FakeWorker F1 未回执", file=sys.stderr)
            return False
        cs = got["frame"].color_str()
        if cs is None:
            print("[smoke D] FAIL: FakeWorker 回执不是 0xA0", file=sys.stderr)
            return False
        color, text = cs
        if "F1: X=1234" not in text or "Y=-4562" not in text:
            print(f"[smoke D] FAIL: FakeWorker F1 回执文本错: {text!r}", file=sys.stderr)
            return False
        print(f"[smoke D] FakeWorker F1 ok: color={color} text={text!r}")
        return True
    finally:
        worker.frame_received.disconnect(on_frame)


def _test_fake_f2_unk(worker: FakeWorker) -> bool:
    got = {"text": None, "color": None}

    def on_frame(fr):
        cs = fr.color_str()
        if cs:
            got["color"], got["text"] = cs

    worker.frame_received.connect(on_frame)
    try:
        # 未知 ID=0x77
        frame = build_f2_param(ADDR_BROADCAST, 0x77, 1.0)
        worker.send_bytes(QByteArray(frame))
        _wait(200)
        if got["text"] is None or "UNK" not in got["text"]:
            print(f"[smoke D] FAIL: FakeWorker F2 UNK 文本错 {got!r}", file=sys.stderr)
            return False
        if got["color"] != 1:  # COLOR_RED
            print(f"[smoke D] FAIL: FakeWorker F2 UNK 颜色应为红 1 实际 {got['color']}",
                  file=sys.stderr)
            return False
        print(f"[smoke D] FakeWorker F2 UNK ok: {got['text']!r} (red)")
        return True
    finally:
        worker.frame_received.disconnect(on_frame)


def _test_fake_f2_clp(worker: FakeWorker) -> bool:
    got = {"text": None}

    def on_frame(fr):
        cs = fr.color_str()
        if cs:
            got["text"] = cs[1]

    worker.frame_received.connect(on_frame)
    try:
        # 越界 600.0 cm → 应被限到 500.0 + CLP
        frame = build_f2_param(ADDR_BROADCAST, 0x01, 600.0)
        worker.send_bytes(QByteArray(frame))
        _wait(200)
        if got["text"] is None or "CLP" not in got["text"] or "500.0" not in got["text"]:
            print(f"[smoke D] FAIL: FakeWorker F2 CLP 文本错 {got!r}", file=sys.stderr)
            return False
        print(f"[smoke D] FakeWorker F2 CLP ok: {got['text']!r}")
        return True
    finally:
        worker.frame_received.disconnect(on_frame)


# ---------------- 端到端测试 ----------------

def _test_e2e(app: QApplication) -> bool:
    """MainWindow + AckMatcher + FakeWorker：模拟用户点发送→收到回执→面板转 ok。"""
    os.environ["LINGXIAO_GUI_FAKE"] = "1"
    try:
        from gui.main import MainWindow
        win = MainWindow()
        # 走仿真"连接"路径
        QMetaObject.invokeMethod(
            win._worker, "open_port", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, "COM_FAKE"),
        )
        _wait(150)
        # 发 F1
        win._on_command_send_requested(0xF1, {"x": 1234, "y": -4562})
        # 等回执 + 处理
        _wait(400)

        # 检查面板状态：F1Panel._lamp 颜色应为绿色
        f1_panel = win._command_panel._panels.get(0xF1)
        if f1_panel is None:
            print("[smoke D] FAIL: e2e F1Panel 未懒构造", file=sys.stderr)
            return False
        ss = f1_panel._lamp.styleSheet()
        if "#2E7D32" not in ss:  # OK 绿
            print(f"[smoke D] FAIL: e2e F1 面板未进入 ok 态 styleSheet={ss!r}", file=sys.stderr)
            return False
        if "F1 OK" not in f1_panel._status.text():
            print(f"[smoke D] FAIL: e2e F1 状态文字错 {f1_panel._status.text()!r}",
                  file=sys.stderr)
            return False
        print(f"[smoke D] e2e F1 ok: status={f1_panel._status.text()!r}")
        win.close()
        return True
    finally:
        os.environ.pop("LINGXIAO_GUI_FAKE", None)


def main() -> int:
    app = QApplication(sys.argv)
    # 触发命令模块导入 -> 自注册
    import gui.commands  # noqa: F401

    ok = True
    ok &= _test_f2_registered()
    ok &= _test_f2_build_frame()
    ok &= _test_f2_parse_ack()
    ok &= _test_cross_no_match()

    # FakeWorker 单元测试
    fw = FakeWorker()
    fw.open_port("UNIT_TEST")
    ok &= _test_fake_f1(fw)
    ok &= _test_fake_f2_unk(fw)
    ok &= _test_fake_f2_clp(fw)
    fw.close_port()

    # 端到端
    ok &= _test_e2e(app)

    QTimer.singleShot(200, app.quit)
    rc = app.exec()
    print(f"[smoke D] app.exec returned {rc}; overall ok={ok}")
    return 0 if (rc == 0 and ok) else 1


if __name__ == "__main__":
    sys.exit(main())
