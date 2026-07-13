# -*- coding: utf-8 -*-
"""P7：2D 投影路径视图（XY / XZ / YZ）。

设计要点：
- 用 pyqtgraph.PlotWidget 原生 2D（不走 OpenGL），自带刻度/缩放/平移
- 机体图标 = 导航纸飞机（细长等腰三角形），朝向当前 yaw 或速度方向（按 plane 投影）
- 路径折线 + 纸飞机；**不画姿态轴、不画速度箭头**（用户明确要求）
- 自带轻量设置面板（折叠），settings 与 3D 视图完全独立
- 与 3D 视图共享 PathSnapshot 信号源（主窗口在 telemetry_bus.path_updated 上 fan-out 多 connect 即可）

接口（与 3D 视图等价子集）：
- `update_snapshot(snap)`：消费 PathSnapshot
- `apply_settings(dict)`：外部灌入 settings（不回发信号）
- `current_settings()`：返回深拷贝
- `cleanup()`：幂等资源释放
- 信号 `settings_changed(dict)` / `reset_requested`

P7 验收依据：
- 投影一致性：XY=(x,y) / XZ=(x,z) / YZ=(y,z)
- 三平面构造均不报错
- update_snapshot 后 path 数据点数与传入 snap.points 一致
- apply_settings 深合并不破坏未指定字段
"""
from __future__ import annotations

import copy
import math
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal, QPointF
from PySide6.QtGui import QColor, QPolygonF, QBrush, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
    QGraphicsPolygonItem,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

# 软导入 pyqtgraph（缺依赖时给占位 widget）
try:
    import numpy as np
    import pyqtgraph as pg
    from pyqtgraph import PlotWidget
    _PG_OK = True
    _PG_IMPORT_ERR: Optional[str] = None
except Exception as _exc:  # pragma: no cover
    _PG_OK = False
    _PG_IMPORT_ERR = repr(_exc)


# ============================================================
#                       默认参数
# ============================================================
# 颜色统一 [r,g,b,a] 0-255 整数（便于 JSON 持久化）
DEFAULTS_2D: dict[str, Any] = {
    "path": {
        "color": [51, 255, 102, 255],   # 绿（与 3D 默认色一致）
        "width": 2.0,
        "antialias": True,
        # 保留轨迹的时间窗口（仅作为 UI 同步值，实际由 PathTracker 统一控制）
        "trail_seconds": 20.0,
        # ---- P8：K 段渲染 ----
        "render_mode": "segmented",     # "segmented" / "fade"
        "k_segments": 8,                # 1~32
        "head_width": 3.0,              # 最新段线宽
        "tail_width": 1.0,              # 最旧段线宽
        "head_alpha": 255,              # 最新段 alpha
        "tail_alpha": 40,               # 最旧段 alpha
    },
    "icon": {
        # 纸飞机三角形：长度（cm）= 沿前向；宽度（cm）= 横向（左右）
        "length_cm": 30.0,
        "width_cm": 18.0,
        "color": [255, 217, 51, 255],   # 黄（与 3D 机头球颜色一致）
        "outline_color": [10, 10, 15, 255],  # 深黑描边，与黄填充高对比
        "outline_width": 2.0,
        # 朝向源：yaw（按 PathSnapshot.attitude_deg.yaw 投影）/ vel（按速度方向投影）
        "heading_source": "yaw",
    },
    "grid": {
        "visible": True,
        "step_cm": 50.0,
        "color": [180, 180, 200, 80],
    },
    "view": {
        "bg_color": [40, 40, 50, 255],
        "auto_range": False,            # 默认取消自动跟随；用户用鼠标滚轮手动缩放
        "fixed_range_cm": 300.0,        # 初始可视范围半径（仅创建时应用一次）
        "show_axis_labels": True,
    },
}

# 平面坐标投影：(plane) → (axis_h_name, axis_v_name, idx_h, idx_v)
# idx 对应 PathSnapshot.pos_cm / PathPoint.x_cm/y_cm/z_cm
_PLANE_TABLE: dict[str, tuple[str, str, int, int]] = {
    "XY": ("X", "Y", 0, 1),
    "XZ": ("X", "Z", 0, 2),
    "YZ": ("Y", "Z", 1, 2),
}


