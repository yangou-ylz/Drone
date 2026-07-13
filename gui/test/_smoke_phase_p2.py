# -*- coding: utf-8 -*-
"""P2 烟雾测试：解码 + PathTracker + TelemetryBus 数学正确性 + 节流 + 渲染开关。

跑法（必须用 3.13 解释器，3.14 默认无 PySide6）：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p2

通过条件：EXIT=0 + 所有 [P2-x] 行打印 OK。
不引入 QApplication，TelemetryBus 仅作为 QObject 直接调用槽。
"""
from __future__ import annotations

import math
import struct
import sys
from pathlib import Path

# 把仓库根加入 sys.path，便于 `python gui/test/_smoke_phase_p2.py` 直接跑
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import QCoreApplication  # noqa: E402

from gui.io.protocol import Frame  # noqa: E402
from gui.services.path_tracker import PathTracker  # noqa: E402
from gui.services.telemetry_bus import TelemetryBus  # noqa: E402
from gui.services.telemetry_decoder import (  # noqa: E402
    decode_attitude_euler,
    decode_attitude_quat,
    decode_height,
    decode_velocity,
)
from gui.services.telemetry_models import PathTrackerConfig  # noqa: E402


# ---------- 帮助：手工构造 Frame（不走串口）----------
def _make_frame(cmd: int, data: bytes) -> Frame:
    return Frame(dest=0xAF, cmd=cmd, data=data, sc=0, ac=0, raw=b"")


def _quat_data(roll_deg: float, pitch_deg: float, yaw_deg: float) -> bytes:
    """生成给定欧拉角的 0x04 帧 DATA（NED约定：偏航顺时针为正，z分量取负，与匿名IMU实际格式一致）。"""
    cr = math.cos(math.radians(roll_deg) / 2.0)
    sr = math.sin(math.radians(roll_deg) / 2.0)
    cp = math.cos(math.radians(pitch_deg) / 2.0)
    sp = math.sin(math.radians(pitch_deg) / 2.0)
    cy = math.cos(math.radians(yaw_deg) / 2.0)
    sy = math.sin(math.radians(yaw_deg) / 2.0)
    w = cr * cp * cy + sr * sp * sy
    x = sr * cp * cy - cr * sp * sy
    y = cr * sp * cy + sr * cp * sy
    z = cr * cp * sy - sr * sp * cy
    # NED约定：偏航顺时针为正，z分量取反（匿名IMU四元数实际格式）
    v0, v1, v2, v3 = int(w * 10000), int(x * 10000), int(y * 10000), int(-z * 10000)
    return struct.pack("<hhhhB", v0, v1, v2, v3, 0)


def _euler_data(roll_deg: float, pitch_deg: float, yaw_deg: float) -> bytes:
    return struct.pack(
        "<hhhB",
        round(roll_deg * 100),
        round(pitch_deg * 100),
        round(yaw_deg * 100),
        0,
    )


def _height_data(alt_fu_cm: int, alt_add_cm: int = 0, alt_sta: int = 0) -> bytes:
    return struct.pack("<iiB", alt_fu_cm, alt_add_cm, alt_sta)


def _velocity_data(vx: int, vy: int, vz: int) -> bytes:
    return struct.pack("<hhh", vx, vy, vz)


# ---------- 用例 ----------
def case_1_decoder_basic() -> None:
    """[P2-1] 解码器：长度/数值正确。"""
    # 0x03 欧拉
    s = decode_attitude_euler(_euler_data(1.23, -4.56, 90.0), ts=0.0)
    assert s is not None and s.source == "euler"
    assert abs(s.roll_deg - 1.23) < 1e-6
    assert abs(s.pitch_deg + 4.56) < 1e-6
    assert abs(s.yaw_deg - 90.0) < 1e-6
    # 0x04 四元数 -> 欧拉
    s = decode_attitude_quat(_quat_data(0.0, 0.0, 90.0), ts=0.0)
    assert s is not None and s.source == "quat"
    assert abs(s.yaw_deg - 90.0) < 0.05
    # 0x05 高度
    h = decode_height(_height_data(123, 45, 7), ts=0.0)
    assert h is not None and h.alt_fu_cm == 123 and h.alt_add_cm == 45 and h.alt_sta == 7
    # 0x07 速度
    v = decode_velocity(_velocity_data(100, -50, 30), ts=0.0)
    assert v is not None and v.vx_cmps == 100 and v.vy_cmps == -50 and v.vz_cmps == 30
    # 长度错误 → None
    assert decode_velocity(b"\x01\x02", ts=0.0) is None
    assert decode_height(b"\x01", ts=0.0) is None
    print("[P2-1] decoder basic OK")


