# -*- coding: utf-8 -*-
"""数字面板 Dock（P9）：独立 QDockWidget，按组列出 11 项指标并跟踪 min/max。

布局：
- 速度组：vx / vy / vz / |v|
- 姿态组：roll / pitch / yaw
- 位置组：x / y / z / h
- 每项一行：标签 + 当前值 + min + max + 单位
- 顶部按钮：清零 min/max

与 HUD overlay 共享同一份设置（`path_viz.hud.settings`），任一项的 `visible`
变化会自动隐藏/显示对应行；main.py 负责三方同步。
"""

from __future__ import annotations

import copy
import math
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ._hud_model import (
    HUD_DEFAULTS,
    HUD_ITEM_KEYS,
    HUD_ITEM_META,
    deep_merge_hud,
    extract_hud_values,
)


# 分组定义（顺序、组名 → 项目 key 列表）
_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("速度",  ("vx", "vy", "vz", "vmag")),
    ("姿态",  ("roll", "pitch", "yaw")),
    ("位置",  ("x", "y", "z", "h")),
)


class _Row:
    """一行：(label, value, min, max, unit) 五个 QLabel + 浮点 min/max 累计。"""

    __slots__ = ("lbl", "val", "mn", "mx", "unit", "min_v", "max_v")

    def __init__(self, parent: QWidget, key: str, meta: dict[str, str]) -> None:
        self.lbl = QLabel(str(meta["label"]), parent)
        self.val = QLabel("--", parent)
        self.mn = QLabel("--", parent)
        self.mx = QLabel("--", parent)
        self.unit = QLabel(str(meta["unit"]), parent)
        for w in (self.val, self.mn, self.mx):
            w.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            w.setStyleSheet("font-family: Consolas, 'Courier New', monospace;")
        self.min_v: float = math.inf
        self.max_v: float = -math.inf

    def reset(self) -> None:
        self.min_v = math.inf
        self.max_v = -math.inf
        self.mn.setText("--")
        self.mx.setText("--")

    def update(self, v: float, fmt: str) -> None:
        if v < self.min_v:
            self.min_v = v
        if v > self.max_v:
            self.max_v = v
        try:
            self.val.setText(fmt.format(v))
            self.mn.setText(fmt.format(self.min_v))
            self.mx.setText(fmt.format(self.max_v))
        except Exception:
            self.val.setText(f"{v:+.1f}")


class NumericPanelDock(QDockWidget):
    """独立的 Dock：数字面板，11 项分组 + min/max。"""

    settings_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("数字面板", parent)
        self.setObjectName("NumericPanelDock")
        self.setAllowedAreas(Qt.AllDockWidgetAreas)
        self._s: dict[str, Any] = copy.deepcopy(HUD_DEFAULTS)
        self._rows: dict[str, _Row] = {}
        self._group_boxes: list[QGroupBox] = []

        body = QWidget()
        vbox = QVBoxLayout(body)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.setSpacing(8)

        # 顶部工具行
        tool_row = QHBoxLayout()
        btn_reset = QPushButton("清零 min/max")
        btn_reset.clicked.connect(self._reset_all)
        tool_row.addWidget(btn_reset)
        tool_row.addStretch(1)
        vbox.addLayout(tool_row)

        # 三个分组
        for title, keys in _GROUPS:
            gb = QGroupBox(title, body)
            form = QFormLayout(gb)
            form.setLabelAlignment(Qt.AlignRight)
            form.setFormAlignment(Qt.AlignLeft | Qt.AlignTop)
            for k in keys:
                row = _Row(gb, k, HUD_ITEM_META[k])
                # 一行五列：label  当前  min  max  unit  → 用一个 horizontal widget 包
                line = QWidget(gb)
                hl = QHBoxLayout(line)
                hl.setContentsMargins(0, 0, 0, 0)
                hl.setSpacing(6)
                row.val.setMinimumWidth(90)
                row.mn.setMinimumWidth(80)
                row.mx.setMinimumWidth(80)
                hl.addWidget(row.val)
                hl.addWidget(QLabel("min", line))
                hl.addWidget(row.mn)
                hl.addWidget(QLabel("max", line))
                hl.addWidget(row.mx)
                hl.addWidget(row.unit)
                form.addRow(row.lbl, line)
                self._rows[k] = row
            vbox.addWidget(gb)
            self._group_boxes.append(gb)

        vbox.addStretch(1)
        self.setWidget(body)
        self._apply_visibility()

    # =====================================================
    #                    公开 API
    # =====================================================
    def apply_settings(self, patch: dict[str, Any]) -> None:
        self._s = deep_merge_hud(self._s, patch or {})
        self._apply_visibility()

    def current_settings(self) -> dict[str, Any]:
        return copy.deepcopy(self._s)

    def update_snapshot(self, snapshot: Any) -> None:
        try:
            vals = extract_hud_values(snapshot)
        except Exception:
            return
        for k, v in vals.items():
            row = self._rows.get(k)
            if row is None:
                continue
            fmt = self._s["items"].get(k, {}).get("fmt", "{:+7.1f}")
            row.update(v, fmt)

    # =====================================================
    #                    内部
    # =====================================================
    def _apply_visibility(self) -> None:
        """根据每项 visible 隐藏/显示对应 QLabel。组内全部隐藏时连组一起隐藏。"""
        items = self._s.get("items", {})
        for title, keys in _GROUPS:
            any_visible = False
            for k in keys:
                row = self._rows.get(k)
                if row is None:
                    continue
                vis = bool(items.get(k, {}).get("visible", True))
                row.lbl.setVisible(vis)
                row.val.setVisible(vis)
                row.mn.setVisible(vis)
                row.mx.setVisible(vis)
                row.unit.setVisible(vis)
                # FormLayout 不能隐藏整行的 label widget——上一行手动 setVisible 已足够
                if vis:
                    any_visible = True
            # 整组都隐藏 → 隐藏 GroupBox
            for gb in self._group_boxes:
                if gb.title() == title:
                    gb.setVisible(any_visible)
                    break

    def _reset_all(self) -> None:
        for row in self._rows.values():
            row.reset()
