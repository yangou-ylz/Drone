# -*- coding: utf-8 -*-
"""3D 姿态可视化面板（Phase 3.2）。

订阅 ImuDataHub.attitude，实时用一个"机体盒子"+机体三轴显示当前 roll/pitch/yaw。
世界系画网格 + 参考三轴，便于对照。右上角文字显示三角数值。

姿态旋转顺序：ZYX（yaw→pitch→roll），与 0x04 四元数解算欧拉角一致。
注：yaw 符号最终由真机视觉校验；本面板直接采用解码器输出的欧拉角。

无 pyqtgraph.opengl / PyOpenGL 时降级为提示文字（不崩）。
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QTimer, Slot
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from gui.imu_test.logger import get_logger

try:
    import math

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
    _GL_ERR: Optional[str] = None
except Exception as _exc:  # pragma: no cover
    _GL_OK = False
    _GL_ERR = str(_exc)


def _make_body_mesh() -> "MeshData":
    """机体盒子：沿 +X 拉长（机头 +X），扁平（Z 薄），便于看姿态。"""
    lx, ly, lz = 3.0, 1.6, 0.4  # 半长
    v = np.array(
        [
            [-lx, -ly, -lz], [+lx, -ly, -lz], [+lx, +ly, -lz], [-lx, +ly, -lz],
            [-lx, -ly, +lz], [+lx, -ly, +lz], [+lx, +ly, +lz], [-lx, +ly, +lz],
        ],
        dtype=float,
    )
    f = np.array(
        [
            [0, 1, 2], [0, 2, 3], [4, 5, 6], [4, 6, 7],
            [0, 1, 5], [0, 5, 4], [2, 3, 7], [2, 7, 6],
            [1, 2, 6], [1, 6, 5], [3, 0, 4], [3, 4, 7],
        ],
        dtype=int,
    )
    return MeshData(vertexes=v, faces=f)


def _make_nose_cone() -> "MeshData":
    """机头红色锥体：底面在 x=3.0（盒子前端），顶点在 x=4.4，指向 +X。"""
    base_x, apex_x, r, cols = 3.0, 4.4, 0.8, 16
    apex = [apex_x, 0.0, 0.0]
    base_center = [base_x, 0.0, 0.0]
    rim = []
    for i in range(cols):
        a = 2.0 * math.pi * i / cols
        rim.append([base_x, r * math.cos(a), r * math.sin(a)])
    verts = [apex, base_center] + rim
    faces = []
    for i in range(cols):
        a = 2 + i
        b = 2 + (i + 1) % cols
        faces.append([0, a, b])
        faces.append([1, b, a])
    return MeshData(vertexes=np.array(verts, dtype=float), faces=np.array(faces, dtype=int))


class Attitude3DPanel(QWidget):
    """实时 3D 姿态可视化。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._log = get_logger()
        self._last_att = None

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        if not _GL_OK:
            tip = QLabel(
                "3D 姿态未启用：缺少 pyqtgraph.opengl 或 PyOpenGL。\n"
                f"（{_GL_ERR}）\n请安装：pip install pyqtgraph PyOpenGL",
                self,
            )
            tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tip.setStyleSheet("color:#999; font-size:13px;")
            lay.addWidget(tip)
            self._view = None
            return

        # 顶部角度条（QLabel 比 GLTextItem 渲染更可靠）
        self._angle_bar = QLabel("Roll --  Pitch --  Yaw --", self)
        self._angle_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._angle_bar.setStyleSheet(
            "QLabel { background-color:#2B2B2B; color:#4FC3F7; font-size:14px;"
            " font-weight:bold; padding:5px; border-bottom:1px solid #3a3a3a; }"
        )
        lay.addWidget(self._angle_bar)

        self._view = GLViewWidget()
        self._view.setBackgroundColor("#1e1e1e")
        self._view.setCameraPosition(distance=17, elevation=35, azimuth=45)
        lay.addWidget(self._view)

        # 世界网格
        grid = GLGridItem()
        grid.setSize(20, 20)
        grid.setSpacing(1, 1)
        grid.setColor((120, 120, 120, 80))
        self._view.addItem(grid)

        # 世界参考三轴：用淡灰细线画一个固定的世界坐标参考（不喧宾夺主）
        # 机体系用 RGB 三色轴另画，二者区分：世界=灰、机体=红绿蓝
        for vec in ((6, 0, 0), (0, 6, 0), (0, 0, 6)):
            wl = GLLinePlotItem(
                pos=np.array([[0, 0, 0], list(vec)], dtype=float),
                color=(0.5, 0.5, 0.5, 0.35),
                width=1.0,
                antialias=True,
            )
            self._view.addItem(wl)

        # 机体盒子（半透明蓝）
        self._body = GLMeshItem(
            meshdata=_make_body_mesh(),
            smooth=False,
            color=(0.30, 0.60, 0.90, 0.65),
            shader="shaded",
            glOptions="translucent",
        )
        self._view.addItem(self._body)

        # 机头红色锥体（指示 +X 朝向）
        self._nose = GLMeshItem(
            meshdata=_make_nose_cone(),
            smooth=True,
            color=(0.90, 0.25, 0.25, 0.95),
            shader="shaded",
            glOptions="opaque",
        )
        self._view.addItem(self._nose)

        # 机体三轴：自绘 RGB 三色线（X红/Y绿/Z蓝），随姿态旋转
        # 用 RGB 而非 GLAxisItem 的蓝/黄/绿，保证与轴标签颜色一致、不混淆
        self._axis_len = 4.8
        self._body_axes = {
            "x": GLLinePlotItem(color=(1.0, 0.25, 0.25, 1.0), width=3.0, antialias=True),
            "y": GLLinePlotItem(color=(0.25, 0.9, 0.25, 1.0), width=3.0, antialias=True),
            "z": GLLinePlotItem(color=(0.35, 0.65, 1.0, 1.0), width=3.0, antialias=True),
        }
        for ax in self._body_axes.values():
            self._view.addItem(ax)

        # 机体系轴标签：X=机头(前)、Y=机翼(左)、Z=机顶(上)
        # 无人机坐标系（FLU）：X 前(机头/大箭头方向)、Y 左、Z 上
        # 这三个标签会随姿态一起转，让人一眼看清当前每根轴指向哪
        self._lbl_len = 5.6  # 标签放在略超机头锥(4.4)与机体轴(4.5)之外
        self._axis_labels = {}
        try:
            from PySide6.QtGui import QFont
            font = QFont()
            font.setPointSize(13)
            font.setBold(True)
            mk = lambda t, c: GLTextItem(text=t, color=c, font=font)
        except Exception:
            mk = lambda t, c: GLTextItem(text=t, color=c)
        # 颜色与机体轴线一致：X红 Y绿 Z蓝（RGB=XYZ 业界惯例，红=机头与红锥呼应）
        self._axis_labels["x"] = mk("X 机头(前)", (255, 80, 80, 255))
        self._axis_labels["y"] = mk("Y 左", (80, 230, 80, 255))
        self._axis_labels["z"] = mk("Z 上", (90, 170, 255, 255))
        for it in self._axis_labels.values():
            self._view.addItem(it)
        # 初始（水平姿态）标签 + 轴线位置，未收到数据前也能正确显示
        L0 = self._lbl_len
        self._axis_labels["x"].setData(pos=np.array([L0, 0.0, 0.0]))
        self._axis_labels["y"].setData(pos=np.array([0.0, L0, 0.0]))
        self._axis_labels["z"].setData(pos=np.array([0.0, 0.0, L0]))
        La0 = self._axis_len
        self._body_axes["x"].setData(pos=np.array([[0, 0, 0], [La0, 0, 0]], dtype=float))
        self._body_axes["y"].setData(pos=np.array([[0, 0, 0], [0, La0, 0]], dtype=float))
        self._body_axes["z"].setData(pos=np.array([[0, 0, 0], [0, 0, La0]], dtype=float))

        self._timer = QTimer(self)
        self._timer.setInterval(33)  # ~30Hz
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ---- 数据入口 ----
    @Slot(object)
    def on_attitude(self, s: object) -> None:
        self._last_att = s

    def clear(self) -> None:
        self._last_att = None

    # ---- 刷新 ----
    def _apply_attitude(self, item, roll: float, pitch: float, yaw: float) -> None:
        """按 ZYX 顺序把姿态应用到 GL item。

        使用 Transform3D（后乘）保证旋转合成正确：
        T = Rz(−yaw) · Ry(pitch) · Rx(roll)

        符号约定（与路径可视化一致）：
        - yaw 取负：IMU NED 顺时针正，pyqtgraph CCW 正，渲染端取负对齐
        - pitch / roll 保持原符号：0x04 四元数已转 NWU，
          正 roll = 右横滚（左翼上扬），正 pitch = 抬头，与 pyqtgraph 方向一致
        """
        m = Transform3D()
        m.rotate(-yaw,  0, 0, 1)
        m.rotate(pitch, 0, 1, 0)
        m.rotate(roll,  1, 0, 0)
        item.setTransform(m)

    def _rotation_matrix(self, roll: float, pitch: float, yaw: float):
        """返回与 _apply_attitude 一致的旋转矩阵 M = Rz(−yaw)·Ry(pitch)·Rx(roll)。

        用于把机体系轴向量映射到世界系，给三根轴标签定位。
        符号与 _apply_attitude 完全一致：yaw 取负，pitch/roll 保持原符号。
        """
        r = math.radians(roll)
        p = math.radians(pitch)
        y = math.radians(-yaw)
        cr, sr = math.cos(r), math.sin(r)
        cp, sp = math.cos(p), math.sin(p)
        cy, sy = math.cos(y), math.sin(y)
        rz = np.array([[cy, -sy, 0.0], [sy, cy, 0.0], [0.0, 0.0, 1.0]])
        ry = np.array([[cp, 0.0, sp], [0.0, 1.0, 0.0], [-sp, 0.0, cp]])
        rx = np.array([[1.0, 0.0, 0.0], [0.0, cr, -sr], [0.0, sr, cr]])
        return rz @ ry @ rx

    def _refresh(self) -> None:
        if self._view is None or self._last_att is None:
            return
        a = self._last_att
        self._apply_attitude(self._body, a.roll_deg, a.pitch_deg, a.yaw_deg)
        self._apply_attitude(self._nose, a.roll_deg, a.pitch_deg, a.yaw_deg)
        # 机体三轴线 + 三根轴标签都随姿态旋转到各自轴尖
        m = self._rotation_matrix(a.roll_deg, a.pitch_deg, a.yaw_deg)
        La = self._axis_len
        axis_tips = {
            "x": m @ np.array([La, 0.0, 0.0]),
            "y": m @ np.array([0.0, La, 0.0]),
            "z": m @ np.array([0.0, 0.0, La]),
        }
        for k, ln in self._body_axes.items():
            t = axis_tips[k]
            ln.setData(pos=np.array([[0.0, 0.0, 0.0], [t[0], t[1], t[2]]]))
        L = self._lbl_len
        tips = {
            "x": m @ np.array([L, 0.0, 0.0]),
            "y": m @ np.array([0.0, L, 0.0]),
            "z": m @ np.array([0.0, 0.0, L]),
        }
        for k, it in self._axis_labels.items():
            t = tips[k]
            it.setData(pos=np.array([t[0], t[1], t[2]]))
        self._angle_bar.setText(
            f"Roll {a.roll_deg:+.1f}°    Pitch {a.pitch_deg:+.1f}°    Yaw {a.yaw_deg:+.1f}°"
        )
