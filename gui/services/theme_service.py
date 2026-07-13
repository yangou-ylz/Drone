# -*- coding: utf-8 -*-
"""主题服务 —— 浅色 / 暗色 QSS 切换。

设计：
- 全局只暴露 :func:`apply_theme` 和 :data:`THEMES`；
- QSS 字符串以模块级常量内联（避免外部资源依赖）；
- 主题选择由 :class:`gui.services.config_service.ConfigService` 持久化，
  键名 ``ui.theme``，取值 ``"light"`` / ``"dark"``，默认 ``"dark"``；
- 切换时调用 ``QApplication.instance().setStyleSheet(qss)``，
  全局所有 Qt 控件即时刷新。

注意：本服务**不接触** :class:`gui.widgets.log_view.LogView` 内部 QTextEdit
的背景色（暗背景对长时间盯日志最舒适，浅色主题也保留暗色日志区）。
"""
from __future__ import annotations

import os
from typing import Iterable

from PySide6.QtWidgets import QApplication


# SVG 箭头资源路径（运行时注入 QSS）
_ASSET_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, "assets"))


def _asset_url(name: str) -> str:
    # QSS 里统一用正斜杠，Qt 能直接识别绝对路径
    return os.path.join(_ASSET_DIR, name).replace("\\", "/")


# 浅色主题：Fusion 风格 + 轻量改色（按钮/输入框圆角与边距）
_LIGHT_QSS = """
QWidget { background-color: #F5F5F5; color: #212121; }
QMainWindow, QDialog { background-color: #F5F5F5; }
QGroupBox { border: 1px solid #C0C0C0; border-radius: 4px; margin-top: 8px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #555; }
QPushButton {
    background-color: #FAFAFA; border: 1px solid #BDBDBD; border-radius: 3px;
    padding: 4px 12px; min-height: 22px;
}
QPushButton:hover { background-color: #EEEEEE; border-color: #1976D2; }
QPushButton:pressed { background-color: #E0E0E0; }
QPushButton:disabled { color: #9E9E9E; background-color: #F0F0F0; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #FFFFFF; border: 1px solid #BDBDBD; border-radius: 3px;
    padding: 2px 6px; min-height: 22px;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #1976D2;
}
/* 关键：自定义 padding 后必须显式给上下箭头按钮分配区域，否则无法点击 */
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border-left: 1px solid #BDBDBD; border-bottom: 1px solid #BDBDBD;
    background: #EEEEEE;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border-left: 1px solid #BDBDBD; border-top: 1px solid #BDBDBD;
    background: #EEEEEE;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #D6E9F8; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: #1976D2; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("@UP_ARROW_LIGHT@"); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("@DOWN_ARROW_LIGHT@"); width: 10px; height: 10px;
}
QStatusBar { background-color: #ECEFF1; border-top: 1px solid #B0BEC5; }
QMenuBar { background-color: #ECEFF1; }
QMenuBar::item:selected { background-color: #1976D2; color: white; }
QMenu { background-color: #FFFFFF; border: 1px solid #BDBDBD; }
QMenu::item:selected { background-color: #1976D2; color: white; }
QSplitter::handle { background-color: #B0BEC5; }
QSplitter::handle:hover { background-color: #1976D2; }
"""

# 暗色主题：深背景 + 蓝色焦点
_DARK_QSS = """
QWidget { background-color: #2B2B2B; color: #DCDCDC; }
QMainWindow, QDialog { background-color: #2B2B2B; }
QGroupBox { border: 1px solid #555; border-radius: 4px; margin-top: 8px; padding-top: 8px; }
QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; color: #AAA; }
QPushButton {
    background-color: #3C3F41; border: 1px solid #5A5A5A; border-radius: 3px;
    padding: 4px 12px; min-height: 22px; color: #DCDCDC;
}
QPushButton:hover { background-color: #4A4D4F; border-color: #2196F3; }
QPushButton:pressed { background-color: #2E3133; }
QPushButton:disabled { color: #777; background-color: #353535; }
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background-color: #3C3F41; border: 1px solid #5A5A5A; border-radius: 3px;
    padding: 2px 6px; min-height: 22px; color: #DCDCDC;
    selection-background-color: #2196F3;
}
QComboBox:focus, QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #2196F3;
}
/* 关键：自定义 padding 后必须显式给上下箭头按钮分配区域，否则无法点击 */
QSpinBox, QDoubleSpinBox { padding-right: 22px; }
QSpinBox::up-button, QDoubleSpinBox::up-button {
    subcontrol-origin: border; subcontrol-position: top right;
    width: 20px; border-left: 1px solid #5A5A5A; border-bottom: 1px solid #5A5A5A;
    background: #4A4D4F;
}
QSpinBox::down-button, QDoubleSpinBox::down-button {
    subcontrol-origin: border; subcontrol-position: bottom right;
    width: 20px; border-left: 1px solid #5A5A5A; border-top: 1px solid #5A5A5A;
    background: #4A4D4F;
}
QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover { background: #5C6063; }
QSpinBox::up-button:pressed, QDoubleSpinBox::up-button:pressed,
QSpinBox::down-button:pressed, QDoubleSpinBox::down-button:pressed { background: #2196F3; }
QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
    image: url("@UP_ARROW_DARK@"); width: 10px; height: 10px;
}
QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
    image: url("@DOWN_ARROW_DARK@"); width: 10px; height: 10px;
}
QComboBox QAbstractItemView { background-color: #3C3F41; color: #DCDCDC; selection-background-color: #2196F3; }
QStatusBar { background-color: #1F1F1F; border-top: 1px solid #555; }
QMenuBar { background-color: #1F1F1F; color: #DCDCDC; }
QMenuBar::item:selected { background-color: #2196F3; color: white; }
QMenu { background-color: #2B2B2B; border: 1px solid #555; color: #DCDCDC; }
QMenu::item:selected { background-color: #2196F3; color: white; }
QSplitter::handle { background-color: #555; }
QSplitter::handle:hover { background-color: #2196F3; }
QLabel { color: #DCDCDC; }
QCheckBox { color: #DCDCDC; }
"""


THEMES: dict[str, str] = {
    "light": _LIGHT_QSS,
    "dark": _DARK_QSS,
}

DEFAULT_THEME = "dark"


def available_themes() -> Iterable[str]:
    return THEMES.keys()


def apply_theme(name: str) -> str:
    """把指定主题套到当前 QApplication；返回最终实际生效的主题名。

    未识别名称时回落到 :data:`DEFAULT_THEME`。
    """
    theme = name if name in THEMES else DEFAULT_THEME
    app = QApplication.instance()
    if app is not None:
        # 运行时替换 SVG 资源绝对路径，避免受 cwd 影响；
        # 用 @TOKEN@ 而不是 .format()，因为 QSS 本身包含大量 { }
        qss = (
            THEMES[theme]
            .replace("@UP_ARROW_LIGHT@", _asset_url("arrow_up_light.svg"))
            .replace("@DOWN_ARROW_LIGHT@", _asset_url("arrow_down_light.svg"))
            .replace("@UP_ARROW_DARK@", _asset_url("arrow_up_dark.svg"))
            .replace("@DOWN_ARROW_DARK@", _asset_url("arrow_down_dark.svg"))
        )
        app.setStyleSheet(qss)
    return theme
