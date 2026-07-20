# -*- coding: utf-8 -*-
"""协议薄壳：复用 groundTest/ano_protocol.py，不重写。

groundTest 不是包（无 __init__.py），用 sys.path 注入方式 import，
后续若 groundTest 改造为包，此处只需删掉 sys.path 注入。
"""
from __future__ import annotations
import os
import sys

# 把 <repo>/groundTest 加入 sys.path
_GROUNDTEST_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), os.pardir, os.pardir, "groundTest")
)
if _GROUNDTEST_DIR not in sys.path:
    sys.path.insert(0, _GROUNDTEST_DIR)

# 透传 ano_protocol 全部公共符号
from ano_protocol import (  # noqa: E402  (path 注入后再 import)
    FRAME_HEAD,
    ADDR_BROADCAST,
    ADDR_UPPER,
    ADDR_IMU,
    ADDR_FC_STM32,
    COLOR_BLACK,
    COLOR_RED,
    COLOR_GREEN,
    Frame,
    FrameParser,
    build_frame,
    build_f1_xy,
    build_f2_param,
    build_f3_xyz,
    calc_checksum,
)

__all__ = [
    "FRAME_HEAD",
    "ADDR_BROADCAST",
    "ADDR_UPPER",
    "ADDR_IMU",
    "ADDR_FC_STM32",
    "COLOR_BLACK",
    "COLOR_RED",
    "COLOR_GREEN",
    "Frame",
    "FrameParser",
    "build_frame",
    "build_f1_xy",
    "build_f2_param",
    "build_f3_xyz",
    "calc_checksum",
]
