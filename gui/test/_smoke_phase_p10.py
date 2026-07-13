# -*- coding: utf-8 -*-
"""P10 烟雾测试：数据源接口 + 视角预设 + 轨迹 CSV 导出 + 长稳定性微压。

验收范围：
- [P10-1] sources.interfaces：dataclass 可实例化 + Mock IPositionSource 子类满足契约
- [P10-2] LingxiaoImuSource：包装 TelemetryBus tracker.snapshot()，is_available + latest + latest_attitude
- [P10-3] 视角预设：top/side/free 触发后 self._s["render"] 字段更新 + settings_changed 发射
- [P10-4] export_path_csv：写入 header + N 个轨迹点，行数 == 点数 + 1
- [P10-5] 长稳定性微压：200Hz × 5s 灌 PathSnapshot → 无异常 + tracemalloc 内存增长 < 5MB

跑法：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p10

通过条件：EXIT=0 + 所有 [P10-x] 行打印 OK。
"""
from __future__ import annotations

import gc
import os
import sys
import tempfile
import time
import tracemalloc
from pathlib import Path
from typing import Optional

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.services.telemetry_models import PathPoint, PathSnapshot  # noqa: E402
from gui.sources import (  # noqa: E402
    AnchorPoint,
    AttitudeReading,
    IAnchorSource,
    IAttitudeSource,
    IPointCloudSource,
    IPositionSource,
    LingxiaoImuSource,
    PositionReading,
)
from gui.widgets.path_visualization_widget import PathVisualizationPlaceholder  # noqa: E402


def _make_app() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    return app


def _snap(x: float = 10.0, y: float = 20.0, z: float = 30.0,
          n_points: int = 3) -> PathSnapshot:
    pts = tuple(
        PathPoint(ts=float(i), x_cm=x + i, y_cm=y + i, z_cm=z + i)
        for i in range(n_points)
    )
    return PathSnapshot(
        ts=time.time(),
        enabled=True,
        yaw0_deg=0.0,
        pos_cm=(x, y, z),
        attitude_deg=(1.0, -2.0, 45.0),
        vel_local_cmps=(0.0, 0.0, 0.0),
        points=pts,
    )


# =============================================================
# Case 1：interfaces dataclass + Mock 子类
# =============================================================
def case_1_interfaces_mock() -> None:
    p = PositionReading(x_cm=1.0, y_cm=2.0, z_cm=3.0, t_mono=0.5)
    assert p.x_cm == 1.0 and p.z_cm == 3.0
    a = AttitudeReading(roll_deg=0.1, pitch_deg=0.2, yaw_deg=0.3, t_mono=0.5)
    assert a.yaw_deg == 0.3
    anc = AnchorPoint(name="A1", x_cm=0.0, y_cm=0.0, z_cm=0.0)
    assert anc.name == "A1"

    class MockPos(IPositionSource):
        def is_available(self) -> bool:
            return True

        def latest(self) -> Optional[PositionReading]:
            return PositionReading(7.0, 8.0, 9.0, 1.0)

    m = MockPos()
    assert isinstance(m, IPositionSource)
    assert m.is_available() is True
    r = m.latest()
    assert r is not None and r.x_cm == 7.0
    # 直接实例化抽象基类应失败
    try:
        IPositionSource()  # type: ignore[abstract]
    except TypeError:
        pass
    else:
        raise AssertionError("IPositionSource 应不可直接实例化")
    print("[P10-1] interfaces + Mock 子类 OK")


# =============================================================
# Case 2：LingxiaoImuSource 包装 bus
# =============================================================
class _FakeTracker:
    def __init__(self) -> None:
        self._snap: Optional[PathSnapshot] = None

    def feed(self, snap: PathSnapshot) -> None:
        self._snap = snap

    def snapshot(self) -> Optional[PathSnapshot]:
        return self._snap


class _FakeBus(QObject):
    def __init__(self) -> None:
        super().__init__()
        self.tracker = _FakeTracker()


def case_2_lingxiao_imu_source() -> None:
    bus = _FakeBus()
    src = LingxiaoImuSource(bus)
    assert src.is_available() is False, "无 snap 时应不可用"
    assert src.latest() is None
    assert src.latest_attitude() is None
    bus.tracker.feed(_snap(x=11.0, y=22.0, z=33.0))
    assert src.is_available() is True
    pos = src.latest()
    assert pos is not None
    assert (pos.x_cm, pos.y_cm, pos.z_cm) == (11.0, 22.0, 33.0)
    att = src.latest_attitude()
    assert att is not None
    assert (att.roll_deg, att.pitch_deg, att.yaw_deg) == (1.0, -2.0, 45.0)
    # as_attitude_source() 适配
    asrc = src.as_attitude_source()
    assert isinstance(asrc, IAttitudeSource)
    a2 = asrc.latest()
    assert a2 is not None and a2.yaw_deg == 45.0
    print("[P10-2] LingxiaoImuSource OK")


