# -*- coding: utf-8 -*-
"""P10 数据源接口：把传感器输入从硬编码解耦。

四类接口 + 一个凌霄 IMU 适配器：

- :class:`IPositionSource` —— 提供 (x,y,z) cm 位置
- :class:`IAttitudeSource` —— 提供 roll/pitch/yaw (°)
- :class:`IPointCloudSource` —— 提供 Nx3 点云（cm，可选）
- :class:`IAnchorSource` —— 提供锚点列表（UWB 基站坐标等）

设计原则：
- 纯 Python ABC，**不依赖 Qt**，便于在测试里 mock；
- 每个接口都有 ``is_available`` 用于运行时探测；返回 ``None`` 表示当前帧无数据；
- 时间戳统一用 ``time.monotonic()`` 秒（与 :class:`telemetry_models` 对齐）；
- :class:`LingxiaoImuSource` 是当前唯一实现：从 :class:`TelemetryBus` 信号拿最新姿态/位置，
  桥接到 :class:`IPositionSource` + :class:`IAttitudeSource`，不修改老数据通路。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Tuple


# ----------------------------------------------------------------------
# 纯数据载体
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class PositionReading:
    """位置读数（局部世界系 cm，z+ 向上）。"""
    x_cm: float
    y_cm: float
    z_cm: float
    t_mono: float


@dataclass(frozen=True)
class AttitudeReading:
    """姿态读数（°，NWU 右手）。"""
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    t_mono: float


@dataclass(frozen=True)
class AnchorPoint:
    """UWB / 视觉锚点。"""
    name: str
    x_cm: float
    y_cm: float
    z_cm: float


# ----------------------------------------------------------------------
# 接口
# ----------------------------------------------------------------------
class IPositionSource(ABC):
    """位置数据源接口。"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def latest(self) -> Optional[PositionReading]:
        """返回最近一次位置；无数据返回 None。"""


class IAttitudeSource(ABC):
    """姿态数据源接口。"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def latest(self) -> Optional[AttitudeReading]: ...


class IPointCloudSource(ABC):
    """点云数据源接口（激光/TOF/双目）。"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def latest(self) -> Optional[Tuple[float, list]]:
        """返回 (t_mono, [(x,y,z), ...])；无数据返回 None。

        点云用 list[tuple] 比 numpy 更友好于 mock；上层渲染再转 ndarray。
        """


class IAnchorSource(ABC):
    """锚点数据源接口（静态/半静态）。"""

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def anchors(self) -> List[AnchorPoint]:
        """返回当前锚点列表；无锚点返回空列表。"""


# ----------------------------------------------------------------------
# 凌霄 IMU 适配器
# ----------------------------------------------------------------------
class LingxiaoImuSource(IPositionSource, IAttitudeSource):
    """把 :class:`TelemetryBus` + :class:`PathTracker` 包装成位置+姿态源。

    用法（示例）::

        bus = TelemetryBus()
        src = LingxiaoImuSource(bus)
        if src.is_available():
            p = src.latest()  # PositionReading

    本类不订阅信号，每次 ``latest()`` 直接读 tracker 最新 snapshot，
    避免与现有 ``path_updated`` 信号链重复维护状态。
    """

    def __init__(self, bus) -> None:
        self._bus = bus

    # ---- IPositionSource ----
    def is_available(self) -> bool:
        try:
            snap = self._bus.tracker.snapshot()
            return snap is not None
        except Exception:
            return False

    def latest(self) -> Optional[PositionReading]:  # type: ignore[override]
        # PySide6 多继承时返回类型要 ignore，但运行时按调用上下文区分
        try:
            snap = self._bus.tracker.snapshot()
            if snap is None:
                return None
            x, y, z = snap.pos_cm
            return PositionReading(
                x_cm=float(x),
                y_cm=float(y),
                z_cm=float(z),
                t_mono=float(snap.ts),
            )
        except Exception:
            return None

    # ---- IAttitudeSource ----
    def latest_attitude(self) -> Optional[AttitudeReading]:
        """同时提供姿态接口。

        为避免与 ``latest()`` 方法名冲突（位置 vs 姿态），姿态用独立名称。
        若调用方需要严格按接口走，可用 :func:`as_attitude_source` 拿到一个
        薄代理把 ``latest()`` 转发到这里。
        """
        try:
            snap = self._bus.tracker.snapshot()
            if snap is None:
                return None
            r, p, y = snap.attitude_deg
            return AttitudeReading(
                roll_deg=float(r),
                pitch_deg=float(p),
                yaw_deg=float(y),
                t_mono=float(snap.ts),
            )
        except Exception:
            return None

    def as_attitude_source(self) -> "IAttitudeSource":
        """返回一个 :class:`IAttitudeSource` 视图（latest 转发到 latest_attitude）。"""
        outer = self

        class _AttView(IAttitudeSource):
            def is_available(self) -> bool:
                return outer.is_available()

            def latest(self) -> Optional[AttitudeReading]:
                return outer.latest_attitude()

        return _AttView()
