# -*- coding: utf-8 -*-
"""P10：数据源抽象接口包。

设计目的：把 GUI 的传感器输入从"硬编码 LingxiaoIMU + SerialWorker.frame_received"
解耦为四类可插拔接口，方便未来接入：
  - 光流位置 / UWB 位置 / VIO 位置          → IPositionSource
  - 外部姿态（IMU 仿真器 / EKF 后处理）     → IAttitudeSource
  - 激光雷达点云 / TOF 距离矩阵             → IPointCloudSource
  - UWB 锚点位置 / 标定点                   → IAnchorSource

本阶段只**定义接口 + LingxiaoImuSource 适配器**，老数据通路保持不变。
"""
from gui.sources.interfaces import (
    IPositionSource,
    IAttitudeSource,
    IPointCloudSource,
    IAnchorSource,
    LingxiaoImuSource,
    PositionReading,
    AttitudeReading,
    AnchorPoint,
)

__all__ = [
    "IPositionSource",
    "IAttitudeSource",
    "IPointCloudSource",
    "IAnchorSource",
    "LingxiaoImuSource",
    "PositionReading",
    "AttitudeReading",
    "AnchorPoint",
]