def case_2_tracker_yaw0_rotation() -> None:
    """[P2-2] PathTracker：yaw0=0 时世界=局部；yaw0=90° 时数学自洽。"""
    # --- 子用例 A：yaw0=0，应零旋转 ---
    tr = PathTracker(PathTrackerConfig(trail_seconds=10.0, max_points=1000,
                                       min_dt_s=1e-4, max_dt_s=2.0))
    tr.on_attitude(decode_attitude_quat(_quat_data(0, 0, 0), ts=0.0))
    tr.on_height(decode_height(_height_data(50), ts=0.0))
    tr.enable()
    tr.on_velocity(decode_velocity(_velocity_data(100, 0, 0), ts=1.0))  # 基准
    tr.on_velocity(decode_velocity(_velocity_data(100, 0, 0), ts=2.0))  # dt=1s
    snap = tr.snapshot()
    x, y, z = snap.pos_cm
    assert abs(x - 100.0) < 1e-2, f"yaw0=0 时 x 应≈100, got {x}"
    assert abs(y) < 1e-2, f"yaw0=0 时 y 应≈0, got {y}"
    # P3 微调：Z 以 enable 时刻为零点；enable 前 height=50 → z_offset=50 → z=0
    assert abs(z) < 1e-6, f"z 应=0 (enable 时刻为零点), got {z}"
    # 启用后再来 height=80 应得 z=80-50=30
    tr.on_height(decode_height(_height_data(80), ts=3.0))
    assert abs(tr.snapshot().pos_cm[2] - 30.0) < 1e-6
    # --- 子用例 B：yaw0=90°，反旋转一致性（机头朝向定义为局部 x+）---
    tr = PathTracker(PathTrackerConfig(trail_seconds=10.0, max_points=1000,
                                       min_dt_s=1e-4, max_dt_s=2.0))
    tr.on_attitude(decode_attitude_quat(_quat_data(0, 0, 90.0), ts=0.0))
    tr.enable()
    snap0 = tr.snapshot()
    assert abs(snap0.yaw0_deg - 90.0) < 0.05, f"yaw0 应≈90°, got {snap0.yaw0_deg}"
    # 0x07 是机体系速度；delta_yaw=0（yaw不变） → 体系前进(100,0) = 局部(100,0)
    tr.on_velocity(decode_velocity(_velocity_data(100, 0, 0), ts=1.0))
    tr.on_velocity(decode_velocity(_velocity_data(100, 0, 0), ts=2.0))
    snap = tr.snapshot()
    x, y, z = snap.pos_cm
    assert abs(x - 100.0) < 1e-2, f"yaw0=90 体系前进 x 应≈+100, got {x}"
    assert abs(y) < 1e-2, f"yaw0=90 体系前进 y 应≈0, got {y}"
    vxl, vyl, _ = snap.vel_local_cmps
    assert abs(vxl - 100.0) < 1e-2 and abs(vyl) < 1e-2
    print(f"[P2-2] tracker yaw0 body-frame OK (yaw0=90° pos=({x:.2f},{y:.2f},{z:.2f}))")


def case_3_tracker_disable_keeps_path() -> None:
    """[P2-3] disable 不清轨迹；reset 清轨迹；再 enable 重新快照 yaw0。"""
    tr = PathTracker()
    tr.on_attitude(decode_attitude_quat(_quat_data(0, 0, 0), ts=0.0))
    tr.enable()
    tr.on_velocity(decode_velocity(_velocity_data(50, 0, 0), ts=0.0))
    tr.on_velocity(decode_velocity(_velocity_data(50, 0, 0), ts=1.0))
    snap_a = tr.snapshot()
    assert len(snap_a.points) >= 2
    tr.disable()
    snap_b = tr.snapshot()
    assert len(snap_b.points) == len(snap_a.points), "disable 不应清空轨迹"
    assert snap_b.enabled is False
    # 重新启用：yaw 不同 → yaw0 应快照新值
    tr.on_attitude(decode_attitude_quat(_quat_data(0, 0, 45.0), ts=2.0))
    tr.enable()
    snap_c = tr.snapshot()
    assert abs(snap_c.yaw0_deg - 45.0) < 0.05
    assert snap_c.pos_cm == (0.0, 0.0, 0.0)
    assert len(snap_c.points) == 1  # 仅原点
    print("[P2-3] disable/reset/re-enable OK")


