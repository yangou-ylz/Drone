# -*- coding: utf-8 -*-
"""命令注册集合。

**新增命令的唯一接入点**：在下方 import 一行即可（模块顶层会自动注册到 REGISTRY）。
"""
from . import cmd_f1  # noqa: F401  导入即触发自注册
from . import cmd_f2  # noqa: F401  导入即触发自注册
from . import cmd_f3  # noqa: F401  导入即触发自注册
from . import cmd_auto_control  # noqa: F401  自主飞行组合面板（代理F7/F9）
from . import cmd_f7  # noqa: F401  自主任务状态机命令
from . import cmd_f9  # noqa: F401  GUI相对位移命令
from . import cmd_placeholder  # noqa: F401  占位命令（飞行控制 / 模式切换）

__all__ = [
    "cmd_f1",
    "cmd_f2",
    "cmd_f3",
    "cmd_auto_control",
    "cmd_f7",
    "cmd_f9",
    "cmd_placeholder",
]
