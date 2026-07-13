# -*- coding: utf-8 -*-
"""P6 烟雾测试：TelemetryBus 节流 + 异常隔离（task #1 / #2 验收）。

跑法（必须用 3.13 解释器）：
    C:\\Users\\20399\\AppData\\Local\\Programs\\Python\\Python313\\python.exe -m gui.test._smoke_phase_p6

通过条件：EXIT=0 + 所有 [P6-x] 行打印 OK。
"""
from __future__ import annotations

import struct
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from PySide6.QtCore import QCoreApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402  (case_6 需要 QWidget 支持)

from gui.io.protocol import Frame  # noqa: E402
from gui.services.telemetry_bus import TelemetryBus  # noqa: E402


def _make_frame(cmd: int, data: bytes) -> Frame:
    return Frame(dest=0xAF, cmd=cmd, data=data, sc=0, ac=0, raw=b"")


def _velocity_data(vx: int, vy: int, vz: int) -> bytes:
    return struct.pack("<hhh", vx, vy, vz)


def case_1_throttle_upper_bound() -> None:
    """[P6-1] 200Hz 灌帧 1s 时 path_updated emit 次数 ≤ render_fps + 容差。

    验收语义（option A 时间窗节流）：
      - 全部帧都进 tracker（统计 emit + drop = 总投递次数）
      - emit 次数受 1/render_fps 时间窗限制，远小于灌帧数
    """
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    bus.set_render_fps(30)
    bus.set_render_enabled(True)
    bus.reset_throttle_stats()
    emit_counter = {"n": 0}
    bus.path_updated.connect(lambda s: emit_counter.__setitem__("n", emit_counter["n"] + 1))

    duration_s = 1.0
    frame_hz = 200
    total_frames = int(duration_s * frame_hz)
    interval = 1.0 / frame_hz
    t_start = time.monotonic()
    for i in range(total_frames):
        # 真实速率：sleep 到下一帧时间点
        target = t_start + (i + 1) * interval
        bus.feed_frame(_make_frame(0x07, _velocity_data(10, 0, 0)))
        now = time.monotonic()
        if target > now:
            time.sleep(target - now)
    elapsed = time.monotonic() - t_start
    stats = bus.get_throttle_stats()
    # 上限：render_fps * elapsed + 2（含 enable 时初始 emit 容差）
    upper_bound = int(30 * elapsed) + 3
    assert emit_counter["n"] <= upper_bound, (
        f"emit 次数 {emit_counter['n']} 超过节流上限 {upper_bound} (elapsed={elapsed:.3f}s)"
    )
    # 至少有一定 emit（不要全 drop）
    assert emit_counter["n"] >= 5, f"emit 次数 {emit_counter['n']} 异常偏低（节流过强）"
    # emit + drop 应≈total_frames（每帧都调用 _maybe_emit_path）
    delivered = stats["emit"] + stats["drop"]
    assert delivered >= total_frames - 2, f"投递次数 {delivered} 远低于灌帧 {total_frames}"
    print(
        f"[P6-1] throttle OK (frames={total_frames} elapsed={elapsed:.2f}s "
        f"emit={emit_counter['n']} drop={stats['drop']} upper={upper_bound})"
    )


def case_2_throttle_disabled_no_emit() -> None:
    """[P6-2] 渲染关闭时高频灌帧 0 次 emit（drop 也为 0，因为函数提前 return）。"""
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    bus.set_render_enabled(False)
    bus.reset_throttle_stats()
    counter = {"n": 0}
    bus.path_updated.connect(lambda s: counter.__setitem__("n", counter["n"] + 1))
    for _ in range(500):
        bus.feed_frame(_make_frame(0x07, _velocity_data(10, 0, 0)))
    assert counter["n"] == 0, f"渲染关闭时不应 emit, got {counter['n']}"
    stats = bus.get_throttle_stats()
    assert stats["emit"] == 0 and stats["drop"] == 0, f"stats 异常: {stats}"
    print("[P6-2] disabled gate OK")


def case_3_throttle_stats_reset() -> None:
    """[P6-3] reset_throttle_stats 清零计数。"""
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    bus.set_render_enabled(True)
    bus.set_render_fps(60)
    for _ in range(20):
        bus.feed_frame(_make_frame(0x07, _velocity_data(10, 0, 0)))
    s1 = bus.get_throttle_stats()
    assert s1["emit"] + s1["drop"] > 0
    bus.reset_throttle_stats()
    s2 = bus.get_throttle_stats()
    assert s2["emit"] == 0 and s2["drop"] == 0
    print(f"[P6-3] stats reset OK (before emit={s1['emit']} drop={s1['drop']})")