def case_4_tracker_trim() -> None:
    """[P2-4] 时间衰减 + 点数上限：超过窗口的点会被丢弃。"""
    cfg = PathTrackerConfig(trail_seconds=1.0, max_points=10, min_dt_s=1e-4, max_dt_s=0.2)
    tr = PathTracker(cfg)
    tr.on_attitude(decode_attitude_quat(_quat_data(0, 0, 0), ts=0.0))
    tr.enable()
    # 喂 100 帧速度，每 0.05s 一帧（超过 trail_seconds=1s）
    for i in range(100):
        tr.on_velocity(decode_velocity(_velocity_data(10, 0, 0), ts=i * 0.05))
    snap = tr.snapshot()
    # 兜底 max_points 不超 10
    assert len(snap.points) <= 10, f"max_points exceeded: {len(snap.points)}"
    # 头点 ts 应在尾点 ts - trail_seconds 之内
    if len(snap.points) >= 2:
        assert snap.points[-1].ts - snap.points[0].ts <= cfg.trail_seconds + 1e-6
    print(f"[P2-4] trim OK (kept {len(snap.points)} points)")


def case_5_bus_render_gate() -> None:
    """[P2-5] TelemetryBus：渲染关时不发 path_updated，但仍解码 + 广播原始样本。"""
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    counters = {"att": 0, "vel": 0, "hgt": 0, "path": 0}
    bus.attitude_updated.connect(lambda s: counters.__setitem__("att", counters["att"] + 1))
    bus.velocity_updated.connect(lambda s: counters.__setitem__("vel", counters["vel"] + 1))
    bus.height_updated.connect(lambda s: counters.__setitem__("hgt", counters["hgt"] + 1))
    bus.path_updated.connect(lambda s: counters.__setitem__("path", counters["path"] + 1))
    # render_enabled=False（默认）
    bus.feed_frame(_make_frame(0x04, _quat_data(0, 0, 0)))
    bus.feed_frame(_make_frame(0x05, _height_data(100)))
    bus.feed_frame(_make_frame(0x07, _velocity_data(50, 0, 0)))
    assert counters["att"] == 1 and counters["vel"] == 1 and counters["hgt"] == 1
    assert counters["path"] == 0, "渲染关时不应发 path_updated"
    # 启用渲染（同步发一次 final 快照 → 计数 +1）
    bus.set_render_enabled(True)
    assert counters["path"] >= 1
    base_path = counters["path"]
    # 现在喂速度，应产生节流后的 path_updated
    bus.set_render_fps(120)  # 拉高到 120 fps，避免被节流挡掉
    bus.feed_frame(_make_frame(0x07, _velocity_data(50, 0, 0)))
    bus.feed_frame(_make_frame(0x07, _velocity_data(50, 0, 0)))
    import time as _t
    _t.sleep(0.02)  # 让节流窗过去
    bus.feed_frame(_make_frame(0x07, _velocity_data(50, 0, 0)))
    assert counters["path"] > base_path, f"启用后应继续发 path_updated, got {counters['path']}"
    print(f"[P2-5] bus render gate OK (att/vel/hgt={counters['att']}/{counters['vel']}/{counters['hgt']}, path={counters['path']})")


def case_6_quat_priority_over_euler() -> None:
    """[P2-6] 0x04 在 0.5s 内有效时，0x03 应被忽略，避免双姿态来源抖动。"""
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    seen = []
    bus.attitude_updated.connect(lambda s: seen.append(s.source))
    bus.feed_frame(_make_frame(0x04, _quat_data(0, 0, 30)))  # 1 quat
    bus.feed_frame(_make_frame(0x03, _euler_data(0, 0, 99)))  # 应被丢
    assert seen == ["quat"], f"expected only quat, got {seen}"
    print("[P2-6] quat over euler priority OK")


def main() -> int:
    try:
        case_1_decoder_basic()
        case_2_tracker_yaw0_rotation()
        case_3_tracker_disable_keeps_path()
        case_4_tracker_trim()
        case_5_bus_render_gate()
        case_6_quat_priority_over_euler()
    except AssertionError as exc:
        import traceback
        traceback.print_exc()
        print(f"[P2 FAIL] {exc}")
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[P2 ERROR] {exc}")
        return 2
    print("[P2] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
