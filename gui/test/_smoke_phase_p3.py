# -*- coding: utf-8 -*-
"""P3 烟雾测试：3D 渲染管线 + path_updated → widget.update_snapshot 端到端。

仅自动验证逻辑（构造合成数据、检查立方体 transform / 路径线点数）；
3D 画面是否"好看"由 _demo_p3_visual.py 让用户目测。

跑法（必须用 3.13 解释器）：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p3
通过条件：EXIT=0 + [P3-x] 全部 OK。
"""
from __future__ import annotations

import math
import os
import struct
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# headless 模式 + 强制 FakeWorker 避免真串口探测
os.environ.setdefault("LINGXIAO_GUI_FAKE", "1")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.io.protocol import Frame  # noqa: E402
from gui.widgets.path_visualization_widget import (  # noqa: E402
    PathVisualizationPlaceholder,
    _GL_OK,
)


def _make_frame(cmd: int, data: bytes) -> Frame:
    return Frame(dest=0xAF, cmd=cmd, data=data, sc=0, ac=0, raw=b"")


def _quat_data(yaw_deg: float) -> bytes:
    cy = math.cos(math.radians(yaw_deg) / 2.0)
    sy = math.sin(math.radians(yaw_deg) / 2.0)
    v0, v1, v2, v3 = int(cy * 10000), 0, 0, int(sy * 10000)
    return struct.pack("<hhhhB", v0, v1, v2, v3, 0)


def _height_data(cm: int) -> bytes:
    return struct.pack("<iiB", cm, 0, 0)


def _velocity_data(vx: int, vy: int, vz: int) -> bytes:
    return struct.pack("<hhh", vx, vy, vz)


def case_1_widget_constructs() -> None:
    """[P3-1] Widget 能在 GL 可用时构造出 GLViewWidget；缺依赖时降级。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    assert _GL_OK, "本环境 pyqtgraph.opengl 不可用，P3 视觉验收无法进行"
    assert w._gl_ok is True
    assert w._view is not None and w._cube is not None and w._path is not None
    w.deleteLater()
    print("[P3-1] widget constructs OK (GL available)")


def case_2_update_snapshot_safe_empty() -> None:
    """[P3-2] None / 空快照 / 异常 snap 不应让 widget 崩溃。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    w.update_snapshot(None)  # 不抛
    class _Bad:
        pos_cm = "oops"
        points = ()
    w.update_snapshot(_Bad())  # 不抛
    print("[P3-2] update_snapshot tolerates bad input OK")


def case_3_end_to_end_through_main() -> None:
    """[P3-3] MainWindow → TelemetryBus.feed_frame → widget 立方体位置正确。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    # 先确保 features.path_visualization=True，否则 bus.set_render_enabled 默认关
    from gui.services.config_service import ConfigService
    cfg = ConfigService()
    cfg.set("features.path_visualization", True)
    # 延迟 import MainWindow，绕开 module level QApplication 创建
    from gui.main import MainWindow
    win = MainWindow()
    win.show()
    _app.processEvents()
    widget = win._feature_widgets.get("path_visualization")
    assert widget is not None and getattr(widget, "_gl_ok", False), "widget 未启用 3D"
    # 喂帧：yaw=0 → 局部=世界；vx=100 cm/s 持续 1s → x≈100 cm
    win._bus.feed_frame(_make_frame(0x04, _quat_data(0.0)))
    win._bus.feed_frame(_make_frame(0x05, _height_data(80)))
    win._bus.feed_frame(_make_frame(0x07, _velocity_data(100, 0, 0)))  # 基准
    # 拉高 fps + 手工模拟时间：bus 内部 dt 是真实 monotonic 差，
    # 用 sleep 跑 0.3s 让 dt 真实推进
    import time as _t
    win._bus.set_render_fps(120)
    _t.sleep(0.05)
    win._bus.feed_frame(_make_frame(0x07, _velocity_data(100, 0, 0)))
    _t.sleep(0.05)
    win._bus.feed_frame(_make_frame(0x07, _velocity_data(100, 0, 0)))
    _t.sleep(0.05)
    win._bus.feed_frame(_make_frame(0x07, _velocity_data(100, 0, 0)))
    _app.processEvents()
    # 验证立方体位置 ≈ 累计积分（vx=100 * 累计 dt）
    snap = win._bus.tracker.snapshot()
    x, y, z = snap.pos_cm
    assert 5.0 < x < 50.0, f"立方体 x 应在 5~50cm 之间（按 ~3*0.05s 积分），got {x}"
    assert abs(y) < 1e-2, f"y 应≈0, got {y}"
    assert abs(z - 80.0) < 1e-6, f"z 应=alt_fu_cm=80, got {z}"
    # 路径点数 ≥ 3
    assert len(snap.points) >= 3, f"路径点应 ≥3, got {len(snap.points)}"
    win.close()
    _app.processEvents()
    print(f"[P3-3] e2e OK (cube=({x:.2f},{y:.2f},{z:.2f}), pts={len(snap.points)})")


def main() -> int:
    try:
        case_1_widget_constructs()
        case_2_update_snapshot_safe_empty()
        case_3_end_to_end_through_main()
    except AssertionError as exc:
        import traceback
        traceback.print_exc()
        print(f"[P3 FAIL] {exc}")
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[P3 ERROR] {exc}")
        return 2
    print("[P3] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
