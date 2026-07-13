# -*- coding: utf-8 -*-
"""P2 遥测数据模型（不可变 dataclass，零 Qt 依赖，便于单元测试和跨线程传递）。

字段冻结依据：gui/path_viz_master_plan.md P0 字段冻结结论。
单位约定：长度=cm，时间=s，角度=度，速度=cm/s；与官方手册保持一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AttitudeSample:
    """0x03 欧拉角（fallback）或 0x04 四元数转欧拉后的姿态。

    - ts: 接收时刻（秒，单调时钟 time.monotonic）
    - roll/pitch/yaw_deg: 度，世界 NWU 系下 -180~180
    - source: 'quat' (0x04) 或 'euler' (0x03)，便于上层选择优先级
    - fusion_sta: 融合状态字节（手册未细化语义，原样透传）
    """
    ts: float
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    source: str
    fusion_sta: int


@dataclass(frozen=True)
class VelocitySample:
    """0x07 飞行速度（大地 NWU 系，北 x+ / 西 y+ / 天 z+），cm/s。"""
    ts: float
    vx_cmps: int
    vy_cmps: int
    vz_cmps: int


@dataclass(frozen=True)
class HeightSample:
    """0x05 高度数据，单位 cm。

    - alt_fu_cm: 融合后对地高度（Z 直接来源，D5）
    - alt_add_cm: 附加测距高度（超声/激光）
    - alt_sta: 测距状态字节
    """
    ts: float
    alt_fu_cm: int
    alt_add_cm: int
    alt_sta: int


@dataclass(frozen=True)
class FlightModeSample:
    """0x06 飞控运行模式（U8 ×5）。

    - mode: 飞控模式原始值
    - locked: True=已解锁（LOCKED=1），False=锁定（LOCKED=0）
    - cid/cmd0/cmd1: 当前飞控执行的指令功能（指示最近一次）
    """
    ts: float
    mode: int
    locked: bool
    cid: int
    cmd0: int
    cmd1: int


@dataclass(frozen=True)
class BatterySample:
    """0x0D 电压电流数据（传输时扩大 100 倍）。"""
    ts: float
    voltage_v: float
    current_a: float


@dataclass(frozen=True)
class ModuleStatusSample:
    """0x0E 外接模块工作状态（U8 ×4）。

    每个状态值语义：0=无数据 / 1=有数据但不可用 / 2=正常 / 3=良好（GPS 专用）。
    - sta_g_vel: 通用速度传感器状态
    - sta_g_pos: 通用位置传感器状态
    - sta_gps: GPS 传感器状态
    - sta_alt_add: 附加测高传感器状态
    """
    ts: float
    sta_g_vel: int
    sta_g_pos: int
    sta_gps: int
    sta_alt_add: int


@dataclass(frozen=True)
class GenPositionSample:
    """0x32 通用位置型传感器数据（S32 ×3，cm）。

    valid_* 表示对应轴是否有效（0x80000000 为无效标志）。
    """
    ts: float
    x_cm: int
    y_cm: int
    z_cm: int
    valid_x: bool
    valid_y: bool
    valid_z: bool


@dataclass(frozen=True)
class GenVelocitySample:
    """0x33 通用速度型传感器数据（光流等，S16 ×3，cm/s）。

    valid_* 表示对应轴是否有效（0x8000 为无效标志）。
    """
    ts: float
    vx_cmps: int
    vy_cmps: int
    vz_cmps: int
    valid_x: bool
    valid_y: bool
    valid_z: bool


@dataclass(frozen=True)
class GenDistanceSample:
    """0x34 通用测距传感器数据（激光/超声等）。

    - direction: 安装方向 0=水平 / 1=垂直
    - angle: 角度信息（0-359）
    - distance_cm: 距离 cm（0xFFFFFFFF 为无效）
    - valid: 距离是否有效
    """
    ts: float
    direction: int
    angle: int
    distance_cm: int
    valid: bool



@dataclass(frozen=True)
class PathPoint:
    """轨迹点：激活瞬间机头为 x+ 的局部世界系下的坐标，cm。"""
    ts: float
    x_cm: float
    y_cm: float
    z_cm: float


@dataclass(frozen=True)
class PathTrackerConfig:
    """PathTracker 行为参数（D7 + 健壮性）。"""
    trail_seconds: float = 20.0       # 路径残留秒数
    max_points: int = 1800            # 兜底点数上限
    min_dt_s: float = 1e-4            # 单步 dt 下限（防抖）
    max_dt_s: float = 0.2             # 单步 dt 上限（防大跳）


@dataclass(frozen=True)
class PathSnapshot:
    """供渲染层使用的一帧快照（不可变，安全跨线程传递）。"""
    ts: float
    enabled: bool                     # 当前是否处于"激活"状态
    yaw0_deg: float                   # 激活瞬间快照的世界系 yaw（用于反旋转）
    pos_cm: tuple[float, float, float] = (0.0, 0.0, 0.0)
    attitude_deg: tuple[float, float, float] = (0.0, 0.0, 0.0)  # roll/pitch/yaw 当前值
    vel_local_cmps: tuple[float, float, float] = (0.0, 0.0, 0.0)  # 局部系速度
    points: tuple[PathPoint, ...] = field(default_factory=tuple)
