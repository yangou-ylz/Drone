# -*- coding: utf-8 -*-
"""凌霄无人机桌面 GUI 上位机 —— 入口。

阶段 B：串口连接栏 + 日志视图 + 三级报警 + 配置持久化 + 全局异常钩子。
命令面板留空区，由阶段 C 起填充。

运行：``python -m gui.main``  或  ``python gui/main.py``
"""
from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# 允许 "python gui/main.py" 直接运行：把仓库根加入 sys.path
_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from PySide6.QtCore import Q_ARG, QByteArray, QMetaObject, Qt, QThread, Slot  # noqa: E402
from PySide6.QtGui import QAction  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QDockWidget,
    QLabel,
    QMainWindow,
    QMessageBox,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from gui import __version__  # noqa: E402
from gui.io.protocol import Frame  # noqa: E402
from gui.io.serial_worker import SerialWorker  # noqa: E402
from gui.services.ack_matcher import AckMatcher  # noqa: E402
from gui.services.alarm_service import AlarmService  # noqa: E402
from gui.services.command_registry import REGISTRY  # noqa: E402
from gui.services.config_service import ConfigService  # noqa: E402
from gui.services.log_service import LogLevel, LogService  # noqa: E402
from gui.services.frame_recorder import FrameRecorder  # noqa: E402
from gui.services.telemetry_bus import STATUS_ERROR, STATUS_INFO, STATUS_WARN, TelemetryBus  # noqa: E402
from gui.services.telemetry_models import PathTrackerConfig  # noqa: E402
from gui.services.theme_service import DEFAULT_THEME, THEMES, apply_theme  # noqa: E402
from gui.widgets.command_panel import CommandPanel  # noqa: E402
from gui.widgets.confirm_dialog import confirm_send  # noqa: E402
from gui.widgets.connection_bar import ConnectionBar  # noqa: E402
from gui.widgets.log_view import LogView  # noqa: E402
from gui.widgets.path_visualization_widget import PathVisualizationPlaceholder  # noqa: E402
from gui.widgets.path_2d_view_widget import Path2DViewWidget  # noqa: E402
from gui.widgets.numeric_panel_dock import NumericPanelDock  # noqa: E402
from gui.widgets.flight_data_dock import FlightDataDock  # noqa: E402
from gui.widgets.frame_monitor_dock import FrameMonitorWidget  # noqa: E402
from gui.position_test.position_test_window import PositionTestWindow  # noqa: E402
import gui.commands  # noqa: F401, E402  导入即注册所有命令

# 功能 Dock 注册表：key = 配置键 / objectName 后缀；value = (菜单显示名, Dock 标题, Widget 工厂)
# P1 起挂"路径可视化（3D）"，P7 起追加 XY / XZ / YZ 三个 2D 投影视图。
# 默认参数 p=plane 绑定避免 late-binding 陷阱。
_FEATURE_DOCKS = (
    ("path_visualization", "路径可视化（3D）", "路径可视化 3D",
     lambda parent: PathVisualizationPlaceholder(parent)),
    ("path_visualization_xy", "路径可视化 · XY", "路径可视化 · XY 平面",
     lambda parent, p="XY": Path2DViewWidget(parent, plane=p)),
    ("path_visualization_xz", "路径可视化 · XZ", "路径可视化 · XZ 平面",
     lambda parent, p="XZ": Path2DViewWidget(parent, plane=p)),
    ("path_visualization_yz", "路径可视化 · YZ", "路径可视化 · YZ 平面",
     lambda parent, p="YZ": Path2DViewWidget(parent, plane=p)),
)

# 与渲染开关联动的 viz 功能 key 集合：任一开启则启用 bus.set_render_enabled
_PATH_VIZ_KEYS = (
    "path_visualization",
    "path_visualization_xy",
    "path_visualization_xz",
    "path_visualization_yz",
)

# 2D 视图：feature_key → (plane, config_key)
_PATH_VIZ_2D = {
    "path_visualization_xy": ("XY", "path_viz_2d.xy.settings"),
    "path_visualization_xz": ("XZ", "path_viz_2d.xz.settings"),
    "path_visualization_yz": ("YZ", "path_viz_2d.yz.settings"),
}


