# -*- coding: utf-8 -*-
"""HUD 共享数据模型（P9）。

供 `hud_overlay_widget.py`（3D 叠加层）和 `numeric_panel_dock.py`（独立 Dock）
共用：
- `HUD_ITEM_KEYS`：11 项固定顺序键
- `HUD_ITEM_META`：每项默认显示文本/单位/格式
- `HUD_DEFAULTS`：完整设置树（items / overlay / ruler 三组）
- `extract_hud_values(snapshot)`：把 PathSnapshot 转成 {key: float}
- `_deep_merge(...)`：与 widget 同款合并工具（避免循环依赖）

设计要点：
- 11 项是"哪些指标可显示"的统一集合，HUD 叠加层和数字面板共用同一份开关，
  改一处三处同步（main.py 统一 broker：path_viz.hud.settings）。
- 每项 visible 默认 True；用户可在任一面板里取消勾选。
"""

from __future__ import annotations

import copy
import math
from typing import Any

# ----------------------- 固定的 11 项指标 -----------------------
HUD_ITEM_KEYS: tuple[str, ...] = (
    "vx", "vy", "vz", "vmag",
    "roll", "pitch", "yaw",
    "x", "y", "z", "h",
)

# 每项的默认元数据（label/单位/格式）。fmt 用 Python 格式串，参数为 float。
HUD_ITEM_META: dict[str, dict[str, str]] = {
    "vx":   {"label": "vx",    "unit": "cm/s", "fmt": "{:+7.1f}"},
    "vy":   {"label": "vy",    "unit": "cm/s", "fmt": "{:+7.1f}"},
    "vz":   {"label": "vz",    "unit": "cm/s", "fmt": "{:+7.1f}"},
    "vmag": {"label": "|v|",   "unit": "cm/s", "fmt": "{:7.1f}"},
    "roll": {"label": "roll",  "unit": "°",    "fmt": "{:+6.1f}"},
    "pitch":{"label": "pitch", "unit": "°",    "fmt": "{:+6.1f}"},
    "yaw":  {"label": "yaw",   "unit": "°",    "fmt": "{:+6.1f}"},
    "x":    {"label": "X",     "unit": "cm",   "fmt": "{:+7.1f}"},
    "y":    {"label": "Y",     "unit": "cm",   "fmt": "{:+7.1f}"},
    "z":    {"label": "Z",     "unit": "cm",   "fmt": "{:+7.1f}"},
    "h":    {"label": "H",     "unit": "cm",   "fmt": "{:+7.1f}"},
}


def _default_items() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for k in HUD_ITEM_KEYS:
        m = HUD_ITEM_META[k]
        out[k] = {
            "visible": True,
            "label": m["label"],
            "unit": m["unit"],
            "fmt": m["fmt"],
        }
    return out


# 完整默认设置树（与 ConfigService 持久化 "path_viz.hud.settings" 对齐）
HUD_DEFAULTS: dict[str, Any] = {
    "items": _default_items(),
    "overlay": {
        "visible": True,
        "font_size_pt": 14,
        "opacity": 0.78,
        "pos_x": 12,            # 相对 3D 视图左上角的偏移（像素）
        "pos_y": 12,
        "bg_color": [10, 14, 22, 180],   # 半透明深底
        "fg_color": [220, 245, 220, 255], # 高亮绿白
    },
    "ruler": {
        "enabled": True,
        "tick_cm_minor": 50,    # 小刻度间隔
        "tick_cm_major": 100,   # 主刻度（带数字）
        "color": [120, 160, 200, 200],
        "text_color": [200, 220, 240, 255],
    },
}


def extract_hud_values(snapshot: Any) -> dict[str, float]:
    """把 PathSnapshot 转换为 {key: 当前数值}。

    缺字段时回填 0.0，保证 UI 不抛异常。
    """
    pos = getattr(snapshot, "pos_cm", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
    att = getattr(snapshot, "attitude_deg", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
    vel = getattr(snapshot, "vel_local_cmps", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
    px, py, pz = [float(c) for c in pos]
    rr, pp, yy = [float(c) for c in att]
    vx, vy, vz = [float(c) for c in vel]
    vmag = math.sqrt(vx * vx + vy * vy + vz * vz)
    return {
        "vx": vx, "vy": vy, "vz": vz, "vmag": vmag,
        "roll": rr, "pitch": pp, "yaw": yy,
        "x": px, "y": py, "z": pz, "h": pz,
    }


def deep_merge_hud(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """深合并（dict 递归覆盖；非 dict 直接替换）。返回新 dict，不改输入。"""
    out = copy.deepcopy(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge_hud(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out
