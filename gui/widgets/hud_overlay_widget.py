# -*- coding: utf-8 -*-
"""HUD 叠加层（P9）：半透明面板覆盖在 3D `GLViewWidget` 之上。

设计：
- 通过 `setParent(host_widget)` + `raise_()` + `resize`/`move` 跟随宿主控件，
  不参与布局，永远飘在上面。
- 11 项指标由共享的 `_hud_model.HUD_DEFAULTS` 定义；可在设置面板里独立勾选。
- 用户可按住面板边缘拖动重新定位；松开后 emit `position_changed`，
  上层 `main.py` 写入 `path_viz.hud.settings.overlay.pos_x/pos_y` 持久化。
- `apply_settings` / `current_settings` / `update_snapshot` 三 API 对齐其它 viz 控件。

注意：
- 仅依赖 PySide6，不依赖 OpenGL；本身就是 QFrame，与底下的 GLViewWidget 不冲突。
- 数据通路由调用方负责（main.py 把 path_updated 转发过来）。
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, QPoint, QEvent
from PySide6.QtGui import QColor, QFont, QMouseEvent
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QLabel,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from ._hud_model import (
    HUD_DEFAULTS,
    HUD_ITEM_KEYS,
    deep_merge_hud,
    extract_hud_values,
)


class HudOverlayWidget(QFrame):
    """覆盖在 3D 视图上的浮动 HUD 面板。"""

    # 用户拖动后发出（新坐标 px，相对宿主 widget 左上角）
    position_changed = Signal(int, int)
    # 用户在浮窗里改了显示项（罕见；目前面板由设置面板控制，这里保留）
    settings_changed = Signal(dict)

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._s: dict[str, Any] = copy.deepcopy(HUD_DEFAULTS)
        self._labels: dict[str, QLabel] = {}        # key -> 数值 QLabel
        self._rows: dict[str, tuple[QLabel, QLabel, QLabel]] = {}  # key -> (lbl, val, unit)

        # 视觉
        self.setObjectName("HudOverlay")
        self.setFrameShape(QFrame.NoFrame)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)  # 自己要接收拖动
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)

        # 内部布局
        self._grid_host = QWidget(self)
        self._grid = QGridLayout(self._grid_host)
        self._grid.setContentsMargins(10, 8, 10, 8)
        self._grid.setHorizontalSpacing(10)
        self._grid.setVerticalSpacing(2)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._grid_host)

        self._build_rows()
        self._apply_visual_style()
        self._reposition_from_settings()

        # 跟随宿主大小变化（拐角自动 reposition）
        host.installEventFilter(self)

        # 拖动状态
        self._drag_active = False
        self._drag_offset = QPoint(0, 0)

    # =====================================================
    #                    公开 API
    # =====================================================
    def apply_settings(self, patch: dict[str, Any]) -> None:
        """深合并设置，重建 UI（项目可见性变化时）+ 重新定位。"""
        new = deep_merge_hud(self._s, patch or {})
        items_changed = new.get("items") != self._s.get("items")
        overlay_changed = new.get("overlay") != self._s.get("overlay")
        self._s = new
        if items_changed:
            self._build_rows()
        if overlay_changed or items_changed:
            self._apply_visual_style()
            self._reposition_from_settings()
        # overlay.visible 控制整体显隐
        visible = bool(self._s["overlay"].get("visible", True))
        self.setVisible(visible)
        if visible:
            # 重建后必须显式 show + raise，否则 _grid_host 内的新 QLabel 偶发不可见（Bug 7）
            self._grid_host.show()
            self.show()
            self.raise_()
            self.update()

    def current_settings(self) -> dict[str, Any]:
        return copy.deepcopy(self._s)

    def update_snapshot(self, snapshot: Any) -> None:
        """每帧调用：把 PathSnapshot 转成数值塞到 QLabel。"""
        try:
            vals = extract_hud_values(snapshot)
        except Exception:
            return
        for k, val in vals.items():
            row = self._rows.get(k)
            if row is None:
                continue
            _, val_lbl, _ = row
            fmt = self._s["items"][k].get("fmt", "{:+7.1f}")
            try:
                val_lbl.setText(fmt.format(val))
            except Exception:
                val_lbl.setText(f"{val:+.1f}")

    # =====================================================
    #                    内部：构建/视觉
    # =====================================================
    def _build_rows(self) -> None:
        """根据 items.visible 重建行（清空旧的 QLabel）。"""
        # 清旧：takeAt 立即从布局移除；setParent(None) 即时脱离父子关系；
        # 显式 hide() 避免 deleteLater 真正销毁前残留显示叠加在新行上（Bug 7）。
        for i in reversed(range(self._grid.count())):
            item = self._grid.takeAt(i)
            w = item.widget() if item is not None else None
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        self._rows.clear()
        self._labels.clear()

        row = 0
        for k in HUD_ITEM_KEYS:
            cfg = self._s["items"].get(k, {})
            if not cfg.get("visible", True):
                continue
            lbl = QLabel(str(cfg.get("label", k)), self._grid_host)
            val = QLabel("--", self._grid_host)
            unit = QLabel(str(cfg.get("unit", "")), self._grid_host)
            lbl.setObjectName("HudLbl")
            val.setObjectName("HudVal")
            unit.setObjectName("HudUnit")
            val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self._grid.addWidget(lbl, row, 0)
            self._grid.addWidget(val, row, 1)
            self._grid.addWidget(unit, row, 2)
            # 新加入的 QLabel 在父 _grid_host 隐藏时不会自动显示，显式 show 一次
            lbl.show()
            val.show()
            unit.show()
            self._rows[k] = (lbl, val, unit)
            self._labels[k] = val
            row += 1
        # 强制立即重算尺寸（grid -> host -> self）
        self._grid.activate()
        self._grid_host.updateGeometry()
        self._grid_host.adjustSize()
        self.updateGeometry()
        self.adjustSize()

    def _apply_visual_style(self) -> None:
        ov = self._s.get("overlay", {})
        bg = ov.get("bg_color", [10, 14, 22, 180])
        fg = ov.get("fg_color", [220, 245, 220, 255])
        fs = int(ov.get("font_size_pt", 14))
        # 透明度通过 RGBA 的 A 通道实现；opacity 二次缩放
        op = max(0.0, min(1.0, float(ov.get("opacity", 0.78))))
        bg_a = int(bg[3] * op) if len(bg) >= 4 else int(180 * op)
        bg_str = f"rgba({bg[0]},{bg[1]},{bg[2]},{bg_a})"
        fg_str = f"rgba({fg[0]},{fg[1]},{fg[2]},{fg[3] if len(fg) >= 4 else 255})"
        # 用 stylesheet 控制（QFrame#HudOverlay 圆角 + 半透明背景）
        self.setStyleSheet(
            f"QFrame#HudOverlay {{"
            f"  background-color: {bg_str};"
            f"  border: 1px solid rgba({fg[0]},{fg[1]},{fg[2]},120);"
            f"  border-radius: 6px;"
            f"}}"
            f"QLabel#HudLbl {{ color: {fg_str}; font-size: {fs}pt; }}"
            f"QLabel#HudVal {{ color: {fg_str}; font-size: {fs}pt; font-weight: bold;"
            f" font-family: 'Consolas','Courier New',monospace; }}"
            f"QLabel#HudUnit {{ color: rgba({fg[0]},{fg[1]},{fg[2]},180);"
            f" font-size: {max(8, fs - 3)}pt; }}"
        )
        # 强制重新计算尺寸
        self._grid_host.adjustSize()
        self.adjustSize()

    def _reposition_from_settings(self) -> None:
        ov = self._s.get("overlay", {})
        x = int(ov.get("pos_x", 12))
        y = int(ov.get("pos_y", 12))
        # 限制在宿主范围内（防止用户拖出窗外）
        if self._host is not None:
            hx = max(0, min(x, max(0, self._host.width() - self.width())))
            hy = max(0, min(y, max(0, self._host.height() - self.height())))
            self.move(hx, hy)
        else:
            self.move(x, y)
        self.raise_()

    # =====================================================
    #                    事件：拖动 + 跟随
    # =====================================================
    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        if obj is self._host and ev.type() == QEvent.Resize:
            self._reposition_from_settings()
        return False

    def mousePressEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if ev.button() == Qt.LeftButton:
            self._drag_active = True
            self._drag_offset = ev.position().toPoint()
            ev.accept()
            return
        super().mousePressEvent(ev)

    def mouseMoveEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._drag_active and self._host is not None:
            # 把全局坐标映射回宿主坐标
            global_pos = ev.globalPosition().toPoint()
            local = self._host.mapFromGlobal(global_pos) - self._drag_offset
            nx = max(0, min(local.x(), max(0, self._host.width() - self.width())))
            ny = max(0, min(local.y(), max(0, self._host.height() - self.height())))
            self.move(nx, ny)
            ev.accept()
            return
        super().mouseMoveEvent(ev)

    def mouseReleaseEvent(self, ev: QMouseEvent) -> None:  # noqa: N802
        if self._drag_active and ev.button() == Qt.LeftButton:
            self._drag_active = False
            p = self.pos()
            self._s["overlay"]["pos_x"] = int(p.x())
            self._s["overlay"]["pos_y"] = int(p.y())
            self.position_changed.emit(int(p.x()), int(p.y()))
            # 把整体设置变更也广播一下（path 写入持久化）
            self.settings_changed.emit(self.current_settings())
            ev.accept()
            return
        super().mouseReleaseEvent(ev)
