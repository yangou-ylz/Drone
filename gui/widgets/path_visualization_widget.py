# -*- coding: utf-8 -*-
"""P5：路径可视化 3D 场景 + 完整参数面板（持久化）。

在 P4 基础上：
- 把所有渲染常量改为运行时可调字段（settings dict）
- 右侧弹出"设置面板"用 QSplitter 折叠/拉宽；按齿轮按钮显隐
- 顶部工具条：重置（清积分）/ 刷新（重建场景）/ 设置
- 任何参数变更立即生效；同时 emit `settings_changed(dict)`
- 主窗口接 `settings_changed` 写入 `gui/config.json` 的 `path_viz.settings` 键
- 主窗口接 `reset_requested` → bus.reset_path()
- 主窗口接 `refresh_requested` → 重建场景 + 重发当前快照
- 路径渐隐（fade）：按时间残留做 alpha 渐变
- 兼容性：类名仍为 `PathVisualizationPlaceholder`，update_snapshot 入口签名不变
"""
from __future__ import annotations

import copy
from typing import Any, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFormLayout,
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

# 软导入：缺依赖时退化为占位
try:
    import numpy as np
    from pyqtgraph import Transform3D
    from pyqtgraph.opengl import (
        GLAxisItem,
        GLGridItem,
        GLLinePlotItem,
        GLMeshItem,
        GLTextItem,
        GLViewWidget,
        MeshData,
    )
    _GL_OK = True
    _GL_IMPORT_ERR: Optional[str] = None
except Exception as _exc:  # pragma: no cover - 仅缺依赖环境会走
    _GL_OK = False
    _GL_IMPORT_ERR = repr(_exc)


# ---- P5 默认参数（数值上等同 P4，确保视觉零回归）----
# 颜色统一用 [r,g,b,a] 0-255 整数列表（便于 JSON 持久化）
DEFAULTS: dict[str, Any] = {
    "cube": {
        "size_cm": 20.0,
        "color": [77, 179, 255, 191],   # 半透蓝 (0.30, 0.70, 1.00, 0.75)*255
        "edge_color": [255, 255, 255, 255],
        "draw_edges": True,
    },
    "nose": {
        "radius_cm": 4.0,
        "color": [255, 217, 51, 255],   # 黄 (1.0, 0.85, 0.20)
        "gap_cm": 1.0,                  # 球心与立方体 +x 面的额外间隙
    },
    "axis": {
        "length_cm": 30.0,
        "visible": True,
        # 箭头头尺寸（圆锥）
        "head_radius_cm": 2.0,
        "head_length_cm": 5.0,
        # X/Y/Z 文字标签
        "labels_visible": True,
        "label_size": 14,
        "label_offset_cm": 3.0,
    },
    "vel_arrow": {
        "scale_cm_per_cmps": 0.4,
        "max_cm": 120.0,
        "color": [255, 140, 25, 255],   # 橙
        "width": 3.0,
        "min_speed_cmps": 1.0,          # 小于此速度折叠为零长
        # 箭头头（圆锥）— 随逕度折叠同步隐藏
        "head_radius_cm": 2.0,
        "head_length_cm": 5.0,
    },
    "grid": {
        "size_cm": 600.0,
        "step_cm": 50.0,
        "color": [180, 180, 200, 80],
        "plane_xy": True,               # 地面
        "plane_xz": False,
        "plane_yz": False,
    },
    "path": {
        "color": [51, 255, 102, 255],   # 绿
        "width": 2.0,
        "antialias": True,
        "fade": True,                   # 渐隐：旧点透明、新点不透明（仅 fade 模式下生效）
        "trail_seconds": 20.0,          # 传给 PathTrackerConfig
        "max_points": 1800,             # 传给 PathTrackerConfig
        # ---- P8：K 段渲染（近粗近亮远细远淡）----
        # render_mode: "segmented"=分段 / "fade"=单线+Nx4 alpha（兼容 P5）
        "render_mode": "segmented",
        "k_segments": 8,                # 1~32
        "head_width": 3.0,              # 最新段线宽
        "tail_width": 1.0,              # 最旧段线宽
        "head_alpha": 255,              # 最新段 alpha（0-255）
        "tail_alpha": 40,               # 最旧段 alpha（0-255）
    },
    "render": {
        "fps": 30,                      # 传给 TelemetryBus
        "antialias": True,              # 通用抗锯齿（影响速度箭头）
        "bg_color": [40, 40, 50, 255],
        "camera_distance": 600.0,
        "camera_elevation": 28.0,
        "camera_azimuth": 45.0,
    },
}


# ---- P4 向后兼容导出（供 _smoke_phase_p4 等老测试沿用）----
# 数值来自 DEFAULTS，确保未来改默认值时这里同步
_NOSE_OFFSET_CM: float = (
    DEFAULTS["cube"]["size_cm"] / 2.0
    + DEFAULTS["nose"]["radius_cm"]
    + DEFAULTS["nose"]["gap_cm"]
)
_VEL_ARROW_SCALE: float = DEFAULTS["vel_arrow"]["scale_cm_per_cmps"]
_VEL_ARROW_MAX_CM: float = DEFAULTS["vel_arrow"]["max_cm"]
_CUBE_SIZE_CM: float = DEFAULTS["cube"]["size_cm"]
_AXIS_LEN_CM: float = DEFAULTS["axis"]["length_cm"]
_NOSE_RADIUS_CM: float = DEFAULTS["nose"]["radius_cm"]


