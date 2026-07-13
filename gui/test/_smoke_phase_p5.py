# -*- coding: utf-8 -*-
"""P5 烟雾测试：完整参数面板 + 持久化 + 渐隐 + 同步 tracker/bus。

不做真 GL 渲染，验证 settings 数据流：
- 默认值与 P4 一致（无视觉回归）
- _on_panel_value_changed → self._s 写入 + settings_changed emit
- apply_settings 深合并 + 重建场景不崩
- 路径渐隐 fade=True 时 setData 的 color 是 Nx4
- ConfigService 默认值含 "path_viz.settings"
- main.py 启动后 widget 拿到 PathTrackerConfig 同步

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p5
通过：EXIT=0 + [P5-x] 全部 OK。
"""
from __future__ import annotations

import os
import struct
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.config_service import _DEFAULTS  # noqa: E402
from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.widgets.path_visualization_widget import (  # noqa: E402
    DEFAULTS as W_DEFAULTS,
    PathVisualizationPlaceholder,
    _GL_OK,
)


def _snap(pts, pos=(0, 0, 0), vel=(0, 0, 0)):
    return PathSnapshot(
        ts=0.0,
        enabled=True,
        yaw0_deg=0.0,
        pos_cm=pos,
        attitude_deg=(0, 0, 0),
        vel_local_cmps=vel,
        points=tuple(pts),
    )


def case_1_config_default_key() -> None:
    """[P5-1] ConfigService._DEFAULTS 含 path_viz.settings，否则会被白名单过滤丢弃。"""
    assert "path_viz.settings" in _DEFAULTS, "ConfigService 缺 path_viz.settings 登记"
    print("[P5-1] ConfigService 默认含 path_viz.settings OK")


def case_2_defaults_match_p4() -> None:
    """[P5-2] DEFAULTS 数值上等同 P4（不引入视觉回归）。"""
    assert W_DEFAULTS["cube"]["size_cm"] == 20.0
    assert W_DEFAULTS["axis"]["length_cm"] == 30.0
    assert W_DEFAULTS["nose"]["radius_cm"] == 4.0
    assert W_DEFAULTS["vel_arrow"]["scale_cm_per_cmps"] == 0.4
    assert W_DEFAULTS["vel_arrow"]["max_cm"] == 120.0
    assert W_DEFAULTS["path"]["trail_seconds"] == 20.0
    assert W_DEFAULTS["render"]["fps"] == 30
    print("[P5-2] DEFAULTS 与 P4 数值一致 OK")


def case_3_value_changed_emit_and_apply() -> None:
    """[P5-3] _on_panel_value_changed → self._s 写入 + settings_changed emit；apply_settings 不崩。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    assert _GL_OK
    captured: list = []
    w.settings_changed.connect(lambda d: captured.append(d))
    # 模拟控件变更
    w._on_panel_value_changed("cube.size_cm", 40.0)
    assert w._s["cube"]["size_cm"] == 40.0, "self._s 未同步"
    assert captured, "settings_changed 未发"
    last = captured[-1]
    assert last["cube"]["size_cm"] == 40.0
    # apply_settings 反向灌入，再次重建不崩
    w.apply_settings({"vel_arrow": {"scale_cm_per_cmps": 1.0}})
    assert w._s["vel_arrow"]["scale_cm_per_cmps"] == 1.0
    assert w._s["cube"]["size_cm"] == 40.0   # 深合并保留之前的改动
    print("[P5-3] value_changed → self._s + emit + apply_settings 深合并 OK")


def case_4_path_fade_color_array() -> None:
    """[P5-4] fade=True 时 setData 传 Nx4 颜色数组；alpha 从 0 → base 单调上升。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    # 构造 4 个时间点，trail=10s
    now = time.monotonic()
    pts = [
        PathPoint(ts=now - 10.0, x_cm=0, y_cm=0, z_cm=0),    # 最旧：alpha≈0
        PathPoint(ts=now - 5.0,  x_cm=10, y_cm=0, z_cm=0),
        PathPoint(ts=now - 1.0,  x_cm=20, y_cm=0, z_cm=0),
        PathPoint(ts=now,        x_cm=30, y_cm=0, z_cm=0),   # 最新：alpha=base
    ]
    w._s["path"]["trail_seconds"] = 10.0
    w._s["path"]["fade"] = True
    # P8：默认 segmented 模式下 _path 为 None；本用例验证 fade 路径，先切回单线渲染
    w.apply_settings({"path": {"render_mode": "fade"}})
    w.update_snapshot(_snap(pts, pos=(30, 0, 0)))
    # 直接看 GLLinePlotItem 的 color 属性（pyqtgraph 暴露为 numpy）
    colors = getattr(w._path, "color", None)
    assert colors is not None, "path 无 color 属性"
    # 部分版本是 ndarray Nx4，部分版本可能是单 tuple；我们的代码传的是 ndarray
    import numpy as _np
    assert isinstance(colors, _np.ndarray), f"期望 ndarray，得到 {type(colors)}"
    assert colors.shape == (4, 4), f"期望 (4,4)，得到 {colors.shape}"
    alphas = colors[:, 3]
    assert alphas[0] < alphas[-1], f"alpha 应单调上升，得到 {alphas}"
    # 最新点 alpha = base_alpha = 255/255 = 1.0
    assert abs(alphas[-1] - 1.0) < 1e-3
    print(f"[P5-4] fade alpha={[round(float(a), 3) for a in alphas]} OK")


