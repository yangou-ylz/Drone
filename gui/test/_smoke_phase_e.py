# -*- coding: utf-8 -*-
"""阶段 E 烟雾测试：占位命令注册、主题、视图菜单。

仅做"能起来 + 关键 API 可用"的快速检查，不依赖飞机。
运行：``python gui/_smoke_phase_e.py``
"""
from __future__ import annotations

import os
import sys

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# 启用 Fake，避免动真串口
os.environ["LINGXIAO_GUI_FAKE"] = "1"

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.command_registry import REGISTRY  # noqa: E402
from gui.services.theme_service import THEMES, apply_theme  # noqa: E402
import gui.commands  # noqa: F401, E402


def check_placeholders() -> None:
    """占位命令应注册，build_frame 应抛 NotImplementedError，parse_ack 返回 None。"""
    print("[1] 占位命令注册检查")
    flight = REGISTRY.get(0xE1)
    mode = REGISTRY.get(0xE2)
    assert flight is not None, "0xE1 占位命令未注册"
    assert mode is not None, "0xE2 占位命令未注册"
    assert flight.category == "飞行控制（占位）", f"分类错: {flight.category!r}"
    assert mode.category == "模式切换（占位）", f"分类错: {mode.category!r}"
    print("    cmd_id, name:", hex(flight.cmd_id), flight.name)
    print("    cmd_id, name:", hex(mode.cmd_id), mode.name)
    # build_frame 应抛
    try:
        flight.build_frame({})
    except NotImplementedError as exc:
        print("    [ok] build_frame 抛 NotImplementedError:", exc)
    else:
        raise AssertionError("占位 build_frame 没有抛异常！")
    # parse_ack 应返回 None
    assert flight.parse_ack("F1: X=1 Y=2") is None
    assert mode.parse_ack("anything") is None
    print("    [ok] parse_ack 始终返回 None")


def check_themes() -> int:
    """主题应能 apply 且不抛错。"""
    print("[2] 主题切换检查")
    app = QApplication.instance() or QApplication(sys.argv)
    assert "dark" in THEMES and "light" in THEMES
    for name in ("dark", "light"):
        applied = apply_theme(name)
        assert applied == name, f"apply_theme({name!r}) 返回 {applied!r}"
        print(f"    [ok] apply_theme({name!r}) 生效")
    # 未识别 → 回落 dark
    applied = apply_theme("nonsense")
    assert applied == "dark", f"回落失败: {applied!r}"
    print("    [ok] 未知主题回落到 dark")
    return 0


def check_main_window() -> int:
    """MainWindow 应能构建，菜单含「视图」，CommandPanel 包含占位类别。"""
    print("[3] MainWindow 端到端")
    app = QApplication.instance() or QApplication(sys.argv)
    from gui.main import MainWindow
    win = MainWindow()

    # 菜单
    menus = [m.title() for m in win.menuBar().findChildren(type(win.menuBar().actions()[0].menu())) if m]
    # 直接看 menuBar 顶层
    titles = [a.text() for a in win.menuBar().actions()]
    print("    顶层菜单:", titles)
    assert any("视图" in t for t in titles), f"缺少视图菜单: {titles}"

    # 占位类别应出现在 CommandPanel 分类下拉
    cats = [win._command_panel._cat_combo.itemText(i)
            for i in range(win._command_panel._cat_combo.count())]
    print("    分类下拉:", cats)
    assert "飞行控制（占位）" in cats, f"占位分类缺失: {cats}"
    assert "模式切换（占位）" in cats, f"占位分类缺失: {cats}"

    # 选中占位分类后，对应面板应能懒构造（disabled 按钮）
    idx = cats.index("飞行控制（占位）")
    win._command_panel._cat_combo.setCurrentIndex(idx)
    QApplication.processEvents()
    cmd = win._command_panel.current_command()
    assert cmd is not None and cmd.cmd_id == 0xE1, f"current_command 错: {cmd}"
    panel = win._command_panel._panels.get(0xE1)
    assert panel is not None, "占位面板未懒构造"
    # 按钮永远禁用
    assert panel._btn.isEnabled() is False
    # 即使 set_enabled_for_link(True) 后仍禁用
    panel.set_enabled_for_link(True)
    assert panel._btn.isEnabled() is False, "占位面板 set_enabled_for_link 后竟可用！"
    print("    [ok] 占位面板按钮永久禁用")

    # 视图菜单切换主题不报错
    win._on_view_change_theme  # 仅引用，不触发（无 sender）

    # 状态栏最后接收 label 存在
    assert hasattr(win, "_sb_last_rx"), "缺少 _sb_last_rx"
    print("    [ok] 状态栏含最后接收 label:", win._sb_last_rx.text())

    QTimer.singleShot(50, app.quit)
    rc = app.exec()
    print("    app.exec returned", rc)
    return rc


def main() -> int:
    check_placeholders()
    check_themes()
    rc = check_main_window()
    print("\n阶段 E 烟雾测试 OK" if rc == 0 else "\n阶段 E 烟雾测试 FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
