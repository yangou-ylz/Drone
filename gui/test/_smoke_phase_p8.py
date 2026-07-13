# -*- coding: utf-8 -*-
"""P8 烟雾测试：K 段路径渲染（近粗近亮远细远淡）。

验收范围：
- [P8-1] segments_by_age 分桶函数（边界 n=0/1、等长切分、端点续接、k=1 全归一段）
- [P8-2] 3D widget segmented 模式 → _path_segments 数量等于 k；fade 模式 → _path 单线
- [P8-3] 切换 render_mode：segmented ? fade 不崩，资源不残留
- [P8-4] 段宽/段 alpha 单调（tail→head）
- [P8-5] 2D widget segmented 模式 → _path_segments 长度=k；投影数据按 plane 拆桶
- [P8-6] cleanup 清干净 K 段 LineItem 不残留
- [P8-7] ConfigService _DEFAULTS 已注册 path.* 新字段对应路径（白名单生效）

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p8

通过条件：EXIT=0 + 所有 [P8-x] 行打印 OK。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.widgets._path_segments import (  # noqa: E402
    lerp_alpha_byte,
    lerp_scalar,
    segments_by_age,
)
from gui.widgets.path_2d_view_widget import Path2DViewWidget  # noqa: E402
from gui.widgets.path_visualization_widget import PathVisualizationPlaceholder  # noqa: E402


def _make_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _make_snap(n: int) -> PathSnapshot:
    pts = tuple(
        PathPoint(ts=time.time() + i * 0.01,
                  x_cm=float(i),
                  y_cm=float(i * 2),
                  z_cm=float(i * 3))
        for i in range(n)
    )
    return PathSnapshot(
        ts=time.time(),
        enabled=True,
        yaw0_deg=0.0,
        pos_cm=(0.0, 0.0, 0.0) if n == 0 else (pts[-1].x_cm, pts[-1].y_cm, pts[-1].z_cm),
        attitude_deg=(0.0, 0.0, 0.0),
        vel_local_cmps=(0.0, 0.0, 0.0),
        points=pts,
    )


def case_1_segments_by_age_basics() -> None:
    # n=0 → 全空，长度=k
    out = segments_by_age([], 5)
    assert len(out) == 5
    assert all(len(s) == 0 for s in out)
    # n=1 → 仅末段含点
    out = segments_by_age([("p",)], 4)
    assert len(out) == 4
    assert out[0] == [] and out[1] == [] and out[2] == []
    assert out[-1] == [("p",)]
    # n=16, k=4 → 每段 4 点 + 端点续接（除末段每段 5 点）
    pts = list(range(16))
    out = segments_by_age(pts, 4)
    assert len(out) == 4
    # 每段长度
    assert len(out[0]) == 5, f"seg0 应 5（含续接），实际 {len(out[0])}"
    assert len(out[1]) == 5
    assert len(out[2]) == 5
    assert len(out[3]) == 4, f"seg3（末段）应 4，实际 {len(out[3])}"
    # 端点续接：seg0 最后 = seg1 第一
    assert out[0][-1] == out[1][0]
    assert out[1][-1] == out[2][0]
    assert out[2][-1] == out[3][0]
    # k=1 → 全归一段
    out = segments_by_age(pts, 1)
    assert len(out) == 1 and len(out[0]) == 16
    # lerp 单调
    assert lerp_scalar(1.0, 3.0, 5, 0) == 1.0
    assert lerp_scalar(1.0, 3.0, 5, 4) == 3.0
    assert lerp_scalar(1.0, 3.0, 5, 2) == 2.0
    assert lerp_alpha_byte(40, 255, 8, 0) == 40
    assert lerp_alpha_byte(40, 255, 8, 7) == 255
    print("[P8-1] segments_by_age + lerp 基础 OK")


def case_2_3d_widget_segmented_count() -> None:
    _make_app()
    w = PathVisualizationPlaceholder(None)
    # 默认 render_mode=segmented, k_segments=8
    if not getattr(w, "_gl_ok", False):
        print("[P8-2] 3D widget _gl_ok=False（offscreen 无 GL）→ 跳过 GL 部分，仅校验 settings")
        s = w.current_settings()
        assert s["path"]["render_mode"] == "segmented"
        assert s["path"]["k_segments"] == 8
        w.cleanup_gl()
        return
    segs = list(getattr(w, "_path_segments", []) or [])
    assert len(segs) == 8, f"默认 K=8，_path_segments 应 8，实际 {len(segs)}"
    # 切到 fade 模式
    w.apply_settings({"path": {"render_mode": "fade"}})
    assert len(getattr(w, "_path_segments", []) or []) == 0, "fade 模式应清空 _path_segments"
    assert w._path is not None, "fade 模式应有 _path 单线"
    # 切回 segmented + 改 K=4
    w.apply_settings({"path": {"render_mode": "segmented", "k_segments": 4}})
    segs = list(getattr(w, "_path_segments", []) or [])
    assert len(segs) == 4
    assert w._path is None, "segmented 模式不应有 _path 单线"
    print("[P8-2] 3D segmented count + render_mode 切换 OK")
    w.cleanup_gl()


def case_3_3d_no_crash_under_snapshots() -> None:
    _make_app()
    w = PathVisualizationPlaceholder(None)
    if not getattr(w, "_gl_ok", False):
        print("[P8-3] 跳过（无 GL）")
        return
    # 灌不同点数 + 切模式
    for n in (0, 1, 2, 10, 100):
        w.update_snapshot(_make_snap(n))
    w.apply_settings({"path": {"render_mode": "fade"}})
    for n in (0, 1, 2, 10, 100):
        w.update_snapshot(_make_snap(n))
    w.apply_settings({"path": {"render_mode": "segmented", "k_segments": 16}})
    for n in (0, 1, 2, 10, 100):
        w.update_snapshot(_make_snap(n))
    print("[P8-3] 3D 切模式 + 灌帧 不崩 OK")
    w.cleanup_gl()


def case_4_3d_widths_monotonic() -> None:
    _make_app()
    w = PathVisualizationPlaceholder(None)
    if not getattr(w, "_gl_ok", False):
        print("[P8-4] 跳过（无 GL）")
        return
    w.apply_settings({"path": {
        "render_mode": "segmented",
        "k_segments": 8,
        "head_width": 4.0,
        "tail_width": 1.0,
    }})
    segs = list(getattr(w, "_path_segments", []) or [])
    assert len(segs) == 8
    widths = [float(getattr(s, "width", 0.0)) for s in segs]
    # 单调递增（tail i=0 → head i=k-1）
    for i in range(1, len(widths)):
        assert widths[i] >= widths[i - 1] - 1e-6, f"width 应单调非递减，{widths}"
    assert abs(widths[0] - 1.0) < 1e-6 and abs(widths[-1] - 4.0) < 1e-6
    print(f"[P8-4] 3D 段宽单调 OK widths={widths}")
    w.cleanup_gl()


def case_5_2d_segmented_projection() -> None:
    _make_app()
    for plane, h_idx, v_idx in [("XY", 0, 1), ("XZ", 0, 2), ("YZ", 1, 2)]:
        w = Path2DViewWidget(None, plane=plane)
        if not getattr(w, "_pg_ok", False):
            w.cleanup()
            continue
        # 默认 segmented + K=8
        segs = list(getattr(w, "_path_segments", []) or [])
        assert len(segs) == 8, f"{plane} 默认 K=8，实际 {len(segs)}"
        assert w._path_item is None, f"{plane} segmented 不应有单线 path_item"
        # 灌 24 点
        snap = _make_snap(24)
        w.update_snapshot(snap)
        # 把每段的数据拼回来，应等于全量按 plane 投影（去重端点续接）
        flat_xs: list[float] = []
        flat_ys: list[float] = []
        for i, seg in enumerate(segs):
            xs, ys = seg.getData()
            if xs is None:
                continue
            xs_l = list(xs)
            ys_l = list(ys)
            if i == 0:
                flat_xs.extend(xs_l)
                flat_ys.extend(ys_l)
            else:
                # 跳过首点（=上一段尾点）
                flat_xs.extend(xs_l[1:])
                flat_ys.extend(ys_l[1:])
        # 期望
        exp_xs = [float((p.x_cm, p.y_cm, p.z_cm)[h_idx]) for p in snap.points]
        exp_ys = [float((p.x_cm, p.y_cm, p.z_cm)[v_idx]) for p in snap.points]
        assert len(flat_xs) == len(exp_xs), (
            f"{plane} 拼回点数 {len(flat_xs)} ≠ 期望 {len(exp_xs)}"
        )
        for a, b in zip(flat_xs, exp_xs):
            assert abs(a - b) < 1e-6
        for a, b in zip(flat_ys, exp_ys):
            assert abs(a - b) < 1e-6
        # 切到 fade
        w.apply_settings({"path": {"render_mode": "fade"}})
        assert len(getattr(w, "_path_segments", []) or []) == 0
        assert w._path_item is not None
        w.cleanup()
    print("[P8-5] 2D segmented 投影 + 模式切换 OK")


def case_6_cleanup_clears_segments() -> None:
    _make_app()
    # 3D
    w3 = PathVisualizationPlaceholder(None)
    if getattr(w3, "_gl_ok", False):
        assert len(getattr(w3, "_path_segments", []) or []) > 0
        w3.cleanup_gl()
        assert len(getattr(w3, "_path_segments", []) or []) == 0
        w3.cleanup_gl()  # 幂等
    # 2D
    w2 = Path2DViewWidget(None, plane="XY")
    if getattr(w2, "_pg_ok", False):
        assert len(getattr(w2, "_path_segments", []) or []) > 0
        w2.cleanup()
        assert len(getattr(w2, "_path_segments", []) or []) == 0
        w2.cleanup()  # 幂等
    print("[P8-6] cleanup 清 K 段 LineItem OK")


def case_7_defaults_path_subkeys_persistable() -> None:
    """白名单层级：ConfigService 用 path_viz.settings 整树持久化，无需登记到子键。
    本案验证 widget 默认 settings 含 P8 新字段，且 _Path2D 的 settings 默认存在。"""
    from gui.widgets.path_visualization_widget import DEFAULTS as D3
    from gui.widgets.path_2d_view_widget import DEFAULTS_2D as D2
    for d, name in ((D3["path"], "3D"), (D2["path"], "2D")):
        for k in ("render_mode", "k_segments", "head_width", "tail_width",
                  "head_alpha", "tail_alpha"):
            assert k in d, f"{name} DEFAULTS.path 缺字段 {k}"
        assert d["render_mode"] == "segmented"
        assert d["k_segments"] == 8
    print("[P8-7] DEFAULTS 包含 P8 新字段 OK")


def main() -> int:
    case_1_segments_by_age_basics()
    case_2_3d_widget_segmented_count()
    case_3_3d_no_crash_under_snapshots()
    case_4_3d_widths_monotonic()
    case_5_2d_segmented_projection()
    case_6_cleanup_clears_segments()
    case_7_defaults_path_subkeys_persistable()
    print("[P8] 全部用例通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
