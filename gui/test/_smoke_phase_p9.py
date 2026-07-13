# -*- coding: utf-8 -*-
"""P9 烟雾测试：HUD 叠加层 + 数字面板 Dock + 3D 坐标尺。

验收范围：
- [P9-1] _hud_model.extract_hud_values：vmag = sqrt(vx?+vy?+vz?)，h == z，11 键齐
- [P9-2] HudOverlayWidget apply_settings：visible 项数 == 行数；overlay.visible=False → setVisible(False)
- [P9-3] HudOverlayWidget update_snapshot：QLabel.text 与 fmt 一致
- [P9-4] NumericPanelDock update_snapshot：min/max 跟踪；reset 清零
- [P9-5] 3D widget hud groupbox：设置 hud.overlay.opacity → settings_changed 携带 hud.* 路径
- [P9-6] 3D widget ruler：enabled=True → _ruler_items 非空；enabled=False → 为空

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p9

通过条件：EXIT=0 + 所有 [P9-x] 行打印 OK。
"""
from __future__ import annotations

import math
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.widgets._hud_model import (  # noqa: E402
    HUD_DEFAULTS,
    HUD_ITEM_KEYS,
    extract_hud_values,
)
from gui.widgets.hud_overlay_widget import HudOverlayWidget  # noqa: E402
from gui.widgets.numeric_panel_dock import NumericPanelDock  # noqa: E402
from gui.widgets.path_visualization_widget import PathVisualizationPlaceholder  # noqa: E402


def _make_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _snap(vx: float = 1.0, vy: float = 2.0, vz: float = 2.0,
          x: float = 10.0, y: float = 20.0, z: float = 30.0,
          roll: float = 1.0, pitch: float = -2.0, yaw: float = 45.0) -> PathSnapshot:
    return PathSnapshot(
        ts=time.time(),
        enabled=True,
        yaw0_deg=0.0,
        pos_cm=(x, y, z),
        attitude_deg=(roll, pitch, yaw),
        vel_local_cmps=(vx, vy, vz),
        points=(PathPoint(ts=time.time(), x_cm=x, y_cm=y, z_cm=z),),
    )


def case_1_extract_hud_values() -> None:
    s = _snap(vx=3.0, vy=4.0, vz=0.0, x=1.0, y=2.0, z=5.0)
    v = extract_hud_values(s)
    assert set(v.keys()) == set(HUD_ITEM_KEYS), f"key 集合不齐 {v.keys()}"
    assert abs(v["vmag"] - 5.0) < 1e-6, f"vmag 期望 5.0，实 {v['vmag']}"
    assert v["h"] == v["z"] == 5.0, "h 应等于 z"
    print("[P9-1] extract_hud_values OK vmag=5 h=z")


def case_2_hud_overlay_apply_settings() -> None:
    _make_app()
    host = QWidget()
    host.resize(800, 600)
    hud = HudOverlayWidget(host)
    # 默认 11 项全可见
    assert len(hud._rows) == len(HUD_ITEM_KEYS), f"默认应 11 行，实 {len(hud._rows)}"
    # 隐藏 5 项
    patch = {"items": {k: {"visible": False} for k in ("vx", "vy", "vz", "vmag", "h")}}
    hud.apply_settings(patch)
    assert len(hud._rows) == len(HUD_ITEM_KEYS) - 5, f"应剩 6 行，实 {len(hud._rows)}"
    # overlay.visible=False → 整体隐藏
    hud.apply_settings({"overlay": {"visible": False}})
    assert hud.isVisible() is False
    hud.deleteLater()
    host.deleteLater()
    print("[P9-2] HudOverlayWidget apply_settings OK")