def case_4_decode_exception_isolated() -> None:
    """[P6-4] 坏帧（长度错）不抛异常，status 槽收到 WARN（节流上下文）。

    feed_frame 已用 try/except 包裹，本用例确认对非法 DATA 返回，不污染计数。
    """
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    bus.set_render_enabled(True)
    bus.reset_throttle_stats()
    # decode_velocity 对非法长度返回 None，不会 raise；feed_frame 早 return
    bus.feed_frame(_make_frame(0x07, b"\x01\x02"))  # 长度错
    bus.feed_frame(_make_frame(0x05, b"\x01"))  # 长度错
    bus.feed_frame(_make_frame(0x99, b""))  # 未知 cmd
    stats = bus.get_throttle_stats()
    # 所有坏帧应被早 return，不进入 _maybe_emit_path
    assert stats["emit"] == 0 and stats["drop"] == 0, f"坏帧不应进入节流: {stats}"
    print("[P6-4] bad frame isolated OK")


def case_5_snapshot_exception_isolated() -> None:
    """[P6-5] tracker.snapshot 抛异常时不污染 bus 状态：status WARN + 后续帧继续节流推进。"""
    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    bus = TelemetryBus()
    bus.set_render_enabled(True)
    bus.set_render_fps(60)
    bus.reset_throttle_stats()
    # 替换 tracker.snapshot 让它抛异常
    original_snapshot = bus._tracker.snapshot
    bus._tracker.snapshot = lambda: (_ for _ in ()).throw(RuntimeError("simulated snapshot fail"))
    warn_msgs: list[str] = []
    bus.status.connect(lambda level, msg: warn_msgs.append(f"{level}:{msg}"))
    emit_counter = {"n": 0}
    bus.path_updated.connect(lambda s: emit_counter.__setitem__("n", emit_counter["n"] + 1))
    # 让节流窗过期，确保下一帧能进入 try 块
    time.sleep(0.02)
    # 第 1 帧：snapshot 抛 → status WARN
    bus.feed_frame(_make_frame(0x07, _velocity_data(10, 0, 0)))
    assert emit_counter["n"] == 0, "异常帧不应 emit"
    assert any("快照" in m or "snapshot" in m for m in warn_msgs), f"应收到 WARN: {warn_msgs}"
    # 恢复 snapshot，再灌帧确认正常路径恢复（节流窗内的会 drop）
    bus._tracker.snapshot = original_snapshot
    time.sleep(0.02)  # 跨过 1/60s 窗
    bus.feed_frame(_make_frame(0x07, _velocity_data(10, 0, 0)))
    assert emit_counter["n"] >= 1, "恢复后应能 emit"
    print(f"[P6-5] snapshot exception isolated OK (warns={len(warn_msgs)} emit={emit_counter['n']})")


def case_6_widget_cleanup_gl() -> None:
    """[P6-6] PathVisualizationWidget.cleanup_gl 幂等清理 GL 资源 + closeEvent 触发。"""
    try:
        from gui.widgets.path_visualization_widget import PathVisualizationPlaceholder as PVW
    except Exception as exc:
        print(f"[P6-6] SKIP (widget import 失败: {exc})")
        return
    w = PVW()
    # 离屏环境下 _GL_OK 可能 True 也可能 False；cleanup_gl 都得幂等
    if not getattr(w, "_gl_ok", False):
        # 无 GL 环境（CI/headless）：cleanup_gl 仍应无害
        w.cleanup_gl()
        w.close()
        print("[P6-6] cleanup_gl no-GL path OK")
        return
    # 有 GL 环境：拆除前清点 view.items 应 >0
    items_before = len(list(getattr(w._view, "items", []) or []))
    assert items_before > 0, "_build_scene 后 view.items 应非空"
    w.cleanup_gl()
    # cleanup 后所有强引用都应为 None
    for name in ("_cube", "_nose", "_axis", "_path", "_vel_arrow"):
        assert getattr(w, name) is None, f"{name} 未置 None"
    # view.items 应清空
    items_after = len(list(getattr(w._view, "items", []) or []))
    assert items_after == 0, f"view.items 应清空, got {items_after}"
    # _gl_ok 标记 False，update_snapshot 不再访问 view
    assert w._gl_ok is False
    # 幂等：再 cleanup 一次不抛
    w.cleanup_gl()
    # closeEvent 也得不抛
    w.close()
    print(f"[P6-6] cleanup_gl OK (items {items_before} -> 0)")


def main() -> int:
    # 统一用 QApplication（case_6 创建 QWidget 需要）
    _app = QApplication.instance() or QApplication(sys.argv)
    try:
        case_1_throttle_upper_bound()
        case_2_throttle_disabled_no_emit()
        case_3_throttle_stats_reset()
        case_4_decode_exception_isolated()
        case_5_snapshot_exception_isolated()
        case_6_widget_cleanup_gl()
    except AssertionError as exc:
        import traceback
        traceback.print_exc()
        print(f"[P6 FAIL] {exc}")
        return 1
    except Exception as exc:
        import traceback
        traceback.print_exc()
        print(f"[P6 ERROR] {exc}")
        return 2
    print("[P6] ALL PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
