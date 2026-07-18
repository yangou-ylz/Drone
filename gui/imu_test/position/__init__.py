# -*- coding: utf-8 -*-
"""位置估计器包：策略模式 + 注册表。

导入本包即触发 estimators 模块里各算法的 @register 自注册。
"""
from gui.imu_test.position.estimator_base import (
    InputKind,
    ParamSpec,
    PositionEstimator,
    create_all,
    register,
    registered_classes,
)
# 导入以触发具体算法自注册（勿删）
from gui.imu_test.position import estimators  # noqa: F401

__all__ = [
    "InputKind",
    "ParamSpec",
    "PositionEstimator",
    "create_all",
    "register",
    "registered_classes",
]
