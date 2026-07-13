# -*- coding: utf-8 -*-
"""IMU 数据质量测试台（独立子包）。

本子包与现有 GUI 功能完全隔离：
- 只订阅 SerialWorker.frame_received 信号获取数据；
- 复用 gui/services 与 groundTest 的解码函数，不重写协议；
- 除 gui/main.py 少量菜单/切换接线外，不修改任何现有文件。

测试目标（依据 gui/imu测试要求.md + 用户 Yaw 跟随需求）：
1. 加速度计 scale 校准
2. 陀螺仪 scale + 零偏标定
2.5 姿态四元数质量
3. 数据频率
4. 数据完整性
6. 噪声方差
⭐ Yaw 跟随性测试（旋转-停止回漂量化）
"""
from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