def _deep_merge(dst: dict, src: dict) -> None:
    """递归把 src 合并入 dst（仅 dict 类型递归，其余覆盖）。"""
    for k, v in src.items():
        if k in dst and isinstance(dst[k], dict) and isinstance(v, dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v


# ---- P8：分段渲染工具（共享自 _path_segments）----
from gui.widgets._path_segments import (  # noqa: E402
    segments_by_age as _segments_by_age,
    lerp_scalar as _seg_lerp,
    lerp_alpha_byte as _seg_lerp_alpha,
)


# ============================================================
#                  颜色按钮（与 3D 同款逻辑）
# ============================================================
class _ColorButton(QPushButton):
    color_changed = Signal(list)

    def __init__(self, rgba: list, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._rgba = ([int(c) for c in rgba] + [255, 255, 255, 255])[:4]
        self.setFixedHeight(22)
        self.setFixedWidth(56)
        self.clicked.connect(self._on_click)
        self._sync_style()

    def rgba(self) -> list:
        return list(self._rgba)

    def set_rgba(self, rgba: list) -> None:
        self._rgba = ([int(c) for c in rgba] + [255, 255, 255, 255])[:4]
        self._sync_style()

    def _sync_style(self) -> None:
        r, g, b, a = self._rgba
        self.setStyleSheet(
            f"QPushButton {{ background-color: rgba({r},{g},{b},{a});"
            f" border:1px solid #555; border-radius:3px; }}"
        )
        self.setToolTip(f"RGBA = ({r}, {g}, {b}, {a})\n点击修改")

    def _on_click(self) -> None:  # pragma: no cover - 交互
        r, g, b, a = self._rgba
        c = QColorDialog.getColor(
            QColor(r, g, b, a),
            self,
            "选择颜色",
            QColorDialog.ColorDialogOption.ShowAlphaChannel,
        )
        if c.isValid():
            self._rgba = [c.red(), c.green(), c.blue(), c.alpha()]
            self._sync_style()
            self.color_changed.emit(list(self._rgba))


# ============================================================
#               轻量设置面板（折叠）
# ============================================================
class _Mini2DSettingsPanel(QScrollArea):
    """每个 2D 视图自带一份；emit value_changed(dotted_path, value)。"""

    value_changed = Signal(str, object)
    reset_requested = Signal()

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        inner = QWidget(self)
        self.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # 顶部：重置
        ops = QHBoxLayout()
        btn_reset = QPushButton("重置积分/轨迹", inner)
        btn_reset.clicked.connect(self.reset_requested)
        ops.addWidget(btn_reset)
        ops.addStretch(1)
        root.addLayout(ops)

        # 路径
        gb_path = QGroupBox("路径", inner)
        f = QFormLayout(gb_path)
        f.setContentsMargins(6, 6, 6, 6)
        sp_w = self._spin(settings["path"]["width"], 0.5, 8.0, 0.1, 2)
        sp_w.valueChanged.connect(self._emit("path.width"))
        f.addRow("线宽（fade）", sp_w)
        cb_col = _ColorButton(settings["path"]["color"], gb_path)
        cb_col.color_changed.connect(self._emit_color("path.color"))
        f.addRow("颜色", cb_col)
        cx_aa = QCheckBox("抗锯齿", gb_path)
        cx_aa.setChecked(bool(settings["path"]["antialias"]))
        cx_aa.toggled.connect(self._emit("path.antialias"))
        f.addRow("", cx_aa)
        # 保留轨迹秒数（与 3D 面板同步；main.py 接收信号后同步到 PathTracker）
        sp_ts = self._spin(
            float(settings["path"].get("trail_seconds", 20.0)),
            1.0, 600.0, 1.0, 1, " s",
        )
        sp_ts.valueChanged.connect(self._emit("path.trail_seconds"))
        f.addRow("保留秒数", sp_ts)
        # ---- P8：路径分段 ----
        cx_seg = QCheckBox("分段模式（近粗近亮远细远淡）", gb_path)
        cx_seg.setChecked(
            str(settings["path"].get("render_mode", "segmented")).lower() == "segmented"
        )
        cx_seg.toggled.connect(
            lambda v: self.value_changed.emit(
                "path.render_mode", "segmented" if v else "fade"
            )
        )
        f.addRow("", cx_seg)
        sp_k = self._int_spin(int(settings["path"].get("k_segments", 8)), 1, 32, " 段")
        sp_k.valueChanged.connect(self._emit("path.k_segments"))
        f.addRow("段数 K", sp_k)
        sp_hw = self._spin(float(settings["path"].get("head_width", 3.0)), 0.5, 12.0, 0.1, 2)
        sp_hw.valueChanged.connect(self._emit("path.head_width"))
        f.addRow("头段线宽", sp_hw)
        sp_tw = self._spin(float(settings["path"].get("tail_width", 1.0)), 0.5, 12.0, 0.1, 2)
        sp_tw.valueChanged.connect(self._emit("path.tail_width"))
        f.addRow("尾段线宽", sp_tw)
        sp_ha = self._int_spin(int(settings["path"].get("head_alpha", 255)), 0, 255)
        sp_ha.valueChanged.connect(self._emit("path.head_alpha"))
        f.addRow("头段透明度", sp_ha)
        sp_ta = self._int_spin(int(settings["path"].get("tail_alpha", 40)), 0, 255)
        sp_ta.valueChanged.connect(self._emit("path.tail_alpha"))
        f.addRow("尾段透明度", sp_ta)
        root.addWidget(gb_path)

        # 纸飞机图标
        gb_icon = QGroupBox("机体图标（纸飞机）", inner)
        f = QFormLayout(gb_icon)
        f.setContentsMargins(6, 6, 6, 6)
        sp_l = self._spin(settings["icon"]["length_cm"], 5.0, 200.0, 1.0, 1, " cm")
        sp_l.valueChanged.connect(self._emit("icon.length_cm"))
        f.addRow("长度", sp_l)
        sp_w2 = self._spin(settings["icon"]["width_cm"], 3.0, 200.0, 1.0, 1, " cm")
        sp_w2.valueChanged.connect(self._emit("icon.width_cm"))
        f.addRow("宽度", sp_w2)
        cb_ic = _ColorButton(settings["icon"]["color"], gb_icon)
        cb_ic.color_changed.connect(self._emit_color("icon.color"))
        f.addRow("填充色", cb_ic)
        cb_oc = _ColorButton(settings["icon"]["outline_color"], gb_icon)
        cb_oc.color_changed.connect(self._emit_color("icon.outline_color"))
        f.addRow("描边色", cb_oc)
        root.addWidget(gb_icon)

        # 网格
        gb_grid = QGroupBox("网格", inner)
        f = QFormLayout(gb_grid)
        f.setContentsMargins(6, 6, 6, 6)
        cx_g = QCheckBox("显示网格", gb_grid)
        cx_g.setChecked(bool(settings["grid"]["visible"]))
        cx_g.toggled.connect(self._emit("grid.visible"))
        f.addRow("", cx_g)
        sp_step = self._spin(settings["grid"]["step_cm"], 10.0, 500.0, 10.0, 1, " cm")
        sp_step.valueChanged.connect(self._emit("grid.step_cm"))
        f.addRow("步长", sp_step)
        root.addWidget(gb_grid)

        # 视图
        gb_view = QGroupBox("视图", inner)
        f = QFormLayout(gb_view)
        f.setContentsMargins(6, 6, 6, 6)
        cx_ar = QCheckBox("自动跟随范围", gb_view)
        cx_ar.setChecked(bool(settings["view"]["auto_range"]))
        cx_ar.toggled.connect(self._emit("view.auto_range"))
        f.addRow("", cx_ar)
        sp_fr = self._spin(settings["view"]["fixed_range_cm"], 50.0, 5000.0, 10.0, 1, " cm")
        sp_fr.valueChanged.connect(self._emit("view.fixed_range_cm"))
        f.addRow("固定半径", sp_fr)
        root.addWidget(gb_view)

        root.addStretch(1)

    def _spin(self, val: float, mn: float, mx: float, step: float = 1.0,
              decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setDecimals(decimals)
        sp.setRange(mn, mx)
        sp.setSingleStep(step)
        sp.setValue(float(val))
        if suffix:
            sp.setSuffix(suffix)
        return sp

    def _int_spin(self, val: int, mn: int, mx: int, suffix: str = "") -> QSpinBox:
        sp = QSpinBox()
        sp.setRange(mn, mx)
        sp.setValue(int(val))
        if suffix:
            sp.setSuffix(suffix)
        return sp

    def _emit(self, path: str):
        return lambda v: self.value_changed.emit(path, v)

    def _emit_color(self, path: str):
        return lambda rgba: self.value_changed.emit(path, list(rgba))


# ============================================================
#                       Path2DViewWidget
# ============================================================
class Path2DViewWidget(QWidget):
    """2D 投影路径视图（按 plane 投到 XY/XZ/YZ）。

    与 3D 视图同生命周期约定：
    - update_snapshot 接收 PathSnapshot；缺图形栈时仍能调用不崩
    - apply_settings 不回发信号；面板交互回发 settings_changed
    """

    settings_changed = Signal(dict)
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None,
                 plane: str = "XY",
                 settings: Optional[dict] = None) -> None:
        super().__init__(parent)
        plane = plane.upper()
        if plane not in _PLANE_TABLE:
            raise ValueError(f"plane 必须为 XY/XZ/YZ，得到 {plane!r}")
        self._plane = plane
        self._h_name, self._v_name, self._h_idx, self._v_idx = _PLANE_TABLE[plane]

        self.setObjectName(f"Path2DViewWidget_{plane}")

        # 当前 settings：深拷贝默认再合并
        self._s: dict[str, Any] = copy.deepcopy(DEFAULTS_2D)
        if settings:
            _deep_merge(self._s, settings)

        # 缓存最近一次快照（便于 apply_settings/重建后即时复绘）
        self._last_snap: Any = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # 顶部工具条
        bar_w = QWidget(self)
        bar = QHBoxLayout(bar_w)
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(4)
        lbl_plane = QLabel(f"平面：{plane}", bar_w)
        lbl_plane.setStyleSheet("font-weight:bold;")
        bar.addWidget(lbl_plane)
        bar.addStretch(1)
        self._btn_settings = QToolButton(bar_w)
        self._btn_settings.setText("设置")
        self._btn_settings.setCheckable(True)
        self._btn_settings.setToolTip("显示/隐藏右侧参数面板")
        self._btn_settings.setMinimumSize(72, 26)
        self._btn_settings.setStyleSheet(
            "QToolButton { padding: 3px 12px; font-size: 10pt; }"
        )
        self._btn_settings.toggled.connect(self._on_toggle_settings)
        bar.addWidget(self._btn_settings)
        root.addWidget(bar_w)

        if not _PG_OK:
            self._pg_ok = False
            self._plot = None
            self._splitter = None
            tip = QLabel(
                "2D 视图未启用：缺少 pyqtgraph。\n"
                f"导入错误：{_PG_IMPORT_ERR}\n"
                "请运行：pip install pyqtgraph",
                self,
            )
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setStyleSheet("color: #d33; padding: 16px;")
            root.addWidget(tip, 1)
            # 仍建一个面板以便持久化调参
            self._panel = _Mini2DSettingsPanel(self._s, self)
            self._panel.setVisible(False)
            self._panel.value_changed.connect(self._on_panel_value_changed)
            self._panel.reset_requested.connect(self.reset_requested)
            return

        self._pg_ok = True
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setChildrenCollapsible(True)
        self._plot = PlotWidget(self._splitter)
        self._plot.setAspectLocked(True, ratio=1.0)
        self._plot.setLabel("bottom", f"{self._h_name} (cm)")
        self._plot.setLabel("left", f"{self._v_name} (cm)")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._splitter.addWidget(self._plot)

        self._panel = _Mini2DSettingsPanel(self._s, self._splitter)
        self._panel.value_changed.connect(self._on_panel_value_changed)
        self._panel.reset_requested.connect(self.reset_requested)
        self._splitter.addWidget(self._panel)
        self._splitter.setStretchFactor(0, 5)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([500, 240])
        self._panel.setVisible(False)
        root.addWidget(self._splitter, 1)

        # 图层占位
        self._path_item: Any = None
        self._path_segments: list = []   # P8：K 段 PlotDataItem（segmented 模式）
        self._icon_item: Any = None
        self._build_scene()

    # =====================================================
    #                       对外 API
    # =====================================================
    @property
    def plane(self) -> str:
        return self._plane

    def apply_settings(self, settings: dict) -> None:
        """外部批量灌入（如启动时从 config 还原）。不回发信号。"""
        if not settings:
            return
        _deep_merge(self._s, settings)
        if self._pg_ok:
            self._apply_view_style()
            self._rebuild_path_item()
            self._rebuild_icon_item()
            if self._last_snap is not None:
                self.update_snapshot(self._last_snap)

    def current_settings(self) -> dict:
        return copy.deepcopy(self._s)

    def update_snapshot(self, snap: Any) -> None:
        """消费 PathSnapshot：刷新路径折线 + 纸飞机位置/朝向。"""
        self._last_snap = snap
        if not self._pg_ok:
            return
        try:
            self._update_path(snap)
            self._update_icon(snap)
            self._apply_auto_range(snap)
        except Exception:
            # 渲染异常不应让总线崩；与 3D 视图保持一致策略
            pass

    def cleanup(self) -> None:
        """幂等资源释放（被 QDockWidget close 或主窗口 close 时调用）。"""
        if not self._pg_ok:
            return
        self._pg_ok = False
        # P8/Bug 修：图标是直接加到 ViewBox 的 QGraphicsItem，plot.clear() 不会清它
        if self._icon_item is not None and self._plot is not None:
            try:
                self._plot.getPlotItem().getViewBox().removeItem(self._icon_item)
            except Exception:
                pass
        try:
            if self._plot is not None:
                self._plot.clear()
        except Exception:
            pass
        self._path_item = None
        self._path_segments = []
        self._icon_item = None

    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            self.cleanup()
        finally:
            super().closeEvent(event)

    # =====================================================
    #                       内部
    # =====================================================
    def _on_toggle_settings(self, checked: bool) -> None:
        if self._panel is not None and self._splitter is not None:
            self._panel.setVisible(checked)

    def _on_panel_value_changed(self, path: str, value: Any) -> None:
        # 写入
        keys = path.split(".")
        d = self._s
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        # 局部重建
        if self._pg_ok:
            grp = keys[0]
            if grp == "path":
                self._rebuild_path_item()
            elif grp == "icon":
                self._rebuild_icon_item()
            elif grp == "grid":
                self._apply_view_style()
            elif grp == "view":
                self._apply_view_style()
                # auto_range 切换：OFF 时锁定为 fixed_range；ON 时恢复自动
                if path == "view.auto_range":
                    self._apply_view_range_initial()
                elif path == "view.fixed_range_cm" and not bool(self._s["view"]["auto_range"]):
                    self._apply_view_range_initial()
            # 用上次快照立即复绘
            if self._last_snap is not None:
                self.update_snapshot(self._last_snap)
        # 回发全量 settings
        self.settings_changed.emit(self.current_settings())

    def _apply_view_range_initial(self) -> None:
        """根据当前 view 设置应用一次范围：auto_range=True 启动自动；否则锁定 fixed_range。"""
        if self._plot is None:
            return
        v = self._s["view"]
        try:
            if bool(v["auto_range"]):
                self._plot.enableAutoRange()
            else:
                self._plot.disableAutoRange()
                r = float(v["fixed_range_cm"])
                self._plot.setXRange(-r, r, padding=0)
                self._plot.setYRange(-r, r, padding=0)
        except Exception:
            pass

    def _build_scene(self) -> None:
        if not self._pg_ok:
            return
        self._apply_view_style()
        self._rebuild_path_item()
        self._rebuild_icon_item()
        # 初始化可视范围（默认 auto_range=False 时锁定为 fixed_range）
        self._apply_view_range_initial()

    def _apply_view_style(self) -> None:
        if self._plot is None:
            return
        view_s = self._s["view"]
        grid_s = self._s["grid"]
        r, g, b, _a = view_s["bg_color"]
        try:
            self._plot.setBackground(QColor(r, g, b))
        except Exception:
            pass
        if bool(grid_s["visible"]):
            self._plot.showGrid(x=True, y=True, alpha=0.3)
        else:
            self._plot.showGrid(x=False, y=False)

    def _rebuild_path_item(self) -> None:
        if self._plot is None:
            return
        # 清旧：fade 单线 + 分段多线都拆
        if self._path_item is not None:
            try:
                self._plot.removeItem(self._path_item)
            except Exception:
                pass
            self._path_item = None
        for it in list(self._path_segments):
            try:
                self._plot.removeItem(it)
            except Exception:
                pass
        self._path_segments = []
        s = self._s["path"]
        r, g, b, a = s["color"]
        antialias = bool(s["antialias"])
        mode = str(s.get("render_mode", "segmented")).lower()
        if mode == "segmented":
            k = max(1, min(64, int(s.get("k_segments", 8))))
            head_w = float(s.get("head_width", 3.0))
            tail_w = float(s.get("tail_width", 1.0))
            head_a = int(s.get("head_alpha", 255))
            tail_a = int(s.get("tail_alpha", 40))
            for i in range(k):
                w = _seg_lerp(tail_w, head_w, k, i)
                a_byte = _seg_lerp_alpha(tail_a, head_a, k, i)
                # 段 alpha = base.alpha × (a_byte/255)【使颜色调色后还能重叠透明度】
                seg_a = int(round(a * (a_byte / 255.0)))
                pen = pg.mkPen(color=(r, g, b, seg_a), width=float(w))
                item = self._plot.plot([], [], pen=pen, antialias=antialias)
                self._path_segments.append(item)
            return
        # fade 模式（单线）
        pen = pg.mkPen(color=(r, g, b, a), width=float(s["width"]))
        self._path_item = self._plot.plot([], [], pen=pen, antialias=antialias)

    def _rebuild_icon_item(self) -> None:
        """纸飞机用 QGraphicsPolygonItem（原生 QGraphics），才能真填充。

        之前用 PlotDataItem+fillLevel=None 只会画描边，且 outline 默认色与背景同色，导致看不见。
        """
        if self._plot is None:
            return
        vb = self._plot.getPlotItem().getViewBox()
        if self._icon_item is not None:
            try:
                vb.removeItem(self._icon_item)
            except Exception:
                pass
            self._icon_item = None
        s = self._s["icon"]
        fill = QBrush(QColor(*[int(c) for c in s["color"]]))
        pen = QPen(QColor(*[int(c) for c in s["outline_color"]]))
        pen.setWidthF(float(s["outline_width"]))
        pen.setCosmetic(True)  # 不受视图缩放影响的线宽
        self._icon_item = QGraphicsPolygonItem()
        self._icon_item.setBrush(fill)
        self._icon_item.setPen(pen)
        self._icon_item.setZValue(10.0)  # 压在路径之上
        vb.addItem(self._icon_item)

    def _update_path(self, snap: Any) -> None:
        points = getattr(snap, "points", ()) or ()
        h_idx = self._h_idx
        v_idx = self._v_idx
        mode = str(self._s["path"].get("render_mode", "segmented")).lower()
        # ---- segmented ----
        if mode == "segmented" and self._path_segments:
            k = len(self._path_segments)
            if not points:
                for seg in self._path_segments:
                    seg.setData([], [])
                return
            buckets = _segments_by_age(points, k)
            for i, seg_pts in enumerate(buckets):
                xs = []
                ys = []
                for p in seg_pts:
                    coords = (
                        float(getattr(p, "x_cm", 0.0)),
                        float(getattr(p, "y_cm", 0.0)),
                        float(getattr(p, "z_cm", 0.0)),
                    )
                    xs.append(coords[h_idx])
                    ys.append(coords[v_idx])
                self._path_segments[i].setData(xs, ys)
            return
        # ---- fade 单线 ----
        if self._path_item is None:
            return
        if not points:
            self._path_item.setData([], [])
            return
        xs = []
        ys = []
        for p in points:
            coords = (
                float(getattr(p, "x_cm", 0.0)),
                float(getattr(p, "y_cm", 0.0)),
                float(getattr(p, "z_cm", 0.0)),
            )
            xs.append(coords[h_idx])
            ys.append(coords[v_idx])
        self._path_item.setData(xs, ys)

    def _update_icon(self, snap: Any) -> None:
        if self._icon_item is None:
            return
        pos = getattr(snap, "pos_cm", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
        cx = float(pos[self._h_idx])
        cy = float(pos[self._v_idx])
        # 朝向：默认按 yaw 旋转到该平面投影
        heading_rad = self._compute_heading_rad(snap)
        s = self._s["icon"]
        length = float(s["length_cm"])
        width = float(s["width_cm"])
        # 纸飞机本地多边形（朝向 +x）：尖端、左后翼、尾部凹点、右后翼，回到尖端
        # 比例：长度 length，宽度 width；尾凹深度 = length * 0.25
        L = length
        W = width * 0.5
        tail_cut = L * 0.25
        local = [
            ( L,         0.0),    # 尖端
            (-L * 0.5,   W),      # 右后翼（视方向：在 +x 的右侧 = -y）→ 但 2D 平面上右翼放 +y 不影响美观
            (-L * 0.5 + tail_cut, 0.0),  # 尾凹
            (-L * 0.5,  -W),      # 左后翼
            ( L,         0.0),    # 闭合
        ]
        cos_h = math.cos(heading_rad)
        sin_h = math.sin(heading_rad)
        poly = QPolygonF()
        for lx, ly in local:
            wx = cx + lx * cos_h - ly * sin_h
            wy = cy + lx * sin_h + ly * cos_h
            poly.append(QPointF(wx, wy))
        self._icon_item.setPolygon(poly)

    def _compute_heading_rad(self, snap: Any) -> float:
        """计算纸飞机在当前 2D 平面上的朝向（弧度）。

        默认按 yaw（机体 +X 方向）；若用户切到 'vel'，按 vel_local 在该平面的投影。
        - XY 平面：yaw=0 即 +X，正方向；CCW 为 + → atan2(y_dir, x_dir)
        - XZ 平面：默认 +X 方向（俯视投影），保留 yaw 在水平的余弦投影
        - YZ 平面：默认 +Y 方向（侧视投影），保留 yaw 的正弦投影
        约定简单实现：XY 用 yaw 完整；XZ/YZ 取近似（航向投到该平面）。
        """
        src = str(self._s["icon"]["heading_source"]).lower()
        if src == "vel":
            vel = getattr(snap, "vel_local_cmps", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
            vh = float(vel[self._h_idx])
            vv = float(vel[self._v_idx])
            if (vh * vh + vv * vv) > 1e-6:
                return math.atan2(vv, vh)
            # 退化到 yaw
        att = getattr(snap, "attitude_deg", (0.0, 0.0, 0.0)) or (0.0, 0.0, 0.0)
        yaw_deg = float(att[2])
        yaw_rad = math.radians(yaw_deg)
        if self._plane == "XY":
            # 机头 +X 在世界 XY 平面绕 Z 旋转 yaw → (cos yaw, sin yaw)
            return yaw_rad
        # 机头单位向量（机体 +X）在世界系 = (cos yaw, sin yaw, 0)
        # 投到 XZ：水平分量 cos yaw 给 X，Z 分量 0 → 直接朝 ±X
        # 投到 YZ：水平分量 sin yaw 给 Y，Z 分量 0 → 直接朝 ±Y
        hx_world = math.cos(yaw_rad)
        hy_world = math.sin(yaw_rad)
        if self._plane == "XZ":
            # 投影：水平 = hx_world，竖直 = 0
            return 0.0 if hx_world >= 0 else math.pi
        # YZ
        return 0.0 if hy_world >= 0 else math.pi

    def _apply_auto_range(self, snap: Any) -> None:
        if self._plot is None:
            return
        view_s = self._s["view"]
        if bool(view_s["auto_range"]):
            try:
                self._plot.enableAutoRange()
            except Exception:
                pass
            return
        # 手动模式：不每帧重置范围，避免覆盖用户鼠标滚轮缩放/拖拽。
        # 初始可视范围在 view.auto_range 被关闭的那一刻（_on_panel_value_changed）应用一次。
        try:
            self._plot.disableAutoRange()
        except Exception:
            pass