def case_5_path_no_fade_uses_single_color() -> None:
    """[P5-5] fade=False 时所有点颜色相同（兼容 pyqtgraph 0.14：Nx4 numpy）。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    pts = [
        PathPoint(ts=0.0, x_cm=0, y_cm=0, z_cm=0),
        PathPoint(ts=1.0, x_cm=10, y_cm=0, z_cm=0),
    ]
    w._s["path"]["fade"] = False
    # P8：路同上，需切到 fade 单线渲染下验证
    w.apply_settings({"path": {"render_mode": "fade"}})
    w.update_snapshot(_snap(pts, pos=(10, 0, 0)))
    colors = getattr(w._path, "color", None)
    assert colors is not None
    import numpy as _np
    arr = _np.asarray(colors)
    # 兼容多种形状：(4,) 单色 / (N,4) 每点同色
    if arr.ndim == 1:
        assert arr.shape == (4,), f"得到 {arr.shape}"
    else:
        assert arr.ndim == 2 and arr.shape[1] == 4, f"得到 {arr.shape}"
        # 所有行必须相同（单色语义）
        assert _np.allclose(arr - arr[0:1], 0.0), "fade=False 但各点颜色不同"
    print(f"[P5-5] no-fade single color shape={arr.shape} OK")


def case_6_main_window_wires_settings() -> None:
    """[P5-6] MainWindow 启动后 widget.settings_changed → bus 同步 + 写 config。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    os.environ["LINGXIAO_GUI_FAKE"] = "1"
    from gui.main import MainWindow
    win = MainWindow()
    try:
        viz = win._feature_widgets.get("path_visualization")
        assert viz is not None
        # 默认应该已经把 bus 的 fps 拉到 30
        assert win._bus._render_fps == 30
        # 修改 fps 到 60，应同步到 bus
        viz._on_panel_value_changed("render.fps", 60)
        assert win._bus._render_fps == 60, f"bus fps={win._bus._render_fps}"
        # 修改 trail_seconds，应同步到 tracker
        viz._on_panel_value_changed("path.trail_seconds", 9.0)
        assert abs(win._bus.tracker.config.trail_seconds - 9.0) < 1e-6
        # 配置应已落盘缓存（_data 里）
        saved = win._config.get("path_viz.settings", {})
        assert isinstance(saved, dict) and saved.get("render", {}).get("fps") == 60
        # reset：触发 bus.reset_path（不报异常即可）
        viz.reset_requested.emit()
        print("[P5-6] main wiring: bus fps/trail_seconds + 持久化 + reset OK")
    finally:
        try:
            win.close()
        except Exception:
            pass


def main() -> int:
    cases = [
        case_1_config_default_key,
        case_2_defaults_match_p4,
        case_3_value_changed_emit_and_apply,
        case_4_path_fade_color_array,
        case_5_path_no_fade_uses_single_color,
        case_6_main_window_wires_settings,
    ]
    for c in cases:
        try:
            c()
        except AssertionError as exc:
            print(f"[P5 FAIL] {c.__name__}: {exc}")
            return 1
        except Exception as exc:
            print(f"[P5 ERROR] {c.__name__}: {exc!r}")
            return 2
    print("[P5] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
