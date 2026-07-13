# -*- coding: utf-8 -*-
"""P4 烟雾测试：姿态旋转 + 机头小球 + 速度长箭头。

不做真 GL 渲染，只验证 transform 矩阵 / setData 调用结果对不对。
跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p4
通过：EXIT=0 + [P4-x] 全部 OK。
"""
from __future__ import annotations

import math
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QVector3D  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.widgets.path_visualization_widget import (  # noqa: E402
    _NOSE_OFFSET_CM,
    _VEL_ARROW_SCALE,
    PathVisualizationPlaceholder,
    _GL_OK,
)


def _snap(pos=(0, 0, 0), att=(0, 0, 0), vel_local=(0, 0, 0), yaw0=0.0):
    return PathSnapshot(
        ts=0.0,
        enabled=True,
        yaw0_deg=yaw0,
        pos_cm=pos,
        attitude_deg=att,
        vel_local_cmps=vel_local,
        points=(PathPoint(ts=0.0, x_cm=pos[0], y_cm=pos[1], z_cm=pos[2]),),
    )


def case_1_widget_has_p4_items() -> None:
    """[P4-1] widget 应额外含 _nose（机头小球）和 _vel_arrow（速度箭头）。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    assert _GL_OK
    assert w._cube is not None and w._axis is not None
    assert w._nose is not None and w._vel_arrow is not None
    print("[P4-1] widget has cube/axis/nose/vel_arrow OK")


def case_2_attitude_rotates_nose() -> None:
    """[P4-2] yaw_local=90° 时机头小球应在 cube 的 -y 方向。

    渲染端 yaw 翻号约定（widget 处 `m.rotate(-yaw_local,...)`）：
    pyqtgraph 是 CCW 正，传入 -90° 即 CW 90°，把机体 +x 映射到世界 -y。
    这与"现实 CW yaw → GUI cube 同方向 CW"的用户视觉期望一致。
    """
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    # pos=(0,0,0), yaw=90°, yaw0=0 → yaw_local=90° → render 用 -90° (CW 90°)
    w.update_snapshot(_snap(pos=(0, 0, 0), att=(0, 0, 90.0), yaw0=0.0))
    p = w._nose.transform().map(QVector3D(0.0, 0.0, 0.0))
    # 期望：(0,0,0) + Rz(-90)·(NOSE_OFFSET,0,0) = (0, -NOSE_OFFSET, 0)
    assert abs(p.x()) < 1e-4, f"nose.x 应≈0, got {p.x()}"
    assert abs(p.y() + _NOSE_OFFSET_CM) < 1e-4, f"nose.y 应≈{-_NOSE_OFFSET_CM}, got {p.y()}"
    assert abs(p.z()) < 1e-4
    print(f"[P4-2] nose at yaw=90° world pos=({p.x():.2f},{p.y():.2f},{p.z():.2f}) OK")


def case_3_yaw0_subtracted() -> None:
    """[P4-3] yaw=120°, yaw0=120° → yaw_local=0°，机头应在 +x 方向。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    w.update_snapshot(_snap(pos=(10, 20, 30), att=(0, 0, 120.0), yaw0=120.0))
    p = w._nose.transform().map(QVector3D(0.0, 0.0, 0.0))
    assert abs(p.x() - (10 + _NOSE_OFFSET_CM)) < 1e-4, f"got {p.x()}"
    assert abs(p.y() - 20) < 1e-4
    assert abs(p.z() - 30) < 1e-4
    print("[P4-3] yaw0 subtraction OK (机头在世界 +x)")


def case_4_velocity_arrow_endpoint() -> None:
    """[P4-4] 速度 (vx_l=100, 0, 0) 时箭头末端 = pos + (100*scale, 0, 0)。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    w.update_snapshot(_snap(pos=(50, 60, 70), vel_local=(100.0, 0.0, 0.0)))
    pts = w._vel_arrow.pos  # numpy (2,3)
    assert pts.shape == (2, 3)
    expected_end_x = 50 + 100 * _VEL_ARROW_SCALE
    assert abs(pts[0][0] - 50) < 1e-4 and abs(pts[0][1] - 60) < 1e-4 and abs(pts[0][2] - 70) < 1e-4
    assert abs(pts[1][0] - expected_end_x) < 1e-4, f"end.x got {pts[1][0]}"
    assert abs(pts[1][1] - 60) < 1e-4
    assert abs(pts[1][2] - 70) < 1e-4
    print(f"[P4-4] vel arrow end=({pts[1][0]:.2f},{pts[1][1]:.2f},{pts[1][2]:.2f}) OK")


def case_5_velocity_zero_collapses_arrow() -> None:
    """[P4-5] 速度近零时箭头压成零长度（首尾同点），避免抖动。"""
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    w.update_snapshot(_snap(pos=(0, 0, 0), vel_local=(0.3, -0.2, 0.0)))
    pts = w._vel_arrow.pos
    assert (pts[0] == pts[1]).all(), f"应零长度, got {pts}"
    print("[P4-5] near-zero speed collapses arrow OK")


def case_6_velocity_decoupled_from_attitude() -> None:
    """[P4-6] 速度箭头方向只由 vel_local 决定，与姿态无关。

    yaw=90° 但速度向量 (vx_l=100,0,0) 仍指向世界 +x，不应跟着 yaw 转。
    （因为 vel_local 已经是 PathTracker 反旋转后的局部世界系坐标。）
    """
    _app = QApplication.instance() or QApplication(sys.argv)
    w = PathVisualizationPlaceholder()
    w.update_snapshot(_snap(pos=(0, 0, 0), att=(0, 0, 90.0), vel_local=(100.0, 0.0, 0.0)))
    pts = w._vel_arrow.pos
    expected_end_x = 100 * _VEL_ARROW_SCALE
    assert abs(pts[1][0] - expected_end_x) < 1e-4
    assert abs(pts[1][1]) < 1e-4, f"vel arrow 不应被姿态影响, got y={pts[1][1]}"
    print("[P4-6] velocity arrow decoupled from attitude OK")


def main() -> int:
    try:
        case_1_widget_has_p4_items()
        case_2_attitude_rotates_nose()
        case_3_yaw0_subtracted()
        case_4_velocity_arrow_endpoint()
        case_5_velocity_zero_collapses_arrow()
        case_6_velocity_decoupled_from_attitude()
    except AssertionError as exc:
        import traceback
        traceback.print_exc()
        print(f"[P4 FAIL] {exc}")
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[P4 ERROR] {exc}")
        return 2
    print("[P4] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
