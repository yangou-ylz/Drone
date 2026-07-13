# -*- coding: utf-8 -*-
"""P1 烟雾测试：顶部"功能"菜单 + 路径可视化 Dock 显隐 + 持久化。

验收清单：
1) MainWindow 顶层菜单含"功能"
2) "功能"下有 checkable 项"路径可视化"
3) 默认未勾选时 Dock 隐藏；勾选后 Dock 显示
4) 取消勾选后 Dock 再次隐藏
5) 勾选状态写入 ConfigService(`features.path_visualization`)
6) 关闭 Dock（模拟点 X）→ 菜单勾选同步取消

运行：``python gui/test/_smoke_phase_p1.py``，EXIT=0 才算通过。
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 走 Fake，避免动真串口
os.environ["LINGXIAO_GUI_FAKE"] = "1"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QDockWidget  # noqa: E402


def check_feature_menu_and_dock() -> int:
    print("[P1] 功能菜单 + Dock 显隐 + 持久化")
    app = QApplication.instance() or QApplication(sys.argv)

    # 重置 features 持久化键，保证默认未勾选的断言可重复运行
    from gui.services.config_service import ConfigService
    _pre = ConfigService()
    _pre.set("features.path_visualization", False)

    from gui.main import MainWindow
    win = MainWindow()
    # 必须 show 主窗口，子部件 isVisible() 才返回 True
    win.show()
    QApplication.processEvents()

    # 1) 顶层菜单含"功能"
    titles = [a.text() for a in win.menuBar().actions()]
    print("    顶层菜单:", titles)
    assert any("功能" in t for t in titles), f"缺少功能菜单: {titles}"

    # 2) 找到路径可视化 action / dock
    act = win._feature_actions.get("path_visualization")
    dock = win._feature_docks.get("path_visualization")
    assert act is not None, "缺少路径可视化 QAction"
    assert dock is not None, "缺少路径可视化 QDockWidget"
    assert isinstance(dock, QDockWidget)
    assert act.isCheckable(), "路径可视化项必须 checkable"
    print(f"    [ok] 找到 QAction({act.text()!r}) 和 Dock({dock.objectName()!r})")

    # 3) 默认未勾选 → 隐藏
    # （首次启动 config 里没有 features.path_visualization → False）
    assert not act.isChecked(), "首次启动应未勾选"
    assert not dock.isVisible(), "首次启动 Dock 应隐藏"
    print("    [ok] 默认未勾选，Dock 隐藏")

    # 4) 勾选 → 显示 + 写配置
    act.setChecked(True)
    QApplication.processEvents()
    assert dock.isVisible(), "勾选后 Dock 应显示"
    saved = win._config.get("features.path_visualization", None)
    assert saved is True, f"勾选后配置应为 True，实际={saved!r}"
    print("    [ok] 勾选 → Dock 显示 + 配置=True")

    # 5) 取消勾选 → 隐藏 + 写配置 False
    act.setChecked(False)
    QApplication.processEvents()
    assert not dock.isVisible(), "取消勾选后 Dock 应隐藏"
    saved = win._config.get("features.path_visualization", None)
    assert saved is False, f"取消勾选后配置应为 False，实际={saved!r}"
    print("    [ok] 取消勾选 → Dock 隐藏 + 配置=False")

    # 6) 关闭 Dock（模拟用户点 X）→ 菜单同步取消勾选
    act.setChecked(True)
    QApplication.processEvents()
    assert dock.isVisible() and act.isChecked()
    dock.close()  # 触发 visibilityChanged(False)
    QApplication.processEvents()
    assert not act.isChecked(), "Dock 被关闭后菜单应自动取消勾选"
    print("    [ok] 关 Dock → 菜单同步取消勾选")

    QTimer.singleShot(50, app.quit)
    rc = app.exec()
    print("    app.exec returned", rc)
    return rc


def main() -> int:
    rc = check_feature_menu_and_dock()
    print("\nP1 烟雾测试 OK" if rc == 0 else "\nP1 烟雾测试 FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