# ============================================================
#                   颜色按钮（点击弹 QColorDialog）
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
        self.setText("")
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
#                   设置面板（折叠分组 + QFormLayout）
# ============================================================
class _SettingsPanel(QScrollArea):
    """所有参数控件集中处。每个控件变更 → emit value_changed(dotted_path, value)。"""

    value_changed = Signal(str, object)   # ("cube.size_cm", 20.0)
    reset_requested = Signal()
    refresh_requested = Signal()
    record_toggle_requested = Signal(bool)  # P5.5：True=开始记录 / False=停止
    viewpoint_preset_requested = Signal(str)  # P10："top" / "side" / "free"
    export_csv_requested = Signal()           # P10：导出轨迹 CSV

    def __init__(self, settings: dict, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        inner = QWidget(self)
        self.setWidget(inner)
        root = QVBoxLayout(inner)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        # ---- 顶部操作 ----
        ops = QHBoxLayout()
        ops.setSpacing(6)
        btn_reset = QPushButton("重置积分/轨迹", inner)
        btn_reset.setToolTip("把方块拉回原点，清空轨迹（保留当前 yaw0）")
        btn_reset.clicked.connect(self.reset_requested)
        btn_refresh = QPushButton("刷新场景", inner)
        btn_refresh.setToolTip("用当前参数重建所有 3D 元素")
        btn_refresh.clicked.connect(self.refresh_requested)
        # P10：视角预设三按钮
        btn_top = QPushButton("俯视", inner)
        btn_top.setToolTip("高仰角从上往下看")
        btn_top.clicked.connect(lambda: self.viewpoint_preset_requested.emit("top"))
        btn_side = QPushButton("侧视", inner)
        btn_side.setToolTip("低仰角侧面视角")
        btn_side.clicked.connect(lambda: self.viewpoint_preset_requested.emit("side"))
        btn_free = QPushButton("自由", inner)
        btn_free.setToolTip("默认斜视视角")
        btn_free.clicked.connect(lambda: self.viewpoint_preset_requested.emit("free"))
        # P10：CSV 导出
        btn_csv = QPushButton("导出轨迹 CSV", inner)
        btn_csv.setToolTip("把当前轨迹点列表以 CSV 格式保存")
        btn_csv.clicked.connect(self.export_csv_requested)
        ops.addWidget(btn_reset)
        ops.addWidget(btn_refresh)
        ops.addWidget(btn_top)
        ops.addWidget(btn_side)
        ops.addWidget(btn_free)
        ops.addWidget(btn_csv)
        ops.addStretch(1)
        root.addLayout(ops)

        # ---- 各分组 ----
        self._build_group_record(root)
        self._build_group_cube(root, settings["cube"])
        self._build_group_nose(root, settings["nose"])
        self._build_group_axis(root, settings["axis"])
        self._build_group_vel(root, settings["vel_arrow"])
        self._build_group_grid(root, settings["grid"])
        self._build_group_path(root, settings["path"])
        self._build_group_hud(root, settings.get("hud", {}))
        self._build_group_render(root, settings["render"])
        root.addStretch(1)

    # ---- 工具 ----
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

    # ---- 分组 ----
    def _build_group_record(self, root: QVBoxLayout) -> None:
        """P5.5：传感器帧记录 → JSONL（用于离线 AI 诊断）。"""
        gb = QGroupBox("传感器帧记录（JSONL）", self)
        v = QVBoxLayout(gb)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)
        row = QHBoxLayout()
        self._btn_rec_start = QPushButton("● 开始记录", gb)
        self._btn_rec_start.setToolTip("选择保存路径并开始把所有状态传感器帧写入 JSONL")
        self._btn_rec_start.clicked.connect(lambda: self.record_toggle_requested.emit(True))
        self._btn_rec_stop = QPushButton("■ 停止", gb)
        self._btn_rec_stop.setEnabled(False)
        self._btn_rec_stop.clicked.connect(lambda: self.record_toggle_requested.emit(False))
        row.addWidget(self._btn_rec_start)
        row.addWidget(self._btn_rec_stop)
        v.addLayout(row)
        self._lbl_rec = QLabel("空闲（未记录）", gb)
        self._lbl_rec.setStyleSheet("color: #555;")
        self._lbl_rec.setWordWrap(True)
        v.addWidget(self._lbl_rec)
        root.addWidget(gb)

    def set_recording_state(self, active: bool, path: str, count: int = 0) -> None:
        """主窗口/widget 反向更新按钮与状态文字。"""
        # 录制控件可能在 _GL 不可用分支或未实例化时缺失
        if not hasattr(self, "_btn_rec_start"):
            return
        self._btn_rec_start.setEnabled(not active)
        self._btn_rec_stop.setEnabled(active)
        if active:
            self._lbl_rec.setStyleSheet("color: #c62828; font-weight: bold;")
            self._lbl_rec.setText(f"●REC {count} 帧 → {path}")
        else:
            self._lbl_rec.setStyleSheet("color: #555;")
            if path:
                self._lbl_rec.setText(f"已停止（{count} 帧）→ {path}")
            else:
                self._lbl_rec.setText("空闲（未记录）")

    # ---- 分组 ----
    def _build_group_cube(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("立方体", self)
        f = QFormLayout(gb)
        sp = self._spin(s["size_cm"], 1.0, 200.0, 1.0, 1, " cm")
        sp.valueChanged.connect(self._emit("cube.size_cm"))
        f.addRow("尺寸", sp)
        cb = _ColorButton(s["color"], gb)
        cb.color_changed.connect(self._emit_color("cube.color"))
        f.addRow("颜色(含 α)", cb)
        cb2 = _ColorButton(s["edge_color"], gb)
        cb2.color_changed.connect(self._emit_color("cube.edge_color"))
        f.addRow("描边颜色", cb2)
        ck = QCheckBox()
        ck.setChecked(bool(s["draw_edges"]))
        ck.toggled.connect(self._emit("cube.draw_edges"))
        f.addRow("绘制描边", ck)
        root.addWidget(gb)

    def _build_group_nose(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("机头小球", self)
        f = QFormLayout(gb)
        sp = self._spin(s["radius_cm"], 0.5, 30.0, 0.5, 1, " cm")
        sp.valueChanged.connect(self._emit("nose.radius_cm"))
        f.addRow("半径", sp)
        cb = _ColorButton(s["color"], gb)
        cb.color_changed.connect(self._emit_color("nose.color"))
        f.addRow("颜色", cb)
        sp2 = self._spin(s["gap_cm"], 0.0, 20.0, 0.5, 1, " cm")
        sp2.valueChanged.connect(self._emit("nose.gap_cm"))
        f.addRow("与立方体间隙", sp2)
        root.addWidget(gb)

    def _build_group_axis(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("机体三轴 (R=X / G=Y / B=Z)", self)
        f = QFormLayout(gb)
        sp = self._spin(s["length_cm"], 5.0, 200.0, 1.0, 1, " cm")
        sp.valueChanged.connect(self._emit("axis.length_cm"))
        f.addRow("长度", sp)
        ck = QCheckBox()
        ck.setChecked(bool(s["visible"]))
        ck.toggled.connect(self._emit("axis.visible"))
        f.addRow("显示轴", ck)
        sp_hr = self._spin(s.get("head_radius_cm", 2.0), 0.0, 20.0, 0.5, 1, " cm")
        sp_hr.valueChanged.connect(self._emit("axis.head_radius_cm"))
        f.addRow("箭头半径", sp_hr)
        sp_hl = self._spin(s.get("head_length_cm", 5.0), 0.0, 30.0, 0.5, 1, " cm")
        sp_hl.valueChanged.connect(self._emit("axis.head_length_cm"))
        f.addRow("箭头长度", sp_hl)
        ck_lbl = QCheckBox()
        ck_lbl.setChecked(bool(s.get("labels_visible", True)))
        ck_lbl.toggled.connect(self._emit("axis.labels_visible"))
        f.addRow("显示 X/Y/Z 字标", ck_lbl)
        sp_ls = self._int_spin(int(s.get("label_size", 14)), 6, 64, " pt")
        sp_ls.valueChanged.connect(self._emit("axis.label_size"))
        f.addRow("字标字号", sp_ls)
        sp_lo = self._spin(s.get("label_offset_cm", 3.0), 0.0, 50.0, 0.5, 1, " cm")
        sp_lo.valueChanged.connect(self._emit("axis.label_offset_cm"))
        f.addRow("字标偏移", sp_lo)
        root.addWidget(gb)

    def _build_group_vel(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("速度箭头", self)
        f = QFormLayout(gb)
        sp = self._spin(s["scale_cm_per_cmps"], 0.01, 5.0, 0.05, 2, " cm/(cm/s)")
        sp.valueChanged.connect(self._emit("vel_arrow.scale_cm_per_cmps"))
        f.addRow("长度系数", sp)
        sp2 = self._spin(s["max_cm"], 10.0, 1000.0, 10.0, 0, " cm")
        sp2.valueChanged.connect(self._emit("vel_arrow.max_cm"))
        f.addRow("长度上限", sp2)
        sp3 = self._spin(s["min_speed_cmps"], 0.0, 50.0, 0.5, 1, " cm/s")
        sp3.valueChanged.connect(self._emit("vel_arrow.min_speed_cmps"))
        f.addRow("折叠阈值", sp3)
        sp4 = self._spin(s["width"], 0.5, 20.0, 0.5, 1, " px")
        sp4.valueChanged.connect(self._emit("vel_arrow.width"))
        f.addRow("线宽", sp4)
        cb = _ColorButton(s["color"], gb)
        cb.color_changed.connect(self._emit_color("vel_arrow.color"))
        f.addRow("颜色", cb)
        sp_hr = self._spin(s.get("head_radius_cm", 2.0), 0.0, 20.0, 0.5, 1, " cm")
        sp_hr.valueChanged.connect(self._emit("vel_arrow.head_radius_cm"))
        f.addRow("箭头半径", sp_hr)
        sp_hl = self._spin(s.get("head_length_cm", 5.0), 0.0, 30.0, 0.5, 1, " cm")
        sp_hl.valueChanged.connect(self._emit("vel_arrow.head_length_cm"))
        f.addRow("箭头长度", sp_hl)
        root.addWidget(gb)

    def _build_group_grid(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("网格", self)
        f = QFormLayout(gb)
        sp = self._spin(s["size_cm"], 50.0, 5000.0, 50.0, 0, " cm")
        sp.valueChanged.connect(self._emit("grid.size_cm"))
        f.addRow("覆盖范围", sp)
        sp2 = self._spin(s["step_cm"], 1.0, 500.0, 5.0, 1, " cm")
        sp2.valueChanged.connect(self._emit("grid.step_cm"))
        f.addRow("步长", sp2)
        cb = _ColorButton(s["color"], gb)
        cb.color_changed.connect(self._emit_color("grid.color"))
        f.addRow("颜色(含 α)", cb)
        ckxy = QCheckBox("XY 平面（地面）")
        ckxy.setChecked(bool(s["plane_xy"]))
        ckxy.toggled.connect(self._emit("grid.plane_xy"))
        f.addRow(ckxy)
        ckxz = QCheckBox("XZ 平面")
        ckxz.setChecked(bool(s["plane_xz"]))
        ckxz.toggled.connect(self._emit("grid.plane_xz"))
        f.addRow(ckxz)
        ckyz = QCheckBox("YZ 平面")
        ckyz.setChecked(bool(s["plane_yz"]))
        ckyz.toggled.connect(self._emit("grid.plane_yz"))
        f.addRow(ckyz)
        root.addWidget(gb)

    def _build_group_path(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("路径线", self)
        f = QFormLayout(gb)
        sp = self._spin(s["width"], 0.5, 20.0, 0.5, 1, " px")
        sp.valueChanged.connect(self._emit("path.width"))
        f.addRow("线宽（fade）", sp)
        cb = _ColorButton(s["color"], gb)
        cb.color_changed.connect(self._emit_color("path.color"))
        f.addRow("颜色", cb)
        ck = QCheckBox()
        ck.setChecked(bool(s["antialias"]))
        ck.toggled.connect(self._emit("path.antialias"))
        f.addRow("抗锯齿", ck)
        ck2 = QCheckBox()
        ck2.setChecked(bool(s["fade"]))
        ck2.toggled.connect(self._emit("path.fade"))
        f.addRow("时间渐隐（fade）", ck2)
        sp2 = self._spin(s["trail_seconds"], 1.0, 600.0, 1.0, 1, " s")
        sp2.valueChanged.connect(self._emit("path.trail_seconds"))
        f.addRow("残留秒数", sp2)
        sp3 = self._int_spin(s["max_points"], 100, 100000, " 点")
        sp3.valueChanged.connect(self._emit("path.max_points"))
        f.addRow("点数上限", sp3)
        # ---- P8：路径分段 ----
        cx_seg = QCheckBox()
        cx_seg.setChecked(str(s.get("render_mode", "segmented")).lower() == "segmented")
        cx_seg.toggled.connect(
            lambda v: self.value_changed.emit(
                "path.render_mode", "segmented" if v else "fade"
            )
        )
        f.addRow("分段模式（近粗近亮远细远淡）", cx_seg)
        sp_k = self._int_spin(int(s.get("k_segments", 8)), 1, 32, " 段")
        sp_k.valueChanged.connect(self._emit("path.k_segments"))
        f.addRow("段数 K", sp_k)
        sp_hw = self._spin(float(s.get("head_width", 3.0)), 0.5, 20.0, 0.5, 1, " px")
        sp_hw.valueChanged.connect(self._emit("path.head_width"))
        f.addRow("头段线宽", sp_hw)
        sp_tw = self._spin(float(s.get("tail_width", 1.0)), 0.5, 20.0, 0.5, 1, " px")
        sp_tw.valueChanged.connect(self._emit("path.tail_width"))
        f.addRow("尾段线宽", sp_tw)
        sp_ha = self._int_spin(int(s.get("head_alpha", 255)), 0, 255, "")
        sp_ha.valueChanged.connect(self._emit("path.head_alpha"))
        f.addRow("头段透明度", sp_ha)
        sp_ta = self._int_spin(int(s.get("tail_alpha", 40)), 0, 255, "")
        sp_ta.valueChanged.connect(self._emit("path.tail_alpha"))
        f.addRow("尾段透明度", sp_ta)
        root.addWidget(gb)

    def _build_group_hud(self, root: QVBoxLayout, s: dict) -> None:
        """P9：HUD 叠加层 + 数字面板共享设置（三方同步入口）。"""
        from gui.widgets._hud_model import HUD_ITEM_KEYS, HUD_ITEM_META, HUD_DEFAULTS
        # 容错：apply_settings 还未灌入时 s 可能为空
        if not s:
            s = copy.deepcopy(HUD_DEFAULTS)
        gb = QGroupBox("HUD（叠加层 + 数字面板）", self)
        v = QVBoxLayout(gb)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(4)

        # ---- 叠加层外观 ----
        ov_box = QGroupBox("叠加层外观", gb)
        ov_form = QFormLayout(ov_box)
        ov = s.get("overlay", {})
        ck_show = QCheckBox()
        ck_show.setChecked(bool(ov.get("visible", True)))
        ck_show.toggled.connect(self._emit("hud.overlay.visible"))
        ov_form.addRow("显示叠加层", ck_show)
        sp_fs = self._int_spin(int(ov.get("font_size_pt", 14)), 8, 48, " pt")
        sp_fs.valueChanged.connect(self._emit("hud.overlay.font_size_pt"))
        ov_form.addRow("字号", sp_fs)
        sp_op = self._spin(float(ov.get("opacity", 0.78)), 0.10, 1.00, 0.05, 2, "")
        sp_op.valueChanged.connect(self._emit("hud.overlay.opacity"))
        ov_form.addRow("不透明度", sp_op)
        cb_bg = _ColorButton(list(ov.get("bg_color", [10, 14, 22, 180])), ov_box)
        cb_bg.color_changed.connect(self._emit_color("hud.overlay.bg_color"))
        ov_form.addRow("背景色", cb_bg)
        cb_fg = _ColorButton(list(ov.get("fg_color", [220, 245, 220, 255])), ov_box)
        cb_fg.color_changed.connect(self._emit_color("hud.overlay.fg_color"))
        ov_form.addRow("文字色", cb_fg)
        v.addWidget(ov_box)

        # ---- 11 项可见性 ----
        it_box = QGroupBox("显示项目（叠加层 & 数字面板共用）", gb)
        it_form = QFormLayout(it_box)
        items = s.get("items", {})
        for k in HUD_ITEM_KEYS:
            cfg = items.get(k, {})
            ck = QCheckBox()
            ck.setChecked(bool(cfg.get("visible", True)))
            ck.toggled.connect(self._emit(f"hud.items.{k}.visible"))
            label = HUD_ITEM_META[k]["label"]
            unit = HUD_ITEM_META[k]["unit"]
            it_form.addRow(f"{label}  ({unit})", ck)
        v.addWidget(it_box)

        # ---- 世界坐标刻度（P9 AxisRulerItem）----
        ru = s.get("ruler", {})
        ru_box = QGroupBox("世界坐标刻度", gb)
        ru_form = QFormLayout(ru_box)
        ck_ru = QCheckBox()
        ck_ru.setChecked(bool(ru.get("enabled", True)))
        ck_ru.toggled.connect(self._emit("hud.ruler.enabled"))
        ru_form.addRow("启用刻度", ck_ru)
        sp_tm = self._int_spin(int(ru.get("tick_cm_minor", 50)), 10, 1000, " cm")
        sp_tm.valueChanged.connect(self._emit("hud.ruler.tick_cm_minor"))
        ru_form.addRow("小刻度间隔", sp_tm)
        sp_tM = self._int_spin(int(ru.get("tick_cm_major", 100)), 10, 5000, " cm")
        sp_tM.valueChanged.connect(self._emit("hud.ruler.tick_cm_major"))
        ru_form.addRow("主刻度间隔（带数字）", sp_tM)
        cb_rc = _ColorButton(list(ru.get("color", [120, 160, 200, 200])), ru_box)
        cb_rc.color_changed.connect(self._emit_color("hud.ruler.color"))
        ru_form.addRow("刻度颜色", cb_rc)
        cb_rt = _ColorButton(list(ru.get("text_color", [200, 220, 240, 255])), ru_box)
        cb_rt.color_changed.connect(self._emit_color("hud.ruler.text_color"))
        ru_form.addRow("数字颜色", cb_rt)
        v.addWidget(ru_box)

        root.addWidget(gb)

    def _build_group_render(self, root: QVBoxLayout, s: dict) -> None:
        gb = QGroupBox("渲染", self)
        f = QFormLayout(gb)
        sp = self._int_spin(s["fps"], 1, 120, " Hz")
        sp.valueChanged.connect(self._emit("render.fps"))
        f.addRow("目标帧率", sp)
        ck = QCheckBox()
        ck.setChecked(bool(s["antialias"]))
        ck.toggled.connect(self._emit("render.antialias"))
        f.addRow("通用抗锯齿", ck)
        cb = _ColorButton(s["bg_color"], gb)
        cb.color_changed.connect(self._emit_color("render.bg_color"))
        f.addRow("背景色", cb)
        sp2 = self._spin(s["camera_distance"], 50.0, 5000.0, 50.0, 0, " cm")
        sp2.valueChanged.connect(self._emit("render.camera_distance"))
        f.addRow("相机距离", sp2)
        sp3 = self._spin(s["camera_elevation"], -89.0, 89.0, 1.0, 0, " °")
        sp3.valueChanged.connect(self._emit("render.camera_elevation"))
        f.addRow("相机仰角", sp3)
        sp4 = self._spin(s["camera_azimuth"], -360.0, 360.0, 5.0, 0, " °")
        sp4.valueChanged.connect(self._emit("render.camera_azimuth"))
        f.addRow("相机方位", sp4)
        root.addWidget(gb)


# ============================================================
#                       主 Widget
# ============================================================
def _deep_merge(dst: dict, src: dict) -> dict:
    """src 覆盖 dst，dict 深合并，其它键直接覆盖。返回 dst。"""
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(dst.get(k), dict):
            _deep_merge(dst[k], v)
        else:
            dst[k] = v
    return dst


def _rgba_to_float(rgba: list) -> tuple:
    seq = (list(rgba) + [255, 255, 255, 255])[:4]
    r, g, b, a = seq
    return (r / 255.0, g / 255.0, b / 255.0, a / 255.0)


def _color_arr(rgba_float: tuple, n: int) -> Any:
    """展开单一颜色为 Nx4 numpy 数组，兼容 pyqtgraph 0.14 GLLinePlotItem 的 nbytes 要求。"""
    nn = max(2, int(n))
    a = np.empty((nn, 4), dtype=np.float32)
    a[:, 0] = float(rgba_float[0])
    a[:, 1] = float(rgba_float[1])
    a[:, 2] = float(rgba_float[2])
    a[:, 3] = float(rgba_float[3]) if len(rgba_float) > 3 else 1.0
    return a


# ---- P8：分段渲染工具（薄包装，避免在主流程里写 import 增加阅读成本）----
from gui.widgets._path_segments import (  # noqa: E402
    segments_by_age as _segments_by_age,
    lerp_scalar as _seg_lerp,
    lerp_alpha_byte as _seg_lerp_alpha,
)


def _apply_transform(m: Any, p: tuple) -> Any:
    """对 (x,y,z) 应用 pyqtgraph Transform3D（4x4），返回 numpy.array([wx, wy, wz])。"""
    px, py, pz = float(p[0]), float(p[1]), float(p[2])
    try:
        # Transform3D.map((x,y,z)) 返回 QVector3D
        qv = m.map([px, py, pz])
        return np.array([float(qv[0]), float(qv[1]), float(qv[2])], dtype=float)
    except Exception:
        try:
            qv = m.map(px, py, pz)
            return np.array([qv.x(), qv.y(), qv.z()], dtype=float)
        except Exception:
            return np.array([px, py, pz], dtype=float)



def _make_cone_mesh(radius_cm: float, length_cm: float, cols: int = 16) -> Any:
    """生成沿 +X 方向、顶点在原点的圆锥（即朝向 +X 的箭头头）。

    底面圆心位于 (-length_cm, 0, 0)，半径 radius_cm；顶点位于 (0,0,0)。
    """
    if radius_cm <= 0.0 or length_cm <= 0.0:
        return None
    import math
    apex = [0.0, 0.0, 0.0]
    base_center = [-float(length_cm), 0.0, 0.0]
    rim = []
    for i in range(cols):
        a = 2.0 * math.pi * i / cols
        rim.append([-float(length_cm), float(radius_cm) * math.cos(a), float(radius_cm) * math.sin(a)])
    verts = [apex, base_center] + rim
    faces = []
    # 侧面：每个相邻两 rim 点与 apex 形成三角形
    for i in range(cols):
        a = 2 + i
        b = 2 + (i + 1) % cols
        faces.append([0, a, b])      # 侧面三角形
        faces.append([1, b, a])      # 底面三角形（封口）
    return MeshData(vertexes=np.array(verts, dtype=float), faces=np.array(faces, dtype=int))


def _make_cube_mesh(size_cm: float) -> Any:
    s = size_cm / 2.0
    verts = np.array(
        [
            [-s, -s, -s], [+s, -s, -s], [+s, +s, -s], [-s, +s, -s],
            [-s, -s, +s], [+s, -s, +s], [+s, +s, +s], [-s, +s, +s],
        ],
        dtype=float,
    )
    faces = np.array(
        [
            [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
            [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7],
        ],
        dtype=int,
    )
    return MeshData(vertexes=verts, faces=faces)


class PathVisualizationPlaceholder(QWidget):
    """P5：路径可视化主 Widget（含设置面板）。

    主入口：`update_snapshot(snap: PathSnapshot)`，由 TelemetryBus.path_updated 触发。
    对外信号：
      - settings_changed(dict)：当前完整 settings；主窗口写入 config + 同步 tracker/bus
      - reset_requested()：主窗口调 bus.reset_path()
      - refresh_requested()：通常无外部副作用，widget 内已重建场景
    """

    settings_changed = Signal(dict)
    reset_requested = Signal()
    refresh_requested = Signal()
    # P5.5：面板录制按钮 → 主窗口负责选路径/启停服务
    record_toggle_requested = Signal(bool)
    # P10：轨迹导出（主窗口负责 QFileDialog + 写文件）
    export_csv_requested = Signal()

    def __init__(self, parent: QWidget | None = None,
                 settings: Optional[dict] = None) -> None:
        super().__init__(parent)
        self.setObjectName("PathVisualizationWidget")

        # 当前 settings：深拷贝默认值再覆盖
        self._s: dict[str, Any] = copy.deepcopy(DEFAULTS)
        if settings:
            _deep_merge(self._s, settings)

        # 缓存最近一次快照，便于"刷新场景"后立刻重绘
        self._last_snap: Any = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 顶部工具条 ----
        bar_w = QWidget(self)
        bar = QHBoxLayout(bar_w)
        bar.setContentsMargins(4, 2, 4, 2)
        bar.setSpacing(4)
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
        bar.addStretch(1)
        root.addWidget(bar_w)

        if not _GL_OK:
            self._gl_ok = False
            self._view = None
            self._splitter = None
            tip = QLabel(
                "3D 场景未启用：缺少 pyqtgraph.opengl 或 PyOpenGL。\n"
                f"导入错误：{_GL_IMPORT_ERR}\n"
                "请运行：pip install pyqtgraph PyOpenGL",
                self,
            )
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setWordWrap(True)
            tip.setStyleSheet("color: #d33; padding: 16px;")
            root.addWidget(tip, 1)
            # 即使无 GL 也建一个 panel（不挂入布局），便于持久化调参
            self._panel = _SettingsPanel(self._s, self)
            self._panel.setVisible(False)
            self._panel.value_changed.connect(self._on_panel_value_changed)
            self._panel.reset_requested.connect(self.reset_requested)
            self._panel.refresh_requested.connect(self._on_refresh_clicked)
            self._panel.record_toggle_requested.connect(self.record_toggle_requested)
            self._panel.viewpoint_preset_requested.connect(self._on_viewpoint_preset)
            self._panel.export_csv_requested.connect(self.export_csv_requested)
            return

        # ---- 水平 Splitter：左=3D，右=设置面板 ----
        self._gl_ok = True
        self._splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self._splitter.setChildrenCollapsible(True)
        self._view = GLViewWidget(self._splitter)
        self._splitter.addWidget(self._view)

        # P9：HUD 叠加层（可拖动、鸟瞰上方）
        try:
            from gui.widgets.hud_overlay_widget import HudOverlayWidget
            self._hud_overlay = HudOverlayWidget(self._view)
            self._hud_overlay.apply_settings(self._s.get("hud", {}))
            self._hud_overlay.settings_changed.connect(self._on_hud_overlay_settings)
        except Exception:
            self._hud_overlay = None

        self._panel = _SettingsPanel(self._s, self._splitter)
        self._panel.value_changed.connect(self._on_panel_value_changed)
        self._panel.reset_requested.connect(self.reset_requested)
        self._panel.refresh_requested.connect(self._on_refresh_clicked)
        self._panel.record_toggle_requested.connect(self.record_toggle_requested)
        self._panel.viewpoint_preset_requested.connect(self._on_viewpoint_preset)
        self._panel.export_csv_requested.connect(self.export_csv_requested)
        self._splitter.addWidget(self._panel)
        self._splitter.setStretchFactor(0, 5)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([600, 280])
        # 默认隐藏右侧面板
        self._panel.setVisible(False)
        root.addWidget(self._splitter, 1)

        # GL items 占位
        self._grid_items: list = []
        self._axis = None
        self._nose = None
        self._cube = None
        self._path = None
        self._path_segments: list = []   # P8：K 段 LineItem（segmented 模式）
        self._vel_arrow = None
        self._ruler_items: list = []     # P9.5：轴向刻度文字 + 刻度线

        self._build_scene()

    # =====================================================
    #                       对外 API
    # =====================================================
    def apply_settings(self, settings: dict) -> None:
        """外部（如主窗口启动时从 config 还原）批量灌入参数。不会回发 settings_changed。"""
        if not settings:
            return
        _deep_merge(self._s, settings)
        if self._gl_ok:
            self._build_scene()
            if self._last_snap is not None:
                self.update_snapshot(self._last_snap)
        # P9：HUD 叠加层同步
        if getattr(self, "_hud_overlay", None) is not None and "hud" in settings:
            try:
                self._hud_overlay.apply_settings(settings.get("hud", {}))
            except Exception:
                pass
        # 同步面板控件显示（整体重建面板最简单）
        self._rebuild_panel()

    def current_settings(self) -> dict:
        """返回当前完整 settings（深拷贝，外部修改无副作用）。"""
        return copy.deepcopy(self._s)

    def set_recording_state(self, active: bool, path: str = "", count: int = 0) -> None:
        """P5.5：主窗口同步记录状态到设置面板的"记录"分组。"""
        if self._panel is not None and hasattr(self._panel, "set_recording_state"):
            try:
                self._panel.set_recording_state(active, path, count)
            except Exception:
                pass

    # =====================================================
    #                   设置面板交互
    # =====================================================
    def _on_toggle_settings(self, checked: bool) -> None:
        if self._panel is not None and self._splitter is not None:
            self._panel.setVisible(checked)

    def _on_panel_value_changed(self, path: str, value: Any) -> None:
        """单个控件变化 → 写入 self._s → 增量/重建相关 item → emit 全量 settings。"""
        # 写入
        keys = path.split(".")
        d = self._s
        for k in keys[:-1]:
            d = d.setdefault(k, {})
        d[keys[-1]] = value
        # 重建对应分组
        if self._gl_ok:
            grp = keys[0]
            if grp == "cube":
                self._rebuild_cube()
            elif grp == "nose":
                self._rebuild_nose()
            elif grp == "axis":
                self._rebuild_axis()
            elif grp == "vel_arrow":
                self._rebuild_vel_arrow()
            elif grp == "grid":
                self._rebuild_grids()
            elif grp == "path":
                self._rebuild_path_item()
            elif grp == "render":
                self._apply_render_settings()
            elif grp == "hud":
                # P9：HUD 设置 → 叠加层 + 广播给主窗（主窗转发给数字面板 Dock）
                if getattr(self, "_hud_overlay", None) is not None:
                    try:
                        self._hud_overlay.apply_settings(self._s.get("hud", {}))
                    except Exception:
                        pass
                # 刻度尺子项变动时重建
                if path.startswith("hud.ruler"):
                    self._rebuild_axis_ruler()
            # 刷新一帧
            if self._last_snap is not None:
                self.update_snapshot(self._last_snap)
        # 通知主窗口持久化 + 同步 tracker / bus
        self.settings_changed.emit(self.current_settings())

    def _on_refresh_clicked(self) -> None:
        """刷新按钮：拆除所有 item 重新构建，再发一次 snapshot。"""
        if self._gl_ok:
            self._build_scene()
            if self._last_snap is not None:
                self.update_snapshot(self._last_snap)
        self.refresh_requested.emit()

    def _on_hud_overlay_settings(self, hud_settings: dict) -> None:
        """P9：HUD 叠加层拖动/参数变 → 写回 self._s["hud"] 并广播给主窗。"""
        if not hud_settings:
            return
        self._s.setdefault("hud", {})
        _deep_merge(self._s["hud"], hud_settings)
        self.settings_changed.emit(self.current_settings())

    # =====================================================
    #                  P10：视角预设
    # =====================================================
    _VIEWPOINT_PRESETS = {
        # name -> (distance_cm, elevation_deg, azimuth_deg)
        "top":  (600.0, 89.0,  0.0),
        "side": (600.0,  5.0, 90.0),
        "free": (600.0, 28.0, 45.0),
    }

    def _on_viewpoint_preset(self, name: str) -> None:
        """P10：俯视/侧视/自由 三按钮 → 写 self._s["render"] 并 setCameraPosition。"""
        preset = self._VIEWPOINT_PRESETS.get(str(name))
        if preset is None:
            return
        dist, elev, azim = preset
        rs = self._s.setdefault("render", {})
        rs["camera_distance"] = float(dist)
        rs["camera_elevation"] = float(elev)
        rs["camera_azimuth"] = float(azim)
        if self._gl_ok and self._view is not None:
            try:
                self._view.setCameraPosition(distance=dist, elevation=elev, azimuth=azim)
            except Exception:
                pass
        self.settings_changed.emit(self.current_settings())

    # =====================================================
    #                  P10：轨迹 CSV 导出
    # =====================================================
    def export_path_csv(self, file_path: str) -> int:
        """将最近一次 snapshot 的轨迹点列表写入 CSV，返回写入点数。

        格式：``t_mono,x_cm,y_cm,z_cm`` 首行 header。无轨迹则只写 header，返回 0。
        任何异常上抛，交由调用层（主窗）提示用户。
        """
        snap = self._last_snap
        points = getattr(snap, "points", ()) if snap is not None else ()
        with open(file_path, "w", encoding="utf-8", newline="") as f:
            f.write("t_mono,x_cm,y_cm,z_cm\n")
            n = 0
            for p in points:
                f.write(f"{float(p.ts):.6f},{float(p.x_cm):.3f},{float(p.y_cm):.3f},{float(p.z_cm):.3f}\n")
                n += 1
        return n

    # =====================================================
    #                  P6#3 GL 资源清理
    # =====================================================
    def cleanup_gl(self) -> None:
        """显式拆除所有 GL items 并断开强引用，便于 GC 回收 VBO。

        触发时机：closeEvent；主窗口在主路径关闭路径可视化 Dock 时也可主动调用。
        幂等：多次调用安全。
        """
        # 标记 GL 不可用，防止 update_snapshot 在拆解过程中继续访问 _view
        self._gl_ok = False
        # P9：先拆 HUD 叠加层（QWidget，不是 GL item）
        hud = getattr(self, "_hud_overlay", None)
        if hud is not None:
            try:
                hud.setParent(None)
                hud.deleteLater()
            except Exception:
                pass
            self._hud_overlay = None
        if self._view is None:
            return
        # 1) 拆 grid 列表
        for it in list(self._grid_items):
            self._remove_item(it)
        self._grid_items = []
        # P9.5：拆 ruler 列表
        for it in list(getattr(self, "_ruler_items", []) or []):
            self._remove_item(it)
        self._ruler_items = []
        # 2) 拆 axis 杆 + 圆锥头 + 字标（带 getattr 兜底缺字段环境）
        for name in (
            "_axis", "_axis_head_x", "_axis_head_y", "_axis_head_z",
            "_axis_lbl_x", "_axis_lbl_y", "_axis_lbl_z",
            "_nose", "_cube", "_path",
            "_vel_arrow", "_vel_head",
        ):
            it = getattr(self, name, None)
            self._remove_item(it)
            try:
                setattr(self, name, None)
            except Exception:
                pass
        # 2.5）P8：拆 K 段 LineItem 列表
        for it in list(getattr(self, "_path_segments", []) or []):
            self._remove_item(it)
        try:
            self._path_segments = []
        except Exception:
            pass
        # 3) 兜底：把 view.items 里残留对象（万一上面漏掉）逐个 removeItem
        try:
            for it in list(getattr(self._view, "items", []) or []):
                try:
                    self._view.removeItem(it)
                except Exception:
                    pass
        except Exception:
            pass

    def closeEvent(self, event) -> None:  # noqa: N802 (Qt 命名)
        """窗口关闭时先释放 GL 资源，再走默认关闭流程。"""
        try:
            self.cleanup_gl()
        except Exception:
            pass
        super().closeEvent(event)

    def _rebuild_panel(self) -> None:
        """整体重建右侧面板（apply_settings 时同步控件值显示）。"""
        if self._panel is None:
            return
        visible = self._panel.isVisible()
        new_panel = _SettingsPanel(self._s, self)
        new_panel.value_changed.connect(self._on_panel_value_changed)
        new_panel.reset_requested.connect(self.reset_requested)
        new_panel.refresh_requested.connect(self._on_refresh_clicked)
        new_panel.record_toggle_requested.connect(self.record_toggle_requested)
        new_panel.viewpoint_preset_requested.connect(self._on_viewpoint_preset)
        new_panel.export_csv_requested.connect(self.export_csv_requested)
        if self._splitter is not None:
            old = self._panel
            idx = self._splitter.indexOf(old)
            sizes = self._splitter.sizes()
            self._splitter.insertWidget(idx, new_panel)
            old.setParent(None)
            old.deleteLater()
            if len(sizes) >= 2:
                self._splitter.setSizes(sizes)
        else:
            self._panel.setParent(None)
            self._panel.deleteLater()
        self._panel = new_panel
        self._panel.setVisible(visible)

    # =====================================================
    #                   场景构建（全量）
    # =====================================================
    def _build_scene(self) -> None:
        if not self._gl_ok or self._view is None:
            return
        # 清空旧 items
        for it in list(getattr(self._view, "items", [])):
            try:
                self._view.removeItem(it)
            except Exception:
                pass
        self._grid_items = []
        self._axis = None
        self._nose = None
        self._cube = None
        self._path = None
        self._path_segments = []
        self._vel_arrow = None
        self._ruler_items = []

        self._apply_render_settings()
        self._rebuild_grids()
        self._rebuild_axis()
        self._rebuild_nose()
        self._rebuild_cube()
        self._rebuild_path_item()
        self._rebuild_vel_arrow()
        self._rebuild_axis_ruler()  # P9.5

    def _apply_render_settings(self) -> None:
        if self._view is None:
            return
        s = self._s["render"]
        bg = s["bg_color"]
        self._view.setBackgroundColor(int(bg[0]), int(bg[1]), int(bg[2]))
        self._view.setCameraPosition(
            distance=float(s["camera_distance"]),
            elevation=float(s["camera_elevation"]),
            azimuth=float(s["camera_azimuth"]),
        )

    # ---- 子项重建（单独可调用）----
    def _remove_item(self, item: Any) -> None:
        if item is None or self._view is None:
            return
        try:
            self._view.removeItem(item)
        except Exception:
            pass

    def _rebuild_grids(self) -> None:
        for it in self._grid_items:
            self._remove_item(it)
        self._grid_items = []
        s = self._s["grid"]
        size = float(s["size_cm"])
        step = float(s["step_cm"])
        color = tuple(int(c) for c in s["color"])
        if bool(s["plane_xy"]):
            g = GLGridItem()
            g.setSize(x=size, y=size, z=0)
            g.setSpacing(x=step, y=step, z=step)
            g.setColor(color)
            self._view.addItem(g)
            self._grid_items.append(g)
        if bool(s["plane_xz"]):
            g = GLGridItem()
            g.setSize(x=size, y=size, z=0)
            g.setSpacing(x=step, y=step, z=step)
            g.setColor(color)
            g.rotate(90, 1, 0, 0)
            self._view.addItem(g)
            self._grid_items.append(g)
        if bool(s["plane_yz"]):
            g = GLGridItem()
            g.setSize(x=size, y=size, z=0)
            g.setSpacing(x=step, y=step, z=step)
            g.setColor(color)
            g.rotate(90, 0, 1, 0)
            self._view.addItem(g)
            self._grid_items.append(g)

    def _rebuild_axis_ruler(self) -> None:
        """P9.5：沿 +X/+Y/+Z 三轴渲染 cm 刻度文字（major 间隔）+ 小刻度线（minor 间隔）。

        刻度范围：±grid.size_cm/2；以 PathTracker 原点（世界 0,0,0）为零点。
        驱动配置：`hud.ruler.{enabled, tick_cm_minor, tick_cm_major, color, text_color}`。
        """
        # 清旧
        for it in list(getattr(self, "_ruler_items", []) or []):
            self._remove_item(it)
        self._ruler_items = []
        if self._view is None:
            return
        ruler = (self._s.get("hud") or {}).get("ruler") or {}
        if not bool(ruler.get("enabled", True)):
            return
        try:
            minor = float(ruler.get("tick_cm_minor", 50.0))
            major = float(ruler.get("tick_cm_major", 100.0))
        except Exception:
            return
        if minor <= 0.0 or major <= 0.0:
            return
        # 范围按 grid.size_cm 的一半（与栅格一致）
        try:
            half = float(self._s["grid"]["size_cm"]) / 2.0
        except Exception:
            half = 200.0
        if half <= 0.0:
            return
        col = tuple(int(c) for c in (ruler.get("color") or [120, 160, 200, 200]))
        tcol = tuple(int(c) for c in (ruler.get("text_color") or [200, 220, 240, 255]))
        # ---- 小刻度线（minor）：三轴上的短横线 ----
        tick_half = max(2.0, half * 0.01)  # 视觉长度
        seg_pts = []  # 用一条 GLLinePlotItem (line_segments) 绘出所有 minor 刻度
        # 沿 X 轴：刻度线在 XY 平面短横（沿 Y 方向）
        v = minor
        while v <= half + 1e-6:
            for sgn in (1.0, -1.0):
                x = sgn * v
                seg_pts.append((x, -tick_half, 0.0))
                seg_pts.append((x, tick_half, 0.0))
                # Y 轴：刻度沿 X 方向
                seg_pts.append((-tick_half, x, 0.0))
                seg_pts.append((tick_half, x, 0.0))
                # Z 轴：刻度沿 X 方向（垂直方向上）
                seg_pts.append((-tick_half, 0.0, x))
                seg_pts.append((tick_half, 0.0, x))
            v += minor
        if seg_pts:
            try:
                arr = np.array(seg_pts, dtype=float)
                line = GLLinePlotItem(pos=arr, color=tuple(c / 255.0 for c in col),
                                       width=1.0, mode="lines", antialias=True)
                self._view.addItem(line)
                self._ruler_items.append(line)
            except Exception:
                pass
        # ---- 大刻度数字（major）：每 major 间隔放一个 GLTextItem ----
        font = None
        try:
            from PySide6.QtGui import QFont
            font = QFont()
            font.setPointSize(9)
        except Exception:
            font = None
        v = major
        while v <= half + 1e-6:
            for sgn in (1.0, -1.0):
                d = sgn * v
                # 三轴各放一个；标签是 cm 数值（带正负号简洁显示）
                txt = f"{int(d)}"
                for pos in (
                    (d, 0.0, 0.0),
                    (0.0, d, 0.0),
                    (0.0, 0.0, d),
                ):
                    try:
                        ti = GLTextItem(text=txt, color=tcol, font=font) if font else GLTextItem(text=txt, color=tcol)
                    except TypeError:
                        ti = GLTextItem(text=txt, color=tcol)
                    try:
                        ti.setData(pos=pos)
                    except Exception:
                        pass
                    self._view.addItem(ti)
                    self._ruler_items.append(ti)
            v += major

    def _rebuild_axis(self) -> None:
        """三轴：1 个 GLAxisItem 杆 + 3 个圆锥头（X 红 / Y 绿 / Z 蓝）+ 3 个 X/Y/Z 字标。"""
        # 拆除旧 items
        for it in (self._axis,
                   getattr(self, "_axis_head_x", None),
                   getattr(self, "_axis_head_y", None),
                   getattr(self, "_axis_head_z", None),
                   getattr(self, "_axis_lbl_x", None),
                   getattr(self, "_axis_lbl_y", None),
                   getattr(self, "_axis_lbl_z", None)):
            self._remove_item(it)
        self._axis = None
        self._axis_head_x = None
        self._axis_head_y = None
        self._axis_head_z = None
        self._axis_lbl_x = None
        self._axis_lbl_y = None
        self._axis_lbl_z = None

        s = self._s["axis"]
        if not bool(s["visible"]):
            return
        L = float(s["length_cm"])
        # 杆（GLAxisItem 内置 RGB 配色：X=红, Y=绿, Z=蓝）
        ax = GLAxisItem(glOptions="opaque")
        ax.setSize(x=L, y=L, z=L)
        self._view.addItem(ax)
        self._axis = ax

        # 箭头头：3 个圆锥，每个朝向各自轴 +
        hr = float(s.get("head_radius_cm", 2.0))
        hl = float(s.get("head_length_cm", 5.0))
        cone_mesh = _make_cone_mesh(hr, hl)
        if cone_mesh is not None:
            # X 头（红）：cone 原始朝向 +X，无需旋转
            self._axis_head_x = GLMeshItem(meshdata=cone_mesh, smooth=True,
                                            color=(1.0, 0.0, 0.0, 1.0),
                                            shader="shaded", glOptions="opaque")
            self._view.addItem(self._axis_head_x)
            # Y 头（绿）：cone 旋转 +90° 绕 Z（+X → +Y）
            self._axis_head_y = GLMeshItem(meshdata=cone_mesh, smooth=True,
                                            color=(0.0, 1.0, 0.0, 1.0),
                                            shader="shaded", glOptions="opaque")
            self._view.addItem(self._axis_head_y)
            # Z 头（蓝）：cone 旋转 -90° 绕 Y（+X → +Z）
            self._axis_head_z = GLMeshItem(meshdata=cone_mesh, smooth=True,
                                            color=(0.0, 0.4, 1.0, 1.0),
                                            shader="shaded", glOptions="opaque")
            self._view.addItem(self._axis_head_z)

        # X/Y/Z 字标
        if bool(s.get("labels_visible", True)):
            try:
                from PySide6.QtGui import QFont
                font = QFont()
                font.setPointSize(int(s.get("label_size", 14)))
                font.setBold(True)
                self._axis_lbl_x = GLTextItem(text="X", color=(255, 64, 64, 255), font=font)
                self._axis_lbl_y = GLTextItem(text="Y", color=(64, 255, 64, 255), font=font)
                self._axis_lbl_z = GLTextItem(text="Z", color=(64, 160, 255, 255), font=font)
                self._view.addItem(self._axis_lbl_x)
                self._view.addItem(self._axis_lbl_y)
                self._view.addItem(self._axis_lbl_z)
            except Exception:
                # GLTextItem 在某些环境不支持 font 参数，退化为纯文本
                self._axis_lbl_x = GLTextItem(text="X", color=(255, 64, 64, 255))
                self._axis_lbl_y = GLTextItem(text="Y", color=(64, 255, 64, 255))
                self._axis_lbl_z = GLTextItem(text="Z", color=(64, 160, 255, 255))
                self._view.addItem(self._axis_lbl_x)
                self._view.addItem(self._axis_lbl_y)
                self._view.addItem(self._axis_lbl_z)

    def _rebuild_nose(self) -> None:
        self._remove_item(self._nose)
        self._nose = None
        s = self._s["nose"]
        r = float(s["radius_cm"])
        md = MeshData.sphere(rows=10, cols=14, radius=r)
        self._nose = GLMeshItem(
            meshdata=md,
            smooth=True,
            color=_rgba_to_float(s["color"]),
            shader="shaded",
            glOptions="opaque",
        )
        self._view.addItem(self._nose)

    def _rebuild_cube(self) -> None:
        self._remove_item(self._cube)
        self._cube = None
        s = self._s["cube"]
        self._cube = GLMeshItem(
            meshdata=_make_cube_mesh(float(s["size_cm"])),
            smooth=False,
            color=_rgba_to_float(s["color"]),
            shader="shaded",
            drawEdges=bool(s["draw_edges"]),
            edgeColor=_rgba_to_float(s["edge_color"]),
            glOptions="translucent",
        )
        self._view.addItem(self._cube)

    def _rebuild_path_item(self) -> None:
        # 清旧：无论模式都拆 fade-line 和 segments，避免残留
        self._remove_item(self._path)
        self._path = None
        for it in list(self._path_segments):
            self._remove_item(it)
        self._path_segments = []
        s = self._s["path"]
        mode = str(s.get("render_mode", "segmented")).lower()
        base_color = _rgba_to_float(s["color"])
        antialias = bool(s["antialias"])
        if mode == "segmented":
            # K 段：每段一个 GLLinePlotItem，宽度预烘、颜色每帧更新
            k = max(1, min(64, int(s.get("k_segments", 8))))
            head_w = float(s.get("head_width", 3.0))
            tail_w = float(s.get("tail_width", 1.0))
            for i in range(k):
                w = _seg_lerp(tail_w, head_w, k, i)
                seg = GLLinePlotItem(
                    pos=np.zeros((2, 3), dtype=float),
                    color=_color_arr(base_color, 2),
                    width=float(w),
                    antialias=antialias,
                    mode="line_strip",
                )
                self._view.addItem(seg)
                self._path_segments.append(seg)
            return
        # fade / 其它：退回单 line（P5 兼容）
        self._path = GLLinePlotItem(
            pos=np.zeros((2, 3), dtype=float),
            color=_color_arr(base_color, 2),
            width=float(s["width"]),
            antialias=antialias,
            mode="line_strip",
        )
        self._view.addItem(self._path)

    def _rebuild_vel_arrow(self) -> None:
        self._remove_item(self._vel_arrow)
        self._remove_item(getattr(self, "_vel_head", None))
        self._vel_arrow = None
        self._vel_head = None
        s = self._s["vel_arrow"]
        self._vel_arrow = GLLinePlotItem(
            pos=np.zeros((2, 3), dtype=float),
            color=_color_arr(_rgba_to_float(s["color"]), 2),
            width=float(s["width"]),
            antialias=bool(self._s["render"]["antialias"]),
            mode="lines",
        )
        self._view.addItem(self._vel_arrow)
        # 圆锥箭头头：朝 +X 的 cone，每帧根据速度方向旋转到位
        hr = float(s.get("head_radius_cm", 2.0))
        hl = float(s.get("head_length_cm", 5.0))
        cone_mesh = _make_cone_mesh(hr, hl)
        if cone_mesh is not None:
            self._vel_head = GLMeshItem(
                meshdata=cone_mesh,
                smooth=True,
                color=_rgba_to_float(s["color"]),
                shader="shaded",
                glOptions="opaque",
            )
            self._view.addItem(self._vel_head)

    # =====================================================
    #                  快照渲染（每帧）
    # =====================================================
    def update_snapshot(self, snap: Any) -> None:
        if not self._gl_ok or snap is None:
            return
        try:
            x, y, z = (float(c) for c in snap.pos_cm)
            roll, pitch, yaw = (float(a) for a in snap.attitude_deg)
            vx_l, vy_l, vz_l = (float(v) for v in snap.vel_local_cmps)
            yaw0 = float(snap.yaw0_deg)
        except Exception:
            return
        self._last_snap = snap

        # ---- 立方体 / 三轴 / 机头：共享 M = T·Rz·Ry·Rx ----
        # yaw 翻号：IMU 报 NWU yaw（CW=减少），但用户期望的可视化方向是现实 CW = GUI CW；
        # pyqtgraph rotate() 是右手 CCW 正，从默认 elevation=30°/azimuth=45° 相机视角看，
        # 直接传 +yaw_local 会让 cube 视觉旋转方向与现实相反，故此处取负翻转
        yaw_local = yaw - yaw0
        m = Transform3D()
        m.translate(x, y, z)
        m.rotate(-yaw_local, 0.0, 0.0, 1.0)
        m.rotate(pitch,      0.0, 1.0, 0.0)
        m.rotate(roll,       1.0, 0.0, 0.0)
        if self._cube is not None:
            self._cube.setTransform(m)
        if self._axis is not None:
            self._axis.setTransform(m)
        # P5.5：三轴箭头头 + X/Y/Z 字标 → 都在轴末端 + 偏移
        ax_s = self._s["axis"]
        L = float(ax_s["length_cm"])
        lbl_off = float(ax_s.get("label_offset_cm", 3.0))
        # X 头
        if getattr(self, "_axis_head_x", None) is not None:
            m_x = Transform3D(m)
            m_x.translate(L, 0.0, 0.0)
            self._axis_head_x.setTransform(m_x)
        # Y 头：cone 默认朝 +X，需要绕 Z 转 +90° → +Y
        if getattr(self, "_axis_head_y", None) is not None:
            m_y = Transform3D(m)
            m_y.translate(0.0, L, 0.0)
            m_y.rotate(90.0, 0.0, 0.0, 1.0)
            self._axis_head_y.setTransform(m_y)
        # Z 头：cone 默认朝 +X，需要绕 Y 转 -90° → +Z
        if getattr(self, "_axis_head_z", None) is not None:
            m_z = Transform3D(m)
            m_z.translate(0.0, 0.0, L)
            m_z.rotate(-90.0, 0.0, 1.0, 0.0)
            self._axis_head_z.setTransform(m_z)
        # 字标：GLTextItem 用 setData(pos=...)，位置取轴末端 + 偏移（世界坐标）
        if getattr(self, "_axis_lbl_x", None) is not None:
            # 计算轴端世界坐标：M·(L+off, 0, 0)
            self._axis_lbl_x.setData(pos=_apply_transform(m, (L + lbl_off, 0.0, 0.0)))
        if getattr(self, "_axis_lbl_y", None) is not None:
            self._axis_lbl_y.setData(pos=_apply_transform(m, (0.0, L + lbl_off, 0.0)))
        if getattr(self, "_axis_lbl_z", None) is not None:
            self._axis_lbl_z.setData(pos=_apply_transform(m, (0.0, 0.0, L + lbl_off)))
        if self._nose is not None:
            nose_offset = (
                float(self._s["cube"]["size_cm"]) / 2.0
                + float(self._s["nose"]["radius_cm"])
                + float(self._s["nose"]["gap_cm"])
            )
            m_nose = Transform3D(m)
            m_nose.translate(nose_offset, 0.0, 0.0)
            self._nose.setTransform(m_nose)

        # ---- 路径线 ----
        pts = snap.points or ()
        n = len(pts)
        path_s = self._s["path"]
        base_color = _rgba_to_float(path_s["color"])
        mode = str(path_s.get("render_mode", "segmented")).lower()
        # ---- P8：segmented 分段渲染 ----
        if mode == "segmented" and self._path_segments:
            k = len(self._path_segments)
            head_a = int(path_s.get("head_alpha", 255))
            tail_a = int(path_s.get("tail_alpha", 40))
            if n >= 2:
                buckets = _segments_by_age(pts, k)
                for i, seg_pts in enumerate(buckets):
                    seg_item = self._path_segments[i]
                    alpha_byte = _seg_lerp_alpha(tail_a, head_a, k, i)
                    a_f = alpha_byte / 255.0
                    seg_color = (base_color[0], base_color[1], base_color[2], base_color[3] * a_f)
                    m = len(seg_pts)
                    if m >= 2:
                        arr = np.fromiter(
                            (c for p in seg_pts for c in (p.x_cm, p.y_cm, p.z_cm)),
                            dtype=float,
                            count=m * 3,
                        ).reshape(-1, 3)
                        seg_item.setData(pos=arr, color=_color_arr(seg_color, m))
                    else:
                        # 空段：折叠到机体位置避免残留旧线
                        arr = np.array([[x, y, z], [x, y, z]], dtype=float)
                        seg_item.setData(pos=arr, color=_color_arr(seg_color, 2))
            else:
                # n<2：所有段折叠到当前位置
                arr = np.array([[x, y, z], [x, y, z]], dtype=float)
                for seg_item in self._path_segments:
                    seg_item.setData(pos=arr, color=_color_arr(base_color, 2))
        # ---- fade 模式（P5 兼容）----
        elif self._path is not None:
            if n >= 2:
                arr = np.fromiter(
                    (c for p in pts for c in (p.x_cm, p.y_cm, p.z_cm)),
                    dtype=float,
                    count=n * 3,
                ).reshape(-1, 3)
                if bool(path_s["fade"]):
                    trail = max(0.001, float(path_s["trail_seconds"]))
                    tail_ts = float(pts[-1].ts)
                    colors = np.empty((n, 4), dtype=float)
                    for i, p in enumerate(pts):
                        age = max(0.0, tail_ts - float(p.ts))
                        ratio = 1.0 - min(1.0, age / trail)
                        colors[i, 0] = base_color[0]
                        colors[i, 1] = base_color[1]
                        colors[i, 2] = base_color[2]
                        colors[i, 3] = base_color[3] * ratio
                    self._path.setData(pos=arr, color=colors.astype(np.float32))
                else:
                    self._path.setData(pos=arr, color=_color_arr(base_color, n))
            elif n == 1:
                p = pts[0]
                arr = np.array(
                    [[p.x_cm, p.y_cm, p.z_cm], [p.x_cm, p.y_cm, p.z_cm]],
                    dtype=float,
                )
                self._path.setData(pos=arr, color=_color_arr(base_color, 2))
            else:
                arr = np.array([[x, y, z], [x, y, z]], dtype=float)
                self._path.setData(pos=arr, color=_color_arr(base_color, 2))

        # ---- 速度箭头 ----
        if self._vel_arrow is not None:
            vs = self._s["vel_arrow"]
            speed = (vx_l * vx_l + vy_l * vy_l + vz_l * vz_l) ** 0.5
            if speed < float(vs["min_speed_cmps"]):
                end = (x, y, z)
                show_head = False
                ux = uy = uz = 0.0
            else:
                arrow_len = min(
                    speed * float(vs["scale_cm_per_cmps"]),
                    float(vs["max_cm"]),
                )
                ux, uy, uz = vx_l / speed, vy_l / speed, vz_l / speed
                end = (x + ux * arrow_len, y + uy * arrow_len, z + uz * arrow_len)
                show_head = True
            self._vel_arrow.setData(pos=np.array([[x, y, z], list(end)], dtype=float))
            # 圆锥头：放在 end，朝向 (ux,uy,uz)
            if getattr(self, "_vel_head", None) is not None:
                if not show_head:
                    self._vel_head.setVisible(False)
                else:
                    self._vel_head.setVisible(True)
                    # 计算从 +X 轴到 (ux,uy,uz) 的旋转 (轴角)
                    import math
                    # +X 默认 → 目标方向
                    # 旋转轴 = (1,0,0) × (ux,uy,uz)；角度 = acos(ux)
                    cross = (0.0 * uz - 0.0 * uy, 0.0 * 0.0 - 1.0 * uz, 1.0 * uy - 0.0 * 0.0)
                    # 简化：cross = (0, -uz, uy)
                    cx, cy, cz = 0.0, -uz, uy
                    norm = math.sqrt(cx * cx + cy * cy + cz * cz)
                    ang_deg = math.degrees(math.acos(max(-1.0, min(1.0, ux))))
                    m_vh = Transform3D()
                    m_vh.translate(end[0], end[1], end[2])
                    if norm > 1e-9:
                        m_vh.rotate(ang_deg, cx / norm, cy / norm, cz / norm)
                    elif ux < 0.0:
                        # 方向是 -X，绕 Z 转 180°
                        m_vh.rotate(180.0, 0.0, 0.0, 1.0)
                    self._vel_head.setTransform(m_vh)

        # ---- P9：HUD 叠加层每帧数值同步 ----
        hud = getattr(self, "_hud_overlay", None)
        if hud is not None:
            try:
                hud.update_snapshot(snap)
            except Exception:
                pass
