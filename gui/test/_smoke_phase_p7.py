# -*- coding: utf-8 -*-
"""P7 烟雾测试：2D 投影视图（Path2DViewWidget）+ 多 Dock 注册。

验收范围：
- [P7-1] 三平面构造（XY/XZ/YZ）均不抛异常
- [P7-2] 投影一致性：XY=(x,y) / XZ=(x,z) / YZ=(y,z)
- [P7-3] update_snapshot 后 path 数据点数等于传入 snap.points 长度
- [P7-4] apply_settings 深合并（保留未指定字段）+ current_settings 深拷贝
- [P7-5] cleanup 幂等（重复调用不抛）
- [P7-6] _FEATURE_DOCKS 注册了 4 个 path_visualization* 条目（3D + XY/XZ/YZ）

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p7

通过条件：EXIT=0 + 所有 [P7-x] 行打印 OK。
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.widgets.path_2d_view_widget import (  # noqa: E402
    DEFAULTS_2D,
    Path2DViewWidget,
    _PLANE_TABLE,
)


def _make_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_snap(points: list[tuple[float, float, float]],
               pos: tuple[float, float, float] = (0.0, 0.0, 0.0),
               yaw_deg: float = 0.0) -> PathSnapshot:
    pts = tuple(
        PathPoint(ts=time.time() + i * 0.01, x_cm=x, y_cm=y, z_cm=z)
        for i, (x, y, z) in enumerate(points)
    )
    return PathSnapshot(
        ts=time.time(),
        enabled=True,
        yaw0_deg=0.0,
        pos_cm=pos,
        attitude_deg=(0.0, 0.0, yaw_deg),
        vel_local_cmps=(0.0, 0.0, 0.0),
        points=pts,
    )


def case_1_construct_all_planes() -> None:
    _make_app()
    widgets = []
    for plane in ("XY", "XZ", "YZ"):
        w = Path2DViewWidget(None, plane=plane)
        assert w.plane == plane, f"plane 属性应为 {plane}，实际 {w.plane}"
        widgets.append(w)
    print("[P7-1] 三平面构造 OK")
    for w in widgets:
        w.cleanup()
        w.deleteLater()


def case_2_projection_consistency() -> None:
    """投影正确性：注入 (x,y,z) 后 path 数据应是相应两轴。"""
    _make_app()
    cases = [
        ("XY", 0, 1),
        ("XZ", 0, 2),
        ("YZ", 1, 2),
    ]
    pts = [(10.0, 20.0, 30.0), (40.0, 50.0, 60.0), (70.0, 80.0, 90.0)]
    snap = _make_snap(pts, pos=pts[-1])
    for plane, h_idx, v_idx in cases:
        w = Path2DViewWidget(None, plane=plane)
        # P8：默认 segmented；本用例校验 fade 单线投影，先切回 fade
        w.apply_settings({"path": {"render_mode": "fade"}})
        w.update_snapshot(snap)
        if not getattr(w, "_pg_ok", False):
            # 没装 pyqtgraph：只验证投影表本身
            assert _PLANE_TABLE[plane][2] == h_idx
            assert _PLANE_TABLE[plane][3] == v_idx
        else:
            # 检查 PlotDataItem 数据
            xs, ys = w._path_item.getData()
            assert xs is not None and ys is not None, f"{plane} path 数据为空"
            assert len(xs) == len(pts), f"{plane} 点数应 {len(pts)}，实际 {len(xs)}"
            for i, (x, y, z) in enumerate(pts):
                expected_h = (x, y, z)[h_idx]
                expected_v = (x, y, z)[v_idx]
                assert abs(xs[i] - expected_h) < 1e-6, (
                    f"{plane} h 轴第 {i} 点应 {expected_h}，实际 {xs[i]}"
                )
                assert abs(ys[i] - expected_v) < 1e-6, (
                    f"{plane} v 轴第 {i} 点应 {expected_v}，实际 {ys[i]}"
                )
        w.cleanup()
        w.deleteLater()
    print("[P7-2] 投影一致性 OK")


def case_3_update_snapshot_point_count() -> None:
    _make_app()
    w = Path2DViewWidget(None, plane="XY")
    # P8：默认 segmented；本用例用 fade 单线点数语义验证
    w.apply_settings({"path": {"render_mode": "fade"}})
    for n in (0, 1, 5, 50):
        pts = [(float(i), float(i * 2), 0.0) for i in range(n)]
        snap = _make_snap(pts)
        w.update_snapshot(snap)
        if getattr(w, "_pg_ok", False):
            xs, ys = w._path_item.getData()
            if n == 0:
                actual = 0 if xs is None else len(xs)
            else:
                actual = len(xs)
            assert actual == n, f"n={n}：path 点数应 {n}，实际 {actual}"
    print("[P7-3] update_snapshot 点数一致 OK")
    w.cleanup()
    w.deleteLater()


def case_4_apply_settings_deep_merge() -> None:
    _make_app()
    w = Path2DViewWidget(None, plane="XY")
    # 只覆盖 path.width，其他字段应原样保留
    w.apply_settings({"path": {"width": 5.5}})
    cur = w.current_settings()
    assert cur["path"]["width"] == 5.5
    # color / antialias 应保持默认
    assert cur["path"]["color"] == DEFAULTS_2D["path"]["color"]
    assert cur["path"]["antialias"] == DEFAULTS_2D["path"]["antialias"]
    # icon 整组未碰
    assert cur["icon"] == DEFAULTS_2D["icon"]
    # current_settings 必须是深拷贝
    cur["path"]["width"] = 999.0
    assert w.current_settings()["path"]["width"] == 5.5, "current_settings 不是深拷贝"
    print("[P7-4] apply_settings 深合并 + current_settings 深拷贝 OK")
    w.cleanup()
    w.deleteLater()


def case_5_cleanup_idempotent() -> None:
    _make_app()
    w = Path2DViewWidget(None, plane="XZ")
    snap = _make_snap([(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)])
    w.update_snapshot(snap)
    w.cleanup()
    w.cleanup()  # 二次调用不应抛异常
    # 再 update 也不应抛
    w.update_snapshot(snap)
    print("[P7-5] cleanup 幂等 OK")
    w.deleteLater()


def case_6_feature_docks_registry() -> None:
    """注册表应包含 4 个 path_visualization* 条目（3D + 3 个 2D 平面）。"""
    from gui.main import _FEATURE_DOCKS, _PATH_VIZ_KEYS, _PATH_VIZ_2D

    keys = [item[0] for item in _FEATURE_DOCKS]
    expected = {"path_visualization", "path_visualization_xy",
                "path_visualization_xz", "path_visualization_yz"}
    missing = expected - set(keys)
    assert not missing, f"_FEATURE_DOCKS 缺失：{missing}"
    assert set(_PATH_VIZ_KEYS) == expected, "_PATH_VIZ_KEYS 应与四个 viz feature 一致"
    assert set(_PATH_VIZ_2D.keys()) == expected - {"path_visualization"}
    # ConfigService 默认值同步登记（白名单设计）
    from gui.services.config_service import _DEFAULTS  # type: ignore
    for k in expected:
        assert f"features.{k}" in _DEFAULTS, f"_DEFAULTS 缺 features.{k}"
    for cfg_k in ("path_viz_2d.xy.settings", "path_viz_2d.xz.settings",
                  "path_viz_2d.yz.settings", "ui.main_window_state"):
        assert cfg_k in _DEFAULTS, f"_DEFAULTS 缺 {cfg_k}"
    print("[P7-6] _FEATURE_DOCKS + _DEFAULTS 注册完整 OK")


def main() -> int:
    case_1_construct_all_planes()
    case_2_projection_consistency()
    case_3_update_snapshot_point_count()
    case_4_apply_settings_deep_merge()
    case_5_cleanup_idempotent()
    case_6_feature_docks_registry()
    print("[P7] 全部用例通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