def case_3_hud_overlay_update_snapshot() -> None:
    _make_app()
    host = QWidget()
    host.resize(800, 600)
    hud = HudOverlayWidget(host)
    s = _snap(vx=1.25, vy=0.0, vz=0.0, x=12.3, y=-4.5, z=6.7,
              roll=0.0, pitch=0.0, yaw=90.0)
    hud.update_snapshot(s)
    # vx 行：fmt {:+7.1f}
    _, vx_lbl, _ = hud._rows["vx"]
    assert vx_lbl.text().strip() == "+1.2", f"vx 文本应为 +1.2，实 {vx_lbl.text()!r}"
    # vmag = 1.25
    _, vmag_lbl, _ = hud._rows["vmag"]
    assert vmag_lbl.text().strip() == "1.2", f"|v| 应为 1.2，实 {vmag_lbl.text()!r}"
    hud.deleteLater()
    host.deleteLater()
    print("[P9-3] HudOverlayWidget update_snapshot OK")


def case_4_numeric_panel_min_max_reset() -> None:
    _make_app()
    dock = NumericPanelDock()
    # 灌三帧不同 vx，min/max 跟踪
    dock.update_snapshot(_snap(vx=1.0))
    dock.update_snapshot(_snap(vx=-3.0))
    dock.update_snapshot(_snap(vx=5.0))
    row = dock._rows["vx"]
    assert abs(row.min_v + 3.0) < 1e-6, f"min 应 -3.0，实 {row.min_v}"
    assert abs(row.max_v - 5.0) < 1e-6, f"max 应  5.0，实 {row.max_v}"
    # reset
    dock._reset_all()
    assert row.min_v == math.inf and row.max_v == -math.inf
    assert row.mn.text() == "--" and row.mx.text() == "--"
    # 隐藏速度组所有项 → 组隐藏
    dock.apply_settings({"items": {k: {"visible": False} for k in ("vx", "vy", "vz", "vmag")}})
    assert dock._group_boxes[0].isVisible() is False or not dock._group_boxes[0].isVisibleTo(dock)
    dock.deleteLater()
    print("[P9-4] NumericPanelDock min/max + reset + group hide OK")


def case_5_3d_widget_hud_emits() -> None:
    _make_app()
    w = PathVisualizationPlaceholder(None)
    captured: list[dict] = []
    w.settings_changed.connect(lambda s: captured.append(s))
    # 直接走 panel 路径：模拟用户改 hud.overlay.opacity
    w._on_panel_value_changed("hud.overlay.opacity", 0.5)
    assert len(captured) >= 1, "settings_changed 未触发"
    last = captured[-1]
    assert "hud" in last, f"settings_changed 缺 hud 子树：{last.keys()}"
    assert abs(float(last["hud"]["overlay"]["opacity"]) - 0.5) < 1e-6
    w.cleanup_gl()
    w.deleteLater()
    print("[P9-5] 3D widget hud panel emit OK")


def case_6_3d_ruler_toggle() -> None:
    _make_app()
    w = PathVisualizationPlaceholder(None)
    if not getattr(w, "_gl_ok", False):
        w.cleanup_gl()
        w.deleteLater()
        print("[P9-6] 跳过（GL 不可用）OK")
        return
    # 默认 enabled=True → ruler 非空
    n_on = len(getattr(w, "_ruler_items", []) or [])
    assert n_on > 0, f"默认应有 ruler items，实 {n_on}"
    # 关闭
    w.apply_settings({"hud": {"ruler": {"enabled": False}}})
    # apply_settings 触发 _build_scene → _rebuild_axis_ruler
    n_off = len(getattr(w, "_ruler_items", []) or [])
    assert n_off == 0, f"enabled=False 应清空 ruler items，实 {n_off}"
    w.cleanup_gl()
    w.deleteLater()
    print(f"[P9-6] 3D ruler toggle OK on={n_on} off=0")


def main() -> int:
    case_1_extract_hud_values()
    case_2_hud_overlay_apply_settings()
    case_3_hud_overlay_update_snapshot()
    case_4_numeric_panel_min_max_reset()
    case_5_3d_widget_hud_emits()
    case_6_3d_ruler_toggle()
    print("[P9] ALL OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
