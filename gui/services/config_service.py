# -*- coding: utf-8 -*-
"""ConfigService —— 运行时配置持久化（JSON）。

存储内容：上次选中的串口名、主窗口尺寸/位置、日志目录、日志等级过滤等。
文件位置：``<repo>/gui/config.json``，与代码同目录，方便用户查看与备份。

设计：
- 读写均加 try/except，损坏文件不致命，回退默认值；
- 提供 :meth:`get` / :meth:`set` 简单接口，未来扩展不影响调用方；
- 同步写入（每次 set 触发 save），日志量小不会成为瓶颈。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any

# 默认配置
_DEFAULTS: dict[str, Any] = {
    "last_port": "",                # 上次连接的串口名
    "window_size": [1200, 800],
    "window_pos": None,             # [x, y]，None=居中
    "log_dir": "",                  # 留空 = <repo>/gui/logs/
    "log_filter_level": "INFO",     # 日志最低显示等级
    # ---- 功能 Dock 显隐持久化（P1 引入；P7 扩展到 4 个视图）----
    # key 命名约定：features.<feature_key>；与 _FEATURE_DOCKS 中的 key 对齐
    "features.path_visualization": False,
    "features.path_visualization_xy": False,
    "features.path_visualization_xz": False,
    "features.path_visualization_yz": False,
    # ---- P5：路径可视化完整参数（3D 视图）----
    # 整张 settings 树以 dict 形式持久化；启动时 widget.apply_settings(...) 还原
    "path_viz.settings": {},
    # ---- P7：三个 2D 投影视图各自的 settings ----
    "path_viz_2d.xy.settings": {},
    "path_viz_2d.xz.settings": {},
    "path_viz_2d.yz.settings": {},
    # ---- P7：QMainWindow 整体 Dock 布局（saveState/restoreState 的 base64 字节）----
    "ui.main_window_state": "",
    # ---- P9：HUD 设置（叠加层 + 数字面板共享同一字段集合，三方同步）----
    "path_viz.hud.settings": {},
    # ---- P9：独立的数字面板 Dock 显隐持久化 ----
    "features.numeric_panel": False,
    # ---- 阶段C：飞行数据面板 Dock 显隐持久化 ----
    "features.flight_data": False,
    # ---- 阶段D：数据帧监视 Dock 显隐持久化 ----
    "features.frame_monitor": False,
}

_CONFIG_PATH = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, "config.json")
)


class ConfigService:
    """轻量配置存储，无 Qt 依赖，方便单元测试。"""

    def __init__(self, path: str = _CONFIG_PATH) -> None:
        self._path = path
        self._data: dict[str, Any] = dict(_DEFAULTS)
        self._load()

    # ---- 公共接口 ----
    def get(self, key: str, default: Any = None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in _DEFAULTS:
            return _DEFAULTS[key]
        return default

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value
        self._save()

    def update(self, **kwargs: Any) -> None:
        """批量更新后只写一次盘。"""
        self._data.update(kwargs)
        self._save()

    @property
    def path(self) -> str:
        return self._path

    # ---- 内部 ----
    def _load(self) -> None:
        if not os.path.isfile(self._path):
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                # 只采纳已知 key，避免脏数据污染
                for k, v in loaded.items():
                    if k in _DEFAULTS:
                        self._data[k] = v
        except Exception as exc:
            # 损坏配置不致命，打到 stderr，让 GUI 启动继续走
            print(f"[ConfigService] 读取配置失败，回退默认值：{exc}", file=sys.stderr)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"[ConfigService] 写入配置失败：{exc}", file=sys.stderr)