class MainWindow(QMainWindow):
    """主窗口：连接栏 + 命令面板占位 + 日志视图。"""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"凌霄无人机 上位机  v{__version__}")

        # 允许 Dock 并排嵌套 + 拒绝同区域自动 tabify（避免 3D OpenGL Dock 与 2D Dock 互相覆盖消失）
        self.setDockNestingEnabled(True)
        self.setDockOptions(
            QMainWindow.DockOption.AnimatedDocks
            | QMainWindow.DockOption.AllowNestedDocks
            | QMainWindow.DockOption.AllowTabbedDocks
        )

        # ---- 1. 服务层 ----
        self._config = ConfigService()
        self._log = LogService(log_dir=str(self._config.get("log_dir", "")))
        self._alarm = AlarmService(self._log, parent_widget=self)

        # ---- 2. 恢复窗口几何 ----
        size = self._config.get("window_size", [1200, 800])
        if isinstance(size, list) and len(size) == 2:
            self.resize(int(size[0]), int(size[1]))
        pos = self._config.get("window_pos", None)
        if isinstance(pos, list) and len(pos) == 2:
            self.move(int(pos[0]), int(pos[1]))

        # ---- 3. UI 组装 ----
        self._connection_bar = ConnectionBar(self._config, self)
        self._log_view = LogView(self._log, self)
        self._command_panel = CommandPanel(self)
        self._command_panel.set_enabled_for_link(False)
        self._command_panel.command_send_requested.connect(self._on_command_send_requested)

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        # 注：连接栏已提到最外层顶部常驻（见下方 _outer 容器），主页面内部不再放置连接栏。

        # 命令面板 / 日志区 用 QSplitter 可拖拽分隔调整高度
        # 鼠标靠近分割条会变十字光标，按住上下拖动即可
        self._splitter = QSplitter(Qt.Orientation.Vertical, central)
        self._splitter.setHandleWidth(8)
        self._splitter.setChildrenCollapsible(False)  # 禁止拖到 0 隐藏
        # 让分割条明显可见 + 鼠标悬停高亮（默认样式在某些主题下几乎看不到）
        self._splitter.setStyleSheet(
            "QSplitter::handle:vertical {"
            " background: #b0b0b0;"
            " border-top: 1px solid #888;"
            " border-bottom: 1px solid #888;"
            "}"
            "QSplitter::handle:vertical:hover { background: #3a8edb; }"
            "QSplitter::handle:vertical:pressed { background: #1f6ec1; }"
        )
        self._splitter.addWidget(self._command_panel)
        self._splitter.addWidget(self._log_view)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 5)
        # 恢复上次拖拽位置
        sizes = self._config.get("splitter_sizes", None)
        if isinstance(sizes, list) and len(sizes) == 2 and all(isinstance(s, int) for s in sizes):
            self._splitter.setSizes(sizes)
        else:
            self._splitter.setSizes([300, 500])
        layout.addWidget(self._splitter, 1)
        # IMU 测试台：中心区用 QStackedWidget 切换
        #   index 0 = 主界面(central)，index 1 = IMU 测试台(懒加载)
        self._central_stack = QStackedWidget(self)
        self._central_stack.addWidget(central)
        self._imu_test_window = None
        self._imu_data_hub = None
        self._position_test_window = None

        # ---- 顶层容器：连接栏常驻顶部 + 下方可切换的中心 stack ----
        # 把连接栏从主页面内部提到最外层，使其跨所有功能页（IMU测试台/数据帧监视等）常驻可见，
        # 无需切回主页即可随时连接/断开串口。连接栏本身排版样式保持不变，仅改变挂载位置。
        _outer = QWidget(self)
        _outer_lay = QVBoxLayout(_outer)
        _outer_lay.setContentsMargins(0, 0, 0, 0)
        _outer_lay.setSpacing(0)
        _outer_lay.addWidget(self._connection_bar)
        _outer_lay.addWidget(self._central_stack, 1)
        self.setCentralWidget(_outer)

        # ---- AckMatcher（必须在主线程，方便 QTimer）----
        self._ack = AckMatcher(self)
        self._ack.ack_matched.connect(self._on_ack_matched)
        self._ack.request_timeout.connect(self._on_ack_timeout)

        # ---- 4. 状态栏 ----
        self.setStatusBar(QStatusBar(self))
        self._sb_conn = QLabel("● 未连接")
        self._sb_conn.setStyleSheet("color: #888;")
        self._sb_rxtx = QLabel("RX: 0 B  |  TX: 0 B")
        self._sb_rxtx.setStyleSheet("color: #555;")
        # 最后一次成功收到帧的时刻（用于直观判断链路是否"哑掉"）
        self._sb_last_rx = QLabel("最后接收: --:--:--")
        self._sb_last_rx.setStyleSheet("color: #555;")
        # 状态栏"最后接收"节流：只显示到秒，无需每帧刷新（省 UI 开销）
        self._last_rx_ui_ts = 0.0
        # P5.5：传感器帧记录状态（默认隐）
        self._sb_rec = QLabel("")
        self._sb_rec.setStyleSheet("color: #c62828; font-weight: bold;")
        self._sb_rec.setVisible(False)
        self.statusBar().addPermanentWidget(self._sb_rec)
        self.statusBar().addPermanentWidget(self._sb_last_rx)
        self.statusBar().addPermanentWidget(self._sb_rxtx)
        self.statusBar().addWidget(self._sb_conn)
        self.statusBar().showMessage("就绪")
        self._rx_bytes = 0
        self._tx_bytes = 0

        # ---- 5. 菜单 + 功能 Dock（P1）+ 遥测总线（P2）----
        # 遥测总线必须在 build_menu 之前实例化（菜单回调需要它）
        # 后台积分常驻，仅 set_render_enabled 控制是否对外广播 path_updated（D3）
        self._bus = TelemetryBus(parent=self)
        self._bus.status.connect(self._on_bus_status)
        # 必须先建 Dock，再 build_menu，因为菜单要绑定 Dock 的勾选状态
        self._feature_docks: dict[str, QDockWidget] = {}
        self._feature_widgets: dict[str, QWidget] = {}
        self._feature_actions: dict[str, QAction] = {}
        self._build_feature_docks()
        # P9：数字面板 Dock（独立于 _FEATURE_DOCKS，本身即 QDockWidget）
        self._numeric_dock = NumericPanelDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._numeric_dock)
        self._numeric_dock.setVisible(False)  # 初始隐藏，根据 features.numeric_panel 恢复
        self._bus.path_updated.connect(self._numeric_dock.update_snapshot)
        self._numeric_dock.settings_changed.connect(self._on_hud_dock_settings_changed)
        # 阶段C：飞行数据面板 Dock（主界面常用数据，本身即 QDockWidget）
        self._flight_data_dock = FlightDataDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self._flight_data_dock)
        self._flight_data_dock.setVisible(False)  # 初始隐藏，根据 features.flight_data 恢复
        self._bus.flight_mode_updated.connect(self._flight_data_dock.on_flight_mode)
        self._bus.battery_updated.connect(self._flight_data_dock.on_battery)
        self._bus.height_updated.connect(self._flight_data_dock.on_height)
        self._bus.velocity_updated.connect(self._flight_data_dock.on_velocity)
        self._bus.module_status_updated.connect(self._flight_data_dock.on_module_status)
        self._bus.gen_position_updated.connect(self._flight_data_dock.on_gen_position)
        self._bus.gen_velocity_updated.connect(self._flight_data_dock.on_gen_velocity)
        self._bus.gen_distance_updated.connect(self._flight_data_dock.on_gen_distance)
        # 阶段D：数据帧监视窗口（整屏显示，点击菜单切换中央视图）
        self._frame_monitor_widget = FrameMonitorWidget(self)
        self._central_stack.addWidget(self._frame_monitor_widget)
        self._build_menu()
        # P3：路径可视化 3D Widget 订阅 PathSnapshot（仅在广播开关启后才会收到）
        viz_widget = self._feature_widgets.get("path_visualization")
        if viz_widget is not None and hasattr(viz_widget, "update_snapshot"):
            self._bus.path_updated.connect(viz_widget.update_snapshot)
        # P5：还原持久化的 3D 可视化参数 + 同步 tracker/bus；接 widget 三类信号
        if viz_widget is not None and hasattr(viz_widget, "apply_settings"):
            saved = self._config.get("path_viz.settings", {}) or {}
            if isinstance(saved, dict) and saved:
                try:
                    viz_widget.apply_settings(saved)
                except Exception as exc:
                    self._log.warn("功能", f"路径可视化参数还原失败：{exc}")
            # 用当前（默认或已还原）的 settings 一次性把 tracker/bus 拉齐
            try:
                self._apply_path_viz_settings(viz_widget.current_settings(), persist=False)
            except Exception as exc:
                self._log.warn("功能", f"路径可视化参数同步失败：{exc}")
            # P9：把 HUD 子树同步给数字面板 Dock
            try:
                cur_full = viz_widget.current_settings()
                hud_sub = cur_full.get("hud") if isinstance(cur_full, dict) else None
                if hud_sub and self._numeric_dock is not None:
                    self._numeric_dock.apply_settings(hud_sub)
            except Exception as exc:
                self._log.warn("功能", f"数字面板初始 HUD 同步失败：{exc}")
            # 用户后续在面板里改参数
            viz_widget.settings_changed.connect(self._on_path_viz_settings_changed)
            viz_widget.reset_requested.connect(self._on_path_viz_reset)
            # refresh 信号目前 widget 内部已自处理，主窗口仅记日志
            viz_widget.refresh_requested.connect(
                lambda: self._log.info("功能", "路径可视化：已刷新场景")
            )
            # P10：CSV 导出按钮
            if hasattr(viz_widget, "export_csv_requested"):
                viz_widget.export_csv_requested.connect(self._on_path_viz_export_csv)

        # ---- P7：三个 2D 投影视图共享 path_updated；各自持久化 settings ----
        for fkey, (_plane, cfg_key) in _PATH_VIZ_2D.items():
            w = self._feature_widgets.get(fkey)
            if w is None:
                continue
            if hasattr(w, "update_snapshot"):
                self._bus.path_updated.connect(w.update_snapshot)
            if hasattr(w, "apply_settings"):
                saved = self._config.get(cfg_key, {}) or {}
                if isinstance(saved, dict) and saved:
                    try:
                        w.apply_settings(saved)
                    except Exception as exc:
                        self._log.warn("功能", f"{fkey} 参数还原失败：{exc}")
            # 闭包绑定 cfg_key，避免 late-binding
            if hasattr(w, "settings_changed"):
                w.settings_changed.connect(
                    lambda s, ck=cfg_key: self._on_path_viz_2d_settings_changed(ck, s)
                )
            if hasattr(w, "reset_requested"):
                w.reset_requested.connect(self._on_path_viz_reset)

        # ---- 同步初始渲染开关：四个 viz 功能任一勾选则启动 PathTracker ----
        if self._any_path_viz_enabled():
            self._bus.set_render_enabled(True)

        # ---- P7：还原 QMainWindow Dock 几何（必须在所有 Dock 已 add 之后）----
        try:
            state_b64 = self._config.get("ui.main_window_state", "") or ""
            if isinstance(state_b64, str) and state_b64:
                ba = QByteArray.fromBase64(state_b64.encode("ascii"))
                if not ba.isEmpty():
                    self.restoreState(ba)
            # restoreState 会把 dock 显隐拉回上次值；用持久化的 features.* 再校准一次
            for k in _PATH_VIZ_KEYS:
                d = self._feature_docks.get(k)
                if d is None:
                    continue
                want = bool(self._config.get(f"features.{k}", False))
                if d.isVisible() != want:
                    d.setVisible(want)
        except Exception as exc:
            self._log.warn("系统", f"Dock 布局还原失败：{exc}")

        # ---- 6. SerialWorker 线程 ----
        # 环境变量 LINGXIAO_GUI_FAKE=1 时启用离线仿真，方便无飞机情况下端到端自测
        self._thread = QThread(self)
        if os.environ.get("LINGXIAO_GUI_FAKE", "").strip() in ("1", "true", "TRUE", "yes"):
            from gui.io.fake_worker import FakeWorker  # 延迟导入，硬件场景零开销
            self._worker = FakeWorker()
            self._log.warn("系统", "已启用 FakeWorker 离线仿真模式（LINGXIAO_GUI_FAKE=1）")
        else:
            self._worker = SerialWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.start_loop)
        self._worker.connected.connect(self._on_serial_connected)
        self._worker.disconnected.connect(self._on_serial_disconnected)
        self._worker.error.connect(self._on_serial_error)
        self._worker.frame_received.connect(self._on_frame)
        # P5.5：帧记录服务同步接同一个信号（独立路径不影响 Bus）
        self._recorder = FrameRecorder(self)
        self._worker.frame_received.connect(self._recorder.on_frame)
        self._recorder.state_changed.connect(self._on_recorder_state)
        self._recorder.frame_logged.connect(self._on_recorder_count)
        self._recorder.error.connect(lambda msg: self._alarm.warn("记录", msg))
        # 阶段D：数据帧监视（常驻订阅，面板隐藏时也不丢帧历史）
        self._worker.frame_received.connect(self._frame_monitor_widget.on_frame)
        self._worker.bytes_in.connect(self._on_bytes_in)
        self._worker.bytes_out.connect(self._on_bytes_out)
        self._thread.start()

        # ---- 7. UI 信号 ? Worker ----
        self._connection_bar.connect_requested.connect(self._req_open_port)
        self._connection_bar.disconnect_requested.connect(self._req_close_port)
        self._log_view.export_requested.connect(self._on_export_log)

        self._log.info("系统", f"GUI v{__version__} 已启动；日志：{self._log.file_path}")

    # ---- 菜单 ----
    def _build_menu(self) -> None:
        bar = self.menuBar()
        m_file = bar.addMenu("文件(&F)")

        act_export = QAction("导出日志…", self)
        act_export.triggered.connect(self._on_menu_export)
        m_file.addAction(act_export)

        act_open_log_dir = QAction("打开日志文件夹", self)
        act_open_log_dir.triggered.connect(self._on_open_log_dir)
        m_file.addAction(act_open_log_dir)

        # P5.5：传感器帧记录（JSONL）— toggle
        m_file.addSeparator()
        self._act_rec = QAction("开始传感器帧记录…", self, checkable=True)
        self._act_rec.setShortcut("Ctrl+R")
        self._act_rec.toggled.connect(self._on_menu_toggle_record)
        m_file.addAction(self._act_rec)
        # P5.5：路径可视化面板的录制按钮 → 同步菜单 QAction（单一源）
        _viz = self._feature_widgets.get("path_visualization")
        if _viz is not None and hasattr(_viz, "record_toggle_requested"):
            _viz.record_toggle_requested.connect(self._act_rec.setChecked)

        m_file.addSeparator()
        act_quit = QAction("退出(&Q)", self)
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        # ----- 视图菜单 -----
        m_view = bar.addMenu("视图(&V)")

        act_clear = QAction("清屏日志", self)
        act_clear.setShortcut("Ctrl+L")
        act_clear.triggered.connect(self._on_view_clear_log)
        m_view.addAction(act_clear)

        # 暂停 / 继续 滚动 —— 可勾选
        self._act_pause_scroll = QAction("暂停滚动", self, checkable=True)
        self._act_pause_scroll.toggled.connect(self._on_view_toggle_scroll)
        m_view.addAction(self._act_pause_scroll)

        m_view.addSeparator()

        # 主题子菜单（互斥单选）
        m_theme = m_view.addMenu("主题")
        from PySide6.QtGui import QActionGroup
        self._theme_group = QActionGroup(self)
        self._theme_group.setExclusive(True)
        cur_theme = str(self._config.get("ui.theme", DEFAULT_THEME))
        if cur_theme not in THEMES:
            cur_theme = DEFAULT_THEME
        for tname, label in (("dark", "暗色"), ("light", "浅色")):
            act = QAction(label, self, checkable=True)
            act.setData(tname)
            act.setChecked(tname == cur_theme)
            act.triggered.connect(self._on_view_change_theme)
            self._theme_group.addAction(act)
            m_theme.addAction(act)

        # ----- 功能（P1：路径可视化 Dock 显隐入口）-----
        m_feature = bar.addMenu("功能(&U)")
        for key, menu_label, _dock_title, _factory in _FEATURE_DOCKS:
            dock = self._feature_docks.get(key)
            if dock is None:
                continue
            act = QAction(menu_label, self, checkable=True)
            # 恢复持久化的勾选状态
            visible = bool(self._config.get(f"features.{key}", False))
            act.setChecked(visible)
            dock.setVisible(visible)
            # 勾选 ? Dock 显隐；同时写配置
            act.toggled.connect(
                lambda checked, k=key, d=dock: self._on_feature_toggled(k, d, checked)
            )
            # Dock 自身被关闭按钮关闭时，菜单同步取消勾选
            dock.visibilityChanged.connect(
                lambda visible_now, a=act: a.setChecked(visible_now)
            )
            m_feature.addAction(act)
            self._feature_actions[key] = act

        # P9：数字面板 Dock（独立于 _FEATURE_DOCKS）
        if getattr(self, "_numeric_dock", None) is not None:
            act_np = QAction("数字面板", self, checkable=True)
            np_visible = bool(self._config.get("features.numeric_panel", False))
            act_np.setChecked(np_visible)
            self._numeric_dock.setVisible(np_visible)
            act_np.toggled.connect(self._on_numeric_panel_toggled)
            self._numeric_dock.visibilityChanged.connect(
                lambda v, a=act_np: a.setChecked(v)
            )
            m_feature.addAction(act_np)
            self._feature_actions["numeric_panel"] = act_np

        # 阶段C：飞行数据面板 Dock（独立于 _FEATURE_DOCKS）
        if getattr(self, "_flight_data_dock", None) is not None:
            act_fd = QAction("飞行数据面板", self, checkable=True)
            fd_visible = bool(self._config.get("features.flight_data", False))
            act_fd.setChecked(fd_visible)
            self._flight_data_dock.setVisible(fd_visible)
            act_fd.toggled.connect(self._on_flight_data_toggled)
            self._flight_data_dock.visibilityChanged.connect(
                lambda v, a=act_fd: a.setChecked(v)
            )
            m_feature.addAction(act_fd)
            self._feature_actions["flight_data"] = act_fd

        # 阶段D：数据帧监视（整屏中央视图，默认隐藏）
        if getattr(self, "_frame_monitor_widget", None) is not None:
            act_fm = QAction("数据帧监视", self, checkable=True)
            act_fm.setChecked(False)  # 不默认显示
            act_fm.toggled.connect(self._on_frame_monitor_toggled)
            m_feature.addAction(act_fm)
            self._feature_actions["frame_monitor"] = act_fm

        # 树莓派位置测试（整屏中央视图，默认隐藏）
        self._act_position_test = QAction("位置测试", self, checkable=True)
        self._act_position_test.toggled.connect(self._on_toggle_position_test)
        m_feature.addAction(self._act_position_test)
        self._feature_actions["position_test"] = self._act_position_test

        # ----- IMU 测试台入口 -----
        m_feature.addSeparator()
        self._act_imu_test = QAction("IMU 测试台", self, checkable=True)
        self._act_imu_test.toggled.connect(self._on_toggle_imu_test)
        m_feature.addAction(self._act_imu_test)

        # ----- 帮助 -----
        m_help = bar.addMenu("帮助(&H)")
        act_about = QAction("关于", self)
        act_about.triggered.connect(self._on_about)
        m_help.addAction(act_about)

    def _on_toggle_imu_test(self, checked: bool) -> None:
        """切换主界面 / IMU 测试台（懒加载）。"""
        if checked:
            # 互斥：关闭数据帧监视
            act_fm = self._feature_actions.get("frame_monitor")
            if act_fm and act_fm.isChecked():
                act_fm.blockSignals(True)
                act_fm.setChecked(False)
                act_fm.blockSignals(False)
                self._config.set("features.frame_monitor", False)
            # 互斥：关闭位置测试
            act_pos = self._feature_actions.get("position_test")
            if act_pos and act_pos.isChecked():
                act_pos.blockSignals(True)
                act_pos.setChecked(False)
                act_pos.blockSignals(False)
            if self._position_test_window is not None:
                self._position_test_window.set_active(False)
            if self._imu_test_window is None:
                from gui.imu_test.data_hub import ImuDataHub
                from gui.imu_test.imu_test_window import ImuTestWindow
                self._imu_data_hub = ImuDataHub(self)
                self._worker.frame_received.connect(self._imu_data_hub.on_frame)
                self._imu_test_window = ImuTestWindow(
                    self._imu_data_hub, self, send_frame_fn=self._send_raw_frame
                )
                self._central_stack.addWidget(self._imu_test_window)
            self._central_stack.setCurrentWidget(self._imu_test_window)
        else:
            self._central_stack.setCurrentIndex(0)

    def _on_toggle_position_test(self, checked: bool) -> None:
        """切换主界面 / 位置测试页（树莓派0xF5镜像0xF6，懒加载）。"""
        if checked:
            # 互斥：关闭数据帧监视
            act_fm = self._feature_actions.get("frame_monitor")
            if act_fm and act_fm.isChecked():
                act_fm.blockSignals(True)
                act_fm.setChecked(False)
                act_fm.blockSignals(False)
                self._config.set("features.frame_monitor", False)
            # 互斥：关闭 IMU 测试台
            if getattr(self, "_act_imu_test", None) and self._act_imu_test.isChecked():
                self._act_imu_test.blockSignals(True)
                self._act_imu_test.setChecked(False)
                self._act_imu_test.blockSignals(False)
            if self._position_test_window is None:
                self._position_test_window = PositionTestWindow(self)
                self._worker.frame_received.connect(self._position_test_window.on_frame)
                self._central_stack.addWidget(self._position_test_window)
            self._position_test_window.set_link_connected(self._connection_bar.is_connected)
            self._position_test_window.set_active(True)
            self._central_stack.setCurrentWidget(self._position_test_window)
            self._log.info("功能", "位置测试 已开启")
        else:
            if self._position_test_window is not None:
                self._position_test_window.set_active(False)
            if self._central_stack.currentWidget() is self._position_test_window:
                self._central_stack.setCurrentIndex(0)
            self._log.info("功能", "位置测试 已关闭")

    def _send_raw_frame(self, frame: bytes) -> bool:
        """发送整帧原始字节（供 IMU 测试台设备校准使用）。

        校验串口连接后跨线程入队；未连接返回 False（不发送）。
        """
        if not self._connection_bar.is_connected:
            self._alarm.warn("校准", "串口未连接，发送已取消")
            return False
        QMetaObject.invokeMethod(
            self._worker, "send_bytes", Qt.ConnectionType.QueuedConnection,
            Q_ARG(QByteArray, QByteArray(bytes(frame))),
        )
        return True


    def _build_feature_docks(self) -> None:
        """创建所有功能 Dock（默认隐藏，由菜单勾选驱动显示）。

        使用 splitDockWidget 让 Dock 在右侧并排显示，避免 Qt 把多个 Dock 自动 tabify
        造成 3D OpenGL Dock 与 2D Dock 互相覆盖消失（Bug 3）。
        """
        prev_dock: Optional[QDockWidget] = None
        for key, _menu_label, dock_title, factory in _FEATURE_DOCKS:
            dock = QDockWidget(dock_title, self)
            dock.setObjectName(f"FeatureDock_{key}")
            dock.setAllowedAreas(
                Qt.DockWidgetArea.LeftDockWidgetArea
                | Qt.DockWidgetArea.RightDockWidgetArea
                | Qt.DockWidgetArea.BottomDockWidgetArea
            )
            dock.setFeatures(
                QDockWidget.DockWidgetFeature.DockWidgetClosable
                | QDockWidget.DockWidgetFeature.DockWidgetMovable
                | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            )
            widget = factory(dock)
            dock.setWidget(widget)
            self._feature_widgets[key] = widget
            dock.setVisible(False)  # 初始隐藏，菜单勾选时再显示
            if prev_dock is None:
                self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, dock)
            else:
                # 与上一个 dock 并排（水平拆分），避免被 tabify 导致看不到
                self.splitDockWidget(prev_dock, dock, Qt.Orientation.Horizontal)
            self._feature_docks[key] = dock
            prev_dock = dock

    def _on_feature_toggled(self, key: str, dock: QDockWidget, checked: bool) -> None:
        """菜单勾选变化：同步显隐 Dock 并写入配置（D2 / D9 仅状态变化时一次日志）。"""
        if dock.isVisible() != checked:
            dock.setVisible(checked)
        self._config.set(f"features.{key}", bool(checked))
        self._log.info("功能", f"{key} {'已开启' if checked else '已关闭'}")
        # 路径可视化（3D + 三个 2D 投影）：任一开启 → 启动 PathTracker 广播
        # D3：积分常驻，仅控制广播；全关时停广播节省 CPU
        if key in _PATH_VIZ_KEYS:
            self._bus.set_render_enabled(self._any_path_viz_enabled())

    def _on_numeric_panel_toggled(self, checked: bool) -> None:
        """P9：数字面板 Dock 菜单切换。"""
        if self._numeric_dock is None:
            return
        if self._numeric_dock.isVisible() != checked:
            self._numeric_dock.setVisible(checked)
        self._config.set("features.numeric_panel", bool(checked))
        self._log.info("功能", f"numeric_panel {'已开启' if checked else '已关闭'}")

    def _on_flight_data_toggled(self, checked: bool) -> None:
        """阶段C：飞行数据面板 Dock 菜单切换。"""
        if getattr(self, "_flight_data_dock", None) is None:
            return
        if self._flight_data_dock.isVisible() != checked:
            self._flight_data_dock.setVisible(checked)
        self._config.set("features.flight_data", bool(checked))
        self._log.info("功能", f"flight_data {'已开启' if checked else '已关闭'}")

    def _on_frame_monitor_toggled(self, checked: bool) -> None:
        """阶段D：数据帧监视菜单切换（整屏显示）。"""
        if getattr(self, "_frame_monitor_widget", None) is None:
            return
        self._config.set("features.frame_monitor", bool(checked))
        if checked:
            # 互斥：关闭 IMU 测试台
            if getattr(self, "_act_imu_test", None) and self._act_imu_test.isChecked():
                self._act_imu_test.blockSignals(True)
                self._act_imu_test.setChecked(False)
                self._act_imu_test.blockSignals(False)
            # 互斥：关闭位置测试
            act_pos = self._feature_actions.get("position_test")
            if act_pos and act_pos.isChecked():
                act_pos.blockSignals(True)
                act_pos.setChecked(False)
                act_pos.blockSignals(False)
            if self._position_test_window is not None:
                self._position_test_window.set_active(False)
            self._central_stack.setCurrentWidget(self._frame_monitor_widget)
            self._log.info("功能", "数据帧监视 已开启")
        else:
            if self._central_stack.currentWidget() is self._frame_monitor_widget:
                self._central_stack.setCurrentIndex(0)
            self._log.info("功能", "数据帧监视 已关闭")

    def _any_path_viz_enabled(self) -> bool:
        """四个路径可视化 feature 是否至少一个已勾选（持久化值）。"""
        for k in _PATH_VIZ_KEYS:
            if bool(self._config.get(f"features.{k}", False)):
                return True
        return False

    # ---- P5：路径可视化参数 → tracker / bus / 持久化 ----
    def _apply_path_viz_settings(self, settings: dict, persist: bool) -> None:
        """把 widget 当前 settings 同步到 PathTracker / TelemetryBus；可选写盘。

        - path.trail_seconds / path.max_points → PathTrackerConfig
        - render.fps → bus.set_render_fps
        其余参数仅影响 widget 自身渲染，已在 widget 内部生效。
        """
        if not isinstance(settings, dict):
            return
        path_s = settings.get("path") or {}
        render_s = settings.get("render") or {}
        try:
            cfg = PathTrackerConfig(
                trail_seconds=float(path_s.get("trail_seconds", 20.0)),
                max_points=int(path_s.get("max_points", 1800)),
            )
            self._bus.update_config(cfg)
        except Exception as exc:
            self._log.warn("功能", f"路径可视化：PathTrackerConfig 同步失败 {exc}")
        try:
            self._bus.set_render_fps(int(render_s.get("fps", 30)))
        except Exception as exc:
            self._log.warn("功能", f"路径可视化：render fps 同步失败 {exc}")
        if persist:
            self._config.set("path_viz.settings", settings)

    @Slot(dict)
    def _on_path_viz_settings_changed(self, settings: dict) -> None:
        self._apply_path_viz_settings(settings, persist=True)
        # P9：HUD 子树同时推送给数字面板 Dock（避免设置面板与 Dock 不同步）
        hud_sub = (settings or {}).get("hud") if isinstance(settings, dict) else None
        if hud_sub and hasattr(self, "_numeric_dock") and self._numeric_dock is not None:
            try:
                self._numeric_dock.apply_settings(hud_sub)
            except Exception as exc:
                self._log.warn("功能", f"数字面板 HUD 同步失败：{exc}")

    def _on_path_viz_2d_settings_changed(self, cfg_key: str, settings: dict) -> None:
        """2D 视图设置变化：写盘 + 若包含 path.trail_seconds，则同步到 PathTracker
        并广播到 3D widget 及其它 2D widget 的 path.trail_seconds 显示。"""
        if not isinstance(settings, dict):
            return
        self._config.set(cfg_key, settings)
        # 只关心 trail_seconds 的跨视图同步
        try:
            new_ts = float((settings.get("path") or {}).get("trail_seconds", 0.0))
        except Exception:
            new_ts = 0.0
        if new_ts <= 0.0:
            return
        # 1) 写入主 path_viz.settings 并 push 到 PathTracker
        main_s = self._config.get("path_viz.settings", {}) or {}
        if not isinstance(main_s, dict):
            main_s = {}
        main_s.setdefault("path", {})["trail_seconds"] = new_ts
        self._apply_path_viz_settings(main_s, persist=True)
        # 2) 同步到 3D widget 的设置面板（不触发回环：apply_settings 不回发信号）
        viz3d = self._feature_widgets.get("path_visualization")
        if viz3d is not None and hasattr(viz3d, "apply_settings"):
            try:
                viz3d.apply_settings({"path": {"trail_seconds": new_ts}})
            except Exception:
                pass
        # 3) 同步到其它 2D widget
        for fkey, (_plane, _ck) in _PATH_VIZ_2D.items():
            if _ck == cfg_key:
                continue
            other = self._feature_widgets.get(fkey)
            if other is not None and hasattr(other, "apply_settings"):
                try:
                    other.apply_settings({"path": {"trail_seconds": new_ts}})
                except Exception:
                    pass

    @Slot(dict)
    def _on_hud_dock_settings_changed(self, hud_settings: dict) -> None:
        """P9：数字面板 Dock 改了 HUD 可见性 → 同步给 3D widget 叠加层 + 持久化。"""
        if not isinstance(hud_settings, dict) or not hud_settings:
            return
        viz_widget = self._feature_widgets.get("path_visualization")
        if viz_widget is not None and hasattr(viz_widget, "apply_settings"):
            try:
                viz_widget.apply_settings({"hud": hud_settings})
            except Exception as exc:
                self._log.warn("功能", f"HUD 叠加层同步失败：{exc}")
        # 插入最新快照（包括更后的 hud）以便写盘
        if viz_widget is not None and hasattr(viz_widget, "current_settings"):
            try:
                self._apply_path_viz_settings(viz_widget.current_settings(), persist=True)
            except Exception:
                pass

    @Slot()
    def _on_path_viz_reset(self) -> None:
        self._bus.reset_path()
        self._log.info("功能", "路径可视化:用户触发重置")

    @Slot()
    def _on_path_viz_export_csv(self) -> None:
        """P10：导出当前 3D 轨迹为 CSV。"""
        viz = self._feature_widgets.get("path_visualization")
        if viz is None or not hasattr(viz, "export_path_csv"):
            return
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        default_name = "lingxiao_path_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".csv"
        path, _ = QFileDialog.getSaveFileName(self, "导出轨迹 CSV", default_name, "CSV 文件 (*.csv)")
        if not path:
            return
        try:
            n = int(viz.export_path_csv(path))
            self._log.info("功能", f"轨迹已导出：{n} 点 → {path}")
            QMessageBox.information(self, "导出完成", f"已写入 {n} 个轨迹点：\n{path}")
        except Exception as exc:
            self._log.warn("功能", f"轨迹导出失败：{exc!r}")
            QMessageBox.warning(self, "导出失败", str(exc))

    # ---- P5.5：传感器帧记录 ----
    @Slot(bool)
    def _on_menu_toggle_record(self, checked: bool) -> None:
        """文件菜单"开始/停止记录"toggle 回调。"""
        if checked:
            # 弹出保存对话框
            from PySide6.QtWidgets import QFileDialog
            default_dir = str(Path(self._log.file_path).parent) if hasattr(self._log, "file_path") else ""
            default_name = "lingxiao_frames_" + datetime.now().strftime("%Y%m%d_%H%M%S") + ".jsonl"
            from pathlib import Path as _P
            default_path = str(_P(default_dir) / default_name) if default_dir else default_name
            path, _ = QFileDialog.getSaveFileName(
                self, "保存传感器帧记录", default_path, "JSON Lines (*.jsonl);;All Files (*)"
            )
            if not path:
                # 用户取消 → 复原勾选
                self._act_rec.blockSignals(True)
                self._act_rec.setChecked(False)
                self._act_rec.blockSignals(False)
                return
            if not self._recorder.start(path):
                self._act_rec.blockSignals(True)
                self._act_rec.setChecked(False)
                self._act_rec.blockSignals(False)
                return
        else:
            self._recorder.stop()

    @Slot(bool, str)
    def _on_recorder_state(self, active: bool, path: str) -> None:
        """记录服务状态变化 → 同步状态栏、菜单勾选、widget 按钮、日志。"""
        # 菜单勾选保持同步（避免外部触发 stop 时勾选错位）
        if self._act_rec.isChecked() != active:
            self._act_rec.blockSignals(True)
            self._act_rec.setChecked(active)
            self._act_rec.blockSignals(False)
        # widget 按钮同步（若 widget 提供了 set_recording_state 方法）
        viz = self._feature_widgets.get("path_visualization")
        if viz is not None and hasattr(viz, "set_recording_state"):
            try:
                viz.set_recording_state(active, path, self._recorder.count)
            except Exception:
                pass
        # 状态栏
        if active:
            self._sb_rec.setText("●REC 0 帧")
            self._sb_rec.setVisible(True)
            self._log.info("记录", f"开始记录:{path}")
        else:
            self._sb_rec.setText("")
            self._sb_rec.setVisible(False)
            if path:
                self._log.info(
                    "记录", f"停止记录:{path}（共 {self._recorder.count} 帧）"
                )

    @Slot(int)
    def _on_recorder_count(self, n: int) -> None:
        # 节流：每 20 帧或末位为 0 时刷新一次状态栏
        if n % 20 != 0:
            return
        self._sb_rec.setText(f"●REC {n} 帧")
        # 同步 widget 面板的"记录中 N 帧"标签
        viz = self._feature_widgets.get("path_visualization")
        if viz is not None and hasattr(viz, "set_recording_state"):
            try:
                viz.set_recording_state(True, self._recorder.path or "", n)
            except Exception:
                pass

    # ---- 连接/断开 ----
    def _req_open_port(self, port_name: str) -> None:
        if not port_name:
            self._alarm.warn("串口", "未输入串口名")
            return
        self._log.info("串口", f"请求连接 {port_name}")
        QMetaObject.invokeMethod(
            self._worker, "open_port", Qt.ConnectionType.QueuedConnection,
            Q_ARG(str, port_name),
        )

    def _req_close_port(self) -> None:
        self._log.info("串口", "请求断开")
        QMetaObject.invokeMethod(
            self._worker, "close_port", Qt.ConnectionType.QueuedConnection,
        )

    # ---- Worker 信号回调 ----
    @Slot(str)
    def _on_serial_connected(self, port_name: str) -> None:
        self._connection_bar.set_connected(port_name)
        self._sb_conn.setText(f"● 已连接 {port_name}")
        self._sb_conn.setStyleSheet("color: #2E7D32; font-weight: bold;")
        self._command_panel.set_enabled_for_link(True)
        if self._position_test_window is not None:
            self._position_test_window.set_link_connected(True)
        self._alarm.info("串口", f"已连接到 {port_name}")

    @Slot(str)
    def _on_serial_disconnected(self, reason: str) -> None:
        self._connection_bar.set_disconnected(reason)
        self._sb_conn.setText("● 未连接")
        self._sb_conn.setStyleSheet("color: #888;")
        self._command_panel.set_enabled_for_link(False)
        if self._position_test_window is not None:
            self._position_test_window.set_link_connected(False)
        # 断开时取消所有挂起，避免无意义超时报警
        if self._ack.pending_count:
            self._log.info("回执", f"串口断开，取消 {self._ack.pending_count} 条挂起请求")
            self._ack.cancel_all()
        self._log.info("串口", f"已断开：{reason}")

    @Slot(str)
    def _on_serial_error(self, msg: str) -> None:
        self._connection_bar.set_error(msg)
        self._command_panel.set_enabled_for_link(False)
        self._alarm.error("串口", msg)

    @Slot(int)
    def _on_bytes_in(self, n: int) -> None:
        self._rx_bytes += n
        self._sb_rxtx.setText(f"RX: {self._rx_bytes} B  |  TX: {self._tx_bytes} B")

    @Slot(int)
    def _on_bytes_out(self, n: int) -> None:
        self._tx_bytes += n
        self._sb_rxtx.setText(f"RX: {self._rx_bytes} B  |  TX: {self._tx_bytes} B")

    @Slot(object)
    def _on_frame(self, fr: Frame) -> None:
        """处理入站帧。阶段 B 只显示 0xA0 字符串帧。"""
        # 状态栏"最后接收"节流：每秒最多刷一次（只精确到秒，逐帧刷新是浪费）
        import time as _time
        mono = _time.monotonic()
        if mono - self._last_rx_ui_ts >= 1.0:
            self._last_rx_ui_ts = mono
            from datetime import datetime
            self._sb_last_rx.setText("最后接收: " + datetime.now().strftime("%H:%M:%S"))
        # 遥测总线：所有帧都喂一份；积分仅在路径可视化开启时进行（D3）
        self._bus.feed_frame(fr)
        try:
            cs = fr.color_str()
        except Exception as exc:
            self._alarm.warn("解析", f"帧 0x{fr.cmd:02X} 解析异常：{exc}")
            return
        if cs is None:
            # 非 0xA0 字符串帧：不逐帧写 debug 日志（100Hz 下纯浪费），
            # 数据帧已在"数据帧监视"里可视化
            return
        color, text = cs
        color_tag = {0: "黑", 1: "红", 2: "绿"}.get(color, str(color))
        # 红字默认归 WARN，命令层（阶段 D 的 UNK 等）可再升级到 ERROR
        level = LogLevel.WARN if color == 1 else LogLevel.INFO
        self._log.log(level, "回执", f"[A0 {color_tag}] {text}")
        # 同步交给 AckMatcher 做发送-回执配对
        try:
            self._ack.handle_text(text)
        except Exception as exc:
            self._alarm.warn("回执", f"AckMatcher 处理异常：{exc}")

    @Slot(int, str)
    def _on_bus_status(self, level: int, text: str) -> None:
        """TelemetryBus 状态汇报 → 日志（warn/error 用红字告警）。"""
        if level >= STATUS_ERROR:
            self._alarm.error("遥测", text)
        elif level >= STATUS_WARN:
            self._alarm.warn("遥测", text)
        else:
            self._log.info("遥测", text)

    # ---- 命令发送 / 回执 ----
    def _on_command_send_requested(self, cmd_id: int, params: dict) -> None:
        """CommandPanel 转发的发送请求：弹确认→组帧→入队→登记 AckMatcher。"""
        cmd = REGISTRY.get(cmd_id)
        if cmd is None:
            self._alarm.error("命令", f"未注册的命令 0x{cmd_id:02X}")
            return
        if not self._connection_bar.is_connected:
            self._alarm.warn("命令", f"{cmd.name}：串口未连接，发送已取消")
            return

        # 1. 敏感命令弹确认（强制勾选复选框）
        if cmd.requires_confirm:
            desc_text = cmd.describe_params(params)
            if not confirm_send(self, cmd.name, desc_text):
                self._log.info("命令", f"已取消：{cmd.name} ({desc_text})")
                return

        # 2. 组帧（捕获参数校验异常）
        try:
            frame = cmd.build_frame(params)
        except Exception as exc:
            self._alarm.error("命令", f"{cmd.name} 组帧失败：{exc}")
            return

        desc = cmd.describe_params(params)
        # 3. 登记 AckMatcher（先登记再发送，避免极快回执先到导致漏匹配）
        token = self._ack.track(cmd, desc)

        # 面板立即进入等待态（黄灯）
        self._command_panel.set_ack_state(
            cmd.cmd_id,
            "waiting",
            f"#{token} 等待回执…  {desc}",
        )

        # 4. 入队发送（跨线程）
        # 注意：Python 原生 bytes 不是注册的 QMetaType，跨线程必须用 QByteArray 包一层
        QMetaObject.invokeMethod(
            self._worker, "send_bytes", Qt.ConnectionType.QueuedConnection,
            Q_ARG(QByteArray, QByteArray(frame)),
        )
        self._log.info("发送", f"#{token} {cmd.name}  {desc}  ({len(frame)}B)")

    @Slot(int, int, bool, int, str, str)
    def _on_ack_matched(self, token: int, cmd_id: int, ok: bool,
                        level_int: int, message: str, description: str) -> None:
        cmd = REGISTRY.get(cmd_id)
        cname = cmd.name if cmd else f"0x{cmd_id:02X}"
        level = LogLevel(level_int)
        text = f"#{token} {cname} 回执：{message}  (原发: {description})"
        self._log.log(level, "回执", text)
        # 面板三态：ERROR=fail红 / WARN=warn橙 / INFO=ok绿
        if level == LogLevel.ERROR:
            panel_state = "fail"
        elif level == LogLevel.WARN:
            panel_state = "warn"
        else:
            panel_state = "ok"
        self._command_panel.set_ack_state(cmd_id, panel_state, f"#{token} {message}")
        # ERROR 级回执升级到报警弹窗
        if level == LogLevel.ERROR:
            self._alarm.error("回执", text)

    @Slot(int, int, str)
    def _on_ack_timeout(self, token: int, cmd_id: int, description: str) -> None:
        cmd = REGISTRY.get(cmd_id)
        cname = cmd.name if cmd else f"0x{cmd_id:02X}"
        timeout_ms = cmd.ack_timeout_ms if cmd else 0
        # 面板走超时红灯
        self._command_panel.set_ack_state(
            cmd_id,
            "timeout",
            f"#{token} 超时（{timeout_ms}ms），请检查链路或手动重发",
        )
        # 不自动重发（用户规则），仅警告
        self._alarm.warn(
            "回执",
            f"#{token} {cname} 回执超时（{timeout_ms}ms），"
            f"请检查链路或手动点「重发上次」  [{description}]",
        )

    # ---- 菜单回调 ----
    def _on_menu_export(self) -> None:
        # 复用 LogView 的导出对话框
        self._log_view._on_export()

    def _on_export_log(self, path: str) -> None:
        ok = self._log.export_to(path)
        if ok:
            self._log.info("系统", f"日志已导出到 {path}")
        else:
            self._alarm.error("系统", f"日志导出失败：{path}")

    def _on_open_log_dir(self) -> None:
        path = self._log.file_path
        if not path:
            self._alarm.warn("系统", "当前没有可打开的日志文件")
            return
        folder = os.path.dirname(path)
        try:
            if sys.platform == "win32":
                os.startfile(folder)  # type: ignore[attr-defined]
            else:
                from PySide6.QtGui import QDesktopServices
                from PySide6.QtCore import QUrl
                QDesktopServices.openUrl(QUrl.fromLocalFile(folder))
        except Exception as exc:
            self._alarm.error("系统", f"打开日志文件夹失败：{exc}")

    def _on_view_clear_log(self) -> None:
        self._log_view.clear_display()

    def _on_view_toggle_scroll(self, paused: bool) -> None:
        self._log_view.set_paused(paused)

    def _on_view_change_theme(self) -> None:
        act = self.sender()
        if act is None:
            return
        name = act.data()
        if not isinstance(name, str):
            return
        applied = apply_theme(name)
        self._config.set("ui.theme", applied)
        self._log.info("系统", f"已切换主题：{applied}")

    def _on_about(self) -> None:
        QMessageBox.information(
            self, "关于",
            f"凌霄无人机桌面上位机\nv{__version__}\n\n"
            "项目：凌霄 FC + 匿名数传 + 自定义上行帧 (0xF1/0xF2)\n"
            "完整长期计划见 /memories/session/plan.md",
        )

    # ---- 关闭 ----
    def closeEvent(self, event) -> None:  # noqa: N802
        try:
            # 1. 保存窗口几何 + 分割条位置 + Dock 布局（P7）
            updates = dict(
                window_size=[self.width(), self.height()],
                window_pos=[self.x(), self.y()],
                splitter_sizes=list(self._splitter.sizes()),
            )
            try:
                state_ba = self.saveState()
                updates["ui.main_window_state"] = bytes(
                    state_ba.toBase64()
                ).decode("ascii")
            except Exception as exc:
                self._log.warn("系统", f"保存 Dock 布局失败：{exc}")
            self._config.update(**updates)
            # 2. 停 worker
            self._worker.stop()
            QMetaObject.invokeMethod(
                self._worker, "close_port", Qt.ConnectionType.QueuedConnection,
            )
            self._thread.quit()
            if not self._thread.wait(2000):
                self._thread.terminate()
                self._thread.wait(500)
            # 3. 关日志
            self._log.close()
        finally:
            super().closeEvent(event)


# ---------------- 全局异常钩子 ----------------

def _install_excepthook(alarm: AlarmService) -> None:
    """把主线程未捕获异常导向 AlarmService.error，避免静默崩溃。"""
    def _hook(exc_type, exc_value, exc_tb):
        text = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        print(text, file=sys.stderr)
        try:
            alarm.error("未捕获异常", str(exc_value) or exc_type.__name__)
        except Exception:
            pass
    sys.excepthook = _hook


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("凌霄无人机上位机")
    # 主题：先建临时 ConfigService 读 ui.theme，再 apply，避免窗口构建时一闪白底
    try:
        _cfg = ConfigService()
        apply_theme(str(_cfg.get("ui.theme", DEFAULT_THEME)))
    except Exception:
        apply_theme(DEFAULT_THEME)
    win = MainWindow()
    _install_excepthook(win._alarm)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
