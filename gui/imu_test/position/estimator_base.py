# -*- coding: utf-8 -*-
"""位置估计器抽象层（方案A：策略模式 + 注册表）。

设计目标（2026-07-17，用户拍板）：
- 高度抽象、接口统一，可扩展、易维护
- 支持多种"由观测量得到位置"的算法，可传参/改模式切换：
    · 直接转发外部观测位置（0x32）
    · 速度积分（0x07 → 位移）
    · 加速度二次积分（0x01 → 位移）
    · 未来：滤波、融合（互补/卡尔曼……）
- 统一注册、统一管理：新算法只需继承 `PositionEstimator` + `@register`，
  GUI 启动即自动出现在对比列表里。

关键约定：
- 输入：每个估计器声明自己需要的观测量类型 `input_kind`（POSITION/VELOCITY/ACCEL）。
  面板把 hub 的样本按类型路由过来，调用 `update(t, x, y, z)`。
  (x,y,z) 采用该输入的自然单位：位置 cm、速度 cm/s、加速度 m/s²。
- 输出：`update` 返回相对装填原点的**三轴位移**，统一单位 **cm**。
  —— 检测的是"位移(相对量)"，不是绝对位置。
- 轴向：按用户选择"机体系 前X-左Y-上Z"，与线速度面板一致，逐轴直连(vx→X,vy→Y,vz→Z)，
  面板层不做坐标变换。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple, Type


class InputKind(Enum):
    """估计器需要的观测量类型（决定面板把哪种 hub 样本喂给它）。"""

    POSITION = "position"       # 外部位置 cm（0x32）
    VELOCITY = "velocity"       # 速度 cm/s（0x07 飞控融合速度）
    ACCEL = "accel"             # 加速度 m/s²（0x01）
    GEN_VELOCITY = "gen_velocity"  # 光流原始速度 cm/s（0x33）


@dataclass(frozen=True)
class ParamSpec:
    """一个可在 GUI 现场调节的参数声明（自动生成 SpinBox）。"""

    key: str                  # 参数标识（set_param 用）
    label: str                # 中文显示名
    default: float            # 默认值
    minimum: float            # 下限
    maximum: float            # 上限
    step: float               # 步进
    unit: str = ""            # 单位（显示用）
    decimals: int = 3         # 小数位


Vec3 = Tuple[float, float, float]


class PositionEstimator(ABC):
    """位置估计器抽象基类。所有算法遵循此统一接口。

    子类必须定义类属性：``key`` / ``label`` / ``input_kind`` / ``color``，
    并实现 ``reset`` 与 ``update``。可选实现 ``params_spec`` 暴露可调参数。
    """

    #: 算法唯一标识（英文，作 CSV/日志用）
    key: str = "base"
    #: 中文显示名（图例/下拉框用）
    label: str = "基类"
    #: 需要的观测量类型
    input_kind: InputKind = InputKind.VELOCITY
    #: 曲线/图例颜色
    color: str = "#FFFFFF"

    def __init__(self) -> None:
        self._params: Dict[str, float] = {
            spec.key: spec.default for spec in self.params_spec()
        }
        self.reset()

    # -------- 参数 --------
    @classmethod
    def params_spec(cls) -> List[ParamSpec]:
        """返回可调参数声明列表（默认无参数，子类按需覆盖）。"""
        return []

    def set_param(self, key: str, value: float) -> None:
        """现场更新一个参数（GUI SpinBox 回调）。未知 key 忽略。"""
        if key in self._params:
            self._params[key] = float(value)

    def param(self, key: str, default: float = 0.0) -> float:
        return self._params.get(key, default)

    # -------- 生命周期 --------
    @abstractmethod
    def reset(self) -> None:
        """清零内部状态并把下一帧作为位移原点（装填/重置时调用）。"""
        raise NotImplementedError

    @abstractmethod
    def update(self, t: float, x: float, y: float, z: float) -> Vec3:
        """喂入一帧观测量，返回当前相对位移 (dx, dy, dz)，单位 cm。

        参数 (x,y,z) 单位取决于 ``input_kind``：
        位置=cm、速度=cm/s、加速度=m/s²。
        """
        raise NotImplementedError


# --------------------------------------------------------------------------- #
# 注册表：新算法 @register 即自动纳入统一管理
# --------------------------------------------------------------------------- #
_REGISTRY: "Dict[str, Type[PositionEstimator]]" = {}


def register(cls: "Type[PositionEstimator]") -> "Type[PositionEstimator]":
    """类装饰器：把估计器登记到全局注册表（按 key 去重，后者覆盖并告警）。"""
    key = getattr(cls, "key", None)
    if not key or key == "base":
        raise ValueError(f"估计器 {cls.__name__} 必须定义唯一的类属性 key")
    _REGISTRY[key] = cls
    return cls


def registered_classes() -> "List[Type[PositionEstimator]]":
    """返回已注册的估计器类（按注册顺序）。"""
    return list(_REGISTRY.values())


def create_all() -> "List[PositionEstimator]":
    """实例化全部已注册估计器（多算法并行对比用）。"""
    return [cls() for cls in _REGISTRY.values()]