# =============================================================
# Case 3：视角预设
# =============================================================
def case_3_viewpoint_preset() -> None:
    _make_app()
    w = PathVisualizationPlaceholder()
    captured = []
    w.settings_changed.connect(lambda s: captured.append(s))
    # top
    w._on_viewpoint_preset("top")
    r = w._s["render"]
    assert r["camera_elevation"] >= 80.0, f"top elevation {r['camera_elevation']}"
    # side
    w._on_viewpoint_preset("side")
    r = w._s["render"]
    assert r["camera_elevation"] <= 15.0, f"side elevation {r['camera_elevation']}"
    # free
    w._on_viewpoint_preset("free")
    r = w._s["render"]
    assert 15.0 <= r["camera_elevation"] <= 60.0, f"free elevation {r['camera_elevation']}"
    # 未知名字 → 不变 + 不发射
    cnt = len(captured)
    w._on_viewpoint_preset("bogus")
    assert len(captured) == cnt, "未知预设不应触发 settings_changed"
    assert cnt == 3, f"应共发射 3 次 settings_changed，实 {cnt}"
    w.deleteLater()
    print("[P10-3] 视角预设 top/side/free OK")


# =============================================================
# Case 4：CSV 导出
# =============================================================
def case_4_export_csv() -> None:
    _make_app()
    w = PathVisualizationPlaceholder()
    snap = _snap(x=100.0, y=200.0, z=300.0, n_points=5)
    w._last_snap = snap
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "out.csv")
        n = w.export_path_csv(path)
        assert n == 5, f"应写 5 点，实 {n}"
        with open(path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        assert lines[0] == "t_mono,x_cm,y_cm,z_cm"
        assert len(lines) == 6, f"header+5 行，实 {len(lines)}"
        # 校验首行数据点
        fields = lines[1].split(",")
        assert abs(float(fields[1]) - 100.0) < 1e-3
    # 空 snap
    w._last_snap = None
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, "empty.csv")
        n = w.export_path_csv(path)
        assert n == 0
        with open(path, "r", encoding="utf-8") as f:
            content = f.read().splitlines()
        assert content == ["t_mono,x_cm,y_cm,z_cm"]
    w.deleteLater()
    print("[P10-4] export_path_csv OK")


# =============================================================
# Case 5：长稳定性微压（200Hz × 5s = 1000 帧）
# =============================================================
def case_5_long_stability_micro() -> None:
    _make_app()
    w = PathVisualizationPlaceholder()
    gc.collect()
    tracemalloc.start()
    base_cur, _ = tracemalloc.get_traced_memory()
    n_frames = 1000  # 200Hz × 5s
    t0 = time.perf_counter()
    for i in range(n_frames):
        s = _snap(x=float(i % 100), y=float((i * 2) % 100), z=float((i * 3) % 100), n_points=1)
        w.update_snapshot(s)
    dt = time.perf_counter() - t0
    gc.collect()
    cur, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    grow_mb = (cur - base_cur) / (1024 * 1024)
    assert grow_mb < 5.0, f"内存增长 {grow_mb:.2f}MB 超 5MB"
    rate = n_frames / dt if dt > 0 else float("inf")
    print(f"[P10-5] 长稳定性微压 OK frames={n_frames} {dt*1000:.1f}ms "
          f"rate={rate:.0f}fps 内存+{grow_mb:.2f}MB peak={peak/1024/1024:.2f}MB")
    w.deleteLater()


def main() -> int:
    cases = [
        case_1_interfaces_mock,
        case_2_lingxiao_imu_source,
        case_3_viewpoint_preset,
        case_4_export_csv,
        case_5_long_stability_micro,
    ]
    failed = []
    for c in cases:
        try:
            c()
        except Exception as exc:
            import traceback
            traceback.print_exc()
            failed.append((c.__name__, exc))
    if failed:
        print(f"\n[FAIL] {len(failed)}/{len(cases)} cases 失败")
        for name, exc in failed:
            print(f"  - {name}: {exc!r}")
        return 1
    print(f"\n[PASS] P10 烟雾测试全部通过 ({len(cases)}/{len(cases)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
